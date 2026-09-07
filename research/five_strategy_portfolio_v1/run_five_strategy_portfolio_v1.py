from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Iterable
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

STRATEGIES = ("ATRDR", "MCB", "OGR", "IFCGR", "SMV6")
SEVERE_LOSS = -0.10
EPS = 1e-12


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, na_rep="NA")


def read_parquet(path: Path, columns: Iterable[str] | None = None) -> pd.DataFrame:
    con = duckdb.connect()
    try:
        if columns:
            select = ",".join(f'"{column}"' for column in columns)
            return con.execute(
                f"SELECT {select} FROM read_parquet(?)", [str(path)]
            ).fetchdf()
        return con.execute("SELECT * FROM read_parquet(?)", [str(path)]).fetchdf()
    finally:
        con.close()


def assert_unique(frame: pd.DataFrame, keys: list[str], label: str) -> None:
    if frame.duplicated(keys).any():
        raise ValueError(f"{label}: duplicate identity on {keys}")


def merge_one_to_one(
    left: pd.DataFrame, right: pd.DataFrame, key: str, label: str
) -> pd.DataFrame:
    assert_unique(left, [key], f"{label}/left")
    assert_unique(right, [key], f"{label}/right")
    result = left.merge(right, on=key, how="left", validate="one_to_one")
    if len(result) != len(left):
        raise ValueError(f"{label}: join inflated row count")
    return result


def asof_trade_view(
    frame: pd.DataFrame, asof: pd.Timestamp
) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = frame.copy()
    if "signal_date" in data:
        data = data.loc[pd.to_datetime(data.signal_date) <= asof].copy()
    exited = data.loc[
        data.exit_date.notna() & (pd.to_datetime(data.exit_date) <= asof)
    ].copy()
    unresolved = data.loc[~data.index.isin(exited.index)].copy()
    return exited, unresolved


def reject_missing_metric(frame: pd.DataFrame, column: str) -> float:
    """Never turn unavailable holdings/account state into a false zero."""
    return float(frame[column].mean()) if column in frame else math.nan


def prevent_false_segment_concat(
    segments: list[pd.DataFrame], reset_flags: list[bool]
) -> pd.DataFrame:
    if len(segments) != len(reset_flags):
        raise ValueError("segment/reset metadata mismatch")
    if len(segments) > 1 and any(reset_flags[1:]):
        raise ValueError(
            "independently initialized account segments cannot be concatenated"
        )
    return pd.concat(segments, ignore_index=True)


def tail_index(returns: pd.Series, fraction: float = 0.05) -> pd.Index:
    clean = returns.dropna()
    if clean.empty:
        return clean.index
    count = max(1, math.ceil(len(clean) * fraction))
    order = pd.DataFrame(
        {"value": clean, "date": pd.to_datetime(clean.index)}, index=clean.index
    )
    return order.sort_values(["value", "date"], kind="mergesort").index[:count]


def account_metrics(
    account: pd.DataFrame, initial_nav: float | None = None
) -> dict[str, object]:
    frame = account.sort_index()
    nav = frame.nav.astype(float)
    returns = nav.pct_change(fill_method=None)
    if initial_nav is not None:
        returns.iloc[0] = nav.iloc[0] / initial_nav - 1
    returns = returns.dropna()
    years = (frame.index[-1] - frame.index[0]).days / 365.25
    dd = nav / nav.cummax() - 1
    std = returns.std(ddof=1)
    tail = returns.loc[tail_index(returns)]
    annual = returns.groupby(returns.index.year).apply(lambda x: (1 + x).prod() - 1)
    monthly = returns.groupby(returns.index.to_period("M")).apply(
        lambda x: (1 + x).prod() - 1
    )
    result: dict[str, object] = {
        "start": frame.index[0].date().isoformat(),
        "end": frame.index[-1].date().isoformat(),
        "nav_rows": len(frame),
        "return_days": len(returns),
        "total_return": nav.iloc[-1] / (initial_nav or nav.iloc[0]) - 1,
        "cagr": (nav.iloc[-1] / (initial_nav or nav.iloc[0])) ** (1 / years) - 1
        if years > 0
        else math.nan,
        "max_drawdown": dd.min(),
        "sharpe": returns.mean() / std * math.sqrt(252)
        if pd.notna(std) and std > 0
        else math.nan,
        "worst_5pct_mean": tail.mean(),
        "worst_year": str(annual.idxmin()) if len(annual) else "NA",
        "worst_year_return": annual.min() if len(annual) else math.nan,
        "worst_month": str(monthly.idxmin()) if len(monthly) else "NA",
        "worst_month_return": monthly.min() if len(monthly) else math.nan,
        "avg_utilization": reject_missing_metric(frame, "utilization"),
        "p95_exposure": frame["utilization"].quantile(0.95)
        if "utilization" in frame
        else math.nan,
        "full_cash_day_ratio": (frame["gross_exposure"].abs() <= EPS).mean()
        if "gross_exposure" in frame
        else math.nan,
        "short_sample": years < 1,
    }
    return result


def normalize_account(
    frame: pd.DataFrame,
    nav: str,
    cash: str | None,
    gross: str | None,
    utilization: str | None,
    active: str | None,
) -> pd.DataFrame:
    data = frame.copy()
    data["trade_date"] = pd.to_datetime(data.trade_date).dt.normalize()
    data = data.sort_values("trade_date", kind="mergesort").set_index("trade_date")
    assert_unique(data.reset_index(), ["trade_date"], "daily account")
    out = pd.DataFrame(index=data.index)
    out["nav"] = data[nav].astype(float)
    if cash:
        out["cash"] = data[cash].astype(float)
    if gross:
        out["gross_exposure"] = data[gross].astype(float)
    if utilization:
        out["utilization"] = data[utilization].astype(float)
    elif "gross_exposure" in out:
        out["utilization"] = out.gross_exposure / out.nav
    if active:
        out["active_positions"] = data[active].astype(float)
    return out


def reconstruct_mcb_account(root: Path, daily_hist: Path) -> pd.DataFrame:
    accepted = read_parquet(root / "mcb/accepted.parquet")
    nav = read_parquet(root / "mcb/nav.parquet")
    for column in ("entry_date", "exit_date"):
        accepted[column] = pd.to_datetime(accepted[column]).dt.normalize()
    symbols = pd.DataFrame({"symbol": sorted(accepted.symbol.astype(str).unique())})
    con = duckdb.connect()
    con.register("symbols", symbols)
    try:
        marks = con.execute(
            "SELECT d.trade_date,d.symbol,d.coord_close FROM read_parquet(?) d "
            "JOIN symbols s USING(symbol) WHERE d.trade_date BETWEEN ? AND ?",
            [str(daily_hist), accepted.entry_date.min(), accepted.exit_date.max()],
        ).fetchdf()
    finally:
        con.close()
    marks["trade_date"] = pd.to_datetime(marks.trade_date).dt.normalize()
    marks = marks.drop_duplicates(["trade_date", "symbol"], keep="last")
    mark_map = {
        (row.trade_date, row.symbol): float(row.coord_close)
        for row in marks.itertuples()
    }
    entries = {date: part for date, part in accepted.groupby("entry_date", sort=False)}
    exits = {date: part for date, part in accepted.groupby("exit_date", sort=False)}
    active: dict[str, object] = {}
    cash = 1.0
    rows = []
    for date in pd.to_datetime(nav.trade_date).dt.normalize():
        if date in exits:
            for row in (
                exits[date].sort_values("event_id", kind="mergesort").itertuples()
            ):
                cash += float(row.qty) * float(row.exit_price) * 0.998
                active.pop(str(row.event_id), None)
        if date in entries:
            for row in (
                entries[date].sort_values("event_id", kind="mergesort").itertuples()
            ):
                cash -= float(row.entry_outlay)
                active[str(row.event_id)] = row
        gross = sum(
            float(row.qty) * mark_map[(date, str(row.symbol))]
            for row in active.values()
        )
        value = cash + gross
        rows.append(
            {
                "trade_date": date,
                "nav": value,
                "cash": cash,
                "gross_exposure": gross,
                "utilization": gross / value,
                "active_positions": len(active),
            }
        )
    result = normalize_account(
        pd.DataFrame(rows),
        "nav",
        "cash",
        "gross_exposure",
        "utilization",
        "active_positions",
    )
    expected = normalize_account(nav, "combined_nav", None, None, None, None)
    delta = (result.nav - expected.nav).abs().max()
    if delta > 2e-12:
        raise ValueError(f"MCB reconstructed account differs from sealed NAV: {delta}")
    return result


def load_accounts(
    root: Path, inputs: dict[str, str], asof: pd.Timestamp
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    accounts: dict[str, pd.DataFrame] = {}
    accounts["MCB"] = reconstruct_mcb_account(root, Path(inputs["daily_hist"]))
    for strategy in ("OGR", "IFCGR"):
        frame = read_parquet(root / strategy.lower() / "nav.parquet")
        frame = frame.loc[frame.board.eq("COMBINED")].copy()
        accounts[strategy] = normalize_account(
            frame, "nav", "cash", "gross_exposure", "utilization", "active_positions"
        )
    atrdr = read_parquet(root / "atrdr/nav.parquet")
    atrdr["gross_exposure"] = atrdr.combined_nav - atrdr.main_cash - atrdr.chinext_cash
    atrdr["cash"] = atrdr.main_cash + atrdr.chinext_cash
    accounts["ATRDR"] = normalize_account(
        atrdr,
        "combined_nav",
        "cash",
        "gross_exposure",
        "utilization",
        "active_positions",
    )
    smv6 = read_parquet(root / "smv6/nav.parquet")
    accounts["SMV6"] = normalize_account(
        smv6, "nav", "cash", "gross_exposure", "gross_exposure_ratio", "position_count"
    )
    accounts = {
        key: value.loc[value.index <= asof].copy() for key, value in accounts.items()
    }

    atrdr_segments = {"ATRDR_HISTORICAL": accounts["ATRDR"]}
    for label, rel in (
        ("ATRDR_2024_2025_RESET", "atrdr/post_2024_2025/stage_b/portfolio_nav.parquet"),
        ("ATRDR_2026_RESET", "atrdr/post_2026/stage_b/portfolio_nav.parquet"),
    ):
        frame = read_parquet(root / rel)
        frame["cash"] = frame.combined_nav * (1 - frame.utilization)
        frame["gross_exposure"] = frame.combined_nav * frame.utilization
        segment = normalize_account(
            frame,
            "combined_nav",
            "cash",
            "gross_exposure",
            "utilization",
            "active_positions",
        )
        atrdr_segments[label] = segment.loc[segment.index <= asof].copy()
    return accounts, atrdr_segments


def common_dates(
    accounts: dict[str, pd.DataFrame], names: Iterable[str]
) -> pd.DatetimeIndex:
    dates: pd.DatetimeIndex | None = None
    for name in names:
        dates = (
            accounts[name].index
            if dates is None
            else dates.intersection(accounts[name].index)
        )
    if dates is None or dates.empty:
        raise ValueError("no common account dates")
    return dates.sort_values()


def portfolio_frame(
    accounts: dict[str, pd.DataFrame],
    weights: dict[str, float],
    dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    if abs(sum(weights.values()) - 1) > EPS:
        raise ValueError("portfolio weights must sum to one")
    result = pd.DataFrame(index=dates)
    q: dict[str, pd.Series] = {}
    for strategy, weight in weights.items():
        nav = accounts[strategy].loc[dates, "nav"]
        q[strategy] = nav / nav.iloc[0]
        result[f"q_{strategy}"] = q[strategy]
        result[f"allocation_{strategy}"] = weight * q[strategy]
    result["nav"] = sum(weights[name] * q[name] for name in weights)
    gross = sum(
        weights[name] * q[name] * accounts[name].loc[dates, "utilization"]
        for name in weights
    )
    result["gross_exposure"] = gross
    result["cash"] = result.nav - result.gross_exposure
    result["utilization"] = result.gross_exposure / result.nav
    for name in weights:
        result[f"drift_weight_{name}"] = result[f"allocation_{name}"] / result.nav
    return result


def leave_cash(
    main: pd.DataFrame,
    component_q: pd.Series,
    weight: float,
    component_utilization: pd.Series,
) -> pd.DataFrame:
    out = main.copy()
    out["nav"] = main.nav - weight * component_q + weight
    out["gross_exposure"] = (
        main.gross_exposure - weight * component_q * component_utilization
    )
    out["cash"] = out.nav - out.gross_exposure
    out["utilization"] = out.gross_exposure / out.nav
    return out


def transaction_notionals(root: Path) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    specs = {
        "MCB": (
            "mcb/accepted.parquet",
            "entry_price",
            "exit_price",
            "qty",
            "entry_date",
            "exit_date",
        ),
        "ATRDR": (
            "atrdr/accepted.parquet",
            "entry_price",
            "exit_price",
            "qty",
            "entry_date",
            "exit_date",
        ),
        "OGR": (
            "ogr/accepted.parquet",
            "entry_raw_price",
            "exit_raw_price",
            "qty",
            "entry_date",
            "exit_date",
        ),
        "IFCGR": (
            "ifcgr/accepted.parquet",
            "entry_raw_price",
            "exit_raw_price",
            "qty",
            "entry_date",
            "exit_date",
        ),
    }
    for strategy, (
        rel,
        entry_price,
        exit_price,
        qty,
        entry_date,
        exit_date,
    ) in specs.items():
        frame = read_parquet(
            root / rel, [qty, entry_price, exit_price, entry_date, exit_date]
        )
        entries = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(frame[entry_date]).dt.normalize(),
                "notional": frame[qty].abs() * frame[entry_price],
            }
        )
        exits = pd.DataFrame(
            {
                "trade_date": pd.to_datetime(frame[exit_date]).dt.normalize(),
                "notional": frame[qty].abs() * frame[exit_price],
            }
        )
        result[strategy] = (
            pd.concat([entries, exits])
            .groupby("trade_date", as_index=False)
            .notional.sum()
        )
    smv6 = read_parquet(
        root / "smv6/local_execution_events.parquet",
        ["trade_date", "filled_delta_qty", "market_price"],
    )
    smv6 = smv6.loc[smv6.filled_delta_qty.notna() & smv6.filled_delta_qty.ne(0)].copy()
    smv6["trade_date"] = pd.to_datetime(smv6.trade_date).dt.normalize()
    smv6["notional"] = smv6.filled_delta_qty.abs() * smv6.market_price
    result["SMV6"] = smv6.groupby("trade_date", as_index=False).notional.sum()
    return result


def fixed_cost_stress(
    account: pd.DataFrame,
    notionals: pd.DataFrame,
    dates: pd.DatetimeIndex,
    extra_bps: float = 20,
) -> tuple[pd.Series, int]:
    base = float(account.loc[dates[0], "nav"])
    costs = notionals.copy()
    costs["trade_date"] = pd.to_datetime(costs.trade_date).dt.normalize()
    costs = costs.loc[costs.trade_date.gt(dates[0]) & costs.trade_date.le(dates[-1])]
    daily = costs.groupby("trade_date").notional.sum().reindex(dates, fill_value=0.0)
    cumulative = daily.cumsum() * extra_bps / 10_000 / base
    q = account.loc[dates, "nav"] / base
    stressed = q - cumulative
    cash = account.loc[dates, "cash"] / base
    insufficient_days = int((cash - cumulative < -EPS).sum())
    return stressed, insufficient_days


def trade_profit(frame: pd.DataFrame) -> pd.Series:
    if not {"entry_outlay", "qty"}.issubset(frame.columns):
        return pd.Series(np.nan, index=frame.index)
    if "exit_price" in frame:
        return frame.qty * frame.exit_price * 0.998 - frame.entry_outlay
    if "exit_raw_price" in frame:
        dividend = pd.Series(0.0, index=frame.index)
        if "cash_events_json" in frame:
            dividend = frame.cash_events_json.fillna("[]").map(
                lambda value: sum(
                    float(event["cash_per_share"]) for event in json.loads(value)
                )
            )
        return (
            frame.qty * (frame.exit_raw_price * 0.998 + dividend) - frame.entry_outlay
        )
    if "entry_outlay" in frame:
        return frame.entry_outlay.astype(float) * frame.net_return.astype(float)
    return pd.Series(np.nan, index=frame.index)


def profit_concentration(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for strategy, source in frames.items():
        frame = source.copy()
        frame["realized_profit"] = trade_profit(frame)
        frame["signal_date"] = pd.to_datetime(frame.signal_date).dt.normalize()
        positive_total = frame.realized_profit.clip(lower=0).sum()
        for dimension, column in (
            ("SIGNAL_DATE", "signal_date"),
            ("SECURITY", "symbol"),
        ):
            grouped = (
                frame.groupby(column, dropna=False)
                .realized_profit.sum()
                .sort_values(ascending=False)
            )
            for rank, (key, profit) in enumerate(grouped.head(5).items(), 1):
                rows.append(
                    {
                        "strategy": strategy,
                        "dimension": dimension,
                        "rank": rank,
                        "key": key.date().isoformat()
                        if isinstance(key, pd.Timestamp)
                        else str(key),
                        "realized_profit": profit,
                        "share_of_all_positive_trade_profit": (
                            max(float(profit), 0.0) / positive_total
                            if positive_total > EPS
                            else math.nan
                        ),
                        "profit_definition": "account-cash realized PnL; OGR includes cash distributions",
                    }
                )
    return pd.DataFrame(rows)


def trade_summary(
    frame: pd.DataFrame,
    signal_count: int,
    signal_days: int,
    immature_count: int,
    capital_rejections: int,
    return_unit: str = "TRADE",
) -> dict[str, object]:
    complete = frame.loc[frame.net_return.notna()].copy()
    profit = trade_profit(complete)
    by_day = (
        complete.assign(profit=profit)
        .groupby(pd.to_datetime(complete.signal_date).dt.normalize())
        .profit.sum()
    )
    positive_profit = profit.clip(lower=0)
    denom = positive_profit.sum()
    by_symbol = (
        complete.assign(positive_profit=positive_profit)
        .groupby("symbol")
        .positive_profit.sum()
    )
    return {
        "signal_count": signal_count,
        "independent_signal_days": signal_days,
        "funded_trade_count": len(frame),
        "completed_count": len(complete),
        "immature_or_unavailable_count": immature_count,
        "mean_native_net_return": complete.net_return.mean(),
        "median_native_net_return": complete.net_return.median(),
        "win_rate": complete.net_return.gt(0).mean(),
        "mean_holding_sessions": complete.holding_sessions.mean(),
        "severe_loss_count": int(complete.net_return.le(SEVERE_LOSS).sum()),
        "capital_rejection_count": capital_rejections,
        "top5_signal_day_positive_profit_share": by_day.nlargest(5).clip(lower=0).sum()
        / denom
        if denom > EPS
        else math.nan,
        "top5_security_positive_profit_share": by_symbol.nlargest(5).sum() / denom
        if denom > EPS
        else math.nan,
        "return_unit": return_unit,
    }


def overlap_group_rows(
    a: pd.DataFrame,
    b: pd.DataFrame,
    a_name: str,
    b_name: str,
    a_returns: pd.DataFrame,
    b_returns: pd.DataFrame,
) -> list[dict[str, object]]:
    a = a.copy()
    b = b.copy()
    for frame in (a, b):
        frame["signal_date"] = pd.to_datetime(frame.signal_date).dt.normalize()
        frame["event_key"] = (
            frame.symbol.astype(str) + "|" + frame.signal_date.dt.strftime("%Y-%m-%d")
        )
        assert_unique(frame, ["event_key"], f"{a_name}/{b_name} event key")
    aset, bset = set(a.event_key), set(b.event_key)
    shared, only_a, only_b = aset & bset, aset - bset, bset - aset
    rows: list[dict[str, object]] = []
    base = {
        "comparison": f"{a_name}_VS_{b_name}",
        "overlap_key": "SYMBOL_SIGNAL_DATE",
        "a_in_b": len(shared) / len(aset),
        "b_in_a": len(shared) / len(bset),
        "jaccard": len(shared) / len(aset | bset),
    }
    for group, keys in (
        ("SHARED", shared),
        (f"ONLY_{a_name}", only_a),
        (f"ONLY_{b_name}", only_b),
    ):
        for source, returns in ((a_name, a_returns), (b_name, b_returns)):
            data = returns.copy()
            data["signal_date"] = pd.to_datetime(data.signal_date).dt.normalize()
            data["event_key"] = (
                data.symbol.astype(str) + "|" + data.signal_date.dt.strftime("%Y-%m-%d")
            )
            data = data.loc[data.event_key.isin(keys) & data.net_return.notna()]
            by_day = data.groupby("signal_date").net_return.mean()
            source_events = (
                a.loc[a.event_key.isin(keys)]
                if source == a_name
                else b.loc[b.event_key.isin(keys)]
            )
            rows.append(
                {
                    **base,
                    "group": group,
                    "return_source": source,
                    "event_count": len(source_events),
                    "independent_dates": source_events.signal_date.nunique(),
                    "year_distribution": json.dumps(
                        source_events.signal_date.dt.year.value_counts()
                        .sort_index()
                        .to_dict()
                    ),
                    "executed_outcome_count": len(data),
                    "event_equal_return": data.net_return.mean(),
                    "signal_day_equal_return": by_day.mean(),
                    "severe_loss_count": int(data.net_return.le(SEVERE_LOSS).sum()),
                    "mean_holding_sessions": data.holding_sessions.mean(),
                }
            )
    return rows


def reject_attribution(root: Path) -> pd.DataFrame:
    rejected = read_parquet(root / "ifcgr/rejected.parquet")
    entries = read_parquet(root / "ogr/entries.parquet", ["gap_id", "entry_status"])
    trades = read_parquet(
        root / "ogr/trades.parquet",
        ["gap_id", "net_return", "holding_sessions", "exit_reason"],
    )
    data = merge_one_to_one(rejected, entries, "gap_id", "IFCGR rejected to OGR entry")
    data = merge_one_to_one(data, trades, "gap_id", "IFCGR rejected to OGR outcome")
    data["counterfactual"] = np.select(
        [
            data.entry_status.ne("EXECUTABLE_ENTRY"),
            data.net_return.isna(),
            data.net_return.le(SEVERE_LOSS),
            data.net_return.lt(0),
            data.net_return.gt(0),
        ],
        [
            "PARENT_NOT_EXECUTABLE",
            "PARENT_OUTCOME_UNAVAILABLE",
            "AVOIDED_SEVERE_LOSS",
            "AVOIDED_NEGATIVE",
            "MISSED_WINNER",
        ],
        default="FLAT",
    )
    columns = [
        "gap_id",
        "symbol",
        "signal_date",
        "entry_status",
        "net_return",
        "holding_sessions",
        "exit_reason",
        "v29r2_rejection_reason",
        "v29r2_open_risk_families",
        "counterfactual",
    ]
    return data[columns].sort_values(["signal_date", "gap_id"], kind="mergesort")


def pair_risk(
    a: pd.DataFrame, b: pd.DataFrame, a_name: str, b_name: str
) -> dict[str, object]:
    dates = a.index.intersection(b.index).sort_values()
    aa, bb = a.loc[dates], b.loc[dates]
    ra, rb = aa.nav.pct_change(fill_method=None), bb.nav.pct_change(fill_method=None)
    valid = ra.notna() & rb.notna()
    both = aa.utilization.gt(EPS) & bb.utilization.gt(EPS) & valid
    a_tail, b_tail = tail_index(ra.loc[valid]), tail_index(rb.loc[valid])

    def corr(x: pd.Series, y: pd.Series) -> float:
        return x.corr(y) if x.std(ddof=1) > 0 and y.std(ddof=1) > 0 else math.nan

    return {
        "record_type": "PAIR_RISK",
        "a": a_name,
        "b": b_name,
        "start": dates[0].date().isoformat(),
        "end": dates[-1].date().isoformat(),
        "n_days": int(valid.sum()),
        "full_day_correlation": corr(ra.loc[valid], rb.loc[valid]),
        "both_active_correlation": corr(ra.loc[both], rb.loc[both])
        if both.sum() > 1
        else math.nan,
        "both_active_return_days": int(both.sum()),
        "common_holding_days": int(
            (aa.utilization.gt(EPS) & bb.utilization.gt(EPS)).sum()
        ),
        "b_mean_on_a_worst5pct": rb.loc[a_tail].mean(),
        "a_tail_n": len(a_tail),
        "a_actual_loss_days_in_tail": int(ra.loc[a_tail].lt(0).sum()),
        "a_mean_on_b_worst5pct": ra.loc[b_tail].mean(),
        "b_tail_n": len(b_tail),
        "b_actual_loss_days_in_tail": int(rb.loc[b_tail].lt(0).sum()),
        "common_negative_ratio": ((ra.loc[valid] < 0) & (rb.loc[valid] < 0)).mean(),
        "a_tail_threshold": ra.loc[a_tail].max(),
        "b_tail_threshold": rb.loc[b_tail].max(),
        "tail_pressure_note": "TAIL_MOSTLY_CASH"
        if ra.loc[a_tail].max() >= -EPS or rb.loc[b_tail].max() >= -EPS
        else "ACTUAL_NEGATIVE_TAIL",
    }


def holding_overlap(a: pd.DataFrame, b: pd.DataFrame, dates: pd.DatetimeIndex) -> int:
    occupied: set[pd.Timestamp] = set()
    for left in a.itertuples():
        for right in b.itertuples():
            if str(left.symbol) != str(right.symbol):
                continue
            start = max(
                pd.Timestamp(left.entry_date), pd.Timestamp(right.entry_date), dates[0]
            )
            end = min(
                pd.Timestamp(left.exit_date), pd.Timestamp(right.exit_date), dates[-1]
            )
            if start < end:
                occupied.update(dates[(dates >= start) & (dates < end)])
    return len(occupied)


def bear_ogr_rows(
    root: Path, common: pd.DatetimeIndex, accounts: dict[str, pd.DataFrame]
) -> list[dict[str, object]]:
    bear = read_parquet(root / "atrdr/v27_bear_routes.parquet")
    bear_accepted = read_parquet(root / "atrdr/accepted.parquet")
    bear_accepted = bear_accepted.loc[bear_accepted.source.eq("V27_BEAR")].copy()
    ogr = read_parquet(
        root / "ogr/signals.parquet",
        ["gap_id", "symbol", "signal_date", "signal_cal_idx"],
    )
    ogr_acc = read_parquet(root / "ogr/accepted.parquet")
    calendar_position = {date: index for index, date in enumerate(common)}
    ogr_dates = pd.to_datetime(ogr.signal_date).dt.normalize()
    rows = []
    for lane, label in (
        ("BEAR_WORSENING_FAST_CAPITULATION", "ATRDR_FAST_BEAR"),
        ("BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION", "ATRDR_SLOW_BEAR"),
    ):
        route = bear.loc[bear.lane.eq(lane)].copy()
        exact = set(
            zip(
                route.symbol.astype(str),
                pd.to_datetime(route.signal_date).dt.normalize(),
            )
        )
        other = set(
            zip(ogr.symbol.astype(str), pd.to_datetime(ogr.signal_date).dt.normalize())
        )
        shared_dates = set(pd.to_datetime(route.signal_date).dt.normalize()) & set(
            pd.to_datetime(ogr.signal_date).dt.normalize()
        )
        near = 0
        for row in route.itertuples():
            route_date = pd.Timestamp(row.signal_date).normalize()
            route_pos = calendar_position.get(route_date)
            if route_pos is None:
                continue
            other_pos = ogr_dates.map(calendar_position)
            near += int(
                (
                    (ogr.symbol.astype(str) == str(row.symbol))
                    & other_pos.notna()
                    & other_pos.sub(route_pos).abs().le(3)
                ).any()
            )
        route_acc = bear_accepted.loc[bear_accepted.lane.eq(lane)]
        same_holding = holding_overlap(route_acc, ogr_acc, common)
        rows.append(
            {
                "comparison": f"{label}_VS_OGR",
                "group": "OVERLAP_DIAGNOSTIC",
                "event_count": len(route),
                "ogr_event_count": len(ogr),
                "exact_symbol_signal_date": len(exact & other),
                "shared_signal_dates": len(shared_dates),
                "same_symbol_within_3_sessions": near,
                "same_security_holding_days": same_holding,
                "route_accepted_count": len(route_acc),
                "route_native_profit": trade_profit(route_acc).sum(),
                "route_mean_net_return": route_acc.net_return.mean(),
                "route_severe_loss_count": int(
                    route_acc.net_return.le(SEVERE_LOSS).sum()
                ),
                "route_year_distribution": json.dumps(
                    pd.to_datetime(route_acc.signal_date)
                    .dt.year.value_counts()
                    .sort_index()
                    .to_dict()
                ),
                "simultaneous_account_exposure_days": int(
                    (
                        accounts["ATRDR"].loc[common].utilization.gt(EPS)
                        & accounts["OGR"].loc[common].utilization.gt(EPS)
                    ).sum()
                ),
                "route_nav_status": "NOT_ESTIMABLE_NO_ROUTE_ACCOUNT",
            }
        )
    return rows


def drawdown_episodes(nav: pd.Series) -> pd.DataFrame:
    values = nav.astype(float)
    peak_date, peak_value = values.index[0], values.iloc[0]
    trough_date, trough_value = peak_date, peak_value
    active = False
    rows = []
    for date, value in values.iloc[1:].items():
        if value >= peak_value:
            if active:
                rows.append(
                    {
                        "peak": peak_date,
                        "trough": trough_date,
                        "recovery": date,
                        "depth": trough_value / peak_value - 1,
                        "recovered": True,
                    }
                )
            peak_date, peak_value = date, value
            trough_date, trough_value, active = date, value, False
        else:
            active = True
            if value < trough_value:
                trough_date, trough_value = date, value
    if active:
        rows.append(
            {
                "peak": peak_date,
                "trough": trough_date,
                "recovery": values.index[-1],
                "depth": trough_value / peak_value - 1,
                "recovered": False,
            }
        )
    return (
        pd.DataFrame(rows).sort_values("depth", kind="mergesort").reset_index(drop=True)
        if rows
        else pd.DataFrame()
    )


def smv6_difficulty_rows(
    accounts: dict[str, pd.DataFrame], common: pd.DatetimeIndex
) -> list[dict[str, object]]:
    stock = portfolio_frame(
        accounts, {"ATRDR": 1 / 3, "MCB": 1 / 3, "OGR": 1 / 3}, common
    )
    smv6 = accounts["SMV6"].loc[common]
    rows: list[dict[str, object]] = []
    pair = pair_risk(stock, smv6, "STOCK_REFERENCE", "SMV6")
    rows.append(
        {"comparison": "SMV6_VS_STOCK_REFERENCE", "group": "DIFFICULTY_SUMMARY", **pair}
    )
    episodes = drawdown_episodes(stock.nav).head(3)
    for rank, episode in enumerate(episodes.itertuples(), 1):
        period = common[(common >= episode.peak) & (common <= episode.recovery)]
        to_trough = common[(common >= episode.peak) & (common <= episode.trough)]
        rows.append(
            {
                "comparison": "SMV6_VS_STOCK_REFERENCE",
                "group": f"DRAWDOWN_{rank}",
                "peak": episode.peak.date().isoformat(),
                "trough": episode.trough.date().isoformat(),
                "recovery": episode.recovery.date().isoformat(),
                "recovered": episode.recovered,
                "stock_depth": episode.depth,
                "smv6_peak_to_trough_return": smv6.loc[to_trough].nav.iloc[-1]
                / smv6.loc[to_trough].nav.iloc[0]
                - 1,
                "smv6_full_episode_return": smv6.loc[period].nav.iloc[-1]
                / smv6.loc[period].nav.iloc[0]
                - 1,
                "episode_sessions": len(period),
            }
        )
    return rows


def inventory(
    config: dict[str, object],
    output: Path,
    signal_start: pd.Timestamp,
    signal_end: pd.Timestamp,
    asof: pd.Timestamp,
) -> None:
    root = Path(config["sealed_output_root"])
    if not root.is_dir():
        raise FileNotFoundError(root)
    rows = []
    hash_cache: dict[Path, str] = {}
    for name, raw in config["inputs"].items():
        path = Path(raw)
        if not path.exists():
            raise FileNotFoundError(path)
        digest = "DIRECTORY_REGISTERED_NOT_REHASHED"
        if path.is_file():
            digest = hash_cache.setdefault(path.resolve(), sha256(path))
        rows.append(
            {
                "kind": "RAW_INPUT",
                "logical_name": name,
                "path": str(path),
                "sha256": digest,
                "bytes": path.stat().st_size if path.is_file() else "NA",
                "producing_commit": "EXTERNAL_REGISTERED_ASSET",
            }
        )
    for path in sorted(root.glob("**/*")):
        if path.is_file() and (path.suffix in (".parquet", ".json")):
            rows.append(
                {
                    "kind": "SEALED_STANDALONE_OUTPUT",
                    "logical_name": str(path.relative_to(root)),
                    "path": str(path),
                    "sha256": sha256(path),
                    "bytes": path.stat().st_size,
                    "producing_commit": config["standalone_baseline"],
                }
            )
    manifest = {
        "research_contract": {
            "signal_start": str(signal_start.date()),
            "signal_end": str(signal_end.date()),
            "as_of": str(asof.date()),
            "portfolio_type": "HISTORICAL_SLEEVE_NAV_COMPOSITE",
        },
        "standalone_baseline": config["standalone_baseline"],
        "integration_provenance_only": config["integration_provenance"],
        "assets": rows,
    }
    (output / "input_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )

    coverage = [
        [
            "MCB",
            "HISTORICAL",
            "2013 warm-up implied by registered PIT daily",
            "2014-01-02/2023-11-20 V53 mother",
            "2014-02-12/2023-11-20 V72",
            "2014-02-13/2023-12-13",
            1.0,
            "EMPTY",
            "NO",
            "2023-12-13",
            "2023-12-13",
            "DEVELOPMENT_AND_CONSUMED_VALIDATION",
            "UNKNOWN",
            "",
        ],
        [
            "OGR",
            "HISTORICAL",
            "2013-2016 prior history implied",
            "2017-01-03/2021-12-31 V13 candidates",
            "2018-02-22/2021-11-15 V28R2",
            "2018-01-02/2021-12-15",
            1.0,
            "EMPTY",
            "NO",
            "2021-12-15",
            "2021-12-15",
            "DEVELOPMENT_AND_CONSUMED_VALIDATION",
            "UNKNOWN",
            "COMMON_WINDOW_LIMITED",
        ],
        [
            "IFCGR",
            "HISTORICAL",
            "inherits same-run OGR warm-up",
            "2017-01-03/2021-12-31 OGR parents",
            "2018-02-22/2021-11-15 keep-reject",
            "2018-01-02/2021-12-15",
            1.0,
            "EMPTY",
            "NO",
            "2021-12-15",
            "2021-12-15",
            "DEVELOPMENT_AND_CONSUMED_VALIDATION_PIT_B",
            "UNKNOWN",
            "COMMON_WINDOW_LIMITED",
        ],
        [
            "ATRDR",
            "HISTORICAL",
            "registered PIT history before first 2014 signals",
            "2014-01-02/2023-12-29 route mothers",
            "2014-01-16/2023-11-22 processed routes",
            "2014-01-03/2023-12-29",
            1.0,
            "EMPTY",
            "NO",
            "2023-12-29",
            "2023-12-29",
            "DEVELOPMENT_AND_CONSUMED_VALIDATION",
            "UNKNOWN",
            "",
        ],
        [
            "ATRDR",
            "POST_2024_2025_RESET",
            "2022-01-04 history start",
            "2024-01-01/2025-12-31",
            "2024-01-01/2025-12-31",
            f"2024-01-02/{min(asof, pd.Timestamp('2026-03-31')).date()}",
            1.0,
            "EMPTY",
            "YES",
            "2026-03-31",
            "2026-03-31",
            "CONSUMED_VALIDATION",
            "UNKNOWN",
            "INDEPENDENT_RESET_DO_NOT_CONCAT",
        ],
        [
            "ATRDR",
            "POST_2026_RESET",
            "2022-01-04 history start",
            f"2026-01-01/{signal_end.date()}",
            f"2026-01-01/{min(signal_end, asof).date()}",
            f"2026-01-05/{asof.date()}",
            1.0,
            "EMPTY",
            "YES",
            "2026-08-12",
            f"{asof.date()} cut; mature outcomes only",
            "CONSUMED_VALIDATION",
            "UNKNOWN",
            "INDEPENDENT_RESET_DO_NOT_CONCAT",
        ],
        [
            "SMV6",
            "LOCAL_CASH_LOT",
            "strategy-native ETF lookbacks",
            "2013-04-01/2026-08-28 callbacks",
            f"2013-05-21/{min(signal_end, asof).date()}",
            f"2013-04-01/{asof.date()}",
            1_000_000,
            "EMPTY",
            "NO",
            "2026-08-28",
            f"{asof.date()}",
            "CONSUMED_VALIDATION_LOCAL_SEMANTICS",
            "UNKNOWN",
            "NATIVE_PLATFORM_EQUIVALENCE_UNVERIFIED",
        ],
    ]
    columns = [
        "strategy",
        "account_segment",
        "feature_warmup",
        "mother_candidate_scan",
        "signal_processing",
        "account_interval",
        "initial_capital",
        "initial_holdings",
        "independent_reset",
        "market_data_end",
        "mature_outcome_end",
        "evidence_stage",
        "independent_oos_status",
        "limitations",
    ]
    write_csv(pd.DataFrame(coverage, columns=columns), output / "coverage_manifest.csv")
    semantic = """# Semantic Preflight

所有策略统一约束：`available_at <= decision_at`；截至日后退出、原因、MAE/MFE不进入结果。Cause/State/Trigger/Outcome 是描述层，不构造新择时规则。

## MCB
ECONOMIC_SEQUENCE：跨板确认后的突破需求；CAUSAL_BACKGROUND：收盘完成的市场/行业状态；STATE_VARIABLES：市场与行业20/60日强弱、广度和个股相对强度；EVENT_FORMATION_TIME：信号日收盘；CONFIRMATION_TRIGGER：冻结 V72 跨板确认；ENTRY_TIME：下一合法交易日开盘；OUTCOME_START_TIME：成交后；POSSIBLE_SEMANTIC_AMBIGUITIES：V53 行为重建 provenance 不等于原始源码；CHOSEN_TIME_ANCHORS：signal_date 收盘决策、entry_date 开盘成交。

## OGR
ECONOMIC_SEQUENCE：历史缺口下方供给释放后的有序需求修复；CAUSAL_BACKGROUND：PIT 日线、分钟、成交额与公司行动；STATE_VARIABLES：缺口区间、VAP 密度、回升、流动性与成交额；EVENT_FORMATION_TIME：信号日15:00；CONFIRMATION_TRIGGER：V28R2 有序成交额门；ENTRY_TIME：信号后首个合法分钟开盘；OUTCOME_START_TIME：成交后；POSSIBLE_SEMANTIC_AMBIGUITIES：事件回报与80槽位账户回报不是同一量；CHOSEN_TIME_ANCHORS：signal_time、entry_time、exit_time。

## IFCGR
ECONOMIC_SEQUENCE：OGR 机会叠加发行人事实冷却；CAUSAL_BACKGROUND：同轮 OGR 父候选及当时可得官方公告；STATE_VARIABLES：开放风险事实及冷却窗口；EVENT_FORMATION_TIME：沿用 OGR；CONFIRMATION_TRIGGER：PIT-B keep/reject；ENTRY_TIME/OUTCOME_START_TIME：沿用 OGR 反事实和执行；POSSIBLE_SEMANTIC_AMBIGUITIES：官方当前枚举缺少完整修订/删除历史，永久保持 PIT-B；CHOSEN_TIME_ANCHORS：公告 causal_available_at 不晚于 OGR decision_at。

## ATRDR（Bull / Fast Bear / Slow Bear）
ECONOMIC_SEQUENCE：市场状态路由后分别捕捉牛市参与扩散、熊市快速投降和慢速供给衰竭；CAUSAL_BACKGROUND：完成收盘的市场状态与 PIT 日线；STATE_VARIABLES：市场20/60日中位收益、广度、个股/行业趋势、换手与库存代理；EVENT_FORMATION_TIME：信号日收盘；CONFIRMATION_TRIGGER：冻结路由与仲裁；ENTRY_TIME：下一合法开盘；OUTCOME_START_TIME：成交后；POSSIBLE_SEMANTIC_AMBIGUITIES：历史、2024–2025、2026账户独立初始化，不能连接；OAI 与 post-2023 行为重建 provenance 保留；CHOSEN_TIME_ANCHORS：各段自身 signal/entry/exit，组合只用连续历史段。

## SMV6
ECONOMIC_SEQUENCE：ETF 压缩后点火并按冻结回调调仓；CAUSAL_BACKGROUND：QMT 日线、关键分钟和成交可用性；STATE_VARIABLES：冻结回调内部状态、现金、整手和持仓；EVENT_FORMATION_TIME：before_trading/signal；CONFIRMATION_TRIGGER：冻结 callback；ENTRY_TIME：本地平台 open/close fill；OUTCOME_START_TIME：本地成交后；POSSIBLE_SEMANTIC_AMBIGUITIES：本地现金整手语义不等于原生 SuperMind 券商等价；CHOSEN_TIME_ANCHORS：local_execution_events 与每日账户，截至日切断后续事件。
"""
    (output / "semantic_preflight.md").write_text(semantic)


def analysis(
    config: dict[str, object], output: Path, asof: pd.Timestamp
) -> dict[str, object]:
    root = Path(config["sealed_output_root"])
    accounts, atrdr_segments = load_accounts(root, config["inputs"], asof)
    common = common_dates(accounts, ("ATRDR", "MCB", "OGR", "IFCGR", "SMV6"))

    mcb_signals = read_parquet(root / "mcb/signals.parquet")
    mcb_trades_all = read_parquet(root / "mcb/trades.parquet")
    mcb_trades, mcb_unresolved = asof_trade_view(mcb_trades_all, asof)
    mcb_acc = read_parquet(root / "mcb/accepted.parquet")
    atrdr_union = read_parquet(root / "atrdr/source_completed_trades.parquet")
    atrdr_acc = read_parquet(root / "atrdr/accepted.parquet")
    ogr_signals = read_parquet(root / "ogr/signals.parquet")
    ogr_trades = read_parquet(root / "ogr/trades.parquet")
    ogr_acc = read_parquet(root / "ogr/accepted.parquet")
    ifcgr_kept = read_parquet(root / "ifcgr/kept.parquet")
    ifcgr_trades = read_parquet(root / "ifcgr/trades.parquet")
    ifcgr_acc = read_parquet(root / "ifcgr/accepted.parquet")
    ogr_ledger = read_parquet(root / "ogr/skipped.parquet")
    ifcgr_ledger = read_parquet(root / "ifcgr/skipped.parquet")
    skips = {
        "MCB": len(read_parquet(root / "mcb/skipped.parquet")),
        "ATRDR": len(read_parquet(root / "atrdr/skipped.parquet")),
        "OGR": int(ogr_ledger.status.ne("EXECUTED").sum()),
        "IFCGR": int(ifcgr_ledger.status.ne("EXECUTED").sum()),
    }

    trade_rows = {
        "MCB": trade_summary(
            mcb_acc,
            len(mcb_signals),
            pd.to_datetime(mcb_signals.signal_date).nunique(),
            len(mcb_unresolved),
            skips["MCB"],
        ),
        "ATRDR": trade_summary(
            atrdr_acc,
            len(atrdr_union),
            pd.to_datetime(atrdr_union.signal_date).nunique(),
            0,
            skips["ATRDR"],
        ),
        "OGR": trade_summary(
            ogr_acc,
            len(ogr_signals),
            pd.to_datetime(ogr_signals.signal_date).nunique(),
            len(ogr_signals) - len(ogr_trades),
            skips["OGR"],
        ),
        "IFCGR": trade_summary(
            ifcgr_acc,
            len(ifcgr_kept),
            pd.to_datetime(ifcgr_kept.signal_date).nunique(),
            len(ifcgr_kept) - len(ifcgr_trades),
            skips["IFCGR"],
        ),
    }
    local = read_parquet(root / "smv6/local_execution_events.parquet")
    local = local.loc[pd.to_datetime(local.trade_date) <= asof]
    sells = local.loc[
        local.event_type.eq("SELL_FILLED") & local.holding_pnl_pct.notna()
    ].copy()
    smv6_events = read_parquet(root / "smv6/events.parquet")
    smv6_events = smv6_events.loc[pd.to_datetime(smv6_events.signal_date) <= asof]
    trade_rows["SMV6"] = {
        "signal_count": len(smv6_events),
        "independent_signal_days": pd.to_datetime(smv6_events.signal_date).nunique(),
        "funded_trade_count": len(sells),
        "completed_count": len(sells),
        "immature_or_unavailable_count": int(
            accounts["SMV6"].iloc[-1].active_positions
        ),
        "mean_native_net_return": sells.holding_pnl_pct.mean(),
        "median_native_net_return": sells.holding_pnl_pct.median(),
        "win_rate": sells.holding_pnl_pct.gt(0).mean(),
        "mean_holding_sessions": math.nan,
        "severe_loss_count": int(sells.holding_pnl_pct.le(SEVERE_LOSS).sum()),
        "capital_rejection_count": int(local.reject_reason.notna().sum()),
        "top5_signal_day_positive_profit_share": math.nan,
        "top5_security_positive_profit_share": math.nan,
        "return_unit": "FINAL_SELL_FILL_HOLDING_PNL_NOT_ROUNDTRIP_TRADE",
    }
    summary = []
    all_notionals = transaction_notionals(root)
    for name, account in accounts.items():
        initial_nav = 1_000_000.0 if name == "SMV6" else 1.0
        metrics = account_metrics(account, initial_nav=initial_nav)
        notionals = all_notionals[name]
        total_notional = notionals.loc[
            pd.to_datetime(notionals.trade_date).le(asof), "notional"
        ].sum()
        metrics["two_way_turnover_over_mean_nav"] = total_notional / account.nav.mean()
        summary.append(
            {
                "strategy": name,
                "account_segment": "PRIMARY_CONTINUOUS",
                **trade_rows[name],
                **metrics,
                "native_cost_note": {
                    "OGR": "20bp_each_side",
                    "IFCGR": "20bp_each_side",
                    "SMV6": "20bp_commission_plus_16bp_roundtrip_slippage",
                    "MCB": "20bp_each_side",
                    "ATRDR": "20bp_each_side",
                }[name],
            }
        )
    for label, account in atrdr_segments.items():
        if label == "ATRDR_HISTORICAL":
            continue
        summary.append(
            {
                "strategy": "ATRDR",
                "account_segment": label,
                **account_metrics(account, initial_nav=1.0),
                "signal_count": "SEE_COVERAGE",
                "funded_trade_count": "SEE_SEALED_SEGMENT",
                "native_cost_note": "20bp_each_side; independent reset; not concatenated",
            }
        )
    strategy_summary = pd.DataFrame(summary)
    write_csv(strategy_summary, output / "strategy_summary.csv")
    write_csv(
        profit_concentration(
            {"MCB": mcb_acc, "ATRDR": atrdr_acc, "OGR": ogr_acc, "IFCGR": ifcgr_acc}
        ),
        output / "profit_concentration.csv",
    )

    family_rows = []
    bull = read_parquet(root / "atrdr/bull_mother.parquet")
    bull_returns = read_parquet(root / "atrdr/bull_outcomes.parquet")
    family_rows.extend(
        overlap_group_rows(
            bull, mcb_signals, "ATRDR_BULL", "MCB", bull_returns, mcb_trades
        )
    )
    bull_acc = atrdr_acc.loc[atrdr_acc.source.eq("V29_SIMPLE_BULL")].copy()
    for frame in (bull_acc, mcb_acc):
        frame["event_key"] = (
            frame.symbol.astype(str)
            + "|"
            + pd.to_datetime(frame.signal_date).dt.strftime("%Y-%m-%d")
        )
    executed = bull_acc.merge(
        mcb_acc, on="event_key", suffixes=("_atrdr", "_mcb"), validate="one_to_one"
    )
    same_execution = (
        pd.to_datetime(executed.entry_date_atrdr).eq(
            pd.to_datetime(executed.entry_date_mcb)
        )
        & pd.to_datetime(executed.exit_date_atrdr).eq(
            pd.to_datetime(executed.exit_date_mcb)
        )
        & executed.entry_price_atrdr.sub(executed.entry_price_mcb).abs().le(EPS)
        & executed.exit_price_atrdr.sub(executed.exit_price_mcb).abs().le(EPS)
        & executed.net_return_atrdr.sub(executed.net_return_mcb).abs().le(EPS)
    )
    family_rows.append(
        {
            "comparison": "ATRDR_BULL_VS_MCB",
            "group": "FUNDED_EXECUTION_OVERLAP",
            "event_count": len(executed),
            "atrdr_bull_funded": len(bull_acc),
            "mcb_funded": len(mcb_acc),
            "same_entry_exit_cost_count": int(same_execution.sum()),
            "execution_note": "same T15/H15 and 20bp each side where exact; capacity may differ",
        }
    )
    rejects = reject_attribution(root)
    write_csv(rejects, output / "ifcgr_reject_attribution.csv")
    family_rows.append(
        {
            "comparison": "OGR_VS_IFCGR",
            "group": "REJECT_ATTRIBUTION",
            "event_count": len(rejects),
            "parent_executable": int(rejects.entry_status.eq("EXECUTABLE_ENTRY").sum()),
            "avoided_negative": int(
                rejects.counterfactual.isin(
                    ["AVOIDED_NEGATIVE", "AVOIDED_SEVERE_LOSS"]
                ).sum()
            ),
            "avoided_severe": int(
                rejects.counterfactual.eq("AVOIDED_SEVERE_LOSS").sum()
            ),
            "missed_winner": int(rejects.counterfactual.eq("MISSED_WINNER").sum()),
            "unavailable_or_unexecutable": int(
                rejects.counterfactual.isin(
                    ["PARENT_NOT_EXECUTABLE", "PARENT_OUTCOME_UNAVAILABLE"]
                ).sum()
            ),
            "counterfactual_mean_return": rejects.net_return.mean(),
            "evidence": "PIT_B",
        }
    )
    ogr_account_metrics = account_metrics(accounts["OGR"].loc[common])
    ifcgr_account_metrics = account_metrics(accounts["IFCGR"].loc[common])
    family_rows.append(
        {
            "comparison": "OGR_VS_IFCGR",
            "group": "SAME_CAPITAL_ACCOUNT",
            "ogr_funded": len(ogr_acc),
            "ifcgr_funded": len(ifcgr_acc),
            "actual_substitute_fills": len(set(ifcgr_acc.gap_id) - set(ogr_acc.gap_id)),
            "filtered_ogr_fills": len(set(ogr_acc.gap_id) - set(ifcgr_acc.gap_id)),
            "ogr_total_return": ogr_account_metrics["total_return"],
            "ifcgr_total_return": ifcgr_account_metrics["total_return"],
            "ogr_max_drawdown": ogr_account_metrics["max_drawdown"],
            "ifcgr_max_drawdown": ifcgr_account_metrics["max_drawdown"],
            "ogr_avg_utilization": ogr_account_metrics["avg_utilization"],
            "ifcgr_avg_utilization": ifcgr_account_metrics["avg_utilization"],
            "window": f"{common[0].date()}/{common[-1].date()}",
        }
    )
    family_rows.extend(bear_ogr_rows(root, common, accounts))
    family_rows.extend(smv6_difficulty_rows(accounts, common))
    write_csv(pd.DataFrame(family_rows), output / "family_analysis.csv")

    risk_rows = []
    for i, a in enumerate(STRATEGIES):
        for b in STRATEGIES[i + 1 :]:
            risk_rows.append(pair_risk(accounts[a], accounts[b], a, b))

    portfolio_specs = {
        "P1": {"ATRDR": 0.25, "MCB": 0.25, "OGR": 0.25, "SMV6": 0.25},
        "P2": {"ATRDR": 0.25, "MCB": 0.25, "IFCGR": 0.25, "SMV6": 0.25},
        "R1": {"ATRDR": 0.50, "OGR": 0.25, "SMV6": 0.25},
        "R2": {"ATRDR": 0.50, "IFCGR": 0.25, "SMV6": 0.25},
    }
    portfolios = {
        name: portfolio_frame(accounts, weights, common)
        for name, weights in portfolio_specs.items()
    }
    portfolio_rows = []
    for name, frame in portfolios.items():
        portfolio_rows.append(
            {
                "portfolio": name,
                "control_type": "PRIMARY"
                if name.startswith("P")
                else "MCB_BUDGET_TO_ATRDR",
                "components": json.dumps(portfolio_specs[name], sort_keys=True),
                **account_metrics(frame),
            }
        )
    for parent in ("P1", "P2"):
        weights = portfolio_specs[parent]
        for strategy, weight in weights.items():
            q = (
                accounts[strategy].loc[common, "nav"]
                / accounts[strategy].loc[common, "nav"].iloc[0]
            )
            control = leave_cash(
                portfolios[parent],
                q,
                weight,
                accounts[strategy].loc[common, "utilization"],
            )
            label = f"{parent}_WITHOUT_{strategy}_LEAVE_CASH"
            metrics = account_metrics(control)
            portfolio_rows.append(
                {
                    "portfolio": label,
                    "control_type": "DELETE_LEAVE_CASH",
                    "parent": parent,
                    "removed": strategy,
                    "components": "locked_parent_window",
                    **metrics,
                }
            )
            parent_metrics = account_metrics(portfolios[parent])
            risk_rows.append(
                {
                    "record_type": "DELETE_LEAVE_CASH_DELTA",
                    "a": parent,
                    "b": label,
                    **{
                        f"delta_{key}": parent_metrics[key] - metrics[key]
                        for key in (
                            "total_return",
                            "cagr",
                            "max_drawdown",
                            "sharpe",
                            "worst_5pct_mean",
                            "avg_utilization",
                        )
                    },
                }
            )

    notionals = all_notionals
    stressed_q: dict[str, pd.Series] = {}
    stress_cash_breaches: dict[str, int] = {}
    for strategy in STRATEGIES:
        stressed_q[strategy], stress_cash_breaches[strategy] = fixed_cost_stress(
            accounts[strategy], notionals[strategy], common
        )
    for name, weights in portfolio_specs.items():
        stressed = portfolios[name].copy()
        stressed["nav"] = sum(
            weights[strategy] * stressed_q[strategy] for strategy in weights
        )
        original_gross = portfolios[name].gross_exposure
        stressed["gross_exposure"] = original_gross
        stressed["cash"] = stressed.nav - stressed.gross_exposure
        stressed["utilization"] = stressed.gross_exposure / stressed.nav
        metrics = account_metrics(stressed)
        portfolio_rows.append(
            {
                "portfolio": f"{name}_EXTRA_20BP_PER_FILL",
                "control_type": "FIXED_TRADE_ADDITIONAL_COST_STRESS",
                "parent": name,
                "components": json.dumps(weights, sort_keys=True),
                "fixed_path_cash_insufficiency_days": sum(
                    stress_cash_breaches[s] for s in weights
                ),
                "cash_insufficiency_by_strategy": json.dumps(
                    {s: stress_cash_breaches[s] for s in weights}, sort_keys=True
                ),
                **metrics,
            }
        )
        base = account_metrics(portfolios[name])
        risk_rows.append(
            {
                "record_type": "COST_STRESS_DELTA",
                "a": name,
                "b": f"{name}_EXTRA_20BP_PER_FILL",
                "delta_total_return": metrics["total_return"] - base["total_return"],
                "delta_cagr": metrics["cagr"] - base["cagr"],
                "delta_max_drawdown": metrics["max_drawdown"] - base["max_drawdown"],
                "delta_sharpe": metrics["sharpe"] - base["sharpe"],
            }
        )
    portfolio_comparison = pd.DataFrame(portfolio_rows)
    write_csv(portfolio_comparison, output / "portfolio_comparison.csv")
    write_csv(pd.DataFrame(risk_rows), output / "risk_and_capital.csv")

    nav_export = pd.DataFrame(index=common)
    for name in portfolio_specs:
        nav_export[name] = portfolios[name].nav
        nav_export[f"{name}_drawdown"] = (
            portfolios[name].nav / portfolios[name].nav.cummax() - 1
        )
    nav_export.index.name = "trade_date"
    write_csv(nav_export.reset_index(), output / "portfolio_nav_and_drawdown.csv")
    try:
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
        for name in ("P1", "P2", "R1", "R2"):
            axes[0].plot(nav_export.index, nav_export[name], label=name)
            axes[1].plot(nav_export.index, nav_export[f"{name}_drawdown"], label=name)
        axes[0].set_ylabel("Unit NAV")
        axes[1].set_ylabel("Drawdown")
        axes[0].legend(ncol=4)
        axes[1].legend(ncol=4)
        fig.tight_layout()
        fig.savefig(output / "portfolio_nav_and_drawdown.png", dpi=150)
        plt.close(fig)
    except ImportError:
        pass

    p = portfolio_comparison.set_index("portfolio")
    p1, p2, r1, r2 = (p.loc[name] for name in ("P1", "P2", "R1", "R2"))
    mcb_shared = len(
        set(zip(pd.to_datetime(bull.signal_date).dt.normalize(), bull.symbol))
        & set(
            zip(
                pd.to_datetime(mcb_signals.signal_date).dt.normalize(),
                mcb_signals.symbol,
            )
        )
    )
    mcb_unique = len(mcb_signals) - mcb_shared
    mcb_label = "REDUNDANT_EXPOSURE | CAPITAL_INEFFICIENT"
    gap_delta = p2.total_return - p1.total_return
    gap_label = "OGR CORE_CANDIDATE | IFCGR INSUFFICIENT_EVIDENCE"
    difficulty = next(
        row for row in family_rows if row.get("group") == "DIFFICULTY_SUMMARY"
    )
    smv6_label = (
        "RETURN_COMPLEMENT_CANDIDATE | DIFFICULTY_DIVERSIFICATION_INSUFFICIENT_EVIDENCE"
    )
    primary = "R1"
    decisions = pd.DataFrame(
        [
            {
                "question": "MCB_INCREMENT",
                "verdict": mcb_label,
                "evidence": f"qualified key overlap={mcb_shared}/{len(mcb_signals)} MCB; MCB_unique={mcb_unique}; P1-R1 return={p1.total_return - r1.total_return:.6f}; P2-R2 return={p2.total_return - r2.total_return:.6f}; P1-R1 MDD={p1.max_drawdown - r1.max_drawdown:.6f}; P1-R1 utilization={p1.avg_utilization - r1.avg_utilization:.6f}",
                "limitation": "no cross-strategy parent id, so symbol-date fallback; R controls are not risk matched",
            },
            {
                "question": "GAP_VARIANT",
                "verdict": gap_label,
                "evidence": f"IFCGR rejects={len(rejects)}; avoided_negative={rejects.counterfactual.str.startswith('AVOIDED').sum()}; missed_winner={rejects.counterfactual.eq('MISSED_WINNER').sum()}; substitute fills=0; P2-P1 return={gap_delta:.6f}",
                "limitation": "IFCGR remains PIT-B; only eight rejects",
            },
            {
                "question": "BEAR_OGR_RELATIONSHIP",
                "verdict": "INSUFFICIENT_EVIDENCE",
                "evidence": "see route-specific exact/date/near/holding overlaps in family_analysis.csv",
                "limitation": "no validated route NAV; account correlation is ATRDR total only",
            },
            {
                "question": "SMV6_DIVERSIFICATION",
                "verdict": smv6_label,
                "evidence": f"SMV6 mean on stock worst5%={difficulty['b_mean_on_a_worst5pct']:.6f}; tail_n={difficulty['a_tail_n']}; P1 minus leave-cash return={p1.total_return - p.loc['P1_WITHOUT_SMV6_LEAVE_CASH'].total_return:.6f}; MDD={p1.max_drawdown - p.loc['P1_WITHOUT_SMV6_LEAVE_CASH'].max_drawdown:.6f}",
                "limitation": "cash cadence contributes; native SuperMind equivalence unverified",
            },
            {
                "question": "FAMILY_STRUCTURE",
                "verdict": "ATRDR+MCB_BULL_CONFIRMATION | OGR+IFCGR_GAP | SMV6_ETF_ROTATION; BEAR-vs-OGR boundary unresolved",
                "evidence": "mechanism labels with event, holding and account diagnostics",
                "limitation": "family boundaries are descriptive, not a count of proven independent alphas",
            },
            {
                "question": "PRIMARY_RESEARCH_CANDIDATE",
                "verdict": primary,
                "evidence": f"R1 Sharpe={r1.sharpe:.4f}, return={r1.total_return:.4f}, MDD={r1.max_drawdown:.4f}; P1 Sharpe={p1.sharpe:.4f}, return={p1.total_return:.4f}, MDD={p1.max_drawdown:.4f}",
                "limitation": "R1 has higher ATRDR concentration and utilization; historical sleeve composite only",
            },
        ]
    )
    write_csv(decisions, output / "decision_matrix.csv")
    return {
        "common": common,
        "portfolios": portfolios,
        "decisions": decisions,
        "summary": strategy_summary,
        "rejects": rejects,
        "risk": pd.DataFrame(risk_rows),
        "portfolio_comparison": portfolio_comparison,
    }


def report(results: dict[str, object], output: Path) -> None:
    p = results["portfolio_comparison"].set_index("portfolio")
    decisions = results["decisions"].set_index("question")
    common = results["common"]

    def pct(value: object) -> str:
        return "NA" if pd.isna(value) else f"{float(value):.2%}"

    lines = [
        "# 五策略经济增量、共同风险与固定资金配置研究 V1",
        "",
        "## 一页决策摘要",
        "",
        f"研究状态：`COMPLETE`。主比较窗口为 **{common[0].date()} 至 {common[-1].date()}（{len(common)} 个共同交易日）**；由 OGR/IFCGR 的有效账户覆盖决定。组合类型严格为 `HISTORICAL_SLEEVE_NAV_COMPOSITE`。",
        "",
        "| 问题 | 结论 |",
        "| --- | --- |",
    ]
    for key in decisions.index:
        lines.append(
            f"| {key} | **{decisions.loc[key, 'verdict']}** — {decisions.loc[key, 'evidence']} |"
        )
    lines += [
        "",
        "## 主组合与预算对照",
        "",
        "| 组合 | 累计收益 | CAGR | 最大回撤 | Sharpe | 最差5%日均值 | 平均资金利用率 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in ("P1", "P2", "R1", "R2"):
        row = p.loc[name]
        lines.append(
            f"| {name} | {pct(row.total_return)} | {pct(row.cagr)} | {pct(row.max_drawdown)} | {row.sharpe:.3f} | {pct(row.worst_5pct_mean)} | {pct(row.avg_utilization)} |"
        )
    lines += [
        "",
        "P1 = 25% ATRDR + 25% MCB + 25% OGR + 25% SMV6；P2 用 IFCGR 替代 OGR。R1/R2 将 MCB 的25%预算交给 ATRDR。初始预算固定、子账户独立复利、不再平衡、不互借现金。",
        "",
        "## 删除留现金与成本压力",
        "",
    ]
    for parent in ("P1", "P2"):
        base = p.loc[parent]
        lines.append(f"### {parent}")
        lines.append("")
        lines.append("| 对照 | 累计收益差（主组合-对照） | 最大回撤差 | Sharpe差 |")
        lines.append("| --- | ---: | ---: | ---: |")
        for label in p.index[p.index.str.startswith(f"{parent}_WITHOUT_")]:
            row = p.loc[label]
            lines.append(
                f"| {label} | {pct(base.total_return - row.total_return)} | {pct(base.max_drawdown - row.max_drawdown)} | {base.sharpe - row.sharpe:.3f} |"
            )
        stress = p.loc[f"{parent}_EXTRA_20BP_PER_FILL"]
        lines.append(
            f"\n额外每次成交20bp的固定路径压力后：累计收益 {pct(stress.total_return)}（相对主结果 {pct(stress.total_return - base.total_return)}），现金不足标记日合计 {int(stress.fixed_path_cash_insufficiency_days)}。这不是重新执行现金约束回放。"
        )
    lines += [
        "",
        "## 证据解释",
        "",
        "- `family_analysis.csv` 分开给出 ATRDR Bull/MCB 的共有与独有事件、OGR/IFCGR 否决、Bear/OGR 路线诊断，以及 SMV6 在股票参照最差日和前三个非重叠回撤阶段的结果。事件层百分比没有加总成资金金额。",
        "- `profit_concentration.csv` 列出每个可精确归因股票策略最赚钱的五个信号日与五只证券；分母是全部正向成交利润，不用接近零的净利润。OGR/IFCGR 的现金分红计入已实现利润。SMV6 因部分卖出/再平衡无法形成无歧义的单事件利润，保持 NA。",
        "- `risk_and_capital.csv` 保留全部策略对的全日/双方持仓相关性、双向最差5%条件收益、实际亏损天数、共同负收益与共同持仓样本数。零方差与缺失持仓返回 NA。最差5%采用收益升序、日期升序的确定性前 ceil(5%×N) 条。",
        "- ATRDR 的历史、2024–2025、2026 三段独立初始化。后两段只在单段概况出现，未拼接、未参与受 OGR 限定的主组合。",
        "- SMV6 只用有成本、整手、现金约束的本地封箱 NAV；原生 SuperMind 等价仍未验证。IFCGR 始终保持 PIT-B 标签。MCB/OAI 行为重建 provenance 没有升级。",
        "",
        "## 局限与使用边界",
        "",
        "这份结果可复现但不等于可投资，也不是独立前向验证。统一券商账户的整手、最低费用、同证券合并、公共现金池、容量和真实成交没有被证明；两个子账户持有同一证券仍按各自归属计账。旧研究已消费历史没有被包装成新 OOS。",
        "",
        "## 唯一下一步建议",
        "",
        f"只将 **{decisions.loc['PRIMARY_RESEARCH_CANDIDATE', 'verdict']}** 带入严格冻结、同口径的前向纸面执行：保留四个独立子账户和原始订单归属，先验证统一券商环境下的可成交性、整手/最低费用、同证券总敞口与实际现金占用；本轮不继续扫描权重。",
        "",
        "## 复跑",
        "",
        "```bash",
        "PYTHONPATH=src /opt/anaconda3/bin/python research/five_strategy_portfolio_v1/run_five_strategy_portfolio_v1.py \\",
        "  --input-config research/five_strategy_portfolio_v1/input_config.json \\",
        "  --output-root research/five_strategy_portfolio_v1/output \\",
        "  --signal-start 2018-01-01 --signal-end 2026-08-03 --as-of 2026-08-03 --stage all",
        "```",
        "",
    ]
    (output / "REPORT.md").write_text("\n".join(lines))


def output_manifest(output: Path) -> None:
    rows = []
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name != "output_manifest.sha256":
            rows.append(f"{sha256(path)}  {path.name}")
    (output / "output_manifest.sha256").write_text("\n".join(rows) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-config", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--signal-start", default="2018-01-01")
    parser.add_argument("--signal-end", default="2026-08-03")
    parser.add_argument("--as-of", default="2026-08-03")
    parser.add_argument(
        "--stage", choices=("inventory", "analysis", "report", "all"), default="all"
    )
    args = parser.parse_args(argv)
    config = json.loads(args.input_config.read_text())
    output = args.output_root
    output.mkdir(parents=True, exist_ok=True)
    signal_start, signal_end, asof = map(
        pd.Timestamp, (args.signal_start, args.signal_end, args.as_of)
    )
    if not signal_start <= signal_end <= asof:
        raise ValueError("require signal_start <= signal_end <= as_of")
    if args.stage in ("inventory", "all"):
        inventory(config, output, signal_start, signal_end, asof)
    results = None
    if args.stage in ("analysis", "report", "all"):
        results = analysis(config, output, asof)
    if args.stage in ("report", "all"):
        report(results, output)
    output_manifest(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
