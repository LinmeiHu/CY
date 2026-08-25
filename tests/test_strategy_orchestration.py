from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from cyq_game.strategy.markup_retest import StrategyStage, load_markup_retest_config
from cyq_game.strategy.orchestration import _parameters_for_validation
from cyq_game.strategy.panel import PanelBuildResult


def test_resealed_validation_loads_only_a_passing_economic_freeze(tmp_path) -> None:
    base = load_markup_retest_config()
    freeze = tmp_path / "freeze.json"
    config = replace(base, freeze_manifest=freeze)
    freeze.write_text(
        json.dumps(
            {
                "status": "FROZEN",
                "config_sha256": config.sha256,
                "economic_selection_snapshot_id": "entry-economic-selection-test",
                "p0_gate_event_id": "p0-test",
                "freeze_decision": "PASS",
                "selected_parameter_id": config.parameters.parameter_id,
                "selected_component": [
                    config.parameters.parameter_id,
                    "neighbor-a",
                    "neighbor-b",
                ],
                "final_parameters": config.parameters.canonical(),
            }
        ),
        encoding="utf-8",
    )

    selected = _parameters_for_validation(config, StrategyStage.RESEALED)

    assert selected == config.parameters


def test_no_trade_freeze_blocks_every_resealed_data_build(tmp_path) -> None:
    base = load_markup_retest_config()
    freeze = tmp_path / "freeze.json"
    config = replace(base, freeze_manifest=freeze)
    freeze.write_text(
        json.dumps(
            {
                "status": "FROZEN",
                "config_sha256": config.sha256,
                "economic_selection_snapshot_id": "entry-economic-selection-test",
                "p0_gate_event_id": "p0-test",
                "freeze_decision": "NO_TRADE",
                "final_parameters": None,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="NO_TRADE"):
        _parameters_for_validation(config, StrategyStage.RESEALED)


def test_legacy_frequency_only_freeze_cannot_unlock_resealed_data(tmp_path) -> None:
    base = load_markup_retest_config()
    freeze = tmp_path / "freeze.json"
    config = replace(base, freeze_manifest=freeze)
    freeze.write_text(
        json.dumps(
            {
                "status": "FROZEN",
                "config_sha256": config.sha256,
                "freeze_decision": "PASS",
                "selected_parameter_id": config.parameters.parameter_id,
                "final_parameters": config.parameters.canonical(),
                "source": "entry_frequency.json",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="economic-selection or P0"):
        _parameters_for_validation(config, StrategyStage.RESEALED)


def _resealed_panel(config_sha256: str, path: Path) -> PanelBuildResult:
    return PanelBuildResult(
        stage="resealed",
        status="COMPLETE",
        path=path,
        manifest_path=path / "manifest.json",
        rows=0,
        symbols=0,
        eligible_rows=0,
        strict_rows=0,
        coverage=0.0,
        config_sha256=config_sha256,
        panel_snapshot_id="panel-test",
    )


def test_direct_resealed_panel_fails_before_resolving_any_input(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cyq_game.strategy.panel as panel_module

    base = load_markup_retest_config()
    config = replace(base, freeze_manifest=tmp_path / "missing-freeze.json")
    touched = False

    def forbidden(*args, **kwargs):
        nonlocal touched
        touched = True
        raise AssertionError("resealed input resolution ran before freeze validation")

    monkeypatch.setattr(panel_module, "_resolve_corporate_action_inputs", forbidden)

    with pytest.raises(FileNotFoundError, match="frozen v1 manifest"):
        panel_module.build_causal_panel(config, StrategyStage.RESEALED)
    assert touched is False


def test_direct_resealed_signal_and_label_builds_fail_before_input_inventory(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cyq_game.strategy.labels as labels_module
    import cyq_game.strategy.signals as signals_module

    base = load_markup_retest_config()
    config = replace(base, freeze_manifest=tmp_path / "missing-freeze.json")
    panel_path = tmp_path / "panel"
    panel_path.mkdir()
    panel = _resealed_panel(config.sha256, panel_path)
    touched = False

    def forbidden(*args, **kwargs):
        nonlocal touched
        touched = True
        raise AssertionError("input inventory ran before freeze validation")

    monkeypatch.setattr(signals_module, "verify_registered_asset_inventory", forbidden)

    with pytest.raises(FileNotFoundError, match="frozen v1 manifest"):
        signals_module.build_strategy_signals(
            config, panel, StrategyStage.RESEALED
        )
    with pytest.raises(FileNotFoundError, match="frozen v1 manifest"):
        labels_module.build_future_labels(config, panel, StrategyStage.RESEALED)
    assert touched is False


def test_direct_resealed_exact_replay_fails_before_any_panel_read(tmp_path) -> None:
    from cyq_game.strategy.exact_replay import evaluate_exact_parameter_lattice_files

    base = load_markup_retest_config()
    config = replace(base, freeze_manifest=tmp_path / "missing-freeze.json")

    with pytest.raises(FileNotFoundError, match="frozen v1 manifest"):
        evaluate_exact_parameter_lattice_files(
            (),
            config,
            StrategyStage.RESEALED,
            (config.parameters,),
            panel_snapshot_id="forbidden-resealed-panel",
        )
