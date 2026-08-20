# json — the contract

Three implementations, one specification. These files are the reason four languages can be
kept in agreement at all: the logic is deliberately rewritten per language, the contract is
not.

| file | what it fixes |
|---|---|
| `grammar.json` | the closed part of the grammar — three progress words, eleven distances, the nine verdicts, thirty stopwords, the stem rule, Φ's weights (0.5 goal / 0.3 distance / 0.2 progress) and `goal_min` = 0.30 |
| `attention.json` | the measured calibration: drift incidence by time since the last human turn, and the harness's own overhead |
| `drift-vectors.json` | the parity vectors, generated **from** the Python package — 16 sequences, 69 steps |

## Why these are not just data

`goal_min` was a literal `0.30` written into `drift.ts` twice, while Python read it from
`grammar.json`. A calibration change would have moved one implementation and not the other,
silently. It is read from here now.

## Why the vectors are sequences

The first check sets the frozen ground and every later verdict depends on it. One-shot
cases would exercise almost none of the instrument.

**A parity check only covers the behaviour its cases ask for.** Until 2026-08-20 no vector
declared a `parent_goal`, so none expected `excursion` — and the TypeScript implementation
shipped eight of the nine verdicts for months with the gate green throughout. The generator
covers it now. When you add a verdict, add a case.

## Copies

The packages vendor these, because a `pip install` and an `npm install` cannot reach this
repository. **This directory is the source**; `typescript/vendor.mjs` re-copies on demand
and `laserbrain/grammar.json` ships inside the wheel. If they disagree, the build fails —
that is what `check-drift-parity` is for.
