#!/usr/bin/env python3
"""Freeze outcome-blind monthly within-industry circulating-size extremes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-INDUSTRY-NEUTRAL-CIRCULATING-SIZE-EXTREMES-MOTHER-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STYLE_DATA_SPEC = REPO / "research/market_behavior_os_v2/experiments/MKT-STYLE-DATA-001_spec.json"
STYLE_DATA_RESULT = REPO / "research/market_behavior_os_v2/artifacts/MKT-STYLE-DATA-001_result.json"
STYLE_PANEL = REPO / "research/market_behavior_os_v2/artifacts/MKT-STYLE-001_panel.csv"
CY006_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
CY006 = tuple(CY006_ROOT / f"partition_year={year}/data_0.parquet" for year in range(2018, 2021))
DAILY = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/pit_daily_compact_2013_2023.parquet")
REGIME = Path("/Volumes/quant/CY_quant_research/ashare_causal_market_regime_routed_simple_strategy_v1/stage_a/causal_market_regime_2014_2023.parquet")
OUTPUT_ROOT = Path("/Volumes/quant/CY_quant_research/ashare_industry_neutral_circulating_size_extremes_mother_v1")
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
EXPECTED_HASHES = {
    SPEC: "a221169d8ab7295283dfeafe34ec0cead9deb73c3232cfbbbaf74189dea2793d",
    STYLE_DATA_SPEC: "506c24bcdd498162b3d44faa3008aa54ddf9a4132606b5da9a890240e224484b",
    STYLE_DATA_RESULT: "a03954d6315f29c7c5a119b91729fbfeef84feb51c7c12ed2330b7822a19f019",
    STYLE_PANEL: "5ed526187d71cb0c719a98ba99fcba368ea6dc53b6ad097efbebb5bb1f2863ad",
    CY006[0]: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    CY006[1]: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    CY006[2]: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}
COOLDOWN = 60


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, PIT timing, or lineage drift."""


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
        raise ResearchError("circulating-size data contract no longer passes")
    if result.get("accepted_semantic_label") != "circulating_market_value_cny":
        raise ResearchError("circulating-size semantic label drift")
    return actual


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
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
            ["signal_cal_idx", "size_lane", "event_id"], kind="mergesort"
        ).itertuples():
            current = int(row.signal_cal_idx)
            if last_admitted is None or current - last_admitted > COOLDOWN:
                kept.append(int(row.Index))
                last_admitted = current
    return raw.loc[kept].sort_values(
        ["signal_date", "size_lane", "pit_industry", "symbol", "event_id"],
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
    con.execute(
        f"CREATE VIEW style_state AS SELECT * FROM read_csv_auto('{STYLE_PANEL.as_posix()}', header=true)"
    )
    raw = con.execute(
        f"""
        WITH market_calendar AS (
          SELECT DISTINCT trade_date,cal_idx
          FROM read_parquet('{DAILY.as_posix()}')
          WHERE trade_date BETWEEN DATE '2018-01-01' AND DATE '2020-12-31'
        ), first_fridays AS (
          SELECT trade_date,cal_idx FROM (
            SELECT trade_date,cal_idx,
              row_number() OVER (
                PARTITION BY year(trade_date),month(trade_date)
                ORDER BY trade_date
              ) AS friday_number
            FROM market_calendar WHERE dayofweek(trade_date)=5
          ) WHERE friday_number=1
        ), coordinate_history AS (
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
        ), eligible AS (
          SELECT s.trade_date,d.cal_idx,s.symbol,d.sleeve,s.industry AS pit_industry,
            s.industry_snapshot_id,s.float_snapshot_id,s.snapshot_id,
            s.decision_at,s.available_at,s.float_effective_date,s.float_announced_date,
            s.float_available_date,s.circulating_shares,s.close AS raw_close,
            s.close*s.circulating_shares AS circulating_market_value_cny,
            s.amount,s.volume,s.turnover_fraction,
            d.causal_industry,d.industry_snapshot_id AS coordinate_industry_snapshot_id,
            d.invalid_step_cum,d.coordinate_factor,d.coord_open,d.coord_high,d.coord_low,
            d.coord_close,d.open,d.high,d.low,d.close,d.step_return,d.ret20,d.ret60,d.ret120,
            d.up_limit_price,d.down_limit_price,d.decision_at AS coordinate_decision_at,
            d.available_at AS coordinate_available_at,
            d.prior60_rows,d.lag60_cal_idx,d.prior60_invalid_min,
            d.prior60_invalid_max,d.prior60_valid
          FROM size_source s
          JOIN first_fridays f ON f.trade_date=s.trade_date
          JOIN coordinate_history d ON d.trade_date=s.trade_date AND d.symbol=s.symbol
          WHERE s.trade_date BETWEEN DATE '2018-01-01' AND DATE '2020-12-31'
            AND d.sleeve IN ('MAIN','CHINEXT') AND NOT s.is_st AND NOT d.is_st
            AND s.hard_valid AND s.bar_valid AND s.float_valid
            AND s.corporate_action_valid AND s.market_rule_valid
            AND s.historical_identity_valid AND s.industry_valid
            AND s.current_day_data_tradable AND s.trade_status=1
            AND NOT s.corporate_action_blocking AND coalesce(s.corporate_action_count,0)=0
            AND s.available_at<=s.decision_at
            AND s.float_effective_date<=s.trade_date
            AND s.float_announced_date<=s.trade_date
            AND s.float_available_date<=s.trade_date
            AND s.close>0 AND s.circulating_shares>0 AND s.volume>0 AND s.amount>0
            AND s.industry IS NOT NULL AND s.industry_snapshot_id IS NOT NULL
            AND d.hard_valid AND d.current_valid AND d.current_day_data_tradable
            AND d.market_rule_valid AND d.corporate_action_valid
            AND NOT d.corporate_action_blocking AND d.historical_identity_valid
            AND d.available_at<=d.decision_at AND d.coord_close>0
            AND d.prior60_rows=60 AND d.lag60_cal_idx=d.cal_idx-60
            AND d.prior60_invalid_min=d.invalid_step_cum
            AND d.prior60_invalid_max=d.invalid_step_cum AND d.prior60_valid
        ), ranked AS (
          SELECT *,count(*) OVER (PARTITION BY trade_date,pit_industry) AS industry_n,
            row_number() OVER (
              PARTITION BY trade_date,pit_industry
              ORDER BY circulating_market_value_cny,amount DESC,symbol
            ) AS small_rank,
            row_number() OVER (
              PARTITION BY trade_date,pit_industry
              ORDER BY circulating_market_value_cny DESC,amount DESC,symbol
            ) AS large_rank
          FROM eligible
        ), extremes AS (
          SELECT CASE WHEN small_rank=1 THEN 'SMALL_CIRCULATING_SIZE'
                      ELSE 'LARGE_CIRCULATING_SIZE' END AS size_lane,*
          FROM ranked
          WHERE industry_n>=10 AND (small_rank=1 OR large_rank=1)
        )
        SELECT concat(e.size_lane,'|',strftime(e.trade_date,'%Y%m%d'),'|',e.pit_industry,'|',e.symbol)
            AS event_id,
          e.*,r.market_regime,r.market_median_ret20,r.market_median_ret60,
          r.market_positive_ret20_share,r.market_positive_ret60_share,
          r.latest_source_timestamp AS market_latest_source_timestamp,
          st.size_positive_participation_small30_large30,
          st.size_leadership_transition5,
          st.size_winner_entropy_top10,
          st.size_positive_mass_max_share,
          st.available_at AS size_state_available_at
        FROM extremes e
        JOIN read_parquet('{REGIME.as_posix()}') r ON r.trade_date=e.trade_date
        LEFT JOIN style_state st ON cast(st.trade_date AS DATE)=e.trade_date
          AND st.market_view='ALL_A' AND st.denominator='NON_ST'
        ORDER BY e.symbol,e.cal_idx,e.size_lane,e.pit_industry
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
        "size_state_available_at",
        "float_effective_date",
        "float_announced_date",
        "float_available_date",
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
            "size_state_available_at",
        ]
    ].max(axis=1)
    audit_values = {
        "frozen_events": int(len(frame)),
        "raw_events_before_cooldown": raw_count,
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "post_2020_signal_count": int(frame.signal_date.dt.year.gt(2020).sum()),
        "predictor_after_decision_count": int(latest.gt(frame.decision_at).sum()),
        "history_failure_count": int(
            (
                frame.prior60_rows.ne(60)
                | frame.lag60_cal_idx.ne(frame.signal_cal_idx - 60)
                | frame.prior60_invalid_min.ne(frame.invalid_step_cum)
                | frame.prior60_invalid_max.ne(frame.invalid_step_cum)
                | ~frame.prior60_valid
            ).sum()
        ),
        "industry_minimum_failure_count": int(frame.industry_n.lt(10).sum()),
        "lane_failure_count": int(
            (~frame.size_lane.isin(["SMALL_CIRCULATING_SIZE", "LARGE_CIRCULATING_SIZE"])).sum()
        ),
        "nonpositive_size_count": int(frame.circulating_market_value_cny.le(0).sum()),
    }
    failures = [
        key
        for key, value in audit_values.items()
        if key.endswith("_count") and value != 0
    ]
    if failures:
        raise ResearchError(f"candidate audit failed: {audit_values}")
    for _, group in frame.groupby("symbol"):
        gaps = np.diff(group.sort_values("signal_cal_idx").signal_cal_idx.to_numpy())
        if len(gaps) and int(gaps.min()) <= COOLDOWN:
            raise ResearchError("causal cooldown drift")
    annual = {
        str(int(year)): {
            str(lane): int(value)
            for lane, value in part.groupby("size_lane").size().items()
        }
        for year, part in frame.groupby(frame.signal_date.dt.year)
    }
    return {
        **audit_values,
        "symbols": int(frame.symbol.nunique()),
        "signal_dates": int(frame.signal_date.nunique()),
        "pit_industries": int(frame.pit_industry.nunique()),
        "annual_lane_counts": annual,
        "minimum_circulating_market_value_cny": float(frame.circulating_market_value_cny.min()),
        "maximum_circulating_market_value_cny": float(frame.circulating_market_value_cny.max()),
        "maximum_signal_date": str(frame.signal_date.max().date()),
    }


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    frame, raw_count = build_candidates()
    payload = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_MOTHER_IDENTITY_FREEZE",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "candidate_sha256": sha256(CANDIDATES),
        "audit": audit(frame, raw_count),
        "return_or_exit_outcome_read": "NO",
        "2021_signal_identity_read": "NO",
        "2022_2024_signal_feature_or_outcome_read": "NO",
        "future_market_or_event_function": False,
        "next_step": "Attach fixed anatomy labels through 2021-06-30, render every event, and review all charts before rule compression.",
    }
    write_json(FREEZE, payload)
    payload["freeze_sha256"] = sha256(FREEZE)
    return payload


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
