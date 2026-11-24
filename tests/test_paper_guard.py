"""Mutation tests run the real guard in independent temporary Git clones."""

import ast
import builtins
import hashlib
import importlib.util
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_paper_text():
    """The guard's own text helpers, so fixtures edit the text the guard reads."""
    spec = importlib.util.spec_from_file_location(
        "paper_guard_text", REPO / "scripts/paper_text.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PAPER_TEXT = load_paper_text()
ROLLING_NAME = "rolling_forecast_2026_09_09.json"
DISCUSSION_HEADING = "# Discussion {#sec-discussion}\n"
ROLLING_CE_HEADING = "## Projecting expenditure records and rolling windows\n"
ROLLING_ACS_HEADING = "## Projecting local relative housing costs\n"

# Each case drifts one sealed rolling figure in its own subsection. The
# third element is the same figure restated correctly somewhere else in the
# paper, so a pin that searched the whole document would still pass.
ROLLING_PROSE_MUTATIONS = (
    (
        "applied compounded rate",
        (("real growth of 0.914 percent", "real growth of 0.924 percent"),),
        DISCUSSION_HEADING,
        "We report rates as compounded annual equivalents, $\\exp(r)-1$, not as "
        "the log rate $r$ that enters the multiplier. The applied annual "
        "real-growth rate is 0.914 percent, from an applied log rate of "
        "0.910 percent.",
        "rolling applied real-growth rate",
    ),
    (
        "applied log rate",
        ((" of 0.910\npercent", " of 0.911\npercent"),),
        ROLLING_ACS_HEADING,
        "The applied annual real-growth rate is 0.914 percent, from an applied "
        "log rate of 0.910 percent.",
        "rolling applied real-growth rate",
    ),
    (
        "dropped log-rate clause",
        ((", from an applied log rate of 0.910\npercent", ""),),
        DISCUSSION_HEADING,
        "The applied annual real-growth rate is 0.914 percent, from an applied "
        "log rate of 0.910 percent.",
        "rolling applied real-growth rate",
    ),
    (
        "dropped compounding convention",
        (("compounded annual equivalents", "annual equivalents"),),
        DISCUSSION_HEADING,
        "We report rates as compounded annual equivalents.",
        "rolling applied real-growth rate",
    ),
    (
        "swapped sensitivities",
        (
            ("0.817 percent", "PLACEHOLDER"),
            ("−0.135 percent", "0.817 percent"),
            ("PLACEHOLDER", "−0.135 percent"),
        ),
        DISCUSSION_HEADING,
        "Using ten annual blocks gives 0.817 percent; excluding the two blocks "
        "ending in 2021 and 2022 from the five-block fit leaves three blocks "
        "and gives −0.135 percent.",
        "rolling real-growth sensitivities",
    ),
    (
        "ten-block sensitivity count",
        (("Using ten annual", "Using nine annual"),),
        DISCUSSION_HEADING,
        "Using ten annual blocks gives 0.817 percent.",
        "rolling real-growth sensitivities",
    ),
    (
        "pandemic-excluded block count",
        (("leaves three\nblocks", "leaves four\nblocks"),),
        DISCUSSION_HEADING,
        "The five-block fit leaves three blocks and gives −0.135 percent.",
        "rolling real-growth sensitivities",
    ),
    (
        "excluded block years",
        (("in 2021 and 2022 from", "in 2020 and 2022 from"),),
        DISCUSSION_HEADING,
        "Excluding the two blocks ending in 2021 and 2022 from the five-block fit.",
        "rolling real-growth sensitivities",
    ),
    (
        "fitted block count",
        (("five nonoverlapping", "six nonoverlapping"),),
        DISCUSSION_HEADING,
        "We construct five nonoverlapping annual collection blocks ending in "
        "2021–2025.",
        "rolling fit uses 5 blocks",
    ),
    (
        "fitted block window",
        (("ending in 2021–2025", "ending in 2020–2025"),),
        DISCUSSION_HEADING,
        "We construct five nonoverlapping annual collection blocks ending in "
        "2021–2025.",
        "rolling fit uses 5 blocks",
    ),
    (
        "declared shrinkage",
        (("the 0.5\nshrinkage", "the 0.6\nshrinkage"),),
        DISCUSSION_HEADING,
        "The applied slope is half that estimate; the 0.5 shrinkage was "
        "declared in advance.",
        "rolling applied slope is the declared 0.5",
    ),
    (
        "swapped area menus",
        (
            ("342 published and seven modeled areas in\n2022", "PLACEHOLDER"),
            (
                "341 published and eight modeled areas from 2023",
                "342 published and seven modeled areas in\n2022",
            ),
            ("PLACEHOLDER", "341 published and eight modeled areas from 2023"),
        ),
        DISCUSSION_HEADING,
        "The menu contains 342 published and seven modeled areas in 2022, and "
        "341 published and eight modeled areas from 2023.",
        "rolling area menu prose",
    ),
    (
        "published area menu",
        (("342 published", "343 published"),),
        DISCUSSION_HEADING,
        "The menu contains 342 published and seven modeled areas in 2022.",
        "rolling area menu prose",
    ),
    (
        "modeled area menu",
        (("and seven modeled", "and eight modeled"),),
        ROLLING_CE_HEADING,
        "The menu contains 342 published and seven modeled areas in 2022, and "
        "341 published and eight modeled areas from 2023.",
        "rolling area menu prose",
    ),
    (
        "area menu year",
        (("modeled areas from 2023", "modeled areas from 2024"),),
        DISCUSSION_HEADING,
        "The menu holds 341 published and eight modeled areas from 2023.",
        "rolling area menu prose",
    ),
    (
        "validation area count",
        (("covers 341 areas", "covers 340 areas"),),
        DISCUSSION_HEADING,
        "The 2023-origin, 2024-target geographic comparison covers 341 areas "
        "with published anchors.",
        "rolling geographic validation covers 341",
    ),
    (
        "validation horizon",
        (("The 2023-origin, 2024-target", "The 2022-origin, 2024-target"),),
        DISCUSSION_HEADING,
        "The 2023-origin, 2024-target geographic comparison covers 341 areas.",
        "rolling geographic validation covers 341",
    ),
    (
        "stabilization year",
        (("occurs in 2029", "occurs in 2030"),),
        ROLLING_CE_HEADING,
        "The relative indices stabilize under this assumption. In this "
        "snapshot that occurs in 2029.",
        "relative rent indices first constant in 2029",
    ),
    (
        "thin-donor support count",
        (("31 areas carry thin-donor", "13 areas carry thin-donor"),),
        DISCUSSION_HEADING,
        "Support narrows: 31 areas carry thin-donor warnings in projected years.",
        "rolling thin-donor warnings cover 31",
    ),
)


INKIND_HEADING = "# Home internet and in-kind benefits {#sec-inkind}\n"
PROJECTION_HEADING = "# Projecting thresholds {#sec-projection}\n"
INKIND_NAMES = (
    "ce_inkind_bls_components_2019_2025.json",
    "ce_inkind_replication_2019_2025.json",
    "ce_replicate_uncertainty_2019_2025.json",
    "provenance.json",
)
# The calculator commit the provenance record names for each receipt. The
# fixtures that edit a named commit read it here, so they follow a repin of
# the receipts rather than a literal.
INKIND_COMMITS = {
    Path(path).name: record["calculator_commit"]
    for path, record in json.loads((REPO / "data/inkind/provenance.json").read_text())["artifacts"].items()
}


def last_digit_changed(commit):
    """The commit with its last hex digit changed, a near miss of the real one."""
    return commit[:-1] + ("1" if commit.endswith("0") else "0")


REPLICATION_HEADING = "# Replication from public consumption data {#sec-replication}\n"

# Each case drifts one in-kind figure where the paper states it. The lift
# range also appears in the abstract and the discussion, so the first case
# fails only because the pin reads the in-kind section itself.
INKIND_PROSE_MUTATIONS = (
    (
        'lift range',
        'section',
        r"0\.5(\s+)to(\s+)3\.5",
        r"0.6\1to\g<2>3.5",
        'in-kind lift range',
    ),
    (
        'abstract lift range',
        'abstract',
        r"0\.5(\s+)to(\s+)3\.5",
        r"0.5\1to\g<2>3.6",
        'abstract in-kind lift range',
    ),
    (
        'swapped stage changes',
        'section',
        r"by(\s+)−0\.17,(\s+)−1\.63,",
        r"by\1−1.63,\2−0.17,",
        'stage changes in tenure order',
    ),
    (
        'rental assistance share of the difference',
        'section',
        r"\\\$175",
        r"\\$157",
        'difference in rises by benefit',
    ),
    (
        "BLS imputed renter points",
        "section",
        r"5\.71(\s+)percent,(\s+)0\.62",
        r"5.71\1percent,\g<2>0.66",
        "BLS 2024-2025 renter growth without its imputed terms",
    ),
    (
        'Garner–Munoz lower bound with home internet',
        'section',
        r"by(\s+)−2\.13(\s+)to(\s+)\+0\.90",
        r"by\1−2.14\2to\g<3>+0.90",
        'Garner–Munoz range with home internet',
    ),
    (
        "vacation-home utilities",
        "section",
        r"and(\s+)utilities(\s+)for(\s+)vacation(\s+)homes",
        r"and\1fuels\2for\3vacation\4homes",
        "Garner–Munoz runs drop vacation-home utilities",
    ),
    (
        "kept vacation-home fuel codes",
        "section",
        r"under(\s+)two(\s+)codes",
        r"under\1three\2codes",
        "Garner–Munoz runs keep the vacation-home fuel codes",
    ),
    ("implicate count", "section", r"We draw five implicates", "We draw four implicates", "implicate, matching-neighbor"),
    (
        'abstract stage changes',
        'abstract',
        r"−1\.63(\s+)to(\s+)−0\.17(\s+)points",
        r"−1.63\1to\g<2>−0.71\3points",
        'abstract stage-change range',
    ),
    (
        "abstract accounting share",
        "abstract",
        r"supply(\s+)4\.9(\s+)to(\s+)12\.9(\s+)percent",
        r"supply\g<1>4.9\2to\g<3>12.8\4percent",
        "abstract and discussion: the accounting's shares",
    ),
    ("identity tolerance", "section", r"0\.00001", "0.000001", "BLS identity tolerance"),
    (
        "evaluation BLS renter growth",
        "evaluation",
        r"renter(\s+)growth(\s+)of(\s+)6\.33",
        r"renter\1growth\2of\g<3>6.38",
        "evaluation section's BLS growth rates for 2024-2025",
    ),
    (
        "evaluation renter points",
        "evaluation",
        r"falls(\s+)by(\s+)0\.62(\s+)points",
        r"falls\1by\g<2>0.72\3points",
        "evaluation section cites BLS's imputed renter points",
    ),
    (
        "appendix names the imputation's old commit",
        "appendix",
        re.escape(f"`{INKIND_COMMITS[INKIND_NAMES[1]]}`"),
        "`4778dfab2d109515b6a14e63da63011dd7feb884`",
        "appendix names the recorded calculator commits",
    ),
    (
        "appendix standard-error commit",
        "appendix",
        re.escape(f"`{INKIND_COMMITS[INKIND_NAMES[2]]}`"),
        f"`{last_digit_changed(INKIND_COMMITS[INKIND_NAMES[2]])}`",
        "appendix names the recorded calculator commits",
    ),
    (
        'replication standard-error ratios',
        'replication',
        r"0\.62(\s+)to(\s+)1\.04",
        r"0.63\1to\g<2>1.04",
        "replication standard errors relative to BLS's",
    ),
    (
        'swapped replication standard-error ratios',
        'replication',
        r"0\.88(\s+)to(\s+)1\.27(.*?)0\.91(\s+)to(\s+)1\.46",
        r"0.91\1to\g<2>1.46\g<3>0.88\g<4>to\g<5>1.27",
        "replication standard errors relative to BLS's",
    ),
    (
        "stage change within one standard error",
        "section",
        r"each(\s+)within(\s+)one(\s+)standard(\s+)error",
        r"each\1within\2half\3a\4standard error",
        "stage changes in tenure order, each within one standard error",
    ),
    (
        'stage-change standard error',
        'section',
        r"3\.19(\s+)for",
        r"3.91\1for",
        'standard errors of the stage change',
    ),
    ("replicate count", "section", r"CE's(\s+)44(\s+)replicate", r"CE's\g<1>40\2replicate", "standard errors of the stage change"),
    (
        "three-quarters bound",
        "section",
        r"three-quarters(\s+)of(\s+)a",
        r"half\1of\2a",
        "every stage change within three-quarters of a standard error",
    ),
    (
        'implicate variance share',
        'section',
        r"for(\s+)8(\s+)to(\s+)30(\s+)percent",
        r"for\g<1>8\2to\g<3>31\4percent",
        "implicate share of the stage change's variance",
    ),
    (
        "half-sample quarters",
        "section",
        r"2016Q4(\s+)and(\s+)2017Q1",
        r"2016Q3\1and\g<2>2016Q4",
        "half-sample pattern changes",
    ),
    (
        "half-sample thresholds",
        "section",
        r"Replicates(\s+)for(\s+)the(\s+)2019–2021",
        r"Replicates\1for\2the\g<3>2019–2022",
        "half-sample pattern changes",
    ),
    (
        "stage-change standard error period",
        "section",
        r"change(\s+)to(\s+)2022–2025(\s+)growth",
        r"change\1to\g<2>2021–2025\3growth",
        "standard errors of the stage change",
    ),
    (
        "stage changes moved out of the growth section",
        "section",
        r"(With\s+home\s+internet\s+added,\s+we\s+estimate\s+that\s+the\s+imputed\s+benefits\s+change\s+growth\s+by\s.*?"
        r"each\s+within\s+one\s+standard\s+error\s+of\s+zero)\s+\(@sec-inkind-uncertainty\)\."
        r"(.*?## Uncertainty and limitations \{#sec-inkind-uncertainty\}\n\n)",
        r"\2\1. ",
        "stage changes in tenure order, each within one standard error",
    ),
    (
        "benefits' share with the index's lead on their terms",
        "section",
        r"falls(\s+)to(\s+)4\.3,(\s+)6\.8,",
        r"falls\1to\g<2>6.8,\g<3>4.3,",
        "accounting with the index's lead on the benefits' terms",
    ),
    (
        "rental assistance per renter 2019-2022 growth",
        "section",
        r"renter(\s+)rose(\s+)17(\s+)percent",
        r"renter\1rose\g<2>27\3percent",
        "rental assistance per renter: 2019–2022 growth",
    ),
    (
        "appendix receipt count",
        "appendix",
        r"we(\s+)keep(\s+)three(\s+)receipts",
        r"we\1keep\2two\3receipts",
        "appendix counts the receipts",
    ),
    # Labels, directions and the displayed formula: each figure stays put
    # while the words that give it meaning change.
    (
        'swapped home internet tenure labels',
        'section',
        r"\+0\.01(\s+)points(\s+)for(\s+)owners(\s+)with(\s+)mortgages,(\s+)\+4\.33(\s+)for(\s+)owners(\s+)without",
        r"+0.01\1points\2for\3owners\4without\5mortgages,\6+4.33\7for\8owners\9with",
        "home internet's change to growth",
    ),
    (
        'level comparison direction',
        'section',
        r"both,(\s+)we(\s+)estimate(\s+)thresholds(\s+)that(\s+)exceed",
        r"both,\1we\2estimate\3thresholds\4that\5fall below",
        'replication with home internet and benefits exceeds BLS in every cell',
    ),
    (
        'rental assistance level gap direction',
        'section',
        r"60(\s+)to(\s+)89(\s+)percent(\s+)above",
        r"60\1to\g<2>89\3percent\4below",
        'rental assistance per renter: level gap before 2024',
    ),
    (
        "mean absolute deviation direction",
        "section",
        r"deviation(\s+)falls(\s+)from",
        r"deviation\1rises\2from",
        "Garner–Munoz mean absolute deviation",
    ),
    (
        'deflator direction',
        'section',
        r"changes(\s+)by(\s+)\+0\.97,",
        r"changes\1by\2−0.97,",
        "BLS's index in place of the composite CPI: growth with home internet",
    ),
    (
        "renter shortfall direction",
        "section",
        r"benefits(\s+)trails(\s+)BLS's(\s+)by(\s+)2\.59",
        r"benefits\1exceeds\2BLS's\3by\g<4>2.59",
        "renter shortfall with imputed terms removed",
    ),
    (
        "swapped share tenures",
        "section",
        r"supply(\s+)4\.9,(\s+)7\.6,(\s+)and(\s+)12\.9",
        r"supply\g<1>12.9,\g<2>7.6,\3and\g<4>4.9",
        "three-part accounting of BLS's growth beyond CPI-U",
    ),
    (
        "swapped BLS and replication shares",
        "section",
        r"percent(\s+)of(\s+)BLS's(\s+)growth(\s+)beyond(\s+)CPI-U,(\s+)and(\s+)we(\s+)estimate",
        r"percent\1of\2our\3growth\4beyond\5CPI-U,\6and\7BLS\8estimates",
        "three-part accounting of BLS's growth beyond CPI-U",
    ),
    (
        "share formula operator",
        "section",
        r"I_\{2025\}-\\pi",
        r"I_{2025}+\\pi",
        "displayed share formula reproduces BLS's shares",
    ),
    (
        "share formula year",
        "section",
        r"\(I_\{2025\}",
        r"(I_{2022}",
        "displayed share formula reproduces BLS's shares",
    ),
    (
        "summer Pandemic EBT year",
        "section",
        r"summer(\s+)Pandemic(\s+)EBT(\s+)in(\s+)its(\s+)2022",
        r"summer\1Pandemic\2EBT\3in\4its\g<5>2023",
        "school lunch EBT caveat reaches 2022's summer Pandemic EBT",
    ),
    (
        "EBT-card caveat confined to 2020 and 2021",
        "section",
        r"2021(\s+)values(\s+)and(\s+)for(\s+)summer(\s+)Pandemic(\s+)EBT(\s+)in(\s+)its(\s+)2022(\s+)values(\s+)",
        r"2021\1values\2",
        "school lunch EBT caveat reaches 2022's summer Pandemic EBT",
    ),
    (
        "school days",
        "section",
        r"179(\s+)school",
        r"180\1school",
        "method constants read from fingerprinted calculator code",
    ),
    (
        "WIC mother's minimum age",
        "section",
        r"has(\s+)a(\s+)woman(\s+)aged(\s+)15(\s+)or",
        r"has\1a\2woman\3aged\g<4>18\5or",
        "method constants read from fingerprinted calculator code",
    ),
    (
        "discussion accounting parts swapped",
        "discussion",
        r"FCSUti(\s+)index(\s+)supplies(\s+)33(\s+)to(\s+)39(\s+)percent(.*?)supply(\s+)4\.9(\s+)to(\s+)12\.9",
        r"FCSUti\1index\2supplies\g<3>4.9\4to\g<5>12.9\6percent\7supply\g<8>33\9to\g<10>39",
        "abstract and discussion: the accounting's shares",
    ),
    # Round 2: the verb or label beside each figure, and the method facts
    # the section quotes, each changed while every figure stays put.
    (
        'lift direction',
        'section',
        r"they(\s+)raise(\s+)the(\s+)thresholds(\s+)by(\s+)a(\s+)further",
        r"they\1lower\2the\3thresholds\4by\5a\6further",
        'in-kind lift range',
    ),
    (
        'abstract lift direction',
        'abstract',
        r"they(\s+)raise(\s+)thresholds(\s+)by(\s+)a(\s+)further",
        r"they\1lower\2thresholds\3by\4a\5further",
        'abstract in-kind lift range',
    ),
    (
        'discussion lift direction',
        'discussion',
        r"benefits(\s+)raises(\s+)them",
        r"benefits\1lowers\2them",
        'discussion home internet and in-kind lift ranges',
    ),
    (
        'swapped stages in the 2024-2025 renter growth',
        'section',
        r"at(\s+)4\.85(\s+)percent(.*?)internet,(\s+)and(\s+)4\.83",
        r"at\g<1>4.83\2percent\3internet,\4and\g<5>4.85",
        'replication 2024-2025 renter growth in three stages',
    ),
    (
        "swapped benefits in the difference",
        "section",
        r"rental(\s+)assistance(\s+)supplies(.*?)and(\s+)school(\s+)lunch",
        r"school\1lunch\2supplies\3and\4rental\5assistance",
        "difference in rises by benefit",
    ),
    (
        "swapped owners of the imputed totals",
        "section",
        r"BLS's(\s+)imputed(\s+)benefits(\s+)rose(\s+)from(.*?)that(\s+)ours(\s+)rose",
        r"our\1imputed\2benefits\3rose\4from\5that\6BLS's\7rose",
        "BLS and replication imputed totals",
    ),
    (
        'standard error of our rise',
        'section',
        r"standard(\s+)error(\s+)of(\s+)\\\$190",
        r"standard\1error\2of\3\\$109",
        'BLS and replication imputed totals',
    ),
    (
        "swapped price series",
        "section",
        r"CPI-U(\s+)rose(\s+)10\.01(\s+)percent,(\s+)BLS's(\s+)FCSUti(\s+)price(\s+)index(\s+)14\.19",
        r"BLS's FCSUti price index\1rose\g<2>10.01\3percent,\4CPI-U\g<8>14.19",
        "price and BLS threshold growth",
    ),
    (
        "growth caption window",
        "section",
        r"national(\s+)threshold(\s+)growth(\s+)from(\s+)2022",
        r"national\1threshold\2growth\3from\g<4>2021",
        "growth table caption names the growth window",
    ),
    (
        'Garner–Munoz stage without home internet or benefits',
        'section',
        r"replication(\s+)without(\s+)home(\s+)internet(\s+)or(\s+)benefits(\s+)trails",
        r"replication\1with\2home\3internet\4and\5benefits\6trails",
        'Garner–Munoz range without home internet or benefits',
    ),
    (
        'Garner–Munoz stage with benefits',
        'section',
        r"When(\s+)we(\s+)also(\s+)add(\s+)the(\s+)imputed(\s+)benefits",
        r"When\1we\2also\3remove\4the\5imputed\6benefits",
        'Garner–Munoz range with benefits and home internet',
    ),
    (
        "share formula deflator",
        "section",
        r"denotes(\s+)CPI-U's(\s+)growth",
        r"denotes\1the FCSUti index's\2growth",
        "displayed share formula reproduces BLS's shares",
    ),
    (
        "BLS 2024-2025 renter split source",
        "section",
        r"and(\s+)rental(\s+)assistance(\s+)alone(\s+)accounts",
        r"and\1school\2lunch\3alone\4accounts",
        "BLS 2024-2025 renter growth without its imputed terms",
    ),
    (
        "owner of the 2024-2025 rental assistance per renter",
        "section",
        r"BLS's(\s+)rental(\s+)assistance(\s+)per(\s+)renter(\s+)rose(\s+)from",
        r"Our\1rental\2assistance\3per\4renter\5rose\6from",
        "BLS 2024-2025 renter growth without its imputed terms",
    ),
    (
        "renters' utilities rule",
        "section",
        r"renters'(\s+)utilities(\s+)for(\s+)any(\s+)property(\s+)but(\s+)a(\s+)rented(\s+)vacation(\s+)home",
        r"renters'\1utilities\2for\3the primary residence only",
        "Garner–Munoz restrictions read from fingerprinted calculator code",
    ),
    (
        "kept fuel codes' reason",
        "section",
        r"vacation-home(\s+)utilities(\s+)leave(\s+)out",
        r"vacation-home\1utilities\2include",
        "Garner–Munoz runs keep the vacation-home fuel codes",
    ),
    (
        "WIC universe year",
        "section",
        r"For(\s+)the(\s+)2025(\s+)thresholds,(\s+)as(\s+)BLS(\s+)does",
        r"For\1the\g<2>2024\3thresholds,\4as\5BLS\6does",
        "method constants read from fingerprinted calculator code",
    ),
    (
        "WIC universe rule",
        "section",
        r"but(\s+)no(\s+)woman(\s+)aged(\s+)15",
        r"but\1no\2woman\3aged\g<4>18",
        "method constants read from fingerprinted calculator code",
    ),
    (
        "WIC infant age",
        "section",
        r"child(\s+)aged(\s+)0(\s+)or(\s+)1\.",
        r"child\1aged\g<2>0\3to\g<4>2.",
        "method constants read from fingerprinted calculator code",
    ),
    (
        "WIC pregnant woman",
        "section",
        r"we(\s+)count(\s+)one(\s+)pregnant(\s+)woman",
        r"we\1count\2two\3pregnant\4women",
        "method constants read from fingerprinted calculator code",
    ),
    (
        "income imputations",
        "section",
        r"income(\s+)five(\s+)times",
        r"income\1three\2times",
        "method constants read from fingerprinted calculator code",
    ),
    (
        "amounts caption band",
        "section",
        r"consumer(\s+)unit(\s+)in(\s+)the(\s+)47th–53rd",
        r"consumer\1unit\2in\3the\g<4>45th–55th",
        "percentile band and windows read from fingerprinted calculator code",
    ),
    (
        "Census school lunch first year",
        "section",
        r"From(\s+)reference(\s+)year(\s+)2018,",
        r"From\1reference\2year\g<3>2019,",
        "Census school lunch values from their first reference year",
    ),
    (
        "internet row years",
        "section",
        r'through(\s+)2024(\s+)and(\s+)"Total',
        r'through\g<1>2023\2and\3"Total',
        "BLS internet row by threshold year",
    ),
    (
        "program count",
        "section",
        r"For(\s+)all(\s+)four(\s+)programs",
        r"For\1all\2five\3programs",
        "programs the participation models cover",
    ),
    (
        'benefit count',
        'section',
        r"internet(\s+)and(\s+)the(\s+)five(\s+)benefits",
        r"internet\1and\2the\3four\4benefits",
        'programs the participation models cover',
    ),
    (
        "amounts caption implicate count",
        "section",
        r"across(\s+)five(\s+)implicates",
        r"across\1four\2implicates",
        "implicate, matching-neighbor and cell-donor counts",
    ),
    (
        "WIC mother in the 2025 additions",
        "section",
        r"we(\s+)count(\s+)the(\s+)children(\s+)alone",
        r"we\1count\2the\3children\4and one mother",
        "method constants read from fingerprinted calculator code",
    ),
    (
        "years of the imputed totals",
        "section",
        r"Between(\s+)the(\s+)2022(\s+)and(\s+)2025(\s+)thresholds,(\s+)BLS's",
        r"Between\1the\g<2>2021\3and\g<4>2025\5thresholds,\6BLS's",
        "BLS and replication imputed totals",
    ),
    (
        "tenure of the 2024-2025 split",
        "section",
        r"For(\s+)renters(\s+)from(\s+)2024(\s+)to(\s+)2025,",
        r"For\1owners with mortgages\2from\g<3>2024\4to\g<5>2025,",
        "BLS 2024-2025 renter growth without its imputed terms",
    ),
    (
        "survey holding Census lunch values",
        "section",
        r"which(\s+)every(\s+)public(\s+)CPS(\s+)ASEC(\s+)person(\s+)file",
        r"which\1every\2public\3CE\5person\6file",
        "Census school lunch values from their first reference year",
    ),
    (
        "programs in the participation list",
        "section",
        r"and(\s+)broadband(\s+)subsidies(\s+)to(\s+)CE(\s+)consumer",
        r"and\1rental\2assistance\3to\4CE\5consumer",
        "programs the participation models cover",
    ),
    (
        "vacation-home principal kept",
        "section",
        r"amounts(\s+)and(\s+)the(\s+)vacation-home(\s+)mortgage",
        r"amounts\1but keep\2the\3vacation-home\4mortgage",
        "Garner–Munoz restrictions read from fingerprinted calculator code",
    ),
    (
        "internet row rule",
        "section",
        r"gives(\s+)equal(\s+)dollars(\s+)across(\s+)tenures",
        r"gives\1the\2most dollars\3across\4tenures",
        "BLS internet reading from fingerprinted calculator code",
    ),
    (
        "broadband in the internet row",
        "section",
        r"as(\s+)including(\s+)broadband(\s+)subsidies(\s+)and(\s+)subtract",
        r"as\1excluding\2broadband\3subsidies\4and\5add",
        "BLS internet reading from fingerprinted calculator code",
    ),
    (
        "FCSUti price factors across replicates",
        "section",
        r"price(\s+)factors(\s+)do(\s+)not(\s+)vary",
        r"price\1factors\2vary",
        "FCSUti price factors held fixed across replicates",
    ),
    # Round 3 (the r4 review): the accounting, the level gap, the new
    # standard errors and the method facts read from code.
    (
        'Garner–Munoz stage change',
        'section',
        r"by(\s+)\+0\.42,(\s+)−4\.45,",
        r"by\1+0.42,\2−4.54,",
        'Garner–Munoz restrictions with the composite CPI',
    ),
    (
        "abstract names the CE summaries",
        "abstract",
        r"with(\s+)the(\s+)CE's(\s+)spending(\s+)summaries",
        r"with\1the\2Garner–Munoz\3shelter\4restrictions",
        "abstract stage-change range",
    ),
    (
        'internet share of thresholds',
        'section',
        r"1\.85(\s+)to(\s+)2\.55",
        r"1.85\1to\g<2>2.65",
        "home internet's share of our thresholds and BLS's",
    ),
    (
        'BLS 2025 rental assistance per renter',
        'section',
        '\\\\\\$1,243(\\s+)in(\\s+)2025',
        '\\\\$1,234\\1in\\g<2>2025',
        "rental assistance per renter: BLS's 2024 and 2025 rise",
    ),
    (
        'standard error of our rental rise',
        'section',
        r"with(\s+)a(\s+)standard(\s+)error(\s+)of(\s+)\\\$453",
        r"with\1a\2standard\3error\4of\5\\$435",
        "rental assistance per renter: BLS's 2024 and 2025 rise",
    ),
    (
        'accounting excess',
        'section',
        'outgrew(\\s+)CPI-U(\\s+)by(\\s+)11\\.61',
        'outgrew\\1CPI-U\\2by\\g<3>11.16',
        "three-part accounting of BLS's growth beyond CPI-U",
    ),
    (
        'index beyond CPI-U',
        'section',
        'by(\\s+)4\\.18(\\s+)points',
        'by\\g<1>4.81\\2points',
        "three-part accounting of BLS's growth beyond CPI-U",
    ),
    (
        'renter benefits part',
        'section',
        '4\\.04,(\\s+)1\\.57,',
        '4.04,\\g<1>1.75,',
        "three-part accounting of BLS's growth beyond CPI-U",
    ),
    (
        're-ranking sign',
        'section',
        r"−0\.27,(\s+)−1\.72,",
        r"−0.27,\1+1.72,",
        're-ranking left out of the accounting',
    ),
    (
        "CPI-U growth at BLS's vintage",
        'section',
        'growth(\\s+)at(\\s+)10\\.08',
        'growth\\1at\\g<2>10.01',
        "CPI-U vintage on BLS's 2025 page",
    ),
    (
        'interpolated 2025 CPI-U in the price section',
        'price',
        'average(\\s+)of(\\s+)138\\.289',
        'average\\1of\\g<2>138.298',
        "CPI-U vintage on BLS's 2025 page",
    ),
    (
        "Schild's inflation points",
        'section',
        'attributes(\\s+)7\\.21',
        'attributes\\g<1>7.12',
        "Schild's attribution of the 2021-2022 rise",
    ),
    (
        'school lunch rise standard error',
        'section',
        r"\\\$47(\s+)for(\s+)school(\s+)lunch",
        r"\\$74\1for\2school\3lunch",
        'standard errors of the rises in band amounts',
    ),
    (
        'lift standard errors',
        'section',
        r"0\.26(\s+)to(\s+)0\.57",
        r"0.26\1to\g<2>0.75",
        "standard errors of the benefits' lifts",
    ),
    (
        'lift years within 1.5 standard errors',
        'section',
        r"the(\s+)2024–2025(\s+)lifts",
        r"the\g<1>2023–2025\2lifts",
        "standard errors of the benefits' lifts",
    ),
    (
        'lift standard-error multiple',
        'section',
        'exceed(\\s+)five(\\s+)standard(\\s+)errors',
        'exceed\\1six\\2standard\\3errors',
        "standard errors of the benefits' lifts",
    ),
    (
        "owners' rented-dwelling spending",
        'section',
        r"\\\$52(\s+)to(\s+)\\\$655",
        r"\\$52\1to\2\\$565",
        "Garner–Munoz restrictions keep owners' rented-dwelling spending",
    ),
    (
        'abstract uncertainty',
        'abstract',
        'each(\\s+)change(\\s+)within(\\s+)one(\\s+)standard',
        'each\\1change\\2within\\3half a\\4standard',
        'abstract and discussion: each change within one standard error',
    ),
    (
        'discussion uncertainty',
        'discussion',
        'points,(\\s+)each(\\s+)change(\\s+)within(\\s+)one',
        'points,\\1each\\2change\\3within\\4half a',
        'abstract and discussion: each change within one standard error',
    ),
    (
        'discussion growth claim without its CE-summaries scope',
        'discussion',
        "With(\\s+)the(\\s+)CE's(\\s+)spending(\\s+)summaries,(\\s+)we(\\s+)estimate",
        'We\\6estimate',
        'discussion growth changes from home internet and the benefits',
    ),
    (
        'reference-year rule',
        'section',
        'interviews(\\s+)to(\\s+)the(\\s+)year(\\s+)before',
        'interviews\\1to\\2the\\3year\\4after',
        'method constants read from fingerprinted calculator code',
    ),
    (
        'ridge penalty',
        'section',
        'ridge(\\s+)penalty(\\s+)of(\\s+)one',
        'ridge\\1penalty\\2of\\3two',
        'method constants read from fingerprinted calculator code',
    ),
    (
        'school lunch cell ladder',
        'section',
        'then(\\s+)across(\\s+)numbers(\\s+)of(\\s+)children,(\\s+)then(\\s+)across(\\s+)regions',
        'then\\1across\\2regions,\\5then\\6across\\7numbers of children',
        'method constants read from fingerprinted calculator code',
    ),
    (
        'children top-code',
        'section',
        'top-coded(\\s+)at(\\s+)four',
        'top-coded\\1at\\2three',
        'method constants read from fingerprinted calculator code',
    ),
    (
        'reference year of the Bridge File lunch values',
        'section',
        'for(\\s+)2017(\\s+)also(\\s+)in(\\s+)the(\\s+)2018(\\s+)CPS',
        'for\\g<1>2016\\2also\\3in\\4the\\g<5>2018\\6CPS',
        'Census school lunch values from their first reference year',
    ),
    (
        'first CPS ASEC file with Census lunch values',
        'section',
        'from(\\s+)the(\\s+)2019(\\s+)file(\\s+)onward',
        'from\\1the\\g<2>2018\\3file\\4onward',
        'Census school lunch values from their first reference year',
    ),
    (
        'research-file years',
        'section',
        'For(\\s+)reference(\\s+)years(\\s+)2014–2017,',
        'For\\1reference\\2years\\g<3>2015–2017,',
        'Census school lunch values from their first reference year',
    ),
    (
        'our 2024-2025 rental assistance per renter',
        'section',
        r"ours(\s+)rose(\s+)from(\s+)\\\$1,277",
        r"ours\1rose\2from\3\\$1,272",
        'BLS 2024-2025 renter growth without its imputed terms',
    ),
    (
        'BLS renter growth without imputed terms',
        'section',
        'grows(\\s+)5\\.71',
        'grows\\g<1>5.17',
        'BLS 2024-2025 renter growth without its imputed terms',
    ),
    # Round 4: the split with the Other share kept separate, as BLS
    # publishes it, beside ours, which gives each term its part of it.
    (
        "abstract share with the Other share kept separate",
        "abstract",
        r"supply(\s+)3\.5(\s+)to(\s+)11\.8",
        r"supply\g<1>3.5\2to\g<3>11.9",
        "abstract and discussion: the accounting's shares",
    ),
    (
        "abstract accountings swapped",
        "abstract",
        r"supply(\s+)4\.9(\s+)to(\s+)12\.9(.*?)supply(\s+)3\.5(\s+)to(\s+)11\.8",
        r"supply\g<1>3.5\2to\g<3>11.8\4supply\g<5>4.9\6to\g<7>12.9",
        "abstract and discussion: the accounting's shares",
    ),
    (
        "discussion share with the Other share kept separate",
        "discussion",
        r"and(\s+)3\.5(\s+)to(\s+)11\.8(\s+)percent",
        r"and\g<1>3.6\2to\g<3>11.8\4percent",
        "abstract and discussion: the accounting's shares",
    ),
    (
        "benefits' rows with the Other share kept separate",
        "section",
        r"supply(\s+)3\.5,(\s+)5\.8,(\s+)and(\s+)11\.8",
        r"supply\g<1>11.8,\g<2>5.8,\3and\g<4>3.5",
        "accounting with the Other share kept separate",
    ),
    (
        "out-of-pocket and Other with the Other share kept separate",
        "section",
        r"supply(\s+)60\.9,(\s+)55\.4,",
        r"supply\g<1>60.9,\g<2>54.5,",
        "accounting with the Other share kept separate",
    ),
    (
        "Other share kept separate counted with the benefits",
        "section",
        r"count(\s+)the(\s+)Other(\s+)share(\s+)with(\s+)out-of-pocket(\s+)spending",
        r"count\1the\2Other\3share\4with\5the\6benefits",
        "accounting with the Other share kept separate",
    ),
    (
        "benefits' rows with the index's lead on them",
        "section",
        r"3\.0,(\s+)5\.2,(\s+)and(\s+)10\.7",
        r"3.0,\g<1>5.3,\2and\g<3>10.7",
        "accounting with the index's lead on the benefits' terms",
    ),
    (
        "terms and rows swapped with the index's lead on them",
        "section",
        r"with(\s+)their(\s+)terms,(\s+)and(.*?)with(\s+)their(\s+)rows",
        r"with\1their\2rows,\3and\4with\5their\6terms",
        "accounting with the index's lead on the benefits' terms",
    ),
    # The high end with the pooled broadband row, the reading before each
    # tenure's own broadband row: 2.13 where BLS's shares give 2.12.
    (
        "internet's share row",
        'section',
        r"1\.54(\s+)to(\s+)2\.12",
        r"1.54\1to\g<2>2.13",
        "home internet's share of our thresholds and BLS's",
    ),
    (
        "internet's two readings swapped",
        'section',
        r"supplies(\s+)1\.54(\s+)to(\s+)2\.12(.*?)supplies(\s+)1\.85(\s+)to(\s+)2\.55",
        r"supplies\g<1>1.85\2to\g<3>2.55\4supplies\g<5>1.54\6to\g<7>2.12",
        "home internet's share of our thresholds and BLS's",
    ),
    (
        "shared component's term coefficient",
        "section",
        r"puts(\s+)the(\s+)term(\s+)\$1\.2",
        r"puts\1the\2term\3$1.0",
        "each component's term carries its part of the Other share",
    ),
    (
        "shelter component's Other coefficient",
        "section",
        r"\+0\.2\\,\\overline\{c\}_E\)",
        r"+0.4\\,\\overline{c}_E)",
        "each component's term carries its part of the Other share",
    ),
    # Round 4: the Garner–Munoz runs keep BLS's current telephone split.
    (
        "telephone exception reversed",
        "section",
        r"We(\s+)keep(\s+)telephone(\s+)out(\s+)of(\s+)utilities",
        r"We\1keep\2telephone\3in\4utilities",
        "Garner–Munoz restrictions read from fingerprinted calculator code",
    ),
    # Round 4: rent paid and the two rental-assistance sensitivities.
    (
        "rent paid share of the three-month total",
        "section",
        r"as(\s+)one(\s+)third(\s+)of",
        r"as\1one\2quarter\3of",
        "method constants read from fingerprinted calculator code",
    ),
    (
        "rent sensitivity base amount",
        "section",
        r"\\\$10,809(\s+)per(\s+)assisted",
        r"\\$10,890\1per\2assisted",
        "rent sensitivities",
    ),
    (
        "next-interview rent change",
        "section",
        r"rises(\s+)0\.8(\s+)percent\.",
        r"rises\g<1>1.8\2percent.",
        "rent sensitivities",
    ),
    (
        "linked renters",
        "section",
        r"6,159(\s+)renters,(\s+)3,120",
        r"6,159\1renters,\g<2>3,210",
        "rent sensitivities",
    ),
    (
        "part-period bounds",
        "section",
        r"is(\s+)25(\s+)to(\s+)75(\s+)percent(\s+)of(\s+)that(\s+)later",
        r"is\g<1>20\2to\g<3>80\4percent\5of\6that\7later",
        "rent sensitivities",
    ),
    (
        "predicted median and mean swapped",
        "section",
        r"falls(\s+)30(\s+)percent(.*?)median(\s+)and(\s+)16(\s+)percent",
        r"falls\g<1>16\2percent\3median\4and\g<5>30\6percent",
        "rent sensitivities",
    ),
    (
        "linear prediction change",
        "section",
        r"amount(\s+)falls(\s+)13(\s+)percent\.",
        r"amount\1falls\g<2>31\3percent.",
        "rent sensitivities",
    ),
    # Round 5: broadband's start, the 2020 WIC cutoff, its by-state
    # sensitivity, and the reading of the internet row with the Other share
    # kept separate.
    (
        "broadband start year",
        "section",
        r"We(\s+)impute(\s+)them(\s+)from(\s+)reference(\s+)year(\s+)2022(\s+)too",
        r"We\1impute\2them\3from\4reference\5year\g<6>2021\7too",
        "broadband start and WIC cutoff from the imputation receipt",
    ),
    (
        "broadband's first thresholds",
        "section",
        r"first(\s+)enter(\s+)our(\s+)2023(\s+)thresholds",
        r"first\1enter\2our\g<3>2022\4thresholds",
        "broadband start and WIC cutoff from the imputation receipt",
    ),
    (
        "WIC cutoff year",
        "section",
        r"We(\s+)add(\s+)no(\s+)WIC(\s+)from(\s+)reference(\s+)year(\s+)2020",
        r"We\1add\2no\3WIC\4from\5reference\6year\g<7>2021",
        "broadband start and WIC cutoff from the imputation receipt",
    ),
    (
        "reference year 2020's interviews",
        "section",
        r"from(\s+)April(\s+)2020(\s+)to(\s+)March(\s+)2021",
        r"from\1January\g<2>2020\3to\4December\g<5>2020",
        "method constants read from fingerprinted calculator code",
    ),
    (
        "reference year 2020's reference periods",
        "section",
        r"center(\s+)on(\s+)mid-February(\s+)2020",
        r"center\1on\2mid-May\g<3>2020",
        "method constants read from fingerprinted calculator code",
    ),
    (
        "the cutoff's reach before the deadline",
        "section",
        r"drop(\s+)WIC(\s+)for(\s+)reference(\s+)periods(\s+)before(\s+)the(\s+)deadline",
        r"drop\1WIC\2for\3reference\4periods\5after\6the\7deadline",
        "method constants read from fingerprinted calculator code",
    ),
    (
        "WIC EBT deadline",
        "section",
        r"by(\s+)October(\s+)1,(\s+)2020,",
        r"by\1October\g<2>1,\g<3>2021,",
        "WIC EBT deadline quoted from 42 U.S.C. 1786(h)(12)(B)(i)",
    ),
    (
        "who grants WIC EBT exemptions",
        "section",
        r"Secretary(\s+)of(\s+)Agriculture(\s+)exempted",
        r"Secretary\1of\2Commerce\3exempted",
        "WIC EBT deadline quoted from 42 U.S.C. 1786(h)(12)(B)(i)",
    ),
    (
        "states statewide before the deadline",
        "section",
        r"including(\s+)in(\s+)six(\s+)states(\s+)whose",
        r"including\1in\2four\3states\4whose",
        "WIC EBT dates from the calculator's FNS table",
    ),
    (
        "first state statewide in 2020",
        "section",
        r"from(\s+)Hawaii(\s+)to(\s+)Illinois",
        r"from\1California\2to\3Illinois",
        "WIC EBT dates from the calculator's FNS table",
    ),
    (
        "states statewide after the deadline",
        "section",
        r"agencies(\s+)of(\s+)six(\s+)more(\s+)states",
        r"agencies\1of\2seven\3more\4states",
        "WIC EBT dates from the calculator's FNS table",
    ),
    (
        "last state statewide",
        "section",
        r"to(\s+)Georgia(\s+)in(\s+)October(\s+)2022",
        r"to\1Georgia\2in\3October\g<4>2023",
        "WIC EBT dates from the calculator's FNS table",
    ),
    (
        "2025 window's reference years",
        "section",
        r"reference(\s+)year(\s+)2020(\s+)or(\s+)later,(\s+)so(\s+)our",
        r"reference\1year\g<2>2019\3or\4later,\5so\6our",
        "percentile band and windows read from fingerprinted calculator code",
    ),
    (
        "BLS's broadband thresholds",
        "section",
        r"in(\s+)its(\s+)2023–2025(\s+)thresholds,(\s+)from(\s+)data(\s+)that(\s+)start(\s+)in(\s+)2022",
        r"in\1its\g<2>2022–2025\3thresholds,\4from\5data\6that\7start\8in\g<9>2021",
        "broadband start and WIC cutoff from the imputation receipt",
    ),
    # Round 6: the 38bf21b review.
    (
        "the 2025 WIC universe's units under the cutoff",
        "section",
        r"these(\s+)units(\s+)take(\s+)none",
        r"these\1units\2take\3little",
        "broadband start and WIC cutoff from the imputation receipt",
    ),
    (
        "by-state WIC mean over CE units",
        "section",
        r"unit(\s+)with(\s+)children(\s+)rises",
        r"unit\1with\2adults\3rises",
        "WIC by-state sensitivity from the imputation receipt",
    ),
    (
        "separate-Other terms match each component row and Other",
        "section",
        r"for(\s+)Other(\s+)and(\s+)for(\s+)each(\s+)component",
        r"for\1Other\2but\3not\4each\5component",
        "BLS internet reading from fingerprinted calculator code",
    ),
    (
        "telephone split's source",
        "section",
        r"as(\s+)BLS(\s+)now(\s+)does(\s+)\[@blsspmshares\]",
        r"as\1BLS\2now\3does\4[@blsspmhome]",
        "Garner–Munoz restrictions read from fingerprinted calculator code",
    ),
    (
        "renters who take the next interview's rent",
        "section",
        r"of(\s+)156(\s+)of(\s+)those",
        r"of\g<1>165\2of\3those",
        "rent sensitivities",
    ),
    (
        "assisted renters who take the next interview's rent",
        "section",
        r"including(\s+)29(\s+)assisted",
        r"including\g<1>92\2assisted",
        "rent sensitivities",
    ),
    (
        "point-fit variants' parameters",
        "section",
        r"implicates(\s+)and(\s+)draw(\s+)new(\s+)parameters",
        r"implicates\1and\2draw\3fitted\4parameters",
        "rent sensitivities",
    ),
    (
        "BLS's 2025 WIC band mean",
        "section",
        r"WIC(\s+)of(\s+)\\\$1\.80",
        r"WIC\1of\2\\$1.08",
        "BLS's 2025 WIC band mean against our none",
    ),
    (
        "our 2025 WIC",
        "section",
        r"where(\s+)we(\s+)add(\s+)none",
        r"where\1we\2add\3less",
        "BLS's 2025 WIC band mean against our none",
    ),
    (
        'by-state WIC rise',
        'section',
        r"\\\$1\.94(\s+)to(\s+)\\\$3\.20",
        r"\\$1.94\1to\2\\$3.02",
        'WIC by-state sensitivity from the imputation receipt',
    ),
    (
        "by-state WIC thresholds",
        "section",
        r"behind(\s+)the(\s+)2021–2025(\s+)thresholds",
        r"behind\1the\g<2>2020–2025\3thresholds",
        "WIC by-state sensitivity from the imputation receipt",
    ),
    (
        'by-state WIC threshold moves in dollars',
        'section',
        r"move(\s+)by(\s+)−\\\$5(\s+)to",
        r"move\1by\2+\\$5\3to",
        'WIC by-state sensitivity from the imputation receipt',
    ),
    (
        'by-state WIC threshold moves in percent',
        'section',
        r"\(−0\.01(\s+)to(\s+)\+0\.05(\s+)percent\)",
        r"(−0.01\1to\g<2>+0.50\3percent)",
        'WIC by-state sensitivity from the imputation receipt',
    ),
    (
        "by-state WIC growth bound",
        "section",
        r"change(\s+)of(\s+)0\.03(\s+)points(\s+)or(\s+)less",
        r"change\1of\g<2>0.02\3points\4or\5less",
        "WIC by-state sensitivity from the imputation receipt",
    ),
    (
        "internet share less the tenure's own broadband",
        "section",
        r"less(\s+)the(\s+)tenure's(\s+)own(\s+)broadband(\s+)row",
        r"less\1the\2pooled\4broadband\5row",
        "BLS internet reading from fingerprinted calculator code",
    ),
    # Round 7: the 4866eb7 delta check.
    (
        "separate-Other terms' source",
        "section",
        r"terms(\s+)we(\s+)compute(\s+)from(\s+)BLS's(\s+)band(\s+)means",
        r"terms\1we\2compute\3from\4our\5band\6means",
        "BLS internet reading from fingerprinted calculator code",
    ),
    (
        "compound count of states statewide before the deadline",
        "section",
        r"including(\s+)in(\s+)six(\s+)states(\s+)whose",
        r"including\1in\2twenty-six\3states\4whose",
        "WIC EBT dates from the calculator's FNS table",
    ),
    (
        "states BLS's rule would reach",
        "section",
        r"the(\s+)12(\s+)states(\s+)and(\s+)the(\s+)District",
        r"the\g<1>13\2states\3and\4the\5District",
        "WIC EBT dates from the calculator's FNS table",
    ),
    (
        "compound count of matching neighbors",
        "section",
        r"of(\s+)one(\s+)of(\s+)the(\s+)five(\s+)recipients",
        r"of\1twenty-one\2of\3the\4five\5recipients",
        "implicate, matching-neighbor and cell-donor counts",
    ),
    (
        "interview that supplies the replacement rent",
        "section",
        r"reports(\s+)at(\s+)its(\s+)next(\s+)interview,",
        r"reports\1at\2its\3previous\4interview,",
        "rent sensitivities",
    ),
    (
        "point-fit variants' parameters fixed",
        "section",
        r"we(\s+)fix(\s+)each(\s+)model's(\s+)parameters",
        r"we\1draw\2each\3model's\4parameters",
        "rent sensitivities",
    ),
    # Round 8: the 4a23997 delta check.
    (
        "compound count of matching neighbors with a non-breaking hyphen",
        "section",
        r"of(\s+)one(\s+)of(\s+)the(\s+)five(\s+)recipients",
        "of\\1twenty\u2011one\\2of\\3the\\4five\\5recipients",
        "implicate, matching-neighbor and cell-donor counts",
    ),
    # Round 9: the bf4b9ab review's P3s.
    (
        "shares the growth split starts from",
        "section",
        r"and(\s+)the(\s+)shares(\s+)from(\s+)which(\s+)we(\s+)reproduce(\s+)them",
        r"and\1shares\2BLS\3reissued",
        "growth split from BLS's July 2026 reissue",
    ),
    (
        "thresholds the growth split starts from",
        "section",
        r"2022(\s+)thresholds(\s+)BLS(\s+)reissued(\s+)in(\s+)July(\s+)2026",
        r"2022\1thresholds\2BLS\3published\4in\5September\g<6>2023",
        "growth split from BLS's July 2026 reissue",
    ),
    (
        "by-state run's reference years",
        "section",
        r"apply(\s+)BLS's(\s+)rule(\s+)state(\s+)by(\s+)state(\s+)in(\s+)every(\s+)reference(\s+)year",
        r"apply\1BLS's\2rule\3state\4by\5state\6in\7earlier\8reference\9years",
        "WIC by-state sensitivity from the imputation receipt",
    ),
    (
        "by-state run's units in the 2025 window",
        "section",
        r"Some(\s+)units(\s+)in(\s+)the(\s+)2025(\s+)window(\s+)then",
        r"No\1units\2in\3the\g<4>2025\5window\6then",
        "WIC by-state sensitivity from the imputation receipt",
    ),
    (
        "the 2025 WIC universe's cutoff year",
        "section",
        r"we(\s+)add(\s+)no(\s+)WIC(\s+)from(\s+)reference(\s+)year(\s+)2020(\s+)on,",
        r"we\1add\2no\3WIC\4from\5reference\6year\g<7>2021\8on,",
        "broadband start and WIC cutoff from the imputation receipt",
    ),
    (
        "2025 window's reference years in the WIC universe's sentence",
        "section",
        r"reference(\s+)year(\s+)2020(\s+)or(\s+)later,(\s+)and(\s+)we(\s+)add",
        r"reference\1year\g<2>2019\3or\4later,\5and\6we\7add",
        "broadband start and WIC cutoff from the imputation receipt",
    ),
    (
        "statewide dates the by-state run reaches",
        "section",
        r"fall(\s+)in(\s+)June(\s+)2020(\s+)or(\s+)later",
        r"fall\1in\2July\g<3>2020\4or\5later",
        "WIC EBT dates from the calculator's FNS table",
    ),
    (
        "re-ranking stated as an estimate",
        "section",
        r"replication,(\s+)we(\s+)estimate(\s+)that(\s+)this(\s+)re-ranking",
        r"replication,\1that\2re-ranking",
        "re-ranking left out of the accounting",
    ),
    (
        "home internet's lift for owners without mortgages",
        'section',
        r"0\.34(\s+)to(\s+)4\.00",
        r"0.34\1to\g<2>4.10",
        "home internet's lift by tenure",
    ),
    (
        "home internet's lift direction",
        'section',
        r"home(\s+)internet(\s+)raises(\s+)the(\s+)replicated",
        r"home\1internet\2lowers\3the\4replicated",
        "home internet's lift by tenure",
    ),
    (
        'home internet item code',
        'section',
        r"\(UCC\)(\s+)690114",
        r"(UCC)\g<1>690116",
        'home internet rules read from fingerprinted calculator code',
    ),
    (
        'home internet annualization',
        'section',
        r"three-month(\s+)total(\s+)by(\s+)four",
        r"three-month\1total\2by\3three",
        'home internet rules read from fingerprinted calculator code',
    ),
    (
        "home internet's spending summaries",
        'section',
        r"FCSUti(\s+)but(\s+)not(\s+)to(\s+)shelter",
        r"FCSUti\1and\2to\4shelter",
        'home internet rules read from fingerprinted calculator code',
    ),
    (
        "home internet's CPI weight",
        'section',
        r"FCSUti(\s+)spending(\s+)among(\s+)units(\s+)with(\s+)children",
        r"FCSUti\1spending\2among\3all\4units",
        'home internet rules read from fingerprinted calculator code',
    ),
    (
        'home internet added after the band',
        'section',
        r"internet(\s+)before(\s+)we(\s+)estimate",
        r"internet\1after\2we\3estimate",
        'home internet rules read from fingerprinted calculator code',
    ),
    (
        "home internet moved into the benefits' terms",
        'section',
        r"count(\s+)home(\s+)internet(\s+)with(\s+)out-of-pocket(\s+)spending",
        r"count\1home\2internet\3with\4the\5benefits",
        'home internet counts with out-of-pocket spending in the accounting',
    ),
    (
        "a standard error for home internet's change",
        'section',
        r"report(\s+)no(\s+)standard(\s+)error",
        r"report\1a\2standard\3error",
        "no standard error for home internet's own change",
    ),
    (
        'Garner–Munoz deviation with home internet',
        'section',
        r"from(\s+)3\.14(\s+)to(\s+)1\.11",
        r"from\g<1>3.14\2to\g<3>1.12",
        'Garner–Munoz mean absolute deviation in three stages',
    ),
    (
        'Garner–Munoz deviation with benefits',
        'section',
        r"rises(\s+)to(\s+)1\.76",
        r"rises\1to\g<2>1.67",
        'Garner–Munoz mean absolute deviation in three stages',
    ),
    (
        'Garner–Munoz lower bound with benefits',
        'section',
        r"by(\s+)0\.76(\s+)to(\s+)3\.63",
        r"by\g<1>0.67\2to\g<3>3.63",
        'Garner–Munoz range with benefits and home internet',
    ),
    (
        'Garner–Munoz direction with benefits',
        'section',
        r"benefits,(\s+)we(\s+)estimate(\s+)thresholds(\s+)that(\s+)exceed",
        r"benefits,\1we\2estimate\3thresholds\4that\5fall below",
        'Garner–Munoz range with benefits and home internet',
    ),
    (
        "Garner–Munoz growth against BLS's",
        'section',
        r"BLS's(\s+)by(\s+)\+0\.56,",
        r"BLS's\1by\2+0.65,",
        "Garner–Munoz restrictions with BLS's index",
    ),
    (
        "our band's home internet",
        'section',
        r"spending(\s+)of(\s+)\\\$543(\s+)to(\s+)\\\$869",
        r"spending\1of\2\\$543\3to\4\\$896",
        "home internet in our band and BLS's",
    ),
    (
        "our band's home internet against BLS's",
        'section',
        r"by(\s+)−1\.1(\s+)to(\s+)\+3\.1",
        r"by\1−1.1\2to\g<3>+3.2",
        "home internet in our band and BLS's",
    ),
    (
        "home internet's share of ours, Other separate",
        'section',
        r"supplies(\s+)1\.49(\s+)to(\s+)2\.04",
        r"supplies\g<1>1.49\2to\g<3>2.40",
        "home internet's share of our thresholds and BLS's",
    ),
    (
        "home internet's share of ours, Other spread",
        'section',
        r"1\.78(\s+)to(\s+)2\.44(\s+)percent(\s+)of(\s+)ours",
        r"1.78\1to\g<2>2.45\3percent\4of\5ours",
        "home internet's share of our thresholds and BLS's",
    ),
    (
        "evaluation's home internet change",
        'evaluation',
        r"by(\s+)−0\.27(\s+)points(\s+)and",
        r"by\1−0.72\2points\3and",
        "evaluation section cites BLS's imputed renter points and our changes",
    ),
    (
        "evaluation's benefits change",
        'evaluation',
        r"by(\s+)\+0\.25(\s+)points",
        r"by\1+0.52\2points",
        "evaluation section cites BLS's imputed renter points and our changes",
    ),
    (
        "discussion's home internet growth change",
        'discussion',
        r"by(\s+)−0\.54(\s+)to(\s+)\+4\.33",
        r"by\1−0.54\2to\g<3>+4.34",
        'discussion growth changes from home internet and the benefits',
    ),
    (
        "discussion's benefits growth change",
        'discussion',
        r"by(\s+)−1\.63(\s+)to(\s+)−0\.17",
        r"by\1−1.63\2to\g<3>−0.71",
        'discussion growth changes from home internet and the benefits',
    ),
    (
        "discussion's home internet lift",
        'discussion',
        r"by(\s+)0\.3(\s+)to(\s+)4\.0(\s+)percent",
        r"by\g<1>0.3\2to\g<3>4.1\4percent",
        'discussion home internet and in-kind lift ranges',
    ),
    (
        "discussion's home internet lift direction",
        'discussion',
        r"internet(\s+)raises(\s+)our(\s+)levels",
        r"internet\1lowers\2our\3levels",
        'discussion home internet and in-kind lift ranges',
    ),
    (
        'replication standard errors without home internet',
        'replication',
        r"for(\s+)the(\s+)replication(\s+)with(\s+)home(\s+)internet(\s+)added",
        r"for\1the\2replication\3without\4home\5internet",
        "replication standard errors relative to BLS's",
    ),
    (
        "abstract home internet lift",
        'abstract',
        r"by(\s+)0\.3(\s+)to(\s+)4\.0(\s+)percent",
        r"by\g<1>0.3\2to\g<3>4.1\4percent",
        'abstract home internet lift range',
    ),
    (
        "abstract standard-error clause moves to home internet",
        'abstract',
        r"4\.0(\s+)percent\.([\s\S]*?)summaries,(\s+)each(\s+)change(\s+)within(\s+)one(\s+)standard(\s+)error(\s+)of(\s+)zero\.",
        r"4.0\1percent, each change within one standard error of zero.\2summaries.",
        'abstract and discussion: each change within one standard error',
    ),
    (
        "abstract benefits' growth change given to home internet",
        'abstract',
        r"percent(\s+)and(\s+)change(\s+)2022–2025",
        r"percent\1and\2home internet costs change\g<3>2022–2025",
        'abstract stage-change range',
    ),
    (
        "discussion levels claim given to BLS",
        'discussion',
        r"We(\s+)estimate(\s+)that(\s+)adding(\s+)home(\s+)internet(\s+)raises",
        r"BLS\1estimates\2that\3adding\4home\5internet\6raises",
        'discussion home internet and in-kind lift ranges',
    ),
    (
        "discussion credits home internet with the shelter definitions' move",
        'discussion',
        r"shelter(\s+)definitions(\s+)also(\s+)move(\s+)them",
        r"shelter\1definitions\2and\3home internet\3also move\4them",
        'discussion home internet and in-kind lift ranges',
    ),
    (
        "WIC threshold moves without our estimate",
        'section',
        r"it,(\s+)we(\s+)estimate(\s+)that(\s+)those(\s+)thresholds(\s+)move",
        r"it,\1those\5thresholds\6move",
        'WIC by-state sensitivity from the imputation receipt',
    ),
    (
        "abstract home internet lift direction",
        'abstract',
        r"it(\s+)raises(\s+)replicated",
        r"it\1lowers\2replicated",
        'abstract home internet lift range',
    ),
    (
        "run count",
        'section',
        r"replication(\s+)three(\s+)ways",
        r"replication\1four\2ways",
        "three runs, the first reproducing the retrospective replication",
    ),
    (
        "the second run claims the exact reproduction",
        'section',
        r"The(\s+)first(\s+)run(\s+)reproduces",
        r"The\1second\2run\3reproduces",
        "three runs, the first reproducing the retrospective replication",
    ),
    (
        "appendix names the run with home internet as the reproduction",
        'appendix',
        r"run(\s+)without(\s+)home(\s+)internet(\s+)or(\s+)benefits(\s+)reproduces",
        r"run\1with\2home\3internet\6reproduces",
        "three runs, the first reproducing the retrospective replication",
    ),
    (
        "section 3 includes home internet",
        'replication',
        r"We(\s+)omit(\s+)home-internet(\s+)spending",
        r"We\1include\2home-internet\3spending",
        "section 3 replication omits home internet",
    ),
    (
        "growth caption swaps the second and third rows",
        'section',
        r"benefits,(\s+)with(\s+)home(\s+)internet,(\s+)and(\s+)with(\s+)both\.",
        r"benefits,\1with\2both,\4and\5with\6home internet.",
        "growth table caption names the stages in row order",
    ),
    (
        "growth caption puts the standard deviation in the second row",
        'section',
        r"In(\s+)the(\s+)third(\s+)row,",
        r"In\1the\2second\3row,",
        "growth table caption names the stages in row order",
    ),
    (
        "growth caption's Garner–Munoz row count",
        'section',
        r"In(\s+)the(\s+)final(\s+)three(\s+)rows",
        r"In\1the\2final\3two\4rows",
        "growth table caption names the stages in row order",
    ),
    (
        "levels caption drops home internet",
        'section',
        r"replication(\s+)with(\s+)home(\s+)internet(\s+)and(\s+)imputed(\s+)in-kind(\s+)benefits(\s+)from",
        r"replication\1with\5imputed\6in-kind\7benefits\8from",
        "levels table caption names the stage with both",
    ),
    (
        "discussion's standard-error clause moves to home internet",
        'discussion',
        r"\+4\.33(\s+)points\.(\s+)We(\s+)estimate",
        r"+4.33\1points, each change within one standard error of zero.\2We\3estimate",
        'discussion growth changes from home internet and the benefits',
    ),
    (
        "discussion drops the benefits' standard-error clause",
        'discussion',
        r"points,(\s+)each(\s+)change(\s+)within(\s+)one(\s+)standard(\s+)error(\s+)of(\s+)zero\.",
        r"points.",
        'abstract and discussion: each change within one standard error',
    ),
    (
        "implicate share without the benefits' scope",
        'section',
        r"For(\s+)each(\s+)of(\s+)the(\s+)benefits'(\s+)changes(\s+)to(\s+)2022–2025(\s+)growth,",
        r"For\1each\2change,",
        "implicate share of the stage change's variance",
    ),
    (
        "band scope drops home internet",
        'section',
        r"In(\s+)our(\s+)band(\s+)with(\s+)home(\s+)internet(\s+)and(\s+)the(\s+)benefits,",
        r"In\1our\2band\3with\7the\8benefits,",
        "home internet in our band and BLS's",
    ),
    (
        "evaluation's home internet change without its period",
        'evaluation',
        r"replication's(\s+)2024–2025(\s+)renter",
        r"replication's\1renter",
        "evaluation section cites BLS's imputed renter points and our changes",
    ),
    (
        "our home internet share stage drops home internet",
        'section',
        r"of(\s+)ours(\s+)with(\s+)home(\s+)internet(\s+)and(\s+)the(\s+)benefits",
        r"of\1ours\2with\6the\7benefits",
        "home internet's share of our thresholds and BLS's",
    ),
)

# The guard's label when it cannot read the abstract, before its reason, and
# the label of its check that the abstract states each tied figure once, its
# years as listed, and no other number.
ABSTRACT_UNREAD = "paper's abstract cannot be read:"
ABSTRACT_INVENTORY = "abstract states exactly the numbers the guard lists, each as a bare number"

# Each case drifts figures in the abstract alone: (name, pattern, replacement,
# failing ties, decoy). The body or a generated table states every one of these
# figures too. The decoy restates the original wording, and the tests place it
# at each of ABSTRACT_DECOY_HOSTS, so a tie that settled for one correct copy,
# or for the first or last rate it found, would pass the edited paper. The
# slot reads a sign typed as any dash and a range joined by a dash, a slash,
# "to" or "and" whole, so each fails beside a copy too, as does the
# inventory of the abstract's figures. A copy inside the abstract restates
# figures the abstract already states, so the inventory fails beside it
# too, and it fails alone for ABSTRACT_RULE_RENAMES, which leave no
# statement of the rule's wording. The wording-removal cases in
# test_abstract_ties_skip_wording_outside_the_block catch a tie that reads
# past the block, and test_abstract_markup_fails_every_abstract_tie covers
# emphasis and other markup.
ABSTRACT_PROSE_MUTATIONS = (
    (
        "2020-2025 CPI-U error",
        r"2\.29(\s+)percent",
        r"2.30\1percent",
        ("abstract current projection cpi_u 2.29", "current projection prose cpi_u", ABSTRACT_INVENTORY),
        "We obtain 2.29 percent with the Consumer Price Index for All Urban Consumers (CPI-U).",
    ),
    (
        "2020-2025 CPI-U sign",
        r"2\.29(\s+)percent",
        "−2.29\\1percent",
        ("abstract current projection cpi_u 2.29", ABSTRACT_INVENTORY),
        "We obtain 2.29 percent with the Consumer Price Index for All Urban Consumers (CPI-U).",
    ),
    (
        "2020-2025 CPI-U sign as an en dash",
        r"2\.29(\s+)percent",
        "\u20132.29\\1percent",
        ("abstract current projection cpi_u 2.29", ABSTRACT_INVENTORY),
        "We obtain 2.29 percent with the Consumer Price Index for All Urban Consumers (CPI-U).",
    ),
    (
        "2020-2025 CPI-U as a spaced range",
        r"2\.29(\s+)percent",
        "2.20 \u2013 2.29\\1percent",
        ("abstract current projection cpi_u 2.29", ABSTRACT_INVENTORY),
        "We obtain 2.29 percent with the Consumer Price Index for All Urban Consumers (CPI-U).",
    ),
    (
        "2020-2025 CPI-U as a range with to",
        r"2\.29(\s+)percent",
        r"2.20 to 2.29\1percent",
        ("abstract current projection cpi_u 2.29", ABSTRACT_INVENTORY),
        "We obtain 2.29 percent with the Consumer Price Index for All Urban Consumers (CPI-U).",
    ),
    (
        "2020-2025 CPI-U as a range with and",
        r"2\.29(\s+)percent",
        r"2.20 and 2.29\1percent",
        ("abstract current projection cpi_u 2.29", ABSTRACT_INVENTORY),
        "We obtain 2.29 percent with the Consumer Price Index for All Urban Consumers (CPI-U).",
    ),
    (
        "2020-2025 CPI-U as a range with a slash",
        r"2\.29(\s+)percent",
        r"2.20/2.29\1percent",
        ("abstract current projection cpi_u 2.29", ABSTRACT_INVENTORY),
        "We obtain 2.29 percent with the Consumer Price Index for All Urban Consumers (CPI-U).",
    ),
    (
        "2020-2025 CPI-U sign as two hyphens",
        r"2\.29(\s+)percent",
        r"--2.29\1percent",
        ("abstract current projection cpi_u 2.29", ABSTRACT_INVENTORY),
        "We obtain 2.29 percent with the Consumer Price Index for All Urban Consumers (CPI-U).",
    ),
    (
        "blend rule renamed",
        r"latter(\s+)two\.",
        r"first\1two.",
        ("abstract current projection blend 0.90",),
        "We obtain 0.90 percent with an equal blend of the latter two.",
    ),
    (
        "CPI-U rule renamed CPI-W",
        r"All(\s+)Urban(\s+)Consumers(\s+)\(CPI-U\)",
        r"Urban\1Wage\2Earners\3(CPI-W)",
        ("abstract current projection cpi_u 2.29",),
        "We obtain 2.29 percent with the Consumer Price Index for All Urban Consumers (CPI-U).",
    ),
    (
        "2020-2025 composite error",
        r"1\.65(\s+)percent",
        r"1.66\1percent",
        (
            "abstract current projection fcsuti_cpi 1.65",
            "current projection prose fcsuti_cpi",
            ABSTRACT_INVENTORY,
        ),
        "We obtain 1.65 percent with a composite price index.",
    ),
    (
        "2020-2025 replication error",
        r"0\.51(\s+)percent",
        r"0.52\1percent",
        (
            "abstract current projection replication_ratio 0.51",
            "current projection prose replication_ratio",
            ABSTRACT_INVENTORY,
        ),
        "We obtain 0.51 percent with replicated consumption growth.",
    ),
    (
        "2020-2025 blend error",
        r"0\.90(\s+)percent",
        r"0.91\1percent",
        ("abstract current projection blend 0.90", "current projection prose blend", ABSTRACT_INVENTORY),
        "We obtain 0.90 percent with an equal blend of the latter two.",
    ),
    (
        "2025 blend error",
        r"1\.17(\s+)percent",
        r"1.18\1percent",
        ("abstract evaluation amended MAE 1.17", ABSTRACT_INVENTORY),
        "The blend yields a mean absolute error of 1.17 percent.",
    ),
    (
        "2025 CPI-U error",
        r"2\.58(\s+)percent",
        r"2.59\1percent",
        ("abstract evaluation CPI-U MAE 2.58", ABSTRACT_INVENTORY),
        "We obtain 2.58 percent for CPI-U adjustment.",
    ),
    (
        "2025 replication error",
        r"0\.75(\s+)percent",
        r"0.74\1percent",
        ("abstract evaluation replication MAE 0.75", ABSTRACT_INVENTORY),
        "We obtain 0.75 percent for consumption growth alone.",
    ),
    (
        "rule count",
        r"compare(\s+)four(\s+)projection",
        r"compare\1five\2projection",
        ("abstract names the retrospective rules and their count",),
        "We compare four projection rules.",
    ),
    (
        "swapped 2020-2025 errors",
        r"2\.29(.*?)1\.65",
        r"1.65\g<1>2.29",
        (
            "abstract current projection cpi_u 2.29",
            "abstract current projection fcsuti_cpi 1.65",
        ),
        "We obtain 2.29 percent with the Consumer Price Index for All Urban Consumers "
        "(CPI-U) and 1.65 percent with a composite price index.",
    ),
    (
        "swapped 2025 errors",
        r"1\.17(.*?)0\.75",
        r"0.75\g<1>1.17",
        (
            "abstract evaluation amended MAE 1.17",
            "abstract evaluation replication MAE 0.75",
        ),
        "The blend yields a mean absolute error of 1.17 percent, and we obtain "
        "0.75 percent for consumption growth alone.",
    ),
)

# Where a decoy can restate an abstract figure's original wording: under the
# discussion heading, in another front-matter field after the abstract block,
# in body text before the introduction, and as the abstract block's last or
# first line.
ABSTRACT_DECOY_HOSTS = ("discussion", "metadata", "preamble", "abstract", "abstract start")
# Cases that rename a rule, so that the edited sentence states no rate in the
# rule's wording. A copy of the original sentence inside the abstract then
# states the rule's rate correctly, and only the inventory fails, since the
# abstract now states that rate twice.
ABSTRACT_RULE_RENAMES = ("CPI-U rule renamed CPI-W", "blend rule renamed")

# Every tie this file's abstract mutations target.
ABSTRACT_TIE_LABELS = (
    "abstract names the retrospective rules and their count",
    "abstract current projection cpi_u 2.29",
    "abstract current projection fcsuti_cpi 1.65",
    "abstract current projection replication_ratio 0.51",
    "abstract current projection blend 0.90",
    "abstract evaluation amended MAE 1.17",
    "abstract evaluation replication MAE 0.75",
    "abstract evaluation CPI-U MAE 2.58",
    "current projection prose cpi_u",
    "current projection prose fcsuti_cpi",
    "current projection prose replication_ratio",
    "current projection prose blend",
)

# Sentences as the body states them, for decoys to restate under the
# discussion heading. Each carries every literal a whole-paper search would
# look for, so only a tie that reads the right section can still fail.
PINNED_BLOB = (
    "https://github.com/PolicyEngine/spm-threshold-paper/blob/"
    "20bfbe1abcb83b4f9f60fbe54789144321ff62b0/"
)
SENSITIVITY_SENTENCE = (
    "We obtain a maximum threshold change of 1.74 percent when we include "
    "tenure codes 5 and 6 as renters."
)
BENCHMARK_CPI_U = (
    "CPI-U adjustment has a mean absolute error of 2.23 percent and understates "
    "threshold growth in four of five years, with a signed mean error of "
    "−1.9 percent."
)
BENCHMARK_COMPOSITE = (
    "Composite-price adjustment reduces the mean absolute error to 1.57 percent, "
    "removing about thirty percent of the CPI-U error in this sample."
)
BENCHMARK_REPLICATION = (
    "The replication ratio scores 0.41 percent, with a signed mean of +0.1 "
    "percent and annual signed means ranging from +0.5 to −0.3 percent."
)
BENCHMARK_BLEND = (
    "The equal blend scores 0.76 percent; its annual signed means range from "
    "−0.1 to −1.4 percent."
)
NOWCAST_LINK = (
    f"The [forecast record]({PINNED_BLOB}docs/forecast-record.md) links the "
    "August 7 archived page, tags, and timestamp proof that document both "
    "forecasts before BLS’s August 24 publication."
)
NOWCAST_NOTE = (
    "The superseded blend had a mean absolute error of 0.98 percent, compared "
    "with 1.17 percent for the committed blend."
)
NOWCAST_AMOUNTS = (
    "We committed to an equal blend that projected \\$41,036.34 for owners with "
    "mortgages, \\$34,135.99 for owners without mortgages, and \\$40,755.98 for "
    "renters."
)
NOWCAST_GROWTH = (
    "Replicated threshold growth ranged from 4.4 to 6.0 percent by tenure, "
    "against 3.2 percent composite-price growth. Their blend projected 3.8 to "
    "4.6 percent growth, compared with 2.6 percent realized CPI-U growth."
)
EVALUATION_LEVELS = (
    "BLS published the 2025 thresholds on August 24, 2026: \\$41,323 for owners "
    "with mortgages, \\$34,326 for owners without, and \\$41,701 for renters. "
    "The linked workbook carries full-precision values and standard errors of "
    "\\$327, \\$560, and \\$393. BLS reports growth of 4.40 to 6.33 percent by "
    "tenure over the corrected 2024 base."
)
EVALUATION_BLEND = (
    "The committed blend understates the three thresholds by 0.69, 0.55, and "
    "2.27 percent, giving a mean absolute error of 1.17 percent. The signed mean "
    "error also equals −1.17 percent. The owner differences fall within one "
    "published BLS standard error; the renter difference reaches about 2.4 "
    "standard errors."
)
EVALUATION_RULES = (
    "CPI-U adjustment understates all three thresholds by 1.70 to 3.47 percent, "
    "for a mean absolute error of 2.58 percent. The replication ratio alone "
    "scores 0.75 percent and has errors on both sides of zero; composite-price "
    "adjustment scores 2.02 percent."
)
EVALUATION_RENTERS = (
    "BLS reports renter growth of 6.33 percent against 5.33 and 4.40 percent for "
    "the two owner tenures. The blend projects renter growth of 3.92 percent, "
    "and replication alone 4.62 percent."
)
COMPARATOR_GAPS = (
    "The fixed-base composite differs from the BLS index by at most 0.7 "
    "percentage point in each year from 2020 through 2025, with a mean absolute "
    "gap of 0.4 point and no consistent sign."
)
COMPARATOR_CPI_U = (
    "For 2025, the BLS threshold page reports CPI-U growth of 2.70 percent, "
    "and the eleven-month annual average in the pinned CPI observations "
    "implies 2.63 percent."
)
APPENDIX_A_RANGES = (
    "The replication used for the 2025 nowcast has mean absolute deviations "
    "across tenures of 1.5 to 2.1 percent per year against revised 2019–2024 "
    "thresholds, and 1.0 to 1.6 percent against the preceding published series "
    "with its corresponding anchor share. Published BLS sampling standard errors "
    "span 0.7 to 2.1 percent of the revised threshold levels in those years."
)
APPENDIX_B_SOURCES = (
    f"Its [source-data provenance]({PINNED_BLOB}data/PROVENANCE.md) "
    "describes the experimental collections."
)
APPENDIX_B_RECORDS = (
    f"The [data provenance]({PINNED_BLOB}data/PROVENANCE.md) and [forecast "
    f"record]({PINNED_BLOB}docs/forecast-record.md) identify the inputs and "
    "evidence of the earlier experiments, and "
    "[`data/inkind/provenance.json`](https://github.com/PolicyEngine/"
    "spm-threshold-paper/blob/inkind-section-2026-11/data/inkind/provenance.json) "
    "those of the in-kind experiment."
)
APPENDIX_B_REPLAY = (
    "The [experiment replay "
    f"guide]({PINNED_BLOB}docs/reproducing-experiments.md) provides commands "
    "and source-file requirements for raw-data replication."
)
BLS_GROWTH_TIE = "BLS-stated 2025 growth 4.40-6.33 and per-tenure 5.33/4.40/6.33"
INKIND_BLS_GROWTH_TIE = "in-kind prose: evaluation section's BLS growth rates for 2024-2025"
GAP_TIE = "composite within 0.7pp of BLS FCSUti, mean gap 0.4"

# Each case drifts figures in the one body section that states them: (name,
# section, pattern, replacement, failing ties, decoy). The section names a
# mutate_article slice, and the pattern must match exactly once there. With
# the decoy restated under the discussion heading, the failing ties are the
# only lines the guard reports.
SECTION_PROSE_MUTATIONS = (
    (
        "tenure-sensitivity maximum",
        "sensitivity",
        r"1\.74(\s+)percent",
        r"1.75\1percent",
        ("current tenure-sensitivity prose",),
        SENSITIVITY_SENTENCE,
    ),
    (
        "appendix forecast record link",
        "appendix B",
        r"blob/20bfbe1abcb83b4f9f60fbe54789144321ff62b0(/docs/forecast-record\.md)",
        r"blob/main\1",
        ("manuscript links fixed supporting document: docs/forecast-record.md",),
        APPENDIX_B_RECORDS,
    ),
    (
        "appendix source-data provenance link",
        "appendix B",
        r"(source-data\s+provenance\]\(\S+/)blob/20bfbe1abcb83b4f9f60fbe54789144321ff62b0"
        r"(/data/PROVENANCE\.md)",
        r"\1blob/main\2",
        ("manuscript links fixed supporting document: data/PROVENANCE.md",),
        APPENDIX_B_SOURCES,
    ),
    (
        "appendix data provenance link",
        "appendix B",
        r"(\[data\s+provenance\]\(\S+/)blob/20bfbe1abcb83b4f9f60fbe54789144321ff62b0"
        r"(/data/PROVENANCE\.md)",
        r"\1blob/main\2",
        ("manuscript links fixed supporting document: data/PROVENANCE.md",),
        APPENDIX_B_RECORDS,
    ),
    (
        "appendix replay guide link",
        "appendix B",
        r"blob/20bfbe1abcb83b4f9f60fbe54789144321ff62b0(/docs/reproducing-experiments\.md)",
        r"blob/main\1",
        ("manuscript links fixed supporting document: docs/reproducing-experiments.md",),
        APPENDIX_B_REPLAY,
    ),
    (
        "appendix replay guide gains an anchored link at main",
        "appendix B",
        r"(docs/reproducing-experiments\.md\))",
        r"\1 ([setup](https://github.com/PolicyEngine/spm-threshold-paper/blob/main/"
        r"docs/reproducing-experiments.md#L1))",
        ("manuscript links fixed supporting document: docs/reproducing-experiments.md",),
        APPENDIX_B_REPLAY,
    ),
    (
        "appendix forecast record loses its link",
        "appendix B",
        r"\[(forecast\s+record)\]\(\S+/docs/forecast-record\.md\)",
        r"\1",
        ("manuscript links fixed supporting document: docs/forecast-record.md",),
        APPENDIX_B_RECORDS,
    ),
    (
        "appendix replay guide loses its link",
        "appendix B",
        r"\[(experiment replay\s+guide)\]\(\S+/docs/reproducing-experiments\.md\)",
        r"\1",
        ("manuscript links fixed supporting document: docs/reproducing-experiments.md",),
        APPENDIX_B_REPLAY,
    ),
    (
        "nowcast forecast record link",
        "nowcast",
        r"blob/20bfbe1abcb83b4f9f60fbe54789144321ff62b0(/docs/forecast-record\.md)",
        r"blob/main\1",
        ("nowcast section links to the fixed forecast registration record",),
        NOWCAST_LINK,
    ),
    (
        "committed owner-with-mortgage amount",
        "nowcast",
        r"41,036\.34",
        "41,036.43",
        (
            "nowcast literal 41,036.34",
            "committed estimate states the amended triple in tenure order",
        ),
        NOWCAST_AMOUNTS,
    ),
    (
        "committed owner-without-mortgage amount",
        "nowcast",
        r"34,135\.99",
        "34,135.98",
        (
            "nowcast literal 34,135.99",
            "committed estimate states the amended triple in tenure order",
        ),
        NOWCAST_AMOUNTS,
    ),
    (
        "committed renter amount",
        "nowcast",
        r"40,755\.98",
        "40,755.89",
        (
            "nowcast literal 40,755.98",
            "committed estimate states the amended triple in tenure order",
        ),
        NOWCAST_AMOUNTS,
    ),
    (
        "swapped committed owner amounts",
        "nowcast",
        r"41,036\.34(.*?)34,135\.99",
        r"34,135.99\g<1>41,036.34",
        ("committed estimate states the amended triple in tenure order",),
        NOWCAST_AMOUNTS,
    ),
    (
        "replicated growth range",
        "nowcast",
        r"4\.4(\s+)to(\s+)6\.0",
        r"4.4\1to\g<2>6.1",
        ("replication growth 4.4 to 6.0",),
        NOWCAST_GROWTH,
    ),
    (
        "composite-price growth",
        "nowcast",
        r"3\.2(\s+)percent",
        r"3.3\1percent",
        ("price growth 3.2",),
        NOWCAST_GROWTH,
    ),
    (
        "projected blend growth range",
        "nowcast",
        r"3\.8(\s+)to(\s+)4\.6",
        r"3.8\1to\g<2>4.7",
        ("blend growth 3.8 to 4.6",),
        NOWCAST_GROWTH,
    ),
    (
        "realized CPI-U growth",
        "nowcast",
        r"2\.6(\s+)percent(\s+)realized",
        r"2.7\1percent\2realized",
        ("realized CPI-U 2025 growth 2.6",),
        NOWCAST_GROWTH,
    ),
    (
        "swapped composite-price and realized CPI-U growth",
        "nowcast",
        r"3\.2(\s+)percent(\s+)composite-price(.*?)2\.6(\s+)percent",
        r"2.6\1percent\2composite-price\g<3>3.2\4percent",
        ("price growth 3.2", "realized CPI-U 2025 growth 2.6"),
        NOWCAST_GROWTH,
    ),
    (
        "superseded blend error",
        "nowcast",
        r"0\.98(\s+)percent",
        r"0.99\1percent",
        ("forecast record evaluation original MAE 0.98",),
        NOWCAST_NOTE,
    ),
    (
        "committed blend error in the nowcast note",
        "nowcast",
        r"1\.17(\s+)percent(\s+)for(\s+)the",
        r"1.18\1percent\2for\3the",
        ("nowcast evaluation amended MAE 1.17",),
        NOWCAST_NOTE,
    ),
    (
        "CPI-U benchmark error",
        "benchmark",
        r"2\.23(\s+)percent",
        r"2.32\1percent",
        ("backtest prose literal 2.23",),
        BENCHMARK_CPI_U,
    ),
    (
        "composite benchmark error",
        "benchmark",
        r"1\.57(\s+)percent",
        r"1.58\1percent",
        ("backtest prose literal 1.57",),
        BENCHMARK_COMPOSITE,
    ),
    (
        "replication benchmark error",
        "benchmark",
        r"0\.41(\s+)percent",
        r"0.42\1percent",
        ("backtest prose literal 0.41",),
        BENCHMARK_REPLICATION,
    ),
    (
        "blend benchmark error",
        "benchmark",
        r"0\.76(\s+)percent",
        r"0.67\1percent",
        ("backtest prose literal 0.76",),
        BENCHMARK_BLEND,
    ),
    (
        "swapped CPI-U and composite benchmark errors",
        "benchmark",
        r"2\.23(\s+)percent(.*?)1\.57(\s+)percent",
        r"1.57\1percent\g<2>2.23\3percent",
        ("backtest prose literal 2.23", "backtest prose literal 1.57"),
        BENCHMARK_CPI_U + " " + BENCHMARK_COMPOSITE,
    ),
    (
        "CPI-U signed benchmark error",
        "benchmark",
        r"−1\.9(\s+)percent",
        r"−2.9\1percent",
        ("signed CPI-U bias -1.9",),
        BENCHMARK_CPI_U,
    ),
    (
        "CPI-U signed benchmark error sign",
        "benchmark",
        r"−1\.9",
        "+1.9",
        ("signed CPI-U bias -1.9",),
        BENCHMARK_CPI_U,
    ),
    (
        "CPI-U understated years",
        "benchmark",
        r"in(\s+)four(\s+)of(\s+)five",
        r"in\1three\2of\3five",
        ("CPI-U understated four of five years",),
        BENCHMARK_CPI_U,
    ),
    (
        "share of CPI-U error the composite removes",
        "benchmark",
        r"about(\s+)thirty(\s+)percent",
        r"about\1forty\2percent",
        ("composite removes ~thirty percent of CPI-U error",),
        BENCHMARK_COMPOSITE,
    ),
    (
        "replication signed benchmark mean",
        "benchmark",
        r"\+0\.1(\s+)percent",
        r"+0.2\1percent",
        ("replication signed mean +0.1",),
        BENCHMARK_REPLICATION,
    ),
    (
        "replication annual signed range",
        "benchmark",
        r"\+0\.5(\s+)to(\s+)−0\.3",
        r"+0.5\1to\2−0.4",
        ("replication annual signed range +0.5 to −0.3",),
        BENCHMARK_REPLICATION,
    ),
    (
        "blend annual signed range",
        "benchmark",
        r"−0\.1(\s+)to(\s+)−1\.4",
        r"−0.1\1to\2−1.5",
        ("blend annual signed range −0.1 to −1.4",),
        BENCHMARK_BLEND,
    ),
    (
        "swapped annual signed ranges",
        "benchmark",
        r"\+0\.5(\s+)to(\s+)−0\.3(.*?)−0\.1(\s+)to(\s+)−1\.4",
        r"−0.1\1to\2−1.4\g<3>+0.5\4to\5−0.3",
        (
            "replication annual signed range +0.5 to −0.3",
            "blend annual signed range −0.1 to −1.4",
        ),
        BENCHMARK_REPLICATION + " " + BENCHMARK_BLEND,
    ),
    (
        "benchmark standard-error floor",
        "appendix A",
        r"span(\s+)0\.7",
        r"span\g<1>0.8",
        ("SE range 0.7 to 2.1 percent",),
        APPENDIX_A_RANGES,
    ),
    (
        "benchmark standard-error ceiling",
        "appendix A",
        r"0\.7(\s+)to(\s+)2\.1",
        r"0.7\1to\g<2>2.2",
        ("SE range 0.7 to 2.1 percent",),
        APPENDIX_A_RANGES,
    ),
    (
        "replication fidelity against revised thresholds",
        "appendix A",
        r"1\.5(\s+)to(\s+)2\.1",
        r"1.5\1to\g<2>2.2",
        ("replication fidelity 1.5 to 2.1 vs corrected",),
        APPENDIX_A_RANGES,
    ),
    (
        "replication fidelity against the published series",
        "appendix A",
        r"1\.0(\s+)to(\s+)1\.6",
        r"0.9\1to\g<2>1.6",
        ("replication fidelity 1.0 to 1.6 vs published",),
        APPENDIX_A_RANGES,
    ),
    (
        "swapped replication fidelity ranges",
        "appendix A",
        r"1\.5(\s+)to(\s+)2\.1(.*?)1\.0(\s+)to(\s+)1\.6",
        r"1.0\1to\g<2>1.6\g<3>1.5\4to\g<5>2.1",
        (
            "replication fidelity 1.5 to 2.1 vs corrected",
            "replication fidelity 1.0 to 1.6 vs published",
        ),
        APPENDIX_A_RANGES,
    ),
    (
        "committed blend evaluation error",
        "evaluation",
        r"error(\s+)of(\s+)1\.17",
        r"error\1of\g<2>1.18",
        ("evaluation amended MAE 1.17",),
        EVALUATION_BLEND,
    ),
    (
        "CPI-U evaluation error",
        "evaluation",
        r"error(\s+)of(\s+)2\.58",
        r"error\1of\g<2>2.59",
        ("evaluation CPI-U MAE 2.58",),
        EVALUATION_RULES,
    ),
    (
        "replication evaluation error",
        "evaluation",
        r"scores(\s+)0\.75",
        r"scores\g<1>0.74",
        ("evaluation replication MAE 0.75",),
        EVALUATION_RULES,
    ),
    (
        "composite evaluation error",
        "evaluation",
        r"scores(\s+)2\.02",
        r"scores\g<1>2.03",
        ("evaluation composite MAE 2.02",),
        EVALUATION_RULES,
    ),
    (
        "swapped replication and composite evaluation errors",
        "evaluation",
        r"scores(\s+)0\.75(.*?)scores(\s+)2\.02",
        r"scores\g<1>2.02\g<2>scores\g<3>0.75",
        ("evaluation replication MAE 0.75", "evaluation composite MAE 2.02"),
        EVALUATION_RULES,
    ),
    (
        "owner-with-mortgage miss",
        "evaluation",
        r"by(\s+)0\.69,",
        r"by\g<1>0.96,",
        ("evaluation per-tenure misses 0.69, 0.55, 2.27 in order",),
        EVALUATION_BLEND,
    ),
    (
        "owner-without-mortgage miss",
        "evaluation",
        r"0\.69,(\s+)0\.55",
        r"0.69,\g<1>0.56",
        ("evaluation per-tenure misses 0.69, 0.55, 2.27 in order",),
        EVALUATION_BLEND,
    ),
    (
        "renter miss",
        "evaluation",
        r"and(\s+)2\.27",
        r"and\g<1>2.28",
        ("evaluation per-tenure misses 0.69, 0.55, 2.27 in order",),
        EVALUATION_BLEND,
    ),
    (
        "swapped owner misses",
        "evaluation",
        r"0\.69,(\s+)0\.55",
        r"0.55,\g<1>0.69",
        ("evaluation per-tenure misses 0.69, 0.55, 2.27 in order",),
        EVALUATION_BLEND,
    ),
    (
        "signed evaluation mean",
        "evaluation",
        r"−1\.17",
        "−1.18",
        ("evaluation signed mean −1.17",),
        EVALUATION_BLEND,
    ),
    (
        "CPI-U understatement range",
        "evaluation",
        r"1\.70(\s+)to(\s+)3\.47",
        r"1.70\1to\g<2>3.48",
        ("CPI-U 2025 understated every tenure by 1.70 to 3.47 percent",),
        EVALUATION_RULES,
    ),
    (
        "BLS owner-with-mortgage threshold",
        "evaluation",
        r"41,323",
        "41,332",
        ("BLS 2025 literal 41,323", "BLS 2025 triple in tenure order"),
        EVALUATION_LEVELS,
    ),
    (
        "BLS owner-without-mortgage threshold",
        "evaluation",
        r"34,326",
        "34,362",
        ("BLS 2025 literal 34,326", "BLS 2025 triple in tenure order"),
        EVALUATION_LEVELS,
    ),
    (
        "BLS renter threshold",
        "evaluation",
        r"41,701",
        "41,710",
        ("BLS 2025 literal 41,701", "BLS 2025 triple in tenure order"),
        EVALUATION_LEVELS,
    ),
    (
        "BLS growth range floor",
        "evaluation",
        r"growth(\s+)of(\s+)4\.40(\s+)to",
        r"growth\1of\g<2>4.41\3to",
        (BLS_GROWTH_TIE,),
        EVALUATION_LEVELS,
    ),
    (
        "BLS growth range ceiling",
        "evaluation",
        r"4\.40(\s+)to(\s+)6\.33",
        r"4.40\1to\g<2>6.34",
        (BLS_GROWTH_TIE,),
        EVALUATION_LEVELS,
    ),
    (
        "BLS renter growth",
        "evaluation",
        r"renter(\s+)growth(\s+)of(\s+)6\.33",
        r"renter\1growth\2of\g<3>6.38",
        (BLS_GROWTH_TIE, INKIND_BLS_GROWTH_TIE),
        EVALUATION_RENTERS,
    ),
    (
        "BLS owner-with-mortgage growth",
        "evaluation",
        r"against(\s+)5\.33",
        r"against\g<1>5.34",
        (BLS_GROWTH_TIE, INKIND_BLS_GROWTH_TIE),
        EVALUATION_RENTERS,
    ),
    (
        "BLS owner-without-mortgage growth",
        "evaluation",
        r"and(\s+)4\.40(\s+)percent",
        r"and\g<1>4.41\2percent",
        (BLS_GROWTH_TIE, INKIND_BLS_GROWTH_TIE),
        EVALUATION_RENTERS,
    ),
    (
        "projected renter growth",
        "evaluation",
        r"growth(\s+)of(\s+)3\.92",
        r"growth\1of\g<2>3.93",
        ("nowcast renter growth 3.92",),
        EVALUATION_RENTERS,
    ),
    (
        "replication renter growth",
        "evaluation",
        r"alone(\s+)4\.62",
        r"alone\g<1>4.63",
        ("replication renter growth 4.62",),
        EVALUATION_RENTERS,
    ),
    (
        "swapped projected and replication renter growth",
        "evaluation",
        r"3\.92(\s+)percent,(\s+)and(\s+)replication(\s+)alone(\s+)4\.62",
        r"4.62\1percent,\2and\3replication\4alone\g<5>3.92",
        ("nowcast renter growth 3.92", "replication renter growth 4.62"),
        EVALUATION_RENTERS,
    ),
    (
        "renter miss in standard errors",
        "evaluation",
        r"about(\s+)2\.4(\s+)standard",
        r"about\g<1>2.5\2standard",
        ("owner misses within one SE; renter about 2.4 SE",),
        EVALUATION_BLEND,
    ),
    (
        "owner misses in standard errors",
        "evaluation",
        r"within(\s+)one(\s+)published",
        r"within\1two\2published",
        ("owner misses within one SE; renter about 2.4 SE",),
        EVALUATION_BLEND,
    ),
    (
        "renter miss split across two lines",
        "evaluation",
        r"2\.4 standard",
        "2.4\nstandard",
        ("owner misses within one SE; renter about 2.4 SE",),
        EVALUATION_BLEND,
    ),
    (
        "committed amounts split across two lines",
        "nowcast",
        r"for owners with mortgages,",
        "for owners\nwith mortgages,",
        ("committed estimate states the amended triple in tenure order",),
        NOWCAST_AMOUNTS,
    ),
    (
        "BLS levels split across two lines",
        "evaluation",
        r"owners with mortgages, (\\\$34,326)",
        r"owners\nwith mortgages, \1",
        ("BLS 2025 triple in tenure order",),
        EVALUATION_LEVELS,
    ),
    (
        "evaluation misses pushed onto an indented line",
        "evaluation",
        r"and\n2\.27 percent",
        "and\n" + " " * 21 + "2.27 percent",
        ("evaluation per-tenure misses 0.69, 0.55, 2.27 in order",),
        EVALUATION_BLEND,
    ),
    (
        "sensitivity maximum split across two lines",
        "sensitivity",
        r"1\.74 percent",
        "1.74\npercent",
        ("current tenure-sensitivity prose",),
        SENSITIVITY_SENTENCE,
    ),
    (
        "benchmark year count split across two lines",
        "benchmark",
        r"in four of five years",
        "in four\nof five years",
        ("CPI-U understated four of five years",),
        BENCHMARK_CPI_U,
    ),
    (
        "comparator mean gap split across two lines",
        "price",
        r"gap of 0\.4 point",
        "gap of 0.4\npoint",
        ("composite within 0.7pp of BLS FCSUti, mean gap 0.4",),
        COMPARATOR_GAPS,
    ),
    (
        "fidelity range split across two lines",
        "appendix A",
        r"of 1\.5 to 2\.1 percent",
        "of 1.5 to\n2.1 percent",
        ("replication fidelity 1.5 to 2.1 vs corrected",),
        APPENDIX_A_RANGES,
    ),
    (
        "owner-with-mortgage standard error",
        "evaluation",
        r"\\\$327",
        r"\\$372",
        ("2025 SE literal 327", "2025 SE triple in tenure order"),
        EVALUATION_LEVELS,
    ),
    (
        "owner-without-mortgage standard error",
        "evaluation",
        r"\\\$560",
        r"\\$506",
        ("2025 SE literal 560", "2025 SE triple in tenure order"),
        EVALUATION_LEVELS,
    ),
    (
        "renter standard error",
        "evaluation",
        r"\\\$393",
        r"\\$339",
        ("2025 SE literal 393", "2025 SE triple in tenure order"),
        EVALUATION_LEVELS,
    ),
    (
        "swapped owner standard errors",
        "evaluation",
        r"\\\$327,(\s+)\\\$560",
        r"\\$560,\1\\$327",
        ("2025 SE triple in tenure order",),
        EVALUATION_LEVELS,
    ),
    (
        "largest comparator gap",
        "price",
        r"most(\s+)0\.7(\s+)percentage",
        r"most\g<1>0.8\2percentage",
        (GAP_TIE,),
        COMPARATOR_GAPS,
    ),
    (
        "mean comparator gap",
        "price",
        r"gap(\s+)of(\s+)0\.4(\s+)point",
        r"gap\1of\g<2>0.5\3point",
        (GAP_TIE,),
        COMPARATOR_GAPS,
    ),
    (
        "BLS-page CPI-U growth",
        "price",
        r"2\.70(\s+)percent",
        r"2.71\1percent",
        ("BLS page 2025 CPI-U growth 2.70 quoted",),
        COMPARATOR_CPI_U,
    ),
    (
        "eleven-month CPI-U growth",
        "price",
        r"2\.63(\s+)percent",
        r"2.64\1percent",
        ("eleven-month CPI-U growth 2.63 quoted",),
        COMPARATOR_CPI_U,
    ),
    (
        "swapped CPI-U growth figures",
        "price",
        r"2\.70(\s+)percent(.*?)2\.63(\s+)percent",
        r"2.63\1percent\g<2>2.70\3percent",
        (
            "BLS page 2025 CPI-U growth 2.70 quoted",
            "eleven-month CPI-U growth 2.63 quoted",
        ),
        COMPARATOR_CPI_U,
    ),
)

# Each case renames or repeats a heading that bounds a section slice:
# (name, edits, ties that must fail). A renamed, repeated or reordered
# heading empties every slice it bounds, and a run-on heading empties the
# slice on the side it runs into, so the guard names the heading and fails
# that section's ties instead of searching anywhere else. Each heading that
# bounds the slices for sections 3.2, 5.3, 6.1, 6.2 and 6.3, the rolling
# section and its two subsections, or either appendix appears in at least
# one case.
SECTION_MARKER_CASES = (
    (
        "renamed sensitivity heading",
        (
            (
                "## Replicated levels and sample sensitivities\n",
                "## Replicated levels and sensitivities\n",
            ),
        ),
        (
            "paper section heading not unique: "
            "'## Replicated levels and sample sensitivities' occurs 0 times",
            "current tenure-sensitivity prose",
        ),
    ),
    (
        "repeated in-kind heading",
        (
            (
                DISCUSSION_HEADING,
                "# Home internet and in-kind benefits {#sec-inkind}\n\n" + DISCUSSION_HEADING,
            ),
        ),
        (
            "paper section heading not unique: "
            "'# Home internet and in-kind benefits {#sec-inkind}' occurs 2 times",
            "current tenure-sensitivity prose",
        ),
    ),
    (
        "renamed benchmark heading",
        (("## Five-year benchmark for the 2025 nowcast\n", "## Five-year benchmark\n"),),
        (
            "paper section heading not unique: "
            "'## Five-year benchmark for the 2025 nowcast' occurs 0 times",
            "backtest prose literal 2.23",
            "signed CPI-U bias -1.9",
        ),
    ),
    (
        "benchmark heading runs into the text after it",
        (
            (
                "## Five-year benchmark for the 2025 nowcast\n",
                "## Five-year benchmark for the 2025 nowcasts\n",
            ),
        ),
        (
            "paper section heading runs into the text after it: "
            "'## Five-year benchmark for the 2025 nowcast'",
            "backtest prose literal 2.23",
        ),
    ),
    (
        "renamed nowcast heading",
        (
            (
                "# Pre-committed 2025 validation {#sec-nowcast}\n",
                "# Pre-registered 2025 validation {#sec-nowcast}\n",
            ),
        ),
        (
            "paper section heading not unique: '# Pre-committed 2025 validation' occurs 0 times",
            "nowcast section links to the fixed forecast registration record",
            "nowcast literal 41,036.34",
            "price growth 3.2",
            "backtest prose literal 2.23",
        ),
    ),
    (
        "nowcast and evaluation headings swapped",
        (
            ("# Pre-committed 2025 validation {#sec-nowcast}\n", "NOWCAST HEADING\n"),
            (
                "## Evaluation against published thresholds {#sec-evaluation}\n",
                "# Pre-committed 2025 validation {#sec-nowcast}\n",
            ),
            ("NOWCAST HEADING\n", "## Evaluation against published thresholds {#sec-evaluation}\n"),
        ),
        (
            "paper sections out of order: "
            "'# Pre-committed 2025 validation' before '## Evaluation against published thresholds'",
            "nowcast literal 41,036.34",
        ),
    ),
    (
        "repeated evaluation heading",
        (
            (
                DISCUSSION_HEADING,
                "## Evaluation against published thresholds {#sec-evaluation}\n\n"
                + DISCUSSION_HEADING,
            ),
        ),
        (
            "paper section heading not unique: "
            "'## Evaluation against published thresholds {#sec-evaluation}' occurs 2 times",
            "paper section heading not unique: "
            "'## Evaluation against published thresholds' occurs 2 times",
            "evaluation amended MAE 1.17",
            "2025 SE triple in tenure order",
            "nowcast literal 41,036.34",
        ),
    ),
    (
        "repeated comparator heading",
        ((DISCUSSION_HEADING, "## Validation of the price comparator\n\n" + DISCUSSION_HEADING),),
        (
            "paper section heading not unique: "
            "'## Validation of the price comparator' occurs 2 times",
            GAP_TIE,
            "BLS page 2025 CPI-U growth 2.70 quoted",
            "evaluation amended MAE 1.17",
        ),
    ),
    (
        "repeated forecasts heading",
        (
            (
                DISCUSSION_HEADING,
                "# Conditional forecasts beyond available microdata {#sec-rolling}\n\n"
                + DISCUSSION_HEADING,
            ),
        ),
        (
            "paper section heading not unique: "
            "'# Conditional forecasts beyond available microdata {#sec-rolling}' occurs 2 times",
            GAP_TIE,
            "BLS page 2025 CPI-U growth 2.70 quoted",
        ),
    ),
    (
        "renamed appendix A heading",
        (
            (
                "# Appendix A: replication benchmark {.unnumbered}\n",
                "# Appendix A: benchmark {.unnumbered}\n",
            ),
        ),
        (
            "paper section heading not unique: "
            "'# Appendix A: replication benchmark {.unnumbered}' occurs 0 times",
            "SE range 0.7 to 2.1 percent",
            "replication fidelity 1.5 to 2.1 vs corrected",
        ),
    ),
    (
        "renamed appendix B heading",
        (
            (
                "# Appendix B: reproducibility {.unnumbered}\n",
                "# Appendix B: replication {.unnumbered}\n",
            ),
        ),
        (
            "paper section heading not unique: "
            "'# Appendix B: reproducibility {.unnumbered}' occurs 0 times",
            "manuscript links fixed supporting document: docs/forecast-record.md",
            "SE range 0.7 to 2.1 percent",
        ),
    ),
    (
        "repeated references heading",
        ((DISCUSSION_HEADING, "# References {.unnumbered}\n\n" + DISCUSSION_HEADING),),
        (
            "paper section heading not unique: '# References {.unnumbered}' occurs 2 times",
            "manuscript links fixed supporting document: docs/forecast-record.md",
        ),
    ),
    (
        "references heading joined to the text before it",
        (("# References {.unnumbered}", "See below.# References {.unnumbered}"),),
        (
            "paper section text runs into the heading after it: '# References {.unnumbered}'",
            "manuscript links fixed supporting document: docs/forecast-record.md",
        ),
    ),
    (
        "appendix B heading restated with a suffix",
        ((DISCUSSION_HEADING, "# Appendix B: reproducibility (continued)\n\n" + DISCUSSION_HEADING),),
        (
            "paper section heading not unique: '# Appendix B: reproducibility' occurs 2 times",
            "manuscript links fixed supporting document: docs/forecast-record.md",
        ),
    ),
    (
        "references heading restated with a suffix",
        ((DISCUSSION_HEADING, "# References (continued)\n\n" + DISCUSSION_HEADING),),
        (
            "paper section heading not unique: '# References' occurs 2 times",
            "manuscript links fixed supporting document: docs/forecast-record.md",
        ),
    ),
    (
        "renamed rolling expenditure heading",
        (
            (
                "## Projecting expenditure records and rolling windows\n",
                "## Projecting expenditure records\n",
            ),
        ),
        (
            "paper section heading not unique: "
            "'## Projecting expenditure records and rolling windows' occurs 0 times",
            "rolling real-growth sensitivities in stated order with their block counts",
        ),
    ),
    (
        "repeated rolling housing-cost heading",
        ((DISCUSSION_HEADING, "## Projecting local relative housing costs\n\n" + DISCUSSION_HEADING),),
        (
            "paper section heading not unique: '## Projecting local relative housing costs' occurs 2 times",
            "rolling real-growth sensitivities in stated order with their block counts",
            "rolling geographic validation covers 341 anchored areas",
        ),
    ),
    (
        "repeated discussion heading",
        ((DISCUSSION_HEADING, DISCUSSION_HEADING + "\n" + DISCUSSION_HEADING),),
        (
            "paper section heading not unique: '# Discussion {#sec-discussion}' occurs 2 times",
            "no text to slice for paper section '## Projecting expenditure records and rolling windows'",
            "no text to slice for paper section '## Projecting local relative housing costs'",
            "rolling real-growth sensitivities in stated order with their block counts",
            "in-kind prose: discussion home internet and in-kind lift ranges",
            "in-kind prose: discussion growth changes from home internet and the benefits",
        ),
    ),
)

# The in-kind ties that read the abstract, labeled as the guard reports them.
INKIND_ABSTRACT_TIE_LABELS = (
    "in-kind prose: abstract in-kind lift range",
    "in-kind prose: abstract home internet lift range",
    "in-kind prose: abstract and discussion: each change within one standard error",
    "in-kind prose: abstract and discussion: the accounting's shares",
    "in-kind prose: abstract stage-change range",
)


# Each literal with a space in it that a tie searches one of the six section
# slices' raw text for: the section the slice covers, the literal and the
# tie's label.
RAW_LITERALS = (
    ("sensitivity", "1.74 percent", "current tenure-sensitivity prose"),
    ("benchmark", "error of −1.9 percent", "signed CPI-U bias -1.9"),
    ("benchmark", "four of five", "CPI-U understated four of five years"),
    ("benchmark", "thirty percent", "composite removes ~thirty percent of CPI-U error"),
    ("benchmark", "+0.5 to −0.3", "replication annual signed range +0.5 to −0.3"),
    ("benchmark", "−0.1 to −1.4", "blend annual signed range −0.1 to −1.4"),
    ("nowcast", "owners with", "committed estimate states the amended triple in tenure order"),
    ("nowcast", "owners without", "committed estimate states the amended triple in tenure order"),
    ("nowcast", "4.4 to 6.0", "replication growth 4.4 to 6.0"),
    ("nowcast", "3.2 percent", "price growth 3.2"),
    ("nowcast", "3.8 to 4.6", "blend growth 3.8 to 4.6"),
    ("nowcast", "2.6 percent", "realized CPI-U 2025 growth 2.6"),
    ("evaluation", "1.70 to 3.47 percent", "CPI-U 2025 understated every tenure by 1.70 to 3.47 percent"),
    ("evaluation", "owners with", "BLS 2025 triple in tenure order"),
    ("evaluation", "owners without", "BLS 2025 triple in tenure order"),
    ("evaluation", "4.40 to 6.33", "BLS-stated 2025 growth 4.40-6.33 and per-tenure 5.33/4.40/6.33"),
    ("evaluation", "2.4 standard errors", "owner misses within one SE; renter about 2.4 SE"),
    ("price", "0.7 percentage point", "composite within 0.7pp of BLS FCSUti, mean gap 0.4"),
    ("price", "0.4 point", "composite within 0.7pp of BLS FCSUti, mean gap 0.4"),
    ("price", "2.70 percent", "BLS page 2025 CPI-U growth 2.70 quoted"),
    ("appendix A", "1.5 to 2.1", "replication fidelity 1.5 to 2.1 vs corrected"),
    ("appendix A", "1.0 to 1.6", "replication fidelity 1.0 to 1.6 vs published"),
)


def whitespace_papers():
    """The papers the whitespace test builds for each spacer, as (name,
    rows) pairs. Each row names a section, a literal, its tie and the
    positions, counted from 1, of the literal's spaces that the paper
    respaces. A tie fails when any one of its literals fails, and a literal
    when any one of its spaces does, so when a paper respaces two spaces of
    one tie, the failure at one hides a mapping at the other. One paper
    respaces every space of every literal, for a mapping that needs them
    all. After it, each round takes the k-th literal of each tie whole and
    then one space position at a time. These papers miss a set of a tie's
    spaces when none of them respaces that set and no other space of the
    tie. The last papers take the missed sets, the k-th of them each tie's
    k-th missed set, so that for each nonempty set of a tie's spaces, some
    paper respaces that set and no other space of the tie. A paper that
    repeats an earlier one drops out. The sensitivity section gets papers
    of its own: its tie runs among the guard's input checks, and when an
    input check fails, the guard exits before the later ties run."""
    ordinals = ("first", "second", "third")
    positions = {literal: tuple(range(1, literal.count(" ") + 1)) for _, literal, _ in RAW_LITERALS}
    rounds = [("every literal", [(where, literal, label, positions[literal]) for where, literal, label in RAW_LITERALS])]
    layers, counts = {}, {}
    for where, literal, label in RAW_LITERALS:
        counts[label] = counts.get(label, 0) + 1
        layers.setdefault(counts[label], []).append((where, literal, label))
    for k, rows in sorted(layers.items()):
        rounds.append((f"{ordinals[k - 1]} literals", [(where, literal, label, positions[literal]) for where, literal, label in rows]))
        for space in range(1, max(len(positions[literal]) for _, literal, _ in rows) + 1):
            rounds.append((
                f"{ordinals[k - 1]} literals, space {space}",
                [(where, literal, label, (space,)) for where, literal, label in rows if len(positions[literal]) >= space],
            ))
    papers, seen = [], set()

    def add(name, rows):
        for group in ([row for row in rows if row[0] == "sensitivity"], [row for row in rows if row[0] != "sensitivity"]):
            if group and frozenset(group) not in seen:
                seen.add(frozenset(group))
                papers.append((name, group))

    for name, rows in rounds:
        add(name, rows)
    # Each tie's spaces as (section, literal, position), and, for each tie,
    # the sets of its spaces that some paper respaces with no other space of
    # the tie.
    spaces = {}
    for where, literal, label in RAW_LITERALS:
        spaces.setdefault(label, []).extend((where, literal, position) for position in positions[literal])
    met = {label: set() for label in spaces}
    for _, rows in papers:
        for label in met:
            chosen = frozenset((where, literal, position) for where, literal, tie, held in rows if tie == label for position in held)
            if chosen:
                met[label].add(chosen)
    missing = {
        label: [
            chosen
            for size in range(1, len(tie) + 1)
            for chosen in map(frozenset, itertools.combinations(tie, size))
            if chosen not in met[label]
        ]
        for label, tie in spaces.items()
    }
    for k in range(max(map(len, missing.values()))):
        rows = []
        for label, sets in missing.items():
            if k < len(sets):
                held = {}
                for where, literal, position in sorted(sets[k]):
                    held.setdefault((where, literal), []).append(position)
                rows.extend((where, literal, label, tuple(chosen)) for (where, literal), chosen in held.items())
        add(f"combinations {k + 1}", rows)
    return papers


# Whitespace that breaks a raw literal's single space and that normalized()
# collapses back to one space: a doubled space, a line break, a no-break
# space, a tab and a line break before an indented line.
SPACINGS = ("  ", "\n", "\u00a0", "\t", "\n ")


def failure_lines(stdout):
    """The labels the guard lists as failures, one per line."""
    return [line[4:] for line in stdout.splitlines() if line.startswith("  - ")]


def reflect_replicates(uncertainty, year):
    """Mirror each of one year's replicate thresholds around its full-sample
    value, with and without the benefits, in both runs. Every squared
    deviation, and so every threshold's standard error, stays the same. The
    lift is a ratio of thresholds, so reflection moves its variance; reseal
    the recorded lift as a forger would."""
    inkind = load_inkind_module()
    for run in uncertainty["runs"].values():
        replicates = run["years"][year]["replicates"]
        series = list(replicates["without_in_kind"].values())
        series += [draw for draws in replicates["with_in_kind"].values() for draw in draws]
        for values in series:
            values[1:] = [2 * values[0] - value for value in values[1:]]
        for tenure, without in replicates["without_in_kind"].items():
            lifts = [
                [inkind._growth(w, v) for w, v in zip(without, draw)]
                for draw in replicates["with_in_kind"][tenure]
            ]
            run["years"][year]["in_kind_lift_percent"][tenure].update(inkind._rubin(lifts))


def load_inkind_module():
    """Load scripts/inkind_inputs.py for its growth and Rubin helpers."""
    spec = importlib.util.spec_from_file_location(
        "paper_guard_inkind_inputs", REPO / "scripts/inkind_inputs.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def excluded_diagnostic(path):
    """Do not read or copy private worker diagnostics into test fixtures."""
    return str(path).endswith((".err", ".lane.log"))


def load_bounded():
    """Extract bounded() from scripts/check_paper.py, which runs its checks
    at import, so the test can call it on text it constructs."""
    tree = ast.parse((REPO / "scripts/check_paper.py").read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "bounded")
    namespace = {"re": re}
    exec(compile(ast.Module([function], []), "check_paper.bounded", "exec"), namespace)
    return namespace["bounded"]


class BoundedLiteralTests(unittest.TestCase):
    """bounded() keeps a pin's literal from matching inside a longer token."""

    CASES = (
        ("six states whose", "including in six states whose", True),
        ("six states whose", "including in twenty-six states whose", False),
        ("six states whose", "including in twenty\u2010six states whose", False),
        ("six states whose", "including in twenty\u2011six states whose", False),
        ("one of the five recipients", "the amount of one of the five recipients", True),
        ("one of the five recipients", "the amount of none of the five recipients", False),
        ("one of the five recipients", "the amount of twenty-one of the five recipients", False),
        ("five", "twenty\u2011five", False),
        ("five", "\u00e9five", False),
        ("in 2025", "\u00e9in 2025", False),
        ("in 2025", "units in 2025.", True),
        ("Garner", "the Garner–Munoz restrictions", True),
        ("1.9 percent", "an error of 11.9 percent", False),
        ("error of −1.9 percent", "a mean error of +1.9 percent", False),
        ('"Total Internet Share"', 'and "Total Internet Share" in 2025', True),
        ("(@sec-inkind-bls)", "as we report (@sec-inkind-bls).", True),
    )

    def test_literals_match_only_whole_tokens(self):
        bounded = load_bounded()
        for literal, text, expected in self.CASES:
            with self.subTest(literal=literal, text=text):
                self.assertEqual(bool(re.search(bounded(literal), text)), expected)


class PaperGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="spm-paper-test-")
        self.repo = Path(self.temp.name) / "paper"
        subprocess.run(
            [
                "git",
                "clone",
                "--quiet",
                "--shared",
                "--no-checkout",
                str(REPO),
                str(self.repo),
            ],
            check=True,
            capture_output=True,
        )
        names = (
            subprocess.check_output(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                cwd=REPO,
            )
            .decode()
            .split("\0")
        )
        for name in names:
            if name and not excluded_diagnostic(name) and (REPO / name).is_file():
                destination = self.repo / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO / name, destination)
        self.install_article()

    def install_article(self):
        # The article owner integrates these two includes concurrently. Supply
        # only that declared integration in the private fixture; the actual
        # checkout still requires an independent check_paper.py run. Restoring
        # from the checkout also resets the fixture between mutation subtests.
        article = self.repo / "paper/index.qmd"
        prose = (REPO / "paper/index.qmd").read_text()
        for name in ("rolling_projection.md", "rolling_validation.md"):
            directive = "{{< include tables/" + name + " >}}"
            if directive not in prose:
                prose += "\n" + directive + "\n"
        article.write_text(prose)

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self):
        return {
            str(p.relative_to(self.repo)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.repo.rglob("*")
            if (
                not excluded_diagnostic(p)
                and ".git" not in p.relative_to(self.repo).parts
                and p.is_file()
            )
        }

    def run_guard(self):
        before = self.snapshot()
        result = subprocess.run(
            [sys.executable, "-B", "scripts/check_paper.py"],
            cwd=self.repo,
            capture_output=True,
            check=False,
            text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(before, self.snapshot(), "Guard changed checkout bytes")
        return result

    def test_integrated_fixture_guard_leaves_sources_unchanged(self):
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_corrupt_evaluation_fails_before_generator_without_repair(self):
        (self.repo / "data/evaluation_2025.json").write_text("invalid committed JSON\n")
        (self.repo / "scripts/evaluate_nowcast_2025.py").write_text(
            "from pathlib import Path\nPath('GENERATOR_RAN').write_text('wrong')\n"
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generators were not run", result.stdout)
        self.assertFalse((self.repo / "GENERATOR_RAN").exists())

    def test_current_corruption_fails_before_generator_without_repair(self):
        (self.repo / "data/current/ce_replication_2019_2025.json").write_text(
            "invalid current JSON\n"
        )
        (self.repo / "scripts/build_current_tables.py").write_text(
            "from pathlib import Path\nPath('GENERATOR_RAN').write_text('wrong')\n"
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generators were not run", result.stdout)
        self.assertIn("current artifact hash mismatch", result.stdout)
        self.assertFalse((self.repo / "GENERATOR_RAN").exists())

    def test_current_internal_content_hash_is_checked_after_file_hash(self):
        release_path = self.repo / "data/current/spm-release.json"
        release = json.loads(release_path.read_text())
        release["years"]["2025"]["thresholds"]["renter"] += 1
        release_path.write_text(json.dumps(release))
        manifest = self.repo / "data/current/SHA256SUMS"
        lines = manifest.read_text().splitlines()
        lines = [
            (
                f"{hashlib.sha256(release_path.read_bytes()).hexdigest()}  data/current/spm-release.json"
                if line.endswith("data/current/spm-release.json")
                else line
            )
            for line in lines
        ]
        manifest.write_text("\n".join(lines) + "\n")
        # Bypass only the independent frozen-manifest byte pin in this private
        # fixture so this attack reaches the release's inner content seal.
        guard_path = self.repo / "scripts/check_paper.py"
        original_manifest_hash = hashlib.sha256(
            (REPO / "data/current/SHA256SUMS").read_bytes()
        ).hexdigest()
        guard_path.write_text(
            guard_path.read_text().replace(
                original_manifest_hash,
                hashlib.sha256(manifest.read_bytes()).hexdigest(),
            )
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release canonical content hash", result.stdout)

    def test_retrospective_manifest_history_cannot_be_amended(self):
        manifest = self.repo / "data/current/SHA256SUMS"
        manifest.write_text(manifest.read_text() + "\n")
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("retrospective checksum manifest history changed", result.stdout)
        self.assertIn("generators were not run", result.stdout)

    def test_new_rolling_tables_must_both_be_included_in_article(self):
        path = self.repo / "paper/index.qmd"
        prose = path.read_text()
        for name in ("rolling_projection.md", "rolling_validation.md"):
            prose = prose.replace("{{< include tables/" + name + " >}}", "")
        path.write_text(prose)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("article tables never included", result.stdout)
        self.assertIn("rolling_projection.md", result.stdout)
        self.assertIn("rolling_validation.md", result.stdout)

    def refresh_rolling_manifest(self):
        manifest = self.repo / "data/current/ROLLING_SHA256SUMS"
        lines = []
        for line in manifest.read_text().splitlines():
            _, name = line.split()
            digest = hashlib.sha256((self.repo / name).read_bytes()).hexdigest()
            lines.append(f"{digest}  {name}")
        manifest.write_text("\n".join(lines) + "\n")

    def test_rolling_corruption_fails_before_generators_without_repair(self):
        (self.repo / "data/current" / ROLLING_NAME).write_text("invalid JSON\n")
        (self.repo / "scripts/build_current_tables.py").write_text(
            "from pathlib import Path\nPath('GENERATOR_RAN').write_text('wrong')\n"
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rolling artifact hash mismatch", result.stdout)
        self.assertIn("generators were not run", result.stdout)
        self.assertFalse((self.repo / "GENERATOR_RAN").exists())

    def test_rolling_provenance_mismatches_fail_after_manifest_refresh(self):
        path = self.repo / "data/current/rolling_provenance.json"
        original = json.loads(path.read_text())
        cases = (
            ("content_sha256", "rolling canonical content hash"),
            ("source_sha256", "rolling source fingerprints"),
            ("code_sha256", "rolling executed code fingerprints"),
            ("calculator_commit", "rolling calculator commit"),
        )
        for field, label in cases:
            with self.subTest(field=field):
                provenance = json.loads(json.dumps(original))
                if isinstance(provenance[field], dict):
                    provenance[field][next(iter(provenance[field]))] = "0" * 64
                else:
                    provenance[field] = "0" * len(provenance[field])
                path.write_text(json.dumps(provenance))
                self.refresh_rolling_manifest()
                result = self.run_guard()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(label, result.stdout)
                self.assertIn("generators were not run", result.stdout)
        path.write_text(json.dumps(original))
        self.refresh_rolling_manifest()

    def test_self_consistently_resealed_rolling_amount_cannot_replace_release(self):
        path = self.repo / "data/current" / ROLLING_NAME
        artifact = json.loads(path.read_text())
        artifact["scenarios"]["ce_trend"]["years"]["2026"]["thresholds"]["renter"] += 1
        artifact["content_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in artifact.items()
                    if key != "content_sha256"
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        path.write_text(json.dumps(artifact))
        provenance_path = self.repo / "data/current/rolling_provenance.json"
        provenance = json.loads(provenance_path.read_text())
        provenance["content_sha256"] = artifact["content_sha256"]
        provenance["artifact_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        provenance_path.write_text(json.dumps(provenance))
        self.refresh_rolling_manifest()
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rolling artifact hash mismatch", result.stdout)
        self.assertIn("generators were not run", result.stdout)

    def test_rolling_manifest_must_cover_exact_additional_artifacts(self):
        (self.repo / "data/current/ROLLING_SHA256SUMS").write_text("")
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rolling", result.stdout)
        self.assertIn("generators were not run", result.stdout)

    def test_rolling_projection_drift_is_detected_without_repair(self):
        table = self.repo / "paper/tables/rolling_projection.md"
        table.write_text(table.read_text() + "unreviewed forecast row\n")
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "generated output drifted: paper/tables/rolling_projection.md",
            result.stdout,
        )

    def test_rolling_validation_missing_is_detected_without_repair(self):
        (self.repo / "paper/tables/rolling_validation.md").unlink()
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generated tables present == expected", result.stdout)
        self.assertIn("rolling_validation.md", result.stdout)

    def test_regenerated_evaluation_json_drift_is_detected(self):
        path = self.repo / "scripts/evaluate_nowcast_2025.py"
        path.write_text(
            path.read_text().replace(
                '(OUTPUT_DATA / "evaluation_2025.json").write_text',
                'summary["unreviewed_change"] = True\n(OUTPUT_DATA / "evaluation_2025.json").write_text',
            )
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "generated output drifted: data/evaluation_2025.json", result.stdout
        )

    def test_missing_and_extra_tables_fail_without_restoring_them(self):
        (self.repo / "paper/tables/evaluation.md").unlink()
        (self.repo / "paper/tables/extra.md").write_text("unexpected table\n")
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generated tables present == expected", result.stdout)

    def test_forecast_record_is_required(self):
        (self.repo / "docs/forecast-record.md").unlink()
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forecast registration record exists", result.stdout)

    def test_nowcast_registration_link_is_required_at_the_forecast(self):
        path = self.repo / "paper/index.qmd"
        qmd = path.read_text()
        url = (
            "https://github.com/PolicyEngine/spm-threshold-paper/blob/"
            "20bfbe1abcb83b4f9f60fbe54789144321ff62b0/docs/forecast-record.md"
        )
        self.assertEqual(qmd.count(url), 2)
        # The Appendix B link stays: it cannot substitute for evidence
        # beside the pre-commitment claim in the nowcast section.
        path.write_text(qmd.replace(url, "#sec-nowcast", 1))
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "nowcast section links to the fixed forecast registration record",
            result.stdout,
        )

    def test_pinned_supporting_documents_match_linked_commit(self):
        for name in (
            "docs/forecast-record.md",
            "data/PROVENANCE.md",
            "docs/reproducing-experiments.md",
        ):
            with self.subTest(path=name):
                path = self.repo / name
                original = path.read_bytes()
                # Retain every guarded literal: altered supporting prose
                # must still fail if the manuscript links unchanged bytes.
                path.write_bytes(original + b"\nUnregistered supporting text.\n")
                result = self.run_guard()
                path.write_bytes(original)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"pinned supporting document matches: {name}", result.stdout
                )

    def test_forecast_record_mutation_is_detected(self):
        path = self.repo / "docs/forecast-record.md"
        path.write_text(path.read_text().replace("$41,099.57", "$41,099.58"))
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forecast record original literal 41,099.57", result.stdout)

    def test_evaluation_archive_tampering_is_detected(self):
        path = self.repo / "paper/tables/evaluation.md"
        path.write_text(path.read_text().replace("0.98%", "0.99%"))
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "generated output drifted: paper/tables/evaluation.md", result.stdout
        )

    def test_evaluation_main_matches_the_four_primary_rules(self):
        archive = (self.repo / "paper/tables/evaluation.md").read_text().splitlines()
        main = (self.repo / "paper/tables/evaluation_main.md").read_text().splitlines()
        self.assertEqual(main[:2], archive[:2])
        self.assertEqual(len(main), 6)
        self.assertEqual(
            main[2:],
            [
                archive[2].replace(
                    "**Amended nowcast (50/50 blend, committed)**",
                    "**Committed equal blend**",
                ),
                archive[4].replace(
                    "CE replication growth ratio alone", "CE replication growth ratio"
                ),
                archive[5].replace(
                    "FCSUti-composite CPI aging alone", "Composite-price adjustment"
                ),
                archive[6].replace(
                    "All-Items CPI-U aging (status quo)", "All-Items CPI-U adjustment"
                ),
            ],
        )
        levels = (self.repo / "paper/tables/evaluation_levels.md").read_text()
        main_levels = (self.repo / "paper/tables/evaluation_levels_main.md").read_text()
        self.assertEqual(
            main_levels, levels.replace("Amended nowcast", "Committed nowcast")
        )

    def test_archived_table_still_checked_when_not_in_article(self):
        qmd = (self.repo / "paper/index.qmd").read_text()
        self.assertNotIn("include tables/package_errors.md", qmd)
        (self.repo / "paper/tables/package_errors.md").write_text("changed archive\n")
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "generated output drifted: paper/tables/package_errors.md", result.stdout
        )

    def test_current_projection_headline_drift_is_detected(self):
        path = self.repo / "paper/index.qmd"
        path.write_text(path.read_text().replace("0.51", "9.51"))
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("current projection prose replication_ratio", result.stdout)

    def test_projection_and_backtest_figures_quoted_elsewhere_still_pin(self):
        """The in-kind section also quotes 0.90 and 0.76, so a drifted
        abstract blend or benchmark blend must still fail its own pin."""
        path = self.repo / "paper/index.qmd"
        text = path.read_text()
        for number, old, new, label in (
            (
                "0.90",
                "0.90 percent with an equal blend",
                "0.91 percent with an equal blend",
                "abstract current projection blend 0.90",
            ),
            (
                "0.76",
                "The equal blend scores 0.76 percent",
                "The equal blend scores 0.77 percent",
                "backtest prose literal 0.76",
            ),
        ):
            with self.subTest(label=label):
                self.assertEqual(text.count(old), 1)
                self.assertGreater(len(re.findall(rf"(?<![\d.]){re.escape(number)}(?!\d)", text)), 1)
                path.write_text(text.replace(old, new))
                result = self.run_guard()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(label, result.stdout)
        path.write_text(text)

    def test_signed_cpi_u_bias_pins_its_sign(self):
        path = self.repo / "paper/index.qmd"
        text = path.read_text()
        self.assertEqual(text.count("error of −1.9 percent"), 1)
        path.write_text(text.replace("error of −1.9 percent", "error of +1.9 percent"))
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("signed CPI-U bias -1.9", result.stdout)

    def test_evaluation_range_rounds_from_saved_errors(self):
        path = self.repo / "paper/index.qmd"
        path.write_text(path.read_text().replace("1.70 to 3.47", "1.70 to 3.48"))
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "CPI-U 2025 understated every tenure by 1.70 to 3.47 percent", result.stdout
        )

    def test_generator_failure_leaves_source_files_unchanged(self):
        (self.repo / "scripts/evaluate_nowcast_2025.py").write_text(
            "raise RuntimeError('fixture failure')\n"
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("evaluate_nowcast_2025.py failed", result.stdout)

    def test_moved_tag_is_rejected_in_independent_clone(self):
        subprocess.run(
            ["git", "update-ref", "refs/tags/v1.1-amended-nowcast", "HEAD"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tag identity mismatch", result.stdout)

    def test_old_timestamp_never_covers_an_amended_manifest(self):
        path = self.repo / "data/COMMITMENT-MANIFEST.txt"
        path.write_text(path.read_text().replace("85049a018", "19a1f44d1"))
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("preserved commitment/proof bytes changed", result.stdout)

    def refresh_inkind_manifest(self):
        lines = [
            f"{hashlib.sha256((self.repo / 'data/inkind' / name).read_bytes()).hexdigest()}  data/inkind/{name}"
            for name in INKIND_NAMES
        ]
        (self.repo / "data/inkind/SHA256SUMS").write_text("\n".join(lines) + "\n")

    def test_inkind_corruption_fails_before_generators_without_repair(self):
        (self.repo / "data/inkind/ce_inkind_replication_2019_2025.json").write_text(
            "invalid in-kind JSON\n"
        )
        (self.repo / "scripts/build_inkind_tables.py").write_text(
            "from pathlib import Path\nPath('GENERATOR_RAN').write_text('wrong')\n"
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("in-kind input validation", result.stdout)
        self.assertIn("hash of data/inkind/ce_inkind_replication_2019_2025.json", result.stdout)
        self.assertIn("generators were not run", result.stdout)
        self.assertFalse((self.repo / "GENERATOR_RAN").exists())

    def test_inkind_manifest_must_cover_exactly_the_receipts(self):
        (self.repo / "data/inkind/extra.json").write_text("{}\n")
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("manifest coverage", result.stdout)
        self.assertIn("generators were not run", result.stdout)

    def reseal_inkind(self, name, receipt):
        """Write an edited receipt and update every hash that records it, so
        only the semantic checks can reject the edit."""
        path = self.repo / "data/inkind" / name
        path.write_text(json.dumps(receipt))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        provenance_path = self.repo / "data/inkind/provenance.json"
        provenance = json.loads(provenance_path.read_text())
        provenance["artifacts"][f"data/inkind/{name}"]["sha256"] = digest
        provenance_path.write_text(json.dumps(provenance))
        self.refresh_inkind_manifest()
        return digest

    def reseal_inkind_replication(self, replication):
        """Reseal an edited replication receipt and repoint the component and
        uncertainty receipts at it."""
        digest = self.reseal_inkind(INKIND_NAMES[1], replication)
        components = json.loads((self.repo / "data/inkind" / INKIND_NAMES[0]).read_text())
        components["inputs"]["replication_receipt"]["sha256"] = digest
        components_digest = self.reseal_inkind(INKIND_NAMES[0], components)
        uncertainty = self.inkind_uncertainty()
        uncertainty["inputs"]["replication_receipt"]["sha256"] = digest
        uncertainty["inputs"]["components_receipt"]["sha256"] = components_digest
        self.reseal_inkind(INKIND_NAMES[2], uncertainty)

    def reseal_and_repin_components(self, edit):
        """Edit the components receipt, reseal it and the uncertainty receipt
        that records it, and pin both new digests in the copy's
        inkind_inputs.py, so only the drift checks can reject the edit."""
        inkind = self.repo / "data/inkind"
        pins = self.repo / "scripts/inkind_inputs.py"
        names = (INKIND_NAMES[0], INKIND_NAMES[2])
        before = {name: hashlib.sha256((inkind / name).read_bytes()).hexdigest() for name in names}
        components = json.loads((inkind / INKIND_NAMES[0]).read_text())
        edit(components)
        digest = self.reseal_inkind(INKIND_NAMES[0], components)
        uncertainty = self.inkind_uncertainty()
        uncertainty["inputs"]["components_receipt"]["sha256"] = digest
        self.reseal_inkind(INKIND_NAMES[2], uncertainty)
        text = pins.read_text()
        for name in names:
            self.assertEqual(text.count(before[name]), 1, f"{name} digest not pinned once")
            text = text.replace(before[name], hashlib.sha256((inkind / name).read_bytes()).hexdigest())
        pins.write_text(text)

    def reseal_and_repin_uncertainty(self, edit):
        """Edit the uncertainty receipt, reseal it and pin its new digest in
        the copy's inkind_inputs.py, so only the drift checks can reject the
        edit."""
        inkind = self.repo / "data/inkind"
        pins = self.repo / "scripts/inkind_inputs.py"
        before = hashlib.sha256((inkind / INKIND_NAMES[2]).read_bytes()).hexdigest()
        uncertainty = self.inkind_uncertainty()
        edit(uncertainty)
        after = self.reseal_inkind(INKIND_NAMES[2], uncertainty)
        text = pins.read_text()
        self.assertEqual(text.count(before), 1, "uncertainty digest not pinned once")
        pins.write_text(text.replace(before, after))

    def reseal_and_repin_receipts(self, edit):
        """Edit any of the three receipts, reseal each in turn with the
        digests of the receipts it records, copy their code fingerprints into
        the provenance record, and pin all three new digests in the copy's
        inkind_inputs.py, so only the drift checks can reject the edit. The
        rent sensitivity receipt records the imputation receipt's digest, so
        its pin fails too."""
        inkind = self.repo / "data/inkind"
        pins = self.repo / "scripts/inkind_inputs.py"
        names = INKIND_NAMES[:3]
        before = {name: hashlib.sha256((inkind / name).read_bytes()).hexdigest() for name in names}
        receipts = {name: json.loads((inkind / name).read_text()) for name in names}
        edit(receipts)
        components, replication, uncertainty = (receipts[name] for name in names)
        replication_digest = self.reseal_inkind(INKIND_NAMES[1], replication)
        components["inputs"]["replication_receipt"]["sha256"] = replication_digest
        components_digest = self.reseal_inkind(INKIND_NAMES[0], components)
        uncertainty["inputs"]["replication_receipt"]["sha256"] = replication_digest
        uncertainty["inputs"]["components_receipt"]["sha256"] = components_digest
        self.reseal_inkind(INKIND_NAMES[2], uncertainty)
        provenance_path = inkind / "provenance.json"
        provenance = json.loads(provenance_path.read_text())
        for name in names:
            provenance["artifacts"][f"data/inkind/{name}"]["code_sha256"] = receipts[name]["code_sha256"]
        provenance_path.write_text(json.dumps(provenance))
        self.refresh_inkind_manifest()
        text = pins.read_text()
        for name in names:
            self.assertEqual(text.count(before[name]), 1, f"{name} digest not pinned once")
            text = text.replace(before[name], hashlib.sha256((inkind / name).read_bytes()).hexdigest())
        pins.write_text(text)

    def restore_inkind(self):
        """Put the copy's receipts, provenance, manifest and pins back to the
        checkout's, between subtests that reseal them."""
        for name in (*INKIND_NAMES, "SHA256SUMS"):
            shutil.copyfile(REPO / "data/inkind" / name, self.repo / "data/inkind" / name)
        shutil.copyfile(REPO / "scripts/inkind_inputs.py", self.repo / "scripts/inkind_inputs.py")

    def assert_resealed_receipts_fail(self, cases):
        """Each case edits the receipts, which are then resealed and repinned
        from the checkout's; the guard must reach the drift checks and fail
        every pin the case names."""
        for name, edit, labels in cases:
            with self.subTest(name=name):
                self.restore_inkind()
                self.reseal_and_repin_receipts(edit)
                result = self.run_guard()
                self.assertNotEqual(result.returncode, 0)
                for label in labels:
                    self.assertIn(f"in-kind prose: {label}", result.stdout)
                self.assertNotIn("generators were not run", result.stdout)
        self.restore_inkind()

    def inkind_uncertainty(self):
        return json.loads((self.repo / "data/inkind" / INKIND_NAMES[2]).read_text())

    def assert_resealed_uncertainty_fails(self, edit, expected):
        """Edit the uncertainty receipt, update every hash that records it,
        and expect the semantic check named ``expected`` to reject it."""
        uncertainty = self.inkind_uncertainty()
        edit(uncertainty)
        self.reseal_inkind(INKIND_NAMES[2], uncertainty)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(expected, result.stdout)
        self.assertIn("generators were not run", result.stdout)

    def test_resealed_uncertainty_receipt_must_match_its_replicates(self):
        def move_one_replicate(uncertainty):
            uncertainty["runs"]["package"]["years"]["2025"]["replicates"]["with_in_kind"]["renter"][0][7] += 40

        self.assert_resealed_uncertainty_fails(
            move_one_replicate, "within variance level with benefits package 2025 renter"
        )

    def test_uncertainty_receipt_must_name_the_recorded_receipts(self):
        def repoint(uncertainty):
            uncertainty["inputs"]["replication_receipt"]["sha256"] = "0" * 64

        self.assert_resealed_uncertainty_fails(
            repoint, "uncertainty receipt derives from the recorded replication receipt"
        )

    def test_uncertainty_receipt_must_start_from_the_replication(self):
        def shift_full_sample(uncertainty):
            uncertainty["runs"]["package"]["years"]["2023"]["replicates"]["without_in_kind"]["renter"][0] += 1

        self.assert_resealed_uncertainty_fails(
            shift_full_sample, "full-sample threshold without benefits package 2023 renter"
        )

    def test_uncertainty_receipt_must_carry_bls_published_standard_errors(self):
        def shift_bls_se(uncertainty):
            uncertainty["runs"]["fcsuti"]["years"]["2024"]["bls"]["standard_errors"]["renter"] += 1

        self.assert_resealed_uncertainty_fails(shift_bls_se, "BLS standard error fcsuti 2024 renter")

    def test_receipts_must_share_code_fingerprints(self):
        def change_fingerprint(uncertainty):
            uncertainty["code_sha256"]["spm_calculator/ce_inkind.py"] = "0" * 64

        uncertainty = self.inkind_uncertainty()
        change_fingerprint(uncertainty)
        self.reseal_inkind(INKIND_NAMES[2], uncertainty)
        provenance_path = self.repo / "data/inkind/provenance.json"
        provenance = json.loads(provenance_path.read_text())
        provenance["artifacts"][f"data/inkind/{INKIND_NAMES[2]}"]["code_sha256"] = uncertainty["code_sha256"]
        provenance_path.write_text(json.dumps(provenance))
        self.refresh_inkind_manifest()
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("spm_calculator/ce_inkind.py differs across receipts", result.stdout)
        self.assertIn("generators were not run", result.stdout)

    def test_uncertainty_receipt_must_read_the_replication_inputs(self):
        def zero_bundle(uncertainty):
            uncertainty["inputs"]["ce_bundles"]["intrvw24.zip"]["sha256"] = "0" * 64

        self.assert_resealed_uncertainty_fails(
            zero_bundle, "uncertainty receipt reads the replication receipt's raw inputs and seed"
        )

    def test_uncertainty_receipt_must_use_the_replication_seed(self):
        def change_seed(uncertainty):
            uncertainty["inputs"]["imputation_seed"] += 1

        self.assert_resealed_uncertainty_fails(
            change_seed, "uncertainty receipt reads the replication receipt's raw inputs and seed"
        )

    def test_resealed_and_repinned_components_reach_the_drift_checks(self):
        """Control for the two tests below: a resealed, repinned components
        receipt with unchanged content passes the whole guard."""
        self.reseal_and_repin_components(lambda components: None)
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_definition_runs_must_drop_vacation_home_utilities(self):
        def keep_2022_vacation_utilities(components):
            components["definition_check"]["2022"]["units_with_amount_removed"]["vacation_utilities"] = 0

        self.reseal_and_repin_components(keep_2022_vacation_utilities)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("in-kind prose: Garner–Munoz runs drop vacation-home utilities", result.stdout)
        self.assertNotIn("generators were not run", result.stdout)

    def test_definition_runs_must_drop_the_vacation_home_principal(self):
        def keep_2022_vacation_home_principal(components):
            components["definition_check"]["2022"]["units_with_amount_removed"]["vacation_home_principal"] = 0

        self.reseal_and_repin_components(keep_2022_vacation_home_principal)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "in-kind prose: Garner–Munoz runs drop vacation-home utilities and principal", result.stdout
        )
        self.assertNotIn("generators were not run", result.stdout)

    def test_paper_states_which_price_factors_the_replicates_hold_fixed(self):
        def replicate_the_price_indexes(uncertainty):
            held = uncertainty["method"]["held_fixed"]
            self.assertIn("the CPI series and BLS's FCSUti index", held)
            held.remove("the CPI series and BLS's FCSUti index")

        self.reseal_and_repin_uncertainty(replicate_the_price_indexes)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("in-kind prose: FCSUti price factors held fixed across replicates", result.stdout)
        self.assertNotIn("generators were not run", result.stdout)

    def test_definition_runs_must_leave_no_utilities_below_zero(self):
        def push_2022_utilities_below_zero(components):
            components["definition_check"]["2022"]["units_with_utilities_below_zero"]["after"] = 57

        self.reseal_and_repin_components(push_2022_utilities_below_zero)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("in-kind prose: Garner–Munoz runs drop vacation-home utilities", result.stdout)
        self.assertNotIn("generators were not run", result.stdout)

    def test_paper_names_the_internet_row_each_year_uses(self):
        def read_2024_from_the_total_row(components):
            components["bls"]["years"]["2024"]["checks"]["internet_row"] = "internet_total_row"

        self.reseal_and_repin_components(read_2024_from_the_total_row)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("in-kind prose: BLS internet row by threshold year", result.stdout)
        self.assertNotIn("generators were not run", result.stdout)

    def test_paper_counts_the_vacation_fuel_codes_the_calculator_keeps(self):
        def name_a_third_code(components):
            limitations = components["limitations"]
            matches = [i for i, text in enumerate(limitations) if "250913 and 250914" in text]
            self.assertEqual(len(matches), 1, limitations)
            limitations[matches[0]] = limitations[matches[0]].replace(
                "250913 and 250914", "250912, 250913 and 250914"
            )

        self.reseal_and_repin_components(name_a_third_code)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("in-kind prose: Garner–Munoz runs keep the vacation-home fuel codes", result.stdout)
        self.assertNotIn("generators were not run", result.stdout)

    def test_resealed_and_repinned_receipts_reach_the_drift_checks(self):
        """Control for the tests below: all three receipts resealed and
        repinned with unchanged content fail no pin but the rent sensitivity
        receipt's, which records the imputation receipt's digest."""
        self.reseal_and_repin_receipts(lambda receipts: None)
        result = self.run_guard()
        self.assertNotIn("generators were not run", result.stdout)
        # A guard that crashes prints no failures at all, so require its verdict.
        self.assertNotIn("Traceback", result.stderr, result.stderr)
        self.assertTrue(
            "PAPER DRIFT CHECK FAILED:" in result.stdout or result.returncode == 0,
            result.stdout + result.stderr,
        )
        failures = {line for line in result.stdout.splitlines() if line.startswith("  - ")}
        self.assertLessEqual(
            failures,
            {"  - in-kind prose: rent sensitivity receipt matches its pin, its script and the imputation receipt"},
            result.stdout + result.stderr,
        )

    def test_fingerprinted_rules_fail_when_their_code_changes(self):
        def fingerprint_changed(path):
            # Every receipt that fingerprints a file must carry one hash
            # for it, so the edit changes it in each.
            def edit(receipts):
                carriers = [receipt for receipt in receipts.values() if path in receipt["code_sha256"]]
                self.assertTrue(carriers, path)
                for receipt in carriers:
                    receipt["code_sha256"][path] = "0" * 64

            return edit

        self.assert_resealed_receipts_fail(
            (
                (
                    "imputation code",
                    fingerprint_changed("spm_calculator/ce_inkind.py"),
                    (
                        "method constants read from fingerprinted calculator code",
                        "percentile band and windows read from fingerprinted calculator code",
                    ),
                ),
                (
                    "BLS shares code",
                    fingerprint_changed("spm_calculator/ce_bls_shares.py"),
                    (
                        "Garner–Munoz restrictions read from fingerprinted calculator code",
                        "BLS internet reading from fingerprinted calculator code",
                    ),
                ),
                (
                    "threshold code",
                    fingerprint_changed("spm_calculator/ce_threshold.py"),
                    ("percentile band and windows read from fingerprinted calculator code",),
                ),
            )
        )

    def test_broadband_start_and_wic_cutoff_follow_the_imputation_receipt(self):
        def methodology(receipts):
            return receipts[INKIND_NAMES[1]]["in_kind_methodology"]

        def start_broadband_a_year_earlier(receipts):
            methodology(receipts)["broadband_first_reference_year"] -= 1

        def end_wic_a_year_later(receipts):
            methodology(receipts)["wic_ebt_all_states_from_reference_year"] += 1

        def add_wic_to_the_2025_window(receipts):
            # The 2025 universe's added units can take WIC only if the window does.
            receipts[INKIND_NAMES[1]]["results"]["2025"]["sample_mean_in_kind_threshold_year_dollars"]["wic"] = 0.5

        label = ("broadband start and WIC cutoff from the imputation receipt",)
        self.assert_resealed_receipts_fail(
            (
                ("broadband start", start_broadband_a_year_earlier, label),
                ("WIC cutoff", end_wic_a_year_later, label),
                ("WIC in the 2025 window", add_wic_to_the_2025_window, label),
            )
        )

    def test_wic_ebt_dates_follow_the_fns_table_the_receipt_hashes(self):
        def change_the_fns_table(receipts):
            receipts[INKIND_NAMES[1]]["in_kind_methodology"]["parameter_files_sha256"][
                "usda_wic_ebt_statewide.csv"
            ] = "0" * 64

        self.assert_resealed_receipts_fail(
            (("FNS table", change_the_fns_table, ("WIC EBT dates from the calculator's FNS table",)),)
        )

    def test_paper_adds_no_2025_wic_only_while_the_receipt_adds_none(self):
        def lift_2025_renters_by_wic(receipts):
            receipts[INKIND_NAMES[1]]["results"]["2025"]["component_lift_percent"]["wic"]["renter"] = 0.01

        self.assert_resealed_receipts_fail(
            (("2025 renter WIC lift", lift_2025_renters_by_wic, ("BLS's 2025 WIC band mean against our none",)),)
        )

    def test_wic_by_state_sentences_follow_the_imputation_receipt(self):
        def sensitivity(receipts):
            return receipts[INKIND_NAMES[1]]["wic_ebt_by_state_sensitivity"]

        # Each case below breaks one check of the pin and keeps the block's
        # other ties, so deleting that check lets the case through.
        def set_threshold(targets, year, tenure, level):
            """Set one rerun threshold and shift each of its implicates by as
            much, so the threshold stays its implicates' mean."""
            shift = level - targets[year]["with_in_kind"][tenure]
            targets[year]["with_in_kind"][tenure] = level
            for run in targets[year]["with_in_kind_by_implicate"]:
                run[tenure] += shift

        def move_a_threshold(receipts, year, tenure, dollars):
            """Move one rerun threshold by `dollars` and restate its change."""
            targets = sensitivity(receipts)["by_target"]
            base = receipts[INKIND_NAMES[1]]["results"][year]["with_in_kind"][tenure]
            set_threshold(targets, year, tenure, targets[year]["with_in_kind"][tenure] + dollars)
            targets[year]["change_dollars"][tenure] += dollars
            targets[year]["change_percent"][tenure] = 100 * targets[year]["change_dollars"][tenure] / base

        def widen_the_largest_move(receipts):
            # The largest move is in neither 2022 nor 2025, so growth holds.
            targets = sensitivity(receipts)["by_target"]
            year, tenure = max(
                ((year, tenure) for year, target in targets.items() for tenure in target["change_dollars"]),
                key=lambda key: targets[key[0]]["change_dollars"][key[1]],
            )
            self.assertNotIn(year, ("2022", "2025"))
            move_a_threshold(receipts, year, tenure, 10)

        def move_an_unmoved_threshold(receipts):
            targets = sensitivity(receipts)["by_target"]
            unmoved = [year for year, target in sorted(targets.items()) if not any(target["change_dollars"].values())]
            self.assertTrue(unmoved, "every threshold moves")
            self.assertNotIn(unmoved[0], ("2022", "2025"))
            move_a_threshold(receipts, unmoved[0], "renter", 1.0)

        def shift_a_threshold_off_its_change(receipts):
            # A moved year outside 2022 and 2025, with its change left as is.
            targets = sensitivity(receipts)["by_target"]
            set_threshold(targets, "2023", "renter", targets["2023"]["with_in_kind"]["renter"] + 1)

        def move_an_implicate_off_its_threshold(receipts):
            # The threshold and its change stay, so only the mean's tie fails.
            sensitivity(receipts)["by_target"]["2023"]["with_in_kind_by_implicate"][0]["renter"] += 5

        def raise_the_largest_wic_rise(receipts):
            targets = sensitivity(receipts)["by_target"]
            results = receipts[INKIND_NAMES[1]]["results"]
            year = max(
                targets,
                key=lambda year: targets[year]["sample_mean_wic_threshold_year_dollars"]
                - results[year]["sample_mean_in_kind_threshold_year_dollars"]["wic"],
            )
            targets[year]["sample_mean_wic_threshold_year_dollars"] += 1

        def push_growth_past_the_stated_bound(receipts):
            # 0.031 still rounds to the 0.03 the prose states, and the 2022
            # thresholds are restated to give it.
            growth = sensitivity(receipts)["growth_2022_2025_change_points"]
            tenure = max(growth, key=lambda tenure: abs(growth[tenure]))
            set_growth_changes(receipts, {tenure: math.copysign(0.031, growth[tenure])})

        def misstate_a_growth_change(receipts):
            # The smallest change, so the largest stays the bound.
            growth = sensitivity(receipts)["growth_2022_2025_change_points"]
            growth[min(growth, key=lambda tenure: abs(growth[tenure]))] += 0.001

        def apply_the_all_states_cutoff(receipts):
            sensitivity(receipts)["wic_ebt_all_states_from_reference_year"] = 2020

        def drop_a_target_year(receipts):
            del sensitivity(receipts)["by_target"][min(sensitivity(receipts)["by_target"])]

        def lower_an_unmoved_years_wic(receipts):
            targets = sensitivity(receipts)["by_target"]
            unmoved = [year for year, target in sorted(targets.items()) if not any(target["change_dollars"].values())]
            self.assertTrue(unmoved, "every threshold moves")
            targets[unmoved[0]]["sample_mean_wic_threshold_year_dollars"] -= 1

        def quoted_extremes(receipts):
            """The rounded extremes the prose quotes, over the years whose
            mean WIC rises."""
            targets = sensitivity(receipts)["by_target"]
            results = receipts[INKIND_NAMES[1]]["results"]
            risen = [
                year
                for year in targets
                if targets[year]["sample_mean_wic_threshold_year_dollars"]
                - results[year]["sample_mean_in_kind_threshold_year_dollars"]["wic"]
                > 1e-9
            ]
            moves = [move for year in risen for move in targets[year]["change_dollars"].values()]
            percents = [move for year in risen for move in targets[year]["change_percent"].values()]
            return tuple(f"{value:+.0f}" for value in (min(moves), max(moves))) + tuple(
                f"{value:+.2f}" for value in (min(percents), max(percents))
            )

        def set_growth_changes(receipts, changes):
            """Give the rerun's 2022 thresholds the 2022–2025 growth changes
            asked for, and restate every figure that follows from them, so
            the block stays consistent. 2025 holds the lowest move the prose
            quotes, so the fixture restates 2022 and checks that the quoted
            extremes stay put."""
            block = sensitivity(receipts)
            targets = block["by_target"]
            results = receipts[INKIND_NAMES[1]]["results"]
            quoted = quoted_extremes(receipts)
            for tenure, change in changes.items():
                base_growth = 100 * (
                    results["2025"]["with_in_kind"][tenure] / results["2022"]["with_in_kind"][tenure] - 1
                )
                level = targets["2025"]["with_in_kind"][tenure] / (1 + (base_growth + change) / 100)
                moved = level - results["2022"]["with_in_kind"][tenure]
                set_threshold(targets, "2022", tenure, level)
                targets["2022"]["change_dollars"][tenure] = moved
                targets["2022"]["change_percent"][tenure] = 100 * moved / results["2022"]["with_in_kind"][tenure]
                block["growth_2022_2025_percent_with"][tenure] = base_growth + change
                block["growth_2022_2025_change_points"][tenure] = change
            self.assertEqual(quoted_extremes(receipts), quoted, "a restated threshold moved a quoted extreme")

        def shrink_growth_well_below_the_stated_bound(receipts):
            # The prose's "0.03 points or less" must be the bound, not a loose one.
            growth = sensitivity(receipts)["growth_2022_2025_change_points"]
            set_growth_changes(receipts, {tenure: math.copysign(0.004, growth[tenure]) for tenure in growth})

        def break_the_run_of_moved_years(receipts):
            # 2024 stops moving while 2021–2023 and 2025 still do, so the
            # prose's "2021–2025" would cover a year with no change. 2024
            # lies outside the 2022–2025 growth window, and its moves are no
            # extreme the prose quotes.
            targets = sensitivity(receipts)["by_target"]
            results = receipts[INKIND_NAMES[1]]["results"]
            quoted = quoted_extremes(receipts)
            targets["2024"]["sample_mean_wic_threshold_year_dollars"] = results["2024"][
                "sample_mean_in_kind_threshold_year_dollars"
            ]["wic"]
            for tenure in targets["2024"]["change_dollars"]:
                targets["2024"]["change_dollars"][tenure] = 0.0
                targets["2024"]["change_percent"][tenure] = 0.0
                set_threshold(targets, "2024", tenure, results["2024"]["with_in_kind"][tenure])
            self.assertEqual(quoted_extremes(receipts), quoted, "2024 held a quoted extreme")

        def misstate_a_percent(receipts):
            # Dollars unchanged, so only the percent's tie to them can fail.
            targets = sensitivity(receipts)["by_target"]
            year = max(targets)
            targets[year]["change_percent"]["renter"] += 0.001

        def misstate_a_growth_level(receipts):
            block = sensitivity(receipts)
            block["growth_2022_2025_percent_with"]["renter"] += 0.001

        def drop_the_sensitivity(receipts):
            del receipts[INKIND_NAMES[1]]["wic_ebt_by_state_sensitivity"]

        label = ("WIC by-state sensitivity from the imputation receipt",)
        self.assert_resealed_receipts_fail(
            (
                ("largest threshold move", widen_the_largest_move, label),
                ("unmoved threshold moves", move_an_unmoved_threshold, label),
                ("largest WIC rise", raise_the_largest_wic_rise, label),
                ("growth change past 0.03", push_growth_past_the_stated_bound, label),
                ("sensitivity keeps the all-states cutoff", apply_the_all_states_cutoff, label),
                ("sensitivity missing", drop_the_sensitivity, label),
                ("a target year missing", drop_a_target_year, label),
                ("an unmoved year's WIC falls", lower_an_unmoved_years_wic, label),
                ("growth bound stated loosely", shrink_growth_well_below_the_stated_bound, label),
                ("moved years not a run", break_the_run_of_moved_years, label),
                ("threshold off its change", shift_a_threshold_off_its_change, label),
                ("threshold off its implicates", move_an_implicate_off_its_threshold, label),
                ("percent change off its dollars", misstate_a_percent, label),
                ("growth off its thresholds", misstate_a_growth_level, label),
                ("growth change off its thresholds", misstate_a_growth_change, label),
            )
        )

    def test_reflected_replicates_fail_only_the_pinned_digest(self):
        """A resealed receipt whose 2019 replicates mirror the committed ones
        passes every consistency check; the digest pinned outside data/inkind
        rejects it, and no generator runs."""
        uncertainty = self.inkind_uncertainty()
        reflect_replicates(uncertainty, "2019")
        self.reseal_inkind(INKIND_NAMES[2], uncertainty)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{INKIND_NAMES[2]} matches the SHA-256 pinned in inkind_inputs.py", result.stdout)
        self.assertEqual(result.stdout.count("in-kind input validation"), 1, result.stdout)
        self.assertIn("generators were not run", result.stdout)

    def test_provenance_must_name_the_pinned_calculator_commit(self):
        provenance_path = self.repo / "data/inkind/provenance.json"
        provenance = json.loads(provenance_path.read_text())
        provenance["artifacts"][f"data/inkind/{INKIND_NAMES[2]}"]["calculator_commit"] = "1" * 40
        provenance_path.write_text(json.dumps(provenance))
        self.refresh_inkind_manifest()
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            f"{INKIND_NAMES[2]} comes from the calculator commit pinned in inkind_inputs.py", result.stdout
        )
        self.assertIn("generators were not run", result.stdout)

    def test_readme_counts_the_receipts_and_names_their_commits(self):
        readme = self.repo / "README.md"
        original = readme.read_text()
        commit = INKIND_COMMITS[INKIND_NAMES[2]]
        cases = (
            ("receipt count", "uses three receipts", "uses two receipts"),
            ("commit", f"`{commit}`", f"`{commit[:7]}`"),
            ("tag", f"`paper-inkind-se-{commit[:7]}`", "`paper-inkind-se-a581c11`"),
        )
        for name, old, new in cases:
            with self.subTest(name=name):
                self.assertEqual(original.count(old), 1, f"ambiguous README edit: {old!r}")
                readme.write_text(original.replace(old, new))
                result = self.run_guard()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "in-kind prose: README counts the receipts and names the commits and tags", result.stdout
                )
        readme.write_text(original)

    def test_bibliography_cites_the_recorded_calculator_commits(self):
        bib = self.repo / "bibliography/references.bib"
        original = bib.read_text()
        # All three receipts come from one calculator commit, so the cases
        # edit one entry at a time; a swap of two commits would change nothing.
        components, replication, uncertainty = (INKIND_COMMITS[name] for name in INKIND_NAMES[:3])
        self.assertEqual({components, replication, uncertainty}, {components})
        stale_components = "8f632e31b4e48bbc735161d24665a8182dc0d9d6"
        stale_uncertainty = "a581c113dd4319fc0f6f9ebd6db5c3697f4a94fa"
        stale_replication = "4778dfab2d109515b6a14e63da63011dd7feb884"
        note = f"Imputation and comparison with BLS components at commit {components}"
        inkind = original.index("@misc{spmcalculator2026inkind")
        inkind = (inkind, original.index("\n}\n", inkind) + 3)
        se = original.index("@misc{spmcalculator2026se")
        se = (se, original.index("\n}\n", se) + 3)

        def in_entry(entry, old, new):
            start, end = entry
            return original[:start] + original[start:end].replace(old, new) + original[end:]

        cases = (
            ("stale components commit", in_entry(inkind, components, stale_components)),
            ("stale standard-error commit", in_entry(se, uncertainty, stale_uncertainty)),
            ("stale components link", in_entry(inkind, f"blob/{components}/", f"blob/{stale_components}/")),
            ("stale standard-error link", in_entry(se, f"blob/{uncertainty}/", f"blob/{stale_uncertainty}/")),
            (
                "note names the imputation's old commit",
                original.replace(
                    note,
                    f"Imputation at commit {stale_replication}; comparison with BLS components at commit {components}",
                ),
            ),
            (
                "in-kind link to a fork",
                in_entry(
                    inkind,
                    "https://github.com/PolicyEngine/spm-calculator/blob/",
                    "https://github.com/MaxGhenis/spm-calculator/blob/",
                ),
            ),
        )
        self.assertEqual(original.count(note), 1)
        self.assertEqual(original[inkind[0] : inkind[1]].count(components), 2)
        self.assertEqual(original[se[0] : se[1]].count(uncertainty), 2)
        for name, edited in cases:
            with self.subTest(name=name):
                self.assertNotEqual(edited, original)
                bib.write_text(edited)
                result = self.run_guard()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("in-kind prose: bibliography cites the recorded calculator commits", result.stdout)
        bib.write_text(original)

    def inkind_replication(self):
        return json.loads((self.repo / "data/inkind" / INKIND_NAMES[1]).read_text())

    def test_resealed_inkind_receipts_must_agree_with_their_sources(self):
        replication = self.inkind_replication()
        replication["results"]["2025"]["without_home_internet"]["renter"] += 1
        with self.subTest(stage="component receipt still names the old replication"):
            self.reseal_inkind(INKIND_NAMES[1], replication)
            result = self.run_guard()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("component receipt derives from the recorded replication receipt", result.stdout)
            self.assertIn("generators were not run", result.stdout)
        with self.subTest(stage="both receipts resealed"):
            self.reseal_inkind_replication(replication)
            result = self.run_guard()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("out-of-pocket threshold 2025 renter", result.stdout)
            self.assertIn("generators were not run", result.stdout)

    def test_internally_consistent_inkind_edit_fails_the_cross_receipt_check(self):
        """Shift one threshold with its implicates, lift and stage effect, so
        the replication receipt agrees with itself; the component receipt
        still disagrees."""
        replication = self.inkind_replication()
        record = replication["results"]["2025"]
        for draw in record["with_in_kind_by_implicate"]:
            draw["renter"] += 5
        record["with_in_kind"]["renter"] += 5
        record["in_kind_lift_percent"]["renter"] = 100 * (
            record["with_in_kind"]["renter"] / record["without_in_kind"]["renter"] - 1
        )
        record["stage_effects"]["in_kind_dollars"]["renter"] += 5
        record["stage_effects"]["in_kind_percent"]["renter"] = record["in_kind_lift_percent"]["renter"]
        self.reseal_inkind_replication(replication)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("package run with 2025 renter", result.stdout)
        self.assertNotIn("implicate mean", result.stdout)
        self.assertNotIn("in-kind lift 2025", result.stdout)
        self.assertNotIn("in-kind stage 2025", result.stdout)
        self.assertIn("generators were not run", result.stdout)

    def test_inkind_table_drift_is_detected_without_repair(self):
        table = self.repo / "paper/tables/inkind_growth.md"
        table.write_text(table.read_text() + "| unreviewed | row | row | row |\n")
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generated output drifted: paper/tables/inkind_growth.md", result.stdout)

    def test_inkind_tables_must_be_included_in_article(self):
        article = self.repo / "paper/index.qmd"
        article.write_text(
            article.read_text().replace("{{< include tables/inkind_amounts.md >}}", "")
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("article tables never included", result.stdout)
        self.assertIn("inkind_amounts.md", result.stdout)

    def mutate_article(self, where, pattern, replacement, once=False):
        """Apply one regex edit inside a named slice of the paper. With
        once=True the pattern must match exactly once in that slice."""
        article = self.repo / "paper/index.qmd"
        text = article.read_text()
        start, end = self.article_bounds(text)[where]
        if once:
            matches = len(re.findall(pattern, text[start:end], flags=re.S))
            self.assertEqual(matches, 1, f"fixture pattern must match once, found {matches}: {pattern}")
        body, count = re.subn(pattern, replacement, text[start:end], count=1, flags=re.S)
        self.assertEqual(count, 1, f"fixture pattern missing: {pattern}")
        # A replacement that restates the matched text tests nothing.
        self.assertNotEqual(body, text[start:end], f"fixture replacement changes nothing: {pattern}")
        article.write_text(text[:start] + body + text[end:])

    @staticmethod
    def article_bounds(text):
        """Each named slice's start and end offsets in the paper."""
        return {
            "section": (text.index(INKIND_HEADING), text.index(PROJECTION_HEADING)),
            "replication": (text.index(REPLICATION_HEADING), text.index(INKIND_HEADING)),
            "abstract": PAPER_TEXT.block_scalar_span(text, "abstract") or (0, 0),
            "evaluation": (
                text.index("## Evaluation against published thresholds"),
                text.index("## Validation of the price comparator"),
            ),
            "discussion": (text.index(DISCUSSION_HEADING), text.index("# Appendix A: replication benchmark")),
            "appendix": (text.index("# Appendix B: reproducibility"), len(text)),
            "appendix B": (text.index("# Appendix B: reproducibility"), text.index("# References")),
            "price": (
                text.index("## Validation of the price comparator"),
                text.index("# Conditional forecasts beyond available microdata"),
            ),
            "sensitivity": (
                text.index("## Replicated levels and sample sensitivities"),
                text.index(INKIND_HEADING),
            ),
            "benchmark": (
                text.index("## Five-year benchmark for the 2025 nowcast"),
                text.index("# Pre-committed 2025 validation"),
            ),
            "nowcast": (
                text.index("# Pre-committed 2025 validation"),
                text.index("## Evaluation against published thresholds"),
            ),
            "appendix A": (
                text.index("# Appendix A: replication benchmark"),
                text.index("# Appendix B: reproducibility"),
            ),
        }

    def test_inkind_prose_figures_drift_from_the_receipts(self):
        for name, where, pattern, replacement, label in INKIND_PROSE_MUTATIONS:
            with self.subTest(name=name):
                self.install_article()
                self.mutate_article(where, pattern, replacement)
                result = self.run_guard()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"in-kind prose: {label}", result.stdout)
        self.install_article()

    def test_inkind_pins_reject_a_figure_borrowed_from_another_section(self):
        cases = (
            ("rental assistance share", (("supplies \\$175 and school", "supplies \\$157 and school"),),
             "difference in rises by benefit",
             "Of the \\$259 difference between the two rises, rental assistance supplies \\$175 and school "
             "lunch \\$92, and the other three benefits narrow it by \\$9."),
            ("renter split", (("5.71 percent, 0.62", "5.71 percent, 0.66"),),
             "BLS 2024-2025 renter growth without its imputed terms",
             "With its imputed benefits' terms removed from both years, it grows 5.71 percent, 0.62 points less."),
        )
        for name, edits, label, decoy in cases:
            with self.subTest(name=name):
                self.assert_article_mutation_fails(
                    name, edits, f"in-kind prose: {label}", DISCUSSION_HEADING, decoy
                )

    def edit_article(self, edits, host=None, decoy=None):
        """Apply exact single-occurrence prose edits, optionally restating the
        original figure under another heading. A call may add only the decoy,
        so the check that the fixture changed the article runs after both."""
        path = self.repo / "paper/index.qmd"
        prose = original = path.read_text()
        for old, new in edits:
            self.assertEqual(prose.count(old), 1, f"ambiguous fixture edit: {old!r}")
            prose = prose.replace(old, new)
        if host is not None:
            self.assertEqual(prose.count(host), 1, f"ambiguous fixture host: {host!r}")
            prose = prose.replace(host, f"{host}\n{decoy}\n")
        self.assertNotEqual(prose, original, f"fixture edits change nothing: {edits!r}")
        path.write_text(prose)

    def assert_article_mutation_fails(
        self, label, edits, expected, host=None, decoy=None
    ):
        self.install_article()
        self.edit_article(edits, host, decoy)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0, label)
        self.assertIn(expected, result.stdout)

    def add_abstract_decoy(self, host, decoy):
        """Restate `decoy` at one of ABSTRACT_DECOY_HOSTS."""
        if host == "discussion":
            self.edit_article((), DISCUSSION_HEADING, decoy)
            return
        path = self.repo / "paper/index.qmd"
        prose = path.read_text()
        span = PAPER_TEXT.block_scalar_span(prose, "abstract")
        self.assertIsNotNone(span, "fixture has no abstract block")
        indent = re.search(r"^( +)\S", prose[span[0] : span[1]], re.M).group(1)
        if host == "abstract":
            at, insert = span[1], f"{indent}{decoy}\n"
        elif host == "abstract start":
            at, insert = span[0], f"{indent}{decoy}\n"
        elif host == "metadata":
            at, insert = span[1], f'note: "{decoy}"\n'
        elif host == "preamble":
            at, insert = prose.index("\n# Introduction\n") + 1, f"{decoy}\n\n"
        else:
            self.fail(f"unknown decoy host: {host}")
        edited = prose[:at] + insert + prose[at:]
        inside = decoy in (PAPER_TEXT.block_words(edited, "abstract") or "")
        self.assertEqual(inside, host.startswith("abstract"), f"decoy misplaced at {host}")
        path.write_text(edited)

    def run_section_mutation(self, where, pattern, replacement, decoy=None):
        """Drift a figure in one section and run the guard. With a decoy, the
        original wording also sits under the discussion heading, just before
        the section's start heading and just after its end heading's line."""
        self.install_article()
        self.mutate_article(where, pattern, replacement, once=True)
        if decoy is not None:
            self.edit_article((), DISCUSSION_HEADING, decoy)
            article = self.repo / "paper/index.qmd"
            text = article.read_text()
            start, end = self.article_bounds(text)[where]
            if end < len(text):
                line_end = text.index("\n", end) + 1
                text = f"{text[:line_end]}\n{decoy}\n{text[line_end:]}"
            article.write_text(f"{text[:start]}{decoy}\n\n{text[start:]}")
        return self.run_guard()

    def assert_abstract_unread(self, result, reason):
        """The guard failed every tie that reads the abstract, and its
        inventory, and said once that it cannot read the abstract, with a
        reason that holds `reason`."""
        self.assertNotEqual(result.returncode, 0)
        lines = failure_lines(result.stdout)
        unread = [line for line in lines if line.startswith(ABSTRACT_UNREAD)]
        self.assertEqual(len(unread), 1, lines)
        self.assertIn(reason, unread[0])
        self.assertEqual(
            sorted(line for line in lines if line not in unread),
            sorted((*ABSTRACT_TIE_LABELS, *INKIND_ABSTRACT_TIE_LABELS, ABSTRACT_INVENTORY)),
        )

    def run_abstract_mutation(self, pattern, replacement, decoy=None, host="discussion"):
        self.install_article()
        self.mutate_article("abstract", pattern, replacement)
        if decoy is not None:
            self.add_abstract_decoy(host, decoy)
        return self.run_guard()

    def test_abstract_figures_drift_alone(self):
        """The body restates 1.17, 2.58 and 0.75, so only a tie that reads the
        abstract can catch a change made there alone."""
        for name, pattern, replacement, labels, _ in ABSTRACT_PROSE_MUTATIONS:
            with self.subTest(name=name):
                result = self.run_abstract_mutation(pattern, replacement)
                self.assertNotEqual(result.returncode, 0)
                for label in labels:
                    self.assertIn(label, failure_lines(result.stdout))
        self.install_article()

    def test_abstract_pins_reject_a_copy_restated_elsewhere(self):
        """With the original wording restated in the discussion, in another
        metadata field, in body text before the introduction or inside the
        abstract itself, only the abstract's own checks fail. A copy inside
        the abstract restates numbers the abstract already states, so the
        number check fails beside it too. A renamed rule's tie passes beside
        such a copy, which states the rule's rate, and the number check
        fails alone."""
        for host in ABSTRACT_DECOY_HOSTS:
            for name, pattern, replacement, labels, decoy in ABSTRACT_PROSE_MUTATIONS:
                with self.subTest(host=host, name=name):
                    result = self.run_abstract_mutation(pattern, replacement, decoy, host)
                    expected = set(labels)
                    if host.startswith("abstract"):
                        # A copy inside the abstract keeps the original figure
                        # there, so the ties that only look for it pass, and
                        # the ties that require every stated rate to match fail.
                        expected = {label for label in expected if not label.startswith("current projection prose")}
                        if re.search(r"\d", decoy):
                            expected.add(ABSTRACT_INVENTORY)
                            if name in ABSTRACT_RULE_RENAMES:
                                expected = {ABSTRACT_INVENTORY}
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(sorted(failure_lines(result.stdout)), sorted(expected))
        self.install_article()

    def test_abstract_number_check_counts_each_number(self):
        """The number check alone catches a number that no tie reads: a
        decimal written without its leading zero, with a decimal comma or
        split by a space, a tied figure restated in other wording, a whole
        number at a range's first end or in a contrast, the abstract's first
        lift range reversed or rounded beside a correct copy, a new year, a
        thousands separator, and a year with an apostrophe, a question mark,
        or straight or curly quotes, double or single, or followed by any
        other mark the abstract's prose allows. A range whose first end
        carries the rule's unit fails that rule's tie too, and so does the
        first lift range extended by a whole number, since the home internet
        tie reads "percent" after it. A year in parentheses before a semicolon
        or a colon passes, since the check strips ( ) , . ; : from each
        number's ends."""
        self.install_article()
        block = PAPER_TEXT.block_words((self.repo / "paper/index.qmd").read_text(), "abstract")
        # Copy the abstract's lift sentence from the first word after the
        # last period before the range through "percent", so the copy keeps
        # the lead the paper gives the range and passes the lift tie. A
        # period inside that lead starts the copy after it.
        lift = re.search(r"[^.\s][^.]*?thresholds by (\d+\.\d+) to (\d+\.\d+) percent", block)
        high = lift[2]
        renters = r"renters\."
        lift_copy = f"renters. {lift[0]}."
        # Write the last 2025 once with each mark the abstract's prose allows
        # glued to its end, leaving out whitespace and the ( ) , . ; : the
        # check strips. A strip set that takes one more mark then changes
        # the note.
        kept_marks = sorted(PAPER_TEXT.PROSE_MARKS - set("(),.;:") - {m for m in PAPER_TEXT.PROSE_MARKS if m.isspace()})
        marked_years = [f"2025{mark}" for mark in kept_marks]
        cases = (
            ("decimal without a leading zero", ((renters, "renters, at .85 percent."),), [ABSTRACT_INVENTORY]),
            ("decimal comma", ((renters, "renters, at 2,31 percent."),), [ABSTRACT_INVENTORY]),
            (
                "tied figure in other wording",
                ((renters, "renters. The blend's error of 0.75 percent leads."),),
                [ABSTRACT_INVENTORY],
            ),
            (
                "lift range reversed beside a correct copy",
                (
                    (r"by(\s+)(\d+\.\d+)(\s+)to(\s+)(\d+\.\d+)(\s+)percent", r"by\1\5\3to\4\2\6percent"),
                    (renters, lift_copy),
                ),
                [ABSTRACT_INVENTORY],
            ),
            (
                "range with the unit after its first end",
                ((r"2\.29(\s+)percent(\s+)with", r"0.90 percent to 2.29\1percent\2with"),),
                ["abstract current projection cpi_u 2.29", ABSTRACT_INVENTORY],
            ),
            ("decimal split by a space", ((renters, "renters, at 2. 31 percent."),), [ABSTRACT_INVENTORY]),
            (
                "whole number at a range's first end",
                ((r"2\.29(\s+)percent(\s+)with", r"2 percent up to 2.29\1percent\2with"),),
                [ABSTRACT_INVENTORY],
            ),
            (
                "whole number in a contrast",
                ((r"2\.29(\s+)percent(\s+)with", r"2 percent, not 2.29\1percent\2with"),),
                [ABSTRACT_INVENTORY],
            ),
            (
                "lift range rounded beside a correct copy",
                (
                    (r"by(\s+)\d+\.\d+(\s+)to(\s+)\d+\.\d+(\s+)percent", r"by\g<1>1\g<2>to\g<3>4\g<4>percent"),
                    (renters, lift_copy),
                ),
                [ABSTRACT_INVENTORY],
            ),
            (
                "lift range extended by a whole number",
                ((rf"to(\s+){re.escape(high)}(\s+)percent", f"to\\g<1>{high}\u20134\\g<2>percent"),),
                [ABSTRACT_INVENTORY, "in-kind prose: abstract home internet lift range"],
            ),
            ("year added", ((renters, "renters in 2024."),), [ABSTRACT_INVENTORY]),
            ("thousands separator", ((renters, "renters, across 10,000 records."),), [ABSTRACT_INVENTORY]),
            (
                "year with an apostrophe",
                ((r"for(\s+)2025(\s+)only", r"for\g<1>2025's\g<2>thresholds only"),),
                [ABSTRACT_INVENTORY],
            ),
            (
                "year with a question mark",
                ((r"for(\s+)2025(\s+)only\.", r"for\g<1>one\g<2>year only: why 2025?"),),
                [ABSTRACT_INVENTORY],
            ),
            ("year in double quotes", ((r"for(\s+)2025(\s+)only", r'for\g<1>"2025"\g<2>only'),), [ABSTRACT_INVENTORY]),
            ("year in single quotes", ((r"for(\s+)2025(\s+)only", r"for\g<1>'2025'\g<2>only"),), [ABSTRACT_INVENTORY]),
            (
                "year in curly double quotes",
                ((r"for(\s+)2025(\s+)only", "for\\g<1>\u201c2025\u201d\\g<2>only"),),
                [ABSTRACT_INVENTORY],
            ),
            (
                "year in curly single quotes",
                ((r"for(\s+)2025(\s+)only", "for\\g<1>\u20182025\u2019\\g<2>only"),),
                [ABSTRACT_INVENTORY],
            ),
            (
                "year followed by each mark the check keeps",
                ((r"for(\s+)2025(\s+)only\.", rf"for\g<1>one\g<2>year only: {' '.join(marked_years)}."),),
                [ABSTRACT_INVENTORY],
            ),
        )
        # The line the guard prints under its failures, which counts each
        # number as often as the abstract states it.
        notes = {
            "tied figure in other wording": "    the abstract states ['0.75'] beyond the lists and lacks []",
            "lift range extended by a whole number": (
                f"    the abstract states ['{high}\u20134'] beyond the lists and lacks ['{high}']"
            ),
            "year added": "    the abstract states ['2024'] beyond the lists and lacks []",
            "year with an apostrophe": """    the abstract states ["2025's"] beyond the lists and lacks ['2025']""",
            "year with a question mark": "    the abstract states ['2025?'] beyond the lists and lacks ['2025']",
            "year in double quotes": """    the abstract states ['"2025"'] beyond the lists and lacks ['2025']""",
            "year in single quotes": """    the abstract states ["'2025'"] beyond the lists and lacks ['2025']""",
            "year in curly double quotes": (
                "    the abstract states ['\u201c2025\u201d'] beyond the lists and lacks ['2025']"
            ),
            "year in curly single quotes": (
                "    the abstract states ['\u20182025\u2019'] beyond the lists and lacks ['2025']"
            ),
            "year followed by each mark the check keeps": (
                f"    the abstract states {sorted(marked_years)} beyond the lists and lacks ['2025']"
            ),
        }
        for name, edits, labels in cases:
            with self.subTest(case=name):
                self.install_article()
                for pattern, replacement in edits:
                    self.mutate_article("abstract", pattern, replacement)
                result = self.run_guard()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(sorted(failure_lines(result.stdout)), sorted(labels))
                if name in notes:
                    self.assertIn(notes[name], result.stdout.splitlines())
        for name, replacement in (
            ("year in parentheses before a semicolon", r"for\g<1>one\g<2>year (2025); later years wait."),
            ("year in parentheses before a colon", r"for\g<1>one\g<2>year (2025): the nowcast's."),
        ):
            with self.subTest(case=name):
                self.install_article()
                self.mutate_article("abstract", r"for(\s+)2025(\s+)only\.", replacement)
                result = self.run_guard()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.install_article()

    def test_abstract_tie_fails_on_a_word_in_its_slot(self):
        """A tie requires every statement of its wording to hold a number its
        slot reads, so a figure spelled out in that wording fails the tie
        beside a correct copy, while the number check, which reads numerals
        alone, passes."""
        self.install_article()
        self.mutate_article(
            "abstract",
            r"renters\.",
            "renters. Rents rose two percent with the Consumer Price Index for All Urban Consumers (CPI-U).",
        )
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(failure_lines(result.stdout), ["abstract current projection cpi_u 2.29"])
        self.install_article()

    def test_abstract_ties_ignore_the_introduction_heading(self):
        """The abstract block ends with the front matter, so renaming, demoting,
        repeating or moving the introduction heading leaves the ties reading
        the same text, and a drifted figure still fails alone."""
        decoy = "The blend yields a mean absolute error of 1.17 percent."
        cases = (
            ("renamed introduction", (("# Introduction\n", "# Background\n"),)),
            ("demoted introduction", (("# Introduction\n", "## Introduction\n"),)),
            (
                "repeated introduction",
                ((DISCUSSION_HEADING, "# Introduction\n\n" + DISCUSSION_HEADING),),
            ),
            (
                "moved introduction after a decoy",
                (
                    ("# Introduction\n", "# Background\n"),
                    (DISCUSSION_HEADING, f"{decoy}\n\n## Introduction\n\n{DISCUSSION_HEADING}"),
                ),
            ),
        )
        for name, edits in cases:
            with self.subTest(case=name):
                self.install_article()
                self.edit_article(edits)
                unchanged = self.run_guard()
                self.assertEqual(unchanged.returncode, 0, unchanged.stdout)
                self.mutate_article("abstract", r"1\.17(\s+)percent", r"1.18\1percent")
                drifted = self.run_guard()
                self.assertEqual(
                    sorted(failure_lines(drifted.stdout)),
                    sorted([ABSTRACT_INVENTORY, "abstract evaluation amended MAE 1.17"]),
                )
        self.install_article()

    def test_abstract_ties_skip_wording_outside_the_block(self):
        """Wording the abstract dropped cannot satisfy the ties that read it
        from a comment after the block, which YAML ends at a line indented
        less than the block, or from a field before the abstract's key."""
        cases = (
            (
                "CPI-U rule renamed",
                r"with(\s+)the(\s+)Consumer(\s+)Price(\s+)Index",
                r"with\1the\2CPI-U\3price\4index",
                "2.29 percent with the Consumer Price Index for All Urban Consumers (CPI-U)",
                ["abstract current projection cpi_u 2.29"],
            ),
            (
                "stage-change range reworded",
                r"points(\s+)per(\s+)tenure",
                r"points\1per\2household",
                "We estimate that they raise thresholds by a further 0.5 to 3.5 percent and change 2022–2025 "
                "growth by −1.63 to −0.17 points per tenure with the CE's spending summaries, each change within "
                "one standard error of zero.",
                [
                    "in-kind prose: abstract stage-change range",
                    "in-kind prose: abstract and discussion: each change within one standard error",
                ],
            ),
        )
        places = {
            "comment after the block": lambda prose, span, old: (span[1], f" # {old}\n"),
            "field before the key": lambda prose, span, old: (
                prose.index("\nabstract: |\n") + 1,
                f"keywords: {json.dumps(old, ensure_ascii=False)}\n",
            ),
        }
        for name, pattern, replacement, old, labels in cases:
            for place, insert in places.items():
                with self.subTest(case=name, place=place):
                    self.install_article()
                    self.mutate_article("abstract", pattern, replacement)
                    path = self.repo / "paper/index.qmd"
                    prose = path.read_text()
                    span = PAPER_TEXT.block_scalar_span(prose, "abstract")
                    self.assertIsNotNone(span, "fixture has no abstract block")
                    at, text = insert(prose, span, old)
                    path.write_text(prose[:at] + text + prose[at:])
                    result = self.run_guard()
                    self.assertEqual(sorted(failure_lines(result.stdout)), sorted(labels))
        self.install_article()

    def test_abstract_block_fails_closed_unless_one_key_sets_the_abstract(self):
        """A folded, repeated, nested, hidden or relocated `abstract: |` key, a
        metadata block in the body or in a grid table's cell, or a carriage
        return without a line feed empties the abstract slice. Every tie that
        reads the abstract fails, instead of reading text that the paper may
        not render as its abstract, and the guard says why."""
        prose = (self.repo / "paper/index.qmd").read_text()
        span = PAPER_TEXT.block_scalar_span(prose, "abstract")
        self.assertIsNotNone(span, "fixture has no abstract block")
        block = prose[span[0] : span[1]]
        key = "abstract: |\n"
        other = "other than on a top-level abstract: | line"
        unread = "is YAML the guard does not read"
        lone = "holds a carriage return without a line feed"
        cases = (
            ("folded abstract", ((key, "abstract: >\n"),), other),
            ("key line with a comment", ((key, "abstract: | # summary\n"),), other),
            ("repeated abstract key", ((block, block + key + block),), "the front matter sets abstract on lines"),
            (
                "abstract key only in the body",
                ((key, "summary: |\n"), ("\n# Introduction\n", f"\n{key}{block}\n# Introduction\n")),
                "the front matter has no top-level abstract: | line",
            ),
            ("quoted abstract key repeated", ((block, f'{block}"abstract": |\n{block}'),), unread),
            (
                "body metadata block sets the abstract",
                ((DISCUSSION_HEADING, f"---\n{key}{block}---\n\n{DISCUSSION_HEADING}"),),
                "in the body, could set abstract",
            ),
            (
                "format-level abstract",
                (("    toc: true\n", "    toc: true\n    abstract: |\n      A copy for the web.\n"),),
                other,
            ),
            (
                "explicit key with a comment in a body block",
                ((DISCUSSION_HEADING, f"---\n? abstract # set here\n: |\n  A copy.\n---\n\n{DISCUSSION_HEADING}"),),
                "in the body, could set abstract",
            ),
            (
                "escaped key in a body block",
                ((DISCUSSION_HEADING, f'---\n"\\x61bstract": A copy.\n---\n\n{DISCUSSION_HEADING}'),),
                "could open a metadata block",
            ),
            (
                "grid table holding a metadata block",
                (
                    (
                        DISCUSSION_HEADING,
                        "+-------------------+\n| ---               |\n| abstract: A copy. |\n"
                        f"| ---               |\n+-------------------+\n\n{DISCUSSION_HEADING}",
                    ),
                ),
                "grid table's border",
            ),
            ("lone carriage return in the front matter", ((key, "toc-title: Contents\r" + key),), lone),
            (
                "lone carriage return before a body metadata block",
                ((DISCUSSION_HEADING, f"Text.\r\r---\rabstract: A copy.\r---\r\r{DISCUSSION_HEADING}"),),
                lone,
            ),
            (
                "tagged format-level abstract",
                (("    toc: true\n", "    toc: true\n    !!str abstract: A copy for the web.\n"),),
                unread,
            ),
            (
                "anchored format-level abstract after an apostrophe",
                (("    toc: true\n", "    toc: true\n    subtitle: Rents in the '90s\n    &k abstract: A copy.\n"),),
                unread,
            ),
            (
                "quote left open over the key line",
                (("    toc: true\n", "    toc: true\n    pagetitle: 'Thresholds\n"),),
                unread,
            ),
            (
                "comment glued to a format-level abstract",
                (("    toc: true\n", "    toc: true\n    <!-- -->abstract: A copy for the web.\n"),),
                "holds an HTML comment or a code fence",
            ),
        )
        for name, edits, reason in cases:
            with self.subTest(case=name):
                self.install_article()
                self.edit_article(edits)
                self.assert_abstract_unread(self.run_guard(), reason)
        self.install_article()

    def test_abstract_markup_fails_every_abstract_tie(self):
        """Quarto renders emphasis, an HTML comment, a code fence, a
        shortcode, raw content, TeX, an entity, a div, a list, a heading's
        underline or a definition in the abstract as other text or none, so
        each fails every tie that reads the abstract, even when it restates
        the abstract's own wording, and the guard names the first character
        outside plain prose or the line that opens the other block."""
        decoy = ABSTRACT_PROSE_MUTATIONS[0][4]
        for name, line, reason in (
            ("emphasis", f"*{decoy}*", "holds '*'"),
            ("underscore emphasis", f"_{decoy}_", "holds '_'"),
            ("HTML comment", f"<!-- {decoy} -->", "holds '<'"),
            ("code fence", f"```\n{decoy}\n```", "holds '`'"),
            ("shortcode", "{{< meta title >}}", "holds '{'"),
            ("raw content", "`\\newpage`{=latex}", "holds '`'"),
            ("TeX command", f"\\phantom{{{decoy}}}", "holds '\\\\'"),
            ("TeX conditional", f"\\iffalse\n{decoy}\n\\fi", "holds '\\\\'"),
            ("HTML entity", "&minus;2.29 percent", "holds '&'"),
            ("div", f"::: hidden\n{decoy}\n:::", "holds ':::'"),
            ("list", f"\n- {decoy}", "opens a paragraph with '-'"),
            ("heading underline", "---", "holds only hyphens or plus signs"),
            ("definition", f": {decoy}", "opens with ':'"),
        ):
            with self.subTest(case=name):
                self.install_article()
                path = self.repo / "paper/index.qmd"
                prose = path.read_text()
                span = PAPER_TEXT.block_scalar_span(prose, "abstract")
                self.assertIsNotNone(span, "fixture has no abstract block")
                indent = re.search(r"^( +)\S", prose[span[0] : span[1]], re.M).group(1)
                lines = "".join(f"{indent}{part}\n" for part in line.split("\n"))
                path.write_text(prose[: span[1]] + lines + prose[span[1] :])
                self.assert_abstract_unread(self.run_guard(), reason)
        self.install_article()

    def test_abstract_comes_only_from_the_paper(self):
        """Quarto merges project and directory metadata into the paper's, so
        an abstract or a metadata-files list in any of those files, or a
        metadata-files list in the paper, fails the guard, while the paper's
        own abstract still passes every tie."""
        label = "only paper/index.qmd may set the abstract or name metadata files"
        cases = (
            ("project file", "_quarto.yml", "abstract: A copy.\n"),
            ("project format", "_quarto.yml", "format:\n  html:\n    abstract: A copy.\n"),
            ("project profile", "_quarto-web.yml", "abstract: A copy.\n"),
            ("local project file", "_quarto.yml.local", "abstract: A copy.\n"),
            ("paper folder metadata", "paper/_metadata.yml", "abstract: A copy.\n"),
            ("root metadata", "_metadata.yml", "format: {pdf: {abstract: A copy.}}\n"),
            ("project metadata files", "_quarto.yml", "metadata-files: [extra.yml]\n"),
            ("paper metadata files", "paper/index.qmd", "metadata-files:\n  - extra.yml\n"),
        )
        for name, relative, addition in cases:
            with self.subTest(case=name):
                self.install_article()
                path = self.repo / relative
                original = path.read_text() if path.exists() else None
                if relative == "paper/index.qmd":
                    path.write_text(original.replace("abstract: |\n", addition + "abstract: |\n", 1))
                else:
                    path.write_text((original or "") + addition)
                try:
                    result = self.run_guard()
                finally:
                    if original is None:
                        path.unlink()
                    else:
                        path.write_text(original)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(failure_lines(result.stdout), [label])
        self.install_article()
        # An included file's front matter would set the abstract too.
        (self.repo / "paper/notes.qmd").write_text("---\nabstract: |\n  A copy.\n---\n\nNotes.\n")
        for directive in (
            "{{< include notes.qmd >}}",
            '{{< include "notes.qmd" >}}',
            '{{< include "tables/../notes.qmd" >}}',
            "{{< include tables/../notes.qmd >}}",
            "{{< include 'tables/sub/../../notes.qmd' >}}",
        ):
            with self.subTest(case=directive):
                self.install_article()
                article = self.repo / "paper/index.qmd"
                article.write_text(article.read_text() + "\n" + directive + "\n")
                result = self.run_guard()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(
                    failure_lines(result.stdout),
                    ["paper/index.qmd may include only the generated tables, as tables/<name>.md"],
                )
        (self.repo / "paper/notes.qmd").unlink()
        self.install_article()

    def test_section_figures_drift_alone(self):
        """A figure changed in the section that states it fails its tie, even
        where the paper states the same numeral in another section."""
        for name, where, pattern, replacement, labels, _ in SECTION_PROSE_MUTATIONS:
            with self.subTest(name=name):
                result = self.run_section_mutation(where, pattern, replacement)
                self.assertNotEqual(result.returncode, 0)
                for label in labels:
                    self.assertIn(label, failure_lines(result.stdout))
        self.install_article()

    def test_section_pins_reject_a_figure_restated_elsewhere(self):
        """With the original wording restated under the discussion heading
        and on each side of the section's headings, only the ties that read
        the changed section fail."""
        for name, where, pattern, replacement, labels, decoy in SECTION_PROSE_MUTATIONS:
            with self.subTest(name=name):
                result = self.run_section_mutation(where, pattern, replacement, decoy)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(sorted(failure_lines(result.stdout)), sorted(labels))
        self.install_article()

    def test_phrase_miss_report_names_the_missing_phrase(self):
        """When a pin's figure still occurs in its section but a phrase
        doesn't, the report names the phrase after the failures and after
        any note that #13's abstract number check prints. A changed figure
        adds no phrase line."""
        result = self.run_section_mutation("evaluation", r"renter(\s+)difference", r"renter\1gap")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(failure_lines(result.stdout), ["owner misses within one SE; renter about 2.4 SE"])
        self.assertIn("Phrases missing from sections that hold the pin's figure:", result.stdout)
        self.assertIn(
            "'2.4 standard errors' occurs in the section; "
            "'renter difference reaches about 2.4 standard errors' doesn't",
            result.stdout,
        )
        result = self.run_section_mutation("evaluation", r"about(\s+)2\.4(\s+)standard", r"about\g<1>2.5\2standard")
        self.assertEqual(failure_lines(result.stdout), ["owner misses within one SE; renter about 2.4 SE"])
        self.assertNotIn("Phrases missing", result.stdout)
        # This paper also fails #13's abstract number check, so the guard
        # prints that check's note, then the phrase §6.2 misses.
        self.install_article()
        self.mutate_article("abstract", r"renters\.", "renters in 2024.", once=True)
        self.mutate_article("evaluation", r"giving(\s+)a(\s+)mean(\s+)absolute(\s+)error", r"giving\1an\2error", once=True)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            sorted(failure_lines(result.stdout)),
            ["abstract states exactly the numbers the guard lists, each as a bare number", "evaluation amended MAE 1.17"],
        )
        lines = result.stdout.splitlines()
        last = max(index for index, line in enumerate(lines) if line.startswith("  - "))
        self.assertEqual(
            lines[last + 1 :],
            [
                "    the abstract states ['2024'] beyond the lists and lacks []",
                "Phrases missing from sections that hold the pin's figure:",
                "    '1.17' occurs in the section; 'giving a mean absolute error of 1.17 percent' doesn't",
            ],
        )
        self.install_article()

    def test_section_slices_fail_closed_without_unique_markers(self):
        """A renamed or repeated heading empties the slices it bounds, so
        their ties fail instead of reading the whole paper."""
        for name, edits, labels in SECTION_MARKER_CASES:
            with self.subTest(case=name):
                self.install_article()
                self.edit_article(edits)
                result = self.run_guard()
                self.assertNotEqual(result.returncode, 0)
                failures = failure_lines(result.stdout)
                for label in labels:
                    self.assertIn(label, failures)
        self.install_article()

    def run_respaced(self, where, spacing, literal=None):
        """Put `spacing` in place of each space between two words on the
        section's lines that don't start with '#', or only inside each
        whole-token occurrence of the literal, and run the guard."""
        self.install_article()
        article = self.repo / "paper/index.qmd"
        text = article.read_text()
        start, end = self.article_bounds(text)[where]
        if literal is None:
            body = "".join(
                line if line.startswith("#") else re.sub(r"(?<=\S) (?=\S)", spacing, line)
                for line in text[start:end].splitlines(keepends=True)
            )
        else:
            body = re.sub(
                rf"(?<!\w){re.escape(literal)}(?!\w)",
                lambda match: match.group(0).replace(" ", spacing),
                text[start:end],
            )
        self.assertNotEqual(body, text[start:end], f"nothing to respace in {where}: {literal!r}")
        article.write_text(text[:start] + body + text[end:])
        return self.run_guard()

    def test_each_raw_literal_fails_only_its_tie_when_respaced(self):
        """Each spacing in place of the spaces inside one literal fails the
        tie that searches the raw slice for it, and no other tie. A tie that
        maps that spacing back to a space, as normalized() does, passes the
        paper, whatever code hands it that text."""
        for where, literal, label in RAW_LITERALS:
            for spacing in SPACINGS:
                with self.subTest(where=where, literal=literal, spacing=spacing):
                    result = self.run_respaced(where, spacing, literal)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(failure_lines(result.stdout), [label])
        self.install_article()

    def test_every_whitespace_character_fails_every_raw_literal_tie(self):
        """Each spacer, a whitespace character other than a space or a run
        of whitespace, in place of spaces inside raw literals fails the ties
        that read them, on each paper whitespace_papers() lists. If a guard
        maps the spacer back to a space anywhere between the file and a
        tie's match, and the mapping lets the tie pass one of these papers,
        this test fails, whatever route the code takes, so it doesn't depend
        on the source checks' model of the guard. For each nonempty set of a
        tie's spaces, some paper respaces that set and no other space of the
        tie. A mapping of a spacer this test tries therefore gets past the
        test only if the mapping depends on more than that spacer in the
        tie's own spaces. The mapping can depend on other text in the paper,
        whether that text holds a spacer or not, on a mix of spacers or on
        how or where the guard runs. The test always runs the guard with -B
        in a checkout named paper. The test's papers respace most sets of a
        tie's spaces only beside another tie's respaced literal in the same
        section. A mapping of such a set that fires only when no other copy
        of its spacer sits in the section therefore gets past. A mapping of
        a run the test doesn't try gets past too."""
        for name, rows in whitespace_papers():
            hosts = list(dict.fromkeys(where for where, _, _, _ in rows))
            labels = {label for _, _, label, _ in rows}
            for spacer in SPACERS:
                with self.subTest(paper=name, sections=", ".join(hosts), spacer=spacer):
                    self.install_article()
                    article = self.repo / "paper/index.qmd"
                    text = article.read_text()
                    bounds = self.article_bounds(text)
                    for where in sorted(hosts, key=lambda host: bounds[host][0], reverse=True):
                        start, end = bounds[where]
                        spaces = {literal: held for host, literal, _, held in rows if host == where}
                        pattern = "|".join(rf"(?<!\w){re.escape(literal)}(?!\w)" for literal in sorted(spaces, key=len, reverse=True))

                        def respace(match, spaces=spaces, spacer=spacer):
                            first, *words = match.group(0).split(" ")
                            held = spaces[match.group(0)]
                            return first + "".join(
                                (spacer if position in held else " ") + word for position, word in enumerate(words, 1)
                            )

                        body = re.sub(pattern, respace, text[start:end])
                        self.assertNotEqual(body, text[start:end])
                        text = text[:start] + body + text[end:]
                    article.write_text(text)
                    result = self.run_guard()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertLessEqual(labels, set(failure_lines(result.stdout)))
        self.install_article()

    def test_respaced_sections_fail_exactly_the_raw_literal_ties(self):
        """Each spacing in place of every space between two words in a
        section fails exactly the ties RAW_LITERALS lists for the section, so
        the table names every tie that searches the section's raw slice for a
        literal with a space in it."""
        for where in dict.fromkeys(where for where, _, _ in RAW_LITERALS):
            expected = sorted({label for host, _, label in RAW_LITERALS if host == where})
            for spacing in SPACINGS:
                with self.subTest(where=where, spacing=spacing):
                    result = self.run_respaced(where, spacing)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(sorted(failure_lines(result.stdout)), expected)
        self.install_article()

    def test_abstract_reads_past_a_byte_order_mark(self):
        """The guard reads the paper as UTF-8 and drops a byte order mark at
        its start, so an editor that adds one leaves every tie passing."""
        self.install_article()
        path = self.repo / "paper/index.qmd"
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.install_article()

    def test_rolling_prose_figures_drift_from_the_sealed_forecast(self):
        for label, edits, _, _, expected in ROLLING_PROSE_MUTATIONS:
            with self.subTest(figure=label):
                self.assert_article_mutation_fails(label, edits, expected)

    def test_reproducibility_identity_matches_the_sealed_forecast(self):
        provenance = json.loads(
            (self.repo / "data/current/rolling_provenance.json").read_text()
        )
        appendix = (
            (self.repo / "paper/index.qmd")
            .read_text()
            .split("# Appendix B: reproducibility {.unnumbered}", 1)[1]
            .split("# References {.unnumbered}", 1)[0]
        )
        for key in ("calculator_commit", "content_sha256"):
            with self.subTest(identity=key):
                self.assertIn(provenance[key], appendix)

    def test_reproducibility_identity_cannot_be_borrowed_from_another_section(self):
        provenance = json.loads(
            (self.repo / "data/current/rolling_provenance.json").read_text()
        )
        for key in ("calculator_commit", "content_sha256"):
            with self.subTest(identity=key):
                identity = provenance[key]
                self.assert_article_mutation_fails(
                    key,
                    ((identity, "0" * len(identity)),),
                    "rolling reproducibility identity",
                    DISCUSSION_HEADING,
                    f"The recorded {key} is `{identity}`.",
                )

    def test_rolling_pins_reject_a_figure_borrowed_from_another_section(self):
        """The same numeral stated correctly elsewhere must not rescue a
        drifted figure: 31 already appears in a tbl-colwidths attribute and
        seven in "seven target years", so an unscoped pin would pass."""
        for label, edits, host, decoy, expected in ROLLING_PROSE_MUTATIONS:
            with self.subTest(figure=label):
                self.assert_article_mutation_fails(label, edits, expected, host, decoy)

    def test_rolling_section_headings_must_be_present_and_unique(self):
        cases = (
            (
                "removed anchor",
                "# Conditional forecasts beyond available microdata {#sec-rolling}",
                "# Conditional forecasts beyond available microdata",
            ),
            (
                "duplicated subsection",
                "## Projecting local relative housing costs",
                "## Projecting local relative housing costs\n\n"
                "## Projecting local relative housing costs",
            ),
        )
        for label, old, new in cases:
            with self.subTest(heading=label):
                self.assert_article_mutation_fails(
                    label, [(old, new)], "paper section heading not unique"
                )

    def reseal_rolling_artifact(self, artifact):
        """Reseal a mutated forecast end to end — content digest, assumption
        digest, provenance, manifest and the calculator byte pins — so the pin
        under test is the only thing left that can fail."""

        def canonical(value):
            return hashlib.sha256(
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode()
            ).hexdigest()

        path = self.repo / "data/current" / ROLLING_NAME
        inputs = self.repo / "scripts/rolling_inputs.py"
        source = inputs.read_text()
        for old in (
            json.loads(path.read_text())["content_sha256"],
            hashlib.sha256(path.read_bytes()).hexdigest(),
        ):
            self.assertIn(old, source)
        artifact["assumption_sha256"] = canonical(artifact["assumptions"])
        artifact["content_sha256"] = canonical(
            {k: v for k, v in artifact.items() if k != "content_sha256"}
        )
        path.write_text(json.dumps(artifact))
        provenance_path = self.repo / "data/current/rolling_provenance.json"
        provenance = json.loads(provenance_path.read_text())
        source = source.replace(
            provenance["content_sha256"], artifact["content_sha256"]
        )
        source = source.replace(
            provenance["artifact_sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
        )
        provenance["content_sha256"] = artifact["content_sha256"]
        provenance["assumption_sha256"] = artifact["assumption_sha256"]
        provenance["artifact_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        provenance_path.write_text(json.dumps(provenance))
        inputs.write_text(source)
        self.refresh_rolling_manifest()

    def test_rolling_rate_pins_follow_the_artifact_not_a_fixed_literal(self):
        """Reseal the forecast at a different real-growth rate and leave the
        prose untouched: a hardcoded 0.914 would still pass."""
        path = self.repo / "data/current" / ROLLING_NAME
        artifact = json.loads(path.read_text())
        applied_log_rate = math.log(1.00924)
        fit = artifact["assumptions"]["real_growth_fit"]
        fit["applied_log_rate"] = applied_log_rate
        fit["log_slope"] = fit["annual_log_slope"] = applied_log_rate * 2
        fit["shrunk_annual_rate"] = fit["annual_rate"] = math.exp(applied_log_rate) - 1
        fit["unshrunk_annual_rate"] = math.exp(applied_log_rate * 2) - 1
        artifact["scenarios"]["ce_trend"]["real_growth_rate"] = fit[
            "shrunk_annual_rate"
        ]
        self.reseal_rolling_artifact(artifact)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rolling applied real-growth rate 0.924", result.stdout)

    def test_rolling_geography_pins_follow_the_artifact_not_a_fixed_literal(self):
        """Reseal one area out of the published menu: the menu, validation and
        thin-support pins must all move with the forecast, not with the prose."""
        path = self.repo / "data/current" / ROLLING_NAME
        artifact = json.loads(path.read_text())
        for scenario in artifact["scenarios"].values():
            for record in scenario["years"].values():
                anchored = next(
                    key
                    for key, area in record["geography_by_area"].items()
                    if area["anchor_status"] == "published_anchor"
                )
                record["geography_by_area"][anchored]["anchor_status"] = (
                    "modeled_unanchored"
                )
                for diagnostic in record["median_diagnostics"].values():
                    diagnostic["thin_support"] = False
        artifact["validation"]["acs"]["area_count"] -= 1
        self.reseal_rolling_artifact(artifact)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        for expected in (
            "rolling area menu prose",
            "rolling geographic validation covers 340",
            "rolling thin-donor warnings cover 0",
        ):
            self.assertIn(expected, result.stdout)


INCLUDE_TARGETS = r"\{\{<\s*include\s+(.*?)\s*>\}\}"
METADATA_SCAN = r"metadata-files?"
PAPER_NAMES = ("QMD", "QMD_RAW")


def whole_paper_reads(source):
    """Each place in a guard's source that reads the paper outside a bounded
    slice: a load of QMD or QMD_RAW other than a slicer's default text, the
    guard's scan for include directives and its search for a metadata-files
    key, each in its exact call; a slicer call that reads the paper without a
    literal end heading;
    and a path-like string, one without whitespace, that names a .qmd file
    outside the assignments of QMD and QMD_RAW."""
    tree = ast.parse(source)
    allowed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in (
            "section_source",
            "section",
            "front_matter_block",
            "front_matter_source",
        ):
            allowed.update(
                id(default)
                for default in node.args.defaults + node.args.kw_defaults
                if isinstance(default, ast.Name) and default.id in PAPER_NAMES
            )
        elif (
            isinstance(node, ast.Call)
            and len(node.args) == 2
            and not node.keywords
            and isinstance(node.args[0], ast.Constant)
            and (ast.unparse(node.func), node.args[0].value)
            in (("re.findall", INCLUDE_TARGETS), ("re.search", METADATA_SCAN))
        ):
            allowed.add(id(node.args[1]))
        elif isinstance(node, ast.Assign) and [ast.unparse(target) for target in node.targets] in (
            ["QMD"],
            ["QMD_RAW"],
        ):
            allowed.update(id(part) for part in ast.walk(node.value) if isinstance(part, ast.Constant))
    reads = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and node.id in PAPER_NAMES
            and isinstance(node.ctx, ast.Load)
            and id(node) not in allowed
        ):
            reads.append(f"line {node.lineno}: {node.id}")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("section_source", "section")
        ):
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            end = node.args[1] if len(node.args) > 1 else keywords.get("end")
            reads_paper = len(node.args) < 3 and "text" not in keywords
            literal_end = isinstance(end, ast.JoinedStr) or (
                isinstance(end, ast.Constant) and isinstance(end.value, str)
            )
            if reads_paper and not literal_end:
                reads.append(f"line {node.lineno}: {ast.unparse(node)}")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and re.fullmatch(r"\S*\.qmd", node.value)
            and id(node) not in allowed
        ):
            reads.append(f"line {node.lineno}: {node.value!r} names a .qmd file")
    return reads


def guard_function(name, **namespace):
    """One function from the guard's source, defined in ``namespace``
    without running the guard."""
    tree = ast.parse((REPO / "scripts/check_paper.py").read_text())
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module([node], []), "check_paper.py", "exec"), {"re": re, **namespace}, namespace)
    return namespace[name]


# Each slicer that returns raw text, and the position of its text argument.
RAW_SLICERS = {"section_source": 2, "front_matter_source": 1}
# Functions the raw-text check relies on, which the guard must define once.
RAW_TEXT_FUNCTIONS = ("stated", "section_source", "front_matter_source", "normalized")
# Ways to bind a name that the check can't follow.
DYNAMIC_BINDERS = ("globals", "vars", "locals", "exec", "eval", "setattr", "__import__")


def raw_slices(tree):
    """The names a guard binds once in all its source, at module level, to a
    section_source() or front_matter_source() call whose text is the paper or
    another such name, alone or as a conditional whose other branch is an
    empty string; and how many times the source binds each name."""
    bindings = {}

    def bind(name):
        bindings[name] = bindings.get(name, 0) + 1

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bind(node.id)
        elif isinstance(node, ast.arg):
            bind(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bind(node.name)
        elif isinstance(node, ast.alias):
            bind((node.asname or node.name).split(".")[0])
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
            bind(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            bind(node.rest)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for name in node.names:
                bind(name)
    once = {
        node.targets[0].id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and bindings[node.targets[0].id] == 1
    }
    paper = {name for name in PAPER_NAMES if name in once}
    raw = set()

    def raw_slice(value):
        if isinstance(value, ast.IfExp):
            return raw_slice(value.body) and isinstance(value.orelse, ast.Constant) and value.orelse.value == ""
        if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in RAW_SLICERS):
            return False
        position = RAW_SLICERS[value.func.id]
        if len(value.args) > position + 1 or any(isinstance(arg, ast.Starred) for arg in value.args):
            return False
        texts = value.args[position:]
        for keyword in value.keywords:
            if keyword.arg is None:
                return False
            if keyword.arg == "text":
                texts.append(keyword.value)
        return all(isinstance(each, ast.Name) and each.id in paper | raw for each in texts)

    while True:
        grown = {name for name, value in once.items() if raw_slice(value)}
        if grown == raw:
            break
        raw = grown
    return raw, bindings


def stated_reads_off_raw_text(source):
    """Each stated() call in a guard's source that reads anything but a raw
    slice of the paper, each use of stated() other than a direct call, each
    second binding of stated, section_source, front_matter_source or
    normalized, and each use of globals, vars, locals, exec, eval, setattr,
    __import__ or __dict__. A raw slice is a name the guard binds once in all
    its source, at module level, to a section_source() or
    front_matter_source() call whose text is the paper or another raw slice,
    alone or as a conditional whose other branch is an empty string."""
    tree = ast.parse(source)
    raw, bindings = raw_slices(tree)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "stated"
    ]
    direct = {id(node.func) for node in calls}
    return [
        f"line {node.lineno}: {ast.unparse(node)}"
        for node in calls
        if not (len(node.args) > 1 and isinstance(node.args[1], ast.Name) and node.args[1].id in raw)
    ] + [
        f"line {node.lineno}: stated used other than in a direct call"
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "stated" and isinstance(node.ctx, ast.Load) and id(node) not in direct
    ] + [
        f"{name} bound {bindings[name]} times"
        for name in RAW_TEXT_FUNCTIONS
        if bindings.get(name, 0) > 1
    ] + [
        f"line {node.lineno}: {ast.unparse(node)} can rebind a name out of the check's sight"
        for node in ast.walk(tree)
        if (isinstance(node, ast.Name) and node.id in DYNAMIC_BINDERS)
        or (isinstance(node, ast.Attribute) and node.attr == "__dict__")
    ]


# Each function that may take a raw slice, with the position and the keyword
# that hand it the text.
RAW_TEXT_READERS = {
    "stated": (1, None),
    "has_number": (None, "text"),
    "has_ordered": (None, "text"),
    "pinned_links": (1, "text"),
    "normalized": (0, "text"),
    "section_source": (2, "text"),
    "front_matter_source": (1, "text"),
}
# How the guard finds the repository and reads the paper: as text, and as
# stored.
PAPER_READS = {
    "REPO": "Path(__file__).resolve().parent.parent",
    "QMD": '(REPO / "paper" / "index.qmd").read_text()',
    "QMD_RAW": '(REPO / "paper" / "index.qmd").read_bytes().decode("utf-8-sig")',
}
# The functions whose bodies may call a raw slicer.
SLICER_BODIES = ("section_source", "section", "front_matter_block", "front_matter_source")
# The functions between the file and a raw tie's match, and what they read.
RAW_TEXT_HELPERS = SLICER_BODIES + ("bounded", "has_number", "has_ordered", "normalized", "stated", "pinned_links")
ONCE_BOUND = RAW_TEXT_HELPERS + PAPER_NAMES + ("REPO", "re", "Path", "failures", "phrase_misses")
# The one attribute the guard may set.
ATTRIBUTE_WRITES = ("sys.dont_write_bytecode",)


def raw_text_detours(source):
    """Each place in a guard's source where text could change between the
    paper and a tie that reads a raw slice: a read of the paper other than
    PAPER_READS; a raw slicer called outside SLICER_BODIES other than to bind
    a raw slice; a raw slice read other than as the text RAW_TEXT_READERS
    names; a string or attribute that names a raw slice, or any use of
    sys.modules, which can reach a slice by name; a second binding of a name
    in ONCE_BOUND, or any binding of a builtin's name; a write to or deletion
    of an attribute other than ATTRIBUTE_WRITES, which can patch a module or
    class the helpers use; any attribute whose name starts with an
    underscore; and any use of the names in DYNAMIC_BINDERS or delattr."""
    tree = ast.parse(source)
    raw, bindings = raw_slices(tree)
    parent = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    reads = {name: [] for name in PAPER_READS}
    binds = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            reads.get(name, []).append(node.value)
            if name in raw:
                binds.update({id(node.value), id(getattr(node.value, "body", node.value))})
    detours = [
        f"{name} read other than as {PAPER_READS[name]}"
        for name, values in reads.items()
        if [ast.dump(value) for value in values] != [ast.dump(ast.parse(PAPER_READS[name], mode="eval").body)]
    ] + [
        f"{name} bound {count} times"
        for name, count in bindings.items()
        if (name in ONCE_BOUND and count > 1) or name in dir(builtins)
    ]
    slicer_bodies = {
        id(part)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in SLICER_BODIES
        for part in ast.walk(node)
    }

    def reads_raw_text(name, above):
        if isinstance(above, ast.keyword):
            call, place = parent[id(above)], above.arg
            slot = 1
        elif isinstance(above, ast.Call) and name in above.args:
            call, place = above, above.args.index(name)
            slot = 0
        else:
            return False
        return isinstance(call.func, ast.Name) and RAW_TEXT_READERS.get(call.func.id, (None, None))[slot] == place

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in raw and isinstance(node.ctx, ast.Load):
            above = parent[id(node)]
            if not reads_raw_text(node, above):
                detours.append(f"line {node.lineno}: {node.id} in {ast.unparse(above)}")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in RAW_SLICERS
            and id(node) not in binds | slicer_bodies
        ):
            detours.append(f"line {node.lineno}: {ast.unparse(node)} binds no raw slice")
        elif isinstance(node, ast.Constant) and node.value in raw:
            detours.append(f"line {node.lineno}: {node.value!r} names a raw slice")
        elif isinstance(node, ast.Attribute) and (
            node.attr in raw
            or node.attr == "modules"
            or node.attr.startswith("_")
            or (isinstance(node.ctx, (ast.Store, ast.Del)) and ast.unparse(node) not in ATTRIBUTE_WRITES)
        ):
            detours.append(f"line {node.lineno}: {ast.unparse(node)}")
        elif isinstance(node, ast.Name) and node.id in DYNAMIC_BINDERS + ("delattr",):
            detours.append(f"line {node.lineno}: {node.id}")
    return detours


def helper_digests(source):
    """A digest of each raw-text helper's code in a guard's source, its
    decorators included and its docstring's text left out, so code that
    shares a line with the docstring still counts."""
    digests = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in RAW_TEXT_HELPERS:
            code = "".join("@" + ast.get_source_segment(source, decorator) + "\n" for decorator in node.decorator_list)
            code += ast.get_source_segment(source, node)
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                code = code.replace(ast.get_source_segment(source, first.value), '""', 1)
            digests[node.name] = hashlib.sha256(code.encode()).hexdigest()[:16]
    return digests


# The digest of each raw-text helper's reviewed code. A change to one of them
# must pass RawTextHelperTests, the two respacing tests and the whitespace
# test, and a review, before its digest changes here. A change to a line that
# test_digest_sees_code_but_not_docstrings edits must update that test too.
RAW_TEXT_HELPER_DIGESTS = {
    "section_source": "b1681ca548ab8ba8",
    "section": "2e67176433e730e8",
    "front_matter_block": "9fc9af41d523bc42",
    "front_matter_source": "307a158c80b21e5a",
    "bounded": "ada848b2afb55486",
    "has_number": "03321ab8a6ae591b",
    "has_ordered": "b78e727e0428668a",
    "normalized": "5e6c3c12fd8a4c92",
    "stated": "b50307b03eaafd29",
    "pinned_links": "274c1f6c00bba34a",
}


class SectionSourceTests(unittest.TestCase):
    def setUp(self):
        self.failures = []
        self.section_source = guard_function("section_source", QMD="", failures=self.failures)

    def test_a_slice_keeps_the_text_between_its_headings(self):
        """A slice keeps its edges' whitespace, and a slice with no end
        heading runs to the end of the text."""
        text = "x\n# A\nbody\n# B\ny"
        self.assertEqual(self.section_source("# A", "# B", text), "\nbody\n")
        self.assertEqual(self.section_source("# B", None, text), "\ny")
        self.assertEqual(self.failures, [])

    def test_each_failure_names_its_heading(self):
        """Each way a slice can fail, at its start or its end heading,
        empties it and records one failure that names the heading."""
        cases = (
            ("# A", "# B", "x\n# B\n", "paper section heading not unique: '# A' occurs 0 times"),
            ("# A", "# B", "# A\n# A\n# B\n", "paper section heading not unique: '# A' occurs 2 times"),
            ("# A", "# B", "# A\nbody\n", "paper section heading not unique: '# B' occurs 0 times"),
            ("# A", "# B", "# A\nx\n# B\ny\n# B\n", "paper section heading not unique: '# B' occurs 2 times"),
            ("# A", "# B", "# B\nx\n# A\n", "paper sections out of order: '# A' before '# B'"),
            ("# A", "# B", "# Ab\n# B\n", "paper section heading runs into the text after it: '# A'"),
            ("# A", "# B", "# A\nbody# B\n", "paper section text runs into the heading after it: '# B'"),
            ("# A", None, "x\n# A", "nothing follows paper section heading '# A'"),
            ("# A", "# B", "", "no text to slice for paper section '# A'"),
        )
        for start, end, text, failure in cases:
            with self.subTest(failure=failure):
                self.failures.clear()
                self.assertEqual(self.section_source(start, end, text), "")
                self.assertEqual(self.failures, [failure])

    def test_a_heading_that_bounds_two_slices_fails_once(self):
        """A repeated heading that ends one slice and starts the next
        records one failure."""
        text = "# A\nx\n# B\ny\n# B\nz\n# C\n"
        self.assertEqual(self.section_source("# A", "# B", text), "")
        self.assertEqual(self.section_source("# B", "# C", text), "")
        self.assertEqual(self.failures, ["paper section heading not unique: '# B' occurs 2 times"])


class PinnedLinksTests(unittest.TestCase):
    COMMIT = "20bfbe1abcb83b4f9f60fbe54789144321ff62b0"
    REPO_URL = "https://github.com/PolicyEngine/spm-threshold-paper"
    PINNED = f"[guide]({REPO_URL}/blob/{COMMIT}/docs/guide.md)"

    def setUp(self):
        self.pinned_links = guard_function(
            "pinned_links",
            SUPPORTING_COMMIT=self.COMMIT,
            SUPPORTING_URL_BASE=f"{self.REPO_URL}/blob/{self.COMMIT}/",
        )

    def test_every_url_naming_the_document_must_be_at_the_pinned_blob(self):
        """A second link that names the document off the pinned commit's
        blob fails in any Markdown form; links at the pinned blob and links
        to other files pass."""
        main = f"{self.REPO_URL}/blob/main/docs/guide.md"
        for extra in (
            f"[a]({main}#L1)",
            f'[a]({main} "title")',
            f"[a](<{main}>)",
            f"[a]({main}?plain=1)",
            f"\n[a]: {main}\n",
            f"<{main}>",
            f"see {main}.",
            f"[a]({self.REPO_URL}/tree/main/docs/guide.md)",
            f"[a]({self.REPO_URL}/tree/{self.COMMIT}/docs/guide.md)",
            f"[a]({self.REPO_URL}/raw/main/docs/guide.md)",
            "[a](https://raw.githubusercontent.com/PolicyEngine/spm-threshold-paper/main/docs/guide.md)",
            "[a](https://github.com/PolicyEngine/SPM-Threshold-Paper/blob/main/docs/guide.md)",
        ):
            with self.subTest(extra=extra):
                self.assertFalse(self.pinned_links("docs/guide.md", f"{self.PINNED} {extra}"))
        for extra in (
            "",
            f"[a]({self.REPO_URL}/blob/{self.COMMIT}/docs/guide.md#L1)",
            f'[a]({self.REPO_URL}/blob/{self.COMMIT}/docs/guide.md "title")',
            f"[a]({self.REPO_URL}/blob/main/docs/guide.md.bak)",
            f"[a]({self.REPO_URL}/blob/main/docs/other.md)",
            f"[a](https://github.com/PolicyEngine/SPM-Threshold-Paper/blob/{self.COMMIT}/docs/guide.md)",
        ):
            with self.subTest(extra=extra):
                self.assertTrue(self.pinned_links("docs/guide.md", f"{self.PINNED} {extra}"))

    def test_a_plain_inline_link_at_the_pinned_commit_must_exist(self):
        """Pinned links in other forms don't stand in for the plain one."""
        for text in (
            "",
            f"[guide]({self.REPO_URL}/blob/{self.COMMIT}/docs/guide.md#L1)",
            f"[guide](<{self.REPO_URL}/blob/{self.COMMIT}/docs/guide.md>)",
            f"{self.REPO_URL}/blob/{self.COMMIT}/docs/guide.md",
        ):
            with self.subTest(text=text):
                self.assertFalse(self.pinned_links("docs/guide.md", text))


# Every character that str.split(), and so normalized(), takes for
# whitespace.
WHITESPACE = tuple(character for character in map(chr, range(sys.maxunicode + 1)) if character.isspace())
# Each whitespace character other than a space, and runs of whitespace, that
# a helper could map back to one space. The whitespace test writes each one
# into the paper. The guard cuts its section slices from text it reads with
# universal newlines, so in those slices a carriage return, alone or with the
# line feed after it, reaches the ties as one line break. The abstract's
# parser reads the stored bytes and fails closed on a lone carriage return,
# U+0085, U+2028 or U+2029 anywhere in the paper, so with those spacers the
# abstract's ties fail too; the whitespace test asserts only that the listed
# ties are among the failures. The helper test runs the helpers on
# strings and sees each spacer as written.
SPACERS = tuple(character for character in WHITESPACE if character != " ") + (
    "  ",
    "   ",
    "\n ",
    "\n  ",
    "\n\t",
    " \n",
    "\t ",
    "\r\n",
    "\n\n",
)


class RawTextHelperTests(unittest.TestCase):
    def setUp(self):
        self.phrase_misses = []
        self.failures = []
        bounded = guard_function("bounded")
        self.has_number = guard_function("has_number", bounded=bounded)
        self.has_ordered = guard_function("has_ordered", bounded=bounded)
        normalized = guard_function("normalized")
        self.stated = guard_function(
            "stated", has_number=self.has_number, normalized=normalized, phrase_misses=self.phrase_misses
        )
        self.section_source = guard_function("section_source", QMD="", failures=self.failures)

    def test_helpers_keep_every_whitespace_character(self):
        """In its section of the paper, each raw literal with any one
        whitespace character other than a space, or a run of whitespace, in
        place of its spaces matches neither has_number(), has_ordered() nor
        stated(), and section_source() keeps every whitespace character. So
        on these inputs no helper the raw ties call maps whitespace back to a
        space. The whitespace test checks the whole guard at run time for
        every spacer, and the respacing tests for five spacings; a helper
        changed to map whitespace only on other inputs fails the digest
        check."""
        self.assertEqual(len(WHITESPACE), 29)
        paper = (REPO / "paper/index.qmd").read_text()
        bounds = PaperGuardTests.article_bounds(paper)
        for where, literal, _ in dict.fromkeys(RAW_LITERALS):
            start, end = bounds[where]
            section = paper[start:end]
            self.assertTrue(self.has_number(literal, text=section), literal)
            self.assertTrue(self.has_ordered([literal], text=section), literal)
            self.assertTrue(self.stated(literal, section), literal)
            for spacer in SPACERS:
                with self.subTest(literal=literal, spacer=spacer):
                    respaced = re.sub(
                        rf"(?<!\w){re.escape(literal)}(?!\w)",
                        lambda match: match.group(0).replace(" ", spacer),
                        section,
                    )
                    self.assertNotEqual(respaced, section)
                    self.assertFalse(self.has_number(literal, text=respaced))
                    self.assertFalse(self.has_ordered([literal], text=respaced))
                    self.assertFalse(self.stated(literal, respaced))
        body = "\n" + "".join(SPACERS) + "body " + "".join(WHITESPACE) + "\n"
        self.assertEqual(self.section_source("# A", "# B", f"x\n# A{body}# B\ny"), body)
        self.assertEqual(self.failures, [])


class GuardSourceTests(unittest.TestCase):
    def test_no_tie_reads_the_whole_paper(self):
        """The guard reads the paper only through slices that a heading
        bounds on each side, the abstract block, the include scan and the
        metadata-files search."""
        self.assertEqual(whole_paper_reads((REPO / "scripts/check_paper.py").read_text()), [])

    def test_source_check_sees_each_way_to_read_the_whole_paper(self):
        """Each listed form of a whole-paper read trips the source check,
        and the guard's own reads don't."""
        base = (
            'QMD = (REPO / "paper" / "index.qmd").read_text()\n'
            'QMD_RAW = (REPO / "paper" / "index.qmd").read_bytes().decode()\n'
            "def section_source(start, end=None, text=QMD): ...\n"
            "def section(start, end=None, text=QMD): ...\n"
            "def front_matter_block(key, text=QMD_RAW): ...\n"
            "def front_matter_source(key, text=QMD_RAW): ...\n"
            f"INCLUDES = [name.strip(\"\\\"'\") for name in re.findall({INCLUDE_TARGETS!r}, QMD_RAW)]\n"
            f"named = re.search({METADATA_SCAN!r}, QMD_RAW)\n"
            'ROLLING = section("# A", "# B")\n'
            'ROLLING_ACS = section("## C", None, ROLLING)\n'
            'SLICE = section_source("# A", end="# B")\n'
        )
        self.assertEqual(whole_paper_reads(base), [])
        for read in (
            'check("x", has_number("1.17", text=QMD))',
            'check("x", has_ordered(["1", "2"], text=QMD))',
            'check("x", "1.17" in QMD)',
            'check("x", stated("1.17", QMD))',
            'check("x", stated("1.17", source=QMD))',
            'check("x", set(stated_values("{} percent", QMD)) == {"1.17"})',
            "PAPER = QMD",
            'check("x", has_number("1.17", text=normalized(QMD)))',
            'check("x", "1.17" in QMD[0:])',
            'check("x", QMD.count("1.17") > 0)',
            'check("x", re.search("1.17", QMD) is not None)',
            'check("x", "1.17" in QMD.split("# A")[1])',
            'TEXT = section_source("# A")',
            'TEXT = section("# A", end=None)',
            'PAPER = (REPO / "paper" / "index.qmd").read_text()',
            'PAPER = (REPO / "paper/index.qmd").read_text()',
            'PAPER = open("paper/index.qmd").read()',
            'PAPERS = sorted(REPO.glob("paper/*.qmd"))',
            'END = None\nTEXT = section("# A", END)',
            'TEXT = section("# A", "# B" if FLAG else None)',
            'check("x", bool(re.findall(r"include|1\\.17", QMD)))',
            'check("x", has_number("1.17", text=QMD_RAW))',
            'check("x", bool(re.search(r"metadata-files?|1\\.17", QMD_RAW)))',
            'TEXT = front_matter_source("abstract", QMD)',
            'check("x", bool(re.findall(r"\\{\\{<\\s*include\\s+(.*?)\\s*>\\}\\}|1\\.17", QMD_RAW)))',
            'check("x", bool(re.search(r"\\{\\{<\\s*include\\s+(.*?)\\s*>\\}\\}", QMD_RAW)))',
            f"INCLUDES = re.findall({INCLUDE_TARGETS!r}, QMD_RAW, flags=re.S)",
            'includes = set(re.findall(r"\\{\\{<\\s*include\\s+tables/([^\\s>]+)\\s*>\\}\\}", QMD))',
        ):
            with self.subTest(read=read):
                self.assertNotEqual(whole_paper_reads(base + read + "\n"), [])


    def test_stated_ties_read_raw_slices(self):
        """Every stated() call reads a raw slice, which keeps the paper's
        line breaks, so a rewrap that splits a multi-word figure fails the
        tie as it failed #13's search of the whole paper."""
        source = (REPO / "scripts/check_paper.py").read_text()
        self.assertIn("stated(", source)
        self.assertEqual(stated_reads_off_raw_text(source), [])

    def test_raw_text_check_sees_each_way_to_hand_stated_other_text(self):
        """Each listed form trips the raw-text check, and reads of names
        bound once to a raw slice don't."""
        base = (
            'QMD = (REPO / "paper" / "index.qmd").read_text()\n'
            "def normalized(text): ...\n"
            "def section_source(start, end=None, text=QMD): ...\n"
            "def front_matter_source(key, text=QMD): ...\n"
            "def stated(literal, source, *phrases): ...\n"
            'NOWCAST_SOURCE = section_source("# A", "## B")\n'
            'NOTE_SOURCE = section_source("### C", "### D", NOWCAST_SOURCE)\n'
            'ABSTRACT_SOURCE = front_matter_source("abstract") if ABSTRACT else ""\n'
            'check("x", stated("3.2 percent", NOWCAST_SOURCE, "y"))\n'
            'check("x", stated("0.98", NOTE_SOURCE))\n'
            'check("x", stated("2.29", ABSTRACT_SOURCE))\n'
        )
        self.assertEqual(stated_reads_off_raw_text(base), [])
        for form in (
            'check("x", stated("3.2 percent", normalized(NOWCAST_SOURCE)))',
            'check("x", stated("3.2 percent", QMD))',
            'check("x", stated("3.2 percent", source=NOWCAST_SOURCE))',
            'NOWCAST_TEXT = section("# A", "## B")\ncheck("x", stated("3.2 percent", NOWCAST_TEXT))',
            'FLAT_SOURCE = normalized(section_source("# A", "## B"))\ncheck("x", stated("3.2", FLAT_SOURCE))',
            'WIDE_SOURCE = section_source("# A", "## B") if X else QMD\ncheck("x", stated("3.2", WIDE_SOURCE))',
            "NOWCAST_SOURCE = normalized(NOWCAST_SOURCE)",
            "for NOWCAST_SOURCE in (QMD,):\n    pass",
            'WIDE_SOURCE = section("# A", "## B") if X else ""\ncheck("x", stated("3.2", WIDE_SOURCE))',
            'WIDE_TEXT = section("# A", "## C")\nNESTED_SOURCE = section_source("# A", "## B", WIDE_TEXT)\n'
            'check("x", stated("3.2", NESTED_SOURCE))',
            'NESTED_SOURCE = section_source("# A", "## B", text=normalized(QMD))\ncheck("x", stated("3.2", NESTED_SOURCE))',
            "def stated_in(literal, NOWCAST_SOURCE):\n    return stated(literal, NOWCAST_SOURCE)",
            'say = stated\ncheck("x", say("3.2", normalized(NOWCAST_SOURCE)))',
            "import NOWCAST_SOURCE",
            'HEADS = ("# A", "## B", normalized(NOWCAST_SOURCE))\nSTAR_SOURCE = section_source(*HEADS)\n'
            'check("x", stated("3.2", STAR_SOURCE))',
            'KW_SOURCE = section_source("# A", "## B", **{"text": normalized(NOWCAST_SOURCE)})\n'
            'check("x", stated("3.2", KW_SOURCE))',
            "match normalized(NOWCAST_SOURCE):\n    case NOWCAST_SOURCE:\n        pass",
            "def NOWCAST_SOURCE():\n    pass",
            "class NOWCAST_SOURCE:\n    pass",
            "try:\n    pass\nexcept ValueError as NOWCAST_SOURCE:\n    pass",
            "match {}:\n    case {**NOWCAST_SOURCE}:\n        pass",
            'globals()["NOWCAST_SOURCE"] = normalized(NOWCAST_SOURCE)',
            "vars().update(NOWCAST_SOURCE=normalized(NOWCAST_SOURCE))",
            'setattr(sys.modules[__name__], "NOWCAST_SOURCE", normalized(NOWCAST_SOURCE))',
            'exec("NOWCAST_SOURCE = normalized(NOWCAST_SOURCE)")',
            'sys.modules[__name__].__dict__["NOWCAST_SOURCE"] = ""',
            "def section_source(start, end=None, text=QMD):\n    return normalized(text)",
            "def stated(literal, source, *phrases):\n    return True",
            "def normalized(text):\n    return text",
            "def front_matter_source(key, text=QMD):\n    return normalized(text)",
            "def f():\n    global NOWCAST_SOURCE",
            "match []:\n    case [*NOWCAST_SOURCE]:\n        pass",
            "async def NOWCAST_SOURCE():\n    pass",
            'locals()["NOWCAST_SOURCE"] = ""',
            'eval("NOWCAST_SOURCE")',
            '__import__("sys").modules[__name__].NOWCAST_SOURCE = ""',
        ):
            with self.subTest(form=form):
                self.assertNotEqual(stated_reads_off_raw_text(base + form + "\n"), [])

    def test_raw_slices_reach_their_ties_unchanged(self):
        """The guard reads the paper as PAPER_READS gives, binds every raw
        slicer call outside the slicers to a raw slice, and hands each raw
        slice only to the readers RAW_TEXT_READERS lists, so none of the
        routes this check names can change a raw slice between the file and a
        tie's helper. The whitespace test catches other routes when their
        mapping lets a tie pass a paper that test builds."""
        source = (REPO / "scripts/check_paper.py").read_text()
        self.assertEqual(len(raw_slices(ast.parse(source))[0]), 7)
        self.assertEqual(raw_text_detours(source), [])

    def test_detour_check_sees_each_way_to_change_raw_text(self):
        """Each listed form trips the detour check, and the reads of raw
        slices that RAW_TEXT_READERS lists don't."""
        base = (
            "import re\n"
            "import sys\n"
            "from pathlib import Path\n"
            "REPO = Path(__file__).resolve().parent.parent\n"
            "sys.dont_write_bytecode = True\n"
            f"QMD = {PAPER_READS['QMD']}\n"
            f"QMD_RAW = {PAPER_READS['QMD_RAW']}\n"
            "failures = []\n"
            "phrase_misses = []\n"
            "def bounded(literal): ...\n"
            "def has_number(literal, *, text, min_count=1): ...\n"
            "def has_ordered(literals, window=400, *, text): ...\n"
            "def pinned_links(path, text): ...\n"
            "def front_matter_block(key, text=QMD_RAW): ...\n"
            "def normalized(text): ...\n"
            "def section_source(start, end=None, text=QMD): ...\n"
            "def section(start, end=None, text=QMD):\n"
            "    return normalized(section_source(start, end, text))\n"
            "def front_matter_source(key, text=QMD_RAW): ...\n"
            "def stated(literal, source, *phrases): ...\n"
            'NOWCAST_SOURCE = section_source("# A", "## B")\n'
            'NOTE_SOURCE = section_source("### C", "### D", NOWCAST_SOURCE)\n'
            'TAIL_SOURCE = section_source("### E", text=NOTE_SOURCE)\n'
            'ABSTRACT_SOURCE = front_matter_source("abstract") if ABSTRACT else ""\n'
            'NOWCAST_TEXT = section("# A", "## B")\n'
            'check("x", stated("3.2 percent", NOWCAST_SOURCE, "y"))\n'
            'check("x", has_number("0.98", text=TAIL_SOURCE))\n'
            'check("x", has_ordered(["owners with", "renters"], 120, text=NOWCAST_SOURCE))\n'
            'check("x", has_number("2.29", text=ABSTRACT_SOURCE))\n'
            'check("x", pinned_links("p.md", NOWCAST_SOURCE))\n'
            'check("x", pinned_links("p.md", text=NOTE_SOURCE))\n'
            'check("x", has_number("y z", text=normalized(NOWCAST_SOURCE)))\n'
        )
        self.assertEqual(raw_text_detours(base), [])
        for form in (
            'check("x", has_number("3.2 percent", text=NOWCAST_SOURCE.replace("\\u202f", " ")))',
            'check("x", has_number("3.2 percent", text=re.sub(r"\\n {2,}", " ", NOWCAST_SOURCE)))',
            'check("x", has_number("3.2 percent", text=re.sub(r" {3,}", " ", NOWCAST_SOURCE)))',
            'check("x", has_ordered(["owners with"], text=NOWCAST_SOURCE.expandtabs(1)))',
            'check("x", stated("3.2 percent", NOWCAST_SOURCE.replace("\\t", " ")))',
            'check("x", pinned_links("p.md", NOWCAST_SOURCE.lower()))',
            'check("x", has_number("3.2 percent", text=NOWCAST_SOURCE[1:]))',
            'check("x", has_number("3.2 percent", text=f"{NOWCAST_SOURCE}"))',
            'check("x", has_number("3.2 percent", text=" ".join([NOWCAST_SOURCE])))',
            'check("x", has_number("3.2 percent", NOWCAST_SOURCE))',
            'TEXT = NOWCAST_SOURCE\ncheck("x", has_number("3.2 percent", text=TEXT))',
            "def fix(text):\n    return text\ncheck(\"x\", has_number(\"3.2 percent\", text=fix(NOWCAST_SOURCE)))",
            'check("x", has_number("3.2 percent", text=section_source("# A", "## B").replace("\\t", " ")))',
            'WIDE_SOURCE = section_source("# A", "## B").replace("\\t", " ")\n'
            'check("x", has_number("3.2 percent", text=WIDE_SOURCE))',
            'sys.modules[__name__].NOWCAST_SOURCE = NOWCAST_SOURCE.replace("\\t", " ")',
            "sys.modules[__name__].NOWCAST_SOURCE = normalized(NOWCAST_SOURCE)",
            'sys.modules[__name__].__setattr__("NOWCAST_SOURCE", normalized(NOWCAST_SOURCE))',
            "MODULE = sys.modules[__name__]",
            'check("x", has_number("3.2 percent", text=getattr(MODULE, "NOWCAST_SOURCE")))',
            'QMD = (REPO / "paper" / "index.qmd").read_text().replace("\\u202f", " ")',
            'QMD_RAW = (REPO / "paper" / "index.qmd").read_bytes().decode("utf-8-sig").expandtabs()',
            'if True:\n    QMD = (REPO / "paper" / "index.qmd").read_text().replace("\\u202f", " ")',
            'Path.read_text = lambda self, *args: ""',
            're.escape = lambda pattern: pattern',
            "del re.escape",
            'delattr(re, "escape")',
            "has_number = lambda literal, *, text, min_count=1: True",
            "def has_ordered(literals, window=400, *, text):\n    return True",
            "def f():\n    global bounded\n    bounded = re.escape",
            "import regex as re",
            "Path = str",
            "REPO = Path(\".\")",
            'check.__globals__["NOWCAST" + "_SOURCE"] = ""',
            "len = lambda items: 1",
        ):
            with self.subTest(form=form):
                self.assertNotEqual(raw_text_detours(base + form + "\n"), [])

    def test_raw_text_helpers_keep_their_reviewed_code(self):
        """Each raw-text helper's code matches the code we reviewed, so a
        change that maps whitespace only on inputs no test builds, such as
        another paper or a run of whitespace the whitespace test doesn't
        try, fails here until someone reviews it and records the new
        digest."""
        digests = helper_digests((REPO / "scripts/check_paper.py").read_text())
        self.assertEqual(sorted(digests), sorted(RAW_TEXT_HELPERS))
        self.assertEqual(digests, RAW_TEXT_HELPER_DIGESTS)

    def test_digest_sees_code_but_not_docstrings(self):
        """A change to a helper's code or decorators changes its digest,
        even on the docstring's closing line, and a change to its docstring
        doesn't."""
        source = (REPO / "scripts/check_paper.py").read_text()
        digests = helper_digests(source)
        code = '    return "" if problems else text[first:last]\n'
        docstring = '    """The paper\'s text between two heading strings, as written.\n'
        decorator = "def has_number(literal: str, *, text: str, min_count: int = 1) -> bool:\n"
        closing = '    so no tie can fall back to searching the whole paper."""\n'
        for name, old, new in (
            ("section_source", code, code.replace("text[first:last]", "text[first:last] if len(text) < 999 else text")),
            ("has_number", decorator, "@staticmethod\n" + decorator),
            ("has_number", closing, closing.replace('"""\n', '"""; text = text.strip()\n')),
        ):
            with self.subTest(name=name):
                self.assertEqual(source.count(old), 1)
                changed = helper_digests(source.replace(old, new))
                self.assertNotEqual(changed[name], digests[name])
                self.assertEqual({k: v for k, v in changed.items() if k != name}, {k: v for k, v in digests.items() if k != name})
        self.assertEqual(source.count(docstring), 1)
        self.assertEqual(helper_digests(source.replace(docstring, docstring.replace("as written", "as stored"))), digests)

if __name__ == "__main__":
    unittest.main()
