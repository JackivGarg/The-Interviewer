import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from frontend.services.api import api

st.set_page_config(page_title="Apply to Job", page_icon="💼", layout="centered")

if not st.session_state.get("authenticated") or st.session_state.get("role") != "candidate":
    st.error("Please login as Candidate to access this page.")
    st.switch_page("app.py")

job_id = st.session_state.get("selected_job_id")

if not job_id:
    st.error("No job selected. Please select a job from the dashboard.")
    if st.button("Go to Dashboard"):
        st.switch_page("app.py")
    st.stop()

st.title("📝 Job Application")

try:
    job = api.get_job(job_id)
except Exception as e:
    st.error(f"Error fetching job: {str(e)}")
    if st.button("Go to Dashboard"):
        st.switch_page("app.py")
    st.stop()

st.markdown("### Position Details")
st.markdown(f"**Title:** {job['title']}")
st.markdown(f"**Description:** {job['description']}")
st.markdown(f"**Experience Required:** {job['experience_required']} years")
st.markdown(f"**Skills Required:** {job['skills_required']}")

if job.get('additional_requirements'):
    st.markdown("### Additional Requirements")
    st.write(job['additional_requirements'])

if job.get('questions_to_ask'):
    st.markdown("### Questions to Ask")
    st.write(job['questions_to_ask'])

if job.get('more_info'):
    st.markdown("### More Information")
    st.write(job['more_info'])

st.markdown("---")
st.markdown("### Your Application")

with st.form("application_form"):
    years_of_experience = st.number_input(
        "Years of Experience *",
        min_value=0,
        max_value=50,
        value=0,
        help="Your total years of professional experience"
    )
    
    skills = st.text_area(
        "Your Skills *",
        placeholder="Enter your skills separated by commas (e.g., Python, FastAPI, SQL, JavaScript)",
        height=100,
        help="List all your relevant skills"
    )
    
    university = st.text_input(
        "University/College",
        placeholder="e.g., MIT, Stanford University"
    )
    
    additional_info = st.text_area(
        "Additional Information",
        placeholder="Any additional information you'd like to share...",
        height=100
    )
    
    st.markdown("---")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        submitted = st.form_submit_button("Submit Application", type="primary")
    
    with col2:
        cancel = st.form_submit_button("Cancel")

if submitted:
    if not skills:
        st.error("Please enter your skills")
    else:
        application_data = {
            "job_posting_id": job_id,
            "years_of_experience": years_of_experience,
            "skills": skills,
            "university": university if university else None,
            "additional_info": additional_info if additional_info else None
        }
        
        try:
            result = api.apply_to_job(application_data)
            st.success("✅ Application submitted successfully!")
            st.info("You can view your applications from the dashboard.")
            if st.button("Go to Dashboard"):
                st.switch_page("app.py")
        except Exception as e:
            st.error(f"Failed to submit application: {str(e)}")

if cancel:
    st.switch_page("app.py")

st.markdown("---")
if st.button("← Back to Dashboard"):
    st.switch_page("app.py")
