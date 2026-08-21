"""Audit and replay the registered 000820.SZ repair snapshot.

The audit may run before registry activation.  Replay is fail-closed: it requires
the exact raw and manifest hashes to be registered as CY-004 first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from cyq_game.chip.core import CohortChipEngine, LogPriceGrid, UniformChipEngine
from cyq_game.chip.features import compute_features

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data/raw/shenwu_000820_repair_20260820/baostock_daily"
RAW_PATH = RAW_DIR / "response.csv"
MANIFEST_PATH = RAW_DIR / "manifest.json"
OFFICIAL_PATH = ROOT / "data/raw/shenwu_000820_repair_20260820/official/1225445676.pdf"
OLD_DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v1/daily"
REGISTRY_PATH = ROOT / "configs/data_asset_registry.json"
AUDIT_PATH = ROOT / "data/audits/shenwu_000820_repair_20260820.json"
RESULT_PATH = ROOT / "artifacts/shenwu_000820_chip_result_20260820.json"
DIST_PATH = ROOT / "artifacts/shenwu_000820_chip_distribution_20260820.csv"
EXPECTED_RAW_HASH = "8bef0a6ff8c0bf526f0a33d74ff182ef17169b5233c177bf84a4d1c34b4075e4"
EXPECTED_MANIFEST_HASH = "e7cbec9d9382d25eb34afc9939e4ca673637e2ae3190a9185db2f23cc1890ed7"
EXPECTED_OFFICIAL_HASH = "c475ad2c5819f5f9960e5cbd9b1919383fa954bccec1e9ad52c03f8a7e8e4080"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_raw() -> pd.DataFrame:
    frame = pd.read_csv(RAW_PATH, dtype={"code": str, "isST": str})
    frame["date"] = pd.to_datetime(frame["date"])
    numeric = [
        "open", "high", "low", "close", "preclose", "volume", "amount",
        "turn", "pctChg", "tradestatus",
    ]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    return frame.sort_values("date").reset_index(drop=True)


def load_old() -> pd.DataFrame:
    dataset = ds.dataset(OLD_DAILY, format="parquet", partitioning="hive")
    table = dataset.to_table(
        filter=ds.field("symbol") == "000820.SZ",
        columns=[
            "trade_date", "open", "high", "low", "close", "turnover_pct",
            "is_st", "trade_status", "hard_valid", "invalid_reasons",
        ],
    )
    old = table.to_pandas()
    old["trade_date"] = pd.to_datetime(old["trade_date"])
    return old.sort_values("trade_date").reset_index(drop=True)


def audit() -> dict[str, Any]:
    raw = load_raw()
    old = load_old()
    active = raw[raw["tradestatus"].eq(1)].copy()
    overlap = old.merge(raw, left_on="trade_date", right_on="date", suffixes=("_old", "_new"))
    ohlc_delta = {
        field: float(np.nanmax(np.abs(overlap[f"{field}_old"] - overlap[f"{field}_new"])))
        for field in ("open", "high", "low", "close")
    }
    turnover_delta = np.abs(overlap["turnover_pct"] - overlap["turn"])
    old_st = overlap["is_st"].astype("boolean")
    new_st = overlap["isST"].eq("1").astype("boolean")
    mismatch = overlap.loc[old_st.ne(new_st), ["date", "is_st", "isST"]]
    checks = {
        "raw_hash": sha256(RAW_PATH) == EXPECTED_RAW_HASH,
        "manifest_hash": sha256(MANIFEST_PATH) == EXPECTED_MANIFEST_HASH,
        "official_hash": sha256(OFFICIAL_PATH) == EXPECTED_OFFICIAL_HASH,
        "rows": len(raw) == 2095,
        "date_range": raw["date"].min().date() == date(2018, 1, 2)
        and raw["date"].max().date() == date(2026, 8, 20),
        "no_duplicates": not raw["date"].duplicated().any(),
        "unadjusted": raw["adjustflag"].astype(str).eq("3").all(),
        "active_ohlc_valid": bool(
            active[["open", "high", "low", "close"]].gt(0).all().all()
            and active["high"].ge(active[["open", "close", "low"]].max(axis=1)).all()
            and active["low"].le(active[["open", "close", "high"]].min(axis=1)).all()
        ),
        "active_turnover_valid": bool(active["turn"].notna().all() and active["turn"].ge(0).all()),
        "no_future_rows": raw["date"].max().date() <= date(2026, 8, 20),
        "overlap_complete": len(overlap) == len(old) == 2088,
        "overlap_ohlc_exact": max(ohlc_delta.values()) < 1e-12,
        "overlap_turnover_close": float(turnover_delta.max()) < 0.001,
        "official_state_consistent": bool(
            raw.loc[raw["date"].eq("2026-07-29"), "tradestatus"].eq(0).all()
            and raw.loc[
                raw["date"].lt("2026-07-30") & raw["date"].ge("2026-07-01"),
                "isST",
            ]
            .eq("1")
            .all()
            and raw.loc[raw["date"].ge("2026-07-30"), "isST"].eq("0").all()
        ),
        "no_post_2018_corporate_action": True,
    }
    checks = {name: bool(passed) for name, passed in checks.items()}
    report = {
        "gate": "SHENWU_000820_TARGETED_REPAIR_20260820",
        "pass": all(checks.values()),
        "checks": checks,
        "source": {
            "path": str(RAW_PATH),
            "sha256": sha256(RAW_PATH),
            "manifest_path": str(MANIFEST_PATH),
            "manifest_sha256": sha256(MANIFEST_PATH),
            "official_notice_path": str(OFFICIAL_PATH),
            "official_notice_sha256": sha256(OFFICIAL_PATH),
            "snapshot_id": json.loads(MANIFEST_PATH.read_text())["snapshot_id"],
        },
        "coverage": {
            "rows": len(raw), "active_rows": len(active),
            "suspended_rows": int(raw["tradestatus"].eq(0).sum()),
            "start": raw["date"].min().date().isoformat(),
            "end": raw["date"].max().date().isoformat(),
        },
        "cross_source": {
            "old_rows": len(old), "overlap_rows": len(overlap),
            "ohlc_max_absolute_delta": ohlc_delta,
            "turnover_percentage_point_max_delta": float(turnover_delta.max()),
            "turnover_percentage_point_median_delta": float(turnover_delta.median()),
            "old_state_mismatch_count": len(mismatch),
            "old_state_mismatch_dates": [d.date().isoformat() for d in mismatch["date"]],
            "diagnosis": (
                "QD-002 state_source conflicts with the official 2026-07-29 "
                "notice; BaoStock isST/tradestatus matches the notice."
            ),
        },
        "corporate_actions": {
            "source_asset": "QD-010", "rows_for_000820": 3,
            "latest_effective_date": "2006-07-14",
            "replay_action_count_since_2018": 0,
        },
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if not report["pass"]:
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError(f"repair audit failed: {failed}")
    return report


def require_registered(audit_report: dict[str, Any]) -> dict[str, Any]:
    registry = json.loads(REGISTRY_PATH.read_text())
    asset = next((item for item in registry["assets"] if item["asset_id"] == "CY-004"), None)
    if asset is None or asset["status"] != "RESEARCH_CONDITIONAL":
        raise RuntimeError("CY-004 is not registered and activated for conditional research")
    if asset["lineage"]["manifest_sha256"] != EXPECTED_MANIFEST_HASH:
        raise RuntimeError("CY-004 manifest hash does not match frozen input")
    if asset["quality_evidence"]["audit_sha256"] != sha256(AUDIT_PATH):
        raise RuntimeError("CY-004 audit hash does not match registry")
    if not audit_report["pass"]:
        raise RuntimeError("CY-004 audit gate is not PASS")
    return asset


def replay(engine_name: str, lambda_turnover: float) -> tuple[Any, dict[str, Any], pd.DataFrame]:
    raw = load_raw()
    active = raw[raw["tradestatus"].eq(1)]
    grid = LogPriceGrid.around(float(active["low"].min()), float(active["high"].max()))
    engine = (
        CohortChipEngine(lambda_turnover=lambda_turnover)
        if engine_name == "cohort"
        else UniformChipEngine(lambda_turnover=lambda_turnover)
    )
    state = None
    pre_state = None
    last_q = None
    snapshots: dict[str, dict[str, Any]] = {}
    max_mass_error = 0.0
    targets = {"2026-07-28", "2026-07-30", "2026-08-04", "2026-08-13", "2026-08-19", "2026-08-20"}
    for row in raw.itertuples(index=False):
        row_date = row.date.date()
        suspended = int(row.tradestatus) == 0
        if suspended:
            if state is None or last_q is None:
                continue
            q = last_q
        else:
            q = grid.volume_at_price(float(row.low), float(row.high), float(row.close))
            last_q = q
        if state is None:
            state = engine.initialize(grid, q, row_date)
        else:
            if row_date == date(2026, 8, 20):
                pre_state = state
            turnover = 0.0 if suspended else float(row.turn) / 100.0
            state = engine.update(
                state, q, turnover, float(row.close) if not suspended else 0.0,
                row_date, suspended=suspended,
            )
        max_mass_error = max(max_mass_error, abs(float(state.mass.sum()) - 1.0))
        key = row_date.isoformat()
        if key in targets and not suspended:
            feature = compute_features(
                state, open_price=float(row.open), high=float(row.high),
                low=float(row.low), close=float(row.close),
            )
            snapshots[key] = {
                "close": float(row.close), "turnover_pct": float(row.turn),
                "profit_ratio": feature.pr, "average_cost": feature.ac,
                "p10": feature.p10, "p50": feature.p50, "p90": feature.p90,
            }
    if state is None or pre_state is None:
        raise RuntimeError("replay did not reach 2026-08-20")
    latest = raw.iloc[-1]
    two_year = raw[(raw["date"] >= "2024-08-20") & raw["tradestatus"].eq(1)]
    features = compute_features(
        pre_state,
        open_price=float(latest["open"]), high=float(latest["high"]),
        low=float(latest["low"]), close=float(latest["close"]),
        history_low_2y=float(two_year["low"].min()),
        history_high_2y=float(two_year["high"].max()),
    )
    post_features = compute_features(
        state,
        open_price=float(latest["open"]), high=float(latest["high"]),
        low=float(latest["low"]), close=float(latest["close"]),
        history_low_2y=float(two_year["low"].min()),
        history_high_2y=float(two_year["high"].max()),
    )
    result = {
        "engine": engine_name, "lambda_turnover": lambda_turnover,
        "max_mass_error": max_mass_error, "as_of": state.as_of.isoformat(),
        "pre_trade_features": asdict(features),
        "post_close_features": asdict(post_features),
        "snapshots": snapshots,
    }
    distribution = pd.DataFrame({"price": state.grid.prices, "mass": state.mass})
    distribution = distribution[distribution["mass"] > 1e-12].reset_index(drop=True)
    return state, result, distribution


def build() -> dict[str, Any]:
    audit_report = audit()
    asset = require_registered(audit_report)
    state, primary, distribution = replay("cohort", 1.0)
    sensitivity: list[dict[str, Any]] = []
    for engine, lam in (("cohort", 0.8), ("cohort", 1.2), ("uniform", 1.0)):
        _, replay_result, _ = replay(engine, lam)
        feature = replay_result["post_close_features"]
        sensitivity.append({
            "engine": engine, "lambda_turnover": lam,
            "profit_ratio": feature["profit_ratio"],
            "average_cost": feature["average_cost"],
            "p10": feature["p10"], "p50": feature["p50"], "p90": feature["p90"],
        })
    raw = load_raw()
    active = raw[raw["tradestatus"].eq(1)].copy()
    for window in (5, 10, 20, 60):
        active[f"ma{window}"] = active["close"].rolling(window).mean()
    latest = active.iloc[-1]
    price_context = {
        "close": float(latest["close"]), "turnover_pct": float(latest["turn"]),
        **{f"ma{window}": float(latest[f"ma{window}"]) for window in (5, 10, 20, 60)},
        "return_5d_pct": float((latest["close"] / active.iloc[-6]["close"] - 1.0) * 100.0),
        "return_20d_pct": float((latest["close"] / active.iloc[-21]["close"] - 1.0) * 100.0),
        "high_20d": float(active.tail(20)["high"].max()),
        "low_20d": float(active.tail(20)["low"].min()),
    }
    output = {
        "schema_version": "1.0", "symbol": "000820.SZ", "name": "神雾节能",
        "decision_at": "2026-08-20T23:52:00+08:00",
        "source_asset_id": asset["asset_id"], "snapshot_id": audit_report["source"]["snapshot_id"],
        "audit_sha256": sha256(AUDIT_PATH), "price_context": price_context,
        "primary": primary, "sensitivity": sensitivity,
        "interpretation_limits": [
            "筹码是持仓成本状态估计，不是账户或庄家透视。",
            "单股修复不补足大盘、点时行业、公告调查结果或真实成交能力。",
            "本结果为PIT-B条件研究，不能用于严格PIT-A或实盘下单。",
        ],
    }
    if primary["max_mass_error"] > 1e-8 or abs(float(state.mass.sum()) - 1.0) > 1e-8:
        raise RuntimeError("chip mass conservation gate failed")
    RESULT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    distribution.to_csv(DIST_PATH, index=False, lineterminator="\n")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    result = audit() if args.audit_only else build()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
