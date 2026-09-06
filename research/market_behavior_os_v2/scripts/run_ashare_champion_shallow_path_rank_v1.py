#!/usr/bin/env python3
"""Generate one fixed shallow price-volume-path ranking rule on 2018-2020."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sklearn
from sklearn.tree import DecisionTreeRegressor

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
EXPERIMENT_ID = "ASHARE-CHAMPION-SHALLOW-PATH-RANK-V1"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
RULE_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_generated_rule.json"
SELECTION_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_generation_selection.csv"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
EXPECTED_SPEC_SHA256 = "07ad3482697075a6ff7eaeed9569ac983375d464646d51e9bd7a2abaf03d2288"
GENERATION_END = date(2020, 12, 31)


class ShallowPathRankError(RuntimeError):
    """Fail-closed shallow-rule generation error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise ShallowPathRankError("frozen generation spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_GENERATION_PROTOCOL_BEFORE_OUTCOME_MODEL":
        raise ShallowPathRankError("generation spec is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise ShallowPathRankError(f"bound input changed: {name}")
    return spec


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
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    return value


def _load_generation(spec: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    features = [row["name"] for row in spec["fixed_features"]]
    trade_columns = [
        "signal_date",
        "symbol",
        "industry",
        "final_net_return",
        "capacity_cny",
    ]
    trades = pd.read_parquet(
        _resolve(spec["inputs"]["champion_trade_panel"]["path"]),
        columns=trade_columns,
        filters=[("signal_date", "<=", GENERATION_END)],
    )
    trades["signal_date"] = pd.to_datetime(trades.signal_date).dt.date
    if trades.empty or max(trades.signal_date) > GENERATION_END:
        raise ShallowPathRankError("validation outcome crossed generation boundary")
    daily = pd.read_parquet(
        _resolve(spec["inputs"]["causal_daily_panel"]["path"]),
        columns=["trade_date", "symbol", "industry", *features],
        filters=[("trade_date", "<=", GENERATION_END)],
    )
    daily["signal_date"] = pd.to_datetime(daily.pop("trade_date")).dt.date
    frame = trades.merge(
        daily,
        on=["signal_date", "symbol", "industry"],
        how="left",
        validate="one_to_one",
    )
    if len(frame) != len(trades):
        raise ShallowPathRankError("generation feature alignment failed")
    incomplete = frame[features].isna().any(axis=1)
    missing_excluded = int(incomplete.sum())
    frame = frame.loc[~incomplete].copy()
    if not np.isfinite(frame[features].to_numpy(dtype=float)).all():
        raise ShallowPathRankError("nonfinite generation feature")
    if frame.duplicated(["signal_date", "symbol"]).any():
        raise ShallowPathRankError("duplicate generation key")
    counts = frame.groupby("signal_date").size()
    if counts.min() < 8 or counts.max() > 10:
        raise ShallowPathRankError("unexpected Champion generation breadth")
    frame["year"] = pd.to_datetime(frame.signal_date).dt.year
    frame.attrs["missing_feature_rows_excluded"] = missing_excluded
    return frame, features


def _serialize_tree(
    model: DecisionTreeRegressor, features: list[str], spec: dict[str, Any]
) -> dict[str, Any]:
    tree = model.tree_
    nodes: list[dict[str, Any]] = []
    for node_id in range(tree.node_count):
        feature_index = int(tree.feature[node_id])
        leaf = feature_index < 0
        node = {
            "node_id": node_id,
            "samples": int(tree.n_node_samples[node_id]),
            "predicted_net_return": float(tree.value[node_id][0][0]),
            "is_leaf": leaf,
        }
        if not leaf:
            node.update(
                {
                    "feature": features[feature_index],
                    "threshold": float(tree.threshold[node_id]),
                    "left_node": int(tree.children_left[node_id]),
                    "right_node": int(tree.children_right[node_id]),
                    "decision": "left when feature <= threshold; right otherwise",
                }
            )
        nodes.append(node)
    used = sorted({node["feature"] for node in nodes if not node["is_leaf"]})
    return {
        "experiment_id": EXPERIMENT_ID,
        "status": "GENERATED_FROM_2018_2020_ONLY",
        "claim_boundary": spec["claim_boundary"],
        "features_in_fixed_order": features,
        "used_split_features": used,
        "model": spec["fixed_model"],
        "sklearn_version": sklearn.__version__,
        "nodes": nodes,
        "selection": spec["fixed_selection_screen"],
        "first_actionable_time": "next legal open after the completed signal close",
        "validation_outcomes_read": "NO",
        "post_2023_outcomes_read": "NO",
        "cy011_read": "NO",
    }


def _period_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    selected = frame.loc[frame.selected]
    return {
        "decision_dates": int(frame.signal_date.nunique()),
        "all_rows": len(frame),
        "selected_rows": len(selected),
        "all_mean_return": float(frame.final_net_return.mean()),
        "selected_mean_return": float(selected.final_net_return.mean()),
        "selected_minus_all_mean_return": float(
            selected.final_net_return.mean() - frame.final_net_return.mean()
        ),
        "all_median_return": float(frame.final_net_return.median()),
        "selected_median_return": float(selected.final_net_return.median()),
        "all_winner_fraction": float(frame.final_net_return.gt(0).mean()),
        "selected_winner_fraction": float(selected.final_net_return.gt(0).mean()),
        "all_severe_fraction": float(frame.final_net_return.le(-0.10).mean()),
        "selected_severe_fraction": float(selected.final_net_return.le(-0.10).mean()),
        "severe_loss_improvement": float(
            frame.final_net_return.le(-0.10).mean()
            - selected.final_net_return.le(-0.10).mean()
        ),
    }


def _screen(
    frame: pd.DataFrame, model: DecisionTreeRegressor, features: list[str]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    screen = frame.copy()
    screen["predicted_net_return"] = model.predict(screen[features].to_numpy(float))
    screen = screen.sort_values(
        [
            "signal_date",
            "predicted_net_return",
            "diffusion_score",
            "max_return20",
            "symbol",
        ],
        ascending=[True, False, False, True, True],
    )
    screen["selection_rank"] = screen.groupby("signal_date").cumcount() + 1
    screen["selected"] = screen.selection_rank.le(3)
    if not screen.groupby("signal_date").selected.sum().eq(3).all():
        raise ShallowPathRankError("generation Top-3 selection failed")
    metrics = {
        "generation_2018_2020": _period_metrics(screen),
        "generation_2018_2019": _period_metrics(screen.loc[screen.year.le(2019)]),
        "generation_2020": _period_metrics(screen.loc[screen.year.eq(2020)]),
    }
    return screen, metrics


def _gate(
    frame: pd.DataFrame,
    metrics: dict[str, Any],
    rule: dict[str, Any],
    spec: dict[str, Any],
) -> tuple[dict[str, bool], bool]:
    gate = spec["generation_gate_all_required"]
    full = metrics["generation_2018_2020"]
    early = metrics["generation_2018_2019"]
    year2020 = metrics["generation_2020"]
    used = len(rule["used_split_features"])
    checks = {
        "complete_rows": len(frame) >= gate["minimum_complete_rows"],
        "decision_dates": frame.signal_date.nunique() >= gate["minimum_decision_dates"],
        "selected_mean": full["selected_mean_return"] >= gate["selected_mean_return"],
        "selected_improvement": full["selected_minus_all_mean_return"]
        >= gate["selected_minus_all_mean_return"],
        "selected_median": full["selected_median_return"]
        >= gate["selected_median_return"],
        "severe": full["severe_loss_improvement"]
        >= gate["minimum_severe_loss_improvement"],
        "2018_2019": early["selected_minus_all_mean_return"]
        >= gate["minimum_2018_2019_selected_minus_all"],
        "2020": year2020["selected_minus_all_mean_return"]
        >= gate["minimum_2020_selected_minus_all"],
        "split_features": gate["minimum_distinct_split_features"]
        <= used
        <= gate["maximum_distinct_split_features"],
    }
    return checks, all(checks.values())


def _render(result: dict[str, Any]) -> str:
    full = result["generation_metrics"]["generation_2018_2020"]
    rule = result["generated_rule"]
    nodes = [node for node in rule["nodes"] if not node["is_leaf"]]
    rule_lines = [
        f"- `{node['feature']} <= {node['threshold']:.8g}` at node {node['node_id']}"
        for node in nodes
    ]
    return "\n".join(
        [
            "# Champion shallow price-volume-path rank V1",
            "",
            f"Status: `{result['status']}`.",
            "",
            "## Generated transparent rule",
            "",
            *rule_lines,
            "",
            (
                f"Used split features: {', '.join(rule['used_split_features'])}. "
                "The tree has depth at most two and no validation outcome was read."
            ),
            "",
            "## Generation screen",
            "",
            (
                f"Top-3 mean {full['selected_mean_return']:.3%} versus all-ten "
                f"{full['all_mean_return']:.3%}; improvement "
                f"{full['selected_minus_all_mean_return']:.3%}; selected median "
                f"{full['selected_median_return']:.3%}; severe-loss improvement "
                f"{full['severe_loss_improvement']:.3%}."
            ),
            "",
            f"All generation gates pass: `{result['generation_passed']}`.",
            "",
            (
                "This is in-sample rule generation on consumed 2018-2020 history. "
                "A separate hash-bound experiment is required before 2021-2023 "
                "validation or executable replay. Post-2023 outcomes and CY-011 "
                "were not read."
            ),
            "",
        ]
    )


def run() -> dict[str, Any]:
    spec = _load_spec()
    frame, features = _load_generation(spec)
    model_spec = spec["fixed_model"]
    model = DecisionTreeRegressor(
        criterion=model_spec["criterion"],
        max_depth=model_spec["max_depth"],
        min_samples_leaf=model_spec["min_samples_leaf"],
        random_state=model_spec["random_state"],
    )
    model.fit(frame[features].to_numpy(float), frame.final_net_return.to_numpy(float))
    rule = _serialize_tree(model, features, spec)
    _atomic_write(RULE_PATH, json.dumps(_clean(rule), indent=2, sort_keys=True) + "\n")
    screen, metrics = _screen(frame, model, features)
    checks, passed = _gate(frame, metrics, rule, spec)
    compact = screen[
        [
            "signal_date",
            "symbol",
            "industry",
            "predicted_net_return",
            "selection_rank",
            "selected",
            "final_net_return",
        ]
    ].sort_values(["signal_date", "selection_rank"])
    _atomic_write(
        SELECTION_PATH,
        compact.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    result = {
        "experiment_id": EXPERIMENT_ID,
        "status": "GENERATION_RULE_EARNED_VALIDATION" if passed else "GENERATION_FAILED",
        "claim_boundary": spec["claim_boundary"],
        "generation_outcome_start": min(frame.signal_date),
        "generation_outcome_end": max(frame.signal_date),
        "missing_feature_rows_excluded": frame.attrs[
            "missing_feature_rows_excluded"
        ],
        "validation_outcomes_read": "NO",
        "post_2023_outcomes_read": "NO",
        "cy011_read": "NO",
        "generated_rule": rule,
        "generation_metrics": metrics,
        "generation_checks": checks,
        "generation_passed": passed,
        "portfolio_replay_run": False,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "rule_sha256": sha256_file(RULE_PATH),
            "selection_sha256": sha256_file(SELECTION_PATH),
        },
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
