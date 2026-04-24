import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from frontend.services.api import api
import json

st.set_page_config(page_title="Evaluation Report", page_icon="📊", layout="wide")

if not st.session_state.get("authenticated") or st.session_state.get("role") not in ["hr", "ceo"]:
    st.error("Access denied. Only HR and CEO can view this page.")
    st.switch_page("app.py")

job_id = st.session_state.get("eval_job_id")
candidate_id = st.session_state.get("eval_candidate_id")

if not job_id or not candidate_id:
    st.error("No assessment selected.")
    if st.button("Back"):
        st.switch_page("app.py")
    st.stop()

st.title("📊 AI Interview Evaluation Report")

try:
    report = api.get_evaluation_report(job_id, candidate_id)
    verdict = report.get("verdict", "Unknown")

    # Handle failed evaluation explicitly before showing any metrics
    if verdict == "Error":
        st.error("⚠️ Evaluation Failed")
        st.warning(report.get("summary", "The evaluation could not be completed due to a technical error."))
        st.info("**Possible causes:** The interview session was too short, or the AI evaluation service encountered an error. "
                "Ask the candidate to re-interview to generate a fresh report.")
    else:
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(label="Technical Score", value=f"{report.get('technical_score', 0)}/10")
        with col2:
            st.metric(label="Behavioral Score", value=f"{report.get('behavioral_score', 0)}/10")
        with col3:
            st.metric(label="Confidence Score", value=f"{report.get('confidence_score', 0)}/10")

        st.markdown("### 📝 Summary")
        st.info(report.get("summary", "No summary provided."))

        col_str, col_weak = st.columns(2)
        with col_str:
            st.markdown("### 💪 Strengths")
            for s in report.get("strengths", []):
                st.markdown(f"- {s}")

        with col_weak:
            st.markdown("### ⚠️ Areas for Improvement")
            for w in report.get("weaknesses", []):
                st.markdown(f"- {w}")

        st.markdown("---")
        if "Strong Hire" in verdict:
            st.success(f"### 🏆 Final Verdict: {verdict}")
        elif "No Hire" in verdict:
            st.error(f"### ❌ Final Verdict: {verdict}")
        else:
            st.warning(f"### ✅ Final Verdict: {verdict}")

except Exception as e:
    st.error(f"Could not load evaluation report: {str(e)}")
    st.info("The candidate may not have completed the interview yet.")

st.markdown("---")
if st.button("← Back to Applications"):
    st.switch_page("pages/hr_view_applications.py")
