# Thermal History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正 thermal-history chain 的物理語義，讓 `T2` 不再直接綁定床內 bulk state，並以最小必要 effluent thermal state 改善 `4:20` 的熱端驗證。

**Architecture:** 保留現有 reduced-order 熱模型主體，不引入 full axial thermal layers。先用測試鎖定 `T2` 語義錯位，再在 `core.py` 新增最小 `T_effluent` state，最後讓 `fitting.py` 與 `observation.py` 對 `T1/T2` 使用一致的觀測鏈。

**Tech Stack:** Python, `unittest`, `scipy.solve_ivp`, local CSV artifacts

---

### Task 1: 鎖定 `T2` 語義回歸

**Files:**
- Modify: `tests/test_measured_case_registry.py`
- Modify: `pour_over/fitting.py`

- [ ] **Step 1: Write the failing test**

```python
def test_thermal_profile_uses_outflow_chain_for_t2(self) -> None:
    from pathlib import Path
    from pour_over.benchmark import _load_measured_benchmark_state
    from pour_over.fitting import evaluate_measured_thermal_profile

    flow_csv = Path("data/kinu_28_light/4:20/kinu28_light_20g_flow_profile.csv")
    thermal_csv = Path("data/kinu_28_light/4:20/kinu28_light_20g_thermal_profile.csv")
    summary_csv = Path(
        "data/kinu_28_light/4:20/kinu28_light_20g_flow_fit_psd_clog_impactrelief_wetbedchi_180s_summary.csv"
    )
    params_fit, info = _load_measured_benchmark_state(flow_csv, summary_csv, refit=False, verbose=False)
    thermal = evaluate_measured_thermal_profile(thermal_csv, params_fit, tau_lag_s=float(info["tau_lag_s"]))

    self.assertIn("model_effluent_temp_C", thermal)
    self.assertFalse((thermal["model_effluent_temp_C"] == thermal["sim"]["T_C"]).all())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests.test_measured_case_registry`
Expected: FAIL because `model_effluent_temp_C` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# evaluate_measured_thermal_profile()
interp_effluent_temp = interp1d(
    sim["t"], obs_layer["T_effluent_C"], kind="linear",
    bounds_error=False, fill_value="extrapolate",
)
model_effluent_temp_C = np.asarray(interp_effluent_temp(t_obs), dtype=float)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest tests.test_measured_case_registry`
Expected: PASS

### Task 2: 新增最小 effluent thermal state

**Files:**
- Modify: `tests/test_core_mass_balance.py`
- Modify: `pour_over/core.py`
- Modify: `pour_over/observation.py`

- [ ] **Step 1: Write the failing test**

```python
def test_simulate_brew_reports_effluent_temperature_series(self) -> None:
    from pour_over.core import simulate_brew
    from pour_over.params import PourProtocol, V60Params

    results = simulate_brew(V60Params(), PourProtocol.standard_v60(), t_end=180.0, n_eval=300)

    self.assertIn("T_effluent_C", results)
    self.assertEqual(results["T_effluent_C"].shape, results["t"].shape)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests.test_core_mass_balance`
Expected: FAIL because `T_effluent_C` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# core state extension
# state = [..., T_bulk, T_effluent, T_dripper, chi_struct, xi_pref]

# rhs
exchange_bulk_effluent = params.lambda_liquid_effluent * (T - T_effluent)
dT = ... - exchange_bulk_effluent
dT_effluent = (
    params.lambda_liquid_effluent * (T - T_effluent)
    - params.lambda_effluent_dripper * (T_effluent - T_dripper)
)

# outputs
T_effluent_K = np.clip(sol.y[T_effluent_idx], params.T_amb, params.T_brew + 5.0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m unittest tests.test_core_mass_balance`
Expected: `test_simulate_brew_reports_effluent_temperature_series` PASS

### Task 3: 接上 `T2/T1` 一致觀測鏈並回歸案例

**Files:**
- Modify: `pour_over/fitting.py`
- Modify: `docs/experiment_log.md`
- Modify: `EXPERIMENT_LOG.md`

- [ ] **Step 1: Write the failing test**

```python
def test_4_20_thermal_profile_exposes_effluent_temperature(self) -> None:
    from pathlib import Path
    from pour_over.benchmark import _load_measured_benchmark_state
    from pour_over.fitting import evaluate_measured_thermal_profile

    flow_csv = Path("data/kinu_28_light/4:20/kinu28_light_20g_flow_profile.csv")
    thermal_csv = Path("data/kinu_28_light/4:20/kinu28_light_20g_thermal_profile.csv")
    summary_csv = Path(
        "data/kinu_28_light/4:20/kinu28_light_20g_flow_fit_psd_clog_impactrelief_wetbedchi_180s_summary.csv"
    )
    params_fit, info = _load_measured_benchmark_state(flow_csv, summary_csv, refit=False, verbose=False)
    thermal = evaluate_measured_thermal_profile(thermal_csv, params_fit, tau_lag_s=float(info["tau_lag_s"]))

    self.assertIn("model_effluent_temp_C", thermal)
    self.assertIsNotNone(thermal["outflow_temp_rmse_C"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m unittest tests.test_measured_case_registry`
Expected: FAIL until `evaluate_measured_thermal_profile()` switches `T2` to effluent chain.

- [ ] **Step 3: Write minimal implementation**

```python
# observation.py
return {
    ...,
    "T_effluent_C": T_effluent_series,
}

# fitting.py
model_outflow_temp_C = np.asarray(interp_effluent_temp(t_obs), dtype=float)
```

- [ ] **Step 4: Run verification**

Run:
- `uv run python -m unittest tests.test_measured_case_registry`
- `uv run python -m unittest tests.test_core_mass_balance`
- `uv run python -m compileall pour_over`

Expected:
- new semantic tests PASS
- no new compile errors

- [ ] **Step 5: Refresh case evidence**

Run:

```bash
MPLBACKEND=Agg uv run python - <<'PY'
from pathlib import Path
from pour_over.benchmark import _load_measured_benchmark_state
from pour_over.fitting import evaluate_measured_thermal_profile, plot_measured_thermal_profile_comparison

case_dir = Path("data/kinu_28_light/4:20")
flow_csv = case_dir / "kinu28_light_20g_flow_profile.csv"
thermal_csv = case_dir / "kinu28_light_20g_thermal_profile.csv"
summary_csv = case_dir / "kinu28_light_20g_flow_fit_psd_clog_impactrelief_wetbedchi_180s_summary.csv"
params_fit, info = _load_measured_benchmark_state(flow_csv, summary_csv, refit=False, verbose=False)
thermal = evaluate_measured_thermal_profile(thermal_csv, params_fit, tau_lag_s=float(info["tau_lag_s"]))
plot_measured_thermal_profile_comparison(thermal, save_as=str(case_dir / "kinu28_light_20g_thermal_profile_comparison.png"))
print("T1_RMSE", thermal["server_temp_rmse_C"])
print("T2_RMSE", thermal["outflow_temp_rmse_C"])
PY
```

Expected: `T2 RMSE` shows a measurable change without changing extraction parameters.

- [ ] **Step 6: Update docs**

```markdown
- thermal-history chain 現在將 `T2` 綁定到 effluent thermal state，而非直接取 bed bulk `T`
- 本輪不動 `k_ext/max_EY/shell-path`，避免以 extraction closure 吸熱誤差
```
