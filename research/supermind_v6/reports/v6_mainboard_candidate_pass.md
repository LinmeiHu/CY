# SuperMind V6 on Shanghai/Shenzhen main-board stocks - exploratory signal quality

Window: 2025-08-28..2026-08-28 (243 sessions)
Universe: 3191 current-listed SH/SZ main-board stocks (NON-PIT survivor universe)

## Result

- Event counts: `{"BUY_FILLED": 64, "BUY_SIGNAL": 64, "REBALANCE_FILLED": 76, "SELL_FILLED": 64, "TAIL_SELL_SIGNAL": 64}`
- Unique bought symbols: 63
- Completed holding P&L: n=64, mean=1.90%, median=-0.96%, win=35.9%, p10=-8.39%, p90=10.79%
- Forward 5 sessions: n=59, mean=-1.38%, median=-2.20%, win=35.6%, p10=-8.31%, p90=4.92%
- Forward 10 sessions: n=59, mean=-0.02%, median=-1.43%, win=44.1%, p10=-6.62%, p90=7.31%
- Forward 20 sessions: n=54, mean=-0.27%, median=-2.55%, win=35.2%, p10=-12.57%, p90=8.14%
- Forward 60 sessions: n=53, mean=-0.33%, median=-2.68%, win=45.3%, p10=-20.87%, p90=20.74%
- 20-session MFE: n=59, mean=10.10%, median=5.11%, win=84.7%, p10=-1.18%, p90=21.97%
- 20-session MAE: n=59, mean=-8.52%, median=-7.21%, win=3.4%, p10=-16.83%, p90=-1.77%

## Interpretation boundary

- current-survivor universe is not historical point-in-time and has survivorship bias
- stock limit-up/down, lot size, fees, slippage, partial fills, and cash are not simulated
- QMT front adjustment is not proven equivalent to SuperMind fq=pre
- order_target return semantics are simplified to full fill or fail-closed no-fill

This experiment does not modify the frozen strategy. It replaces only the static ETF pool after init inside a research sandbox.
