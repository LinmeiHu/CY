"""Select frozen chapter 8/9 parameters from the probe period only.

Research-only and append-only: this file records the exact training-period
selection used by a later holdout replay. No holdout statistic is consulted.
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data/audit/chapter8_9_grid_probe_v01.csv"
OUT = ROOT / "data/audit/chapter8_9_frozen_params_v01.csv"


def main() -> None:
    rows = list(csv.DictReader(IN.open()))
    train = [r for r in rows if r["sample_group"] == "PROBE_2020_2023"]
    chosen = []
    for board in ("MAIN", "CHINEXT"):
        for signal in ("B1", "B2", "B5"):
            candidates = [r for r in train if r["board"] == board and r["signal"] == signal and int(r["n"]) >= 100]
            if not candidates:
                continue
            # Primary objective is mean 20-bar forward return; median breaks ties.
            best = max(candidates, key=lambda r: (float(r["fwd20_mean"]), float(r["fwd20_median"])))
            chosen.append({
                "selection_period": "2020-01-02..2023-12-29",
                "board": board, "signal": signal,
                "narrow_pct": best["narrow_pct"], "vol_window": best["vol_window"],
                "confirm_days": best["confirm_days"], "breakout_buffer": best["breakout_buffer"],
                "train_n": best["n"], "train_fwd20_mean": best["fwd20_mean"],
                "train_fwd20_median": best["fwd20_median"],
            })
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(chosen[0]))
        w.writeheader()
        w.writerows(chosen)
    for r in chosen:
        print(r)
    print(OUT)


if __name__ == "__main__":
    main()
