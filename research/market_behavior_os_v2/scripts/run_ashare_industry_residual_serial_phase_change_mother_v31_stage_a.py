#!/usr/bin/env python3
"""Freeze the outcome-blind V31 industry-residual serial phase-change mother."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import rankdata

EXPERIMENT = "ASHARE-INDUSTRY-RESIDUAL-SERIAL-PHASE-CHANGE-MOTHER-V31"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
REGISTRY = REPO / "configs/data_asset_registry.json"
MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
CY006_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
PARTITIONS = tuple(
    CY006_ROOT / f"partition_year={year}/data_0.parquet" for year in range(2018, 2021)
)
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_industry_residual_serial_phase_change_mother_v31"
)
STAGE_A = OUTPUT_ROOT / "stage_a"

EXPECTED_SPEC = "d43d03bc04b26fbc0b79207c5d0598024f5d60921522e186283d523ed670c65c"
EXPECTED_MANIFEST = "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2"
EXPECTED_PARTITIONS = {
    PARTITIONS[0]: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    PARTITIONS[1]: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    PARTITIONS[2]: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
}
MAX_ROW_DATE = pd.Timestamp("2020-06-30")
SIGNAL_START = pd.Timestamp("2018-07-01")
SIGNAL_END = pd.Timestamp("2020-06-30")
YEARS = (2018, 2019, 2020)
HISTORY_ENDPOINTS = 61
COOLDOWN = 20
REDUNDANCY_LIMIT = 0.80
CONTROLS = (
    "raw_return_20",
    "raw_return_60",
    "return_volatility_60",
    "turnover_ratio_1_to_60",
)


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, PIT timing, or representation drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    expected = {SPEC: EXPECTED_SPEC, MANIFEST: EXPECTED_MANIFEST, **EXPECTED_PARTITIONS}
    actual: dict[str, str] = {}
    for path, expected_hash in expected.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        value = sha256(path)
        actual[str(path)] = value
        if value != expected_hash:
            raise ResearchError(f"frozen input drift: {path}: {value} != {expected_hash}")

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assets = [item for item in registry.get("assets", []) if item.get("asset_id") == "CY-006"]
    if len(assets) != 1:
        raise ResearchError("missing or duplicate CY-006 registry record")
    asset = assets[0]
    lineage = asset.get("lineage", {})
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or lineage.get("record_available_at") is not True
        or lineage.get("record_snapshot_id") is not True
        or lineage.get("immutable_manifest") is not True
        or lineage.get("manifest_path") != str(MANIFEST)
        or lineage.get("manifest_sha256") != EXPECTED_MANIFEST
        or "leave-one-out industry context using registered PIT membership"
        not in asset.get("allowed_uses", [])
    ):
        raise ResearchError("CY-006 registry semantics drift")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = {item["path"]: item["sha256"] for item in manifest.get("files", [])}
    if manifest.get("root") != str(CY006_ROOT):
        raise ResearchError("CY-006 manifest root drift")
    for path, expected_hash in EXPECTED_PARTITIONS.items():
        relative = str(path.relative_to(CY006_ROOT))
        if entries.get(relative) != expected_hash:
            raise ResearchError(f"CY-006 manifest partition drift: {relative}")
    actual[str(REGISTRY)] = sha256(REGISTRY)
    actual[str(Path(__file__).resolve())] = sha256(Path(__file__).resolve())
    return actual


def connect(temporary: Path) -> duckdb.DuckDBPyConnection:
    temporary.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=4")
    connection.execute("SET memory_limit='12GB'")
    connection.execute(f"SET temp_directory='{temporary.as_posix()}'")
    connection.from_parquet([str(path) for path in PARTITIONS], union_by_name=True).create_view(
        "cy006"
    )
    return connection


def row_spearman(left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return row-wise Spearman rho and a strict nondegenerate mask."""
    if left.shape != right.shape or left.ndim != 2:
        raise ValueError("row_spearman requires equally shaped two-dimensional arrays")
    if left.shape[1] < 3:
        raise ValueError("row_spearman requires at least three observations")
    left_rank = rankdata(left, axis=1, method="average")
    right_rank = rankdata(right, axis=1, method="average")
    left_centered = left_rank - left_rank.mean(axis=1, keepdims=True)
    right_centered = right_rank - right_rank.mean(axis=1, keepdims=True)
    denominator = np.sqrt(
        np.square(left_centered).sum(axis=1) * np.square(right_centered).sum(axis=1)
    )
    left_distinct = 1 + np.not_equal(np.diff(np.sort(left, axis=1), axis=1), 0).sum(axis=1)
    right_distinct = 1 + np.not_equal(np.diff(np.sort(right, axis=1), axis=1), 0).sum(axis=1)
    valid = (
        np.isfinite(left).all(axis=1)
        & np.isfinite(right).all(axis=1)
        & np.isfinite(denominator)
        & (denominator > 0)
    )
    valid &= (left_distinct >= 3) & (right_distinct >= 3)
    rho = np.full(left.shape[0], np.nan, dtype=float)
    rho[valid] = np.sum(left_centered[valid] * right_centered[valid], axis=1) / denominator[valid]
    return rho, valid


def build_history(connection: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, dict[str, int]]:
    paths = ",".join(f"'{path.as_posix()}'" for path in PARTITIONS)
    source_audit = connection.execute(
        f"""
        SELECT count(*) AS rows,
          count(*)-count(DISTINCT (trade_date,symbol)) AS duplicate_keys,
          count(*) FILTER (
            WHERE hard_valid AND available_at>decision_at
          ) AS hard_valid_time_travel_rows,
          min(trade_date) AS first_date,max(trade_date) AS last_date
        FROM read_parquet([{paths}],union_by_name=true)
        WHERE trade_date<=DATE '{MAX_ROW_DATE.date()}'
        """
    ).fetchone()
    audit = {
        "source_rows": int(source_audit[0]),
        "duplicate_source_keys": int(source_audit[1]),
        "hard_valid_time_travel_rows": int(source_audit[2]),
    }
    if audit["duplicate_source_keys"] or audit["hard_valid_time_travel_rows"]:
        raise ResearchError(f"CY-006 source audit failed: {audit}")

    connection.execute(
        f"""
        CREATE TEMP TABLE market_calendar AS
        SELECT trade_date,row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
        FROM (
          SELECT DISTINCT trade_date FROM cy006
          WHERE trade_date<=DATE '{MAX_ROW_DATE.date()}'
        )
        """
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE eligible AS
        SELECT d.trade_date,c.cal_idx,d.symbol,d.industry AS causal_industry,
          d.decision_at,d.available_at,d.snapshot_id,d.daily_snapshot_id,
          d.industry_snapshot_id,d.corporate_action_snapshot_id,
          d.amount,d.turnover_fraction,d.close/d.preclose-1.0 AS stock_return
        FROM cy006 d JOIN market_calendar c USING(trade_date)
        WHERE d.trade_date<=DATE '{MAX_ROW_DATE.date()}'
          AND (
            regexp_matches(d.symbol,'^(600|601|603|605)[0-9]{{3}}[.]SH$')
            OR regexp_matches(d.symbol,'^(000|001|002|300|301)[0-9]{{3}}[.]SZ$')
          )
          AND coalesce(d.hard_valid AND d.bar_valid AND d.trading_state_valid
            AND d.industry_valid AND d.corporate_action_valid
            AND NOT d.corporate_action_blocking AND d.market_valid
            AND d.market_rule_valid AND d.historical_identity_valid
            AND d.current_day_data_tradable AND d.trade_status=1 AND NOT d.is_st
            AND d.available_at<=d.decision_at
            AND d.industry IS NOT NULL AND d.industry_snapshot_id IS NOT NULL
            AND d.snapshot_id IS NOT NULL AND d.daily_snapshot_id IS NOT NULL
            AND d.open>0 AND d.high>0 AND d.low>0 AND d.close>0 AND d.preclose>0
            AND d.high>=d.open AND d.high>=d.close
            AND d.low<=d.open AND d.low<=d.close
            AND d.amount>0 AND d.turnover_fraction>0
            AND isfinite(d.open) AND isfinite(d.high) AND isfinite(d.low)
            AND isfinite(d.close) AND isfinite(d.preclose)
            AND isfinite(d.amount) AND isfinite(d.turnover_fraction)
            AND isfinite(d.close/d.preclose-1.0),false)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE daily_liquidity AS
        SELECT trade_date,median(amount) AS same_date_median_amount,
          count(*) AS same_date_eligible_n
        FROM eligible GROUP BY trade_date
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE industry_groups AS
        SELECT trade_date,causal_industry,count(*) AS industry_member_count,
          list_sort(list(stock_return)) AS sorted_stock_returns
        FROM eligible
        GROUP BY trade_date,causal_industry
        HAVING count(*)>=10
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE residual_rows AS
        SELECT e.*,g.industry_member_count,l.same_date_median_amount,
          l.same_date_eligible_n,
          CASE
            WHEN g.industry_member_count%2=0
                 AND e.stock_return<=list_extract(
                   g.sorted_stock_returns,floor(g.industry_member_count/2)::BIGINT
                 )
              THEN list_extract(
                g.sorted_stock_returns,floor(g.industry_member_count/2)::BIGINT+1
              )
            WHEN g.industry_member_count%2=0
              THEN list_extract(
                g.sorted_stock_returns,floor(g.industry_member_count/2)::BIGINT
              )
            WHEN e.stock_return<list_extract(
                   g.sorted_stock_returns,floor(g.industry_member_count/2)::BIGINT+1
                 )
              THEN (
                list_extract(
                  g.sorted_stock_returns,floor(g.industry_member_count/2)::BIGINT+1
                )+list_extract(
                  g.sorted_stock_returns,floor(g.industry_member_count/2)::BIGINT+2
                )
              )/2.0
            WHEN e.stock_return>list_extract(
                   g.sorted_stock_returns,floor(g.industry_member_count/2)::BIGINT+1
                 )
              THEN (
                list_extract(
                  g.sorted_stock_returns,floor(g.industry_member_count/2)::BIGINT
                )+list_extract(
                  g.sorted_stock_returns,floor(g.industry_member_count/2)::BIGINT+1
                )
              )/2.0
            ELSE (
              list_extract(
                g.sorted_stock_returns,floor(g.industry_member_count/2)::BIGINT
              )+list_extract(
                g.sorted_stock_returns,floor(g.industry_member_count/2)::BIGINT+2
              )
            )/2.0
          END AS leave_one_out_industry_median
        FROM eligible e
        JOIN industry_groups g USING(trade_date,causal_industry)
        JOIN daily_liquidity l USING(trade_date)
        """
    )
    connection.execute(
        """
        ALTER TABLE residual_rows ADD COLUMN daily_residual_return DOUBLE;
        UPDATE residual_rows
        SET daily_residual_return=stock_return-leave_one_out_industry_median
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE month_ends AS
        SELECT trade_date,cal_idx FROM (
          SELECT trade_date,cal_idx,
            lead(date_trunc('month',trade_date)) OVER (ORDER BY cal_idx) AS next_month
          FROM market_calendar
        )
        WHERE next_month IS NULL OR next_month>date_trunc('month',trade_date)
        """
    )
    history = connection.execute(
        f"""
        SELECT a.trade_date AS signal_date,a.cal_idx AS signal_cal_idx,a.symbol,
          a.causal_industry,a.decision_at,a.available_at,a.snapshot_id,
          a.daily_snapshot_id,a.industry_snapshot_id,
          a.corporate_action_snapshot_id,a.industry_member_count,
          a.same_date_median_amount,a.same_date_eligible_n,a.amount,
          a.turnover_fraction,a.stock_return AS current_stock_return,
          a.leave_one_out_industry_median AS current_industry_reference,
          a.daily_residual_return AS current_residual_return,
          count(*) AS history_endpoint_count,min(h.cal_idx) AS history_first_cal_idx,
          max(h.cal_idx) AS history_last_cal_idx,
          list(h.daily_residual_return ORDER BY h.cal_idx) AS residual_history,
          list(h.stock_return ORDER BY h.cal_idx) AS stock_return_history,
          list(h.turnover_fraction ORDER BY h.cal_idx) AS turnover_history
        FROM residual_rows a
        JOIN month_ends m ON m.trade_date=a.trade_date AND m.cal_idx=a.cal_idx
        JOIN residual_rows h ON h.symbol=a.symbol
          AND h.cal_idx BETWEEN a.cal_idx-60 AND a.cal_idx
        WHERE a.trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{SIGNAL_END.date()}'
        GROUP BY ALL
        ORDER BY a.trade_date,a.causal_industry,a.symbol
        """
    ).fetch_df()
    audit["history_anchor_rows_before_exactness"] = len(history)
    exact = (
        history.history_endpoint_count.eq(HISTORY_ENDPOINTS)
        & history.history_first_cal_idx.eq(history.signal_cal_idx - 60)
        & history.history_last_cal_idx.eq(history.signal_cal_idx)
    )
    audit["history_anchor_rows_exact"] = int(exact.sum())
    audit["history_anchor_rows_rejected"] = int((~exact).sum())
    return history.loc[exact].reset_index(drop=True), audit


def make_representation(history: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    if history.empty:
        raise ResearchError("no exact V31 histories")
    residual = np.vstack(history.pop("residual_history").to_numpy()).astype(float)
    stock_return = np.vstack(history.pop("stock_return_history").to_numpy()).astype(float)
    turnover = np.vstack(history.pop("turnover_history").to_numpy()).astype(float)
    if residual.shape[1] != HISTORY_ENDPOINTS:
        raise ResearchError(f"unexpected residual history width: {residual.shape}")

    prior_rho, prior_valid = row_spearman(residual[:, :40], residual[:, 1:41])
    recent_rho, recent_valid = row_spearman(residual[:, 40:60], residual[:, 41:61])
    representation = history.copy()
    representation["prior_serial_dependence"] = prior_rho
    representation["recent_serial_dependence"] = recent_rho
    representation["serial_phase_change"] = recent_rho - prior_rho
    representation["raw_return_20"] = np.expm1(np.log1p(stock_return[:, 41:]).sum(axis=1))
    representation["raw_return_60"] = np.expm1(np.log1p(stock_return[:, 1:]).sum(axis=1))
    representation["return_volatility_60"] = stock_return[:, 1:].std(axis=1, ddof=1)
    representation["turnover_ratio_1_to_60"] = turnover[:, -1] / turnover[:, 1:].mean(axis=1)
    finite = np.isfinite(
        representation[
            [
                "prior_serial_dependence",
                "recent_serial_dependence",
                "serial_phase_change",
                *CONTROLS,
            ]
        ].to_numpy(dtype=float)
    ).all(axis=1)
    valid = prior_valid & recent_valid & finite
    audit = {
        "exact_history_rows": len(representation),
        "nondegenerate_prior_rows": int(prior_valid.sum()),
        "nondegenerate_recent_rows": int(recent_valid.sum()),
        "complete_representation_rows": int(valid.sum()),
        "degenerate_or_nonfinite_rows_rejected": int((~valid).sum()),
    }
    return representation.loc[valid].reset_index(drop=True), audit


def same_date_median_spearman(
    frame: pd.DataFrame, control: str, groups: list[str], minimum: int
) -> tuple[float | None, int]:
    correlations: list[float] = []
    for _, part in frame.groupby(groups, sort=True):
        values = part[["serial_phase_change", control]].dropna()
        if len(values) < minimum or values.nunique().min() < 3:
            continue
        rho = values.serial_phase_change.corr(values[control], method="spearman")
        if pd.notna(rho):
            correlations.append(float(rho))
    return (None if not correlations else float(np.median(correlations)), len(correlations))


def causal_cooldown(frame: pd.DataFrame) -> pd.DataFrame:
    retained: list[int] = []
    for _, part in frame.groupby("symbol", sort=False):
        last_cal_idx: int | None = None
        for row in part.sort_values(["signal_cal_idx", "event_id"]).itertuples():
            cal_idx = int(row.signal_cal_idx)
            if last_cal_idx is None or cal_idx > last_cal_idx + COOLDOWN:
                retained.append(int(row.Index))
                last_cal_idx = cal_idx
    return (
        frame.loc[retained]
        .sort_values(["signal_date", "causal_industry", "symbol"], kind="mergesort")
        .reset_index(drop=True)
    )


def select_candidates(representation: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    transition = representation.loc[
        representation.prior_serial_dependence.le(0)
        & representation.recent_serial_dependence.gt(0)
        & representation.current_residual_return.gt(0)
        & representation.amount.ge(representation.same_date_median_amount)
    ].copy()
    transition = transition.sort_values(
        ["signal_date", "causal_industry", "serial_phase_change", "amount", "symbol"],
        ascending=[True, True, False, False, True],
        kind="mergesort",
    )
    selected = transition.groupby(["signal_date", "causal_industry"], sort=False).head(1).copy()
    selected.insert(
        0,
        "event_id",
        selected.apply(
            lambda row: (
                f"RESIDUAL_SERIAL_PHASE|{pd.Timestamp(row.signal_date):%Y%m%d}|"
                f"{row.causal_industry}|{row.symbol}"
            ),
            axis=1,
        ),
    )
    before_cooldown = len(selected)
    return causal_cooldown(selected), before_cooldown


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    connection.close()


def summarize(
    representation: pd.DataFrame,
    candidates: pd.DataFrame,
    before_cooldown: int,
    source_hashes: dict[str, str],
    build_audit: dict[str, int],
    representation_audit: dict[str, int],
    representation_path: Path,
    candidates_path: Path,
) -> dict[str, Any]:
    for column in ("signal_date", "decision_at", "available_at"):
        representation[column] = pd.to_datetime(representation[column])
        candidates[column] = pd.to_datetime(candidates[column])

    redundancy: dict[str, Any] = {}
    redundancy_pass = True
    for control in CONTROLS:
        global_rho, global_groups = same_date_median_spearman(
            representation, control, ["signal_date"], 20
        )
        industry_rho, industry_groups = same_date_median_spearman(
            representation, control, ["signal_date", "causal_industry"], 10
        )
        redundancy[control] = {
            "global_same_date_median_spearman": global_rho,
            "global_date_groups": global_groups,
            "pit_industry_same_date_median_spearman": industry_rho,
            "pit_industry_date_groups": industry_groups,
            "absolute_limit": REDUNDANCY_LIMIT,
        }
        redundancy_pass &= (
            global_rho is not None
            and industry_rho is not None
            and abs(global_rho) < REDUNDANCY_LIMIT
            and abs(industry_rho) < REDUNDANCY_LIMIT
        )

    cooldown_failures = 0
    for _, part in candidates.groupby("symbol"):
        cooldown_failures += int(
            part.signal_cal_idx.sort_values().diff().dropna().le(COOLDOWN).sum()
        )
    audit = {
        **build_audit,
        **representation_audit,
        "transition_rows_before_industry_selection": int(
            (
                representation.prior_serial_dependence.le(0)
                & representation.recent_serial_dependence.gt(0)
                & representation.current_residual_return.gt(0)
                & representation.amount.ge(representation.same_date_median_amount)
            ).sum()
        ),
        "industry_selected_rows_before_cooldown": before_cooldown,
        "candidate_rows": len(candidates),
        "duplicate_event_ids": int(candidates.event_id.duplicated().sum()),
        "timing_failures": int(candidates.available_at.gt(candidates.decision_at).sum()),
        "post_max_signal_rows": int(candidates.signal_date.gt(SIGNAL_END).sum()),
        "pre_signal_start_rows": int(candidates.signal_date.lt(SIGNAL_START).sum()),
        "positive_direction_failures": int(candidates.current_residual_return.le(0).sum()),
        "phase_transition_failures": int(
            (
                candidates.prior_serial_dependence.gt(0) | candidates.recent_serial_dependence.le(0)
            ).sum()
        ),
        "liquidity_failures": int(candidates.amount.lt(candidates.same_date_median_amount).sum()),
        "history_failures": int(
            (
                candidates.history_endpoint_count.ne(HISTORY_ENDPOINTS)
                | candidates.history_first_cal_idx.ne(candidates.signal_cal_idx - 60)
                | candidates.history_last_cal_idx.ne(candidates.signal_cal_idx)
            ).sum()
        ),
        "cooldown_failures": cooldown_failures,
    }
    fatal = (
        "duplicate_event_ids",
        "timing_failures",
        "post_max_signal_rows",
        "pre_signal_start_rows",
        "positive_direction_failures",
        "phase_transition_failures",
        "liquidity_failures",
        "history_failures",
        "cooldown_failures",
    )
    if any(audit[key] for key in fatal):
        raise ResearchError(f"V31 Stage-A audit failed: {audit}")

    annual: dict[str, Any] = {}
    opportunity_pass = True
    for year in YEARS:
        part = candidates.loc[candidates.signal_date.dt.year.eq(year)]
        annual[str(year)] = {
            "events": len(part),
            "decision_dates": int(part.signal_date.nunique()),
            "symbols": int(part.symbol.nunique()),
            "industries": int(part.causal_industry.nunique()),
        }
        opportunity_pass &= len(part) > 50 and part.signal_date.nunique() >= 5

    return {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_REPRESENTATION_AND_CANDIDATE_FREEZE",
        "scientific_definition": (
            "PIT leave-one-out industry daily residual changes from nonpositive prior-40 "
            "lag-one Spearman dependence to positive recent-20 dependence; current "
            "residual is positive"
        ),
        "source_hashes": source_hashes,
        "representation_sha256": sha256(representation_path),
        "candidate_sha256": sha256(candidates_path),
        "audit": audit,
        "annual": annual,
        "redundancy": redundancy,
        "opportunity_gate_passed": bool(opportunity_pass),
        "redundancy_gate_passed": bool(redundancy_pass),
        "stage_a_gate_passed": bool(opportunity_pass and redundancy_pass),
        "outcome_columns_read": False,
        "post_signal_rows_read": False,
        "post_2020_rows_read": False,
        "maximum_source_row_date": str(MAX_ROW_DATE.date()),
        "maximum_signal_date": str(SIGNAL_END.date()),
        "prototype_superseded": (
            "Earlier no-outcome Pearson/latest-path readiness counts were nonbinding; this is the "
            "first and only frozen Spearman/current-residual Stage-A run."
        ),
        "next_action": (
            "WRITE_A_SEPARATE_HASH_BOUND_STAGE_B_OUTCOME_CONTRACT"
            if opportunity_pass and redundancy_pass
            else "CLOSE_V31_BEFORE_ANY_OUTCOME_READ_NO_DEFINITION_RESCUE"
        ),
    }


def main() -> None:
    source_hashes = verify_inputs()
    if STAGE_A.exists():
        raise ResearchError(f"canonical V31 Stage A already exists: {STAGE_A}")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".stage_a_staging_", dir=OUTPUT_ROOT))
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = connect(staging / "duckdb_tmp")
        history, build_audit = build_history(connection)
        connection.close()
        connection = None
        representation, representation_audit = make_representation(history)
        candidates, before_cooldown = select_candidates(representation)
        representation_path = staging / "representation_panel.parquet"
        candidates_path = staging / "candidates_frozen.parquet"
        write_parquet(representation, representation_path)
        write_parquet(candidates, candidates_path)
        result = summarize(
            representation,
            candidates,
            before_cooldown,
            source_hashes,
            build_audit,
            representation_audit,
            representation_path,
            candidates_path,
        )
        (staging / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(staging / "duckdb_tmp", ignore_errors=True)
        staging.replace(STAGE_A)
    except Exception:
        if connection is not None:
            connection.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
