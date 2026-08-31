#!/usr/bin/env python3
"""Run the frozen cheap independent A-share strategy-family discovery funnel."""

from __future__ import annotations

import hashlib
import json
import math
import os
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
SPEC_PATH = PROGRAM / "experiments/ASHARE-INDEP-FUNNEL-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/ASHARE-INDEP-FUNNEL-001_candidate_panel.csv"
SUMMARY_PATH = PROGRAM / "artifacts/ASHARE-INDEP-FUNNEL-001_screen_summary.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-INDEP-FUNNEL-001_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-INDEP-FUNNEL-001_discovery.md"
EXPECTED_SPEC_SHA256 = "5155f8fede9e5a5025bc087ae09746de1bee4cdf1c5d6e7427fecdea89b0c4b6"
START = date(2018, 1, 2)
END = date(2023, 12, 29)
SCREEN_COST = 0.002
MAX_RESPONSE_HORIZON = 20
DUCKDB_MEMORY_LIMIT = "6GB"
DUCKDB_THREADS = 2


class IndependentFunnelError(RuntimeError):
    """Fail-closed independent-family funnel error."""


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


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise IndependentFunnelError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_FORWARD_OUTCOME_ACCESS":
        raise IndependentFunnelError("spec is not frozen before outcomes")
    if list(spec["families"]) != [
        "momentum_60",
        "short_reversal_5",
        "breakout_60",
        "failed_breakdown_20",
        "demand_volume_shock",
        "compression_breakout",
        "industry_rotation_20",
    ]:
        raise IndependentFunnelError("family identity or order changed")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "same-bar", "habitat"):
        if phrase not in prohibited:
            raise IndependentFunnelError(f"missing prohibition: {phrase}")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise IndependentFunnelError(f"bound input changed: {name}")
    return spec


def _validate_cy006(spec: dict[str, Any]) -> tuple[list[Path], dict[str, Any]]:
    registry = json.loads(_resolve(spec["inputs"]["data_asset_registry"]["path"]).read_text())
    assets = {row["asset_id"]: row for row in registry["assets"]}
    asset = assets.get("CY-006")
    if (
        asset is None
        or asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or asset.get("physical_state") != "MATERIALIZED"
        or not asset.get("quality_evidence", {}).get("gate_pass")
    ):
        raise IndependentFunnelError("CY-006 registry activation changed")
    if (
        "daily causal state generation with row-level hard_valid enforcement"
        not in asset["allowed_uses"]
    ):
        raise IndependentFunnelError("CY-006 allowed-use contract changed")
    manifest_path = _resolve(spec["inputs"]["cy006_manifest"]["path"])
    manifest = json.loads(manifest_path.read_text())
    root = Path(manifest["root"])
    by_year = {
        int(row["path"].split("partition_year=")[1].split("/")[0]): row for row in manifest["files"]
    }
    paths: list[Path] = []
    identities: list[dict[str, Any]] = []
    for year in range(START.year, END.year + 1):
        binding = by_year.get(year)
        if binding is None:
            raise IndependentFunnelError(f"CY-006 manifest lacks {year}")
        path = root / binding["path"]
        if (
            not path.is_file()
            or path.stat().st_size != int(binding["size"])
            or sha256_file(path) != binding["sha256"]
        ):
            raise IndependentFunnelError(f"CY-006 partition mismatch: {year}")
        paths.append(path)
        identities.append(
            {
                "year": year,
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": binding["sha256"],
            }
        )
    return paths, {
        "asset_id": "CY-006",
        "manifest_sha256": sha256_file(manifest_path),
        "partitions": identities,
    }


def _configure_connection(temp_path: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'")
    connection.execute(f"SET threads={DUCKDB_THREADS}")
    connection.execute(f"SET temp_directory='{temp_path.as_posix()}'")
    connection.execute("SET preserve_insertion_order=false")
    return connection


def _build_signal_domain(
    paths: list[Path], temp_path: Path
) -> tuple[pd.DataFrame, pd.DataFrame, list[date], dict[str, Any]]:
    connection = _configure_connection(temp_path)
    connection.from_parquet([str(path) for path in paths], union_by_name=True).create_view("source")
    audit = connection.execute(
        """
        SELECT count(*) AS rows,count(DISTINCT symbol) AS symbols,
               min(trade_date) AS first_date,max(trade_date) AS last_date,
               sum((available_at>decision_at)::INTEGER) AS time_travel_rows,
               sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER)
                 AS hard_valid_lineage_failures,
               sum((trade_date>DATE '2023-12-29')::INTEGER) AS post_2023_rows
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
    if (
        input_audit["first_date"] != START.isoformat()
        or input_audit["last_date"] != END.isoformat()
        or input_audit["time_travel_rows"]
        or input_audit["hard_valid_lineage_failures"]
        or input_audit["post_2023_rows_read"]
    ):
        raise IndependentFunnelError(f"CY-006 row audit failed: {input_audit}")
    connection.execute(
        """
        CREATE TEMP TABLE calendar AS
        SELECT trade_date,row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
        FROM (SELECT DISTINCT trade_date FROM source)
        ORDER BY trade_date
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
           AND s.current_day_data_tradable IS TRUE
           AND s.is_st IS FALSE) AS current_valid,
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
        CREATE TEMP TABLE coordinates AS
        SELECT *,sum(coalesce(step_log_return,0)) OVER (
                 PARTITION BY symbol ORDER BY trade_date ROWS UNBOUNDED PRECEDING
               ) AS log_coordinate
        FROM steps
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE rolling AS
        SELECT *,
          exp(log_coordinate) AS coordinate_close,
          exp(log_coordinate)*high/close AS coordinate_high,
          exp(log_coordinate)*low/close AS coordinate_low,
          sum(step_log_return) OVER w5 AS r5,
          sum(step_log_return) OVER w20 AS r20,
          sum(step_log_return) OVER w60 AS r60,
          count(step_log_return) OVER w120 AS valid_steps120,
          lag(cal_idx,120) OVER ws AS cal_idx_lag120,
          max(exp(log_coordinate)*high/close) OVER p20 AS prior_high20,
          min(exp(log_coordinate)*low/close) OVER p20 AS prior_low20,
          max(exp(log_coordinate)*high/close) OVER p60 AS prior_high60,
          avg(amount) OVER p20 AS avg_amount20,
          avg(volume) OVER p20 AS avg_volume20,
          count(*) OVER p20 AS prior_count20,
          count(*) OVER p60 AS prior_count60
        FROM coordinates
        WINDOW
          ws AS (PARTITION BY symbol ORDER BY trade_date),
          w5 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
          w20 AS (PARTITION BY symbol ORDER BY trade_date
                  ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
          w60 AS (PARTITION BY symbol ORDER BY trade_date
                  ROWS BETWEEN 59 PRECEDING AND CURRENT ROW),
          w120 AS (PARTITION BY symbol ORDER BY trade_date
                   ROWS BETWEEN 119 PRECEDING AND CURRENT ROW),
          p20 AS (PARTITION BY symbol ORDER BY trade_date
                  ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
          p60 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE eligible0 AS
        SELECT *,prior_high20/prior_low20-1 AS range20,
               coordinate_close/prior_high20-1 AS breakout20_margin,
               coordinate_close/prior_high60-1 AS breakout60_margin,
               step_log_return AS r1
        FROM rolling
        WHERE current_valid AND history_valid AND cal_idx>=120 AND cal_idx%5=4
          AND valid_steps120=120 AND cal_idx-cal_idx_lag120=120
          AND prior_count20=20 AND prior_count60=60
          AND avg_amount20>=50000000 AND avg_volume20>0
          AND isfinite(r5) AND isfinite(r20) AND isfinite(r60)
          AND prior_high20>0 AND prior_low20>0 AND prior_high60>0
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE eligible AS
        SELECT *,percent_rank() OVER (PARTITION BY trade_date ORDER BY range20,symbol)
                   AS range20_percentile,
               count(*) OVER (PARTITION BY trade_date,industry) AS industry_count,
               (sum(r20) OVER (PARTITION BY trade_date,industry)-r20)
                 / nullif(count(*) OVER (PARTITION BY trade_date,industry)-1,0)
                   AS industry_loo_r20
        FROM eligible0
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE family_raw AS
        SELECT 'momentum_60' AS family,*,r60 AS signal_score FROM eligible
        UNION ALL
        SELECT 'short_reversal_5',*,-r5 FROM eligible
        UNION ALL
        SELECT 'breakout_60',*,breakout60_margin FROM eligible WHERE breakout60_margin>0
        UNION ALL
        SELECT 'failed_breakdown_20',*,
          (prior_low20-coordinate_low)/prior_low20+(coordinate_close-prior_low20)/prior_low20
        FROM eligible WHERE coordinate_low<prior_low20 AND coordinate_close>prior_low20
        UNION ALL
        SELECT 'demand_volume_shock',*,r1*ln(volume/avg_volume20)
        FROM eligible WHERE r1>0 AND volume>avg_volume20
        UNION ALL
        SELECT 'compression_breakout',*,-range20+breakout20_margin
        FROM eligible WHERE range20_percentile<=0.20 AND breakout20_margin>0
        UNION ALL
        SELECT 'industry_rotation_20',*,industry_loo_r20
        FROM eligible WHERE industry IS NOT NULL AND industry<>'' AND industry<>'UNKNOWN'
          AND industry_count>=6 AND isfinite(industry_loo_r20)
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
    selections = connection.execute(
        """
        SELECT family,'top' AS leg,trade_date,cal_idx,decision_at,available_at,symbol,
               industry,signal_score,rank_desc AS signal_rank,candidate_count,
               avg_amount20,range20,r5,r20,r60,breakout20_margin,breakout60_margin
        FROM ranked WHERE rank_desc<=20
        UNION ALL
        SELECT family,'bottom',trade_date,cal_idx,decision_at,available_at,symbol,
               industry,signal_score,rank_asc,candidate_count,
               avg_amount20,range20,r5,r20,r60,breakout20_margin,breakout60_margin
        FROM ranked WHERE rank_asc<=20
          AND family IN ('momentum_60','short_reversal_5','industry_rotation_20')
        UNION ALL
        SELECT 'date_control','control',trade_date,cal_idx,decision_at,available_at,symbol,
               industry,CAST(NULL AS DOUBLE),control_rank,count(*) OVER (PARTITION BY trade_date),
               avg_amount20,range20,r5,r20,r60,breakout20_margin,breakout60_margin
        FROM (
          SELECT *,row_number() OVER (
            PARTITION BY trade_date ORDER BY
              sha256(symbol || '|' || strftime(trade_date,'%Y-%m-%d'))
          ) AS control_rank
          FROM eligible
        ) c WHERE control_rank<=20
        ORDER BY family,leg,trade_date,signal_rank,symbol
        """
    ).fetchdf()
    connection.close()
    if selections.duplicated(["family", "leg", "trade_date", "symbol"]).any():
        raise IndependentFunnelError("duplicate selected candidate")
    expected_families = {
        "momentum_60",
        "short_reversal_5",
        "breakout_60",
        "failed_breakdown_20",
        "demand_volume_shock",
        "compression_breakout",
        "industry_rotation_20",
    }
    if set(population["family"]) != expected_families or set(
        selections["family"]
    ) != expected_families | {"date_control"}:
        raise IndependentFunnelError("one or more frozen families is not estimable")
    return selections, population, calendar, input_audit


def _future_links(selections: pd.DataFrame, calendar: list[date]) -> pd.DataFrame:
    cal_index = {day: index for index, day in enumerate(calendar)}
    rows: list[tuple[int, str, date, int]] = []
    for candidate in selections.itertuples():
        signal = pd.Timestamp(candidate.trade_date).date()
        index = cal_index[signal]
        if index + MAX_RESPONSE_HORIZON >= len(calendar):
            continue
        for horizon in range(1, MAX_RESPONSE_HORIZON + 1):
            rows.append((candidate.Index, candidate.symbol, calendar[index + horizon], horizon))
    return pd.DataFrame(rows, columns=["candidate_row", "symbol", "trade_date", "horizon"])


def _query_path_rows(paths: list[Path], links: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register("links", links)
    frame = connection.execute(
        """
        SELECT l.candidate_row,l.horizon,d.trade_date,d.symbol,d.open,d.high,d.low,d.close,d.amount,
               d.hard_valid,d.trade_status,d.current_day_data_tradable,
               d.buy_blocked_open,d.sell_blocked_open,d.corporate_action_count,
               d.corporate_action_valid,d.corporate_action_blocking,
               d.corporate_action_available_date,d.share_multiplier,d.cash_per_share,
               d.rights_ratio,d.available_at
        FROM read_parquet(?) d JOIN links l USING(symbol,trade_date)
        ORDER BY l.candidate_row,l.horizon
        """,
        [[str(path) for path in paths]],
    ).fetchdf()
    connection.close()
    return frame


def _visible_action(row: Any) -> tuple[float, float] | None:
    rights = 0.0 if pd.isna(row.rights_ratio) else float(row.rights_ratio)
    multiplier = 1.0 if pd.isna(row.share_multiplier) else float(row.share_multiplier)
    cash_per_share = 0.0 if pd.isna(row.cash_per_share) else float(row.cash_per_share)
    available = (
        None
        if pd.isna(row.corporate_action_available_date)
        else pd.Timestamp(row.corporate_action_available_date).date()
    )
    trade_date_value = pd.Timestamp(row.trade_date).date()
    valid = (
        bool(row.corporate_action_valid)
        and not bool(row.corporate_action_blocking)
        and rights == 0.0
        and multiplier > 0
        and available is not None
        and available <= trade_date_value
        and all(math.isfinite(value) for value in (rights, multiplier, cash_per_share))
    )
    return (multiplier, cash_per_share) if valid else None


def _screen_outcome(group: pd.DataFrame, expected_rows: int = 20) -> dict[str, Any]:
    output: dict[str, Any] = {
        "entry_status": "MISSING_PATH",
        "status_h5": "INCOMPLETE",
        "status_h20": "INCOMPLETE",
    }
    group = group.sort_values("horizon")
    if len(group) != expected_rows or group["horizon"].tolist() != list(
        range(1, expected_rows + 1)
    ):
        return output
    entry = group.iloc[0]
    available = pd.Timestamp(entry.available_at)
    if not (
        bool(entry.hard_valid)
        and int(entry.trade_status) == 1
        and bool(entry.current_day_data_tradable)
        and not bool(entry.buy_blocked_open)
        and math.isfinite(float(entry.open))
        and float(entry.open) > 0
        and available.date() <= pd.Timestamp(entry.trade_date).date()
    ):
        output["entry_status"] = "NEXT_OPEN_NOT_EXECUTABLE"
        return output
    output["entry_status"] = "EXECUTABLE"
    entry_open = float(entry.open)
    shares = 1.0
    cash = 0.0
    adverse = math.inf
    for row in group.itertuples(index=False):
        row_available = pd.Timestamp(row.available_at)
        prices = (row.high, row.low, row.close)
        if (
            not bool(row.hard_valid)
            or row_available.date() > pd.Timestamp(row.trade_date).date()
            or not all(
                value is not None and math.isfinite(float(value)) and float(value) > 0
                for value in prices
            )
        ):
            return output
        if row.horizon > 1 and int(row.corporate_action_count or 0) > 0:
            action = _visible_action(row)
            if action is None:
                return output
            multiplier, cash_per_share = action
            cash += shares * cash_per_share
            shares *= multiplier
        adverse = min(adverse, (cash + shares * float(row.low)) / entry_open - 1.0)
        if row.horizon in (5, 20):
            gross = (cash + shares * float(row.close)) / entry_open - 1.0
            net = (cash + shares * float(row.close) * (1.0 - SCREEN_COST)) / (
                entry_open * (1.0 + SCREEN_COST)
            ) - 1.0
            output.update(
                {
                    f"status_h{row.horizon}": "COMPLETE",
                    f"gross_return_h{row.horizon}": gross,
                    f"net_return_h{row.horizon}": net,
                    f"adverse_excursion_h{row.horizon}": adverse,
                    f"entry_amount_h{row.horizon}": float(entry.amount),
                }
            )
    return output


def _attach_outcomes(selections: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    outcomes = {
        int(candidate_row): _screen_outcome(group)
        for candidate_row, group in rows.groupby("candidate_row", sort=True)
    }
    outcome_frame = pd.DataFrame.from_dict(outcomes, orient="index")
    panel = selections.join(outcome_frame, how="left")
    panel["entry_status"] = panel["entry_status"].fillna("MISSING_PATH")
    for horizon in (5, 20):
        panel[f"status_h{horizon}"] = panel[f"status_h{horizon}"].fillna("INCOMPLETE")
    return panel


def _period_masks(panel: pd.DataFrame) -> dict[str, pd.Series]:
    years = pd.to_datetime(panel["trade_date"]).dt.year
    masks = {
        "full": pd.Series(True, index=panel.index),
        "early_2018_2020": years <= 2020,
        "late_2021_2023": years >= 2021,
    }
    masks.update({f"year_{year}": years == year for year in range(2018, 2024)})
    return masks


def _screen_summary(panel: pd.DataFrame) -> pd.DataFrame:
    output: list[dict[str, Any]] = []
    control = panel.loc[panel["family"] == "date_control"].copy()
    control_means: dict[int, pd.Series] = {}
    for horizon in (5, 20):
        valid = control[f"status_h{horizon}"].eq("COMPLETE")
        control_means[horizon] = (
            control.loc[valid].groupby("trade_date")[f"net_return_h{horizon}"].mean()
        )
    for (family, leg), group in panel.groupby(["family", "leg"], sort=True):
        for period, mask in _period_masks(group).items():
            period_group = group.loc[mask]
            for horizon in (5, 20):
                valid = period_group.loc[period_group[f"status_h{horizon}"].eq("COMPLETE")].copy()
                returns = valid[f"net_return_h{horizon}"].astype(float)
                controls = valid["trade_date"].map(control_means[horizon])
                excess = returns - controls
                output.append(
                    {
                        "family": family,
                        "leg": leg,
                        "period": period,
                        "horizon": horizon,
                        "count": len(valid),
                        "signal_dates": int(valid["trade_date"].nunique()),
                        "mean_return": returns.mean(),
                        "median_return": returns.median(),
                        "positive_fraction": (returns > 0).mean(),
                        "p10": returns.quantile(0.10),
                        "p90": returns.quantile(0.90),
                        "severe_loss_fraction": (returns <= -0.10).mean(),
                        "mean_adverse_excursion": valid[f"adverse_excursion_h{horizon}"].mean(),
                        "mean_excess_vs_date_control": excess.mean()
                        if family != "date_control"
                        else 0.0,
                        "entry_executable_fraction": period_group["entry_status"]
                        .eq("EXECUTABLE")
                        .mean(),
                        "median_candidate_count": period_group["candidate_count"].median(),
                        "median_avg_amount20_cny": period_group["avg_amount20"].median(),
                        "p10_entry_amount_cny": valid[f"entry_amount_h{horizon}"].quantile(0.10),
                    }
                )
    return (
        pd.DataFrame(output)
        .sort_values(["family", "leg", "period", "horizon"])
        .reset_index(drop=True)
    )


def _promotion_decisions(
    spec: dict[str, Any], summary: pd.DataFrame, panel: pd.DataFrame
) -> list[dict[str, Any]]:
    gates = spec["promotion"]["all_required"]
    decisions: list[dict[str, Any]] = []
    controls = summary.loc[(summary.family == "date_control") & (summary.leg == "control")]
    for family, family_spec in spec["families"].items():
        horizon = int(family_spec["natural_horizon_sessions"])
        rows = summary.loc[
            (summary.family == family) & (summary.leg == "top") & (summary.horizon == horizon)
        ].set_index("period")
        control_rows = controls.loc[controls.horizon == horizon].set_index("period")
        annual = [f"year_{year}" for year in range(2018, 2024)]
        positive_years = int(
            sum(float(rows.loc[name, "mean_excess_vs_date_control"]) > 0 for name in annual)
        )
        full = rows.loc["full"]
        block_excess = [
            float(rows.loc[name, "mean_excess_vs_date_control"])
            for name in ("early_2018_2020", "late_2021_2023")
        ]
        severe_disadvantage = float(
            full.severe_loss_fraction - control_rows.loc["full", "severe_loss_fraction"]
        )
        family_panel = panel.loc[(panel.family == family) & (panel.leg == "top")]
        gate_results = {
            "complete_top_outcomes": int(full["count"]) >= gates["minimum_complete_top_outcomes"],
            "signal_dates_each_block": all(
                int(rows.loc[name, "signal_dates"]) >= gates["minimum_signal_dates_each_block"]
                for name in ("early_2018_2020", "late_2021_2023")
            ),
            "entry_executability": float(full.entry_executable_fraction)
            >= gates["minimum_entry_executable_fraction"],
            "full_excess": float(full.mean_excess_vs_date_control)
            >= gates["minimum_full_natural_net_excess"],
            "both_block_excess": min(block_excess)
            >= gates["minimum_each_block_natural_net_excess"],
            "positive_years": positive_years >= gates["minimum_positive_calendar_years"],
            "severe_loss": severe_disadvantage
            <= gates["maximum_severe_loss_disadvantage_vs_control"],
            "candidate_breadth": float(family_panel.candidate_count.median())
            >= gates["minimum_median_event_candidates_per_date"],
        }
        decisions.append(
            {
                "family": family,
                "natural_horizon": horizon,
                "classification": "PROMOTE_EXECUTABLE_TRANSLATION"
                if all(gate_results.values())
                else "SCREEN_ONLY_NO_PROMOTION",
                "gate_results": gate_results,
                "full_excess": float(full.mean_excess_vs_date_control),
                "minimum_block_excess": min(block_excess),
                "positive_years": positive_years,
                "severe_loss_disadvantage": severe_disadvantage,
                "complete_top_outcomes": int(full["count"]),
            }
        )
    eligible = sorted(
        (row for row in decisions if row["classification"] == "PROMOTE_EXECUTABLE_TRANSLATION"),
        key=lambda row: (row["minimum_block_excess"], row["full_excess"]),
        reverse=True,
    )
    promoted = {row["family"] for row in eligible[: int(spec["promotion"]["maximum_families"])]}
    for row in decisions:
        if (
            row["classification"] == "PROMOTE_EXECUTABLE_TRANSLATION"
            and row["family"] not in promoted
        ):
            row["classification"] = "PASSED_SCREEN_NOT_EXECUTED_MAXIMUM_REACHED"
    return decisions


@dataclass
class Lot:
    symbol: str
    due_index: int
    shares: float
    action_cash: float = 0.0


def _query_execution_rows(
    paths: list[Path],
    panel: pd.DataFrame,
    families: list[str],
    calendar: list[date],
    spec: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cal_index = {day: index for index, day in enumerate(calendar)}
    plans: list[dict[str, Any]] = []
    keys: set[tuple[str, date]] = set()
    for family in families:
        horizon = int(spec["families"][family]["natural_horizon_sessions"])
        candidates = panel.loc[
            (panel.family == family)
            & (panel.leg == "top")
            & (panel.signal_rank <= spec["executable_translation"]["selected_names_per_signal"])
            & (panel[f"status_h{horizon}"] == "COMPLETE")
        ]
        for signal_date, group in candidates.groupby("trade_date", sort=True):
            signal_day = pd.Timestamp(signal_date).date()
            signal_index = cal_index[signal_day]
            entry_index = signal_index + 1
            due_index = entry_index + horizon
            if due_index >= len(calendar):
                continue
            for row in group.itertuples():
                plans.append(
                    {
                        "family": family,
                        "signal_date": signal_day,
                        "symbol": row.symbol,
                        "entry_index": entry_index,
                        "due_index": due_index,
                        "horizon": horizon,
                    }
                )
                for index in range(entry_index, min(due_index + 21, len(calendar))):
                    keys.add((row.symbol, calendar[index]))
    plan_frame = pd.DataFrame(plans)
    if plan_frame.empty:
        return plan_frame, pd.DataFrame()
    key_frame = pd.DataFrame(sorted(keys), columns=["symbol", "trade_date"])
    connection = duckdb.connect()
    connection.register("needed_keys", key_frame)
    rows = connection.execute(
        """
        SELECT d.trade_date,d.symbol,d.open,d.close,d.amount,d.hard_valid,d.trade_status,
               d.current_day_data_tradable,d.buy_blocked_open,d.sell_blocked_open,
               d.corporate_action_count,d.corporate_action_valid,d.corporate_action_blocking,
               d.corporate_action_available_date,d.share_multiplier,d.cash_per_share,
               d.rights_ratio,d.available_at
        FROM read_parquet(?) d JOIN needed_keys k USING(symbol,trade_date)
        ORDER BY d.trade_date,d.symbol
        """,
        [[str(path) for path in paths]],
    ).fetchdf()
    connection.close()
    if rows.duplicated(["symbol", "trade_date"]).any():
        raise IndependentFunnelError("duplicate execution market row")
    return plan_frame, rows


def _row_valid(row: Any) -> bool:
    return (
        bool(row.hard_valid)
        and pd.Timestamp(row.available_at).date() <= pd.Timestamp(row.trade_date).date()
        and math.isfinite(float(row.open))
        and float(row.open) > 0
        and math.isfinite(float(row.close))
        and float(row.close) > 0
    )


def _replay_family(
    family: str,
    cost: float,
    plans: pd.DataFrame,
    market_rows: pd.DataFrame,
    calendar: list[date],
    spec: dict[str, Any],
) -> dict[str, Any]:
    family_plans = plans.loc[plans.family == family].copy()
    if family_plans.empty:
        raise IndependentFunnelError(f"missing execution plans for {family}")
    row_map = {
        (row.symbol, pd.Timestamp(row.trade_date).date()): row
        for row in market_rows.itertuples(index=False)
    }
    entry_map: dict[int, list[Any]] = {}
    for entry_index, group in family_plans.groupby("entry_index", sort=True):
        entry_map[int(entry_index)] = list(group.itertuples(index=False))
    initial = float(spec["executable_translation"]["initial_capital_cny"])
    vintages = math.ceil(int(family_plans.horizon.iloc[0]) / 5)
    cash = initial
    lots: list[Lot] = []
    turnover = 0.0
    entries = 0
    blocked_exit_delays = 0
    nav_rows: list[dict[str, Any]] = []
    capacity_samples: list[float] = []
    start_index = int(family_plans.entry_index.min())
    final_due = int(family_plans.due_index.max())
    final_index = min(final_due + 20, len(calendar) - 1)
    for index in range(start_index, final_index + 1):
        trade_date_value = calendar[index]
        for lot in lots:
            row = row_map.get((lot.symbol, trade_date_value))
            if row is None or not _row_valid(row):
                raise IndependentFunnelError(
                    f"invalid holding row: {family}:{lot.symbol}:{trade_date_value}"
                )
            if int(row.corporate_action_count or 0) > 0:
                action = _visible_action(row)
                if action is None:
                    raise IndependentFunnelError(
                        f"unsupported action in replay: {family}:{lot.symbol}:{trade_date_value}"
                    )
                multiplier, cash_per_share = action
                lot.action_cash += lot.shares * cash_per_share
                lot.shares *= multiplier
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
            gross_value = lot.shares * float(row.open)
            cash += lot.action_cash + gross_value * (1.0 - cost)
            turnover += gross_value
        lots = survivors
        pre_entry_nav = cash
        for lot in lots:
            row = row_map[(lot.symbol, trade_date_value)]
            pre_entry_nav += lot.action_cash + lot.shares * float(row.open)
        planned = entry_map.get(index, [])
        executable: list[tuple[Any, Any]] = []
        for plan in planned:
            row = row_map.get((plan.symbol, trade_date_value))
            if row is None or not _row_valid(row):
                continue
            if (
                int(row.trade_status) == 1
                and bool(row.current_day_data_tradable)
                and not bool(row.buy_blocked_open)
            ):
                executable.append((plan, row))
        if executable:
            cohort_capital = min(cash, pre_entry_nav / vintages)
            per_name = cohort_capital / len(executable)
            for plan, row in executable:
                shares = per_name / (float(row.open) * (1.0 + cost))
                gross_value = shares * float(row.open)
                cash -= gross_value * (1.0 + cost)
                turnover += gross_value
                lots.append(Lot(plan.symbol, int(plan.due_index), shares))
                entries += 1
                capacity_samples.append(float(row.amount) * 0.05 * len(executable) * vintages)
        nav = cash
        for lot in lots:
            row = row_map[(lot.symbol, trade_date_value)]
            nav += lot.action_cash + lot.shares * float(row.close)
        nav_rows.append(
            {
                "trade_date": trade_date_value,
                "nav": nav,
                "cash": cash,
                "positions": len(lots),
            }
        )
        if index >= final_due and not lots and index not in entry_map:
            break
    nav = pd.DataFrame(nav_rows)
    returns = nav.nav.pct_change().fillna(nav.nav.iloc[0] / initial - 1.0)
    running_peak = nav.nav.cummax()
    drawdown = nav.nav / running_peak - 1.0
    years = len(nav) / 252.0
    annualized = (nav.nav.iloc[-1] / initial) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    sharpe = (
        math.sqrt(252.0) * returns.mean() / returns.std(ddof=1) if returns.std(ddof=1) > 0 else 0.0
    )
    invested_fraction = 1.0 - (nav.cash / nav.nav).clip(lower=0, upper=1)
    return {
        "family": family,
        "cost_per_side_bps": round(cost * 10000),
        "start_date": str(nav.trade_date.iloc[0]),
        "end_date": str(nav.trade_date.iloc[-1]),
        "total_return": float(nav.nav.iloc[-1] / initial - 1.0),
        "annualized_return": annualized,
        "maximum_drawdown": float(drawdown.min()),
        "daily_sharpe": sharpe,
        "turnover_multiple_initial_capital": turnover / initial,
        "entries": entries,
        "blocked_exit_delays": blocked_exit_delays,
        "terminal_open_lots": len(lots),
        "mean_invested_fraction": float(invested_fraction.mean()),
        "p10_capacity_cny_at_5pct_amount": float(np.quantile(capacity_samples, 0.10))
        if capacity_samples
        else None,
        "median_capacity_cny_at_5pct_amount": float(np.median(capacity_samples))
        if capacity_samples
        else None,
    }


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# Independent A-share strategy discovery funnel",
        "",
        "## Boundary",
        "",
        (
            "This is an EXPLORE-only 2018--2023 discovery screen. Every year is "
            "consumed development history; no result is OOS, validation, or live "
            "evidence. Post-2023 data and CY-011 were not read. CHINEXT candidate "
            "rules were not changed or combined."
        ),
        "",
        "## Cheap family screen",
        "",
        (
            "| Family | Natural h | N | Median candidates/date | Full net excess | "
            "Early excess | Late excess | Positive years | Severe disadvantage | Decision |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in result["promotion_decisions"]:
        lines.append(
            f"| {row['family']} | {row['natural_horizon']} | {row['complete_top_outcomes']:,} | "
            f"{result['decision_details'][row['family']]['median_candidate_count']:.0f} | "
            f"{row['full_excess']:.3%} | "
            f"{result['decision_details'][row['family']]['early_excess']:.3%} | "
            f"{result['decision_details'][row['family']]['late_excess']:.3%} | "
            f"{row['positive_years']}/6 | {row['severe_loss_disadvantage']:.3%} | "
            f"{row['classification']} |"
        )
    lines.extend(["", "## Executable translations", ""])
    if result["executable_replays"]:
        lines.extend(
            [
                (
                    "| Family | Cost/side | Total return | Ann. return | Max DD | Sharpe | "
                    "Turnover | Entries | Capacity p10 |"
                ),
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in result["executable_replays"]:
            lines.append(
                f"| {row['family']} | {row['cost_per_side_bps']} bps | {row['total_return']:.2%} | "
                f"{row['annualized_return']:.2%} | {row['maximum_drawdown']:.2%} | "
                f"{row['daily_sharpe']:.3f} | {row['turnover_multiple_initial_capital']:.2f}x | "
                f"{row['entries']} | {row['p10_capacity_cny_at_5pct_amount']:,.0f} |"
            )
    else:
        lines.append("No family passed every frozen promotion gate; no executable replay was run.")
    lines.extend(
        [
            "",
            "## Opportunity, competition, and capacity",
            "",
            (
                "| Family | Entry executable | Top-minus-bottom | Median amount20 | "
                "Screen capacity p10 |"
            ),
            "|---|---:|---:|---:|---:|",
        ]
    )
    for family in result["family_ranking"]:
        detail = result["decision_details"][family]
        spread = detail["top_minus_bottom"]
        spread_text = "n/a" if spread is None else f"{spread:.3%}"
        lines.append(
            f"| {family} | {detail['entry_executable_fraction']:.2%} | {spread_text} | "
            f"{detail['median_avg_amount20_cny']:,.0f} | {detail['screen_capacity_p10_cny']:,.0f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            result["synthesis"],
            "",
            (
                "What market behavior are we still not studying? Signal-time intraday "
                "supply/demand within these independent families, non-price fundamental "
                "revision, order-book pressure, borrow-feasible short legs, and genuinely "
                "untouched temporal confirmation."
            ),
            "",
            "Has any discovered mechanism implied a genuinely new strategy archetype? "
            + result["new_archetype_answer"],
            "",
            "## Reproducibility",
            "",
            f"- Frozen spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- CY-006 manifest SHA-256: `{result['input_identity']['manifest_sha256']}`",
            f"- Candidate panel SHA-256: `{result['hashes']['panel_sha256']}`",
            f"- Screen summary SHA-256: `{result['hashes']['summary_sha256']}`",
            (
                "- Decision clock is 15:00; entries are no earlier than the next market "
                "open; executable exits are no earlier than the open following the "
                "holding-close decision."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    paths, input_identity = _validate_cy006(spec)
    with tempfile.TemporaryDirectory(prefix="ashare-indep-funnel-") as temporary:
        temp_path = Path(temporary)
        selections, population, calendar, input_audit = _build_signal_domain(paths, temp_path)
        links = _future_links(selections, calendar)
        path_rows = _query_path_rows(paths, links)
    panel = _attach_outcomes(selections, path_rows)
    summary = _screen_summary(panel)
    decisions = _promotion_decisions(spec, summary, panel)
    promoted = [
        row["family"]
        for row in decisions
        if row["classification"] == "PROMOTE_EXECUTABLE_TRANSLATION"
    ]
    executable_replays: list[dict[str, Any]] = []
    if promoted:
        plans, execution_rows = _query_execution_rows(paths, panel, promoted, calendar, spec)
        for family in promoted:
            for cost_bps in spec["executable_translation"]["costs_per_side_bps"]:
                executable_replays.append(
                    _replay_family(
                        family, float(cost_bps) / 10000.0, plans, execution_rows, calendar, spec
                    )
                )
    natural_map = {
        name: int(value["natural_horizon_sessions"]) for name, value in spec["families"].items()
    }
    control_means = {
        horizon: panel.loc[
            (panel.family == "date_control") & (panel[f"status_h{horizon}"] == "COMPLETE")
        ]
        .groupby("trade_date")[f"net_return_h{horizon}"]
        .mean()
        for horizon in (5, 20)
    }
    compact = panel.loc[panel.leg == "top"].copy()
    compact["natural_horizon"] = compact.family.map(natural_map)
    compact["natural_status"] = [
        row[f"status_h{int(row.natural_horizon)}"] for _, row in compact.iterrows()
    ]
    compact["natural_net_return"] = [
        row[f"net_return_h{int(row.natural_horizon)}"] for _, row in compact.iterrows()
    ]
    compact["natural_adverse_excursion"] = [
        row[f"adverse_excursion_h{int(row.natural_horizon)}"] for _, row in compact.iterrows()
    ]
    compact["date_control_net_return"] = [
        control_means[int(row.natural_horizon)].get(row.trade_date, np.nan)
        for row in compact.itertuples()
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
        "natural_horizon",
        "entry_status",
        "natural_status",
        "natural_net_return",
        "date_control_net_return",
        "natural_adverse_excursion",
    ]
    panel_text = compact[compact_columns].to_csv(
        index=False, lineterminator="\n", float_format="%.10g"
    )
    summary_text = summary.to_csv(index=False, lineterminator="\n", float_format="%.10g")
    _atomic_write(PANEL_PATH, panel_text)
    _atomic_write(SUMMARY_PATH, summary_text)
    details: dict[str, Any] = {}
    for row in decisions:
        family = row["family"]
        horizon = row["natural_horizon"]
        subset = summary.loc[
            (summary.family == family) & (summary.leg == "top") & (summary.horizon == horizon)
        ].set_index("period")
        full = subset.loc["full"]
        bottom = summary.loc[
            (summary.family == family)
            & (summary.leg == "bottom")
            & (summary.horizon == horizon)
            & (summary.period == "full")
        ]
        details[family] = {
            "early_excess": float(subset.loc["early_2018_2020", "mean_excess_vs_date_control"]),
            "late_excess": float(subset.loc["late_2021_2023", "mean_excess_vs_date_control"]),
            "full_mean_return": float(full.mean_return),
            "full_positive_fraction": float(full.positive_fraction),
            "full_severe_loss_fraction": float(full.severe_loss_fraction),
            "entry_executable_fraction": float(full.entry_executable_fraction),
            "median_candidate_count": float(full.median_candidate_count),
            "median_avg_amount20_cny": float(full.median_avg_amount20_cny),
            "screen_capacity_p10_cny": float(full.p10_entry_amount_cny) * 0.05 * 20,
            "top_minus_bottom": (
                None if bottom.empty else float(full.mean_return - bottom.iloc[0].mean_return)
            ),
        }
    family_ranking = [
        row["family"]
        for row in sorted(
            decisions,
            key=lambda item: (item["minimum_block_excess"], item["full_excess"]),
            reverse=True,
        )
    ]
    promoted_text = ", ".join(promoted) if promoted else "none"
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_EXPLORE_ONLY",
        "claim_boundary": spec["claim_boundary"],
        "input_identity": input_identity,
        "input_audit": input_audit,
        "signal_domain": {
            "families": len(spec["families"]),
            "decision_dates": int(population.trade_date.nunique()),
            "family_date_cells": len(population),
            "selected_top_rows": int((panel.leg == "top").sum()),
            "screen_path_rows": len(path_rows),
            "first_decision_date": str(population.trade_date.min().date()),
            "last_decision_date": str(population.trade_date.max().date()),
        },
        "promotion_decisions": decisions,
        "decision_details": details,
        "family_ranking": family_ranking,
        "promoted_families": promoted,
        "executable_replays": executable_replays,
        "synthesis": (
            "Seven frozen families were screened on one shared PIT panel. Executable "
            f"promotion was limited to {promoted_text}. Passing a screen is only a "
            "development prioritization decision; failure closes only the exact "
            "representation/translation, not the broader mechanism family."
        ),
        "new_archetype_answer": (
            "Yes, but only at exploratory-candidate strength: " + ", ".join(promoted) + "."
            if promoted
            else "No family cleared the fixed standalone promotion boundary in this batch."
        ),
        "boundaries": {
            "post_2023_read": False,
            "cy011_read": False,
            "chinext_changed": False,
            "oos_claim": False,
            "validation_claim": False,
            "live_claim": False,
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "panel_sha256": sha256_file(PANEL_PATH),
            "summary_sha256": sha256_file(SUMMARY_PATH),
        },
    }
    report = _render_report(result)
    _atomic_write(REPORT_PATH, report)
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    completed = run()
    print(json.dumps(_clean(completed), indent=2, sort_keys=True))
