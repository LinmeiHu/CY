"""Falsifiable game-theory decision layer.

Participant identities are hypotheses expressed as probabilities.  They are not
claims that a named institution owns a particular cost band.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import exp, log, sqrt

from cyq_game.config import DecisionConfig, ExecutionConfig
from cyq_game.domain import Action, DecisionContext, StrategyFamily
from cyq_game.state import MarketState, StockState


def _clip(value: float) -> float:
    return min(1.0, max(0.0, value))


def _softmax(raw: dict[ParticipantKind, float]) -> dict[ParticipantKind, float]:
    peak = max(raw.values())
    weights = {kind: exp(value - peak) for kind, value in raw.items()}
    total = sum(weights.values())
    return {kind: value / total for kind, value in weights.items()}


class ParticipantKind(StrEnum):
    CONCENTRATED_STICKY = "concentrated_sticky"
    PASSIVE_INDEX = "passive_index"
    FUNDAMENTAL_LONG = "fundamental_long"
    SHORT_TREND = "short_trend"
    PANIC_FORCED_SELLER = "panic_forced_seller"
    EVENT_CAPITAL = "event_capital"
    ARB_LIQUIDITY = "arbitrage_liquidity"
    ATTENTION_RETAIL = "attention_retail"


@dataclass(frozen=True)
class ParticipantEcology:
    probabilities: dict[ParticipantKind, float]
    observability: float
    entropy: float
    alternative_mass: float
    explanations: tuple[str, ...]

    @property
    def primary(self) -> ParticipantKind:
        return max(self.probabilities, key=self.probabilities.__getitem__)


def infer_participants(
    stock: StockState,
    *,
    fundamental_score: float | None = 0.5,
    passive_flow: float = 0.0,
    event_intensity: float = 0.0,
    attention: float = 0.0,
    liquidity_supply: float = 0.5,
    model_disagreement: float = 0.0,
    hidden_event_risk: float = 0.0,
    data_quality: float = 1.0,
) -> ParticipantEcology:
    ev = stock.evidence
    control = float(ev.get("control", 0.5))
    locked = float(ev.get("locked", 0.5))
    trend = float(ev.get("trend", 0.5))
    oversold = float(ev.get("oversold", 0.0))
    distribution = float(ev.get("distribution", 0.0))
    raw: dict[ParticipantKind, float] = {
        ParticipantKind.CONCENTRATED_STICKY: 2.0 * control + 1.5 * locked,
        ParticipantKind.PASSIVE_INDEX: 1.0 + 3.0 * _clip(passive_flow),
        ParticipantKind.SHORT_TREND: 0.5 + 2.5 * trend + distribution,
        ParticipantKind.PANIC_FORCED_SELLER: 0.3 + 3.5 * oversold,
        ParticipantKind.EVENT_CAPITAL: 0.5 + 3.0 * _clip(event_intensity),
        ParticipantKind.ARB_LIQUIDITY: 0.8 + 2.0 * _clip(liquidity_supply),
        ParticipantKind.ATTENTION_RETAIL: 0.6 + 3.0 * _clip(attention),
    }
    if fundamental_score is not None:
        raw[ParticipantKind.FUNDAMENTAL_LONG] = 0.8 + 3.0 * _clip(fundamental_score)
    probabilities = _softmax(raw)
    count = len(probabilities)
    entropy = -sum(p * log(max(p, 1e-12)) for p in probabilities.values()) / log(count)
    ordered = sorted(probabilities.values(), reverse=True)
    alternative_mass = sum(ordered[1:3])
    penalty = (
        0.30 * entropy
        + 0.15 * alternative_mass
        + 0.20 * _clip(model_disagreement)
        + 0.15 * _clip(hidden_event_risk)
    )
    # Quality is an upper bound.  Improving data quality cannot conceal ambiguity.
    observability = min(_clip(data_quality), _clip(1.0 - penalty))
    primary = max(probabilities, key=probabilities.__getitem__)
    explanations = (
        f"primary_hypothesis={primary.value}:{probabilities[primary]:.3f}",
        f"normalized_entropy={entropy:.3f}",
        f"alternative_mass={alternative_mass:.3f}",
    )
    return ParticipantEcology(
        probabilities=probabilities,
        observability=observability,
        entropy=entropy,
        alternative_mass=alternative_mass,
        explanations=explanations,
    )


@dataclass(frozen=True)
class EdgeCard:
    edge_source: str
    counterparty_state: str
    why_they_act_now: str
    why_edge_persists: str
    expected_payoff_r: float
    capacity_fraction_adv: float
    adversarial_response: str
    expiry_rule: str
    invalidation: str
    falsifiable_explanations: tuple[str, ...]
    evidence_for: tuple[str, ...]
    evidence_against: tuple[str, ...]
    crowding: float = 0.0

    def missing_fields(self) -> tuple[str, ...]:
        missing: list[str] = []
        scalar_text = (
            "edge_source",
            "counterparty_state",
            "why_they_act_now",
            "why_edge_persists",
            "adversarial_response",
            "expiry_rule",
            "invalidation",
        )
        for name in scalar_text:
            if not str(getattr(self, name)).strip():
                missing.append(name)
        if self.expected_payoff_r <= 0:
            missing.append("expected_payoff_r")
        if self.capacity_fraction_adv <= 0:
            missing.append("capacity_fraction_adv")
        for name in ("falsifiable_explanations", "evidence_for", "evidence_against"):
            if not getattr(self, name):
                missing.append(name)
        return tuple(missing)

    @property
    def complete(self) -> bool:
        return not self.missing_fields()


def route_strategy(
    stock: StockState, fundamental_score: float | None
) -> StrategyFamily:
    code = stock.primary.value
    if code in {"T0", "T1", "T2", "T3", "T7"}:
        return StrategyFamily.ACCUMULATION_TREND
    if code == "T6":
        return StrategyFamily.PANIC_REVERSAL
    if code == "T5":
        return StrategyFamily.CAPITAL_SELF_RESCUE
    if code == "T4":
        return StrategyFamily.LEADER_FORMATION
    if fundamental_score is not None and fundamental_score >= 0.72:
        return StrategyFamily.VALUE_DISCOVERY
    return StrategyFamily.CASH_DEFENSE


def build_edge_card(
    stock: StockState,
    ecology: ParticipantEcology,
    *,
    fundamental_score: float | None = 0.5,
) -> tuple[StrategyFamily, EdgeCard | None]:
    """Build an evidence-backed card; return None when no testable edge exists."""

    family = route_strategy(stock, fundamental_score)
    if family == StrategyFamily.CASH_DEFENSE:
        return family, None
    primary = ecology.primary.value
    score = stock.score(stock.primary)
    evidence_for = tuple(stock.explanations[:2]) + ecology.explanations[:1]
    evidence_against = tuple(stock.risk.reasons) or (
        "尚未观察到独立风险信号，但这不证明风险不存在",
    )
    if family == StrategyFamily.ACCUMULATION_TREND:
        source = "筹码集中/底仓留存与价格确认之间的时序差"
        action_now = "潜在集中持有者需在有效突破前后维持成本区稳定"
        persistence = "成本迁移缓慢，只有后续换手和价格确认才会消除该差异"
    elif family == StrategyFamily.PANIC_REVERSAL:
        source = "强制/恐慌卖方的非价格敏感供给"
        action_now = "回撤、亏损筹码与群体超卖同时抬高即时卖出压力"
        persistence = "流动性约束通常跨越多个交易时段，而非单笔成交结束"
    elif family == StrategyFamily.CAPITAL_SELF_RESCUE:
        source = "受伤资本降低退出损失的自救激励"
        action_now = "深回撤后出现放量反弹，存量资本有维护可交易价格的动机"
        persistence = "套牢成本区在充分换手前仍约束供需"
    elif family == StrategyFamily.LEADER_FORMATION:
        source = "弱市相对强度与注意力再分配"
        action_now = "市场宽度偏弱时，资金更集中于少数可交易领导者"
        persistence = "相对强度和流动性反馈可延续，但拥挤会侵蚀收益"
    else:
        source = "基本面已披露信息与筹码定价的暂时偏离"
        action_now = "盈利修正或估值重估使长周期资金重新平衡"
        persistence = "财务信息扩散与机构调仓均需时间"
    card = EdgeCard(
        edge_source=source,
        counterparty_state=f"主要参与者假设={primary}，并保留全部替代解释",
        why_they_act_now=action_now,
        why_edge_persists=persistence,
        expected_payoff_r=0.75 + 1.75 * score,
        capacity_fraction_adv=max(0.005, 0.05 * (1.0 - ecology.alternative_mass)),
        adversarial_response="对手可提前成交、制造假突破或在限制价附近撤出流动性",
        expiry_rule="10 个交易日内未出现预期成本迁移或价格确认则到期",
        invalidation="主成本区失守且底仓留存下降，或独立风险层触发硬无效",
        falsifiable_explanations=(
            "筹码集中来自被动指数或数据口径变化，而非主动吸筹",
            "价格确认仅由短期注意力驱动，缺少持续承接",
        ),
        evidence_for=evidence_for,
        evidence_against=evidence_against,
        crowding=float(stock.evidence.get("distribution", 0.0)),
    )
    return family, card


class ScenarioKind(StrEnum):
    A_CONTINUATION = "A_CONTINUATION"
    B_RETEST = "B_RETEST"
    C_FALSE_BREAKOUT = "C_FALSE_BREAKOUT"
    D_DISTRIBUTION = "D_DISTRIBUTION"
    E_EXTERNAL_DETERIORATION = "E_EXTERNAL_DETERIORATION"
    F_EXECUTION_BLOCKED = "F_EXECUTION_BLOCKED"


@dataclass(frozen=True)
class Scenario:
    kind: ScenarioKind
    probability: float
    return_r: float
    tail_loss_r: float
    execution_probability: float
    evidence: tuple[str, ...]


def build_scenarios(
    stock: StockState,
    market: MarketState,
    context: DecisionContext,
    card: EdgeCard,
) -> tuple[Scenario, ...]:
    trend_support = _clip(
        0.5 * float(stock.evidence.get("trend", 0.5))
        + 0.5 * market.breadth
    )
    distribution = float(stock.evidence.get("distribution", 0.0))
    volatility = market.volatility_percentile
    execution_block = 1.0 - context.execution_probability
    raw = {
        ScenarioKind.A_CONTINUATION: 0.24 + 0.28 * trend_support,
        ScenarioKind.B_RETEST: 0.18 + 0.12 * (1.0 - trend_support),
        ScenarioKind.C_FALSE_BREAKOUT: 0.09 + 0.20 * distribution,
        ScenarioKind.D_DISTRIBUTION: 0.07 + 0.26 * distribution,
        ScenarioKind.E_EXTERNAL_DETERIORATION: 0.06 + 0.12 * volatility,
        ScenarioKind.F_EXECUTION_BLOCKED: 0.02 + 0.35 * execution_block,
    }
    total = sum(raw.values())
    probability = {kind: value / total for kind, value in raw.items()}
    returns = {
        ScenarioKind.A_CONTINUATION: card.expected_payoff_r,
        ScenarioKind.B_RETEST: 0.25 * card.expected_payoff_r,
        ScenarioKind.C_FALSE_BREAKOUT: -0.85,
        ScenarioKind.D_DISTRIBUTION: -1.20,
        ScenarioKind.E_EXTERNAL_DETERIORATION: -1.50,
        ScenarioKind.F_EXECUTION_BLOCKED: -1.80,
    }
    tails = {
        ScenarioKind.A_CONTINUATION: 0.01,
        ScenarioKind.B_RETEST: 0.03,
        ScenarioKind.C_FALSE_BREAKOUT: 0.10,
        ScenarioKind.D_DISTRIBUTION: 0.18,
        ScenarioKind.E_EXTERNAL_DETERIORATION: 0.30,
        ScenarioKind.F_EXECUTION_BLOCKED: 0.45,
    }
    scenarios = tuple(
        Scenario(
            kind=kind,
            probability=probability[kind],
            return_r=returns[kind],
            tail_loss_r=tails[kind] + 0.05 * stock.risk.tail_loss_r,
            execution_probability=(
                context.execution_probability
                if kind != ScenarioKind.F_EXECUTION_BLOCKED
                else max(0.0, context.execution_probability - 0.5)
            ),
            evidence=(f"market={market.phase.value}", f"stock={stock.primary.value}"),
        )
        for kind in ScenarioKind
    )
    if abs(sum(item.probability for item in scenarios) - 1.0) > 1e-12:
        raise AssertionError("scenario probabilities must sum to one")
    return scenarios


@dataclass(frozen=True)
class GameDecision:
    action: Action
    family: StrategyFamily
    q_values: dict[Action, float]
    raw_edge_r: float
    adjusted_edge_r: float
    observability: float
    scenario_probabilities: dict[ScenarioKind, float]
    gates: tuple[str, ...]
    edge_card: EdgeCard | None


class DecisionEngine:
    def __init__(self, decision: DecisionConfig, execution: ExecutionConfig) -> None:
        self.decision = decision
        self.execution = execution

    def decide(
        self,
        *,
        stock: StockState,
        market: MarketState,
        context: DecisionContext,
        ecology: ParticipantEcology,
        edge_card: EdgeCard | None,
        family: StrategyFamily,
        scenarios: tuple[Scenario, ...],
        price: float,
        order_value: float,
        adv_value: float,
        position_fraction: float = 0.0,
        posterior_improved: bool = False,
        prior_protective_stop: float | None = None,
        proposed_protective_stop: float | None = None,
    ) -> GameDecision:
        gates: list[str] = []
        if edge_card is None:
            gates.append("EDGE_CARD_MISSING")
        elif not edge_card.complete:
            gates.append("EDGE_CARD_INCOMPLETE:" + ",".join(edge_card.missing_fields()))
        if context.data_quality < self.decision.observability_min:
            gates.append("DATA_QUALITY_BELOW_GATE")
        observability = min(context.observability, ecology.observability)
        if observability < self.decision.observability_min:
            gates.append("OBSERVABILITY_BELOW_GATE")
        if context.execution_probability < self.decision.execution_probability_min:
            gates.append("EXECUTION_PROBABILITY_BELOW_GATE")
        if stock.risk.blocks_new_risk:
            gates.append("INDEPENDENT_RISK_OVERRIDE")
        if family == StrategyFamily.CASH_DEFENSE:
            gates.append("CASH_DEFENSE")
        if edge_card is None or not scenarios:
            return self._no_trade(family, gates, edge_card, observability)

        participation = order_value / max(adv_value, 1e-9)
        explicit_cost_r = (
            (self.execution.commission_bps + self.execution.slippage_bps) / 10_000.0
        ) / max(price * 0.05 / price, 1e-6)
        impact_r = self.execution.impact_coefficient * sqrt(max(0.0, participation))
        reflexivity_r = 0.35 * edge_card.crowding
        raw_edge_r = sum(item.probability * item.return_r for item in scenarios)
        adjusted_edge_r = raw_edge_r - explicit_cost_r - impact_r - reflexivity_r

        action_scale = {
            Action.BUY: 1.00 if position_fraction <= 0 else 0.00,
            Action.ADD: 0.70 if position_fraction > 0 else 0.00,
            Action.HOLD: 0.45 if position_fraction > 0 else 0.00,
            Action.REDUCE: -0.20 if position_fraction > 0 else 0.00,
            Action.EXIT: -0.45 if position_fraction > 0 else 0.00,
            Action.NO_TRADE: 0.00,
        }
        q_values: dict[Action, float] = {}
        for action, scale in action_scale.items():
            if action == Action.NO_TRADE:
                q_values[action] = 0.0
                continue
            action_explicit_cost_r = explicit_cost_r
            if action in {Action.REDUCE, Action.EXIT}:
                action_explicit_cost_r += (
                    self.execution.stamp_duty_sell_bps / 10_000.0
                ) / max(price * 0.05 / price, 1e-6)
            q_values[action] = sum(
                scenario.probability
                * (
                    scale * scenario.return_r * scenario.execution_probability
                    - abs(scale)
                    * (action_explicit_cost_r + impact_r + reflexivity_r)
                    - max(scale, 0.0) * scenario.tail_loss_r
                )
                for scenario in scenarios
            )
        add_valid = (
            posterior_improved
            and prior_protective_stop is not None
            and proposed_protective_stop is not None
            and proposed_protective_stop > prior_protective_stop
        )
        if not add_valid:
            q_values[Action.ADD] = float("-inf")
            if position_fraction > 0:
                gates.append("ADD_REQUIRES_IMPROVED_POSTERIOR_AND_HIGHER_STOP")

        if stock.risk.blocks_new_risk:
            q_values[Action.BUY] = float("-inf")
            q_values[Action.ADD] = float("-inf")
            if position_fraction > 0:
                q_values[Action.EXIT] = max(q_values[Action.EXIT], 0.30)

        blocking = {
            "EDGE_CARD_MISSING",
            "EDGE_CARD_INCOMPLETE",
            "DATA_QUALITY_BELOW_GATE",
            "OBSERVABILITY_BELOW_GATE",
            "EXECUTION_PROBABILITY_BELOW_GATE",
            "CASH_DEFENSE",
        }
        if any(gate.split(":", 1)[0] in blocking for gate in gates):
            action = (
                Action.EXIT
                if position_fraction > 0 and stock.risk.blocks_new_risk
                else Action.NO_TRADE
            )
        else:
            action = max(q_values, key=q_values.__getitem__)
            if q_values[action] < q_values[Action.NO_TRADE] + self.decision.q_margin_r:
                action = Action.NO_TRADE
                gates.append("Q_MARGIN_NOT_MET")
        return GameDecision(
            action=action,
            family=family,
            q_values=q_values,
            raw_edge_r=raw_edge_r,
            adjusted_edge_r=adjusted_edge_r,
            observability=observability,
            scenario_probabilities={item.kind: item.probability for item in scenarios},
            gates=tuple(gates),
            edge_card=edge_card,
        )

    @staticmethod
    def _no_trade(
        family: StrategyFamily,
        gates: list[str],
        card: EdgeCard | None,
        observability: float,
    ) -> GameDecision:
        return GameDecision(
            action=Action.NO_TRADE,
            family=family,
            q_values={
                action: (0.0 if action == Action.NO_TRADE else float("-inf"))
                for action in Action
            },
            raw_edge_r=0.0,
            adjusted_edge_r=0.0,
            observability=observability,
            scenario_probabilities={},
            gates=tuple(gates),
            edge_card=card,
        )
