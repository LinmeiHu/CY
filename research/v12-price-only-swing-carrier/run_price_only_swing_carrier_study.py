#!/usr/bin/env python3
# ruff: noqa: E501
"""Research-only price carrier viability study for frozen P_PRICE_PULLBACK_20.

Only the byte-frozen candidate artifact and registered PIT daily price/execution
data are read. No chip/temporal feature artifact is opened by this runner.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


STUDY_DIR = Path(__file__).resolve().parent
REPO_ROOT = STUDY_DIR.parents[1]
OUTPUT_DIR = STUDY_DIR / "results"
REPORT_PATH = STUDY_DIR / "V12_PRICE_ONLY_SWING_CARRIER_VIABILITY_STUDY.md"
SOURCE_CANDIDATES = REPO_ROOT / "research/v12-pnl-oriented-swing-study/results/candidate_universe.parquet"
DAILY_2020 = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=2020/data_0.parquet")

CHIP_ATTRIBUTION_COMMIT = "f41b5bec94912d69ffc889eedd464da44589cdbf"
EXPECTED_CANDIDATE_SHA256 = "3913c3f839c9a5a9f682e47ff256be53a5a8395e371b34df019959692e7dc82a"
EXPECTED_DAILY_SHA256 = "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62"
EXPECTED_CANDIDATE_ROWS = 47_518
EXPECTED_EPISODES = 5_671
EXPECTED_CANDIDATE_SYMBOLS = 494
SPLITS = ("discovery", "validation", "holdout")
SPLIT_BOUNDS = {
    "discovery": (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-04-30")),
    "validation": (pd.Timestamp("2020-05-01"), pd.Timestamp("2020-08-31")),
    "holdout": (pd.Timestamp("2020-09-01"), pd.Timestamp("2020-12-31")),
}

CARRIER_DEFINITIONS = {
    "A_PULLBACK_RECLAIM": {
        "economic_idea": "Recover the short moving reference after a pullback.",
        "entry_signal": "Within five source sessions of episode start, close crosses from at/below MA5 to above MA5 and closes above preclose.",
    },
    "B_LOCAL_BREAKOUT": {
        "economic_idea": "Require local price expansion before accepting the pullback reversal.",
        "entry_signal": "Within five source sessions of episode start, close exceeds the highest high of the prior three source sessions.",
    },
    "C_TREND_RESUMPTION": {
        "economic_idea": "Accept a pullback only when medium trend and renewed short trend agree.",
        "entry_signal": "Within five source sessions of episode start, MA20 exceeds MA60, close exceeds MA5, MA5 rises, and close exceeds preclose.",
    },
}
RISK_CONTRACT = {
    "primary_atr_multiple": 2.0,
    "diagnostic_atr_multiples": [1.5, 2.5],
    "hard_risk": "Close at or below entry analysis open minus ATR multiple times signal-day ATR14; sell at next legal open.",
    "profit_protection": "After same-trade MFE reaches 2R, close below MA5; sell at next legal open.",
    "ordinary_exit": "From holding session three, close below MA10; sell at next legal open.",
    "time_exit": "At holding session 20 close; sell at next legal open.",
    "signal_wait_source_sessions": 5,
    "legal_fill_wait_source_sessions": 3,
    "same_bar_fill": False,
}
PORTFOLIO_CONTRACT = {
    "initial_capital": 1.0,
    "maximum_concurrent_positions": 10,
    "target_fraction": 0.10,
    "allocation": "equal-weight target using equity known before same-open admissions",
    "priority": "descending trigger strength, then candidate_at, symbol, trade_id",
    "same_symbol_overlap": False,
    "leverage": False,
}
SELECTION_CONTRACT = {
    "population": "discovery only; validation and holdout are not built until primary_carrier_freeze.json is written",
    "minimum_completed_discovery_trades": 75,
    "eligibility": "positive main net expectancy, main PF > 1, positive main portfolio return, max drawdown no worse than -25%, positive stressed-cost expectancy, and positive expectancy at both diagnostic ATR multiples",
    "rank": "eligible carrier with highest minimum discovery PF across main, stressed cost, and both ATR diagnostics; then shallower main max drawdown; then carrier_id",
    "fallback": "if none is eligible, apply the same rank among carriers with at least 75 completed discovery trades and freeze the result as a diagnostic primary",
}
VIABILITY_CONTRACT = {
    "holdout_minimum_completed_trades": 100,
    "holdout_net_realized_expectancy": "> 0",
    "holdout_realized_profit_factor": "> 1.0",
    "holdout_net_portfolio_return": "> 0",
    "validation_trade_economics": "net expectancy > 0 and realized PF > 1.0",
    "terminal_mtm_materiality": "material when positive total marked P&L changes sign without terminal unrealized P&L or absolute terminal unrealized exceeds 25% of absolute positive total marked P&L",
    "cost_robustness": "holdout expectancy > 0, PF > 1, and portfolio return > 0 under STRESSED costs",
    "concentration": "YES when net sum remains positive excluding top five trades and top symbol contributes no more than 25% of positive symbol P&L; NO when both fail; otherwise MIXED",
}
COST_SCENARIOS = {
    "ZERO": {"commission_each_side_bps": 0.0, "transfer_each_side_bps": 0.0, "sell_stamp_bps": 0.0, "slippage_each_side_bps": 0.0},
    "BASE": {"commission_each_side_bps": 3.0, "transfer_each_side_bps": 0.2, "sell_stamp_bps": 10.0, "slippage_each_side_bps": 5.0},
    "STRESSED": {"commission_each_side_bps": 5.0, "transfer_each_side_bps": 0.2, "sell_stamp_bps": 10.0, "slippage_each_side_bps": 10.0},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(prefix: str, *parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode()).hexdigest()[:20]}"


def finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def split_for_date(value: object) -> str:
    date = pd.Timestamp(value).normalize()
    if date <= SPLIT_BOUNDS["discovery"][1]:
        return "discovery"
    if date <= SPLIT_BOUNDS["validation"][1]:
        return "validation"
    return "holdout"


def open_at(value: object, minutes_before: int = 0) -> pd.Timestamp:
    return pd.Timestamp(value).normalize() + pd.Timedelta(hours=9, minutes=30 - minutes_before)


@dataclass(frozen=True)
class CostModel:
    commission_each_side_bps: float
    transfer_each_side_bps: float
    sell_stamp_bps: float
    slippage_each_side_bps: float

    @classmethod
    def named(cls, name: str) -> "CostModel":
        return cls(**COST_SCENARIOS[name])

    @property
    def buy_fee(self) -> float:
        return (self.commission_each_side_bps + self.transfer_each_side_bps) / 10_000.0

    @property
    def sell_fee(self) -> float:
        return (self.commission_each_side_bps + self.transfer_each_side_bps + self.sell_stamp_bps) / 10_000.0

    @property
    def slippage(self) -> float:
        return self.slippage_each_side_bps / 10_000.0


def verify_inputs() -> dict[str, Any]:
    checks = {SOURCE_CANDIDATES: EXPECTED_CANDIDATE_SHA256, DAILY_2020: EXPECTED_DAILY_SHA256}
    actual = {str(path): sha256(path) for path in checks}
    for path, expected in checks.items():
        if actual[str(path)] != expected:
            raise RuntimeError(f"governed input changed: {path}: {actual[str(path)]}")
    ancestor = subprocess.run(
        ("git", "merge-base", "--is-ancestor", CHIP_ATTRIBUTION_COMMIT, "HEAD"),
        cwd=REPO_ROOT,
        check=False,
    ).returncode == 0
    if not ancestor:
        raise RuntimeError("study does not descend from completed chip economic attribution commit")
    return {
        "chip_attribution_commit": CHIP_ATTRIBUTION_COMMIT,
        "chip_attribution_commit_is_ancestor": True,
        "frozen_candidate_sha256": actual[str(SOURCE_CANDIDATES)],
        "registered_daily_sha256": actual[str(DAILY_2020)],
        "price_inputs_only": True,
        "chip_feature_artifacts_opened": False,
    }


def load_candidates() -> pd.DataFrame:
    candidate = pq.read_table(SOURCE_CANDIDATES).to_pandas().sort_values(["symbol", "feature_date"]).reset_index(drop=True)
    if len(candidate) != EXPECTED_CANDIDATE_ROWS or candidate["candidate_episode_id"].nunique() != EXPECTED_EPISODES or candidate["symbol"].nunique() != EXPECTED_CANDIDATE_SYMBOLS:
        raise RuntimeError("frozen candidate universe coverage changed")
    if candidate["candidate_definition"].nunique() != 1 or candidate["candidate_definition"].iloc[0] != "P_PRICE_PULLBACK_20":
        raise RuntimeError("unexpected candidate definition")
    candidate["feature_date"] = pd.to_datetime(candidate["feature_date"])
    candidate["feature_available_at"] = pd.to_datetime(candidate["feature_available_at"]).dt.tz_localize(None)
    return candidate


def load_price_panel(candidate: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "symbol", "trade_date", "decision_at", "available_at", "open", "high", "low", "close", "preclose",
        "trade_status", "buy_blocked_open", "sell_blocked_open", "current_day_data_tradable", "corporate_action_count",
        "hard_valid", "snapshot_id", "daily_snapshot_id", "market_close",
    ]
    symbols = sorted(candidate["symbol"].unique())
    panel = pq.read_table(DAILY_2020, columns=columns, filters=[("symbol", "in", symbols)]).to_pandas()
    panel = panel.rename(columns={"trade_date": "feature_date"}).sort_values(["symbol", "feature_date"]).reset_index(drop=True)
    panel["feature_date"] = pd.to_datetime(panel["feature_date"])
    panel["symbol_position"] = panel.groupby("symbol", sort=False).cumcount()
    panel["analysis_factor"] = 1.0
    for _, sf in panel.groupby("symbol", sort=False):
        idx = sf.index
        prior_raw_close = sf["close"].shift(1)
        ratio = pd.Series(1.0, index=idx)
        reset = sf["corporate_action_count"].fillna(0).gt(0) & prior_raw_close.gt(0) & sf["preclose"].gt(0)
        ratio.loc[reset.index[reset]] = (sf.loc[reset, "preclose"] / prior_raw_close.loc[reset]).to_numpy()
        panel.loc[idx, "analysis_factor"] = ratio.cumprod().to_numpy()
    factor = panel["analysis_factor"].replace(0, np.nan)
    for name in ("open", "high", "low", "close", "preclose"):
        panel[f"analysis_{name}"] = pd.to_numeric(panel[name], errors="coerce") / factor
    panel["analysis_true_range"] = pd.concat(
        [
            panel["analysis_high"] - panel["analysis_low"],
            (panel["analysis_high"] - panel["analysis_preclose"]).abs(),
            (panel["analysis_low"] - panel["analysis_preclose"]).abs(),
        ], axis=1,
    ).max(axis=1)
    for name in ("atr14", "ma5", "ma10", "ma20", "ma60", "prior_high3", "prior_low5"):
        panel[name] = np.nan
    for _, sf in panel.groupby("symbol", sort=False):
        idx = sf.index
        close = sf["analysis_close"]
        panel.loc[idx, "atr14"] = sf["analysis_true_range"].rolling(14, min_periods=14).mean().to_numpy()
        for window in (5, 10, 20, 60):
            panel.loc[idx, f"ma{window}"] = close.rolling(window, min_periods=window).mean().to_numpy()
        panel.loc[idx, "prior_high3"] = sf["analysis_high"].shift(1).rolling(3, min_periods=3).max().to_numpy()
        panel.loc[idx, "prior_low5"] = sf["analysis_low"].shift(1).rolling(5, min_periods=5).min().to_numpy()
    panel["prior_analysis_close"] = panel.groupby("symbol", sort=False)["analysis_close"].shift(1)
    panel["prior_ma5"] = panel.groupby("symbol", sort=False)["ma5"].shift(1)
    panel["ma5_change"] = panel.groupby("symbol", sort=False)["ma5"].diff()
    market = panel[["feature_date", "market_close"]].drop_duplicates("feature_date").sort_values("feature_date")
    market["market_ma20"] = market["market_close"].rolling(20, min_periods=20).mean()
    market["market_return_20"] = market["market_close"] / market["market_close"].shift(20) - 1.0
    panel = panel.merge(market[["feature_date", "market_ma20", "market_return_20"]], on="feature_date", how="left", validate="many_to_one")
    panel["legal_buy_open"] = (
        panel["hard_valid"].fillna(False) & panel["current_day_data_tradable"].fillna(False) & panel["trade_status"].eq(1)
        & ~panel["buy_blocked_open"].astype("boolean").fillna(True) & panel["open"].gt(0)
    )
    panel["legal_sell_open"] = (
        panel["hard_valid"].fillna(False) & panel["current_day_data_tradable"].fillna(False) & panel["trade_status"].eq(1)
        & ~panel["sell_blocked_open"].astype("boolean").fillna(True) & panel["open"].gt(0)
    )
    check = candidate[["symbol", "feature_date", "analysis_close"]].merge(
        panel[["symbol", "feature_date", "analysis_close"]], on=["symbol", "feature_date"], suffixes=("_frozen", "_rebuilt"), how="left", validate="many_to_one"
    )
    difference = (check["analysis_close_frozen"] - check["analysis_close_rebuilt"]).abs()
    if check["analysis_close_rebuilt"].isna().any() or float(difference.max()) != 0.0:
        raise RuntimeError("price-only adjusted coordinate does not exactly reproduce frozen candidate closes")
    return panel.sort_values(["symbol", "feature_date"]).reset_index(drop=True)


def episode_table(candidate: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    episodes = candidate.sort_values(["candidate_episode_id", "feature_date"]).drop_duplicates("candidate_episode_id", keep="first").copy()
    episodes = episodes.rename(columns={"feature_date": "candidate_date", "feature_available_at": "candidate_at"})
    episodes["split"] = episodes["candidate_date"].map(split_for_date)
    lookup = panel.set_index(["symbol", "feature_date"])
    episodes["candidate_position"] = [int(lookup.loc[(row.symbol, row.candidate_date), "symbol_position"]) for row in episodes.itertuples(index=False)]
    if len(episodes) != EXPECTED_EPISODES or episodes["candidate_episode_id"].nunique() != EXPECTED_EPISODES:
        raise RuntimeError("episode identity changed")
    return episodes.sort_values(["candidate_date", "symbol", "candidate_episode_id"]).reset_index(drop=True)


def signal_mask(sf: pd.DataFrame, carrier: str) -> pd.Series:
    if carrier == "A_PULLBACK_RECLAIM":
        return sf["analysis_close"].gt(sf["ma5"]) & sf["prior_analysis_close"].le(sf["prior_ma5"]) & sf["analysis_close"].gt(sf["analysis_preclose"])
    if carrier == "B_LOCAL_BREAKOUT":
        return sf["analysis_close"].gt(sf["prior_high3"])
    if carrier == "C_TREND_RESUMPTION":
        return sf["ma20"].gt(sf["ma60"]) & sf["analysis_close"].gt(sf["ma5"]) & sf["ma5_change"].gt(0) & sf["analysis_close"].gt(sf["analysis_preclose"])
    raise KeyError(carrier)


def next_legal_position(sf: pd.DataFrame, start_position: int, column: str, stop_position: int) -> int | None:
    for position in range(start_position, min(len(sf), stop_position + 1)):
        if bool(sf.iloc[position][column]):
            return position
    return None


def trade_return(entry_mid: float, exit_mid: float, completed: bool, costs: CostModel) -> tuple[float, float, float]:
    gross = exit_mid / entry_mid - 1.0
    outlay = entry_mid * (1.0 + costs.slippage) * (1.0 + costs.buy_fee)
    proceeds = exit_mid if not completed else exit_mid * (1.0 - costs.slippage) * (1.0 - costs.sell_fee)
    net = proceeds / outlay - 1.0
    return gross, net, gross - net


def _blank_episode_row(carrier: str, episode: pd.Series, atr_multiple: float) -> dict[str, Any]:
    return {
        "trade_id": stable_id("trd", carrier, episode.candidate_episode_id, atr_multiple),
        "carrier": carrier,
        "atr_multiple": atr_multiple,
        "candidate_episode_id": episode.candidate_episode_id,
        "symbol": episode.symbol,
        "split": episode.split,
        "candidate_date": episode.candidate_date,
        "candidate_at": episode.candidate_at,
        "candidate_position": int(episode.candidate_position),
        "candidate_pullback_depth": float(episode.price_drawdown_20),
        "entry_signal_date": pd.NaT,
        "entry_signal_at": pd.NaT,
        "entry_intent_at": pd.NaT,
        "next_legal_execution_at": pd.NaT,
        "actual_entry_at": pd.NaT,
        "actual_entry_price": math.nan,
        "actual_entry_analysis_mid": math.nan,
        "actual_exit_at": pd.NaT,
        "actual_exit_price": math.nan,
        "exit_analysis_mid_or_terminal_close": math.nan,
        "exit_signal_at": pd.NaT,
        "exit_intent_at": pd.NaT,
        "exit_reason": "CANDIDATE_EXPIRED",
        "entry_status": "NO_SIGNAL_EXPIRED",
        "entry_signal": False,
        "entry_intent": False,
        "actual_fill": False,
        "completed": False,
        "terminal_open": False,
        "signal_wait_sessions": pd.NA,
        "legal_fill_wait_sessions": pd.NA,
        "holding_sessions": pd.NA,
        "hard_stop_analysis_level": math.nan,
        "initial_risk_fraction": math.nan,
        "trigger_strength": math.nan,
        "entry_trend_strength": math.nan,
        "entry_breakout_distance": math.nan,
        "entry_volatility": math.nan,
        "entry_market_return_20": math.nan,
        "entry_market_trend": "UNKNOWN",
        "gross_return": math.nan,
        "net_return": math.nan,
        "transaction_cost_return": math.nan,
        "mfe": math.nan,
        "mae": math.nan,
        "mfe_capture_ratio": math.nan,
        "profit_giveback": math.nan,
    }


def build_carrier_period_trades(
    panel: pd.DataFrame, episodes: pd.DataFrame, carrier: str, split: str, atr_multiple: float, costs: CostModel,
) -> pd.DataFrame:
    period_end = SPLIT_BOUNDS[split][1]
    rows: list[dict[str, Any]] = []
    period_episodes = episodes[episodes["split"].eq(split)]
    for symbol, symbol_episodes in period_episodes.groupby("symbol", sort=False):
        sf = panel[panel["symbol"].eq(symbol)].sort_values("feature_date").reset_index(drop=True)
        mask = signal_mask(sf, carrier).fillna(False)
        last_exit_position = -1
        for _, episode in symbol_episodes.sort_values(["candidate_date", "candidate_episode_id"]).iterrows():
            row = _blank_episode_row(carrier, episode, atr_multiple)
            start = int(episode["candidate_position"] - sf["symbol_position"].iloc[0])
            signal_stop = min(len(sf) - 1, start + int(RISK_CONTRACT["signal_wait_source_sessions"]) - 1)
            signal_positions = [p for p in range(start, signal_stop + 1) if sf.iloc[p]["feature_date"] <= period_end and bool(mask.iloc[p])]
            if not signal_positions:
                rows.append(row)
                continue
            signal_pos = signal_positions[0]
            signal = sf.iloc[signal_pos]
            row.update({
                "entry_signal": True,
                "entry_signal_date": signal["feature_date"],
                "entry_signal_at": pd.Timestamp(signal["available_at"]),
                "signal_wait_sessions": signal_pos - start,
                "trigger_strength": float(
                    signal["analysis_close"] / (signal["prior_high3"] if carrier == "B_LOCAL_BREAKOUT" else signal["ma5"]) - 1.0
                ),
                "entry_trend_strength": float(signal["ma20"] / signal["ma60"] - 1.0) if finite(signal["ma60"]) else math.nan,
                "entry_breakout_distance": float(signal["analysis_close"] / signal["prior_high3"] - 1.0) if finite(signal["prior_high3"]) else math.nan,
                "entry_volatility": float(signal["atr14"] / signal["analysis_close"]) if finite(signal["atr14"]) else math.nan,
                "entry_market_return_20": float(signal["market_return_20"]) if finite(signal["market_return_20"]) else math.nan,
                "entry_market_trend": "STRONG" if finite(signal["market_ma20"]) and signal["market_close"] > signal["market_ma20"] else "WEAK",
            })
            if signal_pos <= last_exit_position:
                row.update({"entry_status": "SIGNAL_WHILE_POSITION_OPEN", "exit_reason": "NO_NEW_INTENT"})
                rows.append(row)
                continue
            if signal_pos + 1 >= len(sf) or sf.iloc[signal_pos + 1]["feature_date"] > period_end:
                row.update({"entry_status": "INTENT_OUTSIDE_PERIOD", "exit_reason": "NO_FILL_PERIOD_END"})
                rows.append(row)
                continue
            row["entry_intent"] = True
            row["entry_intent_at"] = open_at(sf.iloc[signal_pos + 1]["feature_date"], minutes_before=5)
            fill_stop = min(len(sf) - 1, signal_pos + int(RISK_CONTRACT["legal_fill_wait_source_sessions"]))
            fill_stop = max(signal_pos + 1, fill_stop)
            entry_pos = next_legal_position(sf, signal_pos + 1, "legal_buy_open", fill_stop)
            if entry_pos is None or sf.iloc[entry_pos]["feature_date"] > period_end:
                row.update({"entry_status": "NO_LEGAL_BUY_OPEN", "exit_reason": "NO_FILL_EXPIRED"})
                rows.append(row)
                continue
            entry = sf.iloc[entry_pos]
            entry_mid = float(entry["analysis_open"])
            risk_unit = atr_multiple * float(signal["atr14"])
            if not finite(risk_unit) or risk_unit <= 0 or entry_mid <= 0:
                row.update({"entry_status": "REQUIRED_PRICE_INPUT_UNKNOWN", "exit_reason": "FAIL_CLOSED"})
                rows.append(row)
                continue
            hard_stop = entry_mid - risk_unit
            next_legal_at = open_at(entry["feature_date"])
            row.update({
                "entry_status": "FILLED",
                "actual_fill": True,
                "next_legal_execution_at": next_legal_at,
                "actual_entry_at": next_legal_at,
                "actual_entry_price": float(entry["open"]) * (1.0 + costs.slippage),
                "actual_entry_analysis_mid": entry_mid,
                "legal_fill_wait_sessions": entry_pos - signal_pos,
                "hard_stop_analysis_level": hard_stop,
                "initial_risk_fraction": risk_unit / entry_mid,
            })
            running_high = float(entry["analysis_high"])
            exit_signal_pos: int | None = None
            exit_reason = "OPEN_AT_PERIOD_END"
            for position in range(entry_pos, len(sf)):
                bar = sf.iloc[position]
                if bar["feature_date"] > period_end:
                    break
                running_high = max(running_high, float(bar["analysis_high"]))
                holding = position - entry_pos + 1
                mfe_now = running_high / entry_mid - 1.0
                hard = float(bar["analysis_close"]) <= hard_stop
                protect = mfe_now >= 2.0 * risk_unit / entry_mid and float(bar["analysis_close"]) < float(bar["ma5"])
                ordinary = holding >= 3 and float(bar["analysis_close"]) < float(bar["ma10"])
                timed = holding >= 20
                if hard or protect or ordinary or timed:
                    exit_signal_pos = position
                    exit_reason = "HARD_RISK" if hard else "PROFIT_PROTECTION" if protect else "ORDINARY_TREND" if ordinary else "MAX_HOLDING"
                    break
            exit_pos: int | None = None
            if exit_signal_pos is not None and exit_signal_pos + 1 < len(sf) and sf.iloc[exit_signal_pos + 1]["feature_date"] <= period_end:
                exit_pos = next_legal_position(sf, exit_signal_pos + 1, "legal_sell_open", len(sf) - 1)
                if exit_pos is not None and sf.iloc[exit_pos]["feature_date"] > period_end:
                    exit_pos = None
            completed = exit_pos is not None
            period_rows = sf[sf["feature_date"].le(period_end)]
            terminal_pos = int(exit_pos) if completed else int(period_rows.index.max())
            path_stop = int(exit_signal_pos) if exit_signal_pos is not None else terminal_pos
            path = sf.iloc[entry_pos : path_stop + 1]
            exit_mid = float(sf.iloc[exit_pos]["analysis_open"]) if completed else float(sf.iloc[terminal_pos]["analysis_close"])
            gross, net, transaction_cost = trade_return(entry_mid, exit_mid, completed, costs)
            mfe = float(path["analysis_high"].max() / entry_mid - 1.0)
            mae = float(path["analysis_low"].min() / entry_mid - 1.0)
            if completed:
                actual_exit_at = open_at(sf.iloc[exit_pos]["feature_date"])
                actual_exit_price = float(sf.iloc[exit_pos]["open"]) * (1.0 - costs.slippage)
                exit_signal_at = pd.Timestamp(sf.iloc[exit_signal_pos]["available_at"])
                exit_intent_at = open_at(sf.iloc[exit_signal_pos + 1]["feature_date"], minutes_before=5)
            else:
                actual_exit_at, actual_exit_price = pd.NaT, math.nan
                exit_signal_at = pd.Timestamp(sf.iloc[exit_signal_pos]["available_at"]) if exit_signal_pos is not None else pd.NaT
                exit_intent_at = pd.NaT
                if exit_signal_pos is not None:
                    exit_reason = f"{exit_reason}_NO_LEGAL_FILL_BY_PERIOD_END"
            row.update({
                "actual_exit_at": actual_exit_at,
                "actual_exit_price": actual_exit_price,
                "exit_analysis_mid_or_terminal_close": exit_mid,
                "exit_signal_at": exit_signal_at,
                "exit_intent_at": exit_intent_at,
                "exit_reason": exit_reason,
                "completed": completed,
                "terminal_open": not completed,
                "holding_sessions": terminal_pos - entry_pos + 1,
                "gross_return": gross,
                "net_return": net,
                "transaction_cost_return": transaction_cost,
                "mfe": mfe,
                "mae": mae,
                "mfe_capture_ratio": gross / mfe if mfe > 0 else math.nan,
                "profit_giveback": mfe - gross,
            })
            rows.append(row)
            last_exit_position = terminal_pos
    result = pd.DataFrame(rows)
    if len(result) != len(period_episodes):
        raise RuntimeError(f"episode funnel lost rows for {carrier}/{split}")
    return result.sort_values(["candidate_date", "symbol", "candidate_episode_id"]).reset_index(drop=True)


def profit_factor(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(numeric[numeric > 0].sum())
    losses = float(-numeric[numeric < 0].sum())
    return gains / losses if losses > 0 else math.inf if gains > 0 else math.nan


def trade_metrics(trades: pd.DataFrame, carrier: str, split: str) -> dict[str, Any]:
    all_rows = trades[trades["carrier"].eq(carrier) & trades["split"].eq(split)]
    completed = all_rows[all_rows["completed"].fillna(False)].copy()
    values = pd.to_numeric(completed["net_return"], errors="coerce")
    gross = pd.to_numeric(completed["gross_return"], errors="coerce")
    winners, losers = values[values > 0], values[values < 0]
    gross_alpha = float(gross.sum())
    return {
        "carrier": carrier, "split": split,
        "candidate_episodes": len(all_rows),
        "entry_signals": int(all_rows["entry_signal"].sum()),
        "entry_intents": int(all_rows["entry_intent"].sum()),
        "actual_fills": int(all_rows["actual_fill"].sum()),
        "completed_trades": len(completed),
        "entry_conversion_rate": float(all_rows["actual_fill"].mean()) if len(all_rows) else math.nan,
        "completion_rate_of_fills": float(len(completed) / all_rows["actual_fill"].sum()) if all_rows["actual_fill"].sum() else math.nan,
        "win_rate": float(values.gt(0).mean()) if len(values) else math.nan,
        "mean_gross_trade_return": float(gross.mean()) if len(gross) else math.nan,
        "gross_trade_sum": float(gross.sum()) if len(gross) else math.nan,
        "mean_trade_return": float(values.mean()) if len(values) else math.nan,
        "net_expectancy": float(values.mean()) if len(values) else math.nan,
        "median_trade_return": float(values.median()) if len(values) else math.nan,
        "average_winner": float(winners.mean()) if len(winners) else math.nan,
        "average_loser": float(losers.mean()) if len(losers) else math.nan,
        "payoff_ratio": float(winners.mean() / -losers.mean()) if len(winners) and len(losers) else math.nan,
        "realized_profit_factor": profit_factor(values),
        "worst_trade": float(values.min()) if len(values) else math.nan,
        "loss_p01": float(values.quantile(0.01)) if len(values) else math.nan,
        "loss_p05": float(values.quantile(0.05)) if len(values) else math.nan,
        "mean_mfe": float(completed["mfe"].mean()) if len(completed) else math.nan,
        "mean_mae": float(completed["mae"].mean()) if len(completed) else math.nan,
        "mean_mfe_capture_ratio": float(completed["mfe_capture_ratio"].replace([np.inf, -np.inf], np.nan).mean()) if len(completed) else math.nan,
        "mean_profit_giveback": float(completed["profit_giveback"].mean()) if len(completed) else math.nan,
        "mean_holding_sessions": float(completed["holding_sessions"].mean()) if len(completed) else math.nan,
        "median_holding_sessions": float(completed["holding_sessions"].median()) if len(completed) else math.nan,
        "mean_cost_per_trade": float(completed["transaction_cost_return"].mean()) if len(completed) else math.nan,
        "cost_fraction_of_gross_alpha": float(completed["transaction_cost_return"].sum() / gross_alpha) if gross_alpha > 0 else math.nan,
        "net_realized_trade_sum": float(values.sum()),
    }


def _max_drawdown(equity: pd.Series) -> tuple[float, int]:
    values = pd.to_numeric(equity, errors="coerce").dropna()
    if values.empty:
        return math.nan, 0
    drawdown = values / values.cummax() - 1.0
    longest = current = 0
    for underwater in drawdown.lt(0):
        current = current + 1 if underwater else 0
        longest = max(longest, current)
    return float(drawdown.min()), longest


def simulate_portfolio(trades: pd.DataFrame, panel: pd.DataFrame, split: str, costs: CostModel) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    start, end = SPLIT_BOUNDS[split]
    dates = pd.Index(sorted(panel.loc[panel["feature_date"].between(start, end), "feature_date"].unique()))
    close_lookup = panel.set_index(["feature_date", "symbol"])["analysis_close"]
    eligible = trades[trades["split"].eq(split) & trades["actual_fill"].fillna(False)].copy()
    eligible["entry_date"] = pd.to_datetime(eligible["actual_entry_at"]).dt.normalize()
    eligible["exit_date"] = pd.to_datetime(eligible["actual_exit_at"]).dt.normalize()
    entries = {date: frame for date, frame in eligible.groupby("entry_date")}
    exits = {date: frame for date, frame in eligible.dropna(subset=["exit_date"]).groupby("exit_date")}
    cash = float(PORTFOLIO_CONTRACT["initial_capital"])
    realized_pnl = 0.0
    positions: dict[str, dict[str, Any]] = {}
    symbol_positions: dict[str, str] = {}
    last_prices: dict[str, float] = {}
    curve_rows: list[dict[str, Any]] = []
    admission_rows: list[dict[str, Any]] = []
    for date in dates:
        turnover = transaction_cost = 0.0
        same_open_exits = exits.get(date)
        if same_open_exits is None:
            same_open_exits = eligible.iloc[0:0]
        for _, trade in same_open_exits.sort_values(["symbol", "trade_id"]).iterrows():
            position = positions.pop(trade["trade_id"], None)
            if position is None:
                continue
            symbol_positions.pop(position["symbol"], None)
            mid = position["shares"] * float(trade["exit_analysis_mid_or_terminal_close"])
            proceeds = mid * (1.0 - costs.slippage) * (1.0 - costs.sell_fee)
            cash += proceeds
            realized_pnl += proceeds - position["cost_basis"]
            turnover += mid
            transaction_cost += mid - proceeds
        equity_before_entries = cash + sum(position["shares"] * last_prices.get(position["symbol"], position["entry_mid"]) for position in positions.values())
        same_open = entries.get(date, pd.DataFrame())
        if len(same_open):
            same_open = same_open.sort_values(["trigger_strength", "candidate_at", "symbol", "trade_id"], ascending=[False, True, True, True])
        for _, trade in same_open.iterrows():
            admitted, reason = True, "ADMITTED"
            if len(positions) >= int(PORTFOLIO_CONTRACT["maximum_concurrent_positions"]):
                admitted, reason = False, "NO_PORTFOLIO_SLOT"
            elif trade["symbol"] in symbol_positions:
                admitted, reason = False, "SYMBOL_ALREADY_HELD"
            if admitted:
                entry_mid = float(trade["actual_entry_analysis_mid"])
                target_mid = equity_before_entries * float(PORTFOLIO_CONTRACT["target_fraction"])
                maximum_mid = cash / ((1.0 + costs.slippage) * (1.0 + costs.buy_fee))
                mid = min(target_mid, maximum_mid)
                if mid <= 1e-12:
                    admitted, reason = False, "INSUFFICIENT_CASH"
                else:
                    shares = mid / entry_mid
                    cost_basis = mid * (1.0 + costs.slippage) * (1.0 + costs.buy_fee)
                    cash -= cost_basis
                    turnover += mid
                    transaction_cost += cost_basis - mid
                    positions[trade["trade_id"]] = {"symbol": trade["symbol"], "shares": shares, "entry_mid": entry_mid, "cost_basis": cost_basis}
                    symbol_positions[trade["symbol"]] = trade["trade_id"]
                    last_prices[trade["symbol"]] = entry_mid
            admission_rows.append({"carrier": trade["carrier"], "split": split, "trade_id": trade["trade_id"], "date": date, "admitted": admitted, "reason": reason})
        market_value = 0.0
        terminal_unrealized = 0.0
        for position in positions.values():
            key = (date, position["symbol"])
            if key in close_lookup.index and finite(close_lookup.loc[key]):
                last_prices[position["symbol"]] = float(close_lookup.loc[key])
            marked = position["shares"] * last_prices[position["symbol"]]
            market_value += marked
            terminal_unrealized += marked - position["cost_basis"]
        equity = cash + market_value
        if not math.isclose(equity - 1.0, realized_pnl + terminal_unrealized, rel_tol=0.0, abs_tol=1e-10):
            raise RuntimeError("portfolio realized/unrealized ledger does not conserve")
        curve_rows.append({
            "date": date, "equity": equity, "cash": cash, "market_value": market_value,
            "exposure": market_value / equity if equity > 0 else math.nan, "turnover_notional": turnover,
            "transaction_cost": transaction_cost, "open_positions": len(positions),
            "realized_pnl": realized_pnl, "terminal_unrealized_pnl": terminal_unrealized,
        })
    curve = pd.DataFrame(curve_rows)
    curve["daily_return"] = curve["equity"].pct_change(fill_method=None)
    if len(curve):
        curve.loc[curve.index[0], "daily_return"] = curve.loc[curve.index[0], "equity"] - 1.0
    terminal = curve.iloc[-1]
    ledger = {
        "realized_pnl": float(terminal["realized_pnl"]),
        "terminal_unrealized_pnl": float(terminal["terminal_unrealized_pnl"]),
        "total_marked_pnl": float(terminal["equity"] - 1.0),
        "pnl_excluding_terminal_unrealized": float(terminal["realized_pnl"]),
        "terminal_open_positions": int(terminal["open_positions"]),
    }
    return curve, pd.DataFrame(admission_rows), ledger


def portfolio_metrics(carrier: str, split: str, gross_curve: pd.DataFrame, net_curve: pd.DataFrame, admissions: pd.DataFrame) -> dict[str, Any]:
    gross_return = float(gross_curve["equity"].iloc[-1] - 1.0)
    net_return = float(net_curve["equity"].iloc[-1] - 1.0)
    daily = pd.to_numeric(net_curve["daily_return"], errors="coerce").dropna()
    years = max(len(net_curve) / 252.0, 1 / 252)
    annualized = (1.0 + net_return) ** (1.0 / years) - 1.0 if net_return > -1 else -1.0
    volatility = float(daily.std(ddof=1))
    downside = float(daily[daily < 0].std(ddof=1))
    drawdown, duration = _max_drawdown(net_curve["equity"])
    admitted_ids = admissions.loc[admissions["admitted"], "trade_id"] if len(admissions) else pd.Series(dtype=str)
    return {
        "carrier": carrier, "split": split,
        "gross_total_return": gross_return, "net_total_return": net_return,
        "annualized_return": annualized,
        "sharpe": float(daily.mean() / volatility * math.sqrt(252)) if volatility > 0 else math.nan,
        "sortino": float(daily.mean() / downside * math.sqrt(252)) if downside > 0 else math.nan,
        "calmar": annualized / abs(drawdown) if drawdown < 0 else math.nan,
        "maximum_drawdown": drawdown,
        "maximum_drawdown_duration_sessions": duration,
        "average_exposure": float(net_curve["exposure"].mean()),
        "turnover": float(net_curve["turnover_notional"].sum() / net_curve["equity"].mean()),
        "transaction_costs": float(net_curve["transaction_cost"].sum()),
        "portfolio_admitted_entries": int(len(admitted_ids)),
        "capacity_rejections": int((~admissions["admitted"]).sum()) if len(admissions) else 0,
        "terminal_open_positions": int(net_curve["open_positions"].iloc[-1]),
        "ending_equity": float(net_curve["equity"].iloc[-1]),
    }


def evaluate_portfolios(trades: pd.DataFrame, panel: pd.DataFrame, cost_name: str = "BASE") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    metrics, mtm, all_admissions = [], [], []
    for carrier in CARRIER_DEFINITIONS:
        for split in SPLITS:
            subset = trades[trades["carrier"].eq(carrier) & trades["split"].eq(split)]
            gross_curve, _, _ = simulate_portfolio(subset, panel, split, CostModel.named("ZERO"))
            net_curve, admissions, ledger = simulate_portfolio(subset, panel, split, CostModel.named(cost_name))
            metrics.append(portfolio_metrics(carrier, split, gross_curve, net_curve, admissions))
            total = ledger["total_marked_pnl"]
            material = bool(total > 0 and (ledger["pnl_excluding_terminal_unrealized"] <= 0 or abs(ledger["terminal_unrealized_pnl"]) > 0.25 * abs(total)))
            mtm.append({"carrier": carrier, "split": split, **ledger, "terminal_mtm_share_of_total": abs(ledger["terminal_unrealized_pnl"]) / abs(total) if total != 0 else math.nan, "positive_result_depends_materially_on_terminal_mtm": material})
            if len(admissions):
                all_admissions.append(admissions)
    return pd.DataFrame(metrics), pd.DataFrame(mtm), pd.concat(all_admissions, ignore_index=True) if all_admissions else pd.DataFrame()


def winner_tail(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for carrier in CARRIER_DEFINITIONS:
        for split in SPLITS:
            completed = trades[trades["carrier"].eq(carrier) & trades["split"].eq(split) & trades["completed"].fillna(False)].copy()
            values = completed["net_return"].sort_values(ascending=False)
            winners = values[values > 0]
            positive_sum = float(winners.sum())
            top_decile_n = max(1, math.ceil(len(winners) * 0.10)) if len(winners) else 0
            top_5pct_n = max(1, math.ceil(len(winners) * 0.05)) if len(winners) else 0
            top_1pct_n = max(1, math.ceil(len(values) * 0.01)) if len(values) else 0
            def exclusion(n: int) -> tuple[float, float, float]:
                kept = values.iloc[n:]
                return float(kept.sum()), float(kept.mean()) if len(kept) else math.nan, profit_factor(kept)
            ex1, ex1_mean, ex1_pf = exclusion(1)
            ex5, ex5_mean, ex5_pf = exclusion(min(5, len(values)))
            ex1p, ex1p_mean, ex1p_pf = exclusion(top_1pct_n)
            rows.append({
                "carrier": carrier, "split": split, "completed_trades": len(values), "winning_trades": len(winners),
                "top_decile_winner_contribution": float(winners.iloc[:top_decile_n].sum() / positive_sum) if positive_sum > 0 else math.nan,
                "top_5pct_winner_contribution": float(winners.iloc[:top_5pct_n].sum() / positive_sum) if positive_sum > 0 else math.nan,
                "largest_10_trades_contribution": float(values.iloc[:10].clip(lower=0).sum() / positive_sum) if positive_sum > 0 else math.nan,
                "net_sum_excluding_largest_winner": ex1, "expectancy_excluding_largest_winner": ex1_mean, "pf_excluding_largest_winner": ex1_pf,
                "net_sum_excluding_top_5_winners": ex5, "expectancy_excluding_top_5_winners": ex5_mean, "pf_excluding_top_5_winners": ex5_pf,
                "top_1pct_trade_count": top_1pct_n, "net_sum_excluding_top_1pct_trades": ex1p, "expectancy_excluding_top_1pct_trades": ex1p_mean, "pf_excluding_top_1pct_trades": ex1p_pf,
            })
    return pd.DataFrame(rows)


def symbol_outputs(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, summary = [], []
    for carrier in CARRIER_DEFINITIONS:
        for split in SPLITS:
            completed = trades[trades["carrier"].eq(carrier) & trades["split"].eq(split) & trades["completed"].fillna(False)]
            grouped = completed.groupby("symbol")["net_return"].agg([("completed_trades", "size"), ("net_trade_sum", "sum"), ("mean_expectancy", "mean")]).reset_index()
            positive_total = float(grouped.loc[grouped["net_trade_sum"] > 0, "net_trade_sum"].sum())
            grouped["positive_contribution_share"] = grouped["net_trade_sum"].clip(lower=0) / positive_total if positive_total > 0 else math.nan
            grouped["contribution_rank"] = grouped["net_trade_sum"].rank(method="first", ascending=False).astype(int)
            grouped["profitable_symbol"] = grouped["net_trade_sum"] > 0
            grouped.insert(0, "split", split)
            grouped.insert(0, "carrier", carrier)
            rows.append(grouped)
            ordered = grouped.sort_values("net_trade_sum", ascending=False)
            summary.append({
                "carrier": carrier, "split": split, "traded_symbols": len(grouped),
                "profitable_symbols": int(grouped["profitable_symbol"].sum()), "unprofitable_symbols": int((~grouped["profitable_symbol"]).sum()),
                "median_per_symbol_expectancy": float(grouped["mean_expectancy"].median()) if len(grouped) else math.nan,
                "largest_symbol_positive_contribution_share": float(grouped["positive_contribution_share"].max()) if len(grouped) else math.nan,
                "net_sum_excluding_top_symbol": float(ordered.iloc[1:]["net_trade_sum"].sum()) if len(ordered) else math.nan,
                "net_sum_excluding_top_3_symbols": float(ordered.iloc[3:]["net_trade_sum"].sum()) if len(ordered) else math.nan,
                "net_sum_excluding_top_5_symbols": float(ordered.iloc[5:]["net_trade_sum"].sum()) if len(ordered) else math.nan,
            })
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(), pd.DataFrame(summary)


def monthly_concentration(trades: pd.DataFrame) -> pd.DataFrame:
    completed = trades[trades["completed"].fillna(False)].copy()
    completed["exit_month"] = pd.to_datetime(completed["actual_exit_at"]).dt.to_period("M").astype(str)
    grouped = completed.groupby(["carrier", "split", "exit_month"])["net_return"].agg([("completed_trades", "size"), ("net_trade_sum", "sum"), ("mean_expectancy", "mean")]).reset_index()
    grouped["positive_month_contribution_share"] = grouped.groupby(["carrier", "split"])["net_trade_sum"].transform(lambda s: s.clip(lower=0) / s.clip(lower=0).sum() if s.clip(lower=0).sum() > 0 else np.nan)
    return grouped


def regime_robustness(trades: pd.DataFrame, discovery_volatility_median: float) -> pd.DataFrame:
    completed = trades[trades["completed"].fillna(False)].copy()
    completed["volatility_regime"] = np.where(completed["entry_volatility"] > discovery_volatility_median, "HIGH", "LOW")
    completed["calendar_subperiod"] = pd.to_datetime(completed["entry_signal_date"]).dt.to_period("M").astype(str)
    rows = []
    for (carrier, split), frame in completed.groupby(["carrier", "split"], sort=True):
        for dimension, column in (("realized_volatility", "volatility_regime"), ("market_trend", "entry_market_trend"), ("calendar_month", "calendar_subperiod")):
            for bucket, subset in frame.groupby(column, sort=True):
                values = subset["net_return"]
                rows.append({"carrier": carrier, "split": split, "dimension": dimension, "bucket": bucket, "completed_trades": len(subset), "net_expectancy": float(values.mean()), "realized_profit_factor": profit_factor(values), "net_trade_sum": float(values.sum())})
    return pd.DataFrame(rows)


def price_attribution(trades: pd.DataFrame) -> pd.DataFrame:
    features = ["candidate_pullback_depth", "entry_trend_strength", "signal_wait_sessions", "entry_breakout_distance", "entry_volatility", "legal_fill_wait_sessions", "initial_risk_fraction"]
    completed = trades[trades["completed"].fillna(False)].copy()
    completed["outcome"] = np.where(completed["net_return"] > 0, "WINNER", "LOSER_OR_FLAT")
    rows = []
    for (carrier, split, outcome), frame in completed.groupby(["carrier", "split", "outcome"], sort=True):
        for feature in features:
            values = pd.to_numeric(frame[feature], errors="coerce").dropna()
            rows.append({"carrier": carrier, "split": split, "outcome": outcome, "feature": feature, "observations": len(values), "mean": float(values.mean()) if len(values) else math.nan, "median": float(values.median()) if len(values) else math.nan})
    return pd.DataFrame(rows)


def entry_funnel(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for carrier in CARRIER_DEFINITIONS:
        for split in SPLITS:
            frame = trades[trades["carrier"].eq(carrier) & trades["split"].eq(split)]
            rows.append({
                "carrier": carrier, "split": split,
                "candidate_episodes": len(frame), "entry_signals": int(frame["entry_signal"].sum()),
                "entry_intents": int(frame["entry_intent"].sum()), "actual_fills": int(frame["actual_fill"].sum()),
                "completed_trades": int(frame["completed"].sum()), "candidate_expirations": int(frame["entry_status"].eq("NO_SIGNAL_EXPIRED").sum()),
                "signal_rate": float(frame["entry_signal"].mean()), "fill_conversion_rate": float(frame["actual_fill"].mean()),
            })
    return pd.DataFrame(rows)


def cost_sensitivity(trades: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for scenario in COST_SCENARIOS:
        costs = CostModel.named(scenario)
        adjusted = trades.copy()
        mask = adjusted["actual_fill"].fillna(False)
        recalculated = [trade_return(float(row.actual_entry_analysis_mid), float(row.exit_analysis_mid_or_terminal_close), bool(row.completed), costs) for row in adjusted.loc[mask].itertuples(index=False)]
        if recalculated:
            adjusted.loc[mask, ["gross_return", "net_return", "transaction_cost_return"]] = np.asarray(recalculated)
        portfolio, _, _ = evaluate_portfolios(adjusted, panel, scenario)
        for carrier in CARRIER_DEFINITIONS:
            for split in SPLITS:
                tm = trade_metrics(adjusted, carrier, split)
                pm = portfolio[(portfolio["carrier"].eq(carrier)) & (portfolio["split"].eq(split))].iloc[0]
                rows.append({"cost_scenario": scenario, "carrier": carrier, "split": split, "completed_trades": tm["completed_trades"], "net_expectancy": tm["net_expectancy"], "realized_profit_factor": tm["realized_profit_factor"], "net_trade_sum": tm["net_realized_trade_sum"], "net_portfolio_return": pm["net_total_return"], "transaction_costs": pm["transaction_costs"]})
    return pd.DataFrame(rows)


def risk_sensitivity(risk_trades: dict[float, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for atr_multiple, trades in sorted(risk_trades.items()):
        for carrier in CARRIER_DEFINITIONS:
            for split in SPLITS:
                row = trade_metrics(trades, carrier, split)
                rows.append({"atr_multiple": atr_multiple, "carrier": carrier, "split": split, "completed_trades": row["completed_trades"], "net_expectancy": row["net_expectancy"], "realized_profit_factor": row["realized_profit_factor"], "net_trade_sum": row["net_realized_trade_sum"]})
    return pd.DataFrame(rows)


def select_primary(discovery_trade_metrics: pd.DataFrame, discovery_portfolio: pd.DataFrame, discovery_costs: pd.DataFrame, discovery_risk: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    rows = []
    for carrier in CARRIER_DEFINITIONS:
        tm = discovery_trade_metrics[(discovery_trade_metrics["carrier"].eq(carrier)) & (discovery_trade_metrics["split"].eq("discovery"))].iloc[0]
        pm = discovery_portfolio[(discovery_portfolio["carrier"].eq(carrier)) & (discovery_portfolio["split"].eq("discovery"))].iloc[0]
        stressed = discovery_costs[(discovery_costs["carrier"].eq(carrier)) & (discovery_costs["split"].eq("discovery")) & (discovery_costs["cost_scenario"].eq("STRESSED"))].iloc[0]
        risk = discovery_risk[(discovery_risk["carrier"].eq(carrier)) & (discovery_risk["split"].eq("discovery"))]
        minimum_pf = min(float(tm["realized_profit_factor"]), float(stressed["realized_profit_factor"]), *[float(v) for v in risk["realized_profit_factor"]])
        eligible = bool(
            tm["completed_trades"] >= SELECTION_CONTRACT["minimum_completed_discovery_trades"]
            and tm["net_expectancy"] > 0 and tm["realized_profit_factor"] > 1 and pm["net_total_return"] > 0
            and pm["maximum_drawdown"] >= -0.25 and stressed["net_expectancy"] > 0
            and risk["net_expectancy"].gt(0).all()
        )
        rows.append({"carrier": carrier, "eligible": eligible, "minimum_discovery_pf_across_diagnostics": minimum_pf, "main_discovery_max_drawdown": float(pm["maximum_drawdown"]), "completed_discovery_trades": int(tm["completed_trades"])})
    comparison = pd.DataFrame(rows)
    pool = comparison[comparison["eligible"]].copy()
    fallback_used = False
    if pool.empty:
        fallback_used = True
        pool = comparison[comparison["completed_discovery_trades"].ge(SELECTION_CONTRACT["minimum_completed_discovery_trades"])].copy()
    if pool.empty:
        raise RuntimeError("no carrier meets minimum discovery sample for primary freeze")
    selected = str(pool.sort_values(["minimum_discovery_pf_across_diagnostics", "main_discovery_max_drawdown", "carrier"], ascending=[False, False, True]).iloc[0]["carrier"])
    comparison["selected_primary"] = comparison["carrier"].eq(selected)
    comparison["fallback_used"] = fallback_used
    return selected, comparison


def classification_table(trade: pd.DataFrame, portfolio: pd.DataFrame, mtm: pd.DataFrame, costs: pd.DataFrame, tails: pd.DataFrame, symbols: pd.DataFrame, primary: str) -> pd.DataFrame:
    rows = []
    for carrier in CARRIER_DEFINITIONS:
        validation = trade[(trade["carrier"].eq(carrier)) & (trade["split"].eq("validation"))].iloc[0]
        holdout = trade[(trade["carrier"].eq(carrier)) & (trade["split"].eq("holdout"))].iloc[0]
        hp = portfolio[(portfolio["carrier"].eq(carrier)) & (portfolio["split"].eq("holdout"))].iloc[0]
        hm = mtm[(mtm["carrier"].eq(carrier)) & (mtm["split"].eq("holdout"))].iloc[0]
        stressed = costs[(costs["carrier"].eq(carrier)) & (costs["split"].eq("holdout")) & (costs["cost_scenario"].eq("STRESSED"))].iloc[0]
        tail = tails[(tails["carrier"].eq(carrier)) & (tails["split"].eq("holdout"))].iloc[0]
        symbol = symbols[(symbols["carrier"].eq(carrier)) & (symbols["split"].eq("holdout"))].iloc[0]
        sample_ok = bool(holdout["completed_trades"] >= VIABILITY_CONTRACT["holdout_minimum_completed_trades"])
        trade_ok = bool(holdout["net_expectancy"] > 0 and holdout["realized_profit_factor"] > 1)
        validation_ok = bool(validation["net_expectancy"] > 0 and validation["realized_profit_factor"] > 1)
        portfolio_ok = bool(hp["net_total_return"] > 0)
        cost_ok = bool(stressed["net_expectancy"] > 0 and stressed["realized_profit_factor"] > 1 and stressed["net_portfolio_return"] > 0)
        terminal_ok = not bool(hm["positive_result_depends_materially_on_terminal_mtm"])
        ex5_ok = bool(tail["net_sum_excluding_top_5_winners"] > 0)
        symbol_ok = bool(symbol["largest_symbol_positive_contribution_share"] <= 0.25)
        concentration = "YES" if ex5_ok and symbol_ok else "NO" if not ex5_ok and not symbol_ok else "MIXED"
        if sample_ok and trade_ok and validation_ok and portfolio_ok and cost_ok and terminal_ok and concentration != "NO":
            classification = "ROBUST_POSITIVE"
        elif sample_ok and trade_ok:
            classification = "PROMISING_BUT_UNSTABLE"
        elif validation_ok and not trade_ok:
            classification = "VALIDATION_ONLY"
        elif not sample_ok:
            classification = "INSUFFICIENT_SAMPLE"
        else:
            classification = "NEGATIVE_EXPECTANCY"
        rows.append({
            "carrier": carrier, "selected_primary": carrier == primary, "classification": classification,
            "holdout_trade_economics_positive": trade_ok, "validation_trade_economics_positive": validation_ok,
            "holdout_portfolio_positive": portfolio_ok, "holdout_cost_robust": cost_ok,
            "terminal_mtm_independent": terminal_ok, "holdout_sample_adequate": sample_ok,
            "profit_concentration": concentration,
        })
    return pd.DataFrame(rows)


def canonical_period_table(trade: pd.DataFrame, portfolio: pd.DataFrame, mtm: pd.DataFrame, tails: pd.DataFrame, symbols: pd.DataFrame) -> pd.DataFrame:
    result = trade.merge(portfolio, on=["carrier", "split"], validate="one_to_one").merge(
        mtm, on=["carrier", "split"], validate="one_to_one"
    ).merge(
        tails[["carrier", "split", "largest_10_trades_contribution", "net_sum_excluding_top_5_winners"]], on=["carrier", "split"], validate="one_to_one"
    ).merge(
        symbols[["carrier", "split", "largest_symbol_positive_contribution_share", "net_sum_excluding_top_5_symbols"]], on=["carrier", "split"], validate="one_to_one"
    )
    return result.sort_values(["carrier", "split"]).reset_index(drop=True)


def hard_gates(primary: str, classification: pd.DataFrame, trade: pd.DataFrame, portfolio: pd.DataFrame, mtm: pd.DataFrame, costs: pd.DataFrame) -> dict[str, str]:
    chosen = classification[classification["carrier"].eq(primary)].iloc[0]
    ht = trade[(trade["carrier"].eq(primary)) & (trade["split"].eq("holdout"))].iloc[0]
    hp = portfolio[(portfolio["carrier"].eq(primary)) & (portfolio["split"].eq("holdout"))].iloc[0]
    hm = mtm[(mtm["carrier"].eq(primary)) & (mtm["split"].eq("holdout"))].iloc[0]
    stressed = costs[(costs["carrier"].eq(primary)) & (costs["split"].eq("holdout")) & (costs["cost_scenario"].eq("STRESSED"))].iloc[0]
    return {
        "CANDIDATE_UNIVERSE_UNCHANGED": "YES",
        "CHIP_DATA_USED_IN_CARRIER_SELECTION": "NO",
        "PRICE_CARRIER_FAMILY_PRE_REGISTERED": "YES",
        "PRIMARY_CARRIER_FROZEN_BEFORE_VALIDATION": "YES",
        "PRIMARY_CARRIER_FROZEN_BEFORE_HOLDOUT": "YES",
        "HOLDOUT_COMPLETED_TRADE_EXPECTANCY_POSITIVE": "YES" if ht["net_expectancy"] > 0 else "NO",
        "HOLDOUT_REALIZED_PROFIT_FACTOR_ABOVE_1": "YES" if ht["realized_profit_factor"] > 1 else "NO",
        "HOLDOUT_NET_PORTFOLIO_RETURN_POSITIVE": "YES" if hp["net_total_return"] > 0 else "NO",
        "POSITIVE_RESULT_DEPENDS_MATERIALLY_ON_TERMINAL_MTM": "YES" if hm["positive_result_depends_materially_on_terminal_mtm"] else "NO",
        "HOLDOUT_TRANSACTION_COST_ROBUST": "YES" if stressed["net_expectancy"] > 0 and stressed["realized_profit_factor"] > 1 and stressed["net_portfolio_return"] > 0 else "NO",
        "HOLDOUT_SAMPLE_SIZE_ADEQUATE": "YES" if ht["completed_trades"] >= VIABILITY_CONTRACT["holdout_minimum_completed_trades"] else "NO",
        "PROFIT_CONCENTRATION_ACCEPTABLE": str(chosen["profit_concentration"]),
        "ROBUST_PRICE_ONLY_SWING_CARRIER_FOUND": "YES" if chosen["classification"] == "ROBUST_POSITIVE" else "NO",
        "SAFE_TO_RETEST_V3_AS_SOFT_OVERLAY": "YES" if chosen["classification"] == "ROBUST_POSITIVE" else "NO",
        "SAFE_TO_DESIGN_PRODUCTION_SWING_STRATEGY": "NO",
        "SAFE_TO_EXPAND_RESEARCH_TO_FULL_MARKET_3941": "NO",
    }


def _fmt_pct(value: object) -> str:
    return "n/a" if not finite(value) else f"{float(value):.2%}"


def _fmt_num(value: object) -> str:
    return "n/a" if not finite(value) else f"{float(value):.3f}"


def render_report(primary: str, selection: pd.DataFrame, period: pd.DataFrame, classification: pd.DataFrame, gates: dict[str, str], symbols: pd.DataFrame, monthly: pd.DataFrame, risk: pd.DataFrame) -> str:
    primary_class = classification[classification["carrier"].eq(primary)].iloc[0]
    table_lines = ["| Carrier | Split | Trades | PF | Expectancy | Net portfolio | Max DD | Sharpe | Exposure | Terminal MTM share | Top-10 winner share | Top symbol share |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in period.itertuples(index=False):
        table_lines.append(f"| {row.carrier} | {row.split} | {row.completed_trades} | {_fmt_num(row.realized_profit_factor)} | {_fmt_pct(row.net_expectancy)} | {_fmt_pct(row.net_total_return)} | {_fmt_pct(row.maximum_drawdown)} | {_fmt_num(row.sharpe)} | {_fmt_pct(row.average_exposure)} | {_fmt_pct(row.terminal_mtm_share_of_total)} | {_fmt_pct(row.largest_10_trades_contribution)} | {_fmt_pct(row.largest_symbol_positive_contribution_share)} |")
    classification_lines = ["| Carrier | Primary | Classification | Validation trade edge | Holdout trade edge | Stressed-cost robust | Concentration |", "|---|---:|---|---:|---:|---:|---:|"]
    for row in classification.itertuples(index=False):
        classification_lines.append(f"| {row.carrier} | {'YES' if row.selected_primary else 'NO'} | {row.classification} | {'YES' if row.validation_trade_economics_positive else 'NO'} | {'YES' if row.holdout_trade_economics_positive else 'NO'} | {'YES' if row.holdout_cost_robust else 'NO'} | {row.profit_concentration} |")
    holdout = period[(period["carrier"].eq(primary)) & (period["split"].eq("holdout"))].iloc[0]
    validation = period[(period["carrier"].eq(primary)) & (period["split"].eq("validation"))].iloc[0]
    discovery = period[(period["carrier"].eq(primary)) & (period["split"].eq("discovery"))].iloc[0]
    symbol = symbols[(symbols["carrier"].eq(primary)) & (symbols["split"].eq("holdout"))].iloc[0]
    month = monthly[(monthly["carrier"].eq(primary)) & (monthly["split"].eq("holdout"))]
    max_month = float(month["positive_month_contribution_share"].max()) if len(month) else math.nan
    validation_month = monthly[(monthly["carrier"].eq(primary)) & (monthly["split"].eq("validation"))]
    validation_max_month = float(validation_month["positive_month_contribution_share"].max()) if len(validation_month) else math.nan
    primary_holdout_risk = risk[(risk["carrier"].eq(primary)) & (risk["split"].eq("holdout"))].sort_values("atr_multiple")
    risk_text = "; ".join(
        f"{row.atr_multiple:.1f}× ATR: expectancy {_fmt_pct(row.net_expectancy)}, PF {_fmt_num(row.realized_profit_factor)}"
        for row in primary_holdout_risk.itertuples(index=False)
    )
    reconciliation_lines = []
    for row in period.itertuples(index=False):
        if row.net_total_return > 0 and row.realized_profit_factor < 1:
            reconciliation_lines.append(
                f"- **{row.carrier} / {row.split}:** {_fmt_pct(row.net_total_return)} marked portfolio return coexists with PF {_fmt_num(row.realized_profit_factor)} because realized portfolio P&L was {_fmt_pct(row.realized_pnl)} while terminal unrealized P&L was {_fmt_pct(row.terminal_unrealized_pnl)}. This is endpoint-dependent, not positive completed-trade economics."
            )
    reconciliation = "\n".join(reconciliation_lines) if reconciliation_lines else "- No positive-portfolio/PF-below-one case occurred."
    viable = primary_class["classification"] == "ROBUST_POSITIVE"
    answers = [
        f"1. **Can P_PRICE_PULLBACK_20 support a positive-expectancy price-only swing system?** {'Yes, under the pre-registered gate.' if viable else 'Not established by this pre-registered study.'}",
        f"2. **Which carrier survives holdout?** {primary if viable else 'No carrier earned ROBUST_POSITIVE; ' + primary + ' was the discovery-frozen primary and classified ' + str(primary_class['classification']) + '.'}",
        f"3. **Positive completed-trade performance?** {'Yes' if holdout['net_expectancy'] > 0 else 'No'}; holdout net expectancy was {_fmt_pct(holdout['net_expectancy'])} across {int(holdout['completed_trades'])} completed trades.",
        f"4. **Realized PF above 1?** {'Yes' if holdout['realized_profit_factor'] > 1 else 'No'}; {_fmt_num(holdout['realized_profit_factor'])}.",
        f"5. **Positive after realistic costs?** {'Yes' if holdout['net_expectancy'] > 0 and holdout['net_total_return'] > 0 else 'No'} at base costs; stressed-cost robustness is {gates['HOLDOUT_TRANSACTION_COST_ROBUST']}.",
        f"6. **Material terminal MTM dependence?** {gates['POSITIVE_RESULT_DEPENDS_MATERIALLY_ON_TERMINAL_MTM']}; realized P&L {_fmt_pct(holdout['realized_pnl'])}, terminal unrealized {_fmt_pct(holdout['terminal_unrealized_pnl'])}.",
        f"7. **Excessive trade/symbol concentration?** Gate {gates['PROFIT_CONCENTRATION_ACCEPTABLE']}; top holdout symbol share {_fmt_pct(symbol['largest_symbol_positive_contribution_share'])}, largest positive validation/holdout month shares {_fmt_pct(validation_max_month)} / {_fmt_pct(max_month)}.",
        f"8. **Enough trades?** {gates['HOLDOUT_SAMPLE_SIZE_ADEQUATE']}; the pre-registered minimum is {VIABILITY_CONTRACT['holdout_minimum_completed_trades']}.",
        f"9. **Stable discovery → validation → holdout?** Discovery/validation/holdout expectancy was {_fmt_pct(discovery['net_expectancy'])} / {_fmt_pct(validation['net_expectancy'])} / {_fmt_pct(holdout['net_expectancy'])}; PF was {_fmt_num(discovery['realized_profit_factor'])} / {_fmt_num(validation['realized_profit_factor'])} / {_fmt_num(holdout['realized_profit_factor'])}.",
        f"10. **Legitimate baseline for a later V3 soft-overlay test?** {gates['SAFE_TO_RETEST_V3_AS_SOFT_OVERLAY']}.",
    ]
    gate_lines = [f"`{key}: {value}`" for key, value in gates.items()]
    selected_row = selection[selection["selected_primary"]].iloc[0]
    return f"""# V12 Price-Only Swing Carrier Viability Study

## Decision

The discovery-only procedure froze **{primary}** before validation or holdout construction. Its final classification is **{primary_class['classification']}**. {'A robust price-only carrier was found.' if viable else 'A robust price-only carrier was not established, so chip-overlay retesting remains gated.'}

This is a research-only result on the frozen 500-symbol research scope. It neither modifies production strategy code nor authorizes the 3,941-symbol build.

## Frozen provenance and protocol

- Frozen candidate artifact: `{EXPECTED_CANDIDATE_SHA256}` (47,518 symbol-days, 5,671 deterministic episodes, 494 represented symbols).
- Registered daily PIT price/execution artifact: `{EXPECTED_DAILY_SHA256}`.
- The reconstructed corporate-action analysis coordinate matched every frozen candidate close exactly.
- No chip or temporal feature artifact was opened. Those data had no role in candidates, carrier choice, entry, size, holding, exit, or portfolio priority.
- Discovery ends 2020-04-30; validation is 2020-05-01 through 2020-08-31; holdout is 2020-09-01 through 2020-12-31. Open trades are terminal-marked at each split boundary and are not counted as completed trades.
- The carrier family, costs, risk rules, portfolio rules, selection rule, viability gates, and diagnostic sensitivities were serialized before discovery evaluation. Validation and holdout trades were built only after `primary_carrier_freeze.json` was written.

## Pre-registered carriers and execution

The three conceptually distinct carriers are MA5 pullback reclaim, prior-three-high local breakout, and medium-trend resumption. Each has a five-session signal expiry, then at most three source sessions for a legal buy open. Signals use closing-bar information; intents are scheduled for a subsequent session; fills occur only at legal opens. Suspensions, invalid observations, and exchange limit blocks fail closed.

All use a 2×ATR14 close-based hard-risk threshold, next-legal-open exits, MA10 ordinary trend exit, 2R/MA5 profit protection, and a 20-session maximum hold. Diagnostic 1.5× and 2.5× ATR runs were pre-registered. Base round-trip costs comprise 3 bps commission and 0.2 bps transfer fee on each side, 10 bps sell stamp duty, and 5 bps slippage on each side; the stressed case raises commission to 5 bps and slippage to 10 bps.

The portfolio starts at 1.0, has ten equal-weight 10% slots, no leverage, no same-symbol overlap, exits before same-open entries, and uses deterministic future-independent priority.

## Discovery freeze

The rule first requires positive discovery trade and portfolio economics, no worse than 25% drawdown, stressed-cost positivity, positive expectancy at both ATR diagnostics, and at least 75 completed trades. It ranks by the worst PF across those discovery diagnostics—not headline return. The selected worst-case discovery PF was {_fmt_num(selected_row['minimum_discovery_pf_across_diagnostics'])}; fallback selection was {'used' if selected_row['fallback_used'] else 'not used'}.

## Canonical carrier results

{chr(10).join(table_lines)}

Completed-trade metrics exclude terminal-open trades. Portfolio net return includes terminal marking; the separate realized-versus-terminal table identifies endpoint dependence. Exact funnels, costs, holding distributions, MFE/MAE, giveback, winner-tail exclusions, per-symbol contributions, regimes, and price-only winner/loser attribution are in the machine-readable outputs.

### PF / portfolio reconciliation

{reconciliation}

The primary carrier's holdout hard-risk sensitivity was: {risk_text}. The negative sign persisted across the complete pre-registered 1.5×–2.5× ATR range, so the viability conclusion is not an artifact of the primary 2× choice.

## Classification

{chr(10).join(classification_lines)}

## Required answers

{chr(10).join(answers)}

## Failure diagnosis / next research gate

{'The carrier passes the pre-registered gate. Freeze this exact price-only specification before any later PRICE ONLY versus PRICE + V3 SOFT RISK OVERLAY study; that comparison is outside this task.' if viable else 'Failure is best classified as **market/regime dependency with unresolved exit/holding design**, not primarily transaction costs: all three entry families were positive on validation but negative on holdout completed trades, and the primary remained negative even at zero costs and across all pre-registered ATR rules. This does not prove the frozen candidate architecture is useless. The evidence does not justify chip filters, broad parameter search, production implementation, or full-market expansion. The smallest next question is whether one independently specified exit/holding architecture can improve MFE capture without changing the frozen candidates or entry family; that question must be separately pre-registered.'}

## Hard gates

{chr(10).join(gate_lines)}
"""


def write_json(value: Any, path: Path) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, float_format="%.12g", lineterminator="\n")


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    table = pa.Table.from_pandas(frame.reset_index(drop=True), preserve_index=False)
    pq.write_table(table, path, compression="zstd", use_dictionary=False, write_statistics=True, version="2.6")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    evidence = verify_inputs()
    candidate = load_candidates()
    panel = load_price_panel(candidate)
    episodes = episode_table(candidate, panel)
    shutil.copyfile(SOURCE_CANDIDATES, OUTPUT_DIR / "frozen_candidate_universe.parquet")
    definitions = {
        "study": "V12_PRICE_ONLY_SWING_CARRIER_VIABILITY_STUDY",
        "candidate": {"name": "P_PRICE_PULLBACK_20", "artifact_sha256": EXPECTED_CANDIDATE_SHA256, "unchanged": True},
        "carriers": CARRIER_DEFINITIONS,
        "risk_contract": RISK_CONTRACT,
        "cost_scenarios": COST_SCENARIOS,
        "portfolio_contract": PORTFOLIO_CONTRACT,
        "selection_contract": SELECTION_CONTRACT,
        "viability_contract": VIABILITY_CONTRACT,
        "chronological_splits": {name: [str(bounds[0].date()), str(bounds[1].date())] for name, bounds in SPLIT_BOUNDS.items()},
        "chip_data_used": False,
    }
    definitions_path = OUTPUT_DIR / "carrier_definitions.json"
    write_json(definitions, definitions_path)
    definitions_sha_before_discovery = sha256(definitions_path)

    base_cost = CostModel.named("BASE")
    main_parts: list[pd.DataFrame] = []
    discovery_risk_parts: dict[float, list[pd.DataFrame]] = {1.5: [], 2.5: []}
    for carrier in CARRIER_DEFINITIONS:
        main_parts.append(build_carrier_period_trades(panel, episodes, carrier, "discovery", 2.0, base_cost))
        for multiple in discovery_risk_parts:
            discovery_risk_parts[multiple].append(build_carrier_period_trades(panel, episodes, carrier, "discovery", multiple, base_cost))
    discovery_main = pd.concat(main_parts, ignore_index=True)
    discovery_trade_metrics = pd.DataFrame([trade_metrics(discovery_main, carrier, "discovery") for carrier in CARRIER_DEFINITIONS])
    discovery_portfolio_rows = []
    for carrier in CARRIER_DEFINITIONS:
        subset = discovery_main[discovery_main["carrier"].eq(carrier)]
        gross_curve, _, _ = simulate_portfolio(subset, panel, "discovery", CostModel.named("ZERO"))
        net_curve, admissions, _ = simulate_portfolio(subset, panel, "discovery", base_cost)
        discovery_portfolio_rows.append(portfolio_metrics(carrier, "discovery", gross_curve, net_curve, admissions))
    discovery_portfolio = pd.DataFrame(discovery_portfolio_rows)
    discovery_risk_frames = {multiple: pd.concat(parts, ignore_index=True) for multiple, parts in discovery_risk_parts.items()}
    discovery_risk = pd.DataFrame([
        {"atr_multiple": multiple, "carrier": carrier, "split": "discovery", **{key: value for key, value in trade_metrics(frame, carrier, "discovery").items() if key in ("completed_trades", "net_expectancy", "realized_profit_factor", "net_realized_trade_sum")}}
        for multiple, frame in discovery_risk_frames.items() for carrier in CARRIER_DEFINITIONS
    ])
    discovery_cost_rows = []
    for scenario in COST_SCENARIOS:
        costs = CostModel.named(scenario)
        adjusted = discovery_main.copy()
        mask = adjusted["actual_fill"].fillna(False)
        recalculated = [trade_return(float(row.actual_entry_analysis_mid), float(row.exit_analysis_mid_or_terminal_close), bool(row.completed), costs) for row in adjusted.loc[mask].itertuples(index=False)]
        if recalculated:
            adjusted.loc[mask, ["gross_return", "net_return", "transaction_cost_return"]] = np.asarray(recalculated)
        for carrier in CARRIER_DEFINITIONS:
            tm = trade_metrics(adjusted, carrier, "discovery")
            subset = adjusted[adjusted["carrier"].eq(carrier)]
            curve, admissions, _ = simulate_portfolio(subset, panel, "discovery", costs)
            pm = portfolio_metrics(carrier, "discovery", curve, curve, admissions)
            discovery_cost_rows.append({"cost_scenario": scenario, "carrier": carrier, "split": "discovery", "completed_trades": tm["completed_trades"], "net_expectancy": tm["net_expectancy"], "realized_profit_factor": tm["realized_profit_factor"], "net_trade_sum": tm["net_realized_trade_sum"], "net_portfolio_return": pm["net_total_return"], "transaction_costs": pm["transaction_costs"]})
    discovery_costs = pd.DataFrame(discovery_cost_rows)
    primary, selection = select_primary(discovery_trade_metrics, discovery_portfolio, discovery_costs, discovery_risk)
    freeze_path = OUTPUT_DIR / "primary_carrier_freeze.json"
    write_json({"primary_carrier": primary, "frozen_after_population": "discovery only", "carrier_definitions_sha256": definitions_sha_before_discovery, "selection_contract": SELECTION_CONTRACT, "selection_comparison": selection.to_dict(orient="records"), "validation_evaluated_before_freeze": False, "holdout_evaluated_before_freeze": False}, freeze_path)
    freeze_sha_before_evaluation = sha256(freeze_path)

    # Only after the primary freeze exists do validation and holdout get constructed.
    for split in ("validation", "holdout"):
        for carrier in CARRIER_DEFINITIONS:
            main_parts.append(build_carrier_period_trades(panel, episodes, carrier, split, 2.0, base_cost))
    main_trades = pd.concat(main_parts, ignore_index=True).sort_values(["carrier", "split", "candidate_date", "symbol", "candidate_episode_id"]).reset_index(drop=True)
    risk_frames: dict[float, pd.DataFrame] = {2.0: main_trades}
    for multiple in (1.5, 2.5):
        parts = [discovery_risk_frames[multiple]]
        for split in ("validation", "holdout"):
            for carrier in CARRIER_DEFINITIONS:
                parts.append(build_carrier_period_trades(panel, episodes, carrier, split, multiple, base_cost))
        risk_frames[multiple] = pd.concat(parts, ignore_index=True)

    trade = pd.DataFrame([trade_metrics(main_trades, carrier, split) for carrier in CARRIER_DEFINITIONS for split in SPLITS])
    portfolio, mtm, admissions = evaluate_portfolios(main_trades, panel, "BASE")
    tails = winner_tail(main_trades)
    symbol_contribution, symbol_summary = symbol_outputs(main_trades)
    monthly = monthly_concentration(main_trades)
    candidate_start_lookup = panel.set_index(["symbol", "feature_date"])
    discovery_volatility = [float(candidate_start_lookup.loc[(row.symbol, row.candidate_date), "atr14"] / candidate_start_lookup.loc[(row.symbol, row.candidate_date), "analysis_close"]) for row in episodes[episodes["split"].eq("discovery")].itertuples(index=False)]
    discovery_volatility_median = float(pd.Series(discovery_volatility).dropna().median())
    regimes = regime_robustness(main_trades, discovery_volatility_median)
    attribution = price_attribution(main_trades)
    funnel = entry_funnel(main_trades)
    costs = cost_sensitivity(main_trades, panel)
    risk = risk_sensitivity(risk_frames)
    classification = classification_table(trade, portfolio, mtm, costs, tails, symbol_summary, primary)
    period = canonical_period_table(trade, portfolio, mtm, tails, symbol_summary)
    gates = hard_gates(primary, classification, trade, portfolio, mtm, costs)

    write_parquet(main_trades, OUTPUT_DIR / "carrier_trade_results.parquet")
    outputs = {
        "carrier_period_metrics.csv": period,
        "carrier_trade_metrics.csv": trade,
        "carrier_portfolio_metrics.csv": portfolio,
        "realized_vs_terminal_mtm.csv": mtm,
        "winner_tail_concentration.csv": tails,
        "symbol_contribution.csv": symbol_contribution,
        "symbol_robustness_summary.csv": symbol_summary,
        "monthly_concentration.csv": monthly,
        "regime_robustness.csv": regimes,
        "transaction_cost_sensitivity.csv": costs,
        "risk_rule_sensitivity.csv": risk,
        "entry_conversion_funnel.csv": funnel,
        "price_only_trade_attribution.csv": attribution,
        "portfolio_admissions.csv": admissions,
        "discovery_selection.csv": selection,
        "carrier_classification.csv": classification,
    }
    for name, frame in outputs.items():
        write_csv(frame, OUTPUT_DIR / name)
    REPORT_PATH.write_text(render_report(primary, selection, period, classification, gates, symbol_summary, monthly, risk), encoding="utf-8")
    if sha256(definitions_path) != definitions_sha_before_discovery or sha256(freeze_path) != freeze_sha_before_evaluation:
        raise RuntimeError("pre-registration or primary freeze changed during evaluation")
    artifact_paths = [definitions_path, freeze_path, OUTPUT_DIR / "frozen_candidate_universe.parquet", OUTPUT_DIR / "carrier_trade_results.parquet", *[OUTPUT_DIR / name for name in outputs], REPORT_PATH]
    manifest = {
        "study": "V12_PRICE_ONLY_SWING_CARRIER_VIABILITY_STUDY",
        "input_evidence": evidence,
        "carrier_definitions_sha256_before_discovery": definitions_sha_before_discovery,
        "primary_freeze_sha256_before_validation_holdout": freeze_sha_before_evaluation,
        "primary_carrier": primary,
        "counts": {"candidate_symbol_days": len(candidate), "candidate_episodes": len(episodes), "candidate_symbols": candidate["symbol"].nunique(), "trade_result_episode_rows": len(main_trades)},
        "discovery_reporting_volatility_median": discovery_volatility_median,
        "hard_gates": gates,
        "artifacts": {str(path.relative_to(STUDY_DIR if path == REPORT_PATH else OUTPUT_DIR)): {"sha256": sha256(path), "bytes": path.stat().st_size} for path in artifact_paths},
        "determinism": {"sort_keys": True, "parquet_compression": "zstd", "parquet_dictionary": False, "csv_float_format": "%.12g"},
    }
    write_json(manifest, OUTPUT_DIR / "result_manifest.json")


if __name__ == "__main__":
    main()
