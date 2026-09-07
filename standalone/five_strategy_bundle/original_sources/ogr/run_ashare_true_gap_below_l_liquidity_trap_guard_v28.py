#!/usr/bin/env python3
# ruff: noqa: E501
"""Develop, freeze, and diagnose a causal liquidity-trap guard for V27."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_fresh_capitulation_snapback_v27 as v27,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_meaningful_prior_decline_v16 as replay,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-LIQUIDITY-TRAP-GUARD-V28"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_liquidity_trap_guard_v28"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_AUTHORIZATION = OS / f"artifacts/{EXPERIMENT}_diagnostic_authorization.json"
DIAGNOSTIC_STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_stage_a_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

CY033_ROOT = Path(
    "/Users/linmei/Documents/CY/data/registered_inputs/"
    "CY-033-PIT-B-DAILY-2018-20260904-V1"
)
CY033_REGISTRY = ROOT / "configs/data_asset_registry.json"

V27_DEVELOPMENT_ENTRIES = (
    v27.EXT_ROOT / "development/fresh_snapback_selected_entries.parquet"
)
V27_DIAGNOSTIC_ENTRIES = (
    v27.EXT_ROOT / "post_observation_diagnostic/fresh_snapback_selected_entries.parquet"
)
V27_LATER_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_fresh_capitulation_snapback_"
    "v27_diagnostic_2024_2025_v1/diagnostic_2024_2025"
)
V27_LATER_ENTRIES = V27_LATER_ROOT / "entries.parquet"
V27_LATER_OUTCOMES = V27_LATER_ROOT / "outcomes.parquet"
V27_LATER_DAILY = V27_LATER_ROOT / "outcome_daily.parquet"

DEVELOPMENT_YEARS = (2018, 2019, 2020, 2021)
DIAGNOSTIC_YEARS = (2022, 2023, 2024)
PRIOR_WINDOW = 20
MAX_PRIOR_ONE_PRICE_LIMIT_DOWNS = 1
PORTFOLIO_K = 80
MIN_ACCEPTED_TRADES_PER_YEAR = 50.0
MIN_MEAN_NET = 0.04
MAX_AVERAGE_HOLDING_SESSIONS = 15.0


class V28Error(RuntimeError):
    """Fail closed on identity, PIT timing, coverage, or freeze drift."""


def sha256(path: Path) -> str:
    return replay.sha256(path)


def write_json(path: Path, value: Any) -> None:
    replay.write_json(path, value)


def cy033_file(year: int) -> Path:
    return CY033_ROOT / f"daily/partition_year={year}/data_0.parquet"


def development_selected_path() -> Path:
    return EXT_ROOT / "development/liquidity_guard_selected_entries.parquet"


def development_lane_root() -> Path:
    return EXT_ROOT / "development/liquidity_guard"


def diagnostic_selected_path() -> Path:
    return EXT_ROOT / "diagnostic_2022_2024/liquidity_guard_selected_entries.parquet"


def diagnostic_lane_root() -> Path:
    return EXT_ROOT / "diagnostic_2022_2024/liquidity_guard"


def is_one_price_limit_down(frame: pd.DataFrame) -> pd.Series:
    """True only when every OHLC print is the day's disclosed down-limit price."""
    required = frame[["open", "high", "low", "close", "down_limit_price"]]
    finite = np.isfinite(required.to_numpy(dtype=float)).all(axis=1)
    values = required.to_numpy(dtype=float)
    limit = values[:, 4]
    equal = np.isclose(values[:, :4], limit[:, None], rtol=0.0, atol=0.006).all(axis=1)
    return pd.Series(finite & equal & (limit > 0), index=frame.index)


def attach_prior_limit_down_feature(
    entries: pd.DataFrame, daily: pd.DataFrame
) -> pd.DataFrame:
    """Attach the count over 20 completed sessions strictly before the signal."""
    needed = {"gap_id", "symbol", "signal_date"}
    daily_needed = {"symbol", "trade_date", "open", "high", "low", "close", "down_limit_price"}
    if not needed.issubset(entries.columns) or not daily_needed.issubset(daily.columns):
        raise V28Error("missing columns for the prior-limit-down feature")
    source = daily[list(daily_needed)].copy()
    source["trade_date"] = pd.to_datetime(source.trade_date).dt.normalize()
    if source.duplicated(["symbol", "trade_date"]).any():
        raise V28Error("duplicate symbol-date in daily feature source")
    source = source.sort_values(["symbol", "trade_date"], kind="mergesort")
    source["_one_price_limit_down"] = is_one_price_limit_down(source).astype(float)
    source["prior20_one_price_limit_down_count"] = source.groupby(
        "symbol", sort=False
    )["_one_price_limit_down"].transform(
        lambda values: values.shift(1).rolling(PRIOR_WINDOW, min_periods=PRIOR_WINDOW).sum()
    )
    feature = source[["symbol", "trade_date", "prior20_one_price_limit_down_count"]]
    result = entries.copy()
    result["signal_date"] = pd.to_datetime(result.signal_date).dt.normalize()
    result = result.merge(
        feature,
        left_on=["symbol", "signal_date"],
        right_on=["symbol", "trade_date"],
        how="left",
        validate="many_to_one",
    ).drop(columns="trade_date")
    result["liquidity_trap_guard"] = (
        result.prior20_one_price_limit_down_count.notna()
        & result.prior20_one_price_limit_down_count.le(MAX_PRIOR_ONE_PRICE_LIMIT_DOWNS)
    )
    return result


def load_signal_state(entries: pd.DataFrame, years: tuple[int, ...]) -> pd.DataFrame:
    """Attach signal-close CY033 state, enforcing availability at decision_at."""
    paths = [cy033_file(year) for year in years]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise V28Error(f"missing registered CY033 partitions: {missing}")
    state = pd.concat(
        [
            pd.read_parquet(
                path,
                columns=[
                    "symbol",
                    "trade_date",
                    "is_st",
                    "hard_valid",
                    "available_at",
                    "snapshot_id",
                ],
            )
            for path in paths
        ],
        ignore_index=True,
    )
    state["trade_date"] = pd.to_datetime(state.trade_date).dt.normalize()
    state["available_at"] = pd.to_datetime(state.available_at)
    if state.duplicated(["symbol", "trade_date"]).any():
        raise V28Error("duplicate symbol-date in CY033")
    wanted = entries.copy()
    wanted["signal_date"] = pd.to_datetime(wanted.signal_date).dt.normalize()
    wanted["signal_time"] = pd.to_datetime(wanted.signal_time)
    state = state.loc[state.symbol.astype(str).isin(set(wanted.symbol.astype(str)))].copy()
    state = state.rename(
        columns={
            "trade_date": "signal_date",
            "is_st": "signal_is_st",
            "hard_valid": "signal_state_hard_valid",
            "available_at": "signal_state_available_at",
            "snapshot_id": "signal_state_snapshot_id",
        }
    )
    result = wanted.merge(
        state,
        on=["symbol", "signal_date"],
        how="left",
        validate="many_to_one",
    )
    available = result.signal_state_available_at.notna() & result.signal_state_available_at.le(
        result.signal_time
    )
    result["signal_state_available_by_decision"] = available
    result["signal_state_hard_valid"] = (
        result.signal_state_hard_valid.eq(True) & available  # noqa: E712
    )
    result.loc[~available, "signal_is_st"] = pd.NA
    return result


def load_cy033_feature_daily(years: tuple[int, ...]) -> pd.DataFrame:
    """Read registered raw daily prices, including the prior-year window when present."""
    requested = set(years)
    prior = min(years) - 1
    if cy033_file(prior).is_file():
        requested.add(prior)
    paths = [cy033_file(year) for year in sorted(requested)]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise V28Error(f"missing registered CY033 feature partitions: {missing}")
    frame = pd.concat(
        [
            pd.read_parquet(
                path,
                columns=[
                    "symbol",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "down_limit_price",
                ],
            )
            for path in paths
        ],
        ignore_index=True,
    )
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def v28_admission_mask(frame: pd.DataFrame) -> pd.Series:
    required = frame[
        [
            "prior20_one_price_limit_down_count",
            "signal_state_hard_valid",
            "signal_is_st",
        ]
    ]
    return (
        required.notna().all(axis=1)
        & frame.signal_state_hard_valid.eq(True)  # noqa: E712
        & frame.signal_is_st.eq(False)  # noqa: E712
        & frame.prior20_one_price_limit_down_count.le(MAX_PRIOR_ONE_PRICE_LIMIT_DOWNS)
    )


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "scientific_status": "RETROSPECTIVE_GUARD_DEVELOPMENT_WITH_LOCKED_LATER_DIAGNOSTIC",
        "parent": v27.EXPERIMENT,
        "economic_hypothesis": (
            "One isolated limit-down can be capitulation, but repeated one-price limit-downs "
            "in the preceding month indicate rationed liquidity: apparent low turnover is "
            "not supply exhaustion because holders could not sell. Demand-recapture entries "
            "are admitted only after this liquidity-trap pattern is absent and the issuer is "
            "known non-ST at the completed signal close."
        ),
        "development": ["2018-01-01", "2021-12-31"],
        "development_start_reason": "registered CY033 state begins in 2018",
        "locked_diagnostic": ["2022-01-01", "2024-12-31"],
        "additional_conditions": {
            "liquidity_trap_guard": "one-price limit-down count in 20 completed pre-signal sessions <= 1",
            "one_price_definition": "raw open=high=low=close=registered down_limit_price within 0.006",
            "issuer_state": "signal-close CY033 hard_valid and non-ST",
            "missing_policy": "fail closed",
            "feature_timestamp": "completed signal close; never entry day or later",
        },
        "unchanged_v27": {
            "admission": "M20/F14/R5",
            "trigger": "first completed daily close above previous completed daily high",
            "entry": "first legal buyable 1-minute open after signal",
            "target": "A67 below L",
            "failure_stop": "NONE",
            "time_stop": "H20",
            "round_trip_cost": 0.004,
            "portfolio": "Main/ChiNext 50/50; K80 per sleeve",
            "execution_and_lineage": "unchanged",
        },
        "development_success": {
            "accepted_trades_per_year_strictly_greater_than": MIN_ACCEPTED_TRADES_PER_YEAR,
            "mean_net_min": MIN_MEAN_NET,
            "average_holding_sessions_strictly_less_than": MAX_AVERAGE_HOLDING_SESSIONS,
            "each_development_signal_year_mean_net_positive": True,
        },
        "governance": {
            "development_outcomes_only_before_selector_pass": True,
            "diagnostic_identity_built_only_after_selector_pass": True,
            "2022_2024_outcomes_opened_only_after_diagnostic_identity_freeze": True,
            "announcement_risk_gate": "NOT_IMPLEMENTED_UNTIL_A_REGISTERED_PIT_EVENT_ASSET_EXISTS",
            "parent_v27_was_selected_after_2017_2023_observation": True,
            "therefore_diagnostic_is_not_pristine_external_validation": True,
        },
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "fixed_rule": "V27 AND signal_non_ST AND prior20_one_price_limit_down_count<=1",
            "parameter_search_disclosure": (
                "The natural alternatives 10/20 sessions and zero/one repeated events were "
                "screened on 2017-2021; the fixed 20-session, at-most-one rule was selected "
                "for economic meaning, frequency, tail reduction, and annual stability."
            ),
            "diagnostic_unlock": "automatic only after every development-success check passes",
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def development_source_hashes() -> dict[str, str]:
    paths: dict[str, Path] = {
        "v27_runner": Path(v27.__file__),
        "v27_contract": v27.CONTRACT,
        "v27_development_entries": V27_DEVELOPMENT_ENTRIES,
        "cy033_asset_manifest": CY033_ROOT / "asset_manifest.json",
        "data_asset_registry": CY033_REGISTRY,
    }
    paths.update({f"cy033_{year}": cy033_file(year) for year in DEVELOPMENT_YEARS})
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise V28Error(f"missing development sources: {missing}")
    return {name: sha256(path) for name, path in paths.items()}


def build_development_stage_a() -> dict[str, Any]:
    entries = pd.read_parquet(V27_DEVELOPMENT_ENTRIES)
    for column in ("signal_date", "signal_time", "entry_date", "entry_time"):
        entries[column] = pd.to_datetime(entries[column])
    entries = entries.loc[entries.signal_date.dt.year.isin(DEVELOPMENT_YEARS)].copy()
    if entries.empty or entries.gap_id.duplicated().any():
        raise V28Error("development V27 identity failure")
    daily = load_cy033_feature_daily(DEVELOPMENT_YEARS)
    featured = attach_prior_limit_down_feature(entries, daily)
    featured = load_signal_state(featured, DEVELOPMENT_YEARS)
    featured["v28_liquidity_trap_gate"] = featured.liquidity_trap_guard
    featured["v28_signal_non_st_gate"] = featured.signal_is_st.eq(False).fillna(False)
    featured["v28_feature_latest_timestamp"] = featured.signal_state_available_at
    featured["v28_feature_uses_post_signal_information"] = False
    selected = featured.loc[v28_admission_mask(featured)].copy()
    selected = selected.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    if selected.empty or selected.gap_id.duplicated().any():
        raise V28Error("development V28 identity failure")
    replay.repair.write_parquet(selected, development_selected_path())
    by_year = selected.groupby(selected.signal_date.dt.year).size()
    return {
        "parent_entries": len(entries),
        "selected_signals": len(selected),
        "executable_entries": int(selected.entry_status.eq("EXECUTABLE_ENTRY").sum()),
        "selected_by_signal_year": {str(year): int(by_year.get(year, 0)) for year in DEVELOPMENT_YEARS},
        "missing_prior20_count": int(featured.prior20_one_price_limit_down_count.isna().sum()),
        "rejected_repeated_one_price_limit_down": int(
            featured.prior20_one_price_limit_down_count.gt(MAX_PRIOR_ONE_PRICE_LIMIT_DOWNS).sum()
        ),
        "rejected_st": int(featured.signal_is_st.eq(True).sum()),
        "rejected_invalid_or_unavailable_state": int((~featured.signal_state_hard_valid.eq(True)).sum()),
        "post_signal_feature_count": int(featured.v28_feature_uses_post_signal_information.sum()),
        "selected_entries_sha256": sha256(development_selected_path()),
    }


def run_stage_a() -> dict[str, Any]:
    contract_hashes = persist_contracts()
    period = build_development_stage_a()
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DEVELOPMENT_IDENTITY_FREEZE_BEFORE_RETURN_OPEN",
        **contract_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": development_source_hashes(),
        "development": period,
        "development_outcomes_opened": "NO_IN_THIS_STAGE",
        "2022_2024_ENTRIES_OR_OUTCOMES_OPENED": "NO_IN_THIS_STAGE",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V28Error("development Stage-A freeze missing")
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    current = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
    }
    drift = {key: [freeze.get(key), value] for key, value in current.items() if freeze.get(key) != value}
    sources = development_source_hashes()
    if sources != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), sources]
    selected_hash = sha256(development_selected_path())
    if selected_hash != freeze["development"]["selected_entries_sha256"]:
        drift["selected_entries_sha256"] = [
            freeze["development"]["selected_entries_sha256"],
            selected_hash,
        ]
    if drift:
        raise V28Error(f"development Stage-A drift: {drift}")
    return {"verified": True, "checks": current}


@contextmanager
def development_runtime() -> Iterator[None]:
    old_root = replay.EXT_ROOT
    old_selected = replay.selected_entries_path
    old_lane = replay.lane_root
    try:
        replay.EXT_ROOT = EXT_ROOT
        replay.selected_entries_path = lambda label: development_selected_path()
        replay.lane_root = lambda label: development_lane_root()
        yield
    finally:
        replay.EXT_ROOT = old_root
        replay.selected_entries_path = old_selected
        replay.lane_root = old_lane


def _accepted_summary(accepted: pd.DataFrame, years: tuple[int, ...]) -> dict[str, Any]:
    accepted = accepted.copy()
    accepted["signal_date"] = pd.to_datetime(accepted.signal_date)
    accepted["entry_date"] = pd.to_datetime(accepted.entry_date)
    yearly = accepted.groupby(accepted.signal_date.dt.year).net_return.agg(
        trades="size",
        mean_net="mean",
        median_net="median",
        win=lambda values: float(values.gt(0).mean()),
        severe10=lambda values: float(values.le(-0.10).mean()),
        average_holding_sessions=lambda values: float(
            accepted.loc[values.index, "holding_sessions"].mean()
        ),
    )
    yearly_payload = {
        str(year): (
            {
                "trades": 0,
                "mean_net": None,
                "median_net": None,
                "win": None,
                "severe10": None,
                "average_holding_sessions": None,
            }
            if year not in yearly.index
            else {
                "trades": int(yearly.loc[year, "trades"]),
                "mean_net": float(yearly.loc[year, "mean_net"]),
                "median_net": float(yearly.loc[year, "median_net"]),
                "win": float(yearly.loc[year, "win"]),
                "severe10": float(yearly.loc[year, "severe10"]),
                "average_holding_sessions": float(yearly.loc[year, "average_holding_sessions"]),
            }
        )
        for year in years
    }
    return {
        "accepted_trades": len(accepted),
        "accepted_trades_per_year": len(accepted) / len(years),
        "mean_net": float(accepted.net_return.mean()),
        "median_net": float(accepted.net_return.median()),
        "win": float(accepted.net_return.gt(0).mean()),
        "severe10": float(accepted.net_return.le(-0.10).mean()),
        "average_holding_sessions": float(accepted.holding_sessions.mean()),
        "yearly_by_signal_year": yearly_payload,
    }


def development_checks(summary: dict[str, Any]) -> dict[str, bool]:
    return {
        "accepted_trades_per_year_gt_50": summary["accepted_trades_per_year"] > MIN_ACCEPTED_TRADES_PER_YEAR,
        "mean_net_ge_4pct": summary["mean_net"] >= MIN_MEAN_NET,
        "average_holding_sessions_lt_15": summary["average_holding_sessions"] < MAX_AVERAGE_HOLDING_SESSIONS,
        "each_signal_year_has_trades": all(
            summary["yearly_by_signal_year"][str(year)]["trades"] > 0 for year in DEVELOPMENT_YEARS
        ),
        "each_signal_year_mean_positive": all(
            (summary["yearly_by_signal_year"][str(year)]["mean_net"] or 0.0) > 0
            for year in DEVELOPMENT_YEARS
        ),
    }


def run_development() -> dict[str, Any]:
    verification = verify_stage_a()
    with development_runtime():
        lane = replay.run_lane("DEVELOPMENT", DEVELOPMENT_YEARS)
    accepted = pd.read_parquet(development_lane_root() / "portfolio_accepted.parquet")
    summary = _accepted_summary(accepted, DEVELOPMENT_YEARS)
    checks = development_checks(summary)
    passed = all(checks.values())
    result = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "lane": lane,
        "accepted_summary": summary,
        "goal_checks": checks,
        "selector_passed": passed,
        "verdict": "DEVELOPMENT_PASS_DIAGNOSTIC_AUTHORIZED" if passed else "DEVELOPMENT_FAILED_DIAGNOSTIC_LOCKED",
        "development_outcomes_opened": "YES",
        "diagnostic_outcomes_opened": "NO",
    }
    write_json(DEVELOPMENT_RESULT, result)
    if passed:
        write_json(
            DIAGNOSTIC_AUTHORIZATION,
            {
                "experiment": EXPERIMENT,
                "stage": "AUTOMATIC_DIAGNOSTIC_AUTHORIZATION_AFTER_DEVELOPMENT_PASS",
                "development_result_sha256": sha256(DEVELOPMENT_RESULT),
                "contract_sha256": sha256(CONTRACT),
                "spec_sha256": sha256(SPEC),
                "runner_sha256": sha256(Path(__file__)),
                "fixed_rule": "V27 AND signal_non_ST AND prior20_one_price_limit_down_count<=1",
                "diagnostic_years": list(DIAGNOSTIC_YEARS),
                "diagnostic_outcomes_opened": "NO_IN_THIS_STAGE",
            },
        )
    render_report(result, None)
    return result


def _assert_diagnostic_authorized() -> dict[str, Any]:
    if not DIAGNOSTIC_AUTHORIZATION.is_file() or not DEVELOPMENT_RESULT.is_file():
        raise V28Error("diagnostic is not authorized")
    authorization = json.loads(DIAGNOSTIC_AUTHORIZATION.read_text(encoding="utf-8"))
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    if not development.get("selector_passed"):
        raise V28Error("development did not pass")
    checks = {
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
    }
    drift = {key: [authorization.get(key), value] for key, value in checks.items() if authorization.get(key) != value}
    if drift:
        raise V28Error(f"diagnostic authorization drift: {drift}")
    return authorization


def diagnostic_source_hashes() -> dict[str, str]:
    paths: dict[str, Path] = {
        "v27_2022_2023_entries": V27_DIAGNOSTIC_ENTRIES,
        "v27_2024_entries": V27_LATER_ENTRIES,
    }
    paths.update({f"cy033_{year}": cy033_file(year) for year in (2021, *DIAGNOSTIC_YEARS)})
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise V28Error(f"missing diagnostic Stage-A sources: {missing}")
    return {name: sha256(path) for name, path in paths.items()}


def _build_diagnostic_part(
    entries_path: Path,
    years: tuple[int, ...],
) -> pd.DataFrame:
    entries = pd.read_parquet(entries_path)
    for column in ("signal_date", "signal_time", "entry_date", "entry_time"):
        entries[column] = pd.to_datetime(entries[column])
    entries = entries.loc[entries.signal_date.dt.year.isin(years)].copy()
    if entries.empty or entries.gap_id.duplicated().any():
        raise V28Error(f"diagnostic parent identity failure: {entries_path}")
    daily = load_cy033_feature_daily(years)
    featured = attach_prior_limit_down_feature(entries, daily)
    featured = load_signal_state(featured, years)
    featured["v28_liquidity_trap_gate"] = featured.liquidity_trap_guard
    featured["v28_signal_non_st_gate"] = featured.signal_is_st.eq(False).fillna(False)
    featured["v28_feature_latest_timestamp"] = featured.signal_state_available_at
    featured["v28_feature_uses_post_signal_information"] = False
    return featured


def run_diagnostic_stage_a() -> dict[str, Any]:
    authorization = _assert_diagnostic_authorized()
    older = _build_diagnostic_part(
        V27_DIAGNOSTIC_ENTRIES,
        (2022, 2023),
    )
    later = _build_diagnostic_part(V27_LATER_ENTRIES, (2024,))
    featured = pd.concat([older, later], ignore_index=True)
    if featured.gap_id.duplicated().any():
        raise V28Error("duplicate diagnostic gap identity")
    selected = featured.loc[v28_admission_mask(featured)].copy()
    selected = selected.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    if selected.empty or selected.gap_id.duplicated().any():
        raise V28Error("diagnostic selected identity failure")
    replay.repair.write_parquet(selected, diagnostic_selected_path())
    by_year = selected.groupby(selected.signal_date.dt.year).size()
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DIAGNOSTIC_2022_2024_IDENTITY_FREEZE_BEFORE_RETURN_OPEN",
        "authorization_sha256": sha256(DIAGNOSTIC_AUTHORIZATION),
        "authorization": authorization,
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": diagnostic_source_hashes(),
        "parent_entries": len(featured),
        "selected_signals": len(selected),
        "executable_entries": int(selected.entry_status.eq("EXECUTABLE_ENTRY").sum()),
        "selected_by_signal_year": {str(year): int(by_year.get(year, 0)) for year in DIAGNOSTIC_YEARS},
        "rejected_repeated_one_price_limit_down": int(
            featured.prior20_one_price_limit_down_count.gt(MAX_PRIOR_ONE_PRICE_LIMIT_DOWNS).sum()
        ),
        "rejected_st": int(featured.signal_is_st.eq(True).sum()),
        "missing_prior20_count": int(featured.prior20_one_price_limit_down_count.isna().sum()),
        "selected_entries_sha256": sha256(diagnostic_selected_path()),
        "diagnostic_outcomes_opened": "NO_IN_THIS_STAGE",
    }
    write_json(DIAGNOSTIC_STAGE_A_FREEZE, freeze)
    return freeze


def verify_diagnostic_stage_a() -> dict[str, Any]:
    _assert_diagnostic_authorized()
    if not DIAGNOSTIC_STAGE_A_FREEZE.is_file():
        raise V28Error("diagnostic Stage-A freeze missing")
    freeze = json.loads(DIAGNOSTIC_STAGE_A_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "authorization_sha256": sha256(DIAGNOSTIC_AUTHORIZATION),
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "selected_entries_sha256": sha256(diagnostic_selected_path()),
    }
    expected = {
        **{key: freeze.get(key) for key in checks if key != "selected_entries_sha256"},
        "selected_entries_sha256": freeze.get("selected_entries_sha256"),
    }
    drift = {key: [expected.get(key), value] for key, value in checks.items() if expected.get(key) != value}
    sources = diagnostic_source_hashes()
    if sources != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), sources]
    if drift:
        raise V28Error(f"diagnostic Stage-A drift: {drift}")
    return {"verified": True, "checks": checks}


def _read_period(path: Path, date_column: str, years: tuple[int, ...]) -> pd.DataFrame:
    start = pd.Timestamp(f"{min(years)}-01-01")
    end = pd.Timestamp(f"{max(years) + 1}-01-01")
    frame = pd.read_parquet(
        path,
        filters=[(date_column, ">=", start.to_pydatetime()), (date_column, "<", end.to_pydatetime())],
    )
    frame[date_column] = pd.to_datetime(frame[date_column])
    return frame


def run_diagnostic() -> dict[str, Any]:
    verification = verify_diagnostic_stage_a()
    selected = pd.read_parquet(diagnostic_selected_path())
    selected["signal_date"] = pd.to_datetime(selected.signal_date)
    executable = selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    ids = set(executable.gap_id.astype(str))
    old_outcomes = _read_period(
        replay.source_paths("POST_OBSERVATION_DIAGNOSTIC")["outcomes"],
        "signal_date",
        (2022, 2023),
    )
    later_outcomes = _read_period(V27_LATER_OUTCOMES, "signal_date", (2024,))
    outcomes = pd.concat([old_outcomes, later_outcomes], ignore_index=True)
    outcomes = outcomes.loc[outcomes.gap_id.astype(str).isin(ids)].copy()
    for column in ("signal_date", "entry_date", "entry_time", "exit_date", "exit_time"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    if outcomes.gap_id.duplicated().any() or len(outcomes) != len(ids) or set(outcomes.gap_id.astype(str)) != ids:
        raise V28Error("diagnostic outcome identity conservation failure")
    if not outcomes.signal_date.dt.year.isin(DIAGNOSTIC_YEARS).all():
        raise V28Error("diagnostic outcome period boundary failure")
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    old_daily = pd.read_parquet(replay.source_paths("POST_OBSERVATION_DIAGNOSTIC")["outcome_daily"])
    later_daily = pd.read_parquet(V27_LATER_DAILY, filters=[("trade_date", "<=", max_exit.to_pydatetime())])
    daily = pd.concat([old_daily, later_daily], ignore_index=True)
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    duplicated = daily.duplicated(["symbol", "trade_date"], keep=False)
    if duplicated.any():
        overlap = daily.loc[duplicated, ["symbol", "trade_date", "open", "high", "low", "close"]]
        inconsistent = overlap.groupby(["symbol", "trade_date"]).nunique(dropna=False).gt(1).any(axis=1)
        if inconsistent.any():
            raise V28Error("inconsistent overlapping diagnostic daily rows")
    daily = daily.sort_values(["symbol", "trade_date"], kind="mergesort").drop_duplicates(
        ["symbol", "trade_date"], keep="last"
    )
    root = diagnostic_lane_root()
    root.mkdir(parents=True, exist_ok=True)
    replay.repair.write_parquet(outcomes, root / "outcomes.parquet")
    old_k = replay.repair.v1.PORTFOLIO_K
    try:
        replay.repair.v1.PORTFOLIO_K = PORTFOLIO_K
        replay.repair.v1.configure_external(root, max_exit)
        portfolio = replay.repair.v1.run_portfolio(
            outcomes,
            daily.loc[daily.trade_date.le(max_exit)].copy(),
            tuple(range(min(DIAGNOSTIC_YEARS), int(max_exit.year) + 1)),
        )
    finally:
        replay.repair.v1.PORTFOLIO_K = old_k
    accepted = pd.read_parquet(root / "portfolio_accepted.parquet")
    summary = _accepted_summary(accepted, DIAGNOSTIC_YEARS)
    result = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "accepted_summary": summary,
        "portfolio": portfolio,
        "diagnostic_descriptive_checks": {
            "accepted_trades_per_year_gt_50": summary["accepted_trades_per_year"] > MIN_ACCEPTED_TRADES_PER_YEAR,
            "mean_net_ge_4pct": summary["mean_net"] >= MIN_MEAN_NET,
            "average_holding_sessions_lt_15": summary["average_holding_sessions"] < MAX_AVERAGE_HOLDING_SESSIONS,
        },
        "maximum_exit_date_used": str(max_exit.date()),
        "outcome_hashes_opened_after_freeze": {
            "v13_2022_2023_outcomes": sha256(replay.source_paths("POST_OBSERVATION_DIAGNOSTIC")["outcomes"]),
            "v27_2024_2025_outcomes": sha256(V27_LATER_OUTCOMES),
        },
        "scientific_status": "POST_OBSERVATION_DIAGNOSTIC_NOT_PRISTINE_EXTERNAL_VALIDATION",
    }
    write_json(DIAGNOSTIC_RESULT, result)
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    render_report(development, result)
    return result


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.2f}%"


def _year_rows(summary: dict[str, Any], years: tuple[int, ...]) -> list[str]:
    rows: list[str] = []
    for year in years:
        item = summary["yearly_by_signal_year"][str(year)]
        holding = item["average_holding_sessions"]
        holding_text = "—" if holding is None else f"{holding:.2f}"
        rows.append(
            f"|{year}|{item['trades']}|{_pct(item['mean_net'])}|{_pct(item['median_net'])}|"
            f"{_pct(item['win'])}|{_pct(item['severe10'])}|"
            f"{holding_text}|"
        )
    return rows


def render_report(development: dict[str, Any], diagnostic: dict[str, Any] | None) -> None:
    dev = development["accepted_summary"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Fixed rule",
        "",
        "Keep V27 M20/F14/R5 and its exact A67/H20/no-stop/K80 execution. At the completed signal close, require registered CY033 hard-valid non-ST state and no more than one one-price limit-down in the preceding 20 completed sessions.",
        "",
        "Economic meaning: one isolated limit-down may be capitulation; repeated one-price limit-downs are rationed selling, so low printed volume is not evidence that supply is exhausted.",
        "",
        "## Development: 2018-2021",
        "",
        f"Accepted {dev['accepted_trades']} ({dev['accepted_trades_per_year']:.2f}/year), mean {_pct(dev['mean_net'])}, median {_pct(dev['median_net'])}, win {_pct(dev['win'])}, severe loss <=-10% {_pct(dev['severe10'])}, average holding {dev['average_holding_sessions']:.2f} sessions.",
        "",
        "|Signal year|Trades|Mean net|Median net|Win|<=-10%|Avg hold|",
        "|---:|---:|---:|---:|---:|---:|---:|",
        *_year_rows(dev, DEVELOPMENT_YEARS),
        "",
        f"Selector passed: **{development['selector_passed']}**. Checks: `{json.dumps(development['goal_checks'], ensure_ascii=False, sort_keys=True)}`.",
    ]
    if diagnostic is not None:
        diag = diagnostic["accepted_summary"]
        lines.extend(
            [
                "",
                "## Locked diagnostic: 2022-2024",
                "",
                f"Accepted {diag['accepted_trades']} ({diag['accepted_trades_per_year']:.2f}/year), mean {_pct(diag['mean_net'])}, median {_pct(diag['median_net'])}, win {_pct(diag['win'])}, severe loss <=-10% {_pct(diag['severe10'])}, average holding {diag['average_holding_sessions']:.2f} sessions.",
                "",
                "|Signal year|Trades|Mean net|Median net|Win|<=-10%|Avg hold|",
                "|---:|---:|---:|---:|---:|---:|---:|",
                *_year_rows(diag, DIAGNOSTIC_YEARS),
                "",
                "This later period is a locked diagnostic for the new guard, not pristine external validation, because parent V27 itself was selected after observing 2017-2023.",
            ]
        )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("stage-a", "development", "diagnostic-stage-a", "diagnostic", "all"),
        default="all",
    )
    args = parser.parse_args()
    payload: dict[str, Any] = {}
    if args.mode in ("stage-a", "all"):
        payload["stage_a"] = run_stage_a()
    if args.mode in ("development", "all"):
        payload["development"] = run_development()
        if args.mode == "all" and not payload["development"]["selector_passed"]:
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            return
    if args.mode in ("diagnostic-stage-a", "all"):
        payload["diagnostic_stage_a"] = run_diagnostic_stage_a()
    if args.mode in ("diagnostic", "all"):
        payload["diagnostic"] = run_diagnostic()
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
