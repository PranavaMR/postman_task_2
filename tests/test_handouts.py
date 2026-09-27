from pathlib import Path
import pytest
from handouts import split_sections, parse_evaluation, makeup_policy, attendance_policy, kind_of, parse_handout


# ---- evaluation tables
def test_percent_table():                                     # BIO F313
    comps, ok, total = parse_evaluation("""7. Evaluation Scheme:
Component Duration Weightage % Date & Time Remarks
Mid-Semester Test 90 Min. 25 10/10 FN1 CB
Assignment/in-class Quizzes/ - 15 CB/OB
Course Quizzes (2) - 20 TBA CB
Comprehensive 3 Hrs. 40 15/12 FN CB and OB""")
    assert [(c["kind"], c["weight"]) for c in comps] == \
        [("midsem", 25), ("assignment", 15), ("quiz", 20), ("compre", 40)]
    assert ok


def test_marks_converted_to_percent():                        # SNS F242: total 300 marks
    comps, ok, _ = parse_evaluation("""Evaluation Scheme:
Mid Sem Test 90 min 90 05/10 AN1 Open Book
Quizzes* 15 min 60 Tutorial hour Closed Book
Class Participation** - 20 Lecture hour Open Book
Comprehensive 3 hrs 130 03/12 FN Closed & Open Book""")
    assert [c["weight"] for c in comps] == [30.0, 20.0, 6.7, 43.3] and ok
    assert comps[1]["kind"] == "quiz"                           # not "tutorial"


def test_serial_numbers_and_wrapped_weights():                # CE F213 / HSS F334 layouts
    comps, _, _ = parse_evaluation("""Evaluation Scheme:
1 Mid-semester Exam 90 minutes 25 Closed book
Mid semester
i. 35 90 min. 6/10/2026 FN1 CB""")
    assert [c["weight"] for c in comps] == [25, 35]


def test_duration_range_not_a_weight():                       # CS U111
    comps, _, _ = parse_evaluation("Evaluation Scheme\nProgramming Quiz 1-2 hrs 70 Nov 15 Open-book")
    assert comps[0]["weight"] == 70


def test_no_midsem_course():                                  # BITS U104
    comps, ok, _ = parse_evaluation("""Evaluation Scheme:
Daily Evaluation in the NA 70% Lab Hours Open Book
Comprehensive To be 30% To be Closed Book""")
    assert {c["kind"] for c in comps} == {"continuous", "compre"} and ok


def test_prose_is_not_a_component():                          # BIO F211 note under the table
    assert kind_of("Please note that of evaluation components will be held during class/tutorial hours and may") is None
    assert kind_of("be announced. (Max. Marks=200 for the course)") is None


# ---- sections
def test_heading_vs_sentence():
    text = "Besides, surprise\nevaluation components will be\nheld later.\n6. Evaluation Scheme\nQuiz 10%"
    assert split_sections(text)["evaluation"].startswith("6. Evaluation Scheme")


# ---- makeup
@pytest.mark.parametrize("quote, level", [
    ("10. Makeup Policy: No makeup for this course.", "none"),                                     # BITS F101
    ("12. Make-up Policy: Stringent. Only in the most genuine cases, as judged by the IC.", "strict"),  # BITS U104
    ("Make-up Policy: Make-up will be granted only in case of exceptional cases such as hospitalization.", "strict"),
    ("Make-up Policy: Make-up will be granted for genuine cases only (No make-up for tutorial tests).", "moderate"),
    ("7. Make-up Policy: There will be no insistence on certificate but all decisions ... mutual faith and trust.", "lenient"),
    ("", "unknown"),
])
def test_makeup_levels(quote, level):
    assert makeup_policy(quote)[0] == level


def test_makeup_excludes_quizzes():                           # CHE F213
    assert makeup_policy("Make-up will be granted for genuine cases only (No make-up for tutorial tests).")[1]


# ---- attendance
def test_attendance_values():
    assert attendance_policy("This is also linked with the attendance in the lecture class.")[0] == "graded"       # SNS F242
    assert attendance_policy("class attendance is mandatory for evaluation of these components.")[0] == "required"  # BIO F211
    assert attendance_policy("However, we do not have any marks for attendance in lectures.")[0] == "not_graded"   # CS F213 (part)
    assert attendance_policy("Each student is expected to attend all classes and participate.")[0] == "expected_only"
    assert attendance_policy("Notices will be on Nalanda.")[0] == "unknown"


# ---- whole files (runs only if the sample handouts are present)
RAW = Path(__file__).parents[1] / "data" / "raw" / "handouts"


@pytest.mark.skipif(not (RAW / "366_MATH_F312.pdf").exists(), reason="sample handouts not present")
def test_real_handout():
    row = parse_handout(RAW / "366_MATH_F312.pdf")
    assert row["code"] == "MATH F312" and row["has_midsem"] and row["makeup_level"] == "strict"
    assert row["makeup_excludes_quizzes"] and row["needs_review"] == ""


def test_marks_mention_near_attendance_is_not_graded():      # BIO F211
    text = "(Max. Marks=200 for the course) # No Make ups will be given and class attendance is mandatory for evaluation."
    assert attendance_policy(text)[0] == "required"
