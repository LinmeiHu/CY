#!/usr/bin/env python3
"""Run the once-frozen chart-compressed causal acceptance lifecycle."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_high_transfer_low_price_displacement_mother_v1_stage_b as stage_b,
)


EXPERIMENT = "ASHARE-HIGH-TRANSFER-LOW-PRICE-DISPLACEMENT-CAUSAL-ACCEPTANCE-V1"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
RESULT = OS_ROOT / f"results/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
MOTHER_ROOT = DATA_ROOT / "ashare_high_transfer_low_price_displacement_mother_v1"
CANDIDATES = MOTHER_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = MOTHER_ROOT / "stage_b/future_paths_through_2020.parquet"
REGIME = DATA_ROOT / (
    "ashare_causal_market_regime_routed_simple_strategy_v1/"
    "stage_a/causal_market_regime_2014_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_high_transfer_low_price_displacement_causal_acceptance_v1"
LEDGER = OUTPUT_ROOT / "development_2015_2019/trade_ledger.parquet"
MANIFEST = OUTPUT_ROOT / "development_2015_2019/manifest.json"

EXPECTED_HASHES = {
    SPEC: "1afd979753308f0d42a6eee57493307464c68aea315a01af968eb1d51e4fc534",
    CANDIDATES: "c2c2a61393563c7aa78fa06d2562df6f1fe6e8bd957b54ca6d97c03630aa0295",
    PATHS: "e0004c8eaef11353cecba4f2269c7404ad724856b42baaa09276162976d60325",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}
EXPECTED_EVENTS = 6115
DEVELOPMENT_YEARS = tuple(range(2015, 2020))
MAX_OUTCOME_DATE = pd.Timestamp("2020-12-31")
CONFIRMATION_FIRST_OFFSET = 5
CONFIRMATION_LAST_OFFSET = 10
ACCEPTANCE_LOOKBACK = 5
ACCEPTANCE_CLOSES_REQUIRED = 3
ENTRY_WAIT = 3
MAX_HOLD = 60
SHORT_PATH_LIMIT = 126
ROUND_TRIP_COST = 0.004


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, chronology, or execution drift."""


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
        value = sha256(path)
        actual[str(path)] = value
        if value != expected:
            raise ResearchError(f"frozen input drift: {path}: {value} != {expected}")
    return actual


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def valid_completed_close(row: Any, lineage: float) -> bool:
    required = (
        row.cal_idx,
        row.coord_close,
        row.invalid_step_cum,
        row.trade_status,
        row.current_day_data_tradable,
        row.current_valid,
        row.market_rule_valid,
        row.corporate_action_count,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.hard_valid,
        row.available_at,
        row.decision_at,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and float(row.invalid_step_cum) == lineage
        and int(row.trade_status) == 1
        and bool(row.current_day_data_tradable)
        and bool(row.current_valid)
        and bool(row.market_rule_valid)
        and int(row.corporate_action_count) == 0
        and bool(row.corporate_action_valid)
        and not bool(row.corporate_action_blocking)
        and bool(row.hard_valid)
        and float(row.coord_close) > 0
        and pd.Timestamp(row.available_at) <= pd.Timestamp(row.decision_at)
    )


def market_admitted(row: Any, decision_at: pd.Timestamp) -> tuple[bool, str]:
    required = (
        row.market_regime,
        row.market_median_ret20,
        row.market_median_ret60,
        row.market_positive_ret20_share,
        row.market_positive_ret60_share,
        row.latest_source_timestamp,
    )
    if any(pd.isna(value) for value in required):
        return False, "UNKNOWN"
    state = str(row.market_regime)
    if state not in {"BULL", "TRANSITION", "BEAR"}:
        return False, "UNKNOWN"
    if pd.Timestamp(row.latest_source_timestamp) > pd.Timestamp(decision_at):
        return False, "FUTURE_SOURCE"
    if state == "BULL":
        return True, "BULL"
    repairing = (
        float(row.market_median_ret20) > float(row.market_median_ret60)
        and float(row.market_positive_ret20_share)
        > float(row.market_positive_ret60_share)
    )
    return bool(repairing), f"{state}_{'REPAIR' if repairing else 'NO_REPAIR'}"


def find_stock_acceptance(candidate: Any, path: pd.DataFrame) -> Any | None:
    lineage = float(candidate.invalid_step_cum)
    level = float(candidate.coord_high)
    indexed = {int(row.cal_idx): row for row in path.itertuples(index=False)}
    for offset in range(CONFIRMATION_FIRST_OFFSET, CONFIRMATION_LAST_OFFSET + 1):
        current_idx = int(candidate.signal_cal_idx) + offset
        window = [
            indexed.get(idx)
            for idx in range(current_idx - ACCEPTANCE_LOOKBACK + 1, current_idx + 1)
        ]
        if any(row is None for row in window):
            continue
        if not all(valid_completed_close(row, lineage) for row in window):
            continue
        above = [float(row.coord_close) > level for row in window]
        if above[-1] and sum(above) >= ACCEPTANCE_CLOSES_REQUIRED:
            return window[-1]
    return None


def select_first_entry(
    confirmation_idx: int, lineage: float, path: pd.DataFrame
) -> Any | None:
    pool = path.loc[
        path.cal_idx.gt(confirmation_idx)
        & path.cal_idx.le(confirmation_idx + ENTRY_WAIT)
    ].sort_values("cal_idx", kind="mergesort")
    return next(
        (
            row
            for row in pool.itertuples(index=False)
            if float(row.invalid_step_cum) == lineage and stage_b.buyable(row)
        ),
        None,
    )


def first_structural_trigger(
    entry_idx: int, level: float, lineage: float, path: pd.DataFrame
) -> Any | None:
    indexed = {
        int(row.cal_idx): row
        for row in path.loc[path.cal_idx.ge(entry_idx)].itertuples(index=False)
    }
    for current_idx in sorted(indexed):
        if current_idx <= entry_idx:
            continue
        previous = indexed.get(current_idx - 1)
        current = indexed[current_idx]
        if previous is None:
            continue
        if not valid_completed_close(previous, lineage) or not valid_completed_close(
            current, lineage
        ):
            continue
        if float(previous.coord_close) < level and float(current.coord_close) < level:
            return current
    return None


def first_sellable(
    path: pd.DataFrame, minimum_idx: int, lineage: float, *, strict: bool
) -> Any | None:
    mask = path.cal_idx.gt(minimum_idx) if strict else path.cal_idx.ge(minimum_idx)
    pool = path.loc[mask].sort_values("cal_idx", kind="mergesort")
    for row in pool.itertuples(index=False):
        if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum) != lineage:
            return None
        if stage_b.sellable_open(row):
            return row
    return None


def choose_exit(
    entry: Any, level: float, lineage: float, path: pd.DataFrame
) -> tuple[Any | None, str]:
    entry_idx = int(entry.cal_idx)
    structural_trigger = first_structural_trigger(entry_idx, level, lineage, path)
    structural_exit = (
        None
        if structural_trigger is None
        else first_sellable(
            path, int(structural_trigger.cal_idx), lineage, strict=True
        )
    )
    time_exit = first_sellable(path, entry_idx + MAX_HOLD, lineage, strict=False)
    if structural_exit is None and time_exit is None:
        return None, "NO_EXIT_IN_PATH"
    if structural_exit is not None and (
        time_exit is None or int(structural_exit.cal_idx) <= int(time_exit.cal_idx)
    ):
        return structural_exit, "TWO_CLOSES_BELOW_EVENT_HIGH"
    return time_exit, "H60"


def replay_one(
    candidate: Any,
    path: pd.DataFrame,
    regime_lookup: dict[pd.Timestamp, Any],
    *,
    allow_extension: bool,
) -> dict[str, Any]:
    common = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "event_high": float(candidate.coord_high),
        "mother_market_regime": str(candidate.market_regime),
    }
    path = path.sort_values("cal_idx", kind="mergesort").reset_index(drop=True)
    confirmation = find_stock_acceptance(candidate, path)
    if confirmation is None:
        return {**common, "status": "NO_STOCK_ACCEPTANCE"}
    confirmation_date = pd.Timestamp(confirmation.trade_date)
    market = regime_lookup.get(confirmation_date)
    if market is None:
        return {
            **common,
            "status": "NO_MARKET_STATE",
            "confirmation_date": confirmation_date,
            "confirmation_cal_idx": int(confirmation.cal_idx),
        }
    admitted, market_route = market_admitted(
        market, pd.Timestamp(confirmation.decision_at)
    )
    confirmation_common = {
        **common,
        "confirmation_date": confirmation_date,
        "confirmation_cal_idx": int(confirmation.cal_idx),
        "confirmation_market_regime": str(market.market_regime),
        "market_route": market_route,
        "market_median_ret20": float(market.market_median_ret20),
        "market_median_ret60": float(market.market_median_ret60),
        "market_positive_ret20_share": float(market.market_positive_ret20_share),
        "market_positive_ret60_share": float(market.market_positive_ret60_share),
        "market_latest_source_timestamp": pd.Timestamp(
            market.latest_source_timestamp
        ),
    }
    if not admitted:
        return {**confirmation_common, "status": "MARKET_ROUTE_REJECTED"}
    lineage = float(candidate.invalid_step_cum)
    entry = select_first_entry(int(confirmation.cal_idx), lineage, path)
    if entry is None:
        return {**confirmation_common, "status": "NO_LEGAL_ENTRY"}
    entry_common = {
        **confirmation_common,
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": int(entry.cal_idx),
        "entry_price": float(entry.coord_open),
    }
    exit_row, exit_reason = choose_exit(
        entry, float(candidate.coord_high), lineage, path
    )
    if exit_row is None:
        if not allow_extension and int(path.cal_idx.max()) >= (
            int(candidate.signal_cal_idx) + SHORT_PATH_LIMIT
        ):
            return {**entry_common, "status": "NEEDS_EXTENSION"}
        return {**entry_common, "status": exit_reason}
    exit_idx = int(exit_row.cal_idx)
    held = path.loc[
        path.cal_idx.ge(int(entry.cal_idx))
        & path.cal_idx.le(exit_idx)
        & path.invalid_step_cum.eq(lineage)
    ]
    gross = float(exit_row.coord_open) / float(entry.coord_open) - 1.0
    return {
        **entry_common,
        "status": "COMPLETED",
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": exit_idx,
        "exit_price": float(exit_row.coord_open),
        "exit_reason": exit_reason,
        "holding_market_sessions": exit_idx - int(entry.cal_idx),
        "gross_return": gross,
        "net_return": gross - ROUND_TRIP_COST,
        "mfe": (
            float(held.coord_high.max() / float(entry.coord_open) - 1.0)
            if not held.empty
            else math.nan
        ),
        "mae": (
            float(held.coord_low.min() / float(entry.coord_open) - 1.0)
            if not held.empty
            else math.nan
        ),
    }


def load_candidates() -> pd.DataFrame:
    frame = pd.read_parquet(CANDIDATES)
    for column in ("signal_date", "decision_at", "available_at"):
        frame[column] = pd.to_datetime(frame[column])
    if len(frame) != EXPECTED_EVENTS or frame.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    if not frame.signal_date.dt.year.isin(DEVELOPMENT_YEARS).all():
        raise ResearchError("signal year escaped development freeze")
    return frame.sort_values(
        ["signal_date", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)


def load_paths(candidates: pd.DataFrame, *, extended_ids: set[str] | None = None) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("candidate_frame", candidates[["event_id", "signal_cal_idx"]])
    where = (
        "p.cal_idx<=c.signal_cal_idx+126"
        if extended_ids is None
        else "p.event_id IN (SELECT event_id FROM extension_ids)"
    )
    if extended_ids is not None:
        con.register("extension_ids", pd.DataFrame({"event_id": sorted(extended_ids)}))
    frame = con.execute(
        f"""
        SELECT p.event_id,p.trade_date,p.cal_idx,p.open,p.high,p.low,p.close,
          p.coord_open,p.coord_high,p.coord_low,p.coord_close,p.invalid_step_cum,
          p.coordinate_factor,p.trade_status,p.current_day_data_tradable,
          p.current_valid,p.market_rule_valid,p.corporate_action_count,
          p.corporate_action_valid,p.corporate_action_blocking,p.hard_valid,
          p.up_limit_price,p.down_limit_price,p.available_at,p.decision_at
        FROM read_parquet('{PATHS.as_posix()}') p
        JOIN candidate_frame c USING(event_id)
        WHERE {where} AND p.trade_date<=DATE '2020-12-31'
        ORDER BY p.event_id,p.cal_idx
        """
    ).fetch_df()
    con.close()
    for column in ("trade_date", "available_at", "decision_at"):
        frame[column] = pd.to_datetime(frame[column])
    if not frame.empty and frame.trade_date.max() > MAX_OUTCOME_DATE:
        raise ResearchError("post-2020 path opened")
    return frame


def load_regime() -> tuple[dict[pd.Timestamp, Any], dict[str, Any]]:
    frame = pd.read_parquet(REGIME)
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    frame["latest_source_timestamp"] = pd.to_datetime(frame.latest_source_timestamp)
    frame = frame.loc[frame.trade_date.le(MAX_OUTCOME_DATE)].copy()
    if frame.trade_date.duplicated().any():
        raise ResearchError("duplicate market state date")
    if frame.latest_source_timestamp.dt.normalize().gt(frame.trade_date).any():
        raise ResearchError("market state source after state date")
    lookup = {
        pd.Timestamp(row.trade_date): row for row in frame.itertuples(index=False)
    }
    audit = {
        "maximum_market_state_date_read": str(frame.trade_date.max().date()),
        "market_state_rows": int(len(frame)),
        "market_source_after_state_date_count": int(
            frame.latest_source_timestamp.dt.normalize().gt(frame.trade_date).sum()
        ),
    }
    return lookup, audit


def run_replay(candidates: pd.DataFrame, regime_lookup: dict[pd.Timestamp, Any]) -> pd.DataFrame:
    short = load_paths(candidates)
    short_groups = {key: part for key, part in short.groupby("event_id", sort=False)}
    rows = [
        replay_one(
            candidate,
            short_groups.get(str(candidate.event_id), pd.DataFrame()),
            regime_lookup,
            allow_extension=False,
        )
        for candidate in candidates.itertuples(index=False)
    ]
    extension_ids = {
        str(row["event_id"]) for row in rows if row["status"] == "NEEDS_EXTENSION"
    }
    if extension_ids:
        extended = load_paths(candidates, extended_ids=extension_ids)
        extended_groups = {
            key: part for key, part in extended.groupby("event_id", sort=False)
        }
        candidate_by_id = {
            str(row.event_id): row for row in candidates.itertuples(index=False)
        }
        replacement = {
            event_id: replay_one(
                candidate_by_id[event_id],
                extended_groups.get(event_id, pd.DataFrame()),
                regime_lookup,
                allow_extension=True,
            )
            for event_id in extension_ids
        }
        rows = [replacement.get(str(row["event_id"]), row) for row in rows]
    frame = pd.DataFrame(rows).sort_values(
        ["signal_date", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if len(frame) != EXPECTED_EVENTS or frame.event_id.duplicated().any():
        raise ResearchError("replay identity drift")
    return frame


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")].copy()
    values = pd.to_numeric(completed.net_return, errors="coerce")
    return {
        "completed": int(len(completed)),
        "signal_dates": int(completed.signal_date.nunique()),
        "symbols": int(completed.symbol.nunique()),
        "mean_net": None if completed.empty else float(values.mean()),
        "median_net": None if completed.empty else float(values.median()),
        "win_rate": None if completed.empty else float(values.gt(0).mean()),
        "severe10": None if completed.empty else float(values.le(-0.10).mean()),
        "mean_holding_market_sessions": (
            None
            if completed.empty
            else float(completed.holding_market_sessions.mean())
        ),
        "structural_exit_share": (
            None
            if completed.empty
            else float(
                completed.exit_reason.eq("TWO_CLOSES_BELOW_EVENT_HIGH").mean()
            )
        ),
    }


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    yearly = {
        str(year): metrics(frame.loc[frame.signal_date.dt.year.eq(year)])
        for year in DEVELOPMENT_YEARS
    }
    gate_by_year = {
        str(year): {
            "completed_gt_50": yearly[str(year)]["completed"] > 50,
            "mean_net_gt_4pct": yearly[str(year)]["mean_net"] is not None
            and yearly[str(year)]["mean_net"] > 0.04,
            "median_net_positive": yearly[str(year)]["median_net"] is not None
            and yearly[str(year)]["median_net"] > 0,
        }
        for year in DEVELOPMENT_YEARS
    }
    gate_pass = all(all(item.values()) for item in gate_by_year.values())
    return {
        "mother_events": int(len(frame)),
        "status_counts": {
            str(key): int(value) for key, value in frame.status.value_counts().items()
        },
        "pooled": metrics(frame),
        "yearly": yearly,
        "market_routes": {
            str(key): metrics(part)
            for key, part in frame.groupby("market_route", dropna=False, sort=True)
        },
        "gate_by_year": gate_by_year,
        "full_development_gate_pass": gate_pass,
    }


def audit(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")].copy()
    result = {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "completed_entry_not_after_confirmation_count": int(
            completed.entry_date.le(completed.confirmation_date).sum()
        ),
        "completed_exit_not_after_entry_count": int(
            completed.exit_date.le(completed.entry_date).sum()
        ),
        "market_source_after_confirmation_count": int(
            completed.market_latest_source_timestamp.gt(
                completed.confirmation_date + pd.Timedelta(hours=15)
            ).sum()
        ),
        "post_2020_signal_count": int(frame.signal_date.gt(MAX_OUTCOME_DATE).sum()),
        "post_2020_confirmation_count": int(
            pd.to_datetime(frame.confirmation_date).gt(MAX_OUTCOME_DATE).sum()
        ),
        "post_2020_exit_count": int(completed.exit_date.gt(MAX_OUTCOME_DATE).sum()),
        "remaining_needs_extension_count": int(
            frame.status.eq("NEEDS_EXTENSION").sum()
        ),
    }
    if any(result.values()):
        raise ResearchError(f"causal audit failed: {result}")
    return result


def render_report(payload: dict[str, Any]) -> str:
    summary = payload["development_summary"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"`{payload['verdict']}`",
        "",
        "## Frozen five-rule lifecycle",
        "",
        "1. The exact high-transfer/low-displacement mother event is an observation seed, not a buy.",
        "2. The seed expires after ten sessions unless at least three of the exact last five valid closes, including the current close, are above the frozen event high.",
        "3. A causal BULL state is admitted; TRANSITION/BEAR also requires both 20-vs-60 return and breadth repair at confirmation.",
        "4. Buy only at the next legal open; two consecutive completed closes below the event high trigger the next legal-open exit, with no re-entry.",
        "5. Otherwise exit at the first legal open on or after H60; deduct 40 bps round trip.",
        "",
        "## One-shot development result",
        "",
        "|Signal year|Completed|Mean net|Median net|Win|Severe <= -10%|Mean hold|Gate|",
        "|---:|---:|---:|---:|---:|---:|---:|:---|",
    ]
    for year in DEVELOPMENT_YEARS:
        item = summary["yearly"][str(year)]
        gate = summary["gate_by_year"][str(year)]
        lines.append(
            f"|{year}|{item['completed']}|{item['mean_net']:.2%}|{item['median_net']:.2%}|"
            f"{item['win_rate']:.2%}|{item['severe10']:.2%}|"
            f"{item['mean_holding_market_sessions']:.1f}|"
            f"{'PASS' if all(gate.values()) else 'FAIL'}|"
        )
    pooled = summary["pooled"]
    lines.extend(
        [
            "",
            "## Pooled and governance",
            "",
            f"- Completed: {pooled['completed']:,}.",
            f"- Mean / median net: {pooled['mean_net']:.2%} / {pooled['median_net']:.2%}.",
            f"- Win / severe-loss rate: {pooled['win_rate']:.2%} / {pooled['severe10']:.2%}.",
            f"- Structural-exit share: {pooled['structural_exit_share']:.2%}.",
            f"- Full every-year gate: **{'PASS' if summary['full_development_gate_pass'] else 'FAIL'}**.",
            "- 2021 and later signals/outcomes were not read. 2022-2024 remains sealed.",
            "- This post-hoc chart-compressed result is not independent confirmation.",
            "",
            "No threshold, horizon, state rule, or exit was rescued after this result.",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates = load_candidates()
    regime_lookup, regime_audit = load_regime()
    ledger = run_replay(candidates, regime_lookup)
    causal_audit = audit(ledger)
    summary = summarize(ledger)
    write_parquet(ledger, LEDGER)
    verdict = (
        "DEVELOPMENT_GATE_PASS_2022_2024_MAY_BE_OPENED_SEPARATELY"
        if summary["full_development_gate_pass"]
        else "DEVELOPMENT_GATE_FAIL_CLOSE_EXACT_FAMILY"
    )
    payload = {
        "experiment": EXPERIMENT,
        "scientific_status": "POST_HOC_CHART_COMPRESSED_DEVELOPMENT_TEST",
        "verdict": verdict,
        "rules_spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes,
        "ledger_path": str(LEDGER),
        "ledger_sha256": sha256(LEDGER),
        "development_summary": summary,
        "causal_audit": causal_audit,
        "regime_audit": regime_audit,
        "maximum_outcome_date": str(MAX_OUTCOME_DATE.date()),
        "post_2020_signal_or_outcome_read": "NO",
        "2022_2024_opened": "NO",
        "neighboring_threshold_rescue": "NO",
    }
    write_json(MANIFEST, payload)
    payload["manifest_sha256"] = sha256(MANIFEST)
    write_json(RESULT, payload)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render_report(payload), encoding="utf-8")
    payload["result_sha256"] = sha256(RESULT)
    payload["report_sha256"] = sha256(REPORT)
    return payload


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
