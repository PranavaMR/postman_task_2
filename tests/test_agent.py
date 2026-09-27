"""Tools, offline mode and the Gemini tool-calling loop (with the network call replaced by a fake model)."""
import os
from pathlib import Path
import pytest
import engine, llm, recommend
import google.genai

pytestmark = pytest.mark.skipif(not Path(engine.DB).exists(), reason="run the three preprocessing scripts first")
STUDENT = {"programmes": ["COMPUTER SCIENCE"], "admission_year": 2024, "year": 3,
           "completed": ["CS F211", "CS F212", "CS F213", "CS F214", "CS F215", "CS F222"], "current": ["CS F241"]}


@pytest.fixture(scope="module")
def con():
    return engine.connect()


@pytest.fixture(scope="module")
def prefixes(con):
    return {r[0].split()[0] for r in con.execute("SELECT code FROM courses")}


def codes(result):
    return {c["code"] for c in result["courses"]}


# ---- tools
def test_all_dels_returned_for_semantic_choice(con):
    result = recommend.search_courses(con, STUDENT, categories=["DEL"])
    assert result["total"] == 22 and {"BITS F471", "CS F407", "BITS F464", "CS F425"} <= codes(result)


def test_code_prefix_and_multiple_categories(con):
    result = recommend.search_courses(con, STUDENT, categories=["DEL", "OPEL"], code_prefixes=["CS", "BITS"])
    assert result["total"] > 0 and all(c["code"].split()[0] in ("CS", "BITS") for c in result["courses"])
    assert {c["category"] for c in result["courses"]} <= {"DEL", "OPEL"}


def test_music_huel(con):
    assert codes(recommend.search_courses(con, STUDENT, categories=["HUEL"], keywords=["music"])) == {"HSS F223", "HSS F329"}


def test_no_midsem_filter_never_returns_a_midsem_course(con):
    for c in recommend.search_courses(con, STUDENT, no_midsem=True)["courses"]:
        assert c["has_midsem"] != 1


def test_course_details(con):
    d = recommend.course_details(con, STUDENT, "bits f471")
    assert d["eligible"] and d["category"] == "DEL" and d["exams"]
    assert recommend.course_details(con, STUDENT, "CS F213")["eligible"] is False


# ---- offline mode: every prompt the user tried
@pytest.mark.parametrize("question, categories, prefixes_, must_have_keyword", [
    ("I'm looking for an AI related DEL to pursue", ["DEL"], [], "machine learning"),
    ("what are the list of department electives for CS", ["DEL"], [], None),
    ("only electives starting with CS in their course code", ["DEL", "HUEL", "OPEL"], ["CS"], None),
    ("give me a HUEL list related to music", ["HUEL"], [], "music"),
    ("give me a DEL/OPEL list related to AI ( either a BITS Fxxx course or a CS Fxxx course )", ["DEL", "OPEL"], ["BITS", "CS"], "neural"),
    ("agentic AI", [], [], "agentic"),
])
def test_offline_parse(prefixes, question, categories, prefixes_, must_have_keyword):
    p = llm.parse_offline(question, prefixes)
    assert p["categories"] == categories and p["code_prefixes"] == prefixes_
    if must_have_keyword:
        assert must_have_keyword in p["keywords"]
    else:
        assert p["keywords"] == []


def test_offline_ai_del_includes_llm_course(con):
    text, _ = llm.offline_reply(con, STUDENT, "I'm looking for an AI related DEL to pursue")
    assert "BITS F471" in text and "CS F407" in text


def test_offline_requirements_and_course_questions(con):
    assert "CS F303" in llm.offline_reply(con, STUDENT, "what cdcs are left for me")[0]
    assert "not available" in llm.offline_reply(con, STUDENT, "can I take CS F213?")[0]


# ---- the Gemini loop, with only the network call faked
def test_gemini_calls_tools_and_keeps_history(con, monkeypatch):
    from google.genai import models, types
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    sent = []

    def fake(self, model, contents, config):
        sent.append(contents)
        last = contents[-1]
        if any(p.function_response for p in last.parts):
            result = last.parts[0].function_response.response["result"]
            text = ", ".join(c["code"] for c in result["courses"] if c["code"] in ("BITS F471", "CS F407"))
            part = types.Part(text=text)
        else:
            part = types.Part(function_call=types.FunctionCall(name="search_courses", args={"categories": ["DEL"]}))
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[part]))])

    monkeypatch.setattr(models.Models, "_generate_content", fake)
    history = [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "Hello!"}]
    reply, log = llm.chat(con, STUDENT, history, "AI related DELs?")
    assert reply == "BITS F471, CS F407"
    assert log == [("search_courses", {"categories": ["DEL"]}, "22 courses")]
    assert [c.role for c in sent[0]][:2] == ["user", "model"]


def test_tool_schemas_build():
    from google import genai
    from google.genai import types
    client = genai.Client(api_key="dummy")
    for tool in llm.make_tools(None, STUDENT, []):
        assert types.FunctionDeclaration.from_callable(client=client, callable=tool).name == tool.__name__
