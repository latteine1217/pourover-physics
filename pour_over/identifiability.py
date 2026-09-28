"""
identifiability.py — measured benchmark 局部可識別性分析

What:
    提供主水力 closure 與 preferential-flow closure 的 local identifiability 掃描。

Why:
    這些分析直接依賴 measured benchmark baseline，應從一般 analysis 工具中抽離，
    讓 benchmark / identifiability 形成同一條正式驗證線。

2026-09-24（F4）：`delta_loss` 全面改為 `delta_chi2`，判讀門檻改用 Δχ² 語意。
    舊門檻（0.18 / 0.45 / 1.10）是混合單位 loss 的經驗值，換算不到任何統計量。
    新門檻由 `_delta_chi2_levels()` 給出：
        Δχ² < 1·corr            weak    落在 1σ 內，資料分不出來 → 建議凍結
        1·corr ≤ Δχ² < 3.84·corr medium 有訊號但未達 95%
        Δχ² ≥ 3.84·corr         hard    95% 可辨識 → 保留為自由度
    `corr = max(reduced_chi2, 1)` 是 σ 誤設修正（見 `fitting.profile_ci`）。
    所有掃描一律使用 `SOLVER_FINE`，不再與 fitting 的 coarse preset 混用。
"""

import csv
import dataclasses
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from .benchmark import _load_measured_benchmark_state
from .fitting import (
    DEFAULT_MEASURED_FLOW_CSV,
    DEFAULT_MEASURED_FLOW_FIT_SUMMARY,
    SOLVER_FINE,
    K_BETA_BOUNDS,
    K_BOUNDS_M2,
    SAT_REL_PERM_EXP_BOUNDS,
    TAU_LAG_BOUNDS_S,
    TAU_WET_BOUNDS_S,
    U_LIQUID_DRIPPER_BOUNDS_W_M2K,
    evaluate_measured_flow_fit,
)
from .params import EXTRACTION_FIT_SPEC, V60Params

# 旁路係數 Ψ 的掃描界：只用來夾住 ±30% factor grid，不是物理門檻。
# 取得夠寬（4 個數量級）以確保 grid 在預設值附近完全不被 clip——
# 被 clip 的格點會讓 Δχ² span 假性變小，看起來「不可識別」。
PSI_SCAN_BOUNDS = (1.0e-6, 1.0e-2)

# ── 哪些掃描參數目前是 fit 的自由度（F6b 自由度重配後）───────────────────────
# What: 判定表的 `in_fit` 欄，來源是 `fitting.fit_k_kbeta_from_flow_profile` 的
#       stage 1/2 + 5 + 7 live 集合（F6d：`U_liquid_dripper_W_m2K` 已凍結，不在其中；
#       thermal slices 仍掃它，但以 `in_fit=False` 標為「凍結參數的敏感度」）。
# Why:  identifiability 表回答「資料分不分得出這個參數」，fit 回答「我們有沒有
#       在擬它」。這兩件事**不會自動一致**——F6 §6.1 正是靠把兩者並排才發現
#       `k_beta`/`tau_lag`（weak）在 fit 裡、`sat_rel_perm_exp`（hard）卻被凍結。
#       把 `in_fit` 做成表上的一欄，下次再錯配時讀表的人一眼就看得到，
#       不必再自己去對照 fitting.py。
FIT_LIVE_PARAMS: frozenset[str] = frozenset({
    "k", "sat_rel_perm_exp", "tau_wet_s",
    "lambda_server_ambient",
    *(spec[0] for spec in EXTRACTION_FIT_SPEC),
})


def _live_param_set(info: dict) -> frozenset[str]:
    """
    這個 case 那一次 fit 實際的 live 參數集合（summary 的 `fit_live_param_names`）。

    Why（F11）：熱端自由度自 F11 起依觀測類型分流——影片 case（有分享壺溫時序）與
        紀錄表 case 的 live 集合不同，靜態的 `FIT_LIVE_PARAMS` 無法同時正確標示兩者。
        summary 缺欄（舊 artifact）才退回靜態集合。
    """
    names = [x for x in str(info.get("fit_live_param_names", "") or "").split(";") if x]
    return frozenset(names) if names else FIT_LIVE_PARAMS


def _delta_chi2_levels(reduced_chi2: float) -> tuple[float, float]:
    """
    回傳 (weak/medium 分界, medium/hard 分界) 的 Δχ² 門檻。

    What: `(1.0 × corr, 3.84 × corr)`，`corr = max(reduced_chi2, 1)`。
    Why:  Δχ² = 1 是單參數 1σ、3.84 是 95%。模型有結構誤差時（reduced χ² ≫ 1）
          未修正的門檻會把任何微小擾動都判成「可識別」。
    """
    corr = max(float(reduced_chi2), 1.0)
    return 1.0 * corr, 3.84 * corr


def _judge_level(local_span: float, wide_span: float,
                 weak_hi: float, hard_lo: float) -> tuple[str, str]:
    """由 Δχ² span 判定識別性等級與建議。"""
    if wide_span >= hard_lo:
        return "hard", "保留自由度（95% 可辨識）"
    if wide_span >= weak_hi:
        return "medium", "可保留，但需另一參數凍結配合"
    return "weak", "建議凍結（Δχ² < 1σ）"


def analyze_fit_identifiability(
    csv_path: str | Path | None = None,
    summary_path: str | Path | None = None,
    slices_csv_path: str | Path = "data/kinu29_fit_identifiability_slices.csv",
    heatmap_path: str | Path = "data/kinu29_fit_identifiability_heatmap.png",
    *,
    refit: bool = False,
    verbose: bool = True,
    solver: dict | None = None,
    n_eval: int | None = None,   # deprecated：保留簽名，實際一律用 SOLVER_FINE
) -> dict:
    """
    分析目前 measured-fit 解附近的局部可識別性。
    """
    flow_path = Path(csv_path) if csv_path is not None else Path(DEFAULT_MEASURED_FLOW_CSV)
    summary_csv = Path(summary_path) if summary_path is not None else Path(DEFAULT_MEASURED_FLOW_FIT_SUMMARY)
    params_fit, info = _load_measured_benchmark_state(
        flow_path,
        summary_csv,
        refit=refit,
        verbose=verbose,
    )
    tau_lag_s = float(info["tau_lag_s"])
    solver_cfg = dict(SOLVER_FINE if solver is None else solver)
    prior_frozen = info.get("k_beta_prior_psd")
    # baseline 與每一個 slice 都必須用**同一個** n_fit_params，否則 Δχ² 會混進
    # 一個純粹來自 dof 記帳的位移（F6b）。來源是那一次 fit 實際的 live 集合
    # （summary 的 `fit_live_param_names`，經 benchmark 的 reload 帶進 info）。
    n_fit = info.get("n_fit_params") or None
    _nfp = {"n_fit_params": int(n_fit)} if n_fit else {}
    baseline = evaluate_measured_flow_fit(flow_path, params_fit, tau_lag_s=tau_lag_s,
                                          solver=solver_cfg, k_beta_prior_psd=prior_frozen,
                                          **_nfp)
    baseline_chi2 = float(baseline["chi2"])
    baseline_reduced_chi2 = float(baseline["reduced_chi2"])
    weak_hi, hard_lo = _delta_chi2_levels(baseline_reduced_chi2)
    live_set = _live_param_set(info)

    def _set_param(p: V60Params, name: str, value: float) -> V60Params:
        return dataclasses.replace(p, **{name: float(value)})

    factor_grid = np.array([0.70, 0.85, 1.00, 1.15, 1.30], dtype=float)
    # P0/P1 重構後，χ 結構態 (`wetbed_struct_*`) 已併入 f_post。
    # `wetbed_irr_gain` 在 2026-04-30 identifiability scan 中 span 僅 0.36（純平 ridge），
    # 已凍結為預設值；正式可識別濕床自由度只剩 `wetbed_rev_gain`。
    # `sat_rel_perm_residual` 已從掃描移除：F2b 之後殘餘飽和由顯式狀態 `V_imm`
    # 攜帶，Corey 的 S_r 預設為 0。掃一個恆為 0 的參數只會得到一條全 0 的 slice。
    slice_specs = [
        ("k", float(params_fit.k), *K_BOUNDS_M2),
        ("k_beta", float(params_fit.k_beta), *K_BETA_BOUNDS),
        ("wetbed_rev_gain", float(params_fit.wetbed_rev_gain), 0.0, 3.5),
        ("sat_rel_perm_exp", float(params_fit.sat_rel_perm_exp), *SAT_REL_PERM_EXP_BOUNDS),
        # 顯式 bypass 份額：F2b 實測佔 V_out 的 ~7%，因此它是否可由資料辨識
        # 必須有答案——不能只因為「它不在 fit 裡」就不掃（AGENTS.md §3.1）。
        ("psi", float(params_fit.psi), *PSI_SCAN_BOUNDS),
        # `tau_lag_s` 是觀測層參數，不是 `V60Params` 欄位；它與 k 一起進 stage 1/2，
        # 因此必須與水力參數放在同一張 slice 表上比較。
        ("tau_lag_s", float(tau_lag_s), *TAU_LAG_BOUNDS_S),
    ]
    # F2b 的悶蒸潤濕時間常數（getattr 防呆，不強制依賴該版 core）
    tau_wet = getattr(params_fit, "tau_wet_s", None)
    if tau_wet is not None and float(tau_wet) > 0.0:
        slice_specs.append(("tau_wet_s", float(tau_wet), *TAU_WET_BOUNDS_S))
    # 萃取端的唯一 live closure 參數（由 `EXTRACTION_FIT_SPEC` 表驅動）。
    for _name, _transform, _lo, _hi, *_rest in EXTRACTION_FIT_SPEC:
        _cur = getattr(params_fit, _name, None)
        if _cur is not None and float(_cur) > 0.0:
            slice_specs.append((_name, float(_cur), float(_lo), float(_hi)))

    slice_rows: list[dict] = []
    for param_name, center, low, high in slice_specs:
        for factor in factor_grid:
            trial_value = float(np.clip(center * factor, low, high))
            # `tau_lag_s` 走觀測層引數，其餘走 `V60Params` 欄位。
            if param_name == "tau_lag_s":
                trial_params, trial_tau_lag = params_fit, trial_value
            else:
                trial_params, trial_tau_lag = _set_param(params_fit, param_name, trial_value), tau_lag_s
            eval_row = evaluate_measured_flow_fit(flow_path, trial_params, tau_lag_s=trial_tau_lag,
                                              solver=solver_cfg, k_beta_prior_psd=prior_frozen,
                                              **_nfp)
            slice_rows.append({
                "param": param_name,
                # F6b：slice CSV 直接帶出「這個參數目前是不是 fit 的自由度」，
                # 讀 CSV 的人不必再回去翻 fitting.py 的 stage 清單。
                "in_fit": bool(param_name in live_set),
                "factor": float(factor),
                "value": trial_value,
                "delta_chi2": float(eval_row["chi2"] - baseline_chi2),
                "reduced_chi2": float(eval_row["reduced_chi2"]),
                "retention_rmse_ml": float(eval_row["retention_rmse_ml"]),
                "rmse_ml": float(eval_row["volume_rmse"]),
                "velocity_rmse_mlps": float(eval_row["velocity_rmse"]),
                "cup_stop_time_error_s": float(eval_row["cup_stop_time_error_s"]),
            })

    slices_path = Path(slices_csv_path)
    slices_path.parent.mkdir(parents=True, exist_ok=True)
    with slices_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(slice_rows[0].keys()))
        writer.writeheader()
        writer.writerows(slice_rows)

    # (k, tau_wet_s) 是 F2b 指出的關鍵 pair：沒有 loss 的 retention 項時它是平 ridge，
    # 有了 retention 項之後這張圖就是「retention 到底有沒有把 ridge 打開」的直接證據。
    pair_specs = [
        ("k", "k_beta"),
        ("k", "tau_wet_s") if any(sp[0] == "tau_wet_s" for sp in slice_specs) else ("k", "sat_rel_perm_exp"),
        ("k_beta", "sat_rel_perm_exp"),
        ("k", "wetbed_rev_gain"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(12.4, 8.6))
    fig.suptitle("Hydraulic Identifiability Around Measured Fit", fontsize=13, fontweight="bold")

    for ax, (param_x, param_y) in zip(axes.flat, pair_specs):
        spec_x = next(spec for spec in slice_specs if spec[0] == param_x)
        spec_y = next(spec for spec in slice_specs if spec[0] == param_y)
        x_vals = np.clip(spec_x[1] * factor_grid, spec_x[2], spec_x[3])
        y_vals = np.clip(spec_y[1] * factor_grid, spec_y[2], spec_y[3])
        z = np.zeros((len(y_vals), len(x_vals)))
        for iy, yv in enumerate(y_vals):
            for ix, xv in enumerate(x_vals):
                trial_params = _set_param(params_fit, param_x, float(xv))
                trial_params = _set_param(trial_params, param_y, float(yv))
                eval_row = evaluate_measured_flow_fit(flow_path, trial_params, tau_lag_s=tau_lag_s,
                                              solver=solver_cfg, k_beta_prior_psd=prior_frozen,
                                              **_nfp)
                z[iy, ix] = float(eval_row["chi2"] - baseline_chi2)

        im = ax.imshow(z, origin="lower", aspect="auto", cmap="YlOrRd")
        ax.set_title(f"{param_x} vs {param_y}")
        ax.set_xlabel(param_x)
        ax.set_ylabel(param_y)
        ax.set_xticks(range(len(x_vals)))
        ax.set_xticklabels([f"{v:.3g}" for v in x_vals], rotation=30, ha="right")
        ax.set_yticks(range(len(y_vals)))
        ax.set_yticklabels([f"{v:.3g}" for v in y_vals])
        for iy in range(len(y_vals)):
            for ix in range(len(x_vals)):
                ax.text(ix, iy, f"{z[iy, ix]:.2f}", ha="center", va="center", fontsize=7)
        fig.colorbar(im, ax=ax, label="delta chi2")

    for ax in axes.flat[len(pair_specs):]:
        ax.axis("off")

    plt.tight_layout()
    heatmap_out = Path(heatmap_path)
    heatmap_out.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(heatmap_out, dpi=160, bbox_inches="tight")
    plt.close(fig)

    # 逐參數判定表：與 thermal / pref-flow 分析同一套語意（F6 補上，
    # 否則水力端只有原始 slice 列，讀者必須自己算 span 才知道哪些該凍結）。
    def _slice_judgement(rows: list[dict], param_name: str) -> dict:
        rows_param = [r for r in rows if r["param"] == param_name]
        near_rows = [r for r in rows_param if abs(float(r["factor"]) - 1.0) > 1e-9]
        local_rows = [r for r in near_rows if abs(float(r["factor"]) - 1.0) <= 0.16 + 1e-9]
        local_span = max((abs(float(r["delta_chi2"])) for r in local_rows), default=0.0)
        wide_span = max((abs(float(r["delta_chi2"])) for r in near_rows), default=0.0)
        level, advice = _judge_level(local_span, wide_span, weak_hi, hard_lo)
        in_fit = param_name in live_set
        # 錯配 = 「資料分得出來卻被凍結」或「資料分不出來卻在擬」。
        mismatch = (level == "hard" and not in_fit) or (level == "weak" and in_fit)
        return {
            "param": param_name,
            "local_span": float(local_span),
            "wide_span": float(wide_span),
            "level": level,
            "in_fit": bool(in_fit),
            "dof_mismatch": bool(mismatch),
            "advice": advice,
        }

    judgement_rows = [_slice_judgement(slice_rows, name) for name, *_ in slice_specs]

    print("\n=== Identifiability ===")
    print(f"  baseline chi2 : {baseline_chi2:.2f}  (reduced {baseline_reduced_chi2:.2f})")
    print(f"  levels        : weak < {weak_hi:.2f} <= medium < {hard_lo:.2f} <= hard")
    print(f"  fit live set  : {', '.join(sorted(live_set))}")
    print(f"  {'param':<26}{'local span':>12}{'wide span':>12}  {'level':<8}"
          f"{'in_fit':<8}advice")
    for row in judgement_rows:
        flag = " <-- DOF MISMATCH" if row["dof_mismatch"] else ""
        print(f"  {row['param']:<26}{row['local_span']:>12.2f}{row['wide_span']:>12.2f}  "
              f"{row['level']:<8}{'yes' if row['in_fit'] else 'no':<8}{row['advice']}{flag}")
    n_mismatch = sum(1 for r in judgement_rows if r["dof_mismatch"])
    print(f"  dof mismatches: {n_mismatch}"
          f"{'  (自由度配置與資料資訊量一致)' if n_mismatch == 0 else ''}")
    print(f"  slices csv    : {slices_path}")
    print(f"  heatmap png   : {heatmap_out}")

    return {
        "params_fit": params_fit,
        "info": info,
        "baseline": baseline,
        "baseline_chi2": baseline_chi2,
        "baseline_reduced_chi2": baseline_reduced_chi2,
        "slice_rows": slice_rows,
        "judgement_rows": judgement_rows,
        "delta_chi2_levels": (float(weak_hi), float(hard_lo)),
        "slices_csv_path": str(slices_path),
        "heatmap_path": str(heatmap_out),
        "factor_grid": factor_grid,
    }


def analyze_pref_flow_identifiability(
    csv_path: str | Path | None = None,
    summary_path: str | Path | None = None,
    slices_csv_path: str | Path = "data/kinu29_pref_flow_identifiability_slices.csv",
    heatmap_path: str | Path = "data/kinu29_pref_flow_identifiability_heatmap.png",
    *,
    refit: bool = False,
    verbose: bool = True,
    solver: dict | None = None,
    n_eval: int | None = None,   # deprecated：保留簽名，實際一律用 SOLVER_FINE
) -> dict:
    """
    分析快路徑 `pref_flow_*` 參數在目前 measured fit 附近的局部可識別性。
    """
    flow_path = Path(csv_path) if csv_path is not None else Path(DEFAULT_MEASURED_FLOW_CSV)
    summary_csv = Path(summary_path) if summary_path is not None else Path(DEFAULT_MEASURED_FLOW_FIT_SUMMARY)
    params_fit, info = _load_measured_benchmark_state(
        flow_path,
        summary_csv,
        refit=refit,
        verbose=verbose,
    )
    if float(getattr(params_fit, "pref_flow_coeff", 0.0)) <= 0.0:
        raise ValueError("目前 calibrated baseline 未啟用 pref_flow，無法做 pref_flow identifiability。")

    tau_lag_s = float(info["tau_lag_s"])
    solver_cfg = dict(SOLVER_FINE if solver is None else solver)
    prior_frozen = info.get("k_beta_prior_psd")
    baseline = evaluate_measured_flow_fit(flow_path, params_fit, tau_lag_s=tau_lag_s,
                                          solver=solver_cfg, k_beta_prior_psd=prior_frozen)
    baseline_chi2 = float(baseline["chi2"])
    baseline_reduced_chi2 = float(baseline["reduced_chi2"])
    weak_hi, hard_lo = _delta_chi2_levels(baseline_reduced_chi2)

    def _set_param(p: V60Params, name: str, value: float) -> V60Params:
        return dataclasses.replace(p, **{name: float(value)})

    def _slice_judgement(rows: list[dict], param_name: str) -> dict:
        rows_param = [r for r in rows if r["param"] == param_name]
        near_rows = [r for r in rows_param if abs(float(r["factor"]) - 1.0) > 1e-9]
        local_rows = [r for r in near_rows if abs(float(r["factor"]) - 1.0) <= 0.20 + 1e-9]
        wide_rows = [r for r in near_rows if abs(float(r["factor"]) - 1.0) <= 0.40 + 1e-9]
        local_span = max((abs(float(r["delta_chi2"])) for r in local_rows), default=0.0)
        wide_span = max((abs(float(r["delta_chi2"])) for r in wide_rows), default=0.0)
        level, advice = _judge_level(local_span, wide_span, weak_hi, hard_lo)
        return {
            "param": param_name,
            "local_span": float(local_span),
            "wide_span": float(wide_span),
            "level": level,
            "advice": advice,
        }

    factor_grid = np.array([0.60, 0.80, 1.00, 1.20, 1.40], dtype=float)
    slice_specs = [
        ("pref_flow_coeff", float(params_fit.pref_flow_coeff), 5.0e-6, 5.0e-4),
        ("pref_flow_open_rate", float(params_fit.pref_flow_open_rate), 0.05, 5.0),
        ("pref_flow_tau_decay", float(params_fit.pref_flow_tau_decay), 1.0, 20.0),
    ]

    slice_rows: list[dict] = []
    for param_name, center, low, high in slice_specs:
        for factor in factor_grid:
            trial_value = float(np.clip(center * factor, low, high))
            trial_params = _set_param(params_fit, param_name, trial_value)
            eval_row = evaluate_measured_flow_fit(flow_path, trial_params, tau_lag_s=tau_lag_s,
                                              solver=solver_cfg, k_beta_prior_psd=prior_frozen)
            slice_rows.append({
                "param": param_name,
                "factor": float(factor),
                "value": trial_value,
                "delta_chi2": float(eval_row["chi2"] - baseline_chi2),
                "reduced_chi2": float(eval_row["reduced_chi2"]),
                "retention_rmse_ml": float(eval_row["retention_rmse_ml"]),
                "rmse_ml": float(eval_row["volume_rmse"]),
                "velocity_rmse_mlps": float(eval_row["velocity_rmse"]),
                "cup_stop_time_error_s": float(eval_row["cup_stop_time_error_s"]),
            })

    slices_path = Path(slices_csv_path)
    slices_path.parent.mkdir(parents=True, exist_ok=True)
    with slices_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(slice_rows[0].keys()))
        writer.writeheader()
        writer.writerows(slice_rows)

    pair_specs = [
        ("pref_flow_coeff", "pref_flow_open_rate"),
        ("pref_flow_coeff", "pref_flow_tau_decay"),
        ("pref_flow_open_rate", "pref_flow_tau_decay"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8))
    fig.suptitle("Preferential-Flow Identifiability Around Measured Fit", fontsize=13, fontweight="bold")

    for ax, (param_x, param_y) in zip(np.atleast_1d(axes).flat, pair_specs):
        spec_x = next(spec for spec in slice_specs if spec[0] == param_x)
        spec_y = next(spec for spec in slice_specs if spec[0] == param_y)
        x_vals = np.clip(spec_x[1] * factor_grid, spec_x[2], spec_x[3])
        y_vals = np.clip(spec_y[1] * factor_grid, spec_y[2], spec_y[3])
        z = np.zeros((len(y_vals), len(x_vals)))
        for iy, yv in enumerate(y_vals):
            for ix, xv in enumerate(x_vals):
                trial_params = _set_param(params_fit, param_x, float(xv))
                trial_params = _set_param(trial_params, param_y, float(yv))
                eval_row = evaluate_measured_flow_fit(flow_path, trial_params, tau_lag_s=tau_lag_s,
                                              solver=solver_cfg, k_beta_prior_psd=prior_frozen)
                z[iy, ix] = float(eval_row["chi2"] - baseline_chi2)

        im = ax.imshow(z, origin="lower", aspect="auto", cmap="YlOrRd")
        ax.set_title(f"{param_x} vs {param_y}")
        ax.set_xlabel(param_x)
        ax.set_ylabel(param_y)
        ax.set_xticks(range(len(x_vals)))
        ax.set_xticklabels([f"{v:.3g}" for v in x_vals], rotation=30, ha="right")
        ax.set_yticks(range(len(y_vals)))
        ax.set_yticklabels([f"{v:.3g}" for v in y_vals])
        for iy in range(len(y_vals)):
            for ix in range(len(x_vals)):
                ax.text(ix, iy, f"{z[iy, ix]:.2f}", ha="center", va="center", fontsize=7)
        fig.colorbar(im, ax=ax, label="delta chi2")

    plt.tight_layout()
    heatmap_out = Path(heatmap_path)
    heatmap_out.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(heatmap_out, dpi=160, bbox_inches="tight")
    plt.close(fig)

    judgement_rows = [
        _slice_judgement(slice_rows, "pref_flow_coeff"),
        _slice_judgement(slice_rows, "pref_flow_open_rate"),
        _slice_judgement(slice_rows, "pref_flow_tau_decay"),
    ]
    recommendation = {
        "fix_pref_flow_coeff": judgement_rows[0]["level"] == "weak",
        "fix_pref_flow_open_rate": judgement_rows[1]["level"] != "hard",
        "fix_pref_flow_tau_decay": judgement_rows[2]["level"] != "hard",
    }

    print("\n=== Pref-Flow Identifiability ===")
    print(f"  baseline chi2 : {baseline_chi2:.2f}  (reduced {baseline_reduced_chi2:.2f})")
    print(f"  levels        : weak < {weak_hi:.2f} <= medium < {hard_lo:.2f} <= hard")
    print(f"  slices csv    : {slices_path}")
    print(f"  heatmap png   : {heatmap_out}")
    for row in judgement_rows:
        print(
            f"  {row['param']:<20} : {row['level']:<6} "
            f"(+-20% dchi2 {row['local_span']:.2f}, +-40% dchi2 {row['wide_span']:.2f})"
            f"  → {row['advice']}"
        )

    return {
        "params_fit": params_fit,
        "info": info,
        "baseline": baseline,
        "baseline_chi2": baseline_chi2,
        "baseline_reduced_chi2": baseline_reduced_chi2,
        "slice_rows": slice_rows,
        "judgement_rows": judgement_rows,
        "recommendation": recommendation,
        "slices_csv_path": str(slices_path),
        "heatmap_path": str(heatmap_out),
        "factor_grid": factor_grid,
    }


def analyze_thermal_identifiability(
    csv_path: str | Path | None = None,
    summary_path: str | Path | None = None,
    slices_csv_path: str | Path = "data/kinu29_thermal_identifiability_slices.csv",
    heatmap_path: str | Path = "data/kinu29_thermal_identifiability_heatmap.png",
    *,
    refit: bool = False,
    verbose: bool = True,
    solver: dict | None = None,
    n_eval: int | None = None,   # deprecated：保留簽名，實際一律用 SOLVER_FINE
) -> dict:
    """
    分析熱端 4 條 λ 在目前 measured fit 附近的局部可識別性。

    What:
        對 `lambda_cool / U_liquid_dripper_W_m2K / lambda_dripper_ambient /
        lambda_server_ambient` 各做 0.7×–1.3× factor sweep，輸出：
          1. CSV：每組 (Δχ², V_RMSE, q_RMSE, cup_stop_err, cup_temp_err)
          2. heatmap：每對熱端參數的 2D Δχ² surface
          3. 文字判讀：強/中/弱 識別性

    Why:
        熱端目前杯溫誤差 ±0.06 °C 收得很好，但 4 條 λ 中只有
        `lambda_server_ambient` 進入 stage 5 fit；其他 3 條是手調 default 或凍結值
        （`U_liquid_dripper_W_m2K` 自 F6d 起凍結在 prior 194，CSV `in_fit=False`、
        圖與列印標 frozen——它的 slice 是「凍結參數的敏感度」，不是擬合不確定度）。
        若它們之間存在 ridge，當前的「準確」可能來自相互抵消（compensating
        errors）；本掃描是把這個假設攤開來看的最低成本工具。
    """
    flow_path = Path(csv_path) if csv_path is not None else Path(DEFAULT_MEASURED_FLOW_CSV)
    summary_csv = Path(summary_path) if summary_path is not None else Path(DEFAULT_MEASURED_FLOW_FIT_SUMMARY)
    params_fit, info = _load_measured_benchmark_state(
        flow_path,
        summary_csv,
        refit=refit,
        verbose=verbose,
    )
    tau_lag_s = float(info["tau_lag_s"])
    solver_cfg = dict(SOLVER_FINE if solver is None else solver)
    prior_frozen = info.get("k_beta_prior_psd")
    # baseline 與 slice 共用那一次 fit 的 n_fit_params（同 fit identifiability；F11 補上）。
    n_fit = info.get("n_fit_params") or None
    _nfp = {"n_fit_params": int(n_fit)} if n_fit else {}
    live_set = _live_param_set(info)
    baseline = evaluate_measured_flow_fit(flow_path, params_fit, tau_lag_s=tau_lag_s,
                                          solver=solver_cfg, k_beta_prior_psd=prior_frozen, **_nfp)
    baseline_chi2 = float(baseline["chi2"])
    baseline_reduced_chi2 = float(baseline["reduced_chi2"])
    weak_hi, hard_lo = _delta_chi2_levels(baseline_reduced_chi2)
    baseline_terms = dict(baseline.get("chi2_terms", {}))
    baseline_cup_err = (
        float(baseline["cup_temp_error_C"])
        if baseline.get("cup_temp_error_C") is not None
        else float("nan")
    )

    def _set_param(p: V60Params, name: str, value: float) -> V60Params:
        return dataclasses.replace(p, **{name: float(value)})

    def _slice_judgement(rows: list[dict], param_name: str) -> dict:
        rows_param = [r for r in rows if r["param"] == param_name]
        near_rows = [r for r in rows_param if abs(float(r["factor"]) - 1.0) > 1e-9]
        local_rows = [r for r in near_rows if abs(float(r["factor"]) - 1.0) <= 0.20 + 1e-9]
        wide_rows = [r for r in near_rows if abs(float(r["factor"]) - 1.0) <= 0.40 + 1e-9]
        local_span = max((abs(float(r["delta_chi2"])) for r in local_rows), default=0.0)
        wide_span = max((abs(float(r["delta_chi2"])) for r in wide_rows), default=0.0)
        # 杯溫導向：若 cup_temp_error 在 ±0.4 °C 內仍能變動 ≥0.3 °C，視為熱端有訊號
        cup_err_swings = [abs(float(r["cup_temp_error_C"]) - baseline_cup_err)
                          for r in near_rows
                          if r["cup_temp_error_C"] is not None and not np.isnan(r["cup_temp_error_C"])]
        cup_err_swing = max(cup_err_swings, default=0.0)
        level, advice = _judge_level(local_span, wide_span, weak_hi, hard_lo)
        # 杯溫是熱端最直接的觀測：swing ≥ 2σ (1.0 °C) 時即使 Δχ² 不夠也升一級。
        # F11：有分享壺溫時序的 case，同一個讀值已在時序項內（單點項不計分），
        # 不再用 swing 升級——否則等於把不在 loss 裡的量拿來判定可辨識度。
        if (cup_err_swing >= 2.0 * 0.5 and level == "weak"
                and "server_temp_series" not in baseline_terms):
            level, advice = "medium", "可保留（杯溫 swing ≥ 2σ）"
        return {
            "param": param_name,
            "in_fit": bool(param_name in live_set),
            "local_span": float(local_span),
            "wide_span": float(wide_span),
            "cup_err_swing_C": float(cup_err_swing),
            "level": level,
            "advice": advice,
        }

    factor_grid = np.array([0.70, 0.85, 1.00, 1.15, 1.30], dtype=float)
    # 邊界：避免極端 λ 讓 ODE 數值退化（過大讓溫度負值；過小讓 stage 5 fit 範圍外）
    # 邊界：避免極端值讓 ODE 數值退化。`U_liquid_dripper_W_m2K` 取代舊的
    # `lambda_liquid_dripper`（F2 標記為 DEPRECATED）；若該欄為 None/0（走舊路徑）
    # 才退回掃描 λ。
    u_liq = getattr(params_fit, "U_liquid_dripper_W_m2K", None)
    liq_spec = (
        ("U_liquid_dripper_W_m2K", float(u_liq), *U_LIQUID_DRIPPER_BOUNDS_W_M2K)
        if u_liq else
        ("lambda_liquid_dripper", float(params_fit.lambda_liquid_dripper), 1.0e-4, 1.0e-1)
    )
    slice_specs = [
        ("lambda_cool", float(params_fit.lambda_cool), 1.0e-5, 5.0e-3),
        liq_spec,
        ("lambda_dripper_ambient", float(params_fit.lambda_dripper_ambient), 1.0e-5, 5.0e-2),
        ("lambda_server_ambient", float(params_fit.lambda_server_ambient), 1.0e-5, 1.0e-2),
    ]

    slice_rows: list[dict] = []
    for param_name, center, low, high in slice_specs:
        for factor in factor_grid:
            trial_value = float(np.clip(center * factor, low, high))
            trial_params = _set_param(params_fit, param_name, trial_value)
            eval_row = evaluate_measured_flow_fit(flow_path, trial_params, tau_lag_s=tau_lag_s,
                                              solver=solver_cfg, k_beta_prior_psd=prior_frozen, **_nfp)
            cup_err = eval_row.get("cup_temp_error_C")
            terms = eval_row.get("chi2_terms", {})
            slice_rows.append({
                "param": param_name,
                # 與 fit identifiability 同一欄語意：False = 凍結 / 手調 default，
                # 這一列回答的是「凍結參數若偏離會怎樣」，不是本次擬合的不確定度。
                "in_fit": bool(param_name in live_set),
                # F11：Δχ² 的來源拆解——熱端參數經黏度回饋也會動 volume 項，
                # 必須分得出「熱時序識別了它」還是「水力項順帶變了」。
                "delta_chi2_volume": float(terms.get("volume", 0.0) - baseline_terms.get("volume", 0.0)),
                "delta_chi2_server_series": float(terms.get("server_temp_series", 0.0)
                                                  - baseline_terms.get("server_temp_series", 0.0)),
                "delta_chi2_cup_temp": float(terms.get("cup_temp", 0.0) - baseline_terms.get("cup_temp", 0.0)),
                "factor": float(factor),
                "value": trial_value,
                "delta_chi2": float(eval_row["chi2"] - baseline_chi2),
                "reduced_chi2": float(eval_row["reduced_chi2"]),
                "retention_rmse_ml": float(eval_row["retention_rmse_ml"]),
                "rmse_ml": float(eval_row["volume_rmse"]),
                "velocity_rmse_mlps": float(eval_row["velocity_rmse"]),
                "cup_stop_time_error_s": float(eval_row["cup_stop_time_error_s"]),
                "cup_temp_error_C": float(cup_err) if cup_err is not None else float("nan"),
            })

    slices_path = Path(slices_csv_path)
    slices_path.parent.mkdir(parents=True, exist_ok=True)
    with slices_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(slice_rows[0].keys()))
        writer.writeheader()
        writer.writerows(slice_rows)

    liq_name = liq_spec[0]
    pair_specs = [
        # 串聯 dripper path：液體→濾杯→空氣
        (liq_name, "lambda_dripper_ambient"),
        # 兩條液體散熱：直接（cool）vs 經過濾杯（U_liquid_dripper）
        ("lambda_cool", liq_name),
        # 兩條 ambient sink：cone 內 vs 杯端
        ("lambda_cool", "lambda_server_ambient"),
        # dripper terminal sink vs cup terminal sink
        ("lambda_dripper_ambient", "lambda_server_ambient"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(12.4, 8.6))
    fig.suptitle("Thermal Identifiability Around Measured Fit", fontsize=13, fontweight="bold")

    for ax, (param_x, param_y) in zip(axes.flat, pair_specs):
        spec_x = next(spec for spec in slice_specs if spec[0] == param_x)
        spec_y = next(spec for spec in slice_specs if spec[0] == param_y)
        x_vals = np.clip(spec_x[1] * factor_grid, spec_x[2], spec_x[3])
        y_vals = np.clip(spec_y[1] * factor_grid, spec_y[2], spec_y[3])
        z = np.zeros((len(y_vals), len(x_vals)))
        for iy, yv in enumerate(y_vals):
            for ix, xv in enumerate(x_vals):
                trial_params = _set_param(params_fit, param_x, float(xv))
                trial_params = _set_param(trial_params, param_y, float(yv))
                eval_row = evaluate_measured_flow_fit(flow_path, trial_params, tau_lag_s=tau_lag_s,
                                              solver=solver_cfg, k_beta_prior_psd=prior_frozen, **_nfp)
                z[iy, ix] = float(eval_row["chi2"] - baseline_chi2)

        im = ax.imshow(z, origin="lower", aspect="auto", cmap="YlOrRd")
        ax.set_title(f"{param_x} vs {param_y}")
        # 非 live 參數標 frozen：讀圖的人要知道哪條軸是本次擬合的自由度。
        ax.set_xlabel(param_x + ("" if param_x in live_set else " (frozen)"))
        ax.set_ylabel(param_y + ("" if param_y in live_set else " (frozen)"))
        ax.set_xticks(range(len(x_vals)))
        ax.set_xticklabels([f"{v:.3g}" for v in x_vals], rotation=30, ha="right")
        ax.set_yticks(range(len(y_vals)))
        ax.set_yticklabels([f"{v:.3g}" for v in y_vals])
        for iy in range(len(y_vals)):
            for ix in range(len(x_vals)):
                ax.text(ix, iy, f"{z[iy, ix]:.2f}", ha="center", va="center", fontsize=7)
        fig.colorbar(im, ax=ax, label="delta chi2")

    plt.tight_layout()
    heatmap_out = Path(heatmap_path)
    heatmap_out.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(heatmap_out, dpi=160, bbox_inches="tight")
    plt.close(fig)

    judgement_rows = [_slice_judgement(slice_rows, name) for name, *_ in slice_specs]
    recommendation = {
        f"fix_{row['param']}": row["level"] == "weak"
        for row in judgement_rows
    }

    print("\n=== Thermal Identifiability ===")
    print(f"  baseline chi2        : {baseline_chi2:.2f}  (reduced {baseline_reduced_chi2:.2f})")
    print(f"  levels               : weak < {weak_hi:.2f} <= medium < {hard_lo:.2f} <= hard")
    print(f"  baseline cup_temp_err: {baseline_cup_err:+.3f} °C")
    print(f"  slices csv           : {slices_path}")
    print(f"  heatmap png          : {heatmap_out}")
    for row in judgement_rows:
        status = "live" if row["in_fit"] else "frozen"
        print(
            f"  {row['param']:<22} : {row['level']:<6} [{status}] "
            f"(+-20% dchi2 {row['local_span']:.2f}, +-40% dchi2 {row['wide_span']:.2f}, "
            f"cup ΔT swing≈{row['cup_err_swing_C']:.2f} °C)"
            f"  → {row['advice']}"
        )

    return {
        "params_fit": params_fit,
        "info": info,
        "baseline": baseline,
        "baseline_chi2": baseline_chi2,
        "baseline_reduced_chi2": baseline_reduced_chi2,
        "slice_rows": slice_rows,
        "judgement_rows": judgement_rows,
        "recommendation": recommendation,
        "slices_csv_path": str(slices_path),
        "heatmap_path": str(heatmap_out),
        "factor_grid": factor_grid,
    }
