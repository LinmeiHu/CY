#!/usr/bin/env python3
"""Freeze outcome-blind material circulating-supply expansion mother events."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


EXPERIMENT = "ASHARE-MATERIAL-CIRCULATING-SUPPLY-EXPANSION-MOTHER-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STYLE_DATA_RESULT = REPO / "research/market_behavior_os_v2/artifacts/MKT-STYLE-DATA-001_result.json"
CY006_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
CY006 = tuple(CY006_ROOT / f"partition_year={year}/data_0.parquet" for year in range(2018, 2021))
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
REGIME = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_routed_simple_strategy_v1/stage_a/"
    "causal_market_regime_2014_2023.parquet"
)
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_material_circulating_supply_expansion_mother_v1"
)
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
EXPECTED_HASHES = {
    SPEC: "f8f75519ccec8097e321081f94336421a0cbf09744b69942e0aa4e3a67f01556",
    STYLE_DATA_RESULT: "a03954d6315f29c7c5a119b91729fbfeef84feb51c7c12ed2330b7822a19f019",
    CY006[0]: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    CY006[1]: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    CY006[2]: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}
MINIMUM_SHARE_INCREASE = 0.5
COOLDOWN = 120


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, PIT timing, or coordinate lineage."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        value = sha256(path)
        actual[str(path)] = value
        if value != expected:
            raise ResearchError(f"input identity drift: {path}: {value} != {expected}")
    result = json.loads(STYLE_DATA_RESULT.read_text(encoding="utf-8"))
    if result.get("status") != "COMPLETE_DATA_CONTRACT_PASS":
        raise ResearchError("circulating-share data contract no longer passes")
    return actual


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def causal_cooldown(raw: pd.DataFrame) -> pd.DataFrame:
    kept: list[int] = []
    for _, group in raw.groupby("symbol", sort=False):
        last_admitted: int | None = None
        for row in group.sort_values(
            ["signal_cal_idx", "event_id"], kind="mergesort"
        ).itertuples():
            current = int(row.signal_cal_idx)
            if last_admitted is None or current - last_admitted > COOLDOWN:
                kept.append(int(row.Index))
                last_admitted = current
    return raw.loc[kept].sort_values(
        ["signal_date", "causal_industry", "symbol", "event_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def build_candidates() -> tuple[pd.DataFrame, int]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_ROOT / "duckdb_tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='12GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    con.from_parquet([str(path) for path in CY006], union_by_name=True).create_view("size_source")
    raw = con.execute(
        f"""
        WITH coordinate_history AS (
          SELECT d.*,
            count(*) OVER w60 AS prior60_rows,
            lag(cal_idx,60) OVER (PARTITION BY symbol ORDER BY cal_idx) AS lag60_cal_idx,
            min(invalid_step_cum) OVER w60 AS prior60_invalid_min,
            max(invalid_step_cum) OVER w60 AS prior60_invalid_max,
            bool_and(
              hard_valid AND current_valid AND current_day_data_tradable
              AND market_rule_valid AND corporate_action_valid
              AND NOT corporate_action_blocking AND historical_identity_valid
              AND available_at<=decision_at AND coord_close>0
            ) OVER w60 AS prior60_valid
          FROM read_parquet('{DAILY.as_posix()}') d
          WHERE trade_date BETWEEN DATE '2017-01-01' AND DATE '2020-12-31'
          WINDOW w60 AS (
            PARTITION BY symbol ORDER BY cal_idx
            ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
          )
        ), joined AS (
          SELECT s.trade_date,s.symbol,s.open,s.high,s.low,s.close,s.preclose,
            s.volume,s.amount,s.turnover_fraction,s.trade_status,s.is_st,
            s.industry,s.industry_snapshot_id,s.float_snapshot_id,s.snapshot_id,
            s.float_effective_date,s.float_announced_date,s.float_available_date,
            s.circulating_shares,s.float_source,s.share_multiplier,
            s.corporate_action_count,s.corporate_action_ids,
            s.corporate_action_blocking,s.decision_at,s.available_at,
            d.cal_idx,d.sleeve,d.causal_industry,
            d.industry_snapshot_id AS coordinate_industry_snapshot_id,
            d.invalid_step_cum,d.coordinate_factor,d.coord_open,d.coord_high,
            d.coord_low,d.coord_close,d.step_return,d.ret20,d.ret60,d.ret120,
            d.up_limit_price,d.down_limit_price,
            d.decision_at AS coordinate_decision_at,
            d.available_at AS coordinate_available_at,
            d.prior60_rows,d.lag60_cal_idx,d.prior60_invalid_min,
            d.prior60_invalid_max,d.prior60_valid,
            lag(s.trade_date) OVER w AS previous_trade_date,
            lag(d.cal_idx) OVER w AS previous_cal_idx,
            lag(s.circulating_shares) OVER w AS previous_circulating_shares,
            lag(s.float_effective_date) OVER w AS previous_float_effective_date,
            lag(s.float_available_date) OVER w AS previous_float_available_date,
            lag(s.available_at) OVER w AS previous_available_at,
            lag(s.decision_at) OVER w AS previous_decision_at,
            lag(s.float_valid) OVER w AS previous_float_valid,
            lag(s.hard_valid) OVER w AS previous_hard_valid,
            lag(d.invalid_step_cum) OVER w AS previous_invalid_step_cum,
            s.hard_valid AS source_hard_valid,s.bar_valid,s.float_valid,
            s.corporate_action_valid AS source_corporate_action_valid,
            s.market_rule_valid AS source_market_rule_valid,
            s.historical_identity_valid AS source_historical_identity_valid,
            s.current_day_data_tradable AS source_current_day_data_tradable,
            d.hard_valid AS coordinate_hard_valid,d.current_valid,
            d.current_day_data_tradable,d.market_rule_valid,
            d.corporate_action_valid,d.corporate_action_blocking AS coordinate_action_blocking,
            d.historical_identity_valid AS coordinate_identity_valid
          FROM size_source s
          JOIN coordinate_history d ON d.trade_date=s.trade_date AND d.symbol=s.symbol
          WINDOW w AS (PARTITION BY s.symbol ORDER BY s.trade_date)
        ), eligible AS (
          SELECT *,circulating_shares/previous_circulating_shares-1.0 AS circulating_share_increase
          FROM joined
          WHERE trade_date BETWEEN DATE '2018-01-01' AND DATE '2020-12-31'
            AND sleeve IN ('MAIN','CHINEXT') AND NOT is_st
            AND source_hard_valid AND bar_valid AND float_valid
            AND source_corporate_action_valid AND source_market_rule_valid
            AND source_historical_identity_valid AND source_current_day_data_tradable
            AND trade_status=1 AND NOT corporate_action_blocking
            AND coalesce(corporate_action_count,0)=0 AND share_multiplier=1.0
            AND available_at<=decision_at
            AND float_effective_date<=trade_date
            AND float_announced_date<=trade_date
            AND float_available_date<=trade_date
            AND previous_circulating_shares>0
            AND circulating_shares/previous_circulating_shares-1.0>=0.5
            AND previous_cal_idx=cal_idx-1
            AND previous_float_valid AND previous_hard_valid
            AND previous_available_at<=previous_decision_at
            AND previous_float_effective_date<=previous_trade_date
            AND previous_float_available_date<=previous_trade_date
            AND previous_invalid_step_cum=invalid_step_cum
            AND coordinate_hard_valid AND current_valid
            AND current_day_data_tradable AND market_rule_valid
            AND corporate_action_valid AND NOT coordinate_action_blocking
            AND coordinate_identity_valid
            AND coordinate_available_at<=coordinate_decision_at
            AND coord_open>0 AND coord_high>0 AND coord_low>0 AND coord_close>0
            AND prior60_rows=60 AND lag60_cal_idx=cal_idx-60
            AND prior60_invalid_min=invalid_step_cum
            AND prior60_invalid_max=invalid_step_cum AND prior60_valid
        )
        SELECT concat('MATERIAL_FLOAT_EXPANSION|',strftime(e.trade_date,'%Y%m%d'),'|',e.symbol)
            AS event_id,
          e.*,r.market_regime,r.market_median_ret20,r.market_median_ret60,
          r.market_positive_ret20_share,r.market_positive_ret60_share,
          r.latest_source_timestamp AS market_latest_source_timestamp
        FROM eligible e
        JOIN read_parquet('{REGIME.as_posix()}') r ON r.trade_date=e.trade_date
        ORDER BY e.symbol,e.cal_idx
        """
    ).fetch_df()
    con.close()
    for column in (
        "trade_date",
        "decision_at",
        "available_at",
        "coordinate_decision_at",
        "coordinate_available_at",
        "market_latest_source_timestamp",
        "float_effective_date",
        "float_announced_date",
        "float_available_date",
        "previous_trade_date",
        "previous_float_effective_date",
        "previous_float_available_date",
        "previous_available_at",
        "previous_decision_at",
    ):
        raw[column] = pd.to_datetime(raw[column])
        if raw[column].dt.tz is not None:
            raw[column] = raw[column].dt.tz_localize(None)
    raw = raw.rename(columns={"trade_date": "signal_date", "cal_idx": "signal_cal_idx"})
    frozen = causal_cooldown(raw)
    write_parquet(frozen, CANDIDATES)
    return frozen, int(len(raw))


def audit(frame: pd.DataFrame, raw_count: int) -> dict[str, Any]:
    latest = frame[
        [
            "available_at",
            "coordinate_available_at",
            "market_latest_source_timestamp",
        ]
    ].max(axis=1)
    return {
        "raw_events_before_cooldown": raw_count,
        "frozen_events": int(len(frame)),
        "symbols": int(frame.symbol.nunique()),
        "signal_dates": int(frame.signal_date.nunique()),
        "pit_industries": int(frame.causal_industry.nunique()),
        "annual_counts": {
            str(key): int(value)
            for key, value in frame.signal_date.dt.year.value_counts().sort_index().items()
        },
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "post_2020_signal_count": int(frame.signal_date.dt.year.gt(2020).sum()),
        "predictor_after_decision_count": int(latest.gt(frame.decision_at).sum()),
        "minimum_share_increase_failure_count": int(
            frame.circulating_share_increase.lt(MINIMUM_SHARE_INCREASE).sum()
        ),
        "same_day_action_failure_count": int(
            (
                frame.corporate_action_count.ne(0)
                | frame.share_multiplier.ne(1.0)
                | frame.corporate_action_blocking
                | frame.coordinate_action_blocking
            ).sum()
        ),
        "nonconsecutive_prior_session_count": int(
            frame.previous_cal_idx.ne(frame.signal_cal_idx - 1).sum()
        ),
        "coordinate_lineage_change_count": int(
            frame.previous_invalid_step_cum.ne(frame.invalid_step_cum).sum()
        ),
        "history_failure_count": int(
            (
                frame.prior60_rows.ne(60)
                | frame.lag60_cal_idx.ne(frame.signal_cal_idx - 60)
                | frame.prior60_invalid_min.ne(frame.invalid_step_cum)
                | frame.prior60_invalid_max.ne(frame.invalid_step_cum)
                | ~frame.prior60_valid
            ).sum()
        ),
        "circulating_share_increase_minimum": float(frame.circulating_share_increase.min()),
        "circulating_share_increase_median": float(frame.circulating_share_increase.median()),
        "circulating_share_increase_maximum": float(frame.circulating_share_increase.max()),
        "validation_2022_2024_outcome_read": False,
        "outcome_columns_attached": False,
    }


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    frame, raw_count = build_candidates()
    result = audit(frame, raw_count)
    fatal_keys = (
        "duplicate_event_count",
        "post_2020_signal_count",
        "predictor_after_decision_count",
        "minimum_share_increase_failure_count",
        "same_day_action_failure_count",
        "nonconsecutive_prior_session_count",
        "coordinate_lineage_change_count",
        "history_failure_count",
    )
    if any(result[key] for key in fatal_keys):
        raise ResearchError(f"outcome-blind candidate audit failed: {result}")
    annual = result["annual_counts"]
    breadth_pass = all(int(annual.get(str(year), 0)) > 50 for year in (2018, 2019, 2020))
    manifest = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_MOTHER_FREEZE",
        "source_hashes": source_hashes,
        "script_sha256": sha256(Path(__file__)),
        "candidate_path": str(CANDIDATES),
        "candidate_sha256": sha256(CANDIDATES),
        "audit": result,
        "annual_mother_breadth_gate_pass": bool(breadth_pass),
        "next_action": (
            "BUILD_FIXED_ANATOMY_AND_COMPLETE_CHART_CORPUS"
            if breadth_pass
            else "CLOSE_MOTHER_FOR_INSUFFICIENT_ANNUAL_BREADTH"
        ),
        "post_2021_signal_identity_read": False,
        "validation_2022_2024_outcome_read": False,
    }
    write_json(FREEZE, manifest)
    return manifest


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
