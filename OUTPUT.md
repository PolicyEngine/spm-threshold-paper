# Paper-support change report

## State

Implemented on `max/spm-paper-voice-20260913`, based on fetched
`origin/master` at `bcc40c38100bd3eacb28eee76ab267189dfa3e4e`.

## Files changed

- `docs/forecast-record.md`: supporting registration/evaluation record with
  the original and amended tenure triples, exact 0.1 to 0.3 percent movement,
  correction rationale and chronology, timestamp qualification, source links,
  and the original 0.98 versus amended 1.17 percent evaluation.
- `scripts/evaluate_nowcast_2025.py`: preserves the existing five-row
  `evaluation.md` archive and emits the four-row `evaluation_main.md` table.
- `paper/tables/evaluation_main.md`: the only new generated table.
- `scripts/check_paper.py`: classifies `evaluation.md` as archived,
  requires `evaluation_main.md` in the article set, and validates moved
  chronology claims against the support record.
- `tests/test_paper_guard.py`: adds support-record, archive-tampering, and
  four-rule main-table coverage. The existing mutation fixture wording
  `real growth of 0.914 percent` remains preserved.
- `PROGRESS.md`: committed progress ledger.

The root-owned dirty edits in `paper/index.qmd` and the existing root test
fixture change were preserved. No root-owned manuscript or README file was
edited by this work.

## Checks

- `python -B tests/test_paper_guard.py`: 31 tests passed.
- `python -B scripts/check_paper.py`: passed — 15 tables, prose pins, and
  commitment checks passed.
- All 42 existing files under `data/` and `paper/tables/` are byte-identical
  to `origin/master`; no existing data, checksum, proof, tag, or generated
  table was modified.
- No heavy native computation, model computation, deployment, or PR was
  performed.

## Main table and guard expectations

`paper/tables/evaluation_main.md` contains exactly these four data rows, in
this order:

1. `Committed equal blend` — `-0.69%`, `-0.55%`, `-2.27%`, `1.17%`.
2. `CE replication growth ratio alone` — `+0.62%`, `+0.03%`, `-1.60%`,
   `0.75%`.
3. `FCSUti-composite CPI aging alone` — `-2.01%`, `-1.14%`, `-2.93%`,
   `2.02%`.
4. `All-Items CPI-U aging (status quo)` — `-2.56%`, `-1.70%`, `-3.47%`,
   `2.58%`.

The archive `paper/tables/evaluation.md` retains the original blend row and
all historical labels/numbers. The guard requires the committed amended
tenure triple once in QMD, requires the original/amended amounts, chronology,
0.1 to 0.3 percent qualification, rationale, timestamp qualification, and
0.98 evaluation in `docs/forecast-record.md`, and retains the 1.17 QMD pin.

## Blockers

No blocker remains in the current compatible checkout. The root should run
its final checks after any further manuscript prose edits; this task did not
edit `paper/index.qmd` or force any manuscript compatibility changes.
