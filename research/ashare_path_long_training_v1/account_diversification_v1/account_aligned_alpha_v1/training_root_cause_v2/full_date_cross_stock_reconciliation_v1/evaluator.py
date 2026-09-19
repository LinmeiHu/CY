"""Small reference evaluator for keyed, date-wise cross-sectional metrics."""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


KEYS = ["t", "j"]


def keyed_join(left: pd.DataFrame, right: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Join independently generated rows by identity, never array position."""
    cols = list(columns)
    if left.duplicated(KEYS).any() or right.duplicated(KEYS).any():
        raise ValueError("duplicate (t,j) identity")
    return left.merge(right[KEYS + cols], on=KEYS, how="inner", validate="one_to_one")


def rankic(score: np.ndarray, target: np.ndarray) -> tuple[float | None, int]:
    paired = np.isfinite(score) & np.isfinite(target)
    if paired.sum() < 2 or np.unique(score[paired]).size < 2 or np.unique(target[paired]).size < 2:
        return None, int(paired.sum())
    value = float(spearmanr(score[paired], target[paired]).statistic)
    return (value if np.isfinite(value) else None), int(paired.sum())


def evaluate_daily(frame: pd.DataFrame, score_col: str = "score", min_pairs: int = 50) -> pd.DataFrame:
    """Select by score before inspecting labels and retain coverage explicitly."""
    required = {"t", "j", score_col, "ret10", "ret20"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    rows: list[dict] = []
    for t, g in frame.groupby("t", sort=True):
        s = g[score_col].to_numpy(float)
        j = g.j.to_numpy(np.int64)
        if not np.isfinite(s).all():
            raise ValueError(f"non-finite score on t={t}")
        order = np.lexsort((j, -s))
        rec: dict = {"t": int(t), "eligible_rows": int(len(g))}
        for horizon in (10, 20):
            y = g[f"ret{horizon}"].to_numpy(float)
            finite = np.isfinite(y)
            ric, pairs = rankic(s, y)
            rec[f"rankic{horizon}"] = ric
            rec[f"rankic{horizon}_pairs"] = pairs
            rec[f"universe_ret{horizon}"] = float(y[finite].mean()) if finite.any() else None
            rec[f"universe_ret{horizon}_rows"] = int(finite.sum())
            for n in (10, 50):
                selected = order[: min(n, len(order))]
                observed = np.isfinite(y[selected])
                rec[f"top{n}_ret{horizon}_coverage"] = int(observed.sum())
                rec[f"top{n}_ret{horizon}_complete"] = bool(len(selected) == n and observed.all())
                partial = float(y[selected][observed].mean()) if observed.any() else None
                rec[f"top{n}_ret{horizon}_partial"] = partial
                rec[f"top{n}_ret{horizon}"] = partial if rec[f"top{n}_ret{horizon}_complete"] else None
                base = rec[f"universe_ret{horizon}"]
                rec[f"top{n}_lift{horizon}"] = (partial - base) if rec[f"top{n}_ret{horizon}_complete"] and base is not None else None
        # Horizon support is independent.  In particular, the final ten dates
        # of a fold can have mature Ret10 while Ret20 is not yet mature.
        if rec["rankic10_pairs"] >= min_pairs or rec["rankic20_pairs"] >= min_pairs:
            rows.append(rec)
    return pd.DataFrame(rows)


def aggregate_daily(daily: pd.DataFrame) -> dict:
    out: dict = {"dates": int(len(daily))}
    for col in daily.columns:
        if col == "t" or col.endswith("_complete"):
            continue
        finite = pd.to_numeric(daily[col], errors="coerce").dropna()
        out[col] = float(finite.mean()) if len(finite) else None
        out[f"{col}_valid_dates"] = int(len(finite))
    return out


def paired_robustness(candidate: pd.DataFrame, baseline: pd.DataFrame, column: str) -> dict:
    pair = candidate[["t", column]].merge(
        baseline[["t", column]], on="t", suffixes=("_candidate", "_baseline"), validate="one_to_one"
    )
    delta = pair[f"{column}_candidate"] - pair[f"{column}_baseline"]
    valid = np.isfinite(delta.to_numpy(float))
    values = delta.to_numpy(float)[valid]
    if not len(values):
        return {"status": "MISSING", "reason": "NO_FINITE_PAIRED_DATES", "dates": 0,
                "mean": None, "positive_dates": 0, "zero_dates": 0, "negative_dates": 0,
                "positive_date_fraction": None, "leave_best1": None, "leave_best3": None,
                "leave_best_block": None}
    ordered = values[np.argsort(values)]
    blocks = pd.Series(values).groupby(np.arange(len(values)) // 20).mean().to_numpy()
    return {
        "status": "OK", "reason": None, "dates": int(len(values)), "mean": float(values.mean()),
        "positive_dates": int((values > 0).sum()), "zero_dates": int((values == 0).sum()),
        "negative_dates": int((values < 0).sum()),
        "positive_date_fraction": float((values > 0).mean()),
        "leave_best1": float(ordered[:-1].mean()) if len(ordered) > 1 else None,
        "leave_best3": float(ordered[:-3].mean()) if len(ordered) > 3 else None,
        "leave_best_block": float(np.delete(blocks, np.argmax(blocks)).mean()) if len(blocks) > 1 else None,
    }
