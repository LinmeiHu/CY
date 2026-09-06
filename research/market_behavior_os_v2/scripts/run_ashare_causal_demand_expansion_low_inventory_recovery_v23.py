#!/usr/bin/env python3
"""Evaluate the frozen V23 post-chart causal structure on 2014-2020 only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb


EXPERIMENT = "ASHARE-CAUSAL-DEMAND-EXPANSION-LOW-INVENTORY-RECOVERY-V23"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
V22_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_local_industry_demand_state_mother_v22"
)
CANDIDATES = V22_ROOT / "stage_a/candidates_frozen.parquet"
OUTCOMES = V22_ROOT / "stage_b/outcomes.parquet"
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_demand_expansion_low_inventory_recovery_v23"
)
FEATURES = OUTPUT_ROOT / "causal_features.parquet"
SELECTED = OUTPUT_ROOT / "selected_outcomes.parquet"
RESULT = OUTPUT_ROOT / "result.json"
REPORT = OUTPUT_ROOT / "REPORT.md"
EXPECTED = {
    SPEC: "cf3969887fdb1e45b52ac346fdd9219050e404171a76c382c3a03a0b725cbd8c",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    CANDIDATES: "58dcf3aaa232bc15e364dfb16806a944521eb782b62e7dc26d9e9068165c9e1e",
    OUTCOMES: "e86f96fdc18f3d5f6db57ed35a52165f5bbd499101dc8af80c0ea73ba0650fbe",
}


class ResearchError(RuntimeError):
    """Fail closed on identity, PIT timing, history, or governance drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual[str(path)] = sha256(path)
        if actual[str(path)] != expected:
            raise ResearchError(
                f"frozen input drift: {path}: {actual[str(path)]} != {expected}"
            )
    return actual


def connection() -> duckdb.DuckDBPyConnection:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ROOT / "duckdb_tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='10GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    return con


def build_features(con: duckdb.DuckDBPyConnection) -> None:
    query = f"""
    WITH eligible_daily AS (
      SELECT *
      FROM read_parquet('{DAILY.as_posix()}')
      WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2020-12-31'
        AND hard_valid AND current_valid AND current_day_data_tradable
        AND market_rule_valid AND corporate_action_valid
        AND NOT corporate_action_blocking AND coalesce(corporate_action_count,0)=0
        AND historical_identity_valid AND industry_valid
        AND causal_industry IS NOT NULL AND industry_snapshot_id IS NOT NULL
        AND NOT is_st AND ret20 IS NOT NULL AND available_at<=decision_at
    ), market_now AS (
      SELECT trade_date,cal_idx,count(*) AS market_n,
        avg((ret20>0)::INT) AS market_breadth20,
        max(available_at) AS market_latest_source_timestamp
      FROM eligible_daily GROUP BY trade_date,cal_idx
    ), market_state AS (
      SELECT *,lag(cal_idx,10) OVER (ORDER BY cal_idx) AS market_lag10_cal_idx,
        lag(market_n,10) OVER (ORDER BY cal_idx) AS market_lag10_n,
        lag(market_breadth20,10) OVER (ORDER BY cal_idx) AS market_breadth20_lag10
      FROM market_now
    ), industry_now AS (
      SELECT trade_date,cal_idx,causal_industry,count(*) AS industry_n_check,
        avg((ret20>0)::INT) AS industry_breadth20_check,
        max(available_at) AS industry_latest_source_timestamp_check
      FROM eligible_daily GROUP BY trade_date,cal_idx,causal_industry
    ), industry_state AS (
      SELECT *,lag(cal_idx,10) OVER (
          PARTITION BY causal_industry ORDER BY cal_idx
        ) AS industry_lag10_cal_idx,
        lag(industry_n_check,10) OVER (
          PARTITION BY causal_industry ORDER BY cal_idx
        ) AS industry_lag10_n,
        lag(industry_breadth20_check,10) OVER (
          PARTITION BY causal_industry ORDER BY cal_idx
        ) AS industry_breadth20_lag10
      FROM industry_now
    ), stock_history AS (
      SELECT c.event_id,
        count(*) FILTER (
          WHERE d.cal_idx BETWEEN c.signal_cal_idx-126 AND c.signal_cal_idx-1
        ) AS prior126_rows,
        min(d.cal_idx) FILTER (
          WHERE d.cal_idx BETWEEN c.signal_cal_idx-126 AND c.signal_cal_idx-1
        ) AS prior126_min_cal_idx,
        max(d.cal_idx) FILTER (
          WHERE d.cal_idx BETWEEN c.signal_cal_idx-126 AND c.signal_cal_idx-1
        ) AS prior126_max_cal_idx,
        count(*) FILTER (
          WHERE d.cal_idx BETWEEN c.signal_cal_idx-126 AND c.signal_cal_idx-1
            AND d.coord_high>=c.coord_close
            AND d.coord_low<=c.coord_close*1.15
        ) AS target_corridor_touch_sessions,
        count(*) FILTER (
          WHERE d.cal_idx BETWEEN c.signal_cal_idx-20 AND c.signal_cal_idx-1
        ) AS prior20_rows_check,
        max(d.coord_high) FILTER (
          WHERE d.cal_idx BETWEEN c.signal_cal_idx-20 AND c.signal_cal_idx-1
        ) AS decline_reference,
        min(d.coord_low) FILTER (
          WHERE d.cal_idx BETWEEN c.signal_cal_idx-20 AND c.signal_cal_idx
        ) AS decline_trough,
        count(*) FILTER (
          WHERE d.cal_idx BETWEEN c.signal_cal_idx-126 AND c.signal_cal_idx
            AND d.invalid_step_cum=c.invalid_step_cum
            AND d.hard_valid AND d.current_valid AND d.market_rule_valid
            AND d.corporate_action_valid AND NOT d.corporate_action_blocking
            AND coalesce(d.corporate_action_count,0)=0
            AND d.available_at<=c.decision_at
        ) AS valid_lineage_rows_127,
        count(*) FILTER (
          WHERE d.cal_idx BETWEEN c.signal_cal_idx-126 AND c.signal_cal_idx
        ) AS observed_rows_127
      FROM read_parquet('{CANDIDATES.as_posix()}') c
      LEFT JOIN read_parquet('{DAILY.as_posix()}') d
        ON d.symbol=c.symbol
       AND d.cal_idx BETWEEN c.signal_cal_idx-126 AND c.signal_cal_idx
       AND d.trade_date<=c.signal_date
      GROUP BY c.event_id
    )
    SELECT c.*,m.market_n,m.market_breadth20,m.market_lag10_cal_idx,
      m.market_lag10_n,m.market_breadth20_lag10,
      m.market_latest_source_timestamp,i.industry_n_check,
      i.industry_breadth20_check,i.industry_lag10_cal_idx,
      i.industry_lag10_n,i.industry_breadth20_lag10,
      i.industry_latest_source_timestamp_check,h.* EXCLUDE(event_id),
      (h.prior126_rows=126
       AND h.prior126_min_cal_idx=c.signal_cal_idx-126
       AND h.prior126_max_cal_idx=c.signal_cal_idx-1
       AND h.valid_lineage_rows_127=h.observed_rows_127
       AND h.observed_rows_127=127) AS exact_prior126_valid,
      (h.prior20_rows_check=20
       AND h.valid_lineage_rows_127=h.observed_rows_127) AS exact_prior20_valid,
      CASE WHEN h.decline_reference>h.decline_trough
        THEN (c.coord_close-h.decline_trough)
             /(h.decline_reference-h.decline_trough) END AS recovery_fraction,
      (h.prior126_rows=126 AND h.target_corridor_touch_sessions<=10
       AND h.valid_lineage_rows_127=h.observed_rows_127
       AND h.observed_rows_127=127) AS low_inventory_passage,
      (m.market_n>=200 AND m.market_lag10_n>=200
       AND i.industry_n_check>=10 AND i.industry_lag10_n>=10
       AND m.market_lag10_cal_idx=c.signal_cal_idx-10
       AND i.industry_lag10_cal_idx=c.signal_cal_idx-10
       AND m.market_breadth20>=0.70 AND i.industry_breadth20_check>=0.70
       AND m.market_breadth20-m.market_breadth20_lag10>=0.10
       AND i.industry_breadth20_check-i.industry_breadth20_lag10>=0.10)
        AS renewed_demand,
      CASE
        WHEN c.mechanism='LOCAL_BULL_DISTRIBUTED_ACCUMULATION_ESCAPE'
          THEN low_inventory_passage OR renewed_demand
        WHEN c.mechanism='LOCAL_BEAR_SLOW_SUPPLY_EXHAUSTION_TAKEOVER'
          THEN exact_prior20_valid AND recovery_fraction>=1.0/3.0
        ELSE false
      END AS selected
    FROM read_parquet('{CANDIDATES.as_posix()}') c
    LEFT JOIN market_state m
      ON m.trade_date=c.signal_date AND m.cal_idx=c.signal_cal_idx
    LEFT JOIN industry_state i
      ON i.trade_date=c.signal_date AND i.cal_idx=c.signal_cal_idx
     AND i.causal_industry=c.causal_industry
    LEFT JOIN stock_history h USING(event_id)
    ORDER BY c.signal_date,c.mechanism,c.symbol
    """
    con.execute(
        f"COPY ({query}) TO '{FEATURES.as_posix()}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )


def audit_features(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    row = con.execute(
        f"""
        SELECT count(*) AS rows,
          count(*)-count(DISTINCT event_id) AS duplicate_event_ids,
          count(*) FILTER (WHERE signal_date>DATE '2020-12-31') AS post_2020_signals,
          count(*) FILTER (WHERE available_at>decision_at) AS signal_timing_failures,
          count(*) FILTER (
            WHERE market_latest_source_timestamp>decision_at
               OR industry_latest_source_timestamp_check>decision_at
          ) AS state_timing_failures,
          count(*) FILTER (WHERE mechanism LIKE 'LOCAL_BULL%' AND NOT exact_prior126_valid)
            AS bull_invalid_history,
          count(*) FILTER (WHERE mechanism LIKE 'LOCAL_BEAR%' AND NOT exact_prior20_valid)
            AS bear_invalid_history,
          count(*) FILTER (WHERE selected AND mechanism NOT LIKE 'LOCAL_BULL%'
                                      AND mechanism NOT LIKE 'LOCAL_BEAR%')
            AS invalid_selected_mechanism
        FROM read_parquet('{FEATURES.as_posix()}')
        """
    ).fetchone()
    audit = {
        "rows": int(row[0]),
        "duplicate_event_ids": int(row[1]),
        "post_2020_signals": int(row[2]),
        "signal_timing_failures": int(row[3]),
        "state_timing_failures": int(row[4]),
        "bull_invalid_history": int(row[5]),
        "bear_invalid_history": int(row[6]),
        "invalid_selected_mechanism": int(row[7]),
    }
    if audit["rows"] != 4933 or any(
        audit[key]
        for key in (
            "duplicate_event_ids",
            "post_2020_signals",
            "signal_timing_failures",
            "state_timing_failures",
            "invalid_selected_mechanism",
        )
    ):
        raise ResearchError(f"feature audit failed: {audit}")
    return audit


def attach_outcomes(con: duckdb.DuckDBPyConnection) -> None:
    query = f"""
    SELECT f.*,o.status,o.entry_date,o.entry_cal_idx,o.entry_price,
      o.exit_date,o.exit_cal_idx,o.exit_price,o.exit_reason,o.holding_sessions,
      o.gross_return,o.net_return
    FROM read_parquet('{FEATURES.as_posix()}') f
    LEFT JOIN read_parquet('{OUTCOMES.as_posix()}') o USING(event_id)
    WHERE f.selected
    ORDER BY f.signal_date,f.mechanism,f.symbol
    """
    con.execute(
        f"COPY ({query}) TO '{SELECTED.as_posix()}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )


def rows_to_dicts(cursor: duckdb.DuckDBPyConnection, query: str) -> list[dict[str, Any]]:
    result = cursor.execute(query)
    columns = [item[0] for item in result.description]
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def summarize(con: duckdb.DuckDBPyConnection, audit: dict[str, int]) -> dict[str, Any]:
    pooled = rows_to_dicts(
        con,
        f"""
        SELECT count(*) AS selected_events,
          count(*) FILTER (WHERE status='COMPLETED') AS completed_events,
          avg(net_return) FILTER (WHERE status='COMPLETED') AS mean_net_return,
          median(net_return) FILTER (WHERE status='COMPLETED') AS median_net_return,
          avg((net_return>0)::INT) FILTER (WHERE status='COMPLETED')
            AS positive_rate,
          avg((net_return<=-0.10)::INT) FILTER (WHERE status='COMPLETED')
            AS severe_loss_rate,
          max(signal_date) AS maximum_signal_date,
          max(exit_date) AS maximum_outcome_date
        FROM read_parquet('{SELECTED.as_posix()}')
        """,
    )[0]
    annual = rows_to_dicts(
        con,
        f"""
        SELECT year(signal_date) AS year,count(*) AS selected_events,
          count(*) FILTER (WHERE status='COMPLETED') AS completed_events,
          avg(net_return) FILTER (WHERE status='COMPLETED') AS mean_net_return,
          median(net_return) FILTER (WHERE status='COMPLETED') AS median_net_return,
          avg((net_return<=-0.10)::INT) FILTER (WHERE status='COMPLETED')
            AS severe_loss_rate
        FROM read_parquet('{SELECTED.as_posix()}')
        GROUP BY year ORDER BY year
        """,
    )
    sleeves = rows_to_dicts(
        con,
        f"""
        SELECT mechanism,count(*) AS selected_events,
          count(*) FILTER (WHERE status='COMPLETED') AS completed_events,
          avg(net_return) FILTER (WHERE status='COMPLETED') AS mean_net_return,
          median(net_return) FILTER (WHERE status='COMPLETED') AS median_net_return,
          avg((net_return<=-0.10)::INT) FILTER (WHERE status='COMPLETED')
            AS severe_loss_rate
        FROM read_parquet('{SELECTED.as_posix()}')
        GROUP BY mechanism ORDER BY mechanism
        """,
    )
    branches = rows_to_dicts(
        con,
        f"""
        SELECT
          CASE
            WHEN mechanism LIKE 'LOCAL_BEAR%' THEN 'BEAR_RECOVERY'
            WHEN low_inventory_passage AND renewed_demand THEN 'BULL_BOTH'
            WHEN low_inventory_passage THEN 'BULL_LOW_INVENTORY'
            WHEN renewed_demand THEN 'BULL_RENEWED_DEMAND'
          END AS admission_branch,
          count(*) AS selected_events,
          count(*) FILTER (WHERE status='COMPLETED') AS completed_events,
          avg(net_return) FILTER (WHERE status='COMPLETED') AS mean_net_return
        FROM read_parquet('{SELECTED.as_posix()}')
        GROUP BY admission_branch ORDER BY admission_branch
        """,
    )
    annual_by_year = {int(item["year"]): item for item in annual}
    gate = all(
        year in annual_by_year
        and int(annual_by_year[year]["completed_events"]) > 50
        and float(annual_by_year[year]["mean_net_return"]) > 0.04
        for year in range(2014, 2021)
    )
    return {
        "experiment": EXPERIMENT,
        "research_status": "POST_CHART_DEVELOPMENT_EVALUATION",
        "spec_sha256": sha256(SPEC),
        "input_sha256": verify_inputs(),
        "output_sha256": {
            str(FEATURES): sha256(FEATURES),
            str(SELECTED): sha256(SELECTED),
        },
        "governance": {
            "post_2021_signal_or_rule_fit": False,
            "post_2021_outcome_read": False,
            "validation_2022_2024_read": False,
        },
        "audit": audit,
        "pooled": pooled,
        "annual": annual,
        "sleeves": sleeves,
        "admission_branches": branches,
        "development_gate_pass": gate,
        "decision": (
            "OPEN_ONE_FROZEN_2022_2024_VALIDATION"
            if gate
            else "DEVELOPMENT_GATE_FAIL_DO_NOT_OPEN_2022_2024"
        ),
    }


def serializable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): serializable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serializable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def write_report(result: dict[str, Any]) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Decision",
        "",
        f"`{result['decision']}`",
        "",
        "This is a post-chart Development evaluation, not independent confirmation. "
        "All 4,933 mother charts were reviewed before the four causal rules were frozen.",
        "",
        "## Pooled",
        "",
        f"`{json.dumps(serializable(result['pooled']), ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Annual gate",
        "",
        "| Year | Completed | Mean net | Median net | Severe loss |",
        "|---:|---:|---:|---:|---:|",
    ]
    for item in result["annual"]:
        lines.append(
            f"| {item['year']} | {item['completed_events']} | "
            f"{item['mean_net_return']:.4%} | {item['median_net_return']:.4%} | "
            f"{item['severe_loss_rate']:.4%} |"
        )
    lines.extend(
        [
            "",
            "## Mechanisms",
            "",
            f"`{json.dumps(serializable(result['sleeves']), ensure_ascii=False, sort_keys=True)}`",
            "",
            "## Admission branches",
            "",
            f"`{json.dumps(serializable(result['admission_branches']), ensure_ascii=False, sort_keys=True)}`",
            "",
            "## Governance",
            "",
            "No post-2021 outcome was read. The 2022-2024 validation remains closed unless "
            "every 2014-2020 calendar year exceeds both frozen gates.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    verify_inputs()
    con = connection()
    build_features(con)
    audit = audit_features(con)
    attach_outcomes(con)
    result = summarize(con, audit)
    con.close()
    RESULT.write_text(
        json.dumps(serializable(result), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    write_report(result)
    print(json.dumps(serializable(result), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
