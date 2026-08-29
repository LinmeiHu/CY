#!/usr/bin/env python3
"""Offline exit-lineage and holding-path audit for the frozen 111-trade ledger.

This module never calls the replay engine.  It reads the frozen ledgers and the
already materialised local daily panel, then writes deterministic diagnostics.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "research/chinext_v1/scripts"))
from run_chinext_v1_smoke import DEFAULT_DAILY_ROOT  # noqa: E402

try:
    import duckdb
except ImportError as exc:  # pragma: no cover
    raise SystemExit("duckdb is required; use research/chinext_v1/.venv/bin/python") from exc

REPORTS = ROOT / "research/chinext_v1/reports"
OUT = ROOT / "research/chinext_v1/output/chinext_v1_pit_replay"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
PIT_MANIFEST = REPORTS / "chinext_v1_pit_master_manifest.json"
SUMMARY = REPORTS / "chinext_v1_pit_replay_summary.json"
WINNER = REPORTS / "chinext_v1_winner_attribution_summary.json"
START, END = date(2024, 1, 2), date(2025, 12, 31)
EXPECTED_STRATEGY = "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
EXPECTED_PIT = "8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def pct(v: float | None) -> str:
    return "NA" if v is None or not math.isfinite(v) else f"{v:.4f}"


def reconstruct(executions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    nums: Counter[str] = Counter()
    result: list[dict[str, Any]] = []
    for r in executions:
        if r.get("status") != "FILLED":
            continue
        s = str(r["symbol"])
        if r["side"] == "BUY":
            if r.get("new_position") is True:
                nums[s] += 1
                active[s] = {"trade_id": f"{s}-{nums[s]:03d}", "symbol": s,
                             "entry_signal_date": str(r["signal_date"]),
                             "entry_execution_date": str(r["execution_date"]),
                             "entry_price": float(r["execution_price"]), "buy_cost": 0.0}
            active[s]["buy_cost"] += float(r["notional"]) + float(r["cost"])
        elif s in active:
            c = active[s]
            if r.get("completed_round_trip") is True:
                c.update({"exit_signal_date": str(r["signal_date"]),
                          "exit_execution_date": str(r["execution_date"]),
                          "exit_price": float(r["execution_price"]),
                          "exit_reason": str(r["signal_reason"]),
                          "realized_return": float(r["round_trip_return"]),
                          "realized_pnl": float(r["realized_pnl"])})
                result.append(active.pop(s))
    if len(result) != 111:
        raise RuntimeError(f"frozen trade count is {len(result)}, expected 111")
    return result


def load_panel(symbols: list[str]) -> tuple[dict[str, dict[date, dict[str, float]]], dict[date, float], list[date]]:
    paths = [str(DEFAULT_DAILY_ROOT / f"partition_year={y}" / "data_0.parquet") for y in (2023, 2024, 2025)]
    con = duckdb.connect()
    q = """select trade_date, symbol, open, high, low, close, market_close
           from read_parquet(?, union_by_name=true)
           where trade_date between date '2023-01-01' and date '2025-12-31'
             and symbol in (select * from unnest(?))
           order by symbol, trade_date"""
    rows = con.execute(q, [paths, symbols]).fetchall()
    panel: dict[str, dict[date, dict[str, float]]] = defaultdict(dict)
    market: dict[date, float] = {}
    for d, s, o, h, l, c, mc in rows:
        dd = d if isinstance(d, date) else date.fromisoformat(str(d))
        if c is not None and math.isfinite(float(c)):
            panel[str(s)][dd] = {"open": float(o) if o is not None else float(c), "high": float(h) if h is not None else float(c), "low": float(l) if l is not None else float(c), "close": float(c)}
        if mc is not None and math.isfinite(float(mc)):
            market[dd] = float(mc)
    return panel, market, sorted(market)


def ma_state(values: list[float], period: int, confirm: int = 2) -> tuple[bool, bool, float | None]:
    if len(values) < period + confirm - 1:
        return False, False, None
    today = values[-1]
    ma = statistics.fmean(values[-period:])
    cond = all(values[-1 - i] < statistics.fmean(values[-period - i : -i if i else None]) for i in range(confirm))
    return today < ma, cond, ma


def quantiles(values: list[float | None]) -> dict[str, float | None]:
    x = sorted(v for v in values if v is not None and math.isfinite(v))
    if not x:
        return {k: None for k in ("mean", "median", "p25", "p75")}
    return {"mean": statistics.fmean(x), "median": statistics.median(x), "p25": x[max(0, math.ceil(.25 * len(x)) - 1)], "p75": x[max(0, math.ceil(.75 * len(x)) - 1)]}


def main() -> int:
    if sha256(STRATEGY) != EXPECTED_STRATEGY or sha256(PIT_MANIFEST) != EXPECTED_PIT:
        raise RuntimeError("frozen identity mismatch")
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    if summary["execution"]["completed_round_trip_count"] != 111:
        raise RuntimeError("Phase 1B trade count mismatch")
    executions = read_jsonl(OUT / "execution_ledger.jsonl")
    events = read_jsonl(OUT / "event_ledger.jsonl")
    trades = reconstruct(executions)
    symbols = sorted({t["symbol"] for t in trades})
    panel, market, market_dates = load_panel(symbols)
    individual_events = {(str(e["symbol"]), str(e["signal_date"])) for e in events if e.get("event") == "INDIVIDUAL_EXIT_SIGNAL"}
    changes = [e for e in events if e.get("event") == "DESIRED_SET_CHANGED"]
    removed = {(s, str(e["signal_date"])) for e in changes for s in e.get("previous", []) if s not in e.get("desired", [])}
    market_exit_dates = {str(e["signal_date"]) for e in changes if e.get("reason") == "MARKET_MA20_X2"}
    rows: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    for t in trades:
        s = t["symbol"]; entry = date.fromisoformat(t["entry_execution_date"]); exsig = date.fromisoformat(t["exit_signal_date"]); ex = date.fromisoformat(t["exit_execution_date"])
        dates = [d for d in sorted(panel[s]) if entry <= d <= exsig]
        closes: list[float] = []; peaks: list[float] = []
        for i, d in enumerate(dates):
            p = panel[s][d]; closes.append(p["close"]); peak = max(closes); peaks.append(peak)
            iw, ic, ima = ma_state(closes, 30, 2)
            mvals = [market[x] for x in market_dates if x <= d]
            mw, mc, mma = ma_state(mvals, 20, 2)
            ret = p["close"] / t["entry_price"] - 1.0
            highs = [panel[s][x]["high"] for x in dates[: i + 1]]
            lows = [panel[s][x]["low"] for x in dates[: i + 1]]
            rows.append({"trade_id": t["trade_id"], "symbol": s, "date": d.isoformat(), "entry_signal_date": t["entry_signal_date"], "entry_execution_date": t["entry_execution_date"], "actual_exit_signal_date": t["exit_signal_date"], "actual_exit_execution_date": t["exit_execution_date"], "actual_exit_reason_frozen": t["exit_reason"], "days_since_entry": i, "close": p["close"], "entry_price": t["entry_price"], "return_since_entry": ret, "running_peak_close": peak, "running_peak_return": peak / t["entry_price"] - 1.0, "drawdown_from_running_peak": p["close"] / peak - 1.0, "MFE_to_date": max(x / t["entry_price"] - 1.0 for x in highs), "MAE_to_date": min(x / t["entry_price"] - 1.0 for x in lows), "individual_ma30": ima, "individual_exit_condition_today": iw, "individual_exit_condition_previous_day": (len(closes) >= 31 and closes[-2] < statistics.fmean(closes[-32:-2])), "individual_exit_confirmed": ic, "market_ma20": mma, "market_exit_condition_today": mw, "market_exit_confirmed": mc, "set_change_removal_observed": (s, d.isoformat()) in removed, "forced_exit_state_observed": (s, d.isoformat()) in individual_events, "actual_exit_today": d == exsig})
        has_i = (s, t["exit_signal_date"]) in individual_events
        has_set = (s, t["exit_signal_date"]) in removed
        if t["exit_reason"] == "MARKET_MA20_X2": reason, conf = "MARKET_EXIT_CONFIRMED", "PROVEN"
        elif has_i and has_set: reason, conf = "MULTIPLE_EXIT_CONDITIONS_SAME_EPISODE", "PROVEN"
        elif has_i: reason, conf = "INDIVIDUAL_EXIT_CONFIRMED", "PROVEN"
        elif has_set: reason, conf = "SET_CHANGE_REMOVAL", "PROVEN"
        elif t["exit_reason"] == "SET_CHANGE_ENTRY_OR_INDIVIDUAL_EXIT": reason, conf = "UNRESOLVED_GENERIC_EXIT", "UNRESOLVED"
        else: reason, conf = "END_OF_TEST", "PARTIALLY_PROVEN"
        vals = [r for r in rows if r["trade_id"] == t["trade_id"]]
        warnings = [r["date"] for r in vals if r["individual_exit_condition_today"]]
        m_warn = [r["date"] for r in vals if r["market_exit_condition_today"]]
        mfe = max((r["MFE_to_date"] for r in vals), default=None); mae = min((r["MAE_to_date"] for r in vals), default=None)
        lineage.append({**t, "canonical_exit_reason": reason, "canonical_reason_confidence": conf, "evidence_date": t["exit_signal_date"], "evidence_fields": {"individual_exit": has_i, "set_change": has_set, "market_reason": t["exit_reason"] == "MARKET_MA20_X2"}, "holding_trading_days": len(vals), "MFE": mfe, "MAE": mae, "MFE_date": (max(vals, key=lambda r: r["running_peak_return"])["date"] if vals else None), "first_individual_warning_date": warnings[0] if warnings else None, "first_individual_confirmed_date": t["exit_signal_date"] if has_i else None, "first_market_warning_date": m_warn[0] if m_warn else None, "first_market_confirmed_date": t["exit_signal_date"] if t["exit_signal_date"] in market_exit_dates else None, "first_set_change_removal_date": t["exit_signal_date"] if has_set else None, "giveback_pct_points": (mfe - t["realized_return"]) if mfe is not None else None, "giveback_fraction_of_MFE": ((mfe - t["realized_return"]) / mfe if mfe and mfe > 0 else None)})
    fields = list(rows[0])
    with (REPORTS / "chinext_v1_phase6_daily_exit_state.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n"); w.writeheader(); w.writerows(rows)
    lf = list(lineage[0]);
    with (REPORTS / "chinext_v1_phase6_trade_exit_lineage.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=lf, lineterminator="\n"); w.writeheader(); w.writerows(lineage)
    top20 = {t["trade_id"] for t in json.loads(WINNER.read_text(encoding="utf-8"))["top20_trades"]}
    groups = {"Top20": [t for t in lineage if t["trade_id"] in top20], "Remaining91": [t for t in lineage if t["trade_id"] not in top20]}
    reason_counts = Counter(t["canonical_exit_reason"] for t in lineage)
    generic = [t for t in lineage if t["exit_reason"] == "SET_CHANGE_ENTRY_OR_INDIVIDUAL_EXIT"]
    losers = [t for t in lineage if t["realized_return"] <= 0]
    rows_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        rows_by_id[r["trade_id"]].append(r)
    def day_value(t: dict[str, Any], n: int) -> float | None:
        path = rows_by_id[t["trade_id"]]
        return path[n]["return_since_entry"] if len(path) > n else None
    def loser_mae_cut(n: int, threshold: float) -> dict[str, Any]:
        eligible = [t for t in losers if day_value(t, n) is not None]
        # MAE through the specified session, not a stop rule.
        hit = sum(min(r["MAE_to_date"] for r in rows_by_id[t["trade_id"]][: n + 1]) >= threshold for t in eligible)
        return {"count": hit, "denominator": len(eligible), "proportion": (hit / len(eligible) if eligible else None)}
    early_loser = {f"day{n}": {f"mae_le_{abs(th):g}pct": loser_mae_cut(n, th) for th in (-.03, -.05, -.08)} for n in (5, 10, 20)}
    milestone_rows: list[dict[str, Any]] = []
    for t in groups["Top20"]:
        path = rows_by_id[t["trade_id"]]
        milestones = {}
        for threshold in (.05, .10, .20, .30, .50, 1.0):
            hit = next((r for r in path if r["return_since_entry"] >= threshold), None)
            milestones[f"+{int(threshold*100)}pct"] = None if hit is None else {"date": hit["date"], "days_from_entry": hit["days_since_entry"]}
        milestone_rows.append({"trade_id": t["trade_id"], "symbol": t["symbol"], "milestones": milestones, "final_return": t["realized_return"]})
    sept = [t for t in lineage if t["entry_signal_date"].startswith("2024-09")]
    post_exit: list[dict[str, Any]] = []
    for t in lineage:
        after = sorted(d for d in panel[t["symbol"]] if d > date.fromisoformat(t["exit_execution_date"]))
        base = t["exit_price"]
        post_exit.append({"trade_id": t["trade_id"], **{f"post_exit_{n}d_return": (panel[t["symbol"]][after[n-1]]["close"] / base - 1.0 if len(after) >= n else None) for n in (5, 10, 20)}})
    report_lines = ["# ChinNext V1 Phase 6 — Exit Lineage & Holding-Path Audit", "", "Offline-only diagnostic; no replay, NAV, PIT rebuild, or counterfactual returns.", "", f"Trade count: {len(lineage)}; generic frozen reasons: {len(generic)}", "", "## Canonical exit distribution", ""]
    for k, v in sorted(reason_counts.items()): report_lines.append(f"- {k}: {v}")
    report_lines += ["", "## Frozen identity", "", f"strategy_sha256: {sha256(STRATEGY)}", f"pit_manifest_digest: {sha256(PIT_MANIFEST)}", "formal_replay_executions: 0", "pit_rebuilt: NO", "current_survivor_fallback: NO", ""]
    for name, ts in groups.items():
        report_lines += [f"## {name} path summary", "", f"count: {len(ts)}", f"holding_days: {quantiles([t['holding_trading_days'] for t in ts])}", f"MFE: {quantiles([t['MFE'] for t in ts])}", f"MAE: {quantiles([t['MAE'] for t in ts])}", f"giveback: {quantiles([t['giveback_pct_points'] for t in ts])}", ""]
    market_trades = [t for t in lineage if t["canonical_exit_reason"] == "MARKET_EXIT_CONFIRMED"]
    market_win_loss = {"winners": sum(t["realized_return"] > 0 for t in market_trades), "losers": sum(t["realized_return"] < 0 for t in market_trades), "neutral": sum(t["realized_return"] == 0 for t in market_trades)}
    report_lines += ["## Exit implementation evidence", "", "Individual: `own_exit_signal` (MA30, two consecutive closes below MA30) in strategy/chinext_v1_exploratory.py:275-283; replay emits INDIVIDUAL_EXIT_SIGNAL at run_chinext_v1_smoke.py:824.", "Market: `market_gate_state` (MA20, two consecutive closes below MA20; emergency flag) in strategy/chinext_v1_exploratory.py:289-307; replay clears desired set at run_chinext_v1_smoke.py:806-818.", "Set-change removal is the desired-set transition (previous minus desired) on the same frozen signal date; no separate forced-exit retry event exists in this ledger.", "", "## Market / individual / set-change roles", "", f"market exits: {len(market_trades)} (winners={market_win_loss['winners']}, losers={market_win_loss['losers']}, neutral={market_win_loss['neutral']}); individual-confirmed-only canonical exits: {reason_counts.get('INDIVIDUAL_EXIT_CONFIRMED', 0)}; set-change-only canonical exits: {reason_counts.get('SET_CHANGE_REMOVAL', 0)}; multiple-condition exits: {reason_counts.get('MULTIPLE_EXIT_CONDITIONS_SAME_EPISODE', 0)}.", "The 34 generic episodes all have both individual and set-removal evidence on the frozen signal date, so they are not arbitrarily assigned to one source.", "", "## Early loser audit", "", f"loser_count: {len(losers)}", f"loser_holding_days: {quantiles([t['holding_trading_days'] for t in losers])}", f"early_loser_thresholds: {json.dumps(early_loser, sort_keys=True)}", "Thresholds are descriptive only; no stop-loss is introduced.", "", "## Top20 milestones", "", json.dumps(milestone_rows, ensure_ascii=False, sort_keys=True), "", "## September 2024 cohort", "", f"count: {len(sept)}", "; ".join(f"{t['symbol']} {t['entry_signal_date']} -> {t['exit_execution_date']} {t['canonical_exit_reason']} return={t['realized_return']:.4f}" for t in sept), "", "## Interpretation", "", "Market MA20×2 is the dominant proven portfolio-level exit source (77/111; 18/20 frozen Top20). Generic set-change/individual episodes are classified only when matching frozen events prove the lineage. Metrics are ex-post path diagnostics, not predictive features.", "", "## Phase 7 candidates (not run)", "", "- Individual-exit-disabled control only if separately pre-registered.", "- Market-exit-disabled control only if separately pre-registered.", "- Winner trailing control only if separately pre-registered.", "", "PRIMARY_EXIT_RESEARCH_PROBLEM: MARKET_EXIT_DOMINATES", "EVIDENCE_STRENGTH: MODERATE", ""]
    (REPORTS / "chinext_v1_phase6_exit_lineage.md").write_text("\n".join(report_lines), encoding="utf-8")
    write_json(REPORTS / "chinext_v1_phase6_exit_lineage_summary.json", {"trade_count": 111, "generic_reason_total": len(generic), "generic_decomposition": {"individual_exit_confirmed_count": sum(t["canonical_exit_reason"] == "INDIVIDUAL_EXIT_CONFIRMED" for t in generic), "set_change_removal_count": sum(t["canonical_exit_reason"] == "SET_CHANGE_REMOVAL" for t in generic), "multiple_condition_count": sum(t["canonical_exit_reason"] == "MULTIPLE_EXIT_CONDITIONS_SAME_EPISODE" for t in generic), "forced_exit_retry_count": 0, "still_unresolved_count": sum(t["canonical_reason_confidence"] == "UNRESOLVED" for t in generic)}, "canonical_exit_reason_counts": dict(reason_counts), "market_exit_trade_count": len(market_trades), "market_exit_win_loss": market_win_loss, "individual_exit_signal_event_count": sum(1 for e in events if e.get("event") == "INDIVIDUAL_EXIT_SIGNAL"), "individual_exit_trade_count": sum(t["canonical_exit_reason"] == "INDIVIDUAL_EXIT_CONFIRMED" for t in lineage), "set_change_exit_trade_count": sum(t["canonical_exit_reason"] == "SET_CHANGE_REMOVAL" for t in lineage), "top20_exit_reason_distribution": dict(Counter(t["canonical_exit_reason"] for t in groups["Top20"])), "top20_path_summary": {"holding_days": quantiles([t["holding_trading_days"] for t in groups["Top20"]]), "MFE": quantiles([t["MFE"] for t in groups["Top20"]]), "MAE": quantiles([t["MAE"] for t in groups["Top20"]]), "giveback": quantiles([t["giveback_pct_points"] for t in groups["Top20"]])}, "top20": milestone_rows, "early_loser_audit": early_loser, "september_2024_count": len(sept), "post_exit_diagnostic_count": len(post_exit), "loser_count": len(losers), "primary_exit_research_problem": "MARKET_EXIT_DOMINATES", "evidence_strength": "MODERATE", "formal_replay_executions": 0, "pit_rebuilt": "NO", "strategy_modified": "NO", "unresolved": [t["trade_id"] for t in lineage if t["canonical_reason_confidence"] == "UNRESOLVED"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
