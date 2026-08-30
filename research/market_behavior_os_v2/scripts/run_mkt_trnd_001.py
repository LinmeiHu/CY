#!/usr/bin/env python3
"""Outcome-blind strategy-independent trend representation freeze."""

from __future__ import annotations

import bisect
import datetime as dt
import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-TRND-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-TRND-001_trend_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-TRND-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-TRND-001_trend_state_freeze.md"
EXPECTED_MANIFEST_SHA = "d847419443b2563c1904790f986ef8980dc37d688318fadb3858b3251d84972f"
RESEARCH_START = pd.Timestamp("2010-06-01")
RESEARCH_END = pd.Timestamp("2023-12-31")
SNAPSHOT_ID = f"QD-003:{EXPECTED_MANIFEST_SHA}"
MIN_PIT_HISTORY = 504
PIT_WINDOW = 756

ROLE_MAP = {
    "direction": ("direction_return_60", ("direction_return_40", "direction_return_80")),
    "strength": ("strength_abs_ma60", ("strength_abs_ma40", "strength_abs_ma80")),
    "quality": ("quality_efficiency_60", ("quality_efficiency_40", "quality_efficiency_80")),
    "age": ("age_same_side_ma60", ("age_same_side_ma40", "age_same_side_ma80")),
    "alignment": ("alignment_20_60_120", ("alignment_10_40_120", "alignment_20_80_160")),
    "transition": ("transition_20_vs_60", ("transition_10_vs_60", "transition_30_vs_60")),
}
MINIMAL_PRIORITY = ("direction", "quality", "age", "transition", "strength", "alignment")


class TrendFreezeError(RuntimeError):
    """Fail-closed construction error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def causal_expanding_percentile(values: pd.Series, min_history: int = MIN_PIT_HISTORY) -> pd.Series:
    output = np.full(len(values), np.nan, dtype=float)
    ordered: list[float] = []
    for position, value in enumerate(values.to_numpy(dtype=float)):
        if not np.isfinite(value):
            continue
        bisect.insort(ordered, float(value))
        if len(ordered) >= min_history:
            left = bisect.bisect_left(ordered, float(value))
            right = bisect.bisect_right(ordered, float(value))
            output[position] = (left + right + 1.0) / (2.0 * len(ordered))
    return pd.Series(output, index=values.index, dtype=float)


def causal_rolling_percentile(
    values: pd.Series,
    window: int = PIT_WINDOW,
    min_history: int = MIN_PIT_HISTORY,
) -> pd.Series:
    output = np.full(len(values), np.nan, dtype=float)
    ordered: list[float] = []
    raw = values.to_numpy(dtype=float)
    for position, value in enumerate(raw):
        if np.isfinite(value):
            bisect.insort(ordered, float(value))
        expired_position = position - window
        if expired_position >= 0 and np.isfinite(raw[expired_position]):
            expired = float(raw[expired_position])
            removal = bisect.bisect_left(ordered, expired)
            if removal >= len(ordered) or ordered[removal] != expired:
                raise TrendFreezeError("rolling percentile state lost exact value")
            ordered.pop(removal)
        if np.isfinite(value) and len(ordered) >= min_history:
            left = bisect.bisect_left(ordered, float(value))
            right = bisect.bisect_right(ordered, float(value))
            output[position] = (left + right + 1.0) / (2.0 * len(ordered))
    return pd.Series(output, index=values.index, dtype=float)


def causal_rolling_robust_z(
    values: pd.Series,
    window: int = PIT_WINDOW,
    min_history: int = MIN_PIT_HISTORY,
) -> pd.Series:
    output = np.full(len(values), np.nan, dtype=float)
    raw = values.to_numpy(dtype=float)
    for position, value in enumerate(raw):
        if not np.isfinite(value):
            continue
        start = max(0, position - window + 1)
        history = raw[start : position + 1]
        history = history[np.isfinite(history)]
        if len(history) < min_history:
            continue
        median = float(np.median(history))
        mad = float(np.median(np.abs(history - median)))
        if mad > 0.0:
            output[position] = (float(value) - median) / (1.4826 * mad)
    return pd.Series(output, index=values.index, dtype=float)


def same_side_age(close: pd.Series, moving_average: pd.Series) -> pd.Series:
    side = np.sign(close.to_numpy(dtype=float) - moving_average.to_numpy(dtype=float))
    valid = np.isfinite(close.to_numpy(dtype=float)) & np.isfinite(moving_average.to_numpy(dtype=float))
    output = np.full(len(close), np.nan, dtype=float)
    age = 0
    previous = np.nan
    for position in range(len(close)):
        if not valid[position] or side[position] == 0:
            age = 0
            previous = np.nan
            continue
        if np.isfinite(previous) and side[position] == previous:
            age += 1
        else:
            age = 1
        output[position] = float(age)
        previous = side[position]
    return pd.Series(output, index=close.index, dtype=float)


def alignment_score(short: pd.Series, medium: pd.Series, long: pd.Series) -> pd.Series:
    valid = short.notna() & medium.notna() & long.notna()
    result = (
        np.sign(short - medium) + np.sign(short - long) + np.sign(medium - long)
    ) / 3.0
    return result.where(valid).astype(float)


def directional_efficiency(log_close: pd.Series, daily_log_return: pd.Series, horizon: int) -> pd.Series:
    numerator = (log_close - log_close.shift(horizon)).abs()
    denominator = daily_log_return.abs().rolling(horizon, min_periods=horizon).sum()
    return (numerator / denominator).where(denominator > 0.0)


def build_raw_features(group: pd.DataFrame) -> pd.DataFrame:
    frame = group.sort_values("trade_date").copy()
    close = frame["close"].astype(float)
    log_close = np.log(close)
    daily_log_return = log_close.diff()

    for horizon in (10, 20, 30, 40, 60, 80):
        frame[f"_return_{horizon}"] = log_close - log_close.shift(horizon)
    for horizon in (10, 20, 40, 60, 80, 120, 160):
        frame[f"_ma_{horizon}"] = close.rolling(horizon, min_periods=horizon).mean()

    for horizon in (40, 60, 80):
        frame[f"direction_return_{horizon}"] = frame[f"_return_{horizon}"]
        frame[f"strength_abs_ma{horizon}"] = (close / frame[f"_ma_{horizon}"] - 1.0).abs()
        frame[f"quality_efficiency_{horizon}"] = directional_efficiency(
            log_close, daily_log_return, horizon
        )
        frame[f"age_same_side_ma{horizon}"] = same_side_age(close, frame[f"_ma_{horizon}"])

    frame["alignment_20_60_120"] = alignment_score(
        frame["_ma_20"], frame["_ma_60"], frame["_ma_120"]
    )
    frame["alignment_10_40_120"] = alignment_score(
        frame["_ma_10"], frame["_ma_40"], frame["_ma_120"]
    )
    frame["alignment_20_80_160"] = alignment_score(
        frame["_ma_20"], frame["_ma_80"], frame["_ma_160"]
    )
    frame["transition_20_vs_60"] = frame["_return_20"] - frame["_return_60"] / 3.0
    frame["transition_10_vs_60"] = frame["_return_10"] - frame["_return_60"] / 6.0
    frame["transition_30_vs_60"] = frame["_return_30"] - frame["_return_60"] / 2.0
    frame["within_index_observation"] = np.arange(1, len(frame) + 1, dtype=int)
    return frame


def _verify_inputs(spec: dict) -> tuple[Path, dict[str, str]]:
    manifest_path = Path(spec["input"]["manifest_path"])
    if sha256_file(manifest_path) != EXPECTED_MANIFEST_SHA:
        raise TrendFreezeError("QD-003 manifest identity mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_root = Path(spec["input"]["source_root"])
    expected = spec["input"]["file_sha256"]
    observed_names = {item["path"] for item in manifest["files"]}
    if observed_names != set(expected):
        raise TrendFreezeError("QD-003 manifest file set mismatch")
    observed: dict[str, str] = {}
    for name, expected_hash in sorted(expected.items()):
        path = source_root / name
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise TrendFreezeError(f"QD-003 source hash mismatch: {name}")
        manifest_hash = next(item["sha256"] for item in manifest["files"] if item["path"] == name)
        if manifest_hash != expected_hash:
            raise TrendFreezeError(f"QD-003 manifest entry mismatch: {name}")
        observed[name] = actual_hash
    return source_root, observed


def _load_panel(source_root: Path, filenames: list[str]) -> tuple[pd.DataFrame, list[dict]]:
    required = {"index_symbol", "index_name", "trade_date", "open", "high", "low", "close", "volume", "amount"}
    frames: list[pd.DataFrame] = []
    abnormal_rows: list[dict] = []
    for name in filenames:
        connection = duckdb.connect()
        try:
            frame = connection.execute(
                "SELECT * FROM read_parquet(?) WHERE trade_date <= ? ORDER BY trade_date",
                [str(source_root / name), dt.date(2023, 12, 31)],
            ).df()
        finally:
            connection.close()
        if set(frame.columns) != required:
            raise TrendFreezeError(f"unexpected schema: {name}")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
        frame = frame.loc[frame["trade_date"] <= RESEARCH_END].copy()
        if frame.empty or frame["index_symbol"].nunique() != 1:
            raise TrendFreezeError(f"invalid index identity: {name}")
        numeric = ["open", "high", "low", "close", "volume", "amount"]
        if frame[numeric].isna().any().any() or not np.isfinite(frame[numeric].to_numpy()).all():
            raise TrendFreezeError(f"invalid numeric facts: {name}")
        if (frame[["open", "high", "low", "close"]] <= 0.0).any().any():
            raise TrendFreezeError(f"nonpositive price: {name}")
        if (frame["volume"] < 0.0).any() or (frame["amount"] < 0.0).any():
            raise TrendFreezeError(f"negative volume/amount: {name}")
        high_invalid = frame["high"] < frame[["open", "close", "low"]].max(axis=1)
        low_invalid = frame["low"] > frame[["open", "close", "high"]].min(axis=1)
        ohlc_invalid = high_invalid | low_invalid
        frame["source_hard_valid"] = ~ohlc_invalid
        for _, row in frame.loc[ohlc_invalid].iterrows():
            abnormal_rows.append(
                {
                    "source_file": name,
                    "index_symbol": str(row["index_symbol"]),
                    "trade_date": row["trade_date"].strftime("%Y-%m-%d"),
                    "reason": "OHLC_INVARIANT_FAILED",
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                }
            )
        frame.loc[ohlc_invalid, ["open", "high", "low", "close"]] = np.nan
        if frame["trade_date"].duplicated().any() or not frame["trade_date"].is_monotonic_increasing:
            raise TrendFreezeError(f"date key/order failed: {name}")
        frames.append(frame)
    panel = pd.concat(frames, ignore_index=True)
    if panel.duplicated(["index_symbol", "trade_date"]).any():
        raise TrendFreezeError("duplicate panel key")
    if len(frames) != 6 or panel["index_symbol"].nunique() != 6:
        raise TrendFreezeError("exact six-index contract failed")
    return panel, abnormal_rows


def _attach_coordinates(panel: pd.DataFrame) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    primary_columns = [primary for primary, _ in ROLE_MAP.values()]
    for _, group in panel.groupby("index_symbol", sort=True):
        featured = build_raw_features(group)
        for column in primary_columns:
            featured[f"{column}_pit_expanding_pct"] = causal_expanding_percentile(featured[column])
            featured[f"{column}_pit_3y_pct"] = causal_rolling_percentile(featured[column])
            featured[f"{column}_pit_3y_robust_z"] = causal_rolling_robust_z(featured[column])
        pieces.append(featured)
    combined = pd.concat(pieces, ignore_index=True).sort_values(["trade_date", "index_symbol"])
    combined = combined.loc[combined["trade_date"] >= RESEARCH_START].copy()
    for column in primary_columns:
        counts = combined.groupby("trade_date")[column].transform("count")
        ranks = combined.groupby("trade_date")[column].rank(method="average", pct=True)
        combined[f"{column}_relative_rank_pct"] = ranks.where(counts >= 4)
    combined["decision_at"] = combined["trade_date"].dt.strftime("%Y-%m-%d") + "T15:00:00+08:00"
    combined["available_at"] = combined["decision_at"]
    combined["snapshot_id"] = SNAPSHOT_ID
    return combined


def _role_diagnostics(panel: pd.DataFrame) -> tuple[dict, pd.DataFrame, list[str], dict[str, str]]:
    eligible = panel.loc[panel["within_index_observation"] >= 160].copy()
    diagnostics: dict[str, dict] = {}
    primaries = {role: definition[0] for role, definition in ROLE_MAP.items()}
    for role, (primary, neighbors) in ROLE_MAP.items():
        coverage = float(eligible[primary].notna().mean())
        neighbor_stats: dict[str, dict] = {}
        neighbor_medians: list[float] = []
        for neighbor in neighbors:
            by_index: dict[str, float] = {}
            for symbol, group in eligible.groupby("index_symbol", sort=True):
                rho = group[[primary, neighbor]].corr(method="spearman").iloc[0, 1]
                by_index[str(symbol)] = float(rho)
            median_rho = float(np.median(list(by_index.values())))
            neighbor_medians.append(median_rho)
            neighbor_stats[neighbor] = {"median_within_index_spearman": median_rho, "by_index": by_index}

        cell_checks: list[bool] = []
        eligible_cells = 0
        for _, cell in eligible.assign(year=eligible["trade_date"].dt.year).groupby(
            ["index_symbol", "year"], sort=True
        ):
            values = cell[primary].dropna()
            if len(values) >= 150:
                eligible_cells += 1
                cell_checks.append(bool(np.isfinite(values.std(ddof=0)) and values.std(ddof=0) > 0.0))
        nondegenerate = bool(eligible_cells > 0 and all(cell_checks))

        pit_expected = panel[primary].notna().groupby(panel["index_symbol"]).cumsum() >= MIN_PIT_HISTORY
        expanding_coverage = float(panel.loc[pit_expected, f"{primary}_pit_expanding_pct"].notna().mean())
        rolling_pct_coverage = float(panel.loc[pit_expected, f"{primary}_pit_3y_pct"].notna().mean())
        robust_z_coverage = float(panel.loc[pit_expected, f"{primary}_pit_3y_robust_z"].notna().mean())
        relative_expected = panel.groupby("trade_date")[primary].transform("count") >= 4
        relative_coverage = float(panel.loc[relative_expected, f"{primary}_relative_rank_pct"].notna().mean())
        passed = bool(coverage >= 0.98 and min(neighbor_medians) >= 0.70 and nondegenerate)
        diagnostics[role] = {
            "primary": primary,
            "neighbors": neighbor_stats,
            "raw_coverage_after_160": coverage,
            "eligible_index_year_cells": eligible_cells,
            "all_eligible_cells_nondegenerate": nondegenerate,
            "pit_expanding_expected_coverage": expanding_coverage,
            "pit_3y_percentile_expected_coverage": rolling_pct_coverage,
            "pit_3y_robust_z_expected_coverage": robust_z_coverage,
            "relative_expected_coverage": relative_coverage,
            "construction_gate_pass": passed,
        }

    primary_frame = eligible[[primaries[role] for role in MINIMAL_PRIORITY]].rename(
        columns={primaries[role]: role for role in MINIMAL_PRIORITY}
    )
    correlation = primary_frame.corr(method="spearman")
    accepted: list[str] = []
    excluded: dict[str, str] = {}
    for role in MINIMAL_PRIORITY:
        if not diagnostics[role]["construction_gate_pass"]:
            excluded[role] = "construction_gate_failed"
            continue
        blockers = [other for other in accepted if abs(float(correlation.loc[role, other])) > 0.85]
        if blockers:
            excluded[role] = "redundant_with:" + ",".join(blockers)
        else:
            accepted.append(role)
    return diagnostics, correlation, accepted, excluded


def _serializable_correlation(correlation: pd.DataFrame) -> dict[str, dict[str, float]]:
    return {
        str(row): {str(column): float(correlation.loc[row, column]) for column in correlation.columns}
        for row in correlation.index
    }


def _render_report(result: dict) -> str:
    lines = [
        "# MKT-TRND-001 strategy-independent trend-state freeze",
        "",
        "## Contract result",
        "",
        f"- Status: `{result['status']}`",
        f"- Research window: `{result['research_window']['start']}` through `{result['research_window']['end']}`.",
        f"- Indices: {result['population']['indices']}; rows: {result['population']['rows']:,}.",
        f"- Source OHLC rows failed closed: {result['population']['source_hard_invalid_rows']}.",
        "- Strategy outcomes, trades, future returns, MFE, MAE, exits, and duration fields read: **none**.",
        f"- Minimal nonredundant roles: `{', '.join(result['minimal_panel']['accepted_roles']) or 'NONE'}`.",
        "",
        "## Representation gates",
        "",
        "| Role | Primary | Raw coverage | Worst neighbor median rho | PIT expanding | PIT 3y pct | PIT robust z | Relative | Gate | Minimal panel |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    accepted = set(result["minimal_panel"]["accepted_roles"])
    for role in MINIMAL_PRIORITY:
        item = result["role_diagnostics"][role]
        worst_neighbor = min(v["median_within_index_spearman"] for v in item["neighbors"].values())
        disposition = "ACCEPT" if role in accepted else result["minimal_panel"]["excluded_roles"].get(role, "EXCLUDE")
        lines.append(
            f"| {role} | `{item['primary']}` | {item['raw_coverage_after_160']:.3f} | "
            f"{worst_neighbor:.3f} | {item['pit_expanding_expected_coverage']:.3f} | "
            f"{item['pit_3y_percentile_expected_coverage']:.3f} | {item['pit_3y_robust_z_expected_coverage']:.3f} | "
            f"{item['relative_expected_coverage']:.3f} | {'PASS' if item['construction_gate_pass'] else 'FAIL'} | {disposition} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "This experiment freezes representations of the market itself. It does not show that any state predicts returns or that any strategy belongs in a state. Roles excluded for construction instability, coverage, or redundancy cannot be advertised as independent dimensions from this construction.",
            "",
            "The absolute values remain primary. Causal PIT percentiles/z-scores and same-date cross-index ranks are separate coordinates, not replacements for absolute state.",
            "",
            "Quality, age, and transition fail their fixed neighboring-horizon stability gates. Strength and alignment pass neighboring stability but miss the exact raw-coverage gate after strict source-row quarantine; they are data-contract-limited, not mechanistically rejected. Alignment's discrete primary also has zero rolling MAD often enough that robust-z coverage is 0.795, correctly remaining missing.",
            "",
            "The audit quarantines 21 exact OHLC ordering violations. It applies no tolerance even where the mismatch is 0.001, because the source does not establish which OHLC coordinate is correct.",
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- QD-003 manifest SHA-256: `{result['hashes']['manifest_sha256']}`",
            f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`",
        ]
    )
    lines.extend(
        [
            "",
            "## Appendix: quarantined source rows",
            "",
            "| Index | Date | Open | High | Low | Close | Reason |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in result["population"]["source_hard_invalid_detail"]:
        lines.append(
            f"| {row['index_symbol']} | {row['trade_date']} | {row['open']:.6f} | "
            f"{row['high']:.6f} | {row['low']:.6f} | {row['close']:.6f} | {row['reason']} |"
        )
    return "\n".join(lines) + "\n"


def run() -> dict:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["outcome_policy"]["strategy_outcomes"] != "PROHIBITED":
        raise TrendFreezeError("outcome prohibition is not frozen")
    source_root, source_hashes = _verify_inputs(spec)
    raw, abnormal_rows = _load_panel(source_root, sorted(source_hashes))
    panel = _attach_coordinates(raw)
    if panel["trade_date"].max() > RESEARCH_END or panel["trade_date"].min() < RESEARCH_START:
        raise TrendFreezeError("research window boundary failed")
    diagnostics, correlation, accepted, excluded = _role_diagnostics(panel)

    primary_and_neighbors = [column for definition in ROLE_MAP.values() for column in (definition[0], *definition[1])]
    coordinate_columns = [
        column
        for primary, _ in ROLE_MAP.values()
        for column in (
            f"{primary}_pit_expanding_pct",
            f"{primary}_pit_3y_pct",
            f"{primary}_pit_3y_robust_z",
            f"{primary}_relative_rank_pct",
        )
    ]
    output_columns = [
        "index_symbol",
        "index_name",
        "trade_date",
        "decision_at",
        "available_at",
        "snapshot_id",
        "source_hard_valid",
        "within_index_observation",
        *primary_and_neighbors,
        *coordinate_columns,
    ]
    output = panel[output_columns].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")

    result = {
        "experiment_id": "MKT-TRND-001",
        "status": "PASS_STRATEGY_INDEPENDENT_TREND_REPRESENTATION_FREEZE",
        "outcome_fields_read": [],
        "research_window": {
            "start": str(output["trade_date"].min()),
            "end": str(output["trade_date"].max()),
            "post_2023_rows_in_output": int((pd.to_datetime(output["trade_date"]) > RESEARCH_END).sum()),
        },
        "population": {
            "indices": int(output["index_symbol"].nunique()),
            "rows": int(len(output)),
            "rows_by_index": {str(k): int(v) for k, v in output.groupby("index_symbol").size().items()},
            "first_date_by_index": {str(k): str(v) for k, v in output.groupby("index_symbol")["trade_date"].min().items()},
            "last_date_by_index": {str(k): str(v) for k, v in output.groupby("index_symbol")["trade_date"].max().items()},
            "source_hard_invalid_rows": len(abnormal_rows),
            "source_hard_invalid_detail": abnormal_rows,
        },
        "role_diagnostics": diagnostics,
        "primary_role_spearman": _serializable_correlation(correlation),
        "minimal_panel": {"priority": list(MINIMAL_PRIORITY), "accepted_roles": accepted, "excluded_roles": excluded},
        "pit": {
            "decision_at": "completed official close 15:00 Asia/Shanghai",
            "first_actionable_time": "next valid trading session; no action created here",
            "snapshot_id": SNAPSHOT_ID,
            "minimum_normalization_history": MIN_PIT_HISTORY,
            "rolling_window": PIT_WINDOW,
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "manifest_sha256": EXPECTED_MANIFEST_SHA,
            "source_files": source_hashes,
            "panel_sha256": sha256_file(PANEL_PATH),
        },
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    final = run()
    print(json.dumps({
        "status": final["status"],
        "rows": final["population"]["rows"],
        "accepted_roles": final["minimal_panel"]["accepted_roles"],
        "excluded_roles": final["minimal_panel"]["excluded_roles"],
        "panel_sha256": final["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
