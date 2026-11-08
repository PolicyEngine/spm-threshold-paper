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
        ):
            before = PAPER.replace('title: "Thresholds"\n', f'title: "Thresholds"\n{repeat}')
            after = PAPER.replace(CLOSE, f"{repeat}{CLOSE}")
            for where, text in (("before", before), ("after", after)):
                with self.subTest(repeat=repeat, where=where):
                    self.assertIsNone(block_scalar_span(text, "abstract"))

    def test_keys_that_share_the_prefix_do_not_count(self):
        extra = (
            'abstract-title: "Summary"\nabstracts: |\n  Another block.\n'
            '"abstract-note": Another field.\n'
        )
        text = PAPER.replace('title: "Thresholds"\n', f'title: "Thresholds"\n{extra}')
        self.assertEqual(block_lines(text), ABSTRACT_LINES)

    def test_nested_keys_belong_to_other_mappings(self):
        nested = PAPER.replace(
            "      text: |\n", "      abstract: |\n        Nested copy.\n      text: |\n"
        )
        self.assertEqual(block_lines(nested), ABSTRACT_LINES)
        self.assertEqual(block_lines(NESTED_FLOW_KEY), ABSTRACT_LINES)
        self.assertIsNone(block_scalar_span(PAPER, "text"))
        only_nested = nested.replace(f"abstract: |\n{ABSTRACT_LINES}", "")
        self.assertIsNone(block_scalar_span(only_nested, "abstract"))

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
            "bare key line": "abstract: Body copy.\n",
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
        ):
            with self.subTest(line=line):
                self.assertEqual(block_lines(with_body(line)), ABSTRACT_LINES)

    def test_the_block_ends_at_the_next_top_level_field(self):
        text = PAPER.replace(CLOSE, f'note: "2.29 percent"\n{CLOSE}')
        self.assertEqual(block_lines(text), ABSTRACT_LINES)

    def test_the_first_line_with_text_sets_the_indentation(self):
        deeper = "  First line,\n    a deeper line,\n  and a third.\n"
        self.assertEqual(block_lines(with_lines(deeper)), deeper)
        shallower = "    Four spaces,\n  then two.\n"
        self.assertEqual(block_lines(with_lines(shallower)), "    Four spaces,\n")
        leading_blank = "\n" + ABSTRACT_LINES
        self.assertEqual(block_lines(with_lines(leading_blank)), leading_blank)

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

    def test_windows_line_endings_keep_the_span_exact(self):
        text = PAPER.replace("\n", "\r\n")
        self.assertEqual(block_lines(text), ABSTRACT_LINES.replace("\n", "\r\n"))

    def test_a_lone_carriage_return_in_the_front_matter_fails_closed(self):
        """pandoc drops a carriage return that no line feed follows, so the
        parser fails closed rather than guess how the line reads."""
        for name, text in {
            "every line": PAPER.replace("\n", "\r"),
            "inside the abstract": with_lines("  First line\rof the abstract.\n"),
            "inside the title": PAPER.replace('"Thresholds"', '"Thresh\rolds"'),
        }.items():
            with self.subTest(case=name):
                self.assertIsNone(block_scalar_span(text, "abstract"))
        body = PAPER.replace("Body text.\n", "Body\rtext.\n")
        self.assertEqual(block_lines(body), ABSTRACT_LINES)

    def test_only_line_feeds_end_lines(self):
        """A form feed or Unicode line separator stays inside its line, so it
        cannot end the block early."""
        for separator in ("\u2028", "\u2029", "\x85", "\x0c", "\x0b"):
            with self.subTest(separator=repr(separator)):
                lines = f"  First line,{separator}then more.\n  Second line.\n"
                self.assertEqual(block_lines(with_lines(lines)), lines)

    def test_the_key_matches_literally(self):
        text = PAPER.replace("abstract: |\n", "abXtract: |\n")
        self.assertIsNone(block_scalar_span(text, "ab.tract"))
        dotted = PAPER.replace("abstract: |\n", "ab.tract: |\n")
        self.assertEqual(block_lines(dotted, "ab.tract"), ABSTRACT_LINES)
        lookalike = dotted.replace(
            'title: "Thresholds"\n', 'title: "Thresholds"\nabXtract: Other\n'
        )
        self.assertEqual(block_lines(lookalike, "ab.tract"), ABSTRACT_LINES)


class StatedValuesTests(unittest.TestCase):
    def test_reads_the_value_in_the_slot(self):
        text = "we obtain 2.29 percent with the Consumer Price Index for All Urban"
        self.assertEqual(stated_values(CPI_U, text), ["2.29"])

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
# and tabs near the block, odd line endings, repeated keys, flow-style keys
# and metadata blocks in the body.
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
    "key line outside any metadata block": with_body("abstract: |\n  Body copy 9.99.\n"),
    "metadata block in a code fence": with_body(
        "```yaml\n---\nabstract: |\n  Body copy 9.99.\n---\n```\n"
    ),
    "byte order mark": "\ufeff" + PAPER,
}


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
        rejects the document."""
        result = subprocess.run(
            [PANDOC, "--from=markdown", "--to=plain", f"--template={self.template}"],
            input=text.encode(),
            capture_output=True,
            check=False,
        )
        return None if result.returncode else words(result.stdout.decode())

    def agrees(self, text):
        """Whether the parser read an abstract that pandoc renders, after
        asserting that pandoc renders the parser's words."""
        span = block_scalar_span(text, "abstract")
        if span is None:
            return False
        rendered = self.rendered(text)
        if rendered is None:
            return False
        self.assertEqual(words(text[span[0] : span[1]]), rendered, text)
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
            span = block_scalar_span(text, "abstract")
            if span is not None:
                parsed[name] = words(text[span[0] : span[1]])
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
