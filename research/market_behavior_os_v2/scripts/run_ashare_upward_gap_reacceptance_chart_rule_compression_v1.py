#!/usr/bin/env python3
"""Replay the fixed chart-derived rule compression for upward-gap reacceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import run_ashare_upward_information_gap_rejection_reacceptance_12m_chart_discovery_v1 as parent

EXPERIMENT = "ASHARE-UPWARD-GAP-REACCEPTANCE-CHART-RULE-COMPRESSION-V1"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "da5198decbfd7adba782d6579e34cea4f8d1d74aadf8b6da82e680db0106898a"

DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
PARENT_ROOT = DATA_ROOT / "ashare_upward_information_gap_rejection_reacceptance_chart_discovery_v1"
CANDIDATES = PARENT_ROOT / "stage_a/frozen_candidates.parquet"
WINDOWS = PARENT_ROOT / "stage_b/chart_window_panel.parquet"
PARENT_OUTCOMES = PARENT_ROOT / "stage_b/baseline_outcomes.parquet"
REGIME = (
    DATA_ROOT
    / "ashare_causal_market_regime_routed_simple_strategy_v1"
    / "stage_a/causal_market_regime_2014_2023.parquet"
)

EXPECTED_CANDIDATE_SHA256 = "2dab45911a89689504d0070062654fbe53f59b7fffdf134c15d6ab5e98aeb238"
EXPECTED_WINDOW_SHA256 = "d12cb32776b6409a8d64ddc6cd935de6295ef0ad0a5839562ca67a86335dfaee"
EXPECTED_PARENT_OUTCOME_SHA256 = "145385ab488bb4f9d3eaf359065fe4aeaecb4fcaf7ce6e69ebb93a43aa23f57c"
EXPECTED_REGIME_SHA256 = "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a"

OUTPUT_ROOT = DATA_ROOT / "ashare_upward_gap_reacceptance_chart_rule_compression_v1"
RESULT = OUTPUT_ROOT / "result.json"
SUMMARY = OUTPUT_ROOT / "fixed_incremental_summary.csv"
ANATOMY = OUTPUT_ROOT / "frozen_rule_anatomy.csv"

CONFIRMATION_HORIZON = 3
ENTRY_HORIZON = 3
MAX_PEAK_HEADROOM = 0.30
TARGET_FRACTION = 0.67
MIN_NET_HEADROOM = 0.04
HORIZON = 60
COST = 0.004
MAX_DECISION_DATE = pd.Timestamp("2020-12-31")

VARIANTS: dict[str, dict[str, bool]] = {
    "R1_STRUCTURAL_FAILURE_EXIT_ONLY": {
        "persistence": False,
        "peak_distance": False,
        "market_deterioration_veto": False,
        "failure_exit": True,
    },
    "R2_ACCEPTANCE_PERSISTENCE_PLUS_EXIT": {
        "persistence": True,
        "peak_distance": False,
        "market_deterioration_veto": False,
        "failure_exit": True,
    },
    "R3_PEAK_DISTANCE_PLUS_PERSISTENCE_PLUS_EXIT": {
        "persistence": True,
        "peak_distance": True,
        "market_deterioration_veto": False,
        "failure_exit": True,
    },
    "R4_FINAL_ALL_FIVE_RULES": {
        "persistence": True,
        "peak_distance": True,
        "market_deterioration_veto": True,
        "failure_exit": True,
    },
}


class ResearchError(RuntimeError):
    """Fail closed on identity, chronology, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(
        f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()


def verify_sources() -> dict[str, str]:
    expected = {
        "freeze": (FREEZE, EXPECTED_FREEZE_SHA256),
        "candidates": (CANDIDATES, EXPECTED_CANDIDATE_SHA256),
        "windows": (WINDOWS, EXPECTED_WINDOW_SHA256),
        "parent_outcomes": (PARENT_OUTCOMES, EXPECTED_PARENT_OUTCOME_SHA256),
        "regime": (REGIME, EXPECTED_REGIME_SHA256),
    }
    actual: dict[str, str] = {}
    for name, (path, expected_hash) in expected.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen source: {path}")
        actual[name] = sha256(path)
        if actual[name] != expected_hash:
            raise ResearchError(
                f"{name} identity drift: {actual[name]} != {expected_hash}"
            )
    return actual


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    connection = duckdb.connect()
    connection.execute("PRAGMA threads=4")
    candidates = connection.execute(
        f"SELECT * FROM read_parquet('{CANDIDATES.as_posix()}') "
        "ORDER BY signal_date,symbol,event_id"
    ).fetch_df()
    windows = connection.execute(
        f"SELECT * FROM read_parquet('{WINDOWS.as_posix()}') "
        "ORDER BY event_id,cal_idx"
    ).fetch_df()
    parent_outcomes = connection.execute(
        f"SELECT * FROM read_parquet('{PARENT_OUTCOMES.as_posix()}') "
        "ORDER BY signal_date,symbol,event_id"
    ).fetch_df()
    regime = connection.execute(
        f"""
        SELECT trade_date,market_regime,market_median_ret20,
          market_positive_ret20_share,market_median_ret60,
          market_positive_ret60_share,
          latest_source_timestamp AS market_latest_source_timestamp
        FROM read_parquet('{REGIME.as_posix()}')
        WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ORDER BY trade_date
        """
    ).fetch_df()
    connection.close()
    for frame, columns in (
        (
            candidates,
            [
                "signal_date",
                "signal_time",
                "available_at",
                "decision_at",
                "market_latest_source_timestamp",
            ],
        ),
        (windows, ["trade_date", "available_at", "decision_at"]),
        (parent_outcomes, ["signal_date", "entry_date", "exit_date"]),
        (regime, ["trade_date", "market_latest_source_timestamp"]),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    if candidates.event_id.duplicated().any():
        raise ResearchError("duplicate candidate identity")
    if candidates.signal_date.max() > MAX_DECISION_DATE:
        raise ResearchError("parent candidate date exceeds development freeze")
    if windows.trade_date.max() > pd.Timestamp("2021-07-12"):
        raise ResearchError("unexpected post-chart-tail bar")
    if regime.market_latest_source_timestamp.gt(
        regime.trade_date + pd.Timedelta(hours=15)
    ).any():
        raise ResearchError("causal regime timestamp is after its decision close")
    return candidates, windows, parent_outcomes, regime


def first_persistence_confirmation(
    candidate: Any, path: pd.DataFrame
) -> tuple[Any | None, str | None]:
    """Return the first valid post-signal bar iff it remains above frozen U."""
    signal_idx = int(candidate.signal_cal_idx)
    lineage = float(candidate.lineage)
    tail = path.loc[
        path.cal_idx.gt(signal_idx)
        & path.cal_idx.le(signal_idx + CONFIRMATION_HORIZON)
    ]
    for row in tail.itertuples(index=False):
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return None, "LINEAGE_BREAK_BEFORE_CONFIRMATION"
        if not parent.valid_row(row):
            continue
        if float(row.coord_close) <= float(candidate.gap_U):
            return None, "NO_PERSISTENCE_CONFIRMATION"
        return row, None
    return None, "NO_VALID_CONFIRMATION_SESSION"


def decision_payload(
    candidate: Any,
    path: pd.DataFrame,
    regime_by_date: dict[pd.Timestamp, Any],
    rules: dict[str, bool],
) -> tuple[dict[str, Any], str | None]:
    base = {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "original_signal_date": pd.Timestamp(candidate.signal_date),
        "original_signal_cal_idx": int(candidate.signal_cal_idx),
        "gap_L": float(candidate.gap_L),
        "gap_U": float(candidate.gap_U),
        "pre_rejection_peak_P": float(candidate.pre_rejection_peak_P),
        "peak_headroom_from_U": float(candidate.peak_headroom_from_U),
        "lineage": float(candidate.lineage),
    }
    if rules["peak_distance"] and float(candidate.peak_headroom_from_U) > MAX_PEAK_HEADROOM:
        return {**base, "qualified_signal": False}, "PEAK_DESTINATION_TOO_REMOTE"

    if rules["persistence"]:
        confirmation, reason = first_persistence_confirmation(candidate, path)
        if confirmation is None:
            return {**base, "qualified_signal": False}, reason
        decision_date = pd.Timestamp(confirmation.trade_date)
        decision_idx = int(confirmation.cal_idx)
        feature_available_at = pd.Timestamp(confirmation.available_at)
        decision_at = pd.Timestamp(confirmation.decision_at)
    else:
        decision_date = pd.Timestamp(candidate.signal_date)
        decision_idx = int(candidate.signal_cal_idx)
        feature_available_at = pd.Timestamp(candidate.available_at)
        decision_at = pd.Timestamp(candidate.decision_at)
    if decision_date > MAX_DECISION_DATE:
        return {**base, "qualified_signal": False}, "CONFIRMATION_AFTER_DEVELOPMENT_END"
    if feature_available_at > decision_at:
        raise ResearchError(f"{candidate.event_id}: decision feature unavailable")

    regime = regime_by_date.get(decision_date.normalize())
    if regime is None:
        raise ResearchError(f"{candidate.event_id}: missing causal regime at {decision_date}")
    if pd.Timestamp(regime.market_latest_source_timestamp) > decision_at:
        raise ResearchError(f"{candidate.event_id}: market state after decision")
    deteriorating = bool(
        float(regime.market_median_ret20) < float(regime.market_median_ret60)
        and float(regime.market_positive_ret20_share)
        < float(regime.market_positive_ret60_share)
    )
    payload = {
        **base,
        "decision_date": decision_date,
        "decision_cal_idx": decision_idx,
        "decision_at": decision_at,
        "feature_available_at": feature_available_at,
        "market_regime": str(regime.market_regime),
        "market_median_ret20": float(regime.market_median_ret20),
        "market_positive_ret20_share": float(regime.market_positive_ret20_share),
        "market_median_ret60": float(regime.market_median_ret60),
        "market_positive_ret60_share": float(regime.market_positive_ret60_share),
        "market_deteriorating": deteriorating,
        "qualified_signal": not (
            rules["market_deterioration_veto"] and deteriorating
        ),
    }
    if rules["market_deterioration_veto"] and deteriorating:
        return payload, "CAUSAL_MARKET_DETERIORATION_VETO"
    return payload, None


def replay_one(
    candidate: Any,
    path: pd.DataFrame,
    regime_by_date: dict[pd.Timestamp, Any],
    rules: dict[str, bool],
) -> dict[str, Any]:
    decision, rejection = decision_payload(candidate, path, regime_by_date, rules)
    if rejection is not None:
        return {**decision, "status": rejection}
    decision_idx = int(decision["decision_cal_idx"])
    lineage = float(decision["lineage"])
    future = path.loc[path.cal_idx.gt(decision_idx)]
    entry = next(
        (
            row
            for row in future.loc[
                future.cal_idx.le(decision_idx + ENTRY_HORIZON)
            ].itertuples(index=False)
            if np.isfinite(float(row.invalid_step_cum))
            and float(row.invalid_step_cum) == lineage
            and parent.buyable_open(row)
        ),
        None,
    )
    if entry is None:
        return {**decision, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    target = entry_price + TARGET_FRACTION * (
        float(decision["pre_rejection_peak_P"]) - entry_price
    )
    net_target_headroom = target / entry_price - 1.0 - COST
    entry_payload = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
        "target_price": target,
        "net_target_headroom": net_target_headroom,
    }
    if not target > entry_price or not target < float(decision["pre_rejection_peak_P"]):
        return {**decision, **entry_payload, "status": "NO_POSITIVE_STRUCTURAL_TARGET"}
    if net_target_headroom < MIN_NET_HEADROOM:
        return {**decision, **entry_payload, "status": "INSUFFICIENT_TARGET_HEADROOM"}

    pending_failure = False
    failure_signal_date: pd.Timestamp | None = None
    pending_time = False
    for row in future.loc[future.cal_idx.gt(entry_idx)].itertuples(index=False):
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != lineage:
            return {
                **decision,
                **entry_payload,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
            }
        if pending_failure and parent.sellable_open(row):
            gross = float(row.coord_open) / entry_price - 1.0
            return {
                **decision,
                **entry_payload,
                "status": "COMPLETED",
                "failure_signal_date": failure_signal_date,
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": float(row.coord_open),
                "exit_reason": "NEXT_OPEN_AFTER_CLOSE_BELOW_L",
                "holding_sessions": int(row.cal_idx) - entry_idx,
                "gross_return": gross,
                "net_return": gross - COST,
            }
        if pending_time and parent.sellable_open(row):
            gross = float(row.coord_open) / entry_price - 1.0
            return {
                **decision,
                **entry_payload,
                "status": "COMPLETED",
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": float(row.coord_open),
                "exit_reason": "H60_TIME_STOP",
                "holding_sessions": int(row.cal_idx) - entry_idx,
                "gross_return": gross,
                "net_return": gross - COST,
            }
        if parent.valid_row(row) and float(row.coord_high) >= target:
            gross = target / entry_price - 1.0
            return {
                **decision,
                **entry_payload,
                "status": "COMPLETED",
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": target,
                "exit_reason": "A67_PRE_REJECTION_PEAK",
                "holding_sessions": int(row.cal_idx) - entry_idx,
                "gross_return": gross,
                "net_return": gross - COST,
            }
        if (
            rules["failure_exit"]
            and not pending_failure
            and parent.valid_row(row)
            and float(row.coord_close) < float(decision["gap_L"])
        ):
            pending_failure = True
            failure_signal_date = pd.Timestamp(row.trade_date)
        if parent.valid_row(row) and int(row.cal_idx) >= entry_idx + HORIZON:
            pending_time = True
    return {**decision, **entry_payload, "status": "INCOMPLETE_BY_2021_END"}


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.loc[frame.status.eq("COMPLETED")].copy()
    qualified = frame.loc[frame.qualified_signal.fillna(False)].copy()
    by_state: dict[str, Any] = {}
    for state, part in complete.groupby("market_regime", dropna=False, sort=True):
        by_state[str(state)] = {
            "completed": len(part),
            "mean_net": float(part.net_return.mean()),
            "median_net": float(part.net_return.median()),
            "severe_loss_rate": float(part.net_return.le(-0.10).mean()),
        }
    return {
        "rows": len(frame),
        "qualified_signals": len(qualified),
        "completed": len(complete),
        "decision_dates": int(qualified.decision_date.nunique()) if not qualified.empty else 0,
        "status_counts": {
            str(key): int(value)
            for key, value in frame.status.value_counts(dropna=False).sort_index().items()
        },
        "mean_net": None if complete.empty else float(complete.net_return.mean()),
        "median_net": None if complete.empty else float(complete.net_return.median()),
        "positive_rate": None if complete.empty else float(complete.net_return.gt(0).mean()),
        "ge_4pct_rate": None if complete.empty else float(complete.net_return.ge(0.04).mean()),
        "severe_loss_rate": None if complete.empty else float(complete.net_return.le(-0.10).mean()),
        "mean_holding_sessions": None
        if complete.empty
        else float(complete.holding_sessions.mean()),
        "exit_reason_counts": {
            str(key): int(value)
            for key, value in complete.exit_reason.value_counts().sort_index().items()
        },
        "by_causal_market_state": by_state,
    }


def parent_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.loc[frame.status.eq("COMPLETED")].copy()
    return {
        "rows": len(frame),
        "qualified_signals": len(frame),
        "completed": len(complete),
        "mean_net": float(complete.net_return.mean()),
        "median_net": float(complete.net_return.median()),
        "positive_rate": float(complete.net_return.gt(0).mean()),
        "ge_4pct_rate": float(complete.net_return.ge(0.04).mean()),
        "severe_loss_rate": float(complete.net_return.le(-0.10).mean()),
        "mean_holding_sessions": float(complete.holding_sessions.mean()),
        "status_counts": {
            str(key): int(value)
            for key, value in frame.status.value_counts().sort_index().items()
        },
    }


def yearly_metrics(frame: pd.DataFrame, *, parent_frame: bool = False) -> dict[str, Any]:
    date_column = "signal_date" if parent_frame else "original_signal_date"
    answer: dict[str, Any] = {}
    for year in range(2014, 2021):
        part = frame.loc[pd.to_datetime(frame[date_column]).dt.year.eq(year)].copy()
        if parent_frame:
            value = parent_metrics(part)
        else:
            value = metrics(part)
        answer[str(year)] = value
    return answer


def build_anatomy(variant_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for variant, frame in variant_frames.items():
        for year in range(2014, 2021):
            part = frame.loc[frame.original_signal_date.dt.year.eq(year)]
            m = metrics(part)
            rows.append(
                {
                    "variant": variant,
                    "original_signal_year": year,
                    "qualified_signals": m["qualified_signals"],
                    "completed": m["completed"],
                    "mean_net": m["mean_net"],
                    "median_net": m["median_net"],
                    "positive_rate": m["positive_rate"],
                    "ge_4pct_rate": m["ge_4pct_rate"],
                    "severe_loss_rate": m["severe_loss_rate"],
                    "mean_holding_sessions": m["mean_holding_sessions"],
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    source_hashes = verify_sources()
    candidates, windows, parent_outcomes, regime = load_inputs()
    paths = {
        event_id: part.sort_values("cal_idx", kind="mergesort").reset_index(drop=True)
        for event_id, part in windows.groupby("event_id", sort=False)
    }
    regime_by_date = {
        pd.Timestamp(row.trade_date).normalize(): row
        for row in regime.itertuples(index=False)
    }
    candidate_by_id = {
        str(row.event_id): row for row in candidates.itertuples(index=False)
    }
    if set(candidate_by_id) != set(paths):
        raise ResearchError("candidate and chart-window identities differ")

    frames: dict[str, pd.DataFrame] = {}
    outcome_hashes: dict[str, str] = {}
    for variant, rules in VARIANTS.items():
        rows = [
            replay_one(candidate_by_id[event_id], paths[event_id], regime_by_date, rules)
            for event_id in sorted(candidate_by_id)
        ]
        frame = pd.DataFrame(rows).sort_values(
            ["original_signal_date", "symbol", "event_id"], kind="mergesort"
        ).reset_index(drop=True)
        for column in (
            "original_signal_date",
            "decision_date",
            "decision_at",
            "feature_available_at",
            "entry_date",
            "failure_signal_date",
            "exit_date",
        ):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column])
        if frame.event_id.duplicated().any():
            raise ResearchError(f"{variant}: duplicate output identity")
        if frame.loc[frame.entry_date.notna(), "entry_date"].le(
            frame.loc[frame.entry_date.notna(), "decision_date"]
        ).any():
            raise ResearchError(f"{variant}: same/prior-bar entry")
        failure_rows = frame.loc[frame.failure_signal_date.notna()]
        if failure_rows.exit_date.le(failure_rows.failure_signal_date).any():
            raise ResearchError(f"{variant}: same-bar structural exit")
        if frame.loc[frame.decision_date.notna(), "decision_date"].max() > MAX_DECISION_DATE:
            raise ResearchError(f"{variant}: decision after development freeze")
        output = OUTPUT_ROOT / f"{variant.lower()}_outcomes.parquet"
        write_parquet(frame, output)
        outcome_hashes[variant] = sha256(output)
        frames[variant] = frame

    anatomy = build_anatomy(frames)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    anatomy.to_csv(ANATOMY, index=False)
    summary_rows = []
    baseline = parent_metrics(parent_outcomes)
    summary_rows.append({"variant": "R0_PARENT_BASELINE", **baseline})
    for variant, frame in frames.items():
        summary_rows.append({"variant": variant, **metrics(frame)})
    summary_frame = pd.DataFrame(
        [
            {
                key: value
                for key, value in row.items()
                if not isinstance(value, dict)
            }
            for row in summary_rows
        ]
    )
    summary_frame.to_csv(SUMMARY, index=False)

    annual = {"R0_PARENT_BASELINE": yearly_metrics(parent_outcomes, parent_frame=True)}
    annual.update({name: yearly_metrics(frame) for name, frame in frames.items()})
    final_name = "R4_FINAL_ALL_FIVE_RULES"
    final_frame = frames[final_name]
    final_metrics = metrics(final_frame)
    annual_qualified = {
        year: int(values["qualified_signals"])
        for year, values in annual[final_name].items()
    }
    gate = {
        "qualified_signals_each_2014_2020_year_gt_50": bool(
            min(annual_qualified.values()) > 50
        ),
        "pooled_completed_mean_net_gt_4pct": bool(
            final_metrics["mean_net"] is not None and final_metrics["mean_net"] > 0.04
        ),
        "pooled_completed_median_net_positive": bool(
            final_metrics["median_net"] is not None and final_metrics["median_net"] > 0
        ),
        "same_or_prior_bar_entry_count": int(
            final_frame.loc[final_frame.entry_date.notna(), "entry_date"].le(
                final_frame.loc[final_frame.entry_date.notna(), "decision_date"]
            ).sum()
        ),
        "same_bar_structural_exit_count": int(
            final_frame.loc[final_frame.failure_signal_date.notna(), "exit_date"].le(
                final_frame.loc[final_frame.failure_signal_date.notna(), "failure_signal_date"]
            ).sum()
        ),
        "max_decision_date": str(final_frame.decision_date.max().date()),
        "2022_2024_unlocked": False,
    }
    gate["passed"] = bool(
        gate["qualified_signals_each_2014_2020_year_gt_50"]
        and gate["pooled_completed_mean_net_gt_4pct"]
        and gate["pooled_completed_median_net_positive"]
        and gate["same_or_prior_bar_entry_count"] == 0
        and gate["same_bar_structural_exit_count"] == 0
    )
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "POST_HOC_CHART_RULE_DEVELOPMENT_REPLAY_COMPLETE",
        "source_hashes": source_hashes,
        "chart_reviewed_completed_trade_count": 3041,
        "fixed_variants": {"R0_PARENT_BASELINE": baseline},
        "annual": annual,
        "final_gate": gate,
        "output_hashes": outcome_hashes,
        "summary_sha256": sha256(SUMMARY),
        "anatomy_sha256": sha256(ANATOMY),
        "post_2021_bar_read": False,
        "2022_2024_outcome_read": False,
        "2025_plus_outcome_read": False,
    }
    for variant, frame in frames.items():
        result["fixed_variants"][variant] = metrics(frame)
    write_json(RESULT, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
