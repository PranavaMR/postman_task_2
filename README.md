# BITS Academic Course Recommender (Postman Round 2)

A dashboard where a BITS Pilani student saves their academic profile and asks questions like
*"Suggest DELs related to AI"* or *"I want an OPEL with no attendance requirement"*.
The system first works out what the student is **required and eligible** to take, using fixed rules
over data extracted from the supplied documents, and only then matches their preferences.

```mermaid
flowchart LR
    A[Timetable PDF] -->|timetable.py| DB[(academic.db)]
    B[540 handout PDFs] -->|handouts.py| DB
    C[Bulletin PDF] -->|bulletin.py| DB
    P[Profile + question] --> E[engine.py<br/>remaining + eligible]
    DB --> E
    E --> R[recommend.py<br/>preferences + policy checks]
    L1[llm.py<br/>question → preferences] --> R
    R --> L2[llm.py<br/>facts → answer]
    L2 --> UI[app.py<br/>Streamlit]
```

## Run it

```
python -m venv .venv
.venv\Scripts\activate                 (Windows)   |   source .venv/bin/activate   (Mac/Linux)
pip install -r requirements.txt
```
Put the dataset in `data/raw/`: `timetable.pdf`, `bulletin.pdf`, and the handouts in `data/raw/handouts/`.
Optionally copy `.env.example` to `.env` and add a Gemini API key; without one the app uses a keyword parser
and a template answer instead of the LLM.

```
python timetable.py data/raw/timetable.pdf data/processed/academic.db
python handouts.py  data/raw/handouts      data/processed/academic.db
python bulletin.py  data/raw/bulletin.pdf  data/processed/academic.db
python -m pytest -q
streamlit run app.py
```
Each preprocessing script replaces only its own tables, so they can be re-run independently; a new
semester's timetable or handouts only needs the relevant script re-run.

## Files

| File | Role |
|---|---|
| `timetable.py` | Timetable → `courses`, `sections` (slots, cancelled flag, midsem/compre per section), `equivalents` |
| `handouts.py` | Handouts → `handouts` (midsem, components, makeup, attendance, topics, source quotes) + `handouts_review.csv` |
| `bulletin.py` | Bulletin → `programme_courses` (core / DEL / humanities pool) and `programme_targets` (unit targets) |
| `engine.py` | Deterministic rules: remaining requirements and eligible courses with their category (CDC/DEL/HUEL/OPEL) |
| `recommend.py` | Filters eligible courses by preferences using handout facts, adds policy notes, ranks |
| `llm.py` | Gemini: question → preference JSON, and facts → answer. Keyword/template fallback |
| `app.py` | Streamlit dashboard: profile, remaining requirements, chat |

## Design decisions

- **Rules first, LLM last.** Eligibility is decided only by `engine.py`. The LLM never sees the raw PDFs and
  never decides eligibility; it only parses the question and phrases the answer from facts it is given.
- **Rule-based extraction, no LLM in preprocessing.** All three documents are parsed with regular expressions
  into SQLite. Anything the rules cannot decide is stored as `unknown`/`NULL` and shown as *not verified*
  rather than guessed.
- **Source kept.** Handout rows keep the original makeup/attendance sentences and file name; Bulletin rows keep
  the page number; timetable rows keep the raw text.
- **Self-checks.** Handout evaluation weights must sum to 100; Bulletin core lists are compared with the
  Bulletin's own "Discipline Core – N Units (M Courses)" lines.

## Rules implemented

| Rule | Source |
|---|---|
| Remaining CDCs = programme core − completed (equivalent courses count as completed) | Bulletin lists; timetable §IX |
| DEL units remaining against the programme's target | Bulletin semester charts |
| 8 units of humanities electives; own-discipline courses can't count as HUEL | Bulletin IV-1, IV-127 |
| Extra DEL/HUEL beyond the requirement count as open electives | Reg 2.05 |
| Dual degree: core of both programmes; humanities once | Bulletin IV-1, Reg 2.05 |
| Project courses (XXX F266/366/367/376/377/491) count as DEL; ≤3 towards DEL, ≤5 overall (noted) | Bulletin IV-125 |
| Higher-degree course: max one per semester (noted) | Reg 2.08 |
| Max 25 units per semester (noted) | Reg 1.01 |
| Courses with comp code ≥ 5000 only for 2026 admits | Timetable note |
| First-year courses not offered to senior students | Reg 3.18 |
| Cancelled sections, Practice School and theses are not recommended | Timetable |

## Data coverage (on the supplied dataset)

| | |
|---|---|
| Timetable | 718 courses, 1680 sections, 238 equivalence pairs |
| Handouts: midsem yes/no known | 479 / 540 (88%) |
| Handouts: makeup policy known | 449 / 540 (83%) |
| Handouts: evaluation weights sum to 100 | 272 / 540 (50%); the rest are stored but unverified |
| Handouts: attendance rule known | 154 / 540 (28%); most handouts don't state one |
| Bulletin | 28 programmes, 136 humanities-pool courses, unit targets found for 23 |

## Known limitations

- **Prerequisites are not checked.** They are in the Bulletin's course descriptions but were not parsed.
- **First-year institute requirements** come from the semester charts, which were not parsed; the engine is
  aimed at students past first year.
- **2026 admits:** the supplied Bulletin (2025-26) has no new-curriculum ("U") courses, so their requirements
  cannot be computed; they only see new-curriculum courses as eligible.
- **Bulletin mismatches to verify:** core-course counts differ from the summary line for EEE, Pharmacy,
  Environmental and Semiconductor; five programmes (incl. BBA, the two General Studies streams, Robotics,
  Architecture) have no DEL-unit target found. The BBA programme name is not in the PDF text.
- **Four lecture sections** (CS F303, CS F363, CHE F415, CHE G553) lost their day/hour slots because the PDF
  lays those cells out of reading order.
- Minors are stored in the profile but not used; timetable clash checking (the optional brownie point) is not
  implemented.

## How this was built

This project was built with the assistance of Sonnet 5, which I used to make
1. handouts.py
2. bulletin.py
3. timetable.py
4. app.py
5. llm.py ( coded by hand but syntaxically guided )
6. tests folder ( except test_engine.py )
where i gave the exact edge cases needed and the logic behind it ( as it was tedious to make it parse bulletin due to rate limits ).
Claude proposed the architecture, with which I ran the entire dataset over the pipelines- ignored some files due to the time constraint of the tasks. With the main limitation being, the lack of incorporation of first year course related queries. 
This was because the bulletin, and handout+timetable data were of different years.
I am still learning the regex-based parsing code in detail as it was coded 100% by AI. 
