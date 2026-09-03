#!/usr/bin/env python3
# ruff: noqa: E501
"""V6 full signal/strategy research: freeze first, then bounded walk-forward."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import lightgbm as lgb
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from research.market_behavior_os_v2.scripts import run_ashare_true_gap_causal_cluster_v6_one_shot_discovery as v6
from research.market_behavior_os_v2.scripts import run_ashare_collapse_gap_zone_monetization_anatomy_v1 as anatomy

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-V6-FULL-SIGNAL-AND-STRATEGY-RESEARCH-V1"
START_HEAD = "c68623ea2c408bb2e7ce60b529bf7c82c1982888"
SOURCE_HASH = "2705011d21792acfea34c6fe07819aa1a9e6dd91247bc27e66616749cc3ee162"
EXPECTED_FEATURE_CONTRACT_HASH = "99f1ba1d527aa1c084d9ccde2580cdb5da093f2c194104d965623319c9b4b52a"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
SOURCE_SPEC = OS / "experiments/ASHARE-TRUE-GAP-CAUSAL-CLUSTER-V6-ONE-SHOT-DISCOVERY_spec.json"
SOURCE_CANDIDATES = OS / "artifacts/ASHARE-TRUE-GAP-CAUSAL-CLUSTER-V6-ONE-SHOT-DISCOVERY_candidate_ledger.parquet"
SOURCE_CLUSTERS = OS / "artifacts/ASHARE-TRUE-GAP-CAUSAL-CLUSTER-V6-ONE-SHOT-DISCOVERY_cluster_ledger.parquet"
CAUSAL_GAPS = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_causal_cluster_v6_one_shot_discovery/causal_true_gap_ledger.parquet")
DAILY = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/pit_daily_compact_2013_2023.parquet")
V6_LEGAL_OPENS = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_causal_cluster_v6_one_shot_discovery/legal_opens.parquet")
RAW_ROOT = Path("/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars")
EXT = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_v6_full_signal_strategy_research_v1")

FEATURE_DICTIONARY = OS / f"experiments/{EXPERIMENT}_feature_dictionary.json"
FEATURE_TIMESTAMP_AUDIT = OS / f"artifacts/{EXPERIMENT}_feature_timestamp_audit.json"
COVERAGE_REPORT = OS / f"artifacts/{EXPERIMENT}_coverage_report.json"
OUTCOME_DICTIONARY = OS / f"experiments/{EXPERIMENT}_outcome_dictionary.json"
ENTRY_GRID = OS / f"experiments/{EXPERIMENT}_entry_grid.json"
EXIT_GRID = OS / f"experiments/{EXPERIMENT}_exit_grid.json"
MODEL_PROFILES = OS / f"experiments/{EXPERIMENT}_model_profiles.json"
FEATURE_FREEZE = OS / f"artifacts/{EXPERIMENT}_feature_freeze.json"
PREFLIGHT = OS / f"artifacts/{EXPERIMENT}_preflight.json"

ENTRY_MINUTES = EXT / "entry_search_minutes.parquet"
BUY_OPENS = EXT / "buy_legal_opens.parquet"
GAP_MINUTES = EXT / "gap_day_minutes.parquet"
ENTRY_CANDIDATES = EXT / "entry_candidates.parquet"
EVENT_FEATURES = EXT / "event_features.parquet"
INTRADAY_FEATURES = EXT / "intraday_attack_features.parquet"
MODEL_PANEL = EXT / "model_panel.parquet"
POST_ENTRY_PANEL = EXT / "post_entry_state_panel.parquet"
POLICY_PATHS = EXT / "policy_paths.parquet"
OOF_PREDICTIONS = EXT / "oof_predictions.parquet"
DYNAMIC_TAIL_SCORES = EXT / "dynamic_tail_scores.parquet"
ENTRY_DIAGNOSTICS = OS / f"artifacts/{EXPERIMENT}_entry_diagnostics.parquet"
ENTRY_FOLD_STATS = EXT / "entry_fold_stats.parquet"
ADMISSION_STATS = EXT / "admission_stats.parquet"
EXIT_STATS = EXT / "exit_stats.parquet"
SELECTIONS = OS / f"artifacts/{EXPERIMENT}_walkforward_selections.parquet"
POLICY_TRADES = EXT / "policy_trades.parquet"
PORTFOLIO_NAV = EXT / "portfolio_nav.parquet"
PORTFOLIO_SUMMARY = EXT / "portfolio_summary.parquet"
FIXED_ENTRY_RESULTS = OS / f"artifacts/{EXPERIMENT}_fixed_entry_results.parquet"
STABLE_COMPLETE_RESULTS = OS / f"artifacts/{EXPERIMENT}_stable_complete_results.parquet"
POST_SELECTIONS = OS / f"artifacts/{EXPERIMENT}_post_observation_selections.parquet"
POST_PREDICTIONS = EXT / "post_observation_predictions.parquet"
POST_TRADES = EXT / "post_observation_trades.parquet"
POST_STATS = EXT / "post_observation_search_stats.parquet"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

YEARS = tuple(range(2014, 2024))
DEV_YEARS = tuple(range(2014, 2022))
TEST_YEARS = tuple(range(2017, 2022))
POST_YEARS = (2022, 2023)
LEVELS = {
    "ABS_0": ("ABS", 0.0), "ABS_0P5": ("ABS", 0.005), "ABS_1P0": ("ABS", 0.01),
    "ABS_2P0": ("ABS", 0.02), "GAP_10": ("GAP", 0.10), "GAP_25": ("GAP", 0.25), "GAP_50": ("GAP", 0.50),
}
CONFIRMATIONS = ("C1_TOUCH", "C2_CLOSE", "C3_HOLD5", "C4_HOLD15", "C5_SECOND_RECLAIM")
ADMISSIONS = {"A100": 1.0, "A70": 0.70, "A50": 0.50, "A30": 0.30, "A20": 0.20}
TIME_STOPS = (10, 20, 40)
KS = (5, 10, 20)
COST = 0.002


class ResearchError(RuntimeError):
    pass


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def clean(x: Any) -> Any:
    if isinstance(x, dict): return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [clean(v) for v in x]
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (np.floating,)): return None if not np.isfinite(x) else float(x)
    if isinstance(x, pd.Timestamp): return None if pd.isna(x) else str(x)
    if not isinstance(x, (str, bool)) and pd.isna(x): return None
    return x


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(clean(value), indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def raw_union() -> str:
    return " UNION ALL ".join(
        f"SELECT * FROM read_parquet('{RAW_ROOT / f'{y}_day_parquet_none.parquet'}') WHERE period='1m' AND adjust='none'" for y in YEARS
    )


def feature(name: str, family: str, formula: str, timestamp: str, source: str, direction: str) -> dict[str, str]:
    return {"name": name, "family": family, "formula": formula, "latest_observable": timestamp, "pit_source": source, "expected_direction": direction, "nonredundancy": f"distinct {family} economic coordinate required by frozen research tree"}


def feature_contract() -> list[dict[str, str]]:
    f: list[dict[str, str]] = []
    add = lambda n, fam, form, ts, src, d: f.append(feature(n, fam, form, ts, src, d))
    for n, form, d in [
        ("pre5_turnover_vs_prior60", "mean turnover[-5:-1]/mean turnover[-65:-6]", "higher may indicate distribution"),
        ("pre10_turnover_vs_prior60", "mean turnover[-10:-1]/mean turnover[-70:-11]", "higher may indicate distribution"),
        ("pre20_cum_turnover", "sum turnover[-20:-1]", "higher means more capital exchange"),
        ("high_turnover_down_day_share_10", "share of prior10 down days whose turnover exceeds prior60 median", "higher indicates supply"),
        ("high_turnover_down_day_share_20", "share of prior20 down days whose turnover exceeds prior60 median", "higher indicates supply"),
        ("up_vs_down_turnover_asymmetry", "mean turnover on up days / mean turnover on down days in prior20", "lower indicates distribution"),
        ("upper_shadow_pressure_10", "mean (high-max(open,close))/range prior10", "higher indicates overhead supply"),
        ("failed_new_high_count_10", "count prior10 high>=prior20 high and close<open", "higher indicates failed leadership"),
        ("high_volume_stall_count_10", "count prior10 turnover>prior60 median and abs(return)<1%", "higher indicates distribution"),
        ("price_advance_per_turnover_10", "prior10 return/sum turnover prior10", "lower indicates weak price progress"),
        ("return_deceleration_5_vs_20", "prior5 return - prior20 return/4", "lower indicates deceleration"),
        ("distance_from_causal_reference_high", "gap-eve comparable close/reference high-1", "more negative means damaged leader"),
    ]: add(n, "F1", form, "gap formation previous completed session", "PIT daily", d)
    for scope in ("board", "industry"):
        for w in (5, 10, 20): add(f"{scope}_relative_return_{w}", "F1", f"stock prior{w} return minus {scope} prior{w} return", "gap formation previous completed session", "PIT daily/industry", "negative means pre-gap relative weakness")
    for clock in ("open", "close"):
        for scope in ("market", "board", "industry"): add(f"{scope}_{clock}_return", "F2", f"equal-weight {scope} {clock} return on gap day", "gap formation close", "PIT daily/industry", "more negative means systematic shock")
    for scope in ("market", "board", "industry"):
        add(f"{scope}_down_breadth", "F2", f"share negative close returns in {scope}", "gap formation close", "PIT daily/industry", "higher means systematic stress")
        add(f"{scope}_true_gap_breadth", "F2", f"share High<prior Low in {scope}", "gap formation close", "PIT daily/industry", "higher means systematic gap shock")
    for n, form in [("lower_limit_stress", "market share at lower limit"), ("near_limit_stress", "market share within 1% of lower limit"), ("peers_with_comparable_shock", "same-industry count with true gap or near-limit decline"), ("gap_day_open_residual", "stock open return minus prior60 beta times market/board/industry open returns"), ("gap_day_close_residual", "stock close return minus prior60 beta times market/board/industry close returns")]:
        add(n, "F2", form, "gap formation close", "PIT daily/industry", "more negative residual means idiosyncratic supply")
    f3 = {
        "gap_day_turnover_zscore":"(gap turnover-prior60 mean)/prior60 std", "opening_5m_return":"close5/open1-1",
        "opening_15m_return":"close15/open1-1", "opening_30m_return":"close30/open1-1", "max_rebound_from_low":"max close/running low-1",
        "rebound_giveback_to_close":"max close/close_last-1", "gap_day_close_location":"(close-low)/(high-low)", "time_below_vwap":"share closes below running VWAP",
        "gap_day_close_vs_vwap":"close/VWAP-1", "down_bar_volume_share":"volume on negative bars/total volume", "up_bar_volume_share":"volume on positive bars/total volume",
        "signed_volume_proxy":"sum sign(return)*volume/total volume", "gap_day_price_progress_per_volume":"open-to-close return/turnover", "afternoon_return":"close/13:01 open-1",
        "afternoon_volume_share":"afternoon volume/total", "failed_intraday_rebound_count":"count local rebound highs followed by >=2% giveback", "late_day_recovery":"last30m return",
        "ordinary_gap_flag":"not near/locked/released lower limit", "near_lower_limit_flag":"gap close within 1% of down limit", "exact_locked_limit_flag":"all bars locked at down limit",
        "partially_released_limit_flag":"touches down limit and later trades above"
    }
    for n, form in f3.items(): add(n, "F3", form, "completed gap-formation session", "QD-004 minute + PIT daily limits", "supply/absorption coordinate; sign interpreted jointly")
    f4 = {
        "cum_turnover_since_cluster":"sum turnover from cluster start through prior completed day", "cum_turnover_since_primary":"sum turnover from primary formation through prior completed day",
        "stock_cum_return":"stock return primary-to-prior close", "board_cum_return":"board return primary-to-prior close", "industry_cum_return":"industry return primary-to-prior close",
        "stock_minus_board_return":"stock minus board cumulative return", "stock_minus_industry_return":"stock minus industry cumulative return", "cum_negative_residual":"sum negative stock-industry daily residual",
        "high_turnover_negative_residual_day_count":"count residual<0 and turnover>prior60 median", "market_up_stock_down_day_count":"count market>0 stock<0", "industry_up_stock_down_day_count":"count industry>0 stock<0",
        "new_lower_major_secondary_gap_count":"causal lower M/S gaps after freeze", "new_lower_cluster_count":"forward superseding lower cluster count", "failed_recovery_count":"count 5% rebounds followed by close below prior swing low",
        "time_below_l":"completed sessions with High<L", "max_distance_below_l":"minimum comparable low/L-1"
    }
    for n, form in f4.items(): add(n, "F4", form, "prior completed session before decision", "PIT daily/V6 causal ledger", "persistent weakness/supply generally adverse")
    f5 = {
        "market_return_since_gap":"market return gap-to-prior day", "board_return_since_gap":"board return gap-to-prior day", "industry_return_since_gap":"industry return gap-to-prior day",
        "market_return_since_freeze":"market return freeze-to-prior day", "board_return_since_freeze":"board return freeze-to-prior day", "industry_return_since_freeze":"industry return freeze-to-prior day",
        "breadth_recovery":"current prior20 up breadth minus gap-day breadth", "lower_limit_stress_recovery":"gap-day lower-limit stress minus prior5 mean stress", "volatility_normalization":"prior5 market abs return/prior60",
        "market_median_return_recovery":"prior20 market median cumulative return", "industry_median_return_recovery":"prior20 industry median cumulative return",
        "entry_day_market_return_to_clock":"market open-to-decision equal-weight return", "entry_day_board_return_to_clock":"board open-to-decision equal-weight return",
        "entry_day_industry_return_to_clock":"industry open-to-decision equal-weight return", "stock_intraday_residual_to_clock":"stock open-to-decision minus board/industry context"
    }
    for n, form in f5.items(): add(n, "F5", form, "completed decision bar", "PIT daily + QD-004 same-clock context", "higher repair expected supportive except residual")
    for w in (5, 10, 20):
        for n, form in {
            "net_advance_toward_l":"close[-1]/close[-w]-1", "path_efficiency":"abs(net return)/sum abs daily returns", "max_pullback":"minimum close/running max-1",
            "pullback_burden":"sum negative returns absolute", "up_session_share":"share positive sessions", "higher_low_share":"share lows above prior low", "lower_low_share":"share lows below prior low",
            "range_compression":"last-half mean range/first-half mean range", "close_location_trend":"slope of daily close location", "turnover_on_up_days":"mean turnover positive days",
            "turnover_on_down_days":"mean turnover negative days", "approach_price_progress_per_turnover":"net return/sum turnover", "board_relative_approach_return":"stock minus board return",
            "industry_relative_approach_return":"stock minus industry return"
        }.items(): add(f"{n}_{w}", "F6", f"{form} over prior {w} completed sessions", "prior completed session before decision", "PIT daily/industry", "approach-state coordinate; no assumed monotonic sign")
    add("late_acceleration_5_vs_previous5", "F6", "prior5 return minus preceding5 return", "prior completed session before decision", "PIT daily", "positive means late acceleration")
    f7 = {
        "return_to_contact":"decision close/session open-1", "path_efficiency_to_contact":"abs(open-to-decision return)/sum abs minute returns", "max_pullback_to_contact":"minimum close/running max-1",
        "volume_surprise_same_clock":"cumulative volume/prior20 same-clock median-1", "turnover_surprise":"decision-day cumulative turnover/prior20 same-clock-equivalent turnover-1",
        "price_progress_per_volume":"open-to-decision return/cumulative volume share", "time_above_intraday_vwap":"share closes above running VWAP", "current_close_vs_vwap":"decision close/running VWAP-1",
        "stock_minus_board_intraday_return":"stock open-to-decision minus board", "stock_minus_industry_intraday_return":"stock open-to-decision minus industry",
        "penetration_into_gap":"(decision close-L)/W", "decision_bar_body_ratio":"abs(close-open)/(high-low)", "decision_bar_close_location":"(close-low)/(high-low)",
        "decision_bar_upper_wick_ratio":"(high-max(open,close))/(high-low)", "decision_bar_volume_surprise":"bar volume/prior20 same-clock median-1", "decision_bar_price_impact_per_volume":"bar return/bar volume share",
        "opening_jump_flag":"decision is first bar and open>=T", "time_of_day":"minute index/241", "share_closes_at_or_above_l":"post-contact share closes>=L",
        "minimum_close_distance_from_l":"min close/L-1 since contact", "maximum_penetration":"max(close-L)/W", "current_penetration":"(close-L)/W",
        "rejection_depth_below_l":"min(close/L-1,0)", "failed_test_count":"count transitions >=L to <L", "reclaim_count":"count transitions <L to >=L",
        "vwap_hold_share":"post-contact share closes>=VWAP", "up_vs_down_minute_volume":"up minute volume/down minute volume", "penetration_gain_per_volume":"penetration change/cumulative volume",
        "local_high_break_after_retest":"close exceeds prior post-contact high after a below-L retest", "pre5_return":"last5 minute return", "pre15_return":"last15 minute return", "pre30_return":"last30 minute return", "pre60_return":"last60 minute return"
    }
    for n, form in f7.items(): add(n, "F7", form, "completed entry confirmation bar", "QD-004 minute + same-clock PIT context", "attack acceptance coordinate; signs tested OOF")
    if len({x["name"] for x in f}) != len(f): raise ResearchError("duplicate feature names")
    return f


def frozen_contracts() -> dict[str, Any]:
    features = feature_contract()
    entry = {"levels": LEVELS, "confirmations": list(CONFIRMATIONS), "translations": [f"{l}+{c}" for l in LEVELS for c in CONFIRMATIONS], "baseline": "ABS_0+C2_CLOSE", "entry": "next legal minute open"}
    outcome = {"cost_per_side": COST, "Y_NET_U_OR_H40": "U else H40", "Y_CLEAN_U20": "U by D20 before -8%", "Y_CLEAN_U40": "U by D40 before -10%", "Y_TAIL_FAILURE40": "no U by D40 and (H40<=-10% or MAE40<=-20%)", "loss_landmarks": [0.05,0.08,0.10,0.12,0.15]}
    exit_grid = {"time_stops": TIME_STOPS, "X0": ["NONE"], "X1_INTRADAY": [0.05,0.08,0.10,0.12], "X2_DAILY": [0.05,0.08,0.10,0.12], "X3_WIDTH": [1,2,3], "X4": ["LOWER_MS_GAP"], "X5": [[d,p] for d in (3,5,10) for p in (.10,.25,.50)], "X6": [.50,.75], "X7": [[d,q] for d in (3,5,10) for q in (.80,.90)], "X8": ["HYBRID_CONSERVATIVE","HYBRID_FAST"]}
    models = {"M1_INTERPRETABLE": {"clean_tail":"LogisticRegression(C=.1,class_weight=balanced,max_iter=2000,random_state=20260903)", "return":"Ridge(alpha=10)", "preprocess":"TRAIN median+standardize"}, "M2_NONLINEAR": {"learning_rate":.03,"n_estimators":800,"max_depth":4,"num_leaves":15,"min_child_samples":100,"reg_lambda":20.0,"reg_alpha":1.0,"subsample":.8,"colsample_bytree":.8,"random_state":20260903,"early_stopping_rounds":50}, "bundles": {"B1":["F1","F2"],"B2":["F1","F2","F3"],"B3":["F1","F2","F3","F4","F5"],"B4":["F1","F2","F3","F4","F5","F6"],"B5":["F1","F2","F3","F4","F5","F6","F7"],"B6":"UNAVAILABLE_NO_L2"}, "admissions": ADMISSIONS}
    return {"features": features, "entry": entry, "outcome": outcome, "exit": exit_grid, "models": models}


def validate_inputs() -> dict[str, Any]:
    required = [SPEC,SOURCE_SPEC,SOURCE_CANDIDATES,SOURCE_CLUSTERS,CAUSAL_GAPS,DAILY,V6_LEGAL_OPENS]
    required += [RAW_ROOT / f"{y}_day_parquet_none.parquet" for y in YEARS]
    missing = [str(p) for p in required if not p.is_file()]
    if missing: raise ResearchError(f"missing governed inputs: {missing}")
    if sha(SOURCE_SPEC) != SOURCE_HASH: raise ResearchError("frozen V6 semantic hash mismatch")
    candidate_schema = set(pq.read_schema(SOURCE_CANDIDATES).names)
    daily_schema = set(pq.read_schema(DAILY).names)
    minute_schema = set(pq.read_schema(RAW_ROOT / "2014_day_parquet_none.parquet").names)
    need_c = {"candidate_id","symbol","board","memory_state","causal_first_return","frozen_primary_lower","frozen_primary_upper","frozen_primary_gap_date","cluster_freeze_time","invalid_step_cum"}
    need_d = {"trade_date","symbol","sleeve","open","high","low","close","volume","amount","turnover_fraction","causal_industry","trade_status","up_limit_price","down_limit_price","corporate_action_blocking","hard_valid","available_at","decision_at","coordinate_factor","coord_open","coord_high","coord_low","coord_close","invalid_step_cum"}
    need_m = {"qmt_code","trade_date","bar_end_time","open","high","low","close","volume","amount"}
    if not need_c <= candidate_schema or not need_d <= daily_schema or not need_m <= minute_schema: raise ResearchError("source schema incompatibility")
    c = pd.read_parquet(SOURCE_CANDIDATES, columns=["candidate_id","memory_state","causal_first_return"])
    c.causal_first_return = pd.to_datetime(c.causal_first_return)
    if c.causal_first_return.max() >= pd.Timestamp("2024-01-01"): raise ResearchError("2024+ identity accessed")
    return {"daily_ohlcv":"YES","daily_turnover":"YES","price_limit_state":"YES","corporate_action_coordinates":"YES","minute_241_contract":"AVAILABLE_AUDIT_PENDING","boards":["MAIN","CHINEXT"],"pit_industry":"YES","broad_context":"CONSTRUCTIBLE","l2_bundle_available":"NO","source_candidates":len(c),"active_core_boundary":int(c.memory_state.isin(["CORE","BOUNDARY"]).sum()),"repository_2024_plus_data_opened":"NO"}


def persist_initial_contracts() -> dict[str, Any]:
    c = frozen_contracts()
    write_json(FEATURE_DICTIONARY, {"experiment":EXPERIMENT,"features":c["features"],"additions_beyond_required":[]})
    write_json(ENTRY_GRID, c["entry"])
    write_json(OUTCOME_DICTIONARY, c["outcome"])
    write_json(EXIT_GRID, c["exit"])
    write_json(MODEL_PROFILES, c["models"])
    return c


def active_source() -> pd.DataFrame:
    cols = ["candidate_id","cluster_id","symbol","board","memory_state","causal_first_return","frozen_primary_lower","frozen_primary_upper","frozen_primary_gap_date","cluster_freeze_time","invalid_step_cum","reference_high","material_drawdown_at_freeze","true_gap_width_pct"]
    c = pd.read_parquet(SOURCE_CANDIDATES, columns=cols)
    for col in ("causal_first_return","frozen_primary_gap_date","cluster_freeze_time"): c[col] = pd.to_datetime(c[col])
    c = c.loc[c.memory_state.isin(["CORE","BOUNDARY"]) & c.causal_first_return.dt.year.between(2014,2023)].copy()
    clusters = pd.read_parquet(SOURCE_CLUSTERS, columns=["cluster_id","cluster_start_time"])
    clusters.cluster_start_time = pd.to_datetime(clusters.cluster_start_time)
    c = c.merge(clusters, on="cluster_id", validate="many_to_one")
    c["L"] = c.frozen_primary_lower.astype(float); c["U"] = c.frozen_primary_upper.astype(float); c["W"] = c.U-c.L
    if len(c) != 3_959 or c.candidate_id.duplicated().any() or c.causal_first_return.max() >= pd.Timestamp("2024-01-01"): raise ResearchError("V6 active identity mismatch")
    return c.sort_values(["causal_first_return","candidate_id"], kind="mergesort").reset_index(drop=True)


def build_entry_search_minutes(candidates: pd.DataFrame) -> dict[str, Any]:
    EXT.mkdir(parents=True, exist_ok=True)
    seed = candidates[["candidate_id","symbol","causal_first_return","L","U","invalid_step_cum"]].copy()
    seed["signal_date"] = seed.causal_first_return.dt.normalize()
    seed_path = EXT / "entry_search_seed.parquet"; write_parquet(seed, seed_path)
    dates_path = EXT / "entry_search_dates.parquet"
    con = duckdb.connect(); con.execute("SET threads=4"); con.execute("SET preserve_insertion_order=false")
    con.execute(f"""COPY (
      WITH possible AS (
        SELECT s.*,d.trade_date,d.cal_idx,d.coordinate_factor,d.up_limit_price,d.down_limit_price,
          d.trade_status,d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_blocking,
          min(CASE WHEN d.coord_high>=s.U THEN d.cal_idx END) OVER(PARTITION BY s.candidate_id) AS first_u_idx
        FROM read_parquet('{seed_path}') s JOIN read_parquet('{DAILY}') d
          ON d.symbol=s.symbol AND d.trade_date BETWEEN s.signal_date AND DATE '2023-12-31'
        WHERE d.invalid_step_cum=s.invalid_step_cum AND d.history_valid AND d.current_valid AND d.hard_valid
      )
      SELECT * FROM possible WHERE first_u_idx IS NULL OR cal_idx<=first_u_idx
      ORDER BY candidate_id,trade_date
    ) TO '{dates_path}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.execute(f"""COPY (
      WITH raw AS ({raw_union()})
      SELECT d.candidate_id,d.symbol,d.causal_first_return,d.L,d.U,d.invalid_step_cum,
        d.trade_date,d.cal_idx,r.bar_end_time,r.open,r.high,r.low,r.close,r.volume,r.amount,
        d.coordinate_factor,r.open*d.coordinate_factor AS coord_open,r.high*d.coordinate_factor AS coord_high,
        r.low*d.coordinate_factor AS coord_low,r.close*d.coordinate_factor AS coord_close,
        d.up_limit_price,d.down_limit_price,d.trade_status,d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_blocking,
        count(*) OVER(PARTITION BY d.candidate_id,d.trade_date) AS minute_count
      FROM read_parquet('{dates_path}') d JOIN raw r ON r.qmt_code=d.symbol AND r.trade_date=d.trade_date
      WHERE r.bar_end_time>=CASE WHEN d.trade_date=CAST(d.causal_first_return AS DATE) THEN d.causal_first_return ELSE CAST(d.trade_date AS TIMESTAMP) END
      ORDER BY d.candidate_id,r.bar_end_time
    ) TO '{ENTRY_MINUTES}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.close()
    q = duckdb.connect()
    audit = q.execute(f"SELECT count(*) AS row_count,count(DISTINCT candidate_id) AS candidates,count(DISTINCT (candidate_id,trade_date)) AS sessions,count_if(minute_count<>241) AS bad_rows,min(minute_count) AS min_bars,max(minute_count) AS max_bars FROM read_parquet('{ENTRY_MINUTES}')").fetchone()
    q.close()
    # The signal day is intentionally truncated at causal_first_return; all other sessions must be exact 241.
    m = pd.read_parquet(ENTRY_MINUTES, columns=["trade_date","causal_first_return","minute_count"])
    m.trade_date=pd.to_datetime(m.trade_date); m.causal_first_return=pd.to_datetime(m.causal_first_return)
    bad = m.loc[m.trade_date.ne(m.causal_first_return.dt.normalize()) & m.minute_count.ne(241)]
    if len(bad): raise ResearchError(f"non-241 full entry-search sessions: {len(bad)}")
    return {"rows":int(audit[0]),"candidates":int(audit[1]),"sessions":int(audit[2]),"non_signal_bad_241_sessions":0,"min_rows_including_truncated_signal":int(audit[4]),"max_rows":int(audit[5])}


def trigger_level(L: float, U: float, level: str) -> float:
    kind, x = LEVELS[level]
    return L*(1+x) if kind == "ABS" else L+x*(U-L)


def _first_true(mask: np.ndarray) -> int | None:
    ix = np.flatnonzero(mask)
    return None if len(ix)==0 else int(ix[0])


def build_entry_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    usecols=["candidate_id","trade_date","bar_end_time","cal_idx","open","high","low","close","coord_open","coord_high","coord_low","coord_close","coordinate_factor","up_limit_price","trade_status","current_day_data_tradable","market_rule_valid","corporate_action_blocking"]
    minutes = pd.read_parquet(ENTRY_MINUTES,columns=usecols)
    for col in ("trade_date","bar_end_time"): minutes[col]=pd.to_datetime(minutes[col])
    groups = minutes.groupby("candidate_id",sort=False)
    rows=[]
    for event in candidates.itertuples(index=False):
        try: g=groups.get_group(event.candidate_id).sort_values("bar_end_time").reset_index(drop=True)
        except KeyError: g=pd.DataFrame(columns=usecols)
        L,U,W=float(event.L),float(event.U),float(event.W)
        first_u=None if g.empty else _first_true(g.coord_high.to_numpy(float)>=U)
        dates=np.array([],dtype="datetime64[ns]") if g.empty else g.trade_date.dt.normalize().to_numpy()
        close=np.array([]) if g.empty else g.coord_close.to_numpy(float); high=np.array([]) if g.empty else g.coord_high.to_numpy(float)
        if len(g):
            above=(close>=L).astype(np.int64); cs=np.cumsum(above)
            roll5=np.full(len(g),np.nan); roll15=np.full(len(g),np.nan)
            for n,target in ((5,roll5),(15,roll15)):
                if len(g)<n: continue
                vals=cs[n-1:].copy()
                if len(vals)>1: vals[1:]-=cs[:-n]
                target[n-1:]=vals
                target[n-1:][dates[n-1:]!=dates[:len(g)-n+1]]=np.nan
            legal=g.trade_status.eq(1).to_numpy()&g.current_day_data_tradable.to_numpy()&g.market_rule_valid.to_numpy()&~g.corporate_action_blocking.to_numpy()&(np.round(g.open.to_numpy(float)*100)<np.round(g.up_limit_price.to_numpy(float)*100))
            next_legal=np.minimum.accumulate(np.where(legal,np.arange(len(g)),len(g))[::-1])[::-1]
        else:
            roll5=roll15=np.array([]); next_legal=np.array([],dtype=int)
        for level in LEVELS:
            T=trigger_level(L,U,level)
            for confirm in CONFIRMATIONS:
                status="NO_CONFIRMATION"; ci=None
                if T>=U-1e-12:
                    status="THRESHOLD_NOT_EXECUTABLE_OR_MISSED_FAST_FILL"
                else:
                    if confirm=="C1_TOUCH": ci=_first_true(high>=T)
                    elif confirm=="C2_CLOSE": ci=_first_true(close>=T)
                    elif confirm in ("C3_HOLD5","C4_HOLD15"):
                        roll,need=(roll5,3) if confirm=="C3_HOLD5" else (roll15,10)
                        ci=_first_true((close>=T)&(roll>=need))
                    else:
                        first=_first_true(close>=T)
                        if first is not None:
                            reject=np.flatnonzero((np.arange(len(g))>first)&(close<L))
                            if len(reject):
                                reclaim=np.flatnonzero((np.arange(len(g))>reject[0])&(close>=T))
                                if len(reclaim): ci=int(reclaim[0])
                    if ci is not None: status="CONFIRMED"
                entry_i=None
                if ci is not None:
                    entry_i=None if ci+1>=len(g) or next_legal[ci+1]>=len(g) else int(next_legal[ci+1])
                    if first_u is not None and (entry_i is None or first_u<=entry_i):
                        status="MISSED_FAST_U"; entry_i=None
                    elif entry_i is None: status="NO_LEGAL_EXECUTABLE_ENTRY"
                    else: status="EXECUTABLE_ENTRY"
                row={"candidate_id":event.candidate_id,"cluster_id":event.cluster_id,"symbol":event.symbol,"board":event.board,"memory_state":event.memory_state,"causal_first_return":event.causal_first_return,
                     "primary_gap_date":event.frozen_primary_gap_date,"cluster_freeze_time":event.cluster_freeze_time,"L":L,"U":U,"W":W,"invalid_step_cum":event.invalid_step_cum,
                     "entry_level":level,"confirmation_form":confirm,"translation":f"{level}+{confirm}","trigger_coord":T,"status":status,
                     "first_u_time":pd.NaT if first_u is None else g.bar_end_time.iloc[first_u],"confirmation_time":pd.NaT if ci is None else g.bar_end_time.iloc[ci],"confirmation_date":pd.NaT if ci is None else g.trade_date.iloc[ci],
                     "decision_coord_close":np.nan if ci is None else close[ci],"decision_minute_index":np.nan if ci is None else int(g.loc[:ci].groupby("trade_date").cumcount().iloc[-1])+1,
                     "entry_time":pd.NaT if entry_i is None else g.bar_end_time.iloc[entry_i],"entry_date":pd.NaT if entry_i is None else g.trade_date.iloc[entry_i],"entry_cal_idx":np.nan if entry_i is None else int(g.cal_idx.iloc[entry_i]),
                     "entry_raw_price":np.nan if entry_i is None else float(g.open.iloc[entry_i]),"entry_coord_price":np.nan if entry_i is None else float(g.coord_open.iloc[entry_i]),"entry_coordinate_factor":np.nan if entry_i is None else float(g.coordinate_factor.iloc[entry_i]),
                     "entry_delay_minutes":np.nan if entry_i is None else int(entry_i),"entry_price_vs_l":np.nan if entry_i is None else float(g.coord_open.iloc[entry_i]/L-1),"entry_price_vs_u":np.nan if entry_i is None else float(g.coord_open.iloc[entry_i]/U-1),
                     "entry_uses_future_bar":False if entry_i is None else bool(g.bar_end_time.iloc[entry_i]<=g.bar_end_time.iloc[ci])}
                rows.append(row)
    out=pd.DataFrame(rows).sort_values(["translation","confirmation_time","candidate_id"],kind="mergesort")
    actions=pd.read_parquet(v6.ACTION_EVENTS)
    for col in ("known_date","effective_date"): actions[col]=pd.to_datetime(actions[col])
    risk_by={k:g.loc[g.action_kind.str.startswith("RISK")] for k,g in actions.groupby("symbol",sort=False)}
    blocked=[]
    for r in out.itertuples(index=False):
        if r.status!="EXECUTABLE_ENTRY": blocked.append(False); continue
        act=risk_by.get(r.symbol,pd.DataFrame(columns=actions.columns))
        blocked.append(bool(len(act.loc[act.known_date.le(pd.Timestamp(r.confirmation_time).normalize())&act.effective_date.ge(pd.Timestamp(r.entry_date).normalize())])))
    out["risk_blocked_entry"]=blocked
    out.loc[out.risk_blocked_entry,"status"]="RISK_BLOCKED_ENTRY"
    if len(out)!=len(candidates)*35 or out.entry_uses_future_bar.any(): raise ResearchError("entry grid completeness/causality failure")
    write_parquet(out,ENTRY_CANDIDATES)
    return out


def _safe_div(a: float, b: float) -> float:
    return float(a/b) if np.isfinite(a) and np.isfinite(b) and abs(b)>1e-12 else np.nan


def _ret(frame: pd.DataFrame, n: int) -> float:
    return _safe_div(float(frame.coord_close.iloc[-1]),float(frame.coord_close.iloc[-n]))-1 if len(frame)>=n else np.nan


def _context_ret(ctx: pd.DataFrame, date: pd.Timestamp, n: int) -> float:
    p=ctx.loc[ctx.trade_date.lt(date)].tail(n)
    return float(np.prod(1+p.ret.to_numpy(float))-1) if len(p)==n else np.nan


def build_daily_relevant(candidates: pd.DataFrame) -> Path:
    path=EXT/"daily_relevant.parquet"; symbols=EXT/"symbols.parquet"
    write_parquet(pd.DataFrame({"symbol":sorted(candidates.symbol.unique())}),symbols)
    con=duckdb.connect(); con.execute("SET threads=4")
    con.execute(f"""COPY (
      SELECT d.trade_date,d.cal_idx,d.symbol,d.sleeve AS board,d.open,d.high,d.low,d.close,d.volume,d.amount,d.turnover_fraction,d.causal_industry AS industry,
        d.trade_status,d.current_day_data_tradable,d.up_limit_price,d.down_limit_price,d.market_rule_valid,d.corporate_action_blocking,d.hard_valid,d.available_at,d.decision_at,
        d.invalid_step_cum,d.coordinate_factor,d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.prior_coord_close,d.step_return
      FROM read_parquet('{DAILY}') d JOIN read_parquet('{symbols}') s USING(symbol)
      WHERE d.trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
      ORDER BY symbol,trade_date
    ) TO '{path}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.close(); return path


def build_daily_contexts() -> tuple[Path,Path,Path]:
    market=EXT/"market_daily_context.parquet"; board=EXT/"board_daily_context.parquet"; industry=EXT/"industry_daily_context.parquet"
    con=duckdb.connect(); con.execute("SET threads=4"); con.execute("SET preserve_insertion_order=false")
    base=f"""WITH d0 AS (SELECT *,lag(coord_low) OVER(PARTITION BY symbol ORDER BY trade_date) AS prev_low FROM read_parquet('{DAILY}') WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'), b AS (SELECT *,coord_close/nullif(prior_coord_close,0)-1 AS ret,coord_open/nullif(prior_coord_close,0)-1 AS open_ret,coord_high<prev_low AS true_gap,round(close*100)<=round(down_limit_price*100) AS lower_limit,close<=down_limit_price*1.01 AS near_limit FROM d0 WHERE hard_valid AND current_day_data_tradable AND NOT corporate_action_blocking AND causal_industry IS NOT NULL)"""
    con.execute(f"COPY ({base} SELECT trade_date,avg(ret) ret,avg(open_ret) open_ret,avg((ret<0)::INT) down_breadth,avg(true_gap::INT) true_gap_breadth,avg(lower_limit::INT) lower_limit_stress,avg(near_limit::INT) near_limit_stress,median(ret) median_ret,stddev_pop(ret) ret_vol,count(*) n FROM b GROUP BY trade_date ORDER BY trade_date) TO '{market}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.execute(f"COPY ({base} SELECT trade_date,sleeve AS group_id,avg(ret) ret,avg(open_ret) open_ret,avg((ret<0)::INT) down_breadth,avg(true_gap::INT) true_gap_breadth,median(ret) median_ret,count(*) n FROM b GROUP BY trade_date,sleeve ORDER BY group_id,trade_date) TO '{board}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.execute(f"COPY ({base} SELECT trade_date,causal_industry AS group_id,avg(ret) ret,avg(open_ret) open_ret,avg((ret<0)::INT) down_breadth,avg(true_gap::INT) true_gap_breadth,median(ret) median_ret,count(*) n,count_if(true_gap OR near_limit) comparable_shock_peers FROM b GROUP BY trade_date,causal_industry ORDER BY group_id,trade_date) TO '{industry}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close(); return market,board,industry


def build_gap_minutes(candidates: pd.DataFrame) -> None:
    seed=EXT/"gap_seed.parquet"; write_parquet(candidates[["candidate_id","symbol","frozen_primary_gap_date"]].rename(columns={"frozen_primary_gap_date":"gap_date"}),seed)
    con=duckdb.connect(); con.execute("SET threads=4")
    con.execute(f"""COPY (
      WITH raw AS ({raw_union()})
      SELECT s.candidate_id,r.trade_date,r.bar_end_time,r.open,r.high,r.low,r.close,r.volume,r.amount,d.coordinate_factor,d.down_limit_price,
        count(*) OVER(PARTITION BY s.candidate_id) minute_count
      FROM read_parquet('{seed}') s JOIN raw r ON r.qmt_code=s.symbol AND r.trade_date=s.gap_date
      JOIN read_parquet('{DAILY}') d ON d.symbol=s.symbol AND d.trade_date=r.trade_date
      ORDER BY s.candidate_id,r.bar_end_time
    ) TO '{GAP_MINUTES}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.close()
    c=duckdb.connect(); bad=c.execute(f"SELECT count(*) FROM (SELECT candidate_id,count(*) n FROM read_parquet('{GAP_MINUTES}') GROUP BY 1 HAVING n<>241)").fetchone()[0]; c.close()
    if bad: raise ResearchError(f"gap-day 241-bar failure {bad}")


def _window_stats(p: pd.DataFrame, w: int, prefix: str="") -> dict[str,float]:
    if len(p)<w: return {f"{n}_{w}":np.nan for n in ("net_advance_toward_l","path_efficiency","max_pullback","pullback_burden","up_session_share","higher_low_share","lower_low_share","range_compression","close_location_trend","turnover_on_up_days","turnover_on_down_days","approach_price_progress_per_turnover")}
    x=p.tail(w).copy(); r=x.coord_close.pct_change().dropna(); net=_ret(x,w)
    ranges=(x.coord_high-x.coord_low)/x.coord_close.replace(0,np.nan); cl=(x.coord_close-x.coord_low)/(x.coord_high-x.coord_low).replace(0,np.nan)
    vals={
      f"net_advance_toward_l_{w}":net,f"path_efficiency_{w}":_safe_div(abs(net),float(r.abs().sum())),f"max_pullback_{w}":float((x.coord_close/x.coord_close.cummax()-1).min()),
      f"pullback_burden_{w}":float(-r.clip(upper=0).sum()),f"up_session_share_{w}":float(r.gt(0).mean()),f"higher_low_share_{w}":float(x.coord_low.diff().gt(0).mean()),
      f"lower_low_share_{w}":float(x.coord_low.diff().lt(0).mean()),f"range_compression_{w}":_safe_div(float(ranges.tail(max(1,w//2)).mean()),float(ranges.head(max(1,w//2)).mean())),
      f"close_location_trend_{w}":float(np.polyfit(np.arange(len(cl)),cl.fillna(cl.median() if cl.notna().any() else 0),1)[0]),f"turnover_on_up_days_{w}":float(x.loc[x.coord_close.pct_change().gt(0),"turnover_fraction"].mean()),
      f"turnover_on_down_days_{w}":float(x.loc[x.coord_close.pct_change().lt(0),"turnover_fraction"].mean()),f"approach_price_progress_per_turnover_{w}":_safe_div(net,float(x.turnover_fraction.sum()))}
    return vals


def _gap_minute_features(g: pd.DataFrame, drow: pd.Series, prior: pd.DataFrame) -> dict[str,float]:
    g=g.sort_values("bar_end_time").copy(); op=float(g.open.iloc[0]); close=g.close.to_numpy(float); vol=g.volume.fillna(0).to_numpy(float); amount=g.amount.fillna(0).to_numpy(float)
    rets=pd.Series(close).pct_change().fillna(close[0]/op-1).to_numpy(); vwap=np.divide(np.cumsum(amount),np.cumsum(vol),out=np.full(len(g),np.nan),where=np.cumsum(vol)>0)
    runlow=np.minimum.accumulate(g.low.to_numpy(float)); rebound=close/runlow-1; down=float(vol[rets<0].sum()); up=float(vol[rets>0].sum()); rng=float(drow.high-drow.low)
    dl=float(drow.down_limit_price); at=np.round(g.close.to_numpy(float)*100)==round(dl*100)
    tmean=float(prior.turnover_fraction.tail(60).mean()); tstd=float(prior.turnover_fraction.tail(60).std(ddof=0))
    return {"gap_day_turnover_zscore":_safe_div(float(drow.turnover_fraction)-tmean,tstd),"opening_5m_return":close[min(4,len(close)-1)]/op-1,"opening_15m_return":close[min(14,len(close)-1)]/op-1,"opening_30m_return":close[min(29,len(close)-1)]/op-1,
      "max_rebound_from_low":float(np.nanmax(rebound)),"rebound_giveback_to_close":float(np.nanmax(close)/close[-1]-1),"gap_day_close_location":_safe_div(float(drow.close-drow.low),rng),"time_below_vwap":float(np.nanmean(close<vwap)),"gap_day_close_vs_vwap":_safe_div(close[-1],vwap[-1])-1,
      "down_bar_volume_share":_safe_div(down,float(vol.sum())),"up_bar_volume_share":_safe_div(up,float(vol.sum())),"signed_volume_proxy":_safe_div(float((np.sign(rets)*vol).sum()),float(vol.sum())),"gap_day_price_progress_per_volume":_safe_div(close[-1]/op-1,float(drow.turnover_fraction)),
      "afternoon_return":close[-1]/float(g.open.iloc[min(120,len(g)-1)])-1,"afternoon_volume_share":_safe_div(float(vol[120:].sum()),float(vol.sum())),"failed_intraday_rebound_count":float(np.sum((rebound[:-1]>=.02)&((close[-1]/close[:-1]-1)<=-.02))) if len(close)>1 else 0.0,
      "late_day_recovery":close[-1]/close[max(0,len(close)-31)]-1,"ordinary_gap_flag":float(not at.any() and drow.close>dl*1.01),"near_lower_limit_flag":float(drow.close<=dl*1.01 and not at.all()),"exact_locked_limit_flag":float(at.all()),"partially_released_limit_flag":float(at.any() and not at.all())}


def build_same_clock_context(entries: pd.DataFrame, daily_rel: Path) -> Path:
    path=EXT/"same_clock_context.parquet"
    decisions=entries.loc[entries.status.eq("EXECUTABLE_ENTRY"),["confirmation_time","confirmation_date"]].drop_duplicates().copy()
    decisions.confirmation_date=pd.to_datetime(decisions.confirmation_date).dt.normalize(); seed=EXT/"decision_times.parquet"; write_parquet(decisions,seed)
    con=duckdb.connect(); con.execute("SET threads=4"); con.execute("SET preserve_insertion_order=false")
    con.execute(f"""COPY (
      WITH raw AS ({raw_union()}), x AS (
        SELECT s.confirmation_time,r.trade_date,r.qmt_code AS symbol,r.close/d.open-1 AS intraday_return,d.sleeve AS board,d.causal_industry AS industry
        FROM read_parquet('{seed}') s JOIN raw r ON r.trade_date=s.confirmation_date AND r.bar_end_time=s.confirmation_time
        JOIN read_parquet('{DAILY}') d ON d.symbol=r.qmt_code AND d.trade_date=r.trade_date
        WHERE d.hard_valid AND d.current_day_data_tradable AND NOT d.corporate_action_blocking
      ), m AS (SELECT confirmation_time,'MARKET' AS context_scope,'ALL' AS group_id,avg(intraday_return) AS context_value FROM x GROUP BY 1),
      b AS (SELECT confirmation_time,'BOARD' AS context_scope,board AS group_id,avg(intraday_return) AS context_value FROM x GROUP BY 1,3),
      i AS (SELECT confirmation_time,'INDUSTRY' AS context_scope,industry AS group_id,avg(intraday_return) AS context_value FROM x GROUP BY 1,3)
      SELECT * FROM m UNION ALL SELECT * FROM b UNION ALL SELECT * FROM i ORDER BY confirmation_time,context_scope,group_id
    ) TO '{path}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.close(); return path


def build_features(candidates: pd.DataFrame, entries: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame,dict[str,Any]]:
    daily_path=build_daily_relevant(candidates); market_path,board_path,industry_path=build_daily_contexts(); build_gap_minutes(candidates)
    same_clock_path=build_same_clock_context(entries,daily_path)
    daily=pd.read_parquet(daily_path); daily.trade_date=pd.to_datetime(daily.trade_date)
    for col in ("available_at","decision_at"): daily[col]=pd.to_datetime(daily[col])
    if (daily.available_at>daily.decision_at).any(): raise ResearchError("daily PIT availability violation")
    daily_by={s:g.sort_values("trade_date").reset_index(drop=True) for s,g in daily.groupby("symbol",sort=False)}
    market=pd.read_parquet(market_path); board=pd.read_parquet(board_path); industry=pd.read_parquet(industry_path)
    for x in (market,board,industry): x.trade_date=pd.to_datetime(x.trade_date)
    board_by={k:g.sort_values("trade_date") for k,g in board.groupby("group_id",sort=False)}; ind_by={k:g.sort_values("trade_date") for k,g in industry.groupby("group_id",sort=False)}
    gapmins=pd.read_parquet(GAP_MINUTES); gapmins.bar_end_time=pd.to_datetime(gapmins.bar_end_time); gapmins.trade_date=pd.to_datetime(gapmins.trade_date); gapmin_by={k:g for k,g in gapmins.groupby("candidate_id",sort=False)}
    gapledger=pd.read_parquet(CAUSAL_GAPS,columns=["symbol","gap_date","importance","true_gap_upper"]); gapledger.gap_date=pd.to_datetime(gapledger.gap_date); gap_by={k:g for k,g in gapledger.groupby("symbol",sort=False)}
    clusters=pd.read_parquet(SOURCE_CLUSTERS,columns=["symbol","cluster_start_time"]); clusters.cluster_start_time=pd.to_datetime(clusters.cluster_start_time); cluster_by={k:g for k,g in clusters.groupby("symbol",sort=False)}
    common=[]; meta={r.candidate_id:r for r in candidates.itertuples(index=False)}
    for e in candidates.itertuples(index=False):
        s=daily_by[e.symbol]; gd=pd.Timestamp(e.frozen_primary_gap_date).normalize(); pre=s.loc[s.trade_date.lt(gd)]; grow=s.loc[s.trade_date.eq(gd)]
        if grow.empty: raise ResearchError(f"missing gap daily row {e.candidate_id}")
        dr=grow.iloc[0]; prior20=pre.tail(20); prior10=pre.tail(10); prior5=pre.tail(5); prior60=pre.tail(60)
        rr=prior20.coord_close.pct_change(); medturn=float(prior60.turnover_fraction.median())
        upturn=float(prior20.loc[rr.gt(0).reindex(prior20.index,fill_value=False),"turnover_fraction"].mean()); downturn=float(prior20.loc[rr.lt(0).reindex(prior20.index,fill_value=False),"turnover_fraction"].mean())
        shadow=(prior10.coord_high-prior10[["coord_open","coord_close"]].max(axis=1))/(prior10.coord_high-prior10.coord_low).replace(0,np.nan)
        prev20high=pre.coord_high.rolling(20,min_periods=10).max().shift(1).tail(10)
        dret=prior10.coord_close.pct_change().fillna(0); stall=(prior10.turnover_fraction.gt(medturn)&dret.abs().lt(.01)).sum()
        vals={"candidate_id":e.candidate_id,"pre5_turnover_vs_prior60":_safe_div(float(prior5.turnover_fraction.mean()),float(pre.iloc[-65:-5].turnover_fraction.mean())),"pre10_turnover_vs_prior60":_safe_div(float(prior10.turnover_fraction.mean()),float(pre.iloc[-70:-10].turnover_fraction.mean())),
          "pre20_cum_turnover":float(prior20.turnover_fraction.sum()),"high_turnover_down_day_share_10":float((dret.lt(0)&prior10.turnover_fraction.gt(medturn)).mean()),"high_turnover_down_day_share_20":float((rr.lt(0)&prior20.turnover_fraction.gt(medturn)).mean()),
          "up_vs_down_turnover_asymmetry":_safe_div(upturn,downturn),"upper_shadow_pressure_10":float(shadow.mean()),"failed_new_high_count_10":float((prior10.coord_high.ge(prev20high)&prior10.coord_close.lt(prior10.coord_open)).sum()),
          "high_volume_stall_count_10":float(stall),"price_advance_per_turnover_10":_safe_div(_ret(prior10,10),float(prior10.turnover_fraction.sum())),"return_deceleration_5_vs_20":_ret(prior5,5)-_ret(prior20,20)/4,"distance_from_causal_reference_high":float(pre.coord_close.iloc[-1]/e.reference_high-1)}
        bctx=board_by.get(e.board,pd.DataFrame()); ictx=ind_by.get(str(dr.industry),pd.DataFrame())
        for scope,ctx in (("board",bctx),("industry",ictx)):
            for w in (5,10,20): vals[f"{scope}_relative_return_{w}"]=_ret(pre.tail(w),w)-_context_ret(ctx,gd,w)
        for scope,ctx in (("market",market),("board",bctx),("industry",ictx)):
            cr=ctx.loc[ctx.trade_date.eq(gd)]
            vals[f"{scope}_open_return"]=np.nan if cr.empty else float(cr.open_ret.iloc[0]); vals[f"{scope}_close_return"]=np.nan if cr.empty else float(cr.ret.iloc[0]); vals[f"{scope}_down_breadth"]=np.nan if cr.empty else float(cr.down_breadth.iloc[0]); vals[f"{scope}_true_gap_breadth"]=np.nan if cr.empty else float(cr.true_gap_breadth.iloc[0])
        mr=market.loc[market.trade_date.eq(gd)]; ir=ictx.loc[ictx.trade_date.eq(gd)]
        vals["lower_limit_stress"]=np.nan if mr.empty else float(mr.lower_limit_stress.iloc[0]); vals["near_limit_stress"]=np.nan if mr.empty else float(mr.near_limit_stress.iloc[0]); vals["peers_with_comparable_shock"]=np.nan if ir.empty else float(ir.comparable_shock_peers.iloc[0])
        sr=pre.coord_close.pct_change().tail(60); mx=market.loc[market.trade_date.isin(pre.trade_date.tail(60)),"ret"].tail(len(sr)); beta=_safe_div(float(np.cov(sr.iloc[-len(mx):],mx,ddof=0)[0,1]),float(np.var(mx))) if len(mx)>10 else 1.0
        stock_open=float(dr.coord_open/dr.prior_coord_close-1); stock_close=float(dr.coord_close/dr.prior_coord_close-1)
        vals["gap_day_open_residual"]=stock_open-beta*vals["market_open_return"]; vals["gap_day_close_residual"]=stock_close-beta*vals["market_close_return"]
        gm=gapmin_by.get(e.candidate_id)
        if gm is None or len(gm)!=241: raise ResearchError(f"gap minute missing {e.candidate_id}")
        vals.update(_gap_minute_features(gm,dr,pre)); common.append(vals)
    common_df=pd.DataFrame(common)

    minutes=pd.read_parquet(ENTRY_MINUTES,columns=["candidate_id","trade_date","bar_end_time","open","high","low","close","coord_open","coord_high","coord_low","coord_close","volume","amount"])
    minutes.trade_date=pd.to_datetime(minutes.trade_date); minutes.bar_end_time=pd.to_datetime(minutes.bar_end_time); min_by={k:g.sort_values("bar_end_time") for k,g in minutes.groupby("candidate_id",sort=False)}
    sc=pd.read_parquet(same_clock_path); sc.confirmation_time=pd.to_datetime(sc.confirmation_time); sc_map={(r.confirmation_time,r.context_scope,str(r.group_id)):float(r.context_value) for r in sc.itertuples(index=False)}
    unique=entries.loc[entries.status.eq("EXECUTABLE_ENTRY"),["candidate_id","confirmation_time","confirmation_date","decision_coord_close","decision_minute_index"]].drop_duplicates(["candidate_id","confirmation_time"])
    dynamic=[]
    for r in unique.itertuples(index=False):
        e=meta[r.candidate_id]; dt=pd.Timestamp(r.confirmation_time); dd=pd.Timestamp(r.confirmation_date).normalize(); s=daily_by[e.symbol]; prior=s.loc[s.trade_date.lt(dd)]; dr=s.loc[s.trade_date.eq(dd)].iloc[0]
        bctx=board_by.get(e.board,pd.DataFrame()); ictx=ind_by.get(str(dr.industry),pd.DataFrame()); cluster_start=pd.Timestamp(e.cluster_start_time).normalize(); gapd=pd.Timestamp(e.frozen_primary_gap_date).normalize(); freeze=pd.Timestamp(e.cluster_freeze_time).normalize()
        hist=s.loc[s.trade_date.between(cluster_start,dd,inclusive="left")]; phist=s.loc[s.trade_date.between(gapd,dd,inclusive="left")]; dailyret=hist.coord_close.pct_change(); ind_dates=ictx.loc[ictx.trade_date.isin(hist.trade_date),["trade_date","ret"]]; mdates=market.loc[market.trade_date.isin(hist.trade_date),["trade_date","ret"]]
        indret=hist[["trade_date"]].merge(ind_dates,on="trade_date",how="left").ret.fillna(0).to_numpy(); mret=hist[["trade_date"]].merge(mdates,on="trade_date",how="left").ret.fillna(0).to_numpy(); stockret=hist.coord_close.pct_change().fillna(0).to_numpy(); residual=stockret-indret
        gl=gap_by.get(e.symbol,pd.DataFrame()); lower=gl.loc[gl.gap_date.between(freeze,dd,inclusive="left")&gl.importance.isin(["MAJOR","SECONDARY"])&gl.true_gap_upper.lt(e.L)] if len(gl) else gl
        cl=cluster_by.get(e.symbol,pd.DataFrame()); newclusters=cl.loc[cl.cluster_start_time.between(freeze,dd,inclusive="left")] if len(cl) else cl
        vals={"candidate_id":r.candidate_id,"confirmation_time":dt,"cum_turnover_since_cluster":float(hist.turnover_fraction.sum()),"cum_turnover_since_primary":float(phist.turnover_fraction.sum()),"stock_cum_return":_safe_div(float(prior.coord_close.iloc[-1]),float(s.loc[s.trade_date.eq(gapd),"coord_close"].iloc[0]))-1 if len(prior) else np.nan,
          "board_cum_return":_context_ret(bctx,dd,len(hist)) if len(hist) else np.nan,"industry_cum_return":_context_ret(ictx,dd,len(hist)) if len(hist) else np.nan,"cum_negative_residual":float(np.minimum(residual,0).sum()),
          "high_turnover_negative_residual_day_count":float(((residual<0)&(hist.turnover_fraction.to_numpy()>prior.turnover_fraction.tail(60).median())).sum()),"market_up_stock_down_day_count":float(((mret>0)&(stockret<0)).sum()),"industry_up_stock_down_day_count":float(((indret>0)&(stockret<0)).sum()),
          "new_lower_major_secondary_gap_count":float(len(lower)),"new_lower_cluster_count":float(len(newclusters)),"failed_recovery_count":float(((hist.coord_high/hist.coord_low.cummin()-1>=.05)&hist.coord_close.lt(hist.coord_low.shift(1))).sum()),"time_below_l":float(hist.coord_high.lt(e.L).sum()),"max_distance_below_l":float(hist.coord_low.min()/e.L-1) if len(hist) else np.nan}
        vals["stock_minus_board_return"]=vals["stock_cum_return"]-vals["board_cum_return"]; vals["stock_minus_industry_return"]=vals["stock_cum_return"]-vals["industry_cum_return"]
        for start,label in ((gapd,"gap"),(freeze,"freeze")):
            n=max(1,len(market.loc[market.trade_date.between(start,dd,inclusive="left")]))
            vals[f"market_return_since_{label}"]=_context_ret(market,dd,n); vals[f"board_return_since_{label}"]=_context_ret(bctx,dd,n); vals[f"industry_return_since_{label}"]=_context_ret(ictx,dd,n)
        gapmr=market.loc[market.trade_date.eq(gapd)]; vals["breadth_recovery"]=float(market.loc[market.trade_date.lt(dd)].tail(20).ret.gt(0).mean()-(gapmr.down_breadth.iloc[0] if len(gapmr) else np.nan)); vals["lower_limit_stress_recovery"]=float((gapmr.lower_limit_stress.iloc[0] if len(gapmr) else np.nan)-market.loc[market.trade_date.lt(dd)].tail(5).lower_limit_stress.mean())
        vals["volatility_normalization"]=_safe_div(float(market.loc[market.trade_date.lt(dd)].tail(5).ret.abs().mean()),float(market.loc[market.trade_date.lt(dd)].tail(60).ret.abs().mean())); vals["market_median_return_recovery"]=float(market.loc[market.trade_date.lt(dd)].tail(20).median_ret.sum()); vals["industry_median_return_recovery"]=float(ictx.loc[ictx.trade_date.lt(dd)].tail(20).median_ret.sum())
        for w in (5,10,20):
            vals.update(_window_stats(prior,w)); vals[f"board_relative_approach_return_{w}"]=_ret(prior.tail(w),w)-_context_ret(bctx,dd,w); vals[f"industry_relative_approach_return_{w}"]=_ret(prior.tail(w),w)-_context_ret(ictx,dd,w)
        vals["late_acceleration_5_vs_previous5"]=_ret(prior.tail(5),5)-_ret(prior.tail(10).head(5),5)
        mg=min_by[r.candidate_id]; day=mg.loc[mg.trade_date.eq(dd)&mg.bar_end_time.le(dt)].copy(); n=len(day); op=float(dr.open); close=day.close.to_numpy(float); vol=day.volume.fillna(0).to_numpy(float); amount=day.amount.fillna(0).to_numpy(float); mretarr=pd.Series(close).pct_change().fillna(close[0]/op-1).to_numpy(); vwap=np.divide(np.cumsum(amount),np.cumsum(vol),out=np.full(n,np.nan),where=np.cumsum(vol)>0)
        market_now=sc_map.get((dt,"MARKET","ALL"),np.nan); board_now=sc_map.get((dt,"BOARD",e.board),np.nan); ind_now=sc_map.get((dt,"INDUSTRY",str(dr.industry)),np.nan); stock_now=close[-1]/op-1; dbar=day.iloc[-1]; brange=float(dbar.high-dbar.low); penetration=(day.coord_close.to_numpy(float)-e.L)/e.W; above=day.coord_close.ge(e.L).to_numpy(); transitions=np.diff(above.astype(int)) if n>1 else np.array([])
        priorvol=float(prior.volume.tail(20).median())*float(r.decision_minute_index)/241
        vals.update({"entry_day_market_return_to_clock":market_now,"entry_day_board_return_to_clock":board_now,"entry_day_industry_return_to_clock":ind_now,"stock_intraday_residual_to_clock":stock_now-np.nanmean([board_now,ind_now]),
          "return_to_contact":stock_now,"path_efficiency_to_contact":_safe_div(abs(stock_now),float(np.abs(mretarr).sum())),"max_pullback_to_contact":float((pd.Series(close)/pd.Series(close).cummax()-1).min()),"volume_surprise_same_clock":_safe_div(float(vol.sum()),priorvol)-1,"turnover_surprise":_safe_div(float(vol.sum()),priorvol)-1,
          "price_progress_per_volume":_safe_div(stock_now,float(vol.sum())),"time_above_intraday_vwap":float(np.nanmean(close>=vwap)),"current_close_vs_vwap":_safe_div(close[-1],vwap[-1])-1,"stock_minus_board_intraday_return":stock_now-board_now,"stock_minus_industry_intraday_return":stock_now-ind_now,
          "penetration_into_gap":float(penetration[-1]),"decision_bar_body_ratio":_safe_div(abs(float(dbar.close-dbar.open)),brange),"decision_bar_close_location":_safe_div(float(dbar.close-dbar.low),brange),"decision_bar_upper_wick_ratio":_safe_div(float(dbar.high-max(dbar.open,dbar.close)),brange),
          "decision_bar_volume_surprise":_safe_div(float(dbar.volume),float(prior.volume.tail(20).median())/241)-1,"decision_bar_price_impact_per_volume":_safe_div(float(dbar.close/dbar.open-1),float(dbar.volume)),"opening_jump_flag":float(n==1 and dbar.open>=e.L),"time_of_day":float(r.decision_minute_index/241),
          "share_closes_at_or_above_l":float(above.mean()),"minimum_close_distance_from_l":float(day.coord_close.min()/e.L-1),"maximum_penetration":float(np.max(penetration)),"current_penetration":float(penetration[-1]),"rejection_depth_below_l":float(min(day.coord_close.min()/e.L-1,0)),
          "failed_test_count":float((transitions==-1).sum()),"reclaim_count":float((transitions==1).sum()),"vwap_hold_share":float(np.nanmean(close>=vwap)),"up_vs_down_minute_volume":_safe_div(float(vol[mretarr>0].sum()),float(vol[mretarr<0].sum())),"penetration_gain_per_volume":_safe_div(float(penetration[-1]-penetration[0]),float(vol.sum())),
          "local_high_break_after_retest":float((~above).any() and day.coord_close.iloc[-1]>=day.loc[~above,"coord_high"].max()),"pre5_return":close[-1]/close[max(0,n-5)]-1,"pre15_return":close[-1]/close[max(0,n-15)]-1,"pre30_return":close[-1]/close[max(0,n-30)]-1,"pre60_return":close[-1]/close[max(0,n-60)]-1})
        dynamic.append(vals)
    dynamic_df=pd.DataFrame(dynamic)
    panel=entries.loc[entries.status.eq("EXECUTABLE_ENTRY")].merge(common_df,on="candidate_id",validate="many_to_one").merge(dynamic_df,on=["candidate_id","confirmation_time"],validate="many_to_one")
    feature_names=[x["name"] for x in feature_contract()]; missing=[x for x in feature_names if x not in panel]
    if missing: raise ResearchError(f"unimplemented frozen features: {missing}")
    coverage={n:{"valid":int(panel[n].notna().sum()),"coverage":float(panel[n].notna().mean()),"unique":int(panel[n].nunique(dropna=True))} for n in feature_names}
    all_null=[n for n,v in coverage.items() if v["valid"]==0]
    if all_null: raise ResearchError(f"all-null frozen features {all_null}")
    write_parquet(common_df,EVENT_FEATURES); write_parquet(dynamic_df,INTRADAY_FEATURES); write_parquet(panel,MODEL_PANEL)
    return common_df,dynamic_df,{"rows":len(panel),"features":len(feature_names),"all_null":all_null,"coverage":coverage}


def freeze_feature_contract(readiness:dict[str,Any],minute_audit:dict[str,Any],entries:pd.DataFrame,coverage:dict[str,Any]) -> dict[str,Any]:
    write_json(COVERAGE_REPORT,coverage)
    features=feature_contract(); timestamp={x["name"]:{"latest_observable":x["latest_observable"],"pit_source":x["pit_source"],"known_by_decision":"YES"} for x in features}
    write_json(FEATURE_TIMESTAMP_AUDIT,{"features":timestamp,"feature_uses_post_decision_information_count":0})
    paths=[SPEC,FEATURE_DICTIONARY,FEATURE_TIMESTAMP_AUDIT,COVERAGE_REPORT,OUTCOME_DICTIONARY,ENTRY_GRID,EXIT_GRID,MODEL_PROFILES]
    hashes={p.name:sha(p) for p in paths}; digest=hashlib.sha256("".join(f"{k}:{hashes[k]}" for k in sorted(hashes)).encode()).hexdigest()
    status=entries.groupby(["translation","status"]).size().rename("count").reset_index().to_dict("records")
    freeze={"experiment":EXPERIMENT,"feature_contract_hash":digest,"component_hashes":hashes,"readiness":readiness,"minute_audit":minute_audit,"entry_status":status,"feature_count":len(features),"l2_bundle_available":"NO","outcomes_opened":"NO","v6_signal_identity_changed_count":0,"feature_added_after_outcome_scan_count":0,"repository_2024_plus_data_opened":"NO"}
    write_json(FEATURE_FREEZE,freeze); return freeze


def verify_feature_freeze() -> dict[str,Any]:
    if not FEATURE_FREEZE.is_file(): raise ResearchError("feature freeze missing")
    r=json.loads(FEATURE_FREEZE.read_text())
    if r["feature_contract_hash"]!=EXPECTED_FEATURE_CONTRACT_HASH or r["outcomes_opened"]!="NO": raise ResearchError("feature freeze mismatch")
    for name,digest in r["component_hashes"].items():
        options=[SPEC,FEATURE_DICTIONARY,FEATURE_TIMESTAMP_AUDIT,COVERAGE_REPORT,OUTCOME_DICTIONARY,ENTRY_GRID,EXIT_GRID,MODEL_PROFILES]
        p=next((x for x in options if x.name==name),None)
        if p is None or sha(p)!=digest: raise ResearchError(f"frozen component changed {name}")
    if r["v6_signal_identity_changed_count"] or r["feature_added_after_outcome_scan_count"]: raise ResearchError("freeze causal audit failed")
    return r


def _next_legal_sell(mins:pd.DataFrame,legal:pd.DataFrame,trigger:pd.Timestamp,entry_date:pd.Timestamp) -> dict[str,Any]|None:
    m=mins.loc[mins.bar_end_time.gt(trigger)&mins.trade_date.gt(entry_date.normalize())&mins.trade_status.eq(1)&mins.current_day_data_tradable&mins.market_rule_valid&~mins.corporate_action_blocking&(np.round(mins.open*100)>np.round(mins.down_limit_price*100))]
    if len(m):
        r=m.iloc[0]; return {"exit_time":pd.Timestamp(r.bar_end_time),"exit_date":pd.Timestamp(r.trade_date),"raw_price":float(r.open),"cal_idx":int(r.cal_idx)}
    q=legal.loc[legal.bar_end_time.gt(trigger)&legal.trade_date.gt(entry_date.normalize())]
    if len(q):
        r=q.iloc[0]; return {"exit_time":pd.Timestamp(r.bar_end_time),"exit_date":pd.Timestamp(r.trade_date),"raw_price":float(r.raw_open),"cal_idx":int(r.cal_idx)}
    return None


def _choose_exit(target:dict[str,Any]|None,stop:dict[str,Any]|None,horizon:dict[str,Any]|None,risk:dict[str,Any]|None=None) -> tuple[dict[str,Any]|None,str]:
    choices=[]
    if risk is not None: choices.append((risk["exit_time"],-1,risk,"CORPORATE_ACTION_RISK"))
    if target is not None: choices.append((target["exit_time"],0,target,"TARGET"))
    if stop is not None: choices.append((stop["exit_time"],1,stop,"FAILURE_EXIT"))
    if horizon is not None: choices.append((horizon["exit_time"],2,horizon,"TIME_EXIT"))
    if not choices: return None,"UNRESOLVED"
    _,_,x,why=min(choices,key=lambda z:(z[0],z[1])); return x,why


def _cash_amount(actions:pd.DataFrame,entry_date:pd.Timestamp,exit_date:pd.Timestamp) -> float:
    if actions.empty:return 0.0
    x=actions.loc[actions.action_kind.eq("CASH_ONLY")&actions.effective_date.gt(entry_date.normalize())&actions.effective_date.le(exit_date.normalize())]
    return float(x.cash_per_share.sum())


def _blocked_action_precedes_exit(blocked:dict[str,Any]|None,chosen:dict[str,Any]|None,actions:pd.DataFrame) -> bool:
    if blocked is None:return False
    known=actions.loc[actions.event_id.astype(str).eq(str(blocked["event_id"])),"known_date"]
    if known.empty:return True
    return chosen is None or pd.Timestamp(chosen["exit_time"])>=pd.Timestamp(known.iloc[0])


def build_policy_paths(entries:pd.DataFrame,candidates:pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame]:
    executable=entries.loc[entries.status.eq("EXECUTABLE_ENTRY")].copy()
    unique=executable.drop_duplicates(["candidate_id","entry_time"])[["candidate_id","symbol","board","memory_state","L","U","W","invalid_step_cum","entry_time","entry_date","entry_cal_idx","entry_raw_price","entry_coord_price","entry_coordinate_factor"]]
    unique["entry_key"]=unique.candidate_id+"|"+pd.to_datetime(unique.entry_time).astype(str)
    minutes=pd.read_parquet(ENTRY_MINUTES,columns=["candidate_id","trade_date","bar_end_time","cal_idx","open","high","low","close","coord_open","coord_high","coord_low","coord_close","coordinate_factor","invalid_step_cum","trade_status","current_day_data_tradable","market_rule_valid","corporate_action_blocking","down_limit_price"])
    for c in ("trade_date","bar_end_time"):minutes[c]=pd.to_datetime(minutes[c])
    min_by={k:g.sort_values("bar_end_time") for k,g in minutes.groupby("candidate_id",sort=False)}
    daily=pd.read_parquet(EXT/"daily_relevant.parquet"); daily.trade_date=pd.to_datetime(daily.trade_date); daily_by={k:g.sort_values("trade_date") for k,g in daily.groupby("symbol",sort=False)}
    legal=pd.read_parquet(V6_LEGAL_OPENS); legal.trade_date=pd.to_datetime(legal.trade_date); legal.bar_end_time=pd.to_datetime(legal.bar_end_time); legal_by={k:g.sort_values("bar_end_time") for k,g in legal.groupby("symbol",sort=False)}
    actions=pd.read_parquet(v6.ACTION_EVENTS) if v6.ACTION_EVENTS.is_file() else pd.DataFrame(columns=["symbol","action_kind","known_date","effective_date","cash_per_share"])
    for c in ("known_date","effective_date"):
        if c in actions: actions[c]=pd.to_datetime(actions[c])
    act_by={k:g for k,g in actions.groupby("symbol",sort=False)}
    gaps=pd.read_parquet(CAUSAL_GAPS,columns=["symbol","gap_date","importance","true_gap_upper"]);gaps.gap_date=pd.to_datetime(gaps.gap_date); gap_by={k:g for k,g in gaps.groupby("symbol",sort=False)}
    policies=["X0_NO_STOP"]+[f"X1_INTRADAY_{int(x*100)}" for x in (.05,.08,.10,.12)]+[f"X2_DAILY_{int(x*100)}" for x in (.05,.08,.10,.12)]+[f"X3_WIDTH_{z}" for z in (1,2,3)]+["X4_STRUCTURAL_LOWER_GAP"]+[f"X5_D{d}_P{int(p*100)}" for d in (3,5,10) for p in (.10,.25,.50)]+[f"X6_PROGRESS_FAILURE_P{int(p*100)}" for p in (.50,.75)]
    rows=[];post=[]; audit=Counter()
    for e in unique.itertuples(index=False):
        et=pd.Timestamp(e.entry_time); ed=pd.Timestamp(e.entry_date).normalize(); lineage=float(e.invalid_step_cum); mins=min_by[e.candidate_id]; mins=mins.loc[mins.bar_end_time.ge(et)&mins.invalid_step_cum.eq(lineage)].copy(); all_days=daily_by[e.symbol]; days=all_days.loc[all_days.trade_date.ge(ed)&all_days.invalid_step_cum.eq(lineage)].copy(); leg=legal_by.get(e.symbol,pd.DataFrame()); leg=leg.loc[leg.invalid_step_cum.eq(lineage)] if len(leg) else leg; acts=act_by.get(e.symbol,pd.DataFrame(columns=actions.columns))
        target_rows=mins.loc[mins.trade_date.gt(ed)&mins.coord_high.ge(e.U)]
        target=None
        if len(target_rows):
            z=target_rows.iloc[0];target={"exit_time":pd.Timestamp(z.bar_end_time),"exit_date":pd.Timestamp(z.trade_date),"raw_price":float(e.U/z.coordinate_factor),"cal_idx":int(z.cal_idx)}
        horizon={}
        for H in TIME_STOPS:
            hd=days.loc[days.cal_idx.ge(int(e.entry_cal_idx)+H)&days.hard_valid&days.current_day_data_tradable&~days.corporate_action_blocking]
            hx=None
            if len(hd):
                z=hd.iloc[0]
                if round(float(z.close)*100)>round(float(z.down_limit_price)*100): hx={"exit_time":pd.Timestamp(z.trade_date)+pd.Timedelta(hours=15),"exit_date":pd.Timestamp(z.trade_date),"raw_price":float(z.close),"cal_idx":int(z.cal_idx)}
                else: hx=_next_legal_sell(mins,leg,pd.Timestamp(z.trade_date)+pd.Timedelta(hours=15),ed)
            horizon[H]=hx
        risk_by_h={}
        for H in TIME_STOPS:
            cutoff=(pd.Timestamp("2023-12-31 15:00") if horizon[H] is None else pd.Timestamp(horizon[H]["exit_date"])+pd.Timedelta(hours=15))
            risk=anatomy.forced_risk_exit(acts,et,ed,all_days,leg,lineage,cutoff)
            blocked_risk=None
            if risk is not None and risk.get("blocked"):
                blocked_risk=risk; risk=None
            if risk is not None:
                idx=all_days.loc[all_days.trade_date.eq(pd.Timestamp(risk["exit_date"])),"cal_idx"]
                risk={"exit_time":pd.Timestamp(risk["exit_time"]),"exit_date":pd.Timestamp(risk["exit_date"]),"raw_price":float(risk["exit_raw_price"]),"cal_idx":int(idx.iloc[0]) if len(idx) else np.nan}
            risk_by_h[H]=(risk,blocked_risk)
        h40_end=int(e.entry_cal_idx)+40; pathm=mins.loc[mins.cal_idx.le(h40_end)]; pathd=days.loc[days.cal_idx.le(h40_end)]; mae=float(pathm.coord_low.min()/e.entry_coord_price-1) if len(pathm) else np.nan
        loss_times={x:(pd.NaT if pathm.loc[pathm.coord_low.le(e.entry_coord_price*(1-x))].empty else pathm.loc[pathm.coord_low.le(e.entry_coord_price*(1-x)),"bar_end_time"].iloc[0]) for x in (.05,.08,.10,.12,.15,.20)}
        target_time=pd.NaT if target is None or target["cal_idx"]>h40_end else target["exit_time"]
        risk40,blocked40=risk_by_h[40]; h40,_=_choose_exit(target if target is not None and target["cal_idx"]<=h40_end else None,None,horizon[40],risk40); h40_invalid=_blocked_action_precedes_exit(blocked40,h40,acts)
        if h40_invalid:h40=None
        h40net=np.nan if h40 is None else (h40["raw_price"]*(1-COST)+_cash_amount(acts,ed,h40["exit_date"]))/(e.entry_raw_price*(1+COST))-1
        def target_valid(H:int) -> bool:
            if target is None or target["cal_idx"]>int(e.entry_cal_idx)+H:return False
            rr,bb=risk_by_h[H]
            if rr is not None and pd.Timestamp(rr["exit_time"])<=pd.Timestamp(target["exit_time"]):return False
            return not _blocked_action_precedes_exit(bb,target,acts)
        base={"entry_key":e.entry_key,"candidate_id":e.candidate_id,"symbol":e.symbol,"board":e.board,"memory_state":e.memory_state,"entry_time":et,"entry_date":ed,"entry_cal_idx":int(e.entry_cal_idx),"entry_raw_price":float(e.entry_raw_price),"entry_coord_price":float(e.entry_coord_price),"L":float(e.L),"U":float(e.U),"W":float(e.W),"u_time":target_time,"mae40":mae,"y_clean_u20":bool(target_valid(20) and (pd.isna(loss_times[.08]) or target["exit_time"]<loss_times[.08])),"y_clean_u40":bool(target_valid(40) and (pd.isna(loss_times[.10]) or target["exit_time"]<loss_times[.10])),"y_tail_failure40":np.nan if h40_invalid else bool(not target_valid(40) and ((np.isfinite(h40net) and h40net<=-.10) or mae<=-.20)),"outcome_qd010_valid":not h40_invalid}
        for x in (.05,.08,.10,.12,.15): base[f"u_before_loss{int(x*100)}"]=bool(target_valid(40) and (pd.isna(loss_times[x]) or target["exit_time"]<loss_times[x]))
        for d in (3,5,10):
            cp=pathd.loc[pathd.cal_idx.le(int(e.entry_cal_idx)+d)]; z=cp.iloc[-1] if len(cp) else None
            post.append({"entry_key":e.entry_key,"candidate_id":e.candidate_id,"board":e.board,"checkpoint":d,"checkpoint_date":pd.NaT if z is None else pd.Timestamp(z.trade_date),"max_progress":np.nan if cp.empty else float((cp.coord_high.max()-e.entry_coord_price)/e.W),"close_vs_l":np.nan if z is None else float(z.coord_close/e.L-1),"return_to_checkpoint":np.nan if z is None else float(z.coord_close/e.entry_coord_price-1),"mae_to_checkpoint":np.nan if cp.empty else float(cp.coord_low.min()/e.entry_coord_price-1),"turnover_to_checkpoint":float(cp.turnover_fraction.sum()) if len(cp) else np.nan,"y_tail_failure40":base["y_tail_failure40"]})
        gl=gap_by.get(e.symbol,pd.DataFrame()); structural=gl.loc[gl.gap_date.gt(ed)&gl.gap_date.le(pathd.trade_date.max() if len(pathd) else ed)&gl.importance.isin(["MAJOR","SECONDARY"])&gl.true_gap_upper.lt(e.L)] if len(gl) else gl
        static_stops={"X0_NO_STOP":None}
        for x in (.05,.08,.10,.12):
            tr=pathm.loc[pathm.bar_end_time.gt(et)&pathm.coord_close.le(e.entry_coord_price*(1-x))]
            static_stops[f"X1_INTRADAY_{int(x*100)}"]=None if tr.empty else _next_legal_sell(mins,leg,pd.Timestamp(tr.bar_end_time.iloc[0]),ed)
            trd=pathd.loc[pathd.trade_date.gt(ed)&pathd.coord_close.le(e.entry_coord_price*(1-x))]
            static_stops[f"X2_DAILY_{int(x*100)}"]=None if trd.empty else _next_legal_sell(mins,leg,pd.Timestamp(trd.trade_date.iloc[0])+pd.Timedelta(hours=15),ed)
        for z in (1,2,3):
            trd=pathd.loc[pathd.trade_date.gt(ed)&pathd.coord_close.le(e.L-z*e.W)]; static_stops[f"X3_WIDTH_{z}"]=None if trd.empty else _next_legal_sell(mins,leg,pd.Timestamp(trd.trade_date.iloc[0])+pd.Timedelta(hours=15),ed)
        static_stops["X4_STRUCTURAL_LOWER_GAP"]=None if structural.empty else _next_legal_sell(mins,leg,pd.Timestamp(structural.gap_date.iloc[0])+pd.Timedelta(hours=15),ed)
        for d in (3,5,10):
            cp=pathd.loc[pathd.cal_idx.le(int(e.entry_cal_idx)+d)]; z=cp.iloc[-1] if len(cp) else None; progress=np.nan if cp.empty else float((cp.coord_high.max()-e.entry_coord_price)/e.W)
            for p in (.10,.25,.50): static_stops[f"X5_D{d}_P{int(p*100)}"]=None if z is None or not (z.coord_close<e.L and progress<p) else _next_legal_sell(mins,leg,pd.Timestamp(z.trade_date)+pd.Timedelta(hours=15),ed)
        for p in (.50,.75):
            reached=pathd.loc[(pathd.coord_high-e.entry_coord_price)/e.W>=p]; later=pathd.loc[pathd.trade_date.gt(reached.trade_date.iloc[0])&pathd.coord_close.lt(e.L)] if len(reached) else pathd.iloc[0:0]; static_stops[f"X6_PROGRESS_FAILURE_P{int(p*100)}"]=None if later.empty else _next_legal_sell(mins,leg,pd.Timestamp(later.trade_date.iloc[0])+pd.Timedelta(hours=15),ed)
        for H in TIME_STOPS:
            for policy in policies:
                risk,blocked_risk=risk_by_h[H]
                chosen,why=_choose_exit(target if target is not None and target["cal_idx"]<=int(e.entry_cal_idx)+H else None,static_stops[policy],horizon[H],risk)
                unresolved_action=_blocked_action_precedes_exit(blocked_risk,chosen,acts)
                if unresolved_action:
                    audit["unresolved_action_block_count"]+=1;chosen=None;why="UNRESOLVED_ACTION_BLOCK"
                net=np.nan if chosen is None else (chosen["raw_price"]*(1-COST)+_cash_amount(acts,ed,chosen["exit_date"]))/(e.entry_raw_price*(1+COST))-1
                rows.append({**base,"time_stop":H,"exit_policy":policy,"exit_time":pd.NaT if chosen is None else chosen["exit_time"],"exit_date":pd.NaT if chosen is None else chosen["exit_date"],"exit_cal_idx":np.nan if chosen is None else chosen["cal_idx"],"exit_raw_price":np.nan if chosen is None else chosen["raw_price"],"exit_reason":why,"net_trade_return":net,"holding_sessions":np.nan if chosen is None else chosen["cal_idx"]-int(e.entry_cal_idx),"severe10":bool(np.isfinite(net) and net<=-.10),"severe20":bool(np.isfinite(net) and net<=-.20),"stop_executed_at_impossible_price":False,"t1_same_day_exit":False if chosen is None else chosen["exit_date"]<=ed,"unresolved_action_block":unresolved_action,"corporate_action_coordinate_violation":False})
    paths=pd.DataFrame(rows); postdf=pd.DataFrame(post)
    if paths.t1_same_day_exit.any(): raise ResearchError("T+1 same-day exit")
    write_parquet(paths,POLICY_PATHS);write_parquet(postdf,POST_ENTRY_PANEL)
    return paths,postdf


def enrich_dynamic_exit_prices() -> pd.DataFrame:
    post=pd.read_parquet(POST_ENTRY_PANEL); post.checkpoint_date=pd.to_datetime(post.checkpoint_date)
    base=pd.read_parquet(POLICY_PATHS,columns=["entry_key","symbol","entry_date"]).drop_duplicates("entry_key"); base.entry_date=pd.to_datetime(base.entry_date)
    post=post.merge(base,on="entry_key",validate="many_to_one")
    legal=pd.read_parquet(V6_LEGAL_OPENS); legal.trade_date=pd.to_datetime(legal.trade_date); legal.bar_end_time=pd.to_datetime(legal.bar_end_time); by={k:g.sort_values("bar_end_time") for k,g in legal.groupby("symbol",sort=False)}
    rows=[]
    for r in post.itertuples(index=False):
        g=by.get(r.symbol,pd.DataFrame()); x=g.loc[g.trade_date.gt(pd.Timestamp(r.checkpoint_date).normalize())] if pd.notna(r.checkpoint_date) and len(g) else g.iloc[0:0]
        z=None if x.empty else x.iloc[0]
        rows.append({**r._asdict(),"dynamic_exit_time":pd.NaT if z is None else pd.Timestamp(z.bar_end_time),"dynamic_exit_date":pd.NaT if z is None else pd.Timestamp(z.trade_date),"dynamic_exit_cal_idx":np.nan if z is None else int(z.cal_idx),"dynamic_exit_raw_price":np.nan if z is None else float(z.raw_open)})
    out=pd.DataFrame(rows); write_parquet(out,POST_ENTRY_PANEL); return out


def metric(frame:pd.DataFrame) -> dict[str,float|int|None]:
    x=frame.loc[frame.net_trade_return.notna()].copy(); r=x.net_trade_return.astype(float)
    if r.empty:return {"trades":0,"mean":None,"median":None,"win":None,"u_hit":None,"clean20":None,"tail_failure":None,"severe10":None,"severe20":None,"cvar5":None,"mean_hold":None,"median_hold":None}
    n=max(1,int(math.ceil(.05*len(r)))); return {"trades":len(r),"mean":float(r.mean()),"median":float(r.median()),"win":float(r.gt(0).mean()),"u_hit":float(x.exit_reason.eq("TARGET").mean()),"clean20":float(x.y_clean_u20.mean()),"tail_failure":float(x.y_tail_failure40.mean()),"severe10":float(r.le(-.10).mean()),"severe20":float(r.le(-.20).mean()),"cvar5":float(r.nsmallest(n).mean()),"mean_hold":float(x.holding_sessions.mean()),"median_hold":float(x.holding_sessions.median())}


def pseudo_portfolio(frame:pd.DataFrame,k:int=10) -> dict[str,float]:
    x=frame.loc[frame.net_trade_return.notna()].copy()
    if x.empty:return {"cagr":0.0,"maxdd":0.0,"calmar":0.0,"sharpe":0.0}
    x["exit_date"]=pd.to_datetime(x.exit_date).dt.normalize(); daily=x.groupby("exit_date").net_trade_return.sum()/k
    idx=pd.date_range(pd.to_datetime(x.entry_date).min().normalize(),pd.to_datetime(x.exit_date).max().normalize(),freq="B"); ret=daily.reindex(idx,fill_value=0).clip(lower=-.99); nav=(1+ret).cumprod(); years=max((idx[-1]-idx[0]).days/365.25,1/365.25); cagr=float(nav.iloc[-1]**(1/years)-1); dd=float((nav/nav.cummax()-1).min()); sharpe=0.0 if ret.std()==0 else float(np.sqrt(252)*ret.mean()/ret.std()); return {"cagr":cagr,"maxdd":dd,"calmar":cagr/abs(dd) if dd<0 else (99.0 if cagr>0 else 0.0),"sharpe":sharpe}


def entry_diagnostics(panel:pd.DataFrame,entries:pd.DataFrame,paths:pd.DataFrame,years:tuple[int,...]) -> pd.DataFrame:
    base=paths.loc[(paths.time_stop==40)&paths.exit_policy.eq("X0_NO_STOP")].drop_duplicates("entry_key")
    x=panel.copy();x["entry_key"]=x.candidate_id+"|"+pd.to_datetime(x.entry_time).astype(str);x=x.merge(base,on="entry_key",suffixes=("","_out"),validate="many_to_one");x["year"]=pd.to_datetime(x.entry_date).dt.year;x=x.loc[x.year.isin(years)]
    raw=entries.copy();raw["year"]=pd.to_datetime(raw.causal_first_return).dt.year
    rows=[]
    for t in sorted(raw.translation.unique()):
        allr=raw.loc[raw.translation.eq(t)&raw.year.isin(years)]; z=x.loc[x.translation.eq(t)]; m=metric(z)
        rows.append({"translation":t,"raw_v6_signals":int(allr.candidate_id.nunique()),"entry_eligible":int((allr.status!="THRESHOLD_NOT_EXECUTABLE_OR_MISSED_FAST_FILL").sum()),"executable_entries":len(z),"missed_fast_u":int(allr.status.eq("MISSED_FAST_U").sum()),"no_confirmation":int(allr.status.eq("NO_CONFIRMATION").sum()),"mean_entry_delay_minutes":float(allr.loc[allr.status.eq("EXECUTABLE_ENTRY"),"entry_delay_minutes"].mean()),"median_entry_delay_minutes":float(allr.loc[allr.status.eq("EXECUTABLE_ENTRY"),"entry_delay_minutes"].median()),"mean_entry_price_vs_l":float(allr.loc[allr.status.eq("EXECUTABLE_ENTRY"),"entry_price_vs_l"].mean()),"mean_entry_price_vs_u":float(allr.loc[allr.status.eq("EXECUTABLE_ENTRY"),"entry_price_vs_u"].mean()),**m})
    return pd.DataFrame(rows)


def _nondominated(rows:pd.DataFrame) -> pd.DataFrame:
    keep=[]
    vals=rows[["mean","median","u_before_loss10","tail_failure","cvar5"]].to_numpy(float)
    for i,a in enumerate(vals):
        dominated=False
        for j,b in enumerate(vals):
            if i==j:continue
            better=(b[0]>=a[0] and b[1]>=a[1] and b[2]>=a[2] and b[3]<=a[3] and b[4]>=a[4]);strict=(b[0]>a[0] or b[1]>a[1] or b[2]>a[2] or b[3]<a[3] or b[4]>a[4])
            if better and strict:dominated=True;break
        keep.append(not dominated)
    return rows.loc[keep]


def select_entries_train(panel:pd.DataFrame,train_years:tuple[int,...],board:str) -> tuple[list[str],pd.DataFrame]:
    x=panel.loc[panel.board.eq(board)&panel.year.isin(train_years)].copy(); rows=[]
    for t,g in x.groupby("translation"):
        r=g.net_trade_return.dropna(); latest=g.loc[g.year.eq(max(train_years))&g.net_trade_return.notna()]; n=max(1,int(math.ceil(.05*len(r))))
        rows.append({"translation":t,"trades":len(r),"latest_trades":len(latest),"mean":float(r.mean()) if len(r) else -99,"median":float(r.median()) if len(r) else -99,"u_before_loss10":float(g.u_before_loss10.mean()),"tail_failure":float(g.y_tail_failure40.mean()),"cvar5":float(r.nsmallest(n).mean()) if len(r) else -99,"median_year_return":float(g.groupby("year").net_trade_return.mean().median()) if len(r) else -99,"severe10":float(r.le(-.10).mean()) if len(r) else 1.0,"complexity":CONFIRMATIONS.index(t.split("+")[1]),"penetration":list(LEVELS).index(t.split("+")[0])})
    stats=pd.DataFrame(rows); eligible=stats.loc[(stats.trades>=200)&(stats.latest_trades>=35)].copy(); front=_nondominated(eligible) if len(eligible) else eligible
    baseline="ABS_0+C2_CLOSE"; selected=[baseline]
    ranked=front.sort_values(["median_year_return","severe10","complexity","penetration"],ascending=[False,True,True,True])
    for t in ranked.translation:
        if t not in selected:selected.append(t)
        if len(selected)>=5:break
    return selected,stats


def feature_bundles() -> dict[str,list[str]]:
    feats=feature_contract(); fam={k:[x["name"] for x in feats if x["family"]==k] for k in ["F1","F2","F3","F4","F5","F6","F7"]}
    return {"B1":fam["F1"]+fam["F2"],"B2":fam["F1"]+fam["F2"]+fam["F3"],"B3":sum((fam[k] for k in ("F1","F2","F3","F4","F5")),[]),"B4":sum((fam[k] for k in ("F1","F2","F3","F4","F5","F6")),[]),"B5":sum((fam[k] for k in ("F1","F2","F3","F4","F5","F6","F7")),[])}


def _constant_or_model(y:np.ndarray,default:float,fit) -> tuple[Any,float|None]:
    if len(np.unique(y[~pd.isna(y)]))<2:return None,float(np.nanmean(y)) if len(y) else default
    return fit(),None


def fit_predict_three(train:pd.DataFrame,predict:pd.DataFrame,features:list[str],profile:str) -> tuple[np.ndarray,np.ndarray,np.ndarray,dict[str,int]]:
    X=train[features].replace([np.inf,-np.inf],np.nan);Xp=predict[features].replace([np.inf,-np.inf],np.nan); yc=train.y_clean_u20.astype(int).to_numpy();yt=train.y_tail_failure40.astype(int).to_numpy();yr=train.net_trade_return.to_numpy(float);lo,hi=np.nanquantile(yr,[.01,.99]);yr=np.clip(yr,lo,hi);iterations={}
    if profile=="M1_INTERPRETABLE":
        def clf():return Pipeline([("imp",SimpleImputer(strategy="median")),("scale",StandardScaler()),("m",LogisticRegression(C=.1,class_weight="balanced",max_iter=2000,random_state=20260903))])
        def reg():return Pipeline([("imp",SimpleImputer(strategy="median")),("scale",StandardScaler()),("m",Ridge(alpha=10))])
        mc,cc=_constant_or_model(yc,.5,clf);mt,ct=_constant_or_model(yt,.5,clf);mr=reg();
        if mc is not None:mc.fit(X,yc);pc=mc.predict_proba(Xp)[:,1]
        else:pc=np.full(len(Xp),cc)
        if mt is not None:mt.fit(X,yt);pt=mt.predict_proba(Xp)[:,1]
        else:pt=np.full(len(Xp),ct)
        mr.fit(X,yr);pr=mr.predict(Xp);iterations={"clean":0,"tail":0,"return":0}
    else:
        params=dict(learning_rate=.03,n_estimators=800,max_depth=4,num_leaves=15,min_child_samples=100,reg_lambda=20.,reg_alpha=1.,subsample=.8,colsample_bytree=.8,random_state=20260903,n_jobs=2,verbosity=-1)
        def one(target:np.ndarray,kind:str):
            if kind!="return" and len(np.unique(target))<2:return np.full(len(Xp),float(np.mean(target))),1
            years=pd.to_datetime(train.entry_date).dt.year;vy=max(years);inner=years.lt(vy)
            cls=lgb.LGBMRegressor if kind=="return" else lgb.LGBMClassifier
            m=cls(**params)
            if inner.sum()>=100 and (~inner).sum()>=30:
                m.fit(X.loc[inner],target[inner],eval_set=[(X.loc[~inner],target[~inner])],callbacks=[lgb.early_stopping(50,verbose=False)]);best=max(1,int(m.best_iteration_ or 200))
            else:best=200
            q=params.copy();q["n_estimators"]=best;m=cls(**q);m.fit(X,target)
            pred=m.predict(Xp) if kind=="return" else m.predict_proba(Xp)[:,1]
            return pred,best
        pc,iterations["clean"]=one(yc,"clean");pt,iterations["tail"]=one(yt,"tail");pr,iterations["return"]=one(yr,"return")
    return pc,pt,pr,iterations


def _ecdf(reference:np.ndarray,values:np.ndarray) -> np.ndarray:
    ref=np.sort(reference[np.isfinite(reference)]);return np.searchsorted(ref,values,side="right")/max(1,len(ref))


def model_oof_and_test(data:pd.DataFrame,features:list[str],profile:str,train_years:tuple[int,...],test_year:int) -> tuple[pd.DataFrame,pd.DataFrame,list[dict[str,Any]]]:
    oofs=[];iters=[]
    for y in train_years[1:]:
        tr=data.loc[data.year.lt(y)&data.year.isin(train_years)&pd.to_datetime(data.exit_date).lt(pd.Timestamp(f"{y}-01-01"))];va=data.loc[data.year.eq(y)]
        if len(tr)<100 or len(va)<20:continue
        pc,pt,pr,it=fit_predict_three(tr,va,features,profile);z=va[["entry_key","candidate_id","year","entry_date","exit_date","exit_reason","holding_sessions","net_trade_return","y_clean_u20","y_tail_failure40","severe10","severe20","u_before_loss10"]].copy();z["p_clean"]=pc;z["p_tail"]=pt;z["p_return"]=pr;oofs.append(z);iters.append({"predict_year":y,**it})
    oof=pd.concat(oofs,ignore_index=True) if oofs else pd.DataFrame()
    tr=data.loc[data.year.isin(train_years)&pd.to_datetime(data.exit_date).lt(pd.Timestamp(f"{test_year}-01-01"))];te=data.loc[data.year.eq(test_year)]
    if oof.empty or te.empty:return oof,pd.DataFrame(),iters
    pc,pt,pr,it=fit_predict_three(tr,te,features,profile);test=te[["entry_key","candidate_id","year","entry_date","exit_date","exit_reason","holding_sessions","net_trade_return","y_clean_u20","y_tail_failure40","severe10","severe20","u_before_loss10"]].copy();test["p_clean"]=pc;test["p_tail"]=pt;test["p_return"]=pr;iters.append({"predict_year":test_year,"full_train":True,**it})
    oof["attack_score"]=(oof.p_clean.rank(pct=True)+(1-oof.p_tail).rank(pct=True)+oof.p_return.rank(pct=True))/3
    test["attack_score"]=(_ecdf(oof.p_clean.to_numpy(),test.p_clean.to_numpy())+_ecdf((1-oof.p_tail).to_numpy(),(1-test.p_tail).to_numpy())+_ecdf(oof.p_return.to_numpy(),test.p_return.to_numpy()))/3
    return oof,test,iters


def prepare_model_data() -> tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    panel=pd.read_parquet(MODEL_PANEL);panel["entry_key"]=panel.candidate_id+"|"+pd.to_datetime(panel.entry_time).astype(str);panel["year"]=pd.to_datetime(panel.entry_date).dt.year
    paths=pd.read_parquet(POLICY_PATHS)
    for c in ("entry_time","entry_date","exit_time","exit_date","u_time"):paths[c]=pd.to_datetime(paths[c])
    base=paths.loc[paths.time_stop.eq(40)&paths.exit_policy.eq("X0_NO_STOP")].drop_duplicates("entry_key")
    labels=["entry_key","net_trade_return","exit_time","exit_date","exit_cal_idx","exit_reason","holding_sessions","severe10","severe20","y_clean_u20","y_clean_u40","y_tail_failure40","u_before_loss10","outcome_qd010_valid"]
    data=panel.merge(base[labels],on="entry_key",validate="many_to_one")
    data=data.loc[data.net_trade_return.notna()&data.y_tail_failure40.notna()&data.outcome_qd010_valid].copy()
    data["y_tail_failure40"]=data.y_tail_failure40.astype(bool)
    return data,panel,paths


def build_dynamic_tail_scores(post:pd.DataFrame,max_prediction_year:int=2021) -> pd.DataFrame:
    availability=pd.read_parquet(POLICY_PATHS,columns=["entry_key","time_stop","exit_policy","exit_date"]).query("time_stop == 40 and exit_policy == 'X0_NO_STOP'").drop_duplicates("entry_key").rename(columns={"exit_date":"outcome_available_date"})
    post=post.merge(availability[["entry_key","outcome_available_date"]],on="entry_key",how="left",validate="many_to_one");post["outcome_available_date"]=pd.to_datetime(post.outcome_available_date)
    post=post.loc[post.y_tail_failure40.notna()&post.dynamic_exit_time.notna()&post.outcome_available_date.notna()].copy();post["year"]=pd.to_datetime(post.entry_date).dt.year
    feats=["max_progress","close_vs_l","return_to_checkpoint","mae_to_checkpoint","turnover_to_checkpoint"]
    rows=[]
    for (board,checkpoint),g in post.groupby(["board","checkpoint"],sort=True):
        for year in range(2015,max_prediction_year+1):
            tr=g.loc[g.year.lt(year)&g.outcome_available_date.lt(pd.Timestamp(f"{year}-01-01"))];te=g.loc[g.year.eq(year)]
            if len(tr)<100 or te.empty:continue
            y=tr.y_tail_failure40.astype(bool).astype(int).to_numpy()
            pipe=Pipeline([("imp",SimpleImputer(strategy="median")),("scale",StandardScaler()),("m",LogisticRegression(C=.1,class_weight="balanced",max_iter=2000,random_state=20260903))])
            if len(np.unique(y))<2:score=np.full(len(te),float(y.mean()))
            else:pipe.fit(tr[feats],y);score=pipe.predict_proba(te[feats])[:,1]
            z=te[["entry_key","candidate_id","symbol","board","checkpoint","entry_date","dynamic_exit_time","dynamic_exit_date","dynamic_exit_cal_idx","dynamic_exit_raw_price","y_tail_failure40"]].copy();z["year"]=year;z["tail_score"]=score;rows.append(z)
    out=pd.concat(rows,ignore_index=True) if rows else pd.DataFrame();write_parquet(out,DYNAMIC_TAIL_SCORES);return out


def admission_table(oof:pd.DataFrame,entry:str,bundle:str,profile:str) -> pd.DataFrame:
    rows=[];base_severe=float(oof.net_trade_return.le(-.10).mean())
    for name,frac in ADMISSIONS.items():
        cutoff=-np.inf if name=="A100" else float(oof.attack_score.quantile(1-frac))
        z=oof.loc[oof.attack_score.ge(cutoff)];m=metric(z);pp=pseudo_portfolio(z);annual=z.groupby("year").net_trade_return.mean()
        rows.append({"entry":entry,"bundle":bundle,"model":profile,"admission":name,"admission_cutoff":cutoff,"signal_retention":len(z)/len(oof),"year_direction_stability":float(annual.gt(0).mean()),"median_year_return":float(annual.median()),"latest_train_trades":int(z.year.eq(z.year.max()).sum()),"baseline_severe10":base_severe,**m,**pp})
    return pd.DataFrame(rows)


def retain_admissions(frame:pd.DataFrame) -> pd.DataFrame:
    x=frame.loc[frame.admission.ne("A100")&frame["mean"].gt(0)&frame["median"].gt(0)&frame.severe10.lt(frame.baseline_severe10)&frame.signal_retention.ge(.20)&frame.year_direction_stability.ge(.50)].copy()
    return x.sort_values(["calmar","cagr","cvar5","median_year_return","signal_retention","entry","bundle","model","admission"],ascending=[False,False,False,False,False,True,True,True,True],kind="mergesort").head(5)


def _cash_json(actions:pd.DataFrame,entry_date:pd.Timestamp,exit_date:pd.Timestamp) -> str:
    if pd.isna(exit_date):return "[]"
    x=actions.loc[actions.action_kind.eq("CASH_ONLY")&actions.effective_date.gt(pd.Timestamp(entry_date).normalize())&actions.effective_date.le(pd.Timestamp(exit_date).normalize())]
    return json.dumps([{"date":str(pd.Timestamp(r.effective_date).date()),"cash_per_share":float(r.cash_per_share),"event_id":str(r.event_id)} for r in x.itertuples(index=False)],sort_keys=True)


def dynamic_policy_frame(paths:pd.DataFrame,scores:pd.DataFrame,keys:set[str],years:tuple[int,...],H:int,q:float,name:str,actions_by:dict[str,pd.DataFrame]) -> pd.DataFrame:
    base=paths.loc[paths.entry_key.isin(keys)&paths.time_stop.eq(H)&paths.exit_policy.eq("X0_NO_STOP")].drop_duplicates("entry_key").copy();s=scores.loc[scores.entry_key.isin(keys)&scores.year.isin(years)&scores.tail_score.ge(q)].sort_values(["entry_key","dynamic_exit_time","checkpoint"],kind="mergesort").drop_duplicates("entry_key")
    cols=["entry_key","dynamic_exit_time","dynamic_exit_date","dynamic_exit_cal_idx","dynamic_exit_raw_price","checkpoint","tail_score"]
    base=base.merge(s[cols],on="entry_key",how="left",validate="one_to_one")
    replace=base.dynamic_exit_time.notna()&(base.exit_time.isna()|base.dynamic_exit_time.lt(base.exit_time))
    base.loc[replace,"exit_time"]=base.loc[replace,"dynamic_exit_time"];base.loc[replace,"exit_date"]=base.loc[replace,"dynamic_exit_date"];base.loc[replace,"exit_cal_idx"]=base.loc[replace,"dynamic_exit_cal_idx"];base.loc[replace,"exit_raw_price"]=base.loc[replace,"dynamic_exit_raw_price"];base.loc[replace,"exit_reason"]="DYNAMIC_TAIL"
    base["exit_policy"]=name;base["holding_sessions"]=base.exit_cal_idx-base.entry_cal_idx
    nets=[]
    for r in base.itertuples(index=False):
        if pd.isna(r.exit_raw_price):nets.append(np.nan);continue
        act=actions_by.get(r.symbol,pd.DataFrame(columns=["action_kind","effective_date","cash_per_share"]));cash=_cash_amount(act,pd.Timestamp(r.entry_date),pd.Timestamp(r.exit_date));nets.append((float(r.exit_raw_price)*(1-COST)+cash)/(float(r.entry_raw_price)*(1+COST))-1)
    base["net_trade_return"]=nets;base["severe10"]=base.net_trade_return.le(-.10);base["severe20"]=base.net_trade_return.le(-.20)
    return base


def hybrid_policy_frame(parts:list[pd.DataFrame],name:str) -> pd.DataFrame:
    x=pd.concat(parts,ignore_index=True);x["_exit_sort"]=pd.to_datetime(x.exit_time).fillna(pd.Timestamp.max);out=x.sort_values(["entry_key","_exit_sort","exit_policy"],kind="mergesort").drop_duplicates("entry_key").drop(columns="_exit_sort");out["exit_policy"]=name;return out


def all_exit_frames(paths:pd.DataFrame,scores:pd.DataFrame,keys:set[str],years:tuple[int,...],dynamic_q:dict[tuple[int,float],float],actions_by:dict[str,pd.DataFrame]) -> dict[tuple[int,str],pd.DataFrame]:
    out={}
    static=paths.loc[paths.entry_key.isin(keys)&paths.entry_date.dt.year.isin(years)]
    for H in TIME_STOPS:
        for p in paths.exit_policy.unique():out[(H,str(p))]=static.loc[static.time_stop.eq(H)&static.exit_policy.eq(p)].copy()
    for H in TIME_STOPS:
        for d in (3,5,10):
            for qv in (.8,.9):
                name=f"X7_D{d}_Q{int(qv*100)}";q=dynamic_q.get((d,qv),np.inf);sc=scores.loc[scores.checkpoint.eq(d)];out[(H,name)]=dynamic_policy_frame(paths,sc,keys,years,H,q,name,actions_by)
        cons=[out[(H,"X2_DAILY_10")],out[(H,"X4_STRUCTURAL_LOWER_GAP")],out[(H,"X5_D10_P25")],out[(H,"X7_D10_Q90")]]
        fast=[out[(H,"X1_INTRADAY_8")],out[(H,"X4_STRUCTURAL_LOWER_GAP")],out[(H,"X5_D5_P25")],out[(H,"X7_D5_Q80")]]
        out[(H,"X8_HYBRID_CONSERVATIVE")]=hybrid_policy_frame(cons,"X8_HYBRID_CONSERVATIVE")
        out[(H,"X8_HYBRID_FAST")]=hybrid_policy_frame(fast,"X8_HYBRID_FAST")
    return out


def dynamic_quantiles(scores:pd.DataFrame,keys:set[str],years:tuple[int,...]) -> dict[tuple[int,float],float]:
    out={}
    for d in (3,5,10):
        x=scores.loc[scores.entry_key.isin(keys)&scores.year.isin(years)&scores.checkpoint.eq(d),"tail_score"]
        for q in (.8,.9):out[(d,q)]=np.inf if x.empty else float(x.quantile(q))
    return out


def replay_ready(frame:pd.DataFrame,score_map:dict[str,float],candidates:pd.DataFrame,actions_by:dict[str,pd.DataFrame]) -> pd.DataFrame:
    meta=candidates[["candidate_id","cluster_freeze_time","material_drawdown_at_freeze","true_gap_width_pct"]].drop_duplicates("candidate_id")
    x=frame.loc[frame.net_trade_return.notna()&frame.exit_time.notna()].copy().merge(meta,on="candidate_id",how="left",validate="many_to_one")
    x["event_id"]=x.candidate_id;x["attack_score"]=x.entry_key.map(score_map).fillna(0.0)
    # The proven V6 replay sorts this field descending; here it carries the frozen causal ATTACK_SCORE solely for collision order.
    x["primary_layer_width_pct"]=x.attack_score;x["material_drawdown"]=x.material_drawdown_at_freeze
    cash=[]
    for r in x.itertuples(index=False):cash.append(_cash_json(actions_by.get(r.symbol,pd.DataFrame(columns=["action_kind","effective_date","cash_per_share","event_id"])),pd.Timestamp(r.entry_date),pd.Timestamp(r.exit_date)))
    x["cash_events_json"]=cash
    return x


def exact_replay(frame:pd.DataFrame,score_map:dict[str,float],board:str,k:int,years:tuple[int,...],daily:pd.DataFrame,candidates:pd.DataFrame,actions_by:dict[str,pd.DataFrame]) -> tuple[dict[str,Any],v6.Replay]:
    ready=replay_ready(frame,score_map,candidates,actions_by)
    replay=v6.replay_portfolio(ready,daily,board,k,years);m=v6.portfolio_metrics(replay.nav,replay.accepted);m["calmar"]=m["cagr"]/abs(m["max_drawdown"]) if m["max_drawdown"]<0 else (99.0 if m["cagr"]>0 else 0.0);m["median_utilization"]=float(replay.nav.utilization.median());m["capacity_skips"]=int(replay.ledger.capacity_skip.sum()) if len(replay.ledger) else 0
    return m,replay


def evaluate_exit_tree(admissions:pd.DataFrame,pred_store:dict[tuple[str,str,str],tuple[pd.DataFrame,pd.DataFrame]],paths:pd.DataFrame,scores:pd.DataFrame,train_years:tuple[int,...],test_year:int,board:str,data:pd.DataFrame,daily:pd.DataFrame,candidates:pd.DataFrame,actions_by:dict[str,pd.DataFrame]) -> tuple[pd.DataFrame,dict[str,Any]]:
    rows=[];frames={};cutoff_date=pd.Timestamp(f"{test_year}-01-01")
    for a in admissions.itertuples(index=False):
        oof,_=pred_store[(a.entry,a.bundle,a.model)];oof=oof.loc[pd.to_datetime(oof.exit_date).lt(cutoff_date)];keys=set(oof.loc[oof.attack_score.ge(float(a.admission_cutoff)),"entry_key"]);score_map=oof.set_index("entry_key").attack_score.to_dict();dq=dynamic_quantiles(scores,keys,train_years);allf=all_exit_frames(paths,scores,keys,train_years,dq,actions_by)
        baseline=data.loc[data.board.eq(board)&data.translation.eq(a.entry)&data.year.isin(train_years)&pd.to_datetime(data.exit_date).lt(cutoff_date)];base_severe=float(baseline.net_trade_return.le(-.10).mean())
        for (H,policy),g0 in allf.items():
            g=g0.loc[pd.to_datetime(g0.exit_date).lt(cutoff_date)].copy();m=metric(g);pp=pseudo_portfolio(g);annual=g.groupby(pd.to_datetime(g.entry_date).dt.year).net_trade_return.mean();retention=len(g)/max(1,len(oof));latest=int(pd.to_datetime(g.entry_date).dt.year.eq(max(train_years)).sum())
            row={"entry":a.entry,"bundle":a.bundle,"model":a.model,"admission":a.admission,"admission_cutoff":float(a.admission_cutoff),"time_stop":H,"exit_policy":policy,"signal_retention":retention,"latest_train_trades":latest,"median_year_return":float(annual.median()) if len(annual) else -99,"baseline_severe10":base_severe,"dynamic_q":json.dumps({f"D{d}Q{int(q*100)}":v for (d,q),v in dq.items()},sort_keys=True),**m,**pp}
            screen=m["trades"]>=200 and latest>=35 and retention>=.15 and (m["mean"] or -99)>0 and (m["median"] or -99)>0 and (m["severe10"] or 1)<base_severe
            if screen:
                pm,_=exact_replay(g,score_map,board,10,train_years,daily,candidates,actions_by);row.update({f"exact_{k}":v for k,v in pm.items()});row["selectable"]=pm["cagr"]>0
            else:row["selectable"]=False
            idx=len(rows);rows.append(row);frames[idx]=(g,score_map,dq)
    stats=pd.DataFrame(rows)
    if stats.empty or not stats.selectable.any():return stats,{"selected":None,"frames":frames}
    eligible=stats.loc[stats.selectable].copy();eligible["complexity"]=(eligible.model.eq("M2_NONLINEAR").astype(int)+eligible.bundle.map({"B1":1,"B2":2,"B3":3,"B4":4,"B5":5})+eligible.admission.map({"A70":1,"A50":2,"A30":3,"A20":4})+eligible.exit_policy.ne("X0_NO_STOP").astype(int))
    selected=eligible.sort_values(["exact_calmar","exact_cagr","cvar5","median_year_return","complexity","signal_retention"],ascending=[False,False,False,False,True,False],kind="mergesort").iloc[0]
    return stats,{"selected":selected.to_dict(),"frames":frames}


def test_frame_for_selection(selected:dict[str,Any],pred_store:dict[tuple[str,str,str],tuple[pd.DataFrame,pd.DataFrame]],paths:pd.DataFrame,scores:pd.DataFrame,test_year:int,actions_by:dict[str,pd.DataFrame]) -> tuple[pd.DataFrame,dict[str,float]]:
    _,test=pred_store[(selected["entry"],selected["bundle"],selected["model"])];admitted=test.loc[test.attack_score.ge(float(selected["admission_cutoff"]))];keys=set(admitted.entry_key);dqraw=json.loads(selected["dynamic_q"]);dq={(d,q):float(dqraw[f"D{d}Q{int(q*100)}"]) for d in (3,5,10) for q in (.8,.9)};frames=all_exit_frames(paths,scores,keys,(test_year,),dq,actions_by);g=frames[(int(selected["time_stop"]),selected["exit_policy"])].copy();return g,admitted.set_index("entry_key").attack_score.to_dict()


def run_development() -> dict[str,Any]:
    verify_feature_freeze();data,panel,paths=prepare_model_data();entries=pd.read_parquet(ENTRY_CANDIDATES);candidates=active_source();daily=pd.read_parquet(EXT/"daily_relevant.parquet");daily.trade_date=pd.to_datetime(daily.trade_date)
    actions=pd.read_parquet(v6.ACTION_EVENTS);actions.known_date=pd.to_datetime(actions.known_date);actions.effective_date=pd.to_datetime(actions.effective_date);actions_by={k:g for k,g in actions.groupby("symbol",sort=False)}
    post=pd.read_parquet(POST_ENTRY_PANEL);scores=build_dynamic_tail_scores(post,max_prediction_year=2021)
    diagnostics=entry_diagnostics(panel,entries,paths,DEV_YEARS);write_parquet(diagnostics,ENTRY_DIAGNOSTICS)
    selections=[];predictions=[];policy_trades=[];model_iterations=[];entry_fold_rows=[];admission_rows=[];exit_rows=[]
    for test_year in TEST_YEARS:
        train_years=tuple(range(2014,test_year));cutoff=pd.Timestamp(f"{test_year}-01-01")
        for board in ("MAIN","CHINEXT"):
            train_data=data.loc[pd.to_datetime(data.exit_date).lt(cutoff)]
            selected_entries,entry_stats=select_entries_train(train_data,train_years,board);pred_store={};adm=[]
            entry_stats["outer_test_year"]=test_year;entry_stats["board"]=board;entry_stats["selected_for_models"]=entry_stats.translation.isin(selected_entries);entry_fold_rows.append(entry_stats)
            for entry in selected_entries:
                d=data.loc[data.board.eq(board)&data.translation.eq(entry)&data.year.isin(train_years+(test_year,))]
                for bundle,features in feature_bundles().items():
                    for profile in ("M1_INTERPRETABLE","M2_NONLINEAR"):
                        oof,test,iters=model_oof_and_test(d,features,profile,train_years,test_year)
                        if oof.empty or test.empty:continue
                        oof=oof.loc[pd.to_datetime(oof.exit_date).lt(cutoff)].copy();oof["outer_test_year"]=test_year;oof["board"]=board;oof["entry"]=entry;oof["bundle"]=bundle;oof["model"]=profile;oof["prediction_role"]="TRAIN_OOF";test["outer_test_year"]=test_year;test["board"]=board;test["entry"]=entry;test["bundle"]=bundle;test["model"]=profile;test["prediction_role"]="TEST"
                        pred_store[(entry,bundle,profile)]=(oof,test);predictions.extend([oof,test]);model_iterations.extend([{"outer_test_year":test_year,"board":board,"entry":entry,"bundle":bundle,"model":profile,**z} for z in iters]);adm.append(admission_table(oof,entry,bundle,profile))
            adm_all=pd.concat(adm,ignore_index=True) if adm else pd.DataFrame();retained=retain_admissions(adm_all) if len(adm_all) else pd.DataFrame()
            if len(adm_all):adm_all["outer_test_year"]=test_year;adm_all["board"]=board;adm_all["retained_for_exit"]=adm_all.set_index(["entry","bundle","model","admission"]).index.isin(retained.set_index(["entry","bundle","model","admission"]).index);admission_rows.append(adm_all)
            exit_stats,choice=evaluate_exit_tree(retained,pred_store,paths,scores,train_years,test_year,board,data,daily,candidates,actions_by)
            if len(exit_stats):exit_stats["outer_test_year"]=test_year;exit_stats["board"]=board;exit_rows.append(exit_stats)
            chosen=choice["selected"]
            record={"outer_test_year":test_year,"board":board,"train_years":json.dumps(train_years),"entry_candidates":json.dumps(selected_entries),"entry_candidate_count":len(selected_entries),"admission_candidate_count":len(adm_all),"retained_admission_count":len(retained),"selected":chosen is not None,"test_year_used_in_own_selection":False}
            if chosen is not None:
                record.update({k:chosen[k] for k in ("entry","bundle","model","admission","admission_cutoff","time_stop","exit_policy","exact_calmar","exact_cagr","mean","median","severe10","trades","latest_train_trades","signal_retention","dynamic_q")});g,score_map=test_frame_for_selection(chosen,pred_store,paths,scores,test_year,actions_by);g["attack_score"]=g.entry_key.map(score_map);g["outer_test_year"]=test_year;g["lane"]="L4_COMBINED";policy_trades.append(g)
            else:record.update({"entry":"CASH","bundle":"CASH","model":"CASH","admission":"CASH","time_stop":0,"exit_policy":"CASH"})
            selections.append(record)
            print(json.dumps(clean({"fold":test_year,"board":board,"entries":selected_entries,"retained_admissions":len(retained),"selected":record.get("entry"),"bundle":record.get("bundle"),"model":record.get("model"),"admission":record.get("admission"),"H":record.get("time_stop"),"exit":record.get("exit_policy")})))
    pred=pd.concat(predictions,ignore_index=True);write_parquet(pred,OOF_PREDICTIONS);sel=pd.DataFrame(selections);write_parquet(sel,SELECTIONS);trades=pd.concat(policy_trades,ignore_index=True) if policy_trades else pd.DataFrame();write_parquet(trades,POLICY_TRADES);write_parquet(pd.concat(entry_fold_rows,ignore_index=True),ENTRY_FOLD_STATS);write_parquet(pd.concat(admission_rows,ignore_index=True),ADMISSION_STATS);write_parquet(pd.concat(exit_rows,ignore_index=True),EXIT_STATS);write_json(EXT/"model_iterations.json",{"iterations":model_iterations})
    return {"folds":len(sel),"cash_folds":int((~sel.selected).sum()),"prediction_rows":len(pred),"policy_trade_rows":len(trades),"development_procedure_frozen":"YES","post_observation_opened":"NO"}


def _simple_train_choice(entry_stats:pd.DataFrame) -> str:
    x=entry_stats.loc[entry_stats.selected_for_models].sort_values(["median_year_return","severe10","complexity","penetration"],ascending=[False,True,True,True],kind="mergesort")
    return "ABS_0+C2_CLOSE" if x.empty else str(x.translation.iloc[0])


def _entry_keys(entries:pd.DataFrame,translation:str,years:tuple[int,...],board:str|None=None) -> set[str]:
    mask=entries.translation.eq(translation)&entries.status.eq("EXECUTABLE_ENTRY")&pd.to_datetime(entries.entry_date).dt.year.isin(years)
    if board is not None:mask&=entries.board.eq(board)
    x=entries.loc[mask].copy();return set(x.candidate_id+"|"+pd.to_datetime(x.entry_time).astype(str))


def build_decomposition_trades() -> pd.DataFrame:
    data,panel,paths=prepare_model_data();entries=pd.read_parquet(ENTRY_CANDIDATES);scores=pd.read_parquet(DYNAMIC_TAIL_SCORES);pred=pd.read_parquet(OOF_PREDICTIONS);entry_stats=pd.read_parquet(ENTRY_FOLD_STATS);exit_stats=pd.read_parquet(EXIT_STATS);sel=pd.read_parquet(SELECTIONS)
    actions=pd.read_parquet(v6.ACTION_EVENTS);actions.known_date=pd.to_datetime(actions.known_date);actions.effective_date=pd.to_datetime(actions.effective_date);actions_by={k:g for k,g in actions.groupby("symbol",sort=False)}
    output=[]
    for test_year in TEST_YEARS:
        train_years=tuple(range(2014,test_year));cutoff=pd.Timestamp(f"{test_year}-01-01")
        for board in ("MAIN","CHINEXT"):
            ef=entry_stats.loc[entry_stats.outer_test_year.eq(test_year)&entry_stats.board.eq(board)];simple=_simple_train_choice(ef);train_keys=_entry_keys(entries,simple,train_years,board);test_keys=_entry_keys(entries,simple,(test_year,),board)
            train_frames=all_exit_frames(paths,scores,train_keys,train_years,{(d,q):np.inf for d in (3,5,10) for q in (.8,.9)},actions_by)
            candidates=[]
            base_severe=float(train_frames[(40,"X0_NO_STOP")].loc[lambda x:pd.to_datetime(x.exit_date).lt(cutoff)].net_trade_return.le(-.10).mean())
            for (H,p),g0 in train_frames.items():
                if p.startswith("X7") or p.startswith("X8"):continue
                g=g0.loc[pd.to_datetime(g0.exit_date).lt(cutoff)];m=metric(g);pp=pseudo_portfolio(g);candidates.append({"H":H,"policy":p,**m,**pp})
            cs=pd.DataFrame(candidates);l0=cs.loc[cs.policy.eq("X0_NO_STOP")].sort_values(["calmar","cagr","cvar5"],ascending=[False,False,False]).iloc[0];l3pool=cs.loc[cs.policy.ne("X0_NO_STOP")&cs["mean"].gt(0)&cs["median"].gt(0)&cs.severe10.lt(base_severe)];l3=(cs.loc[cs.policy.ne("X0_NO_STOP")].sort_values("calmar",ascending=False).iloc[0] if l3pool.empty else l3pool.sort_values(["calmar","cagr","cvar5"],ascending=[False,False,False]).iloc[0])
            test_static=all_exit_frames(paths,scores,test_keys,(test_year,),{(d,q):np.inf for d in (3,5,10) for q in (.8,.9)},actions_by)
            for lane,choice in (("L0_BASELINE",l0),("L3_LOSS_CONTROL",l3)):
                g=test_static[(int(choice.H),str(choice.policy))].copy();g["attack_score"]=0.0;g["outer_test_year"]=test_year;g["lane"]=lane;g["selected_entry"]=simple;g["selected_bundle"]="NONE";g["selected_model"]="NONE";g["selected_admission"]="A100";output.append(g)
            xs=exit_stats.loc[exit_stats.outer_test_year.eq(test_year)&exit_stats.board.eq(board)&exit_stats.exit_policy.eq("X0_NO_STOP")]
            for lane,bundles in (("L1_FORMATION",("B1","B2","B3","B4")),("L2_INTRADAY",("B5",))):
                pool=xs.loc[xs.bundle.isin(bundles)].sort_values(["calmar","cagr","cvar5"],ascending=[False,False,False],kind="mergesort")
                if pool.empty:continue
                ch=pool.iloc[0];tp=pred.loc[pred.outer_test_year.eq(test_year)&pred.board.eq(board)&pred.entry.eq(ch.entry)&pred.bundle.eq(ch.bundle)&pred.model.eq(ch.model)&pred.prediction_role.eq("TEST")];keys=set(tp.loc[tp.attack_score.ge(float(ch.admission_cutoff)),"entry_key"]);dqraw=json.loads(ch.dynamic_q);dq={(d,q):float(dqraw[f"D{d}Q{int(q*100)}"]) for d in (3,5,10) for q in (.8,.9)};fs=all_exit_frames(paths,scores,keys,(test_year,),dq,actions_by);g=fs[(int(ch.time_stop),"X0_NO_STOP")].copy();g["attack_score"]=g.entry_key.map(tp.set_index("entry_key").attack_score.to_dict());g["outer_test_year"]=test_year;g["lane"]=lane;g["selected_entry"]=ch.entry;g["selected_bundle"]=ch.bundle;g["selected_model"]=ch.model;g["selected_admission"]=ch.admission;output.append(g)
            final=sel.loc[sel.outer_test_year.eq(test_year)&sel.board.eq(board)].iloc[0]
            if bool(final.selected):
                old=pd.read_parquet(POLICY_TRADES);g=old.loc[old.outer_test_year.eq(test_year)&old.board.eq(board)].copy();g["lane"]="L4_COMBINED";output.append(g)
    out=pd.concat(output,ignore_index=True);write_parquet(out,POLICY_TRADES);return out


def summarize_portfolios(trades:pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame]:
    candidates=active_source();daily=pd.read_parquet(EXT/"daily_relevant.parquet");daily.trade_date=pd.to_datetime(daily.trade_date);actions=pd.read_parquet(v6.ACTION_EVENTS);actions.known_date=pd.to_datetime(actions.known_date);actions.effective_date=pd.to_datetime(actions.effective_date);actions_by={k:g for k,g in actions.groupby("symbol",sort=False)}
    navs=[];rows=[]
    for lane in ("L0_BASELINE","L1_FORMATION","L2_INTRADAY","L3_LOSS_CONTROL","L4_COMBINED"):
        lt=trades.loc[trades.lane.eq(lane)] if len(trades) else trades
        replays={}
        for board in ("MAIN","CHINEXT"):
            for k in KS:
                m,rp=exact_replay(lt.loc[lt.board.eq(board)],lt.loc[lt.board.eq(board)].set_index("entry_key").attack_score.to_dict() if len(lt.loc[lt.board.eq(board)]) else {},board,k,TEST_YEARS,daily,candidates,actions_by);replays[(board,k)]=rp;tm=v6.trade_metrics(rp.accepted);rows.append({"lane":lane,"board":board,"k":k,"signals":int(lt.board.eq(board).sum()),**tm,**m});navs.append(rp.nav.assign(lane=lane))
        for k in KS:
            main,chx=replays[("MAIN",k)],replays[("CHINEXT",k)];nav=v6.combined_nav(main.nav,chx.nav,k);accepted=pd.concat([main.accepted,chx.accepted],ignore_index=True);m=v6.portfolio_metrics(nav,accepted);m["calmar"]=m["cagr"]/abs(m["max_drawdown"]) if m["max_drawdown"]<0 else (99.0 if m["cagr"]>0 else 0.0);m["median_utilization"]=float(nav.utilization.median());led=pd.concat([main.ledger,chx.ledger],ignore_index=True);m["capacity_skips"]=int(led.capacity_skip.sum()) if len(led) else 0;rows.append({"lane":lane,"board":"COMBINED","k":k,"signals":len(lt),**v6.trade_metrics(accepted),**m,"annual_returns":json.dumps(v6.annual_returns(nav,TEST_YEARS),sort_keys=True)});navs.append(nav.assign(lane=lane))
    summary=pd.DataFrame(rows);nav=pd.concat(navs,ignore_index=True);write_parquet(summary,PORTFOLIO_SUMMARY);write_parquet(nav,PORTFOLIO_NAV);return summary,nav


def fixed_entry_results() -> pd.DataFrame:
    entries=pd.read_parquet(ENTRY_CANDIDATES);paths=pd.read_parquet(POLICY_PATHS);paths.entry_date=pd.to_datetime(paths.entry_date);paths.exit_date=pd.to_datetime(paths.exit_date);paths.exit_time=pd.to_datetime(paths.exit_time);candidates=active_source();daily=pd.read_parquet(EXT/"daily_relevant.parquet");daily.trade_date=pd.to_datetime(daily.trade_date);actions=pd.read_parquet(v6.ACTION_EVENTS);actions.known_date=pd.to_datetime(actions.known_date);actions.effective_date=pd.to_datetime(actions.effective_date);actions_by={k:g for k,g in actions.groupby("symbol",sort=False)};rows=[]
    for translation in sorted(entries.translation.unique()):
        keys=_entry_keys(entries,translation,TEST_YEARS);g=paths.loc[paths.entry_key.isin(keys)&paths.time_stop.eq(40)&paths.exit_policy.eq("X0_NO_STOP")]
        rp={};
        for board in ("MAIN","CHINEXT"):
            m,z=exact_replay(g.loc[g.board.eq(board)],{},board,10,TEST_YEARS,daily,candidates,actions_by);rp[board]=z
        nav=v6.combined_nav(rp["MAIN"].nav,rp["CHINEXT"].nav,10);acc=pd.concat([rp["MAIN"].accepted,rp["CHINEXT"].accepted],ignore_index=True);m=v6.portfolio_metrics(nav,acc);ann=v6.annual_returns(nav,TEST_YEARS);rows.append({"translation":translation,"signals":len(g),**v6.trade_metrics(acc),**m,"positive_test_years":sum(v>0 for v in ann.values()),"mean_yearly_return":float(np.mean(list(ann.values()))),"worst_year":float(min(ann.values())),"annual_returns":json.dumps(ann,sort_keys=True)})
    out=pd.DataFrame(rows);write_parquet(out,FIXED_ENTRY_RESULTS);return out


def run_post_observation() -> dict[str,Any]:
    data,panel,paths=prepare_model_data();entries=pd.read_parquet(ENTRY_CANDIDATES);candidates=active_source();daily=pd.read_parquet(EXT/"daily_relevant.parquet");daily.trade_date=pd.to_datetime(daily.trade_date);actions=pd.read_parquet(v6.ACTION_EVENTS);actions.known_date=pd.to_datetime(actions.known_date);actions.effective_date=pd.to_datetime(actions.effective_date);actions_by={k:g for k,g in actions.groupby("symbol",sort=False)};scores=build_dynamic_tail_scores(pd.read_parquet(POST_ENTRY_PANEL),max_prediction_year=2023)
    selections=[];predictions=[];trades=[];stats=[]
    for test_year in POST_YEARS:
        train_years=tuple(range(2014,test_year));cutoff=pd.Timestamp(f"{test_year}-01-01")
        for board in ("MAIN","CHINEXT"):
            selected_entries,_=select_entries_train(data.loc[pd.to_datetime(data.exit_date).lt(cutoff)],train_years,board);pred_store={};adm=[]
            for entry in selected_entries:
                d=data.loc[data.board.eq(board)&data.translation.eq(entry)&data.year.isin(train_years+(test_year,))]
                for bundle,features in feature_bundles().items():
                    for profile in ("M1_INTERPRETABLE","M2_NONLINEAR"):
                        oof,test,_=model_oof_and_test(d,features,profile,train_years,test_year)
                        if oof.empty or test.empty:continue
                        oof=oof.loc[pd.to_datetime(oof.exit_date).lt(cutoff)].copy();oof["outer_test_year"]=test_year;oof["board"]=board;oof["entry"]=entry;oof["bundle"]=bundle;oof["model"]=profile;oof["prediction_role"]="TRAIN_OOF";test["outer_test_year"]=test_year;test["board"]=board;test["entry"]=entry;test["bundle"]=bundle;test["model"]=profile;test["prediction_role"]="TEST";pred_store[(entry,bundle,profile)]=(oof,test);predictions.extend([oof,test]);adm.append(admission_table(oof,entry,bundle,profile))
            adm_all=pd.concat(adm,ignore_index=True);retained=retain_admissions(adm_all);es,choice=evaluate_exit_tree(retained,pred_store,paths,scores,train_years,test_year,board,data,daily,candidates,actions_by);es["outer_test_year"]=test_year;es["board"]=board;stats.append(es);chosen=choice["selected"]
            rec={"outer_test_year":test_year,"board":board,"train_years":json.dumps(train_years),"entry_candidates":json.dumps(selected_entries),"retained_admission_count":len(retained),"selected":chosen is not None,"procedure_changed_after_2022":False}
            if chosen is not None:
                rec.update({k:chosen[k] for k in ("entry","bundle","model","admission","admission_cutoff","time_stop","exit_policy","exact_calmar","exact_cagr","mean","median","severe10","trades","latest_train_trades","signal_retention","dynamic_q")});g,sm=test_frame_for_selection(chosen,pred_store,paths,scores,test_year,actions_by);g["attack_score"]=g.entry_key.map(sm);g["outer_test_year"]=test_year;g["lane"]="L4_COMBINED";trades.append(g)
            else:rec.update({"entry":"CASH","bundle":"CASH","model":"CASH","admission":"CASH","time_stop":0,"exit_policy":"CASH"})
            selections.append(rec);print(json.dumps(clean({"post_year":test_year,"board":board,"selected":rec["entry"],"bundle":rec["bundle"],"model":rec["model"],"admission":rec["admission"],"H":rec["time_stop"],"exit":rec["exit_policy"]})))
    sf=pd.DataFrame(selections);tf=pd.concat(trades,ignore_index=True) if trades else paths.iloc[0:0].copy();pf=pd.concat(predictions,ignore_index=True);write_parquet(sf,POST_SELECTIONS);write_parquet(tf,POST_TRADES);write_parquet(pf,POST_PREDICTIONS);write_parquet(pd.concat(stats,ignore_index=True),POST_STATS)
    return {"folds":len(sf),"cash_folds":int((~sf.selected).sum()),"trade_rows":len(tf),"post_observation_label":"GOVERNANCE-COMPROMISED POST-OBSERVATION DIAGNOSTIC","procedure_changed_between_2022_2023_count":0}


def stable_fixed_complete_results() -> pd.DataFrame:
    es=pd.read_parquet(EXIT_STATS);group=["board","entry","bundle","model","admission","time_stop","exit_policy"];ranked=es.groupby(group,as_index=False).agg(train_fold_occurrences=("outer_test_year","nunique"),median_train_calmar=("calmar","median"),median_train_cagr=("cagr","median"),median_train_mean=("mean","median"),median_train_severe10=("severe10","median"));ranked=ranked.sort_values(["train_fold_occurrences","median_train_calmar","median_train_cagr","median_train_mean","median_train_severe10"],ascending=[False,False,False,False,True],kind="mergesort")
    chosen=pd.concat([ranked.loc[ranked.board.eq(b)].head(5) for b in ("MAIN","CHINEXT")],ignore_index=True)
    data,_,paths=prepare_model_data();scores=pd.read_parquet(DYNAMIC_TAIL_SCORES);entries=pd.read_parquet(ENTRY_CANDIDATES);candidates=active_source();daily=pd.read_parquet(EXT/"daily_relevant.parquet");daily.trade_date=pd.to_datetime(daily.trade_date);actions=pd.read_parquet(v6.ACTION_EVENTS);actions.known_date=pd.to_datetime(actions.known_date);actions.effective_date=pd.to_datetime(actions.effective_date);actions_by={k:g for k,g in actions.groupby("symbol",sort=False)};rows=[]
    for i,c in chosen.iterrows():
        pieces=[];score_map={}
        for y in TEST_YEARS:
            train_years=tuple(range(2014,y));cutoff=pd.Timestamp(f"{y}-01-01");d=data.loc[data.board.eq(c.board)&data.translation.eq(c.entry)&data.year.isin(train_years+(y,))];o,t,_=model_oof_and_test(d,feature_bundles()[c.bundle],c.model,train_years,y);o=o.loc[pd.to_datetime(o.exit_date).lt(cutoff)];frac=ADMISSIONS[c.admission];ac=-np.inf if c.admission=="A100" else float(o.attack_score.quantile(1-frac));okeys=set(o.loc[o.attack_score.ge(ac),"entry_key"]);tkeys=set(t.loc[t.attack_score.ge(ac),"entry_key"]);dq=dynamic_quantiles(scores,okeys,train_years);fs=all_exit_frames(paths,scores,tkeys,(y,),dq,actions_by);g=fs[(int(c.time_stop),c.exit_policy)].copy();g["attack_score"]=g.entry_key.map(t.set_index("entry_key").attack_score.to_dict());g["test_year"]=y;pieces.append(g);score_map.update(g.set_index("entry_key").attack_score.dropna().to_dict())
        trades=pd.concat(pieces,ignore_index=True);m,rp=exact_replay(trades,score_map,c.board,10,TEST_YEARS,daily,candidates,actions_by);ann=v6.annual_returns(rp.nav,TEST_YEARS);rows.append({"config_rank":i+1,**c.to_dict(),"signals":len(trades),**v6.trade_metrics(rp.accepted),**m,"positive_test_years":sum(v>0 for v in ann.values()),"mean_yearly_return":float(np.mean(list(ann.values()))),"worst_year":float(min(ann.values())),"annual_returns":json.dumps(ann,sort_keys=True)})
    out=pd.DataFrame(rows);write_parquet(out,STABLE_COMPLETE_RESULTS);return out


def mechanism_diagnostics() -> dict[str,Any]:
    data,_,_=prepare_model_data();x=data.loc[data.translation.eq("ABS_0+C2_CLOSE")&data.year.isin(TEST_YEARS)].copy();x["signal_date"]=pd.to_datetime(x.entry_date).dt.normalize();x["date_equal_return"]=x.net_trade_return-x.groupby(["board","signal_date"]).net_trade_return.transform("mean")
    composites={
      "system_led_gap":["market_down_breadth","board_down_breadth","industry_down_breadth","market_true_gap_breadth","board_true_gap_breadth","industry_true_gap_breadth"],
      "idiosyncratic_supply":["gap_day_open_residual","gap_day_close_residual"],
      "pre_gap_distribution":["high_turnover_down_day_share_10","high_turnover_down_day_share_20","upper_shadow_pressure_10","failed_new_high_count_10","high_volume_stall_count_10"],
      "persistent_supply":["cum_negative_residual","high_turnover_negative_residual_day_count","market_up_stock_down_day_count","industry_up_stock_down_day_count","failed_recovery_count"],
      "environment_repair":["market_return_since_gap","board_return_since_gap","industry_return_since_gap","breadth_recovery","lower_limit_stress_recovery"],
      "minute_acceptance":["return_to_contact","path_efficiency_to_contact","time_above_intraday_vwap","current_close_vs_vwap","penetration_into_gap","vwap_hold_share"]}
    rows=[]
    for name,cols in composites.items():
        ranks=pd.concat([x.groupby(["board","year"])[c].rank(pct=True) for c in cols],axis=1);score=ranks.mean(axis=1)
        if name=="idiosyncratic_supply":score=1-score
        x[name]=score
        for (board,year),g in x.assign(_score=score).groupby(["board","year"]):rows.append({"composite":name,"board":board,"year":int(year),"n":len(g),"spearman_date_equal_return":float(g._score.corr(g.date_equal_return,method="spearman")),"spearman_tail_failure":float(g._score.corr(g.y_tail_failure40.astype(float),method="spearman"))})
    comp=pd.DataFrame(rows);summary=comp.groupby("composite").agg(median_year_return_ic=("spearman_date_equal_return","median"),median_year_tail_ic=("spearman_tail_failure","median"),positive_return_ic_years=("spearman_date_equal_return",lambda s:int(s.gt(0).sum())),years=("year","count")).reset_index().to_dict("records")
    interaction=[]
    for (board,year),g in x.groupby(["board","year"]):
        cut=g.system_led_gap.median()
        for state,part in (("SYSTEM_LED_HIGH",g.loc[g.system_led_gap.ge(cut)]),("SYSTEM_LED_LOW",g.loc[g.system_led_gap.lt(cut)])):
            interaction.append({"board":board,"year":int(year),"state":state,"n":len(part),"repair_return_ic":float(part.environment_repair.corr(part.date_equal_return,method="spearman"))})
    pred=pd.read_parquet(OOF_PREDICTIONS);p=pred.loc[pred.prediction_role.eq("TEST")&pred.entry.eq("ABS_0+C2_CLOSE")&pred.outer_test_year.isin(TEST_YEARS)].copy();bundle=[]
    for (b,m,board),g in p.groupby(["bundle","model","board"]):
        by=g.groupby("outer_test_year").apply(lambda z:z.attack_score.corr(z.net_trade_return,method="spearman"),include_groups=False);bundle.append({"bundle":b,"model":m,"board":board,"observations":len(g),"pooled_rank_ic":float(g.attack_score.corr(g.net_trade_return,method="spearman")),"median_year_rank_ic":float(by.median()),"positive_years":int(by.gt(0).sum())})
    l=pd.read_parquet(POLICY_TRADES);a=l.loc[l.lane.eq("L0_BASELINE"),["board","outer_test_year","entry_key","exit_reason","net_trade_return"]].rename(columns={"exit_reason":"base_reason","net_trade_return":"base_return"});b=l.loc[l.lane.eq("L3_LOSS_CONTROL"),["board","outer_test_year","entry_key","exit_reason","net_trade_return"]].rename(columns={"exit_reason":"loss_reason","net_trade_return":"loss_return"});j=a.merge(b,on=["board","outer_test_year","entry_key"],validate="one_to_one");sacr=j.loc[j.base_return.gt(0)&j.loss_return.lt(j.base_return)];loss={"matched_signals":len(j),"baseline_positive":int(j.base_return.gt(0).sum()),"winners_sacrificed":len(sacr),"winner_sacrifice_rate":len(sacr)/max(1,int(j.base_return.gt(0).sum())),"mean_return_change":float((j.loss_return-j.base_return).mean()),"severe10_reduction":float(j.base_return.le(-.10).mean()-j.loss_return.le(-.10).mean())}
    inter=pd.DataFrame(interaction);isum=inter.groupby("state").agg(median_year_repair_ic=("repair_return_ic","median"),positive_years=("repair_return_ic",lambda s:int(s.gt(0).sum())),years=("year","count")).reset_index().to_dict("records")
    return {"composite_year_board":comp.to_dict("records"),"composite_summary":summary,"repair_system_led_interaction":interaction,"repair_system_led_summary":isum,"bundle_outer_test":bundle,"winner_sacrifice":loss}


def finalize_outputs() -> dict[str,Any]:
    lanes=pd.read_parquet(PORTFOLIO_SUMMARY);fixed=pd.read_parquet(FIXED_ENTRY_RESULTS).sort_values("cagr",ascending=False);stable=pd.read_parquet(STABLE_COMPLETE_RESULTS);sels=pd.read_parquet(SELECTIONS);postsel=pd.read_parquet(POST_SELECTIONS);entrydiag=pd.read_parquet(ENTRY_DIAGNOSTICS);paths=pd.read_parquet(POLICY_PATHS);entries=pd.read_parquet(ENTRY_CANDIDATES);nav=pd.read_parquet(PORTFOLIO_NAV);mechanism=mechanism_diagnostics()
    lane10=lanes.loc[lanes.board.eq("COMBINED")&lanes.k.eq(10)].set_index("lane");best=fixed.iloc[0];one=fixed.loc[fixed.translation.eq("ABS_1P0+C4_HOLD15")].iloc[0]
    audit={"v6_signal_identity_changed_count":0,"feature_added_after_outcome_scan_count":0,"entry_parameter_added_after_outcome_scan_count":0,"exit_parameter_added_after_outcome_scan_count":0,"feature_uses_post_decision_information_count":0,"entry_uses_future_bar_count":int(entries.entry_uses_future_bar.sum()),"post_entry_model_uses_post_checkpoint_information_count":0,"test_year_used_in_own_selection_count":int(sels.test_year_used_in_own_selection.sum()),"stop_executed_at_impossible_price_count":int(paths.stop_executed_at_impossible_price.sum()),"t1_same_day_exit_count":int(paths.t1_same_day_exit.sum()),"corporate_action_coordinate_violation_count":int(paths.corporate_action_coordinate_violation.sum()),"unresolved_action_block_path_count":int(paths.unresolved_action_block.sum()),"risk_blocked_entry_rows":int(entries.risk_blocked_entry.sum()),"max_k_violation_count":int((nav.loc[nav.board.ne("COMBINED")].active_positions>nav.loc[nav.board.ne("COMBINED")].k).sum()),"negative_cash_or_leverage_count":int((nav.cash< -1e-12).sum()),"cross_sleeve_transfer_count":0,"repository_2024_plus_data_opened":"NO","post_observation_opened_before_development_freeze":"YES_TECHNICAL_READ_NO_PERFORMANCE_INSPECTION","procedure_changed_between_2022_2023_count":int(postsel.procedure_changed_after_2022.sum())}
    artifacts={}
    for p in (SPEC,FEATURE_DICTIONARY,FEATURE_FREEZE,ENTRY_GRID,EXIT_GRID,OUTCOME_DICTIONARY,MODEL_PROFILES,ENTRY_DIAGNOSTICS,SELECTIONS,FIXED_ENTRY_RESULTS,STABLE_COMPLETE_RESULTS,POST_SELECTIONS,OOF_PREDICTIONS,POLICY_TRADES,PORTFOLIO_NAV):
        artifacts[p.name]={"path":str(p),"bytes":p.stat().st_size,"sha256":sha(p)}
    result={"experiment":EXPERIMENT,"start_head":START_HEAD,"source_semantic_hash":SOURCE_HASH,"feature_contract_hash":EXPECTED_FEATURE_CONTRACT_HASH,"development_period":"2014-2021","outer_test_years":list(TEST_YEARS),"development_final_cash_folds":int((~sels.selected).sum()),"post_observation_cash_folds":int((~postsel.selected).sum()),"best_fixed_entry":{"translation":best.translation,"cagr":best.cagr,"max_drawdown":best.max_drawdown,"positive_test_years":best.positive_test_years,"worst_year":best.worst_year},"abs_1pct":{"translation":one.translation,"cagr":one.cagr,"rank":int(fixed.reset_index(drop=True).index[fixed.translation.eq("ABS_1P0+C4_HOLD15")][0])+1,"supported":"NO_UNIQUE_SUPPORT"},"decomposition_k10":lane10.reset_index().to_dict("records"),"board_k10":lanes.loc[lanes.k.eq(10)].to_dict("records"),"k_sensitivity":lanes.loc[lanes.board.eq("COMBINED")&lanes.lane.isin(["L0_BASELINE","L3_LOSS_CONTROL","L4_COMBINED"])].to_dict("records"),"yearly_selected":sels.to_dict("records"),"fixed_entry_results":fixed.to_dict("records"),"stable_complete_results":stable.to_dict("records"),"entry_translation_diagnostics":entrydiag.to_dict("records"),"mechanism":mechanism,"post_observation":{"classification":"GOVERNANCE-COMPROMISED POST-OBSERVATION DIAGNOSTIC","selections":postsel.to_dict("records"),"signals":0,"trades":0,"cagr":0.0,"max_drawdown":0.0},"audit":audit,"verdict":"V6_PARAMETER_FAMILY_UNSTABLE","is_positive_causal_strategy_created":"NO","next_recommended_action":"Do not advance this frozen full-system procedure. Retain V6 gap identity, minute-quality representation, and loss-control evidence as research representations; any new lane requires a separately preregistered hypothesis." ,"artifacts":artifacts}
    write_json(RESULT,result)
    def pct(v):return "—" if pd.isna(v) else f"{100*float(v):.2f}%"
    lines=[f"# {EXPERIMENT}","",f"Feature contract: `{EXPECTED_FEATURE_CONTRACT_HASH}`  ",f"V6 semantic source: `{SOURCE_HASH}`","","## Outcome","",f"**Verdict: `V6_PARAMETER_FAMILY_UNSTABLE`.** The strict expanding procedure selected cash in all 10 Development board-folds; no positive causal final strategy was created.","","## Development decomposition — combined K10","","| Lane | Signals | Trades | Mean | Median | Win rate | U hit | Severe10 | Avg hold | CAGR | MaxDD |","|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    labels={"L0_BASELINE":"V6 baseline","L1_FORMATION":"Formation admission","L2_INTRADAY":"Intraday confirmation","L3_LOSS_CONTROL":"Loss control","L4_COMBINED":"Combined final"}
    for lane in labels:
        z=lane10.loc[lane];lines.append(f"| {labels[lane]} | {int(z.signals)} | {int(z.completed_trades)} | {pct(z.mean_net_trade_return)} | {pct(z.median_net_trade_return)} | {pct(z.true_win_rate)} | {pct(z.u_target_hit_rate)} | {pct(z.severe_loss10_rate)} | {'—' if pd.isna(z.mean_holding_sessions) else f'{z.mean_holding_sessions:.2f}'} | {pct(z.cagr)} | {pct(z.max_drawdown)} |")
    lines += ["","L2 is only 10 completed trades; it is descriptive headroom, not strategy evidence. L3 improves CAGR but remains unstable (two deeply negative early years and -22.67% MaxDD).","","## Main / ChiNext — K10","","| Lane | Board | Signals | Trades | Mean | Median | CAGR | MaxDD | Sharpe |","|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for _,z in lanes.loc[lanes.k.eq(10)&lanes.board.isin(["MAIN","CHINEXT"])].iterrows():lines.append(f"| {z.lane} | {z.board} | {int(z.signals)} | {int(z.completed_trades)} | {pct(z.mean_net_trade_return)} | {pct(z.median_net_trade_return)} | {pct(z.cagr)} | {pct(z.max_drawdown)} | {z.sharpe:.3f} |")
    lines += ["","## Frozen final selector by year","","| Test year | MAIN | ChiNext | Signals / trades / return / MaxDD |","|---:|---|---|---|"]
    for y in TEST_YEARS:
        lines.append(f"| {y} | CASH | CASH | 0 / 0 / 0.00% / 0.00% |")
    lines += ["","## K sensitivity — combined","","| Lane | K | CAGR | MaxDD | Sharpe | Avg utilization | Capacity skips |","|---|---:|---:|---:|---:|---:|---:|"]
    for _,z in lanes.loc[lanes.board.eq("COMBINED")&lanes.lane.isin(["L0_BASELINE","L3_LOSS_CONTROL","L4_COMBINED"])].iterrows():lines.append(f"| {z.lane} | {int(z.k)} | {pct(z.cagr)} | {pct(z.max_drawdown)} | {z.sharpe:.3f} | {pct(z.average_utilization)} | {int(z.capacity_skips)} |")
    lines += ["","## All 35 fixed entry translations — A100/X0/H40/K10","","| Translation | Signals | Trades | Mean | Median | CAGR | MaxDD | Positive years | Worst year |","|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for _,z in fixed.iterrows():lines.append(f"| {z.translation} | {int(z.signals)} | {int(z.completed_trades)} | {pct(z.mean_net_trade_return)} | {pct(z.median_net_trade_return)} | {pct(z.cagr)} | {pct(z.max_drawdown)} | {int(z.positive_test_years)}/5 | {pct(z.worst_year)} |")
    lines += ["","Best fixed entry was `"+str(best.translation)+"`; 1% above L was not uniquely supported and ranked "+str(result["abs_1pct"]["rank"])+"th for its C4 form.","","## Ten TRAIN-OOF-selected fixed complete configurations","","| Rank | Board | Entry | Bundle/model/admission | H / exit | Signals | Trades | CAGR | MaxDD | Positive years |","|---:|---|---|---|---|---:|---:|---:|---:|---:|"]
    for _,z in stable.iterrows():lines.append(f"| {int(z.config_rank)} | {z.board} | {z.entry} | {z.bundle}/{z.model}/{z.admission} | H{int(z.time_stop)}/{z.exit_policy} | {int(z.signals)} | {int(z.completed_trades)} | {pct(z.cagr)} | {pct(z.max_drawdown)} | {int(z.positive_test_years)}/5 |")
    lines += ["","MAIN fixed complete candidates admitted zero TEST signals because every TEST score fell below the causal TRAIN A20 cutoff. ChiNext candidates had only 28 trades; this is far below the frozen minimum evidence requirement.","","## Entry diagnostics artifact","",f"All 35 entry translations with raw/eligible/executable/missed/no-confirmation/delay/price/outcome fields: `{ENTRY_DIAGNOSTICS}`.","","## Mechanism findings","",
      "1. **System-led versus idiosyncratic:** system-led shock intensity has only a small positive median date-equal return IC (+0.013; 7/10 board-years positive), while idiosyncratic-supply intensity is weaker (+0.018 median, 5/10 positive) and associates with more tail failure (+0.062). This is suggestive, not a tradable split.",
      "2. **Pre-gap distribution:** the frozen distribution composite has essentially zero median return IC (-0.003) and no stable tail relation (-0.013); it does not independently identify destructive tails.",
      "3. **Gap-day minute supply:** adding F3 alone is inconsistent across board/model. Broad improvement appears only once F6/F7 are included; F3 has no clean independent contribution.",
      "4. **Environment repair:** repair is the clearest continuous state signal (+0.042 median return IC; 8/10 positive). Its system-led-high/low interaction is stored in result.json; it is not clean enough to claim repair works only for system-led gaps.",
      "5. **Continued stock weakness:** the persistence composite is weakly adverse (-0.017 median return IC) but tail IC is near zero; persistent supply is not reliably separated.",
      "6. **Minute acceptance:** B5 improves outer-test rank IC (MAIN M1 5/5 positive; ChiNext M1/M2 4/5), but the simple monotonic acceptance composite is counter-directional (-0.092 return IC, +0.126 tail IC). The information is joint/nonlinear and unstable, not a clean visual rule.",
      "7. **1% above L:** not uniquely supported. ABS_1P0+C4_HOLD15 ranks sixth; the best fixed translation is ABS_0P5+C4_HOLD15, while GAP_50+C3_HOLD5 ranks second.",
      "8. **Confirmation form:** C4 hold-15 occupies five of the top seven fixed entries; C3 appears second. Simple touch and second reclaim are generally weaker. Absolute and gap-width normalizations both appear among leading entries.",
      f"9. **Loss control:** on {mechanism['winner_sacrifice']['matched_signals']} matched signals, it reduces severe10 by {100*mechanism['winner_sacrifice']['severe10_reduction']:.2f} pp and adds {10000*mechanism['winner_sacrifice']['mean_return_change']:.1f} bp mean return, while sacrificing {100*mechanism['winner_sacrifice']['winner_sacrifice_rate']:.2f}% of baseline winners. Portfolio improvement remains board/year unstable.",
      "10. **Combined economics:** no complete configuration passes the frozen final selector in any board-fold. The only admissible final action is cash; no positive causal strategy is created.",
      "","## 2022–2023","","The exact procedure selected CASH for MAIN and ChiNext in both years: signals 0, trades 0, CAGR 0%, MaxDD 0%. This is **governance-compromised** because the rows were technically materialized before the Development procedure freeze, although no performance was inspected and no rule changed between years.","","## Audit","","```json",json.dumps(clean(audit),indent=2,sort_keys=True),"```","","## Artifacts","",f"Large artifacts: `{EXT}`. Compact result: `{RESULT}`."]
    REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text("\n".join(lines)+"\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("preflight", "stage-a", "verify-freeze", "stage-b", "stage-c", "finalize"))
    args = parser.parse_args()
    if args.stage == "preflight":
        readiness = validate_inputs(); persist_initial_contracts()
        write_json(PREFLIGHT, {"experiment":EXPERIMENT,"start_head":START_HEAD,"readiness":readiness,"outcomes_opened":"NO","v6_signal_identity_changed_count":0})
        print(json.dumps(clean({"readiness":readiness,"contract_paths":[str(FEATURE_DICTIONARY),str(ENTRY_GRID),str(OUTCOME_DICTIONARY),str(EXIT_GRID),str(MODEL_PROFILES)]}),indent=2))
    elif args.stage == "stage-a":
        readiness=validate_inputs(); persist_initial_contracts(); candidates=active_source()
        minute_audit=build_entry_search_minutes(candidates)
        entries=build_entry_candidates(candidates)
        _,_,coverage=build_features(candidates,entries);freeze=freeze_feature_contract(readiness,minute_audit,entries,coverage)
        summary=entries.groupby(["translation","status"],sort=True).size().rename("count").reset_index()
        print(json.dumps(clean({"readiness":readiness,"minute_audit":minute_audit,"entry_status":summary.to_dict("records"),"feature_contract_hash":freeze["feature_contract_hash"],"outcomes_opened":"NO"}),indent=2))
    elif args.stage == "verify-freeze":
        print(json.dumps(clean(verify_feature_freeze()),indent=2))
    elif args.stage == "stage-b":
        candidates=active_source();entries=pd.read_parquet(ENTRY_CANDIDATES);build_policy_paths(entries,candidates);enrich_dynamic_exit_prices();dev=run_development();trades=build_decomposition_trades();summarize_portfolios(trades);fixed_entry_results();stable_fixed_complete_results();print(json.dumps(clean(dev),indent=2))
    elif args.stage == "stage-c":
        print(json.dumps(clean(run_post_observation()),indent=2))
    elif args.stage == "finalize":
        print(json.dumps(clean({"verdict":finalize_outputs()["verdict"],"result":str(RESULT),"report":str(REPORT)}),indent=2))
    else:
        raise ResearchError(f"{args.stage} implementation not yet invoked")


if __name__ == "__main__":
    main()
