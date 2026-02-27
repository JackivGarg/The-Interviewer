from sqlalchemy import Column, Integer, String, ForeignKey, Text
from sqlalchemy.orm import relationship
from backend.database import Base


class CEO(Base):
    __tablename__ = "ceo"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, default="Jackiv Garg")
    password = Column(String)


class HR(Base):
    __tablename__ = "hr"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)

    job_postings = relationship("JobPosting", back_populates="hr")


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    skills = Column(String, nullable=True)
    experience = Column(String, nullable=True)

    applications = relationship("CandidateApplication", back_populates="candidate")


class JobPosting(Base):
    __tablename__ = "job_postings"

    id = Column(Integer, primary_key=True, index=True)
    hr_id = Column(Integer, ForeignKey("hr.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    experience_required = Column(Integer, nullable=False)
    skills_required = Column(Text, nullable=False)
    additional_requirements = Column(Text, nullable=True)
    questions_to_ask = Column(Text, nullable=True)
    more_info = Column(Text, nullable=True)
    
    hr = relationship("HR", back_populates="job_postings")
    applications = relationship("CandidateApplication", back_populates="job_posting")


class CandidateApplication(Base):
    __tablename__ = "candidate_applications"

    id = Column(Integer, primary_key=True, index=True)
    job_posting_id = Column(Integer, ForeignKey("job_postings.id"), nullable=False)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    years_of_experience = Column(Integer, nullable=False)
    skills = Column(Text, nullable=False)
    university = Column(String, nullable=True)
    additional_info = Column(Text, nullable=True)
    status = Column(String, default="pending")

    job_posting = relationship("JobPosting", back_populates="applications")
    candidate = relationship("Candidate", back_populates="applications")
