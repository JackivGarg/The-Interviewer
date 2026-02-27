import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from frontend.services.api import api
import requests

st.set_page_config(page_title="My Applications", page_icon="💼", layout="centered")

if not st.session_state.get("authenticated") or st.session_state.get("role") != "candidate":
    st.error("Please login as Candidate to access this page.")
    st.switch_page("app.py")

st.title("📋 My Applications")

try:
    applications = api.get_candidate_applications()
    
    if not applications:
        st.info("You haven't applied to any jobs yet.")
        if st.button("View Available Jobs"):
            st.switch_page("app.py")
    else:
        st.markdown(f"**Total Applications:** {len(applications)}")
        
        for i, app in enumerate(applications, 1):
            job_response = requests.get(
                f"{api.base_url}/jobs/{app['job_posting_id']}",
                headers=api._get_headers()
            )
            
            if job_response.status_code == 200:
                job = job_response.json()
                
                with st.expander(f"📋 {job['title']} (Status: {app['status']})"):
                    st.markdown("### Job Details")
                    st.markdown(f"**Description:** {job['description']}")
                    st.markdown(f"**Experience Required:** {job['experience_required']} years")
                    st.markdown(f"**Skills Required:** {job['skills_required']}")
                    
                    st.markdown("---")
                    st.markdown("### Your Application")
                    st.markdown(f"**Years of Experience:** {app['years_of_experience']}")
                    st.markdown(f"**Your Skills:** {app['skills']}")
                    st.markdown(f"**University:** {app.get('university', 'Not specified')}")
                    
                    if app.get('additional_info'):
                        st.markdown("**Additional Info:**")
                        st.write(app['additional_info'])

except Exception as e:
    st.error(f"Error fetching applications: {str(e)}")

st.markdown("---")
if st.button("← Back to Dashboard"):
    st.switch_page("app.py")
