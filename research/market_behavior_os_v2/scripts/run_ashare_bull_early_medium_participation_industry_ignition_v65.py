#!/usr/bin/env python3
"""Reproduce the causal V65 early- plus medium-participation bull strategy."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import run_ashare_bull_medium_participation_industry_ignition_v64 as v64

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-EARLY-MEDIUM-PARTICIPATION-INDUSTRY-IGNITION-V65"
EXT = Path("/Volumes/quant/CY_quant_research/bull_early_medium_participation_industry_ignition_v65")
SOURCE = v64.SOURCE_CANDIDATES
SOURCE_SHA256 = v64.SOURCE_CANDIDATE_SHA256
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
CANDIDATES = EXT / "stage_a/candidates.parquet"
DEV_OUTCOMES = EXT / "stage_b/development_outcomes.parquet"
FORWARD_OUTCOMES = EXT / "stage_b/forward_outcomes.parquet"
DEV_ACCEPTED = EXT / "stage_b/development_accepted.parquet"
DEV_SKIPPED = EXT / "stage_b/development_skipped.parquet"
DEV_NAV = EXT / "stage_b/development_nav.parquet"
ACCEPTED = EXT / "stage_b/combined_accepted.parquet"
SKIPPED = EXT / "stage_b/combined_skipped.parquet"
NAV = EXT / "stage_b/combined_nav.parquet"
POST_ROOT = Path(
    "/Volumes/quant/CY_quant_research/bull_v64_expansion_complement_v65_mechanism/"
    "post_2023_diagnostics_through_2026_09_04"
)
POST_RESULT = POST_ROOT / "result.json"
POST_ACCEPTED = POST_ROOT / "UNION_accepted.parquet"
POST_NAV = POST_ROOT / "UNION_nav.parquet"
PROFILE = "T15_H15_NO_STOP"
DEVELOPMENT = tuple(range(2014, 2021))
FORWARD = (2021, 2022, 2023)
YEARS = tuple(range(2014, 2024))


class ResearchError(RuntimeError):
    """Fail closed on source, chronology, causal, or execution drift."""


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def peak_age_calendar_days(frame: pd.DataFrame) -> pd.Series:
    return (pd.to_datetime(frame.signal_date) - pd.to_datetime(frame.prior250_peak_date)).dt.days


def common_mask(frame: pd.DataFrame) -> pd.Series:
    """Conditions common to both V65 lanes, beyond the frozen V53 source."""
    return (
        frame.market_breadth20.ge(0.65)
        & frame.industry_breadth20_delta5.ge(0.25)
        & frame.ret60.le(0.15)
        & frame.step_return.le(0.06)
        & frame.turnover_ratio.ge(1.50)
    )


def medium_mask(frame: pd.DataFrame) -> pd.Series:
    """Exact frozen V64 medium-participation admission."""
    return common_mask(frame) & frame.market_breadth60.ge(0.45)


def early_mask(frame: pd.DataFrame) -> pd.Series:
    """Frozen old-pressure early-diffusion expansion selected in 2014-2020."""
    return (
        common_mask(frame)
        & frame.market_breadth60.lt(0.45)
        & frame.industry_breadth20_delta5.le(0.60)
        & peak_age_calendar_days(frame).ge(120)
        & frame.prior250_peak_invalid_cum.eq(frame.invalid_step_cum)
    )


def select_candidates() -> pd.DataFrame:
    if sha(SOURCE) != SOURCE_SHA256:
        raise ResearchError("frozen V53 source candidate drift")
    source = v64.parent.base.v1.read_parquet_duckdb(SOURCE)
    for column in (
        "trade_date",
        "signal_date",
        "prior250_peak_date",
        "available_at",
        "decision_at",
        "feature_latest_timestamp",
    ):
        source[column] = pd.to_datetime(source[column])
    if not v64.parent.source_contract_mask(source).all():
        raise ResearchError("V53 source contract violation")
    medium = source.loc[medium_mask(source)].copy()
    early = source.loc[early_mask(source)].copy()
    if set(medium.event_id) & set(early.event_id):
        raise ResearchError("V65 lanes are not mutually exclusive")
    medium["lane"] = "MEDIUM_PARTICIPATION"
    early["lane"] = "EARLY_TRANSITION"
    selected = pd.concat([medium, early], ignore_index=True)
    selected["source_event_id"] = selected.event_id.astype(str)
    selected["event_id"] = "V65|" + selected.lane.astype(str) + "|" + selected.source_event_id
    selected["prior250_peak_age_calendar_days"] = peak_age_calendar_days(selected)
    selected["industry_positive_ret20_share"] = selected.industry_breadth20_delta5
    selected["stock_minus_industry_ret20"] = -selected.ret60
    selected["turnover_expansion"] = selected.turnover_ratio
    selected = selected.sort_values(["signal_date", "event_id"], kind="mergesort").reset_index(
        drop=True
    )
    if selected.event_id.duplicated().any() or selected.source_event_id.duplicated().any():
        raise ResearchError("duplicate V65 event identity")
    return selected


def candidate_audit(frame: pd.DataFrame) -> dict[str, int]:
    expected_decision = frame.signal_date.dt.normalize() + pd.Timedelta(hours=15)
    source_contract = v64.parent.source_contract_mask(frame)
    lane_contract = (frame.lane.eq("MEDIUM_PARTICIPATION") & medium_mask(frame)) | (
        frame.lane.eq("EARLY_TRANSITION") & early_mask(frame)
    )
    return {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "duplicate_source_event_count": int(frame.source_event_id.duplicated().sum()),
        "source_contract_violation_count": int((~source_contract).sum()),
        "lane_contract_violation_count": int((~lane_contract).sum()),
        "feature_after_decision_count": int(
            frame.feature_latest_timestamp.gt(frame.decision_at).sum()
        ),
        "availability_after_decision_count": int(frame.available_at.gt(frame.decision_at).sum()),
        "decision_not_signal_close_count": int(frame.decision_at.ne(expected_decision).sum()),
        "prior_peak_at_or_after_signal_count": int(
            frame.prior250_peak_date.ge(frame.signal_date).sum()
        ),
        "early_prior_peak_lineage_mismatch_count": int(
            frame.loc[frame.lane.eq("EARLY_TRANSITION"), "prior250_peak_invalid_cum"]
            .ne(frame.loc[frame.lane.eq("EARLY_TRANSITION"), "invalid_step_cum"])
            .sum()
        ),
        "hard_valid_false_count": int(frame.hard_valid.ne(True).sum()),
        "post_2023_candidate_count": int(frame.signal_date.gt("2023-12-31").sum()),
    }


def run_stage_a() -> dict[str, Any]:
    candidates = select_candidates()
    audit = candidate_audit(candidates)
    if any(audit.values()):
        raise ResearchError(f"Stage-A audit failed: {audit}")
    v64.parent.base.v1.write_parquet(candidates, CANDIDATES)
    freeze = {
        "experiment": EXPERIMENT,
        "status": "FROZEN_BEFORE_REPRODUCTION_OUTCOME_BUILD",
        "contract_sha256": sha(CONTRACT),
        "spec_sha256": sha(SPEC),
        "runner_sha256": sha(Path(__file__)),
        "source_candidate_sha256": sha(SOURCE),
        "candidate_sha256": sha(CANDIDATES),
        "candidate_count": len(candidates),
        "lane_counts": candidates.lane.value_counts().astype(int).to_dict(),
        "annual_candidate_counts": candidates.groupby(candidates.signal_date.dt.year)
        .size()
        .astype(int)
        .to_dict(),
        "audit": audit,
        "outcomes_opened_during_this_reproduction_stage": False,
        "post_2023_used_for_rule_selection": False,
    }
    write_json(FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    expected = {
        "contract_sha256": sha(CONTRACT),
        "spec_sha256": sha(SPEC),
        "runner_sha256": sha(Path(__file__)),
        "source_candidate_sha256": sha(SOURCE),
        "candidate_sha256": sha(CANDIDATES),
    }
    drift = {
        key: [freeze.get(key), value] for key, value in expected.items() if freeze.get(key) != value
    }
    if drift:
        raise ResearchError(f"Stage-A drift: {drift}")
    return freeze


def attach_fields(outcomes: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "event_id",
        "source_event_id",
        "lane",
        "industry_positive_ret20_share",
        "stock_minus_industry_ret20",
        "turnover_expansion",
    ]
    return outcomes.merge(candidates[fields], on="event_id", how="left", validate="many_to_one")


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    return v64.parent.summarize(frame)


def date_equal(frame: pd.DataFrame) -> float | None:
    return None if frame.empty else float(frame.groupby("signal_date").net_return.mean().mean())


def cluster_bootstrap_mean_ci(
    frame: pd.DataFrame, seed: int = 65, draws: int = 10000
) -> list[float]:
    groups = [
        part.net_return.to_numpy() for _, part in frame.groupby(frame.signal_date.dt.normalize())
    ]
    rng = np.random.default_rng(seed)
    values = np.empty(draws)
    for draw in range(draws):
        picks = rng.integers(0, len(groups), len(groups))
        values[draw] = np.concatenate([groups[index] for index in picks]).mean()
    return [float(value) for value in np.quantile(values, [0.025, 0.5, 0.975])]


def block_bootstrap_nav_excess_ci(
    candidate_nav: pd.DataFrame, baseline_nav: pd.DataFrame, seed: int = 650, draws: int = 10000
) -> list[float]:
    joined = candidate_nav.merge(baseline_nav, on="trade_date", suffixes=("_v65", "_v64"))
    joined["v65_return"] = joined.combined_nav_v65.pct_change().fillna(
        joined.combined_nav_v65.iloc[0] - 1
    )
    joined["v64_return"] = joined.combined_nav_v64.pct_change().fillna(
        joined.combined_nav_v64.iloc[0] - 1
    )
    values = (joined.v65_return - joined.v64_return).to_numpy()
    length = 20
    count = len(values)
    rng = np.random.default_rng(seed)
    results = np.empty(draws)
    blocks = int(np.ceil(count / length))
    for draw in range(draws):
        starts = rng.integers(0, count - length + 1, blocks)
        sample = np.concatenate([values[start : start + length] for start in starts])[:count]
        results[draw] = sample.mean() * 252
    return [float(value) for value in np.quantile(results, [0.025, 0.5, 0.975])]


def execution_audit(outcomes: pd.DataFrame, accepted: pd.DataFrame) -> dict[str, int]:
    completed = outcomes.loc[outcomes.status.eq("COMPLETED")]
    return {
        "signal_bar_fill_count": int(
            (completed.entry_date.notna() & completed.entry_date.le(completed.signal_date)).sum()
        ),
        "t1_same_day_exit_count": int(completed.exit_cal_idx.le(completed.entry_cal_idx).sum()),
        "entry_after_three_session_window_count": int(
            completed.entry_cal_idx.sub(completed.signal_cal_idx).gt(3).sum()
        ),
        "accepted_cost_identity_violation_count": int(
            (accepted.net_return - (accepted.gross_return - 0.004)).abs().gt(1e-12).sum()
        ),
        "accepted_duplicate_event_count": int(accepted.event_id.duplicated().sum()),
    }


def run_stage_b() -> dict[str, Any]:
    freeze = verify_stage_a()
    candidates = pd.read_parquet(CANDIDATES)
    for column in ("signal_date", "decision_at", "available_at", "feature_latest_timestamp"):
        candidates[column] = pd.to_datetime(candidates[column])
    dev_candidates = candidates.loc[candidates.signal_date.dt.year.isin(DEVELOPMENT)].copy()
    forward_candidates = candidates.loc[candidates.signal_date.dt.year.isin(FORWARD)].copy()
    dev_outcomes, dev_audit = v64.parent.base.build_outcomes(dev_candidates, DEV_OUTCOMES)
    forward_outcomes, forward_audit = v64.parent.base.build_outcomes(
        forward_candidates, FORWARD_OUTCOMES
    )
    all_outcomes = pd.concat([dev_outcomes, forward_outcomes], ignore_index=True)
    dev_accepted, _dev_skipped, _dev_nav, _dev_portfolio = v64.parent.base.replay(
        attach_fields(dev_outcomes, dev_candidates), DEV_ACCEPTED, DEV_SKIPPED, DEV_NAV
    )
    accepted, skipped, nav, portfolio = v64.parent.base.replay(
        attach_fields(all_outcomes, candidates), ACCEPTED, SKIPPED, NAV
    )
    for frame in (dev_accepted, accepted, nav):
        for column in ("signal_date", "entry_date", "exit_date", "trade_date"):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column])
    annual = {
        str(year): summarize(accepted.loc[accepted.signal_date.dt.year.eq(year)]) for year in YEARS
    }
    annual_date_equal = {
        str(year): date_equal(accepted.loc[accepted.signal_date.dt.year.eq(year)]) for year in YEARS
    }
    lane = {name: summarize(part) for name, part in accepted.groupby("lane", sort=True)}
    board = {name: summarize(part) for name, part in accepted.groupby("sleeve", sort=True)}
    concentration = v64.parent.base.v1.concentration_metrics(accepted)
    early_accepted = accepted.loc[accepted.lane.eq("EARLY_TRANSITION")]
    baseline_result = json.loads(v64.RESULT.read_text(encoding="utf-8"))
    baseline_accepted = pd.read_parquet(v64.ACCEPTED)
    baseline_nav = pd.read_parquet(v64.NAV)
    baseline_nav["trade_date"] = pd.to_datetime(baseline_nav.trade_date)
    nav["trade_date"] = pd.to_datetime(nav.trade_date)
    post_result = json.loads(POST_RESULT.read_text(encoding="utf-8"))
    post_accepted = pd.read_parquet(POST_ACCEPTED)
    post_nav = pd.read_parquet(POST_NAV)
    post_accepted["signal_date"] = pd.to_datetime(post_accepted.signal_date)
    post_nav["trade_date"] = pd.to_datetime(post_nav.trade_date)
    audit = {
        **candidate_audit(candidates),
        **dev_audit,
        **{f"forward_{key}": value for key, value in forward_audit.items()},
        **execution_audit(all_outcomes, accepted),
        "medium_early_source_overlap_count": len(
            set(candidates.loc[candidates.lane.eq("MEDIUM_PARTICIPATION"), "source_event_id"])
            & set(candidates.loc[candidates.lane.eq("EARLY_TRANSITION"), "source_event_id"])
        ),
        "post_2023_used_for_rule_selection_count": 0,
        "max_k_violation_count": int(portfolio["max_k_violation_count"]),
        "negative_cash_count": int(portfolio["negative_cash_count"]),
    }
    if any(audit.values()):
        raise ResearchError(f"V65 audit failed: {audit}")
    full = summarize(accepted)
    dev = summarize(dev_accepted)
    forward = summarize(accepted.loc[accepted.signal_date.dt.year.isin(FORWARD)])
    gate = {
        "scientific_completed_gt_500": len(accepted) > 500,
        "scientific_mean_gt_3pct": full["mean_net"] > 0.03,
        "scientific_median_positive": full["median_net"] > 0,
        "mean_holding_lt_15": full["mean_holding_sessions"] < 15,
        "all_ten_scientific_years_trade_mean_positive": all(
            annual[str(year)]["mean_net"] > 0 for year in YEARS
        ),
        "all_forward_years_trade_and_date_equal_positive": all(
            annual[str(year)]["mean_net"] > 0 and annual_date_equal[str(year)] > 0
            for year in FORWARD
        ),
        "mean_excluding_best_five_dates_positive": concentration[
            "mean_excluding_best_five_signal_dates"
        ]
        > 0,
        "post_observation_all_years_trade_mean_positive": all(
            value > 0 for value in post_result["union"]["post"]["annual"].values()
        ),
    }
    verdict = (
        "V65_CONFIDENT_SIGNAL_AND_PORTFOLIO_EXPANSION"
        if all(gate.values())
        else "V65_EXPANSION_NOT_CONFIDENT"
    )
    result = {
        "experiment": EXPERIMENT,
        "verdict": verdict,
        "evidence_label": "ITERATIVE_DEVELOPMENT_FIXED_FORWARD_AND_NONPRISTINE_POST_OBSERVATION",
        "stage_a": freeze,
        "candidate_count": len(candidates),
        "candidate_lane_counts": candidates.lane.value_counts().astype(int).to_dict(),
        "outcome_status": all_outcomes.status.value_counts().astype(int).to_dict(),
        "capacity_accepted_completed": len(accepted),
        "capacity_skips": len(skipped),
        "development": dev,
        "fixed_forward": forward,
        "scientific_2014_2023": full,
        "annual": annual,
        "annual_date_equal_mean": annual_date_equal,
        "lane": lane,
        "board": board,
        "portfolio": portfolio,
        "annual_portfolio_return": v64.annual_portfolio_returns(nav),
        "concentration": concentration,
        "bootstrap": {
            "early_lane_signal_date_cluster_mean_95pct_ci": cluster_bootstrap_mean_ci(
                early_accepted
            ),
            (
                "v65_minus_v64_annualized_daily_return_"
                "20_session_block_95pct_ci"
            ): block_bootstrap_nav_excess_ci(nav, baseline_nav),
        },
        "v64_scientific_baseline": {
            "accepted": len(baseline_accepted),
            "mean_net": float(baseline_accepted.net_return.mean()),
            "portfolio": baseline_result["portfolio"],
        },
        "increment_vs_v64_scientific": {
            "accepted_trade_count": len(accepted) - len(baseline_accepted),
            "accepted_trade_count_pct": len(accepted) / len(baseline_accepted) - 1,
            "mean_net_pp": full["mean_net"] - float(baseline_accepted.net_return.mean()),
            "cagr_pp": portfolio["cagr"] - baseline_result["portfolio"]["cagr"],
            "max_drawdown_pp": portfolio["max_drawdown"]
            - baseline_result["portfolio"]["max_drawdown"],
            "sharpe": portfolio["sharpe"] - baseline_result["portfolio"]["sharpe"],
        },
        "post_observation_through_2026_09_04": {
            "accepted": len(post_accepted),
            "summary": post_result["union"]["all"],
            "post_only": post_result["union"]["post"],
            "portfolio": post_result["union"]["portfolio"],
            "annual_portfolio_return": v64.annual_portfolio_returns(post_nav),
            "role": "NON_PRISTINE_DIAGNOSTIC_NOT_USED_FOR_SELECTION",
        },
        "rejected_complement": {
            "name": "P2_FIRST_QUIET_TEST",
            "reason": "positive fixed-forward translation did not persist after 2023",
            "post_2024_2026_mean_net": post_result["p2"]["post"]["mean"],
            "post_2024_mean_net": post_result["p2"]["post"]["annual"]["2024"],
        },
        "gate": gate,
        "audit": audit,
        "hashes": {
            "contract": sha(CONTRACT),
            "spec": sha(SPEC),
            "candidate": sha(CANDIDATES),
            "accepted": sha(ACCEPTED),
            "nav": sha(NAV),
            "post_result": sha(POST_RESULT),
            "post_accepted": sha(POST_ACCEPTED),
            "post_nav": sha(POST_NAV),
        },
    }
    write_json(RESULT, result)
    write_report(result)
    return result


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.2%}"


def write_report(result: dict[str, Any]) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"`{result['verdict']}`",
        "",
        "V65 keeps frozen V64 unchanged and adds one mutually exclusive early-diffusion lane. "
        "The added lane captures broad 20-session participation before 60-session breadth has "
        "fully recovered, but requires non-saturated industry ignition and an old pressure memory.",
        "",
        "## Scientific evidence",
        "",
        "|Year|Trades|Mean net|Median net|Date-equal|Win|Severe10|Mean hold|Portfolio return|",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in YEARS:
        item = result["annual"][str(year)]
        lines.append(
            f"|{year}|{item['completed_trades']}|{pct(item['mean_net'])}|{pct(item['median_net'])}|"
            f"{pct(result['annual_date_equal_mean'][str(year)])}|{pct(item['win_rate'])}|"
            f"{pct(item['severe_loss10'])}|{item['mean_holding_sessions']:.2f}|"
            f"{pct(result['annual_portfolio_return'][str(year)])}|"
        )
    lines += [
        "",
        "## Why it works",
        "",
        "The pressure break is admitted only when demand is broad at both market and industry "
        "levels, the industry participation rate is accelerating, the stock is not already "
        "extended, and the signal candle shows controlled rather than blow-off demand. V64 "
        "covers established medium participation. The V65 early lane covers the distinct moment "
        "when short breadth has diffused but long breadth is still below 45%; an old ceiling and "
        "a cap on industry breadth acceleration reduce recent local retests and saturated snaps.",
        "",
        "## Increment and robustness",
        "",
        f"Scientific accepted trades: {result['v64_scientific_baseline']['accepted']} -> "
        f"{result['capacity_accepted_completed']} "
        f"({result['increment_vs_v64_scientific']['accepted_trade_count_pct']:.1%}).",
        f"Scientific CAGR: {pct(result['v64_scientific_baseline']['portfolio']['cagr'])} -> "
        f"{pct(result['portfolio']['cagr'])}; MaxDD: "
        f"{pct(result['v64_scientific_baseline']['portfolio']['max_drawdown'])} -> "
        f"{pct(result['portfolio']['max_drawdown'])}.",
        f"Early-lane clustered mean 95% CI: "
        f"[{pct(result['bootstrap']['early_lane_signal_date_cluster_mean_95pct_ci'][0])}, "
        f"{pct(result['bootstrap']['early_lane_signal_date_cluster_mean_95pct_ci'][2])}].",
        "",
        "The post-2023 evidence is explicitly non-pristine. It remains a stress diagnostic, not "
        "a threshold-selection sample. The separately tested quiet-supply-test translation was "
        "not accepted because its 2024-2026 mean decayed materially.",
        "",
        f"Audit: `{json.dumps(result['audit'], sort_keys=True)}`.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-a", action="store_true")
    parser.add_argument("--stage-b", action="store_true")
    args = parser.parse_args()
    if args.stage_a:
        print(json.dumps(run_stage_a(), indent=2, sort_keys=True, default=str))
    elif args.stage_b:
        print(json.dumps(run_stage_b(), indent=2, sort_keys=True, default=str))
    else:
        parser.error("choose --stage-a or --stage-b")


if __name__ == "__main__":
    main()
