"""Verify the additional current forecast independently of frozen experiments."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

CALCULATOR_COMMIT = "78bae15f76152c6076dd909a09f6b63dc2ec8c34"
ROLLING_ARTIFACT = "rolling_forecast_2026_09_09.json"
CALCULATOR_ARTIFACT_PATH = f"spm_calculator/data/current/{ROLLING_ARTIFACT}"
ARTIFACT_SHA256 = "cc06784feb81f8c7935d4494cea0a9821a79af868ac50383da8be37c6dc14b99"
CONTENT_SHA256 = "3d86d5c4c0423480e6b69b75d222ffa4a7a2639e4094df5ba2504af01be17173"
ROLLING_FILES = {ROLLING_ARTIFACT, "rolling_provenance.json"}


def canonical_sha256(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def source_fingerprints(document: dict) -> dict[str, str]:
    sources = {source["id"]: source["sha256"] for source in document["sources"]}
    if len(sources) != len(document["sources"]):
        raise ValueError("rolling source fingerprints: duplicate source identity")
    return sources


def load_rolling_forecast(data_dir: Path) -> dict:
    """Check bytes before JSON parsing; never rewrite an input or acquire data."""
    expected_names = {f"data/current/{name}" for name in ROLLING_FILES}
    listed = {}
    for line in (data_dir / "ROLLING_SHA256SUMS").read_text().splitlines():
        fields = line.split()
        if len(fields) != 2:
            raise ValueError("rolling checksum manifest: malformed line")
        digest, name = fields
        if (
            name not in expected_names
            or name in listed
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("rolling checksum manifest: invalid entry")
        listed[name] = digest
    if set(listed) != expected_names:
        raise ValueError("rolling checksum coverage")
    for name, expected in listed.items():
        path = data_dir / Path(name).name
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError(f"rolling artifact hash mismatch: {name}")
    if listed[f"data/current/{ROLLING_ARTIFACT}"] != ARTIFACT_SHA256:
        raise ValueError("rolling artifact hash mismatch: committed calculator bytes")

    document = json.loads((data_dir / ROLLING_ARTIFACT).read_text())
    provenance = json.loads((data_dir / "rolling_provenance.json").read_text())
    content = {key: value for key, value in document.items() if key != "content_sha256"}
    checks = {
        "rolling experiment classification": provenance["classification"]
        == "current_rolling_ce_acs_forecast",
        "rolling information date": provenance["information_date"]
        == document["information_date"],
        "rolling canonical content hash": (
            document["content_sha256"]
            == provenance["content_sha256"]
            == canonical_sha256(content)
            == CONTENT_SHA256
        ),
        "rolling calculator commit": provenance["calculator_commit"]
        == CALCULATOR_COMMIT,
        "rolling artifact provenance": (
            provenance["artifact_sha256"] == ARTIFACT_SHA256
            and provenance["calculator_artifact_path"] == CALCULATOR_ARTIFACT_PATH
            and provenance["calculator_repository"]
            == "https://github.com/PolicyEngine/spm-calculator"
        ),
        "rolling source fingerprints": provenance["source_sha256"]
        == source_fingerprints(document),
        "rolling executed code fingerprints": provenance["code_sha256"]
        == document["code_sha256"],
        "rolling component fingerprints": provenance["component_sha256"]
        == document["component_sha256"],
        "rolling assumption fingerprint": (
            provenance["assumption_sha256"]
            == document["assumption_sha256"]
            == canonical_sha256(document["assumptions"])
        ),
        "rolling inputs are outside frozen commitment": (
            provenance["covered_by_original_timestamp"] is False
            and provenance["frozen_commitments_modified"] is False
        ),
    }
    for scenario in document["scenarios"].values():
        published = scenario["years"]["2025"]
        checks["rolling published 2025 housing shares"] = (
            checks.get("rolling published 2025 housing shares", True)
            and published["national_status"] == "published"
            and published["housing_share_status"] == "published_anchor"
            and published["housing_share_source_ids"] == ["bls-spm-shares"]
        )
    failures = [label for label, okay in checks.items() if not okay]
    if failures:
        raise ValueError("; ".join(failures))
    return document
