#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

MARKERS = ("<" * 7, "=" * 7, ">" * 7)
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__"}


def iter_text_files(root: Path):
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def main() -> int:
    offenders: list[str] = []
    for path in iter_text_files(Path('.')):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue

        for line_no, line in enumerate(text.splitlines(), start=1):
            if line.startswith(MARKERS):
                offenders.append(f"{path}:{line_no}:{line}")

    if offenders:
        print("Unresolved merge markers found:")
        for row in offenders[:100]:
            print(row)
        if len(offenders) > 100:
            print(f"... and {len(offenders) - 100} more")
        return 1

    print("No unresolved merge markers found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
