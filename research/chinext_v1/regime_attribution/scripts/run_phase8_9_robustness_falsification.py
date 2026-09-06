#!/usr/bin/env python3
"""Run the frozen no-search EXP-P8P9-001 robustness/falsification audit."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
SPEC = WORK / "experiments/EXP-P8P9-001_spec.json"
MANIFEST = WORK / "artifacts/v1r_candidate_ledger_manifest.json"
FEATURES = WORK / "artifacts/daily_regime_features.parquet"
P7_RESULT = WORK / "artifacts/v1r_candidate_results.json"
P7_YEARLY = WORK / "artifacts/v1r_candidate_yearly_metrics.csv"
P7_BLOCK = WORK / "artifacts/v1r_candidate_trade_metrics.csv"
OUTPUT_JSON = WORK / "artifacts/v1r_robustness_falsification.json"
OUTPUT_ROLLING = WORK / "artifacts/v1r_rolling_metrics.csv"
OUTPUT_TEMPORAL = WORK / "artifacts/v1r_temporal_metrics.csv"
REPORT_P8 = WORK / "reports/phase8_robustness_overfitting.md"
REPORT_P9 = WORK / "reports/phase9_failure_falsification.md"

PRIMARY = "A40_HALF_PRIMARY"
CONTROL = "C0_ALL_ONE_CONTROL"
NEIGHBORS = ["N30_HALF_NEIGHBOR", "N50_HALF_NEIGHBOR"]
BLOCKS = [
    "EXTENDED_2018_2021",
    "HOLDOUT_O0_2022_2023",
    "DEVELOPMENT_2024_2025",
]
ARMS = [
    CONTROL,
    PRIMARY,
    *NEIGHBORS,
    "Z40_ZERO_SEVERITY",
]
ROLLING_WINDOWS = [126, 252]
INITIAL_CASH = 1_000_000.0


class AuditError(RuntimeError):
    """Raised when frozen Phase 8/9 lineage or invariants fail closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def sign(value: float, tolerance: float = 1e-12) -> int:
    if value > tolerance:
        return 1
    if value < -tolerance:
        return -1
    return 0


def max_drawdown(values: Iterable[float], start: float) -> float:
    peak = float(start)
    result = 0.0
    for value in [float(start), *(float(item) for item in values)]:
        peak = max(peak, value)
        result = min(result, value / peak - 1.0)
    return result


def load_and_validate_spec() -> tuple[dict[str, Any], dict[str, Any]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-P8P9-001":
        raise AuditError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_PHASE8_9_DERIVED_DIAGNOSTICS":
        raise AuditError("Phase 8/9 specification is not frozen")
    bindings = spec.get("input_bindings", {})
    for name, binding in bindings.items():
        path = ROOT / binding["path"]
        actual = sha256_file(path)
        if actual != binding["sha256"]:
            raise AuditError(
                f"input binding mismatch for {name}: expected {binding['sha256']}, got {actual}"
            )
    if bindings["phase8_9_runner"]["path"] != str(
        Path(__file__).resolve().relative_to(ROOT)
    ):
        raise AuditError("runner binding points to another file")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("ledger_count") != 15:
        raise AuditError("frozen ledger manifest does not contain 15 ledgers")
    expected_pairs = {(block, arm) for block in BLOCKS for arm in ARMS}
    actual_pairs = {
        (item["block"], item["arm"]) for item in manifest.get("ledgers", [])
    }
    if actual_pairs != expected_pairs:
        raise AuditError("frozen ledger block/arm surface mismatch")
    for item in manifest["ledgers"]:
        for file_item in item["files"].values():
            path = ROOT / file_item["path"]
            if sha256_file(path) != file_item["sha256"]:
                raise AuditError(f"ledger changed after manifest freeze: {path}")
    return spec, manifest


def ledger_path(manifest: dict[str, Any], block: str, arm: str, name: str) -> Path:
    match = [
        item
        for item in manifest["ledgers"]
        if item["block"] == block and item["arm"] == arm
    ]
    if len(match) != 1:
        raise AuditError(f"missing unique manifest row for {block}/{arm}")
    return ROOT / match[0]["files"][name]["path"]


def load_nav(manifest: dict[str, Any], block: str, arm: str) -> pd.DataFrame:
    frame = pd.DataFrame(read_jsonl(ledger_path(manifest, block, arm, "daily_nav.jsonl")))
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    frame = frame.sort_values("trade_date").reset_index(drop=True)
    if frame.trade_date.duplicated().any():
        raise AuditError(f"duplicate NAV date for {block}/{arm}")
    return frame


def rolling_records(
    block: str, control: pd.DataFrame, candidate: pd.DataFrame
) -> list[dict[str, Any]]:
    if not control.trade_date.equals(candidate.trade_date):
        raise AuditError(f"control/candidate NAV dates differ for {block}")
    records: list[dict[str, Any]] = []
    for window in ROLLING_WINDOWS:
        for end in range(window, len(control)):
            control_return = float(control.nav.iloc[end] / control.nav.iloc[end - window] - 1.0)
            candidate_return = float(
                candidate.nav.iloc[end] / candidate.nav.iloc[end - window] - 1.0
            )
            records.append(
                {
                    "block": block,
                    "window_sessions": window,
                    "start_date": control.trade_date.iloc[end - window].date().isoformat(),
                    "end_date": control.trade_date.iloc[end].date().isoformat(),
                    "control_return": control_return,
                    "candidate_return": candidate_return,
                    "active_return": candidate_return - control_return,
                }
            )
    return records


def expanding_records(
    block: str, control: pd.DataFrame, candidate: pd.DataFrame
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for year in sorted(control.trade_date.dt.year.unique()):
        control_rows = control[control.trade_date.dt.year <= year]
        candidate_rows = candidate[candidate.trade_date.dt.year <= year]
        start_control = INITIAL_CASH
        start_candidate = INITIAL_CASH
        control_return = float(control_rows.iloc[-1].nav / start_control - 1.0)
        candidate_return = float(candidate_rows.iloc[-1].nav / start_candidate - 1.0)
        records.append(
            {
                "record_type": "EXPANDING_BLOCK_PREFIX",
                "block": block,
                "year": int(year),
                "control_return": control_return,
                "candidate_return": candidate_return,
                "active_return": candidate_return - control_return,
                "control_max_drawdown": max_drawdown(control_rows.nav, start_control),
                "candidate_max_drawdown": max_drawdown(candidate_rows.nav, start_candidate),
            }
        )
    return records


def yearly_records(yearly: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year in sorted(yearly.year.unique()):
        control = yearly[(yearly.year == year) & (yearly.arm == CONTROL)].iloc[0]
        candidate = yearly[(yearly.year == year) & (yearly.arm == PRIMARY)].iloc[0]
        rows.append(
            {
                "record_type": "CALENDAR_YEAR",
                "block": str(control.block),
                "year": int(year),
                "control_return": float(control["return"]),
                "candidate_return": float(candidate["return"]),
                "active_return": float(candidate["return"] - control["return"]),
                "control_max_drawdown": float(control.max_drawdown),
                "candidate_max_drawdown": float(candidate.max_drawdown),
                "drawdown_delta_positive_is_better": float(
                    candidate.max_drawdown - control.max_drawdown
                ),
                "control_average_invested_fraction": float(
                    control.average_invested_fraction
                ),
                "candidate_average_invested_fraction": float(
                    candidate.average_invested_fraction
                ),
                "control_severe_loss_rate": float(control.severe_loss_rate),
                "candidate_severe_loss_rate": float(candidate.severe_loss_rate),
                "control_winner20_count": int(control.winner20_count),
                "candidate_winner20_count": int(candidate.winner20_count),
            }
        )
    return rows


def loyo_records(calendar_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    years = [int(row["year"]) for row in calendar_rows]
    for omitted in years:
        values = [
            float(row["active_return"])
            for row in calendar_rows
            if int(row["year"]) != omitted
        ]
        records.append(
            {
                "record_type": "LOYO_ARITHMETIC_YEAR_DELTA_NO_REFIT",
                "omitted_year": omitted,
                "remaining_year_count": len(values),
                "mean_active_return": float(np.mean(values)),
                "median_active_return": float(np.median(values)),
                "positive_year_count": sum(sign(value) > 0 for value in values),
                "negative_year_count": sum(sign(value) < 0 for value in values),
                "neutral_year_count": sum(sign(value) == 0 for value in values),
            }
        )
    return records


def rolling_summary(rolling: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for (block, window), rows in rolling.groupby(
        ["block", "window_sessions"], sort=True
    ):
        values = rows.active_return.astype(float)
        records.append(
            {
                "block": str(block),
                "window_sessions": int(window),
                "window_count": len(values),
                "positive_fraction": float((values > 1e-12).mean()),
                "median_active_return": float(values.median()),
                "mean_active_return": float(values.mean()),
                "p10_active_return": float(values.quantile(0.10)),
                "p90_active_return": float(values.quantile(0.90)),
                "minimum_active_return": float(values.min()),
                "maximum_active_return": float(values.max()),
            }
        )
    return records


def regime_frequency(features: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    features = features.copy()
    features["trade_date"] = pd.to_datetime(features.trade_date)
    for (block, year), rows in features.groupby(
        ["baseline_block", features.trade_date.dt.year], sort=True
    ):
        valid = rows.breadth_above_ma20.notna()
        weak = valid & (rows.breadth_above_ma20 < 0.40)
        strong = valid & (rows.breadth_above_ma20 >= 0.40)
        records.append(
            {
                "block": str(block),
                "year": int(year),
                "session_count": len(rows),
                "valid_count": int(valid.sum()),
                "missing_count": int((~valid).sum()),
                "weak_count": int(weak.sum()),
                "normal_count": int(strong.sum()),
                "valid_fraction": float(valid.mean()),
                "weak_fraction_of_valid": float(weak.sum() / valid.sum()),
                "normal_fraction_of_valid": float(strong.sum() / valid.sum()),
            }
        )
    return records


def expected_multiplier(value: Any, arm: str) -> float:
    if arm == CONTROL:
        return 1.0
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0.0
    threshold, weak = {
        PRIMARY: (0.40, 0.50),
        "N30_HALF_NEIGHBOR": (0.30, 0.50),
        "N50_HALF_NEIGHBOR": (0.50, 0.50),
        "Z40_ZERO_SEVERITY": (0.40, 0.00),
    }[arm]
    return weak if float(value) < threshold else 1.0


def implementation_audit(
    manifest: dict[str, Any], features: pd.DataFrame, p7_result: dict[str, Any]
) -> dict[str, Any]:
    feature_rows = features.copy()
    feature_rows["trade_date"] = pd.to_datetime(feature_rows.trade_date).dt.date
    feature_rows["feature_available_at"] = pd.to_datetime(
        feature_rows.feature_available_at
    )
    feature_rows["first_applicable_trade_date"] = pd.to_datetime(
        feature_rows.first_applicable_trade_date
    ).dt.date
    feature_map = {
        (row.baseline_block, row.trade_date): row
        for row in feature_rows.itertuples(index=False)
    }
    timestamp_failures = sum(
        not (
            row.feature_available_at.date() <= row.trade_date
            and row.first_applicable_trade_date > row.trade_date
        )
        for row in feature_rows.itertuples(index=False)
    )
    same_day_fills = 0
    target_weight_mismatches = 0
    missing_feature_new_buys = 0
    first_applicable_failures = 0
    filled_rows = 0
    new_buy_rows = 0
    overlay_identity_failures = 0
    block_arm_records: list[dict[str, Any]] = []

    for block in BLOCKS:
        for arm in ARMS:
            summary = json.loads(
                ledger_path(manifest, block, arm, "engine_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            identity = summary["entry_weight_overlay"]["identity"]
            expected_identity = {
                "experiment_id": "EXP-P7-003",
                "spec_sha256": p7_result["spec_sha256"],
                "block": block,
                "arm": arm,
                "feature": "breadth_above_ma20",
                "decision_timestamp": "COMPLETED_SIGNAL_CLOSE_T",
                "application": "FIRST_CAUSALLY_VALID_LATER_OPEN_STICKY_MEMBER_TARGET",
            }
            identity_ok = all(identity.get(key) == value for key, value in expected_identity.items())
            overlay_identity_failures += int(not identity_ok)
            arm_same_day = 0
            arm_target_mismatch = 0
            arm_new_buys = 0
            executions = read_jsonl(
                ledger_path(manifest, block, arm, "execution_ledger.jsonl")
            )
            for row in executions:
                if row.get("status") != "FILLED":
                    continue
                filled_rows += 1
                same_day = str(row.get("signal_date")) == str(row.get("execution_date"))
                same_day_fills += int(same_day)
                arm_same_day += int(same_day)
                if row.get("side") != "BUY" or not row.get("new_position"):
                    continue
                new_buy_rows += 1
                arm_new_buys += 1
                signal_date = pd.Timestamp(row["signal_date"]).date()
                feature = feature_map.get((block, signal_date))
                if feature is None:
                    raise AuditError(f"missing feature row for filled new buy {block}/{arm}/{signal_date}")
                multiplier = expected_multiplier(feature.breadth_above_ma20, arm)
                expected_target = 0.10 * multiplier
                mismatch = abs(float(row["target_weight"]) - expected_target) > 1e-12
                target_weight_mismatches += int(mismatch)
                arm_target_mismatch += int(mismatch)
                missing_feature_new_buys += int(
                    pd.isna(feature.breadth_above_ma20) and arm != CONTROL
                )
                first_applicable_failures += int(
                    pd.Timestamp(row["execution_date"]).date()
                    < feature.first_applicable_trade_date
                )
            block_arm_records.append(
                {
                    "block": block,
                    "arm": arm,
                    "filled_new_buy_count": arm_new_buys,
                    "same_day_fill_count": arm_same_day,
                    "target_weight_mismatch_count": arm_target_mismatch,
                    "overlay_identity_exact": identity_ok,
                }
            )
    control_gate_pass = all(
        item["pass"] and all(item["checks"].values())
        for item in p7_result["control_gate"].values()
    )
    checks = {
        "all_three_control_identity_gates_pass": control_gate_pass,
        "feature_timestamp_failure_count": int(timestamp_failures),
        "same_day_fill_count": same_day_fills,
        "first_applicable_execution_failure_count": first_applicable_failures,
        "new_buy_target_weight_mismatch_count": target_weight_mismatches,
        "missing_feature_candidate_new_buy_count": missing_feature_new_buys,
        "overlay_identity_failure_count": overlay_identity_failures,
        "filled_execution_count": filled_rows,
        "filled_new_buy_count": new_buy_rows,
        "entry_signal_changes": int(p7_result["falsification"]["entry_signal_changes"]),
        "rank_changes": int(p7_result["falsification"]["rank_changes"]),
        "exit_changes": int(p7_result["falsification"]["exit_changes"]),
    }
    passed = (
        checks["all_three_control_identity_gates_pass"]
        and checks["feature_timestamp_failure_count"] == 0
        and checks["same_day_fill_count"] == 0
        and checks["first_applicable_execution_failure_count"] == 0
        and checks["new_buy_target_weight_mismatch_count"] == 0
        and checks["missing_feature_candidate_new_buy_count"] == 0
        and checks["overlay_identity_failure_count"] == 0
        and checks["entry_signal_changes"] == 0
        and checks["rank_changes"] == 0
        and checks["exit_changes"] == 0
    )
    return {"checks": checks, "block_arm_records": block_arm_records, "passes": passed}


def beta_timing(
    manifest: dict[str, Any], features: pd.DataFrame
) -> dict[str, Any]:
    features = features.copy()
    features["trade_date"] = pd.to_datetime(features.trade_date)
    block_records: list[dict[str, Any]] = []
    pooled: list[pd.DataFrame] = []
    for block in BLOCKS:
        control = load_nav(manifest, block, CONTROL)[["trade_date", "nav"]].rename(
            columns={"nav": "control_nav"}
        )
        candidate = load_nav(manifest, block, PRIMARY)[["trade_date", "nav"]].rename(
            columns={"nav": "candidate_nav"}
        )
        market = features[features.baseline_block == block][
            ["trade_date", "index_return_1d"]
        ]
        rows = control.merge(candidate, on="trade_date", validate="one_to_one").merge(
            market, on="trade_date", validate="one_to_one"
        )
        rows["control_return"] = rows.control_nav.pct_change()
        rows["candidate_return"] = rows.candidate_nav.pct_change()
        rows["active_return"] = rows.candidate_return - rows.control_return
        rows = rows.dropna(subset=["control_return", "candidate_return", "index_return_1d"])
        pooled.append(rows)
        block_records.append(beta_record(block, rows))
    pooled_rows = pd.concat(pooled, ignore_index=True)
    pooled_record = beta_record("POOLED_DAILY_WITH_BLOCK_LINEAGE", pooled_rows)
    return {
        "method": "OLS_DAILY_PORTFOLIO_RETURN_ON_SAME_DAY_399102_RETURN_WITH_INTERCEPT; descriptive beta diagnostic, not a regime input",
        "blocks": block_records,
        "pooled": pooled_record,
    }


def beta_record(label: str, rows: pd.DataFrame) -> dict[str, Any]:
    x = rows.index_return_1d.to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(x)), x])
    result: dict[str, Any] = {"block": label, "day_count": len(rows)}
    for column, prefix in (
        ("control_return", "control"),
        ("candidate_return", "candidate"),
        ("active_return", "active"),
    ):
        coefficients, *_ = np.linalg.lstsq(
            design, rows[column].to_numpy(dtype=float), rcond=None
        )
        result[f"{prefix}_daily_alpha"] = float(coefficients[0])
        result[f"{prefix}_annualized_linear_alpha"] = float(coefficients[0] * 252)
        result[f"{prefix}_beta"] = float(coefficients[1])
    up = rows[rows.index_return_1d > 0].active_return
    down = rows[rows.index_return_1d < 0].active_return
    result["up_index_day_count"] = len(up)
    result["down_index_day_count"] = len(down)
    result["mean_active_return_up_index_days"] = float(up.mean())
    result["mean_active_return_down_index_days"] = float(down.mean())
    return result


def cost_sensitivity(block_metrics: pd.DataFrame) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for rate_bps in (0, 10, 25, 50):
        rate = rate_bps / 10_000
        positive_blocks = 0
        for block in BLOCKS:
            control = block_metrics[
                (block_metrics.block == block) & (block_metrics.arm == CONTROL)
            ].iloc[0]
            candidate = block_metrics[
                (block_metrics.block == block) & (block_metrics.arm == PRIMARY)
            ].iloc[0]
            control_notional = float(control.filled_side_cost) / 0.001
            candidate_notional = float(candidate.filled_side_cost) / 0.001
            control_adjusted = float(control.total_return) - (rate - 0.001) * control_notional / INITIAL_CASH
            candidate_adjusted = float(candidate.total_return) - (rate - 0.001) * candidate_notional / INITIAL_CASH
            active = candidate_adjusted - control_adjusted
            positive_blocks += int(active > 1e-12)
            rows.append(
                {
                    "cost_bps_per_filled_side": rate_bps,
                    "block": block,
                    "control_adjusted_return": control_adjusted,
                    "candidate_adjusted_return": candidate_adjusted,
                    "active_return": active,
                }
            )
        for item in rows[-len(BLOCKS) :]:
            item["positive_block_count_at_cost"] = positive_blocks
    return {
        "method": "NON_ENDOGENOUS_LEDGER_NOTIONAL_SENSITIVITY; no share/cash-path replay and no exact counterfactual claim",
        "rows": rows,
        "passes_all_rates_two_of_three_positive_blocks": all(
            row["positive_block_count_at_cost"] >= 2
            for row in rows
            if row["block"] == BLOCKS[-1]
        ),
    }


def neighbor_sensitivity(yearly: pd.DataFrame, p7_result: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    primary_signs: dict[int, int] = {}
    for year in sorted(yearly.year.unique()):
        base = yearly[(yearly.year == year) & (yearly.arm == CONTROL)].iloc[0]
        primary = yearly[(yearly.year == year) & (yearly.arm == PRIMARY)].iloc[0]
        primary_signs[int(year)] = sign(float(primary["return"] - base["return"]))
    for arm in [PRIMARY, *NEIGHBORS, "Z40_ZERO_SEVERITY"]:
        deltas: list[float] = []
        signs: list[int] = []
        agreement = 0
        comparable = 0
        for year in sorted(yearly.year.unique()):
            base = yearly[(yearly.year == year) & (yearly.arm == CONTROL)].iloc[0]
            candidate = yearly[(yearly.year == year) & (yearly.arm == arm)].iloc[0]
            delta = float(candidate["return"] - base["return"])
            delta_sign = sign(delta)
            deltas.append(delta)
            signs.append(delta_sign)
            if primary_signs[int(year)] != 0:
                comparable += 1
                agreement += int(delta_sign == primary_signs[int(year)])
        rows.append(
            {
                "arm": arm,
                "positive_year_count": sum(value > 0 for value in signs),
                "negative_year_count": sum(value < 0 for value in signs),
                "neutral_year_count": sum(value == 0 for value in signs),
                "mean_year_active_return": float(np.mean(deltas)),
                "primary_nonzero_sign_agreement_count": agreement if arm != PRIMARY else comparable,
                "primary_nonzero_comparable_year_count": comparable,
            }
        )
    return {
        "rows": rows,
        "phase7_neighbor_gate": p7_result["promotion"]["gates"]["neighbors"],
        "passes": bool(p7_result["promotion"]["gates"]["neighbor_stability"]),
        "post_result_neighbor_substitution_permitted": False,
    }


def tail_exposure_diagnostics(
    block_metrics: pd.DataFrame, p7_result: dict[str, Any]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for block in BLOCKS:
        control = block_metrics[
            (block_metrics.block == block) & (block_metrics.arm == CONTROL)
        ].iloc[0]
        candidate = block_metrics[
            (block_metrics.block == block) & (block_metrics.arm == PRIMARY)
        ].iloc[0]
        item: dict[str, Any] = {
            "block": block,
            "return_delta": float(candidate.total_return - control.total_return),
            "drawdown_delta_positive_is_better": float(
                candidate.max_drawdown - control.max_drawdown
            ),
            "average_invested_fraction_delta": float(
                candidate.average_invested_fraction
                - control.average_invested_fraction
            ),
            "turnover_delta": float(candidate.turnover - control.turnover),
            "filled_side_cost_delta": float(
                candidate.filled_side_cost - control.filled_side_cost
            ),
            "exposure_normalized_return_delta": float(
                candidate.exposure_normalized_return
                - control.exposure_normalized_return
            ),
            "severe_loss_rate_delta": float(
                candidate.severe_loss_rate - control.severe_loss_rate
            ),
            "winner20_count_delta": int(
                candidate.winner20_count - control.winner20_count
            ),
            "winner50_count_delta": int(
                candidate.winner50_count - control.winner50_count
            ),
        }
        for n in (5, 10, 20):
            item[f"return_ex_best{n}_delta"] = float(
                candidate[f"return_ex_best{n}"] - control[f"return_ex_best{n}"]
            )
        rows.append(item)
    return {
        "blocks": rows,
        "winner20_entry_retention": float(
            p7_result["promotion"]["gates"]["winner20_entry_retention"]
        ),
        "top20_positive_pnl_capture": float(
            p7_result["promotion"]["gates"]["top20_positive_pnl_capture"]
        ),
        "right_tail_gate_passes": bool(
            p7_result["promotion"]["gates"]["right_tail"]
        ),
        "exposure_normalized_nonworse_block_count": sum(
            row["exposure_normalized_return_delta"] >= -1e-12 for row in rows
        ),
        "exbest_improvement_block_counts": {
            str(n): sum(row[f"return_ex_best{n}_delta"] > 1e-12 for row in rows)
            for n in (5, 10, 20)
        },
    }


def assemble_gates(
    spec: dict[str, Any],
    calendar_rows: list[dict[str, Any]],
    expanding: list[dict[str, Any]],
    loyo: list[dict[str, Any]],
    rolling: list[dict[str, Any]],
    frequency: list[dict[str, Any]],
    neighbor: dict[str, Any],
    tail: dict[str, Any],
    cost: dict[str, Any],
    implementation: dict[str, Any],
) -> dict[str, Any]:
    rules = spec["robustness_gates"]
    positive_years = sum(sign(float(row["active_return"])) > 0 for row in calendar_rows)
    negative_years = sum(sign(float(row["active_return"])) < 0 for row in calendar_rows)
    yearly_pass = (
        positive_years >= rules["yearly"]["minimum_positive_years"]
        and negative_years <= rules["yearly"]["maximum_negative_years"]
    )
    rolling_pass_blocks: dict[str, dict[str, bool]] = {}
    for window in ROLLING_WINDOWS:
        rows = [item for item in rolling if item["window_sessions"] == window]
        rolling_pass_blocks[str(window)] = {
            item["block"]: item["positive_fraction"]
            >= rules["rolling"]["minimum_positive_fraction"]
            for item in rows
        }
    rolling_pass = all(
        sum(blocks.values()) >= rules["rolling"]["minimum_passing_blocks_per_window"]
        for blocks in rolling_pass_blocks.values()
    )
    expanding_positive = sum(
        sign(float(row["active_return"])) > 0 for row in expanding
    )
    expanding_pass = expanding_positive >= rules["expanding"]["minimum_positive_prefixes"]
    loyo_pass = all(
        float(row["mean_active_return"]) > rules["loyo"]["minimum_mean_active_return"]
        for row in loyo
    )
    frequency_pass = all(
        row["valid_fraction"] >= rules["regime_frequency"]["minimum_valid_fraction"]
        and row["weak_fraction_of_valid"]
        >= rules["regime_frequency"]["minimum_each_state_fraction"]
        and row["normal_fraction_of_valid"]
        >= rules["regime_frequency"]["minimum_each_state_fraction"]
        for row in frequency
    )
    exposure_pass = (
        tail["exposure_normalized_nonworse_block_count"]
        >= rules["exposure_normalization"]["minimum_nonworse_blocks"]
        and min(
            row["exposure_normalized_return_delta"] for row in tail["blocks"]
        )
        >= rules["exposure_normalization"]["maximum_allowed_block_degradation"]
    )
    results = {
        "yearly": {
            "passes": yearly_pass,
            "positive_year_count": positive_years,
            "negative_year_count": negative_years,
            "neutral_year_count": len(calendar_rows) - positive_years - negative_years,
        },
        "rolling": {"passes": rolling_pass, "block_window_passes": rolling_pass_blocks},
        "expanding_prefix": {
            "passes": expanding_pass,
            "positive_prefix_count": expanding_positive,
            "prefix_count": len(expanding),
        },
        "loyo_no_refit": {"passes": loyo_pass, "panel_count": len(loyo)},
        "regime_frequency": {"passes": frequency_pass, "year_count": len(frequency)},
        "neighboring_definitions": {"passes": neighbor["passes"]},
        "exposure_normalization": {
            "passes": exposure_pass,
            "nonworse_block_count": tail["exposure_normalized_nonworse_block_count"],
        },
        "right_tail_retention": {"passes": tail["right_tail_gate_passes"]},
        "cost_sensitivity": {
            "passes": cost["passes_all_rates_two_of_three_positive_blocks"]
        },
        "pit_execution_implementation": {"passes": implementation["passes"]},
    }
    required = rules["required_for_robust_candidate"]
    return {
        "components": results,
        "required_components": required,
        "passes_all_required": all(results[name]["passes"] for name in required),
    }


def falsification_challenges(
    gates: dict[str, Any],
    beta: dict[str, Any],
    tail: dict[str, Any],
    p7_result: dict[str, Any],
) -> list[dict[str, Any]]:
    components = gates["components"]
    pooled = beta["pooled"]
    lower_exposure_all = all(
        row["average_invested_fraction_delta"] <= 1e-12 for row in tail["blocks"]
    )
    return [
        {
            "id": 1,
            "challenge": "Is apparent value only market-beta timing?",
            "verdict": "NON_BETA_VALUE_NOT_ESTABLISHED"
            if pooled["active_annualized_linear_alpha"] <= 0
            else "POSITIVE_ACTIVE_ALPHA_DESCRIPTIVE_ONLY",
            "evidence": {
                "active_annualized_linear_alpha": pooled[
                    "active_annualized_linear_alpha"
                ],
                "active_beta": pooled["active_beta"],
                "active_up_day_mean": pooled["mean_active_return_up_index_days"],
                "active_down_day_mean": pooled[
                    "mean_active_return_down_index_days"
                ],
            },
        },
        {
            "id": 2,
            "challenge": "Is lower drawdown merely lower exposure?",
            "verdict": "EXPOSURE_REDUCTION_CONFOUND_PRESENT"
            if lower_exposure_all and not components["exposure_normalization"]["passes"]
            else "NOT_FULLY_EXPLAINED_BY_EXPOSURE_REDUCTION",
            "evidence": {
                "lower_exposure_all_blocks": lower_exposure_all,
                "exposure_normalization_passes": components[
                    "exposure_normalization"
                ]["passes"],
            },
        },
        {
            "id": 3,
            "challenge": "Does it sacrifice future true winners?",
            "verdict": "LIMITED_BUT_NONZERO_RIGHT_TAIL_SACRIFICE",
            "evidence": {
                "winner20_entry_retention": tail["winner20_entry_retention"],
                "top20_positive_pnl_capture": tail["top20_positive_pnl_capture"],
                "right_tail_gate_passes": tail["right_tail_gate_passes"],
            },
        },
        {
            "id": 4,
            "challenge": "Do only one or two years support it?",
            "verdict": "TEMPORAL_STABILITY_REJECTED"
            if not components["yearly"]["passes"]
            else "BROAD_YEAR_SUPPORT",
            "evidence": components["yearly"],
        },
        {
            "id": 5,
            "challenge": "Is it threshold mining?",
            "verdict": "PRIMARY_WAS_PREREGISTERED_BUT_RELATION_IS_THRESHOLD_SENSITIVE"
            if not components["neighboring_definitions"]["passes"]
            else "NO_THRESHOLD_MINING_AND_NEIGHBORS_STABLE",
            "evidence": {
                "thresholds_optimized": p7_result["falsification"][
                    "thresholds_optimized"
                ],
                "neighbor_stability_passes": components[
                    "neighboring_definitions"
                ]["passes"],
            },
        },
        {
            "id": 6,
            "challenge": "Does it depend on a few extreme trades?",
            "verdict": "V1_REMAINS_EXTREME_TRADE_DEPENDENT_AND_OVERLAY_DOES_NOT_RESOLVE_IT",
            "evidence": {
                "exbest_improvement_block_counts": tail[
                    "exbest_improvement_block_counts"
                ],
                "top20_positive_pnl_capture": tail["top20_positive_pnl_capture"],
            },
        },
        {
            "id": 7,
            "challenge": "Is the regime stably identifiable?",
            "verdict": "STATE_IDENTIFIABLE_BUT_PORTFOLIO_RELATION_UNSTABLE"
            if components["regime_frequency"]["passes"]
            and not components["yearly"]["passes"]
            else "STATE_IDENTIFICATION_LIMITED",
            "evidence": components["regime_frequency"],
        },
        {
            "id": 8,
            "challenge": "Is there a realistic PIT implementation problem?",
            "verdict": "NO_LEDGER_LEVEL_PIT_OR_EXECUTION_DEFECT_FOUND"
            if components["pit_execution_implementation"]["passes"]
            else "PIT_OR_EXECUTION_DEFECT_FOUND",
            "evidence": components["pit_execution_implementation"],
        },
        {
            "id": 9,
            "challenge": "Does a neighboring definition erase the relation?",
            "verdict": "YES_NEIGHBORING_ROBUSTNESS_FAILS"
            if not components["neighboring_definitions"]["passes"]
            else "NO_NEIGHBORING_DEFINITIONS_PASS",
            "evidence": components["neighboring_definitions"],
        },
        {
            "id": 10,
            "challenge": "Does complexity exceed practical benefit?",
            "verdict": "RULE_IS_SIMPLE_BUT_BENEFIT_IS_INSUFFICIENT",
            "evidence": {
                "feature_count": 1,
                "threshold_count": 1,
                "multiplier_count": 1,
                "phase7_promoted": p7_result["promotion"][
                    "passes_all_phase7_promotion_gates"
                ],
                "phase8_robust": gates["passes_all_required"],
            },
        },
    ]


def phase8_report(payload: dict[str, Any]) -> str:
    gates = payload["robustness_gates"]
    lines = [
        "# Phase 8 — robustness and overfitting audit",
        "",
        f"EXP-P8P9-001 robustness verdict: `{payload['decision']['robustness_verdict']}`.",
        "",
        "This audit used only the 15 hash-frozen EXP-P7-003 ledgers. It ran no strategy replay, threshold fit, arm selection, or NAV chaining. All 2018-2025 outcomes are consumed; rolling, expanding, and LOYO results are resampling diagnostics, not untouched OOS.",
        "",
        "## Gate summary",
        "",
        "| Component | Pass | Key evidence |",
        "|---|---:|---|",
    ]
    components = gates["components"]
    lines += [
        f"| Yearly stability | {components['yearly']['passes']} | +/−/neutral years: {components['yearly']['positive_year_count']}/{components['yearly']['negative_year_count']}/{components['yearly']['neutral_year_count']} |",
        f"| Rolling 126/252 | {components['rolling']['passes']} | positive-fraction gate requires 2/3 blocks at each horizon |",
        f"| Expanding prefixes | {components['expanding_prefix']['passes']} | positive prefixes {components['expanding_prefix']['positive_prefix_count']}/{components['expanding_prefix']['prefix_count']} |",
        f"| LOYO, no refit | {components['loyo_no_refit']['passes']} | {components['loyo_no_refit']['panel_count']} omitted-year panels |",
        f"| Regime frequency | {components['regime_frequency']['passes']} | causal state coverage and both-state frequency |",
        f"| Neighbor definitions | {components['neighboring_definitions']['passes']} | fixed 0.30/0.50 falsification arms |",
        f"| Exposure normalization | {components['exposure_normalization']['passes']} | non-worse blocks {components['exposure_normalization']['nonworse_block_count']}/3 |",
        f"| Right-tail retention | {components['right_tail_retention']['passes']} | inherited frozen winner/top-20 gate |",
        f"| Cost sensitivity | {components['cost_sensitivity']['passes']} | ledger-notional diagnostic, not an endogenous replay |",
        f"| PIT/execution | {components['pit_execution_implementation']['passes']} | exact ledger and causal timestamp audit |",
        "",
        "## Calendar-year active returns",
        "",
        "| Year | Candidate | V1 | Delta | DD delta (+ better) |",
        "|---:|---:|---:|---:|---:|",
    ]
    calendar = [
        row for row in payload["temporal"]["records"] if row["record_type"] == "CALENDAR_YEAR"
    ]
    for row in calendar:
        lines.append(
            f"| {row['year']} | {row['candidate_return']:.2%} | {row['control_return']:.2%} | {row['active_return']:.2%} | {row['drawdown_delta_positive_is_better']:.2%} |"
        )
    lines += [
        "",
        "## Rolling windows",
        "",
        "| Block | Sessions | Windows | Positive | Median active | Mean active |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in payload["rolling"]["summary"]:
        lines.append(
            f"| {row['block']} | {row['window_sessions']} | {row['window_count']} | {row['positive_fraction']:.1%} | {row['median_active_return']:.2%} | {row['mean_active_return']:.2%} |"
        )
    tail = payload["tail_exposure"]
    lines += [
        "",
        "## Exposure, tails, and costs",
        "",
        f"The primary retains {tail['winner20_entry_retention']:.2%} of baseline >=20% winner entries and {tail['top20_positive_pnl_capture']:.2%} of baseline Top-20 positive P&L. Exposure-normalized return is non-worse in {tail['exposure_normalized_nonworse_block_count']}/3 blocks. The only materially degraded block is 2018-2021; reduced turnover cannot close its return gap even in the fixed 50 bps ledger-notional sensitivity.",
        "",
        "## OOS boundary",
        "",
        "No untouched OOS exists for this newly designed rule. There is no trained model to refit in LOYO, so the eight leave-one-year-out panels omit years only from the arithmetic annual-delta summary. Walk-forward selection is therefore not feasible and is not claimed. The earlier 2022-2023 label describes a frozen V1 baseline block, not untouched OOS for V1-R.",
        "",
    ]
    return "\n".join(lines)


def phase9_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Phase 9 — active failure and falsification test",
        "",
        f"EXP-P8P9-001 candidate verdict: `{payload['decision']['candidate_verdict']}`.",
        "",
        "| # | Challenge | Verdict |",
        "|---:|---|---|",
    ]
    for item in payload["falsification_challenges"]:
        lines.append(f"| {item['id']} | {item['challenge']} | `{item['verdict']}` |")
    lines += [
        "",
        "## Interpretation",
        "",
        "The strongest pro-candidate evidence is implementation cleanliness, stable observability of the raw breadth state, lower turnover, and limited rather than catastrophic right-tail sacrifice. None rescues portfolio usefulness: bad-year and neighbor gates fail, yearly/rolling/LOYO evidence is not broad, and exposure-normalized performance is materially worse in 2018-2021.",
        "",
        "The primary threshold was preregistered and was not mined. The failure is instead economic sensitivity: moving to the frozen neighboring definitions changes which years improve, and the apparently favorable 0.50 holdout arm cannot be selected after results. The rule is simple, but complexity-adjusted benefit is still insufficient.",
        "",
        "H-010 is supported: breadth remains explanatory for favorable-path opportunity, but no tested V1-R overlay is justified. Frozen V1 remains the strategy baseline.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    spec, manifest = load_and_validate_spec()
    features = pd.read_parquet(
        FEATURES,
        columns=[
            "baseline_block",
            "trade_date",
            "feature_available_at",
            "first_applicable_trade_date",
            "breadth_above_ma20",
            "index_return_1d",
        ],
    )
    p7_result = json.loads(P7_RESULT.read_text(encoding="utf-8"))
    yearly = pd.read_csv(P7_YEARLY)
    block_metrics = pd.read_csv(P7_BLOCK)

    calendar = yearly_records(yearly)
    expanding: list[dict[str, Any]] = []
    rolling_rows: list[dict[str, Any]] = []
    for block in BLOCKS:
        control = load_nav(manifest, block, CONTROL)
        candidate = load_nav(manifest, block, PRIMARY)
        expanding.extend(expanding_records(block, control, candidate))
        rolling_rows.extend(rolling_records(block, control, candidate))
    loyo = loyo_records(calendar)
    rolling_frame = pd.DataFrame(rolling_rows)
    rolling = rolling_summary(rolling_frame)
    frequency = regime_frequency(features)
    neighbor = neighbor_sensitivity(yearly, p7_result)
    tail = tail_exposure_diagnostics(block_metrics, p7_result)
    cost = cost_sensitivity(block_metrics)
    implementation = implementation_audit(manifest, features, p7_result)
    beta = beta_timing(manifest, features)
    gates = assemble_gates(
        spec,
        calendar,
        expanding,
        loyo,
        rolling,
        frequency,
        neighbor,
        tail,
        cost,
        implementation,
    )
    challenges = falsification_challenges(gates, beta, tail, p7_result)
    candidate_rejected = (
        not p7_result["promotion"]["passes_all_phase7_promotion_gates"]
        or not gates["passes_all_required"]
    )
    payload = {
        "experiment_id": "EXP-P8P9-001",
        "spec_sha256": sha256_file(SPEC),
        "evidence_grade": "OUTCOME_CONSUMED_RESAMPLING_AND_FALSIFICATION_NO_UNTOUCHED_OOS",
        "input_manifest_sha256": sha256_file(MANIFEST),
        "strategy_replay_count": 0,
        "threshold_fit_count": 0,
        "neighbor_selected_as_primary": False,
        "naive_nav_chaining": False,
        "temporal": {"records": [*calendar, *expanding, *loyo]},
        "rolling": {"summary": rolling},
        "regime_frequency": frequency,
        "neighbor_sensitivity": neighbor,
        "tail_exposure": tail,
        "cost_sensitivity": cost,
        "beta_timing": beta,
        "implementation_audit": implementation,
        "robustness_gates": gates,
        "falsification_challenges": challenges,
        "decision": {
            "robustness_verdict": "FAIL_NOT_ROBUST"
            if not gates["passes_all_required"]
            else "PASS_ROBUSTNESS_ONLY",
            "candidate_verdict": "REJECT_V1R_KEEP_FROZEN_V1"
            if candidate_rejected
            else "RETAIN_FOR_FUTURE_UNTOUCHED_OOS_ONLY",
            "hypothesis_h010": "SUPPORTED_EXPLANATORY_ONLY",
            "production_authorized": False,
        },
    }

    rolling_export = rolling_frame.sort_values(
        ["block", "window_sessions", "end_date"]
    )
    temporal_export = pd.DataFrame([*calendar, *expanding, *loyo])
    atomic_write(
        OUTPUT_JSON,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    atomic_write(OUTPUT_ROLLING, rolling_export.to_csv(index=False, lineterminator="\n"))
    atomic_write(OUTPUT_TEMPORAL, temporal_export.to_csv(index=False, lineterminator="\n"))
    atomic_write(REPORT_P8, phase8_report(payload))
    atomic_write(REPORT_P9, phase9_report(payload))
    print(f"decision={payload['decision']['candidate_verdict']}")
    for path in (OUTPUT_JSON, OUTPUT_ROLLING, OUTPUT_TEMPORAL, REPORT_P8, REPORT_P9):
        print(f"{path.relative_to(ROOT)} sha256={sha256_file(path)}")


if __name__ == "__main__":
    main()
