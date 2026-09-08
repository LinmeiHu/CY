#!/bin/zsh
set -e
cd /Users/linmei/Documents/CY-worktrees/five-strategy-scaling-regime-v1
export PYTHONPATH=.:src
while [[ ! -f research/scaling_regime_v1/output/annual_scaling_mechanics_comparison.csv ]]; do sleep 10; done
/opt/anaconda3/bin/python -m research.scaling_regime_v1.states
/opt/anaconda3/bin/python -c 'from research.scaling_regime_v1.capital_state import portfolio_states; portfolio_states()'
/opt/anaconda3/bin/python -m research.scaling_regime_v1.comparisons
/opt/anaconda3/bin/python -m research.scaling_regime_v1.scaling_postcheck
