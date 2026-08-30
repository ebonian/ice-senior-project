#!/usr/bin/env bash
# Fetch every RESOLVED candidate in the pre-registered priority order
# F1 -> F3 -> F2 -> F4 (abort criteria cut from the tail). Control uses
# e003's parquets and is not fetched.
set -u
cd "$(dirname "$0")/../.."
ORDER="weth_usdc_0p30 wsteth_weth_0p01 weeth_weth_0p01 wbtc_weth_0p05 wbtc_weth_0p30 arb_weth_0p05 arb_weth_0p30 pendle_weth_0p05 link_weth_0p05"
for slug in $ORDER; do
  case "$slug" in
    weth_usdc_0p30) span=100000 ;;
    *) span=200000 ;;
  esac
  echo "=== $slug (span $span) ==="
  nix develop .#gate1 -c python3 backtest_model_server/e005/fetch_pool_months.py \
    --slug "$slug" --span "$span" || echo "FETCH-ERROR $slug rc=$?"
done
echo "ALL FETCHES DONE"
