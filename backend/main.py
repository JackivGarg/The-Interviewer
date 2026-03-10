from fastapi import FastAPI, Depends, HTTPException, status, Header, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from backend.database import engine, Base, SessionLocal
from backend.models import SeniorExecutive, HR, Candidate, JobPosting, CandidateApplication
from backend.schemas import (
    HRCreate, HRResponse, CandidateCreate, CandidateResponse,
    LoginRequest, TokenResponse, JobPostingCreate, JobPostingResponse,
    JobPostingListResponse, CandidateApplicationCreate, CandidateApplicationResponse,
    ApplicationWithJobResponse, SeniorExecutiveCreate, SeniorExecutiveResponse
)
from backend.auth import (
    verify_password, get_password_hash, create_access_token,
    decode_token
)
from backend.voice_service import voice_service
from passlib.context import CryptContext
from typing import List, Dict

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(title="The Interviewer - Backend API")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(token: str = Security(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = decode_token(token)
        email = payload.get("sub")
        role = payload.get("role")
        if email is None or role is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    if role in ["ceo", "coo", "cto"]:
        user = db.query(SeniorExecutive).filter(SeniorExecutive.email == email).first()
    elif role == "hr":
        user = db.query(HR).filter(HR.email == email).first()
    elif role == "candidate":
        user = db.query(Candidate).filter(Candidate.email == email).first()
    else:
        raise HTTPException(status_code=401, detail="Invalid role")
    
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user, role


Base.metadata.create_all(bind=engine)
db = SessionLocal()
try:
    existing_ceo = db.query(SeniorExecutive).filter(SeniorExecutive.is_ceo == "yes").first()
    if not existing_ceo:
        hashed_password = pwd_context.hash("admin@123")
        ceo = SeniorExecutive(name="Jackiv Garg", email="jackivgarg@gmail.com", password=hashed_password, role="CEO", is_ceo="yes")
        db.add(ceo)
        db.commit()
finally:
    db.close()


@app.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    executive = db.query(SeniorExecutive).filter(SeniorExecutive.email == request.email).first()
    if executive and verify_password(request.password, executive.password):
        role = executive.role.lower()
        token = create_access_token({"sub": executive.email, "role": role})
        return TokenResponse(access_token=token, token_type="bearer", role=role)
    
    hr = db.query(HR).filter(HR.email == request.email).first()
    if hr and verify_password(request.password, hr.password):
        token = create_access_token({"sub": hr.email, "role": "hr"})
        return TokenResponse(access_token=token, token_type="bearer", role="hr")
    
    candidate = db.query(Candidate).filter(Candidate.email == request.email).first()
    if candidate and verify_password(request.password, candidate.password):
        token = create_access_token({"sub": candidate.email, "role": "candidate"})
        return TokenResponse(access_token=token, token_type="bearer", role="candidate")
    
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.post("/token", response_model=TokenResponse)
def login_oauth(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    request = LoginRequest(email=form_data.username, password=form_data.password)
    return login(request, db)


@app.post("/signup/candidate", response_model=CandidateResponse)
def signup_candidate(candidate: CandidateCreate, db: Session = Depends(get_db)):
    existing = db.query(Candidate).filter(Candidate.email == candidate.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(candidate.password)
    new_candidate = Candidate(
        name=candidate.name,
        email=candidate.email,
        password=hashed_password,
        phone=candidate.phone,
        skills=candidate.skills,
        experience=candidate.experience
    )
    db.add(new_candidate)
    db.commit()
    db.refresh(new_candidate)
    return new_candidate


@app.post("/signup/hr", response_model=HRResponse)
def signup_hr(hr: HRCreate, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    user, role = current_user
    if role != "ceo":
        raise HTTPException(status_code=403, detail="Only CEO can add HR")
    existing = db.query(HR).filter(HR.email == hr.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(hr.password)
    new_hr = HR(name=hr.name, email=hr.email, password=hashed_password)
    db.add(new_hr)
    db.commit()
    db.refresh(new_hr)
    return new_hr


@app.get("/hr/jobs", response_model=List[JobPostingResponse])
def get_hr_jobs(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    user, role = current_user
    if role != "hr":
        raise HTTPException(status_code=403, detail="Only HR can view their jobs")
    return db.query(JobPosting).filter(JobPosting.hr_id == user.id).all()


@app.post("/hr/jobs", response_model=JobPostingResponse)
def create_job(
    job: JobPostingCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    user, role = current_user
    if role != "hr":
        raise HTTPException(status_code=403, detail="Only HR can create jobs")
    
    new_job = JobPosting(
        hr_id=user.id,
        title=job.title,
        description=job.description,
        experience_required=job.experience_required,
        skills_required=job.skills_required,
        additional_requirements=job.additional_requirements,
        questions_to_ask=job.questions_to_ask,
        more_info=job.more_info
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    return new_job


@app.get("/jobs", response_model=List[JobPostingListResponse])
def get_all_jobs(db: Session = Depends(get_db)):
    return db.query(JobPosting).all()


@app.get("/jobs/{job_id}", response_model=JobPostingResponse)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/apply", response_model=CandidateApplicationResponse)
def apply_to_job(
    application: CandidateApplicationCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    user, role = current_user
    if role != "candidate":
        raise HTTPException(status_code=403, detail="Only candidates can apply")
    
    job = db.query(JobPosting).filter(JobPosting.id == application.job_posting_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    existing_application = db.query(CandidateApplication).filter(
        CandidateApplication.job_posting_id == application.job_posting_id,
        CandidateApplication.candidate_id == user.id
    ).first()
    
    if existing_application:
        raise HTTPException(status_code=400, detail="Already applied to this job")
    
    new_application = CandidateApplication(
        job_posting_id=application.job_posting_id,
        candidate_id=user.id,
        years_of_experience=application.years_of_experience,
        skills=application.skills,
        university=application.university,
        additional_info=application.additional_info
    )
    db.add(new_application)
    db.commit()
    db.refresh(new_application)
    return new_application


@app.get("/candidate/applications", response_model=List[CandidateApplicationResponse])
def get_candidate_applications(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    user, role = current_user
    if role != "candidate":
        raise HTTPException(status_code=403, detail="Only candidates can view their applications")
    return db.query(CandidateApplication).filter(CandidateApplication.candidate_id == user.id).all()


@app.get("/hr/jobs/{job_id}/applications", response_model=List[CandidateApplicationResponse])
def get_job_applications(
    job_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    user, role = current_user
    if role != "hr":
        raise HTTPException(status_code=403, detail="Only HR can view applications")
    
    job = db.query(JobPosting).filter(JobPosting.id == job_id, JobPosting.hr_id == user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return db.query(CandidateApplication).filter(CandidateApplication.job_posting_id == job_id).all()


@app.get("/candidates", response_model=List[CandidateResponse])
def get_candidates(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    user, role = current_user
    if role not in ["ceo", "hr"]:
        raise HTTPException(status_code=403, detail="Only CEO or HR can view candidates")
    return db.query(Candidate).all()


@app.get("/hr/all", response_model=List[HRResponse])
def get_all_hr(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    user, role = current_user
    if role != "ceo":
        raise HTTPException(status_code=403, detail="Only CEO can view all HR")
    return db.query(HR).all()


@app.get("/ceo/candidates", response_model=List[CandidateResponse])
def get_ceo_candidates(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    user, role = current_user
    if role != "ceo":
        raise HTTPException(status_code=403, detail="Only CEO can view all candidates")
    return db.query(Candidate).all()


@app.get("/ceo/hr-activity", response_model=List[JobPostingResponse])
def get_ceo_hr_activity(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    user, role = current_user
    if role != "ceo":
        raise HTTPException(status_code=403, detail="Only CEO can view HR activity")
    return db.query(JobPosting).all()


@app.get("/ceo/applications", response_model=List[CandidateApplicationResponse])
def get_ceo_applications(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    user, role = current_user
    if role != "ceo":
        raise HTTPException(status_code=403, detail="Only CEO can view all applications")
    return db.query(CandidateApplication).all()


@app.get("/ceo/profile")
def get_ceo_profile(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    user, role = current_user
    if role != "ceo":
        raise HTTPException(status_code=403, detail="Only CEO can view profile")
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


@app.put("/ceo/profile")
def update_ceo_profile(name: str, email: str, password: str = None, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    user, role = current_user
    if role != "ceo":
        raise HTTPException(status_code=403, detail="Only CEO can update profile")
    
    existing = db.query(SeniorExecutive).filter(SeniorExecutive.email == email, SeniorExecutive.id != user.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already in use")
    
    user.name = name
    user.email = email
    if password:
        user.password = get_password_hash(password)
    
    db.commit()
    db.refresh(user)
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


@app.get("/senior-executives", response_model=List[SeniorExecutiveResponse])
def get_senior_executives(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    user, role = current_user
    if role != "ceo":
        raise HTTPException(status_code=403, detail="Only CEO can view senior executives")
    return db.query(SeniorExecutive).all()


@app.post("/senior-executives", response_model=SeniorExecutiveResponse)
def create_senior_executive(executive: SeniorExecutiveCreate, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    user, role = current_user
    if role != "ceo":
        raise HTTPException(status_code=403, detail="Only CEO can add senior executives")
    
    existing = db.query(SeniorExecutive).filter(SeniorExecutive.email == executive.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(executive.password)
    new_executive = SeniorExecutive(
        name=executive.name,
        email=executive.email,
        password=hashed_password,
        role=executive.role,
        is_ceo="no"
    )
    db.add(new_executive)
    db.commit()
    db.refresh(new_executive)
    return new_executive


@app.delete("/senior-executives/{executive_id}")
def delete_senior_executive(executive_id: int, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    user, role = current_user
    if role != "ceo":
        raise HTTPException(status_code=403, detail="Only CEO can delete senior executives")
    
    executive = db.query(SeniorExecutive).filter(SeniorExecutive.id == executive_id, SeniorExecutive.is_ceo == "no").first()
    if not executive:
        raise HTTPException(status_code=404, detail="Senior executive not found or cannot delete CEO")
    
    db.delete(executive)
    db.commit()
    return {"message": "Senior executive deleted successfully"}


@app.post("/api/interview/chat")
def interview_chat(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    user, role = current_user
    if role != "candidate":
        raise HTTPException(status_code=403, detail="Only candidates can interview")
    
    job_id = payload.get("job_id")
    history = payload.get("history", [])
    
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    job_details = {
        "title": job.title,
        "description": job.description,
        "skills_required": job.skills_required,
        "questions_to_ask": job.questions_to_ask
    }
    
    candidate_details = {
        "name": user.name,
        "experience": user.experience,
        "skills": user.skills
    }
    
    ai_response = voice_service.get_response(history, job_details, candidate_details)
    return {"response": ai_response}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
