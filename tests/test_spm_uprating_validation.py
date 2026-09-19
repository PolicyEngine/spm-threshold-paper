"""Light guards for the diagnostic runner; no country model or population runs."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

RUNNER = (
    Path(__file__).resolve().parents[1]
    / "analysis/spm-uprating-validation-20260919/run_cell.py"
)
spec = importlib.util.spec_from_file_location("spm_uprating_cell", RUNNER)
cell = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cell)

try:
    from microdf import MicroSeries
except ImportError:
    MicroSeries = None


class InputIntegrityTest(unittest.TestCase):
    def test_wrong_dataset_fails_before_loading_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.h5"
            path.write_bytes(b"not the frozen population")
            with self.assertRaisesRegex(ValueError, "Dataset hash mismatch"):
                cell.verified_dataset(path, cell.DATASET_SHA256)

    def test_existing_output_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frozen.json"
            path.write_text("frozen forecast")
            with self.assertRaises(FileExistsError):
                cell.main(
                    [
                        "--year",
                        "2025",
                        "--dataset",
                        str(Path(tmp) / "missing.h5"),
                        "--runtime-label",
                        "test",
                        "--country-source-sha",
                        "a" * 40,
                        "--output",
                        str(path),
                    ]
                )
            self.assertEqual(path.read_text(), "frozen forecast")

    def test_anchor_not_applied_to_base_year(self):
        with self.assertRaisesRegex(ValueError, "only for 2025"):
            cell.main(
                [
                    "--year",
                    "2024",
                    "--variant",
                    "anchored_2024_cpi",
                    "--dataset",
                    "missing.h5",
                    "--runtime-label",
                    "test",
                    "--country-source-sha",
                    "a" * 40,
                    "--output",
                    "unused.json",
                ]
            )


@unittest.skipIf(
    MicroSeries is None,
    "Install the runtime's microdf-python to exercise weighted diagnostics",
)
class WeightedDiagnosticTest(unittest.TestCase):
    def test_age_rates_counts_and_band_boundaries_preserve_weights(self):
        # Unequal weights make accidental unweighted aggregation fail loudly.
        weights = [1, 9, 2, 8]
        age = MicroSeries([3, 17, 64, 75], weights=weights)
        resources = MicroSeries([50, 100, 125, 200], weights=weights)
        threshold = MicroSeries([100, 100, 100, 100], weights=weights)
        poor = resources < threshold
        groups = cell.summarize(age, poor, resources, threshold)
        self.assertAlmostEqual(groups["all"]["spm_pct"], 5)
        self.assertAlmostEqual(groups["all"]["people"], 20)
        self.assertAlmostEqual(groups["all"]["poor_people"], 1)
        self.assertAlmostEqual(groups["under_18"]["spm_pct"], 10)
        self.assertAlmostEqual(groups["under_18"]["spm_unit_resources_usd"]["mean"], 95)
        self.assertAlmostEqual(groups["age_18_64"]["people"], 2)
        self.assertAlmostEqual(groups["age_65_plus"]["people"], 8)
        bands = groups["all"]["resource_ratio_band_pct"]
        self.assertAlmostEqual(sum(bands.values()), 100)
        self.assertAlmostEqual(bands["1_to_below_1_25"], 45)
        self.assertAlmostEqual(bands["1_25_to_below_1_5"], 10)
        self.assertAlmostEqual(groups["age_6_17"]["spm_pct"], 0)

    def test_empty_groups_are_explicit(self):
        age = MicroSeries([40], weights=[2])
        resources = MicroSeries([90], weights=[2])
        threshold = MicroSeries([100], weights=[2])
        groups = cell.summarize(age, resources < threshold, resources, threshold)
        self.assertEqual(
            groups["under_18"], {"people": 0.0, "spm_pct": None, "poor_people": 0.0}
        )

    def test_inconsistent_poverty_indicator_is_rejected(self):
        age = MicroSeries([40], weights=[2])
        resources = MicroSeries([90], weights=[2])
        threshold = MicroSeries([100], weights=[2])
        with self.assertRaisesRegex(ValueError, "Canonical poverty indicator"):
            cell.summarize(age, resources >= threshold, resources, threshold)

    def test_misaligned_people_are_rejected(self):
        age = MicroSeries([40], weights=[2], index=[0])
        resources = MicroSeries([90], weights=[2], index=[1])
        threshold = MicroSeries([100], weights=[2], index=[1])
        with self.assertRaisesRegex(ValueError, "not aligned"):
            cell.summarize(age, resources < threshold, resources, threshold)


if __name__ == "__main__":
    unittest.main()
