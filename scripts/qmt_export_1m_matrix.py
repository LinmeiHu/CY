"""Export unadjusted QMT one-minute data as lossless NumPy matrices.

This script runs inside the Windows QMT Python runtime.  Keeping QMT's native
field matrices avoids an expensive long-table reshape in the bundled Python;
the matrices are normalized and validated on the research host afterwards.
Only xtdata market-data methods are used.
"""

import argparse
import hashlib
import json
import time
import traceback
from pathlib import Path

import numpy as np
from xtquant import xtdata


FIELDS = ["open", "high", "low", "close", "volume", "amount"]


def load_codes(path):
    values = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        token = line.strip().split(",", 1)[0].upper()
        if token and token not in {"QMT_CODE", "SYMBOL", "CODE"}:
            values.append(token)
    return list(dict.fromkeys(values))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
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
    args = parser.parse_args()

    codes = load_codes(args.codes_file)
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
        "native_volume_unit": "lots",
        "batches": [],
        "errors": [],
    }
    try:
        for offset in range(0, len(codes), args.batch_size):
            batch_no = offset // args.batch_size + 1
            batch = codes[offset : offset + args.batch_size]
            last_error = ""
            payload = None
            for attempt in range(1, args.attempts + 1):
                try:
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
                    if not payload or "open" not in payload:
                        raise RuntimeError("QMT returned no open matrix")
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

            reference = payload["open"]
            matrix_codes = [str(item) for item in reference.index]
            matrix_times = [str(item) for item in reference.columns]
            files = {}
            for field in FIELDS:
                frame = payload.get(field)
                if frame is None:
                    raise RuntimeError("QMT missing matrix field: " + field)
                if list(frame.index) != list(reference.index):
                    raise RuntimeError("QMT matrix code identity mismatch: " + field)
                if list(frame.columns) != list(reference.columns):
                    raise RuntimeError("QMT matrix time identity mismatch: " + field)
                path = out_dir / ("batch_%04d_%s.npy" % (batch_no, field))
                np.save(str(path), frame.to_numpy(dtype=np.float64))
                files[field] = {
                    "path": str(path),
                    "size": path.stat().st_size,
                    "sha256": sha256(path),
                }
            metadata = {
                "batch": batch_no,
                "requested_codes": batch,
                "matrix_codes": matrix_codes,
                "matrix_times": matrix_times,
                "shape": [len(matrix_codes), len(matrix_times)],
                "files": files,
            }
            metadata_path = out_dir / ("batch_%04d.json" % batch_no)
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            summary["batches"].append(
                {
                    "batch": batch_no,
                    "requested_codes": len(batch),
                    "matrix_codes": len(matrix_codes),
                    "matrix_times": len(matrix_times),
                    "metadata_path": str(metadata_path),
                    "metadata_sha256": sha256(metadata_path),
                }
            )
            print(
                "qmt_1m_matrix batch=%d codes=%d/%d shape=%dx%d"
                % (
                    batch_no,
                    offset + len(batch),
                    len(codes),
                    len(matrix_codes),
                    len(matrix_times),
                ),
                flush=True,
            )
        summary["ok"] = not summary["errors"]
    except Exception:
        summary["errors"].append({"batch": None, "error": traceback.format_exc()})
    finally:
        summary["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        (out_dir / "export_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
