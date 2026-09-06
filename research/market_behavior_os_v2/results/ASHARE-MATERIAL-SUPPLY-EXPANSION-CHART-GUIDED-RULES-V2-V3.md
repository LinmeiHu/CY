# Material supply expansion: chart-guided rules V2/V3

Research status: consumed development research; exact family closed. Later-period validation was not opened.

## Visual review coverage

- Mother event: circulating shares increase by at least 50% between consecutive sessions, with the event level known before any subsequent behavior is evaluated.
- Development years: 2018-2020.
- Mother events reviewed: 1,068.
- Parent-rule trades reviewed: 525.
- Individual parent-trade charts: 525.
- Chronological contact sheets reviewed: 59/59.
- The frozen visual-review record is `ASHARE-MATERIAL-SUPPLY-EXPANSION-TRUE-VS-FALSE-REASSERTION-ANATOMY-V1-REVIEW.md`.

## Patterns visible in the charts

1. A single close above the event-day high was commonly a temporary reclaim rather than durable demand acceptance.
2. Durable winners often kept the event-day high accepted after entry; many failures quickly lost it.
3. Waiting for two additional closes above the event high removed some false reclaims but did not repair the long economics.
4. Waiting for the event-day low to fail recognized losses too late.
5. Two consecutive closes below the event-day high were useful as an earlier failure diagnosis, but this was risk information rather than entry alpha.

Direct counterexamples were present for trigger margin, stock-industry edge, trigger timing, turnover, pretrend, and static BULL/BEAR state. Those variables were therefore not promoted as chart rules.

## V2: three-close acceptance entry

Frozen rule: retain the exact parent trigger, require the next two market sessions to have valid same-lineage closes above the event-day high, then enter at the next legal open. Preserve the original event-low/H120 exit and 40 bps round-trip cost.

| Year | Completed | Mean net | Median net | Severe loss |
|---|---:|---:|---:|---:|
| 2018 | 116 | -7.68% | -11.59% | 60.34% |
| 2019 | 136 | -3.29% | -10.73% | 55.15% |
| 2020 | 157 | +4.26% | -7.94% | 42.68% |

Pooled: 409 trades, -1.64% mean net, -10.28% median net. The delayed-entry rule failed the complete development gate and is closed without threshold rescue.

Result SHA-256: `a043e91cd6d19324106bba54f6f5e0fc07eb259ff92301fdf8707c278df87183`.

## V3: event-high failure exit

Frozen rule: retain all 525 parent entries. After entry, two consecutive valid closes below the event-day high trigger an exit at the next legal sellable open; otherwise exit at H120. Preserve 40 bps round-trip cost.

| Year | Completed | Mean net | Median net | Severe loss |
|---|---:|---:|---:|---:|
| 2018 | 161 | -5.06% | -6.18% | 27.95% |
| 2019 | 163 | -2.87% | -5.42% | 28.22% |
| 2020 | 201 | +1.92% | -4.21% | 24.88% |

Pooled: 525 trades, -1.71% mean net, -5.41% median net, 26.86% severe-loss incidence. Early failures were 435 trades with -8.48% mean; the 90 H120 survivors averaged +31.03%.

The exit rule materially reduced severe losses versus the parent, but annual means and medians did not establish a profitable long strategy. It is classified as defensive exit information inside a non-alpha mother family, not a promotable strategy.

Result SHA-256: `9f5e9208b14d29dbae91c475dabadd61dc60c7081e2b94bd8cab7a5f53e5f4b0`.

## Decision

Close the exact material-supply-expansion family. Do not test nearby share-expansion thresholds, confirmation-day counts, or event-high exit counts. The chart work found a real failure-recognition pattern, but the mother event did not contain sufficient positive long opportunity.
