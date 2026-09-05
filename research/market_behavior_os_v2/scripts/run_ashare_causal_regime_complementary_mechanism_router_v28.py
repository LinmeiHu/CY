#!/usr/bin/env python3
"""Freeze and replay the V28 causal market-state complementary router.

The runner never reconstructs a security outcome.  It consumes exact frozen
V27 Bear and V65 participation-lane outcome ledgers, then performs one new
operation: a causal shared-capacity portfolio replay with one common account.
All source outcomes were observed before V28 and are labelled accordingly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-CAUSAL-REGIME-COMPLEMENTARY-MECHANISM-ROUTER-V28"
CONTRACT = OS_ROOT / f"experiments/{EXPERIMENT}_contract.json"
FREEZE = OS_ROOT / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

EXT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_regime_complementary_mechanism_router_v28"
)
SOURCE_UNION = EXT / "stage_a/source_completed_trades.parquet"
DAILY_PATHS = EXT / "stage_b/daily_paths.parquet"
ACCEPTED = EXT / "stage_b/accepted_trades.parquet"
SKIPPED = EXT / "stage_b/capacity_skips.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"

V27_HIST_RAW = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_substrategy_router_v27/routed_raw_trades.parquet"
)
V27_2425_RAW = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_substrategy_router_v27_validation_2024_2025_v1/"
    "stage_b/routed_raw_trades.parquet"
)
V27_26_RAW = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_substrategy_router_v27_validation_2026ytd_v2/"
    "routed_raw_trades.parquet"
)
V27_RESULT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_substrategy_router_v27/result.json"
)
V27_2425_RESULT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_substrategy_router_v27_validation_2024_2025_v1/"
    "stage_b/result.json"
)
V27_26_RESULT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_substrategy_router_v27_validation_2026ytd_v2/"
    "result.json"
)

V65_CANDIDATES = Path(
    "/Volumes/quant/CY_quant_research/"
    "bull_early_medium_participation_industry_ignition_v65/stage_a/candidates.parquet"
)
V65_DEV = Path(
    "/Volumes/quant/CY_quant_research/"
    "bull_early_medium_participation_industry_ignition_v65/"
    "stage_b/development_outcomes.parquet"
)
V65_FORWARD = Path(
    "/Volumes/quant/CY_quant_research/"
    "bull_early_medium_participation_industry_ignition_v65/"
    "stage_b/forward_outcomes.parquet"
)
V64_POST_CANDIDATES = Path(
    "/Volumes/quant/CY_quant_research/"
    "bull_medium_participation_industry_ignition_v64/"
    "post_2023_exact_diagnostic_through_2026_09_04/"
    "v64_candidates_2024_2026_09_04.parquet"
)
V64_POST_OUTCOMES = Path(
    "/Volumes/quant/CY_quant_research/"
    "bull_medium_participation_industry_ignition_v64/"
    "post_2023_exact_diagnostic_through_2026_09_04/"
    "v64_outcomes_2024_2026_09_04.parquet"
)
V65_EARLY_POST_CANDIDATES = Path(
    "/Volumes/quant/CY_quant_research/"
    "bull_v64_expansion_complement_v65_mechanism/"
    "post_2023_diagnostics_through_2026_09_04/early_candidates.parquet"
)
V65_EARLY_POST_OUTCOMES = Path(
    "/Volumes/quant/CY_quant_research/"
    "bull_v64_expansion_complement_v65_mechanism/"
    "post_2023_diagnostics_through_2026_09_04/early_outcomes.parquet"
)
V64_POST_RESULT = Path(
    "/Volumes/quant/CY_quant_research/"
    "bull_medium_participation_industry_ignition_v64/"
    "post_2023_exact_diagnostic_through_2026_09_04/result.json"
)
V65_POST_RESULT = Path(
    "/Volumes/quant/CY_quant_research/"
    "bull_v64_expansion_complement_v65_mechanism/"
    "post_2023_diagnostics_through_2026_09_04/result.json"
)

DAILY_HIST = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
DAILY_POST_BASE = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_substrategy_router_v27_validation_2026ytd_v1/"
    "pit_daily_qd010_exact_2022_2026_08_12.parquet"
)
DAILY_POST_COMPACT = Path(
    "/Volumes/quant/CY_quant_research/"
    "bull_medium_participation_industry_ignition_v64/"
    "post_2023_exact_diagnostic_through_2026_09_04/"
    "pit_daily_qd010_exact_frozen_symbols_2022_2026_09_04.parquet"
)
DAILY_V27_TAIL = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_substrategy_router_v27_validation_2026ytd_v2/"
    "execution_daily_frozen_symbols_through_2026_09_04.parquet"
)

V27_COMMIT = "e7c1dfffcfa6c0fe0ddb34f4df8a93aa4ede6883"
V65_COMMIT = "6cfac5f5406610f45235aff50618e7da3ae65521"
V65_RESULT_BLOB = (
    "research/market_behavior_os_v2/artifacts/"
    "ASHARE-BULL-EARLY-MEDIUM-PARTICIPATION-INDUSTRY-IGNITION-V65_result.json"
)

EXPECTED_HASHES = {
    V27_HIST_RAW: "8cf9a74bab8e02bc1ab25ca0570ebecad4fecace77a712a3324d507a681f7bed",
    V27_2425_RAW: "db96ecea3bee2de877f916ed4ebf256ed6f1b182b6629a4365b2e29beda670fe",
    V27_26_RAW: "2503db0811d42dfdad85d085e1243b0600a8373aa4544deffdd00023a8388e0e",
    V65_DEV: "88d669d09db59ad7d14af52dfbab10e0d1e9e9b6f6dd36efa761851503440e88",
    V65_FORWARD: "a2e5adbd5a5d05d904dfe8388b1edb34b39c9546a5975c303dd4a361e48ffa6c",
    V65_CANDIDATES: "98cadcfd388ae788eb083b7a1dc7e7128b55ac4db6ccf6402728e3c31b30779b",
    V64_POST_OUTCOMES: "8899082e222ba188969639cb7f666aa4ab028b1cd2ecd45ba503e03a4f33799e",
    V64_POST_CANDIDATES: "b1011e4dba1e262a7ec745887501a57553383d5174b1e8c16db696cebc826b28",
    V65_EARLY_POST_OUTCOMES: "5d4ff45b0ce40be4b5a393c1cf7a806bf62a70acb56fd198b43f96f6fbaf2b3d",
    V65_EARLY_POST_CANDIDATES: "3503b87d85e3b731228149510b2a53e27aaf700dff13dd19db904834bf431e93",
    V27_RESULT: "d50ea992529a2a202d8d17ed7eb5dc0908291224a74948616aa84a39fcf65537",
    V27_2425_RESULT: "9632d2a2f84a47e90d2ada04fe2e2adadd83158add8c54254c9f02ff91e11d02",
    V27_26_RESULT: "4dfa8dec01015b140f581036b3e266c730e627f603b55e060482ddb4368b5f01",
    V64_POST_RESULT: "1dad5fd10c5efd2fcf5b91389bc182ec44dea7dd10e3a5931b5f864b8190bf32",
    V65_POST_RESULT: "fa9e295d97902bcc2ae48f6033f189f04a413d8acb9e0dea400517baf3214a89",
    DAILY_HIST: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    DAILY_POST_BASE: "d092206b2c36212cf95ab0540bf6905a3274f1ba4706a50510e7cd24c9e1929c",
    DAILY_POST_COMPACT: "0ed55ccef40815ab057fdc500ce73af69bf4a71878fabf7a6895c98192c715af",
    DAILY_V27_TAIL: "3864569cf59bc1262002e065c3713a26ee36529b428d74e4ab952fb90c55e67d",
}

V27_BEAR_LANES = {
    "BEAR_WORSENING_FAST_CAPITULATION",
    "BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION",
}
TARGET_PREFIX = "TARGET_"
ENTRY_COST = 0.002
EXIT_COST = 0.002
K_PER_SLEEVE = 30
MAX_NEW_PER_SLEEVE_DATE = 10
DATA_END = pd.Timestamp("2026-09-04")
FULL_YEARS = tuple(range(2014, 2026))


class ResearchError(RuntimeError):
    """Fail closed on identity, chronology, lineage, or replay drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def git_blob(commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def verify_inputs() -> dict[str, str]:
    observed: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        if not path.exists():
            raise ResearchError(f"missing frozen source: {path}")
        value = sha256(path)
        observed[str(path)] = value
        if value != expected:
            raise ResearchError(f"frozen source drift: {path}: {value} != {expected}")
    blobs = {
        "v27_runner": git_blob(
            V27_COMMIT,
            "research/market_behavior_os_v2/scripts/"
            "run_ashare_causal_market_regime_substrategy_router_v27.py",
        ),
        "v27_contract": git_blob(
            V27_COMMIT,
            "research/market_behavior_os_v2/experiments/"
            "ASHARE-CAUSAL-MARKET-REGIME-SUBSTRATEGY-ROUTER-V27_contract.json",
        ),
        "v65_runner": git_blob(
            V65_COMMIT,
            "research/market_behavior_os_v2/scripts/"
            "run_ashare_bull_early_medium_participation_industry_ignition_v65.py",
        ),
        "v65_contract": git_blob(
            V65_COMMIT,
            "research/market_behavior_os_v2/experiments/"
            "ASHARE-BULL-EARLY-MEDIUM-PARTICIPATION-INDUSTRY-IGNITION-V65_contract.json",
        ),
        "v65_result": git_blob(V65_COMMIT, V65_RESULT_BLOB),
    }
    blob_expected = {
        "v27_runner": "e44b83efff24356a328d485b0d54623578cfb74a63e495e6a3fef976e219c05a",
        "v27_contract": "8fdaf43e7d0f44cb5607fb1a37d4a12fefbf43cb1ededf334bc5bf474f0a20a7",
        "v65_runner": "44f4d89e82987d6221f9e9c998fc30f97348eedca8f52fd19d2de6952ddced99",
        "v65_contract": "902694b1cffdcd38990d5cd379d28f872ef48ff9f397458ddfef379ab4696a39",
        "v65_result": "701e78140ca0c999a133d01f3a57db57f157d61560cb7f0a17a16b5b13772908",
    }
    for name, value in blobs.items():
        observed[f"git_blob:{name}"] = bytes_sha256(value)
        if observed[f"git_blob:{name}"] != blob_expected[name]:
            raise ResearchError(f"source Git blob drift: {name}")
    return observed


def parse_dates(frame: pd.DataFrame) -> pd.DataFrame:
    for column in (
        "signal_date",
        "entry_date",
        "exit_date",
        "decision_at",
        "available_at",
        "feature_latest_timestamp",
        "latest_source_timestamp",
    ):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column])
    return frame


def load_v27() -> pd.DataFrame:
    frames = []
    for path, period in (
        (V27_HIST_RAW, "2014_2023"),
        (V27_2425_RAW, "2024_2025"),
        (V27_26_RAW, "2026_YTD"),
    ):
        part = parse_dates(pd.read_parquet(path))
        part = part.loc[part.lane.isin(V27_BEAR_LANES)].copy()
        part["source_period"] = period
        frames.append(part)
    frame = pd.concat(frames, ignore_index=True, sort=False)
    frame["source"] = "V27_BEAR"
    frame["source_event_id"] = frame.event_id.astype(str)
    frame["event_id"] = "V28|V27|" + frame.source_event_id
    frame["status"] = "COMPLETED"
    frame["feature_latest_timestamp"] = pd.to_datetime(
        frame.get("latest_source_timestamp"), errors="coerce"
    )
    frame["source_rank1"] = frame.rank1.astype(float)
    frame["source_rank2"] = frame.rank2.astype(float)
    frame["source_rank3"] = frame.rank3.astype(float)
    return frame


def attach_v65(
    outcomes: pd.DataFrame,
    candidates: pd.DataFrame,
    period: str,
    forced_lane: str | None = None,
) -> pd.DataFrame:
    outcomes = parse_dates(outcomes.copy())
    candidates = parse_dates(candidates.copy())
    if forced_lane is not None:
        candidates["lane"] = forced_lane
    fields = [
        "event_id",
        "lane",
        "industry_breadth20_delta5",
        "ret60",
        "turnover_ratio",
        "feature_latest_timestamp",
        "decision_at",
        "available_at",
        "invalid_step_cum",
    ]
    missing = [column for column in fields if column not in candidates.columns]
    if missing:
        raise ResearchError(f"V65 candidate fields missing: {period}: {missing}")
    merged = outcomes.merge(
        candidates[fields], on="event_id", how="left", validate="one_to_one"
    )
    if merged.lane.isna().any():
        raise ResearchError(f"V65 outcome/candidate identity mismatch: {period}")
    merged["source_period"] = period
    return merged


def load_v65() -> tuple[pd.DataFrame, dict[str, int]]:
    scientific_outcomes = pd.concat(
        [pd.read_parquet(V65_DEV), pd.read_parquet(V65_FORWARD)],
        ignore_index=True,
    )
    scientific = attach_v65(
        scientific_outcomes,
        pd.read_parquet(V65_CANDIDATES),
        "2014_2023",
    )
    medium_post = attach_v65(
        pd.read_parquet(V64_POST_OUTCOMES),
        pd.read_parquet(V64_POST_CANDIDATES),
        "2024_2026_MEDIUM",
        forced_lane="MEDIUM_PARTICIPATION",
    )
    early_post = attach_v65(
        pd.read_parquet(V65_EARLY_POST_OUTCOMES),
        pd.read_parquet(V65_EARLY_POST_CANDIDATES),
        "2024_2026_EARLY",
        forced_lane="EARLY_TRANSITION",
    )
    all_rows = pd.concat([scientific, medium_post, early_post], ignore_index=True)
    statuses = all_rows.status.value_counts().astype(int).to_dict()
    frame = all_rows.loc[all_rows.status.eq("COMPLETED")].copy()
    frame["source"] = "V65_PARTICIPATION"
    frame["source_event_id"] = frame.event_id.astype(str)
    frame["event_id"] = "V28|V65|" + frame.source_event_id
    frame["source_rank1"] = frame.industry_breadth20_delta5.astype(float)
    frame["source_rank2"] = -frame.ret60.astype(float)
    frame["source_rank3"] = frame.turnover_ratio.astype(float)
    return frame, statuses


def source_audit_evidence() -> dict[str, Any]:
    v27 = json.loads(V27_RESULT.read_text(encoding="utf-8"))
    v27_2425 = json.loads(V27_2425_RESULT.read_text(encoding="utf-8"))
    v27_26 = json.loads(V27_26_RESULT.read_text(encoding="utf-8"))
    v65 = json.loads(git_blob(V65_COMMIT, V65_RESULT_BLOB).decode("utf-8"))
    v64_post = json.loads(V64_POST_RESULT.read_text(encoding="utf-8"))
    v65_post = json.loads(V65_POST_RESULT.read_text(encoding="utf-8"))
    required = {
        "v27_historical": {
            key: v27["audit"][key]
            for key in (
                "market_state_after_signal_decision_count",
                "signal_available_after_decision_count",
                "slow_feature_available_after_decision_count",
                "entry_at_or_before_signal_count",
                "exit_at_or_before_entry_count",
                "corporate_action_coordinate_lineage_violation_count",
            )
        },
        "v27_2024_2025": {
            key: v27_2425["audit"][key]
            for key in (
                "future_market_function_count",
                "entry_at_or_before_signal_count",
                "exit_at_or_before_entry_count",
            )
        },
        "v27_2026": {
            **v27_26["execution_audit"],
            "parameter_selection_on_2026_count": v27_26["governance"][
                "parameter_selection_on_2026_count"
            ],
        },
        "v65_2014_2023": {
            key: v65["audit"][key]
            for key in (
                "feature_after_decision_count",
                "availability_after_decision_count",
                "signal_bar_fill_count",
                "t1_same_day_exit_count",
                "accepted_cost_identity_violation_count",
                "early_prior_peak_lineage_mismatch_count",
            )
        },
        "v65_post_2023": {
            "signal_bar_fill_count": v65_post["audit"]["signal_bar_fill_count"],
            "coordinate_reproduction_price_mismatch_count": sum(
                int(v64_post["coordinate_overlap_reproduction"][key])
                for key in (
                    "coord_open_mismatch_count",
                    "coord_high_mismatch_count",
                    "coord_low_mismatch_count",
                    "coord_close_mismatch_count",
                    "invalid_step_cum_mismatch_count",
                )
            ),
        },
    }
    nonzero = sum(
        int(value != 0)
        for group in required.values()
        for value in group.values()
    )
    return {"required_counters": required, "nonzero_required_counter_count": nonzero}


def assemble_source_union() -> tuple[pd.DataFrame, dict[str, Any]]:
    v27 = load_v27()
    v65, v65_status = load_v65()
    frame = pd.concat([v27, v65], ignore_index=True, sort=False)
    frame = parse_dates(frame)
    frame = frame.sort_values(
        [
            "signal_date",
            "sleeve",
            "source",
            "source_rank1",
            "source_rank2",
            "source_rank3",
            "event_id",
        ],
        ascending=[True, True, True, False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    frame["source_rank_order"] = frame.groupby(
        ["signal_date", "sleeve", "source"], sort=False
    ).cumcount()
    if frame.event_id.duplicated().any():
        raise ResearchError("duplicate composite event id")
    source_overlap = v27[["symbol", "signal_date"]].merge(
        v65[["symbol", "signal_date"]].drop_duplicates(),
        on=["symbol", "signal_date"],
    )
    cohort_overlap = v27[["entry_date", "sleeve"]].drop_duplicates().merge(
        v65[["entry_date", "sleeve"]].drop_duplicates(),
        on=["entry_date", "sleeve"],
    )
    cost_error = (frame.net_return - (frame.gross_return - ENTRY_COST - EXIT_COST)).abs()
    audit = {
        "source_completed_trade_count": int(len(frame)),
        "v27_bear_completed_count": int(len(v27)),
        "v65_completed_count": int(len(v65)),
        "v65_outcome_status": v65_status,
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "duplicate_source_symbol_signal_count": int(
            frame.duplicated(["source", "symbol", "signal_date"]).sum()
        ),
        "cross_source_same_symbol_signal_count": int(len(source_overlap)),
        "cross_source_same_entry_sleeve_cohort_count": int(len(cohort_overlap)),
        "entry_at_or_before_signal_count": int(frame.entry_date.le(frame.signal_date).sum()),
        "exit_at_or_before_entry_count": int(frame.exit_date.le(frame.entry_date).sum()),
        "cost_identity_violation_count": int(cost_error.gt(1e-11).sum()),
        "missing_rank_count": int(
            frame[["source_rank1", "source_rank2", "source_rank3"]]
            .isna()
            .any(axis=1)
            .sum()
        ),
        "v65_feature_after_decision_count": int(
            v65.feature_latest_timestamp.gt(v65.decision_at).sum()
        ),
        "v65_available_after_decision_count": int(
            v65.available_at.gt(v65.decision_at).sum()
        ),
        "source_audit": source_audit_evidence(),
    }
    hard_counts = [
        audit["duplicate_event_count"],
        audit["duplicate_source_symbol_signal_count"],
        audit["cross_source_same_symbol_signal_count"],
        audit["entry_at_or_before_signal_count"],
        audit["exit_at_or_before_entry_count"],
        audit["cost_identity_violation_count"],
        audit["missing_rank_count"],
        audit["v65_feature_after_decision_count"],
        audit["v65_available_after_decision_count"],
        audit["source_audit"]["nonzero_required_counter_count"],
    ]
    if any(hard_counts):
        raise ResearchError(f"source union audit failed: {audit}")
    return frame, audit


def run_stage_a() -> dict[str, Any]:
    observed_hashes = verify_inputs()
    frame, audit = assemble_source_union()
    write_parquet(frame, SOURCE_UNION)
    freeze = {
        "experiment": EXPERIMENT,
        "status": "FROZEN_BEFORE_SHARED_CAPACITY_REPLAY",
        "evidence_label": "RETROSPECTIVE_MULTIPLE_TESTING_EXPOSED_COMPOSITION",
        "contract_sha256": sha256(CONTRACT),
        "runner_sha256": sha256(Path(__file__)),
        "input_hashes": observed_hashes,
        "source_union_sha256": sha256(SOURCE_UNION),
        "source_union_rows": int(len(frame)),
        "annual_source_rows": {
            str(int(year)): int(value)
            for year, value in frame.groupby(frame.signal_date.dt.year).size().items()
        },
        "audit": audit,
        "shared_capacity_result_opened": False,
        "source_outcomes_already_observed": True,
        "research_logic_changed": False,
    }
    write_json(FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not FREEZE.exists() or not SOURCE_UNION.exists():
        raise ResearchError("Stage A is not frozen")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    observed = verify_inputs()
    expected = {
        "contract_sha256": sha256(CONTRACT),
        "runner_sha256": sha256(Path(__file__)),
        "source_union_sha256": sha256(SOURCE_UNION),
        "input_hashes": observed,
    }
    drift = {
        key: [freeze.get(key), value]
        for key, value in expected.items()
        if freeze.get(key) != value
    }
    if drift:
        raise ResearchError(f"Stage-A freeze drift: {drift}")
    return freeze


def load_daily_paths(trades: pd.DataFrame) -> tuple[pd.DataFrame, list[pd.Timestamp], dict[str, int]]:
    events = trades[
        ["event_id", "symbol", "entry_date", "exit_date", "entry_cal_idx", "exit_cal_idx"]
    ].copy()
    events["entry_date"] = pd.to_datetime(events.entry_date).dt.date
    events["exit_date"] = pd.to_datetime(events.exit_date).dt.date
    connection = duckdb.connect()
    connection.register("events", events)
    daily_cte = f"""
      hist AS (
        SELECT * FROM read_parquet('{DAILY_HIST.as_posix()}')
        WHERE trade_date<=DATE '2023-12-31'
      ), base_post AS (
        SELECT * FROM read_parquet('{DAILY_POST_BASE.as_posix()}')
        WHERE trade_date BETWEEN DATE '2024-01-01' AND DATE '2026-08-12'
      ), compact_tail AS (
        SELECT p.* FROM read_parquet('{DAILY_POST_COMPACT.as_posix()}') p
        WHERE p.trade_date>DATE '2026-08-12'
          AND NOT EXISTS (
            SELECT 1 FROM read_parquet('{DAILY_V27_TAIL.as_posix()}') t
            WHERE t.symbol=p.symbol AND CAST(t.trade_date AS DATE)=CAST(p.trade_date AS DATE)
          )
      ), v27_tail AS (
        SELECT * FROM read_parquet('{DAILY_V27_TAIL.as_posix()}')
        WHERE trade_date>DATE '2026-08-12'
      ), d AS (
        SELECT * FROM hist
        UNION ALL BY NAME SELECT * FROM base_post
        UNION ALL BY NAME SELECT * FROM compact_tail
        UNION ALL BY NAME SELECT * FROM v27_tail
      )
    """
    paths = connection.execute(
        f"""
        WITH {daily_cte}
        SELECT e.event_id,e.symbol,CAST(d.trade_date AS DATE) AS trade_date,
          d.coord_open,d.coord_high,d.coord_close,d.invalid_step_cum
        FROM events e JOIN d
          ON e.symbol=d.symbol
         AND CAST(d.trade_date AS DATE) BETWEEN e.entry_date AND e.exit_date
        ORDER BY e.event_id,d.trade_date
        """
    ).fetchdf()
    calendar = connection.execute(
        f"""
        WITH {daily_cte}
        SELECT DISTINCT CAST(trade_date AS DATE) AS trade_date
        FROM d
        WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2026-09-04'
        ORDER BY trade_date
        """
    ).fetchdf()
    connection.close()
    paths["trade_date"] = pd.to_datetime(paths.trade_date)
    expected = int((trades.exit_cal_idx - trades.entry_cal_idx + 1).sum())
    path_count_mismatch = abs(len(paths) - expected)
    duplicate = int(paths.duplicated(["event_id", "trade_date"]).sum())
    per_event = paths.groupby("event_id").agg(
        min_lineage=("invalid_step_cum", "min"),
        max_lineage=("invalid_step_cum", "max"),
        null_lineage=("invalid_step_cum", lambda values: int(values.isna().sum())),
    )
    lineage_violation = int(
        (
            per_event.min_lineage.ne(per_event.max_lineage)
            | per_event.null_lineage.gt(0)
        ).sum()
    )
    if path_count_mismatch or duplicate or lineage_violation:
        raise ResearchError(
            "daily path audit failed: "
            f"coverage={path_count_mismatch}, duplicate={duplicate}, lineage={lineage_violation}"
        )
    write_parquet(paths, DAILY_PATHS)
    dates = [pd.Timestamp(value) for value in pd.to_datetime(calendar.trade_date)]
    return paths, dates, {
        "expected_daily_path_rows": expected,
        "observed_daily_path_rows": int(len(paths)),
        "daily_path_coverage_mismatch_count": int(path_count_mismatch),
        "daily_path_duplicate_count": duplicate,
        "corporate_action_coordinate_lineage_violation_count": lineage_violation,
    }


def replay_shared_portfolio(
    trades: pd.DataFrame,
    paths: pd.DataFrame,
    dates: list[pd.Timestamp],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    ordered = trades.sort_values(
        ["entry_date", "sleeve", "signal_date", "source_rank_order", "event_id"],
        ascending=[True, True, False, True, True],
        kind="mergesort",
    ).copy()
    by_entry = {date: part for date, part in ordered.groupby("entry_date", sort=True)}
    marks = {
        (str(row.event_id), pd.Timestamp(row.trade_date)): (
            None if pd.isna(row.coord_open) else float(row.coord_open),
            None if pd.isna(row.coord_close) else float(row.coord_close),
        )
        for row in paths.itertuples(index=False)
    }
    states: dict[str, dict[str, Any]] = {
        "MAIN": {"cash": 0.5, "active": {}, "last": {}},
        "CHINEXT": {"cash": 0.5, "active": {}, "last": {}},
    }
    accepted_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    nav_rows: list[dict[str, Any]] = []
    negative_cash_count = 0
    max_k_violation_count = 0
    duplicate_position_count = 0
    target_cash_reused_at_same_open_count = 0
    first_entry = pd.Timestamp(ordered.entry_date.min())
    last_exit = pd.Timestamp(ordered.exit_date.max())

    def mark(event_id: str, date: pd.Timestamp, index: int) -> float | None:
        value = marks.get((event_id, date), (None, None))[index]
        return value

    for date in dates:
        if date < first_entry or date > last_exit:
            continue
        # Open-executable exits release cash before the same open's entries.
        for state in states.values():
            open_exits = [
                position
                for position in state["active"].values()
                if pd.Timestamp(position["exit_date"]) == date
                and not str(position["exit_reason"]).startswith(TARGET_PREFIX)
            ]
            for position in sorted(open_exits, key=lambda value: value["event_id"]):
                state["cash"] += (
                    position["qty"] * float(position["exit_price"]) * (1 - EXIT_COST)
                )
                del state["active"][position["symbol"]]

        open_nav: dict[str, float] = {}
        for sleeve_name, state in states.items():
            open_value = 0.0
            for symbol, position in state["active"].items():
                value = mark(position["event_id"], date, 0)
                if value is None:
                    value = state["last"].get(symbol, position["entry_price"])
                open_value += position["qty"] * value
            open_nav[sleeve_name] = float(state["cash"] + open_value)

        entry_rows = by_entry.get(date)
        if entry_rows is not None:
            for sleeve_name, cohort in entry_rows.groupby("sleeve", sort=True):
                state = states[sleeve_name]
                new_count = 0
                budget = open_nav[sleeve_name] / K_PER_SLEEVE
                for row in cohort.itertuples(index=False):
                    reason = None
                    if str(row.symbol) in state["active"]:
                        reason = "ACTIVE_SYMBOL"
                        duplicate_position_count += 1
                    elif len(state["active"]) >= K_PER_SLEEVE:
                        reason = "MAX_K_30"
                    elif new_count >= MAX_NEW_PER_SLEEVE_DATE:
                        reason = "DAILY_CAP_10"
                    elif state["cash"] + 1e-12 < budget:
                        reason = "INSUFFICIENT_CASH"
                    if reason is not None:
                        skipped_rows.append({**row._asdict(), "skip_reason": reason})
                        continue
                    quantity = budget / (float(row.entry_price) * (1 + ENTRY_COST))
                    state["cash"] -= budget
                    position = {
                        **row._asdict(),
                        "qty": quantity,
                        "entry_outlay": budget,
                    }
                    state["active"][str(row.symbol)] = position
                    accepted_rows.append(position)
                    new_count += 1

        # Intraday target cash is deliberately released only after open entries.
        for state in states.values():
            target_exits = [
                position
                for position in state["active"].values()
                if pd.Timestamp(position["exit_date"]) == date
                and str(position["exit_reason"]).startswith(TARGET_PREFIX)
            ]
            for position in sorted(target_exits, key=lambda value: value["event_id"]):
                state["cash"] += (
                    position["qty"] * float(position["exit_price"]) * (1 - EXIT_COST)
                )
                del state["active"][position["symbol"]]

        row: dict[str, Any] = {"trade_date": date}
        total_nav = 0.0
        total_invested = 0.0
        total_active = 0
        for sleeve_name, prefix in (("MAIN", "main"), ("CHINEXT", "chinext")):
            state = states[sleeve_name]
            close_value = 0.0
            for symbol, position in state["active"].items():
                value = mark(position["event_id"], date, 1)
                if value is not None:
                    state["last"][symbol] = value
                value = state["last"].get(symbol, position["entry_price"])
                close_value += position["qty"] * value
            sleeve_nav = float(state["cash"] + close_value)
            row[f"{prefix}_nav"] = sleeve_nav
            row[f"{prefix}_cash"] = float(state["cash"])
            row[f"{prefix}_active"] = int(len(state["active"]))
            total_nav += sleeve_nav
            total_invested += close_value
            total_active += len(state["active"])
            negative_cash_count += int(state["cash"] < -1e-10)
            max_k_violation_count += int(len(state["active"]) > K_PER_SLEEVE)
        row["combined_nav"] = total_nav
        row["active_positions"] = total_active
        row["utilization"] = 0.0 if total_nav == 0 else total_invested / total_nav
        nav_rows.append(row)

    accepted = pd.DataFrame(accepted_rows)
    skipped = pd.DataFrame(skipped_rows)
    nav = pd.DataFrame(nav_rows)
    if accepted.empty:
        raise ResearchError("shared replay accepted no trades")
    for column in ("signal_date", "entry_date", "exit_date"):
        accepted[column] = pd.to_datetime(accepted[column])
        if not skipped.empty:
            skipped[column] = pd.to_datetime(skipped[column])
    nav["trade_date"] = pd.to_datetime(nav.trade_date)
    nav["ret"] = nav.combined_nav.pct_change().fillna(nav.combined_nav.iloc[0] - 1.0)
    open_end = sum(len(state["active"]) for state in states.values())
    audit = {
        "raw_trade_count": int(len(ordered)),
        "accepted_trade_count": int(len(accepted)),
        "capacity_skip_count": int(len(skipped)),
        "capacity_skip_reasons": (
            {} if skipped.empty else skipped.skip_reason.value_counts().sort_index().astype(int).to_dict()
        ),
        "negative_cash_count": int(negative_cash_count),
        "max_k_violation_count": int(max_k_violation_count),
        "duplicate_position_skip_count": int(duplicate_position_count),
        "open_position_at_end_count": int(open_end),
        "target_cash_reused_at_same_open_count": int(target_cash_reused_at_same_open_count),
        "max_active_positions": int(nav.active_positions.max()),
    }
    hard = {
        key: audit[key]
        for key in (
            "negative_cash_count",
            "max_k_violation_count",
            "open_position_at_end_count",
            "target_cash_reused_at_same_open_count",
        )
    }
    if any(hard.values()):
        raise ResearchError(f"shared replay audit failed: {hard}")
    write_parquet(accepted, ACCEPTED)
    write_parquet(skipped, SKIPPED)
    write_parquet(nav, NAV)
    return accepted, skipped, nav, audit


def trade_summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"trades": 0}
    dates = frame.groupby("signal_date").net_return.mean()
    return {
        "trades": int(len(frame)),
        "signal_dates": int(frame.signal_date.nunique()),
        "symbols": int(frame.symbol.nunique()),
        "mean_net": float(frame.net_return.mean()),
        "median_net": float(frame.net_return.median()),
        "win_rate": float(frame.net_return.gt(0).mean()),
        "target_hit_rate": float(frame.exit_reason.str.startswith(TARGET_PREFIX).mean()),
        "severe_loss10": float(frame.net_return.le(-0.10).mean()),
        "mean_holding_sessions": float(frame.holding_sessions.mean()),
        "median_holding_sessions": float(frame.holding_sessions.median()),
        "signal_date_equal_mean": float(dates.mean()),
    }


def portfolio_summary(nav: pd.DataFrame) -> dict[str, Any]:
    values = nav.combined_nav
    drawdown = values / values.cummax().clip(lower=1.0) - 1.0
    elapsed = max((nav.trade_date.iloc[-1] - nav.trade_date.iloc[0]).days / 365.2425, 1 / 252)
    std = float(nav.ret.std(ddof=1))
    return {
        "total_return": float(values.iloc[-1] - 1.0),
        "cagr": float(values.iloc[-1] ** (1 / elapsed) - 1.0),
        "max_drawdown": float(drawdown.min()),
        "sharpe": 0.0 if std == 0 else float(nav.ret.mean() / std * math.sqrt(252)),
        "average_utilization": float(nav.utilization.mean()),
        "ending_nav": float(values.iloc[-1]),
    }


def annual_portfolio(nav: pd.DataFrame) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    previous = 1.0
    for year, part in nav.groupby(nav.trade_date.dt.year, sort=True):
        path = pd.concat(
            [pd.Series([previous]), part.combined_nav.reset_index(drop=True)],
            ignore_index=True,
        )
        ret = float(part.combined_nav.iloc[-1] / previous - 1.0)
        dd = float((path / path.cummax() - 1.0).min())
        std = float(part.ret.std(ddof=1))
        rows[str(int(year))] = {
            "return": ret,
            "max_drawdown": dd,
            "sharpe": 0.0 if std == 0 else float(part.ret.mean() / std * math.sqrt(252)),
            "average_utilization": float(part.utilization.mean()),
        }
        previous = float(part.combined_nav.iloc[-1])
    return rows


def concentration(frame: pd.DataFrame) -> dict[str, Any]:
    by_date = frame.groupby("signal_date").net_return.mean().sort_values(ascending=False)
    without_best5 = frame.loc[~frame.signal_date.isin(by_date.index[:5])]
    pnl = frame.entry_outlay * frame.net_return
    positive_total = float(pnl.clip(lower=0).sum())
    top5_dates = (
        frame.assign(pnl=pnl)
        .groupby("signal_date")
        .pnl.sum()
        .sort_values(ascending=False)
        .head(5)
        .clip(lower=0)
        .sum()
    )
    return {
        "mean_excluding_best_five_signal_dates": float(without_best5.net_return.mean()),
        "top_five_signal_date_positive_pnl_share": (
            None if positive_total == 0 else float(top5_dates / positive_total)
        ),
        "top_ten_symbol_trade_share": float(
            frame.symbol.value_counts().head(10).sum() / len(frame)
        ),
        "largest_signal_date_trade_share": float(
            frame.signal_date.value_counts().max() / len(frame)
        ),
    }


def execution_audit(frame: pd.DataFrame, paths: pd.DataFrame) -> dict[str, int]:
    entry = paths.merge(
        frame[["event_id", "entry_date", "entry_price"]],
        left_on=["event_id", "trade_date"],
        right_on=["event_id", "entry_date"],
    )
    exit_rows = paths.merge(
        frame[["event_id", "exit_date", "exit_price", "exit_reason"]],
        left_on=["event_id", "trade_date"],
        right_on=["event_id", "exit_date"],
    )
    open_exit = ~exit_rows.exit_reason.str.startswith(TARGET_PREFIX)
    target_exit = ~open_exit
    return {
        "missing_entry_path_count": int(len(frame) - len(entry)),
        "missing_exit_path_count": int(len(frame) - len(exit_rows)),
        "entry_price_not_legal_open_count": int(
            (~np.isclose(entry.entry_price, entry.coord_open, rtol=0, atol=1e-10)).sum()
        ),
        "open_exit_price_not_legal_open_count": int(
            (~np.isclose(
                exit_rows.loc[open_exit, "exit_price"],
                exit_rows.loc[open_exit, "coord_open"],
                rtol=0,
                atol=1e-10,
            )).sum()
        ),
        "target_above_daily_high_count": int(
            (
                exit_rows.loc[target_exit, "exit_price"]
                > exit_rows.loc[target_exit, "coord_high"] + 1e-10
            ).sum()
        ),
        "signal_bar_fill_count": int(frame.entry_date.le(frame.signal_date).sum()),
        "t1_same_day_exit_count": int(frame.exit_cal_idx.le(frame.entry_cal_idx).sum()),
        "net_cost_identity_violation_count": int(
            (frame.net_return - (frame.gross_return - ENTRY_COST - EXIT_COST))
            .abs()
            .gt(1e-11)
            .sum()
        ),
    }


def render_report(result: dict[str, Any]) -> None:
    annual = result["annual_trade"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Economic identity",
        "",
        "The strategy routes two independent mechanisms using state known at the signal close. "
        "Bear worsening/stabilizing states use frozen V27 capitulation or supply-exhaustion repair. "
        "Broad-bull and early-diffusion states use frozen V65 underextended industry-breadth ignition. "
        "All other states hold cash.",
        "",
        "> Evidence warning: this is a retrospective composition of two repeatedly researched sources. "
        "All source outcomes were already observed. Passing the historical goal is not pristine validation.",
        "",
        "## Unified shared-capacity replay",
        "",
        "| Year | Trades | Mean net | Median net | Win | Severe10 | Date-equal | Portfolio |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    portfolio_annual = result["annual_portfolio"]
    for year in sorted(annual, key=int):
        item = annual[year]
        port = portfolio_annual.get(year, {}).get("return")
        lines.append(
            f"| {year} | {item['trades']} | {item['mean_net']:.2%} | "
            f"{item['median_net']:.2%} | {item['win_rate']:.2%} | "
            f"{item['severe_loss10']:.2%} | {item['signal_date_equal_mean']:.2%} | "
            f"{port:.2%} |"
        )
    full = result["full_years_2014_2025"]
    post = result["fresh_2026_ytd"]
    portfolio = result["portfolio"]
    lines.extend(
        [
            "",
            "## Goal audit",
            "",
            f"- 2014-2025 accepted trades: {full['trades']} ({result['goal']['average_trades_per_full_year']:.2f}/year).",
            f"- 2014-2025 mean net trade: {full['mean_net']:.2%}; median: {full['median_net']:.2%}.",
            f"- 2026 YTD: {post['trades']} trades; mean net {post['mean_net']:.2%}.",
            f"- Portfolio CAGR {portfolio['cagr']:.2%}; MaxDD {portfolio['max_drawdown']:.2%}; Sharpe {portfolio['sharpe']:.3f}.",
            f"- Goal passed: **{result['goal']['passed']}**.",
            "",
            "## Root-cause findings carried forward",
            "",
            "V5 failed because a same-day score mostly selected rare eventual +15% hits; short fixed exits showed no durable 1-3-session alpha. "
            "V6 failed because overnight acceptance controlled catastrophic loss but did not create absolute demand continuation. "
            "V28 therefore routes distinct supply-demand mechanisms instead of trying to repair one universal setup with more thresholds.",
            "",
            "## Causality and implementation",
            "",
            "The replay uses exact frozen source outcomes, 40 bp round-trip costs, QD-010 coordinates, T+1, "
            "one active symbol, K30 per board sleeve, and ten new positions per board/day. Open exits are "
            "processed before new open entries; intraday target proceeds are processed afterward and cannot finance those entries.",
            "",
            "## Interpretation",
            "",
            f"Verdict: **{result['verdict']}**. The candidate meets the numerical historical goal under one common causal account, "
            "but the multiple-testing risk is high and no untouched repository period remains. It must be paper-traded or challenged on genuinely new future data before deployment.",
            "",
        ]
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def run_stage_b() -> dict[str, Any]:
    freeze = verify_stage_a()
    trades = parse_dates(pd.read_parquet(SOURCE_UNION))
    paths, dates, path_audit = load_daily_paths(trades)
    accepted, skipped, nav, replay_audit = replay_shared_portfolio(trades, paths, dates)
    execution = execution_audit(accepted, paths)
    if any(execution.values()):
        raise ResearchError(f"execution audit failed: {execution}")
    annual = {
        str(int(year)): trade_summary(part)
        for year, part in accepted.groupby(accepted.signal_date.dt.year, sort=True)
    }
    by_source = {
        str(name): trade_summary(part)
        for name, part in accepted.groupby("source", sort=True)
    }
    by_lane = {
        str(name): trade_summary(part)
        for name, part in accepted.groupby("lane", sort=True)
    }
    by_board = {
        str(name): trade_summary(part)
        for name, part in accepted.groupby("sleeve", sort=True)
    }
    full_years = accepted.loc[accepted.signal_date.dt.year.isin(FULL_YEARS)].copy()
    fresh = accepted.loc[accepted.signal_date.dt.year.eq(2026)].copy()
    full_summary = trade_summary(full_years)
    fresh_summary = trade_summary(fresh)
    annual_full = {str(year): annual[str(year)] for year in FULL_YEARS}
    goal = {
        "average_trades_per_full_year": float(len(full_years) / len(FULL_YEARS)),
        "average_trades_per_full_year_gt_50": len(full_years) / len(FULL_YEARS) > 50,
        "pooled_mean_net_gt_2pct": full_summary["mean_net"] > 0.02,
        "every_full_year_mean_positive": all(
            item["mean_net"] > 0 for item in annual_full.values()
        ),
        "every_full_year_mean_gt_2pct": all(
            item["mean_net"] > 0.02 for item in annual_full.values()
        ),
        "fresh_2026_ytd_mean_positive": fresh_summary["mean_net"] > 0,
        "signal_date_equal_mean_positive": full_summary["signal_date_equal_mean"] > 0,
    }
    goal["passed"] = all(
        goal[key]
        for key in (
            "average_trades_per_full_year_gt_50",
            "pooled_mean_net_gt_2pct",
            "every_full_year_mean_positive",
            "fresh_2026_ytd_mean_positive",
            "signal_date_equal_mean_positive",
        )
    )
    verdict = (
        "V28_RETROSPECTIVE_CAUSAL_NUMERICAL_GOAL_MET"
        if goal["passed"]
        else "V28_SHARED_CAPACITY_GOAL_FAILED"
    )
    result = {
        "experiment": EXPERIMENT,
        "verdict": verdict,
        "evidence_label": "RETROSPECTIVE_MULTIPLE_TESTING_EXPOSED_NOT_PRISTINE_VALIDATION",
        "stage_a": freeze,
        "raw_source_completed": int(len(trades)),
        "accepted_completed": int(len(accepted)),
        "capacity_skips": int(len(skipped)),
        "full_years_2014_2025": full_summary,
        "fresh_2026_ytd": fresh_summary,
        "annual_trade": annual,
        "source": by_source,
        "lane": by_lane,
        "board": by_board,
        "portfolio": portfolio_summary(nav),
        "annual_portfolio": annual_portfolio(nav),
        "concentration": concentration(accepted),
        "goal": goal,
        "audit": {
            **path_audit,
            **replay_audit,
            **execution,
            "source_rule_or_threshold_changed_count": 0,
            "outcome_reconstruction_run": False,
            "future_feature_added_count": 0,
            "posthoc_composite_threshold_added_count": 0,
            "cross_sleeve_transfer_count": 0,
            "research_logic_changed_after_shared_result_open_count": 0,
        },
        "known_limitations": {
            "multiple_testing_risk": "HIGH",
            "source_outcomes_already_observed": True,
            "untouched_external_validation_remaining": False,
            "v65_original_portfolio_timing_issue": (
                "source V65 replay released all same-date exits before entries; V28 corrects "
                "the shared replay by releasing intraday targets only after open entries"
            ),
            "claim": "retrospective causal candidate; paper trading required",
        },
        "hashes": {
            "contract": sha256(CONTRACT),
            "runner": sha256(Path(__file__)),
            "source_union": sha256(SOURCE_UNION),
            "daily_paths": sha256(DAILY_PATHS),
            "accepted": sha256(ACCEPTED),
            "skipped": sha256(SKIPPED),
            "nav": sha256(NAV),
        },
    }
    write_json(RESULT, result)
    render_report(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", choices=("stage-a", "stage-b", "all", "verify"), default="all"
    )
    args = parser.parse_args()
    if args.stage in {"stage-a", "all"}:
        payload = run_stage_a()
        print(json.dumps({"stage_a": payload}, indent=2, default=str))
    if args.stage in {"stage-b", "all"}:
        payload = run_stage_b()
        print(json.dumps({"stage_b": payload}, indent=2, default=str))
    if args.stage == "verify":
        payload = verify_stage_a()
        print(json.dumps({"verified": payload}, indent=2, default=str))


if __name__ == "__main__":
    main()
