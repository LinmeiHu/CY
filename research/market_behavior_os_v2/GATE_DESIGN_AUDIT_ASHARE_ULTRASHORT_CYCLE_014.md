# A-share ultra-short cycle 014 gate design audit

Frozen before any Cycle-014 forward-outcome join. The 2018--2023 history is
consumed development evidence. This audit distinguishes validity, economics,
diagnostics, and coverage; diagnostics are not silently promoted into AND-gates.

## Gate ledger

| Gate | Class | Failure mode prevented | Why a useful 1--3-session strategy should satisfy it | Numeric basis | Possible false rejection | Redundant? | Failure means |
|---|---|---|---|---|---|---|---|
| Registered CY-006/CY-008/QD-004 identities and bound hashes | HARD_VALIDITY | Unregistered, revised, or silently substituted data | A causal result must be reproducible from the governed snapshot | Exact registered hashes; no fitted number | A real edge present only in another source | No | Scientific validity fails |
| `hard_valid`, causal `available_at`, snapshot identity, PIT industry, and no blocking action at signal formation | HARD_VALIDITY | Lookahead, bad lineage, invalid bars, or future industry membership | The signal must have existed at the declared 15:30 decision | Repository contract | An edge concentrated in ungoverned rows | No | Scientific validity fails |
| Completed-session signal; earliest entry next legal open; T+1, limits, suspensions, lots, actions, and no replacement | HARD_VALIDITY | Same-bar fills and fictitious execution | The strategy must be legally and physically executable | Repository execution contract | A genuine sub-session edge whose half-life expires before next open | No | Scientific validity or executable translation fails |
| Natural h1/h2/h3 construction is independent by horizon | HARD_VALIDITY | Conditioning h1/h2 on availability of h3 | A short response must not require a longer future path | Causal horizon definition | None expected | No | Scientific validity fails |
| Positive mean net primary-horizon return after 20 bps per side | ECONOMIC_PROMOTION | Promoting a statistically visible but loss-making long leg | A standalone long-only replay needs positive economics after canonical friction | Canonical 20 bps/side repository convention; break-even is zero after cost | A diversifying negative-mean hedge-like component | No | Actual standalone economics fail |
| Positive primary-horizon event-minus-date-control net excess | ECONOMIC_PROMOTION | Calling a market-day effect stock-selection alpha | The selected state should improve on a contemporaneous causal alternative | Economic break-even relative to named control; no extra bp floor | A broad market-timing edge shared by all names | Partly with positive net return, but tests a different claim | Proposed stock-selection economics fail |
| No negative early or late block primary net return or excess | ECONOMIC_PROMOTION | Promoting a sign-reversing development result | A recurring discovery candidate should not rely on one coarse regime | Zero is the natural sign boundary after canonical cost | A useful regime-conditional or diversifying strategy | No | Recurring-edge story fails; classify chronology separately |
| At least 100 complete selected and matched outcomes, 30 selected and matched decision dates in each block, 20 securities, and 5 PIT industries | ECONOMIC_PROMOTION | A few names/dates or a tiny matched subset masquerading as a deployable strategy | A portfolio and its causal comparison need repeated, cross-sectional opportunity | Effective-sample and actual-usability reasoning; deliberately no percentage-coverage gate | A rare but very high-payoff event strategy | No | Usable opportunity or comparative evidence is not established |
| At least 90% next-open entry executability | ENGINEERING_COVERAGE | A paper edge dominated by unbuyable next opens | Most generated signals must reach the intended entry | Existing repository executable-screen convention | A valid selective strategy that explicitly models skipped entries | No | Actual portfolio usability fails, not data validity |
| `severe_loss10` and matched-control severe-loss difference | MECHANISM_DIAGNOSTIC | Hidden left-tail deterioration | Tail behavior matters, but one fixed rate is not universally required for ultra-short strategies | Existing definition: cost-aware adverse path at or below -10%; no hard deterioration threshold frozen | Not applicable because diagnostic only | No | Tail economics are reported and judged in replay; screen is not automatically vetoed |
| Family-A event versus simple-seal control and acceptance-score ordering | MECHANISM_DIAGNOSTIC | Mislabeling generic limit-day strength as reopen--reseal acceptance | The lifecycle story predicts stronger accepted reseals than causal same-date simple seals | Sign only; no arbitrary magnitude | A tradable event effect with an incorrect lifecycle explanation | No | Economic story weakens; alpha can still be judged separately |
| Family-B amount shock is own-history unusual and acceptance score is not strongly redundant with prior return/range/r20 | MECHANISM_DIAGNOSTIC | Relabeling momentum or large volume as assimilation | The proposed mechanism should contain information beyond obvious daily geometry | Trailing 252-session 90th percentile with 120-history minimum is an established PIT tail-event convention; redundancy is reported continuously | A useful momentum-conditioned execution signal | No | Mechanism distinctness weakens; not an automatic strategy veto |
| Deterministic rerun and artifact hash identity | HARD_VALIDITY | Unstable selection, reduction order, or replay | The same frozen inputs and rules must reproduce exactly | Byte identity | A numerically equivalent but non-byte-stable implementation | No | Scientific reproducibility fails |
| Replay completes with zero unresolved terminal lots | HARD_VALIDITY | Partial equity or hidden suspended positions | Portfolio metrics require a complete cash/share ledger | Existing replay contract | A valid strategy requiring a longer explicit liquidation horizon | No | Investable result is unavailable |
| Replay total return is positive and exceeds its named control; both block returns exceed control; Sharpe exceeds control | ECONOMIC_PROMOTION | Promoting factor elegance without marginal portfolio value | The simplest portfolio must add realized value over its causal baseline | Actual portfolio break-even and marginal usefulness; no arbitrary Sharpe floor | A low-correlation strategy whose standalone replay is slightly weaker | No | No strategy-candidate claim; diagnostic diversification is insufficient |

## Non-gates

The following remain reported diagnostics: p-values, h1/h3 neighbor signs,
year-by-year counts, severe-loss deterioration, raw-score correlations,
industry concentration, security concentration, and mechanism-specific event
geometry. None is an automatic screen veto unless a validity gate above fails.

No 80% matching or coverage requirement exists. Missing controls reduce the
estimable matched sample and are reported; they do not permit replacement,
future matching, or a favorable rematch.
