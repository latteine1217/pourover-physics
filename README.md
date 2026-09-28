# V60 Pour-Over Physics Simulation

A physics-based numerical simulation of V60 pour-over coffee brewing, modelling bed hydraulics, bin-resolved extraction kinetics, and thermodynamics as one coupled ODE system.

> **Status (2026-09-24, updated 2026-09-28): model revision landed, pour-over video measurement integrated, canonical `kinu29/4:12` passes the benchmark; `kinu27/4:12` fails residual whiteness only; `kinu29/4:11` (no video, log record) still fails reduced χ² and whiteness.**
> The September 2026 audit (`docs/audit_2026-09-24.md`) found structural errors
> in the water inventory, the liquid-node enthalpy balance, the extraction
> closure, and the objective function. Those closures were rewritten, and the
> canonical case (and three additional measured cases) were fit against the
> new objective. **2026-09-27**: three of the four cases turned out to have a
> pour-over video (`tools/video/README.md`); frame-by-frame readout showed the
> hand-logged `drained_volume_ml` column runs systematically **13–73 mL** high
> after the bloom — a measurement artifact, not a hydraulic mechanism.
> Refitting against the video liquid level drops reduced χ² from
> `20.1 / 43.4 / 21.9` to `0.63 / 0.57 / 0.31` with **no equation, closure, or
> live parameter changed** (`Video-derived measurements` below).
> **2026-09-27/28 follow-up (F11–F12c)**, again with no model equation changed:
> the video's server-temperature time series now enters χ² (and `U_liquid_dripper`
> is fitted on video cases while `lambda_server_ambient` is frozen at a physical
> estimate); the stop time is compared through one shared liquid-level operator
> on both sides; readings after the dripper is lifted off the server are excluded;
> the whiteness gate is computed on standardized residuals `r/σ`; and two
> fitting-procedure bugs were fixed (the final-cup reading was taken after the
> dripper was removed, and the hydraulic stages minimized the total χ²,
> including thermal terms not yet fitted). After a full refit of the three video
> cases: `kinu29/4:12` (canonical) and `kinu28/4:20` **PASS** every gate
> (reduced χ² `0.36 / 0.50`); `kinu27/4:12` fails only residual whiteness
> (lag-1 `0.503` on `r/σ`, gate `≤ 0.5`); `kinu29/4:11` (no video), refit
> under the corrected hydraulic objective, still fails reduced χ² (`8.37`) and
> whiteness because its logged `drained` column carries the same read-ahead
> bias with no video to correct it.
> **A PASS does not mean the residual is white**: on unweighted mL residuals
> lag-1 is still `0.54–0.56` on all three video cases, and the model's outflow
> still leads the measured level right after the bloom's first pour
> (canonical `+6.9 / +6.5 mL` at 45 / 50 s, in a σ = 15 mL segment). See
> `Refit disclosure` below and `docs/experiment_log.md`
> (`[BASELINE]`, `EXP-20260928-F12c-FIT-BUGS-AND-REFIT` and the three entries
> before it). A measurement-preprocessing layer (`Measurement preprocessing`
> below) and a video-frame measurement layer (`Video-derived measurements`
> below) both run by default; do not quote a reduced-χ² number without
> checking which observation set produced it.
> Do not quote the pre-2026-09 calibrated values — they were obtained under
> the superseded closures.

## Project Scope

This repository has a layered package structure with two complementary entry points:

- `README.md`: installation, package structure, reproducibility, model boundary, and how to read the fit metrics
- `index.html`: visual showcase of the generated outputs and the main physics stories

The current model is a reduced-order bed-scale simulator. It compares flow, bypass, thermal regime, and extraction behavior across plausible pour-over conditions, and supports calibration against measured `V_in(t)`, `V_out(t)`, retained mass, grinder PSD, and final cup temperature. The codebase is split into fixed physical inputs, tunable reduced-order closures, measured-data I/O, observation-layer transforms, and analysis/showcase entry points. It is not a particle-resolved diffusion-advection PDE solver, and its outputs are engineering-model predictions, not ground truth.

Primary use cases:

- calibrate one real brew against measured `V_in(t)` / `V_out(t)` / retained mass / PSD / cup temperature
- compare grind regimes under one consistent flow/extraction model
- inspect how temperature changes both hydraulic throughput and extraction chemistry
- diagnose whether a cup is limited by flow, accessibility, bypass, or retained liquid
- regenerate a consistent family of figures from the CLI

## Physics Model

One dynamic state family:

```
state = [V_free, V_mob, V_imm, V_abs, w, V_out, V_bed, V_poured,
         {C_fast,i, M_fast,i, C_slow,i, M_slow,i}, T, T_dripper, xi_pref]
```

| Variable | Description |
|----------|-------------|
| `V_free` | Free water ponded above the bed [m³] |
| `V_mob` | Mobile bed pore water [m³] — gravity-drainable, sets `kr(S_mob)` and the in-bed driving head |
| `V_imm` | Immobile bed pore water [m³] — capillary-held, capacity `φ·V_bed·f_retain·w` |
| `V_abs` | Water absorbed into the particles [m³], capacity `V_full·w` |
| `w` | Bed wetting state [-] — the timescale on which retention capacity opens |
| `V_out` | Cumulative bed-outlet volume [m³] |
| `V_bed` | Cumulative through-bed volume [m³] (fines-loading ageing) |
| `V_poured` | Cumulative poured volume [m³] |
| `{C_fast,i, C_slow,i}` | Bin-resolved pore-liquid concentration [g/L] |
| `{M_fast,i, M_slow,i}` | Bin-resolved remaining solid-phase solute [g] |
| `T` | Liquid temperature [K] |
| `T_dripper` | Dripper thermal node [K] |
| `xi_pref` | Preferential-flow channel state [-] (0 unless `pref_flow_coeff > 0`) |

The water inventory closes as an algebraic identity rather than a post-hoc check:

```
V_poured ≡ V_out + V_abs + V_imm + V_mob + V_free
```

Every pool's withdrawal rate is bounded by its own content over a transfer time, so non-negativity follows from the equations; there are no clamps holding the state in range. `water_balance_residual_ml` monitors the identity and is a benchmark gate.

Hydraulic closure keeps the additive resistance form:

```
k_eff   = (k / R_total) × k_kc(φ_eff)
R_total = 1 + (throat_eff − 1) + (deposition − 1) + (1/f_post − 1)
h_drive = h_free + S_mob·h_bed − h_threshold_eff + h_cap_wet      (softplus-smoothed)
Q_ext   = kr(S_mob) · Φ(T) · k_eff · h_bed · h_drive
```

Each `(term − 1)` is that mechanism's incremental resistance over the unblocked baseline. The capillary head `h_cap_bed` sets how much pore water stays immobile; it is **not** subtracted from the through-bed pressure gradient.

This is a single model family. The repository does not maintain an older fractal-PSD branch in parallel. If measured PSD bins are unavailable, the code falls back to a synthetic single-bin representation inside the same bin-resolved framework.

### Key Physical Corrections

| # | Correction | Description |
|---|-----------|-------------|
| [1] | Explicit water pools | Free / mobile-pore / immobile-pore / absorbed water are separate states; the inventory identity is structural, with no level clamp |
| [2] | Young-Laplace bed retention | `h_cap_bed = 2σ(T)/(ρ g r_pore)`, `r_pore = 0.2·d32`, sets the immobile-pool capacity through `f_retain = clip(h_cap_bed/h_bed, 0, 1)` |
| [3] | Time-resolved wetting | Retention capacity opens on `τ_wet`; measured `retained_mass_g` shows a freshly wetted bed drains, and only builds hold-up later |
| [4] | Driving head from the mobile column | `h_free + S_mob·h_bed`; Corey relative permeability takes the **mobile** saturation, with residual saturation carried explicitly by `V_imm` (`sat_rel_perm_residual ≡ 0`) |
| [5] | Supply-limited outflow | Darcy flux is capped by what the pools plus throughflow can supply, so outflow terminates without an artificial cutoff |
| [6] | Split fines clogging | `k_eff` separates early throat blocking (number-weighted fines) from later deposition (volume-weighted), with a saturating kernel `1/(1 + d/d_throat)`, `d_throat = 0.2·d32·√(φ/(1−φ))` |
| [7] | Bypass activation | Bypass stays near zero at low free-water head and opens gradually as wall-channel flow develops |
| [8] | Enthalpy-consistent thermal model | Liquid node carries `V_th = V_mob + V_imm + V_free + V_abs + V_equiv_coffee`; inlet enthalpy uses the **full** `Q_in`, so absorbed water carries its heat instead of vanishing |
| [9] | `U·A_wet(h)` dripper exchange | Liquid-dripper exchange is an area-resolved heat-transfer coefficient with a physical range, replacing a lumped rate constant that implied a super-physical `U` |
| [10] | Particle swelling | `φ(sat) = φ₀ − Δφ·sat`; Kozeny-Carman `k ∝ φ³/(1−φ)²` |
| [11] | CO₂ back-pressure | `h_gas(t) = h_gas_0·exp(−t/τ)`, small for the medium baseline and larger for fresher/light roasts |
| [12] | Crank first-term release | Slow-pool release is the first term of spherical-grain diffusion, `λ_i = π²D/(τ_tort·R_i²)` — a decaying flux, replacing the previous `exp(−L²/4Dt)` factor whose asymptote ran the wrong way |
| [13] | Stokes-Einstein diffusivity | `D(T) = k_B T / (6π μ(T) r)` is the only temperature dependence of the transport rate; the previous Arrhenius factors counted the same effect a second time and were removed |
| [14] | PSD-resolved solute split | `M_fast,0,i = dose·max_EY·vol_frac_i·shell_acc_i`, `M_slow,0,i` the complement, so `Σ M = dose·max_EY` identically — no PSD-independent scaling knobs |
| [15] | Measured PSD on an absolute scale | `PIXEL_SCALE` is read as px/mm; `d_eq = 2√(s·l)/scale`, volume `(π/6)d³`, `s/v = 6/d`; the model scale anchor is the Sauter `d32`, not the resolution-bounded number-based `D10` |
| [16] | Absolute `k_beta` prior | The PSD clogging prior is anchored to a fixed reference index instead of being proportional to `k_beta` itself (the previous form was circular and imposed no constraint) |
| [17] | χ² objective | The loss is `Σ (residual/σ)²` over five measured quantities plus log-space priors, replacing a weighted sum of five differently-dimensioned errors |

## Model boundary and unmeasured inputs

These quantities are needed to close the model but are **not measured yet**. They are disclosed here rather than absorbed into a closure. None of them is fitted as a substitute.

| Missing measurement | What it would close | Current handling |
|---|---|---|
| V60 outlet inner diameter | Equivalent outlet area `A_eq` for the truncated-cone series resistance | A fixed reference area is used; the true-to-model resistance ratio is bounded to 1.65–4.3× |
| Filter paper clean-water `Q(h)` | Paper resistance `R_paper` as a separate series term | Folded into the effective `k`; cannot be separated |
| Filter paper / cup-wall hold-up (dry vs post-brew weighing) | The constant part of retained mass outside the bed | `MEASURED_PAPER_HOLDUP_ML = 0.0`; the 7.7 mL that would fit one case does not transfer across cases, so it is not applied |
| Flow and thermal records from the **same** brew | Joint use of `thermal_profile.csv` (52 temperature points) with `flow_profile.csv` | The two CSV files are different brews (up to 62 g difference in poured mass) and are not combined. **Since 2026-09-27** the three video cases have a same-brew server-temperature time series read from the video; it enters χ² on `kinu29/4:12` and `kinu28/4:20` (see `Video-derived measurements`) |
| Outflow probe semantics | Whether the early outflow temperature reading is the stream or the vessel | Two cases disagree at `t = 5 s` (70.8 vs 25.1 °C). The video outflow series is used only as an out-of-sample check of `U`, restricted to `t ≥ 10 s` and continuous outflow `≥ 0.5 mL/s`; its sharp late drop coincides (within 1 s) with the dripper being lifted off the server, so it is not a stream-break observation |
| Server wall heat uptake before the wall is wetted | Whether the early (`V < 150 mL`) server heat capacity is geometric wetting or headspace-steam condensation on the dry wall | Measured effective heat capacity is `22–37 mL` below `100 mL` vs `42.4 mL` later; a zero-parameter wetted-area model gives only `7–13 mL` and was rejected. Server-temperature points below `150 mL` are excluded from χ²; closing this needs a wall heat-transfer coefficient from an independent measurement |
| Server mass and material | `vessel_equivalent_ml` as a Class-A input | `MEASURED_VESSEL_EQUIV_ML = 42.4` is a **back-solved** value, named "measured" for historical reasons |
| PSD absolute calibration target (a scale bar image) | The absolute length scale of the PSD | ±45% systematic uncertainty remains; the stats-CSV back-solved scale is 1.45× larger, cause unknown |
| ≥3 independent PSD samples per grind setting | Whether one Kinu click is resolvable | Within-setting spread (17–34%) exceeds between-setting difference (7%); the current PSD cannot resolve one click |
| `kinu29 4:12` **log-record** late-stage mass balance | Why `drained > poured − retained` in the last rows of the hand-logged CSV | Final retained mass reads **−7.2 g** in the log record, which is impossible. The video-derived profile (now the default source for this case, see `Video-derived measurements`) does not have this row and is not affected; the log record itself is kept for provenance (`source="log"`) and still shows the anomaly |

## Uncalibrated assumptions

Class-D parameters: present in the model, **not** fitted, and not independently measured. They are forward inputs whose sensitivity is not absorbed anywhere. Changing one changes predictions without any residual telling you so.

(`sat_rel_perm_exp` moved out of this table 2026-09-24: it is now a live Class C stage-1/2 fit parameter — see `Current Calibrated Reference` below.)

| Parameter | Value | Basis | Known weakness |
|---|---|---|---|
| `C_sat_fast` | 220 g/L | Small-molecule solubility order of magnitude | The fast pool is kinetics-limited in the current regime, so this acts as a near-linear factor |
| `C_sat_slow` | 60 / 80 / 100 g/L (light/medium/dark) | Macromolecule solubility ceiling by roast | Same; a ±30% swing is below the TDS measurement uncertainty |
| `alpha_C_fast` / `alpha_C_slow` / `alpha_C_sat` | 0.0015 / 0.006 / 0.003 K⁻¹ | Linear temperature coefficient of solubility | Not separable from `D(T)` with one final TDS reading |
| `SOLUTE_RADIUS_FAST_M` / `SOLUTE_RADIUS_SLOW_M` | 0.40 / 1.00 nm | Hydrodynamic radii entering Stokes-Einstein | Sets the absolute rate scale; fully degenerate with `tau_tort` |
| `shell_thickness` | 200 μm | Cell-damage depth of the broken outer shell | Fixed depth is not literature-supported; it also sets the fast/slow mass split through `shell_acc_i` |
| `pore_radius_ratio` | 0.2 | `r_pore = 0.2 · d32` for the Young-Laplace head | A single geometric factor standing in for the pore-throat distribution |
| `throat_clog_char_vol`, `throat_clog_gain`, `throat_relief_gain` | 25e-6 m³, 1.0, 0.58 | Throat-blocking onset scale and pour-impact relief | Not identified against any direct observation of bed structure |
| `psi_beta`, `bypass_onset_head`, `bypass_onset_width` | 1e3, 3 mm, 8 mm | Bypass activation law | Geometric/empirical; bypass is ~7% of `V_out` on the canonical case |
| `wetbed_rev_gain`, `wetbed_rev_u_half`, `wetbed_rev_h_half`, `wetbed_irr_*`, `wetbed_impact_tau` | see `params.py` | Post-bloom bed rearrangement | Several mechanisms collapsed into one factor; only `wetbed_rev_gain` is scanned |
| `h_gas_0`, `tau_co2` | 1 mm (medium), 35 s | CO₂ back-pressure as an equivalent water head | Head mapping in an open V60 bed is not sourced |
| `absorb_dry_ratio`, `absorb_full_ratio` | 0.4–0.7, 1.2–1.7 mL/g | Bloom absorption by roast | Class-B in principle, but measured per-brew values are not available |
| `max_EY` | 0.22 / 0.30 / 0.32 | Roast-level accessible solute fraction | **Frozen**: it was previously fitted and drove itself past any literature ceiling, because it is degenerate with the pool split |
| `alpha_EY` | 0.10–0.20 | Grind-size coupling `max_EY(k)` | Not independently constrained |
| `axial_node_count` | 2 | Reduced-order substitute for an axial PDE | Two CSTR layers; convergence with node count is not demonstrated |
| `lambda_server_ambient` (video cases with a server-temperature series) | 3.7e-4 s⁻¹ | Wet-wall natural convection + radiation (≈ 0.19 W/K) plus surface evaporation / wall condensation (0.15–0.3 W/K) over `C ≈ 1.22 kJ/K` → `2.9–4.1e-4 s⁻¹`; equals the project's Newton-cooling estimate `lambda_cool` | The series supports only one thermal degree of freedom (a `U`–`λ` ridge in a strict profile); freezing `λ` picks one point on that ridge. On single-point-cup cases (`kinu29/4:11`, `kinu27/4:12`) `λ` is fitted instead |
| `U_liquid_dripper` (single-point-cup cases only) | 194 W/(m²K) | Prior centre (wet-paper-plus-ceramic series estimate) | A single cup temperature does not identify `U`; on video cases with a server series it is fitted instead |

## How to read the fit metrics

The model is calibrated on one brew per case. **The canonical numbers below are calibration residuals, not prediction accuracy.** A small residual on the brew the parameters were fitted to says the closure can be bent to that brew, not that it predicts a new one. Cross-case benchmark rows are closer to a prediction test, and are reported separately.

- **`reduced χ² = χ²_data / dof`** (`dof = N_obs − p_live`; priors are not counted in `N_obs`). A value of 1 means the residuals sit at the measurement noise level. The benchmark gate is `≤ 3.0`, which allows reduced-order structural error but not "you would have to double σ to explain this".
- **Durbin-Watson (DW)** and **lag-1 autocorrelation** test whether the volume residuals look like noise. Since 2026-09-27 they are computed on **standardized residuals `r/σ`** (the quantity χ² assumes is `N(0,1)`); summaries also report them on the σ ≤ 6 mL subset and on unweighted mL residuals. On `r/σ` the σ = 15 mL segments (bloom, start of the second pour) carry 4/15 of the weight, so a whiteness PASS does not rule out structure there. White noise gives `DW ≈ 2`, `lag-1 ≈ 0`. `DW ≈ 0.2` means the residual sits on one side of the data for long stretches — a structural error, and the effective number of independent samples is a small fraction of the nominal one. **An RMSE quoted without these two numbers is not interpretable.**
- **Retention gate**: modelled retained mass (`bed hold-up + outlet hold-up`) against `poured − drained`, relative error `≤ 15%`, applied only when measured retention is `≥ 5 mL`. Retention is not in χ² (it is algebraically `poured − drained`, see `Refit disclosure` point 3); `τ_wet` is identified from the shape of `V_out(t)` itself.
- **Server T(t) gate** (video cases with a server-temperature series in χ²): RMSE of the in-χ² points `≤ 2.0 °C` (= 2σ).
- **V_RMSE is a diagnostic, not a gate.** Its relative form now uses the **measured** final volume as the denominator; the previous model-volume denominator grew whenever the model over-predicted, which loosened the gate exactly when it should have tightened.
- **Confidence intervals are conditional slices**, not strict profile likelihood: the other parameters are frozen while one is scanned, so the interval is a **lower bound** on the true width. A `None` endpoint means the parameter did not cross the threshold within ±2× — i.e. it is not identifiable there and should be frozen rather than fitted. The threshold is inflated to `Δχ² = 3.84 × max(reduced χ², 1)` because the standard 3.84 only holds when σ is right and the model has no structural error.

### Measurement uncertainty (σ)

These σ values define the χ² and therefore every statement above.

| Quantity | σ | Basis |
|---|---|---|
| `V_out` | 3.0 mL (log record); video cases use per-point tiers 4 / 6 / 15 mL | integer graduated-cylinder reading (±0.5) ⊕ scale accuracy (±2–5) ⊕ read-time offset; video tiers see `Video-derived measurements` |
| stop time | 2.5 s | visual judgement of "last drip" (log record, `q < 0.05 mL/s` operator) or liquid-level settling (video, shared `level` operator); half of the 5 s sampling interval in order of magnitude |
| cup temperature | 0.5 °C | probe accuracy (±0.2) ⊕ insertion position/time spread |
| TDS | 0.72 g/L | Brix ±0.02 °Bx ⊕ the 0.79–0.89 range of the 0.85 conversion factor (the factor dominates) |
| retained mass | 3.0 mL | difference of two readings (`poured − drained`); diagnostic band only, not in χ² |
| server temperature series | 1.0 °C | video LCD upper line: blind re-read ≤ 0.1 °C on unflagged frames, ~6% of frames ≥ 1 °C, plus probe-vs-mixed-node spatial spread; ghost-flagged frames are excluded, not down-weighted |

Log-space prior widths: `k_beta` 0.30 dex, `U_liquid_dripper` 0.20 dex (centre 194 W/m²K; active when `U` is fitted), `tau_lag` 0.30 dex (centre 1.0 s), `tau_tort` 0.35 dex (centre 5.0).

## Current Calibrated Reference

Fixed setup for the canonical case:

- grinder: `Kinu 29`; roast: `light`; dose: `20 g`
- bed height: `5.3 cm`; ambient: `23°C`; dripper: ceramic V60, `123.5 g` (the
  raw log's first row reads `224.1 g`; the file's majority value `123.5 g` is
  used, and the user confirmed `123.5 g` on 2026-09-27 — see `Video-derived
  measurements`)
- measured PSD: `data/kinu_29_light/4:12/kinu29_psd_bins.csv` (per-case scan, 36.5 px/mm)
- flow profile (video-derived, default source): `data/kinu_29_light/4:12/kinu29_light_20g_flow_profile_video.csv`
- flow profile (hand-logged record, `source="log"`): `data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv`
- dripper-removal annotation: `data/kinu_29_light/4:12/video/IMG_3346_annotations.json` (lifted at `126.94 s`; later level readings are excluded)
- server equivalent heat capacity: `42.4 mL` water equivalent — back-solved, and independently consistent with the video energy closure at `V ≥ 150 mL` (`44–46 mL`); server mass itself is not measured (see model boundary)
- thermal configuration (video case): `U_liquid_dripper` fitted; `lambda_server_ambient` frozen at `3.7e-4 s⁻¹` (see `Uncalibrated assumptions`)

Calibrated values (canonical case `kinu29/4:12`, full 7-start refit
2026-09-28 after the F12c bug fixes; summary
`data/kinu_29_light/4:12/kinu29_light_20g_flow_fit_summary.csv`). See
`Refit disclosure` below for what these numbers do and do not mean. The
canonical case changed from `kinu29/4:11` (log record) to `kinu29/4:12`
(video) on 2026-09-27 — do not compare this table against an older copy of
itself; the observation set also changed on 2026-09-27/28 (server series in
χ², post-removal rows excluded, `r/σ` whiteness):

| Quantity | Value | 95% CI (conditional) |
|---|---|---|
| `k` | `6.462e-11 m²` | `[6.361e-11, 6.751e-11] m²` (hard) |
| `sat_rel_perm_exp` | `3.189` | `[2.151, 4.315]` (medium) |
| `k_beta` | `2515 (frozen = PSD prior)` | `frozen — no CI (Class B)` |
| `beta_throat` / `beta_deposition` | `1715` / `800.1` | — |
| `tau_lag` | `0.5 s (frozen)` | `frozen — no CI (Class B)` |
| `tau_wet_s` | `10.65 s` (lower bound `10 s`) | `[None, 16.57] s` — one-sided; identifiability medium (see Refit disclosure point 5) |
| `U_liquid_dripper` | `257.6 W/(m²K)` (fitted) | `[184.7, 358.2]` (thermal identifiability medium) |
| `lambda_server_ambient` | `3.7e-4 s⁻¹` (frozen, Class D estimate) | `frozen — no CI` (weak) |
| `tau_tort` | `7.523` | hard local identifiability (span 1.27 local / 5.08 wide) |

| Fit quality | Value |
|---|---|
| `χ²` / `χ²_data` / `χ²_hydraulic` | `9.97` / `9.32` / `4.31` |
| χ² terms | volume `4.28`, server series `5.02` (6 points), stop `0.008`, extracted mass `0.004`; cup temperature not scored (series present) |
| `reduced χ²` (`dof` / `N_obs`) | `0.358` (`26` / `31`) |
| Durbin-Watson / lag-1 on `r/σ` (gate) | `1.34` / `0.326` |
| σ ≤ 6 mL subset / unweighted mL (reported, not gated) | `1.05 / 0.140` (n 16) / `0.88 / 0.561` |
| `V_out` RMSE (diagnostic) | `2.57 mL` |
| retention RMSE | `2.60 mL` |
| retention, model / observed | `53.5 mL` / `52.9 mL` (t = 125 s, last reading before the dripper is lifted) |
| cup stop error | `+0.22 s` (shared liquid-level operator; observed stop `120.9 s`) |
| server temperature series (in χ²) | RMSE `0.92 °C`, bias `+0.02 °C` (6 points, `V ≥ 150 mL`) |
| outflow temperature, out-of-sample | RMSE `2.26 °C`, bias `-0.11 °C` (13 points) |
| cup temperature error (diagnostic) | `-0.43 °C` (observed `75.0 °C`, read from the video) |
| TDS observed / error (measured denominator, last fit-valid reading) | `11.56 g/L` / `+0.045 g/L` |
| water balance residual / energy residual / clip fraction | `3.7e-13 mL` / `2.7e-6` / `0%` |
| multi-start | 7 starts, `χ² ∈ [9.97, 10.40]` |

This table is **not** comparable to the pre-2026-09-27 canonical
(`kinu29/4:11`, reduced χ² `8.48`) — it is a different brew, measured with a
different `V_out(t)` source. Nor is it directly comparable to the
2026-09-27 video-based table (reduced χ² `0.629`, `dof 22`): the observation
set changed, and most of the χ² drop comes from the stop-time operator
(`5.47 → 0.01`), not from a better model. On unweighted residuals, lag-1 is
`0.560 → 0.563` — unchanged.

Benchmark suite (`data/benchmark_suite_summary.csv`; gates in `How
to read the fit metrics`; the three video-derived cases are fully refit
against `*_flow_profile_video.csv`; `kinu29/4:11` keeps the log record and was
refit under the same corrected hydraulic objective; overall status FAIL):

| case | status | reduced χ² | DW / lag-1 (`r/σ`) | retention | cup ΔT | server T(t) RMSE | TDS error | cup stop |
|---|---|---|---|---|---|---|---|---|
| `kinu29/4:12` (canonical, video) | `PASS` | `0.358` | `1.34 / 0.326` | `1.1% OK` | `-0.43 °C` | `0.91 °C OK` | `+0.04 OK` | `+0.22 s` |
| `kinu27/4:12` (video) | `FAIL (whiteness only)` | `0.361` | `0.95 / 0.503` | `0.7% OK` | `-0.01 °C` | n/a (probe QC) | `+0.17 OK` | `-0.10 s` |
| `kinu28/4:20` (video) | `PASS` | `0.498` | `1.38 / 0.303` | `1.6% OK` | `+0.28 °C` | `1.16 °C OK` | `+0.05 OK` | `+0.49 s` |
| `kinu29/4:11` (log, `drained_log_bias_suspected`) | `FAIL` | `8.37 FAIL` | `0.30 / 0.851 FAIL` | `3.8% OK` | `-0.005 °C` | n/a | `+0.26 OK` | `-0.02 s` (q-threshold) |

`kinu27/4:12` misses the whiteness gate by `0.003` on lag-1 and is flagged
`server_probe_not_mixed_mean` (its server probe did not read the mixed mean,
so its server series is excluded and the single cup temperature is used).
`kinu29/4:11` fails reduced χ² and whiteness. The benchmark reload
reproduces every summary χ² bit for bit. An earlier gap (canonical `9.970` vs
`10.040`) came from the summary writer truncating `tau_tort` to 11
significant digits; it now writes round-trip-exact values. Even at
`rtol = 1e-7`, a ~1e-12 relative parameter change can still move χ² by about
`0.07–0.1` through the adaptive step sequence. That is far below any stage or
CI threshold, but it can flip an identifiability level that sits right at a
boundary (see Refit disclosure point 5).

## Video-derived measurements

Three of the four benchmark cases (`kinu29/4:12`, `kinu27/4:12`, `kinu28/4:20`)
have a pour-over video (`IMG_3346.MOV`, `IMG_3347.MOV`, `IMG_3405.MOV`); the
fourth, `kinu29/4:11`, does not. The full method, reproduction commands, and
per-script docstrings live in `tools/video/README.md`; this section
summarizes what changed and why it is trustworthy.

**Rig**: the scale sits under the server, so its reading is cumulative
`V_in(t)`, not `V_out(t)`; the V60 sits on top of the server; the server's
printed graduation marks are read as the liquid-front level (`V_out(t)`); a
two-channel thermocouple LCD beside the rig shows server/slurry temperature
on its upper line and dripper-outlet temperature on its lower line
(identified by matching each video's starting values against that brew's
`*_thermal_profile.csv`).

**Frame-by-frame scale, timer, and temperature readout ("V1")**: frames were
extracted at 1 fps, and each frame's true video timestamp was independently
verified against the raw 30 fps stream (`f_k = k − 0.533 s`, not the naive
`k − 1 s`). The scale's built-in timer digit was read against every
digit-rollover event in the raw 30 fps footage and fit to `timer_s = a + b ·
video_t_s`; the fitted rate `b = 1.01885 / 1.01890 / 1.01813` across the
three independent videos (standard error `≤ 5e-5`) means **the scale's timer
runs 1.86% fast relative to the real clock** — `measured_io.SCALE_TIMER_RATE
= 1.0186`, applied to every log-record time column (`t_real = time_s /
1.0186`; the video-derived profiles are already in real seconds and are not
rescaled). A blind re-read of 24 random frames found 0/24 disagreements on
the scale and timer, and roughly 6% of temperature frames off by `≥ 1 °C`,
concentrated on frames already flagged for LCD-segment ghosting.

**Frame-by-frame liquid level ("V2")**: the server's graduation marks were
calibrated to pixel position with a piecewise-linear fit — accurate here
because the graduations are printed on the front wall at the same viewing
angle as the liquid-front contact point, so the perspective foreshortening
that would bias a side- or back-wall reading cancels out. Three competing
readings (liquid front, foam top, back-wall edge) were tested against the
hand-logged `drained_volume_ml` column; only "the log leads the true liquid
front by roughly 10–20 s" fits all three videos, and foam alone accounts for
only 5–10 mL of the 13–73 mL gap. σ tiers: `4 mL` for a clearly visible
liquid front, `6 mL` for a visually overridden or interpolated frame, `15 mL`
for `V < 50 mL` (extrapolated below the lowest graduation) or an occluded
frame.

**What the video replaces**: only the hand-logged `drained_volume_ml` column,
which is not usable as a Class-A fit target for these three cases — it
systematically reads high after the bloom (`+13…+73 mL`, worst at each
pour's outflow peak and the final pour). It does **not** replace
`poured_weight_g` (cross-checked against the scale-timer video reading to
`±1–2 s`) or any other measured quantity. The corrected profile
(`data/<case>/<stem>_flow_profile_video.csv`, 1-second grid, real seconds)
carries the video liquid-front reading with per-point σ from the tiers
above; any case still fit on the log column (currently only `kinu29/4:11`,
which has no video) is flagged `drained_log_bias_suspected`.

**Reproduction**: `tools/video/README.md` has the full pipeline (`ffmpeg`
frame extraction → manual per-frame readout → timer-rate fit → liquid-level
detection → `tools/video/build_profile.py`). The raw `.MOV` files (136–167 MB
each) are **not version-controlled** (`.gitignore`); the per-frame readout
CSVs and derived JSON under `data/<case>/video/` are the version-controlled,
auditable trace of the measurement.

**Log-record deviation (before → after)**, refitting the same case against
the log column vs the video column with the model unchanged:

| case | reduced χ² (log → video) | DW (→) | lag-1 (→) | `k` [m²] (→) | `tau_wet` [s] (→) |
|---|---|---|---|---|---|
| `kinu29/4:12` | `20.15 → 0.63` | `0.21 → 0.79` | `0.76 → 0.56` | `9.87e-10 (at upper bound) → 6.32e-11` | `60.0 (at upper bound) → 15.3` |
| `kinu27/4:12` | `43.36 → 0.57` | `0.11 → 0.59` | `0.94 → 0.59` | `9.97e-10 (at upper bound) → 6.74e-11` | `59.9 (at upper bound) → 17.8` |
| `kinu28/4:20` | `21.95 → 0.31` | `0.23 → 0.92` | `0.88 → 0.53` | `9.91e-10 (at upper bound) → 8.47e-11` | `59.9 (at upper bound) → 32.8` |

**Meta-field consensus**: the hand-logged CSVs repeat their metadata columns
(e.g. `dripper_mass_g`) on every row. `kinu29/4:12` and `kinu27/4:12` each
have a first row reading `dripper_mass_g = 224.1`, while every other row in
the same file — and every other case, including `kinu28/4:20` and
`kinu29/4:11` — reads `123.5`. The video's server-temperature time series
cannot distinguish the two candidate masses (both give a server RMSE of
`3.58 °C` and a `≈ -4.9 °C` bias over the first 60 s), so
`measured_io.meta_consensus` resolves this the way any repeated-field QC
check should: take the strict majority value across rows, log the correction
in `preprocess_corrections`, and raise (fail fast) if there is no strict
majority or the disagreement is non-numeric. Only the thermal fit (stage 5)
was affected at the time: `lambda_server_ambient` moved `2.57e-4 → 4.96e-4 s⁻¹`
(`kinu29/4:12`) and `1.30e-3 → 1.54e-3 s⁻¹` (`kinu27/4:12`); hydraulics and
extraction parameters were unchanged. The user confirmed on 2026-09-27 that
`123.5 g` is correct. For the video cases this correction is applied when
`tools/video/build_profile.py` assembles the profile (the video CSV already
carries `123.5`), so it does not appear in their summary's
`preprocess_corrections` (which lists only `reading_time_sigma_s 1->0.1`).

**Server-temperature series in χ² (2026-09-27, F11)**: the server reading
(LCD upper line) enters χ² as `server_temp_series` (σ = 1.0 °C, every 5 s),
restricted to (1) after the probe is fully immersed (`26.2 / 28.9 / 30.2 mL`
per video, from a 3–6 °C step while no heat is being added), (2) `V_out ≥
150 mL`, below which the measured effective server heat capacity is only
`22–37 mL` instead of `42.4 mL`, and (3) frames without an LCD ghost flag.
When the series is present the single cup-temperature term is not scored. A
per-case energy-closure QC (measured-only effective heat capacity within
`16 mL` of `42.4 mL`) excludes `kinu27/4:12`, whose probe reads a stratified
cold layer (`65.2 mL`; flag `server_probe_not_mixed_mean`). With the series
in χ², `U_liquid_dripper` becomes identifiable and is fitted, while
`lambda_server_ambient` is frozen at `3.7e-4 s⁻¹` (the two form a ridge in a
strict profile). The outflow reading stays out of χ² and serves as an
out-of-sample check of the fitted `U` (bias `≈ 0 °C` on both series cases).

**Observation operators and readout corrections (2026-09-27, F12a)**:
- *Stop time*: the measured side and the model side use the same function,
  `observation.level_stop_time` (5-point smoothed level first within `2 mL`
  of the final value, final value = median of the last `6 s` of valid
  readings; model side sampled onto the observed grid with sub-grid
  interpolation). Constants live only in `measured_io.py`. The log-record case
  keeps the `q < 0.05 mL/s` operator. The old `+5.85 s` canonical stop error
  was mostly this operator mismatch.
- *Dripper removal*: in all three videos the dripper is lifted off the server
  before the clip ends (`126.94 / 140.71 / 121.96 s`), declared per video in
  `data/<case>/video/<VID>_annotations.json` with frame evidence. Later level
  rows are `use_for_fit = 0`; the final-cup reading (TDS denominator, stage-7
  guard) is the last fit-valid row. The sharp drop of the outflow
  thermocouple coincides with the removal (within 1 s), so it measures when
  the user lifted the dripper, not a stream break.
- *Scale-column occlusion*: where the thermocouple wire crosses the
  graduation column (detected by blue-pixel count, only `IMG_3347` frames
  107–130), the level is the median of three estimators (`median3`).

## Measurement preprocessing

Four rules run by default before every fit, benchmark, and identifiability
scan (`pour_over/preprocess.py`, wired in through
`_prepare_measured_case(preprocess=True)`). These apply to every case
regardless of source; the three video-derived cases additionally carry their
own per-point σ tiers and isotonic-regression monotonization from
`tools/video/build_profile.py` (see `Video-derived measurements` above) in
place of the reading-time-uncertainty and running-max rules below, which
remain the model for the one case still on the log record (`kinu29/4:11`):

| Rule | Constant | What / Why |
|---|---|---|
| Pour-rate physical cap | `POUR_RATE_CAP_MARGIN = 1.1`, `READING_TIME_SIGMA_S = 1.0 s` | Cap = 1.1 × that brew's own largest *other* interval pour rate (leave-one-out). A segment is rebuilt when `ΔV/(Δt + 2σ_t)` exceeds the cap: the endpoint time and cumulative volume are kept fixed, and a new start time is solved so the rebuilt segment pours at exactly the cap rate. |
| Scale drift | — | `poured` is taken as a running max; every lifted row is logged. |
| Graduated-cylinder monotonicity | — | `drained` is taken as a running max (already monotone in all four cases). |
| Reading-time uncertainty | `MEASUREMENT_SIGMA["reading_time_s"] = 1.0` | Propagated into a per-point `σ_V,eff = sqrt(σ_V² + (q_obs·σ_t)²)`, `q_obs` from a central difference of measured `V_out`. This is the error-model change behind most of the reduced-χ² drop above — see the caveat there. |

`kinu29/4:11` (the case still on the log record) triggers the pour-rate cap
once: the raw fourth-pour record reads `74 → 75 s` at `29.3 g/s` — above a
gooseneck kettle's physical rate. The cap is `8.404 g/s` (`1.1 ×` the case's
own second-largest interval rate), so that segment is rebuilt with its start
moved to `71.12 s` and `v_in(74 s)` moved from `173.6` to `194.5 g`; the
endpoint (`75 s`, `202.9 g`) and the total poured volume are unchanged. The
three video-derived cases' `poured_weight_g` (cross-checked against the
video, see `Video-derived measurements`) does not trigger this cap; their own
pour-rate caps (`8.69` / `6.34` / `8.69 g/s` for `kinu29/4:12` /
`kinu27/4:12` / `kinu28/4:20`) are not exceeded by any recorded interval.

Raw CSVs (Class A) are **never** edited by this layer — every correction
happens on the in-memory loaded case, and is logged in that case's
`preprocess_corrections` column (summary and benchmark CSVs), alongside
`max_pour_rate_g_s`. `preprocess=False` reproduces the pre-2026-09-26
behaviour, for comparison and tests only. `MEASUREMENT_SIGMA["v_out"] = 3.0`
still carries its old value without subtracting the reading-time term now
folded in separately, so σ on low-outflow segments is mildly conservative —
disclosed, not corrected, pending a cleaner separation of the two error
sources.

### Refit disclosure (2026-09-24, updated 2026-09-28)

1. **What still fails, and why the pre-video picture failed.** As of
   2026-09-28, after the F12c refit, `kinu29/4:12` and `kinu28/4:20` pass
   every gate and `kinu27/4:12` fails only residual whiteness (lag-1 `0.503`
   on `r/σ`, gate `≤ 0.5`); `kinu29/4:11` (the only case with no video) fails
   reduced χ² (`8.37`) and whiteness, and stays flagged
   `drained_log_bias_suspected`. The passes come partly from computing the
   whiteness test on `r/σ` (unweighted lag-1 is still `0.54–0.56`). The
   pre-2026-09-27 picture — `reduced χ² ∈ [8.49, 29.30]`, `DW ∈ [0.115,
   0.256]`, all four cases showing the same three-segment residual shape in
   phase with the pour rhythm — has been traced to a measurement artifact,
   not a missing mechanism: three independent pour-over videos show the
   hand-logged `drained_volume_ml` column runs `+13…+73 mL` high after the
   bloom (see `Video-derived measurements` above). Nine candidate mechanisms
   were checked and rejected against that pre-video residual: bypass, CO₂
   back-pressure (`h_gas_0 × tau_co2`), `h_cap`, a pore-gas-state closure
   (`V_gas`, 28-point scan), the original preferential-channel
   parameterization (`open_rate × tau_decay`, 3x3 grid, 9/9 rejected), a
   mis-timestamped fourth-pour record (four re-timing variants), and three
   mid-head bed-drainage closure rewrites (`Bself`, `B1L`, `B2L`; 72-point
   k×n scan) — see `docs/experiment_log.md`, entries
   `EXP-20260925-RESIDUAL-DIAGNOSTIC`, `EXP-20260926-GAS-STATE`, and
   `EXP-20260926-PREPROCESS-AND-BED-DRAINAGE`. **2026-09-27 correction**: each
   of these rejections is still correct on its own terms, but the structural
   residual they were tested against is now understood to be the logged-
   volume measurement error, not evidence any of the nine mechanisms is
   missing — see the `2026-09-27 更正` notes added to those three entries and
   `EXP-20260927-VIDEO-MEASUREMENT`. A tenth candidate — lowering the bypass
   activation head (`B3`) — crossed the formal accept threshold in isolation
   on the pre-video data but was **not** merged (its precondition did not
   hold); still recorded as a borderline candidate, now superseded by the
   video result rather than resolved by it. One phase-locked residual
   remains on the video-derived cases: model outflow leads the video liquid
   level at the start of the bloom's first pour (canonical `+6.9 / +6.5 mL`
   at 45 / 50 s; `kinu27` `+8.8 / +9.3 mL`; `kinu28` peak `+16.6 mL` at 55 s).
   It sits in the σ = 15 mL segment, so it barely registers on the `r/σ`
   gate. A layered (tanks-in-series) bed was built and tested as the
   candidate mechanism and did not pass (point 10); the mechanism is open.
2. **The three video-derived cases are now a within-instrument cross-check,
   not a mystery.** Before the video correction, `kinu29/4:12` had a
   mass-balance violation in its log record (`drained > poured` at
   `t = 130 s`) and all three lacked a usable ponding/post-pour record, so
   their `k` and `tau_wet_s` sat at the fit's upper bounds — an artifact of
   fitting a broken record, not a property of those three grinds. Refit
   against the video liquid level, all three converge to `k ∈ [6.5, 7.9] ×
   10⁻¹¹ m²` after the F12c refit (a `1.2×` spread, vs. `16×` before) and
   `tau_wet_s ∈ [10.7, 39.3] s` (the canonical value sits near its lower
   bound, point 5) — consistent in magnitude with each other; `kinu29/4:11`
   refits to `k = 5.31e-11 m²`, `tau_wet_s = 11.2 s`. This is still not an independent
   cross-validation (each case is fit to its own brew), but it is no longer
   three broken records agreeing only because they are all pinned at the
   same bound. `kinu29/4:11` remains the outlier (reduced χ² `8.37`;
   `8.65` before the F12c fix) because its `drained` column has
   the same log-record bias with no video available to correct it — see
   `data_quality_flags` in its summary CSV.
3. **Retention is not an independent observation.** `retained_mass_g` in the
   flow-profile CSVs is algebraically `poured − drained` (both already in the
   volume residual) to floating-point precision, not a separate scale
   reading. It has been removed from `chi2` for this reason and is now a gate
   / diagnostic only (`retention RMSE`, the `≤ 15%` gate above).
4. **Refit status at `rtol = 1e-7`.** The three video-derived cases were
   refit 2026-09-27 21:11 → 2026-09-28 00:11 against
   `*_flow_profile_video.csv` after two fitting-procedure bugs were fixed
   (the final-cup reading was taken after the dripper was lifted, and the
   hydraulic stages minimized the total χ² including not-yet-fitted thermal
   terms; they now minimize `chi2_hydraulic` = volume + stop time + priors).
   7 starts each (6 Latin Hypercube + 1 sibling warm-start): canonical
   `χ² ∈ [9.97, 10.40]`, `kinu27/4:12` `[6.97, 7.18]`, `kinu28/4:20`
   `[14.97, 15.11]` — one basin per case. Before the second fix, `kinu27`'s
   starts landed at `χ² 26.5–28.6` with stage 7 skipped. `kinu29/4:11`'s
   loss was also affected by the second bug; its 7-start refit lands at
   `χ² 234.64` (range `[234.64, 271.96]`). Under the old objective its stage 4
   accepted preferential flow (`pref_flow_coeff 1.14e-4`); judged on
   `chi2_hydraulic`, all seven starts reject it (`Δχ²_hyd −0.13 … −0.87`, short
   of the `−1.0` bar), so that acceptance had been driven by thermal /
   extraction terms, not hydraulic evidence. Preferential flow is now off in
   all four cases (`dof 27 → 28` on `kinu29/4:11`); the slight χ² rise
   (`233.95 → 234.64`) is expected once hydraulics stop yielding to those terms. The earlier `rtol = 1e-6` χ² surface (±7–13 noise) remains
   fully superseded.
5. **Identifiability is uneven.** On the canonical (`kinu29/4:12`,
   2026-09-28): `k` and `tau_tort` are **hard**-identified; `sat_rel_perm_exp`
   and `tau_wet_s` are medium. `tau_wet_s` dropped from hard to medium and
   now sits at `10.65 s`, `0.65 s` above its lower bound, with a one-sided CI
   `[None, 16.57] s`: once the stop time is compared through the shared
   level operator and the observation window ends at dripper removal, the
   stop term no longer constrains when outflow really stops. The project
   rule freezes a parameter only when both CI ends are `None`, so it stays
   fitted — but `10.65 s` should not be read as an identified wetting time.
   On the thermal side, `U_liquid_dripper` (fitted on video cases) is medium
   and `lambda_server_ambient` (frozen at `3.7e-4`) is weak; with only the
   single cup temperature (`kinu29/4:11`, `kinu27/4:12`) the roles are
   reversed (`λ` fitted, `U = 194` frozen). `k_beta` is medium but frozen;
   `tau_lag` is weak. `wetbed_rev_gain` and `psi` (not fitted) read medium in
   the latest scan (wide span `1.39` / `1.25`) and weak in the previous one
   (`0.97` / `0.88`): they sit on the `Δχ² = 1` boundary, where the solver's
   `0.07–0.1` path noise decides the label, so neither label is a stable
   finding. Every CI above is a
   **conditional-slice lower bound**, not a profile-likelihood interval.
6. **Honest comparison to the pre-2026-09 baseline.** The pre-2026-09
   baseline's `TDS +0.02 g/L` / `cup +0.01 °C` came from a two-parameter fit
   to two scalar observations under closures later found to violate water
   and energy conservation — a calibration residual on an unphysical model,
   not evidence of accuracy. Under the physically-defensible closures here,
   the current canonical (`kinu29/4:12`, video-derived) gives TDS error
   `+0.045 g/L` (denominator = last fit-valid reading before the dripper is
   lifted; F12a's `+0.13 / +0.23 / −0.67 g/L` used a post-removal reading and
   are superseded) and cup error `-0.43 °C` (diagnostic; the server series is
   what enters χ²). The TDS number is a **calibration
   residual, not a prediction**: stage 7 fits the single free parameter
   `tau_tort` to the single measured TDS point, so a residual below the
   measurement uncertainty (`σ = 0.72 g/L`) does not demonstrate predictive
   accuracy on TDS. `V_RMSE` moving from the pre-video `12.7 mL` to `3.26 mL` (and `2.57 mL` after F12c)
   on this same case (log column vs video column, same model) is the
   measurement correction described in `Video-derived measurements`, not an
   independent structural improvement layered on top of the water-pool and
   hydraulic rewrite.
7. **Two figures have no generator.** `v60_multi_ode_coupling.png` is a
   hand-authored architecture diagram, not a script output; `data/bloom_thermal_flow_diagnostics.png`
   is a legacy artifact with no current producer and is not referenced by
   this page. Everything else under `data/kinu_*_light/*/*_flow_fit*.png` is
   generated by `uv run python -m pour_over benchmark`, and — unlike most
   `data/**/*.png` — the four-case `_flow_fit.png` / `_flow_fit_residuals.png`
   / `_flow_fit_retention.png` triples **are** in version control via a
   `.gitignore` whitelist (`!data/**/*_flow_fit.png` etc.), so "PNG outputs
   are not version-controlled" no longer applies to them.
8. **`psd_clog_index` does not respond to grind size.** `scaled_grind_params()`
   (used by the `v60_grind.png` sweep) moves `k` explicitly via the
   Kozeny-Carman `d²` relation, but `throat_clog_index` / `deposition_clog_index`
   are ratios of particle diameter to a pore-throat diameter that both scale
   linearly with `psd_diameter_scale`, so the ratio — and therefore `k_beta`'s
   PSD prior — is invariant to it by construction. The grind narrative below
   should be read as "grind changes permeability", not "grind changes
   clogging severity"; the model does not currently represent the latter.
9. **Mid-head bed-drainage diagnostics (2026-09-26).** At `t ≥ 40 s` the
   immobile pool `V_imm` already fills `97.6–99.9%` of the bed's pore volume
   (`f_retain = 1`), so the mobile capacity `φ·V_bed − V_imm` collapses toward
   zero and `S_mob` becomes the ratio of two sub-mL quantities — this, not a
   head miscalibration, is why the model drains through a small ponded head
   almost the same way it drains through none, and why it still stops
   draining a `3.3 mm` ponded layer at `t = 142 s`. A 72-point scan of three
   explicit rewrites (`Bself`: `kr(S_w)` with `S_w = (V_mob+V_imm)/φV_bed`
   and drive `θ_mob·h_bed`; `B1L`: unit-gradient drive; `B2L`: Green-Ampt
   slug) all failed the `Δχ² ≤ -5` and `DW↑` acceptance bar together — see
   point 1 above and `docs/experiment_log.md`,
   `EXP-20260926-PREPROCESS-AND-BED-DRAINAGE`. Measured outflow (outside the
   post-fourth-pour window) tracks ponded depth roughly linearly at
   `q ≈ 0.12 mL/s/mm`, a relationship none of the tried closures reproduce
   without a mechanism this audit has not identified at the time. This
   diagnostic's own precondition — that `t ≥ 40 s` mobile capacity collapses
   toward zero — is a structural fact about the model and is unaffected by
   the video correction; the `Bself`/`B1L`/`B2L` rejections stand.
   **2026-09-27 update**: the foam hypothesis raised here has since been
   tested directly against video, not left untested — per-frame foam-layer
   thickness accounts for only 5–10 mL of the (now known to be `+13…+73 mL`)
   `drained` bias, not the `10 mL` order-of-magnitude guessed here, so foam
   is **not** the primary explanation; the video liquid-front reading, not a
   foam correction, is what replaced the log column. See `Video-derived
   measurements` above and `docs/experiment_log.md`
   `EXP-20260927-VIDEO-MEASUREMENT`.
10. **Layered bed (F12b, 2026-09-27) — negative result, not merged.** A
    tanks-in-series split of `V_mob / V_imm / V_abs` along bed depth (no new
    free parameter; bit-identical to the 0D model at one layer) was built to
    test whether a serial wetting front explains the second-pour lead. It did
    not converge in layer count (`1.9 mL` change at 8 → 16 layers vs a `0.4 mL`
    target), cost 10–50× per simulation, and cut the second-pour residual by
    only `17–43%` (target: half). The zero-parameter deficit arithmetic that
    motivated it double-counted the capillary-retention gap (capture converts
    mobile to immobile water within the same pore volume); corrected, a
    serial front explains `22–40%` of the observed `4–6 s` delay, not
    `50–100%`. The code was reverted. See `docs/experiment_log.md`,
    `EXP-20260927-F12b-LAYERED-BED`.

Structural facts that do not depend on the refit:

- `sat_rel_perm_residual` is structurally `0`; residual saturation is carried by `V_imm`.
- `max_EY` is frozen at the roast prior and is not a fit degree of freedom.
- `pref_flow_coeff = 0` on all four measured fits; it remains an optional stage-4 degree of freedom, accepted only on hydraulic evidence (`chi2_hydraulic`).
- Hydraulic stages (1/2/4) minimize `chi2_hydraulic` (volume + stop time + `k_beta` and Corey priors); thermal (stage 5) and extraction (stage 7) are fitted on the total χ².
- Stage 7 (extraction) only runs when `|V_out_model − V_out_obs| / V_out_obs ≤ 5%`, compared at the last fit-valid reading; otherwise `stage7_skipped_reason` records why.
- The only live extraction closure parameter is `tau_tort`, declared once in `params.EXTRACTION_FIT_SPEC`. Its upper bound (100) is deliberately beyond the physical range so that "the fit pushed it to the bound" is an observable failure signal.
- The full record of what changed and the pre-refit diagnostics is in `docs/experiment_log.md`, entries `EXP-20260924-PHASE2-REFIT`, `EXP-20260924-AUDIT-PHASE2`, `EXP-20260926-PREPROCESS-AND-BED-DRAINAGE`, `EXP-20260927-VIDEO-MEASUREMENT`, `EXP-20260927-F11-THERMAL-SERIES`, `EXP-20260927-F12a-OBSERVATION-OPERATORS`, `EXP-20260927-F12b-LAYERED-BED`, and `EXP-20260928-F12c-FIT-BUGS-AND-REFIT`.

## Roast Profiles

Three built-in profiles model roast-level differences in chemistry and physics:

```python
from pour_over import V60Params, RoastProfile

# Light roast — dense structure, high CO₂, mostly acids
p = V60Params.for_roast(RoastProfile.LIGHT)

# Dark roast — broken cell walls, degassed, bitter compounds dominant
p = V60Params.for_roast(RoastProfile.DARK)

# Combine with grind: light roast + fine grind
p = V60Params.for_roast(RoastProfile.LIGHT, k_target=3e-11)
```

| Parameter | Light | Medium | Dark |
|-----------|-------|--------|------|
| `max_EY` | 22% | 30% | 32% |
| `alpha_EY` | 0.10 | 0.15 | 0.20 |
| `C_sat_slow` | 60 g/L | 80 g/L | 100 g/L |
| `brew_temp_K` | 92°C | 90°C | 88°C |
| `absorb_dry_ratio` | 0.40 mL/g | 0.50 mL/g | 0.70 mL/g |
| `absorb_full_ratio` | 1.2 mL/g | 1.64 mL/g | 1.7 mL/g |
| `co2_pressure_m` | 9 mm | 1 mm | 4 mm |

`Ea_slow`, `fast_fraction`, and `k_ext_factor` were removed from the roast profile: temperature dependence is now carried entirely by Stokes-Einstein `D(T)`, and the fast/slow mass split is set per PSD bin by shell accessibility.

## Package Structure

```
pour_over/
├── __init__.py     # Public API re-exports
├── __main__.py     # uv run python -m pour_over
├── constant.py     # Measurable fixed inputs and physical constants
├── params.py       # RoastProfile, V60Params closures, PourProtocol, EXTRACTION_FIT_SPEC
├── core.py         # simulate_brew ODE engine
├── measured_io.py  # Measured CSV loading and protocol reconstruction
├── observation.py  # Outflow lag and cup/server observation layer
├── fitting.py      # chi-square objective and staged fitting (scipy.optimize)
├── benchmark.py    # Benchmark suite entry point and gates
├── identifiability.py  # Local identifiability scans and profile CI
├── psd.py          # PSD post-processing and model overrides
├── calibration_state.py  # PSD prior anchors and calibration constants
├── analysis.py     # Sensitivity, wet-bed scans, grind optimization façade
├── showcase_state.py   # Current calibrated showcase baseline loader
└── viz.py          # Pure plotting functions and compare_* figures

v60_sim.py          # Backward-compatible thin wrapper
```

- `constant.py` holds quantities that should come from measurement or hardware setup, not fitting.
- `params.py` keeps reduced-order closures and model-control knobs that may be scanned or calibrated.
- `core.py` remains the single coupled ODE engine.
- measured-data ingestion, observation-layer transforms, benchmark, identifiability, and showcase-state loading live in dedicated modules.

## Data Artifacts

PSD data has two layers:

- raw measurement export: `PSD_export_data.csv` and `PSD_export_data_stats.csv` under each brew directory (plus a legacy top-level export under `data/kinu_29_light/`)
- model-ready artifacts: `kinu*_psd_summary.csv` and `kinu*_psd_bins.csv` beside the raw export

The raw CSV files are the source of truth for particle geometry. The `*_psd_*` CSV files are generated artifacts and should be regenerated rather than edited by hand:

```bash
uv run python -m pour_over.psd \
  --raw     "data/kinu_29_light/4:12/PSD_export_data.csv" \
  --stats   "data/kinu_29_light/4:12/PSD_export_data_stats.csv" \
  --out-bins    "data/kinu_29_light/4:12/kinu29_psd_bins.csv" \
  --out-summary "data/kinu_29_light/4:12/kinu29_psd_summary.csv"
```

PSD resolution is read from the `PIXEL_SCALE` column in **px/mm**. The loader raises if the column is missing, non-unique, or non-positive — the previous hard-coded divisors silently assumed 100 μm/px and put per-case `Dv50` at 4.2 mm.

PSD ingestion priority: metadata `psd_bins_csv_path` → per-case sibling PSD in the same brew directory → top-level `data/kinu29_psd_bins.csv` (marked legacy). The former canonical high-resolution override has been removed: the top-level scan is the **lower**-resolution one, so the override contradicted its own narrative.

Large source media under `data/kinu_*_light/` (photos, PDFs) are local measurement media ignored by `.gitignore`. The CSV exports and model-ready CSV artifacts are the reproducible inputs.

## Usage

```python
from pour_over import V60Params, RoastProfile, PourProtocol, simulate_brew

# Standard regime reference brew
params   = V60Params()
protocol = PourProtocol.standard_v60()
results  = simulate_brew(params, protocol, t_end=180)

print(f"EY = {results['EY_pct'][-1]:.1f}%")
print(f"TDS = {results['TDS_gl'][-1]:.1f} g/L")
print(f"Brew time = {results['brew_time']:.0f} s")
print(f"Water balance residual = {max(abs(results['water_balance_residual_ml'])):.2e} mL")
```

```python
# Measured-bin Kinu 29 reference setup
import dataclasses
from pour_over import V60Params, RoastProfile, PourProtocol, simulate_brew

params = dataclasses.replace(
    V60Params.for_roast(RoastProfile.LIGHT),
    psd_bins_csv_path="data/kinu_29_light/4:12/kinu29_psd_bins.csv",
    h_bed=0.053,
    T_amb=296.15,
    dripper_mass_g=123.5,
    dripper_cp_J_gK=0.88,
)
results = simulate_brew(params, PourProtocol.standard_v60(), t_end=180)
print(f"bin count = {results['extraction_bin_count']}")
```

```python
# Find optimal grind size (SCA Golden Cup targets)
from pour_over import find_optimal_grind
find_optimal_grind(protocol)

# Sensitivity analysis (tornado chart + 2D heatmap)
from pour_over import sensitivity_analysis
sensitivity_analysis(protocol)
```

## Installation

```bash
uv sync
uv run python -m pour_over            # run the full simulation suite
uv run python -m pour_over benchmark  # calibrated fit + gates + identifiability
uv run python -m unittest discover -s tests
```

Most figures are generated, not stored: `.gitignore` keeps `v60_simulation.png`, `v60_tds.png`, `v60_grind.png`, `v60_thermal.png`, and `v60_multi_ode_coupling.png` in version control at the repo root, plus a whitelisted exception for the four measured cases' `_flow_fit.png` / `_flow_fit_residuals.png` / `_flow_fit_retention.png` triples under `data/kinu_*_light/*/` (`!data/**/*_flow_fit*.png` in `.gitignore`) — those are also version-controlled so the benchmark result is inspectable without rerunning the fit. Everything else under `data/**/*.png` is still ignored. `v60_multi_ode_coupling.png` is a hand-authored architecture diagram with no generator script; `data/bloom_thermal_flow_diagnostics.png` is a legacy artifact, unreferenced by this page. The extraction-quality and flow-diagnostics panels for the measured cases are written under the brew directory and must be regenerated locally:

```bash
uv run python -m pour_over benchmark
```

This writes, for the canonical case (`kinu29/4:12`, video-derived):

- `data/kinu_29_light/4:12/kinu29_light_20g_flow_fit.png` — measured vs modelled `V_out(t)` and interval `q_out`
- `data/kinu_29_light/4:12/kinu29_light_20g_flow_fit_residuals.png` — residual time series with DW / lag-1 annotation
- `data/kinu_29_light/4:12/kinu29_light_20g_flow_fit_retention.png` — modelled vs measured retained mass
- `data/kinu_29_light/4:12/kinu29_light_20g_flow_fit_summary.csv` — all metrics in the tables above
- `data/kinu_29_light/4:12/kinu29_light_20g_thermal_video_check.png` — modelled vs video-derived server/outflow temperature time series (diagnostic, not a loss term)

The artifact family has been renamed to the short `*_flow_fit*` stem above
(the previous `..._psd_clog_impactrelief_wetbedchi_180s_summary.csv` named
closures — `wetbed χ` — that no longer exist). The old-stem files are kept
under `data/archive/` for provenance only; `fitting.DEFAULT_MEASURED_FLOW_FIT_SUMMARY`
and `showcase_state` now read the short stem by default.

## SCA Golden Cup Targets

| Metric | Target |
|--------|--------|
| Extraction Yield (EY) | 18–22% |
| TDS | 11.5–14.5 g/L (1.15–1.35%) |

These are quality-framing targets, not physical validation: they describe a sensory regime, not whether the model is right. The built-in `standard_v60()` recipe uses **20 g : 340 mL (1:17)**; the generic medium baseline is a regime reference only.

## References

See `docs/literature_map.md` for the closure-by-closure source map, support
level, and open questions. Core anchors:

- Corrochano et al. (2015, *Journal of Food Engineering*) — coffee packed-bed
  permeability and Kozeny-Carman limits, DOI: `10.1016/j.jfoodeng.2014.11.006`
- Moroney et al. (2015, *Chemical Engineering Science*) — double-porosity coffee
  extraction with fast surface release and slow intragranular diffusion, DOI:
  `10.1016/j.ces.2015.06.003`
- Moroney et al. (2019, *PLOS ONE*) — extraction uniformity in porous coffee beds,
  DOI: `10.1371/journal.pone.0219906`
- Cameron et al. (2020, *Matter*) — espresso PSD, inhomogeneous flow, and
  extraction reproducibility, DOI: `10.1016/j.matt.2019.12.019`
- Crank (1975, *The Mathematics of Diffusion*) — spherical-grain diffusion series
  whose first term is the current slow-pool release law
- Brooks & Corey (1964) — relative permeability and residual saturation in
  unsaturated porous media
- Washburn (1921, *Physical Review*) — capillary-flow scaling used only as an
  analogy for wetting-time temperature dependence
- SCA / Coffee Science Foundation brewing fundamentals research — quality-target
  context for EY/TDS, not physical-model validation
