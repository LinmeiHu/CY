from __future__ import annotations

from math import sqrt

import numpy as np


def performance_metrics(
    equity: list[float],
    *,
    fills: int,
    gross_profit: float,
    gross_loss: float,
    total_cost: float,
    blocked_orders: int,
    submitted_orders: int,
    rejected_orders: int = 0,
    order_generation_rejections: int = 0,
) -> dict[str, float | int]:
    if not equity:
        return {}
    values = np.asarray(equity, dtype=np.float64)
    returns = values[1:] / np.maximum(values[:-1], 1e-12) - 1.0
    total_return = float(values[-1] / values[0] - 1.0) if len(values) > 1 else 0.0
    annualized = (1.0 + total_return) ** (252.0 / max(1, len(returns))) - 1.0
    volatility = float(np.std(returns, ddof=1) * sqrt(252.0)) if len(returns) > 1 else 0.0
    sharpe = float(np.mean(returns) * 252.0 / volatility) if volatility > 1e-12 else 0.0
    running_max = np.maximum.accumulate(values)
    drawdowns = 1.0 - values / np.maximum(running_max, 1e-12)
    max_drawdown = float(np.max(drawdowns))
    downside = returns[returns < 0]
    downside_vol = float(np.std(downside, ddof=1) * sqrt(252.0)) if len(downside) > 1 else 0.0
    sortino = (
        float(np.mean(returns) * 252.0 / downside_vol)
        if downside_vol > 1e-12
        else 0.0
    )
    return {
        "initial_equity": float(values[0]),
        "final_equity": float(values[-1]),
        "total_return": total_return,
        "annualized_return": float(annualized),
        "annualized_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": float(annualized / max_drawdown) if max_drawdown > 1e-12 else 0.0,
        "fills": fills,
        "profit_factor": gross_profit / max(gross_loss, 1e-12),
        "total_cost": total_cost,
        "blocked_order_rate": blocked_orders / max(submitted_orders, 1),
        "rejected_order_rate": rejected_orders / max(submitted_orders, 1),
        "order_generation_rejections": order_generation_rejections,
    }
