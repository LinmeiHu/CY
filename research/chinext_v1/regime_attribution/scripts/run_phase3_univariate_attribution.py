#!/usr/bin/env python3
"""Execute preregistered EXP-P3-002 univariate regime attribution."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
SPEC = WORK / "experiments/EXP-P3-002_spec.json"
FEATURES = WORK / "artifacts/daily_regime_features.parquet"
FEATURE_AUDIT = WORK / "artifacts/regime_feature_audit.json"
TRADES = WORK / "artifacts/yearly_trades.csv"
DECOMPOSITION = WORK / "artifacts/yearly_decomposition.json"
BASELINE = WORK / "artifacts/baseline_manifest.json"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
OUTPUT_JSON = WORK / "artifacts/univariate_attribution.json"
OUTPUT_RESULTS = WORK / "artifacts/univariate_feature_results.csv"
OUTPUT_QUINTILES = WORK / "artifacts/univariate_quintiles.csv"
REPORT = WORK / "reports/phase3_univariate_attribution.md"

EXPECTED_SPEC = "0245156dc7a026636af75ee87d75c888405a99d408ec64968350aedb7c5232e7"
EXPECTED = {
    FEATURES: "5fe1ec1cb1bdfa922dd838bd1f559de9463d4926f56dfed09427d826c7465bc6",
    TRADES: "77f28da56a3e36801373b0b356a6e36236095b17dbdb3183a8b1b0a4c8ab3deb",
    DECOMPOSITION: "c86c41ba0a35192ca0c4e3b64679abcca614c69c1412ba75c78bb184bc3c8f9e",
    BASELINE: "682b45455442f00e15e6273622ab6566d1c5c1d94069efc5fbbd40cb17f0977b",
    STRATEGY: "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a",
}
CONTINUOUS = [
    "round_trip_return",
    "mfe",
    "mae",
    "return_5d",
    "return_10d",
    "return_20d",
]
BINARY = [
    "winner_ge20",
    "winner_ge50",
    "severe_loss_le_neg10",
    "extreme_loss_le_neg20",
]
OUTCOMES = CONTINUOUS + BINARY
MIN_SAMPLE = 100
SUBGROUP_MIN_SAMPLE = 10


class AttributionError(RuntimeError):
    """Raised when a frozen identity or causal attribution invariant fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return finite_or_none(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def spearman_estimate(
    feature: Iterable[Any], outcome: Iterable[Any], minimum: int = MIN_SAMPLE
) -> dict[str, Any]:
    pairs = pd.DataFrame({"feature": feature, "outcome": outcome}).dropna()
    result: dict[str, Any] = {
        "n": int(len(pairs)),
        "rho": None,
        "p_value": None,
        "status": "INSUFFICIENT_SAMPLE" if len(pairs) < minimum else "ESTIMATED",
    }
    if len(pairs) < minimum:
        return result
    if pairs.feature.nunique() < 2 or pairs.outcome.nunique() < 2:
        result["status"] = "CONSTANT_INPUT"
        return result
    estimate = spearmanr(pairs.feature.astype(float), pairs.outcome.astype(float))
    result["rho"] = finite_or_none(estimate.statistic)
    result["p_value"] = finite_or_none(estimate.pvalue)
    if result["rho"] is None:
        result["status"] = "NONFINITE_ESTIMATE"
    return result


def cliffs_delta_for_binary(feature: Iterable[Any], event: Iterable[Any]) -> float | None:
    pairs = pd.DataFrame({"feature": feature, "event": event}).dropna()
    positive = pairs.loc[pairs.event.astype(bool), "feature"].astype(float).to_numpy()
    negative = pairs.loc[~pairs.event.astype(bool), "feature"].astype(float).to_numpy()
    if len(positive) == 0 or len(negative) == 0:
        return None
    comparison = positive[:, None] - negative[None, :]
    return float((np.count_nonzero(comparison > 0) - np.count_nonzero(comparison < 0)) / comparison.size)


def benjamini_hochberg(p_values: list[float | None]) -> list[float | None]:
    valid = [(index, float(value)) for index, value in enumerate(p_values) if value is not None and math.isfinite(float(value))]
    if not valid:
        return [None] * len(p_values)
    ordered = sorted(valid, key=lambda item: (item[1], item[0]))
    adjusted: dict[int, float] = {}
    running = 1.0
    total = len(ordered)
    for reverse_index in range(total - 1, -1, -1):
        original_index, p_value = ordered[reverse_index]
        rank = reverse_index + 1
        running = min(running, p_value * total / rank)
        adjusted[original_index] = min(1.0, running)
    return [adjusted.get(index) for index in range(len(p_values))]


def sign(value: float | None) -> int:
    if value is None or not math.isfinite(float(value)) or value == 0:
        return 0
    return 1 if value > 0 else -1


def validate_inputs() -> dict[str, Any]:
    if sha256_file(SPEC) != EXPECTED_SPEC:
        raise AttributionError("EXP-P3-002 spec hash mismatch")
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_FEATURE_OUTCOME_JOIN":
        raise AttributionError("EXP-P3-002 is not frozen before the outcome join")
    actual = {str(path): sha256_file(path) for path in EXPECTED}
    mismatches = {
        str(path): {"expected": expected, "actual": actual[str(path)]}
        for path, expected in EXPECTED.items()
        if actual[str(path)] != expected
    }
    if mismatches:
        raise AttributionError(f"frozen attribution input mismatch: {mismatches}")
    if spec["inputs"]["daily_regime_features_sha256"] != actual[str(FEATURES)]:
        raise AttributionError("spec/feature binding mismatch")
    return spec


def load_and_join(spec: dict[str, Any]) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    feature_frame = pd.read_parquet(FEATURES)
    trade_frame = pd.read_csv(TRADES)
    audit = json.loads(FEATURE_AUDIT.read_text(encoding="utf-8"))
    feature_columns = sorted(audit["coverage"])
    if len(feature_columns) != 93 or not set(feature_columns).issubset(feature_frame.columns):
        raise AttributionError("Phase 2 feature identity/count mismatch")
    if len(feature_frame) != 1942 or feature_frame.trade_date.duplicated().any():
        raise AttributionError("Phase 2 daily identity mismatch")
    if len(trade_frame) != spec["join"]["expected_cycles"]:
        raise AttributionError("authoritative completed-cycle count mismatch")
    feature_frame["trade_date"] = pd.to_datetime(feature_frame.trade_date)
    feature_frame["first_applicable_trade_date"] = pd.to_datetime(
        feature_frame.first_applicable_trade_date
    )
    trade_frame["entry_signal_date"] = pd.to_datetime(trade_frame.entry_signal_date)
    trade_frame["entry_execution_date"] = pd.to_datetime(trade_frame.entry_execution_date)
    trade_frame["exit_signal_date"] = pd.to_datetime(trade_frame.exit_signal_date)
    trade_frame["exit_execution_date"] = pd.to_datetime(trade_frame.exit_execution_date)
    joined = trade_frame.merge(
        feature_frame,
        left_on=["baseline_block", "entry_signal_date"],
        right_on=["baseline_block", "trade_date"],
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    missing_join = joined[joined._merge != "both"]
    if not missing_join.empty:
        raise AttributionError(f"missing entry feature row: {missing_join.iloc[0].trade_id}")
    causal = (
        (joined.trade_date == joined.entry_signal_date)
        & (joined.first_applicable_trade_date > joined.entry_signal_date)
        & (joined.first_applicable_trade_date <= joined.entry_execution_date)
    )
    if not causal.all():
        row = joined.loc[~causal].iloc[0]
        raise AttributionError(f"causal join gate failed: {row.trade_id}")
    if joined.outcome_joined.any():
        raise AttributionError("Phase 2 outcome-contamination flag is not false")
    joined["entry_year"] = joined.entry_signal_date.dt.year
    joined["winner_ge20"] = joined.round_trip_return >= 0.20
    joined["winner_ge50"] = joined.round_trip_return >= 0.50
    joined["severe_loss_le_neg10"] = joined.round_trip_return <= -0.10
    joined["extreme_loss_le_neg20"] = joined.round_trip_return <= -0.20
    gate_failures = int((joined.index_close_to_ma20 <= 0).sum())
    if gate_failures:
        row = joined.loc[joined.index_close_to_ma20 <= 0].iloc[0]
        raise AttributionError(f"actual entry violates frozen market MA20 gate: {row.trade_id}")
    lineage = {
        "joined_cycles": int(len(joined)),
        "unique_trade_ids": int(joined.trade_id.nunique()),
        "missing_daily_join_rows": 0,
        "causal_gate_failures": 0,
        "same_signal_and_execution_date_count": int(
            (joined.entry_signal_date == joined.entry_execution_date).sum()
        ),
        "market_ma20_gate_failures": gate_failures,
        "entry_year_counts": {
            str(year): int(count)
            for year, count in joined.entry_year.value_counts().sort_index().items()
        },
        "block_counts": {
            str(block): int(count)
            for block, count in joined.baseline_block.value_counts().sort_index().items()
        },
    }
    return joined.drop(columns="_merge"), feature_columns, lineage


def primary_registry(spec: dict[str, Any]) -> tuple[dict[str, str], dict[str, int]]:
    family_by_feature: dict[str, str] = {}
    direction_by_feature: dict[str, int] = {}
    for family, details in spec["hypothesis_families"].items():
        for feature, direction in zip(
            details["primary_features"], details["expected_winner_direction"], strict=True
        ):
            if feature in family_by_feature:
                raise AttributionError(f"primary feature repeated across families: {feature}")
            family_by_feature[feature] = family
            direction_by_feature[feature] = int(direction)
    return family_by_feature, direction_by_feature


def subgroup_rhos(
    frame: pd.DataFrame, feature: str, outcome: str, group: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key, rows in frame.groupby(group, sort=True):
        result[str(key)] = spearman_estimate(
            rows[feature], rows[outcome], minimum=SUBGROUP_MIN_SAMPLE
        )
    return result


def build_result_rows(
    joined: pd.DataFrame,
    features: list[str],
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    family_by_feature, direction_by_feature = primary_registry(spec)
    top5_ids = set(
        joined.sort_values(
            ["realized_pnl", "trade_id"], ascending=[False, True]
        ).head(5).trade_id
    )
    rows: list[dict[str, Any]] = []
    for feature in features:
        within_rank = joined.groupby("entry_year", sort=False)[feature].rank(
            method="average", pct=True
        )
        for outcome in OUTCOMES:
            estimate = spearman_estimate(joined[feature], joined[outcome])
            within = spearman_estimate(within_rank, joined[outcome])
            loyo: dict[str, float | None] = {}
            for year in range(2018, 2026):
                subset = joined[joined.entry_year != year]
                loyo[str(year)] = spearman_estimate(
                    subset[feature], subset[outcome]
                )["rho"]
            full_sign = sign(estimate["rho"])
            same_sign_count = sum(sign(value) == full_sign and full_sign != 0 for value in loyo.values())
            available_loyo = sum(value is not None for value in loyo.values())
            direction_stable = bool(
                full_sign != 0
                and sign(within["rho"]) == full_sign
                and available_loyo == 8
                and same_sign_count >= 7
            )
            ex_best5 = None
            if outcome == "round_trip_return":
                subset = joined[~joined.trade_id.isin(top5_ids)]
                ex_best5 = spearman_estimate(subset[feature], subset[outcome])["rho"]
            row = {
                "feature": feature,
                "family": family_by_feature.get(feature, "COMPLETENESS_ONLY"),
                "is_preregistered_primary": feature in family_by_feature,
                "expected_winner_direction": direction_by_feature.get(feature),
                "outcome": outcome,
                "outcome_type": "continuous" if outcome in CONTINUOUS else "binary",
                "n": estimate["n"],
                "rho": estimate["rho"],
                "p_value": estimate["p_value"],
                "q_value_bh": None,
                "cliffs_delta_positive_vs_negative": (
                    cliffs_delta_for_binary(joined[feature], joined[outcome])
                    if outcome in BINARY
                    else None
                ),
                "within_year_rank_rho": within["rho"],
                "within_year_rank_n": within["n"],
                "loyo_same_sign_count": same_sign_count,
                "loyo_available_count": available_loyo,
                "direction_stable": direction_stable,
                "ex_best5_realized_pnl_rho": ex_best5,
                "loyo_rhos_json": json.dumps(clean_json(loyo), sort_keys=True),
                "entry_year_rhos_json": json.dumps(
                    clean_json(subgroup_rhos(joined, feature, outcome, "entry_year")),
                    sort_keys=True,
                ),
                "baseline_block_rhos_json": json.dumps(
                    clean_json(subgroup_rhos(joined, feature, outcome, "baseline_block")),
                    sort_keys=True,
                ),
            }
            rows.append(row)
    q_values = benjamini_hochberg([row["p_value"] for row in rows])
    for row, q_value in zip(rows, q_values, strict=True):
        row["q_value_bh"] = q_value
    return rows


def build_quintiles(joined: pd.DataFrame, features: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature in features:
        valid = joined[["trade_id", feature, *OUTCOMES]].dropna(subset=[feature]).copy()
        try:
            valid["quintile"] = pd.qcut(
                valid[feature], q=5, labels=False, duplicates="drop"
            )
        except ValueError:
            valid["quintile"] = np.nan
        bin_count = int(valid.quintile.nunique(dropna=True))
        for bin_number, sample in valid.dropna(subset=["quintile"]).groupby(
            "quintile", sort=True
        ):
            row: dict[str, Any] = {
                "feature": feature,
                "quintile": int(bin_number) + 1,
                "realized_bin_count": bin_count,
                "n": int(len(sample)),
                "feature_min": float(sample[feature].min()),
                "feature_median": float(sample[feature].median()),
                "feature_max": float(sample[feature].max()),
            }
            for outcome in CONTINUOUS:
                values = sample[outcome].dropna().astype(float)
                row[f"{outcome}_n"] = int(len(values))
                row[f"{outcome}_mean"] = float(values.mean()) if len(values) else None
                row[f"{outcome}_median"] = float(values.median()) if len(values) else None
            for outcome in BINARY:
                values = sample[outcome].dropna().astype(float)
                row[f"{outcome}_n"] = int(len(values))
                row[f"{outcome}_rate"] = float(values.mean()) if len(values) else None
            rows.append(row)
    return rows


def assess_primary_features(
    result_rows: list[dict[str, Any]], spec: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    by_key = {(row["feature"], row["outcome"]): row for row in result_rows}
    family_by_feature, direction_by_feature = primary_registry(spec)
    feature_assessment: dict[str, Any] = {}
    family_survivors: dict[str, list[str]] = {
        family: [] for family in spec["hypothesis_families"]
    }
    for feature, family in family_by_feature.items():
        expected = direction_by_feature[feature]
        winner = by_key[(feature, "winner_ge20")]
        mfe = by_key[(feature, "mfe")]
        winner50 = by_key[(feature, "winner_ge50")]
        endpoints: list[str] = []
        for label, row in (("winner_ge20", winner), ("mfe", mfe)):
            if (
                row["rho"] is not None
                and abs(row["rho"]) >= 0.10
                and row["direction_stable"]
                and expected != 0
                and sign(row["rho"]) == expected
            ):
                endpoints.append(label)
        opposite_winner50 = bool(
            expected != 0
            and winner50["rho"] is not None
            and abs(winner50["rho"]) >= 0.10
            and sign(winner50["rho"]) == -expected
        )
        survives = bool(expected != 0 and endpoints and not opposite_winner50)
        if survives:
            family_survivors[family].append(feature)
        feature_assessment[feature] = {
            "family": family,
            "expected_direction": expected,
            "winner_ge20_rho": winner["rho"],
            "winner_ge20_q": winner["q_value_bh"],
            "winner_ge20_within_year_rank_rho": winner["within_year_rank_rho"],
            "winner_ge20_loyo_same_sign_count": winner["loyo_same_sign_count"],
            "mfe_rho": mfe["rho"],
            "mfe_q": mfe["q_value_bh"],
            "mfe_within_year_rank_rho": mfe["within_year_rank_rho"],
            "mfe_loyo_same_sign_count": mfe["loyo_same_sign_count"],
            "winner_ge50_rho": winner50["rho"],
            "qualifying_endpoints": endpoints,
            "opposite_winner_ge50": opposite_winner50,
            "survives_preregistered_falsification": survives,
        }
    family_assessment: dict[str, Any] = {}
    for family, details in spec["hypothesis_families"].items():
        survivors = family_survivors[family]
        directions = details["expected_winner_direction"]
        if all(int(direction) == 0 for direction in directions):
            verdict = "AMBIGUOUS_UNIVARIATE_NO_SIGN_PREREGISTERED"
        elif len(survivors) >= 2:
            verdict = "SUPPORTED_FOR_FURTHER_CONDITIONAL_TESTING"
        elif len(survivors) == 0:
            verdict = "REJECTED_BY_PREREGISTERED_UNIVARIATE_FALSIFICATION"
        else:
            verdict = "AMBIGUOUS_SINGLE_FEATURE_SURVIVOR"
        family_assessment[family] = {
            "verdict": verdict,
            "primary_feature_count": len(details["primary_features"]),
            "surviving_feature_count": len(survivors),
            "surviving_features": survivors,
            "interaction_authorized": False,
        }
    return feature_assessment, family_assessment


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise AttributionError(f"refusing empty CSV output: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(clean_json(rows))
    temporary.replace(path)


def strongest_rows(
    result_rows: list[dict[str, Any]], outcome: str, primary_only: bool, limit: int = 10
) -> list[dict[str, Any]]:
    rows = [
        row
        for row in result_rows
        if row["outcome"] == outcome
        and row["rho"] is not None
        and (not primary_only or row["is_preregistered_primary"])
    ]
    return sorted(rows, key=lambda row: (-abs(row["rho"]), row["feature"]))[:limit]


def render_report(payload: dict[str, Any]) -> str:
    assessments = payload["primary_feature_assessment"]
    families = payload["family_assessment"]
    strongest_winner = payload["strongest_primary_winner_ge20"]
    strongest_mfe = payload["strongest_primary_mfe"]
    lines = [
        "# Phase 3 — preregistered univariate regime attribution",
        "",
        "EXP-P3-002 joined the frozen Phase 2 completed-close features to the 399 authoritative cycles on entry signal date. This is exploratory mechanism evidence over already-consumed 2018-2025 outcomes, not untouched OOS evidence and not a strategy experiment.",
        "",
        "## Causal and sample audit",
        "",
        f"- Joined completed cycles: `{payload['join_audit']['joined_cycles']}`; missing joins: `{payload['join_audit']['missing_daily_join_rows']}`",
        f"- Causal timestamp failures: `{payload['join_audit']['causal_gate_failures']}`; same-day fills: `{payload['join_audit']['same_signal_and_execution_date_count']}`",
        f"- Frozen market-MA20 entry-gate failures: `{payload['join_audit']['market_ma20_gate_failures']}`",
        f"- Features tested: `{payload['feature_count']}`; feature/outcome estimates: `{payload['estimate_count']}`; BH q<=0.10: `{payload['bh_q_le_0_10_count']}` (descriptive only)",
        "- Missing features and early continuation horizons were deleted pairwise; nothing was imputed or set to zero.",
        "",
        "## Preregistered family verdicts",
        "",
        "| Family | Verdict | Surviving primary features |",
        "|---|---|---|",
    ]
    for family, result in families.items():
        survivor_text = ", ".join(result["surviving_features"]) or "none"
        lines.append(f"| {family} | {result['verdict']} | {survivor_text} |")
    lines += [
        "",
        "A feature survives only if either its >=20% winner or MFE Spearman effect has |rho|>=0.10, matches the preregistered sign, agrees with the pooled within-year rank sign, keeps that sign in at least 7/8 leave-one-year-out estimates, and has no >=50% winner effect of |rho|>=0.10 in the opposite direction. A family needs at least two surviving primary features. Volatility had no monotone sign preregistered, so this phase cannot support H-007 or authorize an interaction by itself.",
        "",
        "## Primary feature diagnostics",
        "",
        "| Feature | Family | Exp sign | RT20 rho | Within-year RT20 | RT20 LOYO | MFE rho | Within-year MFE | MFE LOYO | Survives |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for feature, result in assessments.items():
        fmt = lambda value: "NA" if value is None else f"{value:.3f}"
        lines.append(
            f"| {feature} | {result['family']} | {result['expected_direction']} | "
            f"{fmt(result['winner_ge20_rho'])} | {fmt(result['winner_ge20_within_year_rank_rho'])} | "
            f"{result['winner_ge20_loyo_same_sign_count']}/8 | {fmt(result['mfe_rho'])} | "
            f"{fmt(result['mfe_within_year_rank_rho'])} | {result['mfe_loyo_same_sign_count']}/8 | "
            f"{'YES' if result['survives_preregistered_falsification'] else 'NO'} |"
        )
    lines += [
        "",
        "## Strongest preregistered descriptive associations",
        "",
        "These rankings are reports, not selection rules.",
        "",
        "| Endpoint | Feature | Spearman rho | BH q | Direction stable |",
        "|---|---|---:|---:|---|",
    ]
    for endpoint, rows in ((">=20% winner", strongest_winner), ("MFE", strongest_mfe)):
        for row in rows[:5]:
            q_text = "NA" if row["q_value_bh"] is None else f"{row['q_value_bh']:.3f}"
            lines.append(
                f"| {endpoint} | {row['feature']} | {row['rho']:.3f} | {q_text} | "
                f"{'YES' if row['direction_stable'] else 'NO'} |"
            )
    lines += [
        "",
        "## Falsification and limits",
        "",
        "- Every estimate includes within-entry-year ranks, eight LOYO estimates, entry-year and baseline-block views, and a global ex-best-five-P&L return sensitivity where applicable.",
        "- All actual entries are already conditioned on the binary 399102-above-MA20 gate. The analysis distinguishes continuous gate strength among admitted entries; it does not compare entries with forbidden non-entry days.",
        "- Pooled quintiles are fixed from feature values only and include all outcomes. They diagnose shape and monotonicity but do not define a threshold.",
        "- BH q-values address the reported 93-feature screen, but dependence, small tail-event counts, PIT-B lineage, and already-consumed outcomes cap evidentiary strength.",
        "- No interaction, overlay, entry gate, exposure rule, exit rule, or year parameter was tested or authorized in Phase 3.",
        "",
        "## Phase verdict",
        "",
        payload["phase_verdict"],
        "",
        f"Detailed result artifact SHA-256: `{payload['output_hashes']['univariate_feature_results_csv']}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    spec = validate_inputs()
    joined, features, join_audit = load_and_join(spec)
    result_rows = build_result_rows(joined, features, spec)
    quintile_rows = build_quintiles(joined, features)
    feature_assessment, family_assessment = assess_primary_features(result_rows, spec)
    write_csv(OUTPUT_RESULTS, result_rows)
    write_csv(OUTPUT_QUINTILES, quintile_rows)
    supported = [
        family
        for family, result in family_assessment.items()
        if result["verdict"] == "SUPPORTED_FOR_FURTHER_CONDITIONAL_TESTING"
    ]
    rejected = [
        family
        for family, result in family_assessment.items()
        if result["verdict"] == "REJECTED_BY_PREREGISTERED_UNIVARIATE_FALSIFICATION"
    ]
    if supported:
        phase_verdict = (
            "At least one preregistered family passed the univariate stability gate and may proceed only to a narrow, evidence-supported conditional test. This is not strategy authorization."
        )
    else:
        phase_verdict = (
            "No preregistered family passed the two-feature univariate stability gate. Interactions and V1-R design are not authorized without a separately justified refinement; negative and ambiguous results are retained."
        )
    payload: dict[str, Any] = {
        "experiment_id": "EXP-P3-002",
        "result": "PASS",
        "evidence_grade": spec["evidence_grade"],
        "spec_sha256": EXPECTED_SPEC,
        "input_hashes": {str(path): sha256_file(path) for path in EXPECTED},
        "feature_count": len(features),
        "outcomes": OUTCOMES,
        "estimate_count": len(result_rows),
        "quintile_row_count": len(quintile_rows),
        "join_audit": join_audit,
        "outcome_missingness": {
            outcome: int(joined[outcome].isna().sum()) for outcome in OUTCOMES
        },
        "bh_q_le_0_10_count": sum(
            row["q_value_bh"] is not None and row["q_value_bh"] <= 0.10
            for row in result_rows
        ),
        "primary_feature_assessment": feature_assessment,
        "family_assessment": family_assessment,
        "supported_families": supported,
        "rejected_families": rejected,
        "strongest_primary_winner_ge20": strongest_rows(
            result_rows, "winner_ge20", primary_only=True
        ),
        "strongest_primary_mfe": strongest_rows(
            result_rows, "mfe", primary_only=True
        ),
        "strongest_all_winner_ge20": strongest_rows(
            result_rows, "winner_ge20", primary_only=False
        ),
        "strongest_all_mfe": strongest_rows(
            result_rows, "mfe", primary_only=False
        ),
        "top5_exclusion_trade_ids": joined.sort_values(
            ["realized_pnl", "trade_id"], ascending=[False, True]
        ).head(5).trade_id.tolist(),
        "phase_verdict": phase_verdict,
        "forbidden_actions_performed": [],
        "output_hashes": {
            "univariate_feature_results_csv": sha256_file(OUTPUT_RESULTS),
            "univariate_quintiles_csv": sha256_file(OUTPUT_QUINTILES),
        },
    }
    atomic_write(OUTPUT_JSON, json.dumps(clean_json(payload), indent=2, sort_keys=True) + "\n")
    atomic_write(REPORT, render_report(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
