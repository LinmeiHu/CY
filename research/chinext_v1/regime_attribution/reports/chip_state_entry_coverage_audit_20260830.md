# CY-011 chip-state entry coverage audit

This audit is outcome-blind except for endpoint counts needed to establish
estimability. It computes no chip/outcome association and does not access or
materialize rows from the locked 2024-2026 validation range.

## Governance and identity

- Registry asset: `CY-011`, `RESEARCH_CONDITIONAL`, PIT grade B.
- Authorized discovery range: 2020-01-01 through 2023-12-31.
- Locked validation range: 2024-01-01 through 2026-08-12; unopened.
- Registry SHA-256: `1161ab5e1e509f117833a69e43aa275b4b3e4379a39471fa5ea1701e3f69bde5`.
- Inventory SHA-256: `edde3818f2989043de756e95792737ecacec2ce91464aaf8846507fdc875383e`.
- Build-manifest SHA-256: `0f29784c2f28414781e735c44f4cb6d39554349360fc902626951ef08a161053`.
- Audit SHA-256: `e9672bff295e7a464259cee99ac4efaec25f04e9a57aa1df55b9de9bb002ba05`.
- All 81 inventory files, totaling 5,778,765,864 bytes, match registered sizes
  and SHA-256 identities. The registered audit passes mass conservation, PIT and
  snapshot lineage, semantic intervals/migration, and peak fields.

The physical asset is symbol-bucketed rather than year-partitioned. The audit
query applied an exact 2020-2023 date predicate and materialized no row after
2023; Parquet footer metadata necessarily spans the immutable files. No locked
validation values or outcomes were queried.

## Entry-date coverage

The accepted V1 table contains 220 signal-date entries in the authorized range:
2020 65, 2021 61, 2022 37, and 2023 57. All 220 distinct symbol/date keys join
one-to-one to CY-011. The returned range is 2020-02-18 through 2023-11-23.

Every row has:

- `available_at` exactly signal-date 15:30 Asia/Shanghai;
- valid daily and minute inputs, valid state chain, strict sample, research
  sample, and daily research sample;
- no minute waiver, suspension bridge, or invalid reason;
- semantic state version `chip-state-features-semantic-v3`;
- complete I90/I70 width and retention, migration, average-cost, profit/overhang,
  and main-peak fields.

Maximum observed chip-mass error is `1.89e-12`; minimum state quality is `0.75`.
There are no duplicate keys or missing feature rows. Signal-close information is
available only for the next valid session or later; same-bar use is forbidden.

## Estimability without association

The fixed 220-entry discovery sample has complete MFE and fixed controls, 38
MFE>=20% opportunities, 125 false breakouts, 23 severe losses, 172 securities,
and 54 industries. The two temporal blocks contain 126 and 94 entries. The 2022
binary opportunity endpoint has only one event, so MFE should remain primary and
year-specific binary estimates must not become required gates.

## Audit decision

`PASS_MINIMUM_SUFFICIENT_DISCOVERY_ONLY`.

One small mechanistic family is supportable without screening the semantic table:
a concentrated retained cost base plus upward marginal cost migration. Any test
must freeze one composite before joining outcomes, use MFE as primary, control
frozen H-004 breadth and daily state, bind all CY-011 identities, and leave
2024-2026 locked. No chip threshold, signal, filter, backtest, or strategy action
is authorized.
