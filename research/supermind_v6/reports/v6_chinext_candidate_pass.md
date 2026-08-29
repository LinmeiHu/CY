# SuperMind V6 on ChiNext stocks - exploratory signal quality

Window: 2025-08-28..2026-08-28 (243 sessions)
Universe: 1398 current-listed 300/301 ChiNext stocks (NON-PIT survivor universe)

## Result

- Event counts: `{"BUY_FILLED": 37, "BUY_SIGNAL": 37, "REBALANCE_FILLED": 49, "SELL_FILLED": 37, "TAIL_SELL_SIGNAL": 37}`
- Unique bought symbols: 37
- Completed holding P&L: n=37, mean=2.87%, median=1.46%, win=54.1%, p10=-9.87%, p90=17.53%
- Forward 5 sessions: n=37, mean=-2.09%, median=-2.13%, win=32.4%, p10=-8.56%, p90=4.87%
- Forward 10 sessions: n=37, mean=2.62%, median=0.98%, win=56.8%, p10=-6.66%, p90=14.81%
- Forward 20 sessions: n=36, mean=1.31%, median=-0.49%, win=50.0%, p10=-14.02%, p90=20.72%
- Forward 60 sessions: n=36, mean=3.51%, median=-1.90%, win=38.9%, p10=-14.11%, p90=31.55%
- 20-session MFE: n=37, mean=13.36%, median=9.29%, win=91.9%, p10=0.28%, p90=32.06%
- 20-session MAE: n=37, mean=-8.19%, median=-6.71%, win=5.4%, p10=-16.00%, p90=-1.44%

## Interpretation boundary

- current-survivor universe is not historical point-in-time and has survivorship bias
- stock limit-up/down, lot size, fees, slippage, partial fills, and cash are not simulated
- QMT front adjustment is not proven equivalent to SuperMind fq=pre
- order_target return semantics are simplified to full fill or fail-closed no-fill

This experiment does not modify the frozen strategy. It replaces only the static ETF pool after init inside a research sandbox.
