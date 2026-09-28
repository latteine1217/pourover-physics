"""
test_psd_invariants.py — PSD 管線不變量

What:
    鎖住 raw CSV 的幾何恆等式、bins 表的歸一化與單調性、shell accessibility
    的定義域與單調性、偵測下限公式，以及 PSD → `V60Params` 的質量守恆。

Why:
    PSD 的絕對尺度曾因寫死的像素縮放而整體偏掉一個量級，且沒有任何測試會失敗。
    這裡的不變量都能在「尺度被誤讀」或「幾何欄位被重新縮放卻沒同步重算」時
    直接失敗，而不必等到 fitting 結果變得不合理才被人注意到。

執行：`uv run python -m unittest discover -s tests`
"""

import csv
import math
import unittest
from pathlib import Path

from pour_over.psd import (
    DEFAULT_BIN_EDGES_MM,
    DEFAULT_SHELL_THICKNESS_MM,
    DETECTION_FLOOR_SURFACE_PX,
    load_psd_raw_csv,
    shell_accessibility_fraction_mm,
)
from pour_over.params import V60Params


PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_CSVS = (
    "data/kinu_29_light/kinu29_PSD_export_data.csv",
    "data/kinu_29_light/4:11/PSD_export_data.csv",
    "data/kinu_29_light/4:12/PSD_export_data.csv",
    "data/kinu_27_light/4:12/PSD_export_data.csv",
    "data/kinu_28_light/4:20/PSD_export_data.csv",
)

BINS_CSVS = (
    "data/kinu29_psd_bins.csv",
    "data/kinu_29_light/4:11/kinu29_psd_bins.csv",
    "data/kinu_29_light/4:12/kinu29_psd_bins.csv",
    "data/kinu_27_light/4:12/kinu27_psd_bins.csv",
    "data/kinu_28_light/4:20/kinu28_psd_bins.csv",
)

CANONICAL_BINS_CSV = "data/kinu_29_light/4:11/kinu29_psd_bins.csv"


def _read_bins(rel_path: str) -> list[dict]:
    with (PROJECT_ROOT / rel_path).open(encoding="utf-8", newline="") as f:
        return [{k: float(v) for k, v in row.items()} for row in csv.DictReader(f)]


class TestRawGeometryIdentities(unittest.TestCase):
    """raw CSV 的欄位恆等式：兩軸為半軸、ROUNDNESS 為 aspect 倒數。"""

    def test_surface_equals_pi_times_semi_axes(self):
        for rel in RAW_CSVS:
            with self.subTest(rel), (PROJECT_ROOT / rel).open(encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    short = float(row["SHORT_AXIS"])
                    long_ = float(row["LONG_AXIS"])
                    surface = float(row["SURFACE"])
                    self.assertAlmostEqual(
                        math.pi * short * long_ / surface, 1.0, places=9,
                        msg="pi * SHORT_AXIS * LONG_AXIS 必須等於 SURFACE（兩軸為半軸）",
                    )

    def test_roundness_is_short_over_long(self):
        for rel in RAW_CSVS:
            with self.subTest(rel), (PROJECT_ROOT / rel).open(encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    short = float(row["SHORT_AXIS"])
                    long_ = float(row["LONG_AXIS"])
                    self.assertAlmostEqual(
                        float(row["ROUNDNESS"]), short / long_, places=9,
                        msg="ROUNDNESS 必須恆等於 SHORT_AXIS / LONG_AXIS",
                    )

    def test_pixel_scale_is_unique_and_positive(self):
        for rel in RAW_CSVS:
            with self.subTest(rel):
                raw = load_psd_raw_csv(PROJECT_ROOT / rel)
                self.assertGreater(raw["pixel_scale_px_per_mm"], 0.0)
                with (PROJECT_ROOT / rel).open(encoding="utf-8", newline="") as f:
                    scales = {float(r["PIXEL_SCALE"]) for r in csv.DictReader(f)}
                self.assertEqual(len(scales), 1, "PIXEL_SCALE 必須全檔唯一")

    def test_detection_floor_formula(self):
        for rel in RAW_CSVS:
            with self.subTest(rel):
                raw = load_psd_raw_csv(PROJECT_ROOT / rel)
                expected = (
                    2.0 * math.sqrt(DETECTION_FLOOR_SURFACE_PX / math.pi)
                    / raw["pixel_scale_px_per_mm"]
                )
                self.assertAlmostEqual(raw["detection_floor_mm"], expected, places=12)
                self.assertEqual(raw["min_surface_px"], DETECTION_FLOOR_SURFACE_PX)

    def test_missing_pixel_scale_raises(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
            f.write("ID,SURFACE,ROUNDNESS,SHORT_AXIS,LONG_AXIS,VOLUME\n0,104.0,0.7,4.87,6.79,506.9\n")
            path = f.name
        with self.assertRaises(ValueError):
            load_psd_raw_csv(path)
        Path(path).unlink()


class TestBinsTable(unittest.TestCase):
    """bins CSV 的歸一化、單調性與 shell accessibility 定義域。"""

    def test_fractions_sum_to_one(self):
        for rel in BINS_CSVS:
            with self.subTest(rel):
                rows = _read_bins(rel)
                for key in ("num_fraction", "volume_fraction", "area_fraction"):
                    self.assertAlmostEqual(sum(r[key] for r in rows), 1.0, places=9, msg=key)

    def test_diameter_mid_is_increasing(self):
        for rel in BINS_CSVS:
            with self.subTest(rel):
                mids = [r["d_mid_mm"] for r in _read_bins(rel)]
                self.assertEqual(mids, sorted(mids))
                self.assertEqual(len(set(mids)), len(mids))

    def test_shell_accessibility_in_range_and_decreasing(self):
        for rel in BINS_CSVS:
            with self.subTest(rel):
                rows = _read_bins(rel)
                shells = [r["shell_accessibility_volume_weighted"] for r in rows]
                for value in shells:
                    self.assertGreaterEqual(value, 0.0)
                    self.assertLessEqual(value, 1.0)
                # 粒徑越大，200 μm 殼層占比越小（非嚴格遞減：小粒徑段飽和在 1.0）
                self.assertEqual(shells, sorted(shells, reverse=True))

    def test_censored_flag_matches_detection_floor(self):
        pairs = zip(RAW_CSVS, ("data/kinu29_psd_bins.csv",) + BINS_CSVS[1:])
        for raw_rel, bins_rel in pairs:
            with self.subTest(bins_rel):
                floor = load_psd_raw_csv(PROJECT_ROOT / raw_rel)["detection_floor_mm"]
                for row in _read_bins(bins_rel):
                    self.assertEqual(bool(row["censored"]), row["d_lo_mm"] < floor)

    def test_bin_edges_come_from_default_set(self):
        allowed = set(DEFAULT_BIN_EDGES_MM)
        for rel in BINS_CSVS:
            with self.subTest(rel):
                for row in _read_bins(rel):
                    self.assertIn(row["d_lo_mm"], allowed)
                    self.assertIn(row["d_hi_mm"], allowed)


class TestShellAccessibilityFunction(unittest.TestCase):
    """shell accessibility 的解析定義。"""

    def test_range_and_monotonicity(self):
        diameters = [0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2]
        values = [shell_accessibility_fraction_mm(d, DEFAULT_SHELL_THICKNESS_MM) for d in diameters]
        for value in values:
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)
        self.assertEqual(values, sorted(values, reverse=True))

    def test_fully_accessible_below_twice_shell_thickness(self):
        # d <= 2·shell → 整顆都在殼層內
        self.assertAlmostEqual(shell_accessibility_fraction_mm(0.4, 0.2), 1.0, places=12)
        self.assertLess(shell_accessibility_fraction_mm(0.5, 0.2), 1.0)


class TestParamsIngest(unittest.TestCase):
    """PSD → `V60Params` 的質量守恆與尺度來源。"""

    def setUp(self):
        self.params = V60Params(
            psd_bins_csv_path=str(PROJECT_ROOT / CANONICAL_BINS_CSV),
            h_bed=0.053,
        )

    def test_bin_resolved_mass_conserves_total(self):
        total = float(sum(self.params.M_fast_0_bins) + sum(self.params.M_slow_0_bins))
        self.assertAlmostEqual(total, self.params.M_sol_0, places=12)

    def test_diameter_scale_defaults_to_one(self):
        self.assertEqual(self.params.psd_diameter_scale, 1.0)
        self.assertFalse(hasattr(self.params, "particle_scale"))

    def test_d10_override_does_not_rescale_geometry(self):
        shifted = V60Params(
            psd_bins_csv_path=str(PROJECT_ROOT / CANONICAL_BINS_CSV),
            h_bed=0.053,
            D10_measured_m=2.0 * self.params.D10,
        )
        self.assertAlmostEqual(shifted.d32, self.params.d32, places=12)
        self.assertAlmostEqual(shifted.surface_area_spec, self.params.surface_area_spec, places=9)
        self.assertAlmostEqual(shifted.shell_fraction_abs, self.params.shell_fraction_abs, places=12)

    def test_explicit_diameter_scale_moves_d32(self):
        scaled = V60Params(
            psd_bins_csv_path=str(PROJECT_ROOT / CANONICAL_BINS_CSV),
            h_bed=0.053,
            psd_diameter_scale=2.0,
        )
        self.assertAlmostEqual(scaled.d32 / self.params.d32, 2.0, places=9)

    def test_relative_ratios_are_self_referenced(self):
        self.assertAlmostEqual(self.params.surface_area_ratio, 1.0, places=12)
        self.assertAlmostEqual(self.params.shell_accessibility_ratio, 1.0, places=12)

    def test_k_beta_prior_is_independent_of_k_beta(self):
        other = V60Params(
            psd_bins_csv_path=str(PROJECT_ROOT / CANONICAL_BINS_CSV),
            h_bed=0.053,
            k_beta=3.0 * self.params.k_beta,
        )
        self.assertAlmostEqual(other.k_beta_prior_psd, self.params.k_beta_prior_psd, places=6)


if __name__ == "__main__":
    unittest.main()
