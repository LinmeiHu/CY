"""Direct runtime adapter for the frozen PIT-B daily Parquet dataset."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, tzinfo
from functools import lru_cache
from pathlib import Path
from statistics import fmean
from typing import Any, cast
from zoneinfo import ZoneInfo

import duckdb

from cyq_game.chip.features import CYQK, ChipFeatures, ChipPeak
from cyq_game.data.pit import (
    ChipObservation,
    CorporateActionRecord,
    ExecutionDayBatch,
    FundamentalRecord,
    IndustryMembershipRecord,
    PITStore,
    PreparedChipRecord,
)
from cyq_game.data.registry import (
    DataActivationError,
    DataExecutionAuthorization,
    DataOperation,
    InputBinding,
)
from cyq_game.domain import Bar
from cyq_game.execution.simulator import MarketRule
from cyq_game.portfolio.sizing import CalibratedForecast

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_VERIFIED_INVENTORIES: dict[tuple[str, str], tuple[Path, ...]] = {}

_BAR_COLUMNS = """
symbol, trade_date, open, high, low, close, volume, amount,
circulating_shares, available_at, trade_status, is_st,
up_limit_price, down_limit_price, hard_valid, invalid_reasons,
snapshot_id, market_rule_id, market_rule_valid, limit_pct,
industry, industry_source, source_notice_date,
corporate_action_ids, corporate_action_source,
corporate_action_available_date, corporate_action_blocking,
corporate_action_problems, corporate_action_count, share_multiplier, cash_per_share,
rights_ratio, rights_price
"""

_PREPARED_CHIP_COLUMNS = """
symbol, trade_date, available_at, daily_snapshot_id, minute_snapshot_id,
strict_sample, invalid_reason, state_quality,
profit_ratio, trapped_ratio, average_cost, p01, p10, p50, p90, p99,
asr, space20, ckdp, ckdw, cbw,
cyqk_open_pre, cyqk_high_pre, cyqk_low_pre, cyqk_close_pre,
cyc5, cyc13, cyc34, cys13, cys34, rpy2, concentration_20,
base_retention, peaks_json, priors_json,
opening_30m_return, closing_30m_return, close_vs_vwap,
last_hour_volume_share, realized_volatility
"""

_DAILY_CACHE_COLUMNS = f"""
{_BAR_COLUMNS},
bar_valid, trading_state_valid, float_valid
"""


def _bar_provenance_from_row(
    row: Mapping[str, Any],
    *,
    available_at_text: str | None = None,
) -> dict[str, Any]:
    return {
        "bar_available_at": available_at_text or _aware_local(row["available_at"]).isoformat(),
        "bar_snapshot_id": _optional_text(row.get("snapshot_id")),
        "hard_valid": bool(row["hard_valid"]),
        "invalid_reasons": _parse_text_list(row.get("invalid_reasons")),
    }


class PITBDailyStore(PITStore):
    """Read the immutable PIT-B dataset without copying nine million rows to SQLite.

    SQLite is retained only as a small append-only metadata and experiment store.
    All market facts are read directly from the inventory-frozen Parquet files.
    """

    def __init__(
        self,
        metadata_path: str | Path,
        *,
        binding: InputBinding,
        minute_binding: InputBinding | None = None,
        chip_feature_binding: InputBinding | None = None,
        authorization: DataExecutionAuthorization,
    ) -> None:
        super().__init__(metadata_path)
        if binding.role != "daily_pit_b":
            raise DataActivationError("PIT-B runtime requires the daily_pit_b input role")
        if not authorization.hard_valid:
            raise DataActivationError("hard_valid=false cannot activate the PIT-B runtime")
        if authorization.operation not in {
            DataOperation.BACKTEST,
            DataOperation.ROBUSTNESS,
            DataOperation.STATE_GENERATION,
        }:
            raise DataActivationError(
                f"{authorization.operation.value} cannot activate the PIT-B strategy runtime"
            )
        if binding.inventory_manifest is None or binding.inventory_sha256 is None:
            raise DataActivationError("daily_pit_b must be frozen by an inventory manifest")
        if minute_binding is not None:
            if minute_binding.role != "minute_pit_b":
                raise DataActivationError("minute runtime input must use the minute_pit_b role")
            if minute_binding.inventory_manifest is None or minute_binding.inventory_sha256 is None:
                raise DataActivationError("minute_pit_b must be frozen by an inventory manifest")
        if chip_feature_binding is not None:
            if chip_feature_binding.role != "chip_state_features":
                raise DataActivationError(
                    "prepared chip runtime input must use the chip_state_features role"
                )
            if (
                chip_feature_binding.inventory_manifest is None
                or chip_feature_binding.inventory_sha256 is None
            ):
                raise DataActivationError(
                    "chip_state_features must be frozen by an inventory manifest"
                )
        self.binding = binding
        self.minute_binding = minute_binding
        self.chip_feature_binding = chip_feature_binding
        self.authorization = authorization
        self._parquet_files: tuple[Path, ...] = ()
        self._minute_daily_files: tuple[Path, ...] = ()
        self._minute_execution_files: tuple[Path, ...] = ()
        self._chip_feature_files: tuple[Path, ...] = ()
        self._duckdb: duckdb.DuckDBPyConnection | None = None
        self._daily_cache_month: tuple[int, int] | None = None
        self._minute_cache_month: tuple[int, int] | None = None
        self._chip_cache_month: tuple[int, int] | None = None
        self._strict_day_cache: dict[
            tuple[date, datetime, tuple[str, ...] | None], dict[str, dict[str, Any]]
        ] = {}
        self._execution_day_cache: dict[
            tuple[date, datetime, tuple[str, ...] | None], dict[str, dict[str, Any]]
        ] = {}
        self._execution_bar_cache: dict[
            tuple[date, datetime, tuple[str, ...] | None], dict[str, Bar]
        ] = {}
        self._action_day_cache: dict[
            tuple[date, datetime], dict[str, tuple[CorporateActionRecord, ...]]
        ] = {}

    @property
    def decision_timezone(self) -> tzinfo:
        return _SHANGHAI

    @property
    def supports_native_forecast(self) -> bool:
        return True

    @property
    def requires_intraday_evidence(self) -> bool:
        return self.minute_binding is not None

    @property
    def supports_fundamental_signals(self) -> bool:
        # The frozen PIT-B v2 activation intentionally contains no fundamental
        # domain.  Discovery-only snapshots must not leak into state or orders.
        return False

    @property
    def supports_precomputed_chip_features(self) -> bool:
        return self.chip_feature_binding is not None

    def source_digest(self) -> str:
        inventory_sha256 = self.binding.inventory_sha256
        if inventory_sha256 is None:  # guarded by __init__; keeps the type fail-closed
            raise DataActivationError("PIT-B inventory digest is unavailable")
        digests = [inventory_sha256]
        if self.minute_binding is not None:
            minute_digest = self.minute_binding.inventory_sha256
            if minute_digest is None:
                raise DataActivationError("minute PIT-B inventory digest is unavailable")
            digests.append(minute_digest)
        if self.chip_feature_binding is not None:
            chip_digest = self.chip_feature_binding.inventory_sha256
            if chip_digest is None:
                raise DataActivationError("prepared chip inventory digest is unavailable")
            digests.append(chip_digest)
        if len(digests) == 1:
            return digests[0]
        return hashlib.sha256(":".join(digests).encode()).hexdigest()

    def initialize(self) -> None:
        verification_cache_dir = self.path.parent / ".inventory_verification"
        self._parquet_files = _verify_inventory_once(
            self.binding,
            cache_dir=verification_cache_dir,
        )
        if self.minute_binding is not None:
            minute_files = _verify_inventory_once(
                self.minute_binding,
                cache_dir=verification_cache_dir,
            )
            root = self.minute_binding.path.resolve()
            self._minute_daily_files = tuple(
                path for path in minute_files if path.relative_to(root).parts[0] == "daily"
            )
            self._minute_execution_files = tuple(
                path for path in minute_files if path.relative_to(root).parts[0] == "execution_5m"
            )
            if not self._minute_daily_files or not self._minute_execution_files:
                raise DataActivationError(
                    "minute_pit_b inventory must freeze daily and execution_5m Parquet files"
                )
        if self.chip_feature_binding is not None:
            self._chip_feature_files = _verify_inventory_once(
                self.chip_feature_binding,
                cache_dir=verification_cache_dir,
            )
        super().initialize()
        now = datetime.now(UTC)
        self.bind_input_manifest(
            registry_id=self.authorization.registry_id,
            registry_sha256=self.authorization.registry_sha256,
            input_manifest_id=self.authorization.input_manifest_id,
            input_manifest_sha256=self.authorization.input_manifest_sha256,
            purpose=self.authorization.purpose.value,
            hard_valid=self.authorization.hard_valid,
            run_id=f"runtime:{self.authorization.input_manifest_id}",
            bound_at=now,
        )
        self.complete_input_manifest(
            input_manifest_id=self.authorization.input_manifest_id,
            input_manifest_sha256=self.authorization.input_manifest_sha256,
            completed_at=now,
        )
        self._connection()

    def close(self) -> None:
        if self._duckdb is not None:
            self._duckdb.close()
            self._duckdb = None
        self._daily_cache_month = None
        self._minute_cache_month = None
        self._chip_cache_month = None

    def symbols(self) -> list[str]:
        rows = self._query("SELECT DISTINCT symbol FROM pit_b_daily ORDER BY symbol")
        return [str(row["symbol"]) for row in rows]

    def date_bounds(self) -> tuple[date, date]:
        rows = self._query(
            "SELECT MIN(trade_date) AS start_date, MAX(trade_date) AS end_date FROM pit_b_daily"
        )
        if not rows or rows[0]["start_date"] is None or rows[0]["end_date"] is None:
            raise ValueError("PIT-B dataset contains no market bars")
        return _as_date(rows[0]["start_date"]), _as_date(rows[0]["end_date"])

    def trading_dates_as_of(
        self,
        start: date,
        end: date,
        decision_at: datetime,
        symbols: Sequence[str] | None = None,
    ) -> list[date]:
        local_decision = _local_naive(decision_at)
        parameters: list[Any] = [start, end, local_decision]
        symbol_filter = ""
        if symbols:
            placeholders = ",".join("?" for _ in symbols)
            symbol_filter = f" AND symbol IN ({placeholders})"
            parameters.extend(symbols)
        rows = self._query(
            f"""
            SELECT DISTINCT trade_date
            FROM pit_b_daily
            WHERE trade_date BETWEEN ? AND ?
              AND available_at <= ?
              AND bar_valid = TRUE
              {symbol_filter}
            ORDER BY trade_date
            """,
            parameters,
        )
        return [_as_date(row["trade_date"]) for row in rows]

    def bars_as_of(
        self,
        symbol: str,
        start: date,
        end: date,
        decision_at: datetime,
    ) -> list[Bar]:
        rows = self._query(
            f"""
            SELECT {_BAR_COLUMNS}
            FROM pit_b_daily
            WHERE symbol = ? AND trade_date BETWEEN ? AND ?
              AND available_at <= ? AND hard_valid = TRUE
            ORDER BY trade_date, available_at
            """,
            [symbol, start, end, _local_naive(decision_at)],
        )
        latest = {_as_date(row["trade_date"]): row for row in rows}
        return [_row_to_bar(latest[item]) for item in sorted(latest)]

    def strict_bars_for_day(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, Bar]:
        if not symbols:
            return {}
        rows = self._day_rows(
            strict=True,
            trade_date=trade_date,
            decision_at=decision_at,
            symbols=symbols,
        )
        requested = set(symbols)
        key = (trade_date, _local_naive(decision_at), _query_scope(symbols))
        execution_bars = self._execution_bar_cache.get(key)
        if execution_bars is not None:
            return {
                symbol: execution_bars[symbol]
                for symbol in rows
                if symbol in requested and symbol in execution_bars
            }
        return {symbol: _row_to_bar(row) for symbol, row in rows.items() if symbol in requested}

    def execution_bars_for_day(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, Bar]:
        if not symbols:
            return {}
        rows = self._day_rows(
            strict=False,
            trade_date=trade_date,
            decision_at=decision_at,
            symbols=symbols,
        )
        requested = set(symbols)
        key = (trade_date, _local_naive(decision_at), _query_scope(symbols))
        bars = self._execution_bar_cache.get(key)
        if bars is None:
            bars = {symbol: _row_to_bar(row) for symbol, row in rows.items()}
            self._execution_bar_cache.clear()
            self._execution_bar_cache[key] = bars
        return {symbol: bar for symbol, bar in bars.items() if symbol in requested}

    def chip_observations_for_day(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, ChipObservation]:
        if not self._minute_daily_files or not symbols:
            return {}
        requested = set(symbols)
        self._prepare_minute_month(trade_date)
        use_symbol_filter = len(requested) <= 128
        symbol_filter = ""
        parameters: list[Any] = []
        if use_symbol_filter:
            placeholders = ",".join("?" for _ in requested)
            symbol_filter = f"symbol IN ({placeholders}) AND"
            parameters.extend(requested)
        parameters.extend((trade_date, _local_naive(decision_at)))
        rows = self._query(
            f"""
            SELECT symbol, trade_date, chip_prices, chip_volumes, available_at,
                   source, snapshot_id, hard_valid, opening_30m_return,
                   closing_30m_return, close_vs_vwap, last_hour_volume_share,
                   realized_volatility
            FROM pit_b_minute_month
            WHERE {symbol_filter} trade_date = ?
              AND available_at <= ? AND hard_valid = TRUE
            QUALIFY ROW_NUMBER() OVER (
              PARTITION BY symbol, trade_date ORDER BY available_at DESC
            ) = 1
            """,
            parameters,
        )
        return {
            str(row["symbol"]): ChipObservation(
                symbol=str(row["symbol"]),
                trade_date=_as_date(row["trade_date"]),
                prices=tuple(float(value) for value in row["chip_prices"]),
                volumes=tuple(float(value) for value in row["chip_volumes"]),
                available_at=_aware_local(row["available_at"]),
                source=str(row["source"]),
                snapshot_id=str(row["snapshot_id"]),
                hard_valid=bool(row["hard_valid"]),
                opening_30m_return=float(row["opening_30m_return"]),
                closing_30m_return=float(row["closing_30m_return"]),
                close_vs_vwap=float(row["close_vs_vwap"]),
                last_hour_volume_share=float(row["last_hour_volume_share"]),
                realized_volatility=float(row["realized_volatility"]),
            )
            for row in rows
            if str(row["symbol"]) in requested
        }

    def prepared_chip_features_for_day(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, PreparedChipRecord]:
        if not self._chip_feature_files or not symbols:
            return {}
        requested = set(symbols)
        self._prepare_chip_month(trade_date)
        parameters: list[Any] = []
        symbol_filter = ""
        if len(requested) <= 128:
            placeholders = ",".join("?" for _ in requested)
            symbol_filter = f"symbol IN ({placeholders}) AND"
            parameters.extend(requested)
        parameters.extend((trade_date, _local_naive(decision_at)))
        rows = self._query(
            f"""
            SELECT {_PREPARED_CHIP_COLUMNS}
            FROM pit_b_chip_features_month
            WHERE {symbol_filter} trade_date = ? AND available_at <= ?
              AND strict_sample = TRUE
              AND peaks_json IS NOT NULL AND priors_json IS NOT NULL
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY symbol, trade_date
                ORDER BY available_at DESC, minute_snapshot_id DESC
            ) = 1
            """,
            parameters,
        )
        return {
            str(row["symbol"]): _row_to_prepared_chip(row)
            for row in rows
            if str(row["symbol"]) in requested
        }

    def _prepare_chip_month(self, trade_date: date) -> None:
        """Load one chip-feature month once instead of rescanning yearly Parquet daily."""

        month = (trade_date.year, trade_date.month)
        if self._chip_cache_month == month:
            return
        month_start = trade_date.replace(day=1)
        if trade_date.month == 12:
            month_end = date(trade_date.year + 1, 1, 1)
        else:
            month_end = date(trade_date.year, trade_date.month + 1, 1)
        self._connection().execute(
            f"""
            CREATE OR REPLACE TEMP TABLE pit_b_chip_features_month AS
            SELECT {_PREPARED_CHIP_COLUMNS}
            FROM pit_b_chip_features
            WHERE trade_date >= ? AND trade_date < ?
            """,
            [month_start, month_end],
        )
        self._connection().execute(
            "CREATE INDEX pit_b_chip_features_month_date "
            "ON pit_b_chip_features_month(trade_date)"
        )
        self._chip_cache_month = month

    def _prepare_minute_month(self, trade_date: date) -> None:
        month = (trade_date.year, trade_date.month)
        if self._minute_cache_month == month:
            return
        month_start = trade_date.replace(day=1)
        if trade_date.month == 12:
            month_end = date(trade_date.year + 1, 1, 1)
        else:
            month_end = date(trade_date.year, trade_date.month + 1, 1)
        self._connection().execute(
            """
            CREATE OR REPLACE TEMP TABLE pit_b_minute_month AS
            SELECT symbol, trade_date, chip_prices, chip_volumes, available_at,
                   source, snapshot_id, hard_valid, opening_30m_return,
                   closing_30m_return, close_vs_vwap, last_hour_volume_share,
                   realized_volatility
            FROM pit_b_minute_daily
            WHERE trade_date >= ? AND trade_date < ? AND hard_valid = TRUE
            """,
            [month_start, month_end],
        )
        self._connection().execute(
            "CREATE INDEX pit_b_minute_month_date ON pit_b_minute_month(trade_date)"
        )
        self._minute_cache_month = month

    def execution_windows_for_day(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, list[Bar]]:
        if not self._minute_execution_files:
            return super().execution_windows_for_day(symbols, trade_date, decision_at)
        if not symbols:
            return {}
        placeholders = ",".join("?" for _ in symbols)
        rows = self._query(
            f"""
            SELECT symbol, trade_date, open, high, low, close, volume, amount,
                   circulating_shares, available_at, trade_status, is_st,
                   up_limit_price, down_limit_price
            FROM pit_b_execution_5m
            WHERE symbol IN ({placeholders}) AND trade_date = ?
              AND available_at <= ? AND hard_valid = TRUE
            ORDER BY symbol, window_index
            """,
            [*symbols, trade_date, _local_naive(decision_at)],
        )
        grouped: dict[str, list[Bar]] = {}
        for row in rows:
            grouped.setdefault(str(row["symbol"]), []).append(_row_to_bar(row))
        return grouped

    def execution_batch_for_day(
        self,
        symbol_boards: Mapping[str, str],
        trade_date: date,
        decision_at: datetime,
    ) -> ExecutionDayBatch:
        """Resolve execution bars, validity and rules in one minute-Parquet scan."""

        if not self._minute_execution_files:
            return super().execution_batch_for_day(symbol_boards, trade_date, decision_at)
        symbols = tuple(symbol_boards)
        if not symbols:
            return ExecutionDayBatch({}, {}, frozenset(), frozenset(), {})
        placeholders = ",".join("?" for _ in symbols)
        rows = self._query(
            f"""
            SELECT symbol, trade_date, window_index, open, high, low, close, volume, amount,
                   circulating_shares, available_at, trade_status, is_st,
                   up_limit_price, down_limit_price, market_rule_id,
                   market_rule_valid, limit_pct, hard_valid
            FROM pit_b_execution_5m
            WHERE symbol IN ({placeholders}) AND trade_date = ? AND available_at <= ?
            ORDER BY symbol, window_index
            """,
            [*symbols, trade_date, _local_naive(decision_at)],
        )
        grouped: dict[str, list[Bar]] = {}
        rules: dict[str, MarketRule] = {}
        observed: set[str] = set()
        valid: set[str] = set()
        invalid_at: dict[str, datetime] = {}
        for row in rows:
            symbol = str(row["symbol"])
            observed.add(symbol)
            rule = _market_rule_from_row(row, trade_date)
            if not bool(row["hard_valid"]) or not rule.known:
                row_available_at = _aware_local(row["available_at"])
                invalid_at.setdefault(symbol, row_available_at)
                continue
            grouped.setdefault(symbol, []).append(_row_to_bar(row))
            rules[symbol] = rule
            valid.add(symbol)
        return ExecutionDayBatch(
            windows={symbol: tuple(bars) for symbol, bars in grouped.items()},
            rules=rules,
            observed_symbols=frozenset(observed),
            valid_symbols=frozenset(valid),
            invalid_at=invalid_at,
        )

    def bar_provenance(
        self,
        symbol: str,
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, Any]:
        local_decision = _local_naive(decision_at)
        row = self._cached_day_row(symbol, trade_date, local_decision)
        if row is None:
            rows = self._query(
                f"""
                SELECT {_BAR_COLUMNS}
                FROM pit_b_daily
                WHERE symbol = ? AND trade_date = ? AND available_at <= ?
                ORDER BY available_at DESC LIMIT 1
                """,
                [symbol, trade_date, local_decision],
            )
            row = rows[0] if rows else None
        if row is None:
            return {}
        return _bar_provenance_from_row(row)

    def bar_provenances_for_day(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, dict[str, Any]]:
        """Reuse the loaded daily snapshot instead of resolving each symbol."""

        rows = self._day_rows(
            strict=False,
            trade_date=trade_date,
            decision_at=decision_at,
            symbols=symbols,
        )
        available_at_cache: dict[Any, str] = {}
        result: dict[str, dict[str, Any]] = {}
        for symbol in symbols:
            row = rows.get(symbol)
            if row is None:
                continue
            raw_available_at = row["available_at"]
            available_at_text = available_at_cache.get(raw_available_at)
            if available_at_text is None:
                available_at_text = _aware_local(raw_available_at).isoformat()
                available_at_cache[raw_available_at] = available_at_text
            result[symbol] = _bar_provenance_from_row(
                row,
                available_at_text=available_at_text,
            )
        return result

    def rule_as_of(
        self,
        symbol: str,
        board: str,
        trade_date: date,
        decision_at: datetime,
    ) -> MarketRule:
        del board
        local_decision = _local_naive(decision_at)
        if self._minute_execution_files:
            minute_rows = self._query(
                """
                SELECT market_rule_id, market_rule_valid, limit_pct
                FROM pit_b_execution_5m
                WHERE symbol = ? AND trade_date = ? AND available_at <= ?
                ORDER BY available_at DESC LIMIT 1
                """,
                [symbol, trade_date, local_decision],
            )
            if minute_rows:
                minute_rule = _market_rule_from_row(minute_rows[0], trade_date)
                if minute_rule.known:
                    return minute_rule
        row = self._cached_day_row(symbol, trade_date, local_decision)
        if row is None:
            rows = self._query(
                f"""
                SELECT {_BAR_COLUMNS}
                FROM pit_b_daily
                WHERE symbol = ? AND trade_date = ? AND available_at <= ?
                ORDER BY available_at DESC LIMIT 1
                """,
                [symbol, trade_date, local_decision],
            )
            row = rows[0] if rows else None
        return _market_rule_from_row(row, trade_date)

    def rules_as_of(
        self,
        symbol_boards: Mapping[str, str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, MarketRule]:
        """Resolve all daily rules from the already cached daily PIT snapshot."""

        symbols = tuple(symbol_boards)
        if not symbols:
            return {}
        daily_rows = self._day_rows(
            strict=False,
            trade_date=trade_date,
            decision_at=decision_at,
            symbols=symbols,
        )
        return {
            symbol: _market_rule_from_row(daily_rows.get(symbol), trade_date) for symbol in symbols
        }

    def corporate_actions_for_day(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, list[CorporateActionRecord]]:
        requested = set(symbols)
        return {
            symbol: list(records)
            for symbol, records in self._corporate_actions_for_day(trade_date, decision_at).items()
            if symbol in requested
        }

    def fundamental_as_of(
        self,
        symbol: str,
        trade_date: date,
        decision_at: datetime,
    ) -> FundamentalRecord | None:
        # PIT-B v2 has no frozen fundamental domain; do not fall through to SQLite.
        del symbol, trade_date, decision_at
        return None

    def fundamentals_as_of(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, FundamentalRecord]:
        del symbols, trade_date, decision_at
        return {}

    def corporate_actions_as_of(
        self,
        symbol: str,
        start: date,
        end: date,
        decision_at: datetime,
    ) -> list[CorporateActionRecord]:
        result: list[CorporateActionRecord] = []
        current = start
        while current <= end:
            grouped = self._corporate_actions_for_day(current, decision_at)
            result.extend(grouped.get(symbol, ()))
            current = date.fromordinal(current.toordinal() + 1)
        return result

    def industry_memberships_as_of(
        self,
        symbols: Sequence[str],
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, IndustryMembershipRecord]:
        strict_rows = self._day_rows(
            strict=True,
            trade_date=trade_date,
            decision_at=decision_at,
            symbols=symbols,
        )
        result: dict[str, IndustryMembershipRecord] = {}
        for symbol in symbols:
            row = strict_rows.get(symbol)
            industry = _optional_text(row.get("industry")) if row else None
            if row is None or industry is None:
                continue
            available_at = _aware_local(row["available_at"])
            result[symbol] = IndustryMembershipRecord(
                symbol=symbol,
                industry=industry,
                effective_from=trade_date,
                effective_to=trade_date,
                available_at=available_at,
                source=_optional_text(row.get("industry_source")) or "PIT_B_DAILY",
                snapshot_id=_optional_text(row.get("snapshot_id")) or "UNKNOWN",
                revision_id="1",
                run_id=self.authorization.input_manifest_id,
            )
        return result

    def calibrate_forecast(
        self,
        symbols: Sequence[str],
        train_dates: set[date],
        decision_at: datetime,
    ) -> CalibratedForecast:
        """Compute the existing five-session forecast directly in DuckDB."""

        if not symbols or not train_dates:
            return CalibratedForecast(0.5, 1.0, 1.0, 0, True, 0.20)
        symbol_placeholders = ",".join("?" for _ in symbols)
        date_placeholders = ",".join("?" for _ in train_dates)
        ordered_dates = sorted(train_dates)
        rows = self._query(
            f"""
            WITH selected AS (
              SELECT symbol, trade_date, close,
                     LEAD(close, 5) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                     ) AS close_5
              FROM pit_b_daily
              WHERE symbol IN ({symbol_placeholders})
                AND trade_date IN ({date_placeholders})
                AND available_at <= ?
                AND hard_valid = TRUE
            )
            SELECT (close_5 / close - 1.0) / 0.05 AS outcome
            FROM selected
            WHERE close_5 IS NOT NULL AND close > 0
            """,
            [*symbols, *ordered_dates, _local_naive(decision_at)],
        )
        outcomes = [float(row["outcome"]) for row in rows if row["outcome"] is not None]
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

    def calibrate_forecasts(
        self,
        symbols: Sequence[str],
        train_dates: set[date],
        decision_at: datetime,
    ) -> dict[str, CalibratedForecast]:
        """Compute symbol-level forecasts with one grouped DuckDB scan per fold."""

        fallback = CalibratedForecast(0.5, 1.0, 1.0, 0, True, 0.20)
        result = {symbol: fallback for symbol in symbols}
        if not symbols or not train_dates:
            return result
        symbol_placeholders = ",".join("?" for _ in symbols)
        date_placeholders = ",".join("?" for _ in train_dates)
        ordered_dates = sorted(train_dates)
        rows = self._query(
            f"""
            WITH latest AS (
              SELECT symbol, trade_date, close
              FROM pit_b_daily
              WHERE symbol IN ({symbol_placeholders})
                AND trade_date IN ({date_placeholders})
                AND available_at <= ?
                AND hard_valid = TRUE
              QUALIFY ROW_NUMBER() OVER (
                PARTITION BY symbol, trade_date ORDER BY available_at DESC
              ) = 1
            ), selected AS (
              SELECT symbol, trade_date, close,
                     LEAD(close, 5) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                     ) AS close_5
              FROM latest
            ), outcomes AS (
              SELECT symbol, (close_5 / close - 1.0) / 0.05 AS outcome
              FROM selected
              WHERE close_5 IS NOT NULL AND close > 0
            )
            SELECT symbol,
                   COUNT(*) AS sample_size,
                   COUNT(*) FILTER (WHERE outcome > 0) AS win_count,
                   AVG(outcome) FILTER (WHERE outcome > 0) AS average_win_r,
                   AVG(-outcome) FILTER (WHERE outcome < 0) AS average_loss_r
            FROM outcomes
            GROUP BY symbol
            """,
            [*symbols, *ordered_dates, _local_naive(decision_at)],
        )
        for row in rows:
            symbol = str(row["symbol"])
            sample_size = int(row["sample_size"])
            average_win = _optional_float(row["average_win_r"])
            average_loss = _optional_float(row["average_loss_r"])
            if sample_size <= 0 or average_win is None or average_loss is None:
                result[symbol] = CalibratedForecast(0.5, 1.0, 1.0, sample_size, True, 0.20)
                continue
            probability = min(0.99, max(0.01, int(row["win_count"]) / sample_size))
            result[symbol] = CalibratedForecast(
                win_probability=probability,
                average_win_r=max(0.05, average_win),
                average_loss_r=max(0.05, average_loss),
                sample_size=sample_size,
                out_of_sample=True,
                calibration_error=min(0.20, abs(probability - 0.5) * 0.25),
            )
        return result

    def _day_rows(
        self,
        *,
        strict: bool,
        trade_date: date,
        decision_at: datetime,
        symbols: Sequence[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        local_decision = _local_naive(decision_at)
        scope = _query_scope(symbols)
        key = (trade_date, local_decision, scope)
        cache = self._strict_day_cache if strict else self._execution_day_cache
        if key in cache:
            return cache[key]
        if strict and key in self._execution_day_cache:
            result = {
                symbol: row
                for symbol, row in self._execution_day_cache[key].items()
                if bool(row["hard_valid"])
            }
            self._strict_day_cache.clear()
            self._strict_day_cache[key] = result
            return result
        self._prepare_daily_month(trade_date)
        validity = (
            "hard_valid = TRUE"
            if strict
            else """
                bar_valid = TRUE
                AND trading_state_valid = TRUE
                AND float_valid = TRUE
                AND market_rule_valid = TRUE
                AND trade_status IS NOT NULL
            """
        )
        parameters: list[Any] = []
        symbol_filter = ""
        if scope is not None:
            placeholders = ",".join("?" for _ in scope)
            symbol_filter = f"symbol IN ({placeholders}) AND"
            parameters.extend(scope)
        parameters.extend((trade_date, local_decision))
        rows = self._query(
            f"""
            SELECT {_BAR_COLUMNS}
            FROM pit_b_daily_month
            WHERE {symbol_filter} trade_date = ? AND available_at <= ? AND {validity}
            QUALIFY ROW_NUMBER() OVER (
              PARTITION BY symbol ORDER BY available_at DESC
            ) = 1
            """,
            parameters,
        )
        result = {str(row["symbol"]): row for row in rows}
        cache.clear()
        cache[key] = result
        return result

    def _cached_day_row(
        self,
        symbol: str,
        trade_date: date,
        local_decision: datetime,
    ) -> dict[str, Any] | None:
        for cache in (self._strict_day_cache, self._execution_day_cache):
            for (cached_date, cached_decision, scope), rows in cache.items():
                if (
                    cached_date == trade_date
                    and cached_decision == local_decision
                    and (scope is None or symbol in scope)
                ):
                    row = rows.get(symbol)
                    if row is not None:
                        return row
        return None

    def _prepare_daily_month(self, trade_date: date) -> None:
        """Materialize and index a daily month once for all same-day PIT lookups."""

        month = (trade_date.year, trade_date.month)
        if self._daily_cache_month == month:
            return
        month_start = trade_date.replace(day=1)
        if trade_date.month == 12:
            month_end = date(trade_date.year + 1, 1, 1)
        else:
            month_end = date(trade_date.year, trade_date.month + 1, 1)
        connection = self._connection()
        connection.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE pit_b_daily_month AS
            SELECT {_DAILY_CACHE_COLUMNS}
            FROM pit_b_daily
            WHERE trade_date >= ? AND trade_date < ?
            """,
            [month_start, month_end],
        )
        connection.execute(
            "CREATE INDEX pit_b_daily_month_date ON pit_b_daily_month(trade_date)"
        )
        self._daily_cache_month = month

    def _corporate_actions_for_day(
        self,
        trade_date: date,
        decision_at: datetime,
    ) -> dict[str, tuple[CorporateActionRecord, ...]]:
        local_decision = _local_naive(decision_at)
        key = (trade_date, local_decision)
        if key in self._action_day_cache:
            return self._action_day_cache[key]
        cached_daily = next(
            (
                rows
                for (cached_date, _, _), rows in self._execution_day_cache.items()
                if cached_date == trade_date
            ),
            None,
        )
        if cached_daily is not None:
            rows = [
                row
                for row in cached_daily.values()
                if int(row.get("corporate_action_count") or 0) > 0
                and not bool(row.get("corporate_action_blocking"))
                and row.get("corporate_action_available_date") is not None
                and _action_available_at(row) <= decision_at
            ]
        else:
            # A caller may ask about an action before the end-of-day bar is
            # available. Keep that PIT query path, while the daily engine reuses
            # its already loaded execution snapshot.
            rows = self._query(
                f"""
                SELECT {_BAR_COLUMNS}
                FROM pit_b_daily
                WHERE trade_date = ?
                  AND corporate_action_count > 0
                  AND corporate_action_blocking = FALSE
                  AND corporate_action_available_date IS NOT NULL
                  AND CAST(corporate_action_available_date AS TIMESTAMP)
                        + INTERVAL 15 HOUR <= ?
                QUALIFY ROW_NUMBER() OVER (
                  PARTITION BY symbol ORDER BY available_at DESC
                ) = 1
                """,
                [trade_date, local_decision],
            )
        grouped: dict[str, list[CorporateActionRecord]] = {}
        for row in rows:
            symbol = str(row["symbol"])
            available_at = _action_available_at(row)
            snapshot_id = _optional_text(row.get("snapshot_id")) or "UNKNOWN"
            source = _optional_text(row.get("corporate_action_source")) or "CNINFO"
            action_ids = _parse_text_list(row.get("corporate_action_ids"))
            base_id = action_ids[0] if action_ids else f"pit-b:{symbol}:{trade_date.isoformat()}"
            records: list[CorporateActionRecord] = []
            multiplier = _optional_float(row.get("share_multiplier"))
            if multiplier is not None and abs(multiplier - 1.0) > 1e-12:
                records.append(
                    self._action_record(
                        action_id=f"{base_id}:split",
                        symbol=symbol,
                        action_type="SPLIT",
                        trade_date=trade_date,
                        available_at=available_at,
                        source=source,
                        snapshot_id=snapshot_id,
                        ratio=multiplier,
                    )
                )
            cash = _optional_float(row.get("cash_per_share"))
            if cash is not None and cash > 0:
                records.append(
                    self._action_record(
                        action_id=f"{base_id}:cash",
                        symbol=symbol,
                        action_type="CASH_DIVIDEND",
                        trade_date=trade_date,
                        available_at=available_at,
                        source=source,
                        snapshot_id=snapshot_id,
                        cash_per_share=cash,
                    )
                )
            rights = _optional_float(row.get("rights_ratio"))
            if rights is not None and rights > 0:
                records.append(
                    self._action_record(
                        action_id=f"{base_id}:rights",
                        symbol=symbol,
                        action_type="RIGHTS",
                        trade_date=trade_date,
                        available_at=available_at,
                        source=source,
                        snapshot_id=snapshot_id,
                        ratio=rights,
                        issue_price=_optional_float(row.get("rights_price")),
                    )
                )
            if records:
                grouped[symbol] = records
        result = {symbol: tuple(records) for symbol, records in grouped.items()}
        self._action_day_cache.clear()
        self._action_day_cache[key] = result
        return result

    def _action_record(
        self,
        *,
        action_id: str,
        symbol: str,
        action_type: str,
        trade_date: date,
        available_at: datetime,
        source: str,
        snapshot_id: str,
        ratio: float | None = None,
        cash_per_share: float | None = None,
        issue_price: float | None = None,
    ) -> CorporateActionRecord:
        effective_from = datetime.combine(trade_date, time.min, tzinfo=_SHANGHAI)
        return CorporateActionRecord(
            action_id=action_id,
            symbol=symbol,
            action_type=action_type,
            ex_date=trade_date,
            event_time=available_at,
            available_at=available_at,
            effective_from=effective_from,
            source=source,
            snapshot_id=snapshot_id,
            revision_id="1",
            run_id=self.authorization.input_manifest_id,
            ratio=ratio,
            cash_per_share=cash_per_share,
            issue_price=issue_price,
        )

    def _connection(self) -> duckdb.DuckDBPyConnection:
        if not self._parquet_files:
            raise RuntimeError("PIT-B store must be initialized before use")
        if self._duckdb is None:
            connection = duckdb.connect(database=":memory:")
            read_parquet = cast(Any, connection.read_parquet)
            read_parquet(
                [str(path) for path in self._parquet_files],
                hive_partitioning=False,
            ).create_view("pit_b_daily")
            if self._minute_daily_files:
                read_parquet(
                    [str(path) for path in self._minute_daily_files],
                    hive_partitioning=False,
                ).create_view("pit_b_minute_daily")
            if self._minute_execution_files:
                read_parquet(
                    [str(path) for path in self._minute_execution_files],
                    hive_partitioning=False,
                ).create_view("pit_b_execution_5m")
            if self._chip_feature_files:
                read_parquet(
                    [str(path) for path in self._chip_feature_files],
                    hive_partitioning=False,
                ).create_view("pit_b_chip_features")
            self._duckdb = connection
        return self._duckdb

    def _query(
        self,
        sql: str,
        parameters: Sequence[Any] | None = None,
    ) -> list[dict[str, Any]]:
        cursor = self._connection().execute(sql, parameters or [])
        if cursor.description is None:
            raise RuntimeError("PIT-B query returned no result schema")
        columns = [str(item[0]) for item in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _verify_inventory_once(
    binding: InputBinding,
    *,
    cache_dir: Path | None = None,
) -> tuple[Path, ...]:
    inventory_path = binding.inventory_manifest
    inventory_digest = binding.inventory_sha256
    if inventory_path is None or inventory_digest is None:
        raise DataActivationError("PIT-B inventory identity is incomplete")
    key = (str(inventory_path), inventory_digest)
    cached = _VERIFIED_INVENTORIES.get(key)
    if cached is not None:
        return cached
    if _sha256_file(inventory_path) != inventory_digest:
        raise DataActivationError("PIT-B inventory manifest hash mismatch")
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise DataActivationError("PIT-B inventory manifest is malformed")
    root = binding.path.resolve()
    manifest_root = Path(str(payload.get("root", ""))).expanduser().resolve()
    if manifest_root != root:
        raise DataActivationError("PIT-B inventory root does not match the bound path")
    persistent_cache = _read_verification_cache(cache_dir, inventory_digest)
    cached_files = persistent_cache.get("files", {}) if persistent_cache else {}
    verified: list[Path] = []
    verified_metadata: dict[str, dict[str, Any]] = {}
    for item in payload["files"]:
        if not isinstance(item, dict):
            raise DataActivationError("PIT-B inventory contains a malformed file record")
        relative = item.get("path")
        expected_size = item.get("size")
        expected_digest = item.get("sha256")
        if not isinstance(relative, str) or not relative:
            raise DataActivationError("PIT-B inventory file path is missing")
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise DataActivationError("PIT-B inventory path escapes the bound root") from exc
        if not path.is_file():
            raise DataActivationError(f"PIT-B frozen file is missing: {path}")
        stat = path.stat()
        if stat.st_size != expected_size:
            raise DataActivationError(f"PIT-B frozen file size mismatch: {path}")
        if not isinstance(expected_digest, str):
            raise DataActivationError(f"PIT-B frozen file digest is missing: {path}")
        metadata = _verification_metadata(path, stat, expected_digest)
        cached_metadata = cached_files.get(relative) if isinstance(cached_files, dict) else None
        if cached_metadata != metadata and _sha256_file(path) != expected_digest:
            raise DataActivationError(f"PIT-B frozen file hash mismatch: {path}")
        verified.append(path)
        verified_metadata[relative] = metadata
    if not verified:
        raise DataActivationError("PIT-B inventory contains no Parquet files")
    result = tuple(verified)
    _write_verification_cache(cache_dir, inventory_digest, verified_metadata)
    _VERIFIED_INVENTORIES[key] = result
    return result


def _verification_metadata(
    path: Path,
    stat: os.stat_result,
    expected_digest: str,
) -> dict[str, Any]:
    return {
        "path": str(path),
        "size": stat.st_size,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "sha256": expected_digest,
    }


def _read_verification_cache(
    cache_dir: Path | None,
    inventory_digest: str,
) -> dict[str, Any]:
    if cache_dir is None:
        return {}
    path = cache_dir / f"{inventory_digest}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("inventory_sha256") != inventory_digest:
        return {}
    return payload


def _write_verification_cache(
    cache_dir: Path | None,
    inventory_digest: str,
    files: Mapping[str, Mapping[str, Any]],
) -> None:
    if cache_dir is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{inventory_digest}.json"
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    payload = {
        "inventory_sha256": inventory_digest,
        "files": files,
    }
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _row_to_bar(row: dict[str, Any]) -> Bar:
    trade_status = row.get("trade_status")
    return Bar(
        symbol=str(row["symbol"]),
        trade_date=_as_date(row["trade_date"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
        amount=float(row["amount"]),
        free_float_shares=float(row["circulating_shares"]),
        available_at=_aware_local(row["available_at"]),
        suspended=trade_status is not None and int(trade_status) == 0,
        st=bool(row["is_st"]) if row.get("is_st") is not None else False,
        limit_up=_optional_float(row.get("up_limit_price")),
        limit_down=_optional_float(row.get("down_limit_price")),
    )


@lru_cache(maxsize=2_048)
def _unknown_rule(trade_date: date) -> MarketRule:
    return MarketRule(
        rule_id="UNKNOWN",
        effective_from=trade_date,
        effective_to=trade_date,
        price_limit_pct=None,
        t_plus_one=True,
        lot_size=100,
        known=False,
    )


@lru_cache(maxsize=8_192)
def _known_rule(
    rule_id: str,
    trade_date: date,
    price_limit_pct: float | None,
) -> MarketRule:
    return MarketRule(
        rule_id=rule_id,
        effective_from=trade_date,
        effective_to=trade_date,
        price_limit_pct=price_limit_pct,
        t_plus_one=True,
        lot_size=100,
        known=True,
    )


def _market_rule_from_row(
    row: dict[str, Any] | None,
    trade_date: date,
) -> MarketRule:
    if row is None or not bool(row.get("market_rule_valid")):
        return _unknown_rule(trade_date)
    rule_id = _optional_text(row.get("market_rule_id"))
    if rule_id is None:
        return _unknown_rule(trade_date)
    return _known_rule(rule_id, trade_date, _optional_float(row.get("limit_pct")))


def _action_available_at(row: dict[str, Any]) -> datetime:
    raw = row.get("corporate_action_available_date")
    if raw is None:
        return _aware_local(row["available_at"])
    if isinstance(raw, datetime):
        return _aware_local(raw)
    action_date = _as_date(raw)
    return datetime.combine(action_date, time(15, 0), tzinfo=_SHANGHAI)


def _local_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("decision_at must be timezone-aware")
    return value.astimezone(_SHANGHAI).replace(tzinfo=None)


def _query_scope(symbols: Sequence[str] | None) -> tuple[str, ...] | None:
    """Push small research universes into SQL; None denotes the full-universe path."""

    if not symbols:
        return None
    unique_symbols = tuple(sorted(set(symbols)))
    return unique_symbols if len(unique_symbols) <= 128 else None


@lru_cache(maxsize=32_768)
def _aware_local(value: Any) -> datetime:
    if isinstance(value, datetime):
        return (
            value.replace(tzinfo=_SHANGHAI) if value.tzinfo is None else value.astimezone(_SHANGHAI)
        )
    parsed = datetime.fromisoformat(str(value))
    return (
        parsed.replace(tzinfo=_SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(_SHANGHAI)
    )


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


@lru_cache(maxsize=64)
def _parse_chip_priors(payload: str) -> tuple[str, ...]:
    return tuple(str(value) for value in json.loads(payload))


def _row_to_prepared_chip(row: Mapping[str, Any]) -> PreparedChipRecord:
    peaks_payload = json.loads(str(row["peaks_json"]))
    priors = _parse_chip_priors(str(row["priors_json"]))
    peaks = tuple(
        ChipPeak(
            center_price=float(item["center_price"]),
            mass=float(item["mass"]),
            width_pct=float(item["width_pct"]),
            prominence=float(item["prominence"]),
            age_mean=_optional_float(item.get("age_mean")),
            formation_date=str(item["formation_date"]),
        )
        for item in peaks_payload
    )
    features = ChipFeatures(
        profit_ratio=float(row["profit_ratio"]),
        trapped_ratio=float(row["trapped_ratio"]),
        average_cost=float(row["average_cost"]),
        p01=float(row["p01"]),
        p10=float(row["p10"]),
        p50=float(row["p50"]),
        p90=float(row["p90"]),
        p99=float(row["p99"]),
        asr=float(row["asr"]),
        space20=float(row["space20"]),
        ckdp=float(row["ckdp"]),
        ckdw=float(row["ckdw"]),
        cbw=float(row["cbw"]),
        cyqk_pre=CYQK(
            open=float(row["cyqk_open_pre"]),
            high=float(row["cyqk_high_pre"]),
            low=float(row["cyqk_low_pre"]),
            close=float(row["cyqk_close_pre"]),
        ),
        cyc5=_optional_float(row["cyc5"]),
        cyc13=_optional_float(row["cyc13"]),
        cyc34=_optional_float(row["cyc34"]),
        cys13=_optional_float(row["cys13"]),
        cys34=_optional_float(row["cys34"]),
        rpy2=_optional_float(row["rpy2"]),
        concentration_20=float(row["concentration_20"]),
        peaks=peaks,
        priors=priors,
        quality=float(row["state_quality"]),
    )
    return PreparedChipRecord(
        symbol=str(row["symbol"]),
        trade_date=_as_date(row["trade_date"]),
        available_at=_aware_local(row["available_at"]),
        daily_snapshot_id=str(row["daily_snapshot_id"]),
        minute_snapshot_id=str(row["minute_snapshot_id"]),
        features=features,
        base_retention=float(row["base_retention"]),
        strict_sample=bool(row["strict_sample"]),
        invalid_reason=str(row["invalid_reason"] or ""),
        opening_30m_return=_optional_float(row["opening_30m_return"]),
        closing_30m_return=_optional_float(row["closing_30m_return"]),
        close_vs_vwap=_optional_float(row["close_vs_vwap"]),
        last_hour_volume_share=_optional_float(row["last_hour_volume_share"]),
        realized_volatility=_optional_float(row["realized_volatility"]),
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    separator = "|" if "|" in text else ","
    return [item.strip() for item in text.split(separator) if item.strip()]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
