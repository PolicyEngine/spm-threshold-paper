# SPM uprating and housing validation, September 19, 2026

This is a retrospective development experiment. It does not amend the registered
September 11 forecast or the September 17 forecast grade.

## Controlled uprating comparison

Compare these exact country-model source trees:

- Before: `238321d3b9ff44d2b6f3cbe378040be263221d47` (version 2.6.8).
- After: `44001a4c24ae5d1bce9179e2bb285b41cae6a272` (version 2.6.9 plus
  the mapping-fix commit).

The intervening history consists of #9526, its release-version commit, and
#9527. No unrelated model change is included. Package-version labels alone
cannot identify the after source tree; the full Git revision is required.

For each source tree, run 2024 baseline, 2025 baseline, and 2025 with national
threshold bases anchored to corrected 2024 values times CPI-U. Use the same
population file, Python environment, Core, calculator and seed. Run only one
population process at a time. Summarize person-mapped MicroSeries with their
own weighted operations. Calculate the threshold contribution on 2025 resources;
label the remainder as the change with national threshold bases held constant
in real terms. It is not an isolated causal resource effect.

The attempted `policyengine` 6.0.0 interface rejects the experimental 2.6.x
models at import: the data certificate's compatible range is below 2.3. The
`allow_unmanaged` dataset option does not bypass that check. Preserve the check;
do not modify the release manifest or claim certification. Run this controlled
country-model regression through the country package with an explicit
development-mode flag instead. Record actual versions, source revision,
source path, dataset hash, runner hash, and timings, and mark the outputs
`bundle_certified=false`. Keep all other installed runtime dependencies fixed.

Population SHA-256:
`6496cc4393d4d3c6574f76eca231de5898c803b9067645591fd5c4d3e65aee84`.
The local file is the byte-identical September 15 republication of the
September 9 population used for the forecast.

Historical comparisons use the committed results at paper revision
`a79c03adbe8ec2ef432a7652f6d7123d127af24e`; they are not substitutes for
the controlled before/after comparison.

## Housing reference calculation

Read primary Census methodology before changing the reference. Preserve the
frozen oracle, endpoint files and original acceptance verdict. A successor
replay checks the explicitly documented country-model contract on those saved
outputs and includes independent arithmetic fixtures. Passing this replay
does not establish Census parity for assumptions not supported by the source.

## Frozen artifacts

Verify these hashes again at completion:

- Registered forecast: `a1f6bd78dbdc5fa533d409101170401558bf010bf93647a26f097dd068801941`.
- September 17 grade: `1c9682bccbc42f58cf13cb0d407f3dcfc72ed6b9e7f6de006cc53bfa0f53ac0e`.

The original files and analysis remain untouched. New scripts, results and
interpretation belong in this dated analysis directory.
