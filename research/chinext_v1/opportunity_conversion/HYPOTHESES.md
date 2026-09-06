# Hypotheses

All hypotheses are frozen before the corresponding new experiment is run.
Path-outcome hypotheses explain mechanism location; only entry/decision-time
hypotheses can later support a candidate.

## Opportunity supply and quality

### OC-H001 — opportunity supply

Higher continuous breadth increases the number or rate of authoritative V1
entry candidates, conditional on a reconciled candidate-event denominator.

**Final status:** partially supported. Candidate count/rate has rho 0.215/0.233
and 8/8 positive LOYO but only 5/8 yearly signs. Supply rises, but not uniformly
by year.

### OC-H002 — selected-trade opportunity quality

Among completed V1 trades, higher entry breadth increases MFE/right-tail
availability and may shorten time-to-MFE, but does not reliably increase
capture conditional on MFE.

**Final status:** supported except for timing direction. Breadth->MFE and
opportunity are robust, while terminal/capture are mixed. MFE occurs later, not
earlier, relative to the eventual holding period.

### OC-H003 — dispersion rather than uniform lift

Breadth widens the selected-trade opportunity distribution or increases its
right tail more than it shifts the median single-trade opportunity.

**Final status:** strongly supported. Breadth relates to market return20
standard deviation, p90-p10 spread, and right-tail frequency in 8/8 years and
8/8 LOYO; selected-trade terminal medians stay negative in all five breadth
quintiles.

## Winner versus false positive

### OC-H004 — causal entry separation

Existing PIT stock-level features exhibit continuous, economically coherent,
cross-year separation between future right-tail winners and false
positives/severe losers after conditioning on breadth and year.

### OC-H005 — entry separation is weak or unstable

The same causal entry features fail LOYO, neighboring-definition, or
extreme-trade stability, implying that ex-post classes are not reliably
selectable at entry.

OC-H004 and OC-H005 are competing interpretations; the evidence must falsify
at least one.

**Current evidence:** OC-H004 is not supported and OC-H005 is supported before
final extreme/top-N sensitivity: 0/54 frozen causal feature/outcome pairs pass
the combined gate.

**Final status:** OC-H004 rejected; OC-H005 supported. The final audits add
0/135 neighboring-definition passes and 0/27 Breadth x stock-feature passes.
The candidate-pool audit shows selected candidates are modestly better, not
worse, and only 30/259 selection days have a covered alternative.

## MFE monetization

### OC-H006 — path timing and persistence locate leakage

Conditional on MFE >=20%, capture is associated with earlier peaks, lower
pre-MFE adversity, smoother pre-peak paths, and lower post-peak decay.

**Current evidence:** partially falsified as written. Lower post-peak decay
locates better capture, but later—not earlier—MFE is associated with better
capture because it leaves fewer sessions for giveback. This is descriptive
holding-path geometry, not a causal exit signal.

**Final status:** partially falsified. Leakage location is stable; the proposed
earlier-peak direction is wrong and the stable fields are hindsight outcomes.

### OC-H007 — exit lineage locates leakage

Conditional on the same MFE band, capture and giveback differ materially and
stably by canonical exit reason and holding duration.

**Final status:** descriptive differences are supported, but a causal exit
improvement is rejected. Disabling either exit family lowers total return, and
winner-hold fails OOS.

### OC-H008 — breadth does not explain monetization

After conditioning on MFE magnitude and year, entry breadth has no stable
relationship with MFE realization, conversion, or giveback.

**Current evidence:** provisionally supported in economic terms. Conditional
capture correlations are small and yearly signs mixed; final robustness
remains.

**Final status:** supported. Capture rolling windows are mixed and no
continuous interaction passes.

## Entry versus exit ceilings

### OC-H009 — selection ceiling dominates

Fixed-ledger false-positive/severe-loss avoidance has a larger stable
diagnostic ceiling than recovery of post-MFE giveback.

**Current evidence:** not supported by raw ceiling magnitude, although the two
ceilings are not directly comparable or additive. False-breakout avoidance is
1.809m versus a 2.243m opportunity20 peak-close giveback oracle.

**Final status:** rejected as a simple dominance claim.

### OC-H010 — exit ceiling dominates

Fixed-ledger MFE/peak giveback and post-exit continuation show a larger stable
diagnostic ceiling than entry filtering, and frozen executable exit
counterfactuals are directionally consistent.

**Current evidence:** partially falsified. The exit oracle is larger, but
frozen executable counterfactuals are not directionally consistent across
years and winner-hold fails OOS.

**Final status:** rejected as an actionable dominance claim.

### OC-H011 — apparent ceilings are not actionable

Large hindsight ceilings fail causal predictability, cross-year stability, or
authoritative replay counterfactuals; neither selection nor exit supports an
implementable change.

**Current evidence:** strongly supported provisionally; final robustness and
strategy-gate audit remain.

**Final status:** supported.

## Strategy gate

### OC-H012 — minimum sufficient improvement exists

At least one decision-time variable passes all strategy-design gates and
supports a minimal entry, exit, or holding modification.

**Final status:** rejected.

### OC-H013 — stop without V2

No decision-time variable passes the gate; the correct result is explanation
and falsification, not a forced strategy.

**Final status:** supported.

OC-H012 and OC-H013 are mutually exclusive terminal hypotheses.
