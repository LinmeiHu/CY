#!/usr/bin/env python3
"""Build the outcome-blind V35 board-lot-affordability mother population."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import tempfile
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-BOARD-LOT-AFFORDABILITY-CLIENTELE-MOTHER-V35"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
REGISTRY = REPO / "configs/data_asset_registry.json"
MANIFEST = (
    REPO
    / "research/market_behavior_os_v2/experiments/"
    "ASHARE-V35-CY051_DATA_ASSET_MANIFEST.json"
)
REGISTRY_SUGGESTION = (
    REPO
    / "research/market_behavior_os_v2/experiments/"
    "ASHARE-V35-CY051_REGISTRY_SUGGESTION.json"
)
ACTION_ID_CONTRACT = REPO / "src/cyq_game/chip/price_coordinate.py"
STYLE_SPEC = REPO / "research/market_behavior_os_v2/experiments/MKT-STYLE-DATA-001_spec.json"
STYLE_RESULT = REPO / "research/market_behavior_os_v2/artifacts/MKT-STYLE-DATA-001_result.json"

CY006_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
CY006_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
YEARS = (2018, 2019, 2020)
PARTITIONS = tuple(
    CY006_ROOT / f"partition_year={year}/data_0.parquet" for year in YEARS
)
QD010_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/staging/"
    "crsp_lean_corporate_actions_enrichment_20260809_v2/vintages/"
    "official_full_sh_sz_current_snapshot_20260809_v5"
)
QD010_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/QD-010-cninfo-actions-20260820.json"
)
QD010_MANIFEST = QD010_ROOT / "manifest.json"
QD012_INVENTORY = Path("/Users/linmei/Documents/CY/data/input_inventories/QD-002-20260820.json")

OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_board_lot_affordability_clientele_mother_v35"
)
STAGE_A = OUTPUT_ROOT / "stage_a"

ASSET_ID = "CY-051"
AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-BOARD-LOT-AFFORDABILITY-V35-STAGE-A-2018-2020-V1"
AUTHORIZATION_PURPOSE = "ASHARE_OUTCOME_BLIND_MOTHER_REPRESENTATION"
AUTHORIZED_ARM = "V35_FROZEN_OUTCOME_BLIND_STAGE_A_ONLY"
MANIFEST_STATUS = "FROZEN_OUTCOME_BLIND_BOUNDED_INPUT"

EXPECTED_SPEC_SHA256 = "31d2da975d9d1d6c57b91dfd5eac26b2cb0fc0001cb4055c5c1c629dded9ffe0"
EXPECTED_FILES = {
    ACTION_ID_CONTRACT: "60c9f80fcaa2bf4a6ebfaab37bc56e81dd716cc3bea00891b4fc28d077dd1726",
    STYLE_SPEC: "506c24bcdd498162b3d44faa3008aa54ddf9a4132606b5da9a890240e224484b",
    STYLE_RESULT: "a03954d6315f29c7c5a119b91729fbfeef84feb51c7c12ed2330b7822a19f019",
    CY006_INVENTORY: "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    PARTITIONS[0]: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    PARTITIONS[1]: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    PARTITIONS[2]: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    QD010_INVENTORY: "e1ca622ee227ce308b44933160754d450b80d3ecca79c1470037558e1011ceb8",
    QD010_MANIFEST: "d57afb7826aa87c3929367a989a369f087a7ecf05f1026bcfed751600a3e884c",
    QD012_INVENTORY: "36fe6f09c04ede7423f9dd7ec593eb558e9aee2384205660f8b0fa0cc4f85982",
}
INPUT_ROLES = {
    "corporate_action_id_contract": ACTION_ID_CONTRACT,
    "circulating_size_spec": STYLE_SPEC,
    "circulating_size_result": STYLE_RESULT,
    "cy006_inventory": CY006_INVENTORY,
    "cy006_2018": PARTITIONS[0],
    "cy006_2019": PARTITIONS[1],
    "cy006_2020": PARTITIONS[2],
    "qd010_inventory": QD010_INVENTORY,
    "qd010_source_manifest": QD010_MANIFEST,
    "qd012_inventory": QD012_INVENTORY,
}

SIGNAL_START = pd.Timestamp("2018-01-01")
SIGNAL_END = pd.Timestamp("2020-12-31")
BOARD_LOT_SHARES = 100
MIN_INDUSTRY_COUNT = 12
COOLDOWN_SESSIONS = 60
MIN_ANNUAL_CANDIDATES_EXCLUSIVE = 50
MIN_ANNUAL_INDUSTRIES = 20
MIN_ANNUAL_MONTHS = 10
MIN_ANNUAL_SYMBOLS_EXCLUSIVE = 50
MAX_DIAGNOSTIC_STEPS = 20
BOARD_PATTERN = re.compile(
    r"^(600|601|603|605)[0-9]{3}[.]SH$|^(000|001|002|300|301)[0-9]{3}[.]SZ$"
)

REQUIRED_VALIDITY_FIELDS = (
    "hard_valid",
    "bar_valid",
    "trading_state_valid",
    "industry_valid",
    "float_valid",
    "corporate_action_valid",
    "market_valid",
    "market_rule_valid",
    "historical_identity_valid",
    "current_day_data_tradable",
)
REQUIRED_SNAPSHOT_FIELDS = (
    "snapshot_id",
    "daily_snapshot_id",
    "trading_state_snapshot_id",
    "industry_snapshot_id",
    "float_snapshot_id",
    "corporate_action_snapshot_id",
    "market_snapshot_id",
)


class ResearchError(RuntimeError):
    """Fail closed on a frozen identity, PIT, representation, or publication drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def strict_json(path: Path, label: str) -> dict[str, Any]:
    def no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
        if duplicates:
            raise ResearchError(f"duplicate JSON keys in {label}: {duplicates}")
        return dict(pairs)

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys)
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResearchError(f"{label} must be one JSON object")
    return value


def _one_asset(registry: dict[str, Any], asset_id: str) -> dict[str, Any]:
    matches = [item for item in registry.get("assets", []) if item.get("asset_id") == asset_id]
    if len(matches) != 1:
        raise ResearchError(f"missing or duplicate registry asset: {asset_id}")
    return matches[0]


def _one_authorization(registry: dict[str, Any], authorization_id: str) -> dict[str, Any]:
    matches = [
        item
        for item in registry.get("bounded_authorizations", [])
        if item.get("authorization_id") == authorization_id
    ]
    if len(matches) != 1:
        raise ResearchError(f"missing or duplicate bounded authorization: {authorization_id}")
    return matches[0]


def expected_input_bindings() -> dict[str, dict[str, str]]:
    return {
        role: {"path": str(path), "sha256": EXPECTED_FILES[path]}
        for role, path in INPUT_ROLES.items()
    }


def expected_stage_a_binding(runner_hash: str) -> dict[str, Any]:
    return {
        "spec": {"path": str(SPEC), "sha256": EXPECTED_SPEC_SHA256},
        "runner": {"path": str(Path(__file__).resolve()), "sha256": runner_hash},
        "inputs": expected_input_bindings(),
    }


def expected_registry_asset(manifest_hash: str, binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": ASSET_ID,
        "name": "Bounded V35 outcome-blind board-lot affordability input",
        "kind": "bounded_daily_pit_b_board_lot_representation_input",
        "status": "RESEARCH_CONDITIONAL",
        "pit_grade": "B",
        "physical_state": "MATERIALIZED",
        "location": str(MANIFEST),
        "source": (
            "Exact registered CY-006 2018-2020 daily rows with causal PIT industry, "
            "circulating market value, amount, raw completed close, QD-010 action "
            "identity semantics and QD-012 100-share board-lot rules"
        ),
        "coverage": {
            "authorized_start": "2018-01-01",
            "authorized_end": "2020-12-31",
            "signal_start": "2018-01-01",
            "signal_end": "2020-12-31",
            "maximum_source_row_date": "2020-12-31",
        },
        "lineage": {
            "bounded_authorization_id": AUTHORIZATION_ID,
            "component_assets": ["CY-006", "QD-010", "QD-012"],
            "immutable_manifest": True,
            "manifest_path": str(MANIFEST),
            "manifest_sha256": manifest_hash,
            "pipeline_version": "v35-board-lot-affordability-outcome-blind-stage-a-v1",
            "record_available_at": True,
            "record_snapshot_id": True,
        },
        "quality_evidence": {
            "outcome_blind_contract_frozen": True,
            "outcome_columns_read": False,
            "post_signal_rows_read": False,
            "post_2020_rows_read": False,
            "central_registration_required_before_source_access": True,
        },
        "allowed_uses": [
            "one frozen V35 outcome-blind 2018-2020 Stage-A representation, "
            "opportunity and redundancy audit"
        ],
        "blocked_uses": [
            "outcome, post-signal row, chart, Stage B, portfolio, parameter search, "
            "2021-plus row, live use or strict PIT-A claim"
        ],
        "schema_and_units": (
            "100-share cash ticket from raw completed close; causal PIT industry, "
            "circulating market value in CNY, amount in CNY and strict CY-006 "
            "optional-zero rights semantics"
        ),
        "activation_gates": [
            "central CY-051 asset and bounded authorization exactly match the "
            "frozen repository-side suggestion",
            "public spec, runner, manifest and all ten declared input identities "
            "remain hash-identical before source access",
            "only causal 2018-2020 signal-time rows may enter the outcome-blind "
            "representation and count diagnostics",
            "Stage A publishes atomically into a previously absent output root and "
            "never opens outcome or post-signal data",
        ],
        "stage_a_binding": binding,
    }


def expected_registry_authorization(
    manifest_hash: str, binding: dict[str, Any]
) -> dict[str, Any]:
    artifacts = [
        {"role": role, **item} for role, item in expected_input_bindings().items()
    ]
    return {
        "authorization_id": AUTHORIZATION_ID,
        "asset_id": ASSET_ID,
        "purpose": AUTHORIZATION_PURPOSE,
        "authorized_arms": [AUTHORIZED_ARM],
        "dependency_asset_id": "CY-006",
        "dependency_asset_ids": ["CY-006", "QD-010", "QD-012"],
        "dependency_status": "RESEARCH_CONDITIONAL",
        "scope": {
            "project": "research/market_behavior_os_v2",
            "start": "2018-01-01",
            "end": "2020-12-31",
            "signal_start": "2018-01-01",
            "signal_end": "2020-12-31",
            "maximum_source_row_date": "2020-12-31",
        },
        "bound_manifest": {"path": str(MANIFEST), "sha256": manifest_hash},
        "bound_protocol": {
            "path": str(SPEC),
            "sha256": EXPECTED_SPEC_SHA256,
            "runner_path": str(Path(__file__).resolve()),
            "runner_sha256": binding["runner"]["sha256"],
        },
        "bound_strategy": {"path": str(SPEC), "sha256": EXPECTED_SPEC_SHA256},
        "stage_a_binding": binding,
        "bound_artifacts": artifacts,
        "stage_a_authorized": True,
        "whole_artifact_hash_authorized": True,
        "inventory_metadata_parse_authorized": True,
        "source_parquet_stage_a_parse_authorized": True,
        "stage_b_authorized": False,
        "outcome_attachment_authorized": False,
        "outcome_artifact_parse_authorized": False,
        "outcome_columns_read_authorized": False,
        "post_signal_row_read_authorized": False,
        "charts_authorized": False,
        "portfolio_replay_authorized": False,
        "parameter_search_authorized": False,
        "post_2020_read_authorized": False,
        "2021_read_authorized": False,
        "2022_plus_read_authorized": False,
        "current_survivor_fallback_allowed": False,
        "record_level_available_at_available": False,
        "allowed_uses": [
            "parse only exact 2018-2020 causal CY-006 rows for the frozen V35 "
            "outcome-blind Stage-A gate"
        ],
        "blocked_uses": [
            "outcome, post-signal row, chart, Stage B, portfolio, parameter search, "
            "2021-plus row, live use or strict PIT-A claim"
        ],
        "known_limitations": [
            "CY-006 and QD-010 remain PIT-B research inputs without complete "
            "historical supplier revision vintages",
            "Stage A measures only opportunity breadth and proxy redundancy; it "
            "cannot establish return Alpha or authorize Stage B",
        ],
    }


def require_bound_artifacts(items: object) -> None:
    if not isinstance(items, list):
        raise ResearchError("bound_artifacts must be a list")
    observed: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            raise ResearchError("malformed bound_artifacts row")
        role = item["role"]
        if role in observed:
            raise ResearchError(f"duplicate bound artifact role: {role}")
        observed[role] = {"path": item.get("path"), "sha256": item.get("sha256")}
    if observed != expected_input_bindings():
        raise ResearchError("bound_artifacts drift")


def verify_public_contract() -> dict[str, str]:
    """Verify only repository-public code/spec; never stat or hash a source dataset."""

    runner = Path(__file__).resolve()
    public = (SPEC, runner, MANIFEST, REGISTRY_SUGGESTION)
    if any(not path.is_file() for path in public):
        raise ResearchError("missing V35 public contract, runner, manifest or suggestion")
    spec_hash = sha256(SPEC)
    if spec_hash != EXPECTED_SPEC_SHA256:
        raise ResearchError(f"V35 spec hash drift: {spec_hash} != {EXPECTED_SPEC_SHA256}")
    spec = strict_json(SPEC, "V35 frozen spec")
    runner_hash = sha256(runner)
    manifest_hash = sha256(MANIFEST)
    binding = expected_stage_a_binding(runner_hash)
    manifest = strict_json(MANIFEST, "CY-051 manifest")
    suggestion = strict_json(REGISTRY_SUGGESTION, "CY-051 registry suggestion")
    gate = spec.get("stage_a_opportunity_gate", {})
    correction = spec.get("pre_run_static_correction", {})
    if (
        spec.get("experiment") != EXPERIMENT
        or spec.get("governance", {}).get("outcome_columns_read") is not False
        or spec.get("governance", {}).get("post_signal_rows_read") is not False
        or spec.get("governance", {}).get("post_2020_row_read") is not False
        or gate.get("retained_candidates_each_year_strictly_greater_than")
        != MIN_ANNUAL_CANDIDATES_EXCLUSIVE
        or gate.get("pit_industries_each_year_at_least") != MIN_ANNUAL_INDUSTRIES
        or gate.get("decision_months_each_year_at_least") != MIN_ANNUAL_MONTHS
        or gate.get("unique_symbols_each_year_strictly_greater_than")
        != MIN_ANNUAL_SYMBOLS_EXCLUSIVE
        or spec.get("governance", {}).get(
            "cy051_central_registry_authorization_required_before_source_access"
        )
        is not True
        or correction.get("prior_draft_executed") is not False
        or correction.get("prior_draft_registered") is not False
        or correction.get("outcome_or_post_signal_rows_read") is not False
    ):
        raise ResearchError("V35 frozen public semantics drift")
    boundary = manifest.get("authorization_boundary", {})
    semantic_correction = manifest.get("semantic_correction", {})
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != MANIFEST_STATUS
        or manifest.get("pit_grade") != "B"
        or manifest.get("stage_a_binding") != binding
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("purpose") != AUTHORIZATION_PURPOSE
        or boundary.get("authorized_arm") != AUTHORIZED_ARM
        or boundary.get("stage_a_authorized") is not True
        or boundary.get("stage_b_authorized") is not False
        or boundary.get("outcome_columns_read_authorized") is not False
        or boundary.get("post_signal_row_read_authorized") is not False
        or boundary.get("post_2020_read_authorized") is not False
        or semantic_correction.get("cy006_optional_null_or_finite_zero_only") is not True
        or semantic_correction.get("nonmissing_invalid_or_nonzero_rights_rejected")
        is not True
        or semantic_correction.get("outcome_informed") is not False
    ):
        raise ResearchError("CY-051 public manifest binding drift")
    require_bound_artifacts(manifest.get("bound_artifacts"))
    if (
        suggestion.get("asset") != expected_registry_asset(manifest_hash, binding)
        or suggestion.get("bounded_authorization")
        != expected_registry_authorization(manifest_hash, binding)
        or suggestion.get("central_registry_modified") is not False
    ):
        raise ResearchError("CY-051 registry suggestion binding drift")
    return {
        str(SPEC): spec_hash,
        str(runner): runner_hash,
        str(MANIFEST): manifest_hash,
        str(REGISTRY_SUGGESTION): sha256(REGISTRY_SUGGESTION),
    }


def verify_inputs(public_hashes: dict[str, str]) -> tuple[dict[str, str], dict[str, Any]]:
    """Verify frozen metadata and source bytes only in explicit --run mode."""

    if not REGISTRY.is_file():
        raise ResearchError(f"missing registry: {REGISTRY}")
    actual = dict(public_hashes)
    actual[str(REGISTRY)] = sha256(REGISTRY)
    registry = strict_json(REGISTRY, "data asset registry")
    manifest_hash = public_hashes[str(MANIFEST)]
    runner_hash = public_hashes[str(Path(__file__).resolve())]
    binding = expected_stage_a_binding(runner_hash)
    registered_asset = _one_asset(registry, ASSET_ID)
    registered_authorization = _one_authorization(registry, AUTHORIZATION_ID)
    if registered_asset != expected_registry_asset(manifest_hash, binding):
        raise ResearchError("central CY-051 registry asset does not match frozen suggestion")
    if registered_authorization != expected_registry_authorization(manifest_hash, binding):
        raise ResearchError("central CY-051 authorization does not match frozen suggestion")

    cy006 = _one_asset(registry, "CY-006")
    cy006_lineage = cy006.get("lineage", {})
    if (
        cy006.get("status") != "RESEARCH_CONDITIONAL"
        or cy006.get("pit_grade") != "B"
        or cy006_lineage.get("record_available_at") is not True
        or cy006_lineage.get("record_snapshot_id") is not True
        or cy006_lineage.get("immutable_manifest") is not True
        or cy006_lineage.get("manifest_path") != str(CY006_INVENTORY)
        or cy006_lineage.get("manifest_sha256") != EXPECTED_FILES[CY006_INVENTORY]
        or not {"QD-010", "QD-012"}.issubset(set(cy006_lineage.get("component_assets", [])))
    ):
        raise ResearchError("CY-006 registry semantics drift")

    qd010 = _one_asset(registry, "QD-010")
    qd010_lineage = qd010.get("lineage", {})
    if (
        qd010.get("status") != "RESEARCH_CONDITIONAL"
        or qd010.get("pit_grade") != "B"
        or qd010_lineage.get("immutable_manifest") is not True
        or qd010_lineage.get("manifest_path") != str(QD010_INVENTORY)
        or qd010_lineage.get("manifest_sha256") != EXPECTED_FILES[QD010_INVENTORY]
    ):
        raise ResearchError("QD-010 registry semantics drift")

    qd012 = _one_asset(registry, "QD-012")
    qd012_lineage = qd012.get("lineage", {})
    if (
        qd012.get("status") != "DERIVE_ONLY"
        or qd012.get("pit_grade") != "B"
        or qd012_lineage.get("immutable_manifest") is not True
        or qd012_lineage.get("manifest_path") != str(QD012_INVENTORY)
        or qd012_lineage.get("manifest_sha256") != EXPECTED_FILES[QD012_INVENTORY]
        or "lot_size=100" not in str(qd012.get("schema_and_units", ""))
        or "T+1" not in str(qd012.get("schema_and_units", ""))
    ):
        raise ResearchError("QD-012 board-lot/trading-rule semantics drift")

    # Only an exact central CY-051 registration grants permission to touch source bytes.
    for path, expected_hash in EXPECTED_FILES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        observed = sha256(path)
        actual[str(path)] = observed
        if observed != expected_hash:
            raise ResearchError(f"frozen input drift: {path}: {observed} != {expected_hash}")

    cy006_inventory = strict_json(CY006_INVENTORY, "CY-006 inventory")
    if cy006_inventory.get("root") != str(CY006_ROOT):
        raise ResearchError("CY-006 inventory root drift")
    cy006_entries = {item["path"]: item["sha256"] for item in cy006_inventory.get("files", [])}
    for path in PARTITIONS:
        relative = str(path.relative_to(CY006_ROOT))
        if cy006_entries.get(relative) != EXPECTED_FILES[path]:
            raise ResearchError(f"CY-006 inventory entry drift: {relative}")

    qd010_inventory = strict_json(QD010_INVENTORY, "QD-010 inventory")
    if qd010_inventory.get("root") != str(QD010_ROOT):
        raise ResearchError("QD-010 inventory root drift")
    qd010_entries = {
        item["path"]: item["sha256"] for item in qd010_inventory.get("files", [])
    }
    manifest_relative = str(QD010_MANIFEST.relative_to(QD010_ROOT))
    if qd010_entries.get(manifest_relative) != EXPECTED_FILES[QD010_MANIFEST]:
        raise ResearchError("QD-010 source-manifest inventory binding drift")

    style = strict_json(STYLE_RESULT, "circulating-size data-contract result")
    if (
        style.get("status") != "COMPLETE_DATA_CONTRACT_PASS"
        or style.get("accepted_semantic_label") != "circulating_market_value_cny"
    ):
        raise ResearchError("circulating-size data contract no longer passes")
    return actual, registry


def connect(temporary: Path) -> duckdb.DuckDBPyConnection:
    temporary.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=2")
    connection.execute("SET memory_limit='8GB'")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute(f"SET temp_directory='{temporary.as_posix()}'")
    connection.from_parquet([str(path) for path in PARTITIONS], union_by_name=True).create_view(
        "v35_daily"
    )
    return connection


def parse_action_ids_strict(raw: object) -> tuple[str, ...]:
    """Parse accepted wire forms while refusing canonical-parser loss of multiplicity."""

    if raw is None or raw is pd.NA or (isinstance(raw, float) and math.isnan(raw)):
        return ()
    values: list[object]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return ()
        if text.startswith("["):
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ResearchError("invalid corporate_action_ids JSON") from exc
            if not isinstance(decoded, list):
                raise ResearchError("corporate_action_ids JSON must be a list")
            values = decoded
        else:
            values = text.split("|")
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        raise ResearchError("corporate_action_ids has an unsupported encoded type")
    parsed = [str(value) for value in values]
    if any(not value or value != value.strip() for value in parsed):
        raise ResearchError("corporate_action_ids contains an empty or padded member")
    if len(parsed) != len(set(parsed)):
        raise ResearchError("corporate_action_ids contains duplicate members")
    return tuple(sorted(parsed))


def _finite_positive(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    valid = pd.Series(np.isfinite(numeric) & numeric.gt(0), index=values.index)
    return valid.fillna(False).astype(bool)


def _nonblank(values: pd.Series) -> pd.Series:
    valid = values.notna() & values.astype(str).str.strip().ne("")
    return valid.fillna(False).astype(bool)


def _is_scalar_missing(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        missing = pd.isna(value)
        return isinstance(missing, (bool, np.bool_)) and bool(missing)
    except (TypeError, ValueError):
        return False


def strict_optional_zero_rights(value: object) -> float:
    """Map only a true missing value or finite numeric zero to economic zero."""

    if _is_scalar_missing(value):
        return 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResearchError("rights_ratio is nonmissing and nonnumeric") from exc
    if not math.isfinite(numeric) or numeric != 0.0:
        raise ResearchError("rights_ratio is nonmissing and not finite zero")
    return 0.0


def load_signal_rows(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    source = connection.execute(
        """
        SELECT count(*) AS rows,
          count(*)-count(DISTINCT (trade_date,symbol)) AS duplicate_keys,
          count(*) FILTER (WHERE hard_valid AND available_at>decision_at) AS time_travel_rows,
          count(*) FILTER (
            WHERE trade_date<DATE '2018-01-01' OR trade_date>DATE '2020-12-31'
          ) AS out_of_range_rows,
          min(trade_date) AS first_date,max(trade_date) AS last_date
        FROM v35_daily
        """
    ).fetchone()
    if (
        int(source[1]) != 0
        or int(source[2]) != 0
        or int(source[3]) != 0
        or source[4] is None
        or pd.Timestamp(source[5]) > SIGNAL_END
    ):
        raise ResearchError(f"CY-006 source-level gate failed: {source}")

    raw = connection.execute(
        """
        WITH calendar AS (
          SELECT trade_date,row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
          FROM (
            SELECT DISTINCT trade_date FROM v35_daily
            WHERE trade_date BETWEEN DATE '2018-01-01' AND DATE '2020-12-31'
          )
        ), first_fridays AS (
          SELECT trade_date,cal_idx FROM (
            SELECT trade_date,cal_idx,
              row_number() OVER (
                PARTITION BY year(trade_date),month(trade_date) ORDER BY trade_date
              ) AS friday_number
            FROM calendar WHERE dayofweek(trade_date)=5
          ) WHERE friday_number=1
        )
        SELECT d.trade_date AS signal_date,f.cal_idx AS signal_cal_idx,d.symbol,d.industry,
          d.decision_at,d.available_at,d.close AS raw_close,d.preclose,d.amount,d.volume,
          d.turnover_fraction,d.circulating_shares,d.trade_status,d.is_st,
          d.float_effective_date,d.float_announced_date,d.float_available_date,
          d.corporate_action_count,d.corporate_action_ids,d.corporate_action_blocking,
          d.share_multiplier,d.cash_per_share,d.rights_ratio,
          d.corporate_action_available_date,
          d.hard_valid,d.bar_valid,d.trading_state_valid,d.industry_valid,d.float_valid,
          d.corporate_action_valid,d.market_valid,d.market_rule_valid,
          d.historical_identity_valid,d.current_day_data_tradable,
          d.snapshot_id,d.daily_snapshot_id,d.trading_state_snapshot_id,
          d.industry_snapshot_id,d.float_snapshot_id,d.corporate_action_snapshot_id,
          d.market_snapshot_id
        FROM v35_daily d JOIN first_fridays f USING(trade_date)
        WHERE d.trade_date BETWEEN DATE '2018-01-01' AND DATE '2020-12-31'
        ORDER BY d.trade_date,d.symbol
        """
    ).fetchdf()
    if raw.empty:
        raise ResearchError("no first-Friday CY-006 rows in the frozen range")
    for column in (
        "signal_date",
        "decision_at",
        "available_at",
        "float_effective_date",
        "float_announced_date",
        "float_available_date",
        "corporate_action_available_date",
    ):
        raw[column] = pd.to_datetime(raw[column], errors="coerce")

    board_valid = raw.symbol.astype(str).map(
        lambda value: BOARD_PATTERN.fullmatch(value) is not None
    )
    validity = pd.Series(True, index=raw.index, dtype=bool)
    for column in REQUIRED_VALIDITY_FIELDS:
        known_true = raw[column].notna() & raw[column].eq(True).fillna(False)
        validity &= known_true.astype(bool)
    snapshots = pd.Series(True, index=raw.index, dtype=bool)
    for column in REQUIRED_SNAPSHOT_FIELDS:
        snapshots &= _nonblank(raw[column])
    current_numeric = pd.Series(True, index=raw.index, dtype=bool)
    for column in (
        "raw_close",
        "preclose",
        "amount",
        "volume",
        "turnover_fraction",
        "circulating_shares",
    ):
        current_numeric &= _finite_positive(raw[column])

    action_ids: list[tuple[str, ...]] = []
    action_parse_failed: list[bool] = []
    for encoded in raw.corporate_action_ids:
        try:
            action_ids.append(parse_action_ids_strict(encoded))
            action_parse_failed.append(False)
        except ResearchError:
            action_ids.append(())
            action_parse_failed.append(True)
    action_counts = pd.to_numeric(raw.corporate_action_count, errors="coerce")
    multiplier = pd.to_numeric(raw.share_multiplier, errors="coerce")
    cash = pd.to_numeric(raw.cash_per_share, errors="coerce")
    rights_optional_zero_valid: list[bool] = []
    rights_optional_null: list[bool] = []
    for value in raw.rights_ratio:
        is_null = _is_scalar_missing(value)
        rights_optional_null.append(is_null)
        try:
            strict_optional_zero_rights(value)
            rights_optional_zero_valid.append(True)
        except ResearchError:
            rights_optional_zero_valid.append(False)
    rights_valid = pd.Series(rights_optional_zero_valid, index=raw.index, dtype=bool)
    action_neutral = pd.Series(
        [
            (not failed) and not ids
            for ids, failed in zip(action_ids, action_parse_failed, strict=True)
        ],
        index=raw.index,
        dtype=bool,
    )
    action_neutral &= (
        np.isfinite(action_counts)
        & action_counts.eq(0)
        & raw.corporate_action_blocking.notna()
        & raw.corporate_action_blocking.eq(False).fillna(False)
        & np.isfinite(multiplier)
        & multiplier.eq(1.0)
        & np.isfinite(cash)
        & cash.eq(0.0)
        & rights_valid
    )
    availability = (
        raw.available_at.notna()
        & raw.decision_at.notna()
        & raw.available_at.le(raw.decision_at)
        & raw.decision_at.dt.normalize().eq(raw.signal_date.dt.normalize())
        & raw.float_effective_date.notna()
        & raw.float_announced_date.notna()
        & raw.float_available_date.notna()
        & raw.float_effective_date.le(raw.signal_date)
        & raw.float_announced_date.le(raw.signal_date)
        & raw.float_available_date.le(raw.signal_date)
    )
    industry_valid = _nonblank(raw.industry)
    admitted = (
        board_valid
        & validity
        & snapshots
        & current_numeric
        & action_neutral
        & availability
        & industry_valid
        & raw.trade_status.eq(1)
        & raw.is_st.eq(False)
    ).fillna(False).astype(bool)
    eligible = raw.loc[admitted].copy()
    if eligible.empty:
        raise ResearchError("no V35 rows survive the frozen current-row contract")
    eligible["raw_close"] = pd.to_numeric(eligible.raw_close, errors="raise").astype(float)
    eligible["amount"] = pd.to_numeric(eligible.amount, errors="raise").astype(float)
    eligible["volume"] = pd.to_numeric(eligible.volume, errors="raise").astype(float)
    eligible["turnover_fraction"] = pd.to_numeric(
        eligible.turnover_fraction, errors="raise"
    ).astype(float)
    eligible["circulating_shares"] = pd.to_numeric(
        eligible.circulating_shares, errors="raise"
    ).astype(float)
    eligible["board_lot_ticket_cny"] = BOARD_LOT_SHARES * eligible.raw_close
    eligible["circulating_market_value_cny"] = (
        eligible.raw_close * eligible.circulating_shares
    )
    full_industry_keys = ["signal_date", "industry"]
    eligible["full_industry_size_percentile"] = eligible.groupby(
        full_industry_keys, sort=False
    ).circulating_market_value_cny.rank(method="average", pct=True)
    eligible["full_industry_amount_percentile"] = eligible.groupby(
        full_industry_keys, sort=False
    ).amount.rank(method="average", pct=True)
    eligible["same_date_amount_median_cny"] = eligible.groupby(
        "signal_date", sort=False
    ).amount.transform("median")
    liquid = eligible.loc[eligible.amount.ge(eligible.same_date_amount_median_cny)].copy()
    liquid["industry_n_after_amount_floor"] = liquid.groupby(
        ["signal_date", "industry"], sort=False
    ).symbol.transform("size")
    liquid = liquid.loc[liquid.industry_n_after_amount_floor.ge(MIN_INDUSTRY_COUNT)].copy()

    bucketed: list[pd.DataFrame] = []
    for _, group in liquid.groupby(["signal_date", "industry"], sort=False):
        ordered = group.sort_values(
            ["circulating_market_value_cny", "symbol"], kind="mergesort"
        ).copy()
        n = len(ordered)
        ordered["size_order"] = np.arange(1, n + 1)
        ordered["size_tercile"] = (np.arange(n) * 3 // n) + 1
        bucketed.append(ordered)
    liquid = pd.concat(bucketed, ignore_index=True)
    pool = liquid.loc[liquid.size_tercile.eq(2)].copy()
    pool = pool.sort_values(
        ["signal_date", "industry", "board_lot_ticket_cny", "amount", "symbol"],
        ascending=[True, True, True, False, True],
        kind="mergesort",
    )
    pool["ticket_choice_rank"] = pool.groupby(
        ["signal_date", "industry"], sort=False
    ).cumcount() + 1
    pool["pool_row_id"] = np.arange(1, len(pool) + 1)
    pool = pool.reset_index(drop=True)

    audit = {
        "cy006_rows": int(source[0]),
        "cy006_duplicate_symbol_date_keys": int(source[1]),
        "cy006_hard_valid_time_travel_rows": int(source[2]),
        "cy006_out_of_range_partition_rows": int(source[3]),
        "cy006_first_date": str(pd.Timestamp(source[4]).date()),
        "cy006_last_date": str(pd.Timestamp(source[5]).date()),
        "first_friday_rows": len(raw),
        "current_contract_rows": len(eligible),
        "amount_floor_rows": len(liquid),
        "rankable_middle_tercile_rows": len(pool),
        "current_action_parse_fail_rows": int(sum(action_parse_failed)),
        "current_action_non_neutral_rows": int((~action_neutral).sum()),
        "current_rights_optional_null_rows": int(sum(rights_optional_null)),
        "current_rights_explicit_zero_rows": int(
            sum(valid and not missing for valid, missing in zip(
                rights_optional_zero_valid, rights_optional_null, strict=True
            ))
        ),
        "current_rights_invalid_nonmissing_rows": int(
            sum(not valid for valid in rights_optional_zero_valid)
        ),
        "post_2020_signal_rows": int((raw.signal_date > SIGNAL_END).sum()),
        "post_signal_rows_read": False,
    }
    return pool, audit


def _history_row_valid(row: Any) -> bool:
    for name in REQUIRED_VALIDITY_FIELDS:
        value = getattr(row, name)
        if pd.isna(value) or not bool(value):
            return False
    if pd.isna(row.corporate_action_blocking) or bool(row.corporate_action_blocking):
        return False
    if pd.isna(row.available_at) or pd.isna(row.decision_at) or row.available_at > row.decision_at:
        return False
    if pd.Timestamp(row.decision_at).normalize() != pd.Timestamp(row.trade_date).normalize():
        return False
    if not np.isfinite(float(row.raw_close)) or float(row.raw_close) <= 0:
        return False
    return all(
        pd.notna(getattr(row, name)) and str(getattr(row, name)).strip()
        for name in REQUIRED_SNAPSHOT_FIELDS
    )


def _action_step_return(previous_close: float, row: Any) -> float | None:
    try:
        action_ids = parse_action_ids_strict(row.corporate_action_ids)
    except ResearchError:
        return None
    count_value = pd.to_numeric(pd.Series([row.corporate_action_count]), errors="coerce").iloc[0]
    if not np.isfinite(count_value) or float(count_value) < 0 or float(count_value) % 1 != 0:
        return None
    count = int(count_value)
    if len(action_ids) != count:
        return None
    multiplier = float(row.share_multiplier) if pd.notna(row.share_multiplier) else math.nan
    cash = float(row.cash_per_share) if pd.notna(row.cash_per_share) else math.nan
    try:
        rights = strict_optional_zero_rights(row.rights_ratio)
    except ResearchError:
        return None
    if not all(np.isfinite(value) for value in (multiplier, cash)):
        return None
    if count == 0:
        if action_ids or multiplier != 1.0 or cash != 0.0 or rights != 0.0:
            return None
        denominator = previous_close
    else:
        if (
            rights != 0.0
            or multiplier <= 0
            or cash < 0
            or pd.isna(row.corporate_action_available_date)
            or pd.Timestamp(row.corporate_action_available_date)
            > pd.Timestamp(row.trade_date).normalize()
        ):
            return None
        denominator = (previous_close - cash) / multiplier
    current_close = float(row.raw_close)
    if denominator <= 0 or current_close <= 0:
        return None
    value = math.log(current_close / denominator)
    return value if math.isfinite(value) else None


def attach_prior20_max(
    connection: duckdb.DuckDBPyConnection, pool: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    targets = pool[["pool_row_id", "symbol", "signal_date", "signal_cal_idx"]].copy()
    connection.register("v35_targets", targets)
    history = connection.execute(
        """
        WITH calendar AS (
          SELECT trade_date,row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
          FROM (
            SELECT DISTINCT trade_date FROM v35_daily
            WHERE trade_date BETWEEN DATE '2018-01-01' AND DATE '2020-12-31'
          )
        )
        SELECT t.pool_row_id,t.signal_date,t.signal_cal_idx,d.symbol,d.trade_date,c.cal_idx,
          d.close AS raw_close,d.decision_at,d.available_at,d.corporate_action_count,
          d.corporate_action_ids,d.corporate_action_blocking,d.share_multiplier,
          d.cash_per_share,d.rights_ratio,d.corporate_action_available_date,
          d.hard_valid,d.bar_valid,d.trading_state_valid,d.industry_valid,d.float_valid,
          d.corporate_action_valid,d.market_valid,d.market_rule_valid,
          d.historical_identity_valid,d.current_day_data_tradable,
          d.snapshot_id,d.daily_snapshot_id,d.trading_state_snapshot_id,
          d.industry_snapshot_id,d.float_snapshot_id,d.corporate_action_snapshot_id,
          d.market_snapshot_id
        FROM v35_targets t
        JOIN calendar c
          ON c.cal_idx BETWEEN t.signal_cal_idx-20 AND t.signal_cal_idx
        JOIN v35_daily d ON d.trade_date=c.trade_date AND d.symbol=t.symbol
        WHERE d.trade_date BETWEEN DATE '2018-01-01' AND DATE '2020-12-31'
          AND c.trade_date<=t.signal_date
        ORDER BY t.pool_row_id,c.cal_idx
        """
    ).fetchdf()
    for column in (
        "signal_date",
        "trade_date",
        "decision_at",
        "available_at",
        "corporate_action_available_date",
    ):
        history[column] = pd.to_datetime(history[column], errors="coerce")

    max_by_id: dict[int, float] = {}
    invalid_groups = 0
    for pool_row_id, group in history.groupby("pool_row_id", sort=False):
        ordered = group.sort_values("cal_idx", kind="mergesort")
        expected_last = int(ordered.signal_cal_idx.iloc[0]) if not ordered.empty else -1
        expected_indices = np.arange(expected_last - MAX_DIAGNOSTIC_STEPS, expected_last + 1)
        if (
            len(ordered) != MAX_DIAGNOSTIC_STEPS + 1
            or not np.array_equal(ordered.cal_idx.to_numpy(dtype=int), expected_indices)
            or not all(_history_row_valid(row) for row in ordered.itertuples(index=False))
        ):
            invalid_groups += 1
            continue
        rows = list(ordered.itertuples(index=False))
        steps: list[float] = []
        for previous, current in pairwise(rows):
            step = _action_step_return(float(previous.raw_close), current)
            if step is None:
                steps = []
                break
            steps.append(step)
        if len(steps) == MAX_DIAGNOSTIC_STEPS:
            max_by_id[int(pool_row_id)] = max(steps)
        else:
            invalid_groups += 1
    output = pool.copy()
    output["prior20_max_log_return"] = output.pool_row_id.map(max_by_id)
    audit = {
        "rankable_pool_rows": len(pool),
        "history_rows_read": len(history),
        "prior20_max_available_rows": int(output.prior20_max_log_return.notna().sum()),
        "prior20_max_missing_rows": int(output.prior20_max_log_return.isna().sum()),
        "invalid_or_incomplete_history_groups": invalid_groups,
        "maximum_history_trade_date": (
            None if history.empty else str(history.trade_date.max().date())
        ),
        "post_signal_history_rows": int((history.trade_date > history.signal_date).sum()),
        "post_2020_history_rows": int((history.trade_date > SIGNAL_END).sum()),
        "diagnostic_changed_candidate_identity": False,
    }
    if audit["post_signal_history_rows"] or audit["post_2020_history_rows"]:
        raise ResearchError(f"V35 MAX diagnostic time boundary failed: {audit}")
    return output, audit


def apply_cooldown(selected: pd.DataFrame) -> pd.DataFrame:
    ordered = selected.sort_values(
        ["symbol", "signal_cal_idx", "industry", "event_id"], kind="mergesort"
    ).copy()
    keep = pd.Series(False, index=ordered.index, dtype=bool)
    last_retained: dict[str, int] = {}
    for index, row in ordered.iterrows():
        symbol = str(row.symbol)
        current = int(row.signal_cal_idx)
        prior = last_retained.get(symbol)
        if prior is None or current - prior > COOLDOWN_SESSIONS:
            keep.loc[index] = True
            last_retained[symbol] = current
    ordered["retained_after_60_session_cooldown"] = keep
    return ordered.sort_values(
        ["signal_date", "industry", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)


def safe_rank_correlation(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any]:
    values = frame[[left, right]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(values) < 3 or values.nunique().min() < 2:
        return {"n": len(values), "rho": None}
    rho = values[left].rank(method="average").corr(values[right].rank(method="average"))
    return {"n": len(values), "rho": None if pd.isna(rho) else float(rho)}


def redundancy_diagnostics(pool: pd.DataFrame, selected: pd.DataFrame) -> dict[str, Any]:
    work = pool.copy()
    group_keys = ["signal_date", "industry"]
    features = (
        "circulating_market_value_cny",
        "amount",
        "turnover_fraction",
        "prior20_max_log_return",
    )
    group_rows: dict[str, list[float]] = {feature: [] for feature in features}
    for _, group in work.groupby(group_keys, sort=False):
        for feature in features:
            result = safe_rank_correlation(group, "board_lot_ticket_cny", feature)
            if result["rho"] is not None:
                group_rows[feature].append(float(result["rho"]))

    pooled_ranked = work.copy()
    for column in ("board_lot_ticket_cny", *features):
        pooled_ranked[f"{column}_within_group_rank"] = pooled_ranked.groupby(
            group_keys, sort=False
        )[column].rank(method="average", pct=True)

    size_ordered = work.sort_values(
        [*group_keys, "circulating_market_value_cny", "symbol"], kind="mergesort"
    ).copy()
    size_ordered["same_pool_lowest_size_rank"] = (
        size_ordered.groupby(group_keys, sort=False).cumcount() + 1
    )
    size_rank = size_ordered.set_index("pool_row_id").same_pool_lowest_size_rank
    work["same_pool_lowest_size_rank"] = work.pool_row_id.map(size_rank)
    max_available = work.loc[work.prior20_max_log_return.notna()].copy()
    max_available = max_available.sort_values(
        [*group_keys, "prior20_max_log_return", "symbol"], kind="mergesort"
    )
    max_available["same_pool_lowest_max_rank"] = (
        max_available.groupby(group_keys, sort=False).cumcount() + 1
    )
    lowest_max_keys = set(
        zip(
            max_available.loc[max_available.same_pool_lowest_max_rank.eq(1), "signal_date"],
            max_available.loc[max_available.same_pool_lowest_max_rank.eq(1), "industry"],
            max_available.loc[max_available.same_pool_lowest_max_rank.eq(1), "symbol"],
            strict=False,
        )
    )
    selected_keys = list(
        zip(selected.signal_date, selected.industry, selected.symbol, strict=False)
    )
    max_eligible_groups = {(date, industry) for date, industry, _symbol in lowest_max_keys}
    size_lookup = work.set_index("pool_row_id").same_pool_lowest_size_rank
    size_collision = selected.pool_row_id.map(size_lookup).eq(1)
    max_eligible = [
        (date, industry) in max_eligible_groups
        for date, industry, _symbol in selected_keys
    ]
    max_collision = [key in lowest_max_keys for key in selected_keys]

    per_group = {
        feature: {
            "groups": len(values),
            "mean_rho": None if not values else float(np.mean(values)),
            "median_rho": None if not values else float(np.median(values)),
            "minimum_rho": None if not values else float(np.min(values)),
            "maximum_rho": None if not values else float(np.max(values)),
        }
        for feature, values in group_rows.items()
    }
    pooled = {
        feature: safe_rank_correlation(
            pooled_ranked,
            "board_lot_ticket_cny_within_group_rank",
            f"{feature}_within_group_rank",
        )
        for feature in features
    }
    return {
        "role": "OUTCOME_BLIND_NON_FILTERING_REDUNDANCY_DIAGNOSTIC_ONLY",
        "rankable_pool_rows": len(work),
        "date_industry_groups": int(work.groupby(group_keys).ngroups),
        "within_group_rank_correlation": per_group,
        "pooled_within_group_fractional_rank_correlation": pooled,
        "selected_full_industry_size_percentile": distribution_summary(
            selected.full_industry_size_percentile
        ),
        "selected_full_industry_amount_percentile": distribution_summary(
            selected.full_industry_amount_percentile
        ),
        "selected_equals_same_pool_lowest_size": {
            "n": len(selected),
            "count": int(size_collision.sum()),
            "fraction": None if selected.empty else float(size_collision.mean()),
        },
        "selected_equals_same_pool_lowest_prior20_max": {
            "eligible_groups": int(sum(max_eligible)),
            "count": int(sum(max_collision)),
            "fraction": (
                None
                if not any(max_eligible)
                else float(sum(max_collision) / sum(max_eligible))
            ),
        },
        "candidate_identity_changed": False,
    }


def distribution_summary(values: pd.Series) -> dict[str, float | int | None]:
    finite = pd.to_numeric(values, errors="coerce")
    finite = finite[np.isfinite(finite)]
    if finite.empty:
        return {"n": 0, "min": None, "median": None, "max": None, "mean": None}
    return {
        "n": len(finite),
        "min": float(finite.min()),
        "median": float(finite.median()),
        "max": float(finite.max()),
        "mean": float(finite.mean()),
    }


def semantic_and_opportunity_audit(
    representation: pd.DataFrame,
    candidates: pd.DataFrame,
    source_audit: dict[str, Any],
    max_audit: dict[str, Any],
) -> tuple[dict[str, Any], bool, bool]:
    annual: dict[str, Any] = {}
    annual_passes: list[bool] = []
    for year in YEARS:
        part = candidates.loc[candidates.signal_date.dt.year.eq(year)]
        count = len(part)
        industries = int(part.industry.nunique())
        months = int(part.signal_date.dt.to_period("M").nunique())
        symbols = int(part.symbol.nunique())
        gate = (
            count > MIN_ANNUAL_CANDIDATES_EXCLUSIVE
            and industries >= MIN_ANNUAL_INDUSTRIES
            and months >= MIN_ANNUAL_MONTHS
            and symbols > MIN_ANNUAL_SYMBOLS_EXCLUSIVE
        )
        annual_passes.append(gate)
        annual[str(year)] = {
            "retained_candidates": count,
            "pit_industries": industries,
            "decision_months": months,
            "unique_symbols": symbols,
            "candidate_count_gt_50": bool(count > MIN_ANNUAL_CANDIDATES_EXCLUSIVE),
            "industry_count_ge_20": bool(industries >= MIN_ANNUAL_INDUSTRIES),
            "decision_months_ge_10": bool(months >= MIN_ANNUAL_MONTHS),
            "unique_symbols_gt_50": bool(symbols > MIN_ANNUAL_SYMBOLS_EXCLUSIVE),
            "annual_opportunity_gate_passed": bool(gate),
        }

    retained = representation.loc[
        representation.retained_after_60_session_cooldown
    ].sort_values(["signal_date", "industry", "symbol", "event_id"], kind="mergesort")
    frozen_candidates = candidates.sort_values(
        ["signal_date", "industry", "symbol", "event_id"], kind="mergesort"
    )
    retained_keys = list(
        zip(
            retained.signal_date,
            retained.industry,
            retained.symbol,
            retained.event_id,
            strict=True,
        )
    )
    candidate_keys = list(
        zip(
            frozen_candidates.signal_date,
            frozen_candidates.industry,
            frozen_candidates.symbol,
            frozen_candidates.event_id,
            strict=True,
        )
    )
    winner_rows = representation.ticket_choice_rank.eq(1)
    ticket_identity_error = ~np.isclose(
        representation.board_lot_ticket_cny,
        BOARD_LOT_SHARES * representation.raw_close,
        rtol=0.0,
        atol=1e-12,
    )
    semantic_checks = {
        "duplicate_event_ids": int(representation.event_id.duplicated().sum()),
        "duplicate_date_industry_before_cooldown": int(
            representation.duplicated(["signal_date", "industry"]).sum()
        ),
        "retained_candidate_identity_mismatch": int(retained_keys != candidate_keys),
        "nonwinner_representation_rows": int((~winner_rows).sum()),
        "ticket_identity_error_rows": int(ticket_identity_error.sum()),
        "nonmiddle_tercile_rows": int(representation.size_tercile.ne(2).sum()),
        "industry_minimum_failure_rows": int(
            representation.industry_n_after_amount_floor.lt(MIN_INDUSTRY_COUNT).sum()
        ),
        "amount_floor_failure_rows": int(
            representation.amount.lt(representation.same_date_amount_median_cny).sum()
        ),
        "predictor_after_decision_rows": int(
            representation.available_at.gt(representation.decision_at).sum()
        ),
        "post_2020_signal_rows": int((representation.signal_date > SIGNAL_END).sum()),
        "pre_2018_signal_rows": int((representation.signal_date < SIGNAL_START).sum()),
        "post_signal_history_rows": int(max_audit["post_signal_history_rows"]),
        "post_2020_history_rows": int(max_audit["post_2020_history_rows"]),
        "source_out_of_range_rows": int(source_audit["cy006_out_of_range_partition_rows"]),
        "source_duplicate_keys": int(source_audit["cy006_duplicate_symbol_date_keys"]),
        "source_time_travel_rows": int(source_audit["cy006_hard_valid_time_travel_rows"]),
    }
    for _, group in candidates.groupby("symbol", sort=False):
        gaps = np.diff(group.sort_values("signal_cal_idx").signal_cal_idx.to_numpy(dtype=int))
        if len(gaps) and int(gaps.min()) <= COOLDOWN_SESSIONS:
            raise ResearchError("V35 60-session cooldown drift")
    semantic_pass = all(value == 0 for value in semantic_checks.values())
    opportunity_pass = bool(all(annual_passes))
    return {"checks": semantic_checks, "annual": annual}, semantic_pass, opportunity_pass


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    connection.close()


def run_stage_a() -> dict[str, Any]:
    public_hashes = verify_public_contract()
    source_hashes, _registry = verify_inputs(public_hashes)
    if STAGE_A.exists() or STAGE_A.is_symlink():
        raise ResearchError(f"canonical V35 Stage A already exists: {STAGE_A}")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".stage_a_staging_", dir=OUTPUT_ROOT))
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = connect(staging / "duckdb_tmp")
        pool, source_audit = load_signal_rows(connection)
        pool, max_audit = attach_prior20_max(connection, pool)
        connection.close()
        connection = None

        selected = pool.loc[pool.ticket_choice_rank.eq(1)].copy()
        selected["event_id"] = (
            "BOARD_LOT_AFFORDABILITY|"
            + selected.signal_date.dt.strftime("%Y%m%d")
            + "|"
            + selected.industry.astype(str)
            + "|"
            + selected.symbol.astype(str)
        )
        representation = apply_cooldown(selected)
        candidates = representation.loc[
            representation.retained_after_60_session_cooldown
        ].copy()
        candidates = candidates.drop(columns=["retained_after_60_session_cooldown"])
        candidates = candidates.reset_index(drop=True)

        gate_audit, semantic_pass, opportunity_pass = semantic_and_opportunity_audit(
            representation, candidates, source_audit, max_audit
        )
        diagnostics = redundancy_diagnostics(pool, selected)
        if not semantic_pass:
            raise ResearchError("V35 semantic/PIT gate failed; canonical publication forbidden")

        representation_path = staging / "representation_panel.parquet"
        candidates_path = staging / "candidates_frozen.parquet"
        published_files = ["result.json"]
        representation_hash: str | None = None
        candidates_hash: str | None = None
        if opportunity_pass:
            write_parquet(representation, representation_path)
            write_parquet(candidates, candidates_path)
            representation_hash = sha256(representation_path)
            candidates_hash = sha256(candidates_path)
            published_files = [
                "representation_panel.parquet",
                "candidates_frozen.parquet",
                "result.json",
            ]
        status = (
            "PASSED_OUTCOME_BLIND_OPPORTUNITY_GATE_STAGE_B_NOT_AUTHORIZED"
            if opportunity_pass
            else "FAILED_OPPORTUNITY_GATE_PERMANENTLY_CLOSED"
        )
        result: dict[str, Any] = {
            "experiment": EXPERIMENT,
            "stage": "OUTCOME_BLIND_COUNT_AND_REDUNDANCY_GATE",
            "status": status,
            "source_hashes": source_hashes,
            "frozen_definition": (
                "First completed Friday monthly; amount>=same-date median; within each "
                "PIT industry n>=12 select the lowest 100-share raw-close ticket from "
                "circulating-market-value tercile 2; 60-session symbol cooldown."
            ),
            "source_audit": source_audit,
            "prior20_max_audit": max_audit,
            "gate_audit": gate_audit,
            "redundancy_diagnostics": diagnostics,
            "representation_rows": len(representation),
            "candidate_rows": len(candidates),
            "candidate_symbols": int(candidates.symbol.nunique()),
            "candidate_decision_dates": int(candidates.signal_date.nunique()),
            "candidate_pit_industries": int(candidates.industry.nunique()),
            "ticket_distribution_cny": distribution_summary(candidates.board_lot_ticket_cny),
            "circulating_market_value_distribution_cny": distribution_summary(
                candidates.circulating_market_value_cny
            ),
            "amount_distribution_cny": distribution_summary(candidates.amount),
            "representation_sha256": representation_hash,
            "candidates_sha256": candidates_hash,
            "representation_published": bool(opportunity_pass),
            "candidates_published": bool(opportunity_pass),
            "published_files": published_files,
            "semantic_gate_passed": semantic_pass,
            "opportunity_gate_passed": opportunity_pass,
            "stage_a_gate_passed": bool(semantic_pass and opportunity_pass),
            "opportunity_gate_failure_publication_allowed": bool(
                semantic_pass and not opportunity_pass
            ),
            "outcome_columns_read": False,
            "post_signal_rows_read": False,
            "post_2020_rows_read": False,
            "stage_b_authorized": False,
            "charts_authorized": False,
            "portfolio_replay_authorized": False,
            "stage_b_and_charts_permanently_forbidden": bool(not opportunity_pass),
            "next_action": (
                "INDEPENDENTLY_AUDIT_STAGE_A_THEN_FREEZE_A_SEPARATE_CHART_OR_STAGE_B_CONTRACT"
                if semantic_pass and opportunity_pass
                else "PERMANENTLY_CLOSE_V35_WITHOUT_ANY_FORWARD_OUTCOME_OR_CHART_READ"
            ),
        }
        (staging / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(staging / "duckdb_tmp", ignore_errors=True)
        observed_files = sorted(path.name for path in staging.iterdir() if path.is_file())
        if observed_files != sorted(published_files):
            raise ResearchError(
                f"V35 staging publication file-set drift: {observed_files} != "
                f"{sorted(published_files)}"
            )

        final_public_hashes = verify_public_contract()
        final_source_hashes, _final_registry = verify_inputs(final_public_hashes)
        if final_source_hashes != source_hashes:
            raise ResearchError("a frozen V35 input changed during Stage A")
        if STAGE_A.exists() or STAGE_A.is_symlink():
            raise ResearchError(f"canonical V35 Stage A appeared during construction: {STAGE_A}")
        staging.rename(STAGE_A)
    except Exception:
        if connection is not None:
            connection.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify-public-contract", action="store_true")
    mode.add_argument("--run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.verify_public_contract:
        print(
            json.dumps(
                {
                    "experiment": EXPERIMENT,
                    "public_hashes": verify_public_contract(),
                    "source_files_touched": False,
                    "outcomes_read": False,
                    "run_authorized_by_this_check": False,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return
    print(json.dumps(run_stage_a(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
