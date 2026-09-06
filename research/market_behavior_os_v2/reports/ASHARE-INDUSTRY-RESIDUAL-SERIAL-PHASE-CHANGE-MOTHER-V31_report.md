# V31 — Industry-Residual Serial Phase-Change Mother

## Conclusion

V31 closes as `CLOSE_WITH_ZERO_RULES`. Its outcome-blind representation was valid, broad and distinct from the frozen control set, but its frozen signal economics were strongly chronological: 2018H2 lost, 2019 was modestly positive, and only 2020H1 cleared the required +4% mean. Complete two-pass review of all 1,602 signal charts found no robust ex-ante visual discriminator.

The charts did contain a clear *post-entry* distinction. Among 815 trades that eventually earned at least 4%, 689 (84.54%) showed fast acceptance. Among 421 ordinary losses, 325 (77.20%) showed early rejection. Those observations describe what happened after the signal; they are attribution, not predictors, and the same realized paths cannot be used to manufacture an entry-time rule.

No portfolio replay was run. The 2021 buffer and 2022–2024 outcomes remain closed.

## Frozen mother signal

At each completed month-end close, V31 computed a daily stock return residual against the exact leave-one-out median return of the stock's PIT industry. It required lag-one Spearman dependence to change from nonpositive over the preceding nonoverlapping 40-pair window to positive over the latest 20-pair window, with a positive current residual. Each PIT industry retained the largest phase change, subject to the frozen liquidity, exact-history and 20-session cooldown contracts.

Stage A read no outcome column or post-signal row. It froze 1,602 events across 24 decision dates:

| Signal period | Events | Decision dates | PIT industries | Symbols |
|---|---:|---:|---:|---:|
| 2018H2 | 388 | 6 | 96 | 365 |
| 2019 | 815 | 12 | 98 | 694 |
| 2020H1 | 399 | 6 | 96 | 370 |

The same-date median Spearman associations with raw 20-session return, raw 60-session return, 60-session return volatility and the one-to-60-session turnover ratio were small (global values +0.0431, +0.0196, -0.0166 and +0.0815). The representation and opportunity gates therefore passed before outcomes were attached.

## Frozen signal-level economics

The one-time execution contract used the first legal, non-upper-limit open from signal+1 through signal+3, a +10% gross target, a 20-session fallback lifecycle, T+1, binding limit/suspension/corporate-action/coordinate-lineage rules, and 40 bps round-trip cost.

Of 1,602 signals, 1,594 completed. Four had no legal entry and four failed coordinate lineage after entry.

| Signal period | Signals | Complete | Mean net | Median net | Positive | At least +4% | Severe loss | Target hit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018H2 | 388 | 388 | -2.688% | -3.294% | 38.14% | 29.90% | 24.74% | 28.35% |
| 2019 | 815 | 810 | +1.395% | +5.806% | 58.64% | 51.36% | 14.32% | 48.40% |
| 2020H1 | 399 | 396 | +4.793% | +9.600% | 77.02% | 71.46% | 8.33% | 68.69% |
| Overall | 1,602 | 1,594 | +1.246% | +5.165% | 58.22% | 51.13% | 15.37% | 48.56% |

The breadth requirement was satisfied, but the preregistered gate required mean net return above 4% in *every* development block. Both 2018H2 and 2019 failed it. Aggregate positivity does not override that failure.

## Complete two-pass chart review

Every frozen signal received one full and one chronology-masked chart spanning -126 through +126 global market sessions. The pre-signal and post-signal regions were scaled independently, so future extremes could not alter the appearance of the signal-time panel. Review covered all 65 masked chronology sheets and all 66 outcome sheets at original resolution, with every event covered exactly once in each pass.

Phase 1 froze signal-time morphology before any outcome sheet was opened:

| Frozen signal-time shape | Count |
|---|---:|
| Base or compression | 133 |
| Downtrend or repair | 423 |
| Mature extended high | 147 |
| None clear | 58 |
| Orderly advance | 220 |
| Structural breakdown | 370 |
| Volatile topping | 251 |

Five broad motifs recurred: old-peak decay or structural break; a quiet low base followed by terminal expansion; orderly higher-low advance; mature markup becoming a volatile top; and deep U/W repair below an old high. Calendar clustering was already conspicuous during the blind pass.

Phase 2 then reviewed five mutually exclusive outcome buckets: 815 profits of at least 4%, 113 profits below 4%, 421 ordinary losses, 245 severe losses and eight non-completed lifecycles. Every Phase-1 morphology occurred among both winners and losers. Visually attractive advances and bases had losing counterexamples; damaged or repair structures also produced fast winners. The static pre-signal overlap and calendar composition prevented a simple causal rule.

The strong post-entry regularities do not solve that problem:

- 689 of 815 at-least-4% winners showed fast acceptance; another 41 were slow acceptance and 43 chopped before acceptance.
- 325 of 421 ordinary losses showed early rejection; another 92 chopped before losing.
- Severe losses often rejected early and some repaired only after H20, but that group was reviewed descriptively rather than assigned individual path codes.

These are outcome-path descriptions. They cannot enter the original signal, and V31 did not use them as predictors.

## Process disclosure

After the complete Phase-1 signal-time ledger had been frozen, but before a separate rule-compression specification existed, the primary agent accidentally ran one unpersisted numeric aggregation of the frozen shape labels against outcomes. It promoted no rule, produced no replay and opened no later-period data.

The apparent `BASE_OR_COMPRESSION` subgroup was positive in aggregate among 132 completed rows, but 2018H2 was negative and the annual completed counts were only 25, 50 and 57. It therefore failed both chronological and required-breadth criteria. The accidental diagnostic cannot be treated as confirmation; it reinforces rather than changes the conservative zero-rule close.

## Why no acceptance or exit rule was recycled

V29R1 already tested one-day acceptance on 9,368 charts. Its breadth passed, but every annual mean remained below 4%. V27 already tested a no-progress exit: it lowered severe-loss incidence but sacrificed 103 eventual +4% winners and reduced total return by 12.09 percentage points, CAGR by 1.44 percentage points and Sharpe by 0.30. Recasting V31's post-entry path attribution as either rule would repeat consumed evidence at low information value.

## Evidence bindings

- Stage A result: `/Volumes/quant/CY_quant_research/ashare_industry_residual_serial_phase_change_mother_v31/stage_a/result.json`, SHA-256 `55c772d5c77ff4ee2c333aececa08d24a787dc3a4033952d7d2371e70ccba165`.
- Stage B result: `/Volumes/quant/CY_quant_research/ashare_industry_residual_serial_phase_change_mother_v31/stage_b/result.json`, SHA-256 `2c28f3b4ee1437d9dbdb1460792a72c09063d55067cdcb74aff918b58fb988b0`.
- Stage C chart manifest: `/Volumes/quant/CY_quant_research/ashare_industry_residual_serial_phase_change_mother_v31/stage_c_charts/manifest.json`, SHA-256 `b8dd9ef51a1dec86205a9ce856cfafe87cd650b54835cf1f2943fbcf30624c25`.
- Phase-1 manifest / summary / CSV ledger: SHA-256 `453e3268ca0dc979064772575eec6f6f974fc657fcc81396f966c9455cd7d40a`, `b3a5d9cdf25060465e1d55cf72afeccc8f72dfccacde60670590d8bb2def24be`, `6cde4b72b3b7016d9be7a1a47fed40f7a0de5c4fb5ca2297e5bc6cccfe7081ff`.
- Phase-2 manifest / summary / CSV ledger: SHA-256 `735cea70834b2f24841d7318e6e339ea5835eec3cff9a4530a4e01b594d60f28`, `52946113ff2bf79eae1be51362f4f2c154a033d5ed504dcdefa3f67644fe3e92`, `f340ffa6ceffffe79f0aab6189792d8c66a3e6ca4f7bce3b5d54794966d48e8d`.
- Frozen Stage-A, Stage-B and visual-review specifications: SHA-256 `d43d03bc04b26fbc0b79207c5d0598024f5d60921522e186283d523ed670c65c`, `036b165d6fbeac85dd3af52b83365ead620fd2541d0ed76fe150a4636b7ab48a`, `30b281e890c1d37c8d772883f77c4b54caf0251b4bb9d4db3af41d583a5e9853`.

## Research decision

Freeze zero rules, run no portfolio replay, keep 2021 and 2022–2024 closed, and do not reparameterize V31. The next experiment should use a genuinely different causal mother mechanism rather than another rendering of static price shape or an already-consumed post-entry acceptance/exit idea.
