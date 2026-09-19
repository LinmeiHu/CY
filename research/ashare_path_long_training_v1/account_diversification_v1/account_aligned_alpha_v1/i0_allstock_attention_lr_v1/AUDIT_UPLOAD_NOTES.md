# Audit Upload Notes

AUDIT SNAPSHOT COMPLETION ONLY

- OBSERVATION_ONLY
- NO FIX APPLIED
- Runtime source resolution follows the absolute CHAMP/SRC paths in run.py.
- The normal repository paths now contain byte-identical copies of the actual runtime sources.
- Direct local imports and dynamically loaded evaluator/account modules used by the current training and formal paths were included.
- Checkpoints, data, predictions, embeddings, ledgers, logs, locks, and caches remain excluded.
- The running worktree was not checked out or modified.

## Prior manifest reconciliation

- OBSERVATION_ONLY
- NO FIX APPLIED
- 9 entries had a different declared runtime origin or hash; 1 had a content SHA difference.
- The old manifest followed same-name files in the current worktree for some dependencies; actual Python resolution uses the absolute champion SRC path.
- research/ashare_path_long_training_v1/common.py: path_changed=true, sha_changed=false, actual_sha256=16cae85ea0682e8f009f275cc26af454606436f05d6e789394ba02b71f28c002.
- research/ashare_path_long_training_v1/train.py: path_changed=true, sha_changed=false, actual_sha256=9dbf519fa8a5a9075cbfe3d87cd941e6ae0b6e1a932ea9c5d1e71196523b481d.
- research/ashare_path_long_training_v1/account_daily_inference.py: path_changed=true, sha_changed=false, actual_sha256=1a50cf9bf89e0557ff86936d7a132e886f75fac142c9d181cadb8799e551089e.
- research/ashare_path_long_training_v1/prepare.py: path_changed=true, sha_changed=false, actual_sha256=8bf3adc088bfcb5285bcd873ba21024d6736ed5447103ea4d377bfa7a17c523b.
- research/ashare_path_long_training_v1/sampling.py: path_changed=true, sha_changed=false, actual_sha256=e449faa0c99bf5914f732f8ca0b5bc4f1e44bec6fd6d8231b7610c4a1cc68001.
- research/ashare_wave_adaptive_path_v3/model.py: path_changed=true, sha_changed=false, actual_sha256=7e2fd2a419a095d8abfdb8992230ef265b3612ffa5bfcca9873f6d334e107432.
- research/ashare_path_long_training_v1/FEATURES.json: path_changed=true, sha_changed=false, actual_sha256=876047db4ea4c76e39690c225ba4bd6480ad6cde74bed74ee62007dc547f6176.
- research/ashare_path_long_training_v1/TIME_SPLIT.json: path_changed=true, sha_changed=false, actual_sha256=f18e1144fb54eda8eb10f7836953114e43301c43d31a22434335ec7a21471995.
- research/ashare_path_long_training_v1/RESEARCH_REGISTRY.json: path_changed=true, sha_changed=true, actual_sha256=8ca642231a64bf5c78e3088ff31c98274143dcb726d02c58adb853c4d5e751d8.
