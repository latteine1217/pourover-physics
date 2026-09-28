"""
V60 手沖咖啡 ODE 模擬引擎
==========================
此模組為核心數值積分引擎，實作 V60 動態 ODE 系統的求解與結果後處理。

核心狀態向量：
    state = [V_free, V_mob, V_imm, V_abs, w, V_out, V_bed, V_poured,
             extraction axial bins..., T, T_dripper, xi_pref]

水量帳（What / Why）：
    V_free  自由水體積 [m³]：粉床頂部以上的積水
    V_mob   床內 mobile 孔隙水 [m³]：可被重力排出，決定 kr(S_mob) 與床內驅動頭
    V_imm   床內 immobile 孔隙水 [m³]：毛細扣留，容量 φ·V_bed·f_retain·w，不排出
    V_abs   顆粒吸收水體積 [m³]：容量 V_full·w
    w       床層潤濕狀態 [-]：dw/dt = (1−w)/τ_wet · g(液相在場)
    恆等式  V_poured = V_out + V_abs + V_imm + V_mob + V_free
            （由 `water_balance_residual_ml` 監控）

    Why（F2b）: F2 把床內水視為單一 `S_bed` 池，且因 h_cap_bed > h_bed 而「永不排乾」。
         量測 retained_mass_g 直接否證這件事：悶蒸 46.6 mL 注入乾床後，
         t = 10 → 30 s 之間床內淨排出 24 mL、最終只留 14.6 g；
         但 t = 142 s 保水升到 52.1 g（> V_full + φV_bed = 44.8 mL）。
         也就是說「剛潤濕的乾床會被重力排乾，保水能力是隨潤濕逐漸建立的時序量」。
         mobile / immobile 分池 + 潤濕狀態 w 就是這句話的最小寫法：
         mobile 水受重力排出（Corey 殘留 0），immobile 與吸收水的容量隨 w 開放。

主要函式：
    simulate_brew()  — 數值積分 ODE，回傳完整時序結果 dict
    print_summary()  — 格式化輸出沖煮摘要至 stdout
"""

import warnings

import numpy as np
from scipy.integrate import solve_ivp

from .params import (
    V60Params, PourProtocol, RHO, CP_WATER,
    RATE_SMOOTH_EPS, TRANSFER_TAU_S, smooth_min,
)

# 狀態向量中水力/水量帳佔用的前置長度（萃取 bins 由此之後接續）
_N_BASE_STATES = 8

# 出流供給上限的時間尺度 [s]（= `params.TRANSFER_TAU_S`，同一個連續化常數）
# What: Q_out ≤ (尚未入池的過床水流) + (V_free + V_mob) / FREE_DRAIN_TAU_S。
# Why:  這不是可調 closure，而是質量守恆本身的連續化寫法：水池排出的速率
#       不可能超過「現有存量 / 一個瞬間」。它只在自由水與 mobile 水都剩最後幾 mL
#       時才綁住達西能力——沒有它，濕床毛細項 h_cap,wet 會在 h_free = 0 時
#       仍給出正驅動頭，讓模型從空的水池憑空造水。
FREE_DRAIN_TAU_S = TRANSFER_TAU_S


def _cumtrapz(y, x) -> np.ndarray:
    """
    What: 對 (x, y) 做累積梯形積分，回傳與輸入等長、首項為 0 的陣列。
    Why:  能量審計的殘差門檻是 2% E_in；矩形和在 dt ≈ 0.15 s 下的誤差已不可忽略。
    """
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    if y.size < 2:
        return np.zeros_like(y)
    inc = 0.5 * (y[1:] + y[:-1]) * np.diff(x)
    return np.concatenate(([0.0], np.cumsum(inc)))


def _solve_piecewise(rhs, t_end: float, y0, t_eval, breakpoints, **solver_kw):
    """
    What: 在 `breakpoints` 切出的每一段上各自呼叫 `solve_ivp`，以段尾狀態接續下一段；
          回傳 (t, y)，與單次 `solve_ivp(t_eval=t_eval)` 的 `sol.t` / `sol.y` 同形狀。
    Why:  注水率在斷點處跳動。單段積分跨過跳點時，步長落在跳點哪一側隨參數極小擾動翻轉，
          χ² 帶 ±0.07–0.17 的路徑噪音；分段後段內 RHS 光滑，噪音降到 ~1e-8，
          rtol 1e-7 的截斷誤差與單段 rtol 1e-10 相當（F13-C）。
          段內把 RHS 的 t 夾在 [a, nextafter(b, a)]：RK45 最後一個 stage 落在 t = b，
          不夾會取到下一段的注水率（`pour_rate` 為右連續）。
          某段失敗時停止並回傳已完成的部分（與單次 `solve_ivp` 失敗時的行為相同），另發警告。
    """
    edges = [0.0, *(b for b in breakpoints if 0.0 < b < t_end), float(t_end)]
    y = np.asarray(y0, dtype=float)
    ts, ys = [], []
    for i, (a, b) in enumerate(zip(edges[:-1], edges[1:])):
        last = i == len(edges) - 2
        m = (t_eval >= a) & ((t_eval <= b) if last else (t_eval < b))
        te = t_eval[m]
        te_ext = te if (te.size and te[-1] >= b) else np.append(te, b)
        hi = np.nextafter(b, a)
        seg = solve_ivp(
            lambda t, yy, a=a, hi=hi: rhs(min(max(t, a), hi), yy),
            t_span=(a, b), y0=y, t_eval=te_ext, **solver_kw,
        )
        n_keep = min(te.size, seg.t.size)
        ts.append(seg.t[:n_keep])
        ys.append(seg.y[:, :n_keep])
        if not seg.success:
            warnings.warn(f"ODE 在 [{a:g}, {b:g}] s 段積分失敗（{seg.message}）；結果截斷於 t = {seg.t[-1] if seg.t.size else a:g} s。",
                          RuntimeWarning, stacklevel=3)
            break
        y = seg.y[:, -1]
    return np.concatenate(ts), np.concatenate(ys, axis=1)


def _first_downcrossing(t, y, threshold: float, mask) -> float | None:
    """
    What: 在 `mask` 為真的區間內，找 y 第一次由上往下穿越 threshold 的時刻（線性插補）。
    Why:  grid 解析度（t_end/n_eval ≈ 0.06–0.15 s）會把 brew/drain time 量化成階梯，
          使 fitting loss 出現 staircase ridge；sub-grid 插補讓它回到連續變數。
    """
    idx = np.where(mask)[0]
    if idx.size == 0:
        return None
    if y[idx[0]] <= threshold:
        return float(t[idx[0]])
    for i in idx:
        if i == 0:
            continue
        if y[i] <= threshold < y[i - 1]:
            denom = y[i - 1] - y[i]
            if denom <= 1e-18:
                return float(t[i])
            frac = (y[i - 1] - threshold) / denom
            return float(t[i - 1] + frac * (t[i] - t[i - 1]))
    return None


def simulate_brew(
    params: V60Params,
    protocol: PourProtocol,
    t_end: float = 180.0,
    n_eval: int = 3000,
    rtol: float = 1e-6,
    atol: float = 1e-8,
    max_step: float = 0.5,
) -> dict:
    """
    數值積分 V60 動態 ODE 系統（水量守恆水力 + bin-resolved 萃取 + 雙節點熱模型）。

    What:
          基礎狀態固定為 [V_free, S_bed, V_abs, V_out, V_bed, V_poured]；
          measured PSD bins 啟用時，接著是每個 axial layer × bin 的：
          [C_fast_ij, M_fast_ij, C_slow_ij, M_slow_ij]；
          最後接 [T, T_dripper, xi_pref]。

    Why:
          水力端從「單一水位 h」升級為三個顯式水池（吸收 / 孔隙 / 自由水），
          使 V_poured = V_out + V_abs + V_pore + V_free 成為結構恆等式；
          驅動頭因此只剩自由水柱（床內水柱被 Young-Laplace 保水頭抵銷），
          出流的終止條件不再需要人工 clamp。
          萃取端仍是 bin-resolved，讓 measured PSD 的 A_i、L_i、M_i 真正進入 ODE。
          `rtol/atol/max_step` 保持預設即可重現既有結果；fitting 可用較鬆設定換取速度。
    """
    t_bloom_end = protocol.bloom_end_time()
    n_bins = int(getattr(params, "extraction_bin_count", 1))
    n_layers = int(getattr(params, "axial_node_count", 1))
    n_axial = n_layers * n_bins
    layer_frac = np.asarray(getattr(params, "axial_layer_volume_fraction", np.full(n_layers, 1.0 / max(n_layers, 1))), dtype=float)
    layer_frac = layer_frac / np.maximum(np.sum(layer_frac), 1e-12)
    layer_frac_col = layer_frac[:, None]
    M_fast_0_layers = layer_frac_col * np.asarray(params.M_fast_0_bins, dtype=float)[None, :]
    M_slow_0_layers = layer_frac_col * np.asarray(params.M_slow_0_bins, dtype=float)[None, :]
    b = _N_BASE_STATES
    c_fast_slice = slice(b, b + n_axial)
    m_fast_slice = slice(b + n_axial, b + 2 * n_axial)
    c_slow_slice = slice(b + 2 * n_axial, b + 3 * n_axial)
    m_slow_slice = slice(b + 3 * n_axial, b + 4 * n_axial)
    T_idx = b + 4 * n_axial
    T_dripper_idx = T_idx + 1
    pref_idx = T_idx + 2

    V_full = max(float(params._V_full), 1e-12)
    V_pore_max = max(float(params.V_liquid), 1e-12)
    rho_cp = RHO * CP_WATER
    C_dripper_J_K = rho_cp * float(params.V_equiv_dripper)

    # 液體 ⇄ 濾杯界面：U·A_wet(h)（新路徑）或舊集總 λ（expand 期相容路徑）
    U_dripper = getattr(params, "U_liquid_dripper_W_m2K", None)
    use_area_exchange = U_dripper is not None and float(U_dripper) > 0.0
    if not use_area_exchange:
        warnings.warn(
            "U_liquid_dripper_W_m2K 未設定（None 或 0），退回已棄用的 lambda_liquid_dripper "
            "集總熱交換路徑。該係數隱含 U ≈ 1044 W/m²K，超出濕濾紙+陶瓷串聯的物理上界 "
            "[120, 550]；請改以 U_liquid_dripper_W_m2K 標定。",
            DeprecationWarning,
            stacklevel=2,
        )
    U_val = float(U_dripper) if use_area_exchange else 0.0

    # 床內各層的**瞬時**孔隙液量下限 [m³]（濃度分母的防除零 floor）。
    # What: V_liq_layer = layer_frac × (V_mob + V_imm)，但悶蒸最初期 V_pore → 0，
    #       直接當分母會讓 dC/dt 爆掉。floor 取定容值的 5%。
    # Why（F3）: 舊實作整段用定容 `layer_frac × φ·V_bed`，等於宣稱「孔隙一開始就滿」。
    #       kinu29 悶蒸期實測床內液量遠小於 φ·V_bed = 20.8 mL，
    #       用定容分母會把悶蒸期的床內濃度系統性稀釋掉，
    #       而 `M_balance_residual_g` 的 inventory 又用同一個定容量 —— 循環自洽，
    #       殘差查不出這個錯（AUD-3）。現在兩處都改吃同一個瞬時量。
    V_liq_layer_floor = params.V_liquid * 0.05 * layer_frac_col

    def liquid_volume_layers(V_pore):
        """床內各層瞬時液量 [m³]；`rhs` 與後處理 inventory 共用同一個定義。"""
        return np.maximum(layer_frac_col * V_pore, V_liq_layer_floor)

    def flow_state(t, V_free, V_mob, V_imm, V_abs, w, V_out, V_bed_cum, T, xi_pref):
        """
        單一時刻的完整水力狀態（rhs 與後處理共用）。

        What:
            注水 → 顆粒吸收 → 填 mobile 孔隙 → 自由水積水；
            床內 mobile 水被毛細捕捉成 immobile；出流由達西能力與供給上限共同決定。

        Why:
            舊版後處理另寫一份「重算流量」的程式碼，還把展示用的 `sat`（bloom 後
            硬設 1.0）餵回物理式，導致 q_* 偏 +0.19%、k_vals 局部差 12.6%、
            甚至出現負 bypass。診斷序列與 ODE 只要不是同一段程式，就必然會漂。
        """
        V_pore = V_mob + V_imm
        S_mob = params.mobile_saturation(V_mob, V_imm)
        h_free = params.h_free_from_volume(V_free)
        sat_abs = V_abs / V_full                       # 顆粒吸水飽和度（溶脹驅動量）
        impact = protocol.pour_start_impact(t, bloom_end_s=t_bloom_end, width_s=params.wetbed_impact_tau)
        Q_in = protocol.pour_rate(t)

        # ── 水量分流：注水 → 顆粒吸收 → 填 mobile 孔隙 → 自由水 ───────────────
        A_tot, A_free, A_mob = params.absorption_rate(V_abs, w, Q_in, V_free, V_mob, T)
        A_in = A_tot - A_free - A_mob
        Q_perc = Q_in - A_in
        P_fill, P_free = params.pore_fill_rate(V_mob, V_imm, Q_perc, V_free)
        P_stream = P_fill - P_free
        C_imm = params.immobile_capture_rate(V_mob, V_imm, w, T)

        # ── 出流：驅動頭 = h_free + S_mob·h_bed，導水能力由 kr(S_mob) 控制 ────
        area = max(params.area(params.h_bed + h_free), 1e-12)
        k_base = params.k_eff(
            V_bed_cum, sat_abs, h_free,
            q_in=0.0, u_pore=0.0, t_sec=t, bloom_end_s=None,
            pour_impact=impact,
        )
        psi_val = params.psi_eff(V_out)
        Q_ext_base = params.q_extract(h_free, k_base, T, t, sat=S_mob)
        Q_pref_base = params.q_preferential(
            h_free, xi_pref, T_K=T, t_sec=t, sat=S_mob, bloom_end_s=t_bloom_end
        )
        phi_eff = params.phi_effective(sat_abs, h_free)
        u_proxy = max(Q_ext_base + Q_pref_base, 0.0) / max(area * phi_eff, 1e-12)
        k_val = params.k_eff(
            V_bed_cum, sat_abs, h_free,
            q_in=Q_in, u_pore=u_proxy, t_sec=t, bloom_end_s=t_bloom_end,
            pour_impact=impact,
        )
        Q_ext = params.q_extract(h_free, k_val, T, t, sat=S_mob)
        Q_pref = params.q_preferential(
            h_free, xi_pref, T_K=T, t_sec=t, sat=S_mob, bloom_end_s=t_bloom_end
        )
        Q_bp = params.q_bypass(h_free, psi_val, T)
        Q_darcy = Q_ext + Q_pref + Q_bp

        # 供給上限：達西「能力」再大，也不能超過水真正拿得出來的量。
        # 三個來源：尚未進入任一水池的過床水流、自由水存量、mobile 孔隙水存量。
        s_stream = max(Q_perc - P_stream, 0.0)
        s_free = V_free / FREE_DRAIN_TAU_S
        s_mob = V_mob / FREE_DRAIN_TAU_S
        Q_avail = s_stream + s_free + s_mob
        Q_out = max(float(smooth_min(Q_darcy, Q_avail, RATE_SMOOTH_EPS)), 0.0)
        scale = Q_out / Q_darcy if Q_darcy > 1e-18 else 0.0
        Q_ext *= scale
        Q_pref *= scale
        Q_bp *= scale
        Q_bed = Q_ext + Q_pref
        inv_avail = 1.0 / max(Q_avail, 1e-18)
        Q_from_free = Q_out * s_free * inv_avail
        Q_from_mob = Q_out * s_mob * inv_avail
        Q_from_stream = Q_out - Q_from_free - Q_from_mob

        return {
            "h_free": h_free, "sat": sat_abs, "S_mob": S_mob, "V_pore": V_pore, "area": area,
            "Q_in": Q_in, "A_tot": A_tot, "A_in": A_in, "A_free": A_free, "A_mob": A_mob,
            "P_fill": P_fill, "P_free": P_free, "P_stream": P_stream, "C_imm": C_imm,
            "k_val": k_val, "psi_val": psi_val, "phi_eff": phi_eff,
            "Q_ext": Q_ext, "Q_pref": Q_pref, "Q_bed": Q_bed, "Q_bp": Q_bp, "Q_out": Q_out,
            "Q_from_free": Q_from_free, "Q_from_mob": Q_from_mob, "Q_from_stream": Q_from_stream,
        }

    def rhs(t, state):
        V_free = max(float(state[0]), 0.0)
        V_mob = max(float(state[1]), 0.0)
        V_imm = float(np.clip(state[2], 0.0, V_pore_max))
        V_abs = float(np.clip(state[3], 0.0, V_full))
        w = float(np.clip(state[4], 0.0, 1.0))
        V_out = float(state[5])
        V_bed_cum = float(state[6])
        C_fast_layers = np.maximum(np.asarray(state[c_fast_slice], dtype=float), 0.0).reshape(n_layers, n_bins)
        M_fast_layers = np.maximum(np.asarray(state[m_fast_slice], dtype=float), 0.0).reshape(n_layers, n_bins)
        C_slow_layers = np.maximum(np.asarray(state[c_slow_slice], dtype=float), 0.0).reshape(n_layers, n_bins)
        M_slow_layers = np.maximum(np.asarray(state[m_slow_slice], dtype=float), 0.0).reshape(n_layers, n_bins)
        T = float(np.clip(state[T_idx], params.T_amb, params.T_brew + 5.0))
        T_dripper = float(np.clip(state[T_dripper_idx], params.T_amb - 5.0, params.T_brew + 5.0))
        xi_pref = float(np.clip(state[pref_idx], 0.0, 1.0))

        fs = flow_state(t, V_free, V_mob, V_imm, V_abs, w, V_out, V_bed_cum, T, xi_pref)
        Q_in = fs["Q_in"]
        Q_bed, Q_out = fs["Q_bed"], fs["Q_out"]
        V_pore, h_free, S_mob = fs["V_pore"], fs["h_free"], fs["S_mob"]
        impact = protocol.pour_start_impact(t, bloom_end_s=t_bloom_end, width_s=params.wetbed_impact_tau)

        # ── 四個水池的收支：每一項都是「從某池搬到另一池」，守恆是代數恆等式 ──
        #   d(V_abs + V_imm + V_mob + V_free)/dt ≡ Q_in − Q_out
        dV_abs = fs["A_tot"]
        dV_imm = fs["C_imm"]
        dV_mob = fs["P_fill"] - fs["C_imm"] - fs["A_mob"] - fs["Q_from_mob"]
        dV_free = (
            Q_in - fs["A_in"] - fs["P_stream"] - fs["Q_from_stream"]
            - fs["A_free"] - fs["P_free"] - fs["Q_from_free"]
        )
        dw = params.wetting_rate(w, V_free + V_mob + V_imm + V_abs)

        # ── 萃取：bin-resolved 兩池一階釋放（Crank 球形擴散首項）─────────────
        # What:
        #     rel_x,i,layer = λ_x,i(T) · w · max(1 − C_x,layer / C_sat,x(T), 0) · M_x,i,layer
        #     λ_fast,i = π²·D_eff,fast(T) / δ_i²          （破壁殼層，δ_i = 殼層厚度）
        #     λ_slow,i = π²·D_eff,slow(T) / R_core,i²     （未破壁核心球）
        #     D_eff,x  = k_B·T /(6π·μ(T)·r_x) / τ_tort     （Stokes-Einstein + 曲折度）
        #
        # Why:
        #   1) **漸近方向**。Crank 的球形擴散解長時間由首項主導，退化成一階釋放：
        #      通量隨殘餘質量遞減。舊實作的 `exp(−L²/4Dt)` 乘子在 t → ∞ 時 → 1，
        #      也就是速率隨時間**遞增**——方向與 Crank 相反。slow 主導 bin 的
        #      該乘子整段 < 0.1，`nw_eta_slow = 118` 就是拿來補償它的（AUD-3）。
        #   2) **bin 相對次序**。λ_i ∝ 1/L_i² 讓「細顆粒快、粗顆粒慢」由幾何唯一決定，
        #      不像舊乘子會隨 t 把 bin 次序翻過來。
        #   3) **潤濕 gate `w`**。取代舊的 `t_eff = max(t_sec, t_floor)`：後者用的是
        #      全域時鐘而非接觸時間，`t_floor = 5 s` 實際上從未生效（AUD-3）。
        #      `w`（F2b 的床層潤濕狀態）才是「溶質有沒有液相可以擴散進去」的物理量：
        #      乾床 w = 0 ⇒ 不釋放，與 retained_mass 標定出的潤濕時序自洽。
        #   4) **驅動力**。`(1 − C/C_sat)` 是溶解平衡的 cutoff；殘餘質量的衰減
        #      由 `·M` 本身攜帶，不再另外乘 `(M/M₀)^β`（那會把同一個衰減數兩次）。
        #      Hill flow_factor 一併移除：球體 Sherwood 數在 Re → 0 仍有下限 2，
        #      沒有「靜置時傳質掉到 1/10」這回事。
        lam_fast_bins = params.lambda_fast_bins(T)
        lam_slow_bins = params.lambda_slow_bins(T)
        drive_fast = np.maximum(1.0 - C_fast_layers / max(params.C_sat_fast_T(T), 1e-12), 0.0)
        drive_slow = np.maximum(1.0 - C_slow_layers / max(params.C_sat_slow_T(T), 1e-12), 0.0)
        # 釋放質量率 [g/s]（>= 0）
        rel_fast_layers = lam_fast_bins[None, :] * w * drive_fast * M_fast_layers
        rel_slow_layers = lam_slow_bins[None, :] * w * drive_slow * M_slow_layers

        # 粉床孔隙串接 CSTR 濃度更新：上層先吃稀釋，下層決定出液濃度。
        # 濃度分母改用**瞬時**床內液量（見 `liquid_volume_layers`），因此
        # 必須以「溶質存量 N = C·V」寫守恆，再換算回 dC：
        #     dN_j/dt = rel_j + Q_bed·(C_{j−1} − C_j)
        #     dC_j/dt = (dN_j/dt − C_j·dV_j/dt) / V_j
        # 少了 `− C_j·dV_j/dt` 這一項，孔隙充水時濃度不會被稀釋，
        # 溶質會憑空增加（實測 M_balance 殘差 2.2 g）。
        V_liq_layers_now = liquid_volume_layers(V_pore)
        dV_pore = dV_mob + dV_imm
        # floor 生效時 V_j 被釘住，dV_j/dt = 0（否則會在 floor 上製造假的稀釋項）
        dV_liq_layers = np.where(
            layer_frac_col * V_pore > V_liq_layer_floor,
            layer_frac_col * dV_pore,
            0.0,
        )
        C_fast_upstream = np.vstack([np.zeros((1, n_bins), dtype=float), C_fast_layers[:-1]])
        C_slow_upstream = np.vstack([np.zeros((1, n_bins), dtype=float), C_slow_layers[:-1]])
        # rel [g/s] → [kg/s]（×1e-3）才能與 Q_bed[m³/s]·C[kg/m³] 同單位
        dC_fast_layers = (
            rel_fast_layers * 1e-3 + Q_bed * (C_fast_upstream - C_fast_layers)
            - C_fast_layers * dV_liq_layers
        ) / V_liq_layers_now
        dM_fast_layers = -rel_fast_layers
        dC_slow_layers = (
            rel_slow_layers * 1e-3 + Q_bed * (C_slow_upstream - C_slow_layers)
            - C_slow_layers * dV_liq_layers
        ) / V_liq_layers_now
        dM_slow_layers = -rel_slow_layers

        # ── 熱動方程：液體節點含「孔隙 + 自由水 + 吸收水 + 粉體當量」────────
        # 完整焓平衡 d(V_th·T)/dt = Q_in·T_brew − Q_out·T − losses；
        # 由於 d(V_abs + V_pore + V_free)/dt ≡ Q_in − Q_out（水量守恆），展開後
        #   V_th·dT/dt = Q_in·(T_brew − T) − losses
        # 完全相消，不再有舊版「註解假設 dV/dt = Q_in_free − Q_out、實際是 φ·(…)」
        # 造成的 44.6× 漏項。
        # Why 用全量 Q_in：被顆粒吸收的水（29 mL @ 92 °C，8.4 kJ = 10.7% E_in）
        #      同樣把熱帶進系統，且它的熱容 V_abs 也計在 V_th 裡；
        #      舊版用 Q_in_free 等於把這份焓與熱容一起丟掉。
        V_th = V_pore + V_free + V_abs + params.V_equiv_coffee
        h_total = params.wetted_height(V_pore / V_pore_max, h_free)
        if C_dripper_J_K <= 0.0:
            # 沒有濾杯熱節點（dripper_mass_g = 0）時交換必須為 0：
            # 否則熱量流進一個熱容為零、溫度永不上升的節點，等於憑空消失。
            exchange_W = 0.0
        elif use_area_exchange:
            exchange_W = U_val * params.wetted_area(h_total) * (T - T_dripper)
        else:
            exchange_W = rho_cp * V_th * params.lambda_liquid_dripper * (T - T_dripper)
        dT = (Q_in / V_th) * (params.T_brew - T) \
             - params.lambda_cool * (T - params.T_amb) \
             - exchange_W / max(rho_cp * V_th, 1e-12)

        # 濾杯節點：收到等量熱流（除以自身熱容），再對環境自然對流散熱
        if C_dripper_J_K > 0.0:
            dT_dripper = (
                exchange_W / C_dripper_J_K
                - params.lambda_dripper_ambient * (T_dripper - params.T_amb)
            )
        else:
            dT_dripper = 0.0

        dxi_pref = params.d_preferential_flow_dt(
            xi_pref,
            q_in=Q_in,
            pour_impact=impact,
            t_sec=t,
            bloom_end_s=t_bloom_end,
        )

        return np.concatenate((
            np.array([dV_free, dV_mob, dV_imm, dV_abs, dw, Q_out, Q_bed, Q_in], dtype=float),
            dC_fast_layers.reshape(-1),
            dM_fast_layers.reshape(-1),
            dC_slow_layers.reshape(-1),
            dM_slow_layers.reshape(-1),
            np.array([dT, dT_dripper, dxi_pref], dtype=float),
        ))

    t_eval = np.linspace(0, t_end, n_eval)
    # 初值：T(0) = T_dripper(0) = T_initial_K（量測到的預熱溫度），未提供時退回 T_amb。
    # 第一注熱量由 ODE 自身的 Q_in·(T_brew − T) 項累積，不另外預混 T_shock，
    # 否則第一注能量會被雙重計入。
    T0 = float(params.T_initial_K) if getattr(params, "T_initial_K", None) is not None else float(params.T_amb)
    # 基礎狀態初值全為 0（乾床、未潤濕 w(0) = 0、尚未注水）
    y0 = np.concatenate((
        np.zeros(_N_BASE_STATES, dtype=float),
        np.zeros(n_axial, dtype=float),
        M_fast_0_layers.reshape(-1),
        np.zeros(n_axial, dtype=float),
        M_slow_0_layers.reshape(-1),
        np.array([T0, T0, 0.0], dtype=float),
    ))

    # 在注水率斷點間分段積分（`_solve_piecewise` 的 Why；F13-C）
    t, Y = _solve_piecewise(
        rhs,
        t_end,
        y0,
        t_eval,
        protocol.rate_breakpoints(),
        # RK45 + 加密步長（max_step=0.5）
        # 選用理由（2026-09-24 實測：kinu29 4:11 calibrated、k×4.5、n_eval=1200、
        # t_end=180、max_step=0.5，best-of-3）：
        # - RK45   0.81 s，V_out(180) = 257.6336 mL，水量殘差 3.6e-13 mL（基準）
        # - LSODA  0.67 s，V_out(180) = 257.9122 mL，水量殘差 1.0e-12 mL
        #   → LSODA 確實可用且快約 17%，但末值差 0.28 mL（0.1%），已接近
        #     V_out RMSE 的可辨識尺度；模型含 clip/softplus 等非光滑項，
        #     LSODA 的 BDF 分支在這些折角上的雅可比估算風險較高。
        # - h_cap 附近 softplus 梯度 ~1/HEAD_SOFTPLUS_EPS_M = 2000 m⁻¹，
        #   以 max_step = 0.5 s 足以解析。
        # 結論：預設維持 RK45；大規模掃描要換 LSODA 時應先確認該 case 的末值差異。
        method="RK45",
        rtol=rtol,
        atol=atol,
        max_step=max_step,  # 預設 0.5；fitting 可暫用較粗步長，再以高精度回算 final
    )

    # ── 狀態還原（一律以 ODE 原始狀態為準，不再用展示值回餵物理）────────────
    V_free = np.maximum(Y[0], 0.0)
    V_mob = np.maximum(Y[1], 0.0)
    V_imm = np.clip(Y[2], 0.0, V_pore_max)
    V_abs = np.clip(Y[3], 0.0, V_full)
    w_wet = np.clip(Y[4], 0.0, 1.0)
    V_out = Y[5]
    V_bed = Y[6]
    V_poured = Y[7]
    V_pore = V_mob + V_imm
    S_bed = np.clip(V_pore / V_pore_max, 0.0, 1.0)        # 既有介面：床內孔隙總飽和度
    S_mob = params.mobile_saturation(V_mob, V_imm)
    h_free = params.h_free_from_volume(V_free)
    h_total = params.wetted_height(S_bed, h_free)
    sat = V_abs / V_full                                  # 既有介面：sat = 顆粒吸水飽和度

    C_fast_layers = np.maximum(Y[c_fast_slice], 0.0).reshape(n_layers, n_bins, -1)
    M_fast_layers = np.maximum(Y[m_fast_slice], 0.0).reshape(n_layers, n_bins, -1)
    C_slow_layers = np.maximum(Y[c_slow_slice], 0.0).reshape(n_layers, n_bins, -1)
    M_slow_layers = np.maximum(Y[m_slow_slice], 0.0).reshape(n_layers, n_bins, -1)
    C_fast_bins_mean = np.tensordot(layer_frac, C_fast_layers, axes=(0, 0))
    C_slow_bins_mean = np.tensordot(layer_frac, C_slow_layers, axes=(0, 0))
    C_fast = np.sum(C_fast_bins_mean, axis=0)
    M_fast = np.sum(M_fast_layers, axis=(0, 1))
    C_slow = np.sum(C_slow_bins_mean, axis=0)
    M_slow = np.sum(M_slow_layers, axis=(0, 1))
    C_fast_out = np.sum(C_fast_layers[-1], axis=0)
    C_slow_out = np.sum(C_slow_layers[-1], axis=0)
    C_bed_top = np.sum(C_fast_layers[0] + C_slow_layers[0], axis=0)
    C_bed_bottom = np.sum(C_fast_layers[-1] + C_slow_layers[-1], axis=0)
    T_raw = Y[T_idx]
    T_dripper_raw = Y[T_dripper_idx]
    T_K = np.clip(T_raw, params.T_amb, params.T_brew + 5.0)
    T_dripper_K = np.clip(T_dripper_raw, params.T_amb - 5.0, params.T_brew + 5.0)
    # clip 診斷：clip 會破壞能量守恆，必須可觀測而不是靜靜吞掉
    clip_tol = 1e-9
    clip_mask = (np.abs(T_raw - T_K) > clip_tol) | (np.abs(T_dripper_raw - T_dripper_K) > clip_tol)
    clip_active_fraction = float(np.mean(clip_mask)) if clip_mask.size else 0.0
    if clip_active_fraction > 0.01:
        warnings.warn(
            f"熱模型溫度 clip 在 {clip_active_fraction*100:.1f}% 的輸出點上作用（> 1%）；"
            "能量帳會出現對應量級的殘差，請先檢查熱端 closure 而非繼續調參。",
            RuntimeWarning,
            stacklevel=2,
        )
    xi_pref = np.clip(Y[pref_idx], 0.0, 1.0)
    M_sol = M_fast + M_slow             # 向後相容：總剩餘固相

    # ── 流量分量：逐點呼叫與 rhs 同一個 flow_state，診斷序列因此不可能與 ODE 漂移 ──
    _fs = [
        flow_state(float(ti), float(vf), float(vm), float(vi), float(va), float(ww),
                   float(vo), float(vb), float(Ti), float(xi))
        for ti, vf, vm, vi, va, ww, vo, vb, Ti, xi
        in zip(t, V_free, V_mob, V_imm, V_abs, w_wet, V_out, V_bed, T_K, xi_pref)
    ]
    _get = lambda key: np.array([f[key] for f in _fs], dtype=float)  # noqa: E731
    q_ext = _get("Q_ext")
    q_pref = _get("Q_pref")
    q_bed = _get("Q_bed")
    q_bp = _get("Q_bp")
    q_out = _get("Q_out")
    k_vals = _get("k_val")
    psi_vals = _get("psi_val")
    phi_eff_arr = _get("phi_eff")
    area_arr = np.maximum(_get("area"), 1e-12)
    q_in_raw = _get("Q_in")

    drive_components = params.bed_drive_components(h_free, T_K=T_K, t_sec=t, sat=S_mob)
    h_threshold_arr = np.asarray(drive_components["h_threshold"], dtype=float)
    h_threshold_eff_arr = np.asarray(drive_components["h_threshold_eff"], dtype=float)
    h_cap_wet_arr = np.asarray(drive_components["h_cap_wet"], dtype=float)
    h_bed_drive_arr = np.asarray(drive_components["h_bed_drive"], dtype=float)
    h_eff_arr = np.asarray(drive_components["h_eff"], dtype=float)

    u_pore = np.where(q_bed > 1e-12, q_bed / np.maximum(area_arr * phi_eff_arr, 1e-12), 0.0)
    fine_drag = np.abs(u_pore) * np.array([params.mu_water(Ti) for Ti in T_K]) * params.fine_radius()
    sat_flow_arr = np.asarray(params.flow_saturation(sat, t, t_bloom_end), dtype=float)
    kr_sat_arr = np.asarray(params.relative_permeability(S_mob), dtype=float)

    # ── 累積量：全部由 ODE 狀態直接換算，不再用矩形和重算 ────────────────────
    v_in_ml = V_poured * 1e6
    v_in_eff_ml = (V_poured - V_abs) * 1e6
    v_out_ml = V_out * 1e6
    v_bed_ml = V_bed * 1e6
    v_extract_ml = v_bed_ml          # 同一個 ODE 狀態；語意即「經過粉床的累積體積」
    v_abs_ml = V_abs * 1e6
    v_pore_ml = V_pore * 1e6
    v_mob_ml = V_mob * 1e6
    v_imm_ml = V_imm * 1e6
    v_free_ml = V_free * 1e6
    retained_ml = v_abs_ml + v_pore_ml + v_free_ml
    water_balance_residual_ml = v_in_ml - v_out_ml - retained_ml

    dV_bed = np.diff(V_bed, prepend=V_bed[0])

    _q_out_safe = np.where(q_out > 1e-12, q_out, 1.0)  # 防止零除（h_free < h_cap 時 q_out=0）
    bypass_ratio = np.where(q_out > 1e-12, q_bp / _q_out_safe, 0.0)
    pref_ratio = np.where(q_out > 1e-12, q_pref / _q_out_safe, 0.0)
    head_gate = np.clip(
        h_eff_arr / np.maximum(h_free + h_bed_drive_arr + h_cap_wet_arr, 1e-12), 0.0, 1.0
    )
    bloom_mask = t <= t_bloom_end
    if np.any(bloom_mask):
        choke_means = {
            "sat_flow": float(np.mean(1.0 - sat_flow_arr[bloom_mask])),
            "kr_sat": float(np.mean(1.0 - kr_sat_arr[bloom_mask])),
            "h_cap_h_gas": float(np.mean(1.0 - head_gate[bloom_mask])),
        }
        dominant_bloom_choke = max(choke_means, key=choke_means.get)
    else:
        choke_means = {"sat_flow": 0.0, "kr_sat": 0.0, "h_cap_h_gas": 0.0}
        dominant_bloom_choke = "n/a"

    # ── TDS 後處理（多組分）──────────────────────────────────────────────────
    C_bed = C_fast + C_slow    # 總粉層濃度（用於向後相容 plot_tds/compare_corrections）

    _mf_safe = params.M_fast_0 if params.M_fast_0 > 0 else 1e-10
    _ms_safe = params.M_slow_0 if params.M_slow_0 > 0 else 1e-10
    C_sat_fast_arr = params.C_sat_fast * (1.0 + params.alpha_C_fast * (T_K - params.T_ref))
    C_sat_slow_arr = params.C_sat_slow * (1.0 + params.alpha_C_slow * (T_K - params.T_ref))
    C_sat_eff = (C_sat_fast_arr / _mf_safe * M_fast * float(params.M_fast_0 > 0)
               + C_sat_slow_arr / _ms_safe * M_slow * float(params.M_slow_0 > 0))

    # 下壺瞬時濃度（旁路稀釋後）
    C_bed_out = C_fast_out + C_slow_out
    C_out = np.where(q_out > 1e-12, q_bed * C_bed_out / _q_out_safe, 0.0)

    # 累積萃取質量：以 ODE 狀態增量 dV_bed 積分，與 v_extract_ml 自洽
    M_fast_ext_g = np.cumsum(dV_bed * C_fast_out) * 1e3
    M_slow_ext_g = np.cumsum(dV_bed * C_slow_out) * 1e3
    M_extracted_g = M_fast_ext_g + M_slow_ext_g

    v_out_L = np.maximum(v_out_ml * 1e-3, 1e-9)
    TDS_gl = M_extracted_g / v_out_L
    TDS_fast_gl = M_fast_ext_g / v_out_L
    TDS_slow_gl = M_slow_ext_g / v_out_L

    _dose_safe = params.dose_g if params.dose_g > 0 else 1.0
    _ey_scale = 100.0 / _dose_safe if params.dose_g > 0 else 0.0
    EY_cup_pct = M_extracted_g * _ey_scale
    EY_fast_cup_pct = M_fast_ext_g * _ey_scale
    EY_slow_cup_pct = M_slow_ext_g * _ey_scale

    M_dissolved_g = params.M_sol_0 - M_sol
    EY_dissolved_pct = M_dissolved_g * _ey_scale
    EY_pct = EY_cup_pct

    # 溶質守恆審計：已溶出 = 入杯 + 床內液相 inventory
    # inventory 用與 `rhs` 完全相同的**瞬時**液量（`liquid_volume_layers`）。
    # Why: 舊版兩處都用定容 `layer_frac × φ·V_bed`，於是殘差對「分母用錯」這件事
    #      完全免疫——一個查不出自己錯誤的守恆審計等於沒有審計（AUD-3）。
    V_liq_layers_t = np.maximum(
        layer_frac[:, None] * V_pore[None, :],
        (params.V_liquid * 0.05 * layer_frac)[:, None],
    )                                                   # shape (n_layers, n_t)
    M_liquid_inventory_g = np.sum(
        (C_fast_layers + C_slow_layers) * V_liq_layers_t[:, None, :],
        axis=(0, 1),
    ) * 1e3
    M_balance_residual_g = M_dissolved_g - M_extracted_g - M_liquid_inventory_g

    # ── 能量審計（累積焓帳；參考溫度可任選，殘差對其不變）───────────────────
    V_th = V_pore + V_free + V_abs + params.V_equiv_coffee

    def _energy_audit(T_ref_K: float) -> tuple[np.ndarray, float]:
        """
        What: 回傳 (累積能量殘差 [J], E_in 總量 [J])，參考溫度為 `T_ref_K`。
        Why:  焓是相對量；若審計寫錯（例如漏掉吸收水的熱容），殘差會隨參考溫度漂移。
              以兩個參考溫度交叉檢查，可證明帳目本身而不是剛好對上一個數字。
        """
        e_in = rho_cp * (params.T_brew - T_ref_K) * V_poured
        # ∫ρc(T−T_ref)dV_out：直接對狀態 V_out 積分，與 ODE 出流完全一致
        theta = T_K - T_ref_K
        e_out = rho_cp * np.concatenate((
            [0.0], np.cumsum(0.5 * (theta[1:] + theta[:-1]) * np.diff(V_out))
        )) if t.size > 1 else np.zeros_like(t)
        e_store = rho_cp * V_th * theta + C_dripper_J_K * (T_dripper_K - T_ref_K)
        e_store = e_store - e_store[0]
        e_cool = rho_cp * _cumtrapz(V_th * params.lambda_cool * (T_K - params.T_amb), t)
        e_damb = C_dripper_J_K * params.lambda_dripper_ambient * _cumtrapz(T_dripper_K - params.T_amb, t)
        return e_in - e_out - e_store - e_cool - e_damb, float(e_in[-1]) if e_in.size else 0.0

    energy_residual_J, E_in_total_J = _energy_audit(params.T_amb)
    energy_residual_ref0_J, _ = _energy_audit(0.0)
    energy_residual_fraction = float(
        np.max(np.abs(energy_residual_J)) / max(abs(E_in_total_J), 1e-9)
    )

    # ── 時間標記 ────────────────────────────────────────────────────────────
    # brew_time：自由水柱降到出口毛細截止高度 h_cap 以下 → 床頂積水不再驅動流動。
    #   Why 用 h_cap 而非 0：h_free < h_cap 之後 h_eff 已被 softplus 壓到 ~1e-5 m，
    #   出流僅剩 <0.01 mL/s，殘餘水膜要數百秒才真正歸零，取 0 會退化成 t_end。
    # drain_time：床層出口流量跌破 0.05 mL/s（與 observation 層停流門檻同一數值）。
    t_last_pour = protocol.last_pour_end()
    mask_after = t > t_last_pour
    brew_time = _first_downcrossing(t, h_free, params.h_cap, mask_after)
    if brew_time is None:
        brew_time = t_end
    drain_time = _first_downcrossing(t, q_out * 1e6, 0.05, mask_after)
    if drain_time is None:
        drain_time = t_end

    return dict(
        t            = t,
        h_mm         = h_total * 1e3,
        h_free_mm    = h_free * 1e3,
        S_bed        = S_bed,
        S_mob        = S_mob,
        w_wet        = w_wet,
        tau_wet_s    = float(params.tau_wet_s),
        bed_retention_fraction = float(params.bed_retention_fraction(params.T_brew)),
        dose_g       = params.dose_g,          # 粉重（供 LRR 驗算）
        f_abs        = params.absorb_full_ratio,  # 充分浸潤吸水率 [mL/g]
        D10_um       = params.D10 * 1e6,
        shell_ratio  = params.shell_accessibility_ratio,
        area_ratio   = params.surface_area_ratio,
        phi_eff      = phi_eff_arr,
        u_pore_mps   = u_pore,
        fine_drag_N  = fine_drag,
        q_in_mlps    = q_in_raw * 1e6,
        q_in_eff_mlps= q_in_raw * 1e6,   # 注水不再被 sat 節流；保留鍵以維持既有繪圖介面
        q_ext_mlps   = q_ext    * 1e6,
        q_pref_mlps  = q_pref   * 1e6,
        q_bed_mlps   = q_bed    * 1e6,
        q_bp_mlps    = q_bp     * 1e6,
        q_out_mlps   = q_out    * 1e6,
        k_vals       = k_vals,
        psi_vals     = psi_vals,
        v_in_ml      = v_in_ml,
        v_in_eff_ml  = v_in_eff_ml,
        v_out_ml     = v_out_ml,
        v_bed_ml     = v_bed_ml,
        v_extract_ml = v_extract_ml,
        V_abs_ml     = v_abs_ml,
        V_pore_ml    = v_pore_ml,
        V_mob_ml     = v_mob_ml,
        V_imm_ml     = v_imm_ml,
        V_free_ml    = v_free_ml,
        retained_ml  = retained_ml,
        water_balance_residual_ml = water_balance_residual_ml,
        energy_balance_residual_J = energy_residual_J,
        energy_balance_residual_ref0_J = energy_residual_ref0_J,
        energy_input_J = E_in_total_J,
        energy_residual_fraction = energy_residual_fraction,
        clip_active_fraction = clip_active_fraction,
        bypass_ratio = bypass_ratio,
        pref_ratio   = pref_ratio,
        sat          = sat,
        sat_flow     = sat_flow_arr,
        kr_sat       = kr_sat_arr,
        head_gate    = head_gate,
        h_gas_mm     = np.asarray(params.h_gas(t), dtype=float) * 1e3,
        h_threshold_mm = h_threshold_arr * 1e3,
        h_threshold_eff_mm = h_threshold_eff_arr * 1e3,
        h_cap_wet_mm = h_cap_wet_arr * 1e3,
        h_bed_drive_mm = h_bed_drive_arr * 1e3,
        h_cap_bed_mm = float(params.h_cap_bed(params.T_brew)) * 1e3,
        h_eff_mm     = h_eff_arr * 1e3,
        bloom_end_s  = float(t_bloom_end),
        bloom_choke_means = choke_means,
        dominant_bloom_choke = dominant_bloom_choke,
        pref_flow_state = xi_pref,
        extraction_bin_count = n_bins,
        axial_node_count = n_layers,
        C_fast_bins_gl = C_fast_bins_mean,
        C_slow_bins_gl = C_slow_bins_mean,
        C_fast_layers_gl = C_fast_layers,
        C_slow_layers_gl = C_slow_layers,
        M_fast_bins_g = np.sum(M_fast_layers, axis=0),
        M_slow_bins_g = np.sum(M_slow_layers, axis=0),
        M_fast_layers_g = M_fast_layers,
        M_slow_layers_g = M_slow_layers,
        # 萃取閉合診斷（F3）：λ 以 T_brew 評估，是各 bin 的釋放速率尺度
        tau_tort               = float(params.tau_tort),
        lambda_fast_bins_s_inv = params.lambda_fast_bins(params.T_brew),
        lambda_slow_bins_s_inv = params.lambda_slow_bins(params.T_brew),
        ext_bin_shell_depth_m  = np.asarray(params.ext_bin_shell_depth_m, dtype=float),
        ext_bin_core_radius_m  = np.asarray(params.ext_bin_core_radius_eff_m, dtype=float),
        M_fast_0_bins_g        = np.asarray(params.M_fast_0_bins, dtype=float),
        M_slow_0_bins_g        = np.asarray(params.M_slow_0_bins, dtype=float),
        V_liq_layers_ml        = V_liq_layers_t * 1e6,
        brew_time    = brew_time,
        drain_time   = drain_time,
        # TDS + 固相耗盡（v7 多組分）
        C_bed_gl         = C_bed,
        C_fast_gl        = C_fast,
        C_slow_gl        = C_slow,
        C_bed_top_gl     = C_bed_top,
        C_bed_bottom_gl  = C_bed_bottom,
        C_out_bed_gl     = C_bed_out,
        C_sat_eff_gl     = C_sat_eff,
        C_out_gl         = C_out,
        M_sol_g          = M_sol,
        M_fast_g         = M_fast,
        M_slow_g         = M_slow,
        M_extracted_g    = M_extracted_g,
        M_dissolved_g    = M_dissolved_g,
        M_liquid_inventory_g = M_liquid_inventory_g,
        M_balance_residual_g = M_balance_residual_g,
        TDS_gl           = TDS_gl,
        TDS_fast_gl      = TDS_fast_gl,
        TDS_slow_gl      = TDS_slow_gl,
        EY_pct           = EY_pct,
        EY_cup_pct       = EY_cup_pct,
        EY_fast_cup_pct  = EY_fast_cup_pct,
        EY_slow_cup_pct  = EY_slow_cup_pct,
        EY_dissolved_pct = EY_dissolved_pct,
        # 熱力學
        T_K              = T_K,
        T_C              = T_K - 273.15,
        T_dripper_K      = T_dripper_K,
        T_dripper_C      = T_dripper_K - 273.15,
        lambda_server_ambient = float(getattr(params, "lambda_server_ambient", 0.0)),
    )


def print_summary(results: dict, label: str = "") -> None:
    """
    What: 格式化輸出 simulate_brew() 結果摘要至 stdout。
    Why:  提供一致且可掃描的診斷輸出，便於快速評估沖煮品質。
    """
    tag = f"  [{label}]" if label else ""
    v_out = results["v_out_ml"][-1]
    v_ext = results["v_extract_ml"][-1]
    v_bp  = v_out - v_ext

    print("=" * 54)
    print(f"  V60 手沖模擬摘要{tag}")
    print("=" * 54)
    brew_time = results.get("brew_time", results["drain_time"])
    print(f"  沖煮時間       : {brew_time:.1f} s  (自由水柱 < h_cap)")
    print(f"  滴濾結束時間   : {results['drain_time']:.1f} s  (q_out < 0.05 mL/s)")
    print(f"  總注水量       : {results['v_in_ml'][-1]:.1f} mL")
    print(f"  有效水量（扣吸）: {results['v_in_eff_ml'][-1]:.1f} mL")
    print(f"  總出液量       : {v_out:.1f} mL")
    if v_out > 0:
        print(f"    ├ 萃取液     : {v_ext:.1f} mL  ({v_ext/v_out*100:.1f}%)")
        print(f"    └ 旁路液     : {v_bp:.1f} mL  ({v_bp/v_out*100:.1f}%)")
    if "retained_ml" in results:
        print("  ── 水量守恆 ──────────────────────────────────")
        print(f"    模型保水      : {results['retained_ml'][-1]:.1f} mL")
        print(f"      ├ 顆粒吸收  : {results['V_abs_ml'][-1]:.1f} mL")
        print(f"      ├ 孔隙 immobile: {results.get('V_imm_ml', results['V_pore_ml'])[-1]:.1f} mL")
        print(f"      ├ 孔隙 mobile  : {results.get('V_mob_ml', np.zeros(1))[-1]:.1f} mL")
        print(f"      └ 自由水    : {results['V_free_ml'][-1]:.1f} mL")
        if "w_wet" in results:
            print(f"    潤濕狀態 w    : {results['w_wet'][-1]:.3f}"
                  f"   (tau_wet = {results.get('tau_wet_s', float('nan')):.0f} s,"
                  f" f_retain = {results.get('bed_retention_fraction', float('nan')):.2f})")
        res_max = float(np.max(np.abs(results["water_balance_residual_ml"])))
        print(f"    守恆殘差 max  : {res_max:.4f} mL")
    if "energy_residual_fraction" in results:
        print(f"    能量殘差 max  : {results['energy_residual_fraction']*100:.2f}% E_in"
              f"   (T clip {results['clip_active_fraction']*100:.1f}%)")
    if "q_pref_mlps" in results:
        pref_share = float(np.mean(results.get("pref_ratio", np.zeros_like(results["q_out_mlps"])))) * 100.0
        print(f"  平均快路徑占比 : {pref_share:.1f}%")
    print(f"  峰值水位       : {results['h_mm'].max():.1f} mm"
          f"  (自由水柱峰值 {results['h_free_mm'].max():.1f} mm)")
    print(f"  峰值出水速度   : {results['q_out_mlps'].max():.2f} mL/s")
    k0  = results["k_vals"][0]
    k_f = results["k_vals"][-1]
    print(f"  k 衰減比       : {k_f/k0:.2f}  ({k0:.2e} → {k_f:.2e} m²)")
    if "D10_um" in results:
        print(f"  D10 / 殼層比   : {results['D10_um']:.0f} μm  /  {results['shell_ratio']:.2f}×")
    if "u_pore_mps" in results:
        print(f"  峰值孔隙流速   : {results['u_pore_mps'].max():.4f} m/s")
    if "fine_drag_N" in results:
        print(f"  峰值細粉拖曳力 : {results['fine_drag_N'].max():.2e} N")
    print(f"  最終 TDS       : {results['TDS_gl'][-1]:.2f} g/L  ({results['TDS_gl'][-1]/10:.2f}%)")
    print(f"  EY（入壺）     : {results['EY_cup_pct'][-1]:.1f}%")
    print(f"  EY（已溶出）   : {results['EY_dissolved_pct'][-1]:.1f}%")
    print(f"  └ 差值（留杯） : {results['EY_dissolved_pct'][-1]-results['EY_cup_pct'][-1]:.1f}%")
    print(f"  粉層峰值濃度   : {results['C_bed_gl'].max():.1f} g/L")
    print(f"  固相剩餘溶質   : {results['M_sol_g'][-1]:.2f} g / {results['M_sol_g'][0]:.2f} g")
    # ── LRR 質量守恆驗算 ────────────────────────────────────────────────────
    # LRR = 模型保水 / 粉重 = (W − B) / D [mL/g]
    # Why: 舊版用 Gagné 公式 (W − B(1−C))/D 反推，等於用量測 TDS 修正模型出液量，
    #      一旦模型保水本身錯了（舊模型 30.2 mL vs 量測 52.1 g）也看不出來。
    #      直接印模型自己的保水率，才是對水量帳的驗算。
    #      V60 合理區間 ~1.8–3.0 mL/g（Gagné 典型 2.2；kinu29 4:11 量測 2.6）。
    if "dose_g" in results:
        W   = float(results["v_in_ml"][-1])
        B   = float(results["v_out_ml"][-1])
        C   = float(results["TDS_gl"][-1]) / 1000.0   # g/L → 無量綱分率
        D   = results["dose_g"]
        f_a = results["f_abs"]
        lrr = (W - B) / D if D > 0 else float("nan")
        ey_lrr = (C / (1.0 - C)) * (W / D - f_a) if D > 0 else float("nan")
        print("  ── LRR 質量守恆驗算 ──────────────────────────")
        print(f"    LRR（模型保水） : {lrr:.2f} mL/g  （V60 合理區間 1.8–3.0）")
        if not (1.8 <= lrr <= 3.0):
            print(f"    WARNING: LRR = {lrr:.2f} 落在 [1.8, 3.0] 之外 —— "
                  f"先檢查水量帳（吸水 / 孔隙 hold-up），不要直接調 k。")
        print(f"    EY（LRR 公式）  : {ey_lrr*100:.1f}%  （vs 模型 EY {results['EY_cup_pct'][-1]:.1f}%）")
    if "EY_fast_cup_pct" in results:
        ey_fast = results["EY_fast_cup_pct"][-1]
        ey_slow = results["EY_slow_cup_pct"][-1]
        total   = ey_fast + ey_slow
        ratio   = ey_fast / total * 100 if total > 0 else 50.0
        print(f"  風味分解（入壺）:")
        print(f"    ├ Fast（酸/甜）: EY={ey_fast:.1f}%  TDS={results['TDS_fast_gl'][-1]:.1f} g/L")
        print(f"    └ Slow（苦/澀）: EY={ey_slow:.1f}%  TDS={results['TDS_slow_gl'][-1]:.1f} g/L")
        print(f"    風味平衡 Fast% = {ratio:.0f}%  （越高越明亮/酸，越低越苦）")
        # ── 風味診斷標籤（CVA 邏輯，優先級：萃取完整性 > 平衡傾向）──────────
        ey_cup = results["EY_cup_pct"][-1]
        tds    = results["TDS_gl"][-1]
        fast_ratio = ratio / 100.0
        if ey_cup < 17.0:
            flavor_tag = "Under-extracted ⚠  （萃取不足：甜感與酸質均未發展完全）"
        elif ey_cup > 23.0:
            flavor_tag = "Over-extracted  ⚠  （過度萃取：苦澀物質過量釋放）"
        elif fast_ratio > 0.55:
            flavor_tag = "Bright & Acidic    （明亮酸質主導：有機酸/糖類充分，苦韻偏弱）"
        elif fast_ratio < 0.45:
            flavor_tag = "Heavy & Bitter     （厚重苦韻主導：Slow 組分過度發展）"
        else:
            flavor_tag = "Balanced           （均衡發展：Fast/Slow 在 SCA 黃金窗口內）"
        if tds < 11.0:
            flavor_tag += "  [淡薄]"
        elif tds > 14.5:
            flavor_tag += "  [濃烈]"
        print(f"  ── 風味診斷 ──────────────────────────────────")
        print(f"    {flavor_tag}")
    if "T_C" in results:
        T_start = results["T_C"][0]
        T_end   = results["T_C"][-1]
        print(f"  水溫變化       : {T_start:.1f}°C → {T_end:.1f}°C  (Δ{T_start-T_end:.1f}°C)")
    print("=" * 54)
