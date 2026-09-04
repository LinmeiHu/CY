#!/usr/bin/env python3
"""Run the frozen sequential liquidity-activity Strategy-B experiment."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
EXPERIMENT_ID = "ASHARE-LIQUIDITY-ACTIVITY-LIQUID-BASKET-V1"
FAMILY = "liquidity_activity_liquid_basket"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
SELECTION_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_selection.csv"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
EXPECTED_SPEC_SHA256 = "ed8b983cc78dafe8cc665b09ac27f1e859caf8c63a7783d5b936270ab76fc48f"
HORIZON = 5


class LiquidityActivityError(RuntimeError):
    """Fail-closed liquidity-activity experiment error."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise LiquidityActivityError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _load_spec() -> dict[str, Any]:
    if _sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise LiquidityActivityError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_SEQUENTIAL_STRATEGY_B_BEFORE_GENERATION_REPLAY":
        raise LiquidityActivityError("spec is not frozen before generation replay")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or _sha256_file(path) != binding["sha256"]:
            raise LiquidityActivityError(f"bound input changed: {name}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "before every generation", "combination"):
        if phrase not in prohibited:
            raise LiquidityActivityError(f"missing frozen prohibition: {phrase}")
    return spec


def _selection(spec: dict[str, Any]) -> pd.DataFrame:
    coordinate = "liquidity_median_amount_ratio20_pit_3y_pct"
    state_path = _resolve(spec["inputs"]["liquidity_state_panel"]["path"])
    state = pd.read_csv(
        state_path,
        usecols=[
            "trade_date",
            "market_view",
            "denominator",
            "decision_at",
            "available_at",
            coordinate,
        ],
        parse_dates=["trade_date"],
    )
    state = state.loc[
        state.market_view.eq("ALL_A") & state.denominator.eq("ALL_STATUS")
    ].copy()
    if state.duplicated("trade_date").any() or state.trade_date.max() > pd.Timestamp(
        "2023-12-31"
    ):
        raise LiquidityActivityError("liquidity-state date identity failed")
    state["decision_at"] = pd.to_datetime(state.decision_at, utc=True)
    state["available_at"] = pd.to_datetime(state.available_at, utc=True)
    if (state.available_at > state.decision_at).any():
        raise LiquidityActivityError("liquidity state entered before availability")
    first_valid = state.loc[state[coordinate].notna(), "trade_date"].min()
    if first_valid != pd.Timestamp("2020-07-28"):
        raise LiquidityActivityError(f"unexpected causal activation: {first_valid}")
    expected = state.trade_date.ge(first_valid)
    if state.loc[expected, coordinate].isna().any():
        raise LiquidityActivityError("missing liquidity state after causal activation")
    active = state.loc[expected & state[coordinate].ge(0.80), ["trade_date", coordinate]]

    feature_path = _resolve(spec["inputs"]["daily_feature_panel"]["path"])
    feature = pd.read_parquet(
        feature_path,
        columns=[
            "trade_date",
            "decision_at",
            "available_at",
            "symbol",
            "industry",
            "avg_amount20",
        ],
    )
    feature["trade_date"] = pd.to_datetime(feature.trade_date)
    feature["decision_at"] = pd.to_datetime(feature.decision_at)
    feature["available_at"] = pd.to_datetime(feature.available_at)
    if (
        feature.trade_date.max() > pd.Timestamp("2023-12-31")
        or (feature.available_at > feature.decision_at).any()
        or feature.duplicated(["trade_date", "symbol"]).any()
        or feature.avg_amount20.lt(50_000_000).any()
        or not np.isfinite(feature.avg_amount20).all()
    ):
        raise LiquidityActivityError("daily causal feature panel audit failed")
    selected = feature.merge(active, on="trade_date", how="inner", validate="many_to_one")
    selected = selected.sort_values(
        ["trade_date", "avg_amount20", "symbol"], ascending=[True, False, True]
    )
    selected["liquidity_rank"] = selected.groupby("trade_date").cumcount() + 1
    selected = selected.loc[selected.liquidity_rank.le(20)].copy()
    if selected.groupby("trade_date").size().ne(20).any():
        raise LiquidityActivityError("frozen top-20 basket breadth changed")
    selected["signal_date"] = selected.trade_date.dt.date
    selected["industry"] = selected.industry.astype(str)
    columns = [
        "signal_date",
        "symbol",
        "industry",
        "avg_amount20",
        "liquidity_rank",
        coordinate,
    ]
    return selected[columns].sort_values(["signal_date", "liquidity_rank", "symbol"])


def _plans(
    selection: pd.DataFrame,
    calendar: list[date],
    start_raw: str,
    end_raw: str,
    cutoff_raw: str,
) -> pd.DataFrame:
    coordinate = "liquidity_median_amount_ratio20_pit_3y_pct"
    calendar_index = {day: index for index, day in enumerate(calendar)}
    start = pd.Timestamp(start_raw).date()
    end = pd.Timestamp(end_raw).date()
    cutoff = pd.Timestamp(cutoff_raw).date()
    rows: list[dict[str, Any]] = []
    phase = selection.loc[selection.signal_date.between(start, end)].copy()
    for item in phase.itertuples(index=False):
        signal_date = item.signal_date
        if signal_date not in calendar_index:
            raise LiquidityActivityError(f"signal date absent from calendar: {signal_date}")
        entry_index = calendar_index[signal_date] + 1
        due_index = entry_index + HORIZON
        if due_index >= len(calendar) or calendar[due_index] > cutoff:
            continue
        rows.append(
            {
                "family": FAMILY,
                "signal_date": signal_date,
                "symbol": item.symbol,
                "industry": item.industry,
                "avg_amount20": float(item.avg_amount20),
                "state_value": float(getattr(item, coordinate)),
                "entry_index": entry_index,
                "due_index": due_index,
                "horizon": HORIZON,
            }
        )
    plans = pd.DataFrame(rows)
    if plans.empty or plans.groupby("signal_date").size().ne(20).any():
        raise LiquidityActivityError("phase plan breadth changed")
    return plans.sort_values(
        ["entry_index", "avg_amount20", "symbol"], ascending=[True, False, True]
    )


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# Liquidity-activity liquid-basket V1",
        "",
        f"Status: `{result['status']}`.",
        "",
        (
            "The frozen signal is the top historical quintile of ALL-A median amount "
            "activity versus its prior-20-session baseline. It buys the 20 highest "
            "prior-20-session amount stocks at the next legal open, assigns one-fifth "
            "NAV per daily event, and exits at h5."
        ),
        "",
    ]
    for name in ("generation", "validation", "full"):
        metrics = result.get(name)
        if not metrics:
            continue
        lines.extend([f"## {name.title()}", "", f"Status `{metrics['status']}`."])
        if metrics["status"] == "COMPLETE":
            lines.extend(
                [
                    (
                        f"Annualized {metrics['annualized_return']:.2%}; total "
                        f"{metrics['total_return']:.2%}; max drawdown "
                        f"{metrics['maximum_drawdown']:.2%}; Sharpe "
                        f"{metrics['daily_sharpe']:.3f}; severe trades "
                        f"{metrics['severe_trade_fraction']:.2%}."
                    ),
                    (
                        f"Signals {metrics['signal_dates']}; completed trades "
                        f"{metrics['completed_trades']}; entry coverage "
                        f"{metrics['entry_execution_fraction']:.2%}."
                    ),
                ]
            )
        lines.append("")
    if result.get("independence"):
        item = result["independence"]
        lines.extend(
            [
                "## Independence",
                "",
                (
                    "Daily-return correlation with Industry-Consensus Q1 is "
                    f"{item['daily_return_correlation_with_industry_consensus_q1']:.3f}; "
                    f"signal-date overlap is {item['signal_date_overlap']} "
                    f"(Jaccard {item['signal_date_jaccard']:.3f})."
                ),
                "",
            ]
        )
    lines.extend(
        [
            "This is sequential research on consumed development history, not OOS or "
            "independent confirmation. Post-2023 outcomes and CY-011 were not read. No "
            "Strategy-A combination or parameter rescue was run.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    shared = _load_module(
        "shared_liquid_basket_replay",
        _resolve(spec["inputs"]["shared_replay_runner"]["path"]),
    )
    shared.EXPERIMENT_ID = EXPERIMENT_ID
    shared.FAMILY = FAMILY
    ca = _load_module(
        "ca_for_liquidity_activity",
        _resolve(spec["inputs"]["execution_runner"]["path"]),
    )
    ca_spec = ca._load_spec()
    paths, calendar, input_identity = ca._load_market_inputs(ca_spec)
    events, action_audit = ca._load_risk_events(ca_spec, calendar)
    selection = _selection(spec)
    shared._atomic_write(
        SELECTION_PATH,
        selection.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )

    protocol = spec["sequential_protocol"]
    generation_spec = protocol["generation"]
    gen_start, gen_cutoff, _, _ = shared._phase_bounds(
        calendar,
        generation_spec["signal_period"][0],
        generation_spec["maximum_outcome_date"],
    )
    generation_plans = _plans(
        selection,
        calendar,
        generation_spec["signal_period"][0],
        generation_spec["signal_period"][1],
        generation_spec["maximum_outcome_date"],
    )
    generation_rows = shared._query_execution_rows(
        paths, generation_plans, calendar, gen_cutoff
    )
    generation, gen_equity, gen_trades = shared._replay(
        generation_plans,
        generation_rows,
        calendar,
        events,
        ca,
        gen_start,
        gen_cutoff,
    )
    generation_checks = shared._gate(
        generation, generation_spec["all_required_to_open_validation"]
    )
    generation_passed = all(generation_checks.values())
    hashes = {
        "spec_sha256": _sha256_file(SPEC_PATH),
        "selection_sha256": _sha256_file(SELECTION_PATH),
        **shared._write_phase("generation", gen_equity, gen_trades),
    }
    result: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "claim_boundary": spec["claim_boundary"],
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
        "input_identity": input_identity,
        "action_audit": action_audit,
        "generation": generation,
        "generation_checks": generation_checks,
        "generation_passed": generation_passed,
        "validation_opened": False,
        "full_replay_opened": False,
        "hashes": hashes,
    }
    if not generation_passed:
        result["status"] = "GENERATION_REJECTED_VALIDATION_UNOPENED"
        shared._atomic_write(
            RESULT_PATH,
            json.dumps(shared._clean(result), indent=2, sort_keys=True) + "\n",
        )
        shared._atomic_write(REPORT_PATH, _render(result))
        return result

    validation_spec = protocol["validation"]
    val_start, val_cutoff, _, _ = shared._phase_bounds(
        calendar,
        validation_spec["signal_period"][0],
        validation_spec["maximum_outcome_date"],
    )
    validation_plans = _plans(
        selection,
        calendar,
        validation_spec["signal_period"][0],
        validation_spec["signal_period"][1],
        validation_spec["maximum_outcome_date"],
    )
    validation_rows = shared._query_execution_rows(
        paths, validation_plans, calendar, val_cutoff
    )
    validation, val_equity, val_trades = shared._replay(
        validation_plans,
        validation_rows,
        calendar,
        events,
        ca,
        val_start,
        val_cutoff,
    )
    validation_checks = shared._gate(validation, validation_spec["all_required"])
    validation_passed = all(validation_checks.values())
    result.update(
        {
            "validation_opened": True,
            "validation": validation,
            "validation_checks": validation_checks,
            "validation_passed": validation_passed,
        }
    )
    result["hashes"].update(shared._write_phase("validation", val_equity, val_trades))
    if not validation_passed:
        result["status"] = "VALIDATION_REJECTED_NO_FULL_REPLAY"
        shared._atomic_write(
            RESULT_PATH,
            json.dumps(shared._clean(result), indent=2, sort_keys=True) + "\n",
        )
        shared._atomic_write(REPORT_PATH, _render(result))
        return result

    full_start, full_cutoff, _, _ = shared._phase_bounds(
        calendar, "2020-07-28", "2023-12-31"
    )
    full_plans = pd.concat([generation_plans, validation_plans], ignore_index=True)
    full_rows = shared._query_execution_rows(paths, full_plans, calendar, full_cutoff)
    full, full_equity, full_trades = shared._replay(
        full_plans,
        full_rows,
        calendar,
        events,
        ca,
        full_start,
        full_cutoff,
    )
    independence = shared._independence(spec, full_equity, full_plans)
    full_gate = protocol["final_candidate_all_required"]
    full_checks = {
        "complete": full.get("status") == "COMPLETE",
        "annualized_return": full.get("annualized_return", -1.0)
        >= full_gate["minimum_annualized_return"],
        "daily_sharpe": full.get("daily_sharpe", -1.0)
        >= full_gate["minimum_daily_sharpe"],
        "maximum_drawdown": full.get("maximum_drawdown", -1.0)
        > full_gate["maximum_drawdown_must_be_greater_than"],
        "independence": abs(
            independence["daily_return_correlation_with_industry_consensus_q1"]
        )
        <= full_gate["maximum_daily_return_correlation_with_industry_consensus_q1"],
    }
    result.update(
        {
            "full_replay_opened": True,
            "full": full,
            "independence": independence,
            "full_checks": full_checks,
            "status": (
                "STRATEGY_B_CANDIDATE"
                if all(full_checks.values())
                else "PROMISING_BUT_MIXED_NO_STRATEGY_B_CANDIDATE"
            ),
        }
    )
    result["hashes"].update(shared._write_phase("full", full_equity, full_trades))
    shared._atomic_write(
        RESULT_PATH,
        json.dumps(shared._clean(result), indent=2, sort_keys=True) + "\n",
    )
    shared._atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
