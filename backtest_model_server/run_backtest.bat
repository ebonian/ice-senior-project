@echo off
setlocal EnableExtensions

cd /d "%~dp0" || (
  echo [ERROR] Failed to change directory to script location.
  exit /b 1
)

set "CONFIG_PATH="
if not "%~1"=="" set "CONFIG_PATH=%~1"

echo.
echo ============================================================
echo  Backtest Model Server Harness (multi-strategy, parallel)
echo  (Model server is assumed to already be running)
echo ============================================================
echo.

if defined CONFIG_PATH (
  echo Using config: "%CONFIG_PATH%"
) else (
  echo Using default config: config\backtest_config.yaml
)
echo.

echo [1/3] Pull raw data from B2...
if defined CONFIG_PATH (
  python scripts\01_pull_data.py --config "%CONFIG_PATH%"
) else (
  python scripts\01_pull_data.py
)
if errorlevel 1 goto :fail

echo.
echo [2/3] Build OHLCV and validate...
if defined CONFIG_PATH (
  python scripts\02_prepare_ohlcv.py --config "%CONFIG_PATH%"
) else (
  python scripts\02_prepare_ohlcv.py
)
if errorlevel 1 goto :fail

echo.
echo [3/3] Run inference + metrics + plots + comparison for all strategies in parallel...
if defined CONFIG_PATH (
  python scripts\run_all_strategies.py --config "%CONFIG_PATH%"
) else (
  python scripts\run_all_strategies.py
)
if errorlevel 1 goto :fail

echo.
echo [DONE] Multi-strategy backtest pipeline completed successfully.
echo Per-strategy results: results\^<strategy^>\
echo Per-strategy plots:   plots\^<strategy^>\
echo Comparison:           results\comparison.md  plots\comparison.png
exit /b 0

:fail
echo.
echo [FAILED] Pipeline stopped due to an error.
exit /b 1
