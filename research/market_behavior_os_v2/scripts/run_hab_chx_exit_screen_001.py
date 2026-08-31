#!/usr/bin/env python3
"""Run one frozen, lightweight executable-exit screen on simple cycles."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
CHX_SCRIPTS = ROOT / "research/chinext_v1/scripts"
SRC = ROOT / "src"
for import_root in (str(CHX_SCRIPTS), str(SRC)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

from run_chinext_v1_full_survivor import read_jsonl  # noqa: E402
from run_chinext_v1_smoke import critical_row_valid  # noqa: E402

SPEC_PATH = PROGRAM / "experiments/HAB-CHX-EXIT-SCREEN-001_spec.json"
RESULT_PATH = PROGRAM / "artifacts/HAB-CHX-EXIT-SCREEN-001_result.json"
REPORT_PATH = PROGRAM / "reports/HAB-CHX-EXIT-SCREEN-001_exit_screen.md"
EXPECTED_SPEC_SHA256 = "66a3d8e23d7303f2bd30c972b4262f97a0f865c8701635c5643d42752a0bcab5"

START = date(2018, 1, 2)
END = date(2023, 12, 29)
COST_RATE = 0.001
BLOCKS = {
    "development_2018_2021": "development_execution_ledger",
    "consumed_2022_2023": "consumed_execution_ledger",
}


class ExitScreenError(RuntimeError):
    """Fail-closed executable-exit screen error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, date):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise ExitScreenError("exit-screen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_COUNTERFACTUAL_EXIT_ESTIMATES":
        raise ExitScreenError("exit-screen honesty status changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise ExitScreenError(f"bound input identity mismatch: {name}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "same-bar", "more than one"):
        if phrase not in prohibited:
            raise ExitScreenError(f"missing prohibition: {phrase}")
    return spec


def _validate_cy006(spec: dict[str, Any]) -> list[Path]:
    registry = json.loads(
        _resolve(spec["inputs"]["data_asset_registry"]["path"]).read_text()
    )
    asset = {row["asset_id"]: row for row in registry["assets"]}.get("CY-006")
    if (
        asset is None
        or asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or asset.get("physical_state") != "MATERIALIZED"
        or not asset.get("quality_evidence", {}).get("gate_pass")
    ):
        raise ExitScreenError("CY-006 registry contract is not active")
    manifest = json.loads(
        _resolve(spec["inputs"]["cy006_manifest"]["path"]).read_text()
    )
    root = Path(manifest["root"])
    by_year = {
        int(str(binding["path"]).split("partition_year=")[1].split("/")[0]): binding
        for binding in manifest["files"]
    }
    paths = []
    for year in range(START.year, END.year + 1):
        binding = by_year.get(year)
        if binding is None:
            raise ExitScreenError(f"CY-006 manifest lacks year {year}")
        path = root / binding["path"]
        if (
            not path.is_file()
            or path.stat().st_size != int(binding["size"])
            or sha256_file(path) != binding["sha256"]
        ):
            raise ExitScreenError(f"CY-006 partition identity mismatch: {year}")
        paths.append(path)
    return paths


def _cycles(block: str, path: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = read_jsonl(path)
    if any(date.fromisoformat(str(row["execution_date"])) > END for row in rows):
        raise ExitScreenError("post-2023 execution row encountered")
    active: dict[str, list[dict[str, Any]]] = {}
    all_cycles: list[list[dict[str, Any]]] = []
    for row in rows:
        if row.get("status") != "FILLED":
            continue
        symbol = str(row["symbol"])
        if row["side"] == "BUY" and row.get("new_position") is True:
            if symbol in active:
                raise ExitScreenError(f"overlapping active cycle: {symbol}")
            active[symbol] = [row]
        elif symbol in active:
            active[symbol].append(row)
        if row["side"] == "SELL" and row.get("completed_round_trip") is True:
            if symbol not in active:
                raise ExitScreenError(f"completed sell lacks active cycle: {symbol}")
            all_cycles.append(active.pop(symbol))
    simple = []
    for cycle in all_cycles:
        if len(cycle) != 2:
            continue
        buy, sell = cycle
        if (
            buy["side"] != "BUY"
            or buy.get("new_position") is not True
            or sell["side"] != "SELL"
            or sell.get("completed_round_trip") is not True
        ):
            raise ExitScreenError("two-leg cycle is not one new buy and one full sell")
        simple.append(
            {
                "block": block,
                "symbol": str(buy["symbol"]),
                "entry_signal_date": date.fromisoformat(str(buy["signal_date"])),
                "entry_execution_date": date.fromisoformat(str(buy["execution_date"])),
                "exit_signal_date": date.fromisoformat(str(sell["signal_date"])),
                "exit_execution_date": date.fromisoformat(str(sell["execution_date"])),
                "shares": float(buy["shares"]),
                "entry_cost": float(buy["notional"]) + float(buy["cost"]),
                "actual_return": float(sell["round_trip_return"]),
            }
        )
    return simple, {
        "completed_cycles": len(all_cycles),
        "simple_cycles": len(simple),
        "complex_rebalanced_cycles_excluded": len(all_cycles) - len(simple),
    }


def _load_sessions(spec: dict[str, Any]) -> list[date]:
    frame = pd.read_parquet(_resolve(spec["inputs"]["calendar"]["path"]))
    column = "trade_date" if "trade_date" in frame else "cal_date"
    return sorted(
        set(
            day
            for day in pd.to_datetime(frame[column]).dt.date
            if START <= day <= END
        )
    )


def _load_daily(paths: list[Path], symbols: list[str]) -> pd.DataFrame:
    columns = """
        trade_date, symbol, open, close, volume, amount,
        hard_valid, bar_valid, trading_state_valid, corporate_action_valid,
        market_rule_valid, historical_identity_valid, trade_status,
        current_day_data_tradable, is_st, corporate_action_blocking,
        available_at, sell_blocked_open, corporate_action_count,
        corporate_action_available_date, rights_ratio, share_multiplier,
        cash_per_share, corporate_action_problems
    """
    connection = duckdb.connect()
    frame = connection.execute(
        f"""
        SELECT {columns}
        FROM read_parquet(?)
        WHERE symbol IN (SELECT * FROM UNNEST(?))
          AND trade_date BETWEEN ? AND ?
        ORDER BY symbol, trade_date
        """,
        [[str(path) for path in paths], symbols, START, END],
    ).fetchdf()
    if frame.empty or frame.trade_date.max().date() > END:
        raise ExitScreenError("daily query is empty or crossed pre-2024 boundary")
    frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.date
    if frame.duplicated(["trade_date", "symbol"]).any():
        raise ExitScreenError("duplicate daily symbol-date row")
    return frame


def _action(row: dict[str, Any], day: date) -> tuple[float, float] | None:
    multiplier = 1.0 if pd.isna(row["share_multiplier"]) else float(row["share_multiplier"])
    cash = 0.0 if pd.isna(row["cash_per_share"]) else float(row["cash_per_share"])
    rights = 0.0 if pd.isna(row["rights_ratio"]) else float(row["rights_ratio"])
    available = row["corporate_action_available_date"]
    visible = (
        available is not None
        and not pd.isna(available)
        and pd.Timestamp(available).date() <= day
    )
    valid = (
        row["corporate_action_blocking"] is False
        and row["corporate_action_valid"] is True
        and visible
        and rights == 0.0
        and multiplier > 0
        and all(math.isfinite(value) for value in (multiplier, cash, rights))
    )
    return (multiplier, cash) if valid else None


def _signal(closes: list[float], ma: int, confirm: int) -> bool:
    if len(closes) < ma + confirm - 1:
        return False
    for offset in range(confirm):
        end = len(closes) - offset
        window = closes[end - ma : end]
        if not all(math.isfinite(value) and value > 0 for value in window):
            return False
        if not closes[end - 1] < float(np.mean(window)):
            return False
    return True


def _signal_map(
    daily: pd.DataFrame, sessions: list[date], rules: dict[str, Any]
) -> tuple[dict[tuple[str, date, str], bool], dict[tuple[str, date], dict[str, Any]]]:
    session_index = {day: index for index, day in enumerate(sessions)}
    row_map = {
        (str(row["symbol"]), row["trade_date"]): row
        for row in daily.to_dict("records")
    }
    result: dict[tuple[str, date, str], bool] = {}
    for symbol in sorted(daily.symbol.unique()):
        closes: list[float] = []
        history_dates: list[date] = []
        for day in sessions:
            row = row_map.get((symbol, day))
            if row is not None and int(row["corporate_action_count"] or 0) > 0:
                action = _action(row, day)
                if action is None:
                    closes = []
                    history_dates = []
                else:
                    multiplier, cash = action
                    closes = [(value - cash) / multiplier for value in closes]
            if critical_row_valid(row):
                history_dates.append(day)
                closes.append(float(row["close"]))
            for name, rule in rules.items():
                required = int(rule["ma_sessions"]) + int(rule["confirmation_closes"]) - 1
                contiguous = (
                    len(history_dates) >= required
                    and session_index[day] + 1 >= required
                    and history_dates[-required:]
                    == sessions[session_index[day] - required + 1 : session_index[day] + 1]
                )
                result[(symbol, day, name)] = contiguous and _signal(
                    closes, int(rule["ma_sessions"]), int(rule["confirmation_closes"])
                )
    return result, row_map


def _counterfactual(
    cycle: dict[str, Any],
    rule_name: str,
    rule: dict[str, Any],
    signals: dict[tuple[str, date, str], bool],
    rows: dict[tuple[str, date], dict[str, Any]],
    sessions: list[date],
) -> dict[str, Any]:
    del rule
    session_index = {day: index for index, day in enumerate(sessions)}
    entry_index = session_index[cycle["entry_execution_date"]]
    actual_signal_index = session_index[cycle["exit_signal_date"]]
    actual_execution_index = session_index[cycle["exit_execution_date"]]
    first_signal = None
    for index in range(entry_index, actual_signal_index):
        day = sessions[index]
        if signals.get((cycle["symbol"], day, rule_name), False):
            first_signal = day
            break
    if first_signal is None:
        return {
            "status": "ACTUAL_EXIT_PRESERVED",
            "return": cycle["actual_return"],
            "earlier_exit": False,
        }
    signal_index = session_index[first_signal]
    execution_day = None
    execution_price = None
    for index in range(signal_index + 1, actual_execution_index + 1):
        day = sessions[index]
        row = rows.get((cycle["symbol"], day))
        if row is None:
            continue
        executable = (
            day > cycle["entry_execution_date"]
            and row["hard_valid"] is True
            and int(row["trade_status"]) == 1
            and row["current_day_data_tradable"] is True
            and row["sell_blocked_open"] is False
            and row["open"] is not None
            and math.isfinite(float(row["open"]))
            and float(row["open"]) > 0
        )
        if executable:
            execution_day = day
            execution_price = float(row["open"])
            break
    if execution_day is None or execution_day >= cycle["exit_execution_date"]:
        return {
            "status": "ACTUAL_EXIT_PRESERVED_PENDING_NOT_EARLIER",
            "return": cycle["actual_return"],
            "earlier_exit": False,
        }
    shares = cycle["shares"]
    dividends = 0.0
    for index in range(entry_index + 1, session_index[execution_day] + 1):
        day = sessions[index]
        row = rows.get((cycle["symbol"], day))
        if row is None:
            return {"status": "FAIL_CLOSED_MISSING_HELD_ROW"}
        if int(row["corporate_action_count"] or 0) <= 0:
            continue
        action = _action(row, day)
        if action is None:
            return {"status": "FAIL_CLOSED_HELD_ACTION"}
        multiplier, cash = action
        dividends += shares * cash
        shares = round(shares * multiplier)
    value = dividends + shares * execution_price * (1.0 - COST_RATE)
    return {
        "status": "EARLIER_EXECUTABLE_EXIT",
        "return": value / cycle["entry_cost"] - 1.0,
        "earlier_exit": True,
        "signal_date": first_signal,
        "execution_date": execution_day,
        "lead_sessions": actual_execution_index - session_index[execution_day],
    }


def _metrics(values: list[float]) -> dict[str, Any]:
    array = np.asarray(values, dtype=float)
    return {
        "n": len(array),
        "mean": float(np.mean(array)) if len(array) else None,
        "median": float(np.median(array)) if len(array) else None,
        "win_rate": float(np.mean(array > 0)) if len(array) else None,
        "winner20_rate": float(np.mean(array >= 0.20)) if len(array) else None,
        "severe_loss_rate": float(np.mean(array <= -0.10)) if len(array) else None,
    }


def _evaluate_rule(
    cycles: list[dict[str, Any]],
    name: str,
    rule: dict[str, Any],
    signals: dict[tuple[str, date, str], bool],
    rows: dict[tuple[str, date], dict[str, Any]],
    sessions: list[date],
) -> dict[str, Any]:
    by_block: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for cycle in cycles:
        outcome = _counterfactual(cycle, name, rule, signals, rows, sessions)
        if "return" in outcome:
            by_block[cycle["block"]].append((cycle, outcome))
    result = {}
    for block in BLOCKS:
        pairs = by_block[block]
        actual = [cycle["actual_return"] for cycle, _ in pairs]
        alternative = [outcome["return"] for _, outcome in pairs]
        earlier = [outcome for _, outcome in pairs if outcome["earlier_exit"]]
        result[block] = {
            "evaluable_cycles": len(pairs),
            "fail_closed_cycles": sum(cycle["block"] == block for cycle in cycles) - len(pairs),
            "earlier_exit_count": len(earlier),
            "median_lead_sessions": float(np.median([row["lead_sessions"] for row in earlier]))
            if earlier
            else None,
            "actual": _metrics(actual),
            "alternative": _metrics(alternative),
            "paired_mean_change": float(np.mean(np.asarray(alternative) - np.asarray(actual)))
            if pairs
            else None,
        }
    return result


def _role(evaluation: dict[str, Any], spec: dict[str, Any]) -> str:
    gate = spec["promotion_gate"]
    strong = True
    risk = True
    for block in BLOCKS:
        row = evaluation[block]
        actual = row["actual"]
        alternative = row["alternative"]
        coverage = (
            row["evaluable_cycles"] >= gate["minimum_evaluable_cycles_each_block"]
            and row["earlier_exit_count"] >= gate["minimum_earlier_exits_each_block"]
        )
        strong &= (
            coverage
            and row["paired_mean_change"] >= 0.01
            and alternative["severe_loss_rate"] <= actual["severe_loss_rate"]
        )
        risk &= (
            coverage
            and alternative["severe_loss_rate"] <= actual["severe_loss_rate"] - 0.05
            and row["paired_mean_change"] >= -0.01
        )
    if strong:
        return "STRONG_EXIT_REPLAY_CANDIDATE"
    if risk:
        return "RISK_EXIT_REPLAY_CANDIDATE"
    return "NO_EXIT_REPLAY"


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# HAB-CHX-EXIT-SCREEN-001 — executable exit screen",
        "",
        "The screen is restricted to exact two-leg cycles; complex rebalanced cycles are "
        "excluded rather than assigned invented counterfactual cash flows.",
        "",
        "| Rule | Role | Earlier dev | Mean change dev | Earlier 2022–23 | "
        "Mean change 2022–23 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for name, evaluation in result["evaluations"].items():
        development = evaluation["development_2018_2021"]
        consumed = evaluation["consumed_2022_2023"]
        lines.append(
            f"| {name} | {result['information_roles'][name]} | "
            f"{development['earlier_exit_count']} | {development['paired_mean_change']:.3%} | "
            f"{consumed['earlier_exit_count']} | {consumed['paired_mean_change']:.3%} |"
        )
    lines.extend(
        [
            "",
            "Executable replay candidate: " + (result["replay_candidate"] or "none"),
            "",
            "Every alternative signal is formed at a completed close and can fill only at a "
            "later executable open. No post-2023 or CY-011 row was read.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    spec = _load_spec()
    if RESULT_PATH.exists() or REPORT_PATH.exists():
        raise ExitScreenError("exit-screen output already exists")
    daily_paths = _validate_cy006(spec)
    cycles = []
    population = {}
    for block, input_name in BLOCKS.items():
        block_cycles, counts = _cycles(block, _resolve(spec["inputs"][input_name]["path"]))
        cycles.extend(block_cycles)
        population[block] = counts
    expected = {"development_2018_2021": 53, "consumed_2022_2023": 28}
    if {block: row["simple_cycles"] for block, row in population.items()} != expected:
        raise ExitScreenError("frozen simple-cycle count changed")
    sessions = _load_sessions(spec)
    daily = _load_daily(daily_paths, sorted({cycle["symbol"] for cycle in cycles}))
    signals, rows = _signal_map(daily, sessions, spec["rules"])
    evaluations = {
        name: _evaluate_rule(cycles, name, rule, signals, rows, sessions)
        for name, rule in spec["rules"].items()
    }
    roles = {name: _role(evaluation, spec) for name, evaluation in evaluations.items()}
    candidates = [name for name, role in roles.items() if role.endswith("REPLAY_CANDIDATE")]
    candidates.sort(
        key=lambda name: sum(
            evaluations[name][block]["paired_mean_change"] for block in BLOCKS
        ),
        reverse=True,
    )
    replay = candidates[0] if candidates else None
    result = {
        "experiment_id": spec["experiment_id"],
        "research_level": spec["research_level"],
        "status": "COMPLETE_EXECUTABLE_EXIT_SCREEN",
        "honesty_boundary": spec["honesty_boundary"],
        "population": population,
        "evaluations": evaluations,
        "information_roles": roles,
        "replay_candidate": replay,
        "decision": "RUN_ONE_EXIT_REPLAY" if replay else "EXIT_REMAINS_UNRESOLVED",
        "claim_boundary": {
            "untouched_validation": False,
            "post_2023_rows_read": False,
            "cy011_read": False,
            "portfolio_replay": False,
            "complex_rebalanced_cycles_modeled": False,
            "threshold_search": False,
        },
        "hashes": {
            "spec_sha256": EXPECTED_SPEC_SHA256,
            "inputs": {name: binding["sha256"] for name, binding in spec["inputs"].items()},
        },
    }
    _atomic_write(REPORT_PATH, _render(result))
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(
        RESULT_PATH,
        json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False) + "\n",
    )
    print(json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
