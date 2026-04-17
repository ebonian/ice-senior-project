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
echo  Backtest Model Server Harness
echo  (Model server is assumed to already be running)
echo ============================================================
echo.

if defined CONFIG_PATH (
  echo Using config: "%CONFIG_PATH%"
) else (
  echo Using default config: config\backtest_config.yaml
)
echo.

echo [1/5] Pull raw data from B2...
if defined CONFIG_PATH (
  python scripts\01_pull_data.py --config "%CONFIG_PATH%"
) else (
  python scripts\01_pull_data.py
)
if errorlevel 1 goto :fail

echo.
echo [2/5] Build OHLCV and validate...
if defined CONFIG_PATH (
  python scripts\02_prepare_ohlcv.py --config "%CONFIG_PATH%"
) else (
  python scripts\02_prepare_ohlcv.py
)
if errorlevel 1 goto :fail

echo.
echo [3/5] Run inference backtest...
if defined CONFIG_PATH (
  python scripts\03_run_infer_backtest.py --config "%CONFIG_PATH%"
) else (
  python scripts\03_run_infer_backtest.py
)
if errorlevel 1 goto :fail

echo.
echo [4/5] Compute metrics...
if defined CONFIG_PATH (
  python scripts\04_compute_metrics.py --config "%CONFIG_PATH%"
) else (
  python scripts\04_compute_metrics.py
)
if errorlevel 1 goto :fail

echo.
echo [5/5] Generate dashboard plots...
if defined CONFIG_PATH (
  python scripts\05_plot_dashboard.py --config "%CONFIG_PATH%"
) else (
  python scripts\05_plot_dashboard.py
)
if errorlevel 1 goto :fail

echo.
echo [DONE] Backtest pipeline completed successfully.
echo Results: results\
echo Plots:   plots\
exit /b 0

:fail
echo.
echo [FAILED] Pipeline stopped due to an error.
exit /b 1

