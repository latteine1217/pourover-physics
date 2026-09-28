"""
viz.py — V60 模擬視覺化模組

What:
    提供兩類圖面函式：
    1. `plot_results()`、`plot_tds()`：直接吃單次模擬結果的診斷圖
    2. `compare_*()`：以展示基準為中心的多情境比較圖

Why:
    視覺化層應只負責把已知的 `results` 或 `scenario configs` 轉成可讀圖面，
    不應再承擔 calibrated baseline 選擇或量測資料載入。
    目前展示狀態的組裝已移至 `showcase_state.py`，本模組維持純繪圖責任。
"""

from dataclasses import replace

import numpy as np
import matplotlib.pyplot as plt

from .params import PourProtocol
from .core import simulate_brew
from .measured_io import MEASURED_PAPER_HOLDUP_ML
from .showcase_state import (
    latest_protocol,
    latest_calibrated_params,
    latest_grind_configs,
    latest_correction_configs,
)


# 量測 σ（與 `fitting.MEASUREMENT_SIGMA` 同一來源）：殘差圖必須畫出
# 「多大的殘差才算超出量測噪音」，否則讀者只能看形狀猜量級。
# 這裡以延遲 import 取值，避免 viz -> fitting -> viz 的循環依賴。
def _measurement_sigma(key: str) -> float:
    from .fitting import MEASUREMENT_SIGMA
    return float(MEASUREMENT_SIGMA[key])


PALETTE = {
    "bg": "#f6f1e8",
    "panel": "#fffaf2",
    "grid": "#ddd4c4",
    "ink": "#2d241d",
    "muted": "#6e6256",
    "blue": "#2f6db2",
    "teal": "#147d6f",
    "orange": "#c46a2d",
    "red": "#a63d40",
    "purple": "#7d4f9e",
    "green": "#4f7d43",
    "gold": "#d1a43b",
    "lime": "#99b76b",
}


def _setup_style() -> None:
    """設定輸出圖的整體風格。

    What: 把所有圖改成暖底色、高對比重點線、低干擾網格。
    Why: 使用者看的是沖煮判讀，不是 Matplotlib 預設主題。
    """
    plt.rcParams.update({
        "figure.facecolor": PALETTE["bg"],
        "axes.facecolor": PALETTE["panel"],
        "axes.edgecolor": PALETTE["grid"],
        "axes.labelcolor": PALETTE["ink"],
        "axes.titlecolor": PALETTE["ink"],
        "text.color": PALETTE["ink"],
        "xtick.color": PALETTE["muted"],
        "ytick.color": PALETTE["muted"],
        "font.size": 10.5,
        "axes.titlesize": 12,
        "axes.labelsize": 10,
        "legend.frameon": False,
        "savefig.facecolor": PALETTE["bg"],
    })


def _style_ax(ax, title: str, ylabel: str, xlabel: str = "Time [s]") -> None:
    """統一子圖外觀，讓不同圖之間的閱讀習慣一致。"""
    ax.set_facecolor(PALETTE["panel"])
    ax.grid(True, color=PALETTE["grid"], linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", fontweight="bold", pad=10)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(PALETTE["grid"])


# summary band 的版面常數：標題佔左側 `_BAND_TITLE_SPAN`，數值框只能用右側剩下的空間。
_BAND_TITLE_SPAN = 0.34      # 標題保留區的右界（figure 座標）
_BAND_MAX_STEP = 0.145       # 數值框的預設間距（≤ 5 欄時維持原外觀）


def _summary_band(fig, title: str, stats: list[tuple[str, str]]) -> None:
    """在圖頂部放關鍵數值，讓讀者先抓結論再看曲線。

    間距隨欄數收縮：固定 0.145 時第 6 欄以後會壓到標題上（實測 7 欄的
    flow-fit 圖標題被蓋掉一半）。改為在標題保留區右側均分，欄數少時行為不變。
    """
    fig.text(0.015, 0.985, title, ha="left", va="top",
             fontsize=18, fontweight="bold", color=PALETTE["ink"])
    n = max(len(stats), 1)
    step = min(_BAND_MAX_STEP, (0.985 - _BAND_TITLE_SPAN) / max(n - 1, 1))
    x = 0.985
    for label, value in reversed(stats):
        fig.text(
            x, 0.985, f"{label}\n{value}",
            ha="right", va="top", fontsize=9.2, color=PALETTE["ink"],
            bbox=dict(boxstyle="round,pad=0.35", fc=PALETTE["panel"], ec=PALETTE["grid"], lw=0.8),
        )
        x -= step


def _add_time_guides(ax, results: dict) -> None:
    """加上 brew end / drain end 的垂直參考線。"""
    t = results["t"]
    ymax = ax.get_ylim()[1]
    brew_time = float(results.get("brew_time", np.nan))
    drain_time = float(results.get("drain_time", np.nan))
    if np.isfinite(brew_time) and 0 < brew_time < t[-1]:
        ax.axvline(brew_time, color=PALETTE["muted"], lw=1.0, ls="--", alpha=0.8)
        ax.text(brew_time, ymax, " brew end", color=PALETTE["muted"],
                fontsize=8.2, va="top", ha="left")
    if np.isfinite(drain_time) and brew_time < drain_time < t[-1]:
        ax.axvline(drain_time, color=PALETTE["grid"], lw=1.0, ls=":", alpha=1.0)
        ax.text(drain_time, ymax, " drain end", color=PALETTE["muted"],
                fontsize=8.2, va="top", ha="left")


def _annotate_endpoint(ax, x: float, y: float, text: str, color: str, dx: float = 6, dy: float = 0) -> None:
    """在曲線終點或重點位置標數值，減少 legend 往返。"""
    ax.scatter([x], [y], s=28, color=color, edgecolor="white", linewidth=0.8, zorder=5)
    ax.annotate(
        text, (x, y), xytext=(dx, dy), textcoords="offset points",
        fontsize=8.3, color=color, va="center",
        bbox=dict(boxstyle="round,pad=0.22", fc=PALETTE["panel"], ec=color, lw=0.8),
    )


def _save_fig(fig, save_as: str, message: str) -> None:
    """統一輸出圖檔與關閉 figure，避免互動式殘留狀態。"""
    fig.savefig(save_as, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(message)


def plot_results(
    results: dict,
    title: str = "V60 Flow Diagnostics",
    save_as: str = "v60_simulation.png",
) -> None:
    """六格流體診斷圖。

    What: 呈現水位、流量分解、體積守恆、旁路、滲透率與飽和度。
    Why:  先把流動讀清楚，才能討論後面的萃取品質是不是合理。
    """
    _setup_style()
    t = results["t"]

    fig, axes = plt.subplots(2, 3, figsize=(15.6, 8.8), constrained_layout=True)
    _summary_band(fig, title, [
        ("Brew time", f"{results['brew_time']:.0f} s"),
        ("Drain time", f"{results['drain_time']:.0f} s"),
        ("Avg bypass", f"{results['bypass_ratio'].mean() * 100:.1f}%"),
        ("Avg pref", f"{results.get('pref_ratio', np.zeros_like(results['bypass_ratio'])).mean() * 100:.1f}%"),
        ("Bloom choke", str(results.get("dominant_bloom_choke", "n/a"))),
        ("D10", f"{results['D10_um']:.0f} μm"),
    ])

    ax = axes[0, 0]
    ax.fill_between(t, results["h_mm"], color=PALETTE["blue"], alpha=0.16)
    ax.plot(t, results["h_mm"], color=PALETTE["blue"], lw=2.4)
    ax.axhline(48, color=PALETTE["muted"], lw=1.0, ls="--")
    _style_ax(ax, "Water head over time", "Water Level [mm]")
    _add_time_guides(ax, results)
    _annotate_endpoint(ax, t[-1], results["h_mm"][-1], f"{results['h_mm'][-1]:.1f} mm", PALETTE["blue"], dx=-78)

    ax = axes[0, 1]
    q_pref_mlps = results.get("q_pref_mlps", np.zeros_like(results["q_ext_mlps"]))
    ax.stackplot(
        t, results["q_ext_mlps"], q_pref_mlps, results["q_bp_mlps"],
        labels=["Bulk bed", "Fast path", "Bypass"],
        colors=[PALETTE["teal"], PALETTE["blue"], PALETTE["orange"]], alpha=0.72,
    )
    ax.plot(t, results["q_in_eff_mlps"], color=PALETTE["blue"], lw=1.6, ls="--", label="Effective pour")
    _style_ax(ax, "Where the liquid goes", "Flow Rate [mL/s]")
    _add_time_guides(ax, results)
    ax.legend(loc="upper right", fontsize=8.4)

    ax = axes[0, 2]
    ax.plot(t, results["v_in_ml"], color=PALETTE["green"], lw=2.3, label="Total in")
    ax.plot(t, results["v_in_eff_ml"], color="#8fbf7f", lw=1.7, ls="--", label="Effective in")
    ax.plot(t, results["v_out_ml"], color=PALETTE["red"], lw=2.3, label="Total out")
    ax.plot(t, results["v_extract_ml"], color=PALETTE["blue"], lw=1.7, ls="--", label="Extract out")
    _style_ax(ax, "Cumulative volume balance", "Volume [mL]")
    _add_time_guides(ax, results)
    ax.legend(fontsize=8.2, loc="lower right")

    ax = axes[1, 0]
    bypass_pct = results["bypass_ratio"] * 100
    ax.fill_between(t, bypass_pct, color=PALETTE["orange"], alpha=0.28)
    ax.plot(t, bypass_pct, color=PALETTE["orange"], lw=2.2)
    _style_ax(ax, "Bypass activation", "Bypass Ratio [%]")
    ax.set_ylim(0, 100)
    _add_time_guides(ax, results)
    _annotate_endpoint(ax, t[-1], bypass_pct[-1], f"{bypass_pct[-1]:.1f}%", PALETTE["orange"], dx=-54)

    ax = axes[1, 1]
    k_retained = results["k_vals"] / results["k_vals"][0] * 100
    ax.fill_between(t, k_retained, 100, color=PALETTE["purple"], alpha=0.10)
    ax.plot(t, k_retained, color=PALETTE["purple"], lw=2.2)
    _style_ax(ax, "Permeability retained", "k_eff / k_0 [%]")
    ax.set_ylim(0, 105)
    _add_time_guides(ax, results)
    _annotate_endpoint(ax, t[-1], k_retained[-1], f"{k_retained[-1]:.0f}%", PALETTE["purple"], dx=-48)

    ax = axes[1, 2]
    sat_pct = results["sat"] * 100
    sat_flow_pct = results.get("sat_flow", results["sat"]) * 100
    kr_pct = results.get("kr_sat", np.ones_like(results["sat"])) * 100
    head_gate_pct = results.get("head_gate", np.ones_like(results["sat"])) * 100
    ax.plot(t, sat_pct, color=PALETTE["teal"], lw=1.5, ls="--", label="sat")
    ax.plot(t, sat_flow_pct, color=PALETTE["green"], lw=2.0, label="sat_flow")
    ax.plot(t, kr_pct, color=PALETTE["purple"], lw=2.0, label="kr(sat)")
    ax.plot(t, head_gate_pct, color=PALETTE["orange"], lw=2.0, label="head gate")
    _style_ax(ax, "Bloom choke drivers", "Gate [%]")
    ax.set_ylim(0, 105)
    _add_time_guides(ax, results)
    bloom_end = float(results.get("bloom_end_s", np.nan))
    if np.isfinite(bloom_end):
        ax.axvspan(0.0, bloom_end, color=PALETTE["muted"], alpha=0.08)
        ax.axvline(bloom_end, color=PALETTE["muted"], lw=1.0, ls=":")
    dominant = str(results.get("dominant_bloom_choke", "n/a"))
    means = results.get("bloom_choke_means", {})
    dominant_val = 100.0 * float(means.get(dominant, 0.0)) if isinstance(means, dict) else 0.0
    ax.text(
        0.03,
        0.95,
        f"Bloom dominant: {dominant} ({dominant_val:.0f}%)",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8.2,
        color=PALETTE["ink"],
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.72, "pad": 2.5},
    )
    ax.legend(fontsize=8.0, loc="lower right")

    _save_fig(fig, save_as, f"圖表已儲存至 {save_as}")


def plot_tds(
    results: dict,
    title: str = "V60 Extraction Quality",
    save_as: str = "v60_tds.png",
) -> None:
    """四格萃取品質圖。

    What: 呈現床內濃度、出液濃度、杯中 TDS、以及 EY 分流。
    Why:  讓讀者先看到杯中結果，再回推是濃度不足、旁路稀釋，還是保留液造成。
    """
    _setup_style()
    t = results["t"]

    fig, axes = plt.subplots(2, 2, figsize=(13.5, 8.6), constrained_layout=True)
    fast_share = results["EY_fast_cup_pct"][-1] / max(results["EY_cup_pct"][-1], 1e-9) * 100
    _summary_band(fig, title, [
        ("Cup TDS", f"{results['TDS_gl'][-1] / 10:.2f}%"),
        ("Cup EY", f"{results['EY_cup_pct'][-1]:.1f}%"),
        ("Fast share", f"{fast_share:.0f}%"),
        ("Final LRR", f"{results['f_abs']:.2f} mL/g"),
    ])

    ax = axes[0, 0]
    if "C_bed_top_gl" in results and "C_bed_bottom_gl" in results:
        ax.plot(t, results["C_bed_top_gl"], color="#c59ad8", lw=1.5, ls="--", label="Top layer")
        ax.plot(t, results["C_bed_bottom_gl"], color=PALETTE["purple"], lw=2.3, label="Bottom layer")
        ax.plot(t, results["C_bed_gl"], color="#7d6291", lw=1.8, alpha=0.85, label="Bed mean")
    else:
        ax.plot(t, results["C_bed_gl"], color=PALETTE["purple"], lw=2.3, label="Bed concentration")
    ax.plot(t, results["C_sat_eff_gl"], color="#bb8fd2", lw=1.7, ls="--", label="Effective saturation")
    _style_ax(ax, "Concentration inside the bed", "Concentration [g/L]")
    _add_time_guides(ax, results)
    ax.legend(fontsize=8.4, loc="upper right")

    ax = axes[0, 1]
    ax.plot(t, results["C_out_gl"], color=PALETTE["blue"], lw=2.4, label="Cup inflow concentration")
    ref_curve = results["C_bed_bottom_gl"] if "C_bed_bottom_gl" in results else results["C_bed_gl"]
    ref_label = "Bottom-layer concentration" if "C_bed_bottom_gl" in results else "Bed concentration"
    ax.plot(t, ref_curve, color=PALETTE["purple"], lw=1.2, ls="--", alpha=0.55, label=ref_label)
    _style_ax(ax, "What actually leaves the cone", "Concentration [g/L]")
    _add_time_guides(ax, results)
    ax.legend(fontsize=8.4, loc="upper right")
    _annotate_endpoint(ax, t[-1], results["C_out_gl"][-1], f"{results['C_out_gl'][-1]:.1f} g/L", PALETTE["blue"], dx=-80)

    ax = axes[1, 0]
    ax.plot(t, results["TDS_gl"], color=PALETTE["orange"], lw=2.4, label="Cup TDS")
    ax.axhspan(11.5, 14.5, alpha=0.15, color=PALETTE["lime"], label="SCA band")
    ax2 = ax.twinx()
    ax2.plot(t, results["M_sol_g"], color=PALETTE["muted"], lw=1.6, ls=":", label="Remaining solubles")
    ax2.set_ylabel("Solubles Remaining [g]", color=PALETTE["muted"])
    ax2.tick_params(axis="y", labelcolor=PALETTE["muted"])
    _style_ax(ax, "Cup strength and depletion", "TDS [g/L]")
    _add_time_guides(ax, results)
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8.0, loc="lower right")
    _annotate_endpoint(ax, t[-1], results["TDS_gl"][-1], f"{results['TDS_gl'][-1] / 10:.2f}%", PALETTE["orange"], dx=-52)

    ax = axes[1, 1]
    ax.plot(t, results["EY_cup_pct"], color=PALETTE["teal"], lw=2.4, label="In cup")
    ax.plot(t, results["EY_dissolved_pct"], color="#7fb7ad", lw=1.7, ls="--", label="Dissolved from solid")
    ax.fill_between(
        t, results["EY_cup_pct"], results["EY_dissolved_pct"],
        alpha=0.18, color="#7fb7ad", label="Retained in bed",
    )
    ax.axhspan(18, 22, alpha=0.10, color=PALETTE["lime"], label="SCA target")
    _style_ax(ax, "Extraction yield split", "Extraction Yield [%]")
    _add_time_guides(ax, results)
    ax.legend(fontsize=8.0, loc="lower right")
    _annotate_endpoint(ax, t[-1], results["EY_cup_pct"][-1], f"{results['EY_cup_pct'][-1]:.1f}%", PALETTE["teal"], dx=-50)

    _save_fig(fig, save_as, f"TDS 圖表已儲存至 {save_as}")


def compare_grind(protocol: PourProtocol | None = None) -> None:
    """研磨度比較圖。

    What: 左邊看動態曲線，右下角看最終杯子落點。
    Why:  這比把六張小圖塞滿更容易讀出「哪一個 grind 落在合理區間」。
    """
    protocol = latest_protocol(protocol)
    _setup_style()

    configs = latest_grind_configs()
    colors = [PALETTE["green"], PALETTE["blue"], PALETTE["red"]]

    fig, axes = plt.subplots(2, 2, figsize=(14.4, 8.8), constrained_layout=True)
    _summary_band(fig, "Grind Size Comparison", [
        ("Coarse D10", f"{configs['Coarse'].D10 * 1e6:.0f} um"),
        ("Medium D10", f"{configs['Medium'].D10 * 1e6:.0f} um"),
        ("Fine D10", f"{configs['Fine'].D10 * 1e6:.0f} um"),
    ])

    finals = []
    for (label, params), color in zip(configs.items(), colors):
        res = simulate_brew(params, protocol, t_end=180)
        t = res["t"]
        axes[0, 0].plot(t, res["h_mm"], color=color, lw=2.3, label=label)
        axes[0, 1].plot(t, res["q_out_mlps"], color=color, lw=2.3, label=label)
        axes[1, 0].plot(t, res["TDS_gl"], color=color, lw=2.3, label=label)
        finals.append((label, color, res["EY_cup_pct"][-1], res["TDS_gl"][-1], res["brew_time"], res["bypass_ratio"].mean() * 100))
        print(
            f"{label}: TDS={res['TDS_gl'][-1]:.1f} g/L  "
            f"EY={res['EY_cup_pct'][-1]:.1f}%  "
            f"bypass_avg={res['bypass_ratio'].mean()*100:.1f}%"
        )

    _style_ax(axes[0, 0], "Water head by grind", "Water Level [mm]")
    _style_ax(axes[0, 1], "Outflow rate by grind", "Flow Rate [mL/s]")
    _style_ax(axes[1, 0], "Cup TDS trajectory", "TDS [g/L]")
    axes[1, 0].axhspan(11.5, 14.5, alpha=0.12, color=PALETTE["lime"])
    for ax in (axes[0, 0], axes[0, 1], axes[1, 0]):
        ax.legend(fontsize=8.2, loc="best")

    ax = axes[1, 1]
    _style_ax(ax, "Final cup map", "TDS [g/L]", xlabel="Extraction Yield [%]")
    ax.axhspan(11.5, 14.5, alpha=0.12, color=PALETTE["lime"])
    ax.axvspan(18, 22, alpha=0.10, color="#bed5a0")
    ax.text(21.8, 14.35, "target window", fontsize=8.4, color=PALETTE["green"], ha="right", va="top")
    for label, color, ey, tds, brew_t, bypass in finals:
        size = 40 + brew_t * 0.9
        ax.scatter(ey, tds, s=size, color=color, alpha=0.88, edgecolor="white", linewidth=1.0)
        ax.annotate(
            f"{label}\n{brew_t:.0f}s · {bypass:.1f}% bp",
            (ey, tds), xytext=(7, 5), textcoords="offset points",
            fontsize=8.2, color=color,
        )

    _save_fig(fig, "v60_grind.png", "研磨度綜合對比圖已儲存至 v60_grind.png")


def compare_tds_grind(protocol: PourProtocol | None = None) -> None:
    """不同研磨度的濃度與萃取對比圖（保留供獨立呼叫）。"""
    protocol = latest_protocol(protocol)
    _setup_style()

    configs = latest_grind_configs()
    colors = [PALETTE["green"], PALETTE["blue"], PALETTE["red"]]

    fig, axes = plt.subplots(1, 3, figsize=(15, 5.5), constrained_layout=True)
    _summary_band(fig, "Grind vs Extraction Curves", [("View", "Concentration / TDS / EY")])

    for (label, params), color in zip(configs.items(), colors):
        res = simulate_brew(params, protocol, t_end=180)
        axes[0].plot(res["t"], res["C_out_gl"], color=color, lw=2.3, label=label)
        axes[1].plot(res["t"], res["TDS_gl"], color=color, lw=2.3, label=label)
        axes[2].plot(res["t"], res["EY_cup_pct"], color=color, lw=2.3, label=label)

    _style_ax(axes[0], "Outflow concentration", "Concentration [g/L]")
    _style_ax(axes[1], "Cup TDS", "TDS [g/L]")
    _style_ax(axes[2], "Cup EY", "Extraction Yield [%]")
    axes[1].axhspan(11.5, 14.5, alpha=0.12, color=PALETTE["lime"])
    axes[2].axhspan(18, 22, alpha=0.10, color=PALETTE["lime"])
    for ax in axes:
        ax.legend(fontsize=8.2, loc="best")

    _save_fig(fig, "v60_tds_grind.png", "TDS 研磨度對比圖已儲存至 v60_tds_grind.png")


def compare_corrections(protocol: PourProtocol | None = None) -> None:
    """基礎修正影響量級圖。"""
    protocol = latest_protocol(protocol)
    _setup_style()

    scenarios = latest_correction_configs()
    colors = ["#9e9487", PALETTE["blue"], PALETTE["red"], PALETTE["green"]]

    fig, axes = plt.subplots(1, 2, figsize=(13.2, 5.4), constrained_layout=True)
    _summary_band(fig, "Correction Impact", [("Purpose", "order of magnitude check")])

    for (label, params), color in zip(scenarios.items(), colors):
        res = simulate_brew(params, protocol, t_end=180)
        axes[0].plot(res["t"], res["h_mm"], color=color, lw=2.2, label=label)
        axes[1].plot(res["t"], res["q_out_mlps"], color=color, lw=2.2, label=label)

    _style_ax(axes[0], "Water level response", "Water Level [mm]")
    _style_ax(axes[1], "Outflow response", "Flow Rate [mL/s]")
    for ax in axes:
        ax.legend(fontsize=8.0, loc="best")

    _save_fig(fig, "v60_corrections.png", "修正對比圖已儲存至 v60_corrections.png")


def compare_grind_sizes(protocol: PourProtocol | None = None) -> None:
    """三種研磨度的水位、流量、旁路對比。"""
    protocol = latest_protocol(protocol)
    _setup_style()

    configs = latest_grind_configs()
    colors = [PALETTE["green"], PALETTE["blue"], PALETTE["red"]]

    fig, axes = plt.subplots(1, 3, figsize=(15, 5.4), constrained_layout=True)
    _summary_band(fig, "Grind Flow Comparison", [("Focus", "head / flow / bypass")])

    for (label, params), color in zip(configs.items(), colors):
        res = simulate_brew(params, protocol, t_end=180)
        axes[0].plot(res["t"], res["h_mm"], color=color, lw=2.2, label=label)
        axes[1].plot(res["t"], res["q_out_mlps"], color=color, lw=2.2, label=label)
        axes[2].plot(res["t"], res["bypass_ratio"] * 100, color=color, lw=2.2, label=label)

    _style_ax(axes[0], "Water head", "Water Level [mm]")
    _style_ax(axes[1], "Outflow", "Flow Rate [mL/s]")
    _style_ax(axes[2], "Bypass ratio", "Bypass [%]")
    for ax in axes:
        ax.legend(fontsize=8.0, loc="best")

    _save_fig(fig, "v60_grind_comparison.png", "研磨度比較圖已儲存至 v60_grind_comparison.png")


def compare_thermal(protocol: PourProtocol | None = None) -> None:
    """不同初始水溫的熱耦合對比。

    What: 用四張圖看溫度衰減、流量、TDS、EY。
    Why:  使用者通常想知道「變熱之後，流動變多少、杯子變多少」。
    """
    protocol = latest_protocol(protocol)
    _setup_style()

    base = latest_calibrated_params()
    configs = {
        "83°C": replace(base, T_brew=356.15),
        "93°C": replace(base, T_brew=366.15),
        "99°C": replace(base, T_brew=372.15),
    }
    colors = [PALETTE["blue"], PALETTE["red"], PALETTE["gold"]]

    fig, axes = plt.subplots(2, 2, figsize=(14.4, 8.8), constrained_layout=True)
    _summary_band(fig, "Thermal Coupling Comparison", [
        ("Cool", "83°C"),
        ("Baseline", "93°C"),
        ("Hot", "99°C"),
    ])

    all_results = []
    for (label, params), color in zip(configs.items(), colors):
        res = simulate_brew(params, protocol, t_end=180)
        all_results.append((label, color, res))
        fast = res["EY_fast_cup_pct"][-1]
        slow = res["EY_slow_cup_pct"][-1]
        ratio = fast / max(fast + slow, 1e-9) * 100
        print(
            f"{label}: TDS={res['TDS_gl'][-1]:.1f} g/L  "
            f"EY={res['EY_cup_pct'][-1]:.1f}%  "
            f"Fast={ratio:.0f}%  "
            f"T_drop={res['T_C'][0] - res['T_C'][-1]:.1f}°C"
        )

    for label, color, res in all_results:
        t = res["t"]
        axes[0, 0].plot(t, res["T_C"], color=color, lw=2.3, label=label)
        axes[0, 1].plot(t, res["q_out_mlps"], color=color, lw=2.3, label=label)
        axes[1, 0].plot(t, res["TDS_gl"], color=color, lw=2.3, label=label)
        axes[1, 1].plot(t, res["EY_cup_pct"], color=color, lw=2.3, label=label)

    _style_ax(axes[0, 0], "Temperature decay in the slurry", "Temperature [°C]")
    _style_ax(axes[0, 1], "Outflow response to temperature", "Flow Rate [mL/s]")
    _style_ax(axes[1, 0], "Cup strength by brew temperature", "TDS [g/L]")
    axes[1, 0].axhspan(11.5, 14.5, alpha=0.12, color=PALETTE["lime"])
    _style_ax(axes[1, 1], "Cup yield by brew temperature", "Extraction Yield [%]")
    axes[1, 1].axhspan(18, 22, alpha=0.10, color=PALETTE["lime"])

    for ax in axes.flat:
        ax.legend(fontsize=8.2, loc="best")

    for _, color, res in all_results:
        _annotate_endpoint(axes[1, 0], res["t"][-1], res["TDS_gl"][-1], f"{res['TDS_gl'][-1] / 10:.2f}%", color, dx=-54)
        _annotate_endpoint(axes[1, 1], res["t"][-1], res["EY_cup_pct"][-1], f"{res['EY_cup_pct'][-1]:.1f}%", color, dx=-50)

    _save_fig(fig, "v60_thermal.png", "熱力學對比圖已儲存至 v60_thermal.png")


def compare_flavor(protocol: PourProtocol | None = None) -> None:
    """Fast/Slow 組分的溫度對比圖。"""
    protocol = latest_protocol(protocol)
    _setup_style()

    base = latest_calibrated_params()
    configs = {
        "83°C": replace(base, T_brew=356.15),
        "93°C": replace(base, T_brew=366.15),
        "99°C": replace(base, T_brew=372.15),
    }
    colors = [PALETTE["blue"], PALETTE["red"], PALETTE["gold"]]

    fig, axes = plt.subplots(2, 3, figsize=(15, 9), constrained_layout=True)
    _summary_band(fig, "Flavor Balance vs Temperature", [("View", "fast vs slow components")])

    print("  溫度       | TDS    | EY     | Fast%  | TDS_fast | TDS_slow")
    print("  " + "-" * 65)
    for (label, params), color in zip(configs.items(), colors):
        res = simulate_brew(params, protocol, t_end=180)
        t = res["t"]
        ey_f = res["EY_fast_cup_pct"][-1]
        ey_s = res["EY_slow_cup_pct"][-1]
        ratio = ey_f / max(ey_f + ey_s, 1e-9) * 100
        print(
            f"  {label}: TDS={res['TDS_gl'][-1]:.1f}  "
            f"EY={res['EY_cup_pct'][-1]:.1f}%  "
            f"Fast={ratio:.0f}%  "
            f"fast_TDS={res['TDS_fast_gl'][-1]:.1f}  "
            f"slow_TDS={res['TDS_slow_gl'][-1]:.1f}"
        )

        axes[0, 0].plot(t, res["EY_fast_cup_pct"], color=color, lw=2.2, label=label)
        axes[0, 1].plot(t, res["EY_slow_cup_pct"], color=color, lw=2.2, label=label)
        axes[0, 2].plot(t, res["TDS_fast_gl"], color=color, lw=2.2, label=label)

        total = res["EY_fast_cup_pct"] + res["EY_slow_cup_pct"]
        total_safe = np.where(total > 0.1, total, 1.0)
        fast_pct = np.where(total > 0.1, res["EY_fast_cup_pct"] / total_safe * 100, 50.0)
        axes[1, 0].plot(t, fast_pct, color=color, lw=2.2, label=label)
        axes[1, 1].plot(t, res["TDS_slow_gl"], color=color, lw=2.2, label=label)
        axes[1, 2].plot(t, res["TDS_gl"], color=color, lw=2.2, label=label)

    titles = [
        "Fast EY (bright / acid)", "Slow EY (bitter / astringent)", "Fast TDS",
        "Fast share in cup", "Slow TDS", "Total TDS",
    ]
    ylabels = ["EY [%]", "EY [%]", "TDS [g/L]", "Fast Share [%]", "TDS [g/L]", "TDS [g/L]"]
    for ax, title, ylabel in zip(axes.flat, titles, ylabels):
        _style_ax(ax, title, ylabel)
        ax.legend(fontsize=8.0, loc="best")

    _save_fig(fig, "v60_flavor.png", "風味組分對比圖已儲存至 v60_flavor.png")


# ── 量測擬合診斷圖（吃 `fitting` 的 `info` dict）──────────────────────────────
# What: 這兩張圖只吃 `fit_k_kbeta_from_flow_profile` / `fit_with_multi_start`
#       回傳的 `info`（含 `t_obs_s` / `retained_obs_ml` / `retention_pred_obs_ml`），
#       不重跑模擬、不載入量測檔。
# Why:  χ² 的兩大項是 volume 與 retention，但舊展示圖只畫 V_out。殘差結構
#       （lag-1 ≈ 0.86）與保水時序是「模型還缺哪個機制」的主要證據面，
#       必須有獨立圖面，否則只能從單一 RMSE 數字猜。

def plot_fit_residuals(info: dict, save_as: str) -> None:
    """
    體積殘差時序圖（殘差 vs t，疊注水速率 q_in）。

    What: 上圖 = 各量測點的 V_out 殘差（模型 − 量測）與 ±1σ 帶，
          疊上由量測 `V_in(t)` 差分得到的注水速率；
          下圖 = 保水殘差，用同一條時間軸對齊。
    Why:  殘差若與注水段落同相位，代表缺的是注水期的機制（衝擊/積水），
          而不是整體滲透率——單看 RMSE 看不出這件事。
    """
    _setup_style()

    t_obs = np.asarray(info["t_obs_s"], dtype=float)
    v_in = np.asarray(info["v_in_obs_ml"], dtype=float)
    fit_mask = np.asarray(info["fit_mask"], dtype=bool)
    v_resid = np.asarray(info["v_pred_obs_ml"], dtype=float) - np.asarray(info["v_out_obs_ml"], dtype=float)
    ret_resid = (np.asarray(info["retention_pred_obs_ml"], dtype=float)
                 - np.asarray(info["retained_obs_ml"], dtype=float))
    bloom_end_s = float(info.get("bloom_end_s", np.nan))
    sigma_v = _measurement_sigma("v_out_ml")
    sigma_ret = _measurement_sigma("retention_ml")

    fig, axes = plt.subplots(2, 1, figsize=(11.5, 7.4), sharex=True,
                             gridspec_kw={"height_ratios": [1.6, 1.0]})
    # 5 欄：`_summary_band` 的欄距 0.145，6 欄會讓最左的框壓到標題上。
    _summary_band(fig, "Fit Residuals", [
        ("reduced chi2", f"{info.get('reduced_chi2', np.nan):.2f}"),
        # F12a：白噪音檢定以標準化殘差 r/σ 計算（fitting.WHITENESS_SUBSET_SIGMA_MAX_ML 的 Why）
        ("DW (r/σ)", f"{info.get('durbin_watson', np.nan):.2f}"),
        ("lag-1 (r/σ)", f"{info.get('residual_lag1', np.nan):+.2f}"),
        ("V RMSE", f"{info.get('rmse_ml', np.nan):.2f} mL"),
        ("ret RMSE", f"{info.get('retention_rmse_ml', np.nan):.2f} mL"),
    ])

    ax = axes[0]
    ax.axhline(0.0, color=PALETTE["grid"], lw=1.2)
    # F9：σ 逐點（σ_V ⊕ q_obs·σ_t）；舊 info 沒有此鍵時退回常數帶。
    sigma_pts = np.asarray(info.get("sigma_v_obs_ml", np.full(t_obs.size, sigma_v)), dtype=float)
    ax.fill_between(t_obs, -sigma_pts, sigma_pts, step="mid", color=PALETTE["grid"], alpha=0.45,
                    label=("±1σ measurement band (per-point level σ ⊕ q·σ_t)"
                           if "t_obs_full_s" in info and len(info["t_obs_full_s"]) > t_obs.size
                           else f"±1σ measurement band (σ_V {sigma_v:.0f} mL ⊕ q·σ_t)"))
    ax.bar(t_obs, v_resid, width=4.8, alpha=0.9,
           color=np.where(fit_mask, PALETTE["red"], PALETTE["muted"]),
           label="Volume residual (model − measured)")
    ax.plot(t_obs, v_resid, color=PALETTE["red"], lw=1.1, alpha=0.55)
    _style_ax(ax, "Cumulative outflow residual vs pour rate", "Residual [mL]")

    # F10：影片版有完整 1 s 序列 → 1 s 殘差細線（診斷）與 1 s 注水率。
    t_full = np.asarray(info.get("t_obs_full_s", t_obs), dtype=float)
    if t_full.size > t_obs.size:
        res_full = (np.asarray(info["v_pred_obs_full_ml"], dtype=float)
                    - np.asarray(info["v_out_obs_full_ml"], dtype=float))
        ax.plot(t_full, np.where(np.asarray(info["fit_mask_full"], dtype=bool), res_full, np.nan),
                color=PALETTE["red"], lw=0.9, alpha=0.4, label="1 s residual (diagnostic)")
        t_q, v_q = t_full, np.asarray(info["v_in_obs_full_ml"], dtype=float)
    else:
        t_q, v_q = t_obs, v_in

    ax_q = ax.twinx()
    t_mid = 0.5 * (t_q[1:] + t_q[:-1])
    q_in = np.diff(v_q) / np.maximum(np.diff(t_q), 1e-12)
    ax_q.fill_between(t_mid, 0.0, q_in, color=PALETTE["gold"], alpha=0.25, step="mid",
                      label="Measured pour rate q_in")
    ax_q.set_ylabel("Pour rate [mL/s]", color=PALETTE["gold"], fontsize=10)
    ax_q.tick_params(axis="y", colors=PALETTE["gold"])
    ax_q.set_ylim(bottom=0.0)
    ax_q.grid(False)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax_q.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=9)
    if np.isfinite(bloom_end_s):
        ax.axvline(bloom_end_s, color=PALETTE["purple"], lw=1.0, ls="--")

    ax = axes[1]
    ax.axhline(0.0, color=PALETTE["grid"], lw=1.2)
    ax.axhspan(-sigma_ret, sigma_ret, color=PALETTE["grid"], alpha=0.45,
               label=f"±1σ measurement band ({sigma_ret:.0f} mL)")
    ax.bar(t_obs, ret_resid, width=4.8, alpha=0.9,
           color=np.where(fit_mask, PALETTE["teal"], PALETTE["muted"]),
           label=f"Retention residual (model − measured), runs z {info.get('runs_z', np.nan):+.2f}")
    ax.plot(t_obs, ret_resid, color=PALETTE["teal"], lw=1.1, alpha=0.55)
    _style_ax(ax, "Total retention residual (bed + hold-up + paper)", "Residual [mL]")
    if np.isfinite(bloom_end_s):
        ax.axvline(bloom_end_s, color=PALETTE["purple"], lw=1.0, ls="--")
    ax.legend(loc="upper left", fontsize=9)
    ax.set_xlim(left=0.0)

    plt.tight_layout(rect=[0, 0, 1, 0.92])
    _save_fig(fig, save_as, f"殘差診斷圖已儲存至 {save_as}")


def plot_retention_comparison(info: dict, save_as: str) -> None:
    """
    保水時序對照圖（模型 retained + hold-up vs 量測 `retained_mass_g`）。

    What: 上圖 = 模型總保水（床內 + 出口暫存 + 濾紙潤濕）與量測保水疊圖，
          並以堆疊面積拆出三個來源；下圖 = 模型 − 量測。
    Why:  保水自 F6b 起**不進 χ²**（量測端的 `retained_mass_g` 是
          `poured − drained` 的代數重排，不是獨立觀測），但它仍是判斷模型
          床內水量對不對的主要診斷；而模型保水由三個來源加總而成，
          不把來源拆開就無法判斷「保水差」是床內 closure 的問題還是觀測層
          常數的問題（`MEASURED_PAPER_HOLDUP_ML` 目前是暫定值）。
          圖上仍畫 ±1σ_ret 帶，作為「差多少算大」的尺標。
    """
    _setup_style()

    sim = info["sim_final"]
    obs_layer = info["obs_layer"]
    t_sim = np.asarray(sim["t"], dtype=float)
    t_obs = np.asarray(info["t_obs_s"], dtype=float)
    ret_obs = np.asarray(info["retained_obs_ml"], dtype=float)
    ret_pred_obs = np.asarray(info["retention_pred_obs_ml"], dtype=float)
    fit_mask = np.asarray(info["fit_mask"], dtype=bool)
    sigma_ret = _measurement_sigma("retention_ml")

    bed = np.asarray(sim.get("retained_ml", np.zeros_like(t_sim)), dtype=float)
    hold = np.asarray(obs_layer["v_hold_ml"], dtype=float)
    w_wet = np.clip(np.asarray(sim.get("w_wet", np.zeros_like(t_sim)), dtype=float), 0.0, 1.0)
    paper = MEASURED_PAPER_HOLDUP_ML * w_wet

    fig, axes = plt.subplots(2, 1, figsize=(11.5, 7.8), sharex=True,
                             gridspec_kw={"height_ratios": [2.0, 1.0]})
    _summary_band(fig, "Retention: Model vs Measured", [
        ("ret RMSE", f"{info.get('retention_rmse_ml', np.nan):.2f} mL"),
        ("final model", f"{info.get('retention_final_model_ml', np.nan):.1f} mL"),
        ("final measured", f"{info.get('retention_final_obs_ml', np.nan):.1f} mL"),
        ("paper hold-up", f"{info.get('paper_holdup_final_ml', np.nan):.1f} mL"),
        ("tau_wet", f"{info.get('tau_wet_s_fit', np.nan):.1f} s"),
    ])

    ax = axes[0]
    ax.stackplot(
        t_sim, bed, hold, paper,
        colors=[PALETTE["blue"], PALETTE["teal"], PALETTE["gold"]], alpha=0.55,
        labels=["Model bed retention", "Dripper outlet hold-up", "Paper / wall hold-up"],
    )
    ax.plot(t_sim, bed + hold + paper, color=PALETTE["ink"], lw=2.2, label="Model total retention")
    t_full = np.asarray(info.get("t_obs_full_s", t_obs), dtype=float)
    if t_full.size > t_obs.size:
        m_full = np.asarray(info["fit_mask_full"], dtype=bool)
        ax.plot(t_full, np.where(m_full, np.asarray(info["retained_obs_full_ml"], dtype=float), np.nan),
                color=PALETTE["orange"], lw=1.2, alpha=0.7, label="Measured retained (video, 1 s)")
    ax.scatter(t_obs[fit_mask], ret_obs[fit_mask], s=42, color=PALETTE["orange"],
               edgecolor="white", linewidth=0.8, zorder=5, label="Measured retained mass")
    ax.scatter(t_obs[~fit_mask], ret_obs[~fit_mask], s=42, color=PALETTE["muted"],
               edgecolor="white", linewidth=0.8, zorder=5, label="Held-out point")
    _style_ax(ax, "Retained water: source decomposition", "Retained [mL]")
    ax.legend(loc="upper left", ncol=2, fontsize=8.8)
    ax.set_ylim(bottom=0.0)

    ax = axes[1]
    ax.axhline(0.0, color=PALETTE["grid"], lw=1.2)
    ax.axhspan(-sigma_ret, sigma_ret, color=PALETTE["grid"], alpha=0.45,
               label=f"±1σ measurement band ({sigma_ret:.0f} mL)")
    ax.bar(t_obs, ret_pred_obs - ret_obs, width=4.8, alpha=0.9,
           color=np.where(fit_mask, PALETTE["red"], PALETTE["muted"]),
           label="Model − measured")
    _style_ax(ax, "Retention residual", "Residual [mL]")
    ax.legend(loc="upper left", fontsize=9)
    ax.set_xlim(left=0.0)

    plt.tight_layout(rect=[0, 0, 1, 0.92])
    _save_fig(fig, save_as, f"保水對照圖已儲存至 {save_as}")


def plot_thermal_video_check(info: dict, save_as: str) -> None:
    """
    同一次沖煮的熱時序：χ² 納入點 + 診斷（F10 診斷、F11 進 χ²）。

    What: 上圖 = 模型分享壺溫 `T_server` vs 影片 LCD 上行；下圖 = 模型出口釋放溫度
          `T_cup` vs LCD 下行。三層標記：
            紅色實心（±σ 誤差棒）= 進 χ² 的時序點（F11，`*_series_mask_full`）；
            橘色小點             = 只進診斷 RMSE 的格（無旗標、窗內）；
            空心灰點             = 旗標格或窗外（不用）。
          上圖另標探頭浸沒液量 V_immersion 與容器耦合門檻對應的時刻。
    Why:  讀圖的人必須分得出「哪些點在約束參數」與「哪些只是揭露」；F11 排除的
          悶蒸 / 第二注段（容器熱容未完全耦合）正是模型最偏的區段，不標出來會被
          誤讀成擬合失敗。
    """
    _setup_style()
    t = np.asarray(info["t_obs_full_s"], dtype=float)
    sim = info["sim_final"]
    obs = info["obs_layer"]
    t_sim = np.asarray(sim["t"], dtype=float)
    zeros = np.zeros(t.size, dtype=bool)
    fig, axes = plt.subplots(2, 1, figsize=(11.5, 7.6), sharex=True)
    srv_n = info.get("server_series_n") or 0
    _summary_band(fig, "Video Thermal Check", [
        ("server in chi2", f"n {srv_n}, RMSE {info.get('server_series_rmse_C') or np.nan:.2f} °C"
                           if srv_n else f"none ({info.get('server_series_qc', 'no_series')})"),
        ("server all (diag)", f"RMSE {info.get('thermal_video_server_rmse_C', np.nan):.2f}, "
                              f"bias {info.get('thermal_video_server_bias_C', np.nan):+.2f} °C"),
        ("outflow check window", f"RMSE {info.get('thermal_video_outflow_gated_rmse_C', np.nan):.2f}, "
                                 f"bias {info.get('thermal_video_outflow_gated_bias_C', np.nan):+.2f} °C"),
        ("outflow in chi2", "yes" if info.get("outflow_temp_series_in_chi2") else "no (out-of-sample)"),
    ])
    v_obs = np.asarray(info.get("v_out_obs_full_ml", np.full(t.size, np.nan)), dtype=float)
    for ax, key_obs, key_mask, key_chi2, sigma_key, series, title, label in (
        (axes[0], "server_temp_obs_C", "thermal_server_mask", "server_series_mask_full",
         "server_temp_series_C", obs["T_server_C"],
         "Server temperature (upper LCD line)", "Model server node T_server"),
        (axes[1], "outflow_temp_obs_C", "thermal_outflow_mask", "outflow_series_mask_full",
         "outflow_temp_series_C", obs["T_cup_C"],
         "Dripper outflow temperature (lower LCD line)", "Model outlet release T_cup"),
    ):
        y = np.asarray(info[key_obs], dtype=float)
        m = np.asarray(info[key_mask], dtype=bool)
        m_chi2 = np.asarray(info.get(key_chi2, zeros), dtype=bool)
        ax.plot(t_sim, np.asarray(series, dtype=float), color=PALETTE["blue"], lw=2.2, label=label)
        ax.scatter(t[m & ~m_chi2], y[m & ~m_chi2], s=14, color=PALETTE["orange"], zorder=4,
                   label="Video reading (diagnostic only)")
        ax.scatter(t[~m & ~m_chi2], y[~m & ~m_chi2], s=16, facecolor="none", edgecolor=PALETTE["muted"],
                   zorder=3, label="Video reading (flagged / out of window)")
        if key_chi2 == "outflow_series_mask_full" and not np.any(m_chi2):
            m_oos = np.asarray(info.get("outflow_series_candidate_mask_full", zeros), dtype=bool)
            if np.any(m_oos):
                ax.scatter(t[m_oos], y[m_oos], s=46, marker="D", facecolor="none",
                           edgecolor=PALETTE["teal"], linewidth=1.3, zorder=5,
                           label="Continuous-outflow window (out-of-sample check)")
        if np.any(m_chi2):
            sig = float(info.get("measurement_sigma", {}).get(sigma_key, np.nan)) \
                if isinstance(info.get("measurement_sigma"), dict) else np.nan
            ax.errorbar(t[m_chi2], y[m_chi2], yerr=None if not np.isfinite(sig) else sig,
                        fmt="o", ms=5.5, color=PALETTE["red"], ecolor=PALETTE["red"], elinewidth=1.0,
                        capsize=2.5, zorder=5, label="Video reading (in chi2, ±1σ)")
        ax.axvline(float(info.get("stop_flow_time_s", np.nan)), color=PALETTE["muted"], lw=1.0, ls=":")
        _style_ax(ax, title, "Temperature [°C]")
        ax.legend(loc="lower right", fontsize=8.4)
        ax.set_xlim(0.0, float(t[-1]) + 10.0)
    # 上圖：探頭浸沒與容器耦合門檻對應的時刻（量測 V_out 首次跨過該液量）。
    for v_key, txt, ls in (("v_immersion_ml", "probe immersed", "--"),
                           ("server_series_min_v_ml", "vessel coupled", "-.")):
        v_thr = info.get(v_key)
        if v_thr is None or not np.isfinite(float(v_thr)) or not np.any(v_obs >= float(v_thr)):
            continue
        t_thr = float(t[np.argmax(v_obs >= float(v_thr))])
        axes[0].axvline(t_thr, color=PALETTE["green"], lw=1.1, ls=ls)
        axes[0].text(t_thr + 1.0, axes[0].get_ylim()[0] + 2.0, f"{txt}\nV = {float(v_thr):.0f} mL",
                     fontsize=8.0, color=PALETTE["green"])
    plt.tight_layout(rect=[0, 0, 1, 0.92])
    _save_fig(fig, save_as, f"影片熱時序診斷圖已儲存至 {save_as}")
