"""
tests/test_water_energy_conservation.py — 主模型的水量與能量守恆回歸測試

What:
    對 `simulate_brew` 的輸出直接驗算兩本帳：
      1. 水量：V_poured ≡ V_out + V_abs + V_imm + V_mob + V_free（全程）
      2. 能量：累積焓殘差 < 2% E_in，且對參考溫度不變
    並釘住 F2b 的床內水力判別式：immobile 池只增不減、mobile 池可被重力排乾。

Why:
    這兩件事在舊模型是「事後才發現的漏帳」：吸水被記兩次（差 15.5 mL）、
    H_MIN clamp 憑空生水 0.48 mL、吸收水的焓與熱容完全未計（10.7% E_in）。
    把它們寫成測試之後，任何新 closure 若再靠漏帳換低 loss，會被當場擋下。
    參考溫度不變性是關鍵的第二道檢查：焓是相對量，若審計本身寫錯
    （例如漏掉某個水池的熱容），殘差會隨參考溫度漂移，而不是剛好對上一個數字。
"""

import unittest

import numpy as np

from pour_over import PourProtocol, RoastProfile, V60Params, simulate_brew

WATER_TOL_ML = 0.05
ENERGY_TOL_FRAC = 0.02
ENERGY_REF_INVARIANCE_FRAC = 0.001


def _calibrated_case():
    """
    What: 回傳 measured benchmark 的 calibrated (params, protocol)；失敗時回傳 None。
    Why:  守恆是結構性質，必須在預設參數與 calibrated 參數上同時成立；
          但 calibrated state 依賴 measured artifact，不該讓測試因缺檔而假性失敗。
    """
    try:
        from pathlib import Path

        from pour_over.benchmark import _load_measured_benchmark_state
        from pour_over.fitting import DEFAULT_MEASURED_FLOW_FIT_SUMMARY
        from pour_over.measured_io import load_flow_profile_csv

        # 缺 calibrated summary 時**直接放棄**，不要讓測試觸發重擬。
        # Why: `_load_measured_benchmark_state` 的契約是「summary 不存在就重擬」，
        #      那是給 benchmark 用的。在單元測試裡它會變成一次 ~20 min 的完整
        #      multi-start 校準，而且會**靜默覆寫** canonical artifact——
        #      F6 改 artifact 檔名那天就真的發生了一次（測試把剛寫好的
        #      calibrated state 換成另一次 fit 的結果）。
        if not Path(DEFAULT_MEASURED_FLOW_FIT_SUMMARY).exists():
            return None
        params, info = _load_measured_benchmark_state(None, None, refit=False, verbose=False)
        prof = load_flow_profile_csv(info["csv_path"])
        t_obs = np.asarray(prof["t_s"], dtype=float)
        v_in_obs = np.maximum.accumulate(np.asarray(prof["v_in_ml"], dtype=float))
        protocol = PourProtocol.from_cumulative_profile(list(zip(t_obs, v_in_obs)))
        return params, protocol
    except Exception:  # noqa: BLE001 — 缺 artifact / F1 正在改 PSD 時退回預設參數
        return None


class WaterBalanceTests(unittest.TestCase):
    def setUp(self):
        self.params = V60Params.for_roast(RoastProfile.LIGHT)
        self.protocol = PourProtocol.standard_v60()
        self.results = simulate_brew(self.params, self.protocol, t_end=180, max_step=0.5)

    def _assert_water_balance(self, params, results):
        residual = np.asarray(results["water_balance_residual_ml"], dtype=float)
        self.assertTrue(np.all(np.isfinite(residual)))
        self.assertLess(float(np.max(np.abs(residual))), WATER_TOL_ML)

        v_abs = np.asarray(results["V_abs_ml"], dtype=float)
        self.assertLessEqual(float(np.max(v_abs)), params._V_full * 1e6 + 1e-6)
        self.assertGreaterEqual(float(np.min(v_abs)), -1e-9)

        s_bed = np.asarray(results["S_bed"], dtype=float)
        self.assertLessEqual(float(np.max(s_bed)), 1.0 + 1e-9)
        self.assertGreaterEqual(float(np.min(s_bed)), -1e-9)

        # mobile / immobile 兩池：各自非負，且共用同一孔隙體積（總和 ≤ φ·V_bed）
        v_mob = np.asarray(results["V_mob_ml"], dtype=float)
        v_imm = np.asarray(results["V_imm_ml"], dtype=float)
        self.assertGreaterEqual(float(np.min(v_mob)), -1e-9)
        self.assertGreaterEqual(float(np.min(v_imm)), -1e-9)
        self.assertLessEqual(float(np.max(v_mob + v_imm)), params.V_liquid * 1e6 + 1e-6)
        np.testing.assert_allclose(results["V_pore_ml"], v_mob + v_imm, rtol=0, atol=1e-9)

        # immobile 容量 = φ·V_bed·f_retain·w：不得超過 w 允許的上限
        w = np.asarray(results["w_wet"], dtype=float)
        self.assertGreaterEqual(float(np.min(w)), -1e-12)
        self.assertLessEqual(float(np.max(w)), 1.0 + 1e-12)
        cap_imm = params.V_liquid * params.bed_retention_fraction(params.T_brew) * w * 1e6
        self.assertLessEqual(float(np.max(v_imm - cap_imm)), 1e-6)

        # S_mob 是 mobile 水佔「可排空孔隙」的比例，必須落在 [0, 1]
        s_mob = np.asarray(results["S_mob"], dtype=float)
        self.assertGreaterEqual(float(np.min(s_mob)), -1e-12)
        self.assertLessEqual(float(np.max(s_mob)), 1.0 + 1e-12)

        # 自由水體積不得為負（h_free 由體積反解，負值會被 max() 掩蓋）
        self.assertGreaterEqual(float(np.min(results["V_free_ml"])), -1e-9)

        # 旁路流量恆非負：舊後處理用展示 sat 回餵，曾出現負 bypass
        self.assertGreaterEqual(float(np.min(results["q_bp_mlps"])), -1e-12)
        self.assertGreaterEqual(float(np.min(results["bypass_ratio"])), 0.0)

        # v_extract_ml 必須就是 ODE 狀態 V_bed，而不是矩形和重算
        np.testing.assert_allclose(results["v_extract_ml"], results["v_bed_ml"], rtol=0, atol=0)

    def test_default_light_roast_conserves_water(self):
        self._assert_water_balance(self.params, self.results)

    def test_calibrated_case_conserves_water(self):
        case = _calibrated_case()
        if case is None:
            self.skipTest("measured benchmark artifact 不可用")
        params, protocol = case
        results = simulate_brew(params, protocol, t_end=180, max_step=0.5, n_eval=1200)
        self._assert_water_balance(params, results)


class EnergyBalanceTests(unittest.TestCase):
    def setUp(self):
        self.params = V60Params.for_roast(RoastProfile.LIGHT)
        self.protocol = PourProtocol.standard_v60()
        self.results = simulate_brew(self.params, self.protocol, t_end=180, max_step=0.5)

    def _assert_energy_balance(self, results):
        e_in = float(results["energy_input_J"])
        self.assertGreater(e_in, 0.0)

        residual = np.asarray(results["energy_balance_residual_J"], dtype=float)
        self.assertTrue(np.all(np.isfinite(residual)))
        self.assertLess(float(np.max(np.abs(residual))) / e_in, ENERGY_TOL_FRAC)

        # 參考溫度不變性：T_ref = T_amb 與 T_ref = 0 K 兩套審計必須給同一條殘差曲線
        residual_ref0 = np.asarray(results["energy_balance_residual_ref0_J"], dtype=float)
        drift = float(np.max(np.abs(residual - residual_ref0))) / e_in
        self.assertLess(drift, ENERGY_REF_INVARIANCE_FRAC)

    def test_default_light_roast_conserves_energy(self):
        self._assert_energy_balance(self.results)

    def test_temperature_clip_is_not_silently_absorbing_energy(self):
        # clip 會破壞能量守恆；> 1% 代表熱端 closure 已把溫度推出物理區間
        self.assertLess(float(self.results["clip_active_fraction"]), 0.01)

    def test_calibrated_case_conserves_energy(self):
        case = _calibrated_case()
        if case is None:
            self.skipTest("measured benchmark artifact 不可用")
        params, protocol = case
        results = simulate_brew(params, protocol, t_end=180, max_step=0.5, n_eval=1200)
        self._assert_energy_balance(results)


class BedRetentionPhysicsTests(unittest.TestCase):
    def test_capillary_head_sets_the_retained_bed_fraction(self):
        """
        What: Young-Laplace 保水頭 ≥ 床高 ⇒ 整床都能保水（f_retain = 1）。
        Why:  這是「immobile 池容量有多大」的判別式，由 measured PSD 直接決定，
              不是可調 closure；一旦 PSD 或 h_bed 改到讓它翻轉（粗研磨），
              f_retain 會連續地 < 1，敘事必須跟著改。
        """
        params = V60Params.for_roast(RoastProfile.LIGHT)
        self.assertGreater(float(params.h_cap_bed(params.T_brew)), params.h_bed)
        self.assertAlmostEqual(params.bed_retention_fraction(params.T_brew), 1.0, places=12)

    def test_bed_head_comes_from_the_mobile_column_only(self):
        """
        What: 床內高程頭正比於 mobile 飽和度：S_mob = 1 → h_bed；S_mob = 0 → 0。
        Why:  F2 把毛細保水頭從穿床梯度裡扣掉（h_bed_drive ≡ 0），
              逼得 k 必須上調 4.5× 仍配不上量測。床層兩端的水頭差由邊界條件決定，
              毛細保水只決定殘餘飽和度（= V_imm 容量），不是梯度。
        """
        params = V60Params.for_roast(RoastProfile.LIGHT)
        full = params.bed_drive_components(0.0, T_K=params.T_brew, t_sec=999.0, sat=1.0)
        self.assertAlmostEqual(float(full["h_bed_drive"]), params.h_bed, places=12)
        empty = params.bed_drive_components(0.0, T_K=params.T_brew, t_sec=999.0, sat=0.0)
        self.assertAlmostEqual(float(empty["h_bed_drive"]), 0.0, places=12)

    def test_corey_residual_is_structurally_zero(self):
        """殘餘飽和度已由 `V_imm` 顯式攜帶，`kr` 不得再留一份常數 s_r。"""
        params = V60Params.for_roast(RoastProfile.LIGHT)
        self.assertEqual(float(params.sat_rel_perm_residual), 0.0)

    def test_immobile_pool_never_drains_but_mobile_pool_does(self):
        """
        What: V_imm 全程單調不減；而剛潤濕的床在悶蒸暫停期會排出 mobile 水。
        Why:  這兩件事正是 measured retained_mass_g 的內容
              （t = 10 → 30 s 床內淨排出 24 mL，t = 142 s 保水卻升到 52 g）。
              少了任何一邊，模型就退回 F2「床層永遠不排乾」或舊版「沒有 hold-up」。
        """
        params = V60Params.for_roast(RoastProfile.LIGHT)
        protocol = PourProtocol.standard_v60()
        results = simulate_brew(params, protocol, t_end=180, max_step=0.5)
        v_imm = np.asarray(results["V_imm_ml"], dtype=float)
        # dV_imm/dt = C_imm ≥ 0 為結構性質；門檻留給 RK45 的局部誤差（實測 ~1e-3 mL）
        self.assertGreaterEqual(float(np.min(np.diff(v_imm))), -1e-2)

        t = np.asarray(results["t"], dtype=float)
        v_mob = np.asarray(results["V_mob_ml"], dtype=float)
        bloom_end = float(results["bloom_end_s"])
        window = (t >= bloom_end) & (t <= bloom_end + 25.0)
        self.assertTrue(np.any(window))
        self.assertGreater(float(np.max(v_mob[window]) - v_mob[window][-1]), 1.0)


if __name__ == "__main__":
    unittest.main()
