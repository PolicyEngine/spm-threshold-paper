"""Properties of scripts/rent_sensitivity.py and the receipt it writes.

The helpers use the standard library only, and the receipt checks read
committed JSON, so these tests run without spm-calculator.
"""

import hashlib
import json
import math
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import rent_sensitivity as rs  # noqa: E402
from inkind_inputs import RECEIPT_PINS, REPLICATION  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HelperProperties(unittest.TestCase):
    def test_part_period_bounds_are_inclusive(self):
        self.assertTrue(rs.part_period(25.0, 100.0))
        self.assertTrue(rs.part_period(75.0, 100.0))
        self.assertTrue(rs.part_period(50.0, 100.0))
        self.assertFalse(rs.part_period(24.9, 100.0))
        self.assertFalse(rs.part_period(75.1, 100.0))
        self.assertFalse(rs.part_period(100.0, 100.0))

    def test_part_period_needs_a_positive_finite_next_rent(self):
        for next_rent in (0.0, -10.0, math.nan, math.inf):
            self.assertFalse(rs.part_period(50.0, next_rent))
        self.assertFalse(rs.part_period(math.nan, 100.0))

    def test_floored_benefit_is_twelve_months_of_the_positive_gap(self):
        self.assertEqual(rs.floored_annual_benefit(1000.0, 600.0), 4800.0)
        self.assertEqual(rs.floored_annual_benefit(500.0, 600.0), 0.0)
        # A unit that reports no or negative rent pays nothing.
        self.assertEqual(rs.floored_annual_benefit(500.0, -20.0), 6000.0)
        self.assertEqual(rs.floored_annual_benefit(500.0, 0.0), 6000.0)

    def test_weighted_mean(self):
        self.assertAlmostEqual(rs.weighted_mean([1.0, 3.0], [1.0, 3.0]), 2.5)
        self.assertAlmostEqual(rs.weighted_mean([2.0, 2.0, 2.0], [5.0, 0.1, 9.0]), 2.0)
        with self.assertRaises(ValueError):
            rs.weighted_mean([1.0], [1.0, 2.0])
        with self.assertRaises(ValueError):
            rs.weighted_mean([1.0, 2.0], [0.0, 0.0])
        with self.assertRaises(ValueError):
            rs.weighted_mean([], [])

    def test_summarize_recomputes_each_change_from_the_base(self):
        dollars = {name: 100.0 + 10 * i for i, name in enumerate(rs.VARIANTS)}
        dollars["base"] = 200.0
        rows = rs.summarize(dollars, {"predicted_median": 0.1})
        self.assertEqual(rows["base"]["percent_vs_base"], 0.0)
        for name, row in rows.items():
            self.assertAlmostEqual(row["percent_vs_base"], 100.0 * (dollars[name] / 200.0 - 1.0))
            self.assertEqual(row["description"], rs.VARIANTS[name])
        self.assertEqual(rows["predicted_median"]["share_with_zero_benefit"], 0.1)
        self.assertIsNone(rows["base"]["share_with_zero_benefit"])
        with self.assertRaises(ValueError):
            rs.summarize({"base": 1.0}, {})


class ReceiptTies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = json.loads(rs.RECEIPT.read_text())
        cls.replication = json.loads(rs.REPLICATION_RECEIPT.read_text())
        cls.recorded = cls.replication["imputation_diagnostics"]["rental_assistance"][str(rs.REFERENCE_YEAR)]
        cls.variants = cls.receipt["variants"]

    def test_receipt_comes_from_the_committed_script(self):
        self.assertEqual(self.receipt["generated_by"], "scripts/rent_sensitivity.py")
        self.assertEqual(self.receipt["script_sha256"], sha256(REPO / "scripts" / "rent_sensitivity.py"))

    def test_inputs_are_the_replication_receipts(self):
        self.assertEqual(self.receipt["calculator_commit"], RECEIPT_PINS[REPLICATION][1])
        self.assertEqual(self.receipt["replication_receipt"]["sha256"], RECEIPT_PINS[REPLICATION][0])
        expected_code = {
            name: digest
            for name, digest in self.replication["code_sha256"].items()
            if name.startswith("spm_calculator/")
        }
        self.assertEqual(self.receipt["code_sha256"], expected_code)
        self.assertIn("spm_calculator/ce_inkind.py", expected_code)
        for name, digest in self.receipt["ce_bundles"].items():
            self.assertEqual(digest, self.replication["ce_bundles"][name]["sha256"])
        self.assertEqual(set(self.receipt["ce_bundles"]), {"intrvw22.zip", "intrvw23.zip"})

    def test_base_reproduces_the_replication_receipt(self):
        self.assertTrue(
            math.isclose(
                self.variants["base"]["dollars_per_assisted_renter"],
                self.recorded["ce_mean_amount_per_participant"],
                rel_tol=rs.BASE_TOLERANCE,
            )
        )
        for field in ("renters", "assisted", "fit_rows"):
            self.assertEqual(self.receipt["sample"][field], self.recorded[field])
        self.assertTrue(math.isclose(self.receipt["fit"]["sigma"], self.recorded["sigma"], rel_tol=rs.BASE_TOLERANCE))

    def test_percent_changes_recompute_from_the_dollars(self):
        self.assertEqual(set(self.variants), set(rs.VARIANTS))
        base = self.variants["base"]["dollars_per_assisted_renter"]
        for name, row in self.variants.items():
            self.assertAlmostEqual(
                row["percent_vs_base"], 100.0 * (row["dollars_per_assisted_renter"] / base - 1.0), places=9
            )

    def test_predicted_market_rents_give_less_and_some_units_nothing(self):
        for name in rs.PREDICTED:
            self.assertLess(self.variants[name]["percent_vs_base"], 0)
            self.assertGreater(self.variants[name]["share_with_zero_benefit"], 0)
            self.assertLess(self.variants[name]["share_with_zero_benefit"], 1)
        for name in ("base", "next_interview_rent"):
            self.assertIsNone(self.variants[name]["share_with_zero_benefit"])

    def test_sample_counts_nest(self):
        sample = self.receipt["sample"]
        self.assertLessEqual(sample["part_period_assisted"], sample["part_period_renters"])
        self.assertLessEqual(sample["part_period_renters"], sample["renters_with_next_interview_rent"])
        self.assertLessEqual(sample["renters_with_next_interview_rent"], sample["renters"])
        self.assertLessEqual(sample["assisted"], sample["renters"])
        self.assertEqual(self.receipt["part_period_bounds"], list(rs.PART_PERIOD_BOUNDS))

    def test_assisted_renters_pay_less_than_the_fitted_median(self):
        fit = self.receipt["fit"]
        self.assertLess(fit["mean_rent_paid_assisted_monthly"], fit["mean_fitted_median_market_rent_assisted_monthly"])


if __name__ == "__main__":
    unittest.main()
