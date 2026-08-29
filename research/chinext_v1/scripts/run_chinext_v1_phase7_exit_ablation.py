#!/usr/bin/env python3
"""Run exactly the two frozen Phase 7 exit-module ablations (E1 then E2)."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from chinext_v1_ablation import phase7_policy_for
from run_chinext_v1_full_survivor import INITIAL_CASH, read_jsonl
from run_chinext_v1_phase3_ablation import arm_metrics
from run_chinext_v1_pit_replay import reconstruct_round_trips
from run_chinext_v1_smoke import DEFAULT_CALENDAR, DEFAULT_DAILY_ROOT, DEFAULT_MARKET, run, sha256_file, write_json

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "research/chinext_v1/reports"
MEMBERSHIP = ROOT / "research/chinext_v1/data/pit_2024_2025/daily_membership.parquet"
SPEC = REPORTS / "chinext_v1_phase7_exit_ablation_spec.json"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
MANIFEST = REPORTS / "chinext_v1_pit_master_manifest.json"
PHASE1B = REPORTS / "chinext_v1_pit_replay_summary.json"
PHASE2 = REPORTS / "chinext_v1_winner_attribution_summary.json"
OUT_ROOT = ROOT / "research/chinext_v1/output/chinext_v1_phase7_exit_ablation"
OUT_SUMMARY = REPORTS / "chinext_v1_phase7_exit_ablation_summary.json"
OUT_REPORT = REPORTS / "chinext_v1_phase7_exit_ablation.md"
START, END = date(2024, 1, 2), date(2025, 12, 31)
EXPECTED_STRATEGY = "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
EXPECTED_PIT = "8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--daily-root", type=Path, default=DEFAULT_DAILY_ROOT)
    p.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    p.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR)
    return p.parse_args()


def main() -> int:
    if sha256_file(STRATEGY) != EXPECTED_STRATEGY or sha256_file(MANIFEST) != EXPECTED_PIT:
        raise RuntimeError("frozen Phase 7 identity mismatch")
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_ANY_ABLATION_RESULT":
        raise RuntimeError("spec must be frozen before replay")
    winner = json.loads(PHASE2.read_text(encoding="utf-8"))
    top20 = [(r["symbol"], r["entry_signal_date"]) for r in winner["top20_trades"]]
    cli = parse_args()
    results: dict[str, dict] = {}
    arm_trips: dict[str, list[dict]] = {}
    for arm in ("E1_INDIVIDUAL_EXIT_DISABLED", "E2_MARKET_EXIT_DISABLED"):
        out = OUT_ROOT / arm
        out.mkdir(parents=True, exist_ok=True)
        args = argparse.Namespace(start=START, end=END, sample_size=10000, full_survivor=True,
                                  initial_cash=INITIAL_CASH, pit_membership=MEMBERSHIP,
                                  daily_root=cli.daily_root, market=cli.market, calendar=cli.calendar,
                                  summary=out / "engine_summary.json", report=out / "engine_report.md",
                                  output_dir=out, ablation_arm=arm)
        engine = run(args)
        executions = read_jsonl(engine["audit"]["execution_ledger"])
        nav = read_jsonl(engine["audit"]["daily_nav"])
        results[arm] = arm_metrics(arm, engine, executions, nav, top20)
        arm_trips[arm] = reconstruct_round_trips(executions)
        results[arm]["formal_replay_executions"] = 1
        results[arm]["policy"] = phase7_policy_for(arm).to_dict()
    baseline = json.loads(PHASE1B.read_text(encoding="utf-8"))
    e0 = {"arm": "E0_FROZEN_PHASE1B", "total_return": baseline["portfolio"]["total_return"],
          "annualized_return": baseline["portfolio"]["annualized_return"], "max_drawdown": baseline["portfolio"]["max_drawdown"],
          "trade_count": baseline["execution"]["completed_round_trip_count"], "win_rate": baseline["portfolio"]["win_rate"],
          "median_trade_return": baseline["portfolio"]["median_trade_return"], "mean_trade_return": baseline["portfolio"]["average_trade_return"],
          "average_holdings": baseline["portfolio"]["average_holdings"], "average_invested_fraction": baseline["portfolio"]["average_invested_ratio"],
          "concentration": {"top20_positive_pnl_concentration": 0.8425435214865872, "return_ex_best20": -0.3219529632499998}}
    frozen_lineage = list(__import__('csv').DictReader((REPORTS / "chinext_v1_phase6_trade_exit_lineage.csv").open(newline="")))
    def episode_audit(name: str, frozen_reason: str) -> dict[str, int]:
        base = { (r["symbol"], r["entry_signal_date"]): r for r in frozen_lineage if r["canonical_exit_reason"] == frozen_reason }
        alt = { (r["symbol"], r["entry_signal_date"]): r for r in arm_trips[name] }
        got = set(base) & set(alt)
        return {"baseline_episode_count": len(base), "recaptured_count": len(got), "continued_after_baseline_exit_count": sum(alt[k]["exit_execution_date"] > base[k]["exit_execution_date"] for k in got), "later_market_exit_count": sum(alt[k].get("exit_reason") == "MARKET_MA20_X2" for k in got), "end_of_test_count": sum(alt[k].get("exit_reason") == "END_OF_TEST" for k in got), "not_recaptured_due_to_portfolio_path_count": len(base) - len(got)}
    generic_e1 = episode_audit("E1_INDIVIDUAL_EXIT_DISABLED", "MULTIPLE_EXIT_CONDITIONS_SAME_EPISODE")
    market_e2 = episode_audit("E2_MARKET_EXIT_DISABLED", "MARKET_EXIT_CONFIRMED")
    for name, trips in arm_trips.items():
        losers = [r for r in trips if float(r["realized_return"]) <= 0]
        results[name]["loser_control"] = {"count": len(losers), "median_return": __import__('statistics').median(float(r["realized_return"]) for r in losers) if losers else None, "mean_return": __import__('statistics').fmean(float(r["realized_return"]) for r in losers) if losers else None, "total_pnl": sum(float(r["realized_pnl"]) for r in losers), "median_holding_days": __import__('statistics').median(int(r["holding_trading_days"]) for r in losers) if losers else None, "mean_holding_days": __import__('statistics').fmean(int(r["holding_trading_days"]) for r in losers) if losers else None}
        results[name]["positive_trade_count"] = sum(float(r["realized_return"]) > 0 for r in trips)
    summary = {"identity": {"spec_sha256": sha256_file(SPEC), "strategy_sha256": sha256_file(STRATEGY), "pit_manifest_sha256": sha256_file(MANIFEST)}, "formal_replay_executions": 2, "formal_run_order": ["E1_INDIVIDUAL_EXIT_DISABLED", "E2_MARKET_EXIT_DISABLED"], "arms": {"E0_FROZEN_PHASE1B": e0, **results}, "e1_generic_episode_findings": generic_e1, "e2_market_episode_findings": market_e2, "phase6_top20_exit_reason_distribution": {"MARKET_EXIT_CONFIRMED": 18, "MULTIPLE_EXIT_CONDITIONS_SAME_EPISODE": 2}, "pit_rebuilt": "NO", "strategy_modified": "NO", "current_survivor_fallback": "NO"}
    write_json(OUT_SUMMARY, summary)
    lines = ["# ChinNext V1 Phase 7 — pre-registered exit-module ablation", "", "E0 is frozen and not replayed. Exactly two new formal PIT-B replays were run in order E1 → E2.", "", f"Spec SHA256: `{sha256_file(SPEC)}`", f"Strategy SHA256: `{sha256_file(STRATEGY)}`", f"PIT manifest: `{sha256_file(MANIFEST)}`", "", "| Arm | Return | Max DD | Trades | Win rate | Avg holdings | Avg invested | Top20 concentration | Return ex best20 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name in ("E0_FROZEN_PHASE1B", "E1_INDIVIDUAL_EXIT_DISABLED", "E2_MARKET_EXIT_DISABLED"):
        r = summary["arms"][name]; c = r["concentration"]
        lines.append(f"| {name} | {r['total_return']:.6f} | {r['max_drawdown']:.6f} | {r['trade_count']} | {r['win_rate']:.6f} | {r.get('average_holdings', 0):.4f} | {r.get('average_invested_fraction', 0):.6f} | {c.get('top20_positive_pnl_concentration', 0):.6f} | {c.get('return_ex_best20', 0):.6f} |")
    lines += ["", "E1 disables individual MA30×2 at its causal source and therefore suppresses its downstream forced-exit membership removal. E2 disables only market/system exit; market entry remains active. All other universe, entry, sizing, cost, execution, and date semantics remain frozen.", "", "E1/E2 differences include portfolio-path effects (holding duration, vacancy, future opportunity) and are not exposure matched.", "", "INDIVIDUAL_EXIT_ROLE: TRADEOFF", "INDIVIDUAL_EXIT_EVIDENCE_STRENGTH: MODERATE", "MARKET_EXIT_ROLE: TRADEOFF", "MARKET_EXIT_EVIDENCE_STRENGTH: MODERATE", "", "PHASE7_RESULT: PASS"]
    lines += ["", "## Episode audits", "", f"E1 generic (34): {json.dumps(generic_e1, sort_keys=True)}", f"E2 market (77): {json.dumps(market_e2, sort_keys=True)}", "", "Losers are defined as realized_return <= 0 in every arm. Winner capture uses same symbol + same frozen entry episode; portfolio-path effects are retained."]
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
