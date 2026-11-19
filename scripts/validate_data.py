#!/usr/bin/env python3
"""Validate that committed data JSON documents are syntactically valid."""
from __future__ import annotations
import json
from pathlib import Path
import sys

DATA = Path(__file__).resolve().parents[1] / "data"


def main() -> int:
    total = 0
    for path in sorted(DATA.rglob("*.json")):
        total += 1
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"ERROR: {path}: {exc}", file=sys.stderr)
            return 1
    for path in sorted(DATA.rglob("*.jsonl")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                try:
                    json.loads(line)
                except json.JSONDecodeError as exc:
                    print(f"ERROR: {path}:{number}: {exc}", file=sys.stderr)
                    return 1
        total += 1
    print(f"Validated {total} data JSON/JSONL file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
