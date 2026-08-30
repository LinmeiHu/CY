# EXP-OBL-004 frozen-lineage outcome reveal

Decision: `REJECTED`.

Verdict: `FROZEN_LINEAGE_STRENGTH_FAILS_PRIMARY_RAW_OR_CONTROLLED_GATES`.

## Primary frozen tests

| Endpoint | Raw rho | Raw LOYO + | Controlled rho | Controlled LOYO + | BH q |
|---|---:|---:|---:|---:|---:|
| mfe | 0.014924 | 6/8 | 0.017164 | 6/8 | 0.766319 |
| non_false_breakout | 0.026966 | 7/8 | 0.043243 | 7/8 | 0.766319 |

## Frozen lineage summaries

| Lineage | n | Mean MFE | False-breakout rate | Mean terminal return | Extreme-winner rate |
|---|---:|---:|---:|---:|---:|
| L00_BASE_LOW_ACCEPTANCE_LOW | 92 | 0.1184 | 0.5652 | -0.0020 | 0.0109 |
| L01_BASE_LOW_ACCEPTANCE_HIGH | 112 | 0.1531 | 0.5536 | 0.0241 | 0.0357 |
| L10_BASE_HIGH_ACCEPTANCE_LOW | 96 | 0.2114 | 0.4896 | 0.0668 | 0.0521 |
| L11_BASE_HIGH_ACCEPTANCE_HIGH | 99 | 0.1778 | 0.5253 | 0.0405 | 0.0505 |

Gates: `{"controlled_both_endpoints": false, "falsification": false, "neighbor_both_endpoints": false, "raw_both_endpoints": false, "temporal_both_endpoints": false}`.

Lineages were frozen without outcomes. Full signal-session information is available at 15:30 for T+1 or later only. This reveal tests mechanism separation and authorizes no entry, exit, size, overlay, or production rule.
