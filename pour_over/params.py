"""
pour_over.params — V60 可調參數與主模型資料結構
==============================================

What:
    封裝 V60 主模型的 closure、可標定參數與核心資料結構。

Why:
    固定的幾何/量測輸入已拆到 `constant.py`；
    這個模組應主要承載真正需要推理、掃描或標定的模型旋鈕，
    並保留 RoastProfile 與 PourProtocol 這兩個高階組態入口。

包含：
    - RoastProfile：烘焙度物理係數集（frozen dataclass）
    - V60Params：可調 closure 與模型狀態（繼承固定輸入）
    - PourProtocol：分段注水計畫（dataclass）
"""

import csv
import dataclasses
import math
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from dataclasses import dataclass, field
from typing import ClassVar, List, Tuple

from .calibration_state import CLOG_INDEX_REF, KBETA_PRIOR_REF, KBETA_PRIOR_SIGMA_DEX
from .constant import (
    CP_WATER, G, H_MIN, K_B, R_GAS, RHO,
    SOLUTE_RADIUS_FAST_M, SOLUTE_RADIUS_SLOW_M,
    V60Constant,
)
from .psd import DEFAULT_SHELL_THICKNESS_MM, shell_accessibility_fraction_mm

# ── 萃取端可擬參數規格（F3 → F4 介面）────────────────────────────────────────
# What: `(參數名, 變換, 下界, 上界, prior 中心, prior σ [dex])`。
#       `fitting.EXTRACTION_FIT_PARAMS` 應由此推導出前四欄，
#       prior 中心與 σ 供 χ² 的 log-space regularization 使用。
# Why:  新萃取閉合只留一個 live closure 參數 `tau_tort`（顆粒內有效曲折度）。
#       它有可證偽的物理區間：植物組織 / 咖啡細胞壁的文獻曲折度落在 2–10，
#       因此 prior 中心取 5、σ = 0.35 dex（≈ ±2.2× 的 1σ 帶，涵蓋 2–11）。
#       bounds [1, 100] 的下界 1 是硬物理上界（D_eff 不可能超過自由水 D），
#       上界 100 刻意放寬到不合理區，讓「擬合把它推到 100」成為一個
#       **可觀測的失敗訊號**，而不是被 bound 悄悄夾住。
#       作用範圍（2026-10-07）：`tau_tort` 只作用於 slow pool（`lambda_slow_bins`）；
#       fast pool 用自由溶液 D，不受 prior 影響。shell 30 μm、max_EY 0.30 下四案
#       TDS 命中值落在 3.3–7.6，與 prior 中心同量級（EXP-20261007-EXTRACTION-CLOSURE-REWRITE）。
EXTRACTION_FIT_SPEC: list[tuple[str, str, float, float, float, float]] = [
    ("tau_tort", "log10", 1.0, 100.0, 5.0, 0.35),
]

# 驅動頭 softplus 的平滑寬度 [m]。
# What: `bed_drive_components` 以 softplus 取代 max(0, ·)，eps 決定轉折的圓滑程度。
# Why:  舊版把 eps 綁成 `h_cap * 0.25`，使「出口毛細截止高度」同時決定數值平滑尺度——
#       調 h_cap（Class C closure）會連帶改變積分器看到的剛性，兩件事被混成一個旋鈕。
#       改為獨立數值常數後，h_cap 只描述物理門檻，eps 只描述數值平滑。
HEAD_SOFTPLUS_EPS_M = 5e-4

# 水量分流 smooth_min 的平滑尺度 [m³/s]（= 1e-3 mL/s）
# Why: 遠小於任何有意義的流量，只在「動力學上限」與「供給上限」交叉處磨平折角。
RATE_SMOOTH_EPS = 1e-9

# 水池之間「瞬時」轉移的連續化時間尺度 [s]
# What: 任何一個水池的抽取率一律 ≤ 存量 / TRANSFER_TAU_S。
# Why:  這不是可調 closure，而是質量守恆本身的連續化寫法：
#       「水池排出速率不可能超過現有存量 / 一個瞬間」。τ → 0 是精確約束，
#       但會讓方程剛性爆掉；取 1.0 s（≈ 2× max_step）是 RK45 能平滑解析的最小值。
#       它同時界定兩件事：
#         (a) 積水滲入床內 mobile 孔隙（濕床滲入是 Darcy 尺度，不是毛細 τ_cap 尺度）
#         (b) 自由水 / mobile 水在存量見底時的出流上限
#       因此不需要任何 clamp，出流在水耗盡時自然歸零。
TRANSFER_TAU_S = 1.0


def smooth_min(a, b, eps: float):
    """
    可微的 min(a, b)。

    What: min(a,b) = 0.5*(a + b - |a - b|)，把 |·| 換成 sqrt((a-b)^2 + eps^2)。
    Why:  水量守恆需要「動力學上限」與「供給上限」同時成立，但硬 min() 會在兩者
          交叉處製造斜率不連續，讓 RK45 反覆縮步。eps 遠離交叉處無影響，
          僅在交叉鄰域把折角磨圓。
    """
    a = _as_float(a)
    b = _as_float(b)
    diff = a - b
    return 0.5 * (a + b - np.sqrt(diff * diff + eps * eps))


# ── 純量快速路徑的共用夾值工具（RHS 常數開銷）─────────────────────────────────
# What: 下列 closure 同時服務 ODE RHS（Python 純量）與後處理（整條時序陣列）。
# Why:  RHS 每次呼叫 ~50 次純量 np.clip / np.asarray，每次 ~1–2 µs 的 ufunc 派送
#       開銷佔 RHS 時間兩成以上。純量走 `min(max(x, lo), hi)` 與 np.clip 逐位元相同
#       （皆為單純比較；x 為 NaN 時兩者都回傳 NaN），陣列仍交給 numpy。
def _as_float(x):
    """Python / NumPy 浮點純量原樣回傳；其餘轉成 float ndarray（等同 `np.asarray(x, dtype=float)`）。"""
    return x if isinstance(x, float) else np.asarray(x, dtype=float)


def _clip(x, lo, hi):
    """與 `np.clip(x, lo, hi)` 數值相同；浮點純量回傳 Python 純量，陣列回傳 ndarray。"""
    if isinstance(x, float):
        return min(max(x, lo), hi)
    return np.clip(x, lo, hi)


def _floor(x, lo):
    """與 `np.maximum(x, lo)` 數值相同（x 為 NaN 時回傳 NaN）；浮點純量回傳 Python 純量。"""
    if isinstance(x, float):
        return max(x, lo)
    return np.maximum(x, lo)


def _scalar_out(x):
    """`float(x) if np.ndim(x) == 0 else x`；Python float 直接回傳，省去 np.ndim 派送。"""
    if type(x) is float:
        return x
    return float(x) if np.ndim(x) == 0 else x


def _finite_or_zero(x) -> float:
    """純量版 `float(np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0))`。"""
    x = float(x)
    return x if math.isfinite(x) else 0.0


def _polyval(coeffs, x):
    """
    What: Horner 求值，與 `np.polyval(coeffs, x)` 逐位元相同（同為 `y = y·x + c`、y 由 0 起算）。
    Why:  `np.polyval` 每次都 asarray 係數並配置 zeros_like，純量呼叫的開銷遠大於 4 次乘加。
    """
    y = 0.0
    for c in coeffs:
        y = y * x + c
    return y


def _setup_cjk_font() -> None:
    """優先選用系統中的 CJK 字型，否則退回英文 label。"""
    candidates = [
        "Heiti TC", "PingFang TC", "Apple LiGothic",
        "Noto Sans CJK TC", "Noto Sans TC",
        "Microsoft JhengHei",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.family"] = name
            return

_setup_cjk_font()


# ─────────────────────────────────────────────────────────────────────────────
#  烘焙度物理係數集
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RoastProfile:
    """
    烘焙度對應的化學與物理係數集（不可變）。

    What: 封裝「烘焙度」直接決定的參數差異，與研磨度 k 正交分離。
    Why:  烘焙改變豆子的細胞結構（max_EY = 可及溶質總量）、大分子溶解上限
          （C_sat_slow）、沖煮水溫慣例以及 CO₂ 含量（吸水率）。
          這些參數不應由使用者逐一調整，而應透過語意明確的工廠 for_roast() 管理。

    使用方式：
        p = V60Params.for_roast(RoastProfile.LIGHT)
        p = V60Params.for_roast(RoastProfile.DARK, k_target=1.5e-10)
    """
    name: str

    # ── 溶質可萃取性 ───────────────────────────────────────────────────────
    max_EY: float
    # 總可萃取溶質比例；淺焙與中焙 0.30（Moroney 2016、Liang 2021），深焙 0.32

    alpha_EY: float
    # k-M 聯動靈敏度；淺焙硬豆磨細效益有限（0.10），深焙較高（0.20）

    # ── 萃取動力學 ────────────────────────────────────────────────────────
    # F3（2026-09-24）移除 `k_ext_factor` / `Ea_slow` / `fast_fraction`：
    #   - `k_ext_factor` 是 deprecated 的 `k_ext_coef` 的倍率，該基底已不存在。
    #   - `Ea_slow`：溫度相依現由 Stokes-Einstein `D(T) = k_B T /(6π μ(T) r)` 完整
    #     描述，再疊 Arrhenius 等於把同一件事數兩次（AUD-3 溫度三重計數）。
    #   - `fast_fraction`：兩池的質量分配改由 measured PSD 的殼層可及性
    #     `shell_acc_i` 逐 bin 決定（見 `V60Params._set_extraction_bins`），
    #     不再有一個與 PSD 無關的全域比例旋鈕。
    #   烘焙度對萃取速率的影響改由 `max_EY`（可及溶質總量）與 `C_sat_slow`
    #   （大分子溶解上限）兩個仍有量測根據的量承擔。

    C_sat_slow: float
    # Slow 組分平衡濃度 [g/L]；深焙苦味物量大（100），淺焙少（60）

    brew_temp_K: float
    # 建議沖煮水溫 [K]；淺焙偏高、深焙偏低，中焙取中間值

    # ── 吸水特性（CO₂ 含量影響） ─────────────────────────────────────────
    absorb_dry_ratio: float
    # 零出液吸水率 [mL/g]；淺焙 CO₂ 多→孔隙被佔（0.4），深焙脫氣後（0.7）

    absorb_full_ratio: float
    # 完全飽和吸水率 [mL/g]；淺焙緻密（1.2），深焙疏鬆（1.7）

    # ── CO₂ 背壓（修正 [14]）────────────────────────────────────────────────
    co2_pressure_m: float
    # 悶蒸初始 CO₂ 背壓等效水頭 [m]；映射至 V60Params.h_gas_0
    # Why: 新鮮淺焙豆 CO₂ 殘留多（9mm），深焙脫氣快（4mm）
    #      決定 q_extract 在早期受到的額外反向阻力大小

    # ── 預設配置（class-level constants，型別宣告）────────────────────────
    LIGHT:  ClassVar["RoastProfile"]
    MEDIUM: ClassVar["RoastProfile"]
    DARK:   ClassVar["RoastProfile"]


RoastProfile.LIGHT = RoastProfile(
    name              = "light",
    max_EY            = 0.30,   # Moroney 2016：90 °C 可萃量 28–32%；Liang 2021 E_max 0.3
    alpha_EY          = 0.10,
    C_sat_slow        = 60.0,
    brew_temp_K       = 365.15,  # 92°C：淺焙結構緻密，常用較高水溫
    absorb_dry_ratio  = 0.40,
    absorb_full_ratio = 1.20,
    co2_pressure_m    = 0.009,   # 9mm：淺焙 CO₂ 多，逸散慢
)

RoastProfile.MEDIUM = RoastProfile(
    name              = "medium",
    max_EY            = 0.30,   # Gagné: 中焙手沖上限 ~30%（舊值 0.28 偏保守）
    alpha_EY          = 0.15,
    C_sat_slow        = 80.0,
    brew_temp_K       = 363.15,  # 90°C：中焙取淺/深焙之間的工程中值
    absorb_dry_ratio  = 0.50,
    absorb_full_ratio = 1.64,
    co2_pressure_m    = 0.001,   # 中焙保留小幅 CO₂ 背壓：較符合一般仍有新鮮度的現實狀況
)

RoastProfile.DARK = RoastProfile(
    name              = "dark",
    max_EY            = 0.32,   # Gagné: 深焙細胞壁破壞嚴重，上限 30–32%；取上界 0.32
    alpha_EY          = 0.20,
    C_sat_slow        = 100.0,
    brew_temp_K       = 361.15,  # 88°C：深焙細胞壁破裂、苦味易出，常用較低水溫
    absorb_dry_ratio  = 0.70,
    absorb_full_ratio = 1.70,
    co2_pressure_m    = 0.004,   # 4mm：深焙出油後 CO₂ 已大量散逸
)


# ─────────────────────────────────────────────────────────────────────────────
#  V60 物理參數
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class V60Params(V60Constant):
    """
    V60 濾杯的幾何與物理參數。

    What:
        封裝 V60 主模型真正需要調整、掃描或標定的 closure 參數。

    Why:
        可量測固定輸入已移到 `V60Constant`；
        這裡應只保留模型假設、reduced-order closure 與少量可標定旋鈕，
        讓 `params.py` 不再同時扮演量測資料容器與 fitting 參數倉庫。

    k 參考值（有效滲透率，重新校準使沖煮時間符合真實 V60 ~150s）：
        粗研磨 ≈ 2e-10 m²   中研磨 ≈ 6e-11 m²   細研磨 ≈ 1.5e-11 m²

    h_bed 與乾粉堆積密度（20g 咖啡，V60 半角 30°）：
        V_bed = (π/3) tan²θ h_bed³
        h_bed = 53 mm → V_bed ≈ 51.97 mL
        ρ_bulk,dry = dose / V_bed ≈ 20 / 51.97 ≈ 0.385 g/mL

    k_beta 估算：
        k_beta = 3e3 m⁻³ → 300mL 出液後 k 降至初值 50%

    V_absorb 估算（修正 [13]）：
        V_dry  = 0.5mL/g × 20g = 10mL（CO₂ 修正後零出液門檻）
        V_full = 1.3mL/g × 20g = 26mL（完全飽和，正常出液）
    """
    # 粉層物理
    k: float = 6e-11            # 初始有效滲透率 k0 [m²]（校準至 ~150s 沖煮時間）

    # 旁路
    psi: float = 2.0e-4         # 旁路係數 Ψ [m²/s]
    # 校準更新：原值使標準配方旁路幾乎為零，不符一般現實 V60；
    # 提高兩個數量級後，中研磨旁路回到 ~1-2%，細研磨也不再過度 choke

    # ── 修正 [3] 細粉堵塞 ─────────────────────────────────────────────────────
    k_beta: float = 3e3         # 堵塞係數 β [m⁻³]；k(V) = k0/(1+β·V_out)

    throat_clog_char_vol: float = 25e-6
    # 喉道堵塞特徵體積 [m³]；前段少量出液就能佔據最狹窄孔喉，之後趨於飽和

    throat_clog_gain: float = 1.0
    # 喉道堵塞增益；用 PSD 推出的 throat index 當基底，再乘這個總體增益

    # ── 旁路衰減 ──────────────────────────────────────────────────────────────
    psi_beta: float = 1e3
    # 旁路衰減係數 [m⁻³]；Ψ_eff(V) = Ψ0/(1+psi_beta·V_out)
    # Why: 細粉同樣會沉積在濾紙邊緣，降低肋骨旁路滲透率
    #      psi_beta < k_beta（旁路堵塞比粉層慢，因為流速較低）

    bypass_onset_head: float = 0.003
    # 自由水柱高於粉床頂部後，旁路開始明顯啟動的門檻 [m]
    # Why: 低水位仍近似無旁路，但不把啟動點壓到只剩最高水位末端才出現

    bypass_onset_width: float = 0.008
    # 旁路啟動 sigmoid 的過渡寬度 [m]；控制「低水位近零、高水位漸進打開」

    # ── bloom 後濕床重排（代數版，混合型）────────────────────────────────────
    wetbed_rev_gain: float = 1.2
    # 可逆濕床壓實增益；高孔隙流速 + 高自由水柱時暫時降低 k_eff

    wetbed_rev_u_half: float = 0.0045
    # 可逆壓實的半飽和孔隙流速 [m/s]

    wetbed_rev_h_half: float = 0.010
    # 可逆壓實的半飽和自由水柱高度 [m]

    wetbed_irr_gain: float = 0.22
    # bloom 後注水造成的即時附加沉積強度；量級刻意小於可逆項。
    # FROZEN（2026-04-30）：identifiability scan 顯示此參數在 [0.7×, 1.3×]
    # 範圍 Δloss span 僅 0.36（純平 ridge），不應作為 fitting 自由度。
    # 預設 0.22 為當前 kinu29 light 20 g baseline 的工作值；除非更換 PSD/
    # dose/dripper 顯著破壞 baseline，否則不應改動。

    wetbed_irr_qin_ref: float = 6.0e-6
    # bloom 後注水擾動參考流量 [m³/s]（≈ 6 mL/s）

    wetbed_irr_u_ref: float = 0.012
    # bloom 後注水擾動參考孔隙流速 [m/s]

    # ── 注水脈衝記憶寬度 ──────────────────────────────────────────────────────
    # χ 結構態（wetbed_struct_*）在 P0/P1 重構中已併入 f_irr / throat_relief，
    # 完整移除（identifiability log 顯示 gain × rate 為平 ridge）。
    # `wetbed_impact_tau` 仍保留：用於 `pour_start_impact` 與 `throat_relief_factor`、
    # `q_preferential` 的脈衝寬度。
    wetbed_impact_tau: float = 2.0
    # 注水起始沖擊的記憶寬度 [s]

    sat_flow_relax_tau: float = 2.0
    # bloom 結束後，流動方程使用的等效飽和度鬆弛時間 [s]
    # Why: 避免 sat_flow 在 bloom_end 發生硬切，同時保留「後段視作已成濕床」的工程近似

    sat_rel_perm_residual: float = 0.0
    # Corey 相對滲透率的殘餘飽和度門檻，作用在 **mobile 飽和度 S_mob** 上。
    # Why 從 0.18 改為 0：殘餘（毛細保水）水量自 F2b 起是顯式狀態 `V_imm`，
    #      而 `S_mob = V_mob / (φ·V_bed − V_imm)` 的分母已經把 immobile 佔用的
    #      孔隙扣掉。此時再留一個非零 s_r 等於把同一份保水水量記兩次，
    #      會在 drawdown 段提前把 kr 壓到 0。s_r 現在是結構性的 0，不該再當 fit DOF。

    sat_rel_perm_exp: float = 3.0
    # Corey 型相對滲透率指數；控制 `kr(sat)` 在接近飽和前的打開速度

    # ── bloom 後偏流快路徑（雙路徑水力）──────────────────────────────────────
    pref_flow_coeff: float = 0.0
    # 快路徑導通係數 [m²/s]；預設 0 維持相容性，設為 >0 才啟用第二條過床支路

    pref_flow_open_rate: float = 0.0
    # 快路徑打開速率 [1/s]；由每一注起始的中心沖擊建立偏流通道

    pref_flow_qin_half: float = 4.5e-6
    # 快路徑打開的半飽和注水流量 [m³/s]（約 4.5 mL/s）

    pref_flow_tau_decay: float = 5.0
    # 快路徑衰減時間尺度 [s]；代表中心通道在注水後迅速重新閉合

    throat_relief_gain: float = 0.58
    # 每一注開始的中心沖擊可暫時移除多少 throat 額外阻塞（0~1）

    absorb_dry_ratio: float = 0.5
    # 零出液吸水率 [mL/g]；V_dry = dose_g × absorb_dry_ratio
    # Why（修正 [13]）：新鮮豆 CO₂ 仍殘留於微孔，有效吸水起點僅 ~0.5mL/g
    #      舊值 1.0mL/g 高估「悶蒸零出液」時長（Rao & Fuller 2018 實測中值 0.4–0.6）

    absorb_full_ratio: float = 1.64
    # 完全飽和吸水率 [mL/g]；V_full = dose_g × absorb_full_ratio
    # Why（校準更新）：中研磨 V60 要滿足 LRR≈2.2 時，1.3mL/g 偏低；
    #      提高至 1.64mL/g 後，標準 1:17 配方的 LRR 會落在 ~2.2。
    #      深焙/脫氣豆可再調高至 ~1.7mL/g 以上。

    # ── TDS 萃取動力學 ─────────────────────────────────────────────────────────
    phi: float = 0.4
    # 粉層孔隙率（porosity）；決定滯留水量 V_liquid = φ·V_bed
    # 參考：緊密堆積粉粒 φ ≈ 0.35–0.45

    axial_nodes: int = 2
    # 粉床軸向液相節點數；2 代表上/下兩層串接 CSTR，用最小狀態量保留軸向濃度梯度

    C_sat: float = 150.0
    # 平衡濃度 [g/L]；粉層液體能達到的萃取上限濃度
    # 推算：典型 EY_max≈28%，20g粉 → 5.6g 溶質，V_liquid≈15mL → 373 g/L
    # 但實際平衡受細胞壁阻力限制，取 150 g/L 作為有效 C_sat

    max_EY: float = 0.30
    # 可及溶質總量佔粉重的比例 [-]（Class D：凍結為 roast prior，不進 fitting）
    # What: 決定初始固相溶質量 M_sol_0 = dose_g × max_EY [g]，並逐 bin 依
    #       volume_fraction × shell_accessibility 分配到 fast / slow 兩池。
    # Why:  Moroney et al. (2016) 回報 90 °C 下同一支豆可萃量 28–32%（粗到細），
    #       Liang et al. (2021) 浸泡實驗取 E_max = 0.3、量得平衡萃取 K·E_max ≈ 0.215
    #       且與烘焙度幾乎無關。本模型沒有吸附平衡，兩池都可萃乾，因此 max_EY
    #       對應的是 E_max 而非 K·E_max；淺焙舊值 0.22 是後者
    #       （EXP-20261007-EXTRACTION-CLOSURE-REWRITE）。
    #       這是一個**有物理上限**的量：`max_EY > 1` 沒有意義，> 0.32 已超過
    #       文獻上限。舊 stage 7 把它擬到 0.3725 並與凍結的 `fast_fraction`
    #       完全簡併（AUD-3），等於用一個超物理的可萃取總量吸收萃取速率
    #       closure 的結構誤差。現在它由 `RoastProfile` 給定後凍結，
    #       唯一的 live 萃取參數是 `tau_tort`。

    tau_tort: float = 5.0
    # 咖啡顆粒內部的有效曲折度 τ_tort [-]（Class C：**本閉合唯一的 live 參數**）
    # What: D_eff,slow = D_slow(T) / τ_tort，只作用於 slow pool（未破壁核心）。
    #       它把「完整細胞壁 + 孔隙曲折 + 未溶解基質阻礙」一次收成一個無因次阻力；
    #       fast pool（破壁層）以自由溶液 D 釋放，不受它影響。
    # Why:  自由水中的 Stokes-Einstein D 是擴散的物理上界；多孔生物基質的
    #       有效擴散係數一定比它小，比值即 τ_tort（嚴格說是 τ²/ε_p，此處
    #       以單一有效值表示）。植物組織與咖啡細胞壁的文獻曲折度落在 2–10，
    #       因此這個參數**有可證偽的物理區間**——若擬合把它推到 100，
    #       代表閉合結構仍有問題，而不是「再調一點就好」。
    #       fitting 應在 log 空間搜尋（見模組常數 `EXTRACTION_FIT_SPEC`）。

    # ── 修正 [6] 熱力學 ────────────────────────────────────────────────────────
    lambda_cool: float = 3.7e-4
    # Newton 冷卻係數 λ [1/s]
    # 估算：典型手沖冷卻 ~1.5°C/min，ΔT_0 = 68°C → λ ≈ 1.5/(60×68) ≈ 3.7e-4
    # FROZEN（2026-04-30）：thermal identifiability scan 顯示此 λ 在 [0.7×, 1.3×]
    # 範圍 cup ΔT swing 僅 0.06 °C（純平 ridge）；保留為預設值，不進入 fitting。

    lambda_liquid_dripper: float = 0.0
    # DEPRECATED（expand 期）：液體與濾杯間的等效熱交換係數 [1/s]
    # What: 舊式集總係數，直接寫在液體節點的 dT/dt 上，與濕潤面積、液量都無關。
    # Why 棄用: fit 值 0.0496 /s 換算成界面熱通量後隱含 U ≈ 1044 W/m²K，
    #      遠高於「濕濾紙 + 陶瓷」串聯的物理上界（U ∈ [120, 550]，名目 194）。
    #      成因是係數被迫同時吸收「面積隨水位變化」與「液體熱容隨注水變化」兩件事。
    #      改由 `U_liquid_dripper_W_m2K` × `wetted_area(h)` 表達。
    # 相容策略（expand → migrate → contract）：`U_liquid_dripper_W_m2K` 為 None/0 時，
    #      模型退回本欄的舊行為並發出 DeprecationWarning；待 fitting 改 fit U 後移除。

    U_liquid_dripper_W_m2K: float | None = 194.0
    # 液體 ⇄ 濾杯的界面總熱傳係數 [W/(m²·K)]
    # What: 熱流 = U · A_wet(h) · (T_liquid − T_dripper)，A_wet 為錐面濕潤側面積。
    # Why:  把「界面材料性質」與「幾何」分離後，係數才有可辯護的物理區間。
    #       串聯估計：濕濾紙 (~0.2 mm, λ≈0.6 W/mK) + 陶瓷內側熱阻 + 接觸熱阻
    #       → U ∈ [120, 550] W/m²K，名目 194。fitting 應在此區間內標定。
    #       設為 None 或 0 → 退回 `lambda_liquid_dripper` 舊路徑（DeprecationWarning）。

    lambda_dripper_ambient: float = 0.0
    # 濾杯對環境自然對流冷卻係數 [1/s]
    # Why: 使用者傾向忽略濾紙，改由濾杯本體與空氣自然對流承擔額外散熱
    # FROZEN（2026-04-30）：thermal identifiability scan 顯示此 λ 在 [0.7×, 1.3×]
    # 範圍 cup ΔT swing 僅 0.12 °C（弱可識別）；保留為量測 baseline (0.004)。

    lambda_server_ambient: float = 0.0
    # 分享壺 / 杯中混合液對環境自然對流冷卻係數 [1/s]
    # Why: 床內與濾杯熱節點只能描述 cone 內冷卻；最後飲用溫度還需壺端散熱
    # FIT（2026-04-30）：identifiability medium（cup ΔT swing 0.52 °C），
    # 與 `lambda_liquid_dripper` 沿對角線存在 mild ridge（Δloss span ~0.16），
    # sequential fit (stage 5 → stage 6) 可同時校準兩者。

    alpha_C_sat: float = 0.003
    # C_sat 溫度係數 [1/K]；C_sat(T) = C_sat_ref·(1+α·(T-T_ref))
    # Why: 溶解度為溫度正函數（吸熱）；0.3%/K 對應典型有機物測量值
    #      使 83°C 萃取天花板低於 99°C，復現冷萃化學差異

    # ── 兩池溶解度上限（萃取驅動力的 cutoff）───────────────────────────────
    # F3（2026-09-24）：`fast_fraction` 與 `Ea_fast / Ea_slow` 已移除。
    #   - 兩池的質量分配改由 measured PSD 的殼層可及性逐 bin 決定。
    #   - 溫度相依只保留兩條：D_x(T)（Stokes-Einstein，控速率）與
    #     C_sat,x(T)（控平衡上限）。Arrhenius 是第三條，與 D(T) 重複。
    C_sat_fast: float = 220.0
    # Fast 組分平衡濃度 [g/L]；活性物質分子量小，溶解度較高

    C_sat_slow: float = 80.0
    # Slow 組分平衡濃度 [g/L]；大分子苦味物質溶解度低

    alpha_C_fast: float = 0.0015
    # Fast C_sat 溫度係數 [1/K]；小分子，對 T 較不靈敏

    alpha_C_slow: float = 0.006
    # Slow C_sat 溫度係數 [1/K]；苦味跳變：高溫大幅提升苦味溶解上限

    # ── k–M 聯動（The k-M Linkage）─────────────────────────────────────────
    k_ref: float = 6e-11
    # 中研磨參考滲透率 [m²]；聯動公式以此為基準
    # Why: k 是研磨度的流體力學代理變數（k ∝ d²，Kozeny-Carman）
    #      改變 k 即代表改變粒徑 d ∝ k^(1/2)，同步牽動 max_EY

    alpha_EY: float = 0.15
    # 可及溶質冪次指數：max_EY(k) = max_EY_ref × (k_ref/k)^alpha_EY
    # Why: 磨細 → 更多細胞壁破裂 → 更多可萃取溶質
    #      alpha_EY > 0：k↓（研磨越細）→ max_EY↑
    # 校準：粗(5e-11)→細(5e-12) EY 約 22→30%，alpha≈0.12–0.18（取 0.15）
    # 警告：超過 alpha=0.3 會使模型在細研磨端 EY > 100%（物理不合理）

    # F3（2026-09-24）移除 `alpha_ext`（配合 `k_ext_coef` 一同消失）、
    # `k_diff_ratio` / `Q_half`（Hill flow_factor）、`k_ext_fast_coef` /
    # `k_ext_slow_coef`（Noyes-Whitney base rate）。
    #   - Hill flow_factor：`k_diff_ratio = 0.1` 宣稱靜置時傳質降到 1/10，
    #     但球體的 Sherwood 數在 Re → 0 仍有下限 Sh = 2（純傳導），
    #     不存在 10× 的抑制。且 AUD-3 證明 (k_diff_ratio, Q_half) 在單一
    #     TDS 觀測下完全不可辨識。
    #   - `k_ext_*_coef` / `nw_eta_*`：速率常數現在由幾何（δ_i、R_core,i）與
    #     D(T)/τ_tort 直接算出，沒有「效率因子」可以反推。

    # ── 修正 [16] Darcy 毛細驅動飽和（Capillary-driven imbibition）────────────
    tau_cap_ref: float = 10.0
    # 毛細驅動飽和特徵時間 [s]，以 T_ref=93°C 為錨點
    # Why: 乾燥粉床在 Darcy 毛細壓力驅動下自主潤濕；物理公式：
    #      κ(T) ∝ γ(T)/μ(T)（Darcy 毛細通量，Gagné 圖實驗驗證）
    #      dsat/dt|cap = (1-sat) / τ_cap(T)；τ_cap(T) = τ_cap_ref / κ_ratio(T)
    #      τ_cap_ref=10s → 93°C 時純毛細驅動 9s 內達到 ~59% 飽和
    #      高溫（93°C）比低溫（20°C）快 2.8×，復現「高溫水入粉快」的物理現象
    #      注：此項與液壓填充（Q_in/V_absorb）疊加，不是取代

    tau_wet_s: float = 40.0
    # 床層潤濕狀態 w 的建立時間常數 [s]（Class C，本 slice 唯一新增的 closure 參數）
    # What: dw/dt = (1 − w)/τ_wet，w ∈ [0,1] 表示「粉床已建立保水能力的比例」。
    #       w 同時是 **顆粒吸水容量** `V_full·w` 與 **毛細保水容量** `φ·V_bed·f_retain·w`
    #       的上限係數。
    # Why:  量測（kinu29 4:11, retained_mass_g）給出兩個互斥的硬事實：
    #         t = 30 s 總保水僅 14.6 g（< φ·V_bed = 20.8 mL，更 ≪ V_full + φV_bed = 44.8）
    #         t = 142 s 總保水 52.1 g（> 44.8 mL）
    #       亦即剛潤濕的乾床會被重力排乾，保水能力是「隨潤濕逐漸建立」的時序量，
    #       不是常數 hold-up。物理來源：光焙、含 CO₂ 的乾粉初期疏水，
    #       水要先驅出微孔 CO₂、纖維溶脹後，毛細保水與顆粒吸收才建立得起來。
    #       τ_wet 由 retained_mass_g 的時序直接標定（見 F2b 報告 §3），
    #       不是用來吸收 V_out(t) 誤差的自由旋鈕。

    # F3（2026-09-24）移除 `beta_access`：pool 內部的驅動力衰減不再用
    #   `C_eff = C_sat·(M/M₀)^β` 這個 constant-area Noyes-Whitney 寫法表達。
    #   新閉合是一階釋放 `dM/dt = −λ·w·(1 − C/C_sat)·M`：驅動力的 M 相依
    #   已經由 `·M` 本身攜帶（Crank 首項的線性衰減），再乘一次 (M/M₀)^β
    #   等於把同一個衰減數兩次。

    # ── 修正 [8] 顆粒溶脹（Kozeny-Carman）──────────────────────────────────
    delta_phi: float = 0.02
    # 飽和時孔隙率最大降幅 Δφ；φ(sat) = φ₀ - Δφ·sat
    # Why: 咖啡纖維吸水後膨脹（Swelling），粒子體積約增加 3–5%
    #      等效孔隙率：φ₀=0.40 → 0.38（Δφ≈0.02）
    #      Kozeny-Carman：k ∝ φ³/(1-φ)²，k 在全飽和時降低約 16%
    #      解耦兩種機制：細粉遷移（k_beta·V_out）vs 溶脹（delta_phi·sat）
    #      意義：篩掉細粉後流速仍會變慢 → 這部分由 delta_phi 解釋，k_beta 僅代表細粉
    #      校準備注：原 k=2e-11 已含隱性溶脹效應；若加入本項可能需上調 k_0

    delta_phi_pressure: float = 0.012
    # 壓差造成的額外孔隙率降幅；隨自由水頭增大而上升，排水後可逆恢復

    fine_radius_ratio: float = 0.12
    # 細粉代表半徑相對 D10 的比例；供拖曳力診斷使用

    pore_radius_ratio: float = 0.2
    # 代表性孔喉半徑相對顆粒特徵徑（Sauter d32，退回 D10）的比例
    # What: r_pore = pore_radius_ratio × d_char；供 Young-Laplace 保水頭 `h_cap_bed` 使用。
    # Why:  隨機堆積球床的孔喉尺度約為顆粒徑的 0.15–0.25（Carman/Mayer-Stowe 量級），
    #       取中值 0.2。此值決定「床層能否被重力排乾」，不是自由擬合旋鈕：
    #       整個 [0.15, 0.25] 區間在 h_bed = 5.3 cm 下都給出 h_cap_bed > h_bed，
    #       結論（S_r = 1，濕床不自排）對此比例不敏感。

    # ── 修正 [9] 毛細管壓門檻（滴濾模式）──────────────────────────────────
    h_cap: float = 0.003

    # ── 修正 [14] CO₂ 背壓（Gas-trapping，新鮮豆悶蒸阻力）─────────────────
    h_gas_0: float = 0.001
    # CO₂ 背壓初始等效水頭 [m]
    # Why: 新鮮豆子（烘焙 7 天內）悶蒸時 CO₂ 分壓 0.5–1.5 bar 對向下達西流施加反向阻力。
    #      等效於水頭修正：h_eff = h - h_cap - h_gas(t)
    #      h_gas(t) = h_gas_0 × exp(−t / τ_CO2)，隨 CO₂ 逸散指數衰減。
    #      此項解釋「新鮮豆水位高但流速慢」的 Gas-trapping 現象。
    #      預設中研磨基準保留 1mm 小幅背壓：對一般仍有新鮮度的豆況更合理；
    #      新鮮豆/淺焙再透過 RoastProfile 額外拉高

    tau_co2: float = 35.0
    # CO₂ 逸散時間常數 [s]
    # Why: t = τ → h_gas 降至初值 37%；t = 3τ ≈ 105s → 降至 5%（可忽略）
    #      Cameron et al. (2020) 建議 35–45s；取 35s 復現「第二注水位居高不下」現象
    #      舊值 25s 使排氣過快（第二注 t=45s 時 h_gas 已衰至 28%），阻力表現不足
    # 毛細管壓等效水位門檻 [m]（3mm ≈ 29 Pa）
    # 校準說明：原 5mm 使末段流量過早趨零，導致沖煮時間嚴重高估。
    # 真實 V60 在最後 3-5mm 水位仍有明顯滴流，3mm 更符合實際觀測。
    # Why: 當水頭壓力 ρgh < P_c 時，Poiseuille 流無法維持，轉入「滴濾」模式
    #      對應 V60 肋骨縫隙寬度 ~2–3mm 的毛細管壓（P_c ≈ 2σ/w ≈ 50–100 Pa）
    #      驅動水頭修正為 h_eff = max(0, h-h_cap)，h < h_cap 時流量驟降至零
    #      物理後果：粉層底部殘留少量高濃度液體，永遠不會被計入杯測 EY
    #      （這是真實「可量測 EY < 理論萃取率」的一個重要來源）

    # ── 顆粒幾何 / PSD（新增：粒徑、殼層、碎形）──────────────────────────────
    eta_porosity: float = 3.0
    # 空隙率-滲透率指數：k ≈ f_s·D10²·φ^η；典型多孔介質常見值 ~3

    f_sp: float = 0.015
    # 粉床形狀/壓實經驗係數；以中研磨 D10 對應 k≈6e-11 m² 為校準錨點

    particle_d_min: float = 40e-9
    # 最小粒徑下限 [m]；供 measured PSD 缺值時的數值安全夾限

    shell_thickness: float = DEFAULT_SHELL_THICKNESS_MM * 1e-3
    # 可萃取外層（破壁層）厚度 [m]（Class D；數值與出處見 `psd.DEFAULT_SHELL_THICKNESS_MM`）
    # What: 研磨造成細胞壁破裂的深度尺度。它同時決定兩件事：
    #       (1) fast pool 的質量分率 shell_acc_i = 1 − (1 − δ_i/R_i)³
    #       (2) fast pool 的擴散長度 δ_i = min(shell_thickness, R_i)
    # Why:  同一個厚度必須同時定義「有多少質量」與「要走多遠」，否則兩者
    #       可以各自被調整去補償對方。舊實作對 L_fast 另外加了
    #       `max(0.25·shell_thickness, ...)` 的絕對 floor，使多數 bin 的
    #       L_fast 全等（AUD-3），等於把 bin-resolved 幾何抹平成常數。
    #
    # F3（2026-09-24）移除 `nu_p_fast` / `nu_p_slow`：舊式 `D = ν_p·k_B·T`
    #   的固定 mobility 等價於「D 與黏度無關」，而水在 92 → 75 °C 之間
    #   μ 上升 39%，真實 D 應下降約 34%——方向相反。改用 Stokes-Einstein
    #   `D_x(T) = k_B T /(6π μ(T) r_x)`，分子尺度 r_x 由 `constant.py` 的
    #   `SOLUTE_RADIUS_FAST_M` / `SOLUTE_RADIUS_SLOW_M` 提供（Class B）。

    def cone_bed_volume_m3(self, h_bed_m: float | None = None) -> float:
        """
        計算 V60 圓錐粉床的幾何體積。

        What: 回傳半角 `half_angle_deg`、高度 `h_bed_m` 對應的理想圓錐體積。
        Why:  粉床體積是乾粉堆積密度、孔隙體積與吸水量推導的共同基準；
              將公式集中成 helper，避免幾何關係在各處重寫。
        """
        h = self.h_bed if h_bed_m is None else float(h_bed_m)
        return (np.pi / 3.0) * self._tan2 * h**3

    def dry_bulk_density_g_ml(self, dose_g: float | None = None, h_bed_m: float | None = None) -> float:
        """
        由粉量與粉床幾何回推乾粉堆積密度。

        What: 使用 `ρ_bulk,dry = dose / V_bed`，回傳單位為 g/mL。
        Why:  這是可由量測直接決定的幾何量，不應交給 optimizer 吸收其他水力誤差。
        """
        dose = self.dose_g if dose_g is None else float(dose_g)
        volume_ml = self.cone_bed_volume_m3(h_bed_m) * 1.0e6
        if volume_ml <= 0:
            raise ValueError("粉床體積必須為正值，才能回推乾粉堆積密度")
        return dose / volume_ml

    def solid_water_equivalent_ml(self, mass_g: float, cp_j_gk: float) -> float:
        """
        將固體熱容換算成等效水體積。

        What: 回傳與指定固體具有相同熱容的水體積 [mL]。
        Why:  擬合與熱量帳以水當量最直覺；分享壺、濾杯與粉體都可用同一語言比較。
        """
        mass = max(float(mass_g), 0.0)
        cp = max(float(cp_j_gk), 0.0)
        return mass * cp / 4.18

    def _quantile_from_bins_csv(self, rows: list[dict], prob: float, weight_key: str = "num_fraction") -> float:
        """
        由分桶資料內插分位數直徑。

        What: 假設 bin 內均勻分布，依累積 fraction 反推指定分位數對應直徑 [mm]。
        Why:  bins 已保存 number/volume fraction；直接由 bins 取 D10 比再回退到碎形假設更合理。
        """
        rows_sorted = sorted(rows, key=lambda r: float(r["d_lo_mm"]))
        total = sum(max(float(r[weight_key]), 0.0) for r in rows_sorted)
        if total <= 0:
            raise ValueError("PSD bins 的權重總和必須為正，才能計算分位數")

        target = float(np.clip(prob, 0.0, 1.0)) * total
        cumulative = 0.0
        for row in rows_sorted:
            weight = max(float(row[weight_key]), 0.0)
            d_lo = float(row["d_lo_mm"])
            d_hi = float(row["d_hi_mm"])
            next_cumulative = cumulative + weight
            if target <= next_cumulative or row is rows_sorted[-1]:
                if weight <= 1e-12:
                    return d_hi
                frac = np.clip((target - cumulative) / weight, 0.0, 1.0)
                return d_lo + frac * (d_hi - d_lo)
            cumulative = next_cumulative
        return float(rows_sorted[-1]["d_hi_mm"])

    #: `_load_psd_bin_rows` 必須存在的欄位；缺欄代表 bins CSV 是舊格式。
    REQUIRED_PSD_BIN_COLUMNS: ClassVar[tuple[str, ...]] = (
        "d_lo_mm", "d_hi_mm", "d_mid_mm", "num_fraction", "volume_fraction",
        "diameter_eq_mean_mm", "diameter_eq_median_mm", "aspect_ratio_mean",
        "surface_to_volume_mm_inv_mean", "surface_to_volume_mm_inv_vol_weighted",
    )

    def _load_psd_bin_rows(self, bins_csv_path: str | Path, diameter_scale: float = 1.0) -> list[dict]:
        """
        載入並（必要時）縮放 multi-bin PSD rows。

        What: 讀入 bins CSV，把所有長度相關欄位按 `diameter_scale` 同步縮放，
              並依縮放後的直徑重算 shell accessibility 欄位。
        Why:  PSD 的絕對尺度由 bins CSV 決定；`diameter_scale` 只在顯式做研磨度
              sweep 時 ≠ 1。shell 欄是直徑的非線性函數，縮放直徑卻沿用 CSV 內的
              舊 shell 值會讓幾何自相矛盾，因此改為與 `pour_over.psd` 共用同一個
              解析函式重算。
        """
        path = Path(bins_csv_path)
        scale = max(float(diameter_scale), 1e-9)
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            missing = [c for c in self.REQUIRED_PSD_BIN_COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(
                    f"PSD bins CSV 缺少欄位 {missing}：{path}；"
                    "請以 `uv run python -m pour_over.psd --raw ... --out-bins ...` 重新產生"
                )
            rows_raw = [{k: float(v) for k, v in row.items()} for row in reader]
        if not rows_raw:
            raise ValueError(f"空的 PSD bins CSV：{path}")

        shell_mm = self.shell_thickness * 1e3
        rows_scaled: list[dict] = []
        for row in sorted(rows_raw, key=lambda r: r["d_lo_mm"]):
            scaled = dict(row)
            for key in ("d_lo_mm", "d_hi_mm", "d_mid_mm", "diameter_eq_mean_mm", "diameter_eq_median_mm"):
                scaled[key] = row[key] * scale
            for key in ("surface_to_volume_mm_inv_mean", "surface_to_volume_mm_inv_vol_weighted"):
                scaled[key] = row[key] / scale
            shell_acc = shell_accessibility_fraction_mm(scaled["diameter_eq_mean_mm"], shell_mm)
            scaled["shell_accessibility_mean"] = shell_acc
            scaled["shell_accessibility_volume_weighted"] = shell_acc
            rows_scaled.append(scaled)
        return rows_scaled

    def throat_diameter_from_d32(self, d32_mm: float) -> float:
        """
        由 Sauter 平均粒徑推估床層孔喉特徵直徑 [mm]。

        What: `d_throat = 0.2 · d32 · sqrt(φ / (1 − φ))`。
        Why:  Kozeny 型的水力半徑 r_h = φ/((1−φ)·a_s)，對球形床 a_s = 6/d32，
              故 d_throat ∝ d32·φ/(1−φ)。這裡取其在常見 φ ≈ 0.4–0.5 附近的
              sqrt 形式並配 0.2 的幾何前因子，讓孔喉尺寸隨 PSD 自身移動，
              而不是寫死一個與粒徑無關的 0.45 mm 門檻。
              前因子 0.2 未獨立標定，只保證 d_throat 落在 fines bin 尺度。
        """
        phi = float(np.clip(self.phi, 1e-6, 1.0 - 1e-6))
        return 0.2 * max(float(d32_mm), 1e-9) * float(np.sqrt(phi / (1.0 - phi)))

    def _particle_stats_from_bins_csv(self, bins_csv_path: str | Path, diameter_scale: float = 1.0) -> dict:
        """
        由 multi-bin PSD CSV 計算粒子子模型統計。

        What:
          1. 由 bins 整合 Sauter d32、比表面積、殼層可及性與有效擴散路徑
          2. 以 d32 推得的孔喉尺度計算 throat / deposition 堵塞指數
          3. 另附 number-based D10/D50/D90 供診斷（resolution-bounded）

        Why:
          有實測 PSD 時這些量不該再由理想碎形近似。尺度錨點使用 d32 而非 D10：
          d32 由粗端主導、對影像偵測下限不敏感，而 number-based D10 完全被
          偵測下限鉗制（整數像素格點 artifact）。
        """
        rows_sorted = self._load_psd_bin_rows(bins_csv_path, diameter_scale=diameter_scale)
        vol_total = sum(max(r["volume_fraction"], 0.0) for r in rows_sorted)
        if vol_total <= 0:
            raise ValueError(f"PSD bins CSV 的 volume_fraction 總和為 0：{bins_csv_path}")
        num_total = sum(max(r["num_fraction"], 0.0) for r in rows_sorted)
        if num_total <= 0:
            raise ValueError(f"PSD bins CSV 的 num_fraction 總和為 0：{bins_csv_path}")

        # 第一趟：比表面積 → Sauter d32 → 孔喉尺度。
        # a_s = Σ(vol_frac · (S/V)_vol_weighted) = 6/d32，故 d32 可直接反推。
        surface_area_mm_inv = sum(
            (max(r["volume_fraction"], 0.0) / vol_total) * r["surface_to_volume_mm_inv_vol_weighted"]
            for r in rows_sorted
        )
        d32_mm = 6.0 / max(surface_area_mm_inv, 1e-12)
        d_throat_mm = self.throat_diameter_from_d32(d32_mm)

        aspect_mean = sum(max(r["num_fraction"], 0.0) * r["aspect_ratio_mean"] for r in rows_sorted) / num_total
        roundness_mean = sum(max(r["num_fraction"], 0.0) * r["roundness_mean"] for r in rows_sorted) / num_total
        span_num = (
            self._quantile_from_bins_csv(rows_sorted, 0.90, "num_fraction")
            - self._quantile_from_bins_csv(rows_sorted, 0.10, "num_fraction")
        ) / max(self._quantile_from_bins_csv(rows_sorted, 0.50, "num_fraction"), 1e-12)

        surface_area_fast_mm_inv = 0.0
        shell_fraction_vol = 0.0
        diffusion_path_fast_mm = 0.0
        diffusion_path_slow_mm = 0.0
        shell_weight_total = 0.0
        throat_clog_index = 0.0
        deposition_clog_index = 0.0
        fast_reactive_index = 0.0
        slow_reactive_index = 0.0
        fine_num_total = 0.0
        fine_diameter_acc_mm = 0.0
        for row in rows_sorted:
            vol_w = max(row["volume_fraction"], 0.0) / vol_total
            num_w = max(row["num_fraction"], 0.0) / num_total
            d_mean = max(row["diameter_eq_mean_mm"], 1e-9)
            sv_mm_inv = row["surface_to_volume_mm_inv_vol_weighted"]
            shell_acc = shell_accessibility_fraction_mm(d_mean, self.shell_thickness * 1e3)
            core_ratio = max(1.0 - shell_acc, 0.0) ** (1.0 / 3.0)
            core_radius_mm = 0.5 * d_mean * core_ratio
            shell_depth_mm = min(self.shell_thickness * 1e3, 0.5 * d_mean)
            shell_mid_mm = max(0.5 * shell_depth_mm, 1e-9)
            # ROUNDNESS ≡ 1/aspect_ratio（raw CSV 恆等式），故舊式 (aspect/roundness)^0.35
            # 恆等於 aspect^0.70；直接寫成 aspect^0.70，避免看起來像兩個獨立形狀輸入。
            # 0.70 為未獨立標定的形狀指數。
            irregularity = max(row["aspect_ratio_mean"], 1.0) ** 0.70
            # 堵塞機率的飽和形式：顆粒遠小於孔喉時接近 1，遠大於孔喉時 ∝ d_throat/d。
            # 取代舊的 min(0.45/d, 2.0) —— 那是與 PSD 無關的 magic number，且在
            # 粗端沒有正確的漸近行為。
            clog_kernel = 1.0 / (1.0 + d_mean / max(d_throat_mm, 1e-12))
            surface_area_fast_mm_inv += vol_w * sv_mm_inv * shell_acc
            shell_fraction_vol += vol_w * shell_acc
            diffusion_path_fast_mm += vol_w * shell_acc * shell_mid_mm
            diffusion_path_slow_mm += vol_w * max(1.0 - shell_acc, 0.0) * max(core_radius_mm, shell_mid_mm)
            shell_weight_total += vol_w * shell_acc
            throat_clog_index += num_w * irregularity * clog_kernel
            deposition_clog_index += vol_w * irregularity * clog_kernel
            fast_reactive_index += vol_w * sv_mm_inv * shell_acc
            slow_reactive_index += vol_w * sv_mm_inv * max(1.0 - shell_acc, 0.0)
            if d_mean < 0.50:
                fine_num_total += num_w
                fine_diameter_acc_mm += num_w * d_mean

        D10_mm = self._quantile_from_bins_csv(rows_sorted, 0.10, "num_fraction")
        D50_mm = self._quantile_from_bins_csv(rows_sorted, 0.50, "num_fraction")
        D90_mm = self._quantile_from_bins_csv(rows_sorted, 0.90, "num_fraction")
        Dv50_mm = self._quantile_from_bins_csv(rows_sorted, 0.50, "volume_fraction")
        fines_num_lt_0p30 = sum(max(r["num_fraction"], 0.0) for r in rows_sorted if r["d_mid_mm"] < 0.30) / num_total
        fines_num_lt_0p40 = sum(max(r["num_fraction"], 0.0) for r in rows_sorted if r["d_mid_mm"] < 0.40) / num_total
        fines_num_lt_0p50 = sum(max(r["num_fraction"], 0.0) for r in rows_sorted if r["d_mid_mm"] < 0.50) / num_total
        fines_vol_lt_0p30 = sum(max(r["volume_fraction"], 0.0) for r in rows_sorted if r["d_mid_mm"] < 0.30) / vol_total
        fines_vol_lt_0p40 = sum(max(r["volume_fraction"], 0.0) for r in rows_sorted if r["d_mid_mm"] < 0.40) / vol_total
        fines_vol_lt_0p50 = sum(max(r["volume_fraction"], 0.0) for r in rows_sorted if r["d_mid_mm"] < 0.50) / vol_total
        fast_path_mm = diffusion_path_fast_mm / max(shell_weight_total, 1e-12)
        slow_path_mm = diffusion_path_slow_mm if diffusion_path_slow_mm > 1e-12 else fast_path_mm
        fast_pool_fraction = fast_reactive_index / max(fast_reactive_index + slow_reactive_index, 1e-12)
        fine_diameter_mean_mm = fine_diameter_acc_mm / max(fine_num_total, 1e-12) if fine_num_total > 1e-12 else D10_mm

        return {
            "surface_area": surface_area_mm_inv * 1e3,
            "surface_area_fast": surface_area_fast_mm_inv * 1e3,
            "surface_area_slow": surface_area_mm_inv * 1e3,
            "shell_fraction": shell_fraction_vol,
            "diffusion_path_m": slow_path_mm * 1e-3,
            "diffusion_path_fast_m": fast_path_mm * 1e-3,
            "diffusion_path_slow_m": slow_path_mm * 1e-3,
            "d32_m": d32_mm * 1e-3,
            "Dv50_m": Dv50_mm * 1e-3,
            "throat_diameter_m": d_throat_mm * 1e-3,
            "D10_m": D10_mm * 1e-3,
            "D50_m": D50_mm * 1e-3,
            "D90_m": D90_mm * 1e-3,
            "aspect_ratio_mean": aspect_mean,
            "roundness_mean": roundness_mean,
            "span_num": span_num,
            "fines_num_lt_0p30": fines_num_lt_0p30,
            "fines_num_lt_0p40": fines_num_lt_0p40,
            "fines_num_lt_0p50": fines_num_lt_0p50,
            "fines_vol_lt_0p30": fines_vol_lt_0p30,
            "fines_vol_lt_0p40": fines_vol_lt_0p40,
            "fines_vol_lt_0p50": fines_vol_lt_0p50,
            "throat_clog_index": throat_clog_index,
            "deposition_clog_index": deposition_clog_index,
            "fast_pool_fraction": fast_pool_fraction,
            "fine_diameter_mean_m": fine_diameter_mean_mm * 1e-3,
            "source": str(Path(bins_csv_path)),
            "diameter_scale": max(float(diameter_scale), 1e-9),
        }

    def _build_extraction_bins_from_rows(self, rows_sorted: list[dict]) -> dict:
        """
        將 measured PSD bins 轉成兩池一階釋放閉合所需的**幾何**量。

        What:
          對每個 bin 由解析後的等效球直徑 d_i 直接算出：
            R_i        = d_i / 2                          顆粒半徑
            δ_i        = min(shell_thickness, R_i)         破壁殼層厚度（= fast 擴散長度）
            R_core,i   = R_i − δ_i                         未破壁核心半徑（= slow 擴散長度）
            shell_acc_i = 1 − (R_core,i / R_i)³            fast pool 的質量分率
          並回傳 PSD 自身的 volume / number fraction 與形狀量（供堵塞 closure 用）。

        Why:
          新閉合（Crank 球形擴散首項）只需要「多少質量」與「要走多遠」兩件事：
          質量由 `volume_fraction × shell_acc` 決定，距離由 δ_i / R_core,i 決定。
          舊實作另外算了 A_fast / A_slow（面積）與 path_fast / path_slow（長度），
          再讓 `nw_eta_*` 去反推一個把 A·D/L 湊回目標速率的效率因子——
          面積與效率因子完全簡併，而 `path_fast` 的絕對 floor
          `max(0.25·shell_thickness, ·)` 讓多數 bin 的長度全等（AUD-3）。
          現在 λ_i 只由 δ_i、R_core,i 與 D(T)/τ_tort 決定，沒有可反推的自由度。

          **一致性保證**：δ_i 與 shell_acc_i 出自同一條幾何，因此
          「fast pool 有多少質量」與「fast pool 的擴散長度」不能各自被調整。
        """
        vol_total = sum(max(r["volume_fraction"], 0.0) for r in rows_sorted)
        if vol_total <= 0:
            raise ValueError("PSD bins 的 volume_fraction 總和必須為正")

        num_fraction: list[float] = []
        vol_fraction: list[float] = []
        d_mid_m: list[float] = []
        aspect: list[float] = []
        roundness: list[float] = []
        shell_fraction: list[float] = []
        radius_list: list[float] = []
        delta_list: list[float] = []
        core_radius_list: list[float] = []

        for row in rows_sorted:
            num_w = max(row["num_fraction"], 0.0)
            vol_w = max(row["volume_fraction"], 0.0) / vol_total
            d_mean_m = max(row["diameter_eq_mean_mm"] * 1e-3, 1e-12)
            # shell accessibility 與殼層厚度由**同一個**縮放後直徑解析算出，
            # 與 `pour_over.psd.shell_accessibility_fraction_mm` 共用定義。
            shell_acc = float(np.clip(
                shell_accessibility_fraction_mm(row["diameter_eq_mean_mm"], self.shell_thickness * 1e3),
                0.0, 1.0,
            ))
            radius_m = 0.5 * d_mean_m
            delta_m = min(self.shell_thickness, radius_m)
            core_radius_m = max(radius_m - delta_m, 0.0)

            num_fraction.append(num_w)
            vol_fraction.append(vol_w)
            d_mid_m.append(max(row["d_mid_mm"] * 1e-3, 1e-12))
            aspect.append(max(row["aspect_ratio_mean"], 1.0))
            roundness.append(max(row["roundness_mean"], 0.25))
            shell_fraction.append(shell_acc)
            radius_list.append(radius_m)
            delta_list.append(delta_m)
            core_radius_list.append(core_radius_m)

        return {
            "count": len(rows_sorted),
            "num_fraction": np.asarray(num_fraction, dtype=float),
            "volume_fraction": np.asarray(vol_fraction, dtype=float),
            "diameter_mid_m": np.asarray(d_mid_m, dtype=float),
            "aspect_ratio_mean": np.asarray(aspect, dtype=float),
            "roundness_mean": np.asarray(roundness, dtype=float),
            "shell_fraction": np.asarray(shell_fraction, dtype=float),
            "radius_m": np.asarray(radius_list, dtype=float),
            "shell_depth_m": np.asarray(delta_list, dtype=float),
            "core_radius_m": np.asarray(core_radius_list, dtype=float),
        }

    def _set_extraction_bins(self, bins: dict | None = None) -> None:
        """
        設定萃取 bins 與兩池初始質量，供 ODE 直接使用。

        What:
          逐 bin 寫入幾何（δ_i、R_core,i、shell_acc_i）與初始質量：
              M_fast_0,i = dose · max_EY · vol_frac_i ·  shell_acc_i
              M_slow_0,i = dose · max_EY · vol_frac_i · (1 − shell_acc_i)
          並由其總和回填 `M_fast_0` / `M_slow_0` / `M_sol_0`。

        Why:
          `Σ_i vol_frac_i = 1` ⇒ `M_sol_0 ≡ dose · max_EY`，**恆等**。
          舊實作是 `dose·max_EY·fast_fraction_effective·shell_accessibility_ratio`
          與 `dose·max_EY·(1−f)·shell_ratio^0.7`：三個與 PSD 幾乎無關的縮放因子
          串在一起，其中 `fast_fraction` 已凍結、`shell_accessibility_ratio`
          在 F1 之後恆為 1，於是整條退化成一個與 `max_EY` 完全簡併的常數
          （AUD-3：`max_EY_fit = 0.3725` 超物理上限就是這個簡併的產物）。
          現在兩池的分配**只**由 measured PSD 的殼層可及性決定，
          沒有任何可調的分配旋鈕。
        """
        if bins is None:
            # fallback：沒有 measured PSD 時退化成單一代表性 bin（同一套幾何語言）。
            radius = 0.5 * max(float(self.d32), self.particle_d_min)
            delta = min(self.shell_thickness, radius)
            core_radius = max(radius - delta, 0.0)
            shell_acc = float(np.clip(1.0 - (core_radius / max(radius, 1e-18)) ** 3, 0.0, 1.0))
            self.extraction_bin_count = 1
            self.ext_bin_num_fraction = np.array([1.0], dtype=float)
            self.ext_bin_volume_fraction = np.array([1.0], dtype=float)
            self.ext_bin_diameter_mid_m = np.array([self.d32], dtype=float)
            self.ext_bin_aspect_ratio_mean = np.array([getattr(self, "psd_aspect_ratio_mean", 1.0)], dtype=float)
            self.ext_bin_roundness_mean = np.array([getattr(self, "psd_roundness_mean", 1.0)], dtype=float)
            self.ext_bin_shell_fraction = np.array([shell_acc], dtype=float)
            self.ext_bin_radius_m = np.array([radius], dtype=float)
            self.ext_bin_shell_depth_m = np.array([delta], dtype=float)
            self.ext_bin_core_radius_m = np.array([core_radius], dtype=float)
        else:
            self.extraction_bin_count = int(bins["count"])
            self.ext_bin_num_fraction = np.asarray(bins["num_fraction"], dtype=float)
            self.ext_bin_volume_fraction = np.asarray(bins["volume_fraction"], dtype=float)
            self.ext_bin_diameter_mid_m = np.asarray(bins["diameter_mid_m"], dtype=float)
            self.ext_bin_aspect_ratio_mean = np.asarray(bins["aspect_ratio_mean"], dtype=float)
            self.ext_bin_roundness_mean = np.asarray(bins["roundness_mean"], dtype=float)
            self.ext_bin_shell_fraction = np.asarray(bins["shell_fraction"], dtype=float)
            self.ext_bin_radius_m = np.asarray(bins["radius_m"], dtype=float)
            self.ext_bin_shell_depth_m = np.asarray(bins["shell_depth_m"], dtype=float)
            self.ext_bin_core_radius_m = np.asarray(bins["core_radius_m"], dtype=float)

        # slow pool 的有效核心半徑：R_core → 0 時該 bin 的 M_slow_0 也 → 0
        # （shell_acc → 1），因此 floor 只影響一個質量為零的池的 λ 報表值，
        # 不改變任何質量流。設 floor 的唯一理由是避免 λ_slow = ∞ 進 ODE。
        self.ext_bin_core_radius_eff_m = np.maximum(
            self.ext_bin_core_radius_m, 0.25 * np.maximum(self.ext_bin_shell_depth_m, 1e-12)
        )

        shell_acc_arr = np.clip(self.ext_bin_shell_fraction, 0.0, 1.0)
        vol_arr = np.maximum(self.ext_bin_volume_fraction, 0.0)
        M_total = float(self.dose_g) * float(self.max_EY)
        self.M_fast_0_bins = M_total * vol_arr * shell_acc_arr
        self.M_slow_0_bins = M_total * vol_arr * (1.0 - shell_acc_arr)
        self.M_fast_0 = float(np.sum(self.M_fast_0_bins))
        self.M_slow_0 = float(np.sum(self.M_slow_0_bins))
        self.M_sol_0 = self.M_fast_0 + self.M_slow_0
        # 診斷：measured PSD 幾何直接決定的 fast pool 佔比（無任何旋鈕）
        self.fast_pool_mass_fraction = (
            self.M_fast_0 / self.M_sol_0 if self.M_sol_0 > 0 else 0.0
        )

    def axial_layer_fractions(self) -> np.ndarray:
        """
        回傳床內軸向節點的體積分率。

        What:
          將粉床液相切成 `axial_nodes` 個等體積 layer，供串接 CSTR 使用。

        Why:
          reduced-order 模型要補軸向梯度，但不值得直接跳到 PDE；
          等體積 layer 能避免圓錐幾何把上層權重放到過大，同時保留可解釋的上/下層濃度差。
        """
        n_layers = max(int(self.axial_nodes), 1)
        return np.full(n_layers, 1.0 / n_layers, dtype=float)

    def __post_init__(self):
        self._tan  = np.tan(np.radians(self.half_angle_deg))
        self._tan2 = self._tan ** 2
        self.axial_node_count = max(int(self.axial_nodes), 1)
        self.axial_layer_volume_fraction = self.axial_layer_fractions()
        # 達西幾何係數基值 Φ_ref = π·tan²θ·ρg/μ_ref [m⁻¹s⁻¹]
        # Why:
        #   q_extract 採固定粉床參考截面 A_ref = π·tan²θ·h_bed²、路徑長 L_bed = h_bed，
        #   因此 Darcy 式可整理成 Q = Φ_ref · k · h_bed · h_eff，
        #   T 相依版本再於 q_extract 中按 μ(T)/μ_ref 縮放。
        self.phi_darcy = np.pi * self._tan2 * RHO * G / self.mu  # 避免與孔隙率 phi 重名
        # 悶蒸兩階段門檻（修正 [13]：CO₂排氣修正吸水率）
        self._V_dry  = self.dose_g * self.absorb_dry_ratio  * 1e-6  # [m³]
        self._V_full = self.dose_g * self.absorb_full_ratio * 1e-6  # [m³]
        self.V_absorb = self._V_full - self._V_dry  # 可吸收水量 [m³]（毛細飽和 ODE 分母）
        # 粉層滯留水量（孔隙體積）
        self.V_bed    = self.cone_bed_volume_m3()                 # 粉床幾何體積 [m³]
        self.V_liquid = self.phi * self.V_bed                      # 孔隙水量 [m³]
        self.rho_bulk_dry_g_ml = self.dry_bulk_density_g_ml()
        # 顆粒子模型：優先使用實測 PSD bins；否則退回單一代表性粒徑。
        #
        # 尺度來源（2026-05 PSD 管線重寫）：
        #   - 有 bins CSV 時，PSD 的絕對尺度**完全**由該 CSV 決定，只受顯式
        #     `psd_diameter_scale` 縮放。不再由 `D10_measured_m` 反推縮放倍率。
        #   - 「相對量」（surface_area_ratio、shell_accessibility_ratio 等）一律
        #     以當前 measured PSD 自身為基準（比值恆為 1）。舊實作把 reference
        #     由 `k_ref` 反推成一個虛構的 250 μm 粒子，等於讓一個 closure 參數
        #     決定量測幾何的參考點——那是循環依賴，不是 measured PSD。
        #   - 絕對量（surface_area_spec、shell_fraction_abs、diffusion_path_*）
        #     直接來自 bins，不經任何參考縮放。
        measured_bins_native = None
        measured_bin_rows = None
        psd_scale = max(float(self.psd_diameter_scale), 1e-9)
        if self.psd_bins_csv_path:
            measured_bins_native = self._particle_stats_from_bins_csv(
                self.psd_bins_csv_path, diameter_scale=psd_scale
            )
            measured_bin_rows = self._load_psd_bin_rows(self.psd_bins_csv_path, diameter_scale=psd_scale)

        # number-based D10：診斷量。受影像偵測下限鉗制，不驅動任何幾何。
        if self.D10_measured_m is not None:
            self.D10 = max(float(self.D10_measured_m), self.particle_d_min)
        elif measured_bins_native is not None:
            self.D10 = max(float(measured_bins_native["D10_m"]), self.particle_d_min)
        else:
            self.D10 = np.sqrt(max(self.k, 1e-18) / max(self.f_sp * self.phi**self.eta_porosity, 1e-18))

        if measured_bins_native is not None:
            particle = measured_bins_native
            # 相對量以自身為基準：measured PSD 就是這個 case 的參考幾何。
            ref_particle = measured_bins_native
        else:
            particle = self._single_bin_particle_stats(self.D10)
            ref_particle = particle
        # 模型尺度錨點：Sauter d32（決定比表面積）與體積中位徑 Dv50。
        self.d32 = max(float(particle["d32_m"]), self.particle_d_min)
        self.Dv50 = max(float(particle["Dv50_m"]), self.particle_d_min)
        self.psd_throat_diameter_m = float(particle["throat_diameter_m"])
        self.surface_area_spec = particle["surface_area"]
        self.ref_surface_area_spec = ref_particle["surface_area"]
        self.surface_area_ratio = self.surface_area_spec / max(self.ref_surface_area_spec, 1e-12)
        self.surface_area_fast_spec = particle.get("surface_area_fast", self.surface_area_spec)
        self.ref_surface_area_fast_spec = ref_particle.get("surface_area_fast", self.ref_surface_area_spec)
        self.surface_area_slow_spec = particle.get("surface_area_slow", self.surface_area_spec)
        self.ref_surface_area_slow_spec = ref_particle.get("surface_area_slow", self.ref_surface_area_spec)
        self.shell_fraction_abs = particle["shell_fraction"]
        self.ref_shell_fraction_abs = ref_particle["shell_fraction"]
        self.shell_accessibility_ratio = float(np.clip(
            self.shell_fraction_abs / max(self.ref_shell_fraction_abs, 1e-12),
            0.0, 1.0,
        ))
        # 殼層可及性最多等同 reference 殼層；不可作為放大可萃取總量的乘數。
        self.diffusion_path_m = particle["diffusion_path_m"]
        self.ref_diffusion_path_m = ref_particle["diffusion_path_m"]
        self.diffusion_path_fast_m = particle.get("diffusion_path_fast_m", self.diffusion_path_m)
        self.ref_diffusion_path_fast_m = ref_particle.get("diffusion_path_fast_m", self.ref_diffusion_path_m)
        self.diffusion_path_slow_m = particle.get("diffusion_path_slow_m", self.diffusion_path_m)
        self.ref_diffusion_path_slow_m = ref_particle.get("diffusion_path_slow_m", self.ref_diffusion_path_m)
        self.psd_source = particle.get("source", "fractal_psd")
        self.psd_aspect_ratio_mean = particle.get("aspect_ratio_mean", np.nan)
        self.psd_roundness_mean = particle.get("roundness_mean", np.nan)
        self.psd_span_num = particle.get("span_num", np.nan)
        self.psd_D50_m = particle.get("D50_m", np.nan)
        self.psd_D90_m = particle.get("D90_m", np.nan)
        self.psd_fines_num_lt_0p30 = particle.get("fines_num_lt_0p30", np.nan)
        self.psd_fines_num_lt_0p40 = particle.get("fines_num_lt_0p40", np.nan)
        self.psd_fines_num_lt_0p50 = particle.get("fines_num_lt_0p50", np.nan)
        self.psd_fines_vol_lt_0p30 = particle.get("fines_vol_lt_0p30", np.nan)
        self.psd_fines_vol_lt_0p40 = particle.get("fines_vol_lt_0p40", np.nan)
        self.psd_fines_vol_lt_0p50 = particle.get("fines_vol_lt_0p50", np.nan)
        self.psd_throat_clog_index = particle.get("throat_clog_index", np.nan)
        self.psd_deposition_clog_index = particle.get("deposition_clog_index", np.nan)
        self.psd_fast_pool_fraction = particle.get("fast_pool_fraction", np.nan)
        self.psd_fine_diameter_mean_m = particle.get("fine_diameter_mean_m", np.nan)
        self.ref_psd_fines_num_lt_0p40 = ref_particle.get("fines_num_lt_0p40", np.nan)
        self.ref_psd_fines_vol_lt_0p40 = ref_particle.get("fines_vol_lt_0p40", np.nan)
        self.ref_psd_throat_clog_index = ref_particle.get("throat_clog_index", np.nan)
        self.ref_psd_deposition_clog_index = ref_particle.get("deposition_clog_index", np.nan)
        self.ref_psd_fast_pool_fraction = ref_particle.get("fast_pool_fraction", np.nan)
        # 固相溶質的兩池分配（F3）：
        #   M_fast_0,i = dose·max_EY·vol_frac_i·shell_acc_i
        #   M_slow_0,i = dose·max_EY·vol_frac_i·(1 − shell_acc_i)
        # 由 `_set_extraction_bins()` 在下方統一計算並回填 M_fast_0 / M_slow_0 /
        # M_sol_0。此處**不再**有 fast_fraction、shell_accessibility_ratio、
        # alpha_slow_access 這三層與 PSD 無關的縮放（AUD-3：它們與 `max_EY`
        # 完全簡併，是 `max_EY_fit = 0.3725` 超物理上限的直接成因）。
        self.psd_clog_index_value = self.psd_clog_index()
        self.k_beta_prior_psd = self.k_beta_prior_from_psd()
        self.k_beta_prior_sigma_dex = KBETA_PRIOR_SIGMA_DEX
        # throat / deposition 的權重分配直接取兩個絕對指數的比例。
        # Why: 兩者已是同一個飽和堵塞核 1/(1+d/d_throat) 的無因次加權平均，
        #      只差在權重為 number（喉道事件）或 volume（沉積回填），可直接比較。
        #      舊實作除以一個虛構 reference PSD，在 reference 改為自身後會退化成
        #      固定 50/50，等於把 PSD 資訊丟掉。
        throat = getattr(self, "psd_throat_clog_index", np.nan)
        deposition = getattr(self, "psd_deposition_clog_index", np.nan)
        if np.isfinite(throat) and np.isfinite(deposition):
            throat_rel = max(float(throat), 1e-6)
            deposition_rel = max(float(deposition), 1e-6)
        else:
            throat_rel = 1.0
            deposition_rel = 1.0
        split_sum = throat_rel + deposition_rel
        self.k_beta_throat_share = float(np.clip(throat_rel / split_sum, 0.15, 0.85))
        self.k_beta_deposition_share = float(np.clip(1.0 - self.k_beta_throat_share, 0.15, 0.85))
        norm_sum = self.k_beta_throat_share + self.k_beta_deposition_share
        self.k_beta_throat_share /= norm_sum
        self.k_beta_deposition_share /= norm_sum
        self.k_beta_throat_coeff = float(self.k_beta * self.k_beta_throat_share)
        self.k_beta_deposition_coeff = float(self.k_beta * self.k_beta_deposition_share)
        self.k_beta_throat_prior = float(self.k_beta_prior_psd * self.k_beta_throat_share)
        self.k_beta_deposition_prior = float(self.k_beta_prior_psd * self.k_beta_deposition_share)
        # 咖啡粉等效熱容體積：V_equiv = m_coffee × Cp_coffee / (ρ_water × Cp_water)
        # Why: 悶蒸時乾粉（常溫）吸收熱水熱量，換算為等效水體積後加入熱動方程分母
        #      Cp_water ≈ 4180 J/(kg·K)；dose_g [g] = dose_g×1e-3 [kg]
        self.V_equiv_coffee = self.solid_water_equivalent_ml(self.dose_g, self.Cp_coffee / 1000.0) * 1e-6  # [m³]
        self.V_equiv_dripper = self.solid_water_equivalent_ml(self.dripper_mass_g, self.dripper_cp_J_gK) * 1e-6  # [m³]
        # ── Class B（先算再固定）：孔喉尺度與床層保水頭 ──────────────────────────
        # What: 由 measured PSD 的 canonical Sauter 平均徑 `d32` 推代表性孔喉半徑，
        #       再由 Young-Laplace 得床層毛細保水頭 h_cap_bed = 2σ/(ρ g r_pore)。
        # Why:  「濕床能不能被重力排乾」是可由量測直接判定的事，不該交給 closure 猜。
        #       kinu29：d32 = 893.8 μm → r_pore ≈ 179 μm → h_cap_bed ≈ 68 mm > h_bed 53 mm，
        #       故殘餘飽和度 S_r = 1，床層孔隙水不會在沖煮時間尺度內被重力排空。
        d_char = float(getattr(self, "d32", 0.0)) or float(self.D10)
        self.pore_radius_m = max(float(self.pore_radius_ratio) * d_char, 1e-9)
        self.h_cap_bed_ref = self.h_cap_bed(self.T_ref)
        # 體積熱容 [J/(m³·K)]：焓平衡與能量審計共用同一個縮放，避免兩處各寫一次 4180
        self.rho_cp_water = RHO * CP_WATER
        # 萃取 bins 必須在此處建立：它同時決定 M_fast_0 / M_slow_0 / M_sol_0，
        # 而下面的 κ 與堵塞權重都依賴這些量。
        if measured_bin_rows is not None:
            self._set_extraction_bins(self._build_extraction_bins_from_rows(measured_bin_rows))
        else:
            self._set_extraction_bins()
        # κ = C_sat_0 / M_sol_0 [L⁻¹]（單組分 backward-compat 診斷量）
        # dose_g = 0（純流體 baseline 對比）時退化為 0，不需萃取。
        self.kappa = (self.C_sat / self.M_sol_0) if self.M_sol_0 > 0 else 0.0
        self.kappa_fast = (self.C_sat_fast / self.M_fast_0) if self.M_fast_0 > 0 else 0.0
        self.kappa_slow = (self.C_sat_slow / self.M_slow_0) if self.M_slow_0 > 0 else 0.0
        (
            self.clog_throat_weights,
            self.clog_deposition_weights,
            self.clog_throat_vchar_m3,
            self.clog_deposition_multiplier,
        ) = self.clogging_bin_profiles()

    def _single_bin_particle_stats(self, D10_target: float) -> dict:
        """
        以單一 representative bin 建立 fallback 粒子統計。

        What:
          將沒有 measured PSD 時的 fallback 也收斂到「同一套 bin 模型」：
          - 代表直徑取唯一已知的粒徑尺度（使用者給的 `D10_measured_m`，
            或由 `k` 反推的等效粒徑），並同時當作該退化 PSD 的 d32
          - 形狀預設為近球形
          - shell / core 幾何依 200 μm 殼層直接解析計算

        Why:
          舊的理想碎形 PSD 是另一條獨立流程。現在只保留單一最佳模型，
          fallback 也必須走 bin-resolved 的同一套幾何語言，而不是再維護第二種 PSD closure。
        """
        d = max(D10_target, self.particle_d_min)
        radius = 0.5 * d
        shell_depth = min(self.shell_thickness, radius)
        core_radius = max(radius - shell_depth, 0.0)
        shell_fraction = 1.0 - (core_radius / max(radius, 1e-12)) ** 3
        surface_area = 6.0 / max(d, 1e-18)
        fast_path = max(0.5 * shell_depth, 1e-12)
        slow_path = max(self.shell_thickness, max(core_radius, fast_path))
        fines_flag_030 = float(d < 0.30e-3)
        fines_flag_040 = float(d < 0.40e-3)
        fines_flag_050 = float(d < 0.50e-3)
        d_throat_mm = self.throat_diameter_from_d32(d * 1e3)
        clog_kernel = 1.0 / (1.0 + (d * 1e3) / max(d_throat_mm, 1e-12))
        throat_index = float(clog_kernel)
        deposition_index = float(clog_kernel)
        return {
            "surface_area": float(surface_area),
            "surface_area_fast": float(surface_area * shell_fraction),
            "surface_area_slow": float(surface_area),
            "shell_fraction": float(shell_fraction),
            "diffusion_path_m": float(slow_path),
            "diffusion_path_fast_m": float(fast_path),
            "diffusion_path_slow_m": float(slow_path),
            "D10_m": float(d),
            "D50_m": float(d),
            "D90_m": float(d),
            "aspect_ratio_mean": 1.0,
            "roundness_mean": 1.0,
            "span_num": 1.0,
            "fines_num_lt_0p30": fines_flag_030,
            "fines_num_lt_0p40": fines_flag_040,
            "fines_num_lt_0p50": fines_flag_050,
            "fines_vol_lt_0p30": fines_flag_030,
            "fines_vol_lt_0p40": fines_flag_040,
            "fines_vol_lt_0p50": fines_flag_050,
            "throat_clog_index": float(throat_index),
            "deposition_clog_index": float(deposition_index),
            "fast_pool_fraction": float(shell_fraction),
            "fine_diameter_mean_m": float(d),
            "d32_m": float(d),
            "Dv50_m": float(d),
            "throat_diameter_m": float(d_throat_mm * 1e-3),
            "source": "synthetic_single_bin",
            "diameter_scale": 1.0,
        }

    def saturation(self, V_poured: float) -> float:
        """
        累積注水量對飽和目標的平滑上限 sat_target ∈ [0, 1]。C¹ 連續。

        DEPRECATED（主 ODE 路徑）：顆粒吸水量 `V_abs` 自 F2 起是顯式狀態，
        由 `absorption_rate()` 的動力學/供給雙重限制決定，不再由 `V_poured` 代數推得。
        本式保留為向後相容的代數 closure（舊分析腳本與 `V_dry`/`V_full` 語意展示）。

        What: cubic Hermite smooth-step：
              x = clamp((V_poured - V_dry) / (V_full - V_dry), 0, 1)
              sat_target = x² × (3 - 2x)

        Why（修正 [10]）: 原分段線性版本在 V=V_dry 和 V=V_full 有一階不連續（C⁰）。
             這兩個轉折點在飽和驅動項中直接影響 dh/dt，
             造成 ODE 積分器在轉折瞬間遭遇非光滑項，引發數值衝擊（spike）。
             Cubic Hermite 在兩端都有 dsat/dV=0，保持 C¹ 連續。
        """
        if V_poured <= self._V_dry:
            return 0.0
        elif V_poured >= self._V_full:
            return 1.0
        x = (V_poured - self._V_dry) / (self._V_full - self._V_dry)
        return x * x * (3.0 - 2.0 * x)   # cubic Hermite: C¹ at both ends

    def flow_saturation(self, sat, t_sec, bloom_end_s: float | None):
        """
        流動方程使用的等效飽和度 sat_flow。

        What:
            bloom 前：sat_flow = sat
            bloom 後：sat_flow = sat + (1 - sat) × (1 - exp(-(t - t_bloom_end)/tau))

        Why:
            `sat` 狀態主要描述乾粉潤濕前沿；bloom 結束後若直接硬設 sat_flow=1，
            會在 Darcy 流量、孔隙率與有效注水上引入人工不連續。
            這裡改用連續鬆弛，讓模型平滑過渡到「已成濕床」近似。
        """
        sat_arr = np.clip(np.asarray(sat, dtype=float), 0.0, 1.0)
        if bloom_end_s is None:
            return float(sat_arr) if sat_arr.ndim == 0 else sat_arr

        t_post = np.maximum(np.asarray(t_sec, dtype=float) - float(bloom_end_s), 0.0)
        tau = max(self.sat_flow_relax_tau, 1e-6)
        relax = 1.0 - np.exp(-t_post / tau)
        sat_flow = sat_arr + (1.0 - sat_arr) * relax
        sat_flow = np.clip(sat_flow, 0.0, 1.0)
        return float(sat_flow) if sat_flow.ndim == 0 else sat_flow

    # ── F2b：床內 mobile / immobile 雙水池閉合 ────────────────────────────────
    def wetting_rate(self, w: float, V_retained: float) -> float:
        """
        床層潤濕狀態 w 的成長速率 [1/s]。

        What:
            dw/dt = (1 − w)/τ_wet · g(液相在場)
            g     = smoothstep( V_retained / V_dry )，V_retained = 滯留在濾杯內的總水量

        Why:
            w 是「粉床已建立保水／吸水能力的比例」，它必須由液體接觸驅動——
            乾床放著不會自己潤濕，所以要 g gate，而不是寫成 w = 1 − exp(−t/τ)。
            g 的參考量取 `V_dry`（= dose × absorb_dry_ratio，Class B 量測值），
            語意是「床層已吃進 O(V_dry) 的水 ⇒ 液相確實在場」，不新增常數。
            用總滯留水（含床頂積水）而非床內液量，是為了避免 t = 0 的死結：
            床內液量為 0 → w = 0 → 容量為 0 → 床內液量永遠是 0。
        """
        w_c = _clip(float(w), 0.0, 1.0)
        x = _clip(max(float(V_retained), 0.0) / max(self._V_dry, 1e-12), 0.0, 1.0)
        contact = x * x * (3.0 - 2.0 * x)
        return contact * (1.0 - w_c) / max(float(self.tau_wet_s), 1e-6)

    def bed_retention_fraction(self, T_K=None) -> float:
        """
        床層中可被毛細力留住（不被重力排乾）的高度分率 [-]。

        What: f_retain = clip(h_cap_bed(T) / h_bed, 0, 1)

        Why:  Young-Laplace 保水頭 h_cap_bed 代表「毛細力能把水柱撐住的高度」。
              床高 h_bed 若不超過它，整床都留得住（f_retain = 1，kinu29：68.6 > 53 mm）；
              若換粗研磨使 h_cap_bed < h_bed，只有下方 h_cap_bed 那一段留得住，
              上方自排。這條式子讓 h_cap_bed 從「診斷量」變回主方程裡的物理量，
              且在兩個 regime 之間連續，不需要分支。
        """
        return float(_clip(self.h_cap_bed(T_K) / max(self.h_bed, 1e-12), 0.0, 1.0))

    def immobile_capacity(self, w: float, T_K=None) -> float:
        """毛細保水（immobile）水池的上限 [m³]：φ·V_bed · f_retain(T) · w。"""
        return self.V_liquid * self.bed_retention_fraction(T_K) * _clip(float(w), 0.0, 1.0)

    def absorb_capacity(self, w: float) -> float:
        """顆粒吸收水池的上限 [m³]：V_full · w（潤濕/溶脹尚未完成時吸不滿）。"""
        return self._V_full * _clip(float(w), 0.0, 1.0)

    def mobile_capacity(self, V_imm: float) -> float:
        """mobile 孔隙水的可用空間 [m³]：φ·V_bed − V_imm（兩池共用同一孔隙體積）。"""
        return max(self.V_liquid - max(float(V_imm), 0.0), 0.0)

    def mobile_saturation(self, V_mob: float, V_imm: float):
        """
        mobile 孔隙飽和度 S_mob ∈ [0,1]，供 `relative_permeability` 與床內驅動頭使用。

        What: S_mob = V_mob / max(φ·V_bed − V_imm, ε)

        Why:  這正是 Corey 的有效飽和度 S_e = (S − S_r)/(1 − S_r)，
              只是 S_r 不再是常數，而是由 `V_imm` 顯式攜帶的時序量。
              因此 `sat_rel_perm_residual` 必須是 0，否則同一份保水被記兩次。
        """
        cap = _floor(self.V_liquid - _floor(_as_float(V_imm), 0.0), 1e-3 * self.V_liquid)
        s = _clip(_floor(_as_float(V_mob), 0.0) / cap, 0.0, 1.0)
        return _scalar_out(s)

    def absorption_rate(self, V_abs: float, w: float, Q_in: float, V_free: float, V_mob: float, T_K: float):
        """
        顆粒吸水速率 [m³/s]，以及其中由自由水 / mobile 孔隙水供給的部分。

        What:
            τ_abs   = tau_cap_T(T)                              （Lucas-Washburn 溫度相依）
            kinetic = (V_full·w − V_abs) / τ_abs                 （動力學上限，容量隨潤濕開放）
            supply  = Q_in + (V_free + V_mob) / τ_abs            （供給上限）
            A       = smooth_min(kinetic, supply)
            A_free, A_mob = A × 各來源佔 supply 的比例

        Why:
            容量改吃 `V_full·w` 是本 slice 的核心修正：舊式以 τ_cap ≈ 10 s 直衝 V_full = 24 mL，
            t = 30 s 就吸掉 22 mL，但量測當下**總**保水只有 14.6 g——
            吸水量在物理上不可能超過總保水。把容量掛在潤濕狀態上之後，
            「初期吸不多、後段才吸滿」與 retained_mass_g 的時序一致。
            回傳來源分攤仍是為了讓各水池的非負性由構造保證（抽取率 ≤ 存量/τ）。
            注意 immobile 池不是吸水來源：immobile 的定義是「不會再離開孔隙的水」，
            這裡的「不離開」指不被重力排出，而顆粒吸收是另一條路徑；
            把它排除在供給外只是避免第二條耦合，且量級上由 mobile/free 供給已足夠。

        Returns:
            (A_total, A_from_free, A_from_mob)，單位皆為 m³/s。
        """
        tau = max(self.tau_cap_T(T_K), 1e-6)
        gap = max(self.absorb_capacity(w) - max(float(V_abs), 0.0), 0.0)
        s_in = max(float(Q_in), 0.0)
        s_free = max(float(V_free), 0.0) / tau
        s_mob = max(float(V_mob), 0.0) / tau
        supply = s_in + s_free + s_mob
        rate = max(float(smooth_min(gap / tau, supply, RATE_SMOOTH_EPS)), 0.0)
        inv = 1.0 / max(supply, 1e-18)
        return rate, rate * s_free * inv, rate * s_mob * inv

    def immobile_capture_rate(self, V_mob: float, V_imm: float, w: float, T_K: float) -> float:
        """
        mobile → immobile 的毛細捕捉速率 [m³/s]（恆非負，且只從 mobile 抽取）。

        What:
            gap  = max(φ·V_bed·f_retain·w − V_imm, 0)
            C    = smooth_min(gap / τ_cap(T), V_mob / τ_cap(T))

        Why:
            毛細保水的水一定先是穿過床層的 mobile 水，被孔喉的 Young-Laplace 壓差
            扣留下來才變成 immobile；因此這是床內轉換，不改變床內總液量，
            也不可能讓 V_mob + V_imm 超過 φ·V_bed（結構上保證）。
            容量隨 w 開放，是「剛潤濕的床留不住水、潤濕後才留得住」的直接寫法——
            這正是量測 t = 10 → 30 s 床層淨排出 24 mL、t = 142 s 卻保水 52 g 的來源。
        """
        tau = max(self.tau_cap_T(T_K), 1e-6)
        gap = max(self.immobile_capacity(w, T_K) - max(float(V_imm), 0.0), 0.0)
        return max(float(smooth_min(gap / tau, max(float(V_mob), 0.0) / tau, RATE_SMOOTH_EPS)), 0.0)

    def pore_fill_rate(self, V_mob: float, V_imm: float, Q_perc: float, V_free: float):
        """
        mobile 孔隙的填充速率 [m³/s] 及其中由自由水供給的部分。

        What:
            gap    = φ·V_bed − V_imm − V_mob
            supply = max(Q_perc, 0) + V_free / TRANSFER_TAU_S
            P      = smooth_min(gap / TRANSFER_TAU_S, supply)
            P_free = P × (V_free/τ) / supply

        Why:
            濕床的滲入是 Darcy 尺度的過程（秒），不是毛細吸收尺度（τ_cap ≈ 10 s）：
            若用 τ_cap 當填充率上限，床內 mobile 水最多只能以 φV_bed/τ_cap ≈ 2 mL/s
            被補充，主沖煮段 5 mL/s 的出流就會被儲水補給憑空掐死。
            這裡沒有再放「乾粉先吸飽 V_dry 才填孔隙」的 gate：
            量測顯示第一滴在 t = 5 s（悶蒸注水才 31.7 mL）就落地，
            乾床本來就會讓水穿過；出液早期之所以少，是 kr(S_mob) 與 h_gas 的作用，
            不是孔隙拒絕充填。

        Returns:
            (P_total, P_from_free)，單位皆為 m³/s。
        """
        tau = TRANSFER_TAU_S
        gap = max(self.mobile_capacity(V_imm) - max(float(V_mob), 0.0), 0.0)
        s_stream = max(float(Q_perc), 0.0)
        s_free = max(float(V_free), 0.0) / tau
        supply = s_stream + s_free
        rate = max(float(smooth_min(gap / tau, supply, RATE_SMOOTH_EPS)), 0.0)
        return rate, rate * s_free / max(supply, 1e-18)

    def bed_drive_components(self, h_free, T_K=None, t_sec: float = 0.0, sat=None) -> dict:
        """
        粉床主流與快路徑共用的驅動頭分解。

        What:
            h_bed_drive = S_mob · h_bed
            raw_head    = h_free + h_bed_drive − (h_cap + h_gas(t))
            h_eff       = softplus(raw_head)

        Why（F2b 修正 F2 的驅動頭錯誤）:
            床層底部是濾紙出口、壓力為大氣壓，床頂為自由水面，因此穿床的**總水頭差**
            就是「頂部壓力頭 + 高程差」= h_free + h_bed。F2 把毛細保水頭 h_cap_bed
            從驅動頭裡減掉，是把兩件事混為一談：
              - h_cap_bed 決定的是「沒有積水之後，床內水會不會繼續被重力排出」，
                亦即殘餘飽和度有多大 —— 它是 `V_imm` 的容量來源（見 `bed_retention_fraction`）；
              - 它不是穿床的壓力梯度。把它從梯度裡扣掉，等於宣稱 h_cap_bed > h_bed
                的細研磨床「完全不導水」，與 Darcy 不符，也逼得 k 必須上調 4.5×。
            現在床內只剩 mobile 水參與驅動，其連通程度用 S_mob 表示：
            S_mob → 1（床內飽和）給出完整的 h_bed 高程頭；
            S_mob → 0（mobile 水排乾、只剩 immobile）驅動頭退回 h_free，
            再配合 kr(S_mob) → 0，出流自然終止 —— 終止條件仍不需要任何 clamp。
            同理，濕床內沒有液氣介面，毛細力不提供額外的穿床驅動頭；門檻
            h_cap + h_gas 也不隨濕潤程度縮減（EXP-20261007-HCAP-WET-REMOVAL）。

        Args:
            h_free : 粉床頂部以上的自由水柱高度 [m]（不是總水位）
            sat    : 床內 **mobile** 孔隙飽和度 S_mob ∈ [0,1]（見 `mobile_saturation`）
        """
        h_free_arr = _floor(_as_float(h_free), 0.0)
        t_arr = _as_float(t_sec)
        if sat is None:
            s_mob = np.zeros_like(h_free_arr, dtype=float)
        else:
            s_mob = _clip(_as_float(sat), 0.0, 1.0)
        h_threshold = self.h_cap + self.h_gas(t_arr)
        h_bed_drive = s_mob * self.h_bed
        raw_head = h_free_arr + h_bed_drive - h_threshold
        eps = HEAD_SOFTPLUS_EPS_M
        h_eff = eps * np.logaddexp(0.0, raw_head / eps)
        return {
            "h_threshold": _scalar_out(h_threshold),
            "h_bed_drive": _scalar_out(h_bed_drive),
            "raw_head": _scalar_out(raw_head),
            "h_eff": _scalar_out(h_eff),
        }

    def bed_drive_head(self, h_free, T_K=None, t_sec: float = 0.0, sat=None):
        """
        粉床主流與快路徑共用的有效驅動水頭。

        What:
            回傳 `bed_drive_components()` 中的 `h_eff`。

        Why:
            讓主流程繼續使用單一標量 closure，同時 diagnostics 可讀取完整分解。
        """
        comps = self.bed_drive_components(h_free, T_K=T_K, t_sec=t_sec, sat=sat)
        h_eff = comps["h_eff"]
        return _scalar_out(h_eff)

    def relative_permeability(self, sat):
        """
        未飽和床層的相對滲透率 `kr(S_mob)`。

        What:
            以 Corey 型 closure 表示：
              S_e = clamp((S_mob - s_r) / (1 - s_r), 0, 1)
              kr  = smoothstep(S_e) ^ n
            自變數是 **mobile** 飽和度（見 `mobile_saturation`），s_r 結構上為 0。

        Why:
            `bed_drive_head()` 處理的是壓力頭何時足以推動液體，
            但未飽和 Darcy 還需要一個顯式的導水能力衰減 `kr`。
            自變數必須是 mobile 飽和度而不是總飽和度：毛細扣留的 immobile 水
            佔著孔隙卻不導流，用總飽和度會把「床內水多」誤讀成「導水能力強」。
            這也是 F2 §6 兩條失敗路徑的共同根因。
        """
        sat_arr = _clip(_as_float(sat), 0.0, 1.0)
        s_r = _clip(float(self.sat_rel_perm_residual), 0.0, 0.95)
        if s_r >= 0.999:
            kr = np.zeros_like(sat_arr, dtype=float)
            return float(kr) if kr.ndim == 0 else kr
        s_e = _clip((sat_arr - s_r) / max(1.0 - s_r, 1e-12), 0.0, 1.0)
        s_smooth = s_e * s_e * (3.0 - 2.0 * s_e)
        kr = _clip(s_smooth ** max(float(self.sat_rel_perm_exp), 1.0), 0.0, 1.0)
        return _scalar_out(kr)

    def sigma_water(self, T_K: float) -> float:
        """
        水的表面張力近似 [N/m]。

        What: 以 93°C 為基準做一階線性近似，避免在 0D 模型中引入過重的物性表。
              σ(T) = σ_ref + a·(T - T_ref)

        Why: Lucas-Washburn / Darcy 毛細潤濕的速度標度與 σ/μ 成正比；
             雖然 σ 對 T 的敏感度小於 μ，但不能完全忽略。
        """
        sigma_ref = 0.060  # 93°C 附近表面張力量級
        slope = -1.5e-4    # dσ/dT < 0：溫度升高時表面張力下降
        # np.maximum（而非 max）：`h_cap_bed` 在後處理會餵整條 T_K 時序進來
        sigma = _floor(sigma_ref + slope * (_as_float(T_K) - self.T_ref), 1e-3)
        return _scalar_out(sigma)

    def tau_cap_T(self, T_K: float) -> float:
        """
        溫度相依的毛細潤濕時間常數 [s]。

        What: τ_cap(T) = τ_ref / κ_ratio，κ_ratio ∝ (σ/μ) / (σ_ref/μ_ref)

        Why: Lucas-Washburn 標度 l ~ sqrt((rσ/μ)t)；
             高溫時 μ 下降的效應大於 σ 下降，因此潤濕加快、τ_cap 變小。
        """
        sigma_ratio = self.sigma_water(T_K) / self.sigma_water(self.T_ref)
        mu_ratio = self.mu_water(T_K) / self.mu
        kappa_ratio = sigma_ratio / max(mu_ratio, 1e-12)
        return self.tau_cap_ref / max(kappa_ratio, 1e-6)

    def h_gas(self, t_sec: float) -> float:
        """
        CO₂ 背壓等效水頭 [m]（修正 [14]）。

        What: h_gas(t) = h_gas_0 × exp(−t / τ_CO2)

        Why:  新鮮豆子悶蒸時內部 CO₂ 分壓對達西流施加反向阻力。
              隨著 CO₂ 從粉床逸散，背壓指數衰減至零。
              Darcy 有效驅動水頭修正為：h_eff = h − h_cap − h_gas(t)
        """
        return self.h_gas_0 * np.exp(-t_sec / self.tau_co2)

    # ── 幾何 ─────────────────────────────────────────────────────────────────
    def area(self, h):
        """錐形截面積 A(h) = π·(h·tanθ)² [m²]"""
        return np.pi * self._tan2 * h ** 2

    def volume(self, h: float) -> float:
        """錐體體積 V(h) = (π/3)·tan²θ·h³ [m³]"""
        return (np.pi / 3) * self._tan2 * h ** 3

    def h_cap_bed(self, T_K=None):
        """
        床層孔隙的 Young-Laplace 保水頭 [m]。

        What: h_cap_bed(T) = 2σ(T) / (ρ g r_pore)，r_pore = pore_radius_ratio × d32。

        Why:  決定「沒有積水之後，床內水能不能被重力排乾」，亦即殘餘（immobile）
              飽和度有多大：`bed_retention_fraction()` 把它轉成可保水的床高分率。
              此量由 measured PSD 直接算出（Class B），不是可調 closure。
              注意它 **不** 從穿床驅動頭裡扣除（F2 的錯誤）：床層兩端的水頭差
              由邊界條件決定，毛細保水只決定殘餘飽和度。
        """
        if T_K is None:
            T_K = self.T_ref
        r_pore = max(float(getattr(self, "pore_radius_m", 0.0)), 1e-9)
        sigma = self.sigma_water(T_K)
        return 2.0 * sigma / (RHO * G * r_pore)

    def h_free_from_volume(self, V_free):
        """
        由床頂以上自由水體積反解自由水柱高度 [m]。

        What: 解 cone(h_bed + h_free) − cone(h_bed) = V_free，取解析立方根。
        Why:  儲水方程改以體積為狀態後，水位變成後處理量；
              解析反解比 Newton 迭代便宜且在 V_free → 0 時仍精確。
        """
        V = _floor(_as_float(V_free), 0.0)
        h_total = ((V + self.V_bed) * 3.0 / (np.pi * self._tan2)) ** (1.0 / 3.0)
        h_free = _floor(h_total - self.h_bed, 0.0)
        return _scalar_out(h_free)

    def wetted_height(self, S_bed, h_free):
        """
        濕潤錐面對應的等效水位 [m]。

        What: h_wet = h_bed·S_bed^(1/3) + h_free
              （床內以等體積錐面表示潤濕前沿，床頂以上直接加自由水柱）

        Why:  濾杯側面的熱交換面積與 viz 的 `h_mm` 都需要單一「水位」語意。
              注意這裡刻意用「相加」而非 `if S_bed < 1 ... else ...` 的分段式：
              S_bed 是漸近趨近 1 的 ODE 狀態，永遠差一點點才等於 1，
              分段式會讓 h_free 整段被丟掉（實測峰值水位因此卡在 h_bed = 53 mm，
              而不是真值 66.7 mm）。相加形式在 S_bed → 1 時給出 h_bed + h_free，
              在無積水時給出純潤濕前沿，兩端都正確且處處連續。
        """
        S = _clip(_as_float(S_bed), 0.0, 1.0)
        hf = _floor(_as_float(h_free), 0.0)
        h = self.h_bed * S ** (1.0 / 3.0) + hf
        return _scalar_out(h)

    def wetted_area(self, h_total):
        """
        濕潤錐側面積 A_wet(h) = π·r(h)·slant(h) = π·tanθ/cosθ·h² [m²]。

        What: 液體與濾杯實際接觸的側壁面積，隨水位平方成長。
        Why:  濾杯熱交換是界面現象；把面積顯式寫出來，界面熱傳係數 U 才有
              可辯護的物理區間，不必吞掉幾何隨時間的變化。
        """
        h = _floor(_as_float(h_total), 0.0)
        cos_theta = np.cos(np.radians(self.half_angle_deg))
        a = np.pi * (self._tan / max(cos_theta, 1e-12)) * h ** 2
        return _scalar_out(a)

    # ── 修正 [3][8] 有效滲透率（細粉遷移 × 顆粒溶脹）────────────────────────
    def phi_effective(self, sat: float = 1.0, h_free: float | None = None):
        """
        綜合有效孔隙率：溶脹（與顆粒吸水率 sat 有關）+ 壓差壓實（與 h_free 有關，可逆）

        Args:
            sat    : 顆粒吸水飽和度 V_abs / V_full（溶脹的真正驅動量）
            h_free : 床頂以上自由水柱高度 [m]（壓差壓實的驅動量）

        Why: 溶脹來自顆粒吸水，壓實來自床頂的額外壓差；舊版第二參數是總水位 h，
             需在函式內再減一次 h_bed 才得到自由水柱，語意藏在實作裡。
             直接吃 h_free 後，兩個機制各自對應一個可獨立推理的輸入。
             註：此為滲透率用的有效孔隙率；孔隙「儲水容量」一律用名目 φ，
             否則 dφ_eff/dt 會讓水量帳不再精確守恆。
        """
        phi_sw = self.phi - self.delta_phi * sat
        if h_free is not None:
            head_ratio = _clip(max(float(h_free), 0.0) / max(self.h_bed, 1e-12), 0.0, 1.0)
            phi_sw -= self.delta_phi_pressure * head_ratio
        return max(phi_sw, 1e-3 * self.phi)

    def fine_radius(self) -> float:
        """代表性細粉半徑 [m]。"""
        if np.isfinite(getattr(self, "psd_fine_diameter_mean_m", np.nan)):
            return 0.5 * self.psd_fine_diameter_mean_m
        # 無 measured PSD 時以 d32 為尺度：number-based D10 是偵測下限 artifact。
        return 0.5 * self.d32 * self.fine_radius_ratio

    def clogging_bin_profiles(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        由 measured PSD bins 建立堵塞用的 bin-resolved 權重與時間尺度。

        What:
            回傳 throat/deposition 兩組權重，以及 throat 飽和特徵體積與
            deposition 的強度倍率。

        Why:
            堵塞不該只靠單一 aggregate index。喉道卡塞更接近 number-based
            的小顆粒事件；沉積/回填更接近 volume-based 的累積行為。
            直接用每個 PSD bin 的粒徑與形狀，可讓 `k_eff` 真正吃到實測分布。
        """
        d_mm = np.maximum(self.ext_bin_diameter_mid_m * 1e3, 1e-9)
        num_w = np.maximum(getattr(self, "ext_bin_num_fraction", np.ones_like(d_mm)), 0.0)
        vol_w = np.maximum(self.ext_bin_volume_fraction, 0.0)
        aspect = np.maximum(self.ext_bin_aspect_ratio_mean, 1.0)
        roundness = np.maximum(self.ext_bin_roundness_mean, 0.25)

        # ROUNDNESS ≡ 1/aspect_ratio，故 (aspect/roundness)^0.35 ≡ aspect^0.70。
        # 0.70 為未獨立標定的形狀指數（形狀越不規則越容易架橋/卡塞）。
        irregularity = aspect ** 0.70
        # 飽和堵塞核：d ≪ d_throat 時 → 1，d ≫ d_throat 時 → d_throat/d。
        # d_throat 由 PSD 自身的 d32 與孔隙率推得（見 `throat_diameter_from_d32`），
        # 取代舊的 0.45/d、0.55/d magic number。
        d_throat_mm = self.throat_diameter_from_d32(self.d32 * 1e3)
        clog_kernel = 1.0 / (1.0 + d_mm / max(d_throat_mm, 1e-12))
        throat_raw = num_w * irregularity * clog_kernel
        deposition_raw = vol_w * irregularity * clog_kernel

        throat_sum = max(float(np.sum(throat_raw)), 1e-18)
        deposition_sum = max(float(np.sum(deposition_raw)), 1e-18)
        throat_w = throat_raw / throat_sum
        deposition_w = deposition_raw / deposition_sum

        # 小而不規則的顆粒更快卡喉道；以 bin 尺度調整其飽和特徵體積。
        throat_vchar = self.throat_clog_char_vol * np.clip(
            self.ext_bin_diameter_mid_m / max(self.d32, 1e-12), 0.25, 3.0
        )
        # 沉積倍率保留體積主導，但仍受細粉與形狀不規則度調制。
        # 萃取殼層比例不進堵塞 closure：萃取對水力單向耦合
        # （舊的 (1.1 − 0.4·shell_fraction) 因子無出處，EXP-20261007-EXTRACTION-CLOSURE-REWRITE 移除）。
        deposition_mult = (self.d32 / np.maximum(self.ext_bin_diameter_mid_m, 1e-12)) ** 0.35 * irregularity ** 0.20
        if not np.all(np.isfinite(deposition_mult)) or np.any(deposition_mult <= 0.0):
            raise ValueError("clogging deposition multiplier 必須為有限正值；請檢查 PSD bins")
        return throat_w, deposition_w, throat_vchar, deposition_mult

    def k_beta_components(self, V_out: float) -> tuple[float, float]:
        """
        將單一 `k_beta` 拆成 throat clogging 與 deposition 兩條堵塞律。

        What:
            throat_term     = 1 + A_throat * (1 - exp(-V_out / V_char))
            deposition_term = 1 + beta_deposit * V_out

        Why:
            細粉堵塞有兩個時間尺度：
            - 前段是細粉優先卡喉道，應快速飽和
            - 後段是沉積/回填，應隨出液量繼續累積
            這樣 PSD 的 throat / deposition 指標才各自有物理位置。
        """
        V = max(float(V_out), 0.0)
        throat_w = getattr(self, "clog_throat_weights", None)
        deposition_w = getattr(self, "clog_deposition_weights", None)
        throat_vchar = getattr(self, "clog_throat_vchar_m3", None)
        deposition_mult = getattr(self, "clog_deposition_multiplier", None)
        if throat_w is None or deposition_w is None or throat_vchar is None or deposition_mult is None:
            throat_w, deposition_w, throat_vchar, deposition_mult = self.clogging_bin_profiles()
        throat_amp = (
            self.throat_clog_gain
            * max(self.k_beta_throat_coeff, 0.0)
            * max(self.throat_clog_char_vol, 1e-12)
            / max(1.0 - np.exp(-1.0), 1e-12)
        )
        throat_loading = float(np.sum(throat_w * (1.0 - np.exp(-V / np.maximum(throat_vchar, 1e-12)))))
        throat_term = 1.0 + throat_amp * throat_loading

        beta_dep = max(self.k_beta_deposition_coeff, 0.0)
        deposition_factor = float(np.sum(deposition_w * deposition_mult))
        deposition_term = 1.0 + beta_dep * deposition_factor * V
        return throat_term, deposition_term

    def psd_clog_index(self) -> float:
        """
        由 measured PSD 導出的無因次堵塞指數。

        What: `0.65 · throat_clog_index + 0.35 · deposition_clog_index`。
        Why:  兩個分量共用同一個飽和堵塞核 1/(1 + d/d_throat)，差別只在權重：
              throat 用 number fraction（喉道卡塞是事件計數），deposition 用
              volume fraction（沉積回填是體積累積）。0.65/0.35 為未獨立標定的
              分配權重；因為 prior 最終以 `CLOG_INDEX_REF` 正規化，只有不同 PSD
              之間的相對排序會進入模型。
              刻意不使用 `psd_fines_num_*`：number-based fines fraction 直接受
              影像偵測下限鉗制（低倍率掃描會系統性少算），是量測 artifact。
        """
        throat = getattr(self, "psd_throat_clog_index", np.nan)
        deposition = getattr(self, "psd_deposition_clog_index", np.nan)
        if not (np.isfinite(throat) and np.isfinite(deposition)):
            return float("nan")
        return float(0.65 * throat + 0.35 * deposition)

    def k_beta_prior_from_psd(self) -> float:
        """
        由 measured PSD 導出 `k_beta` 的 soft prior 中心值 [m⁻³]。

        What:
            `prior = KBETA_PRIOR_REF · (clog_index / CLOG_INDEX_REF)`。

        Why:
            舊實作的 prior 正比於 `self.k_beta` 本身、再 clip 到 `k_beta` 的
            0.45–2.8 倍，等於「以待估參數為自己的先驗中心」——這是循環的，
            對 regularization 沒有任何約束力。改為錨在一個絕對 reference：
            `KBETA_PRIOR_REF` 是 canonical fit 的 `k_beta`，`CLOG_INDEX_REF`
            是同一份 PSD 的 clog_index，兩者一起定義「這個堵塞指數對應多大的
            k_beta」。換 PSD 時 prior 隨 clog_index 線性移動，與 `k_beta` 無關。
            指數取 1.0（線性）：目前沒有支持任何非線性的 identifiability 證據。
        """
        clog_index = self.psd_clog_index()
        if not np.isfinite(clog_index) or clog_index <= 0.0:
            return float(self.k_beta)
        return float(KBETA_PRIOR_REF * (clog_index / CLOG_INDEX_REF))

    def post_bloom_gate(self, t_sec: float, bloom_end_s: float | None) -> float:
        """
        bloom 後濕床修正啟用門檻。

        What: 回傳 0–1 的平滑 gate；bloom 前關閉，bloom 後快速打開。
        Why:  未飽和到濕床的過渡只屬於 bloom；後段重排應獨立於 sat。
        """
        if bloom_end_s is None:
            return 0.0
        width = 1.0
        return 1.0 / (1.0 + np.exp(-(t_sec - bloom_end_s) / width))

    def wetbed_postbloom_factor(
        self,
        q_in: float,
        u_pore: float,
        h_free: float,
        t_sec: float,
        bloom_end_s: float | None,
    ) -> float:
        """
        bloom 後濕床重排修正乘子。

        What:
            f_post = f_rev(u, h_free) * f_irr(q_in, u)
            僅在 bloom 後生效，且上限/下限夾住以保數值穩定。

        Why:
            Darcy 本身不描述粉床因水流而局部重排；
            這個乘子用來補足 bloom 後的濕床壓實/即時沉積。
        """
        gate = self.post_bloom_gate(t_sec, bloom_end_s)
        if gate <= 1e-6:
            return 1.0

        h_drive = max(float(h_free), 0.0)
        u_pos = max(_finite_or_zero(u_pore), 0.0)
        q_pos = max(_finite_or_zero(q_in), 0.0)

        S_u = u_pos / (u_pos + self.wetbed_rev_u_half)
        # 可逆壓實由床頂的額外壓差驅動，因此用自由水柱 h_free。
        # 舊版用總水位 h（含 h_bed）當代理量，在 h_free = 0 時仍給出 S_h ≈ 0.84，
        # 等於宣稱「沒有任何超壓時床層仍被壓實」——這只是把常數阻力藏進可逆項。
        S_h = h_drive / (h_drive + self.wetbed_rev_h_half)
        f_rev = 1.0 / (1.0 + self.wetbed_rev_gain * S_u * S_h)

        J_post = _clip(q_pos / self.wetbed_irr_qin_ref, 0.0, 1.0) \
               * _clip(u_pos / self.wetbed_irr_u_ref, 0.0, 1.0)
        f_irr = 1.0 / (1.0 + self.wetbed_irr_gain * J_post)

        f_mix = f_rev * f_irr
        # gate=0 → 1；gate=1 → f_mix
        f_gate = 1.0 - gate * (1.0 - f_mix)
        return float(_clip(f_gate, 0.2, 1.0))

    # NOTE: 已刪除 `d_wetbed_struct_dt` / `wetbed_struct_factor` /
    # `wetbed_struct_throat_term`（P0/P1 refactor）。
    # χ 動力學被併入 `wetbed_postbloom_factor`（其 f_irr 與舊 throat_struct
    # 物理敘事重複），且 identifiability log 顯示其自由度為平 ridge。

    def d_preferential_flow_dt(
        self,
        pref_state: float,
        q_in: float,
        pour_impact: float,
        t_sec: float,
        bloom_end_s: float | None,
    ) -> float:
        """
        bloom 後偏流快路徑的動態方程。

        What:
            dξ_pref/dt = build(impact, q_in) - decay(ξ_pref)

            ξ_pref ∈ [0, 1]：
            - ξ_pref ↑：每一注開始時中心沖擊打開局部快路徑
            - ξ_pref ↓：沖擊消退後，通道在幾秒內重新閉合

        Why:
            單一路徑 Darcy 只能給出單一時間尺度，容易把每次脈衝注水過度平滑化。
            這個狀態就是把「快響應」獨立出來，而不是再往 `k_eff` 疊乘子。

        非作用態 gate（F6d）：
            What: `pref_flow_coeff <= 0` 時直接回傳 0，ξ_pref 停在初值不演化。
            Why:  coeff = 0 時 `q_preferential` 恆為 0，ξ_pref 對任何物理量都沒有作用；
                  但只要 `pref_flow_open_rate > 0`，它仍在每一注有快速暫態，並參與
                  RK45 的誤差估計 → 改變步長序列 → 改變水力解的離散誤差。
                  F6c §3.2 實測：同一組物理參數只因 open_rate 0 ↔ 0.254 就讓 canonical
                  χ² 差 8.05（rtol 1e-6），fit 與 benchmark reload 因此不可比。
                  沒有物理作用的狀態不該影響求解器，這裡讓「惰性」在數值上也成立。
        """
        if float(self.pref_flow_coeff) <= 0.0:
            return 0.0
        gate = self.post_bloom_gate(t_sec, bloom_end_s)
        if gate <= 1e-6:
            return 0.0

        xi = _clip(float(pref_state), 0.0, 1.0)
        q_pos = max(_finite_or_zero(q_in), 0.0)
        S_q = q_pos / (q_pos + self.pref_flow_qin_half)
        S_impact = _clip(float(pour_impact), 0.0, 1.0)
        build = gate * self.pref_flow_open_rate * S_impact * S_q * (1.0 - xi)
        decay = gate * xi / max(self.pref_flow_tau_decay, 1e-6)
        return build - decay

    def q_preferential(
        self,
        h_free,
        pref_state,
        T_K=None,
        t_sec: float = 0.0,
        sat=None,
        bloom_end_s: float | None = None,
    ):
        """
        bloom 後偏流快路徑流量 [m³/s]。

        What:
            Q_pref = Γ_pref · gate_post · wet_gate · ξ_pref · h_eff · μ_ref / μ(T)

        Why:
            這條路徑代表注水脈衝瞬間打開的中心快通道，仍然穿過濕床，
            但它的導通與關閉有自己的時間尺度，不應被硬塞回同一個 Darcy 阻力中。
            預設 `Γ_pref = 0`，因此完全不改變既有流程。
        """
        coeff = max(float(self.pref_flow_coeff), 0.0)
        if coeff <= 0.0:
            base = np.asarray(h_free, dtype=float)
            zeros = np.zeros_like(base, dtype=float)
            return _scalar_out(zeros)

        xi_arr = np.clip(np.asarray(pref_state, dtype=float), 0.0, 1.0)
        gate = self.post_bloom_gate(t_sec, bloom_end_s)
        if sat is None:
            wet_gate = np.zeros_like(xi_arr, dtype=float)
            kr_sat = np.ones_like(xi_arr, dtype=float)
        else:
            wet_gate = np.clip((np.asarray(sat, dtype=float) - 0.85) / 0.15, 0.0, 1.0)
            kr_sat = self.relative_permeability(sat)
        if T_K is None:
            T_K = self.T_brew
        mu_scale = self.mu / self.mu_water(T_K)
        h_eff = self.bed_drive_head(h_free, T_K=T_K, t_sec=t_sec, sat=sat)
        q_pref = coeff * gate * wet_gate * kr_sat * xi_arr * h_eff * mu_scale
        q_pref = np.maximum(q_pref, 0.0)
        return _scalar_out(q_pref)

    def throat_relief_factor(
        self,
        pour_impact: float,
        t_sec: float,
        bloom_end_s: float | None,
    ) -> float:
        """
        每一注起始中心沖擊對喉道阻塞的瞬時 relief。

        What:
            relief = 1 - gate * gain * impact

        Why:
            使用者描述的操作是「每一注開始先用較大力量沖開中心粉床」。
            這比較像短時間打開孔喉，而不是整段注水期間都改變整體床層結構。
            因此只削減 throat 額外阻塞，不碰 deposition。
        """
        gate = self.post_bloom_gate(t_sec, bloom_end_s)
        impact = _clip(float(pour_impact), 0.0, 1.0)
        relief = 1.0 - gate * self.throat_relief_gain * impact
        return float(_clip(relief, 0.25, 1.0))

    def k_eff(
        self,
        V_out,
        sat: float = 1.0,
        h_free: float | None = None,
        q_in: float = 0.0,
        u_pore: float = 0.0,
        t_sec: float = 0.0,
        bloom_end_s: float | None = None,
        pour_impact: float = 0.0,
        clog_terms: tuple[float, float] | None = None,
    ):
        """
        綜合有效滲透率：喉道阻塞 + bloom 後濕床重排 + 沉積（全部加性阻力）× 顆粒溶脹（Kozeny-Carman）

        What:
              k_eff(V_out, sat, h, q_in, u, t, impact)
            = (k / R_total) × k_kc(sat, h)
              R_total = 1 + (throat_eff − 1)
                          + (deposition − 1)
                          + (1/f_post − 1)
              throat_eff = 1 + (throat_irrev − 1) × relief(impact)
              f_post     = f_rev(u, h) · f_irr(q_in, u)，∈ [0.2, 1]
              k_kc       = (φ_eff/φ₀)³ · ((1−φ₀)/(1−φ_eff))²

        Why:
             1. 全加性阻力。Darcy 阻力本質就是各機制相對 baseline 的額外阻力相加。
                先前 `× f_post` 仍為乘性，會在 wetbed 軸上重新製造 ridge，
                與 throat / deposition 的可區分性受損。將 `f_post` 改寫為
                `(1/f_post − 1)` 進總阻力後，三者語意一致：每一項都是
                「這個機制讓阻力增加多少」。
             2. 砍掉 `wetbed_struct_throat_term`。其物理敘事與 `f_irr`
                重複（皆為 bloom 後的「濕床壓實/即時沉積」），且 identifiability log
                已多次記錄 `wetbed_struct_gain × rate` 平 ridge，被迫凍結 rate。
                重複機制不該以兩個自由度同時存在。
             3. `kc` 是 porosity → permeability 的 constitutive 關係，
                屬於介質本身的性質，仍以乘性 outside R_total 表示。
             注意：此次改動會再次偏移 k / k_beta / wetbed_irr_gain / wetbed_rev_gain
                  的校準值，需重新 measured fit。

        `clog_terms`（內部用）：預先算好的 `k_beta_components(V_out)`。
            同一時刻以不同 (q_in, u_pore) 重算 k_eff 時共用，免得重做 bin 加總。

        TODO: 加入攪動項：dk/dt = -beta_agit·Q_in·k（高 Q_in 時細粉遷移更快）
        """
        if clog_terms is None:
            clog_terms = self.k_beta_components(V_out)
        throat_term, deposition_term = clog_terms
        throat_relief = self.throat_relief_factor(pour_impact, t_sec, bloom_end_s)
        throat_eff = 1.0 + (throat_term - 1.0) * throat_relief
        phi_sw = self.phi_effective(sat, h_free)
        kc = (phi_sw / self.phi)**3 * ((1.0 - self.phi) / (1.0 - phi_sw))**2
        f_post = self.wetbed_postbloom_factor(q_in, u_pore, h_free or 0.0, t_sec, bloom_end_s)
        # f_post ∈ [0.2, 1.0]（已被 wetbed_postbloom_factor 內部 clip）。
        # 將乘性 `× f_post` 等價轉為加性 `(1/f_post − 1)`：在 baseline (f_post=1) 時為 0，
        # 與 throat / deposition 的 `(term − 1)` 同構。
        f_post_safe = max(float(f_post), 1e-3)
        resistance_extra = (
            (throat_eff - 1.0)
            + (deposition_term - 1.0)
            + (1.0 / f_post_safe - 1.0)
        )
        resistance_total = 1.0 + resistance_extra
        return self.k / resistance_total * kc

    def psi_eff(self, V_out) -> float:
        """
        旁路衰減修正：Ψ_eff(V) = Ψ0 / (1 + psi_beta·V_out)

        Why: 細粉同樣沉積於濾紙邊緣，逐漸堵塞肋骨旁路通道
             psi_beta < k_beta：旁路堵塞比粉層慢（流速較低，衝擊力小）
        """
        return self.psi / (1.0 + self.psi_beta * V_out)

    # ── 修正 [6] 熱力學方法 ────────────────────────────────────────────────────
    def mu_water(self, T_K: float) -> float:
        """
        依圖擬合的水黏度曲線：μ(T) = μ_ref × μ_rel(T) / μ_rel(T_ref) [Pa·s]

        What:
          1. 先以圖上紅色相對黏滯度曲線擬合 ln(mu_rel(T_C))
          2. 再用 T_ref 正規化，保證 μ(T_ref) = self.mu

        Why:
          使用者指定要以附圖為準，而不是直接套 Andrade 理論式。
          這讓模型中的流速溫度效應直接對齊圖上的經驗曲線。

        純量單筆快取（What / Why）:
          ODE RHS 在同一個 T 下會經由 τ_cap、q_extract、q_bypass、λ_fast/slow 呼叫本式
          約 7 次。快取鍵包含本式的全部輸入（T_K、mu、T_ref、係數），任何一個改變都
          重新計算，因此只是純函數的記憶，不會在原地改參數後回傳過期值。
        """
        scalar = isinstance(T_K, float)
        if scalar:
            key = (T_K, self.mu, self.T_ref, tuple(self.mu_fit_log_coeffs))
            memo = self.__dict__.get("_mu_water_memo")
            if memo is not None and memo[0] == key:
                return memo[1]
        T_C = _clip(T_K - 273.15, 0.0, 100.0)
        T_ref_C = self.T_ref - 273.15
        mu_rel = np.exp(_polyval(self.mu_fit_log_coeffs, T_C))
        mu_rel_ref = np.exp(_polyval(self.mu_fit_log_coeffs, T_ref_C))
        mu = self.mu * mu_rel / max(mu_rel_ref, 1e-12)
        if scalar:
            self._mu_water_memo = (key, mu)
        return mu

    def solute_diffusivity(self, T_K, slow: bool = False):
        """
        自由水中的溶質擴散係數 D_x(T) [m²/s]（Stokes-Einstein）。

        What: `D = k_B·T / (6π·μ(T)·r_x)`，r_x 為 `constant.py` 的
              `SOLUTE_RADIUS_FAST_M` / `SOLUTE_RADIUS_SLOW_M`。
        Why:  這是**整個萃取閉合唯一的溫度相依來源**（除了 C_sat 的平衡上限）。
              舊實作把溫度數了三次：固定 mobility 的 `D = ν_p·k_B·T`（隱含
              D ∝ T 且與黏度無關）、外掛的 `exp(Ea/R(1/T_ref − 1/T))`、
              以及 diffusion 乘子內部再出現一次 D。三者方向不一致
              （真實 D ∝ T/μ(T)，92 → 75 °C 下降 34%；`ν_p k_B T` 只下降 5%），
              且 `Ea_fast/Ea_slow` 在單一 TDS 觀測下不可辨識（AUD-3）。
              Stokes-Einstein 沒有任何可調參數，溫度相依完全由 `mu_water(T)` 決定。
        """
        radius = SOLUTE_RADIUS_SLOW_M if slow else SOLUTE_RADIUS_FAST_M
        return K_B * np.asarray(T_K, dtype=float) / (6.0 * np.pi * self.mu_water(T_K) * radius)

    def effective_diffusivity(self, T_K, slow: bool = False):
        """
        顆粒內有效擴散係數 D_eff = D(T) / τ_tort [m²/s]。

        Why: `tau_tort` 是本閉合唯一的 live closure 參數，代表完整細胞壁與
             顆粒內孔隙曲折造成的阻力，只作用於 slow pool（未破壁核心）；
             fast pool 的破壁層對孔隙液開放，用自由溶液 D（見 `lambda_fast_bins`）。
             它有物理下界 1（不可能快過自由水擴散）。
        """
        return self.solute_diffusivity(T_K, slow=slow) / max(float(self.tau_tort), 1.0)

    def lambda_fast_bins(self, T_K) -> np.ndarray:
        """
        fast pool 的 bin-resolved 一階釋放速率 λ_fast,i [1/s]。

        What: `λ_fast,i = π² · D_fast(T) / (2δ_i)²`，δ_i = 破壁殼層厚度，
              D_fast 為自由溶液 Stokes-Einstein 擴散係數（**不除以 τ_tort**）。
              這是**內面封閉殼層**（sealed-face slab）的首特徵值：殼層外側對
              孔隙液開放、內側被未破壁核心封住，等效擴散半長度是 2δ 而非 δ。
        Why:  Crank 球形擴散解的首項給出 `M(t)/M_∞ = 1 − (6/π²)Σ n⁻² e^(−n²π²Dt/a²)`，
              長時間由 n = 1 主導，退化成一階釋放 `dM/dt = −λ·M`；λ 的分母是
              「擴散路徑的等效半長度平方」。舊實作用的 `exp(−L²/4Dt)` 乘子漸近
              方向**完全相反**：t → ∞ 時它 → 1（速率遞增），而 Crank 的通量是
              遞減的（AUD-3）。這正是 `nw_eta_slow = 118` 這種補償因子的來源。

              尺度約定（2026-09-24 由主控者裁決改採）：fast pool 是厚度 δ 的殼層，
              一面開放、一面 zero-flux，其首特徵值為 `π²D/(2δ)²`。
              **已棄用**先前的「整球約定」`π²D/δ²`——它隱含殼層兩面都對外開放，
              與 `slow` 池共用同一顆核心的幾何自相矛盾。兩個約定相差 4×，
              而這個 O(1) 因子與 `tau_tort` 完全簡併：換約定後同一物理狀態
              報出的 `tau_tort` 會除以 4（F3 的 25.5 → 6.4），因此
              `EXTRACTION_FIT_SPEC` 的 prior 中心 5.0（文獻曲折度 2–10）
              現在才與模型同一個尺度。
        """
        # 破壁細胞對孔隙液開放，沒有細胞壁阻擋；τ_tort 只屬於 slow pool
        # （EXP-20261007-EXTRACTION-CLOSURE-REWRITE）。
        D_free = self.solute_diffusivity(T_K, slow=False)
        delta = np.maximum(self.ext_bin_shell_depth_m, 1e-12)
        return np.pi ** 2 * D_free / (2.0 * delta) ** 2

    def lambda_slow_bins(self, T_K) -> np.ndarray:
        """
        slow pool 的 bin-resolved 一階釋放速率 λ_slow,i [1/s]。

        What: `λ_slow,i = π² · D_eff,slow(T) / R_core,i²`，R_core = R_i − δ_i。
        Why:  slow pool 就是「未破壁核心」這顆球，溶質須穿過完整細胞壁，
              阻擋由 `tau_tort` 表示。Crank 首項的特徵值是
              `π²D/a²`（a = 球半徑）。因此 λ_slow,i ∝ 1/R_core,i²——
              粗顆粒慢、細顆粒快，bin 之間的相對次序由幾何唯一決定，
              不像舊的 `exp(−L²/4Dt)` 會在不同 t 把次序翻過來（AUD-3）。
        """
        D_eff = self.effective_diffusivity(T_K, slow=True)
        core = np.maximum(self.ext_bin_core_radius_eff_m, 1e-12)
        return np.pi ** 2 * D_eff / core ** 2

    # ── 修正 [1][9] 達西萃取（C∞ 平滑過渡 + 毛細管壓門檻） ──────────────────
    def q_extract(self, h_free, k_val=None, T_K=None, t_sec: float = 0.0, sat=None, drive=None):
        """
        壓力頭收支版達西萃取流量 [m³/s]。

        What:
            Q_ext = kr(sat) · Φ(T) · k · L_bed · h_eff
            Φ(T) = π·tan²θ·ρg / μ(T)
            L_bed = h_bed
            等價寫法：
            Q_ext = kr(sat) · k · A_ref · ρg · h_eff / (μ(T) · L_bed)
            A_ref = π·tan²θ·h_bed²
            h_eff = softplus_like(h - h_cap - h_gas(t))

            其中：
            - h                 : 重力驅動水頭（h_free + S_mob·h_bed，見 `bed_drive_components`）
            - h_cap             : 低水位毛細截止頭
            - h_gas(t)          : CO₂ 背壓等效水頭

        Why:
            把所有流動機制都放回「有效壓力頭」的同一語言中，避免：
            1. 用 smooth(h) 和 cap_factor 對低水位重複抑制
            2. 用乘法增益難以判斷各機制究竟是在改變驅動頭，還是改變介質性質
            3. 幾何上以固定粉床參考截面 A_ref、固定路徑長 L_bed=h_bed
               表示濕床主導的工程簡化，而非讓截面隨瞬時水位 h 改變
            同時將 `kr(sat)` 顯式放入 Darcy 主流量，讓 `h_eff` 只負責驅動頭、
            `kr(sat)` 只負責連通液相比例，兩者不再混成同一個 cutoff。

        假設適用範圍（流動截面尺度）:
            本式以固定參考截面 A_ref = π·tan²θ·h_bed² 表示通量，等價於假設
            自由水位 h 大致座落在 h ≈ h_bed 的等效錐面附近。core.simulate_brew
            的儲水方程改用瞬時 A(h) = π·tan²θ·h²，因此當 h ≪ h_bed（如沖煮
            末段水位接近排空）時，q_extract 相對 storage 邏輯會以
            (h/h_bed)² 的量級高估出口流量。
            Kinu29 light / 20 g / h_bed=5.3 cm / 180 s 基準下實測：
            ratio = A(h)/A_ref 中位數 ≈ 0.72，最大 ≈ 1.26，
            僅 ~22% 模擬時間落在 h < 0.5·h_bed、~6% 落在 h < 0.2·h_bed。
            主沖煮段誤差 < 30%，僅 drain tail 短暫區間 (h/h_bed)² → 0
            時局部高估明顯，但該段 h_eff 也已接近 0，絕對流量影響有限。

        `drive`（內部用）：`q_extract_drive()` 的回傳值；給定時忽略 T_K / t_sec / sat。
        """
        if k_val is None:
            k_val = self.k
        if drive is None:
            drive = self.q_extract_drive(h_free, T_K, t_sec, sat=sat)
        kr_phi_T, h_eff = drive
        return kr_phi_T * k_val * self.h_bed * h_eff

    def q_extract_drive(self, h_free, T_K=None, t_sec: float = 0.0, sat=None):
        """
        `q_extract` 中與 k 無關的兩個因子：(kr(sat)·Φ(T), h_eff)。

        Why: 同一時刻 `flow_state` 以兩個不同的 k（u_proxy 迭代）各算一次 Q_ext；
             驅動頭分解與 kr 只取決於 (h_free, T, t, sat)，算一次後經 `drive=` 共用。
             乘法順序與合併前的 `kr·Φ·k·h_bed·h_eff` 相同，結果逐位元一致。
        """
        if T_K is None:
            T_K = self.T_brew
        phi_T = self.phi_darcy * (self.mu / self.mu_water(T_K))
        h_eff = self.bed_drive_head(h_free, T_K=T_K, t_sec=t_sec, sat=sat)
        kr_sat = 1.0 if sat is None else self.relative_permeability(sat)
        return kr_sat * phi_T, h_eff

    def C_sat_T(self, T_K: float) -> float:
        """
        溫度相依的飽和濃度：C_sat(T) = C_sat_ref·(1 + α·(T - T_ref)) [g/L]

        Why: 溶解度為溫度正函數（吸熱溶解）；
             83°C 的萃取天花板比 99°C 低，復現冷萃 vs 熱沖的化學差異。
        """
        return self.C_sat * (1.0 + self.alpha_C_sat * (T_K - self.T_ref))

    def C_sat_fast_T(self, T_K: float) -> float:
        """Fast 組分溫度相依平衡濃度"""
        return self.C_sat_fast * (1.0 + self.alpha_C_fast * (T_K - self.T_ref))

    def C_sat_slow_T(self, T_K: float) -> float:
        """Slow 組分溫度相依平衡濃度；alpha 較大，苦味跳變效應"""
        return self.C_sat_slow * (1.0 + self.alpha_C_slow * (T_K - self.T_ref))

    # ── 修正 [2][9] 旁路（消散型 + V 衰減 + μ(T) + 毛細管門檻） ──────────────
    def q_bypass(self, h_free, psi_val=None, T_K=None):
        """
        帶消散係數的旁路流量 [m³/s]，含溫度修正與毛細管壓門檻。

        What: Q_bp = Ψ·h_free·shape(h_free)·activation(h_free)·(μ_ref/μ(T))
              h_free = max(0, h - h_bed)

        Why（低水位近零）:
             當自由水柱還很低時，水主要穿過粉床而非沿濾紙肋骨形成穩定旁路；
             因此旁路應接近零，而不是只因總水位 > 0 就線性出現。
        Why（高水位打開）:
             當自由水柱高於粉床頂部一段距離後，沿壁面/肋骨的偏流路徑才會快速形成，
             用 sigmoid 啟動函數可平滑表現這個轉折。
        Why（μ 縮放）: Poiseuille 流 Q ∝ 1/μ；與 Q_ext 同比例縮放，
             旁路「比例」由 h 主導，不被 T 扭曲（修正了 v5 的物理悖論）。
        """
        if psi_val is None:
            psi_val = self.psi
        if T_K is None:
            T_K = self.T_brew
        # 毛細管壓門檻（與 q_extract 一致的 sigmoid 截止，寬度 0.25）
        h_free_arr = _floor(_as_float(h_free), 0.0)
        cap_factor = 1.0 / (1.0 + np.exp(-(h_free_arr - self.h_cap) / (self.h_cap * 0.25)))
        activation = 1.0 / (1.0 + np.exp(-(h_free_arr - self.bypass_onset_head) / self.bypass_onset_width))
        shape = _clip(h_free_arr / max(0.5 * self.h_bed, 1e-12), 0.0, 1.0)  # h_free_arr ≥ 0，下界不作用
        mu_scale = self.mu / self.mu_water(T_K)
        return psi_val * h_free_arr * shape * activation * mu_scale * cap_factor

    def q_total(
        self,
        h_free,
        k_val=None,
        psi_val=None,
        T_K=None,
        t_sec: float = 0.0,
        sat=None,
        pref_state: float = 0.0,
        bloom_end_s: float | None = None,
    ):
        """總出水流量 [m³/s]（`h_free` = 粉床頂部以上自由水柱高度）"""
        q_bulk = self.q_extract(h_free, k_val, T_K, t_sec, sat=sat)
        q_pref = self.q_preferential(h_free, pref_state, T_K=T_K, t_sec=t_sec, sat=sat, bloom_end_s=bloom_end_s)
        return q_bulk + q_pref + self.q_bypass(h_free, psi_val, T_K)

    # ── k–M 聯動：研磨度工廠方法 ───────────────────────────────────────────
    @classmethod
    def for_grind(cls, k_target: float, base: "V60Params | None" = None) -> "V60Params":
        """
        以研磨度 k 為軸，聯動調整 max_EY（legacy 便利工廠）。

        What: 返回以 k_target 為滲透率的新 V60Params：
              max_EY(k) = max_EY_ref × (k_ref / k)^alpha_EY

        Why（物理耦合）:
              k ∝ d²（Kozeny-Carman）—— k 是粒徑的流體代理變數；
              磨細（k↓）造成更多細胞壁破裂 → 可及溶質總量 max_EY↑。

        F3（2026-09-24）：移除同時縮放 `k_ext_coef` 的那一行（該欄位已不存在）。
              萃取**速率**現在完全由 measured PSD 的幾何（δ_i、R_core,i）決定，
              而 PSD 的研磨度平移入口是 `psd_diameter_scale`（F1）——
              有 measured PSD 時請改用它，本方法只適用於沒有 PSD 的粗略掃描。

        Args:
            k_target : 目標滲透率 [m²]，代表研磨粗細
            base     : 參考基底（None → 使用預設中研磨參數）

        Returns:
            新的 V60Params，k 與 max_EY 已按聯動公式修正。
        """
        if base is None:
            base = cls()
        ratio = base.k_ref / k_target
        return dataclasses.replace(
            base,
            k      = k_target,
            max_EY = base.max_EY * (ratio ** base.alpha_EY),
        )

    @classmethod
    def for_roast(
        cls,
        profile: "RoastProfile",
        k_target: float | None = None,
        base: "V60Params | None" = None,
    ) -> "V60Params":
        """
        以烘焙度 RoastProfile 為軸，調整所有相關物理係數。

        What: 套用 profile 的組成/動力學/吸水特性至 base（或預設中研磨參數）；
              若提供 k_target，則額外套用 k-M 聯動（for_grind）。

        Why:  烘焙度與研磨度是正交的兩個自由度：
              - for_roast() 設定烘焙度的「基準面」（max_EY、C_sat_slow、吸水率…）
              - for_grind() 在該基準面上沿研磨度軸縮放
              兩者可單獨使用，或串聯使用。

        Args:
            profile  : RoastProfile 實例（推薦使用 RoastProfile.LIGHT/MEDIUM/DARK）
            k_target : 目標研磨滲透率 [m²]（None → 不改變 k，使用 base.k）
            base     : 參考基底（None → 使用預設中研磨參數）

        Returns:
            新的 V60Params，所有烘焙相關參數已更新；
            若 k_target 不為 None，則同時套用 k-M 聯動。
        """
        if base is None:
            base = cls()

        # 1. 套用烘焙度決定的參數（覆蓋 base 中對應欄位）
        roasted = dataclasses.replace(
            base,
            max_EY            = profile.max_EY,
            alpha_EY          = profile.alpha_EY,
            C_sat_slow        = profile.C_sat_slow,
            T_brew            = profile.brew_temp_K,
            absorb_dry_ratio  = profile.absorb_dry_ratio,
            absorb_full_ratio = profile.absorb_full_ratio,
            h_gas_0           = profile.co2_pressure_m,   # 修正 [14]
        )

        # 2. 若指定研磨度，在已更新的烘焙基準上套用 k-M 聯動
        if k_target is not None:
            return cls.for_grind(k_target, base=roasted)
        return roasted


# ─────────────────────────────────────────────────────────────────────────────
#  注水協議
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class PourProtocol:
    """
    注水計畫。

    What:
        支援兩種等價表示：
        1. `pours`：分段常流率事件 `(start_s, volume_ml, duration_s)`
        2. `cumulative_profile`：累積注水量曲線 `(time_s, cumulative_ml)`

    Why:
        實測資料常先拿到 `V_in(t)`，而不是乾淨的段落式 recipe。
        直接接受累積曲線，能讓 ODE 使用者的真實注水節奏，而不是再人工切段。
    """
    pours: List[Tuple[float, float, float]] = field(default_factory=list)
    cumulative_profile: List[Tuple[float, float]] = field(default_factory=list)

    @classmethod
    def standard_v60(cls) -> "PourProtocol":
        """標準三段式 V60（340mL，1:17 粉水比，20g 粉）"""
        return cls(pours=[
            (  0,  60,  6),
            ( 45, 170, 23),
            (100, 110, 16),
        ])

    @classmethod
    def single_pour(cls) -> "PourProtocol":
        return cls(pours=[(0, 300, 30)])

    @classmethod
    def my_recipe(cls) -> "PourProtocol":
        """
        實測五段式 V60（IMG_3244.mov，300mL，20g 粉，93°C）。

        數據來源：影片逐秒電子秤讀數，以秤上計時器為基準。
        注意：注水期間秤重含動能干擾，暫停期間數值才代表靜態液量。

        段次  開始(s)  水量(mL)  持續(s)  流速(mL/s)
        Bloom    0       47       9        5.2
        Pour2   30       75      13        5.8
        Pour3   52       49       8        6.1
        Pour4   71       71       9        7.9
        Pour5   97       62       8        7.8
        合計            304 ≈ 300mL
        """
        return cls(pours=[
            (  0,  47,  9),   # 悶蒸：0–9s，~47mL
            ( 30,  75, 13),   # 第二注：30–43s，~75mL
            ( 52,  49,  8),   # 第三注：52–60s，~49mL
            ( 71,  71,  9),   # 第四注：71–80s，~71mL
            ( 97,  62,  8),   # 第五注：97–105s，~62mL
        ])

    @classmethod
    def from_cumulative_profile(
        cls,
        points: List[Tuple[float, float]],
    ) -> "PourProtocol":
        """
        由累積注水曲線建立注水協議。

        What: 接受 `(time_s, cumulative_ml)` 節點，內部以分段線性 `V_in(t)` 表示。
        Why:  影片/秤重資料通常先得到累積量，這比人工切段更貼近真實注水節奏。
        """
        if len(points) < 2:
            raise ValueError("cumulative_profile 至少需要 2 個點")
        pts = sorted((float(t), float(v)) for t, v in points)
        times = [t for t, _ in pts]
        if any(t1 <= t0 for t0, t1 in zip(times[:-1], times[1:])):
            raise ValueError("cumulative_profile 的時間必須嚴格遞增")
        vols = np.maximum.accumulate([v for _, v in pts]).tolist()
        return cls(cumulative_profile=list(zip(times, vols)))

    def cumulative_volume_ml(self, t: float) -> float:
        """
        回傳時刻 `t` 的累積注水量 [mL]。

        Why: 統一 `pours` 與 `cumulative_profile` 的查詢介面，便於擬合與診斷。
        """
        if self.cumulative_profile:
            pts = self.cumulative_profile
            if t <= pts[0][0]:
                return pts[0][1]
            for (t0, v0), (t1, v1) in zip(pts[:-1], pts[1:]):
                if t0 <= t < t1:
                    alpha = (t - t0) / max(t1 - t0, 1e-12)
                    return v0 + alpha * max(v1 - v0, 0.0)
            return pts[-1][1]

        total = 0.0
        for start, vol_ml, dur in self.pours:
            if t <= start:
                continue
            if t >= start + dur:
                total += vol_ml
            else:
                total += vol_ml * (t - start) / max(dur, 1e-12)
        return total

    def first_pour_volume_ml(self) -> float:
        """
        第一段有效注水量 [mL]。

        Why: 核心模型的初始熱衝擊需要一個「首注量級」來估算粉水混合溫度。
        """
        if self.cumulative_profile:
            pts = self.cumulative_profile
            for (t0, v0), (t1, v1) in zip(pts[:-1], pts[1:]):
                dv = max(v1 - v0, 0.0)
                if dv > 1e-9:
                    return dv
            return 0.0
        if self.pours:
            return self.pours[0][1]
        return 0.0

    def bloom_end_time(self, min_increment_ml: float = 0.5) -> float:
        """
        回傳 bloom 結束時刻 [s]。

        What:
            將 bloom 定義為「第一注開始，到第二次明確注水開始前」。

        Why:
            未飽和到濕床的過渡只應存在於 bloom。
            後續各注應視為已浸濕床層中的 Darcy 流，而不是再次潤濕乾粉。
        """
        if self.cumulative_profile:
            pts = self.cumulative_profile
            active_seen = False
            pause_seen = False
            for (t0, v0), (t1, v1) in zip(pts[:-1], pts[1:]):
                dv = max(v1 - v0, 0.0)
                if not active_seen and dv >= min_increment_ml:
                    active_seen = True
                    continue
                if active_seen and not pause_seen and dv < min_increment_ml:
                    pause_seen = True
                    continue
                if pause_seen and dv >= min_increment_ml:
                    return t0
            return self.last_pour_end()

        if len(self.pours) >= 2:
            return self.pours[1][0]
        return self.last_pour_end()

    def pour_start_times(self, min_increment_ml: float = 0.5) -> List[float]:
        """
        所有有效注水段的開始時刻 [s]。

        What: 從 `pours` 或 `cumulative_profile` 萃取每一注的起點。
        Why:  濕床重排不只看注水量，還要看每一注開始時的中心沖擊。
        """
        if self.cumulative_profile:
            starts: List[float] = []
            pouring = False
            for (t0, v0), (t1, v1) in zip(self.cumulative_profile[:-1], self.cumulative_profile[1:]):
                dv = max(v1 - v0, 0.0)
                active = dv >= min_increment_ml
                if active and not pouring:
                    starts.append(float(t0))
                pouring = active
            return starts
        return [float(start) for start, _, _ in self.pours]

    def pour_start_impact(
        self,
        t: float,
        bloom_end_s: float | None = None,
        width_s: float = 2.0,
        min_increment_ml: float = 0.5,
        starts: List[float] | None = None,
    ) -> float:
        """
        每一注起始沖擊的脈衝包絡。

        What:
            對每一個注水開始時刻 `t_start`，建立 `exp(-(t-t_start)/width)` 脈衝，
            並取所有 post-bloom 注水的最大值。

        Why:
            使用者實際操作會在每一注開始時用較大力量沖開中心粉床；
            這個瞬間效應不應被平均成整段注水的恆定流率。

        `starts`（內部用）：預先算好的 `pour_start_times(min_increment_ml)`。
            注水起點只取決於協議本身，ODE RHS 每步重掃整條累積曲線是純開銷；
            `simulate_brew` 在積分前算一次後傳入。
        """
        if width_s <= 0:
            return 0.0
        if starts is None:
            starts = self.pour_start_times(min_increment_ml=min_increment_ml)
        if bloom_end_s is not None:
            starts = [s for s in starts if s >= bloom_end_s - 1e-9]
        impact = 0.0
        for start in starts:
            if t < start:
                continue
            impact = max(impact, float(np.exp(-(t - start) / width_s)))
        return impact

    def pour_rate(self, t: float) -> float:
        """瞬時注水流量 [m³/s]"""
        if self.cumulative_profile:
            pts = self.cumulative_profile
            if t < pts[0][0] or t >= pts[-1][0]:
                return 0.0
            for (t0, v0), (t1, v1) in zip(pts[:-1], pts[1:]):
                if t0 <= t < t1:
                    return max(v1 - v0, 0.0) / max(t1 - t0, 1e-12) * 1e-6
            return 0.0
        rate = 0.0
        for start, vol_ml, dur in self.pours:
            if start <= t < start + dur:
                rate += vol_ml / dur
        return rate * 1e-6

    def rate_breakpoints(self) -> List[float]:
        """
        注水率（與注水起點衝擊 `pour_start_impact`）可能跳動的所有時刻 [s]，升冪、不重複。

        What: `cumulative_profile` 的全部節點；`pours` 的每段起點與終點。
        Why:  `pour_rate` 是分段常數、衝擊項在注水起點由 0 跳到 1。ODE 積分若跨過這些跳點，
              自適應步長落在跳點哪一側會隨參數的極小擾動翻轉，χ² 因而帶 ±0.07–0.17 的路徑
              噪音與 −0.03…−0.06 的截斷偏差（F13-C）。`simulate_brew` 以此在斷點間分段積分。
        """
        if self.cumulative_profile:
            return sorted({float(t) for t, _ in self.cumulative_profile})
        return sorted({float(x) for start, _, dur in self.pours for x in (start, start + dur)})

    def last_pour_end(self) -> float:
        """最後一注結束的時間 [s]"""
        if self.cumulative_profile:
            pts = self.cumulative_profile
            last_end = pts[0][0]
            for (t0, v0), (t1, v1) in zip(pts[:-1], pts[1:]):
                if max(v1 - v0, 0.0) > 1e-9:
                    last_end = t1
            return last_end
        return max(start + dur for start, _, dur in self.pours)
