#!/usr/bin/env python3
"""Build the frozen outcome-blind V36 broad-market price-delay mother."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-BROAD-MARKET-PRICE-DELAY-COMPENSATION-MOTHER-V36"
REPO = Path(__file__).resolve().parents[3]
EXPERIMENTS = REPO / "research/market_behavior_os_v2/experiments"
SPEC = EXPERIMENTS / f"{EXPERIMENT}_freeze.json"
RUNNER = REPO / "research/market_behavior_os_v2/scripts" / Path(__file__).name
MANIFEST = EXPERIMENTS / "ASHARE-V36-CY054_DATA_ASSET_MANIFEST.json"
REGISTRY_SUGGESTION = EXPERIMENTS / "ASHARE-V36-CY054_REGISTRY_SUGGESTION.json"
REGISTRY = REPO / "configs/data_asset_registry.json"
ACTION_CONTRACT = REPO / "src/cyq_game/chip/price_coordinate.py"

CY006_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
CY006_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
QD010_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/QD-010-cninfo-actions-20260820.json"
)
PARTITIONS = tuple(
    CY006_ROOT / f"partition_year={year}/data_0.parquet" for year in (2018, 2019, 2020)
)

OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_broad_market_price_delay_compensation_mother_v36"
)
STAGE_A = OUTPUT_ROOT / "stage_a"

ASSET_ID = "CY-054"
AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-BROAD-MARKET-PRICE-DELAY-V36-STAGE-A-2018-2020-V1"
AUTHORIZATION_PURPOSE = "ASHARE_OUTCOME_BLIND_MOTHER_REPRESENTATION"
AUTHORIZED_ARM = "V36_FROZEN_OUTCOME_BLIND_STAGE_A_ONLY"
MANIFEST_STATUS = "FROZEN_OUTCOME_BLIND_BOUNDED_INPUT"

EXPECTED_SPEC_SHA256 = "2dc6e2b1ac6e29105172cddc8a6d5dbafa06b30645a8f48b08abdf8f348286fc"
EXPECTED_INPUTS: dict[str, tuple[Path, str]] = {
    "corporate_action_coordinate_contract": (
        ACTION_CONTRACT,
        "60c9f80fcaa2bf4a6ebfaab37bc56e81dd716cc3bea00891b4fc28d077dd1726",
    ),
    "cy006_inventory": (
        CY006_INVENTORY,
        "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    ),
    "cy006_2018": (
        PARTITIONS[0],
        "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    ),
    "cy006_2019": (
        PARTITIONS[1],
        "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    ),
    "cy006_2020": (
        PARTITIONS[2],
        "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    ),
    "qd010_inventory": (
        QD010_INVENTORY,
        "e1ca622ee227ce308b44933160754d450b80d3ecca79c1470037558e1011ceb8",
    ),
}

SOURCE_START = pd.Timestamp("2018-01-01")
MAX_ROW_DATE = pd.Timestamp("2020-12-31")
SIGNAL_START = pd.Timestamp("2019-03-01")
SIGNAL_END = pd.Timestamp("2020-12-31")
YEARS = (2019, 2020)
HISTORY_WEEKS = 56
RESPONSE_WEEKS = 52
LAG_COUNT = 4
MIN_OTHER_MARKET_PEERS = 500
MIN_INDUSTRY_REPRESENTATIONS = 12
COOLDOWN_SESSIONS = 60
MIN_ANNUAL_CANDIDATES_EXCLUSIVE = 50
MIN_ANNUAL_INDUSTRIES = 20
MIN_ANNUAL_SYMBOLS_EXCLUSIVE = 50
MIN_DECISION_MONTHS = {2019: 8, 2020: 10}
MIN_DATE_CONTROL_ROWS = 50
MIN_INDUSTRY_CONTROL_ROWS = 8
MIN_CONTROL_DATES = 8
REDUNDANCY_LIMIT = 0.80
NUMERIC_TOLERANCE = 1e-12
CONTROL_COLUMNS = (
    "log_circulating_market_value",
    "annual_amihud",
    "mean_turnover_60",
    "trading_continuity_60",
    "raw_log_return_60",
    "idio_volatility_60",
)


class ResearchError(RuntimeError):
    """Fail closed on authorization, PIT, chronology, representation or publication drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def strict_json(path: Path, label: str) -> dict[str, Any]:
    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
        if duplicates:
            raise ResearchError(f"duplicate JSON keys in {label}: {duplicates}")
        return dict(pairs)

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys)
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResearchError(f"{label} must be one JSON object")
    return value


def role_map(items: object, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        raise ResearchError(f"{label} must be a list")
    mapped: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            raise ResearchError(f"malformed {label} row")
        role = item["role"]
        if role in mapped or set(item) != {"role", "path", "sha256"}:
            raise ResearchError(f"duplicate or malformed {label} role: {role}")
        mapped[role] = item
    return mapped


def verify_role_declarations(items: object, label: str) -> None:
    mapped = role_map(items, label)
    if set(mapped) != set(EXPECTED_INPUTS):
        raise ResearchError(f"{label} exact role set drift")
    for role, (path, expected_hash) in EXPECTED_INPUTS.items():
        if mapped[role] != {"role": role, "path": str(path), "sha256": expected_hash}:
            raise ResearchError(f"{label} lexical binding drift for {role}")


def only(items: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if len(items) != 1:
        raise ResearchError(f"expected exactly one {label}, found {len(items)}")
    return items[0]


def verify_public_contract() -> dict[str, Any]:
    """Verify repository-public declarations without touching any source input path."""

    for path in (SPEC, RUNNER, MANIFEST, REGISTRY_SUGGESTION):
        if not path.is_file():
            raise ResearchError(f"missing V36 public artifact: {path}")
    hashes = {
        "spec": sha256(SPEC),
        "runner": sha256(RUNNER),
        "manifest": sha256(MANIFEST),
        "registry_suggestion": sha256(REGISTRY_SUGGESTION),
    }
    if hashes["spec"] != EXPECTED_SPEC_SHA256:
        raise ResearchError(f"V36 spec drift: {hashes['spec']} != {EXPECTED_SPEC_SHA256}")

    spec = strict_json(SPEC, "V36 spec")
    manifest = strict_json(MANIFEST, "CY-054 manifest")
    suggestion = strict_json(REGISTRY_SUGGESTION, "CY-054 registry suggestion")
    binding = manifest.get("stage_a_binding", {})
    boundary = manifest.get("authorization_boundary", {})
    incident = spec.get("governance_incident_disclosure", {})
    if (
        spec.get("status") != "FROZEN_BEFORE_SOURCE_ACCESS_AWAITING_CY054_REGISTRATION"
        or spec.get("later_stage_boundary", {}).get("outcome_read_authorized") is not False
        or incident.get("used_for_v36_definition_or_selection") is not False
        or manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != MANIFEST_STATUS
        or binding.get("spec") != {"path": str(SPEC), "sha256": hashes["spec"]}
        or binding.get("runner") != {"path": str(RUNNER), "sha256": hashes["runner"]}
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("purpose") != AUTHORIZATION_PURPOSE
        or boundary.get("authorized_arm") != AUTHORIZED_ARM
        or boundary.get("maximum_source_row_date") != str(MAX_ROW_DATE.date())
        or boundary.get("stage_a_authorized") is not True
        or boundary.get("stage_b_authorized") is not False
        or boundary.get("outcome_columns_read_authorized") is not False
        or boundary.get("post_signal_row_read_authorized") is not False
        or boundary.get("2021_read_authorized") is not False
        or boundary.get("2022_plus_read_authorized") is not False
    ):
        raise ResearchError("V36 manifest/spec public semantics drift")
    verify_role_declarations(manifest.get("bound_artifacts"), "manifest bound_artifacts")

    if suggestion.get("central_registry_modified") is not False:
        raise ResearchError("CY-054 suggestion falsely claims central installation")
    asset = suggestion.get("asset")
    authorization = suggestion.get("bounded_authorization")
    if not isinstance(asset, dict) or not isinstance(authorization, dict):
        raise ResearchError("CY-054 suggestion lacks exact registry objects")
    scope = authorization.get("scope", {})
    lineage = asset.get("lineage", {})
    bound_protocol = authorization.get("bound_protocol", {})
    if (
        asset.get("asset_id") != ASSET_ID
        or asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or lineage.get("manifest_path") != str(MANIFEST)
        or lineage.get("manifest_sha256") != hashes["manifest"]
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
        or authorization.get("authorization_id") != AUTHORIZATION_ID
        or authorization.get("asset_id") != ASSET_ID
        or authorization.get("purpose") != AUTHORIZATION_PURPOSE
        or authorization.get("authorized_arms") != [AUTHORIZED_ARM]
        or authorization.get("dependency_asset_ids") != ["CY-006", "QD-010"]
        or scope.get("signal_start") != str(SIGNAL_START.date())
        or scope.get("signal_end") != str(SIGNAL_END.date())
        or scope.get("maximum_source_row_date") != str(MAX_ROW_DATE.date())
        or authorization.get("bound_manifest")
        != {"path": str(MANIFEST), "sha256": hashes["manifest"]}
        or bound_protocol
        != {
            "path": str(SPEC),
            "sha256": hashes["spec"],
            "runner_path": str(RUNNER),
            "runner_sha256": hashes["runner"],
        }
        or authorization.get("stage_a_authorized") is not True
        or authorization.get("stage_b_authorized") is not False
        or authorization.get("source_parquet_stage_a_parse_authorized") is not True
        or authorization.get("outcome_artifact_parse_authorized") is not False
        or authorization.get("outcome_columns_read_authorized") is not False
        or authorization.get("post_signal_row_read_authorized") is not False
        or authorization.get("post_2020_read_authorized") is not False
        or authorization.get("2021_read_authorized") is not False
        or authorization.get("2022_plus_read_authorized") is not False
        or authorization.get("charts_authorized") is not False
        or authorization.get("portfolio_replay_authorized") is not False
        or authorization.get("parameter_search_authorized") is not False
        or authorization.get("current_survivor_fallback_allowed") is not False
    ):
        raise ResearchError("CY-054 registry suggestion semantics drift")
    verify_role_declarations(authorization.get("bound_artifacts"), "authorization artifacts")
    if authorization["bound_artifacts"] != manifest["bound_artifacts"]:
        raise ResearchError("CY-054 manifest/authorization artifact declarations differ")
    for field in ("source", "quality_evidence", "activation_gates"):
        if not asset.get(field):
            raise ResearchError(f"CY-054 asset misses {field}")
    return {"hashes": hashes, "asset": asset, "authorization": authorization}


def verify_registry_install(public: dict[str, Any]) -> None:
    """Require exact reviewed CY-054 installation before any source syscall."""

    registry = strict_json(REGISTRY, "central registry")
    asset = only(
        [item for item in registry.get("assets", []) if item.get("asset_id") == ASSET_ID],
        f"central asset {ASSET_ID}",
    )
    authorization = only(
        [
            item
            for item in registry.get("bounded_authorizations", [])
            if item.get("authorization_id") == AUTHORIZATION_ID
        ],
        f"central authorization {AUTHORIZATION_ID}",
    )
    if asset != public["asset"] or authorization != public["authorization"]:
        raise ResearchError("central CY-054 objects do not exactly match reviewed suggestion")


def verify_source_inputs() -> dict[str, str]:
    """First function authorized to state, hash, resolve or open source paths."""

    actual: dict[str, str] = {}
    for role, (path, expected_hash) in EXPECTED_INPUTS.items():
        if not path.is_file():
            raise ResearchError(f"missing V36 source {role}: {path}")
        value = sha256(path)
        if value != expected_hash:
            raise ResearchError(f"V36 source drift {role}: {value} != {expected_hash}")
        actual[role] = value

    inventory = strict_json(CY006_INVENTORY, "CY-006 inventory")
    entries = {item["path"]: item["sha256"] for item in inventory.get("files", [])}
    if inventory.get("root") != str(CY006_ROOT):
        raise ResearchError("CY-006 inventory root drift")
    for role in ("cy006_2018", "cy006_2019", "cy006_2020"):
        path, expected_hash = EXPECTED_INPUTS[role]
        if entries.get(str(path.relative_to(CY006_ROOT))) != expected_hash:
            raise ResearchError(f"CY-006 inventory partition drift: {role}")

    registry = strict_json(REGISTRY, "central registry source dependencies")
    for asset_id in ("CY-006", "QD-010"):
        asset = only(
            [item for item in registry.get("assets", []) if item.get("asset_id") == asset_id],
            f"dependency asset {asset_id}",
        )
        if asset.get("status") != "RESEARCH_CONDITIONAL":
            raise ResearchError(f"dependency asset status drift: {asset_id}")
    cy006 = next(item for item in registry["assets"] if item.get("asset_id") == "CY-006")
    lineage = cy006.get("lineage", {})
    if (
        cy006.get("pit_grade") != "B"
        or lineage.get("record_available_at") is not True
        or lineage.get("record_snapshot_id") is not True
        or lineage.get("immutable_manifest") is not True
        or lineage.get("manifest_path") != str(CY006_INVENTORY)
        or lineage.get("manifest_sha256") != EXPECTED_INPUTS["cy006_inventory"][1]
    ):
        raise ResearchError("CY-006 registry semantics drift")
    actual["registry"] = sha256(REGISTRY)
    actual["runner"] = sha256(RUNNER)
    actual["spec"] = sha256(SPEC)
    actual["manifest"] = sha256(MANIFEST)
    actual["registry_suggestion"] = sha256(REGISTRY_SUGGESTION)
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


def loo_median_sql(value: str, count: str, values: str) -> str:
    """Exact leave-one-out median from a sorted one-based DuckDB list."""

    return f"""
      CASE
        WHEN {count}%2=0 AND {value}<=list_extract({values},floor({count}/2)::BIGINT)
          THEN list_extract({values},floor({count}/2)::BIGINT+1)
        WHEN {count}%2=0
          THEN list_extract({values},floor({count}/2)::BIGINT)
        WHEN {value}<list_extract({values},floor({count}/2)::BIGINT+1)
          THEN (list_extract({values},floor({count}/2)::BIGINT+1)
                +list_extract({values},floor({count}/2)::BIGINT+2))/2.0
        WHEN {value}>list_extract({values},floor({count}/2)::BIGINT+1)
          THEN (list_extract({values},floor({count}/2)::BIGINT)
                +list_extract({values},floor({count}/2)::BIGINT+1))/2.0
        ELSE (list_extract({values},floor({count}/2)::BIGINT)
              +list_extract({values},floor({count}/2)::BIGINT+2))/2.0
      END
    """


def build_histories(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    paths = ",".join(f"'{path.as_posix()}'" for path in PARTITIONS)
    source = connection.execute(
        f"""
        SELECT count(*),count(*)-count(DISTINCT (trade_date,symbol)),
          count(*) FILTER (WHERE hard_valid AND available_at>decision_at),
          min(trade_date),max(trade_date)
        FROM read_parquet([{paths}],union_by_name=true)
        WHERE trade_date BETWEEN DATE '{SOURCE_START.date()}' AND DATE '{MAX_ROW_DATE.date()}'
        """
    ).fetchone()
    audit: dict[str, Any] = {
        "source_rows": int(source[0]),
        "duplicate_source_keys": int(source[1]),
        "hard_valid_time_travel_rows": int(source[2]),
        "source_first_date": str(pd.Timestamp(source[3]).date()),
        "source_last_date": str(pd.Timestamp(source[4]).date()),
        "maximum_source_row_date": str(MAX_ROW_DATE.date()),
    }
    if (
        audit["duplicate_source_keys"]
        or audit["hard_valid_time_travel_rows"]
        or pd.Timestamp(source[4]) > MAX_ROW_DATE
    ):
        raise ResearchError(f"V36 source audit failed: {audit}")

    connection.execute(
        f"""
        CREATE TEMP TABLE market_calendar AS
        SELECT trade_date,row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
        FROM (
          SELECT DISTINCT trade_date FROM cy006
          WHERE trade_date BETWEEN DATE '{SOURCE_START.date()}' AND DATE '{MAX_ROW_DATE.date()}'
        )
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE market_weeks AS
        SELECT week_start,week_first_date,week_last_date,first_cal_idx,last_cal_idx,
          market_sessions,row_number() OVER (ORDER BY week_start)-1 AS week_idx,
          week_start+INTERVAL 6 DAY AS week_complete_date
        FROM (
          SELECT CAST(date_trunc('week',trade_date) AS DATE) AS week_start,
            min(trade_date) AS week_first_date,max(trade_date) AS week_last_date,
            min(cal_idx) AS first_cal_idx,max(cal_idx) AS last_cal_idx,
            count(*) AS market_sessions
          FROM market_calendar GROUP BY 1
        )
        """
    )

    snapshot_gate = " AND ".join(
        f"d.{name} IS NOT NULL AND trim(CAST(d.{name} AS VARCHAR))<>''"
        for name in (
            "snapshot_id",
            "daily_snapshot_id",
            "trading_state_snapshot_id",
            "industry_snapshot_id",
            "float_snapshot_id",
            "corporate_action_snapshot_id",
            "market_snapshot_id",
        )
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE base_daily AS
        SELECT d.trade_date,c.cal_idx,w.week_start,w.week_idx,w.market_sessions,
          w.first_cal_idx AS week_first_cal_idx,w.last_cal_idx AS week_last_cal_idx,
          d.symbol,ln(d.close/d.preclose) AS stock_log_return,
          d.amount,d.turnover_fraction,
          CASE WHEN d.trade_status=1 AND d.current_day_data_tradable
                    AND d.amount>0 THEN 1.0 ELSE 0.0 END AS traded_indicator
        FROM cy006 d JOIN market_calendar c USING(trade_date)
        JOIN market_weeks w
          ON w.week_start=CAST(date_trunc('week',d.trade_date) AS DATE)
        WHERE d.trade_date BETWEEN DATE '{SOURCE_START.date()}' AND DATE '{MAX_ROW_DATE.date()}'
          AND (
            regexp_matches(d.symbol,'^(600|601|603|605)[0-9]{{3}}[.]SH$')
            OR regexp_matches(d.symbol,'^(000|001|002|300|301)[0-9]{{3}}[.]SZ$')
          )
          AND coalesce(d.hard_valid AND d.bar_valid AND d.trading_state_valid
            AND d.corporate_action_valid AND NOT d.corporate_action_blocking
            AND d.market_valid AND d.market_rule_valid AND d.historical_identity_valid
            AND d.available_at<=d.decision_at
            AND d.open>0 AND d.high>0 AND d.low>0 AND d.close>0 AND d.preclose>0
            AND d.high>=d.open AND d.high>=d.close
            AND d.low<=d.open AND d.low<=d.close
            AND d.amount>=0 AND d.turnover_fraction>=0
            AND isfinite(d.open) AND isfinite(d.high) AND isfinite(d.low)
            AND isfinite(d.close) AND isfinite(d.preclose)
            AND isfinite(d.amount) AND isfinite(d.turnover_fraction)
            AND isfinite(ln(d.close/d.preclose)),false)
          AND {snapshot_gate}
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE daily_groups AS
        SELECT trade_date,count(*) AS member_count,
          list_sort(list(stock_log_return)) AS sorted_returns
        FROM base_daily GROUP BY trade_date
        HAVING count(*)>=501
        """
    )
    daily_loo = loo_median_sql(
        "b.stock_log_return", "g.member_count", "g.sorted_returns"
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE daily_context AS
        SELECT b.*,{daily_loo} AS loo_market_daily_return
        FROM base_daily b JOIN daily_groups g USING(trade_date)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE weekly_stock AS
        SELECT symbol,week_start,week_idx,market_sessions,
          min(cal_idx) AS observed_first_cal_idx,max(cal_idx) AS observed_last_cal_idx,
          count(*) AS observed_sessions,sum(stock_log_return) AS stock_week_return,
          avg(traded_indicator) AS weekly_trading_continuity
        FROM daily_context
        GROUP BY symbol,week_start,week_idx,market_sessions
        HAVING count(*)=market_sessions
          AND min(cal_idx)=min(week_first_cal_idx)
          AND max(cal_idx)=max(week_last_cal_idx)
          AND isfinite(sum(stock_log_return))
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE weekly_groups AS
        SELECT week_idx,count(*) AS member_count,
          list_sort(list(stock_week_return)) AS sorted_returns
        FROM weekly_stock GROUP BY week_idx
        HAVING count(*)>=501
        """
    )
    weekly_loo = loo_median_sql(
        "w.stock_week_return", "g.member_count", "g.sorted_returns"
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE weekly_context AS
        SELECT w.*,{weekly_loo} AS loo_market_week_return,
          g.member_count-1 AS other_market_peers
        FROM weekly_stock w JOIN weekly_groups g USING(week_idx)
        """
    )

    connection.execute(
        """
        CREATE TEMP TABLE month_ends AS
        SELECT trade_date,cal_idx FROM (
          SELECT trade_date,cal_idx,
            lead(date_trunc('month',trade_date)) OVER (ORDER BY cal_idx) AS next_month
          FROM market_calendar
        ) WHERE next_month IS NULL OR next_month>date_trunc('month',trade_date)
        """
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE signal_universe AS
        SELECT d.trade_date AS signal_date,c.cal_idx AS signal_cal_idx,d.symbol,
          d.industry AS causal_industry,d.decision_at,d.available_at,d.amount,
          d.turnover_fraction,d.close,d.preclose,d.circulating_shares,
          ln(d.close*d.circulating_shares) AS log_circulating_market_value,
          d.snapshot_id,d.daily_snapshot_id,d.trading_state_snapshot_id,
          d.industry_snapshot_id,d.float_snapshot_id,
          d.corporate_action_snapshot_id,d.market_snapshot_id
        FROM cy006 d JOIN month_ends m ON m.trade_date=d.trade_date
        JOIN market_calendar c ON c.trade_date=d.trade_date AND c.cal_idx=m.cal_idx
        WHERE d.trade_date BETWEEN DATE '{SIGNAL_START.date()}' AND DATE '{SIGNAL_END.date()}'
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
            AND d.industry IS NOT NULL AND trim(CAST(d.industry AS VARCHAR))<>''
            AND d.open>0 AND d.high>0 AND d.low>0 AND d.close>0 AND d.preclose>0
            AND d.high>=d.open AND d.high>=d.close
            AND d.low<=d.open AND d.low<=d.close
            AND d.amount>0 AND d.turnover_fraction>0 AND d.circulating_shares>0
            AND isfinite(d.open) AND isfinite(d.high) AND isfinite(d.low)
            AND isfinite(d.close) AND isfinite(d.preclose) AND isfinite(d.amount)
            AND isfinite(d.turnover_fraction) AND isfinite(d.circulating_shares)
            AND isfinite(ln(d.close/d.preclose))
            AND isfinite(ln(d.close*d.circulating_shares)),false)
          AND {snapshot_gate}
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE signal_amounts AS
        SELECT signal_date,median(amount) AS same_date_median_amount,
          count(*) AS same_date_eligible_n
        FROM signal_universe GROUP BY signal_date
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE signal_rankable AS
        SELECT s.*,a.same_date_median_amount,a.same_date_eligible_n
        FROM signal_universe s JOIN signal_amounts a USING(signal_date)
        WHERE s.amount>=a.same_date_median_amount
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE signal_anchor_weeks AS
        SELECT s.signal_date,s.signal_cal_idx,s.symbol,max(w.week_idx) AS anchor_week_idx
        FROM signal_rankable s JOIN market_weeks w
          ON w.week_complete_date<s.signal_date
        GROUP BY s.signal_date,s.signal_cal_idx,s.symbol
        """
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE exact_history_keys AS
        SELECT a.signal_date,a.signal_cal_idx,a.symbol,a.anchor_week_idx,
          count(*) AS history_week_count,count(DISTINCT h.week_idx) AS distinct_week_count,
          min(h.week_idx) AS first_week_idx,max(h.week_idx) AS last_week_idx,
          min(h.other_market_peers) AS minimum_other_market_peers
        FROM signal_anchor_weeks a JOIN weekly_context h ON h.symbol=a.symbol
          AND h.week_idx BETWEEN a.anchor_week_idx-{HISTORY_WEEKS - 1} AND a.anchor_week_idx
        GROUP BY a.signal_date,a.signal_cal_idx,a.symbol,a.anchor_week_idx
        HAVING count(*)={HISTORY_WEEKS}
          AND count(DISTINCT h.week_idx)={HISTORY_WEEKS}
          AND min(h.week_idx)=a.anchor_week_idx-{HISTORY_WEEKS - 1}
          AND max(h.week_idx)=a.anchor_week_idx
          AND min(h.other_market_peers)>={MIN_OTHER_MARKET_PEERS}
        """
    )

    connection.execute(
        """
        CREATE TEMP TABLE daily_controls AS
        SELECT s.signal_date,s.signal_cal_idx,s.symbol,
          count(*) AS control_sessions,min(h.cal_idx) AS control_first_cal_idx,
          max(h.cal_idx) AS control_last_cal_idx,
          avg(h.turnover_fraction) AS mean_turnover_60,
          avg(h.traded_indicator) AS trading_continuity_60,
          sum(h.stock_log_return) AS raw_log_return_60,
          stddev_pop(h.stock_log_return-h.loo_market_daily_return) AS idio_volatility_60
        FROM signal_rankable s JOIN daily_context h ON h.symbol=s.symbol
          AND h.cal_idx BETWEEN s.signal_cal_idx-59 AND s.signal_cal_idx
        GROUP BY s.signal_date,s.signal_cal_idx,s.symbol
        HAVING count(*)=60 AND min(h.cal_idx)=s.signal_cal_idx-59
          AND max(h.cal_idx)=s.signal_cal_idx
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE annual_amihud AS
        SELECT symbol,year(trade_date) AS formation_year,
          count(*) FILTER (WHERE traded_indicator=1 AND amount>0) AS valid_observations,
          avg(abs(stock_log_return)/amount) FILTER (
            WHERE traded_indicator=1 AND amount>0
          ) AS annual_amihud
        FROM base_daily GROUP BY symbol,year(trade_date)
        HAVING count(*) FILTER (WHERE traded_indicator=1 AND amount>0)>=200
        """
    )

    key_audit = connection.execute(
        """
        SELECT (SELECT count(*) FROM signal_universe),
          (SELECT count(*) FROM signal_rankable),
          (SELECT count(*) FROM signal_anchor_weeks),
          (SELECT count(*) FROM exact_history_keys),
          (SELECT count(*) FROM daily_controls),
          (SELECT count(*) FROM weekly_stock),
          (SELECT count(*) FROM weekly_context),
          (SELECT min(signal_date) FROM signal_universe),
          (SELECT max(signal_date) FROM signal_universe)
        """
    ).fetchone()
    audit.update(
        {
            "signal_universe_rows": int(key_audit[0]),
            "amount_eligible_signal_rows": int(key_audit[1]),
            "signal_anchor_rows": int(key_audit[2]),
            "exact_56_week_history_rows": int(key_audit[3]),
            "exact_60_session_control_rows": int(key_audit[4]),
            "weekly_stock_rows": int(key_audit[5]),
            "weekly_context_rows": int(key_audit[6]),
            "first_signal_date": str(pd.Timestamp(key_audit[7]).date()),
            "last_signal_date": str(pd.Timestamp(key_audit[8]).date()),
        }
    )

    history_lists = connection.execute(
        """
        SELECT k.signal_date,k.signal_cal_idx,k.symbol,k.anchor_week_idx,
          list(h.stock_week_return ORDER BY h.week_idx) AS stock_week_returns,
          list(h.loo_market_week_return ORDER BY h.week_idx) AS market_week_returns,
          avg(h.weekly_trading_continuity) AS history_weekly_continuity,
          min(h.other_market_peers) AS minimum_other_market_peers
        FROM exact_history_keys k JOIN weekly_context h ON h.symbol=k.symbol
          AND h.week_idx BETWEEN k.anchor_week_idx-55 AND k.anchor_week_idx
        GROUP BY k.signal_date,k.signal_cal_idx,k.symbol,k.anchor_week_idx
        ORDER BY k.signal_date,k.symbol
        """
    ).fetch_df()
    metadata = connection.execute(
        """
        SELECT s.*,k.anchor_week_idx,k.history_week_count,k.distinct_week_count,
          k.first_week_idx,k.last_week_idx,k.minimum_other_market_peers,
          c.control_sessions,c.control_first_cal_idx,c.control_last_cal_idx,
          c.mean_turnover_60,c.trading_continuity_60,c.raw_log_return_60,
          c.idio_volatility_60,a.valid_observations AS annual_amihud_observations,
          a.annual_amihud
        FROM signal_rankable s JOIN exact_history_keys k
          USING(signal_date,signal_cal_idx,symbol)
        JOIN daily_controls c USING(signal_date,signal_cal_idx,symbol)
        LEFT JOIN annual_amihud a ON a.symbol=s.symbol
          AND a.formation_year=year(s.signal_date)-1
        ORDER BY s.signal_date,s.causal_industry,s.symbol
        """
    ).fetch_df()
    if history_lists.empty or metadata.empty:
        raise ResearchError(f"V36 exact history construction is empty: {audit}")
    histories = metadata.merge(
        history_lists,
        on=["signal_date", "signal_cal_idx", "symbol", "anchor_week_idx"],
        how="inner",
        validate="one_to_one",
        suffixes=("", "_list"),
    )
    audit["history_rows_after_control_join"] = len(histories)
    audit["history_merge_loss"] = len(metadata) - len(histories)
    if audit["history_merge_loss"]:
        raise ResearchError(f"V36 history metadata/list merge failed: {audit}")
    return histories, audit


def compute_one_delay(stock: object, market: object) -> tuple[float, float, float, str]:
    try:
        stock_values = np.asarray(stock, dtype=float)
        market_values = np.asarray(market, dtype=float)
    except (TypeError, ValueError):
        return math.nan, math.nan, math.nan, "NONNUMERIC_HISTORY"
    if stock_values.shape != (HISTORY_WEEKS,) or market_values.shape != (HISTORY_WEEKS,):
        return math.nan, math.nan, math.nan, "BAD_HISTORY_LENGTH"
    if not np.isfinite(stock_values).all() or not np.isfinite(market_values).all():
        return math.nan, math.nan, math.nan, "NONFINITE_HISTORY"

    response = stock_values[LAG_COUNT:]
    current_market = market_values[LAG_COUNT:]
    restricted = np.column_stack((np.ones(RESPONSE_WEEKS), current_market))
    unrestricted = np.column_stack(
        (
            np.ones(RESPONSE_WEEKS),
            current_market,
            market_values[3:-1],
            market_values[2:-2],
            market_values[1:-3],
            market_values[:-4],
        )
    )
    if float(np.sum(np.square(response - response.mean()))) <= 0.0:
        return math.nan, math.nan, math.nan, "DEGENERATE_RESPONSE"
    beta_r, _, rank_r, _ = np.linalg.lstsq(restricted, response, rcond=None)
    beta_u, _, rank_u, _ = np.linalg.lstsq(unrestricted, response, rcond=None)
    if rank_r != restricted.shape[1] or rank_u != unrestricted.shape[1]:
        return math.nan, math.nan, math.nan, "RANK_DEFICIENT_DESIGN"
    sst = float(np.sum(np.square(response - response.mean())))
    r2_r = 1.0 - float(np.sum(np.square(response - restricted @ beta_r))) / sst
    r2_u = 1.0 - float(np.sum(np.square(response - unrestricted @ beta_u))) / sst
    if not np.isfinite([r2_r, r2_u]).all() or r2_u <= 0.0:
        return math.nan, r2_r, r2_u, "NONPOSITIVE_UNRESTRICTED_R2"
    if r2_u + NUMERIC_TOLERANCE < r2_r:
        return math.nan, r2_r, r2_u, "NESTED_R2_VIOLATION"
    delay = 1.0 - r2_r / r2_u
    if not math.isfinite(delay) or delay < 0.0 or delay > 1.0:
        return math.nan, r2_r, r2_u, "DELAY_OUTSIDE_UNIT_INTERVAL"
    return float(delay), float(r2_r), float(r2_u), "VALID"


def make_representation(
    histories: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = [
        compute_one_delay(stock, market)
        for stock, market in zip(
            histories.pop("stock_week_returns"),
            histories.pop("market_week_returns"),
            strict=True,
        )
    ]
    metrics = pd.DataFrame(
        rows,
        columns=["price_delay_52w_4l", "restricted_r2", "unrestricted_r2", "delay_status"],
    )
    representation = pd.concat(
        [histories.reset_index(drop=True), metrics.reset_index(drop=True)], axis=1
    )
    status_counts = {
        str(key): int(value) for key, value in representation.delay_status.value_counts().items()
    }
    representation = representation.loc[representation.delay_status.eq("VALID")].copy()
    representation["industry_representation_count"] = representation.groupby(
        ["signal_date", "causal_industry"]
    )["symbol"].transform("size")
    representation = representation.loc[
        representation.industry_representation_count.ge(MIN_INDUSTRY_REPRESENTATIONS)
    ].copy()
    representation = representation.sort_values(
        ["signal_date", "causal_industry", "symbol"], kind="mergesort"
    ).reset_index(drop=True)
    audit = {
        "regression_input_rows": len(histories),
        "delay_status_counts": status_counts,
        "valid_delay_rows_before_industry_support": int(status_counts.get("VALID", 0)),
        "supported_representation_rows": len(representation),
        "supported_decision_dates": int(representation.signal_date.nunique()),
        "supported_industries": int(representation.causal_industry.nunique()),
    }
    return representation, audit


def spearman(left: pd.Series, right: pd.Series) -> float | None:
    frame = pd.DataFrame(
        {
            "left": pd.to_numeric(left, errors="coerce"),
            "right": pd.to_numeric(right, errors="coerce"),
        }
    ).dropna()
    frame = frame.loc[np.isfinite(frame.left) & np.isfinite(frame.right)]
    if len(frame) < 3 or frame.left.nunique() < 2 or frame.right.nunique() < 2:
        return None
    value = frame.left.rank(method="average").corr(frame.right.rank(method="average"))
    return None if pd.isna(value) else float(value)


def redundancy_diagnostics(representation: pd.DataFrame) -> tuple[dict[str, Any], bool]:
    result: dict[str, Any] = {}
    passed = True
    for control in CONTROL_COLUMNS:
        per_date: list[dict[str, Any]] = []
        for signal_date, part in representation.groupby("signal_date", sort=True):
            valid = part[["price_delay_52w_4l", control]].dropna()
            rho = (
                spearman(valid.price_delay_52w_4l, valid[control])
                if len(valid) >= MIN_DATE_CONTROL_ROWS
                else None
            )
            if rho is not None:
                per_date.append(
                    {
                        "signal_date": str(pd.Timestamp(signal_date).date()),
                        "n": len(valid),
                        "rho": rho,
                    }
                )
        within: list[dict[str, Any]] = []
        for (signal_date, industry), part in representation.groupby(
            ["signal_date", "causal_industry"], sort=True
        ):
            valid = part[["price_delay_52w_4l", control]].dropna()
            rho = (
                spearman(valid.price_delay_52w_4l, valid[control])
                if len(valid) >= MIN_INDUSTRY_CONTROL_ROWS
                else None
            )
            if rho is not None:
                within.append(
                    {
                        "signal_date": str(pd.Timestamp(signal_date).date()),
                        "industry": str(industry),
                        "n": len(valid),
                        "rho": rho,
                    }
                )
        date_median = None if not per_date else float(np.median([item["rho"] for item in per_date]))
        industry_median = (
            None if not within else float(np.median([item["rho"] for item in within]))
        )
        supported_dates = len(per_date)
        within_dates = len({item["signal_date"] for item in within})
        control_pass = bool(
            supported_dates >= MIN_CONTROL_DATES
            and within_dates >= MIN_CONTROL_DATES
            and date_median is not None
            and industry_median is not None
            and abs(date_median) < REDUNDANCY_LIMIT
            and abs(industry_median) < REDUNDANCY_LIMIT
        )
        passed &= control_pass
        result[control] = {
            "same_date_supported_dates": supported_dates,
            "same_date_median_spearman": date_median,
            "within_industry_supported_groups": len(within),
            "within_industry_supported_dates": within_dates,
            "within_industry_median_spearman": industry_median,
            "gate_passed": control_pass,
        }
    return result, passed


def select_candidates(
    representation: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    ranked = representation.sort_values(
        ["signal_date", "causal_industry", "price_delay_52w_4l", "amount", "symbol"],
        ascending=[True, True, False, False, True],
        kind="mergesort",
    ).copy()
    ranked["selection_rank"] = ranked.groupby(
        ["signal_date", "causal_industry"], sort=False
    ).cumcount() + 1
    winners = ranked.loc[ranked.selection_rank.eq(1)].copy()
    winners["event_id"] = (
        "BROAD_MARKET_PRICE_DELAY|"
        + winners.signal_date.dt.strftime("%Y%m%d")
        + "|"
        + winners.causal_industry.astype(str)
        + "|"
        + winners.symbol.astype(str)
    )
    winners = winners.sort_values(
        ["signal_cal_idx", "causal_industry", "symbol", "event_id"], kind="mergesort"
    )
    retained: list[bool] = []
    last_index: dict[str, int] = {}
    for row in winners.itertuples(index=False):
        previous = last_index.get(str(row.symbol))
        keep = previous is None or int(row.signal_cal_idx) - previous > COOLDOWN_SESSIONS
        retained.append(keep)
        if keep:
            last_index[str(row.symbol)] = int(row.signal_cal_idx)
    winners["retained_after_60_session_cooldown"] = retained
    candidates = winners.loc[winners.retained_after_60_session_cooldown].drop(
        columns=["retained_after_60_session_cooldown"]
    )
    candidates = candidates.sort_values(
        ["signal_date", "causal_industry", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)

    exact = ranked.loc[ranked.selection_rank.eq(1), [
        "signal_date",
        "causal_industry",
        "symbol",
        "price_delay_52w_4l",
    ]].sort_values(["signal_date", "causal_industry"], kind="mergesort")
    observed = winners[[
        "signal_date",
        "causal_industry",
        "symbol",
        "price_delay_52w_4l",
    ]].sort_values(["signal_date", "causal_industry"], kind="mergesort")
    if not exact.reset_index(drop=True).equals(observed.reset_index(drop=True)):
        raise ResearchError("V36 deterministic max-delay selection drift")
    for _, group in candidates.groupby("symbol", sort=False):
        gaps = np.diff(group.sort_values("signal_cal_idx").signal_cal_idx.to_numpy(dtype=int))
        if len(gaps) and int(gaps.min()) <= COOLDOWN_SESSIONS:
            raise ResearchError("V36 cooldown drift")
    audit = {
        "pre_cooldown_winners": len(winners),
        "retained_candidates": len(candidates),
        "cooldown_rejections": int((~winners.retained_after_60_session_cooldown).sum()),
        "duplicate_date_industry_winners": int(
            winners.duplicated(["signal_date", "causal_industry"]).sum()
        ),
        "duplicate_event_ids": int(candidates.event_id.duplicated().sum()),
        "exact_max_delay_selection_verified": True,
    }
    return candidates, audit


def opportunity_and_semantic_audit(
    representation: pd.DataFrame,
    candidates: pd.DataFrame,
    source_audit: dict[str, Any],
) -> tuple[dict[str, Any], bool, bool]:
    semantic = {
        "representation_duplicate_symbol_dates": int(
            representation.duplicated(["signal_date", "symbol"]).sum()
        ),
        "candidate_duplicate_event_ids": int(candidates.event_id.duplicated().sum()),
        "pre_signal_rows": int(representation.signal_date.lt(SIGNAL_START).sum()),
        "post_2020_signal_rows": int(representation.signal_date.gt(SIGNAL_END).sum()),
        "predictor_after_decision_rows": int(
            representation.available_at.gt(representation.decision_at).sum()
        ),
        "amount_floor_failures": int(
            representation.amount.lt(representation.same_date_median_amount).sum()
        ),
        "industry_support_failures": int(
            representation.industry_representation_count.lt(
                MIN_INDUSTRY_REPRESENTATIONS
            ).sum()
        ),
        "nonfinite_delay_rows": int(
            (~np.isfinite(representation.price_delay_52w_4l)).sum()
        ),
        "delay_outside_unit_interval_rows": int(
            (
                representation.price_delay_52w_4l.lt(0)
                | representation.price_delay_52w_4l.gt(1)
            ).sum()
        ),
        "history_count_failures": int(representation.history_week_count.ne(56).sum()),
        "history_contiguity_failures": int(
            (
                representation.distinct_week_count.ne(56)
                | representation.first_week_idx.ne(representation.anchor_week_idx - 55)
                | representation.last_week_idx.ne(representation.anchor_week_idx)
            ).sum()
        ),
        "market_peer_failures": int(
            representation.minimum_other_market_peers.lt(MIN_OTHER_MARKET_PEERS).sum()
        ),
        "source_duplicate_keys": int(source_audit["duplicate_source_keys"]),
        "source_time_travel_rows": int(source_audit["hard_valid_time_travel_rows"]),
        "history_merge_loss": int(source_audit["history_merge_loss"]),
    }
    semantic_pass = all(value == 0 for value in semantic.values())
    annual: dict[str, Any] = {}
    opportunity_pass = True
    for year in YEARS:
        part = candidates.loc[candidates.signal_date.dt.year.eq(year)]
        count = len(part)
        industries = int(part.causal_industry.nunique())
        months = int(part.signal_date.dt.to_period("M").nunique())
        symbols = int(part.symbol.nunique())
        passed = bool(
            count > MIN_ANNUAL_CANDIDATES_EXCLUSIVE
            and industries >= MIN_ANNUAL_INDUSTRIES
            and months >= MIN_DECISION_MONTHS[year]
            and symbols > MIN_ANNUAL_SYMBOLS_EXCLUSIVE
        )
        opportunity_pass &= passed
        annual[str(year)] = {
            "retained_candidates": count,
            "pit_industries": industries,
            "decision_months": months,
            "unique_symbols": symbols,
            "candidate_count_gt_50": count > 50,
            "industry_count_ge_20": industries >= 20,
            "decision_month_gate_passed": months >= MIN_DECISION_MONTHS[year],
            "unique_symbols_gt_50": symbols > 50,
            "annual_opportunity_gate_passed": passed,
        }
    return {"semantic_checks": semantic, "annual": annual}, semantic_pass, opportunity_pass


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    connection = duckdb.connect()
    try:
        connection.register("frame", frame)
        connection.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    finally:
        connection.close()


def atomic_publish_no_replace(staging: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        raise ResearchError(f"canonical V36 Stage-A target already exists: {target}")
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(staging)
    target_bytes = os.fsencode(target)
    if sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        result = libc.renamex_np(source_bytes, target_bytes, 0x00000004)
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        result = libc.renameat2(-100, source_bytes, -100, target_bytes, 1)
    else:
        raise ResearchError("platform lacks audited atomic no-replace rename")
    if result != 0:
        error = ctypes.get_errno()
        if error in (errno.EEXIST, errno.ENOTEMPTY):
            raise ResearchError(f"canonical V36 Stage-A target appeared: {target}")
        raise OSError(error, os.strerror(error), str(target))


def run_stage_a() -> dict[str, Any]:
    public = verify_public_contract()
    verify_registry_install(public)
    source_hashes = verify_source_inputs()
    if STAGE_A.exists() or STAGE_A.is_symlink():
        raise ResearchError(f"canonical V36 Stage A already exists: {STAGE_A}")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".stage_a_staging_", dir=OUTPUT_ROOT))
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = connect(staging / "duckdb_tmp")
        histories, source_audit = build_histories(connection)
        connection.close()
        connection = None
        representation, regression_audit = make_representation(histories)
        if representation.empty:
            raise ResearchError("no supported valid V36 representations")
        redundancy, redundancy_pass = redundancy_diagnostics(representation)
        candidates, selection_audit = select_candidates(representation)
        gate_audit, semantic_pass, opportunity_pass = opportunity_and_semantic_audit(
            representation, candidates, source_audit
        )
        stage_a_pass = bool(semantic_pass and opportunity_pass and redundancy_pass)
        result: dict[str, Any] = {
            "experiment": EXPERIMENT,
            "stage": "OUTCOME_BLIND_REPRESENTATION_OPPORTUNITY_AND_REDUNDANCY",
            "status": (
                "PASSED_OUTCOME_BLIND_STAGE_A_STAGE_B_NOT_AUTHORIZED"
                if stage_a_pass
                else "FAILED_OUTCOME_BLIND_GATE_PERMANENTLY_CLOSED"
            ),
            "asset_id": ASSET_ID,
            "authorization_id": AUTHORIZATION_ID,
            "authorized_arm": AUTHORIZED_ARM,
            "source_hashes": source_hashes,
            "source_audit": source_audit,
            "regression_audit": regression_audit,
            "selection_audit": selection_audit,
            "gate_audit": gate_audit,
            "redundancy_diagnostics": redundancy,
            "semantic_gate_passed": semantic_pass,
            "opportunity_gate_passed": opportunity_pass,
            "redundancy_gate_passed": redundancy_pass,
            "stage_a_gate_passed": stage_a_pass,
            "representation_rows": len(representation),
            "candidate_rows": len(candidates),
            "candidate_annual_counts": {
                str(year): int(candidates.signal_date.dt.year.eq(year).sum()) for year in YEARS
            },
            "first_candidate_date": (
                None if candidates.empty else str(candidates.signal_date.min().date())
            ),
            "last_candidate_date": (
                None if candidates.empty else str(candidates.signal_date.max().date())
            ),
            "candidate_symbols": int(candidates.symbol.nunique()),
            "candidate_industries": int(candidates.causal_industry.nunique()),
            "outcome_columns_read": False,
            "post_signal_rows_read": False,
            "post_2020_rows_read": False,
            "2021_plus_rows_read": False,
            "charts_rendered": False,
            "stage_b_authorized": False,
            "portfolio_replay_performed": False,
            "governance_incident_used": False,
            "next_action": (
                "INDEPENDENTLY_AUDIT_STAGE_A; FREEZE_SEPARATE_STAGE_B_BEFORE_OUTCOMES"
                if stage_a_pass
                else "CLOSE_EXACT_V36_WITHOUT_ALTERNATE_LAGS_WINDOWS_SIGN_OR_THRESHOLDS"
            ),
        }
        if stage_a_pass:
            representation_path = staging / "representation_panel.parquet"
            candidates_path = staging / "candidates_frozen.parquet"
            write_parquet(representation, representation_path)
            write_parquet(candidates, candidates_path)
            result["representation_sha256"] = sha256(representation_path)
            result["candidates_sha256"] = sha256(candidates_path)
        (staging / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(staging / "duckdb_tmp", ignore_errors=True)
        second_public = verify_public_contract()
        verify_registry_install(second_public)
        if second_public["hashes"] != public["hashes"]:
            raise ResearchError("V36 public contract changed during run")
        if verify_source_inputs() != source_hashes:
            raise ResearchError("V36 source inputs changed during run")
        atomic_publish_no_replace(staging, STAGE_A)
        return result
    except Exception:
        if connection is not None:
            connection.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--verify-public-contract",
        action="store_true",
        help="verify repository declarations only; never state, stat, hash or open source inputs",
    )
    mode.add_argument(
        "--run",
        action="store_true",
        help="run once only after exact CY-054 central registry installation",
    )
    args = parser.parse_args()
    if args.verify_public_contract:
        public = verify_public_contract()
        print(
            json.dumps(
                {
                    "status": "PUBLIC_CONTRACT_VALID_SOURCE_UNTOUCHED",
                    "asset_id": ASSET_ID,
                    **public["hashes"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    print(json.dumps(run_stage_a(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
