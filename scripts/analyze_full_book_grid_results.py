#!/usr/bin/env python3
"""Freeze discovery parameters and produce auditable full-book attribution tables.

The freeze query is deliberately restricted to DISCOVERY_2020_2022.  No 2023
or later observation is used to choose a parameter.  The same script can be
run on the locked holdout output to produce out-of-sample attribution without
changing the selection rule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml

DISCOVERY_GROUP = "DISCOVERY_2020_2022"
SIGNAL_LOWER = 150.0
SIGNAL_UPPER = 250.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


def rows(con: duckdb.DuckDBPyConnection, query: str) -> list[dict[str, Any]]:
    return con.execute(query).fetchdf().to_dict(orient="records")


def clean(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def clean_rows(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: clean(value) for key, value in row.items()} for row in values]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--top-n", type=int, default=7)
    parser.add_argument("--label", default="DISCOVERY_FREEZE")
    parser.add_argument("--selection-group", default=DISCOVERY_GROUP)
    parser.add_argument(
        "--frozen-ids",
        default=None,
        help="comma-separated parameter IDs to attribute without reselection",
    )
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    event_file = args.events.resolve()
    event_sql = sql_path(event_file)
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("rules"), dict):
        raise ValueError(f"invalid research config: {args.config}")
    rules = config["rules"]
    parameter_definitions: dict[int, dict[str, Any]] = {}
    param_id = 1
    for contraction in rules["contraction_pct"]:
        for pullback in rules["pullback_volume_mult"]:
            for breakout in rules["breakout_volume_mult"]:
                for market_gate in rules["market_gate"]:
                    for sector_gate in rules["sector_gate"]:
                        for confirmation in rules["confirmation_days"]:
                            for cooldown in config["cooldown_days"]:
                                for grace in rules["exit_grace_days"]:
                                    parameter_definitions[param_id] = {
                                        "param_id": param_id,
                                        "contraction": float(contraction),
                                        "pullback": float(pullback),
                                        "breakout": float(breakout),
                                        "market_gate": int(bool(market_gate)),
                                        "sector_gate": int(bool(sector_gate)),
                                        "confirmation": int(confirmation),
                                        "cooldown": int(cooldown),
                                        "grace": int(grace),
                                    }
                                    param_id += 1
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    try:
        integrity = {
            "event_rows": con.execute(
                f"SELECT count(*) FROM read_parquet('{event_sql}')"
            ).fetchone()[0],
            "distinct_event_keys": con.execute(
                f"""SELECT count(*) FROM (
                    SELECT DISTINCT param_id, symbol, signal_date, signal
                    FROM read_parquet('{event_sql}')
                )"""
            ).fetchone()[0],
            "parameter_count": con.execute(
                f"SELECT count(DISTINCT param_id) FROM read_parquet('{event_sql}')"
            ).fetchone()[0],
            "sample_groups": clean_rows(
                rows(
                    con,
                    f"""SELECT sample_group, count(*) AS rows,
                               min(signal_date) AS min_signal_date,
                               max(signal_date) AS max_signal_date
                        FROM read_parquet('{event_sql}')
                        GROUP BY sample_group ORDER BY sample_group""",
                )
            ),
        }
        integrity["duplicate_event_keys"] = (
            integrity["event_rows"] - integrity["distinct_event_keys"]
        )

        freeze_query = f"""
            WITH by_param AS (
                SELECT param_id,
                       count(*) AS signal_count,
                       count(*) / 3.0 AS signals_per_year,
                       avg(selected_net_return) AS mean_return,
                       median(selected_net_return) AS median_return,
                       avg(CASE WHEN selected_net_return > 0 THEN 1.0 ELSE 0.0 END)
                           AS win_rate
                FROM read_parquet('{event_sql}')
                WHERE sample_group = '{args.selection_group.replace("'", "''")}'
                GROUP BY param_id
            )
            SELECT * FROM by_param
            WHERE signals_per_year BETWEEN {SIGNAL_LOWER} AND {SIGNAL_UPPER}
            ORDER BY mean_return DESC, median_return DESC, param_id
        """
        eligible = clean_rows(rows(con, freeze_query))
        if args.frozen_ids:
            parameter_ids = [
                int(item.strip()) for item in args.frozen_ids.split(",") if item.strip()
            ]
            if len(parameter_ids) != len(set(parameter_ids)):
                raise ValueError("--frozen-ids contains duplicates")
            unknown = [item for item in parameter_ids if item not in parameter_definitions]
            if unknown:
                raise ValueError(f"unknown parameter IDs: {unknown}")
            selected_metrics = {int(row["param_id"]): row for row in eligible}
            selected = []
            for item in parameter_ids:
                definition = dict(parameter_definitions[item])
                definition["selection_metrics"] = selected_metrics.get(item)
                selected.append(definition)
        else:
            selected = []
            parameter_ids = []
            for row in eligible[: args.top_n]:
                item = int(row["param_id"])
                definition = dict(parameter_definitions.get(item, {"param_id": item}))
                definition["selection_metrics"] = row
                selected.append(definition)
                parameter_ids.append(item)

        def id_filter() -> str:
            if not parameter_ids:
                return "FALSE"
            return "param_id IN (" + ",".join(str(item) for item in parameter_ids) + ")"

        selected_filter = id_filter()
        by_year = clean_rows(
            rows(
                con,
                f"""SELECT param_id, sample_group,
                           year(signal_date) AS signal_year, count(*) AS signals,
                           count(*) / CASE WHEN sample_group = '{DISCOVERY_GROUP}'
                                           THEN 3.0 ELSE NULL END AS signals_per_year,
                           avg(selected_net_return) AS mean_return,
                           median(selected_net_return) AS median_return,
                           avg(CASE WHEN selected_net_return > 0 THEN 1.0 ELSE 0.0 END)
                               AS win_rate
                    FROM read_parquet('{event_sql}')
                    WHERE {selected_filter}
                    GROUP BY param_id, sample_group, signal_year
                    ORDER BY param_id, sample_group, signal_year""",
            )
        )
        by_board = clean_rows(
            rows(
                con,
                f"""SELECT param_id, sample_group, board, count(*) AS signals,
                           avg(selected_net_return) AS mean_return,
                           median(selected_net_return) AS median_return,
                           avg(CASE WHEN selected_net_return > 0 THEN 1.0 ELSE 0.0 END)
                               AS win_rate
                    FROM read_parquet('{event_sql}')
                    WHERE {selected_filter}
                    GROUP BY param_id, sample_group, board
                    ORDER BY param_id, sample_group, board""",
            )
        )
        by_entry = clean_rows(
            rows(
                con,
                f"""SELECT param_id, sample_group, signal, count(*) AS signals,
                           avg(selected_net_return) AS mean_return,
                           median(selected_net_return) AS median_return,
                           avg(CASE WHEN selected_net_return > 0 THEN 1.0 ELSE 0.0 END)
                               AS win_rate
                    FROM read_parquet('{event_sql}')
                    WHERE {selected_filter}
                    GROUP BY param_id, sample_group, signal
                    ORDER BY param_id, sample_group, signal""",
            )
        )
        by_exit = clean_rows(
            rows(
                con,
                f"""SELECT param_id, sample_group, exit_reason, count(*) AS signals,
                           avg(selected_net_return) AS mean_return,
                           median(selected_net_return) AS median_return,
                           avg(CASE WHEN selected_net_return > 0 THEN 1.0 ELSE 0.0 END)
                               AS win_rate
                    FROM read_parquet('{event_sql}')
                    WHERE {selected_filter}
                    GROUP BY param_id, sample_group, exit_reason
                    ORDER BY param_id, sample_group, signals DESC""",
            )
        )
        by_industry = clean_rows(
            rows(
                con,
                f"""SELECT param_id, sample_group, board, industry,
                           count(*) AS signals,
                           avg(selected_net_return) AS mean_return,
                           median(selected_net_return) AS median_return,
                           avg(CASE WHEN selected_net_return > 0 THEN 1.0 ELSE 0.0 END)
                               AS win_rate
                    FROM read_parquet('{event_sql}')
                    WHERE {selected_filter}
                    GROUP BY param_id, sample_group, board, industry
                    HAVING count(*) >= 10
                    ORDER BY param_id, sample_group, mean_return DESC""",
            )
        )
        symbol_winners = clean_rows(
            rows(
                con,
                f"""SELECT param_id, sample_group, symbol, board, industry,
                           count(*) AS signals,
                           avg(selected_net_return) AS mean_return,
                           median(selected_net_return) AS median_return
                    FROM read_parquet('{event_sql}')
                    WHERE {selected_filter}
                    GROUP BY param_id, sample_group, symbol, board, industry
                    HAVING count(*) >= 2
                    ORDER BY mean_return DESC, signals DESC
                    LIMIT 100""",
            )
        )
        symbol_losers = clean_rows(
            rows(
                con,
                f"""SELECT param_id, sample_group, symbol, board, industry,
                           count(*) AS signals,
                           avg(selected_net_return) AS mean_return,
                           median(selected_net_return) AS median_return
                    FROM read_parquet('{event_sql}')
                    WHERE {selected_filter}
                    GROUP BY param_id, sample_group, symbol, board, industry
                    HAVING count(*) >= 2
                    ORDER BY mean_return ASC, signals DESC
                    LIMIT 100""",
            )
        )

        result = {
            "analysis_version": "full-book-grid-attribution-v1",
            "created_at": datetime.now(UTC).isoformat(),
            "events": str(event_file),
            "events_sha256": sha256_file(event_file),
            "config": str(args.config.resolve()),
            "config_sha256": sha256_file(args.config),
            "freeze_rule": {
                "selection_sample": args.selection_group,
                "signal_year_min": SIGNAL_LOWER,
                "signal_year_max": SIGNAL_UPPER,
                "sort": ["mean_return_desc", "median_return_desc", "param_id_asc"],
                "top_n": args.top_n,
                "explicit_frozen_ids": bool(args.frozen_ids),
                "label": args.label,
                "holdout_and_2023_excluded_from_selection": True,
            },
            "integrity": integrity,
            "eligible_count": len(eligible),
            "eligible_head": eligible[:50],
            "frozen_parameter_ids": parameter_ids,
            "frozen_parameters": selected,
            "annual": by_year,
            "board": by_board,
            "entry_signal": by_entry,
            "exit_reason": by_exit,
            "industry_min_10_signals": by_industry,
            "symbol_winners_min_2_signals_top_100": symbol_winners,
            "symbol_losers_min_2_signals_bottom_100": symbol_losers,
        }
        output_json = args.output / "attribution_and_freeze.json"
        output_json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=clean) + "\n",
            encoding="utf-8",
        )
        (args.output / "frozen_parameter_ids.txt").write_text(
            ",".join(str(item) for item in parameter_ids) + "\n", encoding="utf-8"
        )
        print(json.dumps({
            "output": str(output_json),
            "events_sha256": result["events_sha256"],
            "eligible_count": len(eligible),
            "frozen_parameter_ids": parameter_ids,
            "duplicate_event_keys": integrity["duplicate_event_keys"],
        }, ensure_ascii=False))
    finally:
        con.close()


if __name__ == "__main__":
    main()
