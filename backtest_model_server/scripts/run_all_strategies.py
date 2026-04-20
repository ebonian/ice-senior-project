"""
Parallel multi-strategy backtest driver.

For every strategy in `config/backtest_config.yaml :: strategies`:
  1. Spawn `03_run_infer_backtest.py` in parallel (one child process per strategy,
     all hitting the same model server). Each child writes to
     results/<strategy>/ and its full stdout+stderr is teed live to the
     orchestrator console AND to results/<strategy>/run.log.
  2. Once all inference runs finish, run `04_compute_metrics.py` and
     `05_plot_dashboard.py` per strategy (in parallel — fast, CPU-bound).
  3. Run `06_compare_strategies.py` to produce comparison.md + comparison.png.

Usage (from backtest_model_server/):
    python scripts/run_all_strategies.py
    python scripts/run_all_strategies.py --config config/backtest_config.yaml
    python scripts/run_all_strategies.py --resume         # forwarded to step 3
    python scripts/run_all_strategies.py --strategies simulation_14_1h simulation_14_5min

Notes:
  - Each `reference_date` inference call triggers a fresh B2 fetch on the
    model server, so parallelism is bounded by the server's
    MAX_CONCURRENT_INFERENCES (default: 4). Three strategies × 1 worker each
    is safely under that cap.
  - If any step-3 child exits non-zero, the orchestrator still attempts
    metrics/plots for the strategies that succeeded, then runs comparison
    across whichever subset produced artifacts.
"""

import sys
import os
import time
import logging
import argparse
import subprocess
import threading
from pathlib import Path
from typing import Optional

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR   = SCRIPT_DIR.parent

# Mirror child output faithfully on Windows consoles (default cp1252 chokes on
# common unicode like "→" / "×" that appears in summary prints).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [orchestrator] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_strategies(cfg: dict, override: Optional[list[str]]) -> list[str]:
    if override:
        return override
    s = cfg.get("strategies")
    if isinstance(s, list) and s:
        return [str(x) for x in s]
    single = cfg.get("strategy")
    if single:
        return [str(single)]
    return []


# ---------------------------------------------------------------------------
# Streaming subprocess runner
# ---------------------------------------------------------------------------

def _stream_to(stream, prefix: str, log_fh, out_stream) -> None:
    """Read lines from a subprocess stream, mirror to console + log file.

    Prefixing here (on top of the child's own `--log-prefix`) makes it easy
    to spot which strategy a stderr traceback came from even when the child
    crashed before its logger was configured.
    """
    for raw in iter(stream.readline, b""):
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        console_line = f"[{prefix}] {line}" if prefix else line
        print(console_line, file=out_stream, flush=True)
        log_fh.write(line + "\n")
        log_fh.flush()
    stream.close()


def run_child(
    cmd: list[str],
    cwd: Path,
    prefix: str,
    log_path: Path,
) -> int:
    """Run `cmd`, stream output live, tee to log_path. Returns exit code."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("starting: %s  →  log=%s", " ".join(cmd), log_path)

    # line-buffered so each print() from the child flushes promptly
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    # Force UTF-8 on child stdout/stderr so prints of "→" / "×" don't crash
    # the child under Windows' default cp1252 code page (stdout is a pipe,
    # which Python otherwise encodes using the system locale).
    env["PYTHONIOENCODING"] = "utf-8"

    with open(log_path, "w", encoding="utf-8") as log_fh:
        log_fh.write(f"# cmd: {' '.join(cmd)}\n")
        log_fh.write(f"# cwd: {cwd}\n")
        log_fh.write(f"# started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_fh.flush()

        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

        t_out = threading.Thread(
            target=_stream_to, args=(proc.stdout, prefix, log_fh, sys.stdout),
            daemon=True,
        )
        t_err = threading.Thread(
            target=_stream_to, args=(proc.stderr, prefix, log_fh, sys.stderr),
            daemon=True,
        )
        t_out.start()
        t_err.start()

        rc = proc.wait()

        t_out.join(timeout=5)
        t_err.join(timeout=5)

        log_fh.write(f"# finished: {time.strftime('%Y-%m-%d %H:%M:%S')} rc={rc}\n")

    return rc


# ---------------------------------------------------------------------------
# Parallel stage runner
# ---------------------------------------------------------------------------

def run_in_parallel(jobs: list[dict]) -> dict[str, int]:
    """Start every job on its own thread (each thread spawns a subprocess).

    jobs: list of dicts with keys: cmd, cwd, prefix, log_path, key (strategy name)
    Returns: {strategy_key: exit_code}
    """
    results: dict[str, int] = {}
    threads: list[threading.Thread] = []

    def _target(job):
        rc = run_child(job["cmd"], job["cwd"], job["prefix"], job["log_path"])
        results[job["key"]] = rc

    for j in jobs:
        t = threading.Thread(target=_target, args=(j,), daemon=False)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run model server backtest for all configured strategies in parallel, then compare.",
    )
    parser.add_argument("--config", default=str(BASE_DIR / "config" / "backtest_config.yaml"))
    parser.add_argument("--strategies", nargs="+", default=None,
                        help="Override strategies list from config.")
    parser.add_argument("--resume", action="store_true",
                        help="Forwarded to 03_run_infer_backtest.py (--resume).")
    parser.add_argument("--skip-inference", action="store_true",
                        help="Skip step 3 (assume trace_df.parquet already exists per strategy).")
    parser.add_argument("--skip-plots", action="store_true",
                        help="Skip step 5 (plot dashboard) per strategy.")
    parser.add_argument("--skip-compare", action="store_true",
                        help="Skip step 6 (comparison).")
    args = parser.parse_args()

    cfg_path   = Path(args.config)
    cfg        = load_config(cfg_path)
    strategies = resolve_strategies(cfg, args.strategies)

    if not strategies:
        log.error("No strategies configured. Set `strategies:` in %s (list) or pass --strategies.",
                  cfg_path)
        return 2

    results_dir = BASE_DIR / cfg.get("output_dir", "results")
    results_dir.mkdir(parents=True, exist_ok=True)

    log.info("=" * 72)
    log.info("Multi-strategy backtest")
    log.info("Config: %s", cfg_path)
    log.info("Strategies (%d): %s", len(strategies), ", ".join(strategies))
    log.info("Date range: %s → %s", cfg.get("start_date"), cfg.get("end_date"))
    log.info("Server: %s", cfg.get("server_url"))
    log.info("Results root: %s", results_dir)
    log.info("=" * 72)

    python_exe = sys.executable
    step3 = SCRIPT_DIR / "03_run_infer_backtest.py"
    step4 = SCRIPT_DIR / "04_compute_metrics.py"
    step5 = SCRIPT_DIR / "05_plot_dashboard.py"
    step6 = SCRIPT_DIR / "06_compare_strategies.py"

    # ------------------------------------------------------------------
    # Step 3 — parallel inference
    # ------------------------------------------------------------------
    infer_results: dict[str, int] = {}
    if args.skip_inference:
        log.info("--skip-inference set; skipping step 3.")
        infer_results = {s: 0 for s in strategies}
    else:
        log.info("Step 3/5 — running inference for %d strategies in parallel...", len(strategies))
        jobs = []
        for s in strategies:
            cmd = [
                python_exe, str(step3),
                "--config", str(cfg_path),
                "--strategy", s,
                "--output-subdir", s,
                "--log-prefix", s,
            ]
            if args.resume:
                cmd.append("--resume")
            jobs.append({
                "key":      s,
                "cmd":      cmd,
                "cwd":      BASE_DIR,
                "prefix":   s,
                "log_path": results_dir / s / "run.log",
            })
        t0 = time.time()
        infer_results = run_in_parallel(jobs)
        elapsed = time.time() - t0
        log.info("Step 3 done in %.1fs. Results: %s", elapsed, infer_results)

    succeeded = [s for s, rc in infer_results.items() if rc == 0]
    failed    = [s for s, rc in infer_results.items() if rc != 0]
    if failed:
        log.warning("Step 3 FAILED for: %s  (continuing with %d that succeeded)",
                    ", ".join(failed), len(succeeded))

    if not succeeded:
        log.error("No strategies produced traces; aborting before metrics/plots.")
        return 1

    # ------------------------------------------------------------------
    # Step 4 — metrics (parallel per strategy)
    # ------------------------------------------------------------------
    log.info("Step 4/5 — computing metrics for %d strategies in parallel...", len(succeeded))
    jobs = [{
        "key":      s,
        "cmd":      [python_exe, str(step4),
                     "--config", str(cfg_path),
                     "--strategy", s,
                     "--output-subdir", s,
                     "--log-prefix", s],
        "cwd":      BASE_DIR,
        "prefix":   s,
        "log_path": results_dir / s / "metrics.log",
    } for s in succeeded]
    t0 = time.time()
    metrics_results = run_in_parallel(jobs)
    log.info("Step 4 done in %.1fs. Results: %s", time.time() - t0, metrics_results)
    metrics_ok = [s for s, rc in metrics_results.items() if rc == 0]

    # ------------------------------------------------------------------
    # Step 5 — plots (parallel per strategy)
    # ------------------------------------------------------------------
    if args.skip_plots:
        log.info("--skip-plots set; skipping step 5.")
    else:
        log.info("Step 5/5 — rendering dashboards for %d strategies in parallel...", len(metrics_ok))
        jobs = [{
            "key":      s,
            "cmd":      [python_exe, str(step5),
                         "--config", str(cfg_path),
                         "--output-subdir", s,
                         "--plots-subdir", s,
                         "--log-prefix", s],
            "cwd":      BASE_DIR,
            "prefix":   s,
            "log_path": results_dir / s / "plots.log",
        } for s in metrics_ok]
        t0 = time.time()
        plot_results = run_in_parallel(jobs)
        log.info("Step 5 done in %.1fs. Results: %s", time.time() - t0, plot_results)

    # ------------------------------------------------------------------
    # Step 6 — comparison
    # ------------------------------------------------------------------
    compare_rc = 0
    if args.skip_compare:
        log.info("--skip-compare set; skipping step 6.")
    elif len(metrics_ok) < 2:
        log.warning("Only %d strategy produced metrics; skipping comparison (need ≥2).",
                    len(metrics_ok))
    else:
        log.info("Step 6 — comparing %d strategies...", len(metrics_ok))
        compare_rc = run_child(
            [python_exe, str(step6),
             "--config", str(cfg_path),
             "--strategies", *metrics_ok],
            cwd=BASE_DIR,
            prefix="compare",
            log_path=results_dir / "comparison.log",
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    log.info("=" * 72)
    log.info("Summary:")
    for s in strategies:
        infer_rc = infer_results.get(s, "skipped")
        metrics_rc = metrics_results.get(s, "-") if not args.skip_inference or s in succeeded else "-"
        log.info("  %-28s  infer=%s  metrics=%s", s, infer_rc, metrics_rc)
    log.info("  comparison: rc=%s", compare_rc if not args.skip_compare else "skipped")
    log.info("Results root: %s", results_dir)
    log.info("=" * 72)

    return 0 if (not failed and compare_rc == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
