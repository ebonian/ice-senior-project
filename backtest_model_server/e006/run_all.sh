#!/usr/bin/env bash
# E006 end to end. Pure local computation on E003's committed parquets —
# no network. From the repo root:
#   bash backtest_model_server/e006/run_all.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

R="nix develop .#gate1 -c python3"
E=backtest_model_server/e006

echo "== stage 1: per-hour payoffs + DP upper bound =="
$R $E/oracle.py

echo "== stage 2: exact simulation of the selected policy =="
$R $E/exact.py

echo "== descriptive signals (NOT part of the verdict) =="
$R $E/signals.py

echo "== contract tests (blocking) =="
$R $E/tests/test_e006_contracts.py

echo "== tables + pre-registered decision rule =="
$R $E/tables.py
