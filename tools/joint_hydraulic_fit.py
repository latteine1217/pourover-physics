"""跨 brew 共用水力參數的聯合擬合與留一預測（分析用，不改模型）。

What:
  三個影片案例，水力目標只取資料項（volume + stop_time，不含 prior），熱與萃取參數固定在各案 baseline。
    H0   每案各自 (k, n, tau_wet)                         9 參數
    H1k  共用 k；n、tau_wet 各案                           7 參數
    H1kn 共用 k、n；tau_wet 各案                           5 參數
    H1   共用 (k, n, tau_wet)                              3 參數
    LOO  用兩案擬合共用 (k, n, tau_wet)，預測第三案
  least_squares（TRF，log10 空間，前向差分 1e-3 dex），SOLVER_FINE。
Why:
  「measured PSD → 跨研磨度的 k」只有在不同研磨刻度的水力差異超出量測雜訊時才可能被檢驗；
  共用參數模型的 Δχ² 直接回答現有三支影片 brew 能否區分它們。

用法：`uv run python tools/joint_hydraulic_fit.py [data|prior]`（輸出 `data/joint_hydraulic_fit_<objective>.csv`）。
"""
import csv
import dataclasses
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = (
    "data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv",
    "data/kinu_27_light/4:12/kinu27_light_20g_flow_profile.csv",
    "data/kinu_28_light/4:20/kinu28_light_20g_flow_profile.csv",
)
# 目標：`data` 只取 volume + stop_time；`prior` 另含每案 Corey n 的 log prior（與正式水力 stage 相同）。
OBJECTIVE = sys.argv[1] if len(sys.argv) > 1 else "data"
OUT = ROOT / f"data/joint_hydraulic_fit_{OBJECTIVE}.csv"
NAMES = ("k", "sat_rel_perm_exp", "tau_wet_s")


def _load():
    from pour_over.benchmark import _load_measured_benchmark_state, _summary_path_for
    from pour_over.fitting import _prepare_measured_case
    states = []
    for rel in CASES:
        flow = str(ROOT / rel)
        p, i = _load_measured_benchmark_state(flow, _summary_path_for(flow), refit=False, verbose=False)
        states.append(dict(name=rel.split("/")[1] + "/" + rel.split("/")[2], p=p, info=i, case=_prepare_measured_case(flow)))
    return states


def _bounds():
    from pour_over.fitting import K_BOUNDS_M2, SAT_REL_PERM_EXP_BOUNDS, TAU_WET_BOUNDS_S
    return {"k": K_BOUNDS_M2, "sat_rel_perm_exp": SAT_REL_PERM_EXP_BOUNDS, "tau_wet_s": TAU_WET_BOUNDS_S}


def _evaluate(st, vals):
    from pour_over.fitting import MEASURED_VESSEL_EQUIV_ML, SOLVER_FINE, _chi2_evaluate
    p = dataclasses.replace(st["p"], **vals)
    out = _chi2_evaluate(st["case"], p, st["info"]["tau_lag_s"], vessel_equivalent_ml=MEASURED_VESSEL_EQUIV_ML, solver=SOLVER_FINE,
                         k_beta_prior_psd=st["info"].get("k_beta_prior_psd"))
    h = np.asarray(out["hydraulic_residuals"], float)
    # 版面：volume…, stop_time, prior:k_beta（恆 0）, prior:Corey n
    r = h[:-2] if OBJECTIVE == "data" else np.concatenate([h[:-2], h[-1:]])
    v = np.asarray(out["v_residual_ml"], float)
    return r, float(np.sqrt(np.mean(v ** 2)))


def fit(model: str, idx: tuple[int, ...]) -> dict:
    """model ∈ {H0_i, H1k, H1kn, H1}；idx 為參與擬合的案例。"""
    states = [s for j, s in enumerate(_load()) if j in idx]
    B = _bounds()
    shared = {"H1": NAMES, "H1kn": ("k", "sat_rel_perm_exp"), "H1k": ("k",)}.get(model.split("_")[0], ())
    layout = [(n, None) for n in shared] + [(n, j) for j in range(len(states)) for n in NAMES if n not in shared]

    def unpack(x):
        per = [dict() for _ in states]
        for (n, j), v in zip(layout, x):
            val = 10.0 ** v
            for jj in (range(len(states)) if j is None else (j,)):
                per[jj][n] = val
        return per

    def init(n, j):
        js = range(len(states)) if j is None else (j,)
        return float(np.mean([np.log10(getattr(states[jj]["p"], n)) for jj in js]))

    x0 = np.array([init(n, j) for n, j in layout])
    lo = np.array([np.log10(B[n][0]) for n, _ in layout])
    hi = np.array([np.log10(B[n][1]) for n, _ in layout])
    x0 = np.clip(x0, lo + 1e-6, hi - 1e-6)

    def resid(x):
        return np.concatenate([_evaluate(s, v)[0] for s, v in zip(states, unpack(x))])

    res = least_squares(resid, x0, bounds=(lo, hi), method="trf", diff_step=1e-3, x_scale=1.0)
    per = unpack(res.x)
    rows = []
    for s, v in zip(states, per):
        r, rmse = _evaluate(s, v)
        rows.append(dict(model=model, case=s["name"], chi2_data=float(r @ r), v_rmse_ml=rmse,
                         n_resid=int(r.size), **{n: float(v[n]) for n in NAMES},
                         at_bound=";".join(n for (n, j), xv, lb, ub in zip(layout, res.x, lo, hi)
                                           if (j is None or states[j] is s) and (xv <= lb + 1e-4 or xv >= ub - 1e-4)),
                         n_param=len(layout), nfev=int(res.nfev)))
    return dict(model=model, rows=rows, per=per, states_idx=idx)


def predict(left_out: int, shared_vals: dict) -> dict:
    st = _load()[left_out]
    r, rmse = _evaluate(st, shared_vals)
    return dict(model="LOO_predict", case=st["name"], chi2_data=float(r @ r), v_rmse_ml=rmse, n_resid=int(r.size),
                **{k: float(v) for k, v in shared_vals.items()}, at_bound="", n_param=0, nfev=1)


def main():
    jobs = [("H0_0", (0,)), ("H0_1", (1,)), ("H0_2", (2,)), ("H1k", (0, 1, 2)), ("H1kn", (0, 1, 2)), ("H1", (0, 1, 2))]
    jobs += [(f"H1_loo{j}", tuple(i for i in range(3) if i != j)) for j in range(3)]
    from pour_over.fitting import _single_thread_blas_env
    # 子行程繼承單執行緒 BLAS，避免 N 個 worker 各開滿核心而超訂 CPU（同正式 multi-start）
    with _single_thread_blas_env(), ProcessPoolExecutor(max_workers=min(len(jobs), os.cpu_count() or 1)) as ex:
        results = list(ex.map(fit, *zip(*jobs)))
    rows = [r for res in results for r in res["rows"]]
    loo = [res for res in results if "loo" in res["model"]]
    with _single_thread_blas_env(), ProcessPoolExecutor(max_workers=3) as ex:
        preds = list(ex.map(predict, [int(r["model"][-1]) for r in loo], [r["per"][0] for r in loo]))
    for pr, res in zip(preds, loo):
        pr["model"] = f"LOO_predict_from_{res['model']}"
    rows += preds
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: (repr(float(v)) if isinstance(v, (float, np.floating)) else v) for k, v in r.items()})
    for r in rows:
        print({k: (f"{v:.4g}" if isinstance(v, float) else v) for k, v in r.items()})
    tot = {m: sum(r["chi2_data"] for r in rows if r["model"].startswith(m) and "loo" not in r["model"] and "LOO" not in r["model"])
           for m in ("H0", "H1k", "H1kn", "H1")}
    tot["H1k"] = sum(r["chi2_data"] for r in rows if r["model"] == "H1k")
    tot["H1kn"] = sum(r["chi2_data"] for r in rows if r["model"] == "H1kn")
    tot["H1"] = sum(r["chi2_data"] for r in rows if r["model"] == "H1")
    print("\nΣχ²_data：", {k: round(v, 3) for k, v in tot.items()})
    print("Δχ² vs H0：H1k", round(tot["H1k"] - tot["H0"], 3), "(χ²₂ 95% 5.99)；H1kn", round(tot["H1kn"] - tot["H0"], 3),
          "(χ²₄ 9.49)；H1", round(tot["H1"] - tot["H0"], 3), "(χ²₆ 12.59)")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
