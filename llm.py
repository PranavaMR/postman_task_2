"""Chat agent. Gemini talks to the student and decides which tool to call; the tools are thin wrappers around
engine.py / recommend.py, so every fact and every eligibility decision still comes from the deterministic code.
Without a working GEMINI_API_KEY, offline_reply() answers with simple keyword matching instead."""
import json, os, re
from dotenv import load_dotenv
import engine, recommend

load_dotenv()
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
CATEGORIES = ["CDC", "DEL", "HUEL", "OPEL"]

SYSTEM = """You are a friendly course advisor for BITS Pilani students choosing courses for First Semester 2026-27.
Talk naturally, like a helpful senior: conversational, clear and concise. Use markdown when you list courses.

The student: {profile}

Rules:
- Every fact about requirements, eligibility, courses, exams, evaluation, attendance or makeup MUST come from your
  tools. Never invent course codes, titles, rules or policies, and never recommend a course the tools did not return.
- Categories are already worked out for this student in the tool results: CDC = compulsory core,
  DEL = discipline elective, HUEL = humanities elective, OPEL = open elective.
- Interest questions ("AI-related", "something on finance"): call search_courses for the category WITHOUT keywords
  when it is small (CDC, DEL, HUEL), read the titles and topics, and choose the relevant ones yourself, thinking about
  meaning (a course on large language models IS AI-related). For OPEL (hundreds of courses) pass several keywords and
  synonyms to narrow the search, and search again with other words if the first try finds little.
- "What do I still need / what's left" questions: call get_requirements.
- Questions about one course ("can I take CS F303?", "is BITS F464 lenient?"): call get_course_details.
- has_midsem is 1 (yes), 0 (no) or null (could not be verified). If a property the student cares about is null,
  "unknown" or listed under not_verified, say it could not be verified from the handout. makeup_level "per_institute"
  means the handout defers to the institute's standard rule (genuine cases, with prior permission).
- For each course you recommend, say which requirement it counts towards, why it fits the request, and any caveat
  from its notes. Recommend the best 3-6 unless the student asks for a full list.
- If nothing fits, say so and suggest which condition to relax. If the request is unclear, answer what you can and
  ask one short follow-up question."""


def profile_text(student):
    return (f"programme(s) {', '.join(student['programmes'])}; admitted {student['admission_year']} "
            f"(year {engine.study_year(student)} of study); completed {', '.join(student['completed']) or 'nothing listed'}; "
            f"currently registered in {', '.join(student.get('current', [])) or 'nothing listed'}; "
            f"interests: {student.get('interests') or 'not given'}.")


def make_tools(con, student, log):
    def get_requirements() -> dict:
        """The student's remaining requirements: CDCs still to do and discipline / humanities elective units left."""
        result = engine.remaining(con, student)
        log.append(("get_requirements", {}, "ok"))
        return result

    def search_courses(categories: list[str] = [], code_prefixes: list[str] = [], keywords: list[str] = [],
                       no_midsem: bool = False, no_attendance: bool = False, lenient_makeup: bool = False,
                       project_based: bool = False, open_book: bool = False) -> dict:
        """Courses running this semester that the student is eligible for, with handout facts.

        Args:
            categories: any of "CDC", "DEL", "HUEL", "OPEL"; empty means all.
            code_prefixes: department prefixes such as ["CS", "BITS"]; empty means all.
            keywords: lowercase words or phrases; a course is kept only if one appears in its title or syllabus
                topics. Leave empty to get the full list for the category.
            no_midsem: only courses whose handout has no mid-semester exam.
            no_attendance: drop courses whose handout gives marks for, or requires, attendance.
            lenient_makeup: drop courses with a strict or no-makeup policy.
            project_based: only courses with a project or presentation component.
            open_book: only courses with open-book components.
        """
        args = {k: v for k, v in dict(categories=categories, code_prefixes=code_prefixes, keywords=keywords,
                                      no_midsem=no_midsem, no_attendance=no_attendance, lenient_makeup=lenient_makeup,
                                      project_based=project_based, open_book=open_book).items() if v}
        result = recommend.search_courses(
            con, student, categories=[c.upper() for c in categories], code_prefixes=[p.upper() for p in code_prefixes],
            keywords=[k.lower() for k in keywords], no_midsem=no_midsem, no_attendance=no_attendance,
            lenient_makeup=lenient_makeup, project_based=project_based, open_book=open_book)
        log.append(("search_courses", args, f"{result['total']} courses"))
        return result

    def get_course_details(code: str) -> dict:
        """Everything known about one course for this student: eligibility (or why not), exam dates, evaluation
        components, makeup and attendance policy with quotes from the handout.

        Args:
            code: a course code such as "CS F407".
        """
        result = recommend.course_details(con, student, code)
        log.append(("get_course_details", {"code": code}, "eligible" if result["eligible"] else "not eligible"))
        return result

    return [get_requirements, search_courses, get_course_details]


def status():
    """-> (ok, message). Makes one tiny request so a bad key or model name shows up before the student asks."""
    if not os.getenv("GEMINI_API_KEY"):
        return False, "No GEMINI_API_KEY in .env: running in offline keyword mode."
    try:
        from google import genai
        genai.Client().models.generate_content(model=MODEL, contents="Reply with the word OK.")
        return True, f"Gemini connected ({MODEL})."
    except Exception as e:
        return False, f"Gemini is not working, so offline keyword mode is used. Error: {e}"


def chat(con, student, history, question):
    """history: earlier turns as [{"role": "user" | "assistant", "text": ...}]. -> (reply, tool_log)"""
    from google import genai
    from google.genai import types
    log = []
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM.format(profile=profile_text(student)), tools=make_tools(con, student, log),
        temperature=0.3, automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=8))
    past = [types.Content(role="user" if m["role"] == "user" else "model", parts=[types.Part(text=m["text"])])
            for m in history]
    reply = genai.Client().chats.create(model=MODEL, config=config, history=past).send_message(question)
    return reply.text or "Sorry, I couldn't finish that one. Could you rephrase or narrow it down?", log


# ------------------------------------------------ offline mode ------------------------------------------------
STOPWORDS = set("""a an the i im i'm me my we you your is are am be to of for in on at by with and or but so any some
all only just also please give show list suggest recommend want wanted looking look find need needs prefer like would
could can should what which who whose where how many much courses course electives elective related relating based
around about into this that these those there their them it its do does did have has having pursue take taking
semester sem one ones good best interested interest list get me some kind type code codes starting start begin
beginning prefix department departmental discipline humanities open core compulsory left remaining pending
requirement requirements midsem mid attendance makeup make up lenient project evaluation book either not no without
policy policies scheme exam exams list lists fxxx tell know details""".split())
SYNONYMS = {"ai": ["artificial intelligence", "machine learning", "neural", "deep learning", "intelligent",
                   "language model", "llm", "agents"],
            "ml": ["machine learning", "learning", "neural", "data mining"],
            "llm": ["language model", "llm", "nlp", "natural language"],
            "finance": ["finance", "financial", "investment", "portfolio"],
            "music": ["music", "musicology"]}


def parse_offline(question, prefixes):
    q = question.lower()
    cats = [c for c, p in [("CDC", r"\bcdcs?\b|\bcore\b|compulsory"), ("DEL", r"\bdels?\b|discipline elective|department(al)? elective"),
                           ("HUEL", r"\bhuels?\b|humanit"), ("OPEL", r"\bopels?\b|open elective")] if re.search(p, q)]
    wants_prefix = re.search(r"start|begin|prefix|code|\b[a-z]{2,5} f(xxx|\d)", q)
    code_prefixes = [w for w in re.findall(r"\b[A-Z]{2,5}\b", question) if w in prefixes and wants_prefix
                     and w not in ("DEL", "OPEL", "HUEL", "CDC")]
    if not cats and re.search(r"\belectives?\b", q):
        cats = ["DEL", "HUEL", "OPEL"]
    flags = {"no_midsem": bool(re.search(r"no mid ?-?sem|without (a )?mid ?-?sem", q)),
             "no_attendance": bool(re.search(r"no attendance|attendance (is )?not (required|compulsory)", q)),
             "lenient_makeup": "lenient" in q,
             "project_based": "project" in q,
             "open_book": bool(re.search(r"open ?-?book", q))}
    words = [w for w in re.findall(r"[a-z]+", q) if w not in STOPWORDS and len(w) > 1 and not re.fullmatch(r"f\d{3}", w)
             and w.upper() not in prefixes and w not in ("cdc", "cdcs", "del", "dels", "huel", "huels", "opel", "opels")]
    keywords = [k for w in words for k in SYNONYMS.get(w, [w] if len(w) > 2 else [])]
    return {"categories": cats, "code_prefixes": [p.upper() for p in code_prefixes], "keywords": keywords, **flags}


OFFLINE_NOTE = "_Offline mode: simple keyword matching, so results can be rough._\n\n"


def offline_course(con, student, code):
    d = recommend.course_details(con, student, code)
    status = f"eligible, counts as **{d['category']}**" if d["eligible"] else f"not available to you: {d['reason_not_eligible']}"
    h = d["handout"] if isinstance(d["handout"], dict) else {}
    midsem = {1: "yes", 0: "no"}.get(h.get("has_midsem"), "not verified")
    exams = "; ".join(f"{e['section']} midsem {e['midsem'] or '-'}, compre {e['compre'] or '-'}" for e in d["exams"])
    text = (f"**{d['code']} {d['title'] or ''}** ({d['units'] or '?'} units): {status}.\n\n"
            f"midsem: {midsem}, makeup: {h.get('makeup_level', 'not verified')}, "
            f"attendance: {h.get('attendance', 'not verified')}" + (f"\n\nExams: {exams}" if exams else ""))
    return text, [("get_course_details", {"code": d["code"]}, "ok")]


def offline_requirements(con, student):
    need = engine.remaining(con, student)
    lines = [f"**{p['programme'].title()}**: {len(p['cdc_left'])} CDCs left ({', '.join(p['cdc_left']) or 'none'}); "
             f"DEL units left: {'not verified' if p['del_left'] is None else p['del_left']}" for p in need["programmes"]]
    return "\n".join(lines + [f"HUEL units left: {need['huel_left']}"] + need["notes"]), [("get_requirements", {}, "ok")]


def offline_search(con, student, filters):
    result = recommend.search_courses(con, student, limit=8, **filters)
    log = [("search_courses", {k: v for k, v in filters.items() if v}, f"{result['total']} courses")]
    if not result["courses"]:
        return "No eligible course matched that. Try fewer conditions or different words.", log
    lines = []
    for c in result["courses"]:
        why = "; ".join(c["matched"] + c["not_verified"] + c["notes"])
        lines.append(f"- **{c['code']} {c['title']}** ({c['category']}, {c['units']} units)" + (f": {why}" if why else ""))
    return f"Found {result['total']} matching courses, top {len(lines)}:\n" + "\n".join(lines), log


def offline_reply(con, student, question):
    if m := re.search(r"\b([A-Za-z]{2,5}) ?([FGCUfgcu]\d{3}[A-Za-z]?)\b", question):
        text, log = offline_course(con, student, f"{m[1]} {m[2]}")
    elif re.search(r"\b(left|remaining|pending|still need|do i need)\b", question.lower()):
        text, log = offline_requirements(con, student)
    else:
        prefixes = {r[0].split()[0] for r in con.execute("SELECT code FROM courses")}
        text, log = offline_search(con, student, parse_offline(question, prefixes))
    return OFFLINE_NOTE + text, log
