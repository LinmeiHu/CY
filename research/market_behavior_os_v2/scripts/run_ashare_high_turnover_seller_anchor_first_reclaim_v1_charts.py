#!/usr/bin/env python3
"""Render every frozen seller-anchor reclaim event for chart-rule discovery."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from research.market_behavior_os_v2.scripts import (
    run_ashare_first_active_demand_takeover_after_weakness_12m_chart_discovery_v1 as visual,
)


EXPERIMENT = "ASHARE-HIGH-TURNOVER-SELLER-ANCHOR-FIRST-RECLAIM-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_high_turnover_seller_anchor_first_reclaim_v1_stage_a.py"
)
STAGE_B_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_high_turnover_seller_anchor_first_reclaim_v1_stage_b.py"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_high_turnover_seller_anchor_first_reclaim_v1"
STAGE_A_FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = OUTPUT_ROOT / "stage_b/future_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "stage_b/outcomes.parquet"
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
    SPEC: "5e363f0b58552f6dc017b63481d37d0afe8f6d48357e5eb2a52ac8bc5cefbaca",
    STAGE_A_RUNNER: "8dce9885a8d61f20db8032312ddba5e259ac2cd7199938d297afd2d1fb2ba8bc",
    STAGE_B_RUNNER: "8ac637a028ea1cf056e94fceb475e8f284cd96a75b8938118b1eeafa51f9ce14",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    STAGE_A_FREEZE: "03b139164e0819dc13c4bfb089613ebbefc954f9de0677ae207b521aa36df366",
    CANDIDATES: "b3100747074b5e8c8437b78f7002cbfb53ab066e1dc88918e0f6531f8cc88974",
    PATHS: "d6d00c7c6cf00e7d1957f9e06998eb83fd4d3517cfcd04fdcfd662bc890132cb",
    OUTCOMES: "558526f2ea99a9be17463b9a9944934cfb2900a681d3fb72454bf2138102fba8",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen identity or chart chronology drift."""


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
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


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


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidates = pd.read_parquet(CANDIDATES)
    outcomes = pd.read_parquet(OUTCOMES)
    for column in (
        "signal_date", "anchor_date", "decision_at", "available_at",
        "market_latest_source_timestamp",
    ):
        candidates[column] = pd.to_datetime(candidates[column])
    for column in ("signal_date", "anchor_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    if len(candidates) != 655 or candidates.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    if len(outcomes) != 655 or outcomes.event_id.duplicated().any():
        raise ResearchError("outcome-label identity drift")
    con = duckdb.connect()
    con.register(
        "chart_keys",
        candidates[["event_id", "symbol", "signal_cal_idx", "signal_date"]],
    )
    windows = con.execute(
        f"""
        SELECT k.event_id,k.signal_date,d.symbol,d.trade_date,d.cal_idx,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.turnover_fraction,
          d.current_day_data_tradable,d.current_valid,d.hard_valid,
          d.available_at,d.decision_at
        FROM read_parquet('{DAILY.as_posix()}') d
        JOIN chart_keys k ON d.symbol=k.symbol
          AND d.cal_idx BETWEEN k.signal_cal_idx-126 AND k.signal_cal_idx+126
        WHERE d.trade_date<=DATE '2021-06-30'
        ORDER BY k.event_id,d.cal_idx
        """
    ).fetch_df()
    con.close()
    for column in ("signal_date", "trade_date", "available_at", "decision_at"):
        windows[column] = pd.to_datetime(windows[column])
    if windows.event_id.nunique() != 655:
        raise ResearchError("chart window misses an event")
    if windows.trade_date.max() > pd.Timestamp("2021-06-30"):
        raise ResearchError("chart context crossed the frozen cap")
    if candidates.market_latest_source_timestamp.gt(candidates.decision_at).any():
        raise ResearchError("market state arrived after signal decision")
    return candidates, outcomes, windows


def outcome_bucket(status: str, net_return: float) -> str:
    if status != "COMPLETED" or not math.isfinite(net_return):
        return "NO_COMPLETED_TRADE"
    if net_return >= 0.04:
        return "PROFIT_GE_4PCT"
    if net_return >= 0:
        return "PROFIT_0_TO_4PCT"
    if net_return > -0.10:
        return "LOSS_0_TO_10PCT"
    return "SEVERE_LOSS"


def build_ledger(
    candidates: pd.DataFrame, outcomes: pd.DataFrame, windows: pd.DataFrame
) -> pd.DataFrame:
    outcomes = outcomes.copy()
    merged = candidates.merge(
        outcomes[
            [
                "event_id", "status", "entry_date", "entry_price", "target_price",
                "target_gross_return", "exit_date", "exit_price", "exit_reason",
                "holding_sessions", "net_return",
            ]
        ],
        on="event_id",
        how="left",
        validate="one_to_one",
    )
    window_lookup = {key: part for key, part in windows.groupby("event_id", sort=False)}
    rows: list[dict[str, Any]] = []
    ordered = merged.sort_values(
        ["signal_date", "symbol", "event_id"], kind="mergesort"
    )
    for event in ordered.itertuples(index=False):
        frame = window_lookup[str(event.event_id)]
        valid = frame.loc[
            frame.current_valid.fillna(False)
            & frame[["coord_open", "coord_high", "coord_low", "coord_close"]]
            .notna().all(axis=1)
        ].sort_values("cal_idx", kind="mergesort")
        signal = valid.loc[valid.cal_idx.eq(int(event.signal_cal_idx))]
        if len(signal) != 1:
            raise ResearchError(f"{event.event_id}: signal chart bar not unique")
        signal_close = float(signal.iloc[0].coord_close)
        before = valid.loc[valid.cal_idx.lt(int(event.signal_cal_idx))].tail(126)
        prior126_high = float(before.coord_high.max())
        prior126_low = float(before.coord_low.min())
        target_corridor_touches = int(
            valid.loc[
                valid.cal_idx.gt(int(event.anchor_cal_idx))
                & valid.cal_idx.lt(int(event.signal_cal_idx))
                & valid.coord_high.ge(float(event.anchor_high))
                & valid.coord_low.le(float(event.pre_anchor60_target_high))
            ].shape[0]
        )
        net_return = visual.charts.safe_float(event.net_return)
        rows.append(
            {
                "event_id": str(event.event_id),
                "symbol": str(event.symbol),
                "sleeve": str(event.sleeve),
                "causal_industry": str(event.causal_industry),
                "signal_date": pd.Timestamp(event.signal_date),
                "signal_year": int(pd.Timestamp(event.signal_date).year),
                "signal_cal_idx": int(event.signal_cal_idx),
                "chart_number": 0,
                "market_regime": str(event.market_regime),
                "market_median_ret20": float(event.market_median_ret20),
                "market_median_ret60": float(event.market_median_ret60),
                "market_positive_ret20_share": float(event.market_positive_ret20_share),
                "market_positive_ret60_share": float(event.market_positive_ret60_share),
                "market_return_acceleration": float(
                    event.market_median_ret20 - event.market_median_ret60
                ),
                "market_breadth_acceleration": float(
                    event.market_positive_ret20_share
                    - event.market_positive_ret60_share
                ),
                "anchor_date": pd.Timestamp(event.anchor_date),
                "anchor_cal_idx": int(event.anchor_cal_idx),
                "anchor_age_sessions": int(event.anchor_age_sessions),
                "anchor_return": float(event.anchor_return),
                "anchor_close_location": float(event.anchor_close_location),
                "anchor_turnover_fraction": float(event.anchor_turnover_fraction),
                "anchor_high": float(event.anchor_high),
                "anchor_vwap": float(event.anchor_vwap),
                "below_anchor_vwap_sessions": int(event.below_anchor_vwap_sessions),
                "pre_anchor60_target_high": float(event.pre_anchor60_target_high),
                "signal_target_headroom": float(event.signal_target_headroom),
                "target_corridor_touch_sessions": target_corridor_touches,
                "signal_step_return": float(event.step_return),
                "signal_close_location": float(event.close_location),
                "signal_turnover_ratio": float(event.signal_turnover_ratio),
                "ret20": float(event.ret20),
                "ret60": float(event.ret60),
                "pre126_position": (
                    (signal_close - prior126_low) / (prior126_high - prior126_low)
                    if prior126_high > prior126_low
                    else math.nan
                ),
                "status": str(event.status),
                "entry_date": pd.Timestamp(event.entry_date),
                "entry_price": visual.charts.safe_float(event.entry_price),
                "target_price": visual.charts.safe_float(event.target_price),
                "target_gross_return": visual.charts.safe_float(event.target_gross_return),
                "exit_date": pd.Timestamp(event.exit_date),
                "exit_price": visual.charts.safe_float(event.exit_price),
                "exit_reason": str(event.exit_reason),
                "holding_sessions": visual.charts.safe_float(event.holding_sessions),
                "net_return": net_return,
                "outcome_bucket": outcome_bucket(str(event.status), net_return),
            }
        )
    ledger = pd.DataFrame(rows)
    ledger["chart_number"] = np.arange(1, len(ledger) + 1, dtype=int)
    return ledger


def render_chart(event: pd.Series, frame: pd.DataFrame, output: Path) -> None:
    signal_date = pd.Timestamp(event.signal_date)
    anchor_date = pd.Timestamp(event.anchor_date)
    signal = frame.loc[frame.trade_date.eq(signal_date)]
    if len(signal) != 1:
        raise ResearchError(f"{event.event_id}: chart signal row not unique")
    signal_close = float(signal.iloc[0].coord_close)
    figure, (price_ax, volume_ax) = visual.charts.plt.subplots(
        2, 1, figsize=(13.2, 7.4),
        gridspec_kw={"height_ratios": [4.4, 1.0], "hspace": 0.05}, sharex=True,
    )
    visual.charts.draw_candles(price_ax, frame, signal_close)
    signal_x = visual.charts.mdates.date2num(signal_date.to_pydatetime())
    anchor_x = visual.charts.mdates.date2num(anchor_date.to_pydatetime())
    price_ax.axvline(anchor_x, color="#7c3aed", linewidth=1.1, linestyle="--", label="seller anchor")
    price_ax.axvline(signal_x, color="#b45309", linewidth=1.3, label="first reclaim")
    price_ax.axhline(100.0, color="#b45309", linewidth=0.7, linestyle=":", label="signal close")
    for value, color, label in (
        (event.anchor_vwap, "#2563eb", "anchor VWAP"),
        (event.anchor_high, "#7c3aed", "anchor high"),
        (event.pre_anchor60_target_high, "#dc2626", "pre-anchor target high"),
    ):
        price_ax.axhline(float(value) * 100 / signal_close, color=color, linewidth=0.85, linestyle="--", label=label)
    if pd.notna(event.entry_date) and math.isfinite(float(event.entry_price)):
        entry_x = visual.charts.mdates.date2num(pd.Timestamp(event.entry_date).to_pydatetime())
        price_ax.scatter(entry_x, float(event.entry_price) * 100 / signal_close, marker="^", s=62, color="#7b2cbf", zorder=8, label="entry")
    if math.isfinite(float(event.target_price)):
        price_ax.axhline(float(event.target_price) * 100 / signal_close, color="#f97316", linewidth=0.9, linestyle=":", label="A67 target")
    if pd.notna(event.exit_date) and math.isfinite(float(event.exit_price)):
        exit_x = visual.charts.mdates.date2num(pd.Timestamp(event.exit_date).to_pydatetime())
        price_ax.scatter(exit_x, float(event.exit_price) * 100 / signal_close, marker="v", s=62, color="#111111", zorder=8, label="exit")
    status = str(event.outcome_bucket)
    if math.isfinite(float(event.net_return)):
        status += f" | net {float(event.net_return):+.2%} | {event.exit_reason}"
    price_ax.set_title(
        f"{int(event.chart_number):04d} | {event.symbol} | {signal_date.date()} | {event.market_regime} | {status}\n"
        f"anchor {anchor_date.date()} age {int(event.anchor_age_sessions)} r {float(event.anchor_return):+.1%} | "
        f"signal {float(event.signal_step_return):+.1%} turn {float(event.signal_turnover_ratio):.2f}x | "
        f"headroom {float(event.signal_target_headroom):.1%} corridor touches {int(event.target_corridor_touch_sessions)} | "
        f"r20/r60 {float(event.ret20):+.1%}/{float(event.ret60):+.1%} pos {float(event.pre126_position):.0%}",
        fontsize=9.2,
    )
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    price_ax.grid(alpha=0.17, linewidth=0.5)
    handles, labels = price_ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    price_ax.legend(by_label.values(), by_label.keys(), loc="upper left", ncol=5, fontsize=6.7)
    valid_turn = frame.loc[frame.turnover_fraction.notna()].copy()
    turn_dates = visual.charts.mdates.date2num(pd.to_datetime(valid_turn.trade_date).to_numpy())
    volume_ax.bar(turn_dates, valid_turn.turnover_fraction * 100, width=0.75, color="#8b8b8b", alpha=0.55)
    volume_ax.axvline(anchor_x, color="#7c3aed", linewidth=0.9, linestyle="--")
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
    figure.savefig(output, dpi=105, bbox_inches="tight", facecolor="white", metadata={"Creator": EXPERIMENT, "Title": str(event.event_id)})
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
        "market_regime": str(event.market_regime),
        "outcome_bucket": str(event.outcome_bucket),
        "net_return": visual.charts.safe_float(event.net_return),
        "chart_path": str(output),
    }


def run(workers: int, skip_render: bool) -> dict[str, Any]:
    source_hashes = verify_inputs()
    configure_visuals()
    candidates, outcomes, windows = load_inputs()
    ledger = build_ledger(candidates, outcomes, windows)
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
            chart_index = pd.DataFrame(list(executor.map(render_worker, tasks, chunksize=1)))
        chart_index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
        contact_sheets = visual.build_nine_up(chart_index, SHEET_DIR, EXPERIMENT)
        for bucket in (
            "SEVERE_LOSS", "LOSS_0_TO_10PCT", "PROFIT_0_TO_4PCT",
            "PROFIT_GE_4PCT", "NO_COMPLETED_TRADE",
        ):
            subset = chart_index.loc[chart_index.outcome_bucket.eq(bucket)].sort_values(
                ["signal_date", "symbol", "event_id"], kind="mergesort"
            )
            outcome_sheets.extend(
                visual.build_nine_up(subset, OUTCOME_SHEET_ROOT / bucket.lower(), bucket)
            )
    payload = {
        "experiment": EXPERIMENT,
        "stage": "FULL_FROZEN_MOTHER_CHART_CORPUS",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "window_panel_sha256": sha256(WINDOW_PANEL),
        "review_ledger_sha256": sha256(REVIEW_LEDGER),
        "signals": int(len(candidates)),
        "charts": 0 if skip_render else int(len(candidates)),
        "chronological_contact_sheets": int(len(contact_sheets)),
        "outcome_contact_sheets": int(len(outcome_sheets)),
        "outcome_buckets": {str(key): int(value) for key, value in ledger.outcome_bucket.value_counts().items()},
        "maximum_signal_date": str(candidates.signal_date.max().date()),
        "maximum_chart_bar_date": str(windows.trade_date.max().date()),
        "all_chronological_sheets_reviewed": False,
        "2022_2024_signal_feature_or_outcome_read": "NO",
        "future_market_or_structure_function": False,
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
