"""ATRDR mother screens reconstructed/extracted from frozen definitions.

The slow-supply screen is a minimal extract of the original historical
producer.  The OAI fast-capitulation mother producer was not present in any
reachable source object; its implementation below is reconstructed from the
frozen contract and is checked event-for-event against the frozen mother panel.

RECONSTRUCTED_FROM_FROZEN_SPEC
NOT_ORIGINAL_SOURCE
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from ..errors import ReproductionError
from ..io import _sql_path, write_parquet


def _columns(path: Path) -> set[str]:
    con = duckdb.connect()
    try:
        return set(
            con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{_sql_path(path)}')"
            ).fetchdf()["column_name"]
        )
    finally:
        con.close()


def build_market_state(
    daily: Path,
    output: Path,
    *,
    start: str = "2014-01-01",
    end: str = "2023-12-31",
    history_start: str | None = None,
) -> pd.DataFrame:
    """Rebuild the causal market state from completed PIT daily rows."""
    query = f"""
    WITH lagged AS (
      SELECT *,lag(coord_close,20) OVER w AS calc_lag20_close,
        lag(coord_close,60) OVER w AS calc_lag60_close
      FROM read_parquet('{_sql_path(daily)}')
      WINDOW w AS (PARTITION BY symbol ORDER BY cal_idx)
    ), base AS (
      SELECT trade_date,available_at,decision_at,
        coord_close/nullif(calc_lag20_close,0)-1 AS ret20,
        coord_close/nullif(calc_lag60_close,0)-1 AS ret60
      FROM lagged
      WHERE trade_date BETWEEN DATE '{history_start or start}' AND DATE '{end}'
        AND current_valid AND hard_valid AND NOT is_st
    ), market0 AS (
      SELECT trade_date,
        median(ret20) AS market_median_ret20,
        median(ret60) AS market_median_ret60,
        avg((ret20>0)::INTEGER) AS market_positive_ret20_share,
        avg((ret60>0)::INTEGER) AS market_positive_ret60_share,
        max(available_at) AS latest_source_timestamp
      FROM base GROUP BY trade_date
    ), market AS (
      SELECT *,
        lag(market_positive_ret20_share,5) OVER (ORDER BY trade_date) AS b20_l5,
        lag(latest_source_timestamp,5) OVER (ORDER BY trade_date) AS b20_l5_source_timestamp
      FROM market0
    )
    SELECT *,CASE
      WHEN market_median_ret20>0 AND market_median_ret60>0
       AND market_positive_ret20_share>0.50 AND market_positive_ret60_share>0.50 THEN 'BULL'
      WHEN market_median_ret20<=0 AND market_median_ret60<=0
       AND market_positive_ret20_share<=0.50 AND market_positive_ret60_share<=0.50 THEN 'BEAR'
      ELSE 'TRANSITION' END AS market_regime
    FROM market
    WHERE trade_date BETWEEN DATE '{start}' AND DATE '{end}'
    ORDER BY trade_date
    """
    con = duckdb.connect()
    try:
        frame = con.execute(query).fetchdf()
    finally:
        con.close()
    for column in ("trade_date", "latest_source_timestamp", "b20_l5_source_timestamp"):
        frame[column] = pd.to_datetime(frame[column])
    if frame.latest_source_timestamp.gt(frame.trade_date + pd.Timedelta(hours=15)).any():
        raise ReproductionError("market source is later than completed close")
    write_parquet(frame, output)
    return frame


def build_oai_mother(
    daily: Path,
    output: Path,
    *,
    start: str = "2014-01-01",
    end: str = "2023-12-31",
    expected_count: int | None = 3433,
) -> pd.DataFrame:
    """Rebuild the frozen OAI mother panel, including its 20-session cooldown."""
    daily_columns = _columns(daily)
    lag20 = "" if "lag20_close" in daily_columns else ",lag(coord_close,20) OVER w AS lag20_close"
    step = "" if "step_return" in daily_columns else ",coord_close/nullif(prior_coord_close,0)-1 AS step_return"
    industry_identity = (
        "industry_snapshot_id IS NOT NULL"
        if "industry_snapshot_id" in daily_columns
        else "causal_industry IS NOT NULL"
    )
    query = f"""
    WITH source AS (
      SELECT * {step} FROM read_parquet('{_sql_path(daily)}')
    ), d AS (
      SELECT *,
        max(coord_high) OVER w5 AS prior5_high_x,
        max(coord_high) OVER w10 AS prior10_high,
        min(coord_low) OVER w5 AS prior5_low,
        min(coord_low) OVER w20 AS prior20_low,
        arg_min(cal_idx,coord_low) OVER w20 AS prior20_low_idx,
        avg(turnover_fraction) OVER w20 AS avg_to20_x,
        avg(turnover_fraction) OVER w5 AS avg_to5,
        avg(turnover_fraction) OVER w10 AS avg_to10,
        count(*) OVER w20 AS prior20_n_x,
        bool_and(hard_valid AND current_day_data_tradable AND trade_status=1
          AND market_rule_valid AND corporate_action_valid AND NOT corporate_action_blocking)
          OVER w20 AS prior20_valid_x,
        min(invalid_step_cum) OVER w20 AS invalid_min_x,
        max(invalid_step_cum) OVER w20 AS invalid_max_x,
        lag(coord_close,5) OVER w AS lag5_close_x,
        lag(coord_close,10) OVER w AS lag10_close_x,
        sum(abs(step_return)) OVER w10 AS absret10_sum,
        sum((step_return>0)::INTEGER) OVER w10 AS prior10_up_days,
        max(coord_high) OVER w20 AS prior20_high,
        min(coord_low) OVER w10 AS prior10_low
        {lag20}
      FROM source
      WINDOW
        w AS (PARTITION BY symbol ORDER BY cal_idx),
        w5 AS (PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
        w10 AS (PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING),
        w20 AS (PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
    ), feature AS (
      SELECT *,
        (coord_close-coord_low)/nullif(coord_high-coord_low,0) AS close_location_x,
        turnover_fraction/nullif(avg_to20_x,0) AS turnover_ratio_x,
        prior_coord_close/nullif(lag5_close_x,0)-1 AS prior5_return,
        prior_coord_close/nullif(lag10_close_x,0)-1 AS prior10_return,
        abs(prior_coord_close-lag10_close_x)/nullif(absret10_sum*prior_coord_close,0)
          AS prior10_efficiency,
        cal_idx-prior20_low_idx AS prior20_low_age,
        prior20_high/nullif(prior20_low,0)-1 AS prior20_range,
        prior10_high/nullif(prior10_low,0)-1 AS prior10_range,
        coord_low/nullif(prior20_low,0)-1 AS signal_low_vs_prior20_low,
        coord_low/nullif(prior5_low,0)-1 AS signal_low_vs_prior5_low,
        coord_close/nullif(prior10_high,0)-1 AS close_vs_prior10_high,
        coord_open/nullif(prior_coord_close,0)-1 AS signal_open_gap,
        avg_to5/nullif(avg_to20_x,0) AS prior5_turnover_vs20,
        avg_to10/nullif(avg_to20_x,0) AS prior10_turnover_vs20
      FROM d
    ), eligible AS (
      SELECT * FROM feature
      WHERE trade_date BETWEEN DATE '{start}' AND DATE '{end}'
        AND prior20_n_x=20 AND prior20_valid_x
        AND invalid_min_x=invalid_step_cum AND invalid_max_x=invalid_step_cum
        AND hard_valid AND current_valid AND current_day_data_tradable AND trade_status=1
        AND market_rule_valid AND corporate_action_valid AND NOT corporate_action_blocking
        AND industry_valid AND historical_identity_valid AND {industry_identity}
        AND NOT is_st AND available_at<=decision_at
        AND round(close*100)<round(up_limit_price*100)
        AND coord_close/nullif(lag20_close,0)-1<=-0.10
        AND step_return>=0.05 AND coord_close>prior5_high_x
        AND turnover_fraction/nullif(avg_to20_x,0)>=1.0
        AND (coord_close-coord_low)/nullif(coord_high-coord_low,0)>=0.70
    ), industry AS (
      SELECT trade_date,causal_industry,median(ret20) AS industry_median_ret20,
        avg((ret20>0)::INTEGER) AS industry_positive_ret20_share,
        count(*) AS industry_n
      FROM (
        SELECT trade_date,causal_industry,
          coord_close/nullif(lag(coord_close,20) OVER w,0)-1 AS ret20,
          current_valid,hard_valid,is_st
        FROM read_parquet('{_sql_path(daily)}')
        WINDOW w AS (PARTITION BY symbol ORDER BY cal_idx)
      )
        WHERE current_valid AND hard_valid AND NOT is_st AND causal_industry IS NOT NULL
      GROUP BY trade_date,causal_industry
    )
    SELECT e.*,e.coord_close/nullif(e.lag20_close,0)-1 AS ret20,
      i.industry_median_ret20,i.industry_positive_ret20_share,i.industry_n,
      CASE WHEN i.industry_n>=5 THEN
        e.coord_close/nullif(e.lag20_close,0)-1-i.industry_median_ret20 END
        AS stock_minus_industry_ret20
    FROM eligible e JOIN industry i USING(trade_date,causal_industry)
    ORDER BY symbol,cal_idx
    """
    con = duckdb.connect()
    con.execute("SET threads=4")
    try:
        raw = con.execute(query).fetchdf()
    finally:
        con.close()
    kept: list[int] = []
    for _, rows in raw.groupby("symbol", sort=False):
        last: int | None = None
        for index, cal_idx in zip(rows.index, rows.cal_idx, strict=True):
            current = int(cal_idx)
            if last is None or current - last >= 20:
                kept.append(int(index))
                last = current
    frame = raw.loc[kept].copy()
    frame["event_id"] = "OAI-" + pd.to_datetime(frame.trade_date).dt.strftime("%Y%m%d") + "-" + frame.symbol.astype(str)
    frame = frame.sort_values(["trade_date", "event_id"], kind="mergesort").reset_index(drop=True)
    if frame.event_id.duplicated().any() or (
        expected_count is not None and len(frame) != expected_count
    ):
        raise ReproductionError(f"OAI mother identity drift: {len(frame)} rows")
    write_parquet(frame, output)
    return frame


def select_fast_bear(oai: pd.DataFrame, market: pd.DataFrame, output: Path) -> pd.DataFrame:
    frame = oai.merge(market, on="trade_date", how="left", validate="many_to_one")
    mask = (
        frame.market_regime.eq("BEAR")
        & frame.market_positive_ret20_share.gt(frame.b20_l5)
        & frame.prior10_return.le(-0.08)
    )
    selected = frame.loc[mask].copy()
    selected["signal_date"] = pd.to_datetime(selected.trade_date)
    selected["signal_cal_idx"] = selected.cal_idx.astype(int)
    selected["signal_decision_at"] = pd.to_datetime(selected.decision_at)
    selected["regime_latest_source_timestamp"] = pd.to_datetime(selected.latest_source_timestamp)
    selected["signal_invalid"] = selected.invalid_step_cum
    selected = selected.sort_values(["signal_date", "event_id"], kind="mergesort").reset_index(drop=True)
    write_parquet(selected, output)
    return selected


def select_fast_capacity(outcomes: pd.DataFrame, output: Path) -> pd.DataFrame:
    """Apply the frozen V13R1 rank, active-symbol, K75 and daily-20 gates."""
    rank = ("stock_minus_industry_ret20", "close_vs_prior10_high", "close_location_x")
    eligible = outcomes.loc[
        outcomes.status.eq("COMPLETED") & outcomes[list(rank)].notna().all(axis=1)
    ].sort_values(
        ["entry_date", "sleeve", *rank, "event_id"],
        ascending=[True, True, False, False, False, True],
        kind="mergesort",
    )
    active: dict[str, dict[str, object]] = {"MAIN": {}, "CHINEXT": {}}
    accepted: list[str] = []
    for entry_date, day in eligible.groupby("entry_date", sort=True):
        date = pd.Timestamp(entry_date)
        for state in active.values():
            for symbol, row in list(state.items()):
                exit_date = pd.Timestamp(row.exit_date)
                open_exit = str(row.exit_reason) != "TARGET_10"
                if exit_date < date or (exit_date == date and open_exit):
                    del state[symbol]
        for sleeve, rows in day.groupby("sleeve", sort=True):
            admitted = 0
            state = active[str(sleeve)]
            for row in rows.itertuples(index=False):
                if str(row.symbol) in state or len(state) >= 75 or admitted >= 20:
                    continue
                accepted.append(str(row.event_id))
                state[str(row.symbol)] = row
                admitted += 1
    frame = eligible.loc[eligible.event_id.astype(str).isin(accepted)].copy()
    frame["v13r1_capacity_status"] = "ACCEPTED"
    frame = frame.sort_values(["signal_date", "event_id"], kind="mergesort").reset_index(drop=True)
    write_parquet(frame, output)
    return frame


def build_slow_mother(
    daily: Path,
    regime: Path,
    output: Path,
    *,
    history_start: str = "2013-01-01",
    start: str = "2014-01-01",
    end: str = "2023-12-31",
) -> pd.DataFrame:
    """Minimal extract of the original slow-supply mother SQL, extended to 2023."""
    daily_columns = _columns(daily)
    lag20 = "" if "lag20_close" in daily_columns else ",lag(d.coord_close,20) OVER wfull AS lag20_close"
    step = "" if "step_return" in daily_columns else ",coord_close/nullif(prior_coord_close,0)-1 AS step_return"
    industry_identity = (
        "industry_snapshot_id IS NOT NULL"
        if "industry_snapshot_id" in daily_columns
        else "causal_industry IS NOT NULL"
    )
    query = f"""
    WITH source AS (
      SELECT * {step} FROM read_parquet('{_sql_path(daily)}')
    ), base AS (
      SELECT d.*,r.market_regime,r.latest_source_timestamp AS market_latest_source_timestamp,
        count(*) OVER w60 AS prior60_rows,
        lag(d.cal_idx,60) OVER (PARTITION BY d.symbol ORDER BY d.cal_idx) AS lag60_cal_idx_exact,
        min(d.invalid_step_cum) OVER w60 AS prior60_lineage_min,
        max(d.invalid_step_cum) OVER w60 AS prior60_lineage_max,
        bool_and(d.hard_valid AND d.market_rule_valid AND d.corporate_action_valid
          AND NOT d.corporate_action_blocking AND coalesce(d.corporate_action_count,0)=0)
          OVER w60 AS prior60_lineage_valid,
        max(d.coord_high) OVER w20 AS prior20_high,max(d.coord_high) OVER w5 AS prior5_high,
        min(d.coord_low) OVER w5 AS last5_low,min(d.coord_low) OVER wprev5 AS previous5_low,
        sum((d.step_return>0)::INT) OVER w20/20.0 AS prior20_positive_share,
        max(abs(d.step_return)) OVER w20 AS prior20_max_abs_return,
        sum(CASE WHEN d.step_return<0 THEN d.turnover_fraction ELSE 0 END) OVER w20 AS prior20_downside_turnover,
        sum(CASE WHEN d.step_return>0 THEN d.turnover_fraction ELSE 0 END) OVER w20 AS prior20_upside_turnover,
        sum(CASE WHEN d.step_return<0 THEN d.turnover_fraction ELSE 0 END) OVER w5 AS last5_downside_turnover,
        sum(CASE WHEN d.step_return<0 THEN d.turnover_fraction ELSE 0 END) OVER wprev5 AS previous5_downside_turnover,
        median(d.turnover_fraction) OVER w20 AS prior20_turnover_median,
        CASE WHEN d.coord_high>d.coord_low THEN (d.coord_close-d.coord_low)/(d.coord_high-d.coord_low) END AS close_location
        {lag20}
      FROM source d LEFT JOIN read_parquet('{_sql_path(regime)}') r USING(trade_date)
      WHERE d.trade_date BETWEEN DATE '{history_start}' AND DATE '{end}'
      WINDOW w60 AS(PARTITION BY d.symbol ORDER BY d.cal_idx ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING),
        wfull AS(PARTITION BY d.symbol ORDER BY d.cal_idx),
        w20 AS(PARTITION BY d.symbol ORDER BY d.cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
        w5 AS(PARTITION BY d.symbol ORDER BY d.cal_idx ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
        wprev5 AS(PARTITION BY d.symbol ORDER BY d.cal_idx ROWS BETWEEN 10 PRECEDING AND 6 PRECEDING)
    ), feature AS (
      SELECT *,prior20_downside_turnover/nullif(prior20_upside_turnover,0) AS downside_upside_turnover_ratio,
        turnover_fraction/nullif(prior20_turnover_median,0) AS turnover_expansion,
        coord_close/nullif(lag20_close,0)-1 AS exact_prior20_return,
        (prior60_rows=60 AND lag60_cal_idx_exact=cal_idx-60
          AND prior60_lineage_min=invalid_step_cum AND prior60_lineage_max=invalid_step_cum
          AND prior60_lineage_valid AND hard_valid AND current_valid AND current_day_data_tradable
          AND trade_status=1 AND market_rule_valid AND corporate_action_valid
          AND NOT corporate_action_blocking AND coalesce(corporate_action_count,0)=0
          AND industry_valid AND historical_identity_valid AND {industry_identity}
          AND NOT is_st AND available_at<=decision_at AND market_latest_source_timestamp<=decision_at
          AND round(close*100)<round(up_limit_price*100) AND coord_close>0 AND coord_high>=coord_low
          AND turnover_fraction>0 AND prior20_turnover_median>0) AS row_eligible
      FROM base
    ), flagged AS (
      SELECT *,row_eligible AND market_regime IN ('BEAR','TRANSITION')
        AND exact_prior20_return<=-0.08 AND last5_low>=previous5_low
        AND last5_downside_turnover<=previous5_downside_turnover
        AND step_return BETWEEN 0.02 AND 0.07 AND close_location>=0.75
        AND coord_close>prior5_high AND turnover_expansion BETWEEN 1.00 AND 2.50 AS raw_slow
      FROM feature
    ), cooled AS (
      SELECT *,max(CASE WHEN raw_slow THEN cal_idx END) OVER(PARTITION BY symbol,
        CASE WHEN trade_date<=DATE '2020-12-31' THEN 0
             WHEN trade_date<=DATE '2021-12-31' THEN 1 ELSE 2 END,
        CASE WHEN trade_date<=DATE '2020-12-31' THEN 'ALL' ELSE market_regime END
        ORDER BY cal_idx
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prior_slow_cal_idx FROM flagged
    )
    SELECT 'SLOW_SUPPLY_EXHAUSTION_TAKEOVER|'||strftime(trade_date,'%Y%m%d')||'|'||symbol AS event_id,
      'SLOW_SUPPLY_EXHAUSTION_TAKEOVER' AS mechanism,symbol,sleeve,trade_date AS signal_date,
      cal_idx AS signal_cal_idx,decision_at,available_at,market_regime,market_latest_source_timestamp,
      invalid_step_cum,coordinate_factor,coord_open,coord_high,coord_low,coord_close,
      prior20_high,prior5_high,last5_low,previous5_low,exact_prior20_return,
      prior20_positive_share,prior20_max_abs_return,downside_upside_turnover_ratio,
      last5_downside_turnover,previous5_downside_turnover,turnover_expansion,
      close_location,step_return,causal_industry
    FROM cooled WHERE trade_date BETWEEN DATE '{start}' AND DATE '{end}'
      AND raw_slow AND (prior_slow_cal_idx IS NULL OR cal_idx-prior_slow_cal_idx>20)
    ORDER BY signal_date,event_id
    """
    con = duckdb.connect()
    con.execute("SET threads=4")
    try:
        frame = con.execute(query).fetchdf()
    finally:
        con.close()
    for column in ("signal_date", "decision_at", "available_at", "market_latest_source_timestamp"):
        frame[column] = pd.to_datetime(frame[column])
    if frame.event_id.duplicated().any():
        raise ReproductionError("duplicate slow mother event")
    write_parquet(frame, output)
    return frame


def route_v27_bear(
    fast_accepted: pd.DataFrame,
    slow_outcomes: pd.DataFrame,
    slow_candidates: pd.DataFrame,
    market: pd.DataFrame,
    output: Path,
) -> pd.DataFrame:
    """Apply the frozen worsening/stabilizing V27 Bear arbitration."""
    fast = fast_accepted.loc[
        fast_accepted.market_median_ret20.lt(fast_accepted.market_median_ret60)
    ].copy()
    fast["lane"] = "BEAR_WORSENING_FAST_CAPITULATION"
    fast["rank1"] = fast.stock_minus_industry_ret20
    fast["rank2"] = fast.close_vs_prior10_high
    fast["rank3"] = fast.close_location_x

    candidate_fields = [
        "event_id", "exact_prior20_return", "last5_downside_turnover",
        "previous5_downside_turnover", "close_location",
    ]
    slow = slow_outcomes.loc[slow_outcomes.status.eq("COMPLETED")].merge(
        slow_candidates[candidate_fields], on="event_id", how="left", validate="one_to_one"
    )
    state = market[["trade_date", "market_median_ret20", "market_median_ret60", "latest_source_timestamp"]]
    slow = slow.merge(state, left_on="signal_date", right_on="trade_date", how="left", validate="many_to_one")
    deep_market = slow.market_median_ret60.le(-0.05)
    frozen_gate = ~deep_market | (
        slow.exact_prior20_return.le(-0.15) | slow.last5_downside_turnover.le(0.01)
    )
    slow = slow.loc[
        slow.market_regime.eq("BEAR")
        & slow.market_median_ret20.ge(slow.market_median_ret60)
        & frozen_gate
    ].copy()
    slow["lane"] = "BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION"
    slow["rank1"] = slow.previous5_downside_turnover - slow.last5_downside_turnover
    slow["rank2"] = -slow.exact_prior20_return
    slow["rank3"] = slow.close_location

    columns = [
        "event_id", "symbol", "sleeve", "signal_date", "entry_date", "entry_cal_idx",
        "entry_price", "exit_date", "exit_cal_idx", "exit_price", "exit_reason",
        "holding_sessions", "gross_return", "net_return", "lane", "rank1", "rank2",
        "rank3", "market_regime", "market_median_ret20", "market_median_ret60",
        "latest_source_timestamp",
    ]
    frame = pd.concat([fast[columns], slow[columns]], ignore_index=True)
    frame = frame.sort_values(["signal_date", "lane", "event_id"], kind="mergesort").reset_index(drop=True)
    write_parquet(frame, output)
    return frame


def build_simple_bull(daily: Path, output: Path) -> pd.DataFrame:
    """Minimal extract of the frozen V29 Bull feature and mother-screen SQL."""
    query = f"""
    WITH a0 AS (
      SELECT *,lag(coord_close,20) OVER w AS lag20_close_exact,
        lag(coord_close,60) OVER w AS lag60_close_exact
      FROM read_parquet('{_sql_path(daily)}')
      WINDOW w AS(PARTITION BY symbol ORDER BY trade_date)
    ), v0 AS (
      SELECT *,max(coord_high) OVER w20 AS prior20_high,
        avg(turnover_fraction) OVER w20 AS prior20_turnover,
        sum((round(close*100)=round(up_limit_price*100))::INTEGER) OVER w20 AS prior20_limitups
      FROM a0 WHERE current_valid
      WINDOW w20 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
    ), base AS (
      SELECT *,coord_close/nullif(lag20_close_exact,0)-1 AS ret20,
        coord_close/nullif(lag60_close_exact,0)-1 AS ret60,
        coord_close/nullif(prior_coord_close,0)-1 AS step_return_v29,
        (coord_close-coord_low)/nullif(coord_high-coord_low,0) AS close_location,
        turnover_fraction/nullif(prior20_turnover,0) AS turnover_ratio
      FROM v0 WHERE hard_valid AND NOT is_st
    ), market AS (
      SELECT trade_date,count(*) AS market_n,avg((ret20>0)::INTEGER) AS market_breadth20,
        max(available_at) AS market_latest_source_timestamp FROM base GROUP BY trade_date
    ), industry0 AS (
      SELECT trade_date,causal_industry,count(*) AS industry_n,median(ret20) AS industry20,
        avg((ret20>0)::INTEGER) AS industry_breadth20,
        max(available_at) AS industry_latest_source_timestamp
      FROM base WHERE causal_industry IS NOT NULL GROUP BY trade_date,causal_industry
    ), industry AS (
      SELECT *,lag(industry_breadth20,5) OVER(PARTITION BY causal_industry ORDER BY trade_date)
        AS industry_breadth20_lag5 FROM industry0
    ), feature AS (
      SELECT b.*,m.market_n,m.market_breadth20,m.market_latest_source_timestamp,
        i.industry_n,i.industry20,i.industry_breadth20,i.industry_breadth20_lag5,
        i.industry_latest_source_timestamp,
        i.industry_breadth20-i.industry_breadth20_lag5 AS industry_breadth20_delta5,
        greatest(b.decision_at,m.market_latest_source_timestamp,i.industry_latest_source_timestamp)
          AS feature_latest_timestamp
      FROM base b JOIN market m USING(trade_date)
      JOIN industry i USING(trade_date,causal_industry)
    )
    SELECT * FROM feature WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
      AND hard_valid AND history_valid AND current_valid AND current_day_data_tradable
      AND trade_status=1 AND market_rule_valid AND corporate_action_valid
      AND NOT corporate_action_blocking AND coalesce(corporate_action_count,0)=0
      AND industry_valid AND historical_identity_valid AND available_at<=decision_at
      AND market_latest_source_timestamp<=decision_at AND industry_latest_source_timestamp<=decision_at
      AND round(close*100)<round(up_limit_price*100) AND market_breadth20>=0.65
      AND industry20>0.03 AND industry_breadth20>0.60 AND industry_breadth20_delta5>=0.25
      AND ret60 BETWEEN 0.00 AND 0.15 AND prior20_limitups=0 AND coord_close>prior20_high
      AND step_return_v29 BETWEEN 0.02 AND 0.06 AND close_location>=0.70
      AND turnover_ratio BETWEEN 1.50 AND 4.00
    ORDER BY symbol,cal_idx
    """
    con = duckdb.connect()
    con.execute("SET threads=4")
    try:
        raw = con.execute(query).fetchdf()
    finally:
        con.close()
    kept: list[int] = []
    for _, rows in raw.groupby("symbol", sort=False):
        last: int | None = None
        for index, cal_idx in zip(rows.index, rows.cal_idx, strict=True):
            current = int(cal_idx)
            if last is None or current - last >= 21:
                kept.append(int(index))
                last = current
    frame = raw.loc[kept].copy()
    frame["signal_date"] = pd.to_datetime(frame.trade_date)
    frame["event_id"] = "V29B|" + frame.signal_date.dt.strftime("%Y%m%d") + "|" + frame.symbol.astype(str)
    frame["lane"] = "SIMPLE_BULL_PARTICIPATION_IGNITION"
    frame = frame.sort_values(["signal_date", "event_id"], kind="mergesort").reset_index(drop=True)
    write_parquet(frame, output)
    return frame
