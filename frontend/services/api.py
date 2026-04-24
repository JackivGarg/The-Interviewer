import streamlit as st
import requests
import os
from typing import Optional, Dict, Any, List

API_BASE_URL = os.environ.get("STREAMLIT_API_URL", "http://localhost:8000")


def get_api_base_url():
    return API_BASE_URL


def get_websocket_url():
    base = API_BASE_URL
    if base.startswith("http://"):
        return base.replace("http://", "ws://") + "/api/ws"
    elif base.startswith("https://"):
        return base.replace("https://", "wss://") + "/api/ws"
    return f"ws://{base}/api/ws"


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
        try:
            error_detail = response.json().get("detail", "Login failed")
        except Exception:
            error_detail = f"Login failed (status: {response.status_code})"
        raise Exception(error_detail)
    
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
    
    def get_all_hr(self) -> List[Dict[str, Any]]:
        response = requests.get(f"{self.base_url}/hr/all", headers=self._get_headers())
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Failed to fetch HR"))
    
    def get_all_candidates(self) -> List[Dict[str, Any]]:
        response = requests.get(f"{self.base_url}/ceo/candidates", headers=self._get_headers())
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Failed to fetch candidates"))
    
    def get_ceo_profile(self) -> Dict[str, Any]:
        response = requests.get(f"{self.base_url}/ceo/profile", headers=self._get_headers())
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Failed to fetch profile"))
    
    def update_ceo_profile(self, name: str, email: str, password: str = None) -> Dict[str, Any]:
        payload = {"name": name, "email": email}
        if password and password.strip():
            payload["password"] = password
        response = requests.put(f"{self.base_url}/ceo/profile", json=payload, headers=self._get_headers())
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Failed to update profile"))
    
    def get_all_senior_executives(self) -> List[Dict[str, Any]]:
        response = requests.get(f"{self.base_url}/senior-executives", headers=self._get_headers())
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Failed to fetch senior executives"))
    
    def create_senior_executive(self, name: str, email: str, password: str, role: str) -> Dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/senior-executives",
            json={"name": name, "email": email, "password": password, "role": role},
            headers=self._get_headers()
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Failed to create senior executive"))
    
    def delete_senior_executive(self, executive_id: int) -> Dict[str, Any]:
        response = requests.delete(f"{self.base_url}/senior-executives/{executive_id}", headers=self._get_headers())
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Failed to delete senior executive"))
    
    def create_hr(self, name: str, email: str, password: str) -> Dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/signup/hr",
            json={"name": name, "email": email, "password": password},
            headers=self._get_headers()
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Failed to create HR"))

    def interview_chat(self, job_id: int, history: List[Dict[str, str]]) -> Dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/api/interview/chat",
            json={"job_id": job_id, "history": history},
            headers=self._get_headers()
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Failed to get AI response"))

    def get_evaluation_report(self, job_id: int, candidate_id: int) -> Dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/evaluations/job/{job_id}/candidate/{candidate_id}",
            headers=self._get_headers()
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Evaluation report not found"))

    def update_application_status(self, job_id: int, app_id: int, status: str) -> Dict[str, Any]:
        response = requests.patch(
            f"{self.base_url}/hr/jobs/{job_id}/applications/{app_id}/status",
            json={"status": status},
            headers=self._get_headers()
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(response.json().get("detail", "Failed to update status"))


api = APIService()
