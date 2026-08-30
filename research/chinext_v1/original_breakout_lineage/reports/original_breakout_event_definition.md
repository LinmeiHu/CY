# Authoritative original V1 breakout-event definition

## Event timestamp and reference

For a stock `s` and completed exchange session `t`:

```text
breakout_reference_t = max(close[t-60], ..., close[t-1])
original_breakout_t  = close[t] > breakout_reference_t
decision_at          = t 15:30:00 Asia/Shanghai (conservative completed-bar availability)
earliest_action      = next executable session open after t
```

The reference uses closes, not highs, visual pivots, intraday extremes, or a
future-selected resistance level. Equality does not pass.

## Complete canonical admission context

The original-breakout predicate is necessary but not sufficient for an accepted
V1 entry intent. Canonical admission also requires:

1. daily basic eligibility, at least 180 completed valid observations, contiguous
   history, and mean prior/current 20-session CNY amount at least 100m;
2. hard-valid, non-ST, tradable signal-session state and valid action lineage;
3. `close_t > MA20_t`;
4. FULL40 on prior observations only: 40-close width <=20%, prior MA dispersion
   <=8%, direction efficiency <=0.45, and vol10/vol60 <=0.85;
5. MINVOL on t-30..t-1 only: minimum-volume price location <=0.50 and minimum
   volume / mean volume <=0.70;
6. cross-sectional 20/60/120 RS ranks over the complete basic-eligible set with
   weights 20%/50%/30%;
7. exact 399102 market entry permission (`close > MA20`);
8. vacancy/capacity under ten 10% slots, no rank replacement, and no sticky exit
   conflict.

Signal-session volume divided by prior-20 mean is recorded at threshold 1.20 in
`SHADOW` mode. It does not change membership.

## Execution semantics

Signal formation occurs only after the official completed close. Pending orders
carry the original signal date. A buy requires `execution_date > signal_date`, a
finite positive open, `hard_valid=true`, tradable state, and no open-limit block.
Same-bar or same-session fills are forbidden.

## Research timing map

| Information | AVAILABLE_AT_TIMESTAMP | POTENTIAL_ACTION_TIMESTAMP |
|---|---|---|
| Prior daily formation through t-1 | before t open, subject to recorded daily availability | t open or later, but canonical V1 still waits for completed t signal |
| Completed signal-session daily bar and canonical breakout predicate | t 15:30 Asia/Shanghai | next executable open after t |
| Signal-session full one-minute path/VWAP | t 15:30 Asia/Shanghai | next executable open after t |
| Entry-execution-session observations after the open | their completed bar timestamps | only after each bar; never retroactive to the open fill |

## Bound code identities

- `strategy/chinext_v1_exploratory.py`:
  `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- `scripts/run_chinext_v1_smoke.py`:
  `9993b4ab03a437007eb056e530f786bff2e0fc7f90276aaac9db42cfced30797`
- `scripts/chinext_v1_ablation.py`:
  `12fe1b6b9f4577540079f602bc7df73d88a435a9d1f1fbe336d2b18a3d8e1fda`

This definition is frozen independently of subsequent outcomes and cannot be
redefined to improve lineage separation.
