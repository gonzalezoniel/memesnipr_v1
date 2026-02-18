#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.merge_markers import parse_conflict_blocks, resolve_conflicts

START = "<" * 7
MID = "=" * 7
END = ">" * 7
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__"}


def _has_conflict_markers(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return False

    for line in text.splitlines():
        if line.startswith((START, MID, END)):
            return True
    return False


def _iter_conflicted_files(root: Path):
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if _has_conflict_markers(path):
            yield path


def _resolve_file(path: Path, strategy: str) -> int:
    raw = path.read_text(encoding="utf-8")
    blocks = parse_conflict_blocks(raw)
    if not blocks:
        return 0

    resolved = resolve_conflicts(raw, strategy=strategy)
    path.write_text(resolved, encoding="utf-8")
    print(f"Resolved {len(blocks)} conflict block(s) in {path} using strategy={strategy}")
    return len(blocks)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve git conflict markers in one file or all files."
    )
    parser.add_argument("file", nargs="?", help="Path to conflicted file")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Resolve all conflicted files under the current directory",
    )
    parser.add_argument(
        "--strategy",
        choices=["current", "incoming", "both"],
        default="both",
        help="Resolution strategy to apply",
    )
    args = parser.parse_args()

    if args.all and args.file:
        print("Use either a file path or --all, not both.", file=sys.stderr)
        return 2

    if not args.all and not args.file:
        print("Provide a file path or use --all.", file=sys.stderr)
        return 2

    if args.all:
        conflicted = list(_iter_conflicted_files(Path(".")))
        if not conflicted:
            print("No conflicted files found.")
            return 0

        total_blocks = 0
        for path in conflicted:
            total_blocks += _resolve_file(path, strategy=args.strategy)
        print(f"Resolved {total_blocks} conflict block(s) across {len(conflicted)} file(s).")
        return 0

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"File not found: {file_path}", file=sys.stderr)
        return 2

    if not _has_conflict_markers(file_path):
        print(f"No conflict markers found in {file_path}")
        return 0

    _resolve_file(file_path, strategy=args.strategy)
    return 0


if __name__ == "__main__":
    sys.exit(main())
