"""Mutation tests run the real guard in independent temporary Git clones."""

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROLLING_NAME = "rolling_forecast_2026_09_09.json"
DISCUSSION_HEADING = "# Discussion {#sec-discussion}\n"
ROLLING_CE_HEADING = "## Projecting expenditure records and rolling windows\n"
ROLLING_ACS_HEADING = "## Projecting local relative housing costs\n"

# Each case drifts one sealed rolling figure in its own subsection. The
# third element is the same figure restated correctly somewhere else in the
# paper, so a pin that searched the whole document would still pass.
ROLLING_PROSE_MUTATIONS = (
    (
        "applied compounded rate",
        (("real-growth rate is 0.914 percent", "real-growth rate is 0.924 percent"),),
        DISCUSSION_HEADING,
        "We report rates as compounded annual equivalents, $\\exp(r)-1$, not as "
        "the log rate $r$ that enters the multiplier. The applied annual "
        "real-growth rate is 0.914 percent, from an applied log rate of "
        "0.910 percent.",
        "rolling applied real-growth rate",
    ),
    (
        "applied log rate",
        ((" of 0.910\npercent", " of 0.911\npercent"),),
        ROLLING_ACS_HEADING,
        "The applied annual real-growth rate is 0.914 percent, from an applied "
        "log rate of 0.910 percent.",
        "rolling applied real-growth rate",
    ),
    (
        "dropped log-rate clause",
        ((", from an applied log rate of 0.910\npercent", ""),),
        DISCUSSION_HEADING,
        "The applied annual real-growth rate is 0.914 percent, from an applied "
        "log rate of 0.910 percent.",
        "rolling applied real-growth rate",
    ),
    (
        "dropped compounding convention",
        (("compounded annual equivalents", "annual equivalents"),),
        DISCUSSION_HEADING,
        "We report rates as compounded annual equivalents.",
        "rolling applied real-growth rate",
    ),
    (
        "swapped sensitivities",
        (
            ("0.817 percent", "PLACEHOLDER"),
            ("−0.135 percent", "0.817 percent"),
            ("PLACEHOLDER", "−0.135 percent"),
        ),
        DISCUSSION_HEADING,
        "Using ten annual blocks gives 0.817 percent; excluding the two blocks "
        "ending in 2021 and 2022 from the five-block fit leaves three blocks "
        "and gives −0.135 percent.",
        "rolling real-growth sensitivities",
    ),
    (
        "ten-block sensitivity count",
        (("Using ten annual", "Using nine annual"),),
        DISCUSSION_HEADING,
        "Using ten annual blocks gives 0.817 percent.",
        "rolling real-growth sensitivities",
    ),
    (
        "pandemic-excluded block count",
        (("leaves three\nblocks", "leaves four\nblocks"),),
        DISCUSSION_HEADING,
        "The five-block fit leaves three blocks and gives −0.135 percent.",
        "rolling real-growth sensitivities",
    ),
    (
        "excluded block years",
        (("in 2021 and 2022 from", "in 2020 and 2022 from"),),
        DISCUSSION_HEADING,
        "Excluding the two blocks ending in 2021 and 2022 from the five-block fit.",
        "rolling real-growth sensitivities",
    ),
    (
        "fitted block count",
        (("five nonoverlapping", "six nonoverlapping"),),
        DISCUSSION_HEADING,
        "We construct five nonoverlapping annual collection blocks ending in "
        "2021–2025.",
        "rolling fit uses 5 blocks",
    ),
    (
        "fitted block window",
        (("ending in 2021–2025", "ending in 2020–2025"),),
        DISCUSSION_HEADING,
        "We construct five nonoverlapping annual collection blocks ending in "
        "2021–2025.",
        "rolling fit uses 5 blocks",
    ),
    (
        "declared shrinkage",
        (("the 0.5\nshrinkage", "the 0.6\nshrinkage"),),
        DISCUSSION_HEADING,
        "The applied slope is half that estimate; the 0.5 shrinkage was "
        "declared in advance.",
        "rolling applied slope is the declared 0.5",
    ),
    (
        "swapped area menus",
        (
            ("342 published and seven modeled areas in\n2022", "PLACEHOLDER"),
            (
                "341 published and eight modeled areas from 2023",
                "342 published and seven modeled areas in\n2022",
            ),
            ("PLACEHOLDER", "341 published and eight modeled areas from 2023"),
        ),
        DISCUSSION_HEADING,
        "The menu contains 342 published and seven modeled areas in 2022, and "
        "341 published and eight modeled areas from 2023.",
        "rolling area menu prose",
    ),
    (
        "published area menu",
        (("342 published", "343 published"),),
        DISCUSSION_HEADING,
        "The menu contains 342 published and seven modeled areas in 2022.",
        "rolling area menu prose",
    ),
    (
        "modeled area menu",
        (("and seven modeled", "and eight modeled"),),
        ROLLING_CE_HEADING,
        "The menu contains 342 published and seven modeled areas in 2022, and "
        "341 published and eight modeled areas from 2023.",
        "rolling area menu prose",
    ),
    (
        "area menu year",
        (("modeled areas from 2023", "modeled areas from 2024"),),
        DISCUSSION_HEADING,
        "The menu holds 341 published and eight modeled areas from 2023.",
        "rolling area menu prose",
    ),
    (
        "validation area count",
        (("covers 341 areas", "covers 340 areas"),),
        DISCUSSION_HEADING,
        "The 2023-origin, 2024-target geographic comparison covers 341 areas "
        "with published anchors.",
        "rolling geographic validation covers 341",
    ),
    (
        "validation horizon",
        (("The 2023-origin, 2024-target", "The 2022-origin, 2024-target"),),
        DISCUSSION_HEADING,
        "The 2023-origin, 2024-target geographic comparison covers 341 areas.",
        "rolling geographic validation covers 341",
    ),
    (
        "stabilization year",
        (("occurs in 2029", "occurs in 2030"),),
        ROLLING_CE_HEADING,
        "The relative indices stabilize under this assumption. In this "
        "snapshot that occurs in 2029.",
        "relative rent indices first constant in 2029",
    ),
    (
        "thin-donor support count",
        (("31 areas carry thin-donor", "13 areas carry thin-donor"),),
        DISCUSSION_HEADING,
        "Support narrows: 31 areas carry thin-donor warnings in projected years.",
        "rolling thin-donor warnings cover 31",
    ),
)


def excluded_diagnostic(path):
    """Do not read or copy private worker diagnostics into test fixtures."""
    return str(path).endswith((".err", ".lane.log"))


class PaperGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="spm-paper-test-")
        self.repo = Path(self.temp.name) / "paper"
        subprocess.run(
            [
                "git",
                "clone",
                "--quiet",
                "--shared",
                "--no-checkout",
                str(REPO),
                str(self.repo),
            ],
            check=True,
            capture_output=True,
        )
        names = (
            subprocess.check_output(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                cwd=REPO,
            )
            .decode()
            .split("\0")
        )
        for name in names:
            if name and not excluded_diagnostic(name) and (REPO / name).is_file():
                destination = self.repo / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO / name, destination)
        self.install_article()

    def install_article(self):
        # The article owner integrates these two includes concurrently. Supply
        # only that declared integration in the private fixture; the actual
        # checkout still requires an independent check_paper.py run. Restoring
        # from the checkout also resets the fixture between mutation subtests.
        article = self.repo / "paper/index.qmd"
        prose = (REPO / "paper/index.qmd").read_text()
        for name in ("rolling_projection.md", "rolling_validation.md"):
            directive = "{{< include tables/" + name + " >}}"
            if directive not in prose:
                prose += "\n" + directive + "\n"
        article.write_text(prose)

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self):
        return {
            str(p.relative_to(self.repo)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.repo.rglob("*")
            if (
                not excluded_diagnostic(p)
                and ".git" not in p.relative_to(self.repo).parts
                and p.is_file()
            )
        }

    def run_guard(self):
        before = self.snapshot()
        result = subprocess.run(
            [sys.executable, "-B", "scripts/check_paper.py"],
            cwd=self.repo,
            capture_output=True,
            check=False,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(before, self.snapshot(), "Guard changed checkout bytes")
        return result

    def test_integrated_fixture_guard_leaves_sources_unchanged(self):
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_corrupt_evaluation_fails_before_generator_without_repair(self):
        (self.repo / "data/evaluation_2025.json").write_text("invalid committed JSON\n")
        (self.repo / "scripts/evaluate_nowcast_2025.py").write_text(
            "from pathlib import Path\nPath('GENERATOR_RAN').write_text('wrong')\n"
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generators were not run", result.stdout)
        self.assertFalse((self.repo / "GENERATOR_RAN").exists())

    def test_current_corruption_fails_before_generator_without_repair(self):
        (self.repo / "data/current/ce_replication_2019_2025.json").write_text(
            "invalid current JSON\n"
        )
        (self.repo / "scripts/build_current_tables.py").write_text(
            "from pathlib import Path\nPath('GENERATOR_RAN').write_text('wrong')\n"
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generators were not run", result.stdout)
        self.assertIn("current artifact hash mismatch", result.stdout)
        self.assertFalse((self.repo / "GENERATOR_RAN").exists())

    def test_current_internal_content_hash_is_checked_after_file_hash(self):
        release_path = self.repo / "data/current/spm-release.json"
        release = json.loads(release_path.read_text())
        release["years"]["2025"]["thresholds"]["renter"] += 1
        release_path.write_text(json.dumps(release))
        manifest = self.repo / "data/current/SHA256SUMS"
        lines = manifest.read_text().splitlines()
        lines = [
            (
                f"{hashlib.sha256(release_path.read_bytes()).hexdigest()}  data/current/spm-release.json"
                if line.endswith("data/current/spm-release.json")
                else line
            )
            for line in lines
        ]
        manifest.write_text("\n".join(lines) + "\n")
        # Bypass only the independent frozen-manifest byte pin in this private
        # fixture so this attack reaches the release's inner content seal.
        guard_path = self.repo / "scripts/check_paper.py"
        original_manifest_hash = hashlib.sha256(
            (REPO / "data/current/SHA256SUMS").read_bytes()
        ).hexdigest()
        guard_path.write_text(
            guard_path.read_text().replace(
                original_manifest_hash, hashlib.sha256(manifest.read_bytes()).hexdigest()
            )
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release canonical content hash", result.stdout)

    def test_retrospective_manifest_history_cannot_be_amended(self):
        manifest = self.repo / "data/current/SHA256SUMS"
        manifest.write_text(manifest.read_text() + "\n")
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("retrospective checksum manifest history changed", result.stdout)
        self.assertIn("generators were not run", result.stdout)

    def test_new_rolling_tables_must_both_be_included_in_article(self):
        path = self.repo / "paper/index.qmd"
        prose = path.read_text()
        for name in ("rolling_projection.md", "rolling_validation.md"):
            prose = prose.replace("{{< include tables/" + name + " >}}", "")
        path.write_text(prose)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("article tables never included", result.stdout)
        self.assertIn("rolling_projection.md", result.stdout)
        self.assertIn("rolling_validation.md", result.stdout)

    def refresh_rolling_manifest(self):
        manifest = self.repo / "data/current/ROLLING_SHA256SUMS"
        lines = []
        for line in manifest.read_text().splitlines():
            _, name = line.split()
            digest = hashlib.sha256((self.repo / name).read_bytes()).hexdigest()
            lines.append(f"{digest}  {name}")
        manifest.write_text("\n".join(lines) + "\n")

    def test_rolling_corruption_fails_before_generators_without_repair(self):
        (self.repo / "data/current" / ROLLING_NAME).write_text("invalid JSON\n")
        (self.repo / "scripts/build_current_tables.py").write_text(
            "from pathlib import Path\nPath('GENERATOR_RAN').write_text('wrong')\n"
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rolling artifact hash mismatch", result.stdout)
        self.assertIn("generators were not run", result.stdout)
        self.assertFalse((self.repo / "GENERATOR_RAN").exists())

    def test_rolling_provenance_mismatches_fail_after_manifest_refresh(self):
        path = self.repo / "data/current/rolling_provenance.json"
        original = json.loads(path.read_text())
        cases = (
            ("content_sha256", "rolling canonical content hash"),
            ("source_sha256", "rolling source fingerprints"),
            ("code_sha256", "rolling executed code fingerprints"),
            ("calculator_commit", "rolling calculator commit"),
        )
        for field, label in cases:
            with self.subTest(field=field):
                provenance = json.loads(json.dumps(original))
                if isinstance(provenance[field], dict):
                    provenance[field][next(iter(provenance[field]))] = "0" * 64
                else:
                    provenance[field] = "0" * len(provenance[field])
                path.write_text(json.dumps(provenance))
                self.refresh_rolling_manifest()
                result = self.run_guard()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(label, result.stdout)
                self.assertIn("generators were not run", result.stdout)
        path.write_text(json.dumps(original))
        self.refresh_rolling_manifest()

    def test_self_consistently_resealed_rolling_amount_cannot_replace_release(self):
        path = self.repo / "data/current" / ROLLING_NAME
        artifact = json.loads(path.read_text())
        artifact["scenarios"]["ce_trend"]["years"]["2026"]["thresholds"]["renter"] += 1
        artifact["content_sha256"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in artifact.items() if key != "content_sha256"},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        path.write_text(json.dumps(artifact))
        provenance_path = self.repo / "data/current/rolling_provenance.json"
        provenance = json.loads(provenance_path.read_text())
        provenance["content_sha256"] = artifact["content_sha256"]
        provenance["artifact_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        provenance_path.write_text(json.dumps(provenance))
        self.refresh_rolling_manifest()
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rolling artifact hash mismatch", result.stdout)
        self.assertIn("generators were not run", result.stdout)

    def test_rolling_manifest_must_cover_exact_additional_artifacts(self):
        (self.repo / "data/current/ROLLING_SHA256SUMS").write_text("")
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rolling", result.stdout)
        self.assertIn("generators were not run", result.stdout)

    def test_rolling_projection_drift_is_detected_without_repair(self):
        table = self.repo / "paper/tables/rolling_projection.md"
        table.write_text(table.read_text() + "unreviewed forecast row\n")
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generated output drifted: paper/tables/rolling_projection.md", result.stdout)

    def test_rolling_validation_missing_is_detected_without_repair(self):
        (self.repo / "paper/tables/rolling_validation.md").unlink()
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generated tables present == expected", result.stdout)
        self.assertIn("rolling_validation.md", result.stdout)

    def test_regenerated_evaluation_json_drift_is_detected(self):
        path = self.repo / "scripts/evaluate_nowcast_2025.py"
        path.write_text(
            path.read_text().replace(
                '(OUTPUT_DATA / "evaluation_2025.json").write_text',
                'summary["unreviewed_change"] = True\n(OUTPUT_DATA / "evaluation_2025.json").write_text',
            )
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "generated output drifted: data/evaluation_2025.json", result.stdout
        )

    def test_missing_and_extra_tables_fail_without_restoring_them(self):
        (self.repo / "paper/tables/evaluation.md").unlink()
        (self.repo / "paper/tables/extra.md").write_text("unexpected table\n")
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generated tables present == expected", result.stdout)

    def test_archived_table_still_checked_when_not_in_article(self):
        qmd = (self.repo / "paper/index.qmd").read_text()
        self.assertNotIn("include tables/package_errors.md", qmd)
        (self.repo / "paper/tables/package_errors.md").write_text("changed archive\n")
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "generated output drifted: paper/tables/package_errors.md", result.stdout
        )

    def test_current_projection_headline_drift_is_detected(self):
        path = self.repo / "paper/index.qmd"
        path.write_text(path.read_text().replace("0.51", "9.51"))
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("current projection prose replication_ratio", result.stdout)

    def test_evaluation_range_rounds_from_saved_errors(self):
        path = self.repo / "paper/index.qmd"
        path.write_text(path.read_text().replace("1.70 to 3.47", "1.70 to 3.48"))
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "CPI-U 2025 understated every tenure by 1.70 to 3.47 percent", result.stdout
        )

    def test_generator_failure_leaves_source_files_unchanged(self):
        (self.repo / "scripts/evaluate_nowcast_2025.py").write_text(
            "raise RuntimeError('fixture failure')\n"
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("evaluate_nowcast_2025.py failed", result.stdout)

    def test_moved_tag_is_rejected_in_independent_clone(self):
        subprocess.run(
            ["git", "update-ref", "refs/tags/v1.1-amended-nowcast", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tag identity mismatch", result.stdout)

    def test_old_timestamp_never_covers_an_amended_manifest(self):
        path = self.repo / "data/COMMITMENT-MANIFEST.txt"
        path.write_text(path.read_text().replace("85049a018", "19a1f44d1"))
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("preserved commitment/proof bytes changed", result.stdout)

    def edit_article(self, edits, host=None, decoy=None):
        """Apply exact single-occurrence prose edits, optionally restating the
        original figure under another heading."""
        path = self.repo / "paper/index.qmd"
        prose = path.read_text()
        for old, new in edits:
            self.assertEqual(prose.count(old), 1, f"ambiguous fixture edit: {old!r}")
            prose = prose.replace(old, new)
        if host is not None:
            self.assertEqual(prose.count(host), 1, f"ambiguous fixture host: {host!r}")
            prose = prose.replace(host, f"{host}\n{decoy}\n")
        path.write_text(prose)

    def assert_article_mutation_fails(self, label, edits, expected, host=None, decoy=None):
        self.install_article()
        self.edit_article(edits, host, decoy)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0, label)
        self.assertIn(expected, result.stdout)

    def test_rolling_prose_figures_drift_from_the_sealed_forecast(self):
        for label, edits, _, _, expected in ROLLING_PROSE_MUTATIONS:
            with self.subTest(figure=label):
                self.assert_article_mutation_fails(label, edits, expected)

    def test_rolling_pins_reject_a_figure_borrowed_from_another_section(self):
        """The same numeral stated correctly elsewhere must not rescue a
        drifted figure: 31 already appears in a tbl-colwidths attribute and
        seven in "seven target years", so an unscoped pin would pass."""
        for label, edits, host, decoy, expected in ROLLING_PROSE_MUTATIONS:
            with self.subTest(figure=label):
                self.assert_article_mutation_fails(label, edits, expected, host, decoy)

    def test_rolling_section_headings_must_be_present_and_unique(self):
        cases = (
            (
                "removed anchor",
                "# Conditional forecasts beyond available microdata {#sec-rolling}",
                "# Conditional forecasts beyond available microdata",
            ),
            (
                "duplicated subsection",
                "## Projecting local relative housing costs",
                "## Projecting local relative housing costs\n\n"
                "## Projecting local relative housing costs",
            ),
        )
        for label, old, new in cases:
            with self.subTest(heading=label):
                self.assert_article_mutation_fails(
                    label, [(old, new)], "paper section heading not unique"
                )

    def reseal_rolling_artifact(self, artifact):
        """Reseal a mutated forecast end to end — content digest, assumption
        digest, provenance, manifest and the calculator byte pins — so the pin
        under test is the only thing left that can fail."""

        def canonical(value):
            return hashlib.sha256(
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode()
            ).hexdigest()

        path = self.repo / "data/current" / ROLLING_NAME
        inputs = self.repo / "scripts/rolling_inputs.py"
        source = inputs.read_text()
        for old in (
            json.loads(path.read_text())["content_sha256"],
            hashlib.sha256(path.read_bytes()).hexdigest(),
        ):
            self.assertIn(old, source)
        artifact["assumption_sha256"] = canonical(artifact["assumptions"])
        artifact["content_sha256"] = canonical(
            {k: v for k, v in artifact.items() if k != "content_sha256"}
        )
        path.write_text(json.dumps(artifact))
        provenance_path = self.repo / "data/current/rolling_provenance.json"
        provenance = json.loads(provenance_path.read_text())
        source = source.replace(provenance["content_sha256"], artifact["content_sha256"])
        source = source.replace(
            provenance["artifact_sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
        )
        provenance["content_sha256"] = artifact["content_sha256"]
        provenance["assumption_sha256"] = artifact["assumption_sha256"]
        provenance["artifact_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        provenance_path.write_text(json.dumps(provenance))
        inputs.write_text(source)
        self.refresh_rolling_manifest()

    def test_rolling_rate_pins_follow_the_artifact_not_a_fixed_literal(self):
        """Reseal the forecast at a different real-growth rate and leave the
        prose untouched: a hardcoded 0.914 would still pass."""
        path = self.repo / "data/current" / ROLLING_NAME
        artifact = json.loads(path.read_text())
        applied_log_rate = math.log(1.00924)
        fit = artifact["assumptions"]["real_growth_fit"]
        fit["applied_log_rate"] = applied_log_rate
        fit["log_slope"] = fit["annual_log_slope"] = applied_log_rate * 2
        fit["shrunk_annual_rate"] = fit["annual_rate"] = math.exp(applied_log_rate) - 1
        fit["unshrunk_annual_rate"] = math.exp(applied_log_rate * 2) - 1
        artifact["scenarios"]["ce_trend"]["real_growth_rate"] = fit["shrunk_annual_rate"]
        self.reseal_rolling_artifact(artifact)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rolling applied real-growth rate 0.924", result.stdout)

    def test_rolling_geography_pins_follow_the_artifact_not_a_fixed_literal(self):
        """Reseal one area out of the published menu: the menu, validation and
        thin-support pins must all move with the forecast, not with the prose."""
        path = self.repo / "data/current" / ROLLING_NAME
        artifact = json.loads(path.read_text())
        for scenario in artifact["scenarios"].values():
            for record in scenario["years"].values():
                anchored = next(
                    key
                    for key, area in record["geography_by_area"].items()
                    if area["anchor_status"] == "published_anchor"
                )
                record["geography_by_area"][anchored]["anchor_status"] = (
                    "modeled_unanchored"
                )
                for diagnostic in record["median_diagnostics"].values():
                    diagnostic["thin_support"] = False
        artifact["validation"]["acs"]["area_count"] -= 1
        self.reseal_rolling_artifact(artifact)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        for expected in (
            "rolling area menu prose",
            "rolling geographic validation covers 340",
            "rolling thin-donor warnings cover 0",
        ):
            self.assertIn(expected, result.stdout)


if __name__ == "__main__":
    unittest.main()
