#!/usr/bin/env python3
"""Run the frozen sequential new-high/new-low exhaustion Strategy-B experiment."""

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
EXPERIMENT_ID = "ASHARE-NEW-HIGH-LOW-EXHAUSTION-LIQUID-BASKET-V1"
FAMILY = "new_high_low_exhaustion_liquid_basket"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
SELECTION_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_selection.csv"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
EXPECTED_SPEC_SHA256 = "768840c4ae02d1e9e9c99388d4c941673420680c9200df3273c1e8881fcd6bc2"
HORIZON = 5
COORDINATE = "breadth_net_new_high_low60_pit_3y_pct"


class BreadthExhaustionError(RuntimeError):
    """Fail-closed new-high/new-low exhaustion experiment error."""


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
        raise BreadthExhaustionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _selection(spec: dict[str, Any]) -> pd.DataFrame:
    state_path = _resolve(spec["inputs"]["breadth_state_panel"]["path"])
    state = pd.read_csv(
        state_path,
        usecols=[
            "trade_date",
            "market_view",
            "denominator",
            "decision_at",
            "available_at",
            COORDINATE,
        ],
        parse_dates=["trade_date"],
    )
    state = state.loc[
        state.market_view.eq("ALL_A") & state.denominator.eq("ALL_STATUS")
    ].copy()
    if state.duplicated("trade_date").any() or state.trade_date.max() > pd.Timestamp(
        "2023-12-31"
    ):
        raise BreadthExhaustionError("breadth-state date identity failed")
    state["decision_at"] = pd.to_datetime(state.decision_at, utc=True)
    state["available_at"] = pd.to_datetime(state.available_at, utc=True)
    if (state.available_at > state.decision_at).any():
        raise BreadthExhaustionError("breadth state entered before availability")
    first_valid = state.loc[state[COORDINATE].notna(), "trade_date"].min()
    if first_valid != pd.Timestamp("2020-07-28"):
        raise BreadthExhaustionError(f"unexpected causal activation: {first_valid}")
    expected = state.trade_date.ge(first_valid)
    if state.loc[expected, COORDINATE].isna().any():
        raise BreadthExhaustionError("missing breadth state after causal activation")
    active = state.loc[
        expected & state[COORDINATE].le(0.20), ["trade_date", COORDINATE]
    ]

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
        raise BreadthExhaustionError("daily causal feature panel audit failed")
    selected = feature.merge(active, on="trade_date", how="inner", validate="many_to_one")
    selected = selected.sort_values(
        ["trade_date", "avg_amount20", "symbol"], ascending=[True, False, True]
    )
    selected["liquidity_rank"] = selected.groupby("trade_date").cumcount() + 1
    selected = selected.loc[selected.liquidity_rank.le(20)].copy()
    if selected.groupby("trade_date").size().ne(20).any():
        raise BreadthExhaustionError("frozen top-20 basket breadth changed")
    selected["signal_date"] = selected.trade_date.dt.date
    selected["industry"] = selected.industry.astype(str)
    return selected[
        [
            "signal_date",
            "symbol",
            "industry",
            "avg_amount20",
            "liquidity_rank",
            COORDINATE,
        ]
    ].sort_values(["signal_date", "liquidity_rank", "symbol"])


def _plans(
    selection: pd.DataFrame,
    calendar: list[date],
    start_raw: str,
    end_raw: str,
    cutoff_raw: str,
) -> pd.DataFrame:
    calendar_index = {day: index for index, day in enumerate(calendar)}
    start = pd.Timestamp(start_raw).date()
    end = pd.Timestamp(end_raw).date()
    cutoff = pd.Timestamp(cutoff_raw).date()
    rows: list[dict[str, Any]] = []
    phase = selection.loc[selection.signal_date.between(start, end)].copy()
    for item in phase.itertuples(index=False):
        signal_date = item.signal_date
        if signal_date not in calendar_index:
            raise BreadthExhaustionError(f"signal date absent from calendar: {signal_date}")
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
                "state_value": float(getattr(item, COORDINATE)),
                "entry_index": entry_index,
                "due_index": due_index,
                "horizon": HORIZON,
            }
        )
    plans = pd.DataFrame(rows)
    if plans.empty or plans.groupby("signal_date").size().ne(20).any():
        raise BreadthExhaustionError("phase plan breadth changed")
    return plans.sort_values(
        ["entry_index", "avg_amount20", "symbol"], ascending=[True, False, True]
    )


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# New-high/new-low exhaustion liquid-basket V1",
        "",
        f"Status: `{result['status']}`.",
        "",
        (
            "The frozen signal is the bottom historical quintile of ALL-A 60-session "
            "new-high minus new-low breadth. It buys the 20 highest prior-20-session "
            "amount stocks at the next legal open, assigns one-fifth NAV per daily "
            "event, and exits at h5."
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
    if _sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise BreadthExhaustionError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    binding = spec["inputs"]["state_basket_orchestrator"]
    engine_path = _resolve(binding["path"])
    if _sha256_file(engine_path) != binding["sha256"]:
        raise BreadthExhaustionError("bound state-basket orchestrator changed")
    engine = _load_module("state_basket_for_breadth_exhaustion", engine_path)
    engine.EXPERIMENT_ID = EXPERIMENT_ID
    engine.FAMILY = FAMILY
    engine.SPEC_PATH = SPEC_PATH
    engine.SELECTION_PATH = SELECTION_PATH
    engine.RESULT_PATH = RESULT_PATH
    engine.REPORT_PATH = REPORT_PATH
    engine.EXPECTED_SPEC_SHA256 = EXPECTED_SPEC_SHA256
    engine.HORIZON = HORIZON
    engine._selection = _selection
    engine._plans = _plans
    engine._render = _render
    return engine.run()


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
