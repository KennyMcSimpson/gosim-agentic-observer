#!/usr/bin/env python3
"""Verify that every engine/scoring module under runner/challenge and runner/project_platform
is still byte-identical to what ENGINE_MANIFEST.json recorded (sha256 of each file). Run this
before trusting a local score if you are at all unsure the files were not touched.

    python3 verify_engine.py

Exit code 0 = every file matches; 1 = a file is missing or its hash differs.
Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    manifest_path = ROOT / "ENGINE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ok = True
    for entry in manifest["files"]:
        path = ROOT / entry["runner_path"]
        if not path.is_file():
            print(f"MISSING  {entry['runner_path']}")
            ok = False
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry["sha256"]:
            print(f"MISMATCH {entry['runner_path']}  expected={entry['sha256']}  actual={actual}")
            ok = False
        else:
            print(f"ok       {entry['runner_path']}")
    if ok:
        print(f"\nAll {len(manifest['files'])} engine files match ENGINE_MANIFEST.json "
              f"(source commit {manifest['source_commit']}).")
    else:
        print("\nEngine files do NOT match the manifest -- local scores from this copy are not "
              "guaranteed identical to the platform. Re-copy runner/ from a trusted source.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
