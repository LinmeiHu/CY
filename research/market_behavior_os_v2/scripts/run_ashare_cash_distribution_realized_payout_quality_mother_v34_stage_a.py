#!/usr/bin/env python3
"""Build the outcome-blind V34 realized-cash-payout mother population."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

EXPERIMENT = "ASHARE-CASH-DISTRIBUTION-REALIZED-PAYOUT-QUALITY-MOTHER-V34"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
REGISTRY = REPO / "configs/data_asset_registry.json"
ACTION_ID_CONTRACT = REPO / "src/cyq_game/chip/price_coordinate.py"
CY045_MANIFEST = REPO / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-V34-CY045_DATA_ASSET_MANIFEST.json"
)

ASSET_ID = "CY-045"
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-CASH-DISTRIBUTION-PAYOUT-QUALITY-"
    "V34-STAGE-A-2018-2020-V1"
)
AUTHORIZATION_PURPOSE = "ASHARE_OUTCOME_BLIND_MOTHER_REPRESENTATION"
AUTHORIZED_ARM = "V34_FROZEN_OUTCOME_BLIND_STAGE_A_ONLY"
MANIFEST_STATUS = "FROZEN_OUTCOME_BLIND_MOTHER_REPRESENTATION_BOUNDED_INPUT"

QD010_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/staging/"
    "crsp_lean_corporate_actions_enrichment_20260809_v2/vintages/"
    "official_full_sh_sz_current_snapshot_20260809_v5"
)
QD010_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/QD-010-cninfo-actions-20260820.json"
)
QD010_MANIFEST = QD010_ROOT / "manifest.json"
QD010_DISTRIBUTIONS = QD010_ROOT / "normalized/distributions.parquet"
QD010_RIGHTS = QD010_ROOT / "normalized/rights_issues.parquet"

CY006_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
CY006_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
PARTITIONS = tuple(
    CY006_ROOT / f"partition_year={year}/data_0.parquet" for year in range(2018, 2021)
)

OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_cash_distribution_realized_payout_quality_mother_v34"
)
STAGE_A = OUTPUT_ROOT / "stage_a"

EXPECTED_SPEC = "86adf9667245638671ec9c4b733ff47fbd16abd20306d3f4c2bc048a394e489d"
EXPECTED_FILES = {
    ACTION_ID_CONTRACT: "60c9f80fcaa2bf4a6ebfaab37bc56e81dd716cc3bea00891b4fc28d077dd1726",
    QD010_INVENTORY: "e1ca622ee227ce308b44933160754d450b80d3ecca79c1470037558e1011ceb8",
    QD010_MANIFEST: "d57afb7826aa87c3929367a989a369f087a7ecf05f1026bcfed751600a3e884c",
    QD010_DISTRIBUTIONS: "5982b7dd75ec53deb9ce3874aaf3e4a5168a731b5bbd6d8c2d89258fe4aff387",
    QD010_RIGHTS: "07e864ac6da1d59b69c1b9ce1bcdd01d96d913d0909a718d79627939f8ab87cb",
    CY006_INVENTORY: "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    PARTITIONS[0]: "b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4",
    PARTITIONS[1]: "c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd",
    PARTITIONS[2]: "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62",
}
BOUND_INPUT_ROLES = (
    ("corporate_action_id_contract", ACTION_ID_CONTRACT),
    ("qd010_inventory", QD010_INVENTORY),
    ("qd010_source_manifest", QD010_MANIFEST),
    ("qd010_distributions", QD010_DISTRIBUTIONS),
    ("qd010_rights", QD010_RIGHTS),
    ("cy006_inventory", CY006_INVENTORY),
    ("cy006_2018", PARTITIONS[0]),
    ("cy006_2019", PARTITIONS[1]),
    ("cy006_2020", PARTITIONS[2]),
)

SIGNAL_START = pd.Timestamp("2018-01-01")
SIGNAL_END = pd.Timestamp("2020-12-31")
YEARS = (2018, 2019, 2020)
MIN_CASH_YIELD = 0.02
COOLDOWN_SESSIONS = 120
MIN_ANNUAL_CANDIDATES_EXCLUSIVE = 50
MIN_ANNUAL_INDUSTRIES = 20
FLOAT_TOLERANCE = 1e-12
MARKET_SYMBOL = re.compile(r"^[0-9]{6}[.](SH|SZ)$")


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, PIT timing, source or semantic drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
        raise ResearchError(f"missing or duplicate registry authorization: {authorization_id}")
    return matches[0]


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResearchError(f"{label} must be one JSON object")
    return value


def expected_input_bindings() -> dict[str, dict[str, str]]:
    return {
        role: {"path": str(path), "sha256": EXPECTED_FILES[path]}
        for role, path in BOUND_INPUT_ROLES
    }


def expected_stage_a_binding(spec_hash: str, runner_hash: str) -> dict[str, Any]:
    return {
        "spec": {"path": str(SPEC), "sha256": spec_hash},
        "runner": {
            "path": str(Path(__file__).resolve()),
            "sha256": runner_hash,
        },
        "inputs": expected_input_bindings(),
    }


def require_bound_artifacts(items: object) -> None:
    if not isinstance(items, list):
        raise ResearchError("CY-045 bound_artifacts must be a list")
    observed: dict[str, dict[str, str]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            raise ResearchError("CY-045 bound_artifacts contains a malformed row")
        role = item["role"]
        if role in observed:
            raise ResearchError(f"duplicate CY-045 bound artifact role: {role}")
        observed[role] = {
            "path": item.get("path"),
            "sha256": item.get("sha256"),
        }
    if observed != expected_input_bindings():
        raise ResearchError("CY-045 does not bind the exact complete Stage-A input set")


def verify_central_authorization() -> tuple[dict[str, str], dict[str, Any]]:
    """Authorize V34 before any source Parquet is statted, hashed or opened."""

    runner = Path(__file__).resolve()
    required_public = (SPEC, REGISTRY, CY045_MANIFEST, runner)
    missing = [str(path) for path in required_public if not path.is_file()]
    if missing:
        raise ResearchError(f"missing V34 public authorization input: {missing}")
    public_hashes = {
        str(SPEC): sha256(SPEC),
        str(REGISTRY): sha256(REGISTRY),
        str(CY045_MANIFEST): sha256(CY045_MANIFEST),
        str(runner): sha256(runner),
    }
    if public_hashes[str(SPEC)] != EXPECTED_SPEC:
        raise ResearchError("V34 frozen spec hash drift")

    registry = load_json_object(REGISTRY, "data asset registry")
    asset = _one_asset(registry, ASSET_ID)
    authorization = _one_authorization(registry, AUTHORIZATION_ID)
    manifest = load_json_object(CY045_MANIFEST, "CY-045 manifest")
    binding = expected_stage_a_binding(
        public_hashes[str(SPEC)], public_hashes[str(runner)]
    )
    manifest_hash = public_hashes[str(CY045_MANIFEST)]
    lineage = asset.get("lineage", {})
    scope = authorization.get("scope", {})
    bound_manifest = authorization.get("bound_manifest", {})
    protocol = authorization.get("bound_protocol", {})
    boundary = manifest.get("authorization_boundary", {})
    expected_scope = {
        "project": "research/market_behavior_os_v2",
        "start": str(SIGNAL_START.date()),
        "end": str(SIGNAL_END.date()),
        "signal_start": str(SIGNAL_START.date()),
        "signal_end": str(SIGNAL_END.date()),
        "maximum_source_row_date": str(SIGNAL_END.date()),
    }
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
    required_true = (
        "stage_a_authorized",
        "whole_artifact_hash_authorized",
        "inventory_metadata_parse_authorized",
        "source_parquet_stage_a_parse_authorized",
    )
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or lineage.get("immutable_manifest") is not True
        or lineage.get("manifest_path") != str(CY045_MANIFEST)
        or lineage.get("manifest_sha256") != manifest_hash
        or set(lineage.get("component_assets", [])) != {"QD-010", "CY-006"}
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
        or asset.get("stage_a_binding") != binding
    ):
        raise ResearchError("CY-045 registry asset binding drift")
    if (
        authorization.get("purpose") != AUTHORIZATION_PURPOSE
        or authorization.get("asset_id") != ASSET_ID
        or authorization.get("authorized_arms") != [AUTHORIZED_ARM]
        or any(authorization.get(key) is not True for key in required_true)
        or any(authorization.get(key) is not False for key in required_false)
        or any(scope.get(key) != value for key, value in expected_scope.items())
        or bound_manifest.get("path") != str(CY045_MANIFEST)
        or bound_manifest.get("sha256") != manifest_hash
        or protocol.get("path") != str(SPEC)
        or protocol.get("sha256") != public_hashes[str(SPEC)]
        or protocol.get("runner_path") != str(runner)
        or protocol.get("runner_sha256") != public_hashes[str(runner)]
        or authorization.get("stage_a_binding") != binding
    ):
        raise ResearchError("CY-045 bounded authorization semantics drift")
    require_bound_artifacts(authorization.get("bound_artifacts"))
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
        raise ResearchError("CY-045 manifest authorization semantics drift")
    require_bound_artifacts(manifest.get("bound_artifacts"))
    return public_hashes, registry


def verify_inputs(
    public_hashes: dict[str, str], registry: dict[str, Any]
) -> dict[str, str]:
    """Hash and inspect source inputs only after CY-045 jointly authorizes them."""

    actual = dict(public_hashes)
    for path, expected_hash in EXPECTED_FILES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        observed = sha256(path)
        actual[str(path)] = observed
        if observed != expected_hash:
            raise ResearchError(f"frozen input drift: {path}: {observed} != {expected_hash}")

    qd010 = _one_asset(registry, "QD-010")
    qd010_lineage = qd010.get("lineage", {})
    if (
        qd010.get("status") != "RESEARCH_CONDITIONAL"
        or qd010.get("pit_grade") != "B"
        or qd010_lineage.get("immutable_manifest") is not True
        or qd010_lineage.get("manifest_path") != str(QD010_INVENTORY)
        or qd010_lineage.get("manifest_sha256") != EXPECTED_FILES[QD010_INVENTORY]
        or "bounded PIT-B causal research adaptation" not in qd010.get("allowed_uses", [])
        or qd010.get("quality_evidence", {}).get("strict_pit_eligible") is not False
    ):
        raise ResearchError("QD-010 registry semantics drift")

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
    ):
        raise ResearchError("CY-006 registry semantics drift")

    qd010_inventory = json.loads(QD010_INVENTORY.read_text(encoding="utf-8"))
    qd010_entries = {item["path"]: item["sha256"] for item in qd010_inventory["files"]}
    if qd010_inventory.get("root") != str(QD010_ROOT):
        raise ResearchError("QD-010 inventory root drift")
    for path in (QD010_MANIFEST, QD010_DISTRIBUTIONS, QD010_RIGHTS):
        relative = str(path.relative_to(QD010_ROOT))
        if qd010_entries.get(relative) != EXPECTED_FILES[path]:
            raise ResearchError(f"QD-010 inventory entry drift: {relative}")

    cy006_inventory = json.loads(CY006_INVENTORY.read_text(encoding="utf-8"))
    cy006_entries = {item["path"]: item["sha256"] for item in cy006_inventory["files"]}
    if cy006_inventory.get("root") != str(CY006_ROOT):
        raise ResearchError("CY-006 inventory root drift")
    for path in PARTITIONS:
        relative = str(path.relative_to(CY006_ROOT))
        if cy006_entries.get(relative) != EXPECTED_FILES[path]:
            raise ResearchError(f"CY-006 inventory entry drift: {relative}")

    return actual


def connect(temporary: Path) -> duckdb.DuckDBPyConnection:
    temporary.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=2")
    connection.execute("SET memory_limit='8GB'")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute(f"SET temp_directory='{temporary.as_posix()}'")
    connection.from_parquet([str(path) for path in PARTITIONS], union_by_name=True).create_view(
        "cy006"
    )
    return connection


CanonicalActionIdParser = Callable[[object], tuple[str, ...]]


def load_canonical_action_id_parser() -> CanonicalActionIdParser:
    """Load the hash-bound repository parser only after input authorization."""

    module_spec = importlib.util.spec_from_file_location(
        "v34_bound_price_coordinate", ACTION_ID_CONTRACT
    )
    if module_spec is None or module_spec.loader is None:
        raise ResearchError("cannot load the hash-bound corporate-action parser")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    parser = getattr(module, "parse_action_ids", None)
    if not callable(parser):
        raise ResearchError("hash-bound price-coordinate module lacks parse_action_ids")
    return parser


def normalize_market_symbol(raw: object) -> str | None:
    value = str(raw).strip().upper()
    if MARKET_SYMBOL.fullmatch(value):
        return value
    if not re.fullmatch(r"[0-9]{6}", value):
        return None
    if value.startswith("6"):
        return f"{value}.SH"
    if value.startswith(("0", "3")):
        return f"{value}.SZ"
    return None


def parse_corporate_action_ids(
    raw: object, canonical_parser: CanonicalActionIdParser
) -> tuple[str, ...]:
    """Parse the frozen CY-006 action-id aggregate without losing multiplicity.

    The accepted wire forms are the repository contract's JSON-list, pipe-delimited
    string, or an in-memory list/tuple.  Empty and missing values mean no actions.
    Malformed values, empty members and duplicate members fail closed rather than
    being normalized away.
    """

    if isinstance(raw, (float, np.floating)) and np.isnan(raw):
        raise ResearchError("corporate_action_ids cannot be NaN")
    if raw is None:
        canonical_wire: object = None
        values: list[object] = []
    elif isinstance(raw, str):
        # The repository contract strips only the overall wire string.  V34 then
        # rejects any padded member before invoking that canonical parser.
        canonical_wire = raw.strip()
        if not canonical_wire:
            values = []
        elif canonical_wire.startswith("["):
            try:
                decoded = json.loads(canonical_wire)
            except json.JSONDecodeError as exc:
                raise ResearchError("invalid corporate_action_ids JSON") from exc
            if not isinstance(decoded, list):
                raise ResearchError("corporate_action_ids JSON must be a list")
            values = decoded
        else:
            values = canonical_wire.split("|")
    elif isinstance(raw, (list, tuple)):
        canonical_wire = raw
        values = list(raw)
    else:
        raise ResearchError("corporate_action_ids has an unsupported encoded type")

    if any(
        value is None
        or (isinstance(value, (float, np.floating)) and np.isnan(value))
        for value in values
    ):
        raise ResearchError("corporate_action_ids contains a null or NaN member")
    members = [str(value) for value in values]
    if any(not value or value != value.strip() for value in members):
        raise ResearchError("corporate_action_ids contains an empty or padded member")
    if len(members) != len(set(members)):
        raise ResearchError("corporate_action_ids contains duplicate members")
    try:
        parsed = canonical_parser(canonical_wire)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ResearchError("canonical corporate_action_ids parse failed") from exc
    expected = tuple(sorted(members))
    if parsed != expected:
        raise ResearchError("canonical corporate_action_ids parser changed strict members")
    return parsed


def _date_mask(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    return parsed.ge(SIGNAL_START) & parsed.le(SIGNAL_END)


def load_action_rows(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    distributions = connection.execute(
        """
        SELECT security_id,symbol,event_id,source_event_key,row_hash,announcement_date,
          known_at,effective_date,cash_per_share_gross,share_multiplier,
          rights_subscription_ratio,source_terms_complete,revision_history_complete,
          strict_pit_eligible,revision_ordinal,is_new_event,is_changed_from_previous,
          previous_revision_id,vintage_id
        FROM read_parquet(?)
        WHERE CAST(effective_date AS DATE)>=DATE '2018-01-01'
          AND CAST(effective_date AS DATE)<=DATE '2020-12-31'
        ORDER BY effective_date,symbol,event_id
        """,
        [str(QD010_DISTRIBUTIONS)],
    ).fetchdf()
    rights = connection.execute(
        """
        SELECT symbol,event_id,source_event_key,known_at,effective_date,source_terms_complete,
          revision_ordinal,is_new_event,is_changed_from_previous,previous_revision_id
        FROM read_parquet(?)
        WHERE CAST(effective_date AS DATE)>=DATE '2018-01-01'
          AND CAST(effective_date AS DATE)<=DATE '2020-12-31'
        ORDER BY effective_date,symbol,event_id
        """,
        [str(QD010_RIGHTS)],
    ).fetchdf()

    for frame in (distributions, rights):
        frame["known_at"] = pd.to_datetime(frame.known_at, errors="coerce")
        frame["effective_date"] = pd.to_datetime(frame.effective_date, errors="coerce")
    distributions["announcement_date"] = pd.to_datetime(
        distributions.announcement_date, errors="coerce"
    )

    if not _date_mask(distributions.effective_date).all():
        raise ResearchError("post-2020 or pre-2018 distribution row entered Stage A")
    if len(rights) and not _date_mask(rights.effective_date).all():
        raise ResearchError("post-2020 or pre-2018 rights row entered Stage A")

    distributions["market_symbol"] = distributions.symbol.map(normalize_market_symbol)
    rights["market_symbol"] = rights.symbol.map(normalize_market_symbol)

    previous_revision_present = distributions.previous_revision_id.fillna("").astype(str).ne("")
    revision_conflict = (
        pd.to_numeric(distributions.revision_ordinal, errors="coerce").ne(1)
        | distributions.is_new_event.ne(True)
        | distributions.is_changed_from_previous.eq(True)
        | previous_revision_present
    )
    distribution_identity = distributions[["event_id", "source_event_key", "row_hash", "symbol"]]
    missing_identity = distribution_identity.isna().any(axis=1) | distribution_identity.apply(
        lambda column: column.astype(str).str.strip().eq("")
    ).any(axis=1)
    event_id_text = distributions.event_id.astype(str)
    noncanonical_event_id = distributions.event_id.isna() | event_id_text.ne(
        event_id_text.str.strip()
    )
    duplicate_event_ids = int(distributions.event_id.duplicated(keep=False).sum())
    duplicate_source_event_keys = int(distributions.source_event_key.duplicated(keep=False).sum())
    if duplicate_event_ids or duplicate_source_event_keys:
        raise ResearchError(
            "QD-010 duplicate event identity in the frozen 2018-2020 slice: "
            f"event_id_rows={duplicate_event_ids}, "
            f"source_event_key_rows={duplicate_source_event_keys}"
        )
    if (
        int(revision_conflict.sum())
        or int(missing_identity.sum())
        or int(noncanonical_event_id.sum())
    ):
        raise ResearchError(
            "QD-010 revision/identity conflict in the frozen 2018-2020 slice: "
            f"revision_rows={int(revision_conflict.sum())}, "
            f"missing_identity_rows={int(missing_identity.sum())}, "
            f"noncanonical_event_id_rows={int(noncanonical_event_id.sum())}"
        )

    rights_previous_revision_present = rights.previous_revision_id.fillna("").astype(str).ne("")
    rights_revision_conflict = (
        pd.to_numeric(rights.revision_ordinal, errors="coerce").ne(1)
        | rights.is_new_event.ne(True)
        | rights.is_changed_from_previous.eq(True)
        | rights_previous_revision_present
    )
    rights_identity = rights[["event_id", "source_event_key", "symbol"]]
    rights_missing_identity = rights_identity.isna().any(axis=1) | rights_identity.apply(
        lambda column: column.astype(str).str.strip().eq("")
    ).any(axis=1)
    rights_duplicate_event_ids = int(rights.event_id.duplicated(keep=False).sum())
    rights_duplicate_source_event_keys = int(rights.source_event_key.duplicated(keep=False).sum())
    if (
        rights_duplicate_event_ids
        or rights_duplicate_source_event_keys
        or int(rights_revision_conflict.sum())
        or int(rights_missing_identity.sum())
    ):
        raise ResearchError(
            "QD-010 rights identity/revision conflict in the frozen 2018-2020 slice: "
            f"event_id_rows={rights_duplicate_event_ids}, "
            f"source_event_key_rows={rights_duplicate_source_event_keys}, "
            f"revision_rows={int(rights_revision_conflict.sum())}, "
            f"missing_identity_rows={int(rights_missing_identity.sum())}"
        )

    distributions["effective_day"] = distributions.effective_date.dt.normalize()
    rights["effective_day"] = rights.effective_date.dt.normalize()
    symbol_day_counts = distributions.groupby(
        ["market_symbol", "effective_day"], dropna=False
    ).event_id.transform("size")
    rights_days = set(zip(rights.market_symbol, rights.effective_day, strict=False))
    distributions["distribution_rows_same_symbol_day"] = symbol_day_counts.astype(int)
    distributions["rights_collision_same_symbol_day"] = [
        (symbol, day) in rights_days
        for symbol, day in zip(
            distributions.market_symbol, distributions.effective_day, strict=False
        )
    ]

    cash = pd.to_numeric(distributions.cash_per_share_gross, errors="coerce")
    multiplier = pd.to_numeric(distributions.share_multiplier, errors="coerce")
    rights_ratio = pd.to_numeric(distributions.rights_subscription_ratio, errors="coerce")
    pure = (
        np.isfinite(cash)
        & cash.gt(0)
        & np.isfinite(multiplier)
        & multiplier.eq(1.0)
        & np.isfinite(rights_ratio)
        & rights_ratio.eq(0.0)
        & distributions.source_terms_complete.eq(True)
        & distributions.known_at.notna()
        & distributions.effective_date.notna()
        & distributions.distribution_rows_same_symbol_day.eq(1)
        & ~distributions.rights_collision_same_symbol_day
    )
    eligible_actions = distributions.loc[pure].copy()
    eligible_actions["cash_per_share_gross"] = cash.loc[pure].astype(float)
    eligible_actions["share_multiplier"] = multiplier.loc[pure].astype(float)
    eligible_actions["rights_subscription_ratio"] = rights_ratio.loc[pure].astype(float)

    audit: dict[str, Any] = {
        "distribution_rows_2018_2020": len(distributions),
        "rights_rows_2018_2020": len(rights),
        "first_distribution_effective_date": (
            None if distributions.empty else str(distributions.effective_day.min().date())
        ),
        "last_distribution_effective_date": (
            None if distributions.empty else str(distributions.effective_day.max().date())
        ),
        "missing_known_at_rows": int(distributions.known_at.isna().sum()),
        "missing_effective_date_rows": int(distributions.effective_date.isna().sum()),
        "duplicate_event_id_rows": duplicate_event_ids,
        "duplicate_source_event_key_rows": duplicate_source_event_keys,
        "revision_conflict_rows": int(revision_conflict.sum()),
        "missing_identity_rows": int(missing_identity.sum()),
        "noncanonical_event_id_rows": int(noncanonical_event_id.sum()),
        "unmapped_market_symbol_rows": int(distributions.market_symbol.isna().sum()),
        "rights_duplicate_event_id_rows": rights_duplicate_event_ids,
        "rights_duplicate_source_event_key_rows": rights_duplicate_source_event_keys,
        "rights_revision_conflict_rows": int(rights_revision_conflict.sum()),
        "rights_missing_identity_rows": int(rights_missing_identity.sum()),
        "rights_unmapped_market_symbol_rows": int(rights.market_symbol.isna().sum()),
        "source_terms_incomplete_rows": int(distributions.source_terms_complete.ne(True).sum()),
        "non_cash_or_nonpositive_cash_rows": int((~(np.isfinite(cash) & cash.gt(0))).sum()),
        "share_multiplier_not_one_rows": int(
            (~(np.isfinite(multiplier) & multiplier.eq(1.0))).sum()
        ),
        "distribution_rights_ratio_not_zero_rows": int(
            (~(np.isfinite(rights_ratio) & rights_ratio.eq(0.0))).sum()
        ),
        "nonunique_distribution_symbol_day_rows": int(symbol_day_counts.ne(1).sum()),
        "rights_collision_symbol_day_rows": int(
            distributions.rights_collision_same_symbol_day.sum()
        ),
        "pure_cash_unique_nonrights_rows": len(eligible_actions),
        "revision_history_complete_true_rows": int(
            distributions.revision_history_complete.eq(True).sum()
        ),
        "strict_pit_eligible_true_rows": int(distributions.strict_pit_eligible.eq(True).sum()),
        "known_snapshot_limitation": (
            "QD-010 is a frozen current historical snapshot; revision_history_complete "
            "and strict_pit_eligible are not required or claimed by this bounded PIT-B gate."
        ),
    }
    return eligible_actions, rights, audit


def load_event_date_rows(
    connection: duckdb.DuckDBPyConnection,
    actions: pd.DataFrame,
    canonical_parser: CanonicalActionIdParser,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    source = connection.execute(
        """
        SELECT count(*) AS rows,
          count(*)-count(DISTINCT (trade_date,symbol)) AS duplicate_keys,
          count(*) FILTER (WHERE hard_valid AND available_at>decision_at)
            AS hard_valid_time_travel_rows,
          min(trade_date) AS first_date,max(trade_date) AS last_date
        FROM cy006
        WHERE trade_date>=DATE '2018-01-01' AND trade_date<=DATE '2020-12-31'
        """
    ).fetchone()
    if source[3] is None or pd.Timestamp(source[4]) > SIGNAL_END:
        raise ResearchError(f"CY-006 Stage-A date cap failed: {source[3:5]}")
    if int(source[1]) or int(source[2]):
        raise ResearchError(
            "CY-006 source audit failed: "
            f"duplicate_keys={int(source[1])}, time_travel={int(source[2])}"
        )

    connection.execute(
        """
        CREATE TEMP TABLE v34_calendar AS
        SELECT trade_date,row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
        FROM (
          SELECT DISTINCT trade_date FROM cy006
          WHERE trade_date>=DATE '2018-01-01' AND trade_date<=DATE '2020-12-31'
        )
        """
    )
    selected = actions[
        [
            "event_id",
            "source_event_key",
            "row_hash",
            "market_symbol",
            "announcement_date",
            "known_at",
            "effective_day",
            "cash_per_share_gross",
            "vintage_id",
        ]
    ].copy()
    selected = selected.rename(columns={"effective_day": "signal_date"})
    connection.register("v34_actions", selected)
    joined = connection.execute(
        """
        SELECT a.event_id AS qd010_event_id,a.source_event_key,a.row_hash AS source_row_hash,
          a.market_symbol AS symbol,CAST(a.signal_date AS DATE) AS signal_date,
          a.announcement_date,a.known_at,a.cash_per_share_gross,a.vintage_id,
          c.cal_idx,d.decision_at,d.available_at,d.industry,d.preclose,
          d.circulating_shares,d.turnover_fraction,d.trade_status,d.is_st,
          d.current_day_data_tradable,d.hard_valid,d.bar_valid,d.trading_state_valid,
          d.industry_valid,d.float_valid,d.corporate_action_valid,
          d.corporate_action_blocking,d.market_valid,d.market_rule_valid,
          d.historical_identity_valid,d.corporate_action_count,d.corporate_action_ids,
          d.corporate_action_available_date,d.share_multiplier AS cy006_share_multiplier,
          d.cash_per_share AS cy006_cash_per_share,d.rights_ratio AS cy006_rights_ratio,
          d.snapshot_id,d.daily_snapshot_id,d.trading_state_snapshot_id,
          d.industry_snapshot_id,d.float_snapshot_id,d.corporate_action_snapshot_id,
          d.market_snapshot_id
        FROM v34_actions a
        LEFT JOIN cy006 d
          ON d.symbol=a.market_symbol AND d.trade_date=CAST(a.signal_date AS DATE)
        LEFT JOIN v34_calendar c ON c.trade_date=d.trade_date
        ORDER BY signal_date,symbol,qd010_event_id
        """
    ).fetchdf()
    if len(joined) != len(selected):
        raise ResearchError("QD-010 to CY-006 join changed action-row cardinality")

    joined["signal_date"] = pd.to_datetime(joined.signal_date, errors="coerce")
    joined["decision_at"] = pd.to_datetime(joined.decision_at, errors="coerce")
    joined["available_at"] = pd.to_datetime(joined.available_at, errors="coerce")
    joined["known_at"] = pd.to_datetime(joined.known_at, errors="coerce")
    joined["corporate_action_available_date"] = pd.to_datetime(
        joined.corporate_action_available_date, errors="coerce"
    )
    if not _date_mask(joined.signal_date).all():
        raise ResearchError("joined Stage-A row escaped the frozen date range")

    parsed_action_ids: list[tuple[str, ...]] = []
    action_id_parse_error: list[bool] = []
    for raw_ids in joined.corporate_action_ids:
        try:
            parsed_action_ids.append(parse_corporate_action_ids(raw_ids, canonical_parser))
            action_id_parse_error.append(False)
        except ResearchError:
            parsed_action_ids.append(())
            action_id_parse_error.append(True)
    joined["cy006_corporate_action_ids_canonical"] = [
        "|".join(values) for values in parsed_action_ids
    ]
    action_id_parse_error_mask = pd.Series(
        action_id_parse_error, index=joined.index, dtype=bool
    )
    action_id_exact_match = pd.Series(
        [
            (not parse_failed)
            and isinstance(event_id, str)
            and bool(event_id)
            and event_id == event_id.strip()
            and ids == (event_id,)
            for ids, event_id, parse_failed in zip(
                parsed_action_ids,
                joined.qd010_event_id,
                action_id_parse_error,
                strict=True,
            )
        ],
        index=joined.index,
        dtype=bool,
    )
    joined["event_action_identity_exact_match"] = action_id_exact_match

    required_snapshots = [
        "snapshot_id",
        "daily_snapshot_id",
        "trading_state_snapshot_id",
        "industry_snapshot_id",
        "float_snapshot_id",
        "corporate_action_snapshot_id",
        "market_snapshot_id",
    ]
    booleans = [
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
    ]
    numeric = {
        name: pd.to_numeric(joined[name], errors="coerce")
        for name in (
            "preclose",
            "circulating_shares",
            "turnover_fraction",
            "corporate_action_count",
            "cy006_share_multiplier",
            "cy006_cash_per_share",
            "cy006_rights_ratio",
        )
    }
    board_valid = joined.symbol.str.match(
        r"^(600|601|603|605)[0-9]{3}[.]SH$|^(000|001|002|300|301)[0-9]{3}[.]SZ$",
        na=False,
    )
    daily_row_present = joined.cal_idx.notna() & joined.decision_at.notna()
    industry_nonblank = (
        joined.industry.notna() & joined.industry.astype(str).str.strip().ne("")
    )
    required_snapshots_nonblank = pd.Series(True, index=joined.index, dtype=bool)
    for column in required_snapshots:
        required_snapshots_nonblank &= (
            joined[column].notna() & joined[column].astype(str).str.strip().ne("")
        )
    daily_valid = (
        daily_row_present
        & board_valid
        & joined[booleans].eq(True).all(axis=1)
        & joined.corporate_action_blocking.eq(False)
        & joined.trade_status.eq(1)
        & joined.is_st.eq(False)
        & joined.available_at.notna()
        & joined.available_at.le(joined.decision_at)
        & industry_nonblank
        & required_snapshots_nonblank
        & np.isfinite(numeric["preclose"])
        & numeric["preclose"].gt(0)
        & np.isfinite(numeric["circulating_shares"])
        & numeric["circulating_shares"].gt(0)
        & np.isfinite(numeric["turnover_fraction"])
        & numeric["turnover_fraction"].gt(0)
    )
    action_consistent = (
        numeric["corporate_action_count"].eq(1)
        & ~action_id_parse_error_mask
        & action_id_exact_match
        & np.isfinite(numeric["cy006_share_multiplier"])
        & numeric["cy006_share_multiplier"].eq(1.0)
        & np.isfinite(numeric["cy006_rights_ratio"])
        & numeric["cy006_rights_ratio"].eq(0.0)
        & np.isfinite(numeric["cy006_cash_per_share"])
        & np.isclose(
            numeric["cy006_cash_per_share"],
            pd.to_numeric(joined.cash_per_share_gross, errors="coerce"),
            rtol=0.0,
            atol=FLOAT_TOLERANCE,
        )
        & joined.corporate_action_available_date.notna()
        & joined.corporate_action_available_date.le(joined.signal_date)
    )
    known_by_decision = joined.known_at.notna() & joined.known_at.le(joined.decision_at)
    cash_yield = pd.to_numeric(joined.cash_per_share_gross, errors="coerce") / numeric["preclose"]
    yield_valid = np.isfinite(cash_yield) & cash_yield.ge(MIN_CASH_YIELD)
    admitted = daily_valid & action_consistent & known_by_decision & yield_valid

    joined["cash_yield"] = cash_yield.astype(float)
    joined["circulating_market_value_cny"] = numeric["preclose"] * numeric["circulating_shares"]
    representation = joined.loc[admitted].copy()
    representation["cal_idx"] = representation.cal_idx.astype(int)
    representation["mother_event_id"] = (
        "CASH_PAYOUT_QUALITY|"
        + representation.qd010_event_id.astype(str)
        + "|"
        + representation.signal_date.dt.strftime("%Y%m%d")
        + "|"
        + representation.symbol.astype(str)
    )
    representation = representation[
        [
            "mother_event_id",
            "qd010_event_id",
            "source_event_key",
            "source_row_hash",
            "symbol",
            "signal_date",
            "cal_idx",
            "decision_at",
            "known_at",
            "announcement_date",
            "industry",
            "cash_per_share_gross",
            "preclose",
            "cash_yield",
            "circulating_market_value_cny",
            "turnover_fraction",
            "cy006_corporate_action_ids_canonical",
            "event_action_identity_exact_match",
            "vintage_id",
            "snapshot_id",
            "daily_snapshot_id",
            "trading_state_snapshot_id",
            "industry_snapshot_id",
            "float_snapshot_id",
            "corporate_action_snapshot_id",
            "market_snapshot_id",
        ]
    ].sort_values(["signal_date", "symbol", "qd010_event_id"], kind="mergesort")
    representation = representation.reset_index(drop=True)

    audit: dict[str, Any] = {
        "cy006_rows_2018_2020": int(source[0]),
        "cy006_duplicate_symbol_date_keys": int(source[1]),
        "cy006_hard_valid_time_travel_rows": int(source[2]),
        "cy006_first_date": str(pd.Timestamp(source[3]).date()),
        "cy006_last_date": str(pd.Timestamp(source[4]).date()),
        "pure_action_rows_submitted_to_join": len(joined),
        "missing_event_date_cy006_rows": int((~daily_row_present).sum()),
        "invalid_event_date_cy006_rows": int((daily_row_present & ~daily_valid).sum()),
        "event_date_action_inconsistency_rows": int((daily_row_present & ~action_consistent).sum()),
        "target_board_action_rows": int(board_valid.sum()),
        "target_board_missing_event_date_cy006_rows": int(
            (board_valid & ~daily_row_present).sum()
        ),
        "target_board_invalid_event_date_cy006_rows": int(
            (board_valid & daily_row_present & ~daily_valid).sum()
        ),
        "target_board_event_date_action_inconsistency_rows": int(
            (board_valid & daily_row_present & ~action_consistent).sum()
        ),
        "target_board_blank_industry_rows": int(
            (board_valid & daily_row_present & ~industry_nonblank).sum()
        ),
        "target_board_blank_required_snapshot_rows": int(
            (board_valid & daily_row_present & ~required_snapshots_nonblank).sum()
        ),
        "target_board_action_id_parse_error_rows": int(
            (board_valid & daily_row_present & action_id_parse_error_mask).sum()
        ),
        "target_board_action_id_exact_mismatch_rows": int(
            (board_valid & daily_row_present & ~action_id_exact_match).sum()
        ),
        "action_id_encoding_contract": {
            "path": str(ACTION_ID_CONTRACT),
            "sha256": EXPECTED_FILES[ACTION_ID_CONTRACT],
            "accepted_wire_forms": ["JSON_LIST", "PIPE_DELIMITED_STRING", "LIST_OR_TUPLE"],
            "duplicates_or_empty_members": "FAIL_CLOSED",
            "required_event_day_identity": "EXACTLY_ONE_ID_EQUAL_TO_QD010_EVENT_ID",
        },
        "action_not_known_by_event_close_rows": int((daily_row_present & ~known_by_decision).sum()),
        "invalid_or_below_2pct_yield_rows": int((daily_row_present & ~yield_valid).sum()),
        "admitted_before_cooldown": len(representation),
        "maximum_joined_signal_date": (
            None if joined.empty else str(joined.signal_date.max().date())
        ),
        "signal_day_close_or_return_used_in_representation": False,
        "post_signal_rows_joined": False,
    }
    return representation, audit


def apply_cooldown(representation: pd.DataFrame) -> pd.DataFrame:
    ordered = representation.sort_values(
        ["symbol", "cal_idx", "qd010_event_id"], kind="mergesort"
    ).copy()
    keep = pd.Series(False, index=ordered.index, dtype=bool)
    last_retained: dict[str, int] = {}
    for index, row in ordered.iterrows():
        symbol = str(row.symbol)
        current = int(row.cal_idx)
        prior = last_retained.get(symbol)
        if prior is None or current - prior > COOLDOWN_SESSIONS:
            keep.loc[index] = True
            last_retained[symbol] = current
    ordered["retained_after_120_session_cooldown"] = keep
    return ordered.sort_values(
        ["signal_date", "symbol", "qd010_event_id"], kind="mergesort"
    ).reset_index(drop=True)


def distribution_summary(values: pd.Series) -> dict[str, float | int | None]:
    finite = pd.to_numeric(values, errors="coerce")
    finite = finite[np.isfinite(finite)]
    if finite.empty:
        return {
            "n": 0,
            "min": None,
            "p10": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
            "max": None,
            "mean": None,
        }
    quantiles = finite.quantile([0.10, 0.25, 0.50, 0.75, 0.90])
    return {
        "n": len(finite),
        "min": float(finite.min()),
        "p10": float(quantiles.loc[0.10]),
        "p25": float(quantiles.loc[0.25]),
        "median": float(quantiles.loc[0.50]),
        "p75": float(quantiles.loc[0.75]),
        "p90": float(quantiles.loc[0.90]),
        "max": float(finite.max()),
        "mean": float(finite.mean()),
    }


def safe_spearman(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any]:
    values = frame[[left, right]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(values) < 3 or values.nunique().min() < 3:
        return {"n": len(values), "rho": None}
    rho = values[left].corr(values[right], method="spearman")
    return {"n": len(values), "rho": None if pd.isna(rho) else float(rho)}


def collision_diagnostics(candidates: pd.DataFrame) -> dict[str, Any]:
    frame = candidates.copy()
    frame["log_preclose"] = np.log(frame.preclose)
    frame["log_circulating_market_value"] = np.log(frame.circulating_market_value_cny)
    frame["log_cash_per_share"] = np.log(frame.cash_per_share_gross)
    comparators = (
        "log_preclose",
        "log_circulating_market_value",
        "turnover_fraction",
        "log_cash_per_share",
    )
    output: dict[str, Any] = {
        "interpretation": (
            "Outcome-blind descriptive geometry only. These associations cannot add, "
            "remove or reorder a frozen V34 candidate."
        ),
        "overall": {
            comparator: safe_spearman(frame, "cash_yield", comparator) for comparator in comparators
        },
        "annual": {},
    }
    for year in YEARS:
        part = frame.loc[frame.signal_date.dt.year.eq(year)]
        output["annual"][str(year)] = {
            comparator: safe_spearman(part, "cash_yield", comparator) for comparator in comparators
        }
    return output


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    connection.close()


def summarize(
    representation: pd.DataFrame,
    candidates: pd.DataFrame,
    source_hashes: dict[str, str],
    action_audit: dict[str, Any],
    daily_audit: dict[str, Any],
    representation_path: Path,
    candidates_path: Path,
) -> dict[str, Any]:
    annual: dict[str, Any] = {}
    annual_passes: list[bool] = []
    for year in YEARS:
        before = representation.loc[representation.signal_date.dt.year.eq(year)]
        after = candidates.loc[candidates.signal_date.dt.year.eq(year)]
        industries = int(after.industry.nunique())
        count = len(after)
        gate = count > MIN_ANNUAL_CANDIDATES_EXCLUSIVE and industries >= MIN_ANNUAL_INDUSTRIES
        annual_passes.append(gate)
        annual[str(year)] = {
            "eligible_before_cooldown": len(before),
            "retained_candidates": count,
            "cooldown_drops": int(len(before) - len(after)),
            "unique_symbols": int(after.symbol.nunique()),
            "decision_dates": int(after.signal_date.nunique()),
            "pit_industries": industries,
            "cash_yield_distribution": distribution_summary(after.cash_yield),
            "candidate_count_gt_50": bool(count > MIN_ANNUAL_CANDIDATES_EXCLUSIVE),
            "industry_count_ge_20": bool(industries >= MIN_ANNUAL_INDUSTRIES),
            "annual_opportunity_gate_passed": bool(gate),
        }

    opportunity_pass = bool(all(annual_passes))
    semantic_pass = bool(
        action_audit["duplicate_event_id_rows"] == 0
        and action_audit["duplicate_source_event_key_rows"] == 0
        and action_audit["revision_conflict_rows"] == 0
        and action_audit["missing_identity_rows"] == 0
        and action_audit["noncanonical_event_id_rows"] == 0
        and action_audit["rights_duplicate_event_id_rows"] == 0
        and action_audit["rights_duplicate_source_event_key_rows"] == 0
        and action_audit["rights_revision_conflict_rows"] == 0
        and action_audit["rights_missing_identity_rows"] == 0
        and daily_audit["cy006_duplicate_symbol_date_keys"] == 0
        and daily_audit["cy006_hard_valid_time_travel_rows"] == 0
        and daily_audit["target_board_missing_event_date_cy006_rows"] == 0
        and daily_audit["target_board_event_date_action_inconsistency_rows"] == 0
        and daily_audit["target_board_blank_industry_rows"] == 0
        and daily_audit["target_board_blank_required_snapshot_rows"] == 0
        and daily_audit["target_board_action_id_parse_error_rows"] == 0
        and daily_audit["target_board_action_id_exact_mismatch_rows"] == 0
        and (
            daily_audit["maximum_joined_signal_date"] is None
            or daily_audit["maximum_joined_signal_date"] <= str(SIGNAL_END.date())
        )
        and daily_audit["post_signal_rows_joined"] is False
    )
    status = (
        "PASSED_OUTCOME_BLIND_OPPORTUNITY_GATE_STAGE_B_NOT_AUTHORIZED"
        if opportunity_pass
        else "FAILED_OPPORTUNITY_GATE_PERMANENTLY_CLOSED"
    )
    return {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_COUNT_AND_REPRESENTATION_GATE",
        "status": status,
        "frozen_definition": (
            "Pure QD-010 cash distribution; cash>0, share multiplier=1, rights ratio=0, "
            "complete unique terms, known by event-date close; valid tradable non-ST "
            "Main/ChiNext CY-006 row; cash/preclose>=2%; 120-session symbol cooldown."
        ),
        "source_hashes": source_hashes,
        "action_audit": action_audit,
        "daily_audit": daily_audit,
        "representation_rows": len(representation),
        "candidate_rows": len(candidates),
        "candidate_symbols": int(candidates.symbol.nunique()),
        "candidate_decision_dates": int(candidates.signal_date.nunique()),
        "candidate_pit_industries": int(candidates.industry.nunique()),
        "cash_yield_distribution": distribution_summary(candidates.cash_yield),
        "annual": annual,
        "collision_diagnostics": collision_diagnostics(candidates),
        "representation_sha256": sha256(representation_path),
        "candidates_sha256": sha256(candidates_path),
        "semantic_gate_passed": semantic_pass,
        "opportunity_gate_passed": opportunity_pass,
        "stage_a_gate_passed": bool(semantic_pass and opportunity_pass),
        "opportunity_gate_failure_publication_allowed": bool(
            semantic_pass and not opportunity_pass
        ),
        "semantic_failure_publication_allowed": False,
        "outcome_columns_read": False,
        "post_signal_rows_read": False,
        "post_2020_rows_read": False,
        "maximum_cy006_row_date": daily_audit["cy006_last_date"],
        "maximum_qd010_effective_date": action_audit["last_distribution_effective_date"],
        "stage_b_authorized": False,
        "chart_rendering_authorized": False,
        "portfolio_replay_authorized": False,
        "stage_b_and_charts_permanently_forbidden": bool(not opportunity_pass),
        "next_action": (
            "INDEPENDENTLY_AUDIT_STAGE_A_RESULT_THEN_FREEZE_A_SEPARATE_STAGE_B_CONTRACT"
            if semantic_pass and opportunity_pass
            else "PERMANENTLY_CLOSE_V34_BEFORE_ANY_FORWARD_OUTCOME_OR_CHART_READ"
        ),
    }


def main() -> None:
    public_hashes, registry = verify_central_authorization()
    source_hashes = verify_inputs(public_hashes, registry)
    if STAGE_A.exists() or STAGE_A.is_symlink():
        raise ResearchError(f"canonical V34 Stage A already exists: {STAGE_A}")
    canonical_parser = load_canonical_action_id_parser()
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".stage_a_staging_", dir=OUTPUT_ROOT))
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = connect(staging / "duckdb_tmp")
        actions, _rights, action_audit = load_action_rows(connection)
        base, daily_audit = load_event_date_rows(connection, actions, canonical_parser)
        connection.close()
        connection = None
        representation = apply_cooldown(base)
        candidates = representation.loc[representation.retained_after_120_session_cooldown].copy()
        candidates = candidates.drop(columns=["retained_after_120_session_cooldown"]).reset_index(
            drop=True
        )

        representation_path = staging / "representation_panel.parquet"
        candidates_path = staging / "candidates_frozen.parquet"
        write_parquet(representation, representation_path)
        write_parquet(candidates, candidates_path)
        result = summarize(
            representation,
            candidates,
            source_hashes,
            action_audit,
            daily_audit,
            representation_path,
            candidates_path,
        )
        (staging / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        shutil.rmtree(staging / "duckdb_tmp", ignore_errors=True)
        if result["semantic_gate_passed"] is not True:
            raise ResearchError(
                "V34 semantic/PIT/input gate failed; canonical Stage A publication forbidden"
            )
        final_public_hashes, final_registry = verify_central_authorization()
        final_source_hashes = verify_inputs(final_public_hashes, final_registry)
        if final_source_hashes != source_hashes:
            raise ResearchError("a frozen V34 input changed during Stage A")
        if STAGE_A.exists() or STAGE_A.is_symlink():
            raise ResearchError(
                f"canonical V34 Stage A appeared during construction: {STAGE_A}"
            )
        staging.rename(STAGE_A)
    except Exception:
        if connection is not None:
            connection.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
