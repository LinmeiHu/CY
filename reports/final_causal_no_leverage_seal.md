# Five Strategy Standalone Causal No-Leverage Seal V2

## Direct answers

1. **Do all five strategies use only account cash?** Yes. All production accounts and sub-sleeves are independently cash-funded; every observed account and sleeve passed.
2. **Was cash negative at any timestamp or on any day?** No. Counts are zero for every strategy and every registered ATRDR segment.
3. **Did any strategy exceed 100% gross long exposure?** No. The maximum observed ratio was `0.999995581982908` in SMV6.
4. **Did any fixed portfolio aggregate exceed 100%?** No. P1, P2, R1, and R2 all passed; the largest observed aggregate ratio was `0.6999273163782519` in R2.
5. **Was borrowed cash or margin used?** No. Both maxima are zero and the execution models expose no borrowing or margin facility.
6. **What happens when cash is insufficient?** MCB, historical ATRDR, OGR, and IFCGR skip/reject according to their frozen priority and capacity contracts. SMV6 applies its volume cap, slippage-adjusted fill price, 2bp commission and 100-share lot floor before filling; nine orders were reduced to affordable lots and none was financed.
7. **What did the MCB timing fix change?** Accepted/funded events changed from 1021 to 1010, with 21 identities in the symmetric difference. Total return changed from `0.9617491025224512` to `0.9355958013324606`; ending NAV changed by `-0.0261533011899906`. This is the expected consequence of causal cash/slot ordering and persisting entered immature positions.
8. **What did the ATRDR Fast Bear fix change?** It restored completed events `OAI-20200325-603259.SH` and `OAI-20220214-002177.SZ`. Fast outcomes changed 660 to 666, Fast capacity accepted 550 to 556, and historical funded events 2119 to 2121. Historical ending NAV changed from `3.123001895478578` to `3.1105406156705437`.
9. **Did frozen economic rules change?** No. Thresholds, ranks, targets, horizons, costs, order priorities and capacity limits are unchanged. The changes correct causal availability/account state, expose dates, add accounting fields, and enforce the no-financing invariant.
10. **What caveats remain?** ATRDR V29 is closed only through 2023; 2024–2026 outputs are registered V27 continuations, not V29. IFCGR remains PIT-B. SMV6 native SuperMind equivalence is unverified. OGR/IFCGR VAP diagnostic sums show raw rerun noise up to `8.881784197001252e-15`, with stable identities, economic fields and NAV.

## Seal identity

- Seal: `FIVE_STRATEGY_STANDALONE_CAUSAL_NO_LEVERAGE_V2`
- Old seal HEAD: `806cafdd96b9778654d531319c615293b47e593b`
- Audited production HEAD: `4f62a0b6f4d7cb9e0266e15afb5e4f2550c592c6`
- Economic rules changed: `NO`
- New sealed validation opened: `NO`
- Production requires golden: `NO`
- CY code runtime dependency: `NO`
- Production frozen-intermediate dependency: `NO`
- Package content SHA256: `b2ad54b2cf6f6c1ebd388b01a9134bbfe9dda1638e8664d2eebc3f77c551a604`

The old seal remains in Git history. The old golden is historical evidence only; it is not a production input and is not binding where it encodes the confirmed causal account bugs.

## Strategy hard-gate results

| Strategy | Period included in headline | Min cash | Max gross ratio | Negative cash days | Over-100% days | Cash shortfalls | Cash partial/reject | Status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| ATRDR | 2014-01-03–2023-12-29 | 0.00016163635573016033 | 0.9998943205724158 | 0 | 0 | 450 | 450 | PASS |
| MCB | 2014-02-13–2026-03-31 | 0.0036962513583479045 | 0.9958325288986848 | 0 | 0 | 163 | 163 | PASS |
| OGR | 2018-01-02–2021-12-15 | 0.0014526602262134036 | 0.9985725199847942 | 0 | 0 | 0 | 0 | PASS |
| IFCGR | 2018-01-02–2021-12-15 | 0.0014456707100633827 | 0.9985725199847948 | 0 | 0 | 0 | 0 | PASS |
| SMV6 | 2013-04-01–2026-08-28 | 4.513061951322015 | 0.999995581982908 | 0 | 0 | 9 | 9 partial / 0 reject | PASS |

ATRDR V27 continuation sub-sleeves were also audited directly: 2024–2025 plus its outcome tail had maximum gross ratio `0.32787789638367404`; the 2026 segment had `0.20585450535022615`. Both had zero negative-cash or over-exposure days.

## Fixed portfolio aggregate verification

The verifier is not strategy production logic. It reads independently funded historical sleeve NAV/exposure, normalizes each at the common start, and applies the frozen weights without rebalancing or cross-sleeve borrowing.

| Portfolio | Common period | Min cash | Max gross ratio | Negative cash days | Over-100% days | Status |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| P1 | 2018-01-02–2021-12-15 | 0.35074827697413724 | 0.699250005441039 | 0 | 0 | PASS |
| P2 | 2018-01-02–2021-12-15 | 0.3499758370754633 | 0.699711264517293 | 0 | 0 | PASS |
| R1 | 2018-01-02–2021-12-15 | 0.3612757935305646 | 0.699479691482738 | 0 | 0 | PASS |
| R2 | 2018-01-02–2021-12-15 | 0.3605033536318907 | 0.6999273163782519 | 0 | 0 | PASS |

Only historical ATRDR V29 enters these fixed portfolio checks. The registered post-2023 V27 continuation is deliberately excluded from V29 portfolio identity.

## Production corrections and regressions

- `replay_sleeves`: non-target open exits settle before open buys; target exits settle afterward. Entered incomplete tails remain open and marked through the registered daily end.
- ATRDR Fast Bear: every frozen Fast signal gets its own T10/H20 outcome; no T20/H60 future-completion prefilter remains.
- OGR: explicit account start/end parameters were added, while defaults retain the old sealed 2018–2021 behavior.
- SMV6: the executed cost contract remains 2bp commission plus 16bp round-trip slippage. Cash affordability and its audit metadata are explicit.
- OGR stayed at 370 signals, 355 outcomes and 255 funded trades; IFCGR stayed at 362 kept, 8 rejected and 248 funded trades. Their NAV paths match the old seal.
- SMV6 stayed at 779 strategy events, 1081 local execution events and 3260 NAV rows; common execution fields and NAV match the old seal.

## Verification evidence

- Focused/full test suite: `17 passed, 1 skipped` (the skip is the opt-in external reproduction test).
- Two registered-input runs were performed, including one fresh repo-outside install with empty `PYTHONPATH`.
- Isolation root: `/private/tmp/five_strategy_bundle_causal_v2_ObqCh3`; all 17 project modules resolved inside its copied package.
- Deterministic rerun: 24 of 24 core outputs passed canonical SHA256 comparison at 12 decimal places. The canonicalization covers only binary float noise far below rule thresholds; identity lists and NAV hashes were independently stable.
- Strategy and fixed-portfolio no-financing audits: PASS.

## Reproduction commands

```bash
for strategy in MCB OGR IFCGR ATRDR SMV6; do
  PYTHONPATH= python -m five_strategy_bundle.reproduce \
    --strategy "$strategy" \
    --input-config /private/tmp/five_strategy_bundle_all_inputs.json \
    --output-root /path/outside/repository/output
done

PYTHONPATH= python verify_no_financing.py \
  --output-root /path/outside/repository/output \
  --report-dir reports
```

Detailed evidence is in `production_change_classification.csv`, `old_vs_causal_v2.csv`, `no_financing_audit.csv`, `no_financing_portfolio_audit.csv`, `deterministic_rerun.csv`, and `strategy_reproducibility_matrix.csv`.
