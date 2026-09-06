#!/usr/bin/env python3
"""Build the frozen, outcome-blind CHINEXT V1 daily regime feature library."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
CHINEXT_SCRIPTS = ROOT / "research/chinext_v1/scripts"
SRC = ROOT / "src"
for import_root in (str(CHINEXT_SCRIPTS), str(SRC)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

import run_chinext_v1_extended_replay as extended  # noqa: E402

SPEC = WORK / "experiments/EXP-P2-001_spec.json"
OUTPUT_PARQUET = WORK / "artifacts/daily_regime_features.parquet"
OUTPUT_AUDIT = WORK / "artifacts/regime_feature_audit.json"
REPORT = WORK / "reports/phase2_feature_library.md"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
CY006_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
DAILY_ROOT = Path(
    "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily"
)
CALENDAR = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet"
)
ANCHOR = ROOT / "research/chinext_v1/data/smoke/399102_daily.csv"
CSI300 = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/index_daily/csi000300.parquet"
)
CHINEXT100 = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/index_daily/sz399006.parquet"
)
HOLDOUT_MEMBERSHIP = (
    ROOT / "research/chinext_v1/data/pit_holdout_2022_2023/daily_membership.parquet"
)
DEVELOPMENT_MEMBERSHIP = (
    ROOT / "research/chinext_v1/data/pit_2024_2025/daily_membership.parquet"
)
BASELINE_NAV = {
    "EXTENDED_2018_2021": ROOT
    / "research/chinext_v1/output/chinext_v1_extended_2018_2021/daily_nav.jsonl",
    "HOLDOUT_O0_2022_2023": ROOT
    / "research/chinext_v1/output/chinext_v1_phase9b_oos/O0_BASELINE/daily_nav.jsonl",
    "DEVELOPMENT_2024_2025": ROOT
    / "research/chinext_v1/output/chinext_v1_pit_replay/daily_nav.jsonl",
}

EXPECTED_SPEC = "b6dd24d0d9c1f60b3aa86b92b891fe2887fd4bad2cc9a9a735e8c0221f059bd7"
EXPECTED_INPUTS = {
    STRATEGY: "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a",
    CY006_MANIFEST: "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    CALENDAR: "1ccd72b98ead430557f214917ca161dd2f92c26c605262bcd9fe7bc3db2c64ae",
    HOLDOUT_MEMBERSHIP: "1af3577941081fb8354dae5112c08a89ca24c7d7c78f3fb3dd4943c3ead1ee0e",
    DEVELOPMENT_MEMBERSHIP: "9a6a0a071916b2af99a0f3f16b887672716b78428d28b4368f09bdd32d208c3d",
    ANCHOR: "e096e4d50d0b6ac5062d4940bf0c17c0165dd1c44d5f49ce12d0e3754daa8779",
    CSI300: "6d93a34f308fec0390a184a68a4d7856f566c917248b886b6a4e7dffcf9dda63",
    CHINEXT100: "0d0f8dbb573f1016eaa94f11aa847ea2bf2be296691caa591f93320ddd640c2c",
}
EXPECTED_TRANSIENT_CANONICAL = (
    "07b2f8ea6796f24a3e655b157307aadf07f1b2b7390121776fb36c9db2ee6f7a"
)
EXPECTED_TRANSIENT_MEMBERSHIP = (
    "c4e89c4ee2e416e5e9cd8d699269595243e8fcb27f5c7b11f6f336348d872d81"
)
START = "2018-01-02"
END = "2025-12-31"
MIN_ELIGIBLE = 100
MIN_COVERAGE = 0.95
MIN_INDUSTRY_COVERAGE = 0.80
MIN_RANK_MATCH = 0.80


class FeatureLibraryError(RuntimeError):
    """Raised when an input, PIT, coverage, or reconciliation contract fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def causal_one_step_return(
    previous_close: float,
    current_close: float,
    share_multiplier: float = 1.0,
    cash_per_share: float = 0.0,
) -> float:
    """Return in the current raw-price coordinate after a visible cash/share action."""

    if not all(
        math.isfinite(value)
        for value in (previous_close, current_close, share_multiplier, cash_per_share)
    ):
        raise ValueError("non-finite corporate-action coordinate")
    if share_multiplier <= 0 or current_close <= 0:
        raise ValueError("invalid corporate-action coordinate")
    adjusted_previous = (previous_close - cash_per_share) / share_multiplier
    if adjusted_previous <= 0:
        raise ValueError("invalid corporate-action coordinate")
    return current_close / adjusted_previous - 1.0


def limit_close_hit(close: float, limit_price: float | None) -> bool | None:
    """Registered limit validator tolerance, exposed for focused regression tests."""

    if limit_price is None or not math.isfinite(float(limit_price)):
        return None
    tolerance = max(0.001, abs(float(limit_price)) * 1e-6)
    return abs(float(close) - float(limit_price)) <= tolerance


def coverage_value(value: float, valid_count: int, denominator: int) -> float | None:
    """Fail a cross-sectional feature closed below frozen size/coverage thresholds."""

    if denominator < MIN_ELIGIBLE or valid_count / denominator < MIN_COVERAGE:
        return None
    return float(value) if value is not None and math.isfinite(float(value)) else None


def validate_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    if sha256_file(SPEC) != EXPECTED_SPEC:
        raise FeatureLibraryError("EXP-P2-001 spec hash mismatch")
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_FEATURE_RESULT_AND_BEFORE_OUTCOME_JOIN":
        raise FeatureLibraryError("EXP-P2-001 is not frozen before feature results")
    if spec.get("outcome_analysis_in_this_experiment") is not False:
        raise FeatureLibraryError("EXP-P2-001 outcome-analysis prohibition changed")
    actual = {str(path): sha256_file(path) for path in EXPECTED_INPUTS}
    mismatches = {
        str(path): {"expected": expected, "actual": actual[str(path)]}
        for path, expected in EXPECTED_INPUTS.items()
        if actual[str(path)] != expected
    }
    if mismatches:
        raise FeatureLibraryError(f"frozen input hash mismatch: {mismatches}")
    return spec, actual


def create_membership_tables(
    connection: duckdb.DuckDBPyConnection, extended_membership: Path
) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE target_membership AS
        SELECT 'EXTENDED_2018_2021' AS baseline_block,
               CAST(trade_date AS DATE) AS trade_date,symbol,listed_trading_days,
               'CY-029/B_RECONSTRUCTED' AS authorization_lineage
        FROM read_parquet(?)
        UNION ALL
        SELECT 'HOLDOUT_O0_2022_2023',CAST(trade_date AS DATE),symbol,
               listed_trading_days,'CY-028/B_RECONSTRUCTED'
        FROM read_parquet(?)
        UNION ALL
        SELECT 'DEVELOPMENT_2024_2025',CAST(trade_date AS DATE),symbol,
               listed_trading_days,'CY-027/B_RECONSTRUCTED'
        FROM read_parquet(?)
        """,
        [
            str(extended_membership),
            str(HOLDOUT_MEMBERSHIP),
            str(DEVELOPMENT_MEMBERSHIP),
        ],
    )
    stats = connection.execute(
        """
        SELECT count(*),count(DISTINCT (baseline_block,trade_date,symbol)),
               count(DISTINCT trade_date),min(trade_date),max(trade_date)
        FROM target_membership
        """
    ).fetchone()
    if stats != (2056628, 2056628, 1942, pd.Timestamp(START).date(), pd.Timestamp(END).date()):
        raise FeatureLibraryError(f"unified membership cardinality mismatch: {stats}")
    connection.execute(
        """
        CREATE TEMP TABLE block_symbols AS
        SELECT DISTINCT baseline_block,symbol FROM target_membership
        """
    )


def create_panel_tables(
    connection: duckdb.DuckDBPyConnection, transient_root: Path
) -> dict[str, int]:
    extended_paths = [
        str(transient_root / f"partition_year={year}" / "data_0.parquet")
        for year in range(2018, 2022)
    ]
    direct_paths = [
        str(DAILY_ROOT / f"partition_year={year}" / "data_0.parquet")
        for year in range(2018, 2026)
    ]
    connection.execute(
        """
        CREATE TEMP TABLE raw_industry AS
        SELECT trade_date,
               CASE WHEN symbol='302132.SZ' AND trade_date<DATE '2025-02-17'
                    THEN '300114.SZ' ELSE symbol END AS symbol,
               industry
        FROM read_parquet(?,union_by_name=true)
        WHERE trade_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'
          AND industry_valid IS TRUE
          AND industry IS NOT NULL AND trim(industry)<>''
          AND source_notice_date IS NOT NULL AND source_notice_date<=trade_date
        QUALIFY row_number() OVER (
          PARTITION BY trade_date,
            CASE WHEN symbol='302132.SZ' AND trade_date<DATE '2025-02-17'
                 THEN '300114.SZ' ELSE symbol END
          ORDER BY CASE WHEN symbol='302132.SZ' THEN 0 ELSE 1 END
        )=1
        """,
        [direct_paths],
    )
    connection.execute(
        """
        CREATE TEMP TABLE extended_panel AS
        SELECT 'EXTENDED_2018_2021' AS baseline_block,
               CAST(p.trade_date AS DATE) AS trade_date,p.symbol AS symbol,
               p.open,p.high,p.low,p.close,p.volume,p.amount,p.trade_status,p.is_st,
               p.up_limit_price,p.down_limit_price,p.bar_valid,p.trading_state_valid,
               p.corporate_action_valid,p.market_rule_valid,p.historical_identity_valid,
               p.hard_valid,p.current_day_data_tradable,p.available_at,p.snapshot_id,
               p.corporate_action_count,p.corporate_action_available_date,
               p.corporate_action_blocking,p.share_multiplier,p.cash_per_share,
               p.rights_ratio,p.rights_price,i.industry
        FROM read_parquet(?,union_by_name=true) p
        JOIN block_symbols b
          ON b.baseline_block='EXTENDED_2018_2021' AND p.symbol=b.symbol
        LEFT JOIN raw_industry i
          ON p.trade_date=i.trade_date AND p.symbol=i.symbol
        WHERE p.trade_date BETWEEN DATE '2017-04-12' AND DATE '2021-12-31'
        """,
        [extended_paths],
    )
    connection.execute(
        """
        CREATE TEMP TABLE direct_panel AS
        SELECT b.baseline_block,CAST(p.trade_date AS DATE) AS trade_date,p.symbol,
               p.open,p.high,p.low,p.close,p.volume,p.amount,p.trade_status,p.is_st,
               p.up_limit_price,p.down_limit_price,p.bar_valid,p.trading_state_valid,
               p.corporate_action_valid,p.market_rule_valid,p.historical_identity_valid,
               p.hard_valid,p.current_day_data_tradable,p.available_at,p.snapshot_id,
               p.corporate_action_count,p.corporate_action_available_date,
               p.corporate_action_blocking,p.share_multiplier,p.cash_per_share,
               p.rights_ratio,p.rights_price,
               CASE WHEN p.industry_valid IS TRUE
                          AND p.industry IS NOT NULL AND trim(p.industry)<>''
                          AND p.source_notice_date IS NOT NULL
                          AND p.source_notice_date<=p.trade_date
                    THEN p.industry ELSE NULL END AS industry
        FROM read_parquet(?,union_by_name=true) p
        JOIN block_symbols b ON p.symbol=b.symbol
        WHERE (b.baseline_block='HOLDOUT_O0_2022_2023'
               AND p.trade_date BETWEEN DATE '2021-07-08' AND DATE '2023-12-29')
           OR (b.baseline_block='DEVELOPMENT_2024_2025'
               AND p.trade_date BETWEEN DATE '2023-01-01' AND DATE '2025-12-31')
        """,
        [direct_paths],
    )
    connection.execute(
        """
        CREATE TEMP TABLE panel AS
        SELECT * FROM extended_panel
        UNION ALL BY NAME
        SELECT * FROM direct_panel
        """
    )
    duplicates = connection.execute(
        """
        SELECT count(*)-count(DISTINCT (baseline_block,trade_date,symbol)) FROM panel
        """
    ).fetchone()[0]
    if duplicates:
        raise FeatureLibraryError(f"security panel contains {duplicates} duplicate rows")
    counts = dict(
        connection.execute(
            """
            SELECT baseline_block,count(*) FROM panel GROUP BY baseline_block ORDER BY 1
            """
        ).fetchall()
    )
    return {str(key): int(value) for key, value in counts.items()}


def create_stock_features(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE calendar AS
        SELECT CAST(trade_date AS DATE) AS trade_date,
               row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
        FROM read_parquet(?)
        WHERE trade_date BETWEEN DATE '2017-04-12' AND DATE '2026-01-31'
        ORDER BY trade_date
        """,
        [str(CALENDAR)],
    )
    connection.execute(
        """
        CREATE TEMP TABLE panel_validity AS
        SELECT p.*,c.cal_idx,
          (p.hard_valid IS TRUE AND p.bar_valid IS TRUE
           AND p.trading_state_valid IS TRUE AND p.corporate_action_valid IS TRUE
           AND p.market_rule_valid IS TRUE AND p.historical_identity_valid IS TRUE
           AND p.trade_status=1 AND p.current_day_data_tradable IS TRUE
           AND p.is_st IS FALSE AND p.corporate_action_blocking IS FALSE
           AND p.available_at IS NOT NULL
           AND p.available_at<=CAST(p.trade_date AS TIMESTAMP)+INTERVAL 15 HOUR
           AND p.close IS NOT NULL AND isfinite(p.close) AND p.close>0
           AND p.volume IS NOT NULL AND isfinite(p.volume) AND p.volume>0
           AND p.amount IS NOT NULL AND isfinite(p.amount) AND p.amount>=0
          ) AS critical_valid
        FROM panel p JOIN calendar c USING(trade_date)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE stock_step AS
        SELECT *,
          lag(close) OVER w AS previous_close,
          lag(critical_valid) OVER w AS previous_critical_valid,
          lag(cal_idx) OVER w AS previous_cal_idx
        FROM panel_validity
        WINDOW w AS (PARTITION BY baseline_block,symbol ORDER BY trade_date)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE stock_log_chain AS
        SELECT *,
          CASE
            WHEN critical_valid AND previous_critical_valid
             AND cal_idx-previous_cal_idx=1
             AND coalesce(corporate_action_count,0)=0 THEN true
            WHEN critical_valid AND previous_critical_valid
             AND cal_idx-previous_cal_idx=1
             AND corporate_action_count>0
             AND corporate_action_available_date IS NOT NULL
             AND corporate_action_available_date<=trade_date
             AND coalesce(rights_ratio,0)=0
             AND coalesce(share_multiplier,1)>0
             AND (previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)>0
            THEN true
            ELSE false
          END AS coordinate_step_valid,
          CASE
            WHEN critical_valid AND previous_critical_valid
             AND cal_idx-previous_cal_idx=1
             AND corporate_action_count>0
             AND corporate_action_available_date IS NOT NULL
             AND corporate_action_available_date<=trade_date
             AND coalesce(rights_ratio,0)=0
             AND coalesce(share_multiplier,1)>0
             AND (previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)>0
            THEN ln(close/((previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)))
            WHEN critical_valid AND previous_critical_valid
             AND cal_idx-previous_cal_idx=1
             AND coalesce(corporate_action_count,0)=0
            THEN ln(close/previous_close)
            ELSE NULL
          END AS step_log_return
        FROM stock_step
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE stock_adjusted AS
        SELECT *,
          exp(sum(coalesce(step_log_return,0.0)) OVER (
            PARTITION BY baseline_block,symbol ORDER BY trade_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )) AS adjusted_close
        FROM stock_log_chain
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE stock_windows AS
        SELECT *,
          adjusted_close*high/close AS adjusted_high,
          adjusted_close*low/close AS adjusted_low,
          sum(CASE WHEN critical_valid THEN 1 ELSE 0 END) OVER (
            PARTITION BY baseline_block,symbol ORDER BY trade_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          ) AS history_valid_count_total,
          sum(coordinate_step_valid::INTEGER) OVER (
            PARTITION BY baseline_block,symbol ORDER BY trade_date
            ROWS BETWEEN 119 PRECEDING AND CURRENT ROW
          ) AS coordinate_valid_count120,
          count(*) OVER w121 AS history_row_count121,
          min(cal_idx) OVER w121 AS history_min_cal_idx121,
          sum(CASE WHEN critical_valid THEN 1 ELSE 0 END) OVER w121 AS history_valid_count121,
          avg(amount) OVER w20 AS amount_ma20,
          avg(adjusted_close) OVER w5 AS ma5,
          avg(adjusted_close) OVER w10 AS ma10,
          avg(adjusted_close) OVER w20 AS ma20,
          avg(adjusted_close) OVER w60 AS ma60,
          avg(adjusted_close) OVER w120 AS ma120,
          lag(adjusted_close,1) OVER w AS lag_close1,
          lag(adjusted_close,5) OVER w AS lag_close5,
          lag(adjusted_close,20) OVER w AS lag_close20,
          lag(adjusted_close,60) OVER w AS lag_close60,
          lag(cal_idx,1) OVER w AS lag_idx1,
          lag(cal_idx,5) OVER w AS lag_idx5,
          lag(cal_idx,20) OVER w AS lag_idx20,
          lag(cal_idx,60) OVER w AS lag_idx60,
          max(adjusted_close*high/close) OVER w60 AS high60,
          min(adjusted_close*low/close) OVER w60 AS low60
        FROM stock_adjusted
        WINDOW
          w AS (PARTITION BY baseline_block,symbol ORDER BY trade_date),
          w5 AS (PARTITION BY baseline_block,symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
          w10 AS (PARTITION BY baseline_block,symbol ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW),
          w20 AS (PARTITION BY baseline_block,symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
          w60 AS (PARTITION BY baseline_block,symbol ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW),
          w120 AS (PARTITION BY baseline_block,symbol ORDER BY trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW),
          w121 AS (PARTITION BY baseline_block,symbol ORDER BY trade_date ROWS BETWEEN 120 PRECEDING AND CURRENT ROW)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE eligible_features AS
        SELECT s.baseline_block,s.trade_date,s.cal_idx,s.symbol,m.listed_trading_days,
          s.snapshot_id,s.industry,s.amount,s.volume,s.close,s.up_limit_price,s.down_limit_price,
          s.adjusted_close,
          CASE WHEN s.coordinate_valid_count120=120 THEN s.ma5 END AS ma5,
          CASE WHEN s.coordinate_valid_count120=120 THEN s.ma10 END AS ma10,
          CASE WHEN s.coordinate_valid_count120=120 THEN s.ma20 END AS ma20,
          CASE WHEN s.coordinate_valid_count120=120 THEN s.ma60 END AS ma60,
          CASE WHEN s.coordinate_valid_count120=120 THEN s.ma120 END AS ma120,
          s.amount_ma20,
          CASE WHEN s.coordinate_valid_count120=120 AND s.cal_idx-s.lag_idx1=1
               THEN s.adjusted_close/s.lag_close1-1 END AS ret1,
          CASE WHEN s.coordinate_valid_count120=120 AND s.cal_idx-s.lag_idx5=5
               THEN s.adjusted_close/s.lag_close5-1 END AS ret5,
          CASE WHEN s.coordinate_valid_count120=120 AND s.cal_idx-s.lag_idx20=20
               THEN s.adjusted_close/s.lag_close20-1 END AS ret20,
          CASE WHEN s.coordinate_valid_count120=120 AND s.cal_idx-s.lag_idx60=60
               THEN s.adjusted_close/s.lag_close60-1 END AS ret60,
          CASE WHEN s.coordinate_valid_count120=120 THEN s.adjusted_close>=s.high60 END AS new_high60,
          CASE WHEN s.coordinate_valid_count120=120 THEN s.adjusted_close<=s.low60 END AS new_low60,
          CASE WHEN s.up_limit_price IS NOT NULL AND isfinite(s.up_limit_price)
               THEN abs(s.close-s.up_limit_price)<=greatest(0.001,abs(s.up_limit_price)*1e-6) END
            AS upper_limit_hit,
          CASE WHEN s.down_limit_price IS NOT NULL AND isfinite(s.down_limit_price)
               THEN abs(s.close-s.down_limit_price)<=greatest(0.001,abs(s.down_limit_price)*1e-6) END
            AS lower_limit_hit
        FROM stock_windows s
        JOIN target_membership m USING(baseline_block,trade_date,symbol)
        WHERE m.listed_trading_days>=180
          AND s.critical_valid
          AND s.history_valid_count_total>=180
          AND s.history_row_count121=121
          AND s.history_valid_count121=121
          AND s.cal_idx-s.history_min_cal_idx121=120
          AND s.amount_ma20>=100000000.0
        """
    )


def expected_eligible_counts(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    selects: list[str] = []
    parameters: list[str] = []
    for block, path in BASELINE_NAV.items():
        selects.append(
            "SELECT ? AS baseline_block,CAST(trade_date AS DATE) AS trade_date,"
            "CAST(basic_eligible AS BIGINT) AS expected_eligible "
            "FROM read_json_auto(?)"
        )
        parameters.extend([block, str(path)])
    return connection.execute(" UNION ALL ".join(selects), parameters).fetchdf()


def reconcile_eligibility(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    expected = expected_eligible_counts(connection)
    actual = connection.execute(
        """
        SELECT baseline_block,trade_date,count(*)::BIGINT AS actual_eligible
        FROM eligible_features GROUP BY baseline_block,trade_date
        """
    ).fetchdf()
    result = expected.merge(actual, how="left", on=["baseline_block", "trade_date"])
    result["actual_eligible"] = result["actual_eligible"].fillna(0).astype("int64")
    mismatch = result[result.expected_eligible != result.actual_eligible].sort_values(
        ["trade_date", "baseline_block"]
    )
    if not mismatch.empty:
        row = mismatch.iloc[0]
        raise FeatureLibraryError(
            "first basic-eligible divergence: "
            f"{row.trade_date} {row.baseline_block} expected={row.expected_eligible} "
            f"actual={row.actual_eligible}; total mismatches={len(mismatch)}"
        )
    if len(result) != 1942:
        raise FeatureLibraryError(f"eligible reconciliation date count {len(result)} != 1942")
    return {
        "date_count": int(len(result)),
        "mismatch_count": 0,
        "minimum": int(result.expected_eligible.min()),
        "maximum": int(result.expected_eligible.max()),
        "days_below_cross_sectional_minimum": int(
            (result.expected_eligible < MIN_ELIGIBLE).sum()
        ),
        "by_block": {
            str(block): {
                "dates": int(len(rows)),
                "minimum": int(rows.expected_eligible.min()),
                "maximum": int(rows.expected_eligible.max()),
            }
            for block, rows in result.groupby("baseline_block", sort=True)
        },
    }


CROSS_COVERAGE: dict[str, str] = {
    "breadth_above_ma5": "ma5_valid_count",
    "breadth_above_ma10": "ma10_valid_count",
    "breadth_above_ma20": "ma20_valid_count",
    "breadth_above_ma60": "ma60_valid_count",
    "breadth_above_ma120": "ma120_valid_count",
    "breadth_positive_return1": "ret1_valid_count",
    "breadth_positive_return5": "ret5_valid_count",
    "breadth_positive_return20": "ret20_valid_count",
    "breadth_positive_return60": "ret60_valid_count",
    "breadth_new_high60": "new_high60_valid_count",
    "breadth_new_low60": "new_low60_valid_count",
    "advance_decline_balance": "ret1_valid_count",
    "cross_sectional_return1_std": "ret1_valid_count",
    "cross_sectional_return5_std": "ret5_valid_count",
    "cross_sectional_return20_std": "ret20_valid_count",
    "cross_sectional_down_fraction1": "ret1_valid_count",
    "cross_sectional_return1_p10": "ret1_valid_count",
    "cross_sectional_return1_p50": "ret1_valid_count",
    "cross_sectional_return1_p90": "ret1_valid_count",
    "cross_sectional_return1_p90_p10_spread": "ret1_valid_count",
    "cross_sectional_return1_skewness": "ret1_valid_count",
    "cross_sectional_return1_excess_kurtosis": "ret1_valid_count",
    "cross_sectional_return5_p10": "ret5_valid_count",
    "cross_sectional_return5_p50": "ret5_valid_count",
    "cross_sectional_return5_p90": "ret5_valid_count",
    "cross_sectional_return5_p90_p10_spread": "ret5_valid_count",
    "cross_sectional_return5_skewness": "ret5_valid_count",
    "cross_sectional_return5_excess_kurtosis": "ret5_valid_count",
    "cross_sectional_return20_p10": "ret20_valid_count",
    "cross_sectional_return20_p50": "ret20_valid_count",
    "cross_sectional_return20_p90": "ret20_valid_count",
    "cross_sectional_return20_p90_p10_spread": "ret20_valid_count",
    "cross_sectional_return20_skewness": "ret20_valid_count",
    "cross_sectional_return20_excess_kurtosis": "ret20_valid_count",
    "cross_sectional_return20_right_tail_ge20": "ret20_valid_count",
    "cross_sectional_return20_left_tail_le_neg20": "ret20_valid_count",
    "cross_sectional_return5_right_tail_ge10": "ret5_valid_count",
    "cross_sectional_return5_left_tail_le_neg10": "ret5_valid_count",
    "eligible_total_amount": "amount_valid_count",
    "eligible_median_amount": "amount_valid_count",
    "eligible_total_amount_to_ma20": "amount_valid_count",
    "eligible_fraction_amount_above_own_ma20": "amount_ma20_valid_count",
    "eligible_median_own_amount_to_ma20": "amount_ma20_valid_count",
    "eligible_fraction_return1_ge5": "ret1_valid_count",
    "eligible_fraction_return1_ge10": "ret1_valid_count",
    "eligible_fraction_return1_le_neg5": "ret1_valid_count",
    "eligible_fraction_return1_le_neg10": "ret1_valid_count",
    "upside_downside_tail_balance5": "ret1_valid_count",
    "eligible_fraction_close_at_upper_limit": "upper_limit_valid_count",
    "eligible_fraction_close_at_lower_limit": "lower_limit_valid_count",
}


def create_cross_sectional_features(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[pd.DataFrame, dict[str, int]]:
    raw = connection.execute(
        """
        SELECT baseline_block,trade_date,cal_idx,count(*)::BIGINT AS eligible_count,
          count(ma5) AS ma5_valid_count,count(ma10) AS ma10_valid_count,
          count(ma20) AS ma20_valid_count,count(ma60) AS ma60_valid_count,
          count(ma120) AS ma120_valid_count,
          count(ret1) AS ret1_valid_count,count(ret5) AS ret5_valid_count,
          count(ret20) AS ret20_valid_count,count(ret60) AS ret60_valid_count,
          count(CASE WHEN new_high60 IS NOT NULL THEN 1 END) AS new_high60_valid_count,
          count(CASE WHEN new_low60 IS NOT NULL THEN 1 END) AS new_low60_valid_count,
          count(amount) AS amount_valid_count,count(amount_ma20) AS amount_ma20_valid_count,
          count(CASE WHEN upper_limit_hit IS NOT NULL THEN 1 END) AS upper_limit_valid_count,
          count(CASE WHEN lower_limit_hit IS NOT NULL THEN 1 END) AS lower_limit_valid_count,
          avg((adjusted_close>ma5)::DOUBLE) AS breadth_above_ma5,
          avg((adjusted_close>ma10)::DOUBLE) AS breadth_above_ma10,
          avg((adjusted_close>ma20)::DOUBLE) AS breadth_above_ma20,
          avg((adjusted_close>ma60)::DOUBLE) AS breadth_above_ma60,
          avg((adjusted_close>ma120)::DOUBLE) AS breadth_above_ma120,
          avg((ret1>0)::DOUBLE) AS breadth_positive_return1,
          avg((ret5>0)::DOUBLE) AS breadth_positive_return5,
          avg((ret20>0)::DOUBLE) AS breadth_positive_return20,
          avg((ret60>0)::DOUBLE) AS breadth_positive_return60,
          avg(new_high60::DOUBLE) AS breadth_new_high60,
          avg(new_low60::DOUBLE) AS breadth_new_low60,
          avg((ret1>0)::DOUBLE)-avg((ret1<0)::DOUBLE) AS advance_decline_balance,
          stddev_samp(ret1) AS cross_sectional_return1_std,
          stddev_samp(ret5) AS cross_sectional_return5_std,
          stddev_samp(ret20) AS cross_sectional_return20_std,
          avg((ret1<0)::DOUBLE) AS cross_sectional_down_fraction1,
          quantile_cont(ret1,0.10) AS cross_sectional_return1_p10,
          quantile_cont(ret1,0.50) AS cross_sectional_return1_p50,
          quantile_cont(ret1,0.90) AS cross_sectional_return1_p90,
          quantile_cont(ret1,0.90)-quantile_cont(ret1,0.10) AS cross_sectional_return1_p90_p10_spread,
          skewness(ret1) AS cross_sectional_return1_skewness,
          kurtosis(ret1) AS cross_sectional_return1_excess_kurtosis,
          quantile_cont(ret5,0.10) AS cross_sectional_return5_p10,
          quantile_cont(ret5,0.50) AS cross_sectional_return5_p50,
          quantile_cont(ret5,0.90) AS cross_sectional_return5_p90,
          quantile_cont(ret5,0.90)-quantile_cont(ret5,0.10) AS cross_sectional_return5_p90_p10_spread,
          skewness(ret5) AS cross_sectional_return5_skewness,
          kurtosis(ret5) AS cross_sectional_return5_excess_kurtosis,
          quantile_cont(ret20,0.10) AS cross_sectional_return20_p10,
          quantile_cont(ret20,0.50) AS cross_sectional_return20_p50,
          quantile_cont(ret20,0.90) AS cross_sectional_return20_p90,
          quantile_cont(ret20,0.90)-quantile_cont(ret20,0.10) AS cross_sectional_return20_p90_p10_spread,
          skewness(ret20) AS cross_sectional_return20_skewness,
          kurtosis(ret20) AS cross_sectional_return20_excess_kurtosis,
          avg((ret20>=0.20)::DOUBLE) AS cross_sectional_return20_right_tail_ge20,
          avg((ret20<=-0.20)::DOUBLE) AS cross_sectional_return20_left_tail_le_neg20,
          avg((ret5>=0.10)::DOUBLE) AS cross_sectional_return5_right_tail_ge10,
          avg((ret5<=-0.10)::DOUBLE) AS cross_sectional_return5_left_tail_le_neg10,
          sum(amount) AS eligible_total_amount,
          median(amount) AS eligible_median_amount,
          avg((amount>amount_ma20)::DOUBLE) AS eligible_fraction_amount_above_own_ma20,
          median(amount/amount_ma20) AS eligible_median_own_amount_to_ma20,
          avg((ret1>=0.05)::DOUBLE) AS eligible_fraction_return1_ge5,
          avg((ret1>=0.10)::DOUBLE) AS eligible_fraction_return1_ge10,
          avg((ret1<=-0.05)::DOUBLE) AS eligible_fraction_return1_le_neg5,
          avg((ret1<=-0.10)::DOUBLE) AS eligible_fraction_return1_le_neg10,
          avg((ret1>=0.05)::DOUBLE)-avg((ret1<=-0.05)::DOUBLE) AS upside_downside_tail_balance5,
          avg(upper_limit_hit::DOUBLE) AS eligible_fraction_close_at_upper_limit,
          avg(lower_limit_hit::DOUBLE) AS eligible_fraction_close_at_lower_limit
        FROM eligible_features
        GROUP BY baseline_block,trade_date,cal_idx
        ORDER BY trade_date
        """
    ).fetchdf()
    expected = expected_eligible_counts(connection)
    membership = connection.execute(
        """
        SELECT baseline_block,trade_date,count(*)::BIGINT AS membership_count,
               max(authorization_lineage) AS authorization_lineage
        FROM target_membership GROUP BY baseline_block,trade_date
        """
    ).fetchdf()
    calendar = connection.execute(
        """
        SELECT trade_date,cal_idx,lead(trade_date) OVER (ORDER BY trade_date) AS next_session
        FROM calendar WHERE trade_date>=DATE '2018-01-02'
        """
    ).fetchdf()
    frame = expected.merge(raw, how="left", on=["baseline_block", "trade_date"])
    frame = frame.merge(membership, on=["baseline_block", "trade_date"], how="left")
    frame = frame.merge(calendar, on="trade_date", how="left")
    frame["eligible_count"] = frame["eligible_count"].fillna(0).astype("int64")
    if not (frame.eligible_count == frame.expected_eligible).all():
        raise FeatureLibraryError("cross-sectional frame lost eligible reconciliation")
    failures: dict[str, int] = {}
    for feature, count_column in CROSS_COVERAGE.items():
        valid_count = frame[count_column].fillna(0)
        valid = (frame.eligible_count >= MIN_ELIGIBLE) & (
            valid_count / frame.eligible_count.replace(0, np.nan) >= MIN_COVERAGE
        )
        failures[feature] = int((~valid).sum())
        frame.loc[~valid, feature] = np.nan
    frame["eligible_total_amount_to_ma20"] = (
        frame.groupby("baseline_block", sort=False)["eligible_total_amount"]
        .transform(lambda values: values / values.rolling(20, min_periods=20).mean())
    )
    valid_amount_ratio = (
        frame.eligible_count >= MIN_ELIGIBLE
    ) & frame.eligible_total_amount_to_ma20.notna()
    failures["eligible_total_amount_to_ma20"] = int((~valid_amount_ratio).sum())
    frame.loc[~valid_amount_ratio, "eligible_total_amount_to_ma20"] = np.nan
    return frame.sort_values("trade_date").reset_index(drop=True), failures


def add_breadth_time_features(
    frame: pd.DataFrame, failures: dict[str, int]
) -> pd.DataFrame:
    out = frame.copy()
    groups = out.groupby("baseline_block", sort=False)
    out["breadth_above_ma20_change5"] = groups["breadth_above_ma20"].transform(
        lambda values: values - values.shift(5)
    )
    out["breadth_above_ma20_change20"] = groups["breadth_above_ma20"].transform(
        lambda values: values - values.shift(20)
    )
    out["breadth_above_ma20_volatility10"] = groups[
        "breadth_above_ma20"
    ].transform(lambda values: values.rolling(10, min_periods=10).std(ddof=1))
    state = out["breadth_above_ma20"] >= 0.5
    prior_state = groups["breadth_above_ma20"].shift(1) >= 0.5
    available = out.breadth_above_ma20.notna() & groups["breadth_above_ma20"].shift(1).notna()
    flip = (state != prior_state).astype(float).where(available)
    out["breadth_above_ma20_state_flips20"] = flip.groupby(
        out.baseline_block, sort=False
    ).transform(lambda values: values.rolling(19, min_periods=19).sum())
    for feature in (
        "breadth_above_ma20_change5",
        "breadth_above_ma20_change20",
        "breadth_above_ma20_volatility10",
        "breadth_above_ma20_state_flips20",
    ):
        failures[feature] = int(out[feature].isna().sum())
    return out


def rotation_features(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    connection.execute(
        """
        CREATE TEMP TABLE daily_ranks AS
        SELECT baseline_block,trade_date,cal_idx,symbol,ret5,ret20,
               percent_rank() OVER (PARTITION BY baseline_block,trade_date ORDER BY ret20,symbol) AS ret20_rank,
               ntile(10) OVER (PARTITION BY baseline_block,trade_date ORDER BY ret20 DESC,symbol) AS ret20_decile
        FROM eligible_features WHERE ret20 IS NOT NULL AND ret5 IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE rank_pairs AS
        SELECT c.baseline_block,c.trade_date,c.symbol,c.ret20_rank,c.ret20_decile,
               c.ret5,p.ret20_rank AS prior_rank,p.ret20_decile AS prior_decile,
               p.ret5 AS prior_ret5
        FROM daily_ranks c
        LEFT JOIN daily_ranks p
          ON c.baseline_block=p.baseline_block AND c.symbol=p.symbol
         AND c.cal_idx=p.cal_idx+5
        """
    )
    return connection.execute(
        """
        SELECT baseline_block,trade_date,count(*) AS rank_current_count,
          count(prior_rank) AS rank_matched_count,
          count(prior_rank)::DOUBLE/count(*) AS rank_match_coverage,
          corr(ret20_rank,prior_rank) AS ret20_cross_sectional_rank_stability5,
          sum(CASE WHEN ret20_decile=1 AND prior_decile=1 THEN 1 ELSE 0 END)::DOUBLE /
            nullif(least(sum((ret20_decile=1)::INTEGER),
                         sum((prior_decile=1)::INTEGER)),0) AS ret20_top_decile_overlap5,
          corr(ret5,prior_ret5) AS ret5_current_vs_prior5_cross_sectional_correlation
        FROM rank_pairs GROUP BY baseline_block,trade_date ORDER BY trade_date
        """
    ).fetchdf()


def industry_features(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    connection.execute(
        """
        CREATE TEMP TABLE industry_daily AS
        SELECT baseline_block,trade_date,cal_idx,industry,avg(ret20) AS industry_ret20,
               count(*) AS industry_member_count
        FROM eligible_features
        WHERE industry IS NOT NULL AND ret20 IS NOT NULL
        GROUP BY baseline_block,trade_date,cal_idx,industry
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE industry_coverage AS
        SELECT e.baseline_block,e.trade_date,count(*) AS eligible_count,
               count(e.industry) AS industry_mapped_count,
               count(e.industry)::DOUBLE/count(*) AS industry_mapping_coverage,
               count(DISTINCT e.industry) AS industry_count
        FROM eligible_features e
        GROUP BY e.baseline_block,e.trade_date
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE industry_top3 AS
        SELECT baseline_block,trade_date,cal_idx,industry
        FROM industry_daily
        QUALIFY row_number() OVER (
          PARTITION BY baseline_block,trade_date ORDER BY industry_ret20 DESC,industry
        )<=3
        """
    )
    leadership = connection.execute(
        """
        SELECT c.baseline_block,c.trade_date,
          count(*) AS current_top_count,
          sum((p.industry IS NOT NULL)::INTEGER) AS retained_top_count,
          sum((p.industry IS NOT NULL)::INTEGER)::DOUBLE/count(*) AS industry_top3_overlap5
        FROM industry_top3 c
        LEFT JOIN industry_top3 p
          ON c.baseline_block=p.baseline_block AND c.industry=p.industry
         AND c.cal_idx=p.cal_idx+5
        GROUP BY c.baseline_block,c.trade_date
        """
    ).fetchdf()
    coverage = connection.execute(
        """
        SELECT c.*,d.industry_ret20_dispersion
        FROM industry_coverage c
        LEFT JOIN (
          SELECT baseline_block,trade_date,
                 stddev_samp(industry_ret20) AS industry_ret20_dispersion
          FROM industry_daily GROUP BY baseline_block,trade_date
        ) d USING(baseline_block,trade_date)
        """
    ).fetchdf()
    return coverage.merge(leadership, on=["baseline_block", "trade_date"], how="left")


def load_index_features(target_dates: pd.Series) -> pd.DataFrame:
    anchor = pd.read_csv(ANCHOR, dtype={"trade_date": str})
    anchor["trade_date"] = pd.to_datetime(anchor.trade_date, format="%Y%m%d")
    anchor = anchor.sort_values("trade_date").drop_duplicates("trade_date")
    for column in ("open", "high", "low", "close", "volume", "amount"):
        anchor[column] = pd.to_numeric(anchor[column], errors="coerce")
    if anchor[["open", "high", "low", "close", "volume", "amount"]].isna().any().any():
        raise FeatureLibraryError("exact 399102 anchor has invalid required values")
    close = anchor.close
    for length in (1, 5, 10, 20, 60, 120):
        anchor[f"index_return_{length}d"] = close / close.shift(length) - 1.0
    for length in (5, 10, 20, 60, 120):
        ma = close.rolling(length, min_periods=length).mean()
        anchor[f"index_close_to_ma{length}"] = close / ma - 1.0
        anchor[f"_ma{length}"] = ma
    anchor["index_ma20_slope_5d"] = anchor._ma20 / anchor._ma20.shift(5) - 1.0
    anchor["index_ma60_slope_10d"] = anchor._ma60 / anchor._ma60.shift(10) - 1.0
    for length in (60, 120, 252):
        anchor[f"index_drawdown_from_high{length}"] = (
            close / close.rolling(length, min_periods=length).max() - 1.0
        )
    log_return = np.log(close / close.shift(1))
    for length in (10, 20, 60):
        anchor[f"index_realized_vol{length}"] = (
            log_return.rolling(length, min_periods=length).std(ddof=1) * math.sqrt(252)
        )
    downside_square = np.minimum(log_return, 0.0) ** 2
    for length in (20, 60):
        anchor[f"index_downside_vol{length}"] = (
            downside_square.rolling(length, min_periods=length).mean().pow(0.5)
            * math.sqrt(252)
        )
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            anchor.high - anchor.low,
            (anchor.high - previous_close).abs(),
            (anchor.low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    anchor["index_atr20_to_close"] = (
        true_range.rolling(20, min_periods=20).mean() / close
    )
    anchor["index_vol20_to_vol60"] = (
        anchor.index_realized_vol20 / anchor.index_realized_vol60
    )
    positive = (anchor.index_return_1d > 0).astype(float)
    anchor["index_positive_day_fraction20"] = positive.rolling(20, min_periods=20).mean()
    above20 = (anchor.index_close_to_ma20 > 0).astype(float).where(
        anchor.index_close_to_ma20.notna()
    )
    anchor["index_above_ma20_fraction20"] = above20.rolling(20, min_periods=20).mean()
    flips = (above20 != above20.shift(1)).astype(float).where(
        above20.notna() & above20.shift(1).notna()
    )
    anchor["index_above_ma20_state_flips20"] = flips.rolling(
        19, min_periods=19
    ).sum()
    anchor["index_amount_to_ma20"] = anchor.amount / anchor.amount.rolling(
        20, min_periods=20
    ).mean()
    anchor["index_volume_to_ma20"] = anchor.volume / anchor.volume.rolling(
        20, min_periods=20
    ).mean()

    def comparison(path: Path, prefix: str) -> None:
        other = duckdb.connect().execute(
            """
            SELECT CAST(trade_date AS DATE) AS trade_date,close
            FROM read_parquet(?) ORDER BY trade_date
            """,
            [str(path)],
        ).fetchdf()
        other["trade_date"] = pd.to_datetime(other.trade_date)
        other = other.drop_duplicates("trade_date").set_index("trade_date").close
        aligned = anchor.trade_date.map(other)
        for length in (20, 60):
            other_return = aligned / aligned.shift(length) - 1.0
            anchor[f"index_relative_{prefix}_return{length}"] = (
                anchor[f"index_return_{length}d"] - other_return
            )

    comparison(CSI300, "csi300")
    comparison(CHINEXT100, "399006")
    target = pd.DataFrame({"trade_date": pd.to_datetime(target_dates)})
    columns = [
        column
        for column in anchor.columns
        if column == "trade_date" or (column.startswith("index_") and not column.startswith("index_name"))
    ]
    result = target.merge(anchor[columns], on="trade_date", how="left")
    if result.filter(regex="^index_").isna().any(axis=1).any():
        missing = result.loc[result.filter(regex="^index_").isna().any(axis=1), "trade_date"]
        raise FeatureLibraryError(f"index feature coverage failure: {missing.iloc[0].date()}")
    return result


def finalize_features(
    cross: pd.DataFrame,
    rotation: pd.DataFrame,
    industry: pd.DataFrame,
    failures: dict[str, int],
) -> pd.DataFrame:
    frame = add_breadth_time_features(cross, failures)
    frame = frame.merge(rotation, on=["baseline_block", "trade_date"], how="left")
    frame = frame.merge(
        industry.drop(columns=["eligible_count"]),
        on=["baseline_block", "trade_date"],
        how="left",
    )
    rank_valid = (frame.eligible_count >= MIN_ELIGIBLE) & (
        frame.rank_match_coverage >= MIN_RANK_MATCH
    )
    for feature in (
        "ret20_cross_sectional_rank_stability5",
        "ret20_top_decile_overlap5",
        "ret5_current_vs_prior5_cross_sectional_correlation",
    ):
        valid = rank_valid & frame[feature].notna()
        failures[feature] = int((~valid).sum())
        frame.loc[~valid, feature] = np.nan
    frame["leadership_turnover5"] = 1.0 - frame.ret20_top_decile_overlap5
    failures["leadership_turnover5"] = failures["ret20_top_decile_overlap5"]
    industry_valid = (
        (frame.eligible_count >= MIN_ELIGIBLE)
        & (frame.industry_mapping_coverage >= MIN_INDUSTRY_COVERAGE)
        & (frame.industry_count >= 3)
    )
    for feature in ("industry_ret20_dispersion", "industry_top3_overlap5"):
        valid = industry_valid & frame[feature].notna()
        failures[feature] = int((~valid).sum())
        frame.loc[~valid, feature] = np.nan
    frame["industry_leadership_turnover5"] = 1.0 - frame.industry_top3_overlap5
    failures["industry_leadership_turnover5"] = failures["industry_top3_overlap5"]
    index = load_index_features(frame.trade_date)
    frame = frame.merge(index, on="trade_date", how="left")
    frame["feature_available_at"] = pd.to_datetime(frame.trade_date) + pd.Timedelta(
        hours=15
    )
    frame["decision_timezone"] = "Asia/Shanghai"
    frame["first_applicable_trade_date"] = frame.next_session
    frame["pit_grade"] = "BOUNDED_PIT_B_NOT_STRICT_PIT_A"
    frame["outcome_joined"] = False
    frame["year"] = pd.to_datetime(frame.trade_date).dt.year
    lineage = [
        "baseline_block",
        "trade_date",
        "year",
        "feature_available_at",
        "decision_timezone",
        "first_applicable_trade_date",
        "authorization_lineage",
        "pit_grade",
        "outcome_joined",
        "membership_count",
        "eligible_count",
        "industry_mapping_coverage",
        "rank_match_coverage",
    ]
    internal = {
        "expected_eligible",
        "cal_idx_x",
        "cal_idx_y",
        "next_session",
        "rank_current_count",
        "rank_matched_count",
        "industry_mapped_count",
        "industry_count",
        "eligible_count_y",
        "current_top_count",
        "retained_top_count",
        *[column for column in frame.columns if column.endswith("_valid_count")],
    }
    feature_columns = [
        column
        for column in frame.columns
        if column not in set(lineage) | internal and column not in {"eligible_count_x"}
    ]
    if "eligible_count_x" in frame:
        frame["eligible_count"] = frame["eligible_count_x"]
    output = frame[lineage + sorted(feature_columns)].copy()
    output["trade_date"] = pd.to_datetime(output.trade_date).dt.date
    output["first_applicable_trade_date"] = pd.to_datetime(
        output.first_applicable_trade_date
    ).dt.date
    if len(output) != 1942 or output.trade_date.duplicated().any():
        raise FeatureLibraryError("final feature panel date identity failure")
    if output.outcome_joined.any():
        raise FeatureLibraryError("outcome contamination flag detected")
    return output


def feature_groups(columns: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for column in columns:
        if column.startswith("index_relative_"):
            group = "style_relative_strength"
        elif column.startswith("index_") and (
            "vol" in column or "atr" in column or "downside" in column
        ):
            group = "volatility"
        elif column.startswith("index_"):
            group = "index_trend_or_liquidity"
        elif column.startswith("breadth_") or column == "advance_decline_balance":
            group = "breadth"
        elif column.startswith("cross_sectional_"):
            group = "dispersion_or_volatility"
        elif column.startswith("eligible_fraction_return") or column.startswith(
            "upside_downside"
        ) or column.endswith("_limit"):
            group = "risk_appetite"
        elif (
            "industry" in column
            or "rank" in column
            or "leadership" in column
            or column.startswith("ret20_top_decile")
            or column.startswith("ret5_current_vs_prior5")
        ):
            group = "rotation_persistence"
        elif "amount" in column:
            group = "liquidity_participation"
        else:
            group = "other"
        groups[group].append(column)
    return {key: sorted(value) for key, value in sorted(groups.items())}


def build_audit(
    spec: dict[str, Any],
    actual_inputs: dict[str, str],
    transient_manifest: dict[str, Any],
    panel_counts: dict[str, int],
    eligibility: dict[str, Any],
    output: pd.DataFrame,
    failures: dict[str, int],
) -> dict[str, Any]:
    non_features = {
        "baseline_block",
        "trade_date",
        "year",
        "feature_available_at",
        "decision_timezone",
        "first_applicable_trade_date",
        "authorization_lineage",
        "pit_grade",
        "outcome_joined",
        "membership_count",
        "eligible_count",
        "industry_mapping_coverage",
        "rank_match_coverage",
    }
    features = [column for column in output.columns if column not in non_features]
    coverage = {
        feature: {
            "valid_days": int(output[feature].notna().sum()),
            "failed_closed_days": int(output[feature].isna().sum()),
            "coverage": float(output[feature].notna().mean()),
        }
        for feature in features
    }
    return {
        "experiment_id": "EXP-P2-001",
        "result": "PASS",
        "spec_sha256": EXPECTED_SPEC,
        "formal_strategy_replays": 0,
        "trade_outcomes_read": 0,
        "nav_fields_read": ["trade_date", "basic_eligible"],
        "nav_return_or_pnl_fields_read": 0,
        "thresholds_selected_from_outcomes": 0,
        "floating_reduction_threads": 1,
        "input_hashes": actual_inputs,
        "extended_transient": {
            "canonical_sha256": transient_manifest["canonical_sha256"],
            "membership_sha256": transient_manifest["membership"]["sha256"],
            "persistent_duplicate_daily_store": transient_manifest[
                "persistent_duplicate_daily_store"
            ],
        },
        "panel_rows_by_block_including_warmup": panel_counts,
        "date_range": [START, END],
        "daily_rows": int(len(output)),
        "feature_count": len(features),
        "eligible_reconciliation": eligibility,
        "timestamp_contract": {
            "decision_at": spec["decision_timestamp"],
            "feature_available_at": "trade_date 15:00 Asia/Shanghai",
            "first_applicable_execution": spec["first_applicable_execution"],
            "same_bar_application_allowed": False,
        },
        "history_boundaries": {
            "EXTENDED_2018_2021": "2017-04-12",
            "HOLDOUT_O0_2022_2023": "2021-07-08",
            "DEVELOPMENT_2024_2025": "2023-01-01",
            "cross_block_history_carry": False,
        },
        "price_coordinate": {
            "formula": "current_close / ((prior_close-cash_per_share)/share_multiplier) - 1 on a visible supported action session",
            "rights_or_blocking_action": "nonzero rights or any non-affirmative corporate_action_valid/blocking lineage fails closed; normalized null no-rights fields on affirmative supported rows follow the frozen V1 adapter's zero default",
            "normalization_or_clipping": False,
        },
        "cross_sectional_contract": {
            "denominator": "exact V1 basic-eligible securities",
            "minimum_accumulated_valid_observations": 180,
            "contiguous_valid_tail_sessions": 121,
            "minimum_eligible_count": MIN_ELIGIBLE,
            "minimum_observation_coverage": MIN_COVERAGE,
            "industry_mapping_coverage": MIN_INDUSTRY_COVERAGE,
            "rank_match_coverage": MIN_RANK_MATCH,
            "days_below_minimum": eligibility["days_below_cross_sectional_minimum"],
        },
        "formulas": {
            "breadth": "eligible fraction satisfying the named adjusted-price condition",
            "dispersion": "daily eligible cross-section; quantile_cont, sample standard deviation, adjusted sample skewness and excess kurtosis",
            "downside_volatility": "sqrt(mean(min(log_return,0)^2))*sqrt(252)",
            "new_high_low60": "adjusted close at the inclusive 60-session adjusted high/low envelope",
            "rank_stability5": "Pearson correlation of same-symbol percentile ret20 ranks at t and t-5; equivalent rank-correlation construction",
            "top_decile_overlap5": "intersection divided by the smaller of current/prior top-decile counts",
            "industry_ret20": "equal-weight mean security ret20 within the authorized observed industry label",
            "state_flips20": "transition count across the most recent 20 valid daily states (19 transitions)",
            "limit_tolerance": "max(0.001 CNY, abs(limit_price)*1e-6)",
        },
        "feature_groups": feature_groups(features),
        "coverage": coverage,
        "coverage_failure_days_from_frozen_gates": {
            key: int(value) for key, value in sorted(failures.items())
        },
        "unavailable_families": spec["unavailable_families"],
        "limitations": [
            "All stock/membership history is bounded PIT-B, not strict vendor archival PIT-A.",
            "399102-vs-399006 and 399102-vs-CSI300 are observed index spreads, not constituent-reconstructed style factors.",
            "Industry labels are used only when CY-006 marks them valid and source_notice_date is no later than trade_date.",
            "No trade outcome, performance return, year label, or selected-entry sample influenced this library.",
        ],
        "output": {
            "path": str(OUTPUT_PARQUET),
            "sha256": sha256_file(OUTPUT_PARQUET),
        },
    }


def render_report(audit: dict[str, Any]) -> str:
    eligible = audit["eligible_reconciliation"]
    coverage = audit["coverage"]
    groups = audit["feature_groups"]
    lines = [
        "# Phase 2 — outcome-blind PIT regime feature library",
        "",
        "EXP-P2-001 passed. The artifact contains only completed-close market-state features and lineage fields; no trade outcome, NAV return, P&L, MFE, MAE, exit reason, or holding duration was read.",
        "",
        "## Reconciliation and causal boundary",
        "",
        f"- Daily rows: `{audit['daily_rows']}` (`{audit['date_range'][0]}..{audit['date_range'][1]}`)",
        f"- Feature columns: `{audit['feature_count']}`",
        f"- V1 basic-eligible count mismatches: `{eligible['mismatch_count']}` across `{eligible['date_count']}` sessions",
        f"- Eligible range: `{eligible['minimum']}..{eligible['maximum']}`; cross-sectional features fail closed on `{eligible['days_below_cross_sectional_minimum']}` sessions below 100 names",
        "- Completed-close `t` is available at 15:00 Asia/Shanghai and is applicable only to a later causally valid session.",
        "- The 2018-2021, 2022-2023, and 2024-2025 stock histories reset at their frozen replay warm-up boundaries; no history is carried across evaluation blocks.",
        "- Formal strategy replays: `0`; trade outcomes read: `0`; only `trade_date` and `basic_eligible` were projected from daily NAV for denominator validation.",
        "",
        "## Feature families",
        "",
        "| Family | Features | Minimum daily coverage |",
        "|---|---:|---:|",
    ]
    for group, features in groups.items():
        minimum = min(coverage[feature]["coverage"] for feature in features)
        lines.append(f"| {group} | {len(features)} | {minimum:.2%} |")
    lines += [
        "",
        "## Governance",
        "",
        "The denominator is the exact frozen V1 basic-eligible universe, not raw membership and not current survivors. Rows must pass all frozen hard-validity, trading-state, corporate-action, availability, age, accumulated-180-valid-observation, 121-session-contiguity, and 20-session liquidity requirements. The daily denominator matches the authoritative V1 ledger on every session.",
        "",
        "Security returns use a causal continuous coordinate. On a visible supported action day, the prior close is transformed as `(prior_close - cash_per_share) / share_multiplier`; nonzero rights participation, blocking actions, gaps, or unknown required lineage fail closed. The frozen V1 adapter's normalized null no-rights fields are zero only on rows whose action-validity and nonblocking flags are affirmative. No normalization, clipping, or tolerance relaxation is used.",
        "",
        "Cross-sectional features require at least 100 eligible securities and 95% usable observations. Industry features additionally require 80% mapped coverage; rotation rank features require 80% same-symbol matching. Missing requirements produce nulls, not substitutes.",
        "",
        "## Explicitly unavailable or limited",
        "",
        "- Growth/value and a true PIT market-cap small/large factor are unavailable.",
        "- High-beta/low-beta remains deferred pending a separately validated causal rolling-beta implementation.",
        "- Fund flow, sentiment, and a governed cyclical-sector mapping are unavailable.",
        "- `399102-CSI300` and `399102-399006` are observed index-spread proxies only.",
        "- All inputs are bounded PIT-B rather than strict archival PIT-A.",
        "",
        "## Outcome-blind verdict",
        "",
        "The library is frozen for Phase 3 attribution. Phase 2 makes no claim about which features explain returns and selects no regime threshold or strategy rule.",
        "",
        f"Feature artifact SHA-256: `{audit['output']['sha256']}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    spec, actual_inputs = validate_inputs()
    with tempfile.TemporaryDirectory(prefix="chinext_v1_phase2_") as temporary:
        transient_root = Path(temporary)
        transient_manifest = extended.materialize_transient_inputs(transient_root)
        if transient_manifest["canonical_sha256"] != EXPECTED_TRANSIENT_CANONICAL:
            raise FeatureLibraryError("extended transient canonical hash mismatch")
        if transient_manifest["membership"]["sha256"] != EXPECTED_TRANSIENT_MEMBERSHIP:
            raise FeatureLibraryError("extended transient membership hash mismatch")
        connection = duckdb.connect()
        # Floating cross-sectional moments are evidence, so their reduction order
        # must be byte-stable across reruns.  Parallel DuckDB aggregation changes
        # the last few bits even when every input row is identical.
        connection.execute("SET threads=1")
        create_membership_tables(connection, transient_root / "daily_membership.parquet")
        panel_counts = create_panel_tables(connection, transient_root)
        create_stock_features(connection)
        eligibility = reconcile_eligibility(connection)
        cross, failures = create_cross_sectional_features(connection)
        rotation = rotation_features(connection)
        industry = industry_features(connection)
        output = finalize_features(cross, rotation, industry, failures)
        connection.close()
    OUTPUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = OUTPUT_PARQUET.with_suffix(".parquet.tmp")
    output.to_parquet(temporary_output, index=False, compression="zstd")
    temporary_output.replace(OUTPUT_PARQUET)
    audit = build_audit(
        spec,
        actual_inputs,
        transient_manifest,
        panel_counts,
        eligibility,
        output,
        failures,
    )
    atomic_write(OUTPUT_AUDIT, json.dumps(audit, indent=2, sort_keys=True) + "\n")
    atomic_write(REPORT, render_report(audit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
