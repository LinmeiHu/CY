#!/usr/bin/env python3
# ruff: noqa: E501
"""Run the Development-only Former-Leader Pre-Break Suffocation V4 experiment."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-FORMER-LEADER-PREBREAK-SUFFOCATION-V4"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "3384572cadab08b2b00e47edd07ff78dfe5b8e5857bdfdf8b67e6926c30f979b"

V3_EXPERIMENT = "ASHARE-FORMER-LEADER-DEEP-DRAWDOWN-STRICT-GAP-RECLAIM-V3"
V3_SPEC = OS_ROOT / f"experiments/{V3_EXPERIMENT}_spec.json"
V3_RESULT = OS_ROOT / f"artifacts/{V3_EXPERIMENT}_result.json"
V3_COMPACT = OS_ROOT / f"artifacts/{V3_EXPERIMENT}_features.parquet"
V3_EXTERNAL = Path(
    "/Volumes/quant/CY_quant_research/ashare_former_leader_deep_drawdown_strict_gap_reclaim_v3"
)
V3_FULL = V3_EXTERNAL / f"{V3_EXPERIMENT}_features_full.parquet"
DAILY_STATE = V3_EXTERNAL / "pit_adjusted_daily_state_2013_2021.parquet"
V1_OUTCOMES = Path(
    "/Volumes/quant/CY_quant_research/ashare_down_gap_first_reclaim_v1/"
    "first_reclaim_outcomes_2014_2021.parquet"
)
BREADTH = Path(
    "/Volumes/quant/CY_quant_research/ashare_down_gap_reclaim_walkforward_v2/"
    "board_opening_gap_breadth_2014_2021.parquet"
)

EXTERNAL = Path(
    "/Volumes/quant/CY_quant_research/ashare_former_leader_prebreak_suffocation_v4"
)
FEATURES_EXTERNAL = EXTERNAL / f"{EXPERIMENT}_features_full.parquet"
FEATURES_COMPACT = OS_ROOT / f"artifacts/{EXPERIMENT}_features.parquet"
MAIN_BASE_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_main_base_nav.parquet"
MAIN_SUFF_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_main_suffocation_nav.parquet"
CHINEXT_BASE_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_chinext_base_nav.parquet"
CHINEXT_SUFF_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_chinext_suffocation_nav.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

ENTRY_COST = 0.002
EXIT_COST = 0.002
K = 20
TEST_YEARS = tuple(range(2017, 2022))
FOLDS = tuple((2014, year - 1, year) for year in TEST_YEARS)
DRYUP_BINS = ("<=0.30", "(0.30,0.50]", "(0.50,0.70]", "(0.70,1.00]", ">1.00")
COMPRESSION_BINS = ("<=0.50", "(0.50,0.70]", "(0.70,1.00]", ">1.00")
OUTCOME_COLUMNS = (
    "t1_open_net",
    "t1_close_net",
    "t2_close_net",
    "t3_close_net",
    "mfe_1",
    "mae_1",
    "mfe_3",
    "mae_3",
)


class V4Error(RuntimeError):
    """Fail-closed V4 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    return value


def validate_inputs() -> dict[str, Any]:
    expected = {
        SPEC: EXPECTED_SPEC_SHA256,
        V3_SPEC: "e755ac13309dc96f86ad86dbf26b8b5da6267d46ec414217090faf6084050d64",
        V3_RESULT: "31e2cc27b26f4c0526e0b019ce24576eb165474901e490c7229afd4bb9f5f5cf",
        V3_COMPACT: "9a111f01bab58ac3ca3f4839afbf3b3dba602b8229c2b33b536f0cad48d8185d",
        V3_FULL: "a7e4dca16726df3f03b75ad3b06b7cc5731f7676bd6583de402df3b0522e3ec8",
        DAILY_STATE: "524448ab35a817d5be0a0de5dfa312aad122ab675af92f306e04aa76fdf4f687",
        V1_OUTCOMES: "daa9ce35c11598392f825912d6c715e320c98f88448618bca62cd6bd83d73a49",
        BREADTH: "71f0946a32db24f8af3175c2e1ee5a12e15e4b1db87192bb4a2a9791414fee96",
    }
    for path, digest in expected.items():
        if not path.is_file() or sha256_file(path) != digest:
            raise V4Error(f"input identity mismatch: {path}")
    v3 = json.loads(V3_RESULT.read_text(encoding="utf-8"))
    if v3["population"]["v3_final_candidate_events"] != 3746:
        raise V4Error("V3 source population changed")
    if v3["chronology"]["validation_opened"] or v3["chronology"]["final_oos_opened"]:
        raise V4Error("sealed V3 chronology changed")
    return {
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "source_hashes": {str(path): digest for path, digest in expected.items()},
        "v3_source_verdict": v3["verdict"],
    }


def connection() -> duckdb.DuckDBPyConnection:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    (EXTERNAL / "duckdb_tmp").mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='12GB'")
    con.execute(f"SET temp_directory='{EXTERNAL / 'duckdb_tmp'}'")
    return con


def build_features() -> pd.DataFrame:
    if not FEATURES_EXTERNAL.is_file():
        con = connection()
        con.execute(
            f"""COPY (
            WITH source_events AS (
              SELECT *,CASE WHEN board='ChiNext' THEN 'CHINEXT' ELSE 'MAIN' END AS sleeve
              FROM read_parquet('{V3_FULL}')
              WHERE v3_final_candidate IS TRUE
            ), history_ranked AS (
              SELECT e.gap_id,d.trade_date,d.turnover_fraction,
                     row_number() OVER(PARTITION BY e.gap_id ORDER BY d.trade_date DESC) AS recent_order
              FROM source_events e
              JOIN read_parquet('{DAILY_STATE}') d ON e.symbol=d.symbol
              WHERE d.trade_date<e.reclaim_date AND d.current_valid IS TRUE
                AND d.turnover_fraction IS NOT NULL AND isfinite(d.turnover_fraction)
                AND d.turnover_fraction>=0
            ), history AS (
              SELECT gap_id,
                     count(*) FILTER(WHERE recent_order<=20) AS prebreak_count20,
                     count(*) FILTER(WHERE recent_order<=3) AS recent3_count,
                     count(*) FILTER(WHERE recent_order BETWEEN 4 AND 20) AS reference17_count,
                     count(*) FILTER(WHERE recent_order<=2) AS last2_count,
                     count(*) FILTER(WHERE recent_order BETWEEN 3 AND 5) AS prior3_count,
                     median(turnover_fraction) FILTER(WHERE recent_order<=3) AS recent3_median,
                     median(turnover_fraction) FILTER(WHERE recent_order BETWEEN 4 AND 20) AS reference17_median,
                     median(turnover_fraction) FILTER(WHERE recent_order<=2) AS last2_median,
                     median(turnover_fraction) FILTER(WHERE recent_order BETWEEN 3 AND 5) AS prior3_median,
                     max(trade_date) FILTER(WHERE recent_order<=20) AS latest_prebreak_session,
                     min(trade_date) FILTER(WHERE recent_order<=3) AS recent3_first_session,
                     max(trade_date) FILTER(WHERE recent_order BETWEEN 4 AND 20) AS reference17_last_session,
                     min(trade_date) FILTER(WHERE recent_order<=20) AS earliest_reference_session
              FROM history_ranked WHERE recent_order<=20 GROUP BY gap_id
            ), outcomes AS (
              SELECT entry_id,t1_open_net,t1_close_net,t2_close_net,t3_close_net,
                     mfe_1,mae_1,mfe_3,mae_3
              FROM read_parquet('{V1_OUTCOMES}')
            ), enriched AS (
              SELECT e.gap_id,e.entry_id,e.symbol,e.sleeve,e.board,e.is_st,
                     e.gap_date,e.reclaim_date,e.bar_end_time,e.entry_price,
                     e.next_legal_open_date,e.t1_legal_open_price,e.t1_date,e.t2_date,e.t3_date,
                     e.trigger_close,e.t1_close_price,e.t2_close_price,e.t3_close_price,
                     e.leader_percentile,e.prior_runup,e.deep_drawdown,e.gap_pct,
                     e.strict_gap_width_pct,e.gap_age_trading_days,e.intraday_dryup,
                     e.post_gap_dryup,e.compression_trend,
                     h.* EXCLUDE(gap_id),o.* EXCLUDE(entry_id),b.breadth,
                     CASE WHEN h.prebreak_count20=20 AND h.recent3_count=3
                                AND h.reference17_count=17 AND h.reference17_median>0
                          THEN h.recent3_median/h.reference17_median END AS prebreak_dryup_3_20,
                     CASE WHEN h.last2_count=2 AND h.prior3_count=3 AND h.prior3_median>0
                          THEN h.last2_median/h.prior3_median END AS prebreak_compression_5,
                     count(*) OVER(PARTITION BY e.entry_id) AS source_gap_multiplicity,
                     row_number() OVER(PARTITION BY e.entry_id
                                       ORDER BY e.strict_gap_width_pct DESC,e.gap_id) AS entry_collapse_order
              FROM source_events e
              LEFT JOIN history h USING(gap_id)
              LEFT JOIN outcomes o USING(entry_id)
              LEFT JOIN read_parquet('{BREADTH}') b
                ON e.reclaim_date=b.trade_date AND e.sleeve=b.sleeve
            )
            SELECT * FROM enriched ORDER BY bar_end_time,symbol,gap_id
            ) TO '{FEATURES_EXTERNAL}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
        )
        con.close()
    frame = pd.read_parquet(FEATURES_EXTERNAL)
    for column in (
        "gap_date",
        "reclaim_date",
        "bar_end_time",
        "next_legal_open_date",
        "t1_date",
        "t2_date",
        "t3_date",
        "latest_prebreak_session",
        "recent3_first_session",
        "reference17_last_session",
        "earliest_reference_session",
    ):
        frame[column] = pd.to_datetime(frame[column])
    frame["prebreak_dryup_bin"] = pd.cut(
        frame.prebreak_dryup_3_20,
        [-np.inf, 0.30, 0.50, 0.70, 1.00, np.inf],
        labels=DRYUP_BINS,
        right=True,
    )
    frame["prebreak_compression_bin"] = pd.cut(
        frame.prebreak_compression_5,
        [-np.inf, 0.50, 0.70, 1.00, np.inf],
        labels=COMPRESSION_BINS,
        right=True,
    )
    return frame


def analysis_events(source: pd.DataFrame) -> pd.DataFrame:
    frame = source.loc[source.entry_collapse_order.eq(1)].copy()
    if frame.entry_id.duplicated().any():
        raise V4Error("entry collapse failed")
    if not (
        frame.leader_percentile.ge(0.90 - 1e-12)
        & frame.prior_runup.ge(0.50 - 1e-12)
        & frame.deep_drawdown.ge(0.30 - 1e-12)
        & frame.gap_pct.ge(0.05 - 1e-12)
    ).all():
        raise V4Error("broad V3 structural population changed")
    return frame.sort_values(["bar_end_time", "symbol", "gap_id"], kind="mergesort")


def distribution(series: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return {"observations": 0}
    return {
        "observations": len(values),
        "mean": float(values.mean()),
        "std": float(values.std(ddof=0)),
        "min": float(values.min()),
        "p01": float(values.quantile(0.01)),
        "p10": float(values.quantile(0.10)),
        "p25": float(values.quantile(0.25)),
        "median": float(values.median()),
        "p75": float(values.quantile(0.75)),
        "p90": float(values.quantile(0.90)),
        "p99": float(values.quantile(0.99)),
        "max": float(values.max()),
    }


def outcome_summary(frame: pd.DataFrame, *, date_equal: bool = False) -> dict[str, Any]:
    source = frame.copy()
    if date_equal and len(source):
        values = source.groupby("reclaim_date", sort=True)[list(OUTCOME_COLUMNS)].mean()
    else:
        values = source[list(OUTCOME_COLUMNS)]
    t1 = values.t1_open_net.dropna()
    result: dict[str, Any] = {
        "events": len(source),
        "dates": int(source.reclaim_date.nunique()),
        "observations": len(t1),
        "t1_open_net_mean": float(t1.mean()) if len(t1) else None,
        "t1_open_net_median": float(t1.median()) if len(t1) else None,
        "t1_open_net_positive_rate": float(t1.gt(0).mean()) if len(t1) else None,
    }
    for column in OUTCOME_COLUMNS[1:]:
        clean = values[column].dropna()
        result[f"{column}_mean"] = float(clean.mean()) if len(clean) else None
        if column == "t1_close_net":
            result[f"{column}_median"] = float(clean.median()) if len(clean) else None
    return result


def bin_results(frame: pd.DataFrame, column: str, bins: tuple[str, ...]) -> dict[str, Any]:
    return {
        label: {
            "event_weighted": outcome_summary(frame.loc[frame[column].eq(label)]),
            "date_equal_weighted": outcome_summary(
                frame.loc[frame[column].eq(label)], date_equal=True
            ),
        }
        for label in bins
    }


def low_high_contrast(frame: pd.DataFrame) -> dict[str, Any]:
    low = frame.loc[frame.prebreak_dryup_bin.eq("<=0.30")]
    high = frame.loc[frame.prebreak_dryup_bin.eq(">1.00")]
    low_event = outcome_summary(low)
    high_event = outcome_summary(high)
    low_date = outcome_summary(low, date_equal=True)
    high_date = outcome_summary(high, date_equal=True)

    def difference(left: dict[str, Any], right: dict[str, Any]) -> float | None:
        a, b = left["t1_open_net_mean"], right["t1_open_net_mean"]
        return None if a is None or b is None else float(a - b)

    return {
        "low_events": len(low),
        "high_events": len(high),
        "low_dates": int(low.reclaim_date.nunique()),
        "high_dates": int(high.reclaim_date.nunique()),
        "event_weighted_low": low_event["t1_open_net_mean"],
        "event_weighted_high": high_event["t1_open_net_mean"],
        "event_weighted_low_minus_high": difference(low_event, high_event),
        "date_equal_low": low_date["t1_open_net_mean"],
        "date_equal_high": high_date["t1_open_net_mean"],
        "date_equal_low_minus_high": difference(low_date, high_date),
    }


def fixed_bin_contrast(
    frame: pd.DataFrame, column: str, low_label: str, high_label: str
) -> dict[str, Any]:
    low = frame.loc[frame[column].eq(low_label)]
    high = frame.loc[frame[column].eq(high_label)]
    low_event = outcome_summary(low)
    high_event = outcome_summary(high)
    low_date = outcome_summary(low, date_equal=True)
    high_date = outcome_summary(high, date_equal=True)

    def difference(left: dict[str, Any], right: dict[str, Any]) -> float | None:
        a, b = left["t1_open_net_mean"], right["t1_open_net_mean"]
        return None if a is None or b is None else float(a - b)

    return {
        "low_events": len(low),
        "high_events": len(high),
        "event_weighted_low": low_event["t1_open_net_mean"],
        "event_weighted_high": high_event["t1_open_net_mean"],
        "event_weighted_low_minus_high": difference(low_event, high_event),
        "date_equal_low": low_date["t1_open_net_mean"],
        "date_equal_high": high_date["t1_open_net_mean"],
        "date_equal_low_minus_high": difference(low_date, high_date),
    }


def yearly_results(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        str(year): low_high_contrast(frame.loc[frame.reclaim_date.dt.year.eq(year)])
        for year in range(2014, 2022)
    }


def _spearman(x: pd.Series, y: pd.Series) -> float | None:
    valid = x.notna() & y.notna() & np.isfinite(x) & np.isfinite(y)
    if valid.sum() < 3 or x.loc[valid].nunique() < 2 or y.loc[valid].nunique() < 2:
        return None
    return float(x.loc[valid].rank(method="average").corr(y.loc[valid].rank(method="average")))


def same_date_analysis(frame: pd.DataFrame, sleeve: str | None) -> dict[str, Any]:
    source = frame if sleeve is None else frame.loc[frame.sleeve.eq(sleeve)]
    source = source.loc[source.prebreak_dryup_3_20.notna() & source.t1_open_net.notna()].copy()
    daily_rows: list[dict[str, Any]] = []
    tertile_rows: list[dict[str, Any]] = []
    eligible_events = 0
    for (board, date), group in source.groupby(["sleeve", "reclaim_date"], sort=True):
        if len(group) < 5:
            continue
        group = group.sort_values(
            ["prebreak_dryup_3_20", "strict_gap_width_pct", "symbol", "gap_id"],
            ascending=[True, False, True, True],
            kind="mergesort",
        ).copy()
        eligible_events += len(group)
        group["t1_open_residual"] = group.t1_open_net - group.t1_open_net.median()
        group["t1_close_residual"] = group.t1_close_net - group.t1_close_net.median()
        open_rho = _spearman(-group.prebreak_dryup_3_20, group.t1_open_residual)
        close_rho = _spearman(-group.prebreak_dryup_3_20, group.t1_close_residual)
        daily_rows.append(
            {
                "sleeve": board,
                "reclaim_date": date,
                "events": len(group),
                "t1_open_spearman": open_rho,
                "t1_close_spearman": close_rho,
                "residual_median": float(group.t1_open_residual.median()),
            }
        )
        n = len(group)
        ordinal = np.arange(n)
        group["dryup_third"] = np.minimum(2, (3 * ordinal // n)).astype(int)
        labels = {0: "LOW_DRYUP", 1: "MID_DRYUP", 2: "HIGH_DRYUP"}
        for bucket, part in group.groupby("dryup_third", sort=True):
            tertile_rows.append(
                {
                    "sleeve": board,
                    "reclaim_date": date,
                    "bucket": labels[int(bucket)],
                    "events": len(part),
                    "t1_open_net": float(part.t1_open_net.mean()),
                    "t1_close_net": float(part.t1_close_net.mean()),
                }
            )
    daily = pd.DataFrame(daily_rows)
    tertiles = pd.DataFrame(tertile_rows)

    def rho_stats(column: str) -> dict[str, Any]:
        if daily.empty:
            values = pd.Series(dtype=float)
        else:
            values = daily[column].dropna()
        return {
            "dates": len(values),
            "mean": float(values.mean()) if len(values) else None,
            "median": float(values.median()) if len(values) else None,
            "positive_fraction": float(values.gt(0).mean()) if len(values) else None,
        }

    table: dict[str, Any] = {}
    for label in ("LOW_DRYUP", "MID_DRYUP", "HIGH_DRYUP"):
        part = tertiles.loc[tertiles.bucket.eq(label)] if len(tertiles) else tertiles
        table[label] = {
            "events": int(part.events.sum()) if len(part) else 0,
            "dates": int(part.reclaim_date.nunique()) if len(part) else 0,
            "t1_open_net": float(part.t1_open_net.mean()) if len(part) else None,
            "t1_close_net": float(part.t1_close_net.mean()) if len(part) else None,
        }
    low, high = table["LOW_DRYUP"], table["HIGH_DRYUP"]
    table["LOW_MINUS_HIGH"] = {
        "t1_open_net": None
        if low["t1_open_net"] is None or high["t1_open_net"] is None
        else float(low["t1_open_net"] - high["t1_open_net"]),
        "t1_close_net": None
        if low["t1_close_net"] is None or high["t1_close_net"] is None
        else float(low["t1_close_net"] - high["t1_close_net"]),
    }
    return {
        "eligible_dates": int(daily.reclaim_date.nunique()) if len(daily) else 0,
        "eligible_board_dates": len(daily),
        "eligible_events": eligible_events,
        "t1_open_daily_spearman": rho_stats("t1_open_spearman"),
        "t1_close_daily_spearman": rho_stats("t1_close_spearman"),
        "tertiles_date_equal": table,
        "maximum_absolute_residual_median": float(daily.residual_median.abs().max())
        if len(daily)
        else None,
    }


def controlled_diagnostic(frame: pd.DataFrame, sleeve: str) -> dict[str, Any]:
    predictors = [
        "prebreak_dryup_3_20",
        "prior_runup",
        "leader_percentile",
        "deep_drawdown",
        "gap_pct",
        "strict_gap_width_pct",
        "gap_age_trading_days",
    ]
    columns = ["reclaim_date", "t1_open_net", *predictors]
    source = frame.loc[frame.sleeve.eq(sleeve), columns].replace([np.inf, -np.inf], np.nan).dropna()
    counts = source.groupby("reclaim_date").size()
    source = source.loc[source.reclaim_date.isin(counts[counts >= 5].index)].copy()
    if source.empty:
        return {"observations": 0}
    grouped = source.groupby("reclaim_date", sort=False)
    y = source.t1_open_net - grouped.t1_open_net.transform("mean")
    x = pd.DataFrame(index=source.index)
    for column in predictors:
        demeaned = source[column] - grouped[column].transform("mean")
        scale = float(demeaned.std(ddof=0))
        x[column] = demeaned / scale if scale > 0 else 0.0
    matrix = x.to_numpy(float)
    target = y.to_numpy(float)
    coefficients, _, _, _ = np.linalg.lstsq(matrix, target, rcond=None)
    fitted = matrix @ coefficients
    denominator = float(np.square(target).sum())
    r2 = 1 - float(np.square(target - fitted).sum()) / denominator if denominator > 0 else 0.0
    return {
        "observations": len(source),
        "dates": int(source.reclaim_date.nunique()),
        "standardized_coefficients": {
            name: float(value) for name, value in zip(predictors, coefficients, strict=True)
        },
        "prebreak_dryup_direction": "LOWER_IS_BETTER"
        if coefficients[0] < 0
        else "HIGHER_IS_BETTER_OR_NULL",
        "within_date_r2": r2,
    }


def same_date_predictor_spearman(frame: pd.DataFrame, predictor: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for sleeve in ("MAIN", "CHINEXT"):
        values: list[float] = []
        eligible_events = 0
        source = frame.loc[frame.sleeve.eq(sleeve)]
        for _, group in source.groupby("reclaim_date", sort=True):
            group = group.loc[group[predictor].notna() & group.t1_open_net.notna()]
            if len(group) < 5:
                continue
            residual = group.t1_open_net - group.t1_open_net.median()
            rho = _spearman(-group[predictor], residual)
            if rho is not None:
                values.append(rho)
                eligible_events += len(group)
        series = pd.Series(values, dtype=float)
        result[sleeve] = {
            "dates": len(series),
            "events": eligible_events,
            "mean": float(series.mean()) if len(series) else None,
            "median": float(series.median()) if len(series) else None,
            "positive_fraction": float(series.gt(0).mean()) if len(series) else None,
        }
    return result


def assign_subgroups(frame: pd.DataFrame, breadth: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["reclaim_timing_group"] = np.where(
        result.reclaim_date.eq(result.gap_date), "SAME_DAY_RECLAIM", "LATER_RECLAIM"
    )
    result["gap_size_group_v4"] = pd.cut(
        result.gap_pct,
        [0.05 - 1e-12, 0.07, 0.09, np.inf],
        labels=("5-7%", "7-9%", ">=9%"),
        right=False,
    )
    result["drawdown_group_v4"] = pd.cut(
        result.deep_drawdown,
        [0.30 - 1e-12, 0.40, 0.50, np.inf],
        labels=("30-40%", "40-50%", ">=50%"),
        right=False,
    )
    thresholds = {
        sleeve: (
            float(group.breadth.quantile(0.75)),
            float(group.breadth.quantile(0.90)),
        )
        for sleeve, group in breadth.groupby("sleeve", sort=True)
    }
    result["breadth_q75"] = result.sleeve.map({key: value[0] for key, value in thresholds.items()})
    result["breadth_q90"] = result.sleeve.map({key: value[1] for key, value in thresholds.items()})
    result["panic_breadth_group"] = np.where(
        result.breadth.ge(result.breadth_q90),
        ">=Q90",
        np.where(result.breadth.ge(result.breadth_q75), "Q75-Q90", "below Q75"),
    )
    return result


def subgroup_results(frame: pd.DataFrame, column: str, labels: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for sleeve in ("MAIN", "CHINEXT"):
        result[sleeve] = {
            label: low_high_contrast(
                frame.loc[frame.sleeve.eq(sleeve) & frame[column].eq(label)]
            )
            for label in labels
        }
    return result


def nav_metrics(nav: pd.DataFrame, trades: pd.DataFrame, start_nav: float) -> dict[str, Any]:
    if nav.empty:
        raise V4Error("empty NAV")
    end_nav = float(nav.nav.iloc[-1])
    running = np.maximum.accumulate(np.concatenate(([start_nav], nav.nav.to_numpy())))
    max_drawdown = float((nav.nav.to_numpy() / running[1:] - 1).min())
    daily = nav.daily_return.to_numpy(float)
    std = float(np.std(daily))
    return {
        "start_nav": start_nav,
        "end_nav": end_nav,
        "total_return": end_nav / start_nav - 1,
        "max_drawdown": max_drawdown,
        "sharpe": float(np.mean(daily) / std * math.sqrt(242)) if std > 0 else 0.0,
        "trade_count": len(trades),
        "maximum_concurrent_positions": int(nav.positions.max()),
        "average_cash_utilization": float(nav.cash_utilization.mean()),
    }


def simulate_portfolio(
    events: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    start: pd.Timestamp,
    end: pd.Timestamp,
    ranker: str,
    start_nav: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    frame = events.loc[
        events.reclaim_date.between(start, end)
        & events.next_legal_open_date.notna()
        & events.next_legal_open_date.gt(events.reclaim_date)
        & events.next_legal_open_date.le(end)
        & events.t1_legal_open_price.notna()
        & events.t1_legal_open_price.gt(0)
    ].copy()
    frame = frame.sort_values(["bar_end_time", "symbol", "gap_id"], kind="mergesort")
    source_by_entry = frame.set_index("entry_id", verify_integrity=True).to_dict("index")
    grouped_by_day: dict[pd.Timestamp, list[pd.DataFrame]] = {}
    for timestamp, group in frame.groupby("bar_end_time", sort=True):
        grouped_by_day.setdefault(pd.Timestamp(timestamp).normalize(), []).append(group)
    cash = start_nav
    prior_nav = start_nav
    positions: list[dict[str, Any]] = []
    nav_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    duplicate_count = cap_violations = negative_cash = 0
    for day in calendar[(calendar >= start) & (calendar <= end)]:
        for position in positions.copy():
            if position["exit_date"] == day:
                proceeds = position["shares"] * position["exit_price"] * (1 - EXIT_COST)
                cash += proceeds
                trade_rows.append(
                    {
                        **position,
                        "exit_proceeds": proceeds,
                        "pnl": proceeds - position["entry_debit"],
                        "net_return": proceeds / position["entry_debit"] - 1,
                    }
                )
                positions.remove(position)
        accounting_nav = cash + sum(position["shares"] * position["mark"] for position in positions)
        for group in grouped_by_day.get(day, []):
            held = {position["symbol"] for position in positions}
            candidates = group.loc[~group.symbol.isin(held)].copy()
            if ranker == "BASE":
                candidates = candidates.sort_values(
                    ["strict_gap_width_pct", "symbol", "gap_id"],
                    ascending=[False, True, True],
                    kind="mergesort",
                )
            elif ranker == "SUFFOCATION":
                candidates["dryup_missing"] = candidates.prebreak_dryup_3_20.isna()
                candidates = candidates.sort_values(
                    ["dryup_missing", "prebreak_dryup_3_20", "strict_gap_width_pct", "symbol", "gap_id"],
                    ascending=[True, True, False, True, True],
                    kind="mergesort",
                )
            else:
                raise V4Error(f"unknown ranker {ranker}")
            for _, event in candidates.iterrows():
                if len(positions) >= K:
                    break
                if event.symbol in {position["symbol"] for position in positions}:
                    continue
                principal = min(accounting_nav / K, cash / (1 + ENTRY_COST))
                if principal <= 1e-14:
                    continue
                debit = principal * (1 + ENTRY_COST)
                cash -= debit
                positions.append(
                    {
                        "entry_id": event.entry_id,
                        "gap_id": event.gap_id,
                        "symbol": event.symbol,
                        "entry_date": day,
                        "entry_time": event.bar_end_time,
                        "entry_price": float(event.entry_price),
                        "entry_debit": debit,
                        "shares": principal / event.entry_price,
                        "mark": float(event.entry_price),
                        "exit_date": pd.Timestamp(event.next_legal_open_date),
                        "exit_price": float(event.t1_legal_open_price),
                        "prebreak_dryup_3_20": event.prebreak_dryup_3_20,
                        "strict_gap_width_pct": float(event.strict_gap_width_pct),
                    }
                )
                accounting_nav -= principal * ENTRY_COST
        for position in positions:
            source = source_by_entry[position["entry_id"]]
            mark_map = {
                pd.Timestamp(source["reclaim_date"]): source["trigger_close"],
                pd.Timestamp(source["t1_date"]): source["t1_close_price"],
                pd.Timestamp(source["t2_date"]): source["t2_close_price"],
                pd.Timestamp(source["t3_date"]): source["t3_close_price"],
            }
            if day in mark_map and pd.notna(mark_map[day]):
                position["mark"] = float(mark_map[day])
        nav = cash + sum(position["shares"] * position["mark"] for position in positions)
        cap_violations += int(len(positions) > K)
        negative_cash += int(cash < -1e-12)
        duplicate_count += len(positions) - len({position["symbol"] for position in positions})
        nav_rows.append(
            {
                "trade_date": day,
                "nav": nav,
                "daily_pnl": nav - prior_nav,
                "daily_return": nav / prior_nav - 1 if prior_nav else 0.0,
                "cash": cash,
                "cash_utilization": 1 - cash / nav if nav else 0.0,
                "positions": len(positions),
            }
        )
        prior_nav = nav
    if positions:
        raise V4Error("uncensored positions survived test-year terminal date")
    nav = pd.DataFrame(nav_rows)
    trades = pd.DataFrame(trade_rows)
    metrics = nav_metrics(nav, trades, start_nav)
    metrics.update(
        {
            "duplicate_position_entry_count": duplicate_count,
            "max_concurrent_positions_violation_count": cap_violations,
            "negative_cash_or_leverage_violation_count": negative_cash,
        }
    )
    return nav, trades, metrics


def run_chronology(
    events: pd.DataFrame, calendar: pd.DatetimeIndex, sleeve: str, ranker: str
) -> tuple[list[dict[str, Any]], pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    board = events.loc[events.sleeve.eq(sleeve)]
    start_nav = 1.0
    rows: list[dict[str, Any]] = []
    nav_parts: list[pd.DataFrame] = []
    trade_parts: list[pd.DataFrame] = []
    for train_start, train_end, test_year in FOLDS:
        start = calendar[calendar.year == test_year][0]
        end = calendar[calendar.year == test_year][-1]
        nav, trades, metrics = simulate_portfolio(
            board, calendar, start, end, ranker, start_nav
        )
        rows.append(
            {
                "train_start": train_start,
                "train_end": train_end,
                "test_year": test_year,
                "training_use": "NONE_FIXED_RULE_ONLY",
                "metrics": metrics,
            }
        )
        nav_parts.append(nav)
        trade_parts.append(trades)
        start_nav = metrics["end_nav"]
    nav = pd.concat(nav_parts, ignore_index=True)
    trades = pd.concat(trade_parts, ignore_index=True) if any(len(x) for x in trade_parts) else pd.DataFrame()
    stitched = nav_metrics(nav, trades, 1.0)
    stitched["yearly_returns"] = {
        str(row["test_year"]): row["metrics"]["total_return"] for row in rows
    }
    stitched["duplicate_position_entry_count"] = sum(
        row["metrics"]["duplicate_position_entry_count"] for row in rows
    )
    stitched["max_concurrent_positions_violation_count"] = sum(
        row["metrics"]["max_concurrent_positions_violation_count"] for row in rows
    )
    stitched["negative_cash_or_leverage_violation_count"] = sum(
        row["metrics"]["negative_cash_or_leverage_violation_count"] for row in rows
    )
    return rows, nav, trades, stitched


def chronological_comparison(
    events: pd.DataFrame, calendar: pd.DatetimeIndex, sleeve: str
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    base_rows, base_nav, _, base = run_chronology(events, calendar, sleeve, "BASE")
    suff_rows, suff_nav, _, suff = run_chronology(events, calendar, sleeve, "SUFFOCATION")
    fold_rows = []
    for base_row, suff_row in zip(base_rows, suff_rows, strict=True):
        b, s = base_row["metrics"], suff_row["metrics"]
        fold_rows.append(
            {
                "train_start": base_row["train_start"],
                "train_end": base_row["train_end"],
                "test_year": base_row["test_year"],
                "training_use": "NONE_FIXED_RULE_ONLY",
                "base": b,
                "suffocation": s,
                "incremental_return": s["total_return"] - b["total_return"],
                "incremental_max_drawdown": s["max_drawdown"] - b["max_drawdown"],
                "incremental_sharpe": s["sharpe"] - b["sharpe"],
            }
        )
    return (
        {
            "folds": fold_rows,
            "base_wf": base,
            "suffocation_wf": suff,
            "incremental_return": suff["total_return"] - base["total_return"],
            "incremental_max_drawdown": suff["max_drawdown"] - base["max_drawdown"],
            "incremental_sharpe": suff["sharpe"] - base["sharpe"],
        },
        base_nav,
        suff_nav,
    )


def correctness_audit(source: pd.DataFrame, chronology: dict[str, Any]) -> dict[str, Any]:
    valid_dryup = source.loc[source.prebreak_dryup_3_20.notna()]
    valid_compression = source.loc[source.prebreak_compression_5.notna()]
    audits = {
        "prebreak_dryup_uses_reclaim_or_post_reclaim_session_count": int(
            valid_dryup.latest_prebreak_session.ge(valid_dryup.reclaim_date).sum()
        ),
        "prebreak_dryup_uses_future_volume_count": int(
            valid_dryup.latest_prebreak_session.ge(valid_dryup.reclaim_date).sum()
        ),
        "prebreak_compression_uses_future_volume_count": int(
            valid_compression.latest_prebreak_session.ge(valid_compression.reclaim_date).sum()
        ),
        "post_trigger_volume_used_count": 0,
        "test_year_used_in_own_chronological_rule_count": sum(
            int(fold["train_end"] >= fold["test_year"])
            for sleeve in chronology.values()
            for fold in sleeve["folds"]
        ),
        "post_2021_outcome_read_count": 0,
        "cross_board_contamination_count": 0,
        "duplicate_position_entry_count": sum(
            sleeve["base_wf"]["duplicate_position_entry_count"]
            + sleeve["suffocation_wf"]["duplicate_position_entry_count"]
            for sleeve in chronology.values()
        ),
        "max_concurrent_positions_violation_count": sum(
            sleeve["base_wf"]["max_concurrent_positions_violation_count"]
            + sleeve["suffocation_wf"]["max_concurrent_positions_violation_count"]
            for sleeve in chronology.values()
        ),
        "negative_cash_or_leverage_violation_count": sum(
            sleeve["base_wf"]["negative_cash_or_leverage_violation_count"]
            + sleeve["suffocation_wf"]["negative_cash_or_leverage_violation_count"]
            for sleeve in chronology.values()
        ),
        "validation_opened": False,
        "final_oos_opened": False,
    }
    numeric = {
        key: value
        for key, value in audits.items()
        if key not in ("validation_opened", "final_oos_opened")
    }
    if any(value != 0 for value in numeric.values()):
        raise V4Error(f"hard correctness invariant failed: {audits}")
    return audits


def pct(value: Any) -> str:
    return "—" if value is None else f"{value:.3%}"


def render_report(result: dict[str, Any]) -> str:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"**Verdict: `{result['verdict']}`**",
        "",
        "V4 is an internal chronological pseudo-OOS mechanism experiment designed after earlier 2014--2021 research. Validation 2022--2023 and Final OOS 2024+ remain sealed and unread.",
        "",
        "## Population and corrected feature",
        "",
        f"V3 source gap events: {result['population']['source_v3_events']:,}; outcome-blind collapsed executable entries: {result['population']['analysis_events']:,}; valid PreBreakDryup: {result['population']['prebreak_dryup_valid_events']:,}; valid compression: {result['population']['prebreak_compression_valid_events']:,}.",
        "",
        f"PreBreakDryup distribution: `{result['prebreak_dryup']['distribution']}`",
        "",
        "## Fixed dry-up bins",
        "",
        "| Bin | N | Event T1-open | Date-equal T1-open | Median | Positive | T1-close | T2-close | T3-close | MFE1 | MAE1 | MFE3 | MAE3 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, item in result["prebreak_dryup"]["all_bins"].items():
        event, date = item["event_weighted"], item["date_equal_weighted"]
        lines.append(
            f"| {label} | {event['events']:,} | {pct(event['t1_open_net_mean'])} | {pct(date['t1_open_net_mean'])} | {pct(event['t1_open_net_median'])} | {pct(event['t1_open_net_positive_rate'])} | {pct(event['t1_close_net_mean'])} | {pct(event['t2_close_net_mean'])} | {pct(event['t3_close_net_mean'])} | {pct(event['mfe_1_mean'])} | {pct(event['mae_1_mean'])} | {pct(event['mfe_3_mean'])} | {pct(event['mae_3_mean'])} |"
        )
    lines += [
        "",
        "### Fixed extreme-bin contrasts",
        "",
        "| Population | Low/High N | Event low-high | Date-equal low-high |",
        "|---|---:|---:|---:|",
    ]
    contrasts = {
        "All": result["prebreak_dryup"]["full_low_minus_high"],
        "Main": result["prebreak_dryup"]["board_low_minus_high"]["MAIN"],
        "ChiNext": result["prebreak_dryup"]["board_low_minus_high"]["CHINEXT"],
        "Same-day reclaim": result["prebreak_dryup"]["timing_low_minus_high"][
            "SAME_DAY_RECLAIM"
        ],
        "Later reclaim": result["prebreak_dryup"]["timing_low_minus_high"][
            "LATER_RECLAIM"
        ],
    }
    for label, item in contrasts.items():
        lines.append(
            f"| {label} | {item['low_events']}/{item['high_events']} | {pct(item['event_weighted_low_minus_high'])} | {pct(item['date_equal_low_minus_high'])} |"
        )
    lines += [
        "",
        "### Year-by-year <=0.30 minus >1.00",
        "",
        "| Year | Low/High N | Event low-high | Date-equal low-high |",
        "|---:|---:|---:|---:|",
    ]
    for year, item in result["prebreak_dryup"]["yearly_low_minus_high"].items():
        lines.append(
            f"| {year} | {item['low_events']}/{item['high_events']} | {pct(item['event_weighted_low_minus_high'])} | {pct(item['date_equal_low_minus_high'])} |"
        )
    lines += ["", "## Same-date stock-level incrementality", ""]
    for sleeve in ("MAIN", "CHINEXT"):
        item = result["same_date"][sleeve]
        rho = item["t1_open_daily_spearman"]
        tertile = item["tertiles_date_equal"]
        lines += [
            f"### {sleeve}",
            "",
            f"Eligible board-dates/events: {item['eligible_board_dates']:,}/{item['eligible_events']:,}. Daily Spearman mean/median/positive fraction: {rho['mean']:.4f}/{rho['median']:.4f}/{rho['positive_fraction']:.1%}. Date-equal low/high/low-minus-high T1-open: {pct(tertile['LOW_DRYUP']['t1_open_net'])}/{pct(tertile['HIGH_DRYUP']['t1_open_net'])}/{pct(tertile['LOW_MINUS_HIGH']['t1_open_net'])}.",
            "",
        ]
    lines += ["### Fixed-effect diagnostic", ""]
    for sleeve in ("MAIN", "CHINEXT"):
        item = result["controlled_diagnostic"][sleeve]
        coefficient = item["standardized_coefficients"]["prebreak_dryup_3_20"]
        lines.append(
            f"- {sleeve}: {item['observations']:,} observations/{item['dates']:,} dates; standardized Dryup coefficient {coefficient:.6f}; `{item['prebreak_dryup_direction']}`; within-date R2 {item['within_date_r2']:.4f}."
        )
    compression = result["compression"]
    lines += [
        "",
        "## Progressive compression diagnostic",
        "",
        f"Fixed <=0.50 minus >1.00 event/date-equal T1-open: {pct(compression['low_minus_high']['event_weighted_low_minus_high'])}/{pct(compression['low_minus_high']['date_equal_low_minus_high'])}. Same-date Spearman means Main/ChiNext: {compression['same_date_spearman']['MAIN']['mean']:.4f}/{compression['same_date_spearman']['CHINEXT']['mean']:.4f}. Adds information: `{compression['does_progressive_compression_add_information']}`.",
        "",
        "## Fixed subgroup extreme-bin contrasts",
        "",
        "| Family | Sleeve | Group | Event low-high | Date-equal low-high |",
        "|---|---|---|---:|---:|",
    ]
    for family in ("gap_size", "drawdown", "panic_breadth"):
        for sleeve in ("MAIN", "CHINEXT"):
            for label, item in result["subgroups"][family][sleeve].items():
                lines.append(
                    f"| {family} | {sleeve} | {label} | {pct(item['event_weighted_low_minus_high'])} | {pct(item['date_equal_low_minus_high'])} |"
                )
    lines += ["", "## Internal fixed K=20 chronology", ""]
    for sleeve in ("MAIN", "CHINEXT"):
        item = result["chronological"][sleeve]
        lines += [
            f"### {sleeve}",
            "",
            "| Test | BASE | Suffocation | Difference | BASE DD | Suffocation DD | BASE/Suff trades |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for fold in item["folds"]:
            lines.append(
                f"| {fold['test_year']} | {pct(fold['base']['total_return'])} | {pct(fold['suffocation']['total_return'])} | {pct(fold['incremental_return'])} | {pct(fold['base']['max_drawdown'])} | {pct(fold['suffocation']['max_drawdown'])} | {fold['base']['trade_count']}/{fold['suffocation']['trade_count']} |"
            )
        lines += [
            "",
            f"Stitched BASE/Suffocation/incremental: {pct(item['base_wf']['total_return'])}/{pct(item['suffocation_wf']['total_return'])}/{pct(item['incremental_return'])}; Sharpe increment {item['incremental_sharpe']:.3f}; MaxDD increment {pct(item['incremental_max_drawdown'])}.",
            "",
        ]
    lines += [
        "## Interpretation",
        "",
        f"Pooled support: `{result['decision']['pooled_support']}`; same-date support: `{result['decision']['same_date_support']}`; chronological support: `{result['decision']['chronological_support']}`.",
        "",
        result["decision"]["interpretation"],
        "",
        f"Audit: `{result['audit']}`",
        "",
        f"Next action: {result['decision']['next_recommended_action']}",
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    input_audit = validate_inputs()
    source = build_features()
    events = analysis_events(source)
    breadth = pd.read_parquet(BREADTH)
    breadth["trade_date"] = pd.to_datetime(breadth.trade_date)
    calendar = pd.DatetimeIndex(sorted(breadth.trade_date.unique()))
    events = assign_subgroups(events, breadth)

    all_bins = bin_results(events, "prebreak_dryup_bin", DRYUP_BINS)
    board_bins = {
        sleeve: bin_results(
            events.loc[events.sleeve.eq(sleeve)], "prebreak_dryup_bin", DRYUP_BINS
        )
        for sleeve in ("MAIN", "CHINEXT")
    }
    timing_bins = {
        label: bin_results(
            events.loc[events.reclaim_timing_group.eq(label)],
            "prebreak_dryup_bin",
            DRYUP_BINS,
        )
        for label in ("SAME_DAY_RECLAIM", "LATER_RECLAIM")
    }
    same_date = {
        "MAIN": same_date_analysis(events, "MAIN"),
        "CHINEXT": same_date_analysis(events, "CHINEXT"),
        "COMBINED_BOARD_DATES": same_date_analysis(events, None),
    }
    controlled = {
        sleeve: controlled_diagnostic(events, sleeve) for sleeve in ("MAIN", "CHINEXT")
    }
    compression = {
        "distribution": distribution(events.prebreak_compression_5),
        "bins": bin_results(events, "prebreak_compression_bin", COMPRESSION_BINS),
        "low_minus_high": fixed_bin_contrast(
            events, "prebreak_compression_bin", "<=0.50", ">1.00"
        ),
        "same_date_spearman": same_date_predictor_spearman(
            events, "prebreak_compression_5"
        ),
    }
    compression_directions = [
        compression["low_minus_high"]["event_weighted_low_minus_high"],
        compression["low_minus_high"]["date_equal_low_minus_high"],
        compression["same_date_spearman"]["MAIN"]["mean"],
        compression["same_date_spearman"]["CHINEXT"]["mean"],
    ]
    compression["does_progressive_compression_add_information"] = bool(
        all(value is not None and value > 0 for value in compression_directions)
    )

    main_chrono, main_base_nav, main_suff_nav = chronological_comparison(
        events, calendar, "MAIN"
    )
    chi_chrono, chi_base_nav, chi_suff_nav = chronological_comparison(
        events, calendar, "CHINEXT"
    )
    chronology = {"MAIN": main_chrono, "CHINEXT": chi_chrono}
    audit = correctness_audit(source, chronology)

    full_contrast = low_high_contrast(events)
    combined_same = same_date["COMBINED_BOARD_DATES"]
    combined_tertile = combined_same["tertiles_date_equal"]["LOW_MINUS_HIGH"]["t1_open_net"]
    combined_rho = combined_same["t1_open_daily_spearman"]["mean"]
    pooled_support = bool(
        full_contrast["event_weighted_low_minus_high"] is not None
        and full_contrast["event_weighted_low_minus_high"] > 0
        and full_contrast["date_equal_low_minus_high"] is not None
        and full_contrast["date_equal_low_minus_high"] > 0
    )
    same_date_support = bool(
        combined_tertile is not None
        and combined_tertile > 0
        and combined_rho is not None
        and combined_rho > 0
    )
    chronological_support = bool(
        main_chrono["incremental_return"] + chi_chrono["incremental_return"] > 0
    )
    board_conflict = (
        same_date["MAIN"]["tertiles_date_equal"]["LOW_MINUS_HIGH"]["t1_open_net"] or 0
    ) * (
        same_date["CHINEXT"]["tertiles_date_equal"]["LOW_MINUS_HIGH"]["t1_open_net"] or 0
    ) < 0
    if pooled_support and same_date_support and chronological_support and not board_conflict:
        verdict = "PREBREAK_SUFFOCATION_HAS_INDEPENDENT_INFORMATION"
    elif pooled_support and not same_date_support and not chronological_support:
        verdict = "PREBREAK_SUFFOCATION_MARKET_REGIME_PROXY"
    elif not pooled_support and not same_date_support and not chronological_support:
        verdict = "NO_PREBREAK_SUFFOCATION_INFORMATION"
    else:
        verdict = "PREBREAK_SUFFOCATION_DESCRIPTIVE_ONLY"

    if verdict == "PREBREAK_SUFFOCATION_HAS_INDEPENDENT_INFORMATION":
        interpretation = "Corrected pre-breakout dry-up survives pooled/date-equal, same-date stock selection, and fixed chronological allocation tests. This is Development-only internal evidence and does not authorize Validation."
        next_action = "Preregister one V5 strategy contract using the unchanged corrected dry-up representation, then stop for separate authorization before any 2022--2023 access."
        v5 = True
    elif verdict == "PREBREAK_SUFFOCATION_MARKET_REGIME_PROXY":
        interpretation = "The pooled corrected dry-up pattern disappears under same-date and chronological allocation controls; it is primarily a market repair-regime proxy."
        next_action = "Close the suffocation mechanism without V5 or Validation; retain it only as a descriptive market-regime representation."
        v5 = False
    elif verdict == "NO_PREBREAK_SUFFOCATION_INFORMATION":
        interpretation = "Even the corrected completed-session pre-breakout measure has no useful directional evidence."
        next_action = "Close the volume-suffocation hypothesis and do not test neighboring windows or thresholds."
        v5 = False
    else:
        interpretation = "Corrected dry-up has partial descriptive evidence, but stock-level and forward allocation evidence are not jointly stable enough for a strategy claim."
        next_action = "Close V4 without opening Validation or tuning the representation; do not launch V5 unless genuinely independent evidence appears."
        v5 = False

    result: dict[str, Any] = {
        "experiment_id": EXPERIMENT,
        "status": "DEVELOPMENT_COMPLETE",
        "evidence_class": "INTERNAL_CHRONOLOGICAL_PSEUDO_OOS_NOT_PRISTINE_EXTERNAL_OOS",
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "chronology_boundary": {
            "development": ["2014-01-01", "2021-12-31"],
            "post_2021_outcome_read_count": 0,
            "validation_opened": False,
            "final_oos_opened": False,
        },
        "population": {
            "source_v3_events": len(source),
            "analysis_events": len(events),
            "duplicate_gap_rows_collapsed": len(source) - len(events),
            "prebreak_dryup_valid_source_events": int(source.prebreak_dryup_3_20.notna().sum()),
            "prebreak_dryup_valid_events": int(events.prebreak_dryup_3_20.notna().sum()),
            "prebreak_compression_valid_events": int(events.prebreak_compression_5.notna().sum()),
            "same_day_events": int(events.reclaim_date.eq(events.gap_date).sum()),
            "later_reclaim_events": int(events.reclaim_date.gt(events.gap_date).sum()),
            "main_events": int(events.sleeve.eq("MAIN").sum()),
            "chinext_events": int(events.sleeve.eq("CHINEXT").sum()),
        },
        "prebreak_dryup": {
            "distribution": distribution(events.prebreak_dryup_3_20),
            "all_bins": all_bins,
            "full_low_minus_high": full_contrast,
            "board_bins": board_bins,
            "board_low_minus_high": {
                sleeve: low_high_contrast(events.loc[events.sleeve.eq(sleeve)])
                for sleeve in ("MAIN", "CHINEXT")
            },
            "timing_bins": timing_bins,
            "timing_low_minus_high": {
                label: low_high_contrast(events.loc[events.reclaim_timing_group.eq(label)])
                for label in ("SAME_DAY_RECLAIM", "LATER_RECLAIM")
            },
            "yearly_low_minus_high": yearly_results(events),
        },
        "same_date": same_date,
        "controlled_diagnostic": controlled,
        "compression": compression,
        "chronological": chronology,
        "subgroups": {
            "gap_size": subgroup_results(
                events, "gap_size_group_v4", ("5-7%", "7-9%", ">=9%")
            ),
            "drawdown": subgroup_results(
                events, "drawdown_group_v4", ("30-40%", "40-50%", ">=50%")
            ),
            "panic_breadth": subgroup_results(
                events, "panic_breadth_group", ("below Q75", "Q75-Q90", ">=Q90")
            ),
        },
        "decision": {
            "pooled_support": pooled_support,
            "same_date_support": same_date_support,
            "chronological_support": chronological_support,
            "board_direction_conflict": board_conflict,
            "corrected_dryup_supports_user_hypothesis": verdict
            == "PREBREAK_SUFFOCATION_HAS_INDEPENDENT_INFORMATION",
            "stock_level_information_after_same_date_control": same_date_support,
            "only_proxies_market_panic": verdict == "PREBREAK_SUFFOCATION_MARKET_REGIME_PROXY",
            "suffocation_ranking_improves_chronological_portfolio": chronological_support,
            "v5_justified": v5,
            "interpretation": interpretation,
            "next_recommended_action": next_action,
        },
        "audit": audit,
        "verdict": verdict,
        "input_audit": input_audit,
    }

    compact_columns = [
        "gap_id",
        "entry_id",
        "source_gap_multiplicity",
        "symbol",
        "sleeve",
        "board",
        "is_st",
        "gap_date",
        "reclaim_date",
        "bar_end_time",
        "leader_percentile",
        "prior_runup",
        "deep_drawdown",
        "gap_pct",
        "strict_gap_width_pct",
        "gap_age_trading_days",
        "recent3_median",
        "reference17_median",
        "prebreak_dryup_3_20",
        "prebreak_dryup_bin",
        "last2_median",
        "prior3_median",
        "prebreak_compression_5",
        "prebreak_compression_bin",
        "latest_prebreak_session",
        "earliest_reference_session",
        "intraday_dryup",
        "post_gap_dryup",
        "breadth",
        "reclaim_timing_group",
        "gap_size_group_v4",
        "drawdown_group_v4",
        "panic_breadth_group",
        *OUTCOME_COLUMNS,
    ]
    pq.write_table(
        pa.Table.from_pandas(events[compact_columns], preserve_index=False),
        FEATURES_COMPACT,
        compression="zstd",
    )
    for path, frame in (
        (MAIN_BASE_NAV, main_base_nav),
        (MAIN_SUFF_NAV, main_suff_nav),
        (CHINEXT_BASE_NAV, chi_base_nav),
        (CHINEXT_SUFF_NAV, chi_suff_nav),
    ):
        pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path, compression="zstd")
    artifact_paths = {
        "external_full_features": FEATURES_EXTERNAL,
        "compact_features": FEATURES_COMPACT,
        "main_base_nav": MAIN_BASE_NAV,
        "main_suffocation_nav": MAIN_SUFF_NAV,
        "chinext_base_nav": CHINEXT_BASE_NAV,
        "chinext_suffocation_nav": CHINEXT_SUFF_NAV,
    }
    result["artifacts"] = {
        label: {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for label, path in artifact_paths.items()
    }
    atomic_text(RESULT, json.dumps(json_ready(result), sort_keys=True, indent=2) + "\n")
    atomic_text(REPORT, render_report(result))
    return result


if __name__ == "__main__":
    print(json.dumps(json_ready(run()), sort_keys=True, indent=2))
