#!/usr/bin/env python3
"""Complete the preregistered 81-point economic entry selection."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import itertools
import json
import math
import os
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cyq_game.strategy.economic_evaluation import (  # type: ignore[import-untyped]
    capacity_industry,
    combined_gate_metrics,
    paired_weekly_difference_evidence,
    replay_economic_metrics,
)
from cyq_game.strategy.economic_selection import (  # type: ignore[import-untyped]
    ENTRY_DIMENSIONS,
    assess_candidate,
    select_robust_region,
)
from cyq_game.strategy.exact_replay import (  # type: ignore[import-untyped]
    _market_trading_dates,
    _stream_execution_windows,
)
from cyq_game.strategy.fixed_horizon import (  # type: ignore[import-untyped]
    FixedHorizonTrade,
    PanelSession,
    evaluate_fixed_horizon_trade,
    panel_session_from_record,
)
from cyq_game.strategy.ledger import LedgerEntry, TrialLedger  # type: ignore[import-untyped]
from cyq_game.strategy.markup_retest import (  # type: ignore[import-untyped]
    MarkupRetestConfig,
    StrategyParameters,
    StrategyStage,
)

PROTOCOL_VERSION = "ENTRY_ECONOMIC_EVALUATION_V2"
BASELINE_HASH_VERSION = "MATCHED_ELIGIBLE_BASELINE_SHA256_V2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/markup_retest_main_chinext_2020_2023_v1.yaml"),
    )
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers != 4:
        raise ValueError("economic evaluation is registered for four bounded workers")
    config = MarkupRetestConfig.load(args.config)
    if config.freeze_manifest.exists():
        raise ValueError("economic development evaluation must precede parameter freeze")
    ledger = TrialLedger(config.trial_ledger)
    entries = ledger.read_verified()
    protocol = _one(entries, "ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2")
    p0 = _passing_p0(entries)
    incident = _one(entries, "HOLDOUT_ACCESS_INCIDENT")
    if (
        incident.payload.get("holdout_outcomes_observed") is not False
        or incident.payload.get("used_for_parameter_selection_or_thresholds") is not False
    ):
        raise ValueError("holdout outcome access blocks development selection")
    exact_event = _one(entries, "ENTRY_ECONOMIC_EXACT_REPLAY_V2_COMPLETE")
    exact_manifest_path = Path(str(exact_event.payload["manifest_path"]))
    if _sha256_file(exact_manifest_path) != exact_event.payload["manifest_sha256"]:
        raise ValueError("exact replay manifest identity changed")
    exact = _read_object(exact_manifest_path)
    if (
        exact.get("status") != "COMPLETE"
        or exact.get("stage") != StrategyStage.DEVELOPMENT.value
        or exact.get("evaluation_years") != [2020, 2021, 2022]
        or exact.get("parameter_count") != 81
        or exact.get("holdout_accessed") is not False
    ):
        raise ValueError("exact replay is not the required 81-point development artifact")
    run_id = _digest(
        "|".join(
            (
                PROTOCOL_VERSION,
                str(protocol.payload["run_id"]),
                str(exact["exact_replay_snapshot_id"]),
                str(p0.payload["event_id"]),
                _sha256_file(Path(__file__)),
                _sha256_file(Path("src/cyq_game/strategy/economic_evaluation.py")),
                _sha256_file(Path("src/cyq_game/strategy/economic_selection.py")),
                _sha256_file(Path("src/cyq_game/strategy/fixed_horizon.py")),
            )
        )
    )
    root = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / f"entry_economic_evaluation_v2-{run_id[:12]}"
    )
    root.mkdir(parents=True, exist_ok=True)
    with root.with_suffix(".lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("entry economic evaluation is already running") from error
        return _run_locked(
            config=config,
            ledger=ledger,
            protocol=protocol,
            p0=p0,
            incident=incident,
            exact_event=exact_event,
            exact=exact,
            exact_manifest_path=exact_manifest_path,
            root=root,
            run_id=run_id,
            workers=args.workers,
        )


def _run_locked(
    *,
    config: MarkupRetestConfig,
    ledger: TrialLedger,
    protocol: LedgerEntry,
    p0: LedgerEntry,
    incident: LedgerEntry,
    exact_event: LedgerEntry,
    exact: Mapping[str, Any],
    exact_manifest_path: Path,
    root: Path,
    run_id: str,
    workers: int,
) -> int:
    final_manifest = root / "manifest.json"
    if final_manifest.is_file():
        existing = _read_object(final_manifest)
        if existing.get("run_id") != run_id or existing.get("status") != "COMPLETE":
            raise FileExistsError("existing economic manifest differs")
        completed = _append(
            ledger,
            "ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2_COMPLETE",
            _completion_payload(existing, final_manifest),
        )
        print(
            json.dumps(
                {**_brief(existing), "completion_ledger_sequence": completed.sequence},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    started_payload = {
        "event_id": _digest(f"{run_id}|STARTED"),
        "run_id": run_id,
        "protocol_version": PROTOCOL_VERSION,
        "economic_protocol_run_id": protocol.payload["run_id"],
        "exact_replay_snapshot_id": exact["exact_replay_snapshot_id"],
        "parameter_count": 81,
        "evaluation_years": [2020, 2021, 2022],
        "holdout_accessed": False,
        "global_physical_2023_access_incident": True,
        "holdout_outcomes_observed": False,
    }
    started = _append(ledger, "ENTRY_ECONOMIC_EVALUATION_V2_STARTED", started_payload)
    panel_manifest_path = Path(str(exact["panel_manifest"]))
    panel_files = _development_panel_files(panel_manifest_path)
    exact_rows = _load_exact_rows(exact_manifest_path.parent)
    preparation = _prepare_matched_events(
        root=root,
        run_id=run_id,
        exact_rows=exact_rows,
        panel_files=panel_files,
    )
    execution_files = tuple(
        config.assets.execution_file(year)
        for year in config.stage(StrategyStage.DEVELOPMENT).years()
    )
    config.assert_input_files(StrategyStage.DEVELOPMENT, execution_files)
    if max(_partition_year(path) for path in execution_files) > 2022:
        raise ValueError("fixed attribution attempted to include post-development execution")
    execution_input_inventory = _verify_development_execution_files(
        config, execution_files
    )
    market_dates = _market_trading_dates(
        execution_files,
        start=config.stage(StrategyStage.DEVELOPMENT).history_start,
        end=config.stage(StrategyStage.DEVELOPMENT).max_input_date,
    )
    outcomes = _run_fixed_event_buckets(
        root=root,
        run_id=run_id,
        event_rows=preparation["event_rows"],
        panel_files=panel_files,
        execution_files=execution_files,
        market_dates=market_dates,
        config=config,
        workers=workers,
    )
    results = _evaluate_parameters(
        exact_rows=exact_rows,
        enriched_signals=preparation["enriched_signals"],
        baseline_matches=preparation["baseline_matches"],
        outcomes=outcomes,
        exact=exact,
        config=config,
    )
    metrics_path = root / "parameter_metrics.json"
    decision_path = root / "robust_region_decision.json"
    _write_immutable_json(metrics_path, {"parameters": results["parameter_metrics"]})
    _write_immutable_json(decision_path, results["decision"])
    inventory = _inventory(
        (
            root / "preparation" / "enriched_signals.parquet",
            root / "preparation" / "baseline_matches.parquet",
            root / "preparation" / "fixed_events.parquet",
            root / "preparation" / "manifest.json",
            root / "fixed_progress.json",
            metrics_path,
            decision_path,
            *(root / "fixed_parts").rglob("*.parquet"),
            *(root / "fixed_parts").rglob("manifest.json"),
        ),
        root,
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "COMPLETE",
        "run_id": run_id,
        "protocol_version": PROTOCOL_VERSION,
        "economic_protocol_run_id": protocol.payload["run_id"],
        "config_path": str(config.path.resolve()),
        "config_sha256": config.sha256,
        "stage": StrategyStage.DEVELOPMENT.value,
        "evaluation_years": [2020, 2021, 2022],
        "maximum_physical_data_year_read": 2022,
        "classification": "WALK_FORWARD_DEVELOPMENT_EVIDENCE",
        "exact_replay_manifest": str(exact_manifest_path.resolve()),
        "exact_replay_manifest_sha256": exact_event.payload["manifest_sha256"],
        "exact_replay_snapshot_id": exact["exact_replay_snapshot_id"],
        "execution_input_inventory": execution_input_inventory,
        "p0_gate_event_id": p0.payload["event_id"],
        "started_ledger_sequence": started.sequence,
        "parameter_count": 81,
        "parameter_evaluation_count": len(results["parameter_metrics"]),
        "parameter_evaluation_coverage": len(results["parameter_metrics"]) / 81,
        "matched_baseline_hash_version": BASELINE_HASH_VERSION,
        "industry_capacity_policy": (
            "CAUSAL_INDUSTRY_ELSE_CONSERVATIVE_BOARD_FALLBACK_GROUP"
        ),
        "source_code_inventory": _inventory(
            (
                Path(__file__).resolve(),
                Path("src/cyq_game/strategy/economic_evaluation.py").resolve(),
                Path("src/cyq_game/strategy/economic_selection.py").resolve(),
                Path("src/cyq_game/strategy/fixed_horizon.py").resolve(),
            ),
            config.repo_root.resolve(),
        ),
        "fixed_horizon_target": "TWENTIETH_MARKET_SESSION_AFTER_FILLED_ENTRY",
        "fixed_horizon_exit_intent": "PRIOR_SESSION_CLOSE",
        "blocked_fixed_horizon_exit_persists": True,
        "terminal_decision": results["decision"]["decision"],
        "selected_parameter_id": results["decision"]["selected_parameter_id"],
        "selected_component": results["decision"]["selected_component"],
        "passing_parameter_ids": results["decision"]["passing_parameter_ids"],
        "inventory": inventory,
        "holdout_incident_event_id": incident.payload["event_id"],
        "holdout_accessed": False,
        "global_physical_2023_access_incident": True,
        "formal_2023_untouched_claim_allowed": False,
            "holdout_outcomes_observed": False,
        "holdout_used_for_parameter_selection_or_thresholds": False,
        "parameters_frozen": False,
        "created_at": datetime.now(UTC).isoformat(),
    }
    payload["economic_selection_snapshot_id"] = "entry-economic-selection-" + _digest(
        json.dumps(
            {key: value for key, value in payload.items() if key != "created_at"},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    _write_immutable_json(final_manifest, payload)
    completion = _completion_payload(payload, final_manifest)
    completed = _append(
        ledger, "ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2_COMPLETE", completion
    )
    print(
        json.dumps(
            {**_brief(payload), "completion_ledger_sequence": completed.sequence},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _load_exact_rows(root: Path) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {
        "signals": [],
        "trades": [],
        "open_exposures": [],
    }
    for bucket in range(32):
        part = root / "parts" / f"bucket={bucket:02d}"
        manifest = _read_object(part / "manifest.json")
        if manifest.get("status") != "COMPLETE" or manifest.get("bucket") != bucket:
            raise ValueError(f"exact replay bucket is incomplete: {bucket}")
        for name in result:
            path = part / f"{name}.parquet"
            expected = next(
                (
                    item
                    for item in manifest["inventory"]
                    if item["path"] == path.name
                ),
                None,
            )
            if expected is None or _sha256_file(path) != expected["sha256"]:
                raise ValueError(f"exact replay bucket inventory changed: {path}")
            table = pq.read_table(path)
            if table.num_rows and table.schema.names != ["empty"]:
                result[name].extend(table.to_pylist())
    return result


def _prepare_matched_events(
    *,
    root: Path,
    run_id: str,
    exact_rows: Mapping[str, list[dict[str, Any]]],
    panel_files: Sequence[Path],
) -> dict[str, list[dict[str, Any]]]:
    preparation = root / "preparation"
    manifest_path = preparation / "manifest.json"
    enriched_path = preparation / "enriched_signals.parquet"
    matches_path = preparation / "baseline_matches.parquet"
    events_path = preparation / "fixed_events.parquet"
    if manifest_path.is_file():
        manifest = _read_object(manifest_path)
        if manifest.get("run_id") != run_id or manifest.get("status") != "COMPLETE":
            raise FileExistsError("existing economic preparation differs")
        for raw in manifest["inventory"]:
            path = preparation / str(raw["path"])
            if _sha256_file(path) != raw["sha256"]:
                raise ValueError(f"economic preparation inventory changed: {path}")
        return {
            "enriched_signals": pq.read_table(enriched_path).to_pylist(),
            "baseline_matches": pq.read_table(matches_path).to_pylist(),
            "event_rows": pq.read_table(events_path).to_pylist(),
        }
    if preparation.exists():
        raise FileExistsError("economic preparation exists without complete manifest")
    evaluation_signals = [
        item for item in exact_rows["signals"] if item["is_evaluation_row"]
    ]
    enriched = _enrich_signals(evaluation_signals, panel_files)
    matches, baseline_rows = _matched_baseline_rows(enriched, panel_files)
    event_rows = _fixed_event_rows(enriched, baseline_rows)
    temporary = preparation.with_name(f".{preparation.name}.tmp-{os.getpid()}")
    temporary.mkdir(parents=True)
    _write_parquet(temporary / enriched_path.name, enriched)
    _write_parquet(temporary / matches_path.name, matches)
    _write_parquet(temporary / events_path.name, event_rows)
    inventory = _inventory(
        (
            temporary / enriched_path.name,
            temporary / matches_path.name,
            temporary / events_path.name,
        ),
        temporary,
    )
    (temporary / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "COMPLETE",
                "run_id": run_id,
                "exact_evaluation_signals": len(evaluation_signals),
                "enriched_signals": len(enriched),
                "filled_candidate_signals": sum(
                    item["entry_status"] == "FILLED" for item in enriched
                ),
                "baseline_matches": len(matches),
                "unique_fixed_events": len(event_rows),
                "baseline_hash_version": BASELINE_HASH_VERSION,
                "inventory": inventory,
                "holdout_accessed": False,
            },
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(preparation)
    return {
        "enriched_signals": enriched,
        "baseline_matches": matches,
        "event_rows": event_rows,
    }


def _enrich_signals(
    signals: Sequence[Mapping[str, Any]], panel_files: Sequence[Path]
) -> list[dict[str, Any]]:
    candidate = pa.table(
        {
            "signal_id": [str(item["signal_id"]) for item in signals],
            "parameter_id": [str(item["parameter_id"]) for item in signals],
            "symbol": [str(item["symbol"]) for item in signals],
            "trade_date": [date.fromisoformat(str(item["decision_at"])[:10]) for item in signals],
            "decision_at": [str(item["decision_at"]) for item in signals],
            "signal_available_at": [str(item["available_at"]) for item in signals],
            "signal_market_state": [str(item["market_state"]) for item in signals],
            "signal_sector_state": [str(item["sector_state"]) for item in signals],
            "entry_status": [str(item["entry_status"]) for item in signals],
            "entry_fill_at": [item.get("entry_fill_at") for item in signals],
            "entry_fill_price": [item.get("entry_fill_price") for item in signals],
            "entry_quantity": [int(item.get("entry_quantity") or 0) for item in signals],
            "entry_total_cash": [item.get("entry_total_cash") for item in signals],
        }
    )
    con = duckdb.connect()
    try:
        con.execute("SET threads = 1")
        con.register("candidate_signals", candidate)
        table = con.execute(
            f"""
            SELECT
                c.*,
                p.board,
                p.industry AS panel_industry,
                p.observed_industry,
                p.sector_fallback,
                p.market_state AS panel_market_state,
                p.sector_state AS panel_sector_state,
                p.strategy_eligible,
                p.research_hard_valid,
                p.decision_at AS panel_decision_at,
                p.available_at AS panel_available_at,
                p.daily_snapshot_id,
                p.feature_daily_snapshot_id,
                p.feature_minute_snapshot_id,
                p.corporate_action_snapshot_id,
                abs(hash(p.symbol) % 32)::INTEGER AS symbol_bucket
            FROM candidate_signals c
            JOIN read_parquet({_sql_list(panel_files)}, union_by_name=true) p
              ON p.symbol = c.symbol AND p.trade_date = c.trade_date
            WHERE p.is_evaluation_row
            ORDER BY c.parameter_id, c.signal_id
            """
        ).fetch_arrow_table()
    finally:
        con.close()
    rows = [dict(item) for item in table.to_pylist()]
    if len(rows) != len(signals):
        raise ValueError(
            f"exact signal causal join is not one-to-one: {len(rows)} != {len(signals)}"
        )
    signal_ids = [str(item["signal_id"]) for item in rows]
    if len(signal_ids) != len(set(signal_ids)):
        raise ValueError("exact signal causal join contains duplicate signal ids")
    for row in rows:
        if not row["strategy_eligible"] or not row["research_hard_valid"]:
            raise ValueError("exact signal does not map to a strategy-eligible panel row")
        if row["signal_market_state"] != row["panel_market_state"]:
            raise ValueError("exact signal market state differs from causal panel")
        if row["signal_sector_state"] != row["panel_sector_state"]:
            raise ValueError("exact signal sector state differs from causal panel")
        row["industry"] = capacity_industry(row)
    return rows


def _matched_baseline_rows(
    enriched: Sequence[Mapping[str, Any]], panel_files: Sequence[Path]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: defaultdict[tuple[str, int, str, str, str], list[Mapping[str, Any]]] = (
        defaultdict(list)
    )
    for row in enriched:
        if row["entry_status"] != "FILLED":
            continue
        key = (
            str(row["parameter_id"]),
            _date(row["trade_date"]).year,
            str(row["board"]),
            str(row["panel_market_state"]),
            str(row["panel_sector_state"]),
        )
        grouped[key].append(row)
    maximum: dict[tuple[int, str, str, str], int] = {}
    for (_, year, board, market, sector), rows in grouped.items():
        stratum = (year, board, market, sector)
        maximum[stratum] = max(maximum.get(stratum, 0), len(rows))
    request = pa.table(
        {
            "stratum_year": [item[0] for item in maximum],
            "board": [item[1] for item in maximum],
            "market_state": [item[2] for item in maximum],
            "sector_state": [item[3] for item in maximum],
            "maximum_needed": list(maximum.values()),
        }
    )
    con = duckdb.connect()
    try:
        con.execute("SET threads = 1")
        con.register("baseline_request", request)
        table = con.execute(
            f"""
            WITH eligible AS (
                SELECT
                    p.symbol,
                    p.trade_date,
                    year(p.trade_date)::INTEGER AS stratum_year,
                    p.board,
                    p.market_state,
                    p.sector_state,
                    coalesce(p.industry, p.observed_industry, 'UNKNOWN') AS industry,
                    p.decision_at,
                    p.available_at,
                    p.daily_snapshot_id,
                    p.feature_daily_snapshot_id,
                    p.feature_minute_snapshot_id,
                    p.corporate_action_snapshot_id,
                    abs(hash(p.symbol) % 32)::INTEGER AS symbol_bucket,
                    row_number() OVER (
                        PARTITION BY year(p.trade_date), p.board,
                                     p.market_state, p.sector_state
                        ORDER BY sha256(
                            p.symbol || '|' || cast(p.trade_date AS VARCHAR)
                            || '|{BASELINE_HASH_VERSION}'
                        ), p.symbol, p.trade_date
                    ) AS baseline_rank
                FROM read_parquet({_sql_list(panel_files)}, union_by_name=true) p
                JOIN baseline_request r
                  ON year(p.trade_date) = r.stratum_year
                 AND p.board = r.board
                 AND p.market_state = r.market_state
                 AND p.sector_state = r.sector_state
                WHERE p.is_evaluation_row AND p.strategy_eligible
            )
            SELECT e.*
            FROM eligible e
            JOIN baseline_request r USING (
                stratum_year, board, market_state, sector_state
            )
            WHERE e.baseline_rank <= r.maximum_needed
            ORDER BY stratum_year, board, market_state, sector_state, baseline_rank
            """
        ).fetch_arrow_table()
    finally:
        con.close()
    pool = [dict(item) for item in table.to_pylist()]
    by_stratum: defaultdict[tuple[int, str, str, str], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    for row in pool:
        pool_key = (
            int(row["stratum_year"]),
            str(row["board"]),
            str(row["market_state"]),
            str(row["sector_state"]),
        )
        by_stratum[pool_key].append(row)
    matches: list[dict[str, Any]] = []
    selected_pool: dict[str, dict[str, Any]] = {}
    for key, candidates in sorted(grouped.items()):
        parameter_id, year, board, market, sector = key
        stratum = (year, board, market, sector)
        baseline = by_stratum[stratum]
        if len(baseline) < len(candidates):
            raise ValueError(f"matched eligible baseline is too small for {key}")
        ordered_candidates = sorted(
            candidates,
            key=lambda row: (_digest(f"{parameter_id}|{row['signal_id']}|MATCH"), row["signal_id"]),
        )
        for candidate, baseline_row in zip(
            ordered_candidates, baseline[: len(ordered_candidates)], strict=True
        ):
            baseline_key = _event_key(
                str(baseline_row["symbol"]), _date(baseline_row["trade_date"])
            )
            candidate_key = _event_key(
                str(candidate["symbol"]), _date(candidate["trade_date"])
            )
            selected_pool[baseline_key] = baseline_row
            matches.append(
                {
                    "parameter_id": parameter_id,
                    "candidate_signal_id": str(candidate["signal_id"]),
                    "candidate_event_id": _digest(candidate_key),
                    "baseline_event_id": _digest(baseline_key),
                    "stratum_year": year,
                    "board": board,
                    "market_state": market,
                    "sector_state": sector,
                    "baseline_rank": int(baseline_row["baseline_rank"]),
                }
            )
    expected = sum(len(rows) for rows in grouped.values())
    if len(matches) != expected:
        raise RuntimeError("matched baseline did not cover every filled candidate signal")
    return matches, list(selected_pool.values())


def _fixed_event_rows(
    enriched: Sequence[Mapping[str, Any]], baseline_rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    events: dict[str, dict[str, Any]] = {}
    source_rows: Iterable[Mapping[str, Any]] = itertools.chain(
        (item for item in enriched if item["entry_status"] == "FILLED"),
        baseline_rows,
    )
    for row in source_rows:
        symbol = str(row["symbol"])
        trade_date = _date(row["trade_date"])
        key = _event_key(symbol, trade_date)
        event = {
            "event_id": _digest(key),
            "symbol": symbol,
            "trade_date": trade_date,
            "symbol_bucket": int(row["symbol_bucket"]),
        }
        existing = events.get(key)
        if existing is not None and existing != event:
            raise ValueError("fixed event identity collision")
        events[key] = event
    return sorted(events.values(), key=lambda row: (row["symbol_bucket"], row["symbol"], row["trade_date"]))


def _run_fixed_event_buckets(
    *,
    root: Path,
    run_id: str,
    event_rows: Sequence[Mapping[str, Any]],
    panel_files: Sequence[Path],
    execution_files: Sequence[Path],
    market_dates: Sequence[date],
    config: MarkupRetestConfig,
    workers: int,
) -> list[dict[str, Any]]:
    grouped: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in event_rows:
        grouped[int(event["symbol_bucket"])].append(dict(event))
    if set(grouped) != set(range(32)):
        raise ValueError("fixed attribution events do not cover every symbol bucket")
    parts = root / "fixed_parts"
    completed = {
        bucket
        for bucket in range(32)
        if _valid_fixed_part(parts / f"bucket={bucket:02d}", run_id, grouped[bucket])
    }
    _write_fixed_progress(root, run_id, completed)
    pending = [bucket for bucket in range(32) if bucket not in completed]
    if pending:
        arguments = [
            (
                bucket,
                tuple(grouped[bucket]),
                tuple(panel_files),
                tuple(execution_files),
                tuple(market_dates),
                config,
            )
            for bucket in pending
        ]
        with ProcessPoolExecutor(max_workers=workers, max_tasks_per_child=1) as executor:
            futures = {
                executor.submit(_fixed_bucket, argument): argument[0]
                for argument in arguments
            }
            for future in as_completed(futures):
                bucket = futures.pop(future)
                bucket_outcomes, wall_seconds = future.result()
                _write_fixed_part(
                    parts / f"bucket={bucket:02d}",
                    run_id=run_id,
                    bucket=bucket,
                    expected_events=grouped[bucket],
                    outcomes=bucket_outcomes,
                    wall_seconds=wall_seconds,
                )
                completed.add(bucket)
                _write_fixed_progress(root, run_id, completed)
                print(
                    json.dumps(
                        {
                            "fixed_bucket": bucket,
                            "completed_buckets": len(completed),
                            "total_buckets": 32,
                            "events": len(bucket_outcomes),
                            "wall_seconds": wall_seconds,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    if completed != set(range(32)):
        raise RuntimeError("fixed attribution ended without every bucket")
    all_outcomes: list[dict[str, Any]] = []
    for bucket in range(32):
        all_outcomes.extend(
            dict(item)
            for item in pq.read_table(
                parts / f"bucket={bucket:02d}" / "outcomes.parquet"
            ).to_pylist()
        )
    ids = [str(item["signal_id"]) for item in all_outcomes]
    expected_ids = [str(item["event_id"]) for item in event_rows]
    if len(ids) != len(set(ids)) or set(ids) != set(expected_ids):
        raise ValueError("fixed attribution outcomes do not exactly cover event requests")
    return all_outcomes


def _fixed_bucket(
    arguments: tuple[
        int,
        tuple[dict[str, Any], ...],
        tuple[Path, ...],
        tuple[Path, ...],
        tuple[date, ...],
        MarkupRetestConfig,
    ]
) -> tuple[list[dict[str, Any]], float]:
    bucket, events, panel_files, execution_files, market_dates, config = arguments
    started = time.perf_counter()
    symbols = tuple(sorted({str(item["symbol"]) for item in events}))
    event_groups = itertools.groupby(
        sorted(events, key=lambda item: (item["symbol"], _date(item["trade_date"]))),
        key=lambda item: str(item["symbol"]),
    )
    session_groups = iter(
        itertools.groupby(
            _stream_panel_sessions(panel_files, bucket, symbols),
            key=lambda item: item.symbol,
        )
    )
    execution_groups = iter(
        itertools.groupby(
            _stream_execution_windows(execution_files, (bucket,), symbols=symbols),
            key=lambda item: item.symbol,
        )
    )
    current_sessions = next(session_groups, None)
    current_windows = next(execution_groups, None)
    outcomes: list[dict[str, Any]] = []
    for symbol, symbol_events_iter in event_groups:
        while current_sessions is not None and current_sessions[0] < symbol:
            current_sessions = next(session_groups, None)
        while current_windows is not None and current_windows[0] < symbol:
            current_windows = next(execution_groups, None)
        if current_sessions is None or current_sessions[0] != symbol:
            raise ValueError(f"fixed attribution has no panel sessions for {symbol}")
        sessions = tuple(current_sessions[1])
        current_sessions = next(session_groups, None)
        if current_windows is not None and current_windows[0] == symbol:
            windows = tuple(current_windows[1])
            current_windows = next(execution_groups, None)
        else:
            windows = ()
        session_by_date = {item.trade_date: item for item in sessions}
        for event in symbol_events_iter:
            signal_date = _date(event["trade_date"])
            signal_session = session_by_date.get(signal_date)
            if signal_session is None:
                raise ValueError(
                    f"fixed attribution signal session is missing: {symbol} {signal_date}"
                )
            outcome = evaluate_fixed_horizon_trade(
                signal_id=str(event["event_id"]),
                symbol=symbol,
                signal_date=signal_date,
                signal_decision_at=signal_session.decision_at,
                signal_available_at=signal_session.available_at,
                signal_snapshot_ids=signal_session.snapshot_ids,
                sessions=sessions,
                windows=windows,
                market_trading_dates=market_dates,
                settings=config.execution,
                strategy_version=config.strategy_version,
                parameter_id="FIXED_HORIZON_ATTRIBUTION_V2",
                horizon_sessions=20,
            )
            outcomes.append(_fixed_outcome_row(outcome, bucket))
    return outcomes, time.perf_counter() - started


def _stream_panel_sessions(
    files: Sequence[Path], bucket: int, symbols: Sequence[str]
) -> Iterable[PanelSession]:
    if not symbols:
        return
    symbol_sql = ",".join(_sql_text(item) for item in symbols)
    con = duckdb.connect()
    try:
        con.execute("SET threads = 1")
        reader = con.execute(
            f"""
            SELECT
                symbol, trade_date, decision_at, available_at, close,
                share_multiplier, cash_per_share, daily_snapshot_id,
                feature_daily_snapshot_id, feature_minute_snapshot_id,
                corporate_action_snapshot_id
            FROM read_parquet({_sql_list(files)}, union_by_name=true)
            WHERE abs(hash(symbol) % 32) = {bucket}
              AND symbol IN ({symbol_sql})
              AND trade_date BETWEEN DATE '2020-01-02' AND DATE '2022-12-30'
            ORDER BY symbol, trade_date
            """
        ).fetch_record_batch(65_536)
        for batch in reader:
            names = batch.schema.names
            columns = [batch.column(index).to_pylist() for index in range(len(names))]
            for values in zip(*columns, strict=True):
                yield panel_session_from_record(dict(zip(names, values, strict=True)))
    finally:
        con.close()


def _fixed_outcome_row(outcome: FixedHorizonTrade, bucket: int) -> dict[str, Any]:
    row = asdict(outcome)
    row["signal_date"] = outcome.signal_date.isoformat()
    for field in ("entry_at", "exit_at"):
        value = row[field]
        row[field] = value.isoformat() if value is not None else None
    if outcome.scheduled_exit_date is not None:
        row["scheduled_exit_date"] = outcome.scheduled_exit_date.isoformat()
    row["reason_codes"] = list(outcome.reason_codes)
    row["snapshot_ids"] = list(outcome.snapshot_ids)
    row["symbol_bucket"] = bucket
    return row


def _write_fixed_part(
    target: Path,
    *,
    run_id: str,
    bucket: int,
    expected_events: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    wall_seconds: float,
) -> None:
    if target.exists():
        if _valid_fixed_part(target, run_id, expected_events):
            return
        raise FileExistsError(f"incomplete or mismatched fixed part: {target}")
    expected_ids = {str(item["event_id"]) for item in expected_events}
    outcome_ids = {str(item["signal_id"]) for item in outcomes}
    if len(outcomes) != len(outcome_ids) or outcome_ids != expected_ids:
        raise ValueError("fixed part does not exactly cover bucket events")
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    temporary.mkdir(parents=True)
    path = temporary / "outcomes.parquet"
    _write_parquet(path, outcomes)
    payload = {
        "schema_version": 1,
        "status": "COMPLETE",
        "run_id": run_id,
        "bucket": bucket,
        "events": len(expected_events),
        "outcomes": len(outcomes),
        "worker_wall_seconds": wall_seconds,
        "outcomes_sha256": _sha256_file(path),
        "holdout_accessed": False,
    }
    (temporary / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary.replace(target)


def _valid_fixed_part(
    target: Path,
    run_id: str,
    expected_events: Sequence[Mapping[str, Any]],
) -> bool:
    manifest_path = target / "manifest.json"
    outcome_path = target / "outcomes.parquet"
    if not manifest_path.is_file() or not outcome_path.is_file():
        return False
    payload = _read_object(manifest_path)
    if (
        payload.get("status") != "COMPLETE"
        or payload.get("run_id") != run_id
        or payload.get("events") != len(expected_events)
        or payload.get("outcomes") != len(expected_events)
        or payload.get("outcomes_sha256") != _sha256_file(outcome_path)
    ):
        return False
    ids = set(pq.read_table(outcome_path, columns=["signal_id"])["signal_id"].to_pylist())
    return ids == {str(item["event_id"]) for item in expected_events}


def _write_fixed_progress(root: Path, run_id: str, completed: set[int]) -> None:
    path = root / "fixed_progress.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "status": "COMPLETE" if len(completed) == 32 else "RUNNING",
                "run_id": run_id,
                "completed_buckets": sorted(completed),
                "completed_count": len(completed),
                "total_buckets": 32,
                "updated_at": datetime.now(UTC).isoformat(),
                "holdout_accessed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _evaluate_parameters(
    *,
    exact_rows: Mapping[str, list[dict[str, Any]]],
    enriched_signals: Sequence[Mapping[str, Any]],
    baseline_matches: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    exact: Mapping[str, Any],
    config: MarkupRetestConfig,
) -> dict[str, Any]:
    outcome_by_id = {str(item["signal_id"]): item for item in outcomes}
    enriched_by_id = {str(item["signal_id"]): item for item in enriched_signals}
    signal_groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    trade_groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    match_groups: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for signal in exact_rows["signals"]:
        if signal["is_evaluation_row"]:
            signal_groups[str(signal["parameter_id"])].append(signal)
    for trade in exact_rows["trades"]:
        if trade["is_evaluation_row"]:
            trade_groups[str(trade["parameter_id"])].append(trade)
    for match in baseline_matches:
        match_groups[str(match["parameter_id"])].append(match)
    parameters = tuple(
        StrategyParameters(**{key: float(value) for key, value in item.items()})
        for item in exact["parameters"]
    )
    expected_ids = {item.parameter_id for item in parameters}
    if not set(signal_groups).issubset(expected_ids) or not set(trade_groups).issubset(
        expected_ids
    ):
        raise ValueError("exact replay contains an unknown parameter id")
    for parameter_id in expected_ids:
        signal_groups.setdefault(parameter_id, [])
        trade_groups.setdefault(parameter_id, [])
    parameter_metrics: list[dict[str, Any]] = []
    assessments = []
    metrics_by_id: dict[str, dict[str, Any]] = {}
    for index, parameters_item in enumerate(parameters, start=1):
        parameter_id = parameters_item.parameter_id
        signals = signal_groups[parameter_id]
        trades = trade_groups[parameter_id]
        industry_by_signal: dict[str, str] = {}
        participation_by_signal: dict[str, float] = {}
        for signal in signals:
            if signal.get("entry_status") != "FILLED":
                continue
            signal_id = str(signal["signal_id"])
            enriched = enriched_by_id[signal_id]
            event_id = _digest(
                _event_key(str(signal["symbol"]), _date(enriched["trade_date"]))
            )
            outcome = outcome_by_id[event_id]
            _assert_same_entry(signal, outcome)
            participation = outcome.get("entry_participation")
            if participation is None:
                raise ValueError("filled exact signal has no five-minute participation")
            industry_by_signal[signal_id] = str(enriched["industry"])
            participation_by_signal[signal_id] = float(participation)
        replay = replay_economic_metrics(
            signals,
            trades,
            industry_by_signal=industry_by_signal,
            entry_participation_by_signal=participation_by_signal,
            parameter_id=parameter_id,
        )
        pair_rows: list[dict[str, Any]] = []
        incomplete_pairs = 0
        for match in match_groups[parameter_id]:
            candidate = outcome_by_id[str(match["candidate_event_id"])]
            baseline = outcome_by_id[str(match["baseline_event_id"])]
            if candidate["status"] != "FILLED" or baseline["status"] != "FILLED":
                incomplete_pairs += 1
                continue
            candidate_signal = enriched_by_id[str(match["candidate_signal_id"])]
            pair_rows.append(
                {
                    "candidate_signal_at": str(candidate_signal["decision_at"]),
                    "candidate_return_fraction": float(candidate["return_fraction"]),
                    "baseline_return_fraction": float(baseline["return_fraction"]),
                }
            )
        baseline_evidence = paired_weekly_difference_evidence(
            pair_rows,
            parameter_id=parameter_id,
        )
        combined = combined_gate_metrics(replay, baseline_evidence)
        combined.update(
            {
                "parameters": parameters_item.canonical(),
                "matched_baseline_requested": len(match_groups[parameter_id]),
                "matched_baseline_complete_pairs": len(pair_rows),
                "matched_baseline_incomplete_pairs": incomplete_pairs,
                "matched_baseline_complete_rate": (
                    len(pair_rows) / len(match_groups[parameter_id])
                    if match_groups[parameter_id]
                    else 0.0
                ),
            }
        )
        assessment = assess_candidate(parameter_id, combined)
        combined["economic_gate_status"] = assessment.status
        combined["economic_gate_reason_codes"] = list(assessment.reason_codes)
        parameter_metrics.append(combined)
        metrics_by_id[parameter_id] = combined
        assessments.append(assessment)
        print(
            json.dumps(
                {
                    "economic_parameter": index,
                    "total_parameters": 81,
                    "parameter_id": parameter_id,
                    "status": assessment.status,
                    "trades": combined["closed_trade_count"],
                    "baseline_pairs": len(pair_rows),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    if len(parameter_metrics) != 81:
        raise RuntimeError("economic evaluation did not produce 81 comparable results")
    grids = {
        name: tuple(float(value) for value in config.parameter_grids[name])
        for name in ENTRY_DIMENSIONS
    }
    decision = select_robust_region(
        parameters,
        assessments,
        metrics_by_id,
        grids,
    )
    decision_payload = asdict(decision)
    decision_payload["assessments"] = [asdict(item) for item in decision.assessments]
    return {
        "parameter_metrics": parameter_metrics,
        "decision": decision_payload,
    }


def _assert_same_entry(
    exact_signal: Mapping[str, Any], fixed_outcome: Mapping[str, Any]
) -> None:
    if fixed_outcome.get("entry_at") is None:
        raise ValueError("fixed attribution failed an entry filled by exact replay")
    if str(fixed_outcome["entry_at"]) != str(exact_signal["entry_fill_at"]):
        raise ValueError("fixed attribution entry time differs from exact replay")
    numeric = (
        ("entry_price", "entry_fill_price"),
        ("entry_cash", "entry_total_cash"),
    )
    for fixed_name, signal_name in numeric:
        if not math.isclose(
            float(fixed_outcome[fixed_name]),
            float(exact_signal[signal_name]),
            rel_tol=1.0e-12,
            abs_tol=1.0e-9,
        ):
            raise ValueError(f"fixed attribution {fixed_name} differs from exact replay")
    if int(fixed_outcome["entry_quantity"]) != int(exact_signal["entry_quantity"]):
        raise ValueError("fixed attribution entry quantity differs from exact replay")


def _development_panel_files(manifest_path: Path) -> tuple[Path, ...]:
    manifest = _read_object(manifest_path)
    if (
        manifest.get("status") != "COMPLETE"
        or manifest.get("stage") != StrategyStage.DEVELOPMENT.value
        or manifest.get("maximum_input_date") != "2022-12-30"
    ):
        raise ValueError("panel manifest is not development-only")
    files: list[Path] = []
    for raw in manifest["inventory"]:
        relative = Path(str(raw["path"]))
        year = _partition_year(relative)
        if year is None or year > 2022:
            raise ValueError(f"development panel inventory contains forbidden year: {relative}")
        if year < 2020:
            continue
        path = manifest_path.parent / relative
        if (
            not path.is_file()
            or path.stat().st_size != raw["size"]
            or _sha256_file(path) != raw["sha256"]
        ):
            raise ValueError(f"development panel inventory changed: {path}")
        files.append(path)
    if not files or {2020, 2021, 2022} != {_partition_year(path) for path in files}:
        raise ValueError("development economic panel must cover 2020-2022")
    return tuple(sorted(files))


def _verify_development_execution_files(
    config: MarkupRetestConfig, files: Sequence[Path]
) -> dict[str, Any]:
    registry = _read_object(config.registry_path)
    raw_assets = registry.get("assets")
    if isinstance(raw_assets, list):
        assets = {str(item["asset_id"]): item for item in raw_assets}
    elif isinstance(raw_assets, dict):
        assets = raw_assets
    else:
        raise ValueError("data asset registry has no asset mapping")
    asset = assets.get(config.assets.minute_asset_id)
    if not isinstance(asset, dict):
        raise ValueError("registered minute asset is missing")
    lineage = asset.get("lineage")
    if not isinstance(lineage, dict):
        raise ValueError("registered minute asset has no lineage mapping")
    manifest_path = Path(str(lineage["manifest_path"]))
    expected_manifest_sha = str(lineage["manifest_sha256"])
    if _sha256_file(manifest_path) != expected_manifest_sha:
        raise ValueError("registered minute asset manifest identity changed")
    manifest = _read_object(manifest_path)
    root = Path(str(manifest["root"])).resolve()
    if root != config.assets.minute_root.resolve():
        raise ValueError("registered minute asset manifest root changed")
    inventory = {
        str(item["path"]): item for item in manifest["files"] if isinstance(item, dict)
    }
    verified = []
    for path in files:
        if _partition_year(path) > 2022:
            raise ValueError("development execution verifier refuses post-2022 data")
        relative = str(path.resolve().relative_to(root))
        raw = inventory.get(relative)
        if raw is None:
            raise ValueError(f"execution file is absent from registered inventory: {path}")
        if (
            not path.is_file()
            or path.stat().st_size != raw["size"]
            or _sha256_file(path) != raw["sha256"]
        ):
            raise ValueError(f"registered development execution file changed: {path}")
        verified.append(
            {
                "path": str(path.resolve()),
                "size": path.stat().st_size,
                "sha256": raw["sha256"],
            }
        )
    return {
        "asset_id": config.assets.minute_asset_id,
        "registered_manifest": str(manifest_path.resolve()),
        "registered_manifest_sha256": expected_manifest_sha,
        "development_files": verified,
        "maximum_partition_year_read": 2022,
    }


def _write_parquet(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"economic parquet cannot be empty: {path}")
    table = pa.Table.from_pylist([dict(row) for row in rows])
    pq.write_table(table, path, compression="zstd")


def _inventory(
    paths: Iterable[Path], relative_to: Path
) -> list[dict[str, Any]]:
    records = []
    for path in sorted(set(paths)):
        records.append(
            {
                "path": str(path.relative_to(relative_to)),
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return records


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != raw:
            raise FileExistsError(f"immutable economic artifact differs: {path}")
        return
    path.write_text(raw, encoding="utf-8")


def _one(entries: Sequence[LedgerEntry], event_type: str) -> LedgerEntry:
    found = [item for item in entries if item.event_type == event_type]
    if len(found) != 1:
        raise ValueError(f"expected exactly one {event_type}")
    return found[0]


def _passing_p0(entries: Sequence[LedgerEntry]) -> LedgerEntry:
    found = [
        item
        for item in entries
        if item.event_type == "PIT_B_TRUE_OOS_CALIBRATION_GATE_COMPLETE"
        and item.payload.get("status") == "PASS"
    ]
    if len(found) != 1:
        raise ValueError("expected exactly one passing true-OOS P0 gate")
    return found[0]


def _append(
    ledger: TrialLedger, event_type: str, payload: Mapping[str, Any]
) -> LedgerEntry:
    for entry in ledger.read_verified():
        if entry.payload.get("event_id") != payload["event_id"]:
            continue
        if entry.event_type != event_type or entry.payload != payload:
            raise ValueError("economic trial ledger event collision")
        return entry
    return ledger.append(event_type, payload)


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return payload


def _partition_year(path: Path) -> int:
    for part in path.parts:
        for prefix in ("partition_year=", "year="):
            if part.startswith(prefix):
                value = part.removeprefix(prefix)
                if value.isdigit():
                    return int(value)
    raise ValueError(f"path has no explicit year partition: {path}")


def _event_key(symbol: str, trade_date: date) -> str:
    return f"FIXED_HORIZON_EVENT_V2|{symbol}|{trade_date.isoformat()}"


def _date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_list(paths: Sequence[Path]) -> str:
    return "[" + ",".join(_sql_text(str(path)) for path in paths) + "]"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _brief(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": payload["status"],
        "run_id": payload["run_id"],
        "parameter_evaluation_count": payload["parameter_evaluation_count"],
        "terminal_decision": payload["terminal_decision"],
        "selected_parameter_id": payload["selected_parameter_id"],
        "selected_component_size": len(payload["selected_component"]),
        "holdout_accessed": payload["holdout_accessed"],
        "global_physical_2023_access_incident": payload[
            "global_physical_2023_access_incident"
        ],
        "holdout_outcomes_observed": payload["holdout_outcomes_observed"],
    }


def _completion_payload(
    payload: Mapping[str, Any], manifest_path: Path
) -> dict[str, Any]:
    return {
        "event_id": _digest(
            f"{payload['run_id']}|{payload['economic_selection_snapshot_id']}|COMPLETE"
        ),
        "run_id": payload["run_id"],
        "protocol_version": "ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2",
        "economic_selection_snapshot_id": payload["economic_selection_snapshot_id"],
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": _sha256_file(manifest_path),
        "parameter_count": 81,
        "parameter_evaluation_count": payload["parameter_evaluation_count"],
        "terminal_decision": payload["terminal_decision"],
        "selected_parameter_id": payload["selected_parameter_id"],
        "selected_component": payload["selected_component"],
        "holdout_accessed": False,
        "global_physical_2023_access_incident": True,
        "holdout_outcomes_observed": False,
        "holdout_used_for_parameter_selection_or_thresholds": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
