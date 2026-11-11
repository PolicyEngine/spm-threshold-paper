"""Text helpers that the paper guard and its tests share.

The guard reads the abstract through ``block_words``, and the mutation tests
place their edits with ``block_scalar_span``, so both work on the same block.
Wherever pandoc or Quarto is installed, ``tests/test_paper_text.py`` checks
that the parser reads the words that tool renders as the abstract, or fails
closed.
"""

from __future__ import annotations

import re

FRONT_MATTER_ENDS = ("---", "...")
SIGNED_NUMBER = r"[−-]?\d[\d,]*(?:\.\d+)?"
# Characters a writer could type as a minus sign or a range dash: hyphens,
# figure, en and em dashes, the minus sign and their small and fullwidth forms.
DASHES = "\u2010-\u2015\u2212\ufe58\ufe63\uff0d-"
LINE = re.compile(r"[^\n]*\n|[^\n]+\Z")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
# A line whose value opens a block scalar, as `text: |` or `- >-` do, so the
# deeper lines that follow hold its text rather than keys.
BLOCK_SCALAR_OPENER = re.compile(r"(?:.*:|(?:.*[ \t])?-)[ \t]+[|>][-+1-9]*[ \t]*(?:#.*)?").fullmatch
# Indentation and the "- " markers of block sequence entries, before a key.
SEQUENCE_PREFIX = re.compile(r"[ \t]*(?:-[ \t]+)*").match
# YAML syntax through which a line could set a key that no plain spelling
# names: a tag, anchor or alias at a token's start, an explicit "? " key,
# whose name may follow on later lines, or a double-quoted key with an escape.
UNRESOLVED_SYNTAX = re.compile(
    r"""(?:^|[\s{\[,:?])[!&*][^\s,\[\]{}]|(?:^|[{,\[][ \t]*)(?:\?(?:[ \t]|$)|"[^"]*\\)"""
).search
# A body line that pandoc could read as a metadata block's fence: "---" or
# "..." after any block quote, list item or definition markers.
METADATA_FENCE = re.compile(
    r"[ \t>]*(?:(?:[-*+:~]|\(?[0-9A-Za-z#]{1,9}[.)])[ \t]+)*(?:---|\.\.\.)[ \t]*"
).fullmatch


def _bare(line: str) -> str:
    """A line without its ending and without trailing spaces or tabs."""
    return line.removesuffix("\n").removesuffix("\r").rstrip(" \t")


def _key_matchers(key: str):
    """Two matchers for a line that YAML could read as setting ``key``. The
    first finds the key, plain or quoted, at the line's start before a colon,
    or in an explicit ``? key`` line, which may end in a comment. The second
    also finds it in flow style, after ``{`` or ``,``, as in ``{key: value}``."""
    name = re.escape(key)
    spelled = rf"""(?:{name}|"{name}"|'{name}')"""
    sets = rf"(?:\?[ \t]+{spelled}(?:[ \t]*:|[ \t]+#|[ \t]*\r?$)|{spelled}[ \t]*:)"
    return re.compile(sets).match, re.compile(rf"(?:^|[{{,])[ \t]*{sets}").search


def block_scalar_span(text: str, key: str) -> tuple[int, int] | None:
    """Character span of the literal block under the front matter's one
    top-level ``key: |`` line, read as Quarto and pandoc read it, or None.

    Lines end at line feeds. The front matter opens with a ``---`` line and
    text on the next line, and closes at the next ``---`` or ``...`` line.
    The block takes its indentation from the spaces that lead its first line
    with text and ends at the next line with fewer, such as another field or
    a trailing comment. Lines of spaces and tabs alone stay inside it.

    It returns None, so every tie that reads the block fails, when

    - the text lacks such front matter, or the front matter never closes;
    - the front matter names the key other than once, at any depth, or names
      it on a line other than ``key: |``. A quoted ``"key"``, an explicit
      ``? key`` or a flow mapping such as ``{key: value}`` also names it.
      Quarto renders a key nested under ``format: html:`` or ``format: pdf:``
      in place of the top-level one. Text inside another block scalar, such
      as ``include-in-header: text: |``, names nothing;
    - another front-matter line holds a YAML tag, anchor or alias, an
      explicit ``?`` key or a double-quoted key with an escape, since the
      parser cannot tell which key such a line sets;
    - any line after the front matter names the key, at the line's start or
      in flow style, or the body holds a metadata block at all: a ``---``
      line, even inside a list item or block quote, followed by a line with
      text and later by a ``---`` or ``...`` line. pandoc and Quarto let such
      a block replace the front matter's value, and they resolve aliases,
      anchors, tags and escapes in its keys, which this parser does not;
    - a tab falls within the block's indentation on one of its lines, where
      Quarto and pandoc read the line differently, or a carriage return
      stands alone in the front matter, since pandoc drops it while Quarto
      ends the line there;
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
    body = [_bare(line.replace("\r", "")) for line in lines[end + 1 :]]
    if any(key_anywhere(line.lstrip(" \t>")) for line in body):
        return None
    for row, line in enumerate(body):
        if (
            METADATA_FENCE(line)
            and line.lstrip(" \t>").endswith("---")
            and row + 1 < len(body)
            and body[row + 1].lstrip(" \t>").strip()
            and any(METADATA_FENCE(later) for later in body[row + 2 :])
        ):
            return None
    first = last = starts[0] + 1
    indent = None
    while last < len(header):
        line = header[last][1]
        if line.strip(" \t\r\n"):
            spaces = len(line) - len(line.lstrip(" "))
            indent = spaces if indent is None else indent
            if "\t" in line[: max(indent, 1)]:
                return None
            if spaces < max(indent, 1):
                break
        last += 1
    block = header[first:last]
    if not "".join(line for _, line in block).strip():
        return None
    if _may_set_key_elsewhere(header, range(starts[0], last), key_anywhere):
        return None
    return block[0][0], block[-1][0] + len(block[-1][1])


def _may_set_key_elsewhere(header, skip, key_anywhere) -> bool:
    """Whether a front-matter line outside ``skip`` names the key at any
    depth, or holds a tag, anchor, alias, explicit key or escaped quoted key
    that could set it. Lines inside another block scalar hold text, not keys, and YAML
    comment lines hold neither."""
    opener = None
    for row, (_, line) in enumerate(header):
        if row in skip:
            opener = None
            continue
        bare = _bare(line)
        spaces = len(bare) - len(bare.lstrip(" "))
        if opener is not None:
            if not bare.strip(" \t") or spaces > opener:
                continue
            opener = None
        content = bare[SEQUENCE_PREFIX(bare).end() :]
        if content.startswith("#"):
            continue
        if key_anywhere(content) or UNRESOLVED_SYNTAX(content):
            return True
        if BLOCK_SCALAR_OPENER(bare):
            opener = spaces
    return False


def block_words(text: str, key: str) -> str | None:
    """The words of the front matter's ``key: |`` block, joined by single
    spaces, without the HTML comments that Quarto and pandoc leave out of the
    rendered text, or None when ``block_scalar_span`` finds no block or a
    comment in it never closes."""
    span = block_scalar_span(text, key)
    if span is None:
        return None
    block = HTML_COMMENT.sub("", text[span[0] : span[1]])
    if "<!--" in block:
        return None
    return " ".join(block.split())


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
    the text's "12.29" or "−2.29" never reads as "2.29". A dash of any kind
    right before the slot blocks it too, so "–2.29" and the range "2.20–2.29"
    read as no value rather than as "2.29". A template without exactly one
    slot matches nothing.
    """
    parts = template.split("{}")
    if len(parts) != 2:
        return []
    before, after = (_whitespace_tolerant(part) for part in parts)
    slot = rf"(?<![\d.,{DASHES}])({value})(?![\d]|[.,]\d)"
    return re.findall(before + slot + after, text)
