#!/usr/bin/env python3
"""Compare a frozen, small set of CHINEXT candidate-ranking models."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.tree import DecisionTreeRegressor, export_text

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/HAB-CHX-RANK-MODEL-001_spec.json"
RESULT_PATH = PROGRAM / "artifacts/HAB-CHX-RANK-MODEL-001_result.json"
REPORT_PATH = PROGRAM / "reports/HAB-CHX-RANK-MODEL-001_selection_report.md"
EXPECTED_SPEC_SHA256 = "db236b45011a372c6e186fc01c35861cae610fc6ca66f53db8e8f1e6d7d4f247"

BLOCKS = {
    "chronological_development_2020_2021": (2020, 2021),
    "consumed_2022_2023": (2022, 2023),
}
BASELINE = "BASELINE_RS_SCORE"
SINGLE = "SINGLE_MINVOL_LOCATION"
MODEL_NAMES = ("RIDGE_ALPHA_10", "TREE_DEPTH_2")


class CandidateModelError(RuntimeError):
    """Fail-closed candidate-model contract error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise CandidateModelError("candidate-model spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_AFTER_MARGINAL_SCAN_BEFORE_MULTIVARIATE_ESTIMATES":
        raise CandidateModelError("candidate-model honesty status changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise CandidateModelError(f"bound input identity mismatch: {name}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "0.20", "future outcome", "random"):
        if phrase not in prohibited:
            raise CandidateModelError(f"missing prohibition: {phrase}")
    return spec


def _load_panel(spec: dict[str, Any]) -> pd.DataFrame:
    path = _resolve(spec["inputs"]["candidate_panel"]["path"])
    panel = pd.read_csv(path, parse_dates=["trade_date"])
    panel["year"] = panel.trade_date.dt.year
    model_inputs = spec["model_inputs"]
    forbidden = {
        "forward_return_5",
        "forward_return_20",
        "mfe_20",
        "mae_20",
        "actual_completed_trade_return",
        "selected_by_current_system",
        "next_open_price",
    }
    if forbidden.intersection(model_inputs):
        raise CandidateModelError("future or realized field entered model inputs")
    if (
        len(panel) != 398
        or panel.trade_date.max() > pd.Timestamp("2023-12-31")
        or panel.trade_date.min() < pd.Timestamp("2018-01-01")
        or panel.duplicated(["trade_date", "symbol"]).any()
        or panel[model_inputs].isna().any().any()
    ):
        raise CandidateModelError("candidate panel shape, period, key, or coverage changed")
    complete_per_date = panel.groupby("trade_date")["forward_return_20"].transform("count")
    panel["eligible_top1"] = (
        panel.candidate_count.ge(2) & complete_per_date.eq(panel.candidate_count)
    )
    panel["eligible_top3"] = (
        panel.candidate_count.ge(4) & complete_per_date.eq(panel.candidate_count)
    )
    if int(panel.loc[panel.eligible_top1, "trade_date"].nunique()) != 74:
        raise CandidateModelError("complete multi-candidate decision-date count changed")
    return panel


def _add_static_scores(panel: pd.DataFrame, spec: dict[str, Any]) -> list[str]:
    panel[f"score__{BASELINE}"] = panel["oriented_pct__rs_score"]
    panel[f"score__{SINGLE}"] = panel["oriented_pct__minvol_location"]
    names = [BASELINE, SINGLE]
    for name, bundle in spec["equal_weight_bundles"].items():
        columns = [f"oriented_pct__{feature}" for feature in bundle["inputs"]]
        panel[f"score__{name}"] = panel[columns].mean(axis=1)
        names.append(name)
    return names


def _model_matrix(panel: pd.DataFrame, spec: dict[str, Any]) -> np.ndarray:
    columns = [f"oriented_pct__{feature}" for feature in spec["model_inputs"]]
    return panel[columns].to_numpy(float)


def _fit_models(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    for name in MODEL_NAMES:
        panel[f"score__{name}"] = np.nan
    artifacts: dict[str, Any] = {}
    chronology = spec["chronology"]
    for year in range(chronology["first_scored_year"], chronology["last_scored_year"] + 1):
        training = panel.loc[
            panel.trade_date.lt(pd.Timestamp(year=year, month=1, day=1))
            & panel.forward_return_20.notna()
        ]
        scoring = panel.loc[panel.year.eq(year)]
        if len(training) < chronology["minimum_training_rows"] or scoring.empty:
            raise CandidateModelError(f"insufficient chronological rows for {year}")
        x_train = _model_matrix(training, spec)
        target = training.forward_return_20.clip(-0.25, 0.50).to_numpy(float)
        x_score = _model_matrix(scoring, spec)

        ridge_spec = spec["fixed_models"]["RIDGE_ALPHA_10"]
        ridge = Ridge(
            alpha=float(ridge_spec["alpha"]),
            fit_intercept=bool(ridge_spec["fit_intercept"]),
        ).fit(x_train, target)
        panel.loc[scoring.index, "score__RIDGE_ALPHA_10"] = ridge.predict(x_score)

        tree_spec = spec["fixed_models"]["TREE_DEPTH_2"]
        tree = DecisionTreeRegressor(
            max_depth=int(tree_spec["max_depth"]),
            min_samples_leaf=int(tree_spec["min_samples_leaf"]),
            random_state=int(tree_spec["random_state"]),
        ).fit(x_train, target)
        panel.loc[scoring.index, "score__TREE_DEPTH_2"] = tree.predict(x_score)

        artifacts[str(year)] = {
            "training_rows": len(training),
            "training_end": training.trade_date.max().date().isoformat(),
            "ridge_intercept": float(ridge.intercept_),
            "ridge_coefficients": dict(
                zip(spec["model_inputs"], (float(value) for value in ridge.coef_), strict=True)
            ),
            "tree_node_count": int(tree.tree_.node_count),
            "tree_depth": int(tree.tree_.max_depth),
            "tree_rules": export_text(tree, feature_names=spec["model_inputs"]).strip(),
        }
    return artifacts


def _metrics(values: pd.Series) -> dict[str, Any]:
    finite = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    return {
        "n": len(finite),
        "mean": float(np.mean(finite)) if len(finite) else None,
        "median": float(np.median(finite)) if len(finite) else None,
        "win_rate": float(np.mean(finite > 0)) if len(finite) else None,
        "winner20_rate": float(np.mean(finite >= 0.20)) if len(finite) else None,
        "severe_loss_rate": float(np.mean(finite <= -0.10)) if len(finite) else None,
    }


def _select(panel: pd.DataFrame, name: str, top_n: int) -> pd.DataFrame:
    eligibility = "eligible_top1" if top_n == 1 else "eligible_top3"
    score = f"score__{name}"
    rows = panel.loc[panel[eligibility] & panel[score].notna()].copy()
    rows = rows.sort_values(
        ["trade_date", score, "baseline_rank", "symbol"],
        ascending=[True, False, True, True],
    )
    return rows.groupby("trade_date", as_index=False).head(top_n)


def _evaluate(panel: pd.DataFrame, name: str) -> dict[str, Any]:
    top1 = _select(panel, name, 1)
    top3 = _select(panel, name, 3)
    result: dict[str, Any] = {"blocks": {}, "annual_top1": {}}
    for block, years in BLOCKS.items():
        chosen = top1.loc[top1.year.isin(years)]
        grouped_top3 = (
            top3.loc[top3.year.isin(years)]
            .groupby("trade_date", as_index=False)
            .agg(forward_return_20=("forward_return_20", "mean"))
        )
        result["blocks"][block] = {
            "top1": _metrics(chosen.forward_return_20),
            "top1_mae": _metrics(chosen.mae_20),
            "top3_date_mean": _metrics(grouped_top3.forward_return_20),
        }
    for year, chosen in top1.groupby("year"):
        if int(year) >= 2020:
            result["annual_top1"][str(int(year))] = _metrics(chosen.forward_return_20)
    return result


def _promotion_role(
    evaluation: dict[str, Any], baseline: dict[str, Any], spec: dict[str, Any]
) -> str:
    del spec
    strong = True
    risk = True
    for block in BLOCKS:
        current = evaluation["blocks"][block]["top1"]
        base = baseline["blocks"][block]["top1"]
        strong &= (
            current["n"] >= 20
            and current["mean"] > base["mean"]
            and current["severe_loss_rate"] <= base["severe_loss_rate"]
        )
        risk &= (
            current["n"] >= 20
            and current["severe_loss_rate"] <= base["severe_loss_rate"] - 0.05
            and current["mean"] >= base["mean"] - 0.01
        )
    if strong:
        return "STRONG_ENGINE_REPLAY_CANDIDATE"
    if risk:
        return "RISK_ENGINE_REPLAY_CANDIDATE"
    return "NO_ENGINE_REPLAY"


def _analyze(panel: pd.DataFrame, spec: dict[str, Any], static_names: list[str]) -> dict[str, Any]:
    names = [*static_names, *MODEL_NAMES]
    evaluations = {name: _evaluate(panel, name) for name in names}
    baseline = evaluations[BASELINE]
    roles = {
        name: (
            "CURRENT_BASELINE"
            if name == BASELINE
            else _promotion_role(evaluations[name], baseline, spec)
        )
        for name in names
    }
    scored_candidates = [
        name for name in names if roles[name].endswith("ENGINE_REPLAY_CANDIDATE")
    ]

    def replay_value(name: str) -> tuple[float, float, str]:
        mean_delta = sum(
            evaluations[name]["blocks"][block]["top1"]["mean"]
            - baseline["blocks"][block]["top1"]["mean"]
            for block in BLOCKS
        )
        risk_delta = sum(
            baseline["blocks"][block]["top1"]["severe_loss_rate"]
            - evaluations[name]["blocks"][block]["top1"]["severe_loss_rate"]
            for block in BLOCKS
        )
        return (mean_delta, risk_delta, name)

    shortlist = sorted(scored_candidates, key=replay_value, reverse=True)[:2]
    return {
        "experiment_id": spec["experiment_id"],
        "research_level": spec["research_level"],
        "status": "COMPLETE_CHRONOLOGICAL_MODEL_COMPARISON",
        "honesty_boundary": spec["honesty_boundary"],
        "counts": {
            "candidate_rows": len(panel),
            "complete_outcomes": int(panel.forward_return_20.notna().sum()),
            "complete_multi_candidate_dates": int(
                panel.loc[panel.eligible_top1, "trade_date"].nunique()
            ),
            "scored_model_start": "2020-01-01",
            "scored_model_end": "2023-12-31",
        },
        "evaluations": evaluations,
        "information_roles": roles,
        "engine_replay_shortlist": shortlist,
        "decision": (
            "REPLAY_SHORTLIST_ONLY"
            if shortlist
            else "NO_RANKING_MODEL_CLEARED_PREDECLARED_REPLAY_GATE"
        ),
        "claim_boundary": {
            "untouched_validation": False,
            "post_2023_rows_read": False,
            "cy011_read": False,
            "portfolio_replay": False,
            "hyperparameter_search": False,
            "future_fields_used_as_predictors": False,
        },
        "hashes": {
            "spec_sha256": EXPECTED_SPEC_SHA256,
            "inputs": {name: binding["sha256"] for name, binding in spec["inputs"].items()},
        },
    }


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# HAB-CHX-RANK-MODEL-001 — stock-selection comparison",
        "",
        "All results below are Top-1 choices on complete multi-candidate dates. "
        "The learned models are fit only on prior calendar years.",
        "",
        "| Ranker | Role | Mean dev | Severe dev | Mean 2022–23 | Severe 2022–23 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for name, evaluation in result["evaluations"].items():
        development = evaluation["blocks"]["chronological_development_2020_2021"]["top1"]
        consumed = evaluation["blocks"]["consumed_2022_2023"]["top1"]
        lines.append(
            f"| {name} | {result['information_roles'][name]} | "
            f"{development['mean']:.3%} | {development['severe_loss_rate']:.1%} | "
            f"{consumed['mean']:.3%} | {consumed['severe_loss_rate']:.1%} |"
        )
    shortlist = result["engine_replay_shortlist"]
    lines.extend(
        [
            "",
            "Executable replay shortlist: " + (", ".join(shortlist) if shortlist else "none"),
            "",
            "This is consumed 2018–2023 research, not untouched validation. No post-2023 "
            "or CY-011 row was read, and realized outcome/path fields were not predictors.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    spec = _load_spec()
    if RESULT_PATH.exists() or REPORT_PATH.exists():
        raise CandidateModelError("candidate-model output already exists")
    panel = _load_panel(spec)
    static_names = _add_static_scores(panel, spec)
    model_artifacts = _fit_models(panel, spec)
    result = _analyze(panel, spec, static_names)
    result["model_artifacts"] = model_artifacts
    _atomic_write(REPORT_PATH, _render(result))
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(
        RESULT_PATH,
        json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False) + "\n",
    )
    print(json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
