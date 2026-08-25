from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from cyq_game.data import (  # noqa: E402
    DataActivationError,
    DataAsset,
    DataExecutionAuthorization,
    DataOperation,
    DataPurpose,
    InputBinding,
    QuantReadScope,
    adapt_cninfo_corporate_actions,
    resolve_distribution_reference_price,
)


@pytest.mark.parametrize(
    ("previous_close", "observed_preclose", "multiplier", "cash"),
    (
        (91.10, 64.66, 1.4, 0.58002),
        (112.68, 80.25, 1.4, 0.337),
        (175.84, 146.23, 1.2, 0.363),
    ),
)
def test_reference_price_resolves_603259_share_actions(
    previous_close: float,
    observed_preclose: float,
    multiplier: float,
    cash: float,
) -> None:
    result = resolve_distribution_reference_price(
        previous_close=previous_close,
        observed_preclose=observed_preclose,
        share_multiplier=multiplier,
        cash_per_pre_action_share=cash,
    )

    assert result.matched
    assert result.absolute_error <= result.tolerance


def test_reference_price_rejects_wrong_share_terms() -> None:
    result = resolve_distribution_reference_price(
        previous_close=112.68,
        observed_preclose=80.25,
        share_multiplier=1.2,
        cash_per_pre_action_share=0.337,
    )

    assert not result.matched


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding(root: Path, files: tuple[Path, ...]) -> InputBinding:
    inventory = root / "inventory.json"
    payload = {
        "schema_version": 1,
        "root": str(root),
        "files": [
            {
                "path": str(path.relative_to(root)),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in files
        ],
    }
    inventory.write_text(json.dumps(payload), encoding="utf-8")
    asset = DataAsset(
        asset_id="TEST-CORPORATE",
        name="fixture",
        kind="corporate_actions_pit",
        status="QA_ONLY",
        pit_grade="B",
        physical_state="MATERIALIZED",
        location=root,
        source="test",
        lineage={},
    )
    return InputBinding(
        role="corporate_actions",
        asset=asset,
        path=root,
        source="frozen-cninfo-fixture",
        snapshot_id="fixture-v1",
        available_at_policy="known_at from official announcement date plus one day",
        sha256=None,
        inventory_manifest=inventory,
        inventory_sha256=_sha256(inventory),
    )


def _authorization(
    operation: DataOperation = DataOperation.INGEST,
) -> DataExecutionAuthorization:
    return DataExecutionAuthorization(
        operation=operation,
        registry_id="TEST",
        registry_sha256="a" * 64,
        input_manifest_id="TEST-INPUT",
        input_manifest_sha256="b" * 64,
        purpose=DataPurpose.DATA_PREPARATION,
        hard_valid=False,
        software_test=False,
        scope_start=date(2024, 1, 1),
        scope_end=date(2024, 12, 31),
    )


def _write_sources(root: Path) -> tuple[Path, Path]:
    distributions = root / "distributions.parquet"
    rights = root / "rights_issues.parquet"
    pq.write_table(
        pa.table(
            {
                "symbol": ["000001", "000001"],
                "event_id": ["dist-good", "dist-bad"],
                "revision_id": ["rev-good", "rev-bad"],
                "source": ["cninfo-distribution", "cninfo-distribution"],
                "announcement_date": [datetime(2024, 1, 2), datetime(2024, 1, 4)],
                "known_at": [datetime(2024, 1, 3), datetime(2024, 1, 5)],
                "effective_date": [datetime(2024, 1, 10), datetime(2024, 1, 11)],
                "share_multiplier": [1.2, 1.0],
                "cash_per_share_gross": [0.3, 0.0],
                "source_terms_complete": [True, True],
                "execution_timing_resolved": [True, True],
            }
        ),
        distributions,
    )
    pq.write_table(
        pa.table(
            {
                "symbol": ["000001"],
                "event_id": ["rights-good"],
                "revision_id": ["rev-rights"],
                "source": ["cninfo-rights"],
                "announcement_date": [datetime(2024, 1, 8)],
                "known_at": [datetime(2024, 1, 9)],
                "effective_date": [datetime(2024, 1, 15)],
                "rights_subscription_ratio": [0.3],
                "rights_subscription_price": [8.0],
                "source_terms_complete": [True],
            }
        ),
        rights,
    )
    return distributions, rights


def test_cninfo_adapter_emits_actions_and_fail_closed_blocker(tmp_path: Path) -> None:
    distributions, rights = _write_sources(tmp_path)
    batch = adapt_cninfo_corporate_actions(
        binding=_binding(tmp_path, (distributions, rights)),
        authorization=_authorization(),
        scope=QuantReadScope(
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
            symbols=("000001.SZ",),
        ),
        distributions_path=distributions,
        rights_path=rights,
        run_id="fixture-run",
    )

    assert batch.distribution_rows_seen == 2
    assert batch.rights_rows_seen == 1
    assert [record.action_type for record in batch.records] == [
        "SPLIT",
        "CASH_DIVIDEND",
        "UNRESOLVED_CORPORATE_ACTION",
        "RIGHTS_ISSUE",
    ]
    assert batch.records[0].ratio == pytest.approx(1.2)
    assert batch.records[1].cash_per_share == pytest.approx(0.3)
    assert batch.issues[0].reason == "distribution has no positive economic terms"
    assert all(record.available_at <= record.effective_from for record in batch.records)
    assert all(record.snapshot_id == "fixture-v1" for record in batch.records)


def test_cninfo_adapter_rejects_non_ingest_authorization(tmp_path: Path) -> None:
    distributions, rights = _write_sources(tmp_path)
    with pytest.raises(DataActivationError, match="requires INGEST"):
        adapt_cninfo_corporate_actions(
            binding=_binding(tmp_path, (distributions, rights)),
            authorization=_authorization(DataOperation.BACKTEST),
            scope=QuantReadScope(
                start=date(2024, 1, 1),
                end=date(2024, 1, 31),
                symbols=("000001.SZ",),
            ),
            distributions_path=distributions,
            rights_path=rights,
            run_id="fixture-run",
        )
