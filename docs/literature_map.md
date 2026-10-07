# Literature Map for the Reduced-Order V60 Model

This note maps the current model closures to external literature. It is not a
claim that every fitted parameter is literature-derived. The goal is to separate
directly supported physics from engineering proxies that must remain calibrated
against measured V60 data.

Support levels:

- **Direct**: the source studies coffee brewing or coffee packed beds with a
  closely related model form.
- **Analogous**: the source supports the transport/porous-media mechanism, but
  not specifically this V60 geometry or protocol.
- **Proxy**: the closure is mainly an engineering approximation; literature only
  motivates the direction or boundary condition.

## Current Model Surface

| Closure / state | Local implementation | Literature status | Current interpretation |
|---|---|---|---|
| Darcy bed flow | `pour_over.params.V60Params.q_extract()` | Direct | Coffee beds can be modeled as porous media with Darcy-type flow, but V60 hydrostatic heads are far below espresso pressures. Calibrated `k` is therefore a V60 effective permeability, not an espresso puck constant. It also absorbs the filter-paper resistance and the outlet contraction, neither of which is measured separately. Darcy's linear regime holds at V60 flow rates: at peak outflow the permeability-based Reynolds number `ρ u √k / μ` is about 0.04, and an Ergun estimate puts the inertial correction at a few percent. |
| Mobile / immobile bed water | `core.simulate_brew()` states `V_mob`, `V_imm`, `w` | Analogous | Dual-porosity / mobile-immobile transport is standard in unsaturated soil physics for media where part of the pore water is effectively stagnant. Its use here is forced by measurement rather than imported from coffee literature: the measured retained mass drops below the pore volume shortly after the bloom and exceeds pore-plus-absorption capacity at the end, which a single pore-water pool cannot represent. The capacity-opening timescale `tau_wet` is calibrated against retained mass, not against `V_out`. |
| Young-Laplace bed retention | `V60Params.h_cap_bed()`, `V60Params.bed_retention_fraction()` | Analogous | `h_cap = 2σ(T)/(ρ g r_pore)` is the standard capillary-rise scale, and comparing it with the bed height is the usual way to decide whether a wet medium drains under gravity. The reduction of the pore-throat distribution to a single `r_pore = 0.2 · d32` is a closure choice. Its role is to set the immobile-pool capacity; it is deliberately **not** subtracted from the through-bed pressure gradient, which is the separate question of what drives flow. The canonical brew ends with 2.47 g of water retained per g of coffee, matching the 2.48 ± 0.19 g/g measured by Liang et al. (2021) for drained immersion grounds and the 1.76–2.39 g/g fitted by Lee & Chang (2026); because retention is mostly fixed by measured inflow minus outflow, this is a consistency check on the data and the pool capacities, not a prediction. |
| Porosity-to-permeability correction | `V60Params.k_eff()`, `V60Params.phi_effective()` | Direct / analogous | Kozeny-Carman gives the right qualitative dependence on porosity, but not an absolute or cross-grind permeability. With dry laser-diffraction `d[3,2]`, KC overpredicts espresso-bed permeability by 30% (finest) to 520% (coarsest) of four grinds, an error that grows with grind size (Corrochano 2017 thesis, Ch. 6); XCT/lattice-Boltzmann permeability is non-monotonic in grind setting (Wadsworth et al. 2026); Lee & Chang (2026) need a per-grind fitted hydraulic diameter that grows as the grind gets finer. Here the fitted `k` is about 17× below KC with `d32` and `φ = 0.4`, the same direction. `k` is fitted per brew; the PSD enters flow only through clogging and capillary retention. Use KC as a porosity trend term, not an absolute or cross-grind predictor. |
| Additive hydraulic resistance | `V60Params.k_eff()` | Analogous | Adding incremental resistances is physically cleaner than stacking hidden multipliers. The exact decomposition into throat, deposition, and post-bloom terms is a model design choice that must be kept identifiable. |
| Split fines clogging | `V60Params.clogging_bin_profiles()`, `V60Params.k_beta_components()` | Direct / proxy | Literature supports fines as important for permeability and extraction dynamics. The current number-weighted throat versus volume-weighted deposition split is plausible, but not yet directly validated for V60. |
| Bypass / wall-channel route | `V60Params.q_bypass()` | Proxy | Non-uniform flow and channeling are well documented for coffee beds, but the V60 rib/filter bypass law is a reduced-order empirical closure. Keep fitted/diagnostic, not universal. |
| Preferential-flow state | `V60Params.q_preferential()`, `V60Params.d_preferential_flow_dt()` | Direct / proxy | Fine-grind inhomogeneous flow is supported, but the one-state `xi_pref` ODE is an engineering proxy. Default `pref_flow_coeff = 0` is consistent with the current measured fit. |
| Unsaturated relative permeability | `V60Params.relative_permeability()` | Analogous | Corey-style saturation attenuation is standard porous-media practice, and the argument is now the **mobile** saturation `S_mob = V_mob / (φV_bed − V_imm)`. Residual saturation is carried explicitly by the immobile pool, so the Corey `S_r` is structurally zero rather than a fitted constant — keeping both would count the same retained water twice. The implemented form is `kr = smoothstep(S_mob)^n` with `smoothstep(S) = 3S² − 2S³`, not `S^n`, and the drive head also scales with `S_mob`; at low saturation the flux therefore falls roughly as `S^(2n+1)`. The fitted `n` (2.9–3.4 across brews) is a shape exponent of this form and is not comparable to a soil-physics Brooks-Corey exponent. |
| Capillary wetting | `V60Params.tau_cap_T()`, `core.simulate_brew()` `sat` ODE | Analogous | Lucas-Washburn supports the `sigma / mu` temperature scaling for capillary penetration. Coffee-bed contact angle, pore-size distribution, and degassing make the fitted time constant empirical. |
| CO2 gas back-pressure | `V60Params.h_gas()` | Proxy | Coffee degassing is real, but this exponential equivalent-head term is not directly literature-calibrated. Treat as a bloom choke proxy bounded by measured flow data. |
| Measured PSD ingestion | `psd.load_psd_raw_csv()`, `V60Params._particle_stats_from_bins_csv()`, `V60Params._build_extraction_bins_from_rows()` | Direct for the mechanism, **weak for the absolute scale** | PSD affects surface area, flow uniformity, and extraction, and measured PSD remains the primary path. But the absolute length scale is not literature-supported, it is instrument metadata: the raw export's `PIXEL_SCALE` is read as **px/mm** (17.2 px/mm for the legacy top-level scan, 34–37 px/mm per case). The previous pipeline hard-coded divisors equivalent to 100 μm/px and put per-case `Dv50` at 4.2 mm. Even after the correction, a **±45% absolute-scale uncertainty has not converged** (the stats-CSV back-solved scale is 1.45× larger, cause unknown), and within-setting spread (17–34%) exceeds between-setting difference (7%), so the current PSD cannot resolve one grinder click. Claims about surface area are therefore relative, not absolute. |
| Microstructure / particle geometry | `V60Params._particle_stats_from_bins_csv()` | Direct / analogous | Micro-CT/SPH studies support the idea that particle-scale coffee microstructure affects flow. The current aspect-ratio/roundness indices are reduced-order proxies. |
| Shell accessibility | `V60Params._build_extraction_bins_from_rows()` | Proxy | A finite shell/core distinction is consistent with fast surface release plus slower kernel diffusion, but the fixed 200 μm shell is 5–10 coffee cells deep (cells are 20–40 μm, Moroney et al. 2019) and puts 69% of the canonical extractable mass in the fast pool. A 30–300 μm scan (`EXP-20261007-SHELL-THICKNESS-SCAN`) shows shell thickness, `max_EY` and `tau_tort` are degenerate against one TDS reading and that shell thickness does not explain the cross-brew `tau_tort` spread. |
| Fast/slow extraction pools | `core.simulate_brew()` extraction states | Analogous / proxy | Double-porosity coffee extraction literature (Moroney et al. 2015, 2019) separates rapid release from fines and the broken-cell surface layer from slower diffusion through intact cell walls in the kernel. The model keeps the two-pool structure but not that mechanism: both pools diffuse with the same Stokes-Einstein `D_eff` (solute radius 0.40 vs 1.00 nm) and no cell-wall barrier, so the split is a geometric depth cut. In the canonical brew the mass-weighted fast time constant (about 54 s) overlaps the slow time constants of the main size bins (47–124 s). |
| Crank first-term release, sealed-inner-face shell (fast pool) | `V60Params.lambda_fast_bins()`, fast-pool transfer in `core.simulate_brew()` | Analogous | Superseded 2026-09-24: the fast pool is no longer a Noyes-Whitney `A·D/δ` mass-transfer rate. It now takes the same Crank-series first-eigenvalue structure as the slow pool, `λ_fast,i = π²·D_eff(T)/(2δ_i)²`, treating the broken-shell layer as a slab open on the pore-liquid face and sealed on the unbroken-core face (equivalent diffusion half-length `2δ_i`, not `δ_i`). This convention is an `O(1)` choice degenerate with `tau_tort`: the earlier "whole-sphere" convention `π²D/δ²` would rescale the fitted `tau_tort` by 4×. The empirical efficiency prefactor `nw_eta_*` no longer exists in either pool. The remaining uncalibrated quantity is `shell_thickness` itself. |
| Crank first-term release (slow pool) | slow-pool transfer in `core.simulate_brew()` | Direct / analogous | Crank's solution for diffusion out of a sphere is a series whose leading term decays as `exp(-π² D t / R²)`; retaining only that term gives a first-order release `d M_i/dt = -λ_i M_i` with `λ_i = π² D / (τ_tort R_i²)`. The form is standard; what is calibrated is the single effective tortuosity `tau_tort`, with a log-space prior centred on 5 (literature range roughly 2–10) and bounds deliberately widened to 100 so that "the fit pushed it to the bound" is an observable failure signal. |
| Stokes-Einstein diffusivity | solute diffusivity in `core.simulate_brew()` | Direct / analogous | `D(T) = k_B T / (6π μ(T) r)` is the textbook dilute-solution result and now carries **all** of the transport temperature dependence. The previous model applied it *and* an Arrhenius factor *and* a `D` inside the diffusion factor, which made the slow pool 2.33× more temperature-sensitive over 80–95 °C than Stokes-Einstein alone (1.25×). The hydrodynamic radii (0.40 / 1.00 nm) are order-of-magnitude assumptions, fully degenerate with `tau_tort`. |
| Internal diffusion factor | **removed (2026-09)** | — | The `exp(-path^2 / 4Dt)` factor was removed, not downgraded. It approaches 1 as `t → ∞`, i.e. the release rate *increases* as the grain empties, which is the opposite of the decaying flux that grain-diffusion literature (and Crank's series) gives. It also sat below 0.1 for the whole brew on the bins carrying most of the slow mass, and a large compensating coefficient existed solely to undo that suppression. Replaced by the Crank first term (row above). |
| Axial CSTR layers | `core.simulate_brew()` concentration update | Direct / analogous | Packed-bed models and extraction-uniformity work support spatial gradients. Two CSTR layers are a reduced-order substitute for a PDE/CFD bed. |
| Flow-dependent transfer factor | **removed (2026-09)** | — | The Hill `flow_factor` claimed transfer drops to a tenth of its value when the bed is static, but the sphere Sherwood number has a floor of 2 at `Re → 0`, so no such suppression exists. Its two parameters were also unidentifiable against a single final TDS reading. Flow still affects extraction through residence time and through the concentration carried out of each layer; it no longer multiplies the transfer coefficient. |
| Wet-bed capillary drive head (`h_cap_wet`) | **removed (2026-10)** | — | An extra drive head of about 2 mm was added once the bed was wet, together with a 55% cut of the `h_cap + h_gas` threshold. Inside a saturated bed there is no liquid-gas interface, so capillarity adds no through-bed head, which is the same argument used to keep `h_cap_bed` out of the gradient. Its coefficients cited no source and were tuned against TDS/EY. Removing it moved the video-brew χ² by +0.07 each and raised `k` by about 2% (`EXP-20261007-HCAP-WET-REMOVAL`). |
| Arrhenius temperature factors | **removed (2026-09)** | — | Coffee extraction kinetics are temperature-dependent, but that dependence is already carried by `D(T)`. Applying an Arrhenius factor on top counted it a second time, and `Ea_fast` / `Ea_slow` were never independently calibrated. Removed together with the roast-level `Ea_slow`. |
| Two-node liquid/dripper thermal model | `core.simulate_brew()` `T`, `T_dripper` | Analogous / calibrated | Lumped heat-capacity balances are appropriate at this reduced order. Dripper mass and heat capacity are measured and stay fixed; the vessel equivalent heat capacity is **back-solved, not measured**. |
| `U · A_wet(h)` dripper exchange | `V60Params.wetted_area()`, exchange term in `core.simulate_brew()` | Analogous | Writing the liquid-to-dripper exchange as an area-resolved coefficient is standard lumped-capacitance practice, and it makes the parameter checkable: a wet-paper-plus-ceramic series estimate bounds `U` to roughly 120–550 W/(m²K) with a nominal 194. The superseded lumped rate constant implied `U ≈ 1044`, above that bound, because it was simultaneously covering a heat-capacity deficit and the missing enthalpy of absorbed water. The fit now carries a log-space prior on `U` instead of an unconstrained rate. |
| Coffee solid heat capacity | `pour_over.constant.V60Constant.Cp_coffee` | Direct / analogous | Literature values for coffee thermal properties span a wide range with moisture and roast. The current value is a forward input with sensitivity absorbed by thermal fit. |
| SCA / brewing-control targets | `README.md`, diagnostics | Direct for quality target | EY/TDS targets are useful for cup-quality framing, but they validate sensory regime, not physical model correctness. |

## High-Confidence Anchors

### Darcy flow and permeability

Corrochano et al. developed a method to estimate permeability of roast and
ground coffee beds and fit flow/pressure data to Darcy's law. Their espresso-bed
permeability values are much lower than this V60 model's fitted effective
permeability, which is expected because the systems differ in pressure,
compaction, geometry, and grind regime. The important model implication is not
to copy their `k`, but to preserve Darcy structure and keep `k` as a calibrated
effective bed parameter.

Corrochano et al. also found conventional Kozeny-Carman overpredicted measured
coffee-bed permeability. The first author's thesis gives the numbers: with dry
laser-diffraction `d[3,2]` the overprediction grows from 30% to 520% across four
grinds, and matching the data needs a tortuosity exponent refitted per grind
(0.27–1.01). Lee & Chang (2026), the closest published pour-over model, likewise
fit a hydraulic diameter per grind and interpolate it as a power law in D90.
This supports the current policy: Kozeny-Carman can express porosity
sensitivity, but cannot replace measured calibration, and a single PSD length
scale is not known to carry `k` across grind settings. All of this evidence is
from espresso or untamped samples; for gravity-driven beds it is untested (the
four calibration brews span too narrow a grind range, see
`docs/literature_review/pour_over_modelling/phase5_synthesis/gaps.md`).

### Measured PSD and non-uniform extraction

Cameron et al. show that grind setting affects PSD and that homogeneous-flow
models can fail at fine settings because measured extraction yield peaks and
then drops, implying inhomogeneous flow. This supports:

- retaining measured PSD as first-class input;
- keeping preferential flow or bypass closures available for diagnostics;
- avoiding the claim that finer grind always monotonically improves extraction.

Moroney et al. (2019) model extraction uniformity in coffee beds and compare
one-dimensional flow models with CFD in cylindrical and truncated-cone
geometries. This is the closest published support for this project's axial
layers and concern with V60-like geometry. The model here remains much lower
order, so its axial CSTR layers should be described as a reduced-order
approximation, not a replacement for spatially resolved transport.

Mo et al. (2023) use X-ray microtomography and smoothed-particle hydrodynamics
to connect coffee matrix microstructure with flow properties. This strengthens
the rationale for retaining measured particle geometry statistics, but does not
directly validate the current scalar irregularity exponents.

### Fast and slow extraction pools

Moroney et al. (2015, 2019) model coffee extraction as a doubly porous medium:
fines and the broken-cell surface layer (about one 20–40 μm cell deep) release
quickly, and the kernel releases slowly through intact cell walls. The current
model keeps the two-pool structure, but its shell is 200 μm deep and both pools
use the same diffusivity, so it supports the structure only, not the mechanism
(see the Fast/slow and Shell accessibility rows).

Liang et al. (2021) measure the equilibrium yield of immersion brews as
`K·E_max ≈ 0.215–0.240`, insensitive to grind size (19–23%) and to temperature
over 80–99 °C, with `E_max` assumed 0.3. This supports keeping `max_EY` fixed and
letting temperature act only on rates. The model has no sorption equilibrium,
so `max_EY` acts as the total extractable fraction (`E_max`), not the immersion
equilibrium `K·E_max`; the light-roast value 0.22 matches the latter. With one
TDS reading per brew the two readings cannot be separated
(`EXP-20261007-SHELL-THICKNESS-SCAN`).

### Capillary wetting and saturation

Washburn's capillary-flow result supports a penetration scale controlled by
surface tension, viscosity, pore radius, contact angle, and time. The current
temperature scaling `tau_cap(T) ~ mu / sigma` is therefore directionally
defensible. The absolute wetting timescale is not literature-fixed because
coffee powder has irregular pores, soluble surfactants, CO2 release, and moving
bed structure.

### Thermal model

The two-node liquid/dripper ODE is a lumped heat balance. This is a standard
engineering reduction rather than a coffee-specific theorem. The stronger
literature need is for material properties: coffee-bean/powder specific heat
varies substantially with roast and moisture, so `Cp_coffee = 1800 J/(kg K)`
should remain a forward input with sensitivity tracked. The fitted thermal
parameters `U_liquid_dripper_W_m2K` and `lambda_server_ambient` should not be
treated as measured constants, although `U` now has a literature-bounded range
rather than an open one. `lambda_liquid_dripper` is deprecated.

## Adversarial Checks

This section records sources that weaken, limit, or complicate the model
narrative. Treat these as guardrails against overclaiming.

| Current claim at risk | Counter-evidence / complication | Consequence for this repo |
|---|---|---|
| SCA Golden Cup / classic Brewing Control Chart is an objective target. | Batali et al. (2020) argue the classic chart is problematic from a modern sensory-methodology perspective because it mixes quality, scale, and descriptive terms; newer UC Davis/SCA work proposes updated sensory/consumer charts. | Keep EY/TDS gates as engineering diagnostics and compatibility with industry vocabulary, not as proof of best sensory quality. |
| Brew temperature directly determines sensory quality. | Batali et al. (2020) found that, for drip coffee at fixed TDS and extraction yield, brew temperature from 87-93 C had little sensory impact. | The thermal model is still needed for extraction kinetics and cup temperature, but do not claim higher/lower brew temperature directly maps to better flavor once TDS/EY are controlled. |
| Fines are simply bad because they clog. | Smrke et al. (2024) confirm fines reduce permeability, but also report non-linear VOC behavior and no simple sensory penalty from added fines in their tested espresso. Some high-fines samples scored highly. | Split `throat/deposition` may be useful for flow, but extraction and aroma claims cannot be monotonic "more fines = worse cup." |
| Coffee-particle swelling is established enough to drive porosity closure. | Hargarten et al. (2020) report roughly 15% particle size increase, while Maille et al. (2021) found no clear evidence of swelling and warns gas/bubbles can bias wet size measurements. | `delta_phi` / wet-bed porosity changes should remain calibrated weak closure. Do not use swelling literature as settled quantitative support. |
| Darcy plus scalar permeability fully describes coffee-bed flow. | Recent espresso poroelastic work shows elasticity/porosity coupling and non-linear pressure-flow behavior under high pressure; micro-CT/percolation work emphasizes connected pore volume and angularity. | For V60, Darcy is still a defensible reduced-order baseline, but avoid transferring espresso pressure-flow conclusions or treating scalar `k` as a complete mechanistic state. |
| Measured PSD alone should predict extraction across cases. | Cross-case TDS gaps persist, and the earlier explanation (one scan under-counts fines by a fixed factor) was wrong in direction: the scan that had been designated "high-resolution" is the coarser one. Literature also shows PSD effects interact with flow, geometry, and bed structure. | The two-track "dual baseline" framing was removed. Per-case PSD is now used everywhere, and the honest statement is that the absolute scale is uncertain to ±45% and cannot resolve one grinder click; do not claim PSD-bin ingestion alone solves cross-grinder generalization. |
| A measured PSD length scale carries `k` across grind settings (e.g. `k ∝ d32²`). | Corrochano (2017 thesis): KC with `d[3,2]` overpredicts by 30–520%, growing with grind size; Wadsworth et al. (2026): XCT/LB permeability non-monotonic in grind setting; Lee & Chang (2026): fitted hydraulic diameter grows as the grind gets finer. In the four calibration brews, fitted `k` does not follow `d32²` (kinu28 has the smallest `d32` and the largest `k`), but same-setting `d32` varies by 20% between days, so this is within PSD noise. | `k` stays a per-brew fitted parameter. Do not claim PSD-predicted permeability until a grind series spanning ≥ 2× in `d32` with repeated PSD measurements tests it. |
| Two-pool extraction reproduces the double-porosity mechanism. | Moroney et al. (2015, 2019): the fast pool is a one-cell-deep broken surface layer and the kernel is slowed by intact cell walls. The model's 200 μm shell holds 69% of the extractable mass and both pools share one diffusivity. | Describe the pools as a geometric two-depth split, not as the Moroney mechanism. A closure rewrite (cell-scale shell, cell-wall hindrance, `max_EY` ≈ 0.30) is physically preferred but not distinguishable with one TDS per brew. |
| Aroma / flavor can be inferred from aggregate TDS or EY. | PTR-MS studies show VOCs have distinct time-resolved extraction patterns; Smrke et al. report VOC groups with decreasing, non-monotonic, flat, or increasing headspace signals versus extraction yield. | Current TDS/EY validation is insufficient for aroma prediction. Any "flavor" panel should be renamed extraction/strength quality unless compound or sensory data are added. |
| Flow rate does not enter the transfer coefficient at all (the Hill `flow_factor` was removed). | Schmieder et al. (2023) found flow rate had strong influence on component masses in espresso; flow, temperature, and particle size effects are compound-specific. | Flow now acts only through residence time and layer washout. That is defensible at `Re → 0`, but it is an assumption, not a result: if a flow-rate sweep at fixed PSD shows a transfer-coefficient dependence, the closure has to come back in a form that respects the Sherwood floor. |

### Current downgrades from adversarial review

- `SCA / brewing-control targets`: **Direct for vocabulary, weak for sensory
  optimum**. Keep the metric gates, but avoid calling the target box universal.
- `Arrhenius temperature factors`: **removed**. Superseded by Stokes-Einstein
  `D(T)`; keeping both counted temperature twice.
- `Measured PSD absolute scale`: **weak**. The px/mm correction fixed a
  three-order-of-magnitude error, but a ±45% absolute-scale uncertainty and a
  within-setting spread larger than the between-setting difference both remain.
- `Split fines clogging`: **Direct for permeability, weak for sensory valence**.
  Fines should be allowed to reduce flow without being framed as automatically
  bad for aroma or cup score.
- `Coffee swelling / wet-bed porosity`: **contested**. This closure needs local
  identifiability evidence more than literature authority.
- `Aroma / flavor claims`: **not validated**. Current model validates flow,
  cup temperature, TDS, and EY proxies; aroma needs time-resolved compound data.

## Weak / Needs Better Literature

These items should not be upgraded into main claims without either targeted
measurement or stronger sources:

| Item | Why weak | Suggested evidence to seek |
|---|---|---|
| `h_gas_0`, `tau_co2` as equivalent water head | Degassing is real, but pressure-head mapping in an open V60 bed is not directly sourced. | Coffee degassing kinetics after grinding, bloom gas-flow measurements, or pressure/head measurements during bloom. |
| `throat_relief_factor()` from pour impact | Plausible operator-driven bed disturbance, but no direct V60 pore-throat evidence yet. | Paired high-speed flow or weight data with controlled pour impulse. |
| `wetbed_postbloom_factor()` | Captures compaction/rearrangement/deposition, but several mechanisms are collapsed into one factor. | Repeat brews with identical PSD but different bloom agitation and pour profiles. |
| `q_bypass()` V60 rib/filter law | Bypass is plausible, but current activation law is geometric/empirical. | Dye tracing, separate bed-through versus wall-channel collection, or transparent-dripper imaging. |
| Fixed shell thickness | Fast/slow pool is supported, fixed shell depth is not. | Compound-resolved extraction curves by PSD bin or microscopy-informed cell damage depth. |
| `tau_tort` (single effective tortuosity) | Literature gives a range (roughly 2-10) for porous biological matrices, not a value for roast coffee; it is also degenerate with the assumed solute radii. | Compound-resolved release curves at two temperatures, or an independent diffusivity measurement in a wet coffee matrix. |
| `tau_wet` (retention capacity opening) | Constrained only by two endpoints of one brew's retained-mass series; no literature value. | Repeat brews with retained mass logged at 5 s resolution, across grind settings. |
| PSD absolute scale | ±45% systematic uncertainty; within-setting spread exceeds between-setting difference. | A scale-bar image in the same optical configuration as each scan, and ≥3 independent samples per grind setting. |
| Filter paper resistance and hold-up | Currently folded into `k` and into the retention residual. | Clean-water `Q(h)` through paper alone, and dry vs post-brew paper weighing. |
| Sensory quality from TDS/EY | Modern BCC studies show consumer liking and sensory attributes are not captured by a single old "ideal" box. | Consumer/sensory panel or modern sensory chart mapping. |
| Aroma prediction from extraction yield | VOC behavior can be non-linear and compound-specific. | PTR-MS/GC-MS fractions or calibrated compound pools. |

## Bibliography and Source Links

- Corrochano, B. R., Melrose, J. R., Bentley, A. C., Fryer, P. J., & Bakalis, S. (2015). "A new methodology to estimate the steady-state permeability of roast and ground coffee in packed beds." *Journal of Food Engineering*, 150, 106-116. DOI: [10.1016/j.jfoodeng.2014.11.006](https://doi.org/10.1016/j.jfoodeng.2014.11.006). Open page: <https://www.sciencedirect.com/science/article/pii/S0260877414004737>
- Moroney, K. M., Lee, W. T., O'Brien, S. B. G., Suijver, F., & Marra, J. (2015). "Modelling of coffee extraction during brewing using multiscale methods: An experimentally validated model." *Chemical Engineering Science*, 137, 216-234. DOI: [10.1016/j.ces.2015.06.003](https://doi.org/10.1016/j.ces.2015.06.003). Open page: <https://www.sciencedirect.com/science/article/abs/pii/S0009250915004108>
- Moroney, K. M., Lee, W. T., O'Brien, S. B. G., Suijver, F., & Marra, J. (2016). "Coffee extraction kinetics in a well mixed system." *Journal of Mathematics in Industry*, 7. Open page: <https://pmc.ncbi.nlm.nih.gov/articles/PMC4986356/>
- Moroney, K. M., O'Connell, K., Meikle-Janney, P., O'Brien, S. B. G., Walker, G. M., & Lee, W. T. (2019). "Analysing extraction uniformity from porous coffee beds using mathematical modelling and computational fluid dynamics approaches." *PLOS ONE*, 14(7), e0219906. DOI: [10.1371/journal.pone.0219906](https://doi.org/10.1371/journal.pone.0219906). Open page: <https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0219906>
- Cameron, M. I., Morisco, D., Hofstetter, D., Uman, E., Wilkinson, J., Kennedy, Z. C., Fontenot, S. A., Lee, W. T., Hendon, C. H., & Foster, J. M. (2020). "Systematically Improving Espresso: Insights from Mathematical Modeling and Experiment." *Matter*, 2(3), 631-648. DOI: [10.1016/j.matt.2019.12.019](https://doi.org/10.1016/j.matt.2019.12.019). Open page: <https://www.sciencedirect.com/science/article/pii/S2590238519304102>
- Batali, M. E., Ristenpart, W. D., & Guinard, J.-X. (2020). "Brew temperature, at fixed brew strength and extraction, has little impact on the sensory profile of drip brew coffee." *Scientific Reports*, 10, 16450. DOI: [10.1038/s41598-020-73341-4](https://doi.org/10.1038/s41598-020-73341-4). Open page: <https://www.nature.com/articles/s41598-020-73341-4>
- Guinard, J.-X., Frost, S., Batali, M., Cotter, A., Lim, L. X., & Ristenpart, W. D. (2023). "A new Coffee Brewing Control Chart relating sensory properties and consumer liking to brew strength, extraction yield, and brew ratio." *Journal of Food Science*. DOI: [10.1111/1750-3841.16531](https://doi.org/10.1111/1750-3841.16531). PubMed: <https://pubmed.ncbi.nlm.nih.gov/36988107/>
- Melrose, J., Roman-Corrochano, B., Montoya-Guerra, M., & Bakalis, S. (2018). "Toward a New Brewing Control Chart for the 21st Century." *Journal of Agricultural and Food Chemistry*, 66(21), 5301-5309. DOI: [10.1021/acs.jafc.7b04848](https://doi.org/10.1021/acs.jafc.7b04848). PubMed: <https://pubmed.ncbi.nlm.nih.gov/29656646/>
- Mo, C., Johnston, R., Navarini, L., Suggi Liverani, F., & Ellero, M. (2023). "Exploring the link between coffee matrix microstructure and flow properties using combined X-ray microtomography and smoothed particle hydrodynamics simulations." *Scientific Reports*, 13, 16374. DOI: [10.1038/s41598-023-42380-y](https://doi.org/10.1038/s41598-023-42380-y). Open page: <https://www.nature.com/articles/s41598-023-42380-y>
- Smrke, S., Eiermann, A., & Yeretzian, C. (2024). "The role of fines in espresso extraction dynamics." *Scientific Reports*, 14, 5612. DOI: [10.1038/s41598-024-55831-x](https://doi.org/10.1038/s41598-024-55831-x). Open page: <https://www.nature.com/articles/s41598-024-55831-x>
- Wang, X., & Lim, L.-T. (2021). "Modeling study of coffee extraction at different temperature and grind size conditions to better understand the cold and hot brewing process." *Journal of Food Process Engineering*. DOI page: <https://onlinelibrary.wiley.com/doi/10.1111/jfpe.13748>
- Schmieder, B. K. L., Pannusch, V. B., Vannieuwenhuyse, L., Briesen, H., & Minceva, M. (2023). "Influence of Flow Rate, Particle Size, and Temperature on Espresso Extraction Kinetics." *Foods*, 12(15), 2871. DOI: [10.3390/foods12152871](https://doi.org/10.3390/foods12152871). Open page: <https://www.mdpi.com/2304-8158/12/15/2871>
- Sanchez-Lopez, J. A., Wellinger, M., Gloess, A. N., Zimmermann, R., & Yeretzian, C. (2016). "Extraction kinetics of coffee aroma compounds using a semi-automatic machine: On-line analysis by PTR-ToF-MS." *International Journal of Mass Spectrometry*, 401, 22-30. DOI: [10.1016/j.ijms.2016.02.015](https://doi.org/10.1016/j.ijms.2016.02.015)
- Hargarten, V. B., Kuhn, M., & Briesen, H. (2020). "Swelling properties of roasted coffee particles." *Journal of the Science of Food and Agriculture*, 100, 3960-3971. DOI: [10.1002/jsfa.10440](https://doi.org/10.1002/jsfa.10440). PubMed: <https://pubmed.ncbi.nlm.nih.gov/32337737/>
- Maille, M. J., Sala, K., Scott, D. M., & Zukswert, H. (2021). "Critical examination of particle swelling during wetting of ground coffee." *Journal of Food Engineering*, 295, 110420. DOI: [10.1016/j.jfoodeng.2020.110420](https://doi.org/10.1016/j.jfoodeng.2020.110420). Open page: <https://www.sciencedirect.com/science/article/abs/pii/S0260877420305069>
- Waszkiewicz, R., Myck, F., Bialas, L., Puciata-Mroczynska, M., Dzikowski, M., Szymczak, P., & Lisicki, M. (2026). "Under pressure: Poroelastic regulation of flow in espresso brewing." *Physics of Fluids*, 38, 063113. DOI: [10.1063/5.0319611](https://doi.org/10.1063/5.0319611). Open page: <https://pubs.aip.org/aip/pof/article/38/6/063113/3396119/Under-pressure-Poroelastic-regulation-of-flow-in>
- Lee, H. S., & Chang, B.-Y. (2026). "Coffee brewing trajectories from recipe-level records: a conservation-constrained framework for filter coffee." *npj Science of Food*. DOI: [10.1038/s41538-026-01074-1](https://doi.org/10.1038/s41538-026-01074-1). Code: <https://github.com/Byoung-Yong/FilterCoffee>
- Wadsworth, F. B., Vasseur, J., Zhang, J., Dobson, K. J., et al. (2026). "A model for the permeability of coffee pucks validated using X-ray computed micro-tomography." *Royal Society Open Science*. DOI: [10.1098/rsos.252031](https://doi.org/10.1098/rsos.252031)
- Roman Corrochano, B. (2017). *Advancing the engineering understanding of coffee extraction*. EngD thesis, University of Birmingham. <https://etheses.bham.ac.uk/id/eprint/7176/>
- Liang, J., Chan, K. C., & Ristenpart, W. D. (2021). "An equilibrium desorption model for the strength and extraction yield of full immersion brewed coffee." *Scientific Reports*, 11, 6904. DOI: [10.1038/s41598-021-85787-1](https://doi.org/10.1038/s41598-021-85787-1)
- Foster, J. M., Lee, W. T., Moroney, K. M., et al. (2025). "Dynamics of liquid infiltration into an espresso bed using time-resolved micro-computed tomography: Insights from experiment and modeling." *Physics of Fluids*, 37, 013383. DOI: [10.1063/5.0245167](https://doi.org/10.1063/5.0245167)
- Crank, J. (1975). *The Mathematics of Diffusion* (2nd ed.), Oxford University Press. Chapter 6 gives the series solution for diffusion out of a sphere whose leading term is the current slow-pool release law.
- Washburn, E. W. (1921). "The dynamics of capillary flow." *Physical Review*, 17, 273-283. PDF: <https://kinampark.com/PL/files/Washburn%201921%2C%20The%20dynamixs%20of%20capillary%20flow.pdf>
- Brooks, R. H., & Corey, A. T. (1964). "Hydraulic properties of porous media." Colorado State University Hydrology Paper. PDF: <https://mountainscholar.org/bitstreams/85503e6d-f86c-4423-92d7-9b9d1f894d7e/download>
- Singh, C. B., & Singh, K. K. (1996). "Thermophysical properties of fresh and roasted coffee powders." Summary page: <https://www.semanticscholar.org/paper/THERMOPHYSICAL-PROPERTIES-OF-FRESH-AND-ROASTED-Singh-Singh/df68342551fa820f5e22ca71189524c97ce2e768>
- Specialty Coffee Association / Coffee Science Foundation brewing fundamentals research hub: <https://sca.coffee/brewing-research>

## Maintenance Notes

1. Keep `README.md` as a short pointer to this file; avoid duplicating the full
   bibliography in the project entry point.
2. Add a small `docs/literature_todo.md` only if the weak items become active
   modeling work. For now, this file is enough.
3. Before changing any closure, update the relevant row here from "proxy" to a
   stronger status only when the supporting source or experiment is explicit.
