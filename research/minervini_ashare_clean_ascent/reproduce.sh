#!/bin/bash
set -euo pipefail
cd /Users/linmei/Documents/CY-worktrees/minervini-ashare-clean-ascent-20260908
research_python=/Users/linmei/Documents/CY/.venv/bin/python
plot_python=/Volumes/quant/CY_quant_research/minervini_ashare_clean_ascent_v2/plot_runtime/bin/python
package=research.minervini_ashare_clean_ascent
case "${1:-verify}" in
  verify)
    "$research_python" -m "$package.verify_artifacts"
    "$research_python" -m unittest "$package.test_semantics" -v
    "$research_python" -m "$package.verify_features"
    "$research_python" -m "$package.verify_repeat"
    ;;
  cached|full)
    if [[ "$1" == full ]]; then "$research_python" -u -m "$package.prepare"; fi
    "$research_python" -u -m "$package.check_features"
    "$research_python" -m unittest "$package.test_semantics" -v
    "$research_python" -u -m "$package.verify_features"
    "$research_python" -u -m "$package.replay"
    "$research_python" -u -m "$package.diagnose"
    "$research_python" -u -m "$package.finalize"
    "$research_python" -u -m "$package.supplement"
    "$research_python" -u -m "$package.verify_repeat"
    "$plot_python" -m "$package.plot"
    "$research_python" -m "$package.write_report"
    ;;
  *) echo 'usage: reproduce.sh [verify|cached|full]' >&2; exit 2 ;;
esac
