"""
F12a（2026-09-27）觀測算子一致化與量測判讀修正的契約測試。

What:
    1. 影片 case 的停流：量測端（build_profile）與模型端共用 `observation.level_stop_time`、
       同一組常數（`measured_io.STOP_TOL_ML` 等）、同一個有效格點；模型端次格內插連續；
       紀錄表 case（kinu29 4:11）維持 q 門檻判據不變。
    2. 白噪音檢定吃標準化殘差 r/σ；σ-class ≤ 6 mL 子序列與舊 mL 殘差為附報。
    3. 液位估計量合併：刻度欄被熱電偶線遮擋 → 三估計量中位數並加旗標；濾杯移開後的液位列
       不進 fit；出水口熱電偶「斷流」與濾杯移開同步（診斷）。
Why:
    這些都是「觀測面」的定義：定義不一致時 χ² 照樣算得出數字，不會有任何回歸訊號
    （R12 Q2/Q3 的 +5.85 s 停流誤差、σ = 15 點主導 lag-1 都是這一類）。
"""

import csv
import importlib.util
import json
import sys
import unittest
from pathlib import Path

import numpy as np

from pour_over import fitting, measured_io
from pour_over.fitting import residual_diagnostics
from pour_over.observation import level_stop_time, model_level_stop_time, observed_stop_time_from_layer
from pour_over.params import RoastProfile, V60Params

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools/video"))
import common as video_common  # noqa: E402

VIDEO_CASES = {
    "IMG_3346": REPO / "data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv",
    "IMG_3347": REPO / "data/kinu_27_light/4:12/kinu27_light_20g_flow_profile.csv",
    "IMG_3405": REPO / "data/kinu_28_light/4:20/kinu28_light_20g_flow_profile.csv",
}
LOG_411 = REPO / "data/kinu_29_light/4:11/kinu29_light_20g_flow_profile.csv"
HAVE_CASES = all(p.exists() for p in VIDEO_CASES.values()) and LOG_411.exists()


def _grid_rule_row(t, v, valid, t_last):
    """build_profile F10 版的格點規則（無內插）：回傳第一個候選列的時刻。"""
    vv = np.where(valid, v, np.nan)
    smooth = np.array([np.nanmean(vv[max(0, i - 2): i + 3]) if np.isfinite(vv[max(0, i - 2): i + 3]).any()
                       else np.nan for i in range(t.size)])
    t_end = t[valid].max()
    v_final = np.nanmedian(vv[t >= t_end - measured_io.FINAL_WINDOW_S])
    cand = np.flatnonzero((t > t_last) & (smooth >= v_final - measured_io.STOP_TOL_ML))
    return float(t[cand[0]])


class TestLevelStopOperator(unittest.TestCase):
    """液位停流運算子本身（合成資料）。"""

    t = np.arange(0.0, 61.0)

    @staticmethod
    def _curve(tau):
        return 100.0 * (1.0 - np.exp(-np.arange(0.0, 61.0) / tau))

    def test_matches_grid_rule_and_interpolates_within_cell(self):
        v = self._curve(10.0)
        valid = np.ones(self.t.size, dtype=bool)
        t_stop = level_stop_time(self.t, v, valid, 5.0)
        row = _grid_rule_row(self.t, v, valid, 5.0)
        # 次格內插落在「第一個候選列」的前一格之內 → 向上取整等於格點規則
        self.assertLessEqual(t_stop, row)
        self.assertGreater(t_stop, row - 1.0)
        self.assertEqual(int(np.ceil(t_stop - 1e-9)), int(row))

    def test_subgrid_continuous_in_parameters(self):
        """模型參數微調 → 停流時刻連續微移（不是 1 s 階梯）。"""
        valid = np.ones(self.t.size, dtype=bool)
        s0 = level_stop_time(self.t, self._curve(10.0), valid, 5.0)
        s1 = level_stop_time(self.t, self._curve(10.05), valid, 5.0)
        self.assertNotEqual(s0, s1)
        self.assertLess(abs(s1 - s0), 0.2)

    def test_invalid_points_ignored_and_window_ends_at_last_valid(self):
        v = self._curve(10.0)
        valid = self.t <= 40.0
        s_trunc = level_stop_time(self.t, v, valid, 5.0)
        # 把 40 s 以後的點改成任意值，不影響結果（只看有效點；終值窗止於最後一個有效點）
        v2 = v.copy()
        v2[self.t > 40.0] = 1e3
        self.assertEqual(s_trunc, level_stop_time(self.t, v2, valid, 5.0))
        self.assertLess(s_trunc, level_stop_time(self.t, v, np.ones_like(valid), 5.0))

    def test_model_side_samples_on_observation_grid(self):
        t_sim = np.linspace(0.0, 60.0, 1201)
        v_cup = 100.0 * (1.0 - np.exp(-t_sim / 10.0))
        valid = np.ones(self.t.size, dtype=bool)
        got = model_level_stop_time({"v_cup_ml": v_cup}, t_sim, self.t, valid, 5.0)
        want = level_stop_time(self.t, np.interp(self.t, t_sim, v_cup), valid, 5.0)
        self.assertEqual(got, want)


@unittest.skipUnless(HAVE_CASES, "case 不齊")
class TestStopOperatorOnCases(unittest.TestCase):
    """真實 case：影片用液位運算子、紀錄表不變、常數單一來源。"""

    def test_video_cases_use_level_operator_consistent_with_profile(self):
        for vid, path in VIDEO_CASES.items():
            with self.subTest(video=vid):
                case = fitting._prepare_measured_case(path)
                self.assertEqual(case["stop_operator"], "level")
                want = level_stop_time(case["t_obs_full"], case["v_out_obs_full"], case["fit_mask_full"],
                                       case["protocol"].last_pour_end())
                self.assertEqual(case["stop_flow_time_s"], want)
                # profile 的 flow_stop_visual 列 = 同一運算子跨越時刻所在列
                self.assertEqual(case["stop_flow_time_csv_s"], float(np.ceil(want - 1e-9)))

    def test_model_stop_uses_level_operator_for_video(self):
        case = fitting._prepare_measured_case(VIDEO_CASES["IMG_3346"])
        r = fitting._chi2_evaluate(case, V60Params.for_roast(RoastProfile.LIGHT), fitting.TAU_LAG_FIXED_S,
                                   vessel_equivalent_ml=fitting.MEASURED_VESSEL_EQUIV_ML, solver=fitting.SOLVER_COARSE)
        want = model_level_stop_time(r["obs_layer"], r["sim"]["t"], case["t_obs_full"], case["fit_mask_full"],
                                     case["protocol"].last_pour_end())
        self.assertEqual(r["stop_model_s"], want)
        self.assertEqual(r["stop_operator"], "level")

    def test_log_case_411_unchanged(self):
        case = fitting._prepare_measured_case(LOG_411)
        self.assertEqual(case["stop_operator"], "q_threshold")
        self.assertEqual(case["stop_flow_time_s"], case["stop_flow_time_csv_s"])
        self.assertAlmostEqual(case["stop_flow_time_s"], 135.0 / measured_io.SCALE_TIMER_RATE, places=9)
        r = fitting._chi2_evaluate(case, V60Params.for_roast(RoastProfile.LIGHT), fitting.TAU_LAG_FIXED_S,
                                   vessel_equivalent_ml=fitting.MEASURED_VESSEL_EQUIV_ML, solver=fitting.SOLVER_COARSE)
        self.assertEqual(r["stop_model_s"], observed_stop_time_from_layer(r["obs_layer"], r["sim"]["t"], case["protocol"]))

    def test_build_profile_imports_constants_from_measured_io(self):
        spec = importlib.util.spec_from_file_location("build_profile", REPO / "tools/video/build_profile.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertIs(mod.STOP_TOL_ML, measured_io.STOP_TOL_ML)
        self.assertIs(mod.FINAL_WINDOW_S, measured_io.FINAL_WINDOW_S)
        self.assertIs(mod.level_stop_time, level_stop_time)


@unittest.skipUnless(HAVE_CASES, "case 不齊")
class TestStandardizedWhiteness(unittest.TestCase):
    """白噪音 gate 的對象 = χ² 假設為 N(0,1) 的標準化殘差。"""

    def test_diagnostics_are_on_standardized_residuals(self):
        for path in (VIDEO_CASES["IMG_3346"], LOG_411):
            with self.subTest(case=path.parent.name):
                case = fitting._prepare_measured_case(path)
                r = fitting._chi2_evaluate(case, V60Params.for_roast(RoastProfile.LIGHT), fitting.TAU_LAG_FIXED_S,
                                           vessel_equivalent_ml=fitting.MEASURED_VESSEL_EQUIV_ML,
                                           solver=fitting.SOLVER_COARSE)
                sig = case["sigma_v_obs_ml"][case["fit_mask"]]
                z = r["v_residual_ml"] / sig
                self.assertEqual(r["residual_lag1"], residual_diagnostics(z)["lag1"])
                self.assertEqual(r["durbin_watson"], residual_diagnostics(z)["durbin_watson"])
                low = sig <= fitting.WHITENESS_SUBSET_SIGMA_MAX_ML
                self.assertEqual(r["n_resid_lowsigma"], int(low.sum()))
                self.assertEqual(r["residual_lag1_lowsigma"], residual_diagnostics(z[low])["lag1"])
                self.assertEqual(r["residual_lag1_unweighted"], residual_diagnostics(r["v_residual_ml"])["lag1"])

    def test_subset_threshold_only_drops_15ml_class(self):
        """門檻 7.5 mL：影片 6 mL 等級經時刻傳播後仍 < 7.5，15 mL 等級一律 > 7.5。"""
        for path in VIDEO_CASES.values():
            case = fitting._prepare_measured_case(path)
            base = np.array([float(r["drained_sigma_ml"]) for r in case["raw_prof"]["rows"]])
            prop = case["sigma_v_obs_full_ml"]
            self.assertTrue(np.all(prop[base <= 6.0] < fitting.WHITENESS_SUBSET_SIGMA_MAX_ML))
            self.assertTrue(np.all(prop[base >= 15.0] > fitting.WHITENESS_SUBSET_SIGMA_MAX_ML))

    def test_standardized_lag1_invariant_to_uniform_sigma_scale(self):
        rng = np.random.default_rng(20260927)
        r = np.cumsum(rng.normal(size=30))
        sig = rng.uniform(3.0, 15.0, size=30)
        self.assertAlmostEqual(residual_diagnostics(r / sig)["lag1"], residual_diagnostics(r / (2.5 * sig))["lag1"],
                               places=12)


class TestEstimatorMerge(unittest.TestCase):
    """液位估計量合併規則（`tools/video/common.merge_level_estimators`）。"""

    def test_rules(self):
        m = video_common.merge_level_estimators
        thr = video_common.WIRE_OCCLUSION_MIN_PX
        # 遮擋 + 三者有限 → 中位數
        y, q = m(500.0, 506.0, 503.0, 500.0, thr)
        self.assertEqual((y, q), (503.0, ["tick_col_wire", "median3"]))
        # 未遮擋、刻度欄與鄰格一致 → 刻度欄
        self.assertEqual(m(500.0, 506.0, 503.0, 501.0, thr - 1), (500.0, []))
        # 未遮擋、刻度欄離群 → 另兩者平均
        self.assertEqual(m(480.0, 506.0, 504.0, 500.0, 0), (505.0, ["tick_col_outlier"]))
        # 遮擋但另兩估計量不足 → 退回原規則並保留遮擋旗標
        y, q = m(500.0, float("nan"), 503.0, 500.0, thr)
        self.assertEqual((y, q), (500.0, ["tick_col_wire"]))

    @unittest.skipUnless(HAVE_CASES, "case 不齊")
    def test_level_csv_flags(self):
        paths = {vid: p.parent / "video" / f"{vid}_level.csv" for vid, p in VIDEO_CASES.items()}
        for vid, p in paths.items():
            with self.subTest(video=vid):
                with p.open(encoding="utf-8") as fh:
                    rows = list(csv.DictReader(fh))
                wire = [r for r in rows if "tick_col_wire" in r["quality"]]
                for r in rows:
                    self.assertEqual("tick_col_wire" in r["quality"],
                                     int(r["wire_px_tick"]) >= video_common.WIRE_OCCLUSION_MIN_PX)
                med = [r for r in wire if "median3" in r["quality"]]
                for r in med:
                    e = [float(r[k]) for k in ("V_tick_ml", "V_strip_ml", "V_arc_ml")]
                    self.assertAlmostEqual(float(r["V_liquid_front_ml"]), float(np.median(e)), delta=0.11)
                if vid == "IMG_3347":
                    self.assertEqual([int(r["frame"]) for r in med], list(range(107, 131)))
                else:
                    self.assertEqual(wire, [])


@unittest.skipUnless(HAVE_CASES, "case 不齊")
class TestDripperRemoval(unittest.TestCase):
    """濾杯移開的逐案標註、profile 旗標與出水口熱電偶的同步（診斷）。"""

    def test_annotation_time_matches_profile_meta(self):
        for vid, path in VIDEO_CASES.items():
            with self.subTest(video=vid):
                vdir = path.parent / "video"
                ann = json.loads((vdir / f"{vid}_annotations.json").read_text())
                t0 = json.loads((vdir / f"{vid}_timer_model.json").read_text())["timer_model"]["timer_zero_video_t"]
                want = video_common.frame_video_t(int(ann["dripper_removed_frame"]), vid) - float(t0)
                case = fitting._prepare_measured_case(path)
                self.assertAlmostEqual(case["dripper_removed_time_s"], want, places=2)
                t = case["t_obs_full"]
                last_on = video_common.frame_video_t(int(ann["dripper_removed_frame"]) - 1, vid) - float(t0)
                self.assertFalse(np.any(case["fit_mask_full"] & (t > last_on + 1e-6)))
                self.assertTrue(np.all(case["level_visible_full"][t > last_on + 1e-6]))

    def test_thermo_break_coincides_with_dripper_removal(self):
        for vid, path in VIDEO_CASES.items():
            with self.subTest(video=vid):
                case = fitting._prepare_measured_case(path)
                tb = fitting.thermo_break_time_s(case["t_obs_full"], case["outflow_temp_obs_C"],
                                                 case["protocol"].last_pour_end())
                self.assertIsNotNone(tb)
                self.assertLess(abs(tb - case["dripper_removed_time_s"]), 1.0)

    def test_thermo_break_rule_synthetic(self):
        t = np.arange(100.0, 111.0)
        to = np.array([88.0, 88.1, 88.0, 87.9, 88.0, 88.1, 86.5, 70.0, 60.0, 58.0, 57.0])
        # 105 為最後平台格（≥ 中位數 − 1）、107 為首個 ≥ 5 °C 下降格 → (105 + 106) / 2
        self.assertEqual(fitting.thermo_break_time_s(t, to, 99.0), 105.5)
        self.assertIsNone(fitting.thermo_break_time_s(t, np.full(t.size, 88.0), 99.0))


if __name__ == "__main__":
    unittest.main()


class FinalCupReadingTests(unittest.TestCase):
    """TDS 分母與 stage 7 guard 的最終杯量 = 完整序列最後一個 use_for_fit 列（F12c 修正）。"""

    def test_video_case_final_reading_precedes_dripper_removal(self):
        from pour_over.fitting import _prepare_measured_case
        case = _prepare_measured_case("data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv")
        fit_full = np.asarray(case["fit_mask_full"], dtype=bool)
        t_full = np.asarray(case["t_obs_full"], dtype=float)
        self.assertEqual(case["t_final_obs_s"], float(t_full[fit_full][-1]))
        self.assertLessEqual(case["t_final_obs_s"], float(case["dripper_removed_time_s"]))
        self.assertLess(case["t_final_obs_s"], float(case["t_obs"][-1]))

    def test_log_case_final_reading_is_last_row(self):
        from pour_over.fitting import _prepare_measured_case
        case = _prepare_measured_case("data/kinu_29_light/4:11/kinu29_light_20g_flow_profile.csv")
        self.assertEqual(case["t_final_obs_s"], float(case["t_obs"][-1]))
        self.assertEqual(case["v_out_final_obs_ml"], float(case["v_out_obs"][-1]))


class HydraulicObjectiveTests(unittest.TestCase):
    """水力 stage 的目標 = 水力觀測 + 水力 prior，與熱端參數無關（F12c 修正）。"""

    def test_hydraulic_chi2_excludes_thermal_and_extraction_terms(self):
        import dataclasses
        case = fitting._prepare_measured_case(VIDEO_CASES["IMG_3346"])
        base = V60Params.for_roast(RoastProfile.LIGHT)
        kw = dict(vessel_equivalent_ml=fitting.MEASURED_VESSEL_EQUIV_ML, solver=fitting.SOLVER_COARSE)
        r = fitting._chi2_evaluate(case, base, fitting.TAU_LAG_FIXED_S, **kw)
        t, pr = r["chi2_terms"], r["chi2_prior_terms"]
        want = t["volume"] + t["stop_time"] + pr["k_beta_psd"] + pr.get("sat_rel_perm_exp", 0.0)
        self.assertAlmostEqual(r["chi2_hydraulic"], want, places=10)
        # 只動分享壺冷卻率（不影響床內流動）→ 水力子目標不變、總 χ² 變
        r2 = fitting._chi2_evaluate(
            case, dataclasses.replace(base, lambda_server_ambient=2.0e-3),
            fitting.TAU_LAG_FIXED_S, **kw)
        self.assertAlmostEqual(r2["chi2_hydraulic"], r["chi2_hydraulic"], places=10)
        self.assertNotAlmostEqual(r2["chi2"], r["chi2"], places=3)


class SummaryPrecisionTests(unittest.TestCase):
    """summary 寫入的萃取參數必須 round-trip 精確（F12c 追查：`.10e` 截斷造成 fit/reload χ² 不一致）。"""

    def test_extraction_values_round_trip_exactly(self):
        import tempfile
        from pour_over.benchmark import _load_measured_benchmark_state, _summary_path_for
        flow = Path(VIDEO_CASES["IMG_3346"])
        _, info = _load_measured_benchmark_state(flow, _summary_path_for(flow), refit=False, verbose=False)
        v = 7.523482774261913
        info["extraction_fit_params"] = {"tau_tort": v}
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "summary.csv"
            fitting.save_flow_fit_summary_csv(out, info)
            row = next(csv.DictReader(open(out)))
        self.assertEqual(float(row["extraction_fit_param_values"]), v)
