"""
Comments for my reference
Course search over the engine's eligible list, with handout facts attached.
These are the functions the LLM agent calls as tools (see llm.py); the offline mode uses them too."""
import engine

LENIENT = {"lenient", "moderate"}
STRICT = {"none", "strict"}
CATEGORY_ORDER = {"CDC": 0, "DEL": 1, "HUEL": 2, "OPEL": 3}


def handout_facts(con):
    cols = ["code", "has_midsem", "has_project", "open_book", "makeup_level", "makeup_quote", "attendance",
            "attendance_quote", "components", "weights_ok", "topics", "topic_text", "source_file"]
    facts = {}
    for row in con.execute(f"SELECT {', '.join(cols)} FROM handouts"):
        facts.setdefault(row[0], dict(zip(cols, row)))
    return facts


def topic_score(title, h, topics):
    text = " ".join([title, h.get("topics") or "", h.get("topic_text") or ""]).lower()
    title = title.lower()
    return sum(2 if t.lower() in title else 1 for t in topics if t.lower() in text)


def check(course, h, prefs):
    """-> (keep, matched, unverified) for one course against the preference flags."""
    matched, unverified = [], []
    if not h:
        return True, [], ["no handout found, evaluation and policies not verified"]
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


def search_courses(con, student, categories=(), code_prefixes=(), keywords=(), limit=60, **prefs):
    """Eligible courses filtered by category / code prefix / preference flags; ranked by keyword hits if given.
    Returns {"total": n, "courses": [...compact dicts...], "truncated": bool}."""
    facts = handout_facts(con)
    units_now = sum(engine.unit_lookup(con).get(c, 3) for c in student.get("current", []))
    found = []
    for c in engine.eligible(con, student):
        if categories and c["category"] not in categories:
            continue
        if code_prefixes and c["code"].split()[0] not in code_prefixes:
            continue
        h = facts.get(c["code"], {})
        score = topic_score(c["title"], h, keywords) if keywords else 0
        if keywords and score == 0:
            continue
        keep, matched, unverified = check(c, h, prefs)
        if not keep:
            continue
        notes = list(c["notes"])
        if units_now + (c["units"] or 0) > engine.MAX_UNITS:
            notes.append(f"would take you over {engine.MAX_UNITS} units this semester (Reg 1.01)")
        found.append({"code": c["code"], "title": c["title"], "units": c["units"], "category": c["category"],
                      "topics": h.get("topics"), "has_midsem": h.get("has_midsem"),
                      "makeup_level": h.get("makeup_level"), "attendance": h.get("attendance"),
                      "matched": matched, "not_verified": unverified, "notes": notes, "score": score})
    found.sort(key=lambda c: (-c["score"], len(c["not_verified"]), CATEGORY_ORDER[c["category"]], c["code"]))
    return {"total": len(found), "courses": found[:limit], "truncated": len(found) > limit}


def course_details(con, student, code):
    """Everything known about one course: eligibility for this student, exams, handout facts with quotes."""
    code = " ".join(code.upper().split())
    ok, why = engine.why_not(con, student, code)
    row = con.execute("SELECT title, units FROM courses WHERE code = ? ORDER BY comp_code", (code,)).fetchone()
    exams = con.execute("SELECT DISTINCT section, midsem, compre FROM sections s JOIN courses c USING (comp_code) "
                        "WHERE c.code = ? AND s.cancelled = 0 AND (midsem != '' OR compre != '')", (code,)).fetchall()
    h = handout_facts(con).get(code, {})
    return {"code": code, "title": row[0] if row else None, "units": row[1] if row else None,
            "eligible": ok, "category" if ok else "reason_not_eligible": why,
            "exams": [{"section": s, "midsem": m, "compre": c} for s, m, c in exams],
            "handout": {k: h.get(k) for k in ("has_midsem", "components", "weights_ok", "makeup_level", "makeup_quote",
                                              "attendance", "attendance_quote", "topics", "source_file")} if h
            else "no handout found in the dataset"}
