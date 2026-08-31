# External strategy prior map — cycle-005 checkpoint classifications

This outcome ledger updates the research status of the immutable pre-outcome
definitions in `STRATEGY_PRIOR_MAP.md`. The frozen map remains byte-stable
because the experiment specification binds its SHA-256. External source
performance is not trusted or reasserted here; classifications apply only to the
disclosed A-share implementation tested on consumed 2018--2023 development data.

| Prior | Local implementation | Coverage | Net screen evidence | Severe-loss evidence | Executability | Classification |
|---|---|---:|---|---|---|---|
| EXT-JT-MOM-001 | Long top-20 12-minus-1-month momentum; monthly; h120 | 1,048 complete positions / 59 dates | -5.183% full; -0.588% / -8.919% blocks | +35.878 pp disadvantage | >=90% next-open | `ADVERSE_LONG_LEG_FORMULATION`; no replay |
| EXT-GH-52W-001 | Long top-20 price/action-coordinate 252-session high; monthly; h120 | 979 / 59 | -4.597%; +0.381% / -8.661% | +29.418 pp | >=90% | `CHRONOLOGICALLY_MIXED`; no replay |
| EXT-MG-INDMOM-001 | PIT leave-one-out equal-weight industry r120; monthly; h120 | 1,055 / 59 | +0.250%; +0.919% / -0.303% | +26.161 pp | >=90% | `CHRONOLOGICALLY_MIXED`; no replay |
| EXT-BCW-MAX-001 | Long top-20 negative prior-20-session MAX; monthly; h20 | 1,175 / 59 | -1.185%; -2.229% / -0.474% | +2.553 pp | >=90% | `ADVERSE_LONG_LEG_FORMULATION`; no replay |
| EXT-MIWA-INTRAREV-001 | Long lowest five-session open-to-close return; weekly; h5 | 4,790 / 241 | -0.070%; -0.192% / +0.011% | +7.265 pp | >=90% | `CHRONOLOGICALLY_MIXED`; no replay |
| EXT-AMIHUD-ILLIQ-001 | Canonical annual illiquidity characteristic not changed to monthly | Not run | Not estimated | Not estimated | Not tested | `CANONICAL_REPLICATION_DEFERRED_NOT_SILENTLY_ADAPTED` |
| EXT-FP-BAB-001 | Canonical beta-neutral leveraged long/short | Not run | Not estimated | Not estimated | Short/leverage conflict | `A_SHARE_IMPLEMENTATION_CONFLICT` |
| EXT-GGR-PAIRS-001 | Canonical 12-month formation / six-month long-short pairs | Not run | Not estimated | Not estimated | Short/borrow conflict | `A_SHARE_IMPLEMENTATION_CONFLICT` |
| EXT-BHM-RESMOM-001 | Canonical PIT factor-residual momentum | Not run | Not estimated | Not estimated | Registered factors absent | `DATA_UNAVAILABLE` |
| EXT-CRW-PRCLIM-001 | Existing exact A-share long limit-up-aftermath h5 | Not rerun | Previously adverse | Previously adverse | Previously screened | `EXISTING_EXACT_FORMULATION_ADVERSE_NO_RERUN` |

No result above establishes that the published prior is false. Long-only local
screens omit canonical short legs where disclosed, industry momentum substitutes
equal weighting for value weighting, and the five-test screen is development
replication evidence rather than independent confirmation.
