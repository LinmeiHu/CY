# SuperMind V6 isolated market-data foundation

This directory contains only the reproducible research code and small audit
artifacts for the frozen V6 strategy. Large/raw market data is written below the
Git-ignored paths `research/supermind_v6/data/market_data_qmt_v1/` (selected QMT
build) and `research/supermind_v6/data/market_data_v1/` (preserved earlier
Eastmoney partial build).

## Commands

```bash
cd /Users/linmei/Documents/CY-supermind-v6

# Run these two commands with the Windows 11 VM and Guojin QMT API endpoint open.
# They are bounded to the parsed 152-ETF pool plus two daily index anchors.
prlctl exec 'Windows 11' \
  'C:\Users\linmei\QMTResearch\Python311\python.exe' \
  'C:\Mac\Home\Documents\CY-supermind-v6\research\supermind_v6\scripts\export_v6_from_qmt.py' \
  --strategy 'C:\Mac\Home\Documents\CY-supermind-v6\research\supermind_v6\strategy\SuperMind_V6_CSI1000_MA15_ENTRY_HS300_MA20_EXIT_MINVOLLOC30_CAP50_SET_TAIL_SELL_OPEN_BUY_COMMENTS_FIXED.py' \
  --output 'C:\Mac\Home\Documents\CY-supermind-v6\research\supermind_v6\data\market_data_qmt_v1' \
  --start 19900101 --end 20260828 --mode daily

prlctl exec 'Windows 11' \
  'C:\Users\linmei\QMTResearch\Python311\python.exe' \
  'C:\Mac\Home\Documents\CY-supermind-v6\research\supermind_v6\scripts\export_v6_from_qmt.py' \
  --strategy 'C:\Mac\Home\Documents\CY-supermind-v6\research\supermind_v6\strategy\SuperMind_V6_CSI1000_MA15_ENTRY_HS300_MA20_EXIT_MINVOLLOC30_CAP50_SET_TAIL_SELL_OPEN_BUY_COMMENTS_FIXED.py' \
  --output 'C:\Mac\Home\Documents\CY-supermind-v6\research\supermind_v6\data\market_data_qmt_v1' \
  --start 19900101 --end 20260828 --mode critical-minute

# Copy governed metadata, build the manifest, then validate fail closed.
python research/supermind_v6/scripts/finalize_qmt_v6_manifest.py --end-date 20260828
python research/supermind_v6/scripts/validate_qmt_v6_market_data.py

# Build the fail-closed limited-window execution-availability layer on macOS.
python research/supermind_v6/scripts/build_v6_open_execution_availability.py

# With QMT running, audit the first real bar after every unavailable 09:30 event.
prlctl exec 'Windows 11' \
  'C:\Users\linmei\QMTResearch\Python311\python.exe' \
  'C:\Mac\Home\Documents\CY-supermind-v6\research\supermind_v6\scripts\audit_qmt_open_gaps.py'

# Contract tests.
pytest -q research/supermind_v6/tests/
```

The QMT exporter is atomic and resumable per partition. A cache hit requires the
same bounded request plus a matching partition SHA-256. One symbol failure does
not abort the batch and remains explicit in the summary. It never requests the
full A-share market. QMT's proprietary cache is not treated as an immutable raw
artifact; extracted Parquet partitions and sidecars carry lineage and hashes.

## Current result

The QMT build has 152/152 ETF daily partitions, 212,679 ETF daily rows, both index
anchors, a QMT calendar through 2026-08-28, and 152/152 recent critical-minute
partitions. The critical layer has 109,187 rows from approximately
2025-08-27..2026-08-28; it is not full-history minute data. Validation remains
fail-closed because 144 symbols lack earlier minute history, 175 expected 09:30
bars are absent, exact opening-auction semantics are unverified, and QMT `front`
has not been proven equivalent to SuperMind `fq='pre'`.

For a bounded replay starting on 2025-08-28, the separate execution-availability
layer covers 36,310 expected symbol-sessions and never creates a synthetic price.
It classifies 816 unavailable 09:30 events, 914 unavailable 14:57 signal events,
and 1,084 unavailable 15:00 execution events. The primary policy is fail closed:
no open/close fill without a valid traded bar, and no 14:57 tail signal without a
valid 14:57 bar. QMT found a later real bar for all 816 unavailable opens, but
those prices remain diagnostic sensitivity inputs rather than silent substitutes
or accepted SuperMind fills. See
`manifests/v6_open_execution_availability.json`.
