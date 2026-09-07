# Five Strategy Bundle

An independent Python package that reproduces five frozen A-share strategies from registered base data. Production uses no golden signal, trade, event, or NAV files. Physical data locations are supplied only through JSON configuration.

## Installation

Python 3.10 or newer and the versions recorded in `requirements.lock` are required.

```bash
python -m pip install -e . --no-deps
python -m pytest -q
```

## Data requirements

Copy `configs/input.example.json`, replace each example path with a registered asset location, and pass that file with `--input-config`. Required logical inputs are:

- `daily_hist`: PIT daily bars, coordinate prices, calendars, validity, industry, availability, corporate-action, and trading-status fields used by MCB, OGR, IFCGR, and historical ATRDR.
- `daily_tail`: registered daily execution tail used by MCB and historical ATRDR.
- `atrdr_daily_2024_2025`, `atrdr_daily_2026`: hash-pinned QD-010 coordinate daily assets for the post-2023 ATRDR intervals.
- `mcb_market_industry_state`: completed-close causal market and industry state.
- `raw_minute_root`, `cy033_daily_amount`: registered one-minute bars and PIT-B daily amount partitions for OGR/IFCGR.
- `qd010_distributions`, `qd010_rights`: registered corporate-action tables.
- `ifcgr_route_index`, `ifcgr_sse_titles`, `ifcgr_szse_titles`: registered PIT-B issuer-fact assets.
- `smv6_qmt_root`, `smv6_hybrid_root`: registered QMT daily and hybrid ETF minute/availability roots.

The exact required fields and time semantics are documented in `manifests/raw_input_contract.json`. Unknown or missing required lineage fails closed.

## Reproduction

Every command below is a complete production run and deliberately omits golden files.

```bash
python -m five_strategy_bundle.reproduce --strategy MCB   --input-config inputs.json --output-root output
python -m five_strategy_bundle.reproduce --strategy OGR   --input-config inputs.json --output-root output
python -m five_strategy_bundle.reproduce --strategy IFCGR --input-config inputs.json --output-root output
python -m five_strategy_bundle.reproduce --strategy ATRDR --input-config inputs.json --output-root output
python -m five_strategy_bundle.reproduce --strategy SMV6  --input-config inputs.json --output-root output
```

Production zero points:

- MCB: registered PIT daily plus completed-close market/industry state; V53 → V64 → V65 → V72 → execution → portfolio → NAV.
- OGR: registered PIT daily/minute/amount/corporate actions; V13 → V27 → V28 → V28R1 → V28R2 → execution → portfolio → NAV.
- IFCGR: same-run standalone OGR plus registered PIT-B issuer facts; cooldown → keep/reject → execution → portfolio → NAV.
- ATRDR: registered PIT daily; market state → Bull/Fast Bear/Slow Bear/post-2023 producers → arbitration → execution → portfolio → NAV.
- SMV6: registered QMT/hybrid ETF daily and minute inputs; exact frozen source → callbacks → desired holdings/orders → local fills/cash/positions → NAV.

## Strategy status

- MCB: `FULL_END_TO_END_REPRODUCIBLE`
- OGR: `FULL_END_TO_END_REPRODUCIBLE`
- IFCGR: `END_TO_END_REPRODUCIBLE_WITH_PIT_B`
- ATRDR: `HISTORICAL_ATRDR_V29_PLUS_REGISTERED_V27_CONTINUATIONS`
- SMV6: `LOCAL_END_TO_END_REPRODUCIBLE_PLATFORM_EQUIVALENCE_UNVERIFIED`

IFCGR uses current official PIT-B enumeration whose revision/deletion history is incomplete. SMV6 reproduces local execution but does not claim native SuperMind broker equivalence.

The ATRDR V29 identity is closed only through 2023-12-31. The registered
2024-2026 continuations are V27 route/account runs and are not represented as
ATRDR V29.

## Capital and leverage policy

Every production account is long-only and cash-funded. Financing, margin,
borrowed cash, temporary negative cash, synthetic cash injection, and borrowing
between sleeves are prohibited. Gross long market value may not exceed account
NAV. Buy affordability is decided before execution using the applicable
commission, slippage-adjusted fill price, volume cap, and board-lot size; a
minimum fee is included only where the frozen execution contract defines one.
When available cash is insufficient, the existing execution contract either
reduces the order to an affordable lot or rejects/skips it. Later intraday sale
proceeds cannot finance an earlier open order.

After a complete run, verify both sleeve and fixed-portfolio aggregates with:

```bash
python verify_no_financing.py --output-root output --report-dir reports
```

## Provenance

`manifests/source_provenance.json` identifies each component. `EXACT_COPY` means registered source bytes are preserved; `MINIMAL_EXTRACT` means only the audited producer semantics were extracted; `BEHAVIORALLY_RECONSTRUCTED_EXACT` means the original producer was unavailable and the reconstruction passed complete golden-population comparison without outcome-based fitting. Runtime never depends on the original repository or its Git history.

## Golden references

Golden files are optional validation inputs and are never production inputs. After a production run, validate separately:

```bash
python -m five_strategy_bundle.validate --strategy MCB --golden-config mcb-golden.json --output-root output
```

Repeat with each strategy name. Golden configuration uses the same `{"inputs": {...}}` shape as the production configuration. SMV6 validation compares the 779 source-generated strategy events; its local cash/lot NAV is assessed under the local execution contract, not against the old fractional zero-cost shadow NAV.
