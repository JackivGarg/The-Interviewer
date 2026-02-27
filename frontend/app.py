import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from frontend.services.api import api, clear_token

st.set_page_config(page_title="The Interviewer", page_icon="💼", layout="centered")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "role" not in st.session_state:
    st.session_state.role = None
if "token" not in st.session_state:
    st.session_state.token = None


def logout():
    st.session_state.authenticated = False
    st.session_state.role = None
    st.session_state.token = None
    clear_token()
    st.rerun()


def login_page():
    st.title("💼 The Interviewer")
    st.markdown("### Login")
    
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    
    if st.button("Login"):
        try:
            result = api.login(email, password)
            st.session_state.authenticated = True
            st.session_state.role = result["role"]
            st.session_state.token = result["access_token"]
            st.rerun()
        except Exception as e:
            st.error(f"Login failed: {str(e)}")
    
    st.markdown("---")
    st.markdown("### New Candidate? Sign Up Here")
    
    with st.expander("Candidate Sign Up"):
        name = st.text_input("Full Name")
        new_email = st.text_input("Email", key="signup_email")
        new_password = st.text_input("Password", type="password", key="signup_password")
        phone = st.text_input("Phone (optional)")
        
        if st.button("Sign Up"):
            try:
                api.signup_candidate(name, new_email, new_password, phone)
                st.success("Sign up successful! Please login.")
            except Exception as e:
                st.error(f"Sign up failed: {str(e)}")


def hr_dashboard():
    st.title("💼 HR Dashboard")
    st.markdown(f"**Role:** HR")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        if st.button("Create New Job Posting"):
            st.switch_page("pages/hr_create_job.py")
    
    with col2:
        if st.button("View My Job Postings"):
            st.switch_page("pages/hr_view_jobs.py")
    
    st.markdown("---")
    st.markdown("### All Available Jobs (for reference)")
    
    try:
        jobs = api.get_all_jobs()
        if jobs:
            for job in jobs:
                with st.expander(f"📋 {job['title']}"):
                    st.write(f"**Description:** {job['description']}")
                    st.write(f"**Experience Required:** {job['experience_required']} years")
        else:
            st.info("No jobs available yet.")
    except Exception as e:
        st.error(f"Error fetching jobs: {str(e)}")
    
    st.markdown("---")
    if st.button("Logout"):
        logout()


def candidate_dashboard():
    st.title("💼 Candidate Dashboard")
    st.markdown(f"**Role:** Candidate")
    
    st.markdown("### Available Job Postings")
    
    try:
        jobs = api.get_all_jobs()
        if jobs:
            for job in jobs:
                with st.expander(f"📋 {job['title']}"):
                    st.write(f"**Description:** {job['description']}")
                    st.write(f"**Experience Required:** {job['experience_required']} years")
                    if st.button(f"Apply Now", key=f"apply_{job['id']}"):
                        st.session_state.selected_job_id = job['id']
                        st.switch_page("pages/candidate_apply.py")
        else:
            st.info("No jobs available at the moment.")
    except Exception as e:
        st.error(f"Error fetching jobs: {str(e)}")
    
    st.markdown("---")
    if st.button("My Applications"):
        st.switch_page("pages/candidate_applications.py")
    
    if st.button("Logout"):
        logout()


def main():
    if not st.session_state.authenticated:
        login_page()
    else:
        if st.session_state.role == "hr":
            hr_dashboard()
        elif st.session_state.role == "candidate":
            candidate_dashboard()
        elif st.session_state.role == "ceo":
            st.title("CEO Dashboard")
            st.write("Welcome, CEO!")
            st.info("CEO features coming soon...")
            if st.button("Logout"):
                logout()
        else:
            st.error("Unknown role")
            logout()


if __name__ == "__main__":
    main()
