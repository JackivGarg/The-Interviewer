import streamlit as st
import requests
from typing import Optional, Dict, Any, List

API_BASE_URL = "http://localhost:8000"


def get_token():
    return st.session_state.get("token")


def set_token(token: str):
    st.session_state["token"] = token


def clear_token():
    st.session_state.pop("token", None)


class APIService:
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url
    
    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        token = get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers
    
    def login(self, email: str, password: str) -> Dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/login",
            json={"email": email, "password": password},
            headers={"Content-Type": "application/json"}
        )
        if response.status_code == 200:
            data = response.json()
            set_token(data["access_token"])
            return data
        raise Exception(response.json().get("detail", "Login failed"))
    
    def signup_candidate(self, name: str, email: str, password: str, phone: Optional[str] = None) -> Dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/signup/candidate",
            json={"name": name, "email": email, "password": password, "phone": phone},
            headers={"Content-Type": "application/json"}
        )
        if response.status_code == 200:
            return response.json()
        try:
            detail = response.json().get("detail", "Signup failed")
        except Exception:
            detail = f"Signup failed (status: {response.status_code})"
        raise Exception(detail)
    
    def get_all_jobs(self) -> List[Dict[str, Any]]:
        response = requests.get(f"{self.base_url}/jobs", headers=self._get_headers())
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Failed to fetch jobs"))
    
    def get_job(self, job_id: int) -> Dict[str, Any]:
        response = requests.get(f"{self.base_url}/jobs/{job_id}", headers=self._get_headers())
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Failed to fetch job"))
    
    def create_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/hr/jobs",
            json=job_data,
            headers=self._get_headers()
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", f"Failed to create job: {response.json()}"))
    
    def get_hr_jobs(self) -> List[Dict[str, Any]]:
        response = requests.get(f"{self.base_url}/hr/jobs", headers=self._get_headers())
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Failed to fetch HR jobs"))
    
    def apply_to_job(self, application_data: Dict[str, Any]) -> Dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/apply",
            json=application_data,
            headers=self._get_headers()
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Failed to apply"))
    
    def get_candidate_applications(self) -> List[Dict[str, Any]]:
        response = requests.get(f"{self.base_url}/candidate/applications", headers=self._get_headers())
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Failed to fetch applications"))


api = APIService()
