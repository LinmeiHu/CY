# CY-052 TemplateAudit signal-bar correction receipt

## Scope and cause

The original TemplateAudit pixel aid searched only through image column `x < 708`. Some anonymous charts place the true final colored candle at columns 708–710, immediately before the orange signal marker, so the earlier ledger could classify the penultimate candle. The original ledgers remain untouched and must stay isolated from Phase1 freeze inputs.

Every anonymous individual chart for 1001–1483 and calibration charts 1–25 was reopened. The corrected reader selected the rightmost red/green candle component through column 710, before the marker. A candle was directional only when its body was clearly visible and its close lay near the relevant bar extreme; otherwise it was conservatively `NEUTRAL`. No identity, crosswalk, outcome, Stage-B, future-path, or post-signal source was read.

## Main ledger correction (1001–1483)

- Output: `ASHARE-V34R1_phase1_annotations_templateaudit_corrected_1001_1483.json`
- Items: 483; reviewer: `TemplateAuditCorrectedSignalBar`
- Changed `signal_candle`: 216; changed `evidence`: 216
- Non-target changes across `chart_number`, `primary_morphology`, `market_tape`, and `turnover_state`: 0
- Corrected signal totals: `STRONG_CLOSE` 34; `WEAK_CLOSE` 107; `NEUTRAL` 342

| Old → corrected signal | Count |
|---|---:|
| `NEUTRAL` → `NEUTRAL` | 243 |
| `NEUTRAL` → `STRONG_CLOSE` | 28 |
| `NEUTRAL` → `WEAK_CLOSE` | 73 |
| `STRONG_CLOSE` → `NEUTRAL` | 57 |
| `STRONG_CLOSE` → `STRONG_CLOSE` | 6 |
| `STRONG_CLOSE` → `WEAK_CLOSE` | 16 |
| `WEAK_CLOSE` → `NEUTRAL` | 42 |
| `WEAK_CLOSE` → `WEAK_CLOSE` | 18 |

## Calibration correction (1–25)

- Output: `ASHARE-V34R1_phase1_calibration_templateaudit_corrected_0001_0025.json`
- Items: 25; reviewer: `TemplateAuditCorrectedSignalBar`
- Changed `signal_candle`: 13; changed `evidence`: 13
- Non-target changes across `chart_number`, `primary_morphology`, `market_tape`, and `turnover_state`: 0
- Corrected signal totals: `STRONG_CLOSE` 4; `WEAK_CLOSE` 6; `NEUTRAL` 15

| Old → corrected signal | Count |
|---|---:|
| `NEUTRAL` → `NEUTRAL` | 12 |
| `NEUTRAL` → `STRONG_CLOSE` | 3 |
| `NEUTRAL` → `WEAK_CLOSE` | 5 |
| `STRONG_CLOSE` → `NEUTRAL` | 1 |
| `STRONG_CLOSE` → `WEAK_CLOSE` | 1 |
| `WEAK_CLOSE` → `NEUTRAL` | 2 |
| `WEAK_CLOSE` → `STRONG_CLOSE` | 1 |

## Static verification and bindings

- Public schema SHA-256: `89eeb590b025a4d126d328acbd47a803696606a891a8b804264bf326705fb90d`
- Original main baseline SHA-256: `3372fbedecf17cb06bcf145d22cd122d486cc21ceef68aa957277b5e06cbeca8`
- Corrected main SHA-256: `2c149c2ffe5587afd387eb55d2a54d4f35f2c14a5d0816f90593a1e53f15a9f4`
- Original calibration baseline SHA-256: `5f78f8b39c195f87ef91c53456301ceda37959328d3dcb0ee2772b87e4de7a2f`
- Corrected calibration SHA-256: `e54a7dc97b0f6cd357dcf436c0631e17d4e8e88ed2e458046521802917aac295`
- Independent sheet-0021 calibration SHA-256: `63202e6a73d57d8c6c42d962fe59837d552aa1e419fa3679f022b26c07f82f70`

Both corrected ledgers validate against the public schema, preserve ordered and unique chart coverage, use the exact seven-field contract, and change evidence if and only if the signal label changed. No Stage-B run was performed.
