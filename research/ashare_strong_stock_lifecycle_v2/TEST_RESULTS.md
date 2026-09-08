# Test results

`PYTHONPATH=.:src python -m pytest -q research/ashare_strong_stock_lifecycle_v2/test_lifecycle.py`

Result: `6 passed`.

Materialized-panel audit also passed: 85,966 unique event IDs; 85,168 events with exactly 20 frozen peers; no leader appears in its peer list; no-pressure and peer-unavailable events remain in the panel; pressure starts after event `t`; landmark is exactly `P+4`; no landmark is assigned to no-pressure/no-peer rows; board, historical limit availability, and corporate-action-count fields are present; event-panel SHA-256 matches `V2_MANIFEST.json`.
