#!/usr/bin/env python3
"""Test one frozen late-demand-trap down-ranking rule inside the Champion."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
EXPERIMENT_ID = "ASHARE-CHAMPION-LATE-DEMAND-TRAP-RANK-V1"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
SCORE_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_score_panel.csv"
EQUITY_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_equity.csv"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
INTRADAY_PATH = PROGRAM / "scripts/run_ashare_intraday_indep_cycle_004.py"
CYCLE016_PATH = PROGRAM / "scripts/run_ashare_champion_anatomy_cycle_016.py"
EXPECTED_SPEC_SHA256 = "d66bfdf028b824ba09f468b43ae9cc6cbb4cf8964654d3606d52fe62c68beafc"
FAMILY = "industry_diffusion_low_max_low_late_demand"
INITIAL_CAPITAL = 10_000_000.0


class LateDemandTrapError(RuntimeError):
    """Fail-closed late-demand portability error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise LateDemandTrapError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


INTRADAY = _load_module("ashare_intraday_004_for_late_demand", INTRADAY_PATH)
CYCLE016 = _load_module("ashare_cycle016_for_late_demand", CYCLE016_PATH)
CONSTRUCTION = CYCLE016.CONSTRUCTION
CA = CYCLE016.CA


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise LateDemandTrapError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_CHAMPION_INTRADAY_SCORE_JOIN":
        raise LateDemandTrapError("spec is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise LateDemandTrapError(f"bound input changed: {name}")
    INTRADAY._load_spec()
    CYCLE016._load_spec()
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


def _build_incremental_score(
    spec: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    scratch = Path(spec["resource"]["scratch_root"])
    scratch.mkdir(parents=True, exist_ok=True)
    if not os.access(scratch, os.W_OK):
        raise LateDemandTrapError("external scratch is not writable")
    if shutil.disk_usage(scratch).free < 10 * 2**30:
        raise LateDemandTrapError("external scratch free-space floor failed")
    daily_paths, minute_paths = INTRADAY._input_paths()
    frame, _, source_audit = INTRADAY._build_frame(
        daily_paths, minute_paths, scratch
    )
    base = frame.copy()
    base["control_return"] = base.groupby("trade_date")["step_log_return"].transform(
        INTRADAY._rank
    )
    base["control_range"] = base.groupby("trade_date")["daily_range"].transform(
        INTRADAY._rank
    )
    base["control_r20"] = base.groupby("trade_date")["r20"].transform(
        INTRADAY._rank
    )
    ranked_vwap = base.groupby("trade_date")["close_vs_vwap"].transform(
        INTRADAY._rank
    )
    ranked_close = base.groupby("trade_date")["closing_30m_return"].transform(
        INTRADAY._rank
    )
    ranked_late_volume = base.groupby("trade_date")["last_hour_volume_share"].transform(
        INTRADAY._rank
    )
    base["raw_score"] = (ranked_vwap + ranked_close + ranked_late_volume) / 3.0
    base["raw_rank"] = base.groupby("trade_date")["raw_score"].transform(
        INTRADAY._rank
    )
    base["signal_score"] = (
        base.groupby("trade_date", group_keys=False)
        .apply(INTRADAY._residualize, include_groups=False)
        .reindex(base.index)
    )
    score = base.loc[
        np.isfinite(base.signal_score),
        ["trade_date", "symbol", "signal_score", "raw_score"],
    ].copy()
    score["trade_date"] = pd.to_datetime(score.trade_date).dt.date
    if score.empty or score.duplicated(["trade_date", "symbol"]).any():
        raise LateDemandTrapError("invalid incremental-score panel")
    return score, source_audit


def _champion_plans_and_selection(
    spec: dict[str, Any], score: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    anatomy_spec = json.loads(
        _resolve(spec["inputs"]["champion_anatomy_spec"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    daily = pd.read_parquet(
        _resolve(anatomy_spec["inputs"]["causal_daily_panel"]["path"])
    )
    construction_spec = CONSTRUCTION._load_spec()
    _, champion = CYCLE016.CYCLE015._weekly_selections(daily, construction_spec)
    champion = champion.copy()
    champion["signal_date"] = pd.to_datetime(champion.trade_date).dt.date
    champion = champion.merge(
        score.rename(
            columns={
                "trade_date": "signal_date",
                "signal_score": "late_demand_score",
                "raw_score": "late_demand_raw_score",
            }
        ),
        on=["signal_date", "symbol"],
        how="left",
        validate="one_to_one",
    )
    if (
        len(champion) != 2670
        or champion.signal_date.nunique() != 267
        or not champion.groupby("signal_date").size().eq(10).all()
    ):
        raise LateDemandTrapError("frozen Champion identity/breadth changed")
    champion["score_valid"] = np.isfinite(champion.late_demand_score)
    valid = champion.loc[champion.score_valid].copy()
    valid = valid.sort_values(
        ["signal_date", "late_demand_score", "symbol"],
        ascending=[True, True, True],
    )
    valid["late_demand_rank"] = valid.groupby("signal_date").cumcount() + 1
    supported_dates = set(
        valid.groupby("signal_date").size().loc[lambda x: x >= 3].index
    )
    valid["selected"] = valid.signal_date.isin(supported_dates) & valid.late_demand_rank.le(3)
    chosen = valid.loc[valid.selected].copy()
    if not chosen.groupby("signal_date").size().eq(3).all():
        raise LateDemandTrapError("frozen three-name selection failed")
    selection = champion.merge(
        valid[["signal_date", "symbol", "late_demand_rank", "selected"]],
        on=["signal_date", "symbol"],
        how="left",
        validate="one_to_one",
        suffixes=("", "_ranked"),
    )
    selection["selected"] = selection.selected.eq(True)
    champion["family"] = FAMILY
    calendar = CA._load_market_inputs(CA._load_spec())[1]
    plans = CONSTRUCTION._make_plans(champion, calendar)
    selected_keys = chosen[["signal_date", "symbol"]].copy()
    selected_keys["keep"] = True
    plans = plans.merge(
        selected_keys,
        on=["signal_date", "symbol"],
        how="left",
        validate="one_to_one",
    )
    plans = plans.loc[plans.keep.eq(True)].drop(columns="keep").copy()
    plans["family"] = FAMILY
    return selection, plans


def _load_outcomes(
    spec: dict[str, Any], start: date, end: date
) -> pd.DataFrame:
    columns = ["signal_date", "symbol", "final_net_return"]
    trades = pd.read_parquet(
        _resolve(spec["inputs"]["champion_trade_panel"]["path"]),
        columns=columns,
        filters=[("signal_date", ">=", start), ("signal_date", "<=", end)],
    )
    trades["signal_date"] = pd.to_datetime(trades.signal_date).dt.date
    if trades.empty or min(trades.signal_date) < start or max(trades.signal_date) > end:
        raise LateDemandTrapError("outcome boundary failed")
    return trades


def _period_metrics(selection: pd.DataFrame, outcomes: pd.DataFrame) -> dict[str, Any]:
    joined = outcomes.merge(
        selection[["signal_date", "symbol", "score_valid", "selected"]],
        on=["signal_date", "symbol"],
        how="left",
        validate="one_to_one",
    )
    if joined.selected.isna().any():
        raise LateDemandTrapError("outcome/selection alignment failed")
    selected = joined.loc[joined.selected]
    if selected.empty:
        raise LateDemandTrapError("selected outcome set empty")
    planned = selection.loc[selection.signal_date.isin(set(outcomes.signal_date))]
    valid_dates = planned.groupby("signal_date").selected.sum().loc[lambda x: x.eq(3)]
    return {
        "decision_dates": int(outcomes.signal_date.nunique()),
        "selected_decision_dates": int(valid_dates.size),
        "score_coverage": float(planned.score_valid.mean()),
        "all_rows": len(joined),
        "selected_rows": len(selected),
        "all_mean_return": float(joined.final_net_return.mean()),
        "selected_mean_return": float(selected.final_net_return.mean()),
        "selected_minus_all_mean_return": float(
            selected.final_net_return.mean() - joined.final_net_return.mean()
        ),
        "all_median_return": float(joined.final_net_return.median()),
        "selected_median_return": float(selected.final_net_return.median()),
        "all_winner_fraction": float(joined.final_net_return.gt(0).mean()),
        "selected_winner_fraction": float(selected.final_net_return.gt(0).mean()),
        "all_severe_fraction": float(joined.final_net_return.le(-0.10).mean()),
        "selected_severe_fraction": float(selected.final_net_return.le(-0.10).mean()),
        "severe_loss_improvement": float(
            joined.final_net_return.le(-0.10).mean()
            - selected.final_net_return.le(-0.10).mean()
        ),
    }


def _generation(
    selection: pd.DataFrame, outcomes: pd.DataFrame, spec: dict[str, Any]
) -> dict[str, Any]:
    years = pd.to_datetime(outcomes.signal_date).dt.year
    full = _period_metrics(selection, outcomes)
    early = _period_metrics(selection, outcomes.loc[years.le(2019)])
    year2020 = _period_metrics(selection, outcomes.loc[years.eq(2020)])
    gate = spec["generation_gate_all_required"]
    checks = {
        "coverage": full["score_coverage"] >= gate["minimum_score_coverage"],
        "dates": full["selected_decision_dates"] >= gate["minimum_decision_dates"],
        "selected_mean": full["selected_mean_return"]
        >= gate["minimum_selected_mean_return"],
        "improvement": full["selected_minus_all_mean_return"]
        >= gate["minimum_selected_minus_all_mean_return"],
        "median": full["selected_median_return"]
        >= gate["minimum_selected_median_return"],
        "severe": full["severe_loss_improvement"]
        >= gate["minimum_severe_loss_improvement"],
        "2018_2019": early["selected_minus_all_mean_return"]
        >= gate["minimum_2018_2019_selected_minus_all"],
        "2020": year2020["selected_minus_all_mean_return"]
        >= gate["minimum_2020_selected_minus_all"],
    }
    return {
        "periods": {
            "generation_2018_2020": full,
            "generation_2018_2019": early,
            "generation_2020": year2020,
        },
        "checks": checks,
        "passes": all(checks.values()),
    }


def _validation(
    selection: pd.DataFrame, outcomes: pd.DataFrame, spec: dict[str, Any]
) -> dict[str, Any]:
    full = _period_metrics(selection, outcomes)
    years = pd.to_datetime(outcomes.signal_date).dt.year
    yearly = {
        str(year): _period_metrics(selection, outcomes.loc[years.eq(year)])
        for year in (2021, 2022, 2023)
    }
    gate = spec["validation_gate_all_required"]
    checks = {
        "coverage": full["score_coverage"] >= gate["minimum_score_coverage"],
        "selected_mean": full["selected_mean_return"]
        >= gate["minimum_selected_mean_return"],
        "improvement": full["selected_minus_all_mean_return"]
        >= gate["minimum_selected_minus_all_mean_return"],
        "severe": full["severe_loss_improvement"]
        >= gate["minimum_severe_loss_improvement"],
        "calendar_years": sum(
            row["selected_minus_all_mean_return"] > 0 for row in yearly.values()
        )
        >= gate["minimum_positive_calendar_year_improvements"],
    }
    return {"full": full, "yearly": yearly, "checks": checks, "passes": all(checks.values())}


def _baseline(spec: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(
        _resolve(spec["inputs"]["champion_authoritative_result"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    return result["track_a"]["matched_cost_comparisons"]["20bps"]["low_max"]


def _comparison(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float]:
    return {
        "total_return_delta": float(candidate["total_return"] - baseline["total_return"]),
        "annualized_return_delta": float(
            candidate["annualized_return"] - baseline["annualized_return"]
        ),
        "maximum_drawdown_improvement": float(
            candidate["maximum_drawdown"] - baseline["maximum_drawdown"]
        ),
        "daily_sharpe_delta": float(candidate["daily_sharpe"] - baseline["daily_sharpe"]),
        "severe_trade_fraction_improvement": float(
            baseline["severe_trade_fraction"] - candidate["severe_trade_fraction"]
        ),
    }


def _year_returns(equity: pd.DataFrame) -> dict[str, float]:
    work = equity.copy()
    work["year"] = pd.to_datetime(work.trade_date).dt.year
    ending = work.groupby("year").nav.last().sort_index()
    output: dict[str, float] = {}
    prior = INITIAL_CAPITAL
    for year, nav in ending.items():
        output[str(int(year))] = float(nav / prior - 1.0)
        prior = float(nav)
    return output


def _replay(
    plans: pd.DataFrame,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    ca_spec = CA._load_spec()
    paths, calendar, input_identity = CA._load_market_inputs(ca_spec)
    market_rows = CA.PRIOR._query_execution_rows(paths, plans, calendar)
    events, action_audit = CA._load_risk_events(ca_spec, calendar)
    candidate, equity, exits = CA._replay(FAMILY, plans, market_rows, calendar, events)
    return candidate, equity, exits, input_identity, action_audit


def _render(result: dict[str, Any]) -> str:
    generation = result["generation"]["periods"]["generation_2018_2020"]
    lines = [
        "# Champion late-demand-trap rank V1",
        "",
        f"Status: `{result['status']}`.",
        "",
        (
            "The only rule chooses the three lowest exact Cycle-004 late-demand "
            "residual scores inside each frozen Champion cohort. It uses completed "
            "close-vs-VWAP, closing-30-minute return, and last-hour volume share, "
            "then enters no earlier than the next legal open."
        ),
        "",
        "## Generation",
        "",
        (
            f"Selected mean {generation['selected_mean_return']:.3%} versus all-ten "
            f"{generation['all_mean_return']:.3%}; improvement "
            f"{generation['selected_minus_all_mean_return']:.3%}; coverage "
            f"{generation['score_coverage']:.2%}; gate "
            f"`{result['generation']['passes']}`."
        ),
        "",
        "## Validation and replay",
        "",
    ]
    if result["validation"] is None:
        lines.append("Validation remained unopened because the generation gate failed.")
    else:
        validation = result["validation"]["full"]
        lines.append(
            f"Validation selected mean {validation['selected_mean_return']:.3%}, "
            f"improvement {validation['selected_minus_all_mean_return']:.3%}; "
            f"gate `{result['validation']['passes']}`."
        )
    if result["candidate"] is None:
        lines.append("No executable replay was authorized.")
    else:
        candidate = result["candidate"]
        lines.append(
            f"Replay annualized {candidate['annualized_return']:.2%}, max drawdown "
            f"{candidate['maximum_drawdown']:.2%}, Sharpe "
            f"{candidate['daily_sharpe']:.3f}; target met "
            f"`{result['target_met']}`."
        )
    lines += [
        "",
        (
            "This is consumed-history development optimization, not independent "
            "confirmation. No alternate minute descriptor, threshold, Top-N, "
            "holding period, post-2023 outcome, or CY-011 field was opened."
        ),
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    score, source_audit = _build_incremental_score(spec)
    selection, plans = _champion_plans_and_selection(spec, score)
    generation_outcomes = _load_outcomes(
        spec, date(2018, 1, 1), date(2020, 12, 31)
    )
    generation = _generation(selection, generation_outcomes, spec)
    validation = None
    candidate = None
    equity = pd.DataFrame(columns=["trade_date", "nav"])
    exits = pd.DataFrame()
    input_identity = None
    action_audit = None
    if generation["passes"]:
        validation_outcomes = _load_outcomes(
            spec, date(2021, 1, 1), date(2023, 12, 31)
        )
        validation = _validation(selection, validation_outcomes, spec)
        if validation["passes"]:
            candidate, equity, exits, input_identity, action_audit = _replay(plans)
    baseline = _baseline(spec)
    comparison = None if candidate is None else _comparison(candidate, baseline)
    target = spec["success_target"]
    target_met = bool(
        candidate is not None
        and candidate["annualized_return"] >= target["minimum_annualized_return"]
        and candidate["maximum_drawdown"]
        > target["maximum_drawdown_must_be_greater_than"]
    )
    status = (
        "TARGET_ACHIEVED"
        if target_met
        else "GENERATION_FAILED"
        if not generation["passes"]
        else "VALIDATION_FAILED"
        if validation is not None and not validation["passes"]
        else "REPLAY_TARGET_NOT_MET"
    )
    compact = selection[
        [
            "signal_date",
            "symbol",
            "industry",
            "late_demand_score",
            "late_demand_raw_score",
            "score_valid",
            "late_demand_rank",
            "selected",
        ]
    ].sort_values(["signal_date", "selected", "late_demand_rank", "symbol"])
    _atomic_write(
        SCORE_PATH,
        compact.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    _atomic_write(
        EQUITY_PATH,
        equity.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    result = {
        "experiment_id": EXPERIMENT_ID,
        "status": status,
        "claim_boundary": spec["claim_boundary"],
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
        "score": spec["fixed_score"],
        "selection_rule": spec["fixed_selection"],
        "source_audit": source_audit,
        "generation": generation,
        "validation": validation,
        "replay_authorized": candidate is not None,
        "baseline": baseline,
        "candidate": candidate,
        "comparison": comparison,
        "calendar_year_returns": None if candidate is None else _year_returns(equity),
        "forced_exit_rows": len(exits),
        "input_identity": input_identity,
        "action_audit": action_audit,
        "target": target,
        "target_met": target_met,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "score_panel_sha256": sha256_file(SCORE_PATH),
            "equity_sha256": sha256_file(EQUITY_PATH),
        },
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
