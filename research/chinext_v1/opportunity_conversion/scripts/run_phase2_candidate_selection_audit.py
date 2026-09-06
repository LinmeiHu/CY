#!/usr/bin/env python3
"""Fixed-horizon oracle audit of selection inside the authoritative candidate pool."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/opportunity_conversion"
PRIOR = ROOT / "research/chinext_v1/regime_attribution"
PRIOR_SCRIPT = PRIOR / "scripts/run_phase1_yearly_decomposition.py"
STATS_SCRIPT = WORK / "scripts/run_phase2_4_attribution.py"
FEATURES = PRIOR / "artifacts/daily_regime_features.parquet"
SPEC = WORK / "experiments/phase2_candidate_selection_spec.json"
OUTPUT_CSV = WORK / "artifacts/candidate_fixed_horizon_outcomes.csv"
OUTPUT_DAY_CSV = WORK / "artifacts/candidate_day_selection_audit.csv"
OUTPUT_JSON = WORK / "artifacts/phase2_candidate_selection_audit.json"
REPORT = WORK / "reports/phase2_candidate_selection_audit.md"
DAILY_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")

BLOCKS = {
    "EXTENDED_2018_2021": ROOT
    / "research/chinext_v1/output/chinext_v1_extended_2018_2021",
    "HOLDOUT_O0_2022_2023": ROOT
    / "research/chinext_v1/output/chinext_v1_phase9b_oos/O0_BASELINE",
    "DEVELOPMENT_2024_2025": ROOT
    / "research/chinext_v1/output/chinext_v1_pit_replay",
}


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def candidate_row(block: str, event: dict[str, Any], selected: bool) -> dict[str, Any]:
    rs = event["rs"]
    full = event["full40"]
    minimum = event["minvol"]
    breakout = event["breakout_volume"]
    return {
        "baseline_block": block,
        "signal_date": str(event["signal_date"]),
        "entry_year": int(str(event["signal_date"])[:4]),
        "symbol": str(event["symbol"]),
        "authoritative_selected": selected,
        "entry_rs_score": rs["score"],
        "entry_mom20": rs["mom20"],
        "entry_mom60": rs["mom60"],
        "entry_mom120": rs["mom120"],
        "entry_box_width": full["box_width"],
        "entry_vol_ratio": full["vol_ratio"],
        "entry_minvol_location": minimum["location"],
        "entry_minimum_volume_ratio": minimum["minimum_volume_ratio"],
        "entry_breakout_volume_ratio": breakout["ratio"],
    }


def load_candidates() -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    audit: dict[str, Any] = {}
    for block, directory in BLOCKS.items():
        selected = {
            (str(row["symbol"]), str(row["signal_date"]))
            for row in read_jsonl(directory / "execution_ledger.jsonl")
            if row.get("status") == "FILLED"
            and row.get("side") == "BUY"
            and row.get("new_position") is True
        }
        events = [
            row
            for row in read_jsonl(directory / "event_ledger.jsonl")
            if row.get("event") == "ENTRY_SIGNAL_EVALUATED"
            and (row.get("minvol") or {}).get("passed") is True
            and (row.get("rs") or {}).get("score") is not None
        ]
        event_keys = {(str(row["symbol"]), str(row["signal_date"])) for row in events}
        if not selected.issubset(event_keys):
            raise RuntimeError(f"selected entries absent from final candidate pool: {block}")
        if len(event_keys) != len(events):
            raise RuntimeError(f"duplicate final candidate event: {block}")
        rows.extend(
            candidate_row(
                block,
                event,
                (str(event["symbol"]), str(event["signal_date"])) in selected,
            )
            for event in events
        )
        audit[block] = {
            "candidate_count": len(events),
            "selected_count": len(selected),
            "candidate_days": len({str(row["signal_date"]) for row in events}),
        }
    frame = pd.DataFrame(rows)
    if len(frame) != 1821 or int(frame["authoritative_selected"].sum()) != 409:
        raise RuntimeError("candidate/selection counts do not reconcile to 1,821/409")
    return frame, audit


def load_sessions_prices(
    prior: Any, symbols: list[str]
) -> tuple[list[str], dict[tuple[str, str], dict[str, Any]]]:
    connection = duckdb.connect()
    session_rows = connection.execute(
        """
        SELECT CAST(trade_date AS DATE)
        FROM read_parquet(?)
        WHERE trade_date BETWEEN DATE '2018-01-01' AND DATE '2026-12-31'
        ORDER BY trade_date
        """,
        [str(prior.CALENDAR)],
    ).fetchall()
    paths = [
        str(DAILY_ROOT / f"partition_year={year}" / "data_0.parquet")
        for year in range(2018, 2027)
    ]
    rows = connection.execute(
        """
        SELECT CAST(trade_date AS DATE),symbol,open,high,close,
               buy_blocked_open,current_day_data_tradable,hard_valid,
               corporate_action_count,corporate_action_available_date,
               corporate_action_blocking,corporate_action_valid,
               share_multiplier,cash_per_share,rights_ratio,
               available_at,snapshot_id
        FROM read_parquet(?,union_by_name=true)
        WHERE symbol IN (SELECT * FROM unnest(?))
          AND trade_date BETWEEN DATE '2018-01-01' AND DATE '2026-12-31'
        ORDER BY symbol,trade_date
        """,
        [paths, symbols],
    ).fetchall()
    connection.close()
    prices: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row[1]), row[0].isoformat())
        if key in prices:
            raise RuntimeError(f"duplicate candidate outcome row: {key}")
        prices[key] = {
            "open": row[2],
            "high": row[3],
            "close": row[4],
            "buy_blocked_open": row[5],
            "current_day_data_tradable": row[6],
            "hard_valid": row[7],
            "corporate_action_count": row[8],
            "corporate_action_available_date": row[9],
            "corporate_action_blocking": row[10],
            "corporate_action_valid": row[11],
            "share_multiplier": row[12],
            "cash_per_share": row[13],
            "rights_ratio": row[14],
            "available_at": row[15],
            "snapshot_id": row[16],
        }
    return [row[0].isoformat() for row in session_rows], prices


def fixed_horizon_outcome(
    prior: Any,
    row: dict[str, Any],
    sessions: list[str],
    session_index: dict[str, int],
    prices: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    signal_index = session_index[row["signal_date"]]
    future = sessions[signal_index + 1 : signal_index + 21]
    result: dict[str, Any] = {
        "hypothetical_entry_date": future[0] if future else None,
        "entry_executable": False,
        "coverage_5": False,
        "coverage_10": False,
        "coverage_20": False,
        "failure_reason": None,
    }
    if len(future) < 20:
        result["failure_reason"] = "CALENDAR_END_BEFORE_20"
        return result
    entry_row = prices.get((row["symbol"], future[0]))
    if entry_row is None:
        result["failure_reason"] = "MISSING_ENTRY_ROW"
        return result
    entry_open = entry_row.get("open")
    if not (
        entry_row.get("hard_valid") is True
        and entry_row.get("current_day_data_tradable") is True
        and entry_row.get("buy_blocked_open") is False
        and entry_open is not None
        and math.isfinite(float(entry_open))
        and float(entry_open) > 0
    ):
        result["failure_reason"] = "NEXT_OPEN_NOT_EXECUTABLE"
        return result
    result["entry_executable"] = True
    result["hypothetical_entry_price"] = float(entry_open)
    share_factor = 1.0
    cash_per_entry_share = 0.0
    highs: list[float] = []
    closes: list[float] = []
    for offset, day in enumerate(future):
        daily = prices.get((row["symbol"], day))
        if daily is None:
            result["failure_reason"] = f"MISSING_PATH_ROW_AT_{offset + 1}"
            break
        if daily.get("hard_valid") is not True:
            result["failure_reason"] = f"HARD_VALID_FALSE_AT_{offset + 1}"
            break
        if offset > 0 and int(daily.get("corporate_action_count") or 0) > 0:
            valid, multiplier, cash = prior.action_values(daily, day)
            if not valid:
                result["failure_reason"] = f"CORPORATE_ACTION_INVALID_AT_{offset + 1}"
                break
            cash_per_entry_share += share_factor * cash
            share_factor *= multiplier
        if not all(
            value is not None and math.isfinite(float(value))
            for value in (daily["high"], daily["close"])
        ):
            result["failure_reason"] = f"NONFINITE_PATH_AT_{offset + 1}"
            break

        def total_return(price: float) -> float:
            return (
                (share_factor * price + cash_per_entry_share) / float(entry_open)
                - 1.0
            )

        highs.append(total_return(float(daily["high"])))
        closes.append(total_return(float(daily["close"])))
        horizon = offset + 1
        if horizon in (5, 10, 20):
            result[f"coverage_{horizon}"] = True
            result[f"mfe_{horizon}"] = max(highs)
            result[f"close_return_{horizon}"] = closes[-1]
    if len(closes) == 20:
        result["failure_reason"] = None
        result["opportunity20_fixed20"] = result["mfe_20"] >= 0.20
        result["opportunity50_fixed20"] = result["mfe_20"] >= 0.50
        result["terminal20_ge20"] = result["close_return_20"] >= 0.20
    return result


def summarize_group(group: pd.DataFrame) -> dict[str, Any]:
    covered = group.loc[group["coverage_20"].eq(True)]
    return {
        "candidate_count": int(len(group)),
        "covered20_count": int(len(covered)),
        "median_mfe20": float(covered["mfe_20"].median()) if len(covered) else None,
        "mean_mfe20": float(covered["mfe_20"].mean()) if len(covered) else None,
        "opportunity20_rate": float(covered["opportunity20_fixed20"].mean()) if len(covered) else None,
        "opportunity50_rate": float(covered["opportunity50_fixed20"].mean()) if len(covered) else None,
        "median_close20": float(covered["close_return_20"].median()) if len(covered) else None,
        "terminal20_ge20_rate": float(covered["terminal20_ge20"].mean()) if len(covered) else None,
    }


def main() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("frozen_before_execution") is not True:
        raise RuntimeError("candidate selection spec is not frozen")
    prior = load_module(PRIOR_SCRIPT, "candidate_prior")
    stats = load_module(STATS_SCRIPT, "candidate_stats")
    prior.validate_inputs()
    candidates, audit = load_candidates()
    sessions, prices = load_sessions_prices(prior, sorted(candidates["symbol"].unique()))
    session_index = {day: index for index, day in enumerate(sessions)}
    outcomes = [
        fixed_horizon_outcome(
            prior,
            row,
            sessions,
            session_index,
            prices,
        )
        for row in candidates.to_dict(orient="records")
    ]
    outcome_frame = pd.DataFrame(outcomes)
    candidate_outcomes = pd.concat(
        [candidates.reset_index(drop=True), outcome_frame], axis=1
    )
    connection = duckdb.connect()
    feature_context = connection.execute(
        """
        SELECT baseline_block,CAST(trade_date AS VARCHAR) AS signal_date,
               breadth_above_ma20
        FROM read_parquet(?)
        """,
        [str(FEATURES)],
    ).fetchdf()
    connection.close()
    candidate_outcomes = candidate_outcomes.merge(
        feature_context,
        on=["baseline_block", "signal_date"],
        how="left",
        validate="many_to_one",
    )
    if len(candidate_outcomes) != 1821:
        raise RuntimeError("candidate outcome join changed population")
    atomic_csv(OUTPUT_CSV, candidate_outcomes)

    covered = candidate_outcomes.loc[candidate_outcomes["coverage_20"].eq(True)].copy()
    selected = covered.loc[covered["authoritative_selected"].eq(True)]
    unselected = covered.loc[~covered["authoritative_selected"].eq(True)]
    group_summary = {
        "all_candidates": summarize_group(candidate_outcomes),
        "selected": summarize_group(
            candidate_outcomes.loc[candidate_outcomes["authoritative_selected"].eq(True)]
        ),
        "unselected": summarize_group(
            candidate_outcomes.loc[~candidate_outcomes["authoritative_selected"].eq(True)]
        ),
    }

    day_rows: list[dict[str, Any]] = []
    for (block, day), group in covered.groupby(["baseline_block", "signal_date"]):
        chosen = group.loc[group["authoritative_selected"].eq(True)]
        not_chosen = group.loc[~group["authoritative_selected"].eq(True)]
        if chosen.empty:
            continue
        ranked = group.sort_values(["mfe_20", "entry_rs_score"], ascending=[False, False])
        top3_keys = set(zip(ranked.head(3)["symbol"], ranked.head(3)["signal_date"]))
        chosen_keys = set(zip(chosen["symbol"], chosen["signal_date"]))
        best_all = float(group["mfe_20"].max())
        best_selected = float(chosen["mfe_20"].max())
        day_rows.append(
            {
                "baseline_block": block,
                "signal_date": day,
                "entry_year": int(day[:4]),
                "breadth_above_ma20": group["breadth_above_ma20"].iloc[0],
                "candidate_count": int(len(group)),
                "selected_count": int(len(chosen)),
                "unselected_count": int(len(not_chosen)),
                "candidate_mean_mfe20": float(group["mfe_20"].mean()),
                "candidate_median_mfe20": float(group["mfe_20"].median()),
                "candidate_std_mfe20": float(group["mfe_20"].std(ddof=0)),
                "candidate_best_mfe20": best_all,
                "candidate_opportunity20_rate": float(group["opportunity20_fixed20"].mean()),
                "selected_mean_mfe20": float(chosen["mfe_20"].mean()),
                "selected_opportunity20_rate": float(chosen["opportunity20_fixed20"].mean()),
                "unselected_mean_mfe20": float(not_chosen["mfe_20"].mean()) if len(not_chosen) else None,
                "unselected_opportunity20_rate": float(not_chosen["opportunity20_fixed20"].mean()) if len(not_chosen) else None,
                "best_selected_mfe20": best_selected,
                "best_candidate_regret_mfe20": best_all - best_selected,
                "selected_captured_best_candidate": math.isclose(best_all, best_selected, rel_tol=0, abs_tol=1e-15),
                "selected_captured_any_top3": bool(chosen_keys & top3_keys),
            }
        )
    day_audit = pd.DataFrame(day_rows)
    atomic_csv(OUTPUT_DAY_CSV, day_audit)

    comparable = covered.groupby(["baseline_block", "signal_date"]).filter(
        lambda group: group["authoritative_selected"].any()
        and (~group["authoritative_selected"]).any()
    ).copy()
    comparable["day_mean_mfe20"] = comparable.groupby(
        ["baseline_block", "signal_date"]
    )["mfe_20"].transform("mean")
    comparable["day_centered_mfe20"] = (
        comparable["mfe_20"] - comparable["day_mean_mfe20"]
    )
    within_day = {
        "candidate_rows": int(len(comparable)),
        "candidate_days": int(
            comparable[["baseline_block", "signal_date"]].drop_duplicates().shape[0]
        ),
        "selected_rows": int(comparable["authoritative_selected"].sum()),
        "selected_mean_day_centered_mfe20": float(
            comparable.loc[
                comparable["authoritative_selected"].eq(True), "day_centered_mfe20"
            ].mean()
        ),
        "unselected_mean_day_centered_mfe20": float(
            comparable.loc[
                ~comparable["authoritative_selected"].eq(True), "day_centered_mfe20"
            ].mean()
        ),
    }

    rs_primary = stats.partial_spearman(
        covered,
        "entry_rs_score",
        "mfe_20",
        year_control=True,
        continuous_controls=["breadth_above_ma20"],
    )
    rs_stability = stats.yearly_and_loyo(
        covered,
        "entry_rs_score",
        "mfe_20",
        continuous_controls=["breadth_above_ma20"],
    )
    rs_relation = {**rs_primary, **rs_stability}

    day_quality_relations: dict[str, Any] = {}
    for outcome in (
        "candidate_mean_mfe20",
        "candidate_best_mfe20",
        "candidate_std_mfe20",
        "candidate_opportunity20_rate",
    ):
        primary = stats.partial_spearman(
            day_audit,
            "candidate_count",
            outcome,
            year_control=True,
            continuous_controls=["breadth_above_ma20"],
        )
        stability = stats.yearly_and_loyo(
            day_audit,
            "candidate_count",
            outcome,
            continuous_controls=["breadth_above_ma20"],
        )
        day_quality_relations[outcome] = {**primary, **stability}

    yearly = {
        str(year): {
            "selected": summarize_group(group.loc[group["authoritative_selected"].eq(True)]),
            "unselected": summarize_group(group.loc[~group["authoritative_selected"].eq(True)]),
            "selection_days": int(
                day_audit.loc[day_audit["entry_year"].eq(year)].shape[0]
            ),
            "best_candidate_capture_rate": float(
                day_audit.loc[
                    day_audit["entry_year"].eq(year), "selected_captured_best_candidate"
                ].mean()
            ),
            "median_best_candidate_regret": float(
                day_audit.loc[
                    day_audit["entry_year"].eq(year), "best_candidate_regret_mfe20"
                ].median()
            ),
        }
        for year, group in covered.groupby("entry_year")
    }
    competitive_days = day_audit.loc[day_audit["unselected_count"] > 0]
    selection_day_summary = {
        "selection_day_count": int(len(day_audit)),
        "days_with_unselected_candidates": int((day_audit["unselected_count"] > 0).sum()),
        "all_selection_days_best_candidate_capture_rate": float(day_audit["selected_captured_best_candidate"].mean()),
        "competitive_days_best_candidate_capture_rate": float(competitive_days["selected_captured_best_candidate"].mean()),
        "competitive_days_any_top3_capture_rate": float(competitive_days["selected_captured_any_top3"].mean()),
        "competitive_days_median_best_candidate_regret_mfe20": float(competitive_days["best_candidate_regret_mfe20"].median()),
        "competitive_days_mean_best_candidate_regret_mfe20": float(competitive_days["best_candidate_regret_mfe20"].mean()),
        "yearly": yearly,
    }
    failure_counts = candidate_outcomes["failure_reason"].fillna("NONE").value_counts().to_dict()
    payload = {
        "experiment_id": "OC-EXP-P2-002",
        "status": "PASS",
        "strategy_modified": False,
        "formal_replays": 0,
        "spec_sha256": sha256_file(SPEC),
        "lineage_audit": audit,
        "candidate_count": int(len(candidate_outcomes)),
        "selected_count": int(candidate_outcomes["authoritative_selected"].sum()),
        "coverage": {
            horizon: int(candidate_outcomes[f"coverage_{horizon}"].sum())
            for horizon in (5, 10, 20)
        },
        "failure_counts": failure_counts,
        "group_summary": group_summary,
        "within_day_comparison": within_day,
        "selection_day_oracle": selection_day_summary,
        "rs_mfe20_relation": rs_relation,
        "candidate_count_quality_relations": day_quality_relations,
        "oracle_warning": spec["oracle_warning"],
        "source_hashes": {
            "spec": sha256_file(SPEC),
            "features": sha256_file(FEATURES),
            "output_candidate_csv": sha256_file(OUTPUT_CSV),
            "output_day_csv": sha256_file(OUTPUT_DAY_CSV),
        },
    }
    atomic_write(OUTPUT_JSON, json.dumps(payload, indent=2, sort_keys=True) + "\n")

    lines = [
        "# Phase 2B — Candidate-Pool Selection Audit",
        "",
        "OC-EXP-P2-002: **PASS**. This is a fixed-horizon oracle diagnostic, not a replacement-entry replay or NAV.",
        "",
        "## Lineage and coverage",
        "",
        "| Block | Final candidates | Selected entries | Candidate days |",
        "|---|---:|---:|---:|",
    ]
    for block, row in audit.items():
        lines.append(
            f"| {block} | {row['candidate_count']} | {row['selected_count']} | {row['candidate_days']} |"
        )
    lines += [
        "",
        f"Fixed-horizon coverage: {payload['coverage'][5]}/1,821 at 5 sessions, {payload['coverage'][10]}/1,821 at 10, and {payload['coverage'][20]}/1,821 at 20.",
        "",
        "## Selected versus unselected",
        "",
        "| Group | N | Covered20 | Median MFE20 | Opp20 | Opp50 | Median close20 | Close20 >=20% |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("selected", "unselected"):
        row = group_summary[name]
        lines.append(
            f"| {name} | {row['candidate_count']} | {row['covered20_count']} | {row['median_mfe20']:.2%} | {row['opportunity20_rate']:.2%} | {row['opportunity50_rate']:.2%} | {row['median_close20']:.2%} | {row['terminal20_ge20_rate']:.2%} |"
        )
    lines += [
        "",
        "## Same-day ranking ceiling",
        "",
        f"Across `{selection_day_summary['selection_day_count']}` selection days, only `{selection_day_summary['days_with_unselected_candidates']}` contain an executable, covered alternative candidate. On those competitive days, authoritative selection includes the ex-post best-MFE20 candidate on `{selection_day_summary['competitive_days_best_candidate_capture_rate']:.2%}` of days and at least one ex-post top-3 candidate on `{selection_day_summary['competitive_days_any_top3_capture_rate']:.2%}`. Median best-candidate MFE20 regret is `{selection_day_summary['competitive_days_median_best_candidate_regret_mfe20']:.2%}`. The all-day best-capture rate is `{selection_day_summary['all_selection_days_best_candidate_capture_rate']:.2%}` but is mechanically inflated by 229 days with no alternative.",
        "",
        f"Within days containing both selected and unselected candidates, selected observations have mean day-centered MFE20 `{within_day['selected_mean_day_centered_mfe20']:.2%}` versus `{within_day['unselected_mean_day_centered_mfe20']:.2%}` for unselected observations.",
        "",
        f"Frozen RS score versus candidate MFE20 has breadth/year-controlled rho `{rs_relation['rho']:.3f}`, yearly signs `{rs_relation['yearly_positive']}+/{rs_relation['yearly_negative']}-`, and LOYO `{rs_relation['loyo_positive']}+/{rs_relation['loyo_negative']}-`.",
        "",
        "Unselected outcomes assume a next-session executable open and a fixed 20-session hold. Best-candidate capture/regret uses hindsight and ignores capacity, portfolio feedback, and authoritative exit logic; it cannot authorize a stock-selection rule.",
    ]
    atomic_write(REPORT, "\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
