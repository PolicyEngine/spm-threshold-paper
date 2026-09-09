"""Mutation tests run the real guard in independent temporary Git clones."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROLLING_NAME = "rolling_forecast_2026_09_09.json"


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
        # The article owner integrates these two includes concurrently. Supply
        # only that declared integration in the private fixture; the actual
        # checkout still requires an independent check_paper.py run.
        article = self.repo / "paper/index.qmd"
        prose = article.read_text()
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


if __name__ == "__main__":
    unittest.main()
