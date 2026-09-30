"""Console helper for a frozen GUI to run an agent over JSONL stdio."""

from __future__ import annotations

import dataclasses  # bundled standard-library dependencies for external agent files
import datetime
import json
import math
import os
import runpy
import sys
import typing
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "-B":
        print("Usage: PracticeAgentHost -B <agent.py>", file=sys.stderr)
        return 2
    entry = Path(sys.argv[2]).resolve()
    if not entry.is_file() or entry.suffix.lower() != ".py":
        print(f"Agent script not found: {entry}", file=sys.stderr)
        return 2
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(entry.parent))
    sys.argv = [str(entry)]
    runpy.run_path(str(entry), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
