#!/usr/bin/env python3
"""Screen the frozen causal BEAR plus STRONG_BULL dual-engine hypothesis."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-CAUSAL-BEAR-STRONG-BULL-DUAL-ENGINE-V17"
CONTRACT = OS_ROOT / f"experiments/{EXPERIMENT}_contract.json"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_development_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_development_report.md"
BEAR = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bear_fast_capitulation_active_demand_v10/stage_b/accepted_trades.parquet"
)
BULL = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bull_quiet_inventory_three_session_acceptance_v2/"
    "development_2014_2020/outcomes.parquet"
)
REGIME = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_routed_simple_strategy_v1/"
    "stage_a/causal_market_regime_2014_2023.parquet"
)
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_bear_strong_bull_dual_engine_v17/development_2014_2020"
)
TRADE_LEDGER = EXT_ROOT / "combined_trade_ledger.parquet"
MANIFEST = EXT_ROOT / "manifest.json"

EXPECTED_HASHES = {
    "contract": "5bcca65c12fb590137a45e454e309f79b70a1a79cfa3fff51124246d3a809b7c",
    "bear": "d4e3c43e64ddae0b81c93b802ceb9cc7b674defd87d18ecb2c01d09b387b5835",
    "bull": "c8db4e5a73b3e5e666f89a965372820d3db3fc814faff3b8f878dc3f6d88164a",
    "regime": "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}


class ExperimentError(RuntimeError):
    """Fail closed when a frozen input or causal invariant drifts."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(
        f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()


def verify_inputs() -> dict[str, str]:
    paths = {"contract": CONTRACT, "bear": BEAR, "bull": BULL, "regime": REGIME}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise ExperimentError(f"missing frozen input: {missing}")
    actual = {name: sha256(path) for name, path in paths.items()}
    drift = {
        name: {"expected": EXPECTED_HASHES[name], "actual": value}
        for name, value in actual.items()
        if value != EXPECTED_HASHES[name]
    }
    if drift:
        raise ExperimentError(f"frozen input drift: {drift}")
    return actual


def load_trades() -> tuple[pd.DataFrame, dict[str, Any]]:
    connection = duckdb.connect()
    bear = connection.execute(
        f"""
        SELECT event_id,symbol,sleeve,signal_date,entry_date,entry_cal_idx,
          entry_price,exit_date,exit_cal_idx,exit_price,exit_reason,
          holding_sessions,gross_return,net_return,
          signal_decision_at AS state_source_timestamp
        FROM read_parquet('{BEAR.as_posix()}')
        WHERE signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
          AND status='COMPLETED'
        ORDER BY signal_date,sleeve,symbol,event_id
        """
    ).fetch_df()
    bear["engine"] = "BEAR_FAST_CAPITULATION_ACTIVE_DEMAND"
    bear["market_route"] = "BEAR"

    bull = connection.execute(
        f"""
        SELECT b.event_id,b.symbol,b.sleeve,b.signal_date,b.entry_date,b.entry_cal_idx,
          b.entry_price,b.exit_date,b.exit_cal_idx,b.exit_price,b.exit_reason,
          b.holding_sessions,b.gross_return,b.net_return,
          r.latest_source_timestamp AS state_source_timestamp,
          r.market_regime,r.market_median_ret20,r.market_positive_ret20_share,
          r.market_median_ret60,r.market_positive_ret60_share
        FROM read_parquet('{BULL.as_posix()}') b
        JOIN read_parquet('{REGIME.as_posix()}') r
          ON b.signal_date=r.trade_date
        WHERE b.signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
          AND b.status='COMPLETED' AND b.accepted
          AND r.market_regime='BULL'
          AND r.market_median_ret60>=0.05
          AND r.market_positive_ret60_share>=0.60
        ORDER BY b.signal_date,b.sleeve,b.symbol,b.event_id
        """
    ).fetch_df()
    connection.close()
    bull["engine"] = "STRONG_BULL_QUIET_INVENTORY_ACCEPTANCE"
    bull["market_route"] = "STRONG_BULL"
    columns = [
        "event_id",
        "symbol",
        "sleeve",
        "signal_date",
        "entry_date",
        "entry_cal_idx",
        "entry_price",
        "exit_date",
        "exit_cal_idx",
        "exit_price",
        "exit_reason",
        "holding_sessions",
        "gross_return",
        "net_return",
        "state_source_timestamp",
        "engine",
        "market_route",
    ]
    frame = pd.concat([bear[columns], bull[columns]], ignore_index=True)
    for column in ("signal_date", "entry_date", "exit_date", "state_source_timestamp"):
        frame[column] = pd.to_datetime(frame[column])
    if frame.event_id.duplicated().any():
        raise ExperimentError("duplicate cross-engine event identity")
    causal_audit = {
        "state_source_after_signal_count": int(
            frame.state_source_timestamp.gt(
                frame.signal_date + pd.Timedelta(hours=15)
            ).sum()
        ),
        "entry_at_or_before_signal_count": int(
            frame.entry_date.le(frame.signal_date).sum()
        ),
        "exit_at_or_before_entry_count": int(
            frame.exit_cal_idx.le(frame.entry_cal_idx).sum()
        ),
        "post_2020_signal_count": int(frame.signal_date.dt.year.gt(2020).sum()),
    }
    if any(causal_audit.values()):
        raise ExperimentError(f"causal audit failed: {causal_audit}")
    return frame.sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True), causal_audit


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    values = pd.to_numeric(frame.net_return, errors="coerce")
    return {
        "trades": int(len(frame)),
        "mean_net": None if frame.empty else float(values.mean()),
        "median_net": None if frame.empty else float(values.median()),
        "win_rate": None if frame.empty else float(values.gt(0).mean()),
        "severe10": None if frame.empty else float(values.le(-0.10).mean()),
        "target_hit": None
        if frame.empty
        else float(frame.exit_reason.eq("TARGET_20").mean()),
        "mean_holding_sessions": None
        if frame.empty
        else float(frame.holding_sessions.mean()),
        "signal_dates": int(frame.signal_date.nunique()),
    }


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    yearly = {
        str(year): metrics(frame.loc[frame.signal_date.dt.year.eq(year)])
        for year in range(2014, 2021)
    }
    engines = {
        str(engine): metrics(part)
        for engine, part in frame.groupby("engine", sort=True)
    }
    pooled = metrics(frame)
    gate = {
        "completed_per_year_gt_50": pooled["trades"] / 7.0 > 50,
        "pooled_mean_net_gt_4pct": pooled["mean_net"] is not None
        and pooled["mean_net"] > 0.04,
        "pooled_median_net_positive": pooled["median_net"] is not None
        and pooled["median_net"] > 0,
        "every_calendar_year_mean_positive": all(
            item["trades"] > 0
            and item["mean_net"] is not None
            and item["mean_net"] > 0
            for item in yearly.values()
        ),
        "severe10_le_20pct": pooled["severe10"] is not None
        and pooled["severe10"] <= 0.20,
    }
    return {
        "pooled": pooled,
        "completed_per_year": pooled["trades"] / 7.0,
        "yearly": yearly,
        "engines": engines,
        "gate": gate,
    }


def render_report(result: dict[str, Any]) -> None:
    summary = result["development_2014_2020"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"`{result['verdict']}`",
        "",
        "## Simple routed strategy",
        "",
        "1. In causal BEAR, trade the frozen fast-capitulation active-demand engine only when breadth is improving.",
        "2. In causal STRONG_BULL, require median stock ret60 >=5% and positive-ret60 breadth >=60%, then trade the frozen quiet-inventory breakout only after its third-session platform acceptance.",
        "3. In weak BULL and TRANSITION, hold cash.",
        "4. Both engines enter only at a later legal open, target +20%, time-exit after H60, use no stop, and charge 40 bp round trip.",
        "",
        "Every state input is known at or before the relevant completed decision close. No future return labels the market state.",
        "",
        "## Development 2014-2020",
        "",
        f"Trades {summary['pooled']['trades']} ({summary['completed_per_year']:.1f}/year); mean {summary['pooled']['mean_net']:.2%}; median {summary['pooled']['median_net']:.2%}; win {summary['pooled']['win_rate']:.2%}; severe10 {summary['pooled']['severe10']:.2%}.",
        "",
        "|Year|Trades|Mean net|Median net|Win|Severe10|",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for year in range(2014, 2021):
        item = summary["yearly"][str(year)]
        lines.append(
            f"|{year}|{item['trades']}|{item['mean_net']:.2%}|{item['median_net']:.2%}|{item['win_rate']:.2%}|{item['severe10']:.2%}|"
        )
    lines += [
        "",
        "## Scientific status",
        "",
        "This is a post-hoc development combination. It can authorize an outcome-blind 2024 identity freeze, but cannot itself be called independent confirmation.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    frame, audit = load_trades()
    write_parquet(frame, TRADE_LEDGER)
    development = summarize(frame)
    result = {
        "experiment": EXPERIMENT,
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "development_2014_2020": development,
        "causal_audit": audit,
        "combined_trade_ledger_sha256": sha256(TRADE_LEDGER),
        "post_2020_signal_outcome_read": "NO",
        "verdict": (
            "DUAL_ENGINE_PASSES_DEVELOPMENT_GATE"
            if all(development["gate"].values())
            else "DUAL_ENGINE_FAILS_DEVELOPMENT_GATE"
        ),
    }
    write_json(RESULT, result)
    render_report(result)
    manifest = {
        **result,
        "result_sha256": sha256(RESULT),
        "report_sha256": sha256(REPORT),
    }
    write_json(MANIFEST, manifest)
    return manifest


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True, indent=2, default=str))
