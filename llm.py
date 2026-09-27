#The only places an LLM is used: understanding the question and writing the answer.
#Without GEMINI_API_KEY (or if the call fails) a simple keyword parser and template are used instead.
import json, os, re
from dotenv import load_dotenv

load_dotenv()
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
FLAGS = ["no_midsem", "no_attendance", "lenient_makeup", "project_based", "open_book"]
CATEGORIES = {"CDC", "DEL", "HUEL", "OPEL"}

PARSE_PROMPT = """Turn a BITS Pilani student's course-selection question into JSON with exactly these keys:
"category": one of "CDC", "DEL", "HUEL", "OPEL" or null (DEL = discipline elective, HUEL = humanities elective,
            OPEL = open elective, CDC = compulsory core course),
"topics": 3-8 lowercase words or short phrases that would appear in titles or syllabi of courses on the subject
          the student wants, including synonyms (e.g. AI -> "artificial intelligence", "machine learning", "neural");
          [] if no subject is mentioned,
"no_midsem", "no_attendance", "lenient_makeup", "project_based", "open_book": true only if the student asks for it.
Question: {q}"""

ANSWER_PROMPT = """You are a BITS Pilani course advisor. Answer the student's question using ONLY the facts below.
For each recommended course give one short line: code and title, which requirement it counts towards,
the course properties relevant to the question, and why it matches. Say plainly when something is "not verified".
Mention any policy notes. Do not invent courses, rules or course properties. If the list is empty, say that no
eligible course matched and suggest which preference to relax.

Question: {q}
Student requirements: {need}
Recommended courses: {courses}"""


def client():
    if not os.getenv("GEMINI_API_KEY"):
        return None
    from google import genai
    return genai.Client()


def ask(prompt, as_json=False):
    from google.genai import types
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json" if as_json else None)
    return client().models.generate_content(model=MODEL, contents=prompt, config=config).text


def clean(prefs):
    out = {k: bool(prefs.get(k)) for k in FLAGS}
    cat = str(prefs.get("category") or "").upper()
    out["category"] = cat if cat in CATEGORIES else None
    out["topics"] = [str(t).lower() for t in prefs.get("topics") or [] if len(str(t)) > 2]
    return out


SYNONYMS = {"ai": ["artificial intelligence", "machine learning", "neural", "deep learning", "intelligent"],
            "ml": ["machine learning", "learning", "neural"], "finance": ["finance", "financial", "investment"]}


def keyword_parse(q):
    q = q.lower()
    cats = [("HUEL", r"\bhuels?\b|humanit"), ("OPEL", r"\bopels?\b|open elective"),
            ("DEL", r"\bdels?\b|discipline elective"), ("CDC", r"\bcdcs?\b|\bcore\b")]
    prefs = {"category": next((c for c, p in cats if re.search(p, q)), None),
             "no_midsem": bool(re.search(r"no mid ?-?sem|without (a )?mid ?-?sem", q)),
             "no_attendance": bool(re.search(r"no attendance|attendance (is )?not (required|compulsory)", q)),
             "lenient_makeup": bool(re.search(r"lenient|easy make ?-?up", q)),
             "project_based": "project" in q,
             "open_book": bool(re.search(r"open ?-?book", q))}
    m = re.search(r"(?:related to|about|on|in)\s+([a-z &+-]+?)(?:\s+(?:with|and|that|which)\b|[.,?]|$)", q)
    words = m.group(1).split() if m else []
    prefs["topics"] = [t for w in words for t in SYNONYMS.get(w, [w])]
    return clean(prefs)


def parse_query(q):
    if client():
        try:
            return clean(json.loads(ask(PARSE_PROMPT.format(q=q), as_json=True)))
        except Exception as e:
            print("LLM parse failed, using keywords:", e)
    return keyword_parse(q)


def facts_for(courses):
    keys = ["code", "title", "units", "category", "matched", "unverified", "notes"]
    return [{**{k: c[k] for k in keys}, "makeup_policy_quote": (c.get("makeup_quote") or "")[:200]} for c in courses]


def template_answer(courses):
    if not courses:
        return "No eligible course matched all your preferences. Try relaxing one of them."
    lines = []
    for c in courses:
        why = "; ".join(c["matched"] + c["unverified"] + c["notes"]) or "eligible"
        lines.append(f"- **{c['code']} {c['title']}** ({c['category']}, {c['units']} units): {why}")
    return "\n".join(lines)


def answer(q, need, courses):
    if client():
        try:
            return ask(ANSWER_PROMPT.format(q=q, need=json.dumps(need), courses=json.dumps(facts_for(courses))))
        except Exception as e:
            print("LLM answer failed, using template:", e)
    return template_answer(courses)


if __name__ == "__main__":
    for q in ["Suggest DELs related to AI.", "I want an OPEL with no attendance requirement.",
              "Suggest courses with no midsem and a lenient makeup policy.",
              "I need a HUEL and prefer project-based evaluation."]:
        print(q, "->", parse_query(q))
