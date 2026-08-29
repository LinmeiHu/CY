from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import run_v6_chinext_shadow as base
from v6_data_common import RESEARCH_ROOT, atomic_write_json, atomic_write_parquet

DATA_ROOT = RESEARCH_ROOT / "data" / "market_data_qmt_mainboard_v1"
UNIVERSE_PATH = RESEARCH_ROOT / "manifests" / "mainboard_current_survivor_universe.json"
EVENTS_PATH = RESEARCH_ROOT / "output" / "v6_mainboard_shadow_events.parquet"
SUMMARY_PATH = RESEARCH_ROOT / "manifests" / "v6_mainboard_shadow_summary.json"
REPORT_PATH = RESEARCH_ROOT / "reports" / "v6_mainboard_signal_quality.md"
CANDIDATES_PATH = RESEARCH_ROOT / "manifests" / "v6_mainboard_candidate_symbols.json"
START = date(2025, 8, 28)
END = date(2026, 8, 28)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=date.fromisoformat, default=START)
    parser.add_argument("--end", type=date.fromisoformat, default=END)
    parser.add_argument("--universe", type=Path, default=UNIVERSE_PATH)
    parser.add_argument("--events", type=Path, default=EVENTS_PATH)
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--daily-proxy", action="store_true")
    parser.add_argument("--candidates", type=Path, default=CANDIDATES_PATH)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    return parser.parse_args()


def write_report(path: Path, summary: dict[str, Any]) -> None:
    forward = summary["forward_quality"]
    coverage = summary["critical_bar_coverage"]
    lines = [
        "# SuperMind V6 on Shanghai/Shenzhen main-board stocks - exploratory signal quality",
        "",
        (
            f"Window: {summary['window_start']}..{summary['window_end']} "
            f"({summary['calendar_sessions']} sessions)"
        ),
        (
            f"Universe: {summary['universe_count']} current-listed SH/SZ main-board "
            "stocks (NON-PIT survivor universe)"
        ),
        "",
        "## Result",
        "",
        (
            "- Event counts: `"
            f"{json.dumps(summary['event_counts'], ensure_ascii=False, sort_keys=True)}`"
        ),
        f"- Unique bought symbols: {summary['unique_bought_symbols']}",
        (
            f"- Critical bars: {coverage['exact_1m_final_candidates']} exact-1m "
            f"final candidates; 5m fallback={coverage['five_minute_fallback_symbols']}"
        ),
        f"- Completed holding P&L: {base.fmt_metric(summary['roundtrip_holding_pnl'])}",
        f"- Forward 5 sessions: {base.fmt_metric(forward['fwd_5d'])}",
        f"- Forward 10 sessions: {base.fmt_metric(forward['fwd_10d'])}",
        f"- Forward 20 sessions: {base.fmt_metric(forward['fwd_20d'])}",
        f"- Forward 60 sessions: {base.fmt_metric(forward['fwd_60d'])}",
        f"- 20-session MFE: {base.fmt_metric(forward['mfe_20d'])}",
        f"- 20-session MAE: {base.fmt_metric(forward['mae_20d'])}",
        "",
        "## Interpretation boundary",
        "",
        *[f"- {item}" for item in summary["limitations"]],
        "",
        (
            "This experiment does not modify the frozen strategy. It replaces only the "
            "static ETF pool after init inside a research sandbox."
        ),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    base.DATA_ROOT = args.data_root
    args.execution_label = "MAINBOARD_SHADOW_09_30"
    events, summary = base.run(args)
    summary["experiment"] = "V6_MAINBOARD_CURRENT_SURVIVOR_COUNTERFACTUAL"
    summary["universe_definition"] = (
        "current-listed SH 600/601/603/605 and SZ 000/001/002/003 main-board stocks"
    )
    candidate_symbols = sorted(
        events.loc[
            events["event_type"].isin(["BUY_SIGNAL", "BUY_FILLED", "REBALANCE_FILLED"]),
            "symbol",
        ].unique()
    )
    fallback_path = args.data_root / "qmt_5m_critical_fallback_summary.json"
    fallback_symbols: list[str] = []
    if fallback_path.exists():
        fallback_summary = json.loads(fallback_path.read_text(encoding="utf-8"))
        fallback_symbols = sorted(
            set(fallback_summary.get("results", {})).intersection(candidate_symbols)
        )
    summary["critical_bar_coverage"] = {
        "final_candidate_symbols": len(candidate_symbols),
        "exact_1m_final_candidates": len(candidate_symbols) - len(fallback_symbols),
        "five_minute_fallback_symbols": fallback_symbols,
        "no_fill_events": int(events["event_type"].str.contains("NO_FILL", na=False).sum()),
    }
    if fallback_symbols:
        summary["limitations"].append(
            f"{', '.join(fallback_symbols)} exact 1m history was unavailable; their "
            "open/final-close references use QMT 5m bars and 14:57 uses the 15:00 "
            "5m-bar open as an approximation"
        )
    atomic_write_parquet(events, args.events)
    atomic_write_json(args.summary, summary)
    write_report(args.report, summary)
    atomic_write_json(
        args.candidates,
        {
            "candidate_source": (
                "V6 main-board daily-proxy pass"
                if args.daily_proxy
                else "V6 main-board final shadow"
            ),
            "symbol_count": len(candidate_symbols),
            "symbols": candidate_symbols,
        },
    )
    print(f"EVENTS {len(events)}")
    print(f"BUYS {summary['event_counts'].get('BUY_FILLED', 0)}")
    print(f"SELLS {summary['event_counts'].get('SELL_FILLED', 0)}")
    print(f"REPORT {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
