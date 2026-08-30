# Workspace recovery checkpoint

Recovered on 2026-08-30 from the read-only source worktree
`/Users/linmei/Documents/CY-supermind-v6` at
`e361aa9fb98756becc09c76dd88552533f3762fe`.

## Transfer verification

- verified source files: 161;
- verified destination files before destination-only records: 161;
- missing files: 0;
- extra files: 0;
- hash mismatches: 0;
- source aggregate SHA-256:
  `4965f87b6129a865c102fbfe1a4d807499614ac831b34daa8bd9e3751c3f3942`;
- destination aggregate SHA-256:
  `4965f87b6129a865c102fbfe1a4d807499614ac831b34daa8bd9e3751c3f3942`.

## Exclusions

- Entire external `research/chinext_v1/opportunity_conversion/` tree.
- Source modification `configs/data_asset_registry.json` at SHA-256
  `0b61a977e08bdce45dea4730792b7c9e6927139f7373b2ef359d211747fc3814`.
- Source modification `research/chinext_v1/scripts/run_chinext_v1_smoke.py` at
  SHA-256
  `3136edf9fc6a8a9f0a8d42487d8703943b0eaacaccdd188be18a6274cb4793e3`.
- Python bytecode and test caches.

The external directory remained actively written during recovery and contained 38
files at the final classification snapshot. Exclusion is therefore defined by the
whole directory prefix, not by a potentially stale individual-file list.

The autonomous worktree retains the clean HEAD registry (`1161ab5e...`) and
smoke runner (`9993b4ab...`). Invalid Phase 7/8/9 material is present only as
explicitly labeled audit history and is not accepted scientific evidence.
