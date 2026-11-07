"""Text helpers that the paper guard and its tests share.

The guard reads the abstract through ``block_scalar_span``, and the mutation
tests place their edits with the same function, so both work on the same text.
Wherever pandoc is installed, ``tests/test_paper_text.py`` checks that the
parser reads the words pandoc renders as the abstract, or fails closed.
"""

from __future__ import annotations

import re

FRONT_MATTER_ENDS = ("---", "...")
SIGNED_NUMBER = r"[−-]?\d[\d,]*(?:\.\d+)?"
LINE = re.compile(r"[^\n]*\n|[^\n]+\Z")


def _bare(line: str) -> str:
    """A line without its ending and without trailing spaces or tabs."""
    return line.removesuffix("\n").removesuffix("\r").rstrip(" \t")


def _key_matchers(key: str):
    """Two matchers for a line that YAML could read as setting ``key``. The
    first finds the key, plain or quoted, at the line's start before a colon,
    or in an explicit ``? key`` line. The second also finds it in flow style,
    after ``{`` or ``,``, as in ``{key: value}``."""
    name = re.escape(key)
    spelled = rf"""(?:{name}|"{name}"|'{name}')"""
    sets = rf"(?:\?[ \t]+{spelled}[ \t]*(?::|\r?$)|{spelled}[ \t]*:)"
    return re.compile(sets).match, re.compile(rf"(?:^|[{{,])[ \t]*{sets}").search


def block_scalar_span(text: str, key: str) -> tuple[int, int] | None:
    """Character span of the literal block under the front matter's one
    top-level ``key: |`` line, read as pandoc reads it, or None.

    Lines end at line feeds. The front matter opens with a ``---`` line and
    text on the next line, and closes at the next ``---`` or ``...`` line.
    The block takes its indentation from its first line with text and ends at
    the next line with less, such as another field or a trailing comment.
    Lines of whitespace alone stay inside it. Indented keys belong to other
    mappings and do not count.

    It returns None, so every tie that reads the block fails, when

    - the text lacks such front matter, or the front matter never closes;
    - the front matter names the key other than once, or names it on a line
      other than ``key: |``. A quoted ``"key"`` or an explicit ``? key`` also
      names it;
    - any line after the front matter names the key, at the line's start or
      in flow style such as ``{key: value}``, since pandoc lets a later
      metadata block, even inside a list item or block quote, replace the
      front matter's value;
    - a tab falls in the indentation of a line in the block, since Quarto
      rejects tab indentation that pandoc accepts, or a carriage return
      stands alone in the front matter, since pandoc drops it;
    - the block holds no text.
    """
    lines = LINE.findall(text)
    if len(lines) < 2 or _bare(lines[0]) != "---" or not _bare(lines[1]):
        return None
    header = []
    offset = len(lines[0])
    for end, line in enumerate(lines[1:], 1):
        if _bare(line) in FRONT_MATTER_ENDS:
            break
        header.append((offset, line))
        offset += len(line)
    else:
        return None
    if any("\r" in line.removesuffix("\n").removesuffix("\r") for line in lines[: end + 1]):
        return None
    key_at_start, key_anywhere = _key_matchers(key)
    starts = [index for index, (_, line) in enumerate(header) if key_at_start(line)]
    if len(starts) != 1 or _bare(header[starts[0]][1]) != f"{key}: |":
        return None
    if any(key_anywhere(line.replace("\r", "").lstrip(" \t>")) for line in lines[end + 1 :]):
        return None
    first = last = starts[0] + 1
    indent = None
    while last < len(header):
        line = header[last][1]
        if line.strip():
            leading = line[: len(line) - len(line.lstrip(" \t"))]
            if "\t" in leading:
                return None
            indent = len(leading) if indent is None else indent
            if len(leading) < max(indent, 1):
                break
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
