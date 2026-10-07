"""
萃取閉合（F3）的結構性不變量。

What:
    驗證「兩池 bin-resolved 一階釋放（Crank 球形擴散首項）」這條閉合的
    幾何自洽性、溫度相依方向、質量守恆與參數簡併的消失。

Why:
    AUD-3 的每一條發現都對應下面一個測試：
      - `exp(−L²/4Dt)` 漸近方向錯    → λ 必須 ∝ 1/L²，且與 t 無關
      - bin 相對速率次序被打亂        → λ_slow 必須隨 R_core 單調遞減
      - 溫度三重計數                  → D(T) 只剩 Stokes-Einstein 一條路徑
      - `max_EY` 與 `fast_fraction` 簡併 → M_sol_0 ≡ dose·max_EY（恆等，無縮放）
      - `nw_eta_*` 效率因子            → τ_tort = 1 時 λ 必須等於純幾何值
    這些是「閉合有沒有被改回補償式」的可證偽判據，不是數值回歸。
"""

import dataclasses
import unittest
from pathlib import Path

import numpy as np

from pour_over import PourProtocol, RoastProfile, V60Params, simulate_brew
from pour_over.constant import K_B, SOLUTE_RADIUS_FAST_M, SOLUTE_RADIUS_SLOW_M
from pour_over.params import EXTRACTION_FIT_SPEC
from pour_over.psd import DEFAULT_SHELL_THICKNESS_MM

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_BINS_CSV = PROJECT_ROOT / "data/kinu_29_light/4:12/kinu29_psd_bins.csv"   # F10：canonical = kinu29 4:12


def _canonical_params(**overrides) -> V60Params:
    """canonical kinu29 4:12 / light；overrides 在 `for_roast` **之後**套用。"""
    base = V60Params(psd_bins_csv_path=str(CANONICAL_BINS_CSV), h_bed=0.053)
    roasted = V60Params.for_roast(RoastProfile.LIGHT, base=base)
    return dataclasses.replace(roasted, **overrides) if overrides else roasted


@unittest.skipUnless(CANONICAL_BINS_CSV.exists(), "canonical PSD bins CSV 不存在")
class TestBinGeometry(unittest.TestCase):
    """δ_i / R_core,i / shell_acc_i 必須出自同一條幾何。"""

    def setUp(self):
        self.p = _canonical_params()

    def test_shell_depth_and_shell_fraction_are_consistent(self):
        """shell_acc_i ≡ 1 − (R_core,i / R_i)³ —— 質量分配與擴散長度不可各自調整。"""
        R = self.p.ext_bin_radius_m
        core = self.p.ext_bin_core_radius_m
        expect = 1.0 - (core / R) ** 3
        np.testing.assert_allclose(self.p.ext_bin_shell_fraction, expect, rtol=1e-12, atol=1e-12)

    def test_shell_depth_never_exceeds_radius(self):
        """δ_i ≤ R_i：舊實作的 200 μm 絕對 floor 會讓 bin0 出現 L_slow > R。"""
        self.assertTrue(np.all(self.p.ext_bin_shell_depth_m <= self.p.ext_bin_radius_m + 1e-18))
        self.assertTrue(np.all(self.p.ext_bin_core_radius_m >= 0.0))

    def test_shell_depth_is_min_of_shell_thickness_and_radius(self):
        """δ_i ≡ min(shell_thickness, R_i)：不得有任何額外的絕對 floor（AUD-3）。"""
        np.testing.assert_allclose(
            self.p.ext_bin_shell_depth_m,
            np.minimum(self.p.shell_thickness, self.p.ext_bin_radius_m),
            rtol=1e-12,
        )

    def test_shell_thickness_has_a_single_source(self):
        """params 與 psd 的殼層厚度必須是同一個常數（PSD 表的 shell 欄與模型同義）。"""
        self.assertAlmostEqual(
            V60Params().shell_thickness, DEFAULT_SHELL_THICKNESS_MM * 1e-3, places=15
        )

    def test_core_radius_floor_only_acts_where_slow_pool_is_empty(self):
        """R_core 的數值 floor 不得改變任何有質量的 bin。"""
        floored = self.p.ext_bin_core_radius_eff_m > self.p.ext_bin_core_radius_m + 1e-15
        # floor 生效的 bin，其 slow 池質量必須可忽略（shell_acc → 1）
        self.assertTrue(np.all(self.p.M_slow_0_bins[floored] < 1e-3 * self.p.M_sol_0))


@unittest.skipUnless(CANONICAL_BINS_CSV.exists(), "canonical PSD bins CSV 不存在")
class TestReleaseRates(unittest.TestCase):
    """λ 的尺度律、單調性與參數相依。"""

    def setUp(self):
        self.p = _canonical_params()
        self.T = float(self.p.T_brew)

    def test_lambda_equals_pure_geometry_when_tau_tort_is_one(self):
        """τ_tort = 1 ⇒ λ = π²·D(T)/L²，不得有任何殘留的效率因子。

        fast 池的 L 是**內面封閉殼層**的等效半長度 2δ（2026-09-24 約定），
        slow 池的 L 是核心球半徑。
        """
        p1 = dataclasses.replace(self.p, tau_tort=1.0)
        D_fast = K_B * self.T / (6.0 * np.pi * p1.mu_water(self.T) * SOLUTE_RADIUS_FAST_M)
        D_slow = K_B * self.T / (6.0 * np.pi * p1.mu_water(self.T) * SOLUTE_RADIUS_SLOW_M)
        np.testing.assert_allclose(
            p1.lambda_fast_bins(self.T),
            np.pi ** 2 * D_fast / (2.0 * p1.ext_bin_shell_depth_m) ** 2,
            rtol=1e-12,
        )
        np.testing.assert_allclose(
            p1.lambda_slow_bins(self.T),
            np.pi ** 2 * D_slow / p1.ext_bin_core_radius_eff_m ** 2,
            rtol=1e-12,
        )

    def test_lambda_fast_uses_sealed_face_shell_convention(self):
        """fast 池必須是 `π²D/(2δ)²`，不得退回整球約定 `π²D/δ²`（兩者差 4×）。

        Why: 這個 O(1) 因子與 `tau_tort` 完全簡併，靜默改動會讓 prior 中心 5.0
             與模型不同尺度，而 loss 不會有任何跡象。
        """
        whole_sphere = np.pi ** 2 * self.p.solute_diffusivity(self.T, slow=False) \
            / self.p.ext_bin_shell_depth_m ** 2
        np.testing.assert_allclose(
            self.p.lambda_fast_bins(self.T), whole_sphere / 4.0, rtol=1e-12
        )

    def test_lambda_slow_is_strictly_decreasing_in_core_radius(self):
        """λ_slow,i ∝ 1/R_core,i²：粗顆粒必須比細顆粒慢，且次序與 t 無關。"""
        lam = self.p.lambda_slow_bins(self.T)
        core = self.p.ext_bin_core_radius_eff_m
        order = np.argsort(core)
        self.assertTrue(np.all(np.diff(lam[order]) < 0.0))

    def test_tau_tort_acts_only_on_the_slow_pool(self):
        """τ_tort 是完整細胞壁的阻擋：λ_slow ∝ 1/τ_tort，λ_fast 與之無關。

        Why: fast 池是對孔隙液開放的破壁細胞層，溶質以自由溶液擴散離開；
             把細胞壁阻擋也套在 fast 池，等於宣稱破壁層仍有完整細胞壁。
        """
        p1 = dataclasses.replace(self.p, tau_tort=2.0)
        p2 = dataclasses.replace(self.p, tau_tort=8.0)
        np.testing.assert_allclose(
            p1.lambda_fast_bins(self.T), p2.lambda_fast_bins(self.T), rtol=1e-12
        )
        np.testing.assert_allclose(
            p1.lambda_slow_bins(self.T), 4.0 * p2.lambda_slow_bins(self.T), rtol=1e-12
        )

    def test_diffusivity_increases_with_temperature(self):
        """D(T) = k_B T /(6π μ(T) r) 必須隨 T 嚴格遞增（舊 ν_p·k_B·T 忽略 μ(T)）。"""
        temps = np.array([348.15, 358.15, 366.15, 373.15])
        for slow in (False, True):
            D = np.array([float(self.p.solute_diffusivity(T, slow=slow)) for T in temps])
            self.assertTrue(np.all(np.diff(D) > 0.0), msg=f"slow={slow}")

    def test_diffusivity_is_more_than_temperature_proportional(self):
        """真實 D ∝ T/μ(T)：升溫的增幅必須明顯大於單純 ∝ T 的舊式。"""
        T_lo, T_hi = 348.15, 373.15
        ratio = float(self.p.solute_diffusivity(T_hi) / self.p.solute_diffusivity(T_lo))
        self.assertGreater(ratio, 1.3 * (T_hi / T_lo))

    def test_slow_solute_diffuses_slower_than_fast(self):
        self.assertLess(
            float(self.p.solute_diffusivity(self.T, slow=True)),
            float(self.p.solute_diffusivity(self.T, slow=False)),
        )


@unittest.skipUnless(CANONICAL_BINS_CSV.exists(), "canonical PSD bins CSV 不存在")
class TestPoolMassSplit(unittest.TestCase):
    """兩池初始質量只由 PSD 幾何決定。"""

    def setUp(self):
        self.p = _canonical_params()

    def test_total_initial_mass_is_exactly_dose_times_max_ey(self):
        """M_sol_0 ≡ dose·max_EY：不得再有 fast_fraction / shell_ratio 的縮放。"""
        self.assertAlmostEqual(self.p.M_sol_0, self.p.dose_g * self.p.max_EY, places=12)
        self.assertAlmostEqual(
            float(np.sum(self.p.M_fast_0_bins) + np.sum(self.p.M_slow_0_bins)),
            self.p.M_sol_0, places=12,
        )

    def test_bin_split_follows_volume_fraction_times_shell_accessibility(self):
        M_total = self.p.dose_g * self.p.max_EY
        vol = self.p.ext_bin_volume_fraction
        shell = self.p.ext_bin_shell_fraction
        np.testing.assert_allclose(self.p.M_fast_0_bins, M_total * vol * shell, rtol=1e-12)
        np.testing.assert_allclose(self.p.M_slow_0_bins, M_total * vol * (1.0 - shell), rtol=1e-12)

    def test_max_ey_scales_both_pools_linearly(self):
        """max_EY 只縮放總量，不改變兩池比例（分配權在 PSD 手上）。"""
        doubled = _canonical_params(max_EY=2.0 * self.p.max_EY)
        self.assertAlmostEqual(
            doubled.fast_pool_mass_fraction, self.p.fast_pool_mass_fraction, places=12
        )
        self.assertAlmostEqual(doubled.M_sol_0 / self.p.M_sol_0, 2.0, places=12)

    def test_tau_tort_does_not_change_any_pool_mass(self):
        """速率參數不得偷偷改變可萃取總量（否則又與 max_EY 簡併）。"""
        other = _canonical_params(tau_tort=37.0)
        self.assertAlmostEqual(other.M_fast_0, self.p.M_fast_0, places=12)
        self.assertAlmostEqual(other.M_slow_0, self.p.M_slow_0, places=12)

    def test_shell_thickness_does_not_reach_hydraulics(self):
        """萃取殼層厚度不得改變任何堵塞 closure（萃取對水力單向耦合）。"""
        thick = _canonical_params(shell_thickness=200e-6)
        for got, ref in zip(self.p.clogging_bin_profiles(), thick.clogging_bin_profiles()):
            np.testing.assert_allclose(got, ref, rtol=1e-12)


@unittest.skipUnless(CANONICAL_BINS_CSV.exists(), "canonical PSD bins CSV 不存在")
class TestSoluteConservation(unittest.TestCase):
    """ODE 端的溶質守恆（含瞬時床內液量分母）。"""

    @classmethod
    def setUpClass(cls):
        p = _canonical_params(tau_tort=5.0)
        cls.params = p
        cls.res = simulate_brew(p, PourProtocol.standard_v60(), t_end=180, max_step=1.0)

    def test_balance_residual_is_bounded(self):
        """已溶出 = 入杯 + 床內液相 inventory（兩邊都用同一個瞬時液量）。"""
        resid = np.asarray(self.res["M_balance_residual_g"], dtype=float)
        self.assertTrue(np.all(np.isfinite(resid)))
        self.assertLess(float(np.max(np.abs(resid))), 5.0e-2)

    def test_dissolved_mass_never_exceeds_initial_pool(self):
        M_diss = np.asarray(self.res["M_dissolved_g"], dtype=float)
        self.assertLessEqual(float(np.max(M_diss)), self.params.M_sol_0 + 1e-9)
        self.assertGreaterEqual(float(np.min(M_diss)), -1e-9)

    def test_ey_cup_cannot_exceed_max_ey(self):
        """入杯 EY ≤ max_EY：超過代表閉合在憑空造溶質。"""
        ey = float(np.max(self.res["EY_cup_pct"]))
        self.assertLessEqual(ey, 100.0 * self.params.max_EY + 1e-6)

    def test_liquid_volume_denominator_is_time_varying(self):
        """濃度分母必須隨床內液量變化，不得是定容（悶蒸期會被系統性稀釋）。"""
        v = np.asarray(self.res["V_liq_layers_ml"], dtype=float)
        self.assertGreater(float(np.ptp(v[0])), 1.0)


class TestFitSpec(unittest.TestCase):
    """F3 → F4 的可擬參數介面。"""

    def test_single_live_extraction_parameter(self):
        self.assertEqual(len(EXTRACTION_FIT_SPEC), 1)
        name, transform, lo, hi, center, sigma_dex = EXTRACTION_FIT_SPEC[0]
        self.assertEqual(name, "tau_tort")
        self.assertEqual(transform, "log10")
        self.assertLess(lo, center)
        self.assertLess(center, hi)
        self.assertGreater(sigma_dex, 0.0)

    def test_lower_bound_is_the_physical_limit(self):
        """τ_tort < 1 代表顆粒內擴散快過自由水，物理上不可能。"""
        self.assertAlmostEqual(EXTRACTION_FIT_SPEC[0][2], 1.0, places=12)

    def test_frozen_legacy_extraction_knobs_are_gone(self):
        """舊的補償式旋鈕不得復活（它們與 τ_tort / max_EY 簡併）。"""
        p = V60Params()
        for name in (
            "k_ext_coef", "k_ext_fast_coef", "k_ext_slow_coef",
            "nw_eta_fast", "nw_eta_slow", "fast_fraction",
            "Ea_fast", "Ea_slow", "Ea_ext", "beta_access",
            "nu_p_fast", "nu_p_slow", "k_diff_ratio", "Q_half",
        ):
            self.assertFalse(hasattr(p, name), msg=name)


if __name__ == "__main__":
    unittest.main()
