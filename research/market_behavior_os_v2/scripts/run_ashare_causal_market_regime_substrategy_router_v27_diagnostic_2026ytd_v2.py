#!/usr/bin/env python3
"""Extend the frozen V27 2026 diagnostic through 2026-09-04.

The V27 signal identities required for a fully observed H20/H15 cohort were
already frozen in the 2026-08-12 Stage-A artifact.  With 17 later sessions, the
fixed 24-session maturity cutoff advances from 2026-07-09 to 2026-08-03.  This
runner therefore changes no signal rule: it extends exact execution state only
for the already-frozen candidate symbols and resolves the newly mature slow-lane
outcomes.  Signals after the new cutoff remain right-censored and are excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from research.market_behavior_os_v2.scripts import (
    run_ashare_causal_market_regime_substrategy_router_v27 as v27,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_distributed_accumulation_slow_exhaustion_mother_screen_v1 as slow,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1 as coordinate,
)


EXPERIMENT = (
    "ASHARE-CAUSAL-MARKET-REGIME-SUBSTRATEGY-ROUTER-"
    "V27-DIAGNOSTIC-2026YTD-V2"
)
ROOT = Path("/Volumes/quant/CY_quant_research")
SOURCE = ROOT / "ashare_causal_market_regime_substrategy_router_v27_validation_2026ytd_v1"
SOURCE_STAGE_A = SOURCE / "stage_a"
SOURCE_STAGE_B = SOURCE / "stage_b"
SOURCE_DAILY = SOURCE / "pit_daily_qd010_exact_2022_2026_08_12.parquet"
CY033_ROOT = Path(
    "/Users/linmei/Documents/CY/data/registered_inputs/"
    "CY-033-PIT-B-DAILY-2018-20260904-V1"
)
CY033_2026 = CY033_ROOT / "daily/partition_year=2026/data_0.parquet"
CY033_MANIFEST = CY033_ROOT / "asset_manifest.json"
V27_CONTRACT = Path(v27.CONTRACT)

OUT = ROOT / "ashare_causal_market_regime_substrategy_router_v27_validation_2026ytd_v2"
EXTENDED_DAILY = OUT / "execution_daily_frozen_symbols_through_2026_09_04.parquet"
SLOW_OUTCOMES = OUT / "slow_outcomes.parquet"
ROUTED_RAW = OUT / "routed_raw_trades.parquet"
ACCEPTED = OUT / "accepted_trades.parquet"
SKIPPED = OUT / "capacity_skips.parquet"
PORTFOLIO_NAV = OUT / "portfolio_nav.parquet"
RESULT = OUT / "result.json"
REPORT = OUT / "report.md"
MINUTE_AUDIT = OUT / "v27_minute_execution_audit.json"
MINUTE_CANDIDATES = OUT / "v27_candidate_symbols_64_1m_20260813_20260904.parquet"
MINUTE_EXECUTION = OUT / "v27_execution_relevant_1m_2026.parquet"
MINUTE_DETAILS = OUT / "v27_minute_execution_audit_details.parquet"

DATA_END = pd.Timestamp("2026-09-04")
SOURCE_END = pd.Timestamp("2026-08-12")
MATURITY_LAG = 24

EXPECTED = {
    "v27_contract": "8fdaf43e7d0f44cb5607fb1a37d4a12fefbf43cb1ededf334bc5bf474f0a20a7",
    "source_daily": "d092206b2c36212cf95ab0540bf6905a3274f1ba4706a50510e7cd24c9e1929c",
    "cy033_2026": "cbf898ccaf165310b511fdc7822b3370ce32cc0fd7d09c35a6d5ba0b38821fe8",
    "cy033_manifest": "95905858212f9a79a4f99ba8746fe47c66619ea5f4815eeeb4f0ead195219977",
    "fast_candidates": "213b1b315fb69ea895308300bb7c97cd8fc3c5df30f8ee1595b06dcef69b9667",
    "slow_candidates": "66c12b78adb10fa7e2a3861c71f77222128d9139b95bbbd7aadaf932097e316e",
    "bull_accelerating_candidates": "e250ae6f1cc841040dec15d0c359ec2d3261706e6e929a9f40da2c550390033e",
    "bull_decelerating_candidates": "5e08b7d024bda7a25183046ab2c1093a53473c658c600b44ca1c7c29d32289fa",
}

SOURCE_CANDIDATES = {
    "fast": SOURCE_STAGE_A / "fast_candidates.parquet",
    "slow": SOURCE_STAGE_A / "slow_candidates.parquet",
    "bull_accelerating": SOURCE_STAGE_A / "bull_accelerating_candidates.parquet",
    "bull_decelerating": SOURCE_STAGE_A / "bull_decelerating_candidates.parquet",
}
SOURCE_OUTCOMES = {
    "fast": SOURCE_STAGE_B / "fast_outcomes.parquet",
    "slow": SOURCE_STAGE_B / "slow_outcomes.parquet",
    "bull_accelerating": SOURCE_STAGE_B / "bull_accelerating_outcomes.parquet",
    "bull_decelerating": SOURCE_STAGE_B / "bull_decelerating_outcomes.parquet",
}


class DiagnosticError(RuntimeError):
    """Fail closed on frozen identity, lineage, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(
        f"COPY frame TO '{temporary.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()
    temporary.replace(path)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def verify_inputs() -> dict[str, str]:
    paths = {
        "v27_contract": V27_CONTRACT,
        "source_daily": SOURCE_DAILY,
        "cy033_2026": CY033_2026,
        "cy033_manifest": CY033_MANIFEST,
        **{f"{name}_candidates": path for name, path in SOURCE_CANDIDATES.items()},
    }
    actual: dict[str, str] = {}
    for name, path in paths.items():
        if not path.is_file():
            raise DiagnosticError(f"missing frozen input: {path}")
        actual[name] = sha256(path)
        if name in EXPECTED and actual[name] != EXPECTED[name]:
            raise DiagnosticError(
                f"frozen input drift for {name}: {actual[name]} != {EXPECTED[name]}"
            )
    source_result = json.loads((SOURCE_STAGE_B / "result.json").read_text())
    for name, path in SOURCE_OUTCOMES.items():
        expected = source_result["artifact_hashes"][f"{name}_outcomes.parquet"]
        actual[f"{name}_outcomes"] = sha256(path)
        if actual[f"{name}_outcomes"] != expected:
            raise DiagnosticError(f"frozen outcome drift for {name}")
    return actual


def candidate_symbols() -> list[str]:
    values: set[str] = set()
    for path in SOURCE_CANDIDATES.values():
        frame = pd.read_parquet(path, columns=["symbol"])
        values.update(frame.symbol.astype(str))
    return sorted(values)


def seed_states(symbols: list[str]) -> dict[str, dict[str, Any]]:
    registry = pd.DataFrame({"symbol": symbols})
    connection = duckdb.connect()
    connection.register("registry", registry)
    frame = connection.execute(
        f"""
        WITH last_row AS (
          SELECT d.symbol,d.coordinate_factor,d.invalid_step_cum,d.current_valid
          FROM read_parquet('{SOURCE_DAILY.as_posix()}') d
          JOIN registry r USING(symbol)
          WHERE d.trade_date<=TIMESTAMP '{SOURCE_END:%Y-%m-%d}'
          QUALIFY row_number() OVER(PARTITION BY d.symbol ORDER BY d.trade_date DESC)=1
        ), last_valid AS (
          SELECT d.symbol,d.close,d.coord_close
          FROM read_parquet('{SOURCE_DAILY.as_posix()}') d
          JOIN registry r USING(symbol)
          WHERE d.trade_date<=TIMESTAMP '{SOURCE_END:%Y-%m-%d}' AND d.current_valid
          QUALIFY row_number() OVER(PARTITION BY d.symbol ORDER BY d.trade_date DESC)=1
        )
        SELECT l.symbol,l.coordinate_factor AS factor,l.invalid_step_cum,
          l.current_valid AS previous_current_valid,
          v.close AS last_valid_raw_close,v.coord_close AS last_valid_coordinate_close
        FROM last_row l LEFT JOIN last_valid v USING(symbol)
        ORDER BY l.symbol
        """
    ).fetch_df()
    connection.close()
    if set(symbols) != set(frame.symbol.astype(str)):
        missing = sorted(set(symbols) - set(frame.symbol.astype(str)))
        raise DiagnosticError(f"frozen candidate lacks 2026-08-12 seed: {missing}")
    return {
        str(row.symbol): {
            "factor": float(row.factor),
            "invalid_step_cum": float(row.invalid_step_cum),
            "previous_current_valid": bool(row.previous_current_valid),
            "last_valid_raw_close": float(row.last_valid_raw_close),
            "last_valid_coordinate_close": float(row.last_valid_coordinate_close),
        }
        for row in frame.itertuples(index=False)
    }


def extend_execution_daily(symbols: list[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    registry = pd.DataFrame({"symbol": symbols})
    connection = duckdb.connect()
    connection.register("registry", registry)
    old = connection.execute(
        f"""
        SELECT d.* FROM read_parquet('{SOURCE_DAILY.as_posix()}') d
        JOIN registry r USING(symbol)
        WHERE year(d.trade_date)=2026 AND d.trade_date<=TIMESTAMP '{SOURCE_END:%Y-%m-%d}'
        ORDER BY d.symbol,d.trade_date
        """
    ).fetch_df()
    raw = connection.execute(
        f"""
        SELECT d.* EXCLUDE(partition_year) FROM read_parquet('{CY033_2026.as_posix()}') d
        JOIN registry r USING(symbol)
        WHERE d.trade_date>DATE '{SOURCE_END:%Y-%m-%d}'
          AND d.trade_date<=DATE '{DATA_END:%Y-%m-%d}'
        ORDER BY d.symbol,d.trade_date
        """
    ).fetch_df()
    old_calendar = connection.execute(
        f"""
        SELECT max(cal_idx)::BIGINT AS max_cal_idx,max(trade_date) AS max_date
        FROM read_parquet('{SOURCE_DAILY.as_posix()}')
        """
    ).fetchone()
    old_seq = connection.execute(
        f"""
        SELECT d.symbol,max(d.symbol_seq)::BIGINT AS max_symbol_seq
        FROM read_parquet('{SOURCE_DAILY.as_posix()}') d
        JOIN registry r USING(symbol) GROUP BY d.symbol
        """
    ).fetch_df()
    connection.close()

    if pd.Timestamp(old_calendar[1]).normalize() != SOURCE_END:
        raise DiagnosticError("source daily end drift")
    raw["trade_date"] = pd.to_datetime(raw.trade_date)
    old["trade_date"] = pd.to_datetime(old.trade_date)
    dates = pd.DataFrame(
        {"trade_date": sorted(pd.to_datetime(raw.trade_date.unique()))}
    )
    dates["cal_idx"] = np.arange(
        int(old_calendar[0]) + 1,
        int(old_calendar[0]) + 1 + len(dates),
        dtype=np.int64,
    )
    if len(dates) != 17 or pd.Timestamp(dates.trade_date.max()) != DATA_END:
        raise DiagnosticError(f"unexpected daily extension calendar: {dates}")

    rebuilt = coordinate.reconstruct_qd010_coordinate(
        raw, seed_states(symbols), dates
    )
    rebuilt = rebuilt.merge(old_seq, on="symbol", how="left", validate="many_to_one")
    rebuilt["symbol_seq"] = (
        rebuilt.max_symbol_seq.astype(np.int64)
        + rebuilt.groupby("symbol", sort=False).cumcount()
        + 1
    )
    rebuilt = rebuilt.drop(columns="max_symbol_seq")
    missing_columns = sorted(set(old.columns) - set(rebuilt.columns))
    if missing_columns:
        raise DiagnosticError(f"rebuilt extension missing columns: {missing_columns}")
    extension = rebuilt[list(old.columns)].copy()
    combined = pd.concat([old, extension], ignore_index=True)
    combined = combined.sort_values(["symbol", "trade_date"], kind="mergesort")
    if combined.duplicated(["symbol", "trade_date"]).any():
        raise DiagnosticError("extended execution daily has duplicate identity")
    if pd.Timestamp(combined.trade_date.max()) != DATA_END:
        raise DiagnosticError("extended execution daily does not reach data end")
    if extension.available_at.gt(extension.decision_at).any():
        raise DiagnosticError("extension contains post-decision source availability")
    write_parquet(combined, EXTENDED_DAILY)
    audit = {
        "symbols": len(symbols),
        "old_rows": len(old),
        "extension_rows": len(extension),
        "extension_sessions": len(dates),
        "extension_start": str(pd.Timestamp(dates.trade_date.min()).date()),
        "extension_end": str(pd.Timestamp(dates.trade_date.max()).date()),
        "extension_hard_valid_rows": int(extension.hard_valid.fillna(False).sum()),
        "extension_invalid_rows": int((~extension.hard_valid.fillna(False)).sum()),
        "max_cal_idx": int(dates.cal_idx.max()),
        "sha256": sha256(EXTENDED_DAILY),
    }
    return combined, audit


def compare_reproduced_old_slow(current: pd.DataFrame) -> dict[str, Any]:
    previous = pd.read_parquet(SOURCE_OUTCOMES["slow"])
    joined = previous.merge(
        current,
        on="event_id",
        how="left",
        suffixes=("_old", "_new"),
        validate="one_to_one",
        indicator=True,
    )
    missing = int(joined._merge.ne("both").sum())
    status = int(joined.status_old.ne(joined.status_new).sum())
    categorical = 0
    numeric = 0
    for name in ("entry_date", "exit_date", "exit_reason"):
        left = joined[f"{name}_old"].astype("string").fillna("__NA__")
        right = joined[f"{name}_new"].astype("string").fillna("__NA__")
        categorical += int(left.ne(right).sum())
    for name in (
        "entry_cal_idx",
        "entry_price",
        "exit_cal_idx",
        "exit_price",
        "holding_sessions",
        "gross_return",
        "net_return",
    ):
        left = pd.to_numeric(joined[f"{name}_old"], errors="coerce")
        right = pd.to_numeric(joined[f"{name}_new"], errors="coerce")
        equal = np.isclose(left, right, rtol=0.0, atol=1e-12, equal_nan=True)
        numeric += int((~equal).sum())
    audit = {
        "previous_rows": len(previous),
        "missing_reproduced_rows": missing,
        "status_mismatches": status,
        "categorical_mismatches": categorical,
        "numeric_mismatches": numeric,
    }
    if any(value for key, value in audit.items() if key != "previous_rows"):
        raise DiagnosticError(f"pre-existing slow outcome reproduction drift: {audit}")
    return audit


def replay_slow_mature(
    daily: pd.DataFrame, mature_cal_idx: int
) -> tuple[pd.DataFrame, dict[str, Any]]:
    candidates = pd.read_parquet(SOURCE_CANDIDATES["slow"])
    candidates["signal_date"] = pd.to_datetime(candidates.signal_date)
    mature = candidates.loc[candidates.signal_cal_idx.le(mature_cal_idx)].copy()
    groups = {
        str(symbol): part.sort_values("cal_idx", kind="mergesort")
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for candidate in mature.itertuples(index=False):
        path = groups[str(candidate.symbol)]
        path = path.loc[
            path.cal_idx.gt(int(candidate.signal_cal_idx))
            & path.cal_idx.le(int(candidate.signal_cal_idx) + 100)
        ].copy()
        rows.append(slow.replay_one(candidate, path))
    outcomes = pd.DataFrame(rows)
    for column in ("signal_date", "entry_date", "exit_date"):
        if column in outcomes:
            outcomes[column] = pd.to_datetime(outcomes[column])
    if len(outcomes) != len(mature) or outcomes.event_id.duplicated().any():
        raise DiagnosticError("slow outcome identity conservation failure")
    reproduction = compare_reproduced_old_slow(outcomes)
    incomplete = outcomes.status.eq("INCOMPLETE_PATH")
    if incomplete.any():
        raise DiagnosticError(
            "mature slow outcome remains incomplete: "
            + repr(outcomes.loc[incomplete, "event_id"].tolist())
        )
    write_parquet(outcomes, SLOW_OUTCOMES)
    audit = {
        "mature_candidates": len(mature),
        "newly_mature_candidates": int(
            (~mature.event_id.isin(pd.read_parquet(SOURCE_OUTCOMES["slow"]).event_id)).sum()
        ),
        "status_counts": outcomes.status.value_counts().astype(int).to_dict(),
        "reproduction": reproduction,
        "sha256": sha256(SLOW_OUTCOMES),
    }
    return outcomes, audit


def standardize_slow(
    outcomes: pd.DataFrame, candidates: pd.DataFrame
) -> pd.DataFrame:
    complete = outcomes.loc[outcomes.status.eq("COMPLETED")].copy()
    ranks = candidates[
        [
            "event_id",
            "previous5_downside_turnover",
            "last5_downside_turnover",
            "exact_prior20_return",
            "close_location",
        ]
    ]
    complete = complete.merge(ranks, on="event_id", how="left", validate="one_to_one")
    complete["lane"] = "BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION"
    complete["rank1"] = (
        complete.previous5_downside_turnover - complete.last5_downside_turnover
    )
    complete["rank2"] = -complete.exact_prior20_return
    complete["rank3"] = complete.close_location
    columns = list(pd.read_parquet(SOURCE_STAGE_B / "routed_raw_trades.parquet").columns)
    return complete[columns].copy()


def metric(frame: pd.DataFrame) -> dict[str, Any]:
    return v27.trade_metrics(frame)


def load_portfolio_paths_2026(
    trades: pd.DataFrame,
) -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    """Bind the frozen portfolio engine to the authorized 2026 calendar."""
    connection = duckdb.connect()
    connection.register(
        "trades",
        trades[["event_id", "symbol", "entry_date", "exit_date"]],
    )
    paths = connection.execute(
        f"""
        SELECT t.event_id,CAST(d.trade_date AS DATE) AS trade_date,
          d.coord_open,d.coord_close
        FROM trades t
        JOIN read_parquet('{EXTENDED_DAILY.as_posix()}') d
          ON t.symbol=d.symbol
         AND CAST(d.trade_date AS DATE)
             BETWEEN CAST(t.entry_date AS DATE) AND CAST(t.exit_date AS DATE)
        """
    ).fetch_df()
    calendar = connection.execute(
        f"""
        SELECT DISTINCT CAST(trade_date AS DATE) AS trade_date
        FROM read_parquet('{EXTENDED_DAILY.as_posix()}')
        WHERE year(trade_date)=2026 AND trade_date<=DATE '{DATA_END:%Y-%m-%d}'
        ORDER BY trade_date
        """
    ).fetch_df()
    connection.close()
    paths["trade_date"] = pd.to_datetime(paths.trade_date)
    dates = [pd.Timestamp(value) for value in pd.to_datetime(calendar.trade_date)]
    return paths, dates


def annual_portfolio_2026(nav: pd.DataFrame) -> list[dict[str, Any]]:
    drawdown = nav.combined_nav / nav.combined_nav.cummax() - 1.0
    daily_std = float(nav.ret.std(ddof=1))
    sharpe = (
        None
        if daily_std == 0
        else float(nav.ret.mean() / daily_std * np.sqrt(242.0))
    )
    return [
        {
            "year": 2026,
            "return": float(nav.combined_nav.iloc[-1] / nav.combined_nav.iloc[0] - 1.0),
            "max_drawdown": float(drawdown.min()),
            "sharpe": sharpe,
            "average_utilization": float(nav.utilization.mean()),
            "max_active_positions": int(nav.active_positions.max()),
        }
    ]


def render_report(result: dict[str, Any]) -> None:
    old = result["comparison_to_2026_08_12"]
    now = result["overall"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Data through {result['authorized_data_end']}; frozen maturity cutoff {result['mature_signal_cutoff']}.",
        "",
        "|Snapshot|Trades|Mean net|Median net|Win|Target hit|Severe10|Mean hold|Portfolio|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"|Through 2026-08-12|{old['trades']}|{old['mean_net']:.2%}|{old['median_net']:.2%}|{old['win_rate']:.2%}|{old['target_hit']:.2%}|{old['severe10']:.2%}|{old['average_holding_sessions']:.2f}|{result['previous_portfolio_return']:.2%}|",
        f"|Through 2026-09-04|{now['trades']}|{now['mean_net']:.2%}|{now['median_net']:.2%}|{now['win_rate']:.2%}|{now['target_hit']:.2%}|{now['severe10']:.2%}|{now['average_holding_sessions']:.2f}|{result['portfolio']['total_return']:.2%}|",
        "",
        "## Lanes",
        "",
        "|Lane|Trades|Mean net|Median net|Win|Target hit|Severe10|Mean hold|",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in result["lanes"].items():
        lines.append(
            f"|{name}|{item['trades']}|{item['mean_net']:.2%}|{item['median_net']:.2%}|{item['win_rate']:.2%}|{item['target_hit']:.2%}|{item['severe10']:.2%}|{item['average_holding_sessions']:.2f}|"
        )
    minute = result.get("minute_execution_audit")
    if minute:
        execution = minute["execution"]
        candidate = minute["candidate_daily_crosscheck"]
        lines += [
            "",
            "## Exact one-minute execution audit",
            "",
            f"Execution status: {execution['status']}; {execution['trades']} trades, "
            f"{execution['entry_open_pass']} entry opens passed, "
            f"{execution['exit_fill_pass']} exits were executable, and "
            f"{execution['failures']} execution failures were found.",
            "",
            f"All {candidate['matched_daily_rows']} / {candidate['eligible_daily_rows']} "
            "tradable candidate-days have minute bars. Auxiliary cross-vendor "
            f"comparison recorded {candidate['price_or_bar_count_issues']} price/bar-count, "
            f"{candidate['volume_issues']} volume, and {candidate['amount_issues']} amount "
            "differences; these did not alter signals or execution prices.",
        ]
    lines += [
        "",
        "## Governance",
        "",
        "No V27 rule or threshold was changed. The 2026-08-12 Stage-A candidate identities were reused. Only candidates with signal_cal_idx <= max_cal_idx-24 were evaluated; later signals remain right-censored.",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def run() -> dict[str, Any]:
    input_hashes = verify_inputs()
    symbols = candidate_symbols()
    daily, daily_audit = extend_execution_daily(symbols)
    max_cal_idx = int(daily.cal_idx.max())
    mature_cal_idx = max_cal_idx - MATURITY_LAG
    cutoff_rows = daily.loc[daily.cal_idx.eq(mature_cal_idx), "trade_date"].drop_duplicates()
    if len(cutoff_rows) != 1:
        raise DiagnosticError("maturity cutoff is not one global session")
    mature_date = pd.Timestamp(cutoff_rows.iloc[0]).normalize()
    if mature_date != pd.Timestamp("2026-08-03"):
        raise DiagnosticError(f"unexpected maturity cutoff: {mature_date}")

    slow_outcomes, slow_audit = replay_slow_mature(daily, mature_cal_idx)
    previous_raw = pd.read_parquet(SOURCE_STAGE_B / "routed_raw_trades.parquet")
    previous_raw["signal_date"] = pd.to_datetime(previous_raw.signal_date)
    slow_candidates = pd.read_parquet(SOURCE_CANDIDATES["slow"])
    slow_standard = standardize_slow(slow_outcomes, slow_candidates)
    raw = pd.concat(
        [
            previous_raw.loc[
                ~previous_raw.lane.eq("BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION")
            ],
            slow_standard,
        ],
        ignore_index=True,
    ).sort_values(["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort")
    if raw.event_id.duplicated().any() or raw.duplicated(["symbol", "signal_date"]).any():
        raise DiagnosticError("routed raw identity duplication")
    accepted, skipped, capacity = v27.apply_shared_capacity(raw)
    accepted = accepted.sort_values(
        ["entry_date", "sleeve", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    old_portfolio_daily = v27.v13.DAILY
    old_portfolio_loader = v27.v13.load_paths
    try:
        v27.v13.DAILY = EXTENDED_DAILY
        v27.v13.load_paths = load_portfolio_paths_2026
        nav, portfolio_audit = v27.replay_portfolio(accepted)
    finally:
        v27.v13.DAILY = old_portfolio_daily
        v27.v13.load_paths = old_portfolio_loader

    old_daily = v27.DAILY
    try:
        v27.DAILY = EXTENDED_DAILY
        execution = v27.execution_audit(accepted)
    finally:
        v27.DAILY = old_daily
    blocking = {
        **{key: value for key, value in execution.items() if int(value) != 0},
        **{
            key: value
            for key, value in portfolio_audit.items()
            if key in {"negative_cash_count", "open_position_at_end_count"}
            and int(value) != 0
        },
    }
    if blocking:
        raise DiagnosticError(f"execution/portfolio audit failed: {blocking}")

    write_parquet(slow_outcomes, SLOW_OUTCOMES)
    write_parquet(raw, ROUTED_RAW)
    write_parquet(accepted, ACCEPTED)
    write_parquet(skipped, SKIPPED)
    write_parquet(nav, PORTFOLIO_NAV)
    previous = json.loads((SOURCE_STAGE_B / "result.json").read_text())
    overall = metric(accepted)
    lanes = {
        str(name): metric(part) for name, part in accepted.groupby("lane", sort=True)
    }
    boards = {
        str(name): metric(part) for name, part in accepted.groupby("sleeve", sort=True)
    }
    portfolio = v27.v13.nav_metrics(nav)
    annual_portfolio = annual_portfolio_2026(nav)
    minute_audit = None
    if MINUTE_AUDIT.is_file():
        minute_payload = json.loads(MINUTE_AUDIT.read_text(encoding="utf-8"))
        minute_audit = {
            "audit_status": minute_payload["status"],
            "audit_id": minute_payload["audit_id"],
            "path": str(MINUTE_AUDIT),
            "sha256": sha256(MINUTE_AUDIT),
            "execution": minute_payload["execution"],
            "candidate_full_rows": minute_payload["qmt"]["candidate_full_rows"],
            "candidate_daily_crosscheck": minute_payload["qmt"]["daily_crosscheck"],
        }
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "FROZEN_V27_2026_YTD_POST_OBSERVATION_DIAGNOSTIC",
        "authorized_data_end": str(DATA_END.date()),
        "mature_signal_cutoff": str(mature_date.date()),
        "mature_signal_cal_idx": mature_cal_idx,
        "fixed_maturity_lag_sessions": MATURITY_LAG,
        "overall": overall,
        "lanes": lanes,
        "boards": boards,
        "portfolio": portfolio,
        "annual_portfolio": annual_portfolio,
        "minute_execution_audit": minute_audit,
        "comparison_to_2026_08_12": previous["overall"],
        "previous_portfolio_return": previous["portfolio"]["total_return"],
        "candidate_counts": {
            name: {
                "frozen": int(len(pd.read_parquet(path))),
                "mature": int(
                    pd.read_parquet(path).signal_cal_idx.le(mature_cal_idx).sum()
                ),
            }
            for name, path in SOURCE_CANDIDATES.items()
        },
        "slow_outcome_audit": slow_audit,
        "daily_extension_audit": daily_audit,
        "capacity_audit": capacity,
        "portfolio_audit": portfolio_audit,
        "execution_audit": execution,
        "governance": {
            "source_candidate_identity_changed": False,
            "parameter_selection_on_2026_count": 0,
            "rule_changed_after_open": False,
            "signal_after_maturity_cutoff_count": 0,
            "right_censored_candidates_excluded": True,
            "minute_execution_crosscheck": (
                "PENDING_SEPARATE_EXACT_1M_AUDIT"
                if minute_audit is None
                else f"{minute_audit['execution']['status']}_62_OF_62"
            ),
        },
        "input_hashes": input_hashes,
        "artifact_hashes": {
            path.name: sha256(path)
            for path in (
                EXTENDED_DAILY,
                SLOW_OUTCOMES,
                ROUTED_RAW,
                ACCEPTED,
                SKIPPED,
                PORTFOLIO_NAV,
                *(
                    (MINUTE_AUDIT, MINUTE_CANDIDATES, MINUTE_EXECUTION, MINUTE_DETAILS)
                    if MINUTE_AUDIT.is_file()
                    else ()
                ),
            )
        },
    }
    write_json(RESULT, result)
    render_report(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("choose --run")
    print(json.dumps(run(), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
