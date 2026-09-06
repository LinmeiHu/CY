#!/usr/bin/env python3
# ruff: noqa: E501
"""Build the outcome-blind V29R5 renewed-sell-wave signal identity.

This runner is deliberately limited to 2018-2021 Stage A.  It reads only the
frozen V13 PRIOR_HIGH_REVERSAL identity/features and exact registered CY033
daily state.  It has no execution, return, outcome, or post-2021 input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-RENEWED-SELL-WAVE-REFRESH-V29R5"
DEVELOPMENT_YEARS = (2018, 2019, 2020, 2021)
DEVELOPMENT_START = pd.Timestamp("2018-01-01")
DEVELOPMENT_END = pd.Timestamp("2021-12-31")

PREREG = OS_ROOT / f"experiments/{EXPERIMENT}_preregistration.json"
STAGE_A_FREEZE = OS_ROOT / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}-STAGE-A_report.md"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_renewed_sell_wave_refresh_v29r5"
)
STAGE_A_ROOT = EXT_ROOT / "development_stage_a"
SELECTED_SIGNALS = STAGE_A_ROOT / "renewed_sell_wave_signals.parquet"
CAP25_SIGNALS = STAGE_A_ROOT / "renewed_sell_wave_cap25_identity.parquet"
SIGNAL_AUDIT = STAGE_A_ROOT / "signal_audit.parquet"
DAILY_LINEAGE = STAGE_A_ROOT / "daily_lineage.parquet"

V13_SIGNALS = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_first_reversal_v13/"
    "prior_high_reversal/development/signals.parquet"
)
V13_STAGE_A_FREEZE = (
    OS_ROOT
    / "artifacts/ASHARE-TRUE-GAP-BELOW-L-FIRST-REVERSAL-V13_stage_a_freeze.json"
)
REGISTRY = ROOT / "configs/data_asset_registry.json"
CY033_ROOT = Path(
    "/Users/linmei/Documents/CY/data/registered_inputs/"
    "CY-033-PIT-B-DAILY-2018-20260904-V1"
)

OLD_FRESH_MAX_GAP_AGE = 14
REFRESH_MAX_GAP_AGE = 30
REFRESH_MAX_DAYS_SINCE_LOW20 = 3
MIN_PRIOR_PEAK_TO_GAP = 20
MIN_MAX_DEPTH = 0.10
MIN_CURRENT_DEPTH = 0.05
MIN_RECOVERY_FROM_LOW20 = 0.03
MIN_LOW20_AGE = 1
MAX_LOW20_AGE = 10
MIN_REBOUND_FROM_POST_GAP_LOW_OVER_L = 0.05
PRIOR_WINDOW = 20
MAX_PRIOR_ONE_PRICE_LIMIT_DOWNS = 1
MAX_SIGNAL_AMOUNT_TO_PRIOR_MEDIAN = 2.0
LIMIT_TOLERANCE_CNY = 0.006

# Explicit allow-list prevents accidental access to entry/outcome-like columns
# in the V13 entries parquet.
V13_COLUMNS = [
    "gap_id",
    "symbol",
    "board",
    "gap_date",
    "coordinate_factor",
    "L",
    "U",
    "W",
    "gap_width_pct",
    "pre_gap_inside_touch_sessions",
    "pre_gap_corridor_touch_sessions",
    "pre_peak_to_gap_sessions",
    "pre_gap_drawdown_from_120d_peak",
    "trigger",
    "signal_date",
    "signal_time",
    "gap_age",
    "max_depth",
    "current_depth",
    "days_since_low20",
    "recovery_from_low20",
    "decision_latest_timestamp",
    "feature_uses_post_signal_information",
]

FORBIDDEN_PARENT_TOKENS = (
    "entry",
    "exit",
    "outcome",
    "return",
    "profit",
    "target_hit",
    "holding",
    "forward",
)

DAILY_COLUMNS = [
    "trade_date",
    "decision_at",
    "decision_timezone",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "amount",
    "trade_status",
    "is_st",
    "up_limit_price",
    "down_limit_price",
    "current_day_data_tradable",
    "industry",
    "corporate_action_count",
    "corporate_action_blocking",
    "share_multiplier",
    "cash_per_share",
    "bar_valid",
    "trading_state_valid",
    "industry_valid",
    "corporate_action_valid",
    "market_rule_valid",
    "hard_valid",
    "available_at",
    "snapshot_id",
    "daily_snapshot_id",
    "trading_state_snapshot_id",
    "industry_snapshot_id",
    "corporate_action_snapshot_id",
]


class V29R5Error(RuntimeError):
    """Fail closed on identity, chronology, lineage, or source drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    temporary.replace(path)


def publish_no_replace(staged: Path, target: Path) -> None:
    """Atomically publish one same-filesystem file without overwriting."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise V29R5Error(f"refusing to overwrite existing artifact: {target}")
    os.link(staged, target)
    staged.unlink()


def cy033_path(year: int) -> Path:
    return CY033_ROOT / f"daily/partition_year={year}/data_0.parquet"


def _nonempty(value: Any) -> bool:
    return bool(pd.notna(value) and str(value).strip())


def _is_true(value: Any) -> bool:
    return bool(pd.notna(value) and bool(value))


def _finite_positive(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return bool(math.isfinite(number) and number > 0)


def _price_ticks(value: Any) -> int:
    if not _finite_positive(value):
        return -1
    return math.floor(float(value) * 100.0 + 0.5 + 1e-6)


def refreshed_freshness(gap_age: Any, days_since_low20: Any) -> bool:
    """Old gaps qualify only when a new sell wave made the low very recently."""
    if pd.isna(gap_age) or pd.isna(days_since_low20):
        return False
    age = int(gap_age)
    low_age = int(days_since_low20)
    return bool(
        0 <= age <= OLD_FRESH_MAX_GAP_AGE
        or (
            OLD_FRESH_MAX_GAP_AGE < age <= REFRESH_MAX_GAP_AGE
            and MIN_LOW20_AGE <= low_age <= REFRESH_MAX_DAYS_SINCE_LOW20
        )
    )


def _one_price_limit_down(row: pd.Series) -> bool:
    values = [row.get(column) for column in ("open", "high", "low", "close")]
    limit = row.get("down_limit_price")
    return bool(
        _finite_positive(limit)
        and all(_finite_positive(value) for value in values)
        and all(
            math.isclose(
                float(value),
                float(limit),
                rel_tol=0.0,
                abs_tol=LIMIT_TOLERANCE_CNY,
            )
            for value in values
        )
    )


def _limit_history_row_known(row: pd.Series) -> bool:
    status = pd.to_numeric(
        pd.Series([row.get("trade_status")]), errors="coerce"
    ).iloc[0]
    if pd.isna(status) or float(status) not in (0.0, 1.0):
        return False
    if float(status) == 0.0:
        return True
    return bool(
        all(
            _finite_positive(row.get(column))
            for column in ("open", "high", "low", "close", "down_limit_price")
        )
    )


def _row_lineage_valid(row: pd.Series, signal_time: pd.Timestamp) -> bool:
    required_true = (
        "bar_valid",
        "trading_state_valid",
        "industry_valid",
        "corporate_action_valid",
        "market_rule_valid",
        "hard_valid",
    )
    if not all(_is_true(row.get(column)) for column in required_true):
        return False
    if str(row.get("decision_timezone", "")) != "Asia/Shanghai":
        return False
    if not all(
        _nonempty(row.get(column))
        for column in (
            "snapshot_id",
            "daily_snapshot_id",
            "trading_state_snapshot_id",
            "industry_snapshot_id",
            "corporate_action_snapshot_id",
        )
    ):
        return False
    available_at = pd.to_datetime(row.get("available_at"), errors="coerce")
    decision_at = pd.to_datetime(row.get("decision_at"), errors="coerce")
    return bool(
        pd.notna(available_at)
        and pd.notna(decision_at)
        and available_at <= decision_at
        and available_at <= signal_time
        and decision_at <= signal_time
    )


def _action_free(row: pd.Series) -> bool:
    count = pd.to_numeric(
        pd.Series([row.get("corporate_action_count")]), errors="coerce"
    ).iloc[0]
    multiplier = pd.to_numeric(
        pd.Series([row.get("share_multiplier")]), errors="coerce"
    ).iloc[0]
    cash = pd.to_numeric(
        pd.Series([row.get("cash_per_share")]), errors="coerce"
    ).iloc[0]
    blocking = row.get("corporate_action_blocking")
    return bool(
        pd.notna(count)
        and float(count) == 0.0
        and pd.notna(blocking)
        and not bool(blocking)
        and pd.notna(multiplier)
        and abs(float(multiplier) - 1.0) <= 1e-12
        and pd.notna(cash)
        and abs(float(cash)) <= 1e-12
    )


def _registry_asset(registry: dict[str, Any], asset_id: str) -> dict[str, Any]:
    matches = [
        item for item in registry.get("assets", []) if item.get("asset_id") == asset_id
    ]
    if len(matches) != 1:
        raise V29R5Error(f"{asset_id} must resolve exactly once in registry")
    return matches[0]


def verify_sources(prereg: dict[str, Any]) -> dict[str, str]:
    if prereg.get("experiment") != EXPERIMENT:
        raise V29R5Error("wrong preregistration experiment")
    if prereg.get("stage") != "DEVELOPMENT_STAGE_A_ONLY":
        raise V29R5Error("preregistration is not Stage-A-only")
    if prereg.get("development") != ["2018-01-01", "2021-12-31"]:
        raise V29R5Error("development boundary drift")
    if prereg.get("runner_sha256") != sha256(Path(__file__)):
        raise V29R5Error("runner hash differs from preregistration")
    if prereg.get("outcome_access") != "PROHIBITED":
        raise V29R5Error("outcome access is not explicitly prohibited")

    source_identity = prereg.get("source_identity", {})
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    cy033 = _registry_asset(registry, "CY-033")
    expected_registry_identity = source_identity.get("cy033", {}).get(
        "registry_asset_normalized_sha256"
    )
    if normalized_json_sha256(cy033) != expected_registry_identity:
        raise V29R5Error("CY033 registry identity drift")
    if (
        cy033.get("status") != "RESEARCH_CONDITIONAL"
        or cy033.get("physical_state") != "MATERIALIZED"
        or Path(str(cy033.get("location"))) != CY033_ROOT
        or cy033.get("lineage", {}).get("record_available_at") is not True
        or cy033.get("lineage", {}).get("record_snapshot_id") is not True
    ):
        raise V29R5Error("CY033 is not authorized for bounded conditional research")

    verified = {"runner": sha256(Path(__file__)), "preregistration": sha256(PREREG)}
    for name, item in source_identity.get("parent_artifacts", {}).items():
        path = Path(item["path"])
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise V29R5Error(f"parent artifact drift: {name}")
        verified[name] = item["sha256"]

    manifest_path = Path(str(cy033.get("lineage", {}).get("manifest_path", "")))
    cy033_identity = source_identity.get("cy033", {})
    if (
        not manifest_path.is_file()
        or manifest_path != CY033_ROOT / "asset_manifest.json"
        or sha256(manifest_path) != cy033_identity.get("manifest_sha256")
    ):
        raise V29R5Error("CY033 manifest drift")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("asset_id") != "CY-033" or manifest.get("status") != "PASS":
        raise V29R5Error("CY033 manifest is not active for conditional research")
    listed = {item.get("path"): item for item in manifest.get("files", [])}
    for year in DEVELOPMENT_YEARS:
        expected = cy033_identity.get("partitions", {}).get(str(year), {})
        path = cy033_path(year)
        relative = str(path.relative_to(CY033_ROOT))
        if listed.get(relative, {}).get("sha256") != expected.get("sha256"):
            raise V29R5Error(f"CY033 manifest partition mismatch: {year}")
        if (
            not path.is_file()
            or path.stat().st_size != expected.get("size")
            or sha256(path) != expected.get("sha256")
        ):
            raise V29R5Error(f"CY033 partition drift: {year}")
        verified[f"cy033_{year}"] = expected["sha256"]
    return verified


def load_parent() -> pd.DataFrame:
    if any(
        token in column.lower()
        for column in V13_COLUMNS
        for token in FORBIDDEN_PARENT_TOKENS
    ):
        raise V29R5Error("V13 parent allow-list contains outcome/execution-like column")
    # Read the frozen development signal artifact, never its sibling entry or
    # outcome artifacts, and still retain an explicit feature allow-list.
    connection = duckdb.connect()
    projection = ",".join(f'"{column}"' for column in V13_COLUMNS)
    frame = connection.execute(
        f"""
        SELECT {projection}
        FROM read_parquet(?)
        WHERE signal_date BETWEEN TIMESTAMP '2018-01-01' AND TIMESTAMP '2021-12-31 23:59:59.999999'
        ORDER BY signal_time,symbol,gap_id
        """,
        [str(V13_SIGNALS)],
    ).fetchdf()
    connection.close()
    for column in ("gap_date", "signal_date", "signal_time", "decision_latest_timestamp"):
        frame[column] = pd.to_datetime(frame[column])
    frame = frame.sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    if len(frame) != 850 or frame.gap_id.duplicated().any():
        raise V29R5Error("frozen V13 2018-2021 identity mismatch")
    if not frame.trigger.eq("PRIOR_HIGH_REVERSAL").all():
        raise V29R5Error("parent trigger is not uniformly PRIOR_HIGH_REVERSAL")
    if not frame.board.isin(["MAIN", "CHINEXT"]).all():
        raise V29R5Error("unexpected board in V13 parent")
    if frame.feature_uses_post_signal_information.fillna(True).astype(bool).any():
        raise V29R5Error("post-signal parent feature entered Stage A")
    if frame.decision_latest_timestamp.isna().any() or (
        frame.decision_latest_timestamp > frame.signal_time
    ).any():
        raise V29R5Error("parent feature timestamp exceeds signal decision")
    numeric = frame[
        [
            "coordinate_factor",
            "L",
            "pre_peak_to_gap_sessions",
            "gap_age",
            "max_depth",
            "current_depth",
            "days_since_low20",
        ]
    ].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise V29R5Error("required V13 semantic feature is missing")
    return frame


def load_cy033(symbols: list[str]) -> pd.DataFrame:
    wanted = pd.DataFrame({"symbol": sorted(set(symbols))})
    paths = [str(cy033_path(year)) for year in DEVELOPMENT_YEARS]
    connection = duckdb.connect()
    connection.register("wanted_symbols", wanted)
    columns = ",".join(f"d.{column}" for column in DAILY_COLUMNS)
    frame = connection.execute(
        f"""
        SELECT {columns}
        FROM read_parquet(?, union_by_name=true) d
        JOIN wanted_symbols s USING(symbol)
        WHERE d.trade_date BETWEEN DATE '2018-01-01' AND DATE '2021-12-31'
        ORDER BY d.symbol,d.trade_date
        """,
        [paths],
    ).fetchdf()
    connection.close()
    for column in ("trade_date", "decision_at", "available_at"):
        frame[column] = pd.to_datetime(frame[column])
    if frame.empty or frame.duplicated(["symbol", "trade_date"]).any():
        raise V29R5Error("CY033 selected-symbol slice identity failure")
    if frame.trade_date.min() < DEVELOPMENT_START or frame.trade_date.max() > DEVELOPMENT_END:
        raise V29R5Error("CY033 query escaped the development boundary")
    return frame


def _lineage_rows(
    gap: pd.Series,
    group: pd.DataFrame,
    accessed: dict[int, set[str]],
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for index in sorted(accessed):
        row = group.loc[index]
        records.append(
            {
                "gap_id": str(gap.gap_id),
                "symbol": str(gap.symbol),
                "source_trade_date": pd.Timestamp(row.trade_date).normalize(),
                "lineage_roles": "|".join(sorted(accessed[index])),
                **{
                    column: row.get(column)
                    for column in DAILY_COLUMNS
                    if column != "symbol"
                },
            }
        )
    return pd.DataFrame.from_records(records)


def evaluate_fixed_signal(
    gap: pd.Series,
    symbol_daily: pd.DataFrame,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Rebind one frozen V13 signal and recompute every price feature in CY033."""
    group = symbol_daily.sort_values("trade_date", kind="mergesort").reset_index(drop=True)
    group.index = np.arange(len(group), dtype=int)
    gap_date = pd.Timestamp(gap.gap_date).normalize()
    signal_date = pd.Timestamp(gap.signal_date).normalize()
    signal_time = pd.Timestamp(gap.signal_time)
    audit: dict[str, Any] = {
        "gap_id": str(gap.gap_id),
        "symbol": str(gap.symbol),
        "board": str(gap.board),
        "gap_date": gap_date,
        "signal_date": signal_date,
        "signal_time": signal_time,
        "parent_v13_gap_age": int(gap.gap_age),
        "parent_v13_max_depth": float(gap.max_depth),
        "parent_v13_current_depth": float(gap.current_depth),
        "parent_v13_days_since_low20": int(gap.days_since_low20),
        "parent_v13_recovery_from_low20": float(gap.recovery_from_low20),
        "m20_gate": bool(int(gap.pre_peak_to_gap_sessions) >= MIN_PRIOR_PEAK_TO_GAP),
        "selected": False,
        "selection_status": "NOT_EVALUATED",
        "selection_failure_class": "NOT_EVALUATED",
    }
    accessed: dict[int, set[str]] = defaultdict(set)

    if gap_date < DEVELOPMENT_START:
        audit.update(
            selection_status="GAP_BEFORE_CY033_BOUND",
            selection_failure_class="REGISTERED_COVERAGE_BOUND",
        )
        return audit, pd.DataFrame()
    gap_matches = group.index[group.trade_date.eq(gap_date)].tolist()
    signal_matches = group.index[group.trade_date.eq(signal_date)].tolist()
    if len(gap_matches) != 1 or len(signal_matches) != 1:
        audit.update(
            selection_status="MISSING_OR_DUPLICATE_FIXED_IDENTITY_ROW",
            selection_failure_class="REGISTERED_LINEAGE_INVALID",
        )
        return audit, pd.DataFrame()
    gap_index = int(gap_matches[0])
    signal_index = int(signal_matches[0])
    if signal_index <= gap_index or signal_index < PRIOR_WINDOW:
        audit.update(
            selection_status="INVALID_FIXED_IDENTITY_ORDER",
            selection_failure_class="FROZEN_IDENTITY_MISMATCH",
        )
        return audit, pd.DataFrame()

    previous_index = signal_index - 1
    path_indices = list(range(gap_index, signal_index + 1))
    rolling20_indices = list(range(signal_index - PRIOR_WINDOW + 1, signal_index + 1))
    prior20_indices = list(range(signal_index - PRIOR_WINDOW, signal_index))
    for index in path_indices:
        accessed[index].add("V13_GAP_TO_SIGNAL_COORDINATE_PATH")
    for index in rolling20_indices:
        accessed[index].add("V13_UNIFORM_RAW_LOW20")
    accessed[previous_index].add("V13_PRIOR_HIGH_TRIGGER_PREVIOUS_BAR")
    for index in prior20_indices:
        accessed[index].add("V28_PRIOR20_LIMIT")

    before = group.iloc[:signal_index]
    traded = before.loc[before.trade_status.eq(1)].tail(PRIOR_WINDOW)
    traded_indices = list(traded.index.astype(int))
    for index in traded_indices:
        accessed[index].add("V28R2_PRIOR20_AMOUNT")
    between = pd.DataFrame()
    if len(traded) == PRIOR_WINDOW:
        between = before.loc[before.trade_date.ge(traded.trade_date.iloc[0])]
        for index in between.index.astype(int):
            accessed[int(index)].add("V28R2_TRADING_STATE_CONTINUITY")

    used = group.loc[sorted(accessed)]
    all_lineage_valid = bool(
        not used.empty
        and all(_row_lineage_valid(row, signal_time) for _, row in used.iterrows())
    )
    path = group.loc[path_indices]
    post_gap_path = group.loc[gap_index + 1 : signal_index]
    rolling20 = group.loc[rolling20_indices]
    coordinate_action_free = bool(
        all(_action_free(row) for _, row in path.iterrows())
        and all(_action_free(row) for _, row in rolling20.iterrows())
    )
    gap_row = group.loc[gap_index]
    signal_row = group.loc[signal_index]
    previous_row = group.loc[previous_index]
    computed_gap_age = signal_index - gap_index
    signal_decision_match = bool(pd.Timestamp(signal_row.decision_at) == signal_time)
    frozen_gap_age_match = bool(computed_gap_age == int(gap.gap_age))
    fixed_identity_match = bool(signal_decision_match and frozen_gap_age_match)
    raw_l = (
        float(gap.L) / float(gap.coordinate_factor)
        if _finite_positive(gap.L) and _finite_positive(gap.coordinate_factor)
        else math.nan
    )
    post_gap_lows = pd.to_numeric(post_gap_path.low, errors="coerce")
    rolling20_lows = pd.to_numeric(rolling20.low, errors="coerce")
    prices_complete = bool(
        _finite_positive(raw_l)
        and len(post_gap_path) >= 1
        and len(rolling20) == PRIOR_WINDOW
        and np.isfinite(post_gap_lows.to_numpy(dtype=float)).all()
        and post_gap_lows.gt(0).all()
        and np.isfinite(rolling20_lows.to_numpy(dtype=float)).all()
        and rolling20_lows.gt(0).all()
        and _finite_positive(signal_row.close)
        and _finite_positive(previous_row.high)
    )
    max_depth = (
        1.0 - float(post_gap_lows.min()) / raw_l if prices_complete else math.nan
    )
    current_depth = (
        1.0 - float(signal_row.close) / raw_l if prices_complete else math.nan
    )
    rebound = max_depth - current_depth if prices_complete else math.nan
    if prices_complete:
        low_ticks = np.asarray(
            [_price_ticks(value) for value in rolling20_lows], dtype=np.int64
        )
        lowest_tick = int(low_ticks.min())
        low20_offset = int(np.flatnonzero(low_ticks == lowest_tick)[-1])
        low20_raw = float(rolling20_lows.iloc[low20_offset])
        days_since_low20 = len(rolling20) - 1 - low20_offset
        recovery_from_low20 = float(signal_row.close) / low20_raw - 1.0
    else:
        low20_raw = math.nan
        days_since_low20 = -1
        recovery_from_low20 = math.nan
    old_f14_gate = bool(computed_gap_age <= OLD_FRESH_MAX_GAP_AGE)
    renewed_sell_wave_gate = refreshed_freshness(
        computed_gap_age, days_since_low20
    )
    gap_raw_identity = bool(
        coordinate_action_free
        and _price_ticks(gap_row.high) == _price_ticks(raw_l)
    )
    prior_high_identity = bool(
        coordinate_action_free
        and _price_ticks(signal_row.close) > _price_ticks(previous_row.high)
    )
    no_l_touch_before_signal = bool(
        coordinate_action_free
        and len(post_gap_path) >= 1
        and all(
            _finite_positive(value) and _price_ticks(value) < _price_ticks(raw_l)
            for value in post_gap_path.high
        )
    )
    uniform_v13_gate = bool(
        prices_complete
        and max_depth >= MIN_MAX_DEPTH
        and current_depth >= MIN_CURRENT_DEPTH
        and MIN_LOW20_AGE <= days_since_low20 <= MAX_LOW20_AGE
        and recovery_from_low20 >= MIN_RECOVERY_FROM_LOW20
        and prior_high_identity
    )
    r5_gate = bool(
        prices_complete and rebound >= MIN_REBOUND_FROM_POST_GAP_LOW_OVER_L
    )

    prior20 = group.loc[prior20_indices]
    prior20_limit_history_valid = bool(
        len(prior20) == PRIOR_WINDOW
        and all(_row_lineage_valid(row, signal_time) for _, row in prior20.iterrows())
        and all(_limit_history_row_known(row) for _, row in prior20.iterrows())
    )
    prior20_limit_count = (
        int(sum(_one_price_limit_down(row) for _, row in prior20.iterrows()))
        if prior20_limit_history_valid
        else -1
    )
    current_state_gate = bool(
        fixed_identity_match
        and _row_lineage_valid(signal_row, signal_time)
        and _is_true(signal_row.current_day_data_tradable)
        and pd.notna(signal_row.trade_status)
        and float(signal_row.trade_status) == 1.0
        and pd.notna(signal_row.is_st)
        and not bool(signal_row.is_st)
        and _nonempty(signal_row.industry)
        and _action_free(signal_row)
    )
    v28_gate = bool(
        current_state_gate
        and prior20_limit_history_valid
        and prior20_limit_count <= MAX_PRIOR_ONE_PRICE_LIMIT_DOWNS
    )
    v28r1_gate = bool(
        v28_gate
        and _finite_positive(signal_row.close)
        and _finite_positive(signal_row.up_limit_price)
        and float(signal_row.close)
        < float(signal_row.up_limit_price) - LIMIT_TOLERANCE_CNY
    )

    amounts = pd.to_numeric(traded.amount, errors="coerce")
    unknown_between = (
        int((~between.trade_status.isin([0, 1])).sum())
        if len(traded) == PRIOR_WINDOW
        else -1
    )
    amount_history_valid = bool(
        len(traded) == PRIOR_WINDOW
        and unknown_between == 0
        and all(_row_lineage_valid(row, signal_time) for _, row in traded.iterrows())
        and np.isfinite(amounts.to_numpy(dtype=float)).all()
        and amounts.gt(0).all()
    )
    prior20_median_amount = float(amounts.median()) if amount_history_valid else math.nan
    signal_amount = pd.to_numeric(
        pd.Series([signal_row.amount]), errors="coerce"
    ).iloc[0]
    amount_ratio = (
        float(signal_amount) / prior20_median_amount
        if v28r1_gate
        and _finite_positive(signal_amount)
        and _finite_positive(prior20_median_amount)
        else math.nan
    )
    v28r2_gate = bool(
        v28r1_gate
        and amount_history_valid
        and math.isfinite(amount_ratio)
        and amount_ratio <= MAX_SIGNAL_AMOUNT_TO_PRIOR_MEDIAN
    )
    final_gate = bool(
        fixed_identity_match
        and audit["m20_gate"]
        and uniform_v13_gate
        and r5_gate
        and renewed_sell_wave_gate
        and all_lineage_valid
        and gap_raw_identity
        and prior_high_identity
        and no_l_touch_before_signal
        and v28r2_gate
    )

    failure_order = (
        ("FROZEN_IDENTITY", fixed_identity_match),
        ("M20", audit["m20_gate"]),
        ("UNIFORM_RAW_V13", uniform_v13_gate),
        ("R5", r5_gate),
        ("REFRESH_F30_LOW3", renewed_sell_wave_gate),
        ("REGISTERED_LINEAGE", all_lineage_valid),
        ("ACTION_FREE_COORDINATE", coordinate_action_free),
        ("GAP_RAW_IDENTITY", gap_raw_identity),
        ("PRIOR_HIGH_TRIGGER_IDENTITY", prior_high_identity),
        ("NO_L_TOUCH", no_l_touch_before_signal),
        ("V28_NON_ST_AND_LIMIT_HISTORY", v28_gate),
        ("V28R1_NOT_LOCKED", v28r1_gate),
        ("V28R2_ORDERLY_AMOUNT", v28r2_gate),
    )
    first_failure = next((name for name, passed in failure_order if not passed), "NONE")
    audit.update(
        {
            "gap_age": computed_gap_age,
            "max_depth": max_depth,
            "current_depth": current_depth,
            "rebound_from_post_gap_low_over_l": rebound,
            "days_since_low20": days_since_low20,
            "low20_raw": low20_raw,
            "recovery_from_low20": recovery_from_low20,
            "old_f14_gate": old_f14_gate,
            "renewed_sell_wave_gate": renewed_sell_wave_gate,
            "uniform_raw_v13_gate": uniform_v13_gate,
            "r5_gate": r5_gate,
            "fixed_signal_decision_match": signal_decision_match,
            "frozen_gap_age_match": frozen_gap_age_match,
            "parent_low_age_matches_uniform": bool(
                int(gap.days_since_low20) == days_since_low20
            ),
            "all_accessed_lineage_valid": all_lineage_valid,
            "coordinate_window_action_free": coordinate_action_free,
            "gap_raw_tick_identity": gap_raw_identity,
            "prior_high_raw_tick_identity": prior_high_identity,
            "no_l_touch_before_signal": no_l_touch_before_signal,
            "prior20_one_price_limit_down_count": prior20_limit_count,
            "v28_state_gate": v28_gate,
            "v28r1_not_locked_gate": v28r1_gate,
            "prior20_completed_trading_sessions": len(traded),
            "prior20_unknown_trading_state_rows": unknown_between,
            "prior20_amount_history_complete": amount_history_valid,
            "prior20_median_amount": prior20_median_amount,
            "signal_raw_amount": (
                float(signal_amount) if _finite_positive(signal_amount) else math.nan
            ),
            "signal_amount_to_prior20_median": amount_ratio,
            "v28r2_orderly_amount_gate": v28r2_gate,
            "signal_industry": signal_row.industry,
            "selected": final_gate,
            "selection_status": (
                "SELECTED_RENEWED_SELL_WAVE_REFRESH"
                if final_gate
                else f"REJECTED_{first_failure}"
            ),
            "selection_failure_class": first_failure,
            "added_beyond_old_f14": bool(final_gate and not old_f14_gate),
            "feature_latest_timestamp": max(
                pd.to_datetime(used.available_at).max(),
                pd.Timestamp(gap.decision_latest_timestamp),
            ),
            "feature_uses_post_signal_information": False,
            "signal_available_at": signal_row.available_at,
            "signal_snapshot_id": signal_row.snapshot_id,
            "signal_daily_snapshot_id": signal_row.daily_snapshot_id,
            "signal_trading_state_snapshot_id": signal_row.trading_state_snapshot_id,
            "signal_industry_snapshot_id": signal_row.industry_snapshot_id,
            "signal_corporate_action_snapshot_id": signal_row.corporate_action_snapshot_id,
        }
    )
    return audit, _lineage_rows(gap, group, accessed)


def build_signal_cohort(
    parent: pd.DataFrame, daily: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    groups = {
        str(symbol): group.reset_index(drop=True)
        for symbol, group in daily.groupby("symbol", sort=False)
    }
    audits: list[dict[str, Any]] = []
    lineages: list[pd.DataFrame] = []
    parent_by_id = parent.set_index(parent.gap_id.astype(str), drop=False)
    for gap in parent.itertuples(index=False):
        group = groups.get(str(gap.symbol))
        if group is None:
            audits.append(
                {
                    "gap_id": str(gap.gap_id),
                    "symbol": str(gap.symbol),
                    "board": str(gap.board),
                    "gap_date": pd.Timestamp(gap.gap_date),
                    "signal_date": pd.Timestamp(gap.signal_date),
                    "signal_time": pd.Timestamp(gap.signal_time),
                    "gap_age": int(gap.gap_age),
                    "days_since_low20": int(gap.days_since_low20),
                    "old_f14_gate": int(gap.gap_age) <= OLD_FRESH_MAX_GAP_AGE,
                    "renewed_sell_wave_gate": refreshed_freshness(
                        gap.gap_age, gap.days_since_low20
                    ),
                    "m20_gate": int(gap.pre_peak_to_gap_sessions)
                    >= MIN_PRIOR_PEAK_TO_GAP,
                    "r5_gate": float(gap.max_depth) - float(gap.current_depth)
                    >= MIN_REBOUND_FROM_POST_GAP_LOW_OVER_L,
                    "selected": False,
                    "selection_status": "SYMBOL_ABSENT_FROM_CY033",
                    "selection_failure_class": "REGISTERED_LINEAGE_INVALID",
                    "added_beyond_old_f14": False,
                }
            )
            continue
        audit, lineage = evaluate_fixed_signal(pd.Series(gap._asdict()), group)
        audits.append(audit)
        if not lineage.empty:
            lineages.append(lineage)

    audit_frame = pd.DataFrame.from_records(audits).sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    selected_ids = audit_frame.loc[audit_frame.selected.eq(True), "gap_id"].astype(str)
    selected_parent = parent_by_id.loc[selected_ids].reset_index(drop=True).rename(
        columns={
            "gap_age": "parent_v13_gap_age_source",
            "max_depth": "parent_v13_max_depth_source",
            "current_depth": "parent_v13_current_depth_source",
            "days_since_low20": "parent_v13_days_since_low20_source",
            "recovery_from_low20": "parent_v13_recovery_from_low20_source",
        }
    )
    selected = selected_parent.merge(
        audit_frame.loc[audit_frame.selected.eq(True)],
        on=[
            "gap_id",
            "symbol",
            "board",
            "gap_date",
            "signal_date",
            "signal_time",
        ],
        how="inner",
        validate="one_to_one",
        suffixes=("", "_audit"),
    )
    selected = selected.sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    lineage = (
        pd.concat(lineages, ignore_index=True)
        if lineages
        else pd.DataFrame()
    )
    if selected.empty or selected.gap_id.duplicated().any():
        raise V29R5Error("selected signal identity failure")
    if lineage.empty or lineage.duplicated(["gap_id", "source_trade_date"]).any():
        raise V29R5Error("multi-row daily lineage identity failure")
    if pd.to_datetime(selected.signal_date).gt(DEVELOPMENT_END).any():
        raise V29R5Error("post-2021 selected signal entered Stage A")
    if pd.to_datetime(lineage.source_trade_date).gt(DEVELOPMENT_END).any():
        raise V29R5Error("post-2021 lineage row entered Stage A")
    if (
        not selected.fixed_signal_decision_match.eq(True).all()
        or not selected.frozen_gap_age_match.eq(True).all()
        or not selected.uniform_raw_v13_gate.eq(True).all()
        or selected.feature_uses_post_signal_information.fillna(True).astype(bool).any()
        or (
            pd.to_datetime(selected.feature_latest_timestamp)
            > pd.to_datetime(selected.signal_time)
        ).any()
    ):
        raise V29R5Error("selected signal chronology or uniform-feature invariant failed")
    return selected, audit_frame, lineage


def build_cap25_identity(selected: pd.DataFrame) -> pd.DataFrame:
    """Freeze the sole primary, economically ranked cap-25 admission cohort.

    Every signal date is capped at 25 names.  Industry order is lexical and
    each industry's queue is ordered by the preregistered demand-recovery
    strength measure (rebound/L descending), then stable identity.  Raw signals
    remain a morphology audit only and cannot compete with this primary cohort
    after outcomes are opened.
    """
    needed = {
        "gap_id",
        "symbol",
        "signal_date",
        "signal_industry",
        "rebound_from_post_gap_low_over_l",
    }
    if not needed.issubset(selected.columns):
        raise V29R5Error("cap25 identity is missing required signal columns")
    if selected.gap_id.duplicated().any():
        raise V29R5Error("cap25 input contains duplicate gap identity")
    if selected.signal_industry.map(_nonempty).eq(False).any():
        raise V29R5Error("cap25 industry identity is missing")

    kept: list[pd.DataFrame] = []
    normalized_dates = pd.to_datetime(selected.signal_date).dt.normalize()
    for signal_date in sorted(normalized_dates.unique()):
        event = selected.loc[normalized_dates.eq(signal_date)].copy()
        queues = {
            str(industry): group.sort_values(
                ["rebound_from_post_gap_low_over_l", "symbol", "gap_id"],
                ascending=[False, True, True],
                kind="mergesort",
            ).reset_index(drop=True)
            for industry, group in event.groupby("signal_industry", sort=True)
        }
        industries = sorted(queues)
        positions = {industry: 0 for industry in industries}
        rows: list[pd.Series] = []
        while len(rows) < 25:
            advanced = False
            for industry in industries:
                position = positions[industry]
                queue = queues[industry]
                if position >= len(queue):
                    continue
                rows.append(queue.iloc[position])
                positions[industry] += 1
                advanced = True
                if len(rows) == 25:
                    break
            if not advanced:
                break
        if rows:
            frame = pd.DataFrame(rows)
            frame["cap25_rank"] = np.arange(1, len(frame) + 1, dtype=int)
            frame["cap25_primary_economic_admission"] = True
            kept.append(frame)
    if not kept:
        raise V29R5Error("cap25 identity is empty")
    result = pd.concat(kept, ignore_index=True)
    if result.gap_id.duplicated().any():
        raise V29R5Error("cap25 output contains duplicate gap identity")
    if result.groupby(pd.to_datetime(result.signal_date).dt.normalize()).size().gt(25).any():
        raise V29R5Error("cap25 event limit was violated")
    return result


def summarize(
    parent: pd.DataFrame,
    selected: pd.DataFrame,
    cap25: pd.DataFrame,
    audit: pd.DataFrame,
    lineage: pd.DataFrame,
) -> dict[str, Any]:
    signal_year = pd.to_datetime(selected.signal_date).dt.year
    cap25_year = pd.to_datetime(cap25.signal_date).dt.year
    added = selected.loc[selected.added_beyond_old_f14.eq(True)].copy()
    added_year = pd.to_datetime(added.signal_date).dt.year
    by_year: dict[str, Any] = {}
    for year in DEVELOPMENT_YEARS:
        parent_mask = pd.to_datetime(parent.signal_date).dt.year.eq(year)
        selected_mask = signal_year.eq(year)
        added_mask = added_year.eq(year)
        by_year[str(year)] = {
            "parent_signals": int(parent_mask.sum()),
            "selected_signals": int(selected_mask.sum()),
            "selected_signal_dates": int(
                selected.loc[selected_mask, "signal_date"].nunique()
            ),
            "old_f14_selected": int(
                selected.loc[selected_mask, "old_f14_gate"].eq(True).sum()
            ),
            "added_old_gap_signals": int(added_mask.sum()),
            "added_old_gap_dates": int(added.loc[added_mask, "signal_date"].nunique()),
            "cap25_signals": int(cap25_year.eq(year).sum()),
            "cap25_signal_dates": int(
                cap25.loc[cap25_year.eq(year), "signal_date"].nunique()
            ),
        }
    date_counts = selected.groupby(pd.to_datetime(selected.signal_date).dt.normalize()).size()
    cap25_date_counts = cap25.groupby(
        pd.to_datetime(cap25.signal_date).dt.normalize()
    ).size()
    added_date_counts = added.groupby(pd.to_datetime(added.signal_date).dt.normalize()).size()
    selected_count = len(selected)
    added_count = len(added)
    return {
        "parent_signals": len(parent),
        "selected_signals": selected_count,
        "selected_signal_dates": int(selected.signal_date.nunique()),
        "selected_signals_per_year": selected_count / len(DEVELOPMENT_YEARS),
        "cap25_signals": len(cap25),
        "cap25_signal_dates": int(cap25.signal_date.nunique()),
        "cap25_signals_per_year": len(cap25) / len(DEVELOPMENT_YEARS),
        "old_f14_selected_signals": int(selected.old_f14_gate.eq(True).sum()),
        "added_old_gap_signals": added_count,
        "added_old_gap_signal_dates": int(added.signal_date.nunique()),
        "by_signal_year": by_year,
        "board_counts": selected.board.value_counts().astype(int).to_dict(),
        "added_board_counts": added.board.value_counts().astype(int).to_dict(),
        "gap_age_counts": selected.gap_age.value_counts().sort_index().astype(int).to_dict(),
        "added_gap_age_counts": added.gap_age.value_counts().sort_index().astype(int).to_dict(),
        "added_days_since_low20_counts": added.days_since_low20.value_counts().sort_index().astype(int).to_dict(),
        "selection_failure_counts": audit.selection_failure_class.value_counts().astype(int).to_dict(),
        "frozen_identity_mismatch_rows": int(
            audit.selection_failure_class.eq("FROZEN_IDENTITY").sum()
        ),
        "selected_parent_low_age_mismatch": int(
            selected.parent_low_age_matches_uniform.eq(False).sum()
        ),
        "concentration": {
            "largest_signal_date_count": int(date_counts.max()),
            "largest_signal_date_share": float(date_counts.max() / selected_count),
            "top5_signal_dates_share": float(
                date_counts.nlargest(5).sum() / selected_count
            ),
            "signal_2018_share": float(signal_year.eq(2018).mean()),
            "cap25_largest_signal_date_count": int(cap25_date_counts.max()),
            "cap25_largest_signal_date_share": float(
                cap25_date_counts.max() / len(cap25)
            ),
            "cap25_top5_signal_dates_share": float(
                cap25_date_counts.nlargest(5).sum() / len(cap25)
            ),
            "cap25_signal_2018_share": float(cap25_year.eq(2018).mean()),
            "added_largest_date_count": int(added_date_counts.max()) if added_count else 0,
            "added_largest_date_share": (
                float(added_date_counts.max() / added_count) if added_count else 0.0
            ),
            "added_top5_dates_share": (
                float(added_date_counts.nlargest(5).sum() / added_count)
                if added_count
                else 0.0
            ),
            "largest_raw_signal_dates": {
                str(pd.Timestamp(index).date()): int(value)
                for index, value in date_counts.nlargest(10).items()
            },
            "largest_cap25_signal_dates": {
                str(pd.Timestamp(index).date()): int(value)
                for index, value in cap25_date_counts.nlargest(10).items()
            },
            "largest_added_signal_dates": {
                str(pd.Timestamp(index).date()): int(value)
                for index, value in added_date_counts.nlargest(10).items()
            },
        },
        "lineage_rows": len(lineage),
        "lineage_missing_snapshot_id": int(
            (~lineage.snapshot_id.map(_nonempty)).sum()
        ),
        "lineage_missing_daily_snapshot_id": int(
            (~lineage.daily_snapshot_id.map(_nonempty)).sum()
        ),
        "lineage_missing_industry_snapshot_id": int(
            (~lineage.industry_snapshot_id.map(_nonempty)).sum()
        ),
        "lineage_missing_trading_state_snapshot_id": int(
            (~lineage.trading_state_snapshot_id.map(_nonempty)).sum()
        ),
        "lineage_missing_corporate_action_snapshot_id": int(
            (~lineage.corporate_action_snapshot_id.map(_nonempty)).sum()
        ),
        "lineage_invalid_hard_valid_rows": int(
            (~lineage.hard_valid.eq(True)).sum()
        ),
        "post_2021_parent_signals": int(
            pd.to_datetime(parent.signal_date).gt(DEVELOPMENT_END).sum()
        ),
        "post_2021_selected_signals": int(
            pd.to_datetime(selected.signal_date).gt(DEVELOPMENT_END).sum()
        ),
        "entry_columns_read": [],
        "outcome_columns_read": [],
        "stage_b_exists": False,
    }


def render_report(
    summary: dict[str, Any],
    source_hashes: dict[str, str],
    path: Path = REPORT,
) -> None:
    lines = [
        f"# {EXPERIMENT} Stage A",
        "",
        "Outcome-blind fixed-signal identity only. No entry, outcome, return, portfolio, or post-2021 row was read.",
        "",
        "Economic rule: keep the frozen V13 prior-high reversal and every V27/V28/V28R1/V28R2 gate; an older gap (15-30 sessions) is fresh again only when its 20-session low occurred within the last three completed sessions.",
        "",
        "|Signal year|Parent|Selected|Dates|Old F14|Added old-gap|Added dates|Cap25|Cap25 dates|",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in DEVELOPMENT_YEARS:
        item = summary["by_signal_year"][str(year)]
        lines.append(
            f"|{year}|{item['parent_signals']}|{item['selected_signals']}|{item['selected_signal_dates']}|{item['old_f14_selected']}|{item['added_old_gap_signals']}|{item['added_old_gap_dates']}|{item['cap25_signals']}|{item['cap25_signal_dates']}|"
        )
    lines += [
        "",
        f"Total selected: {summary['selected_signals']} on {summary['selected_signal_dates']} dates; old-F14 portion {summary['old_f14_selected_signals']}; refreshed older-gap additions {summary['added_old_gap_signals']} on {summary['added_old_gap_signal_dates']} dates.",
        f"Sole primary admission cohort: the preregistered industry-round-robin/rebound-ranked cap25 retained {summary['cap25_signals']} on {summary['cap25_signal_dates']} dates ({summary['cap25_signals_per_year']:.2f}/year). Raw signals are morphology audit only after outcomes open.",
        "",
        f"Concentration: `{json.dumps(summary['concentration'], sort_keys=True)}`.",
        f"Added-source low-age distribution: `{json.dumps(summary['added_days_since_low20_counts'], sort_keys=True)}`.",
        "",
        f"Lineage rows: {summary['lineage_rows']}; missing snapshot/daily/trading/industry/action snapshot: {summary['lineage_missing_snapshot_id']} / {summary['lineage_missing_daily_snapshot_id']} / {summary['lineage_missing_trading_state_snapshot_id']} / {summary['lineage_missing_industry_snapshot_id']} / {summary['lineage_missing_corporate_action_snapshot_id']}.",
        f"Source identities: `{json.dumps(source_hashes, sort_keys=True)}`.",
        "",
        "No Stage B exists in this runner.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_dry_run() -> dict[str, Any]:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    source_hashes = verify_sources(prereg)
    parent = load_parent()
    daily = load_cy033(parent.symbol.astype(str).unique().tolist())
    selected, audit, lineage = build_signal_cohort(parent, daily)
    cap25 = build_cap25_identity(selected)
    summary = summarize(parent, selected, cap25, audit, lineage)
    return {
        "experiment": EXPERIMENT,
        "mode": "READ_ONLY_DEVELOPMENT_SIGNAL_DRY_RUN",
        "preregistration_status": prereg.get("status"),
        "source_hashes": source_hashes,
        "summary": summary,
    }


def run_stage_a() -> dict[str, Any]:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if prereg.get("stage_a_authorized") is not True:
        raise V29R5Error("Stage A is a draft and has not been authorized after review")
    existing = [path for path in (STAGE_A_ROOT, STAGE_A_FREEZE, REPORT) if path.exists()]
    abandoned_staging = (
        sorted(EXT_ROOT.glob(f".{STAGE_A_ROOT.name}.staging-*"))
        if EXT_ROOT.exists()
        else []
    )
    if existing or abandoned_staging:
        raise V29R5Error(
            "refusing Stage-A overwrite or automatic recovery of a partial bundle: "
            + ",".join(str(path) for path in existing + abandoned_staging)
        )
    source_hashes = verify_sources(prereg)
    parent = load_parent()
    daily = load_cy033(parent.symbol.astype(str).unique().tolist())
    selected, audit, lineage = build_signal_cohort(parent, daily)
    cap25 = build_cap25_identity(selected)
    summary = summarize(parent, selected, cap25, audit, lineage)
    governance_failures = {
        key: summary[key]
        for key in (
            "lineage_missing_snapshot_id",
            "lineage_missing_daily_snapshot_id",
            "lineage_missing_trading_state_snapshot_id",
            "lineage_missing_industry_snapshot_id",
            "lineage_missing_corporate_action_snapshot_id",
            "lineage_invalid_hard_valid_rows",
            "frozen_identity_mismatch_rows",
            "post_2021_parent_signals",
            "post_2021_selected_signals",
        )
        if summary[key]
    }
    if governance_failures:
        raise V29R5Error(f"Stage-A governance invariant failed: {governance_failures}")
    EXT_ROOT.mkdir(parents=True, exist_ok=True)
    stage_tmp = EXT_ROOT / f".{STAGE_A_ROOT.name}.staging-{os.getpid()}"
    report_tmp = REPORT.with_name(REPORT.name + f".staging-{os.getpid()}")
    freeze_tmp = STAGE_A_FREEZE.with_name(
        STAGE_A_FREEZE.name + f".staging-{os.getpid()}"
    )
    if stage_tmp.exists() or report_tmp.exists() or freeze_tmp.exists():
        raise V29R5Error("unique Stage-A staging target already exists")
    stage_tmp.mkdir()
    staged_selected = stage_tmp / SELECTED_SIGNALS.name
    staged_cap25 = stage_tmp / CAP25_SIGNALS.name
    staged_audit = stage_tmp / SIGNAL_AUDIT.name
    staged_lineage = stage_tmp / DAILY_LINEAGE.name
    write_parquet(selected, staged_selected)
    write_parquet(cap25, staged_cap25)
    write_parquet(audit, staged_audit)
    write_parquet(lineage, staged_lineage)
    output_hashes = {
        "selected_signals": sha256(staged_selected),
        "cap25_identity": sha256(staged_cap25),
        "signal_audit": sha256(staged_audit),
        "daily_lineage": sha256(staged_lineage),
    }
    render_report(summary, source_hashes, report_tmp)
    output_hashes["report"] = sha256(report_tmp)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DEVELOPMENT_STAGE_A_IDENTITY_FREEZE_BEFORE_ANY_OUTCOME_ACCESS",
        "preregistration_sha256": sha256(PREREG),
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes,
        "output_hashes": output_hashes,
        "summary": summary,
        "entry_rows_opened": "NO",
        "outcomes_opened": "NO",
        "return_fields_read": "NO",
        "post_2021_rows_opened": "NO",
        "stage_b_exists": False,
        "sole_primary_outcome_cohort": "CAP25_INDUSTRY_ROUND_ROBIN_REBOUND_RANKED",
        "raw_signal_outcome_competition_permitted": "NO",
    }
    for path in (
        staged_selected,
        staged_cap25,
        staged_audit,
        staged_lineage,
        report_tmp,
    ):
        os.chmod(path, 0o444)
    os.rename(stage_tmp, STAGE_A_ROOT)
    publish_no_replace(report_tmp, REPORT)
    write_json(freeze_tmp, freeze)
    os.chmod(freeze_tmp, 0o444)
    publish_no_replace(freeze_tmp, STAGE_A_FREEZE)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V29R5Error("Stage-A freeze is missing")
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    if (
        freeze.get("stage")
        != "DEVELOPMENT_STAGE_A_IDENTITY_FREEZE_BEFORE_ANY_OUTCOME_ACCESS"
        or freeze.get("entry_rows_opened") != "NO"
        or freeze.get("outcomes_opened") != "NO"
        or freeze.get("return_fields_read") != "NO"
        or freeze.get("post_2021_rows_opened") != "NO"
        or freeze.get("stage_b_exists") is not False
        or freeze.get("sole_primary_outcome_cohort")
        != "CAP25_INDUSTRY_ROUND_ROBIN_REBOUND_RANKED"
        or freeze.get("raw_signal_outcome_competition_permitted") != "NO"
    ):
        raise V29R5Error("Stage-A freeze governance flags drifted")
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    artifact_paths = {
        "selected_signals": SELECTED_SIGNALS,
        "cap25_identity": CAP25_SIGNALS,
        "signal_audit": SIGNAL_AUDIT,
        "daily_lineage": DAILY_LINEAGE,
        "report": REPORT,
        "freeze": STAGE_A_FREEZE,
    }
    missing = [str(path) for path in artifact_paths.values() if not path.is_file()]
    if missing:
        raise V29R5Error("Stage-A artifact missing: " + ",".join(missing))
    wrong_modes = {
        name: oct(path.stat().st_mode & 0o777)
        for name, path in artifact_paths.items()
        if path.stat().st_mode & 0o777 != 0o444
    }
    if wrong_modes:
        raise V29R5Error(f"Stage-A artifact is not sealed read-only: {wrong_modes}")
    checks = {
        "preregistration_sha256": sha256(PREREG),
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": verify_sources(prereg),
        "output_hashes": {
            "selected_signals": sha256(SELECTED_SIGNALS),
            "cap25_identity": sha256(CAP25_SIGNALS),
            "signal_audit": sha256(SIGNAL_AUDIT),
            "daily_lineage": sha256(DAILY_LINEAGE),
            "report": sha256(REPORT),
        },
    }
    drift = {
        key: [freeze.get(key), value]
        for key, value in checks.items()
        if freeze.get(key) != value
    }
    if drift:
        raise V29R5Error(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "summary": freeze["summary"], "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("dry-run", "stage-a", "verify"), default="dry-run"
    )
    args = parser.parse_args()
    if args.mode == "dry-run":
        result = run_dry_run()
    elif args.mode == "stage-a":
        result = run_stage_a()
    else:
        result = verify_stage_a()
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
