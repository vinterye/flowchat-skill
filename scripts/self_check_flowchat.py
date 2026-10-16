#!/usr/bin/env python3
"""Run the standalone Flowchat hard gate with an exact browser receipt."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


HARNESS = Path(__file__).resolve().parents[1] / "harness" / "flowchat_local_harness.py"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the standalone Flowchat static and browser gate")
    parser.add_argument("html", type=Path)
    parser.add_argument("--browser-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    command = [sys.executable, str(HARNESS), str(args.html), "--browser-receipt", str(args.browser_receipt)]
    if args.output:
        command.extend(["--output", str(args.output)])
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
