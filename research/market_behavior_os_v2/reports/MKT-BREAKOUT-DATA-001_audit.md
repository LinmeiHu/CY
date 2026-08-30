# MKT-BREAKOUT-DATA-001 prior-high event-support audit

## Result

- Status: `COMPLETE_EVENT_SUPPORT_PASS`
- Immutable sequences/cohort rows/unique sessions: 1,920/9,600/9,575.
- Primary L20 continuous crossings: 964; unique physical sessions: 957.
- Closing states above/equal/below: 464/1/499.
- Crossings with 60 remaining bars: 899; loss-and-reacquisition sessions: 641.
- Session-domain primary/neighbor pass: True/True; conditional reacquisition pass: True.
- Auction-only L20 crossings: 4; up/down-limit contacts: 107/45.
- Five independently selected scalar cases reproduce the exact prior-high, first crossing, closing state, and censoring count.
- This count-only experiment computes no continuation, depth, dwell, VWAP, trajectory, outcome, prediction, habitat, or strategy estimate.

## Reproducibility

- Spec SHA-256: `db3d0cfa1ea7c6d8ca89fe553c0b4803ac36080b02a57160c41e9391b5040b79`
- Runner SHA-256: `097b521928d81342030ab68dda56eda4d6aa3e1d2ea57028c77b5c38c5ce5bfd`
- Coordinate/event audit SHA-256: `1eaeed29c1c45fae7f0090eee3720d39f20928cc3930bf7bfa95e7ac49b5d897`
- Count audit SHA-256: `59e74964172b8aafdae09d54f8d9536dd372dec1b6a8c61cd9cc97df51a1f561`
