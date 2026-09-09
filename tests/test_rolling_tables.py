"""The current tables report the sealed rolling artifact and retained CE experiment."""

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TENURES = ("owner_with_mortgage", "owner_without_mortgage", "renter")
TENURE_LABELS = ("Owner with mortgage", "Owner without mortgage", "Renter")
ROLLING_NAME = "rolling_forecast_2026_09_09.json"


def table_rows(path):
    """Read data cells without depending on Markdown column widths."""
    return [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in path.read_text().splitlines()[2:]
        if line.startswith("|")
    ]


class RollingTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "paper_current_tables", REPO / "scripts/build_current_tables.py"
        )
        cls.generator = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(REPO / "scripts"))
        try:
            spec.loader.exec_module(cls.generator)
        finally:
            sys.path.pop(0)
        cls.forecast = json.loads((REPO / "data/current" / ROLLING_NAME).read_text())
        cls.temp = tempfile.TemporaryDirectory(prefix="spm-rolling-tables-")
        cls.output = Path(cls.temp.name)
        result = subprocess.run(
            [sys.executable, "-B", "scripts/build_current_tables.py", "--output-root", str(cls.output)],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode:
            cls.temp.cleanup()
            raise AssertionError(result.stdout + result.stderr)
        cls.tables = cls.output / "paper/tables"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_current_release_uses_published_2025_shares_and_precision(self):
        current = self.forecast["scenarios"][self.forecast["default_scenario"]]["years"]["2025"]
        self.assertEqual(current["national_status"], "published")
        self.assertEqual(current["housing_share_status"], "published_anchor")
        table = self.tables / "current_release.md"
        self.assertIn("Published 2025 housing share", table.read_text().splitlines()[0])
        self.assertEqual(
            table_rows(table),
            [
                [label, f"${current['thresholds'][tenure]:,.2f}", f"{current['housing_shares'][tenure]:.6f}"]
                for tenure, label in zip(TENURES, TENURE_LABELS)
            ],
        )
        old = json.loads((REPO / "data/current/spm-release.json").read_text())
        self.assertNotEqual(current["housing_shares"], old["years"]["2025"]["housing_shares"])

    def test_projection_has_all_selected_year_scenario_tenure_values(self):
        expected = []
        for year in (2025, 2026, 2030, 2035):
            for scenario_name in ("ce_trend", "zero_real"):
                scenario = self.forecast["scenarios"][scenario_name]
                record = scenario["years"][str(year)]
                expected.append(
                    [str(year), {"ce_trend": "CE trend", "zero_real": "Zero real"}[scenario_name],
                     record["national_status"].title(),
                     *(f"${record['thresholds'][tenure]:,.2f}" for tenure in TENURES)]
                )
        self.assertEqual(table_rows(self.tables / "rolling_projection.md"), expected)
        self.assertTrue(all(row[2] == "Published" for row in expected if row[0] == "2025"))
        self.assertTrue(all(row[2] == "Forecast" for row in expected if row[0] != "2025"))

    def validation_rows(self):
        return {row[0]: row[1] for row in table_rows(self.tables / "rolling_validation.md")}

    def validation_note(self):
        return " ".join(
            line.strip() for line in (self.tables / "rolling_validation.md").read_text().splitlines()
            if line.strip() and not line.startswith("|")
        )

    def test_validation_fits_compact_table_with_one_short_note(self):
        path = self.tables / "rolling_validation.md"
        rows = table_rows(path)
        self.assertGreaterEqual(len(rows), 9)
        self.assertLessEqual(len(rows), 11)
        self.assertTrue(all(len(row) == 2 for row in rows))
        self.assertEqual(len({row[0] for row in rows}), len(rows))
        self.assertEqual(
            [cell.strip() for cell in path.read_text().splitlines()[0].strip("|").split("|")],
            ["Diagnostic", "Value"],
        )
        note = self.validation_note()
        self.assertTrue(note)
        self.assertLessEqual(len(note.split()), 115)

    def test_validation_reports_actual_acs_comparison_and_scoped_caveat(self):
        acs = self.forecast["validation"]["acs"]
        rows = self.validation_rows()
        self.assertEqual(
            rows["ACS retrospective comparison"],
            f"{acs['origin_spm_year']}→{acs['target_spm_year']}; {acs['area_count']} areas",
        )
        self.assertEqual(
            rows["MAPE (model / carry-forward)"],
            f"{acs['mean_absolute_percentage_error']:.4f}% / "
            f"{acs['baseline_mean_absolute_percentage_error']:.4f}%",
        )
        note = self.validation_note().lower()
        self.assertIn("equal-area", note)
        self.assertRegex(note, r"current (?:source )?vintages")
        self.assertRegex(note, r"(?:no|not|unvalidated)[^.]*later[^.]*bridge|later[^.]*bridge[^.]*not validated")

    def test_validation_distinguishes_stabilized_indices_from_geographic_factors(self):
        years = self.forecast["scenarios"][self.forecast["default_scenario"]]["years"]
        ordered = sorted(map(int, years))
        constant_years = [
            year for year in ordered[:-1]
            if all(years[str(year)]["rent_indices"] == years[str(later)]["rent_indices"]
                   for later in ordered if later > year)
        ]
        first, last = constant_years[0], ordered[-1]
        rows = self.validation_rows()
        self.assertEqual(rows["Constant relative indices"], f"{first}–{last}")
        self.assertNotEqual(years[str(first - 1)]["rent_indices"], years[str(first)]["rent_indices"])
        self.assertGreater(
            max(
                abs(
                    (years[str(last)]["housing_shares"][tenure]
                     - years[str(first)]["housing_shares"][tenure]) * (index - 1)
                )
                for tenure in TENURES
                for index in years[str(first)]["rent_indices"].values()
            ),
            1e-12,
        )
        all_projected = min(
            year for year in ordered if years[str(year)]["acs_window"]["observed_years"] == 0
        )
        self.assertEqual(rows["First all-projected window"], str(all_projected))
        self.assertLess(first, all_projected)
        window = years[str(last)]["acs_window"]
        self.assertEqual(
            rows[f"ACS window ({last})"],
            f"{window['start']}–{window['end']} ({window['projected_years']} projected)",
        )
        self.assertEqual(window["observed_years"], 0)
        note = self.validation_note().lower()
        self.assertRegex(note, r"uniform[^.]*growth[^.]*deflation")
        self.assertRegex(note, r"(?:constant|stabili[sz]ed)[^.]*indices")
        self.assertRegex(note, r"changing housing shares[^.]*geographic factors|housing shares[^.]*change[^.]*geographic factors")
        self.assertRegex(note, r"floating-point noise[^.]*not[^.]*substantive")

    def test_validation_counts_original_donors_and_warning_flags(self):
        years = self.forecast["scenarios"][self.forecast["default_scenario"]]["years"]
        last = max(map(int, years))
        diagnostics = years[str(last)]["median_diagnostics"]
        rows = self.validation_rows()
        for label, field, digits in (
            ("Unique original donors", "unique_original_donor_count", 0),
            ("Allocation-expected donors", "expected_whole_record_count", 2),
            ("Donor-collapsed Kish", "kish_effective_count", 2),
        ):
            values = sorted(row[field] for row in diagnostics.values())
            self.assertEqual(
                rows[f"{label} ({last})"],
                f"{values[0]:,.{digits}f}–{values[-1]:,.{digits}f}",
            )
        self.assertEqual(
            rows[f"Thin-support areas ({last})"],
            f"{sum(row['thin_support'] for row in diagnostics.values())} / {len(diagnostics)}",
        )
        self.assertEqual(
            rows[f"Topcoding warnings ({last})"],
            f"{sum(row['median_topcode_warning'] for row in diagnostics.values())} local / "
            f"{sum(row['rent_index_topcode_warning'] for row in diagnostics.values())} index",
        )
        assumptions = self.forecast["assumptions"]["acs"]
        self.assertEqual(rows["Future donor cohort"], str(assumptions["donor_year"]))
        note = self.validation_note().lower()
        self.assertIn(f"{len(diagnostics)} modeled areas", note)
        self.assertRegex(note, r"(?:copies|donors)[^.]*not[^.]*independent")
        self.assertRegex(note, r"kish[^.]*not[^.]*survey-design")
        self.assertRegex(note, r"diagnostics[^.]*not[^.]*confidence intervals")
        self.assertRegex(note, r"local[^.]*target median")
        self.assertRegex(note, r"index[^.]*local or national[^.]*target[^.]*anchor[^.]*overlap")
        self.assertRegex(note, r"(?:flags|warnings)[^.]*not[^.]*known bias|not[^.]*known bias")

    def test_generator_rejects_nonpublished_or_disagreeing_anchor(self):
        for field in ("national_status", "housing_share_status"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.forecast)
                current = changed["scenarios"][changed["default_scenario"]]["years"]["2025"]
                current[field] = "forecast"
                with self.assertRaisesRegex(ValueError, "must be published"):
                    self.generator.rolling_tables(changed)
        changed = copy.deepcopy(self.forecast)
        changed["scenarios"]["zero_real"]["years"]["2025"]["housing_shares"]["renter"] += 0.01
        with self.assertRaisesRegex(ValueError, "share the published national anchor"):
            self.generator.rolling_tables(changed)

    def test_generator_rejects_unsupported_validation_and_inflated_donors(self):
        changed = copy.deepcopy(self.forecast)
        changed["validation"]["acs"]["unvalidated"] = True
        with self.assertRaisesRegex(ValueError, "validation must be complete"):
            self.generator.rolling_tables(changed)
        changed = copy.deepcopy(self.forecast)
        changed["assumptions"]["acs"]["relative_index_stabilization"]["first_constant_index_year"] += 1
        with self.assertRaisesRegex(ValueError, "stabilization metadata"):
            self.generator.rolling_tables(changed)
        changed = copy.deepcopy(self.forecast)
        diagnostics = changed["scenarios"][changed["default_scenario"]]["years"]["2035"]["median_diagnostics"]
        diagnostics[next(iter(diagnostics))]["unique_records"] *= 5
        with self.assertRaisesRegex(ValueError, "copies must not inflate support counts"):
            self.generator.rolling_tables(changed)

    def test_retrospective_ce_input_and_provenance_remain_exact(self):
        ce_bytes = (REPO / "data/current/ce_replication_2019_2025.json").read_bytes()
        self.assertEqual(
            hashlib.sha256(ce_bytes).hexdigest(),
            "d04e2a61552795f9d90e282045610774a4ff68f67b97067677358741f58a289c",
        )
        ce = json.loads(ce_bytes)
        provenance = json.loads((REPO / "data/current/provenance.json").read_text())
        self.assertEqual(provenance["ce_code_sha256"], ce["code_sha256"])
        self.assertEqual(ce["classification"], "current_retrospective_research")
        self.assertEqual(set(ce["results"]), {str(year) for year in range(2019, 2026)})
        for name in ("current_replication.md", "current_sensitivity.md", "current_projection.md"):
            with self.subTest(table=name):
                archived = subprocess.check_output(["git", "show", f"HEAD:paper/tables/{name}"], cwd=REPO)
                self.assertEqual((self.tables / name).read_bytes(), archived)


if __name__ == "__main__":
    unittest.main()
