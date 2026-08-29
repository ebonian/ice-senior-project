#!/usr/bin/env bash
# E003 end to end. Run from the research repo root.
#
#   bash backtest_model_server/e003/run_all.sh
#
# Steps 3-6 need no network: they are a pure function of the parquets under
# e003/data/swaps/ and the recorded funding CSV, so they reproduce byte-identical
# results offline. Step 1 re-fetches chain data (~20 min/month on the public
# endpoint; already-assembled months are skipped) and step 2 re-verifies it
# against chain.
set -euo pipefail

R="nix develop .#gate1 -c python"
E=backtest_model_server/e003

# 1. Data. RPC only — issue Y forbids the B2 path. Months already assembled are
#    skipped; the fetch is phased and resumable if the endpoint throttles.
$R $E/fetch_months.py --start 2026-05-01 --end 2026-08-28

# 2. Coverage gate. No window enters the race below full coverage.
$R $E/coverage.py

# 3. Contracts: width mapping, frozen constants, envelope arithmetic.
$R $E/tests/test_e003_contracts.py

# 4. Data provenance: E003's month-scale pull must reproduce gate1's T5 cycle
#    fees exactly, using gate1's own fee engine and gate1's own liquidity.
$R $E/tests/test_vs_gate1_t5.py

# 5. The race. The first is the pre-registered policy; the rest are sensitivity
#    runs, reported separately and never used for the verdict.
$R $E/race.py --tag lag0h_rh1h                          # pre-registered
$R $E/race.py --detect-lag-hours 1 --tag lag1h_rh1h     # 1h decision loop
$R $E/race.py --rehedge-hours 4  --tag lag0h_rh4h       # slower rehedge
$R $E/race.py --rehedge-hours 0  --tag lag0h_rhrec      # rehedge only on recenter

# 6. Tables. Every number in REPORT.md comes from here.
for t in lag0h_rh1h lag1h_rh1h lag0h_rh4h lag0h_rhrec; do
  $R $E/tables.py --run "$t" --verdict > "$E/out/$t/tables.md"
done
echo "done — see $E/out/*/tables.md"
