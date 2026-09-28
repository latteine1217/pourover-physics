"""
analysis.py — V60 手沖模擬：分析與最佳化模組

What:
  保留一般分析與最佳化工具，包含：
    1. sensitivity_analysis  — OAT 靈敏度分析（龍捲風圖 + 2D 熱圖）
    2. compare_grind_linkage — k–M 聯動 vs 獨立模型對比
    3. find_optimal_grind    — 以 scipy.optimize.minimize_scalar 搜尋最佳研磨度
  並作為 benchmark / identifiability 工具的相容轉發層。

Why:
  將「一般分析」與「正式驗證線」分開後，
  本模組應專注於可重複使用的探索型工具，同時維持舊 import 路徑不破壞 userspace。

NOTE: P0/P1 重構後，`scan_wetbed_structure` 已移除——χ 結構態被併入 `f_post`，
      不再以獨立 ODE 形式存在；對應的 identifiability 分析改由
      ``pour_over.identifiability.analyze_fit_identifiability`` 在
      ``wetbed_irr_gain`` / ``wetbed_rev_gain`` 軸上進行。
"""

import dataclasses
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import minimize_scalar

from .params import V60Params, PourProtocol, RoastProfile
from .core import simulate_brew, print_summary
from .measured_io import load_flow_profile_csv, _measured_setup_overrides
from .benchmark import _load_measured_benchmark_state, run_benchmark_suite
from .identifiability import analyze_fit_identifiability, analyze_pref_flow_identifiability
from .viz import plot_results


# ─────────────────────────────────────────────────────────────────────────────
#  靈敏度分析
# ─────────────────────────────────────────────────────────────────────────────
def sensitivity_analysis(
    protocol: PourProtocol | None = None,
    delta: float = 0.20,
) -> None:
    """
    OAT（One-At-a-Time）靈敏度分析：中央差分法。

    What:
      對 7 個物理參數各自做 ±delta（預設 ±20%）的微擾，
      計算正規化靈敏度 S_i = (ΔY/Y_ref) / (Δp_i/p_i_ref)。
      輸出 4 個指標的龍捲風圖：EY_final、TDS_final、Drain Time、Fast%。

    Why:
      識別「魔王參數」（對品質指標最敏感的旋鈕），
      也揭示流量參數（k, ψ）與萃取參數（k_ext, max_EY）的解耦程度。
      為實驗量測設計提供優先級依據：敏感度高的參數必須精確量測。
    """
    if protocol is None:
        protocol = PourProtocol.standard_v60()

    # ── 基準參數 ──────────────────────────────────────────────────────────────
    base = V60Params()

    # 待分析的參數：(顯示名, 欄位名, 基準值, 是否用對數微擾)
    # NOTE 2026-09-24（F3）：萃取端重寫後，`k_ext_*_coef` / `fast_fraction` / `Ea_slow`
    # 都已不存在。萃取速率軸換成唯一的 live closure 參數 `tau_tort`（顆粒內曲折度），
    # 幾何軸換成 `shell_thickness`（破壁層厚度，同時決定兩池質量分配與擴散長度）。
    param_specs = [
        ("k  (permeability)",        "k",                 base.k,                 True),
        ("ψ  (bypass coef)",         "psi",               base.psi,               True),
        ("τ_tort  (tortuosity)",     "tau_tort",          base.tau_tort,          True),
        ("max_EY",                   "max_EY",            base.max_EY,            False),
        ("T_brew  [K]",              "T_brew",            base.T_brew,            False),
        ("shell_thickness  [m]",     "shell_thickness",   base.shell_thickness,   True),
        ("C_sat_slow  [g/L]",        "C_sat_slow",        base.C_sat_slow,        False),
    ]

    # ── 輔助：從模擬結果提取 4 個純量指標 ────────────────────────────────────
    def _extract_metrics(res: dict) -> np.ndarray:
        ey_f  = float(res["EY_fast_cup_pct"][-1])
        ey_s  = float(res["EY_slow_cup_pct"][-1])
        total = ey_f + ey_s
        fast_pct = (ey_f / total * 100) if total > 0.1 else 50.0

        tds_arr = res["TDS_gl"]
        valid   = tds_arr[tds_arr > 0]
        tds_fin = float(valid[-1]) if len(valid) > 0 else 0.0

        return np.array([
            float(res["EY_cup_pct"][-1]),   # EY_final [%]
            tds_fin,                          # TDS_final [g/L]
            float(res["drain_time"]),         # drain time [s]
            fast_pct,                         # Fast% [%]
        ])

    metric_names  = ["EY Final [%]", "TDS Final [g/L]", "Drain Time [s]", "Fast Flavor [%]"]
    metric_colors = ["#2196F3", "#4CAF50", "#FF9800", "#9C27B0"]

    # ── 基準模擬 ──────────────────────────────────────────────────────────────
    res_base = simulate_brew(base, protocol, t_end=400, n_eval=800)
    Y_ref    = _extract_metrics(res_base)

    print("\n=== 靈敏度分析（OAT，±20% 中央差分）===")
    print(f"  基準值：EY={Y_ref[0]:.2f}%  TDS={Y_ref[1]:.2f}g/L  "
          f"DrainTime={Y_ref[2]:.0f}s  Fast%={Y_ref[3]:.1f}%")
    print(f"  {'參數':<26}  {'EY':>8}  {'TDS':>8}  {'Drain':>8}  {'Fast%':>8}")
    print("  " + "─" * 70)

    # ── OAT 中央差分 ──────────────────────────────────────────────────────────
    n_params  = len(param_specs)
    n_metrics = len(metric_names)
    S = np.zeros((n_params, n_metrics))  # 正規化靈敏度矩陣

    for i, (name, field_name, p_ref, log_scale) in enumerate(param_specs):
        if log_scale:
            p_hi = p_ref * (1 + delta)
            p_lo = p_ref * (1 - delta)
        else:
            p_hi = p_ref * (1 + delta)
            p_lo = p_ref * (1 - delta)

        params_hi = dataclasses.replace(base, **{field_name: p_hi})
        params_lo = dataclasses.replace(base, **{field_name: p_lo})

        res_hi = simulate_brew(params_hi, protocol, t_end=400, n_eval=800)
        res_lo = simulate_brew(params_lo, protocol, t_end=400, n_eval=800)

        Y_hi = _extract_metrics(res_hi)
        Y_lo = _extract_metrics(res_lo)

        # S = (ΔY/Y_ref) / (2δ)  — 正規化到參數的相對變化量
        # 注意：當 Y_ref→0 時用絕對差分
        dY = Y_hi - Y_lo
        _y_safe = np.where(np.abs(Y_ref) > 1e-12, Y_ref, 1.0)
        S[i] = (dY / _y_safe) / (2 * delta)

        print(f"  {name:<26}  "
              f"{S[i,0]:>+8.3f}  {S[i,1]:>+8.3f}  {S[i,2]:>+8.3f}  {S[i,3]:>+8.3f}")

    print("  " + "─" * 70)
    print("  正規化靈敏度 S = (ΔY/Y_ref) / (Δp/p_ref)")
    print("  |S|>1 代表槓桿效應（參數變化被放大）")

    # ── 龍捲風圖（Tornado Chart）────────────────────────────────────────────
    param_labels = [spec[0] for spec in param_specs]
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(
        f"Sensitivity Analysis — OAT ±{int(delta*100)}%  (V60 v7 Multi-Component)",
        fontsize=13, fontweight="bold",
    )

    for m, (ax, mname, mcolor) in enumerate(zip(axes.flat, metric_names, metric_colors)):
        s_vals = S[:, m]
        # 按絕對值排序
        order = np.argsort(np.abs(s_vals))
        sorted_labels = [param_labels[o] for o in order]
        sorted_vals   = s_vals[order]

        colors = [mcolor if v >= 0 else "#E53935" for v in sorted_vals]
        bars = ax.barh(sorted_labels, sorted_vals, color=colors, edgecolor="white", height=0.6)

        ax.axvline(0, color="black", lw=0.8)
        ax.axvline( 1, color="gray",  lw=0.6, ls="--", alpha=0.5)
        ax.axvline(-1, color="gray",  lw=0.6, ls="--", alpha=0.5)

        # 標注數值
        for bar, val in zip(bars, sorted_vals):
            x_pos = val + np.sign(val) * 0.03
            ha = "left" if val >= 0 else "right"
            ax.text(x_pos, bar.get_y() + bar.get_height() / 2,
                    f"{val:+.2f}", va="center", ha=ha, fontsize=8)

        ax.set_xlabel("Normalized Sensitivity  S = (ΔY/Y) / (Δp/p)")
        ax.set_title(mname, fontsize=11, color=mcolor, fontweight="bold")
        ax.grid(axis="x", alpha=0.3)
        ax.set_xlim(
            min(-0.2, sorted_vals.min() * 1.3),
            max( 0.2, sorted_vals.max() * 1.3),
        )

    plt.tight_layout()
    fname = "v60_sensitivity.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"\n靈敏度龍捲風圖已儲存至 {fname}")

    # ── 2D 熱圖：k × T_brew 對 EY 的交互效應 ──────────────────────────────
    n_scan = 12
    k_scan   = np.logspace(-12, -10, n_scan)
    T_scan   = np.linspace(356.15, 376.15, n_scan)   # 83°C → 103°C
    EY_map   = np.zeros((n_scan, n_scan))
    Fast_map = np.zeros((n_scan, n_scan))

    print(f"\n2D 掃描：k × T_brew，{n_scan}×{n_scan}={n_scan**2} 組...")
    for i, k_v in enumerate(k_scan):
        for j, T_v in enumerate(T_scan):
            p = dataclasses.replace(base, k=k_v, T_brew=T_v)
            r = simulate_brew(p, protocol, t_end=180, n_eval=600)
            EY_map[i, j]   = float(r["EY_cup_pct"][-1])
            ey_f = float(r["EY_fast_cup_pct"][-1])
            ey_s = float(r["EY_slow_cup_pct"][-1])
            tot  = ey_f + ey_s
            Fast_map[i, j] = (ey_f / tot * 100) if tot > 0.1 else 50.0
        print(f"  2D row {i+1}/{n_scan} done")

    T_C_scan = T_scan - 273.15
    fig2, axes2 = plt.subplots(1, 2, figsize=(14, 5))
    fig2.suptitle("2D Sensitivity: Grind (k) × Brew Temperature", fontsize=12)

    # EY 熱圖
    ax = axes2[0]
    im = ax.contourf(T_C_scan, np.log10(k_scan), EY_map, levels=20, cmap="YlOrRd")
    cs = ax.contour(T_C_scan, np.log10(k_scan), EY_map,
                    levels=10, colors="white", linewidths=0.7, alpha=0.6)
    ax.clabel(cs, fmt="%.1f%%", fontsize=7)
    plt.colorbar(im, ax=ax, label="EY Final [%]")
    ax.set_xlabel("Brew Temperature [°C]")
    ax.set_ylabel("log₁₀(k)  — Grind Size [m²]")
    ax.set_title("Final Extraction Yield (EY)")
    ax.plot(base.T_brew - 273.15, np.log10(base.k), "w*", ms=12, label="default")
    ax.legend(fontsize=9)

    # Fast% 熱圖
    ax = axes2[1]
    im2 = ax.contourf(T_C_scan, np.log10(k_scan), Fast_map, levels=20, cmap="RdYlGn_r")
    cs2 = ax.contour(T_C_scan, np.log10(k_scan), Fast_map,
                     levels=10, colors="white", linewidths=0.7, alpha=0.6)
    ax.clabel(cs2, fmt="%.0f%%", fontsize=7)
    plt.colorbar(im2, ax=ax, label="Fast Flavor% (Bright/Acid)")
    ax.set_xlabel("Brew Temperature [°C]")
    ax.set_ylabel("log₁₀(k)  — Grind Size [m²]")
    ax.set_title("Flavor Balance: Fast% (higher = brighter/more acidic)")
    ax.plot(base.T_brew - 273.15, np.log10(base.k), "w*", ms=12, label="default")
    ax.legend(fontsize=9)

    plt.tight_layout()
    fname2 = "v60_sensitivity_2d.png"
    plt.savefig(fname2, dpi=150, bbox_inches="tight")
    print(f"2D 靈敏度熱圖已儲存至 {fname2}")



# ─────────────────────────────────────────────────────────────────────────────
#  k–M 聯動分析
# ─────────────────────────────────────────────────────────────────────────────
def compare_grind_linkage(protocol: PourProtocol | None = None) -> dict:
    """
    掃描研磨度（k）：比較「獨立參數」vs「k-M 聯動」兩種模型的預測差異。

    What:
      對 8 個研磨點（5e-11 → 5e-12 m²）分別跑：
        A. 傳統模型（僅改 k，max_EY 固定）
        B. 聯動模型（V60Params.for_grind，三者同步縮放）
      繪製四格對比圖：EY / TDS / Drain Time / Fast%，並標記 SCA 標準帶。

    Why:
      傳統模型預測「越細 EY 越低」（因為細研磨流速慢，接觸時間雖長但
      max_EY 不變，形成過萃幻象）。
      聯動模型才能正確反映「細研磨提高 EY 上限但增加苦味風險」的物理現實，
      讓模型具備預測最佳研磨點的能力。

    Returns:
      dict 含兩組掃描結果，供 find_optimal_grind 直接使用。
    """
    if protocol is None:
        protocol = PourProtocol.standard_v60()

    base = V60Params()
    k_range = np.logspace(np.log10(5e-11), np.log10(5e-12), 10)
    # 近似研磨度標籤：以 k_ref = 2e-11 為中研磨基準，d ∝ k^0.5
    grind_label = [f"{k:.1e}" for k in k_range]

    metrics_indep  = []  # 傳統（獨立）模型
    metrics_linked = []  # 聯動模型

    print("\n=== k–M 聯動掃描 ===")
    print(f"  {'k [m²]':>10}  {'EY_indep':>8}  {'EY_link':>8}  "
          f"{'TDS_indep':>10}  {'TDS_link':>10}  {'Drain_link':>10}")
    print("  " + "─" * 70)

    for k_v in k_range:
        # A. 獨立模型：只改 k
        p_indep = dataclasses.replace(base, k=k_v)
        r_indep = simulate_brew(p_indep, protocol, t_end=180, n_eval=1200)

        # B. 聯動模型：k + max_EY 同步（F3 後 k_ext_coef 已移除）
        p_link  = V60Params.for_grind(k_v, base)
        r_link  = simulate_brew(p_link, protocol, t_end=180, n_eval=1200)

        def _metrics(r):
            ey_f  = float(r["EY_fast_cup_pct"][-1])
            ey_s  = float(r["EY_slow_cup_pct"][-1])
            total = ey_f + ey_s
            fast_pct = (ey_f / total * 100) if total > 0.1 else 50.0
            tds_arr  = r["TDS_gl"]
            valid    = tds_arr[tds_arr > 0]
            tds_fin  = float(valid[-1]) if len(valid) > 0 else 0.0
            return dict(
                EY         = float(r["EY_cup_pct"][-1]),
                TDS        = tds_fin,
                drain_time = float(r["drain_time"]),
                fast_pct   = fast_pct,
            )

        mi = _metrics(r_indep)
        ml = _metrics(r_link)
        metrics_indep.append(mi)
        metrics_linked.append(ml)

        print(f"  {k_v:>10.2e}  {mi['EY']:>8.2f}  {ml['EY']:>8.2f}  "
              f"{mi['TDS']:>10.2f}  {ml['TDS']:>10.2f}  {ml['drain_time']:>10.1f}")

    # ── 繪圖 ──────────────────────────────────────────────────────────────────
    k_log = np.log10(k_range)
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle("Grind-k  ×  Extraction — Independent vs k-M Linked Model",
                 fontsize=13, fontweight="bold")

    plot_specs = [
        ("EY Final [%]",    "EY",         [18, 22],    "SCA EY target (18–22%)"),
        ("TDS Final [g/L]", "TDS",        [11.5, 14.5],"SCA TDS target (1.15–1.45%)"),
        ("Drain Time [s]",  "drain_time", None,         None),
        ("Fast Flavor [%]", "fast_pct",   None,         None),
    ]

    for ax, (ylabel, key, sca_range, sca_label) in zip(axes.flat, plot_specs):
        y_indep  = [m[key] for m in metrics_indep]
        y_linked = [m[key] for m in metrics_linked]

        ax.plot(k_log, y_indep,  "o--", color="#78909C", lw=1.5, ms=5, label="Independent (k only)")
        ax.plot(k_log, y_linked, "s-",  color="#1565C0", lw=2,   ms=6, label="k-M Linked")

        if sca_range is not None:
            ax.axhspan(sca_range[0], sca_range[1], alpha=0.12,
                       color="#4CAF50", label=sca_label)

        ax.set_xlabel("log₁₀(k)  — Coarse → Fine")
        ax.set_ylabel(ylabel)
        ax.set_title(ylabel)
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)

        # 反轉 x 軸：左為粗，右為細（符合手沖習慣）
        ax.invert_xaxis()

    # x 軸刻度標籤補充（近似研磨度描述）
    for ax in axes.flat:
        xticks = ax.get_xticks()
        ax.set_xticks(xticks)
        ax.set_xticklabels([f"{v:.1f}" for v in xticks], fontsize=7)

    plt.tight_layout()
    fname = "v60_grind_linkage.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"\nk–M 聯動比較圖已儲存至 {fname}")

    return dict(k_range=k_range, metrics_linked=metrics_linked, metrics_indep=metrics_indep)


def find_optimal_grind(
    protocol: PourProtocol | None = None,
    base: V60Params | None = None,
    score_weights: dict | None = None,
) -> tuple[float, V60Params, dict]:
    """
    搜尋使沖煮品質最優的研磨度 k。

    What:
      在 k ∈ [5e-12, 5e-11] 範圍內，以 scipy.optimize.minimize_scalar 最小化
      加權懲罰函數 L(k)：

          L(k) = -w_EY × EY  +  w_TDS × max(0, |TDS - TDS_target| - TDS_tol)²
                              +  w_drain × max(0, drain - drain_max)

      其中 TDS_target = 13.0 g/L，TDS_tol = 1.5 g/L（SCA 標準帶 ±1.5）。
      EY 項為獎勵（負號），TDS 越偏離中心越懲罰，沖煮超時也懲罰。

    Why:
      SCA 標準定義的「黃金杯」要求 TDS ≈ 11.5–14.5 g/L 且 EY ≈ 18–22%。
      但兩者往往相互競爭（細研磨提高 EY 但可能降低 TDS、延長沖煮時間）。
      加權損失函數讓使用者透過 score_weights 調整偏好（重視 EY 還是 TDS 穩定性）。

    Args:
        protocol      : 注水協議（None → 標準三段式）
        base          : 基底參數（None → 預設值）
        score_weights : dict，可覆寫 w_EY / w_TDS / w_drain / TDS_target
                        / TDS_tol / drain_max

    Returns:
        (k_opt, params_opt, result_opt)
        k_opt      : 最優滲透率 [m²]
        params_opt : 對應的 V60Params（已聯動調整）
        result_opt : 對應的 simulate_brew 輸出 dict
    """
    if protocol is None:
        protocol = PourProtocol.standard_v60()
    if base is None:
        base = V60Params()

    # 預設權重
    w = dict(
        w_EY       = 1.0,    # EY 獎勵係數（越大越重視萃取率）
        w_TDS      = 2.0,    # TDS 偏離懲罰係數
        w_drain    = 0.005,  # 沖煮超時懲罰
        TDS_target = 13.0,   # SCA 理想 TDS 中心 [g/L]
        TDS_tol    = 1.5,    # SCA TDS 允許偏差 [g/L]（帶內不懲罰）
        drain_max  = 180.0,  # 超過此沖煮時間開始懲罰 [s]
    )
    if score_weights is not None:
        w.update(score_weights)

    # ── 損失函數 ──────────────────────────────────────────────────────────────
    def _loss(log_k: float) -> float:
        k_v = 10.0 ** log_k
        p   = V60Params.for_grind(k_v, base)
        r   = simulate_brew(p, protocol, t_end=180, n_eval=800)

        ey  = float(r["EY_cup_pct"][-1])
        tds_arr = r["TDS_gl"]
        valid   = tds_arr[tds_arr > 0]
        tds = float(valid[-1]) if len(valid) > 0 else 0.0
        dt  = float(r["drain_time"])

        # TDS 偏離懲罰（帶外才啟動）
        tds_dev  = max(0.0, abs(tds - w["TDS_target"]) - w["TDS_tol"])
        drain_pen = max(0.0, dt - w["drain_max"])

        loss = -w["w_EY"] * ey + w["w_TDS"] * tds_dev**2 + w["w_drain"] * drain_pen
        return loss

    # ── 粗掃描：找最優區間 ────────────────────────────────────────────────────
    log_k_range = np.linspace(np.log10(5e-12), np.log10(5e-11), 20)
    losses      = [_loss(lk) for lk in log_k_range]
    best_idx    = int(np.argmin(losses))
    # 搜尋範圍縮至粗掃最優點 ±0.3 對數單位
    lo = log_k_range[max(0, best_idx - 2)]
    hi = log_k_range[min(len(log_k_range) - 1, best_idx + 2)]

    res_opt = minimize_scalar(_loss, bounds=(lo, hi), method="bounded",
                              options={"xatol": 0.01, "maxiter": 50})
    k_opt = 10.0 ** res_opt.x

    params_opt = V60Params.for_grind(k_opt, base)
    result_opt = simulate_brew(params_opt, protocol, t_end=180, n_eval=1200)

    # ── 結果輸出 ──────────────────────────────────────────────────────────────
    ey_opt  = float(result_opt["EY_cup_pct"][-1])
    tds_arr = result_opt["TDS_gl"]
    valid   = tds_arr[tds_arr > 0]
    tds_opt = float(valid[-1]) if len(valid) > 0 else 0.0
    dt_opt  = float(result_opt["drain_time"])
    ey_f    = float(result_opt["EY_fast_cup_pct"][-1])
    ey_s    = float(result_opt["EY_slow_cup_pct"][-1])
    tot     = ey_f + ey_s
    fast_pct = (ey_f / tot * 100) if tot > 0.1 else 50.0

    # 等效研磨粒徑（相對 k_ref 的比值，以 d ∝ k^0.5 估算）
    d_rel = (k_opt / base.k_ref) ** 0.5   # 相對中研磨粒徑

    print("\n=== 最佳研磨度搜尋結果 ===")
    print("=" * 54)
    print(f"  最優 k         : {k_opt:.3e} m²")
    print(f"  等效粒徑比     : {d_rel:.2f} × 中研磨粒徑")
    print(f"  max_EY（聯動） : {params_opt.max_EY:.3f}  ({params_opt.max_EY*100:.1f}%)")
    print(f"  ────────────────────────────────────────────────")
    print(f"  EY（入壺）     : {ey_opt:.2f}%")
    print(f"  TDS            : {tds_opt:.2f} g/L")
    print(f"  沖煮時間       : {dt_opt:.0f} s")
    print(f"  Fast%（明亮感）: {fast_pct:.1f}%")
    in_sca = (11.5 <= tds_opt <= 14.5) and (18 <= ey_opt <= 22)
    print(f"  SCA 黃金杯     : {'✓ 達標' if in_sca else '✗ 未達標'}")
    print("=" * 54)

    # ── 可視化：粗掃描損失曲線 + 最優點 ──────────────────────────────────────
    # 重跑粗掃描以取得繪圖資料（損失曲線）
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle(f"Optimal Grind Search — k-M Linked  (k_opt = {k_opt:.2e} m²)",
                 fontsize=12, fontweight="bold")

    # 左：損失函數曲線
    ax = axes[0]
    ax.plot(log_k_range, losses, "o-", color="#1565C0", lw=2, ms=5)
    ax.axvline(res_opt.x, color="#E53935", lw=1.5, ls="--", label=f"k_opt = {k_opt:.2e}")
    ax.set_xlabel("log₁₀(k)  — Coarse → Fine")
    ax.set_ylabel("Loss  L(k)")
    ax.set_title("Objective Function L(k)")
    ax.legend(fontsize=8)
    ax.invert_xaxis()
    ax.grid(alpha=0.3)

    # 中：EY vs k（聯動掃描）
    ax = axes[1]
    ey_scan  = []
    tds_scan = []
    for lk in log_k_range:
        kv  = 10.0 ** lk
        p   = V60Params.for_grind(kv, base)
        r   = simulate_brew(p, protocol, t_end=180, n_eval=600)
        ey_scan.append(float(r["EY_cup_pct"][-1]))
        tds_arr2 = r["TDS_gl"]
        valid2   = tds_arr2[tds_arr2 > 0]
        tds_scan.append(float(valid2[-1]) if len(valid2) > 0 else 0.0)

    ax.plot(log_k_range, ey_scan, "s-", color="#2E7D32", lw=2, ms=5, label="EY [%]")
    ax.axhspan(18, 22, alpha=0.12, color="#4CAF50", label="SCA EY target")
    ax.axvline(res_opt.x, color="#E53935", lw=1.5, ls="--", alpha=0.7)
    ax.set_xlabel("log₁₀(k)  — Coarse → Fine")
    ax.set_ylabel("EY Final [%]")
    ax.set_title("EY vs Grind (Linked)")
    ax.legend(fontsize=8)
    ax.invert_xaxis()
    ax.grid(alpha=0.3)

    # 右：TDS vs k
    ax = axes[2]
    ax.plot(log_k_range, tds_scan, "^-", color="#E65100", lw=2, ms=5, label="TDS [g/L]")
    ax.axhspan(11.5, 14.5, alpha=0.12, color="#4CAF50", label="SCA TDS target")
    ax.axvline(res_opt.x, color="#E53935", lw=1.5, ls="--", alpha=0.7,
               label=f"k_opt = {k_opt:.2e}")
    ax.set_xlabel("log₁₀(k)  — Coarse → Fine")
    ax.set_ylabel("TDS Final [g/L]")
    ax.set_title("TDS vs Grind (Linked)")
    ax.legend(fontsize=8)
    ax.invert_xaxis()
    ax.grid(alpha=0.3)

    plt.tight_layout()
    fname = "v60_optimal_grind.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"最佳研磨度搜尋圖已儲存至 {fname}")

    return k_opt, params_opt, result_opt
