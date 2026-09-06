#!/usr/bin/env python3
"""Render every frozen post-low full-float-transfer mother event."""

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
    run_ashare_first_active_demand_takeover_after_weakness_12m_chart_discovery_v1
    as visual,
)


EXPERIMENT = "ASHARE-POST-LOW-FULL-FLOAT-TRANSFER-BASE-RESOLUTION-MOTHER-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_post_low_full_float_transfer_base_resolution_mother_v1_stage_a.py"
)
STAGE_B_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_post_low_full_float_transfer_base_resolution_mother_v1_stage_b.py"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_post_low_full_float_transfer_base_resolution_mother_v1"
STAGE_A_FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = OUTPUT_ROOT / "stage_b/future_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "stage_b/outcomes.parquet"
STAGE_B_MANIFEST = OUTPUT_ROOT / "stage_b/manifest.json"
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
    SPEC: "26d0237a191dda0afb9ef48a440d66315241cb0a80d79069299803987de56f58",
    STAGE_A_RUNNER: "674463440cae236502133efb1cd36eee28bda8448cb3aaf7d6ddd53d3258caea",
    STAGE_B_RUNNER: "e2997d43444a1fe3720156f6aa709d5e1aa08a18bd353160e6c0d0bf1493eb5b",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    STAGE_A_FREEZE: "ceb6f2ca84d91d2001ed8baefc29fb80f25ec9a914d97f3ee0c2de370a92e3bb",
    CANDIDATES: "a681269172910f0b1fc05864c4cf8a53889cc3c5e591ceb9a169c102989a4338",
    PATHS: "97cbbe07fe78cb5ecbfdd947076e8eab22fd90685cba44b83a84d6973ef655e3",
    OUTCOMES: "06c64bbeda4b1ee7b9dca16d6e036815ded86a960ba7b3aafc981bb9409ad2d3",
    STAGE_B_MANIFEST: "6551f65edac5b66db3befaf005b0615da56456924110e80a859a2e03895aa639",
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
        "anchor_date",
        "signal_date",
        "decision_at",
        "available_at",
        "base_latest_available_at",
        "market_latest_source_timestamp",
    ):
        candidates[column] = pd.to_datetime(candidates[column])
    for column in ("anchor_date", "signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    if len(candidates) != 910 or candidates.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    if len(outcomes) != 910 or outcomes.event_id.duplicated().any():
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
          d.step_return,d.current_day_data_tradable,d.current_valid,d.hard_valid,
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
    if windows.event_id.nunique() != 910:
        raise ResearchError("chart window misses an event")
    if windows.trade_date.max() > pd.Timestamp("2021-06-30"):
        raise ResearchError("chart context crossed the frozen cap")
    latest = candidates[
        ["available_at", "base_latest_available_at", "market_latest_source_timestamp"]
    ].max(axis=1)
    if latest.gt(candidates.decision_at).any():
        raise ResearchError("a chart predictor arrived after signal decision")
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


def causal_path_features(
    frame: pd.DataFrame, anchor_idx: int, signal_idx: int
) -> dict[str, float]:
    valid = frame.loc[
        frame.current_valid.fillna(False)
        & frame[["coord_open", "coord_high", "coord_low", "coord_close"]]
        .notna()
        .all(axis=1)
    ].sort_values("cal_idx", kind="mergesort")
    pre = valid.loc[valid.cal_idx.lt(signal_idx)]
    post_anchor = pre.loc[pre.cal_idx.ge(anchor_idx)]
    first10 = post_anchor.loc[post_anchor.cal_idx.le(anchor_idx + 9)]
    last20 = pre.tail(20)
    last10 = pre.tail(10)
    if post_anchor.empty or len(first10) != 10 or len(last20) < 20:
        return {
            "base_width": math.nan,
            "post_anchor_close_efficiency": math.nan,
            "post_anchor_low_test_count": math.nan,
            "pre20_range": math.nan,
            "pre10_return": math.nan,
            "pre10_down_turnover_share": math.nan,
        }
    anchor_close = float(post_anchor.iloc[0].coord_close)
    last_close = float(post_anchor.iloc[-1].coord_close)
    path = float(post_anchor.coord_close.diff().abs().sum())
    down_turn = float(last10.loc[last10.step_return.lt(0), "turnover_fraction"].sum())
    total_turn = float(last10.turnover_fraction.sum())
    anchor_low = float(post_anchor.iloc[0].coord_low)
    return {
        "base_width": float(first10.coord_high.max() / first10.coord_low.min() - 1),
        "post_anchor_close_efficiency": (
            abs(last_close - anchor_close) / path if path > 0 else math.nan
        ),
        "post_anchor_low_test_count": float(
            post_anchor.coord_low.le(anchor_low * 1.03).sum()
        ),
        "pre20_range": float(last20.coord_high.max() / last20.coord_low.min() - 1),
        "pre10_return": float(last_close / last10.iloc[0].coord_close - 1),
        "pre10_down_turnover_share": down_turn / total_turn if total_turn > 0 else math.nan,
    }


def build_ledger(
    candidates: pd.DataFrame, outcomes: pd.DataFrame, windows: pd.DataFrame
) -> pd.DataFrame:
    outcome_columns = [
        "event_id",
        "status",
        "entry_date",
        "entry_price",
        "exit_date",
        "exit_price",
        "exit_reason",
        "holding_sessions",
        "net_return",
    ]
    merged = candidates.merge(
        outcomes[outcome_columns], on="event_id", how="left", validate="one_to_one"
    )
    window_lookup = {key: part for key, part in windows.groupby("event_id", sort=False)}
    date_counts = candidates.groupby("signal_date").size()
    rows: list[dict[str, Any]] = []
    ordered = merged.sort_values(["signal_date", "symbol", "event_id"], kind="mergesort")
    for event in ordered.itertuples(index=False):
        features = causal_path_features(
            window_lookup[str(event.event_id)], int(event.anchor_idx), int(event.signal_cal_idx)
        )
        net_return = visual.charts.safe_float(event.net_return)
        rows.append(
            {
                "event_id": str(event.event_id),
                "symbol": str(event.symbol),
                "sleeve": str(event.sleeve),
                "causal_industry": str(event.causal_industry),
                "anchor_date": pd.Timestamp(event.anchor_date),
                "anchor_idx": int(event.anchor_idx),
                "anchor_low": float(event.anchor_low),
                "base_ceiling": float(event.base_ceiling),
                "old_high_target": float(event.old_high),
                "signal_date": pd.Timestamp(event.signal_date),
                "signal_year": int(pd.Timestamp(event.signal_date).year),
                "signal_cal_idx": int(event.signal_cal_idx),
                "chart_number": 0,
                "same_date_signal_count": int(date_counts[pd.Timestamp(event.signal_date)]),
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
                "ret20": float(event.ret20),
                "ret60": float(event.ret60),
                "anchor_age_sessions": int(event.anchor_age_sessions),
                "turnover_before_signal": float(event.turnover_before_signal),
                "old_high_over_anchor_low": float(event.old_high_over_anchor_low),
                "target_headroom": float(event.target_headroom),
                "signal_step_return": float(event.step_return),
                "signal_close_location": float(event.close_location),
                "signal_turnover_ratio": (
                    float(event.turnover_fraction / event.prior20_median_turnover)
                    if float(event.prior20_median_turnover) > 0
                    else math.nan
                ),
                **features,
                "status": str(event.status),
                "entry_date": pd.Timestamp(event.entry_date),
                "entry_price": visual.charts.safe_float(event.entry_price),
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
        2,
        1,
        figsize=(13.2, 7.4),
        gridspec_kw={"height_ratios": [4.4, 1.0], "hspace": 0.05},
        sharex=True,
    )
    visual.charts.draw_candles(price_ax, frame, signal_close)
    signal_x = visual.charts.mdates.date2num(signal_date.to_pydatetime())
    anchor_x = visual.charts.mdates.date2num(anchor_date.to_pydatetime())
    price_ax.axvline(anchor_x, color="#dc2626", linewidth=1.0, linestyle="--", label="fresh 120D low")
    price_ax.axvline(signal_x, color="#7c3aed", linewidth=1.3, label="base resolution")
    price_ax.axhline(float(event.anchor_low) * 100 / signal_close, color="#dc2626", linewidth=0.8, linestyle=":", label="anchor low")
    price_ax.axhline(float(event.base_ceiling) * 100 / signal_close, color="#2563eb", linewidth=0.9, linestyle="--", label="frozen base ceiling")
    price_ax.axhline(float(event.old_high_target) * 100 / signal_close, color="#f97316", linewidth=0.9, linestyle="-.", label="old-high target")
    price_ax.axhline(100.0, color="#7c3aed", linewidth=0.6, linestyle=":")
    if pd.notna(event.entry_date) and math.isfinite(float(event.entry_price)):
        entry_x = visual.charts.mdates.date2num(pd.Timestamp(event.entry_date).to_pydatetime())
        price_ax.scatter(entry_x, float(event.entry_price) * 100 / signal_close, marker="^", s=62, color="#7b2cbf", zorder=8, label="entry")
    if pd.notna(event.exit_date) and math.isfinite(float(event.exit_price)):
        exit_x = visual.charts.mdates.date2num(pd.Timestamp(event.exit_date).to_pydatetime())
        price_ax.scatter(exit_x, float(event.exit_price) * 100 / signal_close, marker="v", s=62, color="#111111", zorder=8, label="exit")
    status = str(event.outcome_bucket)
    if math.isfinite(float(event.net_return)):
        status += f" | net {float(event.net_return):+.2%} | {event.exit_reason}"
    price_ax.set_title(
        f"{int(event.chart_number):04d} | {event.symbol} | {signal_date.date()} | {event.market_regime} | {status}\n"
        f"age {int(event.anchor_age_sessions)} | transferred {float(event.turnover_before_signal):.2f}x float | "
        f"base {float(event.base_width):.1%} | target room {float(event.target_headroom):.1%} | "
        f"mkt r20/r60 {float(event.market_median_ret20):+.1%}/{float(event.market_median_ret60):+.1%} | "
        f"breadth20/60 {float(event.market_positive_ret20_share):.0%}/{float(event.market_positive_ret60_share):.0%} | "
        f"same-date {int(event.same_date_signal_count)}",
        fontsize=9.1,
    )
    price_ax.set_ylabel("Coordinate price (signal close=100)")
    price_ax.grid(alpha=0.17, linewidth=0.5)
    handles, labels = price_ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    price_ax.legend(by_label.values(), by_label.keys(), loc="upper left", ncol=5, fontsize=6.5)
    valid_turn = frame.loc[frame.turnover_fraction.notna()].copy()
    turn_dates = visual.charts.mdates.date2num(pd.to_datetime(valid_turn.trade_date).to_numpy())
    volume_ax.bar(
        turn_dates,
        valid_turn.turnover_fraction * 100,
        width=0.75,
        color="#8b8b8b",
        alpha=0.55,
    )
    volume_ax.axvline(anchor_x, color="#dc2626", linewidth=0.8, linestyle="--")
    volume_ax.axvline(signal_x, color="#7c3aed", linewidth=1.0)
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
        dpi=105,
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
        "outcome_bucket": str(event.outcome_bucket),
        "market_regime": str(event.market_regime),
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
            subset = chart_index.loc[chart_index.outcome_bucket.eq(bucket)].sort_values(
                ["signal_date", "symbol", "event_id"], kind="mergesort"
            )
            outcome_sheets.extend(
                visual.build_nine_up(
                    subset, OUTCOME_SHEET_ROOT / bucket.lower(), bucket
                )
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
        "outcome_buckets": {
            str(key): int(value)
            for key, value in ledger.outcome_bucket.value_counts().items()
        },
        "market_state_counts": {
            str(key): int(value)
            for key, value in ledger.market_regime.value_counts().items()
        },
        "maximum_signal_date": str(candidates.signal_date.max().date()),
        "maximum_chart_bar_date": str(windows.trade_date.max().date()),
        "all_chronological_sheets_reviewed": False,
        "2022_2024_signal_feature_or_outcome_read": "NO",
        "cy011_read": "NO",
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
