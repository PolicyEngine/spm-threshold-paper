"""Mutation tests run the real guard in independent temporary Git clones."""

import ast
import hashlib
import importlib.util
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


INKIND_HEADING = "# Imputing in-kind benefits {#sec-inkind}\n"
PROJECTION_HEADING = "# Projecting thresholds {#sec-projection}\n"
INKIND_NAMES = (
    "ce_inkind_bls_components_2019_2025.json",
    "ce_inkind_replication_2019_2025.json",
    "ce_replicate_uncertainty_2019_2025.json",
    "provenance.json",
)
REPLICATION_HEADING = "# Replication from public consumption data {#sec-replication}\n"

# Each case drifts one in-kind figure where the paper states it. The lift
# range also appears in the abstract and the discussion, so the first case
# fails only because the pin reads the in-kind section itself.
INKIND_PROSE_MUTATIONS = (
    ("lift range", "section", r"1\.1(\s+)to(\s+)3\.8", r"1.2\1to\g<2>3.8", "in-kind lift range"),
    ("abstract lift range", "abstract", r"1\.1(\s+)to(\s+)3\.8", r"1.1\1to\g<2>3.9", "abstract in-kind lift range"),
    (
        "swapped stage changes",
        "section",
        r"\+0\.06(.*?)\+0\.91",
        r"+0.91\1+0.06",
        "stage changes in tenure order",
    ),
    (
        "rental assistance share of the difference",
        "section",
        r"\\\$169",
        r"\\$196",
        "difference in rises by benefit",
    ),
    (
        "BLS imputed renter points",
        "section",
        r"5\.71(\s+)percent,(\s+)0\.62",
        r"5.71\1percent,\g<2>0.66",
        "BLS 2024-2025 renter growth without its imputed terms",
    ),
    (
        "written-definition lower bound",
        "section",
        r"1\.71(\s+)percent(\s+)below",
        r"1.72\1percent\2below",
        "written-definition range with benefits",
    ),
    (
        "vacation-home utilities",
        "section",
        r"and(\s+)utilities(\s+)for(\s+)vacation(\s+)homes",
        r"and\1fuels\2for\3vacation\4homes",
        "written-definition runs drop vacation-home utilities",
    ),
    (
        "kept vacation-home fuel codes",
        "section",
        r"under(\s+)two(\s+)codes",
        r"under\1three\2codes",
        "written-definition runs keep the vacation-home fuel codes",
    ),
    ("implicate count", "section", r"We draw five implicates", "We draw four implicates", "implicate, matching-neighbor"),
    (
        "abstract stage changes",
        "abstract",
        r"less(\s+)than(\s+)one(\s+)point",
        r"less\1than\2half\3a point",
        "abstract stage changes under one point per tenure",
    ),
    (
        "abstract accounting share",
        "abstract",
        r"supply(\s+)5(\s+)to(\s+)13(\s+)percent",
        r"supply\g<1>5\2to\g<3>12\4percent",
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
        r"`53cb0fa08a0ca2fe1ea4b15a32ec77090ca8b91c`",
        "`4778dfab2d109515b6a14e63da63011dd7feb884`",
        "appendix names the recorded calculator commits",
    ),
    (
        "appendix standard-error commit",
        "appendix",
        r"`53cb0fa08a0ca2fe1ea4b15a32ec77090ca8b91c`",
        "`53cb0fa08a0ca2fe1ea4b15a32ec77090ca8b910`",
        "appendix names the recorded calculator commits",
    ),
    (
        "replication standard-error ratios",
        "replication",
        r"0\.66(\s+)to(\s+)1\.02",
        r"0.67\1to\g<2>1.02",
        "replication standard errors relative to BLS's",
    ),
    (
        "swapped replication standard-error ratios",
        "replication",
        r"0\.85(\s+)to(\s+)1\.35(.*?)1\.01(\s+)to(\s+)1\.95",
        r"1.01\1to\g<2>1.95\g<3>0.85\g<4>to\g<5>1.35",
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
        "stage-change standard error",
        "section",
        r"2\.54(\s+)for",
        r"2.45\1for",
        "standard errors of the stage change",
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
        "implicate variance share",
        "section",
        r"17(\s+)to(\s+)46(\s+)percent",
        r"17\1to\g<2>45\3percent",
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
        r"(We estimate that the imputed benefits\s+change the replication's growth by .*?"
        r"each within one standard error of zero) \(@sec-inkind-uncertainty\)\."
        r"(.*?## Uncertainty and limitations \{#sec-inkind-uncertainty\}\n\n)",
        r"\2\1. ",
        "stage changes in tenure order, each within one standard error",
    ),
    (
        "benefits' share with the index's lead on their terms",
        "section",
        r"benefits(\s+)supply(\s+)4\.3,(\s+)6\.8,",
        r"benefits\1supply\g<2>6.8,\g<3>4.3,",
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
        "swapped stage-change tenure labels",
        "section",
        r"\+0\.06(\s+)points(\s+)for(\s+)owners(\s+)with(\s+)mortgages,(\s+)\+0\.91(\s+)for(\s+)owners(\s+)without",
        r"+0.06\1points\2for\3owners\4without\5mortgages,\6+0.91\7for\8owners\9with",
        "stage changes in tenure order",
    ),
    (
        "level comparison direction",
        "section",
        r"thresholds(\s+)that(\s+)exceed",
        r"thresholds\1that\2fall below",
        "replication with benefits exceeds BLS in every cell",
    ),
    (
        "rental assistance level gap direction",
        "section",
        r"71(\s+)to(\s+)80(\s+)percent(\s+)above",
        r"71\1to\g<2>80\3percent\4below",
        "rental assistance per renter: level gap before 2024",
    ),
    (
        "mean absolute deviation direction",
        "section",
        r"deviation(\s+)falls(\s+)from",
        r"deviation\1rises\2from",
        "written-definition mean absolute deviation",
    ),
    (
        "deflator direction",
        "section",
        r"growth(\s+)rises(\s+)by(\s+)0\.9",
        r"growth\1falls\2by\g<3>0.9",
        "deflator effect exceeds the stage in every tenure",
    ),
    (
        "renter shortfall direction",
        "section",
        r"shortfall(\s+)narrows",
        r"shortfall\1widens",
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
        r"FCSUti(\s+)index(\s+)supplies(\s+)33(\s+)to(\s+)39(\s+)percent(.*?)benefits(\s+)5(\s+)to(\s+)13",
        r"FCSUti\1index\2supplies\g<3>5\4to\g<5>13\6percent\7benefits\g<8>33\9to\g<10>39",
        "abstract and discussion: the accounting's shares",
    ),
    # Round 2: the verb or label beside each figure, and the method facts
    # the section quotes, each changed while every figure stays put.
    (
        "lift direction",
        "section",
        r"imputed(\s+)benefits(\s+)raise(\s+)the(\s+)replicated",
        r"imputed\1benefits\2lower\3the\4replicated",
        "in-kind lift range",
    ),
    (
        "abstract lift direction",
        "abstract",
        r"they(\s+)raise(\s+)replicated",
        r"they\1lower\2replicated",
        "abstract in-kind lift range",
    ),
    (
        "discussion lift direction",
        "discussion",
        r"benefits(\s+)raises(\s+)our(\s+)levels",
        r"benefits\1lowers\2our\3levels",
        "discussion in-kind lift range",
    ),
    (
        "swapped stages in the 2024-2025 renter growth",
        "section",
        r"With(\s+)our(\s+)imputed(\s+)benefits,(\s+)we(\s+)estimate(\s+)the(\s+)retrospective(.*?)without(\s+)them",
        r"Without\1our\2imputed\3benefits,\4we\5estimate\6the\7retrospective\8with\9them",
        "replication 2024-2025 renter growth with and without benefits",
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
        "standard error of our rise",
        "section",
        r"standard(\s+)error(\s+)of(\s+)\\\$191",
        r"standard\1error\2of\3\\$119",
        "BLS and replication imputed totals",
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
        "written-definition stage without benefits",
        "section",
        r"the(\s+)out-of-pocket(\s+)replication(\s+)trails",
        r"the\1replication\2with benefits\3trails",
        "written-definition out-of-pocket range",
    ),
    (
        "written-definition stage with benefits",
        "section",
        r"When(\s+)we(\s+)also(\s+)add(\s+)the(\s+)imputed(\s+)benefits",
        r"When\1we\2also\3remove\4the\5imputed\6benefits",
        "written-definition range with benefits",
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
        "written definitions read from fingerprinted calculator code",
    ),
    (
        "kept fuel codes' reason",
        "section",
        r"vacation-home(\s+)utilities(\s+)leave(\s+)out",
        r"vacation-home\1utilities\2include",
        "written-definition runs keep the vacation-home fuel codes",
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
        "percentile band read from fingerprinted calculator code",
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
        "benefit count",
        "section",
        r"with(\s+)the(\s+)five(\s+)benefits",
        r"with\1the\2four\3benefits",
        "programs the participation models cover",
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
        "written definitions read from fingerprinted calculator code",
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
        "written-definition stage change",
        "section",
        r"by(\s+)\+0\.09,(\s+)−1\.51,",
        r"by\1+0.09,\2−1.15,",
        "written definitions with the composite CPI",
    ),
    (
        "abstract names the CE summaries",
        "abstract",
        r"with(\s+)the(\s+)CE's(\s+)spending(\s+)summaries",
        r"with\1the\2written\3shelter\4definitions",
        "written definitions with the composite CPI",
    ),
    (
        'internet share of thresholds',
        'section',
        '1\\.85(\\s+)to(\\s+)2\\.55',
        '1.85\\1to\\g<2>2.65',
        "home internet's share of BLS's thresholds",
    ),
    (
        'common-component gap',
        'section',
        '0\\.83(\\s+)to(\\s+)3\\.80',
        '0.83\\1to\\g<2>3.90',
        'thresholds on the components both series hold',
    ),
    (
        'common-component definitions swapped',
        'section',
        'under(\\s+)the(\\s+)written(\\s+)definitions(\\s+)and(\\s+)by(.*?)with(\\s+)the(\\s+)CE(\\s+)summaries',
        'with\\1the\\2CE\\3summaries\\4and\\5by\\6under\\7the\\8written\\9definitions',
        'thresholds on the components both series hold',
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
        'with(\\s+)a(\\s+)standard(\\s+)error(\\s+)of(\\s+)\\\\\\$444',
        'with\\1a\\2standard\\3error\\4of\\5\\\\$404',
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
        '−0\\.01,(\\s+)\\+0\\.82,',
        '−0.01,\\1−0.82,',
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
        '\\\\\\$50(\\s+)for(\\s+)school(\\s+)lunch',
        '\\\\$55\\1for\\2school\\3lunch',
        'standard errors of the rises in band amounts',
    ),
    (
        'lift standard errors',
        'section',
        '0\\.31(\\s+)to(\\s+)0\\.61',
        '0.31\\1to\\g<2>0.71',
        "standard errors of the benefits' lifts",
    ),
    (
        'lift years within 1.5 standard errors',
        'section',
        'the(\\s+)2021–2025(\\s+)lifts',
        'the\\g<1>2020–2025\\2lifts',
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
        '\\\\\\$64(\\s+)to(\\s+)\\\\\\$683',
        '\\\\$64\\1to\\2\\\\$638',
        "written definitions keep owners' rented-dwelling spending",
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
        'points,(\\s+)each(\\s+)within(\\s+)one',
        'points,\\1each\\2within\\3half a',
        'abstract and discussion: each change within one standard error',
    ),
    (
        'discussion growth claim without its CE-summaries scope',
        'discussion',
        "With(\\s+)the(\\s+)CE's(\\s+)spending(\\s+)summaries,(\\s+)we(\\s+)estimate",
        'We\\6estimate',
        'abstract and discussion: each change within one standard error',
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
        'ours(\\s+)rose(\\s+)from(\\s+)\\\\\\$1,258',
        'ours\\1rose\\2from\\3\\\\$1,285',
        'BLS 2024-2025 renter growth without its imputed terms',
    ),
    (
        'BLS renter growth without imputed terms',
        'section',
        'grows(\\s+)5\\.71',
        'grows\\g<1>5.17',
        'BLS 2024-2025 renter growth without its imputed terms',
    ),
)

# Each case drifts figures in the abstract alone: (name, pattern, replacement,
# failing ties, decoy). The body or a generated table states every one of these
# figures too. The decoy restates the original wording, and the tests place it
# at each of ABSTRACT_DECOY_HOSTS, so a tie that read more than the abstract
# block, or that settled for one correct copy, would still pass.
ABSTRACT_PROSE_MUTATIONS = (
    (
        "2020-2025 CPI-U error",
        r"2\.29(\s+)percent",
        r"2.30\1percent",
        ("abstract current projection cpi_u 2.29", "current projection prose cpi_u"),
        "We obtain 2.29 percent with the Consumer Price Index.",
    ),
    (
        "2020-2025 CPI-U sign",
        r"2\.29(\s+)percent",
        "−2.29\\1percent",
        ("abstract current projection cpi_u 2.29",),
        "We obtain 2.29 percent with the Consumer Price Index.",
    ),
    (
        "2020-2025 composite error",
        r"1\.65(\s+)percent",
        r"1.66\1percent",
        (
            "abstract current projection fcsuti_cpi 1.65",
            "current projection prose fcsuti_cpi",
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
        ),
        "We obtain 0.51 percent with replicated consumption growth.",
    ),
    (
        "2020-2025 blend error",
        r"0\.90(\s+)percent",
        r"0.91\1percent",
        ("abstract current projection blend 0.90", "current projection prose blend"),
        "We obtain 0.90 percent with an equal blend.",
    ),
    (
        "2025 blend error",
        r"1\.17(\s+)percent",
        r"1.18\1percent",
        ("abstract evaluation amended MAE 1.17",),
        "The blend yields a mean absolute error of 1.17 percent.",
    ),
    (
        "2025 CPI-U error",
        r"2\.58(\s+)percent",
        r"2.59\1percent",
        ("abstract evaluation CPI-U MAE 2.58",),
        "We obtain 2.58 percent for CPI-U adjustment.",
    ),
    (
        "2025 replication error",
        r"0\.75(\s+)percent",
        r"0.74\1percent",
        ("abstract evaluation replication MAE 0.75",),
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
        "We obtain 2.29 percent with the Consumer Price Index and 1.65 percent "
        "with a composite price index.",
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
# in body text before the introduction, and inside the abstract block itself.
ABSTRACT_DECOY_HOSTS = ("discussion", "metadata", "preamble", "abstract")

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
    "compared with 2.63 percent implied by the eleven-month annual average in "
    "the pinned CPI observations."
)
APPENDIX_A_RANGES = (
    "The replication used for the 2025 nowcast has mean absolute deviations "
    "across tenures of 1.5 to 2.1 percent per year against revised 2019–2024 "
    "thresholds, and 1.0 to 1.6 percent against the preceding published series "
    "with its corresponding anchor share. Published BLS sampling standard errors "
    "span 0.7 to 2.1 percent of the revised threshold levels in those years."
)
APPENDIX_B_LINKS = (
    f"The [data provenance]({PINNED_BLOB}data/PROVENANCE.md) and [forecast "
    f"record]({PINNED_BLOB}docs/forecast-record.md) identify each experiment’s "
    "inputs and evidence. The [experiment replay "
    f"guide]({PINNED_BLOB}docs/reproducing-experiments.md) provides commands "
    "and source-file requirements for raw-data replication."
)
BLS_GROWTH_TIE = "BLS-stated 2025 growth 4.40-6.33 and per-tenure 5.33/4.40/6.33"
INKIND_BLS_GROWTH_TIE = "in-kind prose: evaluation section's BLS growth rates for 2024-2025"
GAP_TIE = "composite within 0.7pp of BLS FCSUti, mean gap 0.4"

# Each case drifts figures in the one body section that states them: (name,
# section, pattern, replacement, failing ties, decoy). The section names a
# mutate_article slice, and the pattern edits its first match there. With the
# decoy restated under the discussion heading, the failing ties are the only
# lines the guard reports.
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
        "appendix",
        r"blob/20bfbe1abcb83b4f9f60fbe54789144321ff62b0(/docs/forecast-record\.md)",
        r"blob/main\1",
        ("manuscript links fixed supporting document: docs/forecast-record.md",),
        APPENDIX_B_LINKS,
    ),
    (
        "appendix data provenance links",
        "appendix",
        r"blob/20bfbe1abcb83b4f9f60fbe54789144321ff62b0(/data/PROVENANCE\.md)(.*?)"
        r"blob/20bfbe1abcb83b4f9f60fbe54789144321ff62b0(/data/PROVENANCE\.md)",
        r"blob/main\1\2blob/main\3",
        ("manuscript links fixed supporting document: data/PROVENANCE.md",),
        APPENDIX_B_LINKS,
    ),
    (
        "appendix replay guide link",
        "appendix",
        r"blob/20bfbe1abcb83b4f9f60fbe54789144321ff62b0(/docs/reproducing-experiments\.md)",
        r"blob/main\1",
        ("manuscript links fixed supporting document: docs/reproducing-experiments.md",),
        APPENDIX_B_LINKS,
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
# (name, edits, ties that must fail). The slice comes back empty, so the
# guard reports the heading and fails the section's ties instead of
# searching anywhere else.
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
            "paper section heading not unique: '## Replicated levels and sample sensitivities'",
            "current tenure-sensitivity prose",
        ),
    ),
    (
        "renamed benchmark heading",
        (("## Five-year benchmark for the 2025 nowcast\n", "## Five-year benchmark\n"),),
        (
            "paper section heading not unique: '## Five-year benchmark for the 2025 nowcast'",
            "backtest prose literal 2.23",
            "signed CPI-U bias -1.9",
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
            "paper section heading not unique: '# Pre-committed 2025 validation'",
            "paper section heading not unique: '## Five-year benchmark for the 2025 nowcast'",
            "nowcast section links to the fixed forecast registration record",
            "nowcast literal 41,036.34",
            "price growth 3.2",
            "backtest prose literal 2.23",
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
            "'## Evaluation against published thresholds {#sec-evaluation}'",
            "paper section heading not unique: '# Pre-committed 2025 validation'",
            "evaluation amended MAE 1.17",
            "2025 SE triple in tenure order",
            "nowcast literal 41,036.34",
        ),
    ),
    (
        "repeated comparator heading",
        ((DISCUSSION_HEADING, "## Validation of the price comparator\n\n" + DISCUSSION_HEADING),),
        (
            "paper section heading not unique: '## Validation of the price comparator'",
            "paper section heading not unique: "
            "'## Evaluation against published thresholds {#sec-evaluation}'",
            GAP_TIE,
            "BLS page 2025 CPI-U growth 2.70 quoted",
            "evaluation amended MAE 1.17",
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
            "paper section heading not unique: '# Appendix A: replication benchmark {.unnumbered}'",
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
            "paper section heading not unique: '# Appendix A: replication benchmark {.unnumbered}'",
            "paper section heading not unique: '# Appendix B: reproducibility'",
            "manuscript links fixed supporting document: docs/forecast-record.md",
            "SE range 0.7 to 2.1 percent",
        ),
    ),
)

# The in-kind ties that read the abstract, labeled as the guard reports them.
INKIND_ABSTRACT_TIE_LABELS = (
    "in-kind prose: abstract in-kind lift range",
    "in-kind prose: abstract and discussion: each change within one standard error",
    "in-kind prose: abstract and discussion: the accounting's shares",
    "in-kind prose: written definitions with the composite CPI: the benefits' change to growth",
    "in-kind prose: abstract stage changes under one point per tenure",
)


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
        self.assertIn("in-kind prose: written-definition runs drop vacation-home utilities", result.stdout)
        self.assertNotIn("generators were not run", result.stdout)

    def test_definition_runs_must_drop_the_vacation_home_principal(self):
        def keep_2022_vacation_home_principal(components):
            components["definition_check"]["2022"]["units_with_amount_removed"]["vacation_home_principal"] = 0

        self.reseal_and_repin_components(keep_2022_vacation_home_principal)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "in-kind prose: written-definition runs drop vacation-home utilities and principal", result.stdout
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
        self.assertIn("in-kind prose: written-definition runs drop vacation-home utilities", result.stdout)
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
        self.assertIn("in-kind prose: written-definition runs keep the vacation-home fuel codes", result.stdout)
        self.assertNotIn("generators were not run", result.stdout)

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
        cases = (
            ("receipt count", "uses three receipts", "uses two receipts"),
            ("commit", "`53cb0fa08a0ca2fe1ea4b15a32ec77090ca8b91c`", "`53cb0fa`"),
            ("tag", "`paper-inkind-se-53cb0fa`", "`paper-inkind-se-a581c11`"),
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
        components = uncertainty = replication = "53cb0fa08a0ca2fe1ea4b15a32ec77090ca8b91c"
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
        replication["results"]["2025"]["without_in_kind"]["renter"] += 1
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
        """Shift one threshold with its implicates and lift, so the replication
        receipt agrees with itself; the component receipt still disagrees."""
        replication = self.inkind_replication()
        record = replication["results"]["2025"]
        for draw in record["with_in_kind_by_implicate"]:
            draw["renter"] += 5
        record["with_in_kind"]["renter"] += 5
        record["in_kind_lift_percent"]["renter"] = 100 * (
            record["with_in_kind"]["renter"] / record["without_in_kind"]["renter"] - 1
        )
        self.reseal_inkind_replication(replication)
        result = self.run_guard()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("package run with 2025 renter", result.stdout)
        self.assertNotIn("implicate mean", result.stdout)
        self.assertNotIn("in-kind lift 2025", result.stdout)
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

    def mutate_article(self, where, pattern, replacement):
        article = self.repo / "paper/index.qmd"
        text = article.read_text()
        bounds = {
            "section": (text.index(INKIND_HEADING), text.index(PROJECTION_HEADING)),
            "replication": (text.index(REPLICATION_HEADING), text.index(INKIND_HEADING)),
            "abstract": PAPER_TEXT.block_scalar_span(text, "abstract") or (0, 0),
            "evaluation": (
                text.index("## Evaluation against published thresholds"),
                text.index("## Validation of the price comparator"),
            ),
            "discussion": (text.index(DISCUSSION_HEADING), text.index("# Appendix A: replication benchmark")),
            "appendix": (text.index("# Appendix B: reproducibility"), len(text)),
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
        start, end = bounds[where]
        body, count = re.subn(pattern, replacement, text[start:end], count=1, flags=re.S)
        self.assertEqual(count, 1, f"fixture pattern missing: {pattern}")
        article.write_text(text[:start] + body + text[end:])

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
            ("rental assistance share", (("supplies \\$169 and school", "supplies \\$196 and school"),),
             "difference in rises by benefit",
             "Of the \\$256 difference between the two rises, rental assistance supplies \\$169 and school "
             "lunch \\$94, and the other three benefits narrow it by \\$7."),
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
        original figure under another heading."""
        path = self.repo / "paper/index.qmd"
        prose = path.read_text()
        for old, new in edits:
            self.assertEqual(prose.count(old), 1, f"ambiguous fixture edit: {old!r}")
            prose = prose.replace(old, new)
        if host is not None:
            self.assertEqual(prose.count(host), 1, f"ambiguous fixture host: {host!r}")
            prose = prose.replace(host, f"{host}\n{decoy}\n")
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
        if host == "abstract":
            indent = re.match(r"[ \t]*", prose[span[0] :]).group()
            at, insert = span[1], f"{indent}{decoy}\n"
        elif host == "metadata":
            at, insert = span[1], f'note: "{decoy}"\n'
        elif host == "preamble":
            at, insert = prose.index("\n# Introduction\n") + 1, f"{decoy}\n\n"
        else:
            self.fail(f"unknown decoy host: {host}")
        path.write_text(prose[:at] + insert + prose[at:])

    def run_section_mutation(self, where, pattern, replacement, decoy=None):
        """Drift a figure in one section, optionally restate the original
        wording under the discussion heading, and run the guard."""
        self.install_article()
        self.mutate_article(where, pattern, replacement)
        if decoy is not None:
            self.edit_article((), DISCUSSION_HEADING, decoy)
        return self.run_guard()

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
        abstract itself, only the abstract's own ties fail."""
        for host in ABSTRACT_DECOY_HOSTS:
            for name, pattern, replacement, labels, decoy in ABSTRACT_PROSE_MUTATIONS:
                with self.subTest(host=host, name=name):
                    result = self.run_abstract_mutation(pattern, replacement, decoy, host)
                    self.assertNotEqual(result.returncode, 0)
                    expected = labels
                    if host == "abstract":
                        # A copy inside the abstract keeps the original figure
                        # there, so the ties that only look for it pass, and
                        # the ties that require every stated rate to match fail.
                        expected = tuple(
                            label
                            for label in labels
                            if not label.startswith("current projection prose")
                        )
                    self.assertEqual(sorted(failure_lines(result.stdout)), sorted(expected))
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
                    failure_lines(drifted.stdout), ["abstract evaluation amended MAE 1.17"]
                )
        self.install_article()

    def test_abstract_ties_skip_a_comment_after_the_block(self):
        """YAML ends the abstract's block at a line indented less than the
        block, a comment included, so a comment that keeps wording the
        abstract dropped cannot satisfy the ties that read that wording."""
        cases = (
            (
                "CPI-U rule renamed",
                r"with(\s+)the(\s+)Consumer(\s+)Price(\s+)Index",
                r"with\1the\2CPI-U\3price\4index",
                "2.29 percent with the Consumer Price Index",
                ["abstract current projection cpi_u 2.29"],
            ),
            (
                "stage-change bound changed",
                r"less(\s+)than(\s+)one(\s+)point",
                r"less\1than\2half\3a point",
                "change 2022–2025 growth by less than one point per tenure with the CE's spending summaries",
                [
                    "in-kind prose: abstract stage changes under one point per tenure",
                    "in-kind prose: written definitions with the composite CPI: the benefits' change to growth",
                ],
            ),
        )
        for name, pattern, replacement, comment, labels in cases:
            with self.subTest(case=name):
                self.install_article()
                self.mutate_article("abstract", pattern, replacement)
                path = self.repo / "paper/index.qmd"
                prose = path.read_text()
                span = PAPER_TEXT.block_scalar_span(prose, "abstract")
                self.assertIsNotNone(span, "fixture has no abstract block")
                path.write_text(f"{prose[: span[1]]} # {comment}\n{prose[span[1] :]}")
                result = self.run_guard()
                self.assertEqual(sorted(failure_lines(result.stdout)), sorted(labels))
        self.install_article()

    def test_abstract_block_fails_closed_unless_one_key_sets_the_abstract(self):
        """A folded, repeated or relocated `abstract: |` key, or a metadata
        block in the body that sets the abstract, empties the abstract slice,
        so every abstract tie fails instead of reading text that the paper
        does not render as its abstract."""
        prose = (self.repo / "paper/index.qmd").read_text()
        span = PAPER_TEXT.block_scalar_span(prose, "abstract")
        self.assertIsNotNone(span, "fixture has no abstract block")
        block = prose[span[0] : span[1]]
        key = "abstract: |\n"
        cases = (
            ("folded abstract", ((key, "abstract: >\n"),)),
            ("repeated abstract key", ((block, block + key + block),)),
            (
                "abstract key only in the body",
                ((key, "summary: |\n"), ("\n# Introduction\n", f"\n{key}{block}\n# Introduction\n")),
            ),
            ("quoted abstract key repeated", ((block, f'{block}"abstract": |\n{block}'),)),
            (
                "body metadata block sets the abstract",
                ((DISCUSSION_HEADING, f"---\n{key}{block}---\n\n{DISCUSSION_HEADING}"),),
            ),
        )
        for name, edits in cases:
            with self.subTest(case=name):
                self.install_article()
                self.edit_article(edits)
                result = self.run_guard()
                self.assertNotEqual(result.returncode, 0)
                failures = failure_lines(result.stdout)
                for label in (
                    "paper must set abstract only in one abstract: | block of its front matter",
                    *ABSTRACT_TIE_LABELS,
                    *INKIND_ABSTRACT_TIE_LABELS,
                ):
                    self.assertIn(label, failures)
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
        """With the original wording restated under the discussion heading,
        only the ties that read the changed section fail."""
        for name, where, pattern, replacement, labels, decoy in SECTION_PROSE_MUTATIONS:
            with self.subTest(name=name):
                result = self.run_section_mutation(where, pattern, replacement, decoy)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(sorted(failure_lines(result.stdout)), sorted(labels))
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


class GuardSourceTests(unittest.TestCase):
    def test_no_tie_reads_the_whole_paper(self):
        """Every has_number and has_ordered call names the text it reads, none
        reads QMD, and no tie tests a literal's membership in QMD."""
        tree = ast.parse((REPO / "scripts/check_paper.py").read_text())
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id not in ("has_number", "has_ordered"):
                    continue
                texts = [keyword.value for keyword in node.keywords if keyword.arg == "text"]
                if node.func.id == "has_number" and len(node.args) > 1:
                    texts.append(node.args[1])
                if not texts or any(
                    isinstance(text, ast.Name) and text.id == "QMD" for text in texts
                ):
                    offenders.append(f"line {node.lineno}: {ast.unparse(node)}")
            elif isinstance(node, ast.Compare) and any(
                isinstance(operator, (ast.In, ast.NotIn))
                and isinstance(right, ast.Name)
                and right.id == "QMD"
                for operator, right in zip(node.ops, node.comparators)
            ):
                offenders.append(f"line {node.lineno}: {ast.unparse(node)}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
