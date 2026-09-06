#!/usr/bin/env python3
"""Execute EXP-P7-003 bounded raw-breadth entry-exposure candidate replays."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cyq_game.data import DataAssetRegistry, DataPurpose
import run_chinext_v1_extended_replay as extended_replay
from run_chinext_v1_full_survivor import INITIAL_CASH, read_jsonl
from run_chinext_v1_pit_replay import reconstruct_round_trips
from run_chinext_v1_smoke import (
    DEFAULT_CALENDAR,
    DEFAULT_DAILY_ROOT,
    DEFAULT_MARKET,
    run,
    sha256_file,
)

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
CHINEXT = ROOT / "research/chinext_v1"
REGISTRY = ROOT / "configs/data_asset_registry.json"
BASE_SPEC = WORK / "experiments/EXP-P7-001_spec.json"
WARMUP_SPEC = WORK / "experiments/EXP-P7-002_spec.json"
SPEC = WORK / "experiments/EXP-P7-003_spec.json"
FEATURES = WORK / "artifacts/daily_regime_features.parquet"
BASELINE_MANIFEST = WORK / "artifacts/baseline_manifest.json"
STRATEGY = CHINEXT / "strategy/chinext_v1_exploratory.py"
RUNNER = CHINEXT / "scripts/run_chinext_v1_smoke.py"
MATERIALIZER = CHINEXT / "scripts/run_chinext_v1_extended_replay.py"
OUTPUT_ROOT = WORK / "output/phase7_v1r"
OUTPUT_JSON = WORK / "artifacts/v1r_candidate_results.json"
OUTPUT_YEARLY = WORK / "artifacts/v1r_candidate_yearly_metrics.csv"
OUTPUT_BLOCK = WORK / "artifacts/v1r_candidate_trade_metrics.csv"
REPORT = WORK / "reports/phase7_v1r_exposure_candidate.md"

EXPECTED = {
    BASE_SPEC: "db1ba58b240d0bb21b6289815aa66c3145aceae84fb86a51fdfe3e775ec5d4c8",
    WARMUP_SPEC: "305442a5e442181bc23214a22e2413d3a24f54c722be4a52e8a957ca97e13eb4",
    SPEC: "620dbbcbde02fe1dae1867a7237dfa23eee85ad3d87b8b80c28d491db387911e",
    FEATURES: "5fe1ec1cb1bdfa922dd838bd1f559de9463d4926f56dfed09427d826c7465bc6",
    BASELINE_MANIFEST: "682b45455442f00e15e6273622ab6566d1c5c1d94069efc5fbbd40cb17f0977b",
    STRATEGY: "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a",
    RUNNER: "3136edf9fc6a8a9f0a8d42487d8703943b0eaacaccdd188be18a6274cb4793e3",
    MATERIALIZER: "17123bf4570638f81bc9d2a185926d8ac81cb2cf76f6dbafc4bf06fb63a3b2ae",
    DEFAULT_MARKET.resolve(): "e096e4d50d0b6ac5062d4940bf0c17c0165dd1c44d5f49ce12d0e3754daa8779",
    DEFAULT_CALENDAR: "1ccd72b98ead430557f214917ca161dd2f92c26c605262bcd9fe7bc3db2c64ae",
}

ARMS = [
    "C0_ALL_ONE_CONTROL",
    "A40_HALF_PRIMARY",
    "N30_HALF_NEIGHBOR",
    "N50_HALF_NEIGHBOR",
    "Z40_ZERO_SEVERITY",
]

BLOCKS = {
    "EXTENDED_2018_2021": {
        "start": date(2018, 1, 2),
        "end": date(2021, 12, 31),
        "warmup": date(2017, 4, 12),
        "authorization_start": date(2017, 4, 12),
        "authorization_id": "CYQ-AUTH-CHINEXT-V1R-P7-2017-2021-V1",
        "manifest": CHINEXT / "reports/chinext_v1_free_historical_state_manifest.json",
        "security_master": CHINEXT / "data/pit_free_2017_2021/normalized/security_master.parquet",
        "daily_historical_state": CHINEXT / "data/pit_free_2017_2021/normalized/daily_historical_state.parquet",
        "baseline_output": CHINEXT / "output/chinext_v1_extended_2018_2021",
    },
    "HOLDOUT_O0_2022_2023": {
        "start": date(2022, 1, 4),
        "end": date(2023, 12, 29),
        "warmup": date(2021, 7, 8),
        "authorization_start": date(2022, 1, 4),
        "authorization_id": "CYQ-AUTH-CHINEXT-V1R-P7-2022-2023-V1",
        "manifest": CHINEXT / "reports/chinext_v1_pit_holdout_2022_2023_master_manifest.json",
        "membership": CHINEXT / "data/pit_holdout_2022_2023/daily_membership.parquet",
        "security_master": CHINEXT / "data/pit_holdout_2022_2023/security_master.parquet",
        "baseline_output": CHINEXT / "output/chinext_v1_phase9b_oos/O0_BASELINE",
    },
    "DEVELOPMENT_2024_2025": {
        "start": date(2024, 1, 2),
        "end": date(2025, 12, 31),
        "warmup": date(2023, 1, 1),
        "authorization_start": date(2024, 1, 2),
        "authorization_id": "CYQ-AUTH-CHINEXT-V1R-P7-2024-2025-V1",
        "manifest": CHINEXT / "reports/chinext_v1_pit_master_manifest.json",
        "membership": CHINEXT / "data/pit_2024_2025/daily_membership.parquet",
        "security_master": CHINEXT / "data/pit_2024_2025/security_master.parquet",
        "baseline_output": CHINEXT / "output/chinext_v1_pit_replay",
    },
}


class Phase7Error(RuntimeError):
    """Raised when the preregistered candidate or its lineage fails closed."""


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def validate_frozen_identities() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    mismatch = {
        str(path): {"expected": expected, "actual": sha256_file(path)}
        for path, expected in EXPECTED.items()
        if sha256_file(path) != expected
    }
    if mismatch:
        raise Phase7Error(f"frozen Phase 7 identity mismatch: {mismatch}")
    base = json.loads(BASE_SPEC.read_text(encoding="utf-8"))
    warmup = json.loads(WARMUP_SPEC.read_text(encoding="utf-8"))
    delta = json.loads(SPEC.read_text(encoding="utf-8"))
    if base.get("status") != "FROZEN_BEFORE_ANY_CANDIDATE_PORTFOLIO_RESULT":
        raise Phase7Error("base Phase 7 specification is not frozen")
    if warmup.get("status") != "FROZEN_BEFORE_ANY_CANDIDATE_PORTFOLIO_RESULT":
        raise Phase7Error("EXP-P7-002 is not frozen")
    if warmup["base_spec"]["sha256"] != EXPECTED[BASE_SPEC]:
        raise Phase7Error("EXP-P7-002 base-spec binding mismatch")
    if set(warmup["replacements"]) != {
        "experiment_id",
        "status",
        "bounded_block_inputs.DEVELOPMENT_2024_2025.warmup_start",
    }:
        raise Phase7Error("EXP-P7-002 contains an unauthorized replacement")
    if delta.get("status") != "FROZEN_BEFORE_ANY_CANDIDATE_PORTFOLIO_RESULT":
        raise Phase7Error("EXP-P7-003 is not frozen")
    if delta["base_spec"]["sha256"] != EXPECTED[WARMUP_SPEC]:
        raise Phase7Error("EXP-P7-003 base-spec binding mismatch")
    if set(delta["replacements"]) != {"experiment_id", "status"}:
        raise Phase7Error("EXP-P7-003 contains an unauthorized replacement")
    baseline = json.loads(BASELINE_MANIFEST.read_text(encoding="utf-8"))
    return base, delta, baseline


def authorization_artifacts(block: str) -> dict[str, tuple[Path, str]]:
    common = {
        "regime_features": (FEATURES, sha256_file(FEATURES)),
        "phase7_spec": (SPEC, sha256_file(SPEC)),
        "overlay_runner": (RUNNER, sha256_file(RUNNER)),
        "candidate_wrapper": (Path(__file__).resolve(), sha256_file(Path(__file__).resolve())),
    }
    definition = BLOCKS[block]
    if block == "EXTENDED_2018_2021":
        return {
            "daily_historical_state": (
                definition["daily_historical_state"],
                sha256_file(definition["daily_historical_state"]),
            ),
            "security_master": (
                definition["security_master"],
                sha256_file(definition["security_master"]),
            ),
            **common,
            "extended_materializer": (MATERIALIZER, sha256_file(MATERIALIZER)),
        }
    return {
        "daily_membership": (
            definition["membership"], sha256_file(definition["membership"])
        ),
        "security_master": (
            definition["security_master"], sha256_file(definition["security_master"])
        ),
        **common,
    }


def authorize_all_blocks() -> dict[str, Any]:
    registry = DataAssetRegistry.load(REGISTRY)
    result: dict[str, Any] = {}
    for block, definition in BLOCKS.items():
        authorization = registry.authorize_bounded_research(
            definition["authorization_id"],
            purpose=DataPurpose.CHINEXT_PIT_B_RESEARCH,
            manifest_path=definition["manifest"],
            manifest_sha256=sha256_file(definition["manifest"]),
            artifacts=authorization_artifacts(block),
            start=definition["authorization_start"],
            end=definition["end"],
            dependency_asset_id="QD-007",
            consumer_path=Path(__file__).resolve(),
            strategy_path=STRATEGY,
            strategy_sha256=sha256_file(STRATEGY),
            current_survivor_fallback=False,
        )
        result[block] = {
            "authorization_id": authorization.authorization_id,
            "asset_id": authorization.asset_id,
            "scope": [authorization.scope_start.isoformat(), authorization.scope_end.isoformat()],
        }
    return {"registry_sha256": registry.sha256, "blocks": result}


def validate_append_only_registry_for_legacy_gate_c(spec: dict[str, Any]) -> dict[str, str]:
    compatibility = json.loads(SPEC.read_text(encoding="utf-8"))[
        "extended_registry_compatibility"
    ]
    legacy_bytes = subprocess.run(
        ["git", "show", "HEAD:configs/data_asset_registry.json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    legacy_hash = hashlib.sha256(legacy_bytes).hexdigest()
    if legacy_hash != compatibility["legacy_registry_sha256"]:
        raise Phase7Error("legacy registry bytes do not match EXP-P7-003")
    legacy = json.loads(legacy_bytes)
    current = json.loads(REGISTRY.read_text(encoding="utf-8"))
    current["assets"] = [
        row
        for row in current["assets"]
        if row.get("asset_id") not in {"CY-030", "CY-031", "CY-032"}
    ]
    current["bounded_authorizations"] = [
        row
        for row in current["bounded_authorizations"]
        if not str(row.get("authorization_id", "")).startswith(
            "CYQ-AUTH-CHINEXT-V1R-P7-"
        )
    ]
    additions = [
        row
        for row in current["change_log"]
        if str(row.get("change", "")).startswith(
            "Registered CY-030/CY-031/CY-032"
        )
    ]
    if len(additions) != 1:
        raise Phase7Error("current registry does not have one Phase 7 append log")
    current["change_log"] = [
        row for row in current["change_log"] if row not in additions
    ]
    if current != legacy:
        raise Phase7Error("current registry is not an exact semantic append-only extension")

    actual: dict[str, str] = {}
    failures: list[str] = []
    for role, path, expected in extended_replay.gate_c.iter_bound_files(
        spec["input_bindings"]
    ):
        if path.resolve() == REGISTRY.resolve():
            actual[role] = legacy_hash
            if expected != legacy_hash:
                failures.append(f"{role}: legacy expected {expected}, got {legacy_hash}")
            continue
        if not path.is_file():
            failures.append(f"{role}: missing {path}")
            continue
        digest = sha256_file(path)
        actual[role] = digest
        if digest != expected:
            failures.append(f"{role}: expected {expected}, got {digest}")
    if failures:
        raise Phase7Error(
            "legacy Gate C frozen input failure: " + "; ".join(failures)
        )
    return actual


def load_extended_transient_contract() -> dict[str, Any]:
    raw = extended_replay.REPLAY_SPEC.read_bytes()
    committed = subprocess.run(
        [
            "git",
            "show",
            f"HEAD:{extended_replay.REPLAY_SPEC_RELATIVE.as_posix()}",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    if raw != committed:
        raise Phase7Error("extended transient contract differs from committed bytes")
    payload = json.loads(raw)
    if payload.get("spec_id") != "CHINEXT-V1-EXTENDED-REPLAY-2018-2021-V1":
        raise Phase7Error("unexpected extended transient contract identity")
    if payload.get("status") != "FROZEN_BEFORE_FIRST_VIEW_REPLAY":
        raise Phase7Error("extended transient contract is not frozen")
    if payload.get("strategy_sha256") != sha256_file(STRATEGY):
        raise Phase7Error("extended transient contract strategy mismatch")
    if payload.get("gate_d_result_sha256") != sha256_file(extended_replay.GATE_D_RESULT):
        raise Phase7Error("extended transient contract Gate D mismatch")
    if not isinstance(payload.get("transient_input_contract"), dict):
        raise Phase7Error("extended transient input contract is missing")
    return payload


def load_feature_states() -> pd.DataFrame:
    frame = pd.read_parquet(
        FEATURES,
        columns=[
            "baseline_block",
            "trade_date",
            "feature_available_at",
            "first_applicable_trade_date",
            "eligible_count",
            "breadth_above_ma20",
        ],
    )
    frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.date
    frame["feature_available_at"] = pd.to_datetime(frame.feature_available_at)
    frame["first_applicable_trade_date"] = pd.to_datetime(
        frame.first_applicable_trade_date
    ).dt.date
    if frame.duplicated(["baseline_block", "trade_date"]).any():
        raise Phase7Error("regime feature table has duplicate block/date rows")
    available_date = frame.feature_available_at.dt.date
    if not (
        (available_date <= frame.trade_date)
        & (frame.first_applicable_trade_date > frame.trade_date)
    ).all():
        raise Phase7Error("regime feature timestamp is not causal")
    if not ((frame.eligible_count >= 100) == frame.breadth_above_ma20.notna()).all():
        raise Phase7Error("breadth completeness does not match frozen coverage gate")
    for block, definition in BLOCKS.items():
        rows = frame[frame.baseline_block == block]
        expected_dates = pd.date_range(definition["start"], definition["end"], freq="D")
        if rows.empty or rows.trade_date.min() != definition["start"] or rows.trade_date.max() != definition["end"]:
            raise Phase7Error(f"feature date boundaries mismatch for {block}")
        if len(rows) != {"EXTENDED_2018_2021": 973, "HOLDOUT_O0_2022_2023": 484, "DEVELOPMENT_2024_2025": 485}[block]:
            raise Phase7Error(f"feature session count mismatch for {block}")
        del expected_dates
    return frame


def arm_multipliers(rows: pd.DataFrame, arm: str) -> dict[date, float]:
    if arm == "C0_ALL_ONE_CONTROL":
        values = pd.Series(1.0, index=rows.index)
    else:
        rules = {
            "A40_HALF_PRIMARY": (0.40, 0.50),
            "N30_HALF_NEIGHBOR": (0.30, 0.50),
            "N50_HALF_NEIGHBOR": (0.50, 0.50),
            "Z40_ZERO_SEVERITY": (0.40, 0.00),
        }
        if arm not in rules:
            raise Phase7Error(f"unknown frozen arm: {arm}")
        threshold, weak_multiplier = rules[arm]
        values = pd.Series(1.0, index=rows.index)
        values.loc[rows.breadth_above_ma20.isna()] = 0.0
        values.loc[rows.breadth_above_ma20.notna() & (rows.breadth_above_ma20 < threshold)] = weak_multiplier
    return dict(zip(rows.trade_date, values.astype(float), strict=True))


def overlay_identity(block: str, arm: str, multipliers: dict[date, float]) -> dict[str, Any]:
    counts = pd.Series(list(multipliers.values())).value_counts().sort_index()
    return {
        "experiment_id": "EXP-P7-003",
        "spec_sha256": EXPECTED[SPEC],
        "block": block,
        "arm": arm,
        "feature": "breadth_above_ma20",
        "feature_sha256": EXPECTED[FEATURES],
        "decision_timestamp": "COMPLETED_SIGNAL_CLOSE_T",
        "application": "FIRST_CAUSALLY_VALID_LATER_OPEN_STICKY_MEMBER_TARGET",
        "multiplier_counts": {str(key): int(counts[key]) for key in counts.index},
    }


def run_one(
    *,
    block: str,
    arm: str,
    multipliers: dict[date, float],
    membership: Path,
    daily_root: Path,
) -> dict[str, Any]:
    definition = BLOCKS[block]
    output = OUTPUT_ROOT / block / arm
    output.mkdir(parents=True, exist_ok=False)
    args = argparse.Namespace(
        start=definition["start"],
        end=definition["end"],
        warmup_start=definition["warmup"],
        sample_size=10_000,
        full_survivor=True,
        initial_cash=INITIAL_CASH,
        pit_membership=membership,
        daily_root=daily_root,
        market=DEFAULT_MARKET,
        calendar=DEFAULT_CALENDAR,
        summary=output / "engine_summary.json",
        report=output / "engine_report.md",
        output_dir=output,
        ablation_arm="A0_BASELINE",
        entry_weight_multipliers=multipliers,
        entry_weight_overlay_identity=overlay_identity(block, arm, multipliers),
    )
    return run(args)


def projected_jsonl_sha(path: Path, removed_fields: set[str]) -> str:
    digest = hashlib.sha256()
    for row in read_jsonl(path):
        for field in removed_fields:
            row.pop(field, None)
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
        digest.update(encoded)
    return digest.hexdigest()


def max_drawdown(values: list[float], start: float = INITIAL_CASH) -> float:
    peak = start
    result = 0.0
    for value in [start, *values]:
        peak = max(peak, value)
        result = min(result, value / peak - 1.0)
    return result


def concentration_metrics(trades: list[dict[str, Any]], total_return: float) -> dict[str, Any]:
    ordered = sorted(
        trades,
        key=lambda row: (-float(row["realized_pnl"]), str(row["symbol"]), str(row["entry_signal_date"])),
    )
    positive = sum(max(0.0, float(row["realized_pnl"])) for row in ordered)
    result: dict[str, Any] = {"positive_round_trip_pnl": positive}
    for n in (5, 10, 20):
        top = ordered[:n]
        result[f"top{n}_positive_pnl_concentration"] = (
            sum(max(0.0, float(row["realized_pnl"])) for row in top) / positive
            if positive
            else None
        )
        result[f"return_ex_best{n}"] = total_return - sum(
            float(row["realized_pnl"]) for row in top
        ) / INITIAL_CASH
    return result


def trade_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row["symbol"]), str(row["entry_signal_date"])


def metric_bundle(summary: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    executions = read_jsonl(Path(summary["audit"]["execution_ledger"]))
    nav = read_jsonl(Path(summary["audit"]["daily_nav"]))
    trades = reconstruct_round_trips(executions)
    returns = [float(row["round_trip_return"]) for row in trades]
    costs = sum(float(row.get("cost") or 0.0) for row in executions if row.get("status") == "FILLED")
    total_return = float(summary["portfolio"]["total_return"])
    concentration = concentration_metrics(trades, total_return)
    metrics = {
        "total_return": total_return,
        "annualized_return": float(summary["portfolio"]["annualized_return"]),
        "max_drawdown": float(summary["portfolio"]["max_drawdown"]),
        "trade_count": len(trades),
        "win_rate": sum(value > 0 for value in returns) / len(returns) if returns else None,
        "mean_trade_return": statistics.fmean(returns) if returns else None,
        "median_trade_return": statistics.median(returns) if returns else None,
        "severe_loss_rate": sum(value <= -0.10 for value in returns) / len(returns) if returns else None,
        "winner20_count": sum(value >= 0.20 for value in returns),
        "winner50_count": sum(value >= 0.50 for value in returns),
        "average_invested_fraction": float(summary["portfolio"]["average_invested_ratio"]),
        "exposure_normalized_return": (
            total_return / float(summary["portfolio"]["average_invested_ratio"])
            if float(summary["portfolio"]["average_invested_ratio"]) > 0
            else None
        ),
        "turnover": float(summary["execution"]["turnover"]),
        "filled_side_cost": costs,
        "same_day_fill_count": sum(
            row.get("status") == "FILLED" and row.get("signal_date") == row.get("execution_date")
            for row in executions
        ),
        "stale_held_valuation_count": int(summary["audit"]["stale_held_valuation_count"]),
        "corporate_actions_applied": int(summary["audit"]["corporate_actions_applied"]),
        **concentration,
    }
    return metrics, trades, nav


def yearly_metrics(block: str, arm: str, trades: list[dict[str, Any]], nav: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frame = pd.DataFrame(nav)
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    records: list[dict[str, Any]] = []
    previous = INITIAL_CASH
    for year, rows in frame.groupby(frame.trade_date.dt.year, sort=True):
        year_trades = [row for row in trades if int(str(row["exit_execution_date"])[:4]) == int(year)]
        returns = [float(row["round_trip_return"]) for row in year_trades]
        end_nav = float(rows.iloc[-1].nav)
        records.append(
            {
                "block": block,
                "arm": arm,
                "year": int(year),
                "return": end_nav / previous - 1.0,
                "max_drawdown": max_drawdown(rows.nav.astype(float).tolist(), previous),
                "average_invested_fraction": float(rows.invested_ratio.mean()),
                "trade_count": len(year_trades),
                "win_rate": sum(value > 0 for value in returns) / len(returns) if returns else None,
                "mean_trade_return": statistics.fmean(returns) if returns else None,
                "median_trade_return": statistics.median(returns) if returns else None,
                "severe_loss_rate": sum(value <= -0.10 for value in returns) / len(returns) if returns else None,
                "winner20_count": sum(value >= 0.20 for value in returns),
                "winner50_count": sum(value >= 0.50 for value in returns),
            }
        )
        previous = end_nav
    return records


def compare_control(
    block: str,
    summary: dict[str, Any],
    metrics: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    definition = BLOCKS[block]
    output = Path(summary["audit"]["execution_ledger"]).parent
    event_projection_fields = {"desired_target_weights"}
    if block == "DEVELOPMENT_2024_2025":
        event_projection_fields.add("phase3_ablation")
    checks = {
        "execution_ledger_hash_exact": sha256_file(output / "execution_ledger.jsonl")
        == baseline["execution_ledger_sha256"],
        "event_ledger_projection_hash_exact": projected_jsonl_sha(
            output / "event_ledger.jsonl", event_projection_fields
        )
        == baseline["event_ledger_sha256"],
        "daily_nav_projection_hash_exact": projected_jsonl_sha(
            output / "daily_nav.jsonl", {"planned_target_weight_sum"}
        )
        == baseline["daily_nav_sha256"],
        "total_return_exact_1e12": abs(metrics["total_return"] - baseline["total_return"]) <= 1e-12,
        "max_drawdown_exact_1e12": abs(metrics["max_drawdown"] - baseline["max_drawdown"]) <= 1e-12,
        "completed_cycles_exact": metrics["trade_count"] == baseline["completed_round_trips"],
    }
    return {
        "baseline_output": str(definition["baseline_output"]),
        "event_projection_removed_fields": sorted(event_projection_fields),
        "daily_nav_projection_removed_fields": ["planned_target_weight_sum"],
        "checks": checks,
        "pass": all(checks.values()),
    }


def add_baseline_capture(
    candidate_metrics: dict[str, Any],
    candidate_trades: list[dict[str, Any]],
    baseline_trades: list[dict[str, Any]],
) -> None:
    candidate_by_key = {trade_key(row): row for row in candidate_trades}
    winners = [row for row in baseline_trades if float(row["round_trip_return"]) >= 0.20]
    ordered = sorted(
        baseline_trades,
        key=lambda row: (-float(row["realized_pnl"]), str(row["symbol"]), str(row["entry_signal_date"])),
    )
    top20 = ordered[:20]
    candidate_metrics["baseline_winner20_entry_retention"] = (
        sum(trade_key(row) in candidate_by_key for row in winners) / len(winners)
        if winners
        else 1.0
    )
    denominator = sum(max(0.0, float(row["realized_pnl"])) for row in top20)
    candidate_metrics["baseline_top20_positive_pnl_capture"] = (
        sum(
            max(0.0, float(candidate_by_key[trade_key(row)]["realized_pnl"]))
            for row in top20
            if trade_key(row) in candidate_by_key
        )
        / denominator
        if denominator
        else 1.0
    )


def promotion_decision(
    metrics: dict[str, dict[str, dict[str, Any]]],
    yearly: list[dict[str, Any]],
) -> dict[str, Any]:
    years = {(row["arm"], row["year"]): row for row in yearly}
    baseline_arm = "C0_ALL_ONE_CONTROL"
    primary = "A40_HALF_PRIMARY"
    bad_environment = (
        years[(primary, 2022)]["return"] > years[(baseline_arm, 2022)]["return"]
        and years[(primary, 2023)]["return"] >= years[(baseline_arm, 2023)]["return"] - 0.02
    )
    drawdown_count = sum(
        metrics[block][primary]["max_drawdown"] >= metrics[block][baseline_arm]["max_drawdown"]
        for block in BLOCKS
    )
    winner_retained = sum(
        metrics[block][primary]["baseline_winner20_entry_retention"]
        * metrics[block][baseline_arm]["winner20_count"]
        for block in BLOCKS
    ) / max(1, sum(metrics[block][baseline_arm]["winner20_count"] for block in BLOCKS))
    top20_capture_denominator = sum(
        metrics[block][baseline_arm]["positive_round_trip_pnl"]
        * metrics[block][baseline_arm]["top20_positive_pnl_concentration"]
        for block in BLOCKS
    )
    top20_capture_numerator = sum(
        metrics[block][primary]["baseline_top20_positive_pnl_capture"]
        * metrics[block][baseline_arm]["positive_round_trip_pnl"]
        * metrics[block][baseline_arm]["top20_positive_pnl_concentration"]
        for block in BLOCKS
    )
    top20_capture = top20_capture_numerator / top20_capture_denominator
    exbest_count = sum(
        metrics[block][primary]["return_ex_best20"]
        > metrics[block][baseline_arm]["return_ex_best20"]
        for block in BLOCKS
    )
    neighbors: dict[str, Any] = {}
    for arm in ("N30_HALF_NEIGHBOR", "N50_HALF_NEIGHBOR"):
        neighbor_drawdowns = sum(
            metrics[block][arm]["max_drawdown"] >= metrics[block][baseline_arm]["max_drawdown"]
            for block in BLOCKS
        )
        neighbors[arm] = {
            "improves_2022_return": years[(arm, 2022)]["return"] > years[(baseline_arm, 2022)]["return"],
            "nonworse_block_drawdown_count": neighbor_drawdowns,
            "passes": years[(arm, 2022)]["return"] > years[(baseline_arm, 2022)]["return"] and neighbor_drawdowns >= 2,
        }
    gates = {
        "bad_environment": bad_environment,
        "nonworse_block_drawdown_count": drawdown_count,
        "drawdown": drawdown_count >= 2,
        "winner20_entry_retention": winner_retained,
        "top20_positive_pnl_capture": top20_capture,
        "right_tail": winner_retained >= 0.90 and top20_capture >= 0.80,
        "exbest20_improvement_block_count": exbest_count,
        "distribution": exbest_count >= 2,
        "neighbors": neighbors,
        "neighbor_stability": all(item["passes"] for item in neighbors.values()),
    }
    passed = all(
        gates[key]
        for key in ("bad_environment", "drawdown", "right_tail", "distribution", "neighbor_stability")
    )
    return {
        "primary_arm": primary,
        "gates": gates,
        "decision": "PROMOTE_TO_PHASE8_ROBUSTNESS_ONLY" if passed else "REJECT_OR_RETAIN_EXPLANATORY_ONLY",
        "passes_all_phase7_promotion_gates": passed,
    }


def report_text(payload: dict[str, Any], block_rows: pd.DataFrame) -> str:
    promotion = payload["promotion"]
    lines = [
        "# Phase 7 — simple V1-R raw-breadth exposure candidate",
        "",
        f"EXP-P7-003 decision: `{promotion['decision']}`. This is outcome-consumed candidate evidence, not untouched OOS or production authorization.",
        "",
        "## Control identity",
        "",
    ]
    for block, audit in payload["control_gate"].items():
        lines.append(f"- {block}: `{'PASS' if audit['pass'] else 'FAIL'}` — all six frozen identity/economic checks passed: `{all(audit['checks'].values())}`.")
    lines += [
        "",
        "## Block metrics",
        "",
        "| Block | Arm | Return | Max DD | Avg invested | Trades | Winner20 | Ex-best20 | Top20 capture |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in block_rows.to_dict("records"):
        lines.append(
            f"| {row['block']} | {row['arm']} | {row['total_return']:.2%} | {row['max_drawdown']:.2%} | "
            f"{row['average_invested_fraction']:.2%} | {row['trade_count']} | {row['winner20_count']} | "
            f"{row['return_ex_best20']:.2%} | "
            f"{row.get('baseline_top20_positive_pnl_capture', float('nan')):.2%} |"
        )
    lines += [
        "",
        "## Promotion gates",
        "",
        f"- Bad-environment gate: `{promotion['gates']['bad_environment']}`",
        f"- Non-worse drawdown blocks: `{promotion['gates']['nonworse_block_drawdown_count']}/3`",
        f"- Baseline >=20% winner-entry retention: `{promotion['gates']['winner20_entry_retention']:.2%}`",
        f"- Baseline Top-20 positive-P&L capture: `{promotion['gates']['top20_positive_pnl_capture']:.2%}`",
        f"- Ex-best20 improvement blocks: `{promotion['gates']['exbest20_improvement_block_count']}/3`",
        f"- Neighbor stability: `{promotion['gates']['neighbor_stability']}`",
        "",
        "## Interpretation boundary",
        "",
        "The overlay changes only the target weight assigned to a newly selected V1 member. Missing breadth creates zero new risk and reserves the no-replacement slot. The three NAV blocks remain independent. A Phase 7 promotion would authorize robustness/falsification only, never deployment.",
        "",
        "## Exit adaptation",
        "",
        "Rejected. Phase 6 found no incremental conversion/capture evidence after fixed path/year/exit controls, so all V1 exits remain frozen.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    if OUTPUT_ROOT.exists() or OUTPUT_JSON.exists() or OUTPUT_YEARLY.exists() or OUTPUT_BLOCK.exists() or REPORT.exists():
        raise Phase7Error("Phase 7 output already exists; refusing duplicate formal candidate replays")
    _, _, baseline_manifest = validate_frozen_identities()
    authorizations = authorize_all_blocks()
    features = load_feature_states()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=False)
    all_metrics: dict[str, dict[str, dict[str, Any]]] = {block: {} for block in BLOCKS}
    all_trades: dict[str, dict[str, list[dict[str, Any]]]] = {block: {} for block in BLOCKS}
    all_yearly: list[dict[str, Any]] = []
    control_gate: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="chinext-v1r-p7-extended-input-") as temporary:
        extended_root = Path(temporary)
        original_validator = extended_replay.gate_c.validate_input_hashes
        extended_replay.gate_c.validate_input_hashes = (
            validate_append_only_registry_for_legacy_gate_c
        )
        try:
            prepared = extended_replay.materialize_transient_inputs(extended_root)
        finally:
            extended_replay.gate_c.validate_input_hashes = original_validator
        extended_replay.validate_prepared_manifest(
            prepared, load_extended_transient_contract()
        )
        runtime_inputs = {
            "EXTENDED_2018_2021": (extended_root / "daily_membership.parquet", extended_root),
            "HOLDOUT_O0_2022_2023": (
                BLOCKS["HOLDOUT_O0_2022_2023"]["membership"], DEFAULT_DAILY_ROOT
            ),
            "DEVELOPMENT_2024_2025": (
                BLOCKS["DEVELOPMENT_2024_2025"]["membership"], DEFAULT_DAILY_ROOT
            ),
        }

        for block in BLOCKS:
            rows = features[features.baseline_block == block].sort_values("trade_date")
            membership, daily_root = runtime_inputs[block]
            multipliers = arm_multipliers(rows, "C0_ALL_ONE_CONTROL")
            summary = run_one(
                block=block,
                arm="C0_ALL_ONE_CONTROL",
                multipliers=multipliers,
                membership=membership,
                daily_root=daily_root,
            )
            metrics, trades, nav = metric_bundle(summary)
            all_metrics[block]["C0_ALL_ONE_CONTROL"] = metrics
            all_trades[block]["C0_ALL_ONE_CONTROL"] = trades
            all_yearly.extend(yearly_metrics(block, "C0_ALL_ONE_CONTROL", trades, nav))
            control_gate[block] = compare_control(
                block, summary, metrics, baseline_manifest["blocks"][block]
            )
        if not all(audit["pass"] for audit in control_gate.values()):
            raise Phase7Error(f"all-one control gate failed; candidate arms forbidden: {control_gate}")

        for arm in ARMS[1:]:
            for block in BLOCKS:
                rows = features[features.baseline_block == block].sort_values("trade_date")
                membership, daily_root = runtime_inputs[block]
                multipliers = arm_multipliers(rows, arm)
                summary = run_one(
                    block=block,
                    arm=arm,
                    multipliers=multipliers,
                    membership=membership,
                    daily_root=daily_root,
                )
                metrics, trades, nav = metric_bundle(summary)
                add_baseline_capture(
                    metrics, trades, all_trades[block]["C0_ALL_ONE_CONTROL"]
                )
                all_metrics[block][arm] = metrics
                all_trades[block][arm] = trades
                all_yearly.extend(yearly_metrics(block, arm, trades, nav))

    block_records = [
        {"block": block, "arm": arm, **all_metrics[block][arm]}
        for block in BLOCKS
        for arm in ARMS
    ]
    block_frame = pd.DataFrame(block_records)
    yearly_frame = pd.DataFrame(all_yearly).sort_values(["arm", "year", "block"])
    promotion = promotion_decision(all_metrics, all_yearly)
    atomic_write(
        OUTPUT_BLOCK,
        block_frame.to_csv(index=False, lineterminator="\n", float_format="%.17g"),
    )
    atomic_write(
        OUTPUT_YEARLY,
        yearly_frame.to_csv(index=False, lineterminator="\n", float_format="%.17g"),
    )
    payload = {
        "experiment_id": "EXP-P7-003",
        "result": "PASS",
        "evidence_grade": "OUTCOME_CONSUMED_CANDIDATE_REPLAY_NO_UNTOUCHED_OOS",
        "spec_sha256": EXPECTED[SPEC],
        "warmup_spec_sha256": EXPECTED[WARMUP_SPEC],
        "base_spec_sha256": EXPECTED[BASE_SPEC],
        "authorization": authorizations,
        "formal_replay_execution_count": len(BLOCKS) * len(ARMS),
        "formal_run_order": [
            *[f"{block}/C0_ALL_ONE_CONTROL" for block in BLOCKS],
            *[f"{block}/{arm}" for arm in ARMS[1:] for block in BLOCKS],
        ],
        "control_gate": control_gate,
        "promotion": promotion,
        "output_hashes": {
            "v1r_candidate_yearly_metrics_csv": sha256_file(OUTPUT_YEARLY),
            "v1r_candidate_trade_metrics_csv": sha256_file(OUTPUT_BLOCK),
        },
        "falsification": {
            "thresholds_optimized": 0,
            "multipliers_optimized": 0,
            "neighbor_selected_as_primary": False,
            "entry_signal_changes": 0,
            "rank_changes": 0,
            "exit_changes": 0,
            "naive_nav_chaining": False,
            "strict_pit_a_claim": False,
            "untouched_oos_claim": False,
            "false_breakout_candidate_metric": "UNAVAILABLE_NOT_BOUND_IN_EXP_P7_003",
        },
    }
    atomic_write(OUTPUT_JSON, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    atomic_write(REPORT, report_text(payload, block_frame))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
