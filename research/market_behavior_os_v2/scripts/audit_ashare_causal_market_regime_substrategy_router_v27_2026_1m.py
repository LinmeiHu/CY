#!/usr/bin/env python3
"""Build and audit the exact one-minute execution evidence for V27 in 2026.

The signal and outcome tables are frozen inputs.  Minute bars are used only to
cross-check T+1 opens and standing-target reachability; they never participate
in signal formation or parameter selection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


FIELDS = ("open", "high", "low", "close", "volume", "amount")
BASE_START = "20260813093000"
BASE_END = "20260828150000"
TAIL_START = "20260831093000"
TAIL_END = "20260904150000"
SUPPLEMENT_START = "20260730093000"
SUPPLEMENT_END = "20260804150000"
OLD_CUTOFF = pd.Timestamp("2026-08-12")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        ),
        encoding="utf-8",
    )
    temp.replace(path)


def read_metadata(root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(root.rglob("batch_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        times = payload.get("matrix_times") or []
        codes = payload.get("matrix_codes") or []
        if not times or not codes:
            continue
        records.append(
            {
                "path": path,
                "payload": payload,
                "start": str(times[0]),
                "end": str(times[-1]),
                "n_times": len(times),
                "codes": set(str(code) for code in codes),
            }
        )
    return records


def choose_sources(
    metadata: list[dict[str, object]],
    codes: set[str],
    start: str,
    end: str,
    *,
    require_all: bool,
) -> dict[str, dict[str, object]]:
    chosen: dict[str, dict[str, object]] = {}
    open_cache: dict[Path, np.ndarray] = {}
    for code in sorted(codes):
        eligible = [
            record
            for record in metadata
            if record["start"] <= start
            and record["end"] >= end
            and code in record["codes"]
        ]
        if not eligible:
            if require_all:
                raise RuntimeError(f"no QMT matrix covers {code} in {start}..{end}")
            continue
        scored: list[tuple[int, int, str, dict[str, object]]] = []
        for record in eligible:
            metadata_path = Path(record["path"])
            payload = record["payload"]
            batch = int(payload["batch"])
            array_path = metadata_path.parent / f"batch_{batch:04d}_open.npy"
            if not array_path.is_file():
                continue
            if array_path not in open_cache:
                open_cache[array_path] = np.load(array_path, mmap_mode="r")
            matrix_times = np.asarray([str(value) for value in payload["matrix_times"]])
            mask = (matrix_times >= start) & (matrix_times <= end)
            matrix_codes = [str(value) for value in payload["matrix_codes"]]
            row = matrix_codes.index(code)
            values = open_cache[array_path][row, mask]
            valid = int((np.isfinite(values) & (values > 0)).sum())
            scored.append((-valid, int(record["n_times"]), str(metadata_path), record))
        if not scored:
            if require_all:
                raise RuntimeError(f"no readable QMT matrix covers {code} in {start}..{end}")
            continue
        scored.sort(key=lambda item: item[:3])
        chosen[code] = scored[0][3]
    return chosen


def verify_matrix(record: dict[str, object], verified: dict[str, dict[str, object]]) -> None:
    metadata_path = Path(record["path"])
    key = str(metadata_path)
    if key in verified:
        return
    payload = record["payload"]
    batch = int(payload["batch"])
    expected_shape = tuple(int(value) for value in payload["shape"])
    field_evidence: dict[str, object] = {}
    for field in FIELDS:
        array_path = metadata_path.parent / f"batch_{batch:04d}_{field}.npy"
        if not array_path.is_file():
            raise RuntimeError(f"missing QMT matrix: {array_path}")
        expected = str(payload["files"][field]["sha256"])
        actual = sha256(array_path)
        if actual != expected:
            raise RuntimeError(f"QMT matrix hash mismatch: {array_path}")
        shape = tuple(np.load(array_path, mmap_mode="r").shape)
        if shape != expected_shape:
            raise RuntimeError(
                f"QMT matrix shape mismatch: {array_path}: {shape} != {expected_shape}"
            )
        field_evidence[field] = {
            "path": str(array_path),
            "sha256": actual,
            "size": array_path.stat().st_size,
        }
    verified[key] = {
        "metadata_path": str(metadata_path),
        "metadata_sha256": sha256(metadata_path),
        "shape": list(expected_shape),
        "start": record["start"],
        "end": record["end"],
        "fields": field_evidence,
    }


def materialize_qmt(
    chosen: dict[str, dict[str, object]],
    start: str,
    end: str,
    verified: dict[str, dict[str, object]],
) -> pd.DataFrame:
    by_path: dict[Path, list[str]] = defaultdict(list)
    records: dict[Path, dict[str, object]] = {}
    for code, record in chosen.items():
        path = Path(record["path"])
        by_path[path].append(code)
        records[path] = record

    frames: list[pd.DataFrame] = []
    for metadata_path, codes in sorted(by_path.items(), key=lambda item: str(item[0])):
        record = records[metadata_path]
        verify_matrix(record, verified)
        payload = record["payload"]
        batch = int(payload["batch"])
        matrix_codes = [str(value) for value in payload["matrix_codes"]]
        matrix_times = np.asarray([str(value) for value in payload["matrix_times"]])
        mask = (matrix_times >= start) & (matrix_times <= end)
        selected_times = pd.to_datetime(matrix_times[mask], format="%Y%m%d%H%M%S")
        arrays = {
            field: np.load(
                metadata_path.parent / f"batch_{batch:04d}_{field}.npy",
                mmap_mode="r",
            )
            for field in FIELDS
        }
        for code in sorted(codes):
            row = matrix_codes.index(code)
            frame = pd.DataFrame(
                {
                    "qmt_code": code,
                    "bar_end_time": selected_times,
                    **{field: arrays[field][row, mask] for field in FIELDS},
                }
            )
            # QMT's native minute volume is in lots.  Preserve the conversion
            # explicitly instead of changing prices or filling absent bars.
            frame["volume"] = frame["volume"] * 100.0
            frame["trade_date"] = frame["bar_end_time"].dt.normalize()
            frame["source"] = "qmt_xtdata_none"
            frame["native_volume_unit"] = "lots_x100_to_shares"
            frames.append(frame)
    if not frames:
        return pd.DataFrame(
            columns=[
                "qmt_code",
                "bar_end_time",
                *FIELDS,
                "trade_date",
                "source",
                "native_volume_unit",
            ]
        )
    result = pd.concat(frames, ignore_index=True)
    return result.sort_values(["qmt_code", "bar_end_time"]).reset_index(drop=True)


def parse_sina_payload(body: str) -> list[dict[str, str]]:
    match = re.search(r"var\s+_data=\((.*)\);?\s*$", body, flags=re.DOTALL)
    if not match:
        raise RuntimeError("unexpected Sina one-minute JSONP envelope")
    payload = json.loads(match.group(1))
    if not isinstance(payload, list):
        raise RuntimeError("unexpected Sina one-minute payload type")
    return payload


def download_sina(
    codes: set[str], raw_dir: Path, attempts: int = 4
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    frames: list[pd.DataFrame] = []
    lineage: list[dict[str, object]] = []
    for code in sorted(codes):
        market = "sh" if code.endswith(".SH") else "sz"
        symbol = code.split(".", 1)[0]
        query = urllib.parse.urlencode(
            {"symbol": market + symbol, "scale": 1, "ma": "no", "datalen": 1023}
        )
        url = (
            "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_data=/"
            "CN_MarketDataService.getKLineData?" + query
        )
        body = ""
        error = ""
        for attempt in range(1, attempts + 1):
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://finance.sina.com.cn/",
                    },
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    body = response.read().decode("utf-8")
                error = ""
                break
            except Exception as exc:  # network errors are evidence, not fillable data
                error = repr(exc)
                if attempt < attempts:
                    time.sleep(attempt)
        if error:
            raise RuntimeError(f"Sina minute download failed for {code}: {error}")
        raw_path = raw_dir / f"{code}.jsonp"
        raw_path.write_text(body, encoding="utf-8")
        rows = parse_sina_payload(body)
        frame = pd.DataFrame(rows)
        required = {"day", "open", "high", "low", "close", "volume", "amount"}
        if not required.issubset(frame.columns):
            raise RuntimeError(f"Sina minute fields missing for {code}")
        frame = frame.rename(columns={"day": "bar_end_time"})
        frame["bar_end_time"] = pd.to_datetime(frame["bar_end_time"])
        for field in FIELDS:
            frame[field] = pd.to_numeric(frame[field], errors="raise")
        frame["qmt_code"] = code
        frame["trade_date"] = frame["bar_end_time"].dt.normalize()
        frame["source"] = "sina_cn_market_data_service"
        frame["native_volume_unit"] = "shares"
        frames.append(
            frame[
                [
                    "qmt_code",
                    "bar_end_time",
                    *FIELDS,
                    "trade_date",
                    "source",
                    "native_volume_unit",
                ]
            ]
        )
        lineage.append(
            {
                "qmt_code": code,
                "url": url,
                "downloaded_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
                "raw_path": str(raw_path),
                "raw_sha256": sha256(raw_path),
                "rows": len(frame),
                "first_bar": frame["bar_end_time"].min().isoformat(),
                "last_bar": frame["bar_end_time"].max().isoformat(),
            }
        )
    return pd.concat(frames, ignore_index=True), lineage


def structural_issues(frame: pd.DataFrame) -> pd.DataFrame:
    finite = frame[list(FIELDS)].notna().all(axis=1)
    active = frame.loc[finite].copy()
    bad = (
        (active[["open", "high", "low", "close"]] <= 0).any(axis=1)
        | (active["high"] + 1e-10 < active[["open", "close"]].max(axis=1))
        | (active["low"] - 1e-10 > active[["open", "close"]].min(axis=1))
        | (active[["volume", "amount"]] < 0).any(axis=1)
    )
    return active.loc[bad]


def aggregate_daily(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = frame.sort_values(["qmt_code", "bar_end_time"])
    active = ordered.dropna(subset=["open", "high", "low", "close"])
    grouped = active.groupby(["qmt_code", "trade_date"], sort=True)
    result = grouped.agg(
        minute_rows=("bar_end_time", "size"),
        minute_open=("open", "first"),
        minute_high=("high", "max"),
        minute_low=("low", "min"),
        minute_close=("close", "last"),
        minute_volume=("volume", lambda values: values.sum(min_count=1)),
        minute_amount=("amount", lambda values: values.sum(min_count=1)),
    )
    return result.reset_index()


def daily_crosscheck(frame: pd.DataFrame, daily: pd.DataFrame) -> dict[str, object]:
    aggregate = aggregate_daily(frame)
    expected = daily.loc[
        daily["hard_valid"].fillna(False)
        & daily["current_day_data_tradable"].fillna(False),
        ["symbol", "trade_date", "open", "high", "low", "close", "volume", "amount"],
    ].rename(columns={"symbol": "qmt_code"})
    merged = aggregate.merge(expected, on=["qmt_code", "trade_date"], how="inner")
    price_errors = {}
    for field in ("open", "high", "low", "close"):
        price_errors[field] = float(
            (merged[f"minute_{field}"] - merged[field]).abs().max()
        )
    volume_abs = (merged["minute_volume"] - merged["volume"]).abs()
    amount_abs = (merged["minute_amount"] - merged["amount"]).abs()
    issue_mask = merged["minute_rows"].ne(241)
    price_issue = merged["minute_rows"].ne(241)
    for field in ("open", "high", "low", "close"):
        field_issue = (merged[f"minute_{field}"] - merged[field]).abs().gt(1e-7)
        issue_mask |= field_issue
        price_issue |= field_issue
    # The registered daily vendor retains share/cent residuals while QMT's
    # minute feed reports integer lots and integer yuan.  These fixed source
    # resolutions are explicit validation bounds, not mass normalization.
    volume_tolerance = np.maximum(100.0, merged["volume"].abs() * 1e-6)
    amount_tolerance = np.maximum(100.0, merged["amount"].abs() * 1e-6)
    volume_issue = volume_abs.gt(volume_tolerance)
    amount_issue = amount_abs.gt(amount_tolerance)
    issue_mask |= volume_issue
    issue_mask |= amount_issue
    return {
        "eligible_daily_rows": int(len(expected)),
        "matched_daily_rows": int(len(merged)),
        "issues": int(issue_mask.sum()),
        "price_or_bar_count_issues": int(price_issue.sum()),
        "volume_issues": int(volume_issue.sum()),
        "amount_issues": int(amount_issue.sum()),
        "max_price_abs_error": price_errors,
        "max_volume_abs_error_shares": float(volume_abs.max()) if len(volume_abs) else None,
        "max_amount_abs_error": float(amount_abs.max()) if len(amount_abs) else None,
        "volume_source_resolution_tolerance": "max(100 shares, 1e-6 * daily volume)",
        "amount_source_resolution_tolerance": "max(100 yuan, 1e-6 * daily amount)",
        "issue_examples": merged.loc[issue_mask].head(20).to_dict("records"),
    }


def load_old_execution_pairs(
    pairs: pd.DataFrame, old_paths: list[Path]
) -> pd.DataFrame:
    if pairs.empty:
        return pd.DataFrame()
    con = duckdb.connect()
    try:
        con.register("required_pairs", pairs[["qmt_code", "trade_date"]])
        quoted = ",".join("'" + str(path).replace("'", "''") + "'" for path in old_paths)
        query = f"""
            SELECT b.qmt_code, b.bar_end_time, b.open, b.high, b.low, b.close,
                   b.volume, b.amount, b.trade_date, b.source,
                   'shares' AS native_volume_unit
            FROM read_parquet([{quoted}]) AS b
            INNER JOIN required_pairs AS p
              ON b.qmt_code = p.qmt_code AND b.trade_date = p.trade_date
        """
        return con.execute(query).fetchdf()
    finally:
        con.close()


def execution_audit(
    trades: pd.DataFrame, daily: pd.DataFrame, minute: pd.DataFrame
) -> tuple[dict[str, object], pd.DataFrame]:
    bars = {
        (code, pd.Timestamp(day).normalize()): group.sort_values("bar_end_time")
        for (code, day), group in minute.groupby(["qmt_code", "trade_date"])
    }
    daily_rows = daily.set_index(["symbol", "trade_date"])
    details: list[dict[str, object]] = []
    for trade in trades.itertuples(index=False):
        entry_day = pd.Timestamp(trade.entry_date).normalize()
        exit_day = pd.Timestamp(trade.exit_date).normalize()
        entry_bars = bars.get((trade.symbol, entry_day))
        exit_bars = bars.get((trade.symbol, exit_day))
        entry_daily = daily_rows.loc[(trade.symbol, entry_day)]
        exit_daily = daily_rows.loc[(trade.symbol, exit_day)]
        entry_first_open = None if entry_bars is None or entry_bars.empty else float(entry_bars.iloc[0]["open"])
        exit_first_open = None if exit_bars is None or exit_bars.empty else float(exit_bars.iloc[0]["open"])
        exit_max_high = None if exit_bars is None or exit_bars.empty else float(exit_bars["high"].max())
        price_float_tolerance = 5e-5
        entry_open_ok = entry_first_open is not None and abs(entry_first_open - float(entry_daily["open"])) <= price_float_tolerance
        entry_coordinate_ok = abs(float(trade.entry_price) - float(entry_daily["coord_open"])) <= 1e-9
        is_target = str(trade.exit_reason).startswith("TARGET_")
        raw_exit_price = float(trade.exit_price) / float(exit_daily["coordinate_factor"])
        if is_target:
            exit_fill_ok = exit_max_high is not None and exit_max_high + price_float_tolerance >= raw_exit_price
            exit_test = "minute_high_reaches_standing_target"
        else:
            exit_fill_ok = exit_first_open is not None and abs(exit_first_open - raw_exit_price) <= price_float_tolerance
            exit_test = "first_minute_open_equals_time_stop_fill"
        details.append(
            {
                "event_id": trade.event_id,
                "symbol": trade.symbol,
                "signal_date": pd.Timestamp(trade.signal_date),
                "entry_date": entry_day,
                "exit_date": exit_day,
                "exit_reason": trade.exit_reason,
                "entry_minute_rows": 0 if entry_bars is None else len(entry_bars),
                "exit_minute_rows": 0 if exit_bars is None else len(exit_bars),
                "entry_first_open_raw": entry_first_open,
                "entry_daily_open_raw": float(entry_daily["open"]),
                "entry_open_ok": bool(entry_open_ok),
                "entry_coordinate_ok": bool(entry_coordinate_ok),
                "exit_first_open_raw": exit_first_open,
                "exit_max_high_raw": exit_max_high,
                "exit_expected_raw_price": raw_exit_price,
                "exit_test": exit_test,
                "exit_fill_ok": bool(exit_fill_ok),
                "entry_source": None if entry_bars is None or entry_bars.empty else ",".join(sorted(entry_bars["source"].unique())),
                "exit_source": None if exit_bars is None or exit_bars.empty else ",".join(sorted(exit_bars["source"].unique())),
            }
        )
    frame = pd.DataFrame(details)
    failures = frame.loc[
        ~frame["entry_open_ok"] | ~frame["entry_coordinate_ok"] | ~frame["exit_fill_ok"]
    ]
    summary = {
        "status": "PASS" if len(failures) == 0 else "FAIL_CLOSED",
        "trades": len(frame),
        "entry_open_pass": int(frame["entry_open_ok"].sum()),
        "entry_coordinate_pass": int(frame["entry_coordinate_ok"].sum()),
        "exit_fill_pass": int(frame["exit_fill_ok"].sum()),
        "failures": len(failures),
        "failure_examples": failures.head(20).to_dict("records"),
    }
    return summary, frame


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-root", default="/Users/linmei/Downloads/CY-v27-2026"
    )
    parser.add_argument(
        "--candidate-codes",
        default="/Users/linmei/Downloads/CY-v27-2026/v27_candidate_symbols_64.csv",
    )
    parser.add_argument(
        "--result-dir",
        default="/Volumes/quant/CY_quant_research/ashare_causal_market_regime_substrategy_router_v27_validation_2026ytd_v2",
    )
    parser.add_argument(
        "--old-minute-dir",
        default="/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars",
    )
    args = parser.parse_args()

    cache_root = Path(args.cache_root)
    result_dir = Path(args.result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)
    candidates = {
        line.strip().upper()
        for line in Path(args.candidate_codes).read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    }
    if len(candidates) != 64:
        raise RuntimeError(f"expected 64 frozen candidate symbols, got {len(candidates)}")

    trades = pd.read_parquet(result_dir / "accepted_trades.parquet")
    daily = pd.read_parquet(
        result_dir / "execution_daily_frozen_symbols_through_2026_09_04.parquet"
    )
    for column in ("signal_date", "entry_date", "exit_date"):
        trades[column] = pd.to_datetime(trades[column]).dt.normalize()
    daily["trade_date"] = pd.to_datetime(daily["trade_date"]).dt.normalize()

    metadata = read_metadata(cache_root)
    verified: dict[str, dict[str, object]] = {}
    base_sources = choose_sources(
        metadata, candidates, BASE_START, BASE_END, require_all=True
    )
    base = materialize_qmt(base_sources, BASE_START, BASE_END, verified)
    base_path = result_dir / "v27_candidate_symbols_64_1m_20260813_20260828.parquet"
    base.to_parquet(base_path, index=False)

    all_tail_sources = choose_sources(
        metadata, candidates, TAIL_START, TAIL_END, require_all=True
    )
    all_qmt_tail = materialize_qmt(
        all_tail_sources, TAIL_START, TAIL_END, verified
    )
    candidate_full = pd.concat([base, all_qmt_tail], ignore_index=True).sort_values(
        ["qmt_code", "bar_end_time"]
    )
    candidate_full_path = (
        result_dir / "v27_candidate_symbols_64_1m_20260813_20260904.parquet"
    )
    candidate_full.to_parquet(candidate_full_path, index=False)

    late_trades = trades.loc[trades["exit_date"] > OLD_CUTOFF].copy()
    tail_execution_codes = set(
        late_trades.loc[late_trades["exit_date"] >= pd.Timestamp("2026-08-31"), "symbol"]
    )
    tail_sources = {
        code: all_tail_sources[code] for code in sorted(tail_execution_codes)
    }
    qmt_tail = all_qmt_tail.loc[
        all_qmt_tail["qmt_code"].isin(tail_execution_codes)
    ].copy()

    # Fetch every actual Sep-2 exit from Sina.  Codes also present in QMT form
    # the independent dual-source overlap; missing codes use Sina only.
    sina, sina_lineage = download_sina(
        tail_execution_codes, result_dir / "minute_raw_sina"
    )
    sina_path = result_dir / "v27_sina_1m_execution_tail.parquet"
    sina.to_parquet(sina_path, index=False)

    overlap_codes = sorted(set(qmt_tail["qmt_code"]) & set(sina["qmt_code"]))
    overlap_left = qmt_tail.loc[
        qmt_tail["qmt_code"].isin(overlap_codes),
        ["qmt_code", "bar_end_time", *FIELDS],
    ]
    overlap_right = sina.loc[
        sina["qmt_code"].isin(overlap_codes),
        ["qmt_code", "bar_end_time", *FIELDS],
    ]
    overlap = overlap_left.merge(
        overlap_right,
        on=["qmt_code", "bar_end_time"],
        suffixes=("_qmt", "_sina"),
    )
    overlap_metrics: dict[str, object] = {
        "codes": overlap_codes,
        "matched_rows": len(overlap),
        "max_abs_error": {},
        "bar_convention": (
            "QMT has a separate 09:30 auction bar; Sina folds it into 09:31 "
            "and omits empty minutes. Daily aggregate is authoritative for "
            "the dual-source comparison."
        ),
    }
    for field in FIELDS:
        overlap_metrics["max_abs_error"][field] = float(
            (overlap[f"{field}_qmt"] - overlap[f"{field}_sina"]).abs().max()
        )
    overlap_day = pd.Timestamp("2026-09-02")
    qmt_overlap_daily = aggregate_daily(
        qmt_tail.loc[qmt_tail["trade_date"].eq(overlap_day)]
    )
    sina_overlap_daily = aggregate_daily(
        sina.loc[
            sina["qmt_code"].isin(overlap_codes)
            & sina["trade_date"].eq(overlap_day)
        ]
    )
    aggregate_overlap = qmt_overlap_daily.merge(
        sina_overlap_daily,
        on=["qmt_code", "trade_date"],
        suffixes=("_qmt", "_sina"),
    )
    aggregate_errors = {}
    for field in ("open", "high", "low", "close", "volume", "amount"):
        aggregate_errors[field] = float(
            (
                aggregate_overlap[f"minute_{field}_qmt"]
                - aggregate_overlap[f"minute_{field}_sina"]
            )
            .abs()
            .max()
        )
    overlap_metrics["daily_aggregate_rows"] = len(aggregate_overlap)
    overlap_metrics["daily_aggregate_max_abs_error"] = aggregate_errors

    base_structural = structural_issues(base)
    tail_structural = structural_issues(qmt_tail)
    sina_structural = structural_issues(sina)
    if len(base_structural) or len(tail_structural) or len(sina_structural):
        raise RuntimeError("one-minute structural validation failed")

    base_daily = daily.loc[
        daily["trade_date"].between("2026-08-13", "2026-08-28")
        & daily["symbol"].isin(candidates)
    ]
    full_daily = daily.loc[
        daily["trade_date"].between("2026-08-13", "2026-09-04")
        & daily["symbol"].isin(candidates)
    ]
    qmt_daily_check = daily_crosscheck(candidate_full, full_daily)

    sina_missing_codes = tail_execution_codes - set(tail_sources)
    sina_tail = sina.loc[
        sina["qmt_code"].isin(sina_missing_codes)
        & sina["trade_date"].eq(pd.Timestamp("2026-09-02"))
    ]
    qmt_tail_actual = qmt_tail.loc[
        qmt_tail["qmt_code"].isin(set(tail_sources))
        & qmt_tail["trade_date"].eq(pd.Timestamp("2026-09-02"))
    ]
    new_tail_execution = pd.concat([qmt_tail_actual, sina_tail], ignore_index=True)

    required_pairs = pd.concat(
        [
            trades[["symbol", "entry_date"]].rename(
                columns={"symbol": "qmt_code", "entry_date": "trade_date"}
            ),
            trades[["symbol", "exit_date"]].rename(
                columns={"symbol": "qmt_code", "exit_date": "trade_date"}
            ),
        ],
        ignore_index=True,
    ).drop_duplicates()
    old_pairs = required_pairs.loc[required_pairs["trade_date"] <= OLD_CUTOFF]
    old_minute_dir = Path(args.old_minute_dir)
    old_minute = load_old_execution_pairs(
        old_pairs,
        [
            old_minute_dir / "2026_day_parquet_none.parquet",
            old_minute_dir / "2026_qmt_tail.parquet",
        ],
    )
    old_available = old_minute[["qmt_code", "trade_date"]].drop_duplicates()
    missing_old_pairs = old_pairs.merge(
        old_available,
        on=["qmt_code", "trade_date"],
        how="left",
        indicator=True,
    ).loc[lambda value: value["_merge"].eq("left_only"), ["qmt_code", "trade_date"]]
    supplement_codes = set(missing_old_pairs["qmt_code"])
    supplement_sources = choose_sources(
        metadata,
        supplement_codes,
        SUPPLEMENT_START,
        SUPPLEMENT_END,
        require_all=False,
    )
    supplement = materialize_qmt(
        supplement_sources,
        SUPPLEMENT_START,
        SUPPLEMENT_END,
        verified,
    )
    supplement = supplement.merge(
        missing_old_pairs, on=["qmt_code", "trade_date"], how="inner"
    )
    new_base_pairs = required_pairs.loc[
        required_pairs["trade_date"].between("2026-08-13", "2026-08-28")
    ]
    new_base = base.merge(new_base_pairs, on=["qmt_code", "trade_date"], how="inner")
    execution_minute = pd.concat(
        [old_minute, supplement, new_base, new_tail_execution], ignore_index=True
    ).sort_values(["qmt_code", "bar_end_time"])
    execution_minute_path = result_dir / "v27_execution_relevant_1m_2026.parquet"
    execution_minute.to_parquet(execution_minute_path, index=False)

    audit_summary, audit_details = execution_audit(trades, daily, execution_minute)
    audit_details_path = result_dir / "v27_minute_execution_audit_details.parquet"
    audit_details.to_parquet(audit_details_path, index=False)

    artifacts = {}
    for path in (
        base_path,
        candidate_full_path,
        sina_path,
        execution_minute_path,
        audit_details_path,
    ):
        artifacts[path.name] = {
            "path": str(path),
            "sha256": sha256(path),
            "size": path.stat().st_size,
        }
    result = {
        "audit_id": "ASHARE-CAUSAL-MARKET-REGIME-SUBSTRATEGY-ROUTER-V27-2026-1M-AUDIT-V1",
        "created_at": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        "scope": {
            "frozen_candidates": len(candidates),
            "frozen_trades": len(trades),
            "minute_signal_usage": "NONE_CONFIRMATORY_EXECUTION_AUDIT_ONLY",
            "qmt_candidate_base_start": BASE_START,
            "qmt_candidate_base_end": BASE_END,
            "late_execution_tail_start": TAIL_START,
            "late_execution_tail_end": TAIL_END,
        },
        "qmt": {
            "selected_base_codes": len(base_sources),
            "selected_full_tail_codes": len(all_tail_sources),
            "selected_tail_execution_codes": sorted(tail_sources),
            "selected_historical_supplement_codes": sorted(supplement_sources),
            "verified_matrices": list(verified.values()),
            "base_rows": len(base),
            "candidate_full_rows": len(candidate_full),
            "tail_execution_rows": len(qmt_tail_actual),
            "structural_issues": len(base_structural) + len(tail_structural),
            "daily_crosscheck": qmt_daily_check,
        },
        "sina": {
            "downloaded_execution_codes": sorted(tail_execution_codes),
            "used_for_missing_qmt_codes": sorted(sina_missing_codes),
            "lineage": sina_lineage,
            "structural_issues": len(sina_structural),
            "qmt_overlap": overlap_metrics,
        },
        "execution": audit_summary,
        "artifacts": artifacts,
    }
    execution_pass = audit_summary["failures"] == 0
    candidate_minute_complete = (
        qmt_daily_check["matched_daily_rows"]
        == qmt_daily_check["eligible_daily_rows"]
        and len(base_structural) + len(tail_structural) == 0
    )
    if execution_pass and candidate_minute_complete:
        result["status"] = (
            "PASS"
            if qmt_daily_check["issues"] == 0
            else "PASS_EXECUTION_WITH_AUXILIARY_VENDOR_DIVERGENCES"
        )
    else:
        result["status"] = "FAIL_CLOSED"
    output_path = result_dir / "v27_minute_execution_audit.json"
    atomic_json(output_path, result)
    print(
        json.dumps(
            {**audit_summary, "overall_status": result["status"]},
            ensure_ascii=False,
            default=str,
        )
    )
    return 0 if result["status"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
