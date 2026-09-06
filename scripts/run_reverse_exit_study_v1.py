#!/usr/bin/env python3
"""Read-only Reverse Exit Study V1 over the frozen 500-symbol V3 bundle.

This script does not rebuild chip state, lifecycle ledgers, or strategy outputs. It
verifies the governed artifact identities, joins the ledger-bound immutable 2020
daily price facts for outcome measurement, and prints deterministic JSON results.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

FROZEN_ROOT = Path(
    "/Users/linmei/Documents/CY/data/validation/v12_v3_500_temporal_20260828"
)
LEDGER_ROOT = Path(
    "/Users/linmei/Documents/CY/data/validation/"
    "v12_lifecycle_entry_exit_ledger_500_20260828"
)
DAILY_ROOT = Path(
    "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/"
    "daily"
)
DAILY_2019 = DAILY_ROOT / "partition_year=2019/data_0.parquet"
DAILY_2020 = DAILY_ROOT / "partition_year=2020/data_0.parquet"
DAILY_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)

EXPECTED_FROZEN_MANIFEST_SHA256 = (
    "915686c6b9a069688e4790a1e6a8e699feafaf951ca7b720c11ca8b21b85c29a"
)
EXPECTED_LEDGER_MANIFEST_SHA256 = (
    "4b4ba0325f41dfcda5f9a7e8e3f259907dbf596f5b2863f622bf2503c7e30254"
)
EXPECTED_DAILY_2020_SHA256 = (
    "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62"
)
EXPECTED_DAILY_2019_SHA256 = (
    "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd"
)
EXPECTED_DAILY_INVENTORY_SHA256 = (
    "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2"
)

SPLITS = {
    "discovery": (pd.Timestamp("2020-01-02"), pd.Timestamp("2020-05-07")),
    "validation": (pd.Timestamp("2020-05-08"), pd.Timestamp("2020-09-01")),
    "holdout": (pd.Timestamp("2020-09-02"), pd.Timestamp("2020-12-31")),
}
HORIZONS = (5, 10, 20, 40, 60)
THRESHOLDS = (0.05, 0.10, 0.15, 0.20)
WARNING_LOOKBACK = 20

SIGNAL_LABELS = {
    "rolling_base_loss": "Rolling-base loss",
    "rolling_base_rebind": "Rolling-base rebinding",
    "peak_mass_drop_25pct": "Tracked-peak mass drop >=25% vs prior 5-session max",
    "prominence_drop_25pct": "Tracked-peak prominence drop >=25% vs prior 5-session max",
    "peak_age_ge_120": "Tracked-peak age >=120 sessions",
    "band_widen_25pct": "Tracked band widens >=25% vs prior 5-session median",
    "concentration_drop_10pp": "Concentration_20 drops >=0.10 vs prior 5-session max",
    "profit_saturation_reversal": "Profit ratio reverses from >=0.90 to <=0.75",
    "seller_disagreement_10pct": "Seller-model price spread >=10% of average cost",
    "split": "Temporal split event",
    "merge": "Temporal merge event",
    "lost": "Temporal lost event",
    "cost_migration_reversal": "Average-cost migration reverses +3% then -3%",
    "distribution_evidence": "Price/profit/cost distribution composite",
    "volume_turnover_distribution": "Negative return with volume and turnover surge",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_sources() -> dict[str, Any]:
    frozen_manifest = FROZEN_ROOT / "manifest.json"
    ledger_manifest = LEDGER_ROOT / "manifest.json"
    actual = {
        "frozen_root_manifest_sha256": _sha256(frozen_manifest),
        "ledger_manifest_sha256": _sha256(ledger_manifest),
        "daily_inventory_sha256": _sha256(DAILY_INVENTORY),
        "daily_2019_sha256": _sha256(DAILY_2019),
        "daily_2020_sha256": _sha256(DAILY_2020),
    }
    expected = {
        "frozen_root_manifest_sha256": EXPECTED_FROZEN_MANIFEST_SHA256,
        "ledger_manifest_sha256": EXPECTED_LEDGER_MANIFEST_SHA256,
        "daily_inventory_sha256": EXPECTED_DAILY_INVENTORY_SHA256,
        "daily_2019_sha256": EXPECTED_DAILY_2019_SHA256,
        "daily_2020_sha256": EXPECTED_DAILY_2020_SHA256,
    }
    if actual != expected:
        raise ValueError(f"governed source identity mismatch: {actual!r}")

    manifest = json.loads(ledger_manifest.read_text())
    registered_daily = manifest["panel_metadata"]["registered_inventories"]["CY-006"]
    if registered_daily["sha256"] != actual["daily_inventory_sha256"]:
        raise ValueError("daily outcome inventory is not the ledger-bound CY-006 input")
    inventory = json.loads(DAILY_INVENTORY.read_text())
    inventory_files = {item["path"]: item["sha256"] for item in inventory["files"]}
    if inventory_files.get("partition_year=2019/data_0.parquet") != actual[
        "daily_2019_sha256"
    ]:
        raise ValueError("2019 causal warmup price file is not inventory-bound")
    if inventory_files.get("partition_year=2020/data_0.parquet") != actual[
        "daily_2020_sha256"
    ]:
        raise ValueError("2020 outcome price file is not inventory-bound")
    artifacts: dict[str, Any] = {}
    for name, metadata in manifest["artifacts"].items():
        path = LEDGER_ROOT / name
        digest = _sha256(path)
        if digest != metadata["sha256"]:
            raise ValueError(f"authoritative ledger artifact mismatch: {name}")
        artifacts[name] = {"rows": metadata["rows"], "sha256": digest}
    if not manifest["freeze_verification"]["unchanged"]:
        raise ValueError("authoritative ledger does not attest frozen-root immutability")
    return {
        **actual,
        "frozen_tree_sha256": manifest["freeze_verification"]["after"]["tree_sha256"],
        "frozen_tree_files": manifest["freeze_verification"]["after"]["files"],
        "frozen_tree_bytes": manifest["freeze_verification"]["after"]["bytes"],
        "ledger_artifacts": artifacts,
    }


def _load_panel() -> tuple[pd.DataFrame, dict[str, Any]]:
    feature_glob = str(FROZEN_ROOT / "symbol=*/daily_feature_candidate.parquet")
    con = duckdb.connect()
    frame = con.execute(
        """
        SELECT
            f.*,
            d.decision_at AS price_decision_at,
            d.available_at AS price_available_at,
            d.daily_snapshot_id,
            d.trading_state_snapshot_id,
            d.corporate_action_snapshot_id,
            d.open,
            d.high,
            d.low,
            d.close,
            d.preclose,
            d.volume,
            d.turnover_fraction,
            d.trade_status,
            d.bar_valid,
            d.trading_state_valid,
            d.corporate_action_valid,
            d.historical_identity_valid,
            d.float_valid,
            d.current_day_data_tradable,
            d.corporate_action_count,
            d.corporate_action_blocking
        FROM read_parquet(?, hive_partitioning=false) f
        JOIN read_parquet(?) d USING (symbol, trade_date)
        ORDER BY f.symbol, f.trade_date
        """,
        [feature_glob, str(DAILY_2020)],
    ).fetchdf()
    price_history = con.execute(
        """
        WITH selected AS (
            SELECT DISTINCT symbol
            FROM read_parquet(?, hive_partitioning=false)
        )
        SELECT
            d.symbol,
            d.trade_date,
            d.close,
            d.volume,
            d.turnover_fraction,
            d.bar_valid,
            d.trading_state_valid,
            d.corporate_action_valid,
            d.historical_identity_valid,
            d.daily_snapshot_id,
            d.trading_state_snapshot_id,
            d.corporate_action_snapshot_id,
            d.corporate_action_count,
            d.corporate_action_blocking
        FROM read_parquet(?) d
        JOIN selected s USING (symbol)
        ORDER BY d.symbol, d.trade_date
        """,
        [feature_glob, [str(DAILY_2019), str(DAILY_2020)]],
    ).fetchdf()
    counts = con.execute(
        """
        SELECT
            count(*) AS rows,
            count(DISTINCT f.symbol) AS symbols,
            min(f.trade_date) AS start_date,
            max(f.trade_date) AS end_date,
            sum(f.research_valid::INTEGER) AS research_valid_rows,
            sum(f.hard_valid::INTEGER) AS hard_valid_rows,
            sum((f.available_at <= timezone('Asia/Shanghai',
                f.trade_date::TIMESTAMP + INTERVAL '15 hours 30 minutes'))::INTEGER)
                AS feature_pit_rows,
            sum((d.available_at <= d.decision_at)::INTEGER) AS price_pit_rows,
            count(*) - count(DISTINCT f.symbol || '|' || f.trade_date::VARCHAR)
                AS duplicate_keys,
            count(*) FILTER (
                WHERE f.snapshot_id IS NULL OR f.snapshot_id = ''
                   OR d.daily_snapshot_id IS NULL OR d.daily_snapshot_id = ''
                   OR d.trading_state_snapshot_id IS NULL
                   OR d.trading_state_snapshot_id = ''
                   OR d.corporate_action_snapshot_id IS NULL
                   OR d.corporate_action_snapshot_id = ''
            ) AS missing_required_snapshot_rows
        FROM read_parquet(?, hive_partitioning=false) f
        JOIN read_parquet(?) d USING (symbol, trade_date)
        """,
        [feature_glob, str(DAILY_2020)],
    ).fetchone()
    con.close()
    audit = dict(
        zip(
            (
                "rows",
                "symbols",
                "start_date",
                "end_date",
                "research_valid_rows",
                "hard_valid_rows",
                "feature_pit_rows",
                "price_pit_rows",
                "duplicate_keys",
                "missing_required_snapshot_rows",
            ),
            counts,
            strict=True,
        )
    )
    if audit["rows"] != 121_251 or audit["symbols"] != 500:
        raise ValueError(f"unexpected frozen panel scope: {audit!r}")
    if audit["feature_pit_rows"] != audit["rows"] or audit["price_pit_rows"] != audit["rows"]:
        raise ValueError("PIT availability audit failed")
    if audit["duplicate_keys"] or audit["missing_required_snapshot_rows"]:
        raise ValueError(f"lineage/key audit failed: {audit!r}")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    price_history["trade_date"] = pd.to_datetime(price_history["trade_date"])
    required_text = (
        price_history["daily_snapshot_id"].notna()
        & price_history["trading_state_snapshot_id"].notna()
        & price_history["corporate_action_snapshot_id"].notna()
    )
    price_history["warm_price_lineage_valid"] = (
        price_history["bar_valid"].fillna(False)
        & price_history["trading_state_valid"].fillna(False)
        & price_history["corporate_action_valid"].fillna(False)
        & price_history["historical_identity_valid"].fillna(False)
        & required_text
        & np.isfinite(price_history["close"])
        & price_history["close"].gt(0)
        & price_history["corporate_action_count"].fillna(0).eq(0)
        & ~price_history["corporate_action_blocking"].fillna(True)
    )
    history_grouped = price_history.groupby("symbol", sort=False)
    price_history["warm_ret_1"] = history_grouped["close"].pct_change(
        fill_method=None
    )
    price_history["warm_ret_20"] = history_grouped["close"].pct_change(
        20, fill_method=None
    )
    price_history["warm_ma_60"] = history_grouped["close"].transform(
        lambda values: values.rolling(60, min_periods=60).mean()
    )
    price_history["warm_high_20"] = history_grouped["close"].transform(
        lambda values: values.rolling(20, min_periods=20).max()
    )
    price_history["warm_past_60_price_valid"] = history_grouped[
        "warm_price_lineage_valid"
    ].transform(
        lambda values: values.astype(int).rolling(60, min_periods=60).sum().eq(60)
    )
    price_history["warm_previous_volume_median"] = history_grouped["volume"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=10).median()
    )
    price_history["warm_previous_turnover_median"] = history_grouped[
        "turnover_fraction"
    ].transform(lambda values: values.shift(1).rolling(20, min_periods=10).median())
    warm_columns = [
        "symbol",
        "trade_date",
        "warm_ret_1",
        "warm_ret_20",
        "warm_ma_60",
        "warm_high_20",
        "warm_past_60_price_valid",
        "warm_previous_volume_median",
        "warm_previous_turnover_median",
    ]
    frame = frame.merge(
        price_history.loc[price_history["trade_date"].dt.year.eq(2020), warm_columns],
        on=["symbol", "trade_date"],
        how="left",
        validate="one_to_one",
    )
    return frame, audit


def _group_transform(
    frame: pd.DataFrame,
    column: str,
    function: Any,
) -> pd.Series:
    return frame.groupby("symbol", sort=False)[column].transform(function)


def _prepare_features(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for name, (start, end) in SPLITS.items():
        frame.loc[frame["trade_date"].between(start, end), "split_name"] = name
    if frame["split_name"].isna().any():
        raise ValueError("a row is outside the locked chronological splits")

    required_text = (
        frame["daily_snapshot_id"].notna()
        & frame["trading_state_snapshot_id"].notna()
        & frame["corporate_action_snapshot_id"].notna()
    )
    frame["price_lineage_valid"] = (
        frame["bar_valid"].fillna(False)
        & frame["trading_state_valid"].fillna(False)
        & frame["corporate_action_valid"].fillna(False)
        & frame["historical_identity_valid"].fillna(False)
        & required_text
        & np.isfinite(frame["close"])
        & frame["close"].gt(0)
        & frame["corporate_action_count"].fillna(0).eq(0)
        & ~frame["corporate_action_blocking"].fillna(True)
    )

    grouped = frame.groupby("symbol", sort=False)
    frame["symbol_row"] = grouped.cumcount()
    frame["ret_1"] = frame["warm_ret_1"]
    frame["ret_20"] = frame["warm_ret_20"]
    frame["ma_60"] = frame["warm_ma_60"]
    frame["high_20"] = frame["warm_high_20"]
    frame["past_60_price_valid"] = frame["warm_past_60_price_valid"]
    frame["uptrend"] = (
        frame["research_valid"].fillna(False)
        & frame["past_60_price_valid"]
        & frame["close"].gt(frame["ma_60"])
        & frame["ret_20"].ge(0.10)
        & frame["close"].ge(0.90 * frame["high_20"])
    )

    previous_track = grouped["peak_track_id"].shift(1)
    track_5 = grouped["peak_track_id"].shift(5)
    frame["rolling_base_loss"] = previous_track.notna() & frame["peak_track_id"].isna()
    frame["rolling_base_rebind"] = (
        frame["symbol_row"].gt(0)
        & previous_track.isna()
        & frame["peak_track_id"].notna()
    )

    prior_mass_max = _group_transform(
        frame,
        "peak_track_mass",
        lambda values: values.shift(1).rolling(5, min_periods=3).max(),
    )
    prior_prominence_max = _group_transform(
        frame,
        "peak_track_prominence",
        lambda values: values.shift(1).rolling(5, min_periods=3).max(),
    )
    same_track_5 = frame["peak_track_id"].notna() & frame["peak_track_id"].eq(track_5)
    frame["peak_mass_drop_25pct"] = (
        same_track_5
        & prior_mass_max.gt(0)
        & frame["peak_track_mass"].le(0.75 * prior_mass_max)
    )
    frame["prominence_drop_25pct"] = (
        same_track_5
        & prior_prominence_max.gt(0)
        & frame["peak_track_prominence"].le(0.75 * prior_prominence_max)
    )
    frame["peak_age_ge_120"] = frame["peak_track_age"].ge(120)

    frame["track_band_width"] = (
        frame["peak_track_band_upper"] - frame["peak_track_band_lower"]
    ) / frame["tracked_base_peak"]
    prior_band_median = _group_transform(
        frame,
        "track_band_width",
        lambda values: values.shift(1).rolling(5, min_periods=3).median(),
    )
    frame["band_widen_25pct"] = (
        same_track_5
        & prior_band_median.gt(0)
        & frame["track_band_width"].ge(1.25 * prior_band_median)
    )

    prior_concentration_max = _group_transform(
        frame,
        "concentration_20",
        lambda values: values.shift(1).rolling(5, min_periods=3).max(),
    )
    frame["concentration_drop_10pp"] = frame["concentration_20"].le(
        prior_concentration_max - 0.10
    )
    prior_profit_max = _group_transform(
        frame,
        "profit_ratio",
        lambda values: values.shift(1).rolling(5, min_periods=3).max(),
    )
    frame["profit_saturation_reversal"] = prior_profit_max.ge(0.90) & frame[
        "profit_ratio"
    ].le(0.75)

    max_spread = frame[
        [
            "model_spread_cost_p50",
            "model_spread_cost_p90",
            "model_spread_dominant_peak_today",
        ]
    ].max(axis=1)
    frame["seller_disagreement_10pct"] = (
        frame["average_cost"].gt(0) & max_spread.div(frame["average_cost"]).ge(0.10)
    )
    frame["split"] = frame["peak_track_split"].fillna(False)
    frame["merge"] = frame["peak_track_merge"].fillna(False)
    frame["lost"] = frame["peak_track_lost"].fillna(False)

    average_cost_5 = grouped["average_cost"].shift(5)
    average_cost_20 = grouped["average_cost"].shift(20)
    frame["cost_migration_reversal"] = (
        average_cost_20.gt(0)
        & average_cost_5.div(average_cost_20).ge(1.03)
        & frame["average_cost"].div(average_cost_5).le(0.97)
    )
    frame["distribution_evidence"] = (
        frame["ret_1"].le(-0.02)
        & prior_profit_max.sub(frame["profit_ratio"]).ge(0.15)
        & frame["average_cost"].lt(average_cost_5)
    )

    previous_volume_median = frame["warm_previous_volume_median"]
    previous_turnover_median = frame["warm_previous_turnover_median"]
    frame["volume_turnover_distribution"] = (
        frame["float_valid"].fillna(False)
        & frame["ret_1"].le(-0.02)
        & previous_volume_median.gt(0)
        & previous_turnover_median.gt(0)
        & frame["volume"].div(previous_volume_median).ge(1.50)
        & frame["turnover_fraction"].div(previous_turnover_median).ge(1.50)
    )

    for signal in SIGNAL_LABELS:
        frame[signal] = frame[signal].fillna(False).astype(bool)
        previous = frame.groupby("symbol", sort=False)[signal].shift(1).fillna(False)
        frame[f"{signal}__onset"] = frame[signal] & ~previous
    return frame


def _add_future_labels(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for horizon in HORIZONS:
        frame[f"label_valid_{horizon}"] = False
        frame[f"future_min_return_{horizon}"] = np.nan
        frame[f"local_high_drawdown_{horizon}"] = np.nan
        frame[f"support_failure_{horizon}"] = np.nan
        for threshold in THRESHOLDS:
            suffix = round(threshold * 100)
            frame[f"lead_down_{suffix}_{horizon}"] = np.nan
            frame[f"lead_up_{suffix}_{horizon}"] = np.nan

    for (_, _), group in frame.groupby(["symbol", "split_name"], sort=False):
        positions = group.index.to_numpy()
        closes = group["close"].to_numpy(float)
        valid = group["price_lineage_valid"].to_numpy(bool)
        uptrend = group["uptrend"].to_numpy(bool)
        supports = group["peak_track_band_lower"].to_numpy(float)
        local_highs = group["high_20"].to_numpy(float)
        size = len(group)
        for local_index in np.flatnonzero(uptrend):
            current_close = closes[local_index]
            for horizon in HORIZONS:
                stop = local_index + horizon + 1
                if stop > size:
                    continue
                future_close = closes[local_index + 1 : stop]
                future_valid = valid[local_index + 1 : stop]
                if not valid[local_index] or not future_valid.all():
                    continue
                row_index = positions[local_index]
                returns = future_close / current_close - 1.0
                frame.at[row_index, f"label_valid_{horizon}"] = True
                frame.at[row_index, f"future_min_return_{horizon}"] = float(returns.min())
                frame.at[row_index, f"local_high_drawdown_{horizon}"] = float(
                    (future_close / local_highs[local_index] - 1.0).min()
                )
                support = supports[local_index]
                if np.isfinite(support) and support > 0:
                    frame.at[row_index, f"support_failure_{horizon}"] = float(
                        (future_close < support).any()
                    )
                for threshold in THRESHOLDS:
                    suffix = round(threshold * 100)
                    down = np.flatnonzero(returns <= -threshold)
                    up = np.flatnonzero(returns >= threshold)
                    if len(down):
                        frame.at[row_index, f"lead_down_{suffix}_{horizon}"] = int(
                            down[0] + 1
                        )
                    if len(up):
                        frame.at[row_index, f"lead_up_{suffix}_{horizon}"] = int(
                            up[0] + 1
                        )
    return frame


def _outcome_summary(frame: pd.DataFrame) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for split_name in SPLITS:
        split = frame.loc[frame["split_name"].eq(split_name)]
        for horizon in HORIZONS:
            eligible = split.loc[split[f"label_valid_{horizon}"] & split["uptrend"]]
            for threshold in THRESHOLDS:
                positives = eligible[f"future_min_return_{horizon}"].le(-threshold)
                results.append(
                    {
                        "split": split_name,
                        "outcome": f"current_close_drawdown_{int(threshold * 100)}pct",
                        "horizon": horizon,
                        "eligible": len(eligible),
                        "positives": int(positives.sum()),
                        "rate": _ratio(int(positives.sum()), len(eligible)),
                    }
                )
            support = eligible.loc[eligible[f"support_failure_{horizon}"].notna()]
            support_positives = support[f"support_failure_{horizon}"].astype(bool)
            results.append(
                {
                    "split": split_name,
                    "outcome": "current_rolling_base_support_failure",
                    "horizon": horizon,
                    "eligible": len(support),
                    "positives": int(support_positives.sum()),
                    "rate": _ratio(int(support_positives.sum()), len(support)),
                }
            )
            for threshold in (0.10, 0.15):
                positives = eligible[f"local_high_drawdown_{horizon}"].le(-threshold)
                results.append(
                    {
                        "split": split_name,
                        "outcome": f"local_20d_high_drawdown_{int(threshold * 100)}pct",
                        "horizon": horizon,
                        "eligible": len(eligible),
                        "positives": int(positives.sum()),
                        "rate": _ratio(int(positives.sum()), len(eligible)),
                    }
                )
    return results


def _material_onsets(frame: pd.DataFrame) -> pd.Series:
    """Return 10% local-high drawdown episode starts with a 5% recovery reset."""

    onsets = pd.Series(False, index=frame.index, dtype=bool)
    for _, group in frame.groupby("symbol", sort=False):
        active = False
        for row in group.itertuples():
            if not row.price_lineage_valid or not np.isfinite(row.high_20) or row.high_20 <= 0:
                continue
            drawdown = row.close / row.high_20 - 1.0
            if not active and drawdown <= -0.10:
                onsets.at[row.Index] = True
                active = True
            elif active and drawdown >= -0.05:
                active = False
    return onsets


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _finite_median(values: list[int]) -> float | None:
    return None if not values else float(np.median(values))


def _signal_summary(frame: pd.DataFrame) -> list[dict[str, Any]]:
    frame = frame.copy()
    frame["material_onset"] = _material_onsets(frame)
    results: list[dict[str, Any]] = []

    for split_name in SPLITS:
        split = frame.loc[frame["split_name"].eq(split_name)]
        baseline = split.loc[split["uptrend"] & split["label_valid_20"]]
        baseline_positive = baseline["future_min_return_20"].le(-0.10)
        baseline_rate = _ratio(int(baseline_positive.sum()), len(baseline))

        outcome_count = 0
        coverage_by_signal = {name: 0 for name in SIGNAL_LABELS}
        leads_by_signal: dict[str, list[int]] = {name: [] for name in SIGNAL_LABELS}
        for _, group in split.groupby("symbol", sort=False):
            group = group.reset_index(drop=False)
            outcome_positions = np.flatnonzero(group["material_onset"].to_numpy(bool))
            uptrend = group["uptrend"].to_numpy(bool)
            for outcome_position in outcome_positions:
                start = max(0, outcome_position - WARNING_LOOKBACK)
                if outcome_position - start < WARNING_LOOKBACK:
                    continue
                if not uptrend[start:outcome_position].any():
                    continue
                outcome_count += 1
                for signal in SIGNAL_LABELS:
                    warning = (
                        group[f"{signal}__onset"].to_numpy(bool)
                        & uptrend
                    )
                    prior = np.flatnonzero(warning[start:outcome_position])
                    if not len(prior):
                        continue
                    nearest = start + int(prior[-1])
                    coverage_by_signal[signal] += 1
                    leads_by_signal[signal].append(outcome_position - nearest)

        for signal, label in SIGNAL_LABELS.items():
            warning_rows = split.loc[
                split[f"{signal}__onset"] & split["uptrend"]
            ]
            eligible_warning = warning_rows.loc[warning_rows["label_valid_20"]]
            drawdowns = eligible_warning["future_min_return_20"].le(-0.10)
            warning_rate = _ratio(int(drawdowns.sum()), len(eligible_warning))
            false_warning_rate = (
                None if warning_rate is None else 1.0 - warning_rate
            )
            down_lead = eligible_warning["lead_down_10_20"]
            up_lead = eligible_warning["lead_up_10_20"]
            profitable_first = up_lead.notna() & (
                down_lead.isna() | up_lead.lt(down_lead)
            )
            lift = (
                None
                if warning_rate is None or baseline_rate in (None, 0.0)
                else warning_rate / baseline_rate
            )
            results.append(
                {
                    "split": split_name,
                    "signal": signal,
                    "label": label,
                    "warning_onsets": len(warning_rows),
                    "eligible_warning_onsets": len(eligible_warning),
                    "median_warning_lead": _finite_median(leads_by_signal[signal]),
                    "drawdown_onsets": int(outcome_count),
                    "covered_drawdown_onsets": int(coverage_by_signal[signal]),
                    "drawdown_coverage": _ratio(
                        coverage_by_signal[signal], outcome_count
                    ),
                    "false_warning_rate": false_warning_rate,
                    "warning_drawdown_rate": warning_rate,
                    "baseline_drawdown_rate": baseline_rate,
                    "drawdown_risk_lift": lift,
                    "profitable_trend_premature_exit_rate": _ratio(
                        int(profitable_first.sum()), len(eligible_warning)
                    ),
                    "production_exit_reason_relationship": (
                        "NOT_ESTIMABLE_ZERO_AUTHORITATIVE_EXITS"
                    ),
                }
            )
    return results


def _ledger_summary() -> dict[str, Any]:
    con = duckdb.connect()
    lifecycle = str(LEDGER_ROOT / "lifecycle_events.parquet")
    execution = str(LEDGER_ROOT / "execution_events.parquet")
    summary = str(LEDGER_ROOT / "lifecycle_summary.parquet")
    event_counts = dict(
        con.execute(
            "SELECT event_type, count(*) FROM read_parquet(?) GROUP BY 1 ORDER BY 1",
            [lifecycle],
        ).fetchall()
    )
    execution_counts = dict(
        con.execute(
            "SELECT event_type, count(*) FROM read_parquet(?) GROUP BY 1 ORDER BY 1",
            [execution],
        ).fetchall()
    )
    phase_counts = dict(
        con.execute(
            "SELECT phase, count(*) FROM read_parquet(?) GROUP BY 1 ORDER BY 1",
            [lifecycle],
        ).fetchall()
    )
    lifecycle_rows = con.execute(
        "SELECT count(*) FROM read_parquet(?)", [summary]
    ).fetchone()[0]
    pit_failures = con.execute(
        """
        SELECT count(*)
        FROM read_parquet(?)
        WHERE CAST(available_at AS TIMESTAMPTZ) > CAST(decision_at AS TIMESTAMPTZ)
        """,
        [lifecycle],
    ).fetchone()[0]
    con.close()
    return {
        "event_counts": event_counts,
        "phase_counts": phase_counts,
        "execution_event_counts": execution_counts,
        "lifecycle_summary_rows": int(lifecycle_rows),
        "lifecycle_pit_failures": int(pit_failures),
        "production_entries": 0,
        "production_open_holdings": 0,
        "exit_conditions": 0,
        "exit_intents": 0,
        "exit_execution_attempts": 0,
        "blocked_or_deferred_exits": 0,
        "exit_fills": 0,
    }


def _coverage_summary(frame: pd.DataFrame) -> dict[str, Any]:
    split_rows: dict[str, Any] = {}
    for split_name in SPLITS:
        split = frame.loc[frame["split_name"].eq(split_name)]
        split_rows[split_name] = {
            "rows": len(split),
            "research_valid_rows": int(split["research_valid"].sum()),
            "price_lineage_valid_rows": int(split["price_lineage_valid"].sum()),
            "uptrend_rows": int(split["uptrend"].sum()),
            "tracked_uptrend_rows": int(
                (split["uptrend"] & split["peak_track_id"].notna()).sum()
            ),
            "first_date": split["trade_date"].min().date().isoformat(),
            "last_date": split["trade_date"].max().date().isoformat(),
        }
    return {
        "rows": len(frame),
        "symbols": int(frame["symbol"].nunique()),
        "research_valid_rows": int(frame["research_valid"].sum()),
        "price_lineage_valid_rows": int(frame["price_lineage_valid"].sum()),
        "uptrend_rows": int(frame["uptrend"].sum()),
        "tracked_rows": int(frame["peak_track_id"].notna().sum()),
        "tracked_uptrend_rows": int(
            (frame["uptrend"] & frame["peak_track_id"].notna()).sum()
        ),
        "splits": split_rows,
    }


def main() -> None:
    sources = _verify_sources()
    frame, panel_audit = _load_panel()
    frame = _prepare_features(frame)
    frame = _add_future_labels(frame)
    result = {
        "study": "REVERSE_EXIT_STUDY_V1",
        "protocol": {
            "splits": {
                name: {
                    "start": start.date().isoformat(),
                    "end": end.date().isoformat(),
                    "sessions": 81,
                }
                for name, (start, end) in SPLITS.items()
            },
            "horizons": HORIZONS,
            "drawdown_thresholds": THRESHOLDS,
            "warning_lookback_sessions": WARNING_LOOKBACK,
            "signal_definitions": SIGNAL_LABELS,
            "future_starts_at": "T_PLUS_1",
            "labels_cross_split_boundaries": False,
            "corporate_action_windows_excluded": True,
        },
        "sources": sources,
        "panel_audit": panel_audit,
        "ledger": _ledger_summary(),
        "coverage": _coverage_summary(frame),
        "outcomes": _outcome_summary(frame),
        "signals": _signal_summary(frame),
    }
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
