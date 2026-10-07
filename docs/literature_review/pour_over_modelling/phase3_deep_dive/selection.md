# Phase 3 — Selection

選讀 12 篇全文。選取準則：與「measured PSD + 單一滲透率 closure，跨研磨度預測 V_out(t) 與
drain time，不重擬合」這個候選主張的距離，以及本專案各 closure 的直接來源。

| # | Paper | 為何選 | 讀者 |
|---|---|---|---|
| 1 | Lee & Chang 2026, npj Sci. Food — conservation-constrained framework for filter coffee | **最接近的既有工作**：濾杯 reduced-order，PSD 校準 + held-out 研磨度預測 drawdown | 主 agent |
| 2 | Siregar 2026, Eur. J. Phys. — pour-over teaching model | 錐形 Darcy 手沖模型；確認是否有實驗驗證 | agent A |
| 3 | Wadsworth et al. 2026, RSOS — coffee puck permeability | grind → 比表面積 → k 的理論與跨 11 刻度驗證；本專案 PSD→k 的直接對照 | agent A |
| 4 | Park, Young & Mathijssen 2025, PoF — pour-over jet mixing | 唯一的手沖流體力學實驗；注水衝擊（本專案 throat relief） | agent A |
| 5 | Oec 2026, engrXiv — area-weighted PSD peak predicts TDS | 影像 PSD 特徵選擇；d32 作為尺度錨的外部支持 | agent A |
| 6 | Moroney et al. 2019, PLOS ONE — extraction uniformity, drip filter | 萃取模型主線，含 drip filter 幾何 | agent B |
| 7 | Cameron et al. 2020, Matter — systematically improving espresso | PSD + 不均勻流 + 重現性；研磨度預測的反例 | agent B |
| 8 | Foster et al. 2025, PoF — espresso infiltration μCT | 1D 非飽和流模型 + 時間解析實驗驗證（方法學對照） | agent B |
| 9 | Lee, Smith & Arshad 2023, PoF — uneven extraction | 雙路徑低維模型（本專案 bypass/preferential flow 對照） | agent B |
| 10 | Corrochano et al. 2015, JFE — coffee bed permeability | 本專案 k 與 Kozeny-Carman 的直接來源 | agent C |
| 11 | Mo et al. 2023, Sci. Rep. — XCT microstructure & flow | 微結構 → 滲透率，fines 位置 | agent C |
| 12 | Liang, Chan & Ristenpart 2021, Sci. Rep. — equilibrium desorption | 萃取上限（本專案 max_EY）的機制來源 | agent C |
| 13 | Smrke et al. 2024, Sci. Rep. — role of fines | fines → 滲透率與萃取（本專案 clogging） | agent C |

未選但已在 survey：Moroney 2015 CES（已在 `docs/literature_map.md` 詳列）、Estévez-Sánchez 2025
（付費，摘要已足以定位）、Waszkiewicz 2026（已在 literature map）。
