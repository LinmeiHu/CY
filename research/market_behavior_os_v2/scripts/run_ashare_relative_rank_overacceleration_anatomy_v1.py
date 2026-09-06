#!/usr/bin/env python3
"""Run the frozen post-hoc relative-rank-overacceleration anatomy."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
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
    / "experiments/ASHARE-RELATIVE-RANK-OVERACCELERATION-ANATOMY-V1_spec.json"
)
BUCKET_PATH = (
    PROGRAM
    / "artifacts/ASHARE-RELATIVE-RANK-OVERACCELERATION-ANATOMY-V1_bucket_table.csv"
)
RESULT_PATH = (
    PROGRAM / "artifacts/ASHARE-RELATIVE-RANK-OVERACCELERATION-ANATOMY-V1_result.json"
)
REPORT_PATH = (
    PROGRAM / "reports/ASHARE-RELATIVE-RANK-OVERACCELERATION-ANATOMY-V1_report.md"
)
CYCLE009_PATH = PROGRAM / "scripts/run_ashare_defensive_alpha_cycle_009.py"
EXPECTED_SPEC_SHA256 = "d03cbf90050d523ab110a15aba7ad1af220a3e3c9c60dedab9618482c20a0fee"
START = date(2018, 1, 2)
GEN_END = date(2020, 12, 31)
VALIDATION_START = date(2021, 1, 1)
END = date(2023, 12, 29)
HORIZON = 20
FAMILIES = (
    "market_relative_rank_acceleration_20",
    "industry_follower_rank_acceleration_20",
)


class RelativeRankAnatomyError(RuntimeError):
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
        raise RelativeRankAnatomyError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CYCLE009 = _load_module("ashare_cycle_009_for_rank_anatomy", CYCLE009_PATH)


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise RelativeRankAnatomyError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_LOW_LEG_FORWARD_OUTCOME_AGGREGATION":
        raise RelativeRankAnatomyError("spec is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise RelativeRankAnatomyError(f"bound input changed: {name}")
    return spec


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
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    return value


def _build_exact_frame(
    daily_paths: list[Path], temp_path: Path
) -> tuple[pd.DataFrame, list[date], dict[str, Any]]:
    base, calendar, _, _, audit = CYCLE009.CYCLE8._build_frame(daily_paths, temp_path)
    features = CYCLE009._feature_frame(daily_paths, temp_path)
    frame = base.merge(
        features,
        on=["trade_date", "symbol", "cal_idx"],
        how="left",
        validate="one_to_one",
    )
    frame, _ = CYCLE009._ranks_and_scores(frame)
    if frame.empty or frame.duplicated(["trade_date", "symbol"]).any():
        raise RelativeRankAnatomyError("invalid exact Cycle-009 frame")
    days = pd.to_datetime(frame.trade_date).dt.date
    if days.min() < START or days.max() > END:
        raise RelativeRankAnatomyError("research frame escaped frozen date boundary")
    return frame, calendar, audit


def _verify_prior_high_leg(frame: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    prior = pd.read_csv(_resolve(spec["inputs"]["cycle009_panel"]["path"]))
    output: dict[str, Any] = {}
    for family in FAMILIES:
        expected = prior.loc[
            prior.family.eq(family), ["trade_date", "symbol", "signal_score"]
        ].copy()
        source = frame.loc[np.isfinite(frame[family])].copy()
        actual = (
            source.sort_values(
                ["trade_date", family, "symbol"], ascending=[True, False, True]
            )
            .groupby("trade_date", sort=True)
            .head(20)[["trade_date", "symbol", family]]
            .rename(columns={family: "signal_score"})
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
            raise RelativeRankAnatomyError(f"failed to reproduce Cycle-009 high leg: {family}")
        output[family] = {
            "rows": len(expected),
            "dates": int(expected.trade_date.nunique()),
            "symbols": int(expected.symbol.nunique()),
            "exact_rows": exact_rows,
            "exact_scores": exact_scores,
        }
    return output


def _rank_bucket(values: pd.Series) -> pd.Series:
    ordered = values.rank(method="first")
    return pd.qcut(ordered, 5, labels=[1, 2, 3, 4, 5]).astype(int)


def _selection_panel(frame: pd.DataFrame, families: tuple[str, ...]) -> pd.DataFrame:
    outputs: list[pd.DataFrame] = []
    for family in families:
        work = frame.loc[np.isfinite(frame[family])].copy()
        work["family"] = family
        work["rank_bucket"] = work.groupby("trade_date")[family].transform(_rank_bucket)
        work["signal_score"] = work[family]
        work["candidate_count"] = work.groupby("trade_date").symbol.transform("size")
        work = work.sort_values(
            ["trade_date", "signal_score", "symbol"], ascending=[True, True, True]
        )
        work["signal_rank"] = work.groupby("trade_date").cumcount() + 1
        work["track"] = "posthoc_low_leg_anatomy"
        work["natural_horizon"] = HORIZON
        work["rebalance_sessions"] = HORIZON
        work["decision_at"] = pd.to_datetime(work.trade_date) + pd.Timedelta(
            hours=15, minutes=30
        )
        outputs.append(work)
    columns = [
        "family",
        "track",
        "rank_bucket",
        "trade_date",
        "cal_idx",
        "decision_at",
        "available_at",
        "symbol",
        "industry",
        "signal_score",
        "signal_rank",
        "candidate_count",
        "avg_amount20",
        "natural_horizon",
        "rebalance_sessions",
    ]
    panel = pd.concat(outputs, ignore_index=True)[columns]
    if panel.duplicated(["family", "trade_date", "symbol"]).any():
        raise RelativeRankAnatomyError("duplicate anatomy candidate")
    return panel.reset_index(drop=True)


def _complete(panel: pd.DataFrame) -> pd.DataFrame:
    return panel.loc[panel.status_h20.eq("COMPLETE")].copy()


def _bucket_table(panel: pd.DataFrame, period: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (family, bucket), raw in panel.groupby(["family", "rank_bucket"], sort=True):
        valid = _complete(raw)
        date_returns = valid.groupby("trade_date").net_return_h20.mean()
        date_severe = valid.groupby("trade_date").net_return_h20.apply(
            lambda values: float((values <= -0.10).mean())
        )
        returns = valid.net_return_h20.astype(float)
        rows.append(
            {
                "period": period,
                "family": family,
                "rank_bucket": int(bucket),
                "N": len(valid),
                "decision_dates": int(valid.trade_date.nunique()),
                "mean_net_return": float(date_returns.mean()),
                "median_net_return": float(returns.median()),
                "positive_fraction": float((returns > 0).mean()),
                "severe_loss_fraction": float(date_severe.mean()),
                "entry_execution_coverage": float(raw.entry_status.eq("EXECUTABLE").mean()),
                "median_candidate_count": float(raw.candidate_count.median()),
                "median_avg_amount20_cny": float(raw.avg_amount20.median()),
                "p10_entry_amount_cny": float(valid.entry_amount_h20.quantile(0.10)),
            }
        )
    return pd.DataFrame(rows)


def _period_dates(panel: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    days = pd.to_datetime(panel.trade_date).dt.date
    return panel.loc[(days >= start) & (days <= end)].copy()


def _family_anatomy(panel: pd.DataFrame, family: str) -> dict[str, Any]:
    raw = panel.loc[panel.family.eq(family)].copy()
    valid = _complete(raw)
    if valid.empty:
        raise RelativeRankAnatomyError(f"no complete outcomes: {family}")
    date_all = valid.groupby("trade_date").net_return_h20.mean()
    date_all_severe = valid.groupby("trade_date").net_return_h20.apply(
        lambda values: float((values <= -0.10).mean())
    )
    bucket_date = (
        valid.groupby(["trade_date", "rank_bucket"])
        .net_return_h20.mean()
        .unstack("rank_bucket")
    )
    bucket_means = bucket_date.mean()
    q1 = valid.loc[valid.rank_bucket.eq(1)]
    q5 = valid.loc[valid.rank_bucket.eq(5)]
    q1_date = q1.groupby("trade_date").net_return_h20.mean()
    q5_date = q5.groupby("trade_date").net_return_h20.mean()
    common = bucket_date.dropna(subset=[1, 5])
    ordering_rho = pd.Series(range(1, 6), dtype=float).corr(
        pd.Series([float(bucket_means.loc[index]) for index in range(1, 6)]),
        method="spearman",
    )
    q1_severe = q1.groupby("trade_date").net_return_h20.apply(
        lambda values: float((values <= -0.10).mean())
    )
    return {
        "N": len(valid),
        "decision_dates": int(valid.trade_date.nunique()),
        "symbols": int(valid.symbol.nunique()),
        "bucket_mean_net_returns": {
            f"Q{index}": float(bucket_means.loc[index]) for index in range(1, 6)
        },
        "q1_mean_net_return": float(q1_date.mean()),
        "q1_median_net_return": float(q1.net_return_h20.median()),
        "q1_positive_fraction": float((q1.net_return_h20 > 0).mean()),
        "q1_severe_loss_fraction": float(q1_severe.mean()),
        "all_eligible_mean_net_return": float(date_all.mean()),
        "all_eligible_severe_loss_fraction": float(date_all_severe.mean()),
        "q1_excess_vs_all_eligible": float((q1_date - date_all).dropna().mean()),
        "q5_excess_vs_all_eligible": float((q5_date - date_all).dropna().mean()),
        "q1_minus_q5": float((common[1] - common[5]).mean()),
        "favorable_adjacent_steps": sum(
            float(bucket_means.loc[index]) > float(bucket_means.loc[index + 1])
            for index in range(1, 5)
        ),
        "bucket_spearman_rho": float(ordering_rho),
        "entry_execution_coverage_q1": float(
            raw.loc[raw.rank_bucket.eq(1), "entry_status"].eq("EXECUTABLE").mean()
        ),
        "median_candidates": float(raw.candidate_count.median()),
        "p10_q1_entry_amount_cny": float(q1.entry_amount_h20.quantile(0.10)),
    }


def _generation_decision(
    panel: pd.DataFrame, family: str, spec: dict[str, Any]
) -> dict[str, Any]:
    periods = {
        "generation_2018_2020": (START, GEN_END),
        "generation_2018_2019": (START, date(2019, 12, 31)),
        "generation_2020": (date(2020, 1, 1), GEN_END),
    }
    anatomy = {
        name: _family_anatomy(_period_dates(panel, first, last), family)
        for name, (first, last) in periods.items()
    }
    full = anatomy["generation_2018_2020"]
    gates = spec["generation_gate_all_required"]
    checks = {
        "decision_dates": full["decision_dates"] >= gates["minimum_decision_dates"],
        "execution": full["entry_execution_coverage_q1"]
        >= gates["minimum_entry_execution_coverage"],
        "q1_mean": full["q1_mean_net_return"] >= gates["minimum_q1_mean_net_return"],
        "q1_excess": full["q1_excess_vs_all_eligible"]
        >= gates["minimum_q1_excess_vs_all_eligible"],
        "q1_minus_q5": full["q1_minus_q5"] >= gates["minimum_q1_minus_q5"],
        "adjacent_steps": full["favorable_adjacent_steps"]
        >= gates["minimum_favorable_adjacent_steps"],
        "2018_2019_spread": anatomy["generation_2018_2019"]["q1_minus_q5"] > 0,
        "2020_spread": anatomy["generation_2020"]["q1_minus_q5"] > 0,
        "severe_loss": (
            full["q1_severe_loss_fraction"]
            - full["all_eligible_severe_loss_fraction"]
        )
        <= gates["maximum_q1_severe_loss_disadvantage_vs_all_eligible"],
    }
    return {"periods": anatomy, "gates": checks, "passes": all(checks.values())}


def _validation_decision(
    panel: pd.DataFrame, family: str, spec: dict[str, Any]
) -> dict[str, Any]:
    validation = _family_anatomy(
        _period_dates(panel, VALIDATION_START, END), family
    )
    yearly = {
        str(year): _family_anatomy(
            _period_dates(panel, date(year, 1, 1), date(year, 12, 31)), family
        )
        for year in range(2021, 2024)
    }
    gates = spec["validation_gate_all_required"]
    checks = {
        "q1_mean": validation["q1_mean_net_return"]
        >= gates["minimum_q1_mean_net_return"],
        "q1_excess": validation["q1_excess_vs_all_eligible"]
        >= gates["minimum_q1_excess_vs_all_eligible"],
        "q1_minus_q5": validation["q1_minus_q5"] >= gates["minimum_q1_minus_q5"],
        "adjacent_steps": validation["favorable_adjacent_steps"]
        >= gates["minimum_favorable_adjacent_steps"],
        "calendar_year_spreads": sum(row["q1_minus_q5"] > 0 for row in yearly.values())
        >= gates["minimum_positive_calendar_year_q1_minus_q5"],
        "severe_loss": (
            validation["q1_severe_loss_fraction"]
            - validation["all_eligible_severe_loss_fraction"]
        )
        <= gates["maximum_q1_severe_loss_disadvantage_vs_all_eligible"],
    }
    return {
        "period": validation,
        "calendar_years": yearly,
        "gates": checks,
        "passes": all(checks.values()),
    }


def _interpret(
    generation: dict[str, Any], validation: dict[str, Any] | None
) -> str:
    gen = generation["periods"]["generation_2018_2020"]
    if validation is None:
        if gen["q1_mean_net_return"] <= 0 and gen["q5_excess_vs_all_eligible"] < 0:
            return "HIGH_ACCELERATION_AVOIDANCE_ONLY_GENERATION"
        return "NO_LOW_ACCELERATION_ALPHA_GENERATION"
    val = validation["period"]
    if generation["passes"] and validation["passes"]:
        return "POST_HOC_LOW_ACCELERATION_LONG_CANDIDATE"
    if gen["q1_excess_vs_all_eligible"] * val["q1_excess_vs_all_eligible"] < 0:
        return "CHRONOLOGICALLY_UNSTABLE"
    if min(gen["q1_mean_net_return"], val["q1_mean_net_return"]) <= 0 and max(
        abs(gen["q5_excess_vs_all_eligible"]), abs(val["q5_excess_vs_all_eligible"])
    ) > max(abs(gen["q1_excess_vs_all_eligible"]), abs(val["q1_excess_vs_all_eligible"])):
        return "HIGH_ACCELERATION_AVOIDANCE_ONLY"
    return "LOW_ACCELERATION_INFORMATION_NOT_STRATEGY_GRADE"


def _control_rows(spec: dict[str, Any]) -> pd.DataFrame:
    panel = pd.read_csv(_resolve(spec["inputs"]["cycle009_panel"]["path"]))
    control = panel.loc[panel.family.eq("date_control")].copy()
    control["trade_date"] = pd.to_datetime(control.trade_date).dt.date
    return control


def _replay(
    complete_panel: pd.DataFrame,
    authorized: list[str],
    generation: dict[str, Any],
    validation: dict[str, Any],
    spec: dict[str, Any],
    daily_paths: list[Path],
    calendar: list[date],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not authorized:
        return None, {"authorized": False, "reason": "NO_FAMILY_PASSED_BOTH_GATES"}
    ranked = sorted(
        authorized,
        key=lambda family: (
            min(
                generation[family]["periods"]["generation_2018_2020"][
                    "q1_excess_vs_all_eligible"
                ],
                validation[family]["period"]["q1_excess_vs_all_eligible"],
            ),
            family,
        ),
        reverse=True,
    )
    selected = ranked[0]
    candidate = complete_panel.loc[complete_panel.family.eq(selected)].copy()
    candidate = candidate.sort_values(["trade_date", "signal_rank", "symbol"])
    candidate = candidate.groupby("trade_date", sort=True).head(20)
    control = _control_rows(spec)
    replay_panel = pd.concat([candidate, control], ignore_index=True, sort=False)
    replays, equity, exits = CYCLE009.CYCLE8._replay_families(
        replay_panel, [selected], daily_paths, calendar
    )
    replay = replays[0]
    target = spec["success_target"]
    meets_target = (
        replay.get("status") != "REPLAY_BLOCKED"
        and float(replay["annualized_return"]) >= target["minimum_annualized_return"]
        and float(replay["maximum_drawdown"])
        > target["maximum_drawdown_must_be_greater_than"]
    )
    audit = {
        "authorized": True,
        "selected_family": selected,
        "eligible_families": ranked,
        "selection_rule": spec["executable_translation"]["selection_if_both_pass"],
        "meets_user_return_and_drawdown_target": meets_target,
        "equity_rows": len(equity),
        "risk_exit_rows": len(exits),
    }
    return replay, audit


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# Relative-rank overacceleration anatomy",
        "",
        f"Status: `{result['status']}`.",
        "",
        (
            "This is post-hoc anatomy: the low-side direction was generated by "
            "Cycle-009's surprising adverse high-acceleration leg. It is consumed "
            "2018-2023 development evidence, not independent confirmation."
        ),
        "",
        "## Frozen families",
        "",
        (
            "| Family | Generation Q1 | Q1 vs all | Q1-Q5 | Steps | "
            "Validation Q1 | Q1 vs all | Q1-Q5 | Steps | Decision |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for family in FAMILIES:
        gen = result["generation"][family]["periods"]["generation_2018_2020"]
        val = result["validation"].get(family)
        if val is None:
            val_text = ["unopened", "unopened", "unopened", "unopened"]
        else:
            period = val["period"]
            val_text = [
                f"{period['q1_mean_net_return']:.3%}",
                f"{period['q1_excess_vs_all_eligible']:.3%}",
                f"{period['q1_minus_q5']:.3%}",
                str(period["favorable_adjacent_steps"]),
            ]
        lines.append(
            f"| {family} | {gen['q1_mean_net_return']:.3%} | "
            f"{gen['q1_excess_vs_all_eligible']:.3%} | "
            f"{gen['q1_minus_q5']:.3%} | "
            f"{gen['favorable_adjacent_steps']} | "
            + " | ".join(val_text)
            + f" | {result['interpretation'][family]} |"
        )
    lines += ["", "## Bucket anatomy", ""]
    for family in FAMILIES:
        gen = result["generation"][family]["periods"]["generation_2018_2020"]
        means = gen["bucket_mean_net_returns"]
        lines.append(
            f"- `{family}` generation Q1→Q5: "
            + ", ".join(f"{key} {value:.3%}" for key, value in means.items())
            + f"; Spearman {gen['bucket_spearman_rho']:.3f}."
        )
        val = result["validation"].get(family)
        if val is not None:
            means = val["period"]["bucket_mean_net_returns"]
            lines.append(
                "  Fixed validation Q1→Q5: "
                + ", ".join(f"{key} {value:.3%}" for key, value in means.items())
                + f"; Spearman {val['period']['bucket_spearman_rho']:.3f}."
            )
    lines += ["", "## Executable translation", ""]
    replay = result["replay"]
    if replay is None:
        lines.append("No family passed both frozen gates, so no replay was opened.")
    elif replay.get("status") == "REPLAY_BLOCKED":
        lines.append(f"Replay failed closed: `{replay['error']}`.")
    else:
        lines.append(
            f"The one authorized `{result['replay_audit']['selected_family']}` replay "
            f"returned {replay['total_return']:.2%} total / "
            f"{replay['annualized_return']:.2%} annualized, maximum drawdown "
            f"{replay['maximum_drawdown']:.2%}, Sharpe "
            f"{replay['daily_sharpe']:.3f}. User target met: "
            f"`{result['replay_audit']['meets_user_return_and_drawdown_target']}`."
        )
    lines += [
        "",
        (
            "Post-2023 outcomes and CY-011 were not read. No champion combination, "
            "threshold alternative, or parameter rescue was tested."
        ),
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    daily_paths, _ = CYCLE009.CYCLE5.CYCLE4._input_paths()
    with tempfile.TemporaryDirectory(prefix="ashare-rank-anatomy-") as temporary:
        frame, calendar, input_audit = _build_exact_frame(daily_paths, Path(temporary))
    reproduction = _verify_prior_high_leg(frame, spec)
    selections = _selection_panel(frame, FAMILIES)
    days = pd.to_datetime(selections.trade_date).dt.date
    generation_selection = selections.loc[days <= GEN_END].copy().reset_index(drop=True)
    generation_panel, generation_path_rows = CYCLE009.CYCLE5._attach_outcomes(
        daily_paths, generation_selection, calendar
    )
    generation = {
        family: _generation_decision(generation_panel, family, spec) for family in FAMILIES
    }
    generation_passers = [family for family in FAMILIES if generation[family]["passes"]]
    validation: dict[str, Any] = {}
    validation_panel = pd.DataFrame()
    validation_path_rows = 0
    if generation_passers:
        validation_selection = selections.loc[
            (days >= VALIDATION_START) & selections.family.isin(generation_passers)
        ].copy().reset_index(drop=True)
        validation_panel, validation_path_rows = CYCLE009.CYCLE5._attach_outcomes(
            daily_paths, validation_selection, calendar
        )
        validation = {
            family: _validation_decision(validation_panel, family, spec)
            for family in generation_passers
        }
    bucket_parts = [_bucket_table(generation_panel, "generation_2018_2020")]
    if not validation_panel.empty:
        bucket_parts.append(_bucket_table(validation_panel, "fixed_validation_2021_2023"))
    bucket_table = pd.concat(bucket_parts, ignore_index=True)
    full_panel = pd.concat([generation_panel, validation_panel], ignore_index=True, sort=False)
    authorized = [
        family
        for family in generation_passers
        if validation.get(family, {}).get("passes", False)
    ]
    replay, replay_audit = _replay(
        full_panel,
        authorized,
        generation,
        validation,
        spec,
        daily_paths,
        calendar,
    )
    interpretation = {
        family: _interpret(generation[family], validation.get(family)) for family in FAMILIES
    }
    status = (
        "TARGET_ACHIEVED"
        if replay_audit.get("meets_user_return_and_drawdown_target")
        else "COMPLETE_NO_TARGET_STRATEGY"
    )
    BUCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    bucket_table.sort_values(["period", "family", "rank_bucket"]).to_csv(
        BUCKET_PATH, index=False
    )
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "claim_boundary": spec["claim_boundary"],
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
        "maximum_outcome_date": END,
        "input_audit": input_audit,
        "eligible_rows": len(frame),
        "eligible_symbols": int(frame.symbol.nunique()),
        "decision_dates": int(frame.trade_date.nunique()),
        "prior_high_leg_reproduction": reproduction,
        "generation_path_rows": generation_path_rows,
        "validation_opened_for": generation_passers,
        "validation_path_rows": validation_path_rows,
        "generation": generation,
        "validation": validation,
        "interpretation": interpretation,
        "authorized_replay_families": authorized,
        "replay": replay,
        "replay_audit": replay_audit,
        "success_target": spec["success_target"],
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "bucket_table_sha256": sha256_file(BUCKET_PATH),
        },
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
