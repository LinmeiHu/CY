"""Low-overhead wall/CPU/I/O/RSS stage measurements."""

from __future__ import annotations

import resource
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class StageTelemetry:
    stage: str
    wall_seconds: float
    cpu_seconds: float
    rows: int
    rows_per_second: float
    bytes_read: int
    bytes_written: int
    peak_rss_bytes: int


class TelemetryRecorder:
    """Accumulate named, non-overlapping benchmark stages."""

    def __init__(self) -> None:
        self.records: list[StageTelemetry] = []

    @contextmanager
    def stage(
        self,
        name: str,
        *,
        rows: int = 0,
        read_paths: tuple[Path, ...] = (),
        write_paths: tuple[Path, ...] = (),
    ) -> Iterator[None]:
        before_read = _path_bytes(read_paths)
        before_write = _path_bytes(write_paths)
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        yield
        wall = max(0.0, time.perf_counter() - wall_start)
        cpu = max(0.0, time.process_time() - cpu_start)
        self.records.append(
            StageTelemetry(
                stage=name,
                wall_seconds=wall,
                cpu_seconds=cpu,
                rows=rows,
                rows_per_second=rows / wall if rows and wall else 0.0,
                bytes_read=max(0, _path_bytes(read_paths) - before_read)
                if not before_read
                else before_read,
                bytes_written=max(0, _path_bytes(write_paths) - before_write),
                peak_rss_bytes=_peak_rss_bytes(),
            )
        )

    def to_dict(self) -> list[dict[str, object]]:
        return [asdict(record) for record in self.records]


def _path_bytes(paths: tuple[Path, ...]) -> int:
    total = 0
    for path in paths:
        if path.is_file():
            total += path.stat().st_size
        elif path.is_dir():
            total += sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return total


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # macOS reports bytes; Linux reports KiB.
    return value if value > 10_000_000 else value * 1024
