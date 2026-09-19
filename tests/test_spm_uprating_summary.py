"""Pure JSON-fixture tests; no country packages or population data required."""

import importlib.util
import unittest
from copy import deepcopy
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "analysis/spm-uprating-validation-20260919/summarize_results.py"
)
spec = importlib.util.spec_from_file_location("spm_uprating_summary", SCRIPT)
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)


def fixture_cells():
    cells = []
    for arm, (sha, version) in summary.SOURCES.items():
        for year, variant in summary.SPECS:
            rate = {
                ("before", 2024, "baseline"): 10,
                ("before", 2025, "baseline"): 12,
                ("before", 2025, "anchored_2024_cpi"): 11,
                ("after", 2024, "baseline"): 10,
                ("after", 2025, "baseline"): 13,
                ("after", 2025, "anchored_2024_cpi"): 11.5,
            }[(arm, year, variant)]
            distribution = {"mean": 100, "p25": 80, "median": 95, "p75": 120}
            group = {
                "people": 1000,
                "poor_people": rate * 10,
                "spm_pct": rate,
                "spm_unit_resources_usd": distribution.copy(),
                "spm_unit_threshold_usd": distribution.copy(),
                "resource_threshold_ratio": distribution.copy(),
                "resource_ratio_band_pct": {
                    "below_0_75": rate,
                    "0_75_to_below_1": 0,
                    "1_to_below_1_25": 100 - rate,
                    "1_25_to_below_1_5": 0,
                    "1_5_or_more": 0,
                },
                "component_person_mapped_mean_usd": {},
            }
            if variant == "anchored_2024_cpi":
                group["spm_unit_threshold_usd"] = {
                    key: value * 0.97 for key, value in distribution.items()
                }
            provenance = {
                "country_source_sha_declared": sha,
                "expected_model_version": version,
                "package_versions": {
                    name: version if name == "policyengine-us" else "1.0"
                    for name in summary.PACKAGES
                },
                "dataset_sha256": summary.DATASET_SHA256,
                "expected_dataset_sha256": summary.DATASET_SHA256,
                "runner_sha256": "a" * 64,
                "country_init_sha256": "b" * 64,
                "development_country_model": True,
                "bundle_certified": False,
                "caller_seed": 0,
                "pythonhashseed": "0",
                "country_import_path": "/fixture/country.py",
                "python": "3.13.9",
                "platform": "test",
                "interface": "development",
                "seed_note": "core seeds",
                "spm_config": {
                    "forecast_content_sha256": summary.FORECAST_SHA256,
                    "scenario": "ce_trend",
                },
                "spm_provenance": {"fixture": True},
            }
            cells.append(
                {
                    "format": "spm/uprating-validation-cell/v1",
                    "year": year,
                    "variant": variant,
                    "anchor_factors": summary.ANCHOR_FACTORS.copy()
                    if variant == "anchored_2024_cpi"
                    else None,
                    "provenance": provenance,
                    "groups": {name: deepcopy(group) for name in summary.GROUPS},
                    "spm_pct": {name: rate for name in summary.GROUPS},
                }
            )
    return cells


class ControlledSummaryTest(unittest.TestCase):
    def test_correct_decomposition_and_controlled_difference(self):
        result = summary.summarize(fixture_cells())
        row = result["groups"]["all"]
        self.assertEqual(row["before"]["change_pp"], 2)
        self.assertEqual(row["after"]["threshold_contribution_pp"], 1.5)
        self.assertEqual(row["after"]["constant_real_national_base_change_pp"], 1.5)
        self.assertEqual(row["after_minus_before"]["change_pp"], 1)
        self.assertEqual(row["after_minus_before"]["threshold_contribution_pp"], 0.5)
        self.assertEqual(
            row["after_minus_before"]["constant_real_national_base_change_pp"], 0.5
        )
        self.assertIn(summary.RESIDUAL_LABEL, summary.markdown(result))

    def test_missing_and_duplicate_cells_fail(self):
        cells = fixture_cells()
        with self.assertRaisesRegex(ValueError, "Missing cells"):
            summary.summarize(cells[:-1])
        with self.assertRaisesRegex(ValueError, "Duplicate cell"):
            summary.summarize(cells + [deepcopy(cells[0])])

    def test_each_shared_provenance_mismatch_fails(self):
        for key, value in (
            ("runner_sha256", "c" * 64),
            ("caller_seed", 42),
            ("pythonhashseed", "42"),
        ):
            with self.subTest(field=key):
                cells = fixture_cells()
                cells[-1]["provenance"][key] = value
                with self.assertRaisesRegex(ValueError, "Inconsistent provenance"):
                    summary.summarize(cells)
        cells = fixture_cells()
        cells[-1]["provenance"]["package_versions"]["numpy"] = "999"
        with self.assertRaisesRegex(ValueError, "non_country_package_versions"):
            summary.summarize(cells)

    def test_wrong_dataset_source_version_forecast_rejected(self):
        for key, value in (
            ("dataset_sha256", "c" * 64),
            ("country_source_sha_declared", "c" * 40),
            ("expected_model_version", "2.2.1"),
        ):
            with self.subTest(field=key):
                cells = fixture_cells()
                cells[0]["provenance"][key] = value
                with self.assertRaises(ValueError):
                    summary.summarize(cells)
        cells = fixture_cells()
        cells[0]["provenance"]["spm_config"]["forecast_content_sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "SPM forecast"):
            summary.summarize(cells)

    def test_mismatched_population_fails_even_with_consistent_rate(self):
        cells = fixture_cells()
        group = cells[-1]["groups"]["all"]
        group["people"] *= 2
        group["poor_people"] *= 2
        with self.assertRaisesRegex(ValueError, "populations differ"):
            summary.summarize(cells)

    def test_nonfinite_missing_and_inconsistent_rates_fail(self):
        cells = fixture_cells()
        cells[0]["groups"]["all"]["spm_unit_resources_usd"]["mean"] = float("nan")
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            summary.summarize(cells)
        cells = fixture_cells()
        del cells[0]["provenance"]["runner_sha256"]
        with self.assertRaisesRegex(ValueError, "Missing or malformed"):
            summary.summarize(cells)
        cells = fixture_cells()
        cells[0]["groups"]["all"]["poor_people"] += 100
        with self.assertRaisesRegex(ValueError, "Rate/count mismatch"):
            summary.summarize(cells)

    def test_base_year_and_anchor_resource_differences_are_reported(self):
        cells = fixture_cells()
        cells[3]["groups"]["all"]["spm_unit_resources_usd"]["mean"] += 5
        cells[5]["groups"]["all"]["spm_unit_resources_usd"]["median"] += 2
        result = summary.summarize(cells)
        check = result["checks"]["base_year_2024"]["all"]
        self.assertTrue(check["rates_match"])
        self.assertFalse(check["resources"]["match"])
        self.assertEqual(check["resources"]["after_minus_before"]["mean"], 5)
        self.assertFalse(
            result["checks"]["baseline_to_anchored_2025_resource_summaries"]["after"][
                "all"
            ]["match"]
        )

    def test_unscaled_anchor_threshold_is_rejected(self):
        cells = fixture_cells()
        cells[2]["groups"]["all"]["spm_unit_threshold_usd"] = deepcopy(
            cells[1]["groups"]["all"]["spm_unit_threshold_usd"]
        )
        with self.assertRaisesRegex(ValueError, "Anchored threshold outside"):
            summary.summarize(cells)


if __name__ == "__main__":
    unittest.main()
