"""
measured_io.py — 量測資料與硬體條件輸入

What:
    集中管理 measured benchmark 使用的 CSV parsing、metadata fallback、
    與可直接量測的硬體/環境條件常數。

Why:
    量測資料 I/O 與 optimizer / loss 定義無關；把它們從 fitting 主流程拆開，
    可減少模組耦合，並讓 benchmark、viz、analysis 共用同一套輸入定義。
"""

import csv
import math
from collections import Counter
from pathlib import Path

import numpy as np

from .params import PourProtocol


# ── 量測紀錄品質旗標（F6b，2026-09-24）──────────────────────────────────────
# What: `flow_profile_quality_flags()` 依這兩個門檻判定「這份紀錄缺哪些水力訊號」。
# Why:  F6b §1 的檢核發現三個非 canonical case 的 `k` 被推到 canonical 的 16×，
#       根因不是模型，而是紀錄協定——床面從未記錄到積水、最後一注之後不再記錄
#       出液。χ² 只看得到「零驅動水頭卻有全額通量」，於是 `k` 只能往上撞。
#       這類缺陷用 gate 攔不到（資料本身自洽），只能**顯式標記並揭露**，
#       否則下游會把這三個 case 的校準值當成可交叉驗證的獨立結果。
#
# `QUALITY_PONDING_MARGIN_ML = 6.0`：= 2σ_ret（σ_ret = 3.0，見
#       `fitting.MEASUREMENT_SIGMA`）。保水峰值若不比末段保水高出 2σ，
#       代表紀錄上從來沒有「液面積到床面以上、再排下去」這件事。
# `QUALITY_COARSE_DRAINED_STEP_ML = 5.0`：量筒讀值量化階若 ≥ 5 mL，
#       已大於 χ² 假設的 σ_V = 3.0 mL——此時殘差的下限由讀值解析度決定，
#       不是由模型決定。
QUALITY_PONDING_MARGIN_ML = 6.0
QUALITY_COARSE_DRAINED_STEP_ML = 5.0

# ── 量測預處理常數（F9，2026-09-26；使用端見 `preprocess.preprocess_flow_profile`）──
# 皆為 Class B：由量測程序本身推得，不進 fit。
#
# `READING_TIME_SIGMA_S = 1.0`：逐列讀值的「記錄時刻」1σ 不確定度 [s]。
#   What: 秤與量筒是人眼讀、手寫時間戳；time_s 以整秒記錄，且讀秤、讀量筒、看錶
#         三個動作不同時。
#   Why:  整秒量化本身就有 ±0.5 s（均勻分布 σ = 0.29 s），加上讀取動作的先後
#         （同一列兩個讀值 + 看錶，O(1 s)），合成取 1 s。它同時用在兩處：
#         (a) 注水率上限檢定的容許區間（`ΔV/(Δt + 2σ_t)`，兩端各偏 1σ）；
#         (b) V_out 的誤差傳播 `σ_V,i = sqrt(σ_V² + (q_obs,i·σ_t)²)`
#             （見 `fitting.MEASUREMENT_SIGMA`）。
# `POUR_RATE_CAP_MARGIN = 1.1`：注水率上限 = 1.1 × 同一次沖煮「其他各注」的最大
#   區間注水率（leave-one-out）。
#   What: 手沖壺的最大出水率是硬體性質；同一次沖煮、同一個壺、同一位沖煮者的
#         其餘各注是它最直接的量測。
#   Why:  1.1 的餘裕 = 各注之間可再現的手勢差異量級（kinu29 4:11 各注 5.4–7.6 g/s，
#         最大兩注 7.64 / 7.58 相差 < 1%）；只有超出這個餘裕、且在 ±σ_t 時間戳
#         容許下仍超出者才視為紀錄誤差（見 `preprocess.infer_max_pour_rate_g_s`）。
# `POUR_INTERVAL_MIN_G = 1.0`：區間注水量低於此值不視為「一注」（濾掉秤漂移），
#   與 `protocol_from_cumulative_input(min_pour_ml=1.0)` 同一門檻。
READING_TIME_SIGMA_S = 1.0
POUR_RATE_CAP_MARGIN = 1.1
POUR_INTERVAL_MIN_G = 1.0

# ── 錄影量測常數（F10，2026-09-27；使用端見 `preprocess.preprocess_flow_profile`）──
# 皆為 Class B：由三支沖煮錄影逐格量測推得，不進 fit。
#
# `SCALE_TIMER_RATE = 1.0186`：秤內建計時器相對真實時鐘的速率比（計時器秒 / 真實秒）。
#   What: 紀錄表的 `time_s` 就是這個計時器的讀值；真實時間 t_real = time_s / 1.0186。
#   Why:  V1 以 30 fps 原始幀偵測計時器每一次跳秒，三支影片各自擬合週期：
#         b = 1.01885 ± 0.00005（IMG_3346）、1.01890 ± 0.00003（IMG_3347）、
#         1.01813 ± 0.00004（IMG_3405），387/387 格計時器讀值與模型一致。
#         三者平均 1.0186（片間差 0.0008 ≈ 0.1 s / 140 s，遠小於 σ_t）。
#         不修正時，以 `time_s` 為時間軸的所有流率偏低 1.9%，「180 s」實為 176.7 s。
#         同一台秤用於四個 case（含無影片的 kinu29 4:11），因此這是量測儀器的性質，
#         不是 case 參數。
# `VIDEO_READING_TIME_SIGMA_S = 0.1`：影片版逐格讀值的時刻 1σ [s]。
#   Why: 影片時刻由幀序號決定（f_k 時刻經逐幀比對驗證），秤與液位讀在同一格；
#        剩餘的不確定度是秤顯示更新相位（≤ 1 幀抽樣間隔內的 0.1 s 量級）。
#        紀錄表的 1.0 s 來自「人眼讀秤、讀量筒、看錶三個動作不同時」，影片版不存在這件事。
SCALE_TIMER_RATE = 1.0186
VIDEO_READING_TIME_SIGMA_S = 0.1

# ── 影片版液位停流觀測算子（F12a，2026-09-27；唯一來源）──────────────────────────
# 使用端：`tools/video/build_profile.py`（量測端，決定 `flow_stop_visual` 列）與
#         `observation.level_stop_time`（模型端；fitting 對影片 case 兩側都用它）。皆為 Class B。
# What: 影片 case 的「停流」定義 = 最後一注結束後，`STOP_SMOOTH_POINTS` 點滑動平均的液位
#       首次進入「觀測終值 − STOP_TOL_ML」以上的時刻；觀測終值 = 可用液位列最後
#       `FINAL_WINDOW_S` 秒的中位數。
# Why:  影片沒有「目視最後一滴」這個事件，只有液位；液位解析度 ±2–3 mL（V2）下，液位
#       平衡的判定容差取 2 mL（< 1σ_ok 的一半），終值窗 6 s（≥ 5 點平滑窗、又短到不含
#       末注之後仍在快速上升的段）。模型端若用出流率門檻（q < 0.05 mL/s，約 1 滴/s）
#       就是在比較另一個觀測量：影片長度內液位分辨不出 0.05 mL/s（R12 Q3：同一運算子下
#       停流誤差由 +5.85 / +2.38 / +2.35 s 變 +1.0 / −2.0 / −1.0 s）。
#       紀錄表 case 仍用 `observation.OBSERVED_STOP_THRESHOLD_MLPS`（人眼判定最後一滴）。
STOP_TOL_ML = 2.0
FINAL_WINDOW_S = 6.0
STOP_SMOOTH_POINTS = 5

# ── 分享壺溫度探頭浸沒體積（F11，2026-09-27）──────────────────────────────────
# What: 影片 LCD 上行（分享壺溫）探頭的感溫接點**完全浸入液面**時的壺內液量 V_immersion [mL]，
#       逐支錄影記錄（Class B：量測程序常數，探頭擺位每次沖煮不同，不進 fit）。
#       χ² 的分享壺溫時序只取 `V_out_obs ≥ V_immersion` 的時刻（`fitting._thermal_series_masks`）。
# Why:  浸沒前探頭讀的是空氣、水柱噴濺或部分潤濕的薄膜，不是壺內液溫。判定依據是讀值型態：
#       (1) 首次接觸：讀值由室溫跳到 34–50 °C（IMG_3346 t≈8 s、IMG_3347 t≈13 s、IMG_3405 t≈8 s；
#           影格 f_0012 可見液膜剛觸及探頭線末端），之後數十秒平穩但偏低；
#       (2) 完全浸沒：悶蒸停注期間（出流 < 0.3 mL/s、無熱源）讀值在 2–3 s 內**階躍上升 3–6 °C**
#           後轉為平滑跟隨液溫。無熱源下的液體不可能自行升溫 3–6 °C（此時滴入量只能提供
#           ~0.1 °C/s），唯一解釋是感溫接點由部分潤濕變成完全浸沒。取階躍結束時的影片液量：
#             IMG_3346 t≈28 s → 26.2 mL；IMG_3405 t≈27 s → 28.9 mL；
#             IMG_3347 階躍在 t≈24–26 s，當時液面不可見（< 刻度、未進 fit），取階躍後第一個
#             可見液位 30.2 mL（t=45 s）作為上界——保守側：只會少收點、不會收進浸沒前的點。
#       三支錄影一致落在 26–30 mL（壺底液深約 4–5 mm），與探頭線末端貼近壺底的影格一致。
SERVER_PROBE_IMMERSION_ML: dict[str, float] = {
    "IMG_3346": 26.2,
    "IMG_3347": 30.2,
    "IMG_3405": 28.9,
}

# `drained_log_bias_suspected` 旗標的揭露文字（benchmark CSV 的 `data_quality_notes` 欄）。
DRAINED_LOG_BIAS_NOTE = (
    "出液欄經同法三案影片證實悶蒸後偏高 13–73 mL（等同讀值領先 12–19 s）；"
    "本案無影片，無法修正"
)

MEASURED_BED_HEIGHT_CM = 5.3
MEASURED_VESSEL_EQUIV_ML = 42.4
MEASURED_AMBIENT_TEMP_C = 23.0
MEASURED_DRIPPER_MASS_G = 123.5
# 濾紙 + 濾杯壁面的潤濕保水 [mL]（Class B：由量測差直接定值，**不進 fit**）。
# What: 觀測到的 `retained_mass_g` 包含三部分——床內保水、濾杯出口暫存、
#       以及「濾紙與杯壁上掛著的水」。前兩者模型有，第三者沒有。
# Why:  kinu29 4:11 末段（t = 142 s，床層已停流、狀態穩定）量測保水 52.1 g，
#       F2b 模型保水 44.4 mL → 差 7.7 mL。此時床內與出口暫存都已收斂，
#       這個差值就是未建模的濾紙/杯壁潤濕量。把它當常數揭露，好過讓它
#       污染 `k` 或保水 closure（AGENTS.md §2.3：可直接量測的量不得吸收模型誤差）。
# **警告（2026-09-24 跨 case 檢查）**：這個常數目前只由 kinu29 4:11 一個 case 定值，
#       其他三個 case 的證據與它不一致。四個 case 的末段保水（F1/F2b 前參數，reload）：
#           case            模型(床+暫存)   量測    差
#           kinu29 4:11        42.3        52.1   +9.8
#           kinu29 4:12        42.5        −7.2    n/a（量測本身為負，不可用）
#           kinu27 4:12        43.0        40.0   −3.0
#           kinu28 4:20        42.2        36.3   −5.9
#       模型末段保水幾乎與 case 無關（42.2–43.0），量測卻橫跨 36–52 mL。
#       這四個 case 用同一支濾杯、同一種濾紙、同樣 20 g dose，若真是濾紙潤濕，
#       它應該近乎常數——資料說不是。加上 7.7 只是把「誰不準」從 kinu29 換成
#       kinu27/28（誤差變成 −2.5 / +10.2 / +12.9）。
#       亦即：**這 7.7 mL 很可能不是濾紙保水，而是 kinu29 4:11 那一個 case 的殘差。**
#       依 AGENTS.md §2.3（可直接量測的量不得吸收模型誤差），在取得獨立的濾紙
#       潤濕量測（乾濕濾紙秤重）之前，這個常數屬於**暫定**狀態。
# 主控者決定（2026-09-24）：在取得獨立秤重前**設為 0.0**——四 case 的量測保水散布
#       （36–52 mL）證明 7.7 是 kinu29 4:11 單一 case 的殘差，把它寫成「量測常數」
#       等於用可量測的量吸收模型誤差（AGENTS.md §2.3）。末段保水差額改在文件中揭露。
# TODO: 目標狀態 = 由「乾濾紙 vs 沖煮後濾紙」的直接秤重定值，並隨濾紙規格/濾杯/dose 重取。
MEASURED_PAPER_HOLDUP_ML = 0.0
MEASURED_DRIPPER_CP_J_GK = 0.88
# `MEASURED_LIQUID_DRIPPER_LAMBDA` 自 2026-04-30 起改為「fit initial guess」，
# 不再是 hard-coded 量測常數：thermal identifiability scan 顯示這條 λ 是熱端
# 最強自由度（cup ΔT swing 0.77 °C），由 `fit_k_kbeta_from_flow_profile`
# stage 6 校準，並以此值作為弱 prior reg 的中心。
MEASURED_LIQUID_DRIPPER_LAMBDA = 0.02
MEASURED_DRIPPER_AMBIENT_LAMBDA = 0.004
MEASURED_SERVER_AMBIENT_LAMBDA = 0.0

# Measured PSD baseline（kinu29 light）
# What: 當 case 找不到 per-case PSD 時使用的 fallback bins artifact。
# Why:  AGENTS.md §3.2 / §5 要求「有 measured PSD 必須優先使用」，且優先使用
#       *該 case* 的量測。頂層 `data/kinu29_psd_bins.csv` 來自較早、較低倍率
#       （58 μm/px，偵測下限 146 μm）的掃描，只作為最後 fallback。
MEASURED_PSD_BINS_CSV = "data/kinu29_psd_bins.csv"  # legacy 低倍率掃描
# number-based D10 的診斷 fallback [m]。
# Why: 此值受影像偵測下限鉗制（整數像素格點 artifact），**不再**驅動任何幾何；
#      模型尺度錨點是 PSD summary 的 `model_d32_m` / `model_Dv50_m`。
#      舊名 `MEASURED_D10_M` 保留供既有呼叫端過渡。
MEASURED_D10_DIAGNOSTIC_M = 374.2e-6
MEASURED_D10_M = MEASURED_D10_DIAGNOSTIC_M  # deprecated alias
MEASURED_PSD_DIAMETER_SCALE = 1.0

# Brix → TDS 經驗轉換（VST 折光儀校正因子，specialty coffee 慣例）
# - 折光儀讀值（°Bx，蔗糖等效百分比）需以 0.85 校正成實際咖啡可溶物 % w/w
# - TDS_g/L ≈ TDS_pct × 10 × ρ_brew （ρ ≈ 1.005，簡化為 ×10）
# 來源：VST CoffeeTools 折光儀手冊；T. Lingle "Coffee Brewing Handbook" 章節
BRIX_TO_TDS_PCT_FACTOR = 0.85
BREW_DENSITY_G_PER_ML = 1.0  # 簡化；實際稀薄咖啡液 ρ ≈ 1.005


def brix_to_tds_gl(brix_pct: float) -> float:
    """
    把折光儀 Brix 讀值（°Bx，% w/w 蔗糖等效）轉為 TDS [g/L]。

    What:
        TDS_pct  = Brix × 0.85
        TDS_g/L  = TDS_pct × 10 × ρ_brew  (ρ ≈ 1.0)

    Why:
        實驗室量測通常用 VST / Atago refractometer，讀值是 sucrose-equiv Brix。
        coffee 可溶物的折射率 ~ 0.85 × sucrose（specialty coffee 慣例校正因子）。
    """
    return float(brix_pct) * BRIX_TO_TDS_PCT_FACTOR * 10.0 * BREW_DENSITY_G_PER_ML


def _meta_float(meta: dict, key: str, default: float | None = None) -> float:
    """
    從 CSV metadata 取浮點數，必要時回退到預設值。

    What:
        讀取首列 metadata 的數值欄位，空字串或缺值時使用 `default`。

    Why:
        量測資料有時只缺單一欄位；集中處理可避免擬合流程散落隱性 fallback。
    """
    raw = meta.get(key)
    if raw is None or str(raw).strip() == "":
        if default is None:
            raise ValueError(f"CSV metadata 缺少必要欄位：{key}")
        return float(default)
    return float(raw)


def _project_root() -> Path:
    """Project root（與 `data/` 同層）。"""
    return Path(__file__).resolve().parents[1]


def _resolve_psd_bins_path(
    meta: dict,
    flow_csv_path: str | Path | None = None,
) -> tuple[str | None, float | None]:
    """
    決定當前 case 應使用的 measured PSD bins 路徑與診斷 D10。

    What:
        優先順序：
        1. CSV metadata `psd_bins_csv_path` 顯式指定
        2. 與 `flow_csv_path` 同目錄的 sibling `*_psd_bins.csv`（per-case PSD）
        3. fallback：`MEASURED_PSD_BINS_CSV`（legacy 低倍率掃描）
        路徑不存在時回傳 (None, None)，讓主模型走 single-bin fallback。

    Why:
        AGENTS.md §3.2：每個 case 必須用它自己的 measured PSD。
        2026-05 移除了 `CANONICAL_HIGH_RES_PSD_OVERRIDES`：該 override 讓
        canonical case 改用頂層 PSD，但頂層那份其實是**較低**倍率的掃描
        （58 μm/px vs per-case 27–29 μm/px），方向與其敘事（"high-res baseline"）
        相反；保留它等於讓 canonical case 用解析度最差的量測。
    """
    raw_path = meta.get("psd_bins_csv_path")
    bins_path: Path | None = None
    summary_path: Path | None = None

    if raw_path is not None and str(raw_path).strip() != "":
        bins_path = Path(str(raw_path))
    elif flow_csv_path is not None:
        flow_dir = Path(flow_csv_path).resolve().parent
        siblings = sorted(flow_dir.glob("*_psd_bins.csv"))
        if siblings:
            bins_path = siblings[0]
            summary_candidates = sorted(flow_dir.glob("*_psd_summary.csv"))
            if summary_candidates:
                summary_path = summary_candidates[0]

    if bins_path is None:
        bins_path = Path(MEASURED_PSD_BINS_CSV)

    if not bins_path.is_absolute():
        bins_path = _project_root() / bins_path
    if not bins_path.exists():
        return None, None

    # 診斷 D10。模型尺度不再由此決定（見 `MEASURED_D10_DIAGNOSTIC_M`）；
    # PSD summary 現在輸出 `model_d32_m` / `model_Dv50_m` 作為尺度錨點，
    # 而這兩者已經內含在 bins CSV 中，由 `V60Params` 自行整合。
    d10_raw = meta.get("D10_measured_m")
    d10_value: float | None = None
    if d10_raw is not None and str(d10_raw).strip() != "":
        d10_value = float(d10_raw)
    elif summary_path is not None and summary_path.exists():
        d10_value = _read_summary_float(summary_path, ("model_D10_m",), ("model_D10_mm",))

    if d10_value is None:
        d10_value = float(MEASURED_D10_DIAGNOSTIC_M)
    return str(bins_path), d10_value


def _read_summary_float(
    summary_path: Path,
    m_keys: tuple[str, ...],
    mm_keys: tuple[str, ...] = (),
) -> float | None:
    """
    從 PSD summary CSV 讀第一個可用的數值欄位 [m]。

    What: 依序嘗試 `m_keys`（單位 m），再嘗試 `mm_keys`（單位 mm，回傳前乘 1e-3）。
    Why:  summary 欄位隨 PSD 管線演進調整；集中一處解析可避免各呼叫端各寫一套
          fallback 鏈，同時在欄位全缺時明確回傳 None 而不是靜默給錯誤尺度。
    """
    try:
        with summary_path.open(encoding="utf-8") as f:
            row = next(csv.DictReader(f), None)
    except (OSError, StopIteration):
        return None
    if row is None:
        return None
    for key in m_keys:
        if key in row and str(row[key]).strip():
            return float(row[key])
    for key in mm_keys:
        if key in row and str(row[key]).strip():
            return float(row[key]) * 1e-3
    return None


def measured_psd_scale_m(summary_path: str | Path) -> tuple[float | None, float | None]:
    """
    讀取 PSD summary 的模型尺度錨點 (d32, Dv50) [m]。

    What: 回傳 `model_d32_m` 與 `model_Dv50_m`；缺欄回傳 None。
    Why:  showcase / 診斷需要顯示模型實際使用的粒徑尺度，而該尺度是 Sauter d32，
          不是 resolution-bounded 的 number-based D10。
    """
    path = Path(summary_path)
    if not path.is_absolute():
        path = _project_root() / path
    if not path.exists():
        return None, None
    return (
        _read_summary_float(path, ("model_d32_m",), ("model_d32_mm",)),
        _read_summary_float(path, ("model_Dv50_m",), ("model_Dv50_mm",)),
    )


def _measured_setup_overrides(
    meta: dict,
    flow_csv_path: str | Path | None = None,
) -> dict:
    """
    組裝量測可直接給定的環境、硬體與 PSD ingest 參數。

    What:
        回傳 ambient、濾杯質量/比熱、初始熱交換係數，以及 measured PSD bins
        路徑（若存在）的 override dict。

    Why:
        這些量屬於量測條件或硬體條件，不應每次在擬合內隱性漂移；measured PSD
        ingest 同樣屬於 baseline-level 設定，集中於此處可確保 fitting / benchmark
        / showcase 三條路徑使用同一份 PSD（AGENTS.md §3.2 主敘事必須走 measured PSD）。
    """
    ambient_C = _meta_float(meta, "ambient_temp_C", MEASURED_AMBIENT_TEMP_C)
    dripper_mass_g = _meta_float(meta, "dripper_mass_g", MEASURED_DRIPPER_MASS_G)
    dripper_cp_j_gk = _meta_float(meta, "dripper_cp_J_gK", MEASURED_DRIPPER_CP_J_GK)
    liquid_dripper_lambda = _meta_float(meta, "lambda_liquid_dripper", MEASURED_LIQUID_DRIPPER_LAMBDA)
    dripper_ambient_lambda = _meta_float(meta, "lambda_dripper_ambient", MEASURED_DRIPPER_AMBIENT_LAMBDA)
    server_ambient_lambda = _meta_float(meta, "lambda_server_ambient", MEASURED_SERVER_AMBIENT_LAMBDA)
    overrides: dict = {
        "T_amb": ambient_C + 273.15,
        "dripper_mass_g": dripper_mass_g,
        "dripper_cp_J_gK": dripper_cp_j_gk,
        "lambda_liquid_dripper": liquid_dripper_lambda,
        "lambda_dripper_ambient": dripper_ambient_lambda,
        "lambda_server_ambient": server_ambient_lambda,
    }
    psd_bins_path, d10_value = _resolve_psd_bins_path(meta, flow_csv_path=flow_csv_path)
    if psd_bins_path is not None:
        overrides["psd_bins_csv_path"] = psd_bins_path
        overrides["D10_measured_m"] = d10_value
    return overrides


def meta_consensus(rows: list[dict]) -> tuple[dict, list[dict]]:
    """
    由逐列重複的 meta 欄（`time_mmss` 之前的欄位）取共識值。

    What:
        對每個 meta 欄只看非空值：全部相同 → 不動；不同 → 取嚴格多數值，
        並回傳修正紀錄 `{t_s, field, old, new, rule}`（格式同 `preprocess` 的
        corrections）。沒有嚴格多數、或不一致的欄不是數值時一律 raise（Fail Fast）。
    Why:
        紀錄表的 meta 在每一列重複寫一次，舊版只讀首列。kinu29 4:12 與 kinu27 4:12
        的首列 `dripper_mass_g = 224.1`，同檔其餘 26–27 列與所有其他沖煮皆為 123.5；
        同次沖煮的影片溫度時序無法分辨兩者（分享壺溫 RMSE 皆 3.58 °C，
        2026-09-27），因此以檔內多數值為準並留下修正紀錄，而不是手改原始檔
        （原始檔為 Class A，AGENTS.md §6）。只填首列、其餘留空的欄（如
        `final_tds_pct`）只有一個非空值，不受影響。
    """
    keys = list(rows[0].keys())
    meta_keys = keys[: keys.index("time_mmss")] if "time_mmss" in keys else []
    meta = dict(rows[0])
    fixes: list[dict] = []
    for k in meta_keys:
        vals = [str(r.get(k, "") or "").strip() for r in rows]
        counts = Counter(v for v in vals if v != "")
        if len(counts) <= 1:
            continue
        mode, n = counts.most_common(1)[0]
        total = sum(counts.values())
        if 2 * n <= total:
            raise ValueError(f"meta 欄 {k} 各列不一致且沒有嚴格多數：{dict(counts)}")
        if meta[k].strip() == mode:
            continue
        try:
            old, new = float(meta[k]), float(mode)
        except ValueError as exc:
            raise ValueError(f"meta 欄 {k} 各列不一致（非數值）：{dict(counts)}") from exc
        meta[k] = mode
        fixes.append({"t_s": 0.0, "field": f"meta:{k}", "old": old, "new": new,
                      "rule": f"meta_row_consensus {n}/{total} rows"})
    return meta, fixes


def load_brew_log_csv(csv_path: str | Path) -> tuple[list[dict], dict]:
    """
    讀取實測沖煮紀錄 CSV。

    What:
        載入使用者手動整理的區段式量測資料，回傳原始列與 meta（逐列共識值，
        見 `meta_consensus`；修正紀錄由 `load_flow_profile_csv` 回傳）。

    Why:
        實驗資料常先以 CSV 留存；將 parsing 與擬合分離，後續更容易重複使用。
    """
    path = Path(csv_path)
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"空的 CSV：{path}")
    return rows, meta_consensus(rows)[0]


VIDEO_PROFILE_SUFFIX = "_flow_profile_video.csv"
LOG_PROFILE_SUFFIX = "_flow_profile.csv"


def resolve_flow_profile_path(csv_path: str | Path, source: str = "auto") -> tuple[Path, str]:
    """
    決定一個 case 實際要讀的 flow profile 檔與其來源（"video" | "log"）。

    What:
        `csv_path` 是 case 的識別路徑（慣例為紀錄表 `<stem>_flow_profile.csv`；
        summary / plot 檔名由它推導）。
        - `source="auto"`：`csv_path` 本身是影片版 → 用它；否則同目錄有
          `<stem>_flow_profile_video.csv` → 用影片版；否則同目錄恰有一份
          `*_flow_profile_video.csv` → 用它（多於一份 raise）；都沒有 → 紀錄表。
        - `source="log"`：強制紀錄表（給影片版路徑時 raise）。
        - `source="video"`：強制影片版（找不到時 raise）。
    Why:
        三個有錄影的 case，紀錄表的 drained 欄經同一支影片證實悶蒸後偏高 13–73 mL
        （F10），不得再當 Class A 擬合；但紀錄表本身仍是原始紀錄，必須保留、
        可指定讀取（前後對照、回歸測試）。影片優先放在 loader 而不是各呼叫端，
        是為了讓 fitting / benchmark / identifiability / showcase 不可能讀到不同的來源。
    """
    path = Path(csv_path)
    if source not in ("auto", "log", "video"):
        raise ValueError(f"未知的 flow profile source：{source}")
    is_video = path.name.endswith(VIDEO_PROFILE_SUFFIX)
    if source == "log":
        if is_video:
            raise ValueError(f"source='log' 但給的是影片版 profile：{path}")
        return path, "log"
    if is_video:
        return path, "video"
    stem = path.name[: -len(LOG_PROFILE_SUFFIX)] if path.name.endswith(LOG_PROFILE_SUFFIX) else path.stem
    video = path.parent / f"{stem}{VIDEO_PROFILE_SUFFIX}"
    if not video.exists():
        cands = sorted(path.parent.glob(f"*{VIDEO_PROFILE_SUFFIX}"))
        if len(cands) > 1:
            raise ValueError(f"{path.parent} 有多份影片版 profile，無法決定：{[c.name for c in cands]}")
        video = cands[0] if cands else None
    if video is not None:
        return video, "video"
    if source == "video":
        raise FileNotFoundError(f"找不到 {path} 的影片版 profile（*{VIDEO_PROFILE_SUFFIX}）")
    return path, "log"


def _optional_series(rows: list[dict], key: str) -> np.ndarray | None:
    """逐列浮點欄；整欄不存在回 None，空格為 NaN。"""
    if key not in rows[0]:
        return None
    return np.array([float(r[key]) if str(r.get(key, "")).strip() else np.nan for r in rows], dtype=float)


def load_flow_profile_csv(csv_path: str | Path, source: str = "auto") -> dict:
    """
    讀取 `V_in(t)` / `V_out(t)` 實測剖面。

    `source`（F10）：見 `resolve_flow_profile_path`；預設影片版優先。
    回傳另含（F10）：
        - `profile_source` "video" | "log"、`profile_path`（實際讀的檔）、`video_id`
        - `time_base`：`time_s` 的時間基準。紀錄表 = "scale_timer_s"（秤計時器秒，
          比真實秒快 1.86%，由 `preprocess` 換算）；影片版由 meta `time_base` 給定（"real_s"）。
        - `drained_sigma_ml`：逐點 V_out 1σ（影片版由液位偵測品質決定；紀錄表為 None）
        - `server_temp_C` / `outflow_temp_C` / `temp_flag`：同一次沖煮的溫度時序（影片版；
          紀錄表為 None）。**診斷用，不進 χ²**。

    What:
        載入逐時刻觀測，回傳 numpy 陣列與首列 metadata。除累積注水 / 出液外，
        另回傳三個擬合端需要的觀測量：

        - `retained_mass_g`：濾杯內殘留質量時序 [g]。CSV 有 `retained_mass_g`
          欄時直接使用（`retention_basis="measured"`），否則由
          `poured_weight_g − drained_volume_ml` 導出（`retention_basis="derived"`）。
        - `final_temp_read_time_s`：杯溫實際讀取時刻 [s]，掃 `phase ==
          "dripper_off_final"`；找不到時 fallback 為末列 `time_s`。
        - `stop_flow_time_s`：目視停流時刻，取 `phase == "flow_stop_visual"`。

    Why:
        流動標定需要時間序列，而不是僅靠最終端點。

        `final_temp_read_time_s`：使用者是在某個具體時刻把溫度計插進分享壺，
        不是在模擬視窗末端（t = 180 s）。硬取末值等於把額外的自然冷卻算進
        觀測，再由熱端 closure 反向補償（AUD-1-6）。

        `retained_mass_g`：床內 hold-up 時序的**診斷**量。

        **它不是獨立觀測**（F6b，2026-09-24 實測）：目前四個 case 的
        `retained_mass_g` 欄在每一列都精確等於 `poured_weight_g − drained_volume_ml`
        （max |差| = 2e-14，即浮點往返誤差）。也就是說 `retention_basis="measured"`
        只代表「CSV 有這一欄」，不代表它是獨立秤重。後果有二：
          1. `drained_volume_ml` 的任何讀值誤差會 1:1 傳進保水，兩項殘差因此
             高度相關——F6 §4.3 四個 case 的 retention RMSE 與 V_RMSE 一致到
             0.4% 以內，就是這個代數關係的直接指紋。
          2. 把保水時序放進 χ² 等於把 V_out 殘差罰兩次，並讓 `n_obs` 虛增、
             dof 算錯。**因此 F6b 已將 retention 時序項移出 loss**
             （見 `fitting.MEASUREMENT_SIGMA`），只保留為診斷與 benchmark
             的末段保水 sanity check。
        要讓保水成為真正的獨立觀測，需要在濾杯下方獨立秤重（dripper 淨重時序）；
        屆時應以它自己的 σ 加回 χ²。

    fit_mask（`use_for_fit`）與 `stop_flow_time_s` 的關係：
        `use_for_fit` **完全由 CSV 決定**，程式內不對任何 `time_s` 特判。
        kinu29 4:11 的 `flow_stop_visual`（t = 135 s）被標為 `use_for_fit=0`
        而 `dripper_off_final`（t = 142 s）為 1，兩列因此不同進退——這是資料
        端的選擇，不是程式行為；若要改需改 CSV。
        另注意 `stop_flow_time_s` 的來源列**可以**是 `use_for_fit=0` 的列：
        `use_for_fit` 管的是「這列的累積 V_out 是否進體積殘差」，而目視停流
        時刻是獨立觀測量（不同的量、不同的 σ），兩者沒有理由綁在一起。
    """
    path, profile_source = resolve_flow_profile_path(csv_path, source)
    rows, _ = load_brew_log_csv(path)
    meta, meta_corrections = meta_consensus(rows)
    t_s = np.array([float(r["time_s"]) for r in rows], dtype=float)
    v_in_ml = np.array([float(r["poured_weight_g"]) for r in rows], dtype=float)
    v_out_ml = np.array([float(r["drained_volume_ml"]) for r in rows], dtype=float)
    use_for_fit = np.array([int(r.get("use_for_fit", "1")) for r in rows], dtype=int)
    phases = [r.get("phase", "") for r in rows]
    final_cup_temp_C = float(meta["final_coffee_temp_C"]) if meta.get("final_coffee_temp_C") else None

    # 保水時序：優先用量測欄，缺欄才由 poured − drained 導出。
    if all(str(r.get("retained_mass_g", "")).strip() != "" for r in rows):
        retained_mass_g = np.array([float(r["retained_mass_g"]) for r in rows], dtype=float)
        retention_basis = "measured"
    else:
        retained_mass_g = v_in_ml - v_out_ml
        retention_basis = "derived"

    # 杯溫讀取時刻：`dripper_off_final` 那一列；沒有這個 phase 就取末列。
    final_temp_read_time_s = float(t_s[-1])
    for row in rows:
        if row.get("phase", "").strip().lower() == "dripper_off_final":
            final_temp_read_time_s = float(row["time_s"])
            break

    # 量測 Brix → TDS。CSV 欄位名為 `final_tds_pct`，實際儲存 Brix 讀值（°Bx）；
    # 套用 BRIX_TO_TDS_PCT_FACTOR=0.85 才是實際 TDS_pct。
    # 沒有量測時 final_brix_pct=None，TDS 不進 fit loss。
    final_brix_pct = (
        float(meta["final_tds_pct"]) if meta.get("final_tds_pct") and str(meta["final_tds_pct"]).strip() else None
    )
    final_tds_gl = brix_to_tds_gl(final_brix_pct) if final_brix_pct is not None else None

    stop_flow_time_s = None
    for row in rows:
        if row.get("phase", "").strip().lower() == "flow_stop_visual":
            stop_flow_time_s = float(row["time_s"])
            break
    if stop_flow_time_s is None:
        stop_flow_time_s = float(t_s[-1])

    out = {
        "rows": rows,
        "meta": meta,
        "t_s": t_s,
        "v_in_ml": v_in_ml,
        "v_out_ml": v_out_ml,
        "use_for_fit": use_for_fit,
        "phase": phases,
        "retained_mass_g": retained_mass_g,
        "retention_basis": retention_basis,
        "final_cup_temp_C": final_cup_temp_C,
        "final_temp_read_time_s": final_temp_read_time_s,
        "final_brix_pct": final_brix_pct,
        "final_tds_gl": final_tds_gl,
        "stop_flow_time_s": stop_flow_time_s,
        "profile_source": profile_source,
        "profile_path": str(path),
        "video_id": str(meta.get("source", "")).split(":", 1)[1] if str(meta.get("source", "")).startswith("video:") else "",
        "time_base": str(meta.get("time_base", "") or "scale_timer_s").strip(),
        "drained_sigma_ml": _optional_series(rows, "drained_sigma_ml"),
        "server_temp_C": _optional_series(rows, "server_temp_C"),
        "outflow_temp_C": _optional_series(rows, "outflow_temp_C"),
        "temp_flag": [r.get("temp_flag", "") for r in rows] if "temp_flag" in rows[0] else None,
        "final_coffee_temp_source": str(meta.get("final_coffee_temp_source", "") or "log_meta"),
        "meta_corrections": meta_corrections,
        # F12a：影片版的「濾杯移開」時刻（影格判讀，見 build_profile 的 annotations）與
        # 液位可讀列。`use_for_fit` = 液位可讀 ∧ 濾杯仍在壺上（可與模型 V_cup 比較）；
        # `level_visible` 只要求液位可讀（熱時序遮罩用：移開濾杯後壺內液量仍是有效量測）。
        "dripper_removed_time_s": (float(meta["dripper_removed_time_s"])
                                   if str(meta.get("dripper_removed_time_s", "") or "").strip() else None),
        "level_visible": np.array(
            [str(r.get("drained_quality", "")).strip() != "not_visible_interp" for r in rows], dtype=bool)
            if "drained_quality" in rows[0] else use_for_fit.astype(bool),
    }
    if profile_source == "video" and out["time_base"] != "real_s":
        raise ValueError(f"影片版 profile 的 time_base 必須是 real_s：{path}")
    # 品質旗標由已載入的欄位導出，因此每個讀這份 profile 的路徑都一定拿得到，
    # 不必各自再算一遍（F6b）。
    out["data_quality_flags"] = flow_profile_quality_flags(out)
    return out


def flow_profile_quality_flags(prof: dict) -> list[str]:
    """
    由已載入的 flow profile 導出量測紀錄品質旗標。

    What:
        回傳一組旗標字串（穩定排序），描述「這份紀錄缺哪些水力訊號」：

        - `mass_balance_violation`   任一列 `retained < 0`（出液多於注水）。
        - `no_post_pour_outflow`     最後一注結束之後沒有再記錄到任何出液。
        - `no_ponding_recorded`      保水峰值不比末段保水高出 2σ_ret
                                     → 紀錄上床面從未積水再排下。
        - `coarse_drained_resolution` 量筒讀值量化階 ≥ 5 mL（> σ_V = 3 mL）。
        - `no_equilibrium_row`       沒有 `dripper_off_final` 列
                                     → 末段保水取自目視停流時刻，尚未平衡。
        - `drained_log_bias_suspected` 出液來自手寫紀錄表（`profile_source == "log"`）。
                                     F10：同一紀錄法在三個有錄影的 case 上經影片證實
                                     悶蒸後偏高 13–73 mL；無影片的 case 無法修正，只能揭露
                                     （說明文字見 `DRAINED_LOG_BIAS_NOTE`）。

    Why:
        這些不是「資料錯了」的 gate，而是「這份紀錄能支持什麼結論」的界線。
        一個沒有積水、也沒有注水後滴流的紀錄，對 Darcy 滲透率幾乎沒有約束力
        （驅動水頭與末段衰減這兩段訊號都不在資料裡），`k` 會被推到邊界。
        把它寫成旗標並一路帶進 summary / benchmark CSV，是為了讓下游
        （README / index.html / EXPERIMENT_LOG）不會把這種 case 的校準值
        當成可交叉驗證的獨立結果——這是 F6b §1 的主要結論。

        門檻只有兩個且都掛在量測 σ 上（見模組頂端的 Why），不是可調參數。
    """
    t = np.asarray(prof["t_s"], dtype=float)
    v_in = np.asarray(prof["v_in_ml"], dtype=float)
    v_out = np.asarray(prof["v_out_ml"], dtype=float)
    ret = np.asarray(prof["retained_mass_g"], dtype=float)
    phases = [str(x).strip().lower() for x in prof.get("phase", [])]
    flags: list[str] = []

    if ret.size and float(np.min(ret)) < 0.0:
        flags.append("mass_balance_violation")

    # 最後一注：`poured` 有實質增加（> 0.5 g，濾掉蒸發/抖動）的最後一列。
    pour_idx = [i for i in range(1, t.size) if v_in[i] - v_in[i - 1] > 0.5]
    if pour_idx:
        last_pour = pour_idx[-1]
        if float(v_out[-1] - v_out[last_pour]) <= 0.0:
            flags.append("no_post_pour_outflow")

    if ret.size and float(np.max(ret) - ret[-1]) <= QUALITY_PONDING_MARGIN_ML:
        flags.append("no_ponding_recorded")

    incs = np.diff(v_out)
    incs = incs[incs > 0.0]
    if incs.size:
        # 量化階 = 所有正增量的最大公因數（以 0.1 mL 為單位取整後求 gcd）。
        step = 0
        for x in np.rint(incs * 10.0).astype(int):
            step = math.gcd(step, int(x))
        if step / 10.0 >= QUALITY_COARSE_DRAINED_STEP_ML:
            flags.append("coarse_drained_resolution")

    if "dripper_off_final" not in phases:
        flags.append("no_equilibrium_row")

    if prof.get("profile_source") == "log":
        flags.append("drained_log_bias_suspected")

    return sorted(flags)


def protocol_from_brew_log(rows: list[dict]) -> PourProtocol:
    """
    從區段式沖煮紀錄重建 PourProtocol。

    What:
        將每個 `pour_*` 區段轉成 `(start, volume, duration)`。

    Why:
        使用量測得到的累積重量終點，比逐列內差更能抵抗起始讀值的小幅抖動。
    """
    pours: list[tuple[float, float, float]] = []
    prev_end_g = 0.0

    for row in rows:
        end_g = float(row["weight_end_g"])
        phase = row["phase"].strip().lower()
        if phase.startswith("pour"):
            start_s = float(row["time_start_s"])
            end_s = float(row["time_end_s"])
            duration_s = end_s - start_s
            volume_ml = max(end_g - prev_end_g, 0.0)
            if duration_s <= 0:
                raise ValueError(f"無效注水區段：{row}")
            pours.append((start_s, volume_ml, duration_s))
        prev_end_g = end_g

    if not pours:
        raise ValueError("CSV 中沒有可用的注水區段（phase 必須以 pour 開頭）")
    return PourProtocol(pours=pours)


def protocol_from_cumulative_input(
    t_obs_s: np.ndarray,
    v_in_obs_ml: np.ndarray,
    min_pour_ml: float = 1.0,
) -> PourProtocol:
    """
    從累積注水曲線重建等效分段注水協議。

    What:
        將單調化後的 `V_in(t)` 差分為多段等效 constant-rate pours。

    Why:
        使用真實注水曲線重建協議，比人工估段更穩定，也能直接進 simulate_brew。
    """
    t_obs_s = np.asarray(t_obs_s, dtype=float)
    v_in_obs_ml = np.maximum.accumulate(np.asarray(v_in_obs_ml, dtype=float))
    pours: list[tuple[float, float, float]] = []

    for i in range(1, len(t_obs_s)):
        dt = float(t_obs_s[i] - t_obs_s[i - 1])
        dv = float(v_in_obs_ml[i] - v_in_obs_ml[i - 1])
        if dt <= 0:
            continue
        if dv >= min_pour_ml:
            pours.append((float(t_obs_s[i - 1]), dv, dt))

    if not pours:
        raise ValueError("無法從 V_in(t) 重建注水協議：沒有足夠的正增量")
    return PourProtocol(pours=pours)
