"""
pour_over — V60 手沖咖啡流體模擬套件

公開 API：
    from pour_over import V60Constant, V60Params, RoastProfile, PourProtocol
    from pour_over import simulate_brew, print_summary
    from pour_over import find_optimal_grind, fit_brew_params
"""

from .constant import RHO, G, H_MIN, R_GAS, V60Constant
from .params import RoastProfile, V60Params, PourProtocol
from .core import simulate_brew, print_summary
from .measured_io import (
    load_brew_log_csv,
    load_flow_profile_csv,
    protocol_from_brew_log,
    protocol_from_cumulative_input,
)
from .observation import (
    mixed_cup_temperature_C,
    observed_stop_time_from_layer,
)
from .benchmark import run_benchmark_suite
from .identifiability import (
    analyze_fit_identifiability,
    analyze_pref_flow_identifiability,
)
from .viz import (
    plot_results,
    plot_tds,
    compare_grind,
    compare_tds_grind,
    compare_corrections,
    compare_grind_sizes,
    compare_thermal,
    compare_flavor,
)
from .fitting import (
    fit_brew_params,
    fit_vessel_equivalent_ml,
    fit_brew_log_final_temp,
    fit_k_kbeta_from_flow_profile,
    fit_measured_benchmark,
    generate_measured_flow_fit_artifacts,
    evaluate_measured_flow_fit,
    profile_ci,
    save_fit_summary_csv,
    save_flow_fit_summary_csv,
    plot_flow_fit_comparison,
    demo_fitting,
)
from .psd import (
    load_psd_raw_csv,
    load_psd_stats_csv,
    infer_psd_summary,
    infer_psd_bins,
    psd_overrides_for_model,
    save_psd_summary_csv,
    save_psd_bins_csv,
)
from .analysis import (
    sensitivity_analysis,
    compare_grind_linkage,
    find_optimal_grind,
)

__all__ = [
    # 常數
    "RHO", "G", "H_MIN", "R_GAS",
    # 參數類別
    "V60Constant", "RoastProfile", "V60Params", "PourProtocol",
    # 模擬引擎
    "simulate_brew", "print_summary",
    # 視覺化
    "plot_results", "plot_tds",
    "compare_grind",
    "compare_tds_grind", "compare_corrections",
    "compare_grind_sizes", "compare_thermal", "compare_flavor",
    # 擬合
    "fit_brew_params",
    "load_brew_log_csv", "load_flow_profile_csv",
    "protocol_from_brew_log", "protocol_from_cumulative_input",
    "mixed_cup_temperature_C", "observed_stop_time_from_layer", "fit_vessel_equivalent_ml",
    "fit_brew_log_final_temp", "fit_k_kbeta_from_flow_profile",
    "fit_measured_benchmark", "evaluate_measured_flow_fit", "profile_ci",
    "generate_measured_flow_fit_artifacts",
    "save_fit_summary_csv", "save_flow_fit_summary_csv",
    "plot_flow_fit_comparison",
    "demo_fitting",
    # PSD
    "load_psd_raw_csv", "load_psd_stats_csv",
    "infer_psd_summary", "infer_psd_bins",
    "psd_overrides_for_model", "save_psd_summary_csv", "save_psd_bins_csv",
    # 分析
    "sensitivity_analysis",
    "run_benchmark_suite", "analyze_fit_identifiability",
    "analyze_pref_flow_identifiability",
    "compare_grind_linkage", "find_optimal_grind",
]
