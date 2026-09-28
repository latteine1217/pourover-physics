"""
影片熱時序進 χ²（F11，2026-09-27）的契約測試。

What: 分享壺溫時序項的單位（每點偏 1σ → χ² 增 N）、探頭浸沒前 / 容器未耦合 / 鬼影格
      不納入、時序存在時單點杯溫項移除、n_obs / dof 記帳、紀錄表 case（kinu29 4:11）
      行為不變、缺 V_immersion 時 Fail Fast。
Why:  這些條件全都「算得出數字」——漏掉任何一條，χ² 照樣收斂，只是把浸沒前的空氣讀值、
      同一個杯溫讀值兩次、或熱容結構誤差悄悄餵進熱端參數，沒有任何回歸訊號。
"""

import unittest
from pathlib import Path

import numpy as np

from pour_over import fitting
from pour_over.measured_io import SERVER_PROBE_IMMERSION_ML
from pour_over.params import RoastProfile, V60Params

REPO = Path(__file__).resolve().parents[1]
CANONICAL = REPO / "data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv"
VIDEO_CASES = {
    "IMG_3346": CANONICAL,
    "IMG_3347": REPO / "data/kinu_27_light/4:12/kinu27_light_20g_flow_profile.csv",
    "IMG_3405": REPO / "data/kinu_28_light/4:20/kinu28_light_20g_flow_profile.csv",
}
LOG_411 = REPO / "data/kinu_29_light/4:11/kinu29_light_20g_flow_profile.csv"


def _eval(case, params=None, **kw):
    params = params or V60Params.for_roast(RoastProfile.LIGHT)
    return fitting._chi2_evaluate(
        case, params, fitting.TAU_LAG_FIXED_S,
        vessel_equivalent_ml=fitting.MEASURED_VESSEL_EQUIV_ML,
        solver=fitting.SOLVER_COARSE, **kw)


@unittest.skipUnless(all(p.exists() for p in VIDEO_CASES.values()), "影片 case 不齊")
class TestServerSeriesMask(unittest.TestCase):
    """進 χ² 的時序點只由量測決定，且滿足每一條觀測窗條件。"""

    def test_mask_conditions(self):
        for vid, path in VIDEO_CASES.items():
            with self.subTest(video=vid):
                case = fitting._prepare_measured_case(path)
                m = case["server_series_mask_full"]
                t = case["t_obs_full"]
                v = case["v_out_obs_full"]
                if case["server_series_qc"] != "ok":
                    self.assertEqual(int(m.sum()), 0)   # QC 不過 → 整條排除（另測）
                    continue
                self.assertGreater(int(m.sum()), 3)
                self.assertEqual(case["v_immersion_ml"], SERVER_PROBE_IMMERSION_ML[vid])
                # stride 格點、液位可見、浸沒後、容器耦合後
                np.testing.assert_allclose(np.mod(t[m], fitting.VIDEO_FIT_STRIDE_S), 0.0, atol=1e-9)
                self.assertTrue(np.all(case["level_visible_full"][m]))
                self.assertTrue(np.all(v[m] >= case["v_immersion_ml"]))
                self.assertTrue(np.all(v[m] >= fitting.SERVER_SERIES_MIN_V_ML))
                # 上行有鬼影旗標的格一律不收
                flags = case["temp_flag"]
                for i in np.flatnonzero(m):
                    segs = [s.strip() for s in str(flags[i]).split(";") if s.strip()]
                    self.assertFalse(any(s.startswith("U") or s == "no_frame" for s in segs))
                np.testing.assert_array_equal(case["server_series_t"], t[m])
                np.testing.assert_array_equal(case["server_series_obs_C"], case["server_temp_obs_C"][m])

    def test_pre_immersion_points_exist_and_are_excluded(self):
        """浸沒前確實有液位可見、有讀值的 stride 格點，而它們沒有進 χ²。"""
        case = fitting._prepare_measured_case(CANONICAL)
        t, v = case["t_obs_full"], case["v_out_obs_full"]
        on_grid = np.isclose(np.mod(t, fitting.VIDEO_FIT_STRIDE_S), 0.0)
        pre = on_grid & case["fit_mask_full"] & (v < case["v_immersion_ml"]) \
            & np.isfinite(case["server_temp_obs_C"])
        self.assertGreater(int(pre.sum()), 0)
        self.assertFalse(np.any(case["server_series_mask_full"][pre]))
        self.assertGreater(case["server_series_excluded"]["below_immersion"], 0)

    def test_energy_closure_qc(self):
        """
        量測能量閉合 QC：kinu29 / kinu28 通過（C_eff ≈ 42.4），kinu27 分層不通過 → 整條排除、
        加品質旗標、退回單點杯溫。
        """
        expected = {"IMG_3346": "ok", "IMG_3405": "ok", "IMG_3347": "server_probe_not_mixed_mean"}
        for vid, path in VIDEO_CASES.items():
            with self.subTest(video=vid):
                case = fitting._prepare_measured_case(path)
                self.assertEqual(case["server_series_qc"], expected[vid])
                dev = abs(case["server_energy_closure_c_eff_ml"] - fitting.MEASURED_VESSEL_EQUIV_ML)
                if expected[vid] == "ok":
                    self.assertLessEqual(dev, fitting.SERVER_ENERGY_CLOSURE_TOL_ML)
                    self.assertNotIn("server_probe_not_mixed_mean", case["data_quality_flags"])
                else:
                    self.assertGreater(dev, fitting.SERVER_ENERGY_CLOSURE_TOL_ML)
                    self.assertIn("server_probe_not_mixed_mean", case["data_quality_flags"])
                    self.assertEqual(case["server_series_t"].size, 0)
                    res = _eval(case, keep_sim=False)
                    self.assertGreater(res["chi2_terms"]["cup_temp"], 0.0)
                    self.assertNotIn("server_temp_series", res["chi2_terms"])

    def test_missing_immersion_volume_fails_fast(self):
        n = 10
        with self.assertRaises(ValueError):
            fitting._thermal_series_masks(
                t_full=np.arange(n, dtype=float), v_out_full=np.linspace(0, 200, n),
                level_ok_full=np.ones(n, bool), sel=np.ones(n, bool),
                server_obs=np.full(n, 60.0), outflow_obs=np.full(n, 80.0), temp_flag=None,
                stop_flow_time_s=9.0, video_id="IMG_UNKNOWN")

    def test_outflow_candidate_window(self):
        case = fitting._prepare_measured_case(CANONICAL)
        m = case["outflow_series_candidate_mask_full"]
        t = case["t_obs_full"]
        self.assertGreater(int(m.sum()), 0)
        self.assertTrue(np.all(t[m] >= fitting.OUTFLOW_PROBE_WETTING_S))
        self.assertTrue(np.all(t[m] <= case["stop_flow_time_s"]))
        # 只在裁決納入時才進 χ²
        self.assertEqual(case["outflow_series_t"].size,
                         int(m.sum()) if fitting.OUTFLOW_TEMP_SERIES_IN_CHI2 else 0)


@unittest.skipUnless(CANONICAL.exists() and LOG_411.exists(), "case 不齊")
class TestServerSeriesChi2(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.case = fitting._prepare_measured_case(CANONICAL)
        cls.res = _eval(cls.case)

    def test_unit_one_sigma_shift_gives_n(self):
        """量測整體平移 1σ_Ts（相對模型）→ 時序項 = N（定義驗算）。"""
        case = dict(self.case)
        t_sim = np.asarray(self.res["sim"]["t"])
        model = np.interp(case["server_series_t"], t_sim, self.res["obs_layer"]["T_server_C"])
        sigma = fitting.MEASUREMENT_SIGMA["server_temp_series_C"]
        case["server_series_obs_C"] = model - sigma
        shifted = _eval(case, keep_sim=False)
        n = int(case["server_series_t"].size)
        self.assertAlmostEqual(shifted["chi2_terms"]["server_temp_series"], float(n), places=6)
        self.assertEqual(shifted["server_series_n"], n)

    def test_term_matches_residuals(self):
        r = self.res["server_series_residual_C"]
        sigma = fitting.MEASUREMENT_SIGMA["server_temp_series_C"]
        self.assertAlmostEqual(self.res["chi2_terms"]["server_temp_series"],
                               float(np.sum((r / sigma) ** 2)), places=9)

    def test_single_cup_term_removed_when_series_present(self):
        """時序存在 → 單點杯溫不計分、不計入 n_obs；誤差仍回報（診斷 / gate 用）。"""
        self.assertEqual(self.res["chi2_terms"]["cup_temp"], 0.0)
        self.assertIsNotNone(self.res["cup_temp_error_C"])
        n_vol = int(self.case["fit_mask"].sum())
        n_tds = 1 if self.case["final_tds_gl"] is not None else 0
        expected = n_vol + 1 + n_tds + int(self.case["server_series_t"].size) \
            + int(self.case["outflow_series_t"].size)
        self.assertEqual(self.res["n_obs"], expected)

    def test_dof(self):
        res = _eval(self.case, n_fit_params=6, keep_sim=False)
        self.assertEqual(res["dof"], res["n_obs"] - 6)
        self.assertAlmostEqual(res["reduced_chi2"], res["chi2_data"] / res["dof"])

    def test_log_case_411_unchanged(self):
        """紀錄表 case：無時序項、單點杯溫照舊計分、熱端自由度仍只有 λ_server。"""
        case = fitting._prepare_measured_case(LOG_411)
        self.assertEqual(case["server_series_t"].size, 0)
        self.assertEqual(case["outflow_series_t"].size, 0)
        self.assertIsNone(case["v_immersion_ml"])
        res = _eval(case, keep_sim=False)
        self.assertNotIn("server_temp_series", res["chi2_terms"])
        self.assertNotIn("outflow_temp_series", res["chi2_terms"])
        self.assertGreater(res["chi2_terms"]["cup_temp"], 0.0)
        n_vol = int(case["fit_mask"].sum())
        n_tds = 1 if case["final_tds_gl"] is not None else 0
        self.assertEqual(res["n_obs"], n_vol + 1 + 1 + n_tds)
        self.assertEqual(fitting.THERMAL_SINGLE_POINT_FIT_PARAMS, ("lambda_server_ambient",))
        # F6 的 λ_server seed 網格原樣保留 → 單點 case 的 stage 5 逐位元重現舊行為
        self.assertEqual(fitting.THERMAL_FIT_SEEDS["lambda_server_ambient"],
                         (1.0e-5, 2.0e-4, 5.0e-4, 1.0e-3, 2.0e-3, 4.0e-3))

    def test_thermal_fit_params_have_bounds_and_seeds(self):
        for name in fitting.THERMAL_SERIES_FIT_PARAMS + fitting.THERMAL_SINGLE_POINT_FIT_PARAMS:
            lo, hi = fitting.THERMAL_FIT_BOUNDS[name]
            self.assertLess(lo, hi)
            self.assertTrue(all(lo <= s <= hi for s in fitting.THERMAL_FIT_SEEDS[name]))
            self.assertTrue(hasattr(V60Params(), name))


if __name__ == "__main__":
    unittest.main()
