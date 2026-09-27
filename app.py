import json
from pathlib import Path
import streamlit as st
import engine, llm

PROFILE = Path("data/profile.json")
st.set_page_config(page_title="BITS Course Recommender", layout="wide")
con = engine.connect()


def load_profile():
    if not PROFILE.exists():
        return {}
    data = json.loads(PROFILE.read_text())
    data.setdefault("others", data.get("completed", []))          # profiles saved by the older version
    return data


@st.cache_data(ttl=600, show_spinner="Checking Gemini...")
def gemini_status():
    return llm.status()


def pick(label, options, saved, **kw):
    return st.multiselect(label, options, [c for c in saved if c in options], **kw)


profile = load_profile()
all_codes = sorted({r[0] for r in con.execute("SELECT code FROM courses UNION SELECT code FROM programme_courses")})
running = sorted({r[0] for r in con.execute("SELECT c.code FROM courses c JOIN sections s ON s.comp_code = c.comp_code "
                                             "WHERE s.cancelled = 0")})
huel_pool = engine.codes(con, "SELECT code FROM programme_courses WHERE category = 'huel'")

with st.sidebar:
    st.header("Student profile")
    campus = st.selectbox("Campus", ["Pilani"], help="Only the Pilani timetable is in the dataset")
    admission = st.number_input("Admission year", 2018, 2026, profile.get("admission_year", 2024))
    computed = engine.study_year({"admission_year": admission})
    saved_year = profile.get("year") if profile.get("admission_year") == admission else None
    year = st.number_input("Year of study (Sem I 2026-27)", 1, 5, min(5, saved_year or computed),
                           key=f"year_{admission}", help=f"Worked out from your admission year: {computed}. "
                                                         "Change it if you are behind or ahead.")
    progs = pick("Degree (pick two for a dual degree)", engine.programmes(con), profile.get("programmes", []),
                 max_selections=2)

    assumed = engine.assumed_done(con, progs, year)
    if assumed:
        st.caption(f"Assumed cleared: {len(assumed)} CDCs normally taken before year {year}.")
    backlogs = pick("Backlogs / repeating (CDCs NOT yet cleared)", assumed, profile.get("backlogs", []))
    elective_options = sorted(set().union(*[engine.programme_info(con, p)["del"] for p in progs], huel_pool))
    electives = pick("DELs / HUELs completed", elective_options, profile.get("electives", []))
    others = pick("Other courses completed (open electives, CDCs taken early)", all_codes, profile.get("others", []))
    current = pick("Current courses (this semester)", running, profile.get("current", []))
    minor = st.text_input("Minor (if any)", profile.get("minor", ""))
    interests = st.text_area("Academic interests", profile.get("interests", ""))

    profile = {"campus": campus, "admission_year": int(admission), "year": int(year), "programmes": progs,
               "backlogs": backlogs, "electives": electives, "others": others, "current": current,
               "minor": minor, "interests": interests}
    if st.button("Save profile"):
        PROFILE.parent.mkdir(parents=True, exist_ok=True)
        PROFILE.write_text(json.dumps(profile, indent=2))
        st.success("Saved")

st.title("BITS Academic Course Recommender")
online, message = gemini_status()
(st.success if online else st.warning)(message)
if not profile["programmes"]:
    st.info("Choose your degree in the sidebar to begin.")
    st.stop()

completed = sorted((set(assumed) - set(backlogs)) | set(electives) | set(others))
student = {"programmes": progs, "admission_year": profile["admission_year"], "year": profile["year"],
           "completed": completed, "current": current, "interests": interests}
need = engine.remaining(con, student)

st.subheader("Remaining requirements")
cols = st.columns(len(need["programmes"]) + 1)
for col, p in zip(cols, need["programmes"]):
    col.metric(f"{p['programme'].title()}: CDCs left", len(p["cdc_left"]))
    col.metric("DEL units left", "not verified" if p["del_left"] is None else p["del_left"])
    with col.expander("CDCs still to do"):
        st.write(", ".join(p["cdc_left"]) or "None")
cols[-1].metric("HUEL units left", need["huel_left"])
for note in need["notes"]:
    (st.warning if note.startswith("2026") else st.caption)(note)

st.subheader("Ask me anything about your course choices")
st.caption('e.g. "Suggest DELs related to AI", "I want an OPEL with no attendance requirement", "Can I take CS F303?"')
if "chat" not in st.session_state:
    st.session_state.chat = []
if st.session_state.chat and st.button("Clear chat"):
    st.session_state.chat = []


def show_tools(log):
    if log:
        with st.expander("How this was decided"):
            for name, args, result in log:
                st.markdown(f"`{name}({', '.join(f'{k}={v}' for k, v in args.items())})` → {result}")


for msg in st.session_state.chat:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])
        show_tools(msg.get("log"))

if question := st.chat_input("What are you looking for this semester?"):
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"), st.spinner("Thinking..."):
        reply, log = None, []
        if online:
            try:
                reply, log = llm.chat(con, student, st.session_state.chat, question)
            except Exception as e:
                st.warning(f"Gemini call failed ({e}); answering in offline mode.")
        if reply is None:
            reply, log = llm.offline_reply(con, student, question)
        st.markdown(reply)
        show_tools(log)
    st.session_state.chat += [{"role": "user", "text": question}, {"role": "assistant", "text": reply, "log": log}]
