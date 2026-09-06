#!/usr/bin/env python3
# ruff: noqa: E501
"""Post-hoc <=2021 K80 replay for the frozen DAILY_NON_CHASING_2PCT gate.

This diagnostic reuses the existing A67/H20/40-bp outcomes and the exact
Main/ChiNext K80 portfolio constructor.  It does not rebuild lifecycle outcomes,
open validation sources, or mutate any strategy, registry, or frozen artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_liquidity_trap_guard_v28 as v28,
)

REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-NON-CHASING-K80-CAPACITY-DIAGNOSTIC-V1"
YEARS = (2018, 2019, 2020, 2021)
START = pd.Timestamp("2018-01-01")
CUTOFF = pd.Timestamp("2021-12-31")
THRESHOLD = 0.02
MAX_CLUSTER_DATE = pd.Timestamp("2018-10-26")

V28_OUTCOMES = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_orderly_demand_v28r2/development/"
    "orderly_demand/outcomes.parquet"
)
V28_ACCEPTED = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_orderly_demand_v28r2/development/"
    "orderly_demand/portfolio_accepted.parquet"
)
PARENT_DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_first_reversal_v13/prior_high_reversal/"
    "development/outcome_daily.parquet"
)
FEATURE_MATRIX = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_v29r2_development_morphology_audit_v1/"
    "candidate_feature_matrix.csv"
)
V29R2_STAGE_A = OS_ROOT / (
    "artifacts/ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-"
    "ISSUER-FACT-COOLDOWN-V29R2_stage_a_freeze.json"
)
V29R2_SELECTED = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_orderly_demand_issuer_fact_cooldown_v29r2/"
    "development/issuer_fact_selected_entries.parquet"
)
PORTFOLIO_RUNNER = Path(v28.replay.repair.v1.__file__).resolve()
PORTFOLIO_BASE = Path(v28.replay.repair.v1.base.__file__).resolve()

EXPECTED_HASHES = {
    V28_OUTCOMES: "9df6577d5e89ed0c30295af16b75bc1f16f4649a12c63969d48808384bde2988",
    V28_ACCEPTED: "13a97d3d5b34243c7c53a5395178a72c6c55316059d0f1e5e81b28e0e7c5993f",
    PARENT_DAILY: "c288f088c26657abc105f291e95217bdf79096bb5bc771cbc9d7e37c108b0d0f",
    FEATURE_MATRIX: "707d19363b8357c93ed121650b9b344ea5f52ab6610a8fde3cf79c883bb41415",
    V29R2_STAGE_A: "c9610486c2750ac40a6baee9f6aa74c5ef7daa35648bcd78074d5e3390e283df",
    V29R2_SELECTED: "dbb43e8c623a098d30f15e374f5d7d843241b232e72d9a107d25797f4f8f0c65",
    PORTFOLIO_RUNNER: "a342243d2cf3b72c390d69d58e07c4e80669c7ae9988f6977675860590a22ce5",
    PORTFOLIO_BASE: "3b536b131f4e89663d8cf2e4167a7f429274e304d14485194aca90f9670e91e4",
}

DEFAULT_OUT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_non_chasing_k80_capacity_diagnostic_v1"
)

LANES = {
    "V28R2_PARENT_PLUS_NON_CHASING": "v28r2_parent_plus_non_chasing",
    "V29R2_STAGE_A_SUBSET_PLUS_NON_CHASING": "v29r2_stage_a_subset_plus_non_chasing",
}


class DiagnosticError(RuntimeError):
    """Fail closed on lineage, chronology, or replay semantics."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DiagnosticError(message)


def sha256(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"missing/unsafe input: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        value = sha256(path)
        require(value == expected, f"input drift: {path}: {value}")
        actual[str(path)] = value
    stage_a = json.loads(V29R2_STAGE_A.read_text(encoding="utf-8"))
    development = stage_a.get("development", {})
    require(
        stage_a.get("stage")
        == "DEVELOPMENT_PREREGISTERED_IDENTITY_AND_EXECUTION_BINDING_BEFORE_OUTCOME_OPEN",
        "V29R2 Stage-A state drift",
    )
    require(development.get("selected_signals") == 362, "V29R2 selected count drift")
    require(
        development.get("selected_entries_sha256") == actual[str(V29R2_SELECTED)],
        "V29R2 selected hash not bound by Stage A",
    )
    return actual


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(
        path,
        json.dumps(json_ready(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, set[str], dict[str, Any]]:
    features = pd.read_csv(
        FEATURE_MATRIX,
        usecols=["gap_id", "signal_date", "stock_excess_market_1d"],
    )
    features["signal_date"] = pd.to_datetime(features.signal_date, errors="raise")
    require(len(features) == 355 and features.gap_id.nunique() == 355, "feature universe drift")
    require(features.stock_excess_market_1d.notna().all(), "frozen gate feature is missing")
    require(features.signal_date.max() <= CUTOFF, "post-2021 feature row")

    connection = duckdb.connect()
    protocol_outcomes = connection.execute(
        f"""
        SELECT * FROM read_parquet('{V28_OUTCOMES.as_posix()}')
        WHERE signal_date BETWEEN DATE '2018-01-01' AND DATE '2021-12-31'
        ORDER BY signal_date,symbol,gap_id
        """
    ).fetchdf()
    parent_accepted = connection.execute(
        f"""
        SELECT signal_date,entry_date,exit_date
        FROM read_parquet('{V28_ACCEPTED.as_posix()}')
        WHERE signal_date BETWEEN DATE '2018-01-01' AND DATE '2021-12-31'
        ORDER BY signal_date
        """
    ).fetchdf()
    selected = connection.execute(
        f"""
        SELECT gap_id,signal_date,entry_status
        FROM read_parquet('{V29R2_SELECTED.as_posix()}')
        WHERE signal_date BETWEEN DATE '2018-01-01' AND DATE '2021-12-31'
        ORDER BY signal_date,gap_id
        """
    ).fetchdf()
    connection.close()
    require(
        len(protocol_outcomes) == 355 and protocol_outcomes.gap_id.nunique() == 355,
        "V28 outcome drift",
    )
    require(len(parent_accepted) == 255, "V28 accepted count drift")
    require(len(selected) == 362 and selected.gap_id.nunique() == 362, "V29R2 selection drift")
    require(selected.entry_status.eq("EXECUTABLE_ENTRY").sum() == 347, "V29R2 executable count drift")

    for column in ("signal_date", "entry_date", "exit_date", "entry_time", "exit_time"):
        protocol_outcomes[column] = pd.to_datetime(
            protocol_outcomes[column], errors="raise"
        )
    for column in ("signal_date", "entry_date", "exit_date"):
        parent_accepted[column] = pd.to_datetime(
            parent_accepted[column], errors="raise"
        )
    selected["signal_date"] = pd.to_datetime(selected.signal_date, errors="raise")
    require(protocol_outcomes.signal_date.min() >= START, "pre-development outcome")
    require(protocol_outcomes.signal_date.max() <= CUTOFF, "post-2021 signal outcome")
    cross_boundary = protocol_outcomes.exit_date.gt(CUTOFF)
    parent_accepted_cross_boundary = parent_accepted.exit_date.gt(CUTOFF)
    outcomes = protocol_outcomes.loc[
        protocol_outcomes.entry_date.le(CUTOFF)
        & protocol_outcomes.exit_date.le(CUTOFF)
    ].copy()
    require(outcomes.exit_date.max() <= CUTOFF, "strict-calendar outcome breach")
    require((outcomes.entry_date > outcomes.signal_date).all(), "same-bar entry")
    require(outcomes.entry_status.eq("EXECUTABLE_ENTRY").all(), "non-executable outcome")
    require(outcomes.alpha.eq(0.67).all(), "A67 drift")
    require(outcomes.horizon.eq(20).all(), "H20 drift")
    require(outcomes.stop.eq("NONE").all(), "stop drift")
    require(v28.replay.repair.v1.COST == 0.002, "40-bp round-trip cost drift")

    outcomes = outcomes.merge(
        features[["gap_id", "stock_excess_market_1d"]],
        on="gap_id",
        validate="one_to_one",
    )
    require(len(outcomes) == 355, "feature-outcome identity loss")
    outcomes["daily_non_chasing_2pct"] = outcomes.stock_excess_market_1d.le(THRESHOLD)
    require(outcomes.daily_non_chasing_2pct.sum() == 265, "frozen gate pass count drift")
    v29_ids = set(
        selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY"), "gap_id"].astype(str)
    )
    require(v29_ids.issubset(set(outcomes.gap_id.astype(str))), "V29R2 outcome join gap")

    maximum_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    connection = duckdb.connect()
    daily = connection.execute(
        f"""
        SELECT * FROM read_parquet('{PARENT_DAILY.as_posix()}')
        WHERE trade_date>=DATE '2018-01-01' AND trade_date<=?
        ORDER BY symbol,trade_date
        """,
        [maximum_exit],
    ).fetchdf()
    connection.close()
    daily["trade_date"] = pd.to_datetime(daily.trade_date, errors="raise")
    require(not daily.empty, "empty daily replay frame")
    require(daily.trade_date.min() >= START, "pre-2018 daily row materialized")
    require(daily.trade_date.max() <= maximum_exit <= CUTOFF, "post-2021 daily row materialized")
    require(not daily.duplicated(["symbol", "trade_date"]).any(), "duplicate daily state")
    input_audit = {
        "v28_protocol_signal_outcomes": len(protocol_outcomes),
        "v28_strict_calendar_outcomes": len(outcomes),
        "v28_outcomes_excluded_for_exit_after_2021": int(cross_boundary.sum()),
        "v28_outcome_maximum_signal_date": protocol_outcomes.signal_date.max(),
        "v28_outcome_maximum_entry_date": protocol_outcomes.entry_date.max(),
        "v28_outcome_maximum_exit_date": protocol_outcomes.exit_date.max(),
        "v28_frozen_accepted": len(parent_accepted),
        "v28_frozen_accepted_exiting_after_2021": int(
            parent_accepted_cross_boundary.sum()
        ),
        "v28_frozen_accepted_maximum_signal_date": parent_accepted.signal_date.max(),
        "v28_frozen_accepted_maximum_entry_date": parent_accepted.entry_date.max(),
        "v28_frozen_accepted_maximum_exit_date": parent_accepted.exit_date.max(),
        "protocol_and_strict_calendar_candidate_identity_equal": bool(
            not cross_boundary.any()
        ),
        "frozen_gate_pass": int(outcomes.daily_non_chasing_2pct.sum()),
        "v29r2_selected_signals": len(selected),
        "v29r2_executable_outcome_matches": len(v29_ids),
        "v29r2_and_gate_pass": int(
            (
                outcomes.gap_id.astype(str).isin(v29_ids)
                & outcomes.daily_non_chasing_2pct
            ).sum()
        ),
        "daily_materialized_minimum_date": daily.trade_date.min(),
        "daily_materialized_maximum_date": daily.trade_date.max(),
        "maximum_exit_date": maximum_exit,
    }
    require(input_audit["v29r2_and_gate_pass"] == 260, "V29R2 plus gate count drift")
    return outcomes, daily, v29_ids, input_audit


def trade_stats(frame: pd.DataFrame) -> dict[str, Any]:
    work = frame.copy()
    work["signal_date"] = pd.to_datetime(work.signal_date, errors="raise").dt.normalize()
    work["signal_year"] = work.signal_date.dt.year
    require(work.signal_year.isin(YEARS).all(), "accepted signal year outside development")
    values = work.net_return.astype(float)
    yearly: dict[str, Any] = {}
    for year in YEARS:
        part = work.loc[work.signal_year.eq(year)]
        yearly[str(year)] = {
            "accepted": len(part),
            "mean_return": part.net_return.mean(),
            "median_return": part.net_return.median(),
            "win_rate": part.net_return.gt(0).mean() if len(part) else None,
            "severe10_rate": part.net_return.le(-0.10).mean() if len(part) else None,
            "mean_holding_sessions": part.holding_sessions.mean(),
            "median_holding_sessions": part.holding_sessions.median(),
        }
    return {
        "accepted": len(work),
        "accepted_per_year": len(work) / len(YEARS),
        "mean_return": values.mean(),
        "median_return": values.median(),
        "win_rate": values.gt(0).mean(),
        "severe10_rate": values.le(-0.10).mean(),
        "mean_holding_sessions": work.holding_sessions.mean(),
        "median_holding_sessions": work.holding_sessions.median(),
        "unique_signal_dates": work.signal_date.nunique(),
        "yearly": yearly,
    }


def date_equal_weight(frame: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    work = frame.copy()
    work["signal_date"] = pd.to_datetime(work.signal_date, errors="raise").dt.normalize()
    by_date = (
        work.groupby("signal_date", sort=True)
        .agg(
            accepted=("net_return", "size"),
            mean_return=("net_return", "mean"),
            median_return=("net_return", "median"),
            win_rate=("net_return", lambda x: x.gt(0).mean()),
            severe10_rate=("net_return", lambda x: x.le(-0.10).mean()),
            mean_holding_sessions=("holding_sessions", "mean"),
            median_holding_sessions=("holding_sessions", "median"),
        )
        .reset_index()
    )
    return (
        {
            "unique_signal_dates": len(by_date),
            "equal_weight_mean_return": by_date.mean_return.mean(),
            "median_of_date_mean_returns": by_date.mean_return.median(),
            "equal_weight_win_rate": by_date.win_rate.mean(),
            "equal_weight_severe10_rate": by_date.severe10_rate.mean(),
            "equal_weight_mean_holding_sessions": by_date.mean_holding_sessions.mean(),
            "largest_accepted_date": by_date.loc[by_date.accepted.idxmax(), "signal_date"],
            "largest_accepted_date_count": int(by_date.accepted.max()),
        },
        by_date,
    )


def read_parquet_frame(path: Path) -> pd.DataFrame:
    connection = duckdb.connect()
    frame = connection.execute(
        f"SELECT * FROM read_parquet('{path.as_posix()}')"
    ).fetchdf()
    connection.close()
    return frame


def replay_lane(
    root: Path,
    candidates: pd.DataFrame,
    daily: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    require(not candidates.empty, "empty replay candidates")
    for column in ("signal_date", "entry_date", "exit_date"):
        values = pd.to_datetime(candidates[column], errors="raise")
        require(values.min() >= START and values.max() <= CUTOFF, f"{column} outside boundary")
    root.mkdir(parents=True, exist_ok=False)
    engine = v28.replay.repair.v1
    maximum_exit = pd.Timestamp(candidates.exit_date.max()).normalize()
    old_k = engine.PORTFOLIO_K
    old_ext = engine.EXT
    old_end = engine.END
    old_outer_years = engine.base.OUTER_YEARS
    old_base_k = engine.base.K
    try:
        engine.PORTFOLIO_K = 80
        engine.configure_external(root, maximum_exit)
        portfolio = engine.run_portfolio(
            candidates,
            daily.loc[daily.trade_date.le(maximum_exit)].copy(),
            YEARS,
        )
    finally:
        engine.PORTFOLIO_K = old_k
        engine.configure_external(old_ext, old_end)
        engine.base.OUTER_YEARS = old_outer_years
        engine.base.K = old_base_k
    audit = portfolio["audit"]
    require(audit["max_k_violation_count"] == 0, "K80 violation")
    require(audit["negative_cash_or_leverage_count"] == 0, "cash/leverage violation")
    accepted_path = root / "portfolio_accepted.parquet"
    accepted = read_parquet_frame(accepted_path)
    require(not accepted.empty, "empty accepted output")
    require(set(accepted.gap_id.astype(str)).issubset(set(candidates.gap_id.astype(str))), "accepted identity outside candidates")
    require(pd.to_datetime(accepted.signal_date).max() <= CUTOFF, "post-2021 accepted row")
    return accepted, portfolio


def scenario_candidates(
    outcomes: pd.DataFrame,
    v29_ids: set[str],
    scenario: str,
) -> pd.DataFrame:
    mask = outcomes.daily_non_chasing_2pct
    if scenario == "V29R2_STAGE_A_SUBSET_PLUS_NON_CHASING":
        mask &= outcomes.gap_id.astype(str).isin(v29_ids)
    result = outcomes.loc[mask].copy()
    expected = 265 if scenario == "V28R2_PARENT_PLUS_NON_CHASING" else 260
    require(len(result) == expected, f"candidate count drift for {scenario}")
    return result


def annual_rows(scenario: str, sensitivity: str, stats: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "scenario": scenario,
            "sensitivity": sensitivity,
            "signal_year": year,
            **stats["yearly"][str(year)],
        }
        for year in YEARS
    ]


def output_hashes(root: Path) -> dict[str, str]:
    return {
        path.name: sha256(path)
        for path in sorted(root.iterdir())
        if path.is_file()
    }


def fmt_pct(value: float | None) -> str:
    return "—" if value is None or not math.isfinite(float(value)) else f"{value:+.2%}"


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        f"# {EXPERIMENT}",
        "",
        "Post-hoc 2018-2021 diagnostic. It replays true Main/ChiNext K80 capacity on the frozen A67/H20/no-stop/40-bp outcomes. Candidate counts are never reported as accepted counts. No validation source is opened.",
        "",
        "## Full capacity replays",
        "",
    ]
    for scenario in LANES:
        item = summary["scenarios"][scenario]
        stats = item["full"]["accepted_stats"]
        lines.extend(
            [
                f"### {scenario}",
                "",
                f"Candidates after gate: {item['full']['candidate_count']}; true K80 accepted: {stats['accepted']} ({stats['accepted_per_year']:.2f}/year). Mean {fmt_pct(stats['mean_return'])}, median {fmt_pct(stats['median_return'])}, win {fmt_pct(stats['win_rate'])}, severe10 {fmt_pct(stats['severe10_rate'])}, mean hold {stats['mean_holding_sessions']:.2f}.",
                "",
                f"Original protocol basis and strict all-materialized-rows <=2021-12-31 basis are identity-equal: {item['full']['protocol_vs_strict_calendar']['accepted_identity_equal']}; strict exclusion count: {item['full']['protocol_vs_strict_calendar']['excluded_cross_boundary_outcomes']}.",
                "",
                "|signal year|accepted|mean|median|win|severe10|mean hold|",
                "|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for year in YEARS:
            row = stats["yearly"][str(year)]
            lines.append(
                f"|{year}|{row['accepted']}|{fmt_pct(row['mean_return'])}|{fmt_pct(row['median_return'])}|{fmt_pct(row['win_rate'])}|{fmt_pct(row['severe10_rate'])}|{row['mean_holding_sessions']:.2f}|"
            )
        equal = item["full"]["signal_date_equal_weight"]
        drop = item["drop_2018_10_26"]["accepted_stats"]
        lines.extend(
            [
                "",
                f"Signal-date equal weight: {equal['unique_signal_dates']} dates, mean {fmt_pct(equal['equal_weight_mean_return'])}, win {fmt_pct(equal['equal_weight_win_rate'])}, severe10 {fmt_pct(equal['equal_weight_severe10_rate'])}, mean hold {equal['equal_weight_mean_holding_sessions']:.2f}.",
                "",
                f"After removing 2018-10-26 and rerunning capacity: candidates {item['drop_2018_10_26']['candidate_count']}; accepted {drop['accepted']} ({drop['accepted_per_year']:.2f}/year), mean {fmt_pct(drop['mean_return'])}, median {fmt_pct(drop['median_return'])}, win {fmt_pct(drop['win_rate'])}, severe10 {fmt_pct(drop['severe10_rate'])}, mean hold {drop['mean_holding_sessions']:.2f}; newly admitted replacements versus the full replay: {item['drop_2018_10_26']['newly_admitted_after_replay']}.",
                "",
            ]
        )
    lines.extend(
        [
            "## Boundary and interpretation",
            "",
            f"Frozen V28R2 outcome signal rows: {summary['input_audit']['v28_protocol_signal_outcomes']}; max signal/entry/exit {summary['input_audit']['v28_outcome_maximum_signal_date'][:10]} / {summary['input_audit']['v28_outcome_maximum_entry_date'][:10]} / {summary['input_audit']['v28_outcome_maximum_exit_date'][:10]}; excluded for exit after 2021: {summary['input_audit']['v28_outcomes_excluded_for_exit_after_2021']}.",
            "",
            f"Frozen V28R2 accepted rows: {summary['input_audit']['v28_frozen_accepted']}; max signal/entry/exit {summary['input_audit']['v28_frozen_accepted_maximum_signal_date'][:10]} / {summary['input_audit']['v28_frozen_accepted_maximum_entry_date'][:10]} / {summary['input_audit']['v28_frozen_accepted_maximum_exit_date'][:10]}; exiting after 2021: {summary['input_audit']['v28_frozen_accepted_exiting_after_2021']}.",
            "",
            f"Materialized daily rows are restricted to {summary['input_audit']['daily_materialized_minimum_date'][:10]} through {summary['input_audit']['daily_materialized_maximum_date'][:10]}. Maximum outcome exit is {summary['input_audit']['maximum_exit_date'][:10]}. The physical parent daily file is cross-period, but the SQL predicate prevents any post-2021 row from entering memory or replay.",
            "",
            "This is post-hoc development reuse, not an untouched test. The largest cluster sensitivity addresses concentration but does not create independence. No existing freeze, classifier, strategy, lifecycle, registry, or validation artifact was modified.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_root = args.output_root.resolve()
    require(not out_root.exists(), f"diagnostic output already exists: {out_root}")
    input_hashes = verify_inputs()
    outcomes, daily, v29_ids, input_audit = load_inputs()
    out_root.mkdir(parents=True, exist_ok=False)

    result: dict[str, Any] = {
        "experiment": EXPERIMENT,
        "scientific_status": "POST_HOC_DEVELOPMENT_CAPACITY_DIAGNOSTIC_NOT_VALIDATION",
        "semantics": {
            "gate": "signal-day stock return - cross-sectional market median <= 0.02",
            "gate_known_at": "signal close",
            "portfolio": "Main/ChiNext 50/50, K80 per sleeve",
            "target": "A67 below L",
            "horizon": "H20",
            "stop": "NONE",
            "round_trip_cost": 0.004,
        },
        "input_audit": input_audit,
        "scenarios": {},
        "boundary": {
            "allowed": "2018-01-01 through 2021-12-31",
            "post_2021_rows_materialized": False,
            "post_2021_validation_opened": False,
        },
    }
    annual_payload: list[dict[str, Any]] = []
    date_payload: list[pd.DataFrame] = []

    for scenario, directory in LANES.items():
        candidates = scenario_candidates(outcomes, v29_ids, scenario)
        full_root = out_root / directory / "full"
        full_accepted, full_portfolio = replay_lane(full_root, candidates, daily)
        full_stats = trade_stats(full_accepted)
        full_equal, full_dates = date_equal_weight(full_accepted)
        full_dates.insert(0, "sensitivity", "FULL")
        full_dates.insert(0, "scenario", scenario)
        date_payload.append(full_dates)
        annual_payload.extend(annual_rows(scenario, "FULL", full_stats))

        dropped_candidates = candidates.loc[
            pd.to_datetime(candidates.signal_date).dt.normalize().ne(MAX_CLUSTER_DATE)
        ].copy()
        drop_root = out_root / directory / "drop_2018_10_26"
        drop_accepted, drop_portfolio = replay_lane(drop_root, dropped_candidates, daily)
        drop_stats = trade_stats(drop_accepted)
        drop_equal, drop_dates = date_equal_weight(drop_accepted)
        drop_dates.insert(0, "sensitivity", "DROP_2018_10_26")
        drop_dates.insert(0, "scenario", scenario)
        date_payload.append(drop_dates)
        annual_payload.extend(annual_rows(scenario, "DROP_2018_10_26", drop_stats))

        full_noncluster_ids = set(
            full_accepted.loc[
                pd.to_datetime(full_accepted.signal_date).dt.normalize().ne(MAX_CLUSTER_DATE),
                "gap_id",
            ].astype(str)
        )
        drop_ids = set(drop_accepted.gap_id.astype(str))
        result["scenarios"][scenario] = {
            "full": {
                "candidate_count": len(candidates),
                "accepted_stats": full_stats,
                "protocol_vs_strict_calendar": {
                    "original_protocol_accepted_stats": full_stats,
                    "strict_calendar_le_2021_accepted_stats": full_stats,
                    "excluded_cross_boundary_outcomes": input_audit[
                        "v28_outcomes_excluded_for_exit_after_2021"
                    ],
                    "accepted_identity_equal": input_audit[
                        "protocol_and_strict_calendar_candidate_identity_equal"
                    ],
                },
                "signal_date_equal_weight": full_equal,
                "portfolio_audit": full_portfolio["audit"],
                "output_root": full_root,
                "output_hashes": output_hashes(full_root),
            },
            "drop_2018_10_26": {
                "candidate_count": len(dropped_candidates),
                "removed_candidate_count": len(candidates) - len(dropped_candidates),
                "accepted_stats": drop_stats,
                "signal_date_equal_weight": drop_equal,
                "portfolio_audit": drop_portfolio["audit"],
                "newly_admitted_after_replay": len(drop_ids - full_noncluster_ids),
                "output_root": drop_root,
                "output_hashes": output_hashes(drop_root),
            },
        }

    annual_path = out_root / "accepted_annual_stats.csv"
    date_path = out_root / "accepted_by_signal_date.csv"
    pd.DataFrame(annual_payload).to_csv(annual_path, index=False)
    pd.concat(date_payload, ignore_index=True).to_csv(date_path, index=False)
    report_path = out_root / "report.md"
    summary_path = out_root / "summary.json"
    manifest_path = out_root / "manifest.json"
    atomic_text(report_path, render_report(json_ready(result)))
    atomic_json(summary_path, result)
    manifest = {
        "experiment": EXPERIMENT,
        "runner": str(Path(__file__).resolve()),
        "runner_sha256": sha256(Path(__file__).resolve()),
        "input_sha256": input_hashes,
        "outputs": {
            "summary": {"path": str(summary_path), "sha256": sha256(summary_path)},
            "report": {"path": str(report_path), "sha256": sha256(report_path)},
            "annual": {"path": str(annual_path), "sha256": sha256(annual_path)},
            "signal_date": {"path": str(date_path), "sha256": sha256(date_path)},
        },
        "maximum_materialized_daily_date": input_audit["daily_materialized_maximum_date"],
        "maximum_outcome_exit_date": input_audit["maximum_exit_date"],
        "post_2021_rows_materialized": False,
        "post_2021_validation_opened": False,
        "existing_freeze_modified": False,
    }
    atomic_json(manifest_path, manifest)
    print(json.dumps(json_ready(result), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
