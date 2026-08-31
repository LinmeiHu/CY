#!/usr/bin/env python3
"""Run frozen Industry Rotation diversification and a second alpha discovery batch."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-DIVERSIFIED-CYCLE-002_spec.json"
PANEL_PATH = PROGRAM / "artifacts/ASHARE-DIVERSIFIED-CYCLE-002_candidate_panel.csv"
SUMMARY_PATH = PROGRAM / "artifacts/ASHARE-DIVERSIFIED-CYCLE-002_screen_summary.csv"
EQUITY_PATH = PROGRAM / "artifacts/ASHARE-DIVERSIFIED-CYCLE-002_equity.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-DIVERSIFIED-CYCLE-002_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-DIVERSIFIED-CYCLE-002_report.md"
EXPECTED_SPEC_SHA256 = "f35d9c0b660bcbfb92a68ea5efa7305f3d87aa324f50f14566de96945cabb658"
PRIOR_SCRIPT = PROGRAM / "scripts/run_ashare_indep_funnel_001.py"
START = date(2018, 1, 2)
END = date(2023, 12, 29)
SCREEN_COST = 0.002


class DiversifiedCycleError(RuntimeError):
    """Fail-closed error for ASHARE-DIVERSIFIED-CYCLE-002."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    return value


def _load_prior_module() -> Any:
    module_spec = importlib.util.spec_from_file_location("ashare_indep_funnel_001", PRIOR_SCRIPT)
    if module_spec is None or module_spec.loader is None:
        raise DiversifiedCycleError("cannot load prior frozen runner")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


PRIOR = _load_prior_module()


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise DiversifiedCycleError("cycle spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BOTH_TRACKS_BEFORE_FORWARD_OUTCOME_ACCESS":
        raise DiversifiedCycleError("both tracks were not frozen before outcomes")
    expected_families = [
        "stock_industry_residual_strength_20",
        "industry_diffusion_20",
        "negative_gap_recovery",
        "limit_up_aftermath",
        "price_volume_disagreement",
        "low_idiosyncratic_volatility_20",
        "lower_wick_demand_rejection",
    ]
    if list(spec["track_b_families"]) != expected_families:
        raise DiversifiedCycleError("Track-B family identity/order changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise DiversifiedCycleError(f"bound input changed: {name}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "same-bar", "habitat", "second Track-A"):
        if phrase not in prohibited:
            raise DiversifiedCycleError(f"missing prohibition: {phrase}")
    track_a = spec["track_a"]["single_translation"]
    if (
        track_a["leading_industries"] != 3
        or track_a["securities_per_industry"] != 5
        or spec["track_a"]["alpha_frozen"]["holding_sessions"] != 20
    ):
        raise DiversifiedCycleError("Track-A single translation changed")
    return spec


def _validate_inputs(spec: dict[str, Any]) -> tuple[list[Path], dict[str, Any]]:
    prior_spec = PRIOR._load_spec()
    paths, identity = PRIOR._validate_cy006(prior_spec)
    prior_result = json.loads(_resolve(spec["inputs"]["prior_funnel_result"]["path"]).read_text())
    industry = next(
        row
        for row in prior_result["promotion_decisions"]
        if row["family"] == "industry_rotation_20"
    )
    if (
        industry["classification"] != "SCREEN_ONLY_NO_PROMOTION"
        or industry["gate_results"]["severe_loss"]
        or not industry["gate_results"]["both_block_excess"]
    ):
        raise DiversifiedCycleError("prior Industry Rotation near-miss boundary changed")
    if prior_result["promoted_families"] or prior_result["executable_replays"]:
        raise DiversifiedCycleError("prior no-promotion boundary changed")
    return paths, identity


def _configure_connection(temp_path: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("SET memory_limit='6GB'")
    connection.execute("SET threads=2")
    connection.execute(f"SET temp_directory='{temp_path.as_posix()}'")
    connection.execute("SET preserve_insertion_order=false")
    return connection


def _build_domains(
    paths: list[Path], temp_path: Path
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[date], dict[str, Any]]:
    connection = _configure_connection(temp_path)
    connection.from_parquet([str(path) for path in paths], union_by_name=True).create_view("source")
    audit = connection.execute(
        """
        SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
               sum((available_at>decision_at)::INTEGER),
               sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER),
               sum((trade_date>DATE '2023-12-29')::INTEGER)
        FROM source
        """
    ).fetchone()
    input_audit = {
        "rows": int(audit[0]),
        "symbols": int(audit[1]),
        "first_date": str(audit[2]),
        "last_date": str(audit[3]),
        "time_travel_rows": int(audit[4]),
        "hard_valid_lineage_failures": int(audit[5]),
        "post_2023_rows_read": int(audit[6]),
    }
    if input_audit != {
        "rows": 6155390,
        "symbols": 5262,
        "first_date": "2018-01-02",
        "last_date": "2023-12-29",
        "time_travel_rows": 0,
        "hard_valid_lineage_failures": 0,
        "post_2023_rows_read": 0,
    }:
        raise DiversifiedCycleError(f"source audit changed: {input_audit}")
    connection.execute(
        """
        CREATE TEMP TABLE calendar AS
        SELECT trade_date,row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
        FROM (SELECT DISTINCT trade_date FROM source) ORDER BY trade_date
        """
    )
    calendar = [
        row[0]
        for row in connection.execute("SELECT trade_date FROM calendar ORDER BY cal_idx").fetchall()
    ]
    connection.execute(
        """
        CREATE TEMP TABLE base AS
        SELECT s.*,c.cal_idx,
          (s.hard_valid IS TRUE AND s.bar_valid IS TRUE
           AND s.trading_state_valid IS TRUE AND s.industry_valid IS TRUE
           AND s.float_valid IS TRUE AND s.corporate_action_valid IS TRUE
           AND s.market_valid IS TRUE AND s.market_rule_valid IS TRUE
           AND s.historical_identity_valid IS TRUE
           AND s.corporate_action_blocking IS FALSE
           AND coalesce(s.rights_ratio,0)=0
           AND s.available_at IS NOT NULL AND s.available_at<=s.decision_at
           AND s.open>0 AND s.high>=greatest(s.open,s.close)
           AND s.low<=least(s.open,s.close) AND s.close>0
           AND s.volume>=0 AND s.amount>=0) AS history_valid,
          (s.hard_valid IS TRUE AND s.trade_status=1
           AND s.current_day_data_tradable IS TRUE AND s.is_st IS FALSE) AS current_valid,
          lag(s.close) OVER w AS previous_close,
          lag(c.cal_idx) OVER w AS previous_cal_idx,
          lag(s.hard_valid IS TRUE AND s.bar_valid IS TRUE
              AND s.trading_state_valid IS TRUE AND s.industry_valid IS TRUE
              AND s.float_valid IS TRUE AND s.corporate_action_valid IS TRUE
              AND s.market_valid IS TRUE AND s.market_rule_valid IS TRUE
              AND s.historical_identity_valid IS TRUE
              AND s.corporate_action_blocking IS FALSE
              AND coalesce(s.rights_ratio,0)=0
              AND s.available_at IS NOT NULL AND s.available_at<=s.decision_at
              AND s.open>0 AND s.high>=greatest(s.open,s.close)
              AND s.low<=least(s.open,s.close) AND s.close>0
              AND s.volume>=0 AND s.amount>=0) OVER w AS previous_history_valid
        FROM source s JOIN calendar c USING(trade_date)
        WINDOW w AS (PARTITION BY s.symbol ORDER BY s.trade_date)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE steps AS
        SELECT *,CASE
          WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
           AND coalesce(corporate_action_count,0)=0
          THEN ln(close/previous_close)
          WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
           AND corporate_action_count>0
           AND corporate_action_available_date IS NOT NULL
           AND corporate_action_available_date<=trade_date
           AND coalesce(rights_ratio,0)=0 AND coalesce(share_multiplier,1)>0
           AND previous_close-coalesce(cash_per_share,0)>0
          THEN ln(close/((previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)))
          ELSE NULL END AS step_log_return
        FROM base
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE with_market AS
        SELECT *,median(step_log_return) OVER (PARTITION BY trade_date) AS market_median_step
        FROM steps
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE coordinates AS
        SELECT *,step_log_return-market_median_step AS residual_step,
          sum(coalesce(step_log_return,0)) OVER (
            PARTITION BY symbol ORDER BY trade_date ROWS UNBOUNDED PRECEDING
          ) AS log_coordinate
        FROM with_market
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE rolling AS
        SELECT *,exp(log_coordinate) AS coordinate_close,
          exp(log_coordinate)*open/close AS coordinate_open,
          exp(log_coordinate)*high/close AS coordinate_high,
          exp(log_coordinate)*low/close AS coordinate_low,
          lag(exp(log_coordinate)) OVER ws AS previous_coordinate_close,
          sum(step_log_return) OVER w5 AS r5,
          sum(step_log_return) OVER w20 AS r20,
          count(step_log_return) OVER w120 AS valid_steps120,
          lag(cal_idx,120) OVER ws AS cal_idx_lag120,
          avg(amount) OVER p20 AS avg_amount20,
          avg(volume) OVER p20 AS avg_volume20,
          count(*) OVER p20 AS prior_count20,
          count(residual_step) OVER w20 AS residual_count20,
          stddev_samp(residual_step) OVER w20 AS idio_vol20,
          sum(CASE WHEN step_log_return>0 THEN volume
                   WHEN step_log_return<0 THEN -volume ELSE 0 END) OVER w20
            / nullif(sum(volume) OVER w20,0) AS signed_volume_share20
        FROM coordinates
        WINDOW
          ws AS (PARTITION BY symbol ORDER BY trade_date),
          w5 AS (PARTITION BY symbol ORDER BY trade_date
                 ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
          w20 AS (PARTITION BY symbol ORDER BY trade_date
                  ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
          w120 AS (PARTITION BY symbol ORDER BY trade_date
                   ROWS BETWEEN 119 PRECEDING AND CURRENT ROW),
          p20 AS (PARTITION BY symbol ORDER BY trade_date
                  ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE eligible0 AS
        SELECT *,ln(coordinate_open/previous_coordinate_close) AS gap_return,
          ln(coordinate_close/coordinate_open) AS open_close_return,
          (least(open,close)-low)/nullif(high-low,0) AS lower_wick_share,
          (high-greatest(open,close))/nullif(high-low,0) AS upper_wick_share
        FROM rolling
        WHERE current_valid AND history_valid AND cal_idx>=120 AND cal_idx%5=4
          AND valid_steps120=120 AND cal_idx-cal_idx_lag120=120
          AND prior_count20=20 AND avg_amount20>=50000000 AND avg_volume20>0
          AND isfinite(r5) AND isfinite(r20) AND residual_count20=20
          AND isfinite(idio_vol20) AND isfinite(signed_volume_share20)
          AND previous_coordinate_close>0 AND coordinate_open>0
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE eligible AS
        SELECT *,count(*) OVER (PARTITION BY trade_date,industry) AS industry_count,
          (sum(r20) OVER (PARTITION BY trade_date,industry)-r20)
            / nullif(count(*) OVER (PARTITION BY trade_date,industry)-1,0)
              AS industry_loo_r20,
          (sum((r20>0)::INTEGER) OVER (PARTITION BY trade_date,industry)-(r20>0)::INTEGER)
            / nullif(count(*) OVER (PARTITION BY trade_date,industry)-1,0)
              AS industry_loo_positive_fraction20
        FROM eligible0
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE industry_state AS
        SELECT trade_date,industry,count(*) AS industry_count,avg(r20) AS industry_state_r20
        FROM eligible
        WHERE industry IS NOT NULL AND industry<>'' AND industry<>'UNKNOWN'
        GROUP BY trade_date,industry HAVING count(*)>=6
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE industry_ranked AS
        SELECT *,row_number() OVER (
          PARTITION BY trade_date ORDER BY industry_state_r20 DESC,industry
        ) AS industry_rank
        FROM industry_state
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE track_a_security_ranked AS
        SELECT e.*,i.industry_state_r20,i.industry_rank,
          row_number() OVER (
            PARTITION BY e.trade_date,e.industry ORDER BY e.avg_amount20 DESC,e.symbol
          ) AS liquidity_rank
        FROM eligible e JOIN industry_ranked i USING(trade_date,industry)
        WHERE i.industry_rank<=3
        """
    )
    track_a = connection.execute(
        """
        SELECT 'track_a_diversified' AS family,'top' AS leg,trade_date,cal_idx,
          decision_at,available_at,symbol,industry,industry_state_r20 AS signal_score,
          row_number() OVER (
            PARTITION BY trade_date ORDER BY industry_rank,liquidity_rank,symbol
          ) AS signal_rank,industry_count AS candidate_count,avg_amount20,
          r5,r20,industry_rank,liquidity_rank
        FROM track_a_security_ranked
        WHERE industry_rank<=3 AND liquidity_rank<=5
        UNION ALL
        SELECT 'track_a_concentrated','top',trade_date,cal_idx,decision_at,available_at,
          symbol,industry,industry_state_r20,
          row_number() OVER (
            PARTITION BY trade_date ORDER BY liquidity_rank,symbol
          ),industry_count,avg_amount20,r5,r20,industry_rank,liquidity_rank
        FROM track_a_security_ranked
        WHERE industry_rank=1 AND liquidity_rank<=15
        ORDER BY family,trade_date,signal_rank
        """
    ).fetchdf()
    connection.execute(
        """
        CREATE TEMP TABLE family_raw AS
        SELECT 'stock_industry_residual_strength_20' AS family,*,
          r20-industry_loo_r20 AS signal_score
        FROM eligible WHERE industry_count>=6 AND isfinite(industry_loo_r20)
        UNION ALL
        SELECT 'industry_diffusion_20',*,industry_loo_positive_fraction20
        FROM eligible WHERE industry_count>=6 AND isfinite(industry_loo_positive_fraction20)
        UNION ALL
        SELECT 'negative_gap_recovery',*,-gap_return+open_close_return
        FROM eligible WHERE gap_return<0 AND open_close_return>0
        UNION ALL
        SELECT 'limit_up_aftermath',*,avg_amount20
        FROM eligible WHERE close=up_limit_price
        UNION ALL
        SELECT 'price_volume_disagreement',*,signed_volume_share20-r20
        FROM eligible WHERE signed_volume_share20>0 AND r20<=0
        UNION ALL
        SELECT 'low_idiosyncratic_volatility_20',*,-idio_vol20
        FROM eligible WHERE residual_count20=20 AND idio_vol20>=0
        UNION ALL
        SELECT 'lower_wick_demand_rejection',*,lower_wick_share
        FROM eligible WHERE open_close_return>0 AND lower_wick_share>upper_wick_share
          AND isfinite(lower_wick_share)
        """
    )
    population = connection.execute(
        """
        SELECT family,trade_date,count(*) AS candidate_count,
          median(avg_amount20) AS median_avg_amount20
        FROM family_raw GROUP BY family,trade_date ORDER BY family,trade_date
        """
    ).fetchdf()
    connection.execute(
        """
        CREATE TEMP TABLE ranked AS
        SELECT *,count(*) OVER (PARTITION BY family,trade_date) AS candidate_count,
          row_number() OVER (
            PARTITION BY family,trade_date ORDER BY signal_score DESC,symbol
          ) AS rank_desc,
          row_number() OVER (
            PARTITION BY family,trade_date ORDER BY signal_score ASC,symbol
          ) AS rank_asc
        FROM family_raw WHERE isfinite(signal_score)
        """
    )
    track_b = connection.execute(
        """
        SELECT family,'top' AS leg,trade_date,cal_idx,decision_at,available_at,symbol,
          industry,signal_score,rank_desc AS signal_rank,candidate_count,avg_amount20,
          r5,r20,CAST(NULL AS BIGINT) AS industry_rank,CAST(NULL AS BIGINT) AS liquidity_rank
        FROM ranked WHERE rank_desc<=20
        UNION ALL
        SELECT family,'bottom',trade_date,cal_idx,decision_at,available_at,symbol,
          industry,signal_score,rank_asc,candidate_count,avg_amount20,r5,r20,NULL,NULL
        FROM ranked WHERE rank_asc<=20 AND family IN (
          'stock_industry_residual_strength_20','industry_diffusion_20',
          'low_idiosyncratic_volatility_20'
        )
        UNION ALL
        SELECT 'date_control','control',trade_date,cal_idx,decision_at,available_at,
          symbol,industry,CAST(NULL AS DOUBLE),control_rank,
          count(*) OVER (PARTITION BY trade_date),avg_amount20,r5,r20,NULL,NULL
        FROM (
          SELECT *,row_number() OVER (
            PARTITION BY trade_date ORDER BY
              sha256(symbol || '|002|' || strftime(trade_date,'%Y-%m-%d'))
          ) AS control_rank FROM eligible
        ) c WHERE control_rank<=20
        ORDER BY family,leg,trade_date,signal_rank,symbol
        """
    ).fetchdf()
    connection.close()
    expected = {
        "stock_industry_residual_strength_20",
        "industry_diffusion_20",
        "negative_gap_recovery",
        "limit_up_aftermath",
        "price_volume_disagreement",
        "low_idiosyncratic_volatility_20",
        "lower_wick_demand_rejection",
    }
    if set(population.family) != expected or set(track_b.family) != expected | {"date_control"}:
        raise DiversifiedCycleError("one or more Track-B families is not estimable")
    if track_a.groupby(["family", "trade_date"]).size().max() > 15:
        raise DiversifiedCycleError("Track-A portfolio breadth exceeds frozen design")
    selections = pd.concat([track_a, track_b], ignore_index=True).sort_values(
        ["family", "leg", "trade_date", "signal_rank", "symbol"]
    )
    if selections.duplicated(["family", "leg", "trade_date", "symbol"]).any():
        raise DiversifiedCycleError("duplicate selection key")
    return selections.reset_index(drop=True), population, track_a, calendar, input_audit


def _attach_screen_outcomes(
    paths: list[Path], selections: pd.DataFrame, calendar: list[date]
) -> tuple[pd.DataFrame, int]:
    links = PRIOR._future_links(selections, calendar)
    rows = PRIOR._query_path_rows(paths, links)
    return PRIOR._attach_outcomes(selections, rows), len(rows)


def _track_b_decisions(
    spec: dict[str, Any], summary: pd.DataFrame, panel: pd.DataFrame
) -> list[dict[str, Any]]:
    faux = {
        "families": spec["track_b_families"],
        "promotion": {
            "maximum_families": spec["track_b_promotion"]["maximum_families"],
            "all_required": spec["track_b_promotion"]["all_required"],
        },
    }
    return PRIOR._promotion_decisions(faux, summary, panel)


def _cohort_metrics(panel: pd.DataFrame, family: str, control_dates: pd.Series) -> dict[str, Any]:
    rows = panel.loc[(panel.family == family) & (panel.leg == "top")].copy()
    complete = rows.loc[rows.status_h20.eq("COMPLETE")]
    cohorts = complete.groupby("trade_date").agg(
        net_return=("net_return_h20", "mean"),
        names=("symbol", "size"),
        industries=("industry", "nunique"),
    )
    cohorts["control_return"] = cohorts.index.map(control_dates)
    cohorts["excess"] = cohorts.net_return - cohorts.control_return
    years = pd.to_datetime(cohorts.index).year
    early = years <= 2020
    late = years >= 2021
    annual_excess = cohorts.groupby(years).excess.mean()
    candidate_exec = rows.entry_status.eq("EXECUTABLE").mean()
    return {
        "complete_cohorts": len(cohorts),
        "mean_names": float(cohorts.names.mean()),
        "mean_industries": float(cohorts.industries.mean()),
        "entry_executable_fraction": float(candidate_exec),
        "full_mean_net_return": float(cohorts.net_return.mean()),
        "full_excess": float(cohorts.excess.mean()),
        "early_excess": float(cohorts.loc[early, "excess"].mean()),
        "late_excess": float(cohorts.loc[late, "excess"].mean()),
        "positive_years": int((annual_excess > 0).sum()),
        "severe_loss_fraction": float((cohorts.net_return <= -0.10).mean()),
        "control_severe_loss_fraction": float((cohorts.control_return <= -0.10).mean()),
        "severe_loss_disadvantage": float(
            (cohorts.net_return <= -0.10).mean() - (cohorts.control_return <= -0.10).mean()
        ),
    }


@dataclass
class Lot:
    symbol: str
    industry: str
    due_index: int
    shares: float
    invested_cost: float
    action_cash: float = 0.0


def _make_execution_plans(
    panel: pd.DataFrame,
    families: dict[str, int],
    calendar: list[date],
    names_per_signal: dict[str, int],
) -> pd.DataFrame:
    cal_index = {day: index for index, day in enumerate(calendar)}
    plans: list[dict[str, Any]] = []
    for family, horizon in families.items():
        rows = panel.loc[(panel.family == family) & (panel.leg == "top")]
        rows = rows.loc[rows.signal_rank <= names_per_signal[family]]
        for row in rows.itertuples(index=False):
            signal_date = pd.Timestamp(row.trade_date).date()
            entry_index = cal_index[signal_date] + 1
            due_index = entry_index + horizon
            if due_index >= len(calendar):
                continue
            plans.append(
                {
                    "family": family,
                    "signal_date": signal_date,
                    "symbol": row.symbol,
                    "industry": str(row.industry),
                    "entry_index": entry_index,
                    "due_index": due_index,
                    "horizon": horizon,
                }
            )
    return pd.DataFrame(plans)


def _query_execution_rows(
    paths: list[Path], plans: pd.DataFrame, calendar: list[date]
) -> pd.DataFrame:
    keys: set[tuple[str, date]] = set()
    for row in plans.itertuples(index=False):
        for index in range(int(row.entry_index), min(int(row.due_index) + 21, len(calendar))):
            keys.add((row.symbol, calendar[index]))
    key_frame = pd.DataFrame(sorted(keys), columns=["symbol", "trade_date"])
    connection = duckdb.connect()
    connection.register("needed_keys", key_frame)
    rows = connection.execute(
        """
        SELECT d.trade_date,d.symbol,d.open,d.close,d.amount,d.hard_valid,d.trade_status,
          d.current_day_data_tradable,d.buy_blocked_open,d.sell_blocked_open,
          d.corporate_action_count,d.corporate_action_valid,d.corporate_action_blocking,
          d.corporate_action_available_date,d.share_multiplier,d.cash_per_share,
          d.rights_ratio,d.available_at,d.invalid_reasons,d.corporate_action_problems,
          d.corporate_action_ids,d.corporate_action_snapshot_id
        FROM read_parquet(?) d JOIN needed_keys k USING(symbol,trade_date)
        ORDER BY d.trade_date,d.symbol
        """,
        [[str(path) for path in paths]],
    ).fetchdf()
    connection.close()
    if rows.duplicated(["symbol", "trade_date"]).any():
        raise DiversifiedCycleError("duplicate execution row")
    return rows


def _valid_market_row(row: Any) -> bool:
    return (
        bool(row.hard_valid)
        and pd.Timestamp(row.available_at).date() <= pd.Timestamp(row.trade_date).date()
        and math.isfinite(float(row.open))
        and float(row.open) > 0
        and math.isfinite(float(row.close))
        and float(row.close) > 0
    )


def _replay(
    family: str,
    plans: pd.DataFrame,
    market_rows: pd.DataFrame,
    calendar: list[date],
    *,
    industry_balanced: bool,
) -> tuple[dict[str, Any], pd.DataFrame]:
    family_plans = plans.loc[plans.family == family]
    if family_plans.empty:
        raise DiversifiedCycleError(f"no execution plans: {family}")
    row_map = {
        (row.symbol, pd.Timestamp(row.trade_date).date()): row
        for row in market_rows.itertuples(index=False)
    }
    entry_map = {
        int(index): list(group.itertuples(index=False))
        for index, group in family_plans.groupby("entry_index", sort=True)
    }
    horizon = int(family_plans.horizon.iloc[0])
    vintages = math.ceil(horizon / 5)
    initial = 10_000_000.0
    cost = SCREEN_COST
    cash = initial
    lots: list[Lot] = []
    turnover = 0.0
    entries = 0
    planned_entries = 0
    blocked_exit_delays = 0
    severe_trades = 0
    completed_trades = 0
    nav_rows: list[dict[str, Any]] = []
    capacity: list[float] = []
    start_index = int(family_plans.entry_index.min())
    final_due = int(family_plans.due_index.max())
    final_index = min(final_due + 20, len(calendar) - 1)

    def blocked_result(
        lot: Lot, row: Any | None, reason: str
    ) -> tuple[dict[str, Any], pd.DataFrame]:
        blocker = {
            "reason": reason,
            "symbol": lot.symbol,
            "trade_date": str(trade_date_value),
            "industry": lot.industry,
            "hard_valid": None if row is None else bool(row.hard_valid),
            "corporate_action_blocking": (
                None if row is None else bool(row.corporate_action_blocking)
            ),
            "corporate_action_available_date": (
                None
                if row is None or pd.isna(row.corporate_action_available_date)
                else str(pd.Timestamp(row.corporate_action_available_date).date())
            ),
            "invalid_reasons": None if row is None else str(row.invalid_reasons),
            "corporate_action_problems": (
                None if row is None else str(row.corporate_action_problems)
            ),
            "corporate_action_ids": (
                None if row is None else str(row.corporate_action_ids)
            ),
            "corporate_action_snapshot_id": (
                None if row is None else str(row.corporate_action_snapshot_id)
            ),
        }
        partial = pd.DataFrame(nav_rows)
        return (
            {
                "family": family,
                "status": "BLOCKED_DATA_CONTRACT",
                "cost_per_side_bps": 20,
                "blocker": blocker,
                "planned_entries_before_block": planned_entries,
                "entries_before_block": entries,
                "completed_trades_before_block": completed_trades,
                "terminal_open_lots": len(lots),
                "partial_equity_is_not_strategy_economics": True,
            },
            partial,
        )

    for index in range(start_index, final_index + 1):
        trade_date_value = calendar[index]
        for lot in lots:
            row = row_map.get((lot.symbol, trade_date_value))
            if row is not None and int(row.corporate_action_count or 0) > 0:
                action = PRIOR._visible_action(row)
                if action is None:
                    return blocked_result(lot, row, "UNRESOLVED_CORPORATE_ACTION")
                multiplier, cash_per_share = action
                lot.action_cash += lot.shares * cash_per_share
                lot.shares *= multiplier
            if row is None or not _valid_market_row(row):
                return blocked_result(lot, row, "INVALID_OR_MISSING_HOLDING_ROW")
        survivors: list[Lot] = []
        for lot in lots:
            if index < lot.due_index:
                survivors.append(lot)
                continue
            row = row_map[(lot.symbol, trade_date_value)]
            can_sell = (
                int(row.trade_status) == 1
                and bool(row.current_day_data_tradable)
                and not bool(row.sell_blocked_open)
            )
            if not can_sell:
                blocked_exit_delays += 1
                survivors.append(lot)
                continue
            gross = lot.shares * float(row.open)
            proceeds = lot.action_cash + gross * (1.0 - cost)
            cash += proceeds
            turnover += gross
            completed_trades += 1
            severe_trades += int(proceeds / lot.invested_cost - 1.0 <= -0.10)
        lots = survivors
        pre_entry_nav = cash
        for lot in lots:
            row = row_map[(lot.symbol, trade_date_value)]
            pre_entry_nav += lot.action_cash + lot.shares * float(row.open)
        planned = entry_map.get(index, [])
        planned_entries += len(planned)
        executable: list[tuple[Any, Any]] = []
        for plan in planned:
            row = row_map.get((plan.symbol, trade_date_value))
            if row is None or not _valid_market_row(row):
                continue
            if (
                int(row.trade_status) == 1
                and bool(row.current_day_data_tradable)
                and not bool(row.buy_blocked_open)
            ):
                executable.append((plan, row))
        cohort_capital = min(cash, pre_entry_nav / vintages)
        allocations: list[tuple[Any, Any, float]] = []
        if executable and industry_balanced:
            industries = sorted({str(plan.industry) for plan, _ in executable})
            fixed_industry_count = 3
            for industry in industries:
                members = [
                    (plan, row) for plan, row in executable if str(plan.industry) == industry
                ]
                per_name = cohort_capital / fixed_industry_count / len(members)
                allocations.extend((plan, row, per_name) for plan, row in members)
        elif executable:
            per_name = cohort_capital / len(executable)
            allocations = [(plan, row, per_name) for plan, row in executable]
        for plan, row, allocation in allocations:
            shares = allocation / (float(row.open) * (1.0 + cost))
            gross = shares * float(row.open)
            invested_cost = gross * (1.0 + cost)
            cash -= invested_cost
            turnover += gross
            lots.append(
                Lot(plan.symbol, str(plan.industry), int(plan.due_index), shares, invested_cost)
            )
            entries += 1
            capacity.append(float(row.amount) * 0.05 * max(1, len(executable)) * vintages)
        nav = cash
        industry_values: dict[str, float] = {}
        for lot in lots:
            row = row_map[(lot.symbol, trade_date_value)]
            value = lot.action_cash + lot.shares * float(row.close)
            nav += value
            industry_values[lot.industry] = industry_values.get(lot.industry, 0.0) + value
        invested = sum(industry_values.values())
        hhi = (
            sum((value / invested) ** 2 for value in industry_values.values())
            if invested > 0
            else 0.0
        )
        nav_rows.append(
            {
                "trade_date": trade_date_value,
                "family": family,
                "nav": nav,
                "cash": cash,
                "positions": len(lots),
                "industries": len(industry_values),
                "industry_hhi": hhi,
            }
        )
        if index >= final_due and not lots and index not in entry_map:
            break
    equity = pd.DataFrame(nav_rows)
    returns = equity.nav.pct_change().fillna(equity.nav.iloc[0] / initial - 1.0)
    drawdown = equity.nav / equity.nav.cummax() - 1.0
    years = len(equity) / 252.0
    annualized = (equity.nav.iloc[-1] / initial) ** (1.0 / years) - 1.0
    volatility = returns.std(ddof=1)
    sharpe = math.sqrt(252.0) * returns.mean() / volatility if volatility > 0 else 0.0
    max_drawdown = float(drawdown.min())
    result = {
        "family": family,
        "status": "COMPLETE",
        "cost_per_side_bps": 20,
        "start_date": str(equity.trade_date.iloc[0]),
        "end_date": str(equity.trade_date.iloc[-1]),
        "total_return": float(equity.nav.iloc[-1] / initial - 1.0),
        "annualized_return": float(annualized),
        "maximum_drawdown": max_drawdown,
        "daily_sharpe": float(sharpe),
        "calmar": float(annualized / abs(max_drawdown)) if max_drawdown < 0 else None,
        "turnover_multiple_initial_capital": float(turnover / initial),
        "planned_entries": planned_entries,
        "entries": entries,
        "entry_execution_fraction": float(entries / planned_entries),
        "completed_trades": completed_trades,
        "severe_trade_fraction": float(severe_trades / completed_trades),
        "blocked_exit_delays": blocked_exit_delays,
        "terminal_open_lots": len(lots),
        "mean_positions": float(equity.positions.mean()),
        "mean_industries": float(equity.industries.mean()),
        "mean_industry_hhi_invested_days": float(
            equity.loc[equity.positions > 0, "industry_hhi"].mean()
        ),
        "p10_capacity_cny_at_5pct_amount": float(np.quantile(capacity, 0.10)),
        "median_capacity_cny_at_5pct_amount": float(np.median(capacity)),
    }
    return result, equity


def _track_a_decision(
    spec: dict[str, Any],
    cohort: dict[str, Any],
    diversified: dict[str, Any],
    concentrated: dict[str, Any],
) -> dict[str, Any]:
    gates = spec["track_a"]["promotion_all_required"]
    if diversified["status"] != "COMPLETE" or concentrated["status"] != "COMPLETE":
        return {
            "status": "PARKED",
            "reason": "EXECUTABLE_TRANSLATION_BLOCKED_BY_FROZEN_DATA_CONTRACT",
            "gate_results": {"complete_executable_replay": False},
            "cohort_economics": cohort,
            "diversified_portfolio": diversified,
            "concentrated_control": concentrated,
            "drawdown_improvement": None,
            "sharpe_difference": None,
        }
    gate_results = {
        "complete_cohorts": cohort["complete_cohorts"] >= gates["minimum_complete_cohorts"],
        "entry_executability": cohort["entry_executable_fraction"]
        >= gates["minimum_entry_executable_fraction"],
        "full_excess": cohort["full_excess"]
        >= gates["minimum_full_cohort_net_excess_vs_date_control"],
        "both_block_excess": min(cohort["early_excess"], cohort["late_excess"])
        >= gates["minimum_each_block_cohort_net_excess_vs_date_control"],
        "positive_years": cohort["positive_years"] >= gates["minimum_positive_calendar_years"],
        "cohort_severe_loss": cohort["severe_loss_disadvantage"]
        <= gates["maximum_cohort_severe_loss_disadvantage_vs_control"],
        "industry_hhi": diversified["mean_industry_hhi_invested_days"]
        <= gates["maximum_diversified_industry_hhi"],
        "drawdown_improvement": diversified["maximum_drawdown"] - concentrated["maximum_drawdown"]
        >= gates["minimum_drawdown_improvement_vs_concentrated"],
        "sharpe_improvement": diversified["daily_sharpe"] - concentrated["daily_sharpe"]
        >= gates["minimum_sharpe_difference_vs_concentrated"],
        "positive_total_return": diversified["total_return"] >= gates["minimum_total_return"],
    }
    return {
        "status": "STRATEGY_CANDIDATE" if all(gate_results.values()) else "PARKED",
        "gate_results": gate_results,
        "cohort_economics": cohort,
        "diversified_portfolio": diversified,
        "concentrated_control": concentrated,
        "drawdown_improvement": diversified["maximum_drawdown"] - concentrated["maximum_drawdown"],
        "sharpe_difference": diversified["daily_sharpe"] - concentrated["daily_sharpe"],
    }


def _render_report(result: dict[str, Any]) -> str:
    track_a = result["track_a"]
    lines = [
        "# Industry-rotation translation and second independent discovery cycle",
        "",
        "## Research decisions",
        "",
        f"Track A final status: **{track_a['status']}**.",
        "",
        (
            "Track A keeps the exact 20-session PIT industry state and weekly clock. "
            "The only candidate allocates one third to each of the top three industries "
            "and one fifteenth to each of five liquidity-ranked securities per industry."
        ),
        "",
        (
            "| Translation | Total return | Annualized | Max DD | Sharpe | Calmar | "
            "Severe trades | Turnover | Mean industry HHI |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    track_a_blockers: list[str] = []
    for label, key in (
        ("Diversified 3x5", "diversified_portfolio"),
        ("Concentrated 1x15 control", "concentrated_control"),
    ):
        row = track_a[key]
        if row["status"] == "COMPLETE":
            lines.append(
                f"| {label} | {row['total_return']:.2%} | {row['annualized_return']:.2%} | "
                f"{row['maximum_drawdown']:.2%} | {row['daily_sharpe']:.3f} | "
                f"{row['calmar']:.3f} | {row['severe_trade_fraction']:.2%} | "
                f"{row['turnover_multiple_initial_capital']:.2f}x | "
                f"{row['mean_industry_hhi_invested_days']:.3f} |"
            )
        else:
            blocker = row["blocker"]
            lines.append(
                f"| {label} | DATA CONTRACT BLOCK | -- | -- | -- | -- | -- | -- | -- |"
            )
            track_a_blockers.append(
                f"{label} stopped before valuation on {blocker['trade_date']} for "
                f"{blocker['symbol']}: {blocker['reason']} "
                f"({blocker['corporate_action_problems']}). Partial equity is not economics."
            )
    cohort = track_a["cohort_economics"]
    lines.extend(
        [
            "",
            *track_a_blockers,
            "",
            f"Diversified cohort excess is {cohort['full_excess']:.3%} full, "
            f"{cohort['early_excess']:.3%} early, and {cohort['late_excess']:.3%} late. "
            f"Its severe cohort disadvantage is {cohort['severe_loss_disadvantage']:.3%}.",
            "",
            "## Track B cheap screen",
            "",
            (
                "| Family | N | Horizon | Full excess | Early | Late | Severe disadvantage | "
                "Entry executable | Decision |"
            ),
            "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in result["track_b_decisions"]:
        detail = result["track_b_details"][row["family"]]
        lines.append(
            f"| {row['family']} | {row['complete_top_outcomes']:,} | {row['natural_horizon']} | "
            f"{row['full_excess']:.3%} | {detail['early_excess']:.3%} | "
            f"{detail['late_excess']:.3%} | {row['severe_loss_disadvantage']:.3%} | "
            f"{detail['entry_executable_fraction']:.2%} | {row['classification']} |"
        )
    lines.extend(["", "## Executable Track-B strategies", ""])
    if result["track_b_replays"]:
        lines.extend(
            [
                (
                    "| Family | Total return | Annualized | Max DD | Sharpe | Calmar | "
                    "Severe trades | Turnover | Entries | Capacity p10 |"
                ),
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        track_b_blockers: list[str] = []
        for row in result["track_b_replays"]:
            if row["status"] == "COMPLETE":
                lines.append(
                    f"| {row['family']} | {row['total_return']:.2%} | "
                    f"{row['annualized_return']:.2%} | {row['maximum_drawdown']:.2%} | "
                    f"{row['daily_sharpe']:.3f} | {row['calmar']:.3f} | "
                    f"{row['severe_trade_fraction']:.2%} | "
                    f"{row['turnover_multiple_initial_capital']:.2f}x | {row['entries']} | "
                    f"{row['p10_capacity_cny_at_5pct_amount']:,.0f} |"
                )
            else:
                blocker = row["blocker"]
                lines.append(
                    f"| {row['family']} | DATA CONTRACT BLOCK | -- | -- | -- | -- | -- | "
                    f"{row['entries_before_block']} | -- |"
                )
                track_b_blockers.append(
                    f"Replay stopped on {blocker['trade_date']} for {blocker['symbol']}: "
                    f"{blocker['reason']}. Partial equity is not strategy economics."
                )
        lines.extend(["", *track_b_blockers])
    else:
        lines.append("No Track-B family passed every frozen promotion gate.")
    lines.extend(
        [
            "",
            "## Boundaries and next allocation",
            "",
            result["portfolio_synthesis"],
            "",
            (
                "All 2018--2023 observations are consumed development history. Post-2023 "
                "data and CY-011 were not read. No result is OOS, validation, or live evidence."
            ),
            "",
            f"- Frozen spec: `{result['hashes']['spec_sha256']}`",
            f"- Candidate panel: `{result['hashes']['panel_sha256']}`",
            f"- Screen summary: `{result['hashes']['summary_sha256']}`",
            f"- Equity artifact: `{result['hashes']['equity_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    paths, input_identity = _validate_inputs(spec)
    with tempfile.TemporaryDirectory(prefix="ashare-diversified-002-") as temporary:
        selections, population, _track_a_raw, calendar, input_audit = _build_domains(
            paths, Path(temporary)
        )
        panel, path_rows = _attach_screen_outcomes(paths, selections, calendar)
    summary = PRIOR._screen_summary(panel)
    track_b_panel = panel.loc[panel.family.isin([*spec["track_b_families"], "date_control"])].copy()
    decisions = _track_b_decisions(spec, summary, track_b_panel)
    promoted = [
        row["family"]
        for row in decisions
        if row["classification"] == "PROMOTE_EXECUTABLE_TRANSLATION"
    ]
    control = panel.loc[(panel.family == "date_control") & panel.status_h20.eq("COMPLETE")]
    control_dates = control.groupby("trade_date").net_return_h20.mean()
    diversified_cohorts = _cohort_metrics(panel, "track_a_diversified", control_dates)
    execution_families = {
        "track_a_diversified": 20,
        "track_a_concentrated": 20,
        **{
            family: int(spec["track_b_families"][family]["natural_horizon_sessions"])
            for family in promoted
        },
    }
    names_per_signal = {
        "track_a_diversified": 15,
        "track_a_concentrated": 15,
        **{family: 10 for family in promoted},
    }
    plans = _make_execution_plans(panel, execution_families, calendar, names_per_signal)
    market_rows = _query_execution_rows(paths, plans, calendar)
    diversified, diversified_equity = _replay(
        "track_a_diversified", plans, market_rows, calendar, industry_balanced=True
    )
    concentrated, concentrated_equity = _replay(
        "track_a_concentrated", plans, market_rows, calendar, industry_balanced=False
    )
    track_a_decision = _track_a_decision(spec, diversified_cohorts, diversified, concentrated)
    track_b_replays: list[dict[str, Any]] = []
    equity_frames = [diversified_equity, concentrated_equity]
    for family in promoted:
        replay, equity = _replay(family, plans, market_rows, calendar, industry_balanced=False)
        track_b_replays.append(replay)
        equity_frames.append(equity)
    natural_map = {
        **{
            name: int(value["natural_horizon_sessions"])
            for name, value in spec["track_b_families"].items()
        },
        "track_a_diversified": 20,
        "track_a_concentrated": 20,
    }
    compact = panel.loc[panel.leg == "top"].copy()
    compact["natural_horizon"] = compact.family.map(natural_map)
    compact["natural_status"] = [
        row[f"status_h{int(row.natural_horizon)}"] for _, row in compact.iterrows()
    ]
    compact["natural_net_return"] = [
        row[f"net_return_h{int(row.natural_horizon)}"] for _, row in compact.iterrows()
    ]
    compact_columns = [
        "family",
        "trade_date",
        "decision_at",
        "available_at",
        "symbol",
        "industry",
        "signal_score",
        "signal_rank",
        "candidate_count",
        "avg_amount20",
        "industry_rank",
        "liquidity_rank",
        "natural_horizon",
        "entry_status",
        "natural_status",
        "natural_net_return",
    ]
    _atomic_write(
        PANEL_PATH,
        compact[compact_columns].to_csv(index=False, lineterminator="\n", float_format="%.10g"),
    )
    _atomic_write(
        SUMMARY_PATH,
        summary.to_csv(index=False, lineterminator="\n", float_format="%.10g"),
    )
    equity_output = pd.concat(equity_frames, ignore_index=True).sort_values(
        ["family", "trade_date"]
    )
    _atomic_write(
        EQUITY_PATH,
        equity_output.to_csv(index=False, lineterminator="\n", float_format="%.10g"),
    )
    details: dict[str, Any] = {}
    for row in decisions:
        family = row["family"]
        horizon = row["natural_horizon"]
        subset = summary.loc[
            (summary.family == family) & (summary.leg == "top") & (summary.horizon == horizon)
        ].set_index("period")
        full = subset.loc["full"]
        details[family] = {
            "early_excess": float(subset.loc["early_2018_2020", "mean_excess_vs_date_control"]),
            "late_excess": float(subset.loc["late_2021_2023", "mean_excess_vs_date_control"]),
            "entry_executable_fraction": float(full.entry_executable_fraction),
            "median_candidate_count": float(full.median_candidate_count),
            "median_avg_amount20_cny": float(full.median_avg_amount20_cny),
        }
    ranked = [
        row["family"]
        for row in sorted(
            decisions,
            key=lambda item: (item["minimum_block_excess"], item["full_excess"]),
            reverse=True,
        )
    ]
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_EXPLORE_ONLY",
        "claim_boundary": spec["claim_boundary"],
        "input_identity": input_identity,
        "input_audit": input_audit,
        "domain": {
            "track_b_families": len(spec["track_b_families"]),
            "decision_dates": int(population.trade_date.nunique()),
            "selected_top_rows": int((panel.leg == "top").sum()),
            "screen_path_rows": path_rows,
            "execution_market_rows": len(market_rows),
        },
        "track_a": track_a_decision,
        "track_b_decisions": decisions,
        "track_b_details": details,
        "track_b_ranked_frontier": ranked,
        "track_b_promoted": promoted,
        "track_b_replays": track_b_replays,
        "portfolio_synthesis": (
            "Track A receives no rescue. The highest expected-information next unit is one "
            "separately frozen, shared execution-contract study binding registered QD-010 "
            "announcement timing and pre-effective risk exits, while leaving both promoted "
            "alphas unchanged. If that cannot be made PIT-safe compactly, park both leads and "
            "allocate to independent stock-level intraday mechanisms. Frozen CHINEXT "
            "components remain unchanged."
        ),
        "boundaries": {
            "post_2023_read": False,
            "cy011_read": False,
            "chinext_changed": False,
            "prior_formulations_rerun": False,
            "oos_claim": False,
            "validation_claim": False,
            "live_claim": False,
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "panel_sha256": sha256_file(PANEL_PATH),
            "summary_sha256": sha256_file(SUMMARY_PATH),
            "equity_sha256": sha256_file(EQUITY_PATH),
        },
    }
    report = _render_report(result)
    _atomic_write(REPORT_PATH, report)
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
