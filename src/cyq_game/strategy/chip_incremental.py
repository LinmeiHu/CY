"""Outcome-blind cohort rules for semantic chip incremental validation."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any

from cyq_game.domain import FutureDataError

DEVELOPMENT_START = date(2020, 1, 2)
DEVELOPMENT_END = date(2022, 12, 30)

# The corrected cohort must never inherit the old panel's chip-contaminated
# support or breakout fields.  The longer list also blocks direct chip state.
FORBIDDEN_CANDIDATE_FIELDS = frozenset(
    {
        "average_cost",
        "breakout_excess_atr",
        "cbw",
        "chip_model_disagreement_atr",
        "concentration_20",
        "cost_p01",
        "cost_p05",
        "cost_p10",
        "cost_p15",
        "cost_p50",
        "cost_p85",
        "cost_p90",
        "cost_p95",
        "cost_p99",
        "distribution_score",
        "dominant_band_lower",
        "dominant_band_mass",
        "dominant_band_upper",
        "i70_width_fraction",
        "i90_width_fraction",
        "lower_peak_center",
        "main_peak",
        "mass_sum",
        "peak_count",
        "profit_ratio",
        "setup_score",
        "state_quality",
        "structure_support",
        "support_regained",
        "trapped_ratio",
        "upper_peak_center",
        "valley_depth",
    }
)

_REQUIRED_FIELDS = frozenset(
    {
        "symbol",
        "trade_date",
        "decision_at",
        "available_at",
        "daily_snapshot_id",
        "symbol_session_index",
        "research_hard_valid",
        "tradable_state",
        "support_regained_price",
        "prior_breakout_excess_atr",
        "market_state",
        "sector_state",
    }
)


def assert_price_volume_candidate_schema(columns: Iterable[str]) -> None:
    """Reject chip state and the two contaminated legacy predictor names."""
    names = frozenset(str(column) for column in columns)
    forbidden = sorted(names.intersection(FORBIDDEN_CANDIDATE_FIELDS))
    if forbidden:
        raise ValueError(
            "price-volume cohort contains forbidden chip fields: "
            + ", ".join(forbidden)
        )
    missing = sorted(_REQUIRED_FIELDS - names)
    if missing:
        raise ValueError(
            "price-volume cohort is missing required fields: " + ", ".join(missing)
        )


def select_price_volume_candidates(
    rows: Iterable[Mapping[str, Any]],
    *,
    cooldown_sessions: int = 20,
) -> list[dict[str, Any]]:
    """Apply the preregistered event gates and deterministic de-duplication."""
    if cooldown_sessions != 20:
        raise ValueError("protocol fixes candidate cooldown at 20 sessions")
    materialized = [dict(row) for row in rows]
    if not materialized:
        return []
    schema: set[str] = set()
    for row in materialized:
        schema.update(row)
    assert_price_volume_candidate_schema(schema)
    materialized.sort(
        key=lambda row: (
            str(row["symbol"]),
            _as_date(row["trade_date"]),
            int(row["symbol_session_index"]),
        )
    )

    selected: list[dict[str, Any]] = []
    last_session_by_symbol: dict[str, int] = {}
    selected_weeks: set[tuple[str, int, int]] = set()
    for row in materialized:
        symbol = str(row["symbol"])
        trade_date = _as_date(row["trade_date"])
        if not DEVELOPMENT_START <= trade_date <= DEVELOPMENT_END:
            raise FutureDataError(
                f"price-volume cohort refuses date outside development: {trade_date}"
            )
        decision_at = _as_datetime(row["decision_at"])
        available_at = _as_datetime(row["available_at"])
        if available_at > decision_at:
            raise FutureDataError(
                f"{symbol} candidate is available after decision at {decision_at}"
            )
        if not _qualifies(row):
            continue
        session_index = int(row["symbol_session_index"])
        previous = last_session_by_symbol.get(symbol)
        if previous is not None and session_index - previous < cooldown_sessions:
            continue
        iso = trade_date.isocalendar()
        week_key = (symbol, iso.year, iso.week)
        if week_key in selected_weeks:
            continue
        candidate = dict(row)
        candidate["candidate_id"] = _candidate_id(candidate)
        candidate["candidate_definition"] = "PRICE_VOLUME_ONLY_BREAKOUT_RETEST_V1A1"
        candidate["candidate_uses_chip_fields"] = False
        selected.append(candidate)
        last_session_by_symbol[symbol] = session_index
        selected_weeks.add(week_key)
    return selected


def fixed_chip_primitives(row: Mapping[str, Any]) -> dict[str, Any]:
    """Compute the preregistered current and 20-session-stale primitives."""
    numeric_names = (
        "close",
        "atr14",
        "momentum_20",
        "exact_p50",
        "exact_p50_lag20",
        "exact_p50_lag40",
        "dominant_band_mass",
        "dominant_band_mass_lag20",
        "i70_lower",
        "i70_upper",
        "i90_lower",
        "i90_upper",
        "i70_lower_lag20",
        "i70_upper_lag20",
        "i90_lower_lag20",
        "i90_upper_lag20",
        "i90_width_fraction",
        "i90_width_fraction_lag20",
        "i90_width_fraction_lag40",
        "profit_ratio",
        "profit_ratio_lag20",
        "profit_ratio_lag40",
        "lower_peak_strength",
        "upper_peak_strength",
        "valley_depth",
        "lower_peak_strength_lag20",
        "upper_peak_strength_lag20",
        "valley_depth_lag20",
        "known_cost_fraction_min",
        "model_spread_i90_width_fraction",
        "close_lag20",
        "atr14_lag20",
        "momentum_20_lag20",
    )
    values = {name: _finite_float(row.get(name)) for name in numeric_names}
    reasons: list[str] = []
    if row.get("semantic_research_valid") is not True:
        reasons.append("SEMANTIC_SOURCE_INVALID")
    if row.get("exact_research_valid") is not True:
        reasons.append("EXACT_SOURCE_INVALID")
    known = values["known_cost_fraction_min"]
    if known is None or known < 0.95:
        reasons.append("KNOWN_COST_BELOW_95_PERCENT")
    if values["lower_peak_strength"] in (None, 0.0):
        reasons.append("LOWER_PEAK_UNOBSERVED")
    if values["upper_peak_strength"] is None:
        reasons.append("UPPER_PEAK_UNOBSERVED")
    if values["valley_depth"] is None:
        reasons.append("VALLEY_UNOBSERVED")
    if values["lower_peak_strength_lag20"] in (None, 0.0):
        reasons.append("STALE_LOWER_PEAK_UNOBSERVED")
    if values["upper_peak_strength_lag20"] is None:
        reasons.append("STALE_UPPER_PEAK_UNOBSERVED")
    if values["valley_depth_lag20"] is None:
        reasons.append("STALE_VALLEY_UNOBSERVED")

    close = values["close"]
    atr = values["atr14"]
    close_lag20 = values["close_lag20"]
    atr_lag20 = values["atr14_lag20"]
    if close is None or close <= 0 or atr is None or atr <= 0:
        reasons.append("CURRENT_PRICE_SCALE_INVALID")
    if (
        close_lag20 is None
        or close_lag20 <= 0
        or atr_lag20 is None
        or atr_lag20 <= 0
    ):
        reasons.append("STALE_PRICE_SCALE_INVALID")

    current = _primitive_set(values, stale=False)
    stale = _primitive_set(values, stale=True)
    missing = [name for name, value in (*current.items(), *stale.items()) if value is None]
    if missing:
        reasons.append("MISSING_FIXED_PRIMITIVES:" + ",".join(sorted(missing)))
    return {
        **current,
        **{f"stale_{name}": value for name, value in stale.items()},
        "seller_model_disagreement_atr": _safe_ratio(
            values["model_spread_i90_width_fraction"],
            None if close is None or atr is None or close <= 0 else atr / close,
        ),
        "known_cost_fraction_min": known,
        "chip_measurement_valid": not reasons,
        "chip_measurement_invalid_reasons": "|".join(reasons),
    }


def _primitive_set(
    values: Mapping[str, float | None], *, stale: bool
) -> dict[str, float | None]:
    suffix = "_lag20" if stale else ""
    atr = values[f"atr14{suffix}"]
    close = values[f"close{suffix}"]
    atr_fraction = (
        atr / close
        if atr is not None and close is not None and atr > 0 and close > 0
        else None
    )
    p50_now = values[f"exact_p50{suffix}"]
    p50_prior = values["exact_p50_lag40" if stale else "exact_p50_lag20"]
    cost_return = (
        p50_now / p50_prior - 1.0
        if p50_now is not None
        and p50_prior is not None
        and p50_now > 0
        and p50_prior > 0
        else None
    )
    momentum = values[f"momentum_20{suffix}"]
    price_minus_cost = (
        (momentum - cost_return) / atr_fraction
        if momentum is not None
        and cost_return is not None
        and atr_fraction is not None
        and atr_fraction > 0
        else None
    )
    profit_now = values[f"profit_ratio{suffix}"]
    profit_prior = values["profit_ratio_lag40" if stale else "profit_ratio_lag20"]
    width_now = values[f"i90_width_fraction{suffix}"]
    width_prior = values[
        "i90_width_fraction_lag40" if stale else "i90_width_fraction_lag20"
    ]
    lower_strength = values[f"lower_peak_strength{suffix}"]
    upper_strength = values[f"upper_peak_strength{suffix}"]
    return {
        "i70_width_atr": _safe_width(
            values[f"i70_lower{suffix}"], values[f"i70_upper{suffix}"], atr
        ),
        "i90_width_atr": _safe_width(
            values[f"i90_lower{suffix}"], values[f"i90_upper{suffix}"], atr
        ),
        "dominant_band_mass": values[f"dominant_band_mass{suffix}"],
        "price_minus_cost_migration_20_vol": price_minus_cost,
        "profit_ratio_change_20": (
            profit_now - profit_prior
            if profit_now is not None and profit_prior is not None
            else None
        ),
        "i90_contraction_20": (
            width_prior - width_now
            if width_prior is not None and width_now is not None
            else None
        ),
        "profit_ratio": profit_now,
        "upper_to_lower_peak_strength": _safe_ratio(
            upper_strength, lower_strength
        ),
        "valley_depth": values[f"valley_depth{suffix}"],
    }


def _safe_width(
    lower: float | None, upper: float | None, scale: float | None
) -> float | None:
    if (
        lower is None
        or upper is None
        or scale is None
        or scale <= 0
        or upper < lower
    ):
        return None
    return (upper - lower) / scale


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _qualifies(row: Mapping[str, Any]) -> bool:
    breakout = row.get("prior_breakout_excess_atr")
    return (
        row.get("research_hard_valid") is True
        and row.get("tradable_state") is True
        and row.get("support_regained_price") is True
        and isinstance(breakout, (float, int))
        and float(breakout) >= 0.25
        and row.get("market_state") in {"RISK_ON", "NEUTRAL"}
        and row.get("sector_state") in {"STRONG", "NEUTRAL"}
    )


def _candidate_id(row: Mapping[str, Any]) -> str:
    identity = {
        "symbol": str(row["symbol"]),
        "trade_date": _as_date(row["trade_date"]).isoformat(),
        "decision_at": _as_datetime(row["decision_at"]).isoformat(),
        "daily_snapshot_id": str(row["daily_snapshot_id"]),
        "definition": "PRICE_VOLUME_ONLY_BREAKOUT_RETEST_V1A1",
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return "pv-candidate-" + digest


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
