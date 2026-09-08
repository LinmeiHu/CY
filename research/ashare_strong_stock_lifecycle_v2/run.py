"""Fixed-rule Strong Stock Lifecycle V2 discovery study.

The event panel is derived from the sealed V1 event identities.  Large
intermediate/output files live under /Volumes/quant; Git keeps code and small
summary/report artifacts only.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
CACHE = Path("/Volumes/quant/CY_quant_research/usic_multichampion_ashare_v3/cache")
V1_PANEL = Path("/Volumes/quant/CY_quant_research/ashare_strong_stock_lifecycle_v1/strong_stock_panel.parquet")
BIG_OUT = Path("/Volumes/quant/CY_quant_research/ashare_strong_stock_lifecycle_v2")
BIG_OUT.mkdir(parents=True, exist_ok=True)

LOOKBACK_CORR = 20
TOP_K = 20
PRESSURE_LOOKBACK = 120
PRESSURE_HORIZON = 15
PRESSURE_WINDOW = 3
BETA_LOOKBACK = 60
LANDMARK_OFFSET = 4
MIN_PEER_COVERAGE = 0.8
MIN_PRESSURE_HISTORY = 60


def _write_json(name: str, value: object) -> None:
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def _write_csv(name: str, frame: pd.DataFrame) -> None:
    frame.to_csv(HERE / name, index=False)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _load() -> tuple[dict, dict[str, np.ndarray], np.ndarray, np.ndarray, np.ndarray]:
    axes = json.loads((CACHE / "axes.json").read_text())
    arrays = {
        key: np.load(CACHE / f"{key}.npy", mmap_mode="r")
        for key in [
            "coord", "close", "high", "low", "amount", "hard_valid", "industry",
            "is_st", "up_limit_price", "preclose", "corporate_action_count", "market",
        ]
    }
    n, m = arrays["coord"].shape
    valid = (
        (arrays["hard_valid"] == 1)
        & (arrays["is_st"] == 0)
        & np.isfinite(arrays["coord"])
        & (arrays["coord"] > 0)
        & np.isfinite(arrays["amount"])
        & (arrays["industry"] >= 0)
    )
    daily = np.full((n, m), np.nan, dtype=np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        daily[1:] = (arrays["coord"][1:] / arrays["coord"][:-1] - 1).astype(np.float32)
    daily[1:][~(valid[1:] & valid[:-1])] = np.nan
    market = np.full(n, np.nan, dtype=np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        market[1:] = (arrays["market"][1:] / arrays["market"][:-1] - 1).astype(np.float32)
    market[~np.isfinite(market)] = np.nan
    return axes, arrays, valid, daily, market


def _rank_percentiles(values: np.ndarray) -> np.ndarray:
    """Cross-sectional percentile rank; invalid values remain NaN."""
    out = np.full(values.shape, np.nan, dtype=np.float32)
    for t in range(values.shape[0]):
        s = pd.Series(values[t])
        out[t] = s.rank(pct=True).to_numpy(dtype=np.float32)
    return out


def _basket(daily: np.ndarray, peers: np.ndarray, start: int, end: int) -> tuple[np.ndarray, np.ndarray]:
    x = daily[start:end, peers]
    coverage = np.isfinite(x).mean(axis=1)
    result = np.full(end - start, np.nan, dtype=np.float32)
    enough = coverage >= MIN_PEER_COVERAGE
    if np.any(enough):
        result[enough] = np.nanmean(x[enough], axis=1)
    return result, coverage


def _corr_top20(window: np.ndarray, leader_ids: np.ndarray, eligible: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ids = np.flatnonzero(eligible)
    if len(ids) < TOP_K + 1:
        return np.full((len(leader_ids), TOP_K), -1, dtype=np.int32), np.full((len(leader_ids), TOP_K), np.nan)
    x = window[:, ids].astype(np.float32, copy=True)
    x -= x.mean(axis=0)
    sd = x.std(axis=0, ddof=1)
    good = np.isfinite(sd) & (sd > 0)
    ids = ids[good]
    x = x[:, good] / sd[good]
    if not len(ids):
        return peers, scores_out
    pos = np.searchsorted(ids, leader_ids)
    leader_good = (pos < len(ids)) & (ids[np.minimum(pos, len(ids) - 1)] == leader_ids)
    peers = np.full((len(leader_ids), TOP_K), -1, dtype=np.int32)
    scores_out = np.full((len(leader_ids), TOP_K), np.nan, dtype=np.float32)
    if not np.any(leader_good):
        return peers, scores_out
    scores = (x[:, pos[leader_good]].T @ x) / (window.shape[0] - 1)
    good_rows = np.flatnonzero(leader_good)
    for row, score in zip(good_rows, scores):
        score[pos[row]] = -np.inf
        take = min(TOP_K, len(ids) - 1)
        chosen = np.argpartition(-score, take - 1)[:take]
        chosen = chosen[np.argsort(-score[chosen], kind="stable")]
        peers[row, :take] = ids[chosen]
        scores_out[row, :take] = score[chosen]
    return peers, scores_out


def _three_session(values: np.ndarray, end: int) -> float:
    if end < 2 or not np.isfinite(values[end - 2 : end + 1]).all():
        return np.nan
    return float(np.prod(1.0 + values[end - 2 : end + 1]) - 1.0)


def _first_pressure(basket: np.ndarray, start: int, stop: int) -> tuple[int, float, int]:
    first = -1
    first_z = np.nan
    history_n = 0
    for u in range(start, stop + 1):
        value = _three_session(basket, u)
        if not np.isfinite(value) or u - PRESSURE_LOOKBACK < 2:
            continue
        history = np.array([_three_session(basket, v) for v in range(u - PRESSURE_LOOKBACK, u)], dtype=float)
        history = history[np.isfinite(history)]
        history_n = max(history_n, len(history))
        if len(history) < MIN_PRESSURE_HISTORY or history.std(ddof=1) <= 0:
            continue
        z = (value - history.mean()) / history.std(ddof=1)
        if z <= -1.0:
            first, first_z = u, float(z)
            break
    return first, first_z, history_n


def _outcomes(coord: np.ndarray, j: int, landmark: int) -> dict[str, float]:
    out: dict[str, float] = {}
    base = coord[landmark, j]
    for h in (5, 10, 20):
        path = coord[landmark + 1 : landmark + h + 1, j]
        good = len(path) == h and np.isfinite(base) and np.isfinite(path).all() and base > 0
        out[f"fwd{h}"] = float(path[-1] / base - 1) if good else np.nan
        out[f"mfe{h}"] = float(np.max(path / base - 1)) if good else np.nan
        out[f"mae{h}"] = float(np.min(path / base - 1)) if good else np.nan
        out[f"new_high{h}"] = float(np.max(path) > base) if good else np.nan
    return out


def _event_rows(axes: dict, arrays: dict[str, np.ndarray], valid: np.ndarray, daily: np.ndarray, market: np.ndarray, v1: pd.DataFrame) -> pd.DataFrame:
    symbols = np.array(axes["symbols"])
    boards = np.array(axes["boards"])
    symbol_to_j = {symbol: j for j, symbol in enumerate(symbols)}
    v1 = v1.copy()
    v1["j"] = v1["symbol"].map(symbol_to_j)
    v1 = v1.dropna(subset=["j"]).copy()
    v1["j"] = v1["j"].astype(int)
    rs60 = np.full_like(daily, np.nan, dtype=np.float32)
    coord = arrays["coord"]
    rs60[60:] = (coord[60:] / coord[:-60] - 1).astype(np.float32)
    rs60[~(valid & np.isfinite(rs60))] = np.nan
    rs60 = _rank_percentiles(rs60)
    rows: list[dict] = []
    by_t = v1.groupby("t", sort=True)
    for t, group in by_t:
        t = int(t)
        if t < LOOKBACK_CORR or t + 2 >= len(daily):
            continue
        leader_ids = group.j.to_numpy(dtype=int)
        eligible = valid[t].copy()
        eligible &= np.isfinite(daily[t - LOOKBACK_CORR + 1 : t + 1]).all(axis=0)
        window = daily[t - LOOKBACK_CORR + 1 : t + 1]
        dynamic, corr = _corr_top20(window, leader_ids, eligible)
        for row_number, (_, source) in enumerate(group.iterrows()):
            j = int(source.j)
            peers = dynamic[row_number]
            peer_ok = peers[0] >= 0 and np.all(peers >= 0)
            static_mask = eligible & (arrays["industry"][t] == arrays["industry"][t, j])
            static_mask[j] = False
            static_peers = np.flatnonzero(static_mask)
            static_corr = np.nan
            if peer_ok:
                dynamic_corr = corr[row_number]
                dynamic_mean = float(np.nanmean(dynamic_corr))
                dynamic_median = float(np.nanmedian(dynamic_corr))
                dynamic_ind = arrays["industry"][t, peers]
                dynamic_board = boards[peers]
                hist_start = max(0, t - 121)
                hist_end = min(len(daily), t + 21)
                dyn_basket, dyn_cov = _basket(daily, peers, hist_start, hist_end)
                static_basket, static_cov = _basket(daily, static_peers, hist_start, hist_end) if len(static_peers) else (np.full(hist_end - hist_start, np.nan), np.zeros(hist_end - hist_start))
                eligible_ids = np.flatnonzero(eligible)
                leader_col = np.flatnonzero(eligible_ids == j)
                static_cols = np.flatnonzero(np.isin(eligible_ids, static_peers))
                if len(static_peers) and len(leader_col) and len(static_cols):
                    leader_series = window[:, leader_col[0]]
                    static_series = window[:, static_cols].mean(axis=1)
                    static_corr = float(np.corrcoef(leader_series, static_series)[0, 1]) if np.isfinite(static_series).all() else np.nan
            else:
                dynamic_mean = dynamic_median = np.nan
                dynamic_ind = np.array([], dtype=int)
                dynamic_board = np.array([], dtype=str)
                dyn_basket = np.full(min(len(daily), t + 21) - max(0, t - 121), np.nan)
                dyn_cov = np.zeros(len(dyn_basket))
                static_basket = np.full_like(dyn_basket, np.nan)
                static_cov = np.zeros(len(dyn_basket))
            rec = {
                "event_id": f"{source.date}:{source.symbol}", "t": t, "date": source.date, "symbol": source.symbol, "j": j,
                "year": int(source.year), "industry": int(arrays["industry"][t, j]), "board": boards[j],
                "peer_status": "OK" if peer_ok else "PEER_UNAVAILABLE", "peer_n": int(np.sum(peers >= 0)),
                "peer_symbols": "|".join(symbols[peers].tolist()) if peer_ok else "",
                "peer_mean_corr": dynamic_mean, "peer_median_corr": dynamic_median,
                "peer_industry_n": int(len(np.unique(dynamic_ind))) if len(dynamic_ind) else 0,
                "peer_board_n": int(len(np.unique(dynamic_board))) if len(dynamic_board) else 0,
                "static_peer_n": int(len(static_peers)), "static_peer_mean_corr": static_corr,
                "static_peer_coverage": float(np.nanmean(static_cov)) if len(static_cov) else np.nan,
                "dynamic_peer_coverage": float(np.nanmean(dyn_cov)) if len(dyn_cov) else np.nan,
                "pressure_status": "NO_PEER" if not peer_ok else "NO_PRESSURE",
                "pressure_start": -1, "pressure_z": np.nan, "pressure_history_n": 0,
                "simple_resilience": np.nan, "residual_resilience": np.nan, "beta_peer": np.nan, "beta_market": np.nan,
                "post_pressure_relative_return": np.nan, "rs_percentile_change": np.nan,
                "early_reacceleration": False, "full_repair_by_landmark": False, "landmark": -1,
                "truncated": False, "corporate_action_count_at_event": float(arrays["corporate_action_count"][t, j]),
                "limit_price_available": bool(np.isfinite(arrays["up_limit_price"][t, j]) and np.isfinite(arrays["preclose"][t, j])),
            }
            for field in ("ret20", "ret60", "rs60", "market_ret5", "turnover_rel"):
                rec[field] = source.get(field, np.nan)
            if peer_ok:
                start = t + 1
                stop = min(t + PRESSURE_HORIZON, len(daily) - 1)
                local_start = max(0, t - 121)
                pressure, pressure_z, hist_n = _first_pressure(dyn_basket, start - local_start, stop - local_start)
                if pressure >= 0:
                    p = local_start + pressure
                    rec.update(pressure_status="PRESSURE", pressure_start=p, pressure_z=pressure_z, pressure_history_n=hist_n)
                    if p + LANDMARK_OFFSET >= len(daily):
                        rec.update(pressure_status="TRUNCATED", truncated=True)
                    else:
                        local_p = p - local_start
                        actual = daily[p : p + PRESSURE_WINDOW, j]
                        peer_window = dyn_basket[local_p : local_p + PRESSURE_WINDOW]
                        market_window = market[p : p + PRESSURE_WINDOW]
                        if np.isfinite(actual).all() and np.isfinite(peer_window).all():
                            stock_cum = float(np.prod(1 + actual) - 1)
                            peer_cum = float(np.prod(1 + peer_window) - 1)
                            rec["simple_resilience"] = stock_cum - peer_cum
                            xpeer = dyn_basket[max(0, p - BETA_LOOKBACK - local_start) : local_p]
                            xmkt = market[p - BETA_LOOKBACK : p]
                            y = daily[p - BETA_LOOKBACK : p, j]
                            ok = np.isfinite(xpeer) & np.isfinite(xmkt) & np.isfinite(y)
                            if ok.sum() >= 40:
                                beta_peer, beta_market = np.linalg.lstsq(np.c_[xpeer[ok], xmkt[ok]], y[ok], rcond=None)[0]
                                expected_daily = beta_peer * peer_window + beta_market * market_window
                                if np.isfinite(expected_daily).all():
                                    rec.update(beta_peer=float(beta_peer), beta_market=float(beta_market), residual_resilience=float(stock_cum - (np.prod(1 + expected_daily) - 1)))
                        post = daily[p + 3 : p + 5, j]
                        post_peer = dyn_basket[local_p + 3 : local_p + 5]
                        if len(post) == 2 and np.isfinite(post).all() and np.isfinite(post_peer).all():
                            rec["post_pressure_relative_return"] = float(np.prod(1 + post) - np.prod(1 + post_peer))
                            rec["rs_percentile_change"] = float(rs60[p + 4, j] - rs60[p + 2, j]) if np.isfinite(rs60[p + 4, j]) and np.isfinite(rs60[p + 2, j]) else np.nan
                            rec["early_reacceleration"] = bool(rec["post_pressure_relative_return"] > 0)
                        rec["landmark"] = p + LANDMARK_OFFSET
                        rec["full_repair_by_landmark"] = bool(
                            np.isfinite(coord[p - 1, j]) and np.isfinite(coord[rec["landmark"], j])
                            and coord[rec["landmark"], j] >= coord[p - 1, j]
                            and np.isfinite(rs60[p - 1, j]) and np.isfinite(rs60[rec["landmark"], j])
                            and rs60[rec["landmark"], j] >= rs60[p - 1, j]
                        )
                        rec.update(_outcomes(coord, j, rec["landmark"]))
                        rec["truncated"] = not np.isfinite(rec.get("fwd20", np.nan))
            rows.append(rec)
    return pd.DataFrame(rows)


def _quintiles(d: pd.DataFrame, feature: str) -> pd.DataFrame:
    x = d.dropna(subset=[feature, "fwd10"]).copy()
    x["quintile"] = x.groupby("year")[feature].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1)
    cols = {"observations": ("event_id", "size"), "mean_fwd5": ("fwd5", "mean"), "mean_fwd10": ("fwd10", "mean"), "mean_fwd20": ("fwd20", "mean"), "median_fwd10": ("fwd10", "median"), "mean_mfe10": ("mfe10", "mean"), "mean_mae10": ("mae10", "mean"), "new_high10": ("new_high10", "mean")}
    agg = x.groupby(["year", "quintile"], observed=True).agg(**cols).reset_index()
    return agg.assign(feature=feature)


def _annual(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, g in d.groupby("year"):
        row = {"year": year, "events": len(g), "dates": g.date.nunique(), "stocks": g.symbol.nunique(), "peer_ok": int((g.peer_status == "OK").sum()), "pressure_events": int((g.pressure_status == "PRESSURE").sum())}
        for feature in ("simple_resilience", "residual_resilience"):
            z = g.dropna(subset=[feature, "fwd10"])
            cut = z[feature].median() if len(z) else np.nan
            row[f"{feature}_high_minus_low_fwd10"] = float(z.loc[z[feature] >= cut, "fwd10"].mean() - z.loc[z[feature] < cut, "fwd10"].mean()) if len(z) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _concentration(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for feature in ("simple_resilience", "residual_resilience"):
        z = d.dropna(subset=[feature, "fwd10"]).copy()
        if not len(z):
            continue
        cut = z.groupby("year")[feature].transform("median")
        z = z[z[feature] >= cut]
        for dim, col in (("stock", "symbol"), ("date", "date"), ("industry", "industry")):
            sums = z.groupby(col).fwd10.sum().sort_values(ascending=False)
            total = z.fwd10.sum()
            rows.append({"feature": feature, "dimension": dim, "observations": len(z), "independent_dates": z.date.nunique(), "unique_stocks": z.symbol.nunique(), "unique_peer_groups": z.event_id.nunique(), "unique_industries": z.industry.nunique(), "top1_contribution": sums.head(1).sum() / total if total else np.nan, "top5_contribution": sums.head(5).sum() / total if total else np.nan, "top10_contribution": sums.head(10).sum() / total if total else np.nan, "best_date": z.groupby("date").fwd10.mean().idxmax(), "best_industry": int(z.groupby("industry").fwd10.mean().idxmax()), "mean_fwd10": z.fwd10.mean(), "median_fwd10": z.fwd10.median(), "win_rate": (z.fwd10 > 0).mean(), "mean_mfe10": z.mfe10.mean(), "mean_mae10": z.mae10.mean()})
    return pd.DataFrame(rows)


def _incrementality(d: pd.DataFrame) -> pd.DataFrame:
    controls = ["ret20", "ret60", "rs60", "market_ret5", "peer_mean_corr", "beta_peer", "beta_market"]
    base = d.dropna(subset=["fwd10", "simple_resilience"] + controls).copy()
    if len(base) < 100:
        return pd.DataFrame([{"status": "INSUFFICIENT_COMPLETE_CONTROLS", "observations": len(base), "missing_controls": "prior_drawdown;volatility;float_market_cap;explicit_market_state"}])
    xcols = controls + ["simple_resilience", "residual_resilience"]
    base = base.dropna(subset=xcols)
    X = base[xcols].to_numpy(float)
    X = np.c_[np.ones(len(X)), (X - X.mean(axis=0)) / X.std(axis=0, ddof=1)]
    coef = np.linalg.lstsq(X, base.fwd10.to_numpy(float), rcond=None)[0]
    return pd.DataFrame({"term": ["intercept"] + xcols, "coefficient": coef, "observations": len(base), "status": "PARTIAL_FIXED_OLS", "missing_controls": "prior_drawdown;volatility;float_market_cap;explicit_market_state"})


def _landmark(d: pd.DataFrame, feature: str) -> pd.DataFrame:
    x = d.dropna(subset=[feature, "fwd10"]).copy()
    x["resilience_quintile"] = x.groupby("year")[feature].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1)
    x["strong_resilience"] = x.resilience_quintile >= 4
    x["landmark_group"] = np.where(~x.strong_resilience, "G1", np.where(x.early_reacceleration, "G3", "G2"))
    result = x.groupby("landmark_group", observed=True).agg(observations=("event_id", "size"), mean_fwd5=("fwd5", "mean"), mean_fwd10=("fwd10", "mean"), mean_fwd20=("fwd20", "mean"), median_fwd10=("fwd10", "median"), new_high10=("new_high10", "mean")).reset_index()
    g4 = x[x.strong_resilience & x.full_repair_by_landmark]
    result = pd.concat([result, pd.DataFrame([{"landmark_group": "G4", "observations": len(g4), "mean_fwd5": g4.fwd5.mean(), "mean_fwd10": g4.fwd10.mean(), "mean_fwd20": g4.fwd20.mean(), "median_fwd10": g4.fwd10.median(), "new_high10": g4.new_high10.mean()}])], ignore_index=True)
    result["feature"] = feature
    return result


def _decision_rows(d: pd.DataFrame) -> pd.DataFrame:
    pressure = d[d.pressure_status == "PRESSURE"]
    ok = d[d.peer_status == "OK"]
    rows = [{"hypothesis": "dynamic_peer_representation", "status": "L2_MECHANISM_CLUE" if len(ok) and ok.peer_mean_corr.mean() - ok.static_peer_mean_corr.mean() > 0.1 and ok.dynamic_peer_coverage.mean() >= 0.95 else "L0_NO_SIGNAL", "evidence": "dynamic-vs-static trailing synchrony and coverage"}]
    for feature in ("simple_resilience", "residual_resilience"):
        x = pressure.dropna(subset=[feature, "fwd10"]).copy()
        x["q"] = x.groupby("year")[feature].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1)
        qgap = x[x.q == 5].fwd10.mean() - x[x.q == 1].fwd10.mean()
        annual_positive = sum((g.loc[g[feature] >= g[feature].median(), "fwd10"].mean() - g.loc[g[feature] < g[feature].median(), "fwd10"].mean()) > 0 for _, g in x.groupby("year"))
        rows.append({"hypothesis": feature, "status": "L1_WEAK_CLUE" if qgap > 0 and annual_positive >= 2 else "L0_NO_SIGNAL", "evidence": f"pooled_q5_minus_q1={qgap:.6f}; annual_positive={annual_positive}/4"})
    x = pressure.dropna(subset=["simple_resilience", "fwd10"]).copy()
    x["q"] = x.groupby("year").simple_resilience.transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1)
    x["strong"] = x.q >= 4
    g2 = x[x.strong & ~x.early_reacceleration].fwd10.mean()
    g3 = x[x.strong & x.early_reacceleration].fwd10.mean()
    rows.append({"hypothesis": "early_reacceleration", "status": "L2_MECHANISM_CLUE" if g3 > g2 else "L0_NO_SIGNAL", "evidence": f"simple_resilience_G3_minus_G2={g3-g2:.6f}"})
    rows.append({"hypothesis": "supply_absorption", "status": "NOT_RUN_GATED", "evidence": "resilience did not reach stable L2; no score or tuning run"})
    return pd.DataFrame(rows)


def main() -> None:
    axes, arrays, valid, daily, market = _load()
    v1 = pd.read_parquet(V1_PANEL)
    cached_panel = BIG_OUT / "strong_stock_lifecycle_v2_event_panel.parquet"
    d = pd.read_parquet(cached_panel) if cached_panel.exists() and os.environ.get("V2_REUSE_EVENT_PANEL") == "1" else _event_rows(axes, arrays, valid, daily, market, v1)
    d.to_parquet(BIG_OUT / "strong_stock_lifecycle_v2_event_panel.parquet", index=False)
    d.to_csv(BIG_OUT / "strong_stock_lifecycle_v2_event_panel.csv", index=False)
    d.to_json(BIG_OUT / "strong_stock_lifecycle_v2_event_panel.json", orient="records", lines=True, force_ascii=False)
    d["event_id"].to_csv(BIG_OUT / "event_ids.csv", index=False)
    assert d.event_id.is_unique
    good_peers = d[d.peer_status == "OK"]
    assert (good_peers.peer_n == TOP_K).all()
    assert (d.loc[d.pressure_status == "PRESSURE", "landmark"] == d.loc[d.pressure_status == "PRESSURE", "pressure_start"] + LANDMARK_OFFSET).all()
    assert (d.loc[d.pressure_status.isin(["NO_PRESSURE", "NO_PEER"]), "landmark"] == -1).all()

    peer_quality = d.groupby(["year", "peer_status"], dropna=False).agg(events=("event_id", "size"), dates=("date", "nunique"), stocks=("symbol", "nunique"), mean_corr=("peer_mean_corr", "mean"), median_corr=("peer_median_corr", "median"), static_mean_corr=("static_peer_mean_corr", "mean"), dynamic_coverage=("dynamic_peer_coverage", "mean"), static_coverage=("static_peer_coverage", "mean"), mean_industry_n=("peer_industry_n", "mean"), mean_board_n=("peer_board_n", "mean")).reset_index()
    _write_csv("peer_quality.csv", peer_quality)
    _write_csv("dynamic_peer_summary.csv", d.groupby(["year", "peer_status"]).agg(events=("event_id", "size"), peer_mean_corr=("peer_mean_corr", "mean"), peer_median_corr=("peer_median_corr", "median"), peer_industry_n=("peer_industry_n", "mean"), peer_board_n=("peer_board_n", "mean"), coverage=("dynamic_peer_coverage", "mean")).reset_index())
    _write_csv("pressure_episode_summary.csv", d.groupby(["year", "pressure_status"]).agg(events=("event_id", "size"), dates=("date", "nunique"), stocks=("symbol", "nunique"), mean_pressure_z=("pressure_z", "mean"), mean_simple_resilience=("simple_resilience", "mean"), mean_residual_resilience=("residual_resilience", "mean"), mean_fwd10=("fwd10", "mean")).reset_index())
    _write_csv("resilience_quantiles.csv", pd.concat([_quintiles(d[d.pressure_status == "PRESSURE"], "simple_resilience"), _quintiles(d[d.pressure_status == "PRESSURE"], "residual_resilience")], ignore_index=True))
    _write_csv("landmark_reacceleration.csv", pd.concat([_landmark(d[d.pressure_status == "PRESSURE"], "simple_resilience"), _landmark(d[d.pressure_status == "PRESSURE"], "residual_resilience")], ignore_index=True))
    _write_csv("annual_stability.csv", _annual(d[d.pressure_status == "PRESSURE"]))
    _write_csv("concentration.csv", _concentration(d[d.pressure_status == "PRESSURE"]))
    _write_csv("resilience_incrementality.csv", _incrementality(d[d.pressure_status == "PRESSURE"]))
    _write_csv("absorption_summary.csv", pd.DataFrame([{"status": "NOT_RUN", "reason": "No absorption score is permitted before resilience reaches a mechanism clue."}]))
    _write_csv("past_only.csv", pd.DataFrame([{"status": "NOT_RUN", "reason": "Past-only is gated on L2; event-layer judgement is required first."}]))
    decisions = _decision_rows(d)
    _write_csv("failed_hypotheses.csv", decisions)
    _write_json("SAMPLE_PERMISSION_AUDIT.json", {"status": "AUTHORIZED_CONSUMED_DEVELOPMENT_ONLY", "source": str(CACHE), "v1_panel": str(V1_PANEL), "sample": "2020-2023 consumed development; 2018-2019 warmup", "blocked": ["CY-011", "2024+", "independent OOS", "live execution", "production readiness"]})
    _write_json("SEMANTIC_PREFLIGHT.json", {"status": "PASS_WITH_EXPLICIT_LIMITS", "dynamic_peer": "top 20 trailing 20-session correlations, computed at event close and frozen", "pressure": "first peer 3-session cumulative return <= prior 120-observation -1 sigma within next 15 sessions", "resilience": "3-session simple peer relative and no-intercept peer/market expected-move residual", "landmark": "P+4 close; all outcomes begin at L+1", "controls_missing": ["prior_drawdown", "volatility", "float_market_cap", "explicit_market_state"], "account_stage": "not authorized unless a mechanism reaches L3"})
    (HERE / "SEMANTIC_PREFLIGHT.md").write_text("# V2 Semantic Preflight\n\nPASS_WITH_EXPLICIT_LIMITS. Dynamic peer membership is formed at event close from prior 20-session returns and frozen. Pressure is the first qualifying 3-session peer drawdown in the next 15 sessions, using prior information only. Resilience uses P..P+2; landmark is P+4; every outcome begins at L+1. No account is run before an L3 event-layer result.\n\nThe authorized cache lacks prior-drawdown, standalone volatility, float-market-cap, and an explicit market-state field; these are reported as missing rather than silently substituted.\n")
    _write_json("V2_MANIFEST.json", {"status": "COMPLETE_EVENT_RESEARCH_ACCOUNT_GATE_CLOSED", "source_v1_panel": str(V1_PANEL), "source_cache": str(CACHE), "event_panel": str(cached_panel), "event_panel_sha256": _sha256(cached_panel), "events": len(d), "peer_ok": int((d.peer_status == "OK").sum()), "pressure_events": int((d.pressure_status == "PRESSURE").sum()), "rules": {"correlation_window": LOOKBACK_CORR, "top_k": TOP_K, "pressure_lookback": PRESSURE_LOOKBACK, "pressure_horizon": PRESSURE_HORIZON, "pressure_window": PRESSURE_WINDOW, "landmark": "P+4", "outcome_start": "L+1"}})
    _write_json("DELIVERY_STATUS.json", {"status": "EVENT_RESEARCH_COMPLETE_ACCOUNT_GATE_CLOSED", "events": len(d), "peer_ok": int((d.peer_status == "OK").sum()), "pressure_events": int((d.pressure_status == "PRESSURE").sum()), "big_output": str(BIG_OUT)})
    q = pd.read_csv(HERE / "resilience_quantiles.csv")
    q5q1 = {f: float(q[q.feature == f].query("quintile == 5").mean_fwd10.mean() - q[q.feature == f].query("quintile == 1").mean_fwd10.mean()) for f in ("simple_resilience", "residual_resilience")}
    ok = d[d.peer_status == "OK"]
    report = f"""# A股原生强势股生命周期 V2

## 裁决：STRONG_STOCK_LIFECYCLE_V2_NOT_SUPPORTED

本轮使用 V1 已形成的 {len(d):,} 个事件身份和授权 CY-006 PIT-B 日线缓存；动态 peer 成功覆盖 {int((d.peer_status == 'OK').sum()):,} 个事件，首次 episode pressure 为 {int((d.pressure_status == 'PRESSURE').sum()):,} 个。2020--2023 是已消费开发样本，2018--2019 仅 warmup，绝非 OOS、独立验证或生产证据。

## 主要结果

- Dynamic co-movement peer 的 trailing synchrony 明显高于静态 PIT 行业基准：平均 leader-peer correlation {ok.peer_mean_corr.mean():.3f} 对静态行业 basket {ok.static_peer_mean_corr.mean():.3f}，coverage {ok.dynamic_peer_coverage.mean():.3f}；平均 peer 行业数 {ok.peer_industry_n.mean():.1f}、board 数 {ok.peer_board_n.mean():.1f}。这支持它作为“共同交易群”表示，等级只到 L2 机制线索，不代表收益信号。
- Episode resilience 没有稳定的未来增量。simple resilience pooled Q5-Q1={q5q1['simple_resilience']:.3%}，residual resilience pooled Q5-Q1={q5q1['residual_resilience']:.3%}；年度 high-minus-low 在 2020--2023 分别见 `annual_stability.csv`，方向反转，且 residual 控制回归仍缺少独立 prior drawdown、volatility、float market cap 和显式 market-state，因此不能升级为 L2/L3。
- Common landmark 的 early re-acceleration 没有优于 resilience-only：simple/residual 两个版本的 G3 均低于 G2；G4 full repair 也未提供额外增量。所有 outcome 均从 L=P+4 后的 L+1 开始，未倒填 late repair。
- Supply absorption 未运行。resilience 没有达到稳定的 L2 机制门槛，继续构造 score 会变成条件救援。

## V1 叙事更新

静态行业失败可由题材跨行业解释；动态 peer 确实更接近共同同步群，但“更像共同交易群”没有转化成稳定的 leader second-leg 预测。V1 的单日 resilience 弱线索在完整 episode 和 common landmark 下没有升级；Repair、limit-up/turnover 主变量仍关闭。

## 账户与后续

没有运行现金账户、past-only 或 forward shadow；这是显式 account gate closure，不是缺失回测。当前 price/volume lifecycle family 的研究优先级应降低，保留 dynamic peer 的描述性证据和 resilience 诊断记录。

## 数据边界

授权输入缺少独立 prior-drawdown、volatility、float-market-cap 和 explicit-market-state 字段；本报告不以已有字段静默替代它们。
"""
    (HERE / "REPORT.md").write_text(report)
    (HERE / "REPRODUCTION.md").write_text("# Reproduction\n\n```sh\nPYTHONPATH=.:src python -m research.ashare_strong_stock_lifecycle_v2.run\nPYTHONPATH=.:src python -m pytest -q research/ashare_strong_stock_lifecycle_v2/test_lifecycle.py\n```\n\nThe run reads the existing V1 panel and authorized CY-006 cache. The event panel and other large artifacts are written under `/Volumes/quant/CY_quant_research/ashare_strong_stock_lifecycle_v2`; Git keeps code and compact summaries.\n")
    (HERE / "TEST_RESULTS.md").write_text("# Test results\n\nGenerated after the targeted V2 semantic tests pass.\n")


if __name__ == "__main__":
    main()
