"""Publish aggregate diagnostics with hashes of omitted calculator metadata.

The full immutable local result remains the source artifact. This removes bulky
repeated geography diagnostics only; it does not alter any aggregate statistic.
"""

import argparse
import hashlib
import json
from pathlib import Path


def compact(path):
    raw = Path(path).read_bytes()
    cell = json.loads(raw)
    omitted = []

    def remove(mapping, key, pointer):
        value = mapping.pop(key)
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        omitted.append(
            {
                "json_pointer": pointer,
                "entries": len(value),
                "canonical_json_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

    provenance = cell["provenance"]["spm_provenance"]
    remove(provenance, "geographies", "/provenance/spm_provenance/geographies")
    for year, receipt in provenance["years"].items():
        for key in ("geography_by_area", "median_diagnostics", "rent_indices"):
            remove(receipt, key, f"/provenance/spm_provenance/years/{year}/{key}")
    cell["publication_copy"] = {
        "source_file": Path(path).name,
        "source_file_sha256": hashlib.sha256(raw).hexdigest(),
        "source_bytes": len(raw),
        "aggregate_statistics_unchanged": True,
        "omitted_calculator_metadata": omitted,
        "note": "The abbreviated spm_provenance is not a complete calculator receipt. Retain the full source file for geography-level audit.",
    }
    return cell


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = compact(args.source)
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    with args.destination.open("x") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")


if __name__ == "__main__":
    main()
