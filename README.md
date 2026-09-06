# Five Strategy Bundle

This directory is a split-ready Python package. It never imports code from CY, reads Git objects at runtime, or assumes a user/mount path. Physical data paths are injected by JSON config.

Current closure is deliberately reported per strategy. MCB is fully closed from registered daily/state inputs through V53, V64, V65, V72, execution, cash and NAV. ATRDR is closed and replayed for its 2014–2023 historical source interval, including newly recovered/reconstructed Fast and Slow Bear mother screens, but its post-2023 producers are not yet bundled. OGR, IFCGR and SMV6 remain source-chain incomplete in this delivery; their CLI calls fail closed instead of consuming frozen intermediates.

## Install and run

```bash
python -m pip install -e . --no-deps
python -m pytest -q
python -m five_strategy_bundle.reproduce \
  --strategy MCB \
  --input-config /path/to/inputs.json \
  --golden-config /path/to/mcb-golden.json \
  --output-root /path/to/output
```

Input config:

```json
{
  "inputs": {
    "daily_hist": "/registered/daily.parquet",
    "daily_tail": "/registered/daily_tail.parquet",
    "mcb_market_industry_state": "/registered/market_industry_state.parquet"
  }
}
```

Golden files are comparison-only and use the same JSON shape. They are never passed into a producer.

## Full command surface

```bash
python -m five_strategy_bundle.reproduce --strategy OGR   --input-config inputs.json --output-root output
python -m five_strategy_bundle.reproduce --strategy IFCGR --input-config inputs.json --output-root output
python -m five_strategy_bundle.reproduce --strategy MCB   --input-config inputs.json --golden-config mcb-golden.json --output-root output
python -m five_strategy_bundle.reproduce --strategy ATRDR --input-config inputs.json --output-root output
python -m five_strategy_bundle.reproduce --strategy SMV6  --input-config inputs.json --output-root output
```

OGR, IFCGR and SMV6 currently terminate with `SOURCE_CHAIN_INCOMPLETE`. ATRDR returns the same status after writing its verified historical layers because the registered current strategy extends beyond 2023.

## Evidence boundaries

- IFCGR evidence remains `PIT_B_CURRENT_OFFICIAL_ENUMERATION_REVISION_HISTORY_INCOMPLETE`; it is not PIT-A.
- SMV6 local broker semantics, when eventually bundled, must be labeled `LOCAL_FROZEN_EXECUTION_SEMANTICS_V1`; this is not claimed native SuperMind broker equivalence.
- A different Parquet SHA does not itself imply a logical mismatch. The layer manifest records identity and value comparisons separately.
- Runtime code contains no built-in data locations. See `manifests/raw_input_contract.json` for required columns and time semantics.

The subtree can be split with:

```bash
git subtree split --prefix=standalone/five_strategy_bundle -b five-strategy-standalone
```
