# V60 Pour-Over Physics Simulation

A reduced-order physical model of V60 pour-over brewing, fitted to measured
brews. Bed hydraulics, bin-resolved solute extraction and a multi-node heat
balance are solved as one coupled ODE system. Every mechanism is written as a
physical closure with a stated meaning; the few free parameters are fitted
against time series read from brew videos, a measured particle-size
distribution (PSD), temperatures and TDS.

![Measured vs fitted outflow, canonical brew](data/kinu_29_light/4:12/kinu29_light_20g_flow_fit.png)

*Canonical brew (Kinu 29, light roast, 20 g, 5.3 cm bed): measured poured and
drained volume read frame by frame from the brew video, against the fitted
model. Bottom panel: residuals with the per-point measurement band.*

## Scope

The model is a bed-scale porous-media simulator. It represents:

- the water pathway from the kettle through the grounds and filter into the
  server, including absorption by the grains, capillary retention in the bed,
  and bypass along the filter ribs;
- solute release from each PSD size bin, split into a fast outer-shell pool
  and a slow intact-core pool;
- the heat balance of the slurry, the ceramic dripper and the server.

It is **not** a CFD or multiphase PDE solver, and it is not a black-box
regressor: a parameter enters the fit only when the data can identify it and
it has a physical meaning.

## Quick start

```bash
uv sync
uv run python -m unittest discover -s tests      # test suite
uv run python -m pour_over                       # showcase figures (v60_*.png), then a full refit of the canonical brew (hours)
uv run python -m pour_over benchmark             # fit + benchmark gates + identifiability (hours)
```

```python
from pour_over import V60Params, RoastProfile, PourProtocol, simulate_brew

params = V60Params.for_roast(RoastProfile.LIGHT)
results = simulate_brew(params, PourProtocol.standard_v60(), t_end=180)
print(f"TDS = {results['TDS_gl'][-1]:.1f} g/L, EY = {results['EY_pct'][-1]:.1f}%")
```

A run on measured PSD bins sets `psd_bins_csv_path` (for example
`data/kinu_29_light/4:12/kinu29_psd_bins.csv`) together with the measured bed
height, ambient temperature and dripper mass.

## Physical mechanisms

### State and conservation

```
state = [V_free, V_mob, V_imm, V_abs, w, V_out, V_bed, V_poured,
         {C_fast,i, M_fast,i, C_slow,i, M_slow,i} per layer and PSD bin,
         T, T_dripper, xi_pref]
```

Water is held in four explicit pools: free water ponded above the bed
(`V_free`), gravity-drainable pore water (`V_mob`), capillary-held pore water
(`V_imm`) and water absorbed into the grains (`V_abs`). Every rate moves water
from one pool to another, so the inventory

```
V_poured ≡ V_out + V_abs + V_imm + V_mob + V_free
```

holds as an algebraic identity. Each pool's withdrawal rate is bounded by its
content over a transfer time, which keeps the pools non-negative without
clamps. The residual of this identity is reported with every run
(`water_balance_residual_ml`, ~1e-13 mL on the fitted brews).

### Water pathway

| Mechanism | Physics in the model | Parameters |
|---|---|---|
| Absorption into grains | Rate `(V_full·w − V_abs)/τ_cap(T)`, limited by the water available. `τ_cap(T)` follows Lucas-Washburn scaling `γ(T)/μ(T)` | absorption capacities per gram (roast profile) |
| Bed wetting | A wetting state `w ∈ [0, 1]` grows as `dw/dt = (1 − w)/τ_wet`, gated by liquid actually being present. `w` opens both the absorption capacity and the capillary retention capacity | `τ_wet` (fitted) |
| Capillary retention | Young-Laplace head `h_cap_bed = 2σ(T)/(ρ g r_pore)` with `r_pore = 0.2·d32` from the measured PSD. The retainable fraction of the bed `f_retain = min(h_cap_bed/h_bed, 1)` sets the immobile capacity `φ·V_bed·f_retain·w`; mobile water is captured into it on `τ_cap(T)` | from PSD (not fitted) |
| Darcy flow through the bed | `Q = kr(S_mob) · (ρg/μ(T)) · k_eff · A_ref · h_eff / h_bed`. The driving head is the ponded column plus the mobile-saturated bed height, `h_free + S_mob·h_bed`, minus a low-level capillary cutoff and a CO₂ back-pressure `h_gas(t) = h_gas,0·exp(−t/τ_CO₂)`, softplus-smoothed | `k` (fitted) |
| Unsaturated flow | Corey relative permeability `kr = smoothstep(S_mob)^n` on the **mobile** saturation; residual saturation is carried explicitly by `V_imm`, so there is no separate residual-saturation constant | Corey `n` (fitted) |
| Permeability evolution | `k_eff = k / R_total × Kozeny-Carman(φ_eff)`. `R_total` adds the incremental resistance of fines clogging the pore throats (number-weighted fines), fines depositing in the bed (volume-weighted fines) and post-bloom bed rearrangement; each pour's impact briefly relieves the throats. `φ_eff` falls as grains swell and as the ponded head compacts the bed | clogging strength `k_beta` computed from the measured PSD |
| Bypass | Flow along the filter ribs, near zero at low ponded head and opening smoothly above ~3 mm; it decays as fines deposit on the paper and scales with `1/μ(T)` | fixed |
| Supply-limited outflow | The Darcy capacity is capped by the water the pools can actually deliver, so outflow ends when the pools empty, without an imposed cutoff | — |
| Outlet to server | A first-order hold-up with time constant `τ_lag` (drip and spreading at the outlet) turns bed outflow into the flow that reaches the server | `τ_lag = 0.5 s` (fixed, geometric) |

An optional preferential-flow channel (`xi_pref`) exists in the code; it is
accepted only when it lowers the hydraulic χ² by at least 1, and it is off in
all current fits.

### Solute extraction

- **PSD bins.** The measured PSD (image analysis, absolute scale from the
  export's px/mm column, anchored on the Sauter diameter `d32`) is kept as
  individual size bins. Each bin carries its volume fraction, surface-to-volume
  ratio and aspect ratio.
- **Two pools per bin.** A broken outer shell of thickness `δ` holds the fast
  pool, and the intact core holds the slow pool. The split follows each bin's
  outer-shell accessibility, and the total soluble mass is `dose × max_EY` for
  the roast.
- **Release laws.** Both pools release by first-order diffusion, the long-time
  limit of Crank's spherical-diffusion solution:
  - fast pool (shell sealed on its inner face): `λ_fast,i = π²·D_eff/(2δ)²`;
  - slow pool (core sphere of radius `R_core,i`): `λ_slow,i = π²·D_eff/R_core,i²`.

  Release is multiplied by the wetting state `w` and by the undersaturation
  `1 − C/C_sat(T)`.
- **Temperature dependence.** `D_eff = k_B T / (6π μ(T) r) / τ_tort` (Stokes-Einstein
  over a tortuosity). This is the only temperature dependence of the release
  rate constants; no separate Arrhenius factor is added. The solubility
  ceilings `C_sat(T)` rise linearly with temperature.
- **Transport.** Solute is carried through two axial layers of the bed in
  series (well-mixed within each layer), written in conservative form so that
  filling or draining the pores dilutes or concentrates the pore liquid
  correctly.

The only fitted extraction parameter is `τ_tort`. It has a physical lower
bound of 1, and its upper bound (100) is deliberately beyond the physical
range, so that a fit pushed to the bound shows up as a failure.

### Heat

- **Slurry node.** It includes the pore, free and absorbed water plus the
  coffee's water-equivalent heat capacity. Poured water brings enthalpy at
  `T_brew`, including the water that is absorbed by the grains. The node loses
  heat to ambient by Newton cooling.
- **Dripper node.** Heat capacity comes from the measured dripper mass and
  specific heat. It exchanges heat with the slurry as `U · A_wet(h) · (T − T_dripper)`,
  where `A_wet` is the wetted cone area at the current liquid height and `U` is
  an interface heat-transfer coefficient with a physical range of
  120–550 W/(m²K). The dripper also loses heat to ambient.
- **Server.** It mixes incoming liquid with a vessel water-equivalent of
  42.4 mL and cools to ambient at rate `λ_server`.
- **Couplings.** Temperature feeds back into flow through the water viscosity
  `μ(T)`, and into extraction through `D(T)` and `C_sat(T)`.

### Numerics

The system is integrated with RK45 at `rtol 1e-7`, restarted at every
breakpoint of the piecewise-constant pour rate. Integrating across those jumps
leaves χ² with numerical path noise of order 0.1; restarting at them brings it
to ~1e-8, which makes the fits and the identifiability scans reproducible.

## Fitting the model to a brew

### What is measured

| Quantity | How it is measured | Role in the model |
|---|---|---|
| Dose, bed height, brew and ambient temperature, dripper mass | Direct measurement | Fixed inputs |
| Particle-size distribution | Image analysis of the grounds with [coffeegrindsize](https://github.com/latteine1217/coffeegrindsize), one export per brew | Fixed input (PSD bins, `d32`, fines fractions, clogging strength `k_beta`) |
| Poured volume `V_in(t)` | Scale under the server, read frame by frame from the brew video (1 s grid) | Fixed input (pour schedule) |
| Drained volume `V_out(t)` | Liquid level on the server's printed graduations, read frame by frame from the video | Fit target |
| Stop time | Same liquid-level readings, through one stop-time rule applied identically to model and measurement | Fit target |
| Server temperature `T(t)` | Thermocouple display in the video | Fit target (heat) |
| Outlet temperature | Second thermocouple channel in the video | Out-of-sample check |
| Final TDS | Refractometer | Fit target (extraction) |

**Particle-size distribution.** Each brew's grounds are photographed on a
white background and segmented with
[coffeegrindsize](https://github.com/latteine1217/coffeegrindsize). Its
per-particle export (`data/<case>/PSD_export_data.csv`) is read by
`pour_over/psd.py`:

- `PIXEL_SCALE` is in px/mm, set from a reference length in the photo, and
  is the only source of absolute scale;
- `LONG_AXIS` and `SHORT_AXIS` are half-axes in pixels, with
  π · `SHORT_AXIS` · `LONG_AXIS` = `SURFACE`, so the equal-area diameter is
  2·√(`SHORT_AXIS` · `LONG_AXIS`) / `PIXEL_SCALE`;
- the export's `VOLUME` column is a pseudo-3D estimate and is not used.

A change to the export format in coffeegrindsize requires the matching change
in `psd.py` and in `tests/test_psd_invariants.py`.

**Video readout.** Frames are extracted at 1 fps and their timestamps are
checked against the raw stream. The scale's built-in timer runs 1.86% fast
relative to real time; the rate is fitted from every timer rollover in three
independent videos, and hand-logged times are rescaled by it. The liquid
level is converted to volume with a piecewise-linear calibration against the
printed graduation marks. Each reading carries a per-point σ:

- 4 mL for a clean read;
- 6 mL for a visually overridden or interpolated read;
- 15 mL below the lowest graduation (50 mL) or when the level is occluded.

Readings taken after the dripper is lifted off the server are excluded. The
full pipeline is in `tools/video/README.md`; per-frame readouts are kept under
`data/<case>/video/`.

A brew without video falls back to its hand-logged drained-volume column.
Against video this column reads 13–73 mL high after the bloom, so such cases
are flagged `drained_log_bias_suspected` and are not used as the reference.

**Preprocessing.** Raw CSVs are never edited. Corrections are applied in
memory and written to each fit summary's `preprocess_corrections` column:

- a physical cap on the pour rate (1.1 × the brew's own largest other interval
  rate);
- monotone cumulative readings;
- propagation of reading-time uncertainty into σ.

### Objective

The loss is a σ-normalised χ² over the measured targets, plus weak log-space
priors:

| Term | σ | Basis |
|---|---|---|
| `V_out(t)`, every 5 s | 4 / 6 / 15 mL per point (video) | level readout quality |
| stop time | 2.5 s | liquid-level settling |
| server temperature series | 1.0 °C | display readout, probe placement |
| cup temperature (only when no series exists) | 0.5 °C | probe accuracy and placement |
| extracted solute mass | from TDS σ 0.72 g/L | refractometer and conversion factor |

TDS is compared as dissolved mass, with the **measured** final volume as the
denominator, so that hydraulic error cannot be absorbed by the extraction
parameter.

The priors are Corey `n` (centre 3.0, 0.20 dex), `U` (centre 194 W/(m²K),
0.20 dex) and `τ_tort` (centre 5, 0.35 dex).

### Staged fit

The three physics blocks are fitted in order, so that no block absorbs
another's error:

1. **Hydraulics** (`k`, Corey `n`, `τ_wet`) minimise the hydraulic χ² only:
   volume, stop time and priors.
2. **Heat** fits one thermal degree of freedom:
   - brews with a server-temperature series fit `U`, and `λ_server` is fixed
     at a physical estimate of `3.7e-4 s⁻¹`;
   - brews with a single cup temperature fit `λ_server`, and `U` is fixed at
     194 W/(m²K).

   A time series supports only one of the two, because they trade off along a
   ridge.
3. **Extraction** (`τ_tort`) is fitted against TDS, and only when the model's
   final volume is within 5% of the measured one.

Each stage is accepted only if it lowers χ² by at least 1. Each fit uses 7
starting points (a Latin hypercube plus a warm start), and every reported
parameter comes with a 95% conditional-slice interval.

### Parameter classes

| Class | Parameters | Treatment |
|---|---|---|
| Measured | dose, bed height, temperatures, `V_in(t)`, dripper mass and material, PSD bins | fixed |
| Derived from measurement | `d32`, fines fractions, `r_pore`, clogging strength `k_beta`, dripper and vessel heat capacities | computed, then fixed |
| Fitted | `k`, Corey `n`, `τ_wet`, `U` or `λ_server`, `τ_tort` | fitted with CI |
| Fixed assumptions | see below | not fitted, disclosed |

Fixed assumptions (present in the model, not fitted, not independently
measured):

| Parameter | Value | Note |
|---|---|---|
| `C_sat_fast` / `C_sat_slow` | 220 / 60–100 g/L by roast | solubility ceilings; the fast pool is kinetics-limited in practice |
| Solute radii (Stokes-Einstein) | 0.40 / 1.00 nm | degenerate with `τ_tort` |
| `shell_thickness` | 200 μm | sets the fast diffusion length and the fast/slow split |
| `pore_radius_ratio` | 0.2 | `r_pore = 0.2·d32` |
| `h_gas,0`, `τ_CO₂` | 1 mm, 35 s | CO₂ back-pressure as an equivalent head |
| bypass onset head / width | 3 mm / 8 mm | bypass activation |
| `max_EY` | 0.22 / 0.30 / 0.32 (light / medium / dark) | never fitted |
| axial layers | 2 | reduced-order substitute for an axial PDE |
| `λ_server` on series brews | 3.7e-4 s⁻¹ | wall convection, radiation and evaporation estimate |

## Results

Canonical brew `kinu29/4:12` (summary:
`data/kinu_29_light/4:12/kinu29_light_20g_flow_fit_summary.csv`):

| Parameter | Value | 95% CI (conditional slice) |
|---|---|---|
| `k` | 6.46e-11 m² | [6.36e-11, 6.75e-11] |
| Corey `n` | 3.14 | [2.13, 4.25] |
| `τ_wet` | 10.0 s (at lower bound) | [—, 16.3] |
| `U` | 258 W/(m²K) | [184, 362] |
| `τ_tort` | 7.47 | — |
| `k_beta` | 2515 (from PSD) | fixed |

| Fit quality | Value |
|---|---|
| reduced χ² (dof / N) | 0.358 (26 / 31) |
| Durbin-Watson / lag-1 on `r/σ` | 1.34 / 0.33 |
| `V_out` RMSE | 2.6 mL |
| stop-time error | +0.20 s |
| server temperature series RMSE | 0.92 °C |
| TDS error | +0.11 g/L (measured 11.56 g/L) |
| water balance residual / energy residual | 4e-13 mL / 2.7e-6 |

Four-brew benchmark (`data/benchmark_suite_summary.csv`):

| Brew | Source | reduced χ² | DW / lag-1 (`r/σ`) | TDS error | Status |
|---|---|---|---|---|---|
| `kinu29/4:12` (canonical) | video | 0.358 | 1.34 / 0.33 | +0.11 g/L | PASS |
| `kinu27/4:12` | video | 0.364 | 0.91 / 0.52 | +0.14 g/L | FAIL (residual whiteness) |
| `kinu28/4:20` | video | 0.500 | 1.36 / 0.31 | +0.03 g/L | PASS |
| `kinu29/4:11` | hand log | 8.38 | 0.30 / 0.85 | +0.10 g/L | FAIL (log-record bias) |

**Gates:**

- reduced χ² ≤ 3;
- residual whiteness on `r/σ`: DW ≥ 1.0 or lag-1 ≤ 0.5;
- retained water within 15%;
- cup temperature within 1 °C;
- server series RMSE ≤ 2 °C;
- TDS within 1.44 g/L;
- water residual ≤ 0.05 mL;
- temperature clipping ≤ 1% of steps.

Fitted permeabilities fall in a narrow band across the three video brews
(`k` 6.5–7.7e-11 m²).

These are **calibration residuals** on the brew each parameter set was fitted
to, not prediction accuracy.

## Known limitations

- **Second-pour restart.** When a pour restarts an outflow that had stopped
  (after the bloom), the modelled outflow pulse arrives 2–4 s before the
  measured one, with the pulse volume conserved (about +7 mL at its peak on
  the canonical brew). Later pours, which start while outflow is still
  running, show no lead. The level conversion, foam and scale lag have been
  ruled out; the physical mechanism is not yet identified.
- **`τ_wet` is not a clean wetting time.** Across brews it is fitted at
  10 / 16 / 42 s, and it is set mainly by the later pours and the drawdown
  rather than by the bloom. It currently acts as a shape parameter for how
  retention capacity grows during the brew. On the canonical brew it sits at
  its 10 s lower bound: removing the bound would gain only Δχ² 0.44, and that
  gain comes from the second-pour window above.
- **Residuals are not white on an unweighted scale.** The whiteness gate is
  computed on `r/σ`. On unweighted mL residuals, lag-1 is 0.55–0.57 on all
  three video brews.
- **Early server heat capacity.** Below 150 mL the server's effective heat
  capacity measures 22–37 mL of water instead of 42.4 mL. Series points below
  150 mL are excluded from χ² until the dry-wall heat uptake is measured.
- **Per-brew measurement issues.**
  - `kinu27/4:12`: the server probe reads a stratified layer, so that brew
    uses its single cup temperature instead of the series.
  - `kinu28/4:20`: the upper CI of `U` (585) extends past the physical range.
  - `kinu29/4:11`: this brew has no video and its logged drained volume reads
    ahead of the true level.
- **Level readout.** The graduation-column estimator can lock onto a printed
  graduation line for 1–4 s; this adds a few mL of local error near the
  50 mL mark.
- **Unmeasured inputs.** These are disclosed rather than fitted:
  - outlet inner diameter;
  - clean-water resistance of the filter paper;
  - dry vs post-brew paper hold-up;
  - server mass (the 42.4 mL vessel equivalent is back-solved);
  - an absolute PSD scale target (±45% systematic uncertainty).

  With one PSD sample per grind setting, the PSD cannot resolve a single
  grinder click.
- **Grind sweeps.** Changing grind size rescales `k` through Kozeny-Carman,
  but the clogging indices are diameter ratios and do not change with it.
- **Confidence intervals** are conditional slices (other parameters frozen),
  so they are lower bounds on the true uncertainty.

## Repository layout

```
pour_over/
├── core.py            # coupled ODE engine (simulate_brew)
├── params.py          # closures, V60Params, RoastProfile, PourProtocol
├── constant.py        # physical constants and measured fixed inputs
├── psd.py             # PSD ingestion (raw export → model bins)
├── measured_io.py     # measured CSV loading, measurement constants
├── preprocess.py      # in-memory measurement corrections
├── observation.py     # outlet hold-up, server node, stop-time rule
├── fitting.py         # χ² objective and staged fit
├── benchmark.py       # four-brew benchmark and gates
├── identifiability.py # local identifiability scans and CI
├── analysis.py        # sensitivity and grind optimisation
├── showcase_state.py  # loads the current calibrated state
└── viz.py             # figures
tools/video/           # brew-video readout pipeline
data/<grinder>_light/<recipe>/   # per-brew measurements, PSD, fit outputs
docs/                  # literature map, audit, experiment log
```

- **Per-brew data.** `data/<case>/` holds the flow and thermal profiles
  (`*_flow_profile_video.csv` is the default when present), the raw PSD
  export and its model-ready `*_psd_bins.csv`, and the fit outputs
  (`*_flow_fit_summary.csv` and figures).
- **PSD artifacts.** They are regenerated from the raw export with
  `uv run python -m pour_over.psd` (see its `--help`).
- **Media.** Raw videos and photos are not version-controlled.

## References

The closure-by-closure literature map, with support level and open questions,
is in `docs/literature_map.md`. Core sources:

- Corrochano et al. (2015), *Journal of Food Engineering* — coffee packed-bed
  permeability and Kozeny-Carman limits. DOI `10.1016/j.jfoodeng.2014.11.006`
- Moroney et al. (2015), *Chemical Engineering Science* — double-porosity coffee
  extraction with fast surface release and slow intragranular diffusion.
  DOI `10.1016/j.ces.2015.06.003`
- Moroney et al. (2019), *PLOS ONE* — extraction uniformity in porous coffee beds.
  DOI `10.1371/journal.pone.0219906`
- Cameron et al. (2020), *Matter* — PSD, inhomogeneous flow and extraction
  reproducibility. DOI `10.1016/j.matt.2019.12.019`
- Crank (1975), *The Mathematics of Diffusion* — spherical-grain diffusion
- Brooks & Corey (1964) — relative permeability of unsaturated porous media
- Washburn (1921), *Physical Review* — capillary imbibition scaling

The development history, including every model change, rejected mechanism and
refit, is recorded in `docs/experiment_log.md`.

## License

MIT — see `LICENSE`.
