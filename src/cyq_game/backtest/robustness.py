"""Independent development-sample robustness runs.

Every variant gets a fresh engine, event log, state path, and walk-forward run.  The
final holdout is never passed to the engine by this module.  Results are evidence
for review; they do not mutate the production/research configuration.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from cyq_game.backtest.engine import BacktestEngine
from cyq_game.config import SystemConfig
from cyq_game.data import DataExecutionAuthorization, DataOperation, PITStore


@dataclass(frozen=True)
class RobustnessVariant:
    name: str
    rationale: str
    changed_parameters: dict[str, str | float | bool]
    config: SystemConfig


def build_robustness_variants(config: SystemConfig) -> tuple[RobustnessVariant, ...]:
    """Build the predeclared ablation and parameter-sensitivity matrix."""

    alternative_engine = "uniform" if config.chip.engine == "cohort" else "cohort"
    return (
        RobustnessVariant(
            "baseline",
            "declared configuration",
            {},
            config,
        ),
        RobustnessVariant(
            "chip_engine_alternative",
            "ablate the cohort/uniform chip replacement assumption",
            {"chip.engine": alternative_engine},
            replace(config, chip=replace(config.chip, engine=alternative_engine)),
        ),
        RobustnessVariant(
            "sector_alpha_on",
            "measure incremental sector-direction evidence before any promotion",
            {"decision.sector_alpha_enabled": True},
            replace(
                config,
                decision=replace(config.decision, sector_alpha_enabled=True),
            ),
        ),
        RobustnessVariant(
            "lambda_0_5",
            "lower turnover-replacement sensitivity endpoint",
            {"chip.lambda_turnover": 0.5},
            replace(config, chip=replace(config.chip, lambda_turnover=0.5)),
        ),
        RobustnessVariant(
            "lambda_1_5",
            "upper turnover-replacement sensitivity endpoint",
            {"chip.lambda_turnover": 1.5},
            replace(config, chip=replace(config.chip, lambda_turnover=1.5)),
        ),
        RobustnessVariant(
            "kelly_0_10",
            "lower approved fractional-Kelly endpoint",
            {"portfolio.kelly_fraction": 0.10},
            replace(config, portfolio=replace(config.portfolio, kelly_fraction=0.10)),
        ),
        RobustnessVariant(
            "kelly_0_25",
            "upper approved fractional-Kelly endpoint",
            {"portfolio.kelly_fraction": 0.25},
            replace(config, portfolio=replace(config.portfolio, kelly_fraction=0.25)),
        ),
    )


def run_robustness_suite(
    config: SystemConfig,
    *,
    suite_id: str,
    start: date,
    end: date,
    data_authorization: DataExecutionAuthorization,
    store_factory: Callable[[SystemConfig], PITStore] | None = None,
    max_workers: int = 2,
) -> tuple[Path, dict[str, Any]]:
    """Run the fixed matrix with the final holdout locked for every variant."""

    if config.mode != "research":
        raise ValueError("robustness suites require mode=research")
    if data_authorization.operation is not DataOperation.ROBUSTNESS:
        raise ValueError("robustness suite requires ROBUSTNESS data authorization")
    suite_dir = config.run_dir / suite_id
    if suite_dir.exists():
        raise FileExistsError(f"robustness suite already exists: {suite_dir}")
    suite_dir.mkdir(parents=True, exist_ok=False)

    variants = build_robustness_variants(config)

    def run_variant(variant: RobustnessVariant) -> dict[str, Any]:
        variant_run_id = f"{suite_id}--{variant.name}"
        store = (
            store_factory(variant.config)
            if store_factory is not None
            else PITStore(variant.config.database_path)
        )
        try:
            result = BacktestEngine(
                variant.config,
                run_id=variant_run_id,
                config_text=config_to_text(variant.config),
                data_authorization=data_authorization,
                hypothesis=f"robustness:{variant.name}:{variant.rationale}",
                store=store,
            ).run(start, end, access_final_holdout=False)
        finally:
            store.close()
        if result.holdout_tainted:
            raise RuntimeError(f"holdout unexpectedly tainted by {variant.name}")
        return {
            "name": variant.name,
            "status": "COMPLETE",
            "rationale": variant.rationale,
            "changed_parameters": variant.changed_parameters,
            "run_id": result.run_id,
            "run_dir": str(result.run_dir.resolve()),
            "holdout_tainted": result.holdout_tainted,
            "metrics": result.metrics,
        }

    # Variants are independent and each owns a separate run directory/database.
    # Keep a small cap to avoid overwhelming the shared Parquet/DuckDB storage.
    worker_count = max(1, min(max_workers, len(variants)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        rows = list(executor.map(run_variant, variants))

    baseline = rows[0]["metrics"]
    for row in rows:
        row["delta_vs_baseline"] = _metric_delta(row["metrics"], baseline)
    report: dict[str, Any] = {
        "suite_id": suite_id,
        "status": "COMPLETE",
        "final_holdout_locked": True,
        "methodology": (
            "independent PIT-safe walk-forward reruns on the development sample; "
            "final holdout locked"
        ),
        "promotion_policy": (
            "results require human review across multiple OOS slices; this suite never "
            "changes configuration or enables live trading"
        ),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "variant_count": len(rows),
        "variants": rows,
    }
    report_path = suite_dir / "robustness.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return report_path, report


def config_to_text(config: SystemConfig) -> str:
    """Serialize the effective immutable configuration for audit hashing."""

    return yaml.safe_dump(_serializable(asdict(config)), sort_keys=True)


def _metric_delta(
    metrics: dict[str, float | int], baseline: dict[str, float | int]
) -> dict[str, float | int]:
    selected = ("total_return", "sharpe", "max_drawdown", "fills", "total_cost")
    return {key: metrics.get(key, 0) - baseline.get(key, 0) for key in selected}


def _serializable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value
