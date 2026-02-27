import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from frontend.services.api import api

st.set_page_config(page_title="HR - My Job Postings", page_icon="💼", layout="centered")

if not st.session_state.get("authenticated") or st.session_state.get("role") != "hr":
    st.error("Please login as HR to access this page.")
    st.switch_page("app.py")

st.title("📋 My Job Postings")

try:
    jobs = api.get_hr_jobs()
    
    if not jobs:
        st.info("You haven't created any job postings yet.")
        if st.button("Create New Job Posting"):
            st.switch_page("pages/hr_create_job.py")
    else:
        st.markdown(f"**Total Jobs Posted:** {len(jobs)}")
        
        for job in jobs:
            with st.expander(f"📋 {job['title']} (ID: {job['id']})"):
                st.markdown(f"**Description:** {job['description']}")
                st.markdown(f"**Experience Required:** {job['experience_required']} years")
                st.markdown(f"**Skills Required:** {job['skills_required']}")
                
                if job.get('additional_requirements'):
                    st.markdown("**Additional Requirements:**")
                    st.write(job['additional_requirements'])
                
                if job.get('questions_to_ask'):
                    st.markdown("**Questions to Ask:**")
                    st.write(job['questions_to_ask'])
                
                if job.get('more_info'):
                    st.markdown("**More Info:**")
                    st.write(job['more_info'])
                
                st.markdown("---")
                if st.button(f"View Applications", key=f"view_apps_{job['id']}"):
                    st.session_state.view_job_id = job['id']
                    st.switch_page("pages/hr_view_applications.py")

except Exception as e:
    st.error(f"Error fetching jobs: {str(e)}")

st.markdown("---")
if st.button("← Back to Dashboard"):
    st.switch_page("app.py")

if st.button("Create New Job Posting"):
    st.switch_page("pages/hr_create_job.py")
