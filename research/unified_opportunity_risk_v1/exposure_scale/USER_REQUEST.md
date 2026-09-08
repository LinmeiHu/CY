# Candidate B exposure-scale diagnostic — 2026-09-09

Freeze Candidate B R1_RP100_S10_F1. Preserve opportunity producers/population rules, R1, discovery calibration, quality threshold, Native exits, signal timing and execution rules. Do not optimize X or change KEEP_NATIVE based on this diagnostic.

Run X=1,1.5,2,3,5,8,10,MAX_FILL as real continuous physical accounts through 2026-09-04. User explicitly confirmed: B_i is Candidate-B baseline target calculated at the current diagnostic account NAV, not the historical B account's absolute filled amount. For finite X, request X*B_i and scale RP soft budgets together. Retain gross<=100%, no borrowing/margin, cash>=0 under Native numerical precision, 10% hard single-security admission cap, shared-security aggregation and registered liquidity/execution limits. Do not renormalize existing holdings; preserve Native reductions/exits.

MAX_FILL removes all RP/family soft budgets and uses R1 order to request maximum legal hard-constrained notional. It is an extreme diagnostic, not a production candidate.

Report 2018–2021,2022–2023,2024,2025,2026 YTD,full; also annual rows. Required metrics: CAGR,MaxDD,CVaR5,Sharpe,average/P95/max gross,cash ratio,days gross>25/50/75/90 and >=99%,turnover,fees,worst month,max security/family,capacity diagnostics.

Attribute unused cash to NO_QUALIFYING_OPPORTUNITY,SINGLE_SECURITY_CAP,LIQUIDITY_CAP,GROSS_CAP,CASH_EXHAUSTED,SOFT_RISK_BUDGET,FAMILY_RISK_BUDGET. MAX_FILL has no soft/family budget. Explain the attribution definition and avoid double-counting cash/gross constraints.

Deliver candidate_b_exposure_scale_metrics.csv, candidate_b_exposure_scale_yearly.csv, candidate_b_unused_cash_attribution.csv, candidate_b_exposure_scale_nav.png, candidate_b_exposure_scale_drawdown.png, candidate_b_exposure_scale_gross.png.

Explicitly answer speed of gross increase, point where additional scale stops improving CAGR, acceleration of MaxDD/CVaR, insufficient qualifying opportunities versus risk budget, whether existing strategies can use most capital without low-quality opportunities, and the MAX_FILL extreme bound.

Additional user instruction: put ALL eight account curves on ONE dual-axis plot, with the Shanghai Composite and Shenzhen Component on the other axis. Communicated display convention: account NAV/initial inherited NAV on left, both benchmark price indices normalized to first close=100 on right. Benchmarks display only.

User clarification: 冻结原始信号来源，允许原生持仓状态改变合法请求。Do not filter to only the historical Candidate-B request log.
