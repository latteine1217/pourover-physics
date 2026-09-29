"""
test_piecewise_integration.py — ODE 在注水率斷點間分段積分（F13-C）

What:
    1. `PourProtocol.rate_breakpoints()` 回傳注水率可能跳動的全部時刻。
    2. 分段積分下，累積注水量 `v_in_ml` 在任意時刻都等於注水曲線的精確積分
       （分段常數流率的積分 = 累積曲線的線性內插）。

Why:
    第 2 條是分段積分正確性的直接判據：段內 dV_poured/dt 為常數，RK45 對常數積分精確，
    誤差只剩捨入。單段積分跨過跳點時，這個量會帶 rtol 量級的誤差，且誤差隨步長落點翻轉——
    正是 χ² 路徑噪音的來源（χ² 側的回歸檢查見 `test_chi2_smoothness`）。
"""

import unittest

import numpy as np

from pour_over import PourProtocol, RoastProfile, V60Params, simulate_brew

# 刻意用非整數、不等距的節點，避免與 t_eval 格點或 max_step 對齊而碰巧精確
KNOTS_S = (0.0, 1.3, 2.7, 7.9, 30.4, 33.1, 41.6, 58.2, 64.9, 80.0)
CUM_ML = (0.0, 7.0, 16.5, 43.0, 43.0, 60.2, 104.0, 104.0, 160.3, 160.3)


class RateBreakpointTests(unittest.TestCase):
    def test_cumulative_profile_breakpoints_are_all_knots(self):
        prot = PourProtocol(cumulative_profile=list(zip(KNOTS_S, CUM_ML)))
        self.assertEqual(prot.rate_breakpoints(), list(KNOTS_S))

    def test_pours_breakpoints_are_starts_and_ends(self):
        prot = PourProtocol(pours=[(0, 60, 6), (45, 170, 23)])
        self.assertEqual(prot.rate_breakpoints(), [0.0, 6.0, 45.0, 68.0])


class PiecewiseIntegrationTests(unittest.TestCase):
    def test_poured_volume_is_exact_integral_of_pour_rate(self):
        params = V60Params.for_roast(RoastProfile.LIGHT)
        prot = PourProtocol(cumulative_profile=list(zip(KNOTS_S, CUM_ML)))
        res = simulate_brew(params, prot, t_end=90.0, n_eval=901, rtol=1e-7, atol=1e-9)
        t = np.asarray(res["t"], dtype=float)
        exact = np.interp(t, KNOTS_S, CUM_ML)
        err = float(np.max(np.abs(np.asarray(res["v_in_ml"], dtype=float) - exact)))
        self.assertEqual(t.size, 901)
        self.assertLess(err, 1e-9, msg=f"累積注水量與注水曲線積分差 {err:.3e} mL")


if __name__ == "__main__":
    unittest.main()
