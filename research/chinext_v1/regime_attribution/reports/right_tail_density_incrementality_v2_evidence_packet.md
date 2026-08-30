# EXP-RTD-002 evidence packet — right-tail density incrementality

## Decision

`REJECT` H-020. Eligible-universe 20-session right-tail density describes MFE
opportunity univariately, but adds essentially no information after the frozen
H-004 breadth and trend controls and does not replicate across independent blocks.

## Engineering and PIT integrity

- EXP-RTD-001 remains invalid and has no accepted result.
- EXP-RTD-002 preserves every scientific field and uses fresh output paths.
- Final frame: 399 rows, 387 feature-complete, 383 control-complete.
- `index_realized_vol20`: exactly one column, sourced from accepted pre-entry
  controls, zero missing values, zero duplicate columns.
- Source keys are unique; row count and 213 false-breakout labels are conserved.
- Signal-date availability and T+1 first applicability pass 399/399 rows.
- No threshold, interaction, overlay, replay, or production rule was tested.
- Two executions are byte-identical; the 250-file preexisting aggregate remains
  `998988e3d20436cbb5490ab073da0605f2bf457d9fd0f8b839be6249a6ea3974`.

## Frozen evidence

| Test | Estimate | LOYO direction | Gate |
|---|---:|---:|---:|
| Raw MFE | rho 0.111 | 8/8 positive | pass |
| Within-year MFE | rho 0.114 | — | pass |
| Breadth/trend controlled | partial rho 0.002 | 5/8 positive | fail |
| Breadth/trend/risk controlled | partial rho -0.007 | 4/8 positive | fail |
| MFE>=20% opportunity | rho 0.119 | 8/8 positive | pass |
| Non-false-breakout | rho 0.056 | 8/8 positive | outcome component pass |
| p90 neighbor | rho 0.098 | 8/8 positive | neighbor pass |
| p90-p10 neighbor | rho 0.070 | 8/8 positive | neighbor pass |
| Ex-Top4 P&L | rho 0.117 | 8/8 positive | tail pass |

Block MFE rhos are `0.264` for 2018-2021, `-0.103` for 2022-2023, and `0.022`
for 2024-2025. Only one block carries the pooled relationship. Raw, outcome, and
neighbor gates pass; controlled and full falsification gates fail.

## Falsification interpretation

The collapse from raw rho 0.111 to controlled rho 0.002 is the decisive result.
It supports redundancy with already frozen breadth/trend state rather than an
independent leadership-intensity mechanism. Positive neighboring definitions and
tail robustness do not override the preregistered incremental gate or block
instability.

H-020 therefore supplies no new opportunity signal and cannot motivate a
threshold, breadth interaction, overlay, or strategy modification.

## Output identities

- table: `315151223b71e7bcc56a7e6d8b048f086f25e616d69dfac5b88fe19acc329b5c`;
- JSON: `9abd1860f8c9227acdccd3984abfa7fca789c22b47ad2bc604a5d34257fc5606`;
- generated report: `23c6a9715e0485753a6525b093ee017cf6812dc78df9b3e2e4ccab03c39e9608`.
