"""Explicit Phase 3 resolver facade; legacy selection remains the default."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable

from cyq_game.chip.checkpoint_journal_reader import (
    CheckpointJournalReader,
    DependencyCatalog,
    ReplayBackend,
    RestoredDay,
)


class ChipResolverMode(StrEnum):
    LEGACY_OPERATOR = "LEGACY_OPERATOR"
    CHECKPOINT_JOURNAL = "CHECKPOINT_JOURNAL"


LEGACY_DEFAULT_MODE = ChipResolverMode.LEGACY_OPERATOR


@dataclass(frozen=True)
class CheckpointJournalResolver:
    reader: CheckpointJournalReader
    backend: ReplayBackend

    def restore(self, symbol: str, target: date) -> RestoredDay:
        return self.reader.restore(symbol, target, backend=self.backend)

    def terminal_compatibility_mismatch_count(self, symbol: str) -> int:
        return self.reader.terminal_compatibility_mismatch_count(symbol)


def build_chip_resolver(
    *,
    mode: ChipResolverMode = LEGACY_DEFAULT_MODE,
    legacy_root: str | Path | None = None,
    checkpoint_root: str | Path | None = None,
    replay_parameter_manifest_digest: str | None = None,
    dependency_catalog: DependencyCatalog | None = None,
    replay_backend: ReplayBackend | None = None,
    legacy_factory: Callable[[str | Path], Any] | None = None,
) -> Any:
    if mode is ChipResolverMode.LEGACY_OPERATOR:
        if legacy_root is None:
            raise ValueError("legacy resolver requires an explicit legacy root")
        if legacy_factory is None:
            from cyq_game.strategy.chip_lineage import PersistedChipLineageResolver

            legacy_factory = PersistedChipLineageResolver
        return legacy_factory(legacy_root)
    if mode is not ChipResolverMode.CHECKPOINT_JOURNAL:
        raise ValueError("unknown chip resolver mode")
    if (
        checkpoint_root is None
        or replay_parameter_manifest_digest is None
        or dependency_catalog is None
        or replay_backend is None
    ):
        raise ValueError("checkpoint/journal resolver configuration is incomplete")
    return CheckpointJournalResolver(
        reader=CheckpointJournalReader(
            checkpoint_root,
            replay_parameter_manifest_digest=replay_parameter_manifest_digest,
            dependency_catalog=dependency_catalog,
        ),
        backend=replay_backend,
    )
