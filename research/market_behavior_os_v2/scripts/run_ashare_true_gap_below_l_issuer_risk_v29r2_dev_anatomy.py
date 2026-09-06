#!/usr/bin/env python3
"""Render a strictly <=2021 anatomy corpus for the frozen V29R1 veto.

This is a post-hoc diagnostic, not a selector or classifier revision.  It keeps
the 2022+ validation title and return partitions closed and labels every
post-signal observation as descriptive evidence only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import duckdb
import matplotlib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image, ImageDraw

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Rectangle

EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-ISSUER-RISK-V29R2-DEVELOPMENT-ANATOMY-V1"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
V29_STAGE_A = OS_ROOT / (
    "artifacts/ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-"
    "ISSUER-INTEGRITY-COOLDOWN-V29R1_stage_a_freeze.json"
)
V29_RESULT = OS_ROOT / (
    "artifacts/ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-"
    "ISSUER-INTEGRITY-COOLDOWN-V29R1_development_result.json"
)
V29_PREREG = OS_ROOT / (
    "experiments/ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-"
    "ISSUER-INTEGRITY-COOLDOWN-V29R1_preregistration.json"
)

V29_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_orderly_demand_issuer_integrity_cooldown_v29r1/"
    "development"
)
REJECTED = V29_ROOT / "issuer_integrity_rejected_entries.parquet"
CLASSIFIED = V29_ROOT / "issuer_integrity_classified_events.parquet"
V29_ACCEPTED = V29_ROOT / "issuer_integrity/portfolio_accepted.parquet"
V28_ACCEPTED = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_orderly_demand_v28r2/development/"
    "orderly_demand/portfolio_accepted.parquet"
)
PARENT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_first_reversal_v13/"
    "prior_high_reversal/development"
)
PARENT_OUTCOMES = PARENT / "outcomes.parquet"
PARENT_DAILY = PARENT / "outcome_daily.parquet"
VAP = PARENT / "vap_profiles.parquet"

CY006_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
CY008_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-008-pit-b-minute-v2-2018-2026-20260821.json"
)
CY009_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-009-chip-state-features-v2-2018-2026-20260821.json"
)

YEARS = (2018, 2019, 2020, 2021)
CY006_FILES = [
    Path(
        "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/"
        f"daily/partition_year={year}/data_0.parquet"
    )
    for year in YEARS
]
CY008_FILES = [
    Path(
        "/Users/linmei/Documents/CY/data/processed/pit_b_minute_2018_2026_v2/"
        f"execution_5m/partition_year={year}/data_0.parquet"
    )
    for year in YEARS
]
CY009_FILES = [
    Path(
        "/Users/linmei/Documents/CY/data/processed/"
        f"chip_state_features_by_year_2018_2026_v2/year={year}/data.parquet"
    )
    for year in YEARS
]

EXPECTED_HASHES = {
    SPEC: "33669fbf62d7eeae796e6e7cf5755ba1079c281c495b57da42d63d60c6fd0da8",
    V29_STAGE_A: "a73d30f7f254557bf9c13b54756e1b5277bf1099f6bd33d161ac734af4f0dc7e",
    V29_RESULT: "b3da693163d0521a01107caf8d75532fd40c21c220c79ce0e2424809995e6cb5",
    V29_PREREG: "583e35cf4722daf569feec8bc64118cf430aa5b278b4c7149d6147ef79504b34",
    REJECTED: "0d8ce59c8cfbd479aa772ded90e4273b5e5808d34150417031b3d5c65e61bf06",
    CLASSIFIED: "183370ff9223c6dac78244e9ca3ffe68616bfb392ad8053f796099bf14fbaea9",
    V29_ACCEPTED: "0759ed527b516b4d98bdd6e622b6047ed4f1d1851961b8bea7cbb29bf997315e",
    V28_ACCEPTED: "13a97d3d5b34243c7c53a5395178a72c6c55316059d0f1e5e81b28e0e7c5993f",
    PARENT_OUTCOMES: "6663b459b522018fb4ed274318fca02379250d07236f43c2e28ee70defed85b4",
    PARENT_DAILY: "c288f088c26657abc105f291e95217bdf79096bb5bc771cbc9d7e37c108b0d0f",
    VAP: "2399f0e6ad2d410438f3b1d924a87f9357f4e621b2dca6aafe557a2aa7b4d533",
    CY006_MANIFEST: "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    CY008_MANIFEST: "5903149da5d8afe37fa18719d17e8a5726856d11e8441d25d51217b05d6adf9f",
    CY009_MANIFEST: "d8a8d6c77de3eadb119315bf0c2a9513d94a1f4a28419dc15e616b2713316c32",
}

MAX_DATE = pd.Timestamp("2021-12-31")
OUT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_issuer_risk_v29r2_development_anatomy_v1"
)
CHARTS = OUT / "individual_charts"
SHEETS = OUT / "contact_sheets"
LEDGER = OUT / "anatomy_ledger.parquet"
LEDGER_CSV = OUT / "anatomy_ledger.csv"
WINDOWS = OUT / "chart_window_panel.parquet"
CONTEXT = OUT / "market_industry_context.parquet"
MINUTE = OUT / "signal_entry_5m_panel.parquet"
SUMMARY = OUT / "summary.json"
MANIFEST = OUT / "manifest.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

CJK_FONT = FontProperties(fname="/System/Library/Fonts/STHeiti Light.ttc")
CLEAR_RISK_FAMILIES = {
    "REGULATORY_INVESTIGATION",
    "RISK_WARNING_OR_DELISTING",
    "ILLEGAL_GUARANTEE",
    "ISSUER_BANK_ACCOUNT_FREEZE",
}
ROUTINE_TITLE_MARKERS = (
    "独立董事",
    "专项审计说明",
    "专项说明",
    "专项报告",
    "专项审核报告",
)
ASSERTIVE_ADVERSE_MARKERS = (
    "违规占用",
    "非经营性占用",
    "占用上市公司资金",
    "资金被占用",
    "偿还占用",
    "清偿占用",
    "解决资金占用",
    "资金占用整改",
)


class AnatomyError(RuntimeError):
    """Fail closed on identity, chronology, availability, or sample drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(
        path,
        json.dumps(json_ready(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        temporary,
        compression="zstd",
    )
    os.replace(temporary, path)


def sql_paths(paths: list[Path]) -> str:
    return "[" + ",".join(f"'{path.as_posix()}'" for path in paths) + "]"


def verify_inventory(
    manifest_path: Path,
    expected_manifest_hash: str,
    selected_paths: list[Path],
) -> dict[str, str]:
    if sha256(manifest_path) != expected_manifest_hash:
        raise AnatomyError(f"manifest identity drift: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = Path(manifest["root"])
    declared = {root / row["path"]: row for row in manifest["files"]}
    result: dict[str, str] = {}
    for path in selected_paths:
        row = declared.get(path)
        if row is None:
            raise AnatomyError(f"selected partition absent from inventory: {path}")
        if not path.is_file() or path.stat().st_size != int(row["size"]):
            raise AnatomyError(f"selected partition size drift: {path}")
        actual = sha256(path)
        if actual != row["sha256"]:
            raise AnatomyError(f"selected partition hash drift: {path}")
        result[str(path)] = actual
    return result


def verify_inputs() -> dict[str, str]:
    found: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise AnatomyError(f"missing frozen input: {path}")
        actual = sha256(path)
        if actual != expected:
            raise AnatomyError(f"frozen input drift: {path}: {actual}")
        found[str(path)] = actual
    found.update(verify_inventory(CY006_MANIFEST, EXPECTED_HASHES[CY006_MANIFEST], CY006_FILES))
    found.update(verify_inventory(CY008_MANIFEST, EXPECTED_HASHES[CY008_MANIFEST], CY008_FILES))
    found.update(verify_inventory(CY009_MANIFEST, EXPECTED_HASHES[CY009_MANIFEST], CY009_FILES))
    stage_a = json.loads(V29_STAGE_A.read_text(encoding="utf-8"))
    result = json.loads(V29_RESULT.read_text(encoding="utf-8"))
    if stage_a.get("development", {}).get("rejected_signals") != 60:
        raise AnatomyError("V29R1 rejected-signal identity drift")
    if result.get("verdict") != "DEVELOPMENT_PASS_LATER_DATA_REMAINS_LOCKED":
        raise AnatomyError("unexpected V29R1 development verdict")
    return found


def title_bucket(titles: list[str], families: list[str]) -> str:
    if set(families).intersection(CLEAR_RISK_FAMILIES):
        return "CLEAR_HIGH_RISK_VETO"
    cleaned = [str(title).strip() for title in titles if str(title).strip()]
    only_fund = bool(families) and set(families) == {"CONTROLLER_FUND_MISAPPROPRIATION"}
    routine_form = bool(cleaned) and all(
        any(marker in title for marker in ROUTINE_TITLE_MARKERS) for title in cleaned
    )
    assertive = any(marker in title for title in cleaned for marker in ASSERTIVE_ADVERSE_MARKERS)
    if only_fund and routine_form and not assertive:
        return "SUSPECTED_ROUTINE_OCCUPANCY_TITLE_FALSE_POSITIVE"
    return "OTHER_FUND_OCCUPANCY_VETO"


def stratified_winner_ids(frame: pd.DataFrame) -> list[str]:
    chosen: list[str] = []
    positive = frame.loc[frame.net_return.gt(0)].copy()
    positive["signal_year"] = pd.to_datetime(positive.signal_date).dt.year
    for _, part in positive.groupby("signal_year", sort=True):
        ordered = part.sort_values(["net_return", "gap_id"], kind="mergesort")
        for quantile in (0.25, 0.50, 0.75):
            target = float(ordered.net_return.quantile(quantile))
            row = (
                ordered.assign(distance=(ordered.net_return - target).abs())
                .sort_values(["distance", "gap_id"], kind="mergesort")
                .iloc[0]
            )
            if str(row.gap_id) not in chosen:
                chosen.append(str(row.gap_id))
    return chosen


def load_corpus() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rejected = pd.read_parquet(REJECTED)
    classified = pd.read_parquet(CLASSIFIED)
    outcomes = pd.read_parquet(
        PARENT_OUTCOMES,
        columns=[
            "gap_id",
            "exit_time",
            "exit_date",
            "exit_cal_idx",
            "exit_raw_price",
            "exit_reason",
            "net_return",
            "holding_sessions",
        ],
    )
    accepted = pd.read_parquet(V29_ACCEPTED)
    v28_accepted = pd.read_parquet(V28_ACCEPTED)
    for frame in (rejected, accepted, v28_accepted):
        for column in ("gap_date", "signal_date", "signal_time", "entry_date", "entry_time"):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column])
    for column in ("exit_time", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    classified["available_at"] = pd.to_datetime(classified.available_at, utc=True)
    if len(rejected) != 60 or rejected.gap_id.nunique() != 60:
        raise AnatomyError("expected exactly 60 unique V29R1 vetoes")
    if pd.to_datetime(rejected.signal_date).max() > MAX_DATE:
        raise AnatomyError("post-2021 veto entered anatomy")
    if classified.available_at.max() > pd.Timestamp("2021-12-31 23:59:59", tz="UTC"):
        raise AnatomyError("post-2021 classified title entered anatomy")

    rejected = rejected.merge(outcomes, on="gap_id", how="left", validate="one_to_one")
    event_records: list[dict[str, Any]] = []
    for row in rejected.itertuples(index=False):
        start = pd.Timestamp(row.v29r1_window_start_at).tz_convert("UTC")
        end = pd.Timestamp(row.v29r1_window_end_at).tz_convert("UTC")
        events = classified.loc[
            classified.symbol.eq(row.symbol)
            & classified.action.eq("OPEN")
            & classified.available_at.between(start, end)
        ].sort_values(["available_at", "announcement_key"], kind="mergesort")
        if events.empty:
            raise AnatomyError(f"veto lacks matching frozen OPEN event: {row.gap_id}")
        titles = list(dict.fromkeys(events.title.astype(str)))
        families = sorted(set(events.risk_family.astype(str)))
        event_records.append(
            {
                "gap_id": str(row.gap_id),
                "risk_titles": " || ".join(titles),
                "risk_families": "|".join(families),
                "risk_title_count": len(titles),
                "risk_event_count": len(events),
                "anatomy_group": title_bucket(titles, families),
            }
        )
    rejected = rejected.merge(pd.DataFrame(event_records), on="gap_id", validate="one_to_one")
    rejected["source_status"] = "V29R1_VETOED"

    losers = accepted.loc[accepted.net_return.lt(0)].copy()
    losers["anatomy_group"] = "KEPT_PORTFOLIO_LOSER"
    winner_ids = stratified_winner_ids(accepted)
    winners = accepted.loc[accepted.gap_id.astype(str).isin(winner_ids)].copy()
    winners["anatomy_group"] = "KEPT_REPRESENTATIVE_WINNER"
    kept = pd.concat([losers, winners], ignore_index=True)
    kept["source_status"] = "V29R1_PORTFOLIO_ACCEPTED"
    kept["risk_titles"] = ""
    kept["risk_families"] = ""
    kept["risk_title_count"] = 0
    kept["risk_event_count"] = 0
    if len(losers) != 14 or len(winners) != 12:
        raise AnatomyError(
            f"kept diagnostic corpus drift: losers={len(losers)} winners={len(winners)}"
        )

    common = sorted(set(rejected.columns).intersection(kept.columns))
    ledger = pd.concat([rejected[common], kept[common]], ignore_index=True)
    ledger = ledger.sort_values(
        ["anatomy_group", "signal_date", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    if len(ledger) != 86 or ledger.gap_id.nunique() != 86:
        raise AnatomyError("86-row chart corpus identity drift")
    ledger["chart_number"] = np.arange(1, len(ledger) + 1, dtype=int)
    ledger["signal_year"] = pd.to_datetime(ledger.signal_date).dt.year.astype(int)
    complete = ledger.net_return.notna()
    if (
        pd.to_datetime(ledger.loc[complete, "entry_date"])
        <= pd.to_datetime(ledger.loc[complete, "signal_date"])
    ).any():
        raise AnatomyError("same-bar entry detected in anatomy outcomes")
    if pd.to_datetime(ledger.loc[complete, "exit_date"]).max() > MAX_DATE:
        raise AnatomyError("post-2021 outcome entered anatomy")
    return ledger, accepted, v28_accepted


def load_daily_and_context(
    connection: duckdb.DuckDBPyConnection,
    ledger: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    keys = ledger[["gap_id", "symbol", "signal_cal_idx", "signal_date", "invalid_step_cum"]].copy()
    connection.register("chart_keys", keys)
    windows = connection.execute(
        f"""
        SELECT k.gap_id,k.signal_cal_idx,k.signal_date,
          d.trade_date,d.cal_idx,d.symbol,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.coordinate_factor,
          d.invalid_step_cum,d.history_valid,d.current_valid,d.hard_valid,
          d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_blocking
        FROM chart_keys k
        JOIN read_parquet('{PARENT_DAILY.as_posix()}') d
          ON d.symbol=k.symbol
         AND d.cal_idx BETWEEN k.signal_cal_idx-120 AND k.signal_cal_idx+120
        WHERE d.trade_date<=DATE '2021-12-31'
        ORDER BY k.gap_id,d.cal_idx
        """
    ).fetchdf()
    for column in ("trade_date", "signal_date"):
        windows[column] = pd.to_datetime(windows[column])
    if windows.trade_date.max() > MAX_DATE or windows.signal_date.max() > MAX_DATE:
        raise AnatomyError("post-2021 daily row entered chart windows")
    signal_rows = windows.loc[windows.trade_date.eq(windows.signal_date)]
    if signal_rows.gap_id.nunique() != len(ledger) or signal_rows.gap_id.duplicated().any():
        raise AnatomyError("signal daily row missing or duplicated")
    windows["relative_session"] = windows.cal_idx.astype(int) - windows.signal_cal_idx.astype(int)
    windows["plot_valid"] = (
        windows.hard_valid.eq(1)
        & windows.current_valid.eq(1)
        & windows.history_valid.eq(1)
        & windows.current_day_data_tradable.eq(1)
        & windows.market_rule_valid.eq(1)
        & ~windows.corporate_action_blocking.eq(1)
    )

    symbols = ledger[["symbol"]].drop_duplicates()
    connection.register("chart_symbols", symbols)
    stock = connection.execute(
        f"""
        SELECT d.symbol,d.trade_date,d.decision_at,d.available_at,d.turnover_fraction,
          d.industry,d.industry_snapshot_id,d.hard_valid,d.current_day_data_tradable
        FROM read_parquet({sql_paths(CY006_FILES)}) d
        JOIN chart_symbols s USING(symbol)
        WHERE d.trade_date<=DATE '2021-12-31'
        ORDER BY d.symbol,d.trade_date
        """
    ).fetchdf()
    stock["trade_date"] = pd.to_datetime(stock.trade_date)
    stock["decision_at"] = pd.to_datetime(stock.decision_at)
    stock["available_at"] = pd.to_datetime(stock.available_at)
    valid_stock = stock.hard_valid & stock.current_day_data_tradable
    if stock.loc[valid_stock, "available_at"].gt(stock.loc[valid_stock, "decision_at"]).any():
        raise AnatomyError("CY-006 availability exceeds decision_at")
    windows = windows.merge(
        stock[
            [
                "symbol",
                "trade_date",
                "decision_at",
                "available_at",
                "turnover_fraction",
                "industry",
                "industry_snapshot_id",
                "hard_valid",
            ]
        ].rename(columns={"hard_valid": "cy006_hard_valid"}),
        on=["symbol", "trade_date"],
        how="left",
        validate="many_to_one",
    )
    signal_industry = windows.loc[
        windows.trade_date.eq(windows.signal_date), ["gap_id", "industry"]
    ].rename(columns={"industry": "signal_industry"})
    if signal_industry.signal_industry.isna().any():
        raise AnatomyError("missing PIT signal-date industry")
    windows = windows.merge(signal_industry, on="gap_id", validate="many_to_one")
    industries = (
        signal_industry[["signal_industry"]]
        .drop_duplicates()
        .rename(columns={"signal_industry": "industry"})
    )
    connection.register("chart_industries", industries)
    context = connection.execute(
        f"""
        WITH valid AS (
          SELECT trade_date,industry,close/preclose-1.0 AS step_return
          FROM read_parquet({sql_paths(CY006_FILES)})
          WHERE trade_date<=DATE '2021-12-31'
            AND hard_valid AND current_day_data_tradable
            AND available_at<=decision_at AND preclose>0 AND close>0
        ), market AS (
          SELECT trade_date,median(step_return) AS market_return,
            avg(CASE WHEN step_return>0 THEN 1.0 ELSE 0.0 END) AS market_up_share
          FROM valid GROUP BY trade_date
        ), industry AS (
          SELECT v.trade_date,v.industry,median(v.step_return) AS industry_return,
            avg(CASE WHEN v.step_return>0 THEN 1.0 ELSE 0.0 END) AS industry_up_share,
            count(*) AS industry_members
          FROM valid v JOIN chart_industries i USING(industry)
          GROUP BY v.trade_date,v.industry
        )
        SELECT i.*,m.market_return,m.market_up_share
        FROM industry i JOIN market m USING(trade_date)
        ORDER BY i.industry,i.trade_date
        """
    ).fetchdf()
    context["trade_date"] = pd.to_datetime(context.trade_date)
    if context.trade_date.max() > MAX_DATE:
        raise AnatomyError("post-2021 market/industry context entered anatomy")
    windows = windows.merge(
        context,
        left_on=["signal_industry", "trade_date"],
        right_on=["industry", "trade_date"],
        how="left",
        suffixes=("", "_context"),
        validate="many_to_one",
    )
    return windows, context


def attach_chip(
    connection: duckdb.DuckDBPyConnection,
    windows: pd.DataFrame,
    ledger: pd.DataFrame,
) -> pd.DataFrame:
    symbols = ledger[["symbol"]].drop_duplicates()
    connection.register("chip_symbols", symbols)
    chip = connection.execute(
        f"""
        SELECT c.symbol,c.trade_date AS chip_trade_date,c.available_at AS chip_available_at,
          c.p10,c.p50,c.p90,c.profit_ratio,c.trapped_ratio,c.asr,c.space20,
          c.mass_sum,c.daily_snapshot_id,c.minute_snapshot_id
        FROM read_parquet({sql_paths(CY009_FILES)}) c
        JOIN chip_symbols s USING(symbol)
        WHERE c.trade_date<=DATE '2021-12-31'
          AND c.strict_sample AND c.chip_input_valid AND c.daily_hard_valid
          AND c.minute_hard_valid AND c.state_chain_valid
        ORDER BY c.symbol,c.available_at
        """
    ).fetchdf()
    chip["chip_trade_date"] = pd.to_datetime(chip.chip_trade_date)
    chip["chip_available_at"] = pd.to_datetime(chip.chip_available_at)
    if chip.chip_trade_date.max() > MAX_DATE:
        raise AnatomyError("post-2021 chip row entered anatomy")
    pieces: list[pd.DataFrame] = []
    for symbol, left in windows.groupby("symbol", sort=False):
        right = (
            chip.loc[chip.symbol.eq(symbol)]
            .drop(columns="symbol")
            .sort_values("chip_available_at", kind="mergesort")
        )
        part = left.sort_values("decision_at", kind="mergesort")
        missing_decision = part.decision_at.isna()
        known_part = part.loc[~missing_decision].copy()
        unknown_part = part.loc[missing_decision].copy()
        right_columns = list(right.columns)
        if right.empty or known_part.empty:
            merged_known = known_part
            for column in right_columns:
                merged_known[column] = np.nan
        else:
            merged_known = pd.merge_asof(
                known_part,
                right,
                left_on="decision_at",
                right_on="chip_available_at",
                direction="backward",
                allow_exact_matches=True,
            )
        for column in right_columns:
            unknown_part[column] = np.nan
        pieces.append(pd.concat([merged_known, unknown_part], ignore_index=True))
    result = pd.concat(pieces, ignore_index=True).sort_values(
        ["gap_id", "cal_idx"], kind="mergesort"
    )
    known = result.chip_available_at.notna()
    if result.loc[known, "chip_available_at"].gt(result.loc[known, "decision_at"]).any():
        raise AnatomyError("chip look-ahead detected")
    for column in ("p10", "p50", "p90"):
        result[f"chip_{column}_coord"] = result[column] * result.coordinate_factor
    return result


def load_minute(
    connection: duckdb.DuckDBPyConnection,
    ledger: pd.DataFrame,
    windows: pd.DataFrame,
) -> pd.DataFrame:
    days: list[dict[str, Any]] = []
    for row in ledger.itertuples(index=False):
        days.append(
            {
                "gap_id": row.gap_id,
                "symbol": row.symbol,
                "day_kind": "SIGNAL",
                "trade_date": row.signal_date,
            }
        )
        if pd.notna(row.entry_date) and pd.Timestamp(row.entry_date) <= MAX_DATE:
            days.append(
                {
                    "gap_id": row.gap_id,
                    "symbol": row.symbol,
                    "day_kind": "ENTRY",
                    "trade_date": row.entry_date,
                }
            )
    event_days = pd.DataFrame(days).drop_duplicates(["gap_id", "day_kind"])
    event_days["trade_date"] = pd.to_datetime(event_days.trade_date)
    connection.register("event_days", event_days)
    minute = connection.execute(
        f"""
        SELECT e.gap_id,e.day_kind,m.symbol,m.trade_date,m.window_index,m.available_at,
          m.open,m.high,m.low,m.close,m.volume,m.amount,m.circulating_shares,
          m.hard_valid,m.snapshot_id,m.daily_snapshot_id
        FROM event_days e
        JOIN read_parquet({sql_paths(CY008_FILES)}) m
          ON m.symbol=e.symbol AND m.trade_date=e.trade_date
        WHERE m.hard_valid AND m.window_index BETWEEN 0 AND 5
        ORDER BY e.gap_id,e.day_kind,m.window_index
        """
    ).fetchdf()
    minute["trade_date"] = pd.to_datetime(minute.trade_date)
    minute["available_at"] = pd.to_datetime(minute.available_at)
    if minute.trade_date.max() > MAX_DATE:
        raise AnatomyError("post-2021 intraday row entered anatomy")
    counts = minute.groupby(["gap_id", "day_kind"]).window_index.nunique()
    if not counts.eq(6).all():
        raise AnatomyError(
            f"incomplete registered 5-minute window: {counts.loc[~counts.eq(6)].to_dict()}"
        )
    factors = windows[["gap_id", "trade_date", "coordinate_factor"]].drop_duplicates(
        ["gap_id", "trade_date"]
    )
    minute = minute.merge(factors, on=["gap_id", "trade_date"], validate="many_to_one")
    for column in ("open", "high", "low", "close"):
        minute[f"coord_{column}"] = minute[column] * minute.coordinate_factor
    minute["turnover_pct"] = minute.volume / minute.circulating_shares * 100.0
    minute["plot_x"] = minute.window_index + np.where(minute.day_kind.eq("ENTRY"), 7, 0)
    return minute


def load_vap(connection: duckdb.DuckDBPyConnection, ledger: pd.DataFrame) -> pd.DataFrame:
    ids = ledger[["gap_id"]]
    connection.register("vap_ids", ids)
    return connection.execute(
        f"""
        SELECT v.* FROM read_parquet('{VAP.as_posix()}') v
        JOIN vap_ids i USING(gap_id)
        WHERE v.z_bin BETWEEN -20 AND 29
        ORDER BY v.gap_id,v.z_bin
        """
    ).fetchdf()


def describe(values: pd.Series) -> dict[str, Any]:
    numeric = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if numeric.empty:
        return {"n": 0, "mean": None, "median": None, "win": None, "severe10": None}
    return {
        "n": len(numeric),
        "mean": numeric.mean(),
        "median": numeric.median(),
        "win": numeric.gt(0).mean(),
        "severe10": numeric.le(-0.10).mean(),
    }


def comparison_summary(
    ledger: pd.DataFrame,
    v29: pd.DataFrame,
    v28: pd.DataFrame,
) -> dict[str, Any]:
    v29_ids = set(v29.gap_id.astype(str))
    v28_ids = set(v28.gap_id.astype(str))
    removed = v28.loc[~v28.gap_id.astype(str).isin(v29_ids)].copy()
    added = v29.loc[~v29.gap_id.astype(str).isin(v28_ids)].copy()
    veto_ids = set(ledger.loc[ledger.source_status.eq("V29R1_VETOED"), "gap_id"].astype(str))
    removed_veto = removed.loc[removed.gap_id.astype(str).isin(veto_ids)]
    vetoed = ledger.loc[ledger.source_status.eq("V29R1_VETOED")]
    return {
        "veto_by_anatomy_group": {
            group: describe(part.net_return)
            for group, part in vetoed.groupby("anatomy_group", sort=True)
        },
        "veto_counts_by_signal_year": vetoed.signal_year.value_counts().sort_index().to_dict(),
        "veto_top_signal_dates": {
            str(pd.Timestamp(key).date()): int(value)
            for key, value in vetoed.signal_date.value_counts().head(10).items()
        },
        "v28_portfolio": describe(v28.net_return),
        "v29_portfolio": describe(v29.net_return),
        "portfolio_identity_overlap": len(v28_ids.intersection(v29_ids)),
        "v28_removed": describe(removed.net_return),
        "v28_removed_count": len(removed),
        "v28_removed_by_issuer_veto": describe(removed_veto.net_return),
        "v28_removed_by_issuer_veto_count": len(removed_veto),
        "v29_capacity_replacements": describe(added.net_return),
        "v29_capacity_replacement_count": len(added),
        "v29_signal_year_concentration": v29.signal_year.value_counts().sort_index().to_dict(),
    }


def candle(ax: plt.Axes, frame: pd.DataFrame, x_column: str) -> None:
    for row in frame.itertuples(index=False):
        x_value = getattr(row, x_column)
        x = (
            mdates.date2num(pd.Timestamp(x_value).to_pydatetime())
            if x_column == "trade_date"
            else float(x_value)
        )
        valid = bool(getattr(row, "plot_valid", True))
        up = float(row.coord_close) >= float(row.coord_open)
        color = "#c53b2c" if up else "#198754"
        if not valid:
            color = "#9ca3af"
        ax.vlines(x, row.coord_low, row.coord_high, color=color, linewidth=0.55, alpha=0.82)
        lower = min(float(row.coord_open), float(row.coord_close))
        height = max(abs(float(row.coord_close) - float(row.coord_open)), 1e-8)
        width = 0.72 if x_column == "trade_date" else 0.58
        ax.add_patch(
            Rectangle(
                (x - width / 2, lower), width, height, facecolor=color, edgecolor=color, alpha=0.76
            )
        )


def event_levels(frame: pd.DataFrame, event: pd.Series) -> dict[str, float]:
    prior = frame.loc[frame.relative_session.lt(0) & frame.plot_valid].tail(120)
    if len(prior) < 20:
        raise AnatomyError(f"insufficient prior support window: {event.gap_id}")
    prior20 = prior.tail(20)
    return {
        "support20": float(prior20.coord_low.min()),
        "resistance20": float(prior20.coord_high.max()),
        "support120": float(prior.coord_low.min()),
        "resistance120": float(prior.coord_high.max()),
    }


def render_chart(
    event: pd.Series,
    frame: pd.DataFrame,
    minute: pd.DataFrame,
    vap: pd.DataFrame,
    output: Path,
) -> dict[str, Any]:
    frame = frame.sort_values("cal_idx", kind="mergesort").copy()
    valid = frame.loc[frame.plot_valid & frame.coord_close.notna()].copy()
    signal_date = pd.Timestamp(event.signal_date)
    signal = frame.loc[frame.trade_date.eq(signal_date)]
    if len(signal) != 1:
        raise AnatomyError(f"signal row mismatch: {event.gap_id}")
    signal_close = float(signal.coord_close.iloc[0])
    levels = event_levels(frame, event)
    frame["donchian_low20"] = frame.coord_low.shift(1).rolling(20, min_periods=20).min()
    frame["donchian_high20"] = frame.coord_high.shift(1).rolling(20, min_periods=20).max()

    figure = plt.figure(figsize=(15.8, 11.2), facecolor="white")
    grid = figure.add_gridspec(
        4,
        2,
        width_ratios=[7.1, 1.45],
        height_ratios=[4.7, 1.25, 1.55, 1.75],
        left=0.055,
        right=0.985,
        bottom=0.065,
        top=0.84,
        hspace=0.18,
        wspace=0.06,
    )
    price_ax = figure.add_subplot(grid[0, 0])
    vap_ax = figure.add_subplot(grid[0, 1], sharey=price_ax)
    turn_ax = figure.add_subplot(grid[1, :], sharex=price_ax)
    context_ax = figure.add_subplot(grid[2, :], sharex=price_ax)
    minute_ax = figure.add_subplot(grid[3, :])

    candle(price_ax, valid, "trade_date")
    dates = pd.to_datetime(frame.trade_date)
    price_ax.plot(
        dates,
        frame.donchian_low20,
        color="#6b7280",
        linewidth=0.65,
        alpha=0.72,
        label="prior-only D20 support",
    )
    price_ax.plot(
        dates,
        frame.donchian_high20,
        color="#9a3412",
        linewidth=0.65,
        alpha=0.58,
        label="prior-only D20 pressure",
    )
    chip_known = frame.chip_p50_coord.notna()
    if chip_known.any():
        price_ax.fill_between(
            mdates.date2num(dates[chip_known].dt.to_pydatetime()),
            frame.loc[chip_known, "chip_p10_coord"].astype(float),
            frame.loc[chip_known, "chip_p90_coord"].astype(float),
            color="#7c3aed",
            alpha=0.07,
            label="PIT chip p10-p90",
        )
        price_ax.plot(
            dates[chip_known],
            frame.loc[chip_known, "chip_p50_coord"],
            color="#7c3aed",
            linewidth=0.7,
            alpha=0.78,
            label="PIT chip p50",
        )
    price_ax.axhspan(
        float(event.L), float(event.U), color="#f59e0b", alpha=0.18, label="frozen true-gap [L,U]"
    )
    price_ax.axhline(float(event.L), color="#d97706", linestyle="--", linewidth=1.0, label="L")
    price_ax.axhline(float(event.U), color="#92400e", linestyle="--", linewidth=1.0, label="U")
    price_ax.axhline(
        levels["support20"],
        color="#047857",
        linestyle=":",
        linewidth=0.9,
        label="signal prior20 support",
    )
    price_ax.axhline(
        levels["resistance20"],
        color="#b91c1c",
        linestyle=":",
        linewidth=0.9,
        label="signal prior20 pressure",
    )
    price_ax.axhline(
        levels["support120"],
        color="#065f46",
        linestyle="-.",
        linewidth=0.55,
        alpha=0.58,
        label="prior120 low",
    )
    price_ax.axhline(
        levels["resistance120"],
        color="#7f1d1d",
        linestyle="-.",
        linewidth=0.55,
        alpha=0.58,
        label="prior120 high",
    )
    lifecycle = [(signal_date, "#2563eb", "signal")]
    if pd.notna(event.entry_date):
        lifecycle.append((pd.Timestamp(event.entry_date), "#7c3aed", "T+1 entry"))
    if pd.notna(event.exit_date):
        lifecycle.append((pd.Timestamp(event.exit_date), "#111827", "frozen exit"))
    for date, color, label in lifecycle:
        for axis in (price_ax, turn_ax, context_ax):
            axis.axvline(
                date,
                color=color,
                linewidth=0.9,
                linestyle="--",
                label=label if axis is price_ax else None,
            )
    if pd.notna(event.entry_date):
        price_ax.scatter(
            pd.Timestamp(event.entry_date),
            float(event.entry_coordinate_price),
            marker="^",
            s=58,
            color="#7c3aed",
            zorder=10,
        )
    if pd.notna(event.exit_date):
        exit_rows = frame.loc[frame.trade_date.eq(pd.Timestamp(event.exit_date))]
        if not exit_rows.empty:
            exit_coordinate = float(event.exit_raw_price) * float(
                exit_rows.coordinate_factor.iloc[0]
            )
            price_ax.scatter(
                pd.Timestamp(event.exit_date),
                exit_coordinate,
                marker="v",
                s=58,
                color="#111827",
                zorder=10,
            )
    price_ax.set_ylabel("causal coordinate price", fontproperties=CJK_FONT)
    price_ax.grid(alpha=0.15, linewidth=0.45)
    handles, labels = price_ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles, strict=False))
    price_ax.legend(by_label.values(), by_label.keys(), loc="upper left", ncol=4, fontsize=6.5)

    if not vap.empty:
        y = float(event.L) + (vap.z_bin.astype(float) + 0.5) * 0.10 * float(event.W)
        vap_ax.barh(
            y,
            vap.pre_float_turnover_mass.astype(float),
            height=0.085 * float(event.W),
            color="#2563eb",
            alpha=0.66,
        )
    vap_ax.axhspan(float(event.L), float(event.U), color="#f59e0b", alpha=0.18)
    vap_ax.axhline(float(event.L), color="#d97706", linestyle="--", linewidth=0.8)
    vap_ax.axhline(float(event.U), color="#92400e", linestyle="--", linewidth=0.8)
    vap_ax.set_title("pre-gap 120-session\nraw float-turnover VAP", fontsize=8.2)
    vap_ax.set_xlabel("raw mass", fontsize=7)
    vap_ax.tick_params(axis="both", labelsize=6.5)
    vap_ax.grid(axis="x", alpha=0.13)

    colors = np.where(frame.coord_close.ge(frame.coord_open), "#c53b2c", "#198754")
    turn_ax.bar(dates, frame.turnover_fraction * 100.0, width=0.75, color=colors, alpha=0.52)
    turn_ax.plot(
        dates,
        frame.turnover_fraction.shift(1).rolling(20, min_periods=10).median() * 100.0,
        color="#1d4ed8",
        linewidth=0.8,
        label="prior turnover median",
    )
    turn_ax.set_ylabel("turnover %", fontproperties=CJK_FONT)
    turn_ax.grid(alpha=0.12)
    turn_ax.legend(loc="upper left", fontsize=6.5)

    context = frame[["trade_date", "coord_close", "market_return", "industry_return"]].copy()
    context["market_curve"] = (1.0 + context.market_return.fillna(0)).cumprod()
    context["industry_curve"] = (1.0 + context.industry_return.fillna(0)).cumprod()
    signal_position = int(np.flatnonzero(context.trade_date.eq(signal_date))[0])
    context["stock_index"] = context.coord_close / signal_close
    context["market_index"] = context.market_curve / float(
        context.market_curve.iloc[signal_position]
    )
    context["industry_index"] = context.industry_curve / float(
        context.industry_curve.iloc[signal_position]
    )
    context_ax.plot(
        context.trade_date,
        (context.stock_index - 1) * 100,
        color="#111827",
        linewidth=0.95,
        label="stock",
    )
    context_ax.plot(
        context.trade_date,
        (context.industry_index - 1) * 100,
        color="#f97316",
        linewidth=0.9,
        label="signal-date PIT industry median",
    )
    context_ax.plot(
        context.trade_date,
        (context.market_index - 1) * 100,
        color="#0f766e",
        linewidth=0.9,
        label="market median",
    )
    context_ax.axhline(0, color="#6b7280", linewidth=0.55)
    context_ax.set_ylabel("cum return vs signal %", fontproperties=CJK_FONT)
    context_ax.grid(alpha=0.13)
    context_ax.legend(loc="upper left", ncol=3, fontsize=6.5)

    if not minute.empty:
        minute = minute.sort_values("plot_x", kind="mergesort")
        minute_plot = minute.rename(
            columns={
                "coord_open": "coord_open",
                "coord_high": "coord_high",
                "coord_low": "coord_low",
                "coord_close": "coord_close",
            }
        ).assign(plot_valid=True)
        candle(minute_ax, minute_plot, "plot_x")
        volume_ax = minute_ax.twinx()
        volume_ax.bar(minute.plot_x, minute.turnover_pct, width=0.58, color="#64748b", alpha=0.18)
        volume_ax.set_ylabel("5m turnover %", fontsize=7, color="#64748b")
        volume_ax.tick_params(axis="y", labelsize=6, colors="#64748b")
        labels_5m = [
            "S09:35",
            "09:40",
            "09:45",
            "09:50",
            "09:55",
            "10:00",
            "",
            "E09:35",
            "09:40",
            "09:45",
            "09:50",
            "09:55",
            "10:00",
        ]
        minute_ax.set_xticks(range(13))
        minute_ax.set_xticklabels(labels_5m, fontsize=6.5)
        minute_ax.axvline(6, color="#9ca3af", linewidth=0.7)
        if pd.notna(event.entry_coordinate_price):
            minute_ax.scatter(
                7,
                float(event.entry_coordinate_price),
                marker="^",
                s=50,
                color="#7c3aed",
                zorder=11,
                label="legal entry at open",
            )
        minute_ax.legend(loc="upper left", fontsize=6.5)
    minute_ax.set_ylabel("coordinate price", fontproperties=CJK_FONT)
    minute_ax.set_title(
        "registered CY-008 first 30 minutes: signal day (S) and T+1 entry day "
        "(E); descriptive, no same-bar fill",
        fontsize=8,
    )
    minute_ax.grid(alpha=0.12)

    for axis in (price_ax, turn_ax, context_ax):
        axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=9))
        axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    price_ax.tick_params(labelbottom=False)
    turn_ax.tick_params(labelbottom=False)
    for label in context_ax.get_xticklabels():
        label.set_rotation(22)
        label.set_horizontalalignment("right")
        label.set_fontsize(6.5)

    outcome = "outcome incomplete"
    if pd.notna(event.net_return):
        outcome = (
            f"net {float(event.net_return):+.2%} / "
            f"hold {int(event.holding_sessions)} / {event.exit_reason}"
        )
    title = str(event.risk_titles).split(" || ")[0]
    if len(title) > 64:
        title = title[:61] + "..."
    title = title or "retained by V29R1"
    figure.suptitle(
        f"{int(event.chart_number):03d} | {event.anatomy_group} | "
        f"{event.symbol} | signal {signal_date.date()} | {outcome}\n"
        f"{title}",
        fontsize=11.2,
        fontproperties=CJK_FONT,
        y=0.982,
    )
    signal_turn = (
        float(signal.turnover_fraction.iloc[0])
        if pd.notna(signal.turnover_fraction.iloc[0])
        else math.nan
    )
    prior_turn = frame.loc[frame.relative_session.lt(0), "turnover_fraction"].tail(20).median()
    turn_ratio = (
        signal_turn / prior_turn
        if math.isfinite(signal_turn) and prior_turn and prior_turn > 0
        else math.nan
    )
    signal_chip = signal.iloc[0]
    chip_text = "chip unavailable"
    if pd.notna(signal_chip.chip_p50_coord):
        chip_text = (
            f"PIT-lag chip p10/p50/p90={signal_chip.chip_p10_coord:.3f}/"
            f"{signal_chip.chip_p50_coord:.3f}/{signal_chip.chip_p90_coord:.3f}; "
            f"mass_sum(raw)={signal_chip.mass_sum:.15g}"
        )
    figure.text(
        0.057,
        0.902,
        f"gap [L,U]=[{float(event.L):.4f},{float(event.U):.4f}] | "
        f"prior20 S/R={levels['support20']:.4f}/{levels['resistance20']:.4f} | "
        f"signal turnover / prior20 median={turn_ratio:.2f}x | "
        f"industry={signal.signal_industry.iloc[0]}\n{chip_text}",
        fontsize=7.8,
        fontproperties=CJK_FONT,
    )
    figure.text(
        0.057,
        0.02,
        "All candles/contexts are capped at 2021-12-31. Post-signal paths are "
        "labels, never predictors. "
        "Grey candles are invalid and excluded from level calculations.",
        fontsize=7.4,
        color="#4b5563",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return {
        **levels,
        "signal_turnover_to_prior20_median": turn_ratio,
        "signal_industry": str(signal.signal_industry.iloc[0]),
        "signal_chip_p10_coord": signal_chip.chip_p10_coord,
        "signal_chip_p50_coord": signal_chip.chip_p50_coord,
        "signal_chip_p90_coord": signal_chip.chip_p90_coord,
        "signal_chip_mass_sum_raw": signal_chip.mass_sum,
        "minimum_chart_date": frame.trade_date.min(),
        "maximum_chart_date": frame.trade_date.max(),
        "chart_rows": len(frame),
        "chart_path": str(output),
    }


def contact_sheets(index: pd.DataFrame) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for group, part in index.groupby("anatomy_group", sort=True):
        directory = SHEETS / group.lower()
        directory.mkdir(parents=True, exist_ok=True)
        paths: list[str] = []
        ordered = part.sort_values(["signal_date", "symbol"], kind="mergesort")
        for number, start in enumerate(range(0, len(ordered), 4), start=1):
            subset = ordered.iloc[start : start + 4]
            images = [Image.open(path).convert("RGB") for path in subset.chart_path]
            width = 1180
            resized = []
            for image in images:
                height = round(image.height * width / image.width)
                resized.append(image.resize((width, height), Image.Resampling.LANCZOS))
            cell_height = max(image.height for image in resized) + 34
            canvas = Image.new("RGB", (width * 2, cell_height * 2), "white")
            draw = ImageDraw.Draw(canvas)
            for offset, (row, image) in enumerate(zip(subset.itertuples(), resized, strict=True)):
                x = (offset % 2) * width
                y = (offset // 2) * cell_height
                draw.text(
                    (x + 5, y + 5),
                    f"{row.symbol} {pd.Timestamp(row.signal_date).date()} {row.net_return:+.2%}"
                    if pd.notna(row.net_return)
                    else f"{row.symbol} {pd.Timestamp(row.signal_date).date()} incomplete",
                    fill="black",
                )
                canvas.paste(image, (x, y + 28))
            target = directory / f"sheet_{number:02d}.jpg"
            canvas.save(target, "JPEG", quality=89, optimize=True)
            paths.append(str(target))
        result[group] = paths
    return result


def write_report(summary: dict[str, Any]) -> None:
    groups = summary["comparison"]["veto_by_anatomy_group"]
    rows = []
    for group, stats in groups.items():
        mean = "NA" if stats["mean"] is None else f"{stats['mean']:.2%}"
        win = "NA" if stats["win"] is None else f"{stats['win']:.1%}"
        rows.append(f"|{group}|{stats['n']}|{mean}|{win}|")
    comparison = summary["comparison"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "This is a post-hoc 2018-2021 anatomy audit. It does not change V29R1 "
        "and reads no 2022+ validation title or return.",
        "",
        "## What the veto actually selected",
        "",
        "|Diagnostic title bucket|Complete counterfactual outcomes|Mean net|Win rate|",
        "|---|---:|---:|---:|",
        *rows,
        "",
        "All 60 vetoes were charted. The corpus also includes all 14 retained "
        "portfolio losers and 12 year-stratified retained winners.",
        "",
        "## Capacity decomposition",
        "",
        f"V28R2 and V29R1 share {comparison['portfolio_identity_overlap']} portfolio trades. "
        f"V29R1 removed {comparison['v28_removed_count']} V28R2 trades; "
        f"{comparison['v28_removed_by_issuer_veto_count']} were direct issuer vetoes. "
        "The removed issuer-veto trades had mean "
        f"{comparison['v28_removed_by_issuer_veto']['mean']:.2%}. Only "
        f"{comparison['v29_capacity_replacement_count']} trades entered through "
        "capacity reshuffling, with mean "
        f"{comparison['v29_capacity_replacements']['mean']:.2%}.",
        "",
        "## Diagnostic interpretation",
        "",
        "Most fund-occupancy hits are recurring audit/independent-director headings "
        "that do not assert adverse conduct in the title. They are labelled suspected "
        "title false positives, not reclassified facts.",
        "",
        "The clear-risk veto bucket does not isolate development losses: several of "
        "its strongest price-recapture paths reached the frozen target quickly. A "
        "title event can explain why supply appeared, but title presence alone does "
        "not show that demand failed to absorb it.",
        "",
        "The apparent mean improvement is entangled with deletion and K80 capacity "
        "ordering. It must not be described as an issuer-risk forecasting effect "
        "without an unchanged later validation and a capacity-neutral paired analysis.",
        "",
        "## Chart reading key",
        "",
        "Orange is the frozen [L,U] gap zone; green/red candles are coordinate-price "
        "bars; dotted lines are prior-only support/pressure; purple is the latest "
        "PIT-safe lagged chip p10/p50/p90; the side histogram is raw pre-gap "
        "turnover-at-price mass. The bottom panel is registered CY-008 5-minute "
        "data for the first 30 minutes of signal and T+1 entry days.",
        "",
    ]
    atomic_text(REPORT, "\n".join(lines))


def run(render_limit: int | None = None) -> dict[str, Any]:
    hashes = verify_inputs()
    ledger, v29, v28 = load_corpus()
    full_ledger = ledger.copy()
    if render_limit is not None:
        ledger = ledger.iloc[:render_limit].copy()
    connection = duckdb.connect()
    windows, context = load_daily_and_context(connection, ledger)
    windows = attach_chip(connection, windows, ledger)
    minute = load_minute(connection, ledger, windows)
    vap = load_vap(connection, ledger)
    connection.close()
    if windows.trade_date.max() > MAX_DATE or minute.trade_date.max() > MAX_DATE:
        raise AnatomyError("temporal quarantine failure before publication")

    CHARTS.mkdir(parents=True, exist_ok=True)
    window_groups = {key: part for key, part in windows.groupby("gap_id", sort=False)}
    minute_groups = {key: part for key, part in minute.groupby("gap_id", sort=False)}
    vap_groups = {key: part for key, part in vap.groupby("gap_id", sort=False)}
    records: list[dict[str, Any]] = []
    for event in ledger.itertuples(index=False):
        target = CHARTS / (
            f"{int(event.chart_number):03d}_{event.anatomy_group.lower()}_"
            f"{event.symbol.replace('.', '_')}_{pd.Timestamp(event.signal_date):%Y%m%d}.png"
        )
        anatomy = render_chart(
            pd.Series(event._asdict()),
            window_groups[str(event.gap_id)],
            minute_groups.get(str(event.gap_id), minute.iloc[0:0]),
            vap_groups.get(str(event.gap_id), vap.iloc[0:0]),
            target,
        )
        records.append({**event._asdict(), **anatomy})
    index = pd.DataFrame(records)
    sheets = contact_sheets(index)
    comparison = comparison_summary(full_ledger, v29, v28)

    atomic_parquet(windows, WINDOWS)
    atomic_parquet(context, CONTEXT)
    atomic_parquet(minute, MINUTE)
    atomic_parquet(index, LEDGER)
    index.to_csv(LEDGER_CSV, index=False, float_format="%.10g")
    summary = {
        "experiment": EXPERIMENT,
        "stage": "POST_HOC_DEVELOPMENT_ANATOMY_COMPLETE",
        "chart_count": len(index),
        "group_counts": index.anatomy_group.value_counts().sort_index().to_dict(),
        "comparison": comparison,
        "contact_sheets": sheets,
        "minimum_signal_date": index.signal_date.min(),
        "maximum_signal_date": index.signal_date.max(),
        "maximum_outcome_date": pd.to_datetime(index.exit_date).max(),
        "maximum_chart_date": windows.trade_date.max(),
        "maximum_intraday_date": minute.trade_date.max(),
        "post_2021_announcement_title_read": False,
        "post_2021_return_or_validation_read": False,
        "strategy_or_classifier_changed": False,
    }
    atomic_json(SUMMARY, summary)
    write_report(summary)
    manifest = {
        "experiment": EXPERIMENT,
        "input_hashes": hashes,
        "runner_sha256": sha256(Path(__file__)),
        "spec_sha256": sha256(SPEC),
        "outputs": {
            "ledger": {"path": str(LEDGER), "sha256": sha256(LEDGER)},
            "ledger_csv": {"path": str(LEDGER_CSV), "sha256": sha256(LEDGER_CSV)},
            "windows": {"path": str(WINDOWS), "sha256": sha256(WINDOWS)},
            "context": {"path": str(CONTEXT), "sha256": sha256(CONTEXT)},
            "minute": {"path": str(MINUTE), "sha256": sha256(MINUTE)},
            "summary": {"path": str(SUMMARY), "sha256": sha256(SUMMARY)},
            "report": {"path": str(REPORT), "sha256": sha256(REPORT)},
        },
        "chart_count": len(index),
        "contact_sheet_count": sum(len(paths) for paths in sheets.values()),
        "maximum_data_date": str(max(windows.trade_date.max(), minute.trade_date.max()).date()),
        "post_2021_data_row_opened": False,
        "post_2021_validation_title_or_return_opened": False,
    }
    atomic_json(MANIFEST, manifest)
    return {**summary, "manifest_sha256": sha256(MANIFEST)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-limit", type=int)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    print(
        json.dumps(
            json_ready(run(arguments.render_limit)), ensure_ascii=False, indent=2, sort_keys=True
        )
    )
