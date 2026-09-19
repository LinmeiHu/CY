#!/usr/bin/env python3
"""Formal 2020/2021 continuation, fixed3, and account replay after inner freeze."""
from __future__ import annotations

import gc
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("allstock_core", HERE / "run.py")
core = importlib.util.module_from_spec(spec); assert spec.loader is not None
sys.modules["allstock_core"] = core; spec.loader.exec_module(core)

MANIFEST = core.DOC / "FROZEN_ALPHA_CHECKPOINT_MANIFEST.json"
PRED = core.EXT / "predictions"
CACHE = core.EXT / "forward_inputs"


def checkpoint_manifest() -> dict[tuple[int, int], dict]:
    q = json.loads(MANIFEST.read_text())
    rows = {(int(x["year"]), int(x["seed"])): x for x in q["checkpoints"] if int(x["year"]) in (2020, 2021, 2022)}
    assert set(rows) == {(y, s) for y in (2020, 2021, 2022) for s in core.SEEDS}
    for x in rows.values():
        assert core.sha(Path(x["checkpoint_path"])) == x["checkpoint_sha256"]
    return rows


class FormalData(core.DateData):
    def __init__(self, year: int):
        self.idx = pd.read_parquet(core.common.OUT / "index.parquet")
        self.t = self.idx.t.to_numpy()
        self.dates = np.array(json.loads((core.common.PANEL / "axes.json").read_text())["dates"])
        assert year in (2020, 2021, 2022) and self.dates[-1] < "2024"
        self.cut = int(np.flatnonzero(self.dates < f"{year}-01-01")[-1])
        self.end = int(np.flatnonzero(self.dates <= f"{year}-12-31")[-1])
        self.raw = np.load(core.common.OUT / "raw.npy", mmap_mode="r")
        self.legs = np.load(core.common.OUT / "legs.npy", mmap_mode="r")
        self.factors = np.load(core.common.OUT / "factors.npy", mmap_mode="r")
        self.labels = np.load(core.common.OUT / "labels.npy", mmap_mode="r")
        self.y = core.nested.mature(self.labels, self.t, self.cut)
        self.eval_y = core.nested.mature(self.labels, self.t, self.end)
        self.train = np.flatnonzero(np.isfinite(self.y[:, 1]))
        self.dev_rows = np.flatnonzero((self.t > self.cut) & (self.t <= self.end) & np.isfinite(self.eval_y[:, 1]))
        self.offset = np.load(core.VOL / f"M0_CONTEXT_{year}_offset.npy", mmap_mode="r")
        self.date_rows = {int(t): g.index.to_numpy() for t, g in self.idx.groupby("t", sort=False)}
        mature = self.idx.iloc[self.train]
        self.year_dates = {int(y): np.array(sorted(g.t.unique()), np.int64) for y, g in mature.groupby("year")}
        self.years = sorted(self.year_dates)
        first, last = pd.Timestamp(mature.decision_date.min()), pd.Timestamp(mature.decision_date.max())
        assert first + pd.DateOffset(years=12) <= last
        expected = {2020: 443350, 2021: 522584}.get(year)
        if expected is not None:
            assert len(self.train) == expected, (year, len(self.train), expected)


def percentile_by_date(keys: pd.DataFrame, values: np.ndarray) -> np.ndarray:
    out = np.empty(len(values), np.float64)
    for _, ix in keys.groupby("t", sort=False).indices.items():
        out[ix] = pd.Series(values[ix]).rank(method="average", pct=True).to_numpy(float)
    return out


def selected() -> dict:
    path = HERE / "INNER_SELECTION.json"
    assert path.exists(), "INNER_SELECTION_NOT_COMPLETE"
    q = json.loads(path.read_text())
    assert q["status"] == "FROZEN_BEFORE_2020_2021" and q["formal_outcomes_opened"] is False
    return q


def formal_train(year: int, seed: int, arm: str, choice: dict, manifests: dict) -> Path:
    relation = arm == "RELATION"
    lr, steps = float(choice["lr"]), int(choice["steps"])
    data = FormalData(year)
    start = Path(manifests[(year, seed)]["checkpoint_path"])
    core.train_trajectory(data, start, "FORMAL", year, seed, relation, lr, steps)
    return core.trajectory_dir("FORMAL", year, seed, relation, lr) / f"step{steps}.pt"


def cache_paths(year: int) -> tuple[Path, Path, Path, Path]:
    root = CACHE / str(year)
    return root / "KEYS.parquet", root / "raw.npy", root / "legs.npy", root / "offset.npy"


def source_frame(year: int) -> pd.DataFrame:
    if year in (2020, 2021):
        return pd.read_parquet(core.FULL / str(year) / "KEYS.parquet")
    assert year == 2022
    path = core.VOL / "account_diversification_v1/train_fit_v1/centered_branch_numerical_repair/daily/2022/PREDICTIONS.parquet"
    return pd.read_parquet(path, columns=["t", "j", "decision_date", "ret20", "BRANCH_s17", "BRANCH_s29", "BRANCH_s43"])


def build_forward_cache(year: int) -> None:
    complete = CACHE / str(year) / "COMPLETE.json"
    keys_path, raw_path, legs_path, offset_path = cache_paths(year)
    if complete.exists():
        q = json.loads(complete.read_text())
        assert all(p.exists() for p in (keys_path, raw_path, legs_path, offset_path))
        assert q["rows"] == len(pd.read_parquet(keys_path))
        return
    core.update_state("RUNNING", "P4_BUILD_DAILY_CACHE", year=year)
    source = (core.FULL / str(year) / "KEYS.parquet") if year in (2020, 2021) else (
        core.VOL / "account_diversification_v1/train_fit_v1/centered_branch_numerical_repair/daily/2022/PREDICTIONS.parquet")
    keys = source_frame(year)[["t", "j", "decision_date"]].sort_values(["t", "j"], kind="stable").reset_index(drop=True)
    assert not keys.duplicated(["t", "j"]).any() and keys.decision_date.str.startswith(str(year)).all()
    root = CACHE / str(year); root.mkdir(parents=True, exist_ok=True)
    keys.to_parquet(keys_path, index=False)
    n = len(keys)
    raw = np.lib.format.open_memmap(raw_path, mode="w+", dtype="float32", shape=(n, 4, 32, 13))
    legs = np.lib.format.open_memmap(legs_path, mode="w+", dtype="float32", shape=(n, 4, 10, 18))
    offsets = np.lib.format.open_memmap(offset_path, mode="w+", dtype="float32", shape=(n, 3))
    dates = np.array(json.loads((core.common.PANEL / "axes.json").read_text())["dates"])
    end = int(np.searchsorted(dates, f"{year + 1}-01-01"))
    arrays = {k: core.common.get(k)[:end] for k in ["safe", "history", "adj_close", "adj_open", "adj_high",
              "adj_low", "adj_volume", "close", "circulating_shares", "turnover_fraction", "amount",
              "industry_return", "market"]}
    market = arrays["market"][:, 3]
    market_returns = []
    for h in (3, 20, 60):
        v = np.full(end, np.nan); v[h:] = market[h:] / market[:-h] - 1; market_returns.append(v)
    encoder = core.common.old("features")
    from account_daily_inference import stock_inputs
    base = joblib.load(core.VOL / f"M0_CONTEXT_{year}.joblib")
    registered_index = pd.read_parquet(core.common.OUT / "index.parquet")
    registered_index = registered_index[registered_index.year == year]
    banks = [np.load(core.common.OUT / f"{name}.npy", mmap_mode="r") for name in ("raw", "legs", "factors")]
    groups = list(keys.groupby("j", sort=True))
    for no, (j, group) in enumerate(groups, 1):
        pos = group.index.to_numpy(); tt = group.t.to_numpy(int)
        r, l, factors = stock_inputs(int(j), tt, arrays, market_returns, encoder)
        old = registered_index[registered_index.j == j]
        if len(old):
            loc = np.searchsorted(tt, old.t.to_numpy(int)); assert np.array_equal(tt[loc], old.t.to_numpy(int))
            for bank, value in zip(banks, (r, l, factors)):
                assert np.array_equal(bank[old.index], value[loc], equal_nan=True), (year, int(j), "FEATURE_PARITY")
        scaled = base["scale"].transform(np.nan_to_num(factors).astype("float64"))
        off = np.column_stack([fit.predict(scaled) for fit in base["fits"]]).astype("float32")
        raw[pos], legs[pos], offsets[pos] = r, l, off
        if no % 50 == 0:
            raw.flush(); legs.flush(); offsets.flush()
            core.dump(root / "PROGRESS.json", {"year": year, "stocks_done": no, "stocks_total": len(groups)})
    raw.flush(); legs.flush(); offsets.flush()
    core.dump(complete, {"status": "COMPLETE", "year": year, "rows": n, "dates": int(keys.t.nunique()),
         "source_keys_sha256": core.sha(source), "raw_bytes": raw_path.stat().st_size,
         "legs_bytes": legs_path.stat().st_size, "offset_bytes": offset_path.stat().st_size,
         "feature_parity_all_registered_rows": True, "float_precision": "float32"})


def uniform_forward(model, x, legs):
    pred, z, weights = model.core(x[..., :13], legs)
    n = len(z)
    if n > 1:
        u = model.norm(z - z.mean(0, keepdim=True)); v = model.v(u)
        context = (v.sum(0, keepdim=True) - v) / (n - 1)
        z = z + model.o(context); pred = model.core.pred(z)
    pred = torch.cat([pred[:, :3] + 10 * x[:, 0, 0, 13:16], pred[:, 3:]], 1)
    return pred, z, weights


def attention_statistics(model, z: torch.Tensor, ids: np.ndarray, sample_queries: np.ndarray) -> tuple[dict, list[dict]]:
    n = len(z)
    u = model.norm(z - z.mean(0, keepdim=True)); q, k, v = model.q(u), model.k(u), model.v(u)
    entropies, top1, top5, top10, contexts, chosen = [], [], [], [], [], []
    distributions = []
    samples = []
    with torch.no_grad():
        for start in range(0, n, model.query_chunk):
            qp = q[start:start + model.query_chunk]
            logits = qp @ k.T / math.sqrt(model.d_attn)
            local = torch.arange(len(qp), device=z.device); logits[local, start + local] = -torch.inf
            a = logits.softmax(-1); c = a @ v
            entropy = -(a * a.clamp_min(1e-30).log()).sum(-1)
            values, index = a.topk(min(20, n - 1), dim=-1)
            entropies.extend(entropy.cpu().numpy()); top1.extend(values[:, :1].sum(-1).cpu().numpy())
            top5.extend(values[:, :min(5, values.shape[1])].sum(-1).cpu().numpy())
            top10.extend(values[:, :min(10, values.shape[1])].sum(-1).cpu().numpy()); contexts.append(c.cpu().numpy())
            for query in sample_queries:
                if start <= query < start + len(qp):
                    r = query - start
                    for rank, (jpos, mass) in enumerate(zip(index[r].cpu().numpy(), values[r].cpu().numpy()), 1):
                        samples.append({"query_j": int(ids[query]), "attended_j": int(ids[jpos]), "rank": rank, "mass": float(mass)})
            if len(distributions) < 32:
                take = min(32 - len(distributions), len(a)); distributions.extend(a[:take].cpu().numpy())
    dist = np.asarray(distributions)
    cosine = dist @ dist.T / np.maximum(np.linalg.norm(dist, axis=1)[:, None] * np.linalg.norm(dist, axis=1), 1e-30)
    tri = cosine[np.triu_indices(len(dist), 1)] if len(dist) > 1 else np.array([1.0])
    context = np.concatenate(contexts)
    delta = model.o(torch.as_tensor(context, device=z.device)).cpu().detach().numpy()
    return {
        "stocks": n, "attention_entropy": float(np.mean(entropies)),
        "effective_refs": float(np.exp(np.mean(entropies))), "top1_mass": float(np.mean(top1)),
        "top5_mass": float(np.mean(top5)), "top10_mass": float(np.mean(top10)),
        "query_cosine_mean": float(tri.mean()), "query_cosine_median": float(np.median(tri)),
        "context_cross_section_variance": float(np.var(context, axis=0).mean()),
        "delta_cross_section_variance": float(np.var(delta, axis=0).mean()),
        "delta_to_h_norm": float(np.linalg.norm(delta) / max(np.linalg.norm(z.cpu().numpy()), 1e-30)),
    }, samples


def infer_formal(year: int, seed: int, arm: str, choice: dict, checkpoint_path: Path, uniform: bool = False) -> Path:
    suffix = "_UNIFORM" if uniform else ""
    out = PRED / str(year) / f"{arm}_s{seed}{suffix}.parquet"
    if out.exists(): return out
    build_forward_cache(year)
    keys_path, raw_path, legs_path, offset_path = cache_paths(year)
    keys = pd.read_parquet(keys_path); raw = np.load(raw_path, mmap_mode="r")
    legs = np.load(legs_path, mmap_mode="r"); offsets = np.load(offset_path, mmap_mode="r")
    relation = arm == "RELATION"
    model, _ = core.load_model_checkpoint(checkpoint_path, relation)
    data = FormalData(year)
    branch_folder = core.trajectory_dir("FORMAL", year, seed, relation, float(choice["lr"])) / f"eval_step{int(choice['steps'])}"
    branch = core.fit_centered_branch(model, data, branch_folder)
    score = np.empty(len(keys), np.float32); embedding = np.empty((len(keys), 32), np.float32)
    diag, samples = [], []
    diagnostic_dates = set(np.linspace(0, keys.t.nunique() - 1, 20, dtype=int))
    model.eval()
    with torch.no_grad():
        for date_no, (t, group) in enumerate(keys.groupby("t", sort=True)):
            ix = group.index.to_numpy(); n = len(ix)
            xnp = np.concatenate([raw[ix], np.broadcast_to(offsets[ix, None, None, :], (n, 4, 32, 3))], -1)
            x = torch.as_tensor(xnp, device="mps"); l = torch.as_tensor(np.asarray(legs[ix]), device="mps")
            if uniform:
                p, z, _ = uniform_forward(model, x, l)
            else:
                p, z, _ = model(x, l)
            score[ix] = p[:, 1].cpu().numpy() / 10; embedding[ix] = z.cpu().numpy()
            if relation and not uniform:
                qs = np.linspace(0, n - 1, min(10, n), dtype=int) if date_no in diagnostic_dates else np.array([], int)
                row, smp = attention_statistics(model, z, group.j.to_numpy(int), qs)
                row.update(year=year, seed=seed, t=int(t), decision_date=group.decision_date.iloc[0]); diag.append(row)
                for xrow in smp: xrow.update(year=year, seed=seed, t=int(t), decision_date=group.decision_date.iloc[0])
                samples.extend(smp)
    correction = core.centered((branch["scaler"].transform(core.centered(embedding, keys.t)) @ branch["theta"])[:, None], keys.t).ravel()
    score = score + correction / 10
    out.parent.mkdir(parents=True, exist_ok=True); keys.assign(score=score).to_parquet(out, index=False)
    if diag:
        old = pd.read_parquet(HERE / "ATTENTION_DIAGNOSTICS.parquet") if (HERE / "ATTENTION_DIAGNOSTICS.parquet").exists() else pd.DataFrame()
        pd.concat([old, pd.DataFrame(diag)], ignore_index=True).drop_duplicates(["year", "seed", "t"], keep="last").to_parquet(HERE / "ATTENTION_DIAGNOSTICS.parquet", index=False)
    if samples:
        old = pd.read_parquet(HERE / "ATTENTION_SAMPLES.parquet") if (HERE / "ATTENTION_SAMPLES.parquet").exists() else pd.DataFrame()
        pd.concat([old, pd.DataFrame(samples)], ignore_index=True).drop_duplicates(["year", "seed", "t", "query_j", "rank"], keep="last").to_parquet(HERE / "ATTENTION_SAMPLES.parquet", index=False)
    core.dump(out.with_suffix(".json"), {"sha256": core.sha(out), "rows": len(keys), "dates": int(keys.t.nunique()),
              "checkpoint_sha256": core.sha(checkpoint_path), "uniform_substitution": uniform})
    del model, data; gc.collect(); torch.mps.empty_cache()
    return out


def evaluate_score(year: int, seed: str, arm: str, path: Path) -> tuple[dict, pd.DataFrame]:
    frame = pd.read_parquet(path)
    if year in (2020, 2021):
        ev = core.load_module("allstock_evaluator", core.ROOT / "full_date_cross_stock_reconciliation_v1/evaluator.py")
        source = core.FULL / str(year)
        frame["ret10"] = np.load(source / "ret10.npy"); frame["ret20"] = np.load(source / "ret20.npy")
        daily = ev.evaluate_daily(frame); agg = ev.aggregate_daily(daily)
        if seed == "FIXED3":
            i0 = np.mean([percentile_by_date(frame, np.load(source / f"I0_s{s}.npy")) for s in core.SEEDS], axis=0)
        else:
            i0 = np.load(source / f"I0_s{seed}.npy")
    else:
        assert year == 2022
        source = source_frame(year).sort_values(["t", "j"], kind="stable").reset_index(drop=True)
        assert np.array_equal(frame[["t", "j"]].to_numpy(), source[["t", "j"]].to_numpy())
        frame["ret20"] = source.ret20.to_numpy(float)
        daily = core.signal_daily(frame)
        agg = {"rankic20": float(daily.RankIC20.mean()), "top10_ret20": float(daily.top10_ret20.mean()),
               "top10_lift20": float(daily.top10_lift20.mean()), "top50_ret20": float(daily.top50_ret20.mean()),
               "top50_lift20": float(daily.top50_lift20.mean())}
        if seed == "FIXED3":
            i0 = np.mean([percentile_by_date(frame, source[f"BRANCH_s{s}"].to_numpy(float)) for s in core.SEEDS], axis=0)
        else:
            i0 = source[f"BRANCH_s{seed}"].to_numpy(float)
    top = daily.top10_ret20.dropna()
    overlap, correlations = [], []
    for _, ix in frame.groupby("t", sort=False).indices.items():
        a, b = frame.score.to_numpy()[ix], i0[ix]
        overlap.append(len(set(np.asarray(ix)[np.argsort(a)[-10:]]) & set(np.asarray(ix)[np.argsort(b)[-10:]])) / 10)
        correlations.append(pd.Series(a).corr(pd.Series(b), method="spearman"))
    result = {"year": year, "seed": seed, "arm": arm, "dates": len(top),
              "RankIC20": agg["rankic20"], "top10_ret20": agg["top10_ret20"], "top10_lift20": agg["top10_lift20"],
              "top50_ret20": agg["top50_ret20"], "top50_lift20": agg["top50_lift20"],
              "positive_date_fraction": float((top > 0).mean()), "leave_best1": float(top.drop(top.nlargest(1).index).mean()),
              "leave_best3": float(top.drop(top.nlargest(3).index).mean()),
              "bottom_decile_ret20": float(top.nsmallest(max(1, int(math.ceil(len(top) * .1)))).mean()),
              "score_correlation_to_incumbent": float(np.mean(correlations)), "top10_overlap_to_incumbent": float(np.mean(overlap))}
    return result, daily


def seed17_gate(rows: pd.DataFrame) -> dict:
    verdicts = {}
    for arm in rows.arm.unique():
        if arm == "I0": continue
        c = rows[rows.arm == arm].set_index("year"); b = rows[rows.arm == "I0"].set_index("year")
        top = c.top10_ret20 - b.top10_ret20; leave = c.leave_best3 - b.leave_best3
        passed = bool(top.mean() > 0 and leave.mean() >= 0 and not (top < 0).all())
        verdicts[arm] = {"top10_delta_by_year": clean_series(top), "mean_top10_delta": float(top.mean()),
                         "mean_leave_best3_delta": float(leave.mean()), "passes_futility_gate": passed}
    return {"rule": "pooled Top10 delta>0, pooled leave-best3 delta>=0, and not negative in both years", "arms": verdicts,
            "any_pass": any(x["passes_futility_gate"] for x in verdicts.values())}


def clean_series(value: pd.Series) -> dict:
    return {str(k): float(v) for k, v in value.items()}


def fixed3(year: int, arm: str) -> Path:
    keys = source_frame(year).sort_values(["t", "j"], kind="stable").reset_index(drop=True)
    if arm == "I0":
        if year in (2020, 2021):
            scores = [np.load(core.FULL / str(year) / f"I0_s{s}.npy") for s in core.SEEDS]
        else:
            scores = [keys[f"BRANCH_s{s}"].to_numpy(float) for s in core.SEEDS]
    else:
        scores = [pd.read_parquet(PRED / str(year) / f"{arm}_s{s}.parquet").score.to_numpy(float) for s in core.SEEDS]
    value = np.mean([percentile_by_date(keys, x) for x in scores], axis=0)
    out = PRED / str(year) / f"{arm}_FIXED3.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    keys[["t", "j", "decision_date"]].assign(score=value).to_parquet(out, index=False)
    return out


def account_daily_returns(row: pd.Series) -> pd.DataFrame:
    path = Path(row.ledger_dir) / f"{row.policy}_funded_prefix_nav.parquet"
    f = pd.read_parquet(path); f["date"] = pd.to_datetime(f.date); f["ret"] = f.nav.astype(float).pct_change().fillna(0)
    return f[["date", "ret"]]


def accounts(arms: list[str]) -> tuple[pd.DataFrame, dict]:
    profit = core.load_module("allstock_profit", core.ROOT / "master_alpha158_profit_first_v2/profit_pipeline.py")
    br = profit.broader(); profit.ACCOUNTS = core.EXT / "accounts"
    rows = []
    for year in (2020, 2021):
        for arm in ["I0"] + arms:
            path = None if arm == "I0" else PRED / str(year) / f"{arm}_FIXED3.parquet"
            metric = profit.run_account(year, "I0" if arm == "I0" else f"ALLSTOCK_{arm}", path, br)
            metric["candidate"] = arm; metric["Calmar"] = metric["annual_return"] / metric["MaxDD"] if metric["MaxDD"] else None
            nav = pd.read_parquet(Path(metric["ledger_dir"]) / f"{metric['policy']}_funded_prefix_nav.parquet")
            orders = pd.read_parquet(Path(metric["ledger_dir"]) / f"{metric['policy']}_funded_prefix_orders.parquet")
            buys = orders[(orders.side == "BUY") & (orders.status == "FILLED")]
            metric["zero_new_position_days"] = int(nav.t.nunique() - buys.decision_t.nunique())
            rows.append(metric)
    table = pd.DataFrame(rows); table.to_parquet(HERE / "ACCOUNT_RESULTS.parquet", index=False)
    base = table[table.candidate == "I0"].set_index("year"); gate = {}
    for arm in arms:
        cand = table[table.candidate == arm].set_index("year")
        deltas = cand.annual_return - base.annual_return; dd = cand.MaxDD - base.MaxDD
        paired = []
        for year in (2020, 2021):
            c = account_daily_returns(cand.loc[year]).rename(columns={"ret": "candidate"})
            b = account_daily_returns(base.loc[year]).rename(columns={"ret": "i0"})
            paired.append(c.merge(b, on="date", validate="one_to_one"))
        active = pd.concat(paired).eval("candidate-i0")
        leave3 = float(active.drop(active.nlargest(3).index).sum())
        gate[arm] = {"mean_return_delta": float(deltas.mean()), "worst_year_return_delta": float(deltas.min()),
                     "max_MaxDD_delta": float(dd.max()), "leave_best3_active_daily_sum": leave3,
                     "qualifies": bool(deltas.mean() > 0 and deltas.min() >= -.03 and dd.max() <= .02 and leave3 >= 0)}
    return table, gate


def confirm_2022(earned: list[str], choices: dict, manifests: dict) -> dict:
    core.dump(HERE / "2022_AUTHORIZED.json", {"earned_on_2020_2021": earned, "opened_once": True,
              "frozen_choices": choices, "at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat()})
    year = 2022; rows = []
    source = source_frame(year).sort_values(["t", "j"], kind="stable").reset_index(drop=True)
    for seed in core.SEEDS:
        p = PRED / str(year) / f"I0_s{seed}.parquet"; p.parent.mkdir(parents=True, exist_ok=True)
        source[["t", "j", "decision_date"]].assign(score=source[f"BRANCH_s{seed}"].to_numpy(float)).to_parquet(p, index=False)
        for arm in earned:
            ck = formal_train(year, seed, arm, choices[arm], manifests)
            infer_formal(year, seed, arm, choices[arm], ck)
    for arm in ["I0"] + earned:
        path = fixed3(year, arm); result, _ = evaluate_score(year, "FIXED3", arm, path); rows.append(result)
    profit = core.load_module("allstock_profit_2022", core.ROOT / "master_alpha158_profit_first_v2/profit_pipeline.py")
    br = profit.broader(); profit.ACCOUNTS = core.EXT / "accounts"
    base = profit.run_account(year, "I0", None, br)
    result = {"I0": base, "signals": rows, "candidates": {}}
    for arm in earned:
        cand = profit.run_account(year, f"ALLSTOCK_{arm}", PRED / str(year) / f"{arm}_FIXED3.parquet", br)
        rd = float(cand["annual_return"] - base["annual_return"]); dd = float(cand["MaxDD"] - base["MaxDD"])
        result["candidates"][arm] = {"account": cand, "return_delta": rd, "MaxDD_delta": dd,
                                        "confirmed": bool(rd >= 0 and dd <= .02)}
    core.dump(HERE / "2022_CONFIRMATION.json", result)
    return result


def finalize(signals: pd.DataFrame, accounts_table: pd.DataFrame | None, gate: dict, selection: dict,
             seed_gate: dict, confirmation: dict | None = None) -> None:
    earned = [a for a, x in gate.items() if x["qualifies"]]
    confirmed = [] if confirmation is None else [a for a, x in confirmation.get("candidates", {}).items() if x["confirmed"]]
    if "RELATION" in confirmed:
        status = "ATTENTION_PROFIT_INCREMENT_CONFIRMED"
    elif "RELATION" in earned:
        status = "ATTENTION_DEVELOPMENT_CANDIDATE_ONLY"
    elif "CONTROL" in confirmed:
        status = "SMALL_LR_ONLY_INCREMENT"
    elif accounts_table is not None:
        status = "NO_PROFIT_INCREMENT"
    else:
        status = "NO_PROFIT_INCREMENT"
    attention = pd.read_parquet(HERE / "ATTENTION_DIAGNOSTICS.parquet") if (HERE / "ATTENTION_DIAGNOSTICS.parquet").exists() else pd.DataFrame()
    packet = {"TASK_COMPLETION": "COMPLETE", "FINAL_STATUS": status,
              "ACTUAL_REPO": str(core.REPO), "GIT_BRANCH": core.frozen_spec()["git_branch"], "HEAD": core.frozen_spec()["head"],
              "INNER_SELECTION": selection, "SEED17_GATE": seed_gate, "ACCOUNT_GATE": gate,
              "2022_CONFIRMATION": confirmation,
              "SIGNAL_RESULTS": signals.to_dict("records"),
              "ACCOUNT_RESULTS": accounts_table.to_dict("records") if accounts_table is not None else [],
              "ATTENTION_EFFECTIVE_REFS": float(attention.effective_refs.mean()) if len(attention) else None,
              "ATTENTION_QUERY_COSINE": float(attention.query_cosine_mean.mean()) if len(attention) else None,
              "ATTENTION_TOP10_MASS": float(attention.top10_mass.mean()) if len(attention) else None,
              "FIXED3_EARNED": bool(seed_gate.get("any_pass")), "ACCOUNT_GATE_EARNED": bool(earned),
              "2022_OPENED": (HERE / "TEMPORAL_BOUNDARY_EVENT.json").exists() or confirmation is not None,
              "2022_SMALL_LR_RESULT": None if confirmation is None else confirmation.get("candidates", {}).get("CONTROL"),
              "2022_ATTENTION_RESULT": None if confirmation is None else confirmation.get("candidates", {}).get("RELATION"),
              "2023_OPENED": False, "SEALED_2024_2026_OPENED": False, "PRODUCTION_APPROVED": False,
              "MEASURED_MPS_HOURS_TOTAL": measured_hours(),
              "REPORT": str(HERE / "FINAL_REPORT.md"), "DECISION_PACKET": str(HERE / "DECISION_PACKET.json")}
    core.dump(HERE / "DECISION_PACKET.json", packet)
    (HERE / "FINAL_REPORT.md").write_text("# I0 all-stock attention and small-LR V1\n\n```json\n" + json.dumps(core.clean(packet), ensure_ascii=False, indent=2) + "\n```\n")
    core.update_state("COMPLETE", "FINAL", final_status=status)


def measured_hours() -> float:
    total = 0.0
    for p in (core.EXT / "training").glob("**/COMPLETE_*.json"):
        total += float(json.loads(p.read_text()).get("active_seconds", 0))
    return total / 3600


def run() -> None:
    selection = selected(); manifests = checkpoint_manifest()
    arms = ["CONTROL"] + (["RELATION"] if selection["relation"] is not None else [])
    choices = {"CONTROL": selection["small_lr_control"], "RELATION": selection.get("relation")}
    rows, daily_paths = [], {}
    # Seed17 frozen development first.
    for year in (2020, 2021):
        keys = pd.read_parquet(core.FULL / str(year) / "KEYS.parquet")
        i0 = np.load(core.FULL / str(year) / "I0_s17.npy")
        p = PRED / str(year) / "I0_s17.parquet"; p.parent.mkdir(parents=True, exist_ok=True); keys.assign(score=i0).to_parquet(p, index=False)
        result, daily = evaluate_score(year, "17", "I0", p); rows.append(result); daily_paths[(year, "I0", 17)] = daily
        for arm in arms:
            ck = formal_train(year, 17, arm, choices[arm], manifests)
            path = infer_formal(year, 17, arm, choices[arm], ck)
            result, daily = evaluate_score(year, "17", arm, path); rows.append(result); daily_paths[(year, arm, 17)] = daily
            if arm == "RELATION":
                upath = infer_formal(year, 17, arm, choices[arm], ck, uniform=True)
                result, daily = evaluate_score(year, "17", "RELATION_UNIFORM", upath); rows.append(result)
    seed17 = pd.DataFrame(rows); seed_gate = seed17_gate(seed17)
    core.dump(HERE / "SEED17_ADVANCEMENT.json", seed_gate)
    if not seed_gate["any_pass"]:
        seed17.to_parquet(HERE / "SIGNAL_METRICS.parquet", index=False)
        finalize(seed17, None, {}, selection, seed_gate); return
    passing = [arm for arm in arms if seed_gate["arms"][arm]["passes_futility_gate"]]
    # Multi-seed only for independently passing frozen arms.
    for year in (2020, 2021):
        keys = pd.read_parquet(core.FULL / str(year) / "KEYS.parquet")
        for seed in (29, 43):
            i0 = np.load(core.FULL / str(year) / f"I0_s{seed}.npy")
            p = PRED / str(year) / f"I0_s{seed}.parquet"; keys.assign(score=i0).to_parquet(p, index=False)
            result, _ = evaluate_score(year, str(seed), "I0", p); rows.append(result)
            for arm in passing:
                ck = formal_train(year, seed, arm, choices[arm], manifests)
                path = infer_formal(year, seed, arm, choices[arm], ck)
                result, _ = evaluate_score(year, str(seed), arm, path); rows.append(result)
        for arm in ["I0"] + passing:
            path = fixed3(year, arm); result, _ = evaluate_score(year, "FIXED3", arm, path); rows.append(result)
    signals = pd.DataFrame(rows); signals.to_parquet(HERE / "SIGNAL_METRICS.parquet", index=False)
    account_table, gate = accounts(passing)
    earned = [arm for arm, result in gate.items() if result["qualifies"]]
    # A schema smoke test loaded the consumed 2022 table before the gate.  No outcome statistic was viewed,
    # but the strict contract treats any read as an opening; therefore no 2022 candidate computation is allowed.
    confirmation = ({"status": "INVALID_PREMATURE_SCHEMA_READ", "candidates": {},
                     "promotion_use": "FORBIDDEN", "event": json.loads((HERE / "TEMPORAL_BOUNDARY_EVENT.json").read_text())}
                    if earned and (HERE / "TEMPORAL_BOUNDARY_EVENT.json").exists() else
                    (confirm_2022(earned, choices, manifests) if earned else None))
    finalize(signals, account_table, gate, selection, seed_gate, confirmation)


if __name__ == "__main__":
    try:
        run()
    except Exception:
        core.dump(HERE / "ERROR_PACKET.json", {"status": "BLOCKED_NEEDS_CODEX", "stage": "FORMAL_PIPELINE",
                  "traceback": traceback.format_exc(), "safest_next_action": "repair deterministic implementation blocker and resume formal.py"})
        core.update_state("BLOCKED_NEEDS_CODEX", "FORMAL_PIPELINE")
        raise
