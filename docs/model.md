# Model and assumptions

[Project overview](../README.md) · [Reproducibility and calibration](reproducibility.md) · [Literature map](literature_map.md)

The model uses coupled ODEs to describe water, solute, and energy balances during V60 brewing. This page documents the current mechanisms, data contract, and limitations. Calibration values and experimental evidence are defined by the [experiment log's `[BASELINE]`](experiment_log.md#baseline-current) and its linked artifacts.

## Hydraulics and water retention

Water is partitioned into ponded free water, drainable pore water, capillary-held pore water, and water absorbed by the grains. Fluxes transfer mass between these pools, with outflow and bypass included in the overall balance. The reference summary reports a water balance residual of about `3.2e-13 mL`. This is a numerical conservation diagnostic; it does not establish agreement with measurements.

| Mechanism | Physical description | Parameter role |
|---|---|---|
| Grain absorption | Lucas–Washburn `γ(T)/μ(T)` scaling describes the temperature effect on uptake rate | Capacity fixed by roast |
| Bed wetting | State `w` progressively opens absorption and capillary retention capacity | `τ_wet` calibrated; not a direct bloom-wetting time |
| Capillary retention | Young–Laplace head `2σ(T)/(ρ g r_pore)`, with `r_pore = 0.2·d32`, sets the retention scale | PSD and a fixed geometric ratio |
| Through-bed flow | Darcy flow driven by ponded head and saturated bed height, limited by a separate capillary cutoff and decaying equivalent CO₂ back-pressure | Permeability `k` calibrated |
| Unsaturated flow | Relative permeability `kr = (3S² − 2S³)^n` on drainable saturation `S` | Corey-type exponent `n` calibrated; not the same exponent as in soil formulations |
| Fines clogging | Separate number-weighted throat and volume-weighted deposition clogging; pours briefly relieve throat resistance | Strength computed from measured PSD and fixed |
| Porosity change | Swelling and head compaction modify permeability through a Kozeny–Carman-type correction | Porosity trend, not an absolute permeability prediction |
| Bypass and outlet | Filter-rib bypass and dripping delay from the outlet to the server | Bypass closure fixed; outlet delay `0.5 s` |

Capillary retention capacity and the outflow cutoff are distinct closures. The retention head is not added as extra through-bed driving head. Explicit water pools carry residual retention, so `sat_rel_perm_residual = 0`. Permeability `k` is calibrated per case and cannot be inferred from PSD alone.

## Extraction

Each measured particle-size bin has its own mass, surface area, shell depth, and core size. The shell represents cells broken by grinding and exposed to pore liquid: the fast pool. The core represents solute behind intact cell walls: the slow pool. Spherical geometry determines the shell mass fraction, and two stacked mixing layers transport solute through the bed to the outlet.

### Release laws

For bin `i`, `R_i` is the particle radius, `δ_i = min(shell_thickness, R_i)`, and `R_core,i = R_i − δ_i`. The characteristic first-order release rates are:

```text
λ_fast,i = π² D_fast(T) / (2δ_i)²
λ_slow,i = π² D_slow(T) / (τ_tort R_core,i²)
D(T)     = k_B T / (6π μ(T) r)
```

The fast pool uses the leading eigenvalue of a slab open on the outer face and sealed on the inner face. The slow pool uses the first term of Crank's spherical diffusion solution. Particles without a core receive no slow-pool mass. `τ_tort` acts only on the slow pool, representing effective hindrance from intact cell walls and internal structure.

Stokes–Einstein supplies the only transport temperature dependence of the release rates; no additional Arrhenius factor is applied. Release slows as the liquid approaches `C_sat(T)`; temperature dependence of solubility is represented separately by that ceiling.

The extractable fraction `max_EY` is fixed by roast and is not fitted. There is no sorption equilibrium, so all designated extractable mass can be released given sufficient time. One final TDS observation per case cannot jointly identify `τ_tort`, shell thickness, solute hydrodynamic radius, and extractable fraction.

### Particle-size distribution

Measured PSD is loaded preferentially through `psd_bins_csv_path`. Raw exports come from the [coffeegrindsize fork](https://github.com/latteine1217/coffeegrindsize). Conversion is implemented in [psd.py](../pour_over/psd.py); the model's loading contract is `REQUIRED_PSD_BIN_COLUMNS` in [params.py](../pour_over/params.py).

**Raw export contract:** `PIXEL_SCALE` is in **px/mm** and must be a unique positive value. Missing, inconsistent, or non-positive scales raise an error. `SHORT_AXIS` and `LONG_AXIS` are semiaxes in pixels; `SURFACE` is area in square pixels. The area-equivalent full diameter is `2·sqrt(SHORT_AXIS·LONG_AXIS)/PIXEL_SCALE`. Volume is recomputed using an equivalent sphere; the export's pseudo-3D `VOLUME` is not used.

| Bin fields | Definition and use |
|---|---|
| `d_lo_mm`, `d_hi_mm`, `d_mid_mm` | Bin bounds and midpoint, in mm |
| `num_fraction`, `volume_fraction` | Number and equivalent-sphere volume fractions for throat and deposition clogging |
| `diameter_eq_mean_mm`, `diameter_eq_median_mm` | Mean and median area-equivalent diameter within a bin |
| `aspect_ratio_mean` | Long-to-short axis ratio used as a shape proxy |
| `surface_to_volume_mm_inv_mean` | Number-averaged `6/d` within a bin, in mm⁻¹ |
| `surface_to_volume_mm_inv_vol_weighted` | Volume-weighted `6/d` for specific surface area and `d32` |
| `shell_accessibility_*` | Exported shell fractions; recomputed analytically from scaled diameters when loaded |
| `censored` | Flags bins whose lower edge falls below the image detection limit; this does not mean fines are absent |

Fields in the first six rows are required by the loader; the last two rows describe export and diagnostic information. The model's size anchor is the Sauter diameter `d32`, satisfying `Σ(volume_fraction · S/V) = 6/d32`. Resolution-limited `D10_measured_m` is diagnostic only and does not rescale the PSD. Grind sweeps use explicit `psd_diameter_scale`.

Changes to field names or definitions must be synchronized with the [PSD converter](../pour_over/psd.py), [model parameters](../pour_over/params.py), and [PSD invariant tests](../tests/test_psd_invariants.py).

## Heat balance

- **Slurry:** Energy balance for incoming hot water and coffee solids, including heat loss to ambient.
- **Dripper:** Heat capacity from equipment mass and specific heat, exchanging energy with the slurry through `U·A_wet`.
- **Server:** Mixing of incoming coffee and cooling to ambient; liquid level and probe conditions determine which observations enter the fit.

Video cases with an accepted server temperature series fit `U_liquid_dripper_W_m2K` while fixing the server cooling rate. Cases with only one cup temperature fix `U = 194 W/(m²K)` and fit server cooling instead. Heat capacities are not free parameters for absorbing errors elsewhere. Server equivalent heat capacity is back-estimated rather than directly measured.

## Fixed assumptions and numerical methods

| Assumption | Current value | Role |
|---|---|---|
| Fast / slow `C_sat` | 220 / 60–100 g/L, depending on roast | Dissolved concentration ceiling |
| Fast / slow solute hydrodynamic radius | 0.40 / 1.00 nm | Stokes–Einstein diffusivity |
| Broken-shell thickness | 30 μm | Fast path length and fast/slow mass partition |
| Retention pore-radius ratio | `r_pore = 0.2·d32` | Capillary retention |
| Initial equivalent CO₂ back-pressure | Light / medium / dark: 9 / 1 / 4 mm; decay time 35 s | Bloom outflow closure, not a direct gas measurement |
| Bypass onset / width | 3 / 8 mm of ponded head | Filter-rib bypass closure |
| `max_EY` | Light / medium / dark: 0.30 / 0.30 / 0.32 | Total extractable mass |
| Solute transport layers | 2 | Axial mixing resolution |
| Server cooling rate with accepted temperature series | `3.7e-4 s⁻¹` | Physical estimate from convection and radiation |

The ODE system uses RK45 with `rtol=1e-7` and `atol=1e-9`, integrated piecewise between changes in pour rate. Fitting and identifiability analysis must not use looser tolerances. Summary floats retain exact round-trip representations. Water and energy residuals, clipping activity, and measurement residuals are checked separately.

## Model applicability

Detailed evidence and sources for these limitations are in the [current baseline](experiment_log.md#baseline-current):

- **Calibration and generalization:** Direct observations constrain outflow and temperature, but new pour schedules or water temperatures have not been independently validated. Separately fitted cases do not provide cross-case prediction errors.
- **TDS transferability:** `τ_tort` spans 3.3–7.4 across video cases without a monotonic grind trend. Transfer between two days with the same beans and grind gives TDS errors of about −1.6 / +1.8 g/L; cross-case errors reach about 2.7 g/L. PSD noise, bean aging, and TDS measurement error remain confounded.
- **PSD uncertainty:** Absolute scale retains about ±45% systematic uncertainty; `d32` differs by about 20% between same-setting scans on different days. Replacing the reference PSD with the other day's scan changes fitted `τ_tort` by about 1.5 times, comparable to its spread across cases.
- **Grind sweeps:** Scaling simulated particle sizes does not reproduce fines clogging at a genuinely new grind. New settings require new PSD measurements. A shared `k` and `n` across the three video cases is not rejected by the available data, indicating limited power rather than evidence of equal permeability.
- **Second-pour restart:** Model outflow arrives about 2–4 s early after the bloom, with approximately correct total volume. Low χ² does not resolve this timing discrepancy.
- **Wetting parameter:** Later pours and drainage primarily constrain `τ_wet`. The reference estimate lies at the `10 s` lower bound, with a conditional upper limit of about `16.1 s`; it is not a directly identified wetting time.
- **Early heat coupling:** Dry-glass heat coupling is insufficiently represented below about 150 mL in the server, so those readings are excluded. The Kinu 27 video case also has a probe that does not represent the mixed mean and falls back to a single cup temperature.
- **Observation operators:** The outlet thermocouple's apparent flow break is close to dripper removal and is diagnostic only. Final beverage volume comes from the last `use_for_fit` reading before removal.
- **Uncertainty:** Confidence intervals are conditional slices with other parameters fixed. Joint uncertainty analysis gives hydraulic marginal standard deviations about 1.5–2.4 times their conditional values; multipliers for thermal parameters and `τ_tort` are below 1.3.
- **Hardware not directly measured:** Outlet diameter, paper resistance, paper water hold-up, and server equivalent heat capacity still contain assumptions or back-estimated values.

The [literature map](literature_map.md) distinguishes direct evidence, analogy, and engineering proxies for each closure.
