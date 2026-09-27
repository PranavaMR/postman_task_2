"""Eligible courses -> handout facts -> preference matching -> policy checks -> ranked list.

prefs (from llm.parse_query or the keyword fallback):
    {"category": "DEL" | "HUEL" | "OPEL" | "CDC" | None, "topics": ["machine learning", ...],
     "no_midsem": bool, "no_attendance": bool, "lenient_makeup": bool,
     "project_based": bool, "open_book": bool}
"""
import engine

LENIENT = {"lenient", "moderate"}
STRICT = {"none", "strict"}


def handout_facts(con):
    cols = ["code", "has_midsem", "has_project", "open_book", "makeup_level", "makeup_quote",
            "attendance", "attendance_quote", "topics", "topic_text", "weights_ok", "source_file"]
    facts = {}
    for row in con.execute(f"SELECT {', '.join(cols)} FROM handouts"):
        facts.setdefault(row[0], dict(zip(cols, row)))
    return facts


def topic_score(title, h, topics):
    text = " ".join([title, h.get("topics") or "", h.get("topic_text") or ""]).lower()
    title = title.lower()
    return sum(2 if t.lower() in title else 1 for t in topics if t.lower() in text)


def check(course, h, prefs):
    """-> (keep, matched, unverified) for one course against the user's preferences."""
    matched, unverified = [], []
    if prefs.get("category") and course["category"] != prefs["category"]:
        return False, [], []
    if prefs.get("topics"):
        score = topic_score(course["title"], h, prefs["topics"])
        if score == 0:
            return False, [], []
        course["score"] = score
        matched.append("matches your topic interest")
    if not h:
        unverified.append("no handout found, evaluation and policies not verified")
        return True, matched, unverified

    midsem, attendance, makeup = h.get("has_midsem"), h.get("attendance"), h.get("makeup_level")
    rules = [
        ("no_midsem", midsem == 0, midsem == 1, "no midsem in the evaluation scheme"),
        ("no_attendance", attendance in ("not_graded", "expected_only"), attendance in ("graded", "required"),
         "no attendance marks stated in the handout"),
        ("lenient_makeup", makeup in LENIENT, makeup in STRICT, f"makeup policy: {makeup}"),
        ("project_based", h.get("has_project") == 1, h.get("has_project") == 0, "has a project/presentation component"),
        ("open_book", h.get("open_book") == 1, h.get("open_book") == 0, "has open-book components"),
    ]
    for key, ok, bad, text in rules:
        if not prefs.get(key):
            continue
        if bad:
            return False, [], []
        (matched if ok else unverified).append(text if ok else f"{key.replace('_', ' ')}: not stated in handout")
    return True, matched, unverified


def policy_notes(course, student, units_now):
    notes = list(course["notes"])
    if units_now + (course["units"] or 0) > engine.MAX_UNITS:
        notes.append(f"would exceed {engine.MAX_UNITS} units this semester (Reg 1.01)")
    return notes


def recommend(con, student, prefs, limit=8):
    facts = handout_facts(con)
    units = engine.unit_lookup(con)
    units_now = sum(units.get(c, 3) for c in student.get("current", []))
    picks = []
    for course in engine.eligible(con, student):
        h = facts.get(course["code"], {})
        keep, matched, unverified = check(course, h, prefs)
        if not keep:
            continue
        course.update(matched=matched, unverified=unverified, notes=policy_notes(course, student, units_now),
                      makeup_quote=h.get("makeup_quote"), attendance_quote=h.get("attendance_quote"),
                      source=h.get("source_file"))
        picks.append(course)
    order = {"CDC": 0, "DEL": 1, "HUEL": 2, "OPEL": 3}
    picks.sort(key=lambda c: (-c.get("score", 0), len(c["unverified"]), order[c["category"]], c["code"]))
    return picks[:limit]


if __name__ == "__main__":
    con = engine.connect()
    student = {"programmes": ["COMPUTER SCIENCE"], "admission_year": 2024,
               "completed": ["CS F111", "CS F213", "CS F214", "CS F215", "CS F222"], "current": []}
    prefs = {"category": "DEL", "topics": ["artificial intelligence", "machine learning", "neural", "deep learning"],
             "no_midsem": False}
    for c in recommend(con, student, prefs):
        print(c["code"], c["title"], c["category"], c["matched"], c["unverified"], c["notes"])
