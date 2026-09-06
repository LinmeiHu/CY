from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    build_ashare_true_gap_below_l_demand_recapture_v29r45_stage_b_asset as subject,
)


def _cap_source() -> pd.DataFrame:
    rows = []
    for industry_index, industry in enumerate(("A", "B", "C")):
        for queue_index in range(10):
            number = industry_index * 100 + queue_index
            rows.append(
                {
                    "gap_id": f"gap-{industry}-{queue_index:02d}",
                    "symbol": f"{number:06d}.SZ",
                    "signal_date": pd.Timestamp("2020-01-02"),
                    "signal_industry": industry,
                    "rebound_from_post_gap_low_over_l": 1.0 - queue_index / 100,
                }
            )
    return pd.DataFrame(rows)


def test_cap25_is_exact_lexical_industry_round_robin_and_deterministic() -> None:
    source = _cap_source()
    first = subject.cap25_industry_round_robin(source)
    second = subject.cap25_industry_round_robin(
        source.sample(frac=1.0, random_state=7).reset_index(drop=True)
    )

    assert len(first) == 25
    assert first.cap25_rank.tolist() == list(range(1, 26))
    assert first.signal_industry.iloc[:9].tolist() == ["A", "B", "C"] * 3
    assert first.gap_id.tolist() == second.gap_id.tolist()
    assert first.cap25_primary_economic_admission.eq(True).all()


@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf])
def test_cap25_rejects_missing_or_nonfinite_rank(bad_value: float) -> None:
    source = _cap_source()
    source.loc[0, "rebound_from_post_gap_low_over_l"] = bad_value
    with pytest.raises(subject.CY046BuildError, match="nonfinite"):
        subject.cap25_industry_round_robin(source)


def _identity(signal_date: pd.Timestamp, gap_id: str) -> dict[str, object]:
    return {
        "protocol_arm": "V29R4_CAP25",
        "gap_id": gap_id,
        "symbol": "000001.SZ",
        "signal_date": signal_date,
        "signal_snapshot_id": "aggregate-snapshot",
        "signal_daily_snapshot_id": "daily-snapshot",
        "signal_corporate_action_snapshot_id": "action-snapshot",
    }


def test_admin_censor_and_candidate_offsets_are_exact() -> None:
    dates = pd.bdate_range("2021-10-01", periods=30)
    calendar = subject.market_calendar_frame(dates)
    identity = pd.DataFrame(
        [
            _identity(dates[0], "eligible"),
            _identity(dates[6], "censored"),
        ]
    )
    scheduled = subject.attach_administrative_schedule(identity, calendar)

    eligible = scheduled.loc[scheduled.gap_id.eq("eligible")].iloc[0]
    censored = scheduled.loc[scheduled.gap_id.eq("censored")].iloc[0]
    assert eligible.admin_eligible
    assert eligible.entry_date == dates[1]
    assert eligible.h20_date == dates[21]
    assert eligible.h23_date == dates[24]
    assert not censored.admin_eligible
    assert censored.entry_date == dates[7]
    assert pd.isna(censored.h23_date)

    requests = subject.make_path_requests(scheduled, calendar)
    assert len(requests) == 25
    assert tuple(requests.iloc[0][["signal_session_offset", "entry_session_offset"]]) == (
        0,
        -1,
    )
    assert tuple(requests.iloc[-1][["signal_session_offset", "entry_session_offset"]]) == (
        24,
        23,
    )
    assert requests.trade_date.iloc[0] == dates[0]
    assert requests.trade_date.iloc[-1] == dates[24]


def test_market_calendar_schema_is_exact_and_contiguous() -> None:
    calendar = subject.market_calendar_frame(
        ["2020-01-03", "2020-01-02", "2020-01-03"]
    )
    assert list(calendar.columns) == ["trade_date", "calendar_index"]
    assert calendar.calendar_index.tolist() == [0, 1]
    assert calendar.trade_date.dt.strftime("%Y-%m-%d").tolist() == [
        "2020-01-02",
        "2020-01-03",
    ]


def test_snapshot_binding_rejects_nonempty_conflict_but_preserves_missing() -> None:
    keys = {
        "protocol_arm": "V29R4_CAP25",
        "gap_id": "g",
        "trade_date": pd.Timestamp("2020-01-03"),
    }
    daily = pd.DataFrame(
        [{**keys, "source_row_present": True, "snapshot_id": "daily-bound"}]
    )
    execution = pd.DataFrame(
        [{**keys, "source_row_present": True, "daily_snapshot_id": "daily-bound"}]
    )
    assert subject.validate_execution_daily_snapshot_binding(execution, daily) == {
        "paired_nonempty_snapshot_conflicts": 0,
        "missing_or_unbound_snapshot_rows_preserved": 0,
    }

    conflict = execution.assign(daily_snapshot_id="different")
    with pytest.raises(subject.CY046BuildError, match="conflicts"):
        subject.validate_execution_daily_snapshot_binding(conflict, daily)

    missing = execution.assign(daily_snapshot_id=pd.NA)
    assert subject.validate_execution_daily_snapshot_binding(missing, daily)[
        "missing_or_unbound_snapshot_rows_preserved"
    ] == 1


def _qd_row(
    event_id: str,
    *,
    effective_date: str | None,
    cash: float,
    multiplier: float,
    rights: float,
) -> dict[str, object]:
    row: dict[str, object] = {column: None for column in subject.QD010_COLUMNS}
    row.update(
        {
            "security_id": "sec-1",
            "symbol": "000001.SZ",
            "source": "official",
            "source_api": "api",
            "source_record_id": f"record-{event_id}",
            "announcement_date": pd.Timestamp("2020-01-02"),
            "known_at": pd.Timestamp("2020-01-03"),
            "known_at_precision": "DATE_CONSERVATIVE_NEXT_DAY",
            "known_at_semantics": "causal",
            "record_date": pd.Timestamp("2020-01-06"),
            "effective_date": pd.Timestamp(effective_date) if effective_date else pd.NaT,
            "cash_per_share_gross": cash,
            "share_multiplier": multiplier,
            "bonus_share_ratio": max(multiplier - 1.0, 0.0),
            "capitalized_share_ratio": 0.0,
            "rights_subscription_ratio": rights,
            "rights_subscription_price": 1.0 if rights else 0.0,
            "event_type": "event",
            "source_terms_complete": True,
            "execution_timing_resolved": True,
            "resolution_status": "RESOLVED",
            "price_terms_resolved": True,
            "execution_resolved": False,
            "execution_timing_unresolved_reason": None,
            "execution_unresolved_reason": None,
            "source_description": "synthetic",
            "source_updated_at_available": False,
            "source_updated_at_semantics": "unavailable",
            "vintage_id": "vintage",
            "response_sha256": "a" * 64,
            "source_revision": "revision",
            "revision_history_complete": False,
            "strict_pit_eligible": False,
            "knowledge_quality": "PIT_B",
            "row_hash": hashlib.sha256(event_id.encode("utf-8")).hexdigest(),
            "source_natural_key": f"natural-{event_id}",
            "source_event_key": f"source-event-{event_id}",
            "event_id": event_id,
            "event_identity_quality": "EXACT",
            "revision_id": f"revision-{event_id}",
            "revision_ordinal": 1,
            "is_new_event": True,
            "is_changed_from_previous": False,
            "vintage_observation_id": f"observation-{event_id}",
        }
    )
    return row


def _candidate_scope() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "protocol_arm": "V29R4_CAP25",
                "gap_id": "gap-1",
                "symbol": "000001.SZ",
                "signal_date": pd.Timestamp("2020-01-02"),
                "entry_date": pd.Timestamp("2020-01-03"),
                "h23_date": pd.Timestamp("2020-02-10"),
                "admin_eligible": True,
            }
        ]
    )


def _action_calendar() -> pd.DataFrame:
    return subject.market_calendar_frame(pd.bdate_range("2020-01-02", "2020-02-10"))


def test_action_materialization_is_candidate_bounded_and_classifies_without_dedup(
    tmp_path: Path,
) -> None:
    distributions = pd.DataFrame(
        [
            _qd_row(
                "cash",
                effective_date="2020-01-10",
                cash=0.1,
                multiplier=1.0,
                rights=0.0,
            ),
            _qd_row(
                "mixed-share",
                effective_date="2020-01-13",
                cash=0.2,
                multiplier=1.1,
                rights=0.0,
            ),
            _qd_row(
                "outside",
                effective_date="2020-03-01",
                cash=0.1,
                multiplier=1.0,
                rights=0.0,
            ),
        ]
    )
    rights = pd.DataFrame(
        [
            _qd_row(
                "rights",
                effective_date="2020-01-15",
                cash=0.0,
                multiplier=1.0,
                rights=0.2,
            )
        ]
    )
    dist_path = tmp_path / "distributions.parquet"
    rights_path = tmp_path / "rights_issues.parquet"
    distributions.to_parquet(dist_path, index=False)
    rights.to_parquet(rights_path, index=False)

    result = subject._extract_action_events(
        _candidate_scope(), [dist_path, rights_path], _action_calendar()
    )

    assert result.event_id.tolist() == ["cash", "mixed-share", "rights"]
    assert dict(zip(result.event_id, result.action_kind, strict=True)) == {
        "cash": "CASH_ONLY",
        "mixed-share": "RISK_SHARE",
        "rights": "RISK_RIGHTS",
    }
    assert result.loc[result.event_id.eq("mixed-share"), "cash_per_share_gross"].item() == 0.2
    assert result.available_at.equals(result.known_at)
    assert result.cash_per_share.equals(result.cash_per_share_gross)
    assert result.rights_ratio.equals(result.rights_subscription_ratio)
    assert result.rights_price.equals(result.rights_subscription_price)
    assert result.source_snapshot_id.eq(subject.QD010_SOURCE_SNAPSHOT_ID).all()
    assert result.snapshot_id.equals(result.source_snapshot_id)
    assert tuple(result.columns) == subject.ACTION_OUTPUT_COLUMNS


def test_unknown_effective_action_is_not_silently_filtered(tmp_path: Path) -> None:
    unknown = pd.DataFrame(
        [
            _qd_row(
                "unknown",
                effective_date=None,
                cash=0.1,
                multiplier=1.0,
                rights=0.0,
            )
        ]
    )
    dist_path = tmp_path / "distributions.parquet"
    rights_path = tmp_path / "rights_issues.parquet"
    unknown.to_parquet(dist_path, index=False)
    unknown.iloc[0:0].to_parquet(rights_path, index=False)

    with pytest.raises(subject.CY046BuildError, match="known/effective/available timing"):
        subject._extract_action_events(
            _candidate_scope(), [dist_path, rights_path], _action_calendar()
        )


def test_generic_execution_resolution_flag_is_retained_but_not_a_blanket_gate(
    tmp_path: Path,
) -> None:
    unresolved = pd.DataFrame(
        [
            _qd_row(
                "unresolved-cash",
                effective_date="2020-01-10",
                cash=0.1,
                multiplier=1.0,
                rights=0.0,
            )
        ]
    )
    unresolved.loc[0, "execution_timing_resolved"] = False
    dist_path = tmp_path / "distributions.parquet"
    rights_path = tmp_path / "rights_issues.parquet"
    unresolved.to_parquet(dist_path, index=False)
    unresolved.iloc[0:0].to_parquet(rights_path, index=False)

    result = subject._extract_action_events(
        _candidate_scope(), [dist_path, rights_path], _action_calendar()
    )
    assert result.action_kind.tolist() == ["CASH_ONLY"]
    assert result.execution_timing_resolved.eq(False).all()


def test_action_timing_requires_exact_alias_and_strictly_pre_effective() -> None:
    events = pd.DataFrame(
        {
            "known_at": [pd.Timestamp("2020-01-03")],
            "available_at": [pd.Timestamp("2020-01-03")],
            "effective_date": [pd.Timestamp("2020-01-10")],
        }
    )
    subject.validate_action_event_timing(events)

    with pytest.raises(subject.CY046BuildError, match="exactly known_at"):
        subject.validate_action_event_timing(
            events.assign(available_at=pd.Timestamp("2020-01-03 00:00:01"))
        )
    with pytest.raises(subject.CY046BuildError, match="strict pre-effective"):
        subject.validate_action_event_timing(
            events.assign(
                known_at=pd.Timestamp("2020-01-10"),
                available_at=pd.Timestamp("2020-01-10"),
            )
        )
    with pytest.raises(subject.CY046BuildError, match="date-only midnight"):
        subject.validate_action_event_timing(
            events.assign(effective_date=pd.Timestamp("2020-01-10 09:30:00"))
        )
    with pytest.raises(subject.CY046BuildError, match="timezone-naive"):
        subject.validate_action_event_timing(
            events.assign(effective_date=pd.Timestamp("2020-01-10", tz="Asia/Shanghai"))
        )


def test_action_effective_date_must_be_a_frozen_market_session() -> None:
    event = pd.DataFrame({"effective_date": [pd.Timestamp("2020-01-10")]})
    subject.validate_action_effective_sessions(event, _action_calendar())
    with pytest.raises(subject.CY046BuildError, match="frozen market session"):
        subject.validate_action_effective_sessions(
            event.assign(effective_date=pd.Timestamp("2020-01-11")),
            _action_calendar(),
        )


@pytest.mark.parametrize(
    ("source_table", "cash", "multiplier", "rights", "rights_price", "expected"),
    [
        ("DISTRIBUTION", 0.0, 1.0, 0.0, 0.0, "CASH_ONLY"),
        ("DISTRIBUTION", 0.2, 1.0000000000000002, 0.0, 0.0, "RISK_SHARE"),
        ("DISTRIBUTION", np.nan, 1.1, 0.0, np.nan, "RISK_SHARE"),
        ("DISTRIBUTION", 0.0, 0.0, 0.0, 0.0, "UNSUPPORTED_OR_UNKNOWN"),
        ("DISTRIBUTION", 0.0, np.inf, 0.0, 0.0, "UNSUPPORTED_OR_UNKNOWN"),
        ("DISTRIBUTION", np.inf, 1.0, 0.0, 0.0, "UNSUPPORTED_OR_UNKNOWN"),
        ("RIGHTS", 0.0, 1.0, 0.2, 3.5, "RISK_RIGHTS"),
        ("RIGHTS", 0.0, 1.0, 0.0, 3.5, "UNSUPPORTED_OR_UNKNOWN"),
        ("RIGHTS", 0.0, 1.0, 0.2, np.inf, "UNSUPPORTED_OR_UNKNOWN"),
    ],
)
def test_action_classification_uses_exact_decimal_terms(
    source_table: str,
    cash: float,
    multiplier: float,
    rights: float,
    rights_price: float,
    expected: str,
) -> None:
    row = _qd_row(
        "decimal-classification",
        effective_date="2020-01-10",
        cash=cash,
        multiplier=multiplier,
        rights=rights,
    )
    row["source_table"] = source_table
    row["rights_subscription_price"] = rights_price
    assert subject.classify_qd_action_terms(row) == expected


def test_action_join_requires_full_canonical_symbol(tmp_path: Path) -> None:
    wrong_exchange = pd.DataFrame(
        [
            _qd_row(
                "wrong-exchange",
                effective_date="2020-01-10",
                cash=0.1,
                multiplier=1.0,
                rights=0.0,
            )
        ]
    )
    wrong_exchange.loc[0, "symbol"] = "000001.SH"
    dist_path = tmp_path / "distributions.parquet"
    rights_path = tmp_path / "rights_issues.parquet"
    wrong_exchange.to_parquet(dist_path, index=False)
    wrong_exchange.iloc[0:0].to_parquet(rights_path, index=False)

    result = subject._extract_action_events(
        _candidate_scope(), [dist_path, rights_path], _action_calendar()
    )
    assert result.empty
    with pytest.raises(subject.CY046BuildError, match="noncanonical symbol"):
        subject._extract_action_events(
            _candidate_scope().assign(symbol="000001"),
            [dist_path, rights_path],
            _action_calendar(),
        )


def test_action_frozen_lineage_format_and_uniqueness_fail_closed(tmp_path: Path) -> None:
    first = _qd_row(
        "lineage-a",
        effective_date="2020-01-10",
        cash=0.1,
        multiplier=1.0,
        rights=0.0,
    )
    second = _qd_row(
        "lineage-b",
        effective_date="2020-01-13",
        cash=0.1,
        multiplier=1.0,
        rights=0.0,
    )
    second["row_hash"] = first["row_hash"]
    dist_path = tmp_path / "distributions.parquet"
    rights_path = tmp_path / "rights_issues.parquet"
    pd.DataFrame([first, second]).to_parquet(dist_path, index=False)
    pd.DataFrame([first]).iloc[0:0].to_parquet(rights_path, index=False)
    with pytest.raises(subject.CY046BuildError, match="duplicated: row_hash"):
        subject._extract_action_events(
            _candidate_scope(), [dist_path, rights_path], _action_calendar()
        )

    first["row_hash"] = "not-a-sha256"
    pd.DataFrame([first]).to_parquet(dist_path, index=False)
    with pytest.raises(subject.CY046BuildError, match="lineage format/binding"):
        subject._extract_action_events(
            _candidate_scope(), [dist_path, rights_path], _action_calendar()
        )


def test_atomic_publish_is_no_replace(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    (source / "marker").write_text("first", encoding="utf-8")
    subject.atomic_publish_directory_no_replace(source, destination)
    assert not source.exists()
    assert (destination / "marker").read_text(encoding="utf-8") == "first"

    contender = tmp_path / "contender"
    contender.mkdir()
    (contender / "marker").write_text("second", encoding="utf-8")
    with pytest.raises(subject.CY046BuildError, match="appeared"):
        subject.atomic_publish_directory_no_replace(contender, destination)
    assert contender.is_dir()
    assert (destination / "marker").read_text(encoding="utf-8") == "first"


def test_same_volume_immutable_probe_and_exact_asset_seal_cleanup(tmp_path: Path) -> None:
    subject.probe_uf_immutable_capability(tmp_path)
    root = tmp_path / "asset"
    root.mkdir()
    for filename in subject.EXACT_CANONICAL_FILENAMES:
        (root / filename).write_bytes(b"")
    try:
        subject.seal_canonical_asset_immutable(root)
        subject.assert_canonical_asset_immutable(root)
        assert (root.lstat().st_mode & 0o777) == 0o555
        assert all((path.lstat().st_mode & 0o777) == 0o444 for path in root.iterdir())
    finally:
        subject.clear_canonical_asset_immutability(root)
    assert (root.lstat().st_mode & 0o777) == 0o700
    assert all((path.lstat().st_mode & 0o777) == 0o600 for path in root.iterdir())


def test_explicit_action_schema_survives_empty_and_all_null_terms(tmp_path: Path) -> None:
    for role, columns in subject.EXPECTED_OUTPUT_COLUMNS.items():
        empty_path = tmp_path / f"{role}-empty.parquet"
        subject._write_parquet(
            pd.DataFrame(columns=columns), empty_path, role
        )
        empty_facts = subject.parquet_footer_facts(empty_path)
        assert empty_facts["rows"] == 0
        assert empty_facts["schema_sha256"] == subject.OUTPUT_SCHEMA_SHA256[role]
        assert all(item["type"] != "null" for item in empty_facts["schema"])

    all_null = pd.DataFrame(
        [{column: None for column in subject.ACTION_OUTPUT_COLUMNS}]
    )
    path = tmp_path / "all-null-action-terms.parquet"
    subject._write_parquet(all_null, path, "candidate_action_events")
    facts = subject.parquet_footer_facts(path)
    assert facts["rows"] == 1
    assert facts["schema_sha256"] == subject.OUTPUT_SCHEMA_SHA256[
        "candidate_action_events"
    ]
    assert all(item["type"] != "null" for item in facts["schema"])


def test_post_content_source_revalidation_detects_same_bytes_new_inode(
    tmp_path: Path,
) -> None:
    path = tmp_path / "source.bin"
    path.write_bytes(b"frozen")
    digest = subject.sha256_file(path)
    binding = subject._require_file_hash(path, digest, "synthetic source")
    plan = {"source": binding}
    assert subject.revalidate_sources_after_content_read(plan)[
        "sha256_device_inode_size_match"
    ]
    path.unlink()
    path.write_bytes(b"frozen")
    with pytest.raises(subject.CY046BuildError, match="retargeted"):
        subject.revalidate_sources_after_content_read(plan)


def test_bound_source_rejects_symlink_ancestor_and_root_escape_before_footer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered_root = tmp_path / "registered"
    registered_root.mkdir()
    source = registered_root / "source.parquet"
    source.write_bytes(b"not-opened")
    alias = tmp_path / "alias"
    alias.symlink_to(registered_root, target_is_directory=True)
    monkeypatch.setattr(
        subject.pq,
        "ParquetFile",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("footer opened")),
    )

    with pytest.raises(subject.CY046BuildError, match="symlink"):
        subject.parquet_footer_facts(
            alias / source.name, registered_root=alias
        )
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(b"not-opened")
    with pytest.raises(subject.CY046BuildError, match="lexically contained"):
        subject.parquet_footer_facts(outside, registered_root=registered_root)


def test_manifest_audit_cross_binding_is_exact() -> None:
    manifest = {
        "asset_id": subject.ASSET_ID,
        "status": "PASS",
        "authorization_id": subject.AUTHORIZATION_ID,
        "coverage": {"start": "2018-01-01", "end": "2021-12-31"},
        "protocol": {
            "sha256": "prereg",
            "runner_sha256": "runner",
            "builder_sha256": "builder",
        },
        "files": [],
        "source_bindings": {},
        "pit_contract": subject.PIT_CONTRACT,
        "content_contract": {},
    }
    audit = {
        "asset_id": subject.ASSET_ID,
        "status": "PASS",
        "gate_pass": True,
        "manifest_path": "asset_manifest.json",
        "manifest_sha256": "manifest",
        "preregistration_sha256": "prereg",
        "runner_sha256": "runner",
        "asset_builder_sha256": "builder",
        "source_metadata_gate": "PASS",
        "identity_count_gate": "PASS",
        "scope_gate": "PASS",
        "snapshot_nonempty_conflict_gate": "PASS",
        "post_2021_rows": 0,
        "outcome_or_return_source_columns": [],
        "audit_counts": {},
        "parquet_rows_opened_for_content_build": True,
        "returns_computed": False,
        "outcome_or_return_rows_opened": False,
        "registry_modified": False,
        "post_content_source_revalidation": {},
        "output_schema_sha256": subject.OUTPUT_SCHEMA_SHA256,
        "pit_contract": subject.PIT_CONTRACT,
    }
    subject.validate_manifest_audit_cross_binding(manifest, audit, "manifest")
    with pytest.raises(subject.CY046BuildError, match="cross-binding"):
        subject.validate_manifest_audit_cross_binding(
            manifest, {**audit, "runner_sha256": "different"}, "manifest"
        )
    with pytest.raises(subject.CY046BuildError, match="cross-binding"):
        subject.validate_manifest_audit_cross_binding(
            manifest, {**audit, "unexpected": True}, "manifest"
        )
    with pytest.raises(subject.CY046BuildError, match="cross-binding"):
        subject.validate_manifest_audit_cross_binding(
            {**manifest, "pit_contract": {**subject.PIT_CONTRACT, "grade": "A"}},
            audit,
            "manifest",
        )


def test_audit_counts_must_reconcile_to_manifest_and_output_footers() -> None:
    manifest = {
        "content_contract": {
            "v29r4_cap25_exact_rows": 251,
            "v29r5_cap25_exact_rows": 255,
            "v29r4_admin_eligible": 251,
            "v29r5_admin_eligible": 254,
            "v29r5_admin_censored": 1,
        }
    }
    observed = {
        "v29r4_cap25_identity": 251,
        "v29r5_cap25_identity": 255,
        "candidate_admin_bounds": 506,
        "candidate_daily_path": 12_625,
        "candidate_execution_window0": 12_120,
        "candidate_action_events": 3,
        "market_calendar": 972,
    }
    counts = {
        "r4_cap25_rows": 251,
        "r5_cap25_rows": 255,
        "administrative_bound_rows": 506,
        "r4_administratively_eligible": 251,
        "r4_administratively_censored": 0,
        "r5_administratively_eligible": 254,
        "r5_administratively_censored": 1,
        "cy006_requested_rows": 12_625,
        "cy006_missing_rows_preserved": 0,
        "cy006_hard_invalid_rows_preserved": 0,
        "cy008_requested_window0_rows": 12_120,
        "cy008_missing_rows_preserved": 0,
        "cy008_hard_invalid_rows_preserved": 0,
        "cy008_or_cy006_snapshot_missing_rows_preserved": 0,
        "cy008_cy006_nonempty_snapshot_conflicts": 0,
        "qd010_bounded_event_rows": 3,
        "qd010_cash_only_rows": 1,
        "qd010_risk_share_rows": 1,
        "qd010_risk_rights_rows": 1,
        "qd010_unresolved_or_unsupported_rows": 0,
        "post_2021_rows": 0,
        "invalid_rows_filtered": 0,
    }
    audit = {"audit_counts": counts}
    subject.validate_audit_counts_against_outputs(manifest, audit, observed)
    with pytest.raises(subject.CY046BuildError, match="manifest/footer"):
        subject.validate_audit_counts_against_outputs(
            manifest,
            {"audit_counts": {**counts, "cy006_requested_rows": 12_624}},
            observed,
        )


def test_footer_only_metadata_and_scope_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "small.parquet"
    pd.DataFrame({"x": [1, 2]}).to_parquet(path, index=False)

    monkeypatch.setattr(
        subject.pq,
        "read_table",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("row read")),
    )
    facts = subject.parquet_footer_facts(path)
    assert facts["rows"] == 2
    assert [item["name"] for item in facts["schema"]] == ["x"]

    subject.assert_bounded_partition_path(
        "execution_5m/partition_year=2021/data_0.parquet", "CY008"
    )
    with pytest.raises(subject.CY046BuildError, match="post-2021"):
        subject.assert_bounded_partition_path(
            "execution_5m/partition_year=2022/data_0.parquet", "CY008"
        )
    with pytest.raises(subject.CY046BuildError, match="forbidden"):
        subject.assert_no_forbidden_identity_columns(["gap_id", "net_return"])
