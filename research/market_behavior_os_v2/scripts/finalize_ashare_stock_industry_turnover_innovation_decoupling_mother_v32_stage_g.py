#!/usr/bin/env python3
"""Evaluate the frozen V32 Phase-1 categorical single-label gate.

This program consumes only Stage-F categorical counts.  It has no loader for
the anonymous event ledger, numeric returns, security identities, or dates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

EXPERIMENT = "ASHARE-STOCK-INDUSTRY-TURNOVER-INNOVATION-DECOUPLING-MOTHER-V32"
STAGE = "STAGE_G_SINGLE_PHASE1_LABEL_CATEGORICAL_GATE"
REPO = Path(__file__).resolve().parents[3]
EXP = REPO / "research/market_behavior_os_v2/experiments"
FREEZE = EXP / (
    "ASHARE-STOCK-INDUSTRY-TURNOVER-INNOVATION-DECOUPLING-MOTHER-V32_"
    "stage_g_single_rule_gate_freeze.json"
)
DEFAULT_AUTHORIZATION = EXP / (
    "ASHARE-STOCK-INDUSTRY-TURNOVER-INNOVATION-DECOUPLING-MOTHER-V32_"
    "stage_g_input_authorization.json"
)

EXPECTED_FREEZE_SHA256 = (
    "fa266b4b61485a251e2b54230cb1675725333260e9ce31228381878d1ba885a8"
)
EXPECTED_REVIEWERS = ("Bacon", "Codex-root", "Galileo", "Singer")
ALL_LABELS = (
    "BASE_COMPRESSION",
    "ORDERLY_PRICE_DISCOVERY",
    "HIGH_TURNOVER_LOW_PRICE_DISPLACEMENT",
    "MATURE_EXTENSION_OR_TERMINAL_SPIKE",
    "DOWNTREND_OR_BREAKDOWN",
    "NONE_CLEAR",
)
ELIGIBLE_LABELS = (
    "ORDERLY_PRICE_DISCOVERY",
    "MATURE_EXTENSION_OR_TERMINAL_SPIKE",
    "DOWNTREND_OR_BREAKDOWN",
)
EXPECTED_USAGE = {
    "BASE_COMPRESSION": "POOLED_UNUSABLE",
    "ORDERLY_PRICE_DISCOVERY": "ELIGIBLE_WITH_REVIEWER_GUARDS",
    "HIGH_TURNOVER_LOW_PRICE_DISPLACEMENT": "POOLED_UNUSABLE",
    "MATURE_EXTENSION_OR_TERMINAL_SPIKE": "ELIGIBLE_WITH_REVIEWER_GUARDS",
    "DOWNTREND_OR_BREAKDOWN": "ELIGIBLE_WITH_REVIEWER_GUARDS",
    "NONE_CLEAR": "DESCRIPTIVE_ONLY",
}
EXPECTED_SUMMARY_ASSERTIONS = {
    "anonymous_coverage_exactly_once": True,
    "numeric_return_field_read_or_aggregated": False,
    "phase1_labels_modified": False,
    "portfolio_replay_performed": False,
    "post_signal_used_as_predictor": False,
    "reviewer_stratified_only": True,
    "rule_promotion_or_search_performed": False,
    "security_identity_read_or_published": False,
}
EXPECTED_MANIFEST_GOVERNANCE = {
    "anonymous_identity_coverage_exactly_once": True,
    "numeric_return_field_read_or_aggregated": False,
    "outcome_group_coverage_exactly_once": True,
    "phase1_labels_modified": False,
    "portfolio_replay_performed": False,
    "post_2020_row_read": False,
    "post_signal_used_as_predictor": False,
    "rule_aggregation_performed": False,
    "rule_promotion_or_search_performed": False,
    "security_identity_read_or_published": False,
}
INPUT_FIELDS = (
    "label",
    "phase1_reviewer",
    "pre_outcome_usage_decision",
    "true_n",
    "false_n",
    "minimum_support_per_side",
    "eligible_each_side_ge_25",
    "profit_ge4_true_n",
    "profit_ge4_false_n",
    "profit_ge4_true_rate",
    "profit_ge4_false_rate",
    "profit_ge4_delta_true_minus_false",
    "severe_loss_true_n",
    "severe_loss_false_n",
    "severe_loss_true_rate",
    "severe_loss_false_rate",
    "severe_loss_delta_true_minus_false",
)
OUTPUT_FIELDS = (
    "label",
    "phase1_reviewer_or_pooled",
    "completed_true_n",
    "completed_false_n",
    "support_pass",
    "profit_ge4_true_rate",
    "profit_ge4_false_rate",
    "profit_direction_pass",
    "severe_loss_true_rate",
    "severe_loss_false_rate",
    "severe_direction_pass",
    "block_pass",
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class GateError(RuntimeError):
    """Fail closed on identity, schema, count, or publication drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise GateError(f"{label} is not one lowercase SHA-256 digest")
    return value


def verify_hash(path: Path, expected: str, label: str) -> str:
    if not path.is_file():
        raise GateError(f"missing {label}: {path}")
    actual = sha256(path)
    if actual != require_hash(expected, f"expected {label} hash"):
        raise GateError(f"{label} hash drift: {actual} != {expected}")
    return actual


def strict_json(path: Path, label: str) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        duplicates = sorted(key for key, n in Counter(keys).items() if n > 1)
        if duplicates:
            raise GateError(f"duplicate JSON keys in {label}: {duplicates}")
        return dict(pairs)

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateError(f"{label} must be a JSON object")
    return value


def parse_nonnegative_integer(value: str, label: str) -> int:
    if re.fullmatch(r"0|[1-9][0-9]*", value or "") is None:
        raise GateError(f"{label} is not a canonical nonnegative integer: {value!r}")
    return int(value)


def parse_boolean(value: str, label: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise GateError(f"{label} must be exactly true or false")


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        raise GateError("zero categorical-rate denominator")
    return numerator / denominator


def direction_pass(label: str, endpoint: str, true_rate: float, false_rate: float) -> bool:
    if label == "ORDERLY_PRICE_DISCOVERY":
        return true_rate > false_rate if endpoint == "profit" else true_rate < false_rate
    if label in {"MATURE_EXTENSION_OR_TERMINAL_SPIKE", "DOWNTREND_OR_BREAKDOWN"}:
        return true_rate < false_rate if endpoint == "profit" else true_rate > false_rate
    raise GateError(f"no frozen direction for {label}")


def load_and_validate_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != INPUT_FIELDS:
            raise GateError(f"diagnostic schema drift: {reader.fieldnames}")
        raw_rows = list(reader)
    if len(raw_rows) != 24:
        raise GateError(f"expected 24 diagnostics, found {len(raw_rows)}")

    parsed: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    completed_by_reviewer: dict[str, int] = {}
    for row_number, row in enumerate(raw_rows, start=2):
        label = row["label"]
        reviewer = row["phase1_reviewer"]
        if label not in ALL_LABELS or reviewer not in EXPECTED_REVIEWERS:
            raise GateError(f"unexpected diagnostic identity on row {row_number}")
        key = (label, reviewer)
        if key in seen:
            raise GateError(f"duplicate diagnostic identity {key}")
        seen.add(key)
        if row["pre_outcome_usage_decision"] != EXPECTED_USAGE[label]:
            raise GateError(f"usage-decision drift for {key}")

        true_n = parse_nonnegative_integer(row["true_n"], f"{key} true_n")
        false_n = parse_nonnegative_integer(row["false_n"], f"{key} false_n")
        support_min = parse_nonnegative_integer(
            row["minimum_support_per_side"], f"{key} minimum support"
        )
        if support_min != 25:
            raise GateError(f"minimum-support drift for {key}: {support_min}")
        support = true_n >= support_min and false_n >= support_min
        if parse_boolean(row["eligible_each_side_ge_25"], f"{key} eligibility") != support:
            raise GateError(f"serialized support inconsistency for {key}")
        completed = true_n + false_n
        if reviewer in completed_by_reviewer and completed_by_reviewer[reviewer] != completed:
            raise GateError(f"completed-event denominator drift within {reviewer}")
        completed_by_reviewer[reviewer] = completed

        counts: dict[str, int] = {}
        for field, denominator in (
            ("profit_ge4_true_n", true_n),
            ("profit_ge4_false_n", false_n),
            ("severe_loss_true_n", true_n),
            ("severe_loss_false_n", false_n),
        ):
            counts[field] = parse_nonnegative_integer(row[field], f"{key} {field}")
            if counts[field] > denominator:
                raise GateError(f"{field} exceeds its denominator for {key}")
        parsed.append(
            {
                "label": label,
                "reviewer": reviewer,
                "true_n": true_n,
                "false_n": false_n,
                "support": support,
                **counts,
            }
        )

    expected = {(label, reviewer) for label in ALL_LABELS for reviewer in EXPECTED_REVIEWERS}
    if seen != expected:
        raise GateError("diagnostic label/reviewer Cartesian product is incomplete")
    return parsed


def evaluate(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    table: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {}
    for label in ELIGIBLE_LABELS:
        label_rows = {row["reviewer"]: row for row in rows if row["label"] == label}
        pass_count = 0
        for reviewer in EXPECTED_REVIEWERS:
            row = label_rows[reviewer]
            profit_true = rate(row["profit_ge4_true_n"], row["true_n"])
            profit_false = rate(row["profit_ge4_false_n"], row["false_n"])
            severe_true = rate(row["severe_loss_true_n"], row["true_n"])
            severe_false = rate(row["severe_loss_false_n"], row["false_n"])
            profit_pass = direction_pass(label, "profit", profit_true, profit_false)
            severe_pass = direction_pass(label, "severe", severe_true, severe_false)
            block_pass = row["support"] and profit_pass and severe_pass
            pass_count += int(block_pass)
            table.append(
                {
                    "label": label,
                    "phase1_reviewer_or_pooled": reviewer,
                    "completed_true_n": row["true_n"],
                    "completed_false_n": row["false_n"],
                    "support_pass": row["support"],
                    "profit_ge4_true_rate": profit_true,
                    "profit_ge4_false_rate": profit_false,
                    "profit_direction_pass": profit_pass,
                    "severe_loss_true_rate": severe_true,
                    "severe_loss_false_rate": severe_false,
                    "severe_direction_pass": severe_pass,
                    "block_pass": block_pass,
                }
            )

        pooled: dict[str, int] = {
            field: sum(label_rows[reviewer][field] for reviewer in EXPECTED_REVIEWERS)
            for field in (
                "true_n",
                "false_n",
                "profit_ge4_true_n",
                "profit_ge4_false_n",
                "severe_loss_true_n",
                "severe_loss_false_n",
            )
        }
        profit_true = rate(pooled["profit_ge4_true_n"], pooled["true_n"])
        profit_false = rate(pooled["profit_ge4_false_n"], pooled["false_n"])
        severe_true = rate(pooled["severe_loss_true_n"], pooled["true_n"])
        severe_false = rate(pooled["severe_loss_false_n"], pooled["false_n"])
        profit_pass = direction_pass(label, "profit", profit_true, profit_false)
        severe_pass = direction_pass(label, "severe", severe_true, severe_false)
        pooled_support = pooled["true_n"] >= 25 and pooled["false_n"] >= 25
        pooled_pass = pooled_support and profit_pass and severe_pass
        table.append(
            {
                "label": label,
                "phase1_reviewer_or_pooled": "POOLED",
                "completed_true_n": pooled["true_n"],
                "completed_false_n": pooled["false_n"],
                "support_pass": pooled_support,
                "profit_ge4_true_rate": profit_true,
                "profit_ge4_false_rate": profit_false,
                "profit_direction_pass": profit_pass,
                "severe_loss_true_rate": severe_true,
                "severe_loss_false_rate": severe_false,
                "severe_direction_pass": severe_pass,
                "block_pass": pooled_pass,
            }
        )
        summaries[label] = {
            "reviewer_blocks_passing": pass_count,
            "reviewer_blocks_required": 3,
            "pooled_pass": pooled_pass,
            "label_gate_pass": pass_count >= 3 and pooled_pass,
        }
    return table, summaries


def validate_inputs(authorization_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path, Path]:
    verify_hash(FREEZE, EXPECTED_FREEZE_SHA256, "Stage-G freeze")
    authorization = strict_json(authorization_path, "Stage-G authorization")
    if authorization.get("experiment") != EXPERIMENT:
        raise GateError("authorization experiment mismatch")
    if authorization.get("stage") != "STAGE_G_INPUT_AUTHORIZATION":
        raise GateError("authorization stage mismatch")
    if authorization.get("stage_g_freeze_sha256") != EXPECTED_FREEZE_SHA256:
        raise GateError("authorization Stage-G freeze binding mismatch")
    if authorization.get("runner_sha256") != sha256(Path(__file__)):
        raise GateError("authorization runner binding mismatch")

    stage_f_root = Path(authorization["stage_f_root"])
    output_root = Path(authorization["stage_g_output_root"])
    manifest_path = stage_f_root / "manifest.json"
    summary_path = stage_f_root / "summary.json"
    diagnostic_path = stage_f_root / "phase1_label_x_outcome_by_reviewer_block.csv"
    verify_hash(manifest_path, authorization["stage_f_manifest_sha256"], "Stage-F manifest")
    verify_hash(summary_path, authorization["stage_f_summary_sha256"], "Stage-F summary")
    verify_hash(
        diagnostic_path,
        authorization["stage_f_diagnostic_sha256"],
        "Stage-F categorical diagnostic",
    )

    manifest = strict_json(manifest_path, "Stage-F manifest")
    summary = strict_json(summary_path, "Stage-F summary")
    if manifest.get("experiment") != EXPERIMENT or summary.get("experiment") != EXPERIMENT:
        raise GateError("Stage-F experiment mismatch")
    if manifest.get("stage") != "STAGE_F_PHASE2_ANONYMOUS_REVIEW_FROZEN":
        raise GateError("Stage-F manifest stage mismatch")
    if summary.get("stage") != "STAGE_F_PHASE2_ANONYMOUS_REVIEW_FROZEN":
        raise GateError("Stage-F summary stage mismatch")
    outputs = manifest.get("outputs", {})
    if outputs.get("summary.json") != authorization["stage_f_summary_sha256"]:
        raise GateError("Stage-F manifest does not bind the authorized summary")
    if outputs.get("phase1_label_x_outcome_by_reviewer_block.csv") != authorization[
        "stage_f_diagnostic_sha256"
    ]:
        raise GateError("Stage-F manifest does not bind the authorized diagnostic")
    for key, expected in EXPECTED_SUMMARY_ASSERTIONS.items():
        if summary.get(key) is not expected:
            raise GateError(f"Stage-F summary assertion failed: {key}")
    if summary.get("diagnostic_rows") != 24 or summary.get("diagnostic_eligible_rows") != 18:
        raise GateError("Stage-F diagnostic row-count assertion failed")
    if summary.get("minimum_support_per_true_false_side") != 25:
        raise GateError("Stage-F support threshold drift")
    governance = manifest.get("governance", {})
    for key, expected in EXPECTED_MANIFEST_GOVERNANCE.items():
        if governance.get(key) is not expected:
            raise GateError(f"Stage-F manifest governance assertion failed: {key}")
    return authorization, manifest, summary, diagnostic_path, output_root


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            serialized = dict(row)
            for key, value in serialized.items():
                if isinstance(value, bool):
                    serialized[key] = str(value).lower()
                elif isinstance(value, float):
                    serialized[key] = f"{value:.12f}"
            writer.writerow(serialized)


def publish(
    output: Path,
    authorization_path: Path,
    authorization: dict[str, Any],
    rows: list[dict[str, Any]],
    summaries: dict[str, Any],
) -> dict[str, Any]:
    if output.exists():
        raise GateError(f"refusing to overwrite Stage-G output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        table_path = temp / "stage_g_single_label_gate_by_reviewer.csv"
        write_csv(table_path, rows)
        summary = {
            "experiment": EXPERIMENT,
            "stage": STAGE,
            "scientific_status": "DEVELOPMENT_CATEGORICAL_GATE_ONLY_NOT_ALPHA_CONFIRMATION",
            "labels": summaries,
            "labels_passing": [
                label for label in ELIGIBLE_LABELS if summaries[label]["label_gate_pass"]
            ],
            "automatic_rule_promotion_performed": False,
            "numeric_return_read_or_aggregated": False,
            "post_path_used_as_predictor": False,
            "portfolio_replay_performed": False,
            "post_2020_row_read": False,
        }
        summary_path = temp / "summary.json"
        summary_path.write_bytes(json_bytes(summary))
        manifest = {
            "experiment": EXPERIMENT,
            "stage": STAGE,
            "authorization": {
                "path": str(authorization_path),
                "sha256": sha256(authorization_path),
            },
            "inputs": {
                "stage_g_freeze_sha256": EXPECTED_FREEZE_SHA256,
                "stage_f_manifest_sha256": authorization["stage_f_manifest_sha256"],
                "stage_f_summary_sha256": authorization["stage_f_summary_sha256"],
                "stage_f_diagnostic_sha256": authorization["stage_f_diagnostic_sha256"],
            },
            "outputs": {
                table_path.name: sha256(table_path),
                summary_path.name: sha256(summary_path),
            },
            "governance": {
                "atomic_no_overwrite_publication": True,
                "categorical_counts_only": True,
                "numeric_return_read_or_aggregated": False,
                "post_path_used_as_predictor": False,
                "automatic_rule_promotion_performed": False,
                "portfolio_replay_performed": False,
                "post_2020_row_read": False,
            },
        }
        manifest_path = temp / "manifest.json"
        manifest_path.write_bytes(json_bytes(manifest))
        os.replace(temp, output)
        return {**summary, "manifest_sha256": sha256(output / "manifest.json")}
    except Exception:
        if temp.exists():
            for child in temp.iterdir():
                child.unlink()
            temp.rmdir()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, default=DEFAULT_AUTHORIZATION)
    args = parser.parse_args()
    authorization, _, _, diagnostic_path, output = validate_inputs(args.authorization)
    rows = load_and_validate_rows(diagnostic_path)
    table, summaries = evaluate(rows)
    # Re-verify all authorized inputs immediately before publication.
    validate_inputs(args.authorization)
    result = publish(output, args.authorization, authorization, table, summaries)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
