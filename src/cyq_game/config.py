from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ChipConfig:
    grid_step_pct: float = 0.01
    lambda_turnover: float = 1.0
    engine: str = "cohort"
    smoothing_sigma_bins: float = 1.5
    peak_prominence: float = 0.03
    warmup_days: int = 60


@dataclass(frozen=True)
class DecisionConfig:
    observability_min: float = 0.55
    execution_probability_min: float = 0.80
    q_margin_r: float = 0.25
    regime_min_probability: float = 0.55
    regime_margin: float = 0.10
    sector_alpha_enabled: bool = False


@dataclass(frozen=True)
class PortfolioConfig:
    kelly_fraction: float = 0.15
    single_name_cap: float = 0.10
    sector_cap: float = 0.30
    theme_cap: float = 0.20
    adv_participation_cap: float = 0.05
    min_order_notional: float = 0.0
    soft_drawdown: float = 0.08
    hard_drawdown: float = 0.12
    extreme_gross_multiplier: float = 0.50
    allow_unreliable_size: bool = False


@dataclass(frozen=True)
class ExecutionConfig:
    commission_bps: float = 3.0
    stamp_duty_sell_bps: float = 5.0
    slippage_bps: float = 5.0
    impact_coefficient: float = 0.10
    lot_size: int = 100
    t_plus_one: bool = True
    default_price_limit_pct: float = 0.10


@dataclass(frozen=True)
class BacktestConfig:
    final_holdout_fraction: float = 0.20
    purge_days: int = 5
    embargo_days: int = 5
    allow_holdout_access: bool = False


@dataclass(frozen=True)
class ShadowConfig:
    cash_tolerance: float = 0.01
    quantity_tolerance: int = 0
    max_snapshot_age_seconds: int = 900


@dataclass(frozen=True)
class SystemConfig:
    mode: str
    database_path: Path
    event_store_path: Path
    run_dir: Path
    seed: int
    live_trading_enabled: bool
    initial_cash: float
    benchmark: str
    chip: ChipConfig = field(default_factory=ChipConfig)
    decision: DecisionConfig = field(default_factory=DecisionConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    shadow: ShadowConfig = field(default_factory=ShadowConfig)


def _section(cls: type[Any], raw: dict[str, Any], name: str) -> Any:
    return cls(**raw.get(name, {}))


def load_config(path: str | Path) -> SystemConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("configuration root must be a mapping")
    cfg = SystemConfig(
        mode=str(raw.get("mode", "research")),
        database_path=Path(str(raw.get("database_path", "data/cyq_game.sqlite3"))),
        event_store_path=Path(str(raw.get("event_store_path", "runs/events.jsonl"))),
        run_dir=Path(str(raw.get("run_dir", "runs"))),
        seed=int(raw.get("seed", 0)),
        live_trading_enabled=bool(raw.get("live_trading_enabled", False)),
        initial_cash=float(raw.get("initial_cash", 10_000_000)),
        benchmark=str(raw.get("benchmark", "000985.CSI")),
        chip=_section(ChipConfig, raw, "chip"),
        decision=_section(DecisionConfig, raw, "decision"),
        portfolio=_section(PortfolioConfig, raw, "portfolio"),
        execution=_section(ExecutionConfig, raw, "execution"),
        backtest=_section(BacktestConfig, raw, "backtest"),
        shadow=_section(ShadowConfig, raw, "shadow"),
    )
    validate_config(cfg)
    return cfg


def validate_config(cfg: SystemConfig) -> None:
    if cfg.live_trading_enabled:
        raise ValueError("live trading is not available without an approved broker adapter")
    if not 0.003 <= cfg.chip.grid_step_pct <= 0.015:
        raise ValueError("chip grid step must be within the researched 0.3%-1.5% range")
    if not 0.5 <= cfg.chip.lambda_turnover <= 1.5:
        raise ValueError("lambda_turnover must be in [0.5, 1.5]")
    if cfg.chip.engine not in {"cohort", "uniform"}:
        raise ValueError("chip engine must be cohort or uniform")
    if not 0.10 <= cfg.portfolio.kelly_fraction <= 0.25:
        raise ValueError("fractional Kelly kappa must be in [0.10, 0.25]")
    if cfg.portfolio.min_order_notional < 0.0:
        raise ValueError("min_order_notional must be non-negative")
    if cfg.mode not in {"research", "paper", "shadow"}:
        raise ValueError("mode must be research, paper, or shadow")
    if cfg.shadow.cash_tolerance < 0:
        raise ValueError("shadow cash_tolerance must be non-negative")
    if cfg.shadow.quantity_tolerance < 0:
        raise ValueError("shadow quantity_tolerance must be non-negative")
    if cfg.shadow.max_snapshot_age_seconds <= 0:
        raise ValueError("shadow max_snapshot_age_seconds must be positive")
