from __future__ import annotations

import csv
import fnmatch
import hashlib
import json
import sqlite3
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, tzinfo
from math import isfinite
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cyq_game.domain import Bar, FutureDataError
from cyq_game.execution.simulator import MarketRule
from cyq_game.portfolio.sizing import CalibratedForecast

if TYPE_CHECKING:
    from cyq_game.chip.features import ChipFeatures

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS market_bar (
    symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    amount REAL NOT NULL,
    free_float_shares REAL NOT NULL,
    suspended INTEGER NOT NULL DEFAULT 0,
    st INTEGER NOT NULL DEFAULT 0,
    limit_up REAL,
    limit_down REAL,
    event_time TEXT NOT NULL,
    available_at TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    source TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY(symbol, trade_date, snapshot_id, revision_id)
);
CREATE INDEX IF NOT EXISTS idx_market_bar_asof
ON market_bar(symbol, trade_date, available_at);

CREATE TABLE IF NOT EXISTS market_rule (
    rule_id TEXT NOT NULL,
    board TEXT NOT NULL,
    security_pattern TEXT NOT NULL,
    price_limit_pct REAL,
    t_plus_one INTEGER NOT NULL,
    lot_size INTEGER NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    available_at TEXT NOT NULL,
    source TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY(rule_id, effective_from, revision_id)
);

CREATE TABLE IF NOT EXISTS corporate_action (
    action_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    action_type TEXT NOT NULL,
    ex_date TEXT NOT NULL,
    ratio REAL,
    cash_per_share REAL,
    issue_price REAL,
    shares REAL,
    event_time TEXT NOT NULL,
    available_at TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    source TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    run_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS industry_membership (
    symbol TEXT NOT NULL,
    industry TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    available_at TEXT NOT NULL,
    source TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY(symbol, industry, effective_from, revision_id)
);

CREATE TABLE IF NOT EXISTS fundamental_snapshot (
    symbol TEXT NOT NULL,
    period_end TEXT NOT NULL,
    event_time TEXT NOT NULL,
    available_at TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    revenue_growth REAL,
    profit_growth REAL,
    roe REAL,
    operating_cashflow_to_profit REAL,
    debt_ratio REAL,
    valuation_percentile REAL,
    earnings_revision REAL,
    investment_growth REAL,
    capital_return REAL,
    audit_or_going_concern_risk INTEGER,
    source TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY(symbol, period_end, snapshot_id, revision_id)
);
CREATE INDEX IF NOT EXISTS idx_fundamental_snapshot_asof
ON fundamental_snapshot(symbol, effective_from, available_at, period_end);

CREATE TABLE IF NOT EXISTS data_store_identity (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    registry_id TEXT NOT NULL,
    registry_sha256 TEXT NOT NULL,
    input_manifest_id TEXT NOT NULL,
    input_manifest_sha256 TEXT NOT NULL,
    purpose TEXT NOT NULL,
    hard_valid INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('BUILDING', 'COMPLETE')),
    bound_at TEXT NOT NULL,
    completed_at TEXT,
    run_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state_snapshot (
    state_kind TEXT NOT NULL,
    symbol TEXT NOT NULL,
    as_of TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    available_at TEXT NOT NULL,
    version INTEGER NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY(state_kind, symbol, as_of, version, run_id)
);

CREATE TABLE IF NOT EXISTS experiment_registry (
    experiment_id TEXT PRIMARY KEY,
    parent_experiment_id TEXT,
    created_at TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    final_holdout_tainted INTEGER NOT NULL DEFAULT 0,
    run_id TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class MarketRuleRecord:
    rule_id: str
    board: str
    security_pattern: str
    price_limit_pct: float | None
    t_plus_one: bool
    lot_size: int
    effective_from: date
    effective_to: date | None
    available_at: datetime
    source: str
    snapshot_id: str
    revision_id: str
    run_id: str


@dataclass(frozen=True)
class CorporateActionRecord:
    action_id: str
    symbol: str
    action_type: str
    ex_date: date
    event_time: datetime
    available_at: datetime
    effective_from: datetime
    source: str
    snapshot_id: str
    revision_id: str
    run_id: str
    ratio: float | None = None
    cash_per_share: float | None = None
    issue_price: float | None = None
    shares: float | None = None


@dataclass(frozen=True)
class IndustryMembershipRecord:
    symbol: str
    industry: str
    effective_from: date
    effective_to: date | None
    available_at: datetime
    source: str
    snapshot_id: str
    revision_id: str
    run_id: str


@dataclass(frozen=True)
class FundamentalRecord:
    symbol: str
    period_end: date
    event_time: datetime
    available_at: datetime
    effective_from: date
    source: str
    snapshot_id: str
    revision_id: str
    run_id: str
    revenue_growth: float | None = None
    profit_growth: float | None = None
    roe: float | None = None
    operating_cashflow_to_profit: float | None = None
    debt_ratio: float | None = None
    valuation_percentile: float | None = None
    earnings_revision: float | None = None
    investment_growth: float | None = None
    capital_return: float | None = None
    audit_or_going_concern_risk: bool | None = None

    def __post_init__(self) -> None:
        if not self.symbol or not self.source or not self.snapshot_id:
            raise ValueError("fundamental identity and source fields must be non-empty")
        if not self.revision_id or not self.run_id:
            raise ValueError("fundamental revision_id and run_id must be non-empty")
        if self.available_at.tzinfo is None or self.event_time.tzinfo is None:
            raise ValueError("fundamental timestamps must be timezone-aware")
        if self.event_time > self.available_at:
            raise ValueError("fundamental event_time must not follow available_at")
        if self.period_end > self.available_at.astimezone(UTC).date():
            raise ValueError("fundamental period_end must not follow disclosure time")
        numeric = (
            self.revenue_growth,
            self.profit_growth,
            self.roe,
            self.operating_cashflow_to_profit,
            self.debt_ratio,
            self.valuation_percentile,
            self.earnings_revision,
            self.investment_growth,
            self.capital_return,
        )
        if any(value is not None and not isfinite(value) for value in numeric):
            raise ValueError("fundamental values must be finite when supplied")
        if self.debt_ratio is not None and not 0.0 <= self.debt_ratio <= 1.0:
            raise ValueError("fundamental debt_ratio must be in [0, 1]")
        if self.valuation_percentile is not None and not 0.0 <= self.valuation_percentile <= 1.0:
            raise ValueError("fundamental valuation_percentile must be in [0, 1]")
        if self.capital_return is not None and not -1.0 <= self.capital_return <= 1.0:
            raise ValueError("fundamental capital_return must be in [-1, 1]")


@dataclass(frozen=True)
class ChipObservation:
    """Causal intraday price/volume observations used to update the chip state."""

    symbol: str
    trade_date: date
    prices: tuple[float, ...]
    volumes: tuple[float, ...]
    available_at: datetime
    source: str
    snapshot_id: str
    hard_valid: bool
    opening_30m_return: float | None = None
    closing_30m_return: float | None = None
    close_vs_vwap: float | None = None
    last_hour_volume_share: float | None = None
    realized_volatility: float | None = None

    def __post_init__(self) -> None:
        if not self.symbol or not self.source or not self.snapshot_id:
            raise ValueError("chip observation identity fields must be non-empty")
        if self.available_at.tzinfo is None:
            raise ValueError("chip observation available_at must be timezone-aware")
        if not self.prices or len(self.prices) != len(self.volumes):
            raise ValueError("chip prices and volumes must be non-empty and aligned")
        if any(not isfinite(value) or value <= 0 for value in self.prices):
            raise ValueError("chip prices must be finite and positive")
        if any(not isfinite(value) or value < 0 for value in self.volumes):
            raise ValueError("chip volumes must be finite and non-negative")
        if sum(self.volumes) <= 0:
            raise ValueError("chip observation volume must be positive")
        intraday_values = (
            self.opening_30m_return,
            self.closing_30m_return,
            self.close_vs_vwap,
            self.last_hour_volume_share,
            self.realized_volatility,
        )
        if any(value is not None and not isfinite(value) for value in intraday_values):
            raise ValueError("intraday factors must be finite when supplied")
        if self.last_hour_volume_share is not None and not (
            0.0 <= self.last_hour_volume_share <= 1.0
        ):
            raise ValueError("last_hour_volume_share must be in [0, 1]")
        if self.realized_volatility is not None and self.realized_volatility < 0.0:
            raise ValueError("realized_volatility must be non-negative")

    @property
    def intraday_factors_complete(self) -> bool:
        return all(
            value is not None
            for value in (
                self.opening_30m_return,
                self.closing_30m_return,
                self.close_vs_vwap,
                self.last_hour_volume_share,
                self.realized_volatility,
            )
        )


@dataclass(frozen=True)
class PreparedChipRecord:
    """Frozen causal chip features, computed once and reused by strategy runs."""

    symbol: str
    trade_date: date
    available_at: datetime
    daily_snapshot_id: str
    minute_snapshot_id: str
    features: ChipFeatures
    base_retention: float
    strict_sample: bool
    invalid_reason: str
    opening_30m_return: float | None = None
    closing_30m_return: float | None = None
    close_vs_vwap: float | None = None
    last_hour_volume_share: float | None = None
    realized_volatility: float | None = None

    def __post_init__(self) -> None:
        if not self.symbol or not self.daily_snapshot_id or not self.minute_snapshot_id:
            raise ValueError("prepared chip identity fields must be non-empty")
        if self.available_at.tzinfo is None:
            raise ValueError("prepared chip available_at must be timezone-aware")
        if not isfinite(self.base_retention) or not 0.0 <= self.base_retention <= 1.0 + 1e-9:
            raise ValueError("prepared chip base_retention must be finite and in [0, 1]")
        values = (
            self.opening_30m_return,
            self.closing_30m_return,
            self.close_vs_vwap,
            self.last_hour_volume_share,
            self.realized_volatility,
        )
        if any(value is not None and not isfinite(value) for value in values):
            raise ValueError("prepared intraday factors must be finite when supplied")

    @property
    def intraday_factors_complete(self) -> bool:
        return all(
            value is not None
            for value in (
                self.opening_30m_return,
                self.closing_30m_return,
                self.close_vs_vwap,
                self.last_hour_volume_share,
                self.realized_volatility,
            )
        )


@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    parent_experiment_id: str | None
    created_at: datetime
    hypothesis: str
    config_hash: str
    status: str
    final_holdout_tainted: bool
    run_id: str


@dataclass(frozen=True)
class DataStoreIdentity:
    registry_id: str
    registry_sha256: str
    input_manifest_id: str
    input_manifest_sha256: str
    purpose: str
    hard_valid: bool
    status: str
    bound_at: datetime
    completed_at: datetime | None
    run_id: str


@dataclass(frozen=True)
class ExecutionDayBatch:
    """One causal read of execution windows and their matching market rules."""

    windows: Mapping[str, tuple[Bar, ...]]
    rules: Mapping[str, MarketRule]
    observed_symbols: frozenset[str]
    valid_symbols: frozenset[str]
    invalid_at: Mapping[str, datetime]


class PITStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def close(self) -> None:
        """Release adapter-owned resources; SQLite connections are per operation."""

    @property
    def decision_timezone(self) -> tzinfo:
        """Timezone used to form daily point-in-time decision boundaries."""

        return UTC

    @property
    def supports_native_forecast(self) -> bool:
        return False

    @property
    def requires_intraday_evidence(self) -> bool:
        """Whether missing hard-valid minute evidence must block new risk."""

        return False

    @property
    def supports_fundamental_signals(self) -> bool:
        """Whether frozen PIT fundamentals may enter the strategy chain."""

        return True

    @property
    def supports_precomputed_chip_features(self) -> bool:
        return False

    def calibrate_forecast(
        self,
        symbols: Sequence[str],
        train_dates: set[date],
        decision_at: datetime,
    ) -> CalibratedForecast:
        del symbols, train_dates, decision_at
        raise NotImplementedError("this PIT store does not support native calibration")

    def calibrate_forecasts(
        self,
        symbols: Sequence[str],
        train_dates: set[date],
        decision_at: datetime,
    ) -> dict[str, CalibratedForecast]:
        """Return one train-only forecast per symbol for the active walk-forward fold."""

        return {
            symbol: self.calibrate_forecast([symbol], train_dates, decision_at)
            for symbol in symbols
        }

    def chip_observations_for_day(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, ChipObservation]:
        """Return causal intraday observations; legacy stores have none."""

        del symbols, trade_date, decision_at
        return {}

    def prepared_chip_features_for_day(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, PreparedChipRecord]:
        del symbols, trade_date, decision_at
        return {}

    def execution_windows_for_day(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, list[Bar]]:
        """Return causal execution windows, preserving legacy daily-bar behavior."""

        bars = self.execution_bars_for_day(symbols, trade_date, decision_at)
        return {symbol: [bar] for symbol, bar in bars.items()}

    def execution_batch_for_day(
        self,
        symbol_boards: Mapping[str, str],
        trade_date: date,
        decision_at: datetime,
    ) -> ExecutionDayBatch:
        """Read bars and rules together; adapters can collapse both into one scan."""

        symbols = tuple(symbol_boards)
        windows = self.execution_windows_for_day(symbols, trade_date, decision_at)
        rules = self.rules_as_of(symbol_boards, trade_date, decision_at)
        frozen_windows = {symbol: tuple(bars) for symbol, bars in windows.items()}
        valid_symbols = frozenset(
            symbol
            for symbol, bars in frozen_windows.items()
            if bars and (rule := rules.get(symbol)) is not None and rule.known
        )
        return ExecutionDayBatch(
            windows=frozen_windows,
            rules=rules,
            observed_symbols=frozenset(frozen_windows),
            valid_symbols=valid_symbols,
            invalid_at={},
        )

    def rules_as_of(
        self,
        symbol_boards: Mapping[str, str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, MarketRule]:
        """Batch rule lookup; adapters may replace N point queries with one scan."""

        return {
            symbol: self.rule_as_of(symbol, board, trade_date, decision_at)
            for symbol, board in symbol_boards.items()
        }

    def corporate_actions_for_day(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, list[CorporateActionRecord]]:
        """Batch corporate-action lookup for one economic date."""

        result: dict[str, list[CorporateActionRecord]] = {}
        for symbol in symbols:
            records = self.corporate_actions_as_of(symbol, trade_date, trade_date, decision_at)
            if records:
                result[symbol] = records
        return result

    def fundamentals_as_of(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, FundamentalRecord]:
        """Batch fundamental lookup for one decision boundary."""

        result: dict[str, FundamentalRecord] = {}
        for symbol in symbols:
            record = self.fundamental_as_of(symbol, trade_date, decision_at)
            if record is not None:
                result[symbol] = record
        return result

    def source_digest(self) -> str:
        """Digest the physical store used by the runtime manifest."""

        digest = hashlib.sha256()
        with self.path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def bind_input_manifest(
        self,
        *,
        registry_id: str,
        registry_sha256: str,
        input_manifest_id: str,
        input_manifest_sha256: str,
        purpose: str,
        hard_valid: bool,
        run_id: str,
        bound_at: datetime,
    ) -> DataStoreIdentity:
        """Bind an empty store to one immutable input snapshot.

        An existing unbound store containing source facts cannot be blessed
        retroactively because its physical inputs are no longer provable.
        Rebinding to another manifest is always rejected.
        """

        if bound_at.tzinfo is None:
            raise ValueError("bound_at must be timezone-aware")
        identity_values = (
            registry_id,
            registry_sha256,
            input_manifest_id,
            input_manifest_sha256,
            purpose,
        )
        if any(not value for value in identity_values) or not run_id:
            raise ValueError("data-store identity fields must be non-empty")
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM data_store_identity WHERE singleton_id = 1"
            ).fetchone()
            if row is not None:
                current = _row_to_data_store_identity(row)
                expected = (
                    registry_id,
                    registry_sha256,
                    input_manifest_id,
                    input_manifest_sha256,
                    purpose,
                    hard_valid,
                )
                actual = (
                    current.registry_id,
                    current.registry_sha256,
                    current.input_manifest_id,
                    current.input_manifest_sha256,
                    current.purpose,
                    current.hard_valid,
                )
                if actual != expected:
                    raise ValueError(
                        "PIT store is already bound to a different input snapshot manifest"
                    )
                return current

            source_tables = (
                "market_bar",
                "market_rule",
                "corporate_action",
                "industry_membership",
                "fundamental_snapshot",
            )
            populated = [
                table
                for table in source_tables
                if int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) > 0
            ]
            if populated:
                raise ValueError(
                    "cannot bind a non-empty legacy PIT store; populated tables: "
                    + ", ".join(populated)
                )
            connection.execute(
                """
                INSERT INTO data_store_identity (
                  singleton_id, registry_id, registry_sha256, input_manifest_id,
                  input_manifest_sha256, purpose, hard_valid, status, bound_at,
                  completed_at, run_id
                ) VALUES (1, ?, ?, ?, ?, ?, ?, 'BUILDING', ?, NULL, ?)
                """,
                (
                    registry_id,
                    registry_sha256,
                    input_manifest_id,
                    input_manifest_sha256,
                    purpose,
                    int(hard_valid),
                    bound_at.isoformat(),
                    run_id,
                ),
            )
        return self.data_store_identity()

    def complete_input_manifest(
        self,
        *,
        input_manifest_id: str,
        input_manifest_sha256: str,
        completed_at: datetime,
    ) -> DataStoreIdentity:
        if completed_at.tzinfo is None:
            raise ValueError("completed_at must be timezone-aware")
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM data_store_identity WHERE singleton_id = 1"
            ).fetchone()
            if row is None:
                raise ValueError("PIT store has no input snapshot identity")
            current = _row_to_data_store_identity(row)
            if (
                current.input_manifest_id != input_manifest_id
                or current.input_manifest_sha256 != input_manifest_sha256
            ):
                raise ValueError("PIT store is not bound to the supplied input manifest")
            if current.status == "COMPLETE":
                return current
            connection.execute(
                """
                UPDATE data_store_identity
                SET status = 'COMPLETE', completed_at = ?
                WHERE singleton_id = 1
                """,
                (completed_at.isoformat(),),
            )
        return self.data_store_identity()

    def data_store_identity(self) -> DataStoreIdentity:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM data_store_identity WHERE singleton_id = 1"
            ).fetchone()
        if row is None:
            raise ValueError("PIT store has no input snapshot identity")
        return _row_to_data_store_identity(row)

    def require_input_manifest(
        self,
        *,
        registry_id: str,
        registry_sha256: str,
        input_manifest_id: str,
        input_manifest_sha256: str,
        require_hard_valid: bool = True,
    ) -> DataStoreIdentity:
        identity = self.data_store_identity()
        expected = (
            registry_id,
            registry_sha256,
            input_manifest_id,
            input_manifest_sha256,
        )
        actual = (
            identity.registry_id,
            identity.registry_sha256,
            identity.input_manifest_id,
            identity.input_manifest_sha256,
        )
        if actual != expected:
            raise ValueError("PIT store input identity does not match the active manifest")
        if identity.status != "COMPLETE":
            raise ValueError("PIT store input snapshot is not COMPLETE")
        if require_hard_valid and not identity.hard_valid:
            raise ValueError("PIT store hard_valid=false blocks strategy state and backtest")
        return identity

    def ingest_bars(
        self,
        bars: Iterable[Bar],
        *,
        source: str,
        snapshot_id: str,
        run_id: str,
    ) -> int:
        query = """
        INSERT OR IGNORE INTO market_bar (
          symbol, trade_date, open, high, low, close, volume, amount,
          free_float_shares, suspended, st, limit_up, limit_down,
          event_time, available_at, effective_from, source, snapshot_id,
          revision_id, run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = []
        for bar in bars:
            event_at = datetime.combine(bar.trade_date, time(15), tzinfo=UTC)
            rows.append(
                (
                    bar.symbol,
                    bar.trade_date.isoformat(),
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    bar.amount,
                    bar.free_float_shares,
                    int(bar.suspended),
                    int(bar.st),
                    bar.limit_up,
                    bar.limit_down,
                    event_at.isoformat(),
                    bar.available_at.isoformat(),
                    event_at.isoformat(),
                    source,
                    snapshot_id,
                    "1",
                    run_id,
                )
            )
        with self.connect() as connection:
            before = connection.total_changes
            connection.executemany(query, rows)
            return connection.total_changes - before

    def bars_as_of(
        self,
        symbol: str,
        start: date,
        end: date,
        decision_at: datetime,
    ) -> list[Bar]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM market_bar
                WHERE symbol = ? AND trade_date BETWEEN ? AND ? AND available_at <= ?
                ORDER BY trade_date, available_at, revision_id
                """,
                (symbol, start.isoformat(), end.isoformat(), decision_at.isoformat()),
            ).fetchall()
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest[str(row["trade_date"])] = row
        return [_row_to_bar(latest[key], decision_at) for key in sorted(latest)]

    def symbols(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT symbol FROM market_bar ORDER BY symbol"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def date_bounds(self) -> tuple[date, date]:
        """Return the inclusive date range present in the immutable bar snapshots."""

        with self.connect() as connection:
            row = connection.execute(
                "SELECT MIN(trade_date), MAX(trade_date) FROM market_bar"
            ).fetchone()
        if row is None or row[0] is None or row[1] is None:
            raise ValueError("PIT store contains no market bars")
        return date.fromisoformat(str(row[0])), date.fromisoformat(str(row[1]))

    def trading_dates_as_of(
        self,
        start: date,
        end: date,
        decision_at: datetime,
        symbols: Sequence[str] | None = None,
    ) -> list[date]:
        """Return only dates whose market data was available at the PIT boundary."""

        parameters: list[object] = [
            start.isoformat(),
            end.isoformat(),
            decision_at.isoformat(),
        ]
        symbol_filter = ""
        if symbols:
            placeholders = ",".join("?" for _ in symbols)
            symbol_filter = f" AND symbol IN ({placeholders})"
            parameters.extend(symbols)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT trade_date FROM market_bar
                WHERE trade_date BETWEEN ? AND ? AND available_at <= ?
                {symbol_filter}
                ORDER BY trade_date
                """,
                parameters,
            ).fetchall()
        return [date.fromisoformat(str(row[0])) for row in rows]

    def strict_bars_for_day(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, Bar]:
        """Return bars eligible to create strategy state and new risk."""

        result: dict[str, Bar] = {}
        for symbol in symbols:
            bars = self.bars_as_of(symbol, trade_date, trade_date, decision_at)
            if bars:
                result[symbol] = bars[-1]
        return result

    def execution_bars_for_day(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, Bar]:
        """Return bars usable for valuation and risk-reducing execution."""

        return self.strict_bars_for_day(symbols, trade_date, decision_at)

    def bar_provenance(
        self,
        symbol: str,
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, Any]:
        bars = self.bars_as_of(symbol, trade_date, trade_date, decision_at)
        if not bars:
            return {}
        return {
            "bar_available_at": bars[-1].available_at.isoformat(),
            "bar_snapshot_id": None,
            "hard_valid": True,
            "invalid_reasons": [],
        }

    def bar_provenances_for_day(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, dict[str, Any]]:
        """Return daily bar provenance, with a compatible batched default."""

        return {
            symbol: provenance
            for symbol in symbols
            if (provenance := self.bar_provenance(symbol, trade_date, decision_at))
        }

    def ingest_market_rules(self, records: Iterable[MarketRuleRecord]) -> int:
        query = """
        INSERT OR IGNORE INTO market_rule (
          rule_id, board, security_pattern, price_limit_pct, t_plus_one, lot_size,
          effective_from, effective_to, available_at, source, snapshot_id,
          revision_id, run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                item.rule_id,
                item.board,
                item.security_pattern,
                item.price_limit_pct,
                int(item.t_plus_one),
                item.lot_size,
                item.effective_from.isoformat(),
                item.effective_to.isoformat() if item.effective_to else None,
                item.available_at.isoformat(),
                item.source,
                item.snapshot_id,
                item.revision_id,
                item.run_id,
            )
            for item in records
        ]
        with self.connect() as connection:
            before = connection.total_changes
            connection.executemany(query, rows)
            return connection.total_changes - before

    def rule_as_of(
        self,
        symbol: str,
        board: str,
        trade_date: date,
        decision_at: datetime,
    ) -> MarketRule:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM market_rule
                WHERE board IN (?, '*')
                  AND effective_from <= ?
                  AND (effective_to IS NULL OR effective_to >= ?)
                  AND available_at <= ?
                ORDER BY available_at DESC, revision_id DESC
                """,
                (
                    board,
                    trade_date.isoformat(),
                    trade_date.isoformat(),
                    decision_at.isoformat(),
                ),
            ).fetchall()
        for row in rows:
            if fnmatch.fnmatchcase(symbol, str(row["security_pattern"])):
                return MarketRule(
                    rule_id=str(row["rule_id"]),
                    effective_from=date.fromisoformat(str(row["effective_from"])),
                    effective_to=(
                        date.fromisoformat(str(row["effective_to"]))
                        if row["effective_to"]
                        else None
                    ),
                    price_limit_pct=_optional_float(row["price_limit_pct"]),
                    t_plus_one=bool(row["t_plus_one"]),
                    lot_size=int(row["lot_size"]),
                    known=True,
                )
        return MarketRule(
            rule_id="UNKNOWN",
            effective_from=trade_date,
            effective_to=trade_date,
            price_limit_pct=None,
            t_plus_one=True,
            lot_size=0,
            known=False,
        )

    def ingest_corporate_actions(self, records: Iterable[CorporateActionRecord]) -> int:
        query = """
        INSERT OR IGNORE INTO corporate_action (
          action_id, symbol, action_type, ex_date, ratio, cash_per_share,
          issue_price, shares, event_time, available_at, effective_from,
          source, snapshot_id, revision_id, run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                item.action_id,
                item.symbol,
                item.action_type,
                item.ex_date.isoformat(),
                item.ratio,
                item.cash_per_share,
                item.issue_price,
                item.shares,
                item.event_time.isoformat(),
                item.available_at.isoformat(),
                item.effective_from.isoformat(),
                item.source,
                item.snapshot_id,
                item.revision_id,
                item.run_id,
            )
            for item in records
        ]
        with self.connect() as connection:
            before = connection.total_changes
            connection.executemany(query, rows)
            return connection.total_changes - before

    def corporate_actions_as_of(
        self,
        symbol: str,
        start: date,
        end: date,
        decision_at: datetime,
    ) -> list[CorporateActionRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM corporate_action
                WHERE symbol = ? AND ex_date BETWEEN ? AND ? AND available_at <= ?
                ORDER BY ex_date, available_at, revision_id
                """,
                (symbol, start.isoformat(), end.isoformat(), decision_at.isoformat()),
            ).fetchall()
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest[str(row["action_id"])] = row
        return [_row_to_corporate_action(row) for row in latest.values()]

    def ingest_industry_memberships(self, records: Iterable[IndustryMembershipRecord]) -> int:
        query = """
        INSERT OR IGNORE INTO industry_membership (
          symbol, industry, effective_from, effective_to, available_at,
          source, snapshot_id, revision_id, run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                item.symbol,
                item.industry,
                item.effective_from.isoformat(),
                item.effective_to.isoformat() if item.effective_to else None,
                item.available_at.isoformat(),
                item.source,
                item.snapshot_id,
                item.revision_id,
                item.run_id,
            )
            for item in records
        ]
        with self.connect() as connection:
            before = connection.total_changes
            connection.executemany(query, rows)
            return connection.total_changes - before

    def industry_memberships_as_of(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, IndustryMembershipRecord]:
        """Return one unambiguous effective membership per requested symbol.

        Memberships are filtered by economic validity and publication time. If
        two industries have identical top precedence, the symbol is omitted so
        downstream decisions fail closed instead of guessing a classification.
        """

        if not symbols:
            return {}
        placeholders = ",".join("?" for _ in symbols)
        parameters: list[object] = [
            *symbols,
            trade_date.isoformat(),
            trade_date.isoformat(),
            decision_at.isoformat(),
        ]
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM industry_membership
                WHERE symbol IN ({placeholders})
                  AND effective_from <= ?
                  AND (effective_to IS NULL OR effective_to >= ?)
                  AND available_at <= ?
                ORDER BY symbol, effective_from DESC, available_at DESC,
                         revision_id DESC, industry
                """,
                parameters,
            ).fetchall()

        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(str(row["symbol"]), []).append(row)
        result: dict[str, IndustryMembershipRecord] = {}
        for symbol, candidates in grouped.items():
            first = candidates[0]
            precedence = (
                str(first["effective_from"]),
                str(first["available_at"]),
                str(first["revision_id"]),
            )
            tied_industries = {
                str(row["industry"])
                for row in candidates
                if (
                    str(row["effective_from"]),
                    str(row["available_at"]),
                    str(row["revision_id"]),
                )
                == precedence
            }
            if len(tied_industries) != 1:
                continue
            result[symbol] = _row_to_industry_membership(first)
        return result

    def ingest_fundamentals(self, records: Iterable[FundamentalRecord]) -> int:
        query = """
        INSERT OR IGNORE INTO fundamental_snapshot (
          symbol, period_end, event_time, available_at, effective_from,
          revenue_growth, profit_growth, roe, operating_cashflow_to_profit,
          debt_ratio, valuation_percentile, earnings_revision, investment_growth,
          capital_return, audit_or_going_concern_risk, source, snapshot_id,
          revision_id, run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                item.symbol,
                item.period_end.isoformat(),
                _utc_iso(item.event_time),
                _utc_iso(item.available_at),
                item.effective_from.isoformat(),
                item.revenue_growth,
                item.profit_growth,
                item.roe,
                item.operating_cashflow_to_profit,
                item.debt_ratio,
                item.valuation_percentile,
                item.earnings_revision,
                item.investment_growth,
                item.capital_return,
                (
                    int(item.audit_or_going_concern_risk)
                    if item.audit_or_going_concern_risk is not None
                    else None
                ),
                item.source,
                item.snapshot_id,
                item.revision_id,
                item.run_id,
            )
            for item in records
        ]
        with self.connect() as connection:
            before = connection.total_changes
            connection.executemany(query, rows)
            return connection.total_changes - before

    def fundamental_as_of(
        self,
        symbol: str,
        trade_date: date,
        decision_at: datetime,
    ) -> FundamentalRecord | None:
        """Return the newest economically effective snapshot actually available.

        ``period_end`` alone never makes a filing visible: both ``effective_from``
        and the publication boundary ``available_at`` must have passed.
        """

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM fundamental_snapshot
                WHERE symbol = ?
                  AND period_end <= ?
                  AND effective_from <= ?
                  AND available_at <= ?
                ORDER BY period_end DESC, effective_from DESC,
                         available_at DESC, revision_id DESC, snapshot_id DESC
                LIMIT 1
                """,
                (
                    symbol,
                    trade_date.isoformat(),
                    trade_date.isoformat(),
                    _utc_iso(decision_at),
                ),
            ).fetchone()
        return _row_to_fundamental(row, decision_at) if row is not None else None

    def register_experiment(
        self,
        *,
        experiment_id: str,
        hypothesis: str,
        config_text: str,
        run_id: str,
        created_at: datetime,
        parent_experiment_id: str | None = None,
        status: str = "DEVELOPMENT",
    ) -> ExperimentRecord:
        config_hash = hashlib.sha256(config_text.encode()).hexdigest()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO experiment_registry (
                  experiment_id, parent_experiment_id, created_at, hypothesis,
                  config_hash, status, final_holdout_tainted, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    experiment_id,
                    parent_experiment_id,
                    created_at.isoformat(),
                    hypothesis,
                    config_hash,
                    status,
                    run_id,
                ),
            )
        return ExperimentRecord(
            experiment_id,
            parent_experiment_id,
            created_at,
            hypothesis,
            config_hash,
            status,
            False,
            run_id,
        )

    def mark_holdout_tainted(self, experiment_id: str) -> None:
        with self.connect() as connection:
            changed = connection.execute(
                """
                UPDATE experiment_registry
                SET final_holdout_tainted = 1, status = 'HOLDOUT_ACCESSED'
                WHERE experiment_id = ?
                """,
                (experiment_id,),
            ).rowcount
        if changed != 1:
            raise KeyError(f"unknown experiment: {experiment_id}")

    def experiment(self, experiment_id: str) -> ExperimentRecord:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM experiment_registry WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown experiment: {experiment_id}")
        return ExperimentRecord(
            experiment_id=str(row["experiment_id"]),
            parent_experiment_id=(
                str(row["parent_experiment_id"]) if row["parent_experiment_id"] else None
            ),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            hypothesis=str(row["hypothesis"]),
            config_hash=str(row["config_hash"]),
            status=str(row["status"]),
            final_holdout_tainted=bool(row["final_holdout_tainted"]),
            run_id=str(row["run_id"]),
        )

    def save_state(
        self,
        *,
        kind: str,
        symbol: str,
        as_of: datetime,
        payload: dict[str, Any],
        version: int,
        run_id: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO state_snapshot
                (state_kind, symbol, as_of, payload_json, available_at, version, run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    symbol,
                    as_of.isoformat(),
                    json.dumps(payload, sort_keys=True, ensure_ascii=False),
                    as_of.isoformat(),
                    version,
                    run_id,
                ),
            )


def read_bars_csv(
    path: str | Path,
    *,
    require_available_at: bool = False,
) -> list[Bar]:
    bars: list[Bar] = []
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            trade_date = date.fromisoformat(row["trade_date"])
            available_raw = row.get("available_at")
            if require_available_at and not available_raw:
                raise ValueError(f"bar row {row_number} has no explicit available_at")
            available_at = (
                datetime.fromisoformat(available_raw)
                if available_raw
                else datetime.combine(trade_date, time(15, 30), tzinfo=UTC)
            )
            if available_at.tzinfo is None:
                available_at = available_at.replace(tzinfo=UTC)
            bars.append(
                Bar(
                    symbol=row["symbol"],
                    trade_date=trade_date,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    amount=float(row.get("amount") or 0.0),
                    free_float_shares=float(row["free_float_shares"]),
                    available_at=available_at,
                    suspended=_bool(row.get("suspended")),
                    st=_bool(row.get("st")),
                    limit_up=_optional_float(row.get("limit_up")),
                    limit_down=_optional_float(row.get("limit_down")),
                )
            )
    return bars


def read_industry_memberships_csv(
    path: str | Path,
    *,
    run_id: str,
    snapshot_id: str,
    default_source: str = "csv",
    enforce_identity: bool = False,
) -> list[IndustryMembershipRecord]:
    records: list[IndustryMembershipRecord] = []
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            source = row.get("source") or default_source
            row_snapshot_id = row.get("snapshot_id") or snapshot_id
            if enforce_identity and source != default_source:
                raise ValueError(f"industry row {row_number} source differs from active binding")
            if enforce_identity and row_snapshot_id != snapshot_id:
                raise ValueError(
                    f"industry row {row_number} snapshot_id differs from active binding"
                )
            available_at = datetime.fromisoformat(row["available_at"])
            if available_at.tzinfo is None:
                available_at = available_at.replace(tzinfo=UTC)
            effective_to_raw = row.get("effective_to")
            records.append(
                IndustryMembershipRecord(
                    symbol=row["symbol"],
                    industry=row["industry"],
                    effective_from=date.fromisoformat(row["effective_from"]),
                    effective_to=(
                        date.fromisoformat(effective_to_raw) if effective_to_raw else None
                    ),
                    available_at=available_at,
                    source=source,
                    snapshot_id=row_snapshot_id,
                    revision_id=row.get("revision_id") or "1",
                    run_id=run_id,
                )
            )
    return records


def read_fundamentals_csv(
    path: str | Path,
    *,
    run_id: str,
    snapshot_id: str,
    default_source: str = "csv",
    enforce_identity: bool = False,
) -> list[FundamentalRecord]:
    """Read revision-aware PIT fundamental disclosures from a normalized CSV."""

    records: list[FundamentalRecord] = []
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            source = row.get("source") or default_source
            row_snapshot_id = row.get("snapshot_id") or snapshot_id
            if enforce_identity and source != default_source:
                raise ValueError(f"fundamental row {row_number} source differs from active binding")
            if enforce_identity and row_snapshot_id != snapshot_id:
                raise ValueError(
                    f"fundamental row {row_number} snapshot_id differs from active binding"
                )
            period_end = date.fromisoformat(row["period_end"])
            available_at = _aware_datetime(row["available_at"])
            event_at = _aware_datetime(row.get("event_time") or row["available_at"])
            if event_at > available_at:
                raise ValueError(f"fundamental row {row_number} event_time follows available_at")
            effective_raw = row.get("effective_from")
            records.append(
                FundamentalRecord(
                    symbol=row["symbol"],
                    period_end=period_end,
                    event_time=event_at,
                    available_at=available_at,
                    effective_from=(
                        date.fromisoformat(effective_raw) if effective_raw else available_at.date()
                    ),
                    source=source,
                    snapshot_id=row_snapshot_id,
                    revision_id=row.get("revision_id") or "1",
                    run_id=run_id,
                    revenue_growth=_optional_float(row.get("revenue_growth")),
                    profit_growth=_optional_float(row.get("profit_growth")),
                    roe=_optional_float(row.get("roe")),
                    operating_cashflow_to_profit=_optional_float(
                        row.get("operating_cashflow_to_profit")
                    ),
                    debt_ratio=_optional_float(row.get("debt_ratio")),
                    valuation_percentile=_optional_float(row.get("valuation_percentile")),
                    earnings_revision=_optional_float(row.get("earnings_revision")),
                    investment_growth=_optional_float(row.get("investment_growth")),
                    capital_return=_optional_float(row.get("capital_return")),
                    audit_or_going_concern_risk=_optional_bool(
                        row.get("audit_or_going_concern_risk")
                    ),
                )
            )
    return records


def filter_date_range(bars: Sequence[Bar], start: date, end: date) -> list[Bar]:
    return [bar for bar in bars if start <= bar.trade_date <= end]


def _row_to_bar(row: sqlite3.Row, decision_at: datetime) -> Bar:
    available_at = datetime.fromisoformat(str(row["available_at"]))
    if available_at > decision_at:
        raise FutureDataError("PIT query returned a future market bar")
    return Bar(
        symbol=str(row["symbol"]),
        trade_date=date.fromisoformat(str(row["trade_date"])),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
        amount=float(row["amount"]),
        free_float_shares=float(row["free_float_shares"]),
        available_at=available_at,
        suspended=bool(row["suspended"]),
        st=bool(row["st"]),
        limit_up=_optional_float(row["limit_up"]),
        limit_down=_optional_float(row["limit_down"]),
    )


def _row_to_data_store_identity(row: sqlite3.Row) -> DataStoreIdentity:
    return DataStoreIdentity(
        registry_id=str(row["registry_id"]),
        registry_sha256=str(row["registry_sha256"]),
        input_manifest_id=str(row["input_manifest_id"]),
        input_manifest_sha256=str(row["input_manifest_sha256"]),
        purpose=str(row["purpose"]),
        hard_valid=bool(row["hard_valid"]),
        status=str(row["status"]),
        bound_at=datetime.fromisoformat(str(row["bound_at"])),
        completed_at=(
            datetime.fromisoformat(str(row["completed_at"])) if row["completed_at"] else None
        ),
        run_id=str(row["run_id"]),
    )


def _row_to_corporate_action(row: sqlite3.Row) -> CorporateActionRecord:
    return CorporateActionRecord(
        action_id=str(row["action_id"]),
        symbol=str(row["symbol"]),
        action_type=str(row["action_type"]),
        ex_date=date.fromisoformat(str(row["ex_date"])),
        ratio=_optional_float(row["ratio"]),
        cash_per_share=_optional_float(row["cash_per_share"]),
        issue_price=_optional_float(row["issue_price"]),
        shares=_optional_float(row["shares"]),
        event_time=datetime.fromisoformat(str(row["event_time"])),
        available_at=datetime.fromisoformat(str(row["available_at"])),
        effective_from=datetime.fromisoformat(str(row["effective_from"])),
        source=str(row["source"]),
        snapshot_id=str(row["snapshot_id"]),
        revision_id=str(row["revision_id"]),
        run_id=str(row["run_id"]),
    )


def _row_to_industry_membership(row: sqlite3.Row) -> IndustryMembershipRecord:
    return IndustryMembershipRecord(
        symbol=str(row["symbol"]),
        industry=str(row["industry"]),
        effective_from=date.fromisoformat(str(row["effective_from"])),
        effective_to=(
            date.fromisoformat(str(row["effective_to"])) if row["effective_to"] else None
        ),
        available_at=datetime.fromisoformat(str(row["available_at"])),
        source=str(row["source"]),
        snapshot_id=str(row["snapshot_id"]),
        revision_id=str(row["revision_id"]),
        run_id=str(row["run_id"]),
    )


def _row_to_fundamental(row: sqlite3.Row, decision_at: datetime) -> FundamentalRecord:
    available_at = datetime.fromisoformat(str(row["available_at"]))
    if available_at > decision_at:
        raise FutureDataError("PIT query returned a future fundamental snapshot")
    return FundamentalRecord(
        symbol=str(row["symbol"]),
        period_end=date.fromisoformat(str(row["period_end"])),
        event_time=datetime.fromisoformat(str(row["event_time"])),
        available_at=available_at,
        effective_from=date.fromisoformat(str(row["effective_from"])),
        source=str(row["source"]),
        snapshot_id=str(row["snapshot_id"]),
        revision_id=str(row["revision_id"]),
        run_id=str(row["run_id"]),
        revenue_growth=_optional_float(row["revenue_growth"]),
        profit_growth=_optional_float(row["profit_growth"]),
        roe=_optional_float(row["roe"]),
        operating_cashflow_to_profit=_optional_float(row["operating_cashflow_to_profit"]),
        debt_ratio=_optional_float(row["debt_ratio"]),
        valuation_percentile=_optional_float(row["valuation_percentile"]),
        earnings_revision=_optional_float(row["earnings_revision"]),
        investment_growth=_optional_float(row["investment_growth"]),
        capital_return=_optional_float(row["capital_return"]),
        audit_or_going_concern_risk=(
            bool(row["audit_or_going_concern_risk"])
            if row["audit_or_going_concern_risk"] is not None
            else None
        ),
    )


def _bool(value: object) -> bool:
    return str(value).lower() in {"1", "true", "yes", "y"}


def _optional_bool(value: object) -> bool | None:
    if value in {None, ""}:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"invalid optional boolean value: {value}")


def _aware_datetime(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    aware = result if result.tzinfo is not None else result.replace(tzinfo=UTC)
    return aware.astimezone(UTC)


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("PIT timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _optional_float(value: object) -> float | None:
    if value in {None, ""}:
        return None
    return float(str(value))
