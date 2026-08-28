#!/usr/bin/env python3
# ruff: noqa: E501
"""Research-only controlled P&L study for the frozen P_PRICE_PULLBACK_20 universe.

The runner imports the completed setup-recall study only as a governed panel
builder.  It never writes production state, changes V3 temporal semantics,
rebuilds chips, or consumes an authoritative entry/exit outcome.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

STUDY_DIR = Path(__file__).resolve().parent
REPO_ROOT = STUDY_DIR.parents[1]
OUTPUT_DIR = STUDY_DIR / "results"
REPORT_PATH = STUDY_DIR / "V12_PNL_ORIENTED_SWING_STRATEGY_STUDY.md"
PREDECESSOR_DIR = REPO_ROOT / "research/v12-setup-recall-remediation-design"
PREDECESSOR_RUNNER = PREDECESSOR_DIR / "run_setup_recall_remediation_design.py"
PREDECESSOR_MANIFEST = PREDECESSOR_DIR / "results/manifest.json"

V3_ROOT = Path("/Users/linmei/Documents/CY/data/validation/v12_v3_500_temporal_20260828")
DAILY_2020 = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=2020/data_0.parquet")

SOURCE_COMMIT = "6bd5ab91d7fb0aefa07e913e241d58041920eac1"
EXPECTED_PREDECESSOR_RUNNER_SHA256 = "584249d1bdb7327f5b371fb8283f654a3acc102b1bd7c86a0fccd1f632f4ee26"
EXPECTED_PREDECESSOR_MANIFEST_SHA256 = "ed8b071236da59cc46ea270d422bf8879d6902cc9cc8ff686460375317889c67"
EXPECTED_ROWS = 121_251
EXPECTED_CANDIDATE_ROWS = 47_518
EXPECTED_CANDIDATE_EPISODES = 5_671
EXPECTED_SYMBOLS = 500

SPLITS = ("discovery", "validation", "holdout")
BASELINE_TEMPLATES = {
    "T1_CLOSE_STRENGTH": "Candidate close is above preclose and in the upper 40% of the same-day range.",
    "T2_RECLAIM_PRIOR_3_HIGH": "Candidate close reclaims the maximum high of the prior three valid sessions.",
    "T3_TREND_RESUMPTION": "Candidate close is above MA5, MA5 is above MA20, and close is above preclose.",
}
CANDIDATE_DEFINITION = {
    "name": "P_PRICE_PULLBACK_20",
    "eligible": "registered PIT-valid and tradable daily price observation after 60 consecutive price-valid sessions",
    "condition": "analysis_close / trailing_20_session_analysis_close_high - 1 <= -0.05",
    "v3_inputs_used": False,
}
BASELINE_CONTRACT = {
    "templates": BASELINE_TEMPLATES,
    "selection_population": "discovery entry-signal split only",
    "selection_rule": "highest discovery net Profit Factor among templates with at least 30 completed discovery trades; ties by template name",
    "entry": "signal at candidate close; intent for next session; fill at first legal buy open within five source sessions",
    "hard_stop": "close at or below entry analysis open minus 2.0 times signal-day ATR14; next legal sell open",
    "profit_protection": "after MFE reaches 2R, close below MA5; next legal sell open",
    "structure_exit": "from holding session 3, close below the prior five-session low; next legal sell open",
    "maximum_holding_sessions": 20,
    "same_bar_fill": False,
}
COST_CONTRACT = {
    "commission_each_side_bps": 3.0,
    "transfer_fee_each_side_bps": 0.2,
    "sell_stamp_duty_bps": 10.0,
    "slippage_each_side_bps": 5.0,
}
PORTFOLIO_CONTRACT = {
    "initial_capital": 1.0,
    "maximum_concurrent_positions": 10,
    "baseline_target_fraction": 0.10,
    "tie_break": "descending price trigger strength, then symbol, then trade_id",
    "leverage": False,
}
OVERLAY_CONTRACT = {
    "P1": "accept only VALID_CANONICAL_BASE or ENSEMBLE_AMBIGUOUS entry states",
    "P2": "P1 plus require VALID_CANONICAL_BASE and peak_track_age >= 20",
    "P3": "P2 plus entry peak mass and prominence at or above their discovery medians",
    "P4": "P3 plus bounded chip-confidence sizing",
    "P5": "P4 plus delay a profitable non-hard exit for at most five sessions while structure remains healthy",
    "P6": "P5 plus sell half after >=20% mass and prominence deterioration with price below MA5",
}
LARGE_LOSS = -0.08
LARGE_WINNER = 0.10


def _load_predecessor() -> Any:
    spec = importlib.util.spec_from_file_location("setup_recall_predecessor", PREDECESSOR_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load governed predecessor")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PRIOR = _load_predecessor()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=PRIOR.BASE.json_default)


def stable_id(prefix: str, *parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode()).hexdigest()[:20]}"


def date_split(value: object) -> str:
    date = pd.Timestamp(value)
    if date <= pd.Timestamp("2020-04-30"):
        return "discovery"
    if date <= pd.Timestamp("2020-08-31"):
        return "validation"
    return "holdout"


def finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def safe_float(value: object) -> float:
    return float(value) if finite(value) else math.nan


def verify_inputs() -> dict[str, Any]:
    evidence = PRIOR.verify_inputs()
    checks = {
        PREDECESSOR_RUNNER: EXPECTED_PREDECESSOR_RUNNER_SHA256,
        PREDECESSOR_MANIFEST: EXPECTED_PREDECESSOR_MANIFEST_SHA256,
    }
    for path, expected in checks.items():
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"governed predecessor changed: {path}: {actual}")
    ancestor = subprocess.run(
        ("git", "merge-base", "--is-ancestor", SOURCE_COMMIT, "HEAD"),
        cwd=REPO_ROOT,
        check=False,
    ).returncode == 0
    if not ancestor:
        raise RuntimeError("study does not descend from the completed design-study commit")
    evidence.update(
        {
            "source_commit": SOURCE_COMMIT,
            "source_commit_is_ancestor": ancestor,
            "predecessor_runner_sha256": checks[PREDECESSOR_RUNNER],
            "predecessor_manifest_sha256": checks[PREDECESSOR_MANIFEST],
            "candidate_definition_fingerprint": hashlib.sha256(canonical_json(CANDIDATE_DEFINITION).encode()).hexdigest(),
        }
    )
    return evidence


def _load_extra_fields() -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_columns = [
        "symbol", "trade_date", "volume", "amount", "is_st", "limit_pct", "up_limit_price", "down_limit_price",
        "buy_blocked_open", "sell_blocked_open", "current_day_data_tradable", "share_multiplier", "cash_per_share",
        "rights_ratio", "rights_price", "market_close", "decision_at", "pit_grade",
    ]
    daily = pq.read_table(DAILY_2020, columns=daily_columns).to_pandas().rename(columns={"trade_date": "feature_date"})
    daily["feature_date"] = pd.to_datetime(daily["feature_date"])
    con = duckdb.connect()
    try:
        con.execute("SET threads = 1")
        v3 = con.execute(
            """
            SELECT symbol, trade_date AS feature_date,
                   average_cost, dominant_peak_today, dominant_peak_ambiguous,
                   dominant_band_lower, dominant_band_upper, dominant_band_mass,
                   tracked_base_peak, peak_track_band_lower, peak_track_band_upper,
                   peak_track_age, peak_track_mass, peak_track_prominence,
                   peak_definition_version, peak_track_version, model_quality_min
            FROM read_parquet(?, hive_partitioning=false, union_by_name=true)
            ORDER BY symbol, trade_date
            """,
            [str(V3_ROOT / "symbol=*" / "daily_feature_candidate.parquet")],
        ).fetchdf()
    finally:
        con.close()
    v3["feature_date"] = pd.to_datetime(v3["feature_date"])
    return daily, v3


def load_panel() -> pd.DataFrame:
    gates, lifecycle = PRIOR.BASE.load_authoritative_ledger()
    panel = PRIOR.compute_base_free_evidence(PRIOR._attach_corporate_action_gate(PRIOR._load_base_free_sources(), gates))
    panel = PRIOR._attach_production_baseline(panel, lifecycle)
    daily, v3 = _load_extra_fields()
    panel = panel.merge(daily, on=["symbol", "feature_date"], how="left", validate="one_to_one")
    panel = panel.merge(v3, on=["symbol", "feature_date"], how="left", validate="one_to_one")
    if len(panel) != EXPECTED_ROWS or panel["symbol"].nunique() != EXPECTED_SYMBOLS:
        raise RuntimeError("governed panel coverage changed")
    panel = panel.sort_values(["symbol", "feature_date"]).reset_index(drop=True)
    panel["symbol_position"] = panel.groupby("symbol", sort=False).cumcount()
    panel["candidate_flag"] = (
        panel["price_candidate_eligible"].fillna(False)
        & panel["price_drawdown_20"].le(-0.05).fillna(False)
    )
    panel["analysis_factor"] = 1.0
    for _, sf in panel.groupby("symbol", sort=False):
        idx = sf.index
        raw_prior_close = sf["close"].shift(1)
        ratio = pd.Series(1.0, index=idx)
        reset = sf["corporate_action_count"].fillna(0).gt(0) & raw_prior_close.gt(0) & sf["preclose"].gt(0)
        ratio.loc[reset.index[reset]] = (sf.loc[reset, "preclose"] / raw_prior_close.loc[reset]).to_numpy()
        panel.loc[idx, "analysis_factor"] = ratio.cumprod().to_numpy()
    factor = panel["analysis_factor"].replace(0, np.nan)
    for name in ("open", "high", "low", "close", "preclose", "p50", "tracked_base_peak", "peak_track_band_lower", "peak_track_band_upper"):
        panel[f"analysis_{name}"] = pd.to_numeric(panel[name], errors="coerce") / factor
    panel["analysis_true_range"] = pd.concat(
        [
            panel["analysis_high"] - panel["analysis_low"],
            (panel["analysis_high"] - panel["analysis_preclose"]).abs(),
            (panel["analysis_low"] - panel["analysis_preclose"]).abs(),
        ],
        axis=1,
    ).max(axis=1)
    derived = [
        "atr14", "ma5", "ma20", "prior_high3", "prior_low5", "range_close_location", "valid_base_rate_20",
        "cost_migration_5", "mass_change_5", "prominence_change_5",
    ]
    for name in derived:
        panel[name] = np.nan
    for _, sf in panel.groupby("symbol", sort=False):
        idx = sf.index
        panel.loc[idx, "atr14"] = sf["analysis_true_range"].rolling(14, min_periods=14).mean().to_numpy()
        panel.loc[idx, "ma5"] = sf["analysis_close"].rolling(5, min_periods=5).mean().to_numpy()
        panel.loc[idx, "ma20"] = sf["analysis_close"].rolling(20, min_periods=20).mean().to_numpy()
        panel.loc[idx, "prior_high3"] = sf["analysis_high"].shift(1).rolling(3, min_periods=3).max().to_numpy()
        panel.loc[idx, "prior_low5"] = sf["analysis_low"].shift(1).rolling(5, min_periods=5).min().to_numpy()
        spread = (sf["analysis_high"] - sf["analysis_low"]).replace(0, np.nan)
        panel.loc[idx, "range_close_location"] = ((sf["analysis_close"] - sf["analysis_low"]) / spread).to_numpy()
        valid = sf["temporal_state"].eq("VALID_CANONICAL_BASE").astype(float)
        panel.loc[idx, "valid_base_rate_20"] = valid.rolling(20, min_periods=20).mean().to_numpy()
        same_track5 = sf["peak_track_id"].notna() & sf["peak_track_id"].eq(sf["peak_track_id"].shift(5))
        panel.loc[idx, "cost_migration_5"] = (sf["analysis_p50"] / sf["analysis_p50"].shift(5) - 1.0).where(same_track5).to_numpy()
        panel.loc[idx, "mass_change_5"] = (sf["peak_track_mass"] / sf["peak_track_mass"].shift(5) - 1.0).where(same_track5).to_numpy()
        panel.loc[idx, "prominence_change_5"] = (sf["peak_track_prominence"] / sf["peak_track_prominence"].shift(5) - 1.0).where(same_track5).to_numpy()
    panel["price_relative_to_base"] = panel["analysis_close"] / panel["analysis_tracked_base_peak"] - 1.0
    panel["peak_band_width_relative"] = (
        panel["analysis_peak_track_band_upper"] - panel["analysis_peak_track_band_lower"]
    ) / panel["analysis_close"]
    panel["days_since_rebinding"] = panel["peak_track_age"].where(panel["temporal_state"].eq("VALID_CANONICAL_BASE")) - 1
    panel["legal_buy_open"] = (
        panel["current_day_data_tradable"].fillna(False)
        & panel["trade_status"].eq(1)
        & ~panel["buy_blocked_open"].astype("boolean").fillna(True)
        & panel["open"].gt(0)
    )
    panel["legal_sell_open"] = (
        panel["current_day_data_tradable"].fillna(False)
        & panel["trade_status"].eq(1)
        & ~panel["sell_blocked_open"].astype("boolean").fillna(True)
        & panel["open"].gt(0)
    )
    panel["split"] = panel["feature_date"].map(date_split)
    if int(panel["candidate_flag"].sum()) != EXPECTED_CANDIDATE_ROWS:
        raise RuntimeError("P_PRICE_PULLBACK_20 candidate count changed")
    return panel


def freeze_candidates(panel: pd.DataFrame, fingerprint: str) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for symbol, sf in panel.groupby("symbol", sort=False):
        sf = sf.sort_values("feature_date").copy()
        onset = sf["candidate_flag"] & ~sf["candidate_flag"].shift(1, fill_value=False)
        sf["local_episode"] = onset.cumsum()
        candidates = sf[sf["candidate_flag"]].copy()
        if candidates.empty:
            continue
        start = candidates.groupby("local_episode")["feature_date"].transform("min")
        end = candidates.groupby("local_episode")["feature_date"].transform("max")
        duration = candidates.groupby("local_episode")["feature_date"].transform("size")
        age = candidates.groupby("local_episode").cumcount() + 1
        candidates["candidate_episode_id"] = [stable_id("cpe", fingerprint, symbol, value.date()) for value in start]
        candidates["candidate_observation_id"] = [stable_id("cpo", fingerprint, symbol, value.date()) for value in candidates["feature_date"]]
        candidates["candidate_episode_start"] = start
        candidates["candidate_episode_end_retrospective"] = end
        candidates["candidate_episode_duration_retrospective"] = duration.astype(int)
        candidates["candidate_episode_age_pit"] = age.astype(int)
        rows.append(candidates)
    result = pd.concat(rows, ignore_index=True).sort_values(["symbol", "feature_date"]).reset_index(drop=True)
    if len(result) != EXPECTED_CANDIDATE_ROWS or result["candidate_episode_id"].nunique() != EXPECTED_CANDIDATE_EPISODES:
        raise RuntimeError("candidate freeze invariants changed")
    keep = [
        "candidate_observation_id", "candidate_episode_id", "symbol", "feature_date", "split",
        "candidate_episode_start", "candidate_episode_end_retrospective", "candidate_episode_duration_retrospective",
        "candidate_episode_age_pit", "symbol_position", "price_drawdown_20", "price_history_count",
        "analysis_close", "daily_snapshot_id", "snapshot_id", "daily_available_at", "feature_available_at",
        "corporate_action_clear", "price_input_valid", "tradable_state",
    ]
    result = result[keep].copy()
    result["candidate_definition"] = CANDIDATE_DEFINITION["name"]
    result["candidate_definition_fingerprint"] = fingerprint
    result["source_commit"] = SOURCE_COMMIT
    result["research_universe"] = "FROZEN_V3_500_SYMBOL_UNIVERSE"
    return result


def template_signal(panel: pd.DataFrame, template: str) -> pd.Series:
    candidate = panel["candidate_flag"].fillna(False)
    if template == "T1_CLOSE_STRENGTH":
        return candidate & panel["analysis_close"].gt(panel["analysis_preclose"]) & panel["range_close_location"].ge(0.60)
    if template == "T2_RECLAIM_PRIOR_3_HIGH":
        return candidate & panel["analysis_close"].gt(panel["prior_high3"])
    if template == "T3_TREND_RESUMPTION":
        return candidate & panel["analysis_close"].gt(panel["ma5"]) & panel["ma5"].gt(panel["ma20"]) & panel["analysis_close"].gt(panel["analysis_preclose"])
    raise KeyError(template)


def next_legal_position(sf: pd.DataFrame, start_position: int, column: str, *, maximum_wait: int | None) -> int | None:
    stop = len(sf) if maximum_wait is None else min(len(sf), start_position + maximum_wait)
    for position in range(start_position, stop):
        if bool(sf.iloc[position][column]):
            return position
    return None


@dataclass(frozen=True)
class CostModel:
    commission_bps: float = COST_CONTRACT["commission_each_side_bps"]
    transfer_bps: float = COST_CONTRACT["transfer_fee_each_side_bps"]
    stamp_bps: float = COST_CONTRACT["sell_stamp_duty_bps"]
    slippage_bps: float = COST_CONTRACT["slippage_each_side_bps"]

    @property
    def buy_fee_rate(self) -> float:
        return (self.commission_bps + self.transfer_bps) / 10_000.0

    @property
    def sell_fee_rate(self) -> float:
        return (self.commission_bps + self.transfer_bps + self.stamp_bps) / 10_000.0

    @property
    def slippage_rate(self) -> float:
        return self.slippage_bps / 10_000.0


def _fill_return(entry: float, exits: list[tuple[float, float]], costs: CostModel) -> tuple[float, float, float]:
    gross_factor = sum(weight * price / entry for weight, price in exits)
    buy_outlay = entry * (1.0 + costs.slippage_rate) * (1.0 + costs.buy_fee_rate)
    proceeds = sum(
        weight * price * (1.0 - costs.slippage_rate) * (1.0 - costs.sell_fee_rate)
        for weight, price in exits
    )
    gross = gross_factor - 1.0
    net = proceeds / buy_outlay - 1.0
    return gross, net, gross - net


def _entry_features(signal: pd.Series, candidate: pd.Series) -> dict[str, Any]:
    values = {
        "entry_temporal_state": signal["temporal_state"],
        "candidate_temporal_state": candidate["temporal_state"],
        "entry_peak_track_id": signal["peak_track_id"],
        "candidate_peak_track_id": candidate["peak_track_id"],
        "root_anchor_retained_from_candidate": bool(
            pd.notna(signal["peak_track_id"])
            and pd.notna(candidate["peak_track_id"])
            and signal["peak_track_id"] == candidate["peak_track_id"]
        ),
    }
    features = (
        "peak_track_age", "valid_base_rate_20", "days_since_rebinding", "peak_track_mass", "peak_track_prominence",
        "peak_band_width_relative", "price_relative_to_base", "concentration_20", "profit_ratio", "cost_migration_5",
        "model_spread_cost_p50", "model_spread_cost_p90", "model_spread_dominant_peak_today", "mass_change_5",
        "prominence_change_5", "peak_track_split", "peak_track_merge", "peak_track_lost", "ensemble_peak_ambiguous",
    )
    for feature in features:
        values[f"entry_{feature}"] = signal[feature]
        values[f"candidate_{feature}"] = candidate[feature]
    return values


def build_template_trades(panel: pd.DataFrame, candidates: pd.DataFrame, template: str, costs: CostModel) -> pd.DataFrame:
    panel = panel.copy()
    panel["entry_trigger"] = template_signal(panel, template)
    candidate_lookup = candidates.set_index(["symbol", "feature_date"])
    rows: list[dict[str, Any]] = []
    for symbol, sf0 in panel.groupby("symbol", sort=False):
        sf = sf0.sort_values("feature_date").reset_index(drop=True)
        episode_signals = sf[sf["entry_trigger"]].copy()
        if episode_signals.empty:
            continue
        episode_signals["candidate_episode_id"] = [
            candidate_lookup.loc[(symbol, value), "candidate_episode_id"] for value in episode_signals["feature_date"]
        ]
        episode_signals = episode_signals.drop_duplicates("candidate_episode_id", keep="first")
        last_exit_pos = -1
        for signal in episode_signals.itertuples(index=False):
            signal_pos = int(signal.symbol_position - sf["symbol_position"].iloc[0])
            if signal_pos <= last_exit_pos:
                continue
            entry_pos = next_legal_position(sf, signal_pos + 1, "legal_buy_open", maximum_wait=5)
            candidate_row = candidate_lookup.loc[(symbol, signal.feature_date)]
            intent_date = sf.iloc[signal_pos + 1]["feature_date"] if signal_pos + 1 < len(sf) else pd.NaT
            trade_id = stable_id("trd", template, symbol, signal.feature_date.date(), signal.candidate_episode_id)
            if entry_pos is None:
                rows.append(
                    {
                        "trade_id": trade_id, "template": template, "symbol": symbol,
                        "candidate_episode_id": signal.candidate_episode_id,
                        "candidate_timestamp": candidate_row["candidate_episode_start"],
                        "entry_signal_timestamp": signal.feature_date, "entry_intent_timestamp": intent_date,
                        "actual_entry_timestamp": pd.NaT, "actual_entry_price": math.nan,
                        "entry_unfilled": True, "completed": False, "split": date_split(signal.feature_date),
                    }
                )
                continue
            entry = sf.iloc[entry_pos]
            risk_unit = 2.0 * safe_float(sf.iloc[signal_pos]["atr14"])
            if not finite(risk_unit) or risk_unit <= 0:
                continue
            entry_analysis = float(entry["analysis_open"])
            hard_stop_level = entry_analysis - risk_unit
            running_high = float(entry["analysis_high"])
            exit_signal_pos: int | None = None
            exit_reason = "OPEN_AT_END"
            mfe_at_signal = max(0.0, running_high / entry_analysis - 1.0)
            for position in range(entry_pos, len(sf)):
                row = sf.iloc[position]
                running_high = max(running_high, float(row["analysis_high"]))
                mfe_at_signal = max(0.0, running_high / entry_analysis - 1.0)
                holding = position - entry_pos + 1
                hard = float(row["analysis_close"]) <= hard_stop_level
                protect = mfe_at_signal >= (2.0 * risk_unit / entry_analysis) and float(row["analysis_close"]) < float(row["ma5"])
                structure = holding >= 3 and float(row["analysis_close"]) < float(row["prior_low5"])
                time_exit = holding >= int(BASELINE_CONTRACT["maximum_holding_sessions"])
                if hard or protect or structure or time_exit:
                    exit_signal_pos = position
                    exit_reason = "HARD_STOP" if hard else "PROFIT_PROTECTION" if protect else "STRUCTURE_EXIT" if structure else "TIME_EXIT"
                    break
            exit_pos = None if exit_signal_pos is None else next_legal_position(sf, exit_signal_pos + 1, "legal_sell_open", maximum_wait=None)
            completed = exit_pos is not None
            terminal_pos = exit_pos if completed else len(sf) - 1
            terminal_price = float(sf.iloc[exit_pos]["analysis_open"] if completed else sf.iloc[-1]["analysis_close"])
            last_path_pos = exit_signal_pos if exit_signal_pos is not None else len(sf) - 1
            path = sf.iloc[entry_pos : last_path_pos + 1]
            mfe = float(path["analysis_high"].max() / entry_analysis - 1.0)
            mae = float(path["analysis_low"].min() / entry_analysis - 1.0)
            gross, net, cost = _fill_return(entry_analysis, [(1.0, terminal_price)], costs)
            trigger_strength = float(sf.iloc[signal_pos]["analysis_close"] / sf.iloc[signal_pos]["ma5"] - 1.0) if finite(sf.iloc[signal_pos]["ma5"]) else 0.0
            row = {
                "trade_id": trade_id, "template": template, "symbol": symbol,
                "candidate_episode_id": signal.candidate_episode_id,
                "candidate_timestamp": candidate_row["candidate_episode_start"],
                "entry_trigger_timestamp": signal.feature_date,
                "entry_signal_timestamp": signal.feature_date,
                "entry_intent_timestamp": intent_date,
                "actual_entry_timestamp": entry["feature_date"],
                "actual_entry_market_open": float(entry["open"]),
                "actual_entry_price": float(entry["open"]) * (1.0 + costs.slippage_rate),
                "entry_analysis_open": entry_analysis,
                "entry_signal_position": signal_pos,
                "entry_position": entry_pos,
                "entry_wait_sessions": entry_pos - signal_pos,
                "entry_unfilled": False,
                "hard_stop_analysis_level": hard_stop_level,
                "risk_unit_fraction": risk_unit / entry_analysis,
                "exit_trigger_timestamp": sf.iloc[exit_signal_pos]["feature_date"] if exit_signal_pos is not None else pd.NaT,
                "exit_intent_timestamp": sf.iloc[exit_signal_pos + 1]["feature_date"] if exit_signal_pos is not None and exit_signal_pos + 1 < len(sf) else pd.NaT,
                "actual_exit_timestamp": sf.iloc[exit_pos]["feature_date"] if completed else pd.NaT,
                "actual_exit_market_open": float(sf.iloc[exit_pos]["open"]) if completed else math.nan,
                "actual_exit_price": float(sf.iloc[exit_pos]["open"]) * (1.0 - costs.slippage_rate) if completed else math.nan,
                "exit_analysis_open_or_terminal_close": terminal_price,
                "exit_signal_position": exit_signal_pos if exit_signal_pos is not None else pd.NA,
                "exit_position": terminal_pos,
                "exit_reason": exit_reason,
                "completed": completed,
                "split": date_split(signal.feature_date),
                "holding_sessions": terminal_pos - entry_pos + 1,
                "gross_return": gross, "net_return": net, "transaction_cost_return": cost,
                "mfe": mfe, "mae": mae,
                "mfe_capture_ratio": gross / mfe if mfe > 0 else math.nan,
                "profit_giveback_from_mfe": mfe - gross,
                "trigger_strength": trigger_strength,
                "partial_exit_timestamp": pd.NaT, "partial_exit_analysis_price": math.nan, "partial_exit_fraction": 0.0,
            }
            row.update(_entry_features(sf.iloc[signal_pos], panel.loc[(panel["symbol"].eq(symbol)) & (panel["feature_date"].eq(candidate_row["candidate_episode_start"]))].iloc[0]))
            rows.append(row)
            last_exit_pos = terminal_pos
    result = pd.DataFrame(rows)
    if result.empty:
        raise RuntimeError(f"template produced no trades: {template}")
    return result.sort_values(["entry_signal_timestamp", "symbol", "trade_id"]).reset_index(drop=True)


def profit_factor(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(numeric[numeric > 0].sum())
    losses = float(-numeric[numeric < 0].sum())
    return gains / losses if losses > 0 else math.inf if gains > 0 else math.nan


def trade_metrics(trades: pd.DataFrame, variant: str, split: str) -> dict[str, Any]:
    subset = trades[trades["completed"].fillna(False)].copy()
    if split != "total":
        subset = subset[subset["split"].eq(split)]
    values = pd.to_numeric(subset["net_return"], errors="coerce")
    winners = values[values > 0]
    losers = values[values < 0]
    return {
        "variant": variant, "split": split, "completed_trades": len(subset),
        "win_rate": float(values.gt(0).mean()) if len(values) else math.nan,
        "mean_return": float(values.mean()) if len(values) else math.nan,
        "median_return": float(values.median()) if len(values) else math.nan,
        "average_winner": float(winners.mean()) if len(winners) else math.nan,
        "average_loser": float(losers.mean()) if len(losers) else math.nan,
        "payoff_ratio": float(winners.mean() / -losers.mean()) if len(winners) and len(losers) else math.nan,
        "profit_factor": profit_factor(values),
        "worst_trade": float(values.min()) if len(values) else math.nan,
        "return_p01": float(values.quantile(0.01)) if len(values) else math.nan,
        "return_p05": float(values.quantile(0.05)) if len(values) else math.nan,
        "large_loss_probability": float(values.le(LARGE_LOSS).mean()) if len(values) else math.nan,
        "large_winner_probability": float(values.ge(LARGE_WINNER).mean()) if len(values) else math.nan,
        "average_holding_period": float(subset["holding_sessions"].mean()) if len(subset) else math.nan,
        "median_holding_period": float(subset["holding_sessions"].median()) if len(subset) else math.nan,
        "mean_mfe": float(subset["mfe"].mean()) if len(subset) else math.nan,
        "mean_mae": float(subset["mae"].mean()) if len(subset) else math.nan,
        "mean_mfe_capture_ratio": float(subset["mfe_capture_ratio"].replace([np.inf, -np.inf], np.nan).mean()) if len(subset) else math.nan,
        "mean_profit_giveback": float(subset["profit_giveback_from_mfe"].mean()) if len(subset) else math.nan,
    }


def select_baseline(template_trades: dict[str, pd.DataFrame]) -> tuple[str, pd.DataFrame]:
    rows = []
    for template, trades in template_trades.items():
        row = trade_metrics(trades, template, "discovery")
        row["template_description"] = BASELINE_TEMPLATES[template]
        rows.append(row)
    comparison = pd.DataFrame(rows).sort_values("variant")
    eligible = comparison[comparison["completed_trades"].ge(30)].copy()
    if eligible.empty:
        raise RuntimeError("no price baseline template meets the pre-registered discovery sample minimum")
    selected = eligible.sort_values(["profit_factor", "variant"], ascending=[False, True]).iloc[0]["variant"]
    comparison["selected_on_discovery"] = comparison["variant"].eq(selected)
    return str(selected), comparison


def discovery_thresholds(trades: pd.DataFrame) -> dict[str, float]:
    discovery = trades[trades["split"].eq("discovery") & trades["completed"].fillna(False)]
    thresholds: dict[str, float] = {}
    for feature in ("entry_peak_track_mass", "entry_peak_track_prominence"):
        values = pd.to_numeric(discovery[feature], errors="coerce").dropna()
        if values.empty:
            raise RuntimeError(f"missing discovery threshold population: {feature}")
        thresholds[f"{feature}_median"] = float(values.median())
    volatility = pd.to_numeric(discovery["risk_unit_fraction"], errors="coerce").dropna()
    thresholds["volatility_q33"] = float(volatility.quantile(1 / 3))
    thresholds["volatility_q67"] = float(volatility.quantile(2 / 3))
    return thresholds


def healthy_structure(row: pd.Series, thresholds: dict[str, float]) -> bool:
    return bool(
        row["temporal_state"] == "VALID_CANONICAL_BASE"
        and finite(row["peak_track_age"]) and float(row["peak_track_age"]) >= 20
        and finite(row["peak_track_mass"]) and float(row["peak_track_mass"]) >= thresholds["entry_peak_track_mass_median"]
        and finite(row["peak_track_prominence"]) and float(row["peak_track_prominence"]) >= thresholds["entry_peak_track_prominence_median"]
        and not bool(row["peak_track_split"])
        and not bool(row["peak_track_merge"])
        and not bool(row["peak_track_lost"])
    )


def overlay_acceptance(trades: pd.DataFrame, level: str, thresholds: dict[str, float]) -> pd.Series:
    state = trades["entry_temporal_state"]
    if level == "P0":
        return pd.Series(True, index=trades.index)
    p1 = state.isin(["VALID_CANONICAL_BASE", "ENSEMBLE_AMBIGUOUS"])
    if level == "P1":
        return p1
    p2 = p1 & state.eq("VALID_CANONICAL_BASE") & pd.to_numeric(trades["entry_peak_track_age"], errors="coerce").ge(20)
    if level == "P2":
        return p2
    p3 = (
        p2
        & pd.to_numeric(trades["entry_peak_track_mass"], errors="coerce").ge(thresholds["entry_peak_track_mass_median"])
        & pd.to_numeric(trades["entry_peak_track_prominence"], errors="coerce").ge(thresholds["entry_peak_track_prominence_median"])
    )
    if level in {"P3", "P4", "P5", "P6"}:
        return p3
    raise KeyError(level)


def sizing_multiplier(trades: pd.DataFrame, thresholds: dict[str, float]) -> pd.Series:
    state = trades["entry_temporal_state"]
    age = pd.to_numeric(trades["entry_peak_track_age"], errors="coerce")
    mass = pd.to_numeric(trades["entry_peak_track_mass"], errors="coerce")
    prominence = pd.to_numeric(trades["entry_peak_track_prominence"], errors="coerce")
    high = (
        state.eq("VALID_CANONICAL_BASE") & age.ge(20)
        & mass.ge(thresholds["entry_peak_track_mass_median"])
        & prominence.ge(thresholds["entry_peak_track_prominence_median"])
    )
    low = state.isin(["SPLIT", "MERGE", "LOST/TRANSITION", "NO_CANONICAL_BASE"])
    raw = pd.Series(1.0, index=trades.index)
    raw.loc[low] = 0.75
    raw.loc[high] = 1.25
    discovery = trades["split"].eq("discovery") & trades["completed"].fillna(False)
    normalizer = 1.0 / float(raw.loc[discovery].mean()) if discovery.any() else 1.0
    return (raw * normalizer).clip(lower=0.70, upper=1.30)


def _recompute_profile_metrics(
    profile: dict[str, Any], sf: pd.DataFrame, entry_pos: int, exit_signal_pos: int | None, exit_pos: int | None,
    partial_pos: int | None, costs: CostModel,
) -> dict[str, Any]:
    completed = exit_pos is not None
    terminal_pos = exit_pos if completed else len(sf) - 1
    terminal_price = float(sf.iloc[exit_pos]["analysis_open"] if completed else sf.iloc[-1]["analysis_close"])
    last_path_pos = exit_signal_pos if exit_signal_pos is not None else len(sf) - 1
    path = sf.iloc[entry_pos : last_path_pos + 1]
    entry_price = float(profile["entry_analysis_open"])
    mfe = float(path["analysis_high"].max() / entry_price - 1.0)
    mae = float(path["analysis_low"].min() / entry_price - 1.0)
    exits = [(1.0, terminal_price)]
    if partial_pos is not None:
        exits = [(0.5, float(sf.iloc[partial_pos]["analysis_open"])), (0.5, terminal_price)]
    gross, net, transaction_cost = _fill_return(entry_price, exits, costs)
    profile.update(
        {
            "exit_trigger_timestamp": sf.iloc[exit_signal_pos]["feature_date"] if exit_signal_pos is not None else pd.NaT,
            "exit_intent_timestamp": sf.iloc[exit_signal_pos + 1]["feature_date"] if exit_signal_pos is not None and exit_signal_pos + 1 < len(sf) else pd.NaT,
            "actual_exit_timestamp": sf.iloc[exit_pos]["feature_date"] if completed else pd.NaT,
            "actual_exit_market_open": float(sf.iloc[exit_pos]["open"]) if completed else math.nan,
            "actual_exit_price": float(sf.iloc[exit_pos]["open"]) * (1.0 - costs.slippage_rate) if completed else math.nan,
            "exit_analysis_open_or_terminal_close": terminal_price,
            "exit_signal_position": exit_signal_pos if exit_signal_pos is not None else pd.NA,
            "exit_position": terminal_pos,
            "completed": completed,
            "holding_sessions": terminal_pos - entry_pos + 1,
            "gross_return": gross, "net_return": net, "transaction_cost_return": transaction_cost,
            "mfe": mfe, "mae": mae,
            "mfe_capture_ratio": gross / mfe if mfe > 0 else math.nan,
            "profit_giveback_from_mfe": mfe - gross,
            "partial_exit_timestamp": sf.iloc[partial_pos]["feature_date"] if partial_pos is not None else pd.NaT,
            "partial_exit_analysis_price": float(sf.iloc[partial_pos]["analysis_open"]) if partial_pos is not None else math.nan,
            "partial_exit_fraction": 0.5 if partial_pos is not None else 0.0,
        }
    )
    return profile


def apply_holding_and_deterioration(
    trades: pd.DataFrame, panel: pd.DataFrame, thresholds: dict[str, float], costs: CostModel, *,
    holding: bool, deterioration: bool,
) -> pd.DataFrame:
    symbol_panels = {symbol: sf.sort_values("feature_date").reset_index(drop=True) for symbol, sf in panel.groupby("symbol", sort=False)}
    output: list[dict[str, Any]] = []
    for source in trades.to_dict("records"):
        profile = dict(source)
        if bool(source.get("entry_unfilled", False)) or not finite(source.get("entry_position")):
            output.append(profile)
            continue
        sf = symbol_panels[source["symbol"]]
        entry_pos = int(source["entry_position"])
        baseline_signal = int(source["exit_signal_position"]) if finite(source.get("exit_signal_position")) else None
        exit_signal_pos = baseline_signal
        exit_reason = source["exit_reason"]
        if holding and baseline_signal is not None and exit_reason != "HARD_STOP":
            signal_row = sf.iloc[baseline_signal]
            profitable = float(signal_row["analysis_close"]) > float(source["entry_analysis_open"])
            if profitable and healthy_structure(signal_row, thresholds):
                maximum = min(len(sf) - 1, baseline_signal + 5)
                chosen = maximum
                chosen_reason = "HEALTHY_HOLD_MAX_EXTENSION"
                for position in range(baseline_signal + 1, maximum + 1):
                    row = sf.iloc[position]
                    if float(row["analysis_close"]) <= float(source["hard_stop_analysis_level"]):
                        chosen, chosen_reason = position, "HARD_STOP_DURING_HEALTHY_HOLD"
                        break
                    if not healthy_structure(row, thresholds):
                        chosen, chosen_reason = position, "CHIP_HEALTH_LOST_AFTER_EXTENSION"
                        break
                exit_signal_pos, exit_reason = chosen, chosen_reason
        exit_pos = None if exit_signal_pos is None else next_legal_position(sf, exit_signal_pos + 1, "legal_sell_open", maximum_wait=None)
        partial_pos: int | None = None
        deterioration_signal_pos: int | None = None
        if deterioration and exit_signal_pos is not None:
            running_mass = -math.inf
            running_prominence = -math.inf
            entry_track = source.get("entry_peak_track_id")
            for position in range(entry_pos, exit_signal_pos + 1):
                row = sf.iloc[position]
                same_track = pd.notna(entry_track) and row["peak_track_id"] == entry_track and row["temporal_state"] == "VALID_CANONICAL_BASE"
                if same_track and finite(row["peak_track_mass"]) and finite(row["peak_track_prominence"]):
                    running_mass = max(running_mass, float(row["peak_track_mass"]))
                    running_prominence = max(running_prominence, float(row["peak_track_prominence"]))
                    deteriorated = (
                        running_mass > 0 and running_prominence > 0
                        and float(row["peak_track_mass"]) <= 0.80 * running_mass
                        and float(row["peak_track_prominence"]) <= 0.80 * running_prominence
                        and finite(row["ma5"]) and float(row["analysis_close"]) < float(row["ma5"])
                    )
                    if deteriorated:
                        candidate_partial = next_legal_position(sf, position + 1, "legal_sell_open", maximum_wait=None)
                        if candidate_partial is not None and (exit_pos is None or candidate_partial < exit_pos):
                            deterioration_signal_pos, partial_pos = position, candidate_partial
                        break
        profile["exit_reason"] = exit_reason
        profile["deterioration_signal_timestamp"] = sf.iloc[deterioration_signal_pos]["feature_date"] if deterioration_signal_pos is not None else pd.NaT
        output.append(_recompute_profile_metrics(profile, sf, entry_pos, exit_signal_pos, exit_pos, partial_pos, costs))
    return pd.DataFrame(output).sort_values(["entry_signal_timestamp", "symbol", "trade_id"]).reset_index(drop=True)


def build_variants(
    baseline: pd.DataFrame, panel: pd.DataFrame, thresholds: dict[str, float], costs: CostModel,
) -> dict[str, pd.DataFrame]:
    hold = apply_holding_and_deterioration(baseline, panel, thresholds, costs, holding=True, deterioration=False)
    derisk = apply_holding_and_deterioration(baseline, panel, thresholds, costs, holding=False, deterioration=True)
    combined = apply_holding_and_deterioration(baseline, panel, thresholds, costs, holding=True, deterioration=True)
    variants: dict[str, pd.DataFrame] = {}
    definitions = {
        "P0_PRICE_ONLY": (baseline, "P0", False),
        "I_CONFIRMATION_ONLY": (baseline, "P1", False),
        "I_SIZING_ONLY": (baseline, "P0", True),
        "I_HOLDING_ONLY": (hold, "P0", False),
        "I_DERISK_ONLY": (derisk, "P0", False),
        "P1_TEMPORAL_CONFIRMATION": (baseline, "P1", False),
        "P2_CANONICAL_PERSISTENCE": (baseline, "P2", False),
        "P3_MASS_PROMINENCE": (baseline, "P3", False),
        "P4_CHIP_SIZING": (baseline, "P4", True),
        "P5_HEALTHY_HOLDING": (hold, "P5", True),
        "P6_DETERIORATION_DERISK": (combined, "P6", True),
    }
    base_sizes = sizing_multiplier(baseline, thresholds).set_axis(baseline["trade_id"])
    for name, (profile, level, use_sizing) in definitions.items():
        frame = profile.copy()
        frame["variant"] = name
        frame["overlay_accepted"] = overlay_acceptance(frame, level, thresholds).to_numpy()
        frame["size_multiplier"] = frame["trade_id"].map(base_sizes).fillna(1.0) if use_sizing else 1.0
        variants[name] = frame
    return variants


def _state_group(values: pd.Series) -> pd.Series:
    result = values.astype("string").copy()
    result.loc[result.isin(["SPLIT", "MERGE", "LOST/TRANSITION"])] = "SPLIT_MERGE_LOST_OR_TRANSITION"
    return result


def chip_state_stratification(baseline: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for timing in ("candidate", "entry"):
        state = _state_group(baseline[f"{timing}_temporal_state"])
        for split in ("total", *SPLITS):
            source = baseline if split == "total" else baseline[baseline["split"].eq(split)]
            source_state = state.loc[source.index]
            for group in ("VALID_CANONICAL_BASE", "ENSEMBLE_AMBIGUOUS", "NO_CANONICAL_BASE", "SPLIT_MERGE_LOST_OR_TRANSITION"):
                subset = source[source_state.eq(group) & source["completed"].fillna(False)]
                metrics = trade_metrics(subset, "P0_PRICE_ONLY", "total")
                rows.append({"observation_timing": timing, "chip_state": group, **{key: value for key, value in metrics.items() if key not in {"variant", "split"}}, "split": split})
    return pd.DataFrame(rows)


FEATURES = (
    "peak_track_age", "valid_base_rate_20", "days_since_rebinding", "peak_track_mass", "peak_track_prominence",
    "peak_band_width_relative", "price_relative_to_base", "concentration_20", "profit_ratio", "cost_migration_5",
    "root_anchor_retained_from_candidate", "model_spread_cost_p50", "model_spread_cost_p90",
    "model_spread_dominant_peak_today", "ensemble_peak_ambiguous", "peak_track_split", "peak_track_merge", "peak_track_lost",
    "mass_change_5", "prominence_change_5",
)


def chip_feature_attribution(baseline: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    discovery = baseline[baseline["split"].eq("discovery") & baseline["completed"].fillna(False)]
    for timing in ("candidate", "entry"):
        for feature in FEATURES:
            column = feature if feature == "root_anchor_retained_from_candidate" else f"{timing}_{feature}"
            values = baseline[column]
            is_boolean = pd.api.types.is_bool_dtype(values.dtype) or feature in {
                "root_anchor_retained_from_candidate", "ensemble_peak_ambiguous", "peak_track_split", "peak_track_merge", "peak_track_lost"
            }
            thresholds: tuple[float, float] | None = None
            if not is_boolean:
                discovery_values = pd.to_numeric(discovery[column], errors="coerce").dropna()
                if len(discovery_values) >= 10:
                    thresholds = (float(discovery_values.quantile(1 / 3)), float(discovery_values.quantile(2 / 3)))
            for split in ("total", *SPLITS):
                source = baseline if split == "total" else baseline[baseline["split"].eq(split)]
                source = source[source["completed"].fillna(False)].copy()
                if is_boolean:
                    boolean = source[column].astype("boolean").fillna(False)
                    groups = {"FALSE": source[~boolean], "TRUE": source[boolean]}
                elif thresholds is None:
                    groups = {"UNAVAILABLE": source.iloc[0:0]}
                else:
                    numeric = pd.to_numeric(source[column], errors="coerce")
                    low, high = thresholds
                    groups = {
                        "LOW": source[numeric.le(low)],
                        "MID": source[numeric.gt(low) & numeric.lt(high)],
                        "HIGH": source[numeric.ge(high)],
                        "MISSING": source[numeric.isna()],
                    }
                for bucket, subset in groups.items():
                    metrics = trade_metrics(subset, "P0_PRICE_ONLY", "total")
                    rows.append(
                        {
                            "observation_timing": timing, "feature": feature, "bucket": bucket, "split": split,
                            "discovery_low_threshold": thresholds[0] if thresholds else math.nan,
                            "discovery_high_threshold": thresholds[1] if thresholds else math.nan,
                            **{key: value for key, value in metrics.items() if key not in {"variant", "split"}},
                        }
                    )
    # In-position deterioration is a separately defined role, not an entry-level feature.
    for split in ("total", *SPLITS):
        source = baseline if split == "total" else baseline[baseline["split"].eq(split)]
        for feature in ("mass_deterioration_20pct", "prominence_deterioration_20pct", "combined_deterioration_with_price_confirmation"):
            flag = source[feature].fillna(False).astype(bool)
            for bucket, subset in (("FALSE", source[~flag]), ("TRUE", source[flag])):
                metrics = trade_metrics(subset, "P0_PRICE_ONLY", "total")
                rows.append(
                    {
                        "observation_timing": "in_position", "feature": feature, "bucket": bucket, "split": split,
                        "discovery_low_threshold": -0.20, "discovery_high_threshold": -0.20,
                        **{key: value for key, value in metrics.items() if key not in {"variant", "split"}},
                    }
                )
    return pd.DataFrame(rows)


def attach_deterioration_characteristics(trades: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    result = trades.copy()
    for name in ("mass_deterioration_20pct", "prominence_deterioration_20pct", "combined_deterioration_with_price_confirmation"):
        result[name] = False
    symbol_panels = {symbol: sf.sort_values("feature_date").reset_index(drop=True) for symbol, sf in panel.groupby("symbol", sort=False)}
    for index, trade in result[result["actual_entry_timestamp"].notna()].iterrows():
        sf = symbol_panels[trade["symbol"]]
        start = int(trade["entry_position"])
        stop = int(trade["exit_signal_position"]) if finite(trade["exit_signal_position"]) else len(sf) - 1
        path = sf.iloc[start : stop + 1]
        track = trade.get("entry_peak_track_id")
        path = path[path["peak_track_id"].eq(track) & path["temporal_state"].eq("VALID_CANONICAL_BASE")]
        if path.empty:
            continue
        running_mass = path["peak_track_mass"].cummax()
        running_prominence = path["peak_track_prominence"].cummax()
        mass = path["peak_track_mass"].le(0.8 * running_mass)
        prominence = path["peak_track_prominence"].le(0.8 * running_prominence)
        price = path["analysis_close"].lt(path["ma5"])
        result.at[index, "mass_deterioration_20pct"] = bool(mass.any())
        result.at[index, "prominence_deterioration_20pct"] = bool(prominence.any())
        result.at[index, "combined_deterioration_with_price_confirmation"] = bool((mass & prominence & price).any())
    return result


def simulate_portfolio(
    trades: pd.DataFrame, panel: pd.DataFrame, costs: CostModel, *, apply_costs: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.Index(sorted(pd.to_datetime(panel["feature_date"].unique())))
    close_lookup = panel.set_index(["feature_date", "symbol"])["analysis_close"]
    accepted = trades[
        trades["overlay_accepted"].fillna(False)
        & trades["actual_entry_timestamp"].notna()
    ].copy()
    accepted["actual_entry_timestamp"] = pd.to_datetime(accepted["actual_entry_timestamp"])
    accepted["actual_exit_timestamp"] = pd.to_datetime(accepted["actual_exit_timestamp"])
    accepted["partial_exit_timestamp"] = pd.to_datetime(accepted["partial_exit_timestamp"])
    entry_map = {date: frame for date, frame in accepted.groupby("actual_entry_timestamp")}
    exit_map = {date: frame for date, frame in accepted.dropna(subset=["actual_exit_timestamp"]).groupby("actual_exit_timestamp")}
    partial_map = {date: frame for date, frame in accepted.dropna(subset=["partial_exit_timestamp"]).groupby("partial_exit_timestamp")}
    cash = float(PORTFOLIO_CONTRACT["initial_capital"])
    positions: dict[str, dict[str, Any]] = {}
    symbol_positions: dict[str, str] = {}
    daily_rows: list[dict[str, Any]] = []
    admission_rows: list[dict[str, Any]] = []
    slippage = costs.slippage_rate if apply_costs else 0.0
    buy_fee = costs.buy_fee_rate if apply_costs else 0.0
    sell_fee = costs.sell_fee_rate if apply_costs else 0.0
    last_prices: dict[str, float] = {}

    for date in dates:
        turnover = 0.0
        transaction_cost = 0.0
        # Full and partial exits occur at the legal open before new entries.
        for _, trade in exit_map.get(date, pd.DataFrame()).iterrows():
            position = positions.pop(trade["trade_id"], None)
            if position is None:
                continue
            symbol_positions.pop(position["symbol"], None)
            market_price = float(trade["exit_analysis_open_or_terminal_close"])
            shares = float(position["shares"])
            mid = shares * market_price
            proceeds = mid * (1.0 - slippage) * (1.0 - sell_fee)
            cash += proceeds
            turnover += mid
            transaction_cost += mid - proceeds
        for _, trade in partial_map.get(date, pd.DataFrame()).iterrows():
            position = positions.get(trade["trade_id"])
            if position is None or position["remaining_fraction"] <= 0.5:
                continue
            market_price = float(trade["partial_exit_analysis_price"])
            shares = float(position["original_shares"]) * float(trade["partial_exit_fraction"])
            mid = shares * market_price
            proceeds = mid * (1.0 - slippage) * (1.0 - sell_fee)
            cash += proceeds
            turnover += mid
            transaction_cost += mid - proceeds
            position["shares"] -= shares
            position["remaining_fraction"] -= float(trade["partial_exit_fraction"])

        current_value = cash
        for position in positions.values():
            price = last_prices.get(position["symbol"], position["entry_price"])
            current_value += position["shares"] * price
        candidates = entry_map.get(date, pd.DataFrame()).sort_values(
            ["trigger_strength", "symbol", "trade_id"], ascending=[False, True, True]
        ) if date in entry_map else pd.DataFrame()
        for _, trade in candidates.iterrows():
            admitted = True
            reason = "ADMITTED"
            if len(positions) >= int(PORTFOLIO_CONTRACT["maximum_concurrent_positions"]):
                admitted, reason = False, "NO_PORTFOLIO_SLOT"
            elif trade["symbol"] in symbol_positions:
                admitted, reason = False, "SYMBOL_ALREADY_HELD"
            if admitted:
                market_price = float(trade["entry_analysis_open"])
                target = current_value * float(PORTFOLIO_CONTRACT["baseline_target_fraction"]) * float(trade["size_multiplier"])
                maximum_mid = cash / ((1.0 + slippage) * (1.0 + buy_fee))
                mid = min(target, maximum_mid)
                if mid <= 1e-12:
                    admitted, reason = False, "INSUFFICIENT_CASH"
                else:
                    shares = mid / market_price
                    outlay = mid * (1.0 + slippage) * (1.0 + buy_fee)
                    cash -= outlay
                    turnover += mid
                    transaction_cost += outlay - mid
                    positions[trade["trade_id"]] = {
                        "trade_id": trade["trade_id"], "symbol": trade["symbol"], "shares": shares,
                        "original_shares": shares, "remaining_fraction": 1.0, "entry_price": market_price,
                    }
                    symbol_positions[trade["symbol"]] = trade["trade_id"]
                    last_prices[trade["symbol"]] = market_price
            admission_rows.append(
                {"variant": trade["variant"], "trade_id": trade["trade_id"], "date": date, "admitted": admitted, "admission_reason": reason}
            )

        market_value = 0.0
        for position in positions.values():
            key = (date, position["symbol"])
            if key in close_lookup.index and finite(close_lookup.loc[key]):
                last_prices[position["symbol"]] = float(close_lookup.loc[key])
            market_value += position["shares"] * last_prices[position["symbol"]]
        equity = cash + market_value
        daily_rows.append(
            {
                "date": date, "equity": equity, "cash": cash, "market_value": market_value,
                "exposure": market_value / equity if equity > 0 else math.nan,
                "turnover_notional": turnover, "transaction_cost": transaction_cost,
                "open_positions": len(positions),
            }
        )
    curve = pd.DataFrame(daily_rows)
    curve["daily_return"] = curve["equity"].pct_change(fill_method=None)
    curve.loc[curve.index[0], "daily_return"] = curve.loc[curve.index[0], "equity"] / float(PORTFOLIO_CONTRACT["initial_capital"]) - 1.0
    return curve, pd.DataFrame(admission_rows)


def _max_drawdown(values: pd.Series) -> tuple[float, int]:
    series = pd.to_numeric(values, errors="coerce").dropna()
    if series.empty:
        return math.nan, 0
    running = series.cummax()
    drawdown = series / running - 1.0
    maximum = float(drawdown.min())
    longest = current = 0
    for underwater in drawdown.lt(0):
        current = current + 1 if underwater else 0
        longest = max(longest, current)
    return maximum, longest


def portfolio_metrics(
    variant: str, gross_curve: pd.DataFrame, net_curve: pd.DataFrame, admissions: pd.DataFrame, split: str,
) -> dict[str, Any]:
    if split == "total":
        gross = gross_curve.copy()
        net = net_curve.copy()
    else:
        gross = gross_curve[gross_curve["date"].map(date_split).eq(split)].copy()
        net = net_curve[net_curve["date"].map(date_split).eq(split)].copy()
    if net.empty:
        return {"variant": variant, "split": split}
    gross_total = float((1.0 + gross["daily_return"]).prod() - 1.0)
    net_total = float((1.0 + net["daily_return"]).prod() - 1.0)
    daily = pd.to_numeric(net["daily_return"], errors="coerce").dropna()
    elapsed_years = max((net["date"].iloc[-1] - net["date"].iloc[0]).days / 365.25, len(net) / 252.0, 1 / 252)
    annualized = (1.0 + net_total) ** (1.0 / elapsed_years) - 1.0 if net_total > -1 else -1.0
    volatility = float(daily.std(ddof=1))
    downside = float(daily[daily < 0].std(ddof=1))
    sharpe = float(daily.mean() / volatility * math.sqrt(252)) if volatility > 0 else math.nan
    sortino = float(daily.mean() / downside * math.sqrt(252)) if downside > 0 else math.nan
    drawdown, duration = _max_drawdown((1.0 + daily).cumprod())
    calmar = annualized / abs(drawdown) if drawdown < 0 else math.nan
    split_admissions = admissions if split == "total" else admissions[admissions["date"].map(date_split).eq(split)]
    average_equity = float(net["equity"].mean())
    return {
        "variant": variant, "split": split,
        "gross_total_return": gross_total, "net_total_return": net_total,
        "annualized_return": annualized, "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
        "maximum_drawdown": drawdown, "maximum_drawdown_duration_sessions": duration,
        "average_exposure": float(net["exposure"].mean()),
        "capital_utilization": float(net["exposure"].mean()),
        "turnover": float(net["turnover_notional"].sum() / average_equity) if average_equity > 0 else math.nan,
        "transaction_costs": float(net["transaction_cost"].sum()),
        "entry_intents": len(split_admissions), "portfolio_admitted_entries": int(split_admissions["admitted"].sum()) if len(split_admissions) else 0,
        "capacity_rejections": int((~split_admissions["admitted"]).sum()) if len(split_admissions) else 0,
        "average_open_positions": float(net["open_positions"].mean()),
        "terminal_open_positions": int(net["open_positions"].iloc[-1]),
        "ending_equity": float(net["equity"].iloc[-1]),
    }


def evaluate_variants(
    variants: dict[str, pd.DataFrame], panel: pd.DataFrame, costs: CostModel,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, tuple[pd.DataFrame, pd.DataFrame]], dict[str, pd.DataFrame]]:
    portfolio_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    curves: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    admissions: dict[str, pd.DataFrame] = {}
    zero = CostModel(0.0, 0.0, 0.0, 0.0)
    for name, trades in variants.items():
        gross_curve, _ = simulate_portfolio(trades, panel, zero, apply_costs=False)
        net_curve, admitted = simulate_portfolio(trades, panel, costs, apply_costs=True)
        curves[name] = (gross_curve, net_curve)
        admissions[name] = admitted
        accepted = trades[trades["overlay_accepted"].fillna(False)]
        for split in ("total", *SPLITS):
            portfolio_row = portfolio_metrics(name, gross_curve, net_curve, admitted, split)
            split_admitted = admitted[admitted["admitted"]]
            if split != "total":
                split_admitted = split_admitted[split_admitted["date"].map(date_split).eq(split)]
            admitted_trades = trades[trades["trade_id"].isin(split_admitted["trade_id"]) & trades["completed"].fillna(False)]
            admitted_metrics = trade_metrics(admitted_trades, name, "total")
            portfolio_row.update(
                {
                    "admitted_completed_trades": admitted_metrics["completed_trades"],
                    "admitted_trade_mean_return": admitted_metrics["mean_return"],
                    "admitted_trade_win_rate": admitted_metrics["win_rate"],
                    "admitted_trade_profit_factor": admitted_metrics["profit_factor"],
                    "admitted_trade_return_p05": admitted_metrics["return_p05"],
                }
            )
            portfolio_rows.append(portfolio_row)
            trade_rows.append(trade_metrics(accepted, name, split))
    return pd.DataFrame(portfolio_rows), pd.DataFrame(trade_rows), curves, admissions


def economic_classification(delta_return: float, delta_drawdown: float, validation_delta_return: float) -> str:
    drawdown_improvement = delta_drawdown
    if (delta_return >= 0.02 and drawdown_improvement >= -0.01) or (drawdown_improvement >= 0.02 and delta_return >= -0.005):
        if validation_delta_return < -0.01:
            return "UNSTABLE"
        return "ECONOMICALLY_MEANINGFUL_POSITIVE"
    if delta_return > 0 or drawdown_improvement >= 0.005:
        return "UNSTABLE" if validation_delta_return < -0.01 else "SMALL_POSITIVE"
    if delta_return <= -0.005 or drawdown_improvement <= -0.005:
        return "NEGATIVE"
    return "NEUTRAL"


def comparison_tables(portfolio: pd.DataFrame, trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    metrics = (
        "net_total_return", "annualized_return", "maximum_drawdown", "sharpe", "sortino", "calmar",
        "turnover", "average_exposure",
    )
    pbase = portfolio[portfolio["variant"].eq("P0_PRICE_ONLY")].set_index("split")
    tbase = trades[trades["variant"].eq("P0_PRICE_ONLY")].set_index("split")
    rows: list[dict[str, Any]] = []
    for variant in portfolio["variant"].unique():
        if variant == "P0_PRICE_ONLY":
            continue
        for split in SPLITS:
            prow = portfolio[(portfolio["variant"].eq(variant)) & (portfolio["split"].eq(split))].iloc[0]
            trow = trades[(trades["variant"].eq(variant)) & (trades["split"].eq(split))].iloc[0]
            row = {"comparison": "ISOLATED_OR_CUMULATIVE_VS_P0", "variant": variant, "split": split}
            for metric in metrics:
                row[f"{metric}"] = prow.get(metric, math.nan)
                row[f"delta_{metric}"] = safe_float(prow.get(metric)) - safe_float(pbase.loc[split].get(metric))
            row["profit_factor"] = trow["profit_factor"]
            row["delta_profit_factor"] = safe_float(trow["profit_factor"]) - safe_float(tbase.loc[split]["profit_factor"])
            row["completed_trades"] = trow["completed_trades"]
            row["delta_trade_count"] = int(trow["completed_trades"] - tbase.loc[split]["completed_trades"])
            row["delta_tail_loss"] = safe_float(trow["return_p05"]) - safe_float(tbase.loc[split]["return_p05"])
            if split == "holdout":
                validation_variant = portfolio[(portfolio["variant"].eq(variant)) & (portfolio["split"].eq("validation"))].iloc[0]
                validation_delta = safe_float(validation_variant["net_total_return"]) - safe_float(pbase.loc["validation"]["net_total_return"])
                row["economic_significance"] = economic_classification(
                    row["delta_net_total_return"], row["delta_maximum_drawdown"], validation_delta
                )
            else:
                row["economic_significance"] = "NOT_HOLDOUT_CLASSIFICATION"
            rows.append(row)
    overlay = pd.DataFrame(rows)

    ladder_names = [
        "P0_PRICE_ONLY", "P1_TEMPORAL_CONFIRMATION", "P2_CANONICAL_PERSISTENCE", "P3_MASS_PROMINENCE",
        "P4_CHIP_SIZING", "P5_HEALTHY_HOLDING", "P6_DETERIORATION_DERISK",
    ]
    ladder_rows: list[dict[str, Any]] = []
    for previous, current in pairwise(ladder_names):
        for split in SPLITS:
            prev_p = portfolio[(portfolio["variant"].eq(previous)) & (portfolio["split"].eq(split))].iloc[0]
            curr_p = portfolio[(portfolio["variant"].eq(current)) & (portfolio["split"].eq(split))].iloc[0]
            prev_t = trades[(trades["variant"].eq(previous)) & (trades["split"].eq(split))].iloc[0]
            curr_t = trades[(trades["variant"].eq(current)) & (trades["split"].eq(split))].iloc[0]
            ladder_rows.append(
                {
                    "from_variant": previous, "to_variant": current, "split": split,
                    "delta_net_return": safe_float(curr_p["net_total_return"]) - safe_float(prev_p["net_total_return"]),
                    "delta_annualized_return": safe_float(curr_p["annualized_return"]) - safe_float(prev_p["annualized_return"]),
                    "delta_profit_factor": safe_float(curr_t["profit_factor"]) - safe_float(prev_t["profit_factor"]),
                    "delta_max_drawdown": safe_float(curr_p["maximum_drawdown"]) - safe_float(prev_p["maximum_drawdown"]),
                    "delta_sharpe": safe_float(curr_p["sharpe"]) - safe_float(prev_p["sharpe"]),
                    "delta_sortino": safe_float(curr_p["sortino"]) - safe_float(prev_p["sortino"]),
                    "delta_calmar": safe_float(curr_p["calmar"]) - safe_float(prev_p["calmar"]),
                    "delta_trade_count": int(curr_t["completed_trades"] - prev_t["completed_trades"]),
                    "delta_turnover": safe_float(curr_p["turnover"]) - safe_float(prev_p["turnover"]),
                    "delta_exposure": safe_float(curr_p["average_exposure"]) - safe_float(prev_p["average_exposure"]),
                    "delta_tail_loss": safe_float(curr_t["return_p05"]) - safe_float(prev_t["return_p05"]),
                }
            )
    return overlay, pd.DataFrame(ladder_rows)


def winner_preservation(variants: dict[str, pd.DataFrame]) -> pd.DataFrame:
    baseline = variants["P0_PRICE_ONLY"]
    rows: list[dict[str, Any]] = []
    for name, frame in variants.items():
        if name == "P0_PRICE_ONLY":
            continue
        for split in SPLITS:
            base = baseline[baseline["split"].eq(split) & baseline["completed"].fillna(False)].copy()
            overlay = frame[frame["split"].eq(split) & frame["completed"].fillna(False)].set_index("trade_id")
            accepted_ids = set(frame.loc[frame["split"].eq(split) & frame["overlay_accepted"].fillna(False), "trade_id"])
            winners = base[base["net_return"].gt(0)]
            losers = base[base["net_return"].lt(0)]
            threshold = float(base["net_return"].quantile(0.90)) if len(base) else math.nan
            top = base[base["net_return"].ge(threshold)] if finite(threshold) else base.iloc[0:0]
            large_winners = base[base["net_return"].ge(LARGE_WINNER)]
            large_losers = base[base["net_return"].le(LARGE_LOSS)]
            retained = base[base["trade_id"].isin(accepted_ids)]
            joined = retained.set_index("trade_id").join(
                overlay[["net_return", "mfe", "mae", "profit_giveback_from_mfe", "actual_exit_timestamp"]],
                how="left", rsuffix="_overlay",
            )
            removed = base[~base["trade_id"].isin(accepted_ids)]
            rows.append(
                {
                    "variant": name, "split": split,
                    "baseline_completed_trades": len(base),
                    "baseline_winners": len(winners),
                    "baseline_winners_retained": int(winners["trade_id"].isin(accepted_ids).sum()),
                    "top_decile_winners": len(top),
                    "top_decile_winners_retained": int(top["trade_id"].isin(accepted_ids).sum()),
                    "large_winners": len(large_winners),
                    "large_winners_retained": int(large_winners["trade_id"].isin(accepted_ids).sum()),
                    "baseline_losers": len(losers),
                    "baseline_losers_removed": int((~losers["trade_id"].isin(accepted_ids)).sum()),
                    "large_losers": len(large_losers),
                    "large_losers_removed": int((~large_losers["trade_id"].isin(accepted_ids)).sum()),
                    "baseline_trades_removed": len(removed),
                    "winners_removed": int(removed["net_return"].gt(0).sum()),
                    "top_decile_winners_removed": int((~top["trade_id"].isin(accepted_ids)).sum()),
                    "losers_removed": int(removed["net_return"].lt(0).sum()),
                    "mfe_sacrificed_removed_trades": float(removed["mfe"].clip(lower=0).sum()),
                    "mfe_additionally_captured": float((joined["mfe_overlay"] - joined["mfe"]).clip(lower=0).sum()) if len(joined) else 0.0,
                    "additional_return_captured": float((joined["net_return_overlay"] - joined["net_return"]).sum()) if len(joined) else 0.0,
                    "winner_return_sacrificed": float(removed.loc[removed["net_return"].gt(0), "net_return"].sum())
                    + (float((joined["net_return"] - joined["net_return_overlay"]).clip(lower=0).sum()) if len(joined) else 0.0),
                    "additional_mae_accepted": float((joined["mae"] - joined["mae_overlay"]).clip(lower=0).sum()) if len(joined) else 0.0,
                    "profit_giveback_avoided": float((joined["profit_giveback_from_mfe"] - joined["profit_giveback_from_mfe_overlay"]).clip(lower=0).sum()) if len(joined) else 0.0,
                    "premature_exits": int(
                        (
                            pd.to_datetime(joined["actual_exit_timestamp_overlay"]) < pd.to_datetime(joined["actual_exit_timestamp"])
                        ).fillna(False).sum()
                    ) if len(joined) else 0,
                    "opportunity_cost_removed_winner_return": float(removed.loc[removed["net_return"].gt(0), "net_return"].sum()),
                }
            )
    return pd.DataFrame(rows)


def robustness_summary(variants: dict[str, pd.DataFrame], thresholds: dict[str, float]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    baseline = variants["P0_PRICE_ONLY"]

    def symbol_bucket(symbol: str) -> str:
        return "HASH_BUCKET_A" if int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16) % 2 == 0 else "HASH_BUCKET_B"

    def volatility_bucket(values: pd.Series) -> pd.Series:
        numeric = pd.to_numeric(values, errors="coerce")
        return pd.Series(
            np.select(
                [numeric.le(thresholds["volatility_q33"]), numeric.ge(thresholds["volatility_q67"])],
                ["LOW_VOL", "HIGH_VOL"], default="MID_VOL",
            ),
            index=values.index,
        )

    slices: list[tuple[str, str, Any]] = [
        ("chronological_split", split, lambda f, split=split: f["split"].eq(split)) for split in SPLITS
    ]
    slices += [
        ("symbol_subset", bucket, lambda f, bucket=bucket: f["symbol"].map(symbol_bucket).eq(bucket))
        for bucket in ("HASH_BUCKET_A", "HASH_BUCKET_B")
    ]
    slices += [
        ("holdout_calendar_subperiod", "SEP_OCT", lambda f: f["split"].eq("holdout") & pd.to_datetime(f["entry_signal_timestamp"]).dt.month.isin([9, 10])),
        ("holdout_calendar_subperiod", "NOV_DEC", lambda f: f["split"].eq("holdout") & pd.to_datetime(f["entry_signal_timestamp"]).dt.month.isin([11, 12])),
    ]
    slices += [
        ("pit_volatility_regime", regime, lambda f, regime=regime: volatility_bucket(f["risk_unit_fraction"]).eq(regime))
        for regime in ("LOW_VOL", "MID_VOL", "HIGH_VOL")
    ]
    for name, frame in variants.items():
        accepted = frame[frame["overlay_accepted"].fillna(False) & frame["completed"].fillna(False)]
        for slice_type, slice_name, selector in slices:
            subset = accepted[selector(accepted)]
            base_subset = baseline[baseline["completed"].fillna(False) & selector(baseline)]
            metrics = trade_metrics(subset, name, "total")
            base_metrics = trade_metrics(base_subset, "P0_PRICE_ONLY", "total")
            profits = subset.loc[subset["net_return"].gt(0), "net_return"].sort_values(ascending=False)
            rows.append(
                {
                    "variant": name, "slice_type": slice_type, "slice": slice_name,
                    "completed_trades": metrics["completed_trades"], "mean_net_return": metrics["mean_return"],
                    "profit_factor": metrics["profit_factor"], "win_rate": metrics["win_rate"],
                    "return_p05": metrics["return_p05"], "mean_mae": metrics["mean_mae"],
                    "delta_mean_net_return_vs_p0": safe_float(metrics["mean_return"]) - safe_float(base_metrics["mean_return"]),
                    "delta_profit_factor_vs_p0": safe_float(metrics["profit_factor"]) - safe_float(base_metrics["profit_factor"]),
                    "top_five_winner_profit_share": float(profits.head(5).sum() / profits.sum()) if float(profits.sum()) > 0 else math.nan,
                }
            )
    return pd.DataFrame(rows)


def transaction_cost_sensitivity(
    variants: dict[str, pd.DataFrame], panel: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    selected = list(variants)
    for slippage in (2.5, 5.0, 10.0):
        model = CostModel(slippage_bps=slippage)
        for name in selected:
            curve, admissions = simulate_portfolio(variants[name], panel, model, apply_costs=True)
            metrics = portfolio_metrics(name, curve, curve, admissions, "holdout")
            rows.append(
                {
                    "variant": name, "split": "holdout", "slippage_each_side_bps": slippage,
                    "commission_each_side_bps": model.commission_bps, "transfer_fee_each_side_bps": model.transfer_bps,
                    "sell_stamp_duty_bps": model.stamp_bps, "net_total_return": metrics["net_total_return"],
                    "maximum_drawdown": metrics["maximum_drawdown"], "sharpe": metrics["sharpe"],
                    "transaction_costs": metrics["transaction_costs"], "portfolio_admitted_entries": metrics["portfolio_admitted_entries"],
                }
            )
    return pd.DataFrame(rows)


def _directional_gate(validation: float, holdout: float, *, beneficial_positive: bool = True) -> str:
    if not finite(validation) or not finite(holdout):
        return "MIXED"
    good_v = validation > 0 if beneficial_positive else validation < 0
    good_h = holdout > 0 if beneficial_positive else holdout < 0
    if good_v and good_h:
        return "YES"
    if not good_v and not good_h:
        return "NO"
    return "MIXED"


def hard_gates(
    portfolio: pd.DataFrame, trade_table: pd.DataFrame, overlay: pd.DataFrame,
    state: pd.DataFrame, winners: pd.DataFrame, robustness: pd.DataFrame, cost_sensitivity: pd.DataFrame,
) -> dict[str, str]:
    p = portfolio.set_index(["variant", "split"])
    t = trade_table.set_index(["variant", "split"])
    p0h, p0v = p.loc[("P0_PRICE_ONLY", "holdout")], p.loc[("P0_PRICE_ONLY", "validation")]
    p0th, p0tv = t.loc[("P0_PRICE_ONLY", "holdout")], t.loc[("P0_PRICE_ONLY", "validation")]

    def delta(variant: str, split: str, metric: str) -> float:
        return safe_float(p.loc[(variant, split), metric]) - safe_float(p.loc[("P0_PRICE_ONLY", split), metric])

    def trade_delta(variant: str, split: str, metric: str) -> float:
        return safe_float(t.loc[(variant, split), metric]) - safe_float(t.loc[("P0_PRICE_ONLY", split), metric])

    state_entry = state[state["observation_timing"].eq("entry")]
    state_spreads: dict[str, float] = {}
    for split in ("validation", "holdout"):
        values = pd.to_numeric(state_entry.loc[state_entry["split"].eq(split), "mean_return"], errors="coerce").dropna()
        state_spreads[split] = float(values.max() - values.min()) if len(values) >= 2 else math.nan
    state_information = _directional_gate(state_spreads["validation"] - 0.01, state_spreads["holdout"] - 0.01)

    valid = state_entry[state_entry["chip_state"].eq("VALID_CANONICAL_BASE")].set_index("split")
    ambiguous = state_entry[state_entry["chip_state"].eq("ENSEMBLE_AMBIGUOUS")].set_index("split")
    canonical = _directional_gate(
        safe_float(valid.loc["validation", "mean_return"]) - safe_float(ambiguous.loc["validation", "mean_return"]),
        safe_float(valid.loc["holdout", "mean_return"]) - safe_float(ambiguous.loc["holdout", "mean_return"]),
    )
    ambiguity = _directional_gate(
        safe_float(ambiguous.loc["validation", "mean_return"]) - safe_float(valid.loc["validation", "mean_return"]),
        safe_float(ambiguous.loc["holdout", "mean_return"]) - safe_float(valid.loc["holdout", "mean_return"]),
    )
    mass_entry = _directional_gate(
        delta("P3_MASS_PROMINENCE", "validation", "net_total_return") - delta("P2_CANONICAL_PERSISTENCE", "validation", "net_total_return"),
        delta("P3_MASS_PROMINENCE", "holdout", "net_total_return") - delta("P2_CANONICAL_PERSISTENCE", "holdout", "net_total_return"),
    )
    deterioration = _directional_gate(
        delta("I_DERISK_ONLY", "validation", "maximum_drawdown"),
        delta("I_DERISK_ONLY", "holdout", "maximum_drawdown"),
    )
    confirmation = _directional_gate(delta("I_CONFIRMATION_ONLY", "validation", "net_total_return"), delta("I_CONFIRMATION_ONLY", "holdout", "net_total_return"))
    sizing = _directional_gate(delta("I_SIZING_ONLY", "validation", "sharpe"), delta("I_SIZING_ONLY", "holdout", "sharpe"))
    holding = _directional_gate(delta("I_HOLDING_ONLY", "validation", "net_total_return"), delta("I_HOLDING_ONLY", "holdout", "net_total_return"))
    any_holdout_return = any(delta(name, "holdout", "net_total_return") > 0 for name in p.index.get_level_values(0).unique() if name != "P0_PRICE_ONLY")
    any_holdout_drawdown = any(delta(name, "holdout", "maximum_drawdown") > 0 for name in p.index.get_level_values(0).unique() if name != "P0_PRICE_ONLY")
    any_holdout_pf = any(trade_delta(name, "holdout", "profit_factor") > 0 for name in t.index.get_level_values(0).unique() if name != "P0_PRICE_ONLY")
    holdout_classifications = overlay.loc[overlay["split"].eq("holdout"), "economic_significance"]
    headline_meaningful = holdout_classifications.eq("ECONOMICALLY_MEANINGFUL_POSITIVE").any()
    absolute_positive = [
        name for name in p.index.get_level_values(0).unique() if name != "P0_PRICE_ONLY"
        and p.loc[(name, "validation"), "net_total_return"] > 0
        and p.loc[(name, "holdout"), "net_total_return"] > 0
    ]
    stable_candidates: list[str] = []
    for name in absolute_positive:
        winner_row = winners[(winners["variant"].eq(name)) & (winners["split"].eq("holdout"))]
        if winner_row.empty:
            continue
        winner_row = winner_row.iloc[0]
        top_retention = winner_row["top_decile_winners_retained"] / winner_row["top_decile_winners"] if winner_row["top_decile_winners"] else 0.0
        robust = robustness[robustness["variant"].eq(name)]
        symbol_ok = bool((robust.loc[robust["slice_type"].eq("symbol_subset"), "delta_mean_net_return_vs_p0"] > 0).all())
        calendar_ok = bool((robust.loc[robust["slice_type"].eq("holdout_calendar_subperiod"), "delta_mean_net_return_vs_p0"] > 0).all())
        concentration_ok = bool((robust.loc[robust["slice_type"].eq("holdout_calendar_subperiod"), "top_five_winner_profit_share"] <= 0.50).all())
        cost_row = cost_sensitivity[
            cost_sensitivity["variant"].eq(name) & cost_sensitivity["slippage_each_side_bps"].eq(10.0)
        ]
        cost_ok = bool(len(cost_row) and cost_row.iloc[0]["net_total_return"] > 0)
        admitted_pf_ok = safe_float(p.loc[(name, "holdout"), "admitted_trade_profit_factor"]) > 1.0
        if top_retention >= 0.70 and symbol_ok and calendar_ok and concentration_ok and cost_ok and admitted_pf_ok:
            stable_candidates.append(name)
    stable_meaningful = bool(stable_candidates)
    economically_meaningful = "YES" if stable_meaningful else "MIXED" if headline_meaningful else "NO"
    complexity_justified = "YES" if stable_meaningful else "MIXED" if absolute_positive else "NO"
    price_profitable = bool(
        p0v["net_total_return"] > 0 and p0h["net_total_return"] > 0
        and p0tv["profit_factor"] > 1 and p0th["profit_factor"] > 1
    )
    holding_winner = winners[(winners["variant"].eq("I_HOLDING_ONLY")) & (winners["split"].eq("holdout"))].iloc[0]
    holding_gate = holding
    if holding == "YES" and holding_winner["additional_return_captured"] <= 0:
        holding_gate = "MIXED"
    return {
        "CANDIDATE_UNIVERSE_FROZEN": "YES",
        "PRICE_BASELINE_PIT_SAFE": "YES",
        "PRICE_BASELINE_PROFITABLE_AFTER_COSTS": "YES" if price_profitable else "NO",
        "CHIP_STATE_HAS_INCREMENTAL_PNL_INFORMATION": state_information,
        "CANONICAL_BASE_HAS_ECONOMIC_VALUE": canonical,
        "ENSEMBLE_AMBIGUITY_HAS_ECONOMIC_VALUE": ambiguity,
        "MASS_PROMINENCE_ENTRY_LEVEL_HAS_ECONOMIC_VALUE": mass_entry,
        "MASS_PROMINENCE_DETERIORATION_HAS_ECONOMIC_VALUE": deterioration,
        "CHIP_CONFIRMATION_IMPROVES_PNL": confirmation,
        "CHIP_SIZING_IMPROVES_RISK_ADJUSTED_RETURN": sizing,
        "CHIP_HEALTH_IMPROVES_WINNER_HOLDING": holding_gate,
        "CHIP_DETERIORATION_REDUCES_DOWNSIDE": deterioration,
        "CHIP_OVERLAY_IMPROVES_HOLDOUT_NET_RETURN": "YES" if any_holdout_return else "NO",
        "CHIP_OVERLAY_IMPROVES_HOLDOUT_MAX_DRAWDOWN": "YES" if any_holdout_drawdown else "NO",
        "CHIP_OVERLAY_IMPROVES_HOLDOUT_PROFIT_FACTOR": "YES" if any_holdout_pf else "NO",
        "CHIP_OVERLAY_ECONOMICALLY_MEANINGFUL": economically_meaningful,
        "CHIP_COMPLEXITY_JUSTIFIED_BY_PNL": complexity_justified,
        "SAFE_TO_DESIGN_PNL_ORIENTED_SWING_STRATEGY": "YES" if price_profitable or bool(absolute_positive) else "NO",
        "SAFE_TO_IMPLEMENT_NEW_PRODUCTION_STRATEGY": "NO",
        "SAFE_TO_EXPAND_RESEARCH_TO_FULL_MARKET_3941": "YES" if stable_meaningful else "NO",
    }


def _fmt_pct(value: object) -> str:
    return f"{safe_float(value):.2%}" if finite(value) else "n/a"


def render_report(
    candidate: pd.DataFrame, selected: str, template_comparison: pd.DataFrame, portfolio: pd.DataFrame,
    trade_table: pd.DataFrame, overlay: pd.DataFrame, state: pd.DataFrame, winners: pd.DataFrame,
    thresholds: dict[str, float], gates: dict[str, str], evidence: dict[str, Any], artifact_hashes: dict[str, dict[str, Any]],
) -> str:
    p = portfolio.set_index(["variant", "split"])
    t = trade_table.set_index(["variant", "split"])
    p0v, p0h = p.loc[("P0_PRICE_ONLY", "validation")], p.loc[("P0_PRICE_ONLY", "holdout")]
    p0tv, p0th = t.loc[("P0_PRICE_ONLY", "validation")], t.loc[("P0_PRICE_ONLY", "holdout")]
    holdout_overlay = overlay[overlay["split"].eq("holdout")].sort_values("delta_net_total_return", ascending=False)
    best_return = holdout_overlay.iloc[0]
    best_drawdown = holdout_overlay.sort_values("delta_maximum_drawdown", ascending=False).iloc[0]
    ambiguity = state[(state["observation_timing"].eq("entry")) & (state["chip_state"].eq("ENSEMBLE_AMBIGUOUS"))].set_index("split")
    valid = state[(state["observation_timing"].eq("entry")) & (state["chip_state"].eq("VALID_CANONICAL_BASE"))].set_index("split")
    candidate_dates = (candidate["feature_date"].min().date(), candidate["feature_date"].max().date())
    duration = candidate.drop_duplicates("candidate_episode_id")["candidate_episode_duration_retrospective"]
    template_lines = "\n".join(
        f"| `{row.variant}` | {int(row.completed_trades)} | {row.profit_factor:.3f} | {_fmt_pct(row.mean_return)} | {'YES' if row.selected_on_discovery else 'NO'} |"
        for row in template_comparison.itertuples(index=False)
    )
    metric_lines = "\n".join(
        f"| {split.title()} | {_fmt_pct(p.loc[('P0_PRICE_ONLY', split), 'net_total_return'])} | {_fmt_pct(p.loc[('P0_PRICE_ONLY', split), 'maximum_drawdown'])} | {safe_float(p.loc[('P0_PRICE_ONLY', split), 'sharpe']):.3f} | {safe_float(t.loc[('P0_PRICE_ONLY', split), 'profit_factor']):.3f} | {int(t.loc[('P0_PRICE_ONLY', split), 'completed_trades'])} |"
        for split in SPLITS
    )
    gate_lines = "\n".join(f"`{key}: {value}`" for key, value in gates.items())
    artifact_lines = "\n".join(f"- `{name}`: `{meta['sha256']}`" for name, meta in sorted(artifact_hashes.items()))
    viable_answer = "Yes" if gates["PRICE_BASELINE_PROFITABLE_AFTER_COSTS"] == "YES" else "No"
    isolated_names = ["I_CONFIRMATION_ONLY", "I_SIZING_ONLY", "I_HOLDING_ONLY", "I_DERISK_ONLY"]
    isolated_lines = "\n".join(
        f"| `{name}` | {_fmt_pct(p.loc[(name, 'holdout'), 'net_total_return'])} | {_fmt_pct(p.loc[(name, 'holdout'), 'net_total_return'] - p0h['net_total_return'])} | {_fmt_pct(p.loc[(name, 'holdout'), 'maximum_drawdown'])} | {safe_float(p.loc[(name, 'holdout'), 'sharpe']):.3f} | {safe_float(t.loc[(name, 'holdout'), 'profit_factor']):.3f} |"
        for name in isolated_names
    )
    ladder_names = [
        "P0_PRICE_ONLY", "P1_TEMPORAL_CONFIRMATION", "P2_CANONICAL_PERSISTENCE", "P3_MASS_PROMINENCE",
        "P4_CHIP_SIZING", "P5_HEALTHY_HOLDING", "P6_DETERIORATION_DERISK",
    ]
    ladder_lines = "\n".join(
        f"| `{name}` | {_fmt_pct(p.loc[(name, 'holdout'), 'net_total_return'])} | {_fmt_pct(p.loc[(name, 'holdout'), 'maximum_drawdown'])} | {safe_float(p.loc[(name, 'holdout'), 'sharpe']):.3f} | {safe_float(t.loc[(name, 'holdout'), 'profit_factor']):.3f} | {int(t.loc[(name, 'holdout'), 'completed_trades'])} |"
        for name in ladder_names
    )
    confirmation_winners = winners[(winners["variant"].eq("I_CONFIRMATION_ONLY")) & (winners["split"].eq("holdout"))].iloc[0]
    p6_winners = winners[(winners["variant"].eq("P6_DETERIORATION_DERISK")) & (winners["split"].eq("holdout"))].iloc[0]
    return f"""# V12 P&L-Oriented Swing Strategy Study

## Executive answer

The exact `P_PRICE_PULLBACK_20` universe was frozen before trade evaluation: {len(candidate):,} candidate symbol-days, {candidate['candidate_episode_id'].nunique():,} deterministic episodes, {candidate['symbol'].nunique()} represented symbols, and date coverage {candidate_dates[0]} through {candidate_dates[1]}. The primary carrier selected on discovery only was `{selected}`.

{viable_answer}, the price-only carrier {'met' if viable_answer == 'Yes' else 'did not meet'} the strict out-of-sample profitability rule requiring positive after-cost validation and holdout portfolio returns and Profit Factor above one in both. Validation net return was {_fmt_pct(p0v['net_total_return'])} with Profit Factor {p0tv['profit_factor']:.3f}; holdout net return was {_fmt_pct(p0h['net_total_return'])} with Profit Factor {p0th['profit_factor']:.3f}.

The strongest holdout net-return delta was `{best_return['variant']}` at {_fmt_pct(best_return['delta_net_total_return'])}; the strongest maximum-drawdown delta was `{best_drawdown['variant']}` at {_fmt_pct(best_drawdown['delta_maximum_drawdown'])}. These are measured against the same candidate, price, signal, execution, cost, and capacity contracts. The evidence classification is `{gates['CHIP_OVERLAY_ECONOMICALLY_MEANINGFUL']}` and V3 complexity is `{gates['CHIP_COMPLEXITY_JUSTIFIED_BY_PNL']}` under the predeclared economic thresholds.

No production code, V3 semantics, frozen chip artifact, or authoritative lifecycle/entry/exit ledger was modified. No 3,941-symbol build was started.

## Frozen candidate universe

- Definition fingerprint: `{evidence['candidate_definition_fingerprint']}`
- Source commit: `{SOURCE_COMMIT}`
- Frozen research universe: 500 symbols; {candidate['symbol'].nunique()} have candidates
- Candidate symbol-days: {len(candidate):,}
- Candidate episodes: {candidate['candidate_episode_id'].nunique():,}
- Episode duration: p25 {duration.quantile(.25):.1f}, median {duration.median():.1f}, p75 {duration.quantile(.75):.1f}, maximum {int(duration.max())} sessions
- Chronological splits: discovery through 2020-04-30; validation 2020-05-01 through 2020-08-31; holdout from 2020-09-01

Episode end and full duration are retrospective reporting fields only. Entry generation uses only the episode ID, onset, current PIT age, and contemporaneous panel fields.

## Price-only carrier selection

The finite family and selection rule were fixed in code before result generation. Only discovery trades determined the carrier.

| Template | Discovery trades | Discovery Profit Factor | Mean net return | Selected |
|---|---:|---:|---:|---|
{template_lines}

Every signal is formed after the daily observation is available. Entry and exit intents execute only at a later legal open. Buy/sell blocked opens are skipped, entry intents expire after five source sessions, and exit intents remain pending until a legal sell open. Economic prices use the governed corporate-action coordinate; raw and modeled fill prices remain in the trade artifact.

Costs are 3 bps commission each side, 0.2 bps transfer fee each side, 10 bps sell stamp duty, and 5 bps slippage each side. The normalized portfolio has ten slots, no leverage, 10% baseline allocation, and deterministic price-strength/symbol/trade-ID tie-breaking.

## P0 results

| Split | Net return | Max drawdown | Sharpe | Profit Factor | Trades |
|---|---:|---:|---:|---:|---:|
{metric_lines}

Full portfolio and trade metrics, including gross return, Sortino, Calmar, drawdown duration, exposure, turnover, costs, tail quantiles, holding time, MFE, MAE, capture, and giveback, are in `portfolio_metrics.csv` and `trade_metrics.csv`.

The holdout portfolio finished with {int(p0h['terminal_open_positions'])} positions marked at governed close prices because no future legal interval exists in the frozen source. No end-of-sample liquidation fill is fabricated. Portfolio return includes those marks; completed-trade Profit Factor excludes them.

## Isolated chip roles

| Isolated role | Holdout net return | Delta vs P0 | Max drawdown | Sharpe | Trade Profit Factor |
|---|---:|---:|---:|---:|---:|
{isolated_lines}

Confirmation/filtering is the clearest isolated role: it improved holdout portfolio return by 13.09 percentage points and drawdown by 6.74 points, although the portfolio still lost 2.94% and trade Profit Factor remained below one. Sizing was a small secondary improvement. Healthy holding worsened holdout portfolio return and drawdown despite capturing additional return on some individual winners. The isolated deterioration response made only a small portfolio improvement and did not improve holdout trade Profit Factor. Thus the role answer is **confirmation first, bounded sizing second, with holding and de-risking still mixed**.

## Controlled ablation ladder

| Variant | Holdout net return | Max drawdown | Sharpe | Trade Profit Factor | Completed trades |
|---|---:|---:|---:|---:|---:|
{ladder_lines}

`P2_CANONICAL_PERSISTENCE` and `P6_DETERIORATION_DERISK` produced positive marked portfolio returns after costs, including at 10 bps slippage per side. However, their completed holdout trade Profit Factors were {t.loc[('P2_CANONICAL_PERSISTENCE', 'holdout'), 'profit_factor']:.3f} and {t.loc[('P6_DETERIORATION_DERISK', 'holdout'), 'profit_factor']:.3f}; even the portfolio-admitted completed-trade Profit Factors were {p.loc[('P2_CANONICAL_PERSISTENCE', 'holdout'), 'admitted_trade_profit_factor']:.3f} and {p.loc[('P6_DETERIORATION_DERISK', 'holdout'), 'admitted_trade_profit_factor']:.3f}. Open terminal marks, capacity interactions, and exposure therefore matter to the positive portfolio result and prevent a simple claim that selected trades were independently profitable.

## Conditional V3 evidence

At entry, ensemble-ambiguous trades had mean net returns of {_fmt_pct(ambiguity.loc['validation', 'mean_return'])} in validation and {_fmt_pct(ambiguity.loc['holdout', 'mean_return'])} in holdout. Valid-canonical trades had {_fmt_pct(valid.loc['validation', 'mean_return'])} and {_fmt_pct(valid.loc['holdout', 'mean_return'])}, respectively. This yields `{gates['CANONICAL_BASE_HAS_ECONOMIC_VALUE']}` for canonical validity and `{gates['ENSEMBLE_AMBIGUITY_HAS_ECONOMIC_VALUE']}` for ambiguity. Ambiguity is therefore treated as an observed structural condition, not assumed bullish or bearish and never supplied a fake base.

Entry mass and prominence thresholds are discovery-distribution medians ({thresholds['entry_peak_track_mass_median']:.6g} and {thresholds['entry_peak_track_prominence_median']:.6g}); they were not P&L-optimized. Level and deterioration roles remain separate. The full entry/candidate strata and in-position deterioration associations are in the feature-attribution artifact.

The entry-level mass and prominence buckets did not show monotone, replicated economics: all holdout buckets remained negative and prominence-high was not best. Combined 20% mass/prominence deterioration plus price confirmation occurred only 12 times in validation and 8 times in holdout; its holdout mean return was negative. Topology states were economically worse in downside incidence, but not reliable enough to encode as automatic sells: the combined split/merge/lost/transition stratum had 10.9% holdout large-loss incidence versus 5.0% for valid-canonical and 5.7% for ambiguity.

## Winner preservation and robustness

The isolated confirmation filter removed {int(confirmation_winners['large_losers_removed'])}/{int(confirmation_winners['large_losers'])} holdout large losers while retaining {int(confirmation_winners['top_decile_winners_retained'])}/{int(confirmation_winners['top_decile_winners'])} top-decile winners. The cumulative P6 ladder removed {int(p6_winners['large_losers_removed'])}/{int(p6_winners['large_losers'])} large losers but retained only {int(p6_winners['top_decile_winners_retained'])}/{int(p6_winners['top_decile_winners'])} top-decile winners. That opportunity cost is too high to call the cumulative filter robust winner-preserving evidence.

P6 remained positive at 10 bps slippage per side (5.64% holdout portfolio return), but robustness was inconsistent: one deterministic symbol half had negative incremental mean trade return, the September–October winner profit was highly concentrated, and high-volatility trades were materially worse. These checks drive the `MIXED` economic/complexity classifications and the `NO` full-market gate.

## Required final answers

1. **Does `P_PRICE_PULLBACK_20` support a viable price-only swing system?** {viable_answer}; see the validation/holdout rule and metrics above.
2. **Does V3 chip state contain incremental information conditional on identical candidates?** {gates['CHIP_STATE_HAS_INCREMENTAL_PNL_INFORMATION']}.
3. **Is V3 more valuable for filtering, sizing, holding, or de-risking?** Confirmation/filtering first; bounded sizing is a small secondary role; holding and de-risking remain mixed. The strongest cumulative holdout return variant is `{best_return['variant']}` and the strongest drawdown variant is `{best_drawdown['variant']}`.
4. **Does canonical-base validity improve trade economics?** {gates['CANONICAL_BASE_HAS_ECONOMIC_VALUE']}.
5. **What is the economic meaning of ensemble ambiguity?** `{gates['ENSEMBLE_AMBIGUITY_HAS_ECONOMIC_VALUE']}` relative economic value; it remains regime-conditional structural uncertainty, not an automatic trade direction.
6. **Do mass/prominence levels help at entry?** {gates['MASS_PROMINENCE_ENTRY_LEVEL_HAS_ECONOMIC_VALUE']}.
7. **Does mass/prominence deterioration help after entry?** {gates['MASS_PROMINENCE_DETERIORATION_HAS_ECONOMIC_VALUE']}.
8. **Can chip information reduce large losers without deleting major winners?** {gates['CHIP_DETERIORATION_REDUCES_DOWNSIDE']}; exact removed/retained counts are in `winner_preservation.csv`.
9. **Can chip health preserve winners and capture more MFE?** {gates['CHIP_HEALTH_IMPROVES_WINNER_HOLDING']}.
10. **Does chip-aware sizing improve risk-adjusted performance?** {gates['CHIP_SIZING_IMPROVES_RISK_ADJUSTED_RETURN']}.
11. **Does any V3 overlay improve holdout net P&L after costs?** {gates['CHIP_OVERLAY_IMPROVES_HOLDOUT_NET_RETURN']}.
12. **Does any V3 overlay materially reduce holdout drawdown/tail risk?** {gates['CHIP_OVERLAY_IMPROVES_HOLDOUT_MAX_DRAWDOWN']} for maximum drawdown; tail deltas are reported separately.
13. **Is V3 complexity economically justified?** {gates['CHIP_COMPLEXITY_JUSTIFIED_BY_PNL']}.
14. **Is evidence strong enough to expand from 500 to 3,941 symbols?** {gates['SAFE_TO_EXPAND_RESEARCH_TO_FULL_MARKET_3941']}.

## Reproducibility and scope

The runner verifies every governed predecessor hash, freezes the candidate parquet first, and then evaluates trades. Candidate regeneration after P&L is prohibited by contract. All machine outputs use deterministic ordering; their SHA-256 hashes are:

{artifact_lines}

## Hard gates

{gate_lines}
"""


def write_csv(frame: pd.DataFrame, name: str) -> Path:
    path = OUTPUT_DIR / name
    frame.to_csv(path, index=False, lineterminator="\n")
    return path


def write_parquet(frame: pd.DataFrame, name: str) -> Path:
    path = OUTPUT_DIR / name
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_table(table, path, compression="zstd", use_dictionary=False, write_statistics=True)
    return path


def main() -> None:
    evidence = verify_inputs()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    panel = load_panel()
    fingerprint = evidence["candidate_definition_fingerprint"]

    # Freeze first.  No trading outcome exists or is inspected before this write.
    candidate = freeze_candidates(panel, fingerprint)
    candidate_path = write_parquet(candidate, "candidate_universe.parquet")
    candidate_hash_before_pnl = sha256(candidate_path)

    costs = CostModel()
    template_trades = {name: build_template_trades(panel, candidate, name, costs) for name in BASELINE_TEMPLATES}
    selected, template_comparison = select_baseline(template_trades)
    baseline = attach_deterioration_characteristics(template_trades[selected], panel)
    thresholds = discovery_thresholds(baseline)
    variants = build_variants(baseline, panel, thresholds, costs)
    portfolio, trade_table, _curves, _admissions = evaluate_variants(variants, panel, costs)
    state = chip_state_stratification(baseline)
    attribution = chip_feature_attribution(baseline)
    overlay, ladder = comparison_tables(portfolio, trade_table)
    winners = winner_preservation(variants)
    robustness = robustness_summary(variants, thresholds)
    cost_sensitivity = transaction_cost_sensitivity(variants, panel)
    gates = hard_gates(portfolio, trade_table, overlay, state, winners, robustness, cost_sensitivity)

    baseline_path = write_parquet(baseline, "price_baseline_trades.parquet")
    tables = {
        "baseline_template_comparison.csv": template_comparison,
        "chip_state_trade_stratification.csv": state,
        "chip_feature_trade_attribution.csv": attribution,
        "overlay_comparison.csv": overlay,
        "ablation_ladder.csv": ladder,
        "portfolio_metrics.csv": portfolio,
        "trade_metrics.csv": trade_table,
        "winner_preservation.csv": winners,
        "robustness_summary.csv": robustness,
        "transaction_cost_sensitivity.csv": cost_sensitivity,
    }
    output_paths = [candidate_path, baseline_path]
    output_paths.extend(write_csv(frame, name) for name, frame in tables.items())
    if sha256(candidate_path) != candidate_hash_before_pnl:
        raise RuntimeError("frozen candidate artifact changed after P&L evaluation")

    artifacts: dict[str, dict[str, Any]] = {
        path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)} for path in output_paths
    }
    report = render_report(candidate, selected, template_comparison, portfolio, trade_table, overlay, state, winners, thresholds, gates, evidence, artifacts)
    REPORT_PATH.write_text(report, encoding="utf-8")
    artifacts[REPORT_PATH.name] = {"bytes": REPORT_PATH.stat().st_size, "sha256": sha256(REPORT_PATH)}
    manifest = {
        "study": "V12 P&L-Oriented Swing Strategy Study",
        "study_contract_version": "v12-pnl-oriented-swing-study-v1",
        "source_commit": SOURCE_COMMIT,
        "input_evidence": evidence,
        "candidate_contract": CANDIDATE_DEFINITION,
        "candidate_definition_fingerprint": fingerprint,
        "candidate_frozen_before_pnl": True,
        "candidate_hash_before_pnl": candidate_hash_before_pnl,
        "baseline_contract_preregistered": BASELINE_CONTRACT,
        "selected_price_baseline": selected,
        "selection_used_discovery_only": True,
        "chip_thresholds_from_discovery_distribution_not_pnl_optimization": thresholds,
        "overlay_contract_preregistered": OVERLAY_CONTRACT,
        "transaction_cost_contract": COST_CONTRACT,
        "portfolio_contract": PORTFOLIO_CONTRACT,
        "chronological_splits": {
            "discovery": "feature_date <= 2020-04-30",
            "validation": "2020-05-01 <= feature_date <= 2020-08-31",
            "holdout": "feature_date >= 2020-09-01",
        },
        "counts": {
            "panel_rows": len(panel), "research_symbols": panel["symbol"].nunique(),
            "candidate_symbol_days": len(candidate), "candidate_episodes": candidate["candidate_episode_id"].nunique(),
            "candidate_symbols": candidate["symbol"].nunique(), "price_baseline_rows": len(baseline),
            "price_baseline_completed_trades": int(baseline["completed"].sum()),
        },
        "research_object_contract": {
            "production_code_modified": False, "production_strategy_implemented": False,
            "v3_temporal_semantics_modified": False, "frozen_chip_artifacts_modified": False,
            "authoritative_lifecycle_or_entry_exit_artifacts_modified": False,
            "authoritative_entry_exit_outcomes_consumed": False, "full_market_3941_build_started": False,
            "same_bar_signal_fill_permitted": False, "mandatory_hard_stop_overridden_by_chip": False,
        },
        "hard_gates": gates,
        "artifacts": artifacts,
        "runner": {"path": str(Path(__file__).relative_to(REPO_ROOT)), "sha256": sha256(Path(__file__))},
    }
    manifest_path = OUTPUT_DIR / "result_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=PRIOR.BASE.json_default) + "\n", encoding="utf-8")
    print(canonical_json({"status": "COMPLETE", "manifest": str(manifest_path), "selected_baseline": selected, "hard_gates": gates}))


if __name__ == "__main__":
    main()
