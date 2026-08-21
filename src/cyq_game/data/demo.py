from __future__ import annotations

import csv
import math
import random
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

DEMO_SYMBOLS = (
    ("600001.SH", 11.0, 0.00030, 1_200_000_000.0, 0.10, "DEMO-INDUSTRIAL"),
    ("300001.SZ", 19.0, 0.00018, 720_000_000.0, 0.20, "DEMO-INDUSTRIAL"),
    ("688001.SH", 32.0, -0.00003, 430_000_000.0, 0.20, "DEMO-TECH"),
    ("830001.BJ", 8.5, 0.00012, 260_000_000.0, 0.30, "DEMO-TECH"),
)


def generate_demo_csv(
    output: str | Path,
    *,
    start: date = date(2023, 1, 2),
    end: date = date(2024, 12, 31),
    seed: int = 20260818,
) -> int:
    """Generate deterministic, structurally valid A-share daily bars.

    The series are synthetic and deliberately contain different trend, base, and
    reversal regimes. They are suitable only for smoke tests and demonstrations.
    """

    if end < start:
        raise ValueError("end must not precede start")
    trading_dates = _weekdays(start, end)
    if not trading_dates:
        raise ValueError("date range contains no trading weekdays")
    rows: list[dict[str, str]] = []
    for symbol_index, item in enumerate(DEMO_SYMBOLS):
        symbol, initial, drift, free_float, limit_pct, _industry = item
        rng = random.Random(seed + 1009 * symbol_index)
        previous = initial
        for index, trade_date in enumerate(trading_dates):
            cycle = 0.0025 * math.sin(index / (17.0 + symbol_index * 3.0))
            regime = (
                -0.0015
                if 130 <= index < 175
                else 0.0018
                if 260 <= index < 330
                else 0.0
            )
            shock = rng.gauss(0.0, 0.012 + symbol_index * 0.0015)
            close_return = max(
                -limit_pct * 0.92,
                min(limit_pct * 0.92, drift + cycle + regime + shock),
            )
            close = max(1.0, previous * (1.0 + close_return))
            overnight = rng.gauss(0.0, 0.004)
            open_price = previous * (1.0 + overnight)
            intraday = abs(rng.gauss(0.012, 0.004))
            high = max(open_price, close) * (1.0 + intraday)
            low = max(0.01, min(open_price, close) * (1.0 - intraday))
            turnover = max(0.001, min(0.12, 0.018 + abs(shock) * 1.8 + rng.gauss(0, 0.004)))
            volume = free_float * turnover
            amount = volume * (high + low + close) / 3.0
            available_at = datetime.combine(trade_date, time(15, 30), tzinfo=UTC)
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date.isoformat(),
                    "open": f"{open_price:.4f}",
                    "high": f"{high:.4f}",
                    "low": f"{low:.4f}",
                    "close": f"{close:.4f}",
                    "volume": f"{volume:.0f}",
                    "amount": f"{amount:.2f}",
                    "free_float_shares": f"{free_float:.0f}",
                    "available_at": available_at.isoformat(),
                    "suspended": "0",
                    "st": "0",
                    "limit_up": f"{previous * (1.0 + limit_pct):.4f}",
                    "limit_down": f"{previous * (1.0 - limit_pct):.4f}",
                }
            )
            previous = close
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def generate_demo_industry_csv(
    output: str | Path,
    *,
    effective_from: date = date(2023, 1, 2),
) -> int:
    """Generate deterministic PIT industry memberships for the demo universe."""

    available_at = datetime.combine(effective_from, time(0), tzinfo=UTC)
    rows = [
        {
            "symbol": symbol,
            "industry": industry,
            "effective_from": effective_from.isoformat(),
            "effective_to": "",
            "available_at": available_at.isoformat(),
            "source": "synthetic-demo",
            "snapshot_id": "demo-industry-v1",
            "revision_id": "1",
        }
        for symbol, _initial, _drift, _free_float, _limit_pct, industry in DEMO_SYMBOLS
    ]
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def generate_demo_fundamentals_csv(
    output: str | Path,
    *,
    start: date = date(2023, 1, 2),
    end: date = date(2024, 12, 31),
) -> int:
    """Generate deterministic, disclosure-timestamped demo fundamentals."""

    if end < start:
        raise ValueError("end must not precede start")
    trading_dates = _weekdays(start, end)
    if not trading_dates:
        raise ValueError("date range contains no trading weekdays")
    release_dates = trading_dates[::63]
    rows: list[dict[str, str]] = []
    for symbol_index, item in enumerate(DEMO_SYMBOLS):
        symbol = item[0]
        for release_index, release_date in enumerate(release_dates):
            cycle = 0.015 * math.sin(release_index / 2.0 + symbol_index)
            period_end = release_date - timedelta(days=30)
            event_time = datetime.combine(release_date, time(7, 30), tzinfo=UTC)
            available_at = datetime.combine(release_date, time(8), tzinfo=UTC)
            rows.append(
                {
                    "symbol": symbol,
                    "period_end": period_end.isoformat(),
                    "event_time": event_time.isoformat(),
                    "available_at": available_at.isoformat(),
                    "effective_from": release_date.isoformat(),
                    "revenue_growth": f"{0.12 - 0.015 * symbol_index + cycle:.6f}",
                    "profit_growth": f"{0.16 - 0.020 * symbol_index + cycle:.6f}",
                    "roe": f"{0.17 - 0.015 * symbol_index:.6f}",
                    "operating_cashflow_to_profit": f"{1.10 - 0.05 * symbol_index:.6f}",
                    "debt_ratio": f"{0.30 + 0.05 * symbol_index:.6f}",
                    "valuation_percentile": f"{0.28 + 0.12 * symbol_index:.6f}",
                    "earnings_revision": f"{0.025 - 0.005 * symbol_index:.6f}",
                    "investment_growth": f"{0.08 + 0.01 * symbol_index:.6f}",
                    "capital_return": f"{0.55 - 0.10 * symbol_index:.6f}",
                    "audit_or_going_concern_risk": "0",
                    "source": "synthetic-demo",
                    "snapshot_id": "demo-fundamentals-v1",
                    "revision_id": "1",
                }
            )
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def _weekdays(start: date, end: date) -> list[date]:
    result: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result
