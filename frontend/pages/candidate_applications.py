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
        # Batch-fetch all jobs to avoid N+1 calls
        all_jobs_resp = requests.get(
            f"{api.base_url}/jobs",
            headers=api._get_headers()
        )
        jobs_map = {}
        if all_jobs_resp.status_code == 200:
            for j in all_jobs_resp.json():
                jobs_map[j["id"]] = j

        st.markdown(f"**Total Applications:** {len(applications)}")

        for i, app in enumerate(applications, 1):
            job = jobs_map.get(app["job_posting_id"])
            job_title = job["title"] if job else f"Job #{app['job_posting_id']}"
            status = app["status"]

            status_color = {
                "pending":    "🟡",
                "interviewed":"🔵",
                "hired":      "🟢",
                "rejected":   "🔴",
            }.get(status, "⚪")

            with st.expander(f"{status_color} {job_title} — Status: **{status.upper()}**"):
                if job:
                    st.markdown("### Job Details")
                    st.markdown(f"**Description:** {job.get('description', 'Not specified')}")
                    st.markdown(f"**Experience Required:** {job.get('experience_required', 0)} years")
                    st.markdown(f"**Skills Required:** {job.get('skills_required', 'Not specified')}")

                st.markdown("---")
                st.markdown("### Your Application")
                st.markdown(f"**Years of Experience:** {app['years_of_experience']}")
                st.markdown(f"**Your Skills:** {app['skills']}")
                st.markdown(f"**University:** {app.get('university', 'Not specified')}")

                if app.get("additional_info"):
                    st.markdown("**Additional Info:**")
                    st.write(app["additional_info"])

                st.markdown("---")

                # Interview guard: only allow if status is still "pending"
                if status == "pending":
                    if st.button(f"🎙️ Start Interview", key=f"interview_{app['id']}"):
                        st.session_state.selected_job_id = app["job_posting_id"]
                        st.switch_page("pages/candidate_interview.py")
                elif status == "interviewed":
                    st.info("✅ You have already completed the interview for this position.")
                elif status == "hired":
                    st.success("🎉 Congratulations! You have been hired for this position.")
                elif status == "rejected":
                    st.error("❌ Your application was not successful for this position.")
                else:
                    st.info(f"Application status: {status}")

except Exception as e:
    st.error(f"Error fetching applications: {str(e)}")

st.markdown("---")
if st.button("← Back to Dashboard"):
    st.switch_page("app.py")
