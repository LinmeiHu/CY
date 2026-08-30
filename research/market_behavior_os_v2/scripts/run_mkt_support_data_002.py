#!/usr/bin/env python3
"""Execute the eligibility-aware objective-support coordinate audit."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
PARENT_RUNNER = PROGRAM / "scripts/run_mkt_support_data_001.py"
PARENT_MODULE_SPEC = importlib.util.spec_from_file_location(
    "run_mkt_support_data_001_parent", PARENT_RUNNER
)
if PARENT_MODULE_SPEC is None or PARENT_MODULE_SPEC.loader is None:
    raise RuntimeError("cannot load parent objective-support runner")
parent = importlib.util.module_from_spec(PARENT_MODULE_SPEC)
PARENT_MODULE_SPEC.loader.exec_module(parent)

SPEC_PATH = PROGRAM / "experiments/MKT-SUPPORT-DATA-002_spec.json"
SAMPLE_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DATA-002_sample.csv"
COORDINATE_AUDIT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DATA-002_coordinate_audit.csv"
POPULATION_AUDIT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DATA-002_population_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DATA-002_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-SUPPORT-DATA-002_audit.md"
EXPECTED_SPEC_SHA256 = "79ec5129deddb2add59731a44bfa40b95bcbad827022bc61440f1b778b7ff689"

SupportDataError = parent.SupportDataError
sha256_file = parent.sha256_file
adapter = parent.adapter
_parent_fetch_target_coordinates = parent.fetch_target_coordinates


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise SupportDataError("MKT-SUPPORT-DATA-002 spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_NEW_RAW_MINUTE_ACCESS":
        raise SupportDataError("002 spec is not frozen before raw-minute access")
    sample = spec["sample"]
    expected_sample = {
        "market_views": ["ALL_A", "SH_A", "SZ_A", "CHINEXT_BOARD"],
        "sequences_per_year_view": 10,
        "sessions_per_sequence": 5,
        "expected_market_rows": 1200,
        "supported_action_sessions_per_year": 5,
        "supported_action_years": 6,
        "expected_cohort_rows": 1230,
    }
    for key, expected in expected_sample.items():
        if sample.get(key) != expected:
            raise SupportDataError(f"002 sample contract changed: {key}")
    if spec["support_candidates"] != {
        "primary_previous_sessions": 20,
        "fixed_feasibility_neighbors": [10, 40],
        "price": "minimum action-coordinate daily low through t-1",
        "available_at": "t-1 15:00 Asia/Shanghai",
    }:
        raise SupportDataError("support candidate definitions changed")
    if spec["parent_invalid_attempt"]["parent_outputs_accepted"] is not False:
        raise SupportDataError("invalid parent output boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise SupportDataError(f"002 input identity mismatch: {name}")
    return spec


def _selection_hash(role: str, year: int, market_view: str, symbol: str, trade_date: str = "") -> str:
    if role == "MARKET":
        payload = f"MKT-SUPPORT-DATA-002|MARKET|{year}|{market_view}|{symbol}"
    elif role == "ACTION":
        payload = f"MKT-SUPPORT-DATA-002|ACTION|{year}|{symbol}|{trade_date}"
    else:
        raise SupportDataError(f"unknown sample role: {role}")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _view_mask(symbols: pd.Series, market_view: str) -> pd.Series:
    symbols = symbols.astype(str)
    if market_view == "ALL_A":
        return symbols.str.endswith((".SH", ".SZ"))
    if market_view == "SH_A":
        return symbols.str.endswith(".SH")
    if market_view == "SZ_A":
        return symbols.str.endswith(".SZ")
    if market_view == "CHINEXT_BOARD":
        return symbols.str.endswith(".SZ") & symbols.str[:3].isin(["300", "301"])
    raise SupportDataError(f"unknown governed view: {market_view}")


def _select_market_sequences(
    eligible_rows: pd.DataFrame, spec: dict[str, Any]
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    count = int(spec["sample"]["sequences_per_year_view"])
    block_size = int(spec["sample"]["sessions_per_sequence"])
    for raw_year in spec["date_range"]["years"]:
        year = int(raw_year)
        dates = [pd.Timestamp(value) for value in spec["fixed_five_session_blocks"][str(year)]]
        year_rows = eligible_rows.loc[eligible_rows["trade_date"].isin(dates)].copy()
        sequence_counts = year_rows.groupby("symbol", sort=False)["trade_date"].nunique()
        complete_symbols = sequence_counts.loc[sequence_counts == block_size].index.astype(str)
        for market_view in spec["sample"]["market_views"]:
            candidates = pd.Series(complete_symbols, dtype=str)
            candidates = candidates.loc[_view_mask(candidates, market_view)].tolist()
            ordered = sorted(
                candidates,
                key=lambda symbol: (
                    _selection_hash("MARKET", year, market_view, symbol),
                    symbol,
                ),
            )
            if len(ordered) < count:
                raise SupportDataError(
                    f"insufficient complete sequences: {year}:{market_view}:{len(ordered)}"
                )
            for rank, symbol in enumerate(ordered[:count], start=1):
                for relative_day, trade_date in zip(range(-5, 0), dates, strict=True):
                    rows.append(
                        {
                            "audit_id": (
                                f"MARKET|{year}|{market_view}|{rank:02d}|"
                                f"{symbol}|{trade_date.date()}"
                            ),
                            "cohort": "COORDINATE_ELIGIBLE_MARKET_SEQUENCE",
                            "market_view": market_view,
                            "symbol": symbol,
                            "source_symbol": symbol[:6],
                            "trade_date": trade_date,
                            "target_year": year,
                            "market_sequence_rank": rank,
                            "relative_day": relative_day,
                            "action_selection_rank": pd.NA,
                        }
                    )
    output = pd.DataFrame(rows)
    if len(output) != spec["sample"]["expected_market_rows"]:
        raise SupportDataError("market sequence row count mismatch")
    counts = output.groupby(["target_year", "market_view"]).agg(
        rows=("audit_id", "size"), symbols=("symbol", "nunique")
    )
    if not (counts["rows"].eq(count * block_size) & counts["symbols"].eq(count)).all():
        raise SupportDataError("market sequence cell conservation failed")
    if output.duplicated(["target_year", "market_view", "symbol", "trade_date"]).any():
        raise SupportDataError("duplicate source key within market sequence")
    return output


def build_sample(connection: Any, spec: dict[str, Any]) -> pd.DataFrame:
    all_dates = [
        pd.Timestamp(value)
        for dates in spec["fixed_five_session_blocks"].values()
        for value in dates
    ]
    date_frame = pd.DataFrame({"trade_date": all_dates})
    connection.register("fixed_sample_dates", date_frame)
    eligible = connection.execute(
        """
        SELECT c.trade_date,c.symbol
        FROM coordinate c JOIN fixed_sample_dates d USING(trade_date)
        WHERE c.coordinate_eligible
        ORDER BY c.trade_date,c.symbol
        """
    ).df()
    eligible["trade_date"] = pd.to_datetime(eligible["trade_date"], errors="raise")
    market = _select_market_sequences(eligible, spec)

    candidates = connection.execute(
        """
        SELECT trade_date,symbol,extract(year FROM trade_date)::INTEGER AS target_year
        FROM coordinate
        WHERE coordinate_eligible AND corporate_action_count>0
          AND corporate_action_available_date IS NOT NULL
          AND corporate_action_available_date<=trade_date
          AND corporate_action_blocking IS FALSE
          AND coalesce(rights_ratio,0)=0 AND coalesce(share_multiplier,1)>0
          AND month(trade_date)>=3
        ORDER BY trade_date,symbol
        """
    ).df()
    action_rows: list[dict[str, Any]] = []
    action_count = int(spec["sample"]["supported_action_sessions_per_year"])
    for raw_year in spec["date_range"]["years"]:
        year = int(raw_year)
        cell = candidates.loc[candidates["target_year"] == year].copy()
        cell["selection_hash"] = [
            _selection_hash(
                "ACTION", year, "ACTION_AUDIT", str(row.symbol),
                pd.Timestamp(row.trade_date).strftime("%Y-%m-%d"),
            )
            for row in cell.itertuples(index=False)
        ]
        cell = cell.sort_values(["selection_hash", "symbol", "trade_date"])
        if len(cell) < action_count:
            raise SupportDataError(f"insufficient supported actions: {year}:{len(cell)}")
        for rank, row in enumerate(cell.head(action_count).itertuples(index=False), start=1):
            symbol = str(row.symbol)
            trade_date = pd.Timestamp(row.trade_date)
            action_rows.append(
                {
                    "audit_id": f"ACTION|{year}|{rank:02d}|{symbol}|{trade_date.date()}",
                    "cohort": "SUPPORTED_ACTION_AUDIT",
                    "market_view": "ACTION_AUDIT",
                    "symbol": symbol,
                    "source_symbol": symbol[:6],
                    "trade_date": trade_date,
                    "target_year": year,
                    "market_sequence_rank": pd.NA,
                    "relative_day": pd.NA,
                    "action_selection_rank": rank,
                }
            )
    action = pd.DataFrame(action_rows)
    sample = pd.concat([market, action], ignore_index=True)
    for field in ["market_sequence_rank", "relative_day", "action_selection_rank"]:
        sample[field] = sample[field].astype("Int64")
    if len(sample) != spec["sample"]["expected_cohort_rows"]:
        raise SupportDataError("combined 002 sample cohort count mismatch")
    if sample["audit_id"].duplicated().any():
        raise SupportDataError("duplicate 002 audit cohort identity")
    action_counts = action.groupby("target_year").size()
    if len(action_counts) != 6 or not action_counts.eq(action_count).all():
        raise SupportDataError("002 action cohort year count mismatch")
    return sample.sort_values(["target_year", "cohort", "audit_id"]).reset_index(drop=True)


def fetch_target_coordinates(connection: Any, sample: pd.DataFrame) -> pd.DataFrame:
    coordinates = _parent_fetch_target_coordinates(connection, sample)
    for field in ["up_limit_price", "down_limit_price"]:
        values = pd.to_numeric(coordinates[field], errors="coerce")
        if not (np.isfinite(values) & (values > 0)).all():
            first = coordinates.loc[~(np.isfinite(values) & (values > 0))].iloc[0]
            raise SupportDataError(
                f"target limit field invalid: {field}:{first.symbol}:{first.trade_date}"
            )
    available = pd.to_datetime(coordinates["available_at"], errors="raise")
    decision = pd.to_datetime(coordinates["decision_at"], errors="raise")
    if not available.le(decision).all():
        first = coordinates.loc[~available.le(decision)].iloc[0]
        raise SupportDataError(f"target time travel: {first.symbol}:{first.trade_date}")
    return coordinates


def _render_report(result: dict[str, Any]) -> str:
    audit = result["coordinate_audit"]
    lines = [
        "# MKT-SUPPORT-DATA-002 objective support coordinate audit",
        "",
        "## Result",
        "",
        f"- Status: `{result['status']}`",
        f"- Cohort rows: {audit['cohort_rows']:,}; unique security-sessions: {audit['unique_sessions']:,}.",
        f"- Supported action cohort rows: {audit['supported_action_rows']}.",
        f"- Primary 20-session prior-low tests observed: {audit['primary_level_tests']} (feasibility diagnostic only).",
        f"- Full daily population cells passing: {result['population_audit']['passing_cells']}/{result['population_audit']['cells']}.",
        "- Market sequences were selected from CY-006 coordinate eligibility before minute behavior.",
        "- Descriptor availability is completed session 15:30; no intraday or same-session action is permitted.",
        "- This is coordinate feasibility, not evidence of support, defense, recovery, accumulation, prediction, or a strategy.",
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- Sample SHA-256: `{result['hashes']['sample_sha256']}`",
        f"- Coordinate audit SHA-256: `{result['hashes']['coordinate_audit_sha256']}`",
        f"- Population audit SHA-256: `{result['hashes']['population_audit_sha256']}`",
    ]
    return "\n".join(lines) + "\n"


parent.SPEC_PATH = SPEC_PATH
parent.SAMPLE_PATH = SAMPLE_PATH
parent.COORDINATE_AUDIT_PATH = COORDINATE_AUDIT_PATH
parent.POPULATION_AUDIT_PATH = POPULATION_AUDIT_PATH
parent.RESULT_PATH = RESULT_PATH
parent.REPORT_PATH = REPORT_PATH
parent._load_spec = _load_spec
parent.build_sample = build_sample
parent.fetch_target_coordinates = fetch_target_coordinates
parent._render_report = _render_report


def run(*, verify_partition_content: bool = True) -> dict[str, Any]:
    return parent.run(verify_partition_content=verify_partition_content)


if __name__ == "__main__":
    completed = run()
    print(
        json.dumps(
            {
                "status": completed["status"],
                "coordinate_audit": completed["coordinate_audit"],
                "population_audit": completed["population_audit"],
            },
            indent=2,
            sort_keys=True,
        )
    )
