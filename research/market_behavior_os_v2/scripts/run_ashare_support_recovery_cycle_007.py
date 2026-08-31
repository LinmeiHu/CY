#!/usr/bin/env python3
# ruff: noqa: E501
"""Run the frozen stock-level objective support/recovery discovery cycle."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-SUPPORT-RECOVERY-CYCLE-007_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-SUPPORT-RECOVERY-CYCLE-007_result.json"
PANEL_PATH = PROGRAM / "artifacts/ASHARE-SUPPORT-RECOVERY-CYCLE-007_panel.csv"
SUMMARY_PATH = PROGRAM / "artifacts/ASHARE-SUPPORT-RECOVERY-CYCLE-007_summary.csv"
EQUITY_PATH = PROGRAM / "artifacts/ASHARE-SUPPORT-RECOVERY-CYCLE-007_equity.csv"
EXIT_PATH = PROGRAM / "artifacts/ASHARE-SUPPORT-RECOVERY-CYCLE-007_risk_exits.csv"
REPORT_PATH = PROGRAM / "reports/ASHARE-SUPPORT-RECOVERY-CYCLE-007_report.md"
CYCLE5_PATH = PROGRAM / "scripts/run_ashare_external_prior_cycle_005.py"
EXPECTED_SPEC_SHA256 = "8c54f12db6e91246d84e14a12b159d8db8df3ed8b412a5b465ca378fb506165c"


class Cycle007Error(RuntimeError):
    """Fail-closed cycle error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Cycle007Error(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CYCLE5 = _load_module("ashare_cycle_005_for_007", CYCLE5_PATH)


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise Cycle007Error("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text())
    if spec["status"] != "FROZEN_ALL_HYPOTHESES_BEFORE_FORWARD_OUTCOME_ACCESS":
        raise Cycle007Error("hypotheses were not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise Cycle007Error(f"bound input changed: {name}")
    return spec


def _build_frame(
    paths: list[Path], temp_path: Path
) -> tuple[pd.DataFrame, list[date], dict[str, Any]]:
    con = duckdb.connect()
    con.execute("SET memory_limit='6GB'")
    con.execute("SET threads=1")
    con.execute(f"SET temp_directory='{temp_path.as_posix()}'")
    con.from_parquet([str(path) for path in paths], union_by_name=True).create_view("daily")
    audit_row = con.execute("""SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
      sum((available_at>decision_at)::INTEGER),
      sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER) FROM daily""").fetchone()
    audit = dict(
        zip(
            ("rows", "symbols", "first", "last", "time_travel", "lineage_failures"),
            (
                int(audit_row[0]),
                int(audit_row[1]),
                str(audit_row[2]),
                str(audit_row[3]),
                int(audit_row[4]),
                int(audit_row[5]),
            ),
            strict=True,
        )
    )
    expected = {
        "rows": 6155390,
        "symbols": 5262,
        "first": "2018-01-02",
        "last": "2023-12-29",
        "time_travel": 0,
        "lineage_failures": 0,
    }
    if audit != expected:
        raise Cycle007Error(f"daily source audit changed: {audit}")
    con.execute("""CREATE TEMP TABLE calendar AS SELECT trade_date,
      row_number() OVER (ORDER BY trade_date)-1 cal_idx
      FROM (SELECT DISTINCT trade_date FROM daily) ORDER BY trade_date""")
    calendar = [
        row[0] for row in con.execute("SELECT trade_date FROM calendar ORDER BY cal_idx").fetchall()
    ]
    con.execute("""CREATE TEMP TABLE base AS SELECT d.*,c.cal_idx,
      (d.hard_valid IS TRUE AND d.bar_valid IS TRUE AND d.trading_state_valid IS TRUE
       AND d.industry_valid IS TRUE AND d.float_valid IS TRUE
       AND d.corporate_action_valid IS TRUE AND d.market_valid IS TRUE
       AND d.market_rule_valid IS TRUE AND d.historical_identity_valid IS TRUE
       AND d.corporate_action_blocking IS FALSE AND coalesce(d.rights_ratio,0)=0
       AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
       AND d.open>0 AND d.high>=greatest(d.open,d.close)
       AND d.low<=least(d.open,d.close) AND d.close>0 AND d.volume>=0 AND d.amount>=0) history_valid,
      (d.hard_valid IS TRUE AND d.trade_status=1 AND d.current_day_data_tradable IS TRUE
       AND d.is_st IS FALSE) current_valid,
      lag(d.close) OVER w previous_close,lag(c.cal_idx) OVER w previous_cal_idx,
      lag(history_valid) OVER w previous_history_valid
      FROM daily d JOIN calendar c USING(trade_date)
      WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)""")
    con.execute("""CREATE TEMP TABLE steps AS SELECT *,CASE
      WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
       AND coalesce(corporate_action_count,0)=0 THEN ln(close/previous_close)
      WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
       AND corporate_action_count>0 AND corporate_action_available_date IS NOT NULL
       AND corporate_action_available_date<=trade_date AND coalesce(rights_ratio,0)=0
       AND coalesce(share_multiplier,1)>0 AND previous_close-coalesce(cash_per_share,0)>0
      THEN ln(close/((previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)))
      ELSE NULL END step_return FROM base""")
    con.execute("""CREATE TEMP TABLE coordinates AS SELECT *,
      exp(sum(coalesce(step_return,0)) OVER (PARTITION BY symbol ORDER BY trade_date)) coordinate_close,
      exp(sum(coalesce(step_return,0)) OVER (PARTITION BY symbol ORDER BY trade_date))*low/close coordinate_low,
      exp(sum(coalesce(step_return,0)) OVER (PARTITION BY symbol ORDER BY trade_date))*high/close coordinate_high
      FROM steps""")
    con.execute("""CREATE TEMP TABLE rolling1 AS SELECT *,
      min(coordinate_low) OVER p20 support_l20,
      max(coordinate_high) OVER p60 resistance_h60,
      avg(volume) OVER p20 prior_volume20,
      avg(amount) OVER p20 avg_amount20,
      count(step_return) OVER w120 valid120,
      count(*) OVER p20 prior20_count,
      count(*) OVER p60 prior60_count,
      stddev_samp(step_return) OVER w120 return_sd120,
      skewness(step_return) OVER w60 return_skew60,
      median(step_return) OVER (PARTITION BY trade_date) market_step
      FROM coordinates WINDOW
      p20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
      p60 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING),
      w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW),
      w120 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW)""")
    con.execute("""CREATE TEMP TABLE rolling2 AS SELECT *,
      CASE WHEN coordinate_close>resistance_h60 AND coordinate_high>resistance_h60
        THEN resistance_h60 END breakout_level_today,
      covar_pop(step_return,market_step) FILTER (WHERE market_step<0) OVER w120
        /nullif(var_pop(market_step) FILTER (WHERE market_step<0) OVER w120,0) downside_beta120
      FROM rolling1 WINDOW w120 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW)""")
    con.execute("""CREATE TEMP TABLE features AS SELECT *,
      arg_max(breakout_level_today,cal_idx) FILTER (WHERE breakout_level_today IS NOT NULL)
        OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) recent_breakout_level
      FROM rolling2""")
    frame = con.execute("""SELECT * FROM features WHERE history_valid AND current_valid
      AND valid120=120 AND prior20_count=20 AND prior60_count=60 AND avg_amount20>=50000000
      AND cal_idx%5=0 ORDER BY trade_date,symbol""").fetchdf()
    con.close()
    if frame.empty or frame.duplicated(["symbol", "trade_date"]).any():
        raise Cycle007Error("invalid eligible frame")
    return frame, calendar, audit


def _hash_control(frame: pd.DataFrame, dates: set[Any]) -> pd.DataFrame:
    control = frame.loc[frame.trade_date.isin(dates)].copy()
    control["hash_order"] = control.apply(
        lambda r: hashlib.sha256(f"{r.symbol}|007|{r.trade_date}".encode()).hexdigest(), axis=1
    )
    return (
        control.sort_values(["trade_date", "hash_order", "symbol"])
        .groupby("trade_date", sort=True)
        .head(20)
    )


def _select(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    low = frame.coordinate_low / frame.support_l20
    close = frame.coordinate_close / frame.support_l20
    hold = low.between(1.0, 1.01, inclusive="both") & (close >= 1)
    reclaim = (low < 1) & (close >= 1)
    events = {
        "prior_low_hold": (hold, 1.01 - low),
        "prior_low_break_reclaim": (reclaim, close),
        "confirmed_breakdown": (close < 1, 1 - close),
        "quiet_support_hold": ((hold | reclaim) & (frame.volume <= frame.prior_volume20), close),
        "relative_support_hold": ((hold | reclaim) & (frame.market_step < 0), close),
        "breakout_level_retest": (
            frame.recent_breakout_level.notna()
            & (frame.coordinate_low <= frame.recent_breakout_level * 1.01)
            & (frame.coordinate_close >= frame.recent_breakout_level),
            frame.coordinate_close / frame.recent_breakout_level,
        ),
    }
    outputs = []
    diagnostics = []
    all_dates = set()
    for family, (mask, score) in events.items():
        work = frame.loc[mask].copy()
        work["signal_score"] = score.loc[mask]
        work["track"] = "support"
        work["family"] = family
        work["candidate_count"] = work.groupby("trade_date").symbol.transform("size")
        work = (
            work.sort_values(
                ["trade_date", "signal_score", "symbol"], ascending=[True, False, True]
            )
            .groupby("trade_date", sort=True)
            .head(20)
        )
        work["signal_rank"] = work.groupby("trade_date").cumcount() + 1
        outputs.append(work)
        all_dates.update(work.trade_date.tolist())
        diagnostics.append(
            {
                "family": family,
                "track": "support",
                "eligible_events": len(work),
                "decision_dates": int(work.trade_date.nunique()),
                "symbols": int(work.symbol.nunique()),
                "median_candidates": float(work.candidate_count.median()) if len(work) else 0.0,
            }
        )
    monthly = frame.loc[frame.cal_idx % 20 == 0]
    for family, score in {
        "low_downside_beta_120": -monthly.downside_beta120,
        "low_return_skewness_60": -monthly.return_skew60,
    }.items():
        work = monthly.loc[np.isfinite(score)].copy()
        work["signal_score"] = score.loc[work.index]
        work["track"] = "independent"
        work["family"] = family
        work["candidate_count"] = work.groupby("trade_date").symbol.transform("size")
        work = (
            work.sort_values(
                ["trade_date", "signal_score", "symbol"], ascending=[True, False, True]
            )
            .groupby("trade_date", sort=True)
            .head(20)
        )
        work["signal_rank"] = work.groupby("trade_date").cumcount() + 1
        outputs.append(work)
        all_dates.update(work.trade_date.tolist())
        diagnostics.append(
            {
                "family": family,
                "track": "independent",
                "eligible_events": len(work),
                "decision_dates": int(work.trade_date.nunique()),
                "symbols": int(work.symbol.nunique()),
                "median_candidates": float(work.candidate_count.median()),
            }
        )
    control = _hash_control(frame, all_dates)
    control["family"] = "date_control"
    control["track"] = "control"
    control["candidate_count"] = control.groupby("trade_date").symbol.transform("size")
    control["signal_score"] = np.nan
    control["signal_rank"] = control.groupby("trade_date").cumcount() + 1
    outputs.append(control)
    selection = pd.concat(outputs, ignore_index=True)
    selection["natural_horizon"] = 5
    selection["rebalance_sessions"] = selection.track.map(
        {"support": 5, "independent": 20, "control": 5}
    )
    selection["decision_at"] = pd.to_datetime(selection.trade_date) + pd.Timedelta(
        hours=15, minutes=30
    )
    columns = [
        "family",
        "track",
        "trade_date",
        "cal_idx",
        "decision_at",
        "available_at",
        "symbol",
        "industry",
        "signal_score",
        "signal_rank",
        "candidate_count",
        "avg_amount20",
        "natural_horizon",
        "rebalance_sessions",
    ]
    return selection[columns].sort_values(
        ["family", "trade_date", "signal_rank", "symbol"]
    ).reset_index(drop=True), pd.DataFrame(diagnostics)


def _summarize(
    panel: pd.DataFrame, diagnostics: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    controls = panel.loc[(panel.family == "date_control") & (panel.status_h5 == "COMPLETE")]
    control_net = controls.groupby("trade_date").net_return_h5.mean()
    control_severe = controls.groupby("trade_date").net_return_h5.apply(
        lambda x: float((x <= -0.10).mean())
    )
    rows = []
    for family, group in panel.loc[panel.family != "date_control"].groupby("family", sort=True):
        for period, mask in (
            ("full", pd.Series(True, index=group.index)),
            ("early_2018_2020", pd.to_datetime(group.trade_date).dt.year <= 2020),
            ("late_2021_2023", pd.to_datetime(group.trade_date).dt.year >= 2021),
        ):
            valid = group.loc[mask & group.status_h5.eq("COMPLETE")].copy()
            valid["control"] = valid.trade_date.map(control_net)
            valid["control_severe"] = valid.trade_date.map(control_severe)
            valid = valid.dropna(subset=["control", "control_severe"])
            net = valid.net_return_h5.astype(float)
            rows.append(
                {
                    "family": family,
                    "track": group.track.iloc[0],
                    "period": period,
                    "count": len(valid),
                    "signal_dates": int(valid.trade_date.nunique()),
                    "mean_net_return": net.mean(),
                    "median_net_return": net.median(),
                    "net_excess_vs_control": (net - valid.control).mean(),
                    "severe_loss_fraction": float((net <= -0.10).mean()),
                    "severe_loss_disadvantage": float(
                        (net <= -0.10).mean() - valid.control_severe.mean()
                    ),
                    "entry_executable_fraction": float(group.entry_status.eq("EXECUTABLE").mean()),
                    "median_candidate_count": float(group.candidate_count.median()),
                    "p10_entry_amount_cny": valid.entry_amount_h5.quantile(0.1),
                }
            )
    summary = pd.DataFrame(rows).sort_values(["family", "period"])
    diag = diagnostics.set_index("family").to_dict("index")
    decisions = []
    for family, group in summary.groupby("family", sort=True):
        x = group.set_index("period")
        full = x.loc["full"]
        early = x.loc["early_2018_2020"]
        late = x.loc["late_2021_2023"]
        downside = family == "confirmed_breakdown"

        def expected(value: float, *, is_downside: bool = downside) -> bool:
            return value < 0 if is_downside else value > 0

        gates = {
            "complete_positions": int(full["count"]) >= 300,
            "decision_dates_each_block": int(early.signal_dates) >= 20
            and int(late.signal_dates) >= 20,
            "entry_execution_fraction": float(full.entry_executable_fraction) >= 0.90,
            "expected_direction_full": expected(float(full.net_excess_vs_control)),
            "expected_direction_both_blocks": expected(float(early.net_excess_vs_control))
            and expected(float(late.net_excess_vs_control)),
            "severe_loss": True if downside else float(full.severe_loss_disadvantage) <= 0.02,
            "candidate_breadth": float(full.median_candidate_count) >= 3,
        }
        passes = all(gates.values())
        if passes:
            classification = "DOWNSIDE_PREDICTOR" if downside else "STANDALONE_ALPHA"
        elif float(early.net_excess_vs_control) * float(late.net_excess_vs_control) < 0:
            classification = "CHRONOLOGICALLY_MIXED"
        elif downside and float(full.net_excess_vs_control) < 0:
            classification = "DOWNSIDE_PREDICTOR_INSUFFICIENT_PORTABILITY"
        elif (not downside) and float(full.net_excess_vs_control) < 0:
            classification = "ADVERSE"
        else:
            classification = "ECONOMICALLY_NULL"
        decisions.append(
            {
                "family": family,
                "track": str(full.track),
                "passes_all_screen_gates": passes,
                "gates": gates,
                "net_excess": float(full.net_excess_vs_control),
                "early_excess": float(early.net_excess_vs_control),
                "late_excess": float(late.net_excess_vs_control),
                "mean_net_return": float(full.mean_net_return),
                "median_net_return": float(full.median_net_return),
                "severe_loss_disadvantage": float(full.severe_loss_disadvantage),
                "complete_positions": int(full["count"]),
                "signal_dates": int(full.signal_dates),
                "diagnostics": diag[family],
                "classification": classification,
                "replay_decision": "NO_REPLAY",
            }
        )
    eligible = sorted(
        [
            d
            for d in decisions
            if d["track"] == "support"
            and d["passes_all_screen_gates"]
            and d["family"] != "confirmed_breakdown"
        ],
        key=lambda d: (min(d["early_excess"], d["late_excess"]), d["net_excess"]),
        reverse=True,
    )
    for row in eligible[:2]:
        row["replay_decision"] = "PROMOTE_EXECUTABLE"
    return summary, decisions


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    return value


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(text)
    os.replace(temp, path)


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# Objective support/recovery and bounded independent discovery",
        "",
        f"Status: `{result['status']}`.",
        "",
        "PIT fundamentals: `DATA_BLOCKED_PARKED`; bounded reconnaissance found no revision-aware turnkey source and performed no acquisition.",
        "",
        "| Hypothesis | Track | Events | Dates | Net excess | Early | Late | Severe disadvantage | Classification | Replay |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for d in result["decisions"]:
        lines.append(
            f"| {d['family']} | {d['track']} | {d['complete_positions']:,} | {d['signal_dates']} | {d['net_excess']:.3%} | {d['early_excess']:.3%} | {d['late_excess']:.3%} | {d['severe_loss_disadvantage']:.3%} | {d['classification']} | {d['replay_decision']} |"
        )
    lines += [
        "",
        "No support bundle was run: complexity was not considered before standalone gates. Post-2023 outcomes and CY-011 were not read.",
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    daily_paths, _ = CYCLE5.CYCLE4._input_paths()
    with tempfile.TemporaryDirectory(prefix="ashare-cycle-007-") as temp:
        frame, calendar, audit = _build_frame(daily_paths, Path(temp))
    selection, diagnostics = _select(frame)
    panel, path_rows = CYCLE5._attach_outcomes(daily_paths, selection, calendar)
    summary, decisions = _summarize(panel, diagnostics)
    promoted = [d["family"] for d in decisions if d["replay_decision"] == "PROMOTE_EXECUTABLE"]
    # A replay is intentionally opened only after all screen decisions are frozen by the code above.
    replays = []
    equities = []
    exits = []
    if promoted:
        plans = CYCLE5._plans(panel, promoted, calendar)
        market = CYCLE5.DIVERSIFIED._query_execution_rows(daily_paths, plans, calendar)
        ca_spec = json.loads((PROGRAM / "experiments/ASHARE-CA-REPLAY-003_spec.json").read_text())
        events, action_audit = CYCLE5.CA._load_risk_events(ca_spec, calendar)
        for family in promoted:
            replay, equity, risk = CYCLE5._replay(family, plans, market, calendar, events)
            replay["decision_role"] = "candidate_generation"
            replays.append(replay)
            equities.append(equity)
            exits += [] if risk.empty else [risk]
    else:
        action_audit = {"not_run": True}
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_BOUNDED_DISCOVERY",
        "fundamental_reconnaissance": spec["fundamental_reconnaissance"],
        "input_audit": audit,
        "eligible_rows": len(frame),
        "eligible_symbols": int(frame.symbol.nunique()),
        "decision_dates": int(frame.trade_date.nunique()),
        "future_path_rows_read": path_rows,
        "diagnostics": diagnostics.to_dict("records"),
        "decisions": decisions,
        "support_bundle": None,
        "promoted_families": promoted,
        "replays": replays,
        "action_audit": action_audit,
        "questions": {
            "what_market_behavior_are_we_still_not_studying": "Versioned PIT fundamentals, order-book/queue pressure, borrow-feasible short legs, and untouched temporal confirmation.",
            "new_strategy_archetype_implied": None,
        },
    }
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    (pd.concat(equities, ignore_index=True) if equities else pd.DataFrame()).to_csv(
        EQUITY_PATH, index=False
    )
    (pd.concat(exits, ignore_index=True) if exits else pd.DataFrame()).to_csv(
        EXIT_PATH, index=False
    )
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "panel_sha256": sha256_file(PANEL_PATH),
        "summary_sha256": sha256_file(SUMMARY_PATH),
        "equity_sha256": sha256_file(EQUITY_PATH),
        "risk_exits_sha256": sha256_file(EXIT_PATH),
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
