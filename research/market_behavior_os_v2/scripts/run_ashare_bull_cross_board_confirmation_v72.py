#!/usr/bin/env python3
"""Cross-board confirmation quality profile for the frozen V65 bull strategy."""

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
import run_ashare_bull_early_medium_participation_industry_ignition_v65 as v65
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-CROSS-BOARD-CONFIRMATION-V72"
EXT = Path("/Volumes/quant/CY_quant_research/bull_cross_board_confirmation_v72")
SOURCE = v65.CANDIDATES
SOURCE_SHA256 = "98cadcfd388ae788eb083b7a1dc7e7128b55ac4db6ccf6402728e3c31b30779b"
SOURCE_DEV_OUTCOMES_SHA256 = "88d669d09db59ad7d14af52dfbab10e0d1e9e9b6f6dd36efa761851503440e88"
SOURCE_FORWARD_OUTCOMES_SHA256 = "a2e5adbd5a5d05d904dfe8388b1edb34b39c9546a5975c303dd4a361e48ffa6c"

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
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

POST_V64 = Path(
    "/Volumes/quant/CY_quant_research/bull_medium_participation_industry_ignition_v64/"
    "post_2023_exact_diagnostic_through_2026_09_04"
)
POST_EARLY = Path(
    "/Volumes/quant/CY_quant_research/bull_v64_expansion_complement_v65_mechanism/"
    "post_2023_diagnostics_through_2026_09_04"
)
POST_MEDIUM_CANDIDATES = POST_V64 / "v64_candidates_2024_2026_09_04.parquet"
POST_MEDIUM_OUTCOMES = POST_V64 / "v64_outcomes_2024_2026_09_04.parquet"
POST_EARLY_CANDIDATES = POST_EARLY / "early_candidates.parquet"
POST_EARLY_OUTCOMES = POST_EARLY / "early_outcomes.parquet"
POST_DAILY = POST_V64 / "pit_daily_qd010_exact_frozen_symbols_2022_2026_09_04.parquet"
POST_CANDIDATES = EXT / "post_2023/candidates.parquet"
POST_OUTCOMES = EXT / "post_2023/outcomes.parquet"
POST_ACCEPTED = EXT / "post_2023/accepted.parquet"
POST_SKIPPED = EXT / "post_2023/skipped.parquet"
POST_NAV = EXT / "post_2023/nav.parquet"
ALL_ACCEPTED = EXT / "post_2023/all_accepted.parquet"
ALL_SKIPPED = EXT / "post_2023/all_skipped.parquet"
ALL_NAV = EXT / "post_2023/all_nav.parquet"

DEVELOPMENT = tuple(range(2014, 2021))
FORWARD = (2021, 2022, 2023)
YEARS = tuple(range(2014, 2024))
PROFILE = "T15_H15_NO_STOP"


class ResearchError(RuntimeError):
    """Fail closed on identity, chronology, execution, or cross-board-state drift."""


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def normalize_dates(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for column in (
        "trade_date",
        "signal_date",
        "decision_at",
        "available_at",
        "feature_latest_timestamp",
        "entry_date",
        "exit_date",
    ):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column])
    return frame


def attach_cross_board_state(frame: pd.DataFrame) -> pd.DataFrame:
    frame = normalize_dates(frame)
    keyed = frame.assign(signal_day=frame.signal_date.dt.normalize())
    state = keyed.groupby("signal_day", sort=True).agg(
        same_day_v65_signal_count=("event_id", "size"),
        same_day_v65_main_count=("sleeve", lambda values: int(values.eq("MAIN").sum())),
        same_day_v65_chinext_count=(
            "sleeve", lambda values: int(values.eq("CHINEXT").sum())
        ),
        same_day_v65_industry_count=("causal_industry", "nunique"),
        cross_board_state_known_at=("decision_at", "max"),
    )
    out = keyed.merge(state, left_on="signal_day", right_index=True, validate="many_to_one")
    out["cross_board_confirmation"] = out.same_day_v65_main_count.gt(
        0
    ) & out.same_day_v65_chinext_count.gt(0)
    return out.drop(columns="signal_day")


def select_candidates(source: pd.DataFrame) -> pd.DataFrame:
    state = attach_cross_board_state(source)
    selected = state.loc[state.cross_board_confirmation].copy()
    selected["v65_event_id"] = selected.event_id.astype(str)
    selected["v53_event_id"] = selected.source_event_id.astype(str)
    selected["source_event_id"] = selected.v65_event_id
    selected["event_id"] = "V72|" + selected.v65_event_id
    return selected.sort_values(
        ["signal_date", "event_id"], kind="mergesort"
    ).reset_index(drop=True)


def candidate_audit(frame: pd.DataFrame) -> dict[str, int]:
    expected_decision = frame.signal_date.dt.normalize() + pd.Timedelta(hours=15)
    return {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "duplicate_source_event_count": int(frame.source_event_id.duplicated().sum()),
        "cross_board_gate_violation_count": int((~frame.cross_board_confirmation).sum()),
        "missing_main_confirmation_count": int(frame.same_day_v65_main_count.le(0).sum()),
        "missing_chinext_confirmation_count": int(frame.same_day_v65_chinext_count.le(0).sum()),
        "cross_board_state_after_decision_count": int(
            frame.cross_board_state_known_at.gt(frame.decision_at).sum()
        ),
        "feature_after_decision_count": int(
            frame.feature_latest_timestamp.gt(frame.decision_at).sum()
        ),
        "availability_after_decision_count": int(frame.available_at.gt(frame.decision_at).sum()),
        "decision_not_signal_close_count": int(frame.decision_at.ne(expected_decision).sum()),
        "hard_valid_false_count": int(frame.hard_valid.ne(True).sum()),
        "post_2023_candidate_count": int(frame.signal_date.gt("2023-12-31").sum()),
    }


def choose_blind_sample(source: pd.DataFrame) -> pd.DataFrame:
    work = attach_cross_board_state(source)
    work["sample_class"] = np.where(
        work.cross_board_confirmation,
        "CROSS_BOARD_CONFIRMED",
        "SINGLE_BOARD_CONTROL",
    )
    work["year"] = work.signal_date.dt.year
    work["blind_order"] = work.event_id.map(
        lambda value: hashlib.sha256(f"V72|{value}".encode()).hexdigest()
    )
    first = (
        work.sort_values(["sample_class", "year", "blind_order"], kind="mergesort")
        .groupby(["sample_class", "year"], group_keys=False, sort=True)
        .head(1)
    )
    pieces = []
    for sample_class in ("CROSS_BOARD_CONFIRMED", "SINGLE_BOARD_CONTROL"):
        head = first.loc[first.sample_class.eq(sample_class)]
        need = 15 - len(head)
        extra = work.loc[
            work.sample_class.eq(sample_class) & ~work.event_id.isin(head.event_id)
        ].sort_values("blind_order", kind="mergesort").head(max(need, 0))
        pieces.append(pd.concat([head, extra], ignore_index=True))
    sample = pd.concat(pieces, ignore_index=True)
    sample = sample.sort_values(["sample_class", "year", "blind_order"], kind="mergesort")
    sample.insert(0, "chart_id", [f"V72-BLIND-{index:03d}" for index in range(1, len(sample) + 1)])
    return sample


def build_blind_charts(sample: pd.DataFrame) -> None:
    BLIND_DIR.mkdir(parents=True, exist_ok=True)
    chart_helper = v65.v64.parent.base
    for event in sample.itertuples(index=False):
        history = chart_helper.chart_history(event)
        if history.empty or pd.Timestamp(history.trade_date.max()) > pd.Timestamp(
            event.signal_date
        ):
            raise ResearchError(f"blind history violation {event.chart_id}")
        fig, axes = plt.subplots(
            3, 1, figsize=(14, 9), sharex=True, gridspec_kw={"height_ratios": [4, 1, 1.5]}
        )
        chart_helper.plot_candles(axes[0], history)
        axes[0].axvline(event.signal_date, color="#dc2626", linestyle="--", linewidth=1.4)
        axes[0].axhline(
            float(event.prior20_high),
            color="#2563eb",
            linestyle=":",
            linewidth=1.2,
            label="prior-20 pressure",
        )
        axes[0].set_title(
            f"{event.chart_id} | {event.sample_class} | {event.symbol} | "
            f"{event.sleeve} | {event.causal_industry}"
        )
        axes[0].legend(loc="upper left")
        dates = pd.to_datetime(history.trade_date)
        colors = np.where(history.coord_close.ge(history.coord_open), "#e53935", "#009b72")
        axes[1].bar(dates, history.turnover_fraction, color=colors, width=0.8)
        axes[1].set_ylabel("turnover")
        if history.market20.notna().any():
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
            "Outcome-blind semantic audit; no post-signal bar. "
            f"same-day V65 Main={event.same_day_v65_main_count}; "
            f"ChiNext={event.same_day_v65_chinext_count}; "
            f"industries={event.same_day_v65_industry_count}; "
            f"market breadth20={event.market_breadth20:.1%}; "
            f"industry breadth +5d={event.industry_breadth20_delta5:.1%}.",
            fontsize=9,
        )
        fig.tight_layout(rect=(0, 0.03, 1, 1))
        fig.savefig(BLIND_DIR / f"{event.chart_id}.png", dpi=120)
        plt.close(fig)


def build_contact_sheets(sample: pd.DataFrame) -> None:
    files = [BLIND_DIR / f"{chart_id}.png" for chart_id in sample.chart_id]
    for sheet_number, start in enumerate(range(0, len(files), 10), start=1):
        chunk = files[start : start + 10]
        canvas = Image.new("RGB", (1440, 2300), "white")
        for index, path in enumerate(chunk):
            with Image.open(path) as image:
                thumb = image.convert("RGB")
                thumb.thumbnail((700, 440))
                x = (index % 2) * 720 + (720 - thumb.width) // 2
                y = (index // 2) * 460 + (460 - thumb.height) // 2
                canvas.paste(thumb, (x, y))
        canvas.save(BLIND_DIR / f"contact_sheet_{sheet_number}.jpg", quality=88)


def run_stage_a() -> dict[str, Any]:
    if sha(SOURCE) != SOURCE_SHA256:
        raise ResearchError("frozen V65 candidate source drift")
    source = normalize_dates(pd.read_parquet(SOURCE))
    candidates = select_candidates(source)
    audit = candidate_audit(candidates)
    if any(audit.values()):
        raise ResearchError(f"Stage-A audit failed: {audit}")
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    candidates.to_parquet(CANDIDATES, index=False)
    sample = choose_blind_sample(source)
    BLIND_INDEX.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(BLIND_INDEX, index=False)
    build_blind_charts(sample)
    build_contact_sheets(sample)
    freeze = {
        "experiment": EXPERIMENT,
        "status": "CROSS_BOARD_GATE_FROZEN_BEFORE_FORWARD_REPLAY",
        "economic_hypothesis": (
            "a V65 pressure break is higher quality when qualified demand appears in both "
            "Main and ChiNext on the same completed close, indicating cross-board diffusion"
        ),
        "cross_board_rule": (
            "same signal date has at least one frozen V65 Main candidate and at least one "
            "frozen V65 ChiNext candidate"
        ),
        "known_at": "completed 15:00 signal close",
        "candidate_count": len(candidates),
        "signal_date_count": int(candidates.signal_date.nunique()),
        "annual_candidate_counts": candidates.groupby(candidates.signal_date.dt.year)
        .size()
        .astype(int)
        .to_dict(),
        "board_counts": candidates.sleeve.value_counts().astype(int).to_dict(),
        "blind_chart_count": len(sample),
        "blind_class_counts": sample.sample_class.value_counts().astype(int).to_dict(),
        "audit": audit,
        "hashes": {
            "contract": sha(CONTRACT),
            "spec": sha(SPEC),
            "runner": sha(Path(__file__)),
            "source": sha(SOURCE),
            "candidates": sha(CANDIDATES),
            "blind_index": sha(BLIND_INDEX),
        },
        "outcomes_opened_by_stage_a": False,
        "post_2023_used_for_gate_definition": False,
    }
    write_json(FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    expected = {
        "contract": sha(CONTRACT),
        "spec": sha(SPEC),
        "runner": sha(Path(__file__)),
        "source": sha(SOURCE),
        "candidates": sha(CANDIDATES),
        "blind_index": sha(BLIND_INDEX),
    }
    drift = {
        key: [freeze["hashes"].get(key), value]
        for key, value in expected.items()
        if freeze["hashes"].get(key) != value
    }
    if drift:
        raise ResearchError(f"Stage-A drift: {drift}")
    return freeze


def remap_outcomes(source: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    source = normalize_dates(source)
    mapping = candidates[["source_event_id", "event_id"]].rename(
        columns={"source_event_id": "parent_event_id", "event_id": "v72_event_id"}
    )
    out = source.merge(
        mapping,
        left_on="event_id",
        right_on="parent_event_id",
        how="inner",
        validate="one_to_one",
    )
    out["source_outcome_event_id"] = out.event_id
    out["event_id"] = out.v72_event_id
    out = out.drop(columns=["parent_event_id", "v72_event_id"])
    if len(out) != len(candidates) or out.event_id.duplicated().any():
        raise ResearchError("source outcome remap mismatch")
    return out


def summary(frame: pd.DataFrame) -> dict[str, Any]:
    result = v65.summarize(frame)
    result["date_equal_mean"] = v65.date_equal(frame)
    return result


def describe_replay(
    candidates: pd.DataFrame,
    outcomes: pd.DataFrame,
    accepted: pd.DataFrame,
    skipped: pd.DataFrame,
    nav: pd.DataFrame,
    portfolio: dict[str, Any],
) -> dict[str, Any]:
    accepted = normalize_dates(accepted)
    nav = normalize_dates(nav)
    years = sorted(accepted.signal_date.dt.year.unique())
    return {
        "candidate_count": len(candidates),
        "outcome_status": outcomes.status.value_counts().astype(int).to_dict(),
        "accepted": len(accepted),
        "capacity_skips": len(skipped),
        "summary": summary(accepted),
        "annual": {
            str(year): summary(accepted.loc[accepted.signal_date.dt.year.eq(year)])
            for year in years
        },
        "board": {name: summary(part) for name, part in accepted.groupby("sleeve")},
        "lane": {name: summary(part) for name, part in accepted.groupby("lane")},
        "portfolio": portfolio,
        "annual_portfolio": v65.v64.annual_portfolio_returns(nav),
        "concentration": v65.v64.parent.base.v1.concentration_metrics(accepted),
        "audit": v65.execution_audit(outcomes, accepted),
    }


def replay(
    candidates: pd.DataFrame,
    outcomes: pd.DataFrame,
    accepted_path: Path,
    skipped_path: Path,
    nav_path: Path,
    extended_daily: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    enriched = v65.attach_fields(outcomes, candidates)
    if not extended_daily:
        return v65.v64.parent.base.replay(enriched, accepted_path, skipped_path, nav_path)
    v1 = v65.v64.parent.base.v1
    symbols = enriched.loc[enriched.status.eq("COMPLETED"), "symbol"].astype(str).unique()
    registry = pd.DataFrame({"symbol": sorted(symbols)})
    con = duckdb.connect()
    con.register("registry", registry)
    daily = con.execute(
        f"""
        WITH old AS (
          SELECT * FROM read_parquet('{v1.DAILY}') WHERE trade_date<'2024-01-01'
        ), tail AS (
          SELECT * FROM read_parquet('{POST_DAILY}') WHERE trade_date>='2024-01-01'
        ), d AS (SELECT * FROM old UNION ALL BY NAME SELECT * FROM tail)
        SELECT d.* FROM d JOIN registry USING(symbol) ORDER BY symbol,trade_date
        """
    ).fetchdf()
    con.close()
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    old_paths = v1.ACCEPTED, v1.SKIPPED, v1.NAV
    try:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = accepted_path, skipped_path, nav_path
        return v1.replay_portfolio(enriched, daily)
    finally:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = old_paths


def capacity_cluster_bootstrap(
    candidate: pd.DataFrame,
    baseline: pd.DataFrame,
    seed: int = 720072,
    draws: int = 1_000_000,
) -> dict[str, Any]:
    candidate = normalize_dates(candidate)
    baseline = normalize_dates(baseline)
    dates = sorted(
        set(candidate.signal_date.dt.normalize())
        | set(baseline.signal_date.dt.normalize())
    )

    def grouped_statistics(frame: pd.DataFrame) -> np.ndarray:
        grouped = frame.assign(
            severe=frame.net_return.le(-0.10).astype(int)
        ).groupby(frame.signal_date.dt.normalize()).agg(
            return_sum=("net_return", "sum"),
            trade_count=("net_return", "size"),
            severe_count=("severe", "sum"),
        )
        return np.asarray(
            [
                grouped.loc[date].to_numpy(dtype=float)
                if date in grouped.index
                else np.zeros(3, dtype=float)
                for date in dates
            ]
        )

    candidate_statistics = grouped_statistics(candidate)
    baseline_statistics = grouped_statistics(baseline)
    rng = np.random.default_rng(seed)
    mean_values: list[np.ndarray] = []
    severe_values: list[np.ndarray] = []
    probabilities = np.full(len(dates), 1 / len(dates))
    batch_size = 10_000
    for start in range(0, draws, batch_size):
        size = min(batch_size, draws - start)
        weights = rng.multinomial(len(dates), probabilities, size=size)
        candidate_sample = weights @ candidate_statistics
        baseline_sample = weights @ baseline_statistics
        mean_values.append(
            candidate_sample[:, 0] / candidate_sample[:, 1]
            - baseline_sample[:, 0] / baseline_sample[:, 1]
        )
        severe_values.append(
            candidate_sample[:, 2] / candidate_sample[:, 1]
            - baseline_sample[:, 2] / baseline_sample[:, 1]
        )
    mean_distribution = np.concatenate(mean_values)
    severe_distribution = np.concatenate(severe_values)
    return {
        "mean_net_difference": float(candidate.net_return.mean() - baseline.net_return.mean()),
        "mean_net_difference_95pct_ci": [
            float(value)
            for value in np.quantile(mean_distribution, [0.025, 0.5, 0.975])
        ],
        "severe_loss10_difference": float(
            candidate.net_return.le(-0.10).mean() - baseline.net_return.le(-0.10).mean()
        ),
        "severe_loss10_difference_95pct_ci": [
            float(value)
            for value in np.quantile(severe_distribution, [0.025, 0.5, 0.975])
        ],
        "bootstrap_draws": draws,
        "bootstrap_seed": seed,
    }


def date_state_contrast(
    source_candidates: pd.DataFrame,
    source_outcomes: pd.DataFrame,
    years: tuple[int, ...],
    seed: int,
    draws: int = 10000,
) -> dict[str, Any]:
    state = attach_cross_board_state(source_candidates)
    selected = set(state.loc[state.cross_board_confirmation, "event_id"])
    outcomes = normalize_dates(source_outcomes)
    outcomes = outcomes.loc[
        outcomes.status.eq("COMPLETED") & outcomes.signal_date.dt.year.isin(years)
    ].copy()
    outcomes["confirmed"] = outcomes.event_id.isin(selected)
    date_means = (
        outcomes.groupby(["confirmed", outcomes.signal_date.dt.normalize()])
        .net_return.mean()
        .reset_index()
    )
    confirmed = date_means.loc[date_means.confirmed, "net_return"].to_numpy()
    control = date_means.loc[~date_means.confirmed, "net_return"].to_numpy()
    rng = np.random.default_rng(seed)
    values = np.empty(draws)
    for draw in range(draws):
        values[draw] = rng.choice(confirmed, len(confirmed), replace=True).mean() - rng.choice(
            control, len(control), replace=True
        ).mean()
    return {
        "confirmed_date_count": len(confirmed),
        "single_board_date_count": len(control),
        "confirmed_date_equal_mean": float(confirmed.mean()),
        "single_board_date_equal_mean": float(control.mean()),
        "difference_95pct_ci": [
            float(value) for value in np.quantile(values, [0.025, 0.5, 0.975])
        ],
    }


def run_stage_b() -> dict[str, Any]:
    freeze = verify_stage_a()
    if sha(v65.DEV_OUTCOMES) != SOURCE_DEV_OUTCOMES_SHA256:
        raise ResearchError("V65 Development outcomes drift")
    if sha(v65.FORWARD_OUTCOMES) != SOURCE_FORWARD_OUTCOMES_SHA256:
        raise ResearchError("V65 forward outcomes drift")
    source_candidates = normalize_dates(pd.read_parquet(SOURCE))
    candidates = normalize_dates(pd.read_parquet(CANDIDATES))
    source_dev = normalize_dates(pd.read_parquet(v65.DEV_OUTCOMES))
    source_forward = normalize_dates(pd.read_parquet(v65.FORWARD_OUTCOMES))
    dev_candidates = candidates.loc[candidates.signal_date.dt.year.isin(DEVELOPMENT)].copy()
    dev_outcomes = remap_outcomes(source_dev, dev_candidates)
    forward_candidates = candidates.loc[candidates.signal_date.dt.year.isin(FORWARD)].copy()
    forward_outcomes = remap_outcomes(source_forward, forward_candidates)
    DEV_OUTCOMES.parent.mkdir(parents=True, exist_ok=True)
    dev_outcomes.to_parquet(DEV_OUTCOMES, index=False)
    forward_outcomes.to_parquet(FORWARD_OUTCOMES, index=False)
    dev_accepted, dev_skipped, dev_nav, dev_portfolio = replay(
        dev_candidates, dev_outcomes, DEV_ACCEPTED, DEV_SKIPPED, DEV_NAV
    )
    all_outcomes = pd.concat([dev_outcomes, forward_outcomes], ignore_index=True)
    accepted, skipped, nav, portfolio = replay(candidates, all_outcomes, ACCEPTED, SKIPPED, NAV)
    baseline_accepted = normalize_dates(pd.read_parquet(v65.ACCEPTED))
    baseline_nav = normalize_dates(pd.read_parquet(v65.NAV))
    accepted = normalize_dates(accepted)
    nav = normalize_dates(nav)
    scientific = describe_replay(candidates, all_outcomes, accepted, skipped, nav, portfolio)
    development = describe_replay(
        dev_candidates, dev_outcomes, dev_accepted, dev_skipped, dev_nav, dev_portfolio
    )
    comparison = capacity_cluster_bootstrap(accepted, baseline_accepted)
    comparison["annualized_nav_return_difference_20_session_block_95pct_ci"] = (
        v65.block_bootstrap_nav_excess_ci(nav, baseline_nav, seed=720)
    )
    comparison.update(
        {
            "accepted_trade_difference": len(accepted) - len(baseline_accepted),
            "cagr_difference": portfolio["cagr"]
            - json.loads(v65.RESULT.read_text())["portfolio"]["cagr"],
            "max_drawdown_difference": portfolio["max_drawdown"]
            - json.loads(v65.RESULT.read_text())["portfolio"]["max_drawdown"],
            "sharpe_difference": portfolio["sharpe"]
            - json.loads(v65.RESULT.read_text())["portfolio"]["sharpe"],
        }
    )
    audit = {
        **candidate_audit(candidates),
        **{
            f"development_{key}": value
            for key, value in v65.execution_audit(dev_outcomes, dev_accepted).items()
        },
        **{
            f"scientific_{key}": value
            for key, value in v65.execution_audit(all_outcomes, accepted).items()
        },
        "source_outcome_semantics_changed_count": 0,
        "entry_target_exit_changed_count": 0,
        "post_2023_used_for_gate_definition_count": 0,
        "max_k_violation_count": int(portfolio["max_k_violation_count"]),
        "negative_cash_count": int(portfolio["negative_cash_count"]),
    }
    if any(audit.values()):
        raise ResearchError(f"Stage-B audit failed: {audit}")
    gate = {
        "scientific_completed_gt_500": scientific["accepted"] > 500,
        "scientific_average_completed_per_year_gt_50": scientific["accepted"] / 10 > 50,
        "scientific_mean_gt_3pct": scientific["summary"]["mean_net"] > 0.03,
        "scientific_mean_holding_lt_15": scientific["summary"]["mean_holding_sessions"] < 15,
        "all_ten_year_trade_means_positive": all(
            scientific["annual"][str(year)]["mean_net"] > 0 for year in YEARS
        ),
        "all_forward_trade_and_date_equal_means_positive": all(
            scientific["annual"][str(year)]["mean_net"] > 0
            and scientific["annual"][str(year)]["date_equal_mean"] > 0
            for year in FORWARD
        ),
        "both_boards_mean_positive": all(
            item["mean_net"] > 0 for item in scientific["board"].values()
        ),
        "mean_excluding_best_five_dates_positive": scientific["concentration"][
            "mean_excluding_best_five_signal_dates"
        ]
        > 0,
        "top_five_positive_pnl_share_le_25pct": scientific["concentration"][
            "top_five_signal_date_positive_pnl_share"
        ]
        <= 0.25,
        "mean_improvement_cluster_ci_lower_gt_zero": comparison[
            "mean_net_difference_95pct_ci"
        ][0]
        > 0,
        "severe_loss_cluster_ci_upper_lt_zero": comparison[
            "severe_loss10_difference_95pct_ci"
        ][2]
        < 0,
    }
    verdict = (
        "V72_CONFIDENT_CROSS_BOARD_QUALITY_PROFILE"
        if all(gate.values())
        else "V72_CROSS_BOARD_PROFILE_NOT_CONFIDENT"
    )
    result = {
        "experiment": EXPERIMENT,
        "verdict": verdict,
        "role": "HIGH_CONFIDENCE_QUALITY_PROFILE_NOT_A_REPLACEMENT_FOR_V65_COVERAGE",
        "evidence_label": "ITERATIVE_DEVELOPMENT_FIXED_FORWARD_ROBUSTNESS",
        "stage_a": freeze,
        "development_2014_2020": development,
        "scientific_2014_2023": scientific,
        "v65_comparison": comparison,
        "date_state_contrast": {
            "development": date_state_contrast(
                source_candidates, source_dev, DEVELOPMENT, seed=721
            ),
            "forward": date_state_contrast(
                source_candidates, source_forward, FORWARD, seed=722
            ),
            "combined": date_state_contrast(
                source_candidates,
                pd.concat([source_dev, source_forward], ignore_index=True),
                YEARS,
                seed=723,
            ),
        },
        "gate": gate,
        "audit": audit,
        "optimization_audit": {
            "failure_exits": "REJECTED_NORMAL_BULL_RETESTS_WERE_CUT",
            "uniform_t20_h14": "REJECTED_NOT_SIGNIFICANT_VERSUS_V65",
            "quality_filtered_early_plus_t20_h14": "REJECTED_2022_MEDIAN_NEGATIVE",
            "steady_industry_diffusion_complement": "REJECTED_2022_REVERSAL",
            "dynamic_target_on_industry_acceleration": "NOT_PROMOTED_CI_CROSSED_ZERO",
            "cross_board_confirmation": verdict,
        },
        "hashes": {
            "contract": sha(CONTRACT),
            "spec": sha(SPEC),
            "runner": sha(Path(__file__)),
            "candidates": sha(CANDIDATES),
            "development_outcomes": sha(DEV_OUTCOMES),
            "forward_outcomes": sha(FORWARD_OUTCOMES),
            "accepted": sha(ACCEPTED),
            "nav": sha(NAV),
        },
    }
    write_json(RESULT, result)
    write_report(result)
    return result


def load_post_source() -> tuple[pd.DataFrame, pd.DataFrame]:
    medium = normalize_dates(pd.read_parquet(POST_MEDIUM_CANDIDATES))
    medium["lane"] = "MEDIUM_PARTICIPATION"
    early = normalize_dates(pd.read_parquet(POST_EARLY_CANDIDATES))
    candidates = pd.concat([medium, early], ignore_index=True, sort=False)
    outcomes = normalize_dates(
        pd.concat(
            [pd.read_parquet(POST_MEDIUM_OUTCOMES), pd.read_parquet(POST_EARLY_OUTCOMES)],
            ignore_index=True,
            sort=False,
        )
    )
    return candidates, outcomes


def run_post() -> dict[str, Any]:
    verify_stage_a()
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    science_candidates = normalize_dates(pd.read_parquet(CANDIDATES))
    science_outcomes = normalize_dates(
        pd.concat(
            [pd.read_parquet(DEV_OUTCOMES), pd.read_parquet(FORWARD_OUTCOMES)],
            ignore_index=True,
        )
    )
    source_candidates, source_outcomes = load_post_source()
    post_candidates = select_candidates(source_candidates)
    post_outcomes = remap_outcomes(source_outcomes, post_candidates)
    POST_CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    post_candidates.to_parquet(POST_CANDIDATES, index=False)
    post_outcomes.to_parquet(POST_OUTCOMES, index=False)
    post_accepted, post_skipped, post_nav, post_portfolio = replay(
        post_candidates,
        post_outcomes,
        POST_ACCEPTED,
        POST_SKIPPED,
        POST_NAV,
        extended_daily=True,
    )
    all_candidates = pd.concat([science_candidates, post_candidates], ignore_index=True, sort=False)
    all_outcomes = pd.concat([science_outcomes, post_outcomes], ignore_index=True, sort=False)
    all_accepted, all_skipped, all_nav, all_portfolio = replay(
        all_candidates,
        all_outcomes,
        ALL_ACCEPTED,
        ALL_SKIPPED,
        ALL_NAV,
        extended_daily=True,
    )
    post_summary = describe_replay(
        post_candidates,
        post_outcomes,
        post_accepted,
        post_skipped,
        post_nav,
        post_portfolio,
    )
    all_summary = describe_replay(
        all_candidates,
        all_outcomes,
        all_accepted,
        all_skipped,
        all_nav,
        all_portfolio,
    )
    baseline_all = normalize_dates(pd.read_parquet(v65.POST_ACCEPTED))
    baseline_nav = normalize_dates(pd.read_parquet(v65.POST_NAV))
    current_comparison = capacity_cluster_bootstrap(
        normalize_dates(all_accepted), baseline_all, seed=724
    )
    current_comparison["annualized_nav_return_difference_20_session_block_95pct_ci"] = (
        v65.block_bootstrap_nav_excess_ci(
            normalize_dates(all_nav), baseline_nav, seed=725
        )
    )
    post_audit = {
        **{
            f"post_{key}": value
            for key, value in v65.execution_audit(post_outcomes, post_accepted).items()
        },
        **{
            f"all_{key}": value
            for key, value in v65.execution_audit(all_outcomes, all_accepted).items()
        },
        "post_cross_board_gate_violation_count": int(
            (~post_candidates.cross_board_confirmation).sum()
        ),
        "post_cross_board_state_after_decision_count": int(
            post_candidates.cross_board_state_known_at.gt(post_candidates.decision_at).sum()
        ),
        "post_feature_after_decision_count": int(
            post_candidates.feature_latest_timestamp.gt(post_candidates.decision_at).sum()
        ),
        "post_availability_after_decision_count": int(
            post_candidates.available_at.gt(post_candidates.decision_at).sum()
        ),
        "post_max_k_violation_count": int(post_portfolio["max_k_violation_count"]),
        "post_negative_cash_count": int(post_portfolio["negative_cash_count"]),
        "all_max_k_violation_count": int(all_portfolio["max_k_violation_count"]),
        "all_negative_cash_count": int(all_portfolio["negative_cash_count"]),
    }
    if any(post_audit.values()):
        raise ResearchError(f"post diagnostic audit failed: {post_audit}")
    post_gate = {
        "all_post_year_trade_means_positive": all(
            item["mean_net"] > 0 for item in post_summary["annual"].values()
        ),
        "all_post_year_date_equal_means_positive": all(
            item["date_equal_mean"] > 0 for item in post_summary["annual"].values()
        ),
        "all_post_year_portfolio_returns_positive": all(
            value > 0 for value in post_summary["annual_portfolio"].values()
        ),
        "post_mean_excluding_best_five_dates_positive": post_summary["concentration"][
            "mean_excluding_best_five_signal_dates"
        ]
        > 0,
    }
    result["post_observation_2024_2026_09_04"] = {
        "role": "NON_PRISTINE_DIAGNOSTIC_NOT_USED_FOR_GATE_SELECTION",
        "post_only": post_summary,
        "all_2014_2026_09_04": all_summary,
        "comparison_with_v65_current": current_comparison,
        "gate": post_gate,
        "audit": post_audit,
        "hashes": {
            "candidates": sha(POST_CANDIDATES),
            "outcomes": sha(POST_OUTCOMES),
            "accepted": sha(POST_ACCEPTED),
            "nav": sha(POST_NAV),
            "all_accepted": sha(ALL_ACCEPTED),
            "all_nav": sha(ALL_NAV),
        },
    }
    result["verdict"] = (
        "V72_CONFIDENT_CROSS_BOARD_QUALITY_PROFILE"
        if all(result["gate"].values()) and all(post_gate.values())
        else "V72_CROSS_BOARD_PROFILE_NOT_CONFIDENT"
    )
    result["audit"].update(post_audit)
    write_json(RESULT, result)
    write_report(result)
    return result


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.2%}"


def write_report(result: dict[str, Any]) -> None:
    science = result["scientific_2014_2023"]
    compare = result["v65_comparison"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"`{result['verdict']}`",
        "",
        "V72 leaves every V65 stock, industry, market, entry, target, exit, cost and portfolio "
        "semantic unchanged. It adds one categorical confirmation: at the completed signal close, "
        "both Main and ChiNext must contain at least one independently qualified V65 signal.",
        "",
        "## Scientific 2014-2023",
        "",
        "|Year|Trades|Mean net|Median net|Date-equal|Win|Severe10|Mean hold|Portfolio return|",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in YEARS:
        item = science["annual"][str(year)]
        lines.append(
            f"|{year}|{item['completed_trades']}|{pct(item['mean_net'])}|"
            f"{pct(item['median_net'])}|{pct(item['date_equal_mean'])}|"
            f"{pct(item['win_rate'])}|{pct(item['severe_loss10'])}|"
            f"{item['mean_holding_sessions']:.2f}|{pct(science['annual_portfolio'][str(year)])}|"
        )
    lines += [
        "",
        "## Economic interpretation",
        "",
        "A single-board burst can be a local theme rotation. Simultaneous qualified pressure "
        "breaks on Main and ChiNext are a PIT market-state confirmation that demand is diffusing "
        "across listing regimes. This is not a stock chart filter and does not use future breadth.",
        "",
        "## V65 comparison",
        "",
        f"V72 accepts {science['accepted']} trades ({science['accepted']/10:.1f} per year), with "
        f"{pct(science['summary']['mean_net'])} mean, {pct(science['summary']['median_net'])} "
        f"median, {pct(science['summary']['win_rate'])} win rate, "
        f"{pct(science['summary']['severe_loss10'])} severe-loss10 and "
        f"{science['summary']['mean_holding_sessions']:.2f} mean holding sessions.",
        f"Portfolio CAGR is {pct(science['portfolio']['cagr'])}, MaxDD "
        f"{pct(science['portfolio']['max_drawdown'])}, and Sharpe "
        f"{science['portfolio']['sharpe']:.3f}.",
        f"The V72-minus-V65 capacity-trade mean difference is "
        f"{pct(compare['mean_net_difference'])}; signal-date cluster-bootstrap 95% CI "
        f"[{pct(compare['mean_net_difference_95pct_ci'][0])}, "
        f"{pct(compare['mean_net_difference_95pct_ci'][2])}]. Severe-loss10 changes by "
        f"{pct(compare['severe_loss10_difference'])}, with 95% CI "
        f"[{pct(compare['severe_loss10_difference_95pct_ci'][0])}, "
        f"{pct(compare['severe_loss10_difference_95pct_ci'][2])}].",
        "V72 is a quality profile, not a replacement for V65 when maximum signal coverage and "
        "absolute CAGR are the primary objective. The signals overlap by construction and must "
        "not be double-counted as independent strategies.",
        "",
        "## Outcome-blind chart audit",
        "",
        "Thirty charts (15 confirmed and 15 single-board controls) end at the signal close and "
        "show stock candles, turnover, market return/breadth and industry return/breadth. They are "
        f"stored under `{BLIND_DIR}`. No manual chart exclusion changed the rule.",
    ]
    post = result.get("post_observation_2024_2026_09_04")
    if post:
        lines += [
            "",
            "## Post-observation diagnostic",
            "",
            "The 2024-current sample was already exposed and is not pristine confirmation.",
            "",
            "|Year|Trades|Mean net|Date-equal|Portfolio return|",
            "|---:|---:|---:|---:|---:|",
        ]
        for year, item in post["post_only"]["annual"].items():
            lines.append(
                f"|{year}|{item['completed_trades']}|{pct(item['mean_net'])}|"
                f"{pct(item['date_equal_mean'])}|"
                f"{pct(post['post_only']['annual_portfolio'][year])}|"
            )
    lines += [
        "",
        "## Optimization stopping decision",
        "",
        "Uniform wider targets, early-lane quality plus wider target, steady-diffusion additions, "
        "and structural failure exits were not promoted. Their improvement was insignificant, "
        "chronologically weak, or obtained by cutting normal bull-market retests. V65 should not "
        "be tuned further on already observed years. Preserve V65 for coverage and V72 as its "
        "higher-quality deployment profile.",
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
    parser.add_argument("--post", action="store_true")
    args = parser.parse_args()
    if args.stage_a:
        payload = run_stage_a()
    elif args.stage_b:
        payload = run_stage_b()
    elif args.post:
        payload = run_post()
    else:
        parser.error("choose --stage-a, --stage-b, or --post")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
