from __future__ import annotations

from pathlib import Path

import pytest

from cyq_game.config import load_config


def test_live_trading_cannot_be_enabled(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.yaml"
    path.write_text("mode: paper\nlive_trading_enabled: true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="live trading is not available"):
        load_config(path)


def test_researched_parameter_bounds_are_enforced(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(
        "mode: research\nchip:\n  grid_step_pct: 0.02\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="grid step"):
        load_config(path)
