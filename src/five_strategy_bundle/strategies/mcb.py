"""MCB V53 -> V64 -> V65 -> V72 signal chain.

The V53 producer was not present in any reachable CY source object.  Its
contract, spec, exact source-state hash and golden ledger uniquely determine
this reconstruction.

RECONSTRUCTED_FROM_FROZEN_SPEC
NOT_ORIGINAL_SOURCE
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from ..errors import ReproductionError
from ..io import _sql_path, write_parquet


def build_v53(daily: Path, market_industry_state: Path, output: Path) -> pd.DataFrame:
    """Rebuild the exact post-cooldown V53 candidate population."""
    con = duckdb.connect()
    con.execute("SET threads=4")
    query = f"""
    WITH d AS (
      SELECT *,
        max(coord_high) OVER w20 AS prior20_high,
        avg(turnover_fraction) OVER w20 AS prior20_turnover,
        sum(CASE WHEN round(close*100)=round(up_limit_price*100) THEN 1 ELSE 0 END)
          OVER w20 AS prior20_limitups,
        CASE WHEN coord_high>coord_low
          THEN (coord_close-coord_low)/(coord_high-coord_low) END AS close_location
      FROM read_parquet('{_sql_path(daily)}')
      WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
      WINDOW w20 AS (
        PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
      )
    ), state AS (
      SELECT *,
        lag(industry20,5) OVER (
          PARTITION BY causal_industry ORDER BY trade_date
        ) AS industry20_lag5,
        lag(industry_breadth20,5) OVER (
          PARTITION BY causal_industry ORDER BY trade_date
        ) AS industry_breadth20_lag5
      FROM read_parquet('{_sql_path(market_industry_state)}')
    ), featured AS (
      SELECT d.*,s.* EXCLUDE(trade_date,causal_industry),
        d.turnover_fraction/nullif(d.prior20_turnover,0) AS turnover_ratio,
        s.industry20-s.market20 AS industry_minus_market20,
        s.industry60-s.market60 AS industry_minus_market60,
        s.industry20-s.industry20_lag5 AS industry20_delta5,
        s.industry_breadth20-s.industry_breadth20_lag5 AS industry_breadth20_delta5,
        'V53-'||strftime(d.trade_date,'%Y%m%d')||'-'||d.symbol AS event_id,
        d.trade_date AS signal_date,
        d.decision_at AS feature_latest_timestamp
      FROM d JOIN state s USING(trade_date,causal_industry)
      WHERE d.trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
        AND d.hard_valid AND d.current_valid AND d.current_day_data_tradable
        AND d.market_rule_valid AND d.corporate_action_valid
        AND NOT d.corporate_action_blocking
        AND d.industry_valid AND d.historical_identity_valid
        AND d.industry_snapshot_id IS NOT NULL AND d.trade_status=1 AND NOT d.is_st
        AND d.available_at<=d.decision_at
        AND s.market20>-0.03 AND s.market_breadth20>0.40
        AND s.industry20>0.03 AND s.industry_breadth20>0.60
        AND s.industry20-s.industry20_lag5>=0.03
        AND s.industry_breadth20-s.industry_breadth20_lag5>=0.15
        AND d.ret60 BETWEEN 0.0 AND 0.30
        AND d.prior20_limitups=0
        AND d.coord_close>d.prior20_high
        AND d.step_return BETWEEN 0.02 AND 0.08
        AND d.close_location>=0.70
        AND d.turnover_fraction/nullif(d.prior20_turnover,0) BETWEEN 1.20 AND 4.00
    )
    SELECT * FROM featured
    ORDER BY signal_date,event_id
    """
    try:
        frame = con.execute(query).fetchdf()
    finally:
        con.close()
    accepted: list[int] = []
    for _, rows in frame.groupby("symbol", sort=False):
        last_cal_idx: int | None = None
        for index, cal_idx in zip(rows.index, rows.cal_idx, strict=True):
            current = int(cal_idx)
            if last_cal_idx is None or current - last_cal_idx > 20:
                accepted.append(int(index))
                last_cal_idx = current
    frame = frame.loc[accepted].sort_values(
        ["signal_date", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    _validate_v53(frame)
    write_parquet(frame, output)
    return frame


def build_v65(v53: pd.DataFrame, output: Path) -> pd.DataFrame:
    frame = _dates(v53)
    common = (
        frame.market_breadth20.ge(0.65)
        & frame.industry_breadth20_delta5.ge(0.25)
        & frame.ret60.le(0.15)
        & frame.step_return.le(0.06)
        & frame.turnover_ratio.ge(1.50)
    )
    medium_mask = common & frame.market_breadth60.ge(0.45)
    age = (frame.signal_date - pd.to_datetime(frame.prior250_peak_date)).dt.days
    early_mask = (
        common
        & frame.market_breadth60.lt(0.45)
        & frame.industry_breadth20_delta5.le(0.60)
        & age.ge(120)
        & frame.prior250_peak_invalid_cum.eq(frame.invalid_step_cum)
    )
    medium, early = frame.loc[medium_mask].copy(), frame.loc[early_mask].copy()
    medium["lane"], early["lane"] = "MEDIUM_PARTICIPATION", "EARLY_TRANSITION"
    selected = pd.concat([medium, early], ignore_index=True)
    selected["source_event_id"] = selected.event_id.astype(str)
    selected["event_id"] = "V65|" + selected.lane + "|" + selected.source_event_id
    selected["prior250_peak_age_calendar_days"] = (
        selected.signal_date - pd.to_datetime(selected.prior250_peak_date)
    ).dt.days
    selected["industry_positive_ret20_share"] = selected.industry_breadth20_delta5
    selected["stock_minus_industry_ret20"] = -selected.ret60
    selected["turnover_expansion"] = selected.turnover_ratio
    selected = selected.sort_values(["signal_date", "event_id"], kind="mergesort").reset_index(drop=True)
    if selected.event_id.duplicated().any() or selected.source_event_id.duplicated().any():
        raise ReproductionError("duplicate V65 identity")
    write_parquet(selected, output)
    return selected


def build_v64(v53: pd.DataFrame, output: Path) -> pd.DataFrame:
    frame = _dates(v53)
    mask = (
        frame.market_breadth20.ge(0.65)
        & frame.market_breadth60.ge(0.45)
        & frame.industry_breadth20_delta5.ge(0.25)
        & frame.ret60.le(0.15)
        & frame.step_return.le(0.06)
        & frame.turnover_ratio.ge(1.50)
    )
    selected = frame.loc[mask].copy()
    selected["source_event_id"] = selected.event_id.astype(str)
    selected["event_id"] = "V64|" + selected.source_event_id
    selected["admission_lane"] = "MEDIUM_PARTICIPATION_INDUSTRY_IGNITION"
    selected["industry_positive_ret20_share"] = selected.industry_breadth20_delta5
    selected["stock_minus_industry_ret20"] = -selected.ret60
    selected["turnover_expansion"] = selected.turnover_ratio
    selected = selected.sort_values(["signal_date", "event_id"], kind="mergesort").reset_index(drop=True)
    if selected.event_id.duplicated().any():
        raise ReproductionError("duplicate V64 identity")
    write_parquet(selected, output)
    return selected


def build_v72(v65: pd.DataFrame, output: Path) -> pd.DataFrame:
    frame = _dates(v65)
    keyed = frame.assign(signal_day=frame.signal_date.dt.normalize())
    state = keyed.groupby("signal_day", sort=True).agg(
        same_day_v65_signal_count=("event_id", "size"),
        same_day_v65_main_count=("sleeve", lambda values: int(values.eq("MAIN").sum())),
        same_day_v65_chinext_count=("sleeve", lambda values: int(values.eq("CHINEXT").sum())),
        same_day_v65_industry_count=("causal_industry", "nunique"),
        cross_board_state_known_at=("decision_at", "max"),
    )
    selected = keyed.merge(state, left_on="signal_day", right_index=True, validate="many_to_one")
    selected["cross_board_confirmation"] = selected.same_day_v65_main_count.gt(0) & selected.same_day_v65_chinext_count.gt(0)
    selected = selected.loc[selected.cross_board_confirmation].drop(columns="signal_day").copy()
    selected["v65_event_id"] = selected.event_id.astype(str)
    selected["v53_event_id"] = selected.source_event_id.astype(str)
    selected["source_event_id"] = selected.v65_event_id
    selected["event_id"] = "V72|" + selected.v65_event_id
    selected = selected.sort_values(["signal_date", "event_id"], kind="mergesort").reset_index(drop=True)
    if selected.event_id.duplicated().any() or selected.cross_board_state_known_at.gt(selected.decision_at).any():
        raise ReproductionError("V72 identity or completed-close chronology failure")
    write_parquet(selected, output)
    return selected


def _dates(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for column in ("trade_date", "signal_date", "prior250_peak_date", "available_at", "decision_at", "feature_latest_timestamp"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column])
    return frame


def _validate_v53(frame: pd.DataFrame) -> None:
    if frame.empty or frame.event_id.duplicated().any():
        raise ReproductionError("empty or duplicate V53 identity")
    if frame.available_at.gt(frame.decision_at).any() or frame.feature_latest_timestamp.gt(frame.decision_at).any():
        raise ReproductionError("V53 feature available after decision")
