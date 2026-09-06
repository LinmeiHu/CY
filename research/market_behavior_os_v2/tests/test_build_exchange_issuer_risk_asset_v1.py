from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_risk_asset_v1 as subject,
)
from research.market_behavior_os_v2.scripts import (
    fetch_exchange_issuer_announcements_v1 as collector,
)
from research.market_behavior_os_v2.scripts import (
    seal_exchange_issuer_announcements_v1 as source_sealer,
)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _symbols() -> list[str]:
    return [f"{code:06d}.SZ" for code in range(1, subject.EXPECTED_UNIVERSE_SYMBOLS + 1)]


def _empty_fetched(spec: collector.QuerySpec, page: int) -> collector.FetchedPage:
    payload = {"announceCount": 0, "data": []}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    method, url, params, json_body, headers = collector.build_request(
        spec.exchange,
        spec.code,
        spec.start,
        spec.end,
        page,
        cache_buster="123456",
    )
    return collector.FetchedPage(
        body=body,
        method=method,
        url=url,
        params=params,
        json_body=json_body,
        request_headers=headers,
        response_headers={"Content-Type": "application/json"},
        status_code=200,
        retrieved_at="2026-09-05T00:00:00+00:00",
    )


@pytest.fixture(scope="module")
def collector_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("cy036_collector_template")
    universe = root / subject.UNIVERSE_NAME
    pd.DataFrame({"symbol": _symbols()}).to_parquet(universe, index=False)

    original = collector.fetch_page

    def fake_fetch(session, spec, page, *, retries, timeout):
        del session, retries, timeout
        return _empty_fetched(spec, page)

    collector.fetch_page = fake_fetch
    try:
        collector.run_capture(
            universe,
            root / subject.SOURCE_CAPTURE_NAME,
            subject.COVERAGE_START,
            subject.COVERAGE_END,
            workers=16,
        )
    finally:
        collector.fetch_page = original
    return root


@pytest.fixture
def bounded_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    collector_template: Path,
) -> dict[str, Path]:
    root = tmp_path / "CY-036"
    shutil.copytree(collector_template, root)
    source_root = root / subject.SOURCE_CAPTURE_NAME

    source_manifest_path = source_root / "source_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_manifest["location"] = str(source_root.resolve())
    source_manifest["universe_source"] = str((root / subject.UNIVERSE_NAME).resolve())
    source_manifest_path.write_text(
        json.dumps(source_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    source_sealer.seal_asset(source_root)

    lineage = tmp_path / "lineage"
    lineage.mkdir()
    selected_v28r1 = lineage / "v28r1_selected.parquet"
    pd.DataFrame({"symbol": [*_symbols(), _symbols()[0]]}).to_parquet(selected_v28r1, index=False)

    classifier_path = lineage / "classifier.py"
    shutil.copy2(subject.CLASSIFIER_PATH, classifier_path)
    parent_runner = lineage / "v28r2_runner.py"
    parent_runner.write_text("# frozen V28R2 runner fixture\n", encoding="utf-8")
    parent_selected = lineage / "v28r2_selected.parquet"
    parent_selected.write_bytes(b"FROZEN_PRE_OUTCOME_SELECTED_IDENTITY")
    parent_result = lineage / "v28r2_development_result.json"
    parent_result.write_bytes(b"THIS_OUTCOME_IDENTITY_MUST_NEVER_BE_JSON_PARSED")
    parent_stage = lineage / "v28r2_stage_a_freeze.json"
    parent_stage.write_text(
        json.dumps(
            {
                "experiment": subject.V28R2_EXPERIMENT,
                "development_outcomes_opened": "NO_IN_THIS_STAGE",
                "post_2021_entries_or_outcomes_opened": "NO_IN_THIS_STAGE",
                "runner_sha256": _sha(parent_runner),
                "source_hashes": {"v28r1_development_selected_entries": _sha(selected_v28r1)},
                "development": {"selected_entries_sha256": _sha(parent_selected)},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    prereg = lineage / "v29_preregistration.json"
    prereg.write_text(
        json.dumps(
            {
                "experiment": subject.V29_EXPERIMENT,
                "status": "SEMANTIC_RULE_FROZEN_BEFORE_DEVELOPMENT_EVENT_OUTCOME_JOIN",
                "parent": subject.V28R2_EXPERIMENT,
                "parent_runner_sha256": _sha(parent_runner),
                "parent_development_stage_a_sha256": _sha(parent_stage),
                "parent_development_result_sha256": _sha(parent_result),
                "classifier": {
                    "version": subject.classifier.CLASSIFICATION_VERSION,
                    "runner_sha256": _sha(classifier_path),
                },
                "development": {
                    "signal_years": [2018, 2019, 2020, 2021],
                    "announcement_capture_start": subject.COVERAGE_START,
                    "announcement_capture_end": subject.COVERAGE_END,
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(subject, "V28R1_DEVELOPMENT_SELECTED_PATH", selected_v28r1)
    monkeypatch.setattr(subject, "CLASSIFIER_PATH", classifier_path)
    monkeypatch.setattr(subject, "V28R2_RUNNER_PATH", parent_runner)
    monkeypatch.setattr(subject, "V28R2_STAGE_A_PATH", parent_stage)
    monkeypatch.setattr(subject, "V28R2_SELECTED_PATH", parent_selected)
    monkeypatch.setattr(subject, "V28R2_DEVELOPMENT_RESULT_PATH", parent_result)
    monkeypatch.setattr(subject, "PREREGISTRATION_PATH", prereg)
    return {
        "root": root,
        "source": source_root,
        "selected_v28r1": selected_v28r1,
        "classifier": classifier_path,
        "prereg": prereg,
    }


def test_build_and_full_revalidation_are_bounded_and_non_authorizing(
    bounded_case: dict[str, Path],
) -> None:
    root = bounded_case["root"]

    built = subject.build_asset(root)
    validated = subject.validate_asset(root)

    assert built["status"] == validated["status"] == "PASS"
    assert built["asset_id"] == validated["asset_id"] == "CY-036"
    assert built["registered"] is False
    assert built["backtest_authorized"] is False
    manifest = json.loads((root / "asset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "PASS"
    assert manifest["immutable"] is True
    assert manifest["registered"] is False
    assert manifest["backtest_authorized"] is False
    assert manifest["coverage"] == {
        "start": subject.COVERAGE_START,
        "end": subject.COVERAGE_END,
    }
    assert manifest["universe"]["symbols"] == 378
    assert manifest["pit"]["grade"] == "B"
    assert manifest["pit"]["revision_history_incomplete"] is True
    assert manifest["content"]["title_only"] is True
    roles = {row["role"] for row in manifest["inventory"]}
    assert {
        "universe",
        "source_capture_asset_manifest",
        "source_capture_source_manifest",
        "source_capture_validation_audit",
        "source_capture_announcements",
        "source_capture_request_pages",
        "risk_title_classifier",
        "v29_preregistration",
        "v28r1_development_selected_entries_identity",
        "v28r2_parent_selected_entries_identity",
    }.issubset(roles)
    assert "raw_page" not in roles
    nested = next(
        row for row in manifest["inventory"] if row["role"] == "source_capture_asset_manifest"
    )
    assert nested["raw_page_inventory"] == "COVERED_BY_NESTED_SEAL_NOT_DUPLICATED_HERE"

    extra = root / "unexpected-wrapper-file.txt"
    extra.write_text("not allowed", encoding="utf-8")
    with pytest.raises(subject.CY036BuildError, match="extra entries"):
        subject.validate_asset(root)


def test_universe_drift_fails_before_source_can_be_treated_as_coverage(
    bounded_case: dict[str, Path],
) -> None:
    universe = bounded_case["root"] / subject.UNIVERSE_NAME
    symbols = _symbols()
    symbols[-1] = "000999.SZ"
    pd.DataFrame({"symbol": sorted(symbols)}).to_parquet(universe, index=False)

    with pytest.raises(subject.CY036BuildError, match="does not exactly equal"):
        subject.build_asset(bounded_case["root"])


@pytest.mark.parametrize("target", ["classifier", "prereg"])
def test_classifier_or_preregistration_drift_fails_closed(
    bounded_case: dict[str, Path], target: str
) -> None:
    path = bounded_case[target]
    if target == "classifier":
        path.write_text(path.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
        match = "classifier SHA-256 differs"
    else:
        value = json.loads(path.read_text(encoding="utf-8"))
        value["parent_runner_sha256"] = "0" * 64
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        match = "runner SHA-256 differs"

    with pytest.raises(subject.CY036BuildError, match=match):
        subject.build_asset(bounded_case["root"])


def test_nested_source_seal_drift_is_caught_by_full_revalidation(
    bounded_case: dict[str, Path],
) -> None:
    raw = next((bounded_case["source"] / "raw").rglob("*.json"))
    raw.write_bytes(raw.read_bytes() + b"\n")

    with pytest.raises(subject.CY036BuildError, match="source capture full seal validation failed"):
        subject.build_asset(bounded_case["root"])


def test_existing_wrapper_is_never_overwritten(bounded_case: dict[str, Path]) -> None:
    root = bounded_case["root"]
    subject.build_asset(root)
    before = (root / subject.ASSET_MANIFEST_NAME).read_bytes()

    with pytest.raises(subject.CY036BuildError, match="wrapper files already exist"):
        subject.build_asset(root)

    assert (root / subject.ASSET_MANIFEST_NAME).read_bytes() == before
