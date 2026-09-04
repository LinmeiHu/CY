#!/usr/bin/env python3
"""Run the frozen sequential post-share-distribution drift experiment."""

from __future__ import annotations

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
EXPERIMENT_ID = "ASHARE-POST-DISTRIBUTION-DRIFT-V1"
FAMILY = "post_share_distribution_drift"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
SELECTION_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_selection.csv"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
EXPECTED_SPEC_SHA256 = "21d85109c394cf52c3c6cd3e103ab4fdd94d50b6ed141418e3f3d0412cb6b8fe"
HORIZON = 20
COHORT_DIVISOR = 20


class PostDistributionDriftError(RuntimeError):
    """Fail-closed post-distribution experiment error."""


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
        raise PostDistributionDriftError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _market_symbol(raw: str) -> str:
    value = str(raw).strip().split(".")[0]
    if len(value) != 6 or not value.isdigit():
        raise PostDistributionDriftError(f"invalid QD-010 symbol: {raw}")
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
          CAST(effective_date AS DATE) AS effective_date,share_multiplier
        FROM read_parquet(?)
        WHERE effective_date BETWEEN DATE '2018-01-01' AND DATE '2023-12-31'
          AND coalesce(share_multiplier,1)>1 AND source_terms_complete IS TRUE
        ORDER BY effective_date,symbol,event_id
        """,
        [str(event_path)],
    ).fetchdf()
    connection.close()
    if (
        events.empty
        or events.event_id.isna().any()
        or events.duplicated("event_id").any()
        or events.duplicated(["symbol", "effective_date"]).any()
        or events.known_date.isna().any()
        or events.effective_date.isna().any()
    ):
        raise PostDistributionDriftError("QD-010 event identity failed")
    events["known_date"] = pd.to_datetime(events.known_date)
    events["effective_date"] = pd.to_datetime(events.effective_date)
    if (
        (events.known_date >= events.effective_date).any()
        or events.effective_date.max() > pd.Timestamp("2023-12-31")
        or not np.isfinite(events.share_multiplier).all()
        or events.share_multiplier.le(1.0).any()
    ):
        raise PostDistributionDriftError("QD-010 event timing or term failed")
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
        raise PostDistributionDriftError("daily causal feature panel audit failed")
    selected = events.merge(
        feature,
        left_on=["effective_date", "symbol"],
        right_on=["trade_date", "symbol"],
        how="inner",
        validate="one_to_one",
    )
    if len(selected) != 886 or selected.duplicated(["effective_date", "symbol"]).any():
        raise PostDistributionDriftError("eligible post-distribution event set changed")
    selected["signal_date"] = selected.effective_date.dt.date
    selected["industry"] = selected.industry.astype(str)
    return selected[
        [
            "signal_date",
            "symbol",
            "industry",
            "avg_amount20",
            "event_id",
            "share_multiplier",
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
            raise PostDistributionDriftError(
                f"effective signal absent from calendar: {signal_date}"
            )
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
                "state_value": float(item.share_multiplier),
                "entry_index": entry_index,
                "due_index": due_index,
                "horizon": HORIZON,
            }
        )
    plans = pd.DataFrame(rows)
    if plans.empty or plans.duplicated(["signal_date", "symbol"]).any():
        raise PostDistributionDriftError("phase plan identity failed")
    return plans.sort_values(["entry_index", "symbol"])


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# Post-share-distribution drift V1",
        "",
        f"Status: `{result['status']}`.",
        "",
        (
            "The frozen event is a completed QD-010 bonus/capitalized-share "
            "distribution with share multiplier above one. Every eligible event stock "
            "enters at the next legal open, each event date receives one-twentieth "
            "pre-entry NAV, and the cohort exits at h20."
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
        raise PostDistributionDriftError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    binding = spec["inputs"]["state_basket_orchestrator"]
    engine_path = _resolve(binding["path"])
    if _sha256_file(engine_path) != binding["sha256"]:
        raise PostDistributionDriftError("bound state-basket orchestrator changed")
    engine = _load_module("state_basket_for_post_distribution", engine_path)
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
