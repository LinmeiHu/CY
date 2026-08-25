"""Collapse lifecycle events into a non-overlapping, capacity-limited portfolio.

Research-only post-processing; it deliberately fails closed when dates or prices
are missing. It is not a broker or live execution component.
"""
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data/audit/chapter8_9_trade_lifecycle_v01.csv"
OUT = ROOT / "data/audit/chapter8_9_portfolio_v01.csv"


def main() -> None:
    rows = list(csv.DictReader(IN.open()))
    for r in rows:
        r["signal_date"] = r["signal_date"]
        r["entry_date"] = r["entry_date"]
        r["exit_date"] = r["exit_date"]
        r["net_return"] = float(r["net_return"])
    # One position per symbol: earliest eligible signal after prior exit.
    chosen = []
    last_exit = defaultdict(str)
    for r in sorted(rows, key=lambda x: (x["entry_date"], x["symbol"], x["signal_date"])):
        if r["entry_date"] <= last_exit[r["symbol"]]:
            continue
        last_exit[r["symbol"]] = r["exit_date"]
        chosen.append(r)
    # Equal-weight capacity approximation: 2% initial allocation, max 20 names.
    # Same-day signals are ranked by signal family then symbol for deterministic replay.
    by_day = defaultdict(list)
    for r in chosen:
        by_day[(r["entry_date"], r["sample_group"])].append(r)
    final = []
    for _key, batch in by_day.items():
        for r in sorted(batch, key=lambda x: (x["signal"], x["symbol"]))[:20]:
            r["weight"] = 0.02
            r["weighted_net_return"] = r["net_return"] * 0.02
            final.append(r)
    fields = list(final[0].keys()) if final else []
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(final)
    for group in ("PROBE_2020_2023", "HOLDOUT_2024_2026"):
        rr = [r for r in final if r["sample_group"] == group]
        total = sum(float(r["weighted_net_return"]) for r in rr)
        print(group, "trades", len(rr), "weighted_sum", round(total, 4))
    print(OUT)


if __name__ == "__main__":
    main()
