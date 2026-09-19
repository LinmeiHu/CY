#!/usr/bin/env python3
"""Frozen 2020/2021 I0 fixed3 mechanism diagnostics; no fitting or strategy search."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


SEEDS = (17, 29, 43)
HERE = Path(__file__).resolve().parent
VOL = Path("/Volumes/quant/CY_quant_research/ashare_path_long_training_v1")
OUT = VOL / "account_diversification_v1/account_aligned_alpha_v1/i0_fixed3_baseline_reaudit_v1/ensemble_mechanism_v2"
TRANSFER = VOL / "account_diversification_v1/alpha_held_risk_v2/transfer_v1/daily"
FULL = VOL / "account_diversification_v1/account_aligned_alpha_v1/full_date_cross_stock_reconciliation_v1/full_forward"
REPLAY = VOL / "account_diversification_v1/account_aligned_alpha_v1/i0_fixed3_baseline_reaudit_v1/fresh_replay"
LARGE_LOSS = -0.10


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")
    temporary.replace(path)


def correlation(left: pd.Series, right: pd.Series, method: str = "pearson") -> float:
    valid = left.notna() & right.notna()
    if valid.sum() < 2 or left[valid].nunique() < 2 or right[valid].nunique() < 2:
        return np.nan
    return left[valid].corr(right[valid], method=method)


def add_rank(frame: pd.DataFrame, score: str, output: str, mask: pd.Series | None = None) -> None:
    selected = frame.index if mask is None else frame.index[mask]
    order = frame.loc[selected, ["t", "j", score]].sort_values(
        ["t", score, "j"], ascending=[True, False, True], kind="stable"
    )
    frame[output] = np.nan
    frame.loc[order.index, output] = order.groupby("t", sort=False).cumcount().add(1).to_numpy()


def load_geometry(year: int) -> pd.DataFrame:
    source = TRANSFER / f"{year}.parquet"
    columns = ["t", "j", "decision_date", "final_prediction", "positive_gate", "consensus_rank"]
    columns += [f"BRANCH_s{s}" for s in SEEDS] + [f"rank_s{s}" for s in SEEDS]
    frame = pd.read_parquet(source, columns=columns)
    keys = pd.read_parquet(FULL / str(year) / "KEYS.parquet")
    if not frame[["t", "j", "decision_date"]].equals(keys[["t", "j", "decision_date"]]):
        raise ValueError(f"KEY_AXIS_MISMATCH:{year}")
    ret10 = np.load(FULL / str(year) / "ret10.npy", mmap_mode="r")
    ret20 = np.load(FULL / str(year) / "ret20.npy", mmap_mode="r")
    if len(ret10) != len(frame) or len(ret20) != len(frame):
        raise ValueError(f"LABEL_AXIS_MISMATCH:{year}")
    frame["ret10"] = ret10
    frame["ret20"] = ret20
    frame["year"] = year
    frame["gate_margin"] = frame[[f"BRANCH_s{s}" for s in SEEDS]].mean(axis=1)
    if not np.array_equal(frame.gate_margin.to_numpy(), frame.final_prediction.to_numpy()):
        raise ValueError(f"GATE_MARGIN_MISMATCH:{year}")
    if not np.array_equal(frame.gate_margin.gt(0).to_numpy(), frame.positive_gate.to_numpy()):
        raise ValueError(f"GATE_STATUS_MISMATCH:{year}")
    for seed in SEEDS:
        frame[f"score{seed}"] = frame[f"BRANCH_s{seed}"]
        frame[f"percentile{seed}"] = frame[f"rank_s{seed}"]
        add_rank(frame, f"percentile{seed}", f"rank{seed}")
        add_rank(frame, f"percentile{seed}", f"gate_rank{seed}", frame.positive_gate)
    frame["fixed3_score"] = frame[[f"percentile{s}" for s in SEEDS]].mean(axis=1)
    if not np.array_equal(frame.fixed3_score.to_numpy(), frame.consensus_rank.to_numpy()):
        raise ValueError(f"FIXED3_SCORE_MISMATCH:{year}")
    add_rank(frame, "fixed3_score", "fixed3_rank")
    add_rank(frame, "fixed3_score", "fixed3_gate_rank", frame.positive_gate)
    ranks = frame[[f"rank{s}" for s in SEEDS]]
    frame["rank_mean"] = ranks.mean(axis=1)
    frame["rank_median"] = ranks.median(axis=1)
    frame["rank_min"] = ranks.min(axis=1)
    frame["rank_max"] = ranks.max(axis=1)
    frame["rank_std"] = ranks.std(axis=1, ddof=0)
    for n in (10, 20, 50, 100):
        for seed in SEEDS:
            frame[f"top{n}_s{seed}"] = frame[f"gate_rank{seed}"].le(n)
            frame[f"full_top{n}_s{seed}"] = frame[f"rank{seed}"].le(n)
        frame[f"fixed_top{n}"] = frame.fixed3_gate_rank.le(n)
        frame[f"full_fixed_top{n}"] = frame.fixed3_rank.le(n)
        frame[f"support_top{n}_count"] = frame[[f"top{n}_s{s}" for s in SEEDS]].sum(axis=1).astype("int8")
    frame["composition_class"] = "C" + frame.support_top10_count.astype(str)
    frame["all_seeds_top20"] = frame.rank_max.le(20)
    frame["all_seeds_top50"] = frame.rank_max.le(50)
    frame["best_rank_band"] = pd.cut(
        frame.rank_min, [0, 2, 5, 10, 20, 50, np.inf],
        labels=["R1_2", "R3_5", "R6_10", "R11_20", "R21_50", "R51_PLUS"],
    ).astype(str)
    sorted_ranks = np.sort(ranks.to_numpy(), axis=1)
    frame["one_extreme_two_mediocre"] = (sorted_ranks[:, 0] <= 10) & (sorted_ranks[:, 1] > 20)
    frame["stable_mid_high"] = (sorted_ranks[:, 0] > 10) & (sorted_ranks[:, 2] <= 50)
    return frame


def label_metrics(frame: pd.DataFrame, prefix: dict) -> list[dict]:
    rows = []
    for label in ("ret10", "ret20"):
        values = frame[label].dropna().astype(float)
        rows.append({
            **prefix, "label": label, "selected": len(frame), "coverage": len(values),
            "coverage_fraction": len(values) / len(frame) if len(frame) else np.nan,
            "mean": values.mean() if len(values) else np.nan,
            "median": values.median() if len(values) else np.nan,
            "positive_fraction": values.gt(0).mean() if len(values) else np.nan,
            "large_loss_frequency": values.le(LARGE_LOSS).mean() if len(values) else np.nan,
            "p01": values.quantile(.01) if len(values) else np.nan,
            "p05": values.quantile(.05) if len(values) else np.nan,
        })
    return rows


def geometry_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for t, daily in frame.groupby("t", sort=True):
        for scope, sample, rank_prefix in (
            ("LEGAL", daily, "rank"),
            ("COMMON_GATE", daily[daily.positive_gate], "gate_rank"),
        ):
            for left, right in ((17, 29), (17, 43), (29, 43)):
                row = {
                    "year": int(daily.year.iloc[0]), "t": int(t), "decision_date": daily.decision_date.iloc[0],
                    "scope": scope, "seed_left": left, "seed_right": right, "universe": len(sample),
                    "spearman_score_correlation": correlation(sample[f"percentile{left}"], sample[f"percentile{right}"]),
                }
                for n in (10, 20, 50, 100):
                    a = sample[f"{rank_prefix}{left}"].le(n)
                    b = sample[f"{rank_prefix}{right}"].le(n)
                    overlap = int((a & b).sum())
                    row[f"top{n}_overlap_count"] = overlap
                    row[f"top{n}_overlap_fraction"] = overlap / n
                rows.append(row)
    return pd.DataFrame(rows)


def composition_analysis(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, selected_rows = [], []
    for year, annual in frame.groupby("year"):
        fixed = annual[annual.fixed_top10].copy()
        for group, sample in fixed.groupby("composition_class"):
            prefix = {
                "year": year, "selection": "FIXED3_TOP10", "bucket": group,
                "names": len(sample), "daily_average_fraction": len(sample) / (annual.t.nunique() * 10),
            }
            rows.extend(label_metrics(sample, prefix))
            selected_rows.append(sample.assign(selection="FIXED3_TOP10", bucket=group))
        dropped = annual[
            annual[[f"top10_s{s}" for s in SEEDS]].any(axis=1) & ~annual.fixed_top10
        ].copy()
        prefix = {
            "year": year, "selection": "DROPPED_SINGLE_SEED_EXTREME", "bucket": "DROPPED",
            "names": len(dropped), "daily_average_fraction": len(dropped) / (annual.t.nunique() * 10),
        }
        rows.extend(label_metrics(dropped, prefix))
        selected_rows.append(dropped.assign(selection="DROPPED_SINGLE_SEED_EXTREME", bucket="DROPPED"))
    return pd.DataFrame(rows), pd.concat(selected_rows, ignore_index=True)


def ledger_paths(year: int, arm: str) -> tuple[Path, str]:
    folder = REPLAY / str(year) / arm / "ledgers"
    return folder, f"Y{year}_{arm}_REAUDIT_V1_ROOT"


def execution_maps(year: int, arm: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    root = REPLAY / str(year) / arm
    planning = pd.read_parquet(root / "PLANNING.parquet")
    folder, policy = ledger_paths(year, arm)
    orders = pd.read_parquet(folder / f"{policy}_funded_prefix_orders.parquet")
    nav = pd.read_parquet(folder / f"{policy}_funded_prefix_nav.parquet")
    fills = pd.read_parquet(folder / f"{policy}_funded_prefix_lot_fills.parquet")
    return planning, orders, nav, fills


def lot_pnl(year: int, arm: str, valid_ts: set[int]) -> tuple[pd.DataFrame, list[dict]]:
    folder, policy = ledger_paths(year, arm)
    fills = pd.read_parquet(folder / f"{policy}_funded_prefix_lot_fills.parquet")
    inventory = pd.read_parquet(folder / f"{policy}_funded_prefix_lot_inventory.parquet")
    lots = pd.read_parquet(folder / f"{policy}_funded_prefix_lots.parquet")
    cashflows = pd.read_parquet(folder / f"{policy}_funded_prefix_cashflows.parquet")
    nav = pd.read_parquet(folder / f"{policy}_funded_prefix_nav.parquet")
    start_t, end_t = min(valid_ts), max(valid_ts)
    period_fills = fills[fills.t.between(start_t, end_t)].copy()
    tx = period_fills.assign(value=period_fills.cash_delta.astype(float)).groupby("lot_id").value.sum()
    fees = period_fills.assign(value=period_fills.fees.astype(float)).groupby("lot_id").value.sum()
    start = inventory[inventory.t.eq(start_t - 1)].assign(value_f=lambda x: x.value.astype(float)).groupby("lot_id").value_f.sum()
    end = inventory[inventory.t.eq(end_t)].assign(value_f=lambda x: x.value.astype(float)).groupby("lot_id").value_f.sum()
    ids = tx.index.union(start.index).union(end.index)
    detail = pd.DataFrame({
        "lot_id": ids,
        "fill_cashflow": tx.reindex(ids, fill_value=0).to_numpy(),
        "fees": fees.reindex(ids, fill_value=0).to_numpy(),
        "start_inventory": start.reindex(ids, fill_value=0).to_numpy(),
        "end_inventory": end.reindex(ids, fill_value=0).to_numpy(),
    })
    detail["lot_pnl"] = detail.fill_cashflow + detail.end_inventory - detail.start_inventory
    detail["position_state"] = np.where(detail.end_inventory.eq(0), "CLOSED", "OPEN_END")
    detail = detail.merge(lots[["lot_id", "j", "signal_t", "entry_t"]], on="lot_id", how="left", validate="one_to_one")
    period_cash = cashflows[cashflows.t.between(start_t, end_t)].copy()
    nontrade = period_cash[~period_cash.kind.isin(["BUY", "SELL", "WARMUP_INITIAL_CAPITAL", "ANNUAL_CAPITAL_NORMALIZATION"])]
    external = period_cash[period_cash.kind.isin(["WARMUP_INITIAL_CAPITAL", "ANNUAL_CAPITAL_NORMALIZATION"])].cash_delta.astype(float).sum()
    nav_year = nav[nav.t.isin(valid_ts)].sort_values("t")
    start_nav_rows = nav[nav.t.lt(start_t)].sort_values("t")
    start_nav = float(start_nav_rows.iloc[-1].nav) if len(start_nav_rows) else 1_000_000.0
    end_nav = float(nav_year.iloc[-1].nav)
    components = [
        {"year": year, "arm": arm, "component": "CLOSED_LOT_TRANSACTION_MARK_PNL", "value": detail.loc[detail.position_state.eq("CLOSED"), "lot_pnl"].sum()},
        {"year": year, "arm": arm, "component": "OPEN_END_TRANSACTION_MARK_PNL", "value": detail.loc[detail.position_state.eq("OPEN_END"), "lot_pnl"].sum()},
        {"year": year, "arm": arm, "component": "DIVIDENDS", "value": nontrade.loc[nontrade.kind.str.contains("DIVIDEND", na=False) & ~nontrade.kind.str.contains("TAX", na=False), "cash_delta"].astype(float).sum()},
        {"year": year, "arm": arm, "component": "TAXES", "value": nontrade.loc[nontrade.kind.str.contains("TAX", na=False), "cash_delta"].astype(float).sum()},
        {"year": year, "arm": arm, "component": "OTHER_CORPORATE_ACTION_CASH", "value": nontrade.loc[~nontrade.kind.str.contains("DIVIDEND|TAX", na=False), "cash_delta"].astype(float).sum()},
        {"year": year, "arm": arm, "component": "FEES_MEMO_ALREADY_IN_LOT_PNL", "value": -detail.fees.sum()},
        {"year": year, "arm": arm, "component": "START_INVENTORY_MEMO", "value": detail.start_inventory.sum()},
        {"year": year, "arm": arm, "component": "END_INVENTORY_MEMO", "value": detail.end_inventory.sum()},
        {"year": year, "arm": arm, "component": "EXTERNAL_NET_INFLOW", "value": external},
        {"year": year, "arm": arm, "component": "NAV_CHANGE_LESS_EXTERNAL", "value": end_nav - start_nav - external},
    ]
    reconciled = detail.lot_pnl.sum() + nontrade.cash_delta.astype(float).sum()
    components.append({"year": year, "arm": arm, "component": "RECONCILED_TOTAL", "value": reconciled})
    components.append({"year": year, "arm": arm, "component": "RECONCILIATION_RESIDUAL", "value": reconciled - (end_nav - start_nav - external)})
    return detail, components


def retained_dropped(frame: pd.DataFrame, pnl_maps: dict[tuple[int, str], pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for year, annual in frame.groupby("year"):
        for seed in SEEDS:
            arm = f"I0_S{seed}"
            sample = annual[annual[f"top10_s{seed}"]].copy()
            sample["retention"] = np.where(sample.fixed_top10, "RETAINED_BY_FIXED3", "DROPPED_BY_FIXED3")
            other = [s for s in SEEDS if s != seed]
            sample["other_seed_rank_mean"] = sample[[f"rank{s}" for s in other]].mean(axis=1)
            planning, orders, _, _ = execution_maps(year, arm)
            planned = planning.assign(planned=lambda x: x.status.eq("PLANNED")).groupby(["t", "j"]).planned.max()
            buy = orders[orders.side.eq("BUY")].assign(filled=lambda x: x.status.eq("FILLED")).groupby(["decision_t", "j"]).filled.max()
            sample = sample.merge(planned.rename("planned").reset_index(), on=["t", "j"], how="left")
            sample = sample.merge(buy.rename("filled").reset_index().rename(columns={"decision_t": "t"}), on=["t", "j"], how="left")
            lp = pnl_maps[(year, arm)].groupby(["signal_t", "j"]).agg(realized_lot_pnl=("lot_pnl", "sum")).reset_index().rename(columns={"signal_t": "t"})
            sample = sample.merge(lp, on=["t", "j"], how="left")
            for status, group in sample.groupby("retention"):
                prefix = {
                    "year": year, "seed": seed, "retention": status, "names": len(group),
                    "own_rank_mean": group[f"rank{seed}"].mean(),
                    "other_seed_rank_mean": group.other_seed_rank_mean.mean(),
                    "rank_std_mean": group.rank_std.mean(),
                    "planned_probability": group.planned.eq(True).mean(),
                    "fill_probability": group.filled.eq(True).mean(),
                    "realized_lot_pnl_coverage": group.realized_lot_pnl.notna().mean(),
                    "realized_lot_pnl_sum": group.realized_lot_pnl.sum(),
                    "realized_lot_pnl_mean_filled": group.realized_lot_pnl.mean(),
                }
                rows.extend(label_metrics(group, prefix))
    return pd.DataFrame(rows)


def gate_analysis(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, annual in frame.groupby("year"):
        for t, daily in annual.groupby("t"):
            rows.append({
                "record_type": "DAILY_GATE", "year": year, "t": t,
                "legal_universe": len(daily), "gate_size": int(daily.positive_gate.sum()),
                "gate_fraction": daily.positive_gate.mean(),
                "fixed3_gate_margin_spearman": correlation(daily.fixed3_score, daily.gate_margin, method="spearman"),
            })
        for scope, sample in (("GATE_IN", annual[annual.positive_gate]), ("GATE_OUT", annual[~annual.positive_gate])):
            for left, right in ((17, 29), (17, 43), (29, 43)):
                rows.append({
                    "record_type": "SCOPE_GEOMETRY", "year": year, "scope": scope,
                    "pair": f"{left}_{right}",
                    "spearman_score_correlation": sample.groupby("t").apply(
                        lambda x: correlation(x[f"percentile{left}"], x[f"percentile{right}"]), include_groups=False
                    ).mean(),
                })
        for scope, prefix in (("FULL_NO_GATE", "full_"), ("COMMON_GATE", "")):
            for name, column in [(f"S{s}", f"{prefix}top10_s{s}") for s in SEEDS] + [("FIXED3", f"{prefix}fixed_top10")]:
                sample = annual[annual[column]]
                rows.extend(label_metrics(sample, {"record_type": "SIGNAL_TOP10", "year": year, "scope": scope, "arm": name}))
    return pd.DataFrame(rows)


def execution_analysis(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, annual in frame.groupby("year"):
        cache = {}
        for arm in [f"I0_S{s}" for s in SEEDS] + ["I0_FIXED3"]:
            planning, orders, nav, _ = execution_maps(year, arm)
            planning["planned"] = planning.status.eq("PLANNED")
            buy = orders[orders.side.eq("BUY")].copy()
            buy["filled"] = buy.status.eq("FILLED")
            buy["debit_f"] = pd.to_numeric(buy.debit, errors="coerce").fillna(0)
            nav["cash_f"] = nav.cash.astype(float)
            nav["exposure"] = nav.market_value.astype(float) / nav.nav.astype(float)
            cache[arm] = (planning, buy, nav.set_index("t"))
        for seed in SEEDS:
            arm = f"I0_S{seed}"
            sp, so, sn = cache[arm]
            fp, fo, fn = cache["I0_FIXED3"]
            for t, daily in annual.groupby("t"):
                seed_top = set(daily.loc[daily[f"top10_s{seed}"], "j"])
                fixed_top = set(daily.loc[daily.fixed_top10, "j"])
                common = seed_top & fixed_top
                seed_plan = sp[sp.t.eq(t)]; fixed_plan = fp[fp.t.eq(t)]
                seed_buy = so[so.decision_t.eq(t)]; fixed_buy = fo[fo.decision_t.eq(t)]
                rank_diff = daily[daily.j.isin(common)]
                seed_nav = sn.loc[t]; fixed_nav = fn.loc[t]
                rows.append({
                    "year": year, "t": t, "decision_date": daily.decision_date.iloc[0], "seed": seed,
                    "candidate_overlap": len(common), "signal_symmetric_difference": len(seed_top ^ fixed_top),
                    "common_candidate_mean_abs_order_change": (rank_diff[f"gate_rank{seed}"] - rank_diff.fixed3_gate_rank).abs().mean(),
                    "seed_planned": int(seed_plan.planned.sum()), "fixed3_planned": int(fixed_plan.planned.sum()),
                    "planned_name_symmetric_difference": len(set(seed_plan.loc[seed_plan.planned, "j"]) ^ set(fixed_plan.loc[fixed_plan.planned, "j"])),
                    "seed_zero_size": int(seed_plan.status.eq("ZERO_SIZE").sum()), "fixed3_zero_size": int(fixed_plan.status.eq("ZERO_SIZE").sum()),
                    "seed_filled": int(seed_buy.filled.sum()), "fixed3_filled": int(fixed_buy.filled.sum()),
                    "filled_name_symmetric_difference": len(set(seed_buy.loc[seed_buy.filled, "j"]) ^ set(fixed_buy.loc[fixed_buy.filled, "j"])),
                    "seed_filled_capital": seed_buy.loc[seed_buy.filled, "debit_f"].sum(),
                    "fixed3_filled_capital": fixed_buy.loc[fixed_buy.filled, "debit_f"].sum(),
                    "seed_liquidity_rejections": int(seed_buy.status.isin(["CANCELLED_UNBUYABLE", "CANCELLED_ABOVE_LIMIT", "CANCELLED_LIMIT_OUTSIDE_EXCHANGE_RANGE"]).sum()),
                    "fixed3_liquidity_rejections": int(fixed_buy.status.isin(["CANCELLED_UNBUYABLE", "CANCELLED_ABOVE_LIMIT", "CANCELLED_LIMIT_OUTSIDE_EXCHANGE_RANGE"]).sum()),
                    "seed_aggregate_cap_rejections": int(seed_buy.status.eq("CANCELLED_AGGREGATE_CAP").sum()),
                    "fixed3_aggregate_cap_rejections": int(fixed_buy.status.eq("CANCELLED_AGGREGATE_CAP").sum()),
                    "cash_before_planning_difference": float(fixed_nav.cash_f - seed_nav.cash_f),
                    "exposure_difference": float(fixed_nav.exposure - seed_nav.exposure),
                    "live_lots_difference": int(fixed_nav.live_lots - seed_nav.live_lots),
                })
    return pd.DataFrame(rows)


def account_robustness() -> tuple[pd.DataFrame, pd.DataFrame]:
    stats, blocks = [], []
    for year in (2020, 2021):
        daily = {}
        for arm in [f"I0_S{s}" for s in SEEDS] + ["I0_FIXED3"]:
            folder, policy = ledger_paths(year, arm)
            nav = pd.read_parquet(folder / f"{policy}_funded_prefix_nav.parquet")
            keys = pd.read_parquet(FULL / str(year) / "KEYS.parquet", columns=["t"])
            ts = np.sort(keys.t.unique())
            values = nav[nav.t.isin(ts)].sort_values("t").set_index("t").nav.astype(float)
            previous = pd.Series(np.r_[1_000_000.0, values.to_numpy()[:-1]], index=values.index)
            daily[arm] = values / previous - 1
        table = pd.DataFrame(daily)
        table["active_vs_mean_single"] = table.I0_FIXED3 - table[[f"I0_S{s}" for s in SEEDS]].mean(axis=1)
        active = table.active_vs_mean_single
        stats.append({
            "year": year, "comparison": "FIXED3_MINUS_MEAN_SINGLE", "mean": active.mean(),
            "median": active.median(), "positive_fraction": active.gt(0).mean(),
            "sum": active.sum(), "leave_best1_sum": active.drop(active.nlargest(1).index).sum(),
            "leave_best3_sum": active.drop(active.nlargest(3).index).sum(),
            "worst10_mean": active.nsmallest(10).mean(),
        })
        ts = table.index.to_numpy()
        for block, start in enumerate(range(0, len(table), 20)):
            part = table.iloc[start:start + 20]
            blocks.append({
                "kind": "STATIC_ACTIVE_NAV_RETURN", "year": year, "block": block,
                "start_t": int(ts[start]), "end_t": int(ts[min(start + 19, len(ts) - 1)]),
                "sessions": len(part), "active_sum": part.active_vs_mean_single.sum(),
                "fixed3_compound": (1 + part.I0_FIXED3).prod() - 1,
                "mean_single_compound": np.mean([(1 + part[f"I0_S{s}"]).prod() - 1 for s in SEEDS]),
            })
    return pd.DataFrame(stats), pd.DataFrame(blocks)


def run() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frames = [load_geometry(year) for year in (2020, 2021)]
    geometry = pd.concat(frames, ignore_index=True)
    geometry_columns = [
        "year", "t", "j", "decision_date", "score17", "score29", "score43",
        "percentile17", "percentile29", "percentile43", "rank17", "rank29", "rank43",
        "fixed3_score", "fixed3_rank", "fixed3_gate_rank", "support_top10_count",
        "support_top20_count", "rank_mean", "rank_median", "rank_min", "rank_max", "rank_std",
        "positive_gate", "gate_margin", "composition_class", "all_seeds_top20", "all_seeds_top50",
        "best_rank_band", "one_extreme_two_mediocre", "stable_mid_high", "ret10", "ret20",
    ] + [f"top10_s{s}" for s in SEEDS] + ["fixed_top10"]
    geometry_path = OUT / "SEED_GEOMETRY_2020_2021.parquet"
    geometry[geometry_columns].to_parquet(geometry_path, index=False)
    geometry_summary(geometry).to_csv(HERE / "SEED_GEOMETRY_2020_2021.csv", index=False)

    composition, composition_detail = composition_analysis(geometry)
    composition.to_csv(HERE / "FIXED3_COMPOSITION_2020_2021.csv", index=False)

    pnl_maps, pnl_components = {}, []
    for year, annual in geometry.groupby("year"):
        valid_ts = set(annual.t.unique())
        for arm in [f"I0_S{s}" for s in SEEDS] + ["I0_FIXED3"]:
            detail, components = lot_pnl(year, arm, valid_ts)
            pnl_maps[(year, arm)] = detail
            pnl_components.extend(components)
            if arm == "I0_FIXED3":
                classifications = annual[["t", "j", "fixed3_gate_rank", "composition_class"]].rename(columns={"t": "signal_t"})
                classified = detail[detail.signal_t.isin(valid_ts)].merge(
                    classifications, on=["signal_t", "j"], how="left", validate="many_to_one"
                )
                classified["bucket"] = np.where(
                    classified.fixed3_gate_rank.le(10), classified.composition_class, "SCAN_BEYOND_TOP10"
                )
                for bucket, group in classified.groupby("bucket", dropna=False):
                    pnl_components.extend([
                        {"year": year, "arm": arm, "component": f"FIXED3_NEW_BUY_{bucket}_LOT_PNL", "value": group.lot_pnl.sum()},
                        {"year": year, "arm": arm, "component": f"FIXED3_NEW_BUY_{bucket}_FEES_MEMO", "value": -group.fees.sum()},
                        {"year": year, "arm": arm, "component": f"FIXED3_NEW_BUY_{bucket}_LOTS", "value": len(group)},
                    ])
    pd.DataFrame(pnl_components).to_csv(HERE / "CORRECTED_PNL_BY_CLASS.csv", index=False)

    retained_dropped(geometry, pnl_maps).to_csv(HERE / "RETAINED_DROPPED_ANALYSIS.csv", index=False)

    mid_rows = []
    for (year, bucket), sample in composition_detail.groupby(["year", "bucket"]):
        prefix = {
            "year": year, "bucket": bucket, "names": len(sample), "rank_mean": sample.rank_mean.mean(),
            "best_rank_mean": sample.rank_min.mean(), "worst_rank_mean": sample.rank_max.mean(),
            "rank_std_mean": sample.rank_std.mean(), "all_seeds_top20_fraction": sample.all_seeds_top20.mean(),
            "all_seeds_top50_fraction": sample.all_seeds_top50.mean(),
        }
        mid_rows.extend(label_metrics(sample, prefix))
    pd.DataFrame(mid_rows).to_csv(HERE / "MIDRANK_PROMOTION_ANALYSIS.csv", index=False)

    gate_analysis(geometry).to_csv(HERE / "GATE_ALIGNMENT_ANALYSIS.csv", index=False)
    execution_analysis(geometry).to_csv(HERE / "EXECUTION_DIFFERENCE_ANALYSIS.csv", index=False)
    active, blocks = account_robustness()
    active.to_csv(HERE / "ACTIVE_RETURN_ROBUSTNESS.csv", index=False)
    blocks.to_csv(HERE / "BLOCK_ROBUSTNESS.csv", index=False)
    manifest = {
        "status": "COMPLETE_WITH_BLOCK_REPLACEMENT_DEFERRED_BY_RESOURCE_GUARD",
        "geometry_path": str(geometry_path), "geometry_sha256": sha256(geometry_path),
        "rows": len(geometry), "years": [2020, 2021],
        "outputs": sorted(path.name for path in HERE.glob("*.csv")),
        "block_robustness": {
            "static_nonoverlapping_20_session_blocks": "COMPLETE",
            "stateful_block_replacement_replays": "NOT_RUN_RESOURCE_GUARD",
            "required_replays": 78,
            "estimated_wall_minutes_from_fresh_replay_benchmark": 24,
            "reason": "active primary MPS training; optional CPU/IO replay matrix deferred rather than competing for resources",
        },
        "own_gate_single_seed_accounts": "NOT_RUN_OPTIONAL_DIAGNOSTIC",
        "2022_opened": False, "2023_opened": False, "2024_2026_opened": False,
    }
    write_json(HERE / "ANALYSIS_MANIFEST.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    run()
