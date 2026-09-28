"""
test_chi2_smoothness.py — χ² 表面在 SOLVER_COARSE 下必須平滑

What:
    對 canonical case（F10 起 kinu29 4:12，影片版量測）的發佈參數，在**擬合實際使用的**
    `SOLVER_COARSE` 下掃兩條線並檢查三件事：
      1. `k` 的 ±1% 微擾（5 點）：χ² 的二階差分絕對值 < 5
      2. 同一條線的相鄰點 |Δχ²| < 8
      3. `tau_tort`（顆粒內曲折度）掃描：χ² 的 **volume 項**變化 < 3
      4. `k` 的 ±1e-10 相對微擾：|Δχ²| < 1e-6（F13-C：ODE 在注水率斷點間分段積分前為 0.07–0.17）

Why:
    這三條不是精度測試，是**目標函數是否為函數**的測試。

    第 3 條是最乾淨的判別：`tau_tort` 只進萃取 closure，對水力沒有任何物理
    回饋，因此 volume 項（V_out 殘差）在數學上必須是常數。舊 preset
    （rtol 3e-5 / max_step 1.0）下它在 τ_tort ∈ {5, 6.5, 8, 10} 上跳了 39.4，
    唯一可能的來源是 RK45 的自適應步長選擇：萃取狀態的誤差估計參與了步長
    決策，於是水力解的離散化誤差隨一個與它無關的參數改變。

    第 1、2 條把同一件事寫成 optimizer 看得到的形式：噪音幅度 ±20–30 與
    multi-start 的 basin 間距（F6b §4.2 的 75）同級，而 stage 的接受門檻是
    Δχ² ≤ −1.0、profile CI 的交點是 Δχ² ≈ 3.84×reduced。在那樣的表面上
    「擬合」與「擲骰子」無法區分——F6/F6b 的 stage 7 誤拒、bounded Powell
    回傳高於起點、`hydraulic_converged=False` 都是它的症狀。

    門檻（5 / 8 / 3）取自實測：`SOLVER_FINE` 自己的二階差分最大值是 2.9，
    本 preset 是 2.7；留約 1.7 倍餘裕，既能擋回 ±20 的噪音，也不會因為
    solver 版本的微小差異而假警報。
"""

import unittest
from csv import DictReader
from dataclasses import replace
from pathlib import Path

from pour_over import fitting

REPO = Path(__file__).resolve().parents[1]
CANONICAL_CSV = REPO / fitting.DEFAULT_MEASURED_FLOW_CSV
CANONICAL_SUMMARY = REPO / fitting.DEFAULT_MEASURED_FLOW_FIT_SUMMARY

K_FACTORS = (0.99, 0.995, 1.0, 1.005, 1.01)
TAU_TORT_GRID = (5.0, 6.5, 8.0, 10.0)

MAX_SECOND_DIFF = 5.0        # |χ²(i−1) − 2χ²(i) + χ²(i+1)|
MAX_ADJACENT_DELTA = 8.0     # |χ²(i+1) − χ²(i)|，k 每步 0.5%
MAX_VOLUME_SPAN_VS_TAU_TORT = 3.0


def _canonical_state():
    """從發佈 summary 組出 canonical 參數與 χ² evaluate 所需的凍結量。

    Why 直接讀 summary 而不重擬：本測試要驗的是「在發佈解附近的 χ² 表面」，
    重擬會把 optimizer 的隨機性帶進來，而且跑不進 30 s 的預算。
    """
    from pour_over.benchmark import _load_measured_benchmark_state

    params, info = _load_measured_benchmark_state(
        CANONICAL_CSV, CANONICAL_SUMMARY, refit=False, verbose=False
    )
    with CANONICAL_SUMMARY.open(encoding="utf-8") as f:
        row = next(DictReader(f))
    return {
        "params": params,
        "case": fitting._prepare_measured_case(CANONICAL_CSV),
        "tau_lag_s": float(fitting.TAU_LAG_FIXED_S),
        "vessel_equivalent_ml": float(row["vessel_equivalent_ml"]),
        "k_beta_prior_psd": float(info.get("k_beta_prior_psd") or params.k_beta),
    }


@unittest.skipUnless(
    CANONICAL_CSV.exists() and CANONICAL_SUMMARY.exists(),
    "canonical case 或其 flow-fit summary 不存在",
)
class TestChi2SurfaceSmoothness(unittest.TestCase):
    """擬合用的 solver 必須給出平滑的 χ²（否則所有 Δχ² 門檻都失去意義）。"""

    @classmethod
    def setUpClass(cls):
        cls.state = _canonical_state()

    def _evaluate(self, params):
        st = self.state
        return fitting._chi2_evaluate(
            st["case"], params, st["tau_lag_s"],
            vessel_equivalent_ml=st["vessel_equivalent_ml"],
            solver=fitting.SOLVER_COARSE,
            k_beta_prior_psd=st["k_beta_prior_psd"],
            n_fit_params=fitting.DEFAULT_LIVE_PARAM_COUNT,
            keep_sim=False,
        )

    # F6e（2026-09-24）：SOLVER preset 已升級為 rtol 1e-7 / atol 1e-9，本測試在新 preset 下通過，
    # expectedFailure 已移除。發佈的四 case 參數仍是在 rtol 1e-6 表面上擬出的（未重擬，只重新評估）；
    # 下一輪 multi-start 應以新 preset 重擬。以下為歷史證據，保留供追溯：
    # 實測（F6c 發佈的 canonical 解，k=5.243e-11）：
    #   rtol 1e-6（現行 COARSE 與 FINE）  χ² = 375.33 374.31 368.30 370.56 368.95  |d2|max 8.3
    #   rtol 1e-7 / atol 1e-9            χ² = 370.97 369.42 368.04 367.13 366.13  |d2|max 0.47
    #   rtol 1e-8 / atol 1e-10（參考）   χ² = 370.08 368.51 367.28 366.34 365.65  |d2|max 0.34
    # 真實表面沿 k 單調下降；rtol 1e-6 仍有 ±3–6 的噪音，而 optimizer 恰好停在
    # 一個噪音凹陷上（在帶噪目標上最小化的選擇偏差）。F6b 舊解上同一設定能過，
    # 是因為那一點不是在 1e-6 表面上被最佳化出來的。
    # 修法：SOLVER_COARSE/FINE 改 rtol 1e-7 / atol 1e-9（每次 evaluate ~1.3 s）
    # **並重擬四 case**——只改 preset 不重擬會讓發佈 artifact 無法由現行程式重現。
    # 修好後本測試會變成 unexpected success，強制移除此 decorator。
    def test_k_perturbation_is_smooth(self):
        """k 的 ±1% 微擾上，χ² 不得有比曲率本身還大的抖動。"""
        p0 = self.state["params"]
        chi2 = [float(self._evaluate(replace(p0, k=p0.k * f))["chi2"]) for f in K_FACTORS]

        adjacent = [abs(chi2[i + 1] - chi2[i]) for i in range(len(chi2) - 1)]
        self.assertLess(
            max(adjacent), MAX_ADJACENT_DELTA,
            msg=f"相鄰 |Δχ²| 過大（k 每步 0.5%）：{['%.2f' % d for d in adjacent]}"
                f"；χ²={['%.2f' % c for c in chi2]}",
        )

        second = [abs(chi2[i - 1] - 2.0 * chi2[i] + chi2[i + 1]) for i in range(1, len(chi2) - 1)]
        self.assertLess(
            max(second), MAX_SECOND_DIFF,
            msg=f"χ² 二階差分過大（solver 噪音）：{['%.2f' % d for d in second]}"
                f"；χ²={['%.2f' % c for c in chi2]}",
        )

    def test_chi2_has_no_integration_path_noise(self):
        """k 的 1e-10 相對微擾下，真實梯度貢獻 < 1e-7；χ² 的任何更大變化都是積分路徑噪音。"""
        p0 = self.state["params"]
        base = float(self._evaluate(p0)["chi2"])
        for eps in (1e-10, -1e-10):
            d = float(self._evaluate(replace(p0, k=p0.k * (1.0 + eps)))["chi2"]) - base
            self.assertLess(abs(d), 1e-6, msg=f"k×(1{eps:+.0e}) 使 χ² 移動 {d:+.3e}（路徑噪音）")

    # F6e（2026-09-24）：同上，新 preset 下通過、decorator 已移除。歷史證據：
    # F6c 在這條測試上的「通過」（span 0.99）是假象：當時 reload 把 open_rate 0.254
    # 帶進 coeff = 0 的模型，惰性 ξ_pref 的暫態壓住了 RK45 步長，等於一個隱形的
    # 步長上限。F6d 讓惰性狀態不再演化（params.d_preferential_flow_dt 的 gate）後，
    # 同一個 canonical 狀態下 volume 項 vs τ_tort ∈ {5, 6.5, 8, 10}：
    #   rtol 1e-6，coeff = 0（現行）                 360.99 370.65 365.46 374.16  span 13.17
    #   rtol 1e-6，coeff 1e-30 + open 0.254（模擬舊耦合） 369.79 367.70 367.78 366.80  span 2.99
    #   rtol 1e-7 / atol 1e-9，coeff = 0              363.83 364.80 364.70 364.18  span 0.97
    # 門檻 3 不放寬：放寬到 15 會讓這條測試對它要抓的噪音永遠沉默。
    def test_tau_tort_does_not_move_the_volume_term(self):
        """`tau_tort` 對水力無物理回饋 → volume 項必須近乎常數。"""
        p0 = self.state["params"]
        volumes = [
            float(self._evaluate(replace(p0, tau_tort=tt))["chi2_terms"]["volume"])
            for tt in TAU_TORT_GRID
        ]
        span = max(volumes) - min(volumes)
        self.assertLess(
            span, MAX_VOLUME_SPAN_VS_TAU_TORT,
            msg=f"volume 項隨 tau_tort 變動 {span:.2f}（無物理回饋，應為常數）："
                f"{dict(zip(TAU_TORT_GRID, ['%.2f' % v for v in volumes]))}",
        )

    def test_tau_tort_chi2_is_monotone_or_unimodal(self):
        """χ² 沿 `tau_tort` 不得出現孤立尖點（噪音的指紋）。"""
        p0 = self.state["params"]
        chi2 = [float(self._evaluate(replace(p0, tau_tort=tt))["chi2"]) for tt in TAU_TORT_GRID]
        # 內點若同時高於兩個鄰居，代表表面上有一個純數值的尖峰。
        for i in range(1, len(chi2) - 1):
            self.assertFalse(
                chi2[i] > chi2[i - 1] + 1.0 and chi2[i] > chi2[i + 1] + 1.0,
                msg=f"tau_tort={TAU_TORT_GRID[i]} 處出現孤立尖點："
                    f"{dict(zip(TAU_TORT_GRID, ['%.2f' % c for c in chi2]))}",
            )



class TestInertPreferentialStateDoesNotSteerSolver(unittest.TestCase):
    """
    `pref_flow_coeff <= 0` 時 ξ_pref 對物理無作用，也不得影響求解器（F6d）。

    Why: F6c §3.2 實測 stage 4 reject（coeff = 0）後，只因 reload 把
         `pref_flow_open_rate` 設成 0.254 而 fit 用 0，同一組物理參數的 canonical
         χ² 就差 8.05——惰性狀態的暫態參與 RK45 誤差估計、改變了步長序列。
         這條耦合讓 fit 與 benchmark reload 不可比，也讓「惰性參數怎麼設都一樣」
         這個物理事實在數值上不成立。
    """

    def test_rate_is_zero_when_coefficient_is_zero(self):
        """coeff = 0：不論 open_rate 與注水衝擊多大，dξ/dt 都必須恰為 0。"""
        from pour_over.params import V60Params
        kw = dict(pref_state=0.0, q_in=5.0e-6, pour_impact=1.0, t_sec=100.0, bloom_end_s=30.0)
        inert = V60Params(pref_flow_coeff=0.0, pref_flow_open_rate=0.254)
        self.assertEqual(inert.d_preferential_flow_dt(**kw), 0.0)
        # gate 只關閉非作用態：coeff > 0 時動態必須照常（否則 stage 4 被靜默停用）。
        active = V60Params(pref_flow_coeff=5.0e-5, pref_flow_open_rate=0.254)
        self.assertGreater(active.d_preferential_flow_dt(**kw), 0.0)

    @unittest.skipUnless(
        CANONICAL_CSV.exists() and CANONICAL_SUMMARY.exists(),
        "canonical case 或其 flow-fit summary 不存在",
    )
    def test_open_rate_does_not_change_chi2_when_inactive(self):
        """canonical（coeff = 0）：open_rate 0 與 0.254 的 χ² 必須**逐位相同**。"""
        st = _canonical_state()
        base = replace(st["params"], pref_flow_coeff=0.0)
        chi2 = [
            float(fitting._chi2_evaluate(
                st["case"], replace(base, pref_flow_open_rate=rate), st["tau_lag_s"],
                vessel_equivalent_ml=st["vessel_equivalent_ml"],
                solver=fitting.SOLVER_COARSE,
                k_beta_prior_psd=st["k_beta_prior_psd"],
                keep_sim=False,
            )["chi2"])
            for rate in (0.0, 0.254075)
        ]
        self.assertEqual(chi2[0], chi2[1], msg=f"惰性 ξ_pref 改變了 χ²：{chi2}")


if __name__ == "__main__":
    unittest.main()
