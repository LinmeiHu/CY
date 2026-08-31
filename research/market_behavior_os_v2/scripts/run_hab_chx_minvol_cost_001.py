#!/usr/bin/env python3
"""Run the one bounded matched-cost stress for the frozen minute-vol overlay."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_hab_chx_decision_batch_001 as decision  # noqa: E402
import run_hab_chx_downrev_strat_001 as shared  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/HAB-CHX-MINVOL-COST-001_spec.json"
RESULT_PATH = PROGRAM / "artifacts/HAB-CHX-MINVOL-COST-001_result.json"
REPORT_PATH = PROGRAM / "reports/HAB-CHX-MINVOL-COST-001_cost_stress.md"
OUTPUT_ROOT = PROGRAM / "artifacts/HAB-CHX-MINVOL-COST-001"
EXPECTED_SPEC_SHA256 = "250bad9d15570490ca54632fa86781d94c164a9a1cd7ca6aefe36a91f51c321d"

BLOCKS = ("development_2018_2021", "consumed_2022_2023")
ARMS = ("SAME_COST_BASELINE", "MINVOL_HIGH_HALF_GROSS")


class CostStressError(RuntimeError):
    """Fail-closed minute-volatility cost-stress error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise CostStressError("cost-stress spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_HIGHER_COST_REPLAYS":
        raise CostStressError("cost-stress honesty status changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise CostStressError(f"bound input identity mismatch: {name}")
    if spec["cost_stress"]["stressed_cost_bps_per_side"] != [20.0, 30.0]:
        raise CostStressError("bounded cost levels changed")
    overlay = spec["frozen_overlay"]
    if (
        overlay["state"] != decision.STATE
        or overlay["rule"]
        != "target 5% per selected holding when state >= 0.80; otherwise 10%"
        or overlay["threshold_search"] is not False
        or overlay["exposure_search"] is not False
    ):
        raise CostStressError("frozen risk overlay changed")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "unmatched", "same-bar"):
        if phrase not in prohibited:
            raise CostStressError(f"missing prohibition: {phrase}")
    return spec


@contextmanager
def _cost_config(cost_bps: float) -> Iterator[None]:
    original = shared.engine_module.ChinNextV1Config

    def stressed_config(*args: Any, **kwargs: Any) -> Any:
        return replace(original(*args, **kwargs), transaction_cost_bps=cost_bps)

    shared.engine_module.ChinNextV1Config = stressed_config
    try:
        yield
    finally:
        shared.engine_module.ChinNextV1Config = original


@contextmanager
def _no_overlay(_state: Any, _audit: dict[str, Any]) -> Iterator[None]:
    yield


def _baseline_audit() -> dict[str, Any]:
    return {}


def _run_pair(
    parent_spec: dict[str, Any], state: dict[Any, float], cost_bps: float
) -> dict[str, Any]:
    cost_root = OUTPUT_ROOT / f"{int(cost_bps)}BPS"
    results = {}
    for arm in ARMS:
        output = cost_root / arm
        context = _no_overlay if arm == "SAME_COST_BASELINE" else decision._exposure_budget
        audit_factory = (
            _baseline_audit
            if arm == "SAME_COST_BASELINE"
            else decision._new_exposure_audit
        )
        context_state = None if arm == "SAME_COST_BASELINE" else state
        original_audit = shared._new_audit
        shared._new_audit = audit_factory
        try:
            with _cost_config(cost_bps), decision._configured_shared_runner(output, context):
                dev_engine, dev_audit = shared._run_development(context_state)
                later_engine, later_audit = shared._run_consumed_block(
                    parent_spec, context_state
                )
        finally:
            shared._new_audit = original_audit
        results[arm] = {
            "development_2018_2021": {
                "metrics": shared._candidate_metrics(dev_engine),
                "audit": _audit(arm, dev_audit),
            },
            "consumed_2022_2023": {
                "metrics": shared._candidate_metrics(later_engine),
                "audit": _audit(arm, later_audit),
            },
        }
    return results


def _audit(arm: str, audit: dict[str, Any]) -> dict[str, Any]:
    common = {"input_manifest_sha256": audit.get("input_manifest_sha256")}
    if arm == "MINVOL_HIGH_HALF_GROSS":
        common.update(
            {
                "active_session_count": len(audit["active_sessions"]),
                "high_state_session_count": len(audit["high_state_sessions"]),
                "exposure_transition_session_count": len(
                    audit["exposure_transition_sessions"]
                ),
                "target_order_count": int(audit["target_order_count"]),
            }
        )
    return common


def _comparison(pair: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for block in BLOCKS:
        baseline = pair["SAME_COST_BASELINE"][block]["metrics"]
        overlay = pair["MINVOL_HIGH_HALF_GROSS"][block]["metrics"]
        result[block] = {
            "baseline": baseline,
            "overlay": overlay,
            "overlay_minus_baseline": decision._delta(overlay, baseline),
            "checks": {
                "total_return_improves": overlay["total_return"] > baseline["total_return"],
                "sharpe_improves": overlay["sharpe_rf0"] > baseline["sharpe_rf0"],
                "max_drawdown_no_worse": overlay["max_drawdown"]
                >= baseline["max_drawdown"],
                "material_total_return_benefit": overlay["total_return"]
                - baseline["total_return"]
                >= 0.005,
                "zero_same_day_fills": overlay["same_day_fills"] == 0
                and baseline["same_day_fills"] == 0,
            },
        }
    return result


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# HAB-CHX-MINVOL-COST-001 — matched-cost risk-overlay stress",
        "",
        "At each cost the frozen half-gross overlay is compared with a baseline "
        "replayed at the identical per-side cost.",
        "",
        "| Cost/side | Block | Baseline return | Overlay return | Benefit | "
        "Baseline Sharpe | Overlay Sharpe |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for cost, stress in result["stress_results"].items():
        for block, row in stress["comparisons"].items():
            baseline = row["baseline"]
            overlay = row["overlay"]
            delta = row["overlay_minus_baseline"]
            lines.append(
                f"| {cost} bps | {block} | {baseline['total_return']:.3%} | "
                f"{overlay['total_return']:.3%} | {delta['total_return']:.3%} | "
                f"{baseline['sharpe_rf0']:.3f} | {overlay['sharpe_rf0']:.3f} |"
            )
    lines.extend(
        [
            "",
            f"Decision: **{result['decision']}**.",
            "",
            "The state threshold, exposure levels, stock selection, entries, exits, and "
            "execution contracts were unchanged. No post-2023 or CY-011 row was read.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    spec = _load_spec()
    if OUTPUT_ROOT.exists() or RESULT_PATH.exists() or REPORT_PATH.exists():
        raise CostStressError("cost-stress output already exists")
    parent_spec = decision._load_spec()
    state = decision._load_minute_state(parent_spec)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=False)
    try:
        stress_results = {}
        all_checks = []
        for cost_bps in spec["cost_stress"]["stressed_cost_bps_per_side"]:
            pair = _run_pair(parent_spec, state, float(cost_bps))
            comparisons = _comparison(pair)
            stress_results[str(int(cost_bps))] = {
                "cost_bps_per_side": cost_bps,
                "comparisons": comparisons,
                "audits": {
                    arm: {block: pair[arm][block]["audit"] for block in BLOCKS}
                    for arm in ARMS
                },
            }
            all_checks.extend(
                check
                for row in comparisons.values()
                for check in row["checks"].values()
            )
        passed = all(all_checks)
        result = {
            "experiment_id": spec["experiment_id"],
            "research_level": spec["research_level"],
            "status": "COMPLETE_MATCHED_COST_STRESS",
            "honesty_boundary": spec["honesty_boundary"],
            "stress_results": stress_results,
            "decision": (
                "PROMISING_RISK_OVERLAY"
                if passed
                else "DOWNGRADED_COST_SENSITIVE_RISK_OVERLAY"
            ),
            "all_predeclared_checks_pass": passed,
            "claim_boundary": {
                "untouched_validation": False,
                "post_2023_rows_read": False,
                "cy011_read": False,
                "signal_or_exposure_changed": False,
                "selection_entry_or_exit_changed": False,
                "cost_level_search": False,
                "same_bar_fill_assumed": False,
                "existing_engine_changed_on_disk": False,
            },
            "hashes": {
                "spec_sha256": EXPECTED_SPEC_SHA256,
                "inputs": {
                    name: binding["sha256"] for name, binding in spec["inputs"].items()
                },
                "engine_outputs": {},
            },
        }
        for cost in stress_results:
            result["hashes"]["engine_outputs"][cost] = {}
            for arm in ARMS:
                result["hashes"]["engine_outputs"][cost][arm] = {}
                for block in BLOCKS:
                    directory = OUTPUT_ROOT / f"{cost}BPS" / arm / block
                    result["hashes"]["engine_outputs"][cost][arm][block] = {
                        name: sha256_file(directory / name)
                        for name in (
                            "engine_summary.json",
                            "event_ledger.jsonl",
                            "execution_ledger.jsonl",
                            "daily_nav.jsonl",
                        )
                    }
        _atomic_write(REPORT_PATH, _render(result))
        result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
        _atomic_write(
            RESULT_PATH,
            json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False) + "\n",
        )
        print(json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False))
    except Exception:
        if OUTPUT_ROOT.exists():
            shutil.rmtree(OUTPUT_ROOT)
        if REPORT_PATH.exists():
            REPORT_PATH.unlink()
        raise


if __name__ == "__main__":
    main()
