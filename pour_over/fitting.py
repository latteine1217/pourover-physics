"""
fitting.py — 參數擬合模組

What:
  提供兩階段反向擬合（fit_brew_params）、實測沖煮紀錄解析、
  杯中最終溫度的等效熱容反推，以及示範用流程（demo_fitting）。

Why:
  流體動力學（k, psi）與化學萃取（k_ext_coef, max_EY）在物理上解耦，
  分兩階段獨立優化可降低維度、避免高維非凸陷阱。
"""

import contextlib
import dataclasses
import csv
import itertools
import multiprocessing as mp
import os
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import minimize
from scipy.interpolate import interp1d

from .params import EXTRACTION_FIT_SPEC, V60Params, PourProtocol, RoastProfile
from .core import simulate_brew
from .measured_io import (
    MEASURED_BED_HEIGHT_CM,
    MEASURED_VESSEL_EQUIV_ML,
    MEASURED_AMBIENT_TEMP_C,
    MEASURED_LIQUID_DRIPPER_LAMBDA,
    MEASURED_PAPER_HOLDUP_ML,
    READING_TIME_SIGMA_S,
    SERVER_PROBE_IMMERSION_ML,
    _meta_float,
    _measured_setup_overrides,
    load_brew_log_csv,
    load_flow_profile_csv,
    protocol_from_brew_log,
    protocol_from_cumulative_input,
)
from .preprocess import format_corrections, preprocess_flow_profile
from .observation import (
    level_stop_time,
    mixed_cup_temperature_C,
    model_level_stop_time,
    observed_stop_time_from_layer,
    apply_outflow_lag,
)
from .viz import (
    PALETTE,
    _setup_style,
    _style_ax,
    _summary_band,
    _save_fig,
    plot_fit_residuals,
    plot_results,
    plot_retention_comparison,
    plot_thermal_video_check,
)
from .calibration_state import (
    DEFAULT_PREF_FLOW_OPEN_RATE_FIXED,
    DEFAULT_PREF_FLOW_TAU_DECAY_FIXED,
    KBETA_PRIOR_SIGMA_DEX,
)

# canonical case（F10，2026-09-27 起）：kinu29 4:12。
# What: 路徑是 case 識別路徑（紀錄表檔名）；`load_flow_profile_csv` 會自動改讀同目錄的
#       影片版 `kinu29_light_20g_flow_profile_video.csv`（見 `measured_io.resolve_flow_profile_path`）。
# Why:  與舊 canonical kinu29 4:11 同配方（Kinu 29、light、20 g、5.3 cm、23 °C），但有沖煮錄影：
#       紀錄表 drained 欄經同法三支影片證實悶蒸後偏高 13–73 mL，而 4:11 無影片、無法修正。
#       先前否定的九個「注水期缺失機制」實為擬合這個讀值誤差（F10 報告）。
DEFAULT_MEASURED_FLOW_CSV = "data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv"
# artifact 命名（F6，2026-09-24）：改用短 stem `<case>_flow_fit[.png|_summary.csv]`。
# Why: legacy stem `…_psd_clog_impactrelief_wetbedchi_180s` 把三個已被 F2b/F3 重寫或
#      移除的機制名寫進檔名，讀者無從分辨檔名描述的是不是現在的模型。
DEFAULT_MEASURED_FLOW_FIT_PLOT = "data/kinu_29_light/4:12/kinu29_light_20g_flow_fit.png"
DEFAULT_MEASURED_FLOW_FIT_SUMMARY = "data/kinu_29_light/4:12/kinu29_light_20g_flow_fit_summary.csv"


# ─────────────────────────────────────────────────────────────────────────────
#  量測不確定度、solver preset 與 loss 常數
# ─────────────────────────────────────────────────────────────────────────────
# What: 各觀測量的 1σ 量測不確定度；χ² 的唯一權重來源。
# Why:  舊 loss 是 `1.0·V_RMSE + 0.8·q_RMSE + 0.5·|Δt| + 0.35·|ΔT| + 0.6·|ΔTDS|`，
#       五項單位互不相同（mL / mL·s⁻¹ / s / °C / g·L⁻¹），權重只能靠「量級看起來
#       差不多」設定。以量測 σ 正規化後審計（AUD-4）顯示 drain / temp / TDS 三項
#       實際只佔 χ² 的 0%，等於這三個觀測根本沒有進入擬合。
#       改用 σ 正規化後每一項都是無因次，相對權重由**量測精度**決定，不再是調參。
#
# σ 的來源（2026-09-24 推導，見 docs/audit_2026-09-24.md）：
#   v_out_ml    3.0  = 量筒整數讀值 (±0.5) ⊕ 刻度精度 (±2–5)（讀值本身的 σ_V）
#   reading_time_s 1.0 = 讀取時刻的 1σ（F9，Class B，定義見
#                      `measured_io.READING_TIME_SIGMA_S`）。F9 前它被併在 σ_V 的
#                      「讀數時刻偏移」裡、當成與流率無關的常數；實際上時刻誤差造成的
#                      體積誤差 ∝ 當下出流率，因此 F9 起顯式傳播成逐點 σ：
#                        σ_V,i = sqrt(σ_V² + (q_obs,i · σ_t)²)
#                      （`preprocess.volume_sigma_ml`；q_obs 取自量測中央差分，與參數無關）。
#                      這是量測誤差的正確傳播，**不是調參**；它讓高出流段的 χ² 權重下降，
#                      χ² 因此下降是誤差模型的改變，不代表模型改善。
#                      注意：σ_V = 3.0 沿用舊值未扣除原本併入的時刻項，低出流段 σ 略偏保守。
#   stop_time_s 2.5  = 目視判定「最後一滴」的人為散布（5 s 取樣間隔的一半量級）
#   cup_temp_C  0.5  = 探針精度 (±0.2) ⊕ 插入位置/時刻造成的散布
#   tds_gl      0.72 = Brix 讀值 ±0.02 °Bx ⊕ 轉換係數 0.85 的區間 [0.79, 0.89]
#                      （係數主導：11.56 g/L × (0.89−0.79)/2/0.85 ≈ 0.68）
#   retention_ml 3.0 = poured − drained 的差值誤差（兩個秤 / 量筒讀值相減）
#
# **`retention_ml` 自 F6b（2026-09-24）起不再進 loss，只用於診斷。**
# Why：實測四個 case 的 `retained_mass_g` 欄在每一列都精確等於
#      `poured_weight_g − drained_volume_ml`（max |差| = 2e-14，浮點往返等級）。
#      `poured` 在 drawdown 段幾乎是常數，因此保水殘差就是 V_out 殘差的**線性
#      重排**（差一個負號），不是第二條獨立觀測。把它一起丟進 χ² 有兩個後果：
#        1. 同一條殘差被計兩次 → 等效於把 σ_V 砍到 3.0/√2 ≈ 2.12 mL，
#           χ² 的權重結構因此不再由量測精度決定，而是由「同一個量寫了幾欄」決定。
#        2. `n_obs` 把保水列當成新觀測 → dof 虛增 → reduced χ² 被系統性低估。
#      F6 §4.3 四個 case 的 retention RMSE 與 V_RMSE 一致到 0.4% 以內，
#      就是這個代數關係的指紋。
#      保水要成為真正的獨立觀測，需要濾杯下方的獨立秤重（dripper 淨重時序）。
#      σ 值保留在表上：診斷圖（`viz.plot_retention_comparison`）仍用它畫 ±1σ 帶。
#   server_temp_series_C 1.0（F11）= 影片 LCD 上行（分享壺溫）逐格讀值的 1σ。
#                      V1 盲測（`V1_REPORT.md` §3）：無旗標格的讀值差 ≤ 0.1 °C，但約 6% 的格
#                      有 ≥ 1 °C 誤差；再加上壺內液溫的空間不均（探頭定點 vs 瞬混節點，
#                      影片中注後 1 s 內出現 ±2–3 °C 的跳動）→ 取 1.0 °C。
#                      **有鬼影旗標的上行格一律排除**（不是放大 σ）：盲測中鬼影造成的誤差
#                      是位數混淆（個位 1|7、十位 3|4），量級 1–6 °C、非高斯重尾，無法用
#                      σ = 2 °C 的常態分布描述；排除只少 2–4 點/案（stride 5 s 格點上）。
#   outflow_temp_series_C 1.5（F11）= LCD 下行（出水口）讀值 1σ。比上行寬：探頭在出水口的
#                      滴流/水柱中，讀值同時受水柱是否連續包覆探頭影響（V1：下行 4/24 盲測
#                      差 0.4–1.0 °C，且紀錄表對照 RMS 0.8 °C 已含 −2 s 時間錯位）。
#                      是否進 χ² 由 `OUTFLOW_TEMP_SERIES_IN_CHI2` 決定（見該常數的 Why）。
MEASUREMENT_SIGMA: dict[str, float] = {
    "v_out_ml": 3.0,
    "reading_time_s": READING_TIME_SIGMA_S,   # F9：V_out σ 的時刻誤差傳播（見上方 Why）
    "stop_time_s": 2.5,
    "cup_temp_C": 0.5,
    "tds_gl": 0.72,
    "retention_ml": 3.0,   # 診斷用（±1σ 帶）；不進 χ²，見上方 Why
    "server_temp_series_C": 1.0,    # F11：分享壺溫時序（影片 LCD 上行）
    "outflow_temp_series_C": 1.5,   # F11：出水口溫時序（影片 LCD 下行）
}

# ── 影片版觀測抽樣（F10，2026-09-27）──────────────────────────────────────────
# What: 影片版 profile 為 1 s 格點；χ² 的 V_out 觀測只取每 `VIDEO_FIT_STRIDE_S` 秒一列
#       （Class B），完整 1 s 序列保留於診斷與作圖。
# Why:  (a) χ² 把各列殘差當獨立觀測。液位偵測誤差在 3–5 s 內相關（同一片泡沫、反光、
#           熱電偶線跨數格；V2 的突波剔除窗為 ±5 格），1 s 取樣會把同一個誤差重複計 3–5 次，
#           等效把 σ 除以 √3–√5、dof 灌水。
#       (b) 紀錄表是 5 s 取樣；同頻率抽樣讓 DW / lag-1 / reduced χ² 與紀錄表擬合、
#           benchmark gate 在同一個尺度上可比（DW 對取樣間隔敏感）。
VIDEO_FIT_STRIDE_S = 5.0

# ── 殘差白噪音檢定的對象（F12a，2026-09-27）───────────────────────────────────
# What: `residual_diagnostics` 吃**標準化殘差** r_i/σ_i（σ_i = 進 χ² 的逐點 σ），不是 mL 殘差。
#       另附報只取 σ_i ≤ `WHITENESS_SUBSET_SIGMA_MAX_ML` 的子序列（附報，不 gate）。
# Why:  χ² 假設 r_i/σ_i ~ i.i.d. N(0,1)，白噪音檢定必須檢定同一個量；mL 殘差讓 σ = 15 mL 的
#       外插點（悶蒸、第二注 low_extrap）以 15 倍權重主導自相關，等於用另一套權重檢定同一
#       個模型（R12 Q2 E6）。反面代價：標準化後 σ = 15 段的結構在 gate 上幾乎隱形——而第二注
#       起點的串聯潤濕缺口（R12 Q1）正落在這段，所以另報「只取 σ-class ≤ 6 mL」的 lag1/DW。
#       門檻 7.5 mL：σ 等級 4 / 6 / 15 mL 經讀取時刻傳播後（σ_t = 0.1 s、q ≤ 12 mL/s）
#       最大為 √(6² + 1.2²) = 6.1 mL，7.5 位於 6.1 與 15 之間，只切掉 15 mL 等級。
WHITENESS_SUBSET_SIGMA_MAX_ML = 7.5

# ── 出水口熱電偶「斷流」時刻（F12a 診斷，不進 χ²）─────────────────────────────
# What: 最後一注之後，下行讀值首次比前 `THERMO_BREAK_WINDOW_S` 秒中位數低 ≥ `THERMO_BREAK_DROP_C`
#       的格；往回找最後一個仍在中位數 −1 °C 以內的平台格 j，時刻取 (t_j + t_{j+1})/2。
# Why:  R12 Q3 以它當獨立的停流判據。F12a 影格複核：三支影片的這個時刻都與「濾杯被移離壺口」
#       同步（≤ 1 s，見 `<VID>_annotations.json`），所以它量到的是「使用者判定可以移開濾杯」
#       的時刻，不是液柱自行斷流。只作診斷並與移開時刻並列回報。
THERMO_BREAK_WINDOW_S = 5.0
THERMO_BREAK_DROP_C = 5.0
# summary / benchmark 共用的白噪音附報欄（F12a）。
WHITENESS_REPORT_KEYS: tuple[str, ...] = (
    "residual_diagnostics_basis",
    "residual_lag1_lowsigma", "durbin_watson_lowsigma", "n_resid_lowsigma",
    "residual_lag1_unweighted", "durbin_watson_unweighted",
)

# ── 影片熱時序進 χ² 的觀測窗（F11，2026-09-27）────────────────────────────────
# 所有遮罩只由**量測**決定（液位可見、量測 V_out、量測出流率、LCD 旗標），與參數無關，
# 否則 χ² 會隨參數跳點、optimizer 看到的是不連續函數。取樣與 V_out 同一個 stride 格點。
#
# `SERVER_SERIES_MIN_V_ML`：分享壺溫時序只取 `V_out_obs ≥` 此值的時刻（在探頭浸沒條件之外）。
#   What: 模型的 server 節點把容器等效熱容 `vessel_equivalent_ml` 從第一滴起就**全額、瞬時**
#         耦合到液體上；此門檻以下該假設被量測否定，時序點不進 χ²（仍畫在診斷圖上）。
#   Why:  與模型無關的量測能量平衡（只用影片 V_out、出水口溫、壺溫）反推壺的有效熱容
#         C_eff = V·(T_in − T_s)/(T_s − T_amb)：kinu29 4:12 與 kinu28 4:20 在 V < 100 mL 時
#         C_eff ≈ 18–30 mL，V ≥ 150 mL 後才收斂到 42–46 mL（≈ 常數 42.4）。亦即前段液體
#         只接觸壺底、壺壁尚未參與吸熱，瞬混 + 全額熱容的節點會系統性低估壺溫 5–9 °C
#         （canonical t ≈ 28–65 s）。把這段放進 χ² 會讓 U / λ_server 去補償一個熱容結構
#         誤差（AGENTS.md §3.3、§6 明文禁止「用熱容吸收」）。F11 不為此加機制；
#         目標狀態見下方 TODO。門檻取 150 mL = C_eff 首次落回 42.4 ± 10% 的液量
#         （兩案一致），是量測推得的適用域邊界（Class B），不是 fit 參數。
# F12a（2026-09-27）已檢驗並**否定**「只有潤濕壁與液體耦合」這個候選：以三支影片自洽量得的
#       壺幾何（直筒內徑 7.0 ± 0.15 cm）做零參數的濕潤面積分率 f_wet(V)，乾壁停在室溫、被潤濕時
#       以室溫焓併入（能量精確守恆），量測 C_eff 在 V = 30–100 mL 為 22–37 mL，幾何只給 7–13 mL
#       （正規化到終液位的非物理上界也只有 13–22 mL），V ≥ 125 mL 量測已平在 ≈ 42–45 mL、幾何仍線性
#       上升。套進 server 節點後 V < 150 mL 段偏差由 −3.8 / −0.8 °C 變 +10.8 / +14.1 °C（kinu29 /
#       kinu28），V ≥ 150 mL 段 +4.8 / +4.9 °C，U 掃到上界 550 仍 +3.2 / +4.2 °C（scratchpad F12a
#       `wetcouple*.json`）。亦即乾壁在前段就已大幅參與吸熱（最可能是濾杯下方半封閉頂空的蒸汽
#       冷凝），這條路徑的速率需要一個新的傳熱係數，不是零參數幾何能給的。門檻因此保留。
# TODO: 目標狀態 = 以頂空蒸汽冷凝加熱乾壁的物理閉合（傳熱係數需有獨立量測或可引用估計）取代此門檻，
#       之後改收全部浸沒後時刻。
SERVER_SERIES_MIN_V_ML = 150.0
# `OUTFLOW_PROBE_WETTING_S = 10.0`：出水口探頭在第一次出流後需數秒潤濕，悶蒸首 10 s 的
#   下行讀值是由室溫爬升的暫態（三支影片 t = 5–10 s 讀值 42–62 °C，模型 76–80 °C）。
# `OUTFLOW_SERIES_MIN_Q_MLPS = 0.5`：出水口讀值只有在**連續出流**包覆探頭時才代表流出液溫；
#   量測出流率（V_out_obs 的 ±2 s 中央差分）低於 0.5 mL/s 時為間歇滴流，探頭部分在空氣中。
OUTFLOW_PROBE_WETTING_S = 10.0
OUTFLOW_SERIES_MIN_Q_MLPS = 0.5
# `SERVER_ENERGY_CLOSURE_TOL_ML = 16.0`：分享壺探頭是否讀到「瞬混均溫」的逐案 QC。
#   What: 在時序納入點上，以**量測**能量平衡反推壺的有效熱容
#           C_eff,i = (Σ_{t≤t_i} ΔV_obs·(T_out,obs − T_amb) − V_obs,i·θ_i) / θ_i，θ_i = T_srv,obs − T_amb
#         （不含任何模型參數；壺散熱忽略，會讓 C_eff 偏高 ≤ 4 mL）。若中位數與容器常數
#         `MEASURED_VESSEL_EQUIV_ML` 相差超過此容差，判定探頭讀的不是 lumped server 節點代表的
#         瞬混均溫（壺內分層 / 探頭貼底讀到冷層），該案**整條**分享壺溫時序不進 χ²、退回單點
#         杯溫（量測在停流、壺內混合後讀取），並加旗標 `server_probe_not_mixed_mean`。
#   Why:  單一節點無法表達分層；分層殘差若進 χ²，λ_server / U 會被推到非物理值去吸收它
#         （kinu27 4:12 實測：納入時 2D 擬合給 λ_server = 3.1e-3 /s、U = 526，前者為物理估計
#         1–5e-4 的 6–30 倍，後者貼上界）。AGENTS.md §3.3：不得為補償探頭位置加機制。
#         容差 = 2σ_C：σ_C 由 σ_Ts = 1 °C 與出水口讀值系統誤差 1.5 °C 在 V ≈ 200 mL 傳播得
#         ≈ 8 mL，與 kinu29 / kinu28 在 V ≥ 150 mL 各點的實測散布（±8 mL）一致。
SERVER_ENERGY_CLOSURE_TOL_ML = 16.0
# `OUTFLOW_TEMP_SERIES_IN_CHI2 = False`：出水口溫時序**只當診斷**（F11 兩版本比較後的裁決）。
#   比較（水力固定、(U, λ_server) 2D 擬合；server 時序同一窗）：
#     (a) 只用 server 時序：U = 250（kinu29 4:12）/ 242（kinu28 4:20），兩案一致；
#     (b) 再加 outflow（σ 1.5 °C、q_obs ≥ 0.5 mL/s、無旗標、t ≥ 10 s）：U = 255 / **468**。
#   增益是真的（U 的 ±30% Δχ² span 7.4 → 22.4、7.2 → 40.7），但出水口殘差有兩案同型的結構：
#   第二注起點模型偏熱 +3…+5 °C（床內悶蒸期冷卻的舊液先被推出，單一瞬混漿體節點表達不了），
#   中後段偏冷 −2…−3 °C。這個結構把 kinu28 的 U 推高 93%、kinu29 幾乎不動——U 變成
#   「出水口殘差形狀」的函數，不再是兩案一致的界面熱導。kinu27 4:12 的下行探頭在悶蒸與
#   第二注讀 42–75 °C（其餘兩案 75–84 °C），擺位本身不可靠。改為樣本外檢查：以 server
#   時序擬出的 U 預測出水口溫，RMSE 記在 `thermal_video_outflow_*`。
OUTFLOW_TEMP_SERIES_IN_CHI2 = False

# ── Solver preset（具名，全專案共用）──────────────────────────────────────────
# What: fitting / benchmark / identifiability / __main__ 只准引用這兩組 preset。
#       兩組的**誤差控制相同**（rtol 1e-7 / atol 1e-9 / max_step 0.5，F6e 起），
#       唯一差別是觀測層的輸出網格密度 `n_eval`（720 vs 1800）。
# Why（F6c，2026-09-24）：舊 coarse 的 rtol 3e-5 / max_step 1.0 讓 RK45 的
#       **自適應步長選擇**成為目標函數的一部分，χ² 表面因此帶 ±20–30 的噪音，
#       量級與 multi-start 的 basin 間距（75）同級。實測證據（canonical
#       kinu29 4:11、F6b 發佈參數、tau_lag 0.5 s）：
#
#         k 倍率      0.99     0.995    1.00     1.005    1.01     |二階差分|max
#         舊 coarse   388.45   365.46   357.43   368.08   364.68   18.7
#         本 preset   378.23   377.60   376.09   377.29   378.36   2.7
#         fine        377.87   377.39   375.90   377.29   378.38   2.9
#
#       更直接的判別是 `tau_tort`（顆粒內曲折度）掃描：它對水力**沒有任何
#       物理回饋**，因此 χ² 的 volume 項必須是常數。舊 coarse 下該項在
#       τ_tort ∈ {5, 6.5, 8, 10} 上跳了 39.4（343.8 → 382.0 → 343.9），
#       本 preset 只有 0.73。這證明跳動來自誤差控制把萃取狀態的步長選擇
#       耦合進水力解，不是物理。
#
#       代價：每次 evaluate 0.49 s → 0.90 s（fine 1.04 s）。這個代價是必要的：
#       **所有 stage 的搜尋與接受判定都走 coarse**，而 stage 的門檻是
#       Δχ² ≤ −1.0——在噪音 ±20 的表面上，「調參」與「擲骰子」無法區分。
#       F6/F6b 的 stage 7 誤拒、bounded Powell 回傳高於起點、
#       `hydraulic_converged=False`（stage1/2 差 > 0.05）都是這個表面的症狀。
#       範圍界定：`profile_ci` 與 `identifiability` 本來就走 fine，它們的
#       Δχ² 交點與 span 分級**不曾**受此噪音污染；受污染的是它們所環繞的
#       那個 fit 解本身。
#
#       歷史（F6c）：rtol 1e-6 把噪音從 ±20 降到 ±3–6，但沒有消除。
#       在 F6c 以本 preset 擬合出的 canonical 解上，k ±1% 掃描出現 −6 的凹陷
#       （二階差分 8.3），而 rtol 1e-8 參考解顯示真實表面沿 k 單調（0.34）：
#       optimizer 停在噪音凹陷上。rtol 1e-7 / atol 1e-9 在新舊兩點都平滑
#       （0.47 / 0.40，~1.3 s/eval）。目標狀態：兩組 preset 改 rtol 1e-7 /
#       atol 1e-9 並重擬四 case（只改 preset 不重擬 = 發佈 artifact 不可重現）；
#       （F6e 已升級 preset 並移除 `tests/test_chi2_smoothness.py` 的 expectedFailure；重擬待下一輪。）
#       F6d 補充：上表「本 preset 0.73」與 F6c 的 0.99 都是在惰性 ξ_pref 仍演化時
#       量的——它的暫態等於一個隱形的步長上限。F6d 讓惰性狀態停止演化後，
#       canonical 的 volume-vs-τ_tort span 在 rtol 1e-6 為 13.17、rtol 1e-7 為 0.97；
#       同一點上 U 171.9 → 194 讓 1e-6 的 χ² +12.8，而 rtol 1e-8 參考值只差 −0.31。
#       rtol 1e-6 的殘留噪音比 F6c 估的 ±3–6 大，升級 1e-7 的理由因此更強。
#
#       `n_eval` 維持 720：AUD-6 實測 720 → 1800 只改變觀測層插值 0.03 mL，
#       而 fine 之所以保留 1800，是為了讓發佈的 final / CI 數字不受插值影響。
# F6e（2026-09-24，主控者裁決）：兩組 preset 升級為 rtol 1e-7 / atol 1e-9。
#       發佈的四 case 參數值是在 rtol 1e-6 的表面上擬出的（殘留噪音 ±7–13），
#       本次**未重擬**，只以新容差重新評估並改寫 summary 的指標欄
#       （summary 記 `fit_solver_rtol=1e-6`、`solver_rtol_eval=1e-7`）。
#       目標狀態：下一輪 multi-start 以本 preset 重擬四 case。
# F13-C（2026-09-28）：rtol 1e-7 下殘留的 0.07–0.17 路徑噪音來自單段積分跨過注水率斷點，
#       不是容差不足；`core._solve_piecewise` 分段積分後噪音 ~1e-8，rtol 1e-7 的 χ² 截斷誤差
#       4e-5（單段需 rtol 1e-10 才達到）。preset 不變。
SOLVER_COARSE: dict = {"n_eval": 720, "rtol": 1e-7, "atol": 1e-9, "max_step": 0.5}
SOLVER_FINE: dict = {"n_eval": 1800, "rtol": 1e-7, "atol": 1e-9, "max_step": 0.5}

# ── prior 中心與區間 ─────────────────────────────────────────────────────────
# U_liquid_dripper：濕濾紙 + 陶瓷串聯的自然對流/接觸熱導（F2 §4）。
U_LIQUID_DRIPPER_PRIOR_W_M2K = 194.0
U_LIQUID_DRIPPER_PRIOR_SIGMA_DEX = 0.20      # ≈ 因子 1.6，涵蓋 [120, 550] 的大部分
U_LIQUID_DRIPPER_BOUNDS_W_M2K = (120.0, 550.0)
# What: `U_liquid_dripper_W_m2K` 自 F6d 起**凍結**在 prior 中心，不再是 fit 自由度。
# Why:  AGENTS.md §6「CI 兩端皆 None → 在 ±2× 內不可辨識，應凍結」。F6c 實測
#       canonical（唯一有杯溫的 case）的 profile CI 為 None / None，thermal
#       identifiability ±20% / ±40% 的 Δχ² 只有 2.86 / 4.83（weak，且落在 rtol 1e-6
#       的殘留噪音 ±3–6 內）。F6c stage 5/6 的 Δχ² −11.8 幾乎全來自 λ_server 由 0
#       打開（server 散熱開/關），不是 U 被資料識別。只有一個終點杯溫觀測時，
#       U 與 λ_server 共用同一個自由度；凍結 U、只擬 λ_server 才與資訊量一致。
#       prior 項仍保留在 χ² 裡：凍結在中心上恆為 0，作用同 `k_beta` 的 tripwire。
#       要重新開放 U 需要杯溫**時序**（F6b §9-6），不是更寬的 bounds。
# F11（2026-09-27）：影片 case 有分享壺溫時序後，U 在時序 loss 下為 hard → 對這些 case
#       解凍（`THERMAL_SERIES_FIT_PARAMS`）；本常數只剩兩個角色：stage 5 的起點，與
#       只有單點杯溫的 case（kinu29 4:11）的凍結值。
U_LIQUID_DRIPPER_FIXED_W_M2K = U_LIQUID_DRIPPER_PRIOR_W_M2K

# tau_lag：濾杯出口 → 壺內液面的暫存體積時間常數。
# 決策（A 段要求二擇一）：**加弱 log-space prior 並與 stage 1/2 聯合擬合**，
# 不改為幾何固定。理由：
#   (a) 幾何固定需要「濾杯頸 + 濾紙尖端滯留體積」的獨立量測，目前沒有；
#       用圓錐幾何硬推等於再造一個沒有觀測支持的常數。
#   (b) AUD-3-3 顯示 tau 幾乎只由 stop time 識別，而 σ_stop = 2.5 s 之後該項
#       在 χ² 中很弱 → 無約束的 tau 會漂到邊界（舊版正是漂到 2.0 s 的網格上界）。
#   (c) 0.3 dex ≈ 因子 2 的 prior 把 tau 綁在 0.5–2 s 的物理量級內，同時仍允許
#       停流時間把它推開——這是「弱先驗 + 資料主導」而不是固定值。
TAU_LAG_PRIOR_S = 1.0
TAU_LAG_PRIOR_SIGMA_DEX = 0.30
TAU_LAG_BOUNDS_S = (0.2, 6.0)

# ── F6b（2026-09-24）自由度重配：tau_lag 退出 fit，降為 Class B 固定值 ─────────
# What: `tau_lag` 不再是 live 參數，一律固定為 `TAU_LAG_FIXED_S`。
# Why:  F6 §6.1 的 identifiability 判定 `tau_lag_s` 為 **weak**
#       （local span 1.32、wide span 3.06，皆 < 1σ_corrected = 12.85），
#       而四個 case 中有兩個把它推到下界 0.2 s。「資料分辨不出 + 撞界」的組合
#       只有一種讀法：它在吸收別的誤差（F6 §8-1）。
#       固定值 0.5 s 的依據是**幾何**而非擬合：V60 出口至量筒液面的滴落與
#       壺底鋪展時間，對 ~1.5 mm 孔口與 ~10 cm 落差是 O(0.1–1 s)。
#       它是 Class B（可由量測計算後固定），不是 Class C（可標定 closure）。
#       **同時移除 χ² 中的 tau_lag prior 項**：prior 描述的是「自由參數的外部
#       資訊」；對一個凍結值加 prior 只是往 χ² 加一個常數，而且中心 1.0 s 與
#       凍結值 0.5 s 不同，那個常數（+1.01）還會懲罰我們自己選定的物理錨點。
TAU_LAG_FIXED_S = 0.5

# tau_wet_s：F2b 的潤濕狀態 w 的建立時間常數（Class C）。
# Why 仍進 fit：F13-B profile（2026-09-28）顯示 kinu27 / kinu28 兩側可辨識，canonical 只有上側可辨識。
#     識別資訊來自 V_out 曲線，以第三注之後的注水期與排水段為主，悶蒸窗幾乎不約束；
#     不是 F2b 原寫的 `retained_mass_g` 時序（該項自 F6b 起已不在 χ² 內）。
#     三案值差一個數量級，與「悶蒸潤濕時間」的名義不符，屬結構問題（experiment log F13-B）。
# bounds：下界 10 s 無獨立物理依據，但放寬只換到 canonical Δχ² 0.44，且拉力來自第二注重啟窗
#     （已知結構缺陷，F13 診斷），故不放寬。起點 25 s 取自 F2b 的參考點。
TAU_WET_BOUNDS_S = (10.0, 60.0)
TAU_WET_INIT_S = 25.0

# ── sat_rel_perm_exp：Corey 相對滲透率指數（F6b 起進 fit）────────────────────
# What: `kr = smoothstep(S_e)^n` 的指數 n，stage 1/2 的 live 參數之一。
# Why 它必須進 fit：F6 §6.1 判定它為 **hard**（local span 17.84、wide span 62.36，
#     後者已超過 hard 門檻 49.34）——資料能以 95% 信心分辨它——**但它被凍結在
#     3.0**，同時兩個資料分不出來的參數（`k_beta`、`tau_lag`）卻在被擬合。
#     這是自由度與資訊量的直接錯配（F6 §8-1），F6b 予以對調。
# bounds [1.5, 6.0]：Corey/Brooks-Corey 指數的物理區間。下界 1.5 而非 1.0 是因為
#     n → 1 代表 kr 與飽和度線性，失去非飽和導水的衰減語意（且 `params.py` 的
#     `kr` 實作本身對 n 取 max(n, 1.0) 硬底，掃到 1.0 以下不會有任何響應）。
#     上界 6.0 涵蓋文獻對細顆粒床的上限。
# prior 中心 3.0、σ 0.20 dex：3.0 是 Corey 對均勻球堆的經典值，也是本專案先前的
#     凍結值；0.20 dex ≈ 因子 1.6，足以讓資料把它推到 [1.9, 4.7] 而不必付 1σ，
#     同時擋住漂到 bounds 端點。
SAT_REL_PERM_EXP_BOUNDS = (1.5, 6.0)
SAT_REL_PERM_EXP_INIT = 3.0
SAT_REL_PERM_EXP_PRIOR = 3.0
SAT_REL_PERM_EXP_PRIOR_SIGMA_DEX = 0.20

# ── 水力參數搜尋區間 ─────────────────────────────────────────────────────────
# What: stage 1/2 的 log-space bounds。**bounds 是搜尋範圍，不再同時是 penalty**。
# Why:  舊版 `phys_penalty` 的區間與 optimizer bounds 完全相同，因此該 penalty
#       恆為 0（AUD-6）——它是一段永遠不執行的程式碼，卻讓人以為 loss 裡有
#       物理約束。移除 penalty、保留 bounds，並把真正的軟約束交給 PSD prior。
#       k 上界放寬到 1e-9：F2 的驅動頭結構變更使 k 需上調 ~4.5×（~3.6e-10），
#       F2b 若引入 `tau_wet_s` 還可能再移動一個量級。
K_BOUNDS_M2 = (2.0e-11, 1.0e-9)
K_BETA_BOUNDS = (5.0e2, 6.0e3)
LAMBDA_SERVER_BOUNDS = (1.0e-5, 1.0e-2)

# ── 熱端自由度（stage 5；F11 依觀測類型分流）─────────────────────────────────
# 只有單點杯溫（紀錄表 case，如 kinu29 4:11）：F6d 配置不變，只擬 λ_server。
THERMAL_SINGLE_POINT_FIT_PARAMS: tuple[str, ...] = ("lambda_server_ambient",)
# 有分享壺溫時序（影片 case）：U 解凍；λ_server 凍結在物理估計；λ_cool / λ_dripper_ambient 仍凍結。
# Why（F11 thermal identifiability，時序 loss、水力 / 萃取固定）：
#   1. 在 F10 參數點的 ±15/±30% conditional slice（canonical）：U wide span 7.39 → hard、
#      λ_server 1.90 → medium、λ_cool 0.48 / λ_dripper_ambient 0.35 → weak（kinu28 同分級）。
#   2. 但 (U, λ_server) 2D 聯擬後，canonical 的 λ_server conditional CI 為 **None / None**
#      （±2× 內不可辨識，AGENTS.md §6 → 應凍結），U 的 CI 為 [220, 432]。
#   3. 嚴格 profile（每點重擬另一參數）揭露兩者是一條 ridge：U↑ 與 λ_server↓ 互換
#      （出水口較冷 ⇔ 壺散熱較少），λ_server 在 [5e-5, 8e-4] 內 profile Δχ² ≤ 1.2（兩案）。
#      壺溫時序在 t ≥ 90 s 的資訊只撐得起一個熱端自由度——與 F6d 單點杯溫同一結論，
#      差別在於時序讓「保留哪一個」有了依據：conditional slice 下 U 可辨識、λ_server 不可。
#   → U 進 fit（log，prior 194 / 0.20 dex，bounds [120, 550]）；λ_server 凍結為
#     `LAMBDA_SERVER_SERIES_FIXED_PER_S`（見其 Why）。
THERMAL_SERIES_FIT_PARAMS: tuple[str, ...] = ("U_liquid_dripper_W_m2K",)
# `LAMBDA_SERVER_SERIES_FIXED_PER_S = 3.7e-4`：影片 case 的分享壺散熱係數（凍結值，Class D 物理估計）。
#   What: 250 mL 液體 + 42.4 mL 容器當量（C ≈ 1.22 kJ/K）的 HARIO SCI 500 mL 壺、上方壓著濾杯。
#   Why:  由熱阻估算：濕壁外側自然對流 ~8 + 輻射 ~7 W/(m²K) × 濕壁 0.012 m² ≈ 0.19 W/K；
#         液面蒸發與未濕壁面凝結（影片可見起霧）在濾杯半封閉下 ≈ 0.15–0.3 W/K
#         → λ ≈ 0.35–0.5 W/K ÷ 1.22 kJ/K ≈ 2.9–4.1e-4 /s。取 3.7e-4 = 專案既有的 Newton 冷卻估算
#         （`params.lambda_cool`：熱咖啡 ~1.5 °C/min、ΔT 68 K），落在上式區間中段。
#         三案擬合值不能當依據：F10 的 λ_server 5.0e-4 / 1.5e-3 / 1.0e-3 差 3 倍，是它在吸收
#         U 與（kinu27）壺內分層；本值位於 canonical profile 的平谷內（Δχ² ≤ 0.2），
#         kinu28 的 profile 代價 ≈ +1.0。
LAMBDA_SERVER_SERIES_FIXED_PER_S = 3.7e-4
THERMAL_FIT_BOUNDS: dict[str, tuple[float, float]] = {
    "U_liquid_dripper_W_m2K": U_LIQUID_DRIPPER_BOUNDS_W_M2K,
    "lambda_server_ambient": LAMBDA_SERVER_BOUNDS,
}
# seed 網格：λ_server 沿用 F6 的六點（單點 case 因此逐位元重現舊行為）；
# U 取 bounds 內 log 均勻的四點（含 prior 中心 194）。
THERMAL_FIT_SEEDS: dict[str, tuple[float, ...]] = {
    "lambda_server_ambient": (1.0e-5, 2.0e-4, 5.0e-4, 1.0e-3, 2.0e-3, 4.0e-3),
    "U_liquid_dripper_W_m2K": (130.0, 194.0, 300.0, 450.0),
}

# ── 合法性 gate ──────────────────────────────────────────────────────────────
# 熱模型溫度 clip 若在 > 1% 的輸出點作用，該參數組的解已不是原方程的解。
CLIP_ACTIVE_FRACTION_MAX = 0.01
CLIP_PENALTY_CHI2 = 1.0e4

# stage 接受條件：Δχ² ≤ −1.0（1σ 等級的實質改善），取代舊的三種尺度 guard
# （+0.15 mL / +0.20 mL / +0.5 pt）與零餘裕的嚴格 `<`。
STAGE_ACCEPT_DELTA_CHI2 = -1.0

# stage 7（萃取）啟動前的水力自洽條件：模型末端 V_out 與量測差 ≤ 5%。
# Why: TDS = M_extracted / V_out。若 V_out 本身偏 9%，stage 7 會用萃取參數去
#      吸收水力誤差（AGENTS.md §6 明文禁止）。
STAGE7_V_OUT_TOLERANCE = 0.05

# ── stage 7 可擬參數表（F3 介面）─────────────────────────────────────────────
# What: `(參數名, 變換, 下界, 上界)`；stage 7 完全由這張表驅動。
# Why:  萃取端正由 F3 重寫，可擬參數名稱尚未定案。把 stage 7 做成表驅動後，
#       F3 落地時只需改這一行，不必再動 optimizer 流程。
#       `max_EY` 已**移出** fit：它是 roast-driven prior（AGENTS.md §4.D），
#       舊流程讓它一路撞上 0.35 / 0.40 clip，實際上是在用 roast 參數吸收
#       萃取 closure 的結構誤差。
#       變換目前只支援 "log10"（正定參數）與 "linear"。
#       F3（2026-09-24）落地：萃取閉合重寫後唯一的 live 參數是 `tau_tort`
#       （顆粒內有效曲折度）。規格由 `params.EXTRACTION_FIT_SPEC` 單一來源提供，
#       其中另含 prior 中心與 σ[dex]（見該常數的 Why）。
EXTRACTION_FIT_PARAMS: list[tuple[str, str, float, float]] = [
    (name, transform, lo, hi) for name, transform, lo, hi, *_ in EXTRACTION_FIT_SPEC
]
# {參數名: (prior 中心, prior σ [dex])}——`EXTRACTION_FIT_SPEC` 的第 5/6 欄。
# What: 萃取 closure 參數的 log-space prior，直接進 χ²。
# Why:  spec 宣告 prior 中心與 σ 的用意就是讓 χ² 有一個物理錨點
#       （例如 `tau_tort` 的文獻曲折度 2–10 → 中心 5、σ 0.35 dex）。
#       若只讀 bounds 不讀 prior，stage 7 就會在整個 [1, 100] 上自由漂移，
#       等於把「刻意放寬到不合理區以便觀察失敗」的上界當成可用範圍。
EXTRACTION_FIT_PRIORS: dict[str, tuple[float, float]] = {
    spec[0]: (float(spec[4]), float(spec[5]))
    for spec in EXTRACTION_FIT_SPEC
    if len(spec) >= 6 and spec[1] == "log10" and float(spec[5]) > 0.0
}

# 預設 live 參數個數，用於 reduced χ² 的 dof。
# F6b 自由度重配後的 live 集合：
#   stage 1/2  k, sat_rel_perm_exp, tau_wet_s
#   stage 5    lambda_server_ambient（F6d：U_liquid_dripper 凍結，見 U_LIQUID_DRIPPER_FIXED_W_M2K）
#   stage 7    EXTRACTION_FIT_PARAMS（目前 tau_tort）
# `k_beta`（凍結為 PSD prior）、`tau_lag`（凍結為 TAU_LAG_FIXED_S）與
# `U_liquid_dripper_W_m2K`（凍結為 prior 中心）**不計入**：
# 凍結參數不消耗自由度，繼續把它們算進 dof 會系統性低估 reduced χ²。
DEFAULT_LIVE_PARAM_COUNT = 4 + len(EXTRACTION_FIT_PARAMS)


def residual_diagnostics(residuals: np.ndarray) -> dict:
    """
    殘差序列的結構性檢定（自相關 / Durbin-Watson / runs test）。

    What:
        回傳 `lag1`（lag-1 自相關）、`durbin_watson`、`runs_z`。

    Why:
        χ² 只回答「殘差有多大」，不回答「殘差是不是白噪音」。AUD-1-6 實測
        V 殘差 lag-1 = 0.914、DW = 0.169、runs z = −3.89，代表殘差是**結構誤差**
        而非量測噪音——此時再壓低 RMSE 只是在用參數描一條系統性偏掉的曲線。
        這三個數是 benchmark gate 的一部分，而不是事後才看的附註。

        判讀：白噪音 → lag1 ≈ 0、DW ≈ 2、|runs_z| < 2。
        DW < 1 或 lag1 > 0.5 代表正自相關（模型在某段一路偏同一邊）。
    """
    r = np.asarray(residuals, dtype=float)
    n = r.size
    out = {"lag1": float("nan"), "durbin_watson": float("nan"), "runs_z": float("nan")}
    if n < 3:
        return out

    r_c = r - float(np.mean(r))
    denom = float(np.sum(r_c ** 2))
    if denom > 1e-30:
        out["lag1"] = float(np.sum(r_c[1:] * r_c[:-1]) / denom)
        out["durbin_watson"] = float(np.sum(np.diff(r) ** 2) / denom)

    # Wald–Wolfowitz runs test（以中位數為分界，避免被離群值拉偏）
    med = float(np.median(r))
    signs = np.sign(r - med)
    signs = signs[signs != 0.0]
    n_pos = int(np.sum(signs > 0))
    n_neg = int(np.sum(signs < 0))
    n_tot = n_pos + n_neg
    if n_pos > 0 and n_neg > 0 and n_tot > 1:
        runs = 1 + int(np.sum(signs[1:] != signs[:-1]))
        mu = 2.0 * n_pos * n_neg / n_tot + 1.0
        var = (2.0 * n_pos * n_neg * (2.0 * n_pos * n_neg - n_tot)) / (n_tot ** 2 * (n_tot - 1.0))
        if var > 1e-30:
            out["runs_z"] = float((runs - mu) / np.sqrt(var))
    return out


def _stride_mask(t_s: np.ndarray, stride_s: float) -> np.ndarray:
    """時間落在 `stride_s` 整數倍（±1e-6 s）上的列。"""
    t = np.asarray(t_s, dtype=float)
    r = np.mod(t, float(stride_s))
    return (r < 1e-6) | (float(stride_s) - r < 1e-6)


def server_energy_closure_c_eff_ml(
    *,
    t_full: np.ndarray,
    v_out_full: np.ndarray,
    server_obs: np.ndarray,
    outflow_obs: np.ndarray,
    ambient_temp_C: float,
) -> np.ndarray:
    """
    純量測的分享壺有效熱容 C_eff(t) [mL 水當量]（F11）。

    What: C_eff = (Σ ΔV_obs·(T_out,obs − T_amb) − V_obs·θ) / θ，θ = T_srv,obs − T_amb。
          出水口探頭潤濕前（t < OUTFLOW_PROBE_WETTING_S）的讀值以其後 10 s 的中位數代替。
    Why:  瞬混 + 全額容器熱容的 server 節點成立時，C_eff 應等於容器常數；它是與模型參數
          無關的觀測算子適用性檢查（見 `SERVER_SERIES_MIN_V_ML`、`SERVER_ENERGY_CLOSURE_TOL_ML`）。
    """
    t = np.asarray(t_full, dtype=float)
    to = np.asarray(outflow_obs, dtype=float).copy()
    wet = float(OUTFLOW_PROBE_WETTING_S)
    ref = to[(t >= wet) & (t <= wet + 10.0) & np.isfinite(to)]
    to[t < wet] = float(np.median(ref)) if ref.size else np.nan
    to = np.where(np.isfinite(to), to, np.nan)
    to = np.interp(t, t[np.isfinite(to)], to[np.isfinite(to)]) if np.any(np.isfinite(to)) else to
    v = np.asarray(v_out_full, dtype=float)
    dv = np.clip(np.diff(v, prepend=0.0), 0.0, None)
    h = np.cumsum(dv * (to - float(ambient_temp_C)))
    theta = np.asarray(server_obs, dtype=float) - float(ambient_temp_C)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(theta > 1.0, (h - v * theta) / theta, np.nan)


def _thermal_series_masks(
    *,
    t_full: np.ndarray,
    v_out_full: np.ndarray,
    level_ok_full: np.ndarray,
    sel: np.ndarray,
    server_obs: np.ndarray | None,
    outflow_obs: np.ndarray | None,
    temp_flag: list[str] | None,
    stop_flow_time_s: float,
    video_id: str,
    ambient_temp_C: float = MEASURED_AMBIENT_TEMP_C,
    vessel_equivalent_ml: float = MEASURED_VESSEL_EQUIV_ML,
) -> dict:
    """
    影片熱時序進 χ² 的觀測點（F11）；只依量測決定，與參數無關。

    What:
        回傳完整 1 s 格點上的布林遮罩：
          `server_series_mask_full`  = stride 格點 ∧ 液位可見 ∧ V_obs ≥ V_immersion
                                       ∧ V_obs ≥ SERVER_SERIES_MIN_V_ML ∧ 上行無旗標 ∧ 有讀值
          `outflow_series_mask_full` = stride 格點 ∧ 液位可見 ∧ t ≥ OUTFLOW_PROBE_WETTING_S
                                       ∧ t ≤ 目視停流 ∧ q_obs ≥ OUTFLOW_SERIES_MIN_Q_MLPS
                                       ∧ 下行無旗標 ∧ 有讀值
        以及各條件單獨排除的點數（稽核用）與 `v_immersion_ml`。
        分享壺溫時序再過一道逐案 QC（量測能量閉合，`SERVER_ENERGY_CLOSURE_TOL_ML`）：
        不過 → 整條時序排除、`server_series_qc = "server_probe_not_mixed_mean"`。
        沒有溫度時序（紀錄表 case）→ 兩個遮罩皆為全 False、`v_immersion_ml = None`。
    Why:
        探頭浸沒前讀的不是液溫（`measured_io.SERVER_PROBE_IMMERSION_ML`）；
        容器熱容未完全耦合前 server 節點不適用（`SERVER_SERIES_MIN_V_ML`）；
        出水口探頭只有在連續出流時才讀到流出液溫；鬼影格誤差重尾（`MEASUREMENT_SIGMA`）。
        有溫度時序卻查不到 V_immersion → raise（Fail Fast：不得默默收進浸沒前的點）。
    """
    n = t_full.size
    empty = np.zeros(n, dtype=bool)
    out = {"server_series_mask_full": empty, "outflow_series_mask_full": empty.copy(),
           "v_immersion_ml": None, "server_series_excluded": {}, "outflow_series_excluded": {},
           "server_series_qc": "no_series", "server_energy_closure_c_eff_ml": None}
    if server_obs is None or outflow_obs is None:
        return out
    if video_id not in SERVER_PROBE_IMMERSION_ML:
        raise ValueError(f"影片 `{video_id}` 有分享壺溫時序，但 `SERVER_PROBE_IMMERSION_ML` 沒有它的 "
                         "V_immersion；請先由錄影判定探頭浸沒液量（見 measured_io 該常數的 Why）")
    v_imm = float(SERVER_PROBE_IMMERSION_ML[video_id])
    level_ok = np.asarray(level_ok_full, dtype=bool)
    v_obs = np.asarray(v_out_full, dtype=float)
    base = np.asarray(sel, dtype=bool) & level_ok

    srv_cond = {
        "below_immersion": v_obs >= v_imm,
        "vessel_not_coupled": v_obs >= float(SERVER_SERIES_MIN_V_ML),
        "lcd_flag": _channel_unflagged(temp_flag, "U", n),
        "no_reading": np.isfinite(server_obs),
    }
    # 量測出流率：±2 s 中央差分（窗寬 4 s < stride 5 s → 相鄰取樣點的差分窗不重疊）。
    q_obs = np.full(n, np.nan)
    if n > 4:
        q_obs[2:-2] = (v_obs[4:] - v_obs[:-4]) / np.maximum(t_full[4:] - t_full[:-4], 1e-9)
    out_cond = {
        "probe_wetting": t_full >= float(OUTFLOW_PROBE_WETTING_S),
        "after_stop": t_full <= float(stop_flow_time_s),
        "low_outflow": np.nan_to_num(q_obs, nan=0.0) >= float(OUTFLOW_SERIES_MIN_Q_MLPS),
        "lcd_flag": _channel_unflagged(temp_flag, "L", n),
        "no_reading": np.isfinite(outflow_obs),
    }

    def _combine(cond: dict) -> tuple[np.ndarray, dict]:
        m = base.copy()
        excluded = {}
        for name, c in cond.items():
            excluded[name] = int(np.sum(m & ~c))   # 依序套用：該條件新排除的點數
            m &= c
        return m, excluded

    out["server_series_mask_full"], out["server_series_excluded"] = _combine(srv_cond)
    out["outflow_series_mask_full"], out["outflow_series_excluded"] = _combine(out_cond)
    out["v_immersion_ml"] = v_imm

    # ── 逐案 QC：探頭讀值是否滿足瞬混節點的量測能量閉合（見 SERVER_ENERGY_CLOSURE_TOL_ML）──
    c_eff = server_energy_closure_c_eff_ml(
        t_full=t_full, v_out_full=v_obs, server_obs=server_obs, outflow_obs=outflow_obs,
        ambient_temp_C=ambient_temp_C)
    m_srv = out["server_series_mask_full"]
    c_med = float(np.median(c_eff[m_srv])) if np.any(m_srv) else float("nan")
    out["server_energy_closure_c_eff_ml"] = c_med
    out["server_series_qc"] = "ok"
    if np.isfinite(c_med) and abs(c_med - float(vessel_equivalent_ml)) > float(SERVER_ENERGY_CLOSURE_TOL_ML):
        out["server_series_excluded"]["energy_closure"] = int(m_srv.sum())
        out["server_series_mask_full"] = np.zeros(n, dtype=bool)
        out["server_series_qc"] = "server_probe_not_mixed_mean"
    out["q_obs_centered_full_mlps"] = q_obs
    return out


def _prepare_measured_case(
    csv_path: str | Path,
    *,
    preprocess: bool = True,
    source: str = "auto",
) -> dict:
    """
    把一個 measured flow case 整理成 χ² 評估所需的固定輸入。

    What:
        載入 CSV、重建 `PourProtocol`、算好觀測遮罩與區間流速，回傳一個
        與參數無關的 case bundle。

    Why:
        同一個 case 在一次 fit 中會被評估數百次；把「與參數無關的部分」抽出來
        只做一次，同時讓 `evaluate_measured_flow_fit` 與 fit 主流程的 loss
        吃**完全同一份**前處理（消除舊版兩處各寫一遍的雙實作）。

    `preprocess`（F9，預設 True）：
        走 `preprocess.preprocess_flow_profile` 的量測預處理（時間基準換算、注水率
        上限重建、秤/量筒單調化、讀取時刻 σ 傳播）。注水協議改由預處理的
        `pour_knots` 建立（含重建插入的注水起點）。`False` 只供前後對照與回歸測試：
        它重現 F9 前的行為（raw 注水曲線 + 常數 σ_V + 不換算時間基準）。

    `source`（F10）：傳給 `load_flow_profile_csv`；預設影片版優先，`"log"` 強制紀錄表。

    影片版的觀測抽樣（F10）：
        注水協議、停流時刻、杯溫讀取時刻都用完整 1 s 資料；**χ² 的觀測列**只取
        `VIDEO_FIT_STRIDE_S` 格點（見該常數的 Why）。完整 1 s 序列以 `*_full` 鍵保留，
        供診斷與作圖；`t_obs` 等鍵一律是進 χ² 的抽樣序列。
    """
    raw = load_flow_profile_csv(csv_path, source=source)
    if preprocess:
        prof = preprocess_flow_profile(raw, sigma_v_ml=MEASUREMENT_SIGMA["v_out_ml"])
        pour_knots = prof["pour_knots"]
        sigma_v_full = np.asarray(prof["sigma_v_ml"], dtype=float)
    else:
        prof = raw
        pour_knots = None
        sigma_v_full = np.full(len(raw["t_s"]), MEASUREMENT_SIGMA["v_out_ml"], dtype=float)
    meta = prof["meta"]
    t_full = np.asarray(prof["t_s"], dtype=float)
    v_in_full = np.maximum.accumulate(np.asarray(prof["v_in_ml"], dtype=float))
    v_out_full = np.asarray(prof["v_out_ml"], dtype=float)
    retained_full = np.asarray(prof["retained_mass_g"], dtype=float)
    fit_mask_full = np.asarray(prof["use_for_fit"], dtype=bool)
    if pour_knots is None:
        pour_knots = list(zip(t_full, v_in_full))

    is_video = raw["profile_source"] == "video"
    protocol = PourProtocol.from_cumulative_profile(pour_knots)
    # F12a：停流觀測算子。影片 case = 液位運算子（與 build_profile 同一函式、同一常數、
    # 同一有效格點）；紀錄表 case = 目視最後一滴（CSV 的 flow_stop_visual 列，模型端 q 門檻）。
    stop_csv_s = float(prof["stop_flow_time_s"])
    if is_video:
        stop_operator = "level"
        stop_obs_s = level_stop_time(t_full, v_out_full, fit_mask_full, protocol.last_pour_end())
    else:
        stop_operator = "q_threshold"
        stop_obs_s = stop_csv_s
    level_visible_full = np.asarray(prof.get("level_visible", fit_mask_full), dtype=bool)
    dripper_removed_s = prof.get("dripper_removed_time_s")
    # 出水口探頭讀到出流的窗止於濾杯移開（有標註時）；否則止於停流觀測。
    outflow_end_s = float(dripper_removed_s) if dripper_removed_s is not None else stop_obs_s
    stride_s = float(VIDEO_FIT_STRIDE_S) if is_video else None
    sel = _stride_mask(t_full, stride_s) if is_video else np.ones(t_full.size, dtype=bool)
    t_obs = t_full[sel]
    fit_mask = fit_mask_full[sel]
    dt_obs = np.diff(t_obs)
    v_out_obs = v_out_full[sel]

    def _temp(key: str) -> np.ndarray | None:
        val = prof.get(key)
        return None if val is None else np.asarray(val, dtype=float)

    # F11：影片熱時序進 χ² 的觀測點（量測決定的遮罩；紀錄表 case 為全 False）。
    server_obs_full = _temp("server_temp_C")
    outflow_obs_full = _temp("outflow_temp_C")
    thermal = _thermal_series_masks(
        t_full=t_full,
        v_out_full=v_out_full,
        level_ok_full=level_visible_full,
        sel=sel,
        server_obs=server_obs_full,
        outflow_obs=outflow_obs_full,
        temp_flag=prof.get("temp_flag"),
        stop_flow_time_s=outflow_end_s,
        video_id=str(raw.get("video_id", "")),
        ambient_temp_C=float(meta.get("ambient_temp_C", MEASURED_AMBIENT_TEMP_C)),
    )
    quality_flags = list(prof.get("data_quality_flags", []))
    if thermal["server_series_qc"] == "server_probe_not_mixed_mean":
        quality_flags.append("server_probe_not_mixed_mean")
    m_srv = thermal["server_series_mask_full"]
    m_out = thermal["outflow_series_mask_full"] if OUTFLOW_TEMP_SERIES_IN_CHI2 else np.zeros_like(m_srv)

    # 杯中最終量測（TDS 分母與 stage 7 水力自洽 guard 的比較點）。
    # What：完整 1 s 序列中最後一個 use_for_fit 列。
    # Why：TDS 樣本代表濾杯移開前進杯的全部液體；移開後的液位列已判定為擾動
    #      （F12a，use_for_fit=0），不得當最終量測。取完整序列而非 stride 子序列，
    #      是為了最接近移開時刻。紀錄表 case 末列即 fit 點，結果不變。
    i_final = int(np.flatnonzero(fit_mask_full)[-1])

    return {
        "csv_path": str(csv_path),
        "prof": prof,
        "raw_prof": raw,
        "t_final_obs_s": float(t_full[i_final]),
        "v_out_final_obs_ml": float(v_out_full[i_final]),
        "meta": meta,
        "t_obs": t_obs,
        "v_in_obs": v_in_full[sel],
        "v_out_obs": v_out_obs,
        "retained_obs": retained_full[sel],
        "retention_basis": prof.get("retention_basis", "measured"),
        "data_quality_flags": quality_flags,
        "fit_mask": fit_mask,
        "obs_interval_mask": fit_mask[1:] & fit_mask[:-1],
        "dt_obs": dt_obs,
        "q_obs_mlps": np.diff(v_out_obs) / np.maximum(dt_obs, 1e-12),
        # 逐點 V_out σ（F9 規則 4）；preprocess=False 時為常數 σ_V（舊行為）。
        "sigma_v_obs_ml": sigma_v_full[sel],
        # ── F10：來源、時間基準與完整 1 s 序列（診斷 / 作圖；不進 χ²）──────
        "profile_source": raw["profile_source"],
        "profile_path": raw["profile_path"],
        "video_id": raw.get("video_id", ""),
        "time_base": raw["time_base"],
        "scale_timer_rate_applied": prof.get("scale_timer_rate_applied", 1.0) if preprocess else 1.0,
        "reading_time_sigma_s": prof.get("reading_time_sigma_s") if preprocess else None,
        "fit_stride_s": stride_s,
        "final_coffee_temp_source": raw.get("final_coffee_temp_source", "log_meta"),
        "t_obs_full": t_full,
        "v_in_obs_full": v_in_full,
        "v_out_obs_full": v_out_full,
        "retained_obs_full": retained_full,
        "fit_mask_full": fit_mask_full,
        "sigma_v_obs_full_ml": sigma_v_full,
        "server_temp_obs_C": server_obs_full,
        "outflow_temp_obs_C": outflow_obs_full,
        "temp_flag": prof.get("temp_flag"),
        # F11：進 χ² 的熱時序（stride 格點上、量測決定的子集）。空陣列 = 該項不存在。
        "server_series_t": t_full[m_srv],
        "server_series_obs_C": (server_obs_full[m_srv] if server_obs_full is not None
                                else np.zeros(0)),
        "outflow_series_t": t_full[m_out],
        "outflow_series_obs_C": (outflow_obs_full[m_out] if outflow_obs_full is not None
                                 else np.zeros(0)),
        "server_series_mask_full": m_srv,
        "outflow_series_mask_full": m_out,
        "outflow_series_candidate_mask_full": thermal["outflow_series_mask_full"],
        "server_series_excluded": thermal["server_series_excluded"],
        "outflow_series_excluded": thermal["outflow_series_excluded"],
        "v_immersion_ml": thermal["v_immersion_ml"],
        "server_series_qc": thermal["server_series_qc"],
        "server_energy_closure_c_eff_ml": thermal["server_energy_closure_c_eff_ml"],
        "preprocessed": bool(preprocess),
        "preprocess_corrections": format_corrections(prof.get("corrections", [])),
        "max_pour_rate_g_s": prof.get("max_pour_rate_g_s"),
        "stop_flow_time_s": float(stop_obs_s),
        "stop_operator": stop_operator,
        "stop_flow_time_csv_s": stop_csv_s,
        "stop_level_valid_full": fit_mask_full,
        "dripper_removed_time_s": dripper_removed_s,
        "outflow_obs_end_s": outflow_end_s,
        "level_visible_full": level_visible_full,
        "final_cup_temp_C": prof["final_cup_temp_C"],
        "final_temp_read_time_s": float(prof["final_temp_read_time_s"]),
        "final_tds_gl": prof.get("final_tds_gl"),
        "ambient_temp_C": float(meta.get("ambient_temp_C", MEASURED_AMBIENT_TEMP_C)),
        "protocol": protocol,
        "t_end": max(float(t_full[-1]) + 30.0, 180.0),
    }


def _chi2_evaluate(
    case: dict,
    params_try: V60Params,
    tau_lag_s: float,
    *,
    vessel_equivalent_ml: float | None,
    solver: dict,
    k_beta_prior_psd: float | None = None,
    n_fit_params: int = DEFAULT_LIVE_PARAM_COUNT,
    keep_sim: bool = True,
) -> dict:
    """
    以量測 σ 正規化的 χ²，是本專案**唯一**的擬合目標函數。

    What:
        χ² = Σ_i ((v_pred_i − v_obs_i)/σ_V)²
           + ((stop_model − stop_obs)/σ_stop)²
           + ((T_model(t_read) − T_obs)/σ_T)²              （無分享壺溫時序時）
           + Σ_i ((T_srv_model(t_i) − T_srv_obs(t_i))/σ_Ts)²  （有時序時，取代上一項；F11）
           + ((M_ext_pred − TDS_obs·V_out_obs)/σ_Mext)²
           + Σ_j ((ret_pred_j − ret_obs_j)/σ_ret)²
           + ((log₁₀k_beta − log₁₀k_beta_prior)/σ_kβ)²
           + ((log₁₀U − log₁₀U_prior)/σ_U)²
           + ((log₁₀n_Corey − log₁₀n_prior)/σ_n)²

        其中
        `ret_pred = sim.retained_ml + obs_layer.v_hold_ml + V_paper·w_wet`
        （模型保水必須含觀測層的出口暫存與濾紙/杯壁潤濕，見
        `measured_io.MEASURED_PAPER_HOLDUP_ML`），
        TDS 以**質量**比較（σ_Mext = σ_TDS × V_out_obs[L]）。

    Why（相對舊 loss 的四項結構變更）：
        1. **移除 velocity 項**。`q = ΔV/Δt`，其 RMSE 是 V 殘差差分的 L2 罰，
           不是獨立觀測（AUD-4 機器精度驗證）。它唯一的效果是懲罰殘差的
           高頻變化，於是把 τ_lag 撐到網格上界 2.0 s 去把曲線抹平。
        2. **移除 phys_penalty**。其區間與 optimizer bounds 相同 → 恆為 0。
        3. **TDS 改以質量比較**。舊版 `TDS_pred = M_ext/V_out_model`，當 V_out
           高估 9% 時 stage 7 會調萃取參數去補水力誤差（AGENTS.md §6 禁止）。
           改比質量後，分母來自量測，萃取端只為 `M_extracted` 負責。
        4. **retention 項的歷程**。F4 曾把保水時序加進 χ²，理由是「床內 hold-up
           時序在 loss 中完全簡併」。F6b 的資料檢核推翻了這條理由的前提：
           量測端的 `retained_mass_g` 逐列等於 `poured − drained`，因此該項是
           V_out 殘差的線性重排，**不提供新資訊，只造成雙重計入**（見
           `MEASUREMENT_SIGMA` 的 Why）。F6b 起把它移出 loss、保留為診斷。
           原本要靠它打開的 `(k, τ_wet)` ridge，改由 `tau_wet` 對停流時刻與
           drawdown 段 V_out 曲率的影響來約束；若日後有 dripper 淨重時序這條
           真正獨立的觀測，應把它以自己的 σ 加回來。

    回傳的 `total_loss` 鍵保留為向後相容 alias，但**語意已變**：
        舊 = 五項加權混合單位量；新 = χ²（無因次）。任何以絕對數值比較新舊
        loss 的腳本都會失效，這是刻意的。
    """
    t_obs = case["t_obs"]
    v_out_obs = case["v_out_obs"]
    fit_mask = case["fit_mask"]
    dt_obs = case["dt_obs"]
    ambient_temp_C = case["ambient_temp_C"]
    vessel_eq = 0.0 if vessel_equivalent_ml is None else float(vessel_equivalent_ml)

    sim = simulate_brew(
        params_try,
        case["protocol"],
        t_end=case["t_end"],
        n_eval=int(solver["n_eval"]),
        rtol=float(solver["rtol"]),
        atol=float(solver["atol"]),
        max_step=float(solver["max_step"]),
    )
    obs_layer = apply_outflow_lag(
        sim,
        tau_lag_s,
        ambient_temp_C=ambient_temp_C,
        vessel_equivalent_ml=vessel_eq,
        lambda_server_ambient=float(getattr(params_try, "lambda_server_ambient", 0.0)),
    )
    t_sim = np.asarray(sim["t"], dtype=float)
    v_pred_obs = np.interp(t_obs, t_sim, np.asarray(obs_layer["v_cup_ml"], dtype=float))
    q_pred_mlps = np.diff(v_pred_obs) / np.maximum(dt_obs, 1e-12)
    if case.get("stop_operator") == "level":
        stop_model_s = model_level_stop_time(
            obs_layer, t_sim, case["t_obs_full"], case["stop_level_valid_full"],
            case["protocol"].last_pour_end())
    else:
        stop_model_s = observed_stop_time_from_layer(obs_layer, t_sim, case["protocol"])

    terms: dict[str, float] = {}

    # ── 1. 累積出液 ────────────────────────────────────────────────────────
    # σ 逐點（F9 規則 4：讀取時刻誤差傳播）；舊 case bundle 沒有此鍵時退回常數 σ_V。
    sigma_v = np.asarray(
        case.get("sigma_v_obs_ml", np.full(t_obs.size, MEASUREMENT_SIGMA["v_out_ml"])),
        dtype=float,
    )[fit_mask]
    v_resid = v_pred_obs[fit_mask] - v_out_obs[fit_mask]
    terms["volume"] = float(np.sum((v_resid / sigma_v) ** 2))
    n_obs = int(v_resid.size)

    # ── 2. 目視停流時刻 ────────────────────────────────────────────────────
    stop_err = float(stop_model_s - case["stop_flow_time_s"])
    terms["stop_time"] = float((stop_err / MEASUREMENT_SIGMA["stop_time_s"]) ** 2)
    n_obs += 1

    # ── 3. 杯溫：同一次沖煮有分享壺溫時序時用時序（F11），否則用單點 ─────
    # Why 二擇一（F11，同 F6b 處理 retention 的原則）：影片 case 的單點杯溫
    #     `final_coffee_temp_C` 就是末 3 個上行無旗標格的中位數——時序末段已包含同一個
    #     觀測。兩者同時進 χ² 等於把同一個讀值計兩次、n_obs 虛增。時序項存在時單點項
    #     不計分、不計入 n_obs，但 `cup_temp_error_C` 照算（診斷與 benchmark gate 用）。
    server_series_t = np.asarray(case.get("server_series_t", np.zeros(0)), dtype=float)
    outflow_series_t = np.asarray(case.get("outflow_series_t", np.zeros(0)), dtype=float)
    has_server_series = server_series_t.size > 0
    final_cup_temp_C = case["final_cup_temp_C"]
    mixed_temp = None
    temp_err = None
    terms["cup_temp"] = 0.0
    if final_cup_temp_C is not None:
        mixed_temp = mixed_cup_temperature_C(
            {
                **sim,
                "q_out_mlps": obs_layer["q_cup_mlps"],
                "T_C": obs_layer["T_cup_C"],
                "T_server_C": obs_layer["T_server_C"],
            },
            ambient_temp_C=ambient_temp_C,
            vessel_equivalent_ml=vessel_eq,
            t_read_s=case["final_temp_read_time_s"],
        )
        temp_err = float(mixed_temp - final_cup_temp_C)
        if not has_server_series:
            terms["cup_temp"] = float((temp_err / MEASUREMENT_SIGMA["cup_temp_C"]) ** 2)
            n_obs += 1

    # ── 3b. 分享壺溫 / 出水口溫時序（F11；遮罩見 `_thermal_series_masks`）──────
    # χ²_Ts = Σ_i ((T_server_model(t_i) − T_server_obs(t_i)) / σ_Ts)²，σ_Ts = 1.0 °C；
    # 出水口同式（σ = 1.5 °C），僅在 `OUTFLOW_TEMP_SERIES_IN_CHI2` 時存在。
    server_series_resid = np.zeros(0)
    outflow_series_resid = np.zeros(0)
    if has_server_series:
        ts_model = np.interp(server_series_t, t_sim, np.asarray(obs_layer["T_server_C"], dtype=float))
        server_series_resid = ts_model - np.asarray(case["server_series_obs_C"], dtype=float)
        terms["server_temp_series"] = float(np.sum(
            (server_series_resid / MEASUREMENT_SIGMA["server_temp_series_C"]) ** 2))
        n_obs += int(server_series_resid.size)
    if outflow_series_t.size > 0:
        to_model = np.interp(outflow_series_t, t_sim, np.asarray(obs_layer["T_cup_C"], dtype=float))
        outflow_series_resid = to_model - np.asarray(case["outflow_series_obs_C"], dtype=float)
        terms["outflow_temp_series"] = float(np.sum(
            (outflow_series_resid / MEASUREMENT_SIGMA["outflow_temp_series_C"]) ** 2))
        n_obs += int(outflow_series_resid.size)

    # ── 4. 溶出質量（TDS × 量測 V_out）────────────────────────────────────
    final_tds_gl_obs = case["final_tds_gl"]
    t_read_tds = case["t_final_obs_s"]
    v_out_obs_L = max(case["v_out_final_obs_ml"] * 1e-3, 1e-9)
    m_ext_pred = (
        float(np.interp(t_read_tds, t_sim, np.asarray(sim["M_extracted_g"], dtype=float)))
        if "M_extracted_g" in sim
        else None
    )
    tds_pred_measured_denom = None if m_ext_pred is None else float(m_ext_pred / v_out_obs_L)
    tds_err = None
    terms["extracted_mass"] = 0.0
    if final_tds_gl_obs is not None and m_ext_pred is not None:
        m_ext_obs = float(final_tds_gl_obs) * v_out_obs_L
        sigma_m_ext = MEASUREMENT_SIGMA["tds_gl"] * v_out_obs_L
        terms["extracted_mass"] = float(((m_ext_pred - m_ext_obs) / sigma_m_ext) ** 2)
        tds_err = float(tds_pred_measured_denom - float(final_tds_gl_obs))
        n_obs += 1

    # ── 5. 保水時序：**診斷專用，不進 χ²、不計入 n_obs**（F6b）────────────
    # 模型保水 = 床內保水 + 濾杯出口暫存 + 濾紙/杯壁潤濕（Class B 常數 × 潤濕狀態 w）
    # w_wet 缺席（舊版 core）時該項為 0，不憑空加一個沒有依據的常數。
    #
    # Why 不進 loss：量測端的 `retained_mass_g` 逐列等於 `poured − drained`
    # （四 case 實測 max |差| = 2e-14），因此保水殘差是 V_out 殘差的線性重排。
    # 計進 χ² 等於把同一條殘差罰兩次（有效 σ_V 砍成 3.0/√2），並且讓 n_obs
    # 虛增一倍、dof 跟著錯。完整論證見 `MEASUREMENT_SIGMA` 的 Why。
    ret_pred_sim = np.asarray(sim.get("retained_ml", np.zeros_like(t_sim)), dtype=float)
    w_wet = np.clip(np.asarray(sim.get("w_wet", np.zeros_like(t_sim)), dtype=float), 0.0, 1.0)
    paper_holdup = MEASURED_PAPER_HOLDUP_ML * w_wet
    ret_pred_full = (
        ret_pred_sim
        + np.asarray(obs_layer["v_hold_ml"], dtype=float)
        + paper_holdup
    )
    ret_pred_obs = np.interp(t_obs, t_sim, ret_pred_full)
    ret_resid = ret_pred_obs[fit_mask] - case["retained_obs"][fit_mask]
    retention_rmse = float(np.sqrt(np.mean(ret_resid ** 2))) if ret_resid.size else float("nan")
    fit_idx = np.flatnonzero(fit_mask)
    last_fit_idx = int(fit_idx[-1]) if fit_idx.size else int(t_obs.size - 1)

    chi2_data = float(sum(terms.values()))

    # ── 6. prior 項（不計入 N_obs）─────────────────────────────────────────
    prior_terms: dict[str, float] = {}
    anchor = (
        float(k_beta_prior_psd)
        if k_beta_prior_psd is not None
        else float(getattr(params_try, "k_beta_prior_psd", params_try.k_beta))
    )
    sigma_dex = float(getattr(params_try, "k_beta_prior_sigma_dex", KBETA_PRIOR_SIGMA_DEX))
    prior_terms["k_beta_psd"] = float(
        ((np.log10(max(params_try.k_beta, 1e-30)) - np.log10(max(anchor, 1e-30))) / sigma_dex) ** 2
    )
    u_liq = getattr(params_try, "U_liquid_dripper_W_m2K", None)
    prior_terms["U_liquid_dripper"] = 0.0
    if u_liq is not None and float(u_liq) > 0.0:
        prior_terms["U_liquid_dripper"] = float(
            ((np.log10(float(u_liq)) - np.log10(U_LIQUID_DRIPPER_PRIOR_W_M2K))
             / U_LIQUID_DRIPPER_PRIOR_SIGMA_DEX) ** 2
        )
    # `tau_lag` 的 prior 項已於 F6b 移除：它自 F6b 起是凍結的 Class B 幾何常數
    # （`TAU_LAG_FIXED_S`），不是自由參數。對凍結值加 prior 只會在每一次
    # evaluate 上加同一個常數（中心 1.0 s vs 凍結值 0.5 s → +1.01），既不是
    # 資料也不是約束，只會污染回報的 χ²。
    # `k_beta` 的 prior 項**保留**：它凍結在 prior 中心上，該項恆等於 0，
    # 因此不影響任何最佳化；留著它的唯一作用是 reload 路徑的 tripwire——
    # 若有人載入舊 summary 的 `k_beta_fit`，偏離會立刻在 χ² 上顯形。
    n_corey = getattr(params_try, "sat_rel_perm_exp", None)
    if n_corey is not None and float(n_corey) > 0.0:
        prior_terms["sat_rel_perm_exp"] = float(
            ((np.log10(float(n_corey)) - np.log10(SAT_REL_PERM_EXP_PRIOR))
             / SAT_REL_PERM_EXP_PRIOR_SIGMA_DEX) ** 2
        )
    for _name, (_center, _sigma_dex) in EXTRACTION_FIT_PRIORS.items():
        _val = getattr(params_try, _name, None)
        if _val is not None and float(_val) > 0.0:
            prior_terms[f"ext:{_name}"] = float(
                ((np.log10(float(_val)) - np.log10(_center)) / _sigma_dex) ** 2
            )
    chi2 = chi2_data + float(sum(prior_terms.values()))
    # 水力子目標（stage 1/2/4 的最佳化對象）。
    # What：只含水力觀測（V_out 時序、停流）與水力參數的 prior。
    # Why：熱端與萃取參數在 stage 5/7 才擬合；stage 1/2 時杯溫與分享壺溫殘差
    #      主要反映尚未擬合的 λ_server / U（F12c 實測 kinu27 stage 1 的熱項 ≈ 65），
    #      若讓水力參數最小化總 χ²，optimizer 會扭曲水力去補熱端誤差——正是
    #      CLAUDE.md §3.3 / §6 禁止的「用水力吸收熱誤差」。水力 ↔ 熱的真實耦合
    #      （μ(T) 進 Darcy）仍由 stage 5 以總 χ² 評估時納入。
    chi2_hydraulic = float(
        terms["volume"] + terms["stop_time"]
        + prior_terms["k_beta_psd"] + prior_terms.get("sat_rel_perm_exp", 0.0)
    )

    # ── 7. 合法性 gate：溫度 clip 代表解已不是原方程的解 ─────────────────
    clip_fraction = float(sim.get("clip_active_fraction", 0.0))
    clip_flag = bool(clip_fraction > CLIP_ACTIVE_FRACTION_MAX)
    if clip_flag:
        chi2 += CLIP_PENALTY_CHI2
        chi2_hydraulic += CLIP_PENALTY_CHI2

    dof = max(n_obs - int(n_fit_params), 1)
    # 白噪音檢定吃標準化殘差（F12a；見 WHITENESS_SUBSET_SIGMA_MAX_ML 的 Why）。
    z_resid = v_resid / sigma_v
    diag = residual_diagnostics(z_resid)
    low_sigma = sigma_v <= float(WHITENESS_SUBSET_SIGMA_MAX_ML)
    diag_low = residual_diagnostics(z_resid[low_sigma])
    diag_raw = residual_diagnostics(v_resid)
    water_resid = np.asarray(sim.get("water_balance_residual_ml", [0.0]), dtype=float)

    out = {
        "chi2": float(chi2),
        "chi2_hydraulic": float(chi2_hydraulic),
        "chi2_data": float(chi2_data),
        "reduced_chi2": float(chi2_data / dof),
        "dof": int(dof),
        "n_obs": int(n_obs),
        "n_fit_params": int(n_fit_params),
        "chi2_terms": terms,
        "chi2_prior_terms": prior_terms,
        "total_loss": float(chi2),          # 向後相容 alias；語意見 docstring
        # 殘差與結構檢定
        "v_residual_ml": v_resid,
        "retention_residual_ml": ret_resid,
        "residual_lag1": diag["lag1"],
        "durbin_watson": diag["durbin_watson"],
        "runs_z": diag["runs_z"],
        "residual_diagnostics_basis": "standardized r/sigma",
        # 附報（不 gate）：只取 σ-class ≤ 6 mL 的子序列；以及舊定義（mL 殘差）供前後對照
        "residual_lag1_lowsigma": diag_low["lag1"],
        "durbin_watson_lowsigma": diag_low["durbin_watson"],
        "n_resid_lowsigma": int(low_sigma.sum()),
        "residual_lag1_unweighted": diag_raw["lag1"],
        "durbin_watson_unweighted": diag_raw["durbin_watson"],
        # 診斷指標（不進 loss）
        "volume_rmse": float(np.sqrt(np.mean(v_resid ** 2))) if v_resid.size else float("nan"),
        "velocity_rmse": float(np.sqrt(np.mean(
            (q_pred_mlps[case["obs_interval_mask"]] - case["q_obs_mlps"][case["obs_interval_mask"]]) ** 2
        ))) if np.any(case["obs_interval_mask"]) else float("nan"),
        "retention_rmse_ml": retention_rmse,
        # 末段保水取**最後一個進 fit 的觀測列**，不是 CSV 的最後一列。
        # Why（F6b）：`use_for_fit=0` 的列是被標註為不可信的量測（例如
        # kinu29 4:12 t=130 的 retained = −7.2 g，drained > poured，違反質量守恆）。
        # 既然它不進殘差，就沒有理由讓它獨自定義「末段保水」這個診斷與 gate 的分母。
        "retention_final_model_ml": float(ret_pred_obs[last_fit_idx]),
        "retention_final_obs_ml": float(case["retained_obs"][last_fit_idx]),
        "retention_final_time_s": float(t_obs[last_fit_idx]),
        "paper_holdup_final_ml": float(paper_holdup[-1]),
        # 觀測層與量測對應
        "stop_model_s": float(stop_model_s),
        "cup_stop_time_s": float(stop_model_s),
        "stop_flow_time_s": case["stop_flow_time_s"],
        "stop_operator": case.get("stop_operator", "q_threshold"),
        "cup_stop_time_error_s": stop_err,
        "drain_time_error_s": stop_err,      # deprecated 別名（expand 期保留一個週期）
        "mixed_cup_temp_C": mixed_temp,
        "final_cup_temp_C": final_cup_temp_C,
        "cup_temp_error_C": temp_err,
        # F11 熱時序項（進 χ² 的點；空 = 該項不存在）
        "server_series_residual_C": server_series_resid,
        "outflow_series_residual_C": outflow_series_resid,
        "server_series_n": int(server_series_resid.size),
        "outflow_series_n": int(outflow_series_resid.size),
        "server_series_rmse_C": (float(np.sqrt(np.mean(server_series_resid ** 2)))
                                 if server_series_resid.size else None),
        "server_series_bias_C": (float(np.mean(server_series_resid))
                                 if server_series_resid.size else None),
        "outflow_series_rmse_C": (float(np.sqrt(np.mean(outflow_series_resid ** 2)))
                                  if outflow_series_resid.size else None),
        "outflow_series_bias_C": (float(np.mean(outflow_series_resid))
                                  if outflow_series_resid.size else None),
        "final_tds_gl_obs": final_tds_gl_obs,
        "m_extracted_pred_g": m_ext_pred,
        "tds_pred_measured_denominator": tds_pred_measured_denom,
        "final_tds_gl_pred": tds_pred_measured_denom,
        "tds_error_gl": tds_err,
        # 守恆與合法性
        "water_balance_residual_ml": float(np.max(np.abs(water_resid))),
        "energy_residual_fraction": float(sim.get("energy_residual_fraction", 0.0)),
        "clip_active_fraction": clip_fraction,
        "clip_flag": clip_flag,
        # 預測序列
        "v_pred_obs_ml": v_pred_obs,
        "q_pred_obs_mlps": q_pred_mlps,
        "retention_pred_obs_ml": ret_pred_obs,
        "tau_lag_s": float(tau_lag_s),
        "k_beta_prior_psd": float(anchor),
        "data_quality_flags": list(case.get("data_quality_flags", [])),
    }
    if keep_sim:
        out["sim"] = sim
        out["obs_layer"] = obs_layer
    return out


def _channel_unflagged(flags: list[str] | None, channel: str, n: int) -> np.ndarray:
    """
    LCD 讀值旗標 → 該通道（"U" 上行 = 分享壺、"L" 下行 = 出水口）是否可用。

    Why: V1 盲測顯示溫度讀錯集中在有鬼影旗標的格（~6% 格 ≥ 1 °C 誤差），診斷 RMSE
         只取該通道無旗標的格；`no_frame`（1 s 格點附近 0.6 s 內無影格）兩通道皆不用。
    """
    if flags is None:
        return np.ones(n, dtype=bool)
    out = np.ones(n, dtype=bool)
    for i, f in enumerate(flags):
        segs = [x.strip() for x in str(f).split(";") if x.strip()]
        out[i] = not any(x == "no_frame" or x.startswith(channel) for x in segs)
    return out


def full_series_diagnostics(case: dict, sim: dict, obs_layer: dict) -> dict:
    """
    把模型插到完整觀測格點上（影片版 1 s），並做同一次沖煮的熱時序診斷（F10）。

    What:
        - `v_pred_obs_full_ml` / `retention_pred_obs_full_ml`：完整格點上的模型出液 / 保水。
        - 影片版另回傳熱診斷（**不進 χ²**）：
            server：模型 `T_server_C` vs LCD 上行 `server_temp_C`，取液面可見（壺內有液）
                    且上行無旗標的格；
            outflow：模型出口釋放溫度 `T_cup_C` vs LCD 下行 `outflow_temp_C`，另限
                    t ≤ 目視停流（停流後探頭在空氣中，讀的不是出流）。
          RMSE、平均偏差（模型 − 量測）與點數。
    Why:
        AUD-2 要求同一次沖煮的熱時序；先當診斷揭露，是否進 loss 留給下一輪
        （進 loss 需先處理探頭位置 / 液位覆蓋與 LCD 鬼影的誤差模型）。
    """
    t_sim = np.asarray(sim["t"], dtype=float)
    t_full = np.asarray(case.get("t_obs_full", case["t_obs"]), dtype=float)
    out = {
        "t_obs_full_s": t_full,
        "v_out_obs_full_ml": np.asarray(case.get("v_out_obs_full", case["v_out_obs"]), dtype=float),
        "v_in_obs_full_ml": np.asarray(case.get("v_in_obs_full", case["v_in_obs"]), dtype=float),
        "retained_obs_full_ml": np.asarray(case.get("retained_obs_full", case["retained_obs"]), dtype=float),
        "fit_mask_full": np.asarray(case.get("fit_mask_full", case["fit_mask"]), dtype=bool),
        "sigma_v_obs_full_ml": np.asarray(case.get("sigma_v_obs_full_ml", case["sigma_v_obs_ml"]), dtype=float),
        "v_pred_obs_full_ml": np.interp(t_full, t_sim, np.asarray(obs_layer["v_cup_ml"], dtype=float)),
    }
    ret_model = (np.asarray(sim.get("retained_ml", np.zeros_like(t_sim)), dtype=float)
                 + np.asarray(obs_layer["v_hold_ml"], dtype=float)
                 + MEASURED_PAPER_HOLDUP_ML * np.clip(
                     np.asarray(sim.get("w_wet", np.zeros_like(t_sim)), dtype=float), 0.0, 1.0))
    out["retention_pred_obs_full_ml"] = np.interp(t_full, t_sim, ret_model)

    # F11：熱時序進 χ² 的遮罩與觀測窗設定（作圖標示納入 / 排除、summary 稽核）。
    zeros = np.zeros(t_full.size, dtype=bool)
    out.update({
        "server_series_mask_full": np.asarray(case.get("server_series_mask_full", zeros), dtype=bool),
        "outflow_series_mask_full": np.asarray(case.get("outflow_series_mask_full", zeros), dtype=bool),
        "outflow_series_candidate_mask_full": np.asarray(
            case.get("outflow_series_candidate_mask_full", zeros), dtype=bool),
        "v_immersion_ml": case.get("v_immersion_ml"),
        "server_series_qc": case.get("server_series_qc", "no_series"),
        "server_energy_closure_c_eff_ml": case.get("server_energy_closure_c_eff_ml"),
        "server_series_min_v_ml": float(SERVER_SERIES_MIN_V_ML),
        "outflow_temp_series_in_chi2": bool(OUTFLOW_TEMP_SERIES_IN_CHI2),
        "measurement_sigma": dict(MEASUREMENT_SIGMA),   # viz 畫 ±σ 用（viz 不得 import fitting）
        "server_series_excluded": ";".join(
            f"{k}={v}" for k, v in (case.get("server_series_excluded") or {}).items()),
        "outflow_series_excluded": ";".join(
            f"{k}={v}" for k, v in (case.get("outflow_series_excluded") or {}).items()),
    })
    server_obs = case.get("server_temp_obs_C")
    outflow_obs = case.get("outflow_temp_obs_C")
    if server_obs is None or outflow_obs is None:
        return out
    n = t_full.size
    flags = case.get("temp_flag")
    # 壺內液位可讀即可（F12a：濾杯移開後的列不進 V_out χ²，但壺溫讀值仍有效）。
    liquid = np.asarray(case.get("level_visible_full", out["fit_mask_full"]), dtype=bool)
    srv_model = np.interp(t_full, t_sim, np.asarray(obs_layer["T_server_C"], dtype=float))
    out_model = np.interp(t_full, t_sim, np.asarray(obs_layer["T_cup_C"], dtype=float))
    m_srv = liquid & np.isfinite(server_obs) & _channel_unflagged(flags, "U", n)
    m_out = (liquid & (t_full <= float(case.get("outflow_obs_end_s", case["stop_flow_time_s"])))
             & np.isfinite(outflow_obs) & _channel_unflagged(flags, "L", n))

    def _stats(model, obs, m):
        d = model[m] - obs[m]
        if d.size == 0:
            return float("nan"), float("nan"), 0
        return float(np.sqrt(np.mean(d ** 2))), float(np.mean(d)), int(d.size)

    out.update({
        "server_temp_obs_C": server_obs,
        "outflow_temp_obs_C": outflow_obs,
        "server_temp_model_C": srv_model,
        "outflow_temp_model_C": out_model,
        "thermal_server_mask": m_srv,
        "thermal_outflow_mask": m_out,
    })
    (out["thermal_video_server_rmse_C"], out["thermal_video_server_bias_C"],
     out["thermal_video_server_n"]) = _stats(srv_model, server_obs, m_srv)
    (out["thermal_video_outflow_rmse_C"], out["thermal_video_outflow_bias_C"],
     out["thermal_video_outflow_n"]) = _stats(out_model, outflow_obs, m_out)
    # F11 樣本外檢查：出水口溫只在「連續出流」窗（`_thermal_series_masks` 的候選點：
    # q_obs ≥ 0.5 mL/s、t ≥ 10 s、無旗標、stride 格點）上才代表流出液溫；它不進 χ²
    # （OUTFLOW_TEMP_SERIES_IN_CHI2 = False），因此是對 server 時序擬出之 U 的獨立檢驗。
    m_gate = np.asarray(case.get("outflow_series_candidate_mask_full", zeros), dtype=bool)
    (out["thermal_video_outflow_gated_rmse_C"], out["thermal_video_outflow_gated_bias_C"],
     out["thermal_video_outflow_gated_n"]) = _stats(out_model, outflow_obs, m_gate)
    # F12a：出水口熱電偶斷流時刻與該時刻的模型杯中流率（診斷，不進 χ²；見 THERMO_BREAK_* 的 Why）。
    t_break = thermo_break_time_s(t_full, outflow_obs, case["protocol"].last_pour_end())
    t_rm = case.get("dripper_removed_time_s")
    out["thermo_break_s"] = t_break
    out["model_q_at_thermo_break_mlps"] = (
        float(np.interp(t_break, t_sim, np.asarray(obs_layer["q_cup_mlps"], dtype=float)))
        if t_break is not None else None)
    out["dripper_removed_time_s"] = t_rm
    out["thermo_break_minus_dripper_removed_s"] = (
        float(t_break - float(t_rm)) if (t_break is not None and t_rm is not None) else None)
    return out


def thermo_break_time_s(t_full: np.ndarray, outflow_obs: np.ndarray, t_last_pour_end: float) -> float | None:
    """
    出水口熱電偶讀值的斷流時刻（F12a 診斷；規則見 `THERMO_BREAK_WINDOW_S` 的 What）。

    不看 LCD 旗標：V1 在這一段的旗標本身就是在描述這個下降（「L falling」），不是讀錯。
    找不到 ≥ 5 °C 的下降 → None。
    """
    t = np.asarray(t_full, dtype=float)
    to = np.asarray(outflow_obs, dtype=float)
    for i in np.flatnonzero(t > float(t_last_pour_end)):
        prev = (t >= t[i] - float(THERMO_BREAK_WINDOW_S)) & (t < t[i]) & np.isfinite(to)
        if not np.isfinite(to[i]) or prev.sum() < 2:
            continue
        ref = float(np.median(to[prev]))
        if to[i] <= ref - float(THERMO_BREAK_DROP_C):
            j = i - 1
            while j > 0 and not (np.isfinite(to[j]) and to[j] >= ref - 1.0):
                j -= 1
            return float(0.5 * (t[j] + t[j + 1]))
    return None


def evaluate_measured_flow_fit(
    csv_path: str | Path,
    params_try: V60Params,
    tau_lag_s: float,
    weights: dict | None = None,
    vessel_equivalent_ml: float | None = MEASURED_VESSEL_EQUIV_ML,
    n_eval: int | None = None,
    rtol: float | None = None,
    atol: float | None = None,
    max_step: float | None = None,
    *,
    solver: dict | None = None,
    k_beta_prior_psd: float | None = None,
    n_fit_params: int = DEFAULT_LIVE_PARAM_COUNT,
) -> dict:
    """
    用 measured flow case 評估單一參數組的 χ² 與診斷指標。

    What:
        載入 case → `_chi2_evaluate` → 補上 benchmark / identifiability / 繪圖
        需要的觀測序列。**與 fit 主流程共用同一個 χ²**，不再有第二份實作。

    Why:
        benchmark、identifiability 與正式 fitting 必須共享同一套評分定義，
        否則每個工具都在優化不同目標，結果不可比較。舊版兩處各寫一遍
        （`evaluate_measured_flow_fit` 與 `_evaluate_loss`），兩份的
        prior anchor 在 fit 與 reload 時甚至取到不同的值（AUD-6）。

    `weights` 參數已**停用**（保留簽名以免破壞既有呼叫端）：χ² 的權重由
    `MEASUREMENT_SIGMA` 決定，不再可調。傳入非 None 會發 DeprecationWarning。
    `n_eval / rtol / atol / max_step` 為 legacy 覆寫入口；預設走 `SOLVER_FINE`。
    """
    if weights is not None:
        warnings.warn(
            "evaluate_measured_flow_fit(weights=...) 已停用：loss 改為 σ 正規化 χ²，"
            "權重由 MEASUREMENT_SIGMA 決定。",
            DeprecationWarning,
            stacklevel=2,
        )
    solver_cfg = dict(SOLVER_FINE if solver is None else solver)
    for key, val in (("n_eval", n_eval), ("rtol", rtol), ("atol", atol), ("max_step", max_step)):
        if val is not None:
            solver_cfg[key] = val

    case = _prepare_measured_case(csv_path)
    out = _chi2_evaluate(
        case,
        params_try,
        tau_lag_s,
        vessel_equivalent_ml=vessel_equivalent_ml,
        solver=solver_cfg,
        k_beta_prior_psd=k_beta_prior_psd,
        n_fit_params=n_fit_params,
    )
    full = full_series_diagnostics(case, out["sim"], out["obs_layer"])
    out.update(full)
    out["full_series"] = full
    out["provenance"] = _case_provenance(case)
    out.update({
        "csv_path": str(csv_path),
        "meta": case["meta"],
        "protocol": case["protocol"],
        "t_obs_s": case["t_obs"],
        "v_in_obs_ml": case["v_in_obs"],
        "v_out_obs_ml": case["v_out_obs"],
        "v_out_final_obs_ml": case["v_out_final_obs_ml"],
        "retained_obs_ml": case["retained_obs"],
        "q_obs_mlps": case["q_obs_mlps"],
        "fit_mask": case["fit_mask"],
        "sigma_v_obs_ml": case["sigma_v_obs_ml"],
        "preprocess_corrections": case["preprocess_corrections"],
        "max_pour_rate_g_s": case["max_pour_rate_g_s"],
        "solver": solver_cfg,
        **_case_provenance(case),
    })
    return out


def _case_provenance(case: dict) -> dict:
    """case 的量測來源與時間基準（F10），summary / benchmark / 報告共用同一組鍵。"""
    return {
        "profile_source": case.get("profile_source", "log"),
        "profile_path": case.get("profile_path", case.get("csv_path", "")),
        "video_id": case.get("video_id", ""),
        "time_base": case.get("time_base", "scale_timer_s"),
        "scale_timer_rate_applied": case.get("scale_timer_rate_applied"),
        "reading_time_sigma_s": case.get("reading_time_sigma_s"),
        "fit_stride_s": case.get("fit_stride_s"),
        "final_coffee_temp_source": case.get("final_coffee_temp_source", "log_meta"),
    }


def thermal_series_summary(res: dict) -> dict:
    """
    χ² 評估結果中熱時序項的純量摘要（F11），fit summary / benchmark reload 共用同一組鍵。

    What: 各 χ² 分項（`chi2_term_<name>`）、進 χ² 的熱時序點數與模型 − 量測的 RMSE / 平均偏差。
    Why:  CLAUDE.md §6 要求回報 χ² 分解；熱時序進 loss 後，讀 summary 的人必須看得到
          它佔多少、用了幾個點，否則 reduced χ² 的變化無從歸因。
    """
    terms = res.get("chi2_terms", {}) or {}
    out = {f"chi2_term_{k}": float(terms.get(k, 0.0))
           for k in ("volume", "stop_time", "cup_temp", "extracted_mass",
                     "server_temp_series", "outflow_temp_series")}
    for key in ("server_series_n", "outflow_series_n", "server_series_rmse_C", "server_series_bias_C",
                "outflow_series_rmse_C", "outflow_series_bias_C"):
        out[key] = res.get(key)
    return out


def fit_vessel_equivalent_ml(
    results: dict,
    final_cup_temp_C: float,
    ambient_temp_C: float,
) -> float:
    """
    由最終杯溫反推容器等效水體積。

    What: 反推出一個 `V_eq`，使 `T_mix = (V_cup*T_energy + V_eq*T_amb)/(V_cup+V_eq)`。
    Why:  單一終點溫度不足以識別濾杯內部冷卻係數，但足以識別「杯器吸熱量級」。
    """
    t = np.asarray(results["t"], dtype=float)
    q_out_mlps = np.asarray(results["q_out_mlps"], dtype=float)
    T_out_C = np.asarray(results["T_C"], dtype=float)
    dt = np.diff(t, prepend=t[0])
    cup_volume_ml = float(np.sum(q_out_mlps * dt))
    if cup_volume_ml <= 0:
        return 0.0

    T_energy_C = float(np.sum(q_out_mlps * T_out_C * dt) / cup_volume_ml)
    denominator = final_cup_temp_C - ambient_temp_C
    if denominator <= 1e-9:
        raise ValueError("最終杯溫必須高於環境溫度，否則無法反推容器熱容")

    vessel_equivalent_ml = cup_volume_ml * (T_energy_C - final_cup_temp_C) / denominator
    return max(vessel_equivalent_ml, 0.0)


def fit_brew_log_final_temp(
    csv_path: str | Path,
    params_init: V60Params | None = None,
    vessel_equivalent_ml: float | None = MEASURED_VESSEL_EQUIV_ML,
    verbose: bool = True,
) -> tuple[V60Params, PourProtocol, dict]:
    """
    以實測 CSV 擬合「可識別」的熱容參數。

    What:
      1. 從 CSV 重建注水協議
      2. 套用實測的粉量、粉層高度、水溫與烘焙度
      3. 用量測給定的分享壺等效水體積計算最終杯溫；
         若顯式傳入 `None`，才改用杯溫反推 `vessel_equivalent_ml`

    Why:
      玻璃壺質量與材質已足以估計容器熱容時，`vessel_equivalent_ml` 就是可量測量，
      不應再讓 optimizer 或反推流程吸收其他模型誤差。
    """
    rows, meta = load_brew_log_csv(csv_path)
    protocol = protocol_from_brew_log(rows)

    roast_map = {
        "light": RoastProfile.LIGHT,
        "medium": RoastProfile.MEDIUM,
        "dark": RoastProfile.DARK,
    }
    roast_key = meta["roast"].strip().lower()
    profile = roast_map.get(roast_key)
    if profile is None:
        raise ValueError(f"未知烘焙度：{meta['roast']}")

    if params_init is None:
        params_init = V60Params.for_roast(profile)
    else:
        params_init = V60Params.for_roast(profile, base=params_init)

    params_fit = dataclasses.replace(
        params_init,
        dose_g=_meta_float(meta, "dose_g"),
        h_bed=_meta_float(meta, "bed_height_cm", MEASURED_BED_HEIGHT_CM) / 100.0,
        T_brew=_meta_float(meta, "brew_temp_C") + 273.15,
        **_measured_setup_overrides(meta, flow_csv_path=csv_path),
    )

    t_end = 180.0
    sim = simulate_brew(params_fit, protocol, t_end=t_end, n_eval=3000)

    final_cup_temp_C = _meta_float(meta, "final_coffee_temp_C")
    ambient_temp_C = params_fit.T_amb - 273.15
    if vessel_equivalent_ml is None:
        vessel_equivalent_ml = fit_vessel_equivalent_ml(sim, final_cup_temp_C, ambient_temp_C)
    mixed_temp_C = mixed_cup_temperature_C(sim, ambient_temp_C, vessel_equivalent_ml)

    info = {
        "csv_path": str(csv_path),
        "roast": roast_key,
        "protocol": protocol,
        "sim_final": sim,
        "final_cup_temp_target_C": final_cup_temp_C,
        "ambient_temp_C": ambient_temp_C,
        "vessel_equivalent_ml": vessel_equivalent_ml,
        "mixed_cup_temp_C": mixed_temp_C,
        "cup_volume_ml": float(sim["v_out_ml"][-1]),
        "brew_time_s": float(sim["brew_time"]),
        "drain_time_s": float(sim["drain_time"]),
        "T_out_end_C": float(sim["T_C"][-1]),
        "h_bed_cm": float(params_fit.h_bed * 100.0),
        "rho_bulk_dry_g_ml": float(params_fit.rho_bulk_dry_g_ml),
    }

    if verbose:
        print("=== 實測沖煮紀錄擬合 ===")
        print(f"  CSV               : {csv_path}")
        print(f"  Roast             : {roast_key}")
        print(f"  Dose              : {params_fit.dose_g:.1f} g")
        print(f"  Bed height        : {params_fit.h_bed*100:.1f} cm")
        print(f"  Dry bulk density  : {params_fit.rho_bulk_dry_g_ml:.3f} g/mL")
        print(f"  Brew temperature  : {params_fit.T_brew-273.15:.1f} °C")
        print(f"  Final cup target  : {final_cup_temp_C:.1f} °C")
        print(f"  Vessel equiv.     : {vessel_equivalent_ml:.1f} mL")
        print(f"  Predicted cup temp: {mixed_temp_C:.1f} °C")
        print(f"  Cup volume        : {sim['v_out_ml'][-1]:.1f} mL")
        print(f"  Brew / drain      : {sim['brew_time']:.1f} s / {sim['drain_time']:.1f} s")

    return params_fit, protocol, info


def save_fit_summary_csv(output_path: str | Path, info: dict) -> None:
    """
    將擬合摘要寫入 CSV。

    What: 以單列表格輸出此次擬合的核心結果。
    Why:  方便後續做版本比對、繪圖、或與其他實測批次拼接分析。
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "csv_path",
        "roast",
        "brew_time_s",
        "drain_time_s",
        "cup_volume_ml",
        "ambient_temp_C",
        "final_cup_temp_target_C",
        "mixed_cup_temp_C",
        "vessel_equivalent_ml",
        "h_bed_cm",
        "rho_bulk_dry_g_ml",
        "T_out_end_C",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({k: info[k] for k in fieldnames})


def _read_thermal_only_carry(summary_path: str | Path) -> dict:
    """
    讀回 thermal-only 重擬要固定的水力 / 萃取狀態（`fit_k_kbeta_from_flow_profile`
    的 `thermal_only_from_summary` 模式專用）。

    What: 回傳 `params`（要套到 V60Params 的欄位）、`k_beta_prior_psd`、
          `pref_live` / `ext_live`（那一次 fit 是否接受 stage 4 / 7）與
          `stage7_skipped_reason`。
    Why:  固定的參數值與「它們當初是不是自由度」必須來自**同一份** summary，
          否則 dof 會和參數值脫鉤。缺欄一律 raise（Fail Fast）：thermal-only
          模式的前提就是 summary 完整記錄了上一次 fit，缺欄代表前提不成立。
    """
    path = Path(summary_path)
    with path.open("r", encoding="utf-8", newline="") as f:
        row = next(csv.DictReader(f))

    def _req(key: str) -> float:
        raw = str(row.get(key, "") or "").strip()
        if not raw:
            raise ValueError(f"thermal-only 重擬需要 summary 欄位 `{key}`：{path}")
        return float(raw)

    live = [x for x in str(row.get("fit_live_param_names", "") or "").split(";") if x]
    for name in ("k", "sat_rel_perm_exp"):
        if name not in live:
            raise ValueError(f"summary 的 fit_live_param_names 缺 `{name}`，不是 F6b 之後的 fit：{path}")
    params = {
        "k": _req("k_fit"),
        "sat_rel_perm_exp": _req("sat_rel_perm_exp_fit"),
        "tau_wet_s": _req("tau_wet_s_fit"),
        "pref_flow_coeff": _req("pref_flow_coeff_fit"),
        "pref_flow_open_rate": _req("pref_flow_open_rate_fit"),
        "pref_flow_tau_decay": _req("pref_flow_tau_decay_fit"),
    }
    names = [x for x in str(row.get("extraction_fit_param_names", "") or "").split(";") if x]
    values = [x for x in str(row.get("extraction_fit_param_values", "") or "").split(";") if x]
    if len(names) != len(values):
        raise ValueError(f"summary 的萃取參數名與值個數不一致：{names} vs {values}")
    params.update({n: float(v) for n, v in zip(names, values)})
    if abs(_req("tau_lag_s") - TAU_LAG_FIXED_S) > 1e-12:
        raise ValueError(f"summary 的 tau_lag_s 不等於 TAU_LAG_FIXED_S={TAU_LAG_FIXED_S}：{path}")
    return {
        "params": params,
        "k_beta_prior_psd": _req("k_beta_prior_psd"),
        "pref_live": "pref_flow_coeff" in live,
        "ext_live": any(n in live for n, *_ in EXTRACTION_FIT_PARAMS),
        "stage7_skipped_reason": str(row.get("stage7_skipped_reason", "") or ""),
        "summary_path": str(path),
    }


def _cache_key_value(x: float) -> float:
    """
    cache key 用的相對精度 round（10 位有效數字）。

    Why: 舊版用 `round(k, 15)` 這類**絕對**位數，對 `k ~ 1e-10` 等於保留 5 位
         有效數字（Powell 在 1e-15 的步長上全部撞同一個 key），對
         `k_beta ~ 2e3` 又等於保留 12 位（幾乎不命中）。同一份 cache 在不同
         量級的參數上行為完全相反。改成相對精度後，所有參數一致。
    """
    return float(f"{float(x):.10e}")


def _scalar_metrics(res: dict) -> dict:
    """
    從 χ² 評估結果剝掉時序陣列，只留純量。

    Why: 舊 loss cache 把整個 `sim` 存進 dict（~0.8 MB/entry），一次 fit 數百個
         entry 就是數百 MB，而 optimizer 只需要一個純量。
    """
    drop = {
        "sim", "obs_layer", "v_residual_ml", "retention_residual_ml",
        "v_pred_obs_ml", "q_pred_obs_mlps", "retention_pred_obs_ml",
        "server_series_residual_C", "outflow_series_residual_C",
    }
    return {k: v for k, v in res.items() if k not in drop}


def profile_ci(
    params_fit: V60Params,
    csv_path: str | Path,
    name: str,
    grid: np.ndarray,
    *,
    tau_lag_s: float,
    vessel_equivalent_ml: float | None = MEASURED_VESSEL_EQUIV_ML,
    reduced_chi2: float | None = None,
    k_beta_prior_psd: float | None = None,
    solver: dict | None = None,
    n_fit_params: int = DEFAULT_LIVE_PARAM_COUNT,
    case: dict | None = None,
) -> dict:
    """
    以 Δχ² 門檻給單一參數的 95% 區間。

    What:
        沿 `grid` 掃描 `name`（`"tau_lag_s"` 或任一 `V60Params` 欄位），
        取 Δχ² = 3.84 × max(reduced_chi2, 1) 的交點作為區間端點（線性插補）。

    Why 要乘 `max(reduced_chi2, 1)`：
        標準 Δχ² = 3.84 只在「σ 設定正確且模型無結構誤差」時成立。本模型的
        reduced χ² 目前遠大於 1（殘差自相關 0.914 → 結構誤差），此時直接用
        3.84 會給出荒謬地窄的 CI。乘上 reduced χ² 是標準的 **σ 誤設修正**
        （等價於把 σ 整體放大 √(reduced χ²)），讓 CI 反映「模型與資料的實際
        不一致程度」，而不是假裝 σ 是對的。

    **這是 conditional slice，不是嚴格的 profile likelihood**：掃描某個參數時
    其餘參數凍結在 `params_fit`，沒有重新最佳化。因此回傳的區間是**下界**
    （真 profile CI 只會更寬，不會更窄）。`mode` 欄明確標記這件事。
    嚴格 profile 需要每個格點各跑一次 Powell（成本 ×7×maxiter），在 F6 的
    refit 預算下不划算；若日後要做，把重新最佳化插進迴圈即可。
    """
    case = _prepare_measured_case(csv_path) if case is None else case
    solver_cfg = dict(SOLVER_FINE if solver is None else solver)
    grid = np.asarray(grid, dtype=float)

    chi2_vals = np.full(grid.size, np.nan)
    reduced_vals = np.full(grid.size, np.nan)
    for i, val in enumerate(grid):
        if name == "tau_lag_s":
            p_try, tau_try = params_fit, float(val)
        else:
            p_try, tau_try = dataclasses.replace(params_fit, **{name: float(val)}), float(tau_lag_s)
        res = _chi2_evaluate(
            case, p_try, tau_try,
            vessel_equivalent_ml=vessel_equivalent_ml,
            solver=solver_cfg,
            k_beta_prior_psd=k_beta_prior_psd,
            n_fit_params=n_fit_params,
            keep_sim=False,
        )
        chi2_vals[i] = res["chi2"]
        reduced_vals[i] = res["reduced_chi2"]

    i_min = int(np.nanargmin(chi2_vals))
    chi2_min = float(chi2_vals[i_min])
    # 未指定時，取 χ² 最小那一點的 reduced χ² 作為 σ 誤設修正係數
    # （不用「格點恰等於 fitted 值」去比對浮點數——那在 grid 稍有偏移時會靜默
    #   退回 corr = 1，給出過窄的 CI）。
    if reduced_chi2 is None:
        reduced_chi2 = float(reduced_vals[i_min])
    threshold = 3.84 * max(float(reduced_chi2), 1.0)

    def _cross(idx_range) -> float | None:
        """在給定方向上找 chi2 = chi2_min + threshold 的第一個交點。"""
        prev_i = i_min
        for i in idx_range:
            if not np.isfinite(chi2_vals[i]):
                return None
            if chi2_vals[i] - chi2_min >= threshold:
                y0, y1 = chi2_vals[prev_i] - chi2_min, chi2_vals[i] - chi2_min
                if abs(y1 - y0) < 1e-12:
                    return float(grid[i])
                frac = (threshold - y0) / (y1 - y0)
                return float(grid[prev_i] + frac * (grid[i] - grid[prev_i]))
            prev_i = i
        return None

    ci_lo = _cross(range(i_min - 1, -1, -1))
    ci_hi = _cross(range(i_min + 1, grid.size))
    return {
        "param": name,
        "mode": "conditional",           # 非嚴格 profile；見 docstring
        "grid": grid,
        "chi2": chi2_vals,
        "chi2_min": chi2_min,
        "value_at_min": float(grid[i_min]),
        "reduced_chi2": float(reduced_chi2),
        "delta_chi2_threshold": float(threshold),
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
    }


def default_ci_grid(center: float, n: int = 7, span: float = 2.0) -> np.ndarray:
    """以 `center` 為中心、log 對稱的 n 點格點（預設 0.5× ~ 2×）。"""
    return float(center) * np.geomspace(1.0 / span, span, n)


def fit_k_kbeta_from_flow_profile(
    csv_path: str | Path,
    params_init: V60Params | None = None,
    min_pour_ml: float = 1.0,
    weights: dict | None = None,
    vessel_equivalent_ml: float | None = MEASURED_VESSEL_EQUIV_ML,
    tau_lag_init_s: float = 1.0,
    tau_wet_init_s: float = TAU_WET_INIT_S,
    fit_preferential_flow: bool = False,
    pref_open_rate_fixed: float = DEFAULT_PREF_FLOW_OPEN_RATE_FIXED,
    pref_tau_decay_fixed: float = DEFAULT_PREF_FLOW_TAU_DECAY_FIXED,
    fit_server_cooling: bool = True,
    fit_liquid_dripper_lambda: bool = True,
    compute_ci: bool = True,
    verbose: bool = True,
    thermal_only_from_summary: str | Path | None = None,
) -> tuple[V60Params, dict]:
    """
    以 σ 正規化 χ² 為目標，分階段擬合水力 / 熱 / 萃取 closure。

    What:
      stage 1  (log k, log sat_rel_perm_exp, log tau_wet_s) 3D Powell
      stage 2  同上，從 stage 1 的解再收斂一次（不同起點 → 確認 basin）
      stage 4  （選用）`pref_flow_coeff`
      stage 5  熱端單一自由度（F11 起依熱觀測型態分配；舊 stage 6 已不存在）：
               有分享壺溫時序的影片 case 擬 `log U_liquid_dripper_W_m2K`、
               `lambda_server_ambient` 凍結 3.7e-4；單點杯溫 case 擬
               `log lambda_server_ambient`、U 凍結為 `U_LIQUID_DRIPPER_FIXED_W_M2K`
      stage 7  由 `EXTRACTION_FIT_PARAMS` 驅動的萃取端校準
      final    以 `SOLVER_FINE` 重算一次；`compute_ci=True` 時再跑 conditional CI

    `thermal_only_from_summary`（F6d）：
      給定一份既有 flow-fit summary 時，**只跑 stage 5**。水力（k、sat_rel_perm_exp、
      tau_wet_s、pref flow）與萃取（`EXTRACTION_FIT_PARAMS`）一律從該 summary
      讀回並固定，stage 1/2/4/7 不執行；這些參數仍計入 live 集合與 dof
      （它們是那一次 fit 的自由度，不因本次沒動而消失）。`params_init` 在此模式
      下被忽略。用途：熱端 closure 改動、水力與萃取沒變時，不必為了熱端重跑
      ~1 小時的 multi-start。summary 會記 `refit_scope = thermal_only` 與來源路徑。

    Why（相對舊流程的結構變更）：
      1. **F6b 自由度重配**：stage 1/2 的 live 集合由 `(k, k_beta, tau_lag, tau_wet)`
         改為 `(k, sat_rel_perm_exp, tau_wet)`。依據是 F6 §6.1 的 identifiability：
         `k_beta`（span 6.83 / 9.38）與 `tau_lag`（1.32 / 3.06）判定 **weak**，
         `sat_rel_perm_exp`（17.84 / 62.36）判定 **hard** 卻被凍結在 3.0。
         擬合兩個資料分不出來的參數、同時凍結一個資料分得出來的參數，是自由度
         與資訊量的直接錯配。重配後：
           - `k_beta` 凍結為該 case 的 PSD prior（Class B，`k_beta_prior_from_psd()`）
           - `tau_lag` 凍結為 `TAU_LAG_FIXED_S`（Class B 幾何常數）
           - `sat_rel_perm_exp` 開放（Class C，弱 prior 中心 3.0、σ 0.20 dex）
         live 參數總數不變（dof 反而 +1，因為凍結兩個只開放一個）。
      2. **熱端**：F2 起以物理熱導 `U_liquid_dripper_W_m2K` 取代
         `lambda_liquid_dripper`（DEPRECATED）；F6d 起單點杯溫 case 的 U 凍結在
         prior 中心（單點杯溫不識別 U），stage 5 只擬 λ_server。F11 起分享壺溫時序
         進 χ² 的影片 case 改擬 U、凍結 λ_server（時序下 U–λ 為 ridge，只撐得起
         一個熱端自由度）。
      3. **所有 stage 的接受條件統一為 Δχ² ≤ −1.0 且 clip flag 未觸發**。
         舊版三種尺度的 volume guard（+0.15 mL / +0.20 mL / +0.5 pt）與零餘裕
         的嚴格 `<` 已刪除——它們在不同 case 上代表不同嚴格程度，且其中兩個
         還跨 coarse/fine 比較。F6c 起 coarse 與 fine 的誤差控制相同、只差
         輸出網格密度，跨 mode 比較的殘差已降到 χ² 的 1.5 以內（見
         `SOLVER_COARSE` 的 Why），但「同一個門檻用同一個 solver 量」仍是
         這裡的規則。
      4. **stage 7 加水力自洽前置條件**：`|V_out_model − V_out_obs| / V_out_obs`
         > 5% 時直接跳過並記 `stage7_skipped_reason`，避免萃取參數吸收水力誤差。
      5. **`max_EY` 移出 fit**，凍結為 roast prior（AGENTS.md §4.D）。

    `weights` 參數已停用（保留簽名），χ² 權重由 `MEASUREMENT_SIGMA` 決定。
    """
    if weights is not None:
        warnings.warn(
            "fit_k_kbeta_from_flow_profile(weights=...) 已停用：loss 改為 σ 正規化 χ²。",
            DeprecationWarning,
            stacklevel=2,
        )
    case = _prepare_measured_case(csv_path)
    meta = case["meta"]
    t_obs = case["t_obs"]
    v_out_obs = case["v_out_obs"]
    fit_mask = case["fit_mask"]
    final_cup_temp_C = case["final_cup_temp_C"]
    final_tds_gl_obs = case["final_tds_gl"]
    stop_flow_time_s = case["stop_flow_time_s"]
    protocol = case["protocol"]

    roast_map = {
        "light": RoastProfile.LIGHT,
        "medium": RoastProfile.MEDIUM,
        "dark": RoastProfile.DARK,
    }
    roast_key = meta["roast"].strip().lower()
    profile = roast_map.get(roast_key)
    if profile is None:
        raise ValueError(f"未知烘焙度：{meta['roast']}")

    # thermal-only 模式：水力 / 萃取狀態從 summary 讀回，`params_init` 被忽略。
    carry = _read_thermal_only_carry(thermal_only_from_summary) \
        if thermal_only_from_summary is not None else None
    if carry is not None:
        params_init = V60Params(**carry["params"])
        tau_wet_init_s = float(carry["params"]["tau_wet_s"])

    if params_init is None:
        params_init = V60Params.for_roast(profile)
    else:
        params_init = V60Params.for_roast(profile, base=params_init)

    params_base = dataclasses.replace(
        params_init,
        # F6d：U 凍結（見 U_LIQUID_DRIPPER_FIXED_W_M2K）。顯式寫在這裡而不是依賴
        # V60Params 預設值：起點（LHS / sibling / 呼叫端）帶著別的 U 進來時也不會漏網。
        U_liquid_dripper_W_m2K=float(U_LIQUID_DRIPPER_FIXED_W_M2K),
        dose_g=_meta_float(meta, "dose_g"),
        h_bed=_meta_float(meta, "bed_height_cm", MEASURED_BED_HEIGHT_CM) / 100.0,
        T_brew=_meta_float(meta, "brew_temp_C") + 273.15,
        **_measured_setup_overrides(meta, flow_csv_path=csv_path),
    )
    # F11：有分享壺溫時序的 case，λ_server 凍結為物理估計（只擬 U；見 THERMAL_SERIES_FIT_PARAMS）。
    if case["server_series_t"].size > 0 and "lambda_server_ambient" not in THERMAL_SERIES_FIT_PARAMS:
        params_base = dataclasses.replace(
            params_base, lambda_server_ambient=float(LAMBDA_SERVER_SERIES_FIXED_PER_S))
    # PSD prior anchor 在 fit 開始時**凍結**並寫進 summary。
    # Why: 舊版 fit 時取 `params_base.k_beta_prior_psd`、reload 時取
    #      `params_fit.k_beta_prior_psd`；後者的 `k_beta` 已被 fit 改過，
    #      於是同一個 case 在 fit 與 reload 兩條路徑上的 prior 中心不同（AUD-6）。
    k_beta_prior_frozen = float(getattr(params_base, "k_beta_prior_psd", params_base.k_beta))

    # ── F6b：k_beta 與 tau_lag 退出 fit，凍結為 Class B 值 ────────────────────
    # `k_beta` 直接設成該 case 自己 PSD 算出的 prior 中心。這同時讓 χ² 的
    # `k_beta_psd` prior 項恆等於 0（見 `_chi2_evaluate`），因此重配不會靠
    # 一個殘留的常數項改變 stage 之間的 Δχ² 比較。
    params_base = dataclasses.replace(params_base, k_beta=k_beta_prior_frozen)
    if carry is not None and not np.isclose(k_beta_prior_frozen, carry["k_beta_prior_psd"], rtol=1e-9):
        # PSD（或其縮放）自那一次 fit 後變了 → 讀回的水力參數不再是這個模型的解。
        raise ValueError(
            f"thermal-only：PSD prior {k_beta_prior_frozen:.6g} ≠ summary 的 "
            f"{carry['k_beta_prior_psd']:.6g}；水力狀態已過期，必須完整重擬")
    if tau_lag_init_s != TAU_LAG_FIXED_S and verbose:
        print(f"  [F6b] tau_lag 已凍結為 {TAU_LAG_FIXED_S} s（Class B 幾何常數）；"
              f"忽略傳入的 tau_lag_init_s={tau_lag_init_s}")
    tau_lag_fixed = float(TAU_LAG_FIXED_S)

    if vessel_equivalent_ml is None and final_cup_temp_C is not None:
        sim_ref = simulate_brew(
            params_base, protocol, t_end=case["t_end"], **SOLVER_COARSE
        )
        obs_ref = apply_outflow_lag(sim_ref, tau_lag_fixed, ambient_temp_C=params_base.T_amb - 273.15)
        vessel_equivalent_ml = fit_vessel_equivalent_ml(
            {**sim_ref, "q_out_mlps": obs_ref["q_cup_mlps"], "T_C": obs_ref["T_cup_C"]},
            final_cup_temp_C=final_cup_temp_C,
            ambient_temp_C=params_base.T_amb - 273.15,
        )

    loss_cache: dict[tuple, dict] = {}

    def _evaluate(params_try: V60Params, tau_try: float, *, coarse: bool = True,
                  keep_sim: bool = False) -> dict:
        """統一入口：coarse 走 cache（只存純量），fine 一律重算。"""
        if coarse and not keep_sim:
            key = tuple(_cache_key_value(v) for v in (
                params_try.k, params_try.k_beta, tau_try,
                getattr(params_try, "pref_flow_coeff", 0.0),
                getattr(params_try, "pref_flow_open_rate", 0.0),
                getattr(params_try, "pref_flow_tau_decay", 0.0),
                getattr(params_try, "lambda_server_ambient", 0.0),
                getattr(params_try, "U_liquid_dripper_W_m2K", 0.0) or 0.0,
                getattr(params_try, "tau_wet_s", 0.0) or 0.0,
                # F6b：`sat_rel_perm_exp` 成為 live 參數後**必須**進 cache key，
                # 否則 Powell 沿該方向的每一步都會命中同一筆 cache 而拿到舊 χ²。
                getattr(params_try, "sat_rel_perm_exp", 0.0) or 0.0,
                *[getattr(params_try, n, 0.0) for n, *_ in EXTRACTION_FIT_PARAMS],
            ))
            hit = loss_cache.get(key)
            if hit is not None:
                return hit
        res = _chi2_evaluate(
            case, params_try, tau_try,
            vessel_equivalent_ml=vessel_equivalent_ml,
            solver=SOLVER_COARSE if coarse else SOLVER_FINE,
            k_beta_prior_psd=k_beta_prior_frozen,
            n_fit_params=DEFAULT_LIVE_PARAM_COUNT,
            keep_sim=keep_sim,
        )
        if coarse and not keep_sim:
            res = _scalar_metrics(res)
            loss_cache[key] = res
        return res

    def _accept(new: dict, base: dict, key: str = "chi2") -> bool:
        """stage 接受條件：Δχ²（該 stage 的目標，預設總 χ²）≤ −1.0 且未觸發 clip flag。"""
        return (new[key] - base[key]) <= STAGE_ACCEPT_DELTA_CHI2 and not new["clip_flag"]

    # ── 監控 timer ───────────────────────────────────────────────────────────
    stage_timings: list[dict] = []
    fit_t0_wall = time.perf_counter()
    fit_t0_proc = time.process_time()

    def _stage_start():
        return time.perf_counter(), time.process_time()

    def _stage_end(name: str, t0: tuple[float, float], nfev: int | None = None):
        wall = time.perf_counter() - t0[0]
        proc = time.process_time() - t0[1]
        stage_timings.append({
            "stage": name,
            "wall_s": float(wall),
            "process_s": float(proc),
            "wall_over_proc": float(wall / max(proc, 1e-9)),
            "nfev": int(nfev) if nfev is not None else None,
        })
        if verbose:
            nfev_str = f", nfev={nfev}" if nfev is not None else ""
            scale = wall / max(proc, 1e-9)
            stall = " [stall]" if scale > 1.5 else ""
            print(f"  [timer] {name}: wall={wall:.1f}s proc={proc:.1f}s ratio={scale:.2f}{nfev_str}{stall}")

    # ── Stage 1/2：(log k, log k_beta, log tau_lag) 3D Powell ────────────────
    # ftol 語意：Powell 的 `ftol` 是相對容差，對 χ² ~ 1e3 代表 ~1 的絕對變化。
    # 我們要的是「Δχ² < 0.05 才算收斂」，因此 options 給一個夠小的相對值，
    # 再由外層 stage 2 的 Δχ² 檢查確認真的收斂（單一 tolerance 無法表達絕對語意）。
    # tau_wet_s（F2b）只有在 params 帶這個欄位時才進 fit（用 hasattr 防呆）。
    fit_tau_wet = hasattr(params_base, "tau_wet_s")
    hyd_bounds = [
        (np.log10(K_BOUNDS_M2[0]), np.log10(K_BOUNDS_M2[1])),
        (np.log10(SAT_REL_PERM_EXP_BOUNDS[0]), np.log10(SAT_REL_PERM_EXP_BOUNDS[1])),
    ]
    if fit_tau_wet:
        hyd_bounds.append((np.log10(TAU_WET_BOUNDS_S[0]), np.log10(TAU_WET_BOUNDS_S[1])))

    def _hyd_params(log_x: np.ndarray) -> tuple[V60Params, float]:
        kw = {"k": 10.0 ** log_x[0], "sat_rel_perm_exp": float(10.0 ** log_x[1])}
        if fit_tau_wet:
            kw["tau_wet_s"] = float(10.0 ** log_x[2])
        return dataclasses.replace(params_base, **kw), tau_lag_fixed

    def _hyd_chi2(log_x: np.ndarray) -> float:
        p, tau = _hyd_params(log_x)
        return float(_evaluate(p, tau, coarse=True)["chi2_hydraulic"])

    x0 = [
        np.log10(np.clip(params_base.k, *K_BOUNDS_M2)),
        np.log10(np.clip(getattr(params_base, "sat_rel_perm_exp", SAT_REL_PERM_EXP_INIT),
                         *SAT_REL_PERM_EXP_BOUNDS)),
    ]
    if fit_tau_wet:
        x0.append(np.log10(np.clip(tau_wet_init_s, *TAU_WET_BOUNDS_S)))
    x0 = np.array(x0, dtype=float)

    if carry is None:
        t0 = _stage_start()
        res_stage1 = minimize(
            _hyd_chi2, x0, method="Powell", bounds=hyd_bounds,
            options={"xtol": 1e-3, "ftol": 1e-5, "maxiter": 90, "disp": False},
        )
        _stage_end("stage1_hydraulic", t0, nfev=getattr(res_stage1, "nfev", None))
        chi2_stage1 = float(res_stage1.fun)

        t0 = _stage_start()
        res_stage2 = minimize(
            _hyd_chi2, np.asarray(res_stage1.x, dtype=float), method="Powell", bounds=hyd_bounds,
            options={"xtol": 1e-3, "ftol": 1e-5, "maxiter": 90, "disp": False},
        )
        _stage_end("stage2_hydraulic", t0, nfev=getattr(res_stage2, "nfev", None))
        # Powell 從同一點重啟後可能沿新方向走一段又回不來，收在略高的 χ² 上。
        # 取兩者中較低者，否則 stage 2 會變成「有時候讓結果變差」的一步。
        res_hyd = res_stage1 if chi2_stage1 <= float(res_stage2.fun) else res_stage2
        hyd_converged = bool(abs(chi2_stage1 - float(res_stage2.fun)) < 0.05)
        if verbose and not hyd_converged:
            print(f"  [stage2] 未達 Δχ² < 0.05（stage1 {chi2_stage1:.3f} → "
                  f"stage2 {float(res_stage2.fun):.3f}；採用 χ² 較低者）")

        params_fit, tau_lag_fit = _hyd_params(np.asarray(res_hyd.x, dtype=float))
    else:
        # thermal-only：水力參數固定在 summary 值；stage 1/2 不執行，收斂性無從判定。
        res_stage1 = res_stage2 = None
        hyd_converged = None
        params_fit, tau_lag_fit = params_base, tau_lag_fixed
    res_stage4 = None
    res_stage5 = None
    res_stage7 = None
    stage7_skipped_reason = ""

    # ── Stage 4：preferential flow（選用；thermal-only 模式沿用 summary）────────
    if fit_preferential_flow and carry is None:
        t0 = _stage_start()
        pref_off = _evaluate(params_fit, tau_lag_fit, coarse=True)

        def _pref_chi2(log_x: np.ndarray) -> float:
            p = dataclasses.replace(
                params_fit,
                pref_flow_coeff=float(10.0 ** log_x[0]),
                pref_flow_open_rate=float(pref_open_rate_fixed),
                pref_flow_tau_decay=float(pref_tau_decay_fixed),
            )
            return float(_evaluate(p, tau_lag_fit, coarse=True)["chi2_hydraulic"])

        res_pref = minimize(
            _pref_chi2, np.array([np.log10(5.0e-5)]), method="Powell",
            bounds=[(np.log10(5.0e-6), np.log10(5.0e-4))],
            options={"xtol": 1e-3, "ftol": 1e-5, "maxiter": 110, "disp": False},
        )
        params_pref = dataclasses.replace(
            params_fit,
            pref_flow_coeff=float(10.0 ** res_pref.x[0]),
            pref_flow_open_rate=float(pref_open_rate_fixed),
            pref_flow_tau_decay=float(pref_tau_decay_fixed),
        )
        pref_new = _evaluate(params_pref, tau_lag_fit, coarse=True)
        if _accept(pref_new, pref_off, key="chi2_hydraulic"):
            params_fit = params_pref
            res_stage4 = res_pref
        if verbose:
            print(f"  [stage4] Δχ²_hyd={pref_new['chi2_hydraulic'] - pref_off['chi2_hydraulic']:+.2f} "
                  f"→ {'accept' if res_stage4 is not None else 'reject'}")
        _stage_end("stage4_pref", t0, nfev=getattr(res_pref, "nfev", None))

    # ── Stage 5：熱端（F11：自由度依觀測而定）──────────────────────────────
    # What: 只有單點杯溫（紀錄表 case）→ 1D `lambda_server_ambient`（F6d 行為，逐位元不變）；
    #       有分享壺溫時序（影片 case）→ `THERMAL_SERIES_FIT_PARAMS`（log 空間聯擬）。
    #       seed 網格取各參數 `THERMAL_FIT_SEEDS` 的笛卡兒積，Powell 從最佳 seed 出發。
    # Why:  F6d：一個終點杯溫只撐得起一個熱端自由度（U 的 CI None/None）。F11 的時序
    #       identifiability（canonical，時序 loss）決定哪些參數可進 fit，見
    #       `THERMAL_SERIES_FIT_PARAMS` 的 Why。
    thermal_names = (THERMAL_SERIES_FIT_PARAMS if case["server_series_t"].size > 0
                     else THERMAL_SINGLE_POINT_FIT_PARAMS)
    has_thermal_obs = final_cup_temp_C is not None or case["server_series_t"].size > 0
    if fit_server_cooling and has_thermal_obs and vessel_equivalent_ml is not None:
        t0 = _stage_start()
        thermal_off = _evaluate(params_fit, tau_lag_fit, coarse=True)
        th_bounds = [THERMAL_FIT_BOUNDS[n] for n in thermal_names]

        def _thermal_params(log_x) -> V60Params:
            vals = np.atleast_1d(log_x)
            return dataclasses.replace(
                params_fit, **{n: float(10.0 ** vals[j]) for j, n in enumerate(thermal_names)})

        def _thermal_chi2(log_x: np.ndarray) -> float:
            return float(_evaluate(_thermal_params(log_x), tau_lag_fit, coarse=True)["chi2"])

        # seed 只決定起點量級；接受與否由 Δχ² 統一把關。
        seed_vals, seed_chi2 = None, float("inf")
        for combo in itertools.product(*(THERMAL_FIT_SEEDS[n] for n in thermal_names)):
            c = float(_evaluate(
                dataclasses.replace(params_fit, **{n: float(v) for n, v in zip(thermal_names, combo)}),
                tau_lag_fit, coarse=True)["chi2"])
            if c < seed_chi2:
                seed_chi2, seed_vals = c, combo

        x0_thermal = np.array([np.log10(np.clip(v, *bd)) for v, bd in zip(seed_vals, th_bounds)])
        res_thermal = minimize(
            _thermal_chi2,
            x0_thermal,
            method="Powell",
            bounds=[(np.log10(lo), np.log10(hi)) for lo, hi in th_bounds],
            options={"xtol": 1e-3, "ftol": 1e-5, "maxiter": 150, "disp": False},
        )

        # ── 候選點擇優（F6 修正，取代「只看 Powell 回傳點」）────────────────
        # What: 在 {seed 網格最佳點, Powell 回傳點} 之中取 χ² 最低者，
        #       再交給統一的 Δχ² 守門（對照 stage 進入點）。
        # Why:  實測（F6 task 1，kinu29 4:11 的 4D 參考解）scipy 的 bounded Powell
        #       在 nit=1、status=0「成功收斂」的情況下回傳了比自己起點**高 3.10**
        #       的點（res.fun 與 f(res.x) 一致，因此不是 res.fun 的 wart，
        #       而是它真的回傳了較差的點）。同時 stage 進入點的 λ_server = 0
        #       落在搜尋區間 [1e-5, 1e-2] 之外，於是「Powell 結果 vs 進入點」
        #       比較的是 optimizer 從來沒有機會比較的兩個點——這正是 F4 §6.6.1
        #       記錄的 Δχ² = +19.30 的來源。取候選最小值後，這一步在結構上
        #       不可能讓 χ² 上升。
        cand: list[tuple[str, V60Params, dict]] = []
        for tag, lx in (("seed", x0_thermal), ("powell", np.asarray(res_thermal.x, dtype=float))):
            pp = _thermal_params(lx)
            cand.append((tag, pp, _evaluate(pp, tau_lag_fit, coarse=True)))
        best_tag, params_thermal, thermal_new = min(cand, key=lambda c: c[2]["chi2"])
        if _accept(thermal_new, thermal_off):
            params_fit = params_thermal
            res_stage5 = res_thermal
        if verbose:
            u_tag = "" if "U_liquid_dripper_W_m2K" in thermal_names else " (fixed)"
            print(f"  [stage5] live {','.join(thermal_names)}: "
                  f"U={params_thermal.U_liquid_dripper_W_m2K:.1f} W/m²K{u_tag}, "
                  f"λ_srv={params_thermal.lambda_server_ambient:.2e} (from {best_tag}; "
                  f"powell Δ vs seed = {cand[1][2]['chi2'] - cand[0][2]['chi2']:+.2f}), "
                  f"Δχ²={thermal_new['chi2'] - thermal_off['chi2']:+.2f} "
                  f"→ {'accept' if res_stage5 is not None else 'reject'}")
        _stage_end("stage5_thermal", t0, nfev=getattr(res_thermal, "nfev", None))

    # ── Stage 7：萃取（由 EXTRACTION_FIT_PARAMS 驅動）────────────────────────
    # 三道前置條件，任何一道不過就跳過並記錄原因（不靜默略過）：
    #   1. 有量測 TDS（沒有就沒有可擬的觀測）
    #   2. 表上的參數確實存在於目前的 V60Params（跨 slice 介面的過渡期防呆）
    #   3. 水力自洽：V_out 沒對上時，萃取端不得替水力誤差背書
    stage7_specs = [sp for sp in EXTRACTION_FIT_PARAMS if hasattr(params_fit, sp[0])]
    if carry is not None:
        # thermal-only：萃取參數沿用 summary；原因欄照抄那一次 fit 的判定。
        stage7_skipped_reason = carry["stage7_skipped_reason"]
    elif final_tds_gl_obs is None:
        stage7_skipped_reason = "no_measured_tds"
    elif not EXTRACTION_FIT_PARAMS:
        stage7_skipped_reason = "no_extraction_fit_params"
    elif not stage7_specs:
        stage7_skipped_reason = "extraction_params_not_in_model"
    else:
        t0 = _stage_start()
        ext_off = _evaluate(params_fit, tau_lag_fit, coarse=True, keep_sim=True)
        v_out_model_end = float(np.interp(
            case["t_final_obs_s"],
            np.asarray(ext_off["sim"]["t"], dtype=float),
            np.asarray(ext_off["obs_layer"]["v_cup_ml"], dtype=float),
        ))
        v_out_obs_end = case["v_out_final_obs_ml"]
        v_mismatch = abs(v_out_model_end - v_out_obs_end) / max(abs(v_out_obs_end), 1e-9)
        if v_mismatch > STAGE7_V_OUT_TOLERANCE:
            stage7_skipped_reason = "hydraulic_V_out_mismatch"
            if verbose:
                print(f"  [stage7] skipped: |ΔV_out|/V_out = {v_mismatch*100:.1f}% "
                      f"> {STAGE7_V_OUT_TOLERANCE*100:.0f}%")
        else:
            ext_off_scalar = _scalar_metrics(ext_off)
            x0_ext, bounds_ext = [], []
            for name, transform, lo, hi in stage7_specs:
                cur = float(getattr(params_fit, name))
                if transform == "log10":
                    x0_ext.append(np.log10(np.clip(cur, lo, hi)))
                    bounds_ext.append((np.log10(lo), np.log10(hi)))
                else:
                    x0_ext.append(np.clip(cur, lo, hi))
                    bounds_ext.append((lo, hi))

            def _ext_params(x: np.ndarray) -> V60Params:
                kw = {}
                for j, (name, transform, lo, hi) in enumerate(stage7_specs):
                    v = 10.0 ** x[j] if transform == "log10" else float(x[j])
                    kw[name] = float(np.clip(v, lo, hi))
                return dataclasses.replace(params_fit, **kw)

            def _ext_chi2(x: np.ndarray) -> float:
                return float(_evaluate(_ext_params(x), tau_lag_fit, coarse=True)["chi2"])

            res_ext = minimize(
                _ext_chi2, np.asarray(x0_ext, dtype=float), method="Powell",
                bounds=bounds_ext,
                options={"xtol": 1e-3, "ftol": 1e-5, "maxiter": 100, "disp": False},
            )
            params_ext = _ext_params(np.atleast_1d(np.asarray(res_ext.x, dtype=float)))
            ext_new = _evaluate(params_ext, tau_lag_fit, coarse=True)
            if _accept(ext_new, ext_off_scalar):
                params_fit = params_ext
                res_stage7 = res_ext
            else:
                stage7_skipped_reason = "no_chi2_improvement"
            if verbose:
                print(f"  [stage7] Δχ²={ext_new['chi2'] - ext_off_scalar['chi2']:+.2f} "
                      f"→ {'accept' if res_stage7 is not None else 'reject'}")
        _stage_end("stage7_extraction", t0, nfev=getattr(res_stage7, "nfev", None) if res_stage7 else None)

    # ── Final：fine solver 重算 ─────────────────────────────────────────────
    t0 = _stage_start()
    # live 參數（F6b / F6d）：stage 1/2 的 (k, sat_rel_perm_exp, tau_wet_s) +
    # 被接受的 stage 4 / 5 / 7。`k_beta`、`tau_lag`、`U_liquid_dripper` 已凍結，
    # 不消耗自由度。thermal-only 模式的 stage 4 / 7 是否 live 沿用 summary。
    # 名單與計數由同一份 list 導出，dof 與 `fit_live_param_names` 不可能不一致。
    pref_live = res_stage4 is not None or bool(carry and carry["pref_live"])
    ext_live = res_stage7 is not None or bool(carry and carry["ext_live"])
    live_names = (
        ["k", "sat_rel_perm_exp"]
        + (["tau_wet_s"] if fit_tau_wet else [])
        + (["pref_flow_coeff"] if pref_live else [])
        + (list(thermal_names) if res_stage5 is not None else [])
        + ([n for n, *_ in EXTRACTION_FIT_PARAMS] if ext_live else [])
    )
    n_live = len(live_names)
    final = _chi2_evaluate(
        case, params_fit, tau_lag_fit,
        vessel_equivalent_ml=vessel_equivalent_ml,
        solver=SOLVER_FINE,
        k_beta_prior_psd=k_beta_prior_frozen,
        n_fit_params=n_live,
        keep_sim=True,
    )
    _stage_end("final_eval", t0, nfev=1)

    # ── Conditional CI（Δχ² = 3.84 × max(reduced χ², 1)）────────────────────
    ci: dict[str, dict] = {}
    if compute_ci:
        t0 = _stage_start()
        # 只對 live 參數做 CI。凍結參數（`k_beta`、`tau_lag`）的 conditional
        # slice 在數值上仍算得出來，但它不是信賴區間——那條曲線描述的是
        # 「若當初讓它自由會怎樣」，把它寫進 summary 的 `*_ci_*` 欄會讓讀者
        # 誤以為那是本次擬合的不確定度。要回答那個問題請看 identifiability。
        ci_specs = [
            ("k", float(params_fit.k)),
            ("sat_rel_perm_exp", float(params_fit.sat_rel_perm_exp)),
        ]
        if fit_tau_wet:
            ci_specs.append(("tau_wet_s", float(params_fit.tau_wet_s)))
        # 熱端（F11）：stage 5 被接受的 live 熱參數一併做 CI；凍結者不做（理由同上）。
        # 單點杯溫 case 維持 F6d 行為（λ_server 不做 CI），確保 4:11 的 summary 不變。
        if res_stage5 is not None and case["server_series_t"].size > 0:
            ci_specs.extend((n, float(getattr(params_fit, n))) for n in thermal_names)
        for name, center in ci_specs:
            ci[name] = profile_ci(
                params_fit, csv_path, name, default_ci_grid(center, n=7),
                tau_lag_s=tau_lag_fit,
                vessel_equivalent_ml=vessel_equivalent_ml,
                reduced_chi2=final["reduced_chi2"],
                k_beta_prior_psd=k_beta_prior_frozen,
                n_fit_params=n_live,
                case=case,
            )
        _stage_end("profile_ci", t0, nfev=7 * len(ci_specs))

    fit_wall = time.perf_counter() - fit_t0_wall
    fit_proc = time.process_time() - fit_t0_proc
    sim_final = final["sim"]
    obs_final = final["obs_layer"]
    pref_flow_active = bool(
        (fit_preferential_flow or carry is not None)
        and getattr(params_fit, "pref_flow_coeff", 0.0) > 0.0
    )

    info = {
        "csv_path": str(csv_path),
        "roast": roast_key,
        "protocol": protocol,
        "bloom_end_s": float(protocol.bloom_end_time()),
        "stage_res": {
            "stage1": res_stage1,
            "stage2": res_stage2,
            "stage4_pref": res_stage4,
            "stage5_server": res_stage5,
            # F6d：U 凍結後不再有 stage 6；key 保留（恆 None）以免讀取端 KeyError。
            "stage6_liq_dripper": None,
            "stage7_extraction": res_stage7,
        },
        "hydraulic_converged": hyd_converged,   # thermal-only 模式為 None（未執行 stage 1/2）
        "refit_scope": "full" if carry is None else "thermal_only",
        "carried_from_summary": "" if carry is None else carry["summary_path"],
        "sim_final": sim_final,
        "obs_layer": obs_final,
        # ── χ² 與結構檢定 ────────────────────────────────────────────────
        "chi2": final["chi2"],
        "chi2_hydraulic": final["chi2_hydraulic"],
        "chi2_data": final["chi2_data"],
        "reduced_chi2": final["reduced_chi2"],
        "dof": final["dof"],
        "n_obs": final["n_obs"],
        "chi2_terms": final["chi2_terms"],
        "chi2_prior_terms": final["chi2_prior_terms"],
        "total_loss": final["chi2"],
        "residual_lag1": final["residual_lag1"],
        "durbin_watson": final["durbin_watson"],
        "runs_z": final["runs_z"],
        **{k: final[k] for k in WHITENESS_REPORT_KEYS},
        "stop_operator": case.get("stop_operator", "q_threshold"),
        "stop_flow_time_csv_s": case.get("stop_flow_time_csv_s"),
        # ── 診斷指標 ────────────────────────────────────────────────────
        "rmse_ml": final["volume_rmse"],
        "velocity_rmse_mlps": final["velocity_rmse"],
        "retention_rmse_ml": final["retention_rmse_ml"],
        "retention_final_model_ml": final["retention_final_model_ml"],
        "retention_final_time_s": final.get("retention_final_time_s"),
        "retention_final_obs_ml": final["retention_final_obs_ml"],
        "paper_holdup_final_ml": final["paper_holdup_final_ml"],
        "water_balance_residual_ml": final["water_balance_residual_ml"],
        "energy_residual_fraction": final["energy_residual_fraction"],
        "clip_active_fraction": final["clip_active_fraction"],
        "clip_flag": final["clip_flag"],
        # ── 參數 ────────────────────────────────────────────────────────
        "k_fit": float(params_fit.k),
        "k_beta_fit": float(params_fit.k_beta),
        "k_beta_prior_psd": k_beta_prior_frozen,
        "k_beta_prior_sigma_dex": float(getattr(params_base, "k_beta_prior_sigma_dex", KBETA_PRIOR_SIGMA_DEX)),
        "k_beta_throat_fit": float(getattr(params_fit, "k_beta_throat_coeff", np.nan)),
        "k_beta_deposition_fit": float(getattr(params_fit, "k_beta_deposition_coeff", np.nan)),
        "k_beta_throat_prior": float(getattr(params_base, "k_beta_throat_prior", np.nan)),
        "k_beta_deposition_prior": float(getattr(params_base, "k_beta_deposition_prior", np.nan)),
        "tau_lag_s": float(tau_lag_fit),
        # ── F6b 自由度重配的顯式標記（summary / 報告 / reload 都依賴它）──────
        "k_beta_fixed_from_prior": True,
        "tau_lag_fixed": True,
        "tau_lag_fixed_s": float(TAU_LAG_FIXED_S),
        "sat_rel_perm_exp_prior": float(SAT_REL_PERM_EXP_PRIOR),
        "sat_rel_perm_exp_prior_sigma_dex": float(SAT_REL_PERM_EXP_PRIOR_SIGMA_DEX),
        "fit_live_param_names": ";".join(live_names),
        "tau_wet_s_fit": float(getattr(params_fit, "tau_wet_s", np.nan)),
        "fit_tau_wet": bool(fit_tau_wet),
        "tau_wet_bounds_s": f"{TAU_WET_BOUNDS_S[0]:g};{TAU_WET_BOUNDS_S[1]:g}",
        "tau_wet_at_bound": bool(
            fit_tau_wet and (
                float(getattr(params_fit, "tau_wet_s", 0.0)) >= TAU_WET_BOUNDS_S[1] * 0.99
                or float(getattr(params_fit, "tau_wet_s", 0.0)) <= TAU_WET_BOUNDS_S[0] * 1.01
            )
        ),
        # 欄名保留 `_fit`（讀取端相容）；值自 F6d 起恆為凍結值，由 `_fixed` 標明。
        "U_liquid_dripper_fit": float(getattr(params_fit, "U_liquid_dripper_W_m2K", np.nan) or np.nan),
        "U_liquid_dripper_prior": float(U_LIQUID_DRIPPER_PRIOR_W_M2K),
        "U_liquid_dripper_fixed": "U_liquid_dripper_W_m2K" not in live_names,
        "thermal_fit_param_names": ";".join(thermal_names),
        "fit_preferential_flow": pref_flow_active,
        "pref_flow_coeff_fit": float(getattr(params_fit, "pref_flow_coeff", 0.0)),
        "pref_flow_open_rate_fit": float(getattr(params_fit, "pref_flow_open_rate", 0.0)),
        "pref_flow_tau_decay_fit": float(getattr(params_fit, "pref_flow_tau_decay", 0.0)),
        "pref_flow_open_rate_fixed": float(pref_open_rate_fixed),
        "pref_flow_tau_decay_fixed": float(pref_tau_decay_fixed),
        # ── 觀測序列 ────────────────────────────────────────────────────
        "t_obs_s": t_obs,
        "v_in_obs_ml": case["v_in_obs"],
        "v_out_obs_ml": v_out_obs,
        "retained_obs_ml": case["retained_obs"],
        "retention_basis": case["retention_basis"],
        # 量測紀錄品質旗標（F6b）：一路帶到 summary / benchmark CSV，供 F7b 揭露。
        "data_quality_flags": list(case.get("data_quality_flags", [])),
        # F9 量測預處理：逐列修正紀錄、注水率上限、逐點 V_out σ。
        "preprocess_corrections": case["preprocess_corrections"],
        "max_pour_rate_g_s": case["max_pour_rate_g_s"],
        "sigma_v_obs_ml": case["sigma_v_obs_ml"],
        # F10：量測來源 / 時間基準 / 抽樣（含實際使用的 reading_time_sigma_s）。
        **_case_provenance(case),
        # F10：完整觀測格點上的模型序列與同一次沖煮的熱時序診斷（不進 χ²）。
        **full_series_diagnostics(case, sim_final, obs_final),
        "model_v_out_ml": obs_final["v_cup_ml"],
        "fit_mask": fit_mask,
        "q_obs_mlps": case["q_obs_mlps"],
        "q_pred_obs_mlps": final["q_pred_obs_mlps"],
        "v_pred_obs_ml": final["v_pred_obs_ml"],
        # 模型保水（床內 + 出口暫存 + 濾紙潤濕）插到量測時刻，供 viz 直接畫。
        "retention_pred_obs_ml": final["retention_pred_obs_ml"],
        "model_q_out_mlps": obs_final["q_cup_mlps"],
        "model_T_out_C": obs_final["T_cup_C"],
        # ── 觀測層對應 ──────────────────────────────────────────────────
        "stop_flow_time_s": stop_flow_time_s,
        "cup_stop_time_s": final["cup_stop_time_s"],
        "cup_stop_time_error_s": final["cup_stop_time_error_s"],
        "drain_time_error_s": final["cup_stop_time_error_s"],   # deprecated 別名
        "final_cup_temp_C": final_cup_temp_C,
        "final_temp_read_time_s": case["final_temp_read_time_s"],
        "mixed_cup_temp_C": final["mixed_cup_temp_C"],
        "cup_temp_error_C": final["cup_temp_error_C"],
        # F11：χ² 分項與熱時序（進 χ² 的點）摘要。
        **thermal_series_summary(final),
        "vessel_equivalent_ml": vessel_equivalent_ml,
        # F11：影片 case 的 stage 5 擬的是 U；λ_server 是否為自由度以 live 名單為準。
        "fit_server_cooling": "lambda_server_ambient" in live_names,
        "lambda_server_fixed": "lambda_server_ambient" not in live_names,
        "server_cooling_lambda_fit": float(getattr(params_fit, "lambda_server_ambient", 0.0)),
        "fit_liquid_dripper_lambda": False,   # F6d：液體→濾杯熱導已凍結
        "lambda_liquid_dripper_fit": float(getattr(params_fit, "lambda_liquid_dripper", 0.0)),
        "lambda_liquid_dripper_prior": float(MEASURED_LIQUID_DRIPPER_LAMBDA),
        # ── 萃取 ────────────────────────────────────────────────────────
        "final_tds_gl_obs": final_tds_gl_obs,
        "final_tds_gl_pred": final["tds_pred_measured_denominator"],
        "tds_pred_measured_denominator": final["tds_pred_measured_denominator"],
        "tds_error_gl": final["tds_error_gl"],
        "m_extracted_pred_g": final["m_extracted_pred_g"],
        "fit_extraction": bool(ext_live),
        "stage7_skipped_reason": stage7_skipped_reason,
        "extraction_fit_params": {
            name: float(getattr(params_fit, name))
            for name, *_ in EXTRACTION_FIT_PARAMS
            if hasattr(params_fit, name)
        },
        "k_ext_slow_coef_fit": float(getattr(params_fit, "k_ext_slow_coef", 0.0)),
        "k_ext_fast_coef_fit": float(getattr(params_fit, "k_ext_fast_coef", 0.0)),
        "max_EY_fit": float(getattr(params_fit, "max_EY", 0.0)),
        # ── 其他 ────────────────────────────────────────────────────────
        "h_bed_cm": float(params_fit.h_bed * 100.0),
        "rho_bulk_dry_g_ml": float(params_fit.rho_bulk_dry_g_ml),
        "axial_node_count": int(getattr(params_fit, "axial_node_count", 1)),
        "sat_rel_perm_residual_fit": float(getattr(params_fit, "sat_rel_perm_residual", np.nan)),
        "sat_rel_perm_exp_fit": float(getattr(params_fit, "sat_rel_perm_exp", np.nan)),
        "ci": ci,
        "stage_timings": stage_timings,
        "fit_wall_s": float(fit_wall),
        "fit_process_s": float(fit_proc),
        "loss_cache_entries": len(loss_cache),
    }

    if verbose:
        print_flow_fit_report(info)
    return params_fit, info


def print_flow_fit_report(info: dict) -> None:
    """
    以可掃描格式列印一次擬合的結果（AGENTS.md §8 的輸出格式要求）。
    """
    ci = info.get("ci", {})

    def _ci_str(name: str) -> str:
        row = ci.get(name)
        if row is None:
            return ""
        lo = "-inf" if row["ci_lo"] is None else f"{row['ci_lo']:.4g}"
        hi = "+inf" if row["ci_hi"] is None else f"{row['ci_hi']:.4g}"
        return f"  CI95 [{lo}, {hi}]"

    print("=== Measured Flow Fit (sigma-normalised chi2) ===")
    print(f"  CSV            : {info['csv_path']}")
    print(f"  profile        : {info.get('profile_source', 'log')} ({info.get('profile_path', '')}); "
          f"time_base {info.get('time_base', '')}, timer rate {info.get('scale_timer_rate_applied')}, "
          f"sigma_t {info.get('reading_time_sigma_s')} s, stride {info.get('fit_stride_s')}")
    print(f"  chi2           : {info['chi2']:.2f}   (data {info['chi2_data']:.2f}"
          f" + prior {info['chi2'] - info['chi2_data']:.2f})")
    print(f"  reduced chi2   : {info['reduced_chi2']:.2f}   (dof {info['dof']}, N_obs {info['n_obs']})")
    terms = info["chi2_terms"]
    total_terms = max(sum(terms.values()), 1e-12)
    print("  --- chi2 breakdown ---")
    for key, val in sorted(terms.items(), key=lambda kv: -kv[1]):
        print(f"    {key:<16}: {val:10.2f}  ({val/total_terms*100:5.1f}%)")
    for key, val in info["chi2_prior_terms"].items():
        print(f"    prior:{key:<10}: {val:10.2f}")
    print("  --- residual structure (V_out) ---")
    print(f"    lag-1 autocorr : {info['residual_lag1']:+.3f}   (white noise ~ 0)")
    print(f"    Durbin-Watson  : {info['durbin_watson']:.3f}   (white noise ~ 2)")
    print(f"    runs-test z    : {info['runs_z']:+.2f}   (|z| < 2 = random)")
    print("  --- parameters ---")
    print(f"    live params    : {info.get('fit_live_param_names', '')}")
    if info.get("refit_scope") == "thermal_only":
        print(f"    refit scope    : thermal_only (hydraulic / extraction carried from "
              f"{info.get('carried_from_summary', '')})")
    print(f"    k              : {info['k_fit']:.4e} m^2{_ci_str('k')}")
    print(f"    sat_rel_perm_n : {info['sat_rel_perm_exp_fit']:.3f}{_ci_str('sat_rel_perm_exp')}"
          f"   (prior {info.get('sat_rel_perm_exp_prior', float('nan')):.1f}, "
          f"sigma {info.get('sat_rel_perm_exp_prior_sigma_dex', float('nan')):.2f} dex)")
    kb_tag = " [FIXED = PSD prior]" if info.get("k_beta_fixed_from_prior") else ""
    print(f"    k_beta         : {info['k_beta_fit']:.4e} 1/m^3{kb_tag}")
    print(f"      prior (PSD)  : {info['k_beta_prior_psd']:.4e} "
          f"(sigma {info['k_beta_prior_sigma_dex']:.2f} dex, frozen at fit start)")
    tl_tag = " [FIXED, Class B geometry]" if info.get("tau_lag_fixed") else ""
    print(f"    tau_lag        : {info['tau_lag_s']:.3f} s{tl_tag}")
    if info.get("fit_tau_wet"):
        bnd = "  [AT BOUND]" if info.get("tau_wet_at_bound") else ""
        print(f"    tau_wet        : {info['tau_wet_s_fit']:.2f} s{_ci_str('tau_wet_s')}"
              f"   bounds {info.get('tau_wet_bounds_s','')}{bnd}")
    u_tag = " [FIXED = prior]" if info.get("U_liquid_dripper_fixed") else ""
    print(f"    U_liq_dripper  : {info['U_liquid_dripper_fit']:.1f} W/m2K{u_tag}"
          f"{_ci_str('U_liquid_dripper_W_m2K')}")
    ls_tag = " [FIXED, physical estimate]" if info.get("lambda_server_fixed") else ""
    print(f"    lambda_server  : {info['server_cooling_lambda_fit']:.3e} 1/s{ls_tag}"
          f"{_ci_str('lambda_server_ambient')}")
    print("  --- diagnostics (not in loss) ---")
    print(f"    V_out RMSE     : {info['rmse_ml']:.2f} mL")
    print(f"    q_out RMSE     : {info['velocity_rmse_mlps']:.3f} mL/s")
    print(f"    retention RMSE : {info['retention_rmse_ml']:.2f} mL "
          f"(final model {info['retention_final_model_ml']:.1f} vs obs {info['retention_final_obs_ml']:.1f}"
          f", incl. paper {info.get('paper_holdup_final_ml', 0.0):.1f})")
    print(f"    cup stop error : {info['cup_stop_time_error_s']:+.2f} s")
    if info.get("cup_temp_error_C") is not None:
        print(f"    cup temp error : {info['cup_temp_error_C']:+.2f} degC "
              f"(read at t = {info['final_temp_read_time_s']:.0f} s)")
    if info.get("tds_error_gl") is not None:
        print(f"    TDS error      : {info['tds_error_gl']:+.2f} g/L "
              f"(measured V_out denominator)")
    if info.get("thermal_video_server_n"):
        print(f"    [video thermal, not in loss] server RMSE {info['thermal_video_server_rmse_C']:.2f} degC "
              f"(bias {info['thermal_video_server_bias_C']:+.2f}, n {info['thermal_video_server_n']}); "
              f"outflow RMSE {info['thermal_video_outflow_rmse_C']:.2f} degC "
              f"(bias {info['thermal_video_outflow_bias_C']:+.2f}, n {info['thermal_video_outflow_n']})")
    print(f"    water residual : {info['water_balance_residual_ml']:.2e} mL"
          f"   clip {info['clip_active_fraction']*100:.2f}%")
    if info.get("stage7_skipped_reason"):
        print(f"    stage7 skipped : {info['stage7_skipped_reason']}")


def save_flow_fit_summary_csv(output_path: str | Path, info: dict) -> None:
    """
    將流動標定摘要寫入 CSV。

    What: 輸出擬合參數、χ² 與結構檢定、CI 區間與模擬關鍵終值。
    Why:  流動標定通常會反覆迭代，摘要 CSV 比 console log 更適合版本管理；
          benchmark / identifiability / showcase 三條路徑都由這份 CSV reload
          calibrated state，因此**凍結的 prior anchor 必須寫進來**，否則
          reload 時會用 fit 後的 `k_beta` 反推出不同的 prior 中心（AUD-6）。

    欄位相容性（expand 期）：
      - `drain_time_error_s` 保留一個週期，值等同新名 `cup_stop_time_error_s`。
        它從來就不是「床層排乾時間」的誤差，而是**杯中目視停流**的誤差。
      - `drain_time_s` 為模型端診斷量（床層出口 q < 0.05 mL/s 的時刻），
        與量測的 `stop_flow_time_s` 不是同一個觀測面，不可直接相減。
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ci = info.get("ci", {}) or {}

    def _ci(name: str, side: str):
        row = ci.get(name)
        return None if row is None else row.get(f"ci_{side}")

    row = {
        "csv_path": info["csv_path"],
        "roast": info["roast"],
        # ── 擬合參數 ────────────────────────────────────────────────────
        "k_fit": info["k_fit"],
        "k_beta_fit": info["k_beta_fit"],
        "k_beta_prior_psd": info.get("k_beta_prior_psd"),
        "k_beta_prior_sigma_dex": info.get("k_beta_prior_sigma_dex"),
        "k_beta_throat_fit": info.get("k_beta_throat_fit"),
        "k_beta_deposition_fit": info.get("k_beta_deposition_fit"),
        "k_beta_throat_prior": info.get("k_beta_throat_prior"),
        "k_beta_deposition_prior": info.get("k_beta_deposition_prior"),
        "tau_lag_s": info.get("tau_lag_s"),
        # ── F6b 自由度重配標記 ──────────────────────────────────────────
        # 讀 summary 的人必須能分辨「這個數字是擬出來的」還是「凍結的」。
        "k_beta_fixed_from_prior": info.get("k_beta_fixed_from_prior"),
        "tau_lag_fixed": info.get("tau_lag_fixed"),
        "tau_lag_fixed_s": info.get("tau_lag_fixed_s"),
        "fit_live_param_names": info.get("fit_live_param_names"),
        # 量測紀錄品質旗標（F6b）。非空 → 該 case 的校準值受紀錄限制，
        # 不得當成獨立的交叉驗證結果（見 measured_io.flow_profile_quality_flags）。
        "data_quality_flags": ";".join(info.get("data_quality_flags", []) or []),
        # F9 量測預處理（`preprocess.preprocess_flow_profile`）：修正紀錄（分號分隔，
        # 空 = 無修正）、推得的注水率上限、讀取時刻 σ。
        "preprocess_corrections": info.get("preprocess_corrections", ""),
        "max_pour_rate_g_s": info.get("max_pour_rate_g_s"),
        "reading_time_sigma_s": info.get("reading_time_sigma_s"),
        # F10：量測來源（video = 錄影逐格；log = 手寫紀錄表）、實際讀的檔、時間基準、
        # 秤計時器速率換算（log = SCALE_TIMER_RATE；video = 1.0）、χ² 抽樣間隔、杯溫來源。
        "profile_source": info.get("profile_source", "log"),
        "profile_path": info.get("profile_path", ""),
        "video_id": info.get("video_id", ""),
        "time_base": info.get("time_base", ""),
        "scale_timer_rate_applied": info.get("scale_timer_rate_applied"),
        "fit_stride_s": info.get("fit_stride_s"),
        "final_coffee_temp_source": info.get("final_coffee_temp_source", ""),
        "sat_rel_perm_exp_prior": info.get("sat_rel_perm_exp_prior"),
        "sat_rel_perm_exp_prior_sigma_dex": info.get("sat_rel_perm_exp_prior_sigma_dex"),
        "tau_wet_s_fit": info.get("tau_wet_s_fit"),
        "tau_wet_bounds_s": info.get("tau_wet_bounds_s"),
        "tau_wet_at_bound": info.get("tau_wet_at_bound"),
        "U_liquid_dripper_fit": info.get("U_liquid_dripper_fit"),
        "U_liquid_dripper_prior": info.get("U_liquid_dripper_prior"),
        # F6d：True = U 凍結在 prior 中心、不是本次擬合的自由度（`_fit` 欄只是回報值）。
        "U_liquid_dripper_fixed": info.get("U_liquid_dripper_fixed"),
        # full = 全部 stage 都在這次執行；thermal_only = 只跑 stage 5，水力 / 萃取
        # 參數沿用 `carried_from_summary`；multi-start 不重跑，CI 是在沿用點上重算的
        # conditional slice。
        "refit_scope": info.get("refit_scope", "full"),
        "carried_from_summary": info.get("carried_from_summary", ""),
        # ── CI（conditional slice，Δχ² = 3.84 × max(reduced χ², 1)）──────
        "k_ci_lo": _ci("k", "lo"),
        "k_ci_hi": _ci("k", "hi"),
        # `k_beta` / `tau_lag` 自 F6b 起為凍結參數，CI 欄恆為空（欄位保留以免
        # 破壞既有讀取端；空值即「此參數不是本次擬合的自由度」）。
        "k_beta_ci_lo": _ci("k_beta", "lo"),
        "k_beta_ci_hi": _ci("k_beta", "hi"),
        "tau_lag_ci_lo": _ci("tau_lag_s", "lo"),
        "tau_lag_ci_hi": _ci("tau_lag_s", "hi"),
        "sat_rel_perm_exp_ci_lo": _ci("sat_rel_perm_exp", "lo"),
        "sat_rel_perm_exp_ci_hi": _ci("sat_rel_perm_exp", "hi"),
        "tau_wet_ci_lo": _ci("tau_wet_s", "lo"),
        "tau_wet_ci_hi": _ci("tau_wet_s", "hi"),
        # U：單點杯溫 case 凍結（F6d）→ 空；影片時序 case 若 U 為 live（F11）才有值。
        "U_liquid_dripper_ci_lo": _ci("U_liquid_dripper_W_m2K", "lo"),
        "U_liquid_dripper_ci_hi": _ci("U_liquid_dripper_W_m2K", "hi"),
        # ── χ² 與殘差結構 ───────────────────────────────────────────────
        "chi2": info.get("chi2"),
        "chi2_hydraulic": info.get("chi2_hydraulic"),
        "chi2_data": info.get("chi2_data"),
        "reduced_chi2": info.get("reduced_chi2"),
        "dof": info.get("dof"),
        "n_obs": info.get("n_obs"),
        "residual_lag1": info.get("residual_lag1"),
        "durbin_watson": info.get("durbin_watson"),
        "runs_z": info.get("runs_z"),
        # F12a：白噪音檢定的基準（標準化殘差）與附報欄（σ-class ≤ 6 mL 子序列、舊 mL 殘差）
        **{k: info.get(k) for k in WHITENESS_REPORT_KEYS},
        # ── 診斷指標（不進 loss）────────────────────────────────────────
        "rmse_ml": info["rmse_ml"],
        "velocity_rmse_mlps": info.get("velocity_rmse_mlps"),
        "retention_rmse_ml": info.get("retention_rmse_ml"),
        "retention_final_model_ml": info.get("retention_final_model_ml"),
        "retention_final_obs_ml": info.get("retention_final_obs_ml"),
        "retention_final_time_s": info.get("retention_final_time_s"),
        "paper_holdup_final_ml": info.get("paper_holdup_final_ml"),
        "water_balance_residual_ml": info.get("water_balance_residual_ml"),
        "energy_residual_fraction": info.get("energy_residual_fraction"),
        "clip_active_fraction": info.get("clip_active_fraction"),
        # ── 時間標記 ────────────────────────────────────────────────────
        "brew_time_s": float(info["sim_final"]["brew_time"]),
        "drain_time_s": float(info["sim_final"]["drain_time"]),   # 模型端診斷量，非觀測量
        "stop_flow_time_s": info.get("stop_flow_time_s"),
        # F12a：停流觀測算子（level = 影片液位運算子；q_threshold = 紀錄表目視最後一滴）
        "stop_operator": info.get("stop_operator"),
        "stop_flow_time_csv_s": info.get("stop_flow_time_csv_s"),
        "dripper_removed_time_s": info.get("dripper_removed_time_s"),
        "thermo_break_s": info.get("thermo_break_s"),
        "model_q_at_thermo_break_mlps": info.get("model_q_at_thermo_break_mlps"),
        "cup_stop_time_s": info.get("cup_stop_time_s"),
        "cup_stop_time_error_s": info.get("cup_stop_time_error_s"),
        "drain_time_error_s": info.get("cup_stop_time_error_s"),  # deprecated 別名
        "final_temp_read_time_s": info.get("final_temp_read_time_s"),
        "v_out_final_ml": float(info.get("model_v_out_ml", info["sim_final"]["v_out_ml"])[-1]),
        # ── 幾何 / 硬體 ─────────────────────────────────────────────────
        "h_bed_cm": info.get("h_bed_cm"),
        "rho_bulk_dry_g_ml": info.get("rho_bulk_dry_g_ml"),
        "axial_node_count": info.get("axial_node_count", info["sim_final"].get("axial_node_count")),
        # F2b 之後 `sat_rel_perm_residual` 的預設為 0（殘餘飽和已由 V_imm 顯式攜帶）；
        # 舊 summary 的 0.18 不可 reload（見 benchmark._load_measured_benchmark_state）。
        "sat_rel_perm_residual_fit": info.get("sat_rel_perm_residual_fit"),
        "sat_rel_perm_exp_fit": info.get("sat_rel_perm_exp_fit"),
        # ── 熱端 ────────────────────────────────────────────────────────
        "final_cup_temp_C": info.get("final_cup_temp_C"),
        "mixed_cup_temp_C": info.get("mixed_cup_temp_C"),
        "cup_temp_error_C": info.get("cup_temp_error_C"),
        # F10 熱時序診斷（影片版；不進 χ²）：模型 − 量測的 RMSE / 平均偏差 / 點數。
        "thermal_video_server_rmse_C": info.get("thermal_video_server_rmse_C"),
        "thermal_video_server_bias_C": info.get("thermal_video_server_bias_C"),
        "thermal_video_server_n": info.get("thermal_video_server_n"),
        "thermal_video_outflow_rmse_C": info.get("thermal_video_outflow_rmse_C"),
        "thermal_video_outflow_bias_C": info.get("thermal_video_outflow_bias_C"),
        "thermal_video_outflow_n": info.get("thermal_video_outflow_n"),
        "thermal_video_outflow_gated_rmse_C": info.get("thermal_video_outflow_gated_rmse_C"),
        "thermal_video_outflow_gated_bias_C": info.get("thermal_video_outflow_gated_bias_C"),
        "thermal_video_outflow_gated_n": info.get("thermal_video_outflow_gated_n"),
        # F11：熱時序進 χ²。chi2 分項、點數、V_immersion 與觀測窗設定、模型 − 量測偏差。
        "chi2_term_volume": info.get("chi2_term_volume"),
        "chi2_term_stop_time": info.get("chi2_term_stop_time"),
        "chi2_term_cup_temp": info.get("chi2_term_cup_temp"),
        "chi2_term_extracted_mass": info.get("chi2_term_extracted_mass"),
        "chi2_term_server_temp_series": info.get("chi2_term_server_temp_series"),
        "chi2_term_outflow_temp_series": info.get("chi2_term_outflow_temp_series"),
        "server_series_n": info.get("server_series_n"),
        "server_series_rmse_C": info.get("server_series_rmse_C"),
        "server_series_bias_C": info.get("server_series_bias_C"),
        "outflow_series_n": info.get("outflow_series_n"),
        "outflow_series_rmse_C": info.get("outflow_series_rmse_C"),
        "outflow_series_bias_C": info.get("outflow_series_bias_C"),
        "v_immersion_ml": info.get("v_immersion_ml"),
        "server_series_min_v_ml": info.get("server_series_min_v_ml"),
        "server_series_qc": info.get("server_series_qc"),
        "server_energy_closure_c_eff_ml": info.get("server_energy_closure_c_eff_ml"),
        "outflow_temp_series_in_chi2": info.get("outflow_temp_series_in_chi2"),
        "server_series_excluded": info.get("server_series_excluded"),
        "outflow_series_excluded": info.get("outflow_series_excluded"),
        "thermal_fit_param_names": info.get("thermal_fit_param_names"),
        "vessel_equivalent_ml": info.get("vessel_equivalent_ml"),
        "fit_server_cooling": info.get("fit_server_cooling"),
        "server_cooling_lambda_fit": info.get("server_cooling_lambda_fit"),
        "lambda_server_fixed": info.get("lambda_server_fixed"),
        "server_cooling_lambda_ci_lo": _ci("lambda_server_ambient", "lo"),
        "server_cooling_lambda_ci_hi": _ci("lambda_server_ambient", "hi"),
        "fit_liquid_dripper_lambda": info.get("fit_liquid_dripper_lambda"),
        "lambda_liquid_dripper_fit": info.get("lambda_liquid_dripper_fit"),
        "lambda_liquid_dripper_prior": info.get("lambda_liquid_dripper_prior"),
        # ── preferential flow ───────────────────────────────────────────
        "fit_preferential_flow": info.get("fit_preferential_flow"),
        "pref_flow_coeff_fit": info.get("pref_flow_coeff_fit"),
        "pref_flow_open_rate_fit": info.get("pref_flow_open_rate_fit"),
        "pref_flow_tau_decay_fit": info.get("pref_flow_tau_decay_fit"),
        "pref_flow_open_rate_fixed": info.get("pref_flow_open_rate_fixed"),
        "pref_flow_tau_decay_fixed": info.get("pref_flow_tau_decay_fixed"),
        # ── 萃取（stage 7，由 EXTRACTION_FIT_PARAMS 驅動）───────────────
        "fit_extraction": info.get("fit_extraction"),
        "stage7_skipped_reason": info.get("stage7_skipped_reason", ""),
        "extraction_fit_param_names": ";".join(n for n, *_ in EXTRACTION_FIT_PARAMS),
        # repr = 完整 float 精度（round-trip 精確）。Why：舊版 `.10e` 截斷使 reload 的
        # tau_tort 與 fit 相差 ~2e-12（相對），在 rtol 1e-7 的 χ² 路徑噪音下即造成
        # canonical fit/reload χ² 9.970 vs 10.040（EXP-20260928-F12c 追查）。
        "extraction_fit_param_values": ";".join(
            repr(float(v)) for v in (info.get("extraction_fit_params", {}) or {}).values()
        ),
        "k_ext_slow_coef_fit": info.get("k_ext_slow_coef_fit"),
        "k_ext_fast_coef_fit": info.get("k_ext_fast_coef_fit"),
        "max_EY_fit": info.get("max_EY_fit"),
        "final_tds_gl_obs": info.get("final_tds_gl_obs"),
        "final_tds_gl_pred": info.get("final_tds_gl_pred"),
        "tds_pred_measured_denominator": info.get("tds_pred_measured_denominator"),
        "tds_error_gl": info.get("tds_error_gl"),
        "m_extracted_pred_g": info.get("m_extracted_pred_g"),
    }
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


def plot_flow_fit_comparison(
    info: dict,
    save_as: str = "kinu29_light_20g_flow_fit.png",
) -> None:
    """
    繪製實測 `V_out(t)` 與擬合模型的對照圖。

    What:
        上圖   — 累積注水 / 累積出液
        中圖   — 區間平均流出速度
        下圖   — 各量測點的體積殘差

    Why:
        現在的 loss 是多目標：不只要對總量，也要對節奏、停流時間與杯溫。
        圖也必須把這三種訊號同時展示出來。
    """
    _setup_style()

    sim = info["sim_final"]
    model_v_out = np.asarray(info.get("model_v_out_ml", sim["v_out_ml"]), dtype=float)
    model_q_out = np.asarray(info.get("model_q_out_mlps", sim["q_out_mlps"]), dtype=float)
    t_obs = np.asarray(info["t_obs_s"], dtype=float)
    v_in_obs = np.asarray(info["v_in_obs_ml"], dtype=float)
    v_out_obs = np.asarray(info["v_out_obs_ml"], dtype=float)
    fit_mask = np.asarray(info["fit_mask"], dtype=bool)
    q_obs_mlps = np.asarray(info.get("q_obs_mlps"), dtype=float)
    q_pred_obs_mlps = np.asarray(info.get("q_pred_obs_mlps"), dtype=float)
    stop_flow_time_s = float(info.get("stop_flow_time_s", sim["drain_time"]))
    bloom_end_s = float(info.get("bloom_end_s", np.nan))
    interp = interp1d(
        sim["t"], model_v_out, kind="linear",
        bounds_error=False, fill_value="extrapolate",
    )
    v_out_pred_obs = interp(t_obs)
    residual = v_out_pred_obs - v_out_obs

    fig, axes = plt.subplots(
        3, 1, figsize=(11.5, 10.2),
        gridspec_kw={"height_ratios": [3.2, 1.7, 1.5]},
    )
    pref_coeff = float(info.get("pref_flow_coeff_fit", 0.0))
    pref_txt = (f"pref {pref_coeff:.1e}" if info.get("fit_preferential_flow") else "pref off")
    # summary band 以 χ² 指標為主：V RMSE 只是診斷量，reduced χ² 與殘差白噪音
    # 檢定（DW）才是 benchmark gate 實際看的東西（F4 §4）。
    # `_summary_band` 會依欄數自動收縮間距（viz._BAND_TITLE_SPAN）；
    # pref / cup 這兩個次要資訊仍放下方註記框，不佔 band。
    # band 只列**本次擬合的自由度**（F6b）。`k_beta` 與 `tau_lag` 已凍結，
    # 把凍結值放在「Measured vs Fitted」的參數帶上會讓讀者以為它們是擬出來的；
    # 兩者改列在下方註記框並明確標 fixed。
    _summary_band(fig, "Measured vs Fitted", [
        ("k", f"{info['k_fit']:.2e} m^2"),
        ("Corey n", f"{info.get('sat_rel_perm_exp_fit', np.nan):.2f}"),
        ("tau_wet", f"{info.get('tau_wet_s_fit', np.nan):.1f} s"),
        ("reduced chi2", f"{info.get('reduced_chi2', np.nan):.2f}"),
        ("DW (r/σ)", f"{info.get('durbin_watson', np.nan):.2f}"),
        ("V RMSE", f"{info['rmse_ml']:.1f} mL"),
        ("ret RMSE", f"{info.get('retention_rmse_ml', np.nan):.1f} mL"),
    ])

    # F10：影片版有完整 1 s 序列；χ² 只用抽樣點（VIDEO_FIT_STRIDE_S），兩者都畫。
    t_full = np.asarray(info.get("t_obs_full_s", t_obs), dtype=float)
    has_full = t_full.size > t_obs.size
    v_in_plot = np.asarray(info.get("v_in_obs_full_ml", v_in_obs), dtype=float) if has_full else v_in_obs
    ax = axes[0]
    ax.plot(t_full if has_full else t_obs, v_in_plot, color=PALETTE["gold"], lw=2.4, ls="--",
            label="Measured poured volume")
    if has_full:
        v_full = np.asarray(info["v_out_obs_full_ml"], dtype=float)
        m_full = np.asarray(info["fit_mask_full"], dtype=bool)
        ax.plot(t_full, np.where(m_full, v_full, np.nan), color=PALETTE["orange"], lw=1.3, alpha=0.75,
                label="Measured drained volume (video, 1 s)")
        ax.plot(t_full, np.where(~m_full, v_full, np.nan), color=PALETTE["muted"], lw=1.3, ls=":",
                label="Level not visible (interpolated, not fitted)")
    ax.scatter(t_obs[fit_mask], v_out_obs[fit_mask], s=40, color=PALETTE["orange"],
               edgecolor="white", linewidth=0.8, zorder=4,
               label=(f"Fitted points (every {info.get('fit_stride_s'):g} s)" if has_full
                      else "Measured drained volume"))
    ax.scatter(t_obs[~fit_mask], v_out_obs[~fit_mask], s=40, color=PALETTE["muted"],
               edgecolor="white", linewidth=0.8, zorder=4, label="Held-out point")
    ax.plot(sim["t"], model_v_out, color=PALETTE["blue"], lw=2.6, label="Fitted model outflow")
    _style_ax(ax, "Cumulative volume trajectories", "Volume [mL]")
    if np.isfinite(bloom_end_s):
        ax.axvline(bloom_end_s, color=PALETTE["purple"], lw=1.0, ls="--")
        ax.text(bloom_end_s, ax.get_ylim()[1], " bloom end", color=PALETTE["purple"],
                fontsize=8.2, va="top", ha="left")
    ax.axvline(stop_flow_time_s, color=PALETTE["muted"], lw=1.0, ls=":")
    ax.text(stop_flow_time_s, ax.get_ylim()[1], " visual stop", color=PALETTE["muted"],
            fontsize=8.2, va="top", ha="left")
    ax.legend(loc="upper left", ncol=2, fontsize=9)
    ax.set_xlim(left=0.0)
    ax.set_ylim(bottom=0.0)

    ax = axes[1]
    t_mid = 0.5 * (t_obs[1:] + t_obs[:-1])
    interval_fit_mask = fit_mask[1:] & fit_mask[:-1]
    ax.plot(
        sim["t"], sim["q_out_mlps"],
        color=PALETTE["blue"], lw=1.2, alpha=0.28,
        label="Model instantaneous q_out",
    )
    ax.plot(
        t_mid, q_pred_obs_mlps,
        color=PALETTE["blue"], lw=2.4,
        label="Model interval mean q_out",
    )
    ax.scatter(t_mid[interval_fit_mask], q_obs_mlps[interval_fit_mask], s=38, color=PALETTE["teal"],
               edgecolor="white", linewidth=0.8, zorder=4, label="Observed interval mean q_out")
    ax.scatter(t_mid[~interval_fit_mask], q_obs_mlps[~interval_fit_mask], s=38, color=PALETTE["muted"],
               edgecolor="white", linewidth=0.8, zorder=4, label="Held-out interval")
    _style_ax(ax, "Interval outflow-rate comparison", "Flow Rate [mL/s]")
    if np.isfinite(bloom_end_s):
        ax.axvline(bloom_end_s, color=PALETTE["purple"], lw=1.0, ls="--")
    ax.axvline(stop_flow_time_s, color=PALETTE["muted"], lw=1.0, ls=":")
    ax.legend(loc="upper left", ncol=2, fontsize=8.8)
    ax.set_xlim(left=0.0)
    ax.set_ylim(bottom=0.0)

    ax = axes[2]
    colors = np.where(fit_mask, PALETTE["red"], PALETTE["muted"])
    ax.axhline(0.0, color=PALETTE["grid"], lw=1.2)
    sigma_v = MEASUREMENT_SIGMA["v_out_ml"]
    sigma_pts = np.asarray(info.get("sigma_v_obs_ml", np.full(t_obs.size, sigma_v)), dtype=float)
    ax.fill_between(t_obs, -sigma_pts, sigma_pts, step="mid", color=PALETTE["grid"], alpha=0.45)
    if has_full:
        res_full = (np.asarray(info["v_pred_obs_full_ml"], dtype=float)
                    - np.asarray(info["v_out_obs_full_ml"], dtype=float))
        ax.plot(t_full, np.where(np.asarray(info["fit_mask_full"], dtype=bool), res_full, np.nan),
                color=PALETTE["red"], lw=0.9, alpha=0.45, label="1 s residual (diagnostic)")
    ax.bar(t_obs, residual, width=4.8, color=colors, alpha=0.9)
    ax.plot(t_obs, residual, color=PALETTE["red"], lw=1.0, alpha=0.5)
    band_txt = ("±1σ = per-point level σ ⊕ q·σ_t" if has_full
                else f"±1σ = {sigma_v:.0f} mL ⊕ q·σ_t")
    _style_ax(ax, f"Residual time series at observed drained-volume points ({band_txt})",
              "Model - Measured [mL]")
    if np.isfinite(bloom_end_s):
        ax.axvline(bloom_end_s, color=PALETTE["purple"], lw=1.0, ls="--")
    ax.set_xlim(left=0.0)

    temp_txt = "Cup temp n/a"
    if info.get("final_cup_temp_C") is not None and info.get("mixed_cup_temp_C") is not None:
        temp_txt = (
            f"Cup temp {info['mixed_cup_temp_C']:.1f}°C"
            f" vs {info['final_cup_temp_C']:.1f}°C"
        )
    axes[2].text(
        0.995, 0.92,
        # 這個誤差是**杯中目視停流**的誤差，不是床層排乾時間的誤差（見 summary CSV 註解）
        f"Cup stop error {info.get('cup_stop_time_error_s', info.get('drain_time_error_s', np.nan)):+.2f} s\n{temp_txt}\n"
        f"lag-1 (r/σ) {info.get('residual_lag1', np.nan):+.2f} | runs z {info.get('runs_z', np.nan):+.2f}\n"
        f"Cup {model_v_out[-1]:.1f} mL | {pref_txt}\n"
        f"fixed: k_beta {info.get('k_beta_fit', np.nan):.0f} m^-3 (PSD prior)"
        f" | tau_lag {info.get('tau_lag_s', np.nan):.2f} s\n"
        f"data: {info.get('profile_source', 'log')} {info.get('video_id', '')}"
        f" | time base {info.get('time_base', '')}",
        transform=axes[2].transAxes,
        ha="right", va="top", fontsize=8.6, color=PALETTE["ink"],
        bbox=dict(boxstyle="round,pad=0.25", fc=PALETTE["panel"], ec=PALETTE["grid"], lw=0.8),
    )

    plt.tight_layout(rect=[0, 0, 1, 0.94])
    _save_fig(fig, save_as, f"流動擬合對照圖已儲存至 {save_as}")


def _sibling_summary_row(csv_path: str | Path) -> dict | None:
    """
    讀取與 `csv_path` **同目錄**的 calibrated summary（warm-start 用）。

    Why: 舊版硬編碼 `DEFAULT_MEASURED_FLOW_FIT_SUMMARY`（kinu29 4:11 的 canonical
         summary）作為所有 case 的 warm-start，於是 kinu27 / kinu28 的 multi-start
         有一個起點是別的 case 的解——實測 kinu27 與 kinu28 的 `k_fit` 位元相同，
         代表這兩個 case 根本沒有各自收斂，只是被同一個起點吸住（AUD）。
         改為只讀同目錄的 summary；找不到就不用這個起點。
    """
    case_dir = Path(csv_path).resolve().parent
    # 只認 flow-fit summary：同目錄還有 `*_psd_summary.csv` 與
    # `benchmark_suite_summary.csv`，後者也有 `k_fit` 欄，會被誤當 warm-start。
    # 短 stem `*_flow_fit_summary.csv` 優先，legacy `*_flow_fit_*_summary.csv` 作 fallback
    # （F6，2026-09-24：只留 legacy pattern 時短 stem 不會被 glob 命中，
    #   warm-start 起點會**靜默消失**——測試 `TestWarmStart` 抓到了這一點）。
    cands = sorted(case_dir.glob("*_flow_fit_summary.csv")) \
        + sorted(case_dir.glob("*_flow_fit_*_summary.csv"))
    for cand in cands:
        try:
            with cand.open(encoding="utf-8") as f:
                row = next(csv.DictReader(f), None)
        except (OSError, StopIteration):
            continue
        if row is not None and row.get("k_fit"):
            return row
    return None


# ── multi-start 設計（F6b）──────────────────────────────────────────────────
# What: stage 1/2 的三個 live 參數 (k, sat_rel_perm_exp, tau_wet_s) 上的 Latin
#       hypercube 起點數與亂數種子。
# Why:  F6 §4.4 實測同一個 case 的兩組起點分別收在 χ² 816.9 與 719.1（差 97.8，
#       ≈ 13.6 reduced χ² 單位），而各組**內部** spread 只有 ~2%。也就是說
#       χ² surface 至少有兩個明顯分離的 basin，3 個起點的「deterministic basin
#       選擇」承諾沒有兌現。改用固定 seed 的 LHS：起點在每個維度上分層均勻，
#       且完全可重現（換句話說，這不是「多跑幾次碰運氣」，是一個可重跑的設計）。
MULTI_START_LHS_N = 6
MULTI_START_SEED = 20260924
# LHS 取樣區間（k 與 sat_rel_perm_exp 走 log10、tau_wet 走線性）。
# 刻意**窄於** optimizer bounds：起點不需要覆蓋到邊界，覆蓋到邊界只會浪費
# 一個起點在必然被推回來的位置上。
MULTI_START_K_RANGE_M2 = (2.0e-11, 1.0e-9)
MULTI_START_TAU_WET_RANGE_S = (10.0, 60.0)


def _latin_hypercube_starts(n: int, seed: int) -> list[V60Params]:
    """
    在 (log k, log sat_rel_perm_exp, tau_wet_s) 上取 n 個 Latin hypercube 起點。

    What: 每個維度切成 n 個等寬層，各層取一個亂數點後獨立打亂配對。
    Why:  純隨機取樣在 n = 6 時很容易在某個維度上擠成一團；LHS 保證每個維度
          的邊際分布一定是分層均勻的，這正是我們要的「起點真的分散」。
          seed 固定 → 同一份程式碼永遠得到同一組起點，結果可重跑。
    """
    rng = np.random.default_rng(seed)
    strata = (np.arange(n) + rng.random(n)) / n          # shape (n,)
    axes = []
    for _ in range(3):
        axes.append(rng.permutation(strata))
    lk = np.log10(MULTI_START_K_RANGE_M2[0]) + axes[0] * (
        np.log10(MULTI_START_K_RANGE_M2[1]) - np.log10(MULTI_START_K_RANGE_M2[0]))
    ln = np.log10(SAT_REL_PERM_EXP_BOUNDS[0]) + axes[1] * (
        np.log10(SAT_REL_PERM_EXP_BOUNDS[1]) - np.log10(SAT_REL_PERM_EXP_BOUNDS[0]))
    tw = MULTI_START_TAU_WET_RANGE_S[0] + axes[2] * (
        MULTI_START_TAU_WET_RANGE_S[1] - MULTI_START_TAU_WET_RANGE_S[0])
    return [
        V60Params(k=float(10.0 ** lk[i]),
                  sat_rel_perm_exp=float(10.0 ** ln[i]),
                  tau_wet_s=float(tw[i]))
        for i in range(n)
    ]


# 子行程內把 BLAS / OpenMP 執行緒數限為 1。
# Why: N 個 worker 各自開滿核心數的 BLAS 執行緒會超訂 CPU。這些變數在 BLAS 載入時
#      才被讀取，而 spawn 子行程在執行 initializer 前就已 import numpy，所以必須在
#      子行程誕生前寫進父行程環境（子行程繼承），pool 結束後還原。
_BLAS_THREAD_ENV_VARS = (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
)


@contextlib.contextmanager
def _single_thread_blas_env():
    saved = {k: os.environ.get(k) for k in _BLAS_THREAD_ENV_VARS}
    os.environ.update({k: "1" for k in _BLAS_THREAD_ENV_VARS})
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _start_tau_wet_init(p_init: V60Params) -> float:
    return float(getattr(p_init, "tau_wet_s", TAU_WET_INIT_S) or TAU_WET_INIT_S)


def _fit_one_start(
    i: int,
    p_init: V60Params,
    csv_path: str | Path,
    fit_kwargs: dict,
    verbose: bool,
) -> dict:
    """
    What: multi-start 的單一起點擬合；串行與平行路徑共用。
    Why:  module-level 才能被 spawn 子行程 pickle；兩條路徑呼叫同一函式，
          保證每個起點的計算逐位元相同。
    """
    tau_wet_init = _start_tau_wet_init(p_init)
    p_fit, info = fit_k_kbeta_from_flow_profile(
        csv_path=csv_path,
        params_init=p_init,
        tau_wet_init_s=tau_wet_init,
        verbose=verbose,
        **fit_kwargs,
    )
    return {
        "start_idx": i,
        "k_init": float(p_init.k),
        "sat_rel_perm_exp_init": float(p_init.sat_rel_perm_exp),
        "tau_wet_init_s": tau_wet_init,
        "k_beta_init": float(p_init.k_beta),
        "k_fit": float(info["k_fit"]),
        "k_beta_fit": float(info["k_beta_fit"]),
        "sat_rel_perm_exp_fit": float(info["sat_rel_perm_exp_fit"]),
        "tau_wet_s_fit": float(info.get("tau_wet_s_fit", np.nan)),
        "tau_lag_fit": float(info["tau_lag_s"]),
        "rmse_ml": float(info["rmse_ml"]),
        "chi2": float(info["chi2"]),
        "reduced_chi2": float(info["reduced_chi2"]),
        "total_loss": float(info["chi2"]),
        "params_fit": p_fit,
        "info": info,
    }


def fit_with_multi_start(
    csv_path: str | Path,
    starts: list[V60Params] | None = None,
    fit_preferential_flow: bool = True,
    pref_open_rate_fixed: float = DEFAULT_PREF_FLOW_OPEN_RATE_FIXED,
    pref_tau_decay_fixed: float = DEFAULT_PREF_FLOW_TAU_DECAY_FIXED,
    compute_ci: bool = True,
    verbose: bool = True,
    max_workers: int | None = None,
) -> tuple[V60Params, dict]:
    """
    Multi-start wrapper：對 N 個起點各跑一次擬合，取最低 χ² 者為 canonical fit。

    平行化：起點彼此獨立，各起點在獨立 spawn 子行程中執行（worker 數預設
    `min(len(starts), os.cpu_count())`）。`max_workers=1` 在主行程串行執行、
    不開 pool。兩條路徑每個起點的計算完全相同，結果依起點 index 收集。

    What（F6b 起）：
        `MULTI_START_LHS_N` 個固定 seed 的 Latin hypercube 起點，覆蓋 stage 1/2
        的三個 live 參數 `(k, sat_rel_perm_exp, tau_wet_s)`；若同目錄有既有
        flow-fit summary，再追加一個 sibling warm-start。所有起點的 χ² 與參數
        都記進 `multi_start_results`。

    Why:
        F6 §4.4 顯示 3 個起點不足以定位 basin（兩組起點差 97.8 χ²，組內 spread
        只有 ~2%）。起點數提到 6 並改用分層取樣，是為了讓「χ² surface 有幾個
        basin」變成一個**可回答**的問題——如果 6 個 LHS 起點仍收到分離的 χ²，
        那就是模型的性質，要如實記錄，不是再加起點去掩蓋。
    """
    if starts is None:
        starts = _latin_hypercube_starts(MULTI_START_LHS_N, MULTI_START_SEED)
        last = _sibling_summary_row(csv_path)
        if last is not None:
            # sibling warm-start：只取 `k`，因為 `k_beta` 自 F6b 起凍結、
            # `tau_lag` 已退出 fit，舊 summary 的那兩欄不再是起點資訊。
            try:
                starts.append(V60Params(
                    k=float(last["k_fit"]),
                    sat_rel_perm_exp=float(
                        last.get("sat_rel_perm_exp_fit") or SAT_REL_PERM_EXP_INIT),
                    tau_wet_s=float(last.get("tau_wet_s_fit") or TAU_WET_INIT_S),
                ))
            except (TypeError, ValueError):
                pass

    fit_kwargs = dict(
        fit_preferential_flow=fit_preferential_flow,
        pref_open_rate_fixed=pref_open_rate_fixed,
        pref_tau_decay_fixed=pref_tau_decay_fixed,
        compute_ci=compute_ci,
    )
    n_workers = min(len(starts), os.cpu_count() or 1) if max_workers is None else int(max_workers)
    if n_workers < 1:
        raise ValueError(f"max_workers 必須 ≥ 1，收到 {max_workers}")

    if n_workers == 1:
        multi_results = []
        for i, p_init in enumerate(starts):
            if verbose:
                print(f"=== Multi-start fit {i+1}/{len(starts)} "
                      f"(k_init={p_init.k:.3e}, n_init={p_init.sat_rel_perm_exp:.3f}, "
                      f"tau_wet_init={_start_tau_wet_init(p_init):.1f}) ===")
            multi_results.append(_fit_one_start(i, p_init, csv_path, fit_kwargs, verbose))
    else:
        # 子行程以 verbose=False 執行：逐 stage 的 print 會在多行程間交錯；
        # stage timing 不受 verbose 影響，照常寫進各起點 info["stage_timings"]。
        if verbose:
            print(f"=== Multi-start: {len(starts)} starts on {n_workers} worker processes ===")
        by_idx: dict[int, dict] = {}
        with _single_thread_blas_env(), ProcessPoolExecutor(
            max_workers=n_workers, mp_context=mp.get_context("spawn"),
        ) as pool:
            futures = [
                pool.submit(_fit_one_start, i, p_init, csv_path, fit_kwargs, False)
                for i, p_init in enumerate(starts)
            ]
            for fut in as_completed(futures):
                r = fut.result()   # 子行程例外在此重拋，不吞錯
                by_idx[r["start_idx"]] = r
                if verbose:
                    print(f"  [done {len(by_idx)}/{len(starts)}] start {r['start_idx']}: "
                          f"chi2={r['chi2']:.4f}, k={r['k_fit']:.3e}, "
                          f"n={r['sat_rel_perm_exp_fit']:.3f}, tau_wet={r['tau_wet_s_fit']:.2f}, "
                          f"wall={r['info'].get('fit_wall_s', float('nan')):.0f}s")
        # 依起點 index 排序（非完成順序），使 winner 的 tie-break 與串行路徑相同。
        multi_results = [by_idx[i] for i in range(len(starts))]

    best = min(multi_results, key=lambda r: r["chi2"])
    if verbose:
        print("\n=== Multi-start summary ===")
        # 起點數直接印實際值：`starts` 可由呼叫端顯式傳入（測試/掃描會這樣做），
        # 這時「總數 − LHS 數」會是負的，印出來會誤導。
        print(f"  design: {len(multi_results)} starts"
              f" (LHS n={MULTI_START_LHS_N} seed={MULTI_START_SEED} + sibling warm-start)")
        for r in multi_results:
            tag = " <- winner" if r["start_idx"] == best["start_idx"] else ""
            print(f"  start {r['start_idx']}: k={r['k_fit']:.3e}, n={r['sat_rel_perm_exp_fit']:.3f}, "
                  f"tau_wet={r['tau_wet_s_fit']:.2f}, chi2={r['chi2']:.2f} "
                  f"(red {r['reduced_chi2']:.2f}){tag}")
        ks = [r["k_fit"] for r in multi_results]
        ns = [r["sat_rel_perm_exp_fit"] for r in multi_results]
        c2 = [r["chi2"] for r in multi_results]
        print(f"  k spread: {(max(ks)/min(ks)-1)*100:.1f}%, "
              f"sat_rel_perm_exp spread: {(max(ns)/min(ns)-1)*100:.1f}%")
        dof_best = int(best["info"].get("dof") or 1)
        print(f"  chi2 range: [{min(c2):.2f}, {max(c2):.2f}]  span {max(c2)-min(c2):.2f}"
              f"  (= {(max(c2)-min(c2))/max(dof_best, 1):.2f} reduced-chi2 units"
              f" at dof {dof_best})")

    best_info = best["info"]
    best_info["multi_start_results"] = [
        {k: v for k, v in r.items() if k not in ("params_fit", "info")}
        for r in multi_results
    ]
    best_info["multi_start_winner_idx"] = int(best["start_idx"])
    return best["params_fit"], best_info


def generate_measured_flow_fit_artifacts(
    csv_path: str | Path = DEFAULT_MEASURED_FLOW_CSV,
    plot_path: str | Path = DEFAULT_MEASURED_FLOW_FIT_PLOT,
    summary_path: str | Path = DEFAULT_MEASURED_FLOW_FIT_SUMMARY,
    fit_preferential_flow: bool = True,
    pref_open_rate_fixed: float = DEFAULT_PREF_FLOW_OPEN_RATE_FIXED,
    pref_tau_decay_fixed: float = DEFAULT_PREF_FLOW_TAU_DECAY_FIXED,
    use_multi_start: bool = True,
    verbose: bool = True,
) -> tuple[V60Params, dict]:
    """
    產生專案展示用的量測流動擬合產物（summary CSV + comparison plot）。

    What:
      1. 對量測 `V_in(t)` / `V_out(t)` 執行 `fit_k_kbeta_from_flow_profile`
         （或 `fit_with_multi_start` 若 `use_multi_start=True`）
      2. 將結果寫成 showcase 使用的 summary CSV
      3. 輸出三張展示圖：measured-vs-model 對照圖、殘差時序圖、保水對照圖
         （檔名由 `plot_path` 的短 stem 推導：`…_flow_fit{,_residuals,_retention}.png`）

    Why:
      展示頁的 lead figure 與校準摘要應和目前的正式擬合流程保持同一套參數，
      避免 code path、圖檔名稱與 README 各自漂移。
      殘差與保水兩張圖由同一次 fit 一併輸出（F6，2026-09-24）：它們是
      `README.md` 與 benchmark 公開的產物路徑，若要另外手動產生，文件
      公佈的「跑這一行就有」就是假的。
      `use_multi_start=True`（預設）以 3× 成本換取 deterministic basin 選擇
      （參見 `fit_with_multi_start` docstring）。
    """
    if use_multi_start:
        params_fit, info = fit_with_multi_start(
            csv_path=csv_path,
            fit_preferential_flow=fit_preferential_flow,
            pref_open_rate_fixed=pref_open_rate_fixed,
            pref_tau_decay_fixed=pref_tau_decay_fixed,
            verbose=verbose,
        )
    else:
        params_fit, info = fit_k_kbeta_from_flow_profile(
            csv_path=csv_path,
            fit_preferential_flow=fit_preferential_flow,
            pref_open_rate_fixed=pref_open_rate_fixed,
            pref_tau_decay_fixed=pref_tau_decay_fixed,
            verbose=verbose,
        )
    save_flow_fit_summary_csv(summary_path, info)
    plot_flow_fit_comparison(info, save_as=str(plot_path))
    base = str(plot_path)[:-4] if str(plot_path).endswith(".png") else str(plot_path)
    plot_fit_residuals(info, save_as=f"{base}_residuals.png")
    plot_retention_comparison(info, save_as=f"{base}_retention.png")
    if info.get("thermal_video_server_n"):
        plot_thermal_video_check(info, save_as=f"{base[:-len('_flow_fit')] if base.endswith('_flow_fit') else base}"
                                               "_thermal_video_check.png")
    return params_fit, info


def fit_measured_benchmark(
    csv_path: str | Path = DEFAULT_MEASURED_FLOW_CSV,
    plot_path: str | Path = DEFAULT_MEASURED_FLOW_FIT_PLOT,
    summary_path: str | Path = DEFAULT_MEASURED_FLOW_FIT_SUMMARY,
    fit_preferential_flow: bool = True,
    pref_open_rate_fixed: float = DEFAULT_PREF_FLOW_OPEN_RATE_FIXED,
    pref_tau_decay_fixed: float = DEFAULT_PREF_FLOW_TAU_DECAY_FIXED,
    verbose: bool = True,
) -> tuple[V60Params, dict]:
    """
    對專案的 measured benchmark case 執行正式校準並輸出展示產物。

    What:
        固定使用 `kinu29_light_20g_flow_profile.csv` 作為 benchmark case，
        跑 `k / k_beta / tau_lag + pref-flow(coeff) + server cooling` 校準，
        並輸出對應的 summary CSV 與 comparison plot。

    Why:
        需要一個穩定、可直接重跑的正式入口，讓 benchmark / regression /
        showcase 三者都引用同一套 calibrated artifact，而不是各自手動組命令。
    """
    return generate_measured_flow_fit_artifacts(
        csv_path=csv_path,
        plot_path=plot_path,
        summary_path=summary_path,
        fit_preferential_flow=fit_preferential_flow,
        pref_open_rate_fixed=pref_open_rate_fixed,
        pref_tau_decay_fixed=pref_tau_decay_fixed,
        verbose=verbose,
    )

# ─────────────────────────────────────────────────────────────────────────────
#  參數擬合（兩階段，利用因果解耦）
# ─────────────────────────────────────────────────────────────────────────────
def fit_brew_params(
    t_obs: np.ndarray,
    V_out_obs_ml: np.ndarray,
    TDS_final_gl: float,
    protocol: "PourProtocol",
    params_init: "V60Params | None" = None,
    verbose: bool = True,
) -> tuple["V60Params", dict]:
    """
    DEPRECATED 2026-05-02：legacy 兩階段參數擬合。

    What:
      Stage 1 — 從 V_out(t) 觀測序列擬合流體參數 (k, psi)。
      Stage 2 — 從最終杯中 TDS 擬合萃取參數 (k_ext_coef, max_EY)。

    Status:
      此函式仍動 `k_ext_coef`（已被棄用），但主 ODE 路徑改用 `k_ext_fast_coef` /
      `k_ext_slow_coef`，因此本流程的 stage 2 已**對 EY/TDS 預測無實質作用**。
      新程式碼應使用 `fit_k_kbeta_from_flow_profile`（含 measured Brix → TDS
      stage 7 + multi-start wrapper）。

    Why kept:
      AGENTS.md §2「能刪掉的程式碼才是好設計」與 backward compat 之間取折衷：
      留作 historical reference 與 reduced-order single-pool baseline 對照工具。
      下次萃取線整理時將與 `k_ext_coef` 一同移除。
    """
    import warnings
    warnings.warn(
        "fit_brew_params is deprecated since 2026-05-02; use "
        "fit_k_kbeta_from_flow_profile (multi-start + stage 7 TDS fit) instead. "
        "This legacy two-stage fit operates on the deprecated single-pool "
        "k_ext_coef which is no longer in the main extraction ODE path.",
        DeprecationWarning,
        stacklevel=2,
    )
    if params_init is None:
        params_init = V60Params()

    # ── Stage 1：擬合流體參數 k, psi ──────────────────────────────────────────
    # 目標：最小化 V_out(t) 的均方誤差（log 空間優化，因參數跨越多個數量級）
    def _flow_residual(log_x: np.ndarray) -> float:
        k_try   = 10.0 ** log_x[0]
        psi_try = 10.0 ** log_x[1]
        p = dataclasses.replace(params_init, k=k_try, psi=psi_try)
        res = simulate_brew(p, protocol, t_end=float(t_obs[-1]) + 10, n_eval=500)
        # 內插模型預測值至觀測時間點
        interp = interp1d(res["t"], res["v_out_ml"], kind="linear",
                          bounds_error=False, fill_value="extrapolate")
        V_pred = interp(t_obs)
        rmse = float(np.sqrt(np.mean((V_pred - V_out_obs_ml) ** 2)))
        return rmse

    x0_s1 = np.array([np.log10(params_init.k), np.log10(params_init.psi)])
    bounds_s1 = [(-13, -9), (-8, -4)]  # log10 範圍

    if verbose:
        print("  [Stage 1] 擬合流體參數 k, psi...")

    res1 = minimize(
        _flow_residual, x0_s1,
        method="Nelder-Mead",
        bounds=bounds_s1,
        options={"xatol": 0.01, "fatol": 0.1, "maxiter": 300, "disp": False},
    )
    k_fit   = 10.0 ** res1.x[0]
    psi_fit = 10.0 ** res1.x[1]

    params_s1 = dataclasses.replace(params_init, k=k_fit, psi=psi_fit)

    if verbose:
        print(f"    k   = {k_fit:.3e}  (初始: {params_init.k:.3e})")
        print(f"    psi = {psi_fit:.3e}  (初始: {params_init.psi:.3e})")
        print(f"    V_out RMSE = {res1.fun:.2f} mL")

    # ── Stage 2：擬合萃取參數 k_ext_coef, max_EY ─────────────────────────────
    # 固定流體參數，只擬合化學參數使 TDS_final 吻合
    def _chem_residual(log_x: np.ndarray) -> float:
        kext_try   = 10.0 ** log_x[0]
        max_ey_try = float(np.clip(10.0 ** log_x[1], 0.10, 0.40))
        p = dataclasses.replace(params_s1, k_ext_coef=kext_try, max_EY=max_ey_try)
        res = simulate_brew(p, protocol, t_end=float(t_obs[-1]) + 30, n_eval=800)
        # 使用模擬結束時的 TDS（最後非零點）
        tds_arr = res["TDS_gl"]
        last_valid = tds_arr[tds_arr > 0]
        tds_pred = float(last_valid[-1]) if len(last_valid) > 0 else 0.0
        return (tds_pred - TDS_final_gl) ** 2

    x0_s2 = np.array([
        np.log10(params_s1.k_ext_coef),
        np.log10(params_s1.max_EY),
    ])
    bounds_s2 = [(-9, -5), (-1.3, -0.4)]  # log10(k_ext_coef), log10(max_EY)

    if verbose:
        print(f"  [Stage 2] 擬合萃取參數，目標 TDS = {TDS_final_gl:.2f} g/L...")

    res2 = minimize(
        _chem_residual, x0_s2,
        method="Nelder-Mead",
        options={"xatol": 0.01, "fatol": 1e-4, "maxiter": 300, "disp": False},
    )
    kext_fit   = 10.0 ** res2.x[0]
    max_ey_fit = float(np.clip(10.0 ** res2.x[1], 0.10, 0.40))

    params_fit = dataclasses.replace(params_s1, k_ext_coef=kext_fit, max_EY=max_ey_fit)

    # 驗證：用最終參數跑一次完整模擬
    res_final = simulate_brew(params_fit, protocol, t_end=float(t_obs[-1]) + 30, n_eval=800)
    tds_arr   = res_final["TDS_gl"]
    last_valid = tds_arr[tds_arr > 0]
    tds_pred   = float(last_valid[-1]) if len(last_valid) > 0 else 0.0
    ey_pred    = float(res_final["EY_cup_pct"][-1])

    if verbose:
        print(f"    k_ext_coef = {kext_fit:.3e}  (初始: {params_init.k_ext_coef:.3e})")
        print(f"    max_EY     = {max_ey_fit:.3f}  (初始: {params_init.max_EY:.3f})")
        print(f"    TDS 預測   = {tds_pred:.2f} g/L  (目標: {TDS_final_gl:.2f} g/L)")
        print(f"    EY 預測    = {ey_pred:.1f}%")

    info = {
        "stage1_res": res1,
        "stage2_res": res2,
        "TDS_pred":   tds_pred,
        "EY_pred":    ey_pred,
        "sim_final":  res_final,
    }
    return params_fit, info


def demo_fitting(protocol: "PourProtocol | None" = None) -> None:
    """
    參數擬合示範：用「真實」參數產生合成資料，加入量測雜訊，
    再從雜訊資料反推參數，驗證兩階段擬合的恢復能力。

    Why:
      在沒有真實量測數據時，合成資料驗證是判斷擬合演算法
      是否可識別（identifiable）的必要步驟。
    """
    if protocol is None:
        protocol = PourProtocol.standard_v60()

    # ── 真實參數（產生合成觀測）────────────────────────────────────────────────
    true_params = V60Params(
        k          = 1.5e-11,
        psi        = 3.0e-6,
        k_ext_coef = 0.8e-7,
        max_EY     = 0.24,
    )

    print("\n=== 參數擬合示範（合成資料驗證）===")
    print(f"  真實參數：k={true_params.k:.2e}, psi={true_params.psi:.2e}, "
          f"k_ext={true_params.k_ext_coef:.2e}, max_EY={true_params.max_EY:.2f}")

    # ── 產生「量測」資料（含白雜訊）──────────────────────────────────────────
    res_true = simulate_brew(true_params, protocol, t_end=180, n_eval=1000)
    rng = np.random.default_rng(42)

    # 每 15 s 取一個 V_out 樣本，加 ±2 mL 量測雜訊
    t_sample = np.arange(30, 301, 15, dtype=float)
    interp_Vout = interp1d(res_true["t"], res_true["v_out_ml"],
                           kind="linear", bounds_error=False, fill_value="extrapolate")
    V_out_noisy = interp_Vout(t_sample) + rng.normal(0, 2.0, len(t_sample))
    V_out_noisy = np.clip(V_out_noisy, 0, None)

    # 最終 TDS 加 ±0.2 g/L 雜訊
    tds_arr   = res_true["TDS_gl"]
    last_valid = tds_arr[tds_arr > 0]
    TDS_true   = float(last_valid[-1]) if len(last_valid) > 0 else 10.0
    TDS_noisy  = TDS_true + rng.normal(0, 0.2)

    print(f"  合成 TDS（含雜訊）：{TDS_noisy:.2f} g/L  (真實: {TDS_true:.2f} g/L)")

    # ── 從雜訊資料擬合（初始猜測用預設值）───────────────────────────────────
    init_params = V60Params()  # 故意從錯誤起點出發
    print(f"  初始猜測：k={init_params.k:.2e}, psi={init_params.psi:.2e}, "
          f"k_ext={init_params.k_ext_coef:.2e}, max_EY={init_params.max_EY:.2f}")

    fitted_params, info = fit_brew_params(
        t_obs        = t_sample,
        V_out_obs_ml = V_out_noisy,
        TDS_final_gl = TDS_noisy,
        protocol     = protocol,
        params_init  = init_params,
        verbose      = True,
    )

    # ── 結果比較 ──────────────────────────────────────────────────────────────
    print("\n  ┌────────────────────────────────────────────────┐")
    print("  │              參數恢復結果對比                    │")
    print("  ├──────────────┬──────────────┬──────────────────┤")
    print("  │   參數       │   真實值     │   擬合值         │")
    print("  ├──────────────┼──────────────┼──────────────────┤")
    pairs = [
        ("k  [m²]",      true_params.k,          fitted_params.k,          "{:.2e}"),
        ("psi [m²/s]",   true_params.psi,         fitted_params.psi,        "{:.2e}"),
        ("k_ext [m³/s]", true_params.k_ext_coef,  fitted_params.k_ext_coef, "{:.2e}"),
        ("max_EY",       true_params.max_EY,       fitted_params.max_EY,     "{:.3f}"),
    ]
    for name, true_val, fit_val, fmt in pairs:
        err_pct = abs(fit_val - true_val) / abs(true_val) * 100
        print(f"  │ {name:<12} │ {fmt.format(true_val):>12} │ {fmt.format(fit_val):>12}  ({err_pct:5.1f}%) │")
    print("  └──────────────┴──────────────┴──────────────────┘")

    # ── 視覺化：擬合曲線 vs 合成觀測 vs 真實曲線 ─────────────────────────────
    res_fit = info["sim_final"]
    # 延伸真實模擬至相同時長
    res_true_ext = simulate_brew(true_params, protocol, t_end=330, n_eval=800)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("Parameter Fitting Demo — Synthetic Data Validation", fontsize=12)

    # 左圖：V_out(t)
    ax = axes[0]
    ax.plot(res_true_ext["t"], res_true_ext["v_out_ml"],
            "k-", lw=2, label="True simulation")
    ax.scatter(t_sample, V_out_noisy,
               color="red", s=30, zorder=5, label="Noisy observations")
    ax.plot(res_fit["t"], res_fit["v_out_ml"],
            "b--", lw=2, label="Fitted model")
    ax.set_xlabel("Time [s]")
    ax.set_ylabel("Cumulative Outflow [mL]")
    ax.set_title("Flow Fit (Stage 1)")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    # 右圖：TDS(t)
    ax = axes[1]
    ax.plot(res_true_ext["t"], res_true_ext["TDS_gl"],
            "k-", lw=2, label="True TDS")
    ax.axhline(TDS_noisy, color="red", ls=":", lw=1.5, label=f"Measured TDS = {TDS_noisy:.2f} g/L")
    ax.plot(res_fit["t"], res_fit["TDS_gl"],
            "b--", lw=2, label="Fitted TDS")
    ax.set_xlabel("Time [s]")
    ax.set_ylabel("TDS [g/L]")
    ax.set_title("TDS Fit (Stage 2)")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    plt.tight_layout()
    fname = "v60_fitting_demo.png"
    plt.savefig(fname, dpi=150, bbox_inches="tight")
    print(f"\n擬合示範圖已儲存至 {fname}")
