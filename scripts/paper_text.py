"""Text helpers that the paper guard and its tests share.

The guard reads the abstract through ``block_words`` and reports why it
cannot through ``block_problem``; the mutation tests place their edits with
``block_scalar_span``, so all three work on the same block. Wherever pandoc
or Quarto is installed, ``tests/test_paper_text.py`` checks that the parser
reads the words that tool renders as the abstract, or fails closed.

The parser reads a small part of YAML and Markdown and fails closed on the
rest rather than emulate either. The front matter must hold plain keys with
plain, quoted or block values; the abstract must hold plain prose; and the
body must hold nothing that pandoc or Quarto could read as metadata.
"""

from __future__ import annotations

import re

FRONT_MATTER_ENDS = ("---", "...")
# Characters a writer could type as a minus sign or a range dash: hyphens,
# figure, en and em dashes, the minus sign and their small and fullwidth forms.
DASHES = "\u2010-\u2015\u2212\ufe58\ufe63\uff0d-"
NUMBER = r"\d[\d,]*(?:\.\d+)?"
# What joins two numbers into a range or a pair: dashes, a slash, or a word
# such as "to", "and" or "through".
RANGE_JOIN = rf"\s*[{DASHES}]+\s*|\s*/\s*|\s+(?:to|and|or|through|thru|till|until|versus|vs\.?)\s+"
# A number read whole, with any run of dashes before it, spaced or not, as
# its sign, and with any number joined to it as above, as a range.
SIGNED_NUMBER = rf"(?:[{DASHES}]+\s*)?{NUMBER}(?:(?:{RANGE_JOIN}){NUMBER})?"
LINE = re.compile(r"[^\n]*\n|[^\n]+\Z")
# Line ends that Quarto and pandoc read differently. Quarto ends a line at a
# carriage return without a line feed, which pandoc drops, and the
# JavaScript ^ and $ in Quarto's metadata search also match at the Unicode
# line and paragraph separators.
STRAY_LINE_END = re.compile("\r(?!\n)|[\u2028\u2029\x85]").search
# Quarto deletes HTML comments and then backtick code fences from the file
# before it looks for YAML (readYamlFromMarkdown in Quarto 1.9.36), so a
# comment or fence can join or hide the lines it reads. The front matter
# fails closed on either. In the body, a deleted comment can join text
# within a line, so the body is also read with comments deleted, by Quarto's
# pattern. A deleted fence leaves an empty line in place of whole lines, so
# it can only remove what the body check finds.
QUARTO_COMMENT = re.compile(r"<!--[\W\w]*?-->")
QUARTO_STRIPS = re.compile(r"<!--|^[\t >]*```").search

# The front matter's grammar. A line holds indentation, any "- " markers of
# block sequence entries, and then a key named in letters, digits, "_" and
# "-" followed by a colon, a value alone after a marker, or both.
KEY_NAME = r"[A-Za-z_][A-Za-z0-9_-]*"
ENTRY = re.compile(
    rf"(?P<indent> *)(?P<marks>(?:- +)*)(?:(?P<key>{KEY_NAME}):(?=[ \t]|$))?[ \t]*(?P<rest>.*)"
).fullmatch
# A value is empty, a "|" or ">" block indicator without an indentation
# digit, a quoted scalar, which may run over several lines, a flow list of
# scalars on one line, or plain text that YAML reads as text. A comment may
# follow any of them. Keys are plain names, so a quoted scalar's escapes
# shape only text.
BLOCK_INDICATOR = re.compile(r"[|>][-+]?(?:[ \t]+#.*)?").fullmatch
AFTER_VALUE = re.compile(r"(?:[ \t]+#.*)?").fullmatch
DOUBLE = r'(?:[^"\\]|\\.)*'
SINGLE = r"(?:[^']|'')*"
QUOTED = {'"': re.compile(rf'"{DOUBLE}"').match, "'": re.compile(rf"'{SINGLE}'(?!')").match}
# A quoted value left open at its line's end; a double-quoted line may end
# in a backslash, which escapes the line break.
QUOTE_OPEN = {'"': re.compile(rf'"{DOUBLE}\\?').fullmatch, "'": re.compile(rf"'{SINGLE}").fullmatch}
QUOTE_CLOSES = {'"': re.compile(rf'{DOUBLE}"').match, "'": re.compile(rf"{SINGLE}'(?!')").match}
# A flow list on one line whose items hold no colon, bracket, brace,
# comment, anchor, alias, tag or other indicator, so YAML reads each item as
# text, as in ``keywords: [poverty, "SPM thresholds"]``.
FLOW_LIST = re.compile(
    r"""\[(?:[^\[\]{}:#&*!?|>%@`"'\\]|"(?:[^"\\:]|\\.)*"|'[^':]*')*\](?:[ \t]+#.*)?"""
).fullmatch
# Characters that may not start a plain value, since YAML reads each there
# as syntax: sequence, key and flow indicators, comments, anchors, aliases,
# tags, block indicators, quotes, directives and reserved characters. A
# line that continues a plain value is not a node's start, so YAML reads
# anchor, alias, tag, block, quote and reserved characters there as text;
# such a line may still not start with a sequence, key or flow indicator.
PLAIN_FIRST = frozenset("-?:,[]{}#&*!|>'\"%@`")
# Anchors ("&name") and tags ("!tag") that may lead a value, each followed by
# a space or the line's end, and an alias ("*name") that may stand as a
# whole value. They name or type the value and set no key; keys stay plain
# names, so a property before a key falls outside the grammar.
PROPERTIES = re.compile(r"(?:[&!][^\s,\[\]{}]*(?:[ \t]+|$))*").match
ALIAS = re.compile(r"\*[^\s,\[\]{}]+(?:[ \t]+#.*)?").fullmatch
CONTINUATION_FIRST = frozenset("-?:,[]{}#")
COMMENT = re.compile(r"[ \t]#").search

# A container prefix that pandoc reads before a body block, so a metadata
# block can open after it: indentation, block quote markers, and bullet,
# numbered, example or definition list markers.
CONTAINER = re.compile(r"[ \t>]+|(?:[-*+:~]|\(?(?:[0-9A-Za-z#]{1,9}|@[\w-]*)[.)])[ \t]+").match
# A grid table's border at a line's end. pandoc reads grid cells as blocks,
# so a cell can hold a metadata block.
GRID_BORDER = re.compile(r"\+[-=:]+\+(?:[-=:]*\+)*$").search

# Characters the abstract may hold besides letters and ASCII digits:
# whitespace, sentence punctuation, quotes and dashes. Markdown, HTML and TeX
# each need one of the others (* _ ` [ ] { } < > & \ $ ^ ~ # | @ = % +), so
# text made of these renders as typed, with no part hidden or replaced.
PROSE_MARKS = frozenset(
    " \t\n\r\xa0\u202f.,;:()'\"\u2018\u2019\u201c\u201d?!/"
    "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d-"
)
PROSE_LIST = "letters, digits, spaces, dashes and . , ; : ( ) ' \" ? ! /"


def _bare(line: str) -> str:
    """A line without its ending and without trailing spaces or tabs."""
    return line.removesuffix("\n").removesuffix("\r").rstrip(" \t")


def _key_anywhere(key: str):
    """A search for text that YAML could read as setting ``key``: the key,
    plain or quoted, before a colon, or in an explicit ``? key`` line, which
    may end in a comment, at the line's start or in flow style after ``{``
    or ``,``, as in ``{key: value}``."""
    name = re.escape(key)
    spelled = rf"""(?:{name}|"{name}"|'{name}')"""
    sets = rf"(?:\?[ \t]+{spelled}(?:[ \t]*:|[ \t]+#|[ \t]*\r?$)|{spelled}[ \t]*:)"
    return re.compile(rf"(?:^|[{{,])[ \t]*{sets}").search


def _plain(value: str, first=PLAIN_FIRST) -> bool:
    """Whether YAML reads ``value``, a line's text without its comment, as
    plain text, which sets no key: it may not start with a character in
    ``first`` or hold a colon before a space or the line's end."""
    return bool(value) and value[0] not in first and not re.search(r":(?:[ \t]|$)", value)


def _uncontained(line: str) -> str:
    """A body line without the container prefixes before its text."""
    while (prefix := CONTAINER(line)) is not None:
        line = line[prefix.end() :]
    return line


def block_scalar_span(text: str, key: str) -> tuple[int, int] | None:
    """Character span of the literal block under the front matter's one
    top-level ``key: |`` line, read as Quarto and pandoc read it, or None,
    so that every tie reading the block fails. ``block_problem`` says why.

    Lines end at line feeds. The front matter opens with a ``---`` line and
    text on the next line, and closes at the next ``---`` or ``...`` line.
    The block takes its indentation from the spaces that lead its first line
    with text and ends at the next line with fewer, such as another field or
    a trailing comment. Lines of spaces and tabs alone stay inside it.

    The span is None when

    - the file holds a carriage return without a line feed, or a Unicode
      line or paragraph separator, where Quarto and pandoc end lines
      differently;
    - the text lacks such front matter, or the front matter never closes;
    - a front-matter line falls outside the grammar the parser reads. It
      reads plain keys (letters, digits, "_" and "-"), each with an empty
      value, a ``|`` or ``>`` block without an indentation digit, a quoted
      value, which may run over lines, a one-line flow list of plain or
      quoted items without colons or other indicators, or plain text, which
      may continue on more deeply indented lines; ``- `` entries that hold
      such a key or value; and comments. A value may start with anchors and
      tags, or be an alias, which name or type it and set no key. Anchors
      and tags on keys, explicit ``?`` keys, quoted keys, flow mappings,
      other flow lists, directives, tabs in indentation and a quote still
      open at the front matter's end all fall outside it;
    - a front-matter line, even inside another block, holds an HTML comment
      or starts a backtick code fence, which Quarto deletes before it reads
      the YAML;
    - the front matter names the key other than once, or other than on a
      top-level line that reads exactly ``key: |``. Quarto renders a key
      nested under ``format: html:`` in place of the top-level one. Text
      inside another block or quoted value names nothing;
    - the key's block holds no text;
    - a body line, after list and block quote markers, names the key at its
      start or in flow style; ends in a grid table's border; or opens what
      pandoc could read as a metadata block: a ``---`` line followed by a
      line with text and later by a ``---`` or ``...`` line. Quarto deletes
      HTML comments before it looks for metadata blocks, so the body is
      checked as pandoc reads it and with comments deleted, as Quarto reads
      it.
    """
    return _scan(text, key)[0]


def block_problem(text: str, key: str) -> str | None:
    """Why ``block_words`` reads no words for ``key``, or None when it reads
    them."""
    span, reason = _scan(text, key)
    if span is None:
        return reason
    return _prose_problem(text[span[0] : span[1]], key)


def block_words(text: str, key: str) -> str | None:
    """The words of the front matter's ``key: |`` block, joined by single
    spaces, or None when ``block_scalar_span`` finds no block or the block
    holds anything but plain prose (``PROSE_MARKS``), which Quarto and pandoc
    could render as other text or none."""
    span = _scan(text, key)[0]
    if span is None:
        return None
    block = text[span[0] : span[1]]
    if _prose_problem(block, key) is not None:
        return None
    return " ".join(block.split())


def _prose_problem(block: str, key: str) -> str | None:
    """Why the block's text is not plain prose, or None."""
    for character in block:
        if not (character.isalpha() or character in "0123456789" or character in PROSE_MARKS):
            return f"the {key} may hold only {PROSE_LIST}, and holds {character!r}"
    if ":::" in block:
        return f"the {key} holds ':::', which opens a div that Quarto can hide"
    return None


def _scan(text: str, key: str) -> tuple[tuple[int, int] | None, str]:
    """The block's span and an empty reason, or None and why not."""
    stray = STRAY_LINE_END(text)
    if stray is not None:
        return None, (
            f"line {text.count(chr(10), 0, stray.start()) + 1} holds a carriage return without a line feed "
            "or a Unicode line separator, where Quarto and pandoc end lines differently"
        )
    lines = LINE.findall(text)
    if len(lines) < 2 or _bare(lines[0]) != "---" or not _bare(lines[1]):
        return None, "the file must open with front matter: a --- line, then a line with text"
    header = []
    offset = len(lines[0])
    for end, line in enumerate(lines[1:], 1):
        if _bare(line) in FRONT_MATTER_ENDS:
            break
        header.append((offset, line))
        offset += len(line)
    else:
        return None, "the front matter never closes with a --- or ... line"
    found = _front_matter_block(header, key)
    if isinstance(found, str):
        return None, found
    first, last = found
    reason = _body_problem("".join(lines[end + 1 :]), key, end + 2)
    if reason is not None:
        return None, reason
    return (header[first][0], header[last - 1][0] + len(header[last - 1][1])), ""


def _front_matter_block(header, key: str) -> tuple[int, int] | str:
    """Rows ``first`` to ``last`` (exclusive) of the key's block among the
    front matter's lines, or why the parser reads none. Line numbers in the
    reasons count the file's opening ``---`` as line 1."""
    block = None  # [indentation its text must exceed, its text's indentation, opener's row]
    quote = None  # (quote character, line number) of a quoted value still open
    plain = None  # indentation a plain value's next lines must exceed to continue it
    rows = []
    span = None
    for row, (_, line) in enumerate(header):
        number = row + 2
        unread = f"line {number}, in the front matter, is YAML the guard does not read"
        text = _bare(line)
        stripped = (
            f"line {number}, in the front matter, holds an HTML comment or a code fence, "
            "which Quarto deletes before it reads the YAML"
            if QUARTO_STRIPS(text)
            else None
        )
        spaces = len(text) - len(text.lstrip(" "))
        if block is not None:
            parent, indent, opener = block
            if not text:
                continue
            if indent is None and spaces > parent:
                indent = block[1] = spaces
            if indent is not None:
                if spaces >= indent:
                    # The key's own block may hold markup; block_words then
                    # fails closed on it as text that is not plain prose.
                    if stripped and opener not in rows:
                        return stripped
                    continue
            if opener in rows:
                span = (opener + 1, row) if indent is not None else ()
            block = None
        if stripped:
            return stripped
        if quote is not None:
            closes = QUOTE_CLOSES[quote[0]](text)
            if closes is None:
                continue
            if not AFTER_VALUE(text[closes.end() :]):
                return unread
            quote = None
            continue
        if not text:
            continue
        if text[spaces] == "\t":
            return f"line {number}, in the front matter, has a tab in its indentation"
        if text[spaces] == "#":
            plain = None
            continue
        entry = ENTRY(text)
        name, marks, rest = entry["key"], entry["marks"], entry["rest"]
        if name is None and not marks:
            comment = COMMENT(rest)
            value = rest if comment is None else rest[: comment.start()]
            if plain is None or spaces <= plain or not _plain(value, CONTINUATION_FIRST):
                return unread
            if comment is not None:
                plain = None
            continue
        if name is not None:
            parent = len(entry["indent"]) + len(marks)
        else:
            parent = len(entry["indent"]) + marks.rstrip(" ").rfind("-")
        if name == key:
            rows.append(row)
            if text != f"{key}: |":
                return f"line {number}, in the front matter, sets {key} other than on a top-level {key}: | line"
        plain = None
        rest = rest[PROPERTIES(rest).end() :]
        if not rest or rest.startswith("#"):
            plain = parent
        elif BLOCK_INDICATOR(rest):
            block = [parent, None, row]
        elif FLOW_LIST(rest) or ALIAS(rest):
            pass
        elif rest[0] in QUOTED:
            closed = QUOTED[rest[0]](rest)
            if closed is not None:
                if not AFTER_VALUE(rest[closed.end() :]):
                    return unread
            elif QUOTE_OPEN[rest[0]](rest):
                quote = (rest[0], number)
            else:
                return unread
        else:
            comment = COMMENT(rest)
            value = rest if comment is None else rest[: comment.start()]
            if not _plain(value):
                return unread
            plain = parent if comment is None else None
    if quote is not None:
        return f"a quote opened on line {quote[1]} is still open at the front matter's end"
    if block is not None and block[2] in rows:
        span = (block[2] + 1, len(header)) if block[1] is not None else ()
    if not rows:
        return f"the front matter has no top-level {key}: | line"
    if len(rows) > 1:
        return f"the front matter sets {key} on lines {rows[0] + 2} and {rows[1] + 2}"
    if not span:
        return f"the {key} block holds no text"
    return span


def _body_problem(body: str, key: str, first_number: int) -> str | None:
    """Why a line of the body could set the key, or None. The body is read
    as pandoc reads it, and as Quarto reads it after deleting HTML
    comments."""
    quarto = QUARTO_COMMENT.sub("", body.replace("\r\n", "\n"))
    views = ((body, "line {}, in the body,"), (quarto, "once Quarto deletes HTML comments, a body line"))
    for view, where in views:
        reason = _view_problem([_bare(line) for line in view.split("\n")], key, where, first_number)
        if reason is not None:
            return reason
    return None


def _view_problem(body: list[str], key: str, where: str, first_number: int) -> str | None:
    """Why a line of one view of the body could set the key, or None."""
    key_anywhere = _key_anywhere(key)
    uncontained = [_uncontained(line) for line in body]
    for row, line in enumerate(body):
        place = where.format(first_number + row)
        if GRID_BORDER(line):
            return f"{place} ends in a grid table's border, and pandoc reads grid cells as blocks that could set {key}"
        if key_anywhere(uncontained[row]):
            return f"{place} could set {key}"
    fences = [line in FRONT_MATTER_ENDS for line in uncontained]
    for row, line in enumerate(uncontained):
        if line == "---" and row + 1 < len(body) and uncontained[row + 1] and any(fences[row + 2 :]):
            return f"{where.format(first_number + row)} could open a metadata block, which sets the paper's metadata"
    return None


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
    run of dashes before it, spaced or not, as its sign and with any number
    joined to it by dashes, a slash or a word such as "to", "and" or
    "through", as a range. So the text's "12.29", "−2.29", "– 2.29",
    "2.20–2.29", "2.20 to 2.29" or "2.20 and 2.29" never reads as "2.29". The
    slot starts only at the start of a whitespace-separated token or after
    "(", so "x2.29" reads as nothing. The template's words match only whole
    words, so "index" does not match "indexes". A template without exactly
    one slot matches nothing.
    """
    parts = template.split("{}")
    if len(parts) != 2:
        return []
    before, after = (_whitespace_tolerant(part) for part in parts)
    if parts[0][:1].isalnum():
        before = rf"(?<![\w-]){before}"
    if parts[1][-1:].isalnum():
        after = rf"{after}(?![\w-])"
    slot = rf"(?<![^\s(])({value})(?![\d]|[.,{DASHES}]\d)"
    return re.findall(before + slot + after, text)
