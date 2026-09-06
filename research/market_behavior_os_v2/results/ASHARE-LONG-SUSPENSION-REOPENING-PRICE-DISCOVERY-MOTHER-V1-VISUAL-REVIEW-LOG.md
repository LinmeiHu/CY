# ASHARE Long-Suspension Reopening Price Discovery — Visual Review Log

Status: COMPLETE; no rule outcome aggregation was opened before completion.

## Completed review

- Mother events: 4,459, signal years 2015–2020.
- Chronological sheets: 496/496 reviewed, covering every event once.
- Outcome-sorted second pass: PROFIT_GE_4PCT 139/139, PROFIT_0_TO_4PCT 39/39, LOSS_0_TO_10PCT 111/111, SEVERE_LOSS 159/159, and NO_COMPLETED_TRADE 49/49 reviewed.
- Total review sheets inspected: 993. Every one of the 4,459 mother events was reviewed chronologically and then reviewed again in its complete outcome group.

## Findings closed against reuse

The following do not stably distinguish profitable from unprofitable reopenings and must not be reintroduced as rule candidates in this cycle:

1. Suspension duration by itself.
2. Reopening gap magnitude or sign by itself.
3. Reopening-session return or close location by itself.
4. Immediate recovery of the pre-suspension close.
5. A simple causal BULL/BEAR/TRANSITION label.
6. A blanket exclusion of BEAR observations.

## Surviving mechanisms

### 1. Post-reopening price acceptance

The reopening print is an information-release auction, not a stable entry coordinate. Profitable cases commonly need several sessions to complete price discovery. The most inclusive pre-known anchor is the first legally buyable open, not the pre-suspension close. A usable rule should observe approximately one trading week and require acceptance around that anchor rather than require an uninterrupted hold.

### 2. Confirmed failure after apparent acceptance

Many profitable cases later fail, while severe losers commonly lose the post-reopening anchor and stay below it. One close below the anchor is too sensitive because profitable cases often make a temporary breach. Across the complete severe-loss contrast, two consecutive closes below the first legally buyable open is the simplest recurring confirmation of failed price discovery. The exit can act only at the next legal, non-limit-down open; overnight gaps, limit-down cascades, and renewed suspensions remain uncontrollable execution risk.

### 3. Causal market direction x speed

The same coarse BULL/BEAR state contains both winners and losers. The candidate causal state map uses only information known at the observation close and distinguishes:

- UP_ACCELERATING
- UP_DECELERATING
- DOWN_RECOVERING
- DOWN_DETERIORATING

The intended raw inputs are frozen-horizon market median return measures (20 and 60 sessions); no future year label or later market outcome may enter the state.

### 4. Stock-relative acceptance

Absolute first-week strength alone is insufficient. The candidate should demonstrate that the stock is completing price discovery better than the contemporaneous broad cross-section. The exact minimal causal representation remains to be frozen after loss-group comparison.

### 5. H20 label versus later path

The 0–4% H20 bucket contains both later multi-month winners and later persistent failures. This confirms that a fixed H20 label is not a complete description of the path, but it does not authorize a holding-period search. The frozen H20 evaluation remains unchanged; a failure exit may be added only if the loss contrast supports one deterministic definition.

Profitable cases also include temporary anchor breaches. Therefore an uninterrupted-hold or "never below anchor" rule is closed against reuse.

### Completed ordinary-loss contrast

The 0% to -10% H20 group confirms that later six-month chart success cannot retroactively validate a losing H20 entry: many ordinary H20 losers later became large winners. Within the frozen horizon, the recurring failure is lack of a sustained raised trading range above the first legally buyable open—often a spike-and-fade or brief stabilization followed by failure in weeks two to four.

The contrast narrows the candidate architecture to one entry confirmation plus one confirmed-failure exit:

- the observation-week close should finish above the objective anchor and outperform the contemporaneous market path;
- observation-week rebound from its low is not sufficient by itself;
- one close below the anchor appears too sensitive because profitable cases also temporarily breach it;
- any failure exit should require confirmation, but its exact frozen definition remains pending the severe-loss contrast.

Suspension length, gap sign, volume appearance, and the coarse BULL/BEAR label remain ruled out. The evidence does not justify a score or an additional technical-pattern library.

### Completed severe-loss contrast

The 1,431 severe-loss cases overwhelmingly show a one-way downward price-discovery process after reopening. Some fail immediately; others remain above the anchor for one week and fail in weeks two to four. This is why five-session acceptance can improve entry quality but cannot replace a failure exit.

The severe-loss evidence is stable across the 2018 bear cluster and the later 2019–2020 BULL/TRANSITION cases. A favorable broad market does not rescue an individual reopening whose new price is rejected. Conversely, raw BULL/BEAR labels do not separate winners from losers. The stock should instead be required to outperform the contemporaneous broad cross-section during its own observation window; this is a causal relative-demand test rather than a future regime label.

The severe-loss contrast closes the following alternatives:

- pre-suspension close as a mandatory reclaim level;
- first-day gap, first-day limit state, suspension duration, or volume appearance as a rule;
- a one-close stop;
- using later six-month recovery to relabel a losing H20 trade;
- a hard coarse-market-state veto.

### Completed no-completed-trade contrast

The 435 no-completed-trade cases are primarily execution states, not a hidden profitable chart family. Most reopened in consecutive one-price limit-up states and had no legal entry inside the frozen three-session window. A smaller subset entered and then encountered another long suspension or no legal H20 exit. Subsequent visible appreciation is not an executable return and cannot justify chasing after the entry window or imputing an exit.

Accordingly, the final rules must retain fail-closed execution:

- no legal non-limit-up open within three sessions means no trade;
- no legal exit means no completed return, not a synthetic fill;
- the no-completed group may inform coverage only, never the payoff gate.

## Final visual compression

The complete 4,459-event, 993-sheet review compresses to four executable statements:

1. After a long suspension, do not chase the reopening print; require a legal non-limit-up open within three sessions and freeze that open as the price-discovery anchor.
2. Observe the next five valid traded sessions; buy only if the fifth close is at or above the anchor and the stock has outperformed the contemporaneous broad-market median over the same interval.
3. Enter no earlier than the next legal non-limit-up open after the fifth close.
4. Hold for the frozen 20-session lifecycle, but after two consecutive closes below the anchor sell at the next legal non-limit-down open; all suspension, limit, T+1, and corporate-action constraints remain binding.

Market direction is handled causally by the stock-versus-market comparison. The 20/60-session direction-x-speed phase is retained for reporting and stability anatomy, not used as a hard admission rule because the complete charts do not support one.

## Questions resolved by the contrast pass

1. Acceptance: fifth valid-trading-session close at or above the frozen first-buyable-open anchor, plus positive same-window excess over the causal broad-market median.
2. Failure: two consecutive closes below the frozen anchor; one close is rejected as too twitchy.
3. Market phase: context only. It must not become a hard filter in this experiment.

## Research discipline

- Maximum five final rules.
- Rules are frozen and hashed before any rule-filtered annual or pooled outcome aggregation.
- Initial evaluation remains 2015–2020; post-2021 signals remain closed unless the predeclared breadth and return gates pass.
- No parameter grid, no neighboring suspension threshold, no gap taxonomy, and no same-session fill.
