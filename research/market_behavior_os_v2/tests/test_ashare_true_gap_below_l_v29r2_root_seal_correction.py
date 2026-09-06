from __future__ import annotations

import stat
from pathlib import Path

import pytest

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_fact_rollforward_root_seal_correction_asset_v29r2 as builder,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2_root_seal_correction as runner,
)


def _writable(path: Path) -> bool:
    return bool(path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _stage_identity() -> dict[str, object]:
    stage = {
        "classified_comparator": {"bounded": True},
        "parent_signals": 197,
        "selected_signals": 186,
        "rejected_signals": 11,
        "selected_by_signal_year": {
            "2022": 40,
            "2023": 10,
            "2024": 68,
            "2025": 36,
            "2026": 32,
        },
        "route_audit": {"rows": 7925},
        "selector_outputs_strict_exact": True,
        "execution_contract": {"target": "A67"},
    }
    return {
        "cy063_stage_a_verification": stage,
        "asset_id": "CY-065",
        "superseded_cy064": {"asset_id": "CY-064"},
    }


def test_safe_seal_makes_entire_regular_tree_read_only(tmp_path: Path) -> None:
    root = tmp_path / "root"
    nested = root / "stage" / "lane"
    nested.mkdir(parents=True)
    (root / "seal.json").write_text("seal", encoding="utf-8")
    (nested / "partial.parquet").write_bytes(b"partial")

    runner.seal_dedicated_tree_without_following(root)

    assert not _writable(root)
    assert all(not _writable(path) for path in root.rglob("*"))


def test_safe_seal_rejects_root_symlink_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    target_file = target / "keep-writable"
    target_file.write_text("x", encoding="utf-8")
    link = tmp_path / "root-link"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(runner.RootSealCorrectionError, match="unsafe dedicated root"):
        runner.seal_dedicated_tree_without_following(link)

    assert _writable(target)
    assert _writable(target_file)


def test_safe_seal_rejects_inner_symlink_before_chmod(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    regular = root / "regular"
    regular.write_text("x", encoding="utf-8")
    target = tmp_path / "outside"
    target.write_text("outside", encoding="utf-8")
    (root / "link").symlink_to(target)

    with pytest.raises(runner.RootSealCorrectionError, match="refusing symlink"):
        runner.seal_dedicated_tree_without_following(root)

    assert _writable(root)
    assert _writable(regular)
    assert _writable(target)


def test_verify_only_create_then_raise_seals_root_and_refuses_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CreateThenRaise(RuntimeError):
        pass

    verification_root = tmp_path / "verification"
    stage_b_root = tmp_path / "stage-b"
    asset = tmp_path / "asset"
    parent = tmp_path / "parent.parquet"
    monkeypatch.setattr(runner, "EXPECTED_VERIFICATION_ROOT", verification_root)
    monkeypatch.setattr(runner, "EXPECTED_STAGE_B_ROOT", stage_b_root)
    monkeypatch.setattr(runner, "verify_asset", lambda *_args: _stage_identity())
    original_mkdir = Path.mkdir

    def create_then_raise(self: Path, *args: object, **kwargs: object) -> None:
        original_mkdir(self, *args, **kwargs)
        if self == verification_root:
            (self / "partial.freeze").write_text("partial", encoding="utf-8")
            raise CreateThenRaise

    monkeypatch.setattr(Path, "mkdir", create_then_raise)

    with pytest.raises(CreateThenRaise):
        runner.run_verify_only(asset, parent, verification_root, stage_b_root)

    assert not _writable(verification_root)
    assert not _writable(verification_root / "partial.freeze")
    with pytest.raises(runner.RootSealCorrectionError, match="non-pristine"):
        runner.run_verify_only(asset, parent, verification_root, stage_b_root)


def test_stage_b_create_then_raise_seals_root_and_refuses_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CreateThenRaise(RuntimeError):
        pass

    output_root = tmp_path / "stage-b"
    verification_root = tmp_path / "verification"
    asset = tmp_path / "asset"
    parent = tmp_path / "parent.parquet"
    outcomes = tmp_path / "outcomes.parquet"
    daily = tmp_path / "daily.parquet"
    outer_sha = "d" * 64

    def fake_sha(path: Path) -> str:
        path = Path(path).resolve()
        selected = (runner.CY063_OUTPUT_ROOT / "stage_a/selected_entries.parquet").resolve()
        if path == selected:
            return builder.cy064_builder.CY063_STAGE_HASHES["selected_entries.parquet"]
        return f"sha:{path}"

    identity = {
        "parent_sources": {
            role: {"path": str(path), "sha256": fake_sha(path)}
            for role, path in (
                ("selected", parent),
                ("outcomes", outcomes),
                ("outcome_daily", daily),
            )
        }
    }
    monkeypatch.setattr(runner, "EXPECTED_STAGE_B_ROOT", output_root)
    monkeypatch.setattr(
        runner,
        "verify_outer_freeze",
        lambda *_args: {
            "outer_freeze_sha256": outer_sha,
            "outer_freeze_path": str(verification_root / "verified_stage_a_freeze.json"),
            "asset_identity": identity,
            "cy063_stage_a_hashes": dict(builder.cy064_builder.CY063_STAGE_HASHES),
        },
    )
    monkeypatch.setattr(runner, "sha256", fake_sha)
    original_mkdir = Path.mkdir

    def create_then_raise(self: Path, *args: object, **kwargs: object) -> None:
        original_mkdir(self, *args, **kwargs)
        if self == output_root:
            (self / "partial.seal").write_text("partial", encoding="utf-8")
            raise CreateThenRaise

    monkeypatch.setattr(Path, "mkdir", create_then_raise)

    with pytest.raises(CreateThenRaise):
        runner.run_stage_b(
            asset,
            parent,
            outcomes,
            daily,
            verification_root,
            output_root,
            outer_sha,
        )

    assert not _writable(output_root)
    assert not _writable(output_root / "partial.seal")
    with pytest.raises(runner.RootSealCorrectionError, match="repeated/non-pristine"):
        runner.run_stage_b(
            asset,
            parent,
            outcomes,
            daily,
            verification_root,
            output_root,
            outer_sha,
        )


def test_asset_build_create_then_raise_seals_root_and_refuses_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CreateThenRaise(RuntimeError):
        pass

    asset_root = tmp_path / "asset"
    runner_path = tmp_path / "runner.py"
    runner_path.write_text("# frozen runner\n", encoding="utf-8")
    monkeypatch.setattr(builder, "EXPECTED_ROOT", asset_root)
    monkeypatch.setattr(builder, "NEW_RUNNER", runner_path)
    monkeypatch.setattr(builder, "validate_dependencies", lambda *_args, **_kwargs: {})
    original_mkdir = Path.mkdir

    def create_then_raise(self: Path, *args: object, **kwargs: object) -> None:
        original_mkdir(self, *args, **kwargs)
        if self == asset_root:
            (self / "partial.manifest").write_text("partial", encoding="utf-8")
            raise CreateThenRaise

    monkeypatch.setattr(Path, "mkdir", create_then_raise)

    with pytest.raises(CreateThenRaise):
        builder.build(asset_root, runner_path)

    assert not _writable(asset_root)
    assert not _writable(asset_root / "partial.manifest")
    with pytest.raises(builder.RootSealCorrectionAssetError, match="non-pristine"):
        builder.build(asset_root, runner_path)


def test_cy064_blocked_wrapper_and_absent_roots_revalidate() -> None:
    result = builder.validate_cy064_blocked_predecessor()

    assert result["valid"] is True
    assert result["manifest_sha256"] == builder.CY064_HASHES["asset_manifest"]
