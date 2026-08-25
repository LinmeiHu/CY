#!/usr/bin/env python3
"""Exact one-stock MARKUP_RETEST lifecycle and five-minute execution replay."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import duckdb

from cyq_game.strategy.chip_lineage import PersistedChipLineageResolver
from cyq_game.strategy.execution import (
    EntryExecutionStatus,
    ExecutionScope,
    ExecutionWindow,
    ExitIntent,
    execute_entry,
    execute_exit,
)
from cyq_game.strategy.markup_retest import (
    LifecycleMachine,
    LifecycleMemory,
    MarkupRetestConfig,
    StrategyParameters,
)
from cyq_game.strategy.signals import observation_from_record

CN_TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class Position:
    signal_id: str
    signal_at: datetime
    entry_at: datetime
    entry_price: float
    entry_cash: float
    quantity: int
    accumulation_started_at: date
    breakout_at: date
    anchor_retention_lower: float
    setup_score: float
    close_to_p90_atr: float
    momentum_20: float | None
    dividends: float = 0.0


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=CN_TZ) if value.tzinfo is None else value


def _records(path: Path, symbol: str) -> list[dict[str, Any]]:
    con = duckdb.connect()
    source = str(path / "**" / "*.parquet") if path.is_dir() else str(path)
    query = con.execute(
        f"SELECT * FROM read_parquet('{source}', hive_partitioning=true) "
        "WHERE symbol = ? ORDER BY trade_date",
        [symbol],
    )
    description = query.description
    if description is None:
        raise RuntimeError("panel query returned no schema")
    columns = [item[0] for item in description]
    return [dict(zip(columns, row, strict=True)) for row in query.fetchall()]


def _windows(config: MarkupRetestConfig, symbol: str) -> tuple[ExecutionWindow, ...]:
    files = [str(config.assets.execution_file(year)) for year in range(2020, 2027)]
    con = duckdb.connect()
    query = con.execute(
        f"""
        SELECT * FROM read_parquet({files})
        WHERE symbol = ?
        ORDER BY trade_date, window_index
        """,
        [symbol],
    )
    description = query.description
    if description is None:
        raise RuntimeError("execution query returned no schema")
    columns = [item[0] for item in description]
    result: list[ExecutionWindow] = []
    for values in query.fetchall():
        row = dict(zip(columns, values, strict=True))
        result.append(
            ExecutionWindow(
                symbol=str(row["symbol"]),
                trade_date=row["trade_date"],
                window_index=int(row["window_index"]),
                available_at=_aware(row["available_at"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                amount=float(row["amount"]),
                trade_status=int(row["trade_status"]) if row["trade_status"] is not None else None,
                up_limit_price=(
                    float(row["up_limit_price"])
                    if row["up_limit_price"] is not None
                    else None
                ),
                down_limit_price=(
                    float(row["down_limit_price"])
                    if row["down_limit_price"] is not None
                    else None
                ),
                market_rule_valid=bool(row["market_rule_valid"]),
                hard_valid=bool(row["hard_valid"]),
                snapshot_id=str(row["snapshot_id"]),
                daily_snapshot_id=str(row["daily_snapshot_id"]),
                invalid_reasons=tuple(
                    item for item in str(row.get("invalid_reasons") or "").split("|") if item
                ),
            )
        )
    return tuple(result)


def replay(
    *,
    panel_path: Path,
    chip_root: Path,
    output_root: Path,
    symbol: str,
    parameters: StrategyParameters | None = None,
) -> dict[str, object]:
    config = MarkupRetestConfig.load()
    selected_parameters = parameters or config.parameters
    records = _records(panel_path, symbol)
    windows = _windows(config, symbol)
    market_dates = tuple(
        cast(date, row["trade_date"])
        for row in records
        if cast(date, row["trade_date"]) >= date(2020, 1, 1)
    )
    machine = LifecycleMachine(
        config,
        selected_parameters,
        anchor_retention_resolver=PersistedChipLineageResolver(chip_root),
    )
    memory = LifecycleMemory()
    trading_index = 0
    position: Position | None = None
    skip_through: date | None = None
    trades: list[dict[str, object]] = []
    failed_entries: list[dict[str, object]] = []

    for record in records:
        trade_date = cast(date, record["trade_date"])
        if skip_through is not None and trade_date <= skip_through:
            continue
        observation = observation_from_record(record, config, "single-stock-exact-v2")
        if position is not None and trade_date > position.entry_at.date():
            multiplier = float(record.get("share_multiplier") or 1.0)
            cash_per_share = float(record.get("cash_per_share") or 0.0)
            if multiplier != 1.0 or cash_per_share != 0.0:
                position.dividends += position.quantity * cash_per_share
                position.quantity = round(position.quantity * multiplier)

        transition = machine.advance(memory, observation, trading_index=trading_index)
        memory = transition.memory
        if transition.signal is not None:
            entry = execute_entry(
                transition.signal,
                windows,
                market_trading_dates=market_dates,
                settings=config.execution,
                scope=ExecutionScope.RESEARCH_EVENT_STUDY,
            )
            if entry.status == EntryExecutionStatus.FILLED:
                assert entry.fill_at is not None and entry.fill_price is not None
                position = Position(
                    signal_id=transition.signal.signal_id,
                    signal_at=transition.signal.decision_at,
                    entry_at=entry.fill_at,
                    entry_price=entry.fill_price,
                    entry_cash=entry.total_cash,
                    quantity=entry.quantity,
                    accumulation_started_at=transition.signal.accumulation_started_at,
                    breakout_at=transition.signal.breakout_at,
                    anchor_retention_lower=transition.signal.anchor_retention_lower,
                    setup_score=observation.setup_score,
                    close_to_p90_atr=(observation.close - observation.cost_p90)
                    / observation.atr,
                    momentum_20=(
                        float(record["momentum_20"])
                        if record.get("momentum_20") is not None
                        else None
                    ),
                )
            else:
                failed_entries.append(
                    {
                        "signal_id": transition.signal.signal_id,
                        "signal_at": transition.signal.decision_at.isoformat(),
                        "status": entry.status.value,
                        "reason_codes": list(entry.reason_codes),
                    }
                )
                memory = machine.after_exit()

        if transition.exit_reason is not None and position is not None:
            intent = ExitIntent(
                intent_id=f"exit-{position.signal_id}",
                signal_id=position.signal_id,
                symbol=symbol,
                decision_at=observation.decision_at,
                reason=transition.exit_reason,
                quantity=position.quantity,
                reference_price=observation.close,
                available_at=observation.available_at,
                snapshot_ids=observation.snapshot_ids,
                hard_valid=observation.hard_valid,
            )
            exit_fill = execute_exit(
                intent,
                windows,
                market_trading_dates=market_dates,
                settings=config.execution,
            )
            if exit_fill.fill_at is None or exit_fill.fill_price is None:
                continue
            net_pnl = exit_fill.net_proceeds + position.dividends - position.entry_cash
            trades.append(
                {
                    "signal_id": position.signal_id,
                    "signal_at": position.signal_at.isoformat(),
                    "entry_at": position.entry_at.isoformat(),
                    "entry_price": position.entry_price,
                    "quantity": position.quantity,
                    "accumulation_started_at": position.accumulation_started_at.isoformat(),
                    "breakout_at": position.breakout_at.isoformat(),
                    "anchor_retention_lower": position.anchor_retention_lower,
                    "setup_score": position.setup_score,
                    "close_to_p90_atr": position.close_to_p90_atr,
                    "momentum_20": position.momentum_20,
                    "exit_decision_at": observation.decision_at.isoformat(),
                    "exit_at": exit_fill.fill_at.isoformat(),
                    "exit_price": exit_fill.fill_price,
                    "exit_reason": transition.exit_reason.value,
                    "dividends": position.dividends,
                    "net_pnl": net_pnl,
                    "return_pct": 100.0 * net_pnl / position.entry_cash,
                    "validation_segment": (
                        "DEVELOPMENT" if position.signal_at.date().year <= 2023 else "RESEALED"
                    ),
                }
            )
            skip_through = exit_fill.fill_at.date()
            position = None
            memory = machine.after_exit()
        if observation.tradable:
            trading_index += 1

    output_root.mkdir(parents=True, exist_ok=True)
    trade_path = output_root / "corrected_trades.csv"
    if trades:
        with trade_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(trades[0]))
            writer.writeheader()
            writer.writerows(trades)
    else:
        trade_path.write_text("signal_id\n", encoding="utf-8")
    summary: dict[str, object] = {
        "symbol": symbol,
        "parameters": selected_parameters.canonical(),
        "trades": trades,
        "failed_entries": failed_entries,
        "open_position": asdict(position) if position is not None else None,
        "calculation_price_basis": "raw_unadjusted_with_causal_corporate_action_events",
        "display_price_basis": "raw_unadjusted",
        "causal_corporate_action_rebasing": True,
        "chip_data_version": "chip-operator-log-v11/real-chip-inventory-v2.1",
        "research_as_of": "2026-08-12",
        "pit_grade": "B_RESEARCH_ONLY_UNKNOWN_PREHISTORY",
    }
    (output_root / "corrected_replay_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--chip-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--symbol", default="000001.SZ")
    parser.add_argument("--setup-score-min", type=float)
    parser.add_argument("--breakout-buffer-atr", type=float)
    parser.add_argument("--max-retest-depth-atr", type=float)
    parser.add_argument("--min-cost-migration-atr", type=float)
    parser.add_argument("--distribution-score-min", type=float)
    parser.add_argument("--protective-stop-atr", type=float)
    args = parser.parse_args()
    config = MarkupRetestConfig.load()
    overrides = (
        args.setup_score_min,
        args.breakout_buffer_atr,
        args.max_retest_depth_atr,
        args.min_cost_migration_atr,
        args.distribution_score_min,
        args.protective_stop_atr,
    )
    parameters = None
    if any(value is not None for value in overrides):
        defaults = config.parameters
        parameters = StrategyParameters(
            setup_score_min=args.setup_score_min if args.setup_score_min is not None else defaults.setup_score_min,
            breakout_buffer_atr=args.breakout_buffer_atr if args.breakout_buffer_atr is not None else defaults.breakout_buffer_atr,
            max_retest_depth_atr=args.max_retest_depth_atr if args.max_retest_depth_atr is not None else defaults.max_retest_depth_atr,
            min_cost_migration_atr=args.min_cost_migration_atr if args.min_cost_migration_atr is not None else defaults.min_cost_migration_atr,
            distribution_score_min=args.distribution_score_min if args.distribution_score_min is not None else defaults.distribution_score_min,
            protective_stop_atr=args.protective_stop_atr if args.protective_stop_atr is not None else defaults.protective_stop_atr,
        )
    result = replay(
        panel_path=args.panel,
        chip_root=args.chip_root,
        output_root=args.output_root,
        symbol=args.symbol,
        parameters=parameters,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
