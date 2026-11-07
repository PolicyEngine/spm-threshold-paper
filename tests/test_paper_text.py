"""Tests for scripts/paper_text.py, the helpers through which the paper guard
reads the front matter's abstract and the rates the abstract states.

The unit cases pin each rule of the block parser and the slot reader. The
seeded property tests build random front matter and rate statements, then check
that the abstract's words round-trip, that text outside the block never changes
what the guard reads, and that each value reads as its whole numeric token.
"""

import importlib.util
import random
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
            "abstract:",
            "abstract:|",
            "abstract : |",
            "abstract:  |",
        ):
            with self.subTest(line=line):
                text = PAPER.replace("abstract: |\n", f"{line}\n")
                self.assertIsNone(block_scalar_span(text, "abstract"))

    def test_a_repeated_top_level_key_fails_closed(self):
        for repeat in (
            f"abstract: |\n{ABSTRACT_LINES}",
            "abstract: A second abstract\n",
            "abstract:\n  - a list\n",
        ):
            before = PAPER.replace('title: "Thresholds"\n', f'title: "Thresholds"\n{repeat}')
            after = PAPER.replace("---\n# Introduction", f"{repeat}---\n# Introduction")
            for where, text in (("before", before), ("after", after)):
                with self.subTest(repeat=repeat, where=where):
                    self.assertIsNone(block_scalar_span(text, "abstract"))

    def test_keys_that_share_the_prefix_do_not_count(self):
        extra = 'abstract-title: "Summary"\nabstracts: |\n  Another block.\n'
        text = PAPER.replace('title: "Thresholds"\n', f'title: "Thresholds"\n{extra}')
        self.assertEqual(block_lines(text), ABSTRACT_LINES)

    def test_indented_keys_belong_to_other_mappings(self):
        nested = PAPER.replace(
            "      text: |\n", "      abstract: |\n        Nested copy.\n      text: |\n"
        )
        self.assertEqual(block_lines(nested), ABSTRACT_LINES)
        self.assertIsNone(block_scalar_span(PAPER, "text"))
        only_nested = nested.replace(f"abstract: |\n{ABSTRACT_LINES}", "")
        self.assertIsNone(block_scalar_span(only_nested, "abstract"))

    def test_a_key_in_the_body_lies_outside_the_front_matter(self):
        text = PAPER.replace("abstract: |\n", "summary: |\n").replace(
            "Body text.\n", f"Body text.\n\nabstract: |\n{ABSTRACT_LINES}"
        )
        self.assertIsNone(block_scalar_span(text, "abstract"))

    def test_the_block_ends_at_the_next_top_level_field(self):
        text = PAPER.replace(
            "---\n# Introduction", 'note: "2.29 percent"\n---\n# Introduction'
        )
        self.assertEqual(block_lines(text), ABSTRACT_LINES)

    def test_blank_lines_stay_inside_the_block(self):
        text = PAPER.replace(ABSTRACT_LINES, f"{ABSTRACT_LINES}\n  A second paragraph.\n")
        self.assertEqual(
            block_text(text),
            "First line of the abstract, then its second line. A second paragraph.",
        )

    def test_dots_also_close_the_front_matter(self):
        text = PAPER.replace("---\n# Introduction", "...\n# Introduction")
        self.assertEqual(block_lines(text), ABSTRACT_LINES)

    def test_missing_or_unterminated_front_matter_fails_closed(self):
        cases = {
            "unterminated": PAPER.replace("---\n# Introduction", "# Introduction"),
            "no opening delimiter": PAPER.removeprefix("---\n"),
            "text before the delimiter": "Preface.\n" + PAPER,
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
    words. `statement` lands at a random place in the abstract."""
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
            block.append("")
        block.extend(
            indent + line
            for line in textwrap.wrap(
                " ".join(words), width, break_long_words=False, break_on_hyphens=False
            )
        )
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
    body = ["# Introduction", "", "abstract: |", "  Body copy 9.99.", ""]
    abstract = " ".join(word for words in paragraphs for word in words)
    return fields, rng.choice(("---", "...")), body, abstract


def render(fields, terminator, body):
    lines = ["---", *(line for field in fields for line in field), terminator, *body]
    return "\n".join(lines) + "\n"


def add_decoys(rng, fields, body):
    """Restate a rate as another top-level field and in the body."""
    decoy_fields = (
        [f'note: "{DECOY_STATEMENT}"'],
        ["notes:", f"  - {DECOY_STATEMENT}"],
        ["abstract-note: |", f"  {DECOY_STATEMENT}"],
    )
    fields.insert(rng.randint(0, len(fields)), list(rng.choice(decoy_fields)))
    at = rng.randint(0, len(body))
    body[at:at] = [DECOY_STATEMENT, "abstract: |", f"  {DECOY_STATEMENT}"]


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
                second = rng.choice((["abstract: |", "  Copy."], ["abstract: Copy."]))
                fields.insert(rng.randint(0, len(fields)), list(second))
            else:
                index = next(
                    i for i, field in enumerate(fields) if field[0] == "abstract: |"
                )
                restyled = rng.choice(
                    ("abstract: >", "abstract: |-", "abstract:", "abstract : |")
                )
                fields[index] = [restyled, *fields[index][1:]]
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


if __name__ == "__main__":
    unittest.main()
