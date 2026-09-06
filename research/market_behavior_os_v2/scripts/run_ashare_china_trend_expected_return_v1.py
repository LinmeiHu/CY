#!/usr/bin/env python3
"""Run the frozen China price-volume trend expected-return experiment."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
EXPERIMENT_ID = "ASHARE-CHINA-TREND-EXPECTED-RETURN-V1"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
PREHISTORY_MANIFEST_PATH = PROGRAM / "TREND_PREHISTORY_DATA_MANIFEST.json"
COEFFICIENT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_coefficients.csv"
SCREEN_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_screen.csv"
EQUITY_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_equity.csv"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
ELIGIBILITY_PATH = Path(
    "/Volumes/quant/CY_quant_research/"
    "multiscale_diffusion_daily_alpha_cycle_015/daily_feature_panel.parquet"
)
BASE_PATH = PROGRAM / "scripts/run_ashare_speculative_turnover_ratio_v1.py"
EXPECTED_SPEC_SHA256 = "f5ec6c9c51876a619af26131fec7461dd6d58bf54590f83ee940624f000eeeb8"
EXPECTED_PREHISTORY_SHA256 = "926f0c6b2609b1923854e1306b6efb1ca8f3deab08ac668b6ecb977e3f950529"
LAGS = (3, 5, 10, 20, 50, 100, 200, 300, 400)
FEATURES = tuple([f"p{lag}" for lag in LAGS] + [f"v{lag}" for lag in LAGS])
LAMBDA = 0.02
MINIMUM_BETA_UPDATES = 36
GENERATION_YEARS = {2018, 2019, 2020}
VALIDATION_YEARS = {2021, 2022, 2023}


class ChinaTrendError(RuntimeError):
    """Fail-closed China trend experiment error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise ChinaTrendError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


BASE = _load_module("ashare_speculative_turnover_utility_for_trend", BASE_PATH)
CA = BASE.CA


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


def _load_spec() -> tuple[dict[str, Any], dict[str, Any]]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise ChinaTrendError("frozen trend spec identity mismatch")
    if sha256_file(PREHISTORY_MANIFEST_PATH) != EXPECTED_PREHISTORY_SHA256:
        raise ChinaTrendError("prehistory manifest identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    prehistory = json.loads(PREHISTORY_MANIFEST_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != (
        "FROZEN_BEFORE_ANY_2018_2023_FORWARD_OUTCOME_AGGREGATION_"
        "AFTER_DATA_AVAILABILITY_CORRECTION"
    ):
        raise ChinaTrendError("trend spec was not frozen")
    if prehistory.get("status") != "RESEARCH_CONDITIONAL_EXACT_HASHES_ONLY":
        raise ChinaTrendError("prehistory was not conditionally registered")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise ChinaTrendError(f"bound input changed: {role}")
    for binding in prehistory["bound_partitions"]:
        path = Path(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise ChinaTrendError(f"prehistory partition changed: {binding['year']}")
    audit = prehistory["source_audit"]
    audit_path = Path(audit["path"])
    if not audit_path.is_file() or sha256_file(audit_path) != audit["sha256"]:
        raise ChinaTrendError("prehistory source audit changed")
    if set(binding["year"] for binding in prehistory["bound_partitions"]) != set(
        range(2013, 2018)
    ):
        raise ChinaTrendError("prehistory year scope changed")
    prohibited = "|".join(spec["prohibited"])
    for phrase in (
        "alternative moving-average",
        "prehistory substitution",
        "post-2023",
        "CY-011",
    ):
        if phrase not in prohibited:
            raise ChinaTrendError(f"missing prohibition: {phrase}")
    CA._load_spec()
    return spec, prehistory


def _configure(temp_path: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("SET threads=2")
    connection.execute("SET memory_limit='10GB'")
    connection.execute("SET preserve_insertion_order=false")
    escaped = temp_path.as_posix().replace("'", "''")
    connection.execute(f"SET temp_directory='{escaped}'")
    return connection


def _monthly_signal_panel(
    current_paths: list[Path], prehistory: dict[str, Any], temp_path: Path
) -> tuple[pd.DataFrame, dict[str, Any]]:
    prehistory_paths = [Path(binding["path"]) for binding in prehistory["bound_partitions"]]
    connection = _configure(temp_path)
    connection.from_parquet(
        [str(path) for path in prehistory_paths + current_paths], union_by_name=True
    ).create_view("daily")
    source = connection.execute(
        """
        SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
          count(*)-count(DISTINCT (trade_date,symbol)),
          sum((available_at>decision_at)::INTEGER),
          sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER)
        FROM daily
        """
    ).fetchone()
    audit = {
        "rows": int(source[0]),
        "symbols": int(source[1]),
        "first": str(source[2]),
        "last": str(source[3]),
        "duplicate_keys": int(source[4]),
        "time_travel": int(source[5]),
        "lineage_failures": int(source[6]),
    }
    expected = {
        "rows": 9_542_406,
        "first": "2013-01-04",
        "last": "2023-12-29",
        "duplicate_keys": 0,
        "time_travel": 0,
        "lineage_failures": 0,
    }
    if {key: audit[key] for key in expected} != expected:
        raise ChinaTrendError(f"combined daily source audit changed: {audit}")
    connection.execute(
        """
        CREATE TEMP TABLE calendar AS
        SELECT trade_date,row_number() OVER (ORDER BY trade_date)-1 cal_idx
        FROM (SELECT DISTINCT trade_date FROM daily)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE quality AS
        SELECT d.*,c.cal_idx,
          (d.bar_valid IS TRUE AND d.trading_state_valid IS TRUE
           AND d.corporate_action_valid IS TRUE AND d.market_rule_valid IS TRUE
           AND d.historical_identity_valid IS TRUE
           AND d.corporate_action_blocking IS FALSE AND coalesce(d.rights_ratio,0)=0
           AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
           AND d.open>0 AND d.high>=greatest(d.open,d.close)
           AND d.low<=least(d.open,d.close) AND d.close>0
           AND d.volume>=0 AND d.amount>=0) bar_contract_valid,
          (d.trade_status=0 AND d.trading_state_valid IS TRUE
           AND d.current_day_data_tradable IS FALSE
           AND d.corporate_action_valid IS TRUE AND d.market_rule_valid IS TRUE
           AND d.historical_identity_valid IS TRUE
           AND d.corporate_action_blocking IS FALSE AND coalesce(d.rights_ratio,0)=0
           AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
           AND d.open>0 AND d.high=d.open AND d.low=d.open AND d.close=d.open)
            authorized_suspension,
          (d.hard_valid IS TRUE AND d.trade_status=1
           AND d.current_day_data_tradable IS TRUE AND d.is_st IS FALSE) endpoint_valid
        FROM daily d JOIN calendar c USING(trade_date)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE base AS
        SELECT *,
          (bar_contract_valid OR authorized_suspension) price_observable,
          lag(close) OVER w previous_close,
          lag(cal_idx) OVER w previous_cal_idx,
          lag(bar_contract_valid OR authorized_suspension) OVER w previous_price_observable
        FROM quality
        WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE steps AS
        SELECT *,CASE
          WHEN price_observable AND previous_price_observable
           AND cal_idx-previous_cal_idx=1 AND coalesce(corporate_action_count,0)=0
          THEN ln(close/previous_close)
          WHEN price_observable AND previous_price_observable
           AND cal_idx-previous_cal_idx=1 AND corporate_action_count>0
           AND corporate_action_available_date IS NOT NULL
           AND corporate_action_available_date<=trade_date
           AND coalesce(rights_ratio,0)=0 AND coalesce(share_multiplier,1)>0
           AND previous_close-coalesce(cash_per_share,0)>0
          THEN ln(close/((previous_close-coalesce(cash_per_share,0))
                    /coalesce(share_multiplier,1)))
          ELSE NULL END step_return
        FROM base
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE paths AS
        SELECT *,exp(sum(coalesce(step_return,0)) OVER
          (PARTITION BY symbol ORDER BY trade_date)) coordinate_close
        FROM steps
        """
    )
    rolling_items: list[str] = []
    window_items: list[str] = []
    for lag in LAGS:
        rolling_items.extend(
            [
                f"avg(coordinate_close) OVER w{lag} price_ma{lag}",
                f"count(step_return) OVER w{lag} path_n{lag}",
                (
                    "avg(volume) FILTER (WHERE bar_contract_valid AND trade_status=1 "
                    "AND current_day_data_tradable) "
                    f"OVER w{lag} volume_ma{lag}"
                ),
                (
                    "count(volume) FILTER (WHERE bar_contract_valid AND trade_status=1 "
                    "AND current_day_data_tradable) "
                    f"OVER w{lag} volume_n{lag}"
                ),
            ]
        )
        window_items.append(
            f"w{lag} AS (PARTITION BY symbol ORDER BY trade_date "
            f"ROWS BETWEEN {lag - 1} PRECEDING AND CURRENT ROW)"
        )
    connection.execute(
        "CREATE TEMP TABLE rolling AS SELECT *,"
        + ",".join(rolling_items)
        + ",avg(amount) FILTER (WHERE bar_contract_valid AND trade_status=1 "
        "AND current_day_data_tradable) OVER w20 avg_amount20 "
        "FROM paths WINDOW "
        + ",".join(window_items)
    )
    connection.execute(
        """
        CREATE TEMP TABLE month_ends AS
        SELECT date_trunc('month',trade_date)::DATE month_key,max(trade_date) month_end
        FROM calendar GROUP BY 1
        """
    )
    signal_items: list[str] = []
    for lag in LAGS:
        signal_items.extend(
            [
                (
                    f"CASE WHEN path_n{lag}={lag} AND coordinate_close>0 "
                    f"THEN price_ma{lag}/coordinate_close END p{lag}"
                ),
                (
                    f"CASE WHEN volume_n{lag}>={math.ceil(lag / 2)} AND volume>0 "
                    f"THEN volume_ma{lag}/volume END v{lag}_raw"
                ),
            ]
        )
    monthly = connection.execute(
        "SELECT r.trade_date,m.month_key,r.symbol,r.industry,r.coordinate_close,"
        "r.endpoint_valid,r.avg_amount20,"
        + ",".join(signal_items)
        + " FROM rolling r JOIN month_ends m ON r.trade_date=m.month_end "
        "ORDER BY r.symbol,r.trade_date"
    ).fetchdf()
    connection.close()
    monthly["trade_date"] = pd.to_datetime(monthly.trade_date)
    monthly["month_key"] = pd.to_datetime(monthly.month_key)
    for lag in LAGS:
        raw = f"v{lag}_raw"
        monthly[f"v{lag}"] = monthly.groupby("symbol", sort=False)[raw].ffill()
    monthly = monthly.drop(columns=[f"v{lag}_raw" for lag in LAGS])
    monthly["previous_coordinate"] = monthly.groupby("symbol").coordinate_close.shift(1)
    monthly["previous_month_key"] = monthly.groupby("symbol").month_key.shift(1)
    month_ord = monthly.month_key.dt.year * 12 + monthly.month_key.dt.month
    prior_ord = (
        monthly.previous_month_key.dt.year * 12 + monthly.previous_month_key.dt.month
    )
    contiguous = month_ord - prior_ord == 1
    monthly["monthly_return"] = (
        monthly.coordinate_close / monthly.previous_coordinate - 1.0
    ).where(contiguous)
    audit.update(
        {
            "monthly_rows": len(monthly),
            "monthly_dates": int(monthly.trade_date.nunique()),
            "first_month_end": monthly.trade_date.min().date().isoformat(),
            "last_month_end": monthly.trade_date.max().date().isoformat(),
        }
    )
    return monthly, audit


def _fit_recursive_expected_return(
    monthly: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    work = monthly.sort_values(["symbol", "trade_date"]).copy()
    for feature in FEATURES:
        work[f"prior_{feature}"] = work.groupby("symbol")[feature].shift(1)
    work["prior_endpoint_valid"] = work.groupby("symbol").endpoint_valid.shift(1)
    work["prior_avg_amount20"] = work.groupby("symbol").avg_amount20.shift(1)
    work["prior_signal_month"] = work.groupby("symbol").month_key.shift(1)
    current_ord = work.month_key.dt.year * 12 + work.month_key.dt.month
    prior_ord = work.prior_signal_month.dt.year * 12 + work.prior_signal_month.dt.month
    prior_contiguous = current_ord - prior_ord == 1
    coefficient_rows: list[dict[str, Any]] = []
    score_frames: list[pd.DataFrame] = []
    forecast: np.ndarray | None = None
    updates = 0
    for signal_date, current in work.groupby("trade_date", sort=True):
        regression_columns = [f"prior_{feature}" for feature in FEATURES]
        fit = current.loc[
            prior_contiguous.loc[current.index]
            & current.prior_endpoint_valid.eq(True)
            & current.prior_avg_amount20.ge(50_000_000)
            & np.isfinite(current.monthly_return),
            ["monthly_return", *regression_columns],
        ].dropna()
        if len(fit) < 200:
            continue
        x = fit[regression_columns].to_numpy(float)
        y = fit.monthly_return.to_numpy(float)
        design = np.column_stack([np.ones(len(x)), x])
        beta, _, rank, singular = np.linalg.lstsq(design, y, rcond=None)
        if rank < design.shape[1] or not np.isfinite(beta).all():
            raise ChinaTrendError(f"rank-deficient monthly regression: {signal_date}")
        forecast = beta.copy() if forecast is None else (1.0 - LAMBDA) * forecast + LAMBDA * beta
        updates += 1
        coefficient_rows.append(
            {
                "trade_date": signal_date,
                "regression_rows": len(fit),
                "rank": int(rank),
                "condition_number": float(singular[0] / singular[-1]),
                "beta_updates": updates,
                **{
                    f"beta_{name}": float(value)
                    for name, value in zip(("intercept", *FEATURES), beta, strict=True)
                },
                **{
                    f"forecast_{name}": float(value)
                    for name, value in zip(
                        ("intercept", *FEATURES), forecast, strict=True
                    )
                },
            }
        )
        if updates < MINIMUM_BETA_UPDATES:
            continue
        scoreable = current.loc[
            current.endpoint_valid.astype(bool)
            & current.avg_amount20.ge(50_000_000),
            ["trade_date", "symbol", "industry", "avg_amount20", *FEATURES],
        ].dropna()
        if scoreable.empty:
            continue
        score_design = np.column_stack(
            [np.ones(len(scoreable)), scoreable[list(FEATURES)].to_numpy(float)]
        )
        scoreable = scoreable.copy()
        scoreable["expected_return"] = score_design @ forecast
        scoreable["beta_updates"] = updates
        score_frames.append(scoreable)
    coefficients = pd.DataFrame(coefficient_rows)
    if not score_frames:
        raise ChinaTrendError("recursive model produced no scoreable months")
    scores = pd.concat(score_frames, ignore_index=True)
    diagnostics = {
        "coefficient_months": len(coefficients),
        "first_coefficient_month": str(pd.Timestamp(coefficients.trade_date.min()).date()),
        "last_coefficient_month": str(pd.Timestamp(coefficients.trade_date.max()).date()),
        "first_score_month": str(pd.Timestamp(scores.trade_date.min()).date()),
        "last_score_month": str(pd.Timestamp(scores.trade_date.max()).date()),
        "minimum_regression_rows": int(coefficients.regression_rows.min()),
        "median_regression_rows": float(coefficients.regression_rows.median()),
        "maximum_condition_number": float(coefficients.condition_number.max()),
    }
    return scores, coefficients, diagnostics


def _evaluation_feature(scores: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    connection = duckdb.connect()
    connection.from_parquet(str(ELIGIBILITY_PATH)).create_view("eligibility")
    eligibility = connection.execute(
        """
        SELECT trade_date,cal_idx,decision_at,available_at,symbol,industry,
          avg_amount20,max_return20
        FROM eligibility
        """
    ).fetchdf()
    connection.close()
    score = scores.loc[pd.to_datetime(scores.trade_date).dt.year >= 2018].copy()
    score["trade_date"] = pd.to_datetime(score.trade_date)
    eligibility["trade_date"] = pd.to_datetime(eligibility.trade_date)
    feature = eligibility.merge(
        score[["trade_date", "symbol", "expected_return", "beta_updates"]],
        on=["trade_date", "symbol"],
        how="inner",
        validate="one_to_one",
    )
    feature["turnover_surge_ratio"] = -feature.expected_return
    feature = feature.sort_values(
        ["trade_date", "turnover_surge_ratio", "symbol"]
    ).reset_index(drop=True)
    dates = sorted(feature.trade_date.dt.date.unique())
    if not dates or dates[0] != date(2018, 7, 31) or dates[-1] != date(2023, 12, 29):
        raise ChinaTrendError(f"evaluation score coverage changed: {dates[:1]} {dates[-1:]}")
    if feature.duplicated(["trade_date", "symbol"]).any():
        raise ChinaTrendError("duplicate evaluation scores")
    diagnostics = {
        "evaluation_rows": len(feature),
        "evaluation_dates": len(dates),
        "evaluation_symbols": int(feature.symbol.nunique()),
        "minimum_monthly_candidates": int(feature.groupby("trade_date").size().min()),
        "median_monthly_candidates": float(feature.groupby("trade_date").size().median()),
        "median_rank_correlation_with_low_max": float(
            feature.groupby("trade_date").apply(
                lambda group: group.expected_return.rank(pct=True).corr(
                    (-group.max_return20).rank(pct=True)
                ),
                include_groups=False,
            ).median()
        ),
    }
    return feature, diagnostics


def _hash_order(symbol: str, signal_date: date, seed: str) -> str:
    return hashlib.sha256(f"{symbol}|{signal_date}|{seed}".encode()).hexdigest()


def _sample_plans(frame: pd.DataFrame, calendar: list[date]) -> pd.DataFrame:
    cal_index = {day: index for index, day in enumerate(calendar)}
    work = frame.copy()
    work["trade_date"] = pd.to_datetime(work.trade_date).dt.date
    signal_dates = sorted(work.trade_date.unique())
    next_signal = {current: following for current, following in pairwise(signal_dates)}
    rows: list[dict[str, Any]] = []

    def add(arm: str, selected: pd.DataFrame, signal_date: date, count: int) -> None:
        if len(selected) != count:
            raise ChinaTrendError(f"incomplete {arm} sample: {signal_date}")
        for rank, item in enumerate(selected.itertuples(index=False), start=1):
            rows.append(
                {
                    "arm": arm,
                    "signal_date": signal_date,
                    "symbol": item.symbol,
                    "industry": str(item.industry),
                    "score": float(item.turnover_surge_ratio),
                    "signal_rank": rank,
                    "candidate_count": len(group),
                    "avg_amount20": float(item.avg_amount20),
                    "entry_index": cal_index[signal_date] + 1,
                    "due_index": cal_index[next_signal[signal_date]] + 1,
                }
            )

    for signal_date, raw_group in work.groupby("trade_date", sort=True):
        if signal_date not in next_signal or signal_date > date(2023, 10, 31):
            continue
        group = raw_group.sort_values(
            ["turnover_surge_ratio", "symbol"], ascending=[True, True]
        ).reset_index(drop=True)
        if len(group) < 100:
            raise ChinaTrendError(f"insufficient candidates: {signal_date}")
        group["quintile"] = np.minimum(
            np.arange(len(group), dtype=int) * 5 // len(group) + 1, 5
        )
        add("LOWEST20", group.head(20), signal_date, 20)
        add(
            "HIGHEST20",
            group.sort_values(
                ["turnover_surge_ratio", "symbol"], ascending=[False, True]
            ).head(20),
            signal_date,
            20,
        )
        control = group.copy()
        control["hash_order"] = control.symbol.map(
            lambda symbol, current=signal_date: _hash_order(
                symbol, current, "CHINA-TREND-CONTROL-V1"
            )
        )
        add(
            "DATE_CONTROL20",
            control.sort_values(["hash_order", "symbol"]).head(20),
            signal_date,
            20,
        )
        for quintile in range(1, 6):
            sampled = group.loc[group.quintile.eq(quintile)].copy()
            sampled["hash_order"] = sampled.symbol.map(
                lambda symbol, current=signal_date: _hash_order(
                    symbol, current, "CHINA-TREND-V1"
                )
            )
            add(
                f"Q{quintile}_SAMPLE20",
                sampled.sort_values(["hash_order", "symbol"]).head(20),
                signal_date,
                20,
            )
    plans = pd.DataFrame(rows).sort_values(
        ["signal_date", "arm", "signal_rank", "symbol"]
    )
    counts = plans.groupby(["signal_date", "arm"]).size()
    if (
        plans.empty
        or plans.duplicated(["arm", "signal_date", "symbol"]).any()
        or not counts.eq(20).all()
        or plans.signal_date.nunique() != 64
    ):
        raise ChinaTrendError("sample plan shape changed")
    return plans.reset_index(drop=True)


def _render(result: dict[str, Any]) -> str:
    generation = result["generation"]
    lines = [
        "# China trend expected return V1",
        "",
        f"Status: `{result['status']}`.",
        "",
        "This is the frozen Liu-Zhou-Zhu price-volume expected-return formula: nine "
        "price moving averages, nine volume moving averages, monthly cross-sectional "
        "regressions, and coefficient EMA lambda 0.02. The only executable translation "
        "is monthly equal-weight Top-10 highest expected return.",
        "",
        "## Input and claim boundary",
        "",
        "2013-2017 PIT-B rows were used only for recursive coefficient warmup. All "
        "2018-2023 evaluation and execution used authoritative CY-006/Cycle-015 data. "
        "Post-2023 outcomes and CY-011 were not read. Results remain consumed development "
        "research, not independent confirmation.",
        "",
        "## Generation 2018-2020",
        "",
        f"High-expected-return 20 mean {generation['arms']['LOWEST20']['mean_return']:.3%}; "
        f"excess versus control {generation['lowest20_excess_vs_control']:+.3%}; "
        f"high-minus-low expected return {generation['lowest20_minus_highest20']:+.3%}; "
        f"favorable quintile steps {generation['favorable_quintile_steps']}/4; "
        f"passed `{result['generation_passed']}`.",
        "",
    ]
    if result["validation_opened"]:
        validation = result["validation"]
        lines += [
            "## Fixed validation 2021-2023",
            "",
            f"High-expected-return 20 mean {validation['arms']['LOWEST20']['mean_return']:.3%}; "
            f"excess versus control {validation['lowest20_excess_vs_control']:+.3%}; "
            f"high-minus-low expected return {validation['lowest20_minus_highest20']:+.3%}; "
            f"favorable quintile steps {validation['favorable_quintile_steps']}/4; "
            f"passed `{result['validation_passed']}`.",
            "",
        ]
    else:
        lines += ["Fixed validation remained unopened.", ""]
    if result["replay"] is not None:
        replay = result["replay"]
        lines += [
            "## Executable Top-10 replay",
            "",
            f"Annualized {replay['annualized_return']:.2%}; total "
            f"{replay['total_return']:.2%}; maximum drawdown "
            f"{replay['maximum_drawdown']:.2%}; Sharpe "
            f"{replay['daily_sharpe']:.3f}; target met `{result['target_met']}`.",
            "",
        ]
    lines += [
        "No alternative lag, lambda, regression, Top-N, holding rule, sign, habitat, "
        "or Champion combination was tested.",
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec, prehistory = _load_spec()
    ca_spec = CA._load_spec()
    current_paths, calendar, input_identity = CA._load_market_inputs(ca_spec)
    if calendar[0] != date(2018, 1, 2) or calendar[-1] != date(2023, 12, 29):
        raise ChinaTrendError("authoritative evaluation calendar changed")
    external_root = Path("/Volumes/quant/CY_quant_research")
    with tempfile.TemporaryDirectory(prefix="china_trend_v1_", dir=external_root) as raw_temp:
        monthly, source_audit = _monthly_signal_panel(
            current_paths, prehistory, Path(raw_temp)
        )
    scores, coefficients, model_diagnostics = _fit_recursive_expected_return(monthly)
    feature, feature_diagnostics = _evaluation_feature(scores)
    sampled = _sample_plans(feature, calendar)
    events, action_audit = CA._load_risk_events(ca_spec, calendar)
    generation_plans = sampled.loc[
        sampled.signal_date.map(lambda value: value.year).isin(GENERATION_YEARS)
    ]
    generation_evaluated = BASE._evaluate_plans(
        generation_plans, current_paths, calendar, events
    )
    generation = BASE._period_summary(generation_evaluated, GENERATION_YEARS)
    generation_gates = BASE._gate(
        generation, spec["cheap_screen"]["generation_gate_all_required"], False
    )
    generation_passed = all(generation_gates.values())
    evaluated_frames = [generation_evaluated]
    validation_opened = generation_passed
    validation: dict[str, Any] | None = None
    validation_gates: dict[str, bool] | None = None
    validation_passed = False
    if validation_opened:
        validation_plans = sampled.loc[
            sampled.signal_date.map(lambda value: value.year).isin(VALIDATION_YEARS)
        ]
        validation_evaluated = BASE._evaluate_plans(
            validation_plans, current_paths, calendar, events
        )
        evaluated_frames.append(validation_evaluated)
        validation = BASE._period_summary(validation_evaluated, VALIDATION_YEARS)
        validation_gates = BASE._gate(
            validation, spec["cheap_screen"]["validation_gate_all_required"], True
        )
        validation_passed = all(validation_gates.values())
    screen = pd.concat(evaluated_frames, ignore_index=True).sort_values(
        ["signal_date", "arm", "signal_rank", "symbol"]
    )
    replay: dict[str, Any] | None = None
    equity = pd.DataFrame()
    target_met = False
    if generation_passed and validation_passed:
        portfolio_plans = BASE._portfolio_plans(feature, sampled)
        market_rows = CA.PRIOR._query_execution_rows(
            current_paths, portfolio_plans, calendar
        )
        replay, equity = BASE._replay(
            portfolio_plans, market_rows, calendar, events
        )
        target = spec["success_target"]
        target_met = bool(
            replay["annualized_return"] >= target["minimum_annualized_return"]
            and replay["maximum_drawdown"]
            > target["maximum_drawdown_must_be_greater_than"]
        )
    status = (
        "TARGET_ACHIEVED"
        if target_met
        else "REPLAY_TARGET_NOT_MET"
        if replay is not None
        else "VALIDATION_REJECTED"
        if validation_opened
        else "GENERATION_REJECTED_VALIDATION_UNOPENED"
    )
    _atomic_write(
        COEFFICIENT_PATH,
        coefficients.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    _atomic_write(
        SCREEN_PATH,
        screen.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    _atomic_write(
        EQUITY_PATH,
        equity.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    result = {
        "experiment_id": EXPERIMENT_ID,
        "status": status,
        "claim_boundary": spec["claim_boundary"],
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
        "maximum_outcome_date": "2023-12-29",
        "prehistory_role": "2013-2017_MODEL_WARMUP_ONLY",
        "input_identity": input_identity,
        "source_audit": source_audit,
        "model_diagnostics": model_diagnostics,
        "feature_diagnostics": feature_diagnostics,
        "action_audit": action_audit,
        "sampled_signal_dates": int(sampled.signal_date.nunique()),
        "generation": generation,
        "generation_gates": generation_gates,
        "generation_passed": generation_passed,
        "validation_opened": validation_opened,
        "validation": validation,
        "validation_gates": validation_gates,
        "validation_passed": validation_passed,
        "replay": replay,
        "target": spec["success_target"],
        "target_met": target_met,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "prehistory_manifest_sha256": sha256_file(PREHISTORY_MANIFEST_PATH),
            "coefficients_sha256": sha256_file(COEFFICIENT_PATH),
            "screen_sha256": sha256_file(SCREEN_PATH),
            "equity_sha256": sha256_file(EQUITY_PATH),
        },
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
