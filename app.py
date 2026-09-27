import json
from pathlib import Path
import streamlit as st
import engine, llm, recommend

PROFILE = Path("data/profile.json")
st.set_page_config(page_title="BITS Course Recommender", layout="wide")
con = engine.connect()


def load_profile():
    if PROFILE.exists():
        return json.loads(PROFILE.read_text())
    return {"campus": "Pilani", "admission_year": 2024, "programmes": [], "completed": [],
            "current": [], "minor": "", "interests": ""}


all_codes = sorted({r[0] for r in con.execute("SELECT code FROM courses UNION SELECT code FROM programme_courses")})
profile = load_profile()

with st.sidebar.form("profile"):
    st.header("Student profile")
    campus = st.selectbox("Campus", ["Pilani"], help="Only the Pilani timetable is in the dataset")
    year = st.number_input("Admission year", 2018, 2026, profile["admission_year"])
    progs = st.multiselect("Degree (pick two for a dual degree)", engine.programmes(con),
                           [p for p in profile["programmes"] if p in engine.programmes(con)], max_selections=2)
    completed = st.multiselect("Completed courses", all_codes, [c for c in profile["completed"] if c in all_codes])
    current = st.multiselect("Current courses", all_codes, [c for c in profile["current"] if c in all_codes])
    minor = st.text_input("Minor (if any)", profile["minor"])
    interests = st.text_area("Academic interests", profile["interests"])
    if st.form_submit_button("Save profile"):
        profile = {"campus": campus, "admission_year": int(year), "programmes": progs, "completed": completed,
                   "current": current, "minor": minor, "interests": interests}
        PROFILE.parent.mkdir(parents=True, exist_ok=True)
        PROFILE.write_text(json.dumps(profile, indent=2))
        st.success("Saved")

st.title("BITS Academic Course Recommender")
if not profile["programmes"]:
    st.info("Fill in and save your profile in the sidebar to begin.")
    st.stop()

student = {k: profile[k] for k in ("programmes", "admission_year", "completed", "current")}
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
    st.caption(note)

st.subheader("Ask for recommendations")
st.caption('e.g. "Suggest DELs related to AI", "I want an OPEL with no attendance requirement"')
if "chat" not in st.session_state:
    st.session_state.chat = []
for msg in st.session_state.chat:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])

if question := st.chat_input("What are you looking for this semester?"):
    st.session_state.chat.append({"role": "user", "text": question})
    with st.chat_message("user"):
        st.markdown(question)
    prefs = llm.parse_query(question)
    if not prefs["topics"] and profile["interests"] and "interest" in question.lower():
        prefs["topics"] = llm.parse_query(profile["interests"])["topics"]
    picks = recommend.recommend(con, student, prefs)
    reply = llm.answer(question, need, picks)
    with st.chat_message("assistant"):
        st.markdown(reply)
        with st.expander("How this was decided"):
            st.json(prefs)
            st.dataframe([{"code": c["code"], "title": c["title"], "category": c["category"], "units": c["units"],
                           "matched": "; ".join(c["matched"]), "not verified": "; ".join(c["unverified"]),
                           "policy notes": "; ".join(c["notes"]), "handout": c["source"]} for c in picks])
    st.session_state.chat.append({"role": "assistant", "text": reply})
