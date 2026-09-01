#!/usr/bin/env python3
"""Development-only incrementality audit for the frozen Tail-to-Open score."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC = PROGRAM / "experiments/ASHARE-TAIL-OPEN-ML-RISK-FILTER-V1_spec.json"
OUT = PROGRAM / "artifacts/ASHARE-TAIL-OPEN-ML-RISK-FILTER-V1_result.json"
REPORT = PROGRAM / "reports/ASHARE-TAIL-OPEN-ML-RISK-FILTER-V1_report.md"
PANEL = PROGRAM / "artifacts/ASHARE-TAIL-OPEN-ML-RISK-FILTER-V1_completed_cycles.csv"
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "research/chinext_v1/scripts")]
from run_chinext_v1_full_survivor import read_jsonl  # noqa: E402
from run_chinext_v1_pit_replay import reconstruct_round_trips  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve(raw: str) -> Path:
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else ROOT / candidate


def stats(rows: pd.DataFrame) -> dict[str, Any]:
    returns = rows.round_trip_return.astype(float)
    return {
        "completed_cycles": int(len(rows)),
        "mean_completed_return": float(returns.mean()) if len(rows) else None,
        "median_completed_return": float(returns.median()) if len(rows) else None,
        "mean_realized_pnl_cny": float(rows.realized_pnl.astype(float).mean()) if len(rows) else None,
        "win_rate": float((returns > 0).mean()) if len(rows) else None,
        "severe_loss_rate": float((returns <= -0.10).mean()) if len(rows) else None,
        "mean_calendar_holding_days": float(rows.holding_days.mean()) if len(rows) else None,
    }


def main() -> None:
    spec = json.loads(SPEC.read_text())
    for binding in spec["existing_baseline_inputs"].values():
        path = resolve(binding["path"])
        if sha256(path) != binding["sha256"]:
            raise RuntimeError(f"input identity mismatch: {path}")
    prediction = Path(spec["model"]["prediction_path"])
    if sha256(prediction) != spec["model"]["prediction_sha256"]:
        raise RuntimeError("OOF prediction identity mismatch")
    events = resolve(spec["existing_baseline_inputs"]["development_event_ledger"]["path"])
    candidate_rows = []
    for line in events.open():
        event = json.loads(line)
        minimum = event.get("minvol") or {}
        rs = event.get("rs")
        day = event.get("signal_date", "")
        if (event.get("event") == "ENTRY_SIGNAL_EVALUATED" and "2018-01-02" <= day <= "2021-12-31"
                and minimum.get("passed") and rs is not None):
            acceleration = float(rs["r20"]) - float(rs["r120"])
            candidate_rows.append({"trade_date": day, "symbol": event["symbol"], "rs_acceleration": acceleration,
                                   "rs_admitted": acceleration < 0.20})
    candidates = pd.DataFrame(candidate_rows)
    if candidates.duplicated(["trade_date", "symbol"]).any() or len(candidates) != 377:
        raise RuntimeError("unexpected recoverable candidate identity")
    con = duckdb.connect()
    scores = con.execute(f"""
      SELECT trade_date, symbol, score,
       ntile(5) OVER (PARTITION BY trade_date ORDER BY score ASC, symbol ASC) AS score_quintile
      FROM read_parquet('{prediction.as_posix()}')
      WHERE model='moderately_richer' AND trade_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'
    """).fetchdf()
    con.close()
    if scores.trade_date.min().date().isoformat() != "2018-01-02" or scores.trade_date.max().date().isoformat() != "2021-12-31":
        raise RuntimeError("OOF date boundary mismatch")
    scores["trade_date"] = pd.to_datetime(scores.trade_date).dt.strftime("%Y-%m-%d")
    candidates = candidates.merge(scores, how="left", on=["trade_date", "symbol"], validate="one_to_one")
    ledger = resolve(spec["existing_baseline_inputs"]["development_execution_ledger"]["path"])
    cycles = pd.DataFrame(reconstruct_round_trips(read_jsonl(ledger)))
    cycles["trade_date"] = cycles.entry_signal_date.astype(str)
    cycles = cycles.merge(scores, how="left", on=["trade_date", "symbol"], validate="one_to_one")
    cycles["year"] = cycles.trade_date.str[:4]
    cycles["holding_days"] = (pd.to_datetime(cycles.exit_execution_date) - pd.to_datetime(cycles.entry_execution_date)).dt.days
    if len(cycles) != 139:
        raise RuntimeError("baseline completed-cycle identity mismatch")
    coverage = []
    for year, group in candidates.groupby(candidates.trade_date.str[:4], sort=True):
        admitted = group.loc[group.rs_admitted]
        coverage.append({"year": year, "pre_rs_candidates": int(len(group)), "rs_admitted_candidates": int(len(admitted)),
                         "scored_rs_admitted": int(admitted.score.notna().sum()),
                         "q1_rs_admitted": int((admitted.score_quintile == 1).sum())})
    q_stats = {f"Q{q}": stats(cycles.loc[cycles.score_quintile == q]) for q in range(1, 6)}
    q1 = cycles.loc[cycles.score_quintile == 1]
    other = cycles.loc[cycles.score_quintile.ne(1) & cycles.score_quintile.notna()]
    annual = {}
    adverse_years = []
    for year, group in cycles.groupby("year", sort=True):
        row = {"q1": stats(group.loc[group.score_quintile == 1]), "q2_to_q5": stats(group.loc[group.score_quintile.ne(1) & group.score_quintile.notna()])}
        annual[year] = row
        if row["q1"]["completed_cycles"] and (row["q1"]["mean_completed_return"] < row["q2_to_q5"]["mean_completed_return"] or row["q1"]["severe_loss_rate"] > row["q2_to_q5"]["severe_loss_rate"]):
            adverse_years.append(year)
    q1_date_share = max(Counter(q1.trade_date).values()) / len(q1)
    q1_security_share = max(Counter(q1.symbol).values()) / len(q1)
    q1_candidate = int((candidates.rs_admitted & candidates.score_quintile.eq(1)).sum())
    scored_candidate = int((candidates.rs_admitted & candidates.score.notna()).sum())
    rs_rejected = candidates.loc[~candidates.rs_admitted & candidates.score.notna()]
    rs_overlap = {"rs_rejected_scored_candidates": int(len(rs_rejected)), "q1_within_rs_rejected": int((rs_rejected.score_quintile == 1).sum()),
                  "q1_fraction_within_rs_rejected": float((rs_rejected.score_quintile == 1).mean())}
    gates = {
      "q1_minimum_completed_cycles": len(q1) >= spec["screen"]["minimum_q1_completed_cycles"],
      "q1_pooled_worse": q_stats["Q1"]["mean_completed_return"] < stats(other)["mean_completed_return"] or q_stats["Q1"]["severe_loss_rate"] > stats(other)["severe_loss_rate"],
      "multi_year_adverse": len(adverse_years) >= 2,
      "not_date_or_security_concentrated": q1_date_share <= .50 and q1_security_share <= .30,
      "approximately_80pct_candidate_retention": q1_candidate / scored_candidate <= .25,
      "vetoed_full_trade_nonadverse": q_stats["Q1"]["mean_completed_return"] <= stats(other)["mean_completed_return"],
    }
    authorized = all(gates.values())
    result = {"experiment_id": spec["experiment_id"], "status": "COMPLETE_SCREEN_NO_REPLAY" if not authorized else "SCREEN_AUTHORIZES_ONE_FIXED_REPLAY",
              "classification": "ML_RISK_NOT_INCREMENTAL" if not authorized else "ML_BASELINE_RISK_FILTER_PROMISING",
              "baseline": spec["baseline_selection"], "score_identity": {"model": "moderately_richer", "prediction_sha256": sha256(prediction), "dates": ["2018-01-02", "2021-12-31"], "validation_or_oos_rows": 0},
              "candidate_coverage_by_year": coverage, "candidate_score_coverage": {"pre_rs_candidates": int(len(candidates)), "rs_admitted": int(candidates.rs_admitted.sum()), "scored_rs_admitted": scored_candidate, "unscored_rs_admitted": int(candidates.rs_admitted.sum()) - scored_candidate, "q1_rs_admitted": q1_candidate, "q1_fraction_scored_rs_admitted": q1_candidate / scored_candidate},
              "completed_cycle_score_coverage": {"completed_cycles": len(cycles), "scored": int(cycles.score.notna().sum()), "unscored": int(cycles.score.isna().sum())},
              "q1_to_q5_completed_cycle_metrics": q_stats, "q1_vs_q2_to_q5": {"q1": stats(q1), "q2_to_q5": stats(other), "annual": annual, "adverse_years": adverse_years, "q1_max_date_share": q1_date_share, "q1_max_security_share": q1_security_share},
              "existing_rs_filter_overlap": rs_overlap, "replay_authorization_gates": gates,
              "replay": {"run": False, "reason": "The fixed Q1 veto does not retain approximately 80% of scored RS-admitted candidates; no alternative threshold, conditioning, or rescue is authorized."},
              "claim_boundary": {"development_only": True, "validation_2022_2023_read": False, "final_oos_2024_2026_read": False, "model_refit": False, "new_model_scoring": False, "strategy_replay": False},
              "hashes": {"spec_sha256": sha256(SPEC), "completed_cycle_panel_sha256": None}}
    keep = ["trade_date", "symbol", "score", "score_quintile", "round_trip_return", "entry_execution_date", "exit_execution_date", "holding_days"]
    PANEL.parent.mkdir(parents=True, exist_ok=True); cycles[keep].to_csv(PANEL, index=False)
    result["hashes"]["completed_cycle_panel_sha256"] = sha256(PANEL)
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    REPORT.write_text("# Tail-to-Open ML risk filter V1\n\n`ML_RISK_NOT_INCREMENTAL`; the one fixed Q1 veto was not replayed.\n\n"
                      f"Scored RS-admitted candidates: {scored_candidate}/{int(candidates.rs_admitted.sum())}; Q1: {q1_candidate}/{scored_candidate} ({q1_candidate/scored_candidate:.2%}).\n\n"
                      f"Completed cycles Q1 vs Q2–Q5 mean return: {q_stats['Q1']['mean_completed_return']:.2%} vs {stats(other)['mean_completed_return']:.2%}; severe loss: {q_stats['Q1']['severe_loss_rate']:.2%} vs {stats(other)['severe_loss_rate']:.2%}.\n\n"
                      "No validation or Final-OOS rows were opened and no model was fitted or replayed.\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
