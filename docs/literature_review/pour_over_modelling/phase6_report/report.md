# 手沖咖啡 reduced-order 建模：文獻回顧與研究缺口

Date: 2026-10-07 | 範圍：重力驅動手沖（V60 / 濾杯）的水力、萃取、熱模型，以及可借鑑的 espresso
與多孔介質文獻。資料庫 66 篇（`../paper_db.jsonl`），精讀 13 篇（`../phase3_deep_dive/deep_dive.md`）。
引用 key 對應 `references.bib`。

## 摘要

本回顧要回答：「measured PSD + 單一 permeability closure，不重擬合即可跨研磨度預測 V_out(t) 與
drain time」是否為研究缺口。結論分三部分：

1. **部分已被佔走。** [@lee2026coffee]（npj Science of Food，2026-08）以錐形濾杯 finite-volume
   守恆模型，在 coarse/medium/fine 三個研磨度各擬合 3 個有效參數，再以 `a·D90^b` 內插，預測兩個
   held-out 研磨度的 drawdown time（MAE 6.67 s）、杯量與 TDS。只比對終點，沒有時間解析曲線。
2. **剩下的「單一 k + PSD 物理 closure」有強烈反面先驗。** 四組獨立工作顯示，單一粒徑尺度代入
   Kozeny-Carman 無法跨研磨度傳遞滲透率，誤差隨研磨度系統性變化
   [@corrochano2014new; @wadsworth2026model; @moroney2019analysing; @lee2026coffee]。這些證據全部
   來自 espresso 或未壓實樣品，手沖低壓頭下是否成立仍無資料。
3. **真正空白的是時間解析的手沖資料。** 文獻中沒有任何手沖 V_out(t) 或溫度時序資料集；Lee & Chang
   自己在結論中點名這是驗證軌跡的下一步。

建議把論文主張從「預測」改寫成「檢驗」：在重力手沖中用影片量測整條出液曲線，檢驗 PSD 物理 closure
能否跨研磨度傳遞，並在同一資料上與 Lee & Chang 的逐研磨擬合法比較。

## 1. 背景與分類

| 層級 | 代表 | 流動驅動 | PSD 在水力中的角色 |
|---|---|---|---|
| 孔隙尺度 | [@wadsworth2026model]、[@mo2023exploring] | 數值模擬 | 影像給結構，k 由 LBM/SPH 算出 |
| 連續介質多尺度 | [@moroney2015modelling]、[@moroney2019analysing]、[@cameron2020systematically]、[@foster2025dynamics] | 泵壓 / 定流量 | 每研磨度擬合代表粒徑，或量測 shot time 當輸入 |
| 低維機制 | [@lee2023uneven]、[@siregar2026coffee] | 給定流量 / 重力 | KC 只分配流量；k 為掃描參數 |
| Reduced-order 守恆 | [@lee2026coffee] | 重力（濾杯） | 逐研磨擬合有效直徑 + D90 冪律內插 |
| 統計相關 | [@oec2026area]、[@smrke2024role] | — | PSD 特徵與 TDS / shot time 相關 |

手沖專屬的流體力學研究在 2025–2026 才出現：注水水柱的 avalanche 混合 [@park2025pour]、錐形 Darcy
教學模型 [@siregar2026coffee]、守恆約束框架 [@lee2026coffee]。

## 2. 主要發現

### 2.1 最接近的前作：Lee & Chang 2026
- 模型：水量守恆（池、孔隙、滯留、杯）+ 溶質守恆；KC `K = d_h² ε³/(α_K(1−ε)²)`；cell 間 Darcy 乘上
  `(S − S_res)^n`；24 個 PSD bin 一階釋放，`k_i ∝ (r_ref/r_i)² + (r_ref/r_i)`。無熱模型。
- 實驗：5 研磨 × 3 重複 = 15 次；20 g / 300 g；三段注水；只量 drawdown、杯量、TDS。
- 擬合：每校準研磨 3 個參數（`λ_ret`、`d_h`、release scale），200 起點 multistart，1000 次 bootstrap。
- 結果：held-out 內插誤差都在 1 SD 內；但 drawdown 的重複間 SD 有 13–30 s。
- 弱點（本回顧觀察）：
  - 擬合的 `d_h` 隨研磨變細從 0.469 增加到 2.971，與 KC 方向相反。
  - `d_h` 與 release scale 相關 −0.999，Jacobian 有效秩 2。
  - PSD 對流動的影響完全靠擬合後內插，不是物理預測。
  - 只做內插；medium-coarse 的 D90（1683 μm）緊鄰 coarse（1815 μm）。
- 程式與資料公開：https://github.com/Byoung-Yong/FilterCoffee（MIT）。

### 2.2 單一粒徑尺度的 KC 不能跨研磨度傳遞 k
- [@corrochano2014new]（數字取自第一作者 2017 EngD thesis [@corrochano2017advancing]）：
  - 乾式雷射繞射 d32 + KC 在 4 個 espresso 研磨度全部高估，相對誤差隨研磨變粗而增加，從 30% 到 520%。
  - 要配合資料，tortuosity 指數需逐研磨擬合（0.27–1.01）。
  - 床密度增加約 30% 時，k 降低 3–4 倍。
- [@wadsworth2026model]：
  - 11 個研磨刻度，各 1 個未壓實樣品。
  - 量測比表面積在粗端比球形估計大約 26 倍。
  - LB 滲透率對研磨刻度非單調：G4 1.55e-10 m²，G11 1.58e-11 m²。
- [@moroney2019analysing]：兩研磨的 d32 只差 1.4 倍（27.34 vs 37.78 μm），壓降差 3.5 倍（2.3 vs 0.65 bar）；
  代表粒徑是擬合值。
- [@smrke2024role]：預測 shot time 需要 X50 與 fines 比例兩個特徵。

### 2.3 只有終點時，萃取不可辨識
- 不可辨識是終點量測的結構性限制，不是個別模型的問題：
  - [@lee2026coffee] 的 Jacobian 秩 2。
  - 本專案的 `τ_tort` 跨 brew 變動 2.3 倍。
- [@liang2021equilibrium]：浸泡式平衡 EY 約 21%，幾乎不隨研磨或溫度變化，支持把 `max_EY` 固定。
  每克粉滯留液 2.48 ± 0.19 g，可作為毛細滯留的外部參考。

### 2.4 時間解析手沖資料不存在
- 時間解析的水力資料全部來自 espresso：[@foster2025dynamics] 的 μCT 浸潤前緣、[@moroney2019analysing]
  的出口濃度。
- GitHub 上沒有手沖 V_out(t) 資料集（見 `../phase4_code/code_repos.md`）。

### 2.5 PSD 量測重複性很少被量化
- 已讀文獻都沒有報告 PSD 的重複量測。
- 本專案的資料：同一刻度（Kinu 29）兩天量得的 d32 是 0.894 與 1.069 mm，差約 20%，大於 Kinu 27/28/29
  三個刻度之間的差異。
- 本專案目前的研磨範圍 d32 只跨約 1.2 倍；Lee & Chang 的 D90 跨約 3 倍。

### 2.6 CO₂ 脫氣：動力學已知，對萃取的影響未量化（2026-10-07 補充檢索）
- [@smrke2018time]：淺焙全豆 400 h 釋放 2.5–2.8 mg/g，Weibull λ ≈ 715 h（35 °C）；研磨後最多 75% 的殘留氣體
  在 90 s 內釋放；部分 CO₂ 為結合態，接觸水才釋放。
- [@shimoni2000degassing]：研磨粉 CO₂ 擴散係數 10⁻¹⁴–10⁻¹⁵ m²/s，Arrhenius 活化能 73.6 kJ/mol。
- [@anderson2003diffusion]、[@wang2014effect]：研磨粉擴散動力學、烘焙條件與研磨損失。
- CO₂ 對萃取率的影響找不到同儕審查的量化研究。

## 3. 對本專案現況的含意

| 項目 | 現況 | 文獻對照 |
|---|---|---|
| k 與 PSD 的關係 | k 每支 brew 擬合；`k_from_d32` 已計算但沒有被使用 | 與 Lee & Chang 一樣是逐 brew 擬合，沒有 PSD→k 預測 |
| 三支影片 brew 的 k | 6.46 / 6.67 / 7.66 e-11 m² | 研磨範圍窄，PSD 雜訊大於訊號，無法檢驗傳遞性 |
| 萃取 | 單一 TDS 擬合 `τ_tort` | 與 Lee & Chang 的不可辨識同一現象 |
| 時間解析資料 | 影片 V_out(t) + 壺溫時序 | **文獻空白**，是本專案最獨特的資產 |
| 熱模型 | 多節點，有出口溫度 held-out | 手沖文獻沒有 |

## 4. 研究缺口與建議主張

詳見 `../phase5_synthesis/gaps.md`。摘要如下：

| Gap | 狀態 |
|---|---|
| G1 手沖時間解析出液與溫度資料集 | open |
| G2 重力低壓頭下 PSD→k 的研磨度傳遞性 | open-risky |
| G3 分段 TDS 打破萃取簡併 | open（終點不可辨識已有人報告） |
| G4 影像 PSD 重複性與其傳遞 | open |
| G5 手沖熱耦合 | open，小眾 |
| G6 注水擾動 | open，不建議作為主題 |
| G7 CO₂ / 養豆天數對萃取與流動 | open（動力學已知，萃取效應未量化） |

**主張 A（建議）**：在重力驅動的 V60 手沖中，以影片逐格量測出液曲線與溫度，檢驗「單一床層滲透率尺度
+ 量測 PSD 的物理 closure」能否在不重擬合下預測不同研磨度的整條 V_out(t)；並在同一資料上與逐研磨擬合的
有效參數法 [@lee2026coffee] 比較。

必要的實驗條件：

1. ≥ 4 個研磨度，d32 跨 ≥ 2 倍，包含校準範圍外的外推點。
2. 每研磨 ≥ 3 重複沖煮。
3. 同一批粉做 PSD 重複量測，量化量測雜訊（G4）。
4. 固定注水方式，降低 G6 的影響。
5. 加分：用 Lee & Chang 公開的 15 次沖煮作為外部終點測試。

先驗判斷：依 2.2 節，單一 k + d32 很可能在研磨範圍兩端失效。屆時論文的結論會是「KC 的研磨度相依誤差在
手沖中仍然存在（或縮小到 X%），原因是 …」。只要實驗設計能區分原因（fines、非球形、壓密），這仍然是可以
發表的結果。

**主張 B（保底）**：手沖時間解析資料集與量測方法，加上守恆約束模型的 identifiability 分析。適合 data
paper 或 JOSS。

## 5. 限制

- 檢索只用 OpenAlex（Semantic Scholar 被限流），未查 Google Scholar、Scopus、專利，也未查中日韓文獻。
- 2.6 節 CO₂ 補充檢索：[@smrke2018time] 讀全文（ZHAW 開放版）；[@shimoni2000degassing] 只讀摘要；
  [@anderson2003diffusion] 與 [@wang2014effect] 摘要不可得，其數字轉引自 Smrke 2018 的文獻回顧。
- 只讀到摘要的有：[@siregar2026coffee]、[@park2025pour]、[@corrochano2014new] 的期刊版
  （數字取自 thesis）。
- [@cameron2020systematically] 讀的是缺圖的 accepted manuscript；[@lee2023uneven] 讀的是 arXiv 版。
- 已回原文核對的數字：Lee & Chang 全部、Moroney 2019 的 d32 與壓降、Wadsworth Table 1 與 α、
  Corrochano thesis 的 30%→520%。其餘數字取自 subagent 筆記，未逐一核對。

## 附錄：產出檔案

- `../phase1_frontier/frontier.md`：2022–2026 前沿
- `../phase2_survey/survey.md`、`../paper_db.jsonl`：66 篇分群
- `../phase3_deep_dive/selection.md`、`deep_dive.md`：13 篇精讀
- `../phase4_code/code_repos.md`：開源程式碼與資料
- `../phase5_synthesis/synthesis.md`、`gaps.md`：綜合與缺口
- `references.bib`：66 筆 BibTeX
