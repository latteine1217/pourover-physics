"""
影片版 flow profile（F10，2026-09-27）的契約測試。

What: 影片 profile 的物理不變量、loader 的來源優先序、秤計時器速率換算、
      逐點 σ、χ² 觀測抽樣，以及 canonical 常數指向 kinu29 4:12。
Why:  影片版取代紀錄表成為三個 case 的擬合資料；它若違反守恆或單調性、loader 靜默讀錯
      來源、或時間基準換算漏掉一處，χ² 照樣算得出來，不會有任何回歸訊號。
"""

import csv
import unittest
from pathlib import Path

import numpy as np

from pour_over import fitting
from pour_over.measured_io import (
    SCALE_TIMER_RATE,
    VIDEO_READING_TIME_SIGMA_S,
    READING_TIME_SIGMA_S,
    load_flow_profile_csv,
    resolve_flow_profile_path,
)
from pour_over.preprocess import point_outflow_rate_mlps, preprocess_flow_profile, volume_sigma_ml

REPO = Path(__file__).resolve().parents[1]
VIDEO_CASES = {
    "IMG_3346": REPO / "data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv",
    "IMG_3347": REPO / "data/kinu_27_light/4:12/kinu27_light_20g_flow_profile.csv",
    "IMG_3405": REPO / "data/kinu_28_light/4:20/kinu28_light_20g_flow_profile.csv",
}
LOG_411 = REPO / "data/kinu_29_light/4:11/kinu29_light_20g_flow_profile.csv"


def _video_rows(log_path: Path) -> list[dict]:
    video = log_path.with_name(log_path.name.replace("_flow_profile.csv", "_flow_profile_video.csv"))
    with video.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@unittest.skipUnless(all(p.exists() for p in VIDEO_CASES.values()), "影片 case 不齊")
class TestVideoProfileInvariants(unittest.TestCase):
    """影片 profile 本身（Class A 衍生量）的物理不變量。"""

    def test_invariants(self):
        for vid, log_path in VIDEO_CASES.items():
            with self.subTest(video=vid):
                rows = _video_rows(log_path)
                t = np.array([float(r["time_s"]) for r in rows])
                poured = np.array([float(r["poured_weight_g"]) for r in rows])
                drained = np.array([float(r["drained_volume_ml"]) for r in rows])
                sigma = np.array([float(r["drained_sigma_ml"]) for r in rows])
                use = np.array([r["use_for_fit"] == "1" for r in rows])
                # 1 s 真實秒格點，從 0 起
                np.testing.assert_array_equal(t, np.arange(t.size, dtype=float))
                self.assertEqual({r["time_base"] for r in rows}, {"real_s"})
                self.assertEqual({r["source"] for r in rows}, {f"video:{vid}"})
                # 單調、守恆（0 ≤ retained、drained ≤ poured）
                self.assertTrue(np.all(np.diff(poured) >= 0.0))
                self.assertTrue(np.all(np.diff(drained) >= 0.0))
                self.assertTrue(np.all(poured - drained >= 0.0))
                self.assertEqual(poured[0], 0.0)
                self.assertEqual(drained[0], 0.0)
                # σ 只取三個品質等級；不可見段必為 15 mL 且不進 fit
                self.assertTrue(set(np.unique(sigma)) <= {4.0, 6.0, 15.0})
                removed = np.array(["after_dripper_removed" in r["drained_quality"] for r in rows])
                self.assertTrue(np.all(sigma[~use & ~removed] == 15.0))
                # F12a：濾杯移開後的列不進 fit，且只出現在觀測末段（移開時刻之後）
                self.assertFalse(np.any(use & removed))
                t_rm = float(rows[0]["dripper_removed_time_s"])
                self.assertTrue(np.all(t[removed] > t_rm - 1.0))
                self.assertTrue(np.all(np.diff(np.flatnonzero(removed)) == 1))
                self.assertGreater(int(use.sum()), 90)
                # 停流在最後一注之後、觀測末列之前；末列是 dripper_off_final
                phases = [r["phase"] for r in rows]
                self.assertEqual(phases[-1], "dripper_off_final")
                self.assertEqual(phases.count("flow_stop_visual"), 1)
                i_stop = phases.index("flow_stop_visual")
                last_pour = max(i for i, p in enumerate(phases) if p == "pour")
                self.assertGreater(i_stop, last_pour)
                # 杯溫：紀錄表空白時必須標明影片來源
                self.assertTrue(rows[0]["final_coffee_temp_C"])
                self.assertTrue(rows[0]["final_coffee_temp_source"])


@unittest.skipUnless(all(p.exists() for p in VIDEO_CASES.values()) and LOG_411.exists(), "case 不齊")
class TestLoaderPriority(unittest.TestCase):
    """`load_flow_profile_csv(source=...)` 的來源優先序。"""

    def test_auto_prefers_video(self):
        for log_path in VIDEO_CASES.values():
            prof = load_flow_profile_csv(log_path)
            self.assertEqual(prof["profile_source"], "video")
            self.assertTrue(prof["profile_path"].endswith("_flow_profile_video.csv"))
            self.assertEqual(prof["time_base"], "real_s")
            self.assertIsNotNone(prof["drained_sigma_ml"])
            self.assertIsNotNone(prof["server_temp_C"])

    def test_source_log_forces_the_record_sheet(self):
        for log_path in VIDEO_CASES.values():
            prof = load_flow_profile_csv(log_path, source="log")
            self.assertEqual(prof["profile_source"], "log")
            self.assertEqual(Path(prof["profile_path"]), log_path)
            self.assertEqual(prof["time_base"], "scale_timer_s")
            self.assertIsNone(prof["drained_sigma_ml"])
            self.assertIsNone(prof["server_temp_C"])

    def test_case_without_video_falls_back_to_log(self):
        prof = load_flow_profile_csv(LOG_411)
        self.assertEqual(prof["profile_source"], "log")
        self.assertIn("drained_log_bias_suspected", prof["data_quality_flags"])
        with self.assertRaises(FileNotFoundError):
            resolve_flow_profile_path(LOG_411, source="video")

    def test_log_source_rejects_video_path(self):
        video = Path(load_flow_profile_csv(VIDEO_CASES["IMG_3346"])["profile_path"])
        with self.assertRaises(ValueError):
            resolve_flow_profile_path(video, source="log")
        self.assertEqual(resolve_flow_profile_path(video), (video, "video"))


@unittest.skipUnless(LOG_411.exists() and VIDEO_CASES["IMG_3346"].exists(), "case 不齊")
class TestTimeBase(unittest.TestCase):
    """規則 0：紀錄表 time_s（秤計時器秒）→ 真實秒；影片版不縮放。"""

    def test_log_is_rescaled(self):
        raw = load_flow_profile_csv(LOG_411)
        out = preprocess_flow_profile(raw)
        np.testing.assert_allclose(out["t_s"], raw["t_s"] / SCALE_TIMER_RATE, rtol=0, atol=1e-12)
        self.assertAlmostEqual(out["stop_flow_time_s"], raw["stop_flow_time_s"] / SCALE_TIMER_RATE, places=12)
        self.assertAlmostEqual(out["final_temp_read_time_s"],
                               raw["final_temp_read_time_s"] / SCALE_TIMER_RATE, places=12)
        self.assertEqual(out["scale_timer_rate_applied"], SCALE_TIMER_RATE)
        self.assertEqual(out["reading_time_sigma_s"], READING_TIME_SIGMA_S)
        self.assertTrue(any(c["field"] == "time_s" for c in out["corrections"]))
        # 注水量不變：只改時間軸
        np.testing.assert_array_equal(np.max(out["v_in_ml"]), np.max(raw["v_in_ml"]))

    def test_video_is_not_rescaled(self):
        raw = load_flow_profile_csv(VIDEO_CASES["IMG_3346"])
        out = preprocess_flow_profile(raw)
        np.testing.assert_array_equal(out["t_s"], raw["t_s"])
        self.assertEqual(out["scale_timer_rate_applied"], 1.0)
        self.assertEqual(out["reading_time_sigma_s"], VIDEO_READING_TIME_SIGMA_S)
        self.assertFalse(any(c["field"] == "time_s" for c in out["corrections"]))
        self.assertTrue(any(c["field"] == "reading_time_sigma_s" for c in out["corrections"]))

    def test_rate_constant_matches_the_three_videos(self):
        """SCALE_TIMER_RATE = 三支影片擬合速率的平均（V1：1.01885 / 1.01890 / 1.01813）。"""
        import json
        rates = []
        for log_path in VIDEO_CASES.values():
            (tm,) = log_path.parent.glob("video/*_timer_model.json")
            rates.append(json.loads(tm.read_text())["timer_model"]["b"])
        self.assertAlmostEqual(float(np.mean(rates)), SCALE_TIMER_RATE, places=4)


class TestPointwiseSigma(unittest.TestCase):
    """規則 4：影片版的 V_out σ 逐點 = sqrt(σ_read,i² + (q_i·σ_t)²)。"""

    def test_pointwise_sigma_formula(self):
        t = np.arange(0.0, 21.0, 1.0)
        v_in = np.minimum(t * 10.0, 100.0)
        v_out = np.clip((t - 3.0) * 4.0, 0.0, None)
        s_read = np.where(v_out < 50.0, 15.0, 4.0)
        prof = {
            "t_s": t, "v_in_ml": v_in, "v_out_ml": v_out,
            "use_for_fit": np.ones(t.size, dtype=int), "phase": [""] * (t.size - 1) + ["dripper_off_final"],
            "retained_mass_g": v_in - v_out, "drained_sigma_ml": s_read,
            "profile_source": "video", "time_base": "real_s",
        }
        out = preprocess_flow_profile(prof, max_pour_rate_g_s=20.0)
        q = point_outflow_rate_mlps(t, v_out)
        np.testing.assert_allclose(
            out["sigma_v_ml"], np.sqrt(s_read ** 2 + (q * VIDEO_READING_TIME_SIGMA_S) ** 2), rtol=1e-12)
        np.testing.assert_allclose(volume_sigma_ml(q, 3.0, 1.0), np.sqrt(9.0 + q ** 2), rtol=1e-12)

    def test_nonpositive_sigma_fails_fast(self):
        t = np.arange(0.0, 6.0)
        prof = {"t_s": t, "v_in_ml": t * 10, "v_out_ml": t, "use_for_fit": np.ones(6, dtype=int),
                "phase": [""] * 6, "retained_mass_g": t * 9, "drained_sigma_ml": np.zeros(6)}
        with self.assertRaises(ValueError):
            preprocess_flow_profile(prof, max_pour_rate_g_s=20.0)


@unittest.skipUnless(VIDEO_CASES["IMG_3346"].exists() and LOG_411.exists(), "case 不齊")
class TestStrideAndChi2(unittest.TestCase):
    """χ² 觀測列只取 VIDEO_FIT_STRIDE_S 格點；完整 1 s 序列保留在 `*_full`。"""

    def test_video_case_is_strided(self):
        case = fitting._prepare_measured_case(VIDEO_CASES["IMG_3346"])
        stride = fitting.VIDEO_FIT_STRIDE_S
        self.assertEqual(case["fit_stride_s"], stride)
        np.testing.assert_allclose(np.mod(case["t_obs"], stride), 0.0, atol=1e-9)
        self.assertGreater(case["t_obs_full"].size, 4 * case["t_obs"].size)
        sel = np.isin(case["t_obs_full"], case["t_obs"])
        np.testing.assert_array_equal(case["sigma_v_obs_ml"], case["sigma_v_obs_full_ml"][sel])
        np.testing.assert_array_equal(case["fit_mask"], case["fit_mask_full"][sel])
        # 注水協議用完整 1 s 資料：末值 = 影片秤重終值
        self.assertAlmostEqual(case["protocol"].cumulative_volume_ml(1e3), float(case["v_in_obs_full"][-1]))

    def test_log_case_is_not_strided(self):
        case = fitting._prepare_measured_case(LOG_411)
        self.assertIsNone(case["fit_stride_s"])
        np.testing.assert_array_equal(case["t_obs"], case["t_obs_full"])

    def test_volume_term_uses_pointwise_sigma(self):
        """volume 項 = Σ (r_i/σ_i)²，σ_i 取 case 的逐點值（不是常數 σ_V）。"""
        from pour_over.params import RoastProfile, V60Params
        case = fitting._prepare_measured_case(VIDEO_CASES["IMG_3346"])
        res = fitting._chi2_evaluate(
            case, V60Params.for_roast(RoastProfile.LIGHT), fitting.TAU_LAG_FIXED_S,
            vessel_equivalent_ml=0.0, solver=fitting.SOLVER_COARSE, keep_sim=False)
        sig = case["sigma_v_obs_ml"][case["fit_mask"]]
        self.assertGreater(float(np.ptp(sig)), 1.0)
        self.assertAlmostEqual(res["chi2_terms"]["volume"],
                               float(np.sum((res["v_residual_ml"] / sig) ** 2)), places=6)
        self.assertEqual(res["v_residual_ml"].size, int(case["fit_mask"].sum()))


class TestCanonicalConstants(unittest.TestCase):
    """canonical 由 kinu29 4:11 切換到 kinu29 4:12（F10）；所有入口必須一致。"""

    def test_canonical_points_to_412(self):
        from pour_over.benchmark import DEFAULT_BENCHMARK_CASES
        from pour_over.showcase_state import CANONICAL_FLOW_CSV_NAME, canonical_case_dir
        self.assertIn("kinu_29_light/4:12/", fitting.DEFAULT_MEASURED_FLOW_CSV)
        self.assertIn("kinu_29_light/4:12/", fitting.DEFAULT_MEASURED_FLOW_FIT_SUMMARY)
        self.assertIn("kinu_29_light/4:12/", fitting.DEFAULT_MEASURED_FLOW_FIT_PLOT)
        self.assertEqual((canonical_case_dir() / CANONICAL_FLOW_CSV_NAME).resolve(),
                         (REPO / fitting.DEFAULT_MEASURED_FLOW_CSV).resolve())
        self.assertEqual(DEFAULT_BENCHMARK_CASES[0], fitting.DEFAULT_MEASURED_FLOW_CSV)
        self.assertEqual(len(DEFAULT_BENCHMARK_CASES), 4)
        self.assertIn("data/kinu_29_light/4:11/kinu29_light_20g_flow_profile.csv", DEFAULT_BENCHMARK_CASES)


if __name__ == "__main__":
    unittest.main()
