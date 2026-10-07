"""PSD 量測不確定度對 canonical 擬合的傳遞（分析用，不改模型）。

What:
  canonical `kinu29/4:12`（影片版）在下列 PSD 變體下：
    own        自身 PSD（4:12 掃描），psd_diameter_scale = 1（基準）
    swap_4:11  同刻度另一日掃描 `data/kinu_29_light/4:11/kinu29_psd_bins.csv`
    scale_x    自身 PSD × {0.70, 0.85, 1.20, 1.45}（README：絕對尺度 ±45% 未收斂）
  每個變體：
    (a) 不重擬：baseline 參數固定，`k_beta` 改為新 PSD 的 prior（Class B），量 χ²、volume 項、TDS 誤差；
    (b) 重擬：從 baseline 參數單起點完整擬合（stage 1/2/4/5/7），量 k、n、tau_wet、tau_tort、χ²、TDS 誤差。
Why:
  同刻度兩日 d32 差約 20%，大於刻度間差異；新萃取 closure 下 TDS 對粒徑尺度敏感
  （EXP-20261007-EXTRACTION-CLOSURE-REWRITE）。需要量化 PSD 雜訊傳到參數與預測的大小，決定後續 PSD 量測的精度需求。

用法：`uv run python tools/psd_uncertainty.py`（輸出 `data/psd_uncertainty.csv`）。
"""
import csv
import dataclasses
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FLOW = ROOT / "data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv"
OWN_BINS = ROOT / "data/kinu_29_light/4:12/kinu29_psd_bins.csv"
SWAP_BINS = ROOT / "data/kinu_29_light/4:11/kinu29_psd_bins.csv"
VARIANTS = [("own", OWN_BINS, 1.0), ("swap_4:11", SWAP_BINS, 1.0)] + \
           [(f"scale_{s:.2f}", OWN_BINS, s) for s in (0.70, 0.85, 1.20, 1.45)]
OUT = ROOT / "data/psd_uncertainty.csv"


def run_variant(label: str, bins: Path, scale: float) -> dict:
    import pour_over.fitting as F
    from pour_over.benchmark import _load_measured_benchmark_state, _summary_path_for
    from pour_over.params import V60Params

    p0, i0 = _load_measured_benchmark_state(str(FLOW), _summary_path_for(str(FLOW)), refit=False, verbose=False)

    # (a) 不重擬：同一組擬合參數，只換 PSD（k_beta 跟著新 PSD 的 Class B prior）
    pa = dataclasses.replace(p0, psd_bins_csv_path=str(bins), psd_diameter_scale=scale)
    pa = dataclasses.replace(pa, k_beta=float(pa.k_beta_prior_psd))
    ea = F.evaluate_measured_flow_fit(str(FLOW), pa, i0["tau_lag_s"], solver=F.SOLVER_FINE,
                                      k_beta_prior_psd=float(pa.k_beta_prior_psd))

    # (b) 重擬：擬合流程會從 case 目錄決定 PSD 路徑，於本行程內改寫 overrides 指向變體 PSD
    orig = F._measured_setup_overrides

    def patched(meta, flow_csv_path=None):
        out = orig(meta, flow_csv_path=flow_csv_path)
        out["psd_bins_csv_path"] = str(bins)
        return out

    F._measured_setup_overrides = patched
    init = V60Params(k=p0.k, sat_rel_perm_exp=p0.sat_rel_perm_exp, tau_wet_s=p0.tau_wet_s,
                     tau_tort=p0.tau_tort, psd_diameter_scale=scale)
    pb, ib = F.fit_k_kbeta_from_flow_profile(csv_path=str(FLOW), params_init=init, tau_wet_init_s=float(p0.tau_wet_s),
                                             fit_preferential_flow=True, compute_ci=False, verbose=False)
    F._measured_setup_overrides = orig
    assert Path(pb.psd_bins_csv_path).resolve() == bins.resolve() and abs(pb.psd_diameter_scale - scale) < 1e-12
    eb = F.evaluate_measured_flow_fit(str(FLOW), pb, ib["tau_lag_s"], solver=F.SOLVER_FINE,
                                      k_beta_prior_psd=float(pb.k_beta_prior_psd))
    return dict(
        variant=label, psd_bins=str(bins.relative_to(ROOT)), psd_diameter_scale=scale,
        d32_um=float(pa.d32) * 1e6, k_beta=float(pa.k_beta_prior_psd),
        fast_mass_fraction=float(pa.fast_pool_mass_fraction),
        norefit_chi2=float(ea["chi2"]), norefit_chi2_volume=float(ea["chi2_terms"]["volume"]),
        norefit_tds_error_gl=float(ea["tds_error_gl"]),
        refit_chi2=float(eb["chi2"]), refit_chi2_volume=float(eb["chi2_terms"]["volume"]),
        refit_tds_error_gl=float(eb["tds_error_gl"]), refit_k=float(pb.k),
        refit_sat_rel_perm_exp=float(pb.sat_rel_perm_exp), refit_tau_wet_s=float(pb.tau_wet_s),
        refit_tau_tort=float(pb.tau_tort), refit_U=float(pb.U_liquid_dripper_W_m2K),
        stage7_skipped=str(ib.get("stage7_skipped_reason", "")),
    )


def main():
    from pour_over.fitting import _single_thread_blas_env
    with _single_thread_blas_env(), ProcessPoolExecutor(max_workers=min(len(VARIANTS), os.cpu_count() or 1)) as ex:
        rows = list(ex.map(run_variant, *zip(*VARIANTS)))
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: (repr(float(v)) if isinstance(v, float) else v) for k, v in r.items()})
    for r in rows:
        print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
