"""Preregistered close-to-next-session gate, with no position operations."""
from dataclasses import dataclass
from datetime import date
import math


@dataclass
class DrawdownGate:
    D: float
    high: float
    level: int = 0
    recovery_count: int = 0
    last_close: date | None = None

    def __post_init__(self):
        if self.D not in (0.04, 0.05, 0.06) or not math.isfinite(self.high) or self.high <= 0:
            raise ValueError("Only D4/D5/D6 with positive initial NAV")

    @property
    def multiplier(self):
        return (1.0, 0.75, 0.5, 0.0)[self.level]

    def complete_close(self, day: date, nav: float) -> float:
        """Caller supplies each completed trading close once; return NEXT session capacity."""
        if self.last_close is not None and day <= self.last_close:
            raise ValueError("Close timestamps must strictly increase")
        if not math.isfinite(nav) or nav <= 0:
            raise ValueError("Positive finite NAV required")
        self.last_close = day
        self.high = max(self.high, nav)
        loss = 1 - nav / self.high
        thresholds = (0.5 * self.D, 0.75 * self.D, self.D)
        target = sum(loss >= boundary - 1e-14 for boundary in thresholds)
        if target > self.level:
            self.level, self.recovery_count = target, 0
        elif self.level and loss <= thresholds[self.level - 1] - 0.1 * self.D + 1e-14:
            self.recovery_count += 1
            if self.recovery_count == 3:
                self.level -= 1
                self.recovery_count = 0
        else:
            self.recovery_count = 0
        return self.multiplier
