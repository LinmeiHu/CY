from __future__ import annotations

from pathlib import Path

from cyq_game.backtest.robustness import build_robustness_variants, config_to_text
from cyq_game.config import SystemConfig


def test_robustness_matrix_is_predeclared_and_does_not_mutate_base() -> None:
    base = SystemConfig(
        mode="research",
        database_path=Path("pit.sqlite3"),
        event_store_path=Path("events.jsonl"),
        run_dir=Path("runs"),
        seed=7,
        live_trading_enabled=False,
        initial_cash=1_000_000,
        benchmark="000985.CSI",
    )
    variants = build_robustness_variants(base)
    assert [variant.name for variant in variants] == [
        "baseline",
        "chip_engine_alternative",
        "sector_alpha_on",
        "lambda_0_5",
        "lambda_1_5",
        "kelly_0_10",
        "kelly_0_25",
    ]
    assert base.chip.engine == "cohort"
    assert base.decision.sector_alpha_enabled is False
    assert "live_trading_enabled: false" in config_to_text(variants[0].config)
