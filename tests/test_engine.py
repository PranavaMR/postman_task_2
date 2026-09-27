from pathlib import Path
import pytest
import engine, llm, recommend

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


def test_ai_del_query(con):
    prefs = llm.keyword_parse("Suggest DELs related to AI.")
    recs = recommend.recommend(con, STUDENT, prefs)
    assert recs and all(c["category"] == "DEL" for c in recs)
    assert "CS F407" in {c["code"] for c in recs}


def test_no_midsem_query_never_returns_a_course_with_midsem(con):
    facts = recommend.handout_facts(con)
    for c in recommend.recommend(con, STUDENT, {"no_midsem": True}, limit=20):
        assert facts.get(c["code"], {}).get("has_midsem") != 1
