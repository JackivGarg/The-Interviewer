from pydantic import BaseModel
from typing import Optional, List


class HRCreate(BaseModel):
    name: str
    email: str
    password: str


class HRResponse(BaseModel):
    id: int
    name: str
    email: str

    class Config:
        from_attributes = True


class CandidateCreate(BaseModel):
    name: str
    email: str
    password: str
    phone: Optional[str] = None
    skills: Optional[str] = None
    experience: Optional[str] = None


class CandidateResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str] = None
    skills: Optional[str] = None
    experience: Optional[str] = None

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    role: str


class JobPostingCreate(BaseModel):
    title: str
    description: str
    experience_required: int
    skills_required: str
    additional_requirements: Optional[str] = None
    questions_to_ask: Optional[str] = None
    more_info: Optional[str] = None


class JobPostingResponse(BaseModel):
    id: int
    hr_id: int
    title: str
    description: str
    experience_required: int
    skills_required: str
    additional_requirements: Optional[str] = None
    questions_to_ask: Optional[str] = None
    more_info: Optional[str] = None

    class Config:
        from_attributes = True


class JobPostingListResponse(BaseModel):
    id: int
    title: str
    description: str
    experience_required: int

    class Config:
        from_attributes = True


class CandidateApplicationCreate(BaseModel):
    job_posting_id: int
    years_of_experience: int
    skills: str
    university: Optional[str] = None
    additional_info: Optional[str] = None


class CandidateApplicationResponse(BaseModel):
    id: int
    job_posting_id: int
    candidate_id: int
    years_of_experience: int
    skills: str
    university: Optional[str] = None
    additional_info: Optional[str] = None
    status: str

    class Config:
        from_attributes = True


class ApplicationWithJobResponse(BaseModel):
    id: int
    job_posting: JobPostingResponse
    years_of_experience: int
    skills: str
    university: Optional[str] = None
    additional_info: Optional[str] = None
    status: str

    class Config:
        from_attributes = True
