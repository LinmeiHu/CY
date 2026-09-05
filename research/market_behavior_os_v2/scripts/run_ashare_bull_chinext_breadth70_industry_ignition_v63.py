#!/usr/bin/env python3
"""ChiNext price discovery after broad-market and PIT-industry breadth ignition."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import run_ashare_bull_industry_ignition_first_pressure_break_v62 as base


ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-CHINEXT-BREADTH70-INDUSTRY-IGNITION-V63"
SOURCE_EXPERIMENT = "ASHARE-BULL-INDUSTRY-BREADTH-IGNITION-FIRST-BREAKOUT-V53"
EXT = Path("/Volumes/quant/CY_quant_research/bull_chinext_breadth70_industry_ignition_v63")
SOURCE_CANDIDATES = Path(
    "/Volumes/quant/CY_quant_research/bull_industry_breadth_ignition_first_breakout_v53/"
    "stage_a/candidates.parquet"
)
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
CHRONOLOGY_FREEZE = OS / f"artifacts/{EXPERIMENT}_chronology_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
CANDIDATES = EXT / "stage_a/candidates.parquet"
BLIND_INDEX = EXT / "stage_a/blind_index.csv"
BLIND_DIR = EXT / "stage_a/blind_charts"
DEV_OUTCOMES = EXT / "stage_b/development_outcomes.parquet"
FORWARD_OUTCOMES = EXT / "stage_b/robustness_outcomes.parquet"
DEV_ACCEPTED = EXT / "stage_b/development_accepted.parquet"
DEV_SKIPPED = EXT / "stage_b/development_skipped.parquet"
DEV_NAV = EXT / "stage_b/development_nav.parquet"
ACCEPTED = EXT / "stage_b/combined_accepted.parquet"
SKIPPED = EXT / "stage_b/combined_skipped.parquet"
NAV = EXT / "stage_b/combined_nav.parquet"

PROFILE = "T15_H15_NO_STOP"
YEARS = tuple(range(2014, 2024))
DEVELOPMENT_YEARS = tuple(range(2014, 2021))
ROBUSTNESS_YEARS = (2021, 2022, 2023)
SOURCE_CANDIDATE_SHA256 = "b0dd2daed6cbcc5ff6cad2f7d8caead5fd9b7f4fbaaff349a0dfdd4d0f2530f4"


class ResearchError(RuntimeError):
    """Fail closed on V63 identity, chronology, or execution drift."""


def sha(path: Path) -> str:
    return base.sha(path)


def write_json(path: Path, payload: Any) -> None:
    base.write_json(path, payload)


def source_contract_mask(frame: pd.DataFrame) -> pd.Series:
    return base.source_contract_mask(frame)


def v63_contract_mask(frame: pd.DataFrame) -> pd.Series:
    """Frozen V63 additions to the already-certified V53 source contract."""
    return (
        frame.market_breadth20.ge(0.70)
        & frame.sleeve.eq("CHINEXT")
        & frame.step_return.le(0.06)
        & frame.turnover_ratio.ge(1.50)
    )


def select_candidates() -> pd.DataFrame:
    if sha(SOURCE_CANDIDATES) != SOURCE_CANDIDATE_SHA256:
        raise ResearchError("V53 source candidate drift")
    source = base.v1.read_parquet_duckdb(SOURCE_CANDIDATES)
    for column in (
        "trade_date",
        "signal_date",
        "available_at",
        "decision_at",
        "feature_latest_timestamp",
    ):
        source[column] = pd.to_datetime(source[column])
    if not source_contract_mask(source).all():
        raise ResearchError("V53 source rows violate the frozen source contract")
    mask = v63_contract_mask(source)
    out = source.loc[mask].copy()
    out["source_event_id"] = out.event_id.astype(str)
    out["event_id"] = "V63|" + out.source_event_id
    out["admission_lane"] = "CHINEXT_BREADTH70_INDUSTRY_IGNITION"
    # The shared portfolio engine sorts these fields in descending order.
    out["industry_positive_ret20_share"] = out.industry_breadth20_delta5
    out["stock_minus_industry_ret20"] = -out.ret60
    out["turnover_expansion"] = out.turnover_ratio
    out = out.sort_values(["signal_date", "event_id"], kind="mergesort").reset_index(drop=True)
    if out.event_id.duplicated().any():
        raise ResearchError("duplicate V63 event identity")
    if not source_contract_mask(out).all() or not v63_contract_mask(out).all():
        raise ResearchError("selected row violates the frozen V53/V63 contract")
    if out.available_at.gt(out.decision_at).any():
        raise ResearchError("post-decision V63 availability")
    if out.feature_latest_timestamp.gt(out.decision_at).any():
        raise ResearchError("post-decision V63 feature")
    if out.signal_date.gt(pd.Timestamp("2023-12-31")).any():
        raise ResearchError("post-2023 V63 signal")
    return out


def choose_blind_sample(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["year"] = work.signal_date.dt.year
    work["blind_order"] = work.event_id.map(
        lambda value: hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    )
    sample = (
        work.sort_values(["year", "blind_order"], kind="mergesort")
        .groupby("year", sort=True, group_keys=False)
        .head(3)
        .sort_values(["year", "blind_order"], kind="mergesort")
        .head(30)
        .copy()
    )
    sample.insert(0, "chart_id", [f"V63-BLIND-{i:03d}" for i in range(1, len(sample) + 1)])
    return sample


def build_blind_charts(sample: pd.DataFrame) -> None:
    BLIND_DIR.mkdir(parents=True, exist_ok=True)
    for event in sample.itertuples(index=False):
        history = base.chart_history(event)
        if history.empty or pd.Timestamp(history.trade_date.max()) > pd.Timestamp(event.signal_date):
            raise ResearchError(f"blind history violation {event.chart_id}")
        fig, axes = plt.subplots(
            3,
            1,
            figsize=(14, 9),
            sharex=True,
            gridspec_kw={"height_ratios": [4, 1, 1.5]},
        )
        base.plot_candles(axes[0], history)
        axes[0].axvline(event.signal_date, color="#dc2626", linestyle="--", linewidth=1.4)
        axes[0].axhline(
            float(event.prior20_high),
            color="#2563eb",
            linestyle=":",
            linewidth=1.2,
            label="prior-20 pressure",
        )
        axes[0].set_title(
            f"{event.chart_id} | {event.symbol} | CHINEXT | {event.causal_industry}"
        )
        axes[0].legend(loc="upper left")
        dates = pd.to_datetime(history.trade_date)
        colors = np.where(history.coord_close.ge(history.coord_open), "#e53935", "#009b72")
        axes[1].bar(dates, history.turnover_fraction, color=colors, width=0.8)
        axes[1].set_ylabel("turnover")
        axes[2].plot(dates, history.market20, label="market ret20", color="#111827")
        axes[2].plot(dates, history.industry20, label="industry ret20", color="#7c3aed")
        axes[2].plot(
            dates,
            history.market_breadth20 - 0.5,
            label="market breadth20 - 50%",
            color="#2563eb",
        )
        axes[2].plot(
            dates,
            history.industry_breadth20 - 0.5,
            label="industry breadth20 - 50%",
            color="#f59e0b",
        )
        axes[2].axhline(0, color="black", linewidth=0.7)
        axes[2].legend(loc="upper left", ncol=2)
        axes[2].xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        fig.text(
            0.01,
            0.01,
            "Signal-only chart; no post-signal bar. "
            f"market breadth={event.market_breadth20:.1%}; "
            f"industry breadth={event.industry_breadth20:.1%}; "
            f"industry breadth +5d={event.industry_breadth20_delta5:.1%}; "
            f"signal={event.step_return:.1%}; turnover={event.turnover_ratio:.2f}x.",
            fontsize=9,
        )
        fig.tight_layout(rect=(0, 0.03, 1, 1))
        fig.savefig(BLIND_DIR / f"{event.chart_id}.png", dpi=130)
        plt.close(fig)


def write_spec() -> None:
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "stage": "ITERATIVE_2014_2023_RULE_FREEZE",
            "contract_sha256": sha(CONTRACT),
            "runner_sha256": sha(Path(__file__)),
            "source_experiment": SOURCE_EXPERIMENT,
            "source_candidate_sha256": sha(SOURCE_CANDIDATES),
            "execution_engine_sha256": sha(Path(base.v2.__file__)),
            "portfolio_engine_sha256": sha(Path(base.v1.__file__)),
            "profile": PROFILE,
            "repository_2024_plus_signal_or_feature_opened": False,
        },
    )


def run_stage_a() -> dict[str, Any]:
    write_spec()
    candidates = select_candidates()
    base.v1.write_parquet(candidates, CANDIDATES)
    sample = choose_blind_sample(candidates)
    BLIND_INDEX.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(BLIND_INDEX, index=False)
    build_blind_charts(sample)
    annual = candidates.groupby(candidates.signal_date.dt.year).size().astype(int).to_dict()
    required = [
        "symbol",
        "sleeve",
        "causal_industry",
        "hard_valid",
        "available_at",
        "decision_at",
        "feature_latest_timestamp",
        "market20",
        "market_breadth20",
        "industry20",
        "industry_breadth20",
        "industry20_delta5",
        "industry_breadth20_delta5",
        "ret60",
        "prior20_high",
        "prior20_limitups",
        "step_return",
        "close_location",
        "turnover_ratio",
    ]
    expected_decision_at = candidates.signal_date.dt.normalize() + pd.Timedelta(hours=15)
    freeze = {
        "experiment": EXPERIMENT,
        "contract_sha256": sha(CONTRACT),
        "spec_sha256": sha(SPEC),
        "runner_sha256": sha(Path(__file__)),
        "source_candidate_sha256": sha(SOURCE_CANDIDATES),
        "candidate_sha256": sha(CANDIDATES),
        "blind_index_sha256": sha(BLIND_INDEX),
        "candidate_count": int(len(candidates)),
        "annual_candidate_counts": {str(k): int(v) for k, v in annual.items()},
        "blind_chart_count": int(len(sample)),
        "audit": {
            "duplicate_event_count": int(candidates.event_id.duplicated().sum()),
            "feature_after_decision_count": int(
                candidates.feature_latest_timestamp.gt(candidates.decision_at).sum()
            ),
            "availability_after_decision_count": int(
                candidates.available_at.gt(candidates.decision_at).sum()
            ),
            "decision_not_signal_close_count": int(
                candidates.decision_at.ne(expected_decision_at).sum()
            ),
            "trade_date_signal_date_mismatch_count": int(
                candidates.trade_date.dt.normalize().ne(candidates.signal_date.dt.normalize()).sum()
            ),
            "required_feature_null_row_count": int(candidates[required].isna().any(axis=1).sum()),
            "hard_valid_false_count": int(candidates.hard_valid.ne(True).sum()),
            "source_contract_violation_count": int((~source_contract_mask(candidates)).sum()),
            "v63_contract_violation_count": int((~v63_contract_mask(candidates)).sum()),
            "non_chinext_count": int(candidates.sleeve.ne("CHINEXT").sum()),
            "post_2023_signal_count": int(
                candidates.signal_date.gt(pd.Timestamp("2023-12-31")).sum()
            ),
            "blind_chart_post_signal_bar_count": 0,
        },
    }
    if any(freeze["audit"].values()):
        raise ResearchError(str(freeze["audit"]))
    write_json(FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    expected = {
        "contract_sha256": sha(CONTRACT),
        "spec_sha256": sha(SPEC),
        "runner_sha256": sha(Path(__file__)),
        "source_candidate_sha256": sha(SOURCE_CANDIDATES),
        "candidate_sha256": sha(CANDIDATES),
        "blind_index_sha256": sha(BLIND_INDEX),
    }
    drift = {key: [freeze.get(key), value] for key, value in expected.items() if freeze.get(key) != value}
    if drift:
        raise ResearchError(f"Stage-A drift {drift}")
    return freeze


def attach_rank_fields(outcomes: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "event_id",
        "industry_positive_ret20_share",
        "stock_minus_industry_ret20",
        "turnover_expansion",
    ]
    return outcomes.merge(candidates[fields], on="event_id", how="left", validate="many_to_one")


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    return base.summary(frame)


def run_stage_b() -> dict[str, Any]:
    stage_a = verify_stage_a()
    candidates = base.v1.read_parquet_duckdb(CANDIDATES)
    for column in ("signal_date", "decision_at", "feature_latest_timestamp"):
        candidates[column] = pd.to_datetime(candidates[column])
    dev_candidates = candidates.loc[candidates.signal_date.dt.year.isin(DEVELOPMENT_YEARS)].copy()
    dev_outcomes, dev_audit = base.build_outcomes(dev_candidates, DEV_OUTCOMES)
    dev_accepted, dev_skipped, _dev_nav, dev_portfolio = base.replay(
        attach_rank_fields(dev_outcomes, dev_candidates), DEV_ACCEPTED, DEV_SKIPPED, DEV_NAV
    )
    for column in ("signal_date", "entry_date", "exit_date"):
        dev_accepted[column] = pd.to_datetime(dev_accepted[column])
    dev_full = summarize(dev_accepted)
    dev_annual = {
        str(year): summarize(dev_accepted.loc[dev_accepted.signal_date.dt.year.eq(year)])
        for year in DEVELOPMENT_YEARS
    }
    dev_concentration = base.v1.concentration_metrics(dev_accepted)
    dev_gate = {
        "accepted_completed_at_least_400": len(dev_accepted) >= 400,
        "mean_net_gt_3pct": dev_full["mean_net"] is not None and dev_full["mean_net"] > 0.03,
        "mean_holding_lt_15": dev_full["mean_holding_sessions"] is not None
        and dev_full["mean_holding_sessions"] < 15,
        "at_least_6_positive_years": sum(
            item["mean_net"] is not None and item["mean_net"] > 0
            for item in dev_annual.values()
        )
        >= 6,
        "mean_excluding_best5_dates_positive": dev_concentration[
            "mean_excluding_best_five_signal_dates"
        ]
        > 0,
    }
    if not all(dev_gate.values()):
        result = {
            "experiment": EXPERIMENT,
            "verdict": "BULL_CHINEXT_BREADTH70_INDUSTRY_IGNITION_DEVELOPMENT_FAILED",
            "stage_a": stage_a,
            "development": dev_full,
            "development_annual": dev_annual,
            "development_portfolio": dev_portfolio,
            "development_concentration": dev_concentration,
            "development_gate": dev_gate,
            "development_capacity_skips": int(len(dev_skipped)),
            "audit": dev_audit,
            "robustness_years_opened": False,
        }
        write_json(RESULT, result)
        return result
    write_json(
        CHRONOLOGY_FREEZE,
        {
            "experiment": EXPERIMENT,
            "profile": PROFILE,
            "contract_sha256": sha(CONTRACT),
            "candidate_sha256": sha(CANDIDATES),
            "development_outcomes_sha256": sha(DEV_OUTCOMES),
            "development_accepted_sha256": sha(DEV_ACCEPTED),
            "development_gate": dev_gate,
            "robustness_years_are_observed_not_pristine_validation": True,
        },
    )
    robustness_candidates = candidates.loc[
        candidates.signal_date.dt.year.isin(ROBUSTNESS_YEARS)
    ].copy()
    robustness_outcomes, robustness_audit = base.build_outcomes(
        robustness_candidates, FORWARD_OUTCOMES
    )
    all_outcomes = pd.concat([dev_outcomes, robustness_outcomes], ignore_index=True)
    accepted, skipped, _nav, portfolio = base.replay(
        attach_rank_fields(all_outcomes, candidates), ACCEPTED, SKIPPED, NAV
    )
    for column in ("signal_date", "entry_date", "exit_date"):
        accepted[column] = pd.to_datetime(accepted[column])
    full = summarize(accepted)
    annual = {
        str(year): summarize(accepted.loc[accepted.signal_date.dt.year.eq(year)])
        for year in YEARS
    }
    board = {name: summarize(part) for name, part in accepted.groupby("sleeve", sort=True)}
    concentration = base.v1.concentration_metrics(accepted)
    gate = {
        "capacity_accepted_completed_gt_500": len(accepted) > 500,
        "mean_net_gt_3pct": full["mean_net"] is not None and full["mean_net"] > 0.03,
        "mean_holding_lt_15": full["mean_holding_sessions"] is not None
        and full["mean_holding_sessions"] < 15,
        "2021_2023_each_positive": all(
            annual[str(year)]["mean_net"] is not None and annual[str(year)]["mean_net"] > 0
            for year in ROBUSTNESS_YEARS
        ),
        "mean_excluding_best5_dates_positive": concentration[
            "mean_excluding_best_five_signal_dates"
        ]
        > 0,
        "top5_date_positive_pnl_share_le_25pct": concentration[
            "top_five_signal_date_positive_pnl_share"
        ]
        <= 0.25,
    }
    audit = {
        **dev_audit,
        **{f"robustness_{key}": value for key, value in robustness_audit.items()},
        "feature_after_decision_count": int(
            candidates.feature_latest_timestamp.gt(candidates.decision_at).sum()
        ),
        "availability_after_decision_count": int(
            candidates.available_at.gt(candidates.decision_at).sum()
        ),
        "source_contract_violation_count": int((~source_contract_mask(candidates)).sum()),
        "v63_contract_violation_count": int((~v63_contract_mask(candidates)).sum()),
        "non_chinext_count": int(candidates.sleeve.ne("CHINEXT").sum()),
        "post_2023_signal_or_feature_count": int(
            candidates.signal_date.gt(pd.Timestamp("2023-12-31")).sum()
        ),
        "negative_cash_count": int(portfolio["negative_cash_count"]),
        "max_k_violation_count": int(portfolio["max_k_violation_count"]),
    }
    if any(audit.values()):
        raise ResearchError(str(audit))
    verdict = (
        "BULL_CHINEXT_BREADTH70_INDUSTRY_IGNITION_TARGET_MET"
        if all(gate.values())
        else "BULL_CHINEXT_BREADTH70_INDUSTRY_IGNITION_TARGET_FAILED"
    )
    result = {
        "experiment": EXPERIMENT,
        "verdict": verdict,
        "profile": PROFILE,
        "candidate_count": int(len(candidates)),
        "capacity_accepted_completed_trades": int(len(accepted)),
        "capacity_skips": int(len(skipped)),
        "average_trades_per_year": float(len(accepted) / 10),
        "full": full,
        "annual": annual,
        "board": board,
        "portfolio": portfolio,
        "concentration": concentration,
        "development": dev_full,
        "development_annual": dev_annual,
        "development_gate": dev_gate,
        "gate": gate,
        "audit": audit,
        "evidence_label": "ITERATIVE_2014_2023_RESEARCH_NOT_PRISTINE_VALIDATION",
        "hashes": {
            "chronology_freeze": sha(CHRONOLOGY_FREEZE),
            "accepted": sha(ACCEPTED),
            "nav": sha(NAV),
        },
    }
    write_json(RESULT, result)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"`{verdict}`",
        "",
        "Evidence label: `ITERATIVE_2014_2023_RESEARCH_NOT_PRISTINE_VALIDATION`.",
        "",
        "|Year|Trades|Mean net|Median net|Win|Severe10|Mean hold|",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in YEARS:
        item = annual[str(year)]
        lines.append(
            f"|{year}|{item['completed_trades']}|{base.v1.pct(item['mean_net'])}|"
            f"{base.v1.pct(item['median_net'])}|{base.v1.pct(item['win_rate'])}|"
            f"{base.v1.pct(item['severe_loss10'])}|"
            f"{item['mean_holding_sessions'] if item['mean_holding_sessions'] is not None else '—'}|"
        )
    lines += [
        "",
        f"Gate: `{json.dumps(gate, sort_keys=True)}`.",
        "",
        "The rule is independent of collapse-gap repair. It uses a breadth-70 market risk-appetite state, a PIT industry breadth ignition, and a controlled first 20-session pressure break in ChiNext.",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    return result


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
