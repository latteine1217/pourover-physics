"""各案 live 參數的完整共變異（Gauss-Newton）與條件式 1σ 的比較（分析用，不改模型）。

What:
  在 baseline 最佳點，對 live 參數 θ = log10(k, n, tau_wet, U 或 λ_server, tau_tort) 以中央差分（±0.01 dex）
  計算總 χ² 標準化殘差向量的 Jacobian J；Cov = (JᵀJ)⁻¹。報告：
    marginal 1σ = √Cov_ii（其他參數同時調整），conditional 1σ = 1/√(JᵀJ)_ii（其他參數固定，同現行 CI slice），
    兩者比值，以及相關係數矩陣。
  殘差含 prior 偽觀測（Corey n、U、tau_tort），與擬合目標一致。
Why:
  AGENTS.md §6 與 README 註明現行 CI 是 conditional slice（下界）。需要知道低估多少、哪些參數彼此簡併。
  `tau_wet` 貼下界時 Gauss 近似不可靠，結果另行標註。

用法：`uv run python tools/param_covariance.py`（輸出 `data/param_covariance.csv`）。
"""
import csv
import dataclasses
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = (
    "data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv",
    "data/kinu_27_light/4:12/kinu27_light_20g_flow_profile.csv",
    "data/kinu_28_light/4:20/kinu28_light_20g_flow_profile.csv",
)
FIELD = {"k": "k", "sat_rel_perm_exp": "sat_rel_perm_exp", "tau_wet_s": "tau_wet_s",
         "U_liquid_dripper_W_m2K": "U_liquid_dripper_W_m2K", "lambda_server_ambient": "lambda_server_ambient",
         "tau_tort": "tau_tort"}
STEP_DEX = 0.01
OUT = ROOT / "data/param_covariance.csv"


def main():
    from pour_over.benchmark import _load_measured_benchmark_state, _summary_path_for
    from pour_over.fitting import MEASURED_VESSEL_EQUIV_ML, SOLVER_FINE, _chi2_evaluate, _prepare_measured_case

    rows = []
    for rel in CASES:
        flow = str(ROOT / rel)
        p, i = _load_measured_benchmark_state(flow, _summary_path_for(flow), refit=False, verbose=False)
        case = _prepare_measured_case(flow)
        live = [n for n in str(i.get("fit_live_param_names") or
                                next(csv.DictReader(open(_summary_path_for(flow))))["fit_live_param_names"]).split(";")
                if n in FIELD]

        def resid(q):
            out = _chi2_evaluate(case, q, i["tau_lag_s"], vessel_equivalent_ml=MEASURED_VESSEL_EQUIV_ML, solver=SOLVER_FINE,
                                 k_beta_prior_psd=i.get("k_beta_prior_psd"), n_fit_params=len(live))
            return np.asarray(out["residuals"], float)

        r0 = resid(p)
        J = np.zeros((r0.size, len(live)))
        for j, n in enumerate(live):
            v = float(getattr(p, FIELD[n]))
            rp = resid(dataclasses.replace(p, **{FIELD[n]: v * 10 ** STEP_DEX}))
            rm = resid(dataclasses.replace(p, **{FIELD[n]: v * 10 ** -STEP_DEX}))
            J[:, j] = (rp - rm) / (2 * STEP_DEX)
        H = J.T @ J
        cov = np.linalg.inv(H)
        marg = np.sqrt(np.diag(cov))
        cond = 1.0 / np.sqrt(np.diag(H))
        corr = cov / np.outer(marg, marg)
        name = rel.split("/")[1] + "/" + rel.split("/")[2]
        print(f"\n=== {name}（χ² {float(r0 @ r0):.3f}，{r0.size} 殘差）===")
        print("  param                    value        marg1σ[dex]  cond1σ[dex]  marg/cond  marg 68% 區間")
        for j, n in enumerate(live):
            v = float(getattr(p, FIELD[n]))
            lo, hi = v * 10 ** -marg[j], v * 10 ** marg[j]
            print(f"  {n:24s} {v:11.4g}  {marg[j]:10.4f}  {cond[j]:10.4f}  {marg[j]/cond[j]:8.2f}  [{lo:.4g}, {hi:.4g}]")
            rows.append(dict(case=name, param=n, value=v, marginal_sigma_dex=float(marg[j]),
                             conditional_sigma_dex=float(cond[j]), ratio=float(marg[j] / cond[j]),
                             marginal_lo=lo, marginal_hi=hi,
                             **{f"corr_{m}": float(corr[j, jj]) for jj, m in enumerate(live)}))
        print("  correlation:")
        for j, n in enumerate(live):
            print(f"    {n:24s} " + " ".join(f"{corr[j, jj]:+.2f}" for jj in range(len(live))))
    keys = sorted({k for r in rows for k in r}, key=lambda k: (k.startswith("corr_"), k))
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (repr(float(r[k])) if isinstance(r.get(k), float) else r.get(k, "")) for k in keys})
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
