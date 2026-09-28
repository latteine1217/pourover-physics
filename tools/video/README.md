# tools/video — 沖煮錄影量測的重現步驟

把三支沖煮錄影（秤在分享壺下、V60 在壺上）轉成 1 s 格點的 flow profile：
`data/<case>/<stem>_flow_profile_video.csv`。

| 影片 | case | 幀率 |
|---|---|---|
| `IMG_3346.MOV` | `data/kinu_29_light/4:12`（canonical） | 30 fps |
| `IMG_3347.MOV` | `data/kinu_27_light/4:12` | 30 fps |
| `IMG_3405.MOV` | `data/kinu_28_light/4:20` | 29.97 fps |

- 原始 `.MOV` 放在各 case 目錄，單檔 136–167 MB，不進版控（見 `.gitignore`）。
- 逐格判讀與衍生量放在 `data/<case>/video/`，這些是量測的可追溯紀錄，會進版控。

## 畫面內容與命名

- 秤（七段 LED）：左邊是秤內建計時器，右邊是累積重量。秤在分享壺下，所以讀值 = 累積注水量。
- 溫度計 GM1312（LCD）：上行是分享壺溫（`server`），下行是濾杯出水口溫（`outflow`）。
  依據是三支影片的起始值與 `*_thermal_profile.csv` 逐一對上。
- 分享壺：HARIO SCI 500 mL 刻度，讀液面前緣。

## 時刻慣例與計時器模型

- 抽格用 `ffmpeg -i <VID>.MOV -vf fps=1 f_%04d.jpg`。
  - 30 fps 片的 `f_k` 是第 30(k−1)+14 幀，所以 t = k − 0.533 s。
  - IMG_3405 實測 f12 = 11.478 s、f130 = 129.529 s，兩點間線性內插。
  - `f_1` 是第 0 幀。
  - 這些時刻用抽格與原始幀逐像素比對驗證過；單一定義在 `common.frame_video_t`。
- 計時器模型為 `scale_timer_s = a + b · video_t_s`（`v1/transitions.py` → `v1/ratefit.py` → `v1/qc_timer.py`）。
  - b 由 30 fps 原始幀偵測每一次跳秒擬合：1.01885 / 1.01890 / 1.01813。
  - 在 b 固定下求 a，387/387 格計時器讀值與模型一致。
  - 秤計時器比真實時鐘快 1.86%，專案常數是 `measured_io.SCALE_TIMER_RATE = 1.0186`。
- 真實秒 `t = video_t_s − timer_zero_video_t`。t = 0 是秤計時器被注水自動觸發的時刻。

## 重現步驟

先設定兩個環境變數：`VIDEO_WORK` 是抽格與中間檔的工作目錄，`POUR_OVER_REPO` 預設為本 repo。

```bash
export VIDEO_WORK=/path/to/work; mkdir -p $VIDEO_WORK/vid $VIDEO_WORK/v2
```

### 1. 抽格

```bash
for v in IMG_3346 IMG_3347 IMG_3405; do
  mkdir -p $VIDEO_WORK/vid/$v
  ffmpeg -i data/<case>/$v.MOV -vf fps=1 $VIDEO_WORK/vid/$v/f_%04d.jpg
done
```

### 2. 秤與 LCD 判讀（人工步驟）

輸出為 `vid/sc_<VID>.txt` 與 `vid/th_<VID>.txt`，每格一列：

- `sc`：`frame,timer,weight,note`
- `th`：`frame,upper,lower,flag`

判讀規則：

- 秤：
  - 每張拼圖 36 格，逐張目視判讀。tesseract 對這種七段顯示無效。
  - 被遮擋的位數先看露出的段；仍無法區分時，用注水率平滑性決定，並標 `uncertain:` 與候選值。
  - 手部暫態、顯示空白標 `unreadable:`，計時器停止標 `timer stopped`。
- LCD：
  - 只認深色段。淺灰段視為換值中的殘影（鬼影），歧義寫進 flag，例如 `U tenths ghost (8|0)`。
  - 以彩色原圖判讀。灰階對比拉伸會放大鬼影，不使用。
- QC：
  - 計時器讀值必須滿足 `floor(a + b·t) = 顯示值`（`v1/qc_timer.py`）。
  - 累積重量不得回落超過 0.2 g。
  - 以另一種裁切 / 倍率隨機抽 24 格盲測二次判讀。V1 結果：計時器與秤重 0/24 不一致；
    溫度 6/24 有差異，其中約 6% 格 ≥ 1 °C，集中在有鬼影旗標的格。

### 3. 計時器模型與逐格顯示檔

```bash
uv run python tools/video/v1/transitions.py IMG_3346 x,y,w,h   # 秒個位數框；每支影片各跑一次
uv run python tools/video/v1/ratefit.py
uv run python tools/video/v1/qc_timer.py                       # → vid/timer_model.json
uv run python tools/video/v1/build_displays.py                 # → vid/<VID>_displays.csv, _pours.json, _vs_csv.md
```

### 4. 液位偵測

刻度標定、`CFG` 與目視覆寫都寫在腳本內，偵測原理見各檔 docstring。
`level.py` 需要 Pillow（`from PIL import Image`）；專案環境已由 matplotlib 間接安裝，
若環境中沒有，改用 `uv run --with pillow python tools/video/v2/level.py <VID>`。

```bash
for v in IMG_3346 IMG_3347 IMG_3405; do uv run python tools/video/v2/level.py $v; done   # → v2/raw_<VID>.json
uv run python tools/video/v2/finalize.py      # → vid/<VID>_level.csv（刻度分段線性 y→mL；單調突波剔除；估計量合併）
uv run python tools/video/v2/visual_check.py  # 目視 vs 自動
uv run python tools/video/v2/logcmp.py && uv run python tools/video/v2/hyp.py   # 與紀錄表對照、偏差假設檢定
uv run python tools/video/v2/make_check.py    # 標定檢查圖
```

`vis.py`、`crop.py`、`kymo.py`、`draw.py` 是判讀用的輔助拼圖工具。

**刻度欄遮擋（F12a，2026-09-27）**：分享壺溫熱電偶線斜穿刻度欄時，刻度欄液緣會沿潤濕的線被
抬高 2–5 mL。`level.py` 的 `wire_px_near_front` 數刻度欄 ±`WIRE_BAND_PAD_PX = 10` px、前緣上方
`WIRE_WIN_ABOVE_PX = 60` px 到下方 2 px 窗內的藍線像素（B > R + 50 且 B > G + 30），寫入 raw JSON
的 `wire_px_tick`。`finalize.py` 呼叫 `common.merge_level_estimators`：
1. 遮擋（`wire_px ≥ common.WIRE_OCCLUSION_MIN_PX = 20`）且三估計量（刻度欄 / 無刻度條帶 + 橢圓
   修正 / 前弧擬合）皆有限 → 取中位數，旗標 `tick_col_wire;median3`（σ 6 mL）；
2. 否則沿用 V2 原規則（刻度欄為主，與鄰格中位數差 > 6 px 時取另兩者平均，旗標 `tick_col_outlier`）；
3. 遮擋但估計量不足 → 依 2，另加 `tick_col_wire`。

三支影片全格掃描只命中 IMG_3347 f107–f130（t = 103.7–126.7 s）。level CSV 另存稽核欄
`V_tick_ml`、`V_strip_ml`、`V_arc_ml`、`wire_px_tick`。

`finalize.py` 輸出的 `video_t_s = k − 1` 與 `timer_est_s` 是 V2 自己的舊慣例，下一步不使用；
下一步以 `frame` 對齊 V1 的逐格影片時刻。

### 5. 複製到 case 目錄並組 profile

```bash
cp $VIDEO_WORK/vid/{<VID>_displays.csv,<VID>_level.csv,<VID>_pours.json,sc_<VID>.txt,th_<VID>.txt,trans_<VID>.txt} data/<case>/video/
# <VID>_timer_model.json = timer_model.json 與 ratefit.json 中該片的片段
uv run python tools/video/build_profile.py    # → data/<case>/<stem>_flow_profile_video.csv
```

`build_profile.py` 另讀 `data/<case>/video/<VID>_annotations.json`（見下節「濾杯移開」）。

各欄定義、σ 等級、停流判定與杯溫來源，見 `build_profile.py` 的 docstring。重點如下：

- `drained_volume_ml` 以 1/σ² 加權等張回歸單調化。
- σ 分三級：ok 4 mL；目視或估計器分歧 6 mL；V < 50 mL 外插或液面不可見 15 mL。
- 液面不可見段 `use_for_fit = 0`；濾杯移開後的列也是 `use_for_fit = 0`（`drained_quality` 加
  `after_dripper_removed`），meta 寫入 `dripper_removed_time_s`。
- `flow_stop_visual` 列 = `observation.level_stop_time` 次格跨越時刻向上取整所在列。常數
  `STOP_TOL_ML = 2.0`、`FINAL_WINDOW_S = 6.0`、`STOP_SMOOTH_POINTS = 5` 唯一來源是
  `pour_over/measured_io.py`，模型端 `observation.model_level_stop_time` 用同一函式。
- `dripper_off_final` = 觀測末列（讀最終壺溫用），在濾杯移開之後；它不是最終杯量的讀取點
  （模型端最終杯量取最後一個 `use_for_fit` 列）。
- 紀錄表 `final_coffee_temp_C` 空白時，改用觀測末 3 格分享壺溫的中位數，並寫入 `final_coffee_temp_source`。

## 在模型端的使用

- 預設優先讀影片版：`measured_io.load_flow_profile_csv(path)`；要強制讀紀錄表用 `source="log"`。
- χ² 只取每 `fitting.VIDEO_FIT_STRIDE_S = 5 s` 一列。完整 1 s 序列保留在 case bundle 的 `*_full` 鍵，
  供作圖與熱時序診斷使用。

## 濾杯移開（F12a，2026-09-27）

三支影片在錄影結束前**都有把濾杯移離分享壺**：IMG_3346 f131（126.94 s）、IMG_3347 f144
（140.71 s）、IMG_3405 f129（121.96 s）。移開後床內剩餘液體不再進壺，手與濾杯擾動液面與刻度欄
照明（例：IMG_3346 129–131 s 液位由 250 跳到 258 mL），這些讀值不能與「濾杯在壺上」的模型比較。

- 每支影片以 `data/<case>/video/<VID>_annotations.json` 宣告 `dripper_removed_frame`，並附
  `what` / `why` / `evidence_frames`（影格證據文字）。移開無法用像素規則穩健判定（手、濾杯、布
  的顏色與位置每次不同），因此逐案目視標註。
- 出水口熱電偶（LCD 下行）的驟降時刻 127.5 / 141.5 / 122.5 s 比移開影格晚 0.5–0.8 s：它量到的是
  使用者移開濾杯的時刻，不是液柱自行斷流，模型端只作診斷（`thermo_break_s`）。
- 壺溫（LCD 上行）在移開後仍是有效量測（loader 以 `level_visible` 區分）。

## 濾杯質量共識（meta 欄不一致時的處理）

紀錄表的 meta 欄（`time_mmss` 之前的欄位，如 `dripper_mass_g`）在每一列重複寫一次。
`kinu29 4:12` 與 `kinu27 4:12` 兩份紀錄表只有**首列** `dripper_mass_g = 224.1`，同檔其餘
26/27 列與所有其他沖煮（`kinu28 4:20`、`kinu29 4:11`）皆為 `123.5`。這兩案的影片分享壺溫
時序無法分辨兩個候選質量（RMSE 兩案皆 3.58 °C、前 60 s 偏差皆約 −4.9 °C，質量差在熱容
上的效應被其他熱端不確定度蓋掉），無法用影片獨立判定何者為真。

`measured_io.meta_consensus` 因此把這類逐列不一致視為一般 QC 問題處理：對每個 meta 欄，
若各列非空值不同，取檔內**嚴格多數值**，並把修正寫入 `preprocess_corrections`（格式同
`preprocess` 的修正紀錄）；若沒有嚴格多數、或不一致的欄不是數值，一律 `raise`（Fail
Fast，不靜默選一個值）。這兩案的 `dripper_mass_g` 因此由 `224.1` 修正為 `123.5`（26/27
或 27/28 多數）。raw CSV（Class A）不受影響——修正只發生在載入後的記憶體物件。

兩案受影響的只有熱端（當時 stage 5 只擬 `lambda_server_ambient`）：`kinu29 4:12` 的
`lambda_server` 由 `2.57e-4` 重擬為 `4.96e-4 s⁻¹`；`kinu27 4:12` 由 `1.30e-3` 重擬為
`1.54e-3 s⁻¹`。水力與萃取參數不受影響。

**使用者 2026-09-27 確認 123.5 g 正確。** 影片案例的共識修正在 `build_profile.py` 組 profile 時
套用（stdout 印出修正；影片版 CSV 的 meta 已是 123.5），因此這些案例 summary 的
`preprocess_corrections` 不含此筆。其後熱端配置已改（F11）：分享壺溫時序進 χ² 的影片案例擬
`U_liquid_dripper`、`lambda_server` 凍結 3.7e-4 s⁻¹，見 `docs/experiment_log.md` `[POLICY]`。
