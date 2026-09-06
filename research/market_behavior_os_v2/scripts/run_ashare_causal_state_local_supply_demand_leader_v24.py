#!/usr/bin/env python3
"""Run the frozen V24 causal route and one-per-industry structural selection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb


EXPERIMENT = "ASHARE-CAUSAL-STATE-LOCAL-SUPPLY-DEMAND-LEADER-V24"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
ROOT = Path("/Volumes/quant/CY_quant_research")
V22 = ROOT / "ashare_causal_local_industry_demand_state_mother_v22"
CANDIDATES = V22 / "stage_a/candidates_frozen.parquet"
OUTCOMES = V22 / "stage_b/outcomes.parquet"
FEATURES = ROOT / "ashare_causal_demand_expansion_low_inventory_recovery_v23/causal_features.parquet"
MARKET = ROOT / "ashare_causal_market_regime_routed_simple_strategy_v1/stage_a/causal_market_regime_2014_2023.parquet"
OUTPUT_ROOT = ROOT / "ashare_causal_state_local_supply_demand_leader_v24"
SELECTED = OUTPUT_ROOT / "selected_outcomes.parquet"
RESULT = OUTPUT_ROOT / "result.json"
REPORT = OUTPUT_ROOT / "REPORT.md"
EXPECTED = {
    SPEC: "ffe45035924d87eb37cd3f39714d7b6c45919ee494fbd1d5fd8a3c5a4c9bcad7",
    CANDIDATES: "58dcf3aaa232bc15e364dfb16806a944521eb782b62e7dc26d9e9068165c9e1e",
    OUTCOMES: "e86f96fdc18f3d5f6db57ed35a52165f5bbd499101dc8af80c0ea73ba0650fbe",
    FEATURES: "a66bfdd9e84fc5101cb1693e8c4e649b9ae729c07a0bdeb923b6f55ef6ec5fd9",
    MARKET: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, timing, route, or result drift."""


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
            raise ResearchError(f"input drift: {path}: {actual[str(path)]} != {expected}")
    return actual


def connection() -> duckdb.DuckDBPyConnection:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_ROOT / "duckdb_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='8GB'")
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    return con


def build(con: duckdb.DuckDBPyConnection) -> None:
    query = f"""
    WITH routed AS (
      SELECT f.*,m.market_regime,m.latest_source_timestamp,
        CASE WHEN f.previous5_downside_turnover>0
          THEN f.last5_downside_turnover/f.previous5_downside_turnover END
          AS selling_decay_ratio
      FROM read_parquet('{FEATURES.as_posix()}') f
      JOIN read_parquet('{MARKET.as_posix()}') m
        ON m.trade_date=f.signal_date
      WHERE (m.market_regime='BULL'
             AND f.mechanism='LOCAL_BULL_DISTRIBUTED_ACCUMULATION_ESCAPE')
         OR (m.market_regime='BEAR'
             AND f.mechanism='LOCAL_BEAR_SLOW_SUPPLY_EXHAUSTION_TAKEOVER')
    ), ranked AS (
      SELECT *,row_number() OVER (
        PARTITION BY signal_date,causal_industry,mechanism
        ORDER BY
          CASE WHEN mechanism LIKE 'LOCAL_BULL%' AND exact_prior126_valid THEN 0
               WHEN mechanism LIKE 'LOCAL_BULL%' THEN 1 ELSE 0 END,
          CASE WHEN mechanism LIKE 'LOCAL_BULL%'
               THEN target_corridor_touch_sessions END ASC NULLS LAST,
          CASE WHEN mechanism LIKE 'LOCAL_BULL%'
               THEN exact_prior20_return END ASC NULLS LAST,
          CASE WHEN mechanism LIKE 'LOCAL_BEAR%'
               THEN selling_decay_ratio END ASC NULLS LAST,
          CASE WHEN mechanism LIKE 'LOCAL_BEAR%'
               THEN recovery_fraction END DESC NULLS LAST,
          event_id
      ) AS structural_rank,
      count(*) OVER (
        PARTITION BY signal_date,causal_industry,mechanism
      ) AS industry_date_candidates
      FROM routed
    )
    SELECT r.*,o.status,o.entry_date,o.entry_cal_idx,o.entry_price,
      o.exit_date,o.exit_cal_idx,o.exit_price,o.exit_reason,o.holding_sessions,
      o.gross_return,o.net_return
    FROM ranked r
    LEFT JOIN read_parquet('{OUTCOMES.as_posix()}') o USING(event_id)
    WHERE structural_rank=1
    ORDER BY signal_date,mechanism,causal_industry,event_id
    """
    con.execute(
        f"COPY ({query}) TO '{SELECTED.as_posix()}' "
        "(FORMAT PARQUET, COMPRESSION ZSTD)"
    )


def query_dicts(con: duckdb.DuckDBPyConnection, query: str) -> list[dict[str, Any]]:
    result = con.execute(query)
    columns = [item[0] for item in result.description]
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def summarize(con: duckdb.DuckDBPyConnection, inputs: dict[str, str]) -> dict[str, Any]:
    audit = query_dicts(
        con,
        f"""
        SELECT count(*) AS selected_rows,
          count(*)-count(DISTINCT event_id) AS duplicates,
          count(*) FILTER (WHERE signal_date>DATE '2020-12-31') AS post_2020_signals,
          count(*) FILTER (WHERE available_at>decision_at
             OR latest_source_timestamp>decision_at) AS timing_failures,
          count(*) FILTER (WHERE structural_rank!=1) AS rank_failures,
          count(*) FILTER (
            WHERE (market_regime='BULL' AND mechanism NOT LIKE 'LOCAL_BULL%')
               OR (market_regime='BEAR' AND mechanism NOT LIKE 'LOCAL_BEAR%')
               OR market_regime='TRANSITION'
          ) AS route_failures,
          sum(industry_date_candidates-1) AS same_industry_candidates_removed,
          max(signal_date) AS maximum_signal_date,
          max(exit_date) AS maximum_outcome_date
        FROM read_parquet('{SELECTED.as_posix()}')
        """,
    )[0]
    for key in ("duplicates", "post_2020_signals", "timing_failures", "rank_failures", "route_failures"):
        if int(audit[key]) != 0:
            raise ResearchError(f"selection audit failed: {audit}")
    pooled = query_dicts(
        con,
        f"""
        SELECT count(*) AS selected_events,
          count(*) FILTER (WHERE status='COMPLETED') AS completed_events,
          avg(net_return) FILTER (WHERE status='COMPLETED') AS mean_net_return,
          median(net_return) FILTER (WHERE status='COMPLETED') AS median_net_return,
          avg((net_return>0)::INT) FILTER (WHERE status='COMPLETED') AS positive_rate,
          avg((net_return<=-0.10)::INT) FILTER (WHERE status='COMPLETED') AS severe_loss_rate
        FROM read_parquet('{SELECTED.as_posix()}')
        """,
    )[0]
    annual = query_dicts(
        con,
        f"""
        SELECT year(signal_date) AS year,count(*) AS selected_events,
          count(*) FILTER (WHERE status='COMPLETED') AS completed_events,
          avg(net_return) FILTER (WHERE status='COMPLETED') AS mean_net_return,
          median(net_return) FILTER (WHERE status='COMPLETED') AS median_net_return,
          avg((net_return<=-0.10)::INT) FILTER (WHERE status='COMPLETED') AS severe_loss_rate
        FROM read_parquet('{SELECTED.as_posix()}') GROUP BY year ORDER BY year
        """,
    )
    sleeves = query_dicts(
        con,
        f"""
        SELECT mechanism,count(*) AS selected_events,
          count(*) FILTER (WHERE status='COMPLETED') AS completed_events,
          avg(net_return) FILTER (WHERE status='COMPLETED') AS mean_net_return,
          median(net_return) FILTER (WHERE status='COMPLETED') AS median_net_return
        FROM read_parquet('{SELECTED.as_posix()}') GROUP BY mechanism ORDER BY mechanism
        """,
    )
    by_year = {int(item["year"]): item for item in annual}
    gate = all(
        year in by_year
        and int(by_year[year]["completed_events"]) > 50
        and float(by_year[year]["mean_net_return"]) > 0.04
        for year in range(2014, 2021)
    )
    return {
        "experiment": EXPERIMENT,
        "research_status": "POST_CHART_DEVELOPMENT_EVALUATION",
        "spec_sha256": sha256(SPEC),
        "input_sha256": inputs,
        "selected_sha256": sha256(SELECTED),
        "audit": audit,
        "pooled": pooled,
        "annual": annual,
        "sleeves": sleeves,
        "development_gate_pass": gate,
        "validation_2022_2024_read": False,
        "decision": (
            "OPEN_ONE_FROZEN_2022_2024_VALIDATION"
            if gate
            else "DEVELOPMENT_GATE_FAIL_DO_NOT_OPEN_2022_2024"
        ),
    }


def ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [ready(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def write_report(result: dict[str, Any]) -> None:
    lines = [
        f"# {EXPERIMENT}", "", "## Decision", "", f"`{result['decision']}`", "",
        "This is the second frozen post-chart Development compression. V23 remains closed; "
        "V24 tests causal global routing plus one structural representative per PIT industry/date.",
        "", "## Pooled", "",
        f"`{json.dumps(ready(result['pooled']), ensure_ascii=False, sort_keys=True)}`",
        "", "## Annual", "",
        "| Year | Completed | Mean net | Median net | Severe loss |",
        "|---:|---:|---:|---:|---:|",
    ]
    for item in result["annual"]:
        lines.append(
            f"| {item['year']} | {item['completed_events']} | {item['mean_net_return']:.4%} | "
            f"{item['median_net_return']:.4%} | {item['severe_loss_rate']:.4%} |"
        )
    lines.extend(["", "## Sleeves", "", f"`{json.dumps(ready(result['sleeves']), ensure_ascii=False, sort_keys=True)}`", ""])
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    inputs = verify_inputs()
    con = connection()
    build(con)
    result = summarize(con, inputs)
    con.close()
    RESULT.write_text(json.dumps(ready(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_report(result)
    print(json.dumps(ready(result), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
