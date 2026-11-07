"""Text helpers that the paper guard and its tests share.

The guard reads the abstract through ``block_scalar_span``, and the mutation
tests place their edits with the same function, so both work on the same text.
"""

from __future__ import annotations

import re

FRONT_MATTER_ENDS = ("---", "...")
SIGNED_NUMBER = r"[−-]?\d[\d,]*(?:\.\d+)?"


def block_scalar_span(text: str, key: str) -> tuple[int, int] | None:
    """Character span of the literal block under the front matter's one
    top-level ``key: |`` line: the indented and blank lines that follow it, up
    to the next unindented line.

    Returns None when the text opens without front matter, the front matter
    never closes, the key appears other than exactly once as ``key: |``, or
    the block holds no text. Indented keys belong to other mappings and do not
    count, and a ``key: |`` line in the body lies outside the front matter.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        return None
    header = []
    offset = len(lines[0])
    for line in lines[1:]:
        if line.rstrip() in FRONT_MATTER_ENDS:
            break
        header.append((offset, line))
        offset += len(line)
    else:
        return None
    key_line = re.compile(rf"{re.escape(key)}\s*:")
    starts = [index for index, (_, line) in enumerate(header) if key_line.match(line)]
    if len(starts) != 1 or header[starts[0]][1].rstrip() != f"{key}: |":
        return None
    first = last = starts[0] + 1
    while last < len(header) and (
        not header[last][1].strip() or header[last][1][0] in " \t"
    ):
        last += 1
    block = header[first:last]
    if not "".join(line for _, line in block).strip():
        return None
    return block[0][0], block[-1][0] + len(block[-1][1])


def _whitespace_tolerant(part: str) -> str:
    """Regex for a template fragment in which any whitespace run matches any
    whitespace run in the text."""
    tokens = part.split()
    if not tokens:
        return r"\s+" if part else ""
    lead = r"\s+" if part[0].isspace() else ""
    trail = r"\s+" if part[-1].isspace() else ""
    return lead + r"\s+".join(re.escape(token) for token in tokens) + trail


def stated_values(template: str, text: str, value: str = SIGNED_NUMBER) -> list[str]:
    """Every value that ``text`` gives in the ``{}`` slot of ``template``, in
    order.

    By default the slot takes a signed number at numeric-token boundaries, so
    the text's "12.29" or "−2.29" never reads as "2.29". A template without
    exactly one slot matches nothing.
    """
    parts = template.split("{}")
    if len(parts) != 2:
        return []
    before, after = (_whitespace_tolerant(part) for part in parts)
    slot = rf"(?<![\d.,])({value})(?![\d]|[.,]\d)"
    return re.findall(before + slot + after, text)
