#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from src.merge_markers import parse_conflict_blocks, resolve_conflicts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve git conflict markers in a file by strategy."
    )
    parser.add_argument("file", help="Path to conflicted file")
    parser.add_argument(
        "--strategy",
        choices=["current", "incoming", "both"],
        default="both",
        help="Resolution strategy to apply",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write result back to file (otherwise print to stdout)",
    )
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"File not found: {file_path}", file=sys.stderr)
        return 2

    raw = file_path.read_text(encoding="utf-8")
    blocks = parse_conflict_blocks(raw)
    if not blocks:
        print(f"No conflict markers found in {file_path}")
        return 0

    resolved = resolve_conflicts(raw, strategy=args.strategy)

    if args.write:
        file_path.write_text(resolved, encoding="utf-8")
        print(
            f"Resolved {len(blocks)} conflict block(s) in {file_path} using strategy={args.strategy}"
        )
        return 0

    print(resolved, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
