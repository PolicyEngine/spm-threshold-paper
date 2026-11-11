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
# Characters a writer could type as a minus sign or a range dash: hyphens,
# figure, en and em dashes, the minus sign and their small and fullwidth forms.
DASHES = "\u2010-\u2015\u2212\ufe58\ufe63\uff0d-"
NUMBER = r"\d[\d,]*(?:\.\d+)?"
# A number read whole with any dash before it as its sign, spaced or not,
# and with any range it opens, joined by a dash or by "to".
SIGNED_NUMBER = rf"(?:[{DASHES}]\s*)?{NUMBER}(?:\s*[{DASHES}]\s*{NUMBER}|\s+to\s+{NUMBER})?"
LINE = re.compile(r"[^\n]*\n|[^\n]+\Z")
# Markup that Quarto or pandoc renders as other text or none: an HTML
# comment, a code fence, a shortcode or raw content.
HIDDEN_MARKUP = ("<!--", "```", "{{<", "{=")
# Quarto deletes HTML comments and backtick code fences from the whole file,
# front matter included, before it reads the YAML, so a comment glued to a
# key, or one or a fence that spans other lines, changes the keys it reads.
QUARTO_STRIPS = re.compile(r"<!--|^[\t >]*```").search
# A line that opens a block scalar after a key or a "- " marker, as
# `text: |` or `- >-` do, so the deeper lines that follow hold its text
# rather than keys. A "|" or ">" inside a trailing comment opens nothing.
BLOCK_SCALAR_OPENER = re.compile(
    r"(?:(?:(?![ \t]#).)*:|(?:(?:(?![ \t]#).)*[ \t])?-)[ \t]+[|>][-+1-9]*[ \t]*(?:#.*)?"
).fullmatch
# Indentation and the "- " markers of block sequence entries, before a key.
SEQUENCE_PREFIX = re.compile(r"[ \t]*(?:-[ \t]+)*").match
# Where a quoted scalar can open: at the start of a line's content, after a
# key's ": ", or after a flow "[", "{" or ",", each perhaps followed by an
# explicit key's "? ". An apostrophe inside a word, or a quote after a "?"
# inside a plain value, opens none. The rest of a double- or single-quoted
# scalar, up to its closing quote, may run over several lines.
QUOTE_START = re.compile(r"""(?:^|:[ \t]+|[\[{,][ \t]*)(?:\?[ \t]+)?(["'])""").search
QUOTE_REST = {
    '"': re.compile(r'(?:[^"\\]|\\.)*"').match,
    "'": re.compile(r"(?:[^']|'')*'(?!')").match,
}
COMMENT_START = re.compile(r"(?:^|[ \t])#").search
TRAILING_COMMENT = re.compile(r"(?:^|[ \t])#.*")
# Keys that could set a key no plain spelling names, on a line without its
# quoted scalars and comment: a tag, anchor or alias on a key, or an explicit
# "? " key, whose name may follow on later lines, where a key can start (at
# the line's start, after any "- " markers, or after a flow "[", "{" or ","),
# or a flow collection used as a key, as in `[abstract]: …` or, in a flow
# mapping, `{[abstract]:…}`.
UNRESOLVED_KEY = re.compile(
    r"(?:^|[\[{,][ \t]*)(?:[!&*][^\s,\[\]{}]*(?:[ \t]+[^\s:#][^:#]*?)?[ \t]*:(?:[ \t]|$)|\?(?:[ \t]|$))"
    r"|[\]}][ \t]*:"
).search
# A body line that pandoc could read as a metadata block's fence: "---" or
# "..." after block quote markers, table cell bars, and bullet, numbered,
# example or definition list markers.
METADATA_FENCE = re.compile(
    r"[ \t>|]*(?:(?:[-*+:~]|\(?(?:[0-9A-Za-z#]{1,9}|@[\w-]*)[.)])[ \t]+)*(?:---|\.\.\.)[ \t|]*"
).fullmatch
# What may lead or trail a body line around its text: indentation, block
# quote markers and table cell bars.
BODY_CONTAINER = " \t>|"


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
    - another front-matter line holds a key the parser cannot resolve: one
      with a YAML tag, anchor or alias, an explicit ``?`` key, a flow
      collection as a key, or a double-quoted key with an escape. Such
      syntax inside a quoted scalar, or on a value, sets no key;
    - a quoted scalar is still open at the key's line, where YAML reads that
      line as the scalar's text, or at the front matter's end. A line that a
      quoted scalar runs through opens no block scalar, so the deeper lines
      after it count as keys;
    - another front-matter line, even inside another block scalar, holds an
      HTML comment or starts a backtick code fence, which Quarto deletes
      before it reads the YAML;
    - any line after the front matter names the key, at the line's start or
      in flow style, or the body holds a metadata block at all: a ``---``
      line, even inside a list item, block quote or table cell, followed by
      a line with text and later by a ``---`` or ``...`` line. pandoc and
      Quarto let such a block replace the front matter's value, and they
      resolve aliases, anchors, tags and escapes in its keys, which this
      parser does not;
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
    if any(key_anywhere(line.lstrip(BODY_CONTAINER)) for line in body):
        return None
    for row, line in enumerate(body):
        if (
            METADATA_FENCE(line)
            and line.strip(BODY_CONTAINER).endswith("---")
            and row + 1 < len(body)
            and body[row + 1].strip(BODY_CONTAINER)
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
    depth, holds a key the parser cannot resolve, which could set it, or
    holds markup that Quarto deletes before it reads the YAML, or whether a
    quoted scalar runs on into ``skip`` or past the front matter's end, where
    YAML would read the key line as its text. Lines inside another block
    scalar hold text, not keys, and YAML comment lines hold neither. A line
    that a quoted scalar runs through opens no block scalar, so the lines
    after it count as keys."""
    opener = quote = None
    for row, (_, line) in enumerate(header):
        if row in skip:
            if quote is not None:
                return True
            opener = None
            continue
        if QUARTO_STRIPS(line):
            return True
        bare = _bare(line)
        spaces = len(bare) - len(bare.lstrip(" "))
        if opener is not None:
            if not bare.strip(" \t") or spaces > opener:
                continue
            opener = None
        started = quote
        content = bare.lstrip(" \t") if started else bare[SEQUENCE_PREFIX(bare).end() :]
        if started is None and content.startswith("#"):
            continue
        spans, quote = _quoted_spans(content, started)
        if key_anywhere(content) or _unresolved_key(content, spans):
            return True
        if started is None and quote is None and BLOCK_SCALAR_OPENER(bare):
            opener = spaces
    return quote is not None


def _quoted_spans(content: str, quote: str | None = None):
    """The spans of a front-matter line's quoted scalars, given the quote
    character of one that earlier lines left open, and the quote character
    of one still open at the line's end, or None."""
    spans, at = [], 0
    while True:
        begin = at
        if quote is None:
            start = QUOTE_START(content, at)
            comment = COMMENT_START(content, at)
            if start is None or comment is not None and comment.start() < start.start(1):
                return spans, None
            quote, begin, at = start.group(1), start.start(1), start.end()
        rest = QUOTE_REST[quote](content, at)
        if rest is None:
            spans.append((begin, len(content)))
            return spans, quote
        spans.append((begin, rest.end()))
        quote, at = None, rest.end()


def _unresolved_key(content: str, spans) -> bool:
    """Whether a front-matter line, whose quoted scalars sit at ``spans``,
    holds a key with a tag, anchor or alias, an explicit key, a flow
    collection as a key, or a double-quoted key with an escape."""
    for begin, end in spans:
        scalar = content[begin:end]
        if scalar.startswith('"') and "\\" in scalar and re.match(r"[ \t]*:", content[end:]):
            return True
    plain = content
    for begin, end in reversed(spans):
        plain = plain[:begin] + '""' + plain[end:]
    return bool(UNRESOLVED_KEY(TRAILING_COMMENT.sub("", plain)))


def block_words(text: str, key: str) -> str | None:
    """The words of the front matter's ``key: |`` block, joined by single
    spaces, or None when ``block_scalar_span`` finds no block or the block
    holds an HTML comment, a code fence, a shortcode or raw content, which
    Quarto and pandoc render as other text or none."""
    span = block_scalar_span(text, key)
    if span is None:
        return None
    block = text[span[0] : span[1]]
    if any(mark in block for mark in HIDDEN_MARKUP):
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

    By default the slot takes a number at numeric-token boundaries, with any
    dash before it, spaced or not, as its sign and with any range it opens,
    joined by a dash or by "to", so the text's "12.29", "−2.29", "– 2.29",
    "2.20–2.29" or "2.20 to 2.29" never reads as "2.29". The template's words
    match only whole words, so "index" does not match "indexes". A template
    without exactly one slot matches nothing.
    """
    parts = template.split("{}")
    if len(parts) != 2:
        return []
    before, after = (_whitespace_tolerant(part) for part in parts)
    if parts[0][:1].isalnum():
        before = rf"(?<![\w-]){before}"
    if parts[1][-1:].isalnum():
        after = rf"{after}(?![\w-])"
    slot = rf"(?<![\d.,{DASHES}])({value})(?![\d]|[.,{DASHES}]\d)"
    return re.findall(before + slot + after, text)
