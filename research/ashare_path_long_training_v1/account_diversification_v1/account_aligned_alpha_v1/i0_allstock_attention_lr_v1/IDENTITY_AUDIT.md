# I0 all-stock attention identity audit

- Repository: `/Users/linmei/Documents/CY-worktrees/minute-ret5-multiscale-autonomous-v2`
- Branch: `codex/minute-ret5-multiscale-autonomous-v2`
- HEAD: `2d6865f25324d5d2d6ac8532d4238af4e2693ed4`
- Authoritative inner checkpoint: `/Volumes/quant/CY_quant_research/ashare_path_long_training_v1/account_diversification_v1/o2_nested_earlystop_v1/2020_s17/step32768.pt` (`3da936f818f307cedde4e3f3e7a0e1f7c4c57a25637e17c75f40b42dda4b1024`)
- Representation H: the 32-dimensional `core.fusion` output `z`, immediately before `core.pred`.
- Base path: `PathResidual` adds the frozen M0 Ret10/20/40 offsets after `core.pred`.
- CENTERED: separately fitted continuous relative-Ret20 readout over date-demeaned H; per-seed daily percentile then fixed3 mean.
- Account: RAW-positive admission, fixed Top10, H10, exact cash-only legal engine, independent RMB 1,000,000 per year.
- Optimizer/objective: AdamW, frozen weight decay/betas, O2 smooth-L1 Ret10/20/40 plus frozen auxiliary BCE and consistency.
- Zero-output relation identity: PASS (prediction max abs `0`).
- Frozen I0 cache parity: PASS (prediction `1.86e-08`, embedding `1.19e-07`).
- 2020 account parity: PASS (return `17.43961631%`, MaxDD `15.31343772%`).
- Minute model/data: disabled / not loaded.
