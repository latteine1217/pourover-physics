"""
pour_over 套件入口點。

使用方式：
    uv run python -m pour_over
    uv run python -m pour_over benchmark

預設輸出（5 張圖）：
    v60_simulation.png  — 流體診斷（水位/流量/體積/旁路/k衰減/飽和度）
    v60_tds.png         — 萃取品質（床濃度/出口濃度/TDS/EY）
    v60_grind.png       — 三種研磨度綜合對比（流體 + 萃取）
    v60_thermal.png     — 三種水溫熱力學對比
    data/kinu_29_light/4:12/kinu29_light_20g_flow_fit.png
                        — 實測流動擬合展示圖（canonical kinu29 4:12，影片版量測；F10）

CLI 子命令：
    benchmark           — 依序執行 formal fit、benchmark suite、identifiability
"""

import argparse

from .core import simulate_brew, print_summary
from .showcase_state import latest_calibrated_params, latest_protocol
from .viz import plot_results, plot_tds, compare_grind, compare_thermal
from .analysis import find_optimal_grind
from .benchmark import DEFAULT_BENCHMARK_CASES, run_benchmark_suite
from .identifiability import analyze_fit_identifiability
from .fitting import fit_measured_benchmark, generate_measured_flow_fit_artifacts


def run_showcase() -> None:
    """
    執行原本的展示型主流程。

    Why:
        保持 `uv run python -m pour_over` 的既有行為不變，
        避免新增 CLI 子命令後破壞既有使用者工作流。

    展示基準（F6，2026-09-24）：五張根目錄圖一律以**最新 calibrated state**
    為中心（`showcase_state.latest_calibrated_params()` + 量測注水曲線），
    不再用 `V60Params()` 的通用預設。舊行為會讓 `v60_simulation.png` /
    `v60_tds.png` 展示一組沒有任何量測支持的參數，而同一頁的 compare 圖
    卻是 calibrated 的——同一份文件展示兩個不同模型（AGENTS.md §2.4、§7）。
    """
    protocol = latest_protocol()
    params = latest_calibrated_params()

    # ── 1. calibrated 模擬：流體診斷 + 萃取品質 ──────────────────────────────
    print("=== Calibrated V60 手沖模擬（kinu29 4:12 baseline，影片版量測）===")
    results = simulate_brew(params, protocol, t_end=500)
    print_summary(results, label="Calibrated Kinu 29, light, 20 g")
    plot_results(
        results,
        title="V60 Calibrated Brew — Kinu 29, Light Roast, 20 g",
        save_as="v60_simulation.png",
    )
    plot_tds(results)

    # ── 2. 研磨度綜合對比（流體 + 萃取）──────────────────────────────────────
    print("\n=== 研磨度綜合對比 ===")
    compare_grind(protocol)

    # ── 3. 熱力學耦合：水溫對比 ──────────────────────────────────────────────
    print("\n=== 熱力學耦合：水溫對比 ===")
    compare_thermal(protocol)

    # ── 4. 最佳研磨度搜尋 ────────────────────────────────────────────────────
    print("\n=== 最佳研磨度搜尋（SCA 黃金杯目標）===")
    find_optimal_grind(protocol)

    # ── 5. 量測流動擬合展示產物 ──────────────────────────────────────────────
    print("\n=== 量測流動擬合（含 wetbed χ 校準）===")
    generate_measured_flow_fit_artifacts(verbose=True)


def run_benchmark_command(
    *,
    all_cases: bool = False,
    verbose: bool = True,
) -> None:
    """
    一次執行 measured benchmark 的正式校準、benchmark suite 與可識別性分析。

    What:
        1. `fit_measured_benchmark()`：更新 canonical case 的 calibrated summary / plot
        2. `run_benchmark_suite()`：檢查 regression gates
           （`all_cases=True` 時跑四個 measured case，否則只跑 canonical）
        3. `analyze_fit_identifiability()`：輸出局部 Δχ² slices 與 heatmap

    Why:
        讓使用者只需一個 CLI 子命令，就能完成
        「校準 → 回歸檢查 → 可識別性檢查」。

    solver 一律由 `fitting.SOLVER_COARSE / SOLVER_FINE` 決定，CLI 不再暴露
    `--ident-n-eval`：舊版讓 identifiability 用自己的 n_eval，於是它的 Δloss
    與 fitting 的 loss 其實來自不同的數值解析度（AUD）。
    """
    print("=== Measured Benchmark Fit ===")
    fit_measured_benchmark(verbose=verbose)

    print("\n=== Regression Gates ===")
    run_benchmark_suite(
        cases=list(DEFAULT_BENCHMARK_CASES) if all_cases else None,
        refit=False,
        verbose=verbose,
    )

    print("\n=== Local Identifiability ===")
    analyze_fit_identifiability(refit=False, verbose=verbose)


def build_parser() -> argparse.ArgumentParser:
    """
    建立 CLI parser。

    Why:
        子命令應明確表達 intent，而不是把所有流程都塞進無參數主入口。
    """
    parser = argparse.ArgumentParser(
        prog="python -m pour_over",
        description="V60 手沖物理模擬與量測 benchmark 工具。",
    )
    subparsers = parser.add_subparsers(dest="command")

    bench = subparsers.add_parser(
        "benchmark",
        help="依序執行 formal fit、benchmark suite 與 identifiability 分析。",
    )
    bench.add_argument(
        "--all-cases",
        action="store_true",
        help="benchmark suite 跑全部四個 measured case（預設只跑 canonical case）。",
    )
    bench.add_argument(
        "--quiet",
        action="store_true",
        help="減少 fitting / benchmark 過程輸出。",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """
    CLI 入口。

    What:
        無子命令 → 跑既有 showcase 流程。
        `benchmark` → 跑 measured benchmark 全套檢查。
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "benchmark":
        run_benchmark_command(
            all_cases=bool(args.all_cases),
            verbose=not bool(args.quiet),
        )
        return

    run_showcase()


if __name__ == "__main__":
    main()
