#!/usr/bin/env python3
# ruff: noqa: E501
"""Roll the frozen V28/V28R1/V28R2 family through the mature 2026-08-03 cohort.

This is a post-observation reporting diagnostic.  It never edits a historical
freeze/result and it does not choose or change a rule.  The 2025 and mature
2026 V27 identities are filtered with the already-frozen V28-family gates,
then their already-completed V27 A67/H20 outcomes are replayed with the
unchanged Main/ChiNext K80 portfolio procedure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_demand_not_locked_v28r1 as v28r1,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_liquidity_trap_guard_v28 as v28,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_orderly_demand_v28r2 as v28r2,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_orderly_demand_v28r2_validation_2022_2024 as v28r2_validation,
)

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-V28-FAMILY-ROLLFORWARD-THROUGH-20260904-V1"
ROLL_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_v28_family_rollforward_through_20260904_v1"
)
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

DATA_END = pd.Timestamp("2026-09-04")
MATURE_SIGNAL_CUTOFF = pd.Timestamp("2026-08-03")
YEARS = tuple(range(2018, 2027))
NEW_YEARS = (2025, 2026)
PORTFOLIO_K = 80

V27_2024_2025_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_fresh_capitulation_snapback_v27_diagnostic_2024_2025_v1/"
    "diagnostic_2024_2025"
)
V27_2026_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_fresh_capitulation_snapback_v27_diagnostic_2026ytd_v1/"
    "diagnostic_2026ytd"
)
V27_2024_2025_FREEZE = OS_ROOT / (
    "artifacts/ASHARE-TRUE-GAP-BELOW-L-FRESH-CAPITULATION-SNAPBACK-"
    "V27-DIAGNOSTIC-2024-2025-V1_stage_a_freeze.json"
)
V27_2024_2025_RESULT = OS_ROOT / (
    "artifacts/ASHARE-TRUE-GAP-BELOW-L-FRESH-CAPITULATION-SNAPBACK-"
    "V27-DIAGNOSTIC-2024-2025-V1_result.json"
)
V27_2026_RESULT = OS_ROOT / (
    "artifacts/ASHARE-TRUE-GAP-BELOW-L-FRESH-CAPITULATION-SNAPBACK-"
    "V27-DIAGNOSTIC-2026YTD-V1_result.json"
)

ACCEPTED_COLUMNS = [
    "gap_id",
    "symbol",
    "board",
    "signal_date",
    "signal_time",
    "entry_date",
    "entry_time",
    "exit_date",
    "exit_time",
    "exit_reason",
    "net_return",
    "holding_sessions",
]


class RollforwardError(RuntimeError):
    """Fail closed on source drift, identity loss, or execution-rule drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RollforwardError(f"missing JSON source: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _project_accepted(path: Path) -> pd.DataFrame:
    """Use DuckDB projection to avoid a historical nested-list PyArrow defect."""
    if not path.is_file():
        raise RollforwardError(f"missing accepted-trade source: {path}")
    quoted = str(path).replace("'", "''")
    columns = ", ".join(ACCEPTED_COLUMNS)
    frame = duckdb.sql(
        f"SELECT {columns} FROM read_parquet('{quoted}')"
    ).df()
    for column in ("signal_date", "signal_time", "entry_date", "entry_time", "exit_date", "exit_time"):
        frame[column] = pd.to_datetime(frame[column])
    frame["completed"] = frame.exit_time.notna() & frame.exit_reason.notna() & frame.net_return.notna()
    return frame


def _read_parquet_compat(path: Path) -> pd.DataFrame:
    """Read old files despite a PyArrow repetition-histogram metadata defect."""
    try:
        return pd.read_parquet(path)
    except OSError as error:
        if "Repetition level histogram size mismatch" not in str(error):
            raise
        quoted = str(path).replace("'", "''")
        return duckdb.sql(f"SELECT * FROM read_parquet('{quoted}')").df()


def _normalize_times(frame: pd.DataFrame, include_exit: bool = False) -> pd.DataFrame:
    result = frame.copy()
    columns = ["signal_date", "signal_time", "entry_date", "entry_time"]
    if include_exit:
        columns.extend(["exit_date", "exit_time"])
    for column in columns:
        if column in result:
            result[column] = pd.to_datetime(result[column], errors="raise")
    return result


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RollforwardError(message)


def _close(left: Any, right: Any, label: str) -> None:
    if left is None and right is None:
        return
    _require(left is not None and right is not None, f"legacy statistic null mismatch: {label}")
    _require(math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12), f"legacy statistic drift: {label}: {left} != {right}")


def _summary_for_year(selected: pd.DataFrame, accepted: pd.DataFrame, year: int) -> dict[str, Any]:
    signal_rows = selected.loc[pd.to_datetime(selected.signal_date).dt.year.eq(year)].copy()
    accepted_rows = accepted.loc[pd.to_datetime(accepted.signal_date).dt.year.eq(year)].copy()
    completed = accepted_rows.completed.eq(True)
    values = pd.to_numeric(accepted_rows.loc[completed, "net_return"], errors="raise")
    holding = pd.to_numeric(accepted_rows.loc[completed, "holding_sessions"], errors="raise")
    reasons = accepted_rows.loc[completed, "exit_reason"].astype(str).value_counts().sort_index()
    return {
        "signals": len(signal_rows),
        "unique_signal_dates": int(
            pd.to_datetime(signal_rows.signal_date).dt.normalize().nunique()
        ),
        "executable_entries": int(signal_rows.entry_status.eq("EXECUTABLE_ENTRY").sum()),
        "accepted": len(accepted_rows),
        "completed": int(completed.sum()),
        "mean_net": None if values.empty else float(values.mean()),
        "median_net": None if values.empty else float(values.median()),
        "win": None if values.empty else float(values.gt(0).mean()),
        "severe10": None if values.empty else float(values.le(-0.10).mean()),
        "mean_holding_sessions": None if holding.empty else float(holding.mean()),
        "median_holding_sessions": None if holding.empty else float(holding.median()),
        "exit_reasons": {str(key): int(value) for key, value in reasons.items()},
    }


def _legacy_specifications() -> dict[str, list[dict[str, Any]]]:
    return {
        "V28": [
            {
                "years": (2018, 2019, 2020, 2021),
                "selected": v28.development_selected_path(),
                "accepted": v28.development_lane_root() / "portfolio_accepted.parquet",
                "outcomes": v28.development_lane_root() / "outcomes.parquet",
                "freeze": v28.STAGE_A_FREEZE,
                "result": v28.DEVELOPMENT_RESULT,
                "freeze_counts_path": ("development", "selected_by_signal_year"),
                "result_summary_path": ("accepted_summary", "yearly_by_signal_year"),
            },
            {
                "years": (2022, 2023, 2024),
                "selected": v28.diagnostic_selected_path(),
                "accepted": v28.diagnostic_lane_root() / "portfolio_accepted.parquet",
                "outcomes": v28.diagnostic_lane_root() / "outcomes.parquet",
                "freeze": v28.DIAGNOSTIC_STAGE_A_FREEZE,
                "result": v28.DIAGNOSTIC_RESULT,
                "freeze_counts_path": ("selected_by_signal_year",),
                "result_summary_path": ("accepted_summary", "yearly_by_signal_year"),
            },
        ],
        "V28R1": [
            {
                "years": (2018, 2019, 2020, 2021),
                "selected": v28r1.selected_path("DEVELOPMENT"),
                "accepted": v28r1.lane_root("DEVELOPMENT") / "portfolio_accepted.parquet",
                "outcomes": v28r1.lane_root("DEVELOPMENT") / "outcomes.parquet",
                "freeze": v28r1.STAGE_A_FREEZE,
                "result": v28r1.DEVELOPMENT_RESULT,
                "freeze_counts_path": ("development", "selected_by_signal_year"),
                "result_summary_path": ("accepted_summary", "yearly_by_signal_year"),
            },
            {
                "years": (2022, 2023, 2024),
                "selected": v28r1.selected_path("DIAGNOSTIC_2022_2024"),
                "accepted": v28r1.lane_root("DIAGNOSTIC_2022_2024") / "portfolio_accepted.parquet",
                "outcomes": v28r1.lane_root("DIAGNOSTIC_2022_2024") / "outcomes.parquet",
                "freeze": v28r1.DIAGNOSTIC_STAGE_A_FREEZE,
                "result": v28r1.DIAGNOSTIC_RESULT,
                "freeze_counts_path": ("selected_by_signal_year",),
                "result_summary_path": ("accepted_summary", "yearly_by_signal_year"),
            },
        ],
        "V28R2": [
            {
                "years": (2018, 2019, 2020, 2021),
                "selected": v28r2.selected_path(),
                "accepted": v28r2.lane_root() / "portfolio_accepted.parquet",
                "outcomes": v28r2.lane_root() / "outcomes.parquet",
                "freeze": v28r2.STAGE_A_FREEZE,
                "result": v28r2.DEVELOPMENT_RESULT,
                "freeze_counts_path": ("development", "selected_by_signal_year"),
                "result_summary_path": ("accepted_summary", "yearly_by_signal_year"),
            },
            {
                "years": (2022, 2023, 2024),
                "selected": v28r2_validation.SELECTED,
                "accepted": v28r2_validation.LANE_ROOT / "portfolio_accepted.parquet",
                "outcomes": v28r2_validation.LANE_ROOT / "outcomes.parquet",
                "freeze": v28r2_validation.IDENTITY_FREEZE,
                "result": v28r2_validation.DIAGNOSTIC_RESULT,
                "freeze_counts_path": ("diagnostic", "selected_by_signal_year"),
                "result_summary_path": ("detailed_summary", "yearly_by_signal_year"),
            },
        ],
    }


def _at(value: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for key in path:
        current = current[key]
    return current


def verify_and_load_legacy() -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, Any]]:
    selected_by_strategy: dict[str, list[pd.DataFrame]] = {name: [] for name in _legacy_specifications()}
    outcomes_by_strategy: dict[str, list[pd.DataFrame]] = {name: [] for name in _legacy_specifications()}
    accepted_by_strategy: dict[str, list[pd.DataFrame]] = {name: [] for name in _legacy_specifications()}
    verification: dict[str, Any] = {}
    for strategy, periods in _legacy_specifications().items():
        verification[strategy] = []
        for period in periods:
            freeze = _read_json(period["freeze"])
            result = _read_json(period["result"])
            selected = _normalize_times(_read_parquet_compat(period["selected"]))
            accepted = _project_accepted(period["accepted"])
            outcomes = _normalize_times(_read_parquet_compat(period["outcomes"]), include_exit=True)
            _require(not selected.gap_id.duplicated().any(), f"legacy duplicate selected gap: {strategy}")
            _require(not outcomes.gap_id.duplicated().any(), f"legacy duplicate outcome gap: {strategy}")
            expected_selected_hash = (
                freeze.get("development", {}).get("selected_entries_sha256")
                or freeze.get("selected_entries_sha256")
                or freeze.get("diagnostic", {}).get("selected_entries_sha256")
            )
            _require(expected_selected_hash == sha256(period["selected"]), f"legacy frozen selected hash drift: {strategy}")
            expected_counts = _at(freeze, period["freeze_counts_path"])
            expected_yearly = _at(result, period["result_summary_path"])
            for year in period["years"]:
                actual = _summary_for_year(selected, accepted, year)
                expected = expected_yearly[str(year)]
                _require(actual["signals"] == int(expected_counts[str(year)]), f"legacy signal count drift: {strategy} {year}")
                _require(actual["accepted"] == int(expected["trades"]), f"legacy accepted count drift: {strategy} {year}")
                _close(actual["mean_net"], expected["mean_net"], f"{strategy} {year} mean_net")
                _close(actual["median_net"], expected["median_net"], f"{strategy} {year} median_net")
                _close(actual["win"], expected["win"], f"{strategy} {year} win")
                _close(actual["severe10"], expected["severe10"], f"{strategy} {year} severe10")
                expected_holding = expected.get("average_holding_sessions")
                _close(actual["mean_holding_sessions"], expected_holding, f"{strategy} {year} mean holding")
            selected_by_strategy[strategy].append(selected)
            outcomes_by_strategy[strategy].append(outcomes)
            accepted_by_strategy[strategy].append(accepted)
            verification[strategy].append(
                {
                    "years": list(period["years"]),
                    "selected_sha256": sha256(period["selected"]),
                    "accepted_sha256": sha256(period["accepted"]),
                    "outcomes_sha256": sha256(period["outcomes"]),
                    "frozen_annual_statistics_reproduced": True,
                }
            )
    return (
        {key: pd.concat(value, ignore_index=True, sort=False) for key, value in selected_by_strategy.items()},
        {key: pd.concat(value, ignore_index=True, sort=False) for key, value in outcomes_by_strategy.items()},
        {key: pd.concat(value, ignore_index=True, sort=False) for key, value in accepted_by_strategy.items()},
        verification,
    )


def verify_later_sources() -> dict[str, str]:
    required = [
        V27_2024_2025_FREEZE,
        V27_2024_2025_RESULT,
        V27_2026_RESULT,
        V27_2024_2025_ROOT / "entries.parquet",
        V27_2024_2025_ROOT / "outcomes.parquet",
        V27_2024_2025_ROOT / "outcome_daily.parquet",
        V27_2026_ROOT / "entries.parquet",
        V27_2026_ROOT / "outcomes.parquet",
        V27_2026_ROOT / "outcome_daily.parquet",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    _require(not missing, f"missing later V27 source: {missing}")
    freeze_2024_2025 = _read_json(V27_2024_2025_FREEZE)
    result_2024_2025 = _read_json(V27_2024_2025_RESULT)
    result_2026 = _read_json(V27_2026_RESULT)
    checks = {
        V27_2024_2025_ROOT / "entries.parquet": freeze_2024_2025["population"]["hashes"]["entries"],
        V27_2024_2025_ROOT / "outcomes.parquet": result_2024_2025["hashes"]["outcomes"],
        V27_2024_2025_ROOT / "outcome_daily.parquet": result_2024_2025["hashes"]["outcome_daily"],
        V27_2026_ROOT / "entries.parquet": result_2026["hashes"]["entries"],
        V27_2026_ROOT / "outcomes.parquet": result_2026["hashes"]["outcomes"],
        V27_2026_ROOT / "outcome_daily.parquet": sha256(V27_2026_ROOT / "outcome_daily.parquet"),
    }
    for path, expected in checks.items():
        _require(sha256(path) == expected, f"later V27 source hash drift: {path}")
    _require(result_2026.get("data_end") == str(DATA_END.date()), "2026 V27 data-end drift")
    _require(result_2026.get("fully_mature_signal_cutoff") == str(MATURE_SIGNAL_CUTOFF.date()), "2026 mature-cutoff drift")
    return {str(path): sha256(path) for path in required}


def _build_new_identities() -> dict[str, pd.DataFrame]:
    sources = {
        2025: V27_2024_2025_ROOT / "entries.parquet",
        2026: V27_2026_ROOT / "entries.parquet",
    }
    selected: dict[str, list[pd.DataFrame]] = {"V28": [], "V28R1": [], "V28R2": []}
    for year, path in sources.items():
        entries = _normalize_times(_read_parquet_compat(path))
        entries = entries.loc[entries.signal_date.dt.year.eq(year)].copy()
        _require(not entries.empty and not entries.gap_id.duplicated().any(), f"V27 parent identity failure: {year}")
        if year == 2026:
            _require(entries.signal_date.max().normalize() <= MATURE_SIGNAL_CUTOFF, "right-censored 2026 signal entered mature cohort")

        featured = v28.attach_prior_limit_down_feature(entries, v28.load_cy033_feature_daily((year,)))
        featured = v28.load_signal_state(featured, (year,))
        featured["v28_liquidity_trap_gate"] = featured.liquidity_trap_guard
        featured["v28_signal_non_st_gate"] = featured.signal_is_st.eq(False).fillna(False)
        featured["v28_feature_latest_timestamp"] = featured.signal_state_available_at
        featured["v28_feature_uses_post_signal_information"] = False
        v28_selected = featured.loc[v28.v28_admission_mask(featured)].copy()

        r1_featured = v28r1.attach_signal_price_state(v28_selected, (year,))
        r1_featured["v28r1_demand_not_locked_gate"] = v28r1.demand_not_locked_mask(r1_featured)
        r1_featured["v28r1_feature_latest_timestamp"] = r1_featured.signal_price_available_at
        r1_featured["v28r1_feature_uses_post_signal_information"] = False
        r1_selected = r1_featured.loc[r1_featured.v28r1_demand_not_locked_gate].copy()

        amount_daily = v28r2.load_cy033_amount_daily((year - 1, year))
        r2_featured = v28r2.attach_orderly_amount_feature(r1_selected, amount_daily)
        r2_selected = r2_featured.loc[r2_featured.v28r2_orderly_amount_gate].copy()

        for name, frame in (("V28", v28_selected), ("V28R1", r1_selected), ("V28R2", r2_selected)):
            frame = frame.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
            _require(not frame.empty and not frame.gap_id.duplicated().any(), f"new selected identity failure: {name} {year}")
            executable = frame.entry_status.eq("EXECUTABLE_ENTRY")
            _require(
                (frame.loc[executable, "entry_time"] > frame.loc[executable, "signal_time"]).all(),
                f"T+1/strict-after-signal failure: {name} {year}",
            )
            selected[name].append(frame)

        _require(set(r2_selected.gap_id.astype(str)) <= set(r1_selected.gap_id.astype(str)), f"R2 not subset of R1: {year}")
        _require(set(r1_selected.gap_id.astype(str)) <= set(v28_selected.gap_id.astype(str)), f"R1 not subset of V28: {year}")
    return {key: pd.concat(value, ignore_index=True, sort=False) for key, value in selected.items()}


def _build_daily_2022_2026() -> tuple[pd.DataFrame, dict[str, Any]]:
    source_paths = [
        v28.replay.source_paths("POST_OBSERVATION_DIAGNOSTIC")["outcome_daily"],
        V27_2024_2025_ROOT / "outcome_daily.parquet",
        V27_2026_ROOT / "outcome_daily.parquet",
    ]
    pieces: list[pd.DataFrame] = []
    for priority, path in enumerate(source_paths):
        frame = _read_parquet_compat(path)
        frame["trade_date"] = pd.to_datetime(frame.trade_date, errors="raise").dt.normalize()
        frame = frame.loc[frame.trade_date.dt.year.between(2022, 2026)].copy()
        frame["_source_priority"] = priority
        pieces.append(frame)
    combined = pd.concat(pieces, ignore_index=True, sort=False)
    duplicate = combined.duplicated(["symbol", "trade_date"], keep=False)
    duplicate_keys = int(combined.loc[duplicate, ["symbol", "trade_date"]].drop_duplicates().shape[0])
    if duplicate.any():
        replay_fields = ["open", "high", "low", "close", "cal_idx"]
        inconsistent = combined.loc[duplicate].groupby(["symbol", "trade_date"])[replay_fields].nunique(dropna=False).gt(1).any(axis=1)
        _require(not inconsistent.any(), "overlapping daily source disagrees on raw OHLC/calendar")
    combined = combined.sort_values(["symbol", "trade_date", "_source_priority"], kind="mergesort")
    combined = combined.drop_duplicates(["symbol", "trade_date"], keep="last").drop(columns="_source_priority")
    _require(not combined.duplicated(["symbol", "trade_date"]).any(), "daily deduplication failure")
    _require(combined.trade_date.max().normalize() == DATA_END, "combined daily does not reach data end")
    audit = {
        "source_paths": [str(path) for path in source_paths],
        "source_hashes": {str(path): sha256(path) for path in source_paths},
        "overlapping_symbol_date_keys": duplicate_keys,
        "overlap_raw_ohlc_calendar_mismatch_count": 0,
        "overlap_resolution": "prefer the later purpose-built source; coordinate columns are not used by K80 replay",
        "rows": len(combined),
        "minimum_trade_date": str(combined.trade_date.min().date()),
        "maximum_trade_date": str(combined.trade_date.max().date()),
    }
    return combined, audit


def _attach_new_outcomes(selected: pd.DataFrame) -> pd.DataFrame:
    source = pd.concat(
        [
            _read_parquet_compat(V27_2024_2025_ROOT / "outcomes.parquet"),
            _read_parquet_compat(V27_2026_ROOT / "outcomes.parquet"),
        ],
        ignore_index=True,
        sort=False,
    )
    source = _normalize_times(source, include_exit=True)
    _require(not source.gap_id.duplicated().any(), "duplicate later V27 outcome identity")
    executable = selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY")]
    ids = set(executable.gap_id.astype(str))
    outcomes = source.loc[source.gap_id.astype(str).isin(ids)].copy()
    _require(len(outcomes) == len(ids), "later outcome identity conservation failure")
    _require(set(outcomes.gap_id.astype(str)) == ids, "later outcome identity set mismatch")
    _require(outcomes.exit_time.notna().all() and outcomes.net_return.notna().all(), "incomplete later outcome")
    _require(outcomes.exit_date.max().normalize() <= DATA_END, "outcome beyond authorized data end")
    return outcomes.sort_values(["entry_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)


def _run_new_portfolio(strategy: str, outcomes: pd.DataFrame, daily: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    lane = ROLL_ROOT / strategy.lower() / "rollforward_2025_2026"
    lane.mkdir(parents=True, exist_ok=True)
    old_k = v28.replay.repair.v1.PORTFOLIO_K
    try:
        v28.replay.repair.v1.PORTFOLIO_K = PORTFOLIO_K
        v28.replay.repair.v1.configure_external(lane, pd.Timestamp(outcomes.exit_date.max()).normalize())
        portfolio = v28.replay.repair.v1.run_portfolio(outcomes, daily, NEW_YEARS)
    finally:
        v28.replay.repair.v1.PORTFOLIO_K = old_k
    _require(portfolio["audit"]["capacity_skips"] == 0, f"unexpected new-period capacity skip: {strategy}")
    _require(portfolio["audit"]["max_k_violation_count"] == 0, f"K80 violation: {strategy}")
    accepted = _project_accepted(lane / "portfolio_accepted.parquet")
    _require(accepted.completed.all(), f"incomplete accepted trade: {strategy}")
    return portfolio, accepted


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.2f}%"


def _render_report(result: dict[str, Any]) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        "This is a post-observation roll-forward of unchanged frozen rules, not a new external validation and not a parameter-selection exercise.",
        "",
        f"Data end: `{result['data_end']}`. 2026 includes only parent V27 signals formed on or before `{result['fully_mature_signal_cutoff']}`, so every admitted entry has a completed A67/H20 outcome.",
        "",
    ]
    for strategy in ("V28", "V28R1", "V28R2"):
        lines.extend(
            [
                f"## {strategy}",
                "",
                "|Signal year|Signals|Signal dates|Executable|Accepted|Completed|Mean net|Median net|Win|Severe <= -10%|Mean hold|Median hold|Exit reasons|",
                "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---|",
            ]
        )
        for year in YEARS:
            row = result["strategies"][strategy]["yearly_by_signal_year"][str(year)]
            mean_holding = (
                "—"
                if row["mean_holding_sessions"] is None
                else f"{row['mean_holding_sessions']:.2f}"
            )
            median_holding = (
                "—"
                if row["median_holding_sessions"] is None
                else f"{row['median_holding_sessions']:.2f}"
            )
            lines.append(
                f"|{year}|{row['signals']}|{row['unique_signal_dates']}|{row['executable_entries']}|{row['accepted']}|{row['completed']}|"
                f"{_pct(row['mean_net'])}|{_pct(row['median_net'])}|{_pct(row['win'])}|{_pct(row['severe10'])}|"
                f"{mean_holding}|{median_holding}|"
                f"{json.dumps(row['exit_reasons'], ensure_ascii=False, sort_keys=True)}|"
            )
        lines.append("")
    lines.extend(
        [
            "## Limits",
            "",
            "2018-2021 are retrospective development results; 2022-2024 were already-opened diagnostics; 2025 and 2026 are now post-observation roll-forward diagnostics. 2026 is partial-year and right-censored after the mature-signal cutoff. CY-033 is PIT-B and its historical row inventory is conditional on physically present registered rows.",
            "",
        ]
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def run() -> dict[str, Any]:
    later_source_hashes = verify_later_sources()
    cy033_hashes = v28r2.verify_registered_cy033((2024, 2025, 2026))
    legacy_selected, legacy_outcomes, legacy_accepted, legacy_verification = verify_and_load_legacy()
    new_selected = _build_new_identities()
    daily, daily_audit = _build_daily_2022_2026()
    write_parquet(daily, ROLL_ROOT / "common/outcome_daily_2022_2026.parquet")

    # Publish the shared V28R2 parent bridge first.  Downstream frozen issuer
    # diagnostics may begin from these identities while the three portfolio
    # summaries below are still being materialized.
    new_outcomes_by_strategy = {
        strategy: _attach_new_outcomes(new_selected[strategy])
        for strategy in ("V28", "V28R1", "V28R2")
    }
    r2_all_selected = pd.concat(
        [legacy_selected["V28R2"], new_selected["V28R2"]],
        ignore_index=True,
        sort=False,
    )
    r2_parent_selected = r2_all_selected.loc[
        pd.to_datetime(r2_all_selected.signal_date).dt.year.between(2022, 2026)
    ].copy()
    r2_parent_outcomes = pd.concat(
        [
            legacy_outcomes["V28R2"].loc[
                legacy_outcomes["V28R2"].signal_date.dt.year.between(2022, 2024)
            ],
            new_outcomes_by_strategy["V28R2"],
        ],
        ignore_index=True,
        sort=False,
    )
    r2_parent_selected = r2_parent_selected.sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    r2_parent_outcomes = r2_parent_outcomes.sort_values(
        ["entry_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    _require(
        set(r2_parent_outcomes.gap_id.astype(str))
        == set(
            r2_parent_selected.loc[
                r2_parent_selected.entry_status.eq("EXECUTABLE_ENTRY"), "gap_id"
            ].astype(str)
        ),
        "V28R2 parent outcome identity conservation failure",
    )
    write_parquet(
        r2_parent_selected,
        ROLL_ROOT / "v28r2/selected_signals_2022_2026.parquet",
    )
    write_parquet(
        r2_parent_outcomes,
        ROLL_ROOT / "v28r2/outcomes_2022_2026.parquet",
    )

    strategies: dict[str, Any] = {}
    output_hashes: dict[str, str] = {}
    for strategy in ("V28", "V28R1", "V28R2"):
        new_outcomes = new_outcomes_by_strategy[strategy]
        portfolio, new_accepted = _run_new_portfolio(strategy, new_outcomes, daily)
        all_selected = pd.concat([legacy_selected[strategy], new_selected[strategy]], ignore_index=True, sort=False)
        all_selected = all_selected.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
        all_accepted = pd.concat([legacy_accepted[strategy], new_accepted], ignore_index=True, sort=False)
        all_accepted = all_accepted.sort_values(["entry_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
        _require(not all_selected.gap_id.duplicated().any(), f"full-period selected duplicate: {strategy}")
        _require(not all_accepted.gap_id.duplicated().any(), f"full-period accepted duplicate: {strategy}")

        strategy_root = ROLL_ROOT / strategy.lower()
        write_parquet(all_selected, strategy_root / "selected_signals_2018_2026.parquet")
        write_parquet(all_accepted, strategy_root / "portfolio_accepted_projection_2018_2026.parquet")
        outcomes_projection = pd.concat([legacy_outcomes[strategy], new_outcomes], ignore_index=True, sort=False)[ACCEPTED_COLUMNS]
        write_parquet(outcomes_projection, strategy_root / "outcomes_projection_2018_2026.parquet")

        yearly = {str(year): _summary_for_year(all_selected, all_accepted, year) for year in YEARS}
        strategies[strategy] = {
            "frozen_rule": {
                "V28": "V27 + signal non-ST + prior20 one-price-limit-down count <=1",
                "V28R1": "V28 + signal close strictly below up-limit price minus 0.006 CNY",
                "V28R2": "V28R1 + signal amount <=2.0x strict prior20 median amount",
            }[strategy],
            "unchanged_execution": "next legal 1m entry; A67 target below L; H20; no failure stop; 20bp/side; Main/ChiNext 50/50; K80/sleeve",
            "yearly_by_signal_year": yearly,
            "new_period_portfolio_audit": portfolio["audit"],
        }
        for path in strategy_root.glob("*.parquet"):
            output_hashes[str(path.relative_to(ROLL_ROOT))] = sha256(path)

    output_hashes["common/outcome_daily_2022_2026.parquet"] = sha256(ROLL_ROOT / "common/outcome_daily_2022_2026.parquet")
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "POST_OBSERVATION_UNCHANGED_RULE_ROLLFORWARD_NOT_PRISTINE_EXTERNAL_VALIDATION",
        "data_end": str(DATA_END.date()),
        "fully_mature_signal_cutoff": str(MATURE_SIGNAL_CUTOFF.date()),
        "calendar_scope": list(YEARS),
        "frozen_rules_changed": False,
        "T_plus_1_and_execution_changed": False,
        "cost_target_horizon_capacity_changed": False,
        "legacy_frozen_annual_statistics_reproduced": True,
        "legacy_verification": legacy_verification,
        "later_source_hashes": later_source_hashes,
        "registered_cy033_hashes": cy033_hashes,
        "daily_union_audit": daily_audit,
        "strategies": strategies,
        "output_hashes": output_hashes,
        "limitations": [
            "2018-2021 are retrospective development observations and 2022-2024 were previously opened diagnostics.",
            "2025 and mature 2026 are post-observation roll-forward diagnostics, not untouched confirmation.",
            "2026 is a partial year; signals after 2026-08-03 are excluded because they do not have a full H20-plus-exit tail by 2026-09-04.",
            "CY-033 is PIT-B and conditional on physically present registered rows; a complete survivorship-free historical security-master claim is unavailable.",
            "The legacy runners over-bound the mutable whole-registry file hash; this rollforward instead verifies the exact CY-033 manifest and partition hashes and records the current append-only registry hash.",
        ],
    }
    write_json(RESULT, result)
    _render_report(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    payload = run()
    print(json.dumps({"result": str(RESULT), "report": str(REPORT), "data_end": payload["data_end"]}, sort_keys=True))


if __name__ == "__main__":
    main()
