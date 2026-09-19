#!/usr/bin/env python3
"""Independent keyed score reconstruction and fresh H10 replay for I0 fixed3."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import time
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


SEEDS = (17, 29, 43)
LEDGER_KINDS = (
    "cashflows", "inventory", "inventory_events", "lot_actions", "lot_fills",
    "lot_inventory", "lots", "nav", "orders",
)
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
VOL = Path("/Volumes/quant/CY_quant_research/ashare_path_long_training_v1")
OUT = VOL / "account_diversification_v1/account_aligned_alpha_v1/i0_fixed3_baseline_reaudit_v1"
TRANSFER = VOL / "account_diversification_v1/alpha_held_risk_v2/transfer_v1/daily"
FULL_FORWARD = VOL / "account_diversification_v1/account_aligned_alpha_v1/full_date_cross_stock_reconciliation_v1/full_forward"
AUTH_SIGNAL = VOL / "account_diversification_v1/topn_concentration_v1/centered_vote7/SIGNALS.parquet"
BROADER = REPO / "research/ashare_path_long_training_v1/account_diversification_v1/account_aligned_alpha_v1/training_root_cause_v2/broader_ranking_portfolio_v1/run.py"


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")
    temporary.replace(path)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_symbol_mapping(frame: pd.DataFrame, symbols: list[str]) -> None:
    """Reject an unbound or inconsistent j/symbol axis."""
    if "symbol" not in frame:
        raise ValueError("SYMBOL_IDENTITY_REQUIRED")
    js = frame.j.to_numpy()
    if not np.issubdtype(js.dtype, np.integer) or (js < 0).any() or (js >= len(symbols)).any():
        raise ValueError("J_OUT_OF_SYMBOL_AXIS")
    expected = np.asarray(symbols, dtype=object)[js]
    if not np.array_equal(frame.symbol.astype(str).to_numpy(), expected.astype(str)):
        raise ValueError("SYMBOL_J_MAPPING_MISMATCH")


def _validate_seed_frame(
    seed: int, frame: pd.DataFrame, symbols: list[str] | None = None,
) -> pd.DataFrame:
    required = {"t", "j", "score"}
    if not required <= set(frame):
        raise ValueError(f"SEED_{seed}_MISSING_COLUMNS:{sorted(required - set(frame))}")
    columns = ["t", "j"] + (["symbol"] if "symbol" in frame else []) + ["score"]
    out = frame[columns].copy()
    if out.duplicated(["t", "j"]).any():
        raise ValueError(f"SEED_{seed}_DUPLICATE_KEYS")
    if not np.isfinite(out.score.to_numpy(float)).all():
        raise ValueError(f"SEED_{seed}_NONFINITE_SCORE")
    if symbols is not None:
        validate_symbol_mapping(out, symbols)
    return out.rename(columns={"score": f"score_s{seed}"})


def keyed_fixed3(seed_frames: dict[int, pd.DataFrame]) -> pd.DataFrame:
    """Fail-closed keyed average; input row order is irrelevant."""
    if set(seed_frames) != set(SEEDS):
        raise ValueError(f"EXACT_SEED_SET_REQUIRED:{sorted(seed_frames)}")
    has_symbol = {"symbol" in frame for frame in seed_frames.values()}
    if len(has_symbol) != 1:
        raise ValueError("SEED_SYMBOL_IDENTITY_MISMATCH")
    keys = ["t", "j"] + (["symbol"] if has_symbol == {True} else [])
    merged: pd.DataFrame | None = None
    for seed in SEEDS:
        frame = _validate_seed_frame(seed, seed_frames[seed])
        if merged is None:
            merged = frame
        else:
            merged = merged.merge(frame, on=keys, how="outer", validate="one_to_one", indicator=True)
            if not merged._merge.eq("both").all():
                counts = merged._merge.value_counts().to_dict()
                raise ValueError(f"SEED_KEY_MISMATCH:{seed}:{counts}")
            merged = merged.drop(columns="_merge")
    assert merged is not None
    merged["fixed3"] = merged[[f"score_s{s}" for s in SEEDS]].mean(axis=1)
    return merged.sort_values(["t", "j"], kind="stable").reset_index(drop=True)


def percentile_by_date(frame: pd.DataFrame, value: str) -> pd.DataFrame:
    if frame.duplicated(["t", "j"]).any():
        raise ValueError("DUPLICATE_KEYS")
    if not np.isfinite(frame[value].to_numpy(float)).all():
        raise ValueError("NONFINITE_SCORE")
    keys = ["t", "j"] + (["symbol"] if "symbol" in frame else [])
    out = frame[keys + [value]].copy()
    out["score"] = out.groupby("t")[value].rank(method="average", pct=True)
    return out[keys + ["score"]]


def rebuild_inputs(year: int, out_root: Path = OUT) -> dict:
    if year not in (2020, 2021):
        raise ValueError("AUDIT_YEAR_MUST_BE_2020_OR_2021")
    source = TRANSFER / f"{year}.parquet"
    columns = ["t", "j", "decision_date", "final_prediction", "positive_gate", "consensus_rank"]
    columns += [f"BRANCH_s{s}" for s in SEEDS]
    columns += [f"rank_s{s}" for s in SEEDS]
    frame = pd.read_parquet(source, columns=columns)
    if frame.duplicated(["t", "j"]).any():
        raise ValueError("AUTHORITATIVE_KEY_DUPLICATE")

    axes = json.loads((VOL / "panel/axes.json").read_text())
    symbols = axes["symbols"]
    if frame.j.min() < 0 or frame.j.max() >= len(symbols):
        raise ValueError("AUTHORITATIVE_J_OUT_OF_SYMBOL_AXIS")
    frame["symbol"] = np.asarray(symbols, dtype=object)[frame.j.to_numpy()]
    seed_frames = {
        seed: percentile_by_date(frame[["t", "j", "symbol", f"BRANCH_s{seed}"]], f"BRANCH_s{seed}")
        for seed in SEEDS
    }
    fixed = keyed_fixed3(seed_frames)
    expected_fixed = frame[["t", "j", "symbol", "consensus_rank"]].rename(columns={"consensus_rank": "expected"})
    parity = fixed.merge(expected_fixed, on=["t", "j", "symbol"], how="outer", validate="one_to_one", indicator=True)
    if not parity._merge.eq("both").all() or not np.array_equal(parity.fixed3, parity.expected):
        raise ValueError("FIXED3_SAVED_SCORE_MISMATCH")

    composed = frame[[f"BRANCH_s{s}" for s in SEEDS]].mean(axis=1)
    if not np.array_equal(composed.to_numpy(), frame.final_prediction.to_numpy()):
        raise ValueError("COMPOSED_MEAN_MISMATCH")
    gate_mask = composed.gt(0)
    if not np.array_equal(gate_mask.to_numpy(), frame.positive_gate.to_numpy()):
        raise ValueError("POSITIVE_GATE_MISMATCH")

    start, end = int(frame.t.min()), int(frame.t.max())
    authoritative = pd.read_parquet(AUTH_SIGNAL, filters=[("t", ">=", start), ("t", "<=", end)])
    gate = frame.loc[gate_mask, ["t", "j", "symbol", "decision_date", "final_prediction"]].rename(
        columns={"final_prediction": "pred20"}
    )
    gate = gate.merge(
        authoritative[["t", "j", "pred20", "logamount20"]],
        on=["t", "j"], how="outer", suffixes=("_rebuilt", "_authoritative"),
        validate="one_to_one", indicator=True,
    )
    if not gate._merge.eq("both").all() or not np.array_equal(gate.pred20_rebuilt, gate.pred20_authoritative):
        raise ValueError("AUTHORITATIVE_GATE_MISMATCH")
    gate = gate[["t", "j", "symbol", "decision_date", "pred20_rebuilt", "logamount20"]].rename(
        columns={"pred20_rebuilt": "pred20"}
    ).sort_values(["t", "j"], kind="stable").reset_index(drop=True)

    destination = out_root / "inputs" / str(year)
    destination.mkdir(parents=True, exist_ok=True)
    gate_path = destination / "COMMON_FIXED3_POSITIVE_GATE.parquet"
    gate.to_parquet(gate_path, index=False)
    score_paths: dict[str, Path] = {}
    for seed in SEEDS:
        path = destination / f"I0_S{seed}_SCORE.parquet"
        seed_frames[seed].sort_values(["t", "j"], kind="stable").to_parquet(path, index=False)
        score_paths[f"I0_S{seed}"] = path
    fixed_path = destination / "I0_FIXED3_SCORE.parquet"
    fixed[["t", "j", "symbol", "fixed3"]].rename(columns={"fixed3": "score"}).to_parquet(fixed_path, index=False)
    score_paths["I0_FIXED3"] = fixed_path

    keys = pd.read_parquet(FULL_FORWARD / str(year) / "KEYS.parquet", columns=["t", "j", "decision_date"])
    key_order = np.array_equal(frame[["t", "j"]].to_numpy(), keys[["t", "j"]].to_numpy())
    date_order = np.array_equal(frame.decision_date.astype(str).to_numpy(), keys.decision_date.astype(str).to_numpy())
    npy = {}
    for seed in SEEDS:
        values = np.load(FULL_FORWARD / str(year) / f"I0_s{seed}.npy", mmap_mode="r")
        npy[str(seed)] = {
            "exact": bool(np.array_equal(values, frame[f"BRANCH_s{seed}"].to_numpy())),
            "rows": int(len(values)),
        }
    manifest = {
        "year": year,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "source": str(source), "source_sha256": sha256(source),
        "rows": int(len(frame)), "dates": int(frame.t.nunique()),
        "keys_exact_order": bool(key_order), "decision_dates_exact_order": bool(date_order),
        "npy_to_keyed_composed_exact": npy,
        "percentile": "pandas rank method=average pct=True within t",
        "aggregation": "mean of seed17,29,43 percentiles",
        "tie_break": "score descending then j ascending in archived account source",
        "gate": "mean(BRANCH_s17,BRANCH_s29,BRANCH_s43)>0 before ranking consumption",
        "authoritative_signal_exact": True,
        "gate_path": str(gate_path), "gate_sha256": sha256(gate_path),
        "score_paths": {arm: {"path": str(path), "sha256": sha256(path)} for arm, path in score_paths.items()},
    }
    dump(destination / "INPUT_MANIFEST.json", manifest)
    return manifest


def load_replay_signal(
    score_path: Path, gate_path: Path, symbols: list[str] | None = None,
) -> pd.DataFrame:
    if not score_path.is_file():
        raise FileNotFoundError(f"SCORE_FILE_NOT_FOUND:{score_path}")
    if not gate_path.is_file():
        raise FileNotFoundError(f"GATE_FILE_NOT_FOUND:{gate_path}")
    score = _validate_seed_frame(0, pd.read_parquet(score_path), symbols).rename(columns={"score_s0": "score"})
    gate = pd.read_parquet(gate_path)
    required = {"t", "j", "pred20", "logamount20"}
    if not required <= set(gate) or gate.duplicated(["t", "j"]).any():
        raise ValueError("INVALID_GATE_FILE")
    if symbols is not None:
        validate_symbol_mapping(gate, symbols)
    keys = ["t", "j"] + (["symbol"] if "symbol" in score and "symbol" in gate else [])
    if ("symbol" in score) != ("symbol" in gate):
        raise ValueError("SCORE_GATE_SYMBOL_IDENTITY_MISMATCH")
    merged = gate.merge(score, on=keys, how="left", validate="one_to_one")
    if merged.score.isna().any():
        raise ValueError("GATE_SCORE_KEY_MISSING")
    if not np.isfinite(merged[["score", "pred20", "logamount20"]].to_numpy(float)).all():
        raise ValueError("NONFINITE_REPLAY_INPUT")
    return merged[["t", "j", "score", "pred20", "logamount20"]]


def _runtime():
    return load_module("i0_reaudit_broader", BROADER)


def replay_return_maxdd(ts: list[int], ledgers: Path, policy: str) -> dict:
    nav = pd.read_parquet(ledgers / f"{policy}_funded_prefix_nav.parquet")
    values = nav[nav.t.isin(ts)].nav.astype(float).to_numpy()
    if len(values) != len(ts):
        raise ValueError("REPLAY_NAV_COVERAGE_MISMATCH")
    peaks = np.maximum.accumulate(np.r_[1_000_000.0, values])[1:]
    return {
        "annual_return": float(values[-1] / 1_000_000.0 - 1),
        "max_drawdown": -float(np.min(values / peaks - 1)),
        "nav_rows": len(values),
    }


def fresh_replay(
    year: int,
    arm: str,
    score_path: Path,
    gate_path: Path,
    out_root: Path = OUT,
    forecast_sessions: int | None = None,
) -> dict:
    """Always consumes supplied files before considering an audit-local resume."""
    load_replay_signal(score_path, gate_path)
    br = _runtime()
    dates, symbols, ts, market, actions, _ = br.context(year)
    signal = load_replay_signal(score_path, gate_path, symbols)
    if int(signal.t.min()) != ts[0] or int(signal.t.max()) != ts[-1]:
        raise ValueError("SIGNAL_YEAR_AXIS_MISMATCH")
    starts = br.load(br.BASE / str(year) / "H10_CANONICAL_STARTS.json")
    if len(starts) != 1 or starts[0]["tag"] != "ROOT":
        raise ValueError("CANONICAL_START_IDENTITY")
    start = starts[0]
    snapshot = Path(start["path"])
    if sha256(snapshot) != start["hash"] or D(start["START_NAV"]) != D(1_000_000):
        raise ValueError("CANONICAL_START_HASH")

    archived_source = br.BASE / str(year) / "CENTERED_TOP10_H10_RUN_SOURCE.py"
    source = archived_source.read_text()
    if forecast_sessions is not None and not 1 <= forecast_sessions <= len(ts):
        raise ValueError("INVALID_FORECAST_SESSIONS")
    replay_ts = ts if forecast_sessions is None else ts[:forecast_sessions]
    namespace = "fresh_replay" if forecast_sessions is None else f"benchmark_{forecast_sessions}d"
    destination = out_root / namespace / str(year) / arm
    ledgers = destination / "ledgers"
    ledgers.mkdir(parents=True, exist_ok=True)
    source_path = destination / "RUN_SOURCE.py"
    source_path.write_text(source)
    identity = {
        "year": year, "arm": arm,
        "score_path": str(score_path), "score_sha256": sha256(score_path),
        "gate_path": str(gate_path), "gate_sha256": sha256(gate_path),
        "canonical_start_sha256": start["hash"],
        "source_sha256": sha256(source_path),
        "archived_source_sha256": sha256(archived_source),
        "actions_sha256": sha256(br.B7 / "REGISTERED_ACTIONS_THROUGH2023.parquet"),
        "holding": "H10", "TopN": 10, "common_gate": "FIXED3_COMPOSED_MEAN_POSITIVE",
        "forecast_sessions": forecast_sessions,
        "forecast_through": replay_ts[-1],
    }
    if identity["source_sha256"] != identity["archived_source_sha256"]:
        raise ValueError("EXEC_SOURCE_ARCHIVE_MISMATCH")
    result_path = destination / "RESULT.json"
    if result_path.exists():
        old = br.load(result_path)
        if old.get("identity") != identity:
            raise ValueError("AUDIT_LOCAL_RESUME_IDENTITY_MISMATCH")
        return old

    br.engine.OUT = ledgers
    scope = dict(br.engine.__dict__, holding_horizon=10, normalize_t=None, scale_for=lambda t: D(1), planning_audit=[])
    exec(source, scope)
    suffix = "" if forecast_sessions is None else f"_BENCH{forecast_sessions}D"
    policy = f"Y{year}_{arm}_REAUDIT_V1{suffix}_ROOT"
    started = datetime.now(timezone.utc).astimezone().isoformat()
    clock = time.monotonic()
    engine_result = scope["run"](
        policy, signal, market, actions, dates, symbols, forecast_through=replay_ts[-1], stagger=True,
        resume_path=snapshot, snapshot_path=destination / f"{policy}.pkl", entitlement_branch=start["choices"],
    )
    if engine_result["block"] is not None:
        raise RuntimeError(f"ACCOUNT_BLOCKED:{arm}:{engine_result['block']}")
    pd.DataFrame(scope["planning_audit"]).to_parquet(destination / "PLANNING.parquet", index=False)
    br.dump(destination / "ENGINE.json", engine_result)
    metrics = None
    if forecast_sessions is None:
        metrics = replay_return_maxdd(ts, ledgers, policy)
    result = {
        "status": "COMPLETE_FRESH_REPLAY", "run_id": f"{year}-{arm}-reaudit-v1",
        "started_at": started, "finished_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "identity": identity, "policy": policy, "engine": engine_result, "metrics": metrics,
        "elapsed_seconds": time.monotonic() - clock,
        "old_i0_cache_shortcut_used": False,
    }
    br.dump(result_path, result)
    return result


def _decimal_sum(values: Iterable[object]) -> D:
    return sum((D(str(value)) for value in values), D(0))


def compare_ledger_directories(
    archived_dir: Path,
    archived_policy: str,
    rebuilt_dir: Path,
    rebuilt_policy: str,
    ignored_columns: tuple[str, ...] = (),
) -> dict:
    """Compare every economic ledger and return the earliest stored difference."""
    allowed_ignored = {"policy", "run_id", "source_path"}
    if not set(ignored_columns) <= allowed_ignored:
        raise ValueError("UNAPPROVED_IGNORED_LEDGER_COLUMN")
    report = {
        "status": "PASS",
        "value_normalization": "missing values equal; scalar values compared exactly; storage dtype ignored",
        "ignored_columns": list(ignored_columns),
        "ledgers": {},
        "first_divergence": None,
    }
    for kind in LEDGER_KINDS:
        old_path = archived_dir / f"{archived_policy}_funded_prefix_{kind}.parquet"
        new_path = rebuilt_dir / f"{rebuilt_policy}_funded_prefix_{kind}.parquet"
        if not old_path.is_file() or not new_path.is_file():
            detail = {
                "kind": kind, "reason": "MISSING_LEDGER",
                "archived_exists": old_path.is_file(), "rebuilt_exists": new_path.is_file(),
            }
            report["status"] = "FAIL"
            report["first_divergence"] = detail
            return report
        old = pd.read_parquet(old_path).drop(columns=list(ignored_columns), errors="ignore")
        new = pd.read_parquet(new_path).drop(columns=list(ignored_columns), errors="ignore")
        ledger = {
            "archived_path": str(old_path), "archived_sha256": sha256(old_path),
            "rebuilt_path": str(new_path), "rebuilt_sha256": sha256(new_path),
            "archived_rows": len(old), "rebuilt_rows": len(new),
        }
        report["ledgers"][kind] = ledger
        if list(old.columns) != list(new.columns):
            detail = {
                "kind": kind, "reason": "COLUMN_MISMATCH",
                "archived_columns": list(old.columns), "rebuilt_columns": list(new.columns),
            }
        elif len(old) != len(new):
            detail = {"kind": kind, "reason": "ROW_COUNT_MISMATCH", **ledger}
        else:
            detail = None
            first = []
            for column_number, column in enumerate(old.columns):
                equal = old[column].eq(new[column]) | (old[column].isna() & new[column].isna())
                mismatch = np.flatnonzero(~equal.to_numpy())
                if len(mismatch):
                    first.append((int(mismatch[0]), column_number, column))
            if first:
                row, _, column = min(first)
                left, right = old.iloc[row][column], new.iloc[row][column]
                detail = {
                    "kind": kind, "reason": "VALUE_MISMATCH", "row": row,
                    "column": column, "archived": str(left), "rebuilt": str(right),
                    "archived_row": {key: str(value) for key, value in old.iloc[row].to_dict().items()},
                    "rebuilt_row": {key: str(value) for key, value in new.iloc[row].to_dict().items()},
                }
        if detail is not None:
            report["status"] = "FAIL"
            report["first_divergence"] = detail
            return report
        ledger["values_equal"] = True
    return report


def stock_pnl_reconciliation(
    fills: pd.DataFrame,
    cashflows: pd.DataFrame,
    inventory: pd.DataFrame,
    nav: pd.DataFrame,
    start_t: int,
    end_t: int,
    external_kinds: frozenset[str] = frozenset({"WARMUP_INITIAL_CAPITAL", "ANNUAL_CAPITAL_NORMALIZATION"}),
) -> tuple[pd.DataFrame, dict]:
    """One transaction source plus non-trade events and exact NAV bridge."""
    period_fills = fills[fills.t.between(start_t, end_t)].copy()
    transactions = period_fills.assign(_cash=period_fills.cash_delta.map(lambda x: D(str(x)))).groupby("j")._cash.sum()
    period_cash = cashflows[cashflows.t.between(start_t, end_t)].copy()
    non_trade = period_cash[~period_cash.kind.isin(["BUY", "SELL"]) & ~period_cash.kind.isin(external_kinds)]
    stock_events = non_trade[non_trade.j >= 0].assign(_cash=lambda x: x.cash_delta.map(lambda y: D(str(y)))).groupby("j")._cash.sum()
    start_inventory = inventory[inventory.t.eq(start_t - 1)].assign(_value=lambda x: x.value.map(lambda y: D(str(y)))).groupby("j")._value.sum()
    end_inventory = inventory[inventory.t.eq(end_t)].assign(_value=lambda x: x.value.map(lambda y: D(str(y)))).groupby("j")._value.sum()
    js = transactions.index.union(stock_events.index).union(start_inventory.index).union(end_inventory.index)
    rows = []
    for j in js:
        tx = transactions.get(j, D(0)); event = stock_events.get(j, D(0))
        start = start_inventory.get(j, D(0)); end = end_inventory.get(j, D(0))
        rows.append({"j": int(j), "transaction_cashflow": str(tx), "non_trade_cashflow": str(event),
                     "start_inventory": str(start), "end_inventory": str(end), "stock_pnl": str(tx + event + end - start)})
    by_stock = pd.DataFrame(rows)
    stock_total = _decimal_sum(by_stock.stock_pnl) if len(by_stock) else D(0)
    account_nonstock_cash = _decimal_sum(non_trade[non_trade.j < 0].cash_delta)
    external = _decimal_sum(period_cash[period_cash.kind.isin(external_kinds)].cash_delta)
    nav_by_t = nav.set_index("t")
    end_row = nav_by_t.loc[end_t]
    start_rows = nav_by_t.loc[nav_by_t.index < start_t]
    start_nav = D(str(start_rows.iloc[-1].nav)) if len(start_rows) else D(1_000_000)
    start_receivable = D(str(start_rows.iloc[-1].receivable)) if len(start_rows) else D(0)
    start_tax = D(str(start_rows.iloc[-1].tax_reserve)) if len(start_rows) else D(0)
    receivable_change = D(str(end_row.receivable)) - start_receivable
    tax_reserve_change = D(str(end_row.tax_reserve)) - start_tax
    account_nonstock = account_nonstock_cash + receivable_change - tax_reserve_change
    nav_change_less_external = D(str(end_row.nav)) - start_nav - external
    residual = stock_total + account_nonstock - nav_change_less_external
    summary = {
        "stock_pnl": str(stock_total), "account_nonstock_cashflow": str(account_nonstock_cash),
        "receivable_change": str(receivable_change), "tax_reserve_change": str(tax_reserve_change),
        "account_nonstock_total": str(account_nonstock), "external_net_inflow": str(external),
        "nav_change_less_external": str(nav_change_less_external), "residual": str(residual),
        "pass": residual == 0,
    }
    return by_stock, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-inputs")
    build.add_argument("year", type=int, choices=(2020, 2021))
    replay = sub.add_parser("replay")
    replay.add_argument("year", type=int, choices=(2020, 2021))
    replay.add_argument("arm", choices=("I0_S17", "I0_S29", "I0_S43", "I0_FIXED3"))
    replay.add_argument("--forecast-sessions", type=int)
    args = parser.parse_args()
    if args.command == "build-inputs":
        print(json.dumps(rebuild_inputs(args.year), indent=2))
    else:
        folder = OUT / "inputs" / str(args.year)
        score = folder / f"{args.arm}_SCORE.parquet"
        print(json.dumps(fresh_replay(
            args.year, args.arm, score, folder / "COMMON_FIXED3_POSITIVE_GATE.parquet",
            forecast_sessions=args.forecast_sessions,
        ), indent=2, default=str))


if __name__ == "__main__":
    main()
