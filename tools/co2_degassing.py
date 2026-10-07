"""由 PSD 比表面積與脫氣文獻估算咖啡粉的 CO₂ 釋放量（理論估算，不改模型）。

What:
  1. 全豆儲存：自由 CO₂ 剩餘 M_free(t_r) = M∞ · exp(−(t_r/λ)^k)
     （Smrke et al. 2018，淺焙中速，35 °C：λ 715 h、k 0.842、M∞ 5.07 mg/g）。
     23 °C 情境以 Shimoni & Labuza 2000 的 Ea 73.6 kJ/mol 外推 λ。
  2. 研磨：破壁殼層 δ 內的氣體立即散失，比例 Σ vf_i · [1 − (1 − δ/R_i)³] ≈ S_v · δ，S_v = 6/d32。
  3. 悶蒸：完整細胞內 CO₂ 以擴散逸出，各 bin 核心半徑 R_core 用 Crank 球形解；短時間 F ≈ S_v,core · 2√(Dt/π)。
     兩個擴散情境：
       dry  D_ref ∈ {1e-15, 1e-14} m²/s（Shimoni，研磨粉；T_ref 假設 298 K）以 Ea 換算到沖煮溫度；
       wet  D = 模型 slow pool 溶質有效擴散係數 `effective_diffusivity(T_brew, slow=True)`（濕潤基質的上界假設）。
  4. 氣體體積：理想氣體，沖煮溫度、1 atm。
Why:
  模型的 CO₂ 背壓 `h_gas_0` 對所有案例固定，且無法由出液曲線辨識（EXP-20261007-HGAS-PROFILE）。
  先由文獻量級推導 CO₂ 在悶蒸期間可能釋放的氣體量，判斷它與床層孔隙體積、養豆天數的關係。
  推導見 `docs/theory/co2_degassing.md`。

用法：`uv run python tools/co2_degassing.py`（輸出 `data/co2_degassing_estimates.csv`）。
"""
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

R_GAS = 8.314
EA_J_MOL = 73.6e3              # Shimoni & Labuza 2000
M_CO2_KG_MOL = 44.01e-3
WEIBULL = dict(lam_h=715.0, k=0.842, Minf_mg_g=5.07)   # Smrke et al. 2018，淺焙中速，35 °C
T_SMRKE_K, T_ROOM_K, T_REF_D_K = 308.15, 296.15, 298.15
BLOOM_S = (35.0, 180.0)
AGE_DAYS = (7, 15)
CASES = (
    "data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv",
    "data/kinu_27_light/4:12/kinu27_light_20g_flow_profile.csv",
    "data/kinu_28_light/4:20/kinu28_light_20g_flow_profile.csv",
)
OUT = ROOT / "data/co2_degassing_estimates.csv"


def arrhenius(T: float, T_ref: float) -> float:
    return float(np.exp(-EA_J_MOL / R_GAS * (1.0 / T - 1.0 / T_ref)))


def sphere_release(x):
    """Crank 球形擴散釋放比例 F(x)，x = D t / R²。"""
    x = np.asarray(x, float)
    out = np.empty_like(x)
    small = x < 0.05
    out[small] = 6.0 * np.sqrt(x[small] / np.pi) - 3.0 * x[small]
    n = np.arange(1, 200)[:, None]
    big = ~small
    if big.any():
        out[big] = 1.0 - 6.0 / np.pi ** 2 * np.sum(np.exp(-(n ** 2) * np.pi ** 2 * x[big]) / n ** 2, axis=0)
    return out


def free_remaining_mg_g(t_r_days: float, T_store: float) -> float:
    lam_h = WEIBULL["lam_h"] / arrhenius(T_store, T_SMRKE_K)
    return WEIBULL["Minf_mg_g"] * float(np.exp(-((t_r_days * 24.0) / lam_h) ** WEIBULL["k"]))


def gas_ml(dose_g: float, mg_per_g: float, T_K: float) -> float:
    n_mol = dose_g * mg_per_g * 1e-6 / M_CO2_KG_MOL
    return n_mol * R_GAS * T_K / 101325.0 * 1e6


def main() -> None:
    from pour_over.benchmark import _load_measured_benchmark_state, _summary_path_for

    rows = []
    print(f"Arrhenius：沖煮 93 °C / 25 °C 的 D 比 ≈ {arrhenius(366.15, T_REF_D_K):.0f}；"
          f"23 °C / 35 °C 的 λ 比 = {1 / arrhenius(T_ROOM_K, T_SMRKE_K):.2f}")
    for T_store, lab in ((T_SMRKE_K, "35C"), (T_ROOM_K, "23C")):
        print(f"自由 CO₂ 剩餘（{lab}）第 1/7/15/30 天 [mg/g]：" +
              " / ".join(f"{free_remaining_mg_g(d, T_store):.2f}" for d in (1, 7, 15, 30)))

    for rel in CASES:
        flow = str(ROOT / rel)
        p, _ = _load_measured_benchmark_state(flow, _summary_path_for(flow), refit=False, verbose=False)
        case = rel.split("/")[1] + "/" + rel.split("/")[2]
        T_brew = float(p.T_brew)
        dose = float(p.dose_g)
        vf = p.ext_bin_volume_fraction / p.ext_bin_volume_fraction.sum()
        R = p.ext_bin_radius_m
        delta = float(p.shell_thickness)
        shell = 1.0 - (np.maximum(R - delta, 0.0) / R) ** 3
        f_grind = float(np.sum(vf * shell))
        d32 = float(p.d32)
        R_core = np.maximum(R - delta, 1e-9)
        w_core = vf * (1.0 - shell)
        Sv_core = float(np.sum(w_core * 3.0 / R_core) / w_core.sum())
        V_pore = float(p.phi) * p.cone_bed_volume_m3() * 1e6
        scenarios = [(f"dry_Dref{d:.0e}", d * arrhenius(T_brew, T_REF_D_K)) for d in (1e-15, 1e-14)]
        scenarios.append(("wet_model_slow_Deff", float(p.effective_diffusivity(T_brew, slow=True))))
        for scen, D in scenarios:
            for t in BLOOM_S:
                f_core = float(np.sum(w_core * sphere_release(D * t / R_core ** 2)) / w_core.sum())
                for T_store, slab in ((T_SMRKE_K, "35C"), (T_ROOM_K, "23C")):
                    for day in AGE_DAYS:
                        m_intact = free_remaining_mg_g(day, T_store) * (1.0 - f_grind)
                        released = m_intact * f_core
                        rows.append(dict(
                            case=case, d32_um=d32 * 1e6, S_v_per_m=6.0 / d32, shell_um=delta * 1e6,
                            grind_loss_fraction=f_grind, grind_loss_first_order=6.0 / d32 * delta,
                            pore_volume_ml=V_pore, diffusion_scenario=scen, D_m2_s=D, t_s=t,
                            core_release_fraction=f_core,
                            core_release_short_time=Sv_core * 2.0 * np.sqrt(D * t / np.pi),
                            storage=slab, age_days=day, free_co2_in_grounds_mg_g=m_intact,
                            released_mg_g=released, released_gas_ml=gas_ml(dose, released, T_brew),
                            co2_in_grounds_gas_ml=gas_ml(dose, m_intact, T_brew)))
        print(f"\n{case}：d32 {d32*1e6:.0f} μm，S_v {6/d32:.0f} m⁻¹，研磨散失 {f_grind:.3f}"
              f"（一階 S_v·δ {6/d32*delta:.3f}），孔隙 {V_pore:.1f} mL")
        for r in rows:
            if r["case"] == case and r["t_s"] == 35.0 and r["storage"] == "23C":
                print(f"  {r['diffusion_scenario']:22s} D {r['D_m2_s']:.2e}  第 {r['age_days']:>2} 天："
                      f"粉中 {r['free_co2_in_grounds_mg_g']:.2f} mg/g（{r['co2_in_grounds_gas_ml']:.1f} mL），"
                      f"悶蒸 35 s 釋出 {r['core_release_fraction']:.3f} → {r['released_gas_ml']:.1f} mL")

    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: (repr(float(v)) if isinstance(v, (float, np.floating)) else v) for k, v in r.items()})
    print(f"\nwrote {OUT.relative_to(ROOT)}（{len(rows)} 列）")


if __name__ == "__main__":
    main()
