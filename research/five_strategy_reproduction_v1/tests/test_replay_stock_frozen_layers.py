from pathlib import Path

import pytest

from research.five_strategy_reproduction_v1.replay_stock_frozen_layers import (
    DEFAULT_OUTPUT_ROOT,
    ensure_isolated,
)


def test_reproduction_root_and_children_are_allowed() -> None:
    assert ensure_isolated(DEFAULT_OUTPUT_ROOT) == DEFAULT_OUTPUT_ROOT.resolve()
    child = DEFAULT_OUTPUT_ROOT / "ogr"
    assert ensure_isolated(child) == child.resolve()


def test_output_outside_reproduction_root_is_rejected() -> None:
    with pytest.raises(ValueError, match="output must stay below"):
        ensure_isolated(Path("/tmp/not-the-reproduction-root"))
