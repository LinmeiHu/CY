#!/usr/bin/env bash
set -euo pipefail
research_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$research_root"
research_python="${CY_RESEARCH_PYTHON:-/opt/anaconda3/bin/python3}"
export PYTHONPATH="$research_root/src${PYTHONPATH:+:$PYTHONPATH}"
research_external="$("$research_python" -c 'import json; print(json.load(open("research/five_strategy_exit_risk_v1/input_config.json"))["external_root"])')"
"$research_python" research/five_strategy_exit_risk_v1/run_v2.py --stage prepare
"$research_python" research/five_strategy_exit_risk_v1/run_v2.py --stage smv6
"$research_python" research/five_strategy_exit_risk_v1/run_v2.py --stage simple
"$research_python" research/five_strategy_exit_risk_v1/run_v2.py --stage information
"$research_python" research/five_strategy_exit_risk_v1/run_v2.py --stage accounts
"$research_python" research/five_strategy_exit_risk_v1/diagnostics_v2.py --minutes
"$research_python" research/five_strategy_exit_risk_v1/validate_v2.py
"$research_python" research/five_strategy_exit_risk_v1/figures_v2.py
"$research_python" -m pytest -q research/five_strategy_exit_risk_v1/test_v2.py tests/unit > "$research_external/final_tests.log" 2>&1
cat "$research_external/final_tests.log"
"$research_python" research/five_strategy_exit_risk_v1/report_v2.py
