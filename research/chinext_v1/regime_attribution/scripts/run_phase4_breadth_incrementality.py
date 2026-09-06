#!/usr/bin/env python3
"""Targeted EXP-P4-001 breadth incrementality falsification."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
SPEC_PATH = WORK / "experiments/EXP-P4-002_spec.json"
OUT = WORK / "artifacts/breadth_incrementality.json"
REPORT = WORK / "reports/phase4_breadth_incrementality.md"
FEATURES = WORK / "artifacts/daily_regime_features.parquet"
TRADES = WORK / "artifacts/yearly_trades.csv"
P3 = WORK / "artifacts/univariate_attribution.json"
EXPECTED_SPEC = "f2416ab0f902ec458f01f5bb0caf0460f0a978a4658ba5a0d03ae81800c3041e"
EXPECTED = {
    FEATURES: "5fe1ec1cb1bdfa922dd838bd1f559de9463d4926f56dfed09427d826c7465bc6",
    TRADES: "77f28da56a3e36801373b0b356a6e36236095b17dbdb3183a8b1b0a4c8ab3deb",
    P3: "9fec0656ccc7b0a44b31800878160bc0e5c16d06fd67773bf3bab6be93c30a0c",
}


class IncrementalityError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def load() -> tuple[dict[str, Any], pd.DataFrame, dict[str, str]]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC:
        raise IncrementalityError("EXP-P4-001 spec hash mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    identities = {str(path): sha256_file(path) for path in EXPECTED}
    mismatch = {str(path): identities[str(path)] for path, expected in EXPECTED.items() if identities[str(path)] != expected}
    if mismatch:
        raise IncrementalityError(f"input identity mismatch: {mismatch}")
    feature_frame = pd.read_parquet(FEATURES)
    trade_frame = pd.read_csv(TRADES)
    feature_frame["trade_date"] = pd.to_datetime(feature_frame.trade_date).dt.strftime("%Y-%m-%d")
    joined = trade_frame.merge(feature_frame, left_on=["baseline_block", "entry_signal_date"], right_on=["baseline_block", "trade_date"], how="left", validate="many_to_one")
    if len(joined) != 399 or joined.trade_date.isna().any():
        raise IncrementalityError("frozen entry-date join mismatch")
    joined["entry_year"] = pd.to_datetime(joined.entry_signal_date).dt.year
    joined["winner_ge20"] = (joined.round_trip_return >= 0.20).astype(int)
    joined["winner_ge50"] = (joined.round_trip_return >= 0.50).astype(int)
    return spec, joined, identities


def partial_rank(frame: pd.DataFrame, feature: str, outcome: str, controls: list[str]) -> tuple[int, float | None]:
    columns = ["entry_year", feature, outcome, *controls]
    data = frame[columns].replace([np.inf, -np.inf], np.nan).dropna().copy()
    if len(data) < 30:
        return len(data), None
    ranked = pd.DataFrame(index=data.index)
    ranked[feature] = data[feature].rank(method="average", pct=True)
    for control in controls:
        ranked[control] = data[control].rank(method="average", pct=True)
    ranked[outcome] = data[outcome] if outcome.startswith(("winner_", "severe_")) else data[outcome].rank(method="average", pct=True)
    years = pd.get_dummies(data.entry_year.astype(str), prefix="year", drop_first=True, dtype=float)
    design = np.column_stack([np.ones(len(data)), ranked[controls].to_numpy(float), years.to_numpy(float)])
    x = ranked[feature].to_numpy(float)
    y = ranked[outcome].to_numpy(float)
    x_resid = x - design @ np.linalg.lstsq(design, x, rcond=None)[0]
    y_resid = y - design @ np.linalg.lstsq(design, y, rcond=None)[0]
    if np.std(x_resid) == 0 or np.std(y_resid) == 0:
        return len(data), None
    return len(data), float(np.corrcoef(x_resid, y_resid)[0, 1])


def trend_strata(frame: pd.DataFrame, feature: str, outcome: str, controls: list[str]) -> list[dict[str, Any]]:
    columns = ["entry_year", feature, outcome, *controls]
    data = frame[columns].replace([np.inf, -np.inf], np.nan).dropna().copy()
    for control in controls:
        data[f"_{control}"] = data.groupby("entry_year")[control].rank(method="average", pct=True)
    data["trend_composite"] = data[[f"_{control}" for control in controls]].mean(axis=1)
    data["trend_quintile"] = pd.qcut(data.trend_composite.rank(method="first"), 5, labels=False) + 1
    rows = []
    for quintile, group in data.groupby("trend_quintile", sort=True):
        ranked = group[feature].rank(method="average", pct=True)
        low, high = group[ranked <= 1 / 3], group[ranked >= 2 / 3]
        rows.append({
            "trend_quintile": int(quintile), "count": len(group), "low_count": len(low), "high_count": len(high),
            "top_minus_bottom": float(high[outcome].mean() - low[outcome].mean()) if len(low) and len(high) else None,
        })
    return rows


def main() -> int:
    spec, joined, identities = load()
    breadth, controls, outcomes = spec["breadth_features"], spec["fixed_controls"], spec["outcomes"]
    results: dict[str, Any] = {}
    survivors = []
    for feature in breadth:
        feature_results: dict[str, Any] = {}
        for outcome in outcomes:
            n, rho = partial_rank(joined, feature, outcome, controls)
            loyo = {}
            for year in range(2018, 2026):
                _, estimate = partial_rank(joined[joined.entry_year != year], feature, outcome, controls)
                loyo[str(year)] = estimate
            same_sign = 0 if rho is None or rho == 0 else sum(value is not None and value * rho > 0 for value in loyo.values())
            strata = trend_strata(joined, feature, outcome, controls)
            positive_strata = sum(row["top_minus_bottom"] is not None and row["top_minus_bottom"] > 0 for row in strata)
            feature_results[outcome] = {"n": n, "partial_rank_rho": rho, "loyo": loyo, "loyo_same_sign_count": same_sign, "trend_strata": strata, "positive_strata_count": positive_strata}
        best_outcome = max(("mfe", "winner_ge20"), key=lambda outcome: feature_results[outcome]["partial_rank_rho"] if feature_results[outcome]["partial_rank_rho"] is not None else -999)
        best = feature_results[best_outcome]
        winner50 = feature_results["winner_ge50"]["partial_rank_rho"]
        passes = best["partial_rank_rho"] is not None and best["partial_rank_rho"] >= 0.10 and best["loyo_same_sign_count"] >= 7 and best["positive_strata_count"] >= 4 and not (winner50 is not None and winner50 <= -0.10)
        if passes:
            survivors.append({"feature": feature, "outcome": best_outcome, "partial_rank_rho": best["partial_rank_rho"]})
        results[feature] = {"outcomes": feature_results, "passes_support_gate": passes, "selected_evaluation_outcome": best_outcome}
    decision = "SUPPORTED_INCREMENTAL_WITH_QUALIFICATION" if len(survivors) >= 2 else ("REJECTED_INCREMENTAL" if not survivors else "AMBIGUOUS_REFINE")
    payload = {
        "experiment_id": "EXP-P4-002", "result": "PASS", "decision": decision,
        "input_hashes": identities, "sample_cycles": len(joined), "controls": controls,
        "breadth_features": breadth, "results": results, "survivors": survivors,
        "falsification": {"additional_controls_tested": 0, "interactions_tested": 0, "strategy_thresholds_selected": 0, "overlays_tested": 0},
    }
    atomic_text(OUT, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Phase 4 — breadth incrementality falsification", "", "## Decision", "",
        f"`{decision}`. This remains exploratory mechanism evidence, not a strategy rule or untouched OOS result.", "",
        "## Evidence", "", "| Breadth feature | Best outcome | Partial rho | LOYO same sign | Positive trend strata | Pass |", "|---|---|---:|---:|---:|---|",
    ]
    for feature, result in results.items():
        outcome = result["selected_evaluation_outcome"]; row = result["outcomes"][outcome]
        lines.append(f"| {feature} | {outcome} | {row['partial_rank_rho']} | {row['loyo_same_sign_count']}/8 | {row['positive_strata_count']}/5 | {'YES' if result['passes_support_gate'] else 'NO'} |")
    lines += ["", "## Falsification", "", "The model uses only the three frozen trend controls and entry-year effects. LOYO and fixed trend-stratum comparisons were required; no alternative control set, interaction, threshold, or overlay was searched.", "", "## Strategy candidate", "", "None. Incremental association does not establish portfolio improvement or a safe exposure rule.", ""]
    atomic_text(REPORT, "\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
