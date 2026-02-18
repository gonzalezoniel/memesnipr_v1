from __future__ import annotations

from dataclasses import dataclass


START = "<" * 7
MID = "=" * 7
END = ">" * 7


@dataclass(frozen=True)
class ConflictBlock:
    current_lines: list[str]
    incoming_lines: list[str]


def parse_conflict_blocks(text: str) -> list[ConflictBlock]:
    lines = text.splitlines()
    blocks: list[ConflictBlock] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if not line.startswith(START):
            i += 1
            continue

        i += 1
        current: list[str] = []
        while i < len(lines) and not lines[i].startswith(MID):
            if lines[i].startswith(START):
                raise ValueError("Nested conflict markers are not supported")
            current.append(lines[i])
            i += 1

        if i >= len(lines):
            raise ValueError("Malformed conflict block: missing mid marker")

        i += 1
        incoming: list[str] = []
        while i < len(lines) and not lines[i].startswith(END):
            if lines[i].startswith(START):
                raise ValueError("Nested conflict markers are not supported")
            incoming.append(lines[i])
            i += 1

        if i >= len(lines):
            raise ValueError("Malformed conflict block: missing end marker")

        i += 1
        blocks.append(ConflictBlock(current_lines=current, incoming_lines=incoming))

    return blocks


def resolve_conflicts(text: str, strategy: str) -> str:
    if strategy not in {"current", "incoming", "both"}:
        raise ValueError("strategy must be one of: current, incoming, both")

    lines = text.splitlines()
    output: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        if not line.startswith(START):
            output.append(line)
            i += 1
            continue

        i += 1
        current: list[str] = []
        while i < len(lines) and not lines[i].startswith(MID):
            if lines[i].startswith(START):
                raise ValueError("Nested conflict markers are not supported")
            current.append(lines[i])
            i += 1

        if i >= len(lines):
            raise ValueError("Malformed conflict block: missing mid marker")

        i += 1
        incoming: list[str] = []
        while i < len(lines) and not lines[i].startswith(END):
            if lines[i].startswith(START):
                raise ValueError("Nested conflict markers are not supported")
            incoming.append(lines[i])
            i += 1

        if i >= len(lines):
            raise ValueError("Malformed conflict block: missing end marker")

        i += 1

        if strategy == "current":
            output.extend(current)
        elif strategy == "incoming":
            output.extend(incoming)
        else:
            output.extend(current)
            output.extend(incoming)

    return "\n".join(output) + ("\n" if text.endswith("\n") else "")
