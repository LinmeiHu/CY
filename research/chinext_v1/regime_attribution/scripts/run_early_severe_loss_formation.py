#!/usr/bin/env python3
"""Locate early severe-loss path formation without testing an exit rule."""

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

import run_day5_market_stock_decomposition as d5d  # noqa: E402
import run_early_path_reversal as reversal  # noqa: E402
import run_phase2_feature_library as phase2  # noqa: E402
import run_winner_loser_trajectory_archaeology as wla  # noqa: E402

SPEC = WORK / "experiments/EXP-SLF-001_spec.json"
CONTROLS = WORK / "artifacts/pre_entry_transitions.csv"
TRADES = WORK / "artifacts/yearly_trades.csv"
ENTRIES = WORK / "artifacts/entry_gap_premium_attribution.csv"
INDEX = ROOT / "research/chinext_v1/data/smoke/399102_daily.csv"
CALENDAR = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet"
)
OUTPUT_TABLE = WORK / "artifacts/early_severe_loss_formation.csv"
OUTPUT_JSON = WORK / "artifacts/early_severe_loss_formation.json"
REPORT = WORK / "reports/early_severe_loss_formation.md"
EVIDENCE_PACKET = WORK / "reports/early_severe_loss_formation_evidence_packet.md"

BASE_CONTROLS = d5d.BASE_CONTROLS


class SevereFormationError(RuntimeError):
    """Raised when a frozen identity, path, or endpoint invariant fails."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_spec() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-SLF-001":
        raise SevereFormationError("unexpected severe-formation identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_EARLY_PATH_OUTCOME_TEST":
        raise SevereFormationError("experiment is not frozen before results")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for name, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        actual = sha256_file(path) if path.is_file() else "MISSING"
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[name] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise SevereFormationError(f"frozen input mismatch: {mismatches}")
    phase2.validate_inputs()
    return spec, identities


def load_base(spec: dict[str, Any]) -> pd.DataFrame:
    columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_execution_date",
        "entry_year",
        "entry_industry",
        "severe_loss",
        "false_breakout",
        "round_trip_return",
        "realized_pnl",
        "holding_trading_days",
        "canonical_exit_reason",
        *BASE_CONTROLS,
    ]
    controls = pd.read_csv(CONTROLS, usecols=columns)
    if len(controls) != 399 or controls.trade_id.nunique() != 399:
        raise SevereFormationError("accepted control population changed")
    paths = pd.read_csv(TRADES, usecols=["trade_id", "return_5d"])
    entries = pd.read_csv(ENTRIES, usecols=["trade_id", "execution_price"])
    frame = controls.merge(paths, on="trade_id", validate="one_to_one")
    frame = frame.merge(entries, on="trade_id", validate="one_to_one")
    frame["severe_loss"] = frame.severe_loss.astype(bool)
    frame["false_breakout"] = frame.false_breakout.astype(bool)
    frame["extreme_loss20"] = frame.round_trip_return <= -0.20
    frame["entry_execution_date"] = pd.to_datetime(
        frame.entry_execution_date, errors="raise"
    )
    sample = spec["sample"]
    checks = {
        "cycles": len(frame),
        "severe_losses": int(frame.severe_loss.sum()),
        "day3_survivors": int((frame.holding_trading_days >= 3).sum()),
        "day3_severe_losses": int(
            frame.loc[frame.holding_trading_days >= 3, "severe_loss"].sum()
        ),
        "day5_survivors": int((frame.holding_trading_days >= 5).sum()),
        "day5_severe_losses": int(
            frame.loc[frame.holding_trading_days >= 5, "severe_loss"].sum()
        ),
        "fixed_control_complete_day3": int(
            frame.loc[frame.holding_trading_days >= 3, list(BASE_CONTROLS)]
            .notna()
            .all(axis=1)
            .sum()
        ),
    }
    expected = {key: sample[key] for key in checks}
    if checks != expected:
        raise SevereFormationError(f"severe-formation sample changed: {checks}")
    return frame


def reconstruct_paths(
    frame: pd.DataFrame, spec: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    identities = frame[
        ["trade_id", "baseline_block", "symbol", "entry_execution_date", "holding_trading_days"]
    ].copy()
    identities["max_offset"] = np.select(
        [identities.holding_trading_days >= 5, identities.holding_trading_days >= 3],
        [4, 2],
        default=1,
    ).astype(int)
    contract = spec["transient_contract"]
    with tempfile.TemporaryDirectory(prefix="chinext_v1_slf001_") as temporary:
        transient_root = Path(temporary)
        manifest = phase2.extended.materialize_transient_inputs(transient_root)
        if manifest["canonical_sha256"] != contract["canonical_sha256"]:
            raise SevereFormationError("transient canonical identity changed")
        if manifest["membership"]["sha256"] != contract["membership_sha256"]:
            raise SevereFormationError("transient membership identity changed")
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
              SELECT i.*,c.cal_idx AS entry_idx
              FROM entry_ids i
              JOIN calendar c ON CAST(i.entry_execution_date AS DATE)=c.trade_date
            )
            SELECT m.trade_id,m.entry_idx,m.max_offset,w.cal_idx,w.trade_date,
                   w.close,w.critical_valid,w.coordinate_step_valid,
                   w.corporate_action_count,w.corporate_action_available_date,
                   w.corporate_action_blocking,w.corporate_action_valid,
                   w.share_multiplier,w.cash_per_share,w.rights_ratio
            FROM mapped m
            JOIN stock_windows w
              ON w.baseline_block=m.baseline_block AND w.symbol=m.symbol
             AND w.cal_idx BETWEEN m.entry_idx AND m.entry_idx+m.max_offset
            ORDER BY m.trade_id,w.cal_idx
            """
        ).fetchdf()
        connection.close()
    expected_rows = int((identities.max_offset + 1).sum())
    if len(rows) != expected_rows:
        raise SevereFormationError(f"early path row count changed: {len(rows)}")
    expected_sizes = identities.set_index("trade_id").max_offset.add(1)
    actual_sizes = rows.groupby("trade_id").size()
    if not actual_sizes.reindex(expected_sizes.index).eq(expected_sizes).all():
        raise SevereFormationError("per-trade early path coverage changed")
    if not rows.critical_valid.astype(bool).all():
        raise SevereFormationError("hard-invalid early path row")
    after_entry = rows.cal_idx > rows.entry_idx
    if not rows.loc[after_entry, "coordinate_step_valid"].astype(bool).all():
        raise SevereFormationError("invalid early-path action coordinate")

    prices = frame[["trade_id", "execution_price", "return_5d"]]
    rows = rows.merge(prices, on="trade_id", validate="many_to_one")
    features: list[dict[str, Any]] = []
    action_trades = 0
    return5_errors: list[float] = []
    for trade_id, group in rows.groupby("trade_id", sort=True):
        group = group.sort_values("cal_idx")
        entry_price = float(group.execution_price.iloc[0])
        share_factor = 1.0
        cash_per_original_share = 0.0
        returns: dict[int, float] = {}
        action_count = 0
        for offset, row in enumerate(group.itertuples()):
            count = int(row.corporate_action_count or 0)
            if offset > 0 and count > 0:
                multiplier = reversal.finite_or_default(row.share_multiplier, 1.0)
                cash = reversal.finite_or_default(row.cash_per_share, 0.0)
                rights = reversal.finite_or_default(row.rights_ratio, 0.0)
                visible = pd.notna(row.corporate_action_available_date) and (
                    str(row.corporate_action_available_date)[:10]
                    <= str(row.trade_date)[:10]
                )
                valid = (
                    not bool(row.corporate_action_blocking)
                    and bool(row.corporate_action_valid)
                    and visible
                    and rights == 0.0
                    and multiplier > 0.0
                )
                if not valid:
                    raise SevereFormationError(f"unresolved early action: {trade_id}")
                cash_per_original_share += share_factor * cash
                share_factor *= multiplier
                action_count += count
            returns[offset] = (
                (share_factor * float(row.close) + cash_per_original_share) / entry_price
                - 1.0
            )
        if action_count:
            action_trades += 1
        return5 = returns.get(4)
        if return5 is not None:
            accepted = float(group.return_5d.iloc[0])
            error = abs(return5 - accepted)
            if error > 1e-12:
                raise SevereFormationError(f"day-5 reconstruction mismatch: {trade_id}")
            return5_errors.append(error)
        features.append(
            {
                "trade_id": trade_id,
                "return_2d": returns[1],
                "return_3d": returns.get(2),
                "return_5d_rebuilt": return5,
                "early_action_count": action_count,
            }
        )
    feature_frame = pd.DataFrame(features)
    if feature_frame.return_3d.notna().sum() != spec["sample"]["day3_survivors"]:
        raise SevereFormationError("day-3 reconstructed availability changed")
    if feature_frame.return_5d_rebuilt.notna().sum() != spec["sample"]["day5_survivors"]:
        raise SevereFormationError("day-5 reconstructed availability changed")
    audit = {
        "path_rows": int(len(rows)),
        "expected_path_rows": expected_rows,
        "day2_paths": int(feature_frame.return_2d.notna().sum()),
        "day3_paths": int(feature_frame.return_3d.notna().sum()),
        "day5_paths": int(feature_frame.return_5d_rebuilt.notna().sum()),
        "early_action_cycles": action_trades,
        "invalid_path_rows": 0,
        "return5_max_abs_reconstruction_error": max(return5_errors),
        "transient_canonical_sha256": manifest["canonical_sha256"],
        "transient_membership_sha256": manifest["membership"]["sha256"],
        "panel_counts": panel_counts,
    }
    return feature_frame, audit


def attach_market_components(
    frame: pd.DataFrame, spec: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    calendar = pd.read_parquet(CALENDAR, columns=["trade_date"])
    calendar["trade_date"] = pd.to_datetime(calendar.trade_date, errors="raise")
    calendar = calendar.sort_values("trade_date").reset_index(drop=True)
    if calendar.trade_date.duplicated().any():
        raise SevereFormationError("calendar dates are not unique")
    calendar["cal_idx"] = np.arange(len(calendar), dtype=int)
    frame = frame.merge(
        calendar.rename(columns={"trade_date": "entry_execution_date"}),
        on="entry_execution_date",
        how="left",
        validate="many_to_one",
    )
    if frame.cal_idx.isna().any():
        raise SevereFormationError("entry date missing from calendar")
    date_by_index = dict(zip(calendar.cal_idx, calendar.trade_date, strict=True))
    for horizon, offset in ((2, 1), (3, 2), (5, 4)):
        frame[f"day{horizon}_session_date"] = [
            date_by_index.get(int(index) + offset)
            if holding >= horizon
            else pd.NaT
            for index, holding in zip(
                frame.cal_idx, frame.holding_trading_days, strict=True
            )
        ]
    index = pd.read_csv(INDEX, dtype={"trade_date": str})
    index["trade_date"] = pd.to_datetime(index.trade_date, format="%Y%m%d")
    if index.trade_date.duplicated().any():
        raise SevereFormationError("399102 dates are not unique")
    for column in ("open", "close"):
        index[column] = pd.to_numeric(index[column], errors="raise")
    frame = frame.merge(
        index[["trade_date", "open"]].rename(
            columns={"trade_date": "entry_execution_date", "open": "market_entry_open"}
        ),
        on="entry_execution_date",
        validate="many_to_one",
    )
    for horizon in (2, 3, 5):
        frame = frame.merge(
            index[["trade_date", "close"]].rename(
                columns={
                    "trade_date": f"day{horizon}_session_date",
                    "close": f"market_day{horizon}_close",
                }
            ),
            on=f"day{horizon}_session_date",
            how="left",
            validate="many_to_one",
        )
        eligible = frame.holding_trading_days >= horizon
        if frame.loc[eligible, f"market_day{horizon}_close"].isna().any():
            raise SevereFormationError(f"market day-{horizon} close missing")
        stock_return = frame[f"return_{horizon}d"] if horizon < 5 else frame.return_5d_rebuilt
        market_log = np.log(
            frame[f"market_day{horizon}_close"] / frame.market_entry_open
        )
        stock_log = np.log1p(stock_return)
        frame[f"market_day{horizon}_log_return"] = market_log
        frame[f"adverse_stock_specific_{horizon}d"] = -(stock_log - market_log)
    frame["adverse_beta_adjusted_3d"] = -(
        np.log1p(frame.return_3d)
        - frame.entry_beta60 * frame.market_day3_log_return
    )
    if not (frame.market_entry_open > 0).all():
        raise SevereFormationError("invalid market entry open")
    audit = {
        "calendar_unique": True,
        "index_unique": True,
        "market_entry_open_complete": int(frame.market_entry_open.notna().sum()),
        "market_day2_complete": int(frame.market_day2_close.notna().sum()),
        "market_day3_complete": int(frame.market_day3_close.notna().sum()),
        "market_day5_complete": int(frame.market_day5_close.notna().sum()),
    }
    expected = spec["sample"]
    if audit["market_day2_complete"] != expected["cycles"]:
        raise SevereFormationError("day-2 market coverage changed")
    if audit["market_day3_complete"] != expected["day3_survivors"]:
        raise SevereFormationError("day-3 market coverage changed")
    if audit["market_day5_complete"] != expected["day5_survivors"]:
        raise SevereFormationError("day-5 market coverage changed")
    return frame, audit


def load_analysis_frame(
    spec: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = load_base(spec)
    path, path_audit = reconstruct_paths(frame, spec)
    frame = frame.merge(path, on="trade_id", validate="one_to_one")
    frame, market_audit = attach_market_components(frame, spec)
    day3 = frame[frame.return_3d.notna()].copy()
    block_counts = {
        str(name): {
            "rows": int(len(rows)),
            "severe_losses": int(rows.severe_loss.sum()),
            "endpoint_levels": int(rows.severe_loss.nunique()),
        }
        for name, rows in day3.groupby("baseline_block", sort=True)
    }
    if block_counts != spec["block_endpoint_counts_day3"]:
        raise SevereFormationError(f"day-3 block endpoint counts changed: {block_counts}")
    audit = {
        **path_audit,
        **market_audit,
        "cycles": int(len(frame)),
        "severe_losses": int(frame.severe_loss.sum()),
        "day3_survivors": int(len(day3)),
        "day3_severe_losses": int(day3.severe_loss.sum()),
        "day3_fixed_control_complete": int(
            day3[list(BASE_CONTROLS)].notna().all(axis=1).sum()
        ),
        "early_exit_before_day3_cycles": int(frame.return_3d.isna().sum()),
        "early_exit_before_day3_severe_losses": int(
            frame.loc[frame.return_3d.isna(), "severe_loss"].sum()
        ),
        "block_endpoint_counts_day3": block_counts,
        "available_at_timestamp": "DAY3_SESSION_15:30_ASIA_SHANGHAI",
        "potential_action_timestamp": "NEXT_VALID_SESSION_OR_LATER_ONLY; EXPLANATORY_TEST_AUTHORIZES_NO_ACTION",
        "post_exit_prices_read": 0,
        "counterfactual_returns": 0,
        "strategy_replays": 0,
        "thresholds_or_rules_tested": 0,
    }
    return frame, audit


def bottom_flag(frame: pd.DataFrame, n: int) -> pd.Series:
    ordered = frame.sort_values(["realized_pnl", "trade_id"], ascending=[True, True])
    flag = pd.Series(False, index=frame.index)
    flag.loc[ordered.head(n).index] = True
    return flag


def analyze(frame: pd.DataFrame) -> dict[str, Any]:
    feature = "adverse_stock_specific_3d"
    endpoint = "severe_loss"
    day3 = frame[frame.return_3d.notna()].copy()
    raw = wla.rank_association(day3, feature, endpoint)
    controlled = d5d.controlled_loyo(
        day3, feature, endpoint, extra_controls=("market_day3_log_return",)
    )
    beta = wla.rank_association(day3, "adverse_beta_adjusted_3d", endpoint)
    day2 = wla.rank_association(frame, "adverse_stock_specific_2d", endpoint)
    day5 = wla.rank_association(
        frame[frame.return_5d_rebuilt.notna()], "adverse_stock_specific_5d", endpoint
    )
    duration_exit = d5d.partial_rank(
        day3,
        feature,
        endpoint,
        extra_controls=("market_day3_log_return", "holding_trading_days"),
        category_controls=("entry_year", "canonical_exit_reason"),
    )
    bottom4 = bottom_flag(day3, 4)
    ex_bottom4 = wla.rank_association(day3.loc[~bottom4], feature, endpoint)
    severe_symbols = sorted(day3.loc[day3.severe_loss, "symbol"].astype(str).unique())
    security = wla.omit_group_sensitivity(
        day3, feature, endpoint, "symbol", severe_symbols
    )
    industry = wla.omit_group_sensitivity(
        day3[day3.entry_industry.notna()], feature, endpoint, "entry_industry"
    )
    blocks = {
        str(name): wla.safe_spearman(rows[feature], rows[endpoint])
        for name, rows in day3.groupby("baseline_block", sort=True)
    }
    block_rhos = [packet["rho"] for packet in blocks.values() if packet["rho"] is not None]

    raw_gate = bool(
        raw["rho"] is not None
        and raw["rho"] >= 0.15
        and raw["within_year_rank_rho"] is not None
        and raw["within_year_rank_rho"] > 0
        and raw["loyo_positive_count"] >= 7
    )
    controlled_gate = bool(
        controlled["partial_rank_rho"] is not None
        and controlled["partial_rank_rho"] >= 0.15
        and controlled["loyo_positive_count"] >= 7
    )
    neighbor_gate = bool(
        day2["rho"] is not None
        and day2["rho"] > 0
        and day2["loyo_positive_count"] >= 6
        and day5["rho"] is not None
        and day5["rho"] > 0
        and day5["loyo_positive_count"] >= 6
        and beta["rho"] is not None
        and beta["rho"] >= 0.10
        and beta["loyo_positive_count"] >= 6
    )
    temporal_gate = bool(
        len(block_rhos) == 3
        and sum(value > 0 for value in block_rhos) >= 2
        and min(block_rhos) >= 0
    )
    falsification_gate = bool(
        duration_exit["partial_rank_rho"] is not None
        and duration_exit["partial_rank_rho"] >= 0.10
        and ex_bottom4["rho"] is not None
        and ex_bottom4["rho"] > 0
        and security["positive_fraction"] is not None
        and security["positive_fraction"] >= 0.80
        and industry["positive_fraction"] is not None
        and industry["positive_fraction"] >= 0.80
    )
    if all((raw_gate, controlled_gate, neighbor_gate, temporal_gate, falsification_gate)):
        decision = "DEEPEN"
        verdict = "SEVERE_LOSS_PATH_SEPARATES_BY_DAY3_WITH_QUALIFICATION"
    elif raw_gate and controlled_gate:
        decision = "REFINE"
        verdict = "DAY3_ADVERSE_PATH_SURVIVES_CORE_BUT_NOT_FULL_FALSIFICATION"
    elif raw_gate:
        decision = "PIVOT"
        verdict = "RAW_DAY3_ADVERSE_PATH_IS_REDUNDANT_OR_UNSTABLE"
    else:
        decision = "REJECT"
        verdict = "NO_STABLE_DAY3_SEVERE_LOSS_FORMATION"
    return {
        "experiment_id": "EXP-SLF-001",
        "decision": decision,
        "mechanism_verdict": verdict,
        "primary": {
            "day3_stock_specific_adverse_raw": raw,
            "day3_stock_specific_adverse_controlled": controlled,
            "day3_beta_adjusted_neighbor": beta,
            "day2_neighbor_all_cycles": day2,
            "day5_neighbor_survivors": day5,
            "duration_exit_control": duration_exit,
            "ex_bottom4_pnl": ex_bottom4,
            "leave_one_severe_security_out": security,
            "leave_one_industry_out": industry,
            "blocks": blocks,
            "raw_gate": raw_gate,
            "controlled_gate": controlled_gate,
            "neighbor_gate": neighbor_gate,
            "temporal_gate": temporal_gate,
            "falsification_gate": falsification_gate,
        },
        "secondary": {
            "extreme_loss20": wla.rank_association(day3, feature, "extreme_loss20"),
            "false_breakout": wla.rank_association(day3, feature, "false_breakout"),
            "terminal_return": wla.rank_association(day3, feature, "round_trip_return"),
        },
        "strategy_modification": "NONE",
        "interpretation_boundary": (
            "day-3 return is post-entry, survivor-conditioned, and embedded in "
            "terminal loss; the test locates path separation and cannot support "
            "an entry, stop, hold, exit, or production rule"
        ),
    }


def fmt(value: Any) -> str:
    number = wla.finite_or_none(value)
    return "NA" if number is None else f"{number:.3f}"


def build_report(result: dict[str, Any], audit: dict[str, Any]) -> str:
    primary = result["primary"]
    return "\n".join(
        [
            "# Early severe-loss formation",
            "",
            "EXP-SLF-001 tests whether stock-specific adverse return is already visible by the third held session. It is path attribution, not a stop or exit experiment.",
            "",
            "## Integrity and timing",
            "",
            f"- All cycles/severe losses: `{audit['cycles']}` / `{audit['severe_losses']}`.",
            f"- Day-3 survivors/severe/control-complete: `{audit['day3_survivors']}` / `{audit['day3_severe_losses']}` / `{audit['day3_fixed_control_complete']}`.",
            f"- Early exits before Day 3/severe: `{audit['early_exit_before_day3_cycles']}` / `{audit['early_exit_before_day3_severe_losses']}`; they remain in the Day-2 neighbor.",
            f"- Action-safe path rows/action cycles/Day-5 reconstruction error: `{audit['path_rows']}` / `{audit['early_action_cycles']}` / `{audit['return5_max_abs_reconstruction_error']:.3g}`.",
            f"- AVAILABLE_AT_TIMESTAMP: `{audit['available_at_timestamp']}`.",
            f"- POTENTIAL_ACTION_TIMESTAMP: `{audit['potential_action_timestamp']}`.",
            "",
            "## Frozen tests",
            "",
            "| Test | Estimate | LOYO + |",
            "|---|---:|---:|",
            f"| Day-3 stock-specific adverse raw | {fmt(primary['day3_stock_specific_adverse_raw']['rho'])} | {primary['day3_stock_specific_adverse_raw']['loyo_positive_count']}/8 |",
            f"| Day-3 controlled | {fmt(primary['day3_stock_specific_adverse_controlled']['partial_rank_rho'])} | {primary['day3_stock_specific_adverse_controlled']['loyo_positive_count']}/8 |",
            f"| Day-3 beta-adjusted neighbor | {fmt(primary['day3_beta_adjusted_neighbor']['rho'])} | {primary['day3_beta_adjusted_neighbor']['loyo_positive_count']}/8 |",
            f"| Day-2 all-cycle neighbor | {fmt(primary['day2_neighbor_all_cycles']['rho'])} | {primary['day2_neighbor_all_cycles']['loyo_positive_count']}/8 |",
            f"| Day-5 survivor neighbor | {fmt(primary['day5_neighbor_survivors']['rho'])} | {primary['day5_neighbor_survivors']['loyo_positive_count']}/8 |",
            "",
            f"Gates raw/control/neighbor/temporal/falsification: `{primary['raw_gate']}` / `{primary['controlled_gate']}` / `{primary['neighbor_gate']}` / `{primary['temporal_gate']}` / `{primary['falsification_gate']}`.",
            "",
            "## Decision",
            "",
            f"`{result['decision']}` / `{result['mechanism_verdict']}`.",
            "",
            "No entry, stop, holding, exit, ranking, sizing, replay, or production modification was tested or authorized.",
            "",
        ]
    )


def build_packet(result: dict[str, Any], audit: dict[str, Any]) -> str:
    primary = result["primary"]
    return "\n".join(
        [
            "# EXP-SLF-001 structured evidence packet",
            "",
            "## Question",
            "",
            "Does action-safe stock-specific adverse return become distinguishable by the third held session among accepted severe-loss outcomes?",
            "",
            "## Population and lineage",
            "",
            f"- Day-3 population/severe losses: `{audit['day3_survivors']}` / `{audit['day3_severe_losses']}`.",
            f"- Path rows and invalid rows: `{audit['path_rows']}` / `{audit['invalid_path_rows']}`.",
            f"- Available/action timestamps: `{audit['available_at_timestamp']}` / `{audit['potential_action_timestamp']}`.",
            "",
            "## Result",
            "",
            f"- Raw/controlled: `{fmt(primary['day3_stock_specific_adverse_raw']['rho'])}` / `{fmt(primary['day3_stock_specific_adverse_controlled']['partial_rank_rho'])}`.",
            f"- Decision: `{result['decision']}` / `{result['mechanism_verdict']}`.",
            "",
            "## Boundary",
            "",
            "The feature is post-entry and outcome-overlapping. No threshold, stop, hold/exit policy, replay, or V1 modification was tested.",
            "",
        ]
    )


def main() -> int:
    spec, identities = validate_spec()
    frame, audit = load_analysis_frame(spec)
    result = analyze(frame)
    result.update(
        {
            "spec_sha256": sha256_file(SPEC),
            "input_identities": identities,
            "audit": audit,
            "evidence_grade": "EXPLORATORY_HOLDING_PATH_MECHANISM",
            "breadth_h004_status": "PROSPECTIVE_VALIDATION_PENDING_FROZEN",
        }
    )
    columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_execution_date",
        "entry_year",
        "entry_industry",
        "holding_trading_days",
        "canonical_exit_reason",
        "return_2d",
        "return_3d",
        "return_5d_rebuilt",
        "market_day2_log_return",
        "market_day3_log_return",
        "market_day5_log_return",
        "adverse_stock_specific_2d",
        "adverse_stock_specific_3d",
        "adverse_stock_specific_5d",
        "adverse_beta_adjusted_3d",
        "early_action_count",
        "severe_loss",
        "extreme_loss20",
        "false_breakout",
        "round_trip_return",
        "realized_pnl",
        *BASE_CONTROLS,
    ]
    atomic_write(
        OUTPUT_TABLE,
        frame[columns].sort_values("trade_id").to_csv(
            index=False, lineterminator="\n", float_format="%.17g"
        ),
    )
    atomic_write(
        OUTPUT_JSON, json.dumps(wla.clean_json(result), indent=2, sort_keys=True) + "\n"
    )
    atomic_write(REPORT, build_report(result, audit))
    atomic_write(EVIDENCE_PACKET, build_packet(result, audit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
