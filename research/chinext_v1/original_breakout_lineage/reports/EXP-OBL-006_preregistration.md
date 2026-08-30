# EXP-OBL-006 preregistration

EXP-OBL-006 freezes parameter-free prebreakout positioning without accessing an
outcome. The primary feature is `log(close[t-1] / canonical prior-60 close
reference)`. Because t-1 belongs to the reference window, values are
non-positive; values nearer zero mean price was already positioned nearer the
level before the breakout session.

T-3 and T-5 versions using the same reference are fixed temporal neighbors. The
primary must have at least 300 distinct values, correlate at least 0.60 with each
neighbor, and have positive neighbor direction in at least seven of eight years.
It must also reconcile exactly to the frozen formation artifact and satisfy log
additivity with the signal-session displacement and breakout margin.

No outcome file is available to the runner. Signal breakout margin, reference
age, V1 entry state, and market context are reserved controls for a separate
reveal only if this feature freeze passes. No distance threshold, trading rule,
canonical V1 change, or CY-011 access is authorized.
