import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from frontend.services.api import api
import json

st.set_page_config(page_title="Create Job Posting", page_icon="💼", layout="centered")

if not st.session_state.get("authenticated") or st.session_state.get("role") != "hr":
    st.error("Please login as HR to access this page.")
    st.switch_page("app.py")

st.title("📋 Create New Job Posting")

with st.form("job_form"):
    st.markdown("### Job Details")
    
    title = st.text_input(
        "Job Title *",
        placeholder="e.g., Senior Python Developer"
    )
    
    description = st.text_area(
        "Job Description *",
        placeholder="Describe the role and responsibilities...",
        height=120
    )
    
    experience_required = st.number_input(
        "Years of Experience Required *",
        min_value=0,
        max_value=50,
        value=0,
        help="Enter the minimum years of experience required for this position"
    )
    
    skills_required = st.text_area(
        "Skills Required *",
        placeholder="Enter skills separated by commas (e.g., Python, FastAPI, SQL, JavaScript)",
        height=80,
        help="These skills will be compared with candidate skills during screening"
    )
    
    additional_requirements = st.text_area(
        "Additional Requirements",
        placeholder="Any other requirements or preferences...",
        height=80
    )
    
    questions_to_ask = st.text_area(
        "Questions to Ask Candidate",
        placeholder="Interview questions you want to ask the candidate...",
        height=80
    )
    
    more_info = st.text_area(
        "Additional Information",
        placeholder="Any other information you want to share (benefits, location, etc.)...",
        height=80
    )
    
    # ── Interview Topics with Per-Topic Thresholds ─────────────────────
    st.markdown("---")
    st.markdown("### 🎯 Interview Topics")
    st.caption(
        "Define the topics the AI interviewer should cover. "
        "Set a **threshold** for each topic (1 = lenient, 10 = very strict). "
        "If the candidate scores below the threshold, the AI will ask follow-up questions (max 3 per topic)."
    )

    num_topics = st.number_input(
        "Number of interview topics",
        min_value=1,
        max_value=10,
        value=4,
        help="How many topics should the AI interviewer cover?"
    )

    topics_list = []
    for i in range(int(num_topics)):
        col1, col2 = st.columns([3, 1])
        with col1:
            topic_name = st.text_input(
                f"Topic {i + 1}",
                placeholder=f"e.g., Python Fundamentals, System Design, Behavioral...",
                key=f"topic_{i}"
            )
        with col2:
            threshold = st.slider(
                f"Threshold",
                min_value=1,
                max_value=10,
                value=6,
                key=f"thresh_{i}",
                help="Score needed to pass (6 = standard, 7-8 = strict)"
            )
        if topic_name and topic_name.strip():
            topics_list.append({"topic": topic_name.strip(), "threshold": threshold})

    st.markdown("---")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        submitted = st.form_submit_button("Submit Job Posting", type="primary")
    
    with col2:
        cancel = st.form_submit_button("Cancel")

if submitted:
    if not title or not description or not skills_required:
        st.error("Please fill in all required fields (Title, Description, Skills Required)")
    elif not topics_list:
        st.error("Please define at least one interview topic.")
    else:
        job_data = {
            "title": title,
            "description": description,
            "experience_required": experience_required,
            "skills_required": skills_required,
            "additional_requirements": additional_requirements if additional_requirements else None,
            "questions_to_ask": questions_to_ask if questions_to_ask else None,
            "more_info": more_info if more_info else None,
            "interview_topics": topics_list,
        }
        
        try:
            result = api.create_job(job_data)
            st.success(f"✅ Job posting created successfully! (ID: {result['id']})")
            st.info(f"📋 {len(topics_list)} interview topics configured.")
            st.switch_page("app.py")
        except Exception as e:
            st.error(f"Failed to create job: {str(e)}")

if cancel:
    st.switch_page("app.py")

st.markdown("---")
if st.button("← Back to Dashboard"):
    st.switch_page("app.py")
