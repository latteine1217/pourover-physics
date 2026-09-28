"""
benchmark.py — measured benchmark 載入與回歸檢查

What:
    提供 measured benchmark 的 state loader 與 regression gate suite。

Why:
    benchmark 是獨立於一般 sensitivity / grind analysis 的正式驗收流程，
    應有自己的模組邊界，而不是與其他分析工具混在同一檔。
"""

import csv
import dataclasses
from pathlib import Path

import numpy as np

from .fitting import (
    DEFAULT_MEASURED_FLOW_CSV,
    DEFAULT_MEASURED_FLOW_FIT_PLOT,
    DEFAULT_MEASURED_FLOW_FIT_SUMMARY,
    EXTRACTION_FIT_PARAMS,
    MEASUREMENT_SIGMA,
    SOLVER_FINE,
    WHITENESS_REPORT_KEYS,
    evaluate_measured_flow_fit,
    fit_measured_benchmark,
    thermal_series_summary,
)
from .measured_io import DRAINED_LOG_BIAS_NOTE, load_flow_profile_csv, _measured_setup_overrides
from .params import V60Params, RoastProfile


# 四個 measured case（F10，2026-09-27）：三個有錄影的 case（影片版 profile 由 loader 自動選用；
# kinu29 4:12 為 canonical）+ 無錄影的 kinu29 4:11（紀錄表，帶 `drained_log_bias_suspected`）。
DEFAULT_BENCHMARK_CASES: tuple[str, ...] = (
    "data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv",
    "data/kinu_27_light/4:12/kinu27_light_20g_flow_profile.csv",
    "data/kinu_28_light/4:20/kinu28_light_20g_flow_profile.csv",
    "data/kinu_29_light/4:11/kinu29_light_20g_flow_profile.csv",
)

# data_quality_flags → 揭露文字（benchmark CSV 的 `data_quality_notes` 欄）。
DATA_QUALITY_NOTES: dict[str, str] = {
    "drained_log_bias_suspected": DRAINED_LOG_BIAS_NOTE,
    # F11：分享壺探頭讀值不滿足瞬混節點的量測能量閉合（見 fitting.SERVER_ENERGY_CLOSURE_TOL_ML）。
    "server_probe_not_mixed_mean": (
        "分享壺溫探頭讀值與量測能量閉合不符（有效熱容中位數偏離容器常數 > 16 mL，"
        "且停流後無熱源仍回升數 °C）：壺內分層 / 探頭貼底讀冷層；時序不進 χ²，改用停流後單點杯溫"
    ),
}


def _summary_path_for(csv_path: str | Path) -> Path:
    """
    找出某個 flow case 對應的 calibrated summary 路徑。

    What: 先找同目錄的短 stem `*_flow_fit_summary.csv`；沒有才退回 legacy
          `*_flow_fit_*_summary.csv`；都沒有則由 flow CSV 檔名推導出短 stem。
    Why:  每個 case 的 calibrated state 必須來自**自己**的目錄；
          共用 canonical summary 會讓跨 case 比較變成比同一組參數（AUD）。
          短 stem 優先（F6，2026-09-24）：legacy stem
          `…_psd_clog_impactrelief_wetbedchi_180s` 內嵌的機制名在 F2b/F3 之後
          已不存在，且舊檔留在目錄裡時 glob 會先撞到舊模型的值。
    """
    case_dir = Path(csv_path).resolve().parent
    stem = Path(csv_path).name.replace("_flow_profile.csv", "")
    preferred = case_dir / f"{stem}_flow_fit_summary.csv"
    if preferred.exists():
        return preferred
    hits = sorted(case_dir.glob("*_flow_fit_summary.csv")) or \
        sorted(case_dir.glob("*_flow_fit_*_summary.csv"))
    if hits:
        return hits[0]
    return preferred


def _relative_to_project(path: Path) -> str:
    """把路徑表示為相對於 repo 根的形式（寫進版控 artifact 用）。"""
    root = Path(__file__).resolve().parents[1]
    try:
        return str(Path(path).resolve().relative_to(root))
    except ValueError:
        return str(path)


def _summary_float(summary: dict, key: str, default=None):
    """從 summary 讀浮點數；缺欄或空字串回 `default`（向後相容舊 summary）。"""
    raw = summary.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _load_measured_benchmark_state(
    csv_path: str | Path,
    summary_path: str | Path,
    *,
    refit: bool,
    verbose: bool,
) -> tuple[V60Params, dict]:
    """
    取得 measured benchmark 的目前校準狀態。

    What:
        優先讀取既有 summary CSV；若檔案不存在或指定 `refit=True`，
        則直接重跑正式 measured benchmark fitting。

        新 summary 欄位（`U_liquid_dripper_fit`、凍結的 `k_beta_prior_psd`、
        `extraction_fit_param_names/values`）會被讀入；缺欄時 fallback 到
        舊欄位（`lambda_liquid_dripper_fit`、`k_ext_*_fit`）或 params 預設。

    Why:
        benchmark / identifiability 需要共用同一組 calibrated baseline，
        但又不能每次都強迫重跑整套 fitting。**凍結的 prior anchor 必須從
        summary 讀回**，否則 reload 路徑會用 fit 後的 `k_beta` 反推出一個
        不同的 prior 中心，evaluate 的 χ² 就與 fit 當下的不是同一個函數。
    """
    flow_path = Path(csv_path) if csv_path is not None else Path(DEFAULT_MEASURED_FLOW_CSV)
    summary_csv = Path(summary_path) if summary_path is not None else Path(DEFAULT_MEASURED_FLOW_FIT_SUMMARY)

    if refit or not summary_csv.exists():
        # plot 路徑由該 case 的 summary 推導（F10）：舊版一律寫 canonical 的
        # DEFAULT_MEASURED_FLOW_FIT_PLOT，非 canonical case 重擬時會覆寫 canonical 的圖。
        plot_path = (Path(str(summary_csv)[: -len("_summary.csv")] + ".png")
                     if str(summary_csv).endswith("_summary.csv") else Path(DEFAULT_MEASURED_FLOW_FIT_PLOT))
        return fit_measured_benchmark(
            csv_path=flow_path,
            plot_path=plot_path,
            summary_path=summary_csv,
            verbose=verbose,
        )

    prof = load_flow_profile_csv(flow_path)
    meta = prof["meta"]
    with summary_csv.open("r", encoding="utf-8", newline="") as f:
        summary = next(csv.DictReader(f))

    roast_map = {
        "light": RoastProfile.LIGHT,
        "medium": RoastProfile.MEDIUM,
        "dark": RoastProfile.DARK,
    }
    roast_key = meta["roast"].strip().lower()
    profile = roast_map.get(roast_key)
    if profile is None:
        raise ValueError(f"未知烘焙度：{meta['roast']}")

    params_base = V60Params.for_roast(profile)
    measured_overrides = _measured_setup_overrides(meta, flow_csv_path=flow_path)
    measured_overrides["lambda_server_ambient"] = _summary_float(
        summary, "server_cooling_lambda_fit",
        _summary_float(summary, "lambda_server_ambient",
                       measured_overrides.get("lambda_server_ambient", 0.0)),
    )
    # 熱端：新欄位 `U_liquid_dripper_fit` 優先；缺欄才用舊的 λ（DEPRECATED 路徑）。
    u_fit = _summary_float(summary, "U_liquid_dripper_fit")
    if u_fit is not None and np.isfinite(u_fit) and u_fit > 0.0:
        measured_overrides["U_liquid_dripper_W_m2K"] = float(u_fit)
    else:
        lam_fit = _summary_float(summary, "lambda_liquid_dripper_fit")
        if lam_fit is not None:
            measured_overrides["lambda_liquid_dripper"] = float(lam_fit)

    params_fit_kwargs = dict(
        dose_g=float(meta["dose_g"]),
        h_bed=float(meta["bed_height_cm"]) / 100.0,
        T_brew=float(meta["brew_temp_C"]) + 273.15,
        k=float(summary["k_fit"]),
        k_beta=float(summary["k_beta_fit"]),
        # pref flow 讀 `*_fit`（fit 結束時模型實際用的值），`*_fixed` 只作缺欄 fallback。
        # 語意（F6d）：`*_fixed` 是 stage 4 **搜尋時**固定的 open_rate / tau_decay（設定值），
        # 不是模型狀態；stage 4 reject 時模型的 coeff = 0、open_rate = 預設 0。
        # 舊版優先讀 `*_fixed`，reject 時會把 open_rate 0.254 帶進一個 coeff = 0 的模型；
        # 那在物理上無作用，卻經 RK45 步長控制讓 canonical reload χ² 比 fit 高 8.05
        # （F6c §3.2）。`params.d_preferential_flow_dt` 的非作用態 gate 已從根上消除
        # 這條耦合，這裡改讀 `*_fit` 是讓 reload 的參數在語意上也等於 fit 的參數。
        pref_flow_coeff=_summary_float(summary, "pref_flow_coeff_fit", 0.0),
        pref_flow_open_rate=_summary_float(
            summary, "pref_flow_open_rate_fit",
            _summary_float(summary, "pref_flow_open_rate_fixed", 0.0)),
        pref_flow_tau_decay=_summary_float(
            summary, "pref_flow_tau_decay_fit",
            _summary_float(summary, "pref_flow_tau_decay_fixed", params_base.pref_flow_tau_decay)),
        sat_rel_perm_exp=_summary_float(summary, "sat_rel_perm_exp_fit", params_base.sat_rel_perm_exp),
    )

    # 兩條 reload 路徑都先確認欄位仍存在於 `V60Params`：萃取端與水力 closure 正在
    # 被 F2b/F3 重寫，舊 summary 記的欄位名隨時可能不再是模型的一部分。
    # 「讀舊 summary」是向後相容路徑，它**不該**因為模型演進而 crash。
    valid_fields = {f.name for f in dataclasses.fields(params_base)}
    dropped: list[str] = []

    def _set_if_valid(name: str, value: float) -> None:
        if name in valid_fields:
            params_fit_kwargs[name] = float(value)
        else:
            dropped.append(name)

    # `sat_rel_perm_residual`：F2b 之後預設為 0，因為殘餘飽和已由顯式狀態 `V_imm`
    # 攜帶。舊 summary 記的 0.18 若 reload 回來，同一份保水會被記兩次
    # （Corey 的 S_r 一次、V_imm 一次），模型行為與重擬當下不同。
    # 規則：params 預設為 0（= 新模型語意）時，忽略 summary 的非零舊值。
    sat_res_summary = _summary_float(summary, "sat_rel_perm_residual_fit")
    if float(params_base.sat_rel_perm_residual) == 0.0 and sat_res_summary not in (None, 0.0):
        if verbose:
            print(f"  [reload] 忽略舊 summary 的 sat_rel_perm_residual_fit="
                  f"{sat_res_summary:.3g}（F2b 後殘餘飽和由 V_imm 攜帶，預設 0）")
    elif sat_res_summary is not None:
        _set_if_valid("sat_rel_perm_residual", sat_res_summary)

    # F2b 的 `tau_wet_s`：summary 有就用，沒有就留 params 預設。
    tau_wet_summary = _summary_float(summary, "tau_wet_s_fit")
    if tau_wet_summary is not None and tau_wet_summary > 0.0:
        _set_if_valid("tau_wet_s", tau_wet_summary)

    # stage 7 參數：新格式（表驅動）優先，舊格式作 fallback。
    ext_names = str(summary.get("extraction_fit_param_names", "") or "").strip()
    ext_values = str(summary.get("extraction_fit_param_values", "") or "").strip()
    if ext_names and ext_values:
        for name, raw in zip(ext_names.split(";"), ext_values.split(";")):
            if name and raw:
                _set_if_valid(name, float(raw))
    else:
        # 舊 summary 的萃取欄位（`k_ext_*_coef_fit`）在 F3 之後已不是模型的一部分，
        # `_set_if_valid` 會把它們安全略過。
        # **`max_EY_fit` 刻意不再回讀**：F3 之後 `max_EY` 是凍結的 roast prior
        # （AGENTS.md §4.D）。canonical summary 記的 0.3725 超過文獻上限 0.32，
        # 是 stage 7 與已凍結的 `fast_fraction` 簡併後撞出來的（AUD-3）；
        # 把它讀回來等於讓一個超物理的可萃取總量繼續驅動 benchmark baseline。
        for legacy_key, field in (
            ("k_ext_slow_coef_fit", "k_ext_slow_coef"),
            ("k_ext_fast_coef_fit", "k_ext_fast_coef"),
        ):
            val = _summary_float(summary, legacy_key)
            if val is not None and val > 0.0:
                _set_if_valid(field, val)
    if dropped and verbose:
        print(f"  [reload] summary 記錄的欄位已不存在於目前的 V60Params，已略過："
              f"{', '.join(sorted(set(dropped)))}")

    params_fit = dataclasses.replace(params_base, **params_fit_kwargs, **measured_overrides)
    tau_lag_s = float(summary["tau_lag_s"])
    # 凍結的 PSD prior anchor：有就用 summary 的，沒有才回退到 params 自算值。
    k_beta_prior_frozen = _summary_float(summary, "k_beta_prior_psd")

    # dof 必須用**那一次 fit 實際的 live 參數數**，不是模組預設值。
    # Why（F6b）：`DEFAULT_LIVE_PARAM_COUNT` 是「全部 stage 都接受」時的上限，
    # 但 stage 4/5/6/7 各自可能 reject（canonical 這次就 reject 了 stage 4 與 7）。
    # 用預設值 reload 會把沒動過的參數也算成自由度，於是同一組參數在 fit 與
    # reload 兩條路徑上得到不同的 dof（實測 28 vs 27）與不同的 reduced χ²。
    # summary 的 `fit_live_param_names` 是這件事的單一來源。
    live_names = str(summary.get("fit_live_param_names", "") or "").strip()
    n_live_summary = len([x for x in live_names.split(";") if x]) if live_names else None
    eval_info = evaluate_measured_flow_fit(
        flow_path, params_fit, tau_lag_s=tau_lag_s,
        solver=SOLVER_FINE,
        k_beta_prior_psd=k_beta_prior_frozen,
        **({"n_fit_params": n_live_summary} if n_live_summary else {}),
    )
    info = {
        "csv_path": str(flow_path),
        "summary_path": str(summary_csv),
        "roast": roast_key,
        "sim_final": eval_info["sim"],
        "obs_layer": eval_info["obs_layer"],
        # χ² 與結構檢定
        "chi2": eval_info["chi2"],
        "chi2_data": eval_info["chi2_data"],
        "reduced_chi2": eval_info["reduced_chi2"],
        "dof": eval_info["dof"],
        "n_obs": eval_info["n_obs"],
        "chi2_terms": eval_info["chi2_terms"],
        "residual_lag1": eval_info["residual_lag1"],
        "durbin_watson": eval_info["durbin_watson"],
        "runs_z": eval_info["runs_z"],
        **{k: eval_info.get(k) for k in WHITENESS_REPORT_KEYS},
        "stop_operator": eval_info.get("stop_operator"),
        "total_loss": eval_info["chi2"],
        # 診斷指標
        "rmse_ml": eval_info["volume_rmse"],
        "velocity_rmse_mlps": eval_info["velocity_rmse"],
        "retention_rmse_ml": eval_info["retention_rmse_ml"],
        "retention_final_model_ml": eval_info["retention_final_model_ml"],
        "retention_final_obs_ml": eval_info["retention_final_obs_ml"],
        "retention_final_time_s": eval_info.get("retention_final_time_s"),
        "retention_pred_obs_ml": eval_info["retention_pred_obs_ml"],
        "water_balance_residual_ml": eval_info["water_balance_residual_ml"],
        "energy_residual_fraction": eval_info["energy_residual_fraction"],
        "clip_active_fraction": eval_info["clip_active_fraction"],
        # 觀測層
        "cup_stop_time_s": eval_info["cup_stop_time_s"],
        "cup_stop_time_error_s": eval_info["cup_stop_time_error_s"],
        "drain_time_error_s": eval_info["cup_stop_time_error_s"],   # deprecated 別名
        "stop_flow_time_s": eval_info["stop_flow_time_s"],
        "cup_temp_error_C": eval_info["cup_temp_error_C"],
        "final_cup_temp_C": eval_info["final_cup_temp_C"],
        "mixed_cup_temp_C": eval_info["mixed_cup_temp_C"],
        # F11：χ² 分項與熱時序（進 χ² 的點）摘要，與 fit summary 同一組鍵。
        **thermal_series_summary(eval_info),
        "U_liquid_dripper_fixed": "U_liquid_dripper_W_m2K" not in live_names.split(";"),
        "tau_lag_s": tau_lag_s,
        # F9：旗標取自預處理後的資料（與 χ² 同一份輸入）。
        "data_quality_flags": list(eval_info.get("data_quality_flags", prof.get("data_quality_flags", []))),
        "preprocess_corrections": eval_info.get("preprocess_corrections", ""),
        "max_pour_rate_g_s": eval_info.get("max_pour_rate_g_s"),
        "sigma_v_obs_ml": eval_info.get("sigma_v_obs_ml"),
        "n_fit_params": eval_info.get("n_fit_params"),
        "fit_live_param_names": live_names,
        # 參數
        "k_fit": float(params_fit.k),
        "k_beta_fit": float(params_fit.k_beta),
        "k_beta_prior_psd": (
            k_beta_prior_frozen
            if k_beta_prior_frozen is not None
            else float(getattr(params_fit, "k_beta_prior_psd", params_fit.k_beta))
        ),
        "U_liquid_dripper_fit": float(getattr(params_fit, "U_liquid_dripper_W_m2K", np.nan) or np.nan),
        "tau_wet_s_fit": float(getattr(params_fit, "tau_wet_s", np.nan)),
        "paper_holdup_final_ml": eval_info.get("paper_holdup_final_ml"),
        "axial_node_count": int(getattr(params_fit, "axial_node_count", 1)),
        "sat_rel_perm_residual_fit": float(getattr(params_fit, "sat_rel_perm_residual", np.nan)),
        "sat_rel_perm_exp_fit": float(getattr(params_fit, "sat_rel_perm_exp", np.nan)),
        "fit_preferential_flow": float(params_fit.pref_flow_coeff) > 0.0,
        "pref_flow_coeff_fit": float(params_fit.pref_flow_coeff),
        "pref_flow_open_rate_fit": float(params_fit.pref_flow_open_rate),
        "pref_flow_tau_decay_fit": float(params_fit.pref_flow_tau_decay),
        "pref_flow_open_rate_fixed": _summary_float(
            summary, "pref_flow_open_rate_fixed", float(params_fit.pref_flow_open_rate)),
        "pref_flow_tau_decay_fixed": _summary_float(
            summary, "pref_flow_tau_decay_fixed", float(params_fit.pref_flow_tau_decay)),
        "fit_server_cooling": str(summary.get("fit_server_cooling", "False")) in ("True", "true"),
        "server_cooling_lambda_fit": float(getattr(params_fit, "lambda_server_ambient", 0.0)),
        # 萃取
        "fit_extraction": str(summary.get("fit_extraction", "False")) in ("True", "true"),
        "stage7_skipped_reason": str(summary.get("stage7_skipped_reason", "") or ""),
        "extraction_fit_params": {
            name: float(getattr(params_fit, name))
            for name, *_ in EXTRACTION_FIT_PARAMS
            if hasattr(params_fit, name)
        },
        "k_ext_slow_coef_fit": float(getattr(params_fit, "k_ext_slow_coef", 0.0)),
        "k_ext_fast_coef_fit": float(getattr(params_fit, "k_ext_fast_coef", 0.0)),
        "max_EY_fit": float(getattr(params_fit, "max_EY", 0.0)),
        "final_tds_gl_obs": eval_info.get("final_tds_gl_obs"),
        "final_tds_gl_pred": eval_info.get("tds_pred_measured_denominator"),
        "tds_pred_measured_denominator": eval_info.get("tds_pred_measured_denominator"),
        "tds_error_gl": eval_info.get("tds_error_gl"),
        "v_out_final_ml": float(eval_info["sim"]["v_out_ml"][-1]),
        "v_out_obs_final_ml": float(eval_info["v_out_final_obs_ml"]),
        # ── 觀測序列（讓 reload 路徑也能直接重畫展示圖）──────────────────
        # Why: `viz.plot_fit_residuals` / `plot_retention_comparison` 與
        #      `plot_flow_fit_comparison` 只吃 info dict。沒有這幾個 key 時，
        #      「不重擬、只重畫」就辦不到，改一次圖面樣式就得重跑 50 分鐘的 fit。
        "t_obs_s": eval_info["t_obs_s"],
        "v_in_obs_ml": eval_info["v_in_obs_ml"],
        "v_out_obs_ml": eval_info["v_out_obs_ml"],
        "retained_obs_ml": eval_info["retained_obs_ml"],
        "q_obs_mlps": eval_info["q_obs_mlps"],
        "q_pred_obs_mlps": eval_info["q_pred_obs_mlps"],
        "v_pred_obs_ml": eval_info["v_pred_obs_ml"],
        "fit_mask": eval_info["fit_mask"],
        "model_v_out_ml": eval_info["obs_layer"]["v_cup_ml"],
        "model_q_out_mlps": eval_info["obs_layer"]["q_cup_mlps"],
        "bloom_end_s": float(eval_info["protocol"].bloom_end_time()),
        # F10：量測來源 / 時間基準、完整 1 s 序列與影片熱時序診斷（reload 也能重畫全部圖）。
        **eval_info["provenance"],
        **eval_info["full_series"],
    }
    return params_fit, info


def _default_gate_limits() -> dict:
    """
    benchmark regression gates（**工程驗收門檻，非物理正確性證明**）。

    What / Why 逐條：
      reduced_chi2_max = 3.0
          模型與量測的整體不一致度。1.0 = 殘差已在量測噪音量級；3.0 允許
          reduced-order 模型有結構誤差，但不允許差到「σ 要放大 2 倍才解釋得了」。
      retention_relative_max = 0.15
          保水是獨立的第二條質量觀測（poured − drained）。15% 對 ~50 mL 的保水
          約 7.5 mL，是濾紙 + 杯壁潤濕量級的合理容忍。
      durbin_watson_min = 1.0 / residual_lag1_max = 0.5（滿足其一即可）
          殘差必須接近白噪音。這一條是**真正的物理 gate**：DW = 0.17 代表殘差
          一路偏同一邊，此時壓低 RMSE 只是在描一條系統性偏掉的曲線。
      server_series_rmse_max_C = 2σ_Ts = 2.0 °C（F11；僅在有分享壺溫時序的 case 套用）
          進 χ² 的分享壺溫時序點（模型 − 量測）的 RMSE。用 RMSE ≤ 2σ 而不是「熱時序
          reduced χ² ≤ 3」：後者需要把 dof 拆給熱端與水力兩組參數，拆法沒有唯一答案；
          RMSE ≤ 2σ 與單點杯溫 gate（|err| ≤ 2σ）同一個語意，且與參數個數無關。
      cup_temp / tds 皆取 2σ（0.5 → 1.0 °C，0.72 → 1.44 g/L）
          2σ 是單一量測點的標準接受帶。舊 gate（3.5 °C、2.5 g/L）分別是 7σ 與
          3.5σ，形同沒有 gate。
      water_balance_residual_max = 0.05 mL / clip_active_fraction_max = 0.01
          數值合法性。守恆殘差或溫度 clip 一旦顯著，跑出來的就不是這組方程的解，
          其他指標好看與否都沒有意義。

    這些是「這次改動有沒有把東西弄壞」的回歸防線，不是「模型是對的」的證明。
    通過全部 gate 只代表模型在這四個 case 上與量測不一致到可接受程度；
    物理正確性由 closure 的推導、守恆律測試與 identifiability 分析負責。
    """
    return {
        "reduced_chi2_max": 3.0,
        "retention_relative_max": 0.15,
        "durbin_watson_min": 1.0,
        "residual_lag1_max": 0.5,
        "cup_temp_error_abs_max": 2.0 * MEASUREMENT_SIGMA["cup_temp_C"],
        "server_series_rmse_max_C": 2.0 * MEASUREMENT_SIGMA["server_temp_series_C"],
        "tds_error_abs_max": 2.0 * MEASUREMENT_SIGMA["tds_gl"],
        "water_balance_residual_max_ml": 0.05,
        "clip_active_fraction_max": 0.01,
        # 診斷用（不 gate）：V_RMSE 相對值的分母改為**量測**末值，不再是模型 V_out
        "volume_rmse_relative_report_only": True,
    }


def _evaluate_case(
    csv_path: str | Path,
    summary_path: str | Path | None,
    *,
    refit: bool,
    verbose: bool,
    limits: dict,
) -> dict:
    """對單一 case 載入 calibrated state、套 gates，回傳一列結果。"""
    flow_path = Path(csv_path)
    summary_csv = Path(summary_path) if summary_path is not None else _summary_path_for(flow_path)
    params_fit, info = _load_measured_benchmark_state(
        flow_path, summary_csv, refit=refit, verbose=verbose
    )

    # V_RMSE 相對值：分母用**量測**末值（舊版用模型 v_out，模型偏大時分母跟著
    # 變大，gate 反而變鬆——這是在用被檢查的量去定義檢查標準）。
    v_out_obs_final = float(info.get("v_out_obs_final_ml", 0.0))
    if v_out_obs_final <= 0:
        v_out_obs_final = 1.0
    rmse_relative = float(info["rmse_ml"]) / v_out_obs_final

    ret_obs = info.get("retention_final_obs_ml")
    ret_model = info.get("retention_final_model_ml")
    # 末段保水 gate：**非獨立觀測**（量測端的 `retained_mass_g` 逐列等於
    # `poured − drained`，見 `measured_io.load_flow_profile_csv`），保水時序自
    # F6b 起已移出 χ²。這條 gate 留著的理由是它仍是有用的 sanity check——
    # 「模型末了在床裡留了多少水」與 V_out 的累積誤差是不同的讀法：
    # V_out 對得上但保水差很多，代表水在模型裡被放在錯的地方。
    # 但它**不是**獨立於 V_out 的第二次驗證，報告不得把它當成交叉驗證。
    #
    # 量測保水必須是**正值且非微量**才拿來 gate：
    # kinu29 4:12 的末列保水為 −7.2 g（drained 310 mL > poured − retained），
    # 這是量測本身的不一致，不是模型誤差，拿它當分母只會得到 690% 這種數字。
    # F6b（2026-09-24）：該列已在 CSV 標為 `use_for_fit=0`，而
    # `retention_final_*` 改取**最後一個進 fit 的列**，因此這個 gate 現在拿到的
    # 是 t = 125 s 的 2.8 mL。它仍然小於 5.0 → gate 照樣跳過。這個保護留著：
    # 它擋的是「量測保水本身不可用」這一類情況，不只擋負值。
    retention_applicable = ret_obs is not None and float(ret_obs) >= 5.0
    retention_relative = (
        abs(float(ret_model) - float(ret_obs)) / abs(float(ret_obs))
        if retention_applicable else float("nan")
    )

    srv_rmse = info.get("server_series_rmse_C")
    dw = float(info.get("durbin_watson", float("nan")))
    lag1 = float(info.get("residual_lag1", float("nan")))
    tds_error = info.get("tds_error_gl")
    cup_err = info.get("cup_temp_error_C")

    checks = {
        "reduced_chi2_pass": float(info["reduced_chi2"]) <= limits["reduced_chi2_max"],
        "retention_pass": (
            (not retention_applicable)
            or retention_relative <= limits["retention_relative_max"]
        ),
        "residual_whiteness_pass": (
            (np.isfinite(dw) and dw >= limits["durbin_watson_min"])
            or (np.isfinite(lag1) and lag1 <= limits["residual_lag1_max"])
        ),
        "cup_temp_error_pass": (
            cup_err is None or abs(float(cup_err)) <= limits["cup_temp_error_abs_max"]
        ),
        # F11：沒有分享壺溫時序（紀錄表 case）→ 不適用，視為通過（同 retention gate 的處理）。
        "server_series_pass": (
            srv_rmse is None or float(srv_rmse) <= limits["server_series_rmse_max_C"]
        ),
        "tds_error_pass": (
            tds_error is None or abs(float(tds_error)) <= limits["tds_error_abs_max"]
        ),
        "water_balance_pass": (
            float(info.get("water_balance_residual_ml", 0.0)) <= limits["water_balance_residual_max_ml"]
        ),
        "clip_pass": (
            float(info.get("clip_active_fraction", 0.0)) <= limits["clip_active_fraction_max"]
        ),
    }
    overall_pass = bool(all(checks.values()))

    row = {
        "case_id": f"{Path(flow_path).parent.parent.name}_{Path(flow_path).parent.name}",
        "status": "PASS" if overall_pass else "FAIL",
        "csv_path": str(flow_path),
        # 相對路徑：這份 CSV 會進版控，絕對路徑會把本機 home 目錄寫進 artifact
        "summary_path": _relative_to_project(summary_csv),
        # 量測紀錄品質旗標（F6b）：非空代表該 case 的校準值受量測紀錄限制，
        # 不得當成獨立的交叉驗證結果（見 measured_io.flow_profile_quality_flags）。
        "data_quality_flags": ";".join(info.get("data_quality_flags", []) or []),
        "data_quality_notes": " | ".join(
            DATA_QUALITY_NOTES[f] for f in (info.get("data_quality_flags", []) or []) if f in DATA_QUALITY_NOTES),
        # F10：量測來源與時間基準。
        "profile_source": info.get("profile_source", "log"),
        "video_id": info.get("video_id", ""),
        "time_base": info.get("time_base", ""),
        "scale_timer_rate_applied": info.get("scale_timer_rate_applied"),
        "reading_time_sigma_s": info.get("reading_time_sigma_s"),
        "fit_stride_s": info.get("fit_stride_s"),
        # F9 量測預處理：修正紀錄（空 = 無修正）與推得的注水率上限。
        "preprocess_corrections": info.get("preprocess_corrections", ""),
        "max_pour_rate_g_s": info.get("max_pour_rate_g_s"),
        # 參數
        "k_fit": float(params_fit.k),
        "k_beta_fit": float(params_fit.k_beta),
        "k_beta_prior_psd": info.get("k_beta_prior_psd"),
        "tau_lag_s": float(info["tau_lag_s"]),
        # F6b：`sat_rel_perm_exp` 自 F6b 起是 stage 1/2 的 live 參數，
        # benchmark 列必須帶出來，否則四 case 的比較表看不到這個自由度。
        "sat_rel_perm_exp_fit": info.get("sat_rel_perm_exp_fit"),
        "U_liquid_dripper_fit": info.get("U_liquid_dripper_fit"),
        "tau_wet_s_fit": info.get("tau_wet_s_fit"),
        "server_cooling_lambda_fit": info.get("server_cooling_lambda_fit"),
        "pref_flow_coeff_fit": info.get("pref_flow_coeff_fit"),
        # χ² 與結構
        "chi2": info["chi2"],
        "chi2_data": info["chi2_data"],
        "reduced_chi2": info["reduced_chi2"],
        "dof": info["dof"],
        "n_obs": info["n_obs"],
        "residual_lag1": lag1,
        "durbin_watson": dw,
        "runs_z": info.get("runs_z"),
        # F12a：gate 以標準化殘差判定；以下為附報（σ-class ≤ 6 mL 子序列、舊 mL 殘差），不 gate。
        **{k: info.get(k) for k in WHITENESS_REPORT_KEYS},
        # 診斷
        "rmse_ml": float(info["rmse_ml"]),
        "rmse_relative": rmse_relative,
        "v_out_obs_final_ml": v_out_obs_final,
        "v_out_model_final_ml": info.get("v_out_final_ml"),
        "velocity_rmse_mlps": info.get("velocity_rmse_mlps"),
        "retention_rmse_ml": info.get("retention_rmse_ml"),
        "retention_final_model_ml": ret_model,
        "retention_final_obs_ml": ret_obs,
        "paper_holdup_final_ml": info.get("paper_holdup_final_ml"),
        "retention_relative": retention_relative,
        "retention_gate_applicable": retention_applicable,
        "cup_stop_time_error_s": info.get("cup_stop_time_error_s"),
        "drain_time_error_s": info.get("cup_stop_time_error_s"),   # deprecated 別名
        # F12a：停流算子類型與出水口熱電偶斷流診斷（不 gate）
        "stop_operator": info.get("stop_operator"),
        "stop_flow_time_s": info.get("stop_flow_time_s"),
        "dripper_removed_time_s": info.get("dripper_removed_time_s"),
        "thermo_break_s": info.get("thermo_break_s"),
        "model_q_at_thermo_break_mlps": info.get("model_q_at_thermo_break_mlps"),
        "cup_temp_error_C": cup_err,
        "final_coffee_temp_source": info.get("final_coffee_temp_source", ""),
        # F10 影片熱時序診斷（不進 χ²、不 gate）
        "thermal_video_server_rmse_C": info.get("thermal_video_server_rmse_C"),
        "thermal_video_server_bias_C": info.get("thermal_video_server_bias_C"),
        "thermal_video_outflow_rmse_C": info.get("thermal_video_outflow_rmse_C"),
        "thermal_video_outflow_bias_C": info.get("thermal_video_outflow_bias_C"),
        # F11 樣本外檢查：連續出流窗的出水口溫（不進 χ²）
        "thermal_video_outflow_gated_rmse_C": info.get("thermal_video_outflow_gated_rmse_C"),
        "thermal_video_outflow_gated_bias_C": info.get("thermal_video_outflow_gated_bias_C"),
        # F11 熱時序進 χ²：分項、點數、V_immersion、偏差（server_series_pass 的依據）。
        "U_liquid_dripper_fixed": info.get("U_liquid_dripper_fixed"),
        "chi2_term_volume": info.get("chi2_term_volume"),
        "chi2_term_stop_time": info.get("chi2_term_stop_time"),
        "chi2_term_cup_temp": info.get("chi2_term_cup_temp"),
        "chi2_term_extracted_mass": info.get("chi2_term_extracted_mass"),
        "chi2_term_server_temp_series": info.get("chi2_term_server_temp_series"),
        "chi2_term_outflow_temp_series": info.get("chi2_term_outflow_temp_series"),
        "server_series_n": info.get("server_series_n"),
        "server_series_rmse_C": srv_rmse,
        "server_series_bias_C": info.get("server_series_bias_C"),
        "outflow_series_n": info.get("outflow_series_n"),
        "v_immersion_ml": info.get("v_immersion_ml"),
        "server_series_min_v_ml": info.get("server_series_min_v_ml"),
        "final_tds_gl_obs": info.get("final_tds_gl_obs"),
        "tds_pred_measured_denominator": info.get("tds_pred_measured_denominator"),
        "tds_error_gl": tds_error,
        "water_balance_residual_ml": info.get("water_balance_residual_ml"),
        "energy_residual_fraction": info.get("energy_residual_fraction"),
        "clip_active_fraction": info.get("clip_active_fraction"),
        "stage7_skipped_reason": info.get("stage7_skipped_reason", ""),
        # gate 結果
        **checks,
    }
    return {"params_fit": params_fit, "info": info, "row": row, "checks": checks}


def run_benchmark_suite(
    csv_path: str | Path | None = None,
    summary_path: str | Path | None = None,
    benchmark_csv_path: str | Path = "data/benchmark_suite_summary.csv",
    *,
    cases: list[str | Path] | None = None,
    refit: bool = True,
    verbose: bool = True,
    thresholds: dict | None = None,
) -> dict:
    """
    執行 benchmark / regression suite（可對多個 case 逐一跑）。

    What:
        對 `cases` 中的每個 measured case 載入（或重擬）calibrated state，
        套用 `_default_gate_limits()` 的 gates，輸出一列一 case 的 CSV。
        `cases=None` 時：若顯式給了 `csv_path` 就只跑該 case，否則跑
        `DEFAULT_BENCHMARK_CASES` 四個。

    Why:
        模型越複雜，越不能靠肉眼看圖判斷「這次是否真的比較好」。
        單一 case 的 gate 又容易被 case-specific 的調整騙過去——四個 case 一起跑
        才看得出某個改動是普遍成立還是只對 canonical case 有效。

    **這是工程驗收門檻，不是物理正確性證明**：見 `_default_gate_limits` docstring。
    """
    limits = _default_gate_limits()
    if thresholds is not None:
        limits.update(thresholds)

    if cases is not None:
        case_specs = [(Path(c), None) for c in cases]
    elif csv_path is not None:
        case_specs = [(Path(csv_path), Path(summary_path) if summary_path else None)]
    else:
        case_specs = [(Path(c), None) for c in DEFAULT_BENCHMARK_CASES]

    results = []
    for case_csv, case_summary in case_specs:
        if not case_csv.exists():
            if verbose:
                print(f"  [skip] 找不到 case CSV：{case_csv}")
            continue
        results.append(
            _evaluate_case(case_csv, case_summary, refit=refit, verbose=verbose, limits=limits)
        )
    if not results:
        raise FileNotFoundError("沒有任何可用的 benchmark case")

    rows = [r["row"] for r in results]
    bench_path = Path(benchmark_csv_path)
    bench_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with bench_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print("\n=== Benchmark Suite ===")
    print(f"  gates: reduced_chi2 <= {limits['reduced_chi2_max']:.1f} | "
          f"retention <= {limits['retention_relative_max']*100:.0f}% | "
          f"DW >= {limits['durbin_watson_min']:.1f} or lag1 <= {limits['residual_lag1_max']:.1f} | "
          f"|cup dT| <= {limits['cup_temp_error_abs_max']:.2f} degC | "
          f"server T(t) RMSE <= {limits['server_series_rmse_max_C']:.1f} degC | "
          f"|dTDS| <= {limits['tds_error_abs_max']:.2f} g/L | "
          f"water <= {limits['water_balance_residual_max_ml']:.2f} mL | "
          f"clip <= {limits['clip_active_fraction_max']*100:.0f}%")
    for row in rows:
        print(f"\n  --- {row['case_id']} : {row['status']} ---")
        print(f"    reduced chi2 : {row['reduced_chi2']:.2f}  (chi2 {row['chi2']:.1f}, dof {row['dof']})"
              f"   {'OK' if row['reduced_chi2_pass'] else 'FAIL'}")
        print(f"    residual     : DW {row['durbin_watson']:.2f}, lag1 {row['residual_lag1']:+.3f}, "
              f"runs z {row['runs_z']:+.2f} (standardized r/sigma)   "
              f"{'OK' if row['residual_whiteness_pass'] else 'FAIL'}")
        print(f"    [report]     : sigma-class <= 6 mL subset (n {row['n_resid_lowsigma']}): "
              f"DW {row['durbin_watson_lowsigma']:.2f}, lag1 {row['residual_lag1_lowsigma']:+.3f} | "
              f"unweighted mL: DW {row['durbin_watson_unweighted']:.2f}, "
              f"lag1 {row['residual_lag1_unweighted']:+.3f}   (not gated)")
        if row["retention_final_obs_ml"] is not None:
            rel = (f"{row['retention_relative']*100:.1f}%"
                   if row["retention_gate_applicable"] else "n/a (obs <= 0)")
            print(f"    retention    : model {row['retention_final_model_ml']:.1f} vs "
                  f"obs {row['retention_final_obs_ml']:.1f} mL ({rel})   "
                  f"{'OK' if row['retention_pass'] else 'FAIL'}")
        if row["cup_temp_error_C"] is not None:
            print(f"    cup temp     : {row['cup_temp_error_C']:+.2f} degC   "
                  f"{'OK' if row['cup_temp_error_pass'] else 'FAIL'}")
        if row["server_series_rmse_C"] is not None:
            print(f"    server T(t)  : RMSE {row['server_series_rmse_C']:.2f} degC "
                  f"(bias {row['server_series_bias_C']:+.2f}, n {row['server_series_n']}, "
                  f"V >= {row['server_series_min_v_ml']:.0f} mL, V_imm {row['v_immersion_ml']:.1f} mL)   "
                  f"{'OK' if row['server_series_pass'] else 'FAIL'}")
        if row["tds_error_gl"] is not None:
            print(f"    TDS          : {row['tds_error_gl']:+.2f} g/L (measured denominator)   "
                  f"{'OK' if row['tds_error_pass'] else 'FAIL'}")
        print(f"    conservation : water {row['water_balance_residual_ml']:.2e} mL, "
              f"clip {row['clip_active_fraction']*100:.2f}%   "
              f"{'OK' if (row['water_balance_pass'] and row['clip_pass']) else 'FAIL'}")
        print(f"    [diagnostic] V_RMSE {row['rmse_ml']:.2f} mL = "
              f"{row['rmse_relative']*100:.2f}% of measured V_out; "
              f"q_RMSE {row['velocity_rmse_mlps']:.3f} mL/s; "
              f"cup stop {row['cup_stop_time_error_s']:+.2f} s ({row['stop_operator']} operator)")
        if row.get("thermo_break_s") is not None:
            rm = row.get("dripper_removed_time_s")
            print(f"    [diagnostic] outflow thermocouple break {row['thermo_break_s']:.1f} s "
                  f"(model q_cup {row['model_q_at_thermo_break_mlps']:.2f} mL/s); "
                  f"dripper removed {'n/a' if rm is None else f'{rm:.1f} s'}")
    overall = all(r["row"]["status"] == "PASS" for r in results)
    print(f"\n  overall     : {'PASS' if overall else 'FAIL'}")
    print(f"  summary csv : {bench_path}")

    return {
        # 單 case 時保留舊的扁平鍵，方便既有呼叫端
        "params_fit": results[0]["params_fit"],
        "info": results[0]["info"],
        "row": rows[0],
        "rows": rows,
        "results": results,
        "overall_pass": overall,
        "thresholds": limits,
        "benchmark_csv_path": str(bench_path),
    }
