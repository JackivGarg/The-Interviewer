import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from frontend.services.api import api, clear_token

st.set_page_config(page_title="The Interviewer", page_icon="💼", layout="centered")

st.markdown("""
<style>
    [data-testid="stSidebar"] {
        display: none;
    }
    .stButton > button {
        width: 100%;
        border-radius: 8px;
        padding: 10px;
    }
    .dashboard-card {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        padding: 20px;
        border-radius: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .header-gradient {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
</style>
""", unsafe_allow_html=True)

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
    st.session_state.selected_job_id = None
    st.session_state.view_job_id = None
    st.session_state.eval_job_id = None
    st.session_state.eval_candidate_id = None
    st.session_state.ceo_view = None
    clear_token()
    st.rerun()


def login_page():
    st.markdown("""
    <style>
    .login-container {
        max-width: 400px;
        margin: 0 auto;
        padding: 40px 30px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 20px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.2);
    }
    .login-title {
        text-align: center;
        color: white;
        font-size: 36px;
        font-weight: bold;
        margin-bottom: 10px;
    }
    .login-subtitle {
        text-align: center;
        color: rgba(255,255,255,0.9);
        font-size: 16px;
        margin-bottom: 30px;
    }
    .stTextInput > div > div > input {
        border-radius: 10px;
        padding: 12px;
    }
    .stButton > button {
        width: 100%;
        border-radius: 10px;
        padding: 12px;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)
    
    st.markdown('<div class="login-title">💼 The Interviewer</div>', unsafe_allow_html=True)
    st.markdown('<div class="login-subtitle">Smart Recruitment Platform</div>', unsafe_allow_html=True)
    
    st.markdown("###")
    
    with st.container():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("login_form"):
                email = st.text_input("Email", placeholder="Enter your email")
                password = st.text_input("Password", type="password", placeholder="Enter your password")
                
                submit = st.form_submit_button("Login", type="primary")
                
                if submit:
                    if not email or not password:
                        st.error("Please enter both email and password")
                    else:
                        try:
                            result = api.login(email, password)
                            st.session_state.authenticated = True
                            st.session_state.role = result["role"]
                            st.session_state.token = result["access_token"]
                            st.rerun()
                        except Exception as e:
                            st.error(f"Invalid credentials. Please try again.")
    
    st.markdown("---")
    
    with st.expander("New Candidate? Sign Up Here"):
        col1, col2 = st.columns([1, 1])
        with col1:
            name = st.text_input("Full Name", key="signup_name")
        with col2:
            new_email = st.text_input("Email", key="signup_email")
        new_password = st.text_input("Password", type="password", key="signup_password")
        phone = st.text_input("Phone (optional)", key="signup_phone")
        
        if st.button("Sign Up", key="signup_btn"):
            if not name or not new_email or not new_password:
                st.error("Please fill in all required fields")
            else:
                try:
                    api.signup_candidate(name, new_email, new_password, phone)
                    st.success("Sign up successful! Please login.")
                except Exception as e:
                    st.error(f"Sign up failed: {str(e)}")


def hr_dashboard():
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        st.markdown('<h2 class="header-gradient">💼 HR Dashboard</h2>', unsafe_allow_html=True)
    with col3:
        if st.button("🚪 Logout"):
            logout()
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("###")
        if st.button("📝 Create New Job Posting", use_container_width=True):
            st.switch_page("pages/hr_create_job.py")
    
    with col2:
        st.markdown("###")
        if st.button("📋 View My Job Postings", use_container_width=True):
            st.switch_page("pages/hr_view_jobs.py")
    
    st.markdown("---")
    st.markdown("### My Posted Jobs")
    
    try:
        jobs = api.get_hr_jobs()
        if jobs:
            for job in jobs:
                with st.expander(f"📋 {job['title']}"):
                    st.write(f"**Description:** {job['description']}")
                    st.write(f"**Experience Required:** {job['experience_required']} years")
        else:
            st.info("No jobs available yet.")
    except Exception as e:
        st.error(f"Error fetching jobs: {str(e)}")


def candidate_dashboard():
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        st.markdown('<h2 class="header-gradient">💼 Candidate Dashboard</h2>', unsafe_allow_html=True)
    with col3:
        if st.button("🚪 Logout"):
            logout()
    
    st.markdown("---")
    
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("📂 My Applications", use_container_width=True):
            st.switch_page("pages/candidate_applications.py")
    
    st.markdown("---")
    st.markdown("### Available Job Postings")
    
    try:
        jobs = api.get_all_jobs()
        if jobs:
            for job in jobs:
                with st.expander(f"📋 {job['title']}"):
                    st.write(f"**Description:** {job['description']}")
                    st.write(f"**Experience Required:** {job['experience_required']} years")
                    st.write(f"**Skills Required:** {job.get('skills_required', 'N/A')}")
                    if st.button(f"Apply Now", key=f"apply_{job['id']}"):
                        st.session_state.selected_job_id = job['id']
                        st.switch_page("pages/candidate_apply.py")
        else:
            st.info("No jobs available at the moment.")
    except Exception as e:
        st.error(f"Error fetching jobs: {str(e)}")


def ceo_dashboard():
    # Set default view before any rendering so first load shows HR tab
    if "ceo_view" not in st.session_state:
        st.session_state.ceo_view = "hr"

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        st.markdown('<h2 class="header-gradient">🏢 Executive Dashboard</h2>', unsafe_allow_html=True)
    with col3:
        if st.button("🚪 Logout"):
            logout()
    
    st.markdown("---")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("👥 View HR", use_container_width=True):
            st.session_state.ceo_view = "hr"
            st.rerun()
    
    with col2:
        if st.button("👤 View Candidates", use_container_width=True):
            st.session_state.ceo_view = "candidates"
            st.rerun()
    
    with col3:
        if st.button("👔 Team", use_container_width=True):
            st.session_state.ceo_view = "team"
            st.rerun()
    
    with col4:
        if st.button("⚙️ Settings", use_container_width=True):
            st.session_state.ceo_view = "settings"
            st.rerun()
    
    st.markdown("---")
    
    if st.session_state.ceo_view == "settings":
        st.markdown("### ⚙️ CEO Settings")
        try:
            profile = api.get_ceo_profile()
            with st.form("ceo_settings"):
                new_name = st.text_input("Name", value=profile.get("name", ""))
                new_email = st.text_input("Email", value=profile.get("email", ""))
                new_password = st.text_input("New Password (leave blank to keep current)", type="password")
                submit = st.form_submit_button("Save Changes", type="primary")
                
                if submit:
                    if not new_name or not new_email:
                        st.error("Name and Email are required")
                    else:
                        try:
                            api.update_ceo_profile(new_name, new_email, new_password if new_password else "")
                            st.success("Settings updated successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to update: {str(e)}")
        except Exception as e:
            st.error(f"Error loading settings: {str(e)}")
    
    elif st.session_state.ceo_view == "team":
        st.markdown("### 👔 Senior Executive Team")
        
        with st.expander("Add New Senior Executive"):
            with st.form("add_executive"):
                exec_name = st.text_input("Name")
                exec_email = st.text_input("Email")
                exec_password = st.text_input("Password", type="password")
                exec_role = st.selectbox("Role", ["COO", "CTO", "CFO", "CMO", "Other"])
                submit_exec = st.form_submit_button("Add Executive", type="primary")
                
                if submit_exec:
                    if not exec_name or not exec_email or not exec_password:
                        st.error("All fields are required")
                    else:
                        try:
                            api.create_senior_executive(exec_name, exec_email, exec_password, exec_role)
                            st.success("Executive added successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to add: {str(e)}")
        
        try:
            executives = api.get_all_senior_executives()
            if executives:
                for exec in executives:
                    with st.expander(f"👔 {exec['name']} - {exec['role']}"):
                        st.write(f"**Email:** {exec['email']}")
                        st.write(f"**Role:** {exec['role']}")
            else:
                st.info("No senior executives found.")
        except Exception as e:
            st.error(f"Error fetching team: {str(e)}")
    
    elif st.session_state.ceo_view == "hr":
        st.markdown("### All HR Personnel")
        
        with st.expander("➕ Add New HR Personnel"):
            with st.form("add_hr"):
                hr_name = st.text_input("Name")
                hr_email = st.text_input("Email")
                hr_password = st.text_input("Password", type="password")
                submit_hr = st.form_submit_button("Add HR", type="primary")
                
                if submit_hr:
                    if not hr_name or not hr_email or not hr_password:
                        st.error("All fields are required")
                    else:
                        try:
                            api.create_hr(hr_name, hr_email, hr_password)
                            st.success("HR added successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to add HR: {str(e)}")
        
        try:
            hrs = api.get_all_hr()
            if hrs:
                for hr in hrs:
                    with st.expander(f"👔 {hr['name']}"):
                        st.write(f"**Email:** {hr['email']}")
            else:
                st.info("No HR personnel found.")
        except Exception as e:
            st.error(f"Error fetching HR: {str(e)}")
    else:
        st.markdown("### All Candidates")
        try:
            candidates = api.get_all_candidates()
            if candidates:
                for candidate in candidates:
                    with st.expander(f"👤 {candidate['name']}"):
                        st.write(f"**Email:** {candidate['email']}")
                        st.write(f"**Phone:** {candidate.get('phone', 'N/A')}")
                        st.write(f"**Skills:** {candidate.get('skills', 'N/A')}")
                        st.write(f"**Experience:** {candidate.get('experience', 'N/A')}")
            else:
                st.info("No candidates found.")
        except Exception as e:
            st.error(f"Error fetching candidates: {str(e)}")


def main():
    if not st.session_state.authenticated:
        login_page()
    else:
        if st.session_state.role == "hr":
            hr_dashboard()
        elif st.session_state.role == "candidate":
            candidate_dashboard()
        elif st.session_state.role in ["ceo", "coo", "cto", "cfo", "cmo", "other"]:
            ceo_dashboard()
        else:
            st.error("Unknown role")
            logout()


if __name__ == "__main__":
    main()
