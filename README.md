# Nowcasting Supplemental Poverty Measure thresholds

Working paper on the July 2026 BLS threshold correction, public CE
replication, threshold projection, and the completed evaluation of the
2025 forecast. The September 8 revision preserves that forecast and its
evaluation, and adds a separately identified current-method experiment
and portable threshold release.

## Build and verify

```bash
python3 -B scripts/check_paper.py
python3 -B -m unittest discover -s tests -v
quarto render --to html
quarto render --to pdf
```

The guard and table generators use the Python standard library. Quarto
1.9.36 and TeX Live 2026 render the HTML and PDF to `_output/paper/`.
Clone with full tag history and check out the exact revision to reproduce
it. The guard first checks artifact hashes and frozen Git identities,
then generates tables and evaluation JSON in temporary storage and
compares every output byte with the checkout. It never repairs or
restores source artifacts. The regression tests verify that failed checks
leave source bytes unchanged.

## Preserved forecast evidence

The tags `v1.0-original-nowcast` and `v1.1-amended-nowcast`, forecast
bytes, and all original OpenTimestamps manifest/proof pairs are preserved.
Two hashes in `data/COMMITMENT-MANIFEST.txt` were incorrect; the dated
`data/COMMITMENT-AMENDMENT-2026-09-08.txt` records the exact tag hashes and
the original manifest digest. The original proof does not cover that
amendment. This revision verifies retained proof bytes and Git identities;
it does not independently reverify blockchain attestations.

`data/SHA256SUMS` continues to cover only the frozen artifacts. New inputs
have their own `data/current/SHA256SUMS`; they do not replace the frozen
forecast or become a new prospective commitment. `data/PROVENANCE.md`
describes both collections and the original implementation pin.

## Companion implementation

The current spm-calculator rebuild provides a portable release, standalone
unit calculations, CE research replication, projections, and explicit
PolicyEngine, Microcosm, and real native Axiom adapters. This paper pins version 0.5.0 at development commit
`9e6ae4798458771231613b994df2345dd1685214`; it does not claim that a model
migration or public deployment has occurred. The paper consumes the same release bytes as those adapters.
