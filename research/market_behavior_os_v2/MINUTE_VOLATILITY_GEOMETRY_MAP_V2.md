# Minute-volatility path geometry map V2

MKT-MIN-VOL-GEO-002 is an exact semantic retry of the scientific design frozen
in `MINUTE_VOLATILITY_GEOMETRY_MAP.md` and MKT-MIN-VOL-GEO-001 spec
`d1f67d05...`.

The first construction stopped before computing any correlation because the
single 2019-2023 group/year list incorrectly applied the 150-observation gate
to causal PIT coordinates in 2019. The frozen inputs correctly leave those PIT
coordinates missing during their 504-observation warm-up. The audit also shows
that 2020 has only 102-107 daily-control PIT observations in a representative
group, below the unchanged 150 gate. No result or geometry artifact was made.

The only correction is explicit coordinate-specific cell eligibility:

- raw absolute cells: 2019-2023;
- causal PIT cells and PIT geometry: complete years 2021-2023;
- relative cells and relative geometry: 2019-2023.

The exact 10,696-row common population remains unchanged. Absolute and joint
raw-rank geometry continue to use all common rows from 2018-07-03. PIT geometry
uses only 2021-2023, rather than lowering the 150-observation gate or mixing
incomplete warm-up cells. Relative geometry uses 2019-2023. The target,
controls, input hashes, 0.85 pairwise threshold, 0.70/0.85 joint reconstruction
thresholds, availability, prohibitions, and claim boundary are unchanged.

This correction is frozen before any pairwise or joint geometry is computed.
