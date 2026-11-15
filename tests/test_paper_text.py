"""Tests for scripts/paper_text.py, the helpers through which the paper guard
reads the front matter's abstract and the rates the abstract states.

The unit cases pin each rule of the block parser and the slot reader. The
seeded property tests build random front matter and rate statements, then check
that the abstract's words round-trip, that text outside the block never changes
what the guard reads, that a second key or a key after the front matter makes
the parser fail closed, and that each value reads as its whole numeric token.
Wherever pandoc or Quarto is installed, differential tests check that the
parser reads the words that tool renders as the abstract, or fails closed.
Quarto renders the paper and reads the front matter itself before pandoc does,
so the two can disagree. CI installs neither, so it skips those tests.
"""

import concurrent.futures
import html.parser
import importlib.util
import random
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_paper_text():
    """The helpers the guard imports, loaded from this checkout."""
    spec = importlib.util.spec_from_file_location(
        "paper_text_under_test", REPO / "scripts/paper_text.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PAPER_TEXT = load_paper_text()
block_scalar_span = PAPER_TEXT.block_scalar_span
block_words = PAPER_TEXT.block_words
block_problem = PAPER_TEXT.block_problem
stated_values = PAPER_TEXT.stated_values

MINUS = "\u2212"
CPI_U = "{} percent with the Consumer Price Index"
ABSTRACT_LINES = "  First line of the abstract,\n  then its second line.\n"
FOUR_SPACE_LINES = "    First line of the abstract,\n    then its second line.\n"
CLOSE = "---\n# Introduction"
PAPER = (
    "---\n"
    'title: "Thresholds"\n'
    "format:\n"
    "  pdf:\n"
    "    include-in-header:\n"
    "      text: |\n"
    "        \\usepackage{needspace}\n"
    "abstract: |\n"
    f"{ABSTRACT_LINES}"
    "---\n"
    "# Introduction\n"
    "\n"
    "Body text.\n"
)


def block_lines(text, key="abstract"):
    """The raw lines of the block, or None when the parser finds none."""
    span = block_scalar_span(text, key)
    return None if span is None else text[span[0] : span[1]]


def block_text(text, key="abstract"):
    """The block's words joined by single spaces, as the guard reads them."""
    lines = block_lines(text, key)
    return None if lines is None else " ".join(lines.split())


def with_lines(lines):
    """PAPER with `lines` in place of the abstract's lines."""
    return PAPER.replace(ABSTRACT_LINES, lines)


def with_body(insert):
    """PAPER with `insert` after its body text."""
    return PAPER.replace("Body text.\n", f"Body text.\n\n{insert}\nMore text.\n")


NESTED_FLOW_KEY = PAPER.replace(
    'title: "Thresholds"\n', 'title: "Thresholds"\nlinks: {abstract: "Nested 9.99."}\n'
)
FORMAT_LEVEL_KEY = PAPER.replace(
    "format:\n", "format:\n  html:\n    abstract: |\n      Format copy 9.99.\n"
)


class BlockScalarSpanTests(unittest.TestCase):
    def test_span_covers_exactly_the_indented_lines(self):
        self.assertEqual(block_lines(PAPER), ABSTRACT_LINES)

    def test_trailing_spaces_after_the_indicator_are_allowed(self):
        text = PAPER.replace("abstract: |\n", "abstract: |  \n")
        self.assertEqual(block_lines(text), ABSTRACT_LINES)

    def test_restyled_key_lines_fail_closed(self):
        for line in (
            "abstract: >",
            "abstract: >-",
            "abstract: |-",
            "abstract: |+",
            "abstract: |2",
            "abstract: | # a comment",
            "abstract:",
            "abstract:|",
            "abstract : |",
            "abstract:  |",
            "abstract:\t|",
            '"abstract": |',
            "'abstract': |",
        ):
            with self.subTest(line=line):
                text = PAPER.replace("abstract: |\n", f"{line}\n")
                self.assertIsNone(block_scalar_span(text, "abstract"))

    def test_a_repeated_top_level_key_fails_closed(self):
        for repeat in (
            f"abstract: |\n{ABSTRACT_LINES}",
            "abstract: A second abstract\n",
            "abstract:\n  - a list\n",
            '"abstract": |\n  A quoted copy.\n',
            "'abstract': A quoted copy.\n",
            "? abstract\n: |\n  An explicit copy.\n",
            "? abstract # a comment\n: |\n  An explicit copy.\n",
            '"\\x61bstract": An escaped copy.\n',
        ):
            before = PAPER.replace('title: "Thresholds"\n', f'title: "Thresholds"\n{repeat}')
            after = PAPER.replace(CLOSE, f"{repeat}{CLOSE}")
            for where, text in (("before", before), ("after", after)):
                with self.subTest(repeat=repeat, where=where):
                    self.assertIsNone(block_scalar_span(text, "abstract"))

    def test_keys_that_share_the_prefix_do_not_count(self):
        extra = (
            'abstract-title: "Summary"\nabstracts: |\n  Another block.\n'
            "abstract-note: Another field.\nabstract_2: A third.\n"
        )
        text = PAPER.replace('title: "Thresholds"\n', f'title: "Thresholds"\n{extra}')
        self.assertEqual(block_lines(text), ABSTRACT_LINES)

    def test_a_nested_key_fails_closed(self):
        """Quarto renders an abstract set under ``format: html:`` or
        ``format: pdf:`` in place of the top-level one, so a key at any depth
        of the front matter fails closed."""
        for name, text in {
            "format html": FORMAT_LEVEL_KEY,
            "format pdf": PAPER.replace(
                "    include-in-header:\n", "    abstract: Format copy 9.99.\n    include-in-header:\n"
            ),
            "beside a nested block": PAPER.replace(
                "      text: |\n", "      abstract: |\n        Nested copy.\n      text: |\n"
            ),
            "flow mapping": NESTED_FLOW_KEY,
            "nested flow mapping": PAPER.replace(
                "format:\n", "links: {html: {abstract: Flow copy 9.99.}}\nformat:\n"
            ),
            "sequence entry": PAPER.replace(
                'title: "Thresholds"\n', 'title: "Thresholds"\nnotes:\n  - abstract: Copy 9.99.\n'
            ),
            "explicit nested key": PAPER.replace(
                "  pdf:\n", "  html:\n    ? abstract\n    : Copy 9.99.\n  pdf:\n"
            ),
            "key beside an empty block in a sequence entry": PAPER.replace(
                'title: "Thresholds"\n', 'title: "Thresholds"\nnotes:\n  - text: |\n    abstract: Copy 9.99.\n'
            ),
        }.items():
            with self.subTest(case=name):
                self.assertIsNone(block_scalar_span(text, "abstract"))
        self.assertIsNone(block_scalar_span(PAPER, "text"))

    def test_yaml_syntax_the_parser_cannot_resolve_fails_closed(self):
        """The parser resolves no YAML tags, anchors, aliases, explicit keys
        or escapes, so a front-matter key that holds one could set the key
        unseen, as under ``format: html:``, and fails closed."""
        for name, insert in {
            "tagged nested key": "  html:\n    !!str abstract: Copy 9.99.\n",
            "anchored nested key": "  html:\n    &k abstract: Copy 9.99.\n",
            "aliased nested key": "  html:\n    *k : Copy 9.99.\n",
            "aliased key without a space": "  html:\n    *k: Copy 9.99.\n",
            "tagged quoted key": '  html:\n    !!str "abstract": Copy 9.99.\n',
            "tagged key in a flow mapping": "  html: {toc: true, !!str abstract: Copy 9.99.}\n",
            "anchored key in a sequence entry": "  html:\n    css:\n      - &k abstract: Copy 9.99.\n",
            "escaped nested key": '  html:\n    "\\x61bstract": Copy 9.99.\n',
            "escaped key in a nested flow mapping": '  html: {"\\x61bstract": Copy 9.99.}\n',
            "explicit key named in a block": "  html:\n    ? |-\n      abstract\n    : Copy 9.99.\n",
            "explicit key in a sequence entry": "  html:\n    css:\n      - ? x\n",
            "explicit key in a flow mapping": "  html: {? toc: true}\n",
            "flow sequence as a key": "  html:\n    [abstract]: Copy 9.99.\n",
            "flow sequence as a key in a flow mapping": "  html: {[abstract]: Copy 9.99.}\n",
            "aliased key after an apostrophe in a flow mapping": "  html: {note: it's, *k : Copy 9.99., c: d'}\n",
            "aliased key after a question mark in a flow mapping": '  html: {note: Why? "x, *k : Copy 9.99., c: y"}\n',
            "escaped key with an adjacent value": '  html: {"\\x61bstract":Copy 9.99.}\n',
            "flow sequence key with an adjacent value": "  html: {[abstract]:Copy 9.99.}\n",
            "comment glued to a closing quote": '  html:\n    pagetitle: "x"#c\n',
        }.items():
            with self.subTest(case=name):
                text = PAPER.replace("format:\n", f"format:\n{insert}")
                self.assertIsNone(block_scalar_span(text, "abstract"))

    def test_a_comment_opens_no_block_scalar(self):
        """A "|" or ">" inside a trailing comment opens no block scalar, so the
        keys on the deeper lines after it still count."""
        for opener in ("format:  # html: |\n", "format:  # see: >\n", "format: # - |\n"):
            with self.subTest(opener=opener):
                text = PAPER.replace(
                    "format:\n", f"{opener}  html:\n    toc: true\n    abstract: |\n      Format copy 9.99.\n"
                )
                self.assertIsNone(block_scalar_span(text, "abstract"))

    def test_a_quote_left_open_fails_closed(self):
        """A quoted scalar runs on to its closing quote, and YAML reads the
        lines it spans as its text. Quarto 1.9.36 then renders a format-level
        abstract that the parser would read as block text, or one under a
        block scalar opener that the quote hides, so a quote still open at
        the key line or at the front matter's end fails closed, and a line
        that a quote runs through opens no block scalar."""
        for name, text in {
            "over the key line": PAPER.replace(
                "abstract: |\n", '  html:\n    pagetitle: "x\nabstract: |\n'
            ).replace(ABSTRACT_LINES, ABSTRACT_LINES.rstrip("\n") + '"\n    abstract: "Format copy 9.99."\n'),
            "single-quoted, over the key line": PAPER.replace(
                "abstract: |\n", "  html:\n    pagetitle: 'x\nabstract: |\n"
            ).replace(ABSTRACT_LINES, ABSTRACT_LINES.rstrip("\n") + "'\n    abstract: 'Format copy 9.99.'\n"),
            "over another block's opener": PAPER.replace(
                "format:\n",
                'format:\n  html:\n    pagetitle: "x\n  include-in-header: |\n    y"\n'
                '    abstract: "Format copy 9.99."\n',
            ),
            "to the front matter's end": PAPER.replace(ABSTRACT_LINES, ABSTRACT_LINES + 'note: "open\n'),
            "over the key line, closing after the block": PAPER.replace(
                "abstract: |\n", '  html:\n    pagetitle: "x\nabstract: |\n'
            ).replace(ABSTRACT_LINES, ABSTRACT_LINES + 'note: y"\n'),
            "over another block's opener, closing later": PAPER.replace(
                "format:\n",
                'format:\n  html:\n    pagetitle: "x\n  include-in-header: |\n    y"\n'
                '    abstract: "Format copy 9.99."\n  epub:\n    title: "z"\n',
            ),
            "after an escaped quote, over the key line": PAPER.replace(
                "abstract: |\n", '  html:\n    pagetitle: "x \\"\nabstract: |\n'
            ).replace(ABSTRACT_LINES, ABSTRACT_LINES.rstrip("\n") + '"\n    abstract: "Format copy 9.99."\n'),
        }.items():
            with self.subTest(case=name):
                self.assertIsNone(block_scalar_span(text, "abstract"))

    def test_a_value_on_the_next_line_reads_only_as_plain_text(self):
        """A key with nothing after it on its line takes its value from the
        next deeper line, where YAML reads a quote, a block indicator, a tag,
        an anchor or an alias as syntax. A quote there runs on over the
        abstract's key line, and YAML then reads a later key that the
        parser's own quote hides, so anything but plain text there fails
        closed, a closed quote included. Plain text and nested keys there
        still read."""
        hidden = 'other: "\nabstract: Hidden 9.99.\nend: x "\n'
        for name, (before, after) in {
            "double quote": ('note:\n  "x\n', hidden),
            "single quote": ("note:\n  'x\n", hidden.replace('"', "'")),
            "quote after a comment on the key line": ('note: # see\n  "x\n', hidden),
            "tagged quote": ('note:\n  !!str "x\n', hidden),
            "quote under a key in a sequence entry": ('author:\n  - name:\n      "x\n', hidden),
            "closed quote": ('note:\n  "x"\n', ""),
            "alias": ("note:\n  *n\n", ""),
            "block indicator": ("", 'note:\n  |\n  sub: "x\nabstract: Hidden 9.99.\nend: y "\n'),
            "anchored block indicator": ("", 'note: &n\n  |\n  sub: "x\nabstract: Hidden 9.99.\nend: y "\n'),
        }.items():
            with self.subTest(case=name):
                text = PAPER.replace("abstract: |\n", f"{before}abstract: |\n").replace(
                    ABSTRACT_LINES, ABSTRACT_LINES + after
                )
                self.assertIsNone(block_scalar_span(text, "abstract"))
        for lines in (
            "note:\n  plain words\n",
            "note:\n  plain words\n  over two lines\n",
            "note: # see\n  plain words\n",
            "author:\n  - name: Max\n    affiliation: PolicyEngine\n",
        ):
            with self.subTest(lines=lines):
                text = PAPER.replace("abstract: |\n", f"{lines}abstract: |\n")
                self.assertEqual(block_lines(text), ABSTRACT_LINES)

    def test_a_deeper_line_after_plain_text_continues_it(self):
        """YAML reads a deeper line after plain text as more of that text,
        even when it opens with "- " or holds a quote, so it opens no
        sequence entry and no quote. The parser reads such a line only as
        plain text: one that opens with an indicator such as "-" fails
        closed, and one that holds a quote reads."""
        for name, lines in {
            "dash and quote after a plain value": 'note: foo\n  - "q\nabstract: Hidden 9.99.\nend: y "\n',
            "dash and quote after a sequence entry": 'keywords:\n  - poverty\n    - "q\nabstract: Hidden 9.99.\nend: y "\n',
            "key after a plain value": "note: foo\n  sub: bar\n",
            "line after a commented plain value": "note: foo # see\n  bar\n",
        }.items():
            with self.subTest(case=name):
                text = PAPER.replace(ABSTRACT_LINES, ABSTRACT_LINES + lines)
                self.assertIsNone(block_scalar_span(text, "abstract"))
        for lines in (
            'note: a\n  "b" c\n',
            "note: a\n  b's c\n",
            "keywords:\n  - poverty\n    lines\n",
            'note:\n  plain words\n  "more" words\n',
            'note:\n  sub: a\n    "b" c\n',
        ):
            with self.subTest(lines=lines):
                text = PAPER.replace(ABSTRACT_LINES, ABSTRACT_LINES + lines)
                self.assertEqual(block_lines(text), ABSTRACT_LINES)

    def test_markup_quarto_deletes_from_the_front_matter_fails_closed(self):
        """Quarto 1.9.36 deletes HTML comments and backtick code fences from
        the whole file before it reads the YAML, so a comment glued to a key
        sets that key, and a comment or fence that spans lines hides the
        lines between. Any such markup outside the block, even inside
        another block scalar, fails closed."""
        for name, text in {
            "comment glued to a key after the block": PAPER.replace(
                ABSTRACT_LINES, ABSTRACT_LINES + '<!-- -->abstract: "Hidden copy 9.99."\n'
            ),
            "comment glued to a format-level key": PAPER.replace(
                "format:\n", 'format:\n  html:\n    <!-- -->abstract: "Format copy 9.99."\n'
            ),
            "comment in another block scalar": PAPER.replace(
                "        \\usepackage{needspace}\n", "        \\usepackage{needspace} <!-- x -->\n"
            ),
            "fence in another block scalar": PAPER.replace(
                "        \\usepackage{needspace}\n", "        ```\n        \\usepackage{needspace}\n        ```\n"
            ),
            "fence line before the key": PAPER.replace("abstract: |\n", "```\nabstract: |\n"),
        }.items():
            with self.subTest(case=name):
                self.assertIsNone(block_scalar_span(text, "abstract"))

    def test_a_quoted_value_wrapped_over_lines_still_reads(self):
        """A quoted value that closes on a later line leaves the abstract
        readable, and a block scalar after it still holds text."""
        for value in (
            '"Thresholds for\n  the SPM"',
            "'The CE''s\n  thresholds'",
            "'The\n  CE''s thresholds'",
            "'The\n  CE''s\n  thresholds'",
            '"A \\"quoted\\"\n  word"',
            '"Data, *rolling*\n  forecasts"\nheader: |\n  abstract: not a key',
        ):
            with self.subTest(value=value):
                text = PAPER.replace('title: "Thresholds"\n', f"title: {value}\n")
                self.assertEqual(block_lines(text), ABSTRACT_LINES)

    def test_values_set_no_key(self):
        """Markdown emphasis, punctuation, quoted escapes, and tags or
        anchors on values set no key, so they leave the abstract readable."""
        for value in (
            '"Wow!"',
            "A & B",
            "A*B",
            "50% & up",
            '"Line\\nbreak"',
            "[a, b]",
            "Why? Because",
            "A ?B",
            '"Public consumption data, *rolling* forecasts"',
            "Public consumption data, *rolling* forecasts",
            '"**Bold**, _italic_ and &amp;"',
            '"a, &b c: d"',
            "'It''s *done*: yes'",
            '"A \\"quoted\\" word"',
            '["SPM", "Line\\nbreak"]',
            "&on true",
            "!!str style.css",
            "'It''s, *k : a note'",
            "true # see: 'draft",
            "true # see [note]: here",
        ):
            with self.subTest(value=value):
                text = PAPER.replace('title: "Thresholds"\n', f'title: "Thresholds"\nnote: {value}\n')
                self.assertEqual(block_lines(text), ABSTRACT_LINES)
        for name, lines in {
            "emphasis after a line break": "subtitle: Public consumption data,\n  *rolling* forecasts\n",
            "tagged sequence entry": "css:\n  - !!str style.css\n",
            "escaped sequence entry": 'keywords:\n  - "Line\\nbreak"\n',
        }.items():
            with self.subTest(case=name):
                text = PAPER.replace('title: "Thresholds"\n', f'title: "Thresholds"\n{lines}')
                self.assertEqual(block_lines(text), ABSTRACT_LINES)

    def test_key_text_inside_another_block_names_nothing(self):
        """A block scalar's lines hold text, not keys, and a YAML comment
        line holds neither, so they leave the abstract's block readable."""
        for name, text in {
            "literal block": PAPER.replace(
                "        \\usepackage{needspace}\n",
                "        \\usepackage{needspace}\n        abstract: |\n        {abstract: x}\n",
            ),
            "folded block in a sequence": PAPER.replace(
                'title: "Thresholds"\n',
                'title: "Thresholds"\nnotes:\n  - >-\n    abstract: 9.99\n',
            ),
            "comment line": PAPER.replace(
                'title: "Thresholds"\n', 'title: "Thresholds"\n# old notes, abstract: 9.99\n'
            ),
        }.items():
            with self.subTest(case=name):
                self.assertEqual(block_lines(text), ABSTRACT_LINES)

    def test_a_key_after_the_front_matter_fails_closed(self):
        """pandoc lets a metadata block anywhere in the body, even inside a
        list item or block quote, replace the front matter's abstract, so any
        line after the front matter that names the key, at its start or in
        flow style, empties the slice."""
        for name, insert in {
            "metadata block": "---\nabstract: |\n  Body copy.\n---\n",
            "metadata block closed by dots": "---\nabstract: |\n  Body copy.\n...\n",
            "list item": "- item\n\n  ---\n  abstract: |\n    Body copy.\n  ---\n",
            "block quote": "> ---\n> abstract: |\n>   Body copy.\n> ---\n",
            "quoted key": '---\n"abstract": |\n  Body copy.\n---\n',
            "explicit key": "---\n? abstract\n: |\n  Body copy.\n---\n",
            "explicit key with a comment": "---\n? abstract # set here\n: |\n  Body copy.\n---\n",
            "bare key line": "abstract: Body copy.\n",
            "bare explicit key line with a comment": "? abstract # set here\n: Body copy.\n",
            "flow mapping": "---\n{abstract: Body copy.}\n---\n",
            "quoted flow key after a comma": '---\n{title: X, "abstract": Body copy.}\n---\n',
            "explicit flow key": "---\n{? abstract : Body copy.}\n---\n",
            "flow key on a line led by a comma": "---\n{title: X\n, abstract: Body copy.}\n---\n",
            "flow mapping in a block quote": "> ---\n> {abstract: Body copy.}\n> ---\n",
        }.items():
            with self.subTest(case=name):
                self.assertIsNone(block_scalar_span(with_body(insert), "abstract"))
        right_after = PAPER.replace(CLOSE, f"---\n---\nabstract: |\n  Body copy.\n{CLOSE}")
        self.assertIsNone(block_scalar_span(right_after, "abstract"))
        moved = PAPER.replace("abstract: |\n", "summary: |\n").replace(
            "Body text.\n", f"Body text.\n\nabstract: |\n{ABSTRACT_LINES}"
        )
        self.assertIsNone(block_scalar_span(moved, "abstract"))

    def test_a_metadata_block_in_the_body_fails_closed(self):
        """pandoc and Quarto resolve aliases, anchors, tags and escapes in a
        body metadata block's keys, which the parser does not, so any such
        block fails closed whatever its keys spell."""
        for name, insert in {
            "alias": "---\nk: &k abstract\n*k : Body copy 9.99.\n---\n",
            "anchored explicit key": "---\n? &k abstract\n: Body copy 9.99.\n---\n",
            "escaped quoted key": '---\n"\\x61bstract": Body copy 9.99.\n---\n',
            "tagged key": "---\n!!str abstract: Body copy 9.99.\n---\n",
            "another key": "---\nnote: Body copy 9.99.\n---\n",
            "closed by dots": "---\nnote: Body copy 9.99.\n...\n",
            "list item": "- item\n\n  ---\n  note: Body copy 9.99.\n  ---\n",
            "block quote": "> ---\n> note: Body copy 9.99.\n> ---\n",
            "numbered list item": "1. ---\n   note: Body copy 9.99.\n   ---\n",
            "example list item": '(@) ---\n    "\\x61bstract": Body copy 9.99.\n    ---\n',
            "labeled example list item": "(@good) ---\n    !!str abstract: Body copy 9.99.\n    ---\n",
            "grid table cell": (
                "+--------------------------------+\n"
                "| ---                            |\n"
                "| abstract: Body copy 9.99.      |\n"
                "| ---                            |\n"
                "+--------------------------------+\n"
            ),
            "escaped key in a grid table cell": (
                "+--------------------------------+\n"
                "| ---                            |\n"
                '| "\\x61bstract": Body copy 9.99. |\n'
                "| ---                            |\n"
                "+--------------------------------+\n"
            ),
            "grid table in a list item": (
                "- +--------------------------------+\n"
                "  | ---                            |\n"
                '  | "\\x61bstract": Body copy 9.99. |\n'
                "  | ---                            |\n"
                "  +--------------------------------+\n"
            ),
            "opener after an HTML tag": '<div>---\n"\\x61bstract": Body copy 9.99.\n---\n</div>\n',
            "opener after a closing tag": '<div>\n\n</div>---\n"\\x61bstract": Body copy 9.99.\n---\n',
            "opener after an empty tag": '<hr>---\n"\\x61bstract": Body copy 9.99.\n---\n',
            "opener after a processing instruction": '<?x y?>---\n"\\x61bstract": Body copy 9.99.\n---\n',
            "opener after a footnote label": "Text.[^n]\n\n[^n]:---\n    !!str abstract: Body copy 9.99.\n    ---\n",
            "opener after a ten-digit list marker": (
                "1234567890. ---\n            &a abstract: Body copy 9.99.\n            ---\n"
            ),
            "opener after a definition marker": "Term\n\n: ---\n    !!str abstract: Body copy 9.99.\n    ---\n",
            "opener in a block quote in a list item": (
                "- > ---\n  > !!str abstract: Body copy 9.99.\n  > ---\n"
            ),
            "opener with trailing spaces": '---  \n"\\x61bstract": Body copy 9.99.\n---  \n',
            "opener before a YAML comment": '---\n#. >\n"\\x61bstract": Body copy 9.99.\n---\n',
            "opener before a bare block quote marker": '---\n  >\n"\\x61bstract": Body copy 9.99.\n---\n',
        }.items():
            with self.subTest(case=name):
                self.assertIsNone(block_scalar_span(with_body(insert), "abstract"))
                crlf = with_body(insert).replace("\n", "\r\n")
                self.assertIsNone(block_scalar_span(crlf, "abstract"))

    def test_a_thematic_break_is_not_a_metadata_block(self):
        """A ``---`` line opens a metadata block only before a line with text
        and a later closing line, so a thematic break leaves the block
        readable."""
        for insert in (
            "---\n",
            "---\n\nText after a break.\n",
            "Text.\n\n---\nMore.",
            "---\n\nText between two breaks.\n\n---\n",
            "---\n---\n",
            "----\nText under a rule.\n\n---\n",
            "<hr>---\n\nText after a rule.\n\n---\n",
            "Text with +----+ inside.\n",
        ):
            with self.subTest(insert=insert):
                self.assertEqual(block_lines(with_body(insert)), ABSTRACT_LINES)

    def test_prose_that_mentions_the_abstract_does_not_name_the_key(self):
        for line in (
            "The abstract: 9.99 percent.",
            "Abstract: 9.99 percent.",
            "abstracts: 9.99 percent",
            "abstract-note: 9.99 percent",
            "abstract",
            "? abstracts",
            "The title, abstract and keywords.",
            "{abstracts: 9.99}",
            "- > abstracts: 9.99 percent",
        ):
            with self.subTest(line=line):
                self.assertEqual(block_lines(with_body(line)), ABSTRACT_LINES)

    def test_the_block_ends_at_the_next_top_level_field(self):
        text = PAPER.replace(CLOSE, f'note: "2.29 percent"\n{CLOSE}')
        self.assertEqual(block_lines(text), ABSTRACT_LINES)

    def test_the_first_line_with_text_sets_the_indentation(self):
        deeper = "  First line,\n    a deeper line,\n  and a third.\n"
        self.assertEqual(block_lines(with_lines(deeper)), deeper)
        # YAML ends the block at the two-space line, which then sits deeper
        # than the key and holds no key, so the parser fails closed on it.
        shallower = "    Four spaces,\n  then two.\n"
        self.assertIsNone(block_scalar_span(with_lines(shallower), "abstract"))
        self.assertEqual(
            block_problem(with_lines(shallower), "abstract"),
            f"line {PAPER.count(chr(10), 0, PAPER.index('abstract: |')) + 3}, in the front matter, "
            "is YAML the guard does not read",
        )
        leading_blank = "\n" + ABSTRACT_LINES
        self.assertEqual(block_lines(with_lines(leading_blank)), leading_blank)

    def test_only_spaces_and_tabs_make_a_line_blank(self):
        """YAML reads a no-break space as text, so a first line of spaces and
        a no-break space sets the block's indentation, as pandoc reads it."""
        lines = "   \u00a0\n    Four 2.29,\n   three 9.99.\n"
        self.assertEqual(block_lines(with_lines(lines)), lines)

    def test_a_trailing_comment_ends_the_block(self):
        """YAML ends the block at a line indented less than its first line,
        a comment included, so the comment's text stays out of the slice."""
        comment = "# We obtain 9.99 percent with the Consumer Price Index.\n"
        for lines, indent in (
            (ABSTRACT_LINES, 0),
            (ABSTRACT_LINES, 1),
            (ABSTRACT_LINES + "\n", 1),
            (ABSTRACT_LINES + "\t\n", 1),
            (FOUR_SPACE_LINES, 3),
        ):
            with self.subTest(lines=lines, indent=indent):
                text = with_lines(lines + " " * indent + comment)
                self.assertEqual(block_lines(text), lines)

    def test_a_hash_line_indented_like_the_block_is_text(self):
        """A literal block keeps a "#" line at its own indentation as text,
        even after a line of whitespace."""
        for lines in (
            ABSTRACT_LINES + "  # 9.99 percent\n",
            ABSTRACT_LINES + "\t\n  # 9.99 percent\n",
        ):
            with self.subTest(lines=lines):
                self.assertEqual(block_lines(with_lines(lines)), lines)

    def test_blank_lines_stay_inside_the_block(self):
        for blank in ("\n", "  \n", "\t\n", " \t \n"):
            with self.subTest(blank=blank):
                text = with_lines(f"{ABSTRACT_LINES}{blank}  A second paragraph.\n")
                self.assertEqual(
                    block_text(text),
                    "First line of the abstract, then its second line. A second paragraph.",
                )

    def test_a_tab_within_the_indentation_fails_closed(self):
        """Quarto rejects a tab within the block's indentation, or ends the
        block there, where pandoc reads the line as text."""
        for lines in (
            ABSTRACT_LINES + "\tTabbed text.\n",
            ABSTRACT_LINES + " \tTabbed text.\n",
            ABSTRACT_LINES + "\t# A comment.\n",
            FOUR_SPACE_LINES + "  \tTabbed text.\n",
            "\tTabbed first line.\n" + ABSTRACT_LINES,
        ):
            with self.subTest(lines=lines):
                self.assertIsNone(block_scalar_span(with_lines(lines), "abstract"))

    def test_a_tab_after_the_indentation_is_text(self):
        for lines in (
            "  First line,\twith a tab inside it.\n",
            ABSTRACT_LINES + "  \tTabbed text.\n",
            "  \tTabbed first line,\n  then its second line.\n",
            "  First line,\n    \ta deeper tabbed line.\n",
        ):
            with self.subTest(lines=lines):
                self.assertEqual(block_lines(with_lines(lines)), lines)

    def test_dots_also_close_the_front_matter(self):
        text = PAPER.replace(CLOSE, "...\n# Introduction")
        self.assertEqual(block_lines(text), ABSTRACT_LINES)

    def test_missing_or_unterminated_front_matter_fails_closed(self):
        cases = {
            "unterminated": PAPER.replace(CLOSE, "# Introduction"),
            "no opening delimiter": PAPER.removeprefix("---\n"),
            "text before the delimiter": "Preface.\n" + PAPER,
            "blank line after the delimiter": PAPER.replace("---\n", "---\n\n", 1),
            "spaces after the delimiter": PAPER.replace("---\n", "---\n   \n", 1),
            "separator after the closing dashes": PAPER.replace(
                CLOSE, "---\u2028\n# Introduction"
            ),
            "empty": "",
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                self.assertIsNone(block_scalar_span(text, "abstract"))

    def test_an_empty_block_fails_closed(self):
        for filler in ("", "\n", "  \n\n"):
            with self.subTest(filler=filler):
                text = PAPER.replace(ABSTRACT_LINES, filler)
                self.assertIsNone(block_scalar_span(text, "abstract"))
        for field in ("note: |\n", "note: Field text.\n", "\nnote: |\n"):
            with self.subTest(field=field):
                text = PAPER.replace("abstract: |\n", f"abstract: |\n{field}")
                self.assertIsNone(block_scalar_span(text, "abstract"))

    def test_windows_line_endings_keep_the_span_exact(self):
        text = PAPER.replace("\n", "\r\n")
        self.assertEqual(block_lines(text), ABSTRACT_LINES.replace("\n", "\r\n"))

    def test_a_lone_carriage_return_fails_closed_anywhere(self):
        """Quarto ends a line at a carriage return that no line feed follows,
        which pandoc drops, so a body line "abstract: |" glued to the end of
        another sets Quarto's abstract alone. The parser fails closed on such
        a carriage return anywhere in the file and says on which line."""
        for name, (text, number) in {
            "every line": (PAPER.replace("\n", "\r"), 1),
            "inside the abstract": (with_lines("  First line\rof the abstract.\n"), PAPER.count("\n", 0, PAPER.index("abstract: |")) + 2),
            "inside the title": (PAPER.replace('"Thresholds"', '"Thresh\rolds"'), 2),
            "in the body": (PAPER.replace("Body text.\n", "Body\rtext.\n"), PAPER.count("\n", 0, PAPER.index("Body text.")) + 1),
            "a body key after it": (PAPER.replace("Body text.\n", "Body text.\rabstract: |\r  Other 9.99.\n"), PAPER.count("\n", 0, PAPER.index("Body text.")) + 1),
        }.items():
            with self.subTest(case=name):
                self.assertIsNone(block_scalar_span(text, "abstract"))
                self.assertIsNone(block_words(text, "abstract"))
                self.assertEqual(
                    block_problem(text, "abstract"),
                    f"line {number} holds a carriage return without a line feed or a Unicode line "
                    "separator, where Quarto and pandoc end lines differently",
                )
        crlf = PAPER.replace("\n", "\r\n")
        self.assertEqual(block_words(crlf, "abstract"), words(ABSTRACT_LINES))

    def test_windows_line_endings_keep_every_rule(self):
        """Each rule that fails closed on line feeds fails closed on carriage
        return and line feed pairs too."""
        for name, text in {
            "explicit key repeated": PAPER.replace(CLOSE, f"? abstract\n: |\n  Copy.\n{CLOSE}"),
            "explicit key with a comment": PAPER.replace(
                CLOSE, f"? abstract # c\n: |\n  Copy.\n{CLOSE}"
            ),
            "key in the body": with_body("abstract: Body copy.\n"),
            "flow key in the body": with_body("---\n{abstract: Body copy.}\n---\n"),
            "nested key": FORMAT_LEVEL_KEY,
            "tab within the indentation": with_lines(ABSTRACT_LINES + "\tTabbed.\n"),
        }.items():
            with self.subTest(case=name):
                self.assertIsNone(block_scalar_span(text.replace("\n", "\r\n"), "abstract"))

    def test_only_line_feeds_end_lines(self):
        """A form feed or vertical tab stays inside its line, so it cannot
        end the block early. Quarto's metadata search matches line starts and
        ends at the Unicode line and paragraph separators and at a next-line
        character, so each fails closed wherever it falls."""
        for separator in ("\x0c", "\x0b"):
            with self.subTest(separator=repr(separator)):
                lines = f"  First line,{separator}then more.\n  Second line.\n"
                self.assertEqual(block_lines(with_lines(lines)), lines)
        for separator in ("\u2028", "\u2029", "\x85"):
            for name, text in {
                "abstract": with_lines(f"  First line,{separator}then more.\n  Second line.\n"),
                "body": PAPER.replace("Body text.\n", f"Body{separator}text.\n"),
            }.items():
                with self.subTest(separator=repr(separator), place=name):
                    self.assertIsNone(block_scalar_span(text, "abstract"))
                    self.assertIn("Unicode line separator", block_problem(text, "abstract"))

    def test_reasons_name_the_line_and_the_problem(self):
        """The guard prints the parser's reason, so each names the line, as
        the file numbers it, and what the parser cannot read there."""
        key_row = PAPER.count("\n", 0, PAPER.index("abstract: |")) + 1
        for name, (text, reason) in {
            "tab in indentation": (
                with_lines(FOUR_SPACE_LINES + "  \tTabbed 9.99.\n"),
                f"line {key_row + 3}, in the front matter, has a tab in its indentation",
            ),
            "anchored key": (
                PAPER.replace("format:\n", "&k note: Text.\nformat:\n"),
                "line 3, in the front matter, is YAML the guard does not read",
            ),
            "tagged key": (
                PAPER.replace("format:\n", "!!str note: Text.\nformat:\n"),
                "line 3, in the front matter, is YAML the guard does not read",
            ),
            "comment in the front matter": (
                PAPER.replace("format:\n", "<!-- note -->\nformat:\n"),
                "line 3, in the front matter, holds an HTML comment or a code fence, "
                "which Quarto deletes before it reads the YAML",
            ),
            "quoted key": (
                PAPER.replace("abstract: |\n", '"abstract": |\n'),
                f"line {key_row}, in the front matter, is YAML the guard does not read",
            ),
            "key line with a comment": (
                PAPER.replace("abstract: |\n", "abstract: | # note\n"),
                f"line {key_row}, in the front matter, sets abstract other than on a top-level abstract: | line",
            ),
            "repeated key": (
                PAPER.replace(CLOSE, f"abstract: |\n  Decoy 9.99.\n{CLOSE}"),
                f"the front matter sets abstract on lines {key_row} and {key_row + 3}",
            ),
            "no key": (PAPER.replace("abstract: |\n", "summary: |\n"), "the front matter has no top-level abstract: | line"),
            "empty block": (
                PAPER.replace("abstract: |\n" + ABSTRACT_LINES, "abstract: |\nnote: |\n" + ABSTRACT_LINES),
                "the abstract block holds no text",
            ),
            "quote left open": (
                PAPER.replace('title: "Thresholds"\n', 'title: "Thresholds\n'),
                "a quote opened on line 2 is still open at the front matter's end",
            ),
            "no front matter": ("# Introduction\n", "the file must open with front matter: a --- line, then a line with text"),
            "front matter never closes": (
                PAPER.replace(CLOSE, "# Introduction"),
                "the front matter never closes with a --- or ... line",
            ),
            "body key": (
                with_body("- abstract: Body copy 9.99.\n"),
                f"line {PAPER.count(chr(10)) + 2}, in the body, could set abstract",
            ),
            "body key behind two containers": (
                with_body("- > abstract: Body copy 9.99.\n"),
                f"line {PAPER.count(chr(10)) + 2}, in the body, could set abstract",
            ),
            "body key after an example marker": (
                with_body("(@) abstract: Body copy 9.99.\n"),
                f"line {PAPER.count(chr(10)) + 2}, in the body, could set abstract",
            ),
            "body key after a parenthesized number": (
                with_body("1) abstract: Body copy 9.99.\n"),
                f"line {PAPER.count(chr(10)) + 2}, in the body, could set abstract",
            ),
            "body key in a definition": (
                with_body("Term\n\n: abstract: Body copy 9.99.\n"),
                f"line {PAPER.count(chr(10)) + 4}, in the body, could set abstract",
            ),
            "hidden body opener": (
                with_body('<div>---\n"\\x61bstract": Body copy 9.99.\n---\n</div>\n'),
                f"line {PAPER.count(chr(10)) + 2}, in the body, could open a metadata block, "
                "which sets the paper's metadata",
            ),
            "comment-glued body fences": (
                with_body('<!-- -->---\n"\\x61bstract": Body copy 9.99.\n<!-- -->---\n'),
                "once Quarto deletes HTML comments, a body line could open a metadata block, "
                "which sets the paper's metadata",
            ),
            "markup": (
                with_lines("  First *line*.\n"),
                "the abstract may hold only letters, digits, spaces, dashes and . , ; : ( ) ' \" ? ! / +, "
                "and holds '*'",
            ),
        }.items():
            with self.subTest(case=name):
                self.assertEqual(block_problem(text, "abstract"), reason)
        self.assertIsNone(block_problem(PAPER, "abstract"))

    def test_only_plain_prose_reads(self):
        """Every character outside letters, ASCII digits, spaces, dashes, plus
        signs and sentence punctuation fails the abstract closed, so no
        markup, symbol or invisible character reaches a tie."""
        for character in "*_`<>[]{}\\&$#|~^@=%\u2248\u00a7\u00a9\u2026\u200b\u00ad\ufeff\u0661":
            with self.subTest(character=repr(character)):
                text = with_lines(f"  First{character}line 9.99.\n")
                self.assertIsNotNone(block_scalar_span(text, "abstract"))
                self.assertIsNone(block_words(text, "abstract"))
                self.assertEqual(
                    block_problem(text, "abstract"),
                    "the abstract may hold only letters, digits, spaces, dashes and . , ; : ( ) ' \" ? ! / +, "
                    f"and holds {character!r}",
                )
        for character in "\u00e9\u00df\u4e2d.,;:()'\"?!/+\u2013\u2014\u2212\u2018\u2019\u201c\u201d\u00a0":
            with self.subTest(character=repr(character)):
                text = with_lines(f"  First{character}line 9.99.\n")
                self.assertIsNotNone(block_words(text, "abstract"))

    def test_the_key_matches_literally(self):
        """The parser matches a key as written, never as a pattern, and reads
        only keys named in letters, digits, "_" and "-"."""
        text = PAPER.replace("abstract: |\n", "abXtract: |\n")
        self.assertIsNone(block_scalar_span(text, "ab.tract"))
        self.assertEqual(block_problem(text, "ab.tract"), "the front matter has no top-level ab.tract: | line")
        dotted = PAPER.replace("abstract: |\n", "ab.tract: |\n")
        self.assertIsNone(block_scalar_span(dotted, "ab.tract"))
        hyphen = PAPER.replace("abstract: |\n", "ab-tract: |\n")
        self.assertEqual(block_lines(hyphen, "ab-tract"), ABSTRACT_LINES)
        lookalike = hyphen.replace(
            'title: "Thresholds"\n', 'title: "Thresholds"\nab_tract: Other\nabXtract: Other\n'
        ) + "\nabXtract: Body\n"
        self.assertEqual(block_lines(lookalike, "ab-tract"), ABSTRACT_LINES)


class BlockWordsTests(unittest.TestCase):
    def test_reads_the_block_as_words(self):
        self.assertEqual(block_words(PAPER, "abstract"), words(ABSTRACT_LINES))

    def test_markup_that_renders_as_other_text_fails_closed(self):
        """Quarto and pandoc leave an HTML comment out of the rendered
        abstract, or show it as text inside a code span, after a backslash or
        when it never closes; Quarto deletes a backtick code fence, renders a
        shortcode as other text and drops raw content from the HTML. So the
        parser fails closed on each, rather than guess which words render."""
        for lines in (
            "  First line, <!-- 9.99 percent --> second.\n",
            "  First line,\n  <!-- was: 9.99 percent\n  with the CPI -->\n  second.\n",
            "  Fir<!-- x -->st line.\n",
            "  First line, <!-- 9.99 percent.\n",
            "  First line, <!--> 9.99 percent -->.\n",
            "  First line,\n  ```\n  9.99 percent\n  ```\n  second.\n",
            "  First line, `<!-- 9.99 percent -->`.\n",
            "  First line, \\<!-- 9.99 percent -->.\n",
            "  First line, {{< meta note >}} second.\n",
            "  First line, {{< var rate >}} second.\n",
            "  First line, `9.99 percent`{=latex} second.\n",
        ):
            with self.subTest(lines=lines):
                self.assertIsNotNone(block_scalar_span(with_lines(lines), "abstract"))
                self.assertIsNone(block_words(with_lines(lines), "abstract"))

    def test_markers_that_open_other_blocks_fail_closed(self):
        """pandoc reads a list marker that opens a paragraph, a line of
        hyphens or plus signs and a colon that opens a line as a list, a
        heading, a rule, a table or a definition, and renders other text than
        the parser reads. Each fails closed with a reason. Mid-paragraph, a
        list marker renders as typed, as does a signed number."""
        for name, (lines, reason) in {
            "bullet after a blank line": (
                "  First line.\n\n  - 9.99 percent\n",
                "line 11, in the abstract, opens a paragraph with '-', which pandoc reads as a list marker",
            ),
            "plus bullet on the first line": (
                "  + 9.99 percent\n",
                "line 9, in the abstract, opens a paragraph with '+', which pandoc reads as a list marker",
            ),
            "year as an ordered marker": (
                "  2025. The rate was 9.99 percent.\n",
                "line 9, in the abstract, opens a paragraph with '2025.', which pandoc reads as a list marker",
            ),
            "parenthesized number": (
                "  First line.\n\n  (1) 9.99 percent\n",
                "line 11, in the abstract, opens a paragraph with '(1)', which pandoc reads as a list marker",
            ),
            "letter": (
                "  First line.\n\n  b) 9.99 percent\n",
                "line 11, in the abstract, opens a paragraph with 'b)', which pandoc reads as a list marker",
            ),
            "roman numeral": (
                "  First line.\n\n  iv. 9.99 percent\n",
                "line 11, in the abstract, opens a paragraph with 'iv.', which pandoc reads as a list marker",
            ),
            "bullet after an indented code block": (
                "  First line.\n\n      code\n  - 9.99 percent\n",
                "line 12, in the abstract, opens a paragraph with '-', which pandoc reads as a list marker",
            ),
            "bullet after a tab-indented code block": (
                "  First line.\n\n  \tcode\n  - 9.99 percent\n",
                "line 12, in the abstract, opens a paragraph with '-', which pandoc reads as a list marker",
            ),
            "setext underline": (
                "  9.99 percent\n  ---\n  First line.\n",
                "line 10, in the abstract, holds only hyphens or plus signs, which pandoc reads "
                "as a heading's underline, a rule, a table's border or a list item",
            ),
            "one-hyphen underline": (
                "  9.99 percent\n  -\n",
                "line 10, in the abstract, holds only hyphens or plus signs, which pandoc reads "
                "as a heading's underline, a rule, a table's border or a list item",
            ),
            "simple table border": (
                "  First line.\n\n  ---- ----\n  9.99 1.00\n  ---- ----\n",
                "line 11, in the abstract, holds only hyphens or plus signs, which pandoc reads "
                "as a heading's underline, a rule, a table's border or a list item",
            ),
            "lone plus before text": (
                "  First line.\n\n  +\n  9.99 percent\n",
                "line 11, in the abstract, holds only hyphens or plus signs, which pandoc reads "
                "as a heading's underline, a rule, a table's border or a list item",
            ),
            "definition": (
                "  First line\n  : 9.99 percent\n",
                "line 10, in the abstract, opens with ':', which pandoc reads as a definition list marker",
            ),
            "definition after a tab": (
                "  First line\n  :\t9.99 percent\n",
                "line 10, in the abstract, opens with ':', which pandoc reads as a definition list marker",
            ),
            "lone colon": (
                "  First line\n  :\n",
                "line 10, in the abstract, opens with ':', which pandoc reads as a definition list marker",
            ),
            "uppercase roman numeral": (
                "  First line.\n\n  IV. 9.99 percent\n",
                "line 11, in the abstract, opens a paragraph with 'IV.', which pandoc reads as a list marker",
            ),
            "uppercase letter": (
                "  First line.\n\n  B) 9.99 percent\n",
                "line 11, in the abstract, opens a paragraph with 'B)', which pandoc reads as a list marker",
            ),
            "tab after a marker": (
                "  First line.\n\n  1.\t9.99 percent\n",
                "line 11, in the abstract, opens a paragraph with '1.', which pandoc reads as a list marker",
            ),
            "ten-digit number": (
                "  1234567890. 9.99 percent\n",
                "line 9, in the abstract, opens a paragraph with '1234567890.', which pandoc reads as a list marker",
            ),
            "number after a code block under a no-break space": (
                "  \xa0\n\n      The blend yields 1.17 percent in\n   2025. The next sentence.\n",
                "line 12, in the abstract, opens a paragraph with '2025.', which pandoc reads as a list marker",
            ),
        }.items():
            with self.subTest(case=name):
                text = with_lines(lines)
                self.assertIsNotNone(block_scalar_span(text, "abstract"))
                self.assertIsNone(block_words(text, "abstract"))
                self.assertEqual(block_problem(text, "abstract"), reason)
        for lines in (
            "  First line, then\n  - 9.99 percent.\n",
            "  First line, then\n  + 9.99 percent.\n",
            "  First line, then\n  2025. was 9.99 percent.\n",
            "  +1.04 points and\n  -0.63 points, or \u22120.63.\n",
            "  1.17 percent, e.g. this.\n\n  U.S. rates: 9.99.\n",
            "  First line.\n  \u2013\u2013\n",
            "  Rates: 9.99 to 10.00\n  :not a marker.\n",
        ):
            with self.subTest(lines=lines):
                self.assertIsNotNone(block_words(with_lines(lines), "abstract"))

    def test_edge_cases_read_or_fail_closed_as_pinned(self):
        """A change that newly fails closed on an edge case, or newly reads
        one, fails here, whether or not pandoc and Quarto are installed."""
        read = {name for name, text in EDGE_CASES.items() if block_words(text, "abstract") is not None}
        self.assertEqual(read, EDGE_CASES_READ)

    def test_no_block_reads_as_none(self):
        self.assertIsNone(block_words(PAPER.replace("abstract: |", "abstract: >"), "abstract"))


class StatedValuesTests(unittest.TestCase):
    def test_reads_the_value_in_the_slot(self):
        text = "we obtain 2.29 percent with the Consumer Price Index for All Urban"
        self.assertEqual(stated_values(CPI_U, text), ["2.29"])

    def test_a_dash_signs_the_value_or_joins_a_range(self):
        """A writer can type an en dash, a hyphen, two hyphens or another dash
        for a minus sign or a range, spaced or not, and a slash or a word such
        as "to", "and" or "through" for a range, so the slot reads the dash as
        the value's sign and the range as one value, never as the bare rate.
        A tie then fails even beside a correct copy of the rate. A dash typed
        as punctuation before a rate reads as its sign too, so such a
        statement fails its tie rather than pass a sign flip."""
        for value in (
            "--2.29",
            "-- 2.29",
            "2.20 and 2.29",
            "2.20 or 2.29",
            "2.20 through 2.29",
            "2.20 thru 2.29",
            "2.20 until 2.29",
            "2.20 vs. 2.29",
            "2.20 versus 2.29",
            "2.20/2.29",
            "2.20 / 2.29",
            "\u20132.29",
            "\u20112.29",
            "\u20142.29",
            "2.20\u20132.29",
            "2.20-2.29",
            "2.29\u20132.40",
            "\u2013 2.29",
            "\u2212 2.29",
            "2.20 \u2013 2.29",
            "2.20 - 2.29",
            "2.20 to 2.29",
            "2.20 to\n  2.29",
            "2.20 vs 2.29",
            "2.20 till 2.29",
            "2.20 To 2.29",
            "2.20 AND 2.29",
            "2.20 percent to 2.29",
            "2.20 percent and 2.29",
        ):
            with self.subTest(value=value):
                text = f"of {value} percent with the Consumer Price Index"
                self.assertEqual(stated_values(CPI_U, text), [value])
                both = f"{text}, and of 2.29 percent with the Consumer Price Index"
                self.assertEqual(stated_values(CPI_U, both), [value, "2.29"])

    def test_a_dash_that_cannot_sign_the_value_hides_the_bare_rate(self):
        """After a digit, point or comma, a dash cannot start the slot as a
        sign, and the bare rate after it reads as no value."""
        for text in (
            "in 2025.\u20132.29 percent with the Consumer Price Index",
            "of 1.17,\u20132.29 percent with the Consumer Price Index",
            "of 2.10\u20132.20\u20132.29 percent with the Consumer Price Index",
        ):
            with self.subTest(text=text):
                self.assertEqual(stated_values(CPI_U, text), [])

    def test_to_after_a_word_opens_no_range(self):
        for joiner in ("to", "and", "through", "/"):
            with self.subTest(joiner=joiner):
                text = f"errors fall {joiner} 2.29 percent with the Consumer Price Index"
                self.assertEqual(stated_values(CPI_U, text), ["2.29"])

    def test_the_slot_starts_a_token(self):
        """The slot starts only at a whitespace-separated token's start or
        after "(", so a rate glued to other text reads as no rate."""
        for text, expected in (
            ("of x2.29 percent with the Consumer Price Index", []),
            ("of US2.29 percent with the Consumer Price Index", []),
            ('of "2.29 percent with the Consumer Price Index', []),
            ("of +2.29 percent with the Consumer Price Index", []),
            ("of (2.29 percent with the Consumer Price Index", ["2.29"]),
            ("of\n2.29 percent with the Consumer Price Index", ["2.29"]),
        ):
            with self.subTest(text=text):
                self.assertEqual(stated_values(CPI_U, text), expected)

    def test_template_words_match_whole_words(self):
        """Words added to the start or end of a template's wording, as in a
        renamed rule, leave the statement unread."""
        for template, text in (
            (CPI_U, "2.29 percent with the Consumer Price Indexes"),
            (CPI_U, "2.29 percent with the Consumer Price Index-based rule"),
            ("error of {}", "a terror of 1.17"),
            ("error of {}", "an end-error of 1.17"),
        ):
            with self.subTest(text=text):
                self.assertEqual(stated_values(template, text), [])

    def test_keeps_a_sign(self):
        for sign in (MINUS, "-"):
            with self.subTest(sign=sign):
                text = f"of {sign}2.29 percent with the Consumer Price Index"
                self.assertEqual(stated_values(CPI_U, text), [f"{sign}2.29"])

    def test_reads_whole_numeric_tokens(self):
        cases = {
            "12.29": ["12.29"],
            "2.290": ["2.290"],
            "1,234.5": ["1,234.5"],
            "1.2.29": [],
            "2.29.1": [],
        }
        for number, expected in cases.items():
            with self.subTest(number=number):
                text = f"of {number} percent with the Consumer Price Index"
                self.assertEqual(stated_values(CPI_U, text), expected)

    def test_lists_every_statement_in_order(self):
        text = (
            "2.29 percent with the Consumer Price Index and, in a later "
            "sentence, 2.30 percent with the Consumer Price Index"
        )
        self.assertEqual(stated_values(CPI_U, text), ["2.29", "2.30"])

    def test_any_whitespace_run_meets_a_template_space(self):
        text = "2.29\n  percent with   the\tConsumer\n  Price Index"
        self.assertEqual(stated_values(CPI_U, text), ["2.29"])

    def test_a_template_space_needs_whitespace(self):
        text = "2.29percent with the Consumer Price Index"
        self.assertEqual(stated_values(CPI_U, text), [])

    def test_the_slot_can_take_a_word(self):
        text = "We compare four projection rules."
        self.assertEqual(
            stated_values("compare {} projection rules", text, r"\S+"), ["four"]
        )

    def test_a_template_needs_exactly_one_slot(self):
        text = "2.29 and 1.65 percent with the Consumer Price Index"
        for template in ("percent with the Consumer Price Index", "{} and {} percent"):
            with self.subTest(template=template):
                self.assertEqual(stated_values(template, text), [])

    def test_sentence_punctuation_ends_a_number(self):
        text = "an error of 1.17. Later, an error of 0.75, and then"
        self.assertEqual(stated_values("error of {}", text), ["1.17", "0.75"])

    def test_a_point_or_comma_before_a_digit_continues_the_number(self):
        """A point or comma followed by a digit belongs to a longer number,
        so the slot reads none of it."""
        for text in ("an error of 1.17.5", "an error of 1.17,5", "an error of 1.17.0 percent"):
            with self.subTest(text=text):
                self.assertEqual(stated_values("error of {}", text), [])

    def test_template_words_need_whitespace_between_them(self):
        text = "2.29 percentwith the Consumer Price Index"
        self.assertEqual(stated_values(CPI_U, text), [])


VOCABULARY = (
    "thresholds",
    "tenure",
    "renters",
    "spending",
    "survey",
    "window",
    "basic",
    "needs",
    "records",
    "growth",
)
DECOY_STATEMENT = "We obtain 9.99 percent with the Consumer Price Index."


def random_number(rng):
    """A signed decimal, integer or thousands-separated number."""
    kind = rng.randrange(3)
    if kind == 0:
        digits = f"{rng.uniform(0, 100):.{rng.randint(1, 4)}f}"
    elif kind == 1:
        digits = str(rng.randint(0, 999))
    else:
        digits = f"{rng.randint(1_000, 9_999_999):,}"
    return rng.choice(("", "", MINUS, "-")) + digits


def random_space(rng):
    return rng.choice((" ", "  ", "\n", "\n  ", "\t", " \n    "))


def random_document(rng, statement=""):
    """Front matter holding one abstract literal block among other fields,
    and a body, as lists the property tests can edit, plus the abstract's
    words. `statement` lands at a random place in the abstract. Lines after
    the block's first may sit deeper, and blank lines between paragraphs may
    hold spaces or a tab."""
    filler = VOCABULARY + ("2.29", "percent", f"{MINUS}0.51", "1,234")
    paragraphs = [
        [rng.choice(filler) for _ in range(rng.randint(1, 30))]
        for _ in range(rng.randint(1, 3))
    ]
    if statement:
        words = rng.choice(paragraphs)
        at = rng.randint(0, len(words))
        words[at:at] = statement.split()
    indent = " " * rng.choice((1, 2, 4))
    width = rng.randint(8, 72)
    block = []
    for number, words in enumerate(paragraphs):
        if number:
            block.append(rng.choice(("", " ", indent, "\t")))
        for line in textwrap.wrap(
            " ".join(words), width, break_long_words=False, break_on_hyphens=False
        ):
            deeper = rng.choice(("", "", "", "  ")) if block else ""
            block.append(indent + deeper + line)
    fields = [
        ['title: "Thresholds"'],
        [
            "format:",
            "  pdf:",
            "    include-in-header:",
            "      text: |",
            "        abstract: |",
            "          Nested copy 9.99.",
        ],
        ['abstract-title: "Summary"'],
        ["keywords:", "  - poverty", "  - thresholds"],
    ]
    rng.shuffle(fields)
    fields.insert(rng.randint(0, len(fields)), ["abstract: |", *block])
    body = ["# Introduction", "", "Body copy 9.99.", ""]
    abstract = " ".join(word for words in paragraphs for word in words)
    return fields, rng.choice(("---", "...")), body, abstract


def render(fields, terminator, body):
    lines = ["---", *(line for field in fields for line in field), terminator, *body]
    return "\n".join(lines) + "\n"


def add_decoys(rng, fields, body):
    """Restate a rate in another top-level field, in a comment after the
    abstract indented less than its block, and in the body's prose."""
    decoy_fields = (
        [f'note: "{DECOY_STATEMENT}"'],
        ["notes:", f"  - {DECOY_STATEMENT}"],
        ["abstract-note: |", f"  {DECOY_STATEMENT}"],
    )
    abstract = next(field for field in fields if field[0] == "abstract: |")
    indent = len(abstract[1]) - len(abstract[1].lstrip(" "))
    blank = rng.choice(([], [""], ["\t"]))
    abstract.extend([*blank, " " * rng.randrange(indent) + f"# {DECOY_STATEMENT}"])
    fields.insert(rng.randint(0, len(fields)), list(rng.choice(decoy_fields)))
    at = rng.randint(0, len(body))
    body[at:at] = [DECOY_STATEMENT, "", f"The abstract: {DECOY_STATEMENT}"]


class PropertyTests(unittest.TestCase):
    ROUNDS = 300

    def test_the_abstract_round_trips(self):
        rng = random.Random(20261107)
        for _ in range(self.ROUNDS):
            fields, terminator, body, abstract = random_document(rng)
            text = render(fields, terminator, body)
            self.assertEqual(block_text(text), abstract, text)

    def test_text_outside_the_block_never_changes_what_the_guard_reads(self):
        rng = random.Random(20261108)
        for _ in range(self.ROUNDS):
            fields, terminator, body, abstract = random_document(rng)
            add_decoys(rng, fields, body)
            text = render(fields, terminator, body)
            self.assertEqual(block_text(text), abstract, text)

    def test_a_second_or_restyled_key_fails_closed(self):
        rng = random.Random(20261109)
        for _ in range(self.ROUNDS):
            fields, terminator, body, _ = random_document(rng)
            if rng.random() < 0.5:
                second = rng.choice(
                    (
                        ["abstract: |", "  Copy."],
                        ["abstract: Copy."],
                        ['"abstract": |', "  Copy."],
                        ["'abstract': Copy."],
                        ["? abstract", ": Copy."],
                    )
                )
                fields.insert(rng.randint(0, len(fields)), list(second))
            else:
                index = next(
                    i for i, field in enumerate(fields) if field[0] == "abstract: |"
                )
                restyled = rng.choice(
                    (
                        "abstract: >",
                        "abstract: |-",
                        "abstract:",
                        "abstract : |",
                        '"abstract": |',
                        "abstract: | # note",
                    )
                )
                fields[index] = [restyled, *fields[index][1:]]
            text = render(fields, terminator, body)
            self.assertIsNone(block_scalar_span(text, "abstract"), text)

    def test_a_key_after_the_front_matter_fails_closed(self):
        """However a line after the front matter names the key, and whatever
        container or metadata block holds it, the parser fails closed."""
        rng = random.Random(20261113)
        spellings = (
            "abstract: |",
            "abstract: Copy.",
            "abstract : |",
            '"abstract": |',
            "'abstract': |",
            "? abstract",
            "? abstract # set here",
            "{abstract: Copy.}",
            '{title: X, "abstract": Copy.}',
            "{? abstract : Copy.}",
        )
        containers = ("", "  ", "    ", "> ", ">   ", "> > ")
        for _ in range(self.ROUNDS):
            fields, terminator, body, _ = random_document(rng)
            container = rng.choice(containers)
            lines = [container + rng.choice(spellings), container + "  Body copy 9.99."]
            if rng.random() < 0.5:
                lines = [container + "---", *lines, container + rng.choice(("---", "..."))]
            at = rng.randint(0, len(body))
            body[at:at] = lines
            text = render(fields, terminator, body)
            self.assertIsNone(block_scalar_span(text, "abstract"), text)

    def test_a_rate_in_the_abstract_reaches_its_tie_however_it_wraps(self):
        """A rate the abstract states reads back exactly, whatever the
        wrapping and indentation, and a copy outside the block never adds to
        what the tie sees."""
        rng = random.Random(20261110)
        for _ in range(self.ROUNDS):
            value = random_number(rng)
            statement = f"we obtain {value} percent with the Consumer Price Index"
            fields, terminator, body, _ = random_document(rng, statement)
            add_decoys(rng, fields, body)
            text = render(fields, terminator, body)
            self.assertEqual(stated_values(CPI_U, block_text(text)), [value], text)

    def test_values_round_trip_through_any_template_spacing(self):
        rng = random.Random(20261111)
        for _ in range(self.ROUNDS):
            words = rng.sample(VOCABULARY, rng.randint(1, 4))
            cut = rng.randint(0, len(words))
            template = " ".join([*words[:cut], "{}", *words[cut:]])
            values = [random_number(rng) for _ in range(rng.randint(1, 3))]
            text = " ; ".join(
                random_space(rng).join([*words[:cut], value, *words[cut:]])
                for value in values
            )
            self.assertEqual(stated_values(template, text), values, text)

    def test_a_longer_number_never_reads_as_the_value_it_contains(self):
        rng = random.Random(20261112)
        for _ in range(self.ROUNDS):
            value = f"{rng.uniform(0, 10):.2f}"
            digit = str(rng.randrange(10))
            for glued, expected in (
                (digit + value, [digit + value]),
                (value + digit, [value + digit]),
                (f"{digit},{value}", [f"{digit},{value}"]),
                (f"{value}.{digit}", []),
                (f"{digit}.{value}", []),
            ):
                text = f"of {glued} percent with the Consumer Price Index"
                self.assertEqual(stated_values(CPI_U, text), expected, glued)


PANDOC = shutil.which("pandoc")


def words(text):
    """The words of `text`, less any bare "#" marks, which markdown reads as
    a heading's level."""
    return " ".join(token for token in text.split() if token.strip("#"))


# Documents on which the parser and pandoc have disagreed, or could: comments
# and tabs near the block, odd line endings, repeated keys, flow-style keys,
# keys hidden behind tags, anchors and quotes, markup in the abstract, and
# metadata blocks and tables in the body.
EDGE_CASES = {
    "fixture": PAPER,
    "comment at indent 0 after the block": with_lines(ABSTRACT_LINES + "# 9.99 percent\n"),
    "comment at indent 1 after the block": with_lines(ABSTRACT_LINES + " # 9.99 percent\n"),
    "comment at indent 3 after a 4-space block": with_lines(
        FOUR_SPACE_LINES + "   # 9.99 percent\n"
    ),
    "blank line, then a comment at indent 1": with_lines(
        ABSTRACT_LINES + "\n # 9.99 percent\n"
    ),
    "tab line, then a comment at indent 1": with_lines(
        ABSTRACT_LINES + "\t\n # 9.99 percent\n"
    ),
    "hash line at the block's indentation": with_lines(
        ABSTRACT_LINES + "  # 9.99 percent\n"
    ),
    "tab line, then a hash line at the block's indentation": with_lines(
        ABSTRACT_LINES + "\t\n  # 9.99 percent\n"
    ),
    "tab-indented line after the block": with_lines(ABSTRACT_LINES + "\tTabbed 9.99.\n"),
    "space and tab before a line": with_lines(ABSTRACT_LINES + " \tTabbed 9.99.\n"),
    "tab after the block's indentation": with_lines(
        "  First,\n  \tafter a tab 9.99,\n  third.\n"
    ),
    "tab-indented first line": with_lines("\tFirst 9.99.\n  second.\n"),
    "tab after the first line's indentation": with_lines("  \tFirst 9.99,\n  second.\n"),
    "tab after a deeper line's indentation": with_lines("  First,\n    \tdeeper 9.99,\n  third.\n"),
    "tab within a 4-space block's indentation": with_lines(FOUR_SPACE_LINES + "  \tTabbed 9.99.\n"),
    "tab, then a hash, after the block": with_lines(ABSTRACT_LINES + "\t# 9.99 percent\n"),
    "tab line inside the block": with_lines("  First,\n\t\n  second 9.99.\n"),
    "line indented less than the first": with_lines("    Four 1.11,\n  two 9.99.\n"),
    "line indented more than the first": with_lines("  First,\n    deeper 9.99,\n  third.\n"),
    "leading blank line deeper than the text": with_lines("    \n" + ABSTRACT_LINES),
    "U+2028 inside a line": with_lines("  First line\u2028then 9.99.\n  Second.\n"),
    "form feed inside a line": with_lines("  First line\x0cthen 9.99.\n  Second.\n"),
    "carriage returns alone": PAPER.replace("\n", "\r"),
    "carriage return inside a line": with_lines("  First\rsecond 9.99.\n  third.\n"),
    "Windows line endings": PAPER.replace("\n", "\r\n"),
    "blank line after the opening dashes": PAPER.replace("---\n", "---\n\n", 1),
    "closing dashes, then U+2028": PAPER.replace(CLOSE, "---\u2028\n# Introduction"),
    "closing dashes with trailing spaces": PAPER.replace(CLOSE, "---   \n# Introduction"),
    "closing dots": PAPER.replace(CLOSE, "...\n# Introduction"),
    "quoted key repeated after": PAPER.replace(CLOSE, f'"abstract": |\n  Decoy 9.99.\n{CLOSE}'),
    "single-quoted key repeated after": PAPER.replace(
        CLOSE, f"'abstract': |\n  Decoy 9.99.\n{CLOSE}"
    ),
    "explicit key repeated after": PAPER.replace(
        CLOSE, f"? abstract\n: |\n  Decoy 9.99.\n{CLOSE}"
    ),
    "plain key repeated after": PAPER.replace(CLOSE, f"abstract: |\n  Decoy 9.99.\n{CLOSE}"),
    "key line with a comment": PAPER.replace("abstract: |\n", "abstract: | # note\n"),
    "folded key": PAPER.replace("abstract: |\n", "abstract: >\n"),
    "metadata block in the body": with_body("---\nabstract: |\n  Body copy 9.99.\n---\n"),
    "metadata block in a list item": with_body(
        "- item\n\n  ---\n  abstract: |\n    Body copy 9.99.\n  ---\n"
    ),
    "metadata block in a block quote": with_body(
        "> ---\n> abstract: |\n>   Body copy 9.99.\n> ---\n"
    ),
    "metadata block right after the front matter": PAPER.replace(
        CLOSE, f"---\n---\nabstract: |\n  Body copy 9.99.\n{CLOSE}"
    ),
    "metadata block that sets another key": with_body("---\nnote: |\n  Body copy 9.99.\n---\n"),
    "flow mapping in the body": with_body("---\n{abstract: Body copy 9.99.}\n---\n"),
    "flow key after a comma in the body": with_body(
        '---\n{title: X, "abstract": Body copy 9.99.}\n---\n'
    ),
    "nested flow key in the body": with_body("---\n{meta: {abstract: Body copy 9.99.}}\n---\n"),
    "nested flow key in the front matter": NESTED_FLOW_KEY,
    "format-level key in the front matter": FORMAT_LEVEL_KEY,
    "tagged format-level key": PAPER.replace(
        "format:\n", "format:\n  html:\n    !!str abstract: |\n      Format copy 9.99.\n"
    ),
    "anchored format-level key": PAPER.replace(
        "format:\n", "format:\n  html:\n    &k abstract: |\n      Format copy 9.99.\n"
    ),
    "aliased format-level key": PAPER.replace(
        "format:\n", "names: [&k abstract]\nformat:\n  html:\n    *k : Format copy 9.99.\n"
    ),
    "escaped format-level key": PAPER.replace(
        "format:\n", 'format:\n  html:\n    "\\x61bstract": Format copy 9.99.\n'
    ),
    "explicit format-level key in a block": PAPER.replace(
        "format:\n", "format:\n  html:\n    ? |-\n      abstract\n    : Format copy 9.99.\n"
    ),
    "explicit key with a comment in the body": with_body(
        "---\n? abstract # set here\n: Body copy 9.99.\n---\n"
    ),
    "escaped quoted key in the body": with_body('---\n"\\x61bstract": Body copy 9.99.\n---\n'),
    "anchored explicit key in the body": with_body("---\n? &k abstract\n: Body copy 9.99.\n---\n"),
    "empty block, then a field": PAPER.replace("abstract: |\n", "abstract: |\nnote: |\n"),
    "HTML comment inside the block": with_lines("  First line, <!-- 9.99 percent --> second.\n"),
    "HTML comment line inside the block": with_lines(ABSTRACT_LINES + "  <!-- 9.99 percent -->\n"),
    "HTML comment inside a word": with_lines("  Fir<!-- 9.99 -->st line.\n"),
    "two thematic breaks in the body": with_body("---\n\nText between two breaks.\n\n---\n"),
    "no-break space on the first line": with_lines("   \u00a0\n    Four 1.11,\n   three 9.99.\n"),
    "key line outside any metadata block": with_body("abstract: |\n  Body copy 9.99.\n"),
    "metadata block in a code fence": with_body(
        "```yaml\n---\nabstract: |\n  Body copy 9.99.\n---\n```\n"
    ),
    "byte order mark": "\ufeff" + PAPER,
    "emphasis in a quoted subtitle": PAPER.replace(
        'title: "Thresholds"\n', 'title: "Thresholds"\nsubtitle: "Public data, *rolling* forecasts"\n'
    ),
    "anchored value under format": PAPER.replace("format:\n", "format:\n  html:\n    toc: &on true\n"),
    "comment in a code span": with_lines("  First line, `<!-- 9.99 percent -->` second.\n"),
    "unopened comment": with_lines("  First line, <!--> 9.99 percent --> second.\n"),
    "comment glued to a key after the block": PAPER.replace(
        ABSTRACT_LINES, ABSTRACT_LINES + '<!-- -->abstract: "Hidden copy 9.99."\n'
    ),
    "code fence inside the block": with_lines("  First line,\n  ```\n  9.99 percent\n  ```\n  second.\n"),
    "quoted title wrapped over two lines": PAPER.replace(
        'title: "Thresholds"\n', 'title: "Thresholds for\n  the SPM"\n'
    ),
    "quote open over the key line": PAPER.replace(
        "abstract: |\n", '  html:\n    pagetitle: "x\nabstract: |\n'
    ).replace(ABSTRACT_LINES, ABSTRACT_LINES.rstrip("\n") + '"\n    abstract: "Format copy 9.99."\n'),
    "quote open over another block's opener": PAPER.replace(
        "format:\n",
        'format:\n  html:\n    pagetitle: "x\n  include-in-header: |\n    y"\n    abstract: "Format copy 9.99."\n',
    ),
    # Round 7's counterexamples: an apostrophe or a quote in a plain value,
    # which YAML reads as text, before a key that a tag, anchor, flow list
    # or explicit block key hides from a quote-tracking parser.
    "tagged key after an apostrophe": PAPER.replace(
        "format:\n",
        "subtitle: Rents in the 1980s, '90s and 2000s\nformat:\n  html:\n    !!str abstract: Hidden 9.99.\n",
    ),
    "tagged key after a stray double quote": PAPER.replace(
        "format:\n",
        'thanks: PolicyEngine, "a think tank\nformat:\n  html:\n    !!str abstract: Hidden 9.99.\n',
    ),
    "flow list as a key after an apostrophe": PAPER.replace(
        "format:\n",
        "subtitle: Rents in the 1980s, '90s and 2000s\nformat:\n  html:\n    [abstract]: Hidden 9.99.\n",
    ),
    "anchored key after an apostrophe": PAPER.replace(
        "format:\n",
        "subtitle: Rents in the 1980s, '90s and 2000s\nformat:\n  html:\n    &k abstract: Hidden 9.99.\n",
    ),
    "explicit block key after an apostrophe": PAPER.replace(
        "format:\n",
        "subtitle: Rents in the 1980s, '90s and 2000s\nformat:\n  html:\n"
        "    ? |-\n      abstract\n    : Hidden 9.99.\n",
    ),
    "anchored quote over a block opener": PAPER.replace(
        "format:\n",
        'format:\n  html:\n    pagetitle: &p "x\n   y: |\n     z"\n    abstract: Hidden 9.99.\n',
    ),
    "anchored quote over the key line": PAPER.replace(
        "abstract: |\n", '  html:\n    pagetitle: &p "x\nabstract: |\n'
    ).replace(ABSTRACT_LINES, ABSTRACT_LINES.rstrip("\n") + '"\n    abstract: Hidden 9.99.\n'),
    "carriage returns around a body metadata block": PAPER.replace(
        "Body text.\n", "Body text.\r\r---\rabstract: Body copy 9.99.\r---\r\rMore.\n"
    ),
    "key after a sibling block in a sequence entry": PAPER.replace(
        "format:\n", "notes:\n  - text: |\n      Note.\n    abstract: Hidden 9.99.\nformat:\n"
    ),
    "key line ending in a comment inside a sequence block": PAPER.replace(
        "format:\n", "notes:\n  - text: | # note\n      abstract: not a key\n    other: value\nformat:\n"
    ),
    "block indicator with an indentation digit": PAPER.replace(
        "format:\n", "note: |2\n    Indented note.\nformat:\n"
    ),
    "flow list over two lines": PAPER.replace(
        "format:\n", 'keywords: [poverty,\n  "SPM thresholds"]\nformat:\n'
    ),
    "flow mapping as a value": PAPER.replace(
        "format:\n", 'affiliation: {name: PolicyEngine, city: "Washington"}\nformat:\n'
    ),
    "abstract with strip chomping": PAPER.replace("abstract: |\n", "abstract: |-\n"),
    "raw TeX in the abstract": with_lines("  First \\phantom{9.99 percent} second.\n"),
    "div fence in the abstract": with_lines("  First line,\n  ::: {.hidden}\n  9.99 percent\n  :::\n  second.\n"),
    "grid table holding a metadata block": with_body(
        "+--------------------------+\n"
        "| ---                      |\n"
        "| abstract: Grid copy 9.99.|\n"
        "| ---                      |\n"
        "+--------------------------+\n"
    ),
    "grid table of text": with_body("+------+------+\n| Cell | Cell |\n+======+======+\n| 1.11 | 2.22 |\n+------+------+\n"),
    "one-column pipe table": with_body("| Column |\n|--------|\n| 9.99   |\n"),
    "thematic break, then a line, then dots": with_body("---\nText.\n\n...\n"),
    "blank line inside another block": PAPER.replace(
        "        \\usepackage{needspace}\n", "        \\usepackage{needspace}\n\n        \\usepackage{xcolor}\n"
    ),
    "tagged value in a sequence": PAPER.replace("format:\n", "css:\n  - !!str style.css\nformat:\n"),
    "aliased value": PAPER.replace("format:\n", "toc-title: &t Contents\nlof-title: *t\nformat:\n"),
    "quoted flow list with an escape": PAPER.replace(
        "format:\n", 'keywords: ["SPM", "Line\\nbreak"]\nformat:\n'
    ),
    "emphasis continuing a plain value": PAPER.replace(
        "format:\n", "subtitle: Public consumption data,\n  *rolling* forecasts\nformat:\n"
    ),
    "HTML comment inside another block": PAPER.replace(
        "        \\usepackage{needspace}\n", "        \\usepackage{needspace}\n        <!-- note -->\n"
    ),
    "comment between a plain value and a deeper line": PAPER.replace(
        "format:\n", "subtitle: Public data\n# note\n  continued\nformat:\n"
    ),
    "unindented line after a plain value": PAPER.replace(
        "format:\n", "subtitle: Public data\ncontinued\nformat:\n"
    ),
    "div without braces in the abstract": with_lines(
        "  First line,\n  ::: hidden\n  9.99 percent\n  :::\n  second.\n"
    ),
    # Quarto deletes HTML comments before it looks for metadata blocks, so
    # a comment glued to each fence leaves "---" lines that Quarto reads.
    "escaped key between fences glued to comments": with_body(
        '<!-- -->---\n"\\x61bstract": Body copy 9.99.\n<!-- -->---\n'
    ),
    # Quarto deletes from a comment opener in an indented code block to the
    # next closer, while pandoc reads the metadata block between them.
    "metadata block after a comment opener in code": with_body(
        '    <!--\n\n---\n"\\x61bstract": Body copy 9.99.\n---\n\n<!-- -->\n'
    ),
    "escaped key's metadata block in a grid table": with_body(
        "+--------------------------------+\n"
        "| ---                            |\n"
        '| "\\x61bstract": Grid copy 9.99. |\n'
        "| ---                            |\n"
        "+--------------------------------+\n"
    ),
    "escaped key's metadata block in a list item": with_body(
        '- ---\n  "\\x61bstract": List copy 9.99.\n  ---\n'
    ),
    "escaped key's metadata block closed by dots": with_body(
        '---\n"\\x61bstract": Body copy 9.99.\n...\n'
    ),
    "text after a quote closes on a later line": PAPER.replace(
        'title: "Thresholds"\n', 'title: "Thresholds\n  for the SPM" extra\n'
    ),
    "double-quoted line ending in a backslash": PAPER.replace(
        'title: "Thresholds"\n', 'title: "Thresholds \\\n  for the SPM"\n'
    ),
    "flow list with a colon item": PAPER.replace("format:\n", "keywords: [a: b]\nformat:\n"),
    "flow list holding a flow mapping": PAPER.replace("format:\n", "keywords: [{a: b}]\nformat:\n"),
    "flow list holding braces": PAPER.replace("format:\n", "keywords: [{a}]\nformat:\n"),
    "nested sequence block with shallow text": PAPER.replace(
        "format:\n", "notes:\n- - |\n  shallow\nformat:\n"
    ),
    "bullet opening a paragraph": with_lines("  First line.\n\n  - 9.99 percent.\n"),
    "bullet after an indented code block": with_lines("  First line.\n\n      code\n  - 9.99 percent.\n"),
    "ordered marker opening the block": with_lines("  2025. The rate was 9.99 percent.\n"),
    "setext underline in the block": with_lines("  9.99 percent\n  ---\n"),
    "definition in the block": with_lines("  First line\n  : 9.99 percent\n"),
    "bullet and number mid-paragraph": with_lines(
        "  First line, then\n  - 9.99 percent and\n  + 1.00 and\n  2025. was 9.99.\n"
    ),
    "signed figures opening paragraphs": with_lines("  +1.04 points.\n\n  -0.63 points and \u22120.63.\n"),
    "en dash line and inner colon": with_lines("  Rates: 9.99\n  \u2013\u2013\n  :not a marker.\n"),
    "plain value on the line after its key": PAPER.replace("abstract: |\n", "note:\n  plain words\nabstract: |\n"),
    "quote continuing a plain value": PAPER.replace(ABSTRACT_LINES, ABSTRACT_LINES + 'note: a\n  "b" c\n'),
    "quote on the line after its key, over the key line": PAPER.replace(
        "abstract: |\n", 'note:\n  "x\nabstract: |\n'
    ).replace(ABSTRACT_LINES, ABSTRACT_LINES + 'other: "\nabstract: Hidden 9.99.\nend: x "\n'),
    "block indicator on the line after its key": PAPER.replace(
        ABSTRACT_LINES, ABSTRACT_LINES + 'note:\n  |\n  sub: "x\nabstract: Hidden 9.99.\nend: y "\n'
    ),
    "dash and quote continuing a plain value": PAPER.replace(
        ABSTRACT_LINES, ABSTRACT_LINES + 'note: foo\n  - "q\nabstract: Hidden 9.99.\nend: y "\n'
    ),
    "body opener after an HTML tag": with_body('<div>---\n"\\x61bstract": Body copy 9.99.\n---\n</div>\n'),
    "body opener before a YAML comment": with_body('---\n#. >\n"\\x61bstract": Body copy 9.99.\n---\n'),
    "rule tag before a blank line": with_body("<hr>---\n\nText after a rule.\n\n---\n"),
    "no-break space line before a code block": with_lines(
        "  \xa0\n\n      The blend yields 1.17 percent in\n   2025. The next sentence.\n"
    ),
}

# The edge cases from which the parser reads an abstract; it fails closed on
# every other one. A "#" or a form feed in the abstract fails it as text
# that is not plain prose, and a Unicode line separator anywhere fails the
# file.
EDGE_CASES_READ = frozenset(
    (
        "Windows line endings",
        "anchored value under format",
        "blank line, then a comment at indent 1",
        "closing dashes with trailing spaces",
        "closing dots",
        "comment at indent 0 after the block",
        "comment at indent 1 after the block",
        "comment at indent 3 after a 4-space block",
        "emphasis in a quoted subtitle",
        "fixture",
        "leading blank line deeper than the text",
        "line indented more than the first",
        "no-break space on the first line",
        "quoted title wrapped over two lines",
        "tab after a deeper line's indentation",
        "tab after the block's indentation",
        "tab after the first line's indentation",
        "tab line inside the block",
        "tab line, then a comment at indent 1",
        "two thematic breaks in the body",
        "key line ending in a comment inside a sequence block",
        "one-column pipe table",
        "blank line inside another block",
        "tagged value in a sequence",
        "aliased value",
        "quoted flow list with an escape",
        "emphasis continuing a plain value",
        "double-quoted line ending in a backslash",
        "bullet and number mid-paragraph",
        "signed figures opening paragraphs",
        "en dash line and inner colon",
        "plain value on the line after its key",
        "quote continuing a plain value",
        "rule tag before a blank line",
    )
)


@unittest.skipUnless(PANDOC, "pandoc is not installed")
class PandocAgreementTests(unittest.TestCase):
    """Wherever the parser reads an abstract, pandoc renders the same words,
    or rejects the document, which then cannot render at all."""

    ROUNDS = 100

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.template = Path(cls.directory.name) / "abstract.txt"
        cls.template.write_text("$abstract$\n")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def rendered(self, text):
        """The words pandoc renders as the abstract, or None when pandoc
        rejects the document. pandoc writes HTML here, since its plain writer
        would write a list's markers back as text, and the abstract may render
        only as paragraphs, line breaks or code, which keep its words."""
        result = subprocess.run(
            [PANDOC, "--from=markdown", "--to=html", f"--template={self.template}"],
            input=text.encode(),
            capture_output=True,
            check=False,
        )
        if result.returncode:
            return None
        rendered = result.stdout.decode()
        tags = set(re.findall(r"</?([A-Za-z][A-Za-z0-9]*)", rendered))
        self.assertLessEqual(tags, {"p", "br", "pre", "code"}, rendered)
        return words(html.unescape(re.sub(r"<[^>]*>", " ", rendered)))

    def agrees(self, text):
        """Whether the parser read an abstract that pandoc renders, after
        asserting that pandoc renders the parser's words."""
        ours = block_words(text, "abstract")
        if ours is None:
            return False
        rendered = self.rendered(text)
        if rendered is None:
            return False
        self.assertEqual(words(ours), rendered, text)
        return True

    def test_pandoc_renders_the_fixture(self):
        self.assertEqual(self.rendered(PAPER), words(ABSTRACT_LINES))

    def test_edge_cases(self):
        for name, text in EDGE_CASES.items():
            with self.subTest(case=name):
                self.agrees(text)

    def test_random_documents(self):
        """Every random document with decoys outside its abstract parses,
        renders and agrees."""
        rng = random.Random(20261114)
        agreed = 0
        for _ in range(self.ROUNDS):
            value = random_number(rng)
            statement = f"we obtain {value} percent with the Consumer Price Index"
            fields, terminator, body, _ = random_document(rng, statement)
            add_decoys(rng, fields, body)
            agreed += self.agrees(render(fields, terminator, body))
        self.assertEqual(agreed, self.ROUNDS)


QUARTO = shutil.which("quarto")


class QuartoAbstract(html.parser.HTMLParser):
    """Collects the text of the first ``<div class="abstract">`` on a page
    that Quarto renders, less the block title Quarto sets above it."""

    VOID = frozenset(
        ("area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr")
    )

    def __init__(self):
        super().__init__()
        self.found = False
        self.depth = 0
        self.title_depth = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID or (self.found and not self.depth):
            return
        classes = (dict(attrs).get("class") or "").split()
        if self.depth:
            self.depth += 1
            if self.title_depth is None and "block-title" in classes:
                self.title_depth = self.depth
        elif tag == "div" and "abstract" in classes:
            self.found = True
            self.depth = 1

    def handle_endtag(self, tag):
        if tag in self.VOID or not self.depth:
            return
        if self.depth == self.title_depth:
            self.title_depth = None
        self.depth -= 1

    def handle_data(self, data):
        if self.depth and self.title_depth is None:
            self.parts.append(data)


def renderable(fields):
    """Edit a random document's fields into ones Quarto accepts: it rejects a
    line holding only a tab and a list under ``notes``."""
    for field in fields:
        field[:] = ["" if line == "\t" else line for line in field]
        if field[0] == "notes:":
            field[0] = "remarks:"


@unittest.skipUnless(QUARTO, "quarto is not installed")
class QuartoAgreementTests(unittest.TestCase):
    """Wherever the parser reads an abstract, the page Quarto renders shows
    the same words as its abstract, or Quarto rejects the document, which
    then cannot render at all."""

    ROUNDS = 12
    JOBS = 4

    def rendered(self, text):
        """The words of the abstract on the page Quarto renders, "" when the
        page has none, or None when Quarto rejects the document."""
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "doc.qmd").write_bytes(text.encode())
            result = subprocess.run(
                [QUARTO, "render", "doc.qmd", "--to", "html"],
                cwd=folder,
                capture_output=True,
                check=False,
                timeout=600,
            )
            page = folder / "doc.html"
            if result.returncode or not page.exists():
                return None
            reader = QuartoAbstract()
            reader.feed(page.read_text())
        return words(" ".join(reader.parts))

    def compare(self, documents):
        """The parser's words and Quarto's for each document the parser
        reads an abstract from, rendering JOBS documents at a time."""
        parsed = {}
        for name, text in documents.items():
            ours = block_words(text, "abstract")
            if ours is not None:
                parsed[name] = words(ours)
        with concurrent.futures.ThreadPoolExecutor(self.JOBS) as pool:
            rendered = pool.map(lambda name: self.rendered(documents[name]), parsed)
            return {name: (ours, theirs) for (name, ours), theirs in zip(parsed.items(), rendered)}

    def test_quarto_renders_the_fixture(self):
        self.assertEqual(self.rendered(PAPER), words(ABSTRACT_LINES))

    def test_edge_cases(self):
        for name, (ours, theirs) in self.compare(EDGE_CASES).items():
            with self.subTest(case=name):
                if theirs is not None:
                    self.assertEqual(ours, theirs)

    def test_random_documents(self):
        """Random documents with decoys outside the abstract, edited into
        ones Quarto accepts and closed with ``---``, all parse, render and
        agree."""
        rng = random.Random(20261116)
        documents = {}
        for round_number in range(self.ROUNDS):
            value = random_number(rng)
            statement = f"we obtain {value} percent with the Consumer Price Index"
            fields, _, body, _ = random_document(rng, statement)
            add_decoys(rng, fields, body)
            renderable(fields)
            documents[round_number] = render(fields, "---", body)
        compared = self.compare(documents)
        self.assertEqual(len(compared), self.ROUNDS)
        for round_number, (ours, theirs) in compared.items():
            with self.subTest(round=round_number):
                self.assertEqual(ours, theirs)


if __name__ == "__main__":
    unittest.main()
