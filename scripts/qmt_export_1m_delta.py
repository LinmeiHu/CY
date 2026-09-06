"""Export an immutable unadjusted QMT one-minute delta as batch CSV files.

This script is intended to run inside the Windows QMT Python runtime.  It only
uses ``xtdata`` market-data methods; it does not import or call trading APIs.
"""

import argparse
import hashlib
import json
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
from xtquant import xtdata


FIELDS = ["open", "high", "low", "close", "volume", "amount"]


def load_codes(path):
    values = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        token = line.strip().split(",", 1)[0].upper()
        if token and token not in {"QMT_CODE", "SYMBOL", "CODE"}:
            values.append(token)
    return list(dict.fromkeys(values))


def frame_to_rows(code, frame):
    if frame is None or frame.empty:
        return pd.DataFrame()
    symbol, exchange = code.split(".", 1)
    result = frame.reset_index().rename(columns={"index": "time_key"})
    if "time_key" not in result:
        result = result.rename(columns={result.columns[0]: "time_key"})
    timestamp = pd.to_datetime(
        result["time_key"].astype(str), format="%Y%m%d%H%M%S", errors="coerce"
    )
    result.insert(0, "qmt_code", code)
    result.insert(1, "symbol", symbol)
    result.insert(2, "exchange", exchange)
    result.insert(3, "period", "1m")
    result.insert(4, "adjust", "none")
    result.insert(5, "trade_date", timestamp.dt.strftime("%Y-%m-%d"))
    result.insert(6, "bar_end_time", timestamp.dt.strftime("%Y-%m-%d %H:%M:%S"))
    for column in FIELDS:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    # QMT reports stock volume in lots; the registered QD-004 unit is shares.
    result["volume"] = result["volume"] * 100.0
    result["source"] = "qmt_xtdata"
    return result[
        [
            "qmt_code",
            "symbol",
            "exchange",
            "period",
            "adjust",
            "trade_date",
            "bar_end_time",
            *FIELDS,
            "source",
        ]
    ]


def matrix_to_rows(payload):
    if not payload or "open" not in payload:
        return pd.DataFrame()
    reference = payload["open"]
    codes = [str(item) for item in reference.index]
    times = [str(item) for item in reference.columns]
    for field in FIELDS:
        frame = payload.get(field)
        if frame is None or list(frame.index) != list(reference.index) or list(frame.columns) != list(reference.columns):
            raise RuntimeError("QMT matrix field identity mismatch: " + field)
    count = len(codes) * len(times)
    result = pd.DataFrame(
        {
            "qmt_code": np.repeat(np.asarray(codes, dtype=object), len(times)),
            "bar_end_time": np.tile(np.asarray(times, dtype=object), len(codes)),
        }
    )
    if len(result) != count:
        raise RuntimeError("QMT matrix reshape length mismatch")
    for field in FIELDS:
        result[field] = payload[field].to_numpy().reshape(-1)
    result = result.loc[
        np.isfinite(result.open)
        & np.isfinite(result.high)
        & np.isfinite(result.low)
        & np.isfinite(result.close)
        & np.isfinite(result.volume)
        & np.isfinite(result.amount)
        & result.open.gt(0)
        & result.high.gt(0)
        & result.low.gt(0)
        & result.close.gt(0)
        & result.volume.ge(0)
        & result.amount.ge(0)
    ].copy()
    result["symbol"] = result.qmt_code.str.split(".").str[0]
    result["exchange"] = result.qmt_code.str.split(".").str[1]
    result["period"] = "1m"
    result["adjust"] = "none"
    timestamp = pd.to_datetime(
        result.bar_end_time, format="%Y%m%d%H%M%S", errors="coerce"
    )
    result["trade_date"] = timestamp.dt.strftime("%Y-%m-%d")
    result["bar_end_time"] = timestamp.dt.strftime("%Y-%m-%d %H:%M:%S")
    result["volume"] = result.volume * 100.0
    result["source"] = "qmt_xtdata"
    return result[
        [
            "qmt_code",
            "symbol",
            "exchange",
            "period",
            "adjust",
            "trade_date",
            "bar_end_time",
            *FIELDS,
            "source",
        ]
    ]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes-file", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--matrix-api", action="store_true")
    args = parser.parse_args()

    codes = load_codes(Path(args.codes_file))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "ok": False,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "start": args.start,
        "end": args.end,
        "requested_codes": len(codes),
        "period": "1m",
        "adjust": "none",
        "volume_unit": "shares",
        "batches": [],
        "errors": [],
    }
    try:
        for offset in range(0, len(codes), args.batch_size):
            batch_no = offset // args.batch_size + 1
            batch = codes[offset : offset + args.batch_size]
            output = out_dir / f"batch_{batch_no:04d}.csv"
            frames = []
            last_error = ""
            for attempt in range(1, args.attempts + 1):
                try:
                    if not args.skip_download:
                        if hasattr(xtdata, "download_history_data2"):
                            xtdata.download_history_data2(
                                batch, "1m", args.start, args.end
                            )
                        else:
                            for code in batch:
                                xtdata.download_history_data(
                                    code, "1m", args.start, args.end
                                )
                    if args.matrix_api:
                        payload = xtdata.get_market_data(
                            field_list=FIELDS,
                            stock_list=batch,
                            period="1m",
                            start_time=args.start,
                            end_time=args.end,
                            count=-1,
                            dividend_type="none",
                            fill_data=False,
                        )
                        frames = [matrix_to_rows(payload)]
                    else:
                        payload = xtdata.get_market_data_ex(
                            FIELDS,
                            batch,
                            period="1m",
                            start_time=args.start,
                            end_time=args.end,
                            dividend_type="none",
                            fill_data=False,
                        )
                        frames = [
                            frame_to_rows(code, payload.get(code)) for code in batch
                        ]
                    last_error = ""
                    break
                except Exception:
                    last_error = traceback.format_exc()
                    if attempt < args.attempts:
                        time.sleep(min(10, 2 * attempt))
            if last_error:
                summary["errors"].append(
                    {"batch": batch_no, "codes": batch, "error": last_error}
                )
                continue
            combined = pd.concat(
                [frame for frame in frames if not frame.empty], ignore_index=True
            ) if frames else pd.DataFrame()
            combined.to_csv(output, index=False, encoding="utf-8")
            item = {
                "batch": batch_no,
                "requested_codes": len(batch),
                "codes_with_rows": int(combined.qmt_code.nunique()) if len(combined) else 0,
                "rows": len(combined),
                "path": str(output),
                "size": output.stat().st_size,
                "sha256": sha256(output),
            }
            summary["batches"].append(item)
            print(
                f"qmt_1m_delta batch={batch_no} codes={offset + len(batch)}/{len(codes)} rows={len(combined)}",
                flush=True,
            )
        summary["ok"] = not summary["errors"]
    finally:
        summary["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        (out_dir / "export_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
