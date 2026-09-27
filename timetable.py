"""Timetable PDF -> SQLite. Keeps what the recommender needs: courses (code, title,
units), sections (cancelled flag, day-hour slots, exam dates, raw text) and the
equivalent-courses table.

    python timetable.py data/raw/timetable.pdf data/processed/academic.db
"""
import re, sqlite3, sys
from pathlib import Path
import pdfplumber

YEAR = 2026                        # semester year, for turning "09/10" into a date
COURSE = re.compile(r"^(\d{1,4}) ([A-Z]{2,5} [A-Z]\d{3}[A-Z]?(?:-\d)?) (.+?) ([\d-]+ [\d-]+ [\d-]+ [\d-]+) (\d+) ([LTP]\d\w*)(.*)$")
SECTION = re.compile(r"^(?:Tutorial |Practical )?([LTP]\d\w*)(.*)$")
COURSE_START = re.compile(r"^\d{1,4} [A-Z]{2,5} [A-Z]\d{3}")
DAY, HOUR = r"(?:Th|M|T|W|F|S)", r"(?:1[0-2]|[1-9])"
SLOTS = re.compile(rf"(?:(?:\b{DAY}\b ?)+(?:\b{HOUR}\b ?)+)+")
EXAM = re.compile(r"(\d\d)/(\d\d) (FN|AN)([12]?)")
CODE = re.compile(r"\b([A-Z]{2,5} [A-Z]\d{3}[A-Z]?)\b")
HEADER = {"CREDIT", "MIDSEM", "COMPRE", "SESSION", "DATE &", "COM", "H", "U/C", "L P T S"}


def read_lines(pdf_path):
    """Return (course-page lines, equivalents-page lines), without headers and page numbers."""
    course_lines, equiv_lines, in_equiv = [], [], False
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            in_equiv = ("EQUIVALENT COURSES" in text or in_equiv) and "LIBRARY AND BITS COOP" not in text
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if lines and lines[-1].isdigit():
                lines.pop()                                    # page number
            lines = [ln for ln in lines if ln not in HEADER
                     and not ln.startswith(("II. COURSEWISE", "Note:", "SEC ", "Instructor ROOM", "COD "))]
            if in_equiv:
                equiv_lines += lines
            elif "COURSEWISE TIMETABLE" in text:
                course_lines += lines
    return course_lines, equiv_lines


def glue(lines):
    """One string per course/section row: a line that doesn't start a new row is a
    wrapped piece of the row above, so it is glued back on."""
    rows = []
    for line in lines:
        if COURSE_START.match(line) or SECTION.match(line) or not rows:
            rows.append(line)
        else:
            rows[-1] += " " + line
    return rows


def parse_slots(text):
    """'M W 4 T 10' -> [('M',4),('W',4),('T',10)]  (uses the last day/hour run in the text)"""
    found = SLOTS.findall(text)
    slots, days, last_num = [], [], False
    for tok in (found[-1].split() if found else []):
        if tok.isdigit():
            slots += [(d, int(tok)) for d in days]
            last_num = True
        else:
            days = [tok] if last_num else days + [tok]
            last_num = False
    return slots


def parse_section(comp, code, label, rest):
    exams = {("mid" if n else "compre"): (f"{YEAR}-{m}-{d}", s + n) for d, m, s, n in EXAM.findall(rest)}
    return {"comp_code": comp, "code": code, "section": label, "cancelled": "CANCLED" in rest,
            "slots": parse_slots(EXAM.sub("", rest)), "raw": rest.strip(), **exams}


def parse(rows):
    """Returns (courses, sections, problems). Rows that can't be parsed are reported,
    and their sections are skipped rather than attached to the wrong course."""
    courses, sections, problems, comp, code = {}, [], [], None, None
    for row in rows:
        if m := COURSE.match(row):
            comp, code, title, _lpts, units, label, rest = m.groups()
            comp = int(comp)
            courses[comp] = (code, title, int(units))
            sections.append(parse_section(comp, code, label, rest))
        elif COURSE_START.match(row):
            problems.append(row)
            comp = code = None
        elif (m := SECTION.match(row)) and comp:
            sections.append(parse_section(comp, code, *m.groups()))
        elif m:
            problems.append(f"(orphan section) {row}")
    return courses, sections, problems


def parse_equivalents(lines):
    """'CS F213 OBJECT ORIENTED PROG IS C313 IS F213 ...' -> [('CS F213','IS C313'), ...]"""
    pairs = []
    for line in lines:
        codes = CODE.findall(line)
        pairs += [(codes[0], c) for c in codes[1:] if c != codes[0]]
    return pairs


def save(courses, sections, equivalents, db):
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript("""
        DROP TABLE IF EXISTS courses; DROP TABLE IF EXISTS sections; DROP TABLE IF EXISTS equivalents;
        CREATE TABLE courses (comp_code INT PRIMARY KEY, code TEXT, title TEXT, units INT);
        CREATE TABLE sections (comp_code INT, code TEXT, section TEXT, cancelled INT, slots TEXT,
                               midsem TEXT, compre TEXT, raw TEXT);
        CREATE TABLE equivalents (code TEXT, equivalent_code TEXT);""")
    con.executemany("INSERT INTO courses VALUES (?,?,?,?)", [(k, *v) for k, v in courses.items()])
    con.executemany("INSERT INTO sections VALUES (?,?,?,?,?,?,?,?)", [
        (s["comp_code"], s["code"], s["section"], s["cancelled"],
         " ".join(f"{d}{h}" for d, h in s["slots"]),
         " ".join(s.get("mid", ())), " ".join(s.get("compre", ())), s["raw"]) for s in sections])
    con.executemany("INSERT INTO equivalents VALUES (?,?)", equivalents)
    con.commit()


if __name__ == "__main__":
    course_lines, equiv_lines = read_lines(sys.argv[1])
    courses, sections, problems = parse(glue(course_lines))
    equivalents = parse_equivalents(equiv_lines)
    save(courses, sections, equivalents, sys.argv[2])
    print(f"{len(courses)} courses, {len(sections)} sections, {len(equivalents)} equivalence pairs")
    print(f"{len(problems)} rows could not be parsed:", *problems, sep="\n  ")
