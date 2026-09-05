#!/usr/bin/env python3
"""PIT industry-ignition bull strategy with a first 20-session pressure break."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import run_ashare_bull_leader_pullback_reacceleration_v2 as v2
import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-INDUSTRY-IGNITION-FIRST-PRESSURE-BREAK-V62"
SOURCE_EXPERIMENT = "ASHARE-BULL-INDUSTRY-BREADTH-IGNITION-FIRST-BREAKOUT-V53"
EXT = Path("/Volumes/quant/CY_quant_research/bull_industry_ignition_first_pressure_break_v62")
SOURCE_CANDIDATES = Path(
    "/Volumes/quant/CY_quant_research/bull_industry_breadth_ignition_first_breakout_v53/"
    "stage_a/candidates.parquet"
)
FEATURE_PANEL = Path(
    "/Volumes/quant/CY_quant_research/bull_industry_pullback_reacceleration_v44/"
    "stage_a/causal_feature_panel.parquet"
)
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
FORWARD_FREEZE = OS / f"artifacts/{EXPERIMENT}_forward_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
CANDIDATES = EXT / "stage_a/candidates.parquet"
BLIND_INDEX = EXT / "stage_a/blind_index.csv"
BLIND_DIR = EXT / "stage_a/blind_charts"
DEV_OUTCOMES = EXT / "stage_b/development_outcomes.parquet"
FORWARD_OUTCOMES = EXT / "stage_b/forward_outcomes.parquet"
DEV_ACCEPTED = EXT / "stage_b/development_accepted.parquet"
DEV_SKIPPED = EXT / "stage_b/development_skipped.parquet"
DEV_NAV = EXT / "stage_b/development_nav.parquet"
ACCEPTED = EXT / "stage_b/combined_accepted.parquet"
SKIPPED = EXT / "stage_b/combined_skipped.parquet"
NAV = EXT / "stage_b/combined_nav.parquet"

PROFILE = "T15_H15_NO_STOP"
YEARS = tuple(range(2014, 2024))
DEVELOPMENT_YEARS = tuple(range(2014, 2021))
FORWARD_YEARS = (2021, 2022, 2023)
SOURCE_CANDIDATE_SHA256 = "b0dd2daed6cbcc5ff6cad2f7d8caead5fd9b7f4fbaaff349a0dfdd4d0f2530f4"


class ResearchError(RuntimeError):
    """Fail closed on V62 identity, chronology, or execution drift."""


def sha(path: Path) -> str:
    return v1.sha256(path)


def write_json(path: Path, payload: Any) -> None:
    v1.write_json(path, payload)


def write_spec() -> None:
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "stage": "OUTCOME_BLIND_CONTRACT",
            "contract_sha256": sha(CONTRACT),
            "runner_sha256": sha(Path(__file__)),
            "source_experiment": SOURCE_EXPERIMENT,
            "source_candidate_sha256": sha(SOURCE_CANDIDATES),
            "feature_panel_sha256": sha(FEATURE_PANEL),
            "execution_engine_sha256": sha(Path(v2.__file__)),
            "portfolio_engine_sha256": sha(Path(v1.__file__)),
            "profile": PROFILE,
            "forward_outcomes_opened": False,
        },
    )


def source_contract_mask(frame: pd.DataFrame) -> pd.Series:
    return (
        frame.market20.gt(-0.03)
        & frame.market_breadth20.gt(0.40)
        & frame.industry20.gt(0.03)
        & frame.industry_breadth20.gt(0.60)
        & frame.industry20_delta5.ge(0.03)
        & frame.industry_breadth20_delta5.ge(0.15)
        & frame.ret60.between(0.0, 0.30, inclusive="both")
        & frame.prior20_limitups.eq(0)
        & frame.coord_close.gt(frame.prior20_high)
        & frame.step_return.between(0.02, 0.08, inclusive="both")
        & frame.close_location.ge(0.70)
        & frame.turnover_ratio.between(1.20, 4.00, inclusive="both")
    )


def select_candidates() -> pd.DataFrame:
    if sha(SOURCE_CANDIDATES) != SOURCE_CANDIDATE_SHA256:
        raise ResearchError("V53 source candidate drift")
    source = v1.read_parquet_duckdb(SOURCE_CANDIDATES)
    for column in ("trade_date", "signal_date", "available_at", "decision_at", "feature_latest_timestamp"):
        source[column] = pd.to_datetime(source[column])
    if not source_contract_mask(source).all():
        raise ResearchError("V53 source rows violate their frozen outcome-blind contract")
    mask = source.market20.gt(0) & source.market_breadth20.ge(0.70) & source.industry60.gt(0)
    out = source.loc[mask].copy()
    out["source_event_id"] = out.event_id.astype(str)
    out["event_id"] = "V62|" + out.source_event_id
    out["admission_lane"] = "MARKET_DEMAND_FLOOR_X_INDUSTRY_IGNITION"
    out["industry_positive_ret20_share"] = out.industry_breadth20_delta5
    out["stock_minus_industry_ret20"] = out.industry20_delta5
    out["turnover_expansion"] = out.industry_breadth20
    out = out.sort_values(["signal_date", "event_id"], kind="mergesort").reset_index(drop=True)
    if out.event_id.duplicated().any():
        raise ResearchError("duplicate V62 event identity")
    if out.feature_latest_timestamp.gt(out.decision_at).any():
        raise ResearchError("post-decision V62 feature")
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
    sample.insert(0, "chart_id", [f"V62-BLIND-{i:03d}" for i in range(1, len(sample) + 1)])
    return sample


def chart_history(event: Any) -> pd.DataFrame:
    start = pd.Timestamp(event.signal_date) - pd.Timedelta(days=300)
    symbol = str(event.symbol).replace("'", "''")
    query = f"""
        SELECT trade_date, coord_open, coord_high, coord_low, coord_close,
               turnover_fraction, ret20, ret60, market20, market_breadth20,
               industry20, industry_breadth20
        FROM read_parquet('{FEATURE_PANEL.as_posix()}')
        WHERE symbol = '{symbol}'
          AND trade_date >= DATE '{start.date().isoformat()}'
          AND trade_date <= DATE '{pd.Timestamp(event.signal_date).date().isoformat()}'
        ORDER BY trade_date
    """
    history = duckdb.connect().execute(query).fetchdf()
    if not history.empty:
        return history
    fallback = f"""
        SELECT trade_date, coord_open, coord_high, coord_low, coord_close,
               turnover_fraction
        FROM read_parquet('{v1.DAILY.as_posix()}')
        WHERE symbol = '{symbol}'
          AND trade_date >= DATE '{start.date().isoformat()}'
          AND trade_date <= DATE '{pd.Timestamp(event.signal_date).date().isoformat()}'
        ORDER BY trade_date
    """
    history = duckdb.connect().execute(fallback).fetchdf()
    history["ret20"] = history.coord_close / history.coord_close.shift(20) - 1
    history["ret60"] = history.coord_close / history.coord_close.shift(60) - 1
    for column in ("market20", "market_breadth20", "industry20", "industry_breadth20"):
        history[column] = np.nan
    return history


def plot_candles(axis: Any, frame: pd.DataFrame) -> None:
    dates = mdates.date2num(np.array(pd.to_datetime(frame.trade_date).dt.to_pydatetime()))
    for x, row in zip(dates, frame.itertuples(index=False), strict=True):
        up = float(row.coord_close) >= float(row.coord_open)
        color = "#e53935" if up else "#009b72"
        axis.vlines(x, float(row.coord_low), float(row.coord_high), color=color, linewidth=0.7)
        low = min(float(row.coord_open), float(row.coord_close))
        height = max(abs(float(row.coord_close) - float(row.coord_open)), 1e-6)
        axis.add_patch(plt.Rectangle((x - 0.32, low), 0.64, height, color=color, linewidth=0))
    axis.xaxis_date()


def build_blind_charts(sample: pd.DataFrame) -> None:
    BLIND_DIR.mkdir(parents=True, exist_ok=True)
    for event in sample.itertuples(index=False):
        history = chart_history(event)
        if history.empty or pd.Timestamp(history.trade_date.max()) > pd.Timestamp(event.signal_date):
            raise ResearchError(f"blind history violation {event.chart_id}")
        fig, axes = plt.subplots(3, 1, figsize=(14, 9), sharex=True, gridspec_kw={"height_ratios": [4, 1, 1.5]})
        plot_candles(axes[0], history)
        axes[0].axvline(pd.Timestamp(event.signal_date), color="#d62728", linestyle="--", linewidth=1.4)
        axes[0].axhline(float(event.prior20_high), color="#2563eb", linestyle=":", linewidth=1.2, label="prior-20 pressure")
        axes[0].set_title(f"{event.chart_id} | {event.symbol} | {event.sleeve} | {event.causal_industry}")
        axes[0].legend(loc="upper left")
        dates = pd.to_datetime(history.trade_date)
        colors = np.where(history.coord_close.ge(history.coord_open), "#e53935", "#009b72")
        axes[1].bar(dates, history.turnover_fraction, color=colors, width=0.8)
        axes[1].set_ylabel("turnover")
        if history.market20.notna().any():
            axes[2].plot(dates, history.market20, label="market ret20", color="#111827")
            axes[2].plot(dates, history.industry20, label="industry ret20", color="#7c3aed")
            axes[2].plot(dates, history.market_breadth20 - 0.5, label="market breadth20 - 50%", color="#2563eb", alpha=0.8)
            axes[2].plot(dates, history.industry_breadth20 - 0.5, label="industry breadth20 - 50%", color="#f59e0b", alpha=0.8)
        else:
            axes[2].plot(dates, history.ret20, label="stock ret20", color="#b45309")
            axes[2].plot(dates, history.ret60, label="stock ret60", color="#7c3aed")
        axes[2].axhline(0, color="black", linewidth=0.7)
        axes[2].legend(loc="upper left", ncol=2)
        fig.text(
            0.01,
            0.01,
            "Outcome-blind; no post-signal bar. "
            f"market breadth={event.market_breadth20:.1%}; industry breadth={event.industry_breadth20:.1%}; "
            f"industry breadth +5d={event.industry_breadth20_delta5:.1%}; signal={event.step_return:.1%}.",
            fontsize=9,
        )
        fig.tight_layout(rect=(0, 0.03, 1, 1))
        fig.savefig(BLIND_DIR / f"{event.chart_id}.png", dpi=130)
        plt.close(fig)


def run_stage_a() -> dict[str, Any]:
    write_spec()
    candidates = select_candidates()
    v1.write_parquet(candidates, CANDIDATES)
    sample = choose_blind_sample(candidates)
    BLIND_INDEX.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(BLIND_INDEX, index=False)
    build_blind_charts(sample)
    annual = candidates.groupby(candidates.signal_date.dt.year).size().astype(int).to_dict()
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
            "feature_after_decision_count": int(candidates.feature_latest_timestamp.gt(candidates.decision_at).sum()),
            "post_2023_signal_count": int(candidates.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
            "outcomes_opened": False,
            "blind_chart_post_signal_bar_count": 0,
        },
    }
    write_json(FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text())
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


def build_outcomes(frame: pd.DataFrame, output: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    old_profiles, old_outcomes = v2.PROFILES, v2.OUTCOMES
    try:
        v2.PROFILES = {PROFILE: {"horizon": 15, "target": 0.15}}
        v2.OUTCOMES = output
        return v2.build_outcomes(frame)
    finally:
        v2.PROFILES, v2.OUTCOMES = old_profiles, old_outcomes


def replay(trades: pd.DataFrame, accepted_path: Path, skipped_path: Path, nav_path: Path):
    daily = v1.load_trade_daily(trades.loc[trades.status.eq("COMPLETED"), "symbol"].astype(str).unique().tolist())
    old_paths = v1.ACCEPTED, v1.SKIPPED, v1.NAV
    try:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = accepted_path, skipped_path, nav_path
        return v1.replay_portfolio(trades, daily)
    finally:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = old_paths


def summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"completed_trades": 0, "mean_net": None, "median_net": None, "win_rate": None,
                "target_hit_rate": None, "severe_loss10": None, "mean_holding_sessions": None}
    return {
        "completed_trades": int(len(frame)),
        "mean_net": float(frame.net_return.mean()),
        "median_net": float(frame.net_return.median()),
        "win_rate": float(frame.net_return.gt(0).mean()),
        "target_hit_rate": float(frame.exit_reason.eq("TARGET_15").mean()),
        "severe_loss10": float(frame.net_return.le(-0.10).mean()),
        "mean_holding_sessions": float(frame.holding_sessions.mean()),
    }


def attach_rank_fields(outcomes: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    fields = ["event_id", "industry_positive_ret20_share", "stock_minus_industry_ret20", "turnover_expansion"]
    return outcomes.merge(candidates[fields], on="event_id", how="left", validate="many_to_one")


def run_stage_b() -> dict[str, Any]:
    stage_a = verify_stage_a()
    candidates = v1.read_parquet_duckdb(CANDIDATES)
    for column in ("signal_date", "decision_at", "feature_latest_timestamp"):
        candidates[column] = pd.to_datetime(candidates[column])
    dev_candidates = candidates.loc[candidates.signal_date.dt.year.isin(DEVELOPMENT_YEARS)].copy()
    dev_outcomes, dev_audit = build_outcomes(dev_candidates, DEV_OUTCOMES)
    dev_accepted, dev_skipped, _dev_nav, dev_portfolio = replay(
        attach_rank_fields(dev_outcomes, dev_candidates), DEV_ACCEPTED, DEV_SKIPPED, DEV_NAV
    )
    for column in ("signal_date", "entry_date", "exit_date"):
        dev_accepted[column] = pd.to_datetime(dev_accepted[column])
    dev_full = summary(dev_accepted)
    dev_annual = {str(year): summary(dev_accepted.loc[dev_accepted.signal_date.dt.year.eq(year)]) for year in DEVELOPMENT_YEARS}
    dev_concentration = v1.concentration_metrics(dev_accepted)
    dev_gate = {
        "accepted_completed_at_least_800": len(dev_accepted) >= 800,
        "mean_net_gt_3pct": dev_full["mean_net"] is not None and dev_full["mean_net"] > 0.03,
        "mean_holding_lt_15": dev_full["mean_holding_sessions"] is not None and dev_full["mean_holding_sessions"] < 15,
        "at_least_6_positive_years": sum(
            item["mean_net"] is not None and item["mean_net"] > 0 for item in dev_annual.values()
        ) >= 6,
        "mean_excluding_best5_dates_positive": dev_concentration["mean_excluding_best_five_signal_dates"] > 0,
    }
    if not all(dev_gate.values()):
        result = {
            "experiment": EXPERIMENT,
            "verdict": "BULL_INDUSTRY_IGNITION_FIRST_PRESSURE_BREAK_DEVELOPMENT_FAILED",
            "stage_a": stage_a,
            "development": dev_full,
            "development_annual": dev_annual,
            "development_portfolio": dev_portfolio,
            "development_concentration": dev_concentration,
            "development_gate": dev_gate,
            "development_capacity_skips": int(len(dev_skipped)),
            "audit": dev_audit,
            "forward_years_opened": False,
        }
        write_json(RESULT, result)
        return result
    write_json(
        FORWARD_FREEZE,
        {
            "experiment": EXPERIMENT,
            "profile": PROFILE,
            "contract_sha256": sha(CONTRACT),
            "candidate_sha256": sha(CANDIDATES),
            "development_outcomes_sha256": sha(DEV_OUTCOMES),
            "development_accepted_sha256": sha(DEV_ACCEPTED),
            "development_gate": dev_gate,
            "forward_outcomes_opened": False,
        },
    )
    forward_candidates = candidates.loc[candidates.signal_date.dt.year.isin(FORWARD_YEARS)].copy()
    forward_outcomes, forward_audit = build_outcomes(forward_candidates, FORWARD_OUTCOMES)
    all_outcomes = pd.concat([dev_outcomes, forward_outcomes], ignore_index=True)
    accepted, skipped, _nav, portfolio = replay(
        attach_rank_fields(all_outcomes, candidates), ACCEPTED, SKIPPED, NAV
    )
    for column in ("signal_date", "entry_date", "exit_date"):
        accepted[column] = pd.to_datetime(accepted[column])
    full = summary(accepted)
    annual = {str(year): summary(accepted.loc[accepted.signal_date.dt.year.eq(year)]) for year in YEARS}
    board = {name: summary(part) for name, part in accepted.groupby("sleeve", sort=True)}
    concentration = v1.concentration_metrics(accepted)
    gate = {
        "capacity_accepted_completed_gt_500": len(accepted) > 500,
        "mean_net_gt_3pct": full["mean_net"] is not None and full["mean_net"] > 0.03,
        "mean_holding_lt_15": full["mean_holding_sessions"] is not None and full["mean_holding_sessions"] < 15,
        "2021_2023_each_positive": all(
            annual[str(year)]["mean_net"] is not None and annual[str(year)]["mean_net"] > 0 for year in FORWARD_YEARS
        ),
        "mean_excluding_best5_dates_positive": concentration["mean_excluding_best_five_signal_dates"] > 0,
        "top5_date_positive_pnl_share_le_25pct": concentration["top_five_signal_date_positive_pnl_share"] <= 0.25,
    }
    audit = {
        **dev_audit,
        **{f"forward_{key}": value for key, value in forward_audit.items()},
        "feature_after_decision_count": int(candidates.feature_latest_timestamp.gt(candidates.decision_at).sum()),
        "post_2023_signal_or_feature_count": int(candidates.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "negative_cash_count": int(portfolio["negative_cash_count"]),
        "max_k_violation_count": int(portfolio["max_k_violation_count"]),
    }
    if any(audit.values()):
        raise ResearchError(str(audit))
    verdict = (
        "BULL_INDUSTRY_IGNITION_FIRST_PRESSURE_BREAK_TARGET_MET"
        if all(gate.values())
        else "BULL_INDUSTRY_IGNITION_FIRST_PRESSURE_BREAK_TARGET_FAILED"
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
        "hashes": {"forward_freeze": sha(FORWARD_FREEZE), "accepted": sha(ACCEPTED), "nav": sha(NAV)},
    }
    write_json(RESULT, result)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {EXPERIMENT}", "", f"`{verdict}`", "",
        "|Year|Trades|Mean net|Median net|Win|Severe10|Mean hold|",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in YEARS:
        item = annual[str(year)]
        lines.append(
            f"|{year}|{item['completed_trades']}|{v1.pct(item['mean_net'])}|{v1.pct(item['median_net'])}|"
            f"{v1.pct(item['win_rate'])}|{v1.pct(item['severe_loss10'])}|"
            f"{item['mean_holding_sessions'] if item['mean_holding_sessions'] is not None else '—'}|"
        )
    lines += ["", f"Gate: `{json.dumps(gate, sort_keys=True)}`.", ""]
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
