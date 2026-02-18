import pytest

from src.merge_markers import parse_conflict_blocks, resolve_conflicts


MARKER_START = "<" * 7
MARKER_MID = "=" * 7
MARKER_END = ">" * 7

CONFLICTED = f"""line_a
{MARKER_START} current
old_1
old_2
{MARKER_MID}
new_1
new_2
{MARKER_END} incoming
line_b
"""


def test_parse_conflict_blocks_finds_sections():
    blocks = parse_conflict_blocks(CONFLICTED)
    assert len(blocks) == 1
    assert blocks[0].current_lines == ["old_1", "old_2"]
    assert blocks[0].incoming_lines == ["new_1", "new_2"]


def test_resolve_conflicts_current_strategy():
    resolved = resolve_conflicts(CONFLICTED, strategy="current")
    assert resolved == "line_a\nold_1\nold_2\nline_b\n"


def test_resolve_conflicts_incoming_strategy():
    resolved = resolve_conflicts(CONFLICTED, strategy="incoming")
    assert resolved == "line_a\nnew_1\nnew_2\nline_b\n"


def test_resolve_conflicts_both_strategy():
    resolved = resolve_conflicts(CONFLICTED, strategy="both")
    assert resolved == "line_a\nold_1\nold_2\nnew_1\nnew_2\nline_b\n"


def test_parse_conflict_blocks_raises_on_malformed():
    malformed = f"""x
{MARKER_START} current
left
{MARKER_MID}
right
"""
    with pytest.raises(ValueError):
        parse_conflict_blocks(malformed)
