#!/usr/bin/env bash
# Resumable tail of the E005 pipeline: re-gate wbtc_weth_0p05 (429 crash),
# then fetch+gate+race the remaining F4 pools in pre-registered order.
# Appends to the same logs the live monitor tails.
set -u
cd "$(dirname "$0")/../.."
LOG=backtest_model_server/e005/out/process_all.log
run() { nix develop .#gate1 -c python3 "$@" >> "$LOG" 2>&1; }

echo "=== runner restart $(date -u +%H:%M:%S) ===" >> "$LOG"
run backtest_model_server/e005/coverage.py --slug wbtc_weth_0p05 || echo "COVERAGE-ERROR wbtc_weth_0p05 rc=$?" >> "$LOG"

for slug in arb_weth_0p05 arb_weth_0p30 pendle_weth_0p05 link_weth_0p05; do
  echo "=== fetch $slug ===" >> "$LOG"
  run backtest_model_server/e005/fetch_pool_months.py --slug "$slug" --span 200000 \
    || { echo "FETCH-ERROR $slug" >> "$LOG"; continue; }
  echo "=== processing $slug ===" >> "$LOG"
  run backtest_model_server/e005/coverage.py --slug "$slug" || echo "COVERAGE-ERROR $slug" >> "$LOG"
  [ -f "backtest_model_server/e005/out/$slug/lag1h_rh1h/results.json" ] || \
    run backtest_model_server/e005/race.py --slug "$slug" --detect-lag-hours 1 --rehedge-hours 1 \
    || echo "RACE-ERROR $slug" >> "$LOG"
  [ -f "backtest_model_server/e005/out/$slug/lag1h_rh0h/results.json" ] || \
    run backtest_model_server/e005/race.py --slug "$slug" --detect-lag-hours 1 --rehedge-hours 0 --tag lag1h_rh0h \
    || echo "RACE-ERROR $slug rh0h" >> "$LOG"
done
echo "ALL PROCESSING DONE" >> "$LOG"
echo "runner exited cleanly"
