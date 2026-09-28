"""
preprocess.py — 量測 flow profile 的預處理層（F9，2026-09-26）

What:
    在 `load_flow_profile_csv()`（Class A raw，逐字讀入、不改值）與擬合之間，
    對**已知的資料收集誤差**做可追溯的修正，並把讀取時刻的不確定度轉成
    V_out 的逐點量測 σ。每一筆修正都寫進 `corrections`（原值、新值、理由），
    raw CSV 與 `load_flow_profile_csv()` 的輸出都不被改動。

Why:
    量測紀錄是照實記下的（例：kinu29 4:11 第四注 74 → 75 s 記 29.3 g），
    但它同時帶著資料收集誤差：人工讀秤與讀量筒有時間戳誤差、秤有漂移。
    直接拿 raw 擬合，模型會被要求在 1 s 內吞下超過手沖壺物理上限的注水，
    殘差裡混進的是紀錄誤差而不是床層物理。預處理把這類誤差在**進模型前**
    以明文規則處理，而不是事後讓模型參數去吸收（AGENTS.md §2.3/§2.4）。

規則（每條的常數見 `measured_io` 的 F9 / F10 區段）：
    0. 時間基準（F10）：紀錄表的 `time_s` 是秤計時器秒（`time_base = "scale_timer_s"`），
       換算真實秒 t = time_s / SCALE_TIMER_RATE；影片版（`"real_s"`）不縮放。
       停流時刻與杯溫讀取時刻同步換算。
    1. 注水率物理上限：超過上限的區間，保持累積終點與終點時刻不變，把起點往前移。
    2. 秤重漂移：poured 單調化（running max）。
    3. 量筒讀值：drained 單調化；整數讀值的 ±0.5 mL 量化已在 σ_V 內，不改值。
    4. 讀取時刻不確定度：σ_V,i = sqrt(σ_V,i,read² + (q_obs,i·σ_t)²)。σ_V,i,read 在影片版取
       逐點 `drained_sigma_ml`（液位偵測品質），紀錄表取常數 σ_V；σ_t 在影片版取
       `VIDEO_READING_TIME_SIGMA_S`（逐格判讀），紀錄表取 `READING_TIME_SIGMA_S`。
    5. 質量守恆（drained > poured）：維持既有 `data_quality_flags` 機制，不改值。
"""

from __future__ import annotations

import numpy as np

from .measured_io import (
    POUR_INTERVAL_MIN_G,
    POUR_RATE_CAP_MARGIN,
    READING_TIME_SIGMA_S,
    SCALE_TIMER_RATE,
    VIDEO_READING_TIME_SIGMA_S,
    flow_profile_quality_flags,
)


def infer_max_pour_rate_g_s(
    t_s: np.ndarray,
    v_in_ml: np.ndarray,
    margin: float = POUR_RATE_CAP_MARGIN,
    min_pour_g: float = POUR_INTERVAL_MIN_G,
) -> float:
    """
    由同一次沖煮「其他各注」推得手沖壺注水率上限 [g/s]。

    What:
        各區間注水率 r_j = ΔV_j/Δt_j（只取 ΔV ≥ min_pour_g 的區間）；
        上限 = margin × 第二大的 r_j。

    Why:
        leave-one-out 的精確寫法：檢驗區間 i 時，參考值是「除了 i 以外」的最大值。
        對最大那一區間而言它就是第二大值；對其他區間而言參考值是最大值本身，
        而 r_i ≤ max < margin·max 恆不觸發——所以只有最大區間可能被判為異常，
        上限因此是單一值（第二大 × margin），不需要迭代。
        限制：若同一次沖煮有兩個以上的異常區間，第二大值本身就是異常值，
        此規則只抓得到最大的那一個（fail-safe：不會誤殺正常注水）。
    """
    t = np.asarray(t_s, dtype=float)
    v = np.maximum.accumulate(np.asarray(v_in_ml, dtype=float))
    dt = np.diff(t)
    dv = np.diff(v)
    ok = (dv >= float(min_pour_g)) & (dt > 0.0)
    rates = np.sort(dv[ok] / dt[ok])[::-1]
    if rates.size < 2:
        raise ValueError("注水區間不足兩段，無法以 leave-one-out 推得注水率上限")
    return float(margin) * float(rates[1])


def volume_sigma_ml(
    q_obs_mlps: np.ndarray,
    sigma_v_ml: float | np.ndarray,
    reading_time_sigma_s: float,
) -> np.ndarray:
    """
    V_out 的逐點量測 σ [mL]（讀取時刻誤差的一階傳播）。

    What: σ_V,i = sqrt(σ_V² + (q_obs,i · σ_t)²)
    Why:  讀值 V_out(t_i + δt) ≈ V_out(t_i) + q(t_i)·δt，δt ~ N(0, σ_t²)。
          出流大時，同樣 1 s 的時刻誤差造成較大的體積誤差；出流為 0 時退回 σ_V。
          這是量測誤差的正確傳播，不是調參：σ_t 與 σ_V 都是量測程序決定的常數，
          q_obs 取自**量測**（不是模型），因此 σ 與參數無關、χ² 仍是同一個函數。
    """
    q = np.asarray(q_obs_mlps, dtype=float)
    s_v = np.asarray(sigma_v_ml, dtype=float)      # 純量或逐點（F10 影片版）
    return np.sqrt(s_v ** 2 + (q * float(reading_time_sigma_s)) ** 2)


def point_outflow_rate_mlps(t_s: np.ndarray, v_out_ml: np.ndarray) -> np.ndarray:
    """
    量測出流率在各觀測時刻的估計 [mL/s]（中央差分，兩端單側）。

    Why: σ 傳播需要「該時刻」的 dV/dt；區間平均 q 定義在區間上、少一個點，
         中央差分是最簡單且不外插的點估計。V_out 已單調化，因此結果恆 ≥ 0。
    """
    t = np.asarray(t_s, dtype=float)
    v = np.asarray(v_out_ml, dtype=float)
    n = t.size
    q = np.zeros(n, dtype=float)
    if n < 2:
        return q
    q[0] = (v[1] - v[0]) / max(t[1] - t[0], 1e-12)
    q[-1] = (v[-1] - v[-2]) / max(t[-1] - t[-2], 1e-12)
    if n > 2:
        q[1:-1] = (v[2:] - v[:-2]) / np.maximum(t[2:] - t[:-2], 1e-12)
    return np.maximum(q, 0.0)


def _running_max_with_log(values: np.ndarray, t: np.ndarray, field: str, rule: str,
                          corrections: list[dict]) -> np.ndarray:
    """單調化（running max）並把每一個被抬升的列寫進 corrections。"""
    raw = np.asarray(values, dtype=float)
    mono = np.maximum.accumulate(raw)
    for i in np.flatnonzero(mono > raw):
        corrections.append({
            "t_s": float(t[i]), "field": field,
            "old": float(raw[i]), "new": float(mono[i]), "rule": rule,
        })
    return mono


def _cap_pour_rate(
    t: np.ndarray,
    v_in: np.ndarray,
    cap: float,
    sigma_t: float,
    min_pour_g: float,
    corrections: list[dict],
) -> tuple[np.ndarray, list[tuple[float, float]]]:
    """
    規則 1：超過注水率上限的區間，終點（時刻、累積量）不動、起點往前移。

    What:
        區間 (t_{i−1}, t_i] 的注水量 ΔV 若在時間戳容許 ±σ_t 下仍超過上限
        （ΔV/(Δt + 2σ_t) > cap），往前找最近的 j 使 (V_i − V_j)/(t_i − t_j) ≤ cap，
        把這段 V_i − V_j 重建為「以 cap 注入、於 t_i 結束」：
            t_start = t_i − (V_i − V_j)/cap          （≥ t_j）
            V(t_k)  = V_j + cap·max(t_k − t_start, 0)，j < k < i
        並在 t_start 插入一個注水協議節點。

    Why:
        終點是秤上讀到的累積量與讀取時刻，是這一段最可信的兩個數；
        起點（「第四注開始」這種人工標定）才是時間戳誤差的所在。
        以上限速率往前推是**最小位移**的重建：它只把起點移到物理上
        剛好可行的位置，不另外假設注水形狀。

    Returns:
        (修正後的 V_in(t_obs), 注水協議節點 [(t, V)]；含插入的起點)
    """
    v = v_in.copy()
    knots: list[tuple[float, float]] = [(float(tt), float(vv)) for tt, vv in zip(t, v)]
    for i in range(1, t.size):
        dv = v[i] - v[i - 1]
        dt = t[i] - t[i - 1]
        if dv < min_pour_g or dt <= 0.0:
            continue
        if dv / (dt + 2.0 * sigma_t) <= cap:
            continue
        j = i - 1
        while j >= 0 and (v[i] - v[j]) / (t[i] - t[j]) > cap:
            j -= 1
        if j < 0:
            raise ValueError(
                f"t={t[i]:g} s 的注水量無法在上限 {cap:.2f} g/s 下於紀錄起點之後完成")
        t_start = float(t[i] - (v[i] - v[j]) / cap)
        corrections.append({
            "t_s": float(t[i]), "field": "pour_start_s",
            "old": float(t[i - 1]), "new": t_start,
            "rule": f"pour_rate_cap {cap:.2f} g/s (raw {dv / dt:.1f} g/s)",
        })
        for k in range(j + 1, i):
            new_vk = float(v[j] + cap * max(t[k] - t_start, 0.0))
            if abs(new_vk - v[k]) > 1e-12:
                corrections.append({
                    "t_s": float(t[k]), "field": "v_in_ml",
                    "old": float(v[k]), "new": new_vk,
                    "rule": f"pour_rate_cap {cap:.2f} g/s",
                })
            v[k] = new_vk
        knots = [kn for kn in knots if not (t[j] < kn[0] < t[i])]
        knots += [(float(t[k]), float(v[k])) for k in range(j + 1, i)]
        if t_start > t[j] + 1e-9:
            knots.append((t_start, float(v[j])))
        knots.sort()
    return v, knots


def preprocess_flow_profile(
    prof: dict,
    *,
    max_pour_rate_g_s: float | None = None,
    reading_time_sigma_s: float | None = None,
    sigma_v_ml: float = 3.0,
    min_pour_g: float = POUR_INTERVAL_MIN_G,
) -> dict:
    """
    量測 flow profile 的預處理（規則見模組 docstring）。

    Args:
        prof: `load_flow_profile_csv()` 的輸出（不被修改）。
        max_pour_rate_g_s: 注水率上限；None 時由 `infer_max_pour_rate_g_s` 推得。
        reading_time_sigma_s: 讀取時刻 1σ [s]（規則 1 的容許區間與規則 4 的 σ 傳播）。
            None（預設）= 依來源決定：影片版 `VIDEO_READING_TIME_SIGMA_S`、紀錄表
            `READING_TIME_SIGMA_S`。
        sigma_v_ml: 紀錄表讀值本身的 σ_V（由 `fitting.MEASUREMENT_SIGMA["v_out_ml"]` 傳入）；
            profile 帶逐點 `drained_sigma_ml`（影片版）時以逐點值取代。

    Returns:
        `prof` 的淺拷貝，覆寫 `v_in_ml` / `v_out_ml` / `retained_mass_g` /
        `data_quality_flags`，並新增：
          `pour_knots`           注水協議節點 [(t, V_in)]（含重建插入的起點）
          `q_obs_point_mlps`     各觀測時刻的量測出流率（中央差分）
          `sigma_v_ml`           逐點 V_out σ（規則 4）
          `corrections`          逐列修正紀錄 [{t_s, field, old, new, rule}]
          `max_pour_rate_g_s`    / `max_pour_rate_source`（"given" | "leave_one_out"）
          `reading_time_sigma_s`
          `scale_timer_rate_applied`  規則 0 用的速率比（影片版 / real_s 為 1.0）
          `stop_flow_time_s` / `final_temp_read_time_s`  換算到真實秒後的值
          `quality_flags`        = `data_quality_flags`（修正後資料重算）
          `preprocessed`         True
    """
    # 規則 −1：逐列 meta 共識（`measured_io.meta_consensus`）的修正一併寫入紀錄。
    corrections: list[dict] = list(prof.get("meta_corrections") or [])
    is_video = prof.get("profile_source") == "video"
    if reading_time_sigma_s is None:
        reading_time_sigma_s = VIDEO_READING_TIME_SIGMA_S if is_video else READING_TIME_SIGMA_S
        if is_video:
            corrections.append({
                "t_s": 0.0, "field": "reading_time_sigma_s",
                "old": float(READING_TIME_SIGMA_S), "new": float(reading_time_sigma_s),
                "rule": "video frame-resolved readings",
            })

    # 規則 0：時間基準。紀錄表 time_s = 秤計時器秒 → 真實秒。
    t_raw = np.asarray(prof["t_s"], dtype=float)
    time_base = str(prof.get("time_base", "real_s"))
    if time_base == "scale_timer_s":
        rate = float(SCALE_TIMER_RATE)
        corrections.append({
            "t_s": float(t_raw[-1]), "field": "time_s",
            "old": float(t_raw[-1]), "new": float(t_raw[-1] / rate),
            "rule": f"scale_timer_rate {rate:g} (all rows t/{rate:g})",
        })
    elif time_base == "real_s":
        rate = 1.0
    else:
        raise ValueError(f"未知的 time_base：{time_base}")
    t = t_raw / rate
    v_in_raw = np.asarray(prof["v_in_ml"], dtype=float)
    v_out_raw = np.asarray(prof["v_out_ml"], dtype=float)
    ret_raw = np.asarray(prof["retained_mass_g"], dtype=float)
    if np.any(np.diff(t) <= 0.0):
        raise ValueError("flow profile 的 time_s 必須嚴格遞增")

    # 規則 2：秤重漂移——累積注水不得下降。
    v_in = _running_max_with_log(v_in_raw, t, "v_in_ml", "scale_drift_running_max", corrections)
    # 規則 3：量筒讀值單調化（整數量化 ±0.5 mL 已在 σ_V 內，不改值）。
    v_out = _running_max_with_log(v_out_raw, t, "v_out_ml", "drained_running_max", corrections)

    # 規則 1：注水率物理上限。
    if max_pour_rate_g_s is None:
        cap = infer_max_pour_rate_g_s(t, v_in, min_pour_g=min_pour_g)
        cap_source = "leave_one_out"
    else:
        cap = float(max_pour_rate_g_s)
        cap_source = "given"
    if cap <= 0.0:
        raise ValueError(f"注水率上限必須為正：{cap}")
    v_in, knots = _cap_pour_rate(t, v_in, cap, float(reading_time_sigma_s), min_pour_g, corrections)

    # 保水：量測欄若只是 poured − drained 的代數重排（四 case 皆是，見
    # `load_flow_profile_csv` 的 Why），就以修正後的兩欄重算；若是獨立秤重則不動。
    derived = np.allclose(ret_raw, v_in_raw - v_out_raw, atol=1e-6)
    retained = v_in - v_out if derived else ret_raw.copy()

    # 規則 4：讀取時刻不確定度 → 逐點 V_out σ（影片版讀值 σ 逐點）。
    q_point = point_outflow_rate_mlps(t, v_out)
    sigma_read = prof.get("drained_sigma_ml")
    sigma_read = sigma_v_ml if sigma_read is None else np.asarray(sigma_read, dtype=float)
    if np.any(~np.isfinite(sigma_read)) or np.any(np.asarray(sigma_read) <= 0.0):
        raise ValueError("drained_sigma_ml 必須為正且有限")
    sigma_v = volume_sigma_ml(q_point, sigma_read, reading_time_sigma_s)

    out = dict(prof)
    out.update({
        "t_s": t,
        "stop_flow_time_s": float(prof["stop_flow_time_s"]) / rate if "stop_flow_time_s" in prof else None,
        "final_temp_read_time_s": (float(prof["final_temp_read_time_s"]) / rate
                                   if "final_temp_read_time_s" in prof else None),
        "scale_timer_rate_applied": float(rate),
        "v_in_ml": v_in,
        "v_out_ml": v_out,
        "retained_mass_g": retained,
        "pour_knots": knots,
        "q_obs_point_mlps": q_point,
        "sigma_v_ml": sigma_v,
        "corrections": corrections,
        "max_pour_rate_g_s": float(cap),
        "max_pour_rate_source": cap_source,
        "reading_time_sigma_s": float(reading_time_sigma_s),
        "preprocessed": True,
    })
    # 規則 5：質量守恆等品質旗標以修正後資料重算（機制不變）。
    out["data_quality_flags"] = flow_profile_quality_flags(out)
    out["quality_flags"] = out["data_quality_flags"]
    return out


def format_corrections(corrections: list[dict]) -> str:
    """把 corrections 壓成 summary CSV 的單欄（分號分隔）。"""
    return ";".join(
        f"t={c['t_s']:g}s {c['field']} {c['old']:.4g}->{c['new']:.4g} ({c['rule']})"
        for c in corrections
    )
