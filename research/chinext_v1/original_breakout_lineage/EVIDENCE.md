# Original-breakout lineage evidence ledger

## E-OBL-001 — canonical event code reconciliation

- Canonical strategy SHA-256:
  `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`.
- Canonical replay SHA-256:
  `9993b4ab03a437007eb056e530f786bff2e0fc7f90276aaac9db42cfced30797`.
- `strict_breakout` requires `close_t > max(close[t-60:t-1])`.
- FULL40 and MINVOL exclude signal session; own MA and RS include the completed
  signal close.
- Signal-session breakout volume is `SHADOW`, not a membership gate.
- The signal is formed after the completed close and a fill requires a later
  executable open.

Status: `AUDIT_EVIDENCE_ACCEPTED_PENDING_PROGRAM_CHECKPOINT`.

## E-OBL-002 — data feasibility

- CY-006 daily inventory SHA-256:
  `de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2`.
- QD-004 minute inventory SHA-256:
  `767298a88618f30d4cc6d5db8a7f609670f88ba32987de6a32994844ad75746c`.
- CY-008 minute inventory SHA-256:
  `5903149da5d8afe37fa18719d17e8a5726856d11e8441d25d51217b05d6adf9f`.
- CY-008 cross-year audit SHA-256:
  `fefac612c3ad7467a87fad3c01b8fccce9b1dd6d5269d74c109d037d79f59d5d`.
- Registered evidence supports raw 1-minute OHLCV/amount, deterministic 5-minute
  aggregation, and VWAP reconstruction, but not order queues, ticks, bid/ask, or
  participant identity.

Status: `AUDIT_EVIDENCE_ACCEPTED_PENDING_FRESH_FEATURE_MATERIALIZATION`.
