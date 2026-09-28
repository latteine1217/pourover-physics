"""
量測預處理層（`pour_over.preprocess`，F9）的契約測試。

What: 注水率上限重建保持總量與終點、單調化、σ 擴充公式、無修正時輸出等於輸入、
      以及接入 `_prepare_measured_case` 後 protocol 與 χ² 用到的是修正值。
Why:  預處理改的是**模型看到的觀測**。每一條規則都必須可逐列追溯（corrections），
      且在沒有東西要修時必須是恆等映射——否則它就不是預處理，而是隱性調參。
"""

import unittest
from pathlib import Path

import numpy as np

from pour_over.measured_io import (
    POUR_RATE_CAP_MARGIN,
    flow_profile_quality_flags,
    load_flow_profile_csv,
)
from pour_over.preprocess import (
    infer_max_pour_rate_g_s,
    point_outflow_rate_mlps,
    preprocess_flow_profile,
    volume_sigma_ml,
)

# kinu29 4:11 紀錄表（無錄影）：第四注 74 → 75 s 的注水率異常是本檔多條測試的實例。
# F10 起 canonical 改為 kinu29 4:12，但這些測試描述的是這份紀錄本身，因此保留 4:11。
LOG_411_CSV = Path("data/kinu_29_light/4:11/kinu29_light_20g_flow_profile.csv")


def _synthetic(t, v_in, v_out):
    """最小 profile dict（欄位與 `load_flow_profile_csv` 相同）。"""
    t = np.asarray(t, dtype=float)
    v_in = np.asarray(v_in, dtype=float)
    v_out = np.asarray(v_out, dtype=float)
    prof = {
        "t_s": t, "v_in_ml": v_in, "v_out_ml": v_out,
        "use_for_fit": np.ones(t.size, dtype=int),
        "phase": [""] * (t.size - 1) + ["dripper_off_final"],
        "retained_mass_g": v_in - v_out,
    }
    prof["data_quality_flags"] = flow_profile_quality_flags(prof)
    return prof


class TestPourRateCap(unittest.TestCase):
    """規則 1：超上限注水 → 終點不動、起點前移。"""

    # 五段各 5 s、6 g/s 的注水，第四段在 1 s 內記 30 g（模仿 kinu29 4:11 74 → 75 s）
    T = [0, 5, 10, 15, 20, 24, 25, 30, 40]
    V_IN = [0, 30, 30, 60, 60, 60, 90, 120, 120]
    V_OUT = [0, 5, 15, 25, 35, 40, 45, 60, 80]

    def test_reconstruction_keeps_total_and_endpoint(self):
        prof = _synthetic(self.T, self.V_IN, self.V_OUT)
        out = preprocess_flow_profile(prof, max_pour_rate_g_s=6.6, reading_time_sigma_s=1.0)
        knots = out["pour_knots"]
        t_k = np.array([k[0] for k in knots])
        v_k = np.array([k[1] for k in knots])
        # 終點（t = 25 s, 90 g）與總量不變
        self.assertAlmostEqual(float(np.interp(25.0, t_k, v_k)), 90.0, places=9)
        self.assertAlmostEqual(float(v_k[-1]), 120.0, places=9)
        self.assertAlmostEqual(float(out["v_in_ml"][6]), 90.0, places=9)
        # 起點前移到 25 − 30/6.6，且注水率在任何區間都不超過上限
        t_start = 25.0 - 30.0 / 6.6
        self.assertTrue(np.any(np.isclose(t_k, t_start)))
        rates = np.diff(v_k) / np.diff(t_k)
        self.assertLessEqual(float(np.max(rates)), 6.6 + 1e-9)
        # 中間觀測點（t = 24 s）改成重建曲線上的值，並記錄在 corrections
        self.assertAlmostEqual(float(out["v_in_ml"][5]), 60.0 + 6.6 * (24.0 - t_start), places=9)
        fields = {(c["t_s"], c["field"]) for c in out["corrections"]}
        self.assertIn((24.0, "v_in_ml"), fields)
        self.assertIn((25.0, "pour_start_s"), fields)
        # 保水是 poured − drained 的代數重排 → 以修正值重算
        np.testing.assert_allclose(out["retained_mass_g"], out["v_in_ml"] - out["v_out_ml"])

    def test_rate_within_timestamp_tolerance_is_untouched(self):
        """ΔV/(Δt + 2σ_t) ≤ 上限者視為時間戳誤差內，不重建。"""
        prof = _synthetic([0, 5, 10, 15], [0, 30, 30, 70], [0, 5, 15, 25])
        # 最後一段 8 g/s；上限 6.6：40/(5+2) = 5.7 ≤ 6.6 → 不動
        out = preprocess_flow_profile(prof, max_pour_rate_g_s=6.6, reading_time_sigma_s=1.0)
        self.assertEqual(out["corrections"], [])

    def test_leave_one_out_cap(self):
        """上限 = margin × 第二大區間注水率（leave-one-out）。"""
        cap = infer_max_pour_rate_g_s(self.T, self.V_IN)
        self.assertAlmostEqual(cap, POUR_RATE_CAP_MARGIN * 6.0, places=9)

    @unittest.skipUnless(LOG_411_CSV.exists(), "kinu29 4:11 case 不存在")
    def test_canonical_fourth_pour(self):
        """
        kinu29 4:11：上限 1.1 × 7.64 g/計時器秒；第四注起點約計時器 71.1 s。

        F10：規則 0 先把秒計時器換算真實秒（÷ SCALE_TIMER_RATE），因此上限 ×1.0186、
        時刻 ÷1.0186；區間注水量不變。
        """
        from pour_over.measured_io import SCALE_TIMER_RATE as r
        out = preprocess_flow_profile(load_flow_profile_csv(LOG_411_CSV))
        self.assertAlmostEqual(out["max_pour_rate_g_s"], 1.1 * 38.2 / (5.0 / r), places=6)
        starts = [c["new"] for c in out["corrections"] if c["field"] == "pour_start_s"]
        self.assertEqual(len(starts), 1)
        self.assertAlmostEqual(starts[0], 75.0 / r - (202.9 - 170.3) / out["max_pour_rate_g_s"], places=6)
        self.assertGreater(starts[0], 70.0 / r)
        # 終點與總注水量不變
        idx75 = int(np.argmin(np.abs(out["t_s"] - 75.0 / r)))
        self.assertAlmostEqual(float(out["v_in_ml"][idx75]), 202.9, places=9)
        self.assertAlmostEqual(float(out["v_in_ml"][-1]), 302.7, places=9)


class TestMonotone(unittest.TestCase):
    """規則 2/3：累積量不得下降，被抬升的列逐一記錄。"""

    def test_running_max(self):
        prof = _synthetic([0, 5, 10, 15, 20], [0, 30, 29.8, 29.7, 30.0],
                          [0, 5, 10, 9.0, 12])
        out = preprocess_flow_profile(prof, max_pour_rate_g_s=10.0)
        np.testing.assert_allclose(out["v_in_ml"], [0, 30, 30, 30, 30])
        np.testing.assert_allclose(out["v_out_ml"], [0, 5, 10, 10, 12])
        rules = sorted({c["rule"] for c in out["corrections"]})
        self.assertEqual(rules, ["drained_running_max", "scale_drift_running_max"])
        self.assertEqual(len(out["corrections"]), 3)   # v_in 兩列 + v_out 一列

    def test_input_is_not_mutated(self):
        prof = _synthetic([0, 5, 10], [0, 30, 29.0], [0, 5, 10])
        before = prof["v_in_ml"].copy()
        preprocess_flow_profile(prof, max_pour_rate_g_s=10.0)
        np.testing.assert_array_equal(prof["v_in_ml"], before)


class TestSigmaPropagation(unittest.TestCase):
    """規則 4：σ_V,i = sqrt(σ_V² + (q_obs,i·σ_t)²)。"""

    def test_formula(self):
        q = np.array([0.0, 4.0, 5.0])
        np.testing.assert_allclose(volume_sigma_ml(q, 3.0, 1.0), [3.0, 5.0, np.sqrt(34.0)])

    def test_zero_time_sigma_recovers_constant(self):
        prof = _synthetic([0, 5, 10, 15], [0, 30, 30, 30], [0, 5, 15, 20])
        out = preprocess_flow_profile(prof, max_pour_rate_g_s=10.0, reading_time_sigma_s=0.0)
        np.testing.assert_allclose(out["sigma_v_ml"], 3.0)

    def test_point_rate_is_central_difference(self):
        q = point_outflow_rate_mlps([0, 5, 10, 20], [0, 10, 30, 40])
        np.testing.assert_allclose(q, [2.0, 3.0, 2.0, 1.0])


class TestIdentityWhenClean(unittest.TestCase):
    """無修正時輸出等於輸入。"""

    def test_clean_profile_is_identity(self):
        prof = _synthetic([0, 5, 10, 15, 20], [0, 30, 30, 60, 60], [0, 5, 15, 30, 40])
        out = preprocess_flow_profile(prof, max_pour_rate_g_s=10.0)
        self.assertEqual(out["corrections"], [])
        for key in ("t_s", "v_in_ml", "v_out_ml", "retained_mass_g"):
            np.testing.assert_array_equal(out[key], prof[key])
        np.testing.assert_array_equal(out["use_for_fit"], prof["use_for_fit"])
        self.assertEqual(out["data_quality_flags"], prof["data_quality_flags"])
        self.assertEqual(out["pour_knots"], list(zip(prof["t_s"].tolist(), prof["v_in_ml"].tolist())))


@unittest.skipUnless(LOG_411_CSV.exists(), "kinu29 4:11 case 不存在")
class TestCaseBundleWiring(unittest.TestCase):
    """接入 `_prepare_measured_case` 後，protocol 與 χ² 的 σ 都走修正值。"""

    def test_protocol_uses_reconstructed_pour(self):
        from pour_over.fitting import _prepare_measured_case
        from pour_over.measured_io import SCALE_TIMER_RATE as r
        case = _prepare_measured_case(LOG_411_CSV)
        raw = _prepare_measured_case(LOG_411_CSV, preprocess=False)
        # 預處理後計時器 74 → 75 s（真實秒 ÷1.0186）的注水率 = 上限；raw（不換算）仍是 29.3 g/s
        rate_pp = case["protocol"].pour_rate(74.5 / r) * 1e6
        rate_raw = raw["protocol"].pour_rate(74.5) * 1e6
        self.assertAlmostEqual(rate_pp, case["max_pour_rate_g_s"], places=6)
        self.assertAlmostEqual(rate_raw, 29.3, places=6)
        # 總注水量不變
        self.assertAlmostEqual(case["protocol"].cumulative_volume_ml(150.0),
                               raw["protocol"].cumulative_volume_ml(150.0), places=9)
        # σ：raw 為常數 σ_V，預處理後逐點 ≥ σ_V
        self.assertTrue(np.all(raw["sigma_v_obs_ml"] == 3.0))
        self.assertTrue(np.all(case["sigma_v_obs_ml"] >= 3.0))
        self.assertTrue(case["preprocess_corrections"])


if __name__ == "__main__":
    unittest.main()
