"""Import the exact committed calculator forecast without changing frozen inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from rolling_inputs import (
    ARTIFACT_SHA256,
    CALCULATOR_ARTIFACT_PATH,
    CALCULATOR_COMMIT,
    CONTENT_SHA256,
    ROLLING_ARTIFACT,
    ROLLING_FILES,
    canonical_sha256,
    load_rolling_forecast,
    source_fingerprints,
)

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calculator-repo", required=True, type=Path)
    parser.add_argument("--output-root", default=REPO, type=Path)
    args = parser.parse_args()
    raw = subprocess.check_output(
        ["git", "show", f"{CALCULATOR_COMMIT}:{CALCULATOR_ARTIFACT_PATH}"],
        cwd=args.calculator_repo,
    )
    if hashlib.sha256(raw).hexdigest() != ARTIFACT_SHA256:
        raise ValueError(
            "Committed calculator artifact bytes differ from the source pin"
        )
    document = json.loads(raw)
    content = {key: value for key, value in document.items() if key != "content_sha256"}
    if not document["content_sha256"] == canonical_sha256(content) == CONTENT_SHA256:
        raise ValueError(
            "Committed calculator content seal differs from the source pin"
        )
    provenance = {
        "classification": "current_rolling_ce_acs_forecast",
        "calculator_repository": "https://github.com/PolicyEngine/spm-calculator",
        "calculator_commit": CALCULATOR_COMMIT,
        "calculator_artifact_path": CALCULATOR_ARTIFACT_PATH,
        "artifact_sha256": ARTIFACT_SHA256,
        "content_sha256": CONTENT_SHA256,
        "information_date": document["information_date"],
        "code_sha256": document["code_sha256"],
        "component_sha256": document["component_sha256"],
        "source_sha256": source_fingerprints(document),
        "assumption_sha256": document["assumption_sha256"],
        "covered_by_original_timestamp": False,
        "frozen_commitments_modified": False,
        "retrospective_experiment": "The separate 2019-2025 CE receipt, spm-release.json and provenance.json retain their original bytes and identities.",
        "reproduction": "Offline git show of the pinned calculator commit; exact JSON bytes are copied without reserialization.",
    }
    output = args.output_root / "data" / "current"
    output.mkdir(parents=True, exist_ok=True)
    (output / ROLLING_ARTIFACT).write_bytes(raw)
    (output / "rolling_provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    (output / "ROLLING_SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256((output / name).read_bytes()).hexdigest()}  data/current/{name}\n"
            for name in sorted(ROLLING_FILES)
        )
    )
    load_rolling_forecast(output)
    print(f"Imported {len(raw):,} exact bytes; content SHA256 {CONTENT_SHA256}")


if __name__ == "__main__":
    main()
