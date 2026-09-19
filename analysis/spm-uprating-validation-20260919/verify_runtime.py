"""Bind an installed country package to a Git tree without importing the model."""

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
from importlib import metadata
from pathlib import Path


def verify(repository, revision):
    resolved = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", revision], text=True
    ).strip()
    if resolved != revision:
        raise ValueError("Provide the full source commit SHA")
    archive = subprocess.check_output(
        ["git", "-C", str(repository), "archive", revision, "policyengine_us"]
    )
    distribution = metadata.distribution("policyengine-us")
    package_root = Path(distribution.locate_file("policyengine_us")).resolve()
    files = []
    with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
        for member in tree.getmembers():
            if not member.isfile():
                continue
            relative = Path(member.name).relative_to("policyengine_us")
            source_hash = hashlib.sha256(tree.extractfile(member).read()).hexdigest()
            installed = package_root / relative
            if not installed.is_file():
                raise ValueError(f"Missing installed source file: {relative}")
            installed_hash = hashlib.sha256(installed.read_bytes()).hexdigest()
            if installed_hash != source_hash:
                raise ValueError(
                    f"Installed source differs from {revision}: {relative}"
                )
            files.append([str(relative), source_hash])
    files.sort()
    return {
        "country_source_sha": revision,
        "installed_model_version": distribution.version,
        "files_checked": len(files),
        "all_tracked_package_files_equal": True,
        "file_manifest_sha256": hashlib.sha256(
            json.dumps(files, separators=(",", ":")).encode()
        ).hexdigest(),
        "git_archive_sha256": hashlib.sha256(archive).hexdigest(),
        "installed_package_path": str(package_root),
        "method": "Compare every regular file under policyengine_us in git archive with the installed distribution; reject any missing or unequal file.",
        "package_versions": {
            name: metadata.version(name)
            for name in (
                "policyengine",
                "policyengine-us",
                "policyengine-core",
                "spm-calculator",
                "microdf-python",
                "numpy",
                "pandas",
            )
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--expected-runner-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runner_hash = hashlib.sha256(args.runner.read_bytes()).hexdigest()
    if runner_hash != args.expected_runner_sha256:
        raise ValueError("Runner changed")
    receipt = verify(args.repository, args.revision)
    receipt["runner_sha256"] = runner_hash
    receipt["verification_script_sha256"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(receipt, handle, indent=2)
        handle.write("\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
