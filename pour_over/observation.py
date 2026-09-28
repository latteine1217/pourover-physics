"""
observation.py — 模型觀測層與量測對應

What:
    將粉床出口的模擬量轉成使用者真正量到的壺內 / 杯中觀測量，
    包含 outflow lag、server 熱節點與可觀測停流時間。

Why:
    fitting、benchmark、identifiability 都應共享同一套觀測層；
    否則每個工具其實在比較不同訊號，結論無法對齊。
"""

import numpy as np

from .measured_io import (
    FINAL_WINDOW_S,
    MEASURED_AMBIENT_TEMP_C,
    STOP_SMOOTH_POINTS,
    STOP_TOL_ML,
)
from .params import PourProtocol


# 目視停流門檻 [mL/s]。
# What: `observed_stop_time_from_layer` 與 `core.drain_time` 共用的「流動已停」判據。
# Why:  使用者判定停流的實際依據是「不再看到連續滴落」。V60 出口一滴約
#       0.04–0.05 mL（水在 ~1.5 mm 濾杯孔口的 Tate 極限），因此 0.05 mL/s
#       ≈ 1 滴/秒，正是肉眼由「連續滴」轉為「偶爾一滴」的分界。
#       不是可調參數；改動它等於改動觀測量的定義，必須同步改 core.drain_time。
OBSERVED_STOP_THRESHOLD_MLPS = 0.05


def mixed_cup_temperature_C(
    results: dict,
    ambient_temp_C: float,
    vessel_equivalent_ml: float = 0.0,
    t_read_s: float | None = None,
) -> float:
    """
    取得 server / 杯中在量測時刻的溫度。

    What:
        有 `T_server_C`（observation 層的 server 熱節點時序）時，
        回傳 `interp(t_read_s)`；`t_read_s=None` 則取末值。
        沒有 server 節點時，退回「出流加權混合 + 容器熱容」的代數 fallback。

    Why:
        使用者量到的是某個具體時刻拿溫度計插進分享壺讀到的值
        （kinu29 4:11 為 CSV 的 `dripper_off_final` 列，t = 142 s），
        而不是模擬視窗末端 t = 180 s 的值。硬取 `T_server[-1]` 等於把
        38 秒的額外自然冷卻算進去，再由熱端 closure 反向補償。

        fallback 分支保留給沒有跑 `apply_outflow_lag` 的呼叫端；
        它假設所有出流先瞬間混合再與容器平衡，不含 server 的持續散熱。
    """
    if "T_server_C" in results:
        T_server = np.asarray(results["T_server_C"], dtype=float)
        if T_server.size:
            if t_read_s is None:
                return float(T_server[-1])
            t_arr = np.asarray(results["t"], dtype=float)
            return float(np.interp(float(t_read_s), t_arr, T_server))
    # ── fallback：無 server 熱節點時的代數混合估計 ─────────────────────────
    t = np.asarray(results["t"], dtype=float)
    q_out_mlps = np.asarray(results["q_out_mlps"], dtype=float)
    T_out_C = np.asarray(results["T_C"], dtype=float)
    dt = np.diff(t, prepend=t[0])
    cup_volume_ml = float(np.sum(q_out_mlps * dt))
    if cup_volume_ml <= 0:
        return ambient_temp_C
    cup_energy = float(np.sum(q_out_mlps * T_out_C * dt))
    total_heat_capacity_ml = cup_volume_ml + max(vessel_equivalent_ml, 0.0)
    return (cup_energy + max(vessel_equivalent_ml, 0.0) * ambient_temp_C) / total_heat_capacity_ml


def observed_stop_time_from_layer(
    obs_layer: dict,
    t_sim: np.ndarray,
    protocol: PourProtocol,
    threshold_mlps: float = OBSERVED_STOP_THRESHOLD_MLPS,
) -> float:
    """
    由 lag 後杯中出流推估可觀測停流時間（sub-grid 線性插補）。

    What:
        在最後一注之後，找 `q_cup` 第一個跨越 `threshold_mlps` 的瞬間，
        以線性插補返回 sub-grid 連續時間。

    Why:
        使用者看到的是壺內液面停止上升，不是濾床出口的瞬時停流；
        benchmark / fitting / identifiability 都應共用同一個觀測層定義。

    2026-05-01 修正：原版用 `t_sim[below[0]]` 直接取 grid 點，造成 stop_time
        以 dt = (t_end - 0) / n_eval ≈ 0.25 s 的解析度量化。loss 中
        `weights["drain_time"] * |stop_model - stop_obs|` 因此呈現 staircase
        ridge，subagent 審查證實這是 stages 1/2 basin 漂移的根因（非 Powell
        tolerance 問題）。改為 sub-grid 線性插補後 stop_time 是連續變數，
        loss surface 沿 ridge 變平滑、Powell 收斂於唯一 basin。
    """
    q_cup = np.asarray(obs_layer["q_cup_mlps"], dtype=float)
    t_sim = np.asarray(t_sim, dtype=float)
    t_last = protocol.last_pour_end()
    mask = t_sim >= t_last
    indices = np.where(mask)[0]
    if indices.size == 0:
        return float(t_sim[-1])

    # 從最後一注後第一個點開始掃，找第一段 q_cup 從 above → below threshold 的 crossing
    for i in indices[:-1]:
        if q_cup[i] > threshold_mlps and q_cup[i + 1] <= threshold_mlps:
            q_hi, q_lo = float(q_cup[i]), float(q_cup[i + 1])
            t_hi, t_lo = float(t_sim[i]), float(t_sim[i + 1])
            denom = q_hi - q_lo
            if denom <= 1e-12:
                return t_lo
            # Linear interpolation: q(t) = q_hi + (q_lo - q_hi) * (t - t_hi) / (t_lo - t_hi)
            # Solve q(t) = threshold
            frac = (q_hi - threshold_mlps) / denom
            return t_hi + frac * (t_lo - t_hi)

    # 第一個 grid 點就已經在 threshold 之下（極端 case：流動極早停）
    if q_cup[indices[0]] <= threshold_mlps:
        return float(t_sim[indices[0]])
    return float(t_sim[-1])


def level_stop_time(
    t_grid: np.ndarray,
    v_grid: np.ndarray,
    valid: np.ndarray,
    t_last_pour_end: float,
    *,
    tol_ml: float = STOP_TOL_ML,
    final_window_s: float = FINAL_WINDOW_S,
    smooth_points: int = STOP_SMOOTH_POINTS,
) -> float:
    """
    影片版液位停流運算子（量測端與模型端共用；F12a）。

    What:
        在觀測格點 `t_grid`（1 s）上，只取 `valid` 的液位：
          1. s_i = 以 i 為中心、`smooth_points` 點窗內**有效點**的平均；
          2. 終值 V_f = 最後一個有效格點前 `final_window_s` 秒內有效液位的中位數；
          3. 在 t_i > `t_last_pour_end` 的格點中找第一個 s_i ≥ V_f − `tol_ml`，
             以 (t_{i−1}, s_{i−1}) → (t_i, s_i) 線性內插出跨越時刻（不早於 t_last_pour_end）。
        找不到跨越 → 回傳最後一個有效格點的時刻（觀測窗內未達平衡）。
    Why:
        影片 case 的停流觀測值由 `tools/video/build_profile.py` 以同一規則產生；模型端若改用
        出流率門檻（`OBSERVED_STOP_THRESHOLD_MLPS`）就是在比較兩個不同的觀測量（R12 Q3）。
        兩端共用同一個函式、同一組常數（`measured_io.STOP_TOL_ML` 等）、同一個有效格點遮罩
        （因此終值窗也相同）。次格內插讓模型端停流時刻對參數連續，避免 χ² 階梯
        （同 2026-05-01 `observed_stop_time_from_layer` 的修正）。
    """
    t = np.asarray(t_grid, dtype=float)
    v = np.asarray(v_grid, dtype=float)
    ok = np.asarray(valid, dtype=bool) & np.isfinite(v)
    if not np.any(ok):
        raise ValueError("level_stop_time：沒有任何有效液位格點")
    half = int(smooth_points) // 2
    vv = np.where(ok, v, 0.0)
    n = t.size
    smooth = np.full(n, np.nan)
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        cnt = int(ok[lo:hi].sum())
        if cnt:
            smooth[i] = float(vv[lo:hi].sum()) / cnt
    t_end = float(t[ok].max())
    v_final = float(np.median(v[ok & (t >= t_end - float(final_window_s))]))
    thr = v_final - float(tol_ml)
    cand = np.flatnonzero((t > float(t_last_pour_end)) & np.isfinite(smooth) & (smooth >= thr))
    if cand.size == 0:
        return t_end
    i = int(cand[0])
    if i > 0 and np.isfinite(smooth[i - 1]) and smooth[i - 1] < thr:
        frac = (thr - smooth[i - 1]) / (smooth[i] - smooth[i - 1])
        t_cross = float(t[i - 1] + frac * (t[i] - t[i - 1]))
        return max(t_cross, float(t_last_pour_end))
    return float(t[i])


def model_level_stop_time(
    obs_layer: dict,
    t_sim: np.ndarray,
    t_grid: np.ndarray,
    valid: np.ndarray,
    t_last_pour_end: float,
) -> float:
    """
    模型端液位停流：把模型杯中累積出液 `v_cup_ml` 取樣到**觀測的**格點與有效遮罩上，
    再套 `level_stop_time`（What / Why 同該函式）。
    """
    v_model = np.interp(np.asarray(t_grid, dtype=float), np.asarray(t_sim, dtype=float),
                        np.asarray(obs_layer["v_cup_ml"], dtype=float))
    return level_stop_time(t_grid, v_model, valid, t_last_pour_end)


def apply_outflow_lag(
    results: dict,
    tau_lag_s: float,
    *,
    ambient_temp_C: float | None = None,
    vessel_equivalent_ml: float = 0.0,
    lambda_server_ambient: float | None = None,
) -> dict:
    """
    將粉床出口流量轉成杯中可觀測出液（解析一階 lag）。

    What:
        以一個暫存體積 `V_hold` 把床層出口流量 `q_out` 轉成杯中可觀測流量
        `q_cup`，並同步追蹤 hold-up 與 server 熱節點。

        暫存體積滿足一階 lag：`dV_hold/dt = q_in − V_hold/τ`。
        對**分段常數**的 `q_in`（solver 輸出格點之間即為此形式），該方程有
        解析解，因此本函式改用精確步進：

            a          = exp(−Δt/τ)
            V_hold_new = V_hold·a + q_in·τ·(1 − a)
            released   = V_hold + q_in·Δt − V_hold_new          （精確質量守恆）
            q_cup      = V_hold_new / τ                          （瞬時釋放率）

        焓以同一線性算子步進（輸入 `q_in·T_in`），釋放溫度取該步的釋放焓 / 釋放量。
        server 節點採 operator splitting：先對既有內容物做解析指數冷卻
        `T ← T_amb + (T − T_amb)·exp(−λ Δt)`，再瞬時混入本步流入。

    Why:
        使用者量到的是壺內液面上升的區間平均速度，而不是濾床出口的瞬時滴流。

        2026-09-24 修正（AUD-3-3）：原實作用顯式 Euler
        `q_release = min(V_hold/τ, …)`，等效時間常數偏低
        （coarse grid −6.4%、τ = 0.5 s 時 −28%），意思是「同一個 τ 在不同
        n_eval 下代表不同的物理 hold-up」。由於 τ 幾乎只由停流時間識別，
        這個離散化偏差會被 optimizer 直接吸收成 τ 的偏移。
        解析步進讓 τ 與時間格點完全脫鉤（`tests/test_observation_lag.py` 釘住），
        同時 `v_cup` 仍是精確的累積釋放量（質量守恆到機器精度）。
    """
    tau = max(float(tau_lag_s), 1e-6)
    t = np.asarray(results["t"], dtype=float)
    q_src = np.asarray(results["q_out_mlps"], dtype=float)
    T_src = np.asarray(results["T_C"], dtype=float)
    ambient_C = MEASURED_AMBIENT_TEMP_C if ambient_temp_C is None else float(ambient_temp_C)
    server_lambda = float(results.get("lambda_server_ambient", 0.0) if lambda_server_ambient is None else lambda_server_ambient)
    vessel_eq = max(float(vessel_equivalent_ml), 0.0)

    q_cup = np.zeros_like(q_src)
    v_cup = np.zeros_like(q_src)
    v_hold = np.zeros_like(q_src)
    T_cup = np.zeros_like(T_src)
    v_server = np.zeros_like(q_src)
    T_server = np.full_like(T_src, ambient_C)

    hold_v = 0.0
    hold_e = 0.0          # 焓代理 [mL·°C]
    server_v = 0.0
    server_T = ambient_C

    for i in range(1, len(t)):
        dt = max(float(t[i] - t[i - 1]), 0.0)
        q_in_i = max(float(q_src[i - 1]), 0.0)
        T_in_i = float(T_src[i - 1])

        a = float(np.exp(-dt / tau)) if dt > 0.0 else 1.0
        hold_v_new = hold_v * a + q_in_i * tau * (1.0 - a)
        released_v = hold_v + q_in_i * dt - hold_v_new
        hold_e_new = hold_e * a + q_in_i * T_in_i * tau * (1.0 - a)
        released_e = hold_e + q_in_i * T_in_i * dt - hold_e_new

        if released_v > 1e-12:
            T_release = released_e / released_v
        elif hold_v_new > 1e-12:
            T_release = hold_e_new / hold_v_new
        else:
            T_release = T_in_i

        hold_v = max(hold_v_new, 0.0)
        hold_e = max(hold_e_new, 0.0)
        released_v = max(released_v, 0.0)

        q_cup[i] = hold_v / tau
        v_cup[i] = v_cup[i - 1] + released_v
        v_hold[i] = hold_v
        T_cup[i] = T_release

        # ── server 節點：解析冷卻 → 瞬時混合 ─────────────────────────────
        if server_lambda > 0.0 and dt > 0.0:
            server_T = ambient_C + (server_T - ambient_C) * float(np.exp(-server_lambda * dt))
        cap_prev = server_v + vessel_eq
        server_v = max(server_v + released_v, 0.0)
        cap_next = server_v + vessel_eq
        server_T = (
            (cap_prev * server_T + released_v * T_release) / cap_next
            if cap_next > 1e-9
            else ambient_C
        )
        v_server[i] = server_v
        T_server[i] = server_T

    if len(T_cup) > 1:
        T_cup[0] = T_cup[1]
    if len(T_server) > 1:
        T_server[0] = ambient_C

    return {
        "tau_lag_s": tau,
        "q_cup_mlps": q_cup,
        "v_cup_ml": v_cup,
        "v_hold_ml": v_hold,
        "T_cup_C": T_cup,
        "v_server_ml": v_server,
        "T_server_C": T_server,
        "vessel_equivalent_ml": vessel_eq,
        "lambda_server_ambient": server_lambda,
    }
