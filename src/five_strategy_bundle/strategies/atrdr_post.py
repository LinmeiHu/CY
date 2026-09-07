"""Registered-input V27 ATRDR producers for the post-2023 intervals."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from ..errors import ReproductionError
from ..io import _sql_path, write_parquet
from .atrdr import EXCLUDED_MARKET_INDUSTRIES, _quoted

V27_STANDARD_COLUMNS = [
    "event_id", "symbol", "sleeve", "signal_date", "entry_date", "entry_cal_idx",
    "entry_price", "exit_date", "exit_cal_idx", "exit_price", "exit_reason",
    "holding_sessions", "gross_return", "net_return", "lane", "rank1", "rank2", "rank3",
]


def _daily(daily: Path) -> pd.DataFrame:
    frame = duckdb.sql(
        f"SELECT * FROM read_parquet('{_sql_path(daily)}') ORDER BY symbol,cal_idx"
    ).df()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def build_fast_bear(
    daily: Path,
    market: pd.DataFrame,
    output: Path,
    *,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Exact V17 OAI roll-forward followed by the frozen V27 worsening route."""
    excluded = _quoted(EXCLUDED_MARKET_INDUSTRIES)
    query = f"""
    WITH source AS (
      SELECT * FROM read_parquet('{_sql_path(daily)}')
      WHERE trade_date BETWEEN DATE '2022-01-04' AND DATE '{end}'
        AND sleeve IN ('MAIN','CHINEXT')
        AND causal_industry NOT IN ({excluded})
    ), windows AS (
      SELECT *,lag(coord_close,20) OVER w AS lag20_close_x,
        lag(cal_idx,20) OVER w AS lag20_idx_x,
        lag(invalid_step_cum,20) OVER w AS lag20_invalid_x,
        lag(coord_close,10) OVER w AS lag10_close_x,
        max(coord_high) OVER w5 AS prior5_high_x,
        max(coord_high) OVER w10 AS prior10_high,
        avg(turnover_fraction) OVER w20 AS avg_to20_x,
        count(*) OVER w20 AS prior20_n_x,
        bool_and(history_valid) OVER w20 AS prior20_valid_x
      FROM source
      WINDOW w AS(PARTITION BY symbol ORDER BY trade_date),
        w5 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
        w10 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING),
        w20 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
    ), featured AS (
      SELECT *,coord_close/nullif(lag20_close_x,0)-1 AS ret20_x,
        coord_close/nullif(prior_coord_close,0)-1 AS step_return_x,
        (coord_close-coord_low)/nullif(coord_high-coord_low,0) AS close_location_x,
        turnover_fraction/nullif(avg_to20_x,0) AS turnover_ratio_x,
        prior_coord_close/nullif(lag10_close_x,0)-1 AS prior10_return_x
      FROM windows
    ), industry AS (
      SELECT trade_date,causal_industry,
        median(ret20_x) FILTER(WHERE current_valid AND NOT is_st AND ret20_x IS NOT NULL)
          AS industry_median_ret20
      FROM featured GROUP BY trade_date,causal_industry
    )
    SELECT f.*,f.ret20_x-i.industry_median_ret20 AS stock_minus_industry_ret20,
      f.coord_close/nullif(f.prior10_high,0)-1 AS close_vs_prior10_high
    FROM featured f JOIN industry i USING(trade_date,causal_industry)
    WHERE f.trade_date>=DATE '2023-01-01'
      AND f.hard_valid AND f.history_valid AND f.current_valid
      AND f.current_day_data_tradable AND f.market_rule_valid
      AND f.corporate_action_valid AND NOT f.corporate_action_blocking AND NOT f.is_st
      AND f.prior20_n_x=20 AND f.prior20_valid_x
      AND f.cal_idx-f.lag20_idx_x=20 AND f.invalid_step_cum=f.lag20_invalid_x
      AND f.ret20_x<=-0.10 AND f.step_return_x>=0.05
      AND f.coord_close>f.prior5_high_x AND f.turnover_ratio_x>=1.0
      AND f.close_location_x>=0.70
      AND round(f.close*100)<round(f.up_limit_price*100)
    ORDER BY f.symbol,f.cal_idx
    """
    con = duckdb.connect()
    con.execute("SET threads=4")
    try:
        raw = con.execute(query).fetchdf()
    finally:
        con.close()
    kept: list[int] = []
    for _, rows in raw.groupby("symbol", sort=False):
        last = -10**12
        for index, cal_idx in zip(rows.index, rows.cal_idx, strict=True):
            if int(cal_idx) - last > 20:
                kept.append(int(index))
                last = int(cal_idx)
    frame = raw.loc[kept].copy()
    frame["event_id"] = (
        "OAI-" + pd.to_datetime(frame.trade_date).dt.strftime("%Y%m%d")
        + "-" + frame.symbol.astype(str)
    )
    state = market.rename(columns={"b20_l5": "positive_ret20_share_lag5"})
    frame = frame.merge(state, on="trade_date", how="left", validate="many_to_one")
    frame = frame.loc[
        frame.trade_date.between(pd.Timestamp(start), pd.Timestamp(end))
        & frame.market_regime.eq("BEAR")
        & frame.market_positive_ret20_share.gt(frame.positive_ret20_share_lag5)
        & frame.prior10_return_x.le(-0.08)
        & frame.market_median_ret20.lt(frame.market_median_ret60)
    ].copy()
    frame["signal_date"] = pd.to_datetime(frame.trade_date)
    frame["signal_cal_idx"] = frame.cal_idx.astype(int)
    frame["close_location_x_f"] = frame.close_location_x
    frame["mechanism"] = "BEAR_FAST_CAPITULATION_ACTIVE_DEMAND"
    frame["lane"] = "BEAR_WORSENING_FAST_CAPITULATION"
    frame["rank1"] = frame.stock_minus_industry_ret20
    frame["rank2"] = frame.close_vs_prior10_high
    frame["rank3"] = frame.close_location_x_f
    columns = [
        "event_id", "symbol", "sleeve", "signal_date", "signal_cal_idx",
        "invalid_step_cum", "available_at", "decision_at", "prior10_return_x",
        "stock_minus_industry_ret20", "close_vs_prior10_high", "close_location_x_f",
        "trade_date", "market_regime", "market_median_ret20", "market_median_ret60",
        "market_positive_ret20_share", "positive_ret20_share_lag5",
        "latest_source_timestamp", "mechanism", "lane", "rank1", "rank2", "rank3",
    ]
    frame = frame[columns].sort_values(["signal_date", "symbol"], kind="mergesort").reset_index(drop=True)
    write_parquet(frame, output)
    return frame


def _legal_observation(row: pd.Series) -> bool:
    required = (
        "trade_status", "current_day_data_tradable", "current_valid",
        "market_rule_valid", "corporate_action_valid", "corporate_action_blocking",
        "hard_valid",
    )
    return bool(
        all(not pd.isna(row.get(field)) for field in required)
        and int(row.trade_status) == 1
        and row.current_day_data_tradable and row.current_valid and row.market_rule_valid
        and row.corporate_action_valid and not row.corporate_action_blocking and row.hard_valid
    )


def _buyable(row: pd.Series) -> bool:
    values = (row.open, row.coord_open, row.up_limit_price, row.coordinate_factor)
    return bool(
        _legal_observation(row) and all(np.isfinite(float(value)) for value in values)
        and float(row.open) > 0 and float(row.coord_open) > 0
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def _sellable(row: pd.Series) -> bool:
    values = (row.open, row.coord_open, row.down_limit_price, row.coordinate_factor)
    return bool(
        _legal_observation(row) and all(np.isfinite(float(value)) for value in values)
        and float(row.open) > 0 and float(row.coord_open) > 0
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def build_bull_accelerating(
    daily: Path,
    market: pd.DataFrame,
    output: Path,
    *,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Re-express the frozen V1 setup and V5 delayed trigger on QD-010."""
    query = f"""
    WITH source AS (
      SELECT *,coord_close/nullif(prior_coord_close,0)-1 AS step_return_x
      FROM read_parquet('{_sql_path(daily)}')
      WHERE trade_date BETWEEN DATE '2022-01-04' AND DATE '{end}'
        AND sleeve IN ('MAIN','CHINEXT')
    ), windows AS (
      SELECT *,lag(coord_close,4) OVER w AS lag4_close,
        lag(coord_close,64) OVER w AS lag64_close,
        lag(cal_idx,64) OVER w AS lag64_idx,
        lag(coord_high) OVER w AS prior_high,
        lag(coord_low) OVER w AS prior_low,
        avg(turnover_fraction) OVER w3 AS prior3_turnover,
        sum((step_return_x>0)::INTEGER) OVER w3 AS prior3_positive,
        count(*) OVER w20 AS prior20_n,
        bool_and(hard_valid AND history_valid AND current_valid
          AND current_day_data_tradable AND trade_status=1 AND market_rule_valid
          AND corporate_action_valid AND NOT corporate_action_blocking) OVER w20 AS prior20_valid
      FROM source
      WINDOW w AS(PARTITION BY symbol ORDER BY cal_idx),
        w3 AS(PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING),
        w20 AS(PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
    )
    SELECT *,coord_close/nullif(lag4_close,0)-1 AS impulse3,
      lag4_close/nullif(lag64_close,0)-1 AS pre_impulse_ret60
    FROM windows
    WHERE trade_date>=DATE '2022-01-01' AND prior20_n=20 AND prior20_valid
      AND hard_valid AND history_valid AND current_valid AND current_day_data_tradable
      AND trade_status=1 AND market_rule_valid AND corporate_action_valid
      AND NOT corporate_action_blocking AND NOT is_st AND available_at<=decision_at
      AND coord_close/nullif(lag4_close,0)-1>=0.15 AND prior3_positive>=2
      AND coord_high<=prior_high AND coord_low>=prior_low
      AND step_return_x BETWEEN -0.03 AND 0.03
      AND turnover_fraction<=0.70*prior3_turnover
      AND coord_close>=(prior_high+prior_low)/2
      AND round(close*100)<round(up_limit_price*100)
      AND lag64_idx=cal_idx-64
      AND lag4_close/nullif(lag64_close,0)-1<=0.47
    ORDER BY symbol,cal_idx
    """
    con = duckdb.connect()
    try:
        raw = con.execute(query).fetchdf()
    finally:
        con.close()
    kept: list[int] = []
    for _, rows in raw.groupby("symbol", sort=False):
        previous_raw: int | None = None
        for index, cal_idx in zip(rows.index, rows.cal_idx, strict=True):
            current = int(cal_idx)
            if previous_raw is None or current - previous_raw > 20:
                kept.append(int(index))
            previous_raw = current
    setups = raw.loc[kept].copy()
    daily_frame = _daily(daily)
    groups = {str(key): value for key, value in daily_frame.groupby("symbol", sort=False)}
    rows: list[dict[str, Any]] = []
    # 1e-12 only collapses binary arithmetic noise at an economically identical
    # coordinate tick; it is far below the smallest raw-price tick.
    for setup in setups.itertuples(index=False):
        path = groups[str(setup.symbol)]
        path = path.loc[path.cal_idx.gt(int(setup.cal_idx)) & path.cal_idx.le(int(setup.cal_idx) + 5)]
        trigger = None
        for _, row in path.iterrows():
            if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum) != float(setup.invalid_step_cum):
                break
            if _legal_observation(row) and float(row.coord_close) > float(setup.coord_high) + 1e-12:
                trigger = row
                break
        if trigger is None:
            continue
        rows.append({
            "event_id": "DIFID5-" + pd.Timestamp(trigger.trade_date).strftime("%Y%m%d")
            + "-" + str(setup.symbol).replace(".", ""),
            "symbol": setup.symbol, "sleeve": setup.sleeve,
            "setup_date": pd.Timestamp(setup.trade_date), "setup_cal_idx": int(setup.cal_idx),
            "setup_high_coord": float(setup.coord_high), "setup_low_coord": float(setup.coord_low),
            "impulse3": float(setup.impulse3),
            "setup_turnover_fraction": float(setup.turnover_fraction),
            "pre_impulse_ret60": float(setup.pre_impulse_ret60),
            "signal_date": pd.Timestamp(trigger.trade_date), "signal_cal_idx": int(trigger.cal_idx),
            "invalid_step_cum": float(trigger.invalid_step_cum),
            "coord_open": float(trigger.coord_open), "coord_high": float(trigger.coord_high),
            "coord_low": float(trigger.coord_low), "coord_close": float(trigger.coord_close),
            "available_at": pd.Timestamp(trigger.available_at), "decision_at": pd.Timestamp(trigger.decision_at),
        })
    frame = pd.DataFrame(rows)
    frame = frame.merge(market, left_on="signal_date", right_on="trade_date", how="left", validate="many_to_one")
    frame = frame.loc[
        frame.signal_date.between(pd.Timestamp(start), pd.Timestamp(end))
        & frame.market_regime.eq("BULL")
        & frame.market_median_ret20.ge(frame.market_median_ret60)
    ].copy()
    frame["candidate_source"] = "EXACT_V5_CAUSAL_REBUILD"
    frame["mechanism"] = "BULL_DELAYED_SUPPLY_CONTRACTION"
    frame["lane"] = "BULL_ACCELERATING_DELAYED_SUPPLY_CONTRACTION"
    frame["rank1"] = frame.impulse3
    frame["rank2"] = -frame.pre_impulse_ret60
    frame["rank3"] = 0.0
    frame = frame.sort_values(["signal_date", "symbol"], kind="mergesort").reset_index(drop=True)
    write_parquet(frame, output)
    return frame


def build_bull_decelerating(
    daily: Path,
    market: pd.DataFrame,
    output: Path,
    *,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Exact QIG mother, V24 admission, and frozen V27 decelerating route."""
    excluded = _quoted(EXCLUDED_MARKET_INDUSTRIES)
    query = f"""
    WITH source AS (
      SELECT * FROM read_parquet('{_sql_path(daily)}')
      WHERE trade_date BETWEEN DATE '2022-01-04' AND DATE '{end}'
        AND sleeve IN ('MAIN','CHINEXT') AND causal_industry NOT IN ({excluded})
    ), w1 AS (
      SELECT *,lag(coord_close) OVER w AS lag1_close,lag(cal_idx) OVER w AS lag1_idx,
        lag(invalid_step_cum,60) OVER w AS lag60_invalid_step_cum,
        lag(coord_close,20) OVER w AS lag20_close,lag(cal_idx,20) OVER w AS lag20_idx,
        lag(coord_close,60) OVER w AS lag60_close,lag(cal_idx,60) OVER w AS lag60_idx,
        count(*) OVER w60 AS prior60_n,bool_and(history_valid) OVER w60 AS prior60_valid,
        max(coord_high) OVER w40 AS platform_high,min(coord_low) OVER w40 AS platform_low,
        avg(turnover_fraction) OVER w20 AS avg_to20,
        avg(turnover_fraction) OVER wold AS avg_to_old
      FROM source
      WINDOW w AS(PARTITION BY symbol ORDER BY trade_date),
        w20 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
        w40 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 40 PRECEDING AND 1 PRECEDING),
        w60 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING),
        wold AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 21 PRECEDING)
    ), featured AS (
      SELECT *,CASE WHEN lag1_idx=cal_idx-1 THEN coord_close/nullif(lag1_close,0)-1 END AS step_return,
        CASE WHEN lag20_idx=cal_idx-20 THEN coord_close/nullif(lag20_close,0)-1 END AS ret20,
        CASE WHEN lag60_idx=cal_idx-60 THEN coord_close/nullif(lag60_close,0)-1 END AS ret60,
        platform_high/nullif(platform_low,0)-1 AS platform_width,
        avg_to20/nullif(avg_to_old,0) AS turnover_contraction,
        coord_open/nullif(lag1_close,0)-1 AS open_gap,
        turnover_fraction/nullif(avg_to20,0) AS turnover_expansion,
        (coord_close-coord_low)/nullif(coord_high-coord_low,0) AS close_location
      FROM w1
    ), market1 AS (
      SELECT trade_date,median(step_return) FILTER(WHERE current_valid AND NOT is_st AND step_return IS NOT NULL) AS market_median_ret1,
        avg((step_return>0)::INTEGER) FILTER(WHERE current_valid AND NOT is_st AND step_return IS NOT NULL) AS market_positive_ret1_share,
        max(available_at) FILTER(WHERE current_valid AND NOT is_st) AS market_state_latest
      FROM featured GROUP BY trade_date
    ), industry AS (
      SELECT trade_date,causal_industry,
        median(ret20) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL) AS industry_median_ret20,
        avg((ret20>0)::INTEGER) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL) AS industry_positive_ret20_share,
        count(ret20) FILTER(WHERE current_valid AND NOT is_st AND ret20 IS NOT NULL) AS industry_n20,
        median(step_return) FILTER(WHERE current_valid AND NOT is_st AND step_return IS NOT NULL) AS industry_median_ret1,
        avg((step_return>0)::INTEGER) FILTER(WHERE current_valid AND NOT is_st AND step_return IS NOT NULL) AS industry_positive_ret1_share,
        max(available_at) FILTER(WHERE current_valid AND NOT is_st) AS industry_state_latest
      FROM featured GROUP BY trade_date,causal_industry
    )
    SELECT f.*,m.market_median_ret1,m.market_positive_ret1_share,m.market_state_latest,
      i.industry_median_ret20,i.industry_positive_ret20_share,i.industry_n20,
      i.industry_median_ret1,i.industry_positive_ret1_share,i.industry_state_latest
    FROM featured f JOIN market1 m USING(trade_date)
    JOIN industry i USING(trade_date,causal_industry)
    WHERE f.trade_date BETWEEN DATE '{start}' AND DATE '{end}'
      AND NOT f.is_st AND f.current_valid AND f.prior60_n=60 AND f.prior60_valid
      AND f.lag60_invalid_step_cum=f.invalid_step_cum AND f.platform_width<=0.30
      AND f.avg_to20<=f.avg_to_old AND f.open_gap BETWEEN 0.01 AND 0.08
      AND f.coord_close>f.platform_high AND f.turnover_expansion>=1.50
      AND f.close_location>=0.70 AND round(f.close*100)<round(f.up_limit_price*100)
    ORDER BY f.trade_date,f.symbol
    """
    con = duckdb.connect()
    con.execute("SET threads=4")
    try:
        frame = con.execute(query).fetchdf()
    finally:
        con.close()
    frame = frame.merge(market, on="trade_date", how="left", validate="many_to_one")
    base = (
        frame.market_regime.eq("BULL") & frame.industry_n20.ge(5)
        & frame.industry_median_ret20.gt(0) & frame.industry_positive_ret20_share.gt(0.50)
    )
    synchronized = (
        frame.market_median_ret1.gt(0) & frame.market_positive_ret1_share.gt(0.50)
        & frame.industry_median_ret1.gt(0) & frame.industry_positive_ret1_share.gt(0.50)
    )
    idiosyncratic = frame.open_gap.ge(0.02)
    frame = frame.loc[
        base & (synchronized | (~synchronized & idiosyncratic))
        & frame.market_median_ret20.lt(frame.market_median_ret60)
    ].copy()
    frame["source_event_id"] = "QIG-" + pd.to_datetime(frame.trade_date).dt.strftime("%Y%m%d") + "-" + frame.symbol.astype(str)
    frame["chart_event_id"] = "BULL|" + frame.source_event_id
    frame["signal_date"] = pd.to_datetime(frame.trade_date)
    frame["signal_cal_idx"] = frame.cal_idx.astype(int)
    frame["signal_lineage"] = frame.invalid_step_cum
    frame["signal_coord_close"] = frame.coord_close
    frame["structural_level"] = frame.platform_high
    frame["engine"] = "BULL_CONTINUATION"
    frame["admission_lane"] = np.where(synchronized.loc[frame.index], "SYNCHRONIZED_MAJORITY_DEMAND", "IDIOSYNCRATIC_INFORMATION_JUMP")
    frame["feature_latest_timestamp"] = frame[["available_at", "market_state_latest", "industry_state_latest", "latest_source_timestamp"]].max(axis=1)
    frame["event_id"] = frame.chart_event_id
    frame["lane"] = "BULL_DECELERATING_QUIET_INVENTORY"
    frame["rank1"] = 0.0
    frame["rank2"] = frame.signal_coord_close / frame.structural_level - 1.0
    frame["rank3"] = 0.0
    columns = [
        "source_event_id", "chart_event_id", "symbol", "sleeve", "signal_date",
        "signal_cal_idx", "signal_lineage", "signal_coord_close", "structural_level",
        "engine", "admission_lane", "feature_latest_timestamp", "market_median_ret20",
        "market_median_ret60", "market_regime", "event_id", "lane", "rank1", "rank2", "rank3",
    ]
    frame = frame[columns].sort_values(["signal_date", "symbol"], kind="mergesort").reset_index(drop=True)
    write_parquet(frame, output)
    return frame


def replay_bull_decelerating(candidates: pd.DataFrame, daily: Path) -> pd.DataFrame:
    daily_frame = _daily(daily)
    groups = {str(key): value for key, value in daily_frame.groupby("symbol", sort=False)}
    rows: list[dict[str, Any]] = []
    for candidate in candidates.itertuples(index=False):
        path = groups[str(candidate.symbol)]
        signal_idx, lineage = int(candidate.signal_cal_idx), float(candidate.signal_lineage)
        common = {
            "chart_event_id": str(candidate.chart_event_id), "source_event_id": str(candidate.source_event_id),
            "symbol": str(candidate.symbol), "sleeve": str(candidate.sleeve), "engine": str(candidate.engine),
            "admission_lane": str(candidate.admission_lane), "signal_date": pd.Timestamp(candidate.signal_date),
            "signal_cal_idx": signal_idx, "signal_coord_close": float(candidate.signal_coord_close),
            "structural_level": float(candidate.structural_level), "expected_market_regime": "BULL",
            "target_return": 0.15, "horizon_sessions": 15,
            "route_semantics": "SIGNAL_CLOSE_CAUSAL_BULL",
        }
        confirmations = path.loc[path.cal_idx.eq(signal_idx + 1)]
        if len(confirmations) != 1:
            rows.append({**common, "accepted": False, "status": "NO_IMMEDIATE_CONFIRMATION_BAR"})
            continue
        confirmation = confirmations.iloc[0]
        threshold = float(candidate.structural_level)
        if candidate.admission_lane == "IDIOSYNCRATIC_INFORMATION_JUMP":
            threshold = max(threshold, float(candidate.signal_coord_close))
        confirmation_payload = {
            "confirmation_date": pd.Timestamp(confirmation.trade_date),
            "confirmation_cal_idx": int(confirmation.cal_idx),
            "confirmation_coord_close": float(confirmation.coord_close),
            "confirmation_threshold": threshold,
            "confirmation_close_to_structure": float(confirmation.coord_close) / threshold - 1.0,
            "confirmation_market_regime": "BULL",
        }
        if pd.isna(confirmation.invalid_step_cum) or float(confirmation.invalid_step_cum) != lineage:
            rows.append({**common, **confirmation_payload, "accepted": False, "status": "CONFIRMATION_LINEAGE_CHANGE"})
            continue
        if not _legal_observation(confirmation):
            rows.append({**common, **confirmation_payload, "accepted": False, "status": "INVALID_IMMEDIATE_CONFIRMATION_BAR"})
            continue
        if float(confirmation.coord_close) < threshold:
            rows.append({**common, **confirmation_payload, "accepted": False, "status": "REJECTED_STRUCTURE_NOT_ACCEPTED"})
            continue
        entry_pool = path.loc[path.invalid_step_cum.eq(lineage) & path.cal_idx.gt(signal_idx + 1) & path.cal_idx.le(signal_idx + 4)]
        entry = next((row for _, row in entry_pool.iterrows() if _buyable(row)), None)
        if entry is None:
            rows.append({**common, **confirmation_payload, "accepted": True, "status": "NO_LEGAL_ENTRY"})
            continue
        entry_idx, entry_price = int(entry.cal_idx), float(entry.coord_open)
        target_price = entry_price * 1.15
        pending_time_exit = False
        result: dict[str, Any] | None = None
        for _, row in path.loc[path.cal_idx.gt(entry_idx)].iterrows():
            if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum) != lineage:
                result = {**common, **confirmation_payload, "accepted": True,
                    "entry_date": pd.Timestamp(entry.trade_date), "entry_cal_idx": entry_idx,
                    "entry_price": entry_price, "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY"}
                break
            if pending_time_exit and _sellable(row):
                exit_price, exit_reason = float(row.coord_open), "H15_TIME_STOP"
            elif _legal_observation(row) and float(row.coord_high) >= target_price:
                exit_price, exit_reason = target_price, "TARGET_15"
            else:
                if _legal_observation(row) and int(row.cal_idx) >= entry_idx + 15:
                    pending_time_exit = True
                continue
            gross = exit_price / entry_price - 1.0
            result = {**common, **confirmation_payload, "accepted": True, "status": "COMPLETED",
                "entry_date": pd.Timestamp(entry.trade_date), "entry_cal_idx": entry_idx, "entry_price": entry_price,
                "exit_date": pd.Timestamp(row.trade_date), "exit_cal_idx": int(row.cal_idx), "exit_price": exit_price,
                "exit_reason": exit_reason, "holding_sessions": int(row.cal_idx)-entry_idx,
                "gross_return": gross, "net_return": gross-0.004}
            break
        rows.append(result or {**common, **confirmation_payload, "accepted": True,
            "entry_date": pd.Timestamp(entry.trade_date), "entry_cal_idx": entry_idx,
            "entry_price": entry_price, "status": "INCOMPLETE_PATH"})
    frame = pd.DataFrame(rows)
    for column in ("signal_date", "confirmation_date", "entry_date", "exit_date"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column])
    return frame


def apply_capacity(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    ordered = frame.sort_values(
        ["entry_date", "sleeve", "rank1", "rank2", "rank3", "event_id"],
        ascending=[True, True, False, False, False, True], kind="mergesort",
    )
    active: dict[str, dict[str, Any]] = {"MAIN": {}, "CHINEXT": {}}
    accepted: list[str] = []
    reasons: dict[str, str] = {}
    for entry_date, day in ordered.groupby("entry_date", sort=True):
        for state in active.values():
            for symbol, row in list(state.items()):
                open_exit = not str(row.exit_reason).startswith("TARGET_")
                if row.exit_date < entry_date or (row.exit_date == entry_date and open_exit):
                    del state[symbol]
        for sleeve, cohort in day.groupby("sleeve", sort=True):
            admitted = 0
            state = active[str(sleeve)]
            for row in cohort.itertuples(index=False):
                reason = None
                if row.symbol in state:
                    reason = "ACTIVE_SYMBOL"
                elif len(state) >= 75:
                    reason = "K75_ACTIVE_CAP"
                elif admitted >= 20:
                    reason = "DAILY_ENTRY_CAP_20"
                if reason:
                    reasons[str(row.event_id)] = reason
                    continue
                accepted.append(str(row.event_id))
                state[str(row.symbol)] = row
                admitted += 1
    chosen = ordered.loc[ordered.event_id.astype(str).isin(accepted)].copy()
    chosen["capacity_status"], chosen["skip_reason"] = "ACCEPTED", None
    skipped = ordered.loc[~ordered.event_id.astype(str).isin(accepted)].copy()
    skipped["capacity_status"], skipped["skip_reason"] = "SKIPPED", skipped.event_id.map(reasons)
    return chosen, skipped


def standardize_routes(
    fast_outcomes: pd.DataFrame,
    fast: pd.DataFrame,
    slow_outcomes: pd.DataFrame,
    slow: pd.DataFrame,
    accelerating_outcomes: pd.DataFrame,
    accelerating: pd.DataFrame,
    decelerating_outcomes: pd.DataFrame,
    decelerating: pd.DataFrame,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    merged = fast_outcomes.loc[fast_outcomes.status.eq("COMPLETED")].merge(
        fast[["event_id", "stock_minus_industry_ret20", "close_vs_prior10_high", "close_location_x_f"]],
        on="event_id", validate="one_to_one",
    )
    merged["lane"] = "BEAR_WORSENING_FAST_CAPITULATION"
    merged["rank1"], merged["rank2"], merged["rank3"] = (
        merged.stock_minus_industry_ret20, merged.close_vs_prior10_high, merged.close_location_x_f
    )
    frames.append(merged[V27_STANDARD_COLUMNS])

    merged = slow_outcomes.loc[slow_outcomes.status.eq("COMPLETED")].merge(
        slow[["event_id", "previous5_downside_turnover", "last5_downside_turnover", "exact_prior20_return", "close_location"]],
        on="event_id", validate="one_to_one",
    )
    merged["lane"] = "BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION"
    merged["rank1"] = merged.previous5_downside_turnover - merged.last5_downside_turnover
    merged["rank2"], merged["rank3"] = -merged.exact_prior20_return, merged.close_location
    frames.append(merged[V27_STANDARD_COLUMNS])

    merged = accelerating_outcomes.loc[accelerating_outcomes.status.eq("COMPLETED")].merge(
        accelerating[["event_id", "impulse3", "pre_impulse_ret60"]],
        on="event_id", validate="one_to_one",
    )
    merged["lane"] = "BULL_ACCELERATING_DELAYED_SUPPLY_CONTRACTION"
    merged["rank1"], merged["rank2"], merged["rank3"] = merged.impulse3, -merged.pre_impulse_ret60, 0.0
    frames.append(merged[V27_STANDARD_COLUMNS])

    merged = decelerating_outcomes.loc[decelerating_outcomes.status.eq("COMPLETED")].copy()
    merged["event_id"] = merged.chart_event_id
    merged["lane"] = "BULL_DECELERATING_QUIET_INVENTORY"
    merged["rank1"] = merged.confirmation_close_to_structure
    merged["rank2"] = merged.signal_coord_close / merged.structural_level - 1.0
    merged["rank3"] = 0.0
    frames.append(merged[V27_STANDARD_COLUMNS])
    result = pd.concat(frames, ignore_index=True).sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if result.event_id.duplicated().any() or result.duplicated(["symbol", "signal_date"]).any():
        raise ReproductionError("cross-route ATRDR identity collision")
    return result


def replay_portfolio(
    trades: pd.DataFrame,
    daily: Path,
    *,
    start: str,
    end: str,
) -> pd.DataFrame:
    daily_frame = _daily(daily)
    calendar = sorted(daily_frame.loc[daily_frame.trade_date.between(pd.Timestamp(start), pd.Timestamp(end)), "trade_date"].unique())
    groups = {str(key): value.set_index("trade_date") for key, value in daily_frame.groupby("symbol", sort=False)}
    entries = {key: value for key, value in trades.groupby("entry_date", sort=False)}
    exits = {key: value for key, value in trades.groupby("exit_date", sort=False)}
    state: dict[str, dict[str, Any]] = {
        "MAIN": {"cash": 0.5, "positions": {}}, "CHINEXT": {"cash": 0.5, "positions": {}}
    }
    rows: list[dict[str, Any]] = []
    for value in calendar:
        date = pd.Timestamp(value)
        exit_rows = exits.get(date)
        if exit_rows is not None:
            for row in exit_rows.itertuples(index=False):
                if str(row.exit_reason).startswith("TARGET_"):
                    continue
                sleeve = state[row.sleeve]
                position = sleeve["positions"].pop(str(row.event_id))
                sleeve["cash"] += position["quantity"] * float(row.exit_price) * 0.998
        open_nav: dict[str, float] = {}
        for sleeve_name, sleeve in state.items():
            market_value = sum(
                position["quantity"] * float(groups[position["symbol"]].loc[date, "coord_open"])
                for position in sleeve["positions"].values()
            )
            open_nav[sleeve_name] = float(sleeve["cash"] + market_value)
        entry_rows = entries.get(date)
        if entry_rows is not None:
            for sleeve_name, cohort in entry_rows.groupby("sleeve", sort=True):
                sleeve = state[sleeve_name]
                cohort_budget = min(0.10 * open_nav[sleeve_name], sleeve["cash"])
                per_name = min(cohort_budget / len(cohort), 0.025 * open_nav[sleeve_name])
                for row in cohort.sort_values("event_id").itertuples(index=False):
                    notional = min(per_name, sleeve["cash"] / 1.002)
                    quantity = notional / float(row.entry_price)
                    sleeve["cash"] -= notional * 1.002
                    sleeve["positions"][str(row.event_id)] = {"quantity": quantity, "symbol": str(row.symbol)}
        if exit_rows is not None:
            for row in exit_rows.itertuples(index=False):
                if not str(row.exit_reason).startswith("TARGET_"):
                    continue
                sleeve = state[row.sleeve]
                position = sleeve["positions"].pop(str(row.event_id))
                sleeve["cash"] += position["quantity"] * float(row.exit_price) * 0.998
        payload: dict[str, Any] = {"trade_date": date}
        invested = total_nav = 0.0
        active = 0
        for sleeve_name, prefix in (("MAIN", "main"), ("CHINEXT", "chinext")):
            sleeve = state[sleeve_name]
            market_value = sum(
                position["quantity"] * float(groups[position["symbol"]].loc[date, "coord_close"])
                for position in sleeve["positions"].values()
            )
            nav = float(sleeve["cash"] + market_value)
            payload[f"{prefix}_nav"] = nav
            payload[f"{prefix}_cash"] = float(sleeve["cash"])
            payload[f"{prefix}_gross_exposure"] = float(market_value)
            payload[f"{prefix}_active"] = len(sleeve["positions"])
            if sleeve["cash"] < -1e-10 or market_value > nav + 1e-10:
                raise ReproductionError("V27 continuation financing invariant violated")
            invested += market_value
            total_nav += nav
            active += len(sleeve["positions"])
        payload["combined_nav"], payload["active_positions"] = total_nav, active
        payload["utilization"] = 0.0 if total_nav == 0 else invested / total_nav
        payload["cash"] = float(
            state["MAIN"]["cash"] + state["CHINEXT"]["cash"]
        )
        payload["gross_exposure"] = float(invested)
        payload["gross_exposure_ratio"] = payload["utilization"]
        rows.append(payload)
    nav = pd.DataFrame(rows)
    nav["ret"] = nav.combined_nav.pct_change().fillna(0.0)
    if any(state[name]["positions"] for name in state):
        raise ReproductionError("V27 portfolio has open positions at the registered data end")
    return nav
