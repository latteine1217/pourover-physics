"""
showcase_state.py — 展示頁與 compare_* 的基準狀態載入

What:
    集中管理 showcase / compare 圖使用的 calibrated baseline、
    預設量測注水曲線，以及由 baseline 衍生出的 grind / correction scenario。

Why:
    這些邏輯屬於「展示狀態選擇」，不是視覺化本身。
    把它們從 viz.py 抽離後，畫圖函式就能回到純輸入 -> 純輸出。
"""

import csv
import dataclasses
from dataclasses import replace
from pathlib import Path

from .measured_io import _measured_setup_overrides, load_flow_profile_csv
from .params import PourProtocol, RoastProfile, V60Params
from .preprocess import preprocess_flow_profile


def data_dir() -> Path:
    """回傳專案內 data 目錄。"""
    return Path(__file__).resolve().parents[1] / "data"


def canonical_case_dir() -> Path:
    """
    展示基準 case 的目錄（F10，2026-09-27 起 kinu29 4:12）。

    Why: 必須與 `fitting.DEFAULT_MEASURED_FLOW_CSV` 同一個 case（此處不 import fitting，
         以免 fitting → viz → showcase_state → fitting 成環；`tests` 釘住兩者一致）。
         4:12 有沖煮錄影，flow profile 由 loader 自動改讀影片版（見
         `measured_io.resolve_flow_profile_path`）。
    """
    return data_dir() / "kinu_29_light" / "4:12"


CANONICAL_FLOW_CSV_NAME = "kinu29_light_20g_flow_profile.csv"


def latest_protocol(protocol: PourProtocol | None = None) -> PourProtocol:
    """
    回傳展示頁預設使用的注水協議。

    What:
        優先使用 measured `V_in(t)`；若缺檔則退回標準 V60 recipe。

    Why:
        compare 圖應優先圍繞目前正式 benchmark case，而不是默默退回舊預設。
    """
    if protocol is not None:
        return protocol
    # F10：改用 canonical case 的量測（影片版優先）；舊版讀頂層 legacy 副本
    # `data/kinu29_light_20g_flow_profile.csv`（= kinu29 4:11 紀錄表）。
    flow_csv = canonical_case_dir() / CANONICAL_FLOW_CSV_NAME
    if flow_csv.exists():
        # F9：與 fitting 同一份量測預處理（注水率上限重建），否則展示用的注水協議
        # 與校準當下的協議不同，calibrated 參數就不是這條注水曲線的解。
        obs = preprocess_flow_profile(load_flow_profile_csv(flow_csv))
        return PourProtocol.from_cumulative_profile(obs["pour_knots"])
    return PourProtocol.standard_v60()


def latest_calibrated_params() -> V60Params:
    """
    回傳目前專案展示用的 calibrated baseline。

    What:
        以 canonical case（F10 起 kinu29 4:12）的量測 meta 建立 roast-aware 基底
        （`RoastProfile` → `max_EY` 等凍結 prior），套上 measured PSD bins 與
        量測硬體設定，再從 calibrated summary 讀回 fit 出來的 closure 參數。

    Why:
        compare_*、README 與首頁必須引用同一組展示基準，避免各自硬編碼。
        與 `benchmark._load_measured_benchmark_state` 同一套回讀規則
        （F6，2026-09-24）：舊版只讀 `k / k_beta / λ_liquid_dripper / max_EY /
        k_ext_*`，在 F2b/F3/F4 之後會讓首頁靜默退回熱端與潤濕的預設值，
        且 `max_EY_fit` / `k_ext_*_fit` 早已不是模型欄位（AGENTS.md §2.4、§7）。

        回讀白名單刻意只含「這次 fit 真的動過的參數」：
        `k`、`k_beta`、`tau_lag`（由呼叫端使用）、`pref_flow_*`、
        `U_liquid_dripper_W_m2K`、`lambda_server_ambient`、`tau_wet_s`、
        `sat_rel_perm_exp`（F6b 起為 live 參數），
        以及 `extraction_fit_param_names/values` 表驅動的萃取參數（目前 `tau_tort`）。
        **不讀** `max_EY_fit` / `k_ext_*_fit` / `lambda_liquid_dripper_fit`
        （凍結 prior 或 DEPRECATED 欄位）。
    """
    # canonical case 的 PSD 與 calibrated summary 必須來自同一個資料夾：
    # 2026-05 移除 CANONICAL_HIGH_RES_PSD_OVERRIDES 後，canonical baseline 走
    # per-case sibling PSD（27.4 μm/px），頂層 `kinu29_psd_bins.csv` 僅作 fallback
    # （58 μm/px 的 legacy 低倍率掃描）。
    case_dir = canonical_case_dir()
    flow_csv = case_dir / CANONICAL_FLOW_CSV_NAME
    bins_csv = case_dir / "kinu29_psd_bins.csv"
    if not bins_csv.exists():
        bins_csv = data_dir() / "kinu29_psd_bins.csv"
    summary_csv = case_dir / "kinu29_light_20g_flow_fit_summary.csv"
    if not bins_csv.exists():
        return V60Params()

    summary: dict = {}
    if summary_csv.exists():
        with summary_csv.open("r", encoding="utf-8", newline="") as f:
            summary = next(csv.DictReader(f))

    # ── roast-aware 基底：與 benchmark / fitting 同一條路徑 ─────────────────
    roast_map = {
        "light": RoastProfile.LIGHT,
        "medium": RoastProfile.MEDIUM,
        "dark": RoastProfile.DARK,
    }
    base = V60Params()
    overrides: dict = {"psd_bins_csv_path": str(bins_csv)}
    if flow_csv.exists():
        meta = load_flow_profile_csv(flow_csv)["meta"]
        profile = roast_map.get(str(meta.get("roast", "")).strip().lower())
        if profile is not None:
            base = V60Params.for_roast(profile)
        overrides.update(_measured_setup_overrides(meta, flow_csv_path=flow_csv))
        overrides.update(
            dose_g=float(meta["dose_g"]),
            h_bed=float(meta["bed_height_cm"]) / 100.0,
            T_brew=float(meta["brew_temp_C"]) + 273.15,
        )
    else:
        # 缺量測 CSV 時退回 §11 的展示基準（20 g / 5.3 cm / 23 degC）。
        overrides.update(h_bed=0.053, T_amb=23.0 + 273.15)

    valid_fields = {f.name for f in dataclasses.fields(base)}

    def _num(key: str):
        raw = summary.get(key)
        if raw is None or str(raw).strip() == "":
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _set(field: str, key: str, *, positive: bool = False) -> None:
        val = _num(key)
        if val is None or field not in valid_fields:
            return
        if positive and not val > 0.0:
            return
        overrides[field] = float(val)

    _set("k", "k_fit", positive=True)
    _set("k_beta", "k_beta_fit")
    _set("pref_flow_coeff", "pref_flow_coeff_fit")
    for field, keys in (
        # F6e：與 benchmark 一致，優先讀 `*_fit`（模型實際狀態）；`*_fixed` 只是 stage 4 搜尋設定值。
        ("pref_flow_open_rate", ("pref_flow_open_rate_fit", "pref_flow_open_rate_fixed")),
        ("pref_flow_tau_decay", ("pref_flow_tau_decay_fit", "pref_flow_tau_decay_fixed")),
    ):
        for key in keys:
            if _num(key) is not None:
                _set(field, key)
                break
    _set("U_liquid_dripper_W_m2K", "U_liquid_dripper_fit", positive=True)
    _set("lambda_server_ambient", "server_cooling_lambda_fit")
    _set("tau_wet_s", "tau_wet_s_fit", positive=True)
    # F6b：`sat_rel_perm_exp` 自 F6b 起是 stage 1/2 的 live 參數，展示狀態必須
    # 跟著回讀，否則 showcase 會用 params 預設 3.0 去畫一張與 calibrated summary
    # 不同的模型（正是 F4 §9.1 標記過的那種漂移）。
    _set("sat_rel_perm_exp", "sat_rel_perm_exp_fit", positive=True)

    # 萃取端：表驅動欄位（F4 §3），F3 改表後自動跟上。
    names = str(summary.get("extraction_fit_param_names", "") or "").strip()
    values = str(summary.get("extraction_fit_param_values", "") or "").strip()
    if names and values:
        for name, raw in zip(names.split(";"), values.split(";")):
            name, raw = name.strip(), raw.strip()
            if not name or not raw or name not in valid_fields:
                continue
            try:
                overrides[name] = float(raw)
            except ValueError:
                continue

    return replace(base, **overrides)


def scaled_grind_params(scale: float) -> V60Params:
    """
    用同一份 measured PSD 做等比縮放，生成 coarse / medium / fine。

    What: 以顯式 `psd_diameter_scale` 平移整條 measured PSD，並讓 `k` 依
          Kozeny-Carman 的 d² 關係同步縮放（尺度錨點為 Sauter d32）。
    Why:  舊實作透過覆寫 `D10_measured_m` 間接驅動縮放，把 resolution-bounded
          的 number-based D10 當成研磨度旋鈕；現在縮放倍率是直接輸入，
          而 d32 由縮放後的 PSD 自然得出。
    """
    base = latest_calibrated_params()
    ratio = max(float(scale), 1e-9)
    trial = replace(
        base,
        psd_diameter_scale=float(base.psd_diameter_scale) * ratio,
        k=float(base.k) * ratio ** 2,
    )
    base_prior = max(float(base.k_beta_prior_from_psd()), 1e-9)
    trial_prior = max(float(trial.k_beta_prior_from_psd()), 1e-9)
    scaled_k_beta = float(base.k_beta) * trial_prior / base_prior
    return replace(trial, k_beta=scaled_k_beta)


def latest_grind_configs() -> dict[str, V60Params]:
    """以 calibrated baseline 為中心建立最新 grind 對比。"""
    return {
        "Coarse": scaled_grind_params(1.35),
        "Medium": scaled_grind_params(1.00),
        "Fine": scaled_grind_params(0.78),
    }


def latest_correction_configs() -> dict[str, V60Params]:
    """用最新模型拆出 correction scenario，而不是回到舊 closure。"""
    base = latest_calibrated_params()
    no_clog = replace(base, k_beta=0.0, throat_relief_gain=0.0)
    clog_only = replace(base, throat_relief_gain=0.0)
    no_bypass = replace(base, psi=0.0, psi_beta=0.0)
    return {
        "No clogging": no_clog,
        "PSD clogging": clog_only,
        "No bypass": no_bypass,
        "Full model": base,
    }
