#!/usr/bin/env python3
"""Run the 81-entry funnel independently for a small exact-chip stock set."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import duckdb

from cyq_game.strategy.chip_lineage import PersistedChipLineageResolver
from cyq_game.strategy.markup_retest import MarkupRetestConfig
from cyq_game.strategy.research import screen_entry_lattice


def _diagnose_symbol(task: tuple[str, str, str, str, str]) -> dict[str, Any]:
    symbol, panel_glob, inventory_root, config_path, panel_snapshot_id = task
    con = duckdb.connect()
    query = con.execute(
        f"""
        SELECT * FROM read_parquet('{panel_glob}', hive_partitioning=true)
        WHERE symbol = ? ORDER BY symbol, trade_date
        """,
        [symbol],
    )
    columns = [item[0] for item in query.description]
    records = [dict(zip(columns, row, strict=True)) for row in query.fetchall()]
    con.close()
    root = Path(inventory_root)
    result = screen_entry_lattice(
        records,
        MarkupRetestConfig.load(config_path),
        panel_snapshot_id=panel_snapshot_id,
        anchor_retention_resolver=PersistedChipLineageResolver(root),
    )
    nonzero = []
    for parameters in result.parameters:
        annual = result.annual_evaluation_signal_counts[parameters.parameter_id]
        if annual:
            nonzero.append(
                {
                    "parameter_id": parameters.parameter_id,
                    "parameters": parameters.canonical(),
                    "annual": {str(year): count for year, count in annual.items()},
                }
            )
    dates = sorted(
        {
            str(signal["decision_at"])
            for signal in result.signals
            if str(signal["decision_at"])[:4] in {"2020", "2021", "2022", "2023"}
        }
    )
    development_signals = [
        {
            "parameter_id": str(signal["parameter_id"]),
            "decision_at": str(signal["decision_at"]),
            "accumulation_started_at": str(signal["accumulation_started_at"]),
            "breakout_at": str(signal["breakout_at"]),
            "anchor_retention_lower": float(signal["anchor_retention_lower"]),
        }
        for signal in result.signals
        if str(signal["decision_at"])[:4] in {"2020", "2021", "2022", "2023"}
    ]
    return {
        "symbol": symbol,
        "rows": result.input_rows,
        "evaluation_rows": result.evaluation_rows,
        "nonzero_parameter_sets": len(nonzero),
        "unique_development_signal_dates": dates,
        "development_signals": development_signals,
        "nonzero": nonzero,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--primary-root", type=Path, required=True)
    parser.add_argument("--secondary-root", type=Path, required=True)
    parser.add_argument(
        "--symbol-root",
        action="append",
        default=[],
        metavar="SYMBOL=PATH",
        help="Override one symbol's exact inventory root",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    args = parser.parse_args()
    panel_manifest = json.loads((args.panel.parent / "manifest.json").read_text())
    panel_snapshot_id = str(panel_manifest["panel_snapshot_id"])
    config = MarkupRetestConfig.load(args.config)
    symbol_roots: dict[str, Path] = {}
    for item in args.symbol_root:
        symbol, separator, raw_path = item.partition("=")
        if not separator or not symbol or not raw_path:
            parser.error("--symbol-root must use SYMBOL=PATH")
        symbol_roots[symbol] = Path(raw_path)
    panel_glob = str(args.panel / "**" / "*.parquet")
    tasks = [
        (
            symbol,
            panel_glob,
            str(
                symbol_roots.get(
                    symbol,
                    args.primary_root if symbol == "000001.SZ" else args.secondary_root,
                )
            ),
            str(args.config),
            panel_snapshot_id,
        )
        for symbol in args.symbols
    ]
    with ProcessPoolExecutor(max_workers=min(10, len(tasks))) as pool:
        results = list(pool.map(_diagnose_symbol, tasks))
    payload = {
        "status": "QA_DIAGNOSTIC_ONLY",
        "config_sha256": config.sha256,
        "panel_snapshot_id": panel_snapshot_id,
        "chip_lineage_asset_id": config.assets.chip_lineage_asset_id,
        "symbols": len(results),
        "symbols_with_development_events": sum(
            bool(item["unique_development_signal_dates"]) for item in results
        ),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
