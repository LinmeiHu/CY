# Five Strategy Bundle

This directory is a split-ready Python package. It never imports code from CY, reads Git objects at runtime, or assumes a user/mount path. Physical data paths are injected by JSON config.

Current closure is reported per strategy. OGR, IFCGR, MCB, and the local SMV6 replay are executable from configured raw/registered inputs without frozen signal, trade, event, or NAV inputs. ATRDR is exact through its 2014-2023 frozen source interval, including the 3,433-event Fast reconstruction and the recovered Slow/Bull sources, but its two missing post-2023 V27 producers have not passed exact-population reconstruction and therefore remain fail-closed.

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

Input config follows `configs/input.example.json`; only keys needed by the selected strategy are required. For example, MCB uses:

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

OGR and IFCGR reproduce their frozen development reference interval. IFCGR always regenerates its complete OGR parent in the same invocation. SMV6 executes the exact registered source bytes after an internal SHA256 check, emits source callback events, and separately emits cash/100-share-lot fills with the frozen source's commission, slippage, minute-volume limit, and order ordering. ATRDR returns `SOURCE_CHAIN_INCOMPLETE` after writing its verified historical layers because the required post-2023 population is not exact.

## Evidence boundaries

- IFCGR evidence remains `PIT_B_CURRENT_OFFICIAL_ENUMERATION_REVISION_HISTORY_INCOMPLETE`; it is not PIT-A.
- SMV6 local broker semantics are labeled `LOCAL_FROZEN_EXECUTION_SEMANTICS_V1`; this is not claimed native SuperMind broker equivalence.
- A different Parquet SHA does not itself imply a logical mismatch. The layer manifest records identity and value comparisons separately.
- Runtime code contains no built-in data locations. See `manifests/raw_input_contract.json` for required columns and time semantics.

The subtree can be split with:

```bash
git subtree split --prefix=standalone/five_strategy_bundle -b five-strategy-standalone
```
