# ChinNext V1 — QD-001 / QD-010 Corporate-Action Adjudication

## Scope and decision

This is an outcome-blind adjudication of the remaining Phase12B3 corporate-action mismatch. It does not run replay, materialization, strategy code, or performance analysis.

Decision: `D. CONTRACT_OR_ADAPTER_ERROR_PROVEN` applies to the Phase12B3 mismatch finding itself. The recorded mismatch is stale/incorrect: the current CY-006 row contains the QD-010 event. No date tolerance, symbol exception, event-ID exception, or price-derived normalization is required.

The QD-010 source remains `BOUNDED_PIT_AUTHORIZED`; `revision_history_complete=false` is not upgraded.

## Exact event

| Field | Evidence |
|---|---|
| Symbol | `302132.SZ` in CY-006; raw QD-001 is `302132`; QD-010 normalized symbol is `302132` |
| Security name | `中航成飞` in the frozen BaoStock identity artifacts |
| Event type | `cash_dividend` |
| QD-001 source | `/Users/linmei/Downloads/workspace/quant/data/lake/stock_daily/302132.none.parquet` |
| QD-010 source | CNINFO official `p_sysapi1139`, frozen current snapshot `official_full_sh_sz_current_snapshot_20260809_v5` |
| QD-001 recorded date/boundary | Raw daily bar `trade_date=2018-05-16`; QD-001 has no corporate-action/event fields |
| QD-010 recorded dates | `announcement_date=2018-05-09`; `known_at=2018-05-10`; `record_date=2018-05-15`; `effective_date=2018-05-16`; `pay_date=2018-05-16` |
| QD-001 event fields | None; schema is raw OHLCV plus turnover-related fields |
| QD-010 event fields | `event_id=cninfo:distribution:deba827b250b20ed90d13a29e20ff7ee`, `cash_per_share_gross=0.05`, `share_multiplier=1.0`, `rights_subscription_ratio=NULL`, source lineage and revision flags |
| Original audit artifact | `chinext_v1_phase12b3_warmup_overlap.json`, referenced by `chinext_v1_phase12b3_input_activation_summary.json` |

The current CY-006 row for `302132.SZ / 2018-05-16` has `corporate_action_count=1`, the exact QD-010 event ID, `corporate_action_source=cninfo_official_api.p_sysapi1139`, `corporate_action_available_date=2018-05-10`, `cash_per_share=0.05`, and `corporate_action_valid=true`. The adjacent 2018-05-15 and 2018-05-17 rows have no action marker. The QD-001 raw bar is identical to the corresponding CY-006 OHLCV row. A direct current-source join over all 635 QD-010 GEM events in the 2018 overlap (631 distributions plus 4 rights issues) finds 635 exact CY-006 event-ID matches and 0 unmatched events.

## Semantics and causal rule

QD-010's raw CNINFO response distinguishes announcement, record, ex-right/effective, and payment dates. For this event, the causal market-coordinate boundary is `effective_date=2018-05-16`; `known_at=2018-05-10` gates observability. `record_date` identifies entitlement, not the price-coordinate boundary. `pay_date` is cash settlement timing, not the rebasing boundary.

The general rule already frozen by the Phase12B3 adapter is:

```text
Use an event only when known_at <= decision_date and effective_date <= decision_date.
Apply the event at effective_date: rebase prior history as
past_price=(past_price-cash_per_share_gross)/share_multiplier,
past_volume=past_volume*share_multiplier,
then append the raw same-day bar.
```

This rule is source-semantic, date-effective, PIT-safe, and event-term aware. It does not infer action terms from QD-001 prices. Unsupported, ambiguous, future, duplicate, late, incomplete, conflicting, or rights-participation cases remain fail-closed.

## Why the Phase12B3 mismatch finding is wrong

The frozen overlap report says “QD-010 event absent from CY-006 daily marker” and counts 635 QD-010 keys versus 634 CY-006 keys. Direct inspection of the current frozen CY-006 partition disproves that assertion for the named event, and the complete direct join disproves it for the recorded 635-event QD-010 set: every event is present with its exact ID. The QD-001 bar has no event state from which an independent event-key comparison could be made. Therefore the prior comparison contract/counting path, not the source dates, is defective or stale. No production adapter change is justified by this evidence.

The QD-001/CY-006 boundary status is `PARTIALLY_EQUIVALENT`: the named effective-date boundary is aligned exactly for this event, but QD-001 carries no action metadata, so general all-event equivalence is not proven and is not claimed.

## QD-010 revision-lineage adjudication

`revision_history_complete=false` means the retained asset is a current snapshot, not a complete historical stream: pre-capture source vintages are absent, source revision timestamps are not exposed (`source_updated_at_available=false`), and `fetched_at` is explicitly not `known_at`. The current row's announcement chronology is retained, but the snapshot cannot prove that an event absent from it was absent at an earlier historical cutoff, nor can it reconstruct retroactive corrections.

### BOUNDED_PIT_AUTHORIZED

Allowed use is limited to bounded PIT-B causal research over the registered QD-010 coverage `2017-04-12..2026-08-09`, using explicitly present and complete cash/share-distribution terms after `known_at` and `effective_date` gates pass. Cash distributions and share distributions/bonus shares may support causal rebasing. Rights issues remain execution-unresolved and cannot create participation or new risk.

Forbidden use includes strict archival PIT-A or vendor-level historical absence claims, production release, unsupported action classes, rights participation, and silently treating an absent current-snapshot row as observed historical non-occurrence.

Required assumptions are the frozen source manifest/hash, explicit event identity and terms, conservative `known_at` policy, exact effective-date application, and a valid trade calendar. Fail closed on missing or ambiguous terms, unavailable lineage, future visibility, duplicate identity, conflicting records, unsupported classes, or failed cross-table/action checks.

Revision incompleteness does not break causal use of an explicitly present event whose conservative announcement-derived `known_at` and effective date pass the bounded contract. It does break claims about complete historical event coverage, absence, or strict vendor PIT reconstruction.

## Consequence

The QD-001/QD-010 named mismatch blocker is resolved as an audit/contract defect. Historical-state remediation may proceed independently when authorized. Phase12B4 remains prohibited because the separate historical-state and 2017 warmup blockers remain unresolved.
