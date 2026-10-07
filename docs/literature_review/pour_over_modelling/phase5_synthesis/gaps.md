# Phase 5 — Gaps

Date: 2026-10-07 | 每個 gap 標記狀態：**closed**（已有人做）、**open**（未見前例）、
**open-risky**（未見前例但有反面先驗）。證據指向 `synthesis.md` 節次與 `deep_dive.md` 筆記。

## 原始候選主張的判定

> 「measured PSD + 單一 permeability closure，不重擬合即可跨研磨度預測 V_out(t) 與 drain time」

| 成分 | 狀態 | 依據 |
|---|---|---|
| 濾杯 reduced-order + measured PSD + held-out 研磨度 drawdown 預測 | **closed** | Lee & Chang 2026（終點、內插、每研磨擬合 + D90 冪律） |
| 時間解析 V_out(t) 的預測與比對 | **open** | 文獻中沒有任何手沖 V_out(t) 資料（synthesis 2.3） |
| PSD 經物理 closure 進入 k，單一尺度、不逐研磨擬合 | **open-risky** | espresso 與未壓實樣品上 4 組獨立反證（synthesis 2.1）；重力手沖無資料 |
| 外推到校準研磨範圍之外 | **open** | Lee & Chang 只做內插 |

**結論**：原始主張的敘事已部分被佔走；剩下的部分有強烈反面先驗。主張需要重寫。

## Gap 清單

### G1. 手沖的時間解析出液與溫度資料集 — open（最穩）
- 現況：只有 espresso 有時間解析水力資料；手沖只有終點。
- 本專案現有：4 支影片 brew 的逐格 V_out(t)、壺溫時序、出口溫度，每點附不確定度。
- 缺口：研磨範圍太窄（d32 只跨約 1.2 倍）、單一豆子、單一沖煮者、無重複。
- 可發表形式：資料集 + 量測方法論文（影片讀值管線、觀測算子、不確定度模型）。

### G2. 重力驅動低壓頭下，PSD→k 的研磨度傳遞性 — open-risky（最有科學價值）
- 問題：espresso 中 KC + d32 的誤差隨研磨度系統性增加（Corrochano 30%→520%）。在壓頭只有幾公分、
  床層幾乎不壓密的手沖中，這個誤差是否縮小？
- 為何 risky：多數反證機制（雙峰 PSD、fines、非球形）在手沖同樣存在；只有壓密這一項會減弱。
- 設計成**檢驗**而非主張：固定 k₀ 只擬合一次，預測其他研磨度的整條 V_out(t)；比較三種 PSD 進入方式
  （d32-KC、Wadsworth 的比表面積 percolation 式、Lee & Chang 的逐研磨有效直徑 + 冪律）。
  無論哪個勝出都是結果。
- 前置條件：研磨範圍至少跨 2–3 倍 d32；PSD 重複量測以估計量測雜訊（見 G4）。

### G3. 終點量測下萃取動力學的不可辨識性 — 部分 closed
- Lee & Chang 已報告 Jacobian 秩 2、參數相關 −0.999。本專案的 `τ_tort` 不可辨識是同一現象的又一例。
- 剩下的 open 部分：用**分段收集 TDS**（fractional collection）打破簡併，這在手沖文獻中沒有出現。
  Lee & Chang 在結論中點名這是下一步。

### G4. 影像式 PSD 的重複性與其對流動預測的傳遞 — open
- 現況：Wadsworth 每刻度一個樣品；Lee & Chang 未報 PSD 重複量測；Oec 濾掉 < 0.1 mm。
- 本專案資料：同刻度兩天 d32 差約 20%，大於刻度間差異。絕對尺度 ±45%。
- 可做：同一批粉重複取樣拍攝 N 次，量化 d32 / fines 指標的量測變異，並傳遞到 V_out(t) 預測區間。
  這同時是 G2 的前置條件。

### G5. 手沖的熱耦合 — open（小眾）
- 沒有任何手沖模型同時建模並量測漿體、濾杯、下壺溫度。Lee & Chang 無熱模型。
- 本專案已有：多節點熱模型、壺溫時序擬合、出口溫度 held-out 檢查。
- 價值：作為 G1 論文的一個章節，單獨成文的份量不足。

### G6. 注水擾動與床層重排 — open（本專案目前不處理）
- Park 2025 的 avalanche 混合、Santanatoglia 2023 的人為因素。本專案的 throat relief 是 reduced-order
  近似，第二注提早 2–4 s 的結構誤差可能與此有關。
- 不建議作為下一篇主題；在 G1/G2 論文中列為限制，並固定注水方式。

## 建議的論文主張（取代原始主張）

**主張 A（建議）**：
> 在重力驅動的 V60 手沖中，以影片逐格量測出液曲線與溫度，檢驗「單一床層滲透率尺度 + 量測 PSD 的物理
> closure」能否在不重擬合下預測不同研磨度的整條 V_out(t)，並與逐研磨擬合的有效參數法（Lee & Chang 2026）
> 在同一資料上比較。

- 新意：G1（資料）+ G2（檢驗）+ 與最接近前作的正面比較。
- 必要條件：≥ 4 個研磨度、d32 跨 ≥ 2 倍、每研磨 ≥ 3 重複、PSD 重複量測（G4）。
- 加分：用 Lee & Chang 的公開 15 次沖煮作外部終點測試。
- 目標期刊：npj Science of Food（Lee & Chang 的出處）、Journal of Food Engineering、Physics of Fluids。

**主張 B（保底）**：
> 手沖時間解析資料集與量測方法 + 守恆約束模型的 identifiability 分析。

- 新意只有 G1 + G3 的延伸；份量較輕，適合 data paper 或 JOSS（軟體）。

## 本次檢索的盲區
- 未使用 Semantic Scholar（限流）、Google Scholar、Scopus；OpenAlex 對付費期刊摘要覆蓋不完整。
- 中文、日文、韓文咖啡科學文獻未檢索。
- 專利未檢索（濾杯製造商可能有內部流動模型）。
- Siregar 2026、Park 2025 只讀到摘要。
