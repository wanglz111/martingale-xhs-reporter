#!/usr/bin/env python3
"""
Simple scheduler: run xhs_summary once immediately, then daily at 17:00 UTC.
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
import time
from typing import Sequence


def seconds_until_next_run(target_hour: int = 17) -> float:
    now = dt.datetime.now(dt.timezone.utc)
    target = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target = target + dt.timedelta(days=1)
    return (target - now).total_seconds()


def run_once(state_file: str) -> int:
    return subprocess.call(
        [sys.executable, "xhs_summary.py", "--state-file", state_file],
    )


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Loop runner for xhs_summary.")
    parser.add_argument("--state-file", required=True, help="Path to state.runtime.yaml")
    parser.add_argument("--hour", type=int, default=2, help="UTC hour to run daily (default 2 = 10:00 Beijing)")
    args = parser.parse_args(argv)

    # immediate run
    rc = run_once(args.state_file)
    if rc != 0:
        print(f"[warn] first run exited with {rc}", file=sys.stderr)

    while True:
        sleep_sec = seconds_until_next_run(args.hour)
        time.sleep(max(0, sleep_sec))
        rc = run_once(args.state_file)
        if rc != 0:
            print(f"[warn] scheduled run exited with {rc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
