"""
psd.py — 影像量測 PSD 後處理

What:
    將粒子影像匯出的 raw CSV 與 stats CSV 整理成可直接放入模型的
    bin-resolved PSD 表與摘要欄位。

Why:
    raw CSV 的長度單位由 `PIXEL_SCALE` 決定，先前寫死的 /5、/10、/100、/1000
    等價於假設 100 μm/px，與實際 27–58 μm/px 差一個量級，會讓整條 PSD 的
    絕對尺度失真。本檔把絕對尺度統一交給 `PIXEL_SCALE`，並在缺欄或欄位
    不唯一時直接 raise（Fail Fast），不允許靜默回退。

raw CSV 幾何恆等式（已由五份掃描逐列驗證到機器精度）：
    π · SHORT_AXIS · LONG_AXIS = SURFACE      → 兩軸為「半軸」，單位 px
    ROUNDNESS ≡ SHORT_AXIS / LONG_AXIS        → roundness 是 aspect 的倒數
    VOLUME = SURFACE × SHORT_AXIS             → 匯出軟體的偽 3D 體積，本檔不採用
    min(SURFACE) = 5 px²                      → 硬偵測下限，決定 detection floor

`PIXEL_SCALE` 的單位是 px/mm（非 μm/px）。判據：μm/px 讀法下 canonical 掃描
最大顆粒僅 655 μm，小於軟體自報的 AVG_DIAM 881 μm（不可能）；px/mm 讀法下
同一研磨度的兩張掃描 Dv50 = 999 / 1166 μm，彼此自洽。
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path

DEFAULT_SHELL_THICKNESS_MM = 0.03
# 破壁殼層厚度 [mm]，`params.V60Params.shell_thickness` 的唯一來源。
# What: 研磨時細胞壁破裂、溶質直接對孔隙液開放的表層深度。
# Why:  咖啡細胞約 20–40 μm（Moroney et al. 2019），破壁層約一層細胞深；取 30 μm。
#       舊值 0.2 mm（5–10 層細胞）讓 canonical fast pool 佔可萃質量 69%，與雙孔隙
#       文獻的機制不符（EXP-20261007-EXTRACTION-CLOSURE-REWRITE）。

# What: 模型使用的固定 bin 邊界 [mm]。
# Why:  最細兩個 bin（0.075–0.125、0.125–0.25）覆蓋 fines，是堵塞閉合的主要來源；
#       高解析度 per-case 掃描（27–29 μm/px）能解析到 0.069 mm，低倍率 canonical
#       掃描（58 μm/px）只能到 0.146 mm，因此最細 bin 必須被標記為 censored 而非
#       當成「真的沒有細粉」。
DEFAULT_BIN_EDGES_MM = (0.075, 0.125, 0.25, 0.40, 0.55, 0.75, 1.00, 1.40, 2.00, 3.00)

# 影像偵測的最小連通面積 [px²]；五份掃描一致，為軟體硬下限。
DETECTION_FLOOR_SURFACE_PX = 5.0

# stats CSV 的 AVG_DIAM 定義交叉驗證容差（見 `_cross_check_against_stats`）。
STATS_BRACKET_TOLERANCE = 0.05


def _quantile(values: list[float], prob: float) -> float:
    """線性內插分位數。"""
    xs = sorted(float(v) for v in values)
    if not xs:
        raise ValueError("空的數列無法計算分位數")
    idx = (len(xs) - 1) * float(prob)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return xs[lo]
    w = idx - lo
    return xs[lo] * (1.0 - w) + xs[hi] * w


def _weighted_quantile(values: list[float], weights: list[float], prob: float) -> float:
    """加權分位數；權重需為非負。"""
    pairs = sorted((float(v), max(float(w), 0.0)) for v, w in zip(values, weights))
    total = sum(w for _, w in pairs)
    if total <= 0:
        return _quantile(values, prob)
    target = float(prob) * total
    accum = 0.0
    for value, weight in pairs:
        accum += weight
        if accum >= target:
            return value
    return pairs[-1][0]


def shell_accessibility_fraction_mm(
    diameter_mm: float,
    shell_thickness_mm: float = DEFAULT_SHELL_THICKNESS_MM,
) -> float:
    """
    固定殼層厚度下的可及體積比例。

    What: 將顆粒視為等效球，回傳最外層 `shell_thickness_mm` 的體積占比 ∈ [0, 1]。
    Why:  這是 PSD 表與 `params.py` 萃取幾何共用的唯一定義；先前兩處各寫一份，
          一旦 bins CSV 被縮放就會與 CSV 內的欄位不一致。
    """
    radius = 0.5 * max(float(diameter_mm), 1e-12)
    shell = min(max(float(shell_thickness_mm), 0.0), radius)
    core_radius = max(radius - shell, 0.0)
    return 1.0 - (core_radius / radius) ** 3


def _project_root() -> Path:
    """Project root（與 `data/` 同層）。"""
    return Path(__file__).resolve().parents[1]


def _relative_to_project(path: str | Path) -> str:
    """回傳相對專案根的路徑字串；不在專案內時回傳絕對路徑。"""
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(_project_root()))
    except ValueError:
        return str(resolved)


def load_psd_raw_csv(raw_csv_path: str | Path) -> dict:
    """
    讀取 PSD raw CSV 並換算成物理單位。

    What:
        回傳 {"particles": [...], "pixel_scale_px_per_mm", "um_per_px",
              "detection_floor_mm", "min_surface_px", "particle_count"}。
        每顆粒子的欄位皆以 mm / mm² / mm³ 表示：
            d_eq_mm          = 2·sqrt(SHORT·LONG) / PIXEL_SCALE   （面積等效全直徑）
            short/long_axis  = 2·axis / PIXEL_SCALE               （全直徑，非半軸）
            surface_mm2      = SURFACE / PIXEL_SCALE²
            volume_mm3       = (π/6)·d_eq³                        （球等效）
            surface_to_volume= 6 / d_eq

    Why:
        絕對尺度只能來自 `PIXEL_SCALE`；缺欄、多值或非正值都代表這份匯出
        無法定義長度，必須立刻失敗而不是套一個猜測的縮放。
        體積刻意不用 raw 的 `VOLUME` 欄（= SURFACE × SHORT_AXIS 的偽 3D 量）：
        該定義對長條顆粒系統性低估，且與 `surface_to_volume = 6/d` 不自洽。
    """
    path = Path(raw_csv_path)
    particles: list[dict] = []
    scales: set[float] = set()
    min_surface_px = math.inf

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "PIXEL_SCALE" not in reader.fieldnames:
            raise ValueError(
                f"PSD raw CSV 缺少 PIXEL_SCALE 欄位，無法決定絕對長度尺度：{path}"
            )
        for row in reader:
            scales.add(float(row["PIXEL_SCALE"]))
            short_axis_px = float(row["SHORT_AXIS"])
            long_axis_px = float(row["LONG_AXIS"])
            surface_px2 = float(row["SURFACE"])
            min_surface_px = min(min_surface_px, surface_px2)
            particles.append({
                "short_axis_px": short_axis_px,
                "long_axis_px": long_axis_px,
                "surface_px2": surface_px2,
            })

    if not particles:
        raise ValueError(f"空的 PSD raw CSV：{path}")
    if len(scales) != 1:
        raise ValueError(
            f"PSD raw CSV 的 PIXEL_SCALE 不唯一（{sorted(scales)}）：{path}"
        )
    pixel_scale = scales.pop()
    if not math.isfinite(pixel_scale) or pixel_scale <= 0.0:
        raise ValueError(f"PSD raw CSV 的 PIXEL_SCALE 必須為正值，實得 {pixel_scale}：{path}")

    for p in particles:
        short_px = p.pop("short_axis_px")
        long_px = p.pop("long_axis_px")
        surface_px2 = p.pop("surface_px2")
        d_eq_mm = 2.0 * math.sqrt(short_px * long_px) / pixel_scale
        aspect_ratio = long_px / max(short_px, 1e-12)
        p.update({
            "diameter_eq_mm": d_eq_mm,
            "short_axis_mm": 2.0 * short_px / pixel_scale,
            "long_axis_mm": 2.0 * long_px / pixel_scale,
            "surface_mm2": surface_px2 / (pixel_scale ** 2),
            "volume_mm3": (math.pi / 6.0) * d_eq_mm ** 3,
            "surface_to_volume_mm_inv": 6.0 / max(d_eq_mm, 1e-12),
            "aspect_ratio": aspect_ratio,
            # roundness 為 derived 量：raw CSV 的 ROUNDNESS ≡ SHORT/LONG ≡ 1/aspect_ratio
            # （已逐列驗證到機器精度），因此不再讀該欄，避免下游誤以為是獨立形狀資訊。
            "roundness": 1.0 / max(aspect_ratio, 1e-12),
        })

    return {
        "particles": particles,
        "particle_count": len(particles),
        "pixel_scale_px_per_mm": pixel_scale,
        "um_per_px": 1000.0 / pixel_scale,
        "min_surface_px": float(min_surface_px),
        "detection_floor_mm": 2.0 * math.sqrt(DETECTION_FLOOR_SURFACE_PX / math.pi) / pixel_scale,
    }


def load_psd_stats_csv(stats_csv_path: str | Path) -> dict:
    """
    讀取 PSD stats CSV。

    What: 讀取外部軟體輸出的總表，保留平均直徑/表面積供定義交叉檢查。
    Why:  軟體的 AVG_DIAM 定義未公開，只能當成獨立的尺度證人，不能拿來校正我們的換算。
    """
    path = Path(stats_csv_path)
    with path.open("r", encoding="utf-8", newline="") as f:
        row = next(csv.DictReader(f))
    return {
        "stats_avg_diam_mm": float(row["AVG_DIAM"]),
        "stats_std_diam_mm": float(row["STD_DIAM"]),
        "stats_avg_surf_mm2": float(row["AVG_SURF"]),
        "stats_std_surf_mm2": float(row["STD_SURF"]),
        "stats_eff_pct": float(row["EFF"]),
        "stats_quality": float(row["QUAL"]),
    }


def _cross_check_against_stats(summary: dict, stats: dict) -> dict:
    """
    以 stats CSV 對我們的絕對尺度做定義交叉驗證。

    What:
        檢查軟體自報的 AVG_DIAM 是否落在我們算出的 [d32, D43] 區間內
        （容差 `STATS_BRACKET_TOLERANCE`），並記錄變異係數供判讀。

    Why:
        軟體的 AVG_DIAM 既非 number mean（差 1.8–2.4 倍）也非 (s+l) 之類的
        簡單重算，五份掃描一致落在 Sauter 平均 d32 與體積加權平均 D43 之間
        （AVG_DIAM/d32 = 1.055–1.092）。任何「加權平均直徑」都必然落在這兩個
        矩平均之間，因此這個 bracket 是不依賴軟體內部定義、卻對絕對尺度
        敏感的檢查：若 PIXEL_SCALE 被誤讀成 μm/px，尺度會差三個量級而立刻失敗。

        變異係數（STD_DIAM/AVG_DIAM）只記錄不設門檻：我們的 number CV 為
        0.57–0.75，軟體回報 0.41–0.50，差異來自未知的加權/濾除規則，
        以此設 ±5% 門檻會在全部五份檔案上誤報。
    """
    avg = stats["stats_avg_diam_mm"]
    lo = summary["model_d32_mm"] * (1.0 - STATS_BRACKET_TOLERANCE)
    hi = summary["model_D43_mm"] * (1.0 + STATS_BRACKET_TOLERANCE)
    if not (lo <= avg <= hi):
        raise ValueError(
            "PSD 絕對尺度與 stats CSV 不自洽："
            f"AVG_DIAM = {avg:.4f} mm 未落在 [d32, D43] = "
            f"[{summary['model_d32_mm']:.4f}, {summary['model_D43_mm']:.4f}] mm "
            f"(±{STATS_BRACKET_TOLERANCE:.0%})；請檢查 PIXEL_SCALE 單位"
        )
    return {
        "stats_avg_diam_over_d32": avg / max(summary["model_d32_mm"], 1e-12),
        "stats_avg_diam_over_D43": avg / max(summary["model_D43_mm"], 1e-12),
        "stats_cv_diam": stats["stats_std_diam_mm"] / max(avg, 1e-12),
        "stats_cv_surf": stats["stats_std_surf_mm2"] / max(stats["stats_avg_surf_mm2"], 1e-12),
    }


def infer_psd_summary(
    raw_csv_path: str | Path,
    stats_csv_path: str | Path | None = None,
) -> dict:
    """
    由 PSD 量測輸出生成模型摘要。

    What:
        輸出三組尺度：number-based（D10/D50/D90，resolution-bounded）、
        volume-based（Dv10/Dv50/Dv90、D43）與 area-based（Da*、Sauter d32），
        外加 fines 比例、形狀統計與量測解析度中繼資料。

    Why:
        number-based D10 落在整數像素格點上（SURFACE = 11 px → 0.3742 mm、
        21 px → 0.5171 mm，三份 per-case 掃描給出完全相同的值），是偵測下限的
        artifact，不得再當模型的尺度錨點。模型尺度改用 Sauter d32（決定比表面積）
        與 Dv50（決定體積中位粒徑），兩者都由粗端主導，對偵測下限不敏感。
    """
    raw = load_psd_raw_csv(raw_csv_path)
    particles = raw["particles"]
    stats = load_psd_stats_csv(stats_csv_path) if stats_csv_path else {}

    d_eq = [p["diameter_eq_mm"] for p in particles]
    volumes = [p["volume_mm3"] for p in particles]
    areas = [p["surface_mm2"] for p in particles]
    aspects = [p["aspect_ratio"] for p in particles]
    roundness = [p["roundness"] for p in particles]

    sum_d2 = sum(d ** 2 for d in d_eq)
    sum_d3 = sum(d ** 3 for d in d_eq)
    sum_d4 = sum(d ** 4 for d in d_eq)
    d32_mm = sum_d3 / max(sum_d2, 1e-18)
    d43_mm = sum_d4 / max(sum_d3, 1e-18)
    total_volume = max(sum(volumes), 1e-18)

    raw_path = Path(raw_csv_path)
    summary = {
        "raw_csv_path": _relative_to_project(raw_path),
        "raw_csv_mtime": raw_path.stat().st_mtime,
        "stats_csv_path": _relative_to_project(stats_csv_path) if stats_csv_path else "",
        "particle_count": raw["particle_count"],
        "pixel_scale_px_per_mm": raw["pixel_scale_px_per_mm"],
        "um_per_px": raw["um_per_px"],
        "min_surface_px": raw["min_surface_px"],
        "detection_floor_mm": raw["detection_floor_mm"],
        "diameter_definition": "d_eq_mm = 2*sqrt(SHORT_AXIS*LONG_AXIS)/PIXEL_SCALE",
        "volume_definition": "volume_mm3 = (pi/6)*d_eq_mm**3",
        # number-based：僅供診斷；受偵測下限鉗制
        "resolution_bounded": True,
        "model_avg_diam_mm": statistics.fmean(d_eq),
        "model_D10_mm": _quantile(d_eq, 0.10),
        "model_D50_mm": _quantile(d_eq, 0.50),
        "model_D90_mm": _quantile(d_eq, 0.90),
        # volume-based：模型主尺度
        "model_Dv10_mm": _weighted_quantile(d_eq, volumes, 0.10),
        "model_Dv50_mm": _weighted_quantile(d_eq, volumes, 0.50),
        "model_Dv90_mm": _weighted_quantile(d_eq, volumes, 0.90),
        "model_D43_mm": d43_mm,
        # area-based：Sauter 平均決定比表面積
        "model_d32_mm": d32_mm,
        "model_Da10_mm": _weighted_quantile(d_eq, areas, 0.10),
        "model_Da50_mm": _weighted_quantile(d_eq, areas, 0.50),
        "model_Da90_mm": _weighted_quantile(d_eq, areas, 0.90),
        "fines_num_lt_0p25mm": sum(d < 0.25 for d in d_eq) / len(d_eq),
        "fines_num_lt_0p40mm": sum(d < 0.40 for d in d_eq) / len(d_eq),
        "fines_vol_lt_0p25mm": sum(v for d, v in zip(d_eq, volumes) if d < 0.25) / total_volume,
        "fines_vol_lt_0p40mm": sum(v for d, v in zip(d_eq, volumes) if d < 0.40) / total_volume,
        "aspect_ratio_mean": statistics.fmean(aspects),
        "aspect_ratio_median": _quantile(aspects, 0.50),
        "aspect_ratio_p90": _quantile(aspects, 0.90),
        "roundness_mean": statistics.fmean(roundness),
        "roundness_median": _quantile(roundness, 0.50),
        "roundness_p10": _quantile(roundness, 0.10),
        # 模型入口：尺度錨點改為 Sauter d32 與體積中位徑，不再輸出 recommended_D10
        "model_d32_m": d32_mm / 1000.0,
        "model_Dv50_m": _weighted_quantile(d_eq, volumes, 0.50) / 1000.0,
        "model_D10_m": _quantile(d_eq, 0.10) / 1000.0,
    }

    if stats:
        summary.update(stats)
        summary.update(_cross_check_against_stats(summary, stats))
    return summary


def infer_psd_bins(
    raw_csv_path: str | Path,
    bin_edges_mm: tuple[float, ...] = DEFAULT_BIN_EDGES_MM,
    shell_thickness_mm: float = DEFAULT_SHELL_THICKNESS_MM,
) -> list[dict]:
    """
    將實測 PSD 彙整為 multi-bin 表。

    What:
        依 `diameter_eq_mm` 分桶，每個 bin 輸出 number / area / volume fraction、
        平均粒徑、形狀統計、比表面積（6/d）與 shell accessibility，
        並以 `censored` 標記 bin 下緣低於偵測下限者。

    Why:
        流動、堵塞與萃取不是由單一 D10 決定。`censored` 是必要的誠實標記：
        低倍率掃描的最細 bin 為空不代表沒有細粉，只代表看不到；下游若要
        比較不同解析度的掃描，必須知道哪些 bin 的 fraction 是被截斷的。
        fraction 以「落入 bin 範圍內的顆粒」為母體正規化，使各欄各自和為 1。
    """
    if len(bin_edges_mm) < 2:
        raise ValueError("bin_edges_mm 至少需要兩個邊界")

    raw = load_psd_raw_csv(raw_csv_path)
    particles = raw["particles"]
    detection_floor_mm = raw["detection_floor_mm"]

    lo_edge, hi_edge = float(bin_edges_mm[0]), float(bin_edges_mm[-1])
    in_range = [p for p in particles if lo_edge <= p["diameter_eq_mm"] < hi_edge]
    if not in_range:
        raise ValueError(f"沒有顆粒落在 bin 範圍 [{lo_edge}, {hi_edge}) mm：{raw_csv_path}")

    total_count = len(in_range)
    total_area = sum(p["surface_mm2"] for p in in_range)
    total_volume = sum(p["volume_mm3"] for p in in_range)

    bins: list[dict] = []
    for idx, (lo, hi) in enumerate(zip(bin_edges_mm[:-1], bin_edges_mm[1:])):
        bucket = [p for p in in_range if lo <= p["diameter_eq_mm"] < hi]
        if not bucket:
            continue

        area_sum = sum(p["surface_mm2"] for p in bucket)
        volume_sum = sum(p["volume_mm3"] for p in bucket)
        eq_diams = [p["diameter_eq_mm"] for p in bucket]
        shell_fracs = [
            shell_accessibility_fraction_mm(d, shell_thickness_mm=shell_thickness_mm)
            for d in eq_diams
        ]
        sv_list = [p["surface_to_volume_mm_inv"] for p in bucket]

        bins.append({
            "bin_index": idx,
            "d_lo_mm": lo,
            "d_hi_mm": hi,
            "d_mid_mm": 0.5 * (lo + hi),
            "censored": int(lo < detection_floor_mm),
            "particle_count": len(bucket),
            "num_fraction": len(bucket) / total_count,
            "area_fraction": area_sum / max(total_area, 1e-18),
            "volume_fraction": volume_sum / max(total_volume, 1e-18),
            "diameter_eq_mean_mm": statistics.fmean(eq_diams),
            "diameter_eq_median_mm": _quantile(eq_diams, 0.50),
            "aspect_ratio_mean": statistics.fmean(p["aspect_ratio"] for p in bucket),
            "roundness_mean": statistics.fmean(p["roundness"] for p in bucket),
            "surface_to_volume_mm_inv_mean": statistics.fmean(sv_list),
            # 體積加權 S/V 才滿足 Σ(vol_frac · sv) = 6/d32；比表面積必須用這一欄。
            "surface_to_volume_mm_inv_vol_weighted": (
                sum(sv * p["volume_mm3"] for sv, p in zip(sv_list, bucket)) / max(volume_sum, 1e-18)
            ),
            "shell_accessibility_mean": statistics.fmean(shell_fracs),
            "shell_accessibility_volume_weighted": (
                sum(sf * p["volume_mm3"] for sf, p in zip(shell_fracs, bucket)) / max(volume_sum, 1e-18)
            ),
        })

    if not bins:
        raise ValueError("PSD 分桶結果為空，請檢查 bin_edges_mm 是否合理")
    return bins


def psd_overrides_for_model(summary: dict, bins_csv_path: str | Path | None = None) -> dict:
    """
    將 PSD 摘要轉成模型 override。

    What: 回傳模型可直接接收的最小 override 集。
    Why:  絕對尺度由 bins CSV 決定，因此 override 只需指定 bins 路徑；
          `D10_measured_m` 僅作診斷欄位帶入，不再縮放任何幾何量。
    """
    overrides: dict = {"D10_measured_m": float(summary["model_D10_m"])}
    if bins_csv_path is not None:
        overrides["psd_bins_csv_path"] = str(Path(bins_csv_path))
    return overrides


def save_psd_summary_csv(output_path: str | Path, summary: dict) -> None:
    """將 PSD 摘要寫成單列 CSV。"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary.keys()))
        writer.writeheader()
        writer.writerow(summary)


def save_psd_bins_csv(output_path: str | Path, bins: list[dict]) -> None:
    """將 multi-bin PSD 表寫成 CSV。"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(bins[0].keys()))
        writer.writeheader()
        writer.writerows(bins)


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Convert PSD CSV exports into model-ready bins and summary.")
    parser.add_argument("--raw", required=True, help="Path to raw PSD CSV")
    parser.add_argument("--stats", default=None, help="Stats CSV from the same export")
    parser.add_argument("--out-bins", required=True, help="Output multi-bin PSD CSV path")
    parser.add_argument("--out-summary", required=True, help="Output summary CSV path")
    parser.add_argument(
        "--shell-thickness-mm",
        type=float,
        default=DEFAULT_SHELL_THICKNESS_MM,
        help="Accessible shell thickness used in the multi-bin table",
    )
    args = parser.parse_args()

    summary = infer_psd_summary(args.raw, args.stats)
    bins = infer_psd_bins(args.raw, shell_thickness_mm=args.shell_thickness_mm)
    save_psd_bins_csv(args.out_bins, bins)
    save_psd_summary_csv(args.out_summary, summary)

    print("=== PSD Summary ===")
    print(f"  Raw CSV            : {summary['raw_csv_path']}")
    print(f"  Particle count     : {summary['particle_count']}")
    print(f"  Pixel scale        : {summary['pixel_scale_px_per_mm']:.4f} px/mm ({summary['um_per_px']:.1f} um/px)")
    print(f"  Detection floor    : {summary['detection_floor_mm']*1000:.1f} um")
    print(f"  Dn10 / Dn50 / Dn90 : {summary['model_D10_mm']:.3f} / {summary['model_D50_mm']:.3f} / {summary['model_D90_mm']:.3f} mm (resolution-bounded)")
    print(f"  Dv10 / Dv50 / Dv90 : {summary['model_Dv10_mm']:.3f} / {summary['model_Dv50_mm']:.3f} / {summary['model_Dv90_mm']:.3f} mm")
    print(f"  Sauter d32 / D43   : {summary['model_d32_mm']:.3f} / {summary['model_D43_mm']:.3f} mm")
    print(f"  Fines <0.25 mm     : {summary['fines_num_lt_0p25mm']*100:.1f}% number / {summary['fines_vol_lt_0p25mm']*100:.2f}% volume")
    print(f"  Fines <0.40 mm     : {summary['fines_num_lt_0p40mm']*100:.1f}% number / {summary['fines_vol_lt_0p40mm']*100:.2f}% volume")
    print(f"  Aspect median / p90: {summary['aspect_ratio_median']:.2f} / {summary['aspect_ratio_p90']:.2f}")
    if "stats_avg_diam_mm" in summary:
        print(f"  Stats AVG_DIAM     : {summary['stats_avg_diam_mm']:.3f} mm "
              f"(d32 x {summary['stats_avg_diam_over_d32']:.3f}, D43 x {summary['stats_avg_diam_over_D43']:.3f})")
    print(f"  Multi-bin rows     : {len(bins)} (censored: {sum(b['censored'] for b in bins)})")
    print(f"  Bin output         : {args.out_bins}")
    print(f"  Summary output     : {args.out_summary}")


if __name__ == "__main__":
    _cli()
