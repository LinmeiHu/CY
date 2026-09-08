#!/bin/zsh
set -euo pipefail
cd /Users/linmei/Documents/CY-worktrees/five-strategy-scaling-regime-v1
export PYTHONPATH=.:src
py=/opt/anaconda3/bin/python
$py -m research.scaling_regime_v1.accounts --group identity_prefix --workers 2
$py -m research.scaling_regime_v1.protocol --freeze
$py -m research.scaling_regime_v1.freeze_attribution
$py -m research.scaling_regime_v1.accounts --group native --workers 3
$py -m research.scaling_regime_v1.accounts --group prefixes --workers 3
$py -m research.scaling_regime_v1.signal_prefix
$py -m research.scaling_regime_v1.closure_checks
