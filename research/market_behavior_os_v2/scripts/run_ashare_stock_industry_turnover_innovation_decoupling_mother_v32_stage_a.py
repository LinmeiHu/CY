#!/usr/bin/env python3
"""Build the outcome-blind V32 turnover-innovation independence mother."""

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

EXPERIMENT = "ASHARE-STOCK-INDUSTRY-TURNOVER-INNOVATION-DECOUPLING-MOTHER-V32"
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
V30_REPRESENTATION = Path(
    "/Volumes/quant/CY_quant_research/ashare_low_positive_feedback_good_news_mother_v30/"
    "stage_a/representation_panel.parquet"
)
V31_REPRESENTATION = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_industry_residual_serial_phase_change_mother_v31/"
    "stage_a/representation_panel.parquet"
)
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_stock_industry_turnover_innovation_decoupling_mother_v32"
)
STAGE_A = OUTPUT_ROOT / "stage_a"

EXPECTED_SPEC = "d389cda8f743441a4c46df61a2c044169f33550d05a5153bb96bea5abab75089"
EXPECTED_MANIFEST = "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2"
EXPECTED_PARTITIONS = {
    PARTITIONS[0]: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    PARTITIONS[1]: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    PARTITIONS[2]: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
}
EXPECTED_CONTROLS = {
    V30_REPRESENTATION: "3408f5728764331ec910c649ef8ef65afb80703d6e22e7bfaefd845b3be5ba4b",
    V31_REPRESENTATION: "91f18e9ca0646a33ceb172ad45293ee4e4979f0b4e5ffce865dca9841249f62c",
}
MAX_ROW_DATE = pd.Timestamp("2020-06-30")
SIGNAL_START = pd.Timestamp("2018-07-01")
SIGNAL_END = pd.Timestamp("2020-06-30")
YEARS = (2018, 2019, 2020)
TARGET_HISTORY_ENDPOINTS = 83
COUPLING_PAIRS = 80
MAIN_WINDOW = 60
SHORT_AUDIT_WINDOW = 40
MIN_OTHER_PEERS = 10
MIN_INDUSTRY_REPRESENTATIONS = 10
COOLDOWN = 20
STABILITY_MINIMUM = 0.70
REDUNDANCY_LIMIT = 0.80
CONTROL_COLUMNS = (
    "current_turnover_innovation",
    "turnover_to_prior20_median",
    "mean_turnover_20_to_60",
    "raw_return_20",
    "raw_return_60",
    "return_volatility_60",
    "v30_turnover_pfc_score",
    "v31_serial_phase_change",
)


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, PIT timing, history, or representation drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    expected = {
        SPEC: EXPECTED_SPEC,
        MANIFEST: EXPECTED_MANIFEST,
        **EXPECTED_PARTITIONS,
        **EXPECTED_CONTROLS,
    }
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
    connection.execute("SET threads=2")
    connection.execute("SET memory_limit='12GB'")
    connection.execute("SET preserve_insertion_order=false")
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
        & (left_distinct >= 3)
        & (right_distinct >= 3)
    )
    rho = np.full(left.shape[0], np.nan, dtype=float)
    rho[valid] = np.sum(left_centered[valid] * right_centered[valid], axis=1) / denominator[
        valid
    ]
    return rho, valid


def build_histories(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[pd.DataFrame, dict[str, int]]:
    paths = ",".join(f"'{path.as_posix()}'" for path in PARTITIONS)
    source_audit = connection.execute(
        f"""
        SELECT count(*) AS rows,
          count(*)-count(DISTINCT (trade_date,symbol)) AS duplicate_keys,
          count(*) FILTER (WHERE hard_valid AND available_at>decision_at)
            AS hard_valid_time_travel_rows,
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
    if source_audit[3] is None or pd.Timestamp(source_audit[4]) > MAX_ROW_DATE:
        raise ResearchError(f"primary-source date cap failed: {source_audit[3:5]}")
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
          d.decision_at,d.available_at,d.amount,d.turnover_fraction,
          d.close/d.preclose-1.0 AS stock_return,
          true AS snapshot_identity_complete
        FROM cy006 d JOIN market_calendar c USING(trade_date)
        WHERE d.trade_date<=DATE '{MAX_ROW_DATE.date()}'
          AND (
            regexp_matches(d.symbol,'^(600|601|603|605)[0-9]{{3}}[.]SH$')
            OR regexp_matches(d.symbol,'^(000|001|002|300|301)[0-9]{{3}}[.]SZ$')
          )
          AND coalesce(d.hard_valid AND d.bar_valid AND d.trading_state_valid
            AND d.industry_valid AND d.float_valid AND d.corporate_action_valid
            AND NOT d.corporate_action_blocking AND d.market_valid
            AND d.market_rule_valid AND d.historical_identity_valid
            AND d.current_day_data_tradable AND d.trade_status=1 AND NOT d.is_st
            AND d.available_at<=d.decision_at
            AND d.industry IS NOT NULL AND d.snapshot_id IS NOT NULL
            AND d.daily_snapshot_id IS NOT NULL
            AND d.trading_state_snapshot_id IS NOT NULL
            AND d.industry_snapshot_id IS NOT NULL
            AND d.float_snapshot_id IS NOT NULL
            AND d.corporate_action_snapshot_id IS NOT NULL
            AND d.market_snapshot_id IS NOT NULL
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
    audit["eligible_rows"] = int(
        connection.execute("SELECT count(*) FROM eligible").fetchone()[0]
    )
    connection.execute(
        """
        CREATE TEMP TABLE paired_innovations AS
        SELECT e.trade_date,e.cal_idx,e.symbol,e.causal_industry,e.decision_at,
          e.available_at,
          ln(e.turnover_fraction/p.turnover_fraction) AS stock_turnover_innovation
        FROM eligible e
        JOIN eligible p ON p.symbol=e.symbol AND p.cal_idx=e.cal_idx-1
        WHERE p.causal_industry=e.causal_industry
          AND isfinite(ln(e.turnover_fraction/p.turnover_fraction))
        """
    )
    audit["paired_innovation_rows"] = int(
        connection.execute("SELECT count(*) FROM paired_innovations").fetchone()[0]
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE industry_innovation_groups AS
        SELECT trade_date,causal_industry,count(*) AS industry_member_count,
          list_sort(list(stock_turnover_innovation)) AS sorted_innovations,
          max(available_at) AS industry_latest_available_at,
          min(decision_at) AS industry_first_decision_at,
          max(decision_at) AS industry_last_decision_at
        FROM paired_innovations
        GROUP BY trade_date,causal_industry
        HAVING count(*)>={MIN_OTHER_PEERS + 1}
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE innovation_context AS
        SELECT p.trade_date,p.cal_idx,p.symbol,p.causal_industry,
          p.stock_turnover_innovation,g.industry_member_count,
          g.industry_member_count-1 AS other_peer_count,
          CASE
            WHEN g.industry_member_count%2=0
                 AND p.stock_turnover_innovation<=list_extract(
                   g.sorted_innovations,floor(g.industry_member_count/2)::BIGINT
                 )
              THEN list_extract(
                g.sorted_innovations,floor(g.industry_member_count/2)::BIGINT+1
              )
            WHEN g.industry_member_count%2=0
              THEN list_extract(
                g.sorted_innovations,floor(g.industry_member_count/2)::BIGINT
              )
            WHEN p.stock_turnover_innovation<list_extract(
                   g.sorted_innovations,floor(g.industry_member_count/2)::BIGINT+1
                 )
              THEN (
                list_extract(
                  g.sorted_innovations,floor(g.industry_member_count/2)::BIGINT+1
                )+list_extract(
                  g.sorted_innovations,floor(g.industry_member_count/2)::BIGINT+2
                )
              )/2.0
            WHEN p.stock_turnover_innovation>list_extract(
                   g.sorted_innovations,floor(g.industry_member_count/2)::BIGINT+1
                 )
              THEN (
                list_extract(
                  g.sorted_innovations,floor(g.industry_member_count/2)::BIGINT
                )+list_extract(
                  g.sorted_innovations,floor(g.industry_member_count/2)::BIGINT+1
                )
              )/2.0
            ELSE (
              list_extract(
                g.sorted_innovations,floor(g.industry_member_count/2)::BIGINT
              )+list_extract(
                g.sorted_innovations,floor(g.industry_member_count/2)::BIGINT+2
              )
            )/2.0
          END AS leave_one_out_industry_innovation
        FROM paired_innovations p
        JOIN industry_innovation_groups g USING(trade_date,causal_industry)
        WHERE g.industry_latest_available_at<=p.decision_at
          AND g.industry_first_decision_at=p.decision_at
          AND g.industry_last_decision_at=p.decision_at
        """
    )
    audit["innovation_context_rows"] = int(
        connection.execute("SELECT count(*) FROM innovation_context").fetchone()[0]
    )
    connection.execute("DROP TABLE industry_innovation_groups")
    connection.execute("DROP TABLE paired_innovations")
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
    connection.execute(
        f"""
        CREATE TEMP TABLE target_history_audit AS
        SELECT a.trade_date AS signal_date,a.cal_idx AS signal_cal_idx,a.symbol,
          a.causal_industry,
          count(*) AS history_endpoint_count,
          min(h.cal_idx) AS history_first_cal_idx,
          max(h.cal_idx) AS history_last_cal_idx,
          count(*) FILTER (WHERE h.causal_industry<>a.causal_industry)
            AS history_industry_mismatch_rows,
          count(*) FILTER (WHERE h.snapshot_identity_complete)
            AS history_rows_with_complete_snapshot_identity
        FROM eligible a
        JOIN month_ends m ON m.trade_date=a.trade_date AND m.cal_idx=a.cal_idx
        JOIN eligible h ON h.symbol=a.symbol
          AND h.cal_idx BETWEEN a.cal_idx-{TARGET_HISTORY_ENDPOINTS - 1} AND a.cal_idx
        WHERE a.trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{SIGNAL_END.date()}'
        GROUP BY a.trade_date,a.cal_idx,a.symbol,a.causal_industry
        """
    )
    audit["month_end_anchor_rows_before_exact_history"] = int(
        connection.execute("SELECT count(*) FROM target_history_audit").fetchone()[0]
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE exact_anchor_keys AS
        SELECT * FROM target_history_audit
        WHERE history_endpoint_count={TARGET_HISTORY_ENDPOINTS}
          AND history_first_cal_idx=signal_cal_idx-{TARGET_HISTORY_ENDPOINTS - 1}
          AND history_last_cal_idx=signal_cal_idx
          AND history_industry_mismatch_rows=0
          AND history_rows_with_complete_snapshot_identity={TARGET_HISTORY_ENDPOINTS}
        """
    )
    audit["exact_target_history_rows"] = int(
        connection.execute("SELECT count(*) FROM exact_anchor_keys").fetchone()[0]
    )
    audit["target_history_rows_rejected"] = (
        audit["month_end_anchor_rows_before_exact_history"]
        - audit["exact_target_history_rows"]
    )
    if not audit["exact_target_history_rows"]:
        raise ResearchError("no exact V32 target histories")

    target_metadata = connection.execute(
        f"""
        SELECT k.signal_date,k.signal_cal_idx,k.symbol,k.causal_industry,
          d.decision_at,d.available_at,d.snapshot_id,d.daily_snapshot_id,
          d.trading_state_snapshot_id,d.industry_snapshot_id,d.float_snapshot_id,
          d.corporate_action_snapshot_id,d.market_snapshot_id,d.amount,
          d.turnover_fraction,k.history_endpoint_count,k.history_first_cal_idx,
          k.history_last_cal_idx,k.history_industry_mismatch_rows,
          k.history_rows_with_complete_snapshot_identity
        FROM exact_anchor_keys k
        JOIN cy006 d ON d.trade_date=k.signal_date AND d.symbol=k.symbol
          AND d.industry=k.causal_industry
        WHERE d.trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{SIGNAL_END.date()}'
        ORDER BY k.signal_date,k.causal_industry,k.symbol
        """
    ).fetch_df()
    if len(target_metadata) != audit["exact_target_history_rows"]:
        raise ResearchError("exact-anchor metadata join changed row count")

    target_values = connection.execute(
        f"""
        SELECT k.signal_date,k.signal_cal_idx,k.symbol,k.causal_industry,
          count(*) AS target_value_history_count,
          list(h.turnover_fraction ORDER BY h.cal_idx) AS turnover_history,
          list(h.stock_return ORDER BY h.cal_idx) AS stock_return_history
        FROM exact_anchor_keys k
        JOIN eligible h ON h.symbol=k.symbol
          AND h.cal_idx BETWEEN k.signal_cal_idx-{TARGET_HISTORY_ENDPOINTS - 1}
                            AND k.signal_cal_idx
        GROUP BY k.signal_date,k.signal_cal_idx,k.symbol,k.causal_industry
        ORDER BY k.signal_date,k.causal_industry,k.symbol
        """
    ).fetch_df()
    if (
        len(target_values) != audit["exact_target_history_rows"]
        or not target_values.target_value_history_count.eq(TARGET_HISTORY_ENDPOINTS).all()
    ):
        raise ResearchError("exact-anchor value-history collection drift")
    target_history = target_metadata.merge(
        target_values.drop(columns="target_value_history_count"),
        on=["signal_date", "signal_cal_idx", "symbol", "causal_industry"],
        how="inner",
        validate="one_to_one",
    )
    target_history["same_date_exact_history_n"] = target_history.groupby(
        "signal_date"
    ).symbol.transform("size")
    target_history["same_date_median_amount"] = target_history.groupby(
        "signal_date"
    ).amount.transform("median")
    connection.execute("DROP TABLE target_history_audit")
    connection.execute("DROP TABLE month_ends")
    connection.execute("DROP TABLE market_calendar")
    coupling_history = connection.execute(
        f"""
        SELECT a.signal_date,a.signal_cal_idx,a.symbol,a.causal_industry,
          count(*) AS coupling_pair_count,
          min(i.cal_idx) AS coupling_first_cal_idx,
          max(i.cal_idx) AS coupling_last_cal_idx,
          min(i.other_peer_count) AS minimum_other_peer_count,
          list(i.stock_turnover_innovation ORDER BY i.cal_idx)
            AS stock_innovation_history,
          list(i.leave_one_out_industry_innovation ORDER BY i.cal_idx)
            AS industry_innovation_history
        FROM exact_anchor_keys a
        JOIN innovation_context i ON i.symbol=a.symbol
          AND i.causal_industry=a.causal_industry
          AND i.cal_idx BETWEEN a.signal_cal_idx-{COUPLING_PAIRS - 1}
                            AND a.signal_cal_idx
        GROUP BY a.signal_date,a.signal_cal_idx,a.symbol,a.causal_industry
        ORDER BY a.signal_date,a.causal_industry,a.symbol
        """
    ).fetch_df()
    connection.execute("DROP TABLE exact_anchor_keys")
    connection.execute("DROP TABLE innovation_context")
    connection.execute("DROP TABLE eligible")
    audit["target_rows_with_any_coupling_context"] = len(coupling_history)
    audit["target_rows_without_any_coupling_context"] = len(target_history) - len(
        coupling_history
    )
    exact_coupling = (
        coupling_history.coupling_pair_count.eq(COUPLING_PAIRS)
        & coupling_history.coupling_first_cal_idx.eq(
            coupling_history.signal_cal_idx - (COUPLING_PAIRS - 1)
        )
        & coupling_history.coupling_last_cal_idx.eq(coupling_history.signal_cal_idx)
        & coupling_history.minimum_other_peer_count.ge(MIN_OTHER_PEERS)
    )
    coupling_history = coupling_history.loc[exact_coupling].reset_index(drop=True)
    audit["exact_coupling_history_rows"] = len(coupling_history)
    audit["coupling_history_rows_rejected"] = int((~exact_coupling).sum())
    audit["target_rows_without_complete_coupling_context"] = len(target_history) - len(
        coupling_history
    )
    history = target_history.merge(
        coupling_history,
        on=["signal_date", "signal_cal_idx", "symbol", "causal_industry"],
        how="inner",
        validate="one_to_one",
    )
    audit["complete_history_rows"] = len(history)
    return history, audit


def make_representation(history: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    turnover = np.vstack(history.pop("turnover_history").to_numpy()).astype(float)
    stock_return = np.vstack(history.pop("stock_return_history").to_numpy()).astype(float)
    stock_innovation = np.vstack(history.pop("stock_innovation_history").to_numpy()).astype(float)
    industry_innovation = np.vstack(
        history.pop("industry_innovation_history").to_numpy()
    ).astype(float)
    if (
        turnover.shape[1] != TARGET_HISTORY_ENDPOINTS
        or stock_return.shape[1] != TARGET_HISTORY_ENDPOINTS
    ):
        raise ResearchError(f"unexpected V32 target history shapes: {turnover.shape}")
    if stock_innovation.shape[1] != COUPLING_PAIRS:
        raise ResearchError(f"unexpected V32 coupling history shape: {stock_innovation.shape}")

    rho_80, valid_80 = row_spearman(stock_innovation, industry_innovation)
    rho_60, valid_60 = row_spearman(
        stock_innovation[:, -MAIN_WINDOW:], industry_innovation[:, -MAIN_WINDOW:]
    )
    rho_40, valid_40 = row_spearman(
        stock_innovation[:, -SHORT_AUDIT_WINDOW:],
        industry_innovation[:, -SHORT_AUDIT_WINDOW:],
    )
    representation = history.copy()
    representation["rho_40"] = rho_40
    representation["rho_60"] = rho_60
    representation["rho_80"] = rho_80
    representation["independence_d40"] = 1.0 - np.square(rho_40)
    representation["independence_d60"] = 1.0 - np.square(rho_60)
    representation["independence_d80"] = 1.0 - np.square(rho_80)
    representation["current_turnover_innovation"] = stock_innovation[:, -1]
    representation["prior20_median_turnover"] = np.median(turnover[:, -21:-1], axis=1)
    representation["turnover_to_prior20_median"] = (
        turnover[:, -1] / representation.prior20_median_turnover.to_numpy()
    )
    representation["mean_turnover_20"] = turnover[:, -20:].mean(axis=1)
    representation["mean_turnover_60"] = turnover[:, -60:].mean(axis=1)
    representation["mean_turnover_20_to_60"] = (
        representation.mean_turnover_20 / representation.mean_turnover_60
    )
    representation["raw_return_20"] = np.expm1(
        np.log1p(stock_return[:, -20:]).sum(axis=1)
    )
    representation["raw_return_60"] = np.expm1(
        np.log1p(stock_return[:, -60:]).sum(axis=1)
    )
    representation["return_volatility_60"] = stock_return[:, -60:].std(axis=1, ddof=1)
    finite_columns = [
        "rho_40",
        "rho_60",
        "rho_80",
        "independence_d40",
        "independence_d60",
        "independence_d80",
        *CONTROL_COLUMNS[:6],
    ]
    finite = np.isfinite(representation[finite_columns].to_numpy(dtype=float)).all(axis=1)
    bounded = representation[
        ["independence_d40", "independence_d60", "independence_d80"]
    ].ge(0.0).all(axis=1) & representation[
        ["independence_d40", "independence_d60", "independence_d80"]
    ].le(1.0).all(axis=1)
    positive_denominators = (
        representation.prior20_median_turnover.gt(0)
        & representation.mean_turnover_20.gt(0)
        & representation.mean_turnover_60.gt(0)
    )
    valid = valid_40 & valid_60 & valid_80 & finite & bounded & positive_denominators
    audit = {
        "complete_history_rows": len(representation),
        "nondegenerate_d40_rows": int(valid_40.sum()),
        "nondegenerate_d60_rows": int(valid_60.sum()),
        "nondegenerate_d80_rows": int(valid_80.sum()),
        "complete_representation_rows": int(valid.sum()),
        "degenerate_nonfinite_or_out_of_bounds_rows_rejected": int((~valid).sum()),
    }
    return representation.loc[valid].reset_index(drop=True), audit


def attach_outcome_blind_controls(
    connection: duckdb.DuckDBPyConnection, representation: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    v30 = connection.execute(
        f"""
        SELECT CAST(trade_date AS TIMESTAMP) AS signal_date,symbol,turnover_pfc_score
        FROM read_parquet('{V30_REPRESENTATION.as_posix()}')
        WHERE trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{SIGNAL_END.date()}'
        """
    ).fetch_df()
    v31 = connection.execute(
        f"""
        SELECT CAST(signal_date AS TIMESTAMP) AS signal_date,symbol,serial_phase_change
        FROM read_parquet('{V31_REPRESENTATION.as_posix()}')
        WHERE signal_date BETWEEN TIMESTAMP '{SIGNAL_START}' AND TIMESTAMP '{SIGNAL_END}'
        """
    ).fetch_df()
    if v30.empty or v31.empty:
        raise ResearchError("one or more frozen outcome-blind controls have no rows")
    for frame in (v30, v31):
        frame["signal_date"] = pd.to_datetime(frame.signal_date)
    audit: dict[str, Any] = {
        "v30_control_rows": len(v30),
        "v30_control_duplicate_keys": int(v30.duplicated(["signal_date", "symbol"]).sum()),
        "v30_control_min_queried_date": str(v30.signal_date.min().date()),
        "v30_control_max_queried_date": str(v30.signal_date.max().date()),
        "v30_control_out_of_range_rows": int(
            (~v30.signal_date.between(SIGNAL_START, SIGNAL_END, inclusive="both")).sum()
        ),
        "v31_control_rows": len(v31),
        "v31_control_duplicate_keys": int(v31.duplicated(["signal_date", "symbol"]).sum()),
        "v31_control_min_queried_date": str(v31.signal_date.min().date()),
        "v31_control_max_queried_date": str(v31.signal_date.max().date()),
        "v31_control_out_of_range_rows": int(
            (~v31.signal_date.between(SIGNAL_START, SIGNAL_END, inclusive="both")).sum()
        ),
    }
    if (
        audit["v30_control_duplicate_keys"]
        or audit["v31_control_duplicate_keys"]
        or audit["v30_control_out_of_range_rows"]
        or audit["v31_control_out_of_range_rows"]
        or v30.signal_date.max() > SIGNAL_END
        or v31.signal_date.max() > SIGNAL_END
    ):
        raise ResearchError(f"frozen control identity/date audit failed: {audit}")
    frame = representation.copy()
    frame["signal_date"] = pd.to_datetime(frame.signal_date)
    frame = frame.merge(
        v30.rename(columns={"turnover_pfc_score": "v30_turnover_pfc_score"}),
        on=["signal_date", "symbol"],
        how="left",
        validate="one_to_one",
    )
    frame = frame.merge(
        v31.rename(columns={"serial_phase_change": "v31_serial_phase_change"}),
        on=["signal_date", "symbol"],
        how="left",
        validate="one_to_one",
    )
    audit["v30_exact_overlap_rows"] = int(frame.v30_turnover_pfc_score.notna().sum())
    audit["v31_exact_overlap_rows"] = int(frame.v31_serial_phase_change.notna().sum())
    return frame, audit


def add_cross_sectional_context(representation: pd.DataFrame) -> pd.DataFrame:
    frame = representation.copy()
    frame["industry_exact_history_n"] = frame.groupby(
        ["signal_date", "causal_industry"]
    ).symbol.transform("size")
    return frame.sort_values(
        ["signal_date", "causal_industry", "independence_d60", "amount", "symbol"],
        ascending=[True, True, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)


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
    eligible = representation.loc[
        representation.amount.ge(representation.same_date_median_amount)
        & representation.industry_exact_history_n.ge(MIN_INDUSTRY_REPRESENTATIONS)
    ].copy()
    eligible = eligible.sort_values(
        ["signal_date", "causal_industry", "independence_d60", "amount", "symbol"],
        ascending=[True, True, False, False, True],
        kind="mergesort",
    )
    selected = eligible.groupby(["signal_date", "causal_industry"], sort=False).head(1).copy()
    selected.insert(
        0,
        "event_id",
        selected.apply(
            lambda row: (
                f"TURNOVER_INNOVATION_INDEPENDENCE|{pd.Timestamp(row.signal_date):%Y%m%d}|"
                f"{row.causal_industry}|{row.symbol}"
            ),
            axis=1,
        ),
    )
    before_cooldown = len(selected)
    return causal_cooldown(selected), before_cooldown


def deterministic_selection_failures(
    representation: pd.DataFrame, candidates: pd.DataFrame
) -> int:
    """Verify retained rows remain the exact frozen winner before cooldown."""
    pool = representation.loc[
        representation.amount.ge(representation.same_date_median_amount)
        & representation.industry_exact_history_n.ge(MIN_INDUSTRY_REPRESENTATIONS)
    ].copy()
    pool = pool.sort_values(
        ["signal_date", "causal_industry", "independence_d60", "amount", "symbol"],
        ascending=[True, True, False, False, True],
        kind="mergesort",
    )
    expected = pool.groupby(["signal_date", "causal_industry"], sort=False).head(1)[
        ["signal_date", "causal_industry", "symbol"]
    ]
    checked = candidates[["signal_date", "causal_industry", "symbol"]].merge(
        expected.rename(columns={"symbol": "expected_symbol"}),
        on=["signal_date", "causal_industry"],
        how="left",
        validate="many_to_one",
    )
    missing = checked.expected_symbol.isna()
    mismatch = checked.expected_symbol.notna() & checked.symbol.ne(checked.expected_symbol)
    return int(missing.sum() + mismatch.sum())


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    connection.close()


def median_group_spearman(
    frame: pd.DataFrame,
    left: str,
    right: str,
    groups: list[str],
    minimum: int,
) -> tuple[float | None, int, int]:
    correlations: list[float] = []
    overlap_rows = 0
    for _, part in frame.groupby(groups, sort=True):
        values = part[[left, right]].replace([np.inf, -np.inf], np.nan).dropna()
        overlap_rows += len(values)
        if len(values) < minimum or values.nunique().min() < 3:
            continue
        rho = values[left].corr(values[right], method="spearman")
        if pd.notna(rho):
            correlations.append(float(rho))
    return (
        None if not correlations else float(np.median(correlations)),
        len(correlations),
        overlap_rows,
    )


def correlation_diagnostic(
    frame: pd.DataFrame, left: str, right: str
) -> dict[str, float | int | None]:
    global_rho, global_groups, global_overlap = median_group_spearman(
        frame, left, right, ["signal_date"], 20
    )
    industry_rho, industry_groups, industry_overlap = median_group_spearman(
        frame, left, right, ["signal_date", "causal_industry"], 10
    )
    return {
        "global_same_date_median_spearman": global_rho,
        "global_date_groups": global_groups,
        "global_group_overlap_rows": global_overlap,
        "pit_industry_same_date_median_spearman": industry_rho,
        "pit_industry_date_groups": industry_groups,
        "pit_industry_group_overlap_rows": industry_overlap,
        "exact_overlapping_rows": int(frame[[left, right]].dropna().shape[0]),
        "exact_overlapping_dates": int(
            frame.loc[frame[left].notna() & frame[right].notna(), "signal_date"].nunique()
        ),
    }


def summarize(
    representation: pd.DataFrame,
    candidates: pd.DataFrame,
    before_cooldown: int,
    source_hashes: dict[str, str],
    build_audit: dict[str, int],
    representation_audit: dict[str, int],
    control_audit: dict[str, Any],
    representation_path: Path,
    candidates_path: Path,
) -> dict[str, Any]:
    for column in ("signal_date", "decision_at", "available_at"):
        representation[column] = pd.to_datetime(representation[column])
        candidates[column] = pd.to_datetime(candidates[column])

    stability = {
        "d60_vs_d40": correlation_diagnostic(
            representation, "independence_d60", "independence_d40"
        ),
        "d60_vs_d80": correlation_diagnostic(
            representation, "independence_d60", "independence_d80"
        ),
    }
    stability_values = [
        stability[key][field]
        for key in stability
        for field in (
            "global_same_date_median_spearman",
            "pit_industry_same_date_median_spearman",
        )
    ]
    stability_pass = all(
        value is not None and float(value) >= STABILITY_MINIMUM for value in stability_values
    )

    redundancy: dict[str, Any] = {}
    redundancy_pass = True
    for control in CONTROL_COLUMNS:
        diagnostic = correlation_diagnostic(representation, "independence_d60", control)
        diagnostic["absolute_limit"] = REDUNDANCY_LIMIT
        redundancy[control] = diagnostic
        global_rho = diagnostic["global_same_date_median_spearman"]
        industry_rho = diagnostic["pit_industry_same_date_median_spearman"]
        redundancy_pass &= (
            global_rho is not None
            and industry_rho is not None
            and abs(float(global_rho)) < REDUNDANCY_LIMIT
            and abs(float(industry_rho)) < REDUNDANCY_LIMIT
        )

    cooldown_failures = 0
    for _, part in candidates.groupby("symbol"):
        cooldown_failures += int(
            part.signal_cal_idx.sort_values().diff().dropna().le(COOLDOWN).sum()
        )
    audit = {
        **build_audit,
        **representation_audit,
        **control_audit,
        "industry_selected_rows_before_cooldown": before_cooldown,
        "candidate_rows": len(candidates),
        "deterministic_industry_winner_failures": deterministic_selection_failures(
            representation, candidates
        ),
        "duplicate_representation_keys": int(
            representation.duplicated(["signal_date", "symbol"]).sum()
        ),
        "duplicate_event_ids": int(candidates.event_id.duplicated().sum()),
        "timing_failures": int(candidates.available_at.gt(candidates.decision_at).sum()),
        "post_max_signal_rows": int(candidates.signal_date.gt(SIGNAL_END).sum()),
        "pre_signal_start_rows": int(candidates.signal_date.lt(SIGNAL_START).sum()),
        "liquidity_failures": int(
            candidates.amount.lt(candidates.same_date_median_amount).sum()
        ),
        "industry_support_failures": int(
            candidates.industry_exact_history_n.lt(MIN_INDUSTRY_REPRESENTATIONS).sum()
        ),
        "d60_bounds_failures": int(
            (~candidates.independence_d60.between(0.0, 1.0, inclusive="both")).sum()
        ),
        "history_failures": int(
            (
                candidates.history_endpoint_count.ne(TARGET_HISTORY_ENDPOINTS)
                | candidates.history_first_cal_idx.ne(
                    candidates.signal_cal_idx - (TARGET_HISTORY_ENDPOINTS - 1)
                )
                | candidates.history_last_cal_idx.ne(candidates.signal_cal_idx)
                | candidates.history_industry_mismatch_rows.ne(0)
                | candidates.history_rows_with_complete_snapshot_identity.ne(
                    TARGET_HISTORY_ENDPOINTS
                )
                | candidates.coupling_pair_count.ne(COUPLING_PAIRS)
                | candidates.coupling_first_cal_idx.ne(
                    candidates.signal_cal_idx - (COUPLING_PAIRS - 1)
                )
                | candidates.coupling_last_cal_idx.ne(candidates.signal_cal_idx)
                | candidates.minimum_other_peer_count.lt(MIN_OTHER_PEERS)
            ).sum()
        ),
        "cooldown_failures": cooldown_failures,
    }
    fatal = (
        "duplicate_representation_keys",
        "duplicate_event_ids",
        "deterministic_industry_winner_failures",
        "timing_failures",
        "post_max_signal_rows",
        "pre_signal_start_rows",
        "liquidity_failures",
        "industry_support_failures",
        "d60_bounds_failures",
        "history_failures",
        "cooldown_failures",
    )
    if any(audit[key] for key in fatal):
        raise ResearchError(f"V32 Stage-A audit failed: {audit}")

    annual: dict[str, Any] = {}
    opportunity_pass = True
    required_dates = {2018: 6, 2019: 12, 2020: 6}
    for year in YEARS:
        part = candidates.loc[candidates.signal_date.dt.year.eq(year)]
        annual[str(year)] = {
            "events": len(part),
            "decision_dates": int(part.signal_date.nunique()),
            "symbols": int(part.symbol.nunique()),
            "industries": int(part.causal_industry.nunique()),
            "minimum_required_decision_dates": required_dates[year],
        }
        opportunity_pass &= len(part) > 50
        opportunity_pass &= part.signal_date.nunique() >= required_dates[year]
    overall_industries = int(candidates.causal_industry.nunique())
    opportunity_pass &= overall_industries >= 20

    return {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_REPRESENTATION_AND_CANDIDATE_FREEZE",
        "scientific_definition": (
            "D60=1-Spearman(stock turnover innovation, exact leave-one-out PIT-industry "
            "common turnover innovation)^2 over fixed t-59:t; select the highest D60 "
            "within each supported PIT industry"
        ),
        "source_hashes": source_hashes,
        "representation_sha256": sha256(representation_path),
        "candidate_sha256": sha256(candidates_path),
        "audit": audit,
        "annual": annual,
        "overall_industries": overall_industries,
        "neighboring_definition_stability": stability,
        "non_reconstruction": redundancy,
        "opportunity_gate_passed": bool(opportunity_pass),
        "neighboring_stability_gate_passed": bool(stability_pass),
        "non_reconstruction_gate_passed": bool(redundancy_pass),
        "stage_a_gate_passed": bool(
            opportunity_pass and stability_pass and redundancy_pass
        ),
        "outcome_columns_read": False,
        "post_signal_primary_rows_read": False,
        "post_2020_rows_read": False,
        "maximum_primary_source_row_date": str(MAX_ROW_DATE.date()),
        "maximum_signal_date": str(SIGNAL_END.date()),
        "d40_d80_candidate_use": False,
        "price_or_return_candidate_condition": False,
        "direction": "HIGH_D60_ONLY_FROZEN_BEFORE_OUTCOMES",
        "next_action": (
            "WRITE_A_SEPARATE_HASH_BOUND_STAGE_B_OUTCOME_CONTRACT"
            if opportunity_pass and stability_pass and redundancy_pass
            else "CLOSE_V32_BEFORE_ANY_FORWARD_OUTCOME_READ_NO_DEFINITION_RESCUE"
        ),
    }


def main() -> None:
    source_hashes = verify_inputs()
    if STAGE_A.exists():
        raise ResearchError(f"canonical V32 Stage A already exists: {STAGE_A}")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".stage_a_staging_", dir=OUTPUT_ROOT))
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = connect(staging / "duckdb_tmp")
        history, build_audit = build_histories(connection)
        representation, representation_audit = make_representation(history)
        representation, control_audit = attach_outcome_blind_controls(
            connection, representation
        )
        connection.close()
        connection = None
        representation = add_cross_sectional_context(representation)
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
            control_audit,
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
