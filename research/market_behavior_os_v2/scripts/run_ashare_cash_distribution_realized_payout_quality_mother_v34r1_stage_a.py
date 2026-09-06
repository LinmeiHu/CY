#!/usr/bin/env python3
"""Run the outcome-blind V34R1 structural-N/A semantic correction."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-CASH-DISTRIBUTION-REALIZED-PAYOUT-QUALITY-MOTHER-V34R1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
REGISTRY = REPO / "configs/data_asset_registry.json"
MANIFEST = REPO / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-V34R1-CY047_DATA_ASSET_MANIFEST.json"
)
BASE_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_cash_distribution_realized_payout_quality_mother_v34_stage_a.py"
)
BASE_SPEC = REPO / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-CASH-DISTRIBUTION-REALIZED-PAYOUT-QUALITY-MOTHER-V34_freeze.json"
)
BASE_MANIFEST = REPO / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-V34-CY045_DATA_ASSET_MANIFEST.json"
)
NORMALIZER = Path(
    "/Users/linmei/Downloads/workspace/quant/data/staging/"
    "crsp_lean_corporate_actions_enrichment_20260809_v2/vintages/"
    "official_full_sh_sz_current_snapshot_20260809_v5/lineage/"
    "cninfo_current_snapshot.py"
)
BASE_STAGE_A = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_cash_distribution_realized_payout_quality_mother_v34/stage_a"
)

ASSET_ID = "CY-047"
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-CASH-DISTRIBUTION-PAYOUT-QUALITY-"
    "V34R1-STAGE-A-2018-2020-V1"
)
AUTHORIZATION_PURPOSE = "ASHARE_OUTCOME_BLIND_MOTHER_REPRESENTATION"
AUTHORIZED_ARM = "V34R1_FROZEN_OUTCOME_BLIND_STAGE_A_ONLY"
MANIFEST_STATUS = "FROZEN_OUTCOME_BLIND_SEMANTIC_CORRECTION_BOUNDED_INPUT"
EXPECTED_SPEC_SHA256 = (
    "e41bfe9de6c68878ea556cf31397075adda9076adc19a4089215284436c6bdb4"
)

PARENT_INPUTS = {
    "corporate_action_id_contract": {
        "path": str(REPO / "src/cyq_game/chip/price_coordinate.py"),
        "sha256": "60c9f80fcaa2bf4a6ebfaab37bc56e81dd716cc3bea00891b4fc28d077dd1726",
    },
    "qd010_inventory": {
        "path": "/Users/linmei/Documents/CY/data/input_inventories/"
        "QD-010-cninfo-actions-20260820.json",
        "sha256": "e1ca622ee227ce308b44933160754d450b80d3ecca79c1470037558e1011ceb8",
    },
    "qd010_source_manifest": {
        "path": "/Users/linmei/Downloads/workspace/quant/data/staging/"
        "crsp_lean_corporate_actions_enrichment_20260809_v2/vintages/"
        "official_full_sh_sz_current_snapshot_20260809_v5/manifest.json",
        "sha256": "d57afb7826aa87c3929367a989a369f087a7ecf05f1026bcfed751600a3e884c",
    },
    "qd010_distributions": {
        "path": "/Users/linmei/Downloads/workspace/quant/data/staging/"
        "crsp_lean_corporate_actions_enrichment_20260809_v2/vintages/"
        "official_full_sh_sz_current_snapshot_20260809_v5/normalized/"
        "distributions.parquet",
        "sha256": "5982b7dd75ec53deb9ce3874aaf3e4a5168a731b5bbd6d8c2d89258fe4aff387",
    },
    "qd010_rights": {
        "path": "/Users/linmei/Downloads/workspace/quant/data/staging/"
        "crsp_lean_corporate_actions_enrichment_20260809_v2/vintages/"
        "official_full_sh_sz_current_snapshot_20260809_v5/normalized/"
        "rights_issues.parquet",
        "sha256": "07e864ac6da1d59b69c1b9ce1bcdd01d96d913d0909a718d79627939f8ab87cb",
    },
    "cy006_inventory": {
        "path": "/Users/linmei/Documents/CY/data/input_inventories/"
        "CY-006-pit-b-daily-v2-2018-2026-20260821.json",
        "sha256": "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    },
    "cy006_2018": {
        "path": "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/"
        "daily/partition_year=2018/data_0.parquet",
        "sha256": "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    },
    "cy006_2019": {
        "path": "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/"
        "daily/partition_year=2019/data_0.parquet",
        "sha256": "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    },
    "cy006_2020": {
        "path": "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/"
        "daily/partition_year=2020/data_0.parquet",
        "sha256": "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
    },
}

EXTRA_INPUTS = {
    "v34_base_runner": {
        "path": str(BASE_RUNNER),
        "sha256": "72fe4f7a6300b726ceed0f675ead921e8209aeca994b6cd7c014cbc0258b03d6",
    },
    "qd010_normalizer_semantics": {
        "path": str(NORMALIZER),
        "sha256": "6b012c19c825b2fb7026b83a55710cf00b2d40cfcb4d334543d2a4511dac1eae",
    },
    "v34_parent_spec": {
        "path": str(BASE_SPEC),
        "sha256": "86adf9667245638671ec9c4b733ff47fbd16abd20306d3f4c2bc048a394e489d",
    },
    "v34_parent_manifest": {
        "path": str(BASE_MANIFEST),
        "sha256": "f8407b4c7aa18f420880416c83f23041ae4d42f49c37902a348dc9bd4c964794",
    },
    "v34_parent_stage_a_result": {
        "path": str(BASE_STAGE_A / "result.json"),
        "sha256": "b6c6906fccb70b8af287d7c1f5741a096cf4386624df5e4b91b6f872ab7e7322",
    },
    "v34_parent_stage_a_representation": {
        "path": str(BASE_STAGE_A / "representation_panel.parquet"),
        "sha256": "9112509523807f0901a975d97fe9daef0584481dba577f4cdb1397bfba606537",
    },
    "v34_parent_stage_a_candidates": {
        "path": str(BASE_STAGE_A / "candidates_frozen.parquet"),
        "sha256": "d8845e11504d95029ae55f05b6d060a9528ffd0e99cc17e8094bee818cf2d8c1",
    },
}


class CorrectionError(RuntimeError):
    """Fail closed on public authorization or structural-N/A drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorrectionError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CorrectionError(f"{label} must be one JSON object")
    return value


def one(items: object, key: str, value: str, label: str) -> dict[str, Any]:
    if not isinstance(items, list):
        raise CorrectionError(f"{label} must be a list")
    matches = [item for item in items if isinstance(item, dict) and item.get(key) == value]
    if len(matches) != 1:
        raise CorrectionError(f"missing or duplicate {label}: {value}")
    return matches[0]


def require_bound_artifacts(items: object, expected: dict[str, dict[str, str]]) -> None:
    if not isinstance(items, list):
        raise CorrectionError("bound_artifacts must be a list")
    observed: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            raise CorrectionError("malformed bound_artifacts row")
        role = item["role"]
        if role in observed:
            raise CorrectionError(f"duplicate bound artifact role: {role}")
        observed[role] = {"path": item.get("path"), "sha256": item.get("sha256")}
    if observed != expected:
        raise CorrectionError("bound_artifacts drift")


def expected_inputs() -> dict[str, dict[str, str]]:
    return {**PARENT_INPUTS, **EXTRA_INPUTS}


def expected_binding(runner_hash: str) -> dict[str, Any]:
    return {
        "spec": {"path": str(SPEC), "sha256": EXPECTED_SPEC_SHA256},
        "runner": {"path": str(Path(__file__).resolve()), "sha256": runner_hash},
        "inputs": expected_inputs(),
    }


def verify_public_envelope() -> None:
    public = (SPEC, REGISTRY, MANIFEST, Path(__file__).resolve())
    if any(not path.is_file() for path in public):
        raise CorrectionError("missing V34R1 public authorization input")
    spec_hash = sha256(SPEC)
    runner_hash = sha256(Path(__file__).resolve())
    manifest_hash = sha256(MANIFEST)
    if spec_hash != EXPECTED_SPEC_SHA256:
        raise CorrectionError("V34R1 spec hash drift")

    registry = load_json(REGISTRY, "registry")
    manifest = load_json(MANIFEST, "CY-047 manifest")
    asset = one(registry.get("assets"), "asset_id", ASSET_ID, "registry asset")
    authorization = one(
        registry.get("bounded_authorizations"),
        "authorization_id",
        AUTHORIZATION_ID,
        "bounded authorization",
    )
    binding = expected_binding(runner_hash)
    expected_artifacts = expected_inputs()
    required_true = (
        "stage_a_authorized",
        "whole_artifact_hash_authorized",
        "inventory_metadata_parse_authorized",
        "source_parquet_stage_a_parse_authorized",
    )
    required_false = (
        "stage_b_authorized",
        "outcome_attachment_authorized",
        "outcome_artifact_parse_authorized",
        "outcome_columns_read_authorized",
        "post_signal_row_read_authorized",
        "charts_authorized",
        "portfolio_replay_authorized",
        "parameter_search_authorized",
        "post_2020_read_authorized",
        "2021_read_authorized",
        "2022_plus_read_authorized",
        "current_survivor_fallback_allowed",
    )
    expected_scope = {
        "project": "research/market_behavior_os_v2",
        "start": "2018-01-01",
        "end": "2020-12-31",
        "signal_start": "2018-01-01",
        "signal_end": "2020-12-31",
        "maximum_source_row_date": "2020-12-31",
    }
    lineage = asset.get("lineage", {})
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or lineage.get("immutable_manifest") is not True
        or lineage.get("manifest_path") != str(MANIFEST)
        or lineage.get("manifest_sha256") != manifest_hash
        or set(lineage.get("component_assets", [])) != {"QD-010", "CY-006"}
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
        or asset.get("stage_a_binding") != binding
    ):
        raise CorrectionError("CY-047 registry asset binding drift")
    scope = authorization.get("scope", {})
    protocol = authorization.get("bound_protocol", {})
    bound_manifest = authorization.get("bound_manifest", {})
    if (
        authorization.get("purpose") != AUTHORIZATION_PURPOSE
        or authorization.get("asset_id") != ASSET_ID
        or authorization.get("authorized_arms") != [AUTHORIZED_ARM]
        or any(authorization.get(key) is not True for key in required_true)
        or any(authorization.get(key) is not False for key in required_false)
        or any(scope.get(key) != value for key, value in expected_scope.items())
        or bound_manifest != {"path": str(MANIFEST), "sha256": manifest_hash}
        or protocol.get("path") != str(SPEC)
        or protocol.get("sha256") != spec_hash
        or protocol.get("runner_path") != str(Path(__file__).resolve())
        or protocol.get("runner_sha256") != runner_hash
        or authorization.get("stage_a_binding") != binding
    ):
        raise CorrectionError("CY-047 bounded authorization drift")
    require_bound_artifacts(authorization.get("bound_artifacts"), expected_artifacts)
    boundary = manifest.get("authorization_boundary", {})
    if (
        manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != MANIFEST_STATUS
        or manifest.get("pit_grade") != "B"
        or manifest.get("stage_a_binding") != binding
        or boundary.get("authorization_id") != AUTHORIZATION_ID
        or boundary.get("purpose") != AUTHORIZATION_PURPOSE
        or boundary.get("authorized_arm") != AUTHORIZED_ARM
        or any(boundary.get(key) is not True for key in required_true)
        or any(boundary.get(key) is not False for key in required_false)
        or any(boundary.get(key) != value for key, value in expected_scope.items())
    ):
        raise CorrectionError("CY-047 manifest binding drift")
    require_bound_artifacts(manifest.get("bound_artifacts"), expected_artifacts)


def verify_code_semantics_before_import() -> None:
    for role in ("v34_base_runner", "qd010_normalizer_semantics"):
        item = EXTRA_INPUTS[role]
        path = Path(item["path"])
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise CorrectionError(f"V34R1 code-semantic input drift: {role}")


def load_parent() -> ModuleType:
    module_spec = importlib.util.spec_from_file_location("v34r1_bound_parent", BASE_RUNNER)
    if module_spec is None or module_spec.loader is None:
        raise CorrectionError("cannot load the hash-bound V34 parent runner")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


class _StructuralNaCursor:
    def __init__(self, cursor: Any, state: dict[str, int]) -> None:
        self._cursor = cursor
        self._state = state

    def fetchdf(self) -> pd.DataFrame:
        frame = self._cursor.fetchdf()
        if "rights_subscription_ratio" not in frame.columns:
            raise CorrectionError("distribution structural-N/A field missing")
        structural_na = frame["rights_subscription_ratio"].isna()
        if not structural_na.all():
            raise CorrectionError(
                "distribution rights_subscription_ratio contains a non-structural value"
            )
        self._state["distribution_rows_verified_structural_na"] = len(frame)
        self._state["distribution_unexpected_nonmissing_rows"] = 0
        corrected = frame.copy()
        corrected["rights_subscription_ratio"] = 0.0
        return corrected


class _StructuralNaConnection:
    def __init__(self, connection: Any, distribution_path: Path, state: dict[str, int]) -> None:
        self._connection = connection
        self._distribution_path = str(distribution_path)
        self._state = state

    def execute(self, query: str, parameters: Any = None) -> Any:
        cursor = self._connection.execute(query, parameters)
        values = parameters if isinstance(parameters, (list, tuple)) else ()
        is_distribution_projection = (
            len(values) == 1
            and str(values[0]) == self._distribution_path
            and "rights_subscription_ratio" in query
            and "cash_per_share_gross" in query
        )
        if is_distribution_projection:
            self._state["distribution_projection_queries"] = (
                self._state.get("distribution_projection_queries", 0) + 1
            )
            return _StructuralNaCursor(cursor, self._state)
        return cursor


class _Cy006OptionalZeroCursor:
    def __init__(self, cursor: Any, state: dict[str, int]) -> None:
        self._cursor = cursor
        self._state = state

    def fetchdf(self) -> pd.DataFrame:
        frame = self._cursor.fetchdf()
        if "cy006_rights_ratio" not in frame.columns:
            raise CorrectionError("joined CY-006 optional rights field missing")
        numeric = pd.to_numeric(frame["cy006_rights_ratio"], errors="coerce")
        unexpected = frame["cy006_rights_ratio"].notna() & numeric.ne(0.0)
        if unexpected.any():
            raise CorrectionError("joined CY-006 rights_ratio contains a nonzero value")
        self._state["cy006_optional_rights_null_rows"] = int(numeric.isna().sum())
        self._state["cy006_explicit_zero_rights_rows"] = int(numeric.eq(0.0).sum())
        self._state["cy006_unexpected_nonzero_rights_rows"] = 0
        corrected = frame.copy()
        corrected["cy006_rights_ratio"] = numeric.fillna(0.0)
        return corrected


class _Cy006OptionalZeroConnection:
    def __init__(self, connection: Any, state: dict[str, int]) -> None:
        self._connection = connection
        self._state = state

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def execute(self, query: str, parameters: Any = None) -> Any:
        cursor = self._connection.execute(query, parameters)
        is_event_join = (
            "d.rights_ratio AS cy006_rights_ratio" in query
            and "a.cash_per_share_gross" in query
        )
        if is_event_join:
            self._state["cy006_event_join_queries"] = (
                self._state.get("cy006_event_join_queries", 0) + 1
            )
            return _Cy006OptionalZeroCursor(cursor, self._state)
        return cursor


def configure_parent(parent: ModuleType) -> None:
    parent.EXPERIMENT = EXPERIMENT
    parent.SPEC = SPEC
    parent.CY045_MANIFEST = MANIFEST
    parent.ASSET_ID = ASSET_ID
    parent.AUTHORIZATION_ID = AUTHORIZATION_ID
    parent.AUTHORIZATION_PURPOSE = AUTHORIZATION_PURPOSE
    parent.AUTHORIZED_ARM = AUTHORIZED_ARM
    parent.MANIFEST_STATUS = MANIFEST_STATUS
    parent.EXPECTED_SPEC = EXPECTED_SPEC_SHA256
    parent.OUTPUT_ROOT = Path(
        "/Volumes/quant/CY_quant_research/"
        "ashare_cash_distribution_realized_payout_quality_mother_v34r1"
    )
    parent.STAGE_A = parent.OUTPUT_ROOT / "stage_a"
    parent.__file__ = str(Path(__file__).resolve())

    for role, item in EXTRA_INPUTS.items():
        path = Path(item["path"])
        parent.EXPECTED_FILES[path] = item["sha256"]
        parent.BOUND_INPUT_ROLES = (*parent.BOUND_INPUT_ROLES, (role, path))

    base_load_action_rows = parent.load_action_rows
    base_load_event_date_rows = parent.load_event_date_rows
    base_summarize = parent.summarize

    def safe_spearman_without_scipy(
        frame: pd.DataFrame, left: str, right: str
    ) -> dict[str, Any]:
        values = frame[[left, right]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(values) < 3 or values.nunique().min() < 3:
            return {"n": len(values), "rho": None}
        ranks = values.rank(method="average")
        rho = float(np.corrcoef(ranks[left].to_numpy(), ranks[right].to_numpy())[0, 1])
        return {"n": len(values), "rho": None if not np.isfinite(rho) else rho}

    def corrected_load_action_rows(connection: Any) -> tuple[Any, Any, dict[str, Any]]:
        state: dict[str, int] = {}
        adapter = _StructuralNaConnection(connection, parent.QD010_DISTRIBUTIONS, state)
        actions, rights, audit = base_load_action_rows(adapter)
        if state.get("distribution_projection_queries") != 1:
            raise CorrectionError("distribution structural-N/A adapter ran other than once")
        verified = state.get("distribution_rows_verified_structural_na")
        if verified != audit.get("distribution_rows_2018_2020"):
            raise CorrectionError("structural-N/A row-count audit mismatch")
        audit.update(state)
        audit["v34r1_semantic_correction"] = (
            "Verified every in-scope distribution rights ratio as structural N/A, then "
            "represented only that field as economic zero for the unchanged parent pure-cash "
            "filter; actual rights remain guarded by the separate rights_issues table."
        )
        return actions, rights, audit

    def corrected_load_event_date_rows(
        connection: Any, actions: Any, canonical_parser: Any
    ) -> tuple[Any, dict[str, Any]]:
        state: dict[str, int] = {}
        adapter = _Cy006OptionalZeroConnection(connection, state)
        representation, audit = base_load_event_date_rows(
            adapter, actions, canonical_parser
        )
        if state.get("cy006_event_join_queries") != 1:
            raise CorrectionError("CY-006 optional-zero adapter ran other than once")
        joined = audit.get("pure_action_rows_submitted_to_join")
        observed = state.get("cy006_optional_rights_null_rows", 0) + state.get(
            "cy006_explicit_zero_rights_rows", 0
        )
        if observed != joined:
            raise CorrectionError("CY-006 optional-rights row-count audit mismatch")
        audit.update(state)
        audit["v34r1_cy006_optional_zero_correction"] = (
            "Verified every joined CY-006 optional rights_ratio as null or explicit zero, "
            "then mapped null to canonical economic zero under the existing frozen "
            "optional-zero contract."
        )
        return representation, audit

    def corrected_summarize(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = base_summarize(*args, **kwargs)
        result["frozen_definition"] = (
            "Pure QD-010 cash distribution with distribution rights ratio verified as "
            "structural N/A and no same-symbol/day rights row; cash>0, share multiplier=1, "
            "complete unique terms, known by event-date close; valid tradable non-ST "
            "Main/ChiNext CY-006 row with optional-null-or-explicit-zero rights_ratio; "
            "cash/preclose>=2%; "
            "120-session symbol cooldown."
        )
        result["semantic_correction"] = {
            "parent_v34_result_sha256": EXTRA_INPUTS["v34_parent_stage_a_result"][
                "sha256"
            ],
            "outcome_informed": False,
            "threshold_direction_universe_or_timing_changed": False,
            "distribution_structural_na_required": True,
            "independent_rights_table_collision_guard_preserved": True,
            "cy006_optional_null_coalesced_to_zero_under_frozen_contract": True,
            "cy006_nonzero_rights_rejected": True,
        }
        if result["stage_a_gate_passed"]:
            result["next_action"] = (
                "INDEPENDENTLY_AUDIT_V34R1_STAGE_A_THEN_FREEZE_A_SEPARATE_STAGE_B_CONTRACT"
            )
        else:
            result["next_action"] = (
                "PERMANENTLY_CLOSE_V34R1_BEFORE_ANY_FORWARD_OUTCOME_OR_CHART_READ"
            )
        return result

    parent.load_action_rows = corrected_load_action_rows
    parent.load_event_date_rows = corrected_load_event_date_rows
    parent.summarize = corrected_summarize
    parent.safe_spearman = safe_spearman_without_scipy


def main() -> None:
    verify_public_envelope()
    verify_code_semantics_before_import()
    parent = load_parent()
    configure_parent(parent)
    parent.main()


if __name__ == "__main__":
    main()
