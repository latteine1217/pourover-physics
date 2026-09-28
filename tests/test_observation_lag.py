"""
test_observation_lag.py — 觀測層一階 lag 的解析步進驗證

What:
    釘住 `apply_outflow_lag` 的兩件事：
      1. 對階躍輸入，`q_cup(t)` 精確等於 `q_in·(1 − e^{−t/τ})`，且**與時間步無關**
      2. 累積出液精確守恆：`∫q_cup = ∫q_in − V_hold`

Why:
    舊實作用顯式 Euler，等效時間常數隨 dt 偏低（coarse grid −6.4%、τ = 0.5 s 時
    −28%）。由於 τ 幾乎只由停流時間識別，這個離散化偏差會被 optimizer 直接
    吸收成 τ 的偏移——也就是「同一個 τ 在不同 n_eval 下代表不同的物理 hold-up」。
    這兩個測試把 τ 的物理意義與數值格點徹底脫鉤。
"""

import unittest

import numpy as np

from pour_over.observation import apply_outflow_lag


def _step_results(dt: float, t_end: float = 10.0, q: float = 1.0, T: float = 90.0) -> dict:
    """階躍輸入：t ≥ 0 時 q_out ≡ q、T ≡ T。"""
    t = np.arange(0.0, t_end + 0.5 * dt, dt)
    return {
        "t": t,
        "q_out_mlps": np.full_like(t, q),
        "T_C": np.full_like(t, T),
    }


class TestOutflowLagAnalytic(unittest.TestCase):
    TAU = 2.0
    DTS = (0.5, 0.25, 0.1, 0.025)

    def test_step_response_matches_analytic_at_tau(self):
        """q_cup(t = τ) 必須等於 1 − e⁻¹，誤差 < 1e-9。"""
        target = 1.0 - np.exp(-1.0)
        for dt in self.DTS:
            with self.subTest(dt=dt):
                res = _step_results(dt)
                obs = apply_outflow_lag(res, self.TAU, ambient_temp_C=23.0)
                idx = int(np.argmin(np.abs(res["t"] - self.TAU)))
                self.assertAlmostEqual(float(res["t"][idx]), self.TAU, places=12)
                self.assertLess(abs(float(obs["q_cup_mlps"][idx]) - target), 1e-9)

    def test_step_response_error_independent_of_dt(self):
        """誤差不隨 dt 變化（顯式 Euler 會有 O(dt) 的系統性偏差）。"""
        target = 1.0 - np.exp(-1.0)
        errs = []
        for dt in self.DTS:
            res = _step_results(dt)
            obs = apply_outflow_lag(res, self.TAU, ambient_temp_C=23.0)
            idx = int(np.argmin(np.abs(res["t"] - self.TAU)))
            errs.append(abs(float(obs["q_cup_mlps"][idx]) - target))
        # 全部都在機器精度內 → 最大與最小的差本身也必須在機器精度內
        self.assertLess(max(errs) - min(errs), 1e-12)
        self.assertLess(max(errs), 1e-12)

    def test_full_curve_matches_analytic(self):
        """整條 q_cup(t) 曲線都要對，不只 t = τ 那一點。"""
        res = _step_results(0.1, t_end=12.0)
        obs = apply_outflow_lag(res, self.TAU, ambient_temp_C=23.0)
        analytic = 1.0 - np.exp(-res["t"] / self.TAU)
        # index 0 是初始點（hold = 0），由步進定義；從 index 1 起比較
        self.assertLess(float(np.max(np.abs(obs["q_cup_mlps"][1:] - analytic[1:]))), 1e-9)

    def test_mass_conservation(self):
        """∫q_cup = ∫q_in − V_hold，精確到機器精度。"""
        for dt in self.DTS:
            for tau in (0.5, 2.0, 5.0):
                with self.subTest(dt=dt, tau=tau):
                    res = _step_results(dt, t_end=10.0)
                    obs = apply_outflow_lag(res, tau, ambient_temp_C=23.0)
                    # 分段常數輸入（取左端點）的精確累積量
                    v_in_total = float(np.sum(res["q_out_mlps"][:-1] * np.diff(res["t"])))
                    v_cup = float(obs["v_cup_ml"][-1])
                    v_hold = float(obs["v_hold_ml"][-1])
                    self.assertLess(abs(v_cup - (v_in_total - v_hold)), 1e-10)

    def test_tau_independent_of_grid(self):
        """同一個 τ 在不同 dt 下給出同一條 hold-up 曲線（等效 τ 不漂移）。"""
        ref = None
        probe_t = 3.0
        for dt in self.DTS:
            res = _step_results(dt, t_end=10.0)
            obs = apply_outflow_lag(res, self.TAU, ambient_temp_C=23.0)
            val = float(np.interp(probe_t, res["t"], obs["v_hold_ml"]))
            if ref is None:
                ref = val
            else:
                self.assertLess(abs(val - ref), 1e-9)

    def test_temperature_passthrough(self):
        """等溫輸入下，釋放溫度與 server 溫度都不得超出輸入溫度。"""
        res = _step_results(0.1, t_end=20.0, T=90.0)
        obs = apply_outflow_lag(
            res, self.TAU, ambient_temp_C=23.0,
            vessel_equivalent_ml=42.4, lambda_server_ambient=0.0,
        )
        self.assertLess(float(np.max(obs["T_cup_C"][1:])), 90.0 + 1e-9)
        self.assertGreater(float(obs["T_cup_C"][-1]), 89.99)
        # server 從 ambient 起，混入 90 °C 的液體後單調上升但不超過 90
        self.assertLessEqual(float(np.max(obs["T_server_C"])), 90.0 + 1e-9)
        self.assertGreaterEqual(float(obs["T_server_C"][-1]), 23.0)

    def test_server_cooling_is_exponential(self):
        """無流入時 server 溫度必須是解析指數衰減（不是顯式 Euler）。"""
        dt = 0.5
        t = np.arange(0.0, 60.0 + 0.5 * dt, dt)
        # 先注入一點液體讓 server 有內容物，之後流量歸零
        q = np.where(t <= 1.0, 10.0, 0.0)
        res = {"t": t, "q_out_mlps": q, "T_C": np.full_like(t, 90.0)}
        lam = 0.02
        obs = apply_outflow_lag(
            res, 0.2, ambient_temp_C=23.0,
            vessel_equivalent_ml=0.0, lambda_server_ambient=lam,
        )
        # 取流入結束後兩個時刻，檢查衰減比值符合 exp(−λΔt)
        i0 = int(np.argmin(np.abs(t - 20.0)))
        i1 = int(np.argmin(np.abs(t - 40.0)))
        theta0 = float(obs["T_server_C"][i0]) - 23.0
        theta1 = float(obs["T_server_C"][i1]) - 23.0
        expected = np.exp(-lam * (t[i1] - t[i0]))
        self.assertLess(abs(theta1 / theta0 - expected), 1e-9)


if __name__ == "__main__":
    unittest.main()
