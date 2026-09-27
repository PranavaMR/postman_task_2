"""Engine + recommender checks. Need the built database, so they're skipped if it doesn't exist."""
from pathlib import Path
import pytest
import engine

pytestmark = pytest.mark.skipif(not Path(engine.DB).exists(), reason="run the three preprocessing scripts first")
STUDENT = {"programmes": ["COMPUTER SCIENCE"], "admission_year": 2024,
           "completed": ["CS F111", "CS F213", "HSS F334"], "current": ["CS F211"]}


@pytest.fixture(scope="module")
def con():
    return engine.connect()


def test_equivalents_count_as_done(con):
    assert "IS F213" in engine.done_set(con, ["CS F213"])


def test_remaining(con):
    need = engine.remaining(con, STUDENT)
    cs = need["programmes"][0]
    assert "CS F213" not in cs["cdc_left"] and "CS F211" not in cs["cdc_left"]
    assert cs["del_left"] == 12 and need["huel_left"] == 5


def test_eligible_excludes_done_first_year_and_new_curriculum(con):
    courses = engine.eligible(con, STUDENT)
    codes = {c["code"] for c in courses}
    assert not codes & {"CS F213", "IS F213", "CS F211"}
    assert all(c["comp_code"] < 5000 for c in courses)
    assert not any(c.split()[1][1] == "1" for c in codes)


def test_categories(con):
    cats = {c["code"]: c["category"] for c in engine.eligible(con, STUDENT)}
    assert cats["CS F407"] == "DEL" and cats["CS F351"] == "CDC" and cats["GS F211"] == "HUEL"


def test_why_not(con):
    assert engine.why_not(con, STUDENT, "CS F407") == (True, "DEL")
    assert engine.why_not(con, STUDENT, "CS F213")[0] is False
    assert "first-year" in engine.why_not(con, STUDENT, "MATH F111")[1]
    assert "not offered" in engine.why_not(con, STUDENT, "AN F999")[1]


def test_2026_admit_gets_warning(con):
    notes = engine.remaining(con, {**STUDENT, "admission_year": 2026})["notes"]
    assert any(n.startswith("2026") for n in notes)


def test_study_year_and_assumed_cdcs(con):
    assert engine.study_year({"admission_year": 2024}) == 3
    assert engine.study_year({"admission_year": 2024, "year": 4}) == 4
    assumed = engine.assumed_done(con, ["COMPUTER SCIENCE"], 3)
    assert "CS F213" in assumed and not any(engine.level(c) >= 3 for c in assumed)
