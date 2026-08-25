"""PIT-safe capacity experiment: at most 200 effective entries per year.

This is a research diagnostic layered on the frozen Chapter 8/9 lifecycle
output.  Ranking uses only feature rows dated signal_date; selection is greedy
in chronological order, so later observations cannot decide earlier trades.
"""
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE = ROOT / "data/audit/chapter8_9_trade_lifecycle_v01.csv"
FEATURES = ROOT / "data/processed/chip_state_features_2018_2026_v2/bucket=*/data.parquet"
OUT = ROOT / "data/audit/chapter8_9_top200_v01.csv"


def main() -> None:
    con = duckdb.connect()
    con.execute("PRAGMA threads=8")
    sql = f"""
    WITH c AS (
      SELECT * FROM read_csv_auto('{LIFECYCLE}', header=true)
    ), f AS (
      SELECT symbol, trade_date AS signal_date, chip_input_valid,
             daily_hard_valid, strict_sample, profit_ratio, trapped_ratio,
             asr, space20, base_retention, realized_volatility,
             available_at, daily_snapshot_id
      FROM read_parquet('{FEATURES}')
    ), x AS (
      SELECT c.*, EXTRACT(year FROM CAST(c.signal_date AS DATE)) AS year,
             f.chip_input_valid, f.daily_hard_valid, f.strict_sample,
             f.profit_ratio, f.trapped_ratio, f.asr, f.space20,
             f.base_retention, f.realized_volatility, f.available_at,
             f.daily_snapshot_id
      FROM c JOIN f USING (symbol, signal_date)
      WHERE (regexp_matches(symbol, '^(000|001|002|003|600|601|603|605)'))
         OR regexp_matches(symbol, '^300')
    )
    SELECT * FROM x
    WHERE chip_input_valid AND daily_hard_valid AND strict_sample
      AND available_at IS NOT NULL AND daily_snapshot_id IS NOT NULL
    """
    df = con.execute(sql).fetchdf()
    if df.empty:
        raise SystemExit("no PIT-valid candidates")

    # Cross-sectional ranks are computed only among candidates on that date.
    cols = ["profit_ratio", "asr", "space20", "base_retention"]
    for col in cols:
        df[col + "_pct"] = df.groupby("signal_date")[col].rank(pct=True)
    df["trapped_pct"] = df.groupby("signal_date")["trapped_ratio"].rank(pct=True)
    df["score"] = (
        0.30 * df["profit_ratio_pct"]
        + 0.25 * df["asr_pct"]
        + 0.20 * df["space20_pct"]
        + 0.15 * df["base_retention_pct"]
        - 0.10 * df["trapped_pct"]
    )
    df["board"] = df["symbol"].str.startswith("300").map({True: "CHINEXT", False: "MAIN"})
    df = df.sort_values(["signal_date", "score", "symbol"], ascending=[True, False, True])

    # Chronological greedy capacity: one effective entry per signal day,
    # one effective entry per symbol per year, and no more than 200/year.
    # The daily limit prevents a dense signal burst from consuming the whole
    # annual budget in January while remaining fully PIT-safe.
    counts: dict[int, int] = {}
    seen: set[tuple[int, str]] = set()
    seen_days: set[tuple[int, object]] = set()
    accepted = []
    for row in df.itertuples(index=False):
        key = (int(row.year), row.symbol)
        day_key = (int(row.year), row.signal_date)
        if (counts.get(int(row.year), 0) >= 200 or key in seen
                or day_key in seen_days):
            continue
        seen.add(key)
        seen_days.add(day_key)
        counts[int(row.year)] = counts.get(int(row.year), 0) + 1
        accepted.append(row)
    out = pd.DataFrame(accepted, columns=df.columns)
    out.to_csv(OUT, index=False)

    print("selected", len(out), "of", len(df), "candidates")
    print(out.groupby(["year", "board"], dropna=False).agg(
        n=("net_return", "size"), mean_net=("net_return", "mean"),
        median_net=("net_return", "median"), win_rate=("net_return", lambda s: (s > 0).mean()),
        p10=("net_return", lambda s: s.quantile(.10)), p90=("net_return", lambda s: s.quantile(.90)),
    ).round(5).to_string())
    print("year totals")
    print(out.groupby("year").agg(n=("net_return", "size"), mean_net=("net_return", "mean"),
                                    median_net=("net_return", "median"),
                                    win_rate=("net_return", lambda s: (s > 0).mean())).round(5).to_string())


if __name__ == "__main__":
    main()
