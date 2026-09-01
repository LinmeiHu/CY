#!/usr/bin/env python3
# ruff: noqa: E501
"""Run the frozen Low-MAX cost-resilience and portability confirmation cycle."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-LOW-MAX-CONFIRMATION-CYCLE-012_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-LOW-MAX-CONFIRMATION-CYCLE-012_result.json"
EQUITY_PATH = PROGRAM / "artifacts/ASHARE-LOW-MAX-CONFIRMATION-CYCLE-012_cost_equity.csv"
PORTABILITY_PATH = PROGRAM / "artifacts/ASHARE-LOW-MAX-CONFIRMATION-CYCLE-012_portability.csv"
REPORT_PATH = PROGRAM / "reports/ASHARE-LOW-MAX-CONFIRMATION-CYCLE-012_report.md"
CONSTRUCTION_PATH = PROGRAM / "scripts/run_ashare_industry_diffusion_construction_011.py"
DECISION_PATH = PROGRAM / "scripts/run_hab_chx_decision_batch_001.py"
EXPECTED_SPEC_SHA256 = "f4681932f50b8b54bbbe03ca334c94098afc7a9f84b4ddd25233b1d5cca830a3"


class LowMaxConfirmationError(RuntimeError):
    """Fail-closed error for Cycle 012."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
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


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise LowMaxConfirmationError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CONSTRUCTION = _load_module("ashare_diffusion_construction_011_for_012", CONSTRUCTION_PATH)
DECISION = _load_module("hab_chx_decision_batch_001_for_012", DECISION_PATH)


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise LowMaxConfirmationError("Cycle 012 frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_COST_AND_PORTABILITY_CONTRACT_BEFORE_CYCLE_012_OUTCOMES":
        raise LowMaxConfirmationError("Cycle 012 contract was not frozen before outcomes")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise LowMaxConfirmationError(f"bound input changed: {name}")
    if spec["track_a"]["cost_per_side"] != [0.002, 0.003, 0.004]:
        raise LowMaxConfirmationError("matched cost grid changed")
    baseline = spec["track_b"]["baseline"]
    if baseline["name"] != "CHINEXT_V1_RS_ACCEL_VETO_CANDIDATE_LIFECYCLE":
        raise LowMaxConfirmationError("portability baseline changed")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "third modifier", "turnover-reduction", "new Alpha"):
        if phrase not in prohibited:
            raise LowMaxConfirmationError(f"missing prohibition: {phrase}")
    return spec


def _cost_delta(baseline: dict[str, Any], low_max: dict[str, Any]) -> dict[str, float]:
    return {
        "total_return": low_max["total_return"] - baseline["total_return"],
        "annualized_return": low_max["annualized_return"] - baseline["annualized_return"],
        "maximum_drawdown": low_max["maximum_drawdown"] - baseline["maximum_drawdown"],
        "daily_sharpe": low_max["daily_sharpe"] - baseline["daily_sharpe"],
        "calmar": low_max["calmar"] - baseline["calmar"],
        "severe_loss_improvement": baseline["severe_trade_fraction"] - low_max["severe_trade_fraction"],
        "turnover": low_max["turnover_multiple_initial_capital"] - baseline["turnover_multiple_initial_capital"],
        "completed_trades": low_max["completed_trades"] - baseline["completed_trades"],
        "capacity": low_max["p10_capacity_cny_at_5pct_amount"] - baseline["p10_capacity_cny_at_5pct_amount"],
        "industry_hhi": low_max["mean_industry_hhi_invested_days"] - baseline["mean_industry_hhi_invested_days"],
    }


def classify_cost_resilience(comparisons: dict[str, dict[str, Any]], spec: dict[str, Any]) -> str:
    resilient = spec["track_a"]["classification"]["COST_RESILIENT_all_required"]
    reference = comparisons["20bps"]["delta"]["total_return"]
    checks = []
    for label in ("30bps", "40bps"):
        delta = comparisons[label]["delta"]
        checks.extend(
            [
                delta["total_return"] > resilient["minimum_total_return_delta"],
                delta["annualized_return"] > resilient["minimum_annualized_return_delta"],
                delta["daily_sharpe"] >= resilient["minimum_sharpe_delta"],
                delta["maximum_drawdown"] >= resilient["minimum_drawdown_delta"],
                delta["severe_loss_improvement"] >= resilient["minimum_severe_loss_improvement"],
            ]
        )
    retention = comparisons["40bps"]["delta"]["total_return"] / reference if reference > 0 else -math.inf
    checks.append(retention >= resilient["minimum_40bps_total_return_advantage_retention_vs_20bps"])
    if all(checks):
        return "COST_RESILIENT"
    useful = spec["track_a"]["classification"]["COST_SENSITIVE_BUT_USEFUL_all_required_at_40bps"]
    delta = comparisons["40bps"]["delta"]
    if (
        delta["total_return"] > useful["minimum_total_return_delta"]
        and delta["annualized_return"] > useful["minimum_annualized_return_delta"]
        and delta["daily_sharpe"] > useful["minimum_sharpe_delta"]
        and delta["maximum_drawdown"] >= useful["minimum_drawdown_delta"]
        and delta["severe_loss_improvement"] >= useful["minimum_severe_loss_improvement"]
    ):
        return "COST_SENSITIVE_BUT_USEFUL"
    return "COST_FRAGILE"


def _turnover_attribution(baseline: pd.DataFrame, low_max: pd.DataFrame, comparisons: dict[str, Any]) -> dict[str, Any]:
    base_sets = baseline.groupby("trade_date").symbol.apply(set)
    low_sets = low_max.groupby("trade_date").symbol.apply(set)
    dates = base_sets.index.intersection(low_sets.index)
    changed = pd.Series(
        {day: len(low_sets.loc[day] - base_sets.loc[day]) for day in dates}, dtype=float
    )
    total_changed = float(changed.sum())
    top_ten = float(changed.nlargest(10).sum())
    cost20 = comparisons["20bps"]
    incremental = cost20["delta"]["turnover"]
    low_turnover = cost20["low_max"]["turnover_multiple_initial_capital"]
    return {
        "decision_dates": len(dates),
        "changed_stock_identities": int(total_changed),
        "selection_replacement_fraction": float(changed.mean() / 10.0),
        "mean_holding_overlap_fraction": float(1.0 - changed.mean() / 10.0),
        "dates_with_any_replacement": int((changed > 0).sum()),
        "top_ten_replacement_dates_share": float(top_ten / total_changed) if total_changed else 0.0,
        "maximum_replacements_on_one_date": int(changed.max()),
        "incremental_executed_turnover_multiple_initial_capital": incremental,
        "incremental_turnover_fraction_of_low_max_turnover": float(incremental / low_turnover),
        "baseline_forced_corporate_action_exits": cost20["baseline"]["forced_pre_effective_exits"],
        "low_max_forced_corporate_action_exits": cost20["low_max"]["forced_pre_effective_exits"],
        "forced_exit_count_delta": cost20["low_max"]["forced_pre_effective_exits"] - cost20["baseline"]["forced_pre_effective_exits"],
    }


def _run_cost_track(spec: dict[str, Any], paths: list[Path], calendar: list[date], temp_path: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    construction_spec = CONSTRUCTION._load_spec()
    frame, audit = CONSTRUCTION._build_opportunity_frame(paths, temp_path)
    baseline = CONSTRUCTION._frozen_baseline(frame, construction_spec)
    low_max = CONSTRUCTION._select_modifier(
        frame, baseline, "industry_diffusion_low_max", "max_return20", ascending=True
    )
    selections = pd.concat([baseline, low_max], ignore_index=True)
    selections.loc[selections.family.eq("arm0_baseline"), "family"] = "industry_diffusion_baseline"
    plans = CONSTRUCTION._make_plans(selections, calendar)
    market_rows = CONSTRUCTION.CYCLE2._query_execution_rows(paths, plans, calendar)
    baseline_spec = CONSTRUCTION.BASELINE._load_spec()
    events, action_audit = CONSTRUCTION.BASELINE._load_risk_events(baseline_spec, calendar)
    comparisons: dict[str, Any] = {}
    equities: list[pd.DataFrame] = []
    original_cost = CONSTRUCTION.BASELINE.COST
    try:
        for cost in spec["track_a"]["cost_per_side"]:
            CONSTRUCTION.BASELINE.COST = float(cost)
            rows: dict[str, dict[str, Any]] = {}
            for family in ("industry_diffusion_baseline", "industry_diffusion_low_max"):
                replay, equity, _ = CONSTRUCTION.BASELINE._replay(
                    family, plans, market_rows, calendar, events
                )
                rows[family] = replay
                equity = equity.copy()
                equity["cost_per_side"] = cost
                equities.append(equity)
            label = f"{round(cost * 10000):.0f}bps"
            comparisons[label] = {
                "cost_per_side": cost,
                "baseline": rows["industry_diffusion_baseline"],
                "low_max": rows["industry_diffusion_low_max"],
                "delta": _cost_delta(
                    rows["industry_diffusion_baseline"], rows["industry_diffusion_low_max"]
                ),
            }
    finally:
        CONSTRUCTION.BASELINE.COST = original_cost
    track = {
        "source_audit": audit,
        "action_audit": action_audit,
        "matched_cost_comparisons": comparisons,
        "turnover_attribution": _turnover_attribution(baseline, low_max, comparisons),
        "classification": classify_cost_resilience(comparisons, spec),
    }
    return track, pd.concat(equities, ignore_index=True)


def _build_chinext_low_max(
    paths: list[Path], calendar: list[date], candidate_panel: pd.DataFrame, temp_path: Path
) -> tuple[pd.DataFrame, dict[str, Any]]:
    targets = candidate_panel[["trade_date", "symbol"]].copy()
    targets["trade_date"] = pd.to_datetime(targets.trade_date).dt.date
    symbols = targets[["symbol"]].drop_duplicates()
    calendar_frame = pd.DataFrame({"trade_date": calendar, "cal_idx": range(len(calendar))})
    con = duckdb.connect()
    con.execute("SET memory_limit='6GB'")
    con.execute("SET threads=1")
    con.execute(f"SET temp_directory='{temp_path.as_posix()}'")
    con.execute("SET preserve_insertion_order=false")
    con.register("target_symbols", symbols)
    con.register("targets", targets)
    con.register("calendar_input", calendar_frame)
    con.from_parquet([str(path) for path in paths], union_by_name=True).create_view("source")
    con.execute("CREATE TEMP TABLE calendar AS SELECT * FROM calendar_input")
    con.execute(
        """CREATE TEMP TABLE daily AS SELECT s.* FROM source s
        INNER JOIN target_symbols t USING(symbol)"""
    )
    con.execute(
        """CREATE TEMP TABLE base AS SELECT d.*,c.cal_idx,
        (d.hard_valid IS TRUE AND d.bar_valid IS TRUE AND d.trading_state_valid IS TRUE
         AND d.industry_valid IS TRUE AND d.float_valid IS TRUE
         AND d.corporate_action_valid IS TRUE AND d.market_valid IS TRUE
         AND d.market_rule_valid IS TRUE AND d.historical_identity_valid IS TRUE
         AND d.corporate_action_blocking IS FALSE AND coalesce(d.rights_ratio,0)=0
         AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
         AND d.snapshot_id IS NOT NULL AND d.open>0 AND d.high>=greatest(d.open,d.close)
         AND d.low<=least(d.open,d.close) AND d.close>0 AND d.volume>=0 AND d.amount>=0) history_valid,
        lag(d.close) OVER w previous_close,lag(c.cal_idx) OVER w previous_cal_idx,
        lag(d.hard_valid IS TRUE AND d.bar_valid IS TRUE AND d.trading_state_valid IS TRUE
         AND d.industry_valid IS TRUE AND d.float_valid IS TRUE
         AND d.corporate_action_valid IS TRUE AND d.market_valid IS TRUE
         AND d.market_rule_valid IS TRUE AND d.historical_identity_valid IS TRUE
         AND d.corporate_action_blocking IS FALSE AND coalesce(d.rights_ratio,0)=0
         AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
         AND d.snapshot_id IS NOT NULL AND d.close>0) OVER w previous_history_valid
        FROM daily d JOIN calendar c USING(trade_date)
        WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)"""
    )
    con.execute(
        """CREATE TEMP TABLE steps AS SELECT *,CASE
        WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
         AND coalesce(corporate_action_count,0)=0 THEN ln(close/previous_close)
        WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
         AND corporate_action_count>0 AND corporate_action_available_date IS NOT NULL
         AND corporate_action_available_date<=trade_date AND coalesce(rights_ratio,0)=0
         AND coalesce(share_multiplier,1)>0 AND previous_close-coalesce(cash_per_share,0)>0
        THEN ln(close/((previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)))
        ELSE NULL END step_return
        FROM base"""
    )
    con.execute(
        """CREATE TEMP TABLE features AS SELECT *,
        max(step_return) OVER w20 max_return20,count(step_return) OVER w20 valid_steps20,
        lag(cal_idx,19) OVER ws cal_idx_lag19
        FROM steps WINDOW
        ws AS (PARTITION BY symbol ORDER BY trade_date),
        w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)"""
    )
    output = con.execute(
        """SELECT t.trade_date,t.symbol,f.industry,f.decision_at,f.available_at,
        CASE WHEN f.history_valid AND f.valid_steps20=20 AND f.cal_idx-f.cal_idx_lag19=19
             AND isfinite(f.max_return20) THEN f.max_return20 ELSE NULL END max_return20
        FROM targets t LEFT JOIN features f USING(trade_date,symbol)
        ORDER BY t.trade_date,t.symbol"""
    ).fetchdf()
    con.close()
    if len(output) != len(targets) or output.duplicated(["trade_date", "symbol"]).any():
        raise LowMaxConfirmationError("CHINEXT Low-MAX target join changed cardinality")
    audit = {
        "target_candidates": len(output),
        "target_symbols": int(output.symbol.nunique()),
        "target_dates": int(output.trade_date.nunique()),
        "quality_available": int(output.max_return20.notna().sum()),
        "quality_coverage": float(output.max_return20.notna().mean()),
        "future_predictor_columns": 0,
    }
    return output, audit


def _industry_concentration(rows: pd.DataFrame) -> tuple[float, float]:
    shares = rows.industry.value_counts(normalize=True)
    return float((shares * shares).sum()), float(shares.max())


def _period_pair_metrics(rows: pd.DataFrame) -> dict[str, Any]:
    baseline = rows.baseline_return.astype(float)
    low_max = rows.low_max_return.astype(float)
    return {
        "dates": len(rows),
        "baseline_mean_net_return": float(baseline.mean()),
        "low_max_mean_net_return": float(low_max.mean()),
        "mean_net_improvement": float((low_max - baseline).mean()),
        "baseline_winner_fraction": float((baseline > 0).mean()),
        "low_max_winner_fraction": float((low_max > 0).mean()),
        "winner_capture_improvement": float((low_max > 0).mean() - (baseline > 0).mean()),
        "baseline_severe_loss_fraction": float((baseline <= -0.10).mean()),
        "low_max_severe_loss_fraction": float((low_max <= -0.10).mean()),
        "severe_loss_improvement": float((baseline <= -0.10).mean() - (low_max <= -0.10).mean()),
    }


def portability_gate(metrics: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    gates = spec["track_b"]["replay_authorization_all_required"]
    checks = {
        "quality_coverage": metrics["quality_coverage"] >= gates["minimum_quality_coverage"],
        "multi_candidate_dates": metrics["multi_candidate_dates"] >= gates["minimum_multi_candidate_dates"],
        "changed_selections": metrics["changed_selections"] >= gates["minimum_changed_selections"],
        "changed_fraction": metrics["changed_fraction"] >= gates["minimum_changed_fraction_of_multi_candidate_dates"],
        "full_improvement": metrics["periods"]["full"]["mean_net_improvement"] >= gates["minimum_full_mean_net_improvement"],
        "development_improvement": metrics["periods"]["development_2018_2021"]["mean_net_improvement"] >= gates["minimum_each_block_mean_net_improvement"],
        "later_improvement": metrics["periods"]["consumed_2022_2023"]["mean_net_improvement"] >= gates["minimum_each_block_mean_net_improvement"],
        "severe_loss": metrics["periods"]["full"]["severe_loss_improvement"] >= gates["minimum_severe_loss_improvement"],
        "industry_hhi": metrics["industry_hhi_increase"] <= gates["maximum_industry_hhi_increase"],
        "largest_industry_share": metrics["largest_industry_share_increase"] <= gates["maximum_largest_industry_share_increase"],
    }
    return {"checks": checks, "authorized": all(checks.values())}


def _candidate_portability(
    spec: dict[str, Any], panel: pd.DataFrame, features: pd.DataFrame, audit: dict[str, Any]
) -> tuple[dict[str, Any], pd.DataFrame, dict[tuple[date, str], float]]:
    work = panel.merge(features, on=["trade_date", "symbol"], how="left", validate="one_to_one")
    if len(work) != len(panel):
        raise LowMaxConfirmationError("portability merge changed candidate count")
    quality_map = {
        (pd.Timestamp(row.trade_date).date(), row.symbol): float(row.max_return20)
        for row in work.loc[work.max_return20.notna()].itertuples(index=False)
    }
    comparisons: list[dict[str, Any]] = []
    multi_dates = 0
    for trade_date, group in work.groupby("trade_date", sort=True):
        if len(group) < 2:
            continue
        multi_dates += 1
        baseline = group.sort_values(["baseline_rank", "symbol"]).iloc[0]
        valid = group.loc[group.max_return20.notna()].sort_values(
            ["max_return20", "baseline_rank", "symbol"]
        )
        if valid.empty:
            continue
        low_max = valid.iloc[0]
        if baseline.outcome_status != "COMPLETE" or low_max.outcome_status != "COMPLETE":
            continue
        comparisons.append(
            {
                "trade_date": trade_date,
                "block": baseline.block,
                "candidate_count": len(group),
                "baseline_symbol": baseline.symbol,
                "low_max_symbol": low_max.symbol,
                "changed": baseline.symbol != low_max.symbol,
                "baseline_industry": baseline.industry,
                "low_max_industry": low_max.industry,
                "baseline_return": float(baseline.forward_return_20),
                "low_max_return": float(low_max.forward_return_20),
            }
        )
    paired = pd.DataFrame(comparisons)
    if paired.empty:
        raise LowMaxConfirmationError("no complete portability comparisons")
    base_hhi, base_largest = _industry_concentration(
        paired.rename(columns={"baseline_industry": "industry"})[["industry"]]
    )
    low_hhi, low_largest = _industry_concentration(
        paired.rename(columns={"low_max_industry": "industry"})[["industry"]]
    )
    periods = {
        "full": _period_pair_metrics(paired),
        "development_2018_2021": _period_pair_metrics(
            paired.loc[paired.block.eq("development_2018_2021")]
        ),
        "consumed_2022_2023": _period_pair_metrics(
            paired.loc[paired.block.eq("consumed_2022_2023")]
        ),
    }
    metrics = {
        "eligible_decision_dates": int(work.trade_date.nunique()),
        "median_same_date_candidate_breadth": float(work.groupby("trade_date").size().median()),
        "multi_candidate_dates": multi_dates,
        "complete_comparison_dates": len(paired),
        "quality_coverage": audit["quality_coverage"],
        "changed_selections": int(paired.changed.sum()),
        "changed_fraction": float(paired.changed.mean()),
        "overlap_fraction": float(1.0 - paired.changed.mean()),
        "periods": periods,
        "baseline_industry_hhi": base_hhi,
        "low_max_industry_hhi": low_hhi,
        "industry_hhi_increase": low_hhi - base_hhi,
        "baseline_largest_industry_share": base_largest,
        "low_max_largest_industry_share": low_largest,
        "largest_industry_share_increase": low_largest - base_largest,
    }
    metrics["replay_gate"] = portability_gate(metrics, spec)
    return metrics, paired, quality_map


def _new_low_max_audit() -> dict[str, Any]:
    return {
        "candidate_sessions": set(),
        "candidate_count": 0,
        "vetoed_candidate_count": 0,
        "quality_missing_count": 0,
        "rank_changed_sessions": set(),
    }


@contextmanager
def _low_max_rank(
    quality: dict[tuple[date, str], float], audit: dict[str, Any]
) -> Iterator[None]:
    original = DECISION.shared.engine_module.rank_candidates_for_arm

    def ranked(candidate_symbols: list[str], rs: dict[str, Any], day: date, policy: Any) -> list[str]:
        eligible: list[str] = []
        for symbol in candidate_symbols:
            row = rs.get(symbol)
            if row is None:
                raise LowMaxConfirmationError(f"candidate lacks PIT RS row: {day} {symbol}")
            audit["candidate_count"] += 1
            acceleration = Decimal(str(row["r20"])) - Decimal(str(row["r120"]))
            if acceleration >= Decimal("0.20"):
                audit["vetoed_candidate_count"] += 1
                continue
            if (day, symbol) not in quality:
                audit["quality_missing_count"] += 1
                continue
            eligible.append(symbol)
        if eligible:
            audit["candidate_sessions"].add(day)
        baseline = original(eligible, rs, day, policy)
        baseline_order = {symbol: index for index, symbol in enumerate(baseline)}
        low_max = sorted(eligible, key=lambda symbol: (quality[(day, symbol)], baseline_order[symbol], symbol))
        if low_max != baseline:
            audit["rank_changed_sessions"].add(day)
        return low_max

    DECISION.shared.engine_module.rank_candidates_for_arm = ranked
    try:
        yield
    finally:
        DECISION.shared.engine_module.rank_candidates_for_arm = original


def _serialize_low_max_audit(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_session_count": len(audit["candidate_sessions"]),
        "candidate_count": int(audit["candidate_count"]),
        "vetoed_candidate_count": int(audit["vetoed_candidate_count"]),
        "quality_missing_count": int(audit["quality_missing_count"]),
        "rank_changed_session_count": len(audit["rank_changed_sessions"]),
        "input_manifest_sha256": audit.get("input_manifest_sha256"),
    }


def _run_portability_replay(
    spec: dict[str, Any], quality: dict[tuple[date, str], float], external: Path
) -> dict[str, Any]:
    parent_spec = DECISION._load_spec()
    parent_result = json.loads(
        _resolve(spec["inputs"]["chinext_decision_result"]["path"]).read_text(encoding="utf-8")
    )
    baseline_arm = parent_result["arms"][DECISION.SELECTION_ARM]
    baselines = {
        block: row["candidate"] for block, row in baseline_arm["comparisons"].items()
    }
    original_audit = DECISION.shared._new_audit
    original_tempdir = tempfile.tempdir
    try:
        tempfile.tempdir = str(external)
        DECISION.shared._new_audit = _new_low_max_audit
        with tempfile.TemporaryDirectory(prefix="low-max-portability-012-", dir=external) as output:
            with DECISION._configured_shared_runner(Path(output), _low_max_rank):
                development_engine, development_audit = DECISION.shared._run_development(quality)
                later_engine, later_audit = DECISION.shared._run_consumed_block(parent_spec, quality)
            engines = {
                "development_2018_2021": (development_engine, development_audit),
                "consumed_2022_2023": (later_engine, later_audit),
            }
            blocks: dict[str, Any] = {}
            for block, (engine, audit) in engines.items():
                candidate = DECISION.shared._candidate_metrics(engine)
                blocks[block] = {
                    "baseline": baselines[block],
                    "low_max": candidate,
                    "delta": DECISION._delta(candidate, baselines[block]),
                    "audit": _serialize_low_max_audit(audit),
                }
    finally:
        DECISION.shared._new_audit = original_audit
        tempfile.tempdir = original_tempdir
    return {"status": "COMPLETE_ONE_AUTHORIZED_REPLAY", "blocks": blocks}


def _portability_classification(metrics: dict[str, Any], replay: dict[str, Any] | None) -> str:
    if not metrics["replay_gate"]["authorized"]:
        improvements = [
            metrics["periods"][name]["mean_net_improvement"]
            for name in ("development_2018_2021", "consumed_2022_2023")
        ]
        return "CONDITIONAL_INFORMATION_ONLY" if all(value >= 0 for value in improvements) else "PORTABILITY_FAILED"
    if replay is None:
        raise LowMaxConfirmationError("authorized portability replay missing")
    blocks = replay["blocks"].values()
    if all(
        row["delta"]["total_return"] > 0
        and row["delta"]["sharpe_rf0"] > 0
        and row["delta"]["max_drawdown"] >= 0
        and row["delta"]["severe_loss_rate"] <= 0
        for row in blocks
    ):
        return "REUSABLE_CONDITIONAL_STOCK_QUALITY"
    return "PORTABILITY_FAILED"


def _final_decision(cost: str, portability: str) -> str:
    if cost == "COST_RESILIENT" and portability == "REUSABLE_CONDITIONAL_STOCK_QUALITY":
        return "REUSABLE_STOCK_QUALITY_COMPONENT"
    if cost == "COST_RESILIENT":
        return "STRONG_INDUSTRY_DIFFUSION_CONDITIONAL_INFORMATION"
    if cost == "COST_SENSITIVE_BUT_USEFUL":
        return "PROMISING_BUT_COST_SENSITIVE"
    return "PARKED"


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# Low-MAX conditional stock-quality value confirmation",
        "",
        "> Consumed 2018–2023 development evidence only. Post-2023 outcomes and CY-011 were not read.",
        "",
        "## Track A — Cost resilience",
        "",
        "| Cost/side | Arm | Total | Annualized | Max DD | Sharpe | Calmar | Severe | Turnover | Trades | P10 capacity | HHI |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, comparison in result["track_a"]["matched_cost_comparisons"].items():
        for name in ("baseline", "low_max"):
            row = comparison[name]
            lines.append(
                f"| {label} | {name} | {row['total_return']:.2%} | {row['annualized_return']:.2%} | "
                f"{row['maximum_drawdown']:.2%} | {row['daily_sharpe']:.3f} | {row['calmar']:.3f} | "
                f"{row['severe_trade_fraction']:.2%} | {row['turnover_multiple_initial_capital']:.2f}x | "
                f"{row['completed_trades']} | CNY {row['p10_capacity_cny_at_5pct_amount']:,.0f} | "
                f"{row['mean_industry_hhi_invested_days']:.3f} |"
            )
        delta = comparison["delta"]
        lines.append(
            f"| {label} | Low-MAX delta | {delta['total_return']:+.2%} | {delta['annualized_return']:+.2%} | "
            f"{delta['maximum_drawdown']:+.2%} | {delta['daily_sharpe']:+.3f} | {delta['calmar']:+.3f} | "
            f"{delta['severe_loss_improvement']:+.2%} improvement | {delta['turnover']:+.2f}x | "
            f"{delta['completed_trades']:+d} | CNY {delta['capacity']:+,.0f} | {delta['industry_hhi']:+.3f} |"
        )
    attribution = result["track_a"]["turnover_attribution"]
    lines.extend(
        [
            "",
            f"Classification: `{result['track_a']['classification']}`.",
            "",
            f"Low-MAX replaces {attribution['selection_replacement_fraction']:.2%} of cohort identities; "
            f"the ten busiest dates contain {attribution['top_ten_replacement_dates_share']:.2%} of replacements. "
            f"Incremental executed turnover is {attribution['incremental_executed_turnover_multiple_initial_capital']:.2f}x initial capital. "
            f"Forced corporate-action exits are {attribution['baseline_forced_corporate_action_exits']} baseline versus "
            f"{attribution['low_max_forced_corporate_action_exits']} Low-MAX.",
            "",
            "## Track B — Portability",
            "",
            "The baseline was frozen before Low-MAX outcomes: exact CHINEXT V1 RS-acceleration-veto candidates and lifecycle.",
            "",
        ]
    )
    port = result["track_b"]["candidate_level"]
    lines.append(
        f"There are {port['eligible_decision_dates']} dates, median breadth {port['median_same_date_candidate_breadth']:.0f}, "
        f"{port['multi_candidate_dates']} multi-candidate dates, and {port['changed_selections']} changed Top-1 selections "
        f"({port['changed_fraction']:.2%})."
    )
    lines.extend(["", "| Period | Dates | Baseline net | Low-MAX net | Delta | Winner delta | Severe improvement |", "|---|---:|---:|---:|---:|---:|---:|"])
    for period, row in port["periods"].items():
        lines.append(
            f"| {period} | {row['dates']} | {row['baseline_mean_net_return']:.3%} | "
            f"{row['low_max_mean_net_return']:.3%} | {row['mean_net_improvement']:+.3%} | "
            f"{row['winner_capture_improvement']:+.3%} | {row['severe_loss_improvement']:+.3%} |"
        )
    lines.extend(
        [
            "",
            f"Candidate replay gate: `{port['replay_gate']['authorized']}`; portability classification: "
            f"`{result['track_b']['classification']}`.",
        ]
    )
    replay = result["track_b"].get("full_replay")
    if replay:
        lines.extend(["", "| Block | Baseline return | Low-MAX return | Return delta | DD delta | Sharpe delta | Severe-rate change (candidate − baseline; lower is better) |", "|---|---:|---:|---:|---:|---:|---:|"])
        for block, row in replay["blocks"].items():
            lines.append(
                f"| {block} | {row['baseline']['total_return']:.2%} | {row['low_max']['total_return']:.2%} | "
                f"{row['delta']['total_return']:+.2%} | {row['delta']['max_drawdown']:+.2%} | "
                f"{row['delta']['sharpe_rf0']:+.3f} | {row['delta']['severe_loss_rate']:+.3%} |"
            )
    lines.extend(
        [
            "",
            "## Final Low-MAX conclusion",
            "",
            f"`{result['final_low_max_decision']}`. No further Low-MAX research is authorized without genuinely new independent evidence or untouched confirmation data.",
            "",
            "## Next Price–Volume–Path frontier — planning only",
            "",
        ]
    )
    for index, item in enumerate(result["next_frontier"], start=1):
        lines.append(f"{index}. **{item['family']}** — {item['rationale']}")
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    baseline_spec = CONSTRUCTION.BASELINE._load_spec()
    paths, calendar, input_identity = CONSTRUCTION.BASELINE._load_market_inputs(baseline_spec)
    external = Path("/Volumes/quant")
    if not external.is_dir() or not os.access(external, os.W_OK):
        raise LowMaxConfirmationError("verified external temporary root unavailable")
    with tempfile.TemporaryDirectory(prefix="low-max-confirmation-012-", dir=external) as temporary:
        temporary_path = Path(temporary)
        track_a, equity = _run_cost_track(spec, paths, calendar, temporary_path)
        panel = pd.read_csv(
            _resolve(spec["inputs"]["chinext_candidate_panel"]["path"]),
            parse_dates=["trade_date", "decision_at"],
        )
        features, feature_audit = _build_chinext_low_max(paths, calendar, panel, temporary_path)
        candidate_metrics, portability_panel, quality = _candidate_portability(
            spec, panel, features, feature_audit
        )
        replay = (
            _run_portability_replay(spec, quality, external)
            if candidate_metrics["replay_gate"]["authorized"]
            else None
        )
    portability_classification = _portability_classification(candidate_metrics, replay)
    final_decision = _final_decision(track_a["classification"], portability_classification)
    _atomic_write(
        EQUITY_PATH,
        equity.sort_values(["cost_per_side", "family", "trade_date"]).to_csv(
            index=False, lineterminator="\n", float_format="%.10g"
        ),
    )
    _atomic_write(
        PORTABILITY_PATH,
        portability_panel.sort_values("trade_date").to_csv(
            index=False, lineterminator="\n", float_format="%.10g"
        ),
    )
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "starting_checkpoint": spec["starting_checkpoint"],
        "claim_boundary": spec["claim_boundary"],
        "input_identity": input_identity,
        "track_a": track_a,
        "track_b": {
            "selected_baseline": spec["track_b"]["baseline"],
            "feature_audit": feature_audit,
            "candidate_level": candidate_metrics,
            "full_replay": replay,
            "classification": portability_classification,
        },
        "final_low_max_decision": final_decision,
        "next_frontier": [
            {
                "family": "Price-limit event lifecycle and post-event acceptance",
                "rationale": "Highest information value: existing limit and minute contracts support a bounded event-path test distinct from another momentum lookback.",
            },
            {
                "family": "Industry leader-follower convergence and leadership turnover",
                "rationale": "Broad registered industry coverage can test a distinct propagation mechanism beyond frozen diffusion levels and acceleration.",
            },
            {
                "family": "Liquidity-transition shock assimilation",
                "rationale": "Existing price-volume data make causal state transitions inexpensive to test, though the mechanism is closer to previously explored activity signals.",
            },
        ],
        "boundaries": {
            "post_2023_read": False,
            "cy011_data_read": False,
            "low_max_changed": False,
            "industry_diffusion_changed": False,
            "new_alpha_outcomes_read": False,
            "new_large_data_acquired": False,
            "oos_claim": False,
            "further_low_max_research_authorized": False,
        },
    }
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "cost_equity_sha256": sha256_file(EQUITY_PATH),
        "portability_panel_sha256": sha256_file(PORTABILITY_PATH),
    }
    _atomic_write(REPORT_PATH, _render(result))
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
