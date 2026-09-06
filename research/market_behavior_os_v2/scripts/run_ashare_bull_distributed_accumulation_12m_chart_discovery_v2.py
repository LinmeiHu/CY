#!/usr/bin/env python3
"""Render every frozen pre-2021 BULL distributed-accumulation signal for chart discovery."""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

import run_ashare_first_active_demand_takeover_after_weakness_12m_chart_discovery_v1 as base


EXPERIMENT = "ASHARE-BULL-DISTRIBUTED-ACCUMULATION-12M-CHART-DISCOVERY-V2"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "39169d9a27162a9c81a18627a9f855e7f0713659c6a1255b43c424ac4fc0a943"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
PARENT_ROOT = DATA_ROOT / "ashare_distributed_accumulation_slow_exhaustion_mother_screen_v1"
PARENT_CANDIDATES = PARENT_ROOT / "development_2014_2020_candidates.parquet"
PARENT_OUTCOMES = PARENT_ROOT / "development_2014_2020_outcomes.parquet"
PARENT_RUNNER = OS_ROOT / "scripts/run_ashare_distributed_accumulation_slow_exhaustion_mother_screen_v1.py"
DAILY = DATA_ROOT / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/pit_daily_compact_2013_2023.parquet"
REGIME = DATA_ROOT / "ashare_causal_market_regime_routed_simple_strategy_v1/stage_a/causal_market_regime_2014_2023.parquet"
EXPECTED_INPUT_HASHES = {
    PARENT_CANDIDATES: "7c08a9ed2090fd1b9b27ee0068ed2c438b8583fc876872bc0523d5e00f5ab364",
    PARENT_OUTCOMES: "8e410688aba5f07f1a36c87bd0e061c8d052fe6d2b051656b59970589320285d",
    PARENT_RUNNER: "4c4992e333c9f7931ca84454e1f71742cf49bcfa8ff333ba8876cc202f351870",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}
EXT_ROOT = DATA_ROOT / "ashare_bull_distributed_accumulation_12m_chart_discovery_v2/development_2014_2020"
CANDIDATES = EXT_ROOT / "candidates_frozen.parquet"
OUTCOMES = EXT_ROOT / "outcomes.parquet"
WINDOW_PANEL = EXT_ROOT / "chart_window_panel.parquet"
REVIEW_LEDGER = EXT_ROOT / "review_ledger.parquet"
REVIEW_CSV = EXT_ROOT / "review_ledger.csv"
CHART_DIR = EXT_ROOT / "individual_charts"
CHART_INDEX = EXT_ROOT / "chart_index.csv"
SHEET_DIR = EXT_ROOT / "contact_sheets"
OUTCOME_SHEET_ROOT = EXT_ROOT / "review_sheets_by_outcome"
MANIFEST = EXT_ROOT / "manifest.json"


class ResearchError(RuntimeError):
    """Fail closed on source identity, causal state, or chart chronology."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(
        f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def verify_inputs() -> dict[str, str]:
    expected = {FREEZE: EXPECTED_FREEZE_SHA256, **EXPECTED_INPUT_HASHES}
    actual: dict[str, str] = {}
    for path, expected_hash in expected.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual_hash = sha256(path)
        actual[str(path)] = actual_hash
        if actual_hash != expected_hash:
            raise ResearchError(
                f"frozen input drift: {path}: {actual_hash} != {expected_hash}"
            )
    return actual


def load_mother() -> tuple[pd.DataFrame, pd.DataFrame]:
    candidates = pd.read_parquet(PARENT_CANDIDATES)
    outcomes = pd.read_parquet(PARENT_OUTCOMES)
    candidates = candidates.loc[
        candidates.mechanism.eq("DISTRIBUTED_ACCUMULATION_ESCAPE")
        & candidates.market_regime.eq("BULL")
    ].copy()
    outcomes = outcomes.loc[outcomes.event_id.isin(candidates.event_id)].copy()
    for column in (
        "signal_date",
        "decision_at",
        "available_at",
        "market_latest_source_timestamp",
    ):
        candidates[column] = pd.to_datetime(candidates[column])
    for column in ("signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    if candidates.empty or candidates.event_id.duplicated().any():
        raise ResearchError("empty or duplicate BULL mother identity")
    if len(outcomes) != len(candidates) or outcomes.event_id.duplicated().any():
        raise ResearchError("parent outcome mapping is not one-to-one")
    if not candidates.market_regime.eq("BULL").all():
        raise ResearchError("non-BULL event escaped causal route")
    if candidates.available_at.gt(candidates.decision_at).any():
        raise ResearchError("stock input available after decision")
    if candidates.market_latest_source_timestamp.gt(candidates.decision_at).any():
        raise ResearchError("market state available after decision")
    if candidates.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 signal entered chart discovery")
    if pd.to_datetime(outcomes.exit_date).max() > pd.Timestamp("2021-12-31"):
        raise ResearchError("post-2021 outcome entered chart discovery")
    regime_columns = [
        "trade_date",
        "market_median_ret20",
        "market_positive_ret20_share",
        "market_median_ret60",
        "market_positive_ret60_share",
    ]
    regime = pd.read_parquet(REGIME, columns=regime_columns)
    regime["trade_date"] = pd.to_datetime(regime.trade_date)
    candidates = candidates.merge(
        regime,
        left_on="signal_date",
        right_on="trade_date",
        how="left",
        validate="many_to_one",
    ).drop(columns="trade_date")
    if candidates[regime_columns[1:]].isna().any().any():
        raise ResearchError("missing frozen causal market descriptor")
    candidates["market_return_acceleration"] = (
        candidates.market_median_ret20 - candidates.market_median_ret60
    )
    candidates["market_breadth_acceleration"] = (
        candidates.market_positive_ret20_share
        - candidates.market_positive_ret60_share
    )
    connection = duckdb.connect()
    connection.register(
        "candidate_keys", candidates[["event_id", "symbol", "signal_cal_idx"]]
    )
    daily_features = connection.execute(
        f"""
        SELECT k.event_id,d.ret20,d.ret60,d.turnover_fraction,
          d.coord_open/nullif(d.prior_coord_close,0)-1 AS open_gap
        FROM candidate_keys k
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON d.symbol=k.symbol AND d.cal_idx=k.signal_cal_idx
        """
    ).fetch_df()
    connection.close()
    candidates = candidates.merge(
        daily_features, on="event_id", how="left", validate="one_to_one"
    )
    if candidates[["ret20", "ret60", "turnover_fraction", "open_gap"]].isna().any().any():
        raise ResearchError("missing signal-session chart descriptor")
    candidates["cal_idx"] = candidates.signal_cal_idx.astype(int)
    candidates["turn20"] = (
        candidates.turnover_fraction / candidates.turnover_expansion
    )
    candidates = candidates.sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    outcomes = outcomes.set_index("event_id").loc[candidates.event_id].reset_index()
    return candidates, outcomes


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.loc[frame.status.eq("COMPLETED")].copy()
    values = pd.to_numeric(complete.net_return, errors="coerce")
    dates = frame.groupby("signal_date").size() if not frame.empty else pd.Series(dtype=float)
    return {
        "signals": int(len(frame)),
        "completed": int(len(complete)),
        "signal_dates": int(frame.signal_date.nunique()),
        "symbols": int(frame.symbol.nunique()),
        "mean_net": None if complete.empty else float(values.mean()),
        "median_net": None if complete.empty else float(values.median()),
        "positive_rate": None if complete.empty else float(values.gt(0).mean()),
        "ge_4pct_rate": None if complete.empty else float(values.ge(0.04).mean()),
        "severe10": None if complete.empty else float(values.le(-0.10).mean()),
        "target_hit": None
        if complete.empty
        else float(complete.exit_reason.fillna("").str.startswith("TARGET").mean()),
        "mean_holding_sessions": None
        if complete.empty
        else float(complete.holding_sessions.mean()),
        "largest_date_share": None if frame.empty else float(dates.max() / len(frame)),
        "top_five_date_share": None
        if frame.empty
        else float(dates.nlargest(5).sum() / len(frame)),
    }


def configure_base() -> None:
    base.EXPERIMENT = EXPERIMENT
    base.DAILY = DAILY
    base.EXT_ROOT = EXT_ROOT
    base.CANDIDATES = CANDIDATES
    base.OUTCOMES = OUTCOMES
    base.WINDOW_PANEL = WINDOW_PANEL
    base.REVIEW_LEDGER = REVIEW_LEDGER
    base.REVIEW_CSV = REVIEW_CSV
    base.CHART_DIR = CHART_DIR
    base.CHART_INDEX = CHART_INDEX
    base.SHEET_DIR = SHEET_DIR
    base.OUTCOME_SHEET_ROOT = OUTCOME_SHEET_ROOT
    base.configure_charts()


def run(workers: int, skip_render: bool) -> dict[str, Any]:
    input_hashes = verify_inputs()
    candidates, outcomes = load_mother()
    configure_base()
    write_parquet(candidates, CANDIDATES)
    write_parquet(outcomes, OUTCOMES)
    windows = base.charts.load_windows(candidates)
    ledger = base.build_chart_ledger(candidates, outcomes, windows)
    extras = candidates[
        [
            "event_id",
            "market_regime",
            "causal_industry",
            "exact_prior20_return",
            "prior20_positive_share",
            "prior20_max_abs_return",
            "downside_upside_turnover_ratio",
            "turnover_expansion",
            "close_location",
            "step_return",
            "market_median_ret20",
            "market_positive_ret20_share",
            "market_median_ret60",
            "market_positive_ret60_share",
            "market_return_acceleration",
            "market_breadth_acceleration",
        ]
    ]
    ledger = ledger.merge(extras, on="event_id", how="left", validate="one_to_one")
    write_parquet(windows, WINDOW_PANEL)
    write_parquet(ledger, REVIEW_LEDGER)
    ledger.to_csv(REVIEW_CSV, index=False, float_format="%.10g")
    contact_sheets: list[Path] = []
    outcome_sheets: list[Path] = []
    if not skip_render:
        groups = {key: part for key, part in windows.groupby("event_id", sort=False)}
        tasks = []
        for _, event in ledger.iterrows():
            target = CHART_DIR / (
                f"{int(event.chart_number):04d}_{event.symbol.replace('.', '_')}_"
                f"{pd.Timestamp(event.signal_date):%Y%m%d}.png"
            )
            tasks.append((event.to_dict(), groups[str(event.event_id)], str(target)))
        with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
            chart_index = pd.DataFrame(
                list(executor.map(base.render_worker, tasks, chunksize=1))
            )
        chart_index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
        contact_sheets = base.build_nine_up(chart_index, SHEET_DIR, EXPERIMENT)
        for bucket in (
            "SEVERE_LOSS",
            "LOSS_0_TO_10PCT",
            "PROFIT_0_TO_4PCT",
            "PROFIT_GE_4PCT",
            "NO_COMPLETED_TRADE",
        ):
            subset = chart_index.loc[chart_index.outcome_bucket.eq(bucket)].sort_values(
                ["signal_date", "symbol", "event_id"], kind="mergesort"
            )
            outcome_sheets.extend(
                base.build_nine_up(
                    subset, OUTCOME_SHEET_ROOT / bucket.lower(), bucket
                )
            )
    joined = candidates.merge(
        outcomes,
        on="event_id",
        how="left",
        suffixes=("", "_out"),
        validate="one_to_one",
    )
    joined["signal_date"] = pd.to_datetime(joined.signal_date)
    pooled = metrics(joined)
    annual = {
        str(year): metrics(joined.loc[joined.signal_date.dt.year.eq(year)])
        for year in range(2014, 2021)
    }
    baseline_gate = {
        "completed_gt_50_each_year": all(
            item["completed"] > 50 for item in annual.values()
        ),
        "mean_gt_4pct_each_year": all(
            item["mean_net"] is not None and item["mean_net"] > 0.04
            for item in annual.values()
        ),
        "median_positive_each_year": all(
            item["median_net"] is not None and item["median_net"] > 0
            for item in annual.values()
        ),
        "severe10_le_20pct_each_year": all(
            item["severe10"] is not None and item["severe10"] <= 0.20
            for item in annual.values()
        ),
    }
    payload = {
        "experiment": EXPERIMENT,
        "scientific_status": "POST_HOC_BULL_MOTHER_FULL_CHART_ANATOMY_COMPLETE",
        "input_hashes": input_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "candidate_sha256": sha256(CANDIDATES),
        "outcomes_sha256": sha256(OUTCOMES),
        "review_ledger_sha256": sha256(REVIEW_LEDGER),
        "signals": len(candidates),
        "charts": 0 if skip_render else len(candidates),
        "contact_sheets": len(contact_sheets),
        "outcome_sheets": len(outcome_sheets),
        "pooled": pooled,
        "annual": annual,
        "baseline_gate": baseline_gate,
        "baseline_passes_all_year_gates": all(baseline_gate.values()),
        "max_signal_date": str(candidates.signal_date.max().date()),
        "max_exit_date": str(pd.to_datetime(joined.exit_date).max().date()),
        "max_chart_bar_date": str(pd.to_datetime(windows.trade_date).max().date()),
        "2021_signal_or_rule_read": "NO",
        "2022_2024_read": "NO",
        "future_market_function": False,
        "next_step": "FULL_CHART_REVIEW_THEN_MAX_FIVE_RULE_FREEZE",
    }
    write_json(MANIFEST, payload)
    payload["manifest_sha256"] = sha256(MANIFEST)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--skip-render", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.workers, args.skip_render),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
