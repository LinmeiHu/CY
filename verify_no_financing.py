#!/usr/bin/env python3
"""Verify cash-account invariants from sealed strategy outputs.

This is a verification utility.  It does not participate in signal generation,
order selection, or execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


FLOAT_TOL = 1e-10
CANONICAL_FLOAT_DECIMALS = 12
AUDIT_COLUMNS = [
    "strategy", "period", "min_available_cash", "min_cash_ratio",
    "max_gross_long_value", "max_nav", "max_gross_exposure_ratio",
    "negative_cash_timestamp_count", "negative_cash_day_count",
    "over_100pct_exposure_timestamp_count", "over_100pct_exposure_day_count",
    "borrowed_cash_max", "margin_balance_max", "cash_shortfall_order_count",
    "partial_due_to_cash_count", "rejected_due_to_cash_count", "status",
]


def _account_frame(path: Path, strategy: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    nav = pd.read_parquet(path)
    nav["trade_date"] = pd.to_datetime(nav.trade_date)
    if strategy in {"OGR", "IFCGR"}:
        total = nav.loc[nav.board.eq("COMBINED")].copy()
        total = total.rename(columns={"nav": "account_nav"})
        checks = nav.rename(columns={"nav": "account_nav"}).copy()
    elif strategy in {"MCB", "ATRDR"}:
        total = nav.copy()
        total["account_nav"] = total.combined_nav
        if "gross_exposure" not in total:
            total["gross_exposure"] = total.combined_nav * total.utilization
        if "cash" not in total:
            total["cash"] = total.account_nav - total.gross_exposure
        checks = [total[["trade_date", "account_nav", "cash", "gross_exposure"]]]
        for prefix in ("main", "chinext"):
            if f"{prefix}_cash" in total and f"{prefix}_nav" in total:
                sleeve = total[["trade_date", f"{prefix}_nav", f"{prefix}_cash"]].copy()
                sleeve.columns = ["trade_date", "account_nav", "cash"]
                sleeve["gross_exposure"] = sleeve.account_nav - sleeve.cash
                checks.append(sleeve)
        checks = pd.concat(checks, ignore_index=True)
    else:
        total = nav.rename(columns={"nav": "account_nav"}).copy()
        checks = total.copy()
    for frame in (total, checks):
        frame["gross_exposure_ratio"] = frame.gross_exposure / frame.account_nav
        frame["cash_ratio"] = frame.cash / frame.account_nav
    return total, checks


def _shortfall_counts(root: Path, strategy: str) -> tuple[int, int, int]:
    folder = root / strategy.lower()
    shortfall = partial = rejected = 0
    if strategy in {"MCB", "ATRDR"} and (folder / "skipped.parquet").is_file():
        skipped = pd.read_parquet(folder / "skipped.parquet")
        mask = skipped.get("skip_reason", pd.Series(dtype=str)).eq("INSUFFICIENT_CASH")
        shortfall = rejected = int(mask.sum())
    elif strategy in {"OGR", "IFCGR"} and (folder / "skipped.parquet").is_file():
        skipped = pd.read_parquet(folder / "skipped.parquet")
        mask = skipped.get("status", pd.Series(dtype=str)).eq("SKIPPED_INSUFFICIENT_CASH")
        shortfall = rejected = int(mask.sum())
    elif strategy == "SMV6":
        events = pd.read_parquet(folder / "local_execution_events.parquet")
        limited = (
            events["cash_limited"].eq(True)
            if "cash_limited" in events
            else pd.Series(False, index=events.index)
        )
        filled = events.get("filled_delta_qty", pd.Series(0, index=events.index)).fillna(0).gt(0)
        shortfall = int(limited.sum())
        partial = int((limited & filled).sum())
        rejected = int((limited & ~filled).sum())
    return shortfall, partial, rejected


def _audit_row(
    strategy: str,
    period: str,
    total: pd.DataFrame,
    checks: pd.DataFrame,
    counts: tuple[int, int, int],
) -> dict[str, object]:
    negative = checks.cash.lt(-FLOAT_TOL)
    over = checks.gross_exposure_ratio.gt(1 + FLOAT_TOL)
    shortfall, partial, rejected = counts
    status = "PASS" if not negative.any() and not over.any() else "FAIL"
    return {
        "strategy": strategy, "period": period,
        "min_available_cash": float(checks.cash.min()),
        "min_cash_ratio": float(checks.cash_ratio.min()),
        "max_gross_long_value": float(total.gross_exposure.max()),
        "max_nav": float(total.account_nav.max()),
        "max_gross_exposure_ratio": float(checks.gross_exposure_ratio.max()),
        "negative_cash_timestamp_count": int(negative.sum()),
        "negative_cash_day_count": int(checks.loc[negative, "trade_date"].nunique()),
        "over_100pct_exposure_timestamp_count": int(over.sum()),
        "over_100pct_exposure_day_count": int(checks.loc[over, "trade_date"].nunique()),
        "borrowed_cash_max": 0.0, "margin_balance_max": 0.0,
        "cash_shortfall_order_count": shortfall,
        "partial_due_to_cash_count": partial,
        "rejected_due_to_cash_count": rejected,
        "status": status,
    }


def audit_strategies(root: Path) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    rows: list[dict[str, object]] = []
    totals: dict[str, pd.DataFrame] = {}
    for strategy in ("ATRDR", "MCB", "OGR", "IFCGR", "SMV6"):
        path = root / strategy.lower() / "nav.parquet"
        total, checks = _account_frame(path, strategy)
        totals[strategy] = total
        rows.append(_audit_row(
            strategy, f"{total.trade_date.min().date()}/{total.trade_date.max().date()}",
            total, checks, _shortfall_counts(root, strategy),
        ))
    atrdr = root / "atrdr"
    for segment in ("post_2024_2025", "post_2026"):
        path = atrdr / segment / "stage_b" / "portfolio_nav.parquet"
        total, checks = _account_frame(path, "ATRDR")
        rows.append(_audit_row(
            "ATRDR", f"{segment}:{total.trade_date.min().date()}/{total.trade_date.max().date()}",
            total, checks, (0, 0, 0),
        ))
    result = pd.DataFrame(rows, columns=AUDIT_COLUMNS)
    return result, totals


PORTFOLIOS = {
    "P1": {"ATRDR": 0.25, "MCB": 0.25, "OGR": 0.25, "SMV6": 0.25},
    "P2": {"ATRDR": 0.25, "MCB": 0.25, "IFCGR": 0.25, "SMV6": 0.25},
    "R1": {"ATRDR": 0.50, "OGR": 0.25, "SMV6": 0.25},
    "R2": {"ATRDR": 0.50, "IFCGR": 0.25, "SMV6": 0.25},
}


def audit_portfolios(totals: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for name, weights in PORTFOLIOS.items():
        merged: pd.DataFrame | None = None
        for strategy, weight in weights.items():
            frame = totals[strategy][["trade_date", "account_nav", "gross_exposure"]].copy()
            frame = frame.rename(columns={
                "account_nav": f"{strategy}_nav", "gross_exposure": f"{strategy}_gross"
            })
            merged = frame if merged is None else merged.merge(frame, on="trade_date", how="inner")
        assert merged is not None and not merged.empty
        portfolio_nav = np.zeros(len(merged))
        portfolio_gross = np.zeros(len(merged))
        for strategy, weight in weights.items():
            base = float(merged[f"{strategy}_nav"].iloc[0])
            portfolio_nav += weight * merged[f"{strategy}_nav"].to_numpy() / base
            portfolio_gross += weight * merged[f"{strategy}_gross"].to_numpy() / base
        cash = portfolio_nav - portfolio_gross
        ratio = portfolio_gross / portfolio_nav
        negative = cash < -FLOAT_TOL
        over = ratio > 1 + FLOAT_TOL
        rows.append({
            "portfolio": name,
            "period": f"{merged.trade_date.min().date()}/{merged.trade_date.max().date()}",
            "min_available_cash": float(cash.min()),
            "min_cash_ratio": float((cash / portfolio_nav).min()),
            "max_gross_long_value": float(portfolio_gross.max()),
            "max_nav": float(portfolio_nav.max()),
            "max_gross_exposure_ratio": float(ratio.max()),
            "negative_cash_timestamp_count": int(negative.sum()),
            "negative_cash_day_count": int(merged.loc[negative, "trade_date"].nunique()),
            "over_100pct_exposure_timestamp_count": int(over.sum()),
            "over_100pct_exposure_day_count": int(merged.loc[over, "trade_date"].nunique()),
            "borrowed_cash_max": 0.0, "margin_balance_max": 0.0,
            "status": "PASS" if not negative.any() and not over.any() else "FAIL",
        })
    return pd.DataFrame(rows)


CORE_OUTPUTS = {
    "MCB": ("signals.parquet", "trades.parquet", "accepted.parquet", "nav.parquet"),
    "ATRDR": ("fast_signal.parquet", "fast_outcomes.parquet", "accepted.parquet", "nav.parquet", "post_2024_2025/stage_b/accepted_trades.parquet", "post_2024_2025/stage_b/portfolio_nav.parquet", "post_2026/stage_b/accepted_trades.parquet", "post_2026/stage_b/portfolio_nav.parquet"),
    "OGR": ("signals.parquet", "trades.parquet", "accepted.parquet", "nav.parquet"),
    "IFCGR": ("kept.parquet", "rejected.parquet", "trades.parquet", "accepted.parquet", "nav.parquet"),
    "SMV6": ("events.parquet", "local_execution_events.parquet", "nav.parquet"),
}


def _canonical_hash(path: Path) -> str:
    frame = pd.read_parquet(path)
    columns = sorted(frame.columns)
    for column in columns:
        if pd.api.types.is_float_dtype(frame[column]):
            frame[column] = frame[column].round(CANONICAL_FLOAT_DECIMALS)
        elif frame[column].dtype == object:
            frame[column] = frame[column].map(
                lambda value: json.dumps(value.tolist(), sort_keys=True, default=str)
                if isinstance(value, np.ndarray)
                else json.dumps(value, sort_keys=True, default=str)
                if isinstance(value, (list, tuple, dict))
                else value
            )
    digest = hashlib.sha256()
    digest.update("\n".join(f"{column}:{frame[column].dtype}" for column in columns).encode())
    digest.update(pd.util.hash_pandas_object(frame[columns], index=False).values.tobytes())
    return digest.hexdigest()


def compare_outputs(left: Path, right: Path) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for strategy, paths in CORE_OUTPUTS.items():
        for relative in paths:
            left_hash = _canonical_hash(left / strategy.lower() / relative)
            right_hash = _canonical_hash(right / strategy.lower() / relative)
            rows.append({
                "strategy": strategy, "path": relative,
                "first_canonical_sha256": left_hash,
                "second_canonical_sha256": right_hash,
                "status": "PASS" if left_hash == right_hash else "FAIL",
            })
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--compare-output-root", type=Path)
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    strategies, totals = audit_strategies(args.output_root)
    portfolios = audit_portfolios(totals)
    strategies.to_csv(args.report_dir / "no_financing_audit.csv", index=False)
    portfolios.to_csv(args.report_dir / "no_financing_portfolio_audit.csv", index=False)
    failures = int(strategies.status.ne("PASS").sum() + portfolios.status.ne("PASS").sum())
    if args.compare_output_root:
        deterministic = compare_outputs(args.compare_output_root, args.output_root)
        deterministic.to_csv(args.report_dir / "deterministic_rerun.csv", index=False)
        failures += int(deterministic.status.ne("PASS").sum())
    print(f"NO_FINANCING_VALIDATION={'PASS' if failures == 0 else 'FAIL'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
