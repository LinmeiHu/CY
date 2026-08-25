"""Single public orchestration path for MARKUP_RETEST v1 stages.

The command layer is deliberately thin: stage dates come only from the frozen
YAML configuration and every stage consumes the same causal panel and lifecycle
implementation.  This module contains no SQL thresholds and no signal logic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cyq_game.strategy.labels import LabelBuildResult, build_future_labels
from cyq_game.strategy.markup_retest import (
    MarkupRetestConfig,
    StrategyParameters,
    StrategyStage,
    load_passing_frozen_parameters,
)
from cyq_game.strategy.panel import PanelBuildResult, build_causal_panel
from cyq_game.strategy.signals import SignalBuildResult, build_strategy_signals


@dataclass(frozen=True)
class StrategyStageResult:
    command: str
    stage: str
    status: str
    config_path: str
    config_sha256: str
    parameter_id: str
    panel: dict[str, Any]
    signals: dict[str, Any]
    labels: dict[str, Any]
    coverage_gate: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_strategy_stage(
    config_path: str | Path,
    stage: StrategyStage | str,
    *,
    reuse: bool = True,
    threads: int | None = None,
) -> StrategyStageResult:
    """Materialize and validate one configured validation stage.

    ``development`` is intentionally rejected here.  Parameter research has a
    separate command so validation can never silently become model selection.
    """

    config = MarkupRetestConfig.load(config_path)
    selected_stage = StrategyStage(stage)
    if selected_stage == StrategyStage.DEVELOPMENT:
        raise ValueError("development must use `strategy research --stage development`")
    parameters = _parameters_for_validation(config, selected_stage)
    panel, signals, labels = _build_stage_artifacts(
        config,
        selected_stage,
        parameters=parameters,
        reuse=reuse,
        threads=threads,
    )
    coverage_gate = (
        "PASS"
        if selected_stage == StrategyStage.WEEK
        or panel.coverage >= config.quality.minimum_board_coverage
        else "FAIL"
    )
    status = "PASS" if coverage_gate == "PASS" else "FAIL"
    return StrategyStageResult(
        command="validate",
        stage=selected_stage.value,
        status=status,
        config_path=str(config.path),
        config_sha256=config.sha256,
        parameter_id=parameters.parameter_id,
        panel=panel.to_dict(),
        signals=signals.to_dict(),
        labels=labels.to_dict(),
        coverage_gate=coverage_gate,
    )


def prepare_development_research(
    config_path: str | Path,
    stage: StrategyStage | str,
    *,
    reuse: bool = True,
    threads: int | None = None,
) -> StrategyStageResult:
    """Prepare the one reusable development panel and physically separate labels.

    The parameter evaluator consumes these artifacts without rebuilding chip
    state.  The evaluator is invoked by the same public command after this
    preparation step; this function remains separately testable to enforce the
    2023 hard boundary at the file layer.
    """

    config = MarkupRetestConfig.load(config_path)
    selected_stage = StrategyStage(stage)
    if selected_stage != StrategyStage.DEVELOPMENT:
        raise ValueError("strategy research only accepts --stage development")
    panel, signals, labels = _build_stage_artifacts(
        config,
        selected_stage,
        parameters=config.parameters,
        reuse=reuse,
        threads=threads,
    )
    coverage_gate = "PASS" if panel.coverage >= config.quality.minimum_board_coverage else "FAIL"
    return StrategyStageResult(
        command="research",
        stage=selected_stage.value,
        status="ARTIFACTS_READY" if coverage_gate == "PASS" else "FAIL",
        config_path=str(config.path),
        config_sha256=config.sha256,
        parameter_id=config.parameters.parameter_id,
        panel=panel.to_dict(),
        signals=signals.to_dict(),
        labels=labels.to_dict(),
        coverage_gate=coverage_gate,
    )


def _build_stage_artifacts(
    config: MarkupRetestConfig,
    stage: StrategyStage,
    *,
    parameters: StrategyParameters,
    reuse: bool,
    threads: int | None,
) -> tuple[PanelBuildResult, SignalBuildResult, LabelBuildResult]:
    panel = build_causal_panel(config, stage, reuse=reuse, threads=threads)
    signals = build_strategy_signals(
        config,
        panel,
        stage,
        parameters=parameters,
        reuse=reuse,
        threads=threads,
    )
    labels = build_future_labels(config, panel, stage, reuse=reuse, threads=threads)
    return panel, signals, labels


def _parameters_for_validation(
    config: MarkupRetestConfig, stage: StrategyStage
) -> StrategyParameters:
    if stage != StrategyStage.RESEALED:
        return config.parameters
    return load_passing_frozen_parameters(config)
