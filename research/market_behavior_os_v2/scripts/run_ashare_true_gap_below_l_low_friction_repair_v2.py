#!/usr/bin/env python3
# ruff: noqa: E501
"""Low-friction below-gap repair: expanding Development and fixed replication."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    ashare_below_gap_rebound_v1_core as core,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_reversal_repair_v1 as v1,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-LOW-FRICTION-REPAIR-V2"
START_HEAD = "ada5e9f50d39d75f829fa88e8f2f8196d164510d"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_low_friction_repair_v2"
)
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
VALIDATION_FREEZE = OS / f"artifacts/{EXPERIMENT}_validation_freeze.json"
VALIDATION_RESULT = OS / f"artifacts/{EXPERIMENT}_validation_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
VALIDATION_YEARS = (2022, 2023)


def write_json(path: Path, value: Any) -> None:
    v1.write_json(path, value)


def sha256(path: Path) -> str:
    return v1.sha256(path)


def contract_value() -> dict[str, Any]:
    base = v1.contract_value()
    base["experiment"] = EXPERIMENT
    base["economic_hypothesis"] = (
        "After a clean overhead true gap and a causal below-L washout, a rebound "
        "that achieves price recovery with little cumulative free-float turnover "
        "reveals low supply friction and is more likely to continue toward L."
    )
    base.pop("formation_gate")
    base["low_friction_gate"] = {
        "post_gap_turnover": (
            "sum of PIT daily free-float turnover from first completed session "
            "after gap formation through the completed signal session"
        ),
        "recovery_per_turnover": (
            "recovery_from_20d_low / post_gap_turnover"
        ),
        "development_rule": (
            "for each outer year use the median among all prior Stage-A clean "
            "candidate signals, regardless of execution/outcome availability"
        ),
        "validation_rule": (
            "fixed all-2014-2021 Stage-A clean-candidate median recorded in "
            "validation freeze"
        ),
        "missing_policy": "FAIL_CLOSED",
    }
    base["validation_status_disclosure"] = (
        "2022-2023 V1 aggregate outcomes were already observed before V2. V2 is "
        "a secondary forward replication of a distinct admission mechanism, not "
        "a pristine global OOS claim."
    )
    return base


def persist_contracts() -> dict[str, str]:
    contract = contract_value()
    spec = {
        "experiment": EXPERIMENT,
        "status": "LOW_FRICTION_MECHANISM_FIXED_BEFORE_V2_2022_2023_FEATURE_OR_OUTCOME_READ",
        "contract": contract,
        "dependency_hashes": {
            "v1_runner": sha256(Path(v1.__file__)),
            "v1_core": sha256(Path(core.__file__)),
        },
        "research_disclosure": (
            "Low-friction feature and median-only threshold family were selected "
            "using 2014-2021 Development. No V2 feature or return from 2022-2023 "
            "was inspected during design."
        ),
    }
    write_json(CONTRACT, contract)
    write_json(SPEC, spec)
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def clean_inventory_mask(frame: pd.DataFrame) -> pd.Series:
    return (
        frame.exact_minute_history.fillna(False)
        & frame.pre_gap_inside_density_relative_local.le(1.0)
        & frame.pre_gap_corridor_density_relative_local.le(1.0)
    ).fillna(False)


def attach_low_friction_features(
    signals: pd.DataFrame, daily: pd.DataFrame
) -> pd.DataFrame:
    groups = {
        symbol: part.reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, object]] = []
    for event in signals.itertuples(index=False):
        part = groups[str(event.symbol)]
        gap_pos = np.flatnonzero(
            part.trade_date.eq(pd.Timestamp(event.gap_date)).to_numpy()
        )
        signal_pos = np.flatnonzero(
            part.cal_idx.eq(int(event.signal_cal_idx)).to_numpy()
        )
        if len(gap_pos) != 1 or len(signal_pos) != 1:
            continue
        start = int(gap_pos[0]) + 1
        stop = int(signal_pos[0]) + 1
        if stop <= start:
            raise RuntimeError("low-friction chronology failure")
        post = part.iloc[start:stop]
        valid = v1.source._valid_daily_rows(post) & post.invalid_step_cum.eq(
            float(event.invalid_step_cum)
        ).to_numpy(bool)
        if post.empty or not valid.all():
            continue
        turnover = float(post.turnover_fraction.sum())
        if not np.isfinite(turnover) or turnover <= 0:
            continue
        values = event._asdict()
        rows.append(
            {
                **values,
                "signal_year": int(pd.Timestamp(event.signal_date).year),
                "post_gap_turnover": turnover,
                "recovery_per_turnover": float(event.recovery_from_low20)
                / turnover,
                "feature_latest_timestamp": pd.Timestamp(event.signal_time),
                "feature_uses_post_signal_information": False,
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        raise RuntimeError("low-friction feature construction failure")
    result = result.sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    )
    if result.recovery_per_turnover.isna().any():
        raise RuntimeError("low-friction feature construction failure")
    if result.feature_latest_timestamp.gt(result.signal_time).any():
        raise RuntimeError("post-signal low-friction feature")
    return result.reset_index(drop=True)


def prepare_clean_candidates(
    raw: pd.DataFrame, daily: pd.DataFrame, root: Path, end: pd.Timestamp
) -> pd.DataFrame:
    root.mkdir(parents=True, exist_ok=True)
    v1.configure_external(root, end)
    candidates = raw.loc[raw.form.eq("MA5_RECLAIM")].copy()
    if "signal_time" not in candidates:
        candidates["signal_time"] = pd.to_datetime(candidates.signal_date) + pd.Timedelta(
            hours=15
        )
    candidates = candidates.sort_values(
        ["signal_time", "symbol", "L", "gap_id"], kind="mergesort"
    ).drop_duplicates(["symbol", "signal_date"], keep="first")
    candidates.to_parquet(
        root / "all_signal_candidates.parquet", index=False, compression="zstd"
    )
    vap, _profiles = v1.build_vap_for_signals(candidates, daily)
    clean = candidates.merge(vap, on="gap_id", how="left", validate="one_to_one")
    clean = clean.loc[clean_inventory_mask(clean)].copy()
    features = attach_low_friction_features(clean, daily)
    features.to_parquet(
        root / "stage_a_low_friction_candidates.parquet",
        index=False,
        compression="zstd",
    )
    return features


def run_selected(
    selected: pd.DataFrame,
    daily: pd.DataFrame,
    root: Path,
    end: pd.Timestamp,
    years: tuple[int, ...],
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    v1.configure_external(root, end)
    selected.to_parquet(v1.SIGNALS, index=False, compression="zstd")
    entries = v1.build_entries(selected)
    minutes = v1.build_minute_path(entries, daily)
    outcomes = v1.build_outcomes(
        entries,
        minutes,
        daily,
        alphas=(v1.TARGET_FRACTION,),
        horizons=(v1.TIME_STOP,),
        stops=("NONE",),
    )
    outcomes["entry_date"] = pd.to_datetime(outcomes.entry_date)
    portfolio = v1.run_portfolio(outcomes, daily, years)
    return outcomes, portfolio, entries


def run_development() -> dict[str, Any]:
    hashes = persist_contracts()
    root = EXT_ROOT / "development"
    daily = v1.source.load_daily_through_2021()
    raw = core.build_signals()
    features = prepare_clean_candidates(raw, daily, root, pd.Timestamp("2021-12-31"))
    selections: list[dict[str, Any]] = []
    pieces: list[pd.DataFrame] = []
    for year in DEVELOPMENT_YEARS:
        train = features.loc[features.signal_year.lt(year)]
        test = features.loc[features.signal_year.eq(year)]
        threshold = float(train.recovery_per_turnover.median())
        chosen = test.loc[test.recovery_per_turnover.ge(threshold)].copy()
        chosen["outer_year"] = year
        chosen["train_feature_threshold"] = threshold
        pieces.append(chosen)
        selections.append(
            {
                "outer_year": year,
                "train_candidate_count": len(train),
                "threshold": threshold,
                "selected_stage_a_signals": len(chosen),
            }
        )
    selected = pd.concat(pieces, ignore_index=True)
    outcomes, portfolio, entries = run_selected(
        selected,
        daily,
        root,
        pd.Timestamp("2021-12-31"),
        DEVELOPMENT_YEARS,
    )
    final_threshold = float(features.recovery_per_turnover.median())
    audit = {
        "feature_uses_post_signal_information_count": int(
            features.feature_uses_post_signal_information.sum()
        ),
        "threshold_uses_outcome_eligible_only_count": 0,
        "entry_at_or_before_signal_count": int(
            entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY"), "entry_time"].le(
                entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY"), "signal_time"]
            ).sum()
        ),
        "t1_violation_count": int(
            outcomes.exit_cal_idx.le(outcomes.entry_cal_idx).sum()
        ),
        "repository_2024_plus_data_opened": "NO",
    }
    if any(value for key, value in audit.items() if key.endswith("_count")):
        raise RuntimeError(f"Development audit failed: {audit}")
    result = {
        "experiment": EXPERIMENT,
        "label": "EXPANDING_DEVELOPMENT_2017_2021",
        **hashes,
        "stage_a_clean_candidates": len(features),
        "outer_selections": selections,
        "selected_stage_a_signals": len(selected),
        "complete_outcomes": len(outcomes),
        "event_metrics": v1.trade_metrics(outcomes),
        "portfolio": portfolio,
        "final_validation_threshold": final_threshold,
        "hashes": {
            "features": sha256(root / "stage_a_low_friction_candidates.parquet"),
            "entries": sha256(v1.ENTRIES),
            "outcomes": sha256(v1.OUTCOMES),
            "portfolio_nav": sha256(root / "portfolio_nav.parquet"),
        },
        "audit": audit,
    }
    write_json(DEVELOPMENT_RESULT, result)
    return result


def freeze_validation() -> dict[str, Any]:
    if not DEVELOPMENT_RESULT.is_file():
        raise RuntimeError("V2 Development missing")
    hashes = persist_contracts()
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    if development["contract_sha256"] != hashes["contract_sha256"]:
        raise RuntimeError("contract drift")
    freeze = {
        "experiment": EXPERIMENT,
        "frozen_before_v2_validation_feature_or_outcome_read": True,
        "contract_sha256": hashes["contract_sha256"],
        "spec_sha256": hashes["spec_sha256"],
        "runner_sha256": sha256(Path(__file__)),
        "v1_runner_sha256": sha256(Path(v1.__file__)),
        "v1_core_sha256": sha256(Path(core.__file__)),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
        "fixed_recovery_per_turnover_threshold": development[
            "final_validation_threshold"
        ],
        "validation_period": ["2022-01-01", "2023-12-31"],
        "validation_status": "SECONDARY_FORWARD_REPLICATION_AFTER_V1_AGGREGATE_OBSERVED",
        "v2_validation_feature_opened": "NO",
        "v2_validation_outcome_opened": "NO",
        "repository_2024_plus_data_opened": "NO",
    }
    write_json(VALIDATION_FREEZE, freeze)
    return freeze


def verify_freeze() -> dict[str, Any]:
    freeze = json.loads(VALIDATION_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "v1_runner_sha256": sha256(Path(v1.__file__)),
        "v1_core_sha256": sha256(Path(core.__file__)),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
    }
    drift = {key: [freeze.get(key), value] for key, value in checks.items() if freeze.get(key) != value}
    if drift:
        raise RuntimeError(f"V2 freeze drift: {drift}")
    return freeze


def validation_passed(result: dict[str, Any]) -> tuple[bool, dict[str, bool]]:
    combined = result["portfolio"]["COMBINED"]
    main = result["portfolio"]["MAIN"]
    chinext = result["portfolio"]["CHINEXT"]
    checks = {
        "trade_count": 70 <= int(combined["trades"]) <= 150,
        "mean_net": float(combined["mean_net"]) >= 0.03,
        "median_net": float(combined["median_net"]) > 0,
        "both_years_positive": all(
            float(combined["annual_returns"][str(year)]) > 0
            for year in VALIDATION_YEARS
        ),
        "both_boards_positive": float(main["mean_net"]) > 0
        and float(chinext["mean_net"]) > 0,
        "severe10": float(combined["severe10"]) <= 0.15,
        "max_drawdown": float(combined["max_drawdown"]) >= -0.15,
        "excluding_best_five": float(combined["return_excluding_best_five_days"])
        > 0,
    }
    return all(checks.values()), checks


def run_validation() -> dict[str, Any]:
    freeze = verify_freeze()
    root = EXT_ROOT / "validation"
    daily = v1.load_daily(pd.Timestamp("2023-12-31"))
    gaps = core.build_all_true_gaps(daily)
    raw = core.build_ma5_signal_candidates(daily, gaps)
    raw = raw.loc[raw.signal_date.dt.year.isin(VALIDATION_YEARS)].copy()
    features = prepare_clean_candidates(raw, daily, root, pd.Timestamp("2023-12-31"))
    threshold = float(freeze["fixed_recovery_per_turnover_threshold"])
    selected = features.loc[features.recovery_per_turnover.ge(threshold)].copy()
    outcomes, portfolio, entries = run_selected(
        selected,
        daily,
        root,
        pd.Timestamp("2023-12-31"),
        VALIDATION_YEARS,
    )
    result = {
        "experiment": EXPERIMENT,
        "label": "SECONDARY_FORWARD_REPLICATION_2022_2023",
        "stage_a_clean_candidates": len(features),
        "fixed_threshold": threshold,
        "selected_stage_a_signals": len(selected),
        "entry_status": {
            str(key): int(value)
            for key, value in entries.entry_status.value_counts().items()
        },
        "complete_outcomes": len(outcomes),
        "event_metrics": v1.trade_metrics(outcomes),
        "portfolio": portfolio,
        "audit": {
            "feature_uses_post_signal_information_count": int(
                features.feature_uses_post_signal_information.sum()
            ),
            "validation_rule_changed_count": 0,
            "repository_2024_plus_data_opened": "NO",
        },
    }
    passed, checks = validation_passed(result)
    result["validation_checks"] = checks
    result["verdict"] = (
        "LOW_FRICTION_REPAIR_SECONDARY_REPLICATION_PASSED"
        if passed
        else "LOW_FRICTION_REPAIR_SECONDARY_REPLICATION_FAILED"
    )
    result["validation_freeze_sha256"] = sha256(VALIDATION_FREEZE)
    write_json(VALIDATION_RESULT, result)
    return result


def render_report() -> None:
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    validation = json.loads(VALIDATION_RESULT.read_text(encoding="utf-8")) if VALIDATION_RESULT.is_file() else None
    combined = development["portfolio"]["COMBINED"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Mechanism",
        "",
        "Buy the first causal MA5 reversal while price remains below a clean overhead true gap only when recovery from the post-gap low is large relative to all completed post-gap free-float turnover. This is a low-supply-friction hypothesis, not an accumulation claim.",
        "",
        "## Expanding Development 2017-2021",
        "",
        f"- Stage-A selected signals / complete outcomes: {development['selected_stage_a_signals']} / {development['complete_outcomes']}",
        f"- K20 trades / mean / median: {combined['trades']} / {combined['mean_net']:.2%} / {combined['median_net']:.2%}",
        f"- Severe10 / CAGR / MaxDD / Sharpe: {combined['severe10']:.2%} / {combined['cagr']:.2%} / {combined['max_drawdown']:.2%} / {combined['sharpe']:.3f}",
        "",
    ]
    if validation is None:
        lines += ["## 2022-2023 secondary replication", "", "Not opened.", ""]
    else:
        value = validation["portfolio"]["COMBINED"]
        lines += [
            "## 2022-2023 secondary forward replication",
            "",
            "This period had prior V1 aggregate observation and is not labeled pristine global OOS.",
            f"- Selected signals / complete outcomes: {validation['selected_stage_a_signals']} / {validation['complete_outcomes']}",
            f"- K20 trades / mean / median: {value['trades']} / {value['mean_net']:.2%} / {value['median_net']:.2%}",
            f"- Severe10 / total return / MaxDD: {value['severe10']:.2%} / {value['total_return']:.2%} / {value['max_drawdown']:.2%}",
            f"- Verdict: {validation['verdict']}",
            "",
        ]
    lines += ["## Governance", "", "No 2024+ data was opened. V1 implementation files were not modified."]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage", choices=("development", "freeze-validation", "validation", "report")
    )
    args = parser.parse_args()
    if args.stage == "development":
        print(json.dumps(run_development(), indent=2, default=str))
    elif args.stage == "freeze-validation":
        print(json.dumps(freeze_validation(), indent=2, default=str))
    elif args.stage == "validation":
        print(json.dumps(run_validation(), indent=2, default=str))
    else:
        render_report()


if __name__ == "__main__":
    main()
