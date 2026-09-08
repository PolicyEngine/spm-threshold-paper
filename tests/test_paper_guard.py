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
            if name and (REPO / name).is_file():
                destination = self.repo / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO / name, destination)

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self):
        return {
            str(p.relative_to(self.repo)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.repo.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(self.repo).parts
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

    def test_clean_guard_leaves_sources_unchanged(self):
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
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release canonical content hash", result.stdout)

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
