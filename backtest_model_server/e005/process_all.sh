#!/usr/bin/env bash
# Follow fetch_all.sh: as each pool's 4 months land, run coverage + both races.
set -u
cd "$(dirname "$0")/../.."
ORDER="wbtc_weth_0p05 wbtc_weth_0p30 arb_weth_0p05 arb_weth_0p30 pendle_weth_0p05 link_weth_0p05"
for slug in $ORDER; do
  until [ "$(ls backtest_model_server/e005/data/swaps/$slug/*.meta.json 2>/dev/null | wc -l)" -ge 4 ]; do
    sleep 30
  done
  echo "=== processing $slug ==="
  if [ ! -f "backtest_model_server/e005/out/$slug/lag1h_rh1h/results.json" ]; then
    nix develop .#gate1 -c python3 backtest_model_server/e005/coverage.py --slug "$slug" || echo "COVERAGE-ERROR $slug"
    nix develop .#gate1 -c python3 backtest_model_server/e005/race.py --slug "$slug" --detect-lag-hours 1 --rehedge-hours 1 || echo "RACE-ERROR $slug"
    nix develop .#gate1 -c python3 backtest_model_server/e005/race.py --slug "$slug" --detect-lag-hours 1 --rehedge-hours 0 --tag lag1h_rh0h || echo "RACE-ERROR $slug rh0h"
  fi
done
echo "ALL PROCESSING DONE"
