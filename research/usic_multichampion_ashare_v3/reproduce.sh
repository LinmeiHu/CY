#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
exec /Users/linmei/Documents/CY/.venv/bin/python -u -m research.usic_multichampion_ashare_v3.validate_delivery "$@"
