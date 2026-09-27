
# student dictionary input
#    {"programmes": ["COMPUTER SCIENCE"], "admission_year": 2024,
#     "completed": ["CS F111", "CS F213"], "current": ["CS F211"]}

import sqlite3
from collections import Counter

DB = "data/processed/academic.db"
HUEL_UNITS = 8                                           # Bulletin IV-1: 8 units of humanities electives
MAX_UNITS = 25                                           # Reg 1.01
NEW_CURRICULUM_COMP_CODE = 5000                          # timetable note: comp code >= 5000 is for 2026 admits
PROJECT_NUMBERS = {"266", "366", "367", "376", "377", "491"}
NOT_REGISTRABLE = {"BITS F412", "BITS F413"}             # Practice School is allotted, not chosen
SEMESTER_YEAR = 2026                                     # First Semester 2026-27


def connect(db=DB):
    return sqlite3.connect(db)


def codes(con, sql, params=()):
    return {r[0] for r in con.execute(sql, params)}


def programmes(con):
    return sorted(codes(con, "SELECT programme FROM programme_courses WHERE programme != 'ALL'"))


def equivalents(con):
    eq = {}
    for a, b in con.execute("SELECT code, equivalent_code FROM equivalents"):
        eq.setdefault(a, set()).add(b)
        eq.setdefault(b, set()).add(a)
    return eq


def done_set(con, taken):
    eq = equivalents(con)
    done = set(taken)
    for code in taken:
        done |= eq.get(code, set())
    return done


def programme_info(con, programme):
    core = codes(con, "SELECT code FROM programme_courses WHERE programme = ? AND category = 'core'", (programme,))
    dels = codes(con, "SELECT code FROM programme_courses WHERE programme = ? AND category = 'del'", (programme,))
    row = con.execute("SELECT del_units FROM programme_targets WHERE programme = ?", (programme,)).fetchone()
    dept = Counter(c.split()[0] for c in core).most_common(1)[0][0] if core else None
    return {"name": programme, "core": core, "del": dels, "del_units": row[0] if row else None, "dept": dept}


def is_project(code, dept):
    d, num = code.split()
    return d == dept and num[1:] in PROJECT_NUMBERS


def unit_lookup(con):
    units = {code: u for code, u in con.execute("SELECT code, units FROM programme_courses WHERE units IS NOT NULL")}
    for code, u in con.execute("SELECT code, units FROM courses WHERE comp_code < ?", (NEW_CURRICULUM_COMP_CODE,)):
        units.setdefault(code, u)
    return units


def category(code, progs, huel):
    if any(code in p["core"] for p in progs):
        return "CDC"
    if any(code in p["del"] or is_project(code, p["dept"]) for p in progs):
        return "DEL"
    if code in huel and not any(code.split()[0] == p["dept"] for p in progs):
        return "HUEL"                                    # own discipline courses can't be HUEL (Bulletin IV-127)
    return "OPEL"


def remaining(con, student):
    done = done_set(con, student["completed"] + student.get("current", []))
    units = unit_lookup(con)
    huel = codes(con, "SELECT code FROM programme_courses WHERE category = 'huel'")
    result = {"programmes": [], "huel_left": None, "notes": []}

    for name in student["programmes"]:
        p = programme_info(con, name)
        del_done = sum(units.get(c, 3) for c in done if c in p["del"] or is_project(c, p["dept"]))
        result["programmes"].append({
            "programme": name,
            "cdc_left": sorted(p["core"] - done),
            "del_target": p["del_units"],
            "del_done": del_done,
            "del_left": None if p["del_units"] is None else max(0, p["del_units"] - del_done),
        })
        if p["del_units"] is None:
            result["notes"].append(f"{name}: discipline-elective unit target not found in the Bulletin (not verified)")

    huel_done = sum(units.get(c, 3) for c in done if c in huel)
    result["huel_left"] = max(0, HUEL_UNITS - huel_done)
    if len(student["programmes"]) == 2:
        result["notes"].append("Dual degree: DELs of one degree may count as open electives of the other (Reg 2.05)")
    return result


def eligible(con, student):
    done = done_set(con, student["completed"] + student.get("current", []))
    progs = [programme_info(con, p) for p in student["programmes"]]
    huel = codes(con, "SELECT code FROM programme_courses WHERE category = 'huel'")
    need = remaining(con, student)
    del_left = sum(p["del_left"] or 0 for p in need["programmes"])
    new_admit = student["admission_year"] >= 2026

    running = con.execute("""SELECT DISTINCT c.comp_code, c.code, c.title, c.units FROM courses c
                             JOIN sections s ON s.comp_code = c.comp_code WHERE s.cancelled = 0""").fetchall()
    out, seen = [], set()
    for comp, code, title, units in sorted(running):
        if code in seen or code in done or code in NOT_REGISTRABLE or code.endswith("T"):
            continue
        if (comp >= NEW_CURRICULUM_COMP_CODE) != new_admit:
            continue
        seen.add(code)
        if code.split()[1][1] == "1" and SEMESTER_YEAR - student["admission_year"] >= 1:
            continue                                     # first-year course for a senior student (Reg 3.18)
        cat = category(code, progs, huel)
        notes = []
        if cat == "DEL" and del_left == 0:
            cat, notes = "OPEL", ["DEL requirement already met, counts as open elective (Reg 2.05)"]
        if cat == "HUEL" and need["huel_left"] == 0:
            cat, notes = "OPEL", ["HUEL requirement already met, counts as open elective (Reg 2.05)"]
        if code.split()[1].startswith("G"):
            notes.append("Higher-degree course: max one per semester, needs CDC of that discipline (Reg 2.08)")
        if any(is_project(code, p["dept"]) for p in progs) or code.split()[1][1:] in PROJECT_NUMBERS:
            notes.append("Project course: at most 3 count towards DEL, 5 overall (Bulletin IV-125)")
        out.append({"comp_code": comp, "code": code, "title": title, "units": units,
                    "category": cat, "notes": notes})
    return out


if __name__ == "__main__":
    con = connect()
    student = {"programmes": ["COMPUTER SCIENCE"], "admission_year": 2024,
               "completed": ["CS F111", "CS F213", "CS F214", "CS F215", "CS F222", "HSS F334"], "current": []}
    need = remaining(con, student)
    for p in need["programmes"]:
        print(p["programme"], "| CDCs left:", len(p["cdc_left"]), "| DEL left:", p["del_left"])
    print("HUEL left:", need["huel_left"])
    for note in need["notes"]:
        print(note)
    courses = eligible(con, student)
    print(len(courses), "eligible courses:", Counter(c["category"] for c in courses))
