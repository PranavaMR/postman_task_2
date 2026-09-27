
import csv, json, re, sqlite3, sys
from pathlib import Path
import pdfplumber
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

# Section headings, with or without a leading "7." / "b)".  Order doesn't matter.
HEADINGS = {
    "evaluation": r"evaluation (scheme|components?)",
    "makeup": r"make[\s-]*up policy",
    "attendance": r"attendance policy",
    "plan": r"(course|lecture) plan[^:\n]*|course format[^:\n]*",
    "description": r"course description[^:\n]*|scope (and|&) objectives?[^:\n]*",
    "other": r"chamber consultation[^:\n]*|notices?|grading policy[^:\n]*|criterion for nc|nc criteri\w*"
             r"|text ?books?[^:\n]*|reference books|academic (honesty|conduct)[^:\n]*|course learning[^:\n]*",
}
HEADING = re.compile(r"^\s*(?:\d{1,2}\s*\.|[a-z]\))?\s*(" + "|".join(HEADINGS.values()) + r")\s*(?::|$)", re.I | re.M)

# Evaluation component types. The keyword appearing first in a row's name wins (see kind_of).
KINDS = [
    ("midsem", r"mid[\s-]*sem|mid[\s-]*term"),
    ("compre", r"compre"),
    ("lab", r"\blabs?\b|laborator|experiment"),
    ("tutorial", r"tutorial"),
    ("project", r"project|presentation|seminar|case stud|poster|article"),
    ("assignment", r"assignment|take[\s-]*home|exercise"),
    ("quiz", r"quiz|test"),
    ("continuous", r"continu|participation|daily evaluation"),
]
MAKEUP_LEVELS = [                      # first match wins
    ("none", r"no make[\s-]*up (for|in) this course|no make[\s-]*up will be available|no make[\s-]*up[^.]*whatsoever"),
    ("lenient", r"no insistence|faith and trust"),
    ("strict", r"stringent|extremely genuine|most genuine|very genuine|serious illness|prior (permission|approval)|exceptional|hospitali|extreme exigenc"),
    ("moderate", r"genuine|medical|illness|unavoidable|emergenc|appropriate ?reason|proof|requests? (received|must be submitted)|document|valid reason|genu?e?ineness|merit of the reason|regular students|not given as a routine"),
    ("per_institute", r"augs|agsr|part[\s-]*i\b|as per (the )?(institute|university|rules)|guidelines"),
]


def read_text(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def split_sections(text):
    """{'evaluation': '...', 'makeup': '...', ...} - text between one heading and the next."""
    hits = list(HEADING.finditer(text))
    sections = {}
    for i, m in enumerate(hits):
        name = next(k for k, p in HEADINGS.items() if re.fullmatch(p, m.group(1), re.I))
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        sections.setdefault(name, text[m.start():end])
    return sections


def strip_serial(line):
    return re.sub(r"^\s*[*#]?\s*((\d{1,2}|[ivx]+)\.?\s+)?", "", line)      # "1 ", "iv. ", "*"


def kind_of(line):
    """Component type from the row's name (text before its first number). The keyword that
    appears first wins, so 'Quizzes During tutorial' is a quiz and 'Tutorial Test' a tutorial."""
    name = re.split(r"\d", strip_serial(line), maxsplit=1)[0]
    if not name[:1].isupper() or len(name.split()) > 8:   # rows start with a capital and have short names
        return None
    hits = [(m.start(), k) for k, p in KINDS if (m := re.search(p, name, re.I))]
    return min(hits)[1] if hits else None


def weight(line):
    """First '25%' on the line, else the first bare number that isn't a serial no., duration, date or count."""
    if m := re.search(r"(\d+(?:\.\d+)?)\s*%", line):
        return float(m[1])
    line = strip_serial(line)
    if m := re.search(r"\b(\d{1,2})\s*\+\s*(\d{1,2})\b", line):              # "20 + 10"
        return float(m[1]) + float(m[2])
    line = re.sub(r"\d+(\s*-\s*\d+)?\s*(min|hr|hour|h\b|sec)\w*|\d+/\d+(/\d+)?|\(\s*\d+\s*\)|best \d+|out of \d+|\d+\s*out of",
                  "", line, flags=re.I)
    m = re.search(r"(?<![\w.])(\d{1,3}(?:\.\d+)?)(?![\w.])", line)
    return float(m[1]) if m else None


def parse_evaluation(section):
    """Returns (components, weights_ok, total). Weights given as marks are converted to %."""
    lines = [ln for ln in section.splitlines()[1:]
             if len(ln.split()) <= 18 and not re.search(r"[a-z]{3,}\. [A-Z]", ln)]   # skip prose sentences
    components = []
    for i, line in enumerate(lines):
        if kind := kind_of(line):
            w = weight(line)
            if w is None and i + 1 < len(lines) and not kind_of(lines[i + 1]):
                w = weight(lines[i + 1])                                     # weight wrapped to next line
            if w is None and i > 0 and not kind_of(lines[i - 1]) and "%" in lines[i - 1]:
                w = weight(lines[i - 1])                                     # ...or to the line above
            components.append({"kind": kind, "weight": w, "text": line.strip()})
    total = sum(c["weight"] or 0 for c in components)
    if total >= 150:                                                         # marks, not percentages
        for c in components:
            if c["weight"]:
                c["weight"] = round(c["weight"] * 100 / total, 1)
    return components, bool(components) and (99.5 <= total <= 100.5 or total >= 150), total


def makeup_policy(text):
    if not text:
        return "unknown", False, ""
    flat = " ".join(text.split())
    level = next((lvl for lvl, p in MAKEUP_LEVELS if re.search(p, flat, re.I)), "unknown")
    excludes = bool(re.search(r"no\s*make[\s-]*up[^.]*(quiz|tutorial|test|lab)|(quiz|tutorial)[^.]*no\s*make[\s-]*up", flat, re.I))
    return level, excludes, flat[:400]


def attendance_policy(text):
    """-> (value, quote). graded = counts for marks; required = a condition (e.g. for makeup);
    not_graded = handout says no marks; expected_only = just the standard 'expected to attend' line."""
    sentences = [s for s in re.split(r"(?<=\.)\s", " ".join(text.split())) if re.search(r"attend", s, re.I)]
    quote = " ".join(sentences)[:400]
    has = lambda p: any(re.search(p, s, re.I) for s in sentences)
    if has(r"attendance (carries|has|is (graded|counted))|(marks|weightage) for attendance|linked (with|to) (the )?attendance") \
            and not has(r"(no|not have any) marks for attendance"):
        return "graded", quote
    if has(r"mandatory|compulsory|at-?\s?least \d+\s*%|minimum \d+\s*%"):
        return "required", quote
    if has(r"(no|not have any) marks for attendance|attendance (is|will) not be (graded|counted)"):
        return "not_graded", quote
    if has(r"expected (and encouraged )?to attend"):
        return "expected_only", quote
    return "unknown", quote


def parse_handout(pdf_path):
    text = read_text(pdf_path)
    in_text = re.search(r"Course No\.?\s*:?\s*([A-Z]{2,5})\s*([A-Z]\d{3})", text)
    if m := re.match(r"\d+_([A-Z]+)_(.+)", Path(pdf_path).stem):          # e.g. 161_CS_F213.pdf
        code = f"{m[1]} {m[2]}"
    else:                                                                  # fall back to the handout itself
        code = f"{in_text[1]} {in_text[2]}" if in_text else Path(pdf_path).stem
    sections = split_sections(text)
    components, weights_ok, total = parse_evaluation(sections.get("evaluation", ""))
    kinds = {c["kind"] for c in components}
    makeup_text = sections.get("makeup") or " ".join(
        s for s in re.split(r"(?<=\.)\s", " ".join(text.split())) if re.search(r"make[\s-]*up", s, re.I))
    makeup, makeup_excludes, makeup_quote = makeup_policy(makeup_text)
    title = re.search(r"Course Title\s*:?\s*(.+)", text)

    review = []
    if len(text) < 500:
        review.append("very little text (scanned PDF?)")
    evaluation = sections.get("evaluation", "")
    pass_fail = not components and re.search(r"\bpass\b", evaluation, re.I) and re.search(r"\bfail\b", evaluation, re.I)
    if "evaluation" not in sections:
        review.append("no evaluation section found")
    elif pass_fail:
        review.append("pass/fail course, no graded components")
    elif not weights_ok:
        review.append(f"evaluation weights unclear (sum={total:g})")
    if makeup == "unknown":
        review.append("makeup policy unknown")
    cross_listed = f"{in_text[1]} {in_text[2]}" if in_text and f"{in_text[1]} {in_text[2]}" != code.split("-")[0] else None
    attendance, attendance_quote = attendance_policy(text)

    return {
        "code": code,
        "title": title[1].strip() if title else None,
        "has_midsem": ("midsem" in kinds) if (components or pass_fail) else None,
        "has_compre": ("compre" in kinds) if (components or pass_fail) else None,
        "weights_ok": weights_ok,
        "has_quiz": "quiz" in kinds, "has_lab": "lab" in kinds,
        "has_project": "project" in kinds, "has_assignment": "assignment" in kinds,
        "open_book": bool(re.search(r"\bOB\b|open[\s-]*book", sections.get("evaluation", ""), re.I)),
        "components": json.dumps(components),
        "makeup_level": makeup, "makeup_excludes_quizzes": makeup_excludes, "makeup_quote": makeup_quote,
        "attendance": attendance, "attendance_quote": attendance_quote,
        "topic_text": " ".join((sections.get("description", "") + " " + sections.get("plan", "")).split())[:4000],
        "cross_listed_as": cross_listed,
        "method": "rules",
        "needs_review": "; ".join(review),
        "source_file": Path(pdf_path).name,
    }


def add_topics(rows, n=10):
    """Top-n TF-IDF keywords per course from its description + course plan."""
    docs = [r["topic_text"] or r["code"] for r in rows]
    noise = ["chapter", "chapters", "chs", "vol", "web", "resources", "lecture", "lectures", "module", "week",
             "text", "book", "reference", "notes", "class", "understanding", "introduction", "course", "students"]
    tfidf = TfidfVectorizer(stop_words=list(ENGLISH_STOP_WORDS) + noise, ngram_range=(1, 2), max_df=0.3,
                            token_pattern=r"(?u)\b[a-zA-Z]{3,}\b")
    matrix = tfidf.fit_transform(docs)
    vocab = tfidf.get_feature_names_out()
    for row, vec in zip(rows, matrix):
        scores = vec.toarray()[0]
        row["topics"] = ", ".join(vocab[i] for i in scores.argsort()[::-1][:n] if scores[i] > 0)


def save(rows, db):
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0])
    con = sqlite3.connect(db)
    con.execute("DROP TABLE IF EXISTS handouts")
    con.execute(f"CREATE TABLE handouts ({', '.join(cols)})")
    con.executemany(f"INSERT INTO handouts VALUES ({', '.join('?' * len(cols))})", [list(r.values()) for r in rows])
    con.commit()
    review_csv = Path(db).parent / "handouts_review.csv"
    with open(review_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "source_file", "problems"])
        w.writerows([r["code"], r["source_file"], r["needs_review"]] for r in rows if r["needs_review"])
    return review_csv


if __name__ == "__main__":
    folder, db = sys.argv[1], sys.argv[2]
    pdfs = sorted(Path(folder).glob("*.pdf"))
    if not pdfs:
        sys.exit(f"No PDFs found in '{folder}'. Check the path (run from the folder containing handouts.py).")
    rows, failed = [], []
    for i, pdf in enumerate(pdfs, 1):
        print(f"[{i}/{len(pdfs)}] {pdf.name}", flush=True)
        try:
            rows.append(parse_handout(pdf))
        except Exception as e:                       # one broken PDF shouldn't stop the other 499
            print(f"    FAILED: {e}")
            failed.append(pdf.name)
    add_topics(rows)
    review_csv = save(rows, db)
    n = len(rows)
    for label, known in [("midsem yes/no", lambda r: r["has_midsem"] is not None),
                         ("evaluation weights", lambda r: r["weights_ok"]),
                         ("makeup policy", lambda r: r["makeup_level"] != "unknown"),
                         ("attendance rule", lambda r: r["attendance"] != "unknown")]:
        k = sum(1 for r in rows if known(r))
        print(f"  {label:20} known for {k}/{n} ({100 * k // n}%)")
    flagged = sum(1 for r in rows if r["needs_review"])
    print(f"{len(rows)} handouts parsed, {len(rows) - flagged} clean, {flagged} need review -> {review_csv}")
    if failed:
        print(f"{len(failed)} PDFs could not be read at all:", *failed, sep="\n  ")
