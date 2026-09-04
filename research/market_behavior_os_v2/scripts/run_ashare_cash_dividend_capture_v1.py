#!/usr/bin/env python3
"""Run the frozen sequential cash-dividend capture experiment."""

from __future__ import annotations

import bisect
import hashlib
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
EXPERIMENT_ID = "ASHARE-CASH-DIVIDEND-CAPTURE-V1"
FAMILY = "cash_dividend_capture"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
SELECTION_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_selection.csv"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
EXPECTED_SPEC_SHA256 = "41a5a3ad472d555cf71a159aaa3eff7e4d5ca4a436c1c3059012bd4b049b9a9c"
HORIZON = 20
COHORT_DIVISOR = 20


class CashDividendCaptureError(RuntimeError):
    """Fail-closed cash-dividend experiment error."""


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
        raise CashDividendCaptureError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _market_symbol(raw: str) -> str:
    value = str(raw).strip().split(".")[0]
    if len(value) != 6 or not value.isdigit():
        raise CashDividendCaptureError(f"invalid QD-010 symbol: {raw}")
    if value.startswith("6"):
        return f"{value}.SH"
    if value.startswith(("0", "3")):
        return f"{value}.SZ"
    return f"{value}.OTHER"


def _selection(spec: dict[str, Any]) -> pd.DataFrame:
    event_path = _resolve(spec["inputs"]["qd010_distributions"]["path"])
    connection = duckdb.connect()
    events = connection.execute(
        """
        SELECT event_id,symbol,CAST(known_at AS DATE) AS known_date,
          CAST(effective_date AS DATE) AS effective_date,cash_per_share_gross
        FROM read_parquet(?)
        WHERE effective_date BETWEEN DATE '2018-01-01' AND DATE '2023-12-31'
          AND source_terms_complete IS TRUE
          AND coalesce(share_multiplier,1)=1
          AND coalesce(cash_per_share_gross,0)>0
        ORDER BY known_date,symbol,event_id
        """,
        [str(event_path)],
    ).fetchdf()
    connection.close()
    if (
        events.empty
        or events.event_id.isna().any()
        or events.duplicated("event_id").any()
        or events.known_date.isna().any()
        or events.effective_date.isna().any()
    ):
        raise CashDividendCaptureError("QD-010 cash-event identity failed")
    events["known_date"] = pd.to_datetime(events.known_date)
    events["effective_date"] = pd.to_datetime(events.effective_date)
    if (
        (events.known_date >= events.effective_date).any()
        or events.effective_date.max() > pd.Timestamp("2023-12-31")
        or not np.isfinite(events.cash_per_share_gross).all()
        or events.cash_per_share_gross.le(0.0).any()
    ):
        raise CashDividendCaptureError("QD-010 cash-event timing or term failed")
    events["symbol"] = events.symbol.map(_market_symbol)

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
        raise CashDividendCaptureError("daily causal feature panel audit failed")
    calendar = sorted(feature.trade_date.dt.date.unique())

    def first_decision(row: Any) -> date | None:
        known = pd.Timestamp(row.known_date).date()
        effective = pd.Timestamp(row.effective_date).date()
        index = bisect.bisect_left(calendar, known)
        if index >= len(calendar) or calendar[index] >= effective:
            return None
        return calendar[index]

    events["signal_date"] = [first_decision(row) for row in events.itertuples()]
    events = events.dropna(subset=["signal_date"])
    events = events.sort_values(["signal_date", "symbol", "event_id"]).drop_duplicates(
        ["signal_date", "symbol"], keep="first"
    )
    feature["signal_date"] = feature.trade_date.dt.date
    selected = events.merge(
        feature,
        on=["signal_date", "symbol"],
        how="inner",
        validate="one_to_one",
    )
    if len(selected) != 8095 or selected.duplicated(["signal_date", "symbol"]).any():
        raise CashDividendCaptureError("eligible cash-dividend event set changed")
    if (pd.to_datetime(selected.signal_date) >= selected.effective_date).any():
        raise CashDividendCaptureError("signal is not before cash effective date")
    selected["industry"] = selected.industry.astype(str)
    return selected[
        [
            "signal_date",
            "symbol",
            "industry",
            "avg_amount20",
            "event_id",
            "effective_date",
            "cash_per_share_gross",
        ]
    ].sort_values(["signal_date", "symbol", "event_id"])


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
            raise CashDividendCaptureError(f"signal absent from calendar: {signal_date}")
        entry_index = calendar_index[signal_date] + 1
        due_index = entry_index + HORIZON
        if due_index >= len(calendar) or calendar[due_index] > cutoff:
            continue
        effective = pd.Timestamp(item.effective_date).date()
        if effective not in calendar_index or not (
            entry_index <= calendar_index[effective] < due_index
        ):
            raise CashDividendCaptureError("cash action escaped frozen holding window")
        rows.append(
            {
                "family": FAMILY,
                "signal_date": signal_date,
                "symbol": item.symbol,
                "industry": item.industry,
                "avg_amount20": float(item.avg_amount20),
                "state_value": float(item.cash_per_share_gross),
                "entry_index": entry_index,
                "due_index": due_index,
                "horizon": HORIZON,
            }
        )
    plans = pd.DataFrame(rows)
    if plans.empty or plans.duplicated(["signal_date", "symbol"]).any():
        raise CashDividendCaptureError("phase plan identity failed")
    return plans.sort_values(["entry_index", "symbol"])


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# Cash-dividend capture V1",
        "",
        f"Status: `{result['status']}`.",
        "",
        (
            "The frozen event is a completed implementation-announcement signal for "
            "a cash-only QD-010 distribution. Every eligible event stock enters at the "
            "next legal open, the date cohort receives one-twentieth pre-entry NAV, "
            "the exact cash credit enters the conserved ledger, and the cohort exits "
            "at h20."
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
                        f"{metrics['entry_execution_fraction']:.2%}; mean allocation "
                        f"{metrics['mean_event_allocation_fraction']:.2%}."
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
            "independent confirmation. QD-010 is bounded PIT-B current-history evidence. "
            "Post-2023 outcomes and CY-011 were not read. No Strategy-A combination or "
            "parameter rescue was run.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, Any]:
    if _sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise CashDividendCaptureError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    binding = spec["inputs"]["state_basket_orchestrator"]
    engine_path = _resolve(binding["path"])
    if _sha256_file(engine_path) != binding["sha256"]:
        raise CashDividendCaptureError("bound state-basket orchestrator changed")
    engine = _load_module("state_basket_for_cash_dividend", engine_path)
    original_load_module = engine._load_module

    def configured_load_module(name: str, path: Path) -> Any:
        module = original_load_module(name, path)
        if name == "shared_liquid_basket_replay":
            module.COHORT_DIVISOR = COHORT_DIVISOR
            original_phase_bounds = module._phase_bounds

            def phase_bounds(
                calendar: list[date], start_raw: str, cutoff_raw: str
            ) -> tuple[int, int, date, date]:
                if start_raw == "2020-07-28" and cutoff_raw == "2023-12-31":
                    start_raw = "2018-01-01"
                return original_phase_bounds(calendar, start_raw, cutoff_raw)

            module._phase_bounds = phase_bounds
        return module

    engine.EXPERIMENT_ID = EXPERIMENT_ID
    engine.FAMILY = FAMILY
    engine.SPEC_PATH = SPEC_PATH
    engine.SELECTION_PATH = SELECTION_PATH
    engine.RESULT_PATH = RESULT_PATH
    engine.REPORT_PATH = REPORT_PATH
    engine.EXPECTED_SPEC_SHA256 = EXPECTED_SPEC_SHA256
    engine.HORIZON = HORIZON
    engine._load_module = configured_load_module
    engine._selection = _selection
    engine._plans = _plans
    engine._render = _render
    return engine.run()


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
