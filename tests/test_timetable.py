from timetable import glue, parse, parse_slots, parse_equivalents


def run(*lines):
    courses, sections, problems = parse(glue(lines))
    return courses, sections, problems


# ---- day/hour parsing
def test_slots():
    assert parse_slots("M W 4 T 10") == [("M", 4), ("W", 4), ("T", 10)]
    assert parse_slots("T 7 8 9") == [("T", 7), ("T", 8), ("T", 9)]
    assert parse_slots("M W 10 W 11") == [("M", 10), ("W", 10), ("W", 11)]


# ---- normal rows
def test_normal_course():
    courses, (l1, p1), _ = run(
        "1092 CS F213 OBJECT ORIENTED PROG 3 1 - - 4 L1 PRATIK NARANG 6109 T Th F 3 10/10 AN1 16/12 FN",
        "Practical P1 Anukriti Pandey(RS) 6016 M 1 2")
    assert courses[1092] == ("CS F213", "OBJECT ORIENTED PROG", 4)
    assert l1["slots"] == [("T", 3), ("Th", 3), ("F", 3)]
    assert l1["mid"] == ("2026-10-10", "AN1") and l1["compre"] == ("2026-12-16", "FN")
    assert p1["code"] == "CS F213" and p1["slots"] == [("M", 1), ("M", 2)]


def test_cancelled():
    _, (s,), _ = run("6046 BIO G514 MOLECULAR IMMUNOLOGY 3 4 - 8 15 L1 CANCLED 10/10 FN2 15/12 AN")
    assert s["cancelled"] and s["slots"] == []


def test_project_course():
    courses, (s,), _ = run("1655 CS F266 STUDY PROJECT - - - - 3 L1 YASHVARDHAN SHARMA")
    assert courses[1655][2] == 3 and s["slots"] == []


# ---- wrapped lines (glue)
def test_title_wrapped():                                   # CS U111
    courses, (s,), _ = run("5283 CS U111 COMPUTL THINKING &",
                           "PROGRAMMING 3 2 - 7 12 L1 VINTI AGARWAL 5105 M W 3 Th 9 08/10 AN2 02/12 AN")
    assert courses[5283] == ("CS U111", "COMPUTL THINKING & PROGRAMMING", 12)


def test_hours_wrapped():                                   # CS F303
    _, (s,), _ = run("1320 CS F303 COMPUTER NETWORKS 3 1 - - 4 L1 VIRENDRA SINGH SHEKHA.. 6103 T 8 W 11 S",
                     "5", "08/10 AN1 12/12 FN")
    assert s["slots"] == [("T", 8), ("W", 11), ("S", 5)] and s["mid"] == ("2026-10-08", "AN1")


def test_rooms_split_across_lines():                        # CE F231
    _, (s,), _ = run("2280 CE F231 FLUID MECHANICS 3 - - - 3 L1 RAVIKUMAR GUNTU",
                     "1201(M", "W)", "6104(Th)", "M W 5 Th 10 07/10 FN1 08/12 FN")
    assert s["slots"] == [("M", 5), ("W", 5), ("Th", 10)]


def test_extra_instructor_lines():                          # BIO F111
    _, (s,), _ = run("1002 BIO F111 GENERAL BIOLOGY 3 - - - 3 L1 SHASHI PRAKASH SINGH 5102 M W 2 09/10 AN2 14/12 AN",
                     "Rajdeep Chowdhury")
    assert s["slots"] == [("M", 2), ("W", 2)] and "Rajdeep Chowdhury" in s["raw"]


# ---- things that must not go wrong
def test_same_code_two_comp_codes_kept_apart():             # BIO G514: FD version runs, other is cancelled
    courses, (a, b), _ = run(
        "392 BIO G514 MOLECULAR IMMUNOLOGY 3 2 - - 5 L1 ASHIS KUMAR DAS 6162 T Th F 4 10/10 FN2 15/12 AN",
        "6046 BIO G514 MOLECULAR IMMUNOLOGY 3 4 - 8 15 L1 CANCLED 10/10 FN2 15/12 AN")
    assert (a["comp_code"], a["cancelled"]) == (392, False)
    assert (b["comp_code"], b["cancelled"]) == (6046, True)


def test_unparseable_row_is_reported_not_misattached():
    _, sections, problems = run(
        "1092 CS F213 OBJECT ORIENTED PROG 3 1 - - 4 L1 PRATIK NARANG 6109 T Th F 3 10/10 AN1 16/12 FN",
        "9999 XX F999 BROKEN ROW WITHOUT CREDITS",
        "P1 Someone 6016 M 1 2")
    assert len(sections) == 1 and len(problems) == 2


def test_equivalents():
    pairs = parse_equivalents(["CS F213 OBJECT ORIENTED PROG IS C313 IS F213 CS F213 CS C313"])
    assert pairs == [("CS F213", "IS C313"), ("CS F213", "IS F213"), ("CS F213", "CS C313")]
