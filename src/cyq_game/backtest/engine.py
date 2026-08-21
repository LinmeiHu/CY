from __future__ import annotations

import csv
import hashlib
import json
from collections import deque
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta
from math import exp, floor, sqrt
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from cyq_game.chip import (
    ChipFeatures,
    ChipState,
    CohortChipEngine,
    UniformChipEngine,
    advance_chip_state,
    apply_split_to_state,
)
from cyq_game.config import SystemConfig
from cyq_game.data import (
    ChipObservation,
    DataExecutionAuthorization,
    DataOperation,
    EventStore,
    PITStore,
    PreparedChipRecord,
)
from cyq_game.domain import (
    Action,
    Bar,
    DecisionContext,
    OrderSide,
    OrderStatus,
    PlanStatus,
    RiskFlag,
)
from cyq_game.execution import (
    PlanRepository,
    SimBroker,
    SimOrder,
    TradingPlan,
    apply_split_to_order,
)
from cyq_game.fundamentals import (
    FundamentalSnapshot,
    classify_fundamentals,
    unavailable_fundamentals,
)
from cyq_game.game import (
    DecisionEngine,
    GameDecision,
    build_edge_card,
    build_scenarios,
    infer_participants,
)
from cyq_game.portfolio import (
    CalibratedForecast,
    PortfolioConstraints,
    fractional_kelly_size,
)
from cyq_game.state import (
    MarketState,
    RegimeClassifier,
    SectorState,
    StockClassifier,
    StockEvidence,
    classify_sectors_leave_one_out,
)

from .diagnostics import DecisionGateAccumulator, build_research_diagnostics
from .metrics import performance_metrics
from .walkforward import WalkForwardFold, WalkForwardPlan, build_walk_forward

TERMINAL_ORDER_STATES = {
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
    OrderStatus.BLOCKED,
}


@dataclass(frozen=True)
class BacktestResult:
    run_id: str
    run_dir: Path
    summary_path: Path
    event_path: Path
    event_digest: str
    metrics: dict[str, float | int]
    holdout_tainted: bool


@dataclass(frozen=True)
class OrderGenerationResult:
    status: str
    reason: str
    order: SimOrder | None = None
    order_status: str | None = None
    order_reject_reason: str | None = None
    size_target_fraction: float | None = None
    size_unconstrained_kelly: float | None = None
    size_applied_caps: tuple[str, ...] | None = None
    size_rejected_reason: str | None = None


@dataclass(frozen=True)
class _RollingStats:
    sample_count: int
    return_5: float
    return_20: float
    return_60: float
    volatility: float
    turnover_zscore: float
    average_amount: float
    volume_contraction: float
    low_120: float
    high_20: float
    previous_high: float
    history_low_2y: float
    history_high_2y: float


class _RollingStatsTracker:
    """Maintain the daily rolling inputs in O(1) amortized time."""

    def __init__(self) -> None:
        self._index = -1
        self._closes: deque[float] = deque(maxlen=61)
        self._returns: deque[float] = deque()
        self._return_sum = 0.0
        self._return_sq_sum = 0.0
        self._turnovers: deque[float] = deque()
        self._turnover_sum = 0.0
        self._turnover_sq_sum = 0.0
        self._amounts: deque[float] = deque()
        self._amount_sum = 0.0
        self._volumes_5: deque[float] = deque()
        self._volume_5_sum = 0.0
        self._volumes_20: deque[float] = deque()
        self._volume_20_sum = 0.0
        self._low_120: deque[tuple[int, float]] = deque()
        self._high_20: deque[tuple[int, float]] = deque()
        self._low_504: deque[tuple[int, float]] = deque()
        self._high_504: deque[tuple[int, float]] = deque()

    def update(self, bar: Bar) -> _RollingStats:
        self._index += 1
        index = self._index
        previous_high = self._high_20[0][1] if self._high_20 else bar.close
        previous_close = self._closes[-1] if self._closes else None
        self._closes.append(bar.close)
        if previous_close is not None:
            daily_return = bar.close / previous_close - 1.0
            self._return_sum, self._return_sq_sum = _append_moment(
                self._returns,
                daily_return,
                20,
                self._return_sum,
                self._return_sq_sum,
            )
        self._turnover_sum, self._turnover_sq_sum = _append_moment(
            self._turnovers,
            bar.turnover,
            60,
            self._turnover_sum,
            self._turnover_sq_sum,
        )
        self._amount_sum = _append_sum(self._amounts, bar.amount, 20, self._amount_sum)
        self._volume_5_sum = _append_sum(self._volumes_5, bar.volume, 5, self._volume_5_sum)
        self._volume_20_sum = _append_sum(self._volumes_20, bar.volume, 20, self._volume_20_sum)
        _append_monotonic(self._low_120, index, bar.close, 120, increasing=True)
        _append_monotonic(self._high_20, index, bar.close, 20, increasing=False)
        _append_monotonic(self._low_504, index, bar.low, 504, increasing=True)
        _append_monotonic(self._high_504, index, bar.high, 504, increasing=False)

        turnover_count = len(self._turnovers)
        turnover_mean = self._turnover_sum / turnover_count
        turnover_deviation = sqrt(
            max(0.0, self._turnover_sq_sum / turnover_count - turnover_mean**2)
        )
        volatility = 0.0
        if len(self._returns) >= 2:
            return_mean = self._return_sum / len(self._returns)
            volatility = sqrt(
                max(
                    0.0,
                    self._return_sq_sum / len(self._returns) - return_mean**2,
                )
            )
        volume_contraction = 0.0
        if index + 1 >= 10:
            recent_volume = self._volume_5_sum / len(self._volumes_5)
            baseline_volume = self._volume_20_sum / len(self._volumes_20)
            volume_contraction = max(0.0, 1.0 - recent_volume / max(baseline_volume, 1e-12))
        return _RollingStats(
            sample_count=index + 1,
            return_5=self._period_return(5),
            return_20=self._period_return(20),
            return_60=self._period_return(60),
            volatility=volatility,
            turnover_zscore=(
                (bar.turnover - turnover_mean) / turnover_deviation
                if turnover_count >= 3 and turnover_deviation > 1e-12
                else 0.0
            ),
            average_amount=self._amount_sum / len(self._amounts),
            volume_contraction=volume_contraction,
            low_120=self._low_120[0][1],
            high_20=self._high_20[0][1],
            previous_high=previous_high,
            history_low_2y=self._low_504[0][1],
            history_high_2y=self._high_504[0][1],
        )

    def _period_return(self, periods: int) -> float:
        if self._index + 1 <= periods:
            return 0.0
        return self._closes[-1] / self._closes[-periods - 1] - 1.0


def _append_sum(values: deque[float], value: float, limit: int, current_sum: float) -> float:
    if len(values) == limit:
        current_sum -= values.popleft()
    values.append(value)
    return current_sum + value


def _append_moment(
    values: deque[float],
    value: float,
    limit: int,
    current_sum: float,
    current_sq_sum: float,
) -> tuple[float, float]:
    if len(values) == limit:
        removed = values.popleft()
        current_sum -= removed
        current_sq_sum -= removed * removed
    values.append(value)
    return current_sum + value, current_sq_sum + value * value


def _append_monotonic(
    values: deque[tuple[int, float]],
    index: int,
    value: float,
    limit: int,
    *,
    increasing: bool,
) -> None:
    oldest = index - limit
    while values and values[0][0] <= oldest:
        values.popleft()
    while values and (values[-1][1] >= value if increasing else values[-1][1] <= value):
        values.pop()
    values.append((index, value))


class BacktestEngine:
    """PIT-safe daily research loop with deterministic next-bar execution."""

    def __init__(
        self,
        config: SystemConfig,
        *,
        run_id: str,
        config_text: str,
        data_authorization: DataExecutionAuthorization,
        hypothesis: str = "CYQ cost-state and participant-game edge",
        store: PITStore | None = None,
    ) -> None:
        if data_authorization.operation not in {
            DataOperation.BACKTEST,
            DataOperation.ROBUSTNESS,
        }:
            raise ValueError("BacktestEngine requires BACKTEST or ROBUSTNESS data authorization")
        if not data_authorization.hard_valid:
            raise ValueError("hard_valid=false blocks BacktestEngine")
        self.config = config
        self.run_id = run_id
        self.config_text = config_text
        self.hypothesis = hypothesis
        self.data_authorization = data_authorization
        self.store = store or PITStore(config.database_path)
        self.run_dir = config.run_dir / run_id
        self.events = EventStore(self.run_dir / "events.jsonl")
        self.broker = SimBroker(config.execution, config.initial_cash)
        self.plans = PlanRepository(self.events, run_id)
        self.regimes = RegimeClassifier()
        self.stock_classifier = StockClassifier()
        self.decisions = DecisionEngine(config.decision, config.execution)
        self._chip_engine = (
            CohortChipEngine(config.chip.lambda_turnover)
            if config.chip.engine == "cohort"
            else UniformChipEngine(config.chip.lambda_turnover)
        )
        self._chip_states: dict[str, ChipState] = {}
        self._base_bands: dict[str, tuple[float, float, float]] = {}
        self._processed_actions: set[str] = set()
        self._invalid_symbols: set[str] = set()
        self._prior_scores: dict[str, float] = {}
        self._prior_controls: dict[str, float] = {}
        self._prior_stops: dict[str, float] = {}
        self._latest_prices: dict[str, float] = {}
        self._peak_equity = config.initial_cash
        self._order_generation_failures = 0
        self._fractional_split_adjustments = 0
        self._fractional_split_entitlement_total = 0.0
        self._unresolved_split_cost_basis = 0.0

    def run(
        self,
        start: date,
        end: date,
        *,
        history_start: date | None = None,
        symbols: list[str] | None = None,
        access_final_holdout: bool = False,
    ) -> BacktestResult:
        history_start = history_start or start
        if end < start:
            raise ValueError("end must not precede start")
        if history_start > start:
            raise ValueError("history_start must not follow evaluation start")
        if (
            history_start < self.data_authorization.scope_start
            or end > self.data_authorization.scope_end
        ):
            raise ValueError(
                "backtest range falls outside the authorized input snapshot scope: "
                f"{self.data_authorization.scope_start}.."
                f"{self.data_authorization.scope_end}"
            )
        if access_final_holdout and not self.config.backtest.allow_holdout_access:
            raise ValueError("configuration forbids final holdout access")
        if self.events.path.exists():
            raise FileExistsError(f"run already exists: {self.run_dir}")

        self.store.initialize()
        supports_native_forecast = self.store.supports_native_forecast
        supports_precomputed_chip = self.store.supports_precomputed_chip_features
        supports_fundamentals = self.store.supports_fundamental_signals
        requires_intraday_evidence = self.store.requires_intraday_evidence
        self.store.require_input_manifest(
            registry_id=self.data_authorization.registry_id,
            registry_sha256=self.data_authorization.registry_sha256,
            input_manifest_id=self.data_authorization.input_manifest_id,
            input_manifest_sha256=self.data_authorization.input_manifest_sha256,
        )
        available = self.store.symbols()
        available_set = set(available)
        if symbols is None:
            symbols = available
        else:
            symbols = [symbol for symbol in symbols if symbol in available_set]
        if not symbols:
            raise ValueError("no symbols selected for backtest")
        if not available:
            raise ValueError("PIT store contains no market bars")
        symbol_boards = {symbol: _board(symbol) for symbol in symbols}
        runtime_timezone = self.store.decision_timezone
        calendar_at = datetime.combine(end, time.max, tzinfo=runtime_timezone)
        dates = self.store.trading_dates_as_of(history_start, end, calendar_at, symbols)
        if not dates:
            raise ValueError("selected range contains no available trading dates")
        plan = build_walk_forward(
            dates,
            final_holdout_fraction=self.config.backtest.final_holdout_fraction,
            purge_days=self.config.backtest.purge_days,
            embargo_days=self.config.backtest.embargo_days,
            evaluation_start=start,
            minimum_train_days=max(60, self.config.chip.warmup_days),
        )
        run_dates = dates if access_final_holdout else list(plan.development_dates)
        if not run_dates:
            raise ValueError("walk-forward plan contains no runnable development dates")
        evaluation_dates = [item for item in run_dates if item >= start]
        if not evaluation_dates:
            raise ValueError("walk-forward plan contains no evaluation dates")
        self.run_dir.mkdir(parents=True, exist_ok=False)
        fold_by_date = {test_date: fold for fold in plan.folds for test_date in fold.test_dates}
        final_holdout_dates = set(plan.final_holdout_dates)
        started_at = datetime.combine(run_dates[0], time(0), tzinfo=runtime_timezone)
        self.store.register_experiment(
            experiment_id=self.run_id,
            hypothesis=self.hypothesis,
            config_text=self.config_text,
            run_id=self.run_id,
            created_at=started_at,
        )
        if access_final_holdout:
            self.store.mark_holdout_tainted(self.run_id)
        self._event(
            "RUN_STARTED",
            {
                "history_start": history_start.isoformat(),
                "evaluation_start": start.isoformat(),
                "evaluation_end": end.isoformat(),
                "symbols": symbols,
                "holdout_accessed": access_final_holdout,
            },
            started_at,
        )

        histories: dict[str, list[Bar]] = {symbol: [] for symbol in symbols}
        rolling_trackers = {symbol: _RollingStatsTracker() for symbol in symbols}
        latest_prices = self._latest_prices
        forecast_cache: dict[int, dict[str, CalibratedForecast]] = {}
        pending_by_symbol: dict[str, SimOrder] = {}
        decisions_path = self.run_dir / "decisions.jsonl"
        decision_handle = decisions_path.open("xb", buffering=8 * 1024 * 1024)
        decision_buffer: list[str] = []
        decision_encoder = json.JSONEncoder(
            ensure_ascii=False,
            separators=(",", ":"),
            check_circular=False,
        )
        decision_digest = hashlib.sha256()
        gate_accumulator = DecisionGateAccumulator()
        equity_rows: list[dict[str, Any]] = []
        market_level = 1.0
        market_peak = 1.0
        previous_closes: dict[str, float] = {}
        gross_profit = 0.0
        gross_loss = 0.0
        prior_equity = self.config.initial_cash
        submitted_orders = 0
        blocked_orders = 0
        rejected_orders = 0
        active_history_count = 0
        missing_fundamentals = unavailable_fundamentals()
        missing_fundamental_state = _jsonable(asdict(missing_fundamentals))
        missing_fundamental_evidence = list(missing_fundamentals.contradictions)

        for index, trade_date in enumerate(run_dates):
            decision_at = datetime.combine(trade_date, time(15, 30), tzinfo=runtime_timezone)
            execution_current = self.store.execution_bars_for_day(symbols, trade_date, decision_at)
            if not execution_current:
                continue
            current = self.store.strict_bars_for_day(symbols, trade_date, decision_at)
            current_symbols = list(current)
            active_rule_symbols = set(current) if trade_date >= start else set()
            rules = (
                self.store.rules_as_of(
                    {symbol: symbol_boards[symbol] for symbol in active_rule_symbols},
                    trade_date,
                    decision_at,
                )
                if active_rule_symbols
                else {}
            )
            prepared_chip_records = (
                self.store.prepared_chip_features_for_day(current_symbols, trade_date, decision_at)
                if trade_date >= start
                else {}
            )
            chip_observations = (
                {}
                if supports_precomputed_chip
                else self.store.chip_observations_for_day(current_symbols, trade_date, decision_at)
            )
            fundamental_records = {}
            execution_batch = self.store.execution_batch_for_day(
                {symbol: symbol_boards[symbol] for symbol in pending_by_symbol},
                trade_date,
                decision_at,
            )
            market_open_at = datetime.combine(trade_date, time(9, 30), tzinfo=runtime_timezone)
            self._apply_corporate_actions(
                symbols,
                trade_date,
                market_open_at,
                pending_by_symbol,
                previous_closes,
            )

            for symbol, order in list(pending_by_symbol.items()):
                windows = execution_batch.windows.get(symbol)
                invalid_at = execution_batch.invalid_at.get(symbol)
                if not windows and invalid_at is None:
                    continue
                rule = execution_batch.rules.get(symbol)
                if rule is None and invalid_at is None:
                    continue
                for execution_bar in windows or ():
                    if (
                        order.side == OrderSide.BUY
                        and invalid_at is not None
                        and invalid_at <= execution_bar.available_at
                    ):
                        break
                    if rule is None:
                        break
                    before = order.status
                    fill = self.broker.process_bar(order, execution_bar, rule)
                    event_at = execution_bar.available_at
                    if order.status != before:
                        self._event(
                            "ORDER_STATE_CHANGED",
                            _order_payload(order),
                            event_at,
                        )
                    if fill is not None:
                        self._event("ORDER_FILLED", _jsonable(asdict(fill)), event_at)
                    if order.status in TERMINAL_ORDER_STATES:
                        break
                if (
                    order.side == OrderSide.BUY
                    and invalid_at is not None
                    and order.status not in TERMINAL_ORDER_STATES
                ):
                    before = order.status
                    self.broker.block(order, "HARD_VALID_FALSE_AT_FILL")
                    if order.status != before:
                        self._event(
                            "ORDER_STATE_CHANGED",
                            _order_payload(order),
                            invalid_at,
                        )
                if order.status == OrderStatus.BLOCKED:
                    blocked_orders += 1
                if order.status == OrderStatus.REJECTED:
                    rejected_orders += 1
                if order.status in TERMINAL_ORDER_STATES:
                    pending_by_symbol.pop(symbol, None)

            for symbol, bar in execution_current.items():
                latest_prices[symbol] = bar.close

            daily_returns: list[float] = []
            rolling_stats: dict[str, _RollingStats] = {}
            member_returns: dict[str, float] = {}
            return_20_values: list[float] = []
            volatilities: list[float] = []
            liquidity_ratios: list[float] = []
            turnover_zscores: list[float] = []
            for symbol, bar in current.items():
                prior = previous_closes.get(symbol)
                if prior is not None:
                    daily_returns.append(bar.close / prior - 1.0)
                previous_closes[symbol] = bar.close
                histories[symbol].append(bar)
                stats = rolling_trackers[symbol].update(bar)
                rolling_stats[symbol] = stats
                member_returns[symbol] = stats.return_20
                return_20_values.append(stats.return_20)
                volatilities.append(stats.volatility)
                turnover_zscores.append(stats.turnover_zscore)
                liquidity_ratios.append(bar.amount / max(stats.average_amount, 1.0))
                if stats.sample_count == 1:
                    active_history_count += 1
                if supports_native_forecast and len(histories[symbol]) > 1:
                    # Native forecasts and incremental rolling statistics make
                    # historical Bar retention redundant. Keep only today's
                    # bar for evidence fields that need the current OHLC.
                    del histories[symbol][:-1]
            market_return = fmean(daily_returns) if daily_returns else 0.0
            market_level *= 1.0 + market_return
            market_peak = max(market_peak, market_level)
            market = self._market_state(
                return_20_values=return_20_values,
                volatilities=volatilities,
                liquidity_ratios=liquidity_ratios,
                turnover_zscores=turnover_zscores,
                drawdown=market_level / market_peak - 1.0,
                current_count=len(current),
                active_history_count=active_history_count,
            )
            if trade_date < start:
                if not supports_precomputed_chip:
                    for symbol, bar in current.items():
                        self._warm_chip(symbol, bar, chip_observations.get(symbol))
                continue
            trade_date_text = trade_date.isoformat()
            decision_at_text = decision_at.isoformat()
            bar_provenance_records = self.store.bar_provenances_for_day(
                current_symbols, trade_date, decision_at
            )
            if supports_fundamentals:
                fundamental_records = self.store.fundamentals_as_of(
                    current_symbols, trade_date, decision_at
                )
            market_return_20 = fmean(return_20_values) if return_20_values else 0.0
            memberships = self.store.industry_memberships_as_of(
                current_symbols, trade_date, decision_at
            )
            returns_by_industry: dict[str, dict[str, float]] = {}
            amounts_by_industry: dict[str, dict[str, float]] = {}
            for member_symbol, member_membership in memberships.items():
                if member_symbol not in member_returns:
                    continue
                group_industry = member_membership.industry
                returns_by_industry.setdefault(group_industry, {})[member_symbol] = member_returns[
                    member_symbol
                ]
                member_bar = current.get(member_symbol)
                if member_bar is not None:
                    amounts_by_industry.setdefault(group_industry, {})[member_symbol] = (
                        member_bar.amount
                    )
            sector_states: dict[str, SectorState] = {}
            for industry, industry_returns in returns_by_industry.items():
                sector_states.update(
                    classify_sectors_leave_one_out(
                        member_returns=industry_returns,
                        market_return=market_return_20,
                        member_amounts=amounts_by_industry.get(industry, {}),
                    )
                )
            fold = fold_by_date.get(trade_date)
            active_fold = fold
            if access_final_holdout and trade_date in final_holdout_dates:
                active_fold = _holdout_fold(plan)
            if active_fold is not None and active_fold.fold_id not in forecast_cache:
                if supports_native_forecast:
                    forecast_cache[active_fold.fold_id] = self.store.calibrate_forecasts(
                        symbols, set(active_fold.train_dates), decision_at
                    )
                else:
                    train_dates = set(active_fold.train_dates)
                    forecast_cache[active_fold.fold_id] = {
                        symbol: _calibrate_forecast({symbol: histories[symbol]}, train_dates)
                        for symbol in symbols
                    }

            decision_equity = self._equity(latest_prices)
            decision_gross_exposure = self._gross_exposure()
            gross_exposure_fraction = decision_gross_exposure / max(decision_equity, 1e-12)
            safe_equity = max(decision_equity, 1e-12)
            daily_order_value = 0.02 * decision_equity
            active_fold_id = active_fold.fold_id if active_fold else None
            forecast_train_start = (
                active_fold.train_dates[0].isoformat()
                if active_fold and active_fold.train_dates
                else None
            )
            forecast_train_end = (
                active_fold.train_dates[-1].isoformat()
                if active_fold and active_fold.train_dates
                else None
            )
            market_phase = market.phase.value
            market_phase_scores = {
                key.value: _finite(value) for key, value in market.phase_scores.items()
            }
            market_overlays = [item.value for item in market.overlays]
            market_reasons = list(market.reasons)
            market_trend = _finite(market.trend)
            market_breadth = _finite(market.breadth)
            market_volatility_percentile = _finite(market.volatility_percentile)
            missing_sector = SectorState(0.0, 0.5, 0.5, 0.5, 0.5, 0.0, 0)
            for symbol, bar in current.items():
                stats = rolling_stats[symbol]
                average_amount = max(stats.average_amount, 1.0)
                prepared_chip = prepared_chip_records.get(symbol)
                if supports_precomputed_chip:
                    if prepared_chip is None:
                        # A missing PIT frozen state makes this symbol
                        # ineligible for new risk; omit it from today's
                        # decision universe rather than fabricating features.
                        continue
                    features = prepared_chip.features
                    intraday_source: ChipObservation | PreparedChipRecord | None = prepared_chip
                    base_retention = prepared_chip.base_retention
                    chip_hard_valid = prepared_chip.strict_sample
                else:
                    features = self._update_chip(
                        symbol,
                        bar,
                        stats,
                        chip_observations.get(symbol),
                    )
                    intraday_source = chip_observations.get(symbol)
                    base_retention = None
                    chip_hard_valid = True
                membership = memberships.get(symbol)
                asset_industry = membership.industry if membership is not None else None
                sector = sector_states.get(symbol, missing_sector)
                sector_alpha_score = (
                    sector.score if self.config.decision.sector_alpha_enabled else 0.5
                )
                evidence = self._stock_evidence(
                    symbol,
                    histories[symbol],
                    stats,
                    features.concentration_20,
                    market.breadth,
                    sector_alpha_score,
                    intraday_source,
                    base_retention=base_retention,
                    chip_hard_valid=chip_hard_valid,
                    requires_intraday_evidence=requires_intraday_evidence,
                )
                stock = self.stock_classifier.classify(features, evidence)
                data_quality = min(features.quality, evidence.data_quality)
                rule = rules[symbol]
                execution_probability = _execution_probability(bar, rule.known)
                fundamental_record = fundamental_records.get(symbol)
                if not supports_fundamentals:
                    fundamentals = missing_fundamentals
                    fundamental_score: float | None = None
                elif fundamental_record is None:
                    fundamentals = missing_fundamentals
                    fundamental_score = fundamentals.composite
                else:
                    fundamentals = classify_fundamentals(
                        FundamentalSnapshot(
                            revenue_growth=fundamental_record.revenue_growth,
                            profit_growth=fundamental_record.profit_growth,
                            roe=fundamental_record.roe,
                            operating_cashflow_to_profit=(
                                fundamental_record.operating_cashflow_to_profit
                            ),
                            debt_ratio=fundamental_record.debt_ratio,
                            valuation_percentile=(fundamental_record.valuation_percentile),
                            earnings_revision=fundamental_record.earnings_revision,
                            available_at=fundamental_record.available_at,
                            source=fundamental_record.source,
                            period_end=fundamental_record.period_end,
                            effective_from=fundamental_record.effective_from,
                            investment_growth=fundamental_record.investment_growth,
                            capital_return=fundamental_record.capital_return,
                            audit_or_going_concern_risk=(
                                fundamental_record.audit_or_going_concern_risk
                            ),
                            snapshot_id=fundamental_record.snapshot_id,
                            revision_id=fundamental_record.revision_id,
                        )
                    )
                    fundamental_score = fundamentals.composite
                if fundamentals.blocks_new_risk:
                    fundamental_reason = "基本面审计或持续经营风险"
                    stock = replace(
                        stock,
                        risk=replace(
                            stock.risk,
                            flags=stock.risk.flags | frozenset({RiskFlag.HARD_INVALID}),
                            hard_valid=False,
                            reasons=(
                                stock.risk.reasons
                                if fundamental_reason in stock.risk.reasons
                                else (*stock.risk.reasons, fundamental_reason)
                            ),
                        ),
                    )
                ecology = infer_participants(
                    stock,
                    fundamental_score=fundamental_score,
                    attention=max(
                        min(1.0, max(0.0, evidence.turnover_zscore / 3.0)),
                        evidence.intraday_attention,
                    ),
                    liquidity_supply=min(
                        1.0,
                        bar.amount / average_amount,
                    ),
                    model_disagreement=1.0 - stock.reliability,
                    hidden_event_risk=(
                        1.0
                        if fundamentals.blocks_new_risk
                        else 0.25
                        if symbol in self._invalid_symbols
                        else 0.0
                    ),
                    data_quality=data_quality,
                )
                family, edge_card = build_edge_card(
                    stock, ecology, fundamental_score=fundamental_score
                )
                sector_sizing_confidence = (
                    sector.reliability if self.config.decision.sector_alpha_enabled else 1.0
                )
                position_value = self.broker.position(symbol) * bar.close
                equity = decision_equity
                position_fraction = position_value / safe_equity
                context = _decision_context(
                    symbol=symbol,
                    at=decision_at,
                    data_quality=(0.0 if symbol in self._invalid_symbols else data_quality),
                    observability=ecology.observability,
                    execution_probability=execution_probability,
                    market_confidence=market.reliability,
                    sector_confidence=sector_sizing_confidence,
                    disagreement=1.0 - stock.reliability,
                )
                scenarios = (
                    build_scenarios(stock, market, context, edge_card)
                    if edge_card is not None
                    else ()
                )
                proposed_stop = max(bar.low * 0.97, features.p10 * 0.98)
                prior_stop = self._prior_stops.get(symbol)
                stock_score = stock.score(stock.primary)
                decision = self.decisions.decide(
                    stock=stock,
                    market=market,
                    context=context,
                    ecology=ecology,
                    edge_card=edge_card,
                    family=family,
                    scenarios=scenarios,
                    price=bar.close,
                    order_value=daily_order_value,
                    adv_value=average_amount,
                    position_fraction=position_fraction,
                    posterior_improved=(stock_score > self._prior_scores.get(symbol, 1.0) + 0.03),
                    prior_protective_stop=prior_stop,
                    proposed_protective_stop=proposed_stop,
                )
                self._prior_scores[symbol] = stock_score
                self._prior_controls[symbol] = evidence.control_score
                cyqk_pre = features.cyqk_pre
                row = {
                    "trade_date": trade_date_text,
                    "symbol": symbol,
                    "decision_at": decision_at_text,
                    "industry": asset_industry,
                    "fold_id": active_fold_id,
                    "market_phase": market_phase,
                    "market_phase_scores": market_phase_scores,
                    "market_overlays": market_overlays,
                    "market_reasons": market_reasons,
                    "market_trend": market_trend,
                    "market_breadth": market_breadth,
                    "market_volatility_percentile": market_volatility_percentile,
                    "sector_score": sector.score,
                    "sector_reliability": sector.reliability,
                    "sector_sizing_confidence": sector_sizing_confidence,
                    "sector_member_count_loo": sector.member_count,
                    "sector_alpha_enabled": self.config.decision.sector_alpha_enabled,
                    "stock_types": [item.stock_type.value for item in stock.types],
                    "primary_type": stock.primary.value,
                    "family": family.value,
                    "action": decision.action.value,
                    "q_values": {
                        key.value: _finite(value) for key, value in decision.q_values.items()
                    },
                    "raw_edge_r": decision.raw_edge_r,
                    "adjusted_edge_r": decision.adjusted_edge_r,
                    "observability": decision.observability,
                    "reliability": stock.reliability,
                    "gates": list(decision.gates),
                    "cyqk_pre": {
                        "open": cyqk_pre.open,
                        "high": cyqk_pre.high,
                        "low": cyqk_pre.low,
                        "close": cyqk_pre.close,
                    },
                    "chip_features": {
                        "p01": _finite(features.p01),
                        "p10": _finite(features.p10),
                        "p50": _finite(features.p50),
                        "p90": _finite(features.p90),
                        "p99": _finite(features.p99),
                        "profit_ratio": _finite(features.profit_ratio),
                        "trapped_ratio": _finite(features.trapped_ratio),
                        "average_cost": _finite(features.average_cost),
                        "concentration_20": _finite(features.concentration_20),
                        "chip_width": _finite(features.cbw),
                        "asr": _finite(features.asr),
                        "base_retention": _finite(stock.evidence.get("base_retention")),
                        "historical_position_2y": _finite(features.rpy2),
                    },
                    "price_levels": {
                        "close": _finite(bar.close),
                        "support_120d_low": _finite(stats.low_120),
                        "pressure_20d_high": _finite(stats.previous_high),
                        "historical_low_2y": _finite(stats.history_low_2y),
                        "historical_high_2y": _finite(stats.history_high_2y),
                        "position_2y": _finite(features.rpy2),
                        "new_high": bool(stock.evidence.get("new_high", False)),
                        "failed_breakout": bool(stock.evidence.get("failed_breakout", False)),
                    },
                    "decision_explanation": {
                        "stock_states": [
                            {"state": item.stock_type.value, "score": _finite(item.score)}
                            for item in stock.types
                        ],
                        "stock_reasons": list(stock.explanations),
                        "risk_reasons": list(stock.risk.reasons),
                        "gates": list(decision.gates),
                        "action_rule": (
                            "选择Q值最高动作；相对NO_TRADE的优势不足0.25则不交易；"
                            "风险闸门可覆盖动作"
                        ),
                    },
                    "chip_quality": features.quality,
                    "minute_evidence_required": requires_intraday_evidence,
                    "minute_evidence_available": (
                        intraday_source is not None and intraday_source.intraday_factors_complete
                    ),
                    "intraday_confirmation": evidence.intraday_confirmation,
                    "intraday_conflict": evidence.intraday_conflict,
                    "intraday_attention": evidence.intraday_attention,
                    "fundamental_coverage": fundamentals.coverage,
                    "fundamental_signal_active": (supports_fundamentals),
                    "fundamental_evidence": (
                        missing_fundamental_evidence
                        if fundamentals is missing_fundamentals
                        else list(fundamentals.contradictions)
                    ),
                    "fundamental_state": (
                        missing_fundamental_state
                        if fundamentals is missing_fundamentals
                        else _jsonable(asdict(fundamentals))
                    ),
                    "fundamental_source": (
                        fundamental_record.source if fundamental_record else None
                    ),
                    "fundamental_period_end": (
                        fundamental_record.period_end.isoformat() if fundamental_record else None
                    ),
                    "fundamental_available_at": (
                        fundamental_record.available_at.isoformat() if fundamental_record else None
                    ),
                    "fundamental_snapshot_id": (
                        fundamental_record.snapshot_id if fundamental_record else None
                    ),
                    "fundamental_revision_id": (
                        fundamental_record.revision_id if fundamental_record else None
                    ),
                    "risk_flags": [flag.value for flag in stock.risk.flags],
                    "order_generation_status": "NOT_EVALUATED",
                    "order_generation_reason": "",
                    "order_status": None,
                    "order_reject_reason": None,
                    "size_target_fraction": None,
                    "size_unconstrained_kelly": None,
                    "size_applied_caps": None,
                    "size_rejected_reason": None,
                    "forecast_scope": None,
                    "forecast_train_start": None,
                    "forecast_train_end": None,
                    "forecast_win_probability": None,
                    "forecast_average_win_r": None,
                    "forecast_average_loss_r": None,
                    "forecast_sample_size": None,
                    "forecast_out_of_sample": None,
                    "forecast_calibration_error": None,
                    **bar_provenance_records.get(symbol, {}),
                }
                eligibility_reason: str | None = None
                if active_fold is None:
                    eligibility_reason = "NO_ACTIVE_FOLD"
                elif stats.sample_count < self.config.chip.warmup_days:
                    eligibility_reason = "CHIP_WARMUP"
                elif symbol in pending_by_symbol:
                    eligibility_reason = "PENDING_ORDER"
                elif index + 1 >= len(run_dates):
                    eligibility_reason = "NO_NEXT_BAR"

                if eligibility_reason is not None:
                    row["order_generation_status"] = "INELIGIBLE"
                    row["order_generation_reason"] = eligibility_reason
                else:
                    assert active_fold is not None
                    forecast = forecast_cache[active_fold.fold_id][symbol]
                    row.update(
                        {
                            "forecast_scope": "SYMBOL_FOLD_TRAIN_ONLY_5D_PRIOR",
                            "forecast_train_start": forecast_train_start,
                            "forecast_train_end": forecast_train_end,
                            "forecast_win_probability": forecast.win_probability,
                            "forecast_average_win_r": forecast.average_win_r,
                            "forecast_average_loss_r": forecast.average_loss_r,
                            "forecast_sample_size": forecast.sample_size,
                            "forecast_out_of_sample": forecast.out_of_sample,
                            "forecast_calibration_error": forecast.calibration_error,
                        }
                    )
                    new_order = self._make_order(
                        symbol=symbol,
                        bar=bar,
                        next_date=run_dates[index + 1],
                        decision_at=decision_at,
                        decision=decision,
                        stock_reliability=stock.reliability,
                        market_confidence=market.reliability,
                        sector_confidence=sector_sizing_confidence,
                        equity=equity,
                        position_fraction=position_fraction,
                        adv_value=average_amount,
                        forecast=forecast,
                        proposed_stop=proposed_stop,
                        gross_exposure_fraction=gross_exposure_fraction,
                    )
                    order_status = new_order.order_status
                    order_reject_reason = new_order.order_reject_reason
                    if new_order.order is not None:
                        order = new_order.order
                        self.broker.submit(order, rule)
                        submitted_orders += 1
                        order_status = str(order.status.value)
                        order_reject_reason = order.reason
                        self._event(
                            "ORDER_STATE_CHANGED",
                            _order_payload(order),
                            decision_at,
                        )
                        if order.status == OrderStatus.REJECTED:
                            rejected_orders += 1
                        if order.status not in TERMINAL_ORDER_STATES:
                            pending_by_symbol[symbol] = order
                    elif new_order.status not in {"NO_TRADE"}:
                        self._order_generation_failures += 1
                    row.update(
                        {
                            "order_generation_status": new_order.status,
                            "order_generation_reason": new_order.reason,
                            "order_status": order_status,
                            "order_reject_reason": order_reject_reason,
                            "size_target_fraction": new_order.size_target_fraction,
                            "size_unconstrained_kelly": (new_order.size_unconstrained_kelly),
                            "size_applied_caps": new_order.size_applied_caps,
                            "size_rejected_reason": new_order.size_rejected_reason,
                        }
                    )

                gate_accumulator.observe(row)
                # Persist only actionable signals. NO_TRADE is still evaluated
                # in-memory, but ordinary no-action bars do not bloat the
                # audit/report input or masquerade as trade decisions.
                if decision.action.value != "NO_TRADE":
                    decision_buffer.append(decision_encoder.encode(row) + "\n")
                if len(decision_buffer) >= 2_048:
                    decision_chunk = "".join(decision_buffer).encode("utf-8")
                    decision_handle.write(decision_chunk)
                    decision_digest.update(decision_chunk)
                    decision_buffer.clear()

            equity = decision_equity
            pnl = equity - prior_equity
            if pnl >= 0:
                gross_profit += pnl
            else:
                gross_loss += -pnl
            prior_equity = equity
            self._peak_equity = max(self._peak_equity, equity)
            equity_rows.append(
                {
                    "trade_date": trade_date_text,
                    "cash": self.broker.cash,
                    "equity": equity,
                    "gross_exposure": decision_gross_exposure,
                }
            )

        if decision_buffer:
            decision_chunk = "".join(decision_buffer).encode("utf-8")
            decision_handle.write(decision_chunk)
            decision_digest.update(decision_chunk)
        decision_handle.close()
        result = self._finalize(
            plan=plan,
            symbols=symbols,
            decisions_path=decisions_path,
            decisions_sha256=decision_digest.hexdigest(),
            gate_attribution=gate_accumulator.to_dict(),
            equity_rows=equity_rows,
            submitted_orders=submitted_orders,
            blocked_orders=blocked_orders,
            rejected_orders=rejected_orders,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            holdout_tainted=access_final_holdout,
            history_start=history_start,
            evaluation_start=start,
            evaluation_end=end,
            actual_evaluation_start=evaluation_dates[0],
            actual_evaluation_end=evaluation_dates[-1],
            finished_at=datetime.combine(run_dates[-1], time(23, 59), tzinfo=runtime_timezone),
        )
        return result

    def _bars_for_date(
        self, symbols: list[str], trade_date: date, decision_at: datetime
    ) -> dict[str, Bar]:
        result: dict[str, Bar] = {}
        for symbol in symbols:
            bars = self.store.bars_as_of(symbol, trade_date, trade_date, decision_at)
            if bars:
                result[symbol] = bars[-1]
        return result

    def _apply_corporate_actions(
        self,
        symbols: list[str],
        trade_date: date,
        decision_at: datetime,
        pending_by_symbol: dict[str, SimOrder],
        previous_closes: dict[str, float],
    ) -> None:
        grouped = self.store.corporate_actions_for_day(symbols, trade_date, decision_at)
        for symbol, records in grouped.items():
            records.sort(key=lambda action: _corporate_action_priority(action.action_type))
            for action in records:
                if action.action_id in self._processed_actions:
                    continue
                kind = action.action_type.upper()
                action_payload: dict[str, Any] = {
                    "action_id": action.action_id,
                    "symbol": symbol,
                    "action_type": kind,
                    "available_at": action.available_at,
                    "effective_from": action.effective_from,
                    "source": action.source,
                    "snapshot_id": action.snapshot_id,
                    "chip_injection": False,
                }
                if kind in {"SPLIT", "BONUS", "STOCK_DIVIDEND"} and action.ratio:
                    adjustment = self.broker.apply_split(symbol, action.ratio)
                    action_payload.update(asdict(adjustment))
                    if adjustment.approximate and adjustment.quantity_before > 0:
                        self._fractional_split_adjustments += 1
                        self._fractional_split_entitlement_total += (
                            adjustment.fractional_entitlement
                        )
                    if adjustment.unresolved_cost_basis > 0:
                        self._unresolved_split_cost_basis += adjustment.unresolved_cost_basis
                        self._invalid_symbols.add(symbol)
                    if symbol in self._chip_states:
                        self._chip_states[symbol] = apply_split_to_state(
                            self._chip_states[symbol], action.ratio, trade_date
                        )
                    if symbol in self._base_bands:
                        p10, p90, mass = self._base_bands[symbol]
                        self._base_bands[symbol] = (
                            p10 / action.ratio,
                            p90 / action.ratio,
                            mass,
                        )
                    for price_state, state_name in (
                        (previous_closes, "previous_close"),
                        (self._prior_stops, "prior_stop"),
                        (self._latest_prices, "latest_price"),
                    ):
                        if symbol in price_state:
                            before = price_state[symbol]
                            price_state[symbol] = before / action.ratio
                            action_payload[f"{state_name}_before"] = before
                            action_payload[f"{state_name}_after"] = price_state[symbol]
                    pending = pending_by_symbol.get(symbol)
                    if pending is not None:
                        action_payload["pending_order_adjustment"] = asdict(
                            apply_split_to_order(pending, action.ratio)
                        )
                    rebased_plans = self.plans.rebase_active_for_split(
                        symbol, action.ratio, decision_at
                    )
                    action_payload["rebased_plan_versions"] = [
                        {"plan_id": plan.plan_id, "version": plan.version}
                        for plan in rebased_plans
                    ]
                elif kind in {"CASH_DIVIDEND", "DIVIDEND"} and action.cash_per_share is not None:
                    quantity_before = self.broker.position(symbol)
                    cash_amount = self.broker.apply_cash_dividend(symbol, action.cash_per_share)
                    action_payload.update(
                        {
                            "quantity_before": quantity_before,
                            "cash_per_share": action.cash_per_share,
                            "cash_amount": cash_amount,
                        }
                    )
                elif kind in {"RIGHTS", "RIGHTS_ISSUE"}:
                    # Participation is account-specific. Without an explicit
                    # decision ledger the post-event position is unknowable.
                    self._invalid_symbols.add(symbol)
                elif kind not in {"UNLOCK", "LOCKUP_EXPIRY"}:
                    self._invalid_symbols.add(symbol)
                self._processed_actions.add(action.action_id)
                self._event(
                    "CORPORATE_ACTION_APPLIED",
                    {
                        **action_payload,
                        "risk_blocked": symbol in self._invalid_symbols,
                    },
                    decision_at,
                )

    def _update_chip(
        self,
        symbol: str,
        bar: Bar,
        stats: _RollingStats,
        observation: ChipObservation | None = None,
    ) -> ChipFeatures:
        transition = advance_chip_state(
            self._chip_engine,
            self._chip_states.get(symbol),
            bar,
            observation,
            grid_step_pct=self.config.chip.grid_step_pct,
            history_low_2y=stats.history_low_2y,
            history_high_2y=stats.history_high_2y,
            smoothing_sigma=self.config.chip.smoothing_sigma_bins,
            peak_prominence=self.config.chip.peak_prominence,
        )
        self._chip_states[symbol] = transition.state
        if transition.initial_base_band is not None:
            self._base_bands[symbol] = transition.initial_base_band
        if transition.features is None:  # pragma: no cover - requested above
            raise AssertionError("chip features must be present")
        return transition.features

    def _warm_chip(
        self,
        symbol: str,
        bar: Bar,
        observation: ChipObservation | None = None,
    ) -> None:
        """Advance chip state during pre-roll without computing unused features."""
        transition = advance_chip_state(
            self._chip_engine,
            self._chip_states.get(symbol),
            bar,
            observation,
            grid_step_pct=self.config.chip.grid_step_pct,
            with_features=False,
        )
        self._chip_states[symbol] = transition.state
        if transition.initial_base_band is not None:
            self._base_bands[symbol] = transition.initial_base_band

    def _market_state(
        self,
        *,
        return_20_values: list[float],
        volatilities: list[float],
        liquidity_ratios: list[float],
        turnover_zscores: list[float],
        drawdown: float,
        current_count: int,
        active_history_count: int,
    ) -> MarketState:
        trend = fmean(return_20_values) if return_20_values else 0.0
        breadth = sum(value > 0 for value in return_20_values) / max(
            len(return_20_values), 1
        )
        volatility = min(1.0, (fmean(volatilities) if volatilities else 0.0) / 0.04)
        liquidity = min(1.0, (fmean(liquidity_ratios) if liquidity_ratios else 0.0) / 1.2)
        return self.regimes.classify(
            trend=trend,
            breadth=breadth,
            volatility_percentile=volatility,
            liquidity=liquidity,
            drawdown=drawdown,
            turnover_zscore=(fmean(turnover_zscores) if turnover_zscores else 0.0),
            data_quality=current_count / max(active_history_count, 1),
        )

    def _stock_evidence(
        self,
        symbol: str,
        history: list[Bar],
        stats: _RollingStats,
        concentration: float,
        market_breadth: float,
        sector_score: float,
        observation: ChipObservation | PreparedChipRecord | None = None,
        *,
        base_retention: float | None = None,
        chip_hard_valid: bool = True,
        requires_intraday_evidence: bool | None = None,
    ) -> StockEvidence:
        if base_retention is None:
            p10, p90, original = self._base_bands[symbol]
            state = self._chip_states[symbol]
            retained = float(
                state.mass[(state.grid.prices >= p10) & (state.grid.prices <= p90)].sum()
            ) / max(original, 1e-12)
        else:
            retained = base_retention
        control = min(1.0, 0.55 * concentration + 0.45 * retained)
        intraday_complete = observation is not None and observation.intraday_factors_complete
        intraday_confirmation = 0.5
        intraday_conflict = 0.0
        intraday_attention = 0.0
        intraday_volatility = 0.0
        if intraday_complete:
            assert observation is not None
            assert observation.opening_30m_return is not None
            assert observation.closing_30m_return is not None
            assert observation.close_vs_vwap is not None
            assert observation.last_hour_volume_share is not None
            assert observation.realized_volatility is not None
            tail_return = observation.closing_30m_return + observation.close_vs_vwap
            scaled_tail_return = max(-20.0, min(20.0, 40.0 * tail_return))
            tail_direction = 2.0 / (1.0 + exp(-scaled_tail_return)) - 1.0
            tail_participation = min(1.0, observation.last_hour_volume_share / 0.35)
            intraday_confirmation = min(
                1.0,
                max(0.0, 0.5 + 0.5 * tail_direction * (0.5 + 0.5 * tail_participation)),
            )
            trend_conflict = (stats.return_20 > 0.03 and tail_return < 0.0) or (
                stats.return_20 < -0.03 and tail_return > 0.0
            )
            opening_failure = (
                observation.opening_30m_return > 0.0
                and observation.closing_30m_return < 0.0
                and observation.close_vs_vwap < 0.0
            )
            conflict_magnitude = min(1.0, abs(tail_return) / 0.025)
            intraday_conflict = (
                conflict_magnitude * (0.5 + 0.5 * tail_participation)
                if trend_conflict or opening_failure
                else 0.0
            )
            intraday_volatility = min(1.0, observation.realized_volatility / 0.03)
            intraday_attention = min(
                1.0,
                0.65 * tail_participation + 0.35 * intraday_volatility,
            )
        evidence_quality = 0.0 if symbol in self._invalid_symbols or not chip_hard_valid else 0.95
        if requires_intraday_evidence is None:
            requires_intraday_evidence = self.store.requires_intraday_evidence
        if requires_intraday_evidence and not intraday_complete:
            evidence_quality = 0.0
        daily_failed_breakout = (
            stats.sample_count > 20
            and history[-1].high > stats.previous_high
            and history[-1].close < stats.previous_high
        )
        return StockEvidence(
            return_5=stats.return_5,
            return_20=stats.return_20,
            return_60=stats.return_60,
            drawdown_20=history[-1].close / stats.high_20 - 1.0,
            volatility_percentile=max(min(1.0, stats.volatility / 0.04), intraday_volatility),
            turnover_zscore=stats.turnover_zscore,
            volume_contraction=min(1.0, stats.volume_contraction),
            relative_strength_percentile=min(
                1.0,
                max(0.0, 0.5 + 4.0 * stats.return_20),
            ),
            base_retention=min(1.0, retained),
            valley_fill=min(1.0, max(0.0, concentration - 0.35)),
            distance_from_120d_low=(history[-1].close - stats.low_120) / max(stats.low_120, 1e-12),
            control_score=control,
            prior_control_score=min(1.0, self._prior_controls.get(symbol, control)),
            market_breadth=market_breadth,
            sector_score=sector_score,
            group_oversold=max(0.0, 0.35 - market_breadth) / 0.35,
            new_high=history[-1].close >= stats.previous_high,
            failed_breakout=daily_failed_breakout
            or (
                (history[-1].close >= stats.previous_high or stats.return_5 > 0.02)
                and intraday_conflict >= 0.60
            ),
            rebound_from_low=(history[-1].close / max(stats.low_120, 1e-12) - 1.0),
            intraday_confirmation=intraday_confirmation,
            intraday_conflict=intraday_conflict,
            intraday_attention=intraday_attention,
            data_quality=evidence_quality,
        )

    def _make_order(
        self,
        *,
        symbol: str,
        bar: Bar,
        next_date: date,
        decision_at: datetime,
        decision: GameDecision,
        stock_reliability: float,
        market_confidence: float,
        sector_confidence: float,
        equity: float,
        position_fraction: float,
        adv_value: float,
        forecast: CalibratedForecast,
        proposed_stop: float,
        gross_exposure_fraction: float,
    ) -> OrderGenerationResult:
        position = self.broker.position(symbol)
        side: OrderSide
        quantity: int
        target_fraction = position_fraction
        max_participation = self.config.portfolio.adv_participation_cap
        if decision.action in {Action.BUY, Action.ADD}:
            card = decision.edge_card
            if card is None:
                return OrderGenerationResult(
                    status="SIZE_REJECTED",
                    reason="MISSING_EDGE_CARD",
                    size_rejected_reason="MISSING_EDGE_CARD",
                )
            drawdown = self._portfolio_drawdown(equity)
            size = fractional_kelly_size(
                forecast,
                PortfolioConstraints(
                    equity=equity,
                    cash=self.broker.cash,
                    current_name_fraction=position_fraction,
                    current_sector_fraction=gross_exposure_fraction,
                    current_theme_fraction=position_fraction,
                    adv_value=adv_value,
                    edge_capacity_fraction_adv=card.capacity_fraction_adv,
                    drawdown=drawdown,
                    reliability=stock_reliability,
                    observability=decision.observability,
                    execution_probability=0.98,
                    market_confidence=market_confidence,
                    sector_confidence=sector_confidence,
                ),
                self.config.portfolio,
            )
            if size.rejected_reason is not None:
                if size.rejected_reason == "NON_POSITIVE_KELLY":
                    return OrderGenerationResult(
                        status="NO_TRADE",
                        reason="KELLY_NO_EDGE",
                        size_target_fraction=size.target_fraction,
                        size_unconstrained_kelly=size.unconstrained_kelly,
                        size_applied_caps=size.applied_caps,
                        size_rejected_reason=size.rejected_reason,
                    )
                return OrderGenerationResult(
                    status="SIZE_REJECTED",
                    reason="SIZE_FILTERED",
                    size_target_fraction=size.target_fraction,
                    size_unconstrained_kelly=size.unconstrained_kelly,
                    size_applied_caps=size.applied_caps,
                    size_rejected_reason=size.rejected_reason,
                )
            quantity = _lot_quantity(
                size.incremental_value,
                bar.close,
                self.config.execution.lot_size,
            )
            if quantity <= 0:
                return OrderGenerationResult(
                    status="NO_TRADE",
                    reason=(
                        "PORTFOLIO_CAP_NO_INCREMENT"
                        if size.incremental_value <= 0.0
                        else "BELOW_MINIMUM_EXECUTABLE_LOT"
                    ),
                    size_target_fraction=size.target_fraction,
                    size_unconstrained_kelly=size.unconstrained_kelly,
                    size_applied_caps=size.applied_caps,
                    size_rejected_reason=(
                        "NO_INCREMENTAL_CAPACITY"
                        if size.incremental_value <= 0.0
                        else "LOT_ROUNDING_ZERO"
                    ),
                )
            side = OrderSide.BUY
            target_fraction = size.target_fraction
            max_participation = min(max_participation, card.capacity_fraction_adv)
        elif decision.action in {Action.REDUCE, Action.EXIT} and position > 0:
            side = OrderSide.SELL
            requested = position if decision.action == Action.EXIT else position // 2
            quantity = (
                requested
                if decision.action == Action.EXIT
                else floor(requested / self.config.execution.lot_size)
                * self.config.execution.lot_size
            )
            if quantity <= 0:
                return OrderGenerationResult(
                    status="NO_TRADE",
                    reason="BELOW_MINIMUM_EXECUTABLE_LOT",
                    size_rejected_reason="LOT_ROUNDING_ZERO",
                )
            target_fraction = 0.0 if decision.action == Action.EXIT else position_fraction / 2.0
        else:
            return OrderGenerationResult(status="NO_TRADE", reason="NO_ACTION")

        card = decision.edge_card
        digest_source = asdict(card) if card is not None else {"action": decision.action.value}
        edge_digest = hashlib.sha256(
            json.dumps(digest_source, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        plan_key = f"{self.run_id}|plan|{symbol}|{decision_at.isoformat()}"
        plan_id = str(uuid5(NAMESPACE_URL, plan_key))
        plan = TradingPlan.create(
            symbol=symbol,
            family=decision.family,
            action=decision.action,
            now=decision_at,
            expires_at=decision_at + timedelta(days=14),
            entry_trigger="signal t close confirmed; execute no earlier than next trading bar",
            invalidation=(card.invalidation if card is not None else "independent risk exit"),
            protective_stop=proposed_stop,
            target_fraction=target_fraction,
            max_participation=max_participation,
            edge_card_digest=edge_digest,
            plan_id=plan_id,
        )
        self.plans.append(plan, decision_at)
        validated = replace(
            plan,
            version=2,
            parent_version=1,
            status=PlanStatus.VALIDATED,
        )
        self.plans.append(validated, decision_at)
        active = replace(
            validated,
            version=3,
            parent_version=2,
            status=PlanStatus.ACTIVE,
        )
        self.plans.append(active, decision_at)
        self._prior_stops[symbol] = proposed_stop
        order_id = str(uuid5(NAMESPACE_URL, f"{self.run_id}|order|{plan_id}"))
        return OrderGenerationResult(
            status="ORDER_CREATED",
            reason="",
            order=SimOrder(
                symbol=symbol,
                side=side,
                quantity=quantity,
                signal_time=decision_at,
                earliest_fill_date=next_date,
                max_participation=max_participation,
                plan_id=plan_id,
                order_id=order_id,
            ),
            order_status=OrderStatus.CREATED.value,
            size_target_fraction=target_fraction,
            size_unconstrained_kelly=size.unconstrained_kelly
            if decision.action in {Action.BUY, Action.ADD}
            else None,
            size_applied_caps=size.applied_caps
            if decision.action in {Action.BUY, Action.ADD}
            else None,
        )

    def _portfolio_drawdown(self, equity: float) -> float:
        return max(0.0, 1.0 - equity / max(self._peak_equity, 1e-12))

    def _gross_exposure(self) -> float:
        return sum(
            self.broker.position(symbol) * self._latest_prices.get(symbol, 0.0)
            for symbol in self.broker.lots
        )

    def _equity(self, latest_prices: dict[str, float]) -> float:
        return self.broker.cash + sum(
            self.broker.position(symbol) * latest_prices.get(symbol, 0.0)
            for symbol in self.broker.lots
        )

    def _finalize(
        self,
        *,
        plan: WalkForwardPlan,
        symbols: list[str],
        decisions_path: Path,
        decisions_sha256: str,
        gate_attribution: dict[str, Any],
        equity_rows: list[dict[str, Any]],
        submitted_orders: int,
        blocked_orders: int,
        rejected_orders: int,
        gross_profit: float,
        gross_loss: float,
        holdout_tainted: bool,
        history_start: date,
        evaluation_start: date,
        evaluation_end: date,
        actual_evaluation_start: date,
        actual_evaluation_end: date,
        finished_at: datetime,
    ) -> BacktestResult:
        total_cost = sum(
            fill.commission + fill.stamp_duty + fill.slippage + fill.impact
            for fill in self.broker.fills
        )
        metrics = performance_metrics(
            [float(row["equity"]) for row in equity_rows],
            fills=len(self.broker.fills),
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            total_cost=total_cost,
            blocked_orders=blocked_orders,
            submitted_orders=submitted_orders,
            rejected_orders=rejected_orders,
            order_generation_rejections=self._order_generation_failures,
        )
        metrics["plan_adherence"] = 1.0
        metrics["submitted_orders"] = submitted_orders
        metrics["rejected_orders"] = rejected_orders
        summary: dict[str, Any] = {
            "run_id": self.run_id,
            "status": "COMPLETE",
            "symbols": symbols,
            "metrics": metrics,
            "holdout_tainted": holdout_tainted,
            "final_holdout_accessed": holdout_tainted,
            "history_start": history_start.isoformat(),
            "evaluation_start": evaluation_start.isoformat(),
            "evaluation_end": evaluation_end.isoformat(),
            "actual_evaluation_start": actual_evaluation_start.isoformat(),
            "actual_evaluation_end": actual_evaluation_end.isoformat(),
            "final_holdout_dates": [item.isoformat() for item in plan.final_holdout_dates],
            "corporate_action_approximations": {
                "fractional_split_count": self._fractional_split_adjustments,
                "fractional_entitlement_total": self._fractional_split_entitlement_total,
                "unresolved_cost_basis": self._unresolved_split_cost_basis,
                "method": "ACCOUNT_FLOOR_LARGEST_REMAINDER_NO_CASH_IN_LIEU",
            },
            "event_count_before_final_state": self.events.count(),
        }
        positions = {symbol: self.broker.position(symbol) for symbol in symbols}
        available_quantities = {
            symbol: self.broker.sellable(
                symbol,
                finished_at.date(),
                self.store.rule_as_of(
                    symbol,
                    _board(symbol),
                    finished_at.date(),
                    finished_at,
                ),
            )
            for symbol in symbols
        }
        self._event("STATE_SET", {"key": "summary", "value": summary}, finished_at)
        self._event(
            "STATE_SET",
            {"key": "final_positions", "value": positions},
            finished_at,
        )
        self._event(
            "STATE_SET",
            {"key": "final_cash", "value": self.broker.cash},
            finished_at,
        )
        self._event(
            "STATE_SET",
            {"key": "final_available_quantities", "value": available_quantities},
            finished_at,
        )
        digest = self.events.digest()
        summary_with_digest = {**summary, "event_digest": digest}

        equity_path = self.run_dir / "equity.csv"
        with equity_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["trade_date", "cash", "equity", "gross_exposure"],
            )
            writer.writeheader()
            writer.writerows(equity_rows)
        walk_path = self.run_dir / "walk_forward.json"
        walk_path.write_text(
            json.dumps(_walk_forward_payload(plan), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        summary_path = self.run_dir / "summary.json"
        summary_path.write_text(
            json.dumps(summary_with_digest, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        diagnostics = build_research_diagnostics(
            equity=[float(row["equity"]) for row in equity_rows],
            fills=self.broker.fills,
            gate_attribution=gate_attribution,
            total_cost=total_cost,
            participation_cap=self.config.portfolio.adv_participation_cap,
        )
        diagnostics_path = self.run_dir / "research_diagnostics.json"
        diagnostics_path.write_text(
            json.dumps(diagnostics, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        for symbol, state in self._chip_states.items():
            self.store.save_state(
                kind="chip",
                symbol=symbol,
                as_of=finished_at,
                payload={
                    "engine": state.engine,
                    "quality": state.quality,
                    "mass_sum": float(state.mass.sum()),
                    "average_cost": state.average_cost,
                },
                version=1,
                run_id=self.run_id,
            )
        manifest = {
            "run_id": self.run_id,
            "data_authorization": {
                "operation": self.data_authorization.operation.value,
                "purpose": self.data_authorization.purpose.value,
                "software_test": self.data_authorization.software_test,
                "registry_id": self.data_authorization.registry_id,
                "registry_sha256": self.data_authorization.registry_sha256,
                "input_manifest_id": self.data_authorization.input_manifest_id,
                "input_manifest_sha256": self.data_authorization.input_manifest_sha256,
                "scope_start": self.data_authorization.scope_start.isoformat(),
                "scope_end": self.data_authorization.scope_end.isoformat(),
            },
            "config_sha256": hashlib.sha256(self.config_text.encode()).hexdigest(),
            "pit_store_sha256": self.store.source_digest(),
            "event_digest": digest,
            "date_ranges": {
                "history_start": history_start.isoformat(),
                "evaluation_start": evaluation_start.isoformat(),
                "evaluation_end": evaluation_end.isoformat(),
                "actual_evaluation_start": actual_evaluation_start.isoformat(),
                "actual_evaluation_end": actual_evaluation_end.isoformat(),
            },
            "artifacts": {
                path.name: (decisions_sha256 if path == decisions_path else _file_digest(path))
                for path in (
                    equity_path,
                    decisions_path,
                    walk_path,
                    summary_path,
                    diagnostics_path,
                )
            },
        }
        (self.run_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        return BacktestResult(
            run_id=self.run_id,
            run_dir=self.run_dir,
            summary_path=summary_path,
            event_path=self.events.path,
            event_digest=digest,
            metrics=metrics,
            holdout_tainted=holdout_tainted,
        )

    def _event(self, event_type: str, payload: dict[str, Any], at: datetime) -> None:
        self.events.append(
            event_type,
            _jsonable(payload),
            run_id=self.run_id,
            occurred_at=at,
        )


def _decision_context(
    *,
    symbol: str,
    at: datetime,
    data_quality: float,
    observability: float,
    execution_probability: float,
    market_confidence: float,
    sector_confidence: float,
    disagreement: float,
) -> DecisionContext:
    return DecisionContext(
        symbol=symbol,
        decision_at=at,
        data_quality=min(1.0, max(0.0, data_quality)),
        observability=min(1.0, max(0.0, observability)),
        execution_probability=min(1.0, max(0.0, execution_probability)),
        market_confidence=min(1.0, max(0.0, market_confidence)),
        sector_confidence=min(1.0, max(0.0, sector_confidence)),
        model_disagreement=min(1.0, max(0.0, disagreement)),
    )


def _calibrate_forecast(
    histories: dict[str, list[Bar]], train_dates: set[date]
) -> CalibratedForecast:
    outcomes: list[float] = []
    for history in histories.values():
        selected = [bar for bar in history if bar.trade_date in train_dates]
        for index in range(len(selected) - 5):
            outcomes.append((selected[index + 5].close / selected[index].close - 1.0) / 0.05)
    wins = [value for value in outcomes if value > 0]
    losses = [-value for value in outcomes if value < 0]
    if not wins or not losses:
        return CalibratedForecast(0.5, 1.0, 1.0, len(outcomes), True, 0.20)
    probability = min(0.99, max(0.01, len(wins) / len(outcomes)))
    return CalibratedForecast(
        win_probability=probability,
        average_win_r=max(0.05, fmean(wins)),
        average_loss_r=max(0.05, fmean(losses)),
        sample_size=len(outcomes),
        out_of_sample=True,
        calibration_error=min(0.20, abs(probability - 0.5) * 0.25),
    )


def _holdout_fold(plan: WalkForwardPlan) -> WalkForwardFold:
    return WalkForwardFold(
        fold_id=10_000,
        train_dates=plan.development_dates,
        purge_dates=(),
        test_dates=plan.final_holdout_dates,
        embargo_dates=(),
    )


def _period_return(history: list[Bar], periods: int) -> float:
    if len(history) <= periods:
        return 0.0
    return history[-1].close / history[-periods - 1].close - 1.0


def _rolling_stats(history: list[Bar]) -> _RollingStats:
    if not history:
        raise ValueError("rolling statistics require non-empty history")
    recent_120 = history[-120:]
    recent_20 = history[-20:]
    recent_504 = history[-504:]
    previous_window = history[-21:-1]
    return _RollingStats(
        sample_count=len(history),
        return_5=_period_return(history, 5),
        return_20=_period_return(history, 20),
        return_60=_period_return(history, 60),
        volatility=_rolling_vol(history),
        turnover_zscore=_turnover_zscore(history),
        average_amount=_average_amount(history),
        volume_contraction=_volume_contraction(history),
        low_120=min(bar.close for bar in recent_120),
        high_20=max(bar.close for bar in recent_20),
        previous_high=max(
            (bar.close for bar in previous_window),
            default=history[-1].close,
        ),
        history_low_2y=min(bar.low for bar in recent_504),
        history_high_2y=max(bar.high for bar in recent_504),
    )


def _rolling_vol(history: list[Bar]) -> float:
    closes = [bar.close for bar in history[-21:]]
    returns = [closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes))]
    return pstdev(returns) if len(returns) >= 2 else 0.0


def _turnover_zscore(history: list[Bar]) -> float:
    values = [bar.turnover for bar in history[-60:]]
    if len(values) < 3:
        return 0.0
    deviation = pstdev(values)
    return (values[-1] - fmean(values)) / deviation if deviation > 1e-12 else 0.0


def _average_amount(history: list[Bar]) -> float:
    return fmean(bar.amount for bar in history[-20:]) if history else 0.0


def _volume_contraction(history: list[Bar]) -> float:
    if len(history) < 10:
        return 0.0
    recent = fmean(bar.volume for bar in history[-5:])
    baseline = fmean(bar.volume for bar in history[-20:])
    return max(0.0, 1.0 - recent / max(baseline, 1e-12))


def _execution_probability(bar: Bar, known_rule: bool) -> float:
    if not known_rule or bar.suspended or bar.amount <= 0:
        return 0.0
    if bar.limit_up is not None and bar.low >= bar.limit_up - 1e-10:
        return 0.35
    if bar.limit_down is not None and bar.high <= bar.limit_down + 1e-10:
        return 0.35
    return 0.98


def _lot_quantity(value: float, price: float, lot_size: int) -> int:
    return floor(value / max(price, 1e-12) / lot_size) * lot_size


def _corporate_action_priority(action_type: str) -> int:
    kind = action_type.upper()
    if kind in {"CASH_DIVIDEND", "DIVIDEND"}:
        return 0
    if kind in {"SPLIT", "BONUS", "STOCK_DIVIDEND"}:
        return 1
    if kind in {"UNLOCK", "LOCKUP_EXPIRY"}:
        return 2
    if kind in {"RIGHTS", "RIGHTS_ISSUE"}:
        return 3
    return 4


def _board(symbol: str) -> str:
    code = symbol.split(".", 1)[0]
    if code.startswith(("300", "301")):
        return "CHINEXT"
    if code.startswith(("688", "689")):
        return "STAR"
    if code.startswith(("8", "4")):
        return "BSE"
    return "MAIN"


def _order_payload(order: SimOrder) -> dict[str, Any]:
    return {
        "order_id": order.order_id,
        "symbol": order.symbol,
        "side": order.side.value,
        "quantity": order.quantity,
        "filled_quantity": order.filled_quantity,
        "status": order.status.value,
        "reason": order.reason,
        "plan_id": order.plan_id,
        "earliest_fill_date": order.earliest_fill_date.isoformat(),
    }


def _walk_forward_payload(plan: WalkForwardPlan) -> dict[str, Any]:
    return {
        "purge_days": plan.purge_days,
        "embargo_days": plan.embargo_days,
        "development_dates": [item.isoformat() for item in plan.development_dates],
        "final_holdout_dates": [item.isoformat() for item in plan.final_holdout_dates],
        "folds": [
            {
                "fold_id": fold.fold_id,
                "train_dates": [item.isoformat() for item in fold.train_dates],
                "purge_dates": [item.isoformat() for item in fold.purge_dates],
                "test_dates": [item.isoformat() for item in fold.test_dates],
                "embargo_dates": [item.isoformat() for item in fold.embargo_dates],
            }
            for fold in plan.folds
        ],
    }


def _finite(value: float | None) -> float | str | None:
    if value is None:
        return None
    if value == float("inf"):
        return "Infinity"
    if value == float("-inf"):
        return "-Infinity"
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return value


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
