"""Audit signal frequency using independent stock/date/signal events.

The state-machine grid intentionally repeats an event across parameter rows.
This report removes that multiplicity before judging coverage or quality.
Research-only; it does not alter the backtest result.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/audit/chapter8_9_state_machine_v01.csv"
OUTPUT = ROOT / "data/audit/chapter8_9_independent_event_audit.csv"


def main() -> None:
    frame = pd.read_csv(INPUT, parse_dates=["signal_date"])
    frame = frame[frame["sample_group"].isin(["PROBE_2020_2023", "HOLDOUT_2024_2026"])]
    frame = frame.drop_duplicates(["sample_group", "symbol", "signal_date", "signal"])
    frame["year"] = frame["signal_date"].dt.year
    summary = (
        frame.groupby(["sample_group", "year", "signal"], as_index=False)
        .agg(
            independent_events=("signal", "size"),
            stocks=("symbol", "nunique"),
            mean_net_return=("net_return", "mean"),
            median_net_return=("net_return", "median"),
            win_rate=("net_return", lambda s: float((s > 0).mean())),
        )
        .sort_values(["sample_group", "year", "signal"])
    )
    summary.to_csv(OUTPUT, index=False)
    print(OUTPUT)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
