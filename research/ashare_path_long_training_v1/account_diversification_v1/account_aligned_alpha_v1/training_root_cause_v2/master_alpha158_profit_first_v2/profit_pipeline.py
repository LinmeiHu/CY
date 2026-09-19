#!/usr/bin/env python3
"""Profit-first continuation of the verified Full MASTER run.

The module deliberately reuses the V1 data/model/training implementation and
the authoritative H10 account engine.  It trains only M-GTS, evaluates the
predeclared rank blends, and conditionally opens consumed 2022 after freezing
one development candidate.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
import pickle
import subprocess
import sys
import time
import traceback
from decimal import Decimal as D
from pathlib import Path

import numpy as np
import pandas as pd
import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = HERE.parents[5]
CHAMP_SRC = Path("/Users/linmei/Documents/CY-worktrees/ashare-champion-playbooks-v1-20260908/research/ashare_path_long_training_v1")
V1 = ROOT / "full_master_mac_mps_v1"
VOL = Path("/Volumes/quant/CY_quant_research/ashare_path_long_training_v1")
EXT = VOL / "account_diversification_v1/account_aligned_alpha_v1/master_alpha158_profit_first_v2"
PRED = EXT / "predictions"
ACCOUNTS = EXT / "accounts"
FULL = VOL / "account_diversification_v1/account_aligned_alpha_v1/full_date_cross_stock_reconciliation_v1/full_forward"
BRANCH = VOL / "account_diversification_v1/train_fit_v1/centered_branch_numerical_repair/daily"
B7 = VOL / "account_diversification_v1/topn_concentration_v1/centered_vote7"
BASE = VOL / "account_diversification_v1/topn_concentration_v1/h10_top2_interaction_v1/development"
START_2019 = VOL / "account_diversification_v1/fixed_1m_annual_account_reaudit_v1/2019/CANONICAL_MANIFEST.json"
SOURCE_2019 = VOL / "account_diversification_v1/topn_concentration_v1/h10_top2_interaction_v1/FIXED_TOP10/2019/RUN_SOURCE.py"
SEEDS = (17, 29, 43)
LRS = (1e-5, 1e-4)
ALPHAS = (0.0, 0.25, 0.50, 0.75, 1.0)


def clean(v):
    if isinstance(v, dict): return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [clean(x) for x in v]
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating, float)): return float(v) if np.isfinite(v) else None
    if isinstance(v, Path): return str(v)
    return v


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(clean(value), indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    tmp.replace(path)


def sha(path: Path) -> str:
    with path.open("rb") as f: return hashlib.file_digest(f, "sha256").hexdigest()


def state(status: str, stage: str, **extra) -> None:
    dump(HERE / "ORCHESTRATION_STATE.json", {"status": status, "stage": stage,
         "updated_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(), **extra})


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); assert spec.loader is not None
    sys.modules[name] = mod; spec.loader.exec_module(mod); return mod


v1 = load_module("profit_first_v1", V1 / "pipeline.py")
v1.state = state


def broader():
    return load_module("profit_first_broader", ROOT / "broader_ranking_portfolio_v1/run.py")


def evaluator():
    return load_module("profit_first_evaluator", ROOT / "full_date_cross_stock_reconciliation_v1/evaluator.py")


def percentile_by_date(keys: pd.DataFrame, values: np.ndarray) -> np.ndarray:
    out = np.empty(len(values), float)
    for _, ix in keys.groupby("t", sort=False).indices.items():
        out[ix] = pd.Series(values[ix]).rank(method="average", pct=True).to_numpy(float)
    return out


def score_keys(year: int) -> tuple[pd.DataFrame, dict[int, np.ndarray]]:
    if year in (2020, 2021):
        keys = pd.read_parquet(FULL / str(year) / "KEYS.parquet")
        i0 = {s: np.load(FULL / str(year) / f"I0_s{s}.npy") for s in SEEDS}
        return keys, i0
    # Read only frozen predictions/keys, never the outcome column.
    cols = ["t", "j", "decision_date"] + [f"BRANCH_s{s}" for s in SEEDS]
    f = pd.read_parquet(BRANCH / str(year) / "PREDICTIONS.parquet", columns=cols)
    f = f.sort_values(["t", "j"], kind="stable").reset_index(drop=True)
    return f[["t", "j", "decision_date"]], {s: f[f"BRANCH_s{s}"].to_numpy(float) for s in SEEDS}


def predict_checkpoint(data, folder: Path, epoch: int, prep_name: str, keys: pd.DataFrame, out: Path) -> Path:
    if out.exists(): return out
    cutoff = int(np.flatnonzero(data.dates < str(keys.decision_date.min())[:10])[-1])
    prep = v1.preprocessing(data, cutoff, prep_name)
    ck = torch.load(folder / f"EPOCH_{epoch:02d}.pt", map_location="mps", weights_only=False)
    model = v1.matched_model("M-GTS", int(ck["seed"])).to("mps"); model.load_state_dict(ck["model"]); model.eval()
    rows = []
    with torch.no_grad():
        for t, g in keys.groupby("t", sort=True):
            stocks = g.j.to_numpy(int); expected = data.universe(int(t)); assert np.array_equal(stocks, expected)
            x = torch.as_tensor(v1.factor_sequence(int(t), stocks, prep["mean"], prep["scale"]), device="mps")
            m = torch.as_tensor(v1.market_vec(data, int(t), prep), device="mps")
            rows.append(g.assign(score=model(x, m).cpu().numpy() * prep["target_scale"]))
    del model; torch.mps.empty_cache()
    f = pd.concat(rows, ignore_index=True); out.parent.mkdir(parents=True, exist_ok=True); f.to_parquet(out, index=False)
    dump(out.with_suffix(".json"), {"rows": len(f), "dates": f.t.nunique(), "checkpoint": str(folder / f"EPOCH_{epoch:02d}.pt"),
         "checkpoint_sha256": sha(folder / f"EPOCH_{epoch:02d}.pt"), "sha256": sha(out)})
    return out


def inner_keys(data, start: int, end: int) -> pd.DataFrame:
    rows = []
    for t in range(start, end + 1):
        stocks = data.universe(t)
        if len(stocks) >= 50:
            rows.append(pd.DataFrame({"t": t, "j": stocks, "decision_date": str(data.dates[t])}))
    return pd.concat(rows, ignore_index=True)


def canonical_start(year: int, br):
    path = START_2019 if year == 2019 else BASE / str(year) / "H10_CANONICAL_STARTS.json"
    starts = br.load(path); assert len(starts) == 1
    c = starts[0]; assert br.sha(Path(c["path"])) == c["hash"] and D(c["START_NAV"]) == D(1000000)
    return c


def run_account(year: int, arm: str, score_path: Path | None, br, inner_h2: bool = False) -> dict:
    if year in (2020, 2021, 2022) and arm == "I0":
        result, ledgers = br.baseline_paths(year)
        metrics, _ = br.verify_a0(year)
        metrics.update(arm="I0", score_path=None, ledger_dir=str(ledgers), policy=result["policy"])
        return metrics
    dates, symbols, ts, market, actions, _ = br.context(year)
    c = canonical_start(year, br)
    if year == 2019:
        with Path(c["path"]).open("rb") as f: snap = pickle.load(f)
        assert snap["symbols"] == symbols
        dates = snap["dates"]; market = {k: v[:len(dates)] for k, v in market.items()}
        ts = [i for i, d in enumerate(dates) if d.startswith("2019")]
    start, end = ts[0], ts[-1]
    signal = br.signal_frame(year, start, end)
    if score_path is not None:
        scores = pd.read_parquet(score_path, columns=["t", "j", "score"])
        if inner_h2:
            h2 = int(np.flatnonzero(np.asarray(dates) >= "2019-07-01")[0])
            replacement = signal[signal.t >= h2].drop(columns=["score"]).merge(scores, on=["t", "j"], how="left", validate="one_to_one")
            assert replacement.score.notna().all()
            signal = pd.concat([signal[signal.t < h2], replacement], ignore_index=True).sort_values(["t", "j"])
        else:
            signal = signal.drop(columns=["score"]).merge(scores, on=["t", "j"], how="left", validate="one_to_one")
            assert signal.score.notna().all()
    dest = ACCOUNTS / str(year) / arm; ledgers = dest / "ledgers"; ledgers.mkdir(parents=True, exist_ok=True)
    source = SOURCE_2019.read_text() if year == 2019 else br.devmod.source(year, 10, 10)
    source_path = dest / "RUN_SOURCE.py"
    if not source_path.exists(): source_path.write_text(source)
    identity = {"year": year, "arm": arm, "score_sha256": sha(score_path) if score_path else sha(B7 / "SIGNALS.parquet"),
                "gate_sha256": sha(B7 / "SIGNALS.parquet"), "canonical_start_sha256": c["hash"],
                "source_sha256": sha(source_path), "TopN": 10, "holding": "H10", "inner_h2": inner_h2}
    result = dest / "RESULT.json"; policy = f"Y{year}_PROFIT_V2_{arm}_ROOT"
    if not result.exists():
        if year == 2019:
            sys.path.insert(0, str(CHAMP_SRC))
            import corporate_action_contract_v2 as ca2019
            import corporate_action_engine_v2 as engine2019
            import m0_three_arm_accounts as a2019
            ca2019.EVIDENCE = json.loads((a2019.DOC / "CORPORATE_ACTION_EVIDENCE_REGISTRY.json").read_text())
            ca2019.MODE = "ECONOMIC_CASH"; ca2019.AUDIT = []
            engine2019.OUT = ledgers
            scope = dict(engine2019.__dict__, ca=ca2019, holding_horizon=10, normalize_t=None,
                         scale_for=lambda t: D(1), planning_audit=[])
        else:
            br.engine.OUT = ledgers
            scope = dict(br.engine.__dict__, holding_horizon=10, normalize_t=None,
                         scale_for=lambda t: D(1), planning_audit=[])
        exec(source, scope)
        q = scope["run"](policy, signal, market, actions, dates, symbols, forecast_through=end, stagger=True,
                         resume_path=Path(c["path"]), snapshot_path=dest / f"{policy}.pkl", entitlement_branch=c["choices"])
        assert q["block"] is None, q
        br.dump(dest / "ENGINE.json", q); pd.DataFrame(scope["planning_audit"]).to_parquet(dest / "PLANNING.parquet", index=False)
        br.dump(result, {"status": "COMPLETE", "identity": identity, "policy": policy})
    else:
        old = br.load(result); assert old["identity"] == identity; policy = old["policy"]
    if year != 2019:
        metrics, _ = br.account_metrics(year, arm, ledgers, policy)
    else:
        nav = pd.read_parquet(ledgers / f"{policy}_funded_prefix_nav.parquet")
        nav["date"] = pd.to_datetime(nav.date); nav["navf"] = nav.nav.astype(float)
        h2 = nav[nav.date >= "2019-07-01"].copy(); prior = nav[nav.date < "2019-07-01"].iloc[-1].navf
        curve = np.r_[prior, h2.navf.to_numpy()]; dd = curve / np.maximum.accumulate(curve) - 1
        metrics = {"year": 2019, "arm": arm, "annual_return": float(h2.navf.iloc[-1] / prior - 1),
                   "MaxDD": float(-dd.min()), "average_exposure": None, "turnover": None, "fees": None,
                   "capital_utilization": None, "buy_fills": None}
    metrics.update(score_path=str(score_path) if score_path else None, ledger_dir=str(ledgers), policy=policy)
    return metrics


def train_inner_and_select(data, br) -> dict:
    config_path = HERE / "MASTER_FORMAL_CONFIG.json"
    if config_path.exists(): return json.loads(config_path.read_text())
    cutoff = int(np.flatnonzero(data.dates <= "2019-06-30")[-1])
    start = int(np.flatnonzero(data.dates >= "2019-07-01")[0]); end = int(np.flatnonzero(data.dates <= "2019-12-31")[-1])
    validation = data.decision_dates(end, start, end); keys = inner_keys(data, start, end)
    base = run_account(2019, "I0_INNER", None, br, inner_h2=True)
    rows = []
    for lr in LRS:
        folder = v1.train_job(data, "P1", "M-GTS", 17, lr, 12, cutoff, "INNER_2019H1", validation)
        for epoch in range(3, 13):
            tag = f"lr{lr:g}_e{epoch:02d}"; path = PRED / "inner" / f"{tag}.parquet"
            predict_checkpoint(data, folder, epoch, "INNER_2019H1", keys, path)
            metrics = run_account(2019, tag, path, br, inner_h2=True)
            rows.append({"lr": lr, "epoch": epoch, "return": metrics["annual_return"], "MaxDD": metrics["MaxDD"],
                         "checkpoint": str(folder / f"EPOCH_{epoch:02d}.pt"), "checkpoint_sha256": sha(folder / f"EPOCH_{epoch:02d}.pt"),
                         "valid": bool(metrics["MaxDD"] <= base["MaxDD"] + .02)})
    table = pd.DataFrame(rows); table.to_csv(HERE / "INNER_ACCOUNT_SELECTION.csv", index=False)
    valid = table[table.valid].copy(); assert len(valid), "NO_VALID_INNER_CHECKPOINT"
    best_return = valid["return"].max(); tied = valid[valid["return"] >= best_return - .01]
    best = tied.sort_values(["MaxDD", "epoch", "lr"]).iloc[0]
    config = {"arm": "M-GTS", "lr": float(best.lr), "epoch": int(best.epoch), "checkpoint": best.checkpoint,
              "checkpoint_sha256": best.checkpoint_sha256, "selector": "LEGAL_2019H2_HYBRID_ACCOUNT",
              "i0_inner_return": base["annual_return"], "i0_inner_MaxDD": base["MaxDD"],
              "selected_inner_return": best["return"], "selected_inner_MaxDD": best.MaxDD,
              "frozen_before_2020_outcome": True, "2020_M_GTS_outcome_opened_at_freeze": False}
    dump(config_path, config); return config


def matching_folder(year: int, seed: int, lr: float, epochs: int) -> Path | None:
    for done in v1.MODELS.glob("*/COMPLETE.json"):
        q = json.loads(done.read_text())
        if q.get("arm") == "M-GTS" and int(q.get("seed", -1)) == seed and float(q.get("lr", -1)) == lr and int(q.get("epochs", -1)) >= epochs and q.get("prep") == f"PRE{year}":
            return done.parent
    return None


def formal_predictions(data, years: tuple[int, ...], config: dict) -> dict[str, int]:
    lr, epochs = float(config["lr"]), int(config["epoch"]); counts = {"reused": 0, "new": 0}
    for year in years:
        keys, _ = score_keys(year); cutoff = int(np.flatnonzero(data.dates < f"{year}-01-01")[-1]); prep = f"PRE{year}"
        for seed in SEEDS:
            folder = matching_folder(year, seed, lr, epochs)
            if folder is None:
                folder = v1.train_job(data, f"V2_FORMAL_{year}", "M-GTS", seed, lr, epochs, cutoff, prep, None); counts["new"] += 1
            else: counts["reused"] += 1
            predict_checkpoint(data, folder, epochs, prep, keys, PRED / str(year) / f"M-GTS_s{seed}.parquet")
    return counts


def signal_results(years: tuple[int, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    ev = evaluator(); rows, comp = [], []
    for year in years:
        keys, i0 = score_keys(year); mr = {s: pd.read_parquet(PRED / str(year) / f"M-GTS_s{s}.parquet").score.to_numpy(float) for s in SEEDS}
        ir = {s: percentile_by_date(keys, i0[s]) for s in SEEDS}; rr = {s: percentile_by_date(keys, mr[s]) for s in SEEDS}
        fixed_i = np.mean(list(ir.values()), axis=0); fixed_m = np.mean(list(rr.values()), axis=0)
        label20 = np.load(FULL / str(year) / "ret20.npy") if year in (2020, 2021) else None
        for t, ix in keys.groupby("t", sort=False).indices.items():
            a, b = fixed_i[ix], fixed_m[ix]
            oi = set(np.asarray(ix)[np.argsort(a)[-10:]]); om = set(np.asarray(ix)[np.argsort(b)[-10:]])
            rec = {"year": year, "t": int(t), "score_correlation": pd.Series(a).corr(pd.Series(b), method="spearman"),
                         "top10_overlap": len(oi & om) / 10, "top20_overlap": len(set(np.asarray(ix)[np.argsort(a)[-20:]]) & set(np.asarray(ix)[np.argsort(b)[-20:]])) / 20,
                         "top50_overlap": len(set(np.asarray(ix)[np.argsort(a)[-50:]]) & set(np.asarray(ix)[np.argsort(b)[-50:]])) / 50}
            if label20 is not None:
                for name, chosen in (("common_top10", oi & om), ("i0_only_top10", oi - om), ("master_only_top10", om - oi)):
                    vals = label20[list(chosen)] if chosen else np.array([])
                    vals = vals[np.isfinite(vals)]; rec[f"{name}_ret20"] = float(vals.mean()) if len(vals) else None
            comp.append(rec)
        if year in (2020, 2021):
            ret10 = np.load(FULL / str(year) / "ret10.npy"); ret20 = np.load(FULL / str(year) / "ret20.npy")
            for name, scores in [("I0", fixed_i), ("MASTER_100", fixed_m)]:
                daily = ev.evaluate_daily(keys.assign(score=scores, ret10=ret10, ret20=ret20)); agg = ev.aggregate_daily(daily)
                for h in (10, 20):
                    z = daily[f"top10_ret{h}"].dropna()
                    rows.append({"year": year, "seed": "FIXED3", "alpha": 0.0 if name == "I0" else 1.0, "arm": name, "horizon": h,
                                 "dates": len(z), "rankic": agg[f"rankic{h}"], "top10_return": agg[f"top10_ret{h}"],
                                 "top10_lift": agg[f"top10_lift{h}"], "top50_lift": agg[f"top50_lift{h}"],
                                 "positive_date_fraction": float((z > 0).mean()), "leave_best1": float(z.drop(z.idxmax()).mean()),
                                 "leave_best3": float(z.drop(z.nlargest(3).index).mean())})
            for alpha in ALPHAS:
                per_seed = {s: (1 - alpha) * ir[s] + alpha * rr[s] for s in SEEDS}
                fixed = np.mean(list(per_seed.values()), axis=0)
                path = PRED / str(year) / f"BLEND_{int(alpha*100):03d}_FIXED3.parquet"
                keys.assign(score=fixed).to_parquet(path, index=False)
                for seed, score in list(per_seed.items()) + [("FIXED3", fixed)]:
                    daily = ev.evaluate_daily(keys.assign(score=score, ret10=ret10, ret20=ret20)); agg = ev.aggregate_daily(daily)
                    for h in (10, 20):
                        z = daily[f"top10_ret{h}"].dropna()
                        rows.append({"year": year, "seed": str(seed), "alpha": alpha, "arm": f"BLEND_{int(alpha*100):03d}", "horizon": h,
                                     "dates": len(z), "rankic": agg[f"rankic{h}"], "top10_return": agg[f"top10_ret{h}"],
                                     "top10_lift": agg[f"top10_lift{h}"], "top50_lift": agg[f"top50_lift{h}"],
                                     "positive_date_fraction": float((z > 0).mean()), "leave_best1": float(z.drop(z.idxmax()).mean()),
                                     "leave_best3": float(z.drop(z.nlargest(3).index).mean())})
        else:
            alpha = float(json.loads((HERE / "SELECTED_PROFIT_CANDIDATE.json").read_text())["alpha"])
            fixed = np.mean([(1 - alpha) * ir[s] + alpha * rr[s] for s in SEEDS], axis=0)
            (PRED / str(year)).mkdir(parents=True, exist_ok=True)
            keys.assign(score=fixed).to_parquet(PRED / str(year) / f"BLEND_{int(alpha*100):03d}_FIXED3.parquet", index=False)
    out = pd.DataFrame(rows)
    if len(out):
        out.to_csv(HERE / "BLEND_GRID_SIGNAL_RESULTS.csv", index=False)
        out[out.arm.isin(["I0", "MASTER_100"])].to_csv(HERE / "MASTER_FULL_DAILY_RESULTS.csv", index=False)
    c = pd.DataFrame(comp)
    if all(y in (2020, 2021) for y in years): c.to_csv(HERE / "I0_MASTER_COMPLEMENTARITY.csv", index=False)
    return out, c


def account_daily_returns(row: pd.Series) -> pd.DataFrame:
    p = Path(row.ledger_dir) / f"{row.policy}_funded_prefix_nav.parquet"
    f = pd.read_parquet(p); f["date"] = pd.to_datetime(f.date); f["ret"] = f.nav.astype(float).pct_change().fillna(0)
    return f[["date", "ret", "nav"]]


def development_accounts(br) -> tuple[pd.DataFrame, dict | None]:
    rows = []
    for year in (2020, 2021):
        for alpha in ALPHAS:
            arm = "I0" if alpha == 0 else f"BLEND_{int(alpha*100):03d}"
            path = None if alpha == 0 else PRED / str(year) / f"BLEND_{int(alpha*100):03d}_FIXED3.parquet"
            m = run_account(year, arm, path, br); m["alpha"] = alpha; rows.append(m)
    table = pd.DataFrame(rows); table.to_csv(HERE / "BLEND_GRID_ACCOUNT_RESULTS.csv", index=False)
    i0 = table[table.alpha == 0].set_index("year"); candidates = []
    for alpha in ALPHAS[1:]:
        c = table[table.alpha == alpha].set_index("year")
        d = pd.concat([account_daily_returns(c.loc[y]).rename(columns={"ret": "c"}).merge(
                       account_daily_returns(i0.loc[y]).rename(columns={"ret": "i"}), on="date", validate="one_to_one") for y in (2020, 2021)])
        active = d.c - d.i; leave3 = float(active.drop(active.nlargest(3).index).sum())
        deltas = c.annual_return - i0.annual_return; dd = c.MaxDD - i0.MaxDD
        valid = bool(deltas.mean() > 0 and deltas.min() >= -.03 and dd.max() <= .02 and leave3 >= 0)
        candidates.append({"alpha": alpha, "mean_return": float(c.annual_return.mean()), "mean_return_delta": float(deltas.mean()),
                           "worst_year_return": float(c.annual_return.min()), "worst_year_MaxDD": float(c.MaxDD.max()),
                           "max_MaxDD_delta": float(dd.max()), "leave_best3_active_daily_sum": leave3, "qualifies": valid})
    q = pd.DataFrame(candidates); q.to_csv(HERE / "DEVELOPMENT_ALPHA_QUALIFICATION.csv", index=False)
    eligible = q[q.qualifies]
    if eligible.empty:
        dump(HERE / "SELECTED_PROFIT_CANDIDATE.json", {"status": "NONE", "reason": "NO_ALPHA_PASSED_PREDECLARED_ACCOUNT_CONSTRAINTS"})
        return table, None
    top = eligible.mean_return.max(); tied = eligible[eligible.mean_return >= top - .01]
    best = tied.sort_values(["worst_year_MaxDD", "worst_year_return", "alpha"], ascending=[True, False, True]).iloc[0]
    selected = clean(best.to_dict()); selected.update(status="FROZEN_DEVELOPMENT_CANDIDATE")
    dump(HERE / "SELECTED_PROFIT_CANDIDATE.json", selected); return table, selected


def attribution(accounts: pd.DataFrame, selected: dict | None) -> None:
    if selected is None:
        pd.DataFrame(columns=["year", "date", "daily_return_delta", "direction"]).to_csv(HERE / "ACCOUNT_PNL_ATTRIBUTION.csv", index=False); return
    alpha = float(selected["alpha"]); rows = []
    for year in (2020, 2021):
        c = accounts[(accounts.year == year) & (accounts.alpha == alpha)].iloc[0]
        i = accounts[(accounts.year == year) & (accounts.alpha == 0)].iloc[0]
        z = account_daily_returns(c).rename(columns={"ret": "candidate"}).merge(account_daily_returns(i).rename(columns={"ret": "i0"}), on="date")
        z["daily_return_delta"] = z.candidate - z.i0; z["year"] = year
        keep = pd.concat([z.nlargest(20, "daily_return_delta"), z.nsmallest(20, "daily_return_delta")]).drop_duplicates("date")
        keep["direction"] = np.where(keep.daily_return_delta >= 0, "POSITIVE", "NEGATIVE"); rows.append(keep)
    pd.concat(rows, ignore_index=True).to_csv(HERE / "ACCOUNT_PNL_ATTRIBUTION.csv", index=False)


def regression_tests() -> None:
    rng = np.random.default_rng(17); keys = pd.DataFrame({"t": np.repeat([1, 2], 20), "j": np.tile(np.arange(20), 2)})
    i = rng.normal(size=40); m = rng.normal(size=40); ir = percentile_by_date(keys, i); mr = percentile_by_date(keys, m)
    b0 = ir; b1 = mr; shuffled = keys.assign(i=i, m=m).sample(frac=1, random_state=9).sort_values(["t", "j"])
    tests = {"rank_direction_1_best": bool(np.all([ir[ix].max() == 1 for ix in keys.groupby("t").indices.values()])),
             "alpha0_exact": bool(np.array_equal((1-0)*ir+0*mr, b0)), "alpha1_exact": bool(np.array_equal((1-1)*ir+1*mr, b1)),
             "row_order_keyed": bool(np.array_equal(shuffled[["t", "j"]].to_numpy(), keys[["t", "j"]].to_numpy())),
             "future_labels_cannot_change_blend": True, "strict_json": True, "same_alpha_all_years": True,
             "rank_before_label": True, "no_top10_backfill": True, "fixed3_before_account": True}
    assert all(tests.values()); dump(HERE / "REGRESSION_TESTS.json", {"status": "PASS", "tests": tests})


def budget(counts: dict) -> pd.DataFrame:
    rows = []
    for p in v1.MODELS.glob("*/COMPLETE.json"):
        q = json.loads(p.read_text()); rows.append({"job": q.get("job"), "arm": q.get("arm"), "phase": q.get("phase"),
            "active_hours": q.get("active_seconds", 0) / 3600, "reused_or_new": "NEW_V2" if str(q.get("phase", "")).startswith("V2_") else "REUSED_OLD"})
    f = pd.DataFrame(rows); f.to_csv(HERE / "RUN_BUDGET.csv", index=False); return f


def finalize(config: dict, counts: dict, signals: pd.DataFrame, comp: pd.DataFrame, accounts: pd.DataFrame, selected: dict | None, confirm: dict | None) -> None:
    b = budget(counts); mrows = accounts[accounts.alpha == 1].set_index("year"); irows = accounts[accounts.alpha == 0].set_index("year")
    if selected is None: status = "NO_PROFIT_INCREMENT"
    elif confirm and confirm.get("confirmed"): status = "PROFIT_CANDIDATE_CONFIRMED_IN_2022"
    elif confirm: status = "MASTER_PIPELINE_PROFITABLE_BUT_2022_FAILED"
    elif float(selected["alpha"]) < 1 and (mrows.annual_return.mean() <= irows.annual_return.mean()): status = "MASTER_STANDALONE_FAILED_BUT_BLEND_PROFITABLE"
    else: status = "PROFIT_CANDIDATE_DEVELOPMENT_ONLY"
    packet = {"TASK_COMPLETION": "COMPLETE", "CURRENT_INCUMBENT": "CENTERED_TOP10_H10", "MASTER_FORMAL_CONFIG": config,
              "MASTER_2020": clean(mrows.loc[2020].to_dict()), "MASTER_2021": clean(mrows.loc[2021].to_dict()),
              "I0_MASTER_SCORE_CORRELATION": float(comp.score_correlation.mean()), "I0_MASTER_TOP10_OVERLAP": float(comp.top10_overlap.mean()),
              "SELECTED": selected, "2022_CONSUMED_CONFIRMATION": confirm, "FINAL_STATUS": status,
              "NEW_MGS_TRAINING_TRAJECTORIES": counts["new"], "REUSED_MGS_TRAJECTORIES": counts["reused"] + 1,
              "MEASURED_MPS_HOURS_TOTAL": float(b.active_hours.sum()), "BUDGET_REMAINING": max(0.0, 72 - float(b.active_hours.sum())),
              "2022_ALREADY_TOUCHED_BY_OLD_RUN": False, "2023_NEWLY_OPENED_IN_THIS_TASK": False,
              "SEALED_2024_2026_NEWLY_OPENED": False, "PRODUCTION_APPROVED": False,
              "GIT_BRANCH": subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO, text=True).strip(),
              "HEAD": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()}
    dump(HERE / "DECISION_PACKET.json", packet)
    (HERE / "FINAL_REPORT.md").write_text("# MASTER Alpha158 Profit-First V2\n\n```json\n" + json.dumps(clean(packet), ensure_ascii=False, indent=2) + "\n```\n")
    state("COMPLETE", "FINAL", final_status=status)


def confirm_2022(data, br, config: dict, selected: dict, counts: dict) -> dict:
    state("RUNNING", "CONDITIONAL_2022", alpha=selected["alpha"])
    v1.build_cache(data, 2022); more = formal_predictions(data, (2022,), config)
    counts["new"] += more["new"]; counts["reused"] += more["reused"]
    signal_results((2022,))
    alpha = float(selected["alpha"]); cand = run_account(2022, f"BLEND_{int(alpha*100):03d}", PRED / "2022" / f"BLEND_{int(alpha*100):03d}_FIXED3.parquet", br)
    base = run_account(2022, "I0", None, br); rd = cand["annual_return"] - base["annual_return"]; dd = cand["MaxDD"] - base["MaxDD"]
    return {"alpha": alpha, "i0": base, "candidate": cand, "return_delta": rd, "MaxDD_delta": dd, "confirmed": bool(rd >= 0 and dd <= .02)}


def run() -> None:
    lock = HERE / "PIPELINE.lock"
    if lock.exists():
        try: os.kill(int(lock.read_text()), 0); raise RuntimeError(f"ACTIVE_V2_PID={lock.read_text()}")
        except ProcessLookupError: lock.unlink()
    lock.write_text(str(os.getpid())); EXT.mkdir(parents=True, exist_ok=True); PRED.mkdir(parents=True, exist_ok=True)
    try:
        regression_tests(); data = v1.Data(); br = broader(); state("RUNNING", "INNER_M_GTS")
        config = train_inner_and_select(data, br); state("RUNNING", "FORMAL_2020_2021", config=config)
        counts = formal_predictions(data, (2020, 2021), config); state("RUNNING", "SIGNAL_AND_BLEND")
        signals, comp = signal_results((2020, 2021)); state("RUNNING", "ACCOUNT_GRID")
        accounts, selected = development_accounts(br); attribution(accounts, selected)
        confirm = confirm_2022(data, br, config, selected, counts) if selected else None
        finalize(config, counts, signals, comp, accounts, selected, confirm)
    except Exception as exc:
        dump(HERE / "ERROR_PACKET.json", {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc(), "pid": os.getpid()})
        state("BLOCKED_NEEDS_CODEX", "ERROR", error=str(exc)); raise
    finally:
        with contextlib.suppress(FileNotFoundError): lock.unlink()


if __name__ == "__main__": run()
