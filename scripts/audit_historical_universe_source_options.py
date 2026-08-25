#!/usr/bin/env python3
"""Record bounded, local evidence about candidate historical universe sources.

This is an evidence report only.  It never promotes a source into the data
asset registry and never treats a current snapshot as a historical PIT input.
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import os
import platform
from datetime import UTC, datetime
from pathlib import Path


def _module_state(name: str) -> dict[str, object]:
    present = importlib.util.find_spec(name) is not None
    return {"installed": present, "credential_present": bool(os.getenv("TUSHARE_TOKEN")) if name == "tushare" else None}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    ak_state = _module_state("akshare")
    ts_state = _module_state("tushare")
    ak_functions: list[dict[str, str]] = []
    if ak_state["installed"]:
        import akshare as ak

        for name in sorted(dir(ak)):
            if not any(token in name.lower() for token in ("stock", "trade", "list", "history")):
                continue
            try:
                signature = str(inspect.signature(getattr(ak, name)))
            except (TypeError, ValueError):
                continue
            if any(token in signature.lower() for token in ("date", "trade_date", "start_date")):
                ak_functions.append({"name": name, "signature": signature})

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "sources": {
            "akshare": {
                **ak_state,
                "bounded_local_finding": "Installed; date-parameterized functions inspected locally, but no full-market historical security-universe endpoint was identified. Date parameters mostly target single-stock history or thematic lists.",
                "candidate_functions": ak_functions,
                "research_ready": False,
                "reason": "No demonstrated date-effective full-market snapshot, immutable source response, available_at, snapshot_id, and revision lineage.",
            },
            "tushare": {
                **ts_state,
                "bounded_local_finding": "Client installed, but no TUSHARE_TOKEN is present; stock_basic is a current/basic listing interface rather than demonstrated historical daily universe snapshots.",
                "research_ready": False,
                "reason": "No authorized access and no demonstrated historical PIT snapshot contract.",
            },
            "baostock": {
                "installed": importlib.util.find_spec("baostock") is not None,
                "bounded_local_finding": "Date-specific query_all_stock probes exist and are retained under QD-007 discovery, but materialization is incomplete and the source lacks an authorized immutable revision-vintage contract.",
                "research_ready": False,
                "reason": "QD-007 remains DISCOVERY_ONLY; incomplete coverage and missing activated PIT lineage.",
            },
        },
        "policy": {
            "asset_registry_unchanged": True,
            "fail_closed": True,
            "next_required_evidence": [
                "complete date-effective snapshots for every required trading date",
                "raw response/request metadata, source revision, available_at, snapshot_id, and canonical hashes",
                "listing/delisting/code-change/calendar reconciliation and duplicate audit",
                "registry activation only after all cross-table PIT gates pass",
            ],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
