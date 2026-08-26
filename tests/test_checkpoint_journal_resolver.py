from __future__ import annotations

from pathlib import Path

import pytest

from cyq_game.strategy.checkpoint_journal_resolver import (
    LEGACY_DEFAULT_MODE,
    ChipResolverMode,
    build_chip_resolver,
)


def test_legacy_operator_remains_the_explicit_default() -> None:
    calls = []

    def factory(root: str | Path) -> tuple[str, Path]:
        calls.append(Path(root))
        return "legacy", Path(root)

    result = build_chip_resolver(legacy_root="/tmp/legacy", legacy_factory=factory)
    assert LEGACY_DEFAULT_MODE is ChipResolverMode.LEGACY_OPERATOR
    assert result == ("legacy", Path("/tmp/legacy"))
    assert calls == [Path("/tmp/legacy")]


def test_checkpoint_journal_mode_requires_complete_explicit_configuration() -> None:
    with pytest.raises(ValueError, match="configuration is incomplete"):
        build_chip_resolver(mode=ChipResolverMode.CHECKPOINT_JOURNAL)
    with pytest.raises(ValueError, match="legacy root"):
        build_chip_resolver(mode=ChipResolverMode.LEGACY_OPERATOR)
