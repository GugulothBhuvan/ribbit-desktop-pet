"""Soak monitor (MVP_PLAN Phase 8.4): launches the pet and samples its CPU%
and RSS against the PRD budgets (idle CPU < 1%, RAM < 300 MB).

Usage:
    python tools/soak_monitor.py --minutes 5 [--offscreen] [--no-api] [--csv out.csv]

--no-api blanks the API keys in the child environment so ambient triggers
cannot spend money during the soak; --offscreen renders without touching the
desktop. CPU% is normalized to all cores (task-manager style).
"""
import argparse
import csv
import os
import subprocess
import sys
import tempfile
import time

import psutil

RSS_BUDGET_MB = 300.0
IDLE_CPU_BUDGET_PCT = 1.0

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def main():
    parser = argparse.ArgumentParser(description="Desktop Pet soak monitor")
    parser.add_argument("--minutes", type=float, default=5.0)
    parser.add_argument("--interval", type=float, default=5.0, help="sample every N seconds")
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--no-api", action="store_true")
    parser.add_argument("--csv", default="")
    args = parser.parse_args()

    env = os.environ.copy()
    env["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="petsoak_"), "soak.db")
    if args.offscreen:
        env["QT_QPA_PLATFORM"] = "offscreen"
    if args.no_api:
        env["KRUTRIM_API_KEY"] = ""
        env["GEMINI_API_KEY"] = ""
        env["DEEPGRAM_API_KEY"] = ""

    proc = subprocess.Popen(
        [sys.executable, os.path.join("src", "main.py")],
        cwd=REPO_ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Launched pet (pid {proc.pid}); sampling every {args.interval}s for {args.minutes} min...")

    try:
        # Windows venv python.exe is a launcher stub that spawns the real
        # interpreter as a child — measure the whole process tree.
        time.sleep(2.0)  # let the real interpreter start
        root_ps = psutil.Process(proc.pid)
        tree = [root_ps] + root_ps.children(recursive=True)
        for p in tree:
            p.cpu_percent(None)  # prime the counters
        ncpu = psutil.cpu_count() or 1
        print(f"Measuring {len(tree)} process(es): {[p.pid for p in tree]}")

        samples = []
        deadline = time.time() + args.minutes * 60
        while time.time() < deadline:
            time.sleep(args.interval)
            if proc.poll() is not None:
                print(f"FAIL: app exited early with code {proc.returncode} "
                      "(another instance holding the single-instance mutex?)")
                sys.exit(2)
            cpu_total_pct = 0.0
            rss_mb = 0.0
            for p in tree:
                try:
                    cpu_total_pct += p.cpu_percent(None) / ncpu
                    rss_mb += p.memory_info().rss / (1024 * 1024)
                except psutil.NoSuchProcess:
                    pass
            samples.append((time.time(), cpu_total_pct, rss_mb))
            print(f"  cpu={cpu_total_pct:5.2f}%  rss={rss_mb:6.1f} MB")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    if not samples:
        print("No samples collected.")
        sys.exit(1)

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "cpu_pct", "rss_mb"])
            writer.writerows(samples)
        print(f"Samples written to {args.csv}")

    cpus = [s[1] for s in samples]
    rsss = [s[2] for s in samples]
    avg_cpu, max_cpu = sum(cpus) / len(cpus), max(cpus)
    max_rss = max(rsss)
    rss_growth = rsss[-1] - rsss[0]

    print("\n===== SOAK SUMMARY =====")
    print(f"samples: {len(samples)}  duration: {args.minutes} min")
    print(f"CPU avg: {avg_cpu:.2f}%   max: {max_cpu:.2f}%   (idle budget < {IDLE_CPU_BUDGET_PCT}%)")
    print(f"RSS max: {max_rss:.1f} MB               (budget < {RSS_BUDGET_MB} MB)")
    print(f"RSS growth first->last sample: {rss_growth:+.1f} MB")

    ok = avg_cpu < IDLE_CPU_BUDGET_PCT and max_rss < RSS_BUDGET_MB
    print("VERDICT:", "PASS" if ok else "OVER BUDGET")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
