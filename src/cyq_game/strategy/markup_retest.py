"""Causal accumulation-breakout-retest lifecycle used by every v1 command.

This module intentionally contains no label access, ranking, Top-N selection or
portfolio capacity logic.  Every qualifying event is emitted independently.
Participant language describes falsifiable latent hypotheses, never accounts.
"""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import yaml

from cyq_game.chip.ensemble_v2 import AnchorRetentionEstimate
from cyq_game.chip.peak_versions import PEAK_DEFINITION_VERSION
from cyq_game.chip.price_coordinate import rebase_economic_price
from cyq_game.data.registry import DataAssetRegistry
from cyq_game.domain import (
    ChipLifecycleState,
    ExitReason,
    FutureDataError,
    StrategyFamily,
)
from cyq_game.game.decision import EdgeCard
from cyq_game.strategy.semantic_contract import PANEL_SCHEMA_VERSION, STRATEGY_VERSION

FORBIDDEN_SIGNAL_FIELDS = frozenset(
    {
        "future_return",
        "forward_return",
        "return_5d",
        "return_10d",
        "return_20d",
        "gross_return_5d",
        "gross_return_10d",
        "gross_return_20d",
        "net_return_5d",
        "net_return_10d",
        "net_return_20d",
        "mfe",
        "mae",
        "mfe_20d",
        "mae_20d",
        "exit_price",
        "exit_date",
        "entry_date",
        "entry_price",
        "label_available_at",
        "label_valid",
        "label_reason",
        "corporate_actions_in_horizon",
        "maximum_future_high",
        "minimum_future_low",
        "lifecycle_return",
    }
)


class StrategyStage(StrEnum):
    WEEK = "week"
    YEAR = "year"
    DEVELOPMENT = "development"
    RESEALED = "resealed"


class ChipMassMethod(StrEnum):
    """How mass inside a frozen lifecycle price band is measured."""

    HISTOGRAM_EXACT = "HISTOGRAM_EXACT"
    QUANTILE_CDF_PROXY = "QUANTILE_CDF_PROXY"


@dataclass(frozen=True)
class ChipMassProfile:
    """Immutable daily chip CDF; exact histograms are never normalized here."""

    prices: tuple[float, ...]
    cumulative_mass: tuple[float, ...]
    method: ChipMassMethod

    @classmethod
    def from_histogram(
        cls,
        prices: Sequence[float],
        masses: Sequence[float],
        *,
        mass_tolerance: float,
    ) -> ChipMassProfile:
        if len(prices) != len(masses) or not prices:
            raise ValueError("chip histogram prices and masses must have equal non-zero length")
        pairs = sorted(
            (float(price), float(mass))
            for price, mass in zip(prices, masses, strict=True)
        )
        if any(not math.isfinite(price) or not math.isfinite(mass) for price, mass in pairs):
            raise ValueError("chip histogram contains non-finite values")
        if any(price <= 0 or mass < 0 for price, mass in pairs):
            raise ValueError("chip histogram requires positive prices and non-negative mass")
        combined: list[tuple[float, float]] = []
        for price, mass in pairs:
            if combined and price == combined[-1][0]:
                combined[-1] = (price, combined[-1][1] + mass)
            else:
                combined.append((price, mass))
        total = math.fsum(mass for _, mass in combined)
        if abs(total - 1.0) > mass_tolerance:
            raise ValueError(
                f"chip histogram mass is {total:.17g}; tolerance is {mass_tolerance:.3g}"
            )
        cumulative: list[float] = []
        running = 0.0
        for _, mass in combined:
            running += mass
            cumulative.append(running)
        return cls(
            prices=tuple(price for price, _ in combined),
            cumulative_mass=tuple(cumulative),
            method=ChipMassMethod.HISTOGRAM_EXACT,
        )

    @classmethod
    def from_quantiles(
        cls,
        *,
        p01: float,
        p10: float,
        p50: float,
        p90: float,
        p99: float,
    ) -> ChipMassProfile:
        raw = (
            (float(p01), 0.01),
            (float(p10), 0.10),
            (float(p50), 0.50),
            (float(p90), 0.90),
            (float(p99), 0.99),
        )
        if any(not math.isfinite(price) or price <= 0 for price, _ in raw):
            raise ValueError("chip quantiles must be finite positive prices")
        if any(left[0] > right[0] for left, right in pairwise(raw)):
            raise ValueError("chip quantiles must be monotone")
        if raw[0][0] == raw[-1][0]:
            return cls(
                prices=(raw[0][0],),
                cumulative_mass=(1.0,),
                method=ChipMassMethod.QUANTILE_CDF_PROXY,
            )
        collapsed: list[tuple[float, float]] = []
        for price, cumulative in raw:
            if collapsed and price == collapsed[-1][0]:
                collapsed[-1] = (price, cumulative)
            else:
                collapsed.append((price, cumulative))
        return cls(
            prices=tuple(price for price, _ in collapsed),
            cumulative_mass=tuple(cumulative for _, cumulative in collapsed),
            method=ChipMassMethod.QUANTILE_CDF_PROXY,
        )

    def cdf(self, price: float, *, include_equal: bool = True) -> float:
        if len(self.prices) == 1:
            boundary = self.prices[0]
            return 1.0 if price > boundary or (include_equal and price == boundary) else 0.0
        if self.method == ChipMassMethod.HISTOGRAM_EXACT:
            index = (
                bisect_right(self.prices, price)
                if include_equal
                else bisect_left(self.prices, price)
            )
            return self.cumulative_mass[index - 1] if index else 0.0
        if price < self.prices[0]:
            return 0.0
        if price > self.prices[-1]:
            return 1.0
        right = bisect_right(self.prices, price)
        if right == 0:
            return 0.0
        if right >= len(self.prices):
            return self.cumulative_mass[-1]
        left = right - 1
        low_price = self.prices[left]
        high_price = self.prices[right]
        weight = (price - low_price) / (high_price - low_price)
        return self.cumulative_mass[left] + weight * (
            self.cumulative_mass[right] - self.cumulative_mass[left]
        )

    def mass_between(self, lower: float, upper: float) -> float:
        if upper < lower:
            raise ValueError("chip band upper bound is below lower bound")
        if len(self.prices) == 1:
            return 1.0 if lower <= self.prices[0] <= upper else 0.0
        lower_mass = self.cdf(
            lower,
            include_equal=self.method != ChipMassMethod.QUANTILE_CDF_PROXY,
        )
        if self.method == ChipMassMethod.HISTOGRAM_EXACT:
            lower_mass = self.cdf(lower, include_equal=False)
        return max(0.0, self.cdf(upper) - lower_mass)


@dataclass(frozen=True)
class StageBoundary:
    name: StrategyStage
    start: date
    end: date
    history_start: date
    max_input_date: date
    min_input_date: date | None = None
    symbols: tuple[str, ...] = ()

    def years(self) -> tuple[int, ...]:
        return tuple(range(self.history_start.year, self.end.year + 1))

    def assert_date(self, value: date, *, source: str) -> None:
        if value > self.max_input_date:
            raise FutureDataError(
                f"{self.name.value} cannot read {source} dated {value}; "
                f"maximum is {self.max_input_date}"
            )
        if self.min_input_date is not None and value < self.min_input_date:
            # Resealed validation may use frozen pre-2024 history as state input.
            # This lower bound applies only to evaluation rows, not warm-up rows.
            if source == "evaluation":
                raise FutureDataError(
                    f"{self.name.value} evaluation cannot include {value}; "
                    f"minimum is {self.min_input_date}"
                )


@dataclass(frozen=True)
class StrategyWindows:
    accumulation: int
    recent_evidence: int
    retest_min: int
    retest_max: int
    exit_confirmation: int
    max_holding: int
    cooldown: int
    label_horizon: int
    embargo: int


@dataclass(frozen=True)
class FixedThresholds:
    high_turnover_quantile: float
    low_price_impact_quantile: float
    support_tolerance_atr: float
    retest_volume_ratio_max: float
    retest_turnover_ratio_max: float
    recent_band_overlap_floor: float
    anchor_retention_floor: float
    anchor_severe_retention_floor: float
    anchor_band_expansion_ratio_max: float
    anchor_peak_count_increase_max: int
    max_model_disagreement_atr: float
    setup_component_count: int
    distribution_component_count: int


@dataclass(frozen=True)
class StrategyParameters:
    setup_score_min: float
    breakout_buffer_atr: float
    max_retest_depth_atr: float
    min_cost_migration_atr: float
    distribution_score_min: float
    protective_stop_atr: float

    def canonical(self) -> dict[str, float]:
        return {
            "setup_score_min": self.setup_score_min,
            "breakout_buffer_atr": self.breakout_buffer_atr,
            "max_retest_depth_atr": self.max_retest_depth_atr,
            "min_cost_migration_atr": self.min_cost_migration_atr,
            "distribution_score_min": self.distribution_score_min,
            "protective_stop_atr": self.protective_stop_atr,
        }

    @property
    def parameter_id(self) -> str:
        raw = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class ExecutionSettings:
    decision_time: time
    next_window_end: time
    max_entry_wait_trading_days: int
    nominal_capital_per_signal: float
    fee_bps: float
    slippage_bps: float
    impact_bps: float

    @property
    def one_way_cost_fraction(self) -> float:
        return (self.fee_bps + self.slippage_bps + self.impact_bps) / 10_000.0


@dataclass(frozen=True)
class QualitySettings:
    minimum_board_coverage: float
    mass_tolerance: float
    calibration_ece_max: float
    annual_signal_min: int
    annual_signal_max: int
    mean_signal_min: int
    mean_signal_max: int
    current_industry_grade: str
    unknown_industry_fallback: str


@dataclass(frozen=True)
class AssetPaths:
    daily_asset_id: str
    minute_asset_id: str
    chip_feature_asset_id: str
    chip_lineage_asset_id: str | None
    corporate_action_asset_id: str
    daily_root: Path
    minute_root: Path
    chip_feature_root: Path
    chip_lineage_root: Path | None

    def daily_file(self, year: int) -> Path:
        return self.daily_root / f"partition_year={year}" / "data_0.parquet"

    def minute_daily_file(self, year: int) -> Path:
        return self.minute_root / "daily" / f"partition_year={year}" / "data_0.parquet"

    def execution_file(self, year: int) -> Path:
        return self.minute_root / "execution_5m" / f"partition_year={year}" / "data_0.parquet"

    def feature_file(self, year: int) -> Path:
        return self.chip_feature_root / f"year={year}" / "data.parquet"


@dataclass(frozen=True)
class OutputPaths:
    root: Path
    panel_root: Path
    label_root: Path
    signal_root: Path
    validation_root: Path


@dataclass(frozen=True)
class MarkupRetestConfig:
    path: Path
    repo_root: Path
    strategy_version: str
    panel_schema_version: int
    registry_path: Path
    legacy_quarantine_manifest: Path
    trial_ledger: Path
    freeze_manifest: Path
    assets: AssetPaths
    outputs: OutputPaths
    stages: Mapping[StrategyStage, StageBoundary]
    windows: StrategyWindows
    fixed: FixedThresholds
    parameters: StrategyParameters
    parameter_grids: Mapping[str, tuple[float, ...]]
    execution: ExecutionSettings
    quality: QualitySettings
    sha256: str

    @classmethod
    def load(
        cls, path: str | Path = "configs/markup_retest_v1.yaml"
    ) -> MarkupRetestConfig:
        return load_markup_retest_config(path)

    def stage(self, name: StrategyStage | str) -> StageBoundary:
        stage = StrategyStage(name)
        return self.stages[stage]

    def input_files(
        self, stage: StrategyStage | str, *, include_execution: bool = False
    ) -> tuple[Path, ...]:
        boundary = self.stage(stage)
        files: list[Path] = []
        for year in boundary.years():
            files.extend(
                (
                    self.assets.daily_file(year),
                    self.assets.feature_file(year),
                )
            )
            if include_execution:
                files.append(self.assets.execution_file(year))
        self.assert_input_files(stage, files)
        return tuple(files)

    def assert_input_files(
        self, stage: StrategyStage | str, paths: Sequence[Path]
    ) -> None:
        boundary = self.stage(stage)
        for path in paths:
            year = _partition_year(path)
            if year is None:
                raise ValueError(f"input path has no explicit year partition: {path}")
            if year > boundary.max_input_date.year:
                raise FutureDataError(
                    f"{boundary.name.value} refuses physical file {path}; "
                    f"year {year} exceeds {boundary.max_input_date.year}"
                )


def _partition_year(path: Path) -> int | None:
    for part in path.parts:
        for prefix in ("partition_year=", "year="):
            if part.startswith(prefix):
                value = part.removeprefix(prefix)
                if value.isdigit() and len(value) == 4:
                    return int(value)
    return None


def load_passing_frozen_parameters(config: MarkupRetestConfig) -> StrategyParameters:
    """Fail closed before any resealed input can be resolved or read."""

    if not config.freeze_manifest.is_file():
        raise FileNotFoundError(
            f"resealed validation requires the frozen v1 manifest: "
            f"{config.freeze_manifest}"
        )
    payload = json.loads(config.freeze_manifest.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("freeze manifest must be a JSON object")
    if payload.get("status") != "FROZEN":
        raise ValueError("resealed validation requires an immutable frozen manifest")
    if payload.get("config_sha256") != config.sha256:
        raise ValueError("freeze manifest config hash mismatch")
    economic_snapshot = payload.get("economic_selection_snapshot_id")
    p0_event_id = payload.get("p0_gate_event_id")
    if (
        not isinstance(economic_snapshot, str)
        or not economic_snapshot.startswith("entry-economic-selection-")
        or not isinstance(p0_event_id, str)
        or not p0_event_id
    ):
        raise ValueError("freeze manifest lacks economic-selection or P0 gate identity")
    decision = payload.get("freeze_decision")
    if decision == "NO_TRADE":
        raise ValueError("frozen development decision is NO_TRADE; holdout risk is forbidden")
    if decision != "PASS":
        raise ValueError("resealed validation requires a passing economic freeze")
    raw = payload.get("final_parameters")
    if not isinstance(raw, dict):
        raise ValueError("freeze manifest has no final_parameters object")
    required = set(config.parameters.canonical())
    if set(raw) != required:
        raise ValueError("freeze manifest final_parameters schema mismatch")
    parameters = StrategyParameters(
        **{name: float(raw[name]) for name in sorted(required)}
    )
    component = payload.get("selected_component")
    if (
        payload.get("selected_parameter_id") != parameters.parameter_id
        or not isinstance(component, list)
        or len(component) < 3
        or parameters.parameter_id not in component
    ):
        raise ValueError("freeze manifest lacks a robust selected economic component")
    return parameters


def _date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _time(value: object) -> time:
    parsed = time.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"time must include an explicit UTC offset: {value}")
    return parsed


def _path(repo_root: Path, value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else repo_root / path


def _mapping(value: object, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return cast(Mapping[str, Any], value)


def load_markup_retest_config(
    path: str | Path = "configs/markup_retest_v1.yaml",
) -> MarkupRetestConfig:
    config_path = Path(path).resolve()
    repo_root = config_path.parent.parent
    raw_bytes = config_path.read_bytes()
    loaded = yaml.safe_load(raw_bytes)
    root = _mapping(loaded, name="config")
    strategy = _mapping(root["strategy"], name="strategy")
    if strategy.get("family") != StrategyFamily.MARKUP_RETEST.value:
        raise ValueError("v1 config must enable MARKUP_RETEST")
    if tuple(strategy.get("enabled_families", ())) != (StrategyFamily.MARKUP_RETEST.value,):
        raise ValueError("MARKUP_RETEST must be the only enabled v1 strategy family")

    governance = _mapping(root["governance"], name="governance")
    asset_raw = _mapping(root["assets"], name="assets")
    output_raw = _mapping(root["outputs"], name="outputs")
    window_raw = _mapping(root["windows"], name="windows")
    fixed_raw = _mapping(root["fixed_thresholds"], name="fixed_thresholds")
    parameter_raw = _mapping(root["parameters"], name="parameters")
    default_raw = _mapping(parameter_raw["defaults"], name="parameters.defaults")
    grid_raw = _mapping(parameter_raw["grids"], name="parameters.grids")
    execution_raw = _mapping(root["execution"], name="execution")
    quality_raw = _mapping(root["quality"], name="quality")

    stages: dict[StrategyStage, StageBoundary] = {}
    for stage_name, stage_value in _mapping(root["stages"], name="stages").items():
        stage = StrategyStage(stage_name)
        values = _mapping(stage_value, name=f"stages.{stage_name}")
        stages[stage] = StageBoundary(
            name=stage,
            start=_date(values["start"]),
            end=_date(values["end"]),
            history_start=_date(values["history_start"]),
            max_input_date=_date(values["max_input_date"]),
            min_input_date=(
                _date(values["min_input_date"]) if values.get("min_input_date") else None
            ),
            symbols=tuple(str(item) for item in values.get("symbols", ())),
        )
    if stages[StrategyStage.DEVELOPMENT].max_input_date >= date(2024, 1, 1):
        raise ValueError("development max_input_date must be before 2024-01-01")

    config = MarkupRetestConfig(
        path=config_path,
        repo_root=repo_root,
        strategy_version=str(strategy["version"]),
        panel_schema_version=int(strategy["panel_schema_version"]),
        registry_path=_path(repo_root, governance["registry"]),
        legacy_quarantine_manifest=_path(
            repo_root, governance["legacy_quarantine_manifest"]
        ),
        trial_ledger=_path(repo_root, governance["trial_ledger"]),
        freeze_manifest=_path(repo_root, governance["freeze_manifest"]),
        assets=AssetPaths(
            daily_asset_id=str(asset_raw["daily_asset_id"]),
            minute_asset_id=str(asset_raw["minute_asset_id"]),
            chip_feature_asset_id=str(asset_raw["chip_feature_asset_id"]),
            chip_lineage_asset_id=(
                str(asset_raw["chip_lineage_asset_id"])
                if asset_raw.get("chip_lineage_asset_id")
                else None
            ),
            corporate_action_asset_id=str(asset_raw["corporate_action_asset_id"]),
            daily_root=_path(repo_root, asset_raw["daily_root"]),
            minute_root=_path(repo_root, asset_raw["minute_root"]),
            chip_feature_root=_path(repo_root, asset_raw["chip_feature_root"]),
            chip_lineage_root=(
                _path(repo_root, asset_raw["chip_lineage_root"])
                if asset_raw.get("chip_lineage_root")
                else None
            ),
        ),
        outputs=OutputPaths(
            root=_path(repo_root, output_raw["root"]),
            panel_root=_path(repo_root, output_raw["panel_root"]),
            label_root=_path(repo_root, output_raw["label_root"]),
            signal_root=_path(repo_root, output_raw["signal_root"]),
            validation_root=_path(repo_root, output_raw["validation_root"]),
        ),
        stages=stages,
        windows=StrategyWindows(
            accumulation=int(window_raw["accumulation"]),
            recent_evidence=int(window_raw["recent_evidence"]),
            retest_min=int(window_raw["retest_min"]),
            retest_max=int(window_raw["retest_max"]),
            exit_confirmation=int(window_raw["exit_confirmation"]),
            max_holding=int(window_raw["max_holding"]),
            cooldown=int(window_raw["cooldown"]),
            label_horizon=int(window_raw["label_horizon"]),
            embargo=int(window_raw["embargo"]),
        ),
        fixed=FixedThresholds(
            high_turnover_quantile=float(fixed_raw["high_turnover_quantile"]),
            low_price_impact_quantile=float(fixed_raw["low_price_impact_quantile"]),
            support_tolerance_atr=float(fixed_raw["support_tolerance_atr"]),
            retest_volume_ratio_max=float(fixed_raw["retest_volume_ratio_max"]),
            retest_turnover_ratio_max=float(fixed_raw["retest_turnover_ratio_max"]),
            recent_band_overlap_floor=float(fixed_raw["recent_band_overlap_floor"]),
            anchor_retention_floor=float(fixed_raw["anchor_retention_floor"]),
            anchor_severe_retention_floor=float(
                fixed_raw["anchor_severe_retention_floor"]
            ),
            anchor_band_expansion_ratio_max=float(
                fixed_raw["anchor_band_expansion_ratio_max"]
            ),
            anchor_peak_count_increase_max=int(
                fixed_raw["anchor_peak_count_increase_max"]
            ),
            max_model_disagreement_atr=float(
                fixed_raw["max_model_disagreement_atr"]
            ),
            setup_component_count=int(fixed_raw["setup_component_count"]),
            distribution_component_count=int(fixed_raw["distribution_component_count"]),
        ),
        parameters=StrategyParameters(
            setup_score_min=float(default_raw["setup_score_min"]),
            breakout_buffer_atr=float(default_raw["breakout_buffer_atr"]),
            max_retest_depth_atr=float(default_raw["max_retest_depth_atr"]),
            min_cost_migration_atr=float(default_raw["min_cost_migration_atr"]),
            distribution_score_min=float(default_raw["distribution_score_min"]),
            protective_stop_atr=float(default_raw["protective_stop_atr"]),
        ),
        parameter_grids={
            key: tuple(float(item) for item in cast(Sequence[Any], values))
            for key, values in grid_raw.items()
        },
        execution=ExecutionSettings(
            decision_time=_time(execution_raw["decision_time"]),
            next_window_end=_time(execution_raw["next_window_end"]),
            max_entry_wait_trading_days=int(execution_raw["max_entry_wait_trading_days"]),
            nominal_capital_per_signal=float(execution_raw["nominal_capital_per_signal"]),
            fee_bps=float(execution_raw["fee_bps"]),
            slippage_bps=float(execution_raw["slippage_bps"]),
            impact_bps=float(execution_raw["impact_bps"]),
        ),
        quality=QualitySettings(
            minimum_board_coverage=float(quality_raw["minimum_board_coverage"]),
            mass_tolerance=float(quality_raw["mass_tolerance"]),
            calibration_ece_max=float(quality_raw["calibration_ece_max"]),
            annual_signal_min=int(quality_raw["annual_signal_min"]),
            annual_signal_max=int(quality_raw["annual_signal_max"]),
            mean_signal_min=int(quality_raw["mean_signal_min"]),
            mean_signal_max=int(quality_raw["mean_signal_max"]),
            current_industry_grade=str(quality_raw["current_industry_grade"]),
            unknown_industry_fallback=str(quality_raw["unknown_industry_fallback"]),
        ),
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )
    _validate_config(config)
    return config


def _validate_config(config: MarkupRetestConfig) -> None:
    if config.panel_schema_version != PANEL_SCHEMA_VERSION:
        raise ValueError(
            f"panel schema version must be {PANEL_SCHEMA_VERSION}; old artifacts are invalid"
        )
    if config.strategy_version != STRATEGY_VERSION:
        raise ValueError(
            f"strategy version must be {STRATEGY_VERSION}; old artifacts are invalid"
        )
    if not config.legacy_quarantine_manifest.is_file():
        raise ValueError("legacy quarantine manifest is missing")
    quarantine = _mapping(
        yaml.safe_load(config.legacy_quarantine_manifest.read_text()), name="legacy quarantine"
    )
    if quarantine.get("status") != "LEGACY_INVALID_FOR_PROMOTION":
        raise ValueError("legacy outputs are not quarantined")
    expected_grid_sizes = {
        "setup_score_min": 3,
        "breakout_buffer_atr": 3,
        "max_retest_depth_atr": 3,
        "min_cost_migration_atr": 3,
        "distribution_score_min": 3,
        "protective_stop_atr": 3,
    }
    if set(config.parameter_grids) != set(expected_grid_sizes):
        raise ValueError("exactly the six declared parameter grids are required")
    for key, size in expected_grid_sizes.items():
        if len(config.parameter_grids[key]) != size:
            raise ValueError(f"{key} must have {size} grid values")
    if config.windows.retest_min < 1 or config.windows.retest_max < config.windows.retest_min:
        raise ValueError("retest must start after the breakout bar")
    if config.quality.minimum_board_coverage < 0.95:
        raise ValueError("board coverage gate cannot be below 95%")
    if not (
        0.0
        <= config.fixed.anchor_severe_retention_floor
        < config.fixed.anchor_retention_floor
        <= 1.0
    ):
        raise ValueError("anchor retention thresholds are inconsistent")
    if not 0.0 <= config.fixed.recent_band_overlap_floor <= 1.0:
        raise ValueError("recent band overlap threshold must be in [0, 1]")
    if config.fixed.anchor_band_expansion_ratio_max < 1.0:
        raise ValueError("anchor band expansion ratio must be at least one")
    if config.fixed.anchor_peak_count_increase_max < 0:
        raise ValueError("anchor peak count tolerance cannot be negative")
    if config.fixed.max_model_disagreement_atr <= 0:
        raise ValueError("model disagreement limit must be positive")
    if config.execution.decision_time.isoformat() != "15:30:00+08:00":
        raise ValueError("v1 decision_time must match chip availability at 15:30+08:00")
    if config.execution.next_window_end.isoformat() != "09:35:00+08:00":
        raise ValueError("v1 entry must use the next legal 5-minute window ending 09:35")
    if config.execution.max_entry_wait_trading_days != 3:
        raise ValueError("v1 entry must fail explicitly after three market trading days")
    if config.execution.nominal_capital_per_signal <= 0:
        raise ValueError("nominal capital per signal must be positive")
    if min(
        config.execution.fee_bps,
        config.execution.slippage_bps,
        config.execution.impact_bps,
    ) < 0:
        raise ValueError("execution costs cannot be negative")
    _validate_registered_assets(config)


def _validate_registered_assets(config: MarkupRetestConfig) -> None:
    """Bind the strategy to the sole authoritative registry allowlist."""

    registry = DataAssetRegistry.load(config.registry_path)
    bindings = {
        config.assets.daily_asset_id: config.assets.daily_root,
        config.assets.minute_asset_id: config.assets.minute_root,
        config.assets.chip_feature_asset_id: config.assets.chip_feature_root,
    }
    for asset_id, configured_root in bindings.items():
        try:
            asset = registry.assets[asset_id]
        except KeyError as error:
            raise ValueError(f"strategy asset is not registered: {asset_id}") from error
        if asset.status not in {"RESEARCH_CONDITIONAL", "DERIVE_ONLY"}:
            raise ValueError(f"strategy asset {asset_id} is not research-eligible")
        if asset.physical_state != "MATERIALIZED" or asset.location is None:
            raise ValueError(f"strategy asset {asset_id} is not materialized")
        if configured_root.resolve() != asset.location.resolve():
            raise ValueError(
                f"strategy path does not match registry for {asset_id}: "
                f"{configured_root} != {asset.location}"
            )
    lineage_id = config.assets.chip_lineage_asset_id
    lineage_root = config.assets.chip_lineage_root
    if (lineage_id is None) != (lineage_root is None):
        raise ValueError(
            "chip_lineage_asset_id and chip_lineage_root must be configured together"
        )
    if lineage_id is not None and lineage_root is not None:
        try:
            lineage_asset = registry.assets[lineage_id]
        except KeyError as error:
            raise ValueError(
                f"strategy chip-lineage asset is not registered: {lineage_id}"
            ) from error
        if lineage_asset.status not in {"RESEARCH_CONDITIONAL", "DERIVE_ONLY"}:
            raise ValueError(
                f"strategy chip-lineage asset {lineage_id} is not research-eligible"
            )
        if (
            lineage_asset.physical_state != "MATERIALIZED"
            or lineage_asset.location is None
        ):
            raise ValueError(
                f"strategy chip-lineage asset {lineage_id} is not materialized"
            )
        if lineage_root.resolve() != lineage_asset.location.resolve():
            raise ValueError(
                f"strategy path does not match registry for {lineage_id}: "
                f"{lineage_root} != {lineage_asset.location}"
            )
    try:
        corporate_action = registry.assets[config.assets.corporate_action_asset_id]
    except KeyError as error:
        raise ValueError(
            "corporate-action lineage asset is not registered: "
            f"{config.assets.corporate_action_asset_id}"
        ) from error
    if corporate_action.status != "RESEARCH_CONDITIONAL":
        raise ValueError("corporate-action lineage is not research-eligible")


def verify_registered_asset_inventory(
    config: MarkupRetestConfig, asset_id: str
) -> dict[str, Any]:
    """Verify one registered manifest and every file it freezes exactly once per run."""

    registry = DataAssetRegistry.load(config.registry_path)
    try:
        asset = registry.assets[asset_id]
    except KeyError as error:
        raise ValueError(f"strategy asset is not registered: {asset_id}") from error
    raw_manifest = asset.lineage.get("manifest_path")
    raw_sha256 = asset.lineage.get("manifest_sha256")
    if not isinstance(raw_manifest, str) or not isinstance(raw_sha256, str):
        raise ValueError(f"registered asset {asset_id} has no immutable manifest identity")
    manifest_path = Path(raw_manifest).expanduser().resolve()
    if not manifest_path.is_file() or _file_sha256(manifest_path) != raw_sha256:
        raise ValueError(f"registered asset {asset_id} manifest identity changed")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_inventory = payload.get("files", payload.get("inventory"))
    if not isinstance(raw_inventory, list) or not raw_inventory:
        raise ValueError(f"registered asset {asset_id} manifest has no inventory")
    raw_root = payload.get("root", payload.get("location"))
    root = (
        Path(raw_root).expanduser().resolve()
        if isinstance(raw_root, str) and raw_root
        else asset.location
    )
    if root is None or asset.location is None or root != asset.location.resolve():
        raise ValueError(f"registered asset {asset_id} manifest root mismatch")
    for raw in raw_inventory:
        if not isinstance(raw, dict):
            raise ValueError(f"registered asset {asset_id} inventory entry is invalid")
        relative = Path(str(raw.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"registered asset {asset_id} inventory path is unsafe")
        path = root / relative
        if not path.is_file() or path.stat().st_size != raw.get("size"):
            raise ValueError(f"registered asset {asset_id} inventory size changed: {path}")
        if _file_sha256(path) != raw.get("sha256"):
            raise ValueError(f"registered asset {asset_id} inventory hash changed: {path}")
    return {
        "asset_id": asset_id,
        "path": str(manifest_path),
        "size": manifest_path.stat().st_size,
        "sha256": raw_sha256,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class LifecycleAnchor:
    anchor_id: str
    symbol: str
    source_snapshot_id: str
    root_anchor_id: str
    parent_anchor_id: str | None
    role: str
    created_at: date
    lower: float
    upper: float
    reference_mass: float
    average_cost: float
    cost_p50: float
    band_width: float
    peak_count: int
    mass_method: ChipMassMethod
    peak_track_id: str = ""


@dataclass(frozen=True)
class LifecycleObservation:
    symbol: str
    decision_at: datetime
    available_at: datetime
    snapshot_ids: tuple[str, ...]
    hard_valid: bool
    tradable: bool
    pit_grade: str
    setup_score: float
    breakout_excess_atr: float
    support_regained: bool
    downside_absorption: bool
    chip_profile: ChipMassProfile
    cost_p10: float
    cost_p90: float
    peak_count: int
    recent_band_overlap: float
    distribution_score: float
    structure_support: float
    close: float
    close_vs_vwap: float
    low: float
    volume: float
    turnover: float
    average_cost: float
    cost_p50: float
    prior_average_cost: float
    prior_cost_p50: float
    atr: float
    chip_model_disagreement_atr: float = 0.0
    share_multiplier: float = 1.0
    cash_per_share: float = 0.0
    structure_broken: bool = False
    corporate_action_blocking: bool = False
    corporate_action_ids: tuple[str, ...] = ()
    market_state: str = "UNKNOWN"
    sector_state: str = "UNKNOWN"
    industry_pit_grade: str = "UNKNOWN"
    evidence_for: tuple[str, ...] = ()
    evidence_against: tuple[str, ...] = ()
    alternative_explanations: tuple[str, ...] = ()
    anchor_retention_estimates: tuple[AnchorRetentionEstimate, ...] = ()
    peak_track_id: str | None = None
    peak_track_band_lower: float | None = None
    peak_track_band_upper: float | None = None
    peak_track_ambiguous: bool = True
    peak_definition_version: str | None = None

    def __post_init__(self) -> None:
        if self.available_at > self.decision_at:
            raise FutureDataError(
                f"{self.symbol} observation available at {self.available_at} after "
                f"decision {self.decision_at}"
            )
        numeric_values = (
            self.setup_score,
            self.breakout_excess_atr,
            self.cost_p10,
            self.cost_p90,
            self.recent_band_overlap,
            self.distribution_score,
            self.structure_support,
            self.close,
            self.close_vs_vwap,
            self.low,
            self.volume,
            self.turnover,
            self.average_cost,
            self.cost_p50,
            self.prior_average_cost,
            self.prior_cost_p50,
            self.atr,
            self.chip_model_disagreement_atr,
            self.share_multiplier,
            self.cash_per_share,
        )
        if any(not math.isfinite(value) for value in numeric_values):
            raise ValueError("lifecycle numeric fields must be finite")
        if self.atr <= 0:
            raise ValueError("ATR must be positive")
        if self.chip_model_disagreement_atr < 0:
            raise ValueError("chip model disagreement must be finite and non-negative")
        if self.cost_p10 > self.cost_p90:
            raise ValueError("cost_p10 cannot exceed cost_p90")
        if any(
            value <= 0.0
            for value in (
                self.cost_p10,
                self.cost_p90,
                self.structure_support,
                self.close,
                self.low,
                self.average_cost,
                self.cost_p50,
                self.prior_average_cost,
                self.prior_cost_p50,
            )
        ):
            raise ValueError("lifecycle price fields must be positive")
        if self.volume < 0.0 or self.turnover < 0.0:
            raise ValueError("volume and turnover must be non-negative")
        if not 0.0 <= self.recent_band_overlap <= 1.0:
            raise ValueError("recent band overlap must be in [0, 1]")
        if self.peak_count < 1:
            raise ValueError("peak_count must be positive")
        if self.share_multiplier <= 0:
            raise ValueError("share_multiplier must be positive")
        if self.cash_per_share < 0:
            raise ValueError("cash_per_share cannot be negative")
        if not self.snapshot_ids or any(not item for item in self.snapshot_ids):
            raise ValueError("every observation requires input snapshot ids")
        if len(set(self.corporate_action_ids)) != len(self.corporate_action_ids):
            raise ValueError("corporate action ids must be unique")

    @property
    def peak_identity_valid(self) -> bool:
        return bool(
            self.peak_track_id
            and not self.peak_track_ambiguous
            and self.peak_track_band_lower is not None
            and self.peak_track_band_upper is not None
            and self.peak_track_band_lower > 0.0
            and self.peak_track_band_upper >= self.peak_track_band_lower
            and self.peak_definition_version == PEAK_DEFINITION_VERSION
        )


AnchorRetentionResolver = Callable[
    [LifecycleAnchor, LifecycleObservation], AnchorRetentionEstimate | None
]


@dataclass(frozen=True)
class LifecycleMemory:
    state: ChipLifecycleState = ChipLifecycleState.NEUTRAL
    accumulation_started_at: date | None = None
    accumulation_index: int | None = None
    accumulation_anchor: LifecycleAnchor | None = None
    comparison_anchor: LifecycleAnchor | None = None
    working_anchor: LifecycleAnchor | None = None
    anchor_chain: tuple[LifecycleAnchor, ...] = ()
    breakout_at: date | None = None
    breakout_support: float | None = None
    breakout_atr: float | None = None
    breakout_volume: float | None = None
    breakout_turnover: float | None = None
    pre_breakout_average_cost: float | None = None
    pre_breakout_cost_p50: float | None = None
    breakout_index: int | None = None
    active_signal_id: str | None = None
    distribution_days: int = 0
    holding_days: int = 0
    cooldown_remaining: int = 0
    pending_exit_reason: ExitReason | None = None
    applied_action_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategySignal:
    signal_id: str
    symbol: str
    decision_at: datetime
    strategy_version: str
    strategy_family: StrategyFamily
    lifecycle_state: ChipLifecycleState
    accumulation_started_at: date
    breakout_at: date
    retest_confirmed_at: date
    anchor_created_at: date
    anchor_lower: float
    anchor_upper: float
    anchor_reference_mass: float
    anchor_retention: float
    anchor_mass_method: ChipMassMethod
    evidence_for: tuple[str, ...]
    evidence_against: tuple[str, ...]
    market_state: str
    sector_state: str
    alternative_explanations: tuple[str, ...]
    available_at: datetime
    snapshot_ids: tuple[str, ...]
    hard_valid: bool
    pit_grade: str
    industry_pit_grade: str
    parameter_id: str
    edge_card: EdgeCard | None
    execution_status: str
    unfilled_reason: str | None
    root_anchor_id: str = ""
    working_anchor_id: str = ""
    anchor_chain_ids: tuple[str, ...] = ()
    anchor_retention_lower: float = 0.0
    anchor_retention_upper: float = 0.0
    anchor_retention_confidence: float = 0.0
    anchor_model_retentions: tuple[tuple[str, float], ...] = ()

    @property
    def order_authorized(self) -> bool:
        return (
            self.hard_valid
            and self.edge_card is not None
            and self.edge_card.complete
            and self.execution_status == "READY_FOR_NEXT_WINDOW"
        )


@dataclass(frozen=True)
class TransitionResult:
    memory: LifecycleMemory
    signal: StrategySignal | None = None
    exit_reason: ExitReason | None = None
    soft_exit_cancelled: bool = False


def assert_no_label_access(record: Mapping[str, object]) -> None:
    forbidden = sorted(FORBIDDEN_SIGNAL_FIELDS.intersection(record))
    if forbidden:
        raise FutureDataError(
            "signal generation cannot access label fields: " + ", ".join(forbidden)
        )


def freeze_lifecycle_anchor(
    observation: LifecycleObservation,
    *,
    strategy_version: str = "markup_retest_v1",
) -> LifecycleAnchor:
    """Freeze one causal root reference; the band is diagnostics, not lineage."""

    if not observation.peak_identity_valid:
        raise ValueError("accumulation anchor requires an unambiguous tracked peak")
    assert observation.peak_track_band_lower is not None
    assert observation.peak_track_band_upper is not None
    assert observation.peak_track_id is not None
    reference_mass = observation.chip_profile.mass_between(
        observation.peak_track_band_lower, observation.peak_track_band_upper
    )
    if reference_mass <= 0:
        raise ValueError("accumulation anchor has no measurable chip mass")
    source_snapshot_id = "|".join(sorted(observation.snapshot_ids))
    identity = "|".join(
        (
            observation.symbol,
            observation.decision_at.date().isoformat(),
            source_snapshot_id,
            strategy_version,
            "ROOT",
        )
    )
    anchor_id = hashlib.sha256(identity.encode()).hexdigest()
    return LifecycleAnchor(
        anchor_id=anchor_id,
        symbol=observation.symbol,
        source_snapshot_id=source_snapshot_id,
        root_anchor_id=anchor_id,
        parent_anchor_id=None,
        role="ROOT",
        created_at=observation.decision_at.date(),
        lower=observation.peak_track_band_lower,
        upper=observation.peak_track_band_upper,
        reference_mass=reference_mass,
        average_cost=observation.average_cost,
        cost_p50=observation.cost_p50,
        band_width=max(
            observation.peak_track_band_upper - observation.peak_track_band_lower,
            1e-12,
        ),
        peak_count=observation.peak_count,
        mass_method=observation.chip_profile.method,
        peak_track_id=observation.peak_track_id,
    )


def _action_rebased_price(
    value: float, *, share_multiplier: float, cash_per_share: float
) -> float:
    return rebase_economic_price(
        value,
        cash_per_share=cash_per_share,
        share_multiplier=share_multiplier,
    )


def rebase_comparison_anchor(
    anchor: LifecycleAnchor,
    *,
    share_multiplier: float,
    cash_per_share: float,
) -> LifecycleAnchor:
    """Move comparison fields to the post-action price coordinate.

    The immutable lineage anchor remains separate because its original
    ``lower``/``upper`` values select source-date inventory cells.
    """

    lower = _action_rebased_price(
        anchor.lower,
        share_multiplier=share_multiplier,
        cash_per_share=cash_per_share,
    )
    upper = _action_rebased_price(
        anchor.upper,
        share_multiplier=share_multiplier,
        cash_per_share=cash_per_share,
    )
    return replace(
        anchor,
        lower=lower,
        upper=upper,
        average_cost=_action_rebased_price(
            anchor.average_cost,
            share_multiplier=share_multiplier,
            cash_per_share=cash_per_share,
        ),
        cost_p50=_action_rebased_price(
            anchor.cost_p50,
            share_multiplier=share_multiplier,
            cash_per_share=cash_per_share,
        ),
        band_width=max(upper - lower, 1e-12),
    )


def rebase_lifecycle_memory(
    memory: LifecycleMemory, observation: LifecycleObservation
) -> LifecycleMemory:
    """Rebase frozen strategy references without mutating lineage identity."""

    multiplier = observation.share_multiplier
    cash = observation.cash_per_share
    if multiplier == 1.0 and cash == 0.0:
        return memory
    if not observation.corporate_action_ids:
        raise ValueError("economic corporate action requires canonical action ids")
    already_applied = set(memory.applied_action_ids)
    if already_applied.intersection(observation.corporate_action_ids):
        if set(observation.corporate_action_ids).issubset(already_applied):
            return memory
        raise ValueError("partially replayed corporate action id set")

    comparison = memory.comparison_anchor or memory.accumulation_anchor
    if comparison is not None:
        comparison = rebase_comparison_anchor(
            comparison,
            share_multiplier=multiplier,
            cash_per_share=cash,
        )

    def price(value: float | None) -> float | None:
        if value is None:
            return None
        return _action_rebased_price(
            value,
            share_multiplier=multiplier,
            cash_per_share=cash,
        )

    return replace(
        memory,
        comparison_anchor=comparison,
        breakout_support=price(memory.breakout_support),
        breakout_atr=(
            None
            if memory.breakout_atr is None
            else memory.breakout_atr / multiplier
        ),
        breakout_volume=(
            None
            if memory.breakout_volume is None
            else memory.breakout_volume * multiplier
        ),
        pre_breakout_average_cost=price(memory.pre_breakout_average_cost),
        pre_breakout_cost_p50=price(memory.pre_breakout_cost_p50),
        applied_action_ids=tuple(
            sorted((*memory.applied_action_ids, *observation.corporate_action_ids))
        ),
    )


def band_occupancy_proxy(
    anchor: LifecycleAnchor, observation: LifecycleObservation
) -> float:
    """Diagnostic only; new chips in this band are not anchor descendants."""

    retained = observation.chip_profile.mass_between(anchor.lower, anchor.upper)
    return min(1.0, max(0.0, retained / anchor.reference_mass))


def exact_anchor_retention(
    anchor: LifecycleAnchor,
    observation: LifecycleObservation,
    *,
    resolver: AnchorRetentionResolver | None = None,
) -> AnchorRetentionEstimate | None:
    """Return the exact PIT lineage estimate for this root anchor and date."""

    matches = tuple(
        estimate
        for estimate in observation.anchor_retention_estimates
        if estimate.anchor_id == anchor.root_anchor_id
        and estimate.symbol == observation.symbol
        and estimate.anchor_date == anchor.created_at
        and estimate.current_date == observation.decision_at.date()
    )
    if len(matches) > 1:
        raise ValueError("duplicate anchor lineage estimates for one decision")
    if matches:
        return matches[0]
    if resolver is None:
        return None
    estimate = resolver(anchor, observation)
    if estimate is None:
        return None
    if (
        estimate.anchor_id != anchor.root_anchor_id
        or estimate.symbol != observation.symbol
        or estimate.anchor_date != anchor.created_at
        or estimate.current_date != observation.decision_at.date()
    ):
        raise ValueError("anchor retention resolver returned a mismatched estimate")
    return estimate


def maybe_create_support_anchor(
    memory: LifecycleMemory,
    observation: LifecycleObservation,
    estimate: AnchorRetentionEstimate,
    fixed: FixedThresholds,
) -> LifecycleAnchor | None:
    """Advance only the working support; the immutable root remains unchanged."""

    lineage_root = memory.accumulation_anchor
    comparison_root = memory.comparison_anchor or lineage_root
    if (
        lineage_root is None
        or comparison_root is None
        or estimate.lower < fixed.anchor_retention_floor
    ):
        return None
    if (
        not observation.peak_identity_valid
        or observation.peak_track_id != comparison_root.peak_track_id
    ):
        return None
    assert observation.peak_track_band_lower is not None
    assert observation.peak_track_band_upper is not None
    assert observation.peak_track_id is not None
    band_width = max(
        observation.peak_track_band_upper - observation.peak_track_band_lower,
        1e-12,
    )
    if band_width / comparison_root.band_width > fixed.anchor_band_expansion_ratio_max:
        return None
    if (
        observation.peak_count - comparison_root.peak_count
        > fixed.anchor_peak_count_increase_max
    ):
        return None
    if min(
        observation.average_cost - comparison_root.average_cost,
        observation.cost_p50 - comparison_root.cost_p50,
    ) < 0:
        return None
    parent = memory.working_anchor or lineage_root
    source_snapshot_id = "|".join(sorted(observation.snapshot_ids))
    identity = "|".join(
        (
            observation.symbol,
            lineage_root.anchor_id,
            parent.anchor_id,
            observation.decision_at.date().isoformat(),
            source_snapshot_id,
            "SUPPORT",
        )
    )
    reference_mass = observation.chip_profile.mass_between(
        observation.peak_track_band_lower, observation.peak_track_band_upper
    )
    if reference_mass <= 0:
        return None
    return LifecycleAnchor(
        anchor_id=hashlib.sha256(identity.encode()).hexdigest(),
        symbol=observation.symbol,
        source_snapshot_id=source_snapshot_id,
        root_anchor_id=lineage_root.anchor_id,
        parent_anchor_id=parent.anchor_id,
        role="SUPPORT",
        created_at=observation.decision_at.date(),
        lower=observation.peak_track_band_lower,
        upper=observation.peak_track_band_upper,
        reference_mass=reference_mass,
        average_cost=observation.average_cost,
        cost_p50=observation.cost_p50,
        band_width=band_width,
        peak_count=observation.peak_count,
        mass_method=observation.chip_profile.method,
        peak_track_id=observation.peak_track_id,
    )


def chip_structure_broken(
    anchor: LifecycleAnchor,
    observation: LifecycleObservation,
    fixed: FixedThresholds,
    *,
    comparison_anchor: LifecycleAnchor | None = None,
    resolver: AnchorRetentionResolver | None = None,
) -> bool:
    comparison = comparison_anchor or anchor
    if (
        not observation.peak_identity_valid
        or observation.peak_track_id != comparison.peak_track_id
    ):
        return True
    estimate = exact_anchor_retention(anchor, observation, resolver=resolver)
    if estimate is None:
        return True
    comparison = comparison_anchor or anchor
    band_width = max(observation.cost_p90 - observation.cost_p10, 1e-12)
    expanded = (
        band_width / comparison.band_width > fixed.anchor_band_expansion_ratio_max
    )
    split = (
        observation.peak_count - comparison.peak_count
        > fixed.anchor_peak_count_increase_max
    )
    return estimate.lower < fixed.anchor_severe_retention_floor and (expanded or split)


def distribution_score_with_anchor(
    anchor: LifecycleAnchor,
    observation: LifecycleObservation,
    fixed: FixedThresholds,
    *,
    resolver: AnchorRetentionResolver | None = None,
) -> float:
    if (
        not observation.peak_identity_valid
        or observation.peak_track_id != anchor.peak_track_id
    ):
        raise ValueError("distribution requires the same unambiguous peak track")
    estimate = exact_anchor_retention(anchor, observation, resolver=resolver)
    if estimate is None:
        raise ValueError("distribution requires exact anchor lineage")
    base_loss = estimate.lower < fixed.anchor_retention_floor
    component_weight = 1.0 / fixed.distribution_component_count
    return min(1.0, observation.distribution_score + component_weight * base_loss)


class LifecycleMachine:
    """Pure state transition engine shared by validation and research."""

    def __init__(
        self,
        config: MarkupRetestConfig,
        parameters: StrategyParameters | None = None,
        *,
        anchor_retention_resolver: AnchorRetentionResolver | None = None,
    ):
        self.config = config
        self.parameters = parameters or config.parameters
        self.anchor_retention_resolver = anchor_retention_resolver

    def advance(
        self,
        memory: LifecycleMemory,
        observation: LifecycleObservation,
        *,
        trading_index: int,
    ) -> TransitionResult:
        invalid = (
            observation.corporate_action_blocking
            or not observation.hard_valid
            or not observation.peak_identity_valid
        )
        if invalid:
            if memory.active_signal_id is not None:
                return self._advance_open(memory, observation)
            return TransitionResult(
                LifecycleMemory(
                    state=ChipLifecycleState.BROKEN,
                    cooldown_remaining=memory.cooldown_remaining,
                )
            )
        memory = rebase_lifecycle_memory(memory, observation)
        if memory.active_signal_id is not None:
            return self._advance_open(memory, observation)
        # Suspension is an observed trading state, not missing data.  Preserve
        # the lifecycle and do not consume a retest/cooldown trading day.
        if not observation.tradable:
            return TransitionResult(memory)
        if memory.cooldown_remaining > 0:
            # A 20-day cooldown blocks all 20 complete tradable observations;
            # the stock may form a new setup only on the following trading day.
            return TransitionResult(
                LifecycleMemory(cooldown_remaining=memory.cooldown_remaining - 1)
            )

        setup = observation.setup_score >= self.parameters.setup_score_min
        if memory.state in {ChipLifecycleState.NEUTRAL, ChipLifecycleState.BROKEN}:
            if not setup:
                return TransitionResult(LifecycleMemory())
            root_anchor = freeze_lifecycle_anchor(
                observation, strategy_version=self.config.strategy_version
            )
            return TransitionResult(
                LifecycleMemory(
                    state=ChipLifecycleState.ACCUMULATING,
                    accumulation_started_at=observation.decision_at.date(),
                    accumulation_index=trading_index,
                    accumulation_anchor=root_anchor,
                    comparison_anchor=root_anchor,
                    working_anchor=root_anchor,
                    anchor_chain=(root_anchor,),
                )
            )

        if memory.state == ChipLifecycleState.ACCUMULATING:
            if memory.accumulation_index is None:
                raise ValueError("ACCUMULATING state is missing accumulation_index")
            if (
                trading_index - memory.accumulation_index
                > self.config.windows.accumulation * 3
            ):
                return TransitionResult(LifecycleMemory())
            if observation.breakout_excess_atr < self.parameters.breakout_buffer_atr:
                return TransitionResult(memory)
            if memory.accumulation_anchor is None:
                raise ValueError("ACCUMULATING state is missing its frozen anchor")
            return TransitionResult(
                replace(
                    memory,
                    state=ChipLifecycleState.BREAKOUT,
                    breakout_at=observation.decision_at.date(),
                    breakout_support=observation.structure_support,
                    breakout_atr=observation.atr,
                    breakout_volume=observation.volume,
                    breakout_turnover=observation.turnover,
                    pre_breakout_average_cost=observation.prior_average_cost,
                    pre_breakout_cost_p50=observation.prior_cost_p50,
                    breakout_index=trading_index,
                )
            )

        if memory.state == ChipLifecycleState.BREAKOUT:
            if memory.breakout_index is None:
                raise ValueError("BREAKOUT state is missing breakout_index")
            if memory.accumulation_anchor is None:
                raise ValueError("BREAKOUT state is missing its frozen anchor")
            elapsed = trading_index - memory.breakout_index
            if self._breakout_price_structure_broken(memory, observation) or chip_structure_broken(
                memory.accumulation_anchor,
                observation,
                self.config.fixed,
                comparison_anchor=memory.comparison_anchor,
                resolver=self.anchor_retention_resolver,
            ):
                return TransitionResult(
                    LifecycleMemory(
                        state=ChipLifecycleState.BROKEN,
                        cooldown_remaining=self.config.windows.cooldown,
                    )
                )
            if elapsed > self.config.windows.retest_max:
                return TransitionResult(
                    LifecycleMemory(cooldown_remaining=self.config.windows.cooldown)
                )
            if elapsed < self.config.windows.retest_min:
                return TransitionResult(memory)
            if not self._retest_qualified(memory, observation):
                return TransitionResult(memory)
            estimate = exact_anchor_retention(
                memory.accumulation_anchor,
                observation,
                resolver=self.anchor_retention_resolver,
            )
            if estimate is None:
                return TransitionResult(memory)
            support_anchor = maybe_create_support_anchor(
                memory, observation, estimate, self.config.fixed
            )
            signal_memory = memory
            if support_anchor is not None:
                signal_memory = replace(
                    memory,
                    working_anchor=support_anchor,
                    anchor_chain=(*memory.anchor_chain, support_anchor),
                )
            signal = self.create_signal(signal_memory, observation)
            return TransitionResult(
                replace(
                    signal_memory,
                    state=ChipLifecycleState.RETEST_READY,
                    active_signal_id=signal.signal_id,
                ),
                signal=signal,
            )

        return TransitionResult(memory)

    def _retest_qualified(
        self, memory: LifecycleMemory, observation: LifecycleObservation
    ) -> bool:
        required = (
            memory.breakout_support,
            memory.breakout_atr,
            memory.breakout_volume,
            memory.breakout_turnover,
            memory.pre_breakout_average_cost,
            memory.pre_breakout_cost_p50,
        )
        if any(value is None for value in required):
            raise ValueError("BREAKOUT state is missing causal retest anchors")
        if memory.accumulation_anchor is None:
            raise ValueError("BREAKOUT state is missing its frozen accumulation anchor")
        if observation.peak_track_id != memory.accumulation_anchor.peak_track_id:
            return False
        estimate = exact_anchor_retention(
            memory.accumulation_anchor,
            observation,
            resolver=self.anchor_retention_resolver,
        )
        if estimate is None:
            return False
        support = cast(float, memory.breakout_support)
        breakout_volume = max(cast(float, memory.breakout_volume), 1e-12)
        breakout_turnover = max(cast(float, memory.breakout_turnover), 1e-12)
        frozen_breakout_atr = cast(float, memory.breakout_atr)
        retest_depth_atr = abs(support - observation.low) / frozen_breakout_atr
        retest_volume_ratio = observation.volume / breakout_volume
        retest_turnover_ratio = observation.turnover / breakout_turnover
        # Average cost and p50 are continuous state measurements.  A daily
        # dominant peak is intentionally not used here: peak rank can switch
        # between distinct local modes, so comparing ranks across days would
        # invent a false lineage relation.
        cost_migration_atr = min(
            observation.average_cost - cast(float, memory.pre_breakout_average_cost),
            observation.cost_p50 - cast(float, memory.pre_breakout_cost_p50),
        ) / frozen_breakout_atr
        return all(
            (
                retest_depth_atr <= self.parameters.max_retest_depth_atr,
                cost_migration_atr >= self.parameters.min_cost_migration_atr,
                retest_volume_ratio <= self.config.fixed.retest_volume_ratio_max,
                retest_turnover_ratio <= self.config.fixed.retest_turnover_ratio_max,
                self._breakout_support_regained(memory, observation),
                observation.downside_absorption,
                estimate.lower >= self.config.fixed.anchor_retention_floor,
                observation.chip_model_disagreement_atr
                <= self.config.fixed.max_model_disagreement_atr,
                observation.market_state in {"RISK_ON", "NEUTRAL"},
                observation.sector_state in {"STRONG", "NEUTRAL"},
            )
        )

    def create_signal(
        self, memory: LifecycleMemory, observation: LifecycleObservation
    ) -> StrategySignal:
        """Create the canonical v1 signal identity from causal lifecycle state.

        Parameter-lattice research calls this public method after reproducing
        the same lifecycle transition in vector form.  Keeping identity and
        evidence construction here prevents the fast research path from
        inventing a second signal schema.
        """
        if memory.accumulation_started_at is None or memory.breakout_at is None:
            raise ValueError("entry signal requires accumulation and breakout dates")
        if memory.accumulation_anchor is None:
            raise ValueError("entry signal requires a frozen accumulation anchor")
        estimate = exact_anchor_retention(
            memory.accumulation_anchor,
            observation,
            resolver=self.anchor_retention_resolver,
        )
        if estimate is None:
            raise ValueError("entry signal requires exact anchor lineage")
        working_anchor = memory.working_anchor or memory.accumulation_anchor
        identity = "|".join(
            (
                observation.symbol,
                observation.decision_at.isoformat(),
                self.config.strategy_version,
                self.parameters.parameter_id,
                *observation.snapshot_ids,
            )
        )
        signal_id = hashlib.sha256(identity.encode()).hexdigest()
        return StrategySignal(
            signal_id=signal_id,
            symbol=observation.symbol,
            decision_at=observation.decision_at,
            strategy_version=self.config.strategy_version,
            strategy_family=StrategyFamily.MARKUP_RETEST,
            lifecycle_state=ChipLifecycleState.RETEST_READY,
            accumulation_started_at=memory.accumulation_started_at,
            breakout_at=memory.breakout_at,
            retest_confirmed_at=observation.decision_at.date(),
            anchor_created_at=memory.accumulation_anchor.created_at,
            anchor_lower=memory.accumulation_anchor.lower,
            anchor_upper=memory.accumulation_anchor.upper,
            anchor_reference_mass=memory.accumulation_anchor.reference_mass,
            anchor_retention=estimate.central,
            anchor_mass_method=memory.accumulation_anchor.mass_method,
            evidence_for=observation.evidence_for,
            evidence_against=observation.evidence_against,
            market_state=observation.market_state,
            sector_state=observation.sector_state,
            alternative_explanations=observation.alternative_explanations,
            available_at=observation.available_at,
            snapshot_ids=observation.snapshot_ids,
            hard_valid=observation.hard_valid,
            pit_grade=observation.pit_grade,
            industry_pit_grade=observation.industry_pit_grade,
            parameter_id=self.parameters.parameter_id,
            edge_card=None,
            execution_status="BLOCKED_UNCALIBRATED",
            unfilled_reason="OOS_CALIBRATION_REQUIRED",
            root_anchor_id=memory.accumulation_anchor.anchor_id,
            working_anchor_id=working_anchor.anchor_id,
            anchor_chain_ids=tuple(anchor.anchor_id for anchor in memory.anchor_chain),
            anchor_retention_lower=estimate.lower,
            anchor_retention_upper=estimate.upper,
            anchor_retention_confidence=estimate.confidence,
            anchor_model_retentions=tuple(
                (model.value, value) for model, value in estimate.model_retentions
            ),
        )

    def _advance_open(
        self, memory: LifecycleMemory, observation: LifecycleObservation
    ) -> TransitionResult:
        # An exit intent is not an exit fill.  Keep the position and its intent
        # alive until the execution layer confirms a legal sell; otherwise a
        # limit-down/suspension day would silently erase the blocked exposure.
        if memory.pending_exit_reason is not None:
            return TransitionResult(memory)
        if observation.corporate_action_blocking:
            reason = ExitReason.CORPORATE_ACTION
            return TransitionResult(
                replace(memory, pending_exit_reason=reason), exit_reason=reason
            )
        if not observation.hard_valid:
            reason = ExitReason.DATA_INVALID
            return TransitionResult(
                replace(memory, pending_exit_reason=reason), exit_reason=reason
            )
        if not observation.peak_identity_valid:
            reason = ExitReason.DATA_INVALID
            return TransitionResult(
                replace(memory, pending_exit_reason=reason), exit_reason=reason
            )
        # A suspended position remains exposed, but no trading-day confirmation
        # or holding-window counter is consumed because no legal exit exists.
        if not observation.tradable:
            return TransitionResult(memory)
        if memory.accumulation_anchor is None:
            raise ValueError("open lifecycle is missing its frozen accumulation anchor")
        if (
            exact_anchor_retention(
                memory.accumulation_anchor,
                observation,
                resolver=self.anchor_retention_resolver,
            )
            is None
        ):
            reason = ExitReason.DATA_INVALID
            return TransitionResult(
                replace(memory, pending_exit_reason=reason), exit_reason=reason
            )

        holding_days = memory.holding_days + 1
        base = replace(memory, holding_days=holding_days)
        support = memory.breakout_support or observation.structure_support
        if chip_structure_broken(
            memory.accumulation_anchor,
            observation,
            self.config.fixed,
            comparison_anchor=memory.comparison_anchor,
            resolver=self.anchor_retention_resolver,
        ):
            reason = ExitReason.STRUCTURE_BROKEN
            return TransitionResult(
                replace(base, pending_exit_reason=reason), exit_reason=reason
            )
        if observation.close < support - self.parameters.protective_stop_atr * observation.atr:
            reason = ExitReason.PROTECTIVE_STOP
            return TransitionResult(
                replace(base, pending_exit_reason=reason), exit_reason=reason
            )
        if holding_days >= self.config.windows.max_holding:
            reason = ExitReason.MAX_HOLDING_PERIOD
            return TransitionResult(
                replace(base, pending_exit_reason=reason), exit_reason=reason
            )

        distributing = (
            distribution_score_with_anchor(
                memory.accumulation_anchor,
                observation,
                self.config.fixed,
                resolver=self.anchor_retention_resolver,
            )
            >= self.parameters.distribution_score_min
        )
        distribution_days = memory.distribution_days + 1 if distributing else 0
        cancelled = (
            memory.distribution_days == 1
            and not distributing
            and self._breakout_support_regained(memory, observation)
        )
        state = (
            ChipLifecycleState.DISTRIBUTING
            if distribution_days
            else ChipLifecycleState.RETEST_READY
        )
        updated = replace(
            memory,
            state=state,
            distribution_days=distribution_days,
            holding_days=holding_days,
        )
        if distribution_days >= self.config.windows.exit_confirmation:
            reason = ExitReason.DISTRIBUTION_CONFIRMED
            return TransitionResult(
                replace(updated, pending_exit_reason=reason), exit_reason=reason
            )
        return TransitionResult(updated, soft_exit_cancelled=cancelled)

    def _breakout_support_regained(
        self, memory: LifecycleMemory, observation: LifecycleObservation
    ) -> bool:
        if memory.breakout_support is None:
            raise ValueError("lifecycle is missing frozen breakout support")
        return (
            observation.close
            >= memory.breakout_support
            - self.config.fixed.support_tolerance_atr * observation.atr
            and observation.close_vs_vwap >= 0
        )

    @staticmethod
    def _breakout_price_structure_broken(
        memory: LifecycleMemory, observation: LifecycleObservation
    ) -> bool:
        if memory.breakout_support is None:
            raise ValueError("lifecycle is missing frozen breakout support")
        return observation.close < memory.breakout_support - 1.5 * observation.atr

    def after_exit(self) -> LifecycleMemory:
        return LifecycleMemory(cooldown_remaining=self.config.windows.cooldown)


def build_calibrated_edge_card(
    signal: StrategySignal,
    *,
    expected_payoff_r: float,
    calibrated_probability: float,
    calibration_ece: float,
    calibration_baseline_brier: float,
    calibration_model_brier: float,
    capacity_fraction_adv: float,
    ece_limit: float,
) -> EdgeCard:
    """Authorize an EdgeCard only from next-period OOS calibration evidence."""

    if not 0.0 < calibrated_probability < 1.0:
        raise ValueError("calibrated probability must be in (0, 1)")
    if calibration_ece > ece_limit:
        raise ValueError("calibration ECE gate failed")
    if calibration_model_brier >= calibration_baseline_brier:
        raise ValueError("calibration does not beat the baseline occurrence rate")
    card = EdgeCard(
        edge_source="筹码吸筹、突破、缩量回踩和成本上移的因果时序差",
        counterparty_state="集中黏性资金承接是假说；保留被动资金与注意力替代解释",
        why_they_act_now="突破后供给缩减且回踩承接确认，存量持有者有维持新成本区的激励",
        why_edge_persists="成本迁移和底仓松动通常跨越多个交易日完成",
        expected_payoff_r=expected_payoff_r,
        capacity_fraction_adv=capacity_fraction_adv,
        adversarial_response="假突破、价格支撑撤回、限制价流动性消失和拥挤交易",
        expiry_rule="最长持有窗口到期或成本迁移停止",
        invalidation="主峰/结构支撑失守、底仓松动、派发确认或数据失效",
        falsifiable_explanations=signal.alternative_explanations,
        evidence_for=(
            *signal.evidence_for,
            f"oos_calibrated_probability={calibrated_probability:.6f}",
        ),
        evidence_against=signal.evidence_against,
    )
    if not card.complete:
        raise ValueError("calibrated EdgeCard is incomplete: " + ", ".join(card.missing_fields()))
    return card


def authorize_signal(
    signal: StrategySignal,
    *,
    edge_card: EdgeCard,
) -> StrategySignal:
    """Return an executable next-window signal after calibration gates pass."""

    if not edge_card.complete:
        raise ValueError("cannot authorize a signal with an incomplete EdgeCard")
    return replace(
        signal,
        edge_card=edge_card,
        execution_status="READY_FOR_NEXT_WINDOW",
        unfilled_reason=None,
    )
