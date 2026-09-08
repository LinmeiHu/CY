# Test results

`20 targeted tests: PASS`; the 8 new native-account methods cover all 26 required contracts, with inherited V3 execution regressions run alongside them. BASE full-account repeat is byte-identical for NAV, trades, orders, audit, open positions and holdings.

Covered: planned risk, board lots, cash, aggregate cap and partial size, stop risk release, nonnegative risk, structural invalidation, buy-day T+1, next legal exit, gap loss, limit/suspension delay, historical entry limits, share-credit date, dividends, share effectiveness, winner transition, monotonic trail, max hold, R reconciliation, no leverage, nonnegative cash, integer shares, one physical position and determinism. P2-specific 27–32 remain not run because P2 admission is blocked.
