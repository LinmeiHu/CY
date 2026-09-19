#!/usr/bin/env python3
"""Frozen CENTERED-score breadth audit; account construction only, no fitting."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import pickle
import sys
from decimal import Decimal as D
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CHAMP = Path("/Users/linmei/Documents/CY-worktrees/ashare-champion-playbooks-v1-20260908")
SRC = CHAMP / "research/ashare_path_long_training_v1"
DEV = SRC / "account_diversification_v1/topn_concentration_v1/h10_top2_interaction_v1"
VOL = Path("/Volumes/quant/CY_quant_research/ashare_path_long_training_v1")
B7 = VOL / "account_diversification_v1/topn_concentration_v1/centered_vote7"
BASE = VOL / "account_diversification_v1/topn_concentration_v1/h10_top2_interaction_v1/development"
OUT = VOL / "account_diversification_v1/account_aligned_alpha_v1/training_root_cause_v2/broader_ranking_portfolio_v1"
REP = ROOT / "representation_sufficiency_v1"
TAIL = ROOT / "tail_target_stability_v1"
YEARS_DEV = (2020, 2021)
YEAR_CONFIRM = 2022
ARMS = ("A0_TOP10", "A0_RW", "A1_TOP20", "A2_TOP50", "A3_TOP5PCT")

sys.path.insert(0, str(SRC))
sys.path.insert(0, str(DEV))
import common  # noqa: E402
import development as devmod  # noqa: E402
import entitlement_boundary as boundary  # noqa: E402
import entitlement_boundary_engine as engine  # noqa: E402


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load(path: Path):
    return json.loads(path.read_text())


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n")
    tmp.replace(path)


def arm_slots_source(arm: str) -> str:
    if arm == "A0_RW":
        return "min(10,len(frame))"
    if arm == "A1_TOP20":
        return "min(20,len(frame))"
    if arm == "A2_TOP50":
        return "min(50,len(frame))"
    if arm == "A3_TOP5PCT":
        return "min(len(frame),max(1,int(np.ceil(.05*len(frame)))))"
    raise ValueError(arm)


def weighted_source(year: int, arm: str) -> str:
    """Adapt the authoritative H10 source only at deterministic cohort sizing."""
    source = devmod.source(year, 10, 10)
    helper = f'''\ndef portfolio_slots(frame):
 return {arm_slots_source(arm)}
def portfolio_weights(n):
 # Fixed 1/sqrt(rank), water-filled at the frozen 1% per-order cap.
 if n<=0:return []
 raw=[D(1)/D(r).sqrt() for r in range(1,n+1)]
 result=[D(0)]*n;active=list(range(n));remaining=D('.1')
 while active:
  denom=sum((raw[i] for i in active),D(0))
  proposal={{i:remaining*raw[i]/denom for i in active}}
  capped=[i for i in active if proposal[i]>D('.01')]
  if not capped:
   for i in active:result[i]=proposal[i]
   break
  for i in capped:result[i]=D('.01');remaining-=D('.01')
  active=[i for i in active if i not in capped]
 return result
'''
    source = helper + source
    old = "slots=10 if stagger else 10-len(positions)"
    new = "slots=portfolio_slots(schedule[t]) if stagger and t in schedule else (0 if stagger else 10-len(positions))"
    assert source.count(old) == 1
    source = source.replace(old, new)
    old = "candidates=schedule[t] if ranker is None else ranker(schedule[t],t,day,navnow,free,market,symbols)"
    new = old + "\n    rank_weights=portfolio_weights(slots)"
    assert source.count(old) == 1
    source = source.replace(old, new)
    old = "budget=min(navnow*((D('.05')*D(20)/D(10)/D(10))*day_scale if stagger else NEW_POSITION_WEIGHT),available,dec(np.exp(r.logamount20))*D('.01'))"
    new = "target_weight=rank_weights[len(planned)] if stagger else NEW_POSITION_WEIGHT\n     budget=min(navnow*(target_weight*day_scale if stagger else NEW_POSITION_WEIGHT),available,dec(np.exp(r.logamount20))*D('.01'))"
    assert source.count(old) == 1
    source = source.replace(old, new)
    old = "per_name_budget=str(navnow*(D('.05')*D(20)/D(10)/D(10))*day_scale)"
    new = "per_name_budget=str(navnow*target_weight*day_scale),target_weight=str(target_weight)"
    assert source.count(old) == 1
    source = source.replace(old, new)
    # The frozen next-open assertion remains 1% per order; all water-filled weights obey it.
    assert "q['decision_nav']*((D('.05')*D(20)/D(10)/D(10))" in source
    return source


def context(year: int):
    meta = load(common.PANEL / "axes.json")
    # Canonical snapshots bind the complete pre-2024 trading calendar axis.
    # The engine is still stopped at the requested year's last session.
    dates = [d for d in meta["dates"] if d < "2024-01-01"]
    symbols = meta["symbols"]
    ts = [i for i, d in enumerate(dates) if d.startswith(str(year))]
    assert ts and year <= 2022
    market = {k: common.get(k)[: len(dates)] for k in ["up_limit_price", "limit_pct"]}
    # Reuse the exact registered action input bound by the authoritative account.
    # The engine gates each fact by known_at and stops at the requested year end;
    # this is not access to 2023 signals, labels, returns, or account outcomes.
    actions = pd.read_parquet(B7 / "REGISTERED_ACTIONS_THROUGH2023.parquet")
    cfg = load(SRC / "account_diversification_v1/GENERAL_ENTITLEMENT_INFRASTRUCTURE.json")
    boundary.REGISTRY = cfg["events"]
    return dates, symbols, ts, market, actions, cfg


def signal_frame(year: int, start: int, end: int) -> pd.DataFrame:
    f = pd.read_parquet(B7 / "SIGNALS.parquet", filters=[("t", ">=", start), ("t", "<=", end)])
    assert f.t.between(start, end).all() and (f.pred20 > 0).all()
    return f


def baseline_paths(year: int) -> tuple[dict, Path]:
    result_path = BASE / str(year) / f"Y{year}_CENTERED_TOP10_H10_ROOT_RESULT.json"
    result = load(result_path)
    assert result["arm"] == "CENTERED_TOP10_H10" and result["account_reconciliation"] == "EXACT_DECIMAL"
    return result, BASE / str(year) / "ledgers"


def execute_arm(year: int, arm: str) -> tuple[dict, Path, str]:
    assert arm != "A0_TOP10"
    dates, symbols, ts, market, actions, cfg = context(year)
    start, end = ts[0], ts[-1]
    sig = signal_frame(year, start, end)
    canonical = load(BASE / str(year) / "H10_CANONICAL_STARTS.json")
    assert len(canonical) == 1 and canonical[0]["tag"] == "ROOT"
    c = canonical[0]
    assert sha(Path(c["path"])) == c["hash"] and D(c["START_NAV"]) == D(1000000)
    dest = OUT / str(year) / arm
    ledgers = dest / "ledgers"
    ledgers.mkdir(parents=True, exist_ok=True)
    source = weighted_source(year, arm)
    source_path = dest / "RUN_SOURCE.py"
    source_path.write_text(source)
    identity = {
        "year": year,
        "arm": arm,
        "canonical_start_sha256": c["hash"],
        "signal_sha256": sha(B7 / "SIGNALS.parquet"),
        "actions_sha256": sha(B7 / "REGISTERED_ACTIONS_THROUGH2023.parquet"),
        "source_sha256": sha(source_path),
        "score": "FROZEN_CENTERED_FIXED3",
        "gate": "RAW_POSITIVE",
        "holding": "H10",
        "daily_cohort_budget": ".10_NAV",
        "per_order_cap": ".01_NAV",
        "same_name_cap": ".10_NAV",
    }
    result_file = dest / "RESULT.json"
    if result_file.exists():
        old = load(result_file)
        assert old["identity"] == identity
        return old, ledgers, old["policy"]
    engine.OUT = ledgers
    scope = dict(engine.__dict__, holding_horizon=10, normalize_t=None, scale_for=lambda t: D(1), planning_audit=[])
    exec(source, scope)
    name = f"Y{year}_{arm}_ROOT"
    q = scope["run"](
        name,
        sig,
        market,
        actions,
        dates,
        symbols,
        forecast_through=end,
        stagger=True,
        resume_path=Path(c["path"]),
        snapshot_path=dest / f"{name}.pkl",
        entitlement_branch=c["choices"],
    )
    dump(dest / "ENGINE.json", q)
    assert q["block"] is None, q
    pd.DataFrame(scope["planning_audit"]).to_parquet(dest / "PLANNING.parquet", index=False)
    result = {"identity": identity, "policy": name, "status": "COMPLETE_RECONCILED", "engine": q}
    dump(result_file, result)
    return result, ledgers, name


def read_ledger(folder: Path, policy: str, kind: str) -> pd.DataFrame:
    return pd.read_parquet(folder / f"{policy}_funded_prefix_{kind}.parquet")


def forward_labels(year: int) -> pd.DataFrame:
    a = np.load(REP / str(year) / "FORWARD_FULL_DAILY.npz")
    f = pd.DataFrame({"t": a["t"].astype(int), "j": a["j"].astype(int), "ret20": a["ret"].astype(float), "centered_score": a["linear"].astype(float)})
    f["rank"] = f.groupby("t").centered_score.rank(method="first", ascending=False)
    f["eligible_n"] = f.groupby("t").j.transform("size")
    f["predicted_percentile"] = f["rank"] / f["eligible_n"]
    return f


def account_metrics(year: int, arm: str, folder: Path, policy: str) -> tuple[dict, dict]:
    _, _, ts, _, _, _ = context(year)
    nav = read_ledger(folder, policy, "nav")
    g = nav[nav.t.isin(ts)].copy()
    assert len(g) == len(ts)
    v = g.nav.astype(float).to_numpy()
    ret = float(v[-1] / 1e6 - 1)
    dd = -float(np.min(v / np.maximum.accumulate(np.r_[1e6, v])[1:] - 1))
    exposure = g.market_value.astype(float).to_numpy() / v
    cash = g.cash.astype(float).to_numpy() / v
    fills = read_ledger(folder, policy, "lot_fills")
    fy = fills[fills.t.isin(ts)].copy()
    orders = read_ledger(folder, policy, "orders")
    oy = orders[(orders.t.isin(ts)) & (orders.side == "BUY") & (orders.status == "FILLED")].copy()
    inv = read_ledger(folder, policy, "inventory")
    iy = inv[inv.t.isin(ts)].copy()
    iy["value_f"] = iy.value.astype(float)
    by_t = iy.groupby("t").value_f.transform("sum")
    iy["gross_weight"] = np.where(by_t > 0, iy.value_f / by_t, 0)
    hhi = iy.assign(sq=lambda x: x.gross_weight**2).groupby("t").sq.sum().reindex(ts, fill_value=0)
    max_name = iy.groupby("t").gross_weight.max().reindex(ts, fill_value=0)
    li = read_ledger(folder, policy, "lot_inventory")
    liy = li[li.t.isin(ts)].copy()
    repeated = liy.groupby(["t", "j"]).size().rename("lots").reset_index()
    repfrac = repeated.assign(multi=lambda x: x.lots.gt(1)).groupby("t").multi.mean().reindex(ts, fill_value=0)
    daily_ret = pd.Series(v, index=ts).pct_change().fillna(pd.Series({ts[0]: v[0] / 1e6 - 1})).sort_values()
    negative_mass = -daily_ret[daily_ret < 0].sum()
    worst5_share = float((-daily_ret.head(5).sum()) / negative_mass) if negative_mass else 0.0
    # Net executed lot return, fee-inclusive; dividends remain in account PnL, not this position diagnostic.
    lf = fills.copy()
    lf["cash_f"] = lf.cash_delta.astype(float)
    lot = lf.groupby("lot_id").agg(net_cash=("cash_f", "sum"), buy_cash=("cash_f", lambda x: -x[x < 0].sum()), sides=("side", "nunique"))
    lot = lot[(lot.buy_cash > 0) & (lot.sides >= 2)]
    lot["return"] = lot.net_cash / lot.buy_cash
    worst10 = float(lot.nsmallest(10, "return")["return"].mean()) if len(lot) else np.nan
    # Stock PnL concentration over the calendar interval.
    fflow = fy.assign(cash_f=lambda x: x.cash_delta.astype(float)).groupby("j").cash_f.sum()
    cf = read_ledger(folder, policy, "cashflows")
    cfy = cf[cf.t.isin(ts)].copy()
    cfy["cash_f"] = cfy.cash_delta.astype(float)
    # BUY/SELL are already represented by lot_fills.  cashflows is only the
    # authoritative source for non-trade stock events such as dividends/tax.
    cflow = cfy[(cfy.j >= 0) & ~cfy.kind.isin(["BUY", "SELL"])].groupby("j").cash_f.sum()
    start_inv = inv[inv.t == ts[0] - 1].assign(value_f=lambda x: x.value.astype(float)).groupby("j").value_f.sum()
    end_inv = inv[inv.t == ts[-1]].assign(value_f=lambda x: x.value.astype(float)).groupby("j").value_f.sum()
    js = fflow.index.union(cflow.index).union(start_inv.index).union(end_inv.index)
    stock_pnl = fflow.reindex(js, fill_value=0) + cflow.reindex(js, fill_value=0) + end_inv.reindex(js, fill_value=0) - start_inv.reindex(js, fill_value=0)
    positive = stock_pnl[stock_pnl > 0].sort_values(ascending=False)
    pos_sum = positive.sum()
    conc = {
        "year": year,
        "arm": arm,
        "positive_pnl_top1_share": float(positive.head(1).sum() / pos_sum) if pos_sum else 0.0,
        "positive_pnl_top3_share": float(positive.head(3).sum() / pos_sum) if pos_sum else 0.0,
        "worst10_closed_lot_mean_return": worst10,
        "worst_account_day_return": float(daily_ret.iloc[0]),
        "worst5_account_day_mean_return": float(daily_ret.head(5).mean()),
        "worst5_negative_return_share": worst5_share,
        "mean_same_name_multi_cohort_fraction": float(repfrac.mean()),
        "peak_live_lots_same_name": int(repeated.lots.max()) if len(repeated) else 0,
    }
    lab = forward_labels(year)
    selected = oy[["decision_t", "j", "reserved"]].rename(columns={"decision_t": "t"}).merge(lab, on=["t", "j"], how="left", validate="many_to_one")
    selected = selected[selected.ret20.notna()].copy()
    selected["capital"] = selected.reserved.astype(float)
    weighted_ret = float(np.average(selected.ret20, weights=selected.capital)) if len(selected) and selected.capital.sum() else np.nan
    metrics = {
        "year": year,
        "arm": arm,
        "annual_return": ret,
        "MaxDD": dd,
        "average_exposure": float(exposure.mean()),
        "peak_exposure": float(exposure.max()),
        "unused_cash": float(cash.mean()),
        "turnover": float((fy.quantity.astype(float) * fy.price.astype(float)).sum() / v.mean()),
        "fees": float(fy.fees.astype(float).sum()),
        "average_holdings": float(g.holdings.mean()),
        "gross_HHI": float(hhi.mean()),
        "mean_largest_name_gross_weight": float(max_name.mean()),
        "capital_utilization": float(exposure.mean()),
        "buy_fills": int(len(oy)),
        "equal_weight_selected_ret20": float(selected.ret20.mean()),
        "capital_weighted_selected_ret20": weighted_ret,
        "mean_predicted_percentile": float(selected.predicted_percentile.mean()),
        "median_funded_rank": float(selected["rank"].median()),
        "p90_funded_rank": float(selected["rank"].quantile(.90)),
        "account_reconciliation": "PASS_EXISTING_EXACT_DECIMAL",
    }
    return metrics, conc


def verify_a0(year: int) -> tuple[dict, dict]:
    result, folder = baseline_paths(year)
    policy = result["policy"]
    metrics, conc = account_metrics(year, "A0_TOP10", folder, policy)
    for k in ["annual_return", "MaxDD", "average_exposure", "turnover", "fees"]:
        oldkey = "fees" if k == "fees" else k
        assert abs(metrics[k] - float(result[oldkey])) < 1e-12, (year, k, metrics[k], result[oldkey])
    metrics["account_reconciliation"] = "PASS_EXACT_REPRODUCTION_OF_AUTHORITATIVE_A0"
    return metrics, conc


def score_curve(scopes: tuple[int, ...]) -> pd.DataFrame:
    old = pd.read_csv(TAIL / "SCORE_PERCENTILE_RETURN_CURVE.csv")
    wanted = [str(y) for y in scopes]
    if 2020 in scopes:
        wanted.append("TRAIN_FOLD_2020")
    old = old[old.scope.astype(str).isin(wanted)].copy()
    old["support"] = np.where(old.scope.astype(str).eq("TRAIN_FOLD_2020"), "PRE2020_TRAIN_DIAGNOSTIC", old.scope.astype(str))
    agg = old.groupby(["support", "bucket"], as_index=False).agg(
        mean_Ret20=("mean_ret20", "mean"), median_Ret20=("median_ret20", "mean"),
        positive_fraction=("positive_fraction", "mean"), left_tail_ES10=("es10", "mean"), count=("n", "sum")
    )
    turns = []
    frames = [(str(y), forward_labels(y)) for y in scopes if isinstance(y, int)]
    if 2020 in scopes:
        spec = importlib.util.spec_from_file_location("tail_target_stability_run", TAIL / "run.py")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        pre = mod.train(2020).rename(columns={"score": "centered_score"})
        frames.append(("PRE2020_TRAIN_DIAGNOSTIC", pre[["t", "j", "centered_score"]]))
    for support, f in frames:
        f = f.copy()
        f["pct"] = f.groupby("t").centered_score.rank(method="first", pct=True, ascending=False)
        bins = [("TOP_0_5PCT", 0, .005), ("P0_5_1PCT", .005, .01), ("P1_2PCT", .01, .02), ("P2_5PCT", .02, .05), ("P5_10PCT", .05, .10), ("P10_20PCT", .10, .20)]
        for name, lo, hi in bins:
            sets = [set(g.j) for _, g in f[(f.pct > lo) & (f.pct <= hi)].groupby("t", sort=True)]
            replacement = [1 - len(a & b) / max(1, min(len(a), len(b))) for a, b in zip(sets[:-1], sets[1:])]
            turns.append({"support": support, "bucket": name, "mean_one_day_name_replacement": float(np.mean(replacement)) if replacement else np.nan})
    return agg.merge(pd.DataFrame(turns), on=["support", "bucket"], how="left")


def marginal_alpha(years: tuple[int, ...]) -> pd.DataFrame:
    rows = []
    for year in years:
        f = forward_labels(year)
        sig = pd.read_parquet(B7 / "SIGNALS.parquet", filters=[("t", ">=", int(f.t.min())), ("t", "<=", int(f.t.max()))], columns=["t", "j", "score"])
        z = sig.merge(f[["t", "j", "ret20"]], on=["t", "j"], how="inner", validate="one_to_one")
        z["rank"] = z.groupby("t").score.rank(method="first", ascending=False)
        z["n"] = z.groupby("t").j.transform("size")
        z["universe_mean"] = z.groupby("t").ret20.transform("mean")
        masks = {
            "RANK1_10": z["rank"].le(10),
            "RANK11_20": z["rank"].between(11, 20),
            "RANK21_50": z["rank"].between(21, 50),
            "TOP5PCT_REMAINDER": z["rank"].gt(50) & z["rank"].le(np.ceil(.05 * z["n"])),
        }
        for bucket, mask in masks.items():
            q = z[mask]
            daily = q.groupby("t").agg(ret20=("ret20", "mean"), universe=("universe_mean", "first"))
            rows.append({"year": year, "bucket": bucket, "rows": len(q), "dates": len(daily), "mean_ret20": float(daily.ret20.mean()), "lift_vs_positive_gate_universe": float((daily.ret20 - daily.universe).mean()), "classification": "POSITIVE_ALPHA" if (daily.ret20 - daily.universe).mean() > .001 else "NEGATIVE_DILUTION" if (daily.ret20 - daily.universe).mean() < -.001 else "NEAR_ZERO_ALPHA"})
    out = pd.DataFrame(rows)
    dev = out[out.year.isin(YEARS_DEV)].groupby("bucket", as_index=False).agg(rows=("rows", "sum"), dates=("dates", "sum"), mean_ret20=("mean_ret20", "mean"), lift_vs_positive_gate_universe=("lift_vs_positive_gate_universe", "mean"))
    dev["year"] = "DEVELOPMENT_2020_2021"
    dev["classification"] = np.where(dev.lift_vs_positive_gate_universe > .001, "POSITIVE_ALPHA", np.where(dev.lift_vs_positive_gate_universe < -.001, "NEGATIVE_DILUTION", "NEAR_ZERO_ALPHA"))
    return pd.concat([out, dev], ignore_index=True)


def run_years(years: tuple[int, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    yearly, concentration = [], []
    for year in years:
        m, c = verify_a0(year)
        yearly.append(m); concentration.append(c)
        for arm in ARMS[1:]:
            _, folder, policy = execute_arm(year, arm)
            m, c = account_metrics(year, arm, folder, policy)
            yearly.append(m); concentration.append(c)
    return pd.DataFrame(yearly), pd.DataFrame(concentration)


def development() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    yearly, conc = run_years(YEARS_DEV)
    yearly.to_csv(HERE / "PORTFOLIO_ARM_YEARLY_DEVELOPMENT.csv", index=False)
    conc.to_csv(HERE / "PORTFOLIO_CONCENTRATION_DEVELOPMENT.csv", index=False)
    piv = yearly.pivot(index="arm", columns="year", values="annual_return")
    coherent = {}
    for arm in ARMS[1:]:
        delta = piv.loc[arm] - piv.loc["A0_TOP10"]
        coherent[arm] = {"return_delta_2020": float(delta[2020]), "return_delta_2021": float(delta[2021]), "same_direction": bool(np.sign(delta[2020]) == np.sign(delta[2021]))}
    # Frozen before 2022: coherent return preservation requires each-year delta >= -2pp.
    rw_identity = bool(np.allclose(piv.loc["A0_RW"], piv.loc["A0_TOP10"], rtol=0, atol=1e-12))
    # A0_RW is an attribution control. Under the frozen 1% per-order cap its
    # ten weights water-fill to 1% each, so identity equivalence cannot earn a
    # new candidate label.
    eligible = [a for a in ("A1_TOP20", "A2_TOP50", "A3_TOP5PCT") if coherent[a]["return_delta_2020"] >= -.02 and coherent[a]["return_delta_2021"] >= -.02]
    if eligible:
        candidate = max(eligible, key=lambda a: float((piv.loc[a] - piv.loc["A0_TOP10"]).mean()))
    else:
        candidate = "A0_TOP10"
    freeze = {
        "status": "FROZEN_BEFORE_2022_CONFIRMATION",
        "years_observed": [2020, 2021],
        "candidate": candidate,
        "coherence": coherent,
        "A0_RW_IDENTITY_EQUIVALENT_TO_A0": rw_identity,
        "development_rule": "Candidate must preserve return within -2pp in each of 2020 and 2021; primary ranking is mean return delta. Risk/concentration cannot rescue larger return dilution.",
        "confirmation_rule": "2022 candidate return delta must be >= -3pp, average exposure no more than 5pp below A0, and concentration improvement may not be solely lower exposure.",
        "no_2022_outcomes_read_by_this_stage": True,
        "no_parameter_search": True,
    }
    dump(HERE / "DEVELOPMENT_INTERPRETATION_FREEZE.json", freeze)
    print("DEVELOPMENT_COMPLETE", candidate)


def finalize() -> None:
    freeze = load(HERE / "DEVELOPMENT_INTERPRETATION_FREEZE.json")
    assert freeze["status"] == "FROZEN_BEFORE_2022_CONFIRMATION" and freeze["years_observed"] == [2020, 2021]
    dev = pd.read_csv(HERE / "PORTFOLIO_ARM_YEARLY_DEVELOPMENT.csv")
    devc = pd.read_csv(HERE / "PORTFOLIO_CONCENTRATION_DEVELOPMENT.csv")
    confirm, confirmc = run_years((YEAR_CONFIRM,))
    yearly = pd.concat([dev, confirm], ignore_index=True)
    conc = pd.concat([devc, confirmc], ignore_index=True)
    yearly.to_csv(HERE / "PORTFOLIO_ARM_YEARLY.csv", index=False)
    conc.to_csv(HERE / "PORTFOLIO_CONCENTRATION.csv", index=False)
    marginal = marginal_alpha((2020, 2021, 2022))
    marginal.to_csv(HERE / "MARGINAL_ALPHA_BY_RANK.csv", index=False)
    score = score_curve((2020, 2021, 2022))
    score.to_csv(HERE / "SCORE_RETURN_CURVE.csv", index=False)
    summarize(yearly, conc, marginal, score, freeze)


def summarize(yearly: pd.DataFrame, conc: pd.DataFrame, marginal: pd.DataFrame, score: pd.DataFrame, freeze: dict) -> None:
    base = yearly[yearly.arm == "A0_TOP10"].set_index("year")
    summary = {}
    for arm in ARMS:
        q = yearly[yearly.arm == arm].set_index("year")
        summary[arm] = {str(y): {k: float(q.loc[y, k]) for k in ["annual_return", "MaxDD", "average_exposure", "peak_exposure", "turnover", "fees", "average_holdings", "gross_HHI"]} for y in [2020, 2021, 2022]}
        summary[arm]["mean_return_delta_vs_A0"] = float((q.annual_return - base.annual_return).mean())
        summary[arm]["mean_MaxDD_delta_vs_A0"] = float((q.MaxDD - base.MaxDD).mean())
        summary[arm]["mean_HHI_delta_vs_A0"] = float((q.gross_HHI - base.gross_HHI).mean())
    candidate = freeze["candidate"]
    if candidate == "A0_TOP10":
        confirmed = False
    else:
        c = yearly[(yearly.arm == candidate) & (yearly.year == 2022)].iloc[0]
        b = base.loc[2022]
        confirmed = bool(c.annual_return - b.annual_return >= -.03 and c.average_exposure - b.average_exposure >= -.05)
    best = max(ARMS, key=lambda a: yearly[yearly.arm == a].annual_return.mean())
    a1 = yearly[yearly.arm == "A1_TOP20"].set_index("year")
    broader_dilutes = bool((a1.annual_return >= base.annual_return - .02).all() and (yearly[yearly.arm.isin(["A2_TOP50", "A3_TOP5PCT"])].groupby("arm").annual_return.mean() < base.annual_return.mean()).all())
    rw = yearly[yearly.arm == "A0_RW"].set_index("year")
    if np.allclose(rw.annual_return, base.annual_return, rtol=0, atol=1e-12):
        rank_effect = "NONE_UNDER_FROZEN_1PCT_PER_ORDER_CAP_A0_RW_EQUALS_A0"
    else:
        rank_effect = "POSITIVE" if (rw.annual_return - base.annual_return).mean() > 0 else "NEGATIVE"
    if confirmed and candidate == "A1_TOP20" and broader_dilutes:
        diagnosis = "B. MODERATE_BREADTH_SUPPORTED"
    elif confirmed and candidate == "A0_RW":
        diagnosis = "C. SCORE_WEIGHTING_SUPPORTED"
    elif confirmed:
        diagnosis = "A. EXTREME_CONCENTRATION_PROBLEM"
    elif best == "A0_TOP10":
        diagnosis = "D. TOP10_ALREADY_ECONOMICALLY_BEST"
    else:
        diagnosis = "E. MIXED / INCONCLUSIVE"
    def bucket(name: str) -> dict:
        q = marginal[(marginal.year.astype(str) == "DEVELOPMENT_2020_2021") & (marginal.bucket == name)].iloc[0]
        c = marginal[(marginal.year.astype(str) == "2022") & (marginal.bucket == name)].iloc[0]
        return {"development_lift": float(q.lift_vs_positive_gate_universe), "development_class": q.classification, "confirmation_lift": float(c.lift_vs_positive_gate_universe), "confirmation_class": c.classification}
    packet = {
        "PRIMARY_DIAGNOSIS": diagnosis,
        "AUTHORITATIVE_BASELINE": "CENTERED_TOP10_H10",
        "ARMS": summary,
        "MARGINAL_ALPHA_11_20": bucket("RANK11_20"),
        "MARGINAL_ALPHA_21_50": bucket("RANK21_50"),
        "MARGINAL_ALPHA_TOP5_REMAINDER": bucket("TOP5PCT_REMAINDER"),
        "BREADTH_EFFECT": diagnosis,
        "RANK_WEIGHT_EFFECT": rank_effect,
        "BEST_PREDECLARED_ARM_BY_MEAN_RETURN_DIAGNOSTIC_ONLY": best,
        "DEVELOPMENT_FROZEN_CANDIDATE": candidate,
        "CANDIDATE_EARNED": confirmed,
        "NEXT_PRIORITY": "RETAIN_CENTERED_TOP10_H10" if not confirmed else "PRESERVE_CANDIDATE_FOR_SEPARATE_PROMOTION_REVIEW",
        "NO_MODEL_TRAINING": True,
        "2023_OPENED": False,
        "SEALED_2024_2026_OPENED": False,
        "git_branch": "codex/minute-ret5-multiscale-autonomous-v2",
        "head": "2d6865f25324d5d2d6ac8532d4238af4e2693ed4",
    }
    dump(HERE / "DECISION_PACKET_BROADER_RANKING_PORTFOLIO.json", packet)
    lines = ["# 更宽排序组合构建审计", "", "全程复用冻结CENTERED fixed3分数、RAW正门、H10账户引擎及2020–2022已消费开发数据；没有训练模型，没有读取2023或2024–2026。", "", f"**PRIMARY_DIAGNOSIS = {diagnosis}**", "", "## 年度账户", "", yearly.to_markdown(index=False), "", "## 边际Alpha", "", marginal.to_markdown(index=False), "", "## 集中度", "", conc.to_markdown(index=False), "", "## 解释", "", f"2020–2021事先冻结候选：`{candidate}`；2022确认通过：`{confirmed}`。A0_RW在冻结1%单笔上限下退化为与A0相同的每名1%配置，因此不能把任何差异归因于权重。", "", "Top5%是信号可预测分辨率，不代表整个Top5%适合持仓；边际桶直接检验更低排名是否稀释经济收益。"]
    (HERE / "BROADER_RANKING_PORTFOLIO_REPORT.md").write_text("\n".join(lines) + "\n")
    print("FINAL_COMPLETE", diagnosis, candidate, confirmed)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["development", "finalize"])
    args = p.parse_args()
    development() if args.stage == "development" else finalize()
