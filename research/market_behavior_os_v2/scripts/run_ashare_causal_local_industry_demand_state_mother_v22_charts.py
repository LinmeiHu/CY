#!/usr/bin/env python3
"""Render every frozen local-industry candidate for chronological chart review."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import run_ashare_first_active_demand_takeover_after_weakness_12m_chart_discovery_v1 as visual

EXPERIMENT = "ASHARE-CAUSAL-LOCAL-INDUSTRY-DEMAND-STATE-MOTHER-V22"
REPO = Path(__file__).resolve().parents[3]
FREEZE = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STAGE_A_RUNNER = (
    REPO
    / "research/market_behavior_os_v2/scripts/"
    "run_ashare_causal_local_industry_demand_state_mother_v22_stage_a.py"
)
STAGE_B_RUNNER = (
    REPO
    / "research/market_behavior_os_v2/scripts/"
    "run_ashare_causal_local_industry_demand_state_mother_v22_stage_b.py"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = (
    DATA_ROOT
    / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1"
    / "pit_daily_compact_2013_2023.parquet"
)
REGIME = (
    DATA_ROOT
    / "ashare_causal_market_regime_routed_simple_strategy_v1"
    / "stage_a/causal_market_regime_2014_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_causal_local_industry_demand_state_mother_v22"
STAGE_A_FREEZE = OUTPUT_ROOT / "stage_a" / "stage_a_freeze.json"
CANDIDATES = OUTPUT_ROOT / "stage_a" / "candidates_frozen.parquet"
PATHS = OUTPUT_ROOT / "stage_b" / "future_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "stage_b" / "outcomes.parquet"
CHART_ROOT = OUTPUT_ROOT / "stage_c_charts"
WINDOW_PANEL = CHART_ROOT / "chart_window_panel.parquet"
REVIEW_LEDGER = CHART_ROOT / "review_ledger.parquet"
REVIEW_CSV = CHART_ROOT / "review_ledger.csv"
CHART_DIR = CHART_ROOT / "individual_charts"
CHART_INDEX = CHART_ROOT / "chart_index.csv"
SHEET_DIR = CHART_ROOT / "contact_sheets"
OUTCOME_SHEET_ROOT = CHART_ROOT / "review_sheets_by_outcome"
MANIFEST = CHART_ROOT / "manifest.json"
EXPECTED_HASHES = {
    FREEZE: "9098c3380e3b95f09aaee06b47fccbf8504a8eb93e6e69463b598d7c70e92288",
    STAGE_A_RUNNER: "1ccbe027a06f7eb806de56b24616f9e0b10d7873be58b92784a31e0b0d9f4b32",
    STAGE_B_RUNNER: "27691539a8e171d8837f1dcccc75fcec73414f2b8f31f29da54991a9c52de3c6",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
    STAGE_A_FREEZE: "6ad89277576c5c00ca977aaf04fbad9fa92cea31c9d82b51d92875f305ac2e7f",
    CANDIDATES: "58dcf3aaa232bc15e364dfb16806a944521eb782b62e7dc26d9e9068165c9e1e",
    PATHS: "c4de7543a8acc3899e57c3793180ab45bec97961d995d1c0ed1cb38ce91dc186",
    OUTCOMES: "e86f96fdc18f3d5f6db57ed35a52165f5bbd499101dc8af80c0ea73ba0650fbe",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen input or chart chronology drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual[str(path)] = sha256(path)
        if actual[str(path)] != expected:
            raise ResearchError(
                f"input identity drift: {path}: {actual[str(path)]} != {expected}"
            )
    return actual


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def load_enriched_candidates() -> tuple[pd.DataFrame, pd.DataFrame]:
    candidates = pd.read_parquet(CANDIDATES)
    outcomes = pd.read_parquet(OUTCOMES)
    for column in (
        "signal_date",
        "decision_at",
        "available_at",
        "industry_latest_source_timestamp",
    ):
        candidates[column] = pd.to_datetime(candidates[column])
    for column in ("signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    if len(candidates) != 4933 or candidates.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    if len(outcomes) != len(candidates) or outcomes.event_id.duplicated().any():
        raise ResearchError("outcome identity drift")
    regime = pd.read_parquet(
        REGIME,
        columns=[
            "trade_date",
            "market_regime",
            "market_median_ret20",
            "market_positive_ret20_share",
            "market_median_ret60",
            "market_positive_ret60_share",
            "latest_source_timestamp",
        ],
    )
    regime["trade_date"] = pd.to_datetime(regime.trade_date)
    regime = regime.rename(
        columns={"latest_source_timestamp": "market_latest_source_timestamp"}
    )
    candidates = candidates.merge(
        regime,
        left_on="signal_date",
        right_on="trade_date",
        how="left",
        validate="many_to_one",
    ).drop(columns="trade_date")
    con = duckdb.connect()
    con.register("keys", candidates[["event_id", "symbol", "signal_cal_idx"]])
    descriptors = con.execute(
        f"""
        SELECT k.event_id,d.ret20,d.ret60,d.turnover_fraction,
          d.coord_open/nullif(d.prior_coord_close,0)-1 AS open_gap
        FROM keys k JOIN read_parquet('{DAILY.as_posix()}') d
          ON d.symbol=k.symbol AND d.cal_idx=k.signal_cal_idx
        """
    ).fetch_df()
    con.close()
    candidates = candidates.merge(
        descriptors, on="event_id", how="left", validate="one_to_one"
    )
    required = [
        "ret20",
        "ret60",
        "turnover_fraction",
        "open_gap",
        "market_regime",
        "market_median_ret20",
        "market_positive_ret20_share",
        "market_median_ret60",
        "market_positive_ret60_share",
    ]
    if candidates[required].isna().any().any():
        raise ResearchError("missing chart descriptor")
    if candidates.market_latest_source_timestamp.gt(candidates.decision_at).any():
        raise ResearchError("global market descriptor after decision")
    candidates["market_return_acceleration"] = (
        candidates.market_median_ret20 - candidates.market_median_ret60
    )
    candidates["market_breadth_acceleration"] = (
        candidates.market_positive_ret20_share
        - candidates.market_positive_ret60_share
    )
    candidates["cal_idx"] = candidates.signal_cal_idx.astype(int)
    candidates["turn20"] = (
        candidates.turnover_fraction / candidates.turnover_expansion
    )
    candidates = candidates.sort_values(
        ["signal_date", "mechanism", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    outcomes = outcomes.set_index("event_id").loc[candidates.event_id].reset_index()
    return candidates, outcomes


def configure_visuals() -> None:
    visual.EXPERIMENT = EXPERIMENT
    visual.DAILY = DAILY
    visual.EXT_ROOT = CHART_ROOT
    visual.CHART_DIR = CHART_DIR
    visual.SHEET_DIR = SHEET_DIR
    visual.OUTCOME_SHEET_ROOT = OUTCOME_SHEET_ROOT
    visual.WINDOW_PANEL = WINDOW_PANEL
    visual.REVIEW_LEDGER = REVIEW_LEDGER
    visual.REVIEW_CSV = REVIEW_CSV
    visual.CHART_INDEX = CHART_INDEX
    visual.configure_charts()


def render_chart(event: pd.Series, frame: pd.DataFrame, output: Path) -> None:
    signal_date = pd.Timestamp(event.signal_date)
    signal = frame.loc[frame.trade_date.eq(signal_date)]
    if len(signal) != 1:
        raise ResearchError(f"{event.event_id}: chart signal row not unique")
    signal_close = float(signal.iloc[0].coord_close)
    figure, (price_ax, volume_ax) = visual.charts.plt.subplots(
        2,
        1,
        figsize=(13.2, 7.4),
        gridspec_kw={"height_ratios": [4.4, 1.0], "hspace": 0.05},
        sharex=True,
    )
    visual.charts.draw_candles(price_ax, frame, signal_close)
    signal_x = visual.charts.mdates.date2num(signal_date.to_pydatetime())
    price_ax.axvline(signal_x, color="#b45309", linewidth=1.3, label="signal")
    price_ax.axhline(
        100.0, color="#b45309", linewidth=0.7, linestyle=":", label="signal close"
    )
    target_return = 0.15 if str(event.local_industry_state) == "LOCAL_BULL" else 0.10
    if pd.notna(event.entry_date) and math.isfinite(float(event.entry_price)):
        entry_x = visual.charts.mdates.date2num(
            pd.Timestamp(event.entry_date).to_pydatetime()
        )
        price_ax.scatter(
            entry_x,
            float(event.entry_price) * 100.0 / signal_close,
            marker="^",
            s=65,
            color="#7b2cbf",
            zorder=8,
            label="entry",
        )
        price_ax.axhline(
            float(event.entry_price) * (1 + target_return) * 100.0 / signal_close,
            color="#ff7f0e",
            linewidth=0.75,
            linestyle="--",
            label=f"+{int(target_return * 100)}% target",
        )
    if pd.notna(event.exit_date) and math.isfinite(float(event.exit_price)):
        exit_x = visual.charts.mdates.date2num(
            pd.Timestamp(event.exit_date).to_pydatetime()
        )
        price_ax.scatter(
            exit_x,
            float(event.exit_price) * 100.0 / signal_close,
            marker="v",
            s=65,
            color="#111111",
            zorder=8,
            label="exit",
        )
    status = str(event.outcome_bucket)
    if math.isfinite(float(event.net_return)):
        status += f" | net {float(event.net_return):+.2%} | {event.exit_reason}"
    price_ax.set_title(
        f"{int(event.chart_number):04d} | {event.symbol} | {signal_date.date()} | "
        f"{event.local_industry_state}/{event.market_regime} | {status}\n"
        f"industry r20/r60 {float(event.industry_median_ret20):+.1%}/"
        f"{float(event.industry_median_ret60):+.1%} | participation "
        f"{float(event.industry_positive_ret20_share):.0%}/"
        f"{float(event.industry_positive_ret60_share):.0%} | stock r20 "
        f"{float(event.ret20):+.1%} | same-date {int(event.cluster_signal_count)}",
        fontsize=9.8,
    )
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    price_ax.grid(alpha=0.17, linewidth=0.5)
    handles, labels = price_ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    price_ax.legend(
        by_label.values(), by_label.keys(), loc="upper left", ncol=5, fontsize=7.0
    )
    valid_turn = frame.loc[frame.turnover_fraction.notna()].copy()
    turn_dates = visual.charts.mdates.date2num(
        pd.to_datetime(valid_turn.trade_date).to_numpy()
    )
    volume_ax.bar(
        turn_dates,
        valid_turn.turnover_fraction * 100.0,
        width=0.75,
        color="#8b8b8b",
        alpha=0.55,
    )
    volume_ax.axvline(signal_x, color="#b45309", linewidth=1.0)
    volume_ax.set_ylabel("Turnover %")
    volume_ax.grid(alpha=0.12, linewidth=0.4)
    volume_ax.xaxis.set_major_locator(visual.charts.mdates.MonthLocator(interval=2))
    volume_ax.xaxis.set_major_formatter(visual.charts.mdates.DateFormatter("%Y-%m"))
    for label in volume_ax.get_xticklabels():
        label.set_rotation(25)
        label.set_horizontalalignment("right")
    figure.subplots_adjust(left=0.065, right=0.985, top=0.88, bottom=0.10)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        output,
        dpi=115,
        bbox_inches="tight",
        facecolor="white",
        metadata={"Creator": EXPERIMENT, "Title": str(event.event_id)},
    )
    visual.charts.plt.close(figure)


def render_worker(payload: tuple[dict[str, Any], pd.DataFrame, str]) -> dict[str, Any]:
    event_dict, frame, output_text = payload
    event = pd.Series(event_dict)
    output = Path(output_text)
    render_chart(event, frame, output)
    return {
        "chart_number": int(event.chart_number),
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "signal_date": pd.Timestamp(event.signal_date),
        "mechanism": str(event.mechanism),
        "local_industry_state": str(event.local_industry_state),
        "outcome_bucket": str(event.outcome_bucket),
        "net_return": visual.charts.safe_float(event.net_return),
        "chart_path": str(output),
    }


def run(workers: int, skip_render: bool) -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates, outcomes = load_enriched_candidates()
    configure_visuals()
    windows = visual.charts.load_windows(candidates)
    ledger = visual.build_chart_ledger(candidates, outcomes, windows)
    extras = candidates[
        [
            "event_id",
            "mechanism",
            "causal_industry",
            "local_industry_state",
            "industry_median_ret20",
            "industry_median_ret60",
            "industry_positive_ret20_share",
            "industry_positive_ret60_share",
            "market_regime",
            "market_median_ret20",
            "market_median_ret60",
            "market_positive_ret20_share",
            "market_positive_ret60_share",
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
                list(executor.map(render_worker, tasks, chunksize=1))
            )
        chart_index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
        contact_sheets = visual.build_nine_up(chart_index, SHEET_DIR, EXPERIMENT)
        for bucket in (
            "SEVERE_LOSS",
            "LOSS_0_TO_10PCT",
            "PROFIT_0_TO_4PCT",
            "PROFIT_GE_4PCT",
            "NO_COMPLETED_TRADE",
        ):
            subset = chart_index.loc[
                chart_index.outcome_bucket.eq(bucket)
            ].sort_values(["signal_date", "symbol", "event_id"], kind="mergesort")
            outcome_sheets.extend(
                visual.build_nine_up(
                    subset, OUTCOME_SHEET_ROOT / bucket.lower(), bucket
                )
            )
    payload = {
        "experiment": EXPERIMENT,
        "stage": "FULL_FROZEN_CANDIDATE_CHART_CORPUS",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "window_panel_sha256": sha256(WINDOW_PANEL),
        "review_ledger_sha256": sha256(REVIEW_LEDGER),
        "signals": len(candidates),
        "charts": 0 if skip_render else len(candidates),
        "chronological_contact_sheets": len(contact_sheets),
        "outcome_contact_sheets": len(outcome_sheets),
        "maximum_signal_date": str(candidates.signal_date.max().date()),
        "maximum_chart_bar_date": str(pd.to_datetime(windows.trade_date).max().date()),
        "all_chronological_sheets_reviewed": False,
        "2021_signal_or_rule_read": "NO",
        "2022_2024_signal_or_outcome_read": "NO",
        "future_market_or_industry_function": False,
        "next_step": "REVIEW_ALL_CHRONOLOGICAL_SHEETS_BEFORE_ANY_RULE_FREEZE",
    }
    write_json(MANIFEST, payload)
    payload["manifest_sha256"] = sha256(MANIFEST)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--skip-render", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.workers, args.skip_render), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
