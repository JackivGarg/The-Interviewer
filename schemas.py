from pydantic import BaseModel
from typing import Optional


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
