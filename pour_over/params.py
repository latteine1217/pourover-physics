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
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from dataclasses import dataclass, field
from typing import ClassVar, List, Tuple

from .constant import G, H_MIN, K_B, R_GAS, RHO, V60Constant


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
    Why:  烘焙改變豆子的細胞結構（max_EY）、可溶物組成（fast_fraction）、
          萃取動力學（Ea_slow、k_ext_factor）以及 CO₂ 含量（吸水率）。
          這些參數不應由使用者逐一調整，而應透過語意明確的工廠 for_roast() 管理。

    使用方式：
        p = V60Params.for_roast(RoastProfile.LIGHT)
        p = V60Params.for_roast(RoastProfile.DARK, k_target=1.5e-10)
    """
    name: str

    # ── 溶質可萃取性 ───────────────────────────────────────────────────────
    max_EY: float
    # 最大萃取率；淺焙細胞壁緻密（0.22），深焙焦糖化破壁（0.30）

    alpha_EY: float
    # k-M 聯動靈敏度；淺焙硬豆磨細效益有限（0.10），深焙較高（0.20）

    # ── 萃取動力學 ────────────────────────────────────────────────────────
    k_ext_factor: float
    # k_ext_coef 相對倍率（相對於中焙基準 1.0）
    # Why: 深焙糖類分解增加易溶物 → k_ext↑；淺焙有機酸多但細胞壁阻力大 → k_ext↓

    Ea_slow: float
    # Slow 組分活化能 [J/mol]；深焙苦味物質焦化後活化能降低（更易在高溫萃出）

    # ── 組分比例 ──────────────────────────────────────────────────────────
    fast_fraction: float
    # Fast 組分佔比；淺焙含更多有機酸（0.45），深焙苦味物多（0.25）

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
    max_EY            = 0.22,
    alpha_EY          = 0.10,
    k_ext_factor      = 0.80,
    Ea_slow           = 50000.0,
    fast_fraction     = 0.45,
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
    k_ext_factor      = 1.00,
    Ea_slow           = 45000.0,
    fast_fraction     = 0.35,
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
    k_ext_factor      = 1.30,
    Ea_slow           = 38000.0,
    fast_fraction     = 0.25,
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

    sat_rel_perm_residual: float = 0.18
    # 未飽和達西的殘餘飽和度門檻；低於此值時主過床流近乎無法形成連通液相

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

    k_ext_coef: float = 6.0e-7
    # DEPRECATED 2026-05-02：原為單一萃取速率係數 [m³/s]，已被 fast/slow 雙 pool 取代。
    # 主 ODE 路徑（`core.py` rhs）只使用 `k_ext_fast_coef` / `k_ext_slow_coef`（透過
    # `nw_eta_*` 在 __post_init__ 反推），本欄位**不再進入主萃取計算**。
    # 仍保留欄位以維持向後相容性（`for_grind` / `for_roast` / 舊版 `fit_two_stage`
    # / `analysis.sensitivity_analysis` tornado 仍引用），但對 EY/TDS 預測無實質作用。
    # 改用 `k_ext_fast_coef`、`k_ext_slow_coef` 或（經 stage 7 fit 後）`max_EY` 與
    # 對應 `nw_eta` derived 值。subagent 萃取審計 deferred 的 rename 任務會徹底移除。

    max_EY: float = 0.30
    # 最大萃取率（可溶物佔粉重的比例）
    # Why: 決定初始固相溶質量 M_sol_0 = dose_g × max_EY [g]
    #      當 M_sol → 0 時 C_sat_eff → 0，自然終止萃取，修正 C_bed 末端暴增
    # Gagné 實驗依據：手沖可萃取上限 30–32%；中焙取保守值 0.30
    # 舊值 0.28 來自 SCA 測試豆校準，偏保守；修正為物理上限中位估計

    # ── 修正 [6] 熱力學 ────────────────────────────────────────────────────────
    lambda_cool: float = 3.7e-4
    # Newton 冷卻係數 λ [1/s]
    # 估算：典型手沖冷卻 ~1.5°C/min，ΔT_0 = 68°C → λ ≈ 1.5/(60×68) ≈ 3.7e-4
    # FROZEN（2026-04-30）：thermal identifiability scan 顯示此 λ 在 [0.7×, 1.3×]
    # 範圍 cup ΔT swing 僅 0.06 °C（純平 ridge）；保留為預設值，不進入 fitting。

    lambda_liquid_dripper: float = 0.0
    # 液體與濾杯間的等效熱交換係數 [1/s]
    # Why: 補上液體對濾杯持續放熱，而不只在終點把容器當一次性混杯熱沉
    # FIT（2026-04-30）：thermal identifiability scan 顯示此 λ 為熱端最強自由度
    # （cup ΔT swing 0.77 °C），由 `fit_k_kbeta_from_flow_profile` stage 6 校準；
    # `MEASURED_LIQUID_DRIPPER_LAMBDA = 0.02` 改作 initial guess 與弱 prior reg 中心。

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

    Ea_ext: float = 25000.0
    # 萃取活化能 Ea [J/mol]（~25 kJ/mol）
    # Why: 符合擴散控制固液萃取典型範圍（10–40 kJ/mol）
    #      80°C vs 93°C：k_ext 降至 ~74%（定性與杯測感受一致）

    alpha_C_sat: float = 0.003
    # C_sat 溫度係數 [1/K]；C_sat(T) = C_sat_ref·(1+α·(T-T_ref))
    # Why: 溶解度為溫度正函數（吸熱）；0.3%/K 對應典型有機物測量值
    #      使 83°C 萃取天花板低於 99°C，復現冷萃化學差異

    # ── 修正 [7] 多組分萃取 ────────────────────────────────────────────────────
    fast_fraction: float = 0.35
    # Fast 組分佔可溶物比例（有機酸、咖啡因、糖類）
    # Why: Fast 在低 T 易萃，決定明亮感與酸度；Slow 需高 T，帶出苦味

    C_sat_fast: float = 220.0
    # Fast 組分平衡濃度 [g/L]；活性物質分子量小，溶解度較高

    C_sat_slow: float = 80.0
    # Slow 組分平衡濃度 [g/L]；大分子苦味物質溶解度低

    Ea_fast: float = 15000.0
    # Fast 活化能 [J/mol]（~15 kJ/mol）；小分子擴散快，低 T 即可萃出

    Ea_slow: float = 45000.0
    # Slow 活化能 [J/mol]（~45 kJ/mol）；苦味物質需突破高熱障礙
    # Why: 99°C 下 k_ext_slow 比 83°C 高 ~7×，復現「高溫焦苦感」

    alpha_C_fast: float = 0.0015
    # Fast C_sat 溫度係數 [1/K]；小分子，對 T 較不靈敏

    alpha_C_slow: float = 0.006
    # Slow C_sat 溫度係數 [1/K]；苦味跳變：高溫大幅提升苦味溶解上限

    # ── k–M 聯動（The k-M Linkage）─────────────────────────────────────────
    k_ref: float = 6e-11
    # 中研磨參考滲透率 [m²]；聯動公式以此為基準
    # Why: k 是研磨度的流體力學代理變數（k ∝ d²，Kozeny-Carman）
    #      改變 k 即代表改變粒徑 d ∝ k^(1/2)，同步牽動 max_EY 和 k_ext_coef

    alpha_EY: float = 0.15
    # 可及溶質冪次指數：max_EY(k) = max_EY_ref × (k_ref/k)^alpha_EY
    # Why: 磨細 → 更多細胞壁破裂 → 更多可萃取溶質
    #      alpha_EY > 0：k↓（研磨越細）→ max_EY↑
    # 校準：粗(5e-11)→細(5e-12) EY 約 22→30%，alpha≈0.12–0.18（取 0.15）
    # 警告：超過 alpha=0.3 會使模型在細研磨端 EY > 100%（物理不合理）

    alpha_ext: float = 0.30
    # 萃取速率冪次指數：k_ext(k) = k_ext_ref × (k_ref/k)^alpha_ext
    # Why: 磨細 → 粒徑縮短 → 擴散路徑縮短 → k_ext↑
    #      alpha_ext > 0：k↓（研磨越細）→ k_ext↑（更快萃出）
    # 物理估算：k_ext ∝ 1/d² ∝ 1/k（alpha≈1），但實測偏弱，取保守值 0.30

    # ── 修正 [15] 流速依賴傳質係數（邊界層 Sh 效應）────────────────────────────
    k_diff_ratio: float = 0.1
    # 靜置/流動 k_ext 比值；Q_ext=0 時 k_ext_eff = k_diff_ratio × k_ext_T(T)
    # Why: 無流動時邊界層加厚，Sherwood 數降低 ~3-10×；
    #      0.1 = 物理合理估計（靜置僅靠分子擴散，效率約為對流狀態的 10%）
    #      量化影響：60s 悶蒸 EY 貢獻從 +1.31% 降至 ~0.3-0.5%（符合 Gagné 觀測邊界）

    k_ext_fast_coef: float = 6.0e-7 * 2.3
    # Fast 組分萃取基礎速率常數（已合併原 k_ext_coef × k_ext_fast_mult = 2.3 倍）
    # Why: 直接給定單一 base coefficient，避免「base × multiplier」雙自由度退化；
    #      Fast（小分子、酸甜）更依賴對流更新，需要較大基礎速率以維持 SCA 目標 EY 18–22%

    k_ext_slow_coef: float = 6.0e-7 * 0.525
    # Slow 組分萃取基礎速率常數（已合併原 k_ext_coef × k_ext_slow_mult = 0.525 倍）
    # Why: Slow（苦味大分子）在靜置時仍有緩慢累積；保守基礎速率避免長悶蒸過度萃取

    Q_half: float = 3e-7
    # Hill 方程半飽和流速 [m³/s]（= 0.3 mL/s）
    # Why: 邊界層過渡的物理臨界點 ≈ Pe=1，即 v_crit = D/d_p ≈ 1.7e-6 m/s
    #      對應體積流量 ~0.005 mL/s；加上注水擾動效應，工程值取 0.3 mL/s
    #      flow_factor = k_diff_ratio + (1-k_diff_ratio) × Q_ext/(Q_ext+Q_half)
    #      Q_ext = 0.3 mL/s 時 flow_factor = 0.55；Q_ext = 1.5 mL/s 時 = 0.85
    #      舊設 Q_half=1 mL/s 錯誤：把正常滴濾（1-2 mL/s）誤判為半靜置狀態

    # ── 修正 [16] Darcy 毛細驅動飽和（Capillary-driven imbibition）────────────
    tau_cap_ref: float = 10.0
    # 毛細驅動飽和特徵時間 [s]，以 T_ref=93°C 為錨點
    # Why: 乾燥粉床在 Darcy 毛細壓力驅動下自主潤濕；物理公式：
    #      κ(T) ∝ γ(T)/μ(T)（Darcy 毛細通量，Gagné 圖實驗驗證）
    #      dsat/dt|cap = (1-sat) / τ_cap(T)；τ_cap(T) = τ_cap_ref / κ_ratio(T)
    #      τ_cap_ref=10s → 93°C 時純毛細驅動 9s 內達到 ~59% 飽和
    #      高溫（93°C）比低溫（20°C）快 2.8×，復現「高溫水入粉快」的物理現象
    #      注：此項與液壓填充（Q_in/V_absorb）疊加，不是取代

    # ── 修正 [11] Pool 內部驅動力衰減（constant-area Noyes-Whitney）─────────
    beta_access: float = 1.0
    # 單一 pool 內部的驅動力衰減冪次。
    # Why: bin-resolved 框架已透過 fast / slow 雙 pool 結構表達「易出的先走、
    #      難出的後走」這個 aggregate 「末期阻力」現象——
    #      fast pool 短 L、shell-only mass、快耗盡；slow pool 長 L、core mass、慢釋出。
    #      EY(t) 從 [60,90] 區間 ~23 m%/s 衰到 [120,150] 區間 ~1.9 m%/s 已是 12× 衰減，
    #      由 pool 結構自然產生，無需在 pool 內部再疊一次冪次衰減。
    #      因此 pool 內部 driving force 採 constant-area Noyes-Whitney：
    #        C_eff = C_sat(T) × (M/M₀)^1
    #      β > 1 的「pool 內部超線性」沒有對應的物理機制（殼層 200 μm 內無法支撐
    #      super-linear 阻力），且實證 sweep 顯示 β=1.5 反而把 fast pool 拖到 90s 後
    #      仍未耗盡——與杯測「fast 前段出完」的直覺相反。
    # 候選：
    #      β=1.0：constant-area Noyes-Whitney（預設，與 bin-resolved 自洽）
    #      β=2/3：shrinking-core（球形粒子 A ∝ M^(2/3)），可選的更精細形式
    #      β=1.5：歷史值，aggregate-pool 時代的補償，已不再適用

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

    darcy_capillary_c0: float = 0.16663265
    # 已浸濕床層的 Darcy 毛細係數在 0°C 的截距
    # 校準點：a(2°C)=0.18, a(100°C)=0.835

    darcy_capillary_c1: float = 0.00668367
    # 已浸濕床層的 Darcy 毛細係數斜率 [1/°C]
    # 線性式：a(T_C) = 0.16663265 + 0.00668367 * T_C

    darcy_capillary_gain: float = 0.1
    # Darcy 毛細係數對濕床通量的影響強度；作為無因次增益乘子
    # 校準更新：壓力頭收支版 q_extract 下，只保留小幅濕床毛細增益，
    # 避免把通量推得過快而造成 TDS/EY 偏低

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

    shell_thickness: float = 200e-6
    # 可萃取外層厚度 [m]；可及可溶物質量 ∝ 外層殼層體積

    nu_p_fast: float = 1.1e11
    # Einstein-Smoluchowski mobility：Fast 組分 D = ν_p k_B T

    nu_p_slow: float = 4.5e10
    # Slow 組分 mobility 較低，反映大分子/苦味組分擴散較慢

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

    def _load_psd_bin_rows(self, bins_csv_path: str | Path, diameter_scale: float = 1.0) -> list[dict]:
        """
        載入並縮放 multi-bin PSD rows。

        What: 讀入 bins CSV，並把所有長度相關欄位按 `diameter_scale` 同步縮放。
        Why:  measured PSD 要同時服務 D10 對齊、k 反推比例調整，以及後續的 bin-resolved 萃取；
              把縮放邏輯集中，才能保證水力與萃取共用同一組幾何假設。
        """
        path = Path(bins_csv_path)
        scale = max(float(diameter_scale), 1e-9)
        with path.open("r", encoding="utf-8", newline="") as f:
            rows_raw = [{k: float(v) for k, v in row.items()} for row in csv.DictReader(f)]
        if not rows_raw:
            raise ValueError(f"空的 PSD bins CSV：{path}")

        rows_scaled: list[dict] = []
        for row in sorted(rows_raw, key=lambda r: r["d_lo_mm"]):
            scaled = dict(row)
            for key in ("d_lo_mm", "d_hi_mm", "d_mid_mm", "diameter_eq_mean_mm", "diameter_eq_median_mm"):
                scaled[key] = row[key] * scale
            scaled["surface_to_volume_mm_inv_mean"] = row["surface_to_volume_mm_inv_mean"] / scale
            rows_scaled.append(scaled)
        return rows_scaled

    def _particle_stats_from_bins_csv(self, bins_csv_path: str | Path, diameter_scale: float = 1.0) -> dict:
        """
        由 multi-bin PSD CSV 計算粒子子模型統計。

        What:
          1. 從 bins 直接整合 volume_fraction 與各 bin 形狀統計
          2. 計算比表面積、200 μm 殼層可及性與有效擴散路徑
          3. 視需要由 number fraction 直接內插 D10

        Why:
          有實測 PSD 時，這些量不應再由理想碎形分佈近似；
          直接整合 bins 能讓表面積與殼層模型真正落在量測分布上。
        """
        def shell_accessibility_fraction_mm(diameter_mm: float) -> float:
            radius = 0.5 * max(float(diameter_mm), 1e-12)
            shell_mm = min(self.shell_thickness * 1e3, radius)
            core_radius = max(radius - shell_mm, 0.0)
            return 1.0 - (core_radius / radius) ** 3

        rows_sorted = self._load_psd_bin_rows(bins_csv_path, diameter_scale=diameter_scale)
        vol_total = sum(max(r["volume_fraction"], 0.0) for r in rows_sorted)
        if vol_total <= 0:
            raise ValueError(f"PSD bins CSV 的 volume_fraction 總和為 0：{bins_csv_path}")

        num_total = sum(max(r["num_fraction"], 0.0) for r in rows_sorted)
        aspect_mean = sum(max(r["num_fraction"], 0.0) * r["aspect_ratio_mean"] for r in rows_sorted) / max(num_total, 1e-12)
        roundness_mean = sum(max(r["num_fraction"], 0.0) * r["roundness_mean"] for r in rows_sorted) / max(num_total, 1e-12)
        span_num = (
            self._quantile_from_bins_csv(rows_sorted, 0.90, "num_fraction")
            - self._quantile_from_bins_csv(rows_sorted, 0.10, "num_fraction")
        ) / max(self._quantile_from_bins_csv(rows_sorted, 0.50, "num_fraction"), 1e-12)

        surface_area_mm_inv = 0.0
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
            num_w = max(row["num_fraction"], 0.0) / max(num_total, 1e-12)
            d_mean = max(row["diameter_eq_mean_mm"], 1e-9)
            sv_mm_inv = row["surface_to_volume_mm_inv_mean"]
            shell_acc = shell_accessibility_fraction_mm(d_mean)
            core_ratio = max(1.0 - shell_acc, 0.0) ** (1.0 / 3.0)
            core_radius_mm = 0.5 * d_mean * core_ratio
            shell_depth_mm = min(self.shell_thickness * 1e3, 0.5 * d_mean)
            shell_mid_mm = max(0.5 * shell_depth_mm, 1e-9)
            aspect = max(row["aspect_ratio_mean"], 1.0)
            roundness = max(row["roundness_mean"], 0.25)
            irregularity = (aspect / roundness) ** 0.35
            surface_area_mm_inv += vol_w * sv_mm_inv
            surface_area_fast_mm_inv += vol_w * sv_mm_inv * shell_acc
            shell_fraction_vol += vol_w * shell_acc
            diffusion_path_fast_mm += vol_w * shell_acc * shell_mid_mm
            diffusion_path_slow_mm += vol_w * max(1.0 - shell_acc, 0.0) * max(core_radius_mm, shell_mid_mm)
            shell_weight_total += vol_w * shell_acc
            throat_clog_index += num_w * irregularity * min(0.45 / d_mean, 2.0)
            deposition_clog_index += vol_w * irregularity * min(0.55 / d_mean, 1.8)
            fast_reactive_index += vol_w * sv_mm_inv * shell_acc
            slow_reactive_index += vol_w * sv_mm_inv * max(1.0 - shell_acc, 0.0)
            if d_mean < 0.50:
                fine_num_total += num_w
                fine_diameter_acc_mm += num_w * d_mean

        D10_mm = self._quantile_from_bins_csv(rows_sorted, 0.10, "num_fraction")
        D50_mm = self._quantile_from_bins_csv(rows_sorted, 0.50, "num_fraction")
        D90_mm = self._quantile_from_bins_csv(rows_sorted, 0.90, "num_fraction")
        fines_num_lt_0p30 = sum(max(r["num_fraction"], 0.0) for r in rows_sorted if r["d_mid_mm"] < 0.30) / max(num_total, 1e-12)
        fines_num_lt_0p40 = sum(max(r["num_fraction"], 0.0) for r in rows_sorted if r["d_mid_mm"] < 0.40) / max(num_total, 1e-12)
        fines_num_lt_0p50 = sum(max(r["num_fraction"], 0.0) for r in rows_sorted if r["d_mid_mm"] < 0.50) / max(num_total, 1e-12)
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
        將 PSD bins 轉成 bin-resolved 萃取子模型所需的幾何量。

        What:
          對每個 bin 建立：
          - 固體體積分率
          - fast/slow 對應的表面積 A_i
          - fast/slow 的擴散路徑 L_i
          - fast/slow 的質量分配權重

        Why:
          這是把 measured PSD 從「只提供單一 D10」提升成真正可進 ODE 的關鍵；
          之後每個 bin 都能有自己的 A_i、L_i、M_i、C_i，而不是先壓成單一平均量。
        """
        vol_total = sum(max(r["volume_fraction"], 0.0) for r in rows_sorted)
        if vol_total <= 0:
            raise ValueError("PSD bins 的 volume_fraction 總和必須為正")

        V_solid_total = (1.0 - self.phi) * self.V_bed
        area_fast_list: list[float] = []
        area_slow_list: list[float] = []
        path_fast_list: list[float] = []
        path_slow_list: list[float] = []
        fast_reactive: list[float] = []
        slow_reactive: list[float] = []
        num_fraction: list[float] = []
        vol_fraction: list[float] = []
        d_mid_m: list[float] = []
        aspect: list[float] = []
        roundness: list[float] = []
        shell_fraction: list[float] = []

        for row in rows_sorted:
            num_w = max(row["num_fraction"], 0.0)
            vol_w = max(row["volume_fraction"], 0.0) / vol_total
            d_mean_m = max(row["diameter_eq_mean_mm"] * 1e-3, 1e-12)
            shell_acc = float(np.clip(row["shell_accessibility_volume_weighted"], 0.0, 1.0))
            core_ratio = max(1.0 - shell_acc, 0.0) ** (1.0 / 3.0)
            core_radius_m = 0.5 * d_mean_m * core_ratio
            shell_depth_m = min(self.shell_thickness, 0.5 * d_mean_m)
            shell_mid_m = max(0.5 * shell_depth_m, 1e-12)
            sv_m_inv = row["surface_to_volume_mm_inv_mean"] * 1e3
            V_solid_i = V_solid_total * vol_w

            A_total_i = sv_m_inv * V_solid_i
            A_fast_i = A_total_i * shell_acc
            # A_slow_i = core-surface area
            # Why: slow pool 由 core 表面釋出溶質到 bulk，瓶頸在 core surface 而非
            #      整個 particle outer surface。`(1 - shell_acc)^(2/3)` 對應球形
            #      殘存核心的相對 surface area（核心半徑 ∝ (1-shell)^(1/3)，面積 ∝ 半徑²）。
            # 2026-05-01 P0 修正：原 `A_slow_i = A_total_i` 不真實放大 slow 介面，
            #      讓 slow A 比 fast A 還大，與物理直覺相反。subagent 萃取審計指出此問題。
            core_surface_factor = max(1.0 - shell_acc, 0.0) ** (2.0 / 3.0)
            A_slow_i = A_total_i * max(core_surface_factor, 0.05)

            area_fast_list.append(A_fast_i)
            area_slow_list.append(A_slow_i)
            path_fast_list.append(max(0.25 * self.shell_thickness, shell_mid_m))
            path_slow_list.append(max(self.shell_thickness, max(core_radius_m, shell_mid_m)))
            fast_reactive.append(max(A_fast_i, 0.0))
            slow_reactive.append(max(A_total_i * max(1.0 - shell_acc, 0.05), 0.0))
            num_fraction.append(num_w)
            vol_fraction.append(vol_w)
            d_mid_m.append(max(row["d_mid_mm"] * 1e-3, 1e-12))
            aspect.append(max(row["aspect_ratio_mean"], 1.0))
            roundness.append(max(row["roundness_mean"], 0.25))
            shell_fraction.append(shell_acc)

        fast_reactive_arr = np.asarray(fast_reactive, dtype=float)
        slow_reactive_arr = np.asarray(slow_reactive, dtype=float)
        vol_arr = np.asarray(vol_fraction, dtype=float)
        fast_mass_frac = fast_reactive_arr / max(float(np.sum(fast_reactive_arr)), 1e-18)
        slow_mass_frac = slow_reactive_arr / max(float(np.sum(slow_reactive_arr)), 1e-18)

        return {
            "count": len(rows_sorted),
            "num_fraction": np.asarray(num_fraction, dtype=float),
            "volume_fraction": vol_arr,
            "diameter_mid_m": np.asarray(d_mid_m, dtype=float),
            "aspect_ratio_mean": np.asarray(aspect, dtype=float),
            "roundness_mean": np.asarray(roundness, dtype=float),
            "shell_fraction": np.asarray(shell_fraction, dtype=float),
            "area_fast_m2": np.asarray(area_fast_list, dtype=float),
            "area_slow_m2": np.asarray(area_slow_list, dtype=float),
            "path_fast_m": np.asarray(path_fast_list, dtype=float),
            "path_slow_m": np.asarray(path_slow_list, dtype=float),
            "fast_mass_fraction": fast_mass_frac,
            "slow_mass_fraction": slow_mass_frac,
        }

    def _set_extraction_bins(self, bins: dict | None = None) -> None:
        """
        設定萃取 bins 供 ODE 直接使用。

        What:
          - 有 measured PSD bins 時，建立多 bin 幾何與質量權重
          - 否則退化成單一 aggregate bin，維持舊 fast/slow 模型行為

        Why:
          這讓 `core.py` 可以統一用 bin-resolved 狀態更新，而不用分兩套邏輯。
        """
        if bins is None:
            self.extraction_bin_count = 1
            self.ext_bin_area_fast_m2 = np.array([self.noyes_whitney_area(slow=False)], dtype=float)
            self.ext_bin_area_slow_m2 = np.array([self.noyes_whitney_area(slow=True)], dtype=float)
            self.ext_bin_path_fast_m = np.array([self.diffusion_path_fast_m], dtype=float)
            self.ext_bin_path_slow_m = np.array([self.diffusion_path_slow_m], dtype=float)
            self.ext_bin_fast_mass_fraction = np.array([1.0], dtype=float)
            self.ext_bin_slow_mass_fraction = np.array([1.0], dtype=float)
            self.ext_bin_num_fraction = np.array([1.0], dtype=float)
            self.ext_bin_volume_fraction = np.array([1.0], dtype=float)
            self.ext_bin_diameter_mid_m = np.array([self.D10], dtype=float)
            self.ext_bin_aspect_ratio_mean = np.array([getattr(self, "psd_aspect_ratio_mean", 1.0)], dtype=float)
            self.ext_bin_roundness_mean = np.array([getattr(self, "psd_roundness_mean", 1.0)], dtype=float)
            self.ext_bin_shell_fraction = np.array([self.shell_fraction_abs], dtype=float)
            self.M_fast_0_bins = np.array([self.M_fast_0], dtype=float)
            self.M_slow_0_bins = np.array([self.M_slow_0], dtype=float)
            return

        self.extraction_bin_count = int(bins["count"])
        self.ext_bin_area_fast_m2 = np.asarray(bins["area_fast_m2"], dtype=float)
        self.ext_bin_area_slow_m2 = np.asarray(bins["area_slow_m2"], dtype=float)
        self.ext_bin_path_fast_m = np.asarray(bins["path_fast_m"], dtype=float)
        self.ext_bin_path_slow_m = np.asarray(bins["path_slow_m"], dtype=float)
        self.ext_bin_fast_mass_fraction = np.asarray(bins["fast_mass_fraction"], dtype=float)
        self.ext_bin_slow_mass_fraction = np.asarray(bins["slow_mass_fraction"], dtype=float)
        self.ext_bin_num_fraction = np.asarray(bins["num_fraction"], dtype=float)
        self.ext_bin_volume_fraction = np.asarray(bins["volume_fraction"], dtype=float)
        self.ext_bin_diameter_mid_m = np.asarray(bins["diameter_mid_m"], dtype=float)
        self.ext_bin_aspect_ratio_mean = np.asarray(bins["aspect_ratio_mean"], dtype=float)
        self.ext_bin_roundness_mean = np.asarray(bins["roundness_mean"], dtype=float)
        self.ext_bin_shell_fraction = np.asarray(bins["shell_fraction"], dtype=float)
        self.M_fast_0_bins = self.M_fast_0 * self.ext_bin_fast_mass_fraction
        self.M_slow_0_bins = self.M_slow_0 * self.ext_bin_slow_mass_fraction

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
        # 顆粒子模型：優先使用實測 PSD bins；否則退回量測 D10 或理想碎形 PSD。
        measured_bins_native = None
        measured_bin_rows_scaled = None
        if self.psd_bins_csv_path:
            measured_bins_native = self._particle_stats_from_bins_csv(self.psd_bins_csv_path, diameter_scale=1.0)

        if self.D10_measured_m is not None:
            self.D10 = max(float(self.D10_measured_m), self.particle_d_min)
        elif measured_bins_native is not None:
            self.D10 = max(float(measured_bins_native["D10_m"]), self.particle_d_min)
        else:
            self.D10 = np.sqrt(max(self.k, 1e-18) / max(self.f_sp * self.phi**self.eta_porosity, 1e-18))
        self.k_from_D10 = self.f_sp * (self.D10 ** 2) * (self.phi ** self.eta_porosity)
        ref_D10 = np.sqrt(max(self.k_ref, 1e-18) / max(self.f_sp * self.phi**self.eta_porosity, 1e-18))
        if measured_bins_native is not None:
            native_D10 = max(float(measured_bins_native["D10_m"]), self.particle_d_min)
            particle_scale = self.D10 / native_D10
            ref_scale = ref_D10 / native_D10
            particle = self._particle_stats_from_bins_csv(self.psd_bins_csv_path, diameter_scale=particle_scale)
            ref_particle = self._particle_stats_from_bins_csv(self.psd_bins_csv_path, diameter_scale=ref_scale)
            measured_bin_rows_scaled = self._load_psd_bin_rows(self.psd_bins_csv_path, diameter_scale=particle_scale)
        else:
            ref_particle = self._single_bin_particle_stats(ref_D10)
            particle = self._single_bin_particle_stats(self.D10)
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
        # 固相溶質耗盡模型
        # 多組分可萃量分流：
        # - fast pool 主要來自外層較易接觸的可溶物，吃完整 shell penalty
        # - slow pool 代表較深層、較慢釋出的可溶物，受 shell penalty 影響但較弱
        # 2026-05-01 P1 修正：原 slow_access_ratio = 0.5*(1+shell_ratio) 在 shell_ratio→0
        #   時還保留 0.5 floor，物理上不合理（shell 完全堵死時 slow pool 不該還有 50% 可萃）。
        #   改為 `slow_access_ratio = shell_ratio ** alpha_slow_access`，alpha < 1 表示
        #   slow 對 shell penalty 比 fast 弱（fast 是 alpha=1）。預設 alpha=0.7。
        if np.isfinite(self.psd_fast_pool_fraction) and np.isfinite(self.ref_psd_fast_pool_fraction):
            psd_fast_shift = (self.psd_fast_pool_fraction / max(self.ref_psd_fast_pool_fraction, 1e-12)) ** 0.25
        else:
            psd_fast_shift = 1.0
        self.fast_fraction_effective = float(np.clip(self.fast_fraction * psd_fast_shift, 0.12, 0.78))
        fast_access_ratio = self.shell_accessibility_ratio
        # alpha_slow_access = 0.7：slow pool 對 shell penalty 的次方，0=完全免疫、1=和 fast 一樣
        alpha_slow_access = 0.7
        slow_access_ratio = max(self.shell_accessibility_ratio, 1e-6) ** alpha_slow_access
        self.M_fast_0 = self.dose_g * self.max_EY * self.fast_fraction_effective * fast_access_ratio
        self.M_slow_0 = self.dose_g * self.max_EY * (1.0 - self.fast_fraction_effective) * slow_access_ratio
        self.M_sol_0 = self.M_fast_0 + self.M_slow_0
        # κ = C_sat_0 / M_sol_0 [L⁻¹]；C_sat_eff(t) = κ·M_sol(t)
        # 單位：[g/L] / [g] = [1/L]（與 SI：k_ext[m³/s]×C_sat[kg/m³] 一致）
        # dose_g=0（用於 baseline 對比）時退化為純流體模型，不需萃取
        # 保留舊 kappa（單組分，backward compat）
        self.kappa = (self.C_sat / self.M_sol_0) if self.M_sol_0 > 0 else 0.0
        # Noyes-Whitney 參考校準：以中研磨參考幾何反推無因次效率因子
        # k_NW = η * A_eff * D / L，其中 η 吸收 tortuosity / 未建模阻力 / 單位校準
        A_fast_ref = self.noyes_whitney_area(slow=False, use_reference=True)
        A_slow_ref = self.noyes_whitney_area(slow=True, use_reference=True)
        L_fast_ref = self.noyes_whitney_length(slow=False, use_reference=True)
        L_slow_ref = self.noyes_whitney_length(slow=True,  use_reference=True)
        D_fast_ref = self.diffusion_coeff(self.T_ref, slow=False)
        D_slow_ref = self.diffusion_coeff(self.T_ref, slow=True)
        nw_fast_ref = A_fast_ref * D_fast_ref / max(L_fast_ref, 1e-18)
        nw_slow_ref = A_slow_ref * D_slow_ref / max(L_slow_ref, 1e-18)
        self.nw_eta_fast = self.k_ext_fast_coef / max(nw_fast_ref, 1e-18)
        self.nw_eta_slow = self.k_ext_slow_coef / max(nw_slow_ref, 1e-18)
        self.k_beta_prior_psd = self.k_beta_prior_from_psd()
        throat = getattr(self, "psd_throat_clog_index", np.nan)
        deposition = getattr(self, "psd_deposition_clog_index", np.nan)
        throat_ref = getattr(self, "ref_psd_throat_clog_index", np.nan)
        deposition_ref = getattr(self, "ref_psd_deposition_clog_index", np.nan)
        if all(np.isfinite(v) for v in (throat, deposition, throat_ref, deposition_ref)):
            throat_rel = throat / max(throat_ref, 1e-12)
            deposition_rel = deposition / max(deposition_ref, 1e-12)
        else:
            throat_rel = 1.0
            deposition_rel = 1.0
        throat_rel = max(throat_rel, 1e-6)
        deposition_rel = max(deposition_rel, 1e-6)
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
        # κ for each component（溫度相依，在方法中計算；此處存 ref 值）
        self.kappa_fast = (self.C_sat_fast / self.M_fast_0) if self.M_fast_0 > 0 else 0.0
        self.kappa_slow = (self.C_sat_slow / self.M_slow_0) if self.M_slow_0 > 0 else 0.0
        # 咖啡粉等效熱容體積：V_equiv = m_coffee × Cp_coffee / (ρ_water × Cp_water)
        # Why: 悶蒸時乾粉（常溫）吸收熱水熱量，換算為等效水體積後加入熱動方程分母
        #      Cp_water ≈ 4180 J/(kg·K)；dose_g [g] = dose_g×1e-3 [kg]
        self.V_equiv_coffee = self.solid_water_equivalent_ml(self.dose_g, self.Cp_coffee / 1000.0) * 1e-6  # [m³]
        self.V_equiv_dripper = self.solid_water_equivalent_ml(self.dripper_mass_g, self.dripper_cp_J_gK) * 1e-6  # [m³]
        if measured_bin_rows_scaled is not None:
            self._set_extraction_bins(self._build_extraction_bins_from_rows(measured_bin_rows_scaled))
        else:
            self._set_extraction_bins()
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
          - 代表直徑直接取 D10
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
        throat_index = min(0.45 / max(d * 1e3, 1e-9), 2.0)
        deposition_index = min(0.55 / max(d * 1e3, 1e-9), 1.8)
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
            "source": "synthetic_single_bin",
            "diameter_scale": 1.0,
        }

    def saturation(self, V_poured: float) -> float:
        """
        累積注水量對飽和目標的平滑上限 sat_target ∈ [0, 1]。C¹ 連續。

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

    def bed_drive_components(self, h, T_K=None, t_sec: float = 0.0, sat=None) -> dict:
        """
        粉床主流與快路徑共用的驅動頭分解。

        What:
            h_eff = softplus(h - h_threshold_eff + h_cap_wet)

        Why:
            主 Darcy 路徑與偏流快路徑都受同一個床層水頭、
            毛細門檻與 CO₂ 背壓控制；抽成共用 closure 可避免
            雙路徑各自維護一套不一致的壓力頭邏輯。
        """
        if T_K is None:
            T_K = self.T_brew
        h_arr = np.asarray(h, dtype=float)
        T_arr = np.asarray(T_K, dtype=float)
        t_arr = np.asarray(t_sec, dtype=float)
        if sat is None:
            wet_gate = np.zeros_like(h_arr, dtype=float)
        else:
            wet_gate = np.clip((np.asarray(sat, dtype=float) - 0.85) / 0.15, 0.0, 1.0)

        h_threshold = self.h_cap + self.h_gas(t_arr)
        wet_span = np.clip(h_arr / max(self.h_bed, 1e-12), 0.0, 1.0)
        h_cap_wet = (
            self.darcy_capillary_gain
            * self.darcy_capillary_coeff(T_arr)
            * (0.5 * self.h_bed * wet_span)
            * wet_gate
        )
        h_threshold_eff = h_threshold * (1.0 - 0.55 * wet_gate)
        raw_head = h_arr - h_threshold_eff + h_cap_wet
        eps = max(self.h_cap * 0.25, 1e-6)
        h_eff = eps * np.logaddexp(0.0, raw_head / eps)
        return {
            "wet_gate": float(wet_gate) if np.ndim(wet_gate) == 0 else wet_gate,
            "h_threshold": float(h_threshold) if np.ndim(h_threshold) == 0 else h_threshold,
            "h_threshold_eff": float(h_threshold_eff) if np.ndim(h_threshold_eff) == 0 else h_threshold_eff,
            "h_cap_wet": float(h_cap_wet) if np.ndim(h_cap_wet) == 0 else h_cap_wet,
            "raw_head": float(raw_head) if np.ndim(raw_head) == 0 else raw_head,
            "h_eff": float(h_eff) if np.ndim(h_eff) == 0 else h_eff,
        }

    def bed_drive_head(self, h, T_K=None, t_sec: float = 0.0, sat=None):
        """
        粉床主流與快路徑共用的有效驅動水頭。

        What:
            回傳 `bed_drive_components()` 中的 `h_eff`。

        Why:
            讓主流程繼續使用單一標量 closure，同時 diagnostics 可讀取完整分解。
        """
        comps = self.bed_drive_components(h, T_K=T_K, t_sec=t_sec, sat=sat)
        h_eff = comps["h_eff"]
        return float(h_eff) if np.ndim(h_eff) == 0 else h_eff

    def relative_permeability(self, sat):
        """
        未飽和床層的相對滲透率 `kr(sat)`。

        What:
            以 Corey 型 closure 表示：
              S_e = clamp((sat - s_r) / (1 - s_r), 0, 1)
              kr  = smoothstep(S_e) ^ n

        Why:
            `bed_drive_head()` 處理的是壓力頭何時足以推動液體，
            但未飽和 Darcy 還需要一個顯式的導水能力衰減 `kr(sat)`。
            這樣 bloom 前的低飽和區就不再只靠壓力頭 cutoff，
            而是同時反映液相連通度尚未建立的事實。
        """
        sat_arr = np.clip(np.asarray(sat, dtype=float), 0.0, 1.0)
        s_r = np.clip(float(self.sat_rel_perm_residual), 0.0, 0.95)
        if s_r >= 0.999:
            kr = np.zeros_like(sat_arr, dtype=float)
            return float(kr) if kr.ndim == 0 else kr
        s_e = np.clip((sat_arr - s_r) / max(1.0 - s_r, 1e-12), 0.0, 1.0)
        s_smooth = s_e * s_e * (3.0 - 2.0 * s_e)
        kr = np.clip(s_smooth ** max(float(self.sat_rel_perm_exp), 1.0), 0.0, 1.0)
        return float(kr) if kr.ndim == 0 else kr

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
        sigma = np.maximum(1e-3, sigma_ref + slope * (np.asarray(T_K, dtype=float) - self.T_ref))
        return float(sigma) if np.ndim(sigma) == 0 else sigma

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

    def darcy_capillary_coeff(self, T_K: float) -> float:
        """
        已浸濕床層的 Darcy 毛細係數（線性溫度關係）。

        What: 依據使用者提供的圖，採線性近似：
              a(T_C) = a0 + a1 * T_C
              0°C  約 0.18，100°C 約 0.80

        Why: 乾粉浸濕前沿可用 Lucas-Washburn；
             但床層一旦完成浸濕，毛細傳輸改以 Darcy 型係數描述，
             並依圖使用線性溫度關係，而不是 sqrt(t) 前沿律。
        """
        T_C = np.clip(T_K - 273.15, 0.0, 100.0)
        return self.darcy_capillary_c0 + self.darcy_capillary_c1 * T_C

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

    # ── 修正 [3][8] 有效滲透率（細粉遷移 × 顆粒溶脹）────────────────────────
    def phi_effective(self, sat: float = 1.0, h: float | None = None):
        """
        綜合有效孔隙率：溶脹（與 sat 有關）+ 壓差壓實（與 h 有關，可逆）
        """
        phi_sw = self.phi - self.delta_phi * sat
        if h is not None:
            head_ratio = np.clip(max(h - self.h_bed, 0.0) / max(self.h_bed, 1e-12), 0.0, 1.0)
            phi_sw -= self.delta_phi_pressure * head_ratio
        return max(phi_sw, 1e-3 * self.phi)

    def fine_radius(self) -> float:
        """代表性細粉半徑 [m]。"""
        if np.isfinite(getattr(self, "psd_fine_diameter_mean_m", np.nan)):
            return 0.5 * self.psd_fine_diameter_mean_m
        return 0.5 * self.D10 * self.fine_radius_ratio

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
        shell = np.clip(self.ext_bin_shell_fraction, 0.0, 1.0)

        irregularity = (aspect / roundness) ** 0.35
        throat_raw = num_w * irregularity * np.minimum(0.45 / d_mm, 2.0)
        deposition_raw = vol_w * irregularity * np.minimum(0.55 / d_mm, 1.8)

        throat_sum = max(float(np.sum(throat_raw)), 1e-18)
        deposition_sum = max(float(np.sum(deposition_raw)), 1e-18)
        throat_w = throat_raw / throat_sum
        deposition_w = deposition_raw / deposition_sum

        # 小而不規則的顆粒更快卡喉道；以 bin 尺度調整其飽和特徵體積。
        throat_vchar = self.throat_clog_char_vol * np.clip(self.ext_bin_diameter_mid_m / max(self.D10, 1e-12), 0.25, 3.0)
        # 沉積倍率保留體積主導，但仍受細粉與形狀不規則度調制。
        deposition_mult = np.clip((self.D10 / np.maximum(self.ext_bin_diameter_mid_m, 1e-12)) ** 0.35 * irregularity ** 0.20, 0.5, 2.5)
        # 外殼比例越低的粗粒，沉積更像骨架回填；給較小附加倍率。
        deposition_mult *= np.clip(0.6 + 0.4 * (1.0 - shell + 0.25), 0.5, 1.4)
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

    def noyes_whitney_area(self, slow: bool = False, use_reference: bool = False) -> float:
        """
        顯式 Noyes-Whitney 介面面積 A_eff [m²]。

        What: A_eff = a_s * V_solid * f_shell
              a_s     : PSD/形狀加權後的比表面積 [1/m]
              V_solid : 粉床固體體積
              f_shell : 200 μm 外層殼層可及比例
        """
        if slow:
            a_s = self.ref_surface_area_slow_spec if use_reference else self.surface_area_slow_spec
            f_shell = 1.0
        else:
            a_s_raw = self.ref_surface_area_fast_spec if use_reference else self.surface_area_fast_spec
            shell_frac = self.ref_shell_fraction_abs if use_reference else self.shell_fraction_abs
            # `surface_area_fast_spec` 已經在 bins 整合時包含 shell-accessibility 權重；
            # 這裡改回「每單位可及殼層體積的界面密度」，避免和 M_fast_0 的 shell penalty 重複。
            a_s = a_s_raw / max(shell_frac, 1e-12)
            f_shell = 1.0
        V_solid = (1.0 - self.phi) * self.V_bed
        return a_s * V_solid * f_shell

    def noyes_whitney_length(self, slow: bool = False, use_reference: bool = False) -> float:
        """
        顯式 Noyes-Whitney 擴散路徑長度 L_eff [m]。

        Why: Fast 受外層殼層控制；Slow 需穿透更深核心，因此路徑較長。
        """
        if slow:
            path = self.ref_diffusion_path_slow_m if use_reference else self.diffusion_path_slow_m
            if self.psd_bins_csv_path:
                fast_path = self.ref_diffusion_path_fast_m if use_reference else self.diffusion_path_fast_m
                # measured-bin 下，`diffusion_path_slow_m` 代表 deeper-core 的體積加權平均；
                # 直接拿來當 0D `L_eff` 會偏向最深核心，對 reduced-order 模型過重。
                # 幾何平均保留「比 fast 更深」，但不把整個 slow pool 視為都來自最深處。
                path = np.sqrt(max(path * fast_path, 1e-18))
            return max(self.shell_thickness, path)
        path = self.ref_diffusion_path_fast_m if use_reference else self.diffusion_path_fast_m
        return max(0.25 * self.shell_thickness, path)

    def k_beta_prior_from_psd(self) -> float:
        """
        由細粉比例與分布寬度推導 k_beta 的 soft prior。

        What:
            以 `<0.40 mm` fines 的 number / volume blend 當作堵塞指數，
            再用 PSD span 做小幅修正，回傳供 regularization 使用的中心值。

        Why:
            後段堵塞主要由細粉決定，但仍不能把 `k_beta` 直接寫死；
            這裡只提供可量測資訊導出的 soft prior。
        """
        fines_num = getattr(self, "psd_fines_num_lt_0p40", np.nan)
        fines_vol = getattr(self, "psd_fines_vol_lt_0p40", np.nan)
        fines_num_ref = getattr(self, "ref_psd_fines_num_lt_0p40", np.nan)
        fines_vol_ref = getattr(self, "ref_psd_fines_vol_lt_0p40", np.nan)
        throat = getattr(self, "psd_throat_clog_index", np.nan)
        deposition = getattr(self, "psd_deposition_clog_index", np.nan)
        throat_ref = getattr(self, "ref_psd_throat_clog_index", np.nan)
        deposition_ref = getattr(self, "ref_psd_deposition_clog_index", np.nan)
        span = getattr(self, "psd_span_num", np.nan)

        if not np.isfinite(fines_num) or not np.isfinite(fines_vol):
            return float(self.k_beta)

        fines_index = 0.7 * fines_num + 0.3 * fines_vol
        if np.isfinite(fines_num_ref) and np.isfinite(fines_vol_ref):
            fines_ref = max(0.7 * fines_num_ref + 0.3 * fines_vol_ref, 1e-4)
        else:
            fines_ref = max(fines_index, 1e-4)
        if np.isfinite(throat) and np.isfinite(deposition) and np.isfinite(throat_ref) and np.isfinite(deposition_ref):
            clog_index = 0.65 * throat + 0.35 * deposition
            clog_ref = max(0.65 * throat_ref + 0.35 * deposition_ref, 1e-4)
        else:
            clog_index = fines_index
            clog_ref = fines_ref
        span_ref = 1.55
        clog_scale = (clog_index / clog_ref) ** 1.20
        fines_scale = (fines_index / fines_ref) ** 0.45
        span_scale = (max(span, 0.25) / span_ref) ** 0.35 if np.isfinite(span) else 1.0
        prior = self.k_beta * clog_scale * fines_scale * span_scale
        return float(np.clip(prior, 0.45 * self.k_beta, 2.8 * self.k_beta))

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
        h: float,
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

        h_drive = max(h, 0.0)
        u_pos = max(float(np.nan_to_num(u_pore, nan=0.0, posinf=0.0, neginf=0.0)), 0.0)
        q_pos = max(float(np.nan_to_num(q_in, nan=0.0, posinf=0.0, neginf=0.0)), 0.0)

        S_u = u_pos / (u_pos + self.wetbed_rev_u_half)
        # bloom 後床層已浸濕，重排不必等自由水柱高於粉層才會發生；
        # 因此這裡用總水頭 h，而不是只用 h_free。
        S_h = h_drive / (h_drive + self.wetbed_rev_h_half)
        f_rev = 1.0 / (1.0 + self.wetbed_rev_gain * S_u * S_h)

        J_post = np.clip(q_pos / self.wetbed_irr_qin_ref, 0.0, 1.0) \
               * np.clip(u_pos / self.wetbed_irr_u_ref, 0.0, 1.0)
        f_irr = 1.0 / (1.0 + self.wetbed_irr_gain * J_post)

        f_mix = f_rev * f_irr
        # gate=0 → 1；gate=1 → f_mix
        f_gate = 1.0 - gate * (1.0 - f_mix)
        return float(np.clip(f_gate, 0.2, 1.0))

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
        """
        gate = self.post_bloom_gate(t_sec, bloom_end_s)
        if gate <= 1e-6:
            return 0.0

        xi = float(np.clip(pref_state, 0.0, 1.0))
        q_pos = max(float(np.nan_to_num(q_in, nan=0.0, posinf=0.0, neginf=0.0)), 0.0)
        S_q = q_pos / (q_pos + self.pref_flow_qin_half)
        S_impact = np.clip(pour_impact, 0.0, 1.0)
        build = gate * self.pref_flow_open_rate * S_impact * S_q * (1.0 - xi)
        decay = gate * xi / max(self.pref_flow_tau_decay, 1e-6)
        return build - decay

    def q_preferential(
        self,
        h,
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
            base = np.asarray(h, dtype=float)
            zeros = np.zeros_like(base, dtype=float)
            return float(zeros) if np.ndim(zeros) == 0 else zeros

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
        h_eff = self.bed_drive_head(h, T_K=T_K, t_sec=t_sec, sat=sat)
        q_pref = coeff * gate * wet_gate * kr_sat * xi_arr * h_eff * mu_scale
        q_pref = np.maximum(q_pref, 0.0)
        return float(q_pref) if np.ndim(q_pref) == 0 else q_pref

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
        impact = float(np.clip(pour_impact, 0.0, 1.0))
        relief = 1.0 - gate * self.throat_relief_gain * impact
        return float(np.clip(relief, 0.25, 1.0))

    def k_eff(
        self,
        V_out,
        sat: float = 1.0,
        h: float | None = None,
        q_in: float = 0.0,
        u_pore: float = 0.0,
        t_sec: float = 0.0,
        bloom_end_s: float | None = None,
        pour_impact: float = 0.0,
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

        TODO: 加入攪動項：dk/dt = -beta_agit·Q_in·k（高 Q_in 時細粉遷移更快）
        """
        throat_term, deposition_term = self.k_beta_components(V_out)
        throat_relief = self.throat_relief_factor(pour_impact, t_sec, bloom_end_s)
        throat_eff = 1.0 + (throat_term - 1.0) * throat_relief
        phi_sw = self.phi_effective(sat, h)
        kc = (phi_sw / self.phi)**3 * ((1.0 - self.phi) / (1.0 - phi_sw))**2
        f_post = self.wetbed_postbloom_factor(q_in, u_pore, h or 0.0, t_sec, bloom_end_s)
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
        """
        T_C = np.clip(T_K - 273.15, 0.0, 100.0)
        T_ref_C = self.T_ref - 273.15
        mu_rel = np.exp(np.polyval(self.mu_fit_log_coeffs, T_C))
        mu_rel_ref = np.exp(np.polyval(self.mu_fit_log_coeffs, T_ref_C))
        return self.mu * mu_rel / max(mu_rel_ref, 1e-12)

    def k_ext_T(self, T_K: float) -> float:
        """
        DEPRECATED 2026-05-02：legacy 單一 pool Arrhenius 萃取速率縮放。

        主 ODE 改用 `k_ext_fast_T` / `k_ext_slow_T`（雙 pool + bin-resolved），此
        method 已不在主萃取計算中被呼叫。保留僅為相容舊 `fit_two_stage` 流程。
        新程式碼請使用 fast/slow 版本。
        """
        return self.k_ext_coef * np.exp(
            self.Ea_ext / R_GAS * (1.0 / self.T_ref - 1.0 / T_K)
        )

    def diffusion_coeff(self, T_K: float, slow: bool = False) -> float:
        """
        Einstein-Smoluchowski 擴散係數：D = ν_p k_B T
        """
        mobility = self.nu_p_slow if slow else self.nu_p_fast
        return mobility * K_B * T_K

    def internal_diffusion_factor(self, t_sec: float, T_K: float, slow: bool = False) -> float:
        """
        顆粒內部擴散近似：c(r,t) ~ exp(-r² / 4Dt)

        What: 以 PSD 加權後的有效殘餘核心半徑作為擴散距離，
              將粒內 diffusion 對可及速率的抑制作為 0–1 乘子。

        Why: 0D 模型無法直接解球坐標 PDE，但仍需要把「核心溶質傳得較慢」
             這件事折進速率方程。

        2026-05-01 P0 修正：原 `path_eff = ref_path · sqrt(path/ref_path)` 把
            指數內 path 從二次降到一次，缺乏物理依據；對粗 bin 的 diffusion 阻力
            嚴重低估（subagent 萃取審計指出粗 bin 應有完整 path² 懲罰）。
            改回 Fickian: `diff = exp(-path² / 4Dt)`。
            為避免 reduced-order 0D 模型對 slow 在 t→0 時瞬時壓成零，
            改以 `t_eff = max(t_sec, t_floor)` 的方式處理 — t_floor 從 0.5 s
            提高到 5 s（典型 first-pour 滴流時間量級），讓 slow 在 first-drip
            就有合理的擴散時間積累。
        """
        t_eff = max(t_sec, 5.0)
        D_eff = max(self.diffusion_coeff(T_K, slow=slow), 1e-18)
        path = self.diffusion_path_slow_m if slow else self.diffusion_path_fast_m
        return float(np.exp(-(path ** 2) / max(4.0 * D_eff * t_eff, 1e-18)))

    def internal_diffusion_factor_path(self, t_sec: float, T_K: float, path_m: float, ref_path_m: float, slow: bool = False) -> float:
        """
        指定路徑長度版本的粒內 diffusion 乘子。

        What: 與 `internal_diffusion_factor()` 相同，但路徑由各 PSD bin 顯式提供。
        Why:  measured PSD 要真正進 bin-resolved ODE，就必須讓每個 bin 有自己的 diffusion path。

        2026-05-01 P0 修正：刪除 `sqrt(path_ratio)` 壓縮，回到 Fickian
            `diff = exp(-path² / 4Dt)`。`ref_path_m` 參數保留為 API 相容性
            但不再被使用。
        """
        t_eff = max(t_sec, 5.0)
        D_eff = max(self.diffusion_coeff(T_K, slow=slow), 1e-18)
        return float(np.exp(-(path_m ** 2) / max(4.0 * D_eff * t_eff, 1e-18)))

    # ── 修正 [1][9] 達西萃取（C∞ 平滑過渡 + 毛細管壓門檻） ──────────────────
    def q_extract(self, h, k_val=None, T_K=None, t_sec: float = 0.0, sat=None):
        """
        壓力頭收支版達西萃取流量 [m³/s]。

        What:
            Q_ext = kr(sat) · Φ(T) · k · L_bed · h_eff
            Φ(T) = π·tan²θ·ρg / μ(T)
            L_bed = h_bed
            等價寫法：
            Q_ext = kr(sat) · k · A_ref · ρg · h_eff / (μ(T) · L_bed)
            A_ref = π·tan²θ·h_bed²
            h_eff = softplus_like(h - h_cap - h_gas(t) + h_cap,wet)

            其中：
            - h                 : 重力驅動水頭
            - h_cap             : 低水位毛細截止頭
            - h_gas(t)          : CO₂ 背壓等效水頭
            - h_cap,wet         : 已浸濕床層的額外毛細驅動水頭

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
        """
        if k_val is None:
            k_val = self.k
        if T_K is None:
            T_K = self.T_brew
        phi_T = self.phi_darcy * (self.mu / self.mu_water(T_K))
        h_eff = self.bed_drive_head(h, T_K=T_K, t_sec=t_sec, sat=sat)
        kr_sat = 1.0 if sat is None else self.relative_permeability(sat)
        return kr_sat * phi_T * k_val * self.h_bed * h_eff

    def C_sat_T(self, T_K: float) -> float:
        """
        溫度相依的飽和濃度：C_sat(T) = C_sat_ref·(1 + α·(T - T_ref)) [g/L]

        Why: 溶解度為溫度正函數（吸熱溶解）；
             83°C 的萃取天花板比 99°C 低，復現冷萃 vs 熱沖的化學差異。
        """
        return self.C_sat * (1.0 + self.alpha_C_sat * (T_K - self.T_ref))

    # ── 修正 [7] 多組分萃取方法 ───────────────────────────────────────────────
    def k_ext_fast_T(self, T_K: float, t_sec: float = 0.0) -> float:
        """
        Fast 組分顯式 Noyes-Whitney 速率：k = η * A_eff * D / L_eff

        Why: 將原本等效的 k_ext 改寫成顯式 A·D/L 形式：
             - A_eff 來自 PSD/形狀/外層殼層
             - D 來自 Einstein-Smoluchowski
             - L_eff 代表外層殼層到核心的平均擴散距離
             另外保留 Arrhenius 與粒內 diffusion 因子，作為咖啡細胞壁阻力修正。
        """
        return float(np.sum(self.ext_bin_fast_mass_fraction * self.k_ext_fast_bins_T(T_K, t_sec=t_sec)))

    def k_ext_slow_T(self, T_K: float, t_sec: float = 0.0) -> float:
        """Slow 組分顯式 Noyes-Whitney 速率：k = η * A_eff * D / L_eff"""
        return float(np.sum(self.ext_bin_slow_mass_fraction * self.k_ext_slow_bins_T(T_K, t_sec=t_sec)))

    def k_ext_fast_bins_T(self, T_K: float, t_sec: float = 0.0) -> np.ndarray:
        """
        Fast 組分的 bin-resolved Noyes-Whitney 速率陣列。
        """
        D_eff = self.diffusion_coeff(T_K, slow=False)
        arr = np.exp(self.Ea_fast / R_GAS * (1.0 / self.T_ref - 1.0 / T_K))
        diff_factor = np.array([
            self.internal_diffusion_factor_path(t_sec, T_K, path, self.ref_diffusion_path_fast_m, slow=False)
            for path in self.ext_bin_path_fast_m
        ])
        return self.nw_eta_fast * self.ext_bin_area_fast_m2 * D_eff / np.maximum(self.ext_bin_path_fast_m, 1e-18) * arr * diff_factor

    def k_ext_slow_bins_T(self, T_K: float, t_sec: float = 0.0) -> np.ndarray:
        """
        Slow 組分的 bin-resolved Noyes-Whitney 速率陣列。
        """
        D_eff = self.diffusion_coeff(T_K, slow=True)
        arr = np.exp(self.Ea_slow / R_GAS * (1.0 / self.T_ref - 1.0 / T_K))
        diff_factor = np.array([
            self.internal_diffusion_factor_path(t_sec, T_K, path, self.ref_diffusion_path_slow_m, slow=True)
            for path in self.ext_bin_path_slow_m
        ])
        return self.nw_eta_slow * self.ext_bin_area_slow_m2 * D_eff / np.maximum(self.ext_bin_path_slow_m, 1e-18) * arr * diff_factor

    def C_sat_fast_T(self, T_K: float) -> float:
        """Fast 組分溫度相依平衡濃度"""
        return self.C_sat_fast * (1.0 + self.alpha_C_fast * (T_K - self.T_ref))

    def C_sat_slow_T(self, T_K: float) -> float:
        """Slow 組分溫度相依平衡濃度；alpha 較大，苦味跳變效應"""
        return self.C_sat_slow * (1.0 + self.alpha_C_slow * (T_K - self.T_ref))

    # ── 修正 [2][9] 旁路（消散型 + V 衰減 + μ(T) + 毛細管門檻） ──────────────
    def q_bypass(self, h, psi_val=None, T_K=None):
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
        cap_factor = 1.0 / (1.0 + np.exp(-(h - self.h_cap) / (self.h_cap * 0.25)))
        h_free = np.maximum(h - self.h_bed, 0.0)
        activation = 1.0 / (1.0 + np.exp(-(h_free - self.bypass_onset_head) / self.bypass_onset_width))
        shape = np.minimum(h_free / max(0.5 * self.h_bed, 1e-12), 1.0)
        mu_scale = self.mu / self.mu_water(T_K)
        return psi_val * h_free * shape * activation * mu_scale * cap_factor

    def q_total(
        self,
        h,
        k_val=None,
        psi_val=None,
        T_K=None,
        t_sec: float = 0.0,
        sat=None,
        pref_state: float = 0.0,
        bloom_end_s: float | None = None,
    ):
        """總出水流量 [m³/s]"""
        q_bulk = self.q_extract(h, k_val, T_K, t_sec, sat=sat)
        q_pref = self.q_preferential(h, pref_state, T_K=T_K, t_sec=t_sec, sat=sat, bloom_end_s=bloom_end_s)
        return q_bulk + q_pref + self.q_bypass(h, psi_val, T_K)

    # ── k–M 聯動：研磨度工廠方法 ───────────────────────────────────────────
    @classmethod
    def for_grind(cls, k_target: float, base: "V60Params | None" = None) -> "V60Params":
        """
        以研磨度 k 為軸，聯動調整 max_EY 與 k_ext_coef。

        What: 返回以 k_target 為滲透率的新 V60Params：
              max_EY(k)     = max_EY_ref     × (k_ref / k)^alpha_EY
              k_ext_coef(k) = k_ext_coef_ref × (k_ref / k)^alpha_ext

        Why（物理耦合）:
              k ∝ d²（Kozeny-Carman）—— k 是粒徑的流體代理變數。
              磨細（k↓）同步帶來：
                1. 更多細胞壁破裂 → max_EY↑（可及溶質增加）
                2. 擴散路徑縮短  → k_ext↑（萃取速率加快）
              三者解耦時無法預測最佳研磨點；聯動後可掃描 k-EY 曲線找極值。

        Args:
            k_target : 目標滲透率 [m²]，代表研磨粗細
            base     : 參考基底（None → 使用預設中研磨參數）

        Returns:
            新的 V60Params，k / max_EY / k_ext_coef 均已按聯動公式修正。
        """
        if base is None:
            base = cls()
        ratio = base.k_ref / k_target
        return dataclasses.replace(
            base,
            k          = k_target,
            max_EY     = base.max_EY     * (ratio ** base.alpha_EY),
            k_ext_coef = base.k_ext_coef * (ratio ** base.alpha_ext),
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
              - for_roast() 設定烘焙度的「基準面」（max_EY_ref, k_ext_ref...）
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
            k_ext_coef        = base.k_ext_coef * profile.k_ext_factor,
            Ea_slow           = profile.Ea_slow,
            fast_fraction     = profile.fast_fraction,
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
    ) -> float:
        """
        每一注起始沖擊的脈衝包絡。

        What:
            對每一個注水開始時刻 `t_start`，建立 `exp(-(t-t_start)/width)` 脈衝，
            並取所有 post-bloom 注水的最大值。

        Why:
            使用者實際操作會在每一注開始時用較大力量沖開中心粉床；
            這個瞬間效應不應被平均成整段注水的恆定流率。
        """
        if width_s <= 0:
            return 0.0
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
