# WORKER-MINUTE-001 handoff

## Director decision requested

Approve or reject the proposed `session_ledger` + lossless `array241`
`session_primitives` schema. This worker recommends approval for a separately
frozen single-writer build, but did not publish a cache.

## What is ready

- Physical layout and source-role audit for QD-004/CY-006/CY-008.
- Exact PIT/session/claim boundaries.
- Deterministic 128-session tiny benchmark on frozen 2020-02-03.
- Partition, size, build-time budget, raw-rows-avoided, reuse-family, resource,
  and atomic-publication plan.
- Focused benchmark code and tests confined to this packet.

## Important boundaries

- Complete primitives are available at 15:30 only.
- Position 0 is the separate 09:30 auction row; lunch is absent.
- Arrays are raw/unadjusted doubles. Never compare them across dates without a
  separately validated causal action coordinate.
- The all-key ledger is mandatory; a primitive miss cannot be interpreted.
- No cache consumer may infer order flow, participant identity, alpha, support,
  breakout acceptance, or strategy usefulness from this infrastructure result.
- Do not run a full build concurrently with another QD-004 scanner. Current
  host swap was already 2.39 GiB used at inspection.

## Proposed next build packet

Freeze a Director-owned cache build spec containing exact source/code hashes,
the two-table schema, pre-2024 scope, `year/month` layout, a one-writer/one-thread
resource contract, deterministic tiny and one-month challenges, all validity
and anti-time-travel gates, and atomic staging/manifest publication. The build
worker should write only to a unique staging directory and return a packet for
independent QA before the Director changes any current pointer.

## Material result

For 2018--2023, lossless primitive arrays project to 7.51 GiB plus a small
ledger/manifest overhead (8.5 GiB budget) and can avoid 1,486,577,999 raw row
visits for each reuse family. The accepted prior full-scale adapter gives a
10--15 minute conservative planning interval for a single-writer build; this
interval has not been measured end to end.
