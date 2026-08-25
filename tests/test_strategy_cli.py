from __future__ import annotations

import argparse

import pytest

from cyq_game import cli


def test_strategy_validate_parser_has_only_validation_stages() -> None:
    args = cli._parser().parse_args(
        ["strategy", "validate", "--stage", "week", "--threads", "4"]
    )
    assert args.command == "strategy"
    assert args.strategy_action == "validate"
    assert args.stage == "week"
    assert args.threads == 4


def test_strategy_research_parser_has_only_development_stage() -> None:
    args = cli._parser().parse_args(
        ["strategy", "research", "--stage", "development", "--no-reuse"]
    )
    assert args.strategy_action == "research"
    assert args.stage == "development"
    assert args.no_reuse is True


@pytest.mark.parametrize(
    "argv",
    (
        ["strategy", "validate", "--stage", "development"],
        ["strategy", "research", "--stage", "year"],
    ),
)
def test_strategy_parser_rejects_cross_stage_commands(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        cli._parser().parse_args(argv)


def test_strategy_dispatch_uses_single_orchestrator(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    class Result:
        status = "PASS"

        def to_dict(self) -> dict[str, str]:
            return {"status": self.status}

    def validate(
        config: str, stage: str, *, reuse: bool, threads: int | None
    ) -> Result:
        observed.update(
            {"config": config, "stage": stage, "reuse": reuse, "threads": threads}
        )
        return Result()

    import cyq_game.strategy.orchestration as orchestration

    monkeypatch.setattr(orchestration, "validate_strategy_stage", validate)
    args = argparse.Namespace(
        strategy_action="validate",
        config="one.yaml",
        stage="week",
        no_reuse=True,
        threads=7,
    )
    assert cli._markup_retest_strategy(args) == 0
    assert observed == {
        "config": "one.yaml",
        "stage": "week",
        "reuse": False,
        "threads": 7,
    }
