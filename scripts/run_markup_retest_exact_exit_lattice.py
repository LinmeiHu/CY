#!/usr/bin/env python3
"""Run the exact 2x9 development exit lattice in one shared panel pass."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean, median
from typing import Any

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cyq_game.strategy.exact_replay import (
    ExactReplayResult,
    evaluate_exact_parameter_lattice_files,
)
from cyq_game.strategy.ledger import TrialLedger
from cyq_game.strategy.markup_retest import (
    MarkupRetestConfig,
    StrategyParameters,
    StrategyStage,
)
from cyq_game.strategy.research import exit_parameter_grid

PROTOCOL_VERSION = "EXACT_EXIT_SELECTION_V2_ACTION_FAIL_CLOSED"
REQUIRED_ENTRY_FILL_RATE = 0.95
REQUIRED_CLOSED_TRADE_RATE = 0.95
TRIM_FRACTION = 0.05


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = MarkupRetestConfig.load(args.config)
    entry_path = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "entry_frequency.json"
    )
    entry = _load_entry_shortlist(entry_path, config)
    entries = tuple(
        StrategyParameters(**{key: float(value) for key, value in row.items()})
        for row in entry["candidate_parameters"]
    )
    parameters = tuple(
        item for candidate in entries for item in exit_parameter_grid(config, candidate)
    )
    if len(parameters) != 18 or len({item.parameter_id for item in parameters}) != 18:
        raise ValueError("the frozen entry shortlist must expand to exactly 18 exit trials")

    protocol_run_id = _persist_protocol(
        config,
        panel_snapshot_id=str(entry["panel_snapshot_id"]),
        entry_lattice_snapshot_id=str(entry["entry_lattice_snapshot_id"]),
        parameters=parameters,
    )
    panel_manifest = Path(str(entry["panel_manifest"]))
    panel_files = tuple(sorted(panel_manifest.parent.rglob("*.parquet")))
    prior_target = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / f"exact_exit_lattice-{str(entry['entry_lattice_snapshot_id'])[14:26]}"
    )
    mismatch_symbols = _action_mismatch_symbols(panel_files)
    if prior_target.joinpath("manifest.json").is_file():
        prior_result, prior_payload = _load_result(prior_target, parameters)
        _persist_prior_invalidation(prior_payload, config)
        repaired = evaluate_exact_parameter_lattice_files(
            panel_files,
            config,
            StrategyStage.DEVELOPMENT,
            parameters,
            panel_snapshot_id=str(entry["panel_snapshot_id"]),
            threads=args.threads,
            symbols=mismatch_symbols,
        )
        result = _merge_repair(prior_result, repaired, mismatch_symbols)
        replay_lineage = {
            "mode": "TARGETED_ACTION_COORDINATE_REPAIR",
            "prior_manifest": str(prior_target / "manifest.json"),
            "prior_exact_exit_lattice_snapshot_id": prior_payload[
                "exact_exit_lattice_snapshot_id"
            ],
            "repaired_symbols": len(mismatch_symbols),
            "repaired_symbol_list": list(mismatch_symbols),
            "repair_input_rows": repaired.input_rows,
            "repair_evaluation_rows": repaired.evaluation_rows,
            "full_market_rescan": False,
        }
    else:
        result = evaluate_exact_parameter_lattice_files(
            panel_files,
            config,
            StrategyStage.DEVELOPMENT,
            parameters,
            panel_snapshot_id=str(entry["panel_snapshot_id"]),
            threads=args.threads,
        )
        replay_lineage = {
            "mode": "FULL_SINGLE_PASS",
            "repaired_symbols": len(mismatch_symbols),
            "repaired_symbol_list": list(mismatch_symbols),
            "full_market_rescan": True,
        }
    payload = _summarize(
        result,
        config,
        entry=entry,
        protocol_run_id=protocol_run_id,
        replay_lineage=replay_lineage,
    )
    target = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / (
            f"exact_exit_lattice-{str(entry['entry_lattice_snapshot_id'])[14:26]}"
            "-coordinate-v2"
        )
    )
    _write_artifacts(target, result, payload)
    _persist_trials(payload, config, protocol_run_id=protocol_run_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _load_entry_shortlist(path: Path, config: MarkupRetestConfig) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"entry shortlist is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("entry shortlist must be a JSON object")
    if payload.get("status") != "PASS":
        raise ValueError("entry shortlist did not pass its frequency gate")
    if payload.get("config_sha256") != config.sha256:
        raise ValueError("entry shortlist config hash mismatch")
    candidates = payload.get("candidate_parameters")
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise ValueError("exact exit lattice requires exactly two entry candidates")
    return payload


def _protocol_payload(
    config: MarkupRetestConfig,
    *,
    panel_snapshot_id: str,
    entry_lattice_snapshot_id: str,
    parameters: Sequence[StrategyParameters],
) -> dict[str, Any]:
    run_id = hashlib.sha256(
        (
            f"{PROTOCOL_VERSION}|{config.sha256}|{panel_snapshot_id}|"
            f"{entry_lattice_snapshot_id}"
        ).encode()
    ).hexdigest()
    return {
        "event_id": hashlib.sha256(f"{run_id}|PROTOCOL".encode()).hexdigest(),
        "run_id": run_id,
        "protocol_version": PROTOCOL_VERSION,
        "strategy_version": config.strategy_version,
        "config_sha256": config.sha256,
        "panel_snapshot_id": panel_snapshot_id,
        "entry_lattice_snapshot_id": entry_lattice_snapshot_id,
        "parameter_ids": [item.parameter_id for item in parameters],
        "evaluation_years": [2020, 2021, 2022],
        "execution_scope": "RESEARCH_EVENT_STUDY",
        "entry_fill_rate_min": REQUIRED_ENTRY_FILL_RATE,
        "closed_trade_rate_min": REQUIRED_CLOSED_TRADE_RATE,
        "return_gates": {
            "overall_mean_net_return": ">0",
            "each_year_mean_net_return": ">0",
        },
        "robustness_gate": "AT_LEAST_ONE_ADJACENT_EXIT_GRID_POINT_PASSES",
        "selection_order": [
            "worst_annual_mean_net_return_desc",
            "trimmed_5pct_mean_net_return_desc",
            "overall_mean_net_return_desc",
            "event_sequence_max_drawdown_asc",
            "parameter_id_asc",
        ],
        "no_trade_rule": "NO_TRADE_IF_NO_ROBUST_EXIT_COMBINATION_PASSES",
        "holdout_accessed": False,
        "action_coordinate_gate": (
            "BLOCK_NEW_RISK_FROM_FIRST_PREVIOUS_CLOSE_TO_PRECLOSE_MISMATCH"
        ),
    }


def _persist_protocol(
    config: MarkupRetestConfig,
    *,
    panel_snapshot_id: str,
    entry_lattice_snapshot_id: str,
    parameters: Sequence[StrategyParameters],
) -> str:
    payload = _protocol_payload(
        config,
        panel_snapshot_id=panel_snapshot_id,
        entry_lattice_snapshot_id=entry_lattice_snapshot_id,
        parameters=parameters,
    )
    _append_idempotent(TrialLedger(config.trial_ledger), "EXIT_SELECTION_PROTOCOL", payload)
    return str(payload["run_id"])


def _summarize(
    result: ExactReplayResult,
    config: MarkupRetestConfig,
    *,
    entry: Mapping[str, Any],
    protocol_run_id: str,
    replay_lineage: Mapping[str, Any],
) -> dict[str, Any]:
    trials = [
        _trial_metrics(parameters, result)
        for parameters in result.parameters
    ]
    by_id = {str(trial["parameter_id"]): trial for trial in trials}
    parameter_by_id = {item.parameter_id: item for item in result.parameters}
    for trial in trials:
        parameters = parameter_by_id[str(trial["parameter_id"])]
        neighbors = [
            other.parameter_id
            for other in result.parameters
            if _exit_neighbor(parameters, other, config)
        ]
        passing_neighbors = [
            item for item in neighbors if bool(by_id[item]["base_gate_pass"])
        ]
        trial["adjacent_parameter_ids"] = neighbors
        trial["passing_adjacent_parameter_ids"] = passing_neighbors
        trial["robustness_gate_pass"] = bool(
            trial["base_gate_pass"] and passing_neighbors
        )
        reasons = list(trial["reason_codes"])
        if trial["base_gate_pass"] and not passing_neighbors:
            reasons.append("NO_ADJACENT_EXIT_GRID_POINT_PASSES")
        trial["reason_codes"] = reasons

    passing = [trial for trial in trials if trial["robustness_gate_pass"]]
    passing.sort(key=_selection_key)
    selected_id = str(passing[0]["parameter_id"]) if passing else None
    decision = "EXIT_CANDIDATE" if selected_id is not None else "NO_TRADE"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "PASS",
        "decision": decision,
        "reason_codes": (
            [] if selected_id is not None else ["NO_ROBUST_EXIT_COMBINATION_PASSES"]
        ),
        "strategy_version": config.strategy_version,
        "config_path": str(config.path),
        "config_sha256": config.sha256,
        "stage": StrategyStage.DEVELOPMENT.value,
        "evaluation_years": [2020, 2021, 2022],
        "holdout_accessed": False,
        "panel_snapshot_id": entry["panel_snapshot_id"],
        "panel_manifest": entry["panel_manifest"],
        "entry_lattice_snapshot_id": entry["entry_lattice_snapshot_id"],
        "protocol_run_id": protocol_run_id,
        "protocol_version": PROTOCOL_VERSION,
        "replay_lineage": dict(replay_lineage),
        "panel_passes": result.panel_passes,
        "input_rows": result.input_rows,
        "evaluation_rows": result.evaluation_rows,
        "parameter_trials": len(trials),
        "signals": len(result.signals),
        "trades": len(result.trades),
        "open_exposures": len(result.open_exposures),
        "selected_parameter_id": selected_id,
        "selected_parameters": (
            parameter_by_id[selected_id].canonical() if selected_id is not None else None
        ),
        "trials": trials,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    payload["exact_exit_lattice_snapshot_id"] = "exact-exit-lattice-" + hashlib.sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key != "generated_at"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return payload


def _trial_metrics(
    parameters: StrategyParameters,
    result: ExactReplayResult,
) -> dict[str, Any]:
    signals = [
        row
        for row in result.signals
        if row["parameter_id"] == parameters.parameter_id
        and bool(row["is_evaluation_row"])
    ]
    filled = [row for row in signals if row["entry_status"] == "FILLED"]
    trades = [
        row
        for row in result.trades
        if row["parameter_id"] == parameters.parameter_id
        and bool(row["is_evaluation_row"])
    ]
    open_exposures = [
        row
        for row in result.open_exposures
        if row["parameter_id"] == parameters.parameter_id
        and bool(row["is_evaluation_row"])
    ]
    returns = [float(row["return_fraction"]) for row in trades]
    annual: dict[str, dict[str, Any]] = {}
    for year in (2020, 2021, 2022):
        annual_signals = [row for row in signals if _year(row["decision_at"]) == year]
        annual_filled = [row for row in filled if _year(row["decision_at"]) == year]
        annual_trades = [row for row in trades if _year(row["signal_at"]) == year]
        annual_returns = [float(row["return_fraction"]) for row in annual_trades]
        annual[str(year)] = {
            "signals": len(annual_signals),
            "filled_entries": len(annual_filled),
            "closed_trades": len(annual_trades),
            "mean_net_return_fraction": _mean_or_none(annual_returns),
            "median_net_return_fraction": _median_or_none(annual_returns),
            "win_rate": _mean_or_none([float(value > 0) for value in annual_returns]),
        }
    fill_rate = len(filled) / len(signals) if signals else 0.0
    closed_rate = len(trades) / len(filled) if filled else 0.0
    mean_return = _mean_or_none(returns)
    annual_means = [annual[str(year)]["mean_net_return_fraction"] for year in (2020, 2021, 2022)]
    reasons: list[str] = []
    if fill_rate < REQUIRED_ENTRY_FILL_RATE:
        reasons.append("ENTRY_FILL_RATE_BELOW_PROTOCOL_MINIMUM")
    if closed_rate < REQUIRED_CLOSED_TRADE_RATE:
        reasons.append("CLOSED_TRADE_RATE_BELOW_PROTOCOL_MINIMUM")
    if mean_return is None or mean_return <= 0:
        reasons.append("OVERALL_MEAN_NET_RETURN_NOT_POSITIVE")
    if any(value is None or value <= 0 for value in annual_means):
        reasons.append("ANNUAL_MEAN_NET_RETURN_NOT_POSITIVE")
    return {
        "parameter_id": parameters.parameter_id,
        "parameters": parameters.canonical(),
        "signals": len(signals),
        "entry_status_counts": dict(Counter(str(row["entry_status"]) for row in signals)),
        "filled_entries": len(filled),
        "entry_fill_rate": fill_rate,
        "closed_trades": len(trades),
        "closed_trade_rate": closed_rate,
        "open_exposures": len(open_exposures),
        "mean_net_return_fraction": mean_return,
        "median_net_return_fraction": _median_or_none(returns),
        "trimmed_5pct_mean_net_return_fraction": _trimmed_mean(returns),
        "win_rate": _mean_or_none([float(value > 0) for value in returns]),
        "total_net_pnl": sum(float(row["net_pnl"]) for row in trades),
        "total_blocked_tail_loss": sum(
            float(row["blocked_tail_loss"]) for row in trades
        ),
        "event_sequence_max_drawdown_fraction": _event_sequence_drawdown(trades),
        "exit_reason_counts": dict(Counter(str(row["exit_reason"]) for row in trades)),
        "annual": annual,
        "worst_annual_mean_net_return_fraction": (
            min(float(value) for value in annual_means if value is not None)
            if all(value is not None for value in annual_means)
            else None
        ),
        "base_gate_pass": not reasons,
        "reason_codes": reasons,
    }


def _exit_neighbor(
    left: StrategyParameters,
    right: StrategyParameters,
    config: MarkupRetestConfig,
) -> bool:
    entry_names = (
        "setup_score_min",
        "breakout_buffer_atr",
        "max_retest_depth_atr",
        "min_cost_migration_atr",
    )
    if any(getattr(left, name) != getattr(right, name) for name in entry_names):
        return False
    distances = []
    for name in ("distribution_score_min", "protective_stop_atr"):
        grid = config.parameter_grids[name]
        distances.append(abs(grid.index(getattr(left, name)) - grid.index(getattr(right, name))))
    return sum(distances) == 1


def _selection_key(trial: Mapping[str, Any]) -> tuple[float, float, float, float, str]:
    return (
        -float(trial["worst_annual_mean_net_return_fraction"]),
        -float(trial["trimmed_5pct_mean_net_return_fraction"]),
        -float(trial["mean_net_return_fraction"]),
        abs(float(trial["event_sequence_max_drawdown_fraction"])),
        str(trial["parameter_id"]),
    )


def _event_sequence_drawdown(trades: Sequence[Mapping[str, Any]]) -> float:
    ordered = sorted(trades, key=lambda row: (str(row["exit_at"]), str(row["signal_id"])))
    nav = 1.0
    peak = 1.0
    drawdown = 0.0
    for row in ordered:
        nav *= 1.0 + float(row["return_fraction"])
        peak = max(peak, nav)
        drawdown = min(drawdown, nav / peak - 1.0)
    return drawdown


def _trimmed_mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    trim = math.floor(len(ordered) * TRIM_FRACTION)
    kept = ordered[trim : len(ordered) - trim] if trim else ordered
    return fmean(kept)


def _mean_or_none(values: Sequence[float]) -> float | None:
    return fmean(values) if values else None


def _median_or_none(values: Sequence[float]) -> float | None:
    return median(values) if values else None


def _year(value: object) -> int:
    return int(str(value)[:4])


def _write_artifacts(
    target: Path,
    result: ExactReplayResult,
    payload: dict[str, Any],
) -> None:
    if target.exists():
        manifest = target / "manifest.json"
        if manifest.is_file():
            prior = json.loads(manifest.read_text(encoding="utf-8"))
            if prior.get("exact_exit_lattice_snapshot_id") == payload.get(
                "exact_exit_lattice_snapshot_id"
            ):
                return
        raise FileExistsError(f"exact exit target already exists and differs: {target}")
    temp = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    temp.mkdir(parents=True)
    inventory: list[dict[str, Any]] = []
    for name, rows in (
        ("signals.parquet", result.signals),
        ("trades.parquet", result.trades),
        ("open_exposures.parquet", result.open_exposures),
    ):
        path = temp / name
        table = pa.Table.from_pylist(list(rows)) if rows else pa.table({"empty": []})
        pq.write_table(table, path, compression="zstd")
        inventory.append(
            {
                "path": name,
                "rows": table.num_rows,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    payload["inventory"] = inventory
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    (temp / "manifest.json").write_text(rendered, encoding="utf-8")
    temp.replace(target)


def _persist_trials(
    payload: Mapping[str, Any],
    config: MarkupRetestConfig,
    *,
    protocol_run_id: str,
) -> None:
    ledger = TrialLedger(config.trial_ledger)
    snapshot_id = str(payload["exact_exit_lattice_snapshot_id"])
    for raw_trial in payload["trials"]:
        trial = dict(raw_trial)
        parameter_id = str(trial["parameter_id"])
        event = {
            "event_id": hashlib.sha256(
                f"{protocol_run_id}|{snapshot_id}|{parameter_id}".encode()
            ).hexdigest(),
            "run_id": protocol_run_id,
            "exact_exit_lattice_snapshot_id": snapshot_id,
            "config_sha256": config.sha256,
            "holdout_accessed": False,
            **trial,
        }
        _append_idempotent(ledger, "EXACT_EXIT_TRIAL", event)
    decision = {
        "event_id": hashlib.sha256(
            f"{protocol_run_id}|{snapshot_id}|DECISION".encode()
        ).hexdigest(),
        "run_id": protocol_run_id,
        "exact_exit_lattice_snapshot_id": snapshot_id,
        "config_sha256": config.sha256,
        "decision": payload["decision"],
        "selected_parameter_id": payload["selected_parameter_id"],
        "selected_parameters": payload["selected_parameters"],
        "reason_codes": payload["reason_codes"],
        "holdout_accessed": False,
    }
    _append_idempotent(ledger, "EXACT_EXIT_DECISION", decision)


def _append_idempotent(
    ledger: TrialLedger,
    event_type: str,
    payload: Mapping[str, Any],
) -> None:
    event_id = str(payload["event_id"])
    for entry in ledger.read_verified():
        if entry.payload.get("event_id") != event_id:
            continue
        if entry.event_type != event_type or entry.payload != payload:
            raise ValueError(f"trial ledger event collision: {event_id}")
        return
    ledger.append(event_type, payload)


def _action_mismatch_symbols(files: Sequence[Path]) -> tuple[str, ...]:
    con = duckdb.connect()
    try:
        rows = con.execute(
            """
            WITH ordered AS (
                SELECT *, lag(close) OVER (
                    PARTITION BY symbol ORDER BY trade_date
                ) AS previous_close
                FROM read_parquet(?, union_by_name=true)
            ), actions AS (
                SELECT *,
                    (previous_close - coalesce(cash_per_share, 0.0))
                    / coalesce(share_multiplier, 1.0) AS expected_preclose
                FROM ordered
                WHERE coalesce(share_multiplier, 1.0) <> 1.0
                   OR coalesce(cash_per_share, 0.0) <> 0.0
            )
            SELECT DISTINCT symbol
            FROM actions
            WHERE previous_close IS NOT NULL
              AND preclose IS NOT NULL
              AND (
                    coalesce(share_multiplier, 1.0) <= 0
                 OR previous_close <= coalesce(cash_per_share, 0.0)
                 OR abs(preclose - expected_preclose)
                    > greatest(0.02, preclose * 0.001)
              )
            ORDER BY symbol
            """,
            [[str(path) for path in files]],
        ).fetchall()
    finally:
        con.close()
    result = tuple(str(row[0]) for row in rows)
    if not result:
        raise ValueError("action coordinate repair expected at least one failed symbol")
    return result


def _load_result(
    target: Path,
    parameters: Sequence[StrategyParameters],
) -> tuple[ExactReplayResult, dict[str, Any]]:
    manifest = target / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    rows: dict[str, tuple[dict[str, Any], ...]] = {}
    for name in ("signals", "trades", "open_exposures"):
        rows[name] = tuple(
            pq.read_table(target / f"{name}.parquet").to_pylist()
        )
    return (
        ExactReplayResult(
            parameters=tuple(parameters),
            input_rows=int(payload["input_rows"]),
            evaluation_rows=int(payload["evaluation_rows"]),
            panel_passes=int(payload["panel_passes"]),
            signals=rows["signals"],
            trades=rows["trades"],
            open_exposures=rows["open_exposures"],
        ),
        payload,
    )


def _merge_repair(
    prior: ExactReplayResult,
    repaired: ExactReplayResult,
    symbols: Sequence[str],
) -> ExactReplayResult:
    affected = set(symbols)

    def merged(
        prior_rows: Sequence[dict[str, Any]],
        repair_rows: Sequence[dict[str, Any]],
        date_field: str,
    ) -> tuple[dict[str, Any], ...]:
        return tuple(
            sorted(
                (
                    *(row for row in prior_rows if str(row["symbol"]) not in affected),
                    *repair_rows,
                ),
                key=lambda row: (
                    str(row["parameter_id"]),
                    str(row["symbol"]),
                    str(row[date_field]),
                ),
            )
        )

    return ExactReplayResult(
        parameters=prior.parameters,
        input_rows=prior.input_rows,
        evaluation_rows=prior.evaluation_rows,
        panel_passes=prior.panel_passes,
        signals=merged(prior.signals, repaired.signals, "decision_at"),
        trades=merged(prior.trades, repaired.trades, "signal_at"),
        open_exposures=merged(
            prior.open_exposures,
            repaired.open_exposures,
            "signal_at",
        ),
    )


def _persist_prior_invalidation(
    prior: Mapping[str, Any],
    config: MarkupRetestConfig,
) -> None:
    snapshot_id = str(prior["exact_exit_lattice_snapshot_id"])
    payload = {
        "event_id": hashlib.sha256(
            f"{snapshot_id}|ACTION_COORDINATE_INVALIDATION_V1".encode()
        ).hexdigest(),
        "invalidated_exact_exit_lattice_snapshot_id": snapshot_id,
        "config_sha256": config.sha256,
        "reason_codes": [
            "UNRESOLVED_ACTION_PRICE_COORDINATE_WAS_NOT_FAILED_CLOSED",
            "POSITION_QUANTITY_COULD_BE_MULTIPLIED_WITHOUT_REFERENCE_PRICE_RESET",
        ],
        "replacement_protocol_version": PROTOCOL_VERSION,
        "holdout_accessed": False,
    }
    _append_idempotent(
        TrialLedger(config.trial_ledger),
        "EXACT_EXIT_RESULT_INVALIDATED",
        payload,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
