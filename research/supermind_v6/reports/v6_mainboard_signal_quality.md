# SuperMind V6 on Shanghai/Shenzhen main-board stocks - exploratory signal quality

Window: 2025-08-28..2026-08-28 (243 sessions)
Universe: 3191 current-listed SH/SZ main-board stocks (NON-PIT survivor universe)

## Result

- Event counts: `{"BUY_FILLED": 64, "BUY_SIGNAL": 64, "REBALANCE_FILLED": 78, "SELL_FILLED": 64, "TAIL_SELL_SIGNAL": 64}`
- Unique bought symbols: 63
- Critical bars: 61 exact-1m final candidates; 5m fallback=['600810.SH', '600847.SH']
- Completed holding P&L: n=64, mean=1.87%, median=-0.96%, win=35.9%, p10=-8.39%, p90=10.79%
- Forward 5 sessions: n=59, mean=-1.37%, median=-2.20%, win=35.6%, p10=-8.31%, p90=4.92%
- Forward 10 sessions: n=59, mean=0.07%, median=-0.90%, win=44.1%, p10=-6.62%, p90=7.31%
- Forward 20 sessions: n=54, mean=-0.17%, median=-2.29%, win=37.0%, p10=-12.57%, p90=8.14%
- Forward 60 sessions: n=53, mean=-0.81%, median=-2.83%, win=43.4%, p10=-21.61%, p90=20.74%
- 20-session MFE: n=59, mean=10.54%, median=5.47%, win=84.7%, p10=-1.18%, p90=23.64%
- 20-session MAE: n=59, mean=-8.47%, median=-7.13%, win=3.4%, p10=-16.83%, p90=-1.77%

## Interpretation boundary

- current-survivor universe is not historical point-in-time and has survivorship bias
- stock limit-up/down, lot size, fees, slippage, partial fills, and cash are not simulated
- QMT front adjustment is not proven equivalent to SuperMind fq=pre
- order_target return semantics are simplified to full fill or fail-closed no-fill
- 600810.SH, 600847.SH exact 1m history was unavailable; their open/final-close references use QMT 5m bars and 14:57 uses the 15:00 5m-bar open as an approximation

This experiment does not modify the frozen strategy. It replaces only the static ETF pool after init inside a research sandbox.
