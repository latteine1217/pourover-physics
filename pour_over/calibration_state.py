"""
calibration_state.py — frozen calibrated closure 常量

What:
    提供目前主模型在「kinu29 light、20 g、h_bed = 5.3 cm、measured PSD =
    data/kinu29_psd_bins.csv、ceramic V60 dripper」這組標準展示基準下，
    經由 ``fit_k_kbeta_from_flow_profile``（含 ``fit_preferential_flow=True``）
    擬合得到的 closure 參數。常量名稱沿用 ``DEFAULT_*_FIXED``，
    以維持 ``pour_over.fitting`` 對外的 API 不破壞。

    NOTE: ``DEFAULT_WETBED_STRUCT_RATE_FIXED`` 已隨 P0/P1 重構移除：
    χ 結構態與 ``f_irr`` 的物理敘事重複，identifiability log 顯示
    ``wetbed_struct_gain × rate`` 為平 ridge，現整體併入
    ``wetbed_postbloom_factor``（加性阻力進 ``R_total``）。

Why:
    這些值在物理上與特定 PSD、dose、bed height、硬體配置綁定，
    並非通用常數；若直接把 15+ 位有效數字的 optimizer raw output
    黏進原始碼，會把擬合 noise 當成模型的一部分，
    並讓「何時必須重算」這件事對新使用者完全不可見。
    把它們集中在獨立檔案、保留 6 位有效數字並附原值與重算指引，
    才能在維持 reproducibility 的同時暴露其 frozen 屬性。

重算指引:
    當下列任一條件改變，必須在乾淨的 measured flow case 上重新跑
    ``fit_k_kbeta_from_flow_profile``（``fit_preferential_flow=True``），
    並把新值同步更新回此檔；不要在 ``fitting.py`` 內就地覆寫常量：

    1. measured PSD（``psd_bins_csv_path`` 或 bin 結構）
    2. dose（``dose_g``）
    3. bed height（``h_bed``）
    4. dripper 硬體（質量、材質、幾何）
    5. ambient / brew 溫度顯著偏離 23 / 92 degC
"""

# 6 位有效數字 round 後的值（原始 full precision 在註釋中保留）
DEFAULT_PREF_FLOW_OPEN_RATE_FIXED = 0.254075   # 原值 0.254074546131474
DEFAULT_PREF_FLOW_TAU_DECAY_FIXED = 3.14014    # 原值 3.1401416403754285

# ── k_beta 的 PSD soft prior anchor ──────────────────────────────────────────
# What:
#     `V60Params.k_beta_prior_from_psd()` 以
#         prior = KBETA_PRIOR_REF * (clog_index / CLOG_INDEX_REF)
#     把 measured PSD 的無因次堵塞指數映射到 k_beta 的先驗中心 [m⁻³]。
#
# Why:
#     這兩個數是**標定 anchor，不是物理常數**。`KBETA_PRIOR_REF` 取自
#     2026-05-06 canonical fit 的 `k_beta_fit`；`CLOG_INDEX_REF` 是同一次標定
#     所用 PSD（kinu29 light, 4:11, 2026-05 重建之 bins）的 `psd_clog_index()`。
#     一旦更換 calibration case、重新產生 PSD bins、或改動 `psd_clog_index()`
#     的組成（throat/deposition 權重、堵塞核形式），兩者都必須一起重算，
#     否則 prior 會靜默偏移一個常數倍率。
#
# 重算方式：
#     p = V60Params(psd_bins_csv_path="data/kinu_29_light/4:11/kinu29_psd_bins.csv", ...)
#     CLOG_INDEX_REF = p.psd_clog_index()
#     KBETA_PRIOR_REF = <該 case 的 k_beta_fit>
KBETA_PRIOR_REF = 2353.0
CLOG_INDEX_REF = 0.377042  # kinu29 light 4:11 PSD（2026-05 重建），原值 0.37704198235776015

# k_beta soft prior 的對數標準差 [dex]，供 fitting regularization 使用。
# 0.30 dex ≈ 因子 2：PSD → k_beta 的映射只宣稱量級與排序，不宣稱精度。
KBETA_PRIOR_SIGMA_DEX = 0.30
