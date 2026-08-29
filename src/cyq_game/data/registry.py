"""Fail-closed activation of registered data assets.

The data asset registry is an allowlist, not an activation record.  A concrete
run must additionally name and hash every physical input in an immutable input
snapshot manifest.  This module validates both layers before data can enter a
PIT store or a strategy runtime.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any


class DataActivationError(ValueError):
    """Raised when registered data cannot be activated safely."""


class DataPurpose(StrEnum):
    DATA_PREPARATION = "DATA_PREPARATION"
    SOFTWARE_TEST = "SOFTWARE_TEST"
    CAUSAL_RESEARCH = "CAUSAL_RESEARCH"
    STRICT_ARCHIVAL_RESEARCH = "STRICT_ARCHIVAL_RESEARCH"
    CHINEXT_PIT_B_RESEARCH = "CHINEXT_PIT_B_RESEARCH"
    CHINEXT_V1_TEMPORAL_HOLDOUT_VALIDATION = "CHINEXT_V1_TEMPORAL_HOLDOUT_VALIDATION"


class DataOperation(StrEnum):
    INSPECT = "INSPECT"
    INGEST = "INGEST"
    STATE_GENERATION = "STATE_GENERATION"
    BACKTEST = "BACKTEST"
    ROBUSTNESS = "ROBUSTNESS"


@dataclass(frozen=True)
class DataAsset:
    asset_id: str
    name: str
    kind: str
    status: str
    pit_grade: str
    physical_state: str
    location: Path | None
    source: str
    lineage: dict[str, Any]


@dataclass(frozen=True)
class AuditEvidence:
    status: str
    evidence: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS" and bool(self.evidence.strip())


@dataclass(frozen=True)
class InputBinding:
    role: str
    asset: DataAsset
    path: Path
    source: str
    snapshot_id: str
    available_at_policy: str
    sha256: str | None
    inventory_manifest: Path | None
    inventory_sha256: str | None

    def verify_file(self, path: str | Path) -> Path:
        """Verify that one concrete file is frozen by this binding."""

        return _verify_bound_file(self, Path(path).expanduser().resolve())


@dataclass(frozen=True)
class DataExecutionAuthorization:
    """Immutable proof that one operation passed the activation policy.

    Strategy runtimes accept this value instead of trusting that a caller ran
    the registry checks elsewhere. The PIT store verifies the same identities
    independently before state generation starts.
    """

    operation: DataOperation
    registry_id: str
    registry_sha256: str
    input_manifest_id: str
    input_manifest_sha256: str
    purpose: DataPurpose
    hard_valid: bool
    software_test: bool
    scope_start: date
    scope_end: date


@dataclass(frozen=True)
class FrozenArtifactBinding:
    """One exact file identity inside a bounded research authorization."""

    role: str
    path: Path
    sha256: str


@dataclass(frozen=True)
class BoundedResearchAuthorization:
    """Central-registry authorization for one immutable, narrow research artifact."""

    authorization_id: str
    purpose: DataPurpose
    asset_id: str
    dependency_asset_id: str
    dependency_status: str
    project_scope: Path
    bound_manifest: Path
    bound_manifest_sha256: str
    bound_artifacts: tuple[FrozenArtifactBinding, ...]
    bound_strategy: Path
    bound_strategy_sha256: str
    scope_start: date
    scope_end: date
    current_survivor_fallback_allowed: bool
    record_level_available_at_available: bool


@dataclass(frozen=True)
class DataAssetRegistry:
    path: Path
    sha256: str
    registry_id: str
    global_gate: dict[str, Any]
    assets: dict[str, DataAsset]
    bounded_authorizations: dict[str, BoundedResearchAuthorization]

    @classmethod
    def load(cls, path: str | Path) -> DataAssetRegistry:
        registry_path = Path(path).expanduser().resolve()
        payload = _read_json_object(registry_path, label="data asset registry")
        registry_id = _required_text(payload, "registry_id", "data asset registry")
        global_gate = _required_mapping(payload, "global_gate", "data asset registry")
        raw_assets = payload.get("assets")
        if not isinstance(raw_assets, list) or not raw_assets:
            raise DataActivationError("data asset registry assets must be a non-empty list")

        assets: dict[str, DataAsset] = {}
        for raw in raw_assets:
            if not isinstance(raw, dict):
                raise DataActivationError("every data asset must be an object")
            asset_id = _required_text(raw, "asset_id", "data asset")
            if asset_id in assets:
                raise DataActivationError(f"duplicate asset_id: {asset_id}")
            raw_location = raw.get("location")
            location = (
                Path(raw_location).expanduser().resolve()
                if isinstance(raw_location, str) and raw_location.strip()
                else None
            )
            lineage = raw.get("lineage", {})
            if not isinstance(lineage, dict):
                raise DataActivationError(f"asset {asset_id} lineage must be an object")
            assets[asset_id] = DataAsset(
                asset_id=asset_id,
                name=_required_text(raw, "name", f"asset {asset_id}"),
                kind=_required_text(raw, "kind", f"asset {asset_id}"),
                status=_required_text(raw, "status", f"asset {asset_id}"),
                pit_grade=_required_text(raw, "pit_grade", f"asset {asset_id}"),
                physical_state=_required_text(raw, "physical_state", f"asset {asset_id}"),
                location=location,
                source=_required_text(raw, "source", f"asset {asset_id}"),
                lineage=lineage,
            )
        bounded_authorizations = _load_bounded_authorizations(
            payload.get("bounded_authorizations", []),
            registry_path=registry_path,
            assets=assets,
        )
        return cls(
            path=registry_path,
            sha256=_sha256_file(registry_path),
            registry_id=registry_id,
            global_gate=global_gate,
            assets=assets,
            bounded_authorizations=bounded_authorizations,
        )

    def authorize_bounded_research(
        self,
        authorization_id: str,
        *,
        purpose: DataPurpose,
        manifest_path: str | Path,
        manifest_sha256: str,
        artifacts: Mapping[str, tuple[str | Path, str]],
        start: date,
        end: date,
        dependency_asset_id: str,
        consumer_path: str | Path,
        strategy_path: str | Path,
        strategy_sha256: str,
        current_survivor_fallback: bool,
    ) -> BoundedResearchAuthorization:
        """Fail closed unless a request exactly matches one bounded authorization."""

        try:
            authorization = self.bounded_authorizations[authorization_id]
        except KeyError as exc:
            raise DataActivationError(
                f"missing bounded research authorization: {authorization_id}"
            ) from exc
        if purpose is not authorization.purpose:
            raise DataActivationError(
                "bounded authorization purpose mismatch: "
                f"expected {authorization.purpose.value}, got {purpose.value}"
            )
        if dependency_asset_id != authorization.dependency_asset_id:
            raise DataActivationError(
                "bounded authorization dependency mismatch: "
                f"expected {authorization.dependency_asset_id}, got {dependency_asset_id}"
            )
        dependency = self.assets.get(dependency_asset_id)
        if dependency is None or dependency.status != authorization.dependency_status:
            raise DataActivationError(
                f"bounded dependency status changed for {dependency_asset_id}"
            )
        if start != authorization.scope_start or end != authorization.scope_end:
            raise DataActivationError(
                "bounded authorization date range mismatch: "
                f"expected {authorization.scope_start}..{authorization.scope_end}, "
                f"got {start}..{end}"
            )
        if current_survivor_fallback or authorization.current_survivor_fallback_allowed:
            raise DataActivationError("current-survivor fallback is forbidden")

        requested_manifest = Path(manifest_path).expanduser().resolve()
        if requested_manifest != authorization.bound_manifest:
            raise DataActivationError("bounded manifest path mismatch")
        if manifest_sha256.lower() != authorization.bound_manifest_sha256:
            raise DataActivationError("bounded manifest hash mismatch")
        if _sha256_file(requested_manifest) != authorization.bound_manifest_sha256:
            raise DataActivationError("bounded manifest content changed")

        expected_artifacts = {item.role: item for item in authorization.bound_artifacts}
        if set(artifacts) != set(expected_artifacts):
            raise DataActivationError("bounded artifact roles mismatch")
        for role, (raw_path, claimed_hash) in artifacts.items():
            expected = expected_artifacts[role]
            requested_path = Path(raw_path).expanduser().resolve()
            if requested_path != expected.path:
                raise DataActivationError(f"bounded artifact path mismatch for {role}")
            if claimed_hash.lower() != expected.sha256:
                raise DataActivationError(f"bounded artifact hash mismatch for {role}")
            if _sha256_file(requested_path) != expected.sha256:
                raise DataActivationError(f"bounded artifact content changed for {role}")

        requested_strategy = Path(strategy_path).expanduser().resolve()
        if requested_strategy != authorization.bound_strategy:
            raise DataActivationError("bounded strategy path mismatch")
        if strategy_sha256.lower() != authorization.bound_strategy_sha256:
            raise DataActivationError("bounded strategy hash mismatch")
        if _sha256_file(requested_strategy) != authorization.bound_strategy_sha256:
            raise DataActivationError("bounded strategy content changed")

        consumer = Path(consumer_path).expanduser().resolve()
        if not _is_same_or_descendant(consumer, authorization.project_scope):
            raise DataActivationError(f"consumer is outside bounded research scope: {consumer}")
        return authorization


def _load_bounded_authorizations(
    raw_authorizations: object,
    *,
    registry_path: Path,
    assets: Mapping[str, DataAsset],
) -> dict[str, BoundedResearchAuthorization]:
    if not isinstance(raw_authorizations, list):
        raise DataActivationError("bounded_authorizations must be a list")
    project_root = registry_path.parent.parent
    result: dict[str, BoundedResearchAuthorization] = {}
    for raw in raw_authorizations:
        if not isinstance(raw, dict):
            raise DataActivationError("every bounded authorization must be an object")
        authorization_id = _required_text(raw, "authorization_id", "bounded authorization")
        if authorization_id in result:
            raise DataActivationError(f"duplicate bounded authorization_id: {authorization_id}")
        try:
            purpose = DataPurpose(
                _required_text(raw, "purpose", f"authorization {authorization_id}")
            )
        except ValueError as exc:
            raise DataActivationError(
                f"unknown purpose for bounded authorization {authorization_id}"
            ) from exc
        if purpose not in (
            DataPurpose.CHINEXT_PIT_B_RESEARCH,
            DataPurpose.CHINEXT_V1_TEMPORAL_HOLDOUT_VALIDATION,
        ):
            raise DataActivationError(f"unsupported bounded authorization purpose: {purpose.value}")
        asset_id = _required_text(raw, "asset_id", f"authorization {authorization_id}")
        asset = assets.get(asset_id)
        if asset is None or asset.status != "RESEARCH_CONDITIONAL":
            raise DataActivationError(
                f"bounded authorization asset is not research-conditional: {asset_id}"
            )
        if asset.lineage.get("bounded_authorization_id") != authorization_id:
            raise DataActivationError(
                f"asset {asset_id} does not bind authorization {authorization_id}"
            )
        dependency_asset_id = _required_text(
            raw, "dependency_asset_id", f"authorization {authorization_id}"
        )
        dependency = assets.get(dependency_asset_id)
        if dependency is None:
            raise DataActivationError(
                f"bounded authorization dependency is unregistered: {dependency_asset_id}"
            )
        dependency_status = _required_text(
            raw, "dependency_status", f"authorization {authorization_id}"
        )
        if dependency.status != dependency_status:
            raise DataActivationError(
                f"bounded authorization dependency status mismatch: {dependency_asset_id}"
            )

        raw_scope = _required_mapping(raw, "scope", f"authorization {authorization_id}")
        project_scope_value = _required_text(
            raw_scope, "project", f"authorization {authorization_id} scope"
        )
        project_scope_path = Path(project_scope_value)
        if project_scope_path.is_absolute() or ".." in project_scope_path.parts:
            raise DataActivationError("bounded project scope must be repository-relative")
        project_scope = (project_root / project_scope_path).resolve()
        scope_start = _required_date(raw_scope, "start", f"authorization {authorization_id} scope")
        scope_end = _required_date(raw_scope, "end", f"authorization {authorization_id} scope")
        if scope_end < scope_start:
            raise DataActivationError("bounded authorization scope end precedes start")

        manifest = _required_mapping(raw, "bound_manifest", f"authorization {authorization_id}")
        bound_manifest = (
            Path(_required_text(manifest, "path", f"authorization {authorization_id} manifest"))
            .expanduser()
            .resolve()
        )
        bound_manifest_sha256 = _required_digest(
            manifest, "sha256", f"authorization {authorization_id} manifest"
        )

        raw_artifacts = raw.get("bound_artifacts")
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            raise DataActivationError("bounded authorization artifacts must be non-empty")
        artifacts: list[FrozenArtifactBinding] = []
        roles: set[str] = set()
        for raw_artifact in raw_artifacts:
            if not isinstance(raw_artifact, dict):
                raise DataActivationError("every bounded artifact must be an object")
            role = _required_text(
                raw_artifact, "role", f"authorization {authorization_id} artifact"
            )
            if role in roles:
                raise DataActivationError(f"duplicate bounded artifact role: {role}")
            roles.add(role)
            artifacts.append(
                FrozenArtifactBinding(
                    role=role,
                    path=Path(
                        _required_text(
                            raw_artifact,
                            "path",
                            f"authorization {authorization_id} artifact {role}",
                        )
                    )
                    .expanduser()
                    .resolve(),
                    sha256=_required_digest(
                        raw_artifact,
                        "sha256",
                        f"authorization {authorization_id} artifact {role}",
                    ),
                )
            )

        strategy = _required_mapping(raw, "bound_strategy", f"authorization {authorization_id}")
        bound_strategy = (
            Path(_required_text(strategy, "path", f"authorization {authorization_id} strategy"))
            .expanduser()
            .resolve()
        )
        bound_strategy_sha256 = _required_digest(
            strategy, "sha256", f"authorization {authorization_id} strategy"
        )
        fallback_allowed = raw.get("current_survivor_fallback_allowed")
        if fallback_allowed is not False:
            raise DataActivationError("bounded authorization must forbid current-survivor fallback")
        record_available = raw.get("record_level_available_at_available")
        if record_available is not False:
            raise DataActivationError(
                "bounded authorization must preserve unavailable record-level available_at"
            )
        result[authorization_id] = BoundedResearchAuthorization(
            authorization_id=authorization_id,
            purpose=purpose,
            asset_id=asset_id,
            dependency_asset_id=dependency_asset_id,
            dependency_status=dependency_status,
            project_scope=project_scope,
            bound_manifest=bound_manifest,
            bound_manifest_sha256=bound_manifest_sha256,
            bound_artifacts=tuple(artifacts),
            bound_strategy=bound_strategy,
            bound_strategy_sha256=bound_strategy_sha256,
            scope_start=scope_start,
            scope_end=scope_end,
            current_survivor_fallback_allowed=fallback_allowed,
            record_level_available_at_available=record_available,
        )
    return result


@dataclass(frozen=True)
class InputSnapshotManifest:
    path: Path
    sha256: str
    manifest_id: str
    registry_id: str
    registry_sha256: str
    purpose: DataPurpose
    hard_valid: bool
    scope_start: date
    scope_end: date
    bindings: dict[str, InputBinding]
    audits: dict[str, AuditEvidence]

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        registry: DataAssetRegistry,
    ) -> InputSnapshotManifest:
        manifest_path = Path(path).expanduser().resolve()
        payload = _read_json_object(manifest_path, label="input snapshot manifest")
        manifest_id = _required_text(payload, "manifest_id", "input snapshot manifest")
        registry_id = _required_text(payload, "registry_id", "input snapshot manifest")
        registry_sha256 = _required_digest(payload, "registry_sha256", "input snapshot manifest")
        if registry_id != registry.registry_id:
            raise DataActivationError(
                f"registry_id mismatch: manifest={registry_id}, registry={registry.registry_id}"
            )
        if registry_sha256 != registry.sha256:
            raise DataActivationError(
                "registry hash mismatch; re-freeze the input manifest after registry changes"
            )
        try:
            purpose = DataPurpose(_required_text(payload, "purpose", "input snapshot manifest"))
        except ValueError as exc:
            raise DataActivationError("unknown input manifest purpose") from exc
        hard_valid = payload.get("hard_valid")
        if not isinstance(hard_valid, bool):
            raise DataActivationError("input snapshot manifest hard_valid must be boolean")
        raw_scope = _required_mapping(payload, "scope", "input snapshot manifest")
        scope_start = _required_date(raw_scope, "start", "input snapshot manifest scope")
        scope_end = _required_date(raw_scope, "end", "input snapshot manifest scope")
        if scope_end < scope_start:
            raise DataActivationError("input snapshot manifest scope end precedes start")

        raw_bindings = payload.get("bindings")
        if not isinstance(raw_bindings, list) or not raw_bindings:
            raise DataActivationError("input snapshot manifest bindings must be non-empty")
        bindings: dict[str, InputBinding] = {}
        for raw_binding in raw_bindings:
            binding = _load_binding(raw_binding, registry=registry, purpose=purpose)
            if binding.role in bindings:
                raise DataActivationError(f"duplicate input role: {binding.role}")
            bindings[binding.role] = binding

        audits = _load_audits(payload.get("audits"))
        instance = cls(
            path=manifest_path,
            sha256=_sha256_file(manifest_path),
            manifest_id=manifest_id,
            registry_id=registry_id,
            registry_sha256=registry_sha256,
            purpose=purpose,
            hard_valid=hard_valid,
            scope_start=scope_start,
            scope_end=scope_end,
            bindings=bindings,
            audits=audits,
        )
        instance._validate_semantics()
        return instance

    def binding(self, role: str) -> InputBinding:
        try:
            return self.bindings[role]
        except KeyError as exc:
            raise DataActivationError(
                f"input manifest does not bind required role: {role}"
            ) from exc

    def authorize(
        self,
        operation: DataOperation,
        *,
        registry: DataAssetRegistry,
        software_test: bool = False,
    ) -> DataExecutionAuthorization:
        """Authorize an operation without silently broadening the manifest purpose."""

        if operation is DataOperation.INSPECT:
            return self._authorization(operation, registry, software_test)
        if self.purpose is DataPurpose.SOFTWARE_TEST:
            if not software_test:
                raise DataActivationError(
                    "SOFTWARE_TEST data requires an explicit software_test authorization"
                )
            if not self.hard_valid:
                raise DataActivationError(
                    f"hard_valid=false blocks software-test {operation.value}"
                )
            if operation in {
                DataOperation.STATE_GENERATION,
                DataOperation.BACKTEST,
                DataOperation.ROBUSTNESS,
            }:
                qa_roles = [
                    binding.role
                    for binding in self.bindings.values()
                    if binding.asset.status == "QA_ONLY"
                ]
                if qa_roles:
                    raise DataActivationError(
                        "QA_ONLY assets may test adapters but cannot drive strategy execution: "
                        + ", ".join(sorted(qa_roles))
                    )
            return self._authorization(operation, registry, software_test)
        if software_test:
            raise DataActivationError(
                "software_test authorization cannot be applied to non-test data"
            )
        if self.purpose is DataPurpose.DATA_PREPARATION:
            if operation is DataOperation.INGEST:
                return self._authorization(operation, registry, software_test)
            raise DataActivationError(f"DATA_PREPARATION cannot authorize {operation.value}")
        if operation is DataOperation.INGEST:
            return self._authorization(operation, registry, software_test)
        if not self.hard_valid:
            raise DataActivationError(f"hard_valid=false blocks {operation.value}")
        if not all(item.passed for item in self.audits.values()):
            raise DataActivationError(f"all causal audits must PASS before {operation.value}")

        gate = registry.global_gate
        ready_key = (
            "strict_archival_pit_ready"
            if self.purpose is DataPurpose.STRICT_ARCHIVAL_RESEARCH
            else "free_causal_research_ready"
        )
        if not gate.get(ready_key, False):
            raise DataActivationError(f"global gate {ready_key}=false")
        if operation in {DataOperation.BACKTEST, DataOperation.ROBUSTNESS} and not gate.get(
            "backtest_authorized", False
        ):
            raise DataActivationError("global gate backtest_authorized=false")
        return self._authorization(operation, registry, software_test)

    def _authorization(
        self,
        operation: DataOperation,
        registry: DataAssetRegistry,
        software_test: bool,
    ) -> DataExecutionAuthorization:
        return DataExecutionAuthorization(
            operation=operation,
            registry_id=registry.registry_id,
            registry_sha256=registry.sha256,
            input_manifest_id=self.manifest_id,
            input_manifest_sha256=self.sha256,
            purpose=self.purpose,
            hard_valid=self.hard_valid,
            software_test=software_test,
            scope_start=self.scope_start,
            scope_end=self.scope_end,
        )

    def require_range(self, start: date, end: date, *, exact: bool = False) -> None:
        """Require an operation range to be covered by the frozen snapshot scope."""

        if end < start:
            raise DataActivationError("requested range end precedes start")
        if exact and (start != self.scope_start or end != self.scope_end):
            raise DataActivationError(
                "PIT construction range must exactly match the input manifest scope: "
                f"{self.scope_start}..{self.scope_end}"
            )
        if start < self.scope_start or end > self.scope_end:
            raise DataActivationError(
                "requested range falls outside the input manifest scope: "
                f"{self.scope_start}..{self.scope_end}"
            )

    def _validate_semantics(self) -> None:
        statuses = {binding.asset.status for binding in self.bindings.values()}
        if "GENERATED_OUTPUT" in statuses or "UNAVAILABLE" in statuses:
            raise DataActivationError(
                "generated outputs and unavailable assets can never be activated as inputs"
            )
        if self.purpose is DataPurpose.DATA_PREPARATION:
            if self.hard_valid:
                raise DataActivationError("DATA_PREPARATION must remain hard_valid=false")
            return
        if self.purpose is DataPurpose.SOFTWARE_TEST:
            if not self.hard_valid:
                raise DataActivationError("SOFTWARE_TEST requires hard_valid=true")
            if not statuses <= {"DEMO_ONLY", "QA_ONLY"}:
                raise DataActivationError("SOFTWARE_TEST may bind only DEMO_ONLY or QA_ONLY assets")
            return

        if not self.hard_valid:
            raise DataActivationError(f"{self.purpose.value} requires hard_valid=true")
        if not all(item.passed for item in self.audits.values()):
            raise DataActivationError(
                f"{self.purpose.value} requires PASS evidence for every audit"
            )
        if not statuses <= {"RESEARCH_CONDITIONAL", "DERIVE_ONLY"}:
            raise DataActivationError(f"{self.purpose.value} contains a non-research asset")
        if self.purpose is DataPurpose.STRICT_ARCHIVAL_RESEARCH:
            non_archival = [
                binding.asset.asset_id
                for binding in self.bindings.values()
                if binding.asset.pit_grade != "A"
            ]
            if non_archival:
                raise DataActivationError(
                    "strict archival research requires PIT grade A: "
                    + ", ".join(sorted(non_archival))
                )


REQUIRED_AUDITS = (
    "coverage",
    "duplicates",
    "time_travel",
    "consistency",
    "cross_table",
)


def _load_binding(
    raw: object,
    *,
    registry: DataAssetRegistry,
    purpose: DataPurpose,
) -> InputBinding:
    if not isinstance(raw, dict):
        raise DataActivationError("every input binding must be an object")
    role = _required_text(raw, "role", "input binding")
    asset_id = _required_text(raw, "asset_id", f"input binding {role}")
    try:
        asset = registry.assets[asset_id]
    except KeyError as exc:
        raise DataActivationError(f"unregistered asset_id: {asset_id}") from exc
    if asset.location is None:
        raise DataActivationError(f"asset {asset_id} has no physical registered location")
    path = Path(_required_text(raw, "path", f"input binding {role}")).expanduser().resolve()
    if not path.exists():
        raise DataActivationError(f"bound path does not exist: {path}")
    if not _is_same_or_descendant(path, asset.location):
        raise DataActivationError(
            f"bound path {path} is outside registered location {asset.location}"
        )

    _verify_source_manifest(asset)
    bounded_authorization_id = asset.lineage.get("bounded_authorization_id")
    if bounded_authorization_id:
        raise DataActivationError(
            f"asset {asset_id} requires central bounded authorization "
            f"{bounded_authorization_id}; generic input binding is forbidden"
        )

    sha256 = _optional_digest(raw, "sha256", f"input binding {role}")
    raw_inventory = raw.get("inventory_manifest")
    inventory_manifest = (
        Path(raw_inventory).expanduser().resolve()
        if isinstance(raw_inventory, str) and raw_inventory.strip()
        else None
    )
    inventory_sha256 = _optional_digest(raw, "inventory_sha256", f"input binding {role}")
    if path.is_file():
        if sha256 is None:
            raise DataActivationError(f"file binding {role} requires sha256")
        if _sha256_file(path) != sha256:
            raise DataActivationError(f"file hash mismatch for role {role}: {path}")
        if inventory_manifest is not None or inventory_sha256 is not None:
            raise DataActivationError(f"file binding {role} must not declare an inventory manifest")
    elif path.is_dir():
        if sha256 is not None:
            raise DataActivationError(
                f"directory binding {role} must use inventory_manifest, not sha256"
            )
        if inventory_manifest is None or inventory_sha256 is None:
            raise DataActivationError(
                f"directory binding {role} requires inventory_manifest and inventory_sha256"
            )
        if not inventory_manifest.is_file():
            raise DataActivationError(f"inventory manifest does not exist: {inventory_manifest}")
        if _sha256_file(inventory_manifest) != inventory_sha256:
            raise DataActivationError(f"inventory hash mismatch for role {role}")
        _load_inventory(inventory_manifest, expected_root=path)
    else:
        raise DataActivationError(f"bound path is not a regular file or directory: {path}")

    frozen_manifest = asset.lineage.get("manifest_path")
    frozen_hash = asset.lineage.get("manifest_sha256")
    if frozen_manifest or frozen_hash:
        if inventory_manifest is None or inventory_sha256 is None:
            raise DataActivationError(
                f"asset {asset_id} requires its registered inventory manifest"
            )
        if Path(str(frozen_manifest)).expanduser().resolve() != inventory_manifest:
            raise DataActivationError(f"registered manifest path mismatch for asset {asset_id}")
        if str(frozen_hash).lower() != inventory_sha256:
            raise DataActivationError(f"registered manifest hash mismatch for asset {asset_id}")

    if purpose is DataPurpose.SOFTWARE_TEST and asset.status not in {
        "DEMO_ONLY",
        "QA_ONLY",
    }:
        raise DataActivationError(f"software-test binding {role} uses non-test asset {asset_id}")
    return InputBinding(
        role=role,
        asset=asset,
        path=path,
        source=_required_text(raw, "source", f"input binding {role}"),
        snapshot_id=_required_text(raw, "snapshot_id", f"input binding {role}"),
        available_at_policy=_required_text(raw, "available_at_policy", f"input binding {role}"),
        sha256=sha256,
        inventory_manifest=inventory_manifest,
        inventory_sha256=inventory_sha256,
    )


def _verify_source_manifest(asset: DataAsset) -> None:
    """Verify source-lineage evidence without treating it as a content inventory."""

    raw_path = asset.lineage.get("source_manifest_path")
    raw_hash = asset.lineage.get("source_manifest_sha256")
    if raw_path is None and raw_hash is None:
        return
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise DataActivationError(
            f"asset {asset.asset_id} source_manifest_path must be non-empty text"
        )
    if not isinstance(raw_hash, str) or len(raw_hash) != 64:
        raise DataActivationError(
            f"asset {asset.asset_id} source_manifest_sha256 must be a SHA-256 digest"
        )
    try:
        int(raw_hash, 16)
    except ValueError as exc:
        raise DataActivationError(
            f"asset {asset.asset_id} source_manifest_sha256 must be a SHA-256 digest"
        ) from exc
    source_manifest = Path(raw_path).expanduser().resolve()
    if not source_manifest.is_file():
        raise DataActivationError(
            f"asset {asset.asset_id} source manifest does not exist: {source_manifest}"
        )
    if _sha256_file(source_manifest) != raw_hash.lower():
        raise DataActivationError(f"source manifest hash mismatch for asset {asset.asset_id}")


def _verify_bound_file(binding: InputBinding, path: Path) -> Path:
    if not path.is_file():
        raise DataActivationError(f"selected input is not a regular file: {path}")
    if binding.path.is_file():
        if path != binding.path:
            raise DataActivationError(
                f"selected file {path} does not equal file binding {binding.path}"
            )
        if binding.sha256 is None or _sha256_file(path) != binding.sha256:
            raise DataActivationError(f"selected file hash mismatch: {path}")
        return path
    if not _is_same_or_descendant(path, binding.path):
        raise DataActivationError(
            f"selected file {path} is outside directory binding {binding.path}"
        )
    if binding.inventory_manifest is None or binding.inventory_sha256 is None:
        raise DataActivationError(f"directory binding {binding.role} has no frozen inventory")
    if _sha256_file(binding.inventory_manifest) != binding.inventory_sha256:
        raise DataActivationError(f"inventory hash mismatch for role {binding.role}")
    entries = _load_inventory(binding.inventory_manifest, expected_root=binding.path)
    relative = path.relative_to(binding.path).as_posix()
    try:
        expected_size, expected_hash = entries[relative]
    except KeyError as exc:
        raise DataActivationError(
            f"selected file is absent from inventory for {binding.role}: {relative}"
        ) from exc
    if path.stat().st_size != expected_size:
        raise DataActivationError(f"selected file size mismatch: {path}")
    if _sha256_file(path) != expected_hash:
        raise DataActivationError(f"selected file hash mismatch: {path}")
    return path


def _load_inventory(
    path: Path,
    *,
    expected_root: Path,
) -> dict[str, tuple[int, str]]:
    payload = _read_json_object(path, label="file inventory")
    if payload.get("schema_version") != 1:
        raise DataActivationError("file inventory schema_version must equal 1")
    raw_root = _required_text(payload, "root", "file inventory")
    if Path(raw_root).expanduser().resolve() != expected_root:
        raise DataActivationError(
            f"file inventory root mismatch: expected {expected_root}, got {raw_root}"
        )
    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise DataActivationError("file inventory files must be a non-empty list")
    result: dict[str, tuple[int, str]] = {}
    for index, item in enumerate(raw_files):
        if not isinstance(item, dict):
            raise DataActivationError(f"file inventory files[{index}] must be an object")
        relative = _required_text(item, "path", f"file inventory files[{index}]")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise DataActivationError(
                f"file inventory path must be relative and contained: {relative}"
            )
        canonical = relative_path.as_posix()
        if canonical in result:
            raise DataActivationError(f"duplicate file inventory path: {canonical}")
        size = item.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise DataActivationError(
                f"file inventory size must be a non-negative integer: {canonical}"
            )
        digest = _required_digest(item, "sha256", f"file inventory {canonical}")
        result[canonical] = (size, digest)
    return result


def _load_audits(raw: object) -> dict[str, AuditEvidence]:
    if not isinstance(raw, dict):
        raise DataActivationError("input snapshot manifest audits must be an object")
    unknown = set(raw) - set(REQUIRED_AUDITS)
    missing = set(REQUIRED_AUDITS) - set(raw)
    if unknown:
        raise DataActivationError("unknown audits: " + ", ".join(sorted(unknown)))
    if missing:
        raise DataActivationError("missing audits: " + ", ".join(sorted(missing)))
    result: dict[str, AuditEvidence] = {}
    for name in REQUIRED_AUDITS:
        item = raw[name]
        if not isinstance(item, dict):
            raise DataActivationError(f"audit {name} must be an object")
        status = _required_text(item, "status", f"audit {name}")
        if status not in {"PASS", "FAIL", "NOT_RUN"}:
            raise DataActivationError(f"audit {name} has invalid status: {status}")
        evidence = item.get("evidence", "")
        if not isinstance(evidence, str):
            raise DataActivationError(f"audit {name} evidence must be text")
        result[name] = AuditEvidence(status=status, evidence=evidence)
    return result


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise DataActivationError(f"{label} does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataActivationError(f"cannot read {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise DataActivationError(f"{label} root must be an object")
    return payload


def _required_mapping(payload: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise DataActivationError(f"{label} {key} must be an object")
    return value


def _required_text(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DataActivationError(f"{label} {key} must be non-empty text")
    return value.strip()


def _required_date(payload: dict[str, Any], key: str, label: str) -> date:
    value = _required_text(payload, key, label)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DataActivationError(f"{label} {key} must be an ISO date") from exc


def _optional_digest(payload: dict[str, Any], key: str, label: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 64:
        raise DataActivationError(f"{label} {key} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise DataActivationError(f"{label} {key} must be a SHA-256 digest") from exc
    return value.lower()


def _required_digest(payload: dict[str, Any], key: str, label: str) -> str:
    value = _optional_digest(payload, key, label)
    if value is None:
        raise DataActivationError(f"{label} {key} is required")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_same_or_descendant(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
