#!/usr/bin/env python3
"""Execute frozen HAB-CHX-001 CHINEXT V1 market-habitat association."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/HAB-CHX-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/HAB-CHX-001_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/HAB-CHX-001_result.json"
REPORT_PATH = PROGRAM / "reports/HAB-CHX-001_chinext_market_habitat.md"
EXPECTED_SPEC_SHA256 = "c17f8ea89cee61dc1ede89722bde38d0710c2a254b15e972fb19bd9664305a38"
BOOTSTRAP_SEED = 20260830
BOOTSTRAP_REPETITIONS = 2000
MIN_SAMPLE = 20


class HabitatError(RuntimeError):
    """Raised when frozen inputs, PIT semantics, or reconciliation fail."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def _seed(label: str) -> int:
    digest = hashlib.sha256(f"{BOOTSTRAP_SEED}:{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % (2**32)


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def _state_cell(a: pd.Series, b: pd.Series) -> pd.Series:
    return pd.Series(
        np.select(
            [a.gt(0) & b.gt(0), a.gt(0) & b.le(0), a.le(0) & b.gt(0)],
            ["A_AND_B", "A_ONLY", "B_ONLY"],
            default="NEITHER",
        ),
        index=a.index,
    )


def _validate_timestamp_columns(frame: pd.DataFrame, prefix: str) -> None:
    decision = pd.to_datetime(frame[f"decision_at_{prefix}"], utc=True)
    available = pd.to_datetime(frame[f"available_at_{prefix}"], utc=True)
    if not available.eq(decision).all():
        raise HabitatError(f"{prefix} availability differs from completed-close decision")
    shanghai = decision.dt.tz_convert("Asia/Shanghai")
    if not (shanghai.dt.hour.eq(15) & shanghai.dt.minute.eq(0)).all():
        raise HabitatError(f"{prefix} decision time is not completed 15:00 close")


def _bound_path(spec: dict[str, Any], item: dict[str, Any], source: bool = False) -> Path:
    base = Path(spec["inputs"]["frozen_event_ledgers"]["source_checkout_root"]) if source else ROOT
    path = base / item["path"]
    if not path.is_file():
        raise HabitatError(f"bound input missing: {path}")
    actual = sha256_file(path)
    if actual != item["sha256"]:
        raise HabitatError(f"bound input hash mismatch: {path}: {actual}")
    return path


def load_market_state(spec: dict[str, Any]) -> pd.DataFrame:
    trend_item = spec["inputs"]["trend_panel"]
    breadth_item = spec["inputs"]["breadth_panel"]
    trend_path = _bound_path(spec, trend_item)
    breadth_path = _bound_path(spec, breadth_item)

    trend = pd.read_csv(trend_path)
    trend = trend.loc[
        trend.index_symbol.eq("sz399006") & trend.source_hard_valid.astype(bool),
        [
            "trade_date",
            "decision_at",
            "available_at",
            "snapshot_id",
            "direction_return_60",
            "direction_return_60_pit_3y_pct",
        ],
    ].rename(
        columns={
            "decision_at": "decision_at_trend",
            "available_at": "available_at_trend",
            "snapshot_id": "snapshot_id_trend",
            "direction_return_60": "A_trend_direction",
            "direction_return_60_pit_3y_pct": "A_trend_pit_3y_pct",
        }
    )
    breadth = pd.read_csv(breadth_path)
    common_columns = [
        "trade_date",
        "decision_at",
        "available_at",
        "snapshot_id",
        "breadth_net_new_high_low60",
        "breadth_net_new_high_low60_pit_3y_pct",
        "breadth_net_new_high_low60_relative_to_all",
    ]
    primary = breadth.loc[
        breadth.market_view.eq("CHINEXT_BOARD")
        & breadth.denominator.eq("ALL_STATUS")
        & breadth.view_valid.astype(bool),
        common_columns,
    ].rename(
        columns={
            "decision_at": "decision_at_breadth",
            "available_at": "available_at_breadth",
            "snapshot_id": "snapshot_id_breadth",
            "breadth_net_new_high_low60": "B_breadth_discovery",
            "breadth_net_new_high_low60_pit_3y_pct": "B_breadth_pit_3y_pct",
            "breadth_net_new_high_low60_relative_to_all": "B_breadth_relative_to_all",
        }
    )
    neighbor = breadth.loc[
        breadth.market_view.eq("CHINEXT_BOARD")
        & breadth.denominator.eq("NON_ST")
        & breadth.view_valid.astype(bool),
        ["trade_date", "breadth_net_new_high_low60"],
    ].rename(columns={"breadth_net_new_high_low60": "B_breadth_discovery_non_st"})
    for label, frame in (("trend", trend), ("breadth", primary), ("neighbor", neighbor)):
        frame["trade_date"] = pd.to_datetime(frame.trade_date)
        if frame.trade_date.duplicated().any():
            raise HabitatError(f"duplicate {label} market date")
    state = trend.merge(primary, on="trade_date", validate="one_to_one").merge(
        neighbor, on="trade_date", validate="one_to_one"
    )
    if len(state) != 1337:
        raise HabitatError(f"common state population changed: {len(state)}")
    if state.trade_date.min() != pd.Timestamp("2018-07-03") or state.trade_date.max() != pd.Timestamp(
        "2023-12-29"
    ):
        raise HabitatError("common state date boundary changed")
    required = ["A_trend_direction", "B_breadth_discovery", "B_breadth_discovery_non_st"]
    if not np.isfinite(state[required].to_numpy(float)).all():
        raise HabitatError("primary market state contains missing/nonfinite value")
    _validate_timestamp_columns(state, "trend")
    _validate_timestamp_columns(state, "breadth")
    state["state_cell"] = _state_cell(state.A_trend_direction, state.B_breadth_discovery)
    state["calendar_year"] = state.trade_date.dt.year
    state["temporal_block"] = np.where(state.trade_date.le("2020-12-31"), "EARLY", "LATE")
    return state.sort_values("trade_date").reset_index(drop=True)


def load_strategy_process(spec: dict[str, Any], state: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    ledger_spec = spec["inputs"]["frozen_event_ledgers"]
    evaluated: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, pd.Timestamp, str]] = set()
    expected_hash_by_block: dict[str, str] = {}
    for block in ("EXTENDED_2018_2021", "HOLDOUT_O0_2022_2023"):
        item = ledger_spec[block]
        path = _bound_path(spec, item, source=True)
        expected_hash_by_block[block] = item["sha256"]
        for row in _read_jsonl(path):
            event = row.get("event")
            signal_date = pd.Timestamp(row["signal_date"]) if row.get("signal_date") else None
            if event == "ENTRY_SIGNAL_EVALUATED":
                if row.get("price_structure_pass") is not True:
                    raise HabitatError("evaluated event without frozen price-structure pass")
                candidate = bool(row.get("minvol", {}).get("passed") is True and row.get("rs") is not None)
                evaluated.append(
                    {
                        "baseline_block": block,
                        "trade_date": signal_date,
                        "symbol": str(row["symbol"]),
                        "admissible_candidate": candidate,
                        "source_event_ledger_sha256": item["sha256"],
                    }
                )
            elif event == "DESIRED_SET_CHANGED":
                additions = set(map(str, row.get("desired", []))) - set(map(str, row.get("previous", [])))
                for symbol in additions:
                    selected_keys.add((block, signal_date, symbol))
    events = pd.DataFrame(evaluated)
    if events.duplicated(["baseline_block", "trade_date", "symbol"]).any():
        raise HabitatError("duplicate evaluated strategy event")
    event_keys = set(map(tuple, events[["baseline_block", "trade_date", "symbol"]].to_numpy()))
    if not selected_keys.issubset(event_keys):
        raise HabitatError("selected addition lacks same-date evaluated event")
    events["selected_admission"] = [
        (row.baseline_block, row.trade_date, row.symbol) in selected_keys
        for row in events.itertuples(index=False)
    ]
    state_columns = [
        "trade_date",
        "A_trend_direction",
        "A_trend_pit_3y_pct",
        "B_breadth_discovery",
        "B_breadth_pit_3y_pct",
        "B_breadth_relative_to_all",
        "B_breadth_discovery_non_st",
        "state_cell",
        "calendar_year",
        "temporal_block",
        "snapshot_id_trend",
        "snapshot_id_breadth",
    ]
    events = events.merge(state[state_columns], on="trade_date", how="inner", validate="many_to_one")
    expected = spec["strategy_process_definitions"]["expected_pre_outcome_counts"]
    actual = {
        "evaluated_events": len(events),
        "admissible_candidates": int(events.admissible_candidate.sum()),
        "selected_admissions": int(events.selected_admission.sum()),
        "distinct_evaluation_dates": int(events.trade_date.nunique()),
    }
    for key, value in actual.items():
        if value != int(expected[key]):
            raise HabitatError(f"strategy process count changed: {key}: {value}")
    if (events.selected_admission & ~events.admissible_candidate).any():
        raise HabitatError("selected admission is not an admissible candidate")

    daily_counts = events.groupby("trade_date", sort=True).agg(
        evaluated_count=("symbol", "size"),
        candidate_count=("admissible_candidate", "sum"),
        selected_count=("selected_admission", "sum"),
    )
    daily = state.merge(daily_counts, left_on="trade_date", right_index=True, how="left", validate="one_to_one")
    daily[["evaluated_count", "candidate_count", "selected_count"]] = daily[
        ["evaluated_count", "candidate_count", "selected_count"]
    ].fillna(0).astype(int)
    if len(daily) != int(expected["valid_market_dates"]):
        raise HabitatError("calendar denominator changed")
    return events.sort_values(["trade_date", "symbol"]).reset_index(drop=True), daily


def load_completed_cycles(
    spec: dict[str, Any], state: pd.DataFrame, events: pd.DataFrame
) -> pd.DataFrame:
    trade_item = spec["inputs"]["completed_cycles"]
    baseline_item = spec["inputs"]["baseline_manifest"]
    trade_path = _bound_path(spec, trade_item)
    _bound_path(spec, baseline_item)
    trades = pd.read_csv(trade_path)
    blocks = {"EXTENDED_2018_2021", "HOLDOUT_O0_2022_2023"}
    trades = trades.loc[trades.baseline_block.isin(blocks)].copy()
    for column in ("entry_signal_date", "entry_execution_date", "exit_signal_date", "exit_execution_date"):
        trades[column] = pd.to_datetime(trades[column])
    if not trades.entry_execution_date.gt(trades.entry_signal_date).all():
        raise HabitatError("same-or-earlier entry fill detected")
    selected = events.loc[
        events.selected_admission,
        ["baseline_block", "trade_date", "symbol", "source_event_ledger_sha256"],
    ].rename(columns={"trade_date": "entry_signal_date"})
    cycles = selected.merge(
        trades,
        on=["baseline_block", "entry_signal_date", "symbol"],
        how="left",
        validate="one_to_one",
    )
    if len(cycles) != 280 or cycles.trade_id.isna().any():
        raise HabitatError("280 selected admissions do not reconcile to completed cycles")
    if cycles.trade_id.duplicated().any():
        raise HabitatError("completed cycle used more than once")
    state_columns = [
        "trade_date",
        "A_trend_direction",
        "A_trend_pit_3y_pct",
        "B_breadth_discovery",
        "B_breadth_pit_3y_pct",
        "B_breadth_relative_to_all",
        "B_breadth_discovery_non_st",
        "state_cell",
        "calendar_year",
        "temporal_block",
        "snapshot_id_trend",
        "snapshot_id_breadth",
    ]
    cycles = cycles.merge(
        state[state_columns],
        left_on="entry_signal_date",
        right_on="trade_date",
        validate="many_to_one",
    )
    cycles["winner20"] = cycles.round_trip_return.ge(0.20)
    cycles["winner50"] = cycles.round_trip_return.ge(0.50)
    cycles["severe_loss10"] = cycles.round_trip_return.le(-0.10)
    cycles["extreme_loss20"] = cycles.round_trip_return.le(-0.20)
    cycles["false_breakout"] = cycles.mfe.lt(0.10) & cycles.round_trip_return.le(0)
    cycles["opportunity20"] = cycles.mfe.ge(0.20)
    cycles["conversion20"] = cycles.winner20
    cycles["giveback_from_peak"] = cycles.mfe - cycles.round_trip_return
    return cycles.sort_values(["entry_signal_date", "symbol"]).reset_index(drop=True)


def _pearson(left: np.ndarray, right: np.ndarray) -> float:
    mask = np.isfinite(left) & np.isfinite(right)
    if int(mask.sum()) < 3:
        return float("nan")
    x, y = left[mask], right[mask]
    if np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _rank_residual(values: np.ndarray, control: np.ndarray) -> np.ndarray:
    design = np.column_stack([np.ones(len(control)), control])
    coefficient, *_ = np.linalg.lstsq(design, values, rcond=None)
    return values - design @ coefficient


def _correlation(left: np.ndarray, right: np.ndarray, control: np.ndarray | None = None) -> float:
    mask = np.isfinite(left) & np.isfinite(right)
    if control is not None:
        mask &= np.isfinite(control)
    if int(mask.sum()) < MIN_SAMPLE:
        return float("nan")
    x = rankdata(left[mask], method="average")
    y = rankdata(right[mask], method="average")
    if control is not None:
        z = rankdata(control[mask], method="average")
        x = _rank_residual(x, z)
        y = _rank_residual(y, z)
    return _pearson(x, y)


def _cluster_bootstrap_correlation(
    frame: pd.DataFrame,
    feature: str,
    outcome: str,
    control: str | None,
    label: str,
) -> tuple[float | None, float | None, int]:
    columns = [feature, outcome, "cluster_date"] + ([control] if control else [])
    data = frame[columns].replace([np.inf, -np.inf], np.nan).dropna().copy()
    if len(data) < MIN_SAMPLE or data[feature].nunique() < 2 or data[outcome].nunique() < 2:
        return None, None, 0
    x = rankdata(data[feature].to_numpy(float), method="average")
    y = rankdata(data[outcome].to_numpy(float), method="average")
    z = rankdata(data[control].to_numpy(float), method="average") if control else None
    clusters = data.cluster_date.astype(str).to_numpy()
    unique = np.unique(clusters)
    indices = [np.flatnonzero(clusters == item) for item in unique]
    rng = np.random.default_rng(_seed(label))
    estimates: list[float] = []
    for _ in range(BOOTSTRAP_REPETITIONS):
        chosen = rng.integers(0, len(indices), size=len(indices))
        sample_index = np.concatenate([indices[index] for index in chosen])
        bx, by = x[sample_index], y[sample_index]
        if z is not None:
            bz = z[sample_index]
            bx = _rank_residual(bx, bz)
            by = _rank_residual(by, bz)
        estimate = _pearson(bx, by)
        if math.isfinite(estimate):
            estimates.append(estimate)
    if len(estimates) < int(BOOTSTRAP_REPETITIONS * 0.80):
        return None, None, len(estimates)
    low, high = np.quantile(estimates, [0.05, 0.95])
    return float(low), float(high), len(estimates)


def association_diagnostics(
    frame: pd.DataFrame,
    feature: str,
    outcome: str,
    label: str,
    control: str | None = None,
) -> dict[str, Any]:
    columns = [feature, outcome, "cluster_date", "calendar_year", "temporal_block"]
    if control:
        columns.append(control)
    data = frame[columns].replace([np.inf, -np.inf], np.nan).dropna().copy()
    rho = _correlation(
        data[feature].to_numpy(float),
        data[outcome].to_numpy(float),
        data[control].to_numpy(float) if control else None,
    )
    low, high, bootstrap_valid = _cluster_bootstrap_correlation(
        data, feature, outcome, control, label
    )
    blocks: dict[str, dict[str, Any]] = {}
    for block in ("EARLY", "LATE"):
        rows = data.loc[data.temporal_block.eq(block)]
        blocks[block] = {
            "n": len(rows),
            "rho": _correlation(
                rows[feature].to_numpy(float),
                rows[outcome].to_numpy(float),
                rows[control].to_numpy(float) if control else None,
            ),
        }
    yearly: dict[str, dict[str, Any]] = {}
    for year, rows in data.groupby("calendar_year", sort=True):
        yearly[str(int(year))] = {
            "n": len(rows),
            "rho": _correlation(
                rows[feature].to_numpy(float),
                rows[outcome].to_numpy(float),
                rows[control].to_numpy(float) if control else None,
            ),
        }
    loyo: dict[str, dict[str, Any]] = {}
    for year in sorted(data.calendar_year.unique()):
        rows = data.loc[data.calendar_year.ne(year)]
        loyo[str(int(year))] = {
            "n": len(rows),
            "rho": _correlation(
                rows[feature].to_numpy(float),
                rows[outcome].to_numpy(float),
                rows[control].to_numpy(float) if control else None,
            ),
        }
    sign = 0 if not math.isfinite(rho) or rho == 0 else int(np.sign(rho))
    block_pass = sign != 0 and all(
        item["rho"] is not None
        and math.isfinite(item["rho"])
        and np.sign(item["rho"]) == sign
        and abs(item["rho"]) >= 0.05
        for item in blocks.values()
    )
    eligible_years = [item for item in yearly.values() if item["n"] >= MIN_SAMPLE and item["rho"] is not None]
    same_sign_years = sum(math.isfinite(item["rho"]) and np.sign(item["rho"]) == sign for item in eligible_years)
    interval_excludes_zero = low is not None and high is not None and (low > 0 or high < 0)
    gate = bool(
        math.isfinite(rho)
        and abs(rho) >= 0.10
        and interval_excludes_zero
        and block_pass
        and same_sign_years >= 4
    )
    return {
        "n": len(data),
        "rho": rho,
        "bootstrap_90pct": [low, high],
        "bootstrap_valid_repetitions": bootstrap_valid,
        "temporal_blocks": blocks,
        "yearly": yearly,
        "eligible_year_count": len(eligible_years),
        "same_sign_year_count": same_sign_years,
        "leave_one_year_out": loyo,
        "gate_pass": gate,
        "partial_control": control,
    }


def _fit_ols(frame: pd.DataFrame, outcome: str, model: str) -> dict[str, Any]:
    data = frame[[outcome, "A_trend_direction", "B_breadth_discovery"]].replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    y = data[outcome].to_numpy(float)
    a = data.A_trend_direction.to_numpy(float) / 0.10
    b = data.B_breadth_discovery.to_numpy(float) / 0.01
    columns = [np.ones(len(data))]
    names = ["intercept"]
    if model in {"A", "A+B"}:
        columns.append(a)
        names.append("A_per_0p10")
    if model in {"B", "A+B"}:
        columns.append(b)
        names.append("B_per_0p01")
    if model == "A+B":
        columns.append(a * b)
        names.append("A_x_B")
    design = np.column_stack(columns)
    if len(data) <= design.shape[1] or np.linalg.matrix_rank(design) < design.shape[1]:
        return {"n": len(data), "coefficients": {}, "r_squared": None, "adjusted_r_squared": None}
    coefficient, *_ = np.linalg.lstsq(design, y, rcond=None)
    fitted = design @ coefficient
    residual_sum = float(np.square(y - fitted).sum())
    total_sum = float(np.square(y - y.mean()).sum())
    if total_sum == 0:
        r_squared = adjusted = None
    else:
        r_squared = 1.0 - residual_sum / total_sum
        adjusted = 1.0 - (1.0 - r_squared) * (len(data) - 1) / (len(data) - design.shape[1])
    return {
        "n": len(data),
        "coefficients": dict(zip(names, map(float, coefficient), strict=True)),
        "r_squared": r_squared,
        "adjusted_r_squared": adjusted,
    }


def nested_model_diagnostics(frame: pd.DataFrame, outcome: str, label: str) -> dict[str, Any]:
    models = {name: _fit_ols(frame, outcome, name) for name in ("BASELINE", "A", "B", "A+B")}
    blocks: dict[str, Any] = {}
    for block in ("EARLY", "LATE"):
        subset = frame.loc[frame.temporal_block.eq(block)]
        blocks[block] = {
            name: _fit_ols(subset, outcome, name) for name in ("BASELINE", "A", "B", "A+B")
        }

    data = frame[[outcome, "A_trend_direction", "B_breadth_discovery", "cluster_date"]].replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    clusters = data.cluster_date.astype(str).to_numpy()
    unique = np.unique(clusters)
    indices = [np.flatnonzero(clusters == item) for item in unique]
    rng = np.random.default_rng(_seed(f"nested:{label}"))
    interactions: list[float] = []
    for _ in range(BOOTSTRAP_REPETITIONS):
        chosen = rng.integers(0, len(indices), size=len(indices))
        sample = data.iloc[np.concatenate([indices[index] for index in chosen])]
        fitted = _fit_ols(sample, outcome, "A+B")
        value = fitted["coefficients"].get("A_x_B")
        if value is not None and math.isfinite(value):
            interactions.append(float(value))
    interaction_interval = (
        list(map(float, np.quantile(interactions, [0.05, 0.95])))
        if len(interactions) >= int(BOOTSTRAP_REPETITIONS * 0.80)
        else [None, None]
    )

    def delta(fitted: dict[str, Any]) -> float | None:
        combined = fitted["A+B"]["adjusted_r_squared"]
        singles = [fitted[name]["adjusted_r_squared"] for name in ("A", "B")]
        if combined is None or any(value is None for value in singles):
            return None
        return float(combined - max(singles))

    full_delta = delta(models)
    block_deltas = {block: delta(fitted) for block, fitted in blocks.items()}
    full_interaction = models["A+B"]["coefficients"].get("A_x_B")
    block_interactions = {
        block: fitted["A+B"]["coefficients"].get("A_x_B") for block, fitted in blocks.items()
    }
    same_sign = (
        full_interaction is not None
        and full_interaction != 0
        and all(value is not None and np.sign(value) == np.sign(full_interaction) for value in block_interactions.values())
    )
    interval_excludes_zero = (
        interaction_interval[0] is not None
        and (interaction_interval[0] > 0 or interaction_interval[1] < 0)
    )
    gate = bool(
        full_delta is not None
        and full_delta >= 0.01
        and all(value is not None and value >= 0.01 for value in block_deltas.values())
        and same_sign
        and interval_excludes_zero
    )
    return {
        "full": models,
        "temporal_blocks": blocks,
        "A_plus_B_adjusted_r2_increment_over_best_single": full_delta,
        "block_increments": block_deltas,
        "interaction_bootstrap_90pct": interaction_interval,
        "interaction_bootstrap_valid_repetitions": len(interactions),
        "gate_pass": gate,
    }


def _positive_pnl_concentration(rows: pd.DataFrame) -> float | None:
    positive = rows.loc[rows.realized_pnl.gt(0), "realized_pnl"].sort_values(ascending=False)
    if positive.empty or positive.sum() <= 0:
        return None
    return float(positive.head(20).sum() / positive.sum())


def summarize_cells(daily: pd.DataFrame, events: pd.DataFrame, cycles: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for cell in ("NEITHER", "A_ONLY", "B_ONLY", "A_AND_B"):
        d = daily.loc[daily.state_cell.eq(cell)]
        e = events.loc[events.state_cell.eq(cell)]
        t = cycles.loc[cycles.state_cell.eq(cell)]
        opportunity = t.loc[t.opportunity20]
        result[cell] = {
            "market_dates": len(d),
            "adequate_market_dates": len(d) >= 30,
            "evaluated_events": len(e),
            "candidate_rate_among_events": float(e.admissible_candidate.mean()) if len(e) else None,
            "selected_rate_among_events": float(e.selected_admission.mean()) if len(e) else None,
            "mean_evaluated_count_per_market_date": float(d.evaluated_count.mean()) if len(d) else None,
            "completed_cycles": len(t),
            "adequate_completed_cycles": len(t) >= 20,
            "payoff_evidence_status": "DESCRIPTIVE" if len(t) >= 20 else "INSUFFICIENT_EVIDENCE",
            "round_trip_return_mean": float(t.round_trip_return.mean()) if len(t) else None,
            "round_trip_return_median": float(t.round_trip_return.median()) if len(t) else None,
            "hit_rate": float(t.round_trip_return.gt(0).mean()) if len(t) else None,
            "winner20_rate": float(t.winner20.mean()) if len(t) else None,
            "winner50_rate": float(t.winner50.mean()) if len(t) else None,
            "opportunity20_rate": float(t.opportunity20.mean()) if len(t) else None,
            "conversion20_within_opportunity_rate": float(opportunity.conversion20.mean()) if len(opportunity) else None,
            "false_breakout_rate": float(t.false_breakout.mean()) if len(t) else None,
            "severe_loss10_rate": float(t.severe_loss10.mean()) if len(t) else None,
            "extreme_loss20_rate": float(t.extreme_loss20.mean()) if len(t) else None,
            "positive_pnl_top20_concentration": _positive_pnl_concentration(t),
        }
    return result


def summarize_temporal(cycles: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for block, rows in cycles.groupby("temporal_block", sort=True):
        result[str(block)] = {
            "completed_cycles": len(rows),
            "mean_return": float(rows.round_trip_return.mean()),
            "median_return": float(rows.round_trip_return.median()),
            "winner20_rate": float(rows.winner20.mean()),
            "winner50_rate": float(rows.winner50.mean()),
            "false_breakout_rate": float(rows.false_breakout.mean()),
            "severe_loss10_rate": float(rows.severe_loss10.mean()),
            "positive_pnl_top20_concentration": _positive_pnl_concentration(rows),
        }
    return result


def _analysis_samples(
    daily: pd.DataFrame, events: pd.DataFrame, cycles: pd.DataFrame
) -> dict[str, tuple[pd.DataFrame, list[str], str]]:
    daily_sample = daily.rename(columns={"trade_date": "cluster_date"}).copy()
    event_sample = events.rename(columns={"trade_date": "cluster_date"}).copy()
    candidate_sample = event_sample.loc[event_sample.admissible_candidate].copy()
    trade_sample = cycles.rename(columns={"entry_signal_date": "cluster_date"}).copy()
    opportunity_sample = trade_sample.loc[trade_sample.opportunity20].copy()
    return {
        "daily_process": (daily_sample, ["evaluated_count", "candidate_count", "selected_count"], "opportunity_process"),
        "event_conversion": (event_sample, ["admissible_candidate", "selected_admission"], "opportunity_process"),
        "candidate_selection": (candidate_sample, ["selected_admission"], "opportunity_process"),
        "completed_cycle": (
            trade_sample,
            [
                "round_trip_return",
                "mfe",
                "mae",
                "winner20",
                "winner50",
                "severe_loss10",
                "extreme_loss20",
                "false_breakout",
                "opportunity20",
                "giveback_from_peak",
            ],
            "payoff",
        ),
        "opportunity20_conversion": (opportunity_sample, ["conversion20"], "payoff"),
    }


def run_analyses(
    daily: pd.DataFrame, events: pd.DataFrame, cycles: pd.DataFrame
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, str]], list[str]]:
    associations: dict[str, Any] = {}
    nested: dict[str, Any] = {}
    sensitivity: dict[str, Any] = {}
    passing: list[dict[str, str]] = []
    synergy: list[str] = []
    for sample_name, (frame, outcomes, role) in _analysis_samples(daily, events, cycles).items():
        associations[sample_name] = {}
        nested[sample_name] = {}
        sensitivity[sample_name] = {}
        for outcome in outcomes:
            associations[sample_name][outcome] = {}
            for coordinate, feature, control in (
                ("A", "A_trend_direction", None),
                ("B", "B_breadth_discovery", None),
                ("A_given_B", "A_trend_direction", "B_breadth_discovery"),
                ("B_given_A", "B_breadth_discovery", "A_trend_direction"),
            ):
                result = association_diagnostics(
                    frame,
                    feature,
                    outcome,
                    f"{sample_name}:{outcome}:{coordinate}",
                    control,
                )
                associations[sample_name][outcome][coordinate] = result
                if coordinate in {"A", "B"} and result["gate_pass"]:
                    passing.append(
                        {"sample": sample_name, "endpoint": outcome, "coordinate": coordinate, "role": role}
                    )
            nested_result = nested_model_diagnostics(frame, outcome, f"{sample_name}:{outcome}")
            nested[sample_name][outcome] = nested_result
            if nested_result["gate_pass"]:
                synergy.append(f"{sample_name}:{outcome}")
            sensitivity[sample_name][outcome] = association_diagnostics(
                frame,
                "B_breadth_discovery_non_st",
                outcome,
                f"{sample_name}:{outcome}:B_NON_ST",
            )
    return associations, nested, sensitivity, passing, synergy


def secondary_coordinate_diagnostics(
    daily: pd.DataFrame, events: pd.DataFrame, cycles: pd.DataFrame
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for sample_name, (frame, outcomes, _) in _analysis_samples(daily, events, cycles).items():
        output[sample_name] = {}
        for outcome in outcomes:
            output[sample_name][outcome] = {}
            for label, feature in (
                ("A_pit_3y", "A_trend_pit_3y_pct"),
                ("B_pit_3y", "B_breadth_pit_3y_pct"),
                ("B_relative_to_all", "B_breadth_relative_to_all"),
            ):
                rows = frame[[feature, outcome]].replace([np.inf, -np.inf], np.nan).dropna()
                output[sample_name][outcome][label] = {
                    "n": len(rows),
                    "rho": _correlation(rows[feature].to_numpy(float), rows[outcome].to_numpy(float)),
                }
    return output


def build_panel(daily: pd.DataFrame, events: pd.DataFrame, cycles: pd.DataFrame) -> pd.DataFrame:
    common = [
        "A_trend_direction",
        "A_trend_pit_3y_pct",
        "B_breadth_discovery",
        "B_breadth_pit_3y_pct",
        "B_breadth_relative_to_all",
        "B_breadth_discovery_non_st",
        "state_cell",
        "calendar_year",
        "temporal_block",
        "snapshot_id_trend",
        "snapshot_id_breadth",
    ]
    daily_panel = daily[["trade_date", *common, "evaluated_count", "candidate_count", "selected_count"]].copy()
    daily_panel["sample_type"] = "DAILY_PROCESS"
    event_panel = events[
        [
            "trade_date",
            *common,
            "baseline_block",
            "symbol",
            "admissible_candidate",
            "selected_admission",
            "source_event_ledger_sha256",
        ]
    ].copy()
    event_panel["sample_type"] = "EVALUATED_EVENT"
    trade_panel = cycles[
        [
            "entry_signal_date",
            *common,
            "baseline_block",
            "symbol",
            "trade_id",
            "entry_execution_date",
            "exit_signal_date",
            "exit_execution_date",
            "round_trip_return",
            "realized_pnl",
            "mfe",
            "mae",
            "winner20",
            "winner50",
            "severe_loss10",
            "extreme_loss20",
            "false_breakout",
            "opportunity20",
            "conversion20",
            "giveback_from_peak",
            "source_event_ledger_sha256",
        ]
    ].copy().rename(columns={"entry_signal_date": "trade_date"})
    trade_panel["sample_type"] = "COMPLETED_CYCLE"
    panel = pd.concat([daily_panel, event_panel, trade_panel], ignore_index=True, sort=False)
    panel = panel.sort_values(["trade_date", "sample_type", "symbol"], na_position="first").reset_index(drop=True)
    return panel


def _format_number(value: Any, percent: bool = False) -> str:
    if value is None or not math.isfinite(float(value)):
        return "NA"
    return f"{float(value):.2%}" if percent else f"{float(value):.3f}"


def _report(result: dict[str, Any]) -> str:
    lines = [
        "# HAB-CHX-001 CHINEXT V1 market-habitat association",
        "",
        f"Decision: `{result['decision']}`.",
        "",
        "This is exploratory association using already-consumed outcomes. It is not a causal mechanism, trading signal, habitat gate, or strategy authorization.",
        "",
        "## Population and PIT boundary",
        "",
        f"- Common valid completed-close market dates: {result['population']['market_dates']} ({result['population']['first_date']}..{result['population']['last_date']}).",
        f"- Evaluated events / candidates / selected admissions / completed cycles: {result['population']['evaluated_events']} / {result['population']['admissible_candidates']} / {result['population']['selected_admissions']} / {result['population']['completed_cycles']}.",
        "- Every completed cycle entered strictly after its signal-date close; all selected additions reconcile one-to-one.",
        "- 2024-2025 is absent because the frozen state panels end in 2023. No proxy or backfill was used.",
        "- A zero daily opportunity count is the observed V1 engine process, not pure latent-pattern incidence; exit-branch suppression and no qualifying structure are not separable in the event ledger.",
        "",
        "## Frozen-coordinate continuous evidence",
        "",
        "| Sample | Endpoint | Coordinate | N | Rho | 90% cluster CI | Early | Late | Same-sign years | Gate |",
        "|---|---|---|---:|---:|---|---:|---:|---:|---|",
    ]
    for sample, endpoints in result["associations"].items():
        for endpoint, coordinates in endpoints.items():
            for coordinate in ("A", "B", "A_given_B", "B_given_A"):
                row = coordinates[coordinate]
                interval = row["bootstrap_90pct"]
                lines.append(
                    f"| {sample} | {endpoint} | {coordinate} | {row['n']} | {_format_number(row['rho'])} | "
                    f"[{_format_number(interval[0])}, {_format_number(interval[1])}] | "
                    f"{_format_number(row['temporal_blocks']['EARLY']['rho'])} | "
                    f"{_format_number(row['temporal_blocks']['LATE']['rho'])} | "
                    f"{row['same_sign_year_count']}/{row['eligible_year_count']} | "
                    f"{'PASS' if row['gate_pass'] else 'FAIL'} |"
                )
    lines += [
        "",
        "A is the absolute 60-session CHINEXT-index log direction. B is the absolute CHINEXT-board net new-high/new-low fraction. Partial rows residualize ranked coordinate and endpoint on the other ranked coordinate. They are not additional mechanisms.",
        "",
        "## BASELINE / A / B / A+B",
        "",
        "| Sample | Endpoint | Adj-R2 A | Adj-R2 B | Adj-R2 A+B | Increment | Interaction 90% CI | Gate |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for sample, endpoints in result["nested_models"].items():
        for endpoint, row in endpoints.items():
            full = row["full"]
            interval = row["interaction_bootstrap_90pct"]
            lines.append(
                f"| {sample} | {endpoint} | {_format_number(full['A']['adjusted_r_squared'])} | "
                f"{_format_number(full['B']['adjusted_r_squared'])} | {_format_number(full['A+B']['adjusted_r_squared'])} | "
                f"{_format_number(row['A_plus_B_adjusted_r2_increment_over_best_single'])} | "
                f"[{_format_number(interval[0])}, {_format_number(interval[1])}] | "
                f"{'PASS' if row['gate_pass'] else 'FAIL'} |"
            )
    lines += [
        "",
        "The nested OLS/LPM comparison is a fixed association diagnostic, not an executable fitted predictor. No failed model is rescued by a new boundary or link function.",
        "",
        "## Interpretation",
        "",
        "Direction and discovery each have stable positive association with evaluated, candidate, and selected counts. Their partial-rank associations remain positive for evaluated and candidate counts. The fixed A+B interaction passes only for those two daily formation counts; it fails selected counts and every payoff endpoint.",
        "",
        "Conditional on an evaluated event or admissible candidate, selected-admission rates fall as state strength rises. This is consistent with opportunity density meeting a finite-vacancy, maximum-ten-position strategy architecture; it is not evidence that the market state rejects demand or that fewer admissions would improve returns. The breadth selection-rate association does not survive the strict B-given-A gate.",
        "",
        "Payoff separation is narrow. Higher direction associates with more-negative MAE (A rho -0.198; A-given-B rho -0.158), so it is not a defensive habitat result. Discovery breadth associates with MFE>=20% opportunity (B rho 0.190), but its B-given-A gate and the conversion20 gate fail. No absolute primary gate passes for completed-cycle return, winner20, winner50, false breakout, severe loss, extreme loss, or within-opportunity conversion. Opportunity incidence is not harvested-edge evidence.",
        "",
        "## Fixed economic sign cells",
        "",
        "| Cell | Dates | Events | Candidates/event | Selected/event | Cycles | Mean return | Winner20 | False breakout | Severe loss |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cell in ("NEITHER", "A_ONLY", "B_ONLY", "A_AND_B"):
        row = result["diagnostic_cells"][cell]
        cycle_label = str(row["completed_cycles"])
        if not row["adequate_completed_cycles"]:
            cycle_label += " INSUFFICIENT"
        lines.append(
            f"| {cell} | {row['market_dates']} | {row['evaluated_events']} | "
            f"{_format_number(row['candidate_rate_among_events'], True)} | "
            f"{_format_number(row['selected_rate_among_events'], True)} | {cycle_label} | "
            f"{_format_number(row['round_trip_return_mean'], True)} | "
            f"{_format_number(row['winner20_rate'], True)} | "
            f"{_format_number(row['false_breakout_rate'], True)} | "
            f"{_format_number(row['severe_loss10_rate'], True)} |"
        )
    lines += [
        "",
        "These cells use the predeclared zero boundaries for economic legibility only. A_ONLY has fewer than 20 cycles and is explicitly insufficient. MKT-GEO-001 already warned that the discovery-zero boundary is occupancy-imbalanced; no cell is an action rule. B_ONLY's positive mean is paired with 0.994 top-20 positive-PnL concentration, so it is not broad payoff support.",
        "",
        "## Breadth denominator sensitivity",
        "",
        "The NON_ST breadth coordinate is reported only as a neighboring-denominator sensitivity. It cannot replace the ALL_STATUS primary. Full results are preserved in the JSON artifact.",
        "",
        "## Matrix completeness and limitations",
        "",
        "Observed opportunity generation, admission conversion, completed-cycle return, right-tail, and severe-failure behavior are measurable. Habitat-specific counterfactual NAV, drawdown, turnover, execution-cost impact, and capacity are not identified by this zero-replay association and remain unpopulated. Positive-PnL concentration is descriptive and the strategy remains right-tail dependent.",
        "",
        "The two state coordinates may describe association but cannot prove that changing exposure or admission would improve results. Existing outcomes are fully consumed; independent future time is still required for confirmation.",
        "",
        "## Synthesis checkpoint",
        "",
        "**What market behavior are we still not studying?** Recurring correlation/liquidity shock recovery, non-slope intraday transitions, action-safe support/acceptance, accumulation/distribution falsification, and multi-strategy habitat portability remain open.",
        "",
        "**Has any discovered mechanism implied a genuinely new strategy archetype?** No. This experiment concerns one existing breakout seed and has no new trigger, veto, exit, recurring opportunity process independent of V1, or validated capacity profile.",
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`.",
        f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`.",
        f"- Result evidence uses {BOOTSTRAP_REPETITIONS} deterministic cluster resamples with seed {BOOTSTRAP_SEED}.",
    ]
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise HabitatError("HAB-CHX-001 spec hash mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_MARKET_STATE_OUTCOME_JOIN":
        raise HabitatError("HAB-CHX-001 spec is not frozen")
    state = load_market_state(spec)
    events, daily = load_strategy_process(spec, state)
    cycles = load_completed_cycles(spec, state, events)
    associations, nested, sensitivity, passing, synergy = run_analyses(daily, events, cycles)
    panel = build_panel(daily, events, cycles)
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False, float_format="%.12g", date_format="%Y-%m-%d")

    passed_roles = sorted({item["role"] for item in passing})
    if {"opportunity_process", "payoff"}.issubset(passed_roles):
        decision = "EXPLORATORY_OPPORTUNITY_AND_PAYOFF_HABITAT_ASSOCIATION"
    elif "opportunity_process" in passed_roles:
        decision = "EXPLORATORY_OPPORTUNITY_PROCESS_ASSOCIATION_ONLY"
    elif "payoff" in passed_roles:
        decision = "EXPLORATORY_PAYOFF_ASSOCIATION_ONLY"
    else:
        decision = "NO_STABLE_HABITAT_ASSOCIATION"

    result = {
        "experiment_id": "HAB-CHX-001",
        "decision": decision,
        "evidence_grade": spec["evidence_grade"],
        "strategy_rule_authorized": False,
        "new_strategy_archetype_authorized": False,
        "outcome_fields_read": [
            "round_trip_return",
            "realized_pnl",
            "mfe",
            "mae",
            "giveback_from_peak",
        ],
        "population": {
            "market_dates": len(daily),
            "first_date": daily.trade_date.min().date().isoformat(),
            "last_date": daily.trade_date.max().date().isoformat(),
            "evaluated_events": len(events),
            "admissible_candidates": int(events.admissible_candidate.sum()),
            "selected_admissions": int(events.selected_admission.sum()),
            "completed_cycles": len(cycles),
            "same_or_earlier_entry_fills": int(cycles.entry_execution_date.le(cycles.entry_signal_date).sum()),
        },
        "associations": associations,
        "passing_primary_associations": passing,
        "nested_models": nested,
        "passing_A_plus_B_synergies": synergy,
        "breadth_non_st_sensitivity": sensitivity,
        "secondary_coordinates": secondary_coordinate_diagnostics(daily, events, cycles),
        "diagnostic_cells": summarize_cells(daily, events, cycles),
        "temporal_payoff_summary": summarize_temporal(cycles),
        "limitations": {
            "causality": "NOT_ESTABLISHED",
            "untouched_oos": "NONE",
            "zero_day_latent_opportunity": "NOT_IDENTIFIED",
            "habitat_specific_nav_drawdown_turnover_capacity": "NOT_IDENTIFIED_ZERO_REPLAY",
            "post_2023": "UNAVAILABLE_EXCLUDED",
            "cy011": "UNOPENED",
        },
        "interpretation": {
            "opportunity_process": "A and B associate with daily formation counts; A+B incrementality is limited to evaluated/candidate counts.",
            "capacity_pressure": "Selected rate falls when opportunity density rises; finite vacancies/max-ten architecture prevents interpreting the rate as market rejection or counterfactual benefit.",
            "payoff": "A associates with more-negative MAE. B associates with MFE>=20% opportunity, but not incrementally after A under the fixed gate; conversion and final-return/right-tail/failure primaries fail.",
            "A_plus_B_payoff_synergy": "NONE",
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "panel_sha256": sha256_file(PANEL_PATH),
            "trend_panel_sha256": spec["inputs"]["trend_panel"]["sha256"],
            "breadth_panel_sha256": spec["inputs"]["breadth_panel"]["sha256"],
            "completed_cycles_sha256": spec["inputs"]["completed_cycles"]["sha256"],
        },
        "checkpoint_questions": {
            "what_market_behavior_is_still_unstudied": [
                "correlation/liquidity shock recovery",
                "non-slope market intraday transitions",
                "action-safe support and breakout acceptance",
                "accumulation/distribution falsification",
                "multi-strategy habitat portability",
            ],
            "new_strategy_archetype_implied": False,
        },
    }
    RESULT_PATH.write_text(json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_report(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    result = run()
    print(
        json.dumps(
            {
                "decision": result["decision"],
                "population": result["population"],
                "passing_primary_associations": result["passing_primary_associations"],
                "passing_A_plus_B_synergies": result["passing_A_plus_B_synergies"],
                "hashes": result["hashes"],
            },
            indent=2,
            sort_keys=True,
        )
    )
