#!/usr/bin/env python3
"""Execute preregistered CHINEXT V1 winner/loser pre-entry archaeology."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
if str(WORK / "scripts") not in sys.path:
    sys.path.insert(0, str(WORK / "scripts"))

import run_phase2_feature_library as phase2  # noqa: E402

SPEC = WORK / "experiments/EXP-WLA-001_spec.json"
YEARLY_TRADES = WORK / "artifacts/yearly_trades.csv"
PHASE5_TRADES = WORK / "artifacts/trade_mechanism_attribution.csv"
DAILY_REGIME = WORK / "artifacts/daily_regime_features.parquet"
OUTPUT_TRAJECTORIES = WORK / "artifacts/pre_entry_trajectories.csv"
OUTPUT_TRANSITIONS = WORK / "artifacts/pre_entry_transitions.csv"
OUTPUT_GROUPS = WORK / "artifacts/pre_entry_group_trajectories.csv"
OUTPUT_JSON = WORK / "artifacts/winner_loser_trajectory_archaeology.json"
REPORT = WORK / "reports/winner_loser_trajectory_archaeology.md"

ANCHORS = (60, 40, 20, 10, 5, 3, 1)
TRAJECTORY_FEATURES = (
    "relative_strength20",
    "realized_vol20",
    "range_width20",
    "downside_amount_share20",
    "higher_low10",
    "lower_high10",
    "distance_to_prior_high20",
    "amount_ratio5_to_prior15",
)
PRIMARY_TRANSITIONS = (
    "rs_improvement",
    "volatility_compression",
    "range_compression",
    "downside_amount_contraction",
)
SUPPLY_TRANSITIONS = {
    "volatility_compression",
    "range_compression",
    "downside_amount_contraction",
}
CONTROL_COLUMNS = (
    "entry_rs_score",
    "entry_mom20",
    "entry_box_width",
    "entry_minvol_location",
    "entry_breakout_volume_ratio",
    "index_return_20d",
    "index_realized_vol20",
    "breadth_composite",
    "entry_beta60",
    "entry_log_amount20",
)
SECONDARY_ENDPOINTS = (
    "winner20",
    "false_breakout",
    "severe_loss",
    "mfe",
    "round_trip_return",
)


class ArchaeologyError(RuntimeError):
    """Raised when an identity, PIT, sample, or analysis invariant fails."""


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


def finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return finite_or_none(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_spec_and_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-WLA-001":
        raise ArchaeologyError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_TRAJECTORY_OUTCOME_JOIN":
        raise ArchaeologyError("experiment is not frozen before trajectory results")
    if spec.get("evidence_grade") != "EXPLORATORY_MECHANISM_EVIDENCE":
        raise ArchaeologyError("experiment evidence grade changed")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for name, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise ArchaeologyError(f"bound input missing: {name}: {path}")
        actual = sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[name] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise ArchaeologyError(f"frozen input mismatch: {mismatches}")
    phase2.validate_inputs()
    return spec, identities


def classify_outcome(value: float) -> str:
    if value >= 0.50:
        return "extreme_winner"
    if value >= 0.20:
        return "strong_winner"
    if value > 0.0:
        return "ordinary_winner"
    if value <= -0.10:
        return "severe_loser"
    return "ordinary_loser"


def load_trade_frame() -> pd.DataFrame:
    trades = pd.read_csv(YEARLY_TRADES)
    if len(trades) != 399 or trades.trade_id.nunique() != 399:
        raise ArchaeologyError("yearly trade input is not 399 unique cycles")
    for column in (
        "entry_signal_date",
        "entry_execution_date",
        "exit_signal_date",
        "exit_execution_date",
    ):
        trades[column] = pd.to_datetime(trades[column], errors="raise")
    if not (trades.entry_signal_date < trades.entry_execution_date).all():
        raise ArchaeologyError("entry signal/execution order is not causal")
    if not (trades.exit_signal_date <= trades.exit_execution_date).all():
        raise ArchaeologyError("exit signal/execution order is invalid")
    required = [
        "round_trip_return",
        "realized_pnl",
        "mfe",
        "holding_trading_days",
        *CONTROL_COLUMNS[:5],
    ]
    if trades[required].replace([np.inf, -np.inf], np.nan).isna().any().any():
        raise ArchaeologyError("required frozen trade values are missing")

    phase5 = pd.read_csv(PHASE5_TRADES, usecols=["trade_id", "breadth_composite"])
    if len(phase5) != 399 or phase5.trade_id.nunique() != 399:
        raise ArchaeologyError("Phase 5 mechanism table is not 399 unique cycles")
    trades = trades.merge(phase5, on="trade_id", how="left", validate="one_to_one")

    daily = pd.read_parquet(
        DAILY_REGIME,
        columns=[
            "baseline_block",
            "trade_date",
            "feature_available_at",
            "first_applicable_trade_date",
            "index_return_20d",
            "index_realized_vol20",
        ],
    )
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    daily["feature_available_at"] = pd.to_datetime(daily.feature_available_at)
    daily["first_applicable_trade_date"] = pd.to_datetime(daily.first_applicable_trade_date)
    trades = trades.merge(
        daily,
        left_on=["baseline_block", "entry_signal_date"],
        right_on=["baseline_block", "trade_date"],
        how="left",
        validate="many_to_one",
    )
    if trades.trade_date.isna().any():
        raise ArchaeologyError("entry signal did not join the frozen daily regime library")
    causal = (
        (trades.feature_available_at.dt.date == trades.entry_signal_date.dt.date)
        & (trades.first_applicable_trade_date > trades.entry_signal_date)
        & (trades.first_applicable_trade_date <= trades.entry_execution_date)
    )
    if not causal.all():
        raise ArchaeologyError("entry regime control has invalid applicability")

    trades["entry_year"] = trades.entry_signal_date.dt.year
    trades["winner20"] = trades.round_trip_return >= 0.20
    trades["extreme_winner"] = trades.round_trip_return >= 0.50
    trades["false_breakout"] = (trades.mfe < 0.10) & (trades.round_trip_return <= 0.0)
    trades["severe_loss"] = trades.round_trip_return <= -0.10
    trades["outcome_class"] = trades.round_trip_return.map(classify_outcome)
    expected_counts = {
        "extreme_winner": 15,
        "strong_winner": 24,
        "ordinary_winner": 122,
        "ordinary_loser": 194,
        "severe_loser": 44,
    }
    if trades.outcome_class.value_counts().to_dict() != expected_counts:
        raise ArchaeologyError("fixed outcome-group counts changed")
    if int(trades.false_breakout.sum()) != 213:
        raise ArchaeologyError("fixed false-breakout count changed")
    return trades


def load_index_close(calendar: pd.DataFrame) -> dict[int, float]:
    index = pd.read_csv(phase2.ANCHOR, dtype={"trade_date": str})
    index["trade_date"] = pd.to_datetime(index.trade_date, format="%Y%m%d")
    index["close"] = pd.to_numeric(index.close, errors="raise")
    merged = calendar.merge(index[["trade_date", "close"]], on="trade_date", how="left")
    if merged.close.isna().any() or (merged.close <= 0).any():
        raise ArchaeologyError("399102 close is missing or invalid on the experiment calendar")
    return dict(zip(merged.cal_idx.astype(int), merged.close.astype(float), strict=True))


def feature_window(
    rows: pd.DataFrame,
    index_close: dict[int, float],
    anchor_idx: int,
) -> dict[str, float]:
    window = rows[(rows.cal_idx >= anchor_idx - 20) & (rows.cal_idx <= anchor_idx)].copy()
    expected = list(range(anchor_idx - 20, anchor_idx + 1))
    if window.cal_idx.astype(int).tolist() != expected:
        raise ArchaeologyError(f"noncontiguous 21-row window ending at {anchor_idx}")
    if not window.critical_valid.astype(bool).all():
        raise ArchaeologyError(f"hard-invalid row in window ending at {anchor_idx}")
    steps = window[window.cal_idx > anchor_idx - 20].copy()
    if len(steps) != 20 or not steps.coordinate_step_valid.astype(bool).all():
        raise ArchaeologyError(f"invalid corporate-action coordinate ending at {anchor_idx}")
    step_returns = steps.step_log_return.to_numpy(float)
    if not np.isfinite(step_returns).all():
        raise ArchaeologyError(f"nonfinite stock return ending at {anchor_idx}")
    if anchor_idx not in index_close or anchor_idx - 20 not in index_close:
        raise ArchaeologyError(f"missing index return window ending at {anchor_idx}")
    index_return = math.log(index_close[anchor_idx] / index_close[anchor_idx - 20])

    bars = window[window.cal_idx >= anchor_idx - 19].copy()
    prior10 = bars[bars.cal_idx <= anchor_idx - 10]
    last10 = bars[bars.cal_idx >= anchor_idx - 9]
    prior15 = bars[bars.cal_idx <= anchor_idx - 5]
    last5 = bars[bars.cal_idx >= anchor_idx - 4]
    current = window[window.cal_idx == anchor_idx].iloc[0]
    prior_high = window[window.cal_idx < anchor_idx].adjusted_high.max()
    amount_total = float(bars.amount.sum())
    if len(bars) != 20 or len(prior10) != 10 or len(last10) != 10:
        raise ArchaeologyError(f"unexpected subwindow size ending at {anchor_idx}")
    if amount_total <= 0 or float(prior15.amount.mean()) <= 0:
        raise ArchaeologyError(f"invalid traded amount ending at {anchor_idx}")
    metrics = {
        "relative_strength20": float(step_returns.sum() - index_return),
        "realized_vol20": float(np.std(step_returns, ddof=1) * math.sqrt(252.0)),
        "range_width20": float(
            (bars.adjusted_high.max() - bars.adjusted_low.min()) / current.adjusted_close
        ),
        "downside_amount_share20": float(
            bars.loc[bars.step_log_return < 0, "amount"].sum() / amount_total
        ),
        "higher_low10": float(math.log(last10.adjusted_low.min() / prior10.adjusted_low.min())),
        "lower_high10": float(
            math.log(last10.adjusted_high.max() / prior10.adjusted_high.max())
        ),
        "distance_to_prior_high20": float(math.log(current.adjusted_close / prior_high)),
        "amount_ratio5_to_prior15": float(last5.amount.mean() / prior15.amount.mean()),
        "average_amount20": float(bars.amount.mean()),
    }
    if not all(math.isfinite(value) for value in metrics.values()):
        raise ArchaeologyError(f"nonfinite trajectory metric ending at {anchor_idx}")
    return metrics


def beta60(
    rows: pd.DataFrame,
    index_close: dict[int, float],
    signal_idx: int,
) -> float:
    window = rows[(rows.cal_idx >= signal_idx - 60) & (rows.cal_idx <= signal_idx)].copy()
    if window.cal_idx.astype(int).tolist() != list(range(signal_idx - 60, signal_idx + 1)):
        raise ArchaeologyError("noncontiguous beta60 window")
    steps = window[window.cal_idx > signal_idx - 60]
    if not window.critical_valid.astype(bool).all() or not steps.coordinate_step_valid.astype(bool).all():
        raise ArchaeologyError("invalid beta60 stock window")
    stock = steps.step_log_return.to_numpy(float)
    market = np.array(
        [math.log(index_close[idx] / index_close[idx - 1]) for idx in range(signal_idx - 59, signal_idx + 1)],
        dtype=float,
    )
    variance = float(np.var(market, ddof=1))
    if variance <= 0 or not np.isfinite(stock).all() or not np.isfinite(market).all():
        raise ArchaeologyError("invalid beta60 market window")
    return float(np.cov(stock, market, ddof=1)[0, 1] / variance)


def construct_trajectories(
    trades: pd.DataFrame,
    spec: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    identity = spec["transient_contract"]
    with tempfile.TemporaryDirectory(prefix="chinext_v1_wla001_") as temporary:
        transient_root = Path(temporary)
        manifest = phase2.extended.materialize_transient_inputs(transient_root)
        if manifest["canonical_sha256"] != identity["canonical_sha256"]:
            raise ArchaeologyError("extended transient canonical identity changed")
        if manifest["membership"]["sha256"] != identity["membership_sha256"]:
            raise ArchaeologyError("extended transient membership identity changed")
        connection = phase2.duckdb.connect()
        connection.execute("SET threads=1")
        phase2.create_membership_tables(connection, transient_root / "daily_membership.parquet")
        panel_counts = phase2.create_panel_tables(connection, transient_root)
        phase2.create_stock_features(connection)

        identities = trades[
            ["trade_id", "baseline_block", "symbol", "entry_signal_date"]
        ].copy()
        connection.register("trade_identity", identities)
        connection.execute(
            """
            CREATE TEMP TABLE trade_entries AS
            SELECT t.*,c.cal_idx AS signal_idx
            FROM trade_identity t
            JOIN calendar c ON CAST(t.entry_signal_date AS DATE)=c.trade_date
            """
        )
        if connection.execute("SELECT count(*) FROM trade_entries").fetchone()[0] != 399:
            raise ArchaeologyError("entry dates do not map to 399 calendar rows")
        history = connection.execute(
            """
            SELECT t.trade_id,t.baseline_block,t.symbol,t.signal_idx,
                   w.trade_date,w.cal_idx,w.critical_valid,w.coordinate_step_valid,
                   w.step_log_return,w.adjusted_close,w.adjusted_high,w.adjusted_low,
                   w.amount,w.industry,w.snapshot_id,w.available_at
            FROM trade_entries t
            JOIN stock_windows w
              ON w.baseline_block=t.baseline_block AND w.symbol=t.symbol
             AND w.cal_idx BETWEEN t.signal_idx-79 AND t.signal_idx
            ORDER BY t.trade_id,w.cal_idx
            """
        ).fetchdf()
        calendar = connection.execute(
            "SELECT CAST(trade_date AS TIMESTAMP) AS trade_date,cal_idx FROM calendar ORDER BY cal_idx"
        ).fetchdf()
        connection.close()

    index_close = load_index_close(calendar)
    records: list[dict[str, Any]] = []
    trade_meta: list[dict[str, Any]] = []
    for trade_id, rows in history.groupby("trade_id", sort=True):
        rows = rows.sort_values("cal_idx").reset_index(drop=True)
        signal_idx = int(rows.signal_idx.iloc[0])
        if rows.cal_idx.astype(int).tolist() != list(range(signal_idx - 79, signal_idx + 1)):
            raise ArchaeologyError(f"incomplete 80-session history for {trade_id}")
        signal_row = rows[rows.cal_idx == signal_idx].iloc[0]
        t1_metrics: dict[str, float] | None = None
        for label in ANCHORS:
            # T-1 is the entry-signal close; T-k is k-1 sessions before that close.
            anchor_idx = signal_idx - (label - 1)
            metrics = feature_window(rows, index_close, anchor_idx)
            if label == 1:
                t1_metrics = metrics
            anchor_row = rows[rows.cal_idx == anchor_idx].iloc[0]
            records.append(
                {
                    "trade_id": trade_id,
                    "baseline_block": rows.baseline_block.iloc[0],
                    "symbol": rows.symbol.iloc[0],
                    "sessions_before_entry": label,
                    "anchor_date": pd.Timestamp(anchor_row.trade_date).date().isoformat(),
                    "feature_available_at": pd.Timestamp(anchor_row.available_at).isoformat(),
                    "snapshot_id": anchor_row.snapshot_id,
                    **metrics,
                }
            )
        if t1_metrics is None:
            raise ArchaeologyError(f"missing T-1 metrics for {trade_id}")
        trade_meta.append(
            {
                "trade_id": trade_id,
                "entry_industry": signal_row.industry,
                "entry_beta60": beta60(rows, index_close, signal_idx),
                "entry_log_amount20": math.log(t1_metrics["average_amount20"]),
                "entry_snapshot_id": signal_row.snapshot_id,
            }
        )

    trajectories = pd.DataFrame(records)
    if len(trajectories) != 399 * len(ANCHORS):
        raise ArchaeologyError("trajectory row count changed")
    if trajectories.duplicated(["trade_id", "sessions_before_entry"]).any():
        raise ArchaeologyError("duplicate trade/anchor trajectory row")

    transitions = trades.merge(pd.DataFrame(trade_meta), on="trade_id", validate="one_to_one")
    indexed = trajectories.set_index(["trade_id", "sessions_before_entry"])
    for feature in TRAJECTORY_FEATURES:
        for anchor in ANCHORS:
            values = indexed[feature].xs(anchor, level="sessions_before_entry")
            transitions[f"{feature}_t{anchor}"] = transitions.trade_id.map(values)
    transitions["rs_improvement"] = (
        transitions.relative_strength20_t1 - transitions.relative_strength20_t20
    )
    transitions["rs_improvement_neighbor"] = (
        transitions.relative_strength20_t3 - transitions.relative_strength20_t20
    )
    transitions["volatility_compression"] = (
        transitions.realized_vol20_t20 - transitions.realized_vol20_t5
    )
    transitions["volatility_compression_neighbor"] = (
        transitions.realized_vol20_t20 - transitions.realized_vol20_t3
    )
    transitions["range_compression"] = (
        transitions.range_width20_t20 - transitions.range_width20_t5
    )
    transitions["range_compression_neighbor"] = (
        transitions.range_width20_t20 - transitions.range_width20_t3
    )
    transitions["downside_amount_contraction"] = (
        transitions.downside_amount_share20_t20 - transitions.downside_amount_share20_t5
    )
    transitions["downside_amount_contraction_neighbor"] = (
        transitions.downside_amount_share20_t20 - transitions.downside_amount_share20_t3
    )
    transitions["higher_low_formation"] = transitions.higher_low10_t5
    transitions["prior_high_approach"] = (
        transitions.distance_to_prior_high20_t1 - transitions.distance_to_prior_high20_t20
    )
    transitions["amount_release"] = (
        transitions.amount_ratio5_to_prior15_t1 - transitions.amount_ratio5_to_prior15_t5
    )
    required = [*PRIMARY_TRANSITIONS, *(f"{name}_neighbor" for name in PRIMARY_TRANSITIONS)]
    if transitions[required].replace([np.inf, -np.inf], np.nan).isna().any().any():
        raise ArchaeologyError("a fixed primary transition is missing")

    trajectory_outcomes = trades[
        [
            "trade_id",
            "entry_year",
            "outcome_class",
            "extreme_winner",
            "winner20",
            "false_breakout",
            "severe_loss",
            "mfe",
            "round_trip_return",
            "realized_pnl",
        ]
    ]
    trajectories = trajectories.merge(trajectory_outcomes, on="trade_id", validate="many_to_one")
    audit = {
        "panel_counts": panel_counts,
        "transient_canonical_sha256": manifest["canonical_sha256"],
        "transient_membership_sha256": manifest["membership"]["sha256"],
        "trajectory_rows": int(len(trajectories)),
        "complete_trade_anchor_pairs": int(
            trajectories.groupby("trade_id").sessions_before_entry.nunique().eq(len(ANCHORS)).sum()
        ),
        "hard_valid_window_failures": 0,
        "coordinate_window_failures": 0,
        "causal_entry_failures": 0,
        "post_entry_price_rows_read": 0,
        "strategy_replays": 0,
    }
    return trajectories, transitions, audit


def safe_spearman(x: pd.Series, y: pd.Series) -> dict[str, Any]:
    data = pd.DataFrame({"x": x, "y": y}).replace([np.inf, -np.inf], np.nan).dropna()
    result = {"n": int(len(data)), "rho": None, "p_value": None}
    if len(data) < 10 or data.x.nunique() < 2 or data.y.nunique() < 2:
        return result
    estimate = spearmanr(data.x, data.y)
    result["rho"] = finite_or_none(estimate.statistic)
    result["p_value"] = finite_or_none(estimate.pvalue)
    return result


def rank_association(frame: pd.DataFrame, feature: str, endpoint: str) -> dict[str, Any]:
    full = safe_spearman(frame[feature], frame[endpoint])
    ranked = frame[[feature, endpoint, "entry_year"]].copy()
    ranked["x_rank"] = ranked.groupby("entry_year")[feature].rank(pct=True, method="average")
    ranked["y_rank"] = ranked.groupby("entry_year")[endpoint].rank(pct=True, method="average")
    within = safe_spearman(ranked.x_rank, ranked.y_rank)
    loyo: dict[str, dict[str, Any]] = {}
    for year in range(2018, 2026):
        loyo[str(year)] = safe_spearman(
            frame.loc[frame.entry_year != year, feature],
            frame.loc[frame.entry_year != year, endpoint],
        )
    positive = sum(item["rho"] is not None and item["rho"] > 0 for item in loyo.values())
    negative = sum(item["rho"] is not None and item["rho"] < 0 for item in loyo.values())
    return {
        **full,
        "within_year_rank_rho": within["rho"],
        "within_year_rank_p_value": within["p_value"],
        "loyo": loyo,
        "loyo_positive_count": int(positive),
        "loyo_negative_count": int(negative),
    }


def bh_adjust(p_values: dict[str, float | None]) -> dict[str, float | None]:
    observed = sorted(
        ((name, float(value)) for name, value in p_values.items() if value is not None),
        key=lambda item: item[1],
    )
    result: dict[str, float | None] = {name: None for name in p_values}
    minimum = 1.0
    total = len(observed)
    for reverse_rank, (name, value) in enumerate(reversed(observed), start=1):
        rank = total - reverse_rank + 1
        minimum = min(minimum, value * total / rank)
        result[name] = float(min(1.0, minimum))
    return result


def partial_rank(
    frame: pd.DataFrame,
    feature: str,
    endpoint: str,
    *,
    extra_controls: tuple[str, ...] = (),
    category_controls: tuple[str, ...] = ("entry_year",),
) -> dict[str, Any]:
    controls = [*CONTROL_COLUMNS, *extra_controls]
    columns = [feature, endpoint, *controls, *category_controls]
    data = frame[columns].replace([np.inf, -np.inf], np.nan).dropna().copy()
    result = {"n": int(len(data)), "partial_rank_rho": None, "p_value": None}
    if len(data) < 300 or data[feature].nunique() < 2 or data[endpoint].nunique() < 2:
        return result
    predictor = data[feature].rank(pct=True, method="average").to_numpy(float)
    if pd.api.types.is_bool_dtype(data[endpoint]) or set(data[endpoint].unique()).issubset({0, 1, False, True}):
        outcome = data[endpoint].astype(float).to_numpy()
    else:
        outcome = data[endpoint].rank(pct=True, method="average").to_numpy(float)
    design_parts = [np.ones((len(data), 1))]
    ranked_controls = pd.DataFrame(index=data.index)
    for control in controls:
        ranked_controls[control] = data[control].rank(pct=True, method="average")
    design_parts.append(ranked_controls.to_numpy(float))
    for category in category_controls:
        dummies = pd.get_dummies(
            data[category].fillna("MISSING").astype(str),
            prefix=category,
            drop_first=True,
            dtype=float,
        )
        if len(dummies.columns):
            design_parts.append(dummies.to_numpy(float))
    design = np.column_stack(design_parts)
    x_residual = predictor - design @ np.linalg.lstsq(design, predictor, rcond=None)[0]
    y_residual = outcome - design @ np.linalg.lstsq(design, outcome, rcond=None)[0]
    if np.std(x_residual) == 0 or np.std(y_residual) == 0:
        return result
    estimate = pearsonr(x_residual, y_residual)
    result["partial_rank_rho"] = finite_or_none(estimate.statistic)
    result["p_value"] = finite_or_none(estimate.pvalue)
    return result


def controlled_with_loyo(frame: pd.DataFrame, feature: str, endpoint: str) -> dict[str, Any]:
    full = partial_rank(frame, feature, endpoint)
    loyo: dict[str, dict[str, Any]] = {}
    for year in range(2018, 2026):
        loyo[str(year)] = partial_rank(frame[frame.entry_year != year], feature, endpoint)
    positive = sum(
        item["partial_rank_rho"] is not None and item["partial_rank_rho"] > 0
        for item in loyo.values()
    )
    return {**full, "loyo": loyo, "loyo_positive_count": int(positive)}


def omit_group_sensitivity(
    frame: pd.DataFrame,
    feature: str,
    endpoint: str,
    group: str,
    values: list[str] | None = None,
) -> dict[str, Any]:
    estimates: dict[str, Any] = {}
    omissions = values or sorted(frame[group].dropna().astype(str).unique())
    for value in omissions:
        subset = frame[frame[group].astype(str) != value]
        estimates[value] = safe_spearman(subset[feature], subset[endpoint])
    valid = [item["rho"] for item in estimates.values() if item["rho"] is not None]
    return {
        "estimates": estimates,
        "valid_omissions": int(len(valid)),
        "positive_fraction": float(sum(value > 0 for value in valid) / len(valid)) if valid else None,
        "minimum_rho": float(min(valid)) if valid else None,
        "maximum_rho": float(max(valid)) if valid else None,
    }


def deterministic_top_flag(frame: pd.DataFrame, n: int) -> pd.Series:
    ordered = frame.sort_values(
        ["realized_pnl", "trade_id"], ascending=[False, True], kind="mergesort"
    )
    flag = pd.Series(False, index=frame.index)
    flag.loc[ordered.head(n).index] = True
    return flag


def analyze(transitions: pd.DataFrame) -> tuple[dict[str, Any], str]:
    q_values = bh_adjust(
        {
            feature: rank_association(transitions, feature, "extreme_winner")["p_value"]
            for feature in PRIMARY_TRANSITIONS
        }
    )
    primary: dict[str, Any] = {}
    raw_gate_components: list[str] = []
    passing_components: list[str] = []
    top4 = deterministic_top_flag(transitions, 4)
    extreme_symbols = sorted(
        transitions.loc[transitions.extreme_winner, "symbol"].astype(str).unique()
    )
    for feature in PRIMARY_TRANSITIONS:
        raw = rank_association(transitions, feature, "extreme_winner")
        controlled = controlled_with_loyo(transitions, feature, "extreme_winner")
        neighbor = rank_association(
            transitions, f"{feature}_neighbor", "extreme_winner"
        )
        ex_top4 = rank_association(transitions.loc[~top4], feature, "extreme_winner")
        holding_exit = partial_rank(
            transitions,
            feature,
            "extreme_winner",
            extra_controls=("holding_trading_days",),
            category_controls=("entry_year", "canonical_exit_reason"),
        )
        industry_control = partial_rank(
            transitions,
            feature,
            "extreme_winner",
            category_controls=("entry_year", "entry_industry"),
        )
        security_sensitivity = omit_group_sensitivity(
            transitions,
            feature,
            "extreme_winner",
            "symbol",
            extreme_symbols,
        )
        industry_sensitivity = omit_group_sensitivity(
            transitions[transitions.entry_industry.notna()],
            feature,
            "extreme_winner",
            "entry_industry",
        )
        block = {
            str(name): safe_spearman(rows[feature], rows.extreme_winner)
            for name, rows in transitions.groupby("baseline_block", sort=True)
        }
        raw_gate = bool(
            raw["rho"] is not None
            and raw["rho"] >= 0.10
            and q_values[feature] is not None
            and q_values[feature] <= 0.10
            and raw["within_year_rank_rho"] is not None
            and raw["within_year_rank_rho"] > 0
            and raw["loyo_positive_count"] >= 7
            and neighbor["rho"] is not None
            and neighbor["rho"] > 0
            and neighbor["loyo_positive_count"] >= 6
        )
        controlled_gate = bool(
            controlled["partial_rank_rho"] is not None
            and controlled["partial_rank_rho"] >= 0.10
            and controlled["loyo_positive_count"] >= 7
        )
        falsification_gate = bool(
            ex_top4["rho"] is not None
            and ex_top4["rho"] > 0
            and holding_exit["partial_rank_rho"] is not None
            and holding_exit["partial_rank_rho"] > 0
            and industry_control["partial_rank_rho"] is not None
            and industry_control["partial_rank_rho"] > 0
            and security_sensitivity["positive_fraction"] is not None
            and security_sensitivity["positive_fraction"] >= 0.80
            and industry_sensitivity["positive_fraction"] is not None
            and industry_sensitivity["positive_fraction"] >= 0.80
        )
        passes = bool(raw_gate and controlled_gate and falsification_gate)
        if raw_gate:
            raw_gate_components.append(feature)
        if passes:
            passing_components.append(feature)
        primary[feature] = {
            "expected_direction": "positive",
            "raw": raw,
            "bh_q_value": q_values[feature],
            "controlled": controlled,
            "neighbor": neighbor,
            "ex_global_top1pct_pnl": ex_top4,
            "holding_duration_exit_reason_control": holding_exit,
            "industry_fixed_effect_control": industry_control,
            "leave_one_extreme_security_out": security_sensitivity,
            "leave_one_industry_out": industry_sensitivity,
            "baseline_block": block,
            "raw_gate": raw_gate,
            "controlled_gate": controlled_gate,
            "falsification_gate": falsification_gate,
            "passes": passes,
        }

    secondary = {
        feature: {
            endpoint: rank_association(transitions, feature, endpoint)
            for endpoint in SECONDARY_ENDPOINTS
        }
        for feature in PRIMARY_TRANSITIONS
    }
    coherent = "rs_improvement" in passing_components and bool(
        SUPPLY_TRANSITIONS.intersection(passing_components)
    )
    if coherent:
        decision = "DEEPEN"
    elif passing_components:
        decision = "REFINE"
    elif raw_gate_components:
        decision = "PIVOT"
    else:
        decision = "REJECT"
    concentration = {
        "extreme_winner_cycles": int(transitions.extreme_winner.sum()),
        "extreme_winner_unique_securities": int(
            transitions.loc[transitions.extreme_winner, "symbol"].nunique()
        ),
        "maximum_extreme_winner_cycles_per_security": int(
            transitions.loc[transitions.extreme_winner, "symbol"].value_counts().max()
        ),
        "global_top1pct_trade_count": 4,
    }
    result = {
        "experiment_id": "EXP-WLA-001",
        "decision": decision,
        "coherent_demand_compression_mechanism": coherent,
        "raw_gate_components": raw_gate_components,
        "passing_components": passing_components,
        "primary": primary,
        "secondary": secondary,
        "concentration": concentration,
        "control_columns": list(CONTROL_COLUMNS),
        "multiple_testing": "Benjamini-Hochberg across exactly four frozen primary transitions",
    }
    return result, decision


def group_summary(trajectories: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for (outcome_class, anchor), rows in trajectories.groupby(
        ["outcome_class", "sessions_before_entry"], sort=True
    ):
        for feature in TRAJECTORY_FEATURES:
            records.append(
                {
                    "outcome_class": outcome_class,
                    "sessions_before_entry": int(anchor),
                    "feature": feature,
                    "count": int(rows[feature].notna().sum()),
                    "mean": float(rows[feature].mean()),
                    "median": float(rows[feature].median()),
                    "p25": float(rows[feature].quantile(0.25)),
                    "p75": float(rows[feature].quantile(0.75)),
                }
            )
    return pd.DataFrame(records)


def fmt(value: Any, digits: int = 3) -> str:
    number = finite_or_none(value)
    return "NA" if number is None else f"{number:.{digits}f}"


def build_report(
    transitions: pd.DataFrame,
    groups: pd.DataFrame,
    result: dict[str, Any],
    audit: dict[str, Any],
) -> str:
    lines = [
        "# Winner/loser pre-entry trajectory archaeology",
        "",
        "EXP-WLA-001 is exploratory mechanism evidence over already-consumed 2018-2025 outcomes. It uses no strategy replay, post-entry price, threshold search, interaction search, or strategy modification.",
        "",
        "## Integrity and PIT audit",
        "",
        f"- Frozen completed cycles: `{len(transitions)}`; complete trade/anchor panels: `{audit['complete_trade_anchor_pairs']}`.",
        f"- Trajectory rows: `{audit['trajectory_rows']}` at fixed anchors T-60/T-40/T-20/T-10/T-5/T-3/T-1.",
        "- T-1 is the completed entry-signal close; it is applicable only to the later first-valid entry execution.",
        f"- Hard-valid/coordinate/causal failures: `{audit['hard_valid_window_failures']}` / `{audit['coordinate_window_failures']}` / `{audit['causal_entry_failures']}`.",
        f"- Strategy replays: `{audit['strategy_replays']}`; post-entry price rows read: `{audit['post_entry_price_rows_read']}`.",
        "- Stock returns use the existing visible-action causal coordinate. Downside traded-amount share is a proxy based on negative-return sessions, not order-flow classification.",
        "",
        "## Fixed outcome groups",
        "",
        "| Group | N |",
        "|---|---:|",
    ]
    for name, count in transitions.outcome_class.value_counts().sort_index().items():
        lines.append(f"| {name} | {count} |")
    lines += [
        "",
        "## Preregistered primary transition tests",
        "",
        "All four transitions are oriented so a positive association supports the proposed extreme-winner mechanism.",
        "",
        "| Transition | Raw rho | BH q | Within-year rho | LOYO + | Controlled rho | Controlled LOYO + | Neighbor rho | Pass |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for feature in PRIMARY_TRANSITIONS:
        item = result["primary"][feature]
        lines.append(
            f"| {feature} | {fmt(item['raw']['rho'])} | {fmt(item['bh_q_value'])} | "
            f"{fmt(item['raw']['within_year_rank_rho'])} | {item['raw']['loyo_positive_count']}/8 | "
            f"{fmt(item['controlled']['partial_rank_rho'])} | {item['controlled']['loyo_positive_count']}/8 | "
            f"{fmt(item['neighbor']['rho'])} | {'YES' if item['passes'] else 'NO'} |"
        )
    lines += [
        "",
        "The fixed controlled design includes V1 entry RS/momentum/box/minimum-volume/breakout-volume state, entry-year effects, market return/volatility, frozen breadth, trailing stock beta, and traded-amount liquidity. The neighbor uses T-3 in place of T-1 or T-5; it cannot replace the primary definition.",
        "",
        "## Group trajectories at the key anchors",
        "",
        "| Group | Anchor | Relative strength20 median | Vol20 median | Range20 median | Downside-amount share median |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for outcome_class in sorted(transitions.outcome_class.unique()):
        for anchor in (20, 5, 1):
            values: dict[str, float] = {}
            for feature in (
                "relative_strength20",
                "realized_vol20",
                "range_width20",
                "downside_amount_share20",
            ):
                row = groups[
                    (groups.outcome_class == outcome_class)
                    & (groups.sessions_before_entry == anchor)
                    & (groups.feature == feature)
                ].iloc[0]
                values[feature] = row["median"]
            lines.append(
                f"| {outcome_class} | T-{anchor} | {fmt(values['relative_strength20'])} | "
                f"{fmt(values['realized_vol20'])} | {fmt(values['range_width20'])} | "
                f"{fmt(values['downside_amount_share20'])} |"
            )
    lines += [
        "",
        "## Active falsification",
        "",
        "| Transition | Ex-top-1% rho | Holding/exit controlled rho | Industry-FE rho | Security omission + | Industry omission + | Falsification pass |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for feature in PRIMARY_TRANSITIONS:
        item = result["primary"][feature]
        lines.append(
            f"| {feature} | {fmt(item['ex_global_top1pct_pnl']['rho'])} | "
            f"{fmt(item['holding_duration_exit_reason_control']['partial_rank_rho'])} | "
            f"{fmt(item['industry_fixed_effect_control']['partial_rank_rho'])} | "
            f"{fmt(item['leave_one_extreme_security_out']['positive_fraction'])} | "
            f"{fmt(item['leave_one_industry_out']['positive_fraction'])} | "
            f"{'YES' if item['falsification_gate'] else 'NO'} |"
        )
    lines += [
        "",
        "## Scientific decision",
        "",
        f"`{result['decision']}`. Passing components: `{', '.join(result['passing_components']) or 'none'}`. A coherent demand-plus-compression mechanism requires RS improvement and at least one independently passing compression/supply transition.",
        "",
        "A positive historical difference is not a filter, threshold, or candidate. All existing outcomes are consumed and the underlying security/universe data are bounded PIT-B, not untouched PIT-A.",
        "",
        "## Strategy candidate",
        "",
        "None. EXP-WLA-001 authorizes no entry, sizing, ranking, exit, or production change.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    spec, identities = validate_spec_and_inputs()
    trades = load_trade_frame()
    trajectories, transitions, audit = construct_trajectories(trades, spec)
    groups = group_summary(trajectories)
    result, _ = analyze(transitions)
    result.update(
        {
            "spec_sha256": sha256_file(SPEC),
            "input_identities": identities,
            "audit": audit,
            "outcome_group_counts": {
                str(key): int(value)
                for key, value in transitions.outcome_class.value_counts().sort_index().items()
            },
            "breadth_h004_status": "PROSPECTIVE_VALIDATION_PENDING_FROZEN",
            "strategy_modification": "NONE",
        }
    )
    trajectory_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "sessions_before_entry",
        "anchor_date",
        "feature_available_at",
        "snapshot_id",
        *TRAJECTORY_FEATURES,
        "average_amount20",
        "entry_year",
        "outcome_class",
        "extreme_winner",
        "winner20",
        "false_breakout",
        "severe_loss",
        "mfe",
        "round_trip_return",
        "realized_pnl",
    ]
    transition_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
        "entry_year",
        "entry_industry",
        "entry_snapshot_id",
        "entry_beta60",
        "entry_log_amount20",
        "outcome_class",
        "extreme_winner",
        "winner20",
        "false_breakout",
        "severe_loss",
        "mfe",
        "round_trip_return",
        "realized_pnl",
        "holding_trading_days",
        "canonical_exit_reason",
        *CONTROL_COLUMNS[:-2],
        *PRIMARY_TRANSITIONS,
        *(f"{name}_neighbor" for name in PRIMARY_TRANSITIONS),
        "higher_low_formation",
        "prior_high_approach",
        "amount_release",
    ]
    atomic_write(
        OUTPUT_TRAJECTORIES,
        trajectories[trajectory_columns].sort_values(
            ["trade_id", "sessions_before_entry"], ascending=[True, False]
        ).to_csv(index=False, lineterminator="\n", float_format="%.17g"),
    )
    atomic_write(
        OUTPUT_TRANSITIONS,
        transitions[transition_columns].sort_values("trade_id").to_csv(
            index=False, lineterminator="\n", float_format="%.17g"
        ),
    )
    atomic_write(
        OUTPUT_GROUPS,
        groups.sort_values(["outcome_class", "sessions_before_entry", "feature"]).to_csv(
            index=False, lineterminator="\n", float_format="%.17g"
        ),
    )
    atomic_write(OUTPUT_JSON, json.dumps(clean_json(result), indent=2, sort_keys=True) + "\n")
    atomic_write(REPORT, build_report(transitions, groups, result, audit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
