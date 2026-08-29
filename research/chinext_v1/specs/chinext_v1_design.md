# ChinNext V1 Phase 0 design

## 1. Scope and frozen reference

This is a design document, not a strategy implementation. It adapts the structural
ideas of the frozen ETF V6 to ChiNext A shares without treating the change as an ETF
pool substitution.

Frozen reference:

```text
research/supermind_v6/strategy/SuperMind_V6_CSI1000_MA15_ENTRY_HS300_MA20_EXIT_MINVOLLOC30_CAP50_SET_TAIL_SELL_OPEN_BUY_COMMENTS_FIXED.py
SHA256 7fa9d715bdf4c352526d556132f8ec8502e9f355876100f357c8bdc5fdc91f33
2677 lines; Git tracked; unmodified
```

The original V6 `asset_balanced` ranking source is unavailable. The frozen file
actually implements a transparent V5-style 20/60/120 cross-sectional relative-
strength fallback. ChinNext V1 inherits the transparent factor family, not an
imagined `asset_balanced` implementation.

## 2. Exact source V6 structure

The following is the reference behavior that Phase 1 must be able to reproduce in
small unit fixtures before changing it:

- CSI1000 `000852.SH` close above MA15 controls **NEW ENTRY only**. Gate-off does
  not liquidate existing holdings.
- HS300 ETF `510300.SH` close versus MA20 supplies portfolio-level exit logic.
  Frozen mode `BOTH` combines a weekly unbuffered exit and daily 2% emergency exit.
- B60 is `C_t > max(C_{t-60}, ..., C_{t-1})`.
- Candidate ETF close must be strictly above its own MA20 including `C_t`.
- FULL40 excludes signal day for its box, MA-dispersion, direction-efficiency, and
  volatility-ratio inputs. Frozen thresholds are 12.5%, 5%, 0.40, and 0.90.
- MINVOLLOC_L30_C0.50 uses `t-30..t-1`; signal-day volume is excluded. The source
  calculates `min_volume_ratio` for diagnostics but does not use it as a gate.
- Cross-sectional RS uses 20/60/120-day returns, percentile ranks over the full
  eligible cross-section, and an equal-weight mean. It is the V5 fallback.
- Maximum holdings are five. CAP50_SET targets `min(50%, 1/N)` per desired member.
- SET_CHANGE_ONLY resizes all desired members only when membership changes or the
  last processed membership differs; ordinary price drift does not rebalance.
- A full portfolio does not replace a holding merely because a new candidate ranks
  higher (`NO_REPLACEMENT`).
- Individual exit is two consecutive closes below MA40 (`MA40 x 2`).
- At 14:57 the strategy forms sell-only signals from a pseudo-close, then submits
  queued sells at the 15:00 callback under `set_execution('close')`.
- Official-close entry targets and exit fallbacks execute at the next opening
  auction, with a 09:30 callback fallback.
- `forced_sells` and `force_exit_all` are sticky until actual positions disappear.
- Official-close fallback catches thresholds crossed after the 14:57 snapshot and
  retries incomplete exits at the next open.

Source evidence is concentrated at lines 31-51, 74-293, 503-594, 690-847,
858-1415, 1451-1816, 1825-2359, and 2399-2669 of the frozen file.

## 3. Configuration wiring audit

Three source context fields are descriptive rather than operative:

| Context field | Declared | Actual implementation | Phase 1 requirement |
|---|---:|---|---|
| `breakout_days` | 60 | `entry_signal()` hardcodes `[-61:-1]` | Wire the value into one tested window; fail on invalid values. |
| `box_days` | 40 | `full40_signal()` hardcodes `[-41:-1]` and several 40 constants | Wire the value consistently into box and direction-efficiency windows. |
| `exit_confirm` | 2 | `own_exit_signal()` explicitly evaluates exactly two observations | Wire confirmation count or name the rule as a fixed two-day rule; do not expose a false parameter. |

This audit does not authorize modification of the frozen source.

## 4. Proposed ChiNext V1 semantics

### 4.1 Universe

For each decision date `t`, construct the eligible universe only from records whose
`available_at <= decision_at` and whose required lineage is known:

1. ChiNext A shares present in a date-effective, point-in-time security master.
2. At least 180 exchange trading sessions since listing. Calendar-day age is not a
   substitute.
3. Exclude ST, `*ST`, and every risk-warning state effective on `t`.
4. Exclude suspended or otherwise non-tradable shares for the intended order side
   and execution window.
5. Require prior 20 completed trading-day amounts and mean amount at least CNY
   100,000,000. The signal day may be included only if the decision occurs after its
   official close and the order cannot fill on that day.
6. Unknown listing identity, risk status, trading status, limit rule, or lineage
   fails closed.

The local `chinext_current_survivor_universe.json` is explicitly
`NON_PIT_CURRENT_SURVIVOR`; it is not an input to this universe. QD-007 is currently
`DISCOVERY_ONLY` and forbidden for universe construction. CY-006 contains daily
PIT-B rows with trading state, ST flag, limits, actions, lineage, and `hard_valid`,
but its schema has no `list_date`; it therefore does not by itself prove the 180-
session listing-age gate or a complete date-effective ChiNext identity master.

### 4.2 Market regime

Both roles use `399102.SZ`, but they remain separate configuration fields so later
research cannot accidentally couple entry and exit semantics:

```text
market_entry_anchor = 399102.SZ
market_exit_anchor  = 399102.SZ
market_ma_days      = 20
```

- Entry permission: official `Close_t > MA20_t`; this only permits new holdings.
- Normal risk-off candidate: two consecutive official closes below their respective
  MA20 values.
- Emergency candidate: official close below `MA20_t * 0.96`.
- Missing anchor data or unknown availability blocks new risk. Whether it also
  forces liquidation must be specified only after a SuperMind/data failure probe;
  Phase 0 does not invent that behavior.

No registered local evidence for `399102.SZ` was found; the anchor's exact symbol,
history coverage, field semantics, and SuperMind availability remain a Phase 1
data gate.

### 4.3 Portfolio

```text
max_holdings = 10
position_cap = 0.10
target_weight = min(0.10, 1 / N)
rebalance_policy = SET_CHANGE_ONLY
```

When `N < 10`, the cap deliberately leaves cash. All desired members are resized
only after a membership change; price drift alone does not trigger daily orders.
Order/fill reconciliation must compare actual shares and weights, not only member
names, because the frozen membership-only ledger can miss partial fills.

### 4.4 Entry structure

All entry conditions use the official completed close of signal day `t` and can
first submit a buy at a causally valid `t+1` execution window:

- B60: signal close strictly above the preceding 60 completed closes.
- Own trend: `Close_t > MA20_t`.
- FULL40 initial candidate, using inputs strictly before the signal day:
  - `box_days = 40`
  - `box_width_max = 0.20`
  - `ma_dispersion_max = 0.08`
  - `direction_efficiency_max = 0.45`
  - `vol10 / vol60 <= 0.85`
- MINVOL:
  - prior 30-day window `t-30..t-1`
  - signal-day volume excluded
  - minimum-volume day's price location `<= 0.50`
  - `minimum_volume_ratio = min(volume[t-30:t-1]) / mean(volume[t-30:t-1])`
  - candidate threshold `minimum_volume_ratio <= 0.70`
- Breakout volume:
  - `breakout_volume_ratio = volume_t / mean(volume[t-20:t-1])`
  - candidate threshold `>= 1.20`
  - modes `OFF`, `SHADOW`, and `HARD`
  - first research round recommendation: `SHADOW`; record values and counterfactual
    pass/fail, but do not alter membership.

The signal-day volume in breakout volume is permitted only after the official close
is complete and cannot be paired with a same-day fill.

### 4.5 Relative strength

For every fully eligible PIT-universe member with sufficient history:

```text
mom20  = C_t / C_(t-20)  - 1
mom60  = C_t / C_(t-60)  - 1
mom120 = C_t / C_(t-120) - 1
r20, r60, r120 = cross-sectional percentile ranks
rs_score = 0.20*r20 + 0.50*r60 + 0.30*r120
```

Ranks are formed over the full eligible cross-section, not only breakout names.
Ties must have a deterministic rule frozen before any performance experiment.

### 4.6 Replacement

Two policy arms are designed, but neither is implemented in Phase 0:

1. `NO_REPLACEMENT`: frozen V6 baseline; fill vacancies only.
2. `WEEKLY_HYSTERESIS`: at one frozen weekly checkpoint, replace at most one
   holding if its composite RS percentile is below 0.50, a new candidate's
   composite RS percentile is above 0.90, and the new name passes the complete
   entry and execution gates. If several pairs qualify, use deterministic worst-
   held/best-new ordering.

The weekly checkpoint, holiday handling, and tie behavior must be frozen in a unit
test before implementation. They are not inferred from V6's market-exit week logic.

### 4.7 Individual exits

Phase 0 defines three research arms without implementing them:

- Baseline: two consecutive closes below MA40.
- Candidate: two consecutive closes below MA30.
- Candidate: ATR20 trailing exit using
  `highest_official_close_since_entry - 3 * ATR20`.

For the ATR arm, true-range price basis, corporate-action rebasing, entry-day
inclusion, confirmation count, and gap/open execution must be fixed only after the
adjustment and execution contracts are proven. No current default is silently
assumed.

## 5. Execution and trading-system gates

The signal engine and execution simulator must be separate. A desired order is not
a fill. Every order must preserve side-specific eligibility, sellable quantity,
price limits, auction availability, and partial-fill state.

### 5.1 Required ledger behavior

- A buy formed from day `t` official-close inputs cannot fill during day `t`.
- A share bought on day `t` must not be considered sellable at the `t` 14:57 tail.
- Sellable inventory is tracked separately from total inventory; unknown T+1 state
  blocks the sell rather than fabricating availability.
- Suspension, absent execution bar, upper-limit buy risk, lower-limit sell risk,
  partial fills, and rejected orders remain explicit states and are retried only
  under a frozen policy.
- `forced_sells` / `force_exit_all` remain sticky until actual positions, not target
  membership, prove completion.
- Corporate actions must rebase price history, entry reference, highest-close state,
  ATR state, and share/sellable ledgers consistently and conservatively.

### 5.2 SuperMind items not proven locally

The frozen source and the existing V6 audit support the documented engine claim
that `set_execution('close')` matches a minute-backtest order at the current bar's
close. They do **not** prove real executability. The following remain unresolved
until a minimal SuperMind probe records callbacks, order IDs, trades, prices,
quantities, and statuses:

- exact 14:57 bar interval and whether `bar.open` is visible at callback time;
- 14:57 fallback `history('1m').close` current-bar causality;
- 14:57-15:00 closing-auction order-entry behavior and cutoff;
- whether a 15:00 callback can know the official close and still receive that same
  close (an optimistic same-bar assumption in the frozen backtest);
- `open_auction()` callback availability, auction matching price, and the 09:30
  fallback price under global close execution;
- suspension, upper/lower limit, partial fill, cancellation, and retry events;
- T+1 sellable-quantity exposure and enforcement;
- special no-limit/changed-limit stages for newly listed ChiNext shares;
- SuperMind corporate-action and `fq='pre'` equivalence for prices, volume, orders,
  positions, and trailing state.

Until those probes pass, the conservative research baseline is official-close
signal followed by next-session execution with explicit no-fill states. Tail-close
fills may be logged only as an unresolved/shadow execution arm.

## 6. Data and causality contract

Every row used for universe, feature, signal, or execution must carry or inherit:

```text
trade_date / effective_date
decision_at
available_at
source
snapshot_id
hard_valid (where governed by the registry)
```

Required facts include date-effective security identity, listing/delisting date,
risk-warning state, trading status, raw and adjusted OHLCV/amount, price-limit rule
and prices, exchange calendar, corporate actions, and execution-window observations.
Unknown required lineage or rule scope fails closed. Current security names/lists,
future revised states, forward-filled bars, and unregistered substitute sources are
forbidden.

CY-006 can be evaluated as a candidate daily fact source only within its registered
2018-01-01..2026-08-12 PIT-B scope, with `available_at <= decision_at` and
`hard_valid=true`. It is not authorization to change CY production code, and it
does not close the missing listing-age/PIT-universe or SuperMind-equivalence gates.

## 7. Recommended Phase 1 scope

Phase 1 should remain evidence-first and narrowly bounded:

1. Materialize and register an immutable, date-effective ChiNext security master
   with listing/delisting, board identity, ST/risk-warning, new-listing phase,
   availability, snapshot, and revision evidence.
2. Validate `399102.SZ` identity, daily coverage, adjustment, and availability.
3. Build small deterministic fixtures for the 180-session gate, amount gate, B60,
   FULL40, MINVOL ratio, breakout-volume shadow field, weighted RS, cash retention,
   SET_CHANGE_ONLY, and T+1 sellable ledger.
4. Run minimal SuperMind probes for daily/minute timestamp boundaries, open and
   closing auctions, close execution, limits, suspension, partial fills, and
   corporate actions. Freeze raw logs and engine configuration.
5. Only after those gates pass, implement a minimal `NO_REPLACEMENT` baseline and
   compare signal membership on a tiny frozen symbol/date sample.

Explicitly out of scope: parameter optimization, complete strategy variants,
full-market backtests, production-code changes, and performance claims.
