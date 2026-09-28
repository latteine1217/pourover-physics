"""逐列 meta 共識規則（measured_io.meta_consensus）。"""
import unittest

from pour_over.measured_io import load_flow_profile_csv, meta_consensus


def _rows(values_by_key: dict[str, list[str]]) -> list[dict]:
    n = len(next(iter(values_by_key.values())))
    rows = []
    for i in range(n):
        row = {k: v[i] for k, v in values_by_key.items()}
        row.update({"time_mmss": "00:00", "time_s": str(i)})
        rows.append(row)
    return rows


class MetaConsensusTests(unittest.TestCase):
    def test_minority_first_row_is_replaced_and_logged(self):
        rows = _rows({"dripper_mass_g": ["224.1", "123.5", "123.5", "123.5"]})
        meta, fixes = meta_consensus(rows)
        self.assertEqual(meta["dripper_mass_g"], "123.5")
        self.assertEqual(len(fixes), 1)
        self.assertEqual(fixes[0]["field"], "meta:dripper_mass_g")
        self.assertAlmostEqual(fixes[0]["old"], 224.1)
        self.assertAlmostEqual(fixes[0]["new"], 123.5)

    def test_first_row_only_field_is_untouched(self):
        rows = _rows({"final_tds_pct": ["1.36", "", "", ""]})
        meta, fixes = meta_consensus(rows)
        self.assertEqual(meta["final_tds_pct"], "1.36")
        self.assertEqual(fixes, [])

    def test_no_strict_majority_raises(self):
        rows = _rows({"dripper_mass_g": ["224.1", "123.5"]})
        with self.assertRaises(ValueError):
            meta_consensus(rows)

    def test_non_numeric_inconsistency_raises(self):
        rows = _rows({"roast": ["medium", "light", "light"]})
        with self.assertRaises(ValueError):
            meta_consensus(rows)

    def test_real_case_uses_majority_dripper_mass(self):
        """kinu29 4:12 紀錄表首列 224.1、其餘 123.5 → 載入後為 123.5 並留紀錄。"""
        prof = load_flow_profile_csv("data/kinu_29_light/4:12/kinu29_light_20g_flow_profile.csv", source="log")
        self.assertEqual(float(prof["meta"]["dripper_mass_g"]), 123.5)
        self.assertTrue(any(c["field"] == "meta:dripper_mass_g" for c in prof["meta_corrections"]))


if __name__ == "__main__":
    unittest.main()
