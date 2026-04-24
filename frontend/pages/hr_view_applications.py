import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from frontend.services.api import api
import requests

st.set_page_config(page_title="HR - View Applications", page_icon="💼", layout="centered")

if not st.session_state.get("authenticated") or st.session_state.get("role") != "hr":
    st.error("Please login as HR to access this page.")
    st.switch_page("app.py")

job_id = st.session_state.get("view_job_id")

if not job_id:
    st.error("No job selected.")
    if st.button("Go to My Jobs"):
        st.switch_page("pages/hr_view_jobs.py")
    st.stop()

st.title("📋 Applications for Job")

try:
    job = api.get_job(job_id)
    st.markdown(f"**Job Title:** {job['title']}")
    st.markdown("---")

    response = requests.get(
        f"{api.base_url}/hr/jobs/{job_id}/applications",
        headers=api._get_headers()
    )

    if response.status_code == 200:
        applications = response.json()

        if not applications:
            st.info("No applications received yet.")
        else:
            st.markdown(f"**Total Applications:** {len(applications)}")

            for i, app in enumerate(applications, 1):
                candidate_name = app.get("candidate_name", f"Candidate #{app['candidate_id']}")
                status = app["status"]

                # Status badge colours
                status_color = {
                    "pending":    "🟡",
                    "interviewed":"🔵",
                    "hired":      "🟢",
                    "rejected":   "🔴",
                }.get(status, "⚪")

                with st.expander(f"{status_color} {candidate_name} — Status: **{status.upper()}**"):
                    st.markdown(f"**Years of Experience:** {app['years_of_experience']}")
                    st.markdown(f"**Skills:** {app['skills']}")
                    st.markdown(f"**University:** {app.get('university', 'Not specified')}")
                    if app.get("additional_info"):
                        st.markdown("**Additional Info:**")
                        st.write(app["additional_info"])

                    st.markdown("---")

                    # Status action buttons (only show relevant transitions)
                    col_eval, col_hire, col_reject = st.columns([2, 1, 1])

                    with col_eval:
                        if st.button("📊 View AI Evaluation Report", key=f"eval_{app['id']}"):
                            st.session_state["eval_job_id"] = job_id
                            st.session_state["eval_candidate_id"] = app["candidate_id"]
                            st.switch_page("pages/evaluation_report.py")

                    with col_hire:
                        if status not in ["hired"] and st.button("✅ Hire", key=f"hire_{app['id']}"):
                            patch_resp = requests.patch(
                                f"{api.base_url}/hr/jobs/{job_id}/applications/{app['id']}/status",
                                json={"status": "hired"},
                                headers=api._get_headers()
                            )
                            if patch_resp.status_code == 200:
                                st.success("Marked as Hired!")
                                st.rerun()
                            else:
                                st.error("Failed to update status.")

                    with col_reject:
                        if status not in ["rejected"] and st.button("❌ Reject", key=f"reject_{app['id']}"):
                            patch_resp = requests.patch(
                                f"{api.base_url}/hr/jobs/{job_id}/applications/{app['id']}/status",
                                json={"status": "rejected"},
                                headers=api._get_headers()
                            )
                            if patch_resp.status_code == 200:
                                st.warning("Marked as Rejected.")
                                st.rerun()
                            else:
                                st.error("Failed to update status.")

    else:
        st.error(f"Error: {response.json().get('detail', 'Failed to fetch applications')}")

except Exception as e:
    st.error(f"Error: {str(e)}")

st.markdown("---")
if st.button("← Back to My Jobs"):
    st.switch_page("pages/hr_view_jobs.py")
