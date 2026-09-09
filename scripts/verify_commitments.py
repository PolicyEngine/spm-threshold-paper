"""Check archived proof bytes and Git identities, not blockchain attestations."""

import hashlib
import json
import subprocess

PRESERVED = {
    "data/COMMITMENT-MANIFEST.txt": "18d82ad41fad56b42dfce537523e50b5b89956b8161dc60e60d90f8753b39b37",
    "data/COMMITMENT-MANIFEST.txt.ots": "1e23ccf54836b8fd7ede8d13ed2b606fa9ae6d7b0801794841b7d660a25004bb",
    "data/SHA256SUMS.precommit": "a49ffac0e653e1a2c94861676e9a21d2d5761813f43d46482c7f8dd8baf1fe28",
    "data/SHA256SUMS.precommit.ots": "dd36909119b5303c9cf5e3c36e6e4061724e288a1b350a59ebe2285aac396512",
    "data/SHA256SUMS": "b8ad819d509cbac69333c39a3fa826e2a3c158fa52ed651a7f46f70106b523d8",
    "data/SHA256SUMS.ots": "5beecfc52227154ac43123e57a1379edcf6b34b3f59c828102cc85c2d77041cb",
}
TAGS = {
    "v1.0-original-nowcast": {
        "tag_object": "12b7042a960412477af53c62ebd961ded1a2625e",
        "commit": "a8b7c51869e64e36517d4eca8d5dbd6e2e0cde5b",
        "nowcast_sha256": "19a1f44d10d9151c0b4d3cdb953e9d338bc9dd7a6fe06b88a91665649a5931c0",
    },
    "v1.1-amended-nowcast": {
        "tag_object": "3759670e314b762fa24348a3c9a16526cdc74b47",
        "commit": "d72e1dc083ad1abc95b1c88fd1b782944454074b",
        "nowcast_sha256": "259a5b2e0d15646722fe309f741546e364827fab053c73c99d273061fa0b1ba8",
    },
}


def verify_commitments(repo):
    failures = []
    for name, expected in PRESERVED.items():
        path = repo / name
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            failures.append(f"preserved commitment/proof bytes changed: {name}")
    try:
        amendment = json.loads(
            (repo / "data/COMMITMENT-AMENDMENT-2026-09-08.txt").read_text()
        )
        if amendment["date"] != "2026-09-08" or amendment["tags"] != TAGS:
            failures.append(
                "dated commitment amendment differs from expected identities"
            )
        if (
            amendment["original_manifest_sha256"]
            != PRESERVED["data/COMMITMENT-MANIFEST.txt"]
        ):
            failures.append(
                "commitment amendment does not identify the archived manifest"
            )
        if amendment["covered_by_original_timestamp"] is not False:
            failures.append(
                "amendment must not claim coverage by the original timestamp"
            )
    except (OSError, KeyError, ValueError, TypeError) as error:
        failures.append(f"invalid commitment amendment: {error}")
    for tag, expected in TAGS.items():
        commands = {
            "tag_object": ["git", "rev-parse", tag],
            "commit": ["git", "rev-parse", f"{tag}^{{commit}}"],
            "nowcast_sha256": ["git", "show", f"{tag}:data/nowcast_2025.json"],
        }
        for key, command in commands.items():
            result = subprocess.run(command, cwd=repo, capture_output=True, check=False)
            if result.returncode:
                failures.append(
                    f"cannot resolve {tag} {key}; full history and tags required"
                )
                continue
            actual = (
                hashlib.sha256(result.stdout).hexdigest()
                if key == "nowcast_sha256"
                else result.stdout.decode().strip()
            )
            if actual != expected[key]:
                failures.append(f"tag identity mismatch: {tag} {key}")
    return failures
