#!/usr/bin/env python3
"""Execute the frozen objective-recovery temporal dynamics experiment."""

from __future__ import annotations

import gc
import hashlib
import importlib.util
import json
import math
import time
import warnings
from collections.abc import Iterable
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-SUPPORT-DYN-001_spec.json"
SESSION_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-001_session_panel.csv"
TRAJECTORY_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-001_trajectory_panel.csv"
TRANSITION_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-001_transition_audit.csv"
STABILITY_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-001_stability_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-SUPPORT-DYN-001_dynamics.md"
EXPECTED_SPEC_SHA256 = "2abeaff258a7f9a42fd98423e574dd90c5e4263ce494cb04bcee9a18992eeef0"

warnings.filterwarnings(
    "ignore",
    message="Downcasting object dtype arrays on .fillna.*",
    category=FutureWarning,
)


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


data004 = _load_module(
    "run_mkt_support_dyn_data_004_for_dynamics",
    PROGRAM / "scripts/run_mkt_support_dyn_data_004.py",
)
support001 = data004.retry003.parent.support001
adapter = data004.retry003.parent.adapter
sha256_file = data004.sha256_file


class SupportDynamicsError(RuntimeError):
    """Fail-closed MKT-SUPPORT-DYN-001 error."""


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, tuple):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _load_spec() -> tuple[dict[str, Any], dict[str, Any]]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise SupportDynamicsError("temporal dynamics spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_TEMPORAL_ESTIMATES" or spec["outcome_access"]:
        raise SupportDynamicsError("temporal dynamics activation changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise SupportDynamicsError(f"bound input identity mismatch: {name}")
    data_spec = data004._load_spec()
    data_result = json.loads(
        _resolve(spec["inputs"]["data004_result"]["path"]).read_text(encoding="utf-8")
    )
    geometry = json.loads(
        _resolve(spec["inputs"]["geometry_result"]["path"]).read_text(encoding="utf-8")
    )
    if (
        data_result["status"] != "COMPLETE_SAMPLE_ADEQUACY_PASS"
        or data_result["process_estimates_constructed"]
        or data_result["cy011_read"]
        or geometry["direct_roles"] != ["recovery_speed", "recovery_volume_intensity"]
    ):
        raise SupportDynamicsError("parent evidence activation changed")
    return spec, data_spec


def _resource_guard(spec: dict[str, Any], started: float) -> None:
    budget = spec["resource_budget"]
    if psutil.virtual_memory().available < budget["system_memory_headroom_floor_gib"] * 2**30:
        raise SupportDynamicsError("system memory headroom floor breached")
    if adapter._max_rss_bytes() > budget["peak_rss_ceiling_gib"] * 2**30:
        raise SupportDynamicsError("process RSS ceiling breached")
    if time.monotonic() - started > budget["wall_clock_ceiling_minutes"] * 60:
        raise SupportDynamicsError("wall-clock ceiling breached")


def _spearman(left: Iterable[float], right: Iterable[float]) -> float:
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(frame) < 3 or frame["left"].nunique() < 2 or frame["right"].nunique() < 2:
        return np.nan
    return float(frame["left"].rank(method="average").corr(frame["right"].rank(method="average")))


def _sign(value: float) -> int:
    if not np.isfinite(value) or value == 0:
        return 0
    return 1 if value > 0 else -1


def _sign_agreement(left: pd.Series, right: pd.Series) -> float:
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if frame.empty:
        return np.nan
    return float(np.mean(np.sign(frame["left"].to_numpy()) == np.sign(frame["right"].to_numpy())))


def _temporal_operators(days: np.ndarray, values: np.ndarray) -> dict[str, float]:
    days = np.asarray(days, dtype=float)
    values = np.asarray(values, dtype=float)
    if (
        len(days) < 2
        or len(days) != len(values)
        or not np.isfinite(days).all()
        or not np.isfinite(values).all()
        or not np.all(np.diff(days) > 0)
    ):
        return {"endpoint_rate": np.nan, "ols_slope": np.nan, "theil_sen_slope": np.nan}
    endpoint = float((values[-1] - values[0]) / (days[-1] - days[0]))
    centered_days = days - days.mean()
    centered_values = values - values.mean()
    denominator = float(np.dot(centered_days, centered_days))
    ols = float(np.dot(centered_days, centered_values) / denominator)
    pairwise = [
        float((values[j] - values[i]) / (days[j] - days[i]))
        for i in range(len(days) - 1)
        for j in range(i + 1, len(days))
    ]
    return {
        "endpoint_rate": endpoint,
        "ols_slope": ols,
        "theil_sen_slope": float(np.median(pairwise)),
    }


def _session_features(rows: pd.DataFrame, level: float, include_auction: bool) -> dict[str, Any]:
    selected = rows if include_auction else rows.iloc[1:]
    expected = 241 if include_auction else 240
    if len(selected) != expected:
        raise SupportDynamicsError("session grid length changed")
    descriptor = support001._session_descriptor(rows, level, include_auction)
    opens = selected["mapped_open"].to_numpy(dtype=float)
    highs = selected["mapped_high"].to_numpy(dtype=float)
    lows = selected["mapped_low"].to_numpy(dtype=float)
    closes = selected["mapped_close"].to_numpy(dtype=float)
    volumes = selected["volume"].to_numpy(dtype=float)
    if (
        not np.isfinite(opens).all()
        or not np.isfinite(highs).all()
        or not np.isfinite(lows).all()
        or not np.isfinite(closes).all()
        or not np.isfinite(volumes).all()
        or (volumes < 0).any()
        or float(volumes.sum()) <= 0
    ):
        raise SupportDynamicsError("generic session input invalid")
    tested_indices = np.flatnonzero(lows <= level)
    first_test = int(tested_indices[0]) if len(tested_indices) else None
    total_volume = float(volumes.sum())
    shares = volumes / total_volume
    price_range = float(highs.max() - lows.min())
    output = dict(descriptor)
    output.update(
        {
            "first_test_position": (
                np.nan if first_test is None else float(first_test / (expected - 1))
            ),
            "time_of_low": float(int(np.argmin(lows)) / (expected - 1)),
            "close_location": (
                np.nan if price_range == 0 else float((closes[-1] - lows.min()) / price_range)
            ),
            "open_to_close_return": float(closes[-1] / opens[0] - 1.0),
            "minute_realized_volatility": float(
                math.sqrt(float(np.square(np.diff(np.log(closes))).sum()))
            ),
            "volume_herfindahl": float(np.square(shares).sum()),
            "opening_30_volume_share": float(volumes[:30].sum() / total_volume),
            "closing_30_volume_share": float(volumes[-30:].sum() / total_volume),
        }
    )
    return output


def _manual_session_descriptor(
    rows: pd.DataFrame, level: float, include_auction: bool
) -> dict[str, Any]:
    selected = (
        rows.reset_index(drop=True) if include_auction else rows.iloc[1:].reset_index(drop=True)
    )
    lows = [float(value) for value in selected["mapped_low"]]
    closes = [float(value) for value in selected["mapped_close"]]
    volumes = [float(value) for value in selected["volume"]]
    tested = [index for index, value in enumerate(lows) if value <= level]
    output: dict[str, Any] = {
        "tested": bool(tested),
        "recovery_completion": np.nan,
        "recovery_speed": np.nan,
        "recovery_volume_intensity": np.nan,
    }
    if not tested:
        return output
    first = tested[0]
    recovery = next((index for index in range(first, len(closes)) if closes[index] >= level), None)
    output["recovery_completion"] = recovery is not None
    if recovery is not None:
        span_volume = sum(volumes[first : recovery + 1])
        output["recovery_speed"] = recovery - first
        output["recovery_volume_intensity"] = (span_volume / sum(volumes)) / (
            (recovery - first + 1) / len(volumes)
        )
    return output


def _case_hash(sequence_id: str) -> str:
    return hashlib.sha256(f"MKT-SUPPORT-DYN-001|{sequence_id}".encode()).hexdigest()


def _load_parent_frames(spec: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sample = pd.read_csv(
        _resolve(spec["inputs"]["data004_sample"]["path"]),
        dtype={"symbol": str, "source_symbol": str},
    )
    coordinate = pd.read_csv(
        _resolve(spec["inputs"]["data004_coordinate_audit"]["path"]),
        dtype={"symbol": str, "source_symbol": str},
        float_precision="round_trip",
    )
    counts = pd.read_csv(
        _resolve(spec["inputs"]["data004_support_count_audit"]["path"]),
        dtype={"symbol": str},
    )
    for frame in (sample, coordinate):
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    expected = spec["sample"]
    if (
        len(sample) != expected["exact_cohort_rows"]
        or sample["sequence_id"].nunique() != expected["exact_sequences"]
        or len(sample[["symbol", "trade_date"]].drop_duplicates())
        != expected["exact_unique_security_sessions"]
        or len(coordinate) != expected["exact_cohort_rows"]
        or len(counts) != expected["exact_sequences"]
    ):
        raise SupportDynamicsError("bound sample population changed")
    return sample, coordinate, counts


def _read_session_panel(
    spec: dict[str, Any],
    data_spec: dict[str, Any],
    sample: pd.DataFrame,
    coordinate: pd.DataFrame,
    selected_cases: set[str],
    started: float,
    verify_partition_content: bool,
) -> tuple[pd.DataFrame, dict[tuple[str, pd.Timestamp], pd.DataFrame], int]:
    parent = data004.retry003.parent
    data_contract = parent.data003.parent.parent
    base = data_spec["_base_data_spec"]
    data_contract._verify_registry_assets(base)
    partitions = data_contract.bind_partitions(base, verify_content=verify_partition_content)
    coordinate_unique = coordinate.sort_values("audit_id").drop_duplicates(["symbol", "trade_date"])
    if len(coordinate_unique) != spec["sample"]["exact_unique_security_sessions"]:
        raise SupportDynamicsError("coordinate physical-session population changed")
    records: list[dict[str, Any]] = []
    manual_raw: dict[tuple[str, pd.Timestamp], pd.DataFrame] = {}
    raw_row_count = 0
    for (raw_year, raw_block), batch in coordinate_unique.groupby(
        ["target_year", "block_id"], sort=True
    ):
        _resource_guard(spec, started)
        year = int(raw_year)
        block_id = int(raw_block)
        targets = batch[["symbol", "source_symbol", "trade_date"]].drop_duplicates()
        table = adapter.read_raw_table(
            partitions["qd004"][f"bars/{year}_day_parquet_none.parquet"],
            pd.to_datetime(targets["trade_date"]).dt.date,
            targets["source_symbol"].astype(str),
        )
        adapter.vectorized_session_descriptors(table)
        raw_row_count += int(table.num_rows)
        raw = table.to_pandas()
        raw["trade_date"] = pd.to_datetime(raw["trade_date"], errors="raise")
        raw["symbol"] = raw["symbol"].astype(str).str.zfill(6) + "." + raw["exchange"].astype(str)
        raw = raw.merge(
            targets[["symbol", "trade_date"]],
            on=["symbol", "trade_date"],
            validate="many_to_one",
        )
        if raw.groupby(["symbol", "trade_date"]).ngroups != len(targets):
            raise SupportDynamicsError(f"raw block coverage changed: {year}:{block_id}")
        validation_coordinate = batch.rename(columns={"daily_snapshot_id": "snapshot_id"})
        parent.data003._read_and_validate_cy008(year, targets, validation_coordinate, partitions)
        coordinate_index = batch.set_index(["symbol", "trade_date"])
        for (symbol, trade_date), rows in raw.groupby(["symbol", "trade_date"], sort=True):
            rows = rows.sort_values("bar_end_time").reset_index(drop=True)
            if len(rows) != 241:
                raise SupportDynamicsError(f"minute grid changed: {symbol}:{trade_date}")
            daily = coordinate_index.loc[(symbol, pd.Timestamp(trade_date))]
            if isinstance(daily, pd.DataFrame):
                daily = daily.iloc[0]
            raw_ohlc = rows[["open", "high", "low", "close"]].to_numpy(dtype=float)
            scale = float(daily.coordinate_scale)
            mapped = raw_ohlc * scale
            if not np.isfinite(mapped).all() or not (mapped > 0).all():
                raise SupportDynamicsError(f"mapped minute OHLC invalid: {symbol}:{trade_date}")
            rows = rows.copy()
            for index, field in enumerate(["open", "high", "low", "close"]):
                rows[f"mapped_{field}"] = mapped[:, index]
            record: dict[str, Any] = {
                "symbol": str(symbol),
                "trade_date": pd.Timestamp(trade_date),
            }
            for horizon in [10, 20, 40]:
                level = float(daily[f"support_low{horizon}"])
                for path_name, include_auction in [("cont", False), ("auction", True)]:
                    features = _session_features(rows, level, include_auction)
                    for field, value in features.items():
                        record[f"h{horizon}_{path_name}_{field}"] = value
            records.append(record)
            case_ids = sample.loc[
                sample["symbol"].eq(symbol)
                & sample["trade_date"].eq(pd.Timestamp(trade_date))
                & sample["sequence_id"].isin(selected_cases),
                "sequence_id",
            ]
            for sequence_id in case_ids:
                manual_raw[(str(sequence_id), pd.Timestamp(trade_date))] = rows.copy()
        del raw, table
        gc.collect()
        _resource_guard(spec, started)
    descriptors = pd.DataFrame(records)
    if len(descriptors) != spec["sample"]["exact_unique_security_sessions"]:
        raise SupportDynamicsError("descriptor physical-session population changed")
    panel = sample.merge(descriptors, on=["symbol", "trade_date"], validate="many_to_one")
    if len(panel) != spec["sample"]["exact_cohort_rows"]:
        raise SupportDynamicsError("descriptor cohort population changed")
    expected = coordinate[
        [
            "audit_id",
            "primary_level_tested",
            "primary_recovery_completion",
            "primary_recovery_speed",
            "primary_recovery_volume_intensity",
        ]
    ].merge(
        panel[
            [
                "audit_id",
                "h20_cont_tested",
                "h20_cont_recovery_completion",
                "h20_cont_recovery_speed",
                "h20_cont_recovery_volume_intensity",
            ]
        ],
        on="audit_id",
        validate="one_to_one",
    )
    comparisons = [
        ("primary_level_tested", "h20_cont_tested"),
        ("primary_recovery_completion", "h20_cont_recovery_completion"),
        ("primary_recovery_speed", "h20_cont_recovery_speed"),
        ("primary_recovery_volume_intensity", "h20_cont_recovery_volume_intensity"),
    ]
    for left, right in comparisons:
        equal = expected[left].eq(expected[right]) | (
            expected[left].isna() & expected[right].isna()
        )
        if not bool(equal.all()):
            first = expected.loc[~equal, ["audit_id", left, right]].iloc[0]
            raise SupportDynamicsError(
                f"parent descriptor disagreement: {left}:count={int((~equal).sum())}:"
                f"{first.audit_id}:{first[left]!r}!={first[right]!r}"
            )
    return panel.sort_values("audit_id").reset_index(drop=True), manual_raw, raw_row_count


CONTROL_FIELDS = [
    "first_test_position",
    "time_of_low",
    "close_location",
    "open_to_close_return",
    "minute_realized_volatility",
    "volume_herfindahl",
    "opening_30_volume_share",
    "closing_30_volume_share",
    "signed_test_geometry",
    "closing_level_state",
]


def _build_trajectory_and_transition(
    panel: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    trajectory_records: list[dict[str, Any]] = []
    transition_records: list[dict[str, Any]] = []
    identity = [
        "sequence_id",
        "target_year",
        "block_id",
        "market_view",
        "market_sequence_rank",
        "symbol",
    ]
    for key, rows in panel.groupby(identity, sort=True):
        rows = rows.sort_values("relative_day")
        if len(rows) != 5 or rows["relative_day"].tolist() != [-5, -4, -3, -2, -1]:
            raise SupportDynamicsError(f"sequence conservation changed: {key[0]}")
        record = dict(zip(identity, key, strict=True))
        for horizon in [10, 20, 40]:
            for path_name in ["cont", "auction"]:
                prefix = f"h{horizon}_{path_name}"
                tested = rows[f"{prefix}_tested"].astype(bool)
                recovered = (
                    tested
                    & rows[f"{prefix}_recovery_completion"].fillna(False).astype(bool)
                    & rows[f"{prefix}_recovery_speed"].notna()
                    & rows[f"{prefix}_recovery_volume_intensity"].notna()
                )
                eligible = rows.loc[recovered]
                record[f"{prefix}_tested_days"] = int(tested.sum())
                record[f"{prefix}_recovered_days"] = len(eligible)
                if len(eligible) >= 2:
                    days = eligible["relative_day"].to_numpy(dtype=float)
                    for field in ["recovery_speed", "recovery_volume_intensity"]:
                        operators = _temporal_operators(
                            days, eligible[f"{prefix}_{field}"].to_numpy(dtype=float)
                        )
                        for operator, value in operators.items():
                            record[f"{prefix}_{field}_{operator}"] = value
                    for field in CONTROL_FIELDS:
                        operators = _temporal_operators(
                            days, eligible[f"{prefix}_{field}"].to_numpy(dtype=float)
                        )
                        record[f"{prefix}_{field}_endpoint_rate"] = operators["endpoint_rate"]
                tested_rows = rows.loc[tested]
                transition: dict[str, Any] = {
                    **dict(zip(identity, key, strict=True)),
                    "level_horizon": horizon,
                    "path": path_name,
                    "tested_day_count": len(tested_rows),
                    "first_state": None,
                    "last_state": None,
                    "transition_category": None,
                    "adjacent_R_R": 0,
                    "adjacent_R_F": 0,
                    "adjacent_F_R": 0,
                    "adjacent_F_F": 0,
                }
                if len(tested_rows) >= 2:
                    states = [
                        "R" if bool(value) else "F"
                        for value in tested_rows[f"{prefix}_recovery_completion"].fillna(False)
                    ]
                    transition["first_state"] = states[0]
                    transition["last_state"] = states[-1]
                    transition["transition_category"] = f"{states[0]}_TO_{states[-1]}"
                    for current, following in pairwise(states):
                        transition[f"adjacent_{current}_{following}"] += 1
                transition_records.append(transition)
        trajectory_records.append(record)
    trajectory = pd.DataFrame(trajectory_records).sort_values("sequence_id").reset_index(drop=True)
    transitions = (
        pd.DataFrame(transition_records)
        .sort_values(["sequence_id", "level_horizon", "path"])
        .reset_index(drop=True)
    )
    if len(trajectory) != 1920 or len(transitions) != 1920 * 6:
        raise SupportDynamicsError("trajectory/transition population changed")
    return trajectory, transitions


def _block_mask(frame: pd.DataFrame, name: str) -> pd.Series:
    years = [2018, 2019, 2020] if name == "A" else [2021, 2022, 2023]
    return frame["target_year"].isin(years)


def _rank_adjusted_r2(frame: pd.DataFrame, target: str, controls: list[str]) -> float:
    complete = frame[[target, *controls]].dropna()
    n = len(complete)
    p = len(controls)
    if n <= p + 1 or complete[target].nunique() < 2:
        return np.nan
    ranked = complete.rank(method="average")
    y = ranked[target].to_numpy(dtype=float)
    x = np.column_stack([np.ones(n), *(ranked[field].to_numpy(dtype=float) for field in controls)])
    fitted = x @ np.linalg.lstsq(x, y, rcond=None)[0]
    sst = float(np.square(y - y.mean()).sum())
    if sst == 0:
        return np.nan
    r2 = 1.0 - float(np.square(y - fitted).sum()) / sst
    return float(1.0 - (1.0 - r2) * (n - 1) / (n - p - 1))


def _pair_stats(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any]:
    joint = frame[[left, right]].dropna()
    return {
        "n": len(joint),
        "spearman": _spearman(joint[left], joint[right]),
        "sign_agreement": _sign_agreement(joint[left], joint[right]),
    }


def _evaluate_role(
    spec: dict[str, Any], trajectory: pd.DataFrame, role: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    gates = spec["representation_gates"]
    target = role.removesuffix("_progression")
    primary = f"h20_cont_{target}_endpoint_rate"
    eligible = trajectory.loc[trajectory[primary].notna()].copy()
    checks: dict[str, bool] = {}
    rows: list[dict[str, Any]] = []
    expected_year = spec["sample"]["primary_recovered_by_year"]
    expected_block = spec["sample"]["primary_recovered_by_block"]
    year_counts = eligible.groupby("target_year").size()
    block_counts = {name: int(_block_mask(eligible, name).sum()) for name in ["A", "B"]}
    checks["exact_primary_population"] = (
        len(eligible) == spec["sample"]["primary_recovered_sequences"]
        and block_counts == expected_block
        and all(
            int(year_counts.get(int(year), 0)) == count for year, count in expected_year.items()
        )
    )
    shape: dict[str, Any] = {}
    shape_passes: list[bool] = []
    for operator in ["ols_slope", "theil_sen_slope"]:
        neighbor = f"h20_cont_{target}_{operator}"
        stats = {"global": _pair_stats(eligible, primary, neighbor)}
        for block in ["A", "B"]:
            stats[block] = _pair_stats(
                eligible.loc[_block_mask(eligible, block)], primary, neighbor
            )
        passed = (
            stats["global"]["spearman"] >= gates["shape_global_spearman_minimum"]
            and stats["global"]["sign_agreement"] >= gates["shape_global_sign_agreement_minimum"]
            and all(
                stats[block]["spearman"] >= gates["shape_each_block_spearman_minimum"]
                and stats[block]["sign_agreement"]
                >= gates["shape_each_block_sign_agreement_minimum"]
                for block in ["A", "B"]
            )
        )
        stats["pass"] = bool(passed)
        shape[operator] = stats
        shape_passes.append(bool(passed))
        for domain in ["global", "A", "B"]:
            rows.append(
                {
                    "role": role,
                    "challenge": f"shape_{operator}",
                    "domain": domain,
                    **stats[domain],
                    "pass": passed,
                }
            )
    checks["shape"] = all(shape_passes)
    levels: dict[str, Any] = {}
    level_passes: list[bool] = []
    for horizon in [10, 40]:
        neighbor = f"h{horizon}_cont_{target}_endpoint_rate"
        stats = {"global": _pair_stats(trajectory, primary, neighbor)}
        for block in ["A", "B"]:
            stats[block] = _pair_stats(
                trajectory.loc[_block_mask(trajectory, block)], primary, neighbor
            )
        passed = (
            stats["global"]["n"] >= gates["level_neighbor_minimum_intersection_total"]
            and stats["global"]["spearman"] >= gates["level_neighbor_global_spearman_minimum"]
            and stats["global"]["sign_agreement"]
            >= gates["level_neighbor_global_sign_agreement_minimum"]
            and all(
                stats[block]["n"] >= gates["level_neighbor_minimum_intersection_each_block"]
                and stats[block]["spearman"] >= gates["level_neighbor_each_block_spearman_minimum"]
                for block in ["A", "B"]
            )
        )
        stats["pass"] = bool(passed)
        levels[str(horizon)] = stats
        level_passes.append(bool(passed))
        for domain in ["global", "A", "B"]:
            rows.append(
                {
                    "role": role,
                    "challenge": f"level_{horizon}",
                    "domain": domain,
                    **stats[domain],
                    "pass": passed,
                }
            )
    checks["level_neighbors"] = all(level_passes)
    auction = {"global": _pair_stats(trajectory, primary, f"h20_auction_{target}_endpoint_rate")}
    for block in ["A", "B"]:
        auction[block] = _pair_stats(
            trajectory.loc[_block_mask(trajectory, block)],
            primary,
            f"h20_auction_{target}_endpoint_rate",
        )
    auction_pass = (
        auction["global"]["n"] >= gates["auction_minimum_intersection_total"]
        and auction["global"]["spearman"] >= gates["auction_global_spearman_minimum"]
        and auction["global"]["sign_agreement"] >= gates["auction_global_sign_agreement_minimum"]
        and all(
            auction[block]["n"] >= gates["auction_minimum_intersection_each_block"]
            and auction[block]["spearman"] >= gates["auction_each_block_spearman_minimum"]
            for block in ["A", "B"]
        )
    )
    auction["pass"] = bool(auction_pass)
    checks["auction"] = bool(auction_pass)
    for domain in ["global", "A", "B"]:
        rows.append(
            {
                "role": role,
                "challenge": "auction",
                "domain": domain,
                **auction[domain],
                "pass": auction_pass,
            }
        )
    control_names = spec["fixed_generic_controls"][role]
    controls = [f"h20_cont_{name}_endpoint_rate" for name in control_names]
    external: dict[str, Any] = {}
    external_passes: list[bool] = []
    for domain, domain_frame in [
        ("global", eligible),
        ("A", eligible.loc[_block_mask(eligible, "A")]),
        ("B", eligible.loc[_block_mask(eligible, "B")]),
    ]:
        complete = domain_frame[[primary, *controls]].dropna()
        pairwise = {
            control: abs(_spearman(complete[primary], complete[control])) for control in controls
        }
        adjusted = _rank_adjusted_r2(complete, primary, controls)
        threshold = (
            gates["external_joint_adjusted_rank_r2_global_maximum_exclusive"]
            if domain == "global"
            else gates["external_joint_adjusted_rank_r2_each_block_maximum_exclusive"]
        )
        passed = (
            len(complete) == len(domain_frame)
            and all(
                value < gates["external_pairwise_absolute_spearman_maximum_exclusive"]
                for value in pairwise.values()
            )
            and np.isfinite(adjusted)
            and adjusted < threshold
        )
        external[domain] = {
            "n": len(complete),
            "pairwise_absolute_spearman": pairwise,
            "joint_adjusted_rank_r2": adjusted,
            "pass": bool(passed),
        }
        external_passes.append(bool(passed))
        rows.append(
            {
                "role": role,
                "challenge": "external_generic_controls",
                "domain": domain,
                "n": len(complete),
                "spearman": max(pairwise.values()) if pairwise else np.nan,
                "sign_agreement": np.nan,
                "joint_adjusted_rank_r2": adjusted,
                "pass": passed,
            }
        )
    checks["external_distinctness"] = all(external_passes)
    richer = trajectory.loc[trajectory["h20_cont_recovered_days"].ge(3)]
    richer_counts = {
        "total": len(richer),
        "by_block": {name: int(_block_mask(richer, name).sum()) for name in ["A", "B"]},
        "by_year": {
            str(year): int(richer["target_year"].eq(year).sum()) for year in range(2018, 2024)
        },
    }
    passed = all(checks.values())
    return (
        {
            "role": role,
            "target_field": target,
            "primary_n": len(eligible),
            "primary_by_block": block_counts,
            "primary_by_year": {
                str(year): int(year_counts.get(year, 0)) for year in range(2018, 2024)
            },
            "three_or_more_recovered_days": richer_counts,
            "shape": shape,
            "level_neighbors": levels,
            "auction": auction,
            "external": external,
            "checks": checks,
            "representation_pass": bool(passed),
        },
        rows,
    )


def _cluster_bootstrap_interval(
    frame: pd.DataFrame,
    value: str,
    statistic: str,
    resamples: int,
    seed: int,
) -> tuple[float, float]:
    clusters = sorted(
        frame[["target_year", "block_id"]].drop_duplicates().itertuples(index=False, name=None)
    )
    rng = np.random.default_rng(seed)
    estimates: list[float] = []
    grouped = {key: group for key, group in frame.groupby(["target_year", "block_id"], sort=True)}
    for _ in range(resamples):
        chosen = rng.choice(len(clusters), size=len(clusters), replace=True)
        sampled = pd.concat([grouped[clusters[int(index)]] for index in chosen], ignore_index=True)
        if statistic == "median":
            estimate = float(sampled[value].median())
        elif statistic == "risk_difference":
            estimate = _transition_risk_difference(sampled)
        else:
            raise SupportDynamicsError(f"unknown bootstrap statistic: {statistic}")
        if np.isfinite(estimate):
            estimates.append(estimate)
    if len(estimates) < int(0.95 * resamples):
        return np.nan, np.nan
    return tuple(float(item) for item in np.quantile(estimates, [0.025, 0.975]))


def _evaluate_direction(
    spec: dict[str, Any], trajectory: pd.DataFrame, role_result: dict[str, Any]
) -> dict[str, Any]:
    role = role_result["role"]
    field = f"h20_cont_{role_result['target_field']}_endpoint_rate"
    eligible = trajectory.loc[trajectory[field].notna()].copy()
    gates = spec["directional_process_gates"]
    blocks: dict[str, Any] = {}
    medians: dict[str, float] = {}
    for block in ["A", "B"]:
        block_frame = eligible.loc[_block_mask(eligible, block)]
        median = float(block_frame[field].median())
        direction = _sign(median)
        nonzero = block_frame.loc[block_frame[field].ne(0), field]
        fraction = (
            np.nan
            if nonzero.empty or direction == 0
            else float(np.mean(np.sign(nonzero) == direction))
        )
        interval = _cluster_bootstrap_interval(
            block_frame,
            field,
            "median",
            gates["calendar_block_bootstrap_resamples"],
            gates["calendar_block_bootstrap_seed"],
        )
        blocks[block] = {
            "n": len(block_frame),
            "median": median,
            "sign": direction,
            "nonzero_sign_fraction": fraction,
            "bootstrap_95_interval": interval,
            "interval_excludes_zero": bool(interval[0] > 0 or interval[1] < 0),
        }
        medians[block] = median
    common_sign = _sign(medians["A"])
    years = {
        str(year): float(eligible.loc[eligible["target_year"].eq(year), field].median())
        for year in range(2018, 2024)
    }
    years_same = (
        0 if common_sign == 0 else sum(_sign(value) == common_sign for value in years.values())
    )
    passed = (
        role_result["representation_pass"]
        and common_sign != 0
        and _sign(medians["B"]) == common_sign
        and all(
            blocks[block]["nonzero_sign_fraction"]
            >= gates["nonzero_sign_fraction_each_block_minimum"]
            and blocks[block]["interval_excludes_zero"]
            for block in ["A", "B"]
        )
        and years_same >= gates["minimum_year_medians_same_sign"]
    )
    return {
        "role": role,
        "blocks": blocks,
        "annual_medians": years,
        "years_same_sign": years_same,
        "directional_process_pass": bool(passed),
    }


def _rank_residual(frame: pd.DataFrame, target: str, controls: list[str]) -> pd.Series:
    complete = frame[[target, *controls]].dropna()
    output = pd.Series(np.nan, index=frame.index, dtype=float)
    if len(complete) <= len(controls) + 1 or complete[target].nunique() < 2:
        return output
    ranks = complete.rank(method="average")
    y = ranks[target].to_numpy(dtype=float)
    x = np.column_stack(
        [np.ones(len(complete)), *(ranks[field].to_numpy(dtype=float) for field in controls)]
    )
    output.loc[complete.index] = y - x @ np.linalg.lstsq(x, y, rcond=None)[0]
    return output


def _coupling_domain(frame: pd.DataFrame, spec: dict[str, Any], residual: bool) -> dict[str, Any]:
    speed = "h20_cont_recovery_speed_endpoint_rate"
    volume = "h20_cont_recovery_volume_intensity_endpoint_rate"
    if not residual:
        joint = frame[[speed, volume]].dropna()
        return {"n": len(joint), "spearman": _spearman(joint[speed], joint[volume])}
    speed_controls = [
        f"h20_cont_{field}_endpoint_rate"
        for field in spec["fixed_generic_controls"]["recovery_speed_progression"]
    ]
    volume_controls = [
        f"h20_cont_{field}_endpoint_rate"
        for field in spec["fixed_generic_controls"]["recovery_volume_intensity_progression"]
    ]
    working = frame.copy()
    working["_speed_residual"] = _rank_residual(working, speed, speed_controls)
    working["_volume_residual"] = _rank_residual(working, volume, volume_controls)
    joint = working[["_speed_residual", "_volume_residual"]].dropna()
    return {
        "n": len(joint),
        "spearman": _spearman(joint["_speed_residual"], joint["_volume_residual"]),
    }


def _evaluate_coupling(
    spec: dict[str, Any],
    trajectory: pd.DataFrame,
    roles: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    gates = spec["coupling_gates"]
    raw = {"global": _coupling_domain(trajectory, spec, False)}
    residual = {"global": _coupling_domain(trajectory, spec, True)}
    for block in ["A", "B"]:
        domain = trajectory.loc[_block_mask(trajectory, block)]
        raw[block] = _coupling_domain(domain, spec, False)
        residual[block] = _coupling_domain(domain, spec, True)
    raw_year = {
        str(year): _coupling_domain(
            trajectory.loc[trajectory["target_year"].eq(year)], spec, False
        )["spearman"]
        for year in range(2018, 2024)
    }
    residual_year = {
        str(year): _coupling_domain(trajectory.loc[trajectory["target_year"].eq(year)], spec, True)[
            "spearman"
        ]
        for year in range(2018, 2024)
    }
    shape: dict[str, Any] = {}
    for operator in ["ols_slope", "theil_sen_slope"]:
        left = f"h20_cont_recovery_speed_{operator}"
        right = f"h20_cont_recovery_volume_intensity_{operator}"
        shape[operator] = _pair_stats(trajectory, left, right)

    def base_pass(evidence: dict[str, Any], annual: dict[str, float]) -> bool:
        global_sign = _sign(evidence["global"]["spearman"])
        return bool(
            global_sign != 0
            and abs(evidence["global"]["spearman"]) >= gates["global_absolute_spearman_minimum"]
            and all(
                _sign(evidence[block]["spearman"]) == global_sign
                and abs(evidence[block]["spearman"])
                >= gates["each_block_absolute_spearman_minimum"]
                for block in ["A", "B"]
            )
            and sum(_sign(value) == global_sign for value in annual.values())
            >= gates["minimum_years_same_sign"]
        )

    raw_pass = base_pass(raw, raw_year)
    residual_pass = base_pass(residual, residual_year)
    raw_sign = _sign(raw["global"]["spearman"])
    shape_pass = all(
        _sign(item["spearman"]) == raw_sign
        and abs(item["spearman"]) >= gates["ols_and_theil_sen_global_absolute_spearman_minimum"]
        for item in shape.values()
    )
    role_pass = all(item["representation_pass"] for item in roles.values())
    return {
        "raw": raw,
        "raw_by_year": raw_year,
        "residual": residual,
        "residual_by_year": residual_year,
        "shape": shape,
        "individual_representations_pass": role_pass,
        "raw_gates_pass": raw_pass,
        "residual_gates_pass": residual_pass,
        "shape_gates_pass": shape_pass,
        "coupling_pass": bool(role_pass and raw_pass and residual_pass and shape_pass),
    }


def _transition_risk_difference(frame: pd.DataFrame) -> float:
    valid = frame.loc[frame["first_state"].isin(["R", "F"])]
    first_r = valid.loc[valid["first_state"].eq("R"), "last_state"]
    first_f = valid.loc[valid["first_state"].eq("F"), "last_state"]
    if first_r.empty or first_f.empty:
        return np.nan
    return float(first_r.eq("R").mean() - first_f.eq("R").mean())


def _adjacent_risk_difference(frame: pd.DataFrame) -> float:
    rr = int(frame["adjacent_R_R"].sum())
    rf = int(frame["adjacent_R_F"].sum())
    fr = int(frame["adjacent_F_R"].sum())
    ff = int(frame["adjacent_F_F"].sum())
    if rr + rf == 0 or fr + ff == 0:
        return np.nan
    return float(rr / (rr + rf) - fr / (fr + ff))


def _evaluate_transition(spec: dict[str, Any], transitions: pd.DataFrame) -> dict[str, Any]:
    gates = spec["transition_gates"]
    primary = transitions.loc[
        transitions["level_horizon"].eq(20)
        & transitions["path"].eq("cont")
        & transitions["transition_category"].notna()
    ].copy()
    if len(primary) != spec["sample"]["primary_repeated_test_sequences"]:
        raise SupportDynamicsError("primary transition population changed")
    arm_counts = primary["first_state"].value_counts()
    block_arms: dict[str, dict[str, int]] = {}
    block_effects: dict[str, float] = {}
    intervals: dict[str, tuple[float, float]] = {}
    for block in ["A", "B"]:
        domain = primary.loc[_block_mask(primary, block)]
        block_arms[block] = {
            state: int(domain["first_state"].eq(state).sum()) for state in ["R", "F"]
        }
        block_effects[block] = _transition_risk_difference(domain)
        intervals[block] = _cluster_bootstrap_interval(
            domain,
            "",
            "risk_difference",
            gates["calendar_block_bootstrap_resamples"],
            gates["calendar_block_bootstrap_seed"],
        )
    global_effect = _transition_risk_difference(primary)
    intervals["global"] = _cluster_bootstrap_interval(
        primary,
        "",
        "risk_difference",
        gates["calendar_block_bootstrap_resamples"],
        gates["calendar_block_bootstrap_seed"],
    )
    annual_effects = {
        str(year): _transition_risk_difference(primary.loc[primary["target_year"].eq(year)])
        for year in range(2018, 2024)
    }
    annual_arms = {
        str(year): {
            state: int((primary["target_year"].eq(year) & primary["first_state"].eq(state)).sum())
            for state in ["R", "F"]
        }
        for year in range(2018, 2024)
    }
    categories = {
        category: {
            "total": int(primary["transition_category"].eq(category).sum()),
            "by_block": {
                block: int(
                    (
                        _block_mask(primary, block) & primary["transition_category"].eq(category)
                    ).sum()
                )
                for block in ["A", "B"]
            },
            "by_year": {
                str(year): int(
                    (
                        primary["target_year"].eq(year)
                        & primary["transition_category"].eq(category)
                    ).sum()
                )
                for year in range(2018, 2024)
            },
        }
        for category in ["R_TO_R", "R_TO_F", "F_TO_R", "F_TO_F"]
    }
    support_pass = (
        int(arm_counts.get("R", 0)) >= gates["minimum_first_R_total"]
        and int(arm_counts.get("F", 0)) >= gates["minimum_first_F_total"]
        and all(
            block_arms[block][state] >= gates["minimum_each_arm_each_block"]
            for block in ["A", "B"]
            for state in ["R", "F"]
        )
        and all(
            annual_arms[str(year)][state] >= gates["minimum_each_arm_each_year"]
            for year in range(2018, 2024)
            for state in ["R", "F"]
        )
    )
    global_sign = _sign(global_effect)
    interval_pass = all(
        np.isfinite(intervals[domain]).all()
        and (intervals[domain][0] > 0 or intervals[domain][1] < 0)
        for domain in ["global", "A", "B"]
    )
    annual_same = sum(_sign(value) == global_sign for value in annual_effects.values())
    adjacent = _adjacent_risk_difference(primary)
    process_pass = bool(
        support_pass
        and global_sign != 0
        and all(
            _sign(block_effects[block]) == global_sign
            and abs(block_effects[block]) >= gates["minimum_absolute_risk_difference_each_block"]
            for block in ["A", "B"]
        )
        and interval_pass
        and annual_same >= gates["minimum_years_same_sign"]
        and _sign(adjacent) == global_sign
        and abs(adjacent - global_effect)
        <= gates["adjacent_pair_absolute_difference_from_primary_maximum"]
    )
    return {
        "support_status": "PASS" if support_pass else gates["unsupported_status"],
        "arm_counts": {state: int(arm_counts.get(state, 0)) for state in ["R", "F"]},
        "arm_counts_by_block": block_arms,
        "arm_counts_by_year": annual_arms,
        "categories": categories,
        "global_risk_difference": global_effect,
        "block_risk_differences": block_effects,
        "annual_risk_differences": annual_effects,
        "bootstrap_95_intervals": intervals,
        "adjacent_pair_risk_difference": adjacent,
        "years_same_sign": annual_same,
        "transition_process_pass": process_pass,
    }


def _descriptive_view_and_relative_audit(
    spec: dict[str, Any], trajectory: pd.DataFrame, transitions: pd.DataFrame
) -> dict[str, Any]:
    views: dict[str, Any] = {}
    for view in spec["sample"]["market_views"]:
        frame = trajectory.loc[trajectory["market_view"].eq(view)].copy()
        role_evidence: dict[str, Any] = {}
        for role in ["recovery_speed_progression", "recovery_volume_intensity_progression"]:
            target = role.removesuffix("_progression")
            primary = f"h20_cont_{target}_endpoint_rate"
            eligible = frame.loc[frame[primary].notna()]
            controls = [
                f"h20_cont_{field}_endpoint_rate" for field in spec["fixed_generic_controls"][role]
            ]
            complete = eligible[[primary, *controls]].dropna()
            pairwise = {
                control: abs(_spearman(complete[primary], complete[control]))
                for control in controls
            }
            role_evidence[role] = {
                "n": len(eligible),
                "median_endpoint_rate": (
                    np.nan if eligible.empty else float(eligible[primary].median())
                ),
                "endpoint_ols_spearman": _spearman(
                    eligible[primary], eligible[f"h20_cont_{target}_ols_slope"]
                ),
                "endpoint_theil_sen_spearman": _spearman(
                    eligible[primary], eligible[f"h20_cont_{target}_theil_sen_slope"]
                ),
                "level10_spearman": _spearman(
                    frame[primary], frame[f"h10_cont_{target}_endpoint_rate"]
                ),
                "level40_spearman": _spearman(
                    frame[primary], frame[f"h40_cont_{target}_endpoint_rate"]
                ),
                "auction_spearman": _spearman(
                    frame[primary], frame[f"h20_auction_{target}_endpoint_rate"]
                ),
                "maximum_generic_pairwise_absolute_spearman": (
                    np.nan if not pairwise else max(pairwise.values())
                ),
                "generic_joint_adjusted_rank_r2": _rank_adjusted_r2(complete, primary, controls),
            }
        view_transitions = transitions.loc[
            transitions["market_view"].eq(view)
            & transitions["level_horizon"].eq(20)
            & transitions["path"].eq("cont")
            & transitions["transition_category"].notna()
        ]
        views[view] = {
            "roles": role_evidence,
            "raw_coupling": _coupling_domain(frame, spec, False),
            "residual_coupling": _coupling_domain(frame, spec, True),
            "transition": {
                "n": len(view_transitions),
                "first_R": int(view_transitions["first_state"].eq("R").sum()),
                "first_F": int(view_transitions["first_state"].eq("F").sum()),
                "risk_difference": _transition_risk_difference(view_transitions),
            },
        }
    cell_fields = ["target_year", "block_id", "market_view"]
    all_cells = trajectory[cell_fields].drop_duplicates().sort_values(cell_fields)
    eligible = (
        trajectory.loc[trajectory["h20_cont_recovery_speed_endpoint_rate"].notna()]
        .groupby(cell_fields)
        .size()
        .rename("eligible_count")
        .reset_index()
    )
    cells = all_cells.merge(eligible, on=cell_fields, how="left", validate="one_to_one")
    cells["eligible_count"] = cells["eligible_count"].fillna(0).astype(int)
    frequency = cells["eligible_count"].value_counts().sort_index()
    relative_support = {
        "cells": len(cells),
        "minimum": int(cells["eligible_count"].min()),
        "median": float(cells["eligible_count"].median()),
        "maximum": int(cells["eligible_count"].max()),
        "cells_at_least_5": int(cells["eligible_count"].ge(5).sum()),
        "count_frequency": {str(count): int(value) for count, value in frequency.items()},
        "promoted_relative_coordinate": False,
    }
    return {"market_views": views, "relative_cell_support": relative_support}


def _manual_case_audit(
    selected_cases: list[str],
    panel: pd.DataFrame,
    trajectory: pd.DataFrame,
    coordinate: pd.DataFrame,
    manual_raw: dict[tuple[str, pd.Timestamp], pd.DataFrame],
) -> dict[str, Any]:
    coordinate_index = coordinate.set_index("audit_id")
    trajectory_index = trajectory.set_index("sequence_id")
    results: dict[str, Any] = {}
    for sequence_id in selected_cases:
        rows = panel.loc[panel["sequence_id"].eq(sequence_id)].sort_values("relative_day")
        manual_days: list[float] = []
        manual_speed: list[float] = []
        manual_volume: list[float] = []
        session_equal = True
        for row in rows.itertuples(index=False):
            raw = manual_raw[(sequence_id, pd.Timestamp(row.trade_date))]
            level = float(coordinate_index.loc[row.audit_id, "support_low20"])
            manual = _manual_session_descriptor(raw, level, False)
            for field in [
                "tested",
                "recovery_completion",
                "recovery_speed",
                "recovery_volume_intensity",
            ]:
                expected = getattr(row, f"h20_cont_{field}")
                observed = manual[field]
                equal = (pd.isna(expected) and pd.isna(observed)) or expected == observed
                session_equal = session_equal and bool(equal)
            if (
                manual["tested"]
                and manual["recovery_completion"]
                and pd.notna(manual["recovery_speed"])
                and pd.notna(manual["recovery_volume_intensity"])
            ):
                manual_days.append(float(row.relative_day))
                manual_speed.append(float(manual["recovery_speed"]))
                manual_volume.append(float(manual["recovery_volume_intensity"]))
        expected_trajectory = trajectory_index.loc[sequence_id]
        trajectory_equal = session_equal
        for field, values in [
            ("recovery_speed", manual_speed),
            ("recovery_volume_intensity", manual_volume),
        ]:
            operators = _temporal_operators(np.array(manual_days), np.array(values))
            for operator, observed in operators.items():
                expected = expected_trajectory[f"h20_cont_{field}_{operator}"]
                trajectory_equal = trajectory_equal and bool(expected == observed)
        if not trajectory_equal:
            raise SupportDynamicsError(f"manual scalar disagreement: {sequence_id}")
        results[sequence_id] = {
            "session_fields_exact": session_equal,
            "trajectory_operators_exact": trajectory_equal,
        }
    return {"selected_sequence_ids": selected_cases, "cases": results, "all_exact": True}


def _render_report(result: dict[str, Any]) -> str:
    roles = result["roles"]
    direction = result["directional_process"]
    transition = result["transition"]
    coupling = result["coupling"]
    raw_rho = coupling["raw"]["global"]["spearman"]
    recovered = result["population"]["primary_recovered_sequences"]
    repeated = result["population"]["primary_repeated_test_sequences"]
    relative_cells = result["descriptive_view_and_relative_audit"]["relative_cell_support"]
    lines = [
        "# MKT-SUPPORT-DYN-001 objective-recovery dynamics",
        "",
        "## Result",
        "",
        f"- Status: `{result['status']}`",
    ]
    for role in ["recovery_speed_progression", "recovery_volume_intensity_progression"]:
        lines.append(
            f"- {role}: representation `{roles[role]['representation_pass']}`; "
            f"directional process `{direction[role]['directional_process_pass']}`."
        )
    lines.extend(
        [
            (
                f"- Residual timing/activity coupling: `{coupling['coupling_pass']}`; "
                f"raw rho {raw_rho:.3f}."
            ),
            (
                f"- Completion-state transition: support `{transition['support_status']}`; "
                f"process `{transition['transition_process_pass']}`; risk difference "
                f"{transition['global_risk_difference']:.3f}."
            ),
            f"- Primary recovered/repeated-test sequence counts: {recovered}/{repeated}.",
            (
                f"- Conditional relative-cell support: {relative_cells['cells_at_least_5']}"
                f"/{relative_cells['cells']} cells have at least five trajectories; no "
                "relative coordinate is promoted."
            ),
            f"- Raw rows conserved: {result['population']['raw_minute_rows']:,}.",
            "",
            "## Interpretation boundary",
            "",
            (
                "- A stable trajectory is a completed-history coordinate, not evidence "
                "of common strengthening or weakening."
            ),
            (
                "- Rolling prior-low definitions are not one unchanged physical level. "
                "Recovery-period activity does not identify buyers, sellers, or absorption."
            ),
            (
                "- No future return, outcome, strategy, timing, execution, post-2023 "
                "data, or CY-011 was read."
            ),
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Session panel SHA-256: `{result['hashes']['session_panel_sha256']}`",
            f"- Trajectory panel SHA-256: `{result['hashes']['trajectory_panel_sha256']}`",
            f"- Transition audit SHA-256: `{result['hashes']['transition_audit_sha256']}`",
            f"- Stability audit SHA-256: `{result['hashes']['stability_audit_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run(*, verify_partition_content: bool = True) -> dict[str, Any]:
    started = time.monotonic()
    spec, data_spec = _load_spec()
    sample, coordinate, counts = _load_parent_frames(spec)
    eligible_ids = counts.loc[counts["recovered_sequence"].astype(bool), "sequence_id"].astype(str)
    selected_cases = sorted(eligible_ids, key=lambda value: (_case_hash(value), value))[
        : spec["replication"]["manual_sequence_cases"]
    ]
    panel, manual_raw, raw_rows = _read_session_panel(
        spec,
        data_spec,
        sample,
        coordinate,
        set(selected_cases),
        started,
        verify_partition_content,
    )
    if raw_rows != spec["sample"]["exact_raw_minute_rows"]:
        raise SupportDynamicsError("raw minute row conservation changed")
    trajectory, transitions = _build_trajectory_and_transition(panel)
    primary_recovered = int(trajectory["h20_cont_recovered_days"].ge(2).sum())
    primary_repeated = int(trajectory["h20_cont_tested_days"].ge(2).sum())
    if (
        primary_recovered != spec["sample"]["primary_recovered_sequences"]
        or primary_repeated != spec["sample"]["primary_repeated_test_sequences"]
    ):
        raise SupportDynamicsError("primary adequacy count changed")
    manual = _manual_case_audit(selected_cases, panel, trajectory, coordinate, manual_raw)
    del manual_raw
    gc.collect()
    _resource_guard(spec, started)

    roles: dict[str, dict[str, Any]] = {}
    stability_rows: list[dict[str, Any]] = []
    for role in ["recovery_speed_progression", "recovery_volume_intensity_progression"]:
        evidence, rows = _evaluate_role(spec, trajectory, role)
        roles[role] = evidence
        for row in rows:
            row["role"] = role
        stability_rows.extend(rows)
    directions = {
        role: _evaluate_direction(spec, trajectory, evidence) for role, evidence in roles.items()
    }
    coupling = _evaluate_coupling(spec, trajectory, roles)
    transition = _evaluate_transition(spec, transitions)
    descriptive_audit = _descriptive_view_and_relative_audit(spec, trajectory, transitions)

    accepted_roles = [role for role, evidence in roles.items() if evidence["representation_pass"]]
    directional_roles = [
        role for role, evidence in directions.items() if evidence["directional_process_pass"]
    ]
    any_process = bool(
        directional_roles or coupling["coupling_pass"] or transition["transition_process_pass"]
    )
    status = (
        "COMPLETE_TEMPORAL_PROCESS_SUPPORTED"
        if any_process
        else (
            "COMPLETE_REPRESENTATION_PASS_NO_PROCESS"
            if accepted_roles
            else "COMPLETE_TEMPORAL_REPRESENTATIONS_REJECTED"
        )
    )

    panel_out = panel.copy()
    panel_out["trade_date"] = panel_out["trade_date"].dt.strftime("%Y-%m-%d")
    panel_out.to_csv(SESSION_PATH, index=False, float_format="%.17g", lineterminator="\n")
    trajectory.to_csv(TRAJECTORY_PATH, index=False, float_format="%.17g", lineterminator="\n")
    transitions.to_csv(TRANSITION_PATH, index=False, lineterminator="\n")
    stability = (
        pd.DataFrame(stability_rows)
        .sort_values(["role", "challenge", "domain"])
        .reset_index(drop=True)
    )
    stability.to_csv(STABILITY_PATH, index=False, float_format="%.17g", lineterminator="\n")

    result: dict[str, Any] = {
        "experiment_id": "MKT-SUPPORT-DYN-001",
        "status": status,
        "population": {
            "sequences": len(trajectory),
            "cohort_rows": len(panel),
            "unique_sessions": len(panel[["symbol", "trade_date"]].drop_duplicates()),
            "raw_minute_rows": raw_rows,
            "primary_recovered_sequences": primary_recovered,
            "primary_repeated_test_sequences": primary_repeated,
        },
        "roles": roles,
        "accepted_temporal_roles": accepted_roles,
        "directional_process": directions,
        "directional_process_roles": directional_roles,
        "coupling": coupling,
        "transition": transition,
        "descriptive_view_and_relative_audit": descriptive_audit,
        "manual_scalar_replication": manual,
        "coordinate_systems": spec["coordinate_systems"],
        "rolling_level_identity_claim": False,
        "buyer_seller_or_absorption_claim": "NONE",
        "support_defense_claim": "NONE",
        "prediction_or_usefulness_claim": "NONE",
        "strategy_or_outcome_fields_read": [],
        "future_fields_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
        "partition_content_hashes_verified": verify_partition_content,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "session_panel_sha256": sha256_file(SESSION_PATH),
            "trajectory_panel_sha256": sha256_file(TRAJECTORY_PATH),
            "transition_audit_sha256": sha256_file(TRANSITION_PATH),
            "stability_audit_sha256": sha256_file(STABILITY_PATH),
            "bound_inputs": {name: binding["sha256"] for name, binding in spec["inputs"].items()},
        },
    }
    result = _clean(result)
    RESULT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    durable_bytes = sum(
        path.stat().st_size
        for path in [
            SESSION_PATH,
            TRAJECTORY_PATH,
            TRANSITION_PATH,
            STABILITY_PATH,
            RESULT_PATH,
            REPORT_PATH,
        ]
    )
    if durable_bytes > spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20:
        raise SupportDynamicsError("durable output ceiling breached")
    _resource_guard(spec, started)
    return result


if __name__ == "__main__":
    completed = run()
    print(
        json.dumps(
            {
                "status": completed["status"],
                "accepted_temporal_roles": completed["accepted_temporal_roles"],
                "directional_process_roles": completed["directional_process_roles"],
                "coupling_pass": completed["coupling"]["coupling_pass"],
                "transition_process_pass": completed["transition"]["transition_process_pass"],
            },
            indent=2,
            sort_keys=True,
        )
    )
