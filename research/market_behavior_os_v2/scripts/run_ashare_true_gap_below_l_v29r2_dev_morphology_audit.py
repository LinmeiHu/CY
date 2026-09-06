#!/usr/bin/env python3
# ruff: noqa: E501
"""Read-only <=2021 morphology audit for executable V28R2/V29R1 candidates.

The audit never opens a 2022+ partition.  Daily/PIT features are evaluated at
the signal close.  The minute panel ends at the T+1 10:00 observation; minute
features are associations with the already-frozen open-entry outcome and are
not represented as executable 10:00-entry returns.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
MAX_DATE = pd.Timestamp("2021-12-31")

V28_OUTCOMES = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_orderly_demand_v28r2/development/"
    "orderly_demand/outcomes.parquet"
)
V28_SELECTED = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_orderly_demand_v28r2/development/"
    "orderly_demand_selected_entries.parquet"
)
V29_OUTCOMES = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_orderly_demand_issuer_integrity_cooldown_v29r1/"
    "development/issuer_integrity/outcomes.parquet"
)
PARENT_DAILY = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_first_reversal_v13/"
    "prior_high_reversal/development/outcome_daily.parquet"
)

YEARS = (2018, 2019, 2020, 2021)
DAILY_FILES = [
    Path(
        "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/"
        f"daily/partition_year={year}/data_0.parquet"
    )
    for year in YEARS
]
MINUTE_FILES = [
    Path(
        "/Users/linmei/Documents/CY/data/processed/pit_b_minute_2018_2026_v2/"
        f"execution_5m/partition_year={year}/data_0.parquet"
    )
    for year in YEARS
]
CHIP_FILES = [
    Path(
        "/Users/linmei/Documents/CY/data/processed/"
        f"chip_state_features_by_year_2018_2026_v2/year={year}/data.parquet"
    )
    for year in YEARS
]

EXPECTED_HASHES = {
    V28_OUTCOMES: "9df6577d5e89ed0c30295af16b75bc1f16f4649a12c63969d48808384bde2988",
    V28_SELECTED: "963aaae2053c4b62a5060931c757a51bc7776324f14089d4def5502db9e6d112",
    V29_OUTCOMES: "2517fcd0b13fca5b1f784c30e3e4cda819a6c6610116c338cf740a5a7e63f644",
    PARENT_DAILY: "c288f088c26657abc105f291e95217bdf79096bb5bc771cbc9d7e37c108b0d0f",
    DAILY_FILES[0]: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    DAILY_FILES[1]: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    DAILY_FILES[2]: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    DAILY_FILES[3]: "cbd4b2d2ccdff32b09ed1a2e9347f8045cde89ff7e4e1b189577bc353e4d9311",
    MINUTE_FILES[0]: "0b5f3a090a79d31fa723228132f080582d015a197b0fd2496fadfdde43502cf4",
    MINUTE_FILES[1]: "8a34ee395a18a200dd50df728c4448531ff99a20c6b2148f16666daa38a1790f",
    MINUTE_FILES[2]: "292b15641bf374ab27e9c4a812b77f4142223858f31b16dfea34a669a3305036",
    MINUTE_FILES[3]: "b0ef29775404a15680ca176b15c46c0590e0424c0eaf052f0c65b73369458a7d",
    CHIP_FILES[0]: "fdd159a95c63bf4049b808c0a9fb9f200e7b2fb15a2e0a3e7bc1a289b84a3d47",
    CHIP_FILES[1]: "3bc0f5bab82345a30eec213aa2b18e43e555063ab6171e73a7b8282ad4c26a6a",
    CHIP_FILES[2]: "f0cba77ae00f87c6c29e563245300f02c52007b07219569c7c351da190a753f1",
    CHIP_FILES[3]: "0d16d8b72609016aebcf53dce8e3e6a319f1037ba95150ca282f90ed4ce2045a",
}

OUT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_v29r2_development_morphology_audit_v1"
)
FEATURES_CSV = OUT / "candidate_feature_matrix.csv"
WIN_LOSS_CSV = OUT / "winner_loser_comparison.csv"
QUARTILES_CSV = OUT / "feature_quartile_profiles.csv"
RULES_CSV = OUT / "candidate_rule_profiles.csv"
RULE_YEARS_CSV = OUT / "candidate_rule_year_profiles.csv"
LOYO_CSV = OUT / "candidate_rule_leave_one_year_out.csv"
DATE_ROBUSTNESS_CSV = OUT / "candidate_rule_signal_date_robustness.csv"
SUMMARY_JSON = OUT / "summary.json"
MANIFEST_JSON = OUT / "manifest.json"
REPORT = OS_ROOT / "reports/ASHARE-TRUE-GAP-BELOW-L-V29R2-DEVELOPMENT-MORPHOLOGY-AUDIT-V1_report.md"


class AuditError(RuntimeError):
    """Fail-closed audit error."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    result: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise AuditError(f"missing input: {path}")
        actual = sha256(path)
        if actual != expected:
            raise AuditError(f"input drift: {path}: {actual}")
        result[str(path)] = actual
    return result


def sql_paths(paths: list[Path]) -> str:
    return "[" + ",".join(repr(path.as_posix()) for path in paths) + "]"


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(
        path,
        json.dumps(json_ready(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def load_daily_features(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    query = f"""
    WITH o0 AS (
      SELECT *,year(signal_date)::INTEGER AS signal_year
      FROM read_parquet('{V28_OUTCOMES.as_posix()}')
    ), selected AS (
      SELECT gap_id,signal_amount_to_prior20_median
      FROM read_parquet('{V28_SELECTED.as_posix()}')
    ), v29 AS (
      SELECT gap_id FROM read_parquet('{V29_OUTCOMES.as_posix()}')
    ), o AS (
      SELECT o0.*,selected.signal_amount_to_prior20_median,
        v29.gap_id IS NOT NULL AS v29_executable
      FROM o0 JOIN selected USING(gap_id) LEFT JOIN v29 USING(gap_id)
    ), parent_signal AS (
      SELECT o.gap_id,d.coordinate_factor AS signal_coordinate_factor,
        d.coord_close AS parent_signal_coord_close
      FROM o JOIN read_parquet('{PARENT_DAILY.as_posix()}') d
        ON d.symbol=o.symbol AND d.cal_idx=o.signal_cal_idx
      WHERE d.trade_date<=DATE '2021-12-31'
    ), levels AS (
      SELECT o.gap_id,
        min(d.coord_low) FILTER (
          WHERE d.hard_valid=1 AND d.current_valid=1 AND d.history_valid=1
            AND d.current_day_data_tradable=1 AND d.market_rule_valid=1
            AND d.corporate_action_blocking<>1
        ) AS support20,
        max(d.coord_high) FILTER (
          WHERE d.hard_valid=1 AND d.current_valid=1 AND d.history_valid=1
            AND d.current_day_data_tradable=1 AND d.market_rule_valid=1
            AND d.corporate_action_blocking<>1
        ) AS resistance20,
        count(*) FILTER (
          WHERE d.hard_valid=1 AND d.current_valid=1 AND d.history_valid=1
            AND d.current_day_data_tradable=1 AND d.market_rule_valid=1
            AND d.corporate_action_blocking<>1
        ) AS level_n
      FROM o JOIN read_parquet('{PARENT_DAILY.as_posix()}') d
        ON d.symbol=o.symbol
       AND d.cal_idx BETWEEN o.signal_cal_idx-20 AND o.signal_cal_idx-1
      WHERE d.trade_date<=DATE '2021-12-31'
      GROUP BY o.gap_id
    ), daily_valid AS (
      SELECT *,close/preclose-1.0 AS step_return
      FROM read_parquet({sql_paths(DAILY_FILES)})
      WHERE trade_date<=DATE '2021-12-31'
        AND hard_valid AND current_day_data_tradable
        AND available_at<=decision_at AND preclose>0 AND close>0
    ), market0 AS (
      SELECT trade_date,median(step_return) AS market_return,
        avg(CASE WHEN step_return>0 THEN 1.0 ELSE 0.0 END) AS market_up_share
      FROM daily_valid GROUP BY trade_date
    ), market AS (
      SELECT *,
        exp(sum(ln(1+market_return)) OVER (
          ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ))-1 AS market_return_5d
      FROM market0
    ), industry0 AS (
      SELECT trade_date,industry,median(step_return) AS industry_return,
        avg(CASE WHEN step_return>0 THEN 1.0 ELSE 0.0 END) AS industry_up_share,
        count(*) AS industry_members
      FROM daily_valid WHERE industry IS NOT NULL
      GROUP BY trade_date,industry
    ), industry AS (
      SELECT *,
        exp(sum(ln(1+industry_return)) OVER (
          PARTITION BY industry ORDER BY trade_date
          ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ))-1 AS industry_return_5d
      FROM industry0
    )
    SELECT o.*,parent_signal.signal_coordinate_factor,
      levels.support20,levels.resistance20,levels.level_n,
      signal.decision_at,signal.available_at AS signal_available_at,
      signal.industry,signal.close AS signal_raw_close,
      signal.turnover_fraction,signal.step_return AS signal_stock_return,
      market.market_return,market.market_up_share,market.market_return_5d,
      industry.industry_return,industry.industry_up_share,
      industry.industry_members,industry.industry_return_5d,
      turnover.prior20_turnover_median,turnover.prior20_turnover_n,
      chip.trade_date AS chip_trade_date,chip.available_at AS chip_available_at,
      chip.p10 AS chip_p10_raw,chip.p50 AS chip_p50_raw,chip.p90 AS chip_p90_raw,
      chip.profit_ratio AS chip_profit_ratio,
      chip.trapped_ratio AS chip_trapped_ratio,chip.mass_sum AS chip_mass_sum,
      chip.daily_snapshot_id AS chip_daily_snapshot_id,
      chip.minute_snapshot_id AS chip_minute_snapshot_id
    FROM o
    JOIN parent_signal USING(gap_id)
    JOIN levels USING(gap_id)
    JOIN daily_valid signal
      ON signal.symbol=o.symbol AND signal.trade_date=o.signal_date
    JOIN market ON market.trade_date=o.signal_date
    JOIN industry
      ON industry.trade_date=o.signal_date AND industry.industry=signal.industry
    LEFT JOIN LATERAL (
      SELECT median(x.turnover_fraction) AS prior20_turnover_median,
        count(*) AS prior20_turnover_n
      FROM (
        SELECT history.turnover_fraction
        FROM daily_valid history
        WHERE history.symbol=o.symbol AND history.trade_date<o.signal_date
        ORDER BY history.trade_date DESC LIMIT 20
      ) x
    ) turnover ON true
    LEFT JOIN LATERAL (
      SELECT state.*
      FROM read_parquet({sql_paths(CHIP_FILES)}) state
      WHERE state.symbol=o.symbol AND state.trade_date<=DATE '2021-12-31'
        AND state.available_at<=signal.decision_at
        AND state.strict_sample AND state.chip_input_valid
        AND state.daily_hard_valid AND state.minute_hard_valid
        AND state.state_chain_valid
      ORDER BY state.available_at DESC LIMIT 1
    ) chip ON true
    ORDER BY o.signal_date,o.gap_id
    """
    frame = connection.execute(query).fetchdf()
    if len(frame) != 355 or frame.gap_id.nunique() != 355:
        raise AuditError(f"executable universe drift: {len(frame)}")
    if int(frame.v29_executable.sum()) != 298:
        raise AuditError("V29 executable subset drift")
    if not frame.entry_status.eq("EXECUTABLE_ENTRY").all():
        raise AuditError("non-executable row in V28 outcome universe")
    for column in ("signal_date", "entry_date", "exit_date", "chip_trade_date"):
        known = pd.to_datetime(frame[column], errors="coerce").dropna()
        if not known.empty and known.max() > MAX_DATE:
            raise AuditError(f"post-2021 row observed in {column}")
    if (pd.to_datetime(frame.entry_date) <= pd.to_datetime(frame.signal_date)).any():
        raise AuditError("same-bar entry in frozen outcome universe")
    if not frame.level_n.eq(20).all() or not frame.prior20_turnover_n.eq(20).all():
        raise AuditError("incomplete prior20 feature history")
    if (frame.signal_available_at > frame.decision_at).any():
        raise AuditError("daily feature availability exceeds decision_at")
    known_chip = frame.chip_available_at.notna()
    if (frame.loc[known_chip, "chip_available_at"] > frame.loc[known_chip, "decision_at"]).any():
        raise AuditError("chip look-ahead")

    frame["signal_vs_support20"] = frame.signal_coord_close / frame.support20 - 1
    frame["signal_to_l_headroom"] = frame.L / frame.signal_coord_close - 1
    factor = frame.signal_coordinate_factor
    frame["chip_p10_overhead"] = frame.chip_p10_raw * factor / frame.signal_coord_close - 1
    frame["chip_p50_overhead"] = frame.chip_p50_raw * factor / frame.signal_coord_close - 1
    frame["chip_p50_over_l"] = frame.chip_p50_raw * factor / frame.L - 1
    frame["signal_turnover_ratio"] = (
        frame.turnover_fraction / frame.prior20_turnover_median
    )
    frame["signal_amount_ratio"] = frame.signal_amount_to_prior20_median
    frame["stock_excess_market_1d"] = frame.signal_stock_return - frame.market_return
    frame["stock_excess_industry_1d"] = frame.signal_stock_return - frame.industry_return
    frame["industry_excess_market_1d"] = frame.industry_return - frame.market_return
    frame["industry_excess_market_5d"] = (
        frame.industry_return_5d - frame.market_return_5d
    )
    return frame


def attach_minute_features(
    connection: duckdb.DuckDBPyConnection, frame: pd.DataFrame
) -> pd.DataFrame:
    keys = frame[["gap_id", "symbol", "signal_date", "entry_date", "signal_raw_close"]]
    connection.register("audit_keys", keys)
    minute = connection.execute(
        f"""
        WITH bars AS (
          SELECT k.*,m.window_index,m.available_at,m.open,m.high,m.low,m.close,
            m.volume,m.amount
          FROM audit_keys k
          JOIN read_parquet({sql_paths(MINUTE_FILES)}) m
            ON m.symbol=k.symbol AND m.trade_date=k.entry_date
          WHERE m.trade_date<=DATE '2021-12-31'
            AND m.hard_valid AND m.window_index BETWEEN 0 AND 5
        )
        SELECT gap_id,count(*) AS minute_n,count(DISTINCT window_index) AS minute_windows,
          max(available_at) AS minute_known_at,
          first(open ORDER BY window_index) AS open0,
          last(close ORDER BY window_index) AS close1000,
          first(close ORDER BY abs(window_index-2),window_index) AS close0945,
          min(low) AS low30,max(high) AS high30,
          sum(volume) AS volume30,sum(amount) AS amount30,
          sum(volume) FILTER(WHERE window_index<=2) AS volume_first15,
          sum(volume) FILTER(WHERE window_index>=3) AS volume_second15,
          avg(CASE WHEN close>=open THEN 1.0 ELSE 0.0 END) AS up_bar_share
        FROM bars GROUP BY gap_id ORDER BY gap_id
        """
    ).fetchdf()
    if len(minute) != 355 or minute.gap_id.nunique() != 355:
        raise AuditError("minute universe is incomplete")
    if not minute.minute_n.eq(6).all() or not minute.minute_windows.eq(6).all():
        raise AuditError("first-30-minute window is incomplete")
    result = frame.merge(minute, on="gap_id", validate="one_to_one")
    if pd.to_datetime(result.minute_known_at).dt.time.max().isoformat() > "10:00:00":
        raise AuditError("minute feature uses a post-10:00 bar")
    vwap = result.amount30 / result.volume30
    result["overnight_gap"] = result.open0 / result.signal_raw_close - 1
    result["open_to_1000"] = result.close1000 / result.open0 - 1
    result["signal_close_to_1000"] = result.close1000 / result.signal_raw_close - 1
    result["close1000_vs_vwap30"] = result.close1000 / vwap - 1
    result["last15_return"] = result.close1000 / result.close0945 - 1
    result["second15_volume_ratio"] = result.volume_second15 / result.volume_first15
    denominator = result.high30 - result.low30
    result["close_location30"] = np.where(
        denominator > 0, (result.close1000 - result.low30) / denominator, np.nan
    )
    return result


DAILY_FEATURES = {
    "signal_vs_support20": "signal close / causal prior20 support - 1",
    "signal_to_l_headroom": "frozen L / signal close - 1",
    "chip_p10_overhead": "latest PIT chip p10 / signal close - 1",
    "chip_p50_overhead": "latest PIT chip p50 / signal close - 1",
    "chip_p50_over_l": "latest PIT chip p50 / frozen L - 1",
    "chip_trapped_ratio": "latest PIT trapped chip mass share",
    "signal_amount_ratio": "signal amount / prior20 median amount",
    "signal_turnover_ratio": "signal turnover / prior20 median turnover",
    "stock_excess_market_1d": "signal stock return - market median return",
    "stock_excess_industry_1d": "signal stock return - PIT-industry median return",
    "industry_excess_market_1d": "PIT-industry median - market median return",
    "market_return_5d": "five-session compounded market median return",
    "industry_excess_market_5d": "five-session PIT-industry minus market return",
}

MINUTE_FEATURES = {
    "overnight_gap": "T+1 open / signal close - 1",
    "open_to_1000": "10:00 close / T+1 open - 1",
    "signal_close_to_1000": "10:00 close / signal close - 1",
    "close1000_vs_vwap30": "10:00 close / first-30m VWAP - 1",
    "last15_return": "10:00 close / 09:45 close - 1",
    "second15_volume_ratio": "09:45-10:00 volume / 09:30-09:45 volume",
    "close_location30": "10:00 close location in first-30m range",
    "up_bar_share": "share of first six five-minute bars closing up",
}


def outcome_stats(part: pd.DataFrame) -> dict[str, Any]:
    return {
        "n": len(part),
        "mean_return": part.net_return.mean(),
        "median_return": part.net_return.median(),
        "win_rate": part.net_return.gt(0).mean(),
        "loss_count": part.net_return.le(0).sum(),
        "severe10_rate": part.net_return.le(-0.10).mean(),
        "mean_holding_sessions": part.holding_sessions.mean(),
        "median_holding_sessions": part.holding_sessions.median(),
        "annual_average_count": len(part) / len(YEARS),
        "year_counts": {
            int(key): int(value)
            for key, value in part.signal_year.value_counts().sort_index().items()
        },
        "year_mean_returns": {
            int(key): value
            for key, value in part.groupby("signal_year").net_return.mean().items()
        },
        "year_win_rates": {
            int(key): value
            for key, value in part.groupby("signal_year").net_return.apply(
                lambda x: x.gt(0).mean()
            ).items()
        },
        "year_mean_holding": {
            int(key): value
            for key, value in part.groupby("signal_year").holding_sessions.mean().items()
        },
    }


def winner_loser_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for feature, meaning in {**DAILY_FEATURES, **MINUTE_FEATURES}.items():
        for label, part in frame.groupby(frame.net_return.gt(0), sort=True):
            values = pd.to_numeric(part[feature], errors="coerce").dropna()
            rows.append(
                {
                    "feature": feature,
                    "meaning": meaning,
                    "availability": "signal_close" if feature in DAILY_FEATURES else "T+1_10:00",
                    "outcome_group": "WIN" if label else "LOSS",
                    "n": len(values),
                    "mean": values.mean(),
                    "median": values.median(),
                    "p25": values.quantile(0.25),
                    "p75": values.quantile(0.75),
                }
            )
    return pd.DataFrame(rows)


def quartile_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for feature, meaning in {**DAILY_FEATURES, **MINUTE_FEATURES}.items():
        valid = frame.loc[frame[feature].notna()].copy()
        valid["quartile"] = pd.qcut(
            valid[feature], 4, labels=False, duplicates="drop"
        ) + 1
        for quartile, part in valid.groupby("quartile", observed=True, sort=True):
            stats = outcome_stats(part)
            rows.append(
                {
                    "feature": feature,
                    "meaning": meaning,
                    "availability": "signal_close" if feature in DAILY_FEATURES else "T+1_10:00",
                    "quartile": int(quartile),
                    "feature_min": part[feature].min(),
                    "feature_max": part[feature].max(),
                    **{key: value for key, value in stats.items() if not isinstance(value, dict)},
                    "year_counts_json": json.dumps(stats["year_counts"], sort_keys=True),
                    "year_mean_returns_json": json.dumps(
                        stats["year_mean_returns"], sort_keys=True
                    ),
                }
            )
    return pd.DataFrame(rows)


Rule = tuple[str, str, Callable[[pd.DataFrame], pd.Series]]


def rule_definitions() -> list[Rule]:
    return [
        (
            "DAILY_NON_CHASING_2PCT",
            "stock signal-day excess return versus market median <= 2 percentage points",
            lambda x: x.stock_excess_market_1d <= 0.02,
        ),
        (
            "DAILY_MARKET_5D_NONNEGATIVE",
            "five-session compounded market median return >= 0",
            lambda x: x.market_return_5d >= 0,
        ),
        (
            "DAILY_TURNOVER_NOT_EXTREME_1P5X",
            "signal turnover / prior20 median turnover <= 1.5x",
            lambda x: x.signal_turnover_ratio <= 1.5,
        ),
        (
            "DAILY_P10_AT_OR_ABOVE_SIGNAL",
            "latest PIT chip p10 is at or above the signal close",
            lambda x: x.chip_p10_overhead >= 0,
        ),
        (
            "DAILY_NON_CHASING_AND_MARKET_OK",
            "daily non-chasing rule and five-session market return >= 0",
            lambda x: (x.stock_excess_market_1d <= 0.02) & (x.market_return_5d >= 0),
        ),
        (
            "AT_1000_ABOVE_VWAP30",
            "at 10:00, close is at or above first-30m VWAP",
            lambda x: x.close1000_vs_vwap30 >= 0,
        ),
        (
            "AT_1000_LAST15_NONNEGATIVE",
            "at 10:00, return since 09:45 is nonnegative",
            lambda x: x.last15_return >= 0,
        ),
        (
            "AT_1000_ABOVE_VWAP_AND_UPPER_HALF",
            "at 10:00, close is above VWAP and in the upper half of the 30m range",
            lambda x: (x.close1000_vs_vwap30 >= 0) & (x.close_location30 >= 0.5),
        ),
    ]


def rule_tables(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    profile_rows: list[dict[str, Any]] = []
    year_rows: list[dict[str, Any]] = []
    loyo_rows: list[dict[str, Any]] = []
    for name, meaning, function in rule_definitions():
        mask = function(frame).fillna(False)
        availability = "T+1_10:00" if name.startswith("AT_1000") else "signal_close"
        for passed in (True, False):
            part = frame.loc[mask.eq(passed)]
            stats = outcome_stats(part)
            profile_rows.append(
                {
                    "rule": name,
                    "meaning": meaning,
                    "availability": availability,
                    "group": "PASS" if passed else "FAIL",
                    **{key: value for key, value in stats.items() if not isinstance(value, dict)},
                    "year_counts_json": json.dumps(stats["year_counts"], sort_keys=True),
                    "year_mean_returns_json": json.dumps(
                        stats["year_mean_returns"], sort_keys=True
                    ),
                    "year_win_rates_json": json.dumps(
                        stats["year_win_rates"], sort_keys=True
                    ),
                }
            )
            for year, year_part in part.groupby("signal_year", sort=True):
                annual = outcome_stats(year_part)
                year_rows.append(
                    {
                        "rule": name,
                        "availability": availability,
                        "group": "PASS" if passed else "FAIL",
                        "signal_year": int(year),
                        **{
                            key: value
                            for key, value in annual.items()
                            if not isinstance(value, dict)
                        },
                    }
                )
        for held_out in YEARS:
            training = frame.loc[frame.signal_year.ne(held_out)]
            training_mask = mask.loc[training.index]
            passed = training.loc[training_mask]
            failed = training.loc[~training_mask]
            loyo_rows.append(
                {
                    "rule": name,
                    "availability": availability,
                    "held_out_year": held_out,
                    "pass_n": len(passed),
                    "fail_n": len(failed),
                    "pass_mean_return": passed.net_return.mean(),
                    "fail_mean_return": failed.net_return.mean(),
                    "mean_return_difference": passed.net_return.mean() - failed.net_return.mean(),
                    "pass_win_rate": passed.net_return.gt(0).mean(),
                    "fail_win_rate": failed.net_return.gt(0).mean(),
                    "win_rate_difference": passed.net_return.gt(0).mean()
                    - failed.net_return.gt(0).mean(),
                    "pass_mean_holding": passed.holding_sessions.mean(),
                    "fail_mean_holding": failed.holding_sessions.mean(),
                    "holding_difference": passed.holding_sessions.mean()
                    - failed.holding_sessions.mean(),
                }
            )
    return pd.DataFrame(profile_rows), pd.DataFrame(year_rows), pd.DataFrame(loyo_rows)


def signal_date_robustness(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    date_sizes = frame.signal_date.value_counts()
    for name, _, function in rule_definitions():
        mask = function(frame).fillna(False)
        availability = "T+1_10:00" if name.startswith("AT_1000") else "signal_close"
        by_date = (
            frame.assign(rule_pass=mask)
            .groupby(["signal_date", "rule_pass"])
            .agg(
                n=("net_return", "size"),
                mean_return=("net_return", "mean"),
                win_rate=("net_return", lambda x: x.gt(0).mean()),
                mean_holding=("holding_sessions", "mean"),
            )
            .reset_index()
        )
        pivot = by_date.pivot(index="signal_date", columns="rule_pass", values="mean_return")
        matched = pivot.dropna()
        difference = matched[True] - matched[False]
        for passed in (True, False):
            group = by_date.loc[by_date.rule_pass.eq(passed)]
            rows.append(
                {
                    "rule": name,
                    "availability": availability,
                    "group": "PASS" if passed else "FAIL",
                    "unique_signal_dates": group.signal_date.nunique(),
                    "equal_date_weight_mean_return": group.mean_return.mean(),
                    "equal_date_weight_median_return": group.mean_return.median(),
                    "equal_date_weight_win_rate": group.win_rate.mean(),
                    "equal_date_weight_mean_holding": group.mean_holding.mean(),
                    "matched_dates": len(matched),
                    "matched_pass_minus_fail_mean": difference.mean(),
                    "matched_pass_minus_fail_median": difference.median(),
                    "matched_pass_better_share": difference.gt(0).mean(),
                    "all_unique_signal_dates": frame.signal_date.nunique(),
                    "largest_signal_date": date_sizes.index[0],
                    "largest_signal_date_n": int(date_sizes.iloc[0]),
                }
            )
    return pd.DataFrame(rows)


def monotonicity(quartiles: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for feature, part in quartiles.groupby("feature", sort=True):
        ordered = part.sort_values("quartile")
        result[feature] = {
            "mean_return_sequence": ordered.mean_return.tolist(),
            "win_rate_sequence": ordered.win_rate.tolist(),
            "mean_holding_sequence": ordered.mean_holding_sessions.tolist(),
            "mean_return_spearman": ordered.quartile.corr(
                ordered.mean_return, method="spearman"
            ),
            "win_rate_spearman": ordered.quartile.corr(
                ordered.win_rate, method="spearman"
            ),
            "holding_spearman": ordered.quartile.corr(
                ordered.mean_holding_sessions, method="spearman"
            ),
        }
    return result


def fmt_pct(value: float) -> str:
    return f"{value:+.2%}"


def render_report(
    frame: pd.DataFrame,
    quartiles: pd.DataFrame,
    rules: pd.DataFrame,
    year_rules: pd.DataFrame,
    date_robustness: pd.DataFrame,
) -> str:
    all_stats = outcome_stats(frame)
    daily = rules.loc[
        rules.rule.eq("DAILY_NON_CHASING_2PCT") & rules.group.eq("PASS")
    ].iloc[0]
    daily_fail = rules.loc[
        rules.rule.eq("DAILY_NON_CHASING_2PCT") & rules.group.eq("FAIL")
    ].iloc[0]
    minute = rules.loc[
        rules.rule.eq("AT_1000_ABOVE_VWAP30") & rules.group.eq("PASS")
    ].iloc[0]
    minute_fail = rules.loc[
        rules.rule.eq("AT_1000_ABOVE_VWAP30") & rules.group.eq("FAIL")
    ].iloc[0]
    annual = year_rules.loc[
        year_rules.rule.eq("DAILY_NON_CHASING_2PCT")
        & year_rules.group.eq("PASS")
    ].sort_values("signal_year")
    annual_lines = "\n".join(
        f"- {int(row.signal_year)}: n={int(row.n)}, mean={fmt_pct(row.mean_return)}, "
        f"win={row.win_rate:.1%}, mean hold={row.mean_holding_sessions:.2f}"
        for row in annual.itertuples(index=False)
    )
    daily_top = quartiles.loc[
        quartiles.feature.eq("stock_excess_market_1d")
    ].sort_values("quartile")
    daily_sequence = " / ".join(fmt_pct(value) for value in daily_top.mean_return)
    minute_top = quartiles.loc[
        quartiles.feature.eq("close1000_vs_vwap30")
    ].sort_values("quartile")
    minute_sequence = " / ".join(fmt_pct(value) for value in minute_top.mean_return)
    daily_date = date_robustness.loc[
        date_robustness.rule.eq("DAILY_NON_CHASING_2PCT")
        & date_robustness.group.eq("PASS")
    ].iloc[0]
    minute_date = date_robustness.loc[
        date_robustness.rule.eq("AT_1000_ABOVE_VWAP30")
        & date_robustness.group.eq("PASS")
    ].iloc[0]
    return f"""# ASHARE-TRUE-GAP-BELOW-L-V29R2-DEVELOPMENT-MORPHOLOGY-AUDIT-V1

Strictly read-only development audit. Every opened market-data partition is 2018-2021; maximum signal, entry, exit, chip, and minute observation dates are no later than 2021-12-31. No validation title or return source is opened.

## Universe

- All 355 executable V28R2 outcomes; V29R1's 298 executable outcomes are an exact subset.
- Baseline: mean {fmt_pct(all_stats['mean_return'])}, median {fmt_pct(all_stats['median_return'])}, win {all_stats['win_rate']:.1%}, mean holding {all_stats['mean_holding_sessions']:.2f} sessions.
- Signal years: {all_stats['year_counts']}.
- Winners/losers are 332/23. The analysis does not fit on the 14 portfolio losers or the two issuer-title cases.
- Latest PIT chip is missing for 32/355 signals and is left missing. No substitute, normalization, or clipping is used.

## Signal-close features

The clearest full-sample monotone relationship is excessive one-day stock outperformance versus the market. Mean return by ascending quartile is {daily_sequence}; the upper quartile also has materially lower hit rate and longer holding. Turnover ratio is directionally monotone in mean return, but its separation is weaker. Distances to support/L and PIT chip p10/p50 are not jointly monotone enough to justify a cutoff.

Simplest development candidate: **signal-day stock return minus the cross-sectional market median must be <= 2 percentage points**. This is a non-chasing condition known at the signal close, so the existing T+1-open chronology remains legal.

- Pass: n={int(daily.n)} ({daily.annual_average_count:.2f}/year), mean={fmt_pct(daily.mean_return)}, median={fmt_pct(daily.median_return)}, win={daily.win_rate:.1%}, mean hold={daily.mean_holding_sessions:.2f}.
- Fail: n={int(daily_fail.n)}, mean={fmt_pct(daily_fail.mean_return)}, median={fmt_pct(daily_fail.median_return)}, win={daily_fail.win_rate:.1%}, mean hold={daily_fail.mean_holding_sessions:.2f}.
- Annual pass profile:
{annual_lines}

This is post-hoc and highly imbalanced toward 2018. The small 2019-2021 counts prevent calling it validated; it is only the simplest candidate for a new frozen development experiment.

There are only {int(daily_date.all_unique_signal_dates)} unique signal dates and the largest date contributes {int(daily_date.largest_signal_date_n)} rows. With each signal date weighted equally, pass dates average {fmt_pct(daily_date.equal_date_weight_mean_return)}; on the {int(daily_date.matched_dates)} dates containing both groups, pass minus fail averages {fmt_pct(daily_date.matched_pass_minus_fail_mean)} and is positive on {daily_date.matched_pass_better_share:.1%} of dates.

## T+1 first 30 minutes

All 355 entries have exactly six hard-valid registered five-minute windows, and the last observation is available at 10:00. First-30-minute VWAP quartile mean returns are {minute_sequence}, with the lowest quartile carrying the weakest hit rate and longest holding.

Descriptive 10:00 demand condition: **10:00 close >= first-30-minute VWAP**.

- Association among frozen open-entry outcomes, pass: n={int(minute.n)}, mean={fmt_pct(minute.mean_return)}, win={minute.win_rate:.1%}, mean hold={minute.mean_holding_sessions:.2f}.
- Fail: n={int(minute_fail.n)}, mean={fmt_pct(minute_fail.mean_return)}, win={minute_fail.win_rate:.1%}, mean hold={minute_fail.mean_holding_sessions:.2f}.

Equal-date weighting gives {fmt_pct(minute_date.equal_date_weight_mean_return)} for pass dates. Among {int(minute_date.matched_dates)} signal dates containing both pass/fail observations, pass minus fail averages {fmt_pct(minute_date.matched_pass_minus_fail_mean)} and is positive on {minute_date.matched_pass_better_share:.1%} of dates.

This is not an executable return estimate. CY-008 ends at the bar whose value becomes known at 10:00 and contains no post-decision fill bar. Any use requires a separately registered 10:00-after entry procedure, with the earliest legal fill after 10:00 and all exits recomputed from that price. It cannot be attached to the frozen opening fill.
"""


def main() -> None:
    hashes = verify_inputs()
    connection = duckdb.connect()
    frame = attach_minute_features(connection, load_daily_features(connection))
    connection.close()
    if pd.to_datetime(frame.minute_known_at).max() > pd.Timestamp("2021-12-31 23:59:59"):
        raise AuditError("post-2021 minute row observed")

    win_loss = winner_loser_table(frame)
    quartiles = quartile_table(frame)
    rules, rule_years, loyo = rule_tables(frame)
    date_robustness = signal_date_robustness(frame)
    monotone = monotonicity(quartiles)

    OUT.mkdir(parents=True, exist_ok=True)
    frame.to_csv(FEATURES_CSV, index=False)
    win_loss.to_csv(WIN_LOSS_CSV, index=False)
    quartiles.to_csv(QUARTILES_CSV, index=False)
    rules.to_csv(RULES_CSV, index=False)
    rule_years.to_csv(RULE_YEARS_CSV, index=False)
    loyo.to_csv(LOYO_CSV, index=False)
    date_robustness.to_csv(DATE_ROBUSTNESS_CSV, index=False)
    atomic_text(
        REPORT,
        render_report(frame, quartiles, rules, rule_years, date_robustness),
    )

    summary = {
        "experiment": "ASHARE-TRUE-GAP-BELOW-L-V29R2-DEVELOPMENT-MORPHOLOGY-AUDIT-V1",
        "chronology": {
            "maximum_allowed_date": MAX_DATE,
            "maximum_signal_date": pd.to_datetime(frame.signal_date).max(),
            "maximum_entry_date": pd.to_datetime(frame.entry_date).max(),
            "maximum_exit_date": pd.to_datetime(frame.exit_date).max(),
            "maximum_chip_trade_date": pd.to_datetime(frame.chip_trade_date).max(),
            "maximum_minute_known_at": pd.to_datetime(frame.minute_known_at).max(),
            "post_2021_partition_opened": False,
            "validation_title_or_return_opened": False,
        },
        "universe": {
            "v28r2_executable": len(frame),
            "v29r1_executable_subset": int(frame.v29_executable.sum()),
            "winners": int(frame.net_return.gt(0).sum()),
            "losers": int(frame.net_return.le(0).sum()),
            "chip_missing": int(frame.chip_p50_raw.isna().sum()),
            "signal_year_counts": outcome_stats(frame)["year_counts"],
            "baseline": outcome_stats(frame),
            "v29_subset_baseline": outcome_stats(frame.loc[frame.v29_executable]),
        },
        "feature_monotonicity": monotone,
        "candidate_rules": rules.loc[rules.group.eq("PASS")].to_dict("records"),
        "candidate_rules_v29_subset": {
            name: outcome_stats(
                frame.loc[frame.v29_executable & function(frame).fillna(False)]
            )
            for name, _, function in rule_definitions()
        },
        "signal_date_robustness": date_robustness.to_dict("records"),
        "minute_interpretation": (
            "Association with frozen open-entry outcomes only. A 10:00 observation "
            "requires a new post-10:00 entry rule; no legal fill is present here."
        ),
    }
    atomic_json(SUMMARY_JSON, summary)
    manifest = {
        "runner": str(Path(__file__).resolve()),
        "runner_sha256": sha256(Path(__file__).resolve()),
        "input_sha256": hashes,
        "outputs": [
            str(FEATURES_CSV),
            str(WIN_LOSS_CSV),
            str(QUARTILES_CSV),
            str(RULES_CSV),
            str(RULE_YEARS_CSV),
            str(LOYO_CSV),
            str(DATE_ROBUSTNESS_CSV),
            str(SUMMARY_JSON),
            str(REPORT),
        ],
        "maximum_data_date": MAX_DATE,
        "post_2021_partition_opened": False,
        "validation_title_or_return_opened": False,
    }
    atomic_json(MANIFEST_JSON, manifest)
    print(json.dumps(json_ready(summary), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
