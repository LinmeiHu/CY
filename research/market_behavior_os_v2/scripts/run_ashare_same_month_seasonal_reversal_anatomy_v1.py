#!/usr/bin/env python3
"""Run the frozen post-hoc same-month seasonal-reversal anatomy."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = (
    PROGRAM
    / "experiments/ASHARE-SAME-MONTH-SEASONAL-REVERSAL-ANATOMY-V1_spec.json"
)
BUCKET_PATH = (
    PROGRAM
    / "artifacts/ASHARE-SAME-MONTH-SEASONAL-REVERSAL-ANATOMY-V1_bucket_table.csv"
)
RESULT_PATH = (
    PROGRAM / "artifacts/ASHARE-SAME-MONTH-SEASONAL-REVERSAL-ANATOMY-V1_result.json"
)
REPORT_PATH = (
    PROGRAM / "reports/ASHARE-SAME-MONTH-SEASONAL-REVERSAL-ANATOMY-V1_report.md"
)
HELPER_PATH = (
    PROGRAM / "scripts/run_ashare_relative_rank_overacceleration_anatomy_v1.py"
)
EXPECTED_SPEC_SHA256 = "affbdebce17806b81e1859188a5dff7ea02c7f310a1ec8cb8058aebf1144a01b"
FAMILY = "same_month_seasonality_1y"


class SeasonalReversalError(RuntimeError):
    """Fail-closed experiment error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise SeasonalReversalError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


HELPER = _load_module("ashare_rank_anatomy_for_seasonality", HELPER_PATH)


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise SeasonalReversalError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_LOW_SEASONAL_SCORE_OUTCOME_AGGREGATION":
        raise SeasonalReversalError("spec is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise SeasonalReversalError(f"bound input changed: {name}")
    return spec


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _verify_prior_high_leg(frame: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    prior = pd.read_csv(_resolve(spec["inputs"]["cycle009_panel"]["path"]))
    expected = prior.loc[
        prior.family.eq(FAMILY), ["trade_date", "symbol", "signal_score"]
    ].copy()
    source = frame.loc[np.isfinite(frame[FAMILY])].copy()
    actual = (
        source.sort_values(
            ["trade_date", FAMILY, "symbol"], ascending=[True, False, True]
        )
        .groupby("trade_date", sort=True)
        .head(20)[["trade_date", "symbol", FAMILY]]
        .rename(columns={FAMILY: "signal_score"})
    )
    expected["trade_date"] = pd.to_datetime(expected.trade_date).dt.date
    actual["trade_date"] = pd.to_datetime(actual.trade_date).dt.date
    merged = expected.merge(
        actual,
        on=["trade_date", "symbol"],
        how="outer",
        suffixes=("_prior", "_recomputed"),
        indicator=True,
    )
    exact_rows = bool((merged._merge == "both").all()) and len(actual) == len(expected)
    exact_scores = exact_rows and bool(
        np.allclose(
            merged.signal_score_prior.to_numpy(float),
            merged.signal_score_recomputed.to_numpy(float),
            rtol=0,
            atol=1e-12,
        )
    )
    if not (exact_rows and exact_scores):
        raise SeasonalReversalError("failed to reproduce Cycle-009 high seasonality leg")
    return {
        "rows": len(expected),
        "dates": int(expected.trade_date.nunique()),
        "symbols": int(expected.symbol.nunique()),
        "exact_rows": exact_rows,
        "exact_scores": exact_scores,
    }


def _render(result: dict[str, Any]) -> str:
    generation = result["generation"]["periods"]["generation_2018_2020"]
    validation = result["validation"]
    lines = [
        "# Same-month seasonal-reversal anatomy",
        "",
        f"Status: `{result['status']}`.",
        "",
        (
            "This low-score direction is post-hoc: it was generated only after the "
            "canonical high-score continuation leg was adverse. All results are "
            "consumed 2018-2023 development evidence, never independent confirmation."
        ),
        "",
        "## Generation",
        "",
        (
            f"Q1 mean {generation['q1_mean_net_return']:.3%}; Q1 versus all eligible "
            f"{generation['q1_excess_vs_all_eligible']:.3%}; Q1-Q5 "
            f"{generation['q1_minus_q5']:.3%}; favorable adjacent steps "
            f"{generation['favorable_adjacent_steps']}/4; gate "
            f"`{result['generation']['passes']}`."
        ),
        "",
        "Q1→Q5: "
        + ", ".join(
            f"{key} {value:.3%}"
            for key, value in generation["bucket_mean_net_returns"].items()
        )
        + f"; Spearman {generation['bucket_spearman_rho']:.3f}.",
        "",
        "## Fixed validation",
        "",
    ]
    if validation is None:
        lines.append("Unopened because the frozen generation gate failed.")
    else:
        period = validation["period"]
        lines += [
            (
                f"Q1 mean {period['q1_mean_net_return']:.3%}; Q1 versus all eligible "
                f"{period['q1_excess_vs_all_eligible']:.3%}; Q1-Q5 "
                f"{period['q1_minus_q5']:.3%}; favorable adjacent steps "
                f"{period['favorable_adjacent_steps']}/4; gate "
                f"`{validation['passes']}`."
            ),
            "",
            "Q1→Q5: "
            + ", ".join(
                f"{key} {value:.3%}"
                for key, value in period["bucket_mean_net_returns"].items()
            )
            + f"; Spearman {period['bucket_spearman_rho']:.3f}.",
        ]
    lines += ["", "## Executable translation", ""]
    replay = result["replay"]
    if replay is None:
        lines.append("No replay was authorized.")
    elif replay.get("status") == "REPLAY_BLOCKED":
        lines.append(f"Replay failed closed: `{replay['error']}`.")
    else:
        lines.append(
            f"The frozen lowest-score Top-10 replay returned "
            f"{replay['total_return']:.2%} total / "
            f"{replay['annualized_return']:.2%} annualized, maximum drawdown "
            f"{replay['maximum_drawdown']:.2%}, Sharpe "
            f"{replay['daily_sharpe']:.3f}. User target met: "
            f"`{result['replay_audit']['meets_user_return_and_drawdown_target']}`."
        )
    lines += [
        "",
        f"Final interpretation: `{result['interpretation']}`.",
        "",
        (
            "Post-2023 outcomes and CY-011 were not read. No year/month partition, "
            "threshold, Top-N, horizon, or champion rescue was tested."
        ),
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    daily_paths, _ = HELPER.CYCLE009.CYCLE5.CYCLE4._input_paths()
    with tempfile.TemporaryDirectory(prefix="ashare-seasonal-reversal-") as temporary:
        frame, calendar, input_audit = HELPER._build_exact_frame(
            daily_paths, Path(temporary)
        )
    reproduction = _verify_prior_high_leg(frame, spec)
    selection = HELPER._selection_panel(frame, (FAMILY,))
    days = pd.to_datetime(selection.trade_date).dt.date
    generation_selection = selection.loc[days <= HELPER.GEN_END].reset_index(drop=True)
    generation_panel, generation_path_rows = HELPER.CYCLE009.CYCLE5._attach_outcomes(
        daily_paths, generation_selection, calendar
    )
    generation = HELPER._generation_decision(generation_panel, FAMILY, spec)
    validation = None
    validation_panel = pd.DataFrame()
    validation_path_rows = 0
    if generation["passes"]:
        validation_selection = selection.loc[days >= HELPER.VALIDATION_START].reset_index(
            drop=True
        )
        validation_panel, validation_path_rows = HELPER.CYCLE009.CYCLE5._attach_outcomes(
            daily_paths, validation_selection, calendar
        )
        validation = HELPER._validation_decision(validation_panel, FAMILY, spec)
    tables = [HELPER._bucket_table(generation_panel, "generation_2018_2020")]
    if not validation_panel.empty:
        tables.append(
            HELPER._bucket_table(validation_panel, "fixed_validation_2021_2023")
        )
    bucket_table = pd.concat(tables, ignore_index=True)
    authorized = [FAMILY] if validation is not None and validation["passes"] else []
    full_panel = pd.concat(
        [generation_panel, validation_panel], ignore_index=True, sort=False
    )
    replay, replay_audit = HELPER._replay(
        full_panel,
        authorized,
        {FAMILY: generation},
        {} if validation is None else {FAMILY: validation},
        spec,
        daily_paths,
        calendar,
    )
    interpretation = HELPER._interpret(generation, validation)
    status = (
        "TARGET_ACHIEVED"
        if replay_audit.get("meets_user_return_and_drawdown_target")
        else "COMPLETE_NO_TARGET_STRATEGY"
    )
    BUCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    bucket_table.sort_values(["period", "rank_bucket"]).to_csv(BUCKET_PATH, index=False)
    result = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "claim_boundary": spec["claim_boundary"],
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
        "maximum_outcome_date": date(2023, 12, 29),
        "input_audit": input_audit,
        "eligible_rows": len(frame),
        "eligible_symbols": int(frame.symbol.nunique()),
        "decision_dates": int(frame.trade_date.nunique()),
        "prior_high_leg_reproduction": reproduction,
        "generation_path_rows": generation_path_rows,
        "validation_opened": generation["passes"],
        "validation_path_rows": validation_path_rows,
        "generation": generation,
        "validation": validation,
        "interpretation": interpretation,
        "replay": replay,
        "replay_audit": replay_audit,
        "success_target": spec["success_target"],
    }
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "bucket_table_sha256": sha256_file(BUCKET_PATH),
    }
    _atomic_write(
        RESULT_PATH, json.dumps(HELPER._clean(result), indent=2, sort_keys=True) + "\n"
    )
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(HELPER._clean(run()), indent=2, sort_keys=True))
