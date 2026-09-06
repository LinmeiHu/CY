#!/usr/bin/env python3
"""Render every frozen long-suspension reopening mother event."""

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
import run_ashare_first_active_demand_takeover_after_weakness_12m_chart_discovery_v1 as visual


EXPERIMENT = "ASHARE-LONG-SUSPENSION-REOPENING-PRICE-DISCOVERY-MOTHER-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_long_suspension_reopening_price_discovery_mother_v1_stage_a.py"
)
STAGE_B_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_long_suspension_reopening_price_discovery_mother_v1_stage_b.py"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_long_suspension_reopening_price_discovery_mother_v1"
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
    SPEC: "25f9ea72762bb092df739c7ca4bba7bfca2d7d68083f420ee12c0756200d8365",
    STAGE_A_RUNNER: "3183213e9249a48d9c6aed0d291498d8ee890e2e0d9e1cc374f5361ef16ad9cc",
    STAGE_B_RUNNER: "659182d6072a457c4b374239b33faf406eed7a949f6a29fa4ca9d6bd273bfa5a",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    STAGE_A_FREEZE: "8df2281f1f6f1761043e4e58a390501503d044d32ac0b44e265c9a8b6b33f1b7",
    CANDIDATES: "0f29af9f2b747a9650c9593da15a6f49c82a2a5984ec6d9c2f3da0610ecdae35",
    PATHS: "bcfe149df26aa4a06672d6bb6e8a8d45b36b9ab7f8956ab84805215eb6649a26",
    OUTCOMES: "7fb637bb2deae3486fe3fa832c1303d8cea2bb4b65649e16e789eed675236b98",
    STAGE_B_MANIFEST: "7e21b27bc4496931061f044986123d03458acc554a04f4557c60a368d97f74b1",
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
        "pre_suspension_trade_date",
        "signal_date",
        "decision_at",
        "available_at",
        "market_latest_source_timestamp",
    ):
        candidates[column] = pd.to_datetime(candidates[column])
    for column in ("pre_suspension_trade_date", "signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    if len(candidates) != 4459 or candidates.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    if len(outcomes) != 4459 or outcomes.event_id.duplicated().any():
        raise ResearchError("outcome-label identity drift")
    con = duckdb.connect()
    con.register(
        "chart_keys",
        candidates[
            [
                "event_id",
                "symbol",
                "pre_suspension_cal_idx",
                "signal_cal_idx",
                "signal_date",
            ]
        ],
    )
    windows = con.execute(
        f"""
        SELECT k.event_id,k.signal_date,d.symbol,d.trade_date,d.cal_idx,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.turnover_fraction,
          d.step_return,d.trade_status,d.current_day_data_tradable,
          d.current_valid,d.hard_valid,d.available_at,d.decision_at
        FROM read_parquet('{DAILY.as_posix()}') d
        JOIN chart_keys k ON d.symbol=k.symbol
          AND d.cal_idx BETWEEN k.pre_suspension_cal_idx-126 AND k.signal_cal_idx+126
        WHERE d.trade_date<=DATE '2021-06-30'
        ORDER BY k.event_id,d.cal_idx
        """
    ).fetch_df()
    con.close()
    for column in ("signal_date", "trade_date", "available_at", "decision_at"):
        windows[column] = pd.to_datetime(windows[column])
    if windows.event_id.nunique() != 4459:
        raise ResearchError("chart window misses an event")
    if windows.trade_date.max() > pd.Timestamp("2021-06-30"):
        raise ResearchError("chart context crossed the frozen cap")
    latest = candidates[["available_at", "market_latest_source_timestamp"]].max(axis=1)
    if latest.gt(candidates.decision_at).any():
        raise ResearchError("a chart annotation arrived after the signal decision")
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
    outcome_lookup = {str(row.event_id): row for row in outcomes.itertuples(index=False)}
    window_lookup = {key: part for key, part in windows.groupby("event_id", sort=False)}
    rows: list[dict[str, Any]] = []
    for event in candidates.sort_values(
        ["signal_date", "symbol", "event_id"], kind="mergesort"
    ).itertuples(index=False):
        frame = window_lookup[str(event.event_id)]
        valid = frame.loc[
            frame.current_valid.fillna(False)
            & frame[["coord_open", "coord_high", "coord_low", "coord_close"]]
            .notna()
            .all(axis=1)
        ].sort_values("cal_idx", kind="mergesort")
        pre = valid.loc[valid.cal_idx.lt(int(event.signal_cal_idx))].tail(126)
        signal = valid.loc[valid.cal_idx.eq(int(event.signal_cal_idx))]
        # The 126-session chart window deliberately includes the non-trading
        # suspension gap, so it need not contain 125 valid candles.
        if pre.empty or len(signal) != 1:
            raise ResearchError(f"{event.event_id}: incomplete causal chart history")
        signal_close = float(signal.iloc[0].coord_close)
        prior_high = float(pre.coord_high.max())
        prior_low = float(pre.coord_low.min())
        outcome = outcome_lookup[str(event.event_id)]
        net_return = visual.charts.safe_float(outcome.net_return)
        rows.append(
            {
                "event_id": str(event.event_id),
                "symbol": str(event.symbol),
                "sleeve": str(event.sleeve),
                "causal_industry": str(event.causal_industry),
                "pre_suspension_trade_date": pd.Timestamp(event.pre_suspension_trade_date),
                "pre_suspension_close": float(event.pre_suspension_close),
                "suspension_market_sessions": int(event.suspension_market_sessions),
                "signal_date": pd.Timestamp(event.signal_date),
                "signal_year": int(pd.Timestamp(event.signal_date).year),
                "signal_cal_idx": int(event.signal_cal_idx),
                "chart_number": 0,
                "market_regime": str(event.market_regime),
                "market_median_ret20": float(event.market_median_ret20),
                "market_median_ret60": float(event.market_median_ret60),
                "market_positive_ret20_share": float(event.market_positive_ret20_share),
                "market_positive_ret60_share": float(event.market_positive_ret60_share),
                "reopening_open_return": float(event.reopening_open_return),
                "reopening_close_return": float(event.reopening_close_return),
                "close_location": visual.charts.safe_float(event.close_location),
                "ret20": visual.charts.safe_float(event.ret20),
                "ret60": visual.charts.safe_float(event.ret60),
                "pre126_return": signal_close / float(pre.coord_close.iloc[0]) - 1,
                "pre126_position": (
                    (signal_close - prior_low) / (prior_high - prior_low)
                    if prior_high > prior_low
                    else math.nan
                ),
                "status": str(outcome.status),
                "entry_date": pd.Timestamp(outcome.entry_date),
                "entry_price": visual.charts.safe_float(outcome.entry_price),
                "exit_date": pd.Timestamp(outcome.exit_date),
                "exit_price": visual.charts.safe_float(outcome.exit_price),
                "exit_reason": str(outcome.exit_reason),
                "holding_sessions": visual.charts.safe_float(outcome.holding_sessions),
                "net_return": net_return,
                "outcome_bucket": outcome_bucket(str(outcome.status), net_return),
            }
        )
    ledger = pd.DataFrame(rows)
    ledger["chart_number"] = np.arange(1, len(ledger) + 1, dtype=int)
    return ledger


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
    pre_date = pd.Timestamp(event.pre_suspension_trade_date)
    pre_x = visual.charts.mdates.date2num(pre_date.to_pydatetime())
    price_ax.axvline(pre_x, color="#64748b", linewidth=1.0, linestyle=":", label="last trade")
    price_ax.axvline(signal_x, color="#b45309", linewidth=1.4, label="reopen signal")
    price_ax.axhline(
        float(event.pre_suspension_close) * 100 / signal_close,
        color="#475569",
        linewidth=0.8,
        linestyle="--",
        label="pre-susp close",
    )
    if pd.notna(event.entry_date) and math.isfinite(float(event.entry_price)):
        entry_x = visual.charts.mdates.date2num(pd.Timestamp(event.entry_date).to_pydatetime())
        price_ax.scatter(
            entry_x,
            float(event.entry_price) * 100 / signal_close,
            marker="^",
            s=65,
            color="#7b2cbf",
            zorder=8,
            label="entry",
        )
    if pd.notna(event.exit_date) and math.isfinite(float(event.exit_price)):
        exit_x = visual.charts.mdates.date2num(pd.Timestamp(event.exit_date).to_pydatetime())
        price_ax.scatter(
            exit_x,
            float(event.exit_price) * 100 / signal_close,
            marker="v",
            s=65,
            color="#111111",
            zorder=8,
            label="H20 exit",
        )
    status = str(event.outcome_bucket)
    if math.isfinite(float(event.net_return)):
        status += f" | net {float(event.net_return):+.2%}"
    close_loc = (
        f"{float(event.close_location):.0%}"
        if math.isfinite(float(event.close_location))
        else "NA"
    )
    price_ax.set_title(
        f"{int(event.chart_number):04d} | {event.symbol} | {signal_date.date()} | "
        f"{event.market_regime} | {status}\n"
        f"suspended {int(event.suspension_market_sessions)} market sessions | "
        f"reopen O/C {float(event.reopening_open_return):+.1%}/"
        f"{float(event.reopening_close_return):+.1%} | close loc {close_loc} | "
        f"r20/r60 {float(event.ret20):+.1%}/{float(event.ret60):+.1%}",
        fontsize=9.8,
    )
    price_ax.set_ylabel("Coordinate price (reopen close=100)")
    price_ax.grid(alpha=0.17, linewidth=0.5)
    handles, labels = price_ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    price_ax.legend(by_label.values(), by_label.keys(), loc="upper left", ncol=5, fontsize=7)
    valid_turn = frame.loc[frame.turnover_fraction.notna()].copy()
    turn_dates = visual.charts.mdates.date2num(pd.to_datetime(valid_turn.trade_date).to_numpy())
    volume_ax.bar(
        turn_dates,
        valid_turn.turnover_fraction * 100,
        width=0.75,
        color="#8b8b8b",
        alpha=0.55,
    )
    volume_ax.axvline(pre_x, color="#64748b", linewidth=0.8, linestyle=":")
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
                visual.build_nine_up(subset, OUTCOME_SHEET_ROOT / bucket.lower(), bucket)
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
        "outcome_buckets": {
            str(key): int(value) for key, value in ledger.outcome_bucket.value_counts().items()
        },
        "maximum_signal_date": str(candidates.signal_date.max().date()),
        "maximum_chart_bar_date": str(windows.trade_date.max().date()),
        "all_chronological_sheets_reviewed": False,
        "post_2021_06_signal_or_rule_read": "NO",
        "2022_2024_signal_or_outcome_read": "NO",
        "future_market_function": False,
        "next_step": "REVIEW_ALL_CHRONOLOGICAL_AND_OUTCOME_SHEETS_BEFORE_RULE_FREEZE",
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
