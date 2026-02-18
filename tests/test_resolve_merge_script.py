from __future__ import annotations

import subprocess
import sys
from pathlib import Path

START = "<" * 7
MID = "=" * 7
END = ">" * 7


def test_resolve_merge_markers_script_resolves_single_file(tmp_path):
    conflicted = tmp_path / "conflicted.py"
    conflicted.write_text(
        f"a\n{START} ours\nleft\n{MID}\nright\n{END} theirs\nb\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/resolve_merge_markers.py",
            str(conflicted),
            "--strategy",
            "incoming",
        ],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert conflicted.read_text(encoding="utf-8") == "a\nright\nb\n"
