#!/usr/bin/env python3
"""Execute the preregistered action-safe T+1 entry-gap attribution."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
if str(WORK / "scripts") not in sys.path:
    sys.path.insert(0, str(WORK / "scripts"))

import run_phase2_feature_library as phase2  # noqa: E402
import run_post_entry_landmark_emergence as landmark  # noqa: E402
import run_winner_loser_trajectory_archaeology as wla  # noqa: E402

SPEC = WORK / "experiments/EXP-EGP-001_spec.json"
BOUNDARY_TABLE = WORK / "artifacts/false_breakout_boundary_attribution.csv"
BOUNDARY_RESULT = WORK / "artifacts/false_breakout_boundary_falsification.json"
TRANSITIONS = WORK / "artifacts/pre_entry_transitions.csv"
INDEX_BARS = ROOT / "research/chinext_v1/data/smoke/399102_daily.csv"
LEDGERS = {
    "EXTENDED_2018_2021": ROOT
    / "research/chinext_v1/data/execution_ledgers/extended_execution_ledger.jsonl",
    "HOLDOUT_O0_2022_2023": ROOT
    / "research/chinext_v1/data/execution_ledgers/holdout_execution_ledger.jsonl",
    "DEVELOPMENT_2024_2025": ROOT
    / "research/chinext_v1/data/execution_ledgers/development_execution_ledger.jsonl",
}
OUTPUT_TABLE = WORK / "artifacts/entry_gap_premium_attribution.csv"
OUTPUT_JSON = WORK / "artifacts/entry_gap_premium_attribution.json"
REPORT = WORK / "reports/entry_gap_premium_attribution.md"


class EntryGapError(RuntimeError):
    """Raised when a frozen identity, fill, or action-coordinate invariant fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def excess_log_gap(stock_log_gap: pd.Series, market_log_gap: pd.Series) -> pd.Series:
    return stock_log_gap.astype(float) - market_log_gap.astype(float)


def validate_spec() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-EGP-001":
        raise EntryGapError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_ENTRY_GAP_OUTCOME_TEST":
        raise EntryGapError("experiment is not frozen before results")
    identities: dict[str, str] = {}
    mismatch: dict[str, Any] = {}
    for name, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise EntryGapError(f"missing bound input: {name}: {path}")
        actual = sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatch[name] = {"expected": binding["sha256"], "actual": actual}
    if mismatch:
        raise EntryGapError(f"frozen input mismatch: {mismatch}")
    return spec, identities


def load_entry_fills(frame: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for block, path in LEDGERS.items():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if not (
                row.get("status") == "FILLED"
                and row.get("side") == "BUY"
                and row.get("new_position") is True
            ):
                continue
            records.append(
                {
                    "baseline_block": block,
                    "symbol": str(row["symbol"]),
                    "entry_signal_date": str(row["signal_date"]),
                    "entry_execution_date": str(row["execution_date"]),
                    "execution_open": float(row["execution_open"]),
                    "execution_price": float(row["execution_price"]),
                    "entry_fill_snapshot_id": str(row["snapshot_id"]),
                }
            )
    entries = pd.DataFrame(records)
    keys = [
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
    ]
    if entries.duplicated(keys).any():
        raise EntryGapError("duplicate entry-fill identity")
    result = frame.merge(entries, on=keys, how="left", validate="one_to_one")
    if result.execution_price.isna().any():
        raise EntryGapError("completed cycle is missing its exact entry fill")
    return result


def action_safe_entry_rows(
    identities: pd.DataFrame, spec: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    expected = spec["transient_contract"]
    with tempfile.TemporaryDirectory(prefix="chinext_v1_egp001_") as temporary:
        transient_root = Path(temporary)
        manifest = phase2.extended.materialize_transient_inputs(transient_root)
        if manifest["canonical_sha256"] != expected["canonical_sha256"]:
            raise EntryGapError("transient canonical identity changed")
        if manifest["membership"]["sha256"] != expected["membership_sha256"]:
            raise EntryGapError("transient membership identity changed")
        connection = phase2.duckdb.connect()
        connection.execute("SET threads=1")
        phase2.create_membership_tables(
            connection, transient_root / "daily_membership.parquet"
        )
        panel_counts = phase2.create_panel_tables(connection, transient_root)
        phase2.create_stock_features(connection)
        connection.register("entry_ids", identities)
        rows = connection.execute(
            """
            WITH mapped AS (
              SELECT i.*,s.cal_idx AS signal_idx,e.cal_idx AS execution_idx
              FROM entry_ids i
              JOIN calendar s ON CAST(i.entry_signal_date AS DATE)=s.trade_date
              JOIN calendar e ON CAST(i.entry_execution_date AS DATE)=e.trade_date
            ), base AS (
              SELECT m.*,s.critical_valid AS signal_valid,
                     s.adjusted_close AS signal_adjusted_close,
                     e.critical_valid AS execution_valid,
                     e.open AS panel_execution_open,e.close AS execution_close,
                     e.adjusted_close AS execution_adjusted_close
              FROM mapped m
              JOIN stock_windows s
                ON s.baseline_block=m.baseline_block AND s.symbol=m.symbol
               AND s.cal_idx=m.signal_idx
              JOIN stock_windows e
                ON e.baseline_block=m.baseline_block AND e.symbol=m.symbol
               AND e.cal_idx=m.execution_idx
            )
            SELECT b.*,
              (SELECT count(*) FROM stock_windows w
                WHERE w.baseline_block=b.baseline_block AND w.symbol=b.symbol
                  AND w.cal_idx>b.signal_idx AND w.cal_idx<=b.execution_idx) AS step_count,
              (SELECT count(*) FROM stock_windows w
                WHERE w.baseline_block=b.baseline_block AND w.symbol=b.symbol
                  AND w.cal_idx>b.signal_idx AND w.cal_idx<=b.execution_idx
                  AND w.coordinate_step_valid IS NOT TRUE) AS invalid_step_count,
              (SELECT coalesce(sum(coalesce(w.corporate_action_count,0)),0)
                 FROM stock_windows w
                WHERE w.baseline_block=b.baseline_block AND w.symbol=b.symbol
                  AND w.cal_idx>b.signal_idx AND w.cal_idx<=b.execution_idx) AS action_count
            FROM base b ORDER BY trade_id
            """
        ).fetchdf()
        connection.close()
    if len(rows) != 399 or rows.trade_id.nunique() != 399:
        raise EntryGapError("action-safe entry rows are not 399 unique cycles")
    audit = {
        "transient_canonical_sha256": manifest["canonical_sha256"],
        "transient_membership_sha256": manifest["membership"]["sha256"],
        "panel_counts": panel_counts,
    }
    return rows, audit


def load_frame(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    upstream = json.loads(BOUNDARY_RESULT.read_text(encoding="utf-8"))
    if (
        upstream.get("experiment_id") != "EXP-FBB-001"
        or upstream.get("decision") != "DEEPEN"
        or upstream.get("strategy_modification") != "NONE"
    ):
        raise EntryGapError("accepted false-breakout result identity/status changed")
    path = pd.read_csv(BOUNDARY_TABLE)
    if len(path) != 399 or path.trade_id.nunique() != 399:
        raise EntryGapError("accepted boundary table is not 399 unique cycles")
    controls = pd.read_csv(TRANSITIONS)
    if len(controls) != 399 or controls.trade_id.nunique() != 399:
        raise EntryGapError("accepted controls are not 399 unique cycles")
    control_columns = [
        "trade_id",
        "entry_signal_date",
        "entry_execution_date",
        *landmark.BASE_CONTROLS,
    ]
    frame = path.merge(
        controls[control_columns], on="trade_id", how="left", validate="one_to_one"
    )
    frame = load_entry_fills(frame)
    identity_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
    ]
    panel, panel_audit = action_safe_entry_rows(frame[identity_columns], spec)
    frame = frame.merge(panel, on=identity_columns, how="left", validate="one_to_one")
    if not frame.signal_valid.astype(bool).all() or not frame.execution_valid.astype(bool).all():
        raise EntryGapError("signal/execution bar is not hard-valid")
    if int(frame.invalid_step_count.sum()) != 0 or not frame.step_count.eq(1).all():
        raise EntryGapError("entry is not one valid action-safe T+1 coordinate step")
    if not (frame.execution_open == frame.panel_execution_open).all():
        raise EntryGapError("ledger execution open differs from action-safe panel open")
    if not (frame.execution_price == frame.execution_open).all():
        raise EntryGapError("a completed entry did not fill exactly at execution open")
    positive = [
        "execution_open",
        "execution_price",
        "signal_adjusted_close",
        "execution_close",
        "execution_adjusted_close",
    ]
    if (frame[positive] <= 0).any().any():
        raise EntryGapError("non-positive price in entry-gap construction")
    index = pd.read_csv(INDEX_BARS, dtype={"trade_date": str})
    index["trade_date"] = pd.to_datetime(index.trade_date, format="%Y%m%d").dt.strftime(
        "%Y-%m-%d"
    )
    index_close = dict(zip(index.trade_date, index.close.astype(float), strict=True))
    index_open = dict(zip(index.trade_date, index.open.astype(float), strict=True))
    frame["market_signal_close"] = frame.entry_signal_date.map(index_close)
    frame["market_execution_open"] = frame.entry_execution_date.map(index_open)
    if frame[["market_signal_close", "market_execution_open"]].isna().any().any():
        raise EntryGapError("399102 entry-gap coverage is incomplete")
    frame["adjusted_execution_open"] = (
        frame.execution_adjusted_close * frame.execution_open / frame.execution_close
    )
    frame["stock_entry_gap_log"] = np.log(
        frame.adjusted_execution_open / frame.signal_adjusted_close
    )
    frame["market_entry_gap_log"] = np.log(
        frame.market_execution_open / frame.market_signal_close
    )
    frame["excess_entry_gap_log"] = excess_log_gap(
        frame.stock_entry_gap_log, frame.market_entry_gap_log
    )
    frame["excess_entry_gap_simple"] = np.expm1(frame.excess_entry_gap_log)
    frame["intraday_fill_premium"] = frame.execution_price / frame.execution_open - 1.0
    required = [
        "stock_entry_gap_log",
        "market_entry_gap_log",
        "excess_entry_gap_log",
        "excess_entry_gap_simple",
        "intraday_fill_premium",
    ]
    if not np.isfinite(frame[required].to_numpy(float)).all():
        raise EntryGapError("nonfinite entry-gap result")
    if frame.intraday_fill_premium.abs().max() != 0.0:
        raise EntryGapError("intraday fill premium must be exactly zero")
    if int(frame.false_breakout.astype(bool).sum()) != 213:
        raise EntryGapError("false-breakout endpoint count changed")
    audit = {
        **panel_audit,
        "cycles": int(len(frame)),
        "false_breakouts": int(frame.false_breakout.astype(bool).sum()),
        "entry_fill_rows_in_ledgers": 409,
        "completed_entry_fills_joined": 399,
        "signal_and_execution_valid": 399,
        "invalid_coordinate_steps": 0,
        "t1_step_count": 399,
        "execution_open_mismatches": 0,
        "nonzero_intraday_fill_premiums": 0,
        "action_event_cycles": int((frame.action_count > 0).sum()),
        "index_coverage": 399,
        "post_entry_rows_read": 0,
        "strategy_replays": 0,
        "entry_or_exit_rules_tested": 0,
    }
    return frame, audit


def partial_rank(
    frame: pd.DataFrame,
    *,
    duration_exit: bool = False,
) -> dict[str, Any]:
    extra = ["market_entry_gap_log"]
    categories = ["entry_year"]
    if duration_exit:
        extra.append("holding_trading_days")
        categories.append("canonical_exit_reason")
    return landmark.partial_rank(
        frame,
        "excess_entry_gap_log",
        "false_breakout",
        extra_controls=tuple(extra),
        category_controls=tuple(categories),
    )


def controlled_loyo(
    frame: pd.DataFrame,
    *,
    duration_exit: bool = False,
) -> dict[str, Any]:
    full = partial_rank(frame, duration_exit=duration_exit)
    loyo = {
        str(year): partial_rank(
            frame[frame.entry_year != year], duration_exit=duration_exit
        )
        for year in range(2018, 2026)
    }
    positive = sum(
        item["partial_rank_rho"] is not None and item["partial_rank_rho"] > 0
        for item in loyo.values()
    )
    return {**full, "loyo": loyo, "loyo_positive_count": int(positive)}


def deterministic_absolute_top_flag(frame: pd.DataFrame, n: int) -> pd.Series:
    ordered = frame.assign(_abs=frame.excess_entry_gap_log.abs()).sort_values(
        ["_abs", "trade_id"], ascending=[False, True], kind="mergesort"
    )
    flag = pd.Series(False, index=frame.index)
    flag.loc[ordered.head(n).index] = True
    return flag


def deterministic_bottom_pnl_flag(frame: pd.DataFrame, n: int) -> pd.Series:
    ordered = frame.sort_values(
        ["realized_pnl", "trade_id"], ascending=[True, True], kind="mergesort"
    )
    flag = pd.Series(False, index=frame.index)
    flag.loc[ordered.head(n).index] = True
    return flag


def analyze(frame: pd.DataFrame) -> dict[str, Any]:
    feature = "excess_entry_gap_log"
    raw = wla.rank_association(frame, feature, "false_breakout")
    controlled = controlled_loyo(frame)
    duration_exit = controlled_loyo(frame, duration_exit=True)
    stock_gap_neighbor = wla.rank_association(
        frame, "stock_entry_gap_log", "false_breakout"
    )
    topology = wla.rank_association(frame, feature, "oriented_order")
    abs_top4 = deterministic_absolute_top_flag(frame, 4)
    ex_abs_top4 = wla.rank_association(
        frame.loc[~abs_top4], feature, "false_breakout"
    )
    bottom4 = deterministic_bottom_pnl_flag(frame, 4)
    ex_bottom4 = wla.rank_association(
        frame.loc[~bottom4], feature, "false_breakout"
    )
    no_action = wla.rank_association(
        frame.loc[frame.action_count == 0], feature, "false_breakout"
    )
    security = wla.omit_group_sensitivity(
        frame, feature, "false_breakout", "symbol"
    )
    industry = wla.omit_group_sensitivity(
        frame[frame.entry_industry.notna()],
        feature,
        "false_breakout",
        "entry_industry",
    )
    blocks = {
        str(name): wla.safe_spearman(rows[feature], rows.false_breakout)
        for name, rows in frame.groupby("baseline_block", sort=True)
    }
    yearly = {
        str(year): wla.safe_spearman(rows[feature], rows.false_breakout)
        for year, rows in frame.groupby("entry_year", sort=True)
    }
    raw_gate = bool(
        raw["rho"] is not None
        and raw["rho"] >= 0.10
        and raw["within_year_rank_rho"] is not None
        and raw["within_year_rank_rho"] > 0
        and raw["loyo_positive_count"] >= 7
    )
    controlled_gate = bool(
        controlled["partial_rank_rho"] is not None
        and controlled["partial_rank_rho"] >= 0.10
        and controlled["loyo_positive_count"] >= 7
    )
    topology_gate = bool(
        topology["rho"] is not None
        and topology["rho"] >= 0.10
        and topology["within_year_rank_rho"] is not None
        and topology["within_year_rank_rho"] > 0
        and topology["loyo_positive_count"] >= 7
    )
    neighbor_gate = bool(
        stock_gap_neighbor["rho"] is not None
        and stock_gap_neighbor["rho"] > 0
        and stock_gap_neighbor["loyo_positive_count"] >= 6
    )
    positive_blocks = sum(
        item["rho"] is not None and item["rho"] > 0 for item in blocks.values()
    )
    falsification_gate = bool(
        ex_abs_top4["rho"] is not None
        and ex_abs_top4["rho"] >= 0.05
        and ex_bottom4["rho"] is not None
        and ex_bottom4["rho"] >= 0.05
        and no_action["rho"] is not None
        and no_action["rho"] >= 0.05
        and duration_exit["partial_rank_rho"] is not None
        and duration_exit["partial_rank_rho"] >= 0.05
        and security["positive_fraction"] is not None
        and security["positive_fraction"] >= 0.80
        and industry["positive_fraction"] is not None
        and industry["positive_fraction"] >= 0.80
        and positive_blocks >= 2
    )
    if raw_gate and controlled_gate and topology_gate and neighbor_gate and falsification_gate:
        decision = "DEEPEN"
        verdict = "STOCK_SPECIFIC_T1_GAP_CONTRIBUTES_TO_FALSE_BREAKOUT_TOPOLOGY"
    elif raw_gate and controlled_gate:
        decision = "REFINE"
        verdict = "ENTRY_GAP_ASSOCIATES_WITH_FALSE_BREAKOUT_BUT_NOT_FULL_TOPOLOGY"
    elif raw_gate:
        decision = "PIVOT"
        verdict = "RAW_ENTRY_GAP_IS_REDUNDANT_WITH_MARKET_OR_PREENTRY_STATE"
    else:
        decision = "REJECT"
        verdict = "ENTRY_GAP_DOES_NOT_EXPLAIN_FALSE_BREAKOUT_TOPOLOGY"
    secondary = {
        endpoint: wla.rank_association(frame, feature, endpoint)
        for endpoint in ("mfe", "round_trip_return")
    }
    return {
        "experiment_id": "EXP-EGP-001",
        "decision": decision,
        "mechanism_verdict": verdict,
        "primary": {
            "raw": raw,
            "controlled_preentry_market": controlled,
            "controlled_duration_exit": duration_exit,
            "stock_gap_neighbor": stock_gap_neighbor,
            "false_breakout_topology": topology,
            "ex_absolute_top1pct_gap": ex_abs_top4,
            "ex_global_bottom1pct_pnl": ex_bottom4,
            "no_corporate_action_step": no_action,
            "leave_one_security_out": security,
            "leave_one_industry_out": industry,
            "baseline_block": blocks,
            "yearly": yearly,
            "raw_gate": raw_gate,
            "controlled_gate": controlled_gate,
            "topology_gate": topology_gate,
            "neighbor_gate": neighbor_gate,
            "falsification_gate": falsification_gate,
        },
        "secondary": secondary,
        "primary_feature": "log(stock T+1 execution-open / signal close, action-safe) minus log(399102 T+1 open / signal close)",
        "implementation_finding": "all 399 completed entries filled exactly at the execution-session open; intraday fill premium has zero variation",
        "interpretation_boundary": "entry-gap attribution is observational on already-consumed outcomes and does not authorize avoiding or resizing gap-up fills",
        "strategy_modification": "NONE",
    }


def fmt(value: Any, digits: int = 3) -> str:
    number = wla.finite_or_none(value)
    return "NA" if number is None else f"{number:.{digits}f}"


def build_report(audit: dict[str, Any], result: dict[str, Any]) -> str:
    p = result["primary"]
    lines = [
        "# Action-safe T+1 entry-gap attribution",
        "",
        "EXP-EGP-001 tests whether a stock-specific signal-close-to-T+1-open gap contributes to the supported false-breakout topology. It does not test a gap filter or alternate fill.",
        "",
        "## Execution and coordinate audit",
        "",
        f"- Completed cycles / exact fills / hard-valid signal+execution bars: `{audit['cycles']}` / `{audit['completed_entry_fills_joined']}` / `{audit['signal_and_execution_valid']}`.",
        f"- Invalid coordinate steps / execution-open mismatches / nonzero intraday fill premiums: `{audit['invalid_coordinate_steps']}` / `{audit['execution_open_mismatches']}` / `{audit['nonzero_intraday_fill_premiums']}`.",
        f"- Action-event cycles / index-covered cycles: `{audit['action_event_cycles']}` / `{audit['index_coverage']}`.",
        "- Every completed entry fills exactly at the T+1 session open. The varying feature is therefore the action-safe overnight gap relative to 399102, not execution slippage.",
        "",
        "## Preregistered primary",
        "",
        "| Raw rho | Within-year | LOYO + | Controlled rho | LOYO + | Duration/exit rho | Topology rho | Stock-gap neighbor rho |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {fmt(p['raw']['rho'])} | {fmt(p['raw']['within_year_rank_rho'])} | {p['raw']['loyo_positive_count']}/8 | "
        f"{fmt(p['controlled_preentry_market']['partial_rank_rho'])} | {p['controlled_preentry_market']['loyo_positive_count']}/8 | "
        f"{fmt(p['controlled_duration_exit']['partial_rank_rho'])} | "
        f"{fmt(p['false_breakout_topology']['rho'])} | {fmt(p['stock_gap_neighbor']['rho'])} |",
        "",
        "## Frozen gates",
        "",
        f"- Raw / controlled / topology / neighbor / falsification: `{'PASS' if p['raw_gate'] else 'FAIL'}` / `{'PASS' if p['controlled_gate'] else 'FAIL'}` / `{'PASS' if p['topology_gate'] else 'FAIL'}` / `{'PASS' if p['neighbor_gate'] else 'FAIL'}` / `{'PASS' if p['falsification_gate'] else 'FAIL'}`.",
        "",
        "## Scientific decision",
        "",
        f"`{result['decision']}` / `{result['mechanism_verdict']}`.",
        "",
        "A surviving relationship would be entry-timing attribution, not evidence that a gap filter improves V1. No counterfactual fill, ranking, or portfolio replay is present.",
        "",
        "## Strategy candidate",
        "",
        "None. No entry, exit, filter, sizing, ranking, or production change was tested or authorized.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    spec, identities = validate_spec()
    frame, audit = load_frame(spec)
    result = analyze(frame)
    result.update(
        {
            "spec_sha256": sha256_file(SPEC),
            "input_identities": identities,
            "audit": audit,
            "evidence_grade": "EXPLORATORY_ENTRY_TIMING_MECHANISM",
            "breadth_h004_status": "PROSPECTIVE_VALIDATION_PENDING_FROZEN",
        }
    )
    output_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
        "entry_year",
        "entry_industry",
        "execution_open",
        "execution_price",
        "stock_entry_gap_log",
        "market_entry_gap_log",
        "excess_entry_gap_log",
        "excess_entry_gap_simple",
        "intraday_fill_premium",
        "action_count",
        "false_breakout",
        "oriented_order",
        "mfe",
        "round_trip_return",
        "realized_pnl",
        "holding_trading_days",
        "canonical_exit_reason",
    ]
    atomic_write(
        OUTPUT_TABLE,
        frame[output_columns].sort_values("trade_id").to_csv(
            index=False, lineterminator="\n", float_format="%.17g"
        ),
    )
    atomic_write(
        OUTPUT_JSON, json.dumps(wla.clean_json(result), indent=2, sort_keys=True) + "\n"
    )
    atomic_write(REPORT, build_report(audit, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
