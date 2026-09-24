"""Recover the two OGR VAP histories from public minute bars and L2 trades."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import requests


HERE = Path(__file__).parent
OUT = HERE / "cache" / "public_minutes"
BASE = "https://huggingface.co/datasets"
HF = "neigezhu/china-a-share-1min-ohlcv"
L2 = "phields/a-share-l2-trades"
HF_REV = "ba589a11534825044fe5a6b84838f50ba8d8d188"
L2_REV = "860bdb273a0dbe3153ffb5fc0d8e1d7496c627ca"
GAPS = {"600363.SH": "2026-08-31", "603137.SH": "2026-09-02"}
OLD = Path("/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars/2026_day_parquet_none.parquet")
GRID = list(range(570, 691)) + list(range(781, 901))


def get(url: str) -> requests.Response:
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return response


def fetch_hf(symbol: str, revision: str) -> tuple[pd.DataFrame, str]:
    ticker = symbol[:6]
    path = OUT / f"hf_{ticker}.parquet"
    if not path.exists():
        path.write_bytes(get(f"{BASE}/{HF}/resolve/{revision}/data/stock_1m/SH/{ticker}.parquet").content)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with duckdb.connect() as con:
        bars = con.execute("SELECT * FROM read_parquet(?)", [str(path)]).fetchdf()
    bars = bars.loc[bars.timestamp.between("2026-04-13", "2026-08-06 23:59:59")].copy()
    return bars.rename(columns={"timestamp": "bar_end_time", "turnover": "amount"}), digest


def fetch_l2(day: str, revision: str) -> pd.DataFrame:
    path = OUT / f"l2_{day}.parquet"
    complete = OUT / f"l2_{day}.closing_complete"
    if path.exists() and complete.exists():
        return pd.read_parquet(path)
    folder = f"data/l2_trades/trade_date={day}/code_prefix=60"
    listing = get(f"https://huggingface.co/api/datasets/{L2}/tree/{revision}/{folder}").json()
    files = [f"{BASE}/{L2}/resolve/{revision}/{item['path']}" for item in listing if item["path"].endswith(".parquet")]
    if not files:
        raise RuntimeError(f"No L2 files for {day}")
    late_only = path.exists()
    predicate = "time_s BETWEEN 54001 AND 54059" if late_only else "((time_s BETWEEN 33900 AND 41400) OR (time_s BETWEEN 46800 AND 54059))"
    with duckdb.connect() as con:
        trades = con.execute("""
            SELECT ticker,time_s,tran_id,price_x10000,volume
            FROM read_parquet(?)
            WHERE ticker IN ('600363','603137')
              AND """ + predicate + """
            ORDER BY ticker,time_s,tran_id
        """, [files]).fetchdf()
    if late_only:
        trades = pd.concat([pd.read_parquet(path), trades], ignore_index=True).sort_values(["ticker", "time_s", "tran_id"])
    trades.to_parquet(path, index=False)
    complete.touch()
    return trades


def minute_bars(trades: pd.DataFrame, day: str, ticker: str) -> pd.DataFrame:
    rows = trades.loc[trades.ticker.eq(ticker)].copy()
    if rows.empty:
        raise RuntimeError(f"No trades for {ticker} {day}")
    minute = np.where(rows.time_s < 34200, 570, np.where(rows.time_s >= 54000, 900, rows.time_s // 60 + 1))
    rows["minute"] = minute
    rows["price"] = rows.price_x10000 / 10000.0
    rows["amount"] = rows.price * rows.volume
    grouped = rows.groupby("minute", sort=True).agg(
        open=("price", "first"), high=("price", "max"), low=("price", "min"),
        close=("price", "last"), volume=("volume", "sum"), amount=("amount", "sum"),
    )
    if not grouped.index.isin(GRID).all():
        raise RuntimeError(f"Out-of-session trades for {ticker} {day}")
    grouped = grouped.reindex(GRID)
    grouped["close"] = grouped.close.ffill().bfill()
    for column in ("open", "high", "low"):
        grouped[column] = grouped[column].fillna(grouped.close)
    grouped[["volume", "amount"]] = grouped[["volume", "amount"]].fillna(0)
    grouped["bar_end_time"] = pd.to_datetime(day) + pd.to_timedelta(grouped.index // 60, unit="h") + pd.to_timedelta(grouped.index % 60, unit="m")
    grouped["qmt_code"] = ticker + ".SH"
    grouped["trade_date"] = pd.Timestamp(day)
    grouped["source"] = "phields_l2_trades"
    return grouped.reset_index(drop=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    daily = pd.read_parquet(HERE / "cache/daily_with_snapshot.parquet")
    revision = L2_REV
    hf_revision = HF_REV
    needed = {}
    for symbol, gap in GAPS.items():
        history = daily.loc[(daily.symbol == symbol) & (daily.trade_date < pd.Timestamp(gap))].sort_values("trade_date").tail(120)
        assert len(history) == 120
        needed[symbol] = history
    dates = sorted({str(day.date()) for history in needed.values() for day in history.trade_date if day >= pd.Timestamp("2026-08-07")})
    recovered = []
    for day in dates:
        trades = fetch_l2(day, revision)
        for symbol, history in needed.items():
            if pd.Timestamp(day) in set(history.trade_date):
                bars = minute_bars(trades, day, symbol[:6])
                recovered.append(bars)
        print("L2", day, len(trades), flush=True)
    old_days = sorted({str(day.date()) for history in needed.values() for day in history.trade_date if day <= pd.Timestamp("2026-04-10")})
    with duckdb.connect() as con:
        old = con.execute("SELECT * FROM read_parquet(?) WHERE qmt_code IN ('600363.SH','603137.SH') AND trade_date IN (SELECT UNNEST(?::DATE[]))", [str(OLD), old_days]).fetchdf()
    old = old.loc[old.apply(lambda row: pd.Timestamp(row.trade_date) in set(needed[row.qmt_code].trade_date), axis=1)]
    old["source"] = "frozen_canonical"
    hf_frames, hf_hashes = [], {}
    for symbol, history in needed.items():
        frame, digest = fetch_hf(symbol, hf_revision)
        hf_hashes[symbol] = digest
        frame = frame.loc[frame.bar_end_time.dt.normalize().isin(history.trade_date)].copy()
        frame["qmt_code"] = symbol
        frame["trade_date"] = frame.bar_end_time.dt.normalize()
        frame["source"] = "neigezhu_public_1m"
        hf_frames.append(frame)
    cols = ["qmt_code", "trade_date", "bar_end_time", "open", "high", "low", "close", "volume", "amount", "source"]
    all_bars = pd.concat([old[cols], *[x[cols] for x in hf_frames], *[x[cols] for x in recovered]], ignore_index=True)
    all_bars["period"] = "1m"
    all_bars["adjust"] = "none"
    all_bars["source_resolution_minutes"] = 1
    all_bars = all_bars.sort_values(["qmt_code", "bar_end_time"]).reset_index(drop=True)
    checks = all_bars.groupby(["qmt_code", "trade_date", "source"]).agg(bars=("bar_end_time", "size"), volume=("volume", "sum"), amount=("amount", "sum")).reset_index()
    check_daily = daily[["symbol", "trade_date", "volume", "amount"]].rename(columns={"symbol": "qmt_code", "volume": "daily_volume", "amount": "daily_amount"})
    checks = checks.merge(check_daily, on=["qmt_code", "trade_date"], validate="one_to_one")
    checks["volume_rel_error"] = (checks.volume - checks.daily_volume).abs() / checks.daily_volume
    checks["amount_rel_error"] = (checks.amount - checks.daily_amount).abs() / checks.daily_amount
    checks.to_csv(HERE / "public_minute_daily_reconciliation.csv", index=False)
    for symbol, history in needed.items():
        part = checks.loc[checks.qmt_code.eq(symbol)]
        assert len(part) == 120 and part.bars.eq(241).all(), (symbol, len(part), part.loc[part.bars.ne(241)])
    all_bars["trade_date"] = all_bars.trade_date.dt.date
    all_bars.to_parquet(OUT / "2026_day_parquet_none.parquet", index=False)
    manifest = {"l2_revision": revision, "hf_revision": hf_revision, "hf_file_sha256": hf_hashes,
                "l2_extract_sha256": {day: hashlib.sha256((OUT / f"l2_{day}.parquet").read_bytes()).hexdigest() for day in dates},
                "dates": dates, "daily_reconciliation_max_rel_error": {"volume": float(checks.volume_rel_error.max()), "amount": float(checks.amount_rel_error.max())}}
    (HERE / "public_minute_source_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
