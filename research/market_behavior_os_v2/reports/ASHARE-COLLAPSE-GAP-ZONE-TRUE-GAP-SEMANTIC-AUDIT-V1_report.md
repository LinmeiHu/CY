# A-share Collapse-Gap-Zone True-Gap Semantic Audit V1

This audit reads frozen identities and entries only. It does not read exits, returns, NAV, or outcome statistics.

## Verdict

`V1_SEMANTIC_CONTRACT_INVALID`

V1 used `[Open_t, Low_{t-1}]`; the intended no-trade gap is `[High_t, Low_{t-1}]`. Future post-zone depth is no longer allowed to erase gap identity.

## Damage summary

| Period | Trades | Target not true | Entry below true gap | Lower true layer | Semantically valid |
|---|---:|---:|---:|---:|---:|
| DEVELOPMENT | 207 | 15 | 160 | 34 | 32 |
| VALIDATION | 94 | 10 | 78 | 12 | 10 |
| COMBINED | 301 | 25 | 238 | 46 | 42 |

## 600250.SH example

- Legacy target survives as true gap: `True`.
- Entry reached true target: `False`.
- Lower significant true layers: `1` (`600250.SH|2022-04-27`).
- Legacy trade semantically valid: `False`.

## Governance

No corrected return replay is authorized by this audit. A corrected V2 contract must be frozen before any Development economics are regenerated. 2022-2023 cannot regain first external Validation status.
