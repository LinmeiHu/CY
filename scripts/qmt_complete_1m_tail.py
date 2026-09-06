#!/usr/bin/env python3
"""Complete a QMT one-minute window without letting one callback stall the run.

The QMT history downloader can finish writing its cache yet fail to return.  This
host-side driver therefore isolates each code chunk in its own Windows process,
kills only exporter processes after a bounded timeout, and probes the cache
before deciding whether a smaller retry is needed.  It never calls trading APIs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any


QMT_PYTHON = r"C:\QMT\GuoJinQMT\bin.x64\pythonw.exe"
QMT_DOWNLOAD_SCRIPT = (
    r"\\Mac\Home\Downloads\CY-v27-2026\qmt_download_export_1m_matrix.py"
)
QMT_PROBE_SCRIPT = (
    r"\\Mac\Home\Documents\CY-supermind-v6-autonomous-20260830"
    r"\scripts\qmt_export_1m_matrix.py"
)


def mac_to_unc(path: Path) -> str:
    resolved = path.resolve()
    home = Path.home().resolve()
    relative = resolved.relative_to(home)
    return r"\\Mac\Home" + "\\" + str(relative).replace("/", "\\")


def load_codes(path: Path) -> list[str]:
    values: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        token = line.strip().split(",", 1)[0].upper()
        if token and token not in {"QMT_CODE", "SYMBOL", "CODE"}:
            values.append(token)
    return list(dict.fromkeys(values))


def qmt_command(
    script: str,
    codes_file: Path,
    start: str,
    end: str,
    out_dir: Path,
) -> list[str]:
    args = [
        QMT_PYTHON,
        script,
        "--codes-file",
        mac_to_unc(codes_file),
        "--start",
        start,
        "--end",
        end,
        "--out-dir",
        mac_to_unc(out_dir),
        "--batch-size",
        str(len(load_codes(codes_file))),
        "--attempts",
        "1",
    ]
    return [
        "prlctl",
        "exec",
        "Windows 11",
        "cmd",
        "/c",
        subprocess.list2cmdline(args),
    ]


def kill_only_exporters() -> None:
    expression = (
        "Get-CimInstance Win32_Process | Where-Object {"
        "$_.Name -eq 'pythonw.exe' -and "
        "($_.CommandLine -like '*qmt_download_export_1m_matrix.py*' -or "
        "$_.CommandLine -like '*qmt_export_1m_matrix.py*')} | "
        "Select-Object -ExpandProperty ProcessId"
    )
    try:
        found = subprocess.run(
            [
                "prlctl",
                "exec",
                "Windows 11",
                "powershell",
                "-NoProfile",
                "-Command",
                expression,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        pids = [int(token) for token in found.stdout.split() if token.isdigit()]
    except subprocess.TimeoutExpired:
        pids = []
    for pid in pids:
        try:
            subprocess.run(
                [
                    "prlctl",
                    "exec",
                    "Windows 11",
                    "cmd",
                    "/c",
                    "taskkill",
                    "/PID",
                    str(pid),
                    "/T",
                    "/F",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        except subprocess.TimeoutExpired:
            pass
    time.sleep(1)


def matrix_columns(out_dir: Path) -> int | None:
    path = out_dir / "batch_0001.json"
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return int(value["shape"][1])


def run_once(
    script: str,
    codes_file: Path,
    start: str,
    end: str,
    out_dir: Path,
    timeout: int,
) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    command = qmt_command(script, codes_file, start, end, out_dir)
    try:
        subprocess.run(command, check=True, timeout=timeout)
        return "RETURNED"
    except subprocess.TimeoutExpired:
        kill_only_exporters()
        return "TIMED_OUT"
    except subprocess.CalledProcessError:
        kill_only_exporters()
        return "FAILED"


def write_codes(path: Path, codes: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(codes) + "\n", encoding="utf-8")


def complete_chunk(
    chunk_no: int,
    codes: list[str],
    start: str,
    end: str,
    root: Path,
    expected_columns: int,
    timeout: int,
) -> dict[str, Any]:
    code_file = root / "code_chunks" / f"chunk_{chunk_no:04d}.csv"
    write_codes(code_file, codes)
    attempts: list[dict[str, Any]] = []
    for attempt_no in (1, 2):
        out_dir = root / "download_attempts" / (
            f"chunk_{chunk_no:04d}_attempt_{attempt_no}"
        )
        state = run_once(
            QMT_DOWNLOAD_SCRIPT, code_file, start, end, out_dir, timeout
        )
        columns = matrix_columns(out_dir)
        attempts.append(
            {
                "attempt": attempt_no,
                "state": state,
                "matrix_columns": columns,
                "output": str(out_dir),
            }
        )
        if columns == expected_columns:
            return {
                "chunk": chunk_no,
                "codes": len(codes),
                "status": "COMPLETE",
                "attempts": attempts,
            }

        probe_dir = root / "cache_probes" / (
            f"chunk_{chunk_no:04d}_after_{attempt_no}"
        )
        probe_state = run_once(
            QMT_PROBE_SCRIPT,
            code_file,
            start,
            end,
            probe_dir,
            max(timeout, 90),
        )
        probe_columns = matrix_columns(probe_dir)
        attempts.append(
            {
                "attempt": f"probe_after_{attempt_no}",
                "state": probe_state,
                "matrix_columns": probe_columns,
                "output": str(probe_dir),
            }
        )
        if probe_columns == expected_columns:
            return {
                "chunk": chunk_no,
                "codes": len(codes),
                "status": "COMPLETE_AFTER_CALLBACK_TIMEOUT",
                "attempts": attempts,
            }
    return {
        "chunk": chunk_no,
        "codes": len(codes),
        "status": "INCOMPLETE_REQUIRES_SMALL_RETRY",
        "attempts": attempts,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes-file", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--start-chunk", type=int, default=1)
    parser.add_argument("--expected-columns", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    codes = load_codes(args.codes_file)
    chunks = [
        codes[offset : offset + args.chunk_size]
        for offset in range(0, len(codes), args.chunk_size)
    ]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "start": args.start,
        "end": args.end,
        "requested_codes": len(codes),
        "chunk_size": args.chunk_size,
        "expected_columns": args.expected_columns,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chunks": [],
    }
    manifest_path = args.out_dir / "completion_manifest.json"
    for index, chunk in enumerate(chunks, start=1):
        if index < args.start_chunk:
            continue
        item = complete_chunk(
            index,
            chunk,
            args.start,
            args.end,
            args.out_dir,
            args.expected_columns,
            args.timeout,
        )
        manifest["chunks"].append(item)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(
            "tail_completion chunk=%d/%d codes=%d status=%s"
            % (index, len(chunks), len(chunk), item["status"]),
            flush=True,
        )
    manifest["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    incomplete = [
        item for item in manifest["chunks"] if not item["status"].startswith("COMPLETE")
    ]
    manifest["ok"] = not incomplete
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
