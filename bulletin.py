
import re, sqlite3, sys
from pathlib import Path
import pdfplumber

LIST_PAGES = range(314, 336)        # "List of Courses" + humanities pool (Bulletin IV-106 to IV-127)
CHART_PAGES = range(209, 314)       # semester-wise charts, which end with the unit summary lines
COURSE = re.compile(r"^([A-Z]{2,5}) ([FG]\d{3}[A-Z]?)\s+(.*?)\s*(\d+)\*?$")    # "CS F211 Data Structures ... 3 1 4"
CODE_ONLY = re.compile(r"^([A-Z]{2,5}) ([FG]\d{3}[A-Z]?)\b(.*)$")             # title wraps; units on a later line
HEADING = re.compile(r"^[A-Z][A-Z &,.()\-–]+$")                                  # e.g. "COMPUTER SCIENCE"


def column_lines(pdf, pages):
    for pn in pages:
        page = pdf.pages[pn - 1]
        mid = page.width / 2
        for box in [(0, 0, mid, page.height), (mid, 0, page.width, page.height)]:
            for line in (page.crop(box).extract_text() or "").splitlines():
                yield pn, line.strip()


def parse_lists(pdf):
    rows, programme, category, track, heading = [], None, None, None, []
    for pn, line in column_lines(pdf, LIST_PAGES):
        if line.startswith("CORE COURSES"):
            programme, category, track = " ".join(heading) or None, "core", None
            heading = []
        elif line.startswith("DISCIPLINE ELECTIVE COURSES"):
            category, track = "del", None
        elif line.startswith("Pool of Humanities"):
            programme, category, track = "ALL", "huel", None
        elif line.startswith(("Project Type Courses", "Other Courses")):
            category = None                                 # project courses are handled by a rule instead
        elif re.match(r"^(Track|Pool)\s*[-–]?\s*\S", line) and category == "del":
            track = line
        elif (m := COURSE.match(line) or CODE_ONLY.match(line)) and category:
            programme = programme or f"{m[1]} (programme name not found in text)"   # e.g. BBA, p332
            units = int(m[4]) if m.re is COURSE else None
            title = re.sub(r"(\s+[\d-]+){0,2}$", "", m[3]).strip(" */")            # drop the L and P columns
            rows.append((programme, category, f"{m[1]} {m[2]}", title, units, track, pn))
            heading = []
        elif COURSE.match(line) or CODE_ONLY.match(line):
            heading = []
        elif HEADING.match(line) and len(line) > 6 and "COURSES" not in line:
            heading.append(line)                            # programme names can span two or three lines
    return rows


def parse_targets(pdf):
    targets, name, page = [], None, None
    text = ""
    for pn in CHART_PAGES:
        text += f"\n@@PAGE {pn}\n" + (pdf.pages[pn - 1].extract_text() or "")
    for pn_text in text.split("@@PAGE ")[1:]:
        pn, body = pn_text.split("\n", 1)
        for m in re.finditer(r"Admitted to (.+?) Programme"
                             r"|Discipline Core\s*[-–]?\s*(\d+)(?:\s*or\s*\d+)?\s*Units\s*\((\d+)"
                             r"|Discipline Electives?\s*[-–]?\s*(\d+)\s*Units\s*(?:\(min\)\s*-?\s*)?\(?(\d+)", body):
            if m[1]:
                name, page = " ".join(m[1].split()), int(pn)
            elif m[2] and name:
                targets.append([name, int(m[2]), int(m[3]), None, None, page])
            elif m[4] and targets and targets[-1][0] == name:
                targets[-1][3:5] = int(m[4]), int(m[5])
    return [tuple(t) for t in targets]


def tokens(name):
    words = re.findall(r"[a-z]+", name.lower().replace("&", " and "))
    return [w for w in words if w not in {"b", "e", "m", "sc"}]          # drop degree letters "B.E.", "M.Sc."


def match_targets(rows, targets):
    """Chart names ('B. E. Computer Science') -> list names ('COMPUTER SCIENCE'): every chart word
    must start a word of the list name; the chart name matching the most words wins."""
    out = []
    for prog in sorted({r[0] for r in rows if r[0] != "ALL"}):
        words = tokens(prog)
        best = max(targets, default=None, key=lambda t: len(tokens(t[0])) if all(
            any(w.startswith(tw) for w in words) for tw in tokens(t[0])) else -1)
        if best and all(any(w.startswith(tw) for w in words) for tw in tokens(best[0])):
            out.append((prog, *best[1:]))
        else:
            out.append((prog, None, None, None, None, None))
    return out


def save(rows, targets, db):
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript("""
        DROP TABLE IF EXISTS programme_courses; DROP TABLE IF EXISTS programme_targets;
        CREATE TABLE programme_courses (programme TEXT, category TEXT, code TEXT, title TEXT,
                                        units INT, track TEXT, page INT);
        CREATE TABLE programme_targets (programme TEXT, core_units INT, core_courses INT,
                                        del_units INT, del_courses INT, page INT);""")
    con.executemany("INSERT INTO programme_courses VALUES (?,?,?,?,?,?,?)", rows)
    con.executemany("INSERT INTO programme_targets VALUES (?,?,?,?,?,?)", targets)
    con.commit()


if __name__ == "__main__":
    with pdfplumber.open(sys.argv[1]) as pdf:
        rows = parse_lists(pdf)
        targets = match_targets(rows, parse_targets(pdf))
    save(rows, targets, sys.argv[2])
    programmes = sorted({r[0] for r in rows if r[0] != "ALL"})
    print(f"{len(rows)} course rows for {len(programmes)} programmes, "
          f"{sum(r[1] == 'huel' for r in rows)} humanities courses, {sum(t[3] is not None for t in targets)} with elective-unit targets")
    for t in targets:
        core = sum(1 for r in rows if r[0] == t[0] and r[1] == "core")
        print(f"  {t[0][:55]:55} core courses listed={core:3} | target: core={t[2]} del_units={t[3]}")
