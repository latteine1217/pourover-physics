"""
test_fitting_loss.py — σ 正規化 χ² 的單位一致性與結構性質

What:
    釘住 loss 契約：
      1. 每一項都以量測 σ 正規化（把預測整體平移 1σ → χ² 增量 = N）
      2. velocity 項、phys_penalty 與 retention 時序項都不在 loss 裡
      3. PSD prior 在 anchor 上為 0、偏離 1 dex 為 (1/σ_dex)²
      4. stage 7 在水力 V_out 偏差 > 5% 時跳過
      5. multi-start warm-start 只讀該 case 自己目錄的 summary
      6. F6b 自由度配置：live 集合、dof 計數、LHS 起點、量測標註與品質旗標

Why:
    每一條都對應一個已被審計證實的失效模式；用測試釘住比寫進 docstring
    有效——舊實作的 velocity 項、phys_penalty 與 retention 項都有註解說它們
    在做什麼，但 velocity 是 V 殘差的差分罰、phys_penalty 恆為 0、
    retention 是 V_out 殘差的線性重排。三者都「看起來是獨立的一項」。
"""

import math
import unittest
from pathlib import Path

import numpy as np

from pour_over import fitting
from pour_over.fitting import (
    EXTRACTION_FIT_PARAMS,
    MEASUREMENT_SIGMA,
    SAT_REL_PERM_EXP_BOUNDS,
    SAT_REL_PERM_EXP_INIT,
    SAT_REL_PERM_EXP_PRIOR,
    SAT_REL_PERM_EXP_PRIOR_SIGMA_DEX,
    STAGE7_V_OUT_TOLERANCE,
    TAU_LAG_FIXED_S,
    U_LIQUID_DRIPPER_PRIOR_SIGMA_DEX,
    U_LIQUID_DRIPPER_PRIOR_W_M2K,
    _prepare_measured_case,
    _sibling_summary_row,
    residual_diagnostics,
)

# F10（2026-09-27）：canonical = kinu29 4:12（loader 自動改讀影片版 profile）；
# kinu29 4:11 是無錄影的紀錄表 case，特定於其紀錄內容的測試改用 `LOG_411_CSV`。
CANONICAL_CSV = Path("data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv")
CANONICAL_SUMMARY_PATH = Path("data/kinu_29_light/4:12/kinu29_light_20g_flow_fit_summary.csv")
LOG_411_CSV = Path("data/kinu_29_light/4:11/kinu29_light_20g_flow_profile.csv")
KINU27_CSV = Path("data/kinu_27_light/4:12/kinu27_light_20g_flow_profile.csv")


class TestChi2Units(unittest.TestCase):
    """χ² 各項的單位一致性：用合成殘差直接驗算，不需要跑模擬。"""

    def _chi2_terms(self, v_pred, v_obs, mask, sigma):
        return float(np.sum(((v_pred[mask] - v_obs[mask]) / sigma) ** 2))

    def test_one_sigma_shift_gives_chi2_equals_n(self):
        """把預測整體平移 1σ_V → volume 項 χ² 增量剛好等於 N（定義驗算）。"""
        case = _prepare_measured_case(CANONICAL_CSV)
        v_obs = case["v_out_obs"]
        mask = case["fit_mask"]
        sigma = MEASUREMENT_SIGMA["v_out_ml"]
        n = int(np.sum(mask))

        chi2_perfect = self._chi2_terms(v_obs.copy(), v_obs, mask, sigma)
        chi2_shifted = self._chi2_terms(v_obs + sigma, v_obs, mask, sigma)
        self.assertAlmostEqual(chi2_perfect, 0.0, places=12)
        self.assertAlmostEqual(chi2_shifted - chi2_perfect, float(n), places=9)

    def test_retention_sigma_is_diagnostic_only(self):
        """
        σ_ret 仍在表上（診斷圖的 ±1σ 帶要用），但 retention **不進 χ²**。

        Why（F6b）：四個 case 的 `retained_mass_g` 逐列等於 `poured − drained`，
        因此保水殘差是 V_out 殘差的線性重排。計進 χ² 等於把同一條殘差罰兩次
        （有效 σ_V 變成 3.0/√2 ≈ 2.12），並讓 n_obs 虛增、dof 算錯。
        """
        self.assertIn("retention_ml", MEASUREMENT_SIGMA)
        self.assertGreater(MEASUREMENT_SIGMA["retention_ml"], 0.0)
        src = Path(fitting.__file__).read_text(encoding="utf-8")
        self.assertNotIn('terms["retention"]', src)

    def test_retained_mass_is_algebraically_derived(self):
        """
        釘住 F6b 的事實前提：量測保水 ≡ poured − drained。

        Why 要測：整條「retention 不進 loss」的推理建立在這個代數恆等式上。
        若日後有人補了 dripper 淨重時序（真正的獨立觀測），這條測試會失敗，
        那正是「該把 retention 以自己的 σ 加回 χ²」的訊號——而不是把測試改掉。
        """
        for csv_path in (CANONICAL_CSV, KINU27_CSV, LOG_411_CSV):
            if not csv_path.exists():
                continue
            case = _prepare_measured_case(csv_path)
            # 用 CSV 的原始 `poured_weight_g`（`raw_prof`），不是預處理後的值
            # （F9 預處理會單調化 poured 並重建超上限注水，保水隨之以修正值重算）。
            raw = case["raw_prof"]
            derived = (np.asarray(raw["v_in_ml"], dtype=float)
                       - np.asarray(raw["v_out_ml"], dtype=float))
            self.assertLess(float(np.max(np.abs(
                np.asarray(raw["retained_mass_g"], dtype=float) - derived))), 1e-9,
                            f"{csv_path} 的保水已不是 poured - drained，"
                            f"請重新評估 retention 是否該回到 χ²")

    def test_tds_term_is_mass_based(self):
        """TDS 以質量比較：σ_Mext = σ_TDS × V_out_obs[L]，單位為 g。"""
        v_out_obs_L = 0.250
        sigma_m = MEASUREMENT_SIGMA["tds_gl"] * v_out_obs_L
        # 偏一個 σ_TDS 的濃度誤差 → χ² 剛好 1
        m_obs = 11.56 * v_out_obs_L
        m_pred = (11.56 + MEASUREMENT_SIGMA["tds_gl"]) * v_out_obs_L
        self.assertAlmostEqual(((m_pred - m_obs) / sigma_m) ** 2, 1.0, places=12)

    def test_all_sigmas_documented_and_positive(self):
        for key in ("v_out_ml", "stop_time_s", "cup_temp_C", "tds_gl", "retention_ml"):
            self.assertIn(key, MEASUREMENT_SIGMA)
            self.assertGreater(MEASUREMENT_SIGMA[key], 0.0)


class TestRemovedTerms(unittest.TestCase):
    """velocity 項與 phys_penalty 必須從 loss 中消失。"""

    def test_no_velocity_term_in_chi2(self):
        src = Path(fitting.__file__).read_text(encoding="utf-8")
        # velocity 只能作為診斷指標出現，不得進入 chi2_terms
        self.assertNotIn('terms["velocity"]', src)
        self.assertNotIn('terms["velocity_rmse"]', src)

    def test_no_phys_penalty(self):
        src = Path(fitting.__file__).read_text(encoding="utf-8")
        # 只准出現在說明為何移除它的註解/docstring 裡，不得是可執行的賦值
        self.assertNotIn("phys_penalty +=", src)
        self.assertNotIn("phys_penalty = 0.0", src)

    def test_velocity_rmse_is_reported_as_diagnostic(self):
        """q_RMSE 仍要回報（診斷），只是不進 loss。"""
        src = Path(fitting.__file__).read_text(encoding="utf-8")
        self.assertIn('"velocity_rmse"', src)


class TestPsdPrior(unittest.TestCase):
    """PSD prior 的數值契約。"""

    SIGMA_DEX = 0.30

    def _prior(self, k_beta, anchor, sigma_dex):
        return ((math.log10(k_beta) - math.log10(anchor)) / sigma_dex) ** 2

    def test_zero_at_anchor(self):
        self.assertAlmostEqual(self._prior(2353.0, 2353.0, self.SIGMA_DEX), 0.0, places=12)

    def test_one_dex_offset(self):
        """偏離 1 dex 時 prior = (1/0.3)²。"""
        val = self._prior(23530.0, 2353.0, self.SIGMA_DEX)
        self.assertAlmostEqual(val, (1.0 / 0.30) ** 2, places=9)

    def test_u_prior_contract(self):
        """U 的 prior：中心 194 W/m²K、σ 0.20 dex。"""
        self.assertAlmostEqual(U_LIQUID_DRIPPER_PRIOR_W_M2K, 194.0, places=9)
        self.assertAlmostEqual(U_LIQUID_DRIPPER_PRIOR_SIGMA_DEX, 0.20, places=9)
        val = ((math.log10(1940.0) - math.log10(194.0)) / 0.20) ** 2
        self.assertAlmostEqual(val, (1.0 / 0.20) ** 2, places=9)

    def test_sat_rel_perm_exp_prior_contract(self):
        """sat_rel_perm_exp 的 prior：中心 3.0、σ 0.20 dex（F6b 起的 live 參數）。"""
        self.assertAlmostEqual(SAT_REL_PERM_EXP_PRIOR, 3.0, places=9)
        self.assertAlmostEqual(SAT_REL_PERM_EXP_PRIOR_SIGMA_DEX, 0.20, places=9)
        self.assertAlmostEqual(
            ((math.log10(30.0) - math.log10(3.0)) / 0.20) ** 2,
            (1.0 / 0.20) ** 2, places=9)
        # 起點必須落在 bounds 內，bounds 是 Corey 指數的物理區間
        self.assertEqual(SAT_REL_PERM_EXP_BOUNDS, (1.5, 6.0))
        self.assertGreaterEqual(SAT_REL_PERM_EXP_INIT, SAT_REL_PERM_EXP_BOUNDS[0])
        self.assertLessEqual(SAT_REL_PERM_EXP_INIT, SAT_REL_PERM_EXP_BOUNDS[1])
        # `params.relative_permeability` 對指數取 max(n, 1.0) 硬底；
        # 下界若 <= 1.0，該段格點會完全沒有響應（假性「不可識別」）。
        self.assertGreater(SAT_REL_PERM_EXP_BOUNDS[0], 1.0)

    def test_tau_lag_is_frozen_without_prior_term(self):
        """
        F6b：tau_lag 退出 fit，凍結為 Class B 幾何常數，且 χ² 不再帶它的 prior 項。

        Why 要釘住「沒有 prior 項」：對凍結值加 prior 只是往每次 evaluate 加一個
        常數（中心 1.0 s vs 凍結值 0.5 s → +1.01）。那個常數不是資料也不是約束，
        卻會讓所有 χ² 與 F6 之前的數字無法比較，而且靜默。
        """
        self.assertAlmostEqual(TAU_LAG_FIXED_S, 0.5, places=9)
        lo, hi = fitting.TAU_LAG_BOUNDS_S
        self.assertGreaterEqual(TAU_LAG_FIXED_S, lo)
        self.assertLessEqual(TAU_LAG_FIXED_S, hi)
        src = Path(fitting.__file__).read_text(encoding="utf-8")
        self.assertNotIn('prior_terms["tau_lag"]', src)


class TestStage7Gate(unittest.TestCase):
    """stage 7 的水力自洽前置條件。"""

    def test_tolerance_is_five_percent(self):
        self.assertAlmostEqual(STAGE7_V_OUT_TOLERANCE, 0.05, places=12)

    def test_gate_logic(self):
        """|ΔV_out| / V_out > 5% → 跳過；否則允許。"""
        for v_model, v_obs, should_skip in (
            (250.0, 250.0, False),
            (260.0, 250.0, False),     # 4.0%
            (263.0, 250.0, True),      # 5.2%
            (272.5, 250.0, True),      # 9.0%（AUD 觀測到的實際偏差）
        ):
            mismatch = abs(v_model - v_obs) / abs(v_obs)
            self.assertEqual(mismatch > STAGE7_V_OUT_TOLERANCE, should_skip,
                             msg=f"v_model={v_model}")

    def test_max_ey_not_in_fit_params(self):
        """max_EY 已凍結為 roast prior，不得出現在 EXTRACTION_FIT_PARAMS。"""
        names = [n for n, *_ in EXTRACTION_FIT_PARAMS]
        self.assertNotIn("max_EY", names)

    def test_extraction_params_come_from_params_spec(self):
        """EXTRACTION_FIT_PARAMS 必須由 params.EXTRACTION_FIT_SPEC 推導（單一來源）。"""
        from pour_over.params import EXTRACTION_FIT_SPEC
        derived = [(n, t, lo, hi) for n, t, lo, hi, *_ in EXTRACTION_FIT_SPEC]
        self.assertEqual(EXTRACTION_FIT_PARAMS, derived)

    def test_extraction_priors_use_spec_center_and_sigma(self):
        """spec 的第 5/6 欄必須真的進 χ²，而不是只被讀進來放著。"""
        from pour_over.fitting import EXTRACTION_FIT_PRIORS
        from pour_over.params import EXTRACTION_FIT_SPEC
        for spec in EXTRACTION_FIT_SPEC:
            if len(spec) >= 6 and spec[1] == "log10" and float(spec[5]) > 0.0:
                self.assertIn(spec[0], EXTRACTION_FIT_PRIORS)
                center, sigma = EXTRACTION_FIT_PRIORS[spec[0]]
                self.assertAlmostEqual(center, float(spec[4]), places=12)
                self.assertAlmostEqual(sigma, float(spec[5]), places=12)
        # prior 在中心為 0、偏離 1σ_dex 為 1
        for name, (center, sigma) in EXTRACTION_FIT_PRIORS.items():
            at_center = ((math.log10(center) - math.log10(center)) / sigma) ** 2
            one_sigma = ((math.log10(center * 10 ** sigma) - math.log10(center)) / sigma) ** 2
            self.assertAlmostEqual(at_center, 0.0, places=12)
            self.assertAlmostEqual(one_sigma, 1.0, places=9)

    def test_params_in_spec_exist_on_the_model(self):
        """表上的參數應真的是 V60Params 的欄位（不同步時 stage 7 會跳過並記錄）。"""
        from pour_over.params import V60Params
        p = V60Params()
        missing = [n for n, *_ in EXTRACTION_FIT_PARAMS if not hasattr(p, n)]
        self.assertEqual(missing, [], msg=f"EXTRACTION_FIT_PARAMS 與模型不同步：{missing}")

    def test_extraction_fit_params_shape(self):
        """表格格式：(name, transform, lo, hi)，transform 只能是 log10/linear。"""
        for spec in EXTRACTION_FIT_PARAMS:
            self.assertEqual(len(spec), 4)
            name, transform, lo, hi = spec
            self.assertIsInstance(name, str)
            self.assertIn(transform, ("log10", "linear"))
            self.assertLess(lo, hi)


class TestWarmStart(unittest.TestCase):
    """multi-start 的 warm-start 必須讀 case 自己的目錄。"""

    @unittest.skipUnless(KINU27_CSV.exists(), "kinu27 case 不存在")
    def test_kinu27_reads_kinu27_directory(self):
        row = _sibling_summary_row(KINU27_CSV)
        self.assertIsNotNone(row)
        self.assertIn("kinu_27_light", row["csv_path"])

    @unittest.skipUnless(CANONICAL_CSV.exists(), "canonical case 不存在")
    def test_canonical_reads_its_own_directory(self):
        row = _sibling_summary_row(CANONICAL_CSV)
        self.assertIsNotNone(row)
        self.assertIn("kinu_29_light/4:12", row["csv_path"])

    @unittest.skipUnless(KINU27_CSV.exists() and CANONICAL_CSV.exists(), "cases 不齊")
    def test_two_cases_do_not_share_warm_start(self):
        a = _sibling_summary_row(KINU27_CSV)
        b = _sibling_summary_row(CANONICAL_CSV)
        self.assertNotEqual(float(a["k_fit"]), float(b["k_fit"]))


class TestF2bIntegration(unittest.TestCase):
    """F2b（mobile/immobile + tau_wet_s）在 fitting 端的契約。"""

    def test_tau_wet_bounds_and_start(self):
        from pour_over.fitting import TAU_WET_BOUNDS_S, TAU_WET_INIT_S
        self.assertEqual(TAU_WET_BOUNDS_S, (10.0, 60.0))
        self.assertGreaterEqual(TAU_WET_INIT_S, TAU_WET_BOUNDS_S[0])
        self.assertLessEqual(TAU_WET_INIT_S, TAU_WET_BOUNDS_S[1])

    def test_tau_wet_is_a_params_field(self):
        """core/params 已帶 tau_wet_s → stage 1/2 會把它納入聯合擬合。"""
        from pour_over.params import V60Params
        self.assertTrue(hasattr(V60Params(), "tau_wet_s"))

    def test_sat_rel_perm_residual_default_is_zero(self):
        """F2b：殘餘飽和由 V_imm 顯式攜帶，Corey 的 S_r 必須是 0。"""
        from pour_over.params import V60Params
        self.assertEqual(float(V60Params().sat_rel_perm_residual), 0.0)

    def test_legacy_sat_rel_perm_residual_not_reloaded(self):
        """舊 summary 的 0.18 不得覆蓋新預設（否則保水被記兩次）。"""
        import csv as _csv
        from pour_over.benchmark import _summary_path_for, _load_measured_benchmark_state
        summ = _summary_path_for(CANONICAL_CSV)
        with summ.open(encoding="utf-8") as f:
            row = next(_csv.DictReader(f))
        legacy = float(row.get("sat_rel_perm_residual_fit") or 0.0)
        if legacy == 0.0:
            self.skipTest("summary 已無舊值，無可驗證的迴歸")
        p_fit, _ = _load_measured_benchmark_state(
            CANONICAL_CSV, summ, refit=False, verbose=False)
        self.assertEqual(float(p_fit.sat_rel_perm_residual), 0.0)

    def test_paper_holdup_is_class_b_constant(self):
        """濾紙/杯壁 hold-up 是揭露的量測常數，不是 fit 參數。"""
        from pour_over.measured_io import MEASURED_PAPER_HOLDUP_ML
        from pour_over.fitting import EXTRACTION_FIT_PARAMS
        # 2026-09-24：無獨立秤重前固定 0.0（見 measured_io 註解）；上界仍守住量級。
        self.assertGreaterEqual(MEASURED_PAPER_HOLDUP_ML, 0.0)
        self.assertLess(MEASURED_PAPER_HOLDUP_ML, 20.0)
        names = [n for n, *_ in EXTRACTION_FIT_PARAMS]
        self.assertNotIn("V_holdup_paper_ml", names)
        self.assertNotIn("MEASURED_PAPER_HOLDUP_ML", names)

    def test_dof_counts_four_live_params(self):
        """
        F6d live 集合：k, sat_rel_perm_exp, tau_wet, lambda_server + 萃取端。

        `k_beta`（凍結為 PSD prior）、`tau_lag`（凍結為 TAU_LAG_FIXED_S）與
        `U_liquid_dripper`（F6d 凍結為 prior 中心）不計入：凍結參數不消耗自由度，
        算進 dof 會系統性低估 reduced χ²。
        """
        from pour_over.fitting import DEFAULT_LIVE_PARAM_COUNT, EXTRACTION_FIT_PARAMS
        self.assertEqual(DEFAULT_LIVE_PARAM_COUNT, 4 + len(EXTRACTION_FIT_PARAMS))

    def test_u_liquid_dripper_is_frozen_at_prior(self):
        """
        F6d：U 凍結在 prior 中心（CI None/None、thermal identifiability weak）。

        凍結在中心上 → χ² 的 U prior 項恆為 0，不會在 stage 間比較時偷偷加常數。
        """
        from pour_over.fitting import U_LIQUID_DRIPPER_FIXED_W_M2K
        self.assertEqual(U_LIQUID_DRIPPER_FIXED_W_M2K, U_LIQUID_DRIPPER_PRIOR_W_M2K)
        lo, hi = fitting.U_LIQUID_DRIPPER_BOUNDS_W_M2K
        self.assertLessEqual(lo, U_LIQUID_DRIPPER_FIXED_W_M2K)
        self.assertLessEqual(U_LIQUID_DRIPPER_FIXED_W_M2K, hi)

    @unittest.skipUnless(CANONICAL_SUMMARY_PATH.exists(), "canonical summary 不存在")
    def test_thermal_only_carry_matches_summary(self):
        """
        thermal-only 重擬讀回的固定值與 live 旗標必須與 summary 同源（F6d）。

        Why: 固定值與「它們當初是不是自由度」若來自不同地方，dof 會與參數值脫鉤；
             這條測試釘住兩者都從同一列 summary 導出。
        """
        import csv
        with CANONICAL_SUMMARY_PATH.open(encoding="utf-8") as f:
            row = next(csv.DictReader(f))
        carry = fitting._read_thermal_only_carry(CANONICAL_SUMMARY_PATH)
        self.assertEqual(carry["params"]["k"], float(row["k_fit"]))
        self.assertEqual(carry["params"]["tau_wet_s"], float(row["tau_wet_s_fit"]))
        self.assertEqual(carry["params"]["sat_rel_perm_exp"], float(row["sat_rel_perm_exp_fit"]))
        live = row["fit_live_param_names"].split(";")
        self.assertEqual(carry["ext_live"], any(n in live for n, *_ in EXTRACTION_FIT_PARAMS))
        self.assertEqual(carry["pref_live"], "pref_flow_coeff" in live)
        for name, *_ in EXTRACTION_FIT_PARAMS:
            self.assertIn(name, carry["params"])


class TestResidualDiagnostics(unittest.TestCase):
    """殘差結構檢定的行為驗算。"""

    def test_white_noise(self):
        rng = np.random.default_rng(0)
        d = residual_diagnostics(rng.normal(size=400))
        self.assertLess(abs(d["lag1"]), 0.15)
        self.assertGreater(d["durbin_watson"], 1.7)
        self.assertLess(abs(d["runs_z"]), 3.0)

    def test_strongly_autocorrelated(self):
        """單調漂移 → lag1 → 1、DW → 0、runs_z 明顯為負。"""
        d = residual_diagnostics(np.linspace(-10.0, 10.0, 60))
        self.assertGreater(d["lag1"], 0.9)
        self.assertLess(d["durbin_watson"], 0.2)
        self.assertLess(d["runs_z"], -5.0)

    def test_alternating(self):
        """交替符號 → 負自相關、DW → 4、runs_z 明顯為正。"""
        d = residual_diagnostics(np.array([1.0, -1.0] * 30))
        self.assertLess(d["lag1"], -0.9)
        self.assertGreater(d["durbin_watson"], 3.8)
        self.assertGreater(d["runs_z"], 5.0)

    def test_too_short(self):
        d = residual_diagnostics(np.array([1.0, 2.0]))
        self.assertTrue(math.isnan(d["lag1"]))


class TestSolverPresets(unittest.TestCase):
    """具名 solver preset：全專案只准有這兩組。"""

    def test_presets_have_required_keys(self):
        for preset in (fitting.SOLVER_COARSE, fitting.SOLVER_FINE):
            for key in ("n_eval", "rtol", "atol", "max_step"):
                self.assertIn(key, preset)

    def test_fine_differs_from_coarse_only_in_output_grid(self):
        """
        F6c 契約變更：兩組 preset 的**誤差控制必須完全相同**。

        Why: 舊契約只要求 fine 比 coarse 嚴，於是 coarse 的 rtol 3e-5 讓 RK45 的
             自適應步長選擇進入目標函數，χ² 表面帶 ±20–30 的噪音（見
             `fitting.SOLVER_COARSE` 的 Why 與 `tests/test_chi2_smoothness.py`）。
             現在兩組只差觀測層輸出網格 `n_eval`，coarse 與 fine 量的是同一個
             χ² 函數，stage 門檻與 CI 交點才有意義。
        """
        self.assertGreater(fitting.SOLVER_FINE["n_eval"], fitting.SOLVER_COARSE["n_eval"])
        for key in ("rtol", "atol", "max_step"):
            self.assertEqual(fitting.SOLVER_FINE[key], fitting.SOLVER_COARSE[key], msg=key)


class TestMeasuredCaseIngest(unittest.TestCase):
    """case bundle 必須帶齊新 loss 需要的觀測量。"""

    @unittest.skipUnless(LOG_411_CSV.exists(), "kinu29 4:11 case 不存在")
    def test_case_has_retention_and_read_time(self):
        from pour_over.measured_io import SCALE_TIMER_RATE
        case = _prepare_measured_case(LOG_411_CSV)
        self.assertEqual(case["retained_obs"].shape, case["t_obs"].shape)
        self.assertEqual(case["retention_basis"], "measured")
        # kinu29 4:11 的 dripper_off_final 在秤計時器 142 s（F10：換算真實秒 = 142 / 1.0186）
        r = SCALE_TIMER_RATE
        self.assertAlmostEqual(case["final_temp_read_time_s"], 142.0 / r, places=9)
        # 停流目視時刻來自 flow_stop_visual（計時器 135 s），該列 use_for_fit = 0
        self.assertAlmostEqual(case["stop_flow_time_s"], 135.0 / r, places=9)
        idx135 = int(np.argmin(np.abs(case["t_obs"] - 135.0 / r)))
        idx142 = int(np.argmin(np.abs(case["t_obs"] - 142.0 / r)))
        self.assertFalse(bool(case["fit_mask"][idx135]))
        self.assertTrue(bool(case["fit_mask"][idx142]))


class TestF6bDofReallocation(unittest.TestCase):
    """
    F6b 自由度重配的契約。

    Why 這一組要用測試釘住：自由度配置是「哪些參數在被擬」與「資料分不分得出
    它們」的對應關係。這個對應一旦漂掉，loss 照樣會下降、圖照樣會畫出來，
    沒有任何回歸訊號——F6 §6.1 就是靠人工比對兩張表才發現 `k_beta`/`tau_lag`
    （weak）在 fit 裡、`sat_rel_perm_exp`（hard）卻被凍結。
    """

    def test_identifiability_live_set_matches_fitting(self):
        """identifiability 的 `FIT_LIVE_PARAMS` 必須與 fitting 的 live 集合一致。"""
        from pour_over.identifiability import FIT_LIVE_PARAMS
        expected = {
            "k", "sat_rel_perm_exp", "tau_wet_s",
            "lambda_server_ambient",
            *(n for n, *_ in EXTRACTION_FIT_PARAMS),
        }
        self.assertEqual(set(FIT_LIVE_PARAMS), expected)
        # 凍結參數不得出現在 live 集合
        self.assertNotIn("k_beta", FIT_LIVE_PARAMS)
        self.assertNotIn("tau_lag_s", FIT_LIVE_PARAMS)
        self.assertNotIn("U_liquid_dripper_W_m2K", FIT_LIVE_PARAMS)
        # live 集合大小必須等於 dof 用的計數
        self.assertEqual(len(FIT_LIVE_PARAMS), fitting.DEFAULT_LIVE_PARAM_COUNT)

    def test_lhs_starts_are_reproducible_and_spread(self):
        """固定 seed → 同一組起點；且每個維度都真的分散（LHS 的全部意義）。"""
        a = fitting._latin_hypercube_starts(fitting.MULTI_START_LHS_N,
                                            fitting.MULTI_START_SEED)
        b = fitting._latin_hypercube_starts(fitting.MULTI_START_LHS_N,
                                            fitting.MULTI_START_SEED)
        self.assertEqual(fitting.MULTI_START_LHS_N, 2)
        self.assertEqual([p.k for p in a], [p.k for p in b])
        self.assertEqual([p.sat_rel_perm_exp for p in a], [p.sat_rel_perm_exp for p in b])
        for p in a:
            self.assertGreaterEqual(p.k, fitting.MULTI_START_K_RANGE_M2[0])
            self.assertLessEqual(p.k, fitting.MULTI_START_K_RANGE_M2[1])
            self.assertGreaterEqual(p.sat_rel_perm_exp, fitting.SAT_REL_PERM_EXP_BOUNDS[0])
            self.assertLessEqual(p.sat_rel_perm_exp, fitting.SAT_REL_PERM_EXP_BOUNDS[1])
            self.assertGreaterEqual(p.tau_wet_s, fitting.MULTI_START_TAU_WET_RANGE_S[0])
            self.assertLessEqual(p.tau_wet_s, fitting.MULTI_START_TAU_WET_RANGE_S[1])
        # 分層性質：每個維度的 n 個值必須落在 n 個不同的等寬層裡
        n = fitting.MULTI_START_LHS_N
        for lo, hi, vals, logspace in (
            (*fitting.MULTI_START_K_RANGE_M2, [p.k for p in a], True),
            (*fitting.SAT_REL_PERM_EXP_BOUNDS, [p.sat_rel_perm_exp for p in a], True),
            (*fitting.MULTI_START_TAU_WET_RANGE_S, [p.tau_wet_s for p in a], False),
        ):
            if logspace:
                u = [(math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
                     for v in vals]
            else:
                u = [(v - lo) / (hi - lo) for v in vals]
            self.assertEqual(sorted(min(int(x * n), n - 1) for x in u), list(range(n)))

    def test_sat_rel_perm_exp_is_in_cache_key(self):
        """
        live 參數必須進 loss cache key。

        Why：漏掉的話 Powell 沿該方向的每一步都會命中同一筆 cache 而拿回舊 χ²，
        於是那個參數看起來「完全沒有影響」，optimizer 直接把它留在起點上——
        一個不會 crash、不會報錯、只會靜默把自由度變回凍結的 bug。
        """
        src = Path(fitting.__file__).read_text(encoding="utf-8")
        head, _, _ = src.partition("def _accept(")
        _, _, key_block = head.rpartition("key = tuple(")
        self.assertIn('"sat_rel_perm_exp"', key_block)
        self.assertIn('"tau_wet_s"', key_block)


class TestDataQualityFlags(unittest.TestCase):
    """
    量測紀錄品質旗標的契約（F6b；F10 起分紀錄表 / 影片版兩組）。

    Why：這些旗標是「這份紀錄能支持什麼結論」的界線，會一路進 summary /
    benchmark CSV 給 F7b 揭露。旗標算錯或消失都不會讓任何 gate 失敗，
    只會讓下游安靜地把受限 case 當成獨立驗證——因此必須有測試。

    F10：紀錄表（`source="log"`）一律帶 `drained_log_bias_suspected`——同一紀錄法的
    drained 欄經三支錄影證實悶蒸後偏高 13–73 mL。三個有錄影的 case 改讀影片版後，
    F6b 的 `no_ponding_recorded` / `no_post_pour_outflow` / `mass_balance_violation`
    應全部消失：它們是讀值誤差的指紋，不是沖煮本身的性質。
    """

    LOG_CASES = {
        "kinu29 4:11": (LOG_411_CSV, {"drained_log_bias_suspected"}),
        "kinu29 4:12": (Path("data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv"),
                        {"mass_balance_violation", "coarse_drained_resolution",
                         "no_equilibrium_row", "drained_log_bias_suspected"}),
        "kinu27 4:12": (Path("data/kinu_27_light/4:12/kinu27_light_20g_flow_profile.csv"),
                        {"no_post_pour_outflow", "no_ponding_recorded",
                         "coarse_drained_resolution", "drained_log_bias_suspected"}),
        "kinu28 4:20": (Path("data/kinu_28_light/4:20/kinu28_light_20g_flow_profile.csv"),
                        {"no_post_pour_outflow", "no_ponding_recorded",
                         "no_equilibrium_row", "drained_log_bias_suspected"}),
    }
    VIDEO_CASES = ("kinu29 4:12", "kinu27 4:12", "kinu28 4:20")

    def test_log_flags_match_the_audited_state(self):
        from pour_over.measured_io import load_flow_profile_csv
        for name, (path, expected) in self.LOG_CASES.items():
            if not path.exists():
                continue
            with self.subTest(case=name):
                got = set(load_flow_profile_csv(path, source="log")["data_quality_flags"])
                self.assertEqual(got, expected)

    def test_video_profiles_are_clean(self):
        """影片版 profile 不得帶任何 F6b 旗標（見 class docstring）。"""
        from pour_over.measured_io import load_flow_profile_csv
        for name in self.VIDEO_CASES:
            path = self.LOG_CASES[name][0]
            if not path.exists():
                continue
            with self.subTest(case=name):
                prof = load_flow_profile_csv(path)
                self.assertEqual(prof["profile_source"], "video")
                self.assertEqual(prof["data_quality_flags"], [])

    def test_flags_reach_the_case_bundle(self):
        """旗標必須進 case bundle，否則 summary / benchmark 拿不到。"""
        case = _prepare_measured_case(KINU27_CSV, source="log")
        self.assertIn("no_post_pour_outflow", case["data_quality_flags"])
        self.assertIn("drained_log_bias_suspected", case["data_quality_flags"])


class TestMeasurementAnnotation(unittest.TestCase):
    """量測標註（`use_for_fit`）的契約。"""

    KINU29_412 = Path("data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv")

    @unittest.skipUnless(KINU29_412.exists(), "kinu29 4:12 case 不存在")
    def test_mass_balance_violating_row_is_excluded(self):
        """
        F6b：kinu29 4:12 **紀錄表**的計時器 t = 130 s（drained 310 mL > poured 302.8 g，
        retained = −7.2 g）違反質量守恆，必須被標為 `use_for_fit = 0`。

        同時確認 `stop_flow_time_s` 仍取自該列——`use_for_fit` 管的是
        「這列的累積 V_out / 保水是否進殘差」，目視停流時刻是另一個觀測量。
        F10：紀錄表時間經秤計時器速率換算為真實秒（130 / 1.0186）。
        """
        from pour_over.measured_io import SCALE_TIMER_RATE
        case = _prepare_measured_case(self.KINU29_412, source="log")
        idx = int(np.argmin(np.abs(case["t_obs"] - 130.0 / SCALE_TIMER_RATE)))
        self.assertLess(float(case["retained_obs"][idx]), 0.0)
        self.assertFalse(bool(case["fit_mask"][idx]))
        self.assertAlmostEqual(case["stop_flow_time_s"], 130.0 / SCALE_TIMER_RATE, places=9)

    @unittest.skipUnless(KINU29_412.exists(), "kinu29 4:12 case 不存在")
    def test_no_negative_retention_survives_the_fit_mask(self):
        """任何 case（紀錄表與影片版）都不得讓「保水為負」的列進殘差。"""
        for csv_path in (CANONICAL_CSV, KINU27_CSV, self.KINU29_412, LOG_411_CSV):
            if not csv_path.exists():
                continue
            for source in ("auto", "log"):
                case = _prepare_measured_case(csv_path, source=source)
                masked = case["retained_obs"][case["fit_mask"]]
                self.assertTrue(bool(np.all(masked >= 0.0)),
                                f"{csv_path} ({source}) 仍有負保水列進入 fit")


if __name__ == "__main__":
    unittest.main()
