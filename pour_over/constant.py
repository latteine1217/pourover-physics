"""
pour_over.constant — 可量測固定輸入與物理常數
==============================================

What:
    集中 V60 主模型中「物理上可量測、應固定」的常數與輸入欄位。

Why:
    這些量不應混入 closure / fitting 旋鈕，否則 `params.py` 會同時承擔
    幾何量、量測輸入、物理常數與可標定參數，模組責任會失焦。
    將其獨立後，`V60Params` 可以只保留模型假設與少量可調參數，
    同時又維持既有 dataclass API 相容性。
"""

from dataclasses import dataclass

# ── 物理常數 ──────────────────────────────────────────────────────────────────
RHO = 1000.0  # 水密度 [kg/m³]
G = 9.81  # 重力加速度 [m/s²]
H_MIN = 1e-4  # 最低有效水位（避免 A(h)→0 除以零）[m]
R_GAS = 8.314  # 理想氣體常數 [J/(mol·K)]（保留供既有呼叫端；主萃取路徑已不用 Arrhenius）
K_B = 1.380649e-23  # 波茲曼常數 [J/K]
CP_WATER = 4180.0  # 水比熱容 [J/(kg·K)]；焓平衡與能量審計以 RHO*CP_WATER 為體積熱容

# ── 溶質分子尺度（Class B：由文獻擴散係數先算再固定，不進 fitting）──────────
# What: 兩個溶質池代表分子的 Stokes-Einstein 水力半徑 [m]。
#       主萃取閉合用 D_x(T) = k_B·T / (6π·μ(T)·r_x) 描述全部溫度相依性，
#       因此這兩個半徑是「溫度相依從哪裡來」的唯一物理輸入。
# Why:  舊實作用 `D = ν_p·k_B·T`（ν_p 為固定 mobility），等於宣告 D ∝ T 而
#       與黏度無關——但 92 → 75 °C 之間 μ 上升 39%，真實 D 下降約 34%，
#       方向完全相反。再乘一層 Arrhenius `exp(Ea/R(1/T_ref − 1/T))` 之後，
#       同一件事被數了三次（AUD-3）。Stokes-Einstein 只用 μ(T) 一條路徑。
SOLUTE_RADIUS_FAST_M = 0.40e-9
# fast pool（咖啡因、綠原酸、蔗糖等小分子）代表半徑。
# 推導：r = k_B·T /(6π·μ·D)，μ(25 °C) = 8.90e-4 Pa·s。
#   咖啡因 D_w(25 °C) ≈ 0.63e-9 m²/s → r = 0.39 nm
#   蔗糖   D_w(25 °C) ≈ 0.52e-9 m²/s → r = 0.47 nm
# 取 0.40 nm 代表這群分子的下緣（最易擴散者主導 fast pool 的早期釋放）。

SOLUTE_RADIUS_SLOW_M = 1.00e-9
# slow pool（melanoidin、阿拉伯半乳聚醣片段等 1–10 kDa 大分子）代表半徑。
# 推導：同式代入 D_w(25 °C) ≈ 2.4e-10 m²/s（5 kDa 級寡糖/褐色素片段）→ r ≈ 1.0 nm。
# D_slow/D_fast = r_fast/r_slow = 0.40，即 slow 溶質本身就比 fast 慢 2.5×；
# 兩池其餘的速率差來自幾何（殼層厚度 δ vs 核心半徑 R_core），不再由
# 兩個獨立的 mobility 旋鈕決定。


@dataclass
class V60Constant:
    """
    V60 模型的固定物理輸入。

    What:
        定義濾杯幾何、量測環境、硬體熱容與 measured PSD 入口等固定欄位。

    Why:
        這些量應該來自量測、實驗設定或材料性質，而不是交由 optimizer
        當成補償其他 closure 缺項的自由旋鈕。
    """

    half_angle_deg: float = 30.0
    # V60 圓錐半角 [deg]；幾何固定量

    mu: float = 3.0e-4
    # 參考溫度下的水動力黏度 [Pa·s]；供 Darcy 基準縮放使用

    h_bed: float = 0.048
    # 粉層高度 [m]；量測擬合時應以實測覆寫

    dose_g: float = 20.0
    # 粉重 [g]

    T_brew: float = 366.15
    # 初始沖煮水溫 [K]

    T_ref: float = 366.15
    # 黏度與 Arrhenius 校準參考溫度 [K]

    T_amb: float = 298.15
    # 環境溫度 [K]

    T_initial_K: float | None = None
    # 沖煮起始時刻的粉床/濾杯溫度 [K]；None → 退回 T_amb
    # What: 探針在 t=0 讀到的實測起始溫度（含預熱）。
    # Why:  過去硬編 T(0)=T_dripper(0)=T_amb，等於假設完全沒有預熱；
    #       kinu29 探針 t=0 讀 25.5 °C 已高於 T_amb=23 °C。
    #       這是可直接量測的 Class-A 輸入，不該由熱端 closure 吸收。

    dripper_mass_g: float = 0.0
    # 濾杯質量 [g]

    dripper_cp_J_gK: float = 0.88
    # 濾杯材質比熱 [J/(g·K)]

    mu_fit_log_coeffs: tuple[float, float, float, float] = (
        -8.17297841e-07,
        2.32004852e-04,
        -3.36945065e-02,
        5.90898359e-01,
    )
    # 由相對黏滯度 vs 溫度曲線擬合出的 log-cubic 係數

    Cp_coffee: float = 1800.0
    # 乾咖啡粉比熱容 [J/(kg·K)]
    # Source: Singh & Heldman, "Introduction to Food Engineering" Appendix table（roasted coffee
    # beans 1670–1880 J/(kg·K)）；Pittia et al. 2007（"Thermophysical properties of green and
    # roasted coffee", J. Food Eng., 80(2), 600–605）回報烘焙咖啡 1500–1900 J/(kg·K)，與含水率/
    # 烘焙度相關。1800 取中位代表值。
    # Sensitivity: V_equiv_coffee ∝ Cp_coffee；20 g 粉、Cp=1800 → V_equiv = 8.6 mL water-equiv，
    # 占 V_eff_T (≈24 mL post-bloom) 約 36%。±10% Cp 變動 → ±0.86 mL V_eff_T，bloom 期升溫
    # 速率小幅變動，但 cup_temp 會被熱端 fit (λ_liq_drip / λ_server) 自動吸收。
    # 因此本參數視為 calibrated forward-input（與 dripper_mass_g、dripper_cp_J_gK 同列）：
    # 不進 fitting loop；若使用者切換不同烘焙度或顯著潤濕粉，可在此調整。

    D10_measured_m: float | None = None
    # 診斷用 number-based D10 覆寫 [m]；**不縮放任何幾何量**。
    # Why: 影像量測的 number-based D10 落在整數像素格點上（SURFACE = 11 px、21 px
    #      分別給出 0.3742 / 0.5171 mm，三份 per-case 掃描完全相同），是偵測下限的
    #      artifact，不是研磨度資訊。模型尺度錨點改用 Sauter `d32`（見 `V60Params.d32`）。
    #      本欄保留僅為向後相容既有 CSV metadata 與 override 呼叫端。

    psd_bins_csv_path: str | None = None
    # 若有 multi-bin PSD，優先用 bins 直接計算表面積、殼層可及性與擴散路徑
    # PSD 的絕對尺度完全由此 bins CSV 決定（由 `pour_over.psd` 依 PIXEL_SCALE 產生）。

    psd_diameter_scale: float = 1.0
    # measured PSD 的顯式粒徑縮放倍率（1.0 = 直接使用量測值）
    # Why: 研磨度 sweep 需要在同一份量測形狀上平移粒徑分布。此處必須是顯式輸入，
    #      不得再由 `D10_measured_m` 隱性推導縮放比例——那會讓 resolution-bounded
    #      的 D10 artifact 反過來決定整條 PSD 的絕對尺度。
