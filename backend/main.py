from fastapi import FastAPI, Depends, HTTPException, status, Security, WebSocket, WebSocketDisconnect, File, UploadFile, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
import os
import time
import asyncio
import logging
import json as json_module

# ── Centralized logging (MUST be first, before other backend imports) ────────
from backend.logging_config import setup_logging
setup_logging()

from backend.database import engine, Base, SessionLocal
from backend.models import SeniorExecutive, HR, Candidate, JobPosting, CandidateApplication
from backend.schemas import (
    HRCreate, HRResponse, CandidateCreate, CandidateResponse,
    LoginRequest, TokenResponse, JobPostingCreate, JobPostingResponse,
    JobPostingListResponse, CandidateApplicationCreate, CandidateApplicationResponse,
    ApplicationWithJobResponse, SeniorExecutiveCreate, SeniorExecutiveResponse,
    CEOProfileUpdate, ApplicationStatusUpdate
)
from backend.auth import (
    verify_password, get_password_hash, create_access_token,
    decode_token, pwd_context
)
from backend.services.voice_handler import handle_voice_session
from backend.services.resume_parser import extract_text_from_pdf, extract_candidate_profile
from backend.services.question_file_generator import generate_question_file
from typing import List, Dict, Any, Optional

logger = logging.getLogger("interviewer.api")

app = FastAPI(title="The Interviewer - Backend API")


# ── Request/Response logging middleware ───────────────────────────────────────
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every HTTP request with method, path, status code, and duration."""
    async def dispatch(self, request: Request, call_next):
        t0 = time.time()
        method = request.method
        path = request.url.path
        logger.info(f"→ {method} {path}")
        try:
            response = await call_next(request)
            elapsed = round((time.time() - t0) * 1000, 1)
            logger.info(f"← {method} {path} │ {response.status_code} │ {elapsed}ms")
            return response
        except Exception as e:
            elapsed = round((time.time() - t0) * 1000, 1)
            logger.error(f"✗ {method} {path} │ EXCEPTION │ {elapsed}ms │ {type(e).__name__}: {e}")
            raise


app.add_middleware(RequestLoggingMiddleware)

# ── In-memory store for prepared interview data ──────────────────────────────
# Key: (job_id, candidate_id) → {resume_profile, question_file}
# Populated by /api/interview/prepare, consumed by WS handler
_prepared_interviews: Dict[tuple, dict] = {}

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
    
    if role in ["ceo", "coo", "cto", "cfo", "cmo", "other"]:
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


class RoleChecker:
    """Reusable FastAPI dependency for role-based authorization."""
    def __init__(self, allowed_roles: list):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user=Depends(get_current_user)):
        user, role = current_user
        if role not in self.allowed_roles:
            logger.warning(f"[RBAC] ACCESS DENIED: role='{role}' tried to access endpoint requiring {self.allowed_roles}")
            raise HTTPException(status_code=403, detail="Not authorized")
        logger.debug(f"[RBAC] Access granted: role='{role}' (allowed={self.allowed_roles})")
        return user, role


# Pre-built role checkers for common patterns
allow_ceo = RoleChecker(["ceo"])
allow_hr = RoleChecker(["hr"])
allow_candidate = RoleChecker(["candidate"])
allow_ceo_hr = RoleChecker(["ceo", "hr"])


Base.metadata.create_all(bind=engine)
logger.info("[Startup] Database tables created/verified")

EVAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evaluations")
os.makedirs(EVAL_DIR, exist_ok=True)
logger.info(f"[Startup] Evaluation dir: {EVAL_DIR}")

db = SessionLocal()
try:
    existing_ceo = db.query(SeniorExecutive).filter(SeniorExecutive.is_ceo == "yes").first()
    if not existing_ceo:
        hashed_password = pwd_context.hash("admin@123")
        ceo = SeniorExecutive(name="Jackiv Garg", email="jackivgarg@gmail.com", password=hashed_password, role="CEO", is_ceo="yes")
        db.add(ceo)
        db.commit()
        logger.info("[Startup] Default CEO account created (jackivgarg@gmail.com)")
    else:
        logger.info(f"[Startup] CEO account already exists: {existing_ceo.email}")
finally:
    db.close()


@app.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    logger.info(f"[Auth] Login attempt: email={request.email}")

    executive = db.query(SeniorExecutive).filter(SeniorExecutive.email == request.email).first()
    if executive and verify_password(request.password, executive.password):
        role = executive.role.lower()
        token = create_access_token({"sub": executive.email, "role": role})
        logger.info(f"[Auth] Login SUCCESS: email={request.email} role={role} (SeniorExecutive)")
        return TokenResponse(access_token=token, token_type="bearer", role=role)
    
    hr = db.query(HR).filter(HR.email == request.email).first()
    if hr and verify_password(request.password, hr.password):
        token = create_access_token({"sub": hr.email, "role": "hr"})
        logger.info(f"[Auth] Login SUCCESS: email={request.email} role=hr")
        return TokenResponse(access_token=token, token_type="bearer", role="hr")
    
    candidate = db.query(Candidate).filter(Candidate.email == request.email).first()
    if candidate and verify_password(request.password, candidate.password):
        token = create_access_token({"sub": candidate.email, "role": "candidate"})
        logger.info(f"[Auth] Login SUCCESS: email={request.email} role=candidate")
        return TokenResponse(access_token=token, token_type="bearer", role="candidate")
    
    logger.warning(f"[Auth] Login FAILED: email={request.email} (invalid credentials)")
    raise HTTPException(status_code=401, detail="Invalid credentials")




@app.post("/signup/candidate", response_model=CandidateResponse)
def signup_candidate(candidate: CandidateCreate, db: Session = Depends(get_db)):
    logger.info(f"[Signup] Candidate registration: name={candidate.name} email={candidate.email}")
    existing = db.query(Candidate).filter(Candidate.email == candidate.email).first()
    if existing:
        logger.warning(f"[Signup] REJECTED: email={candidate.email} already registered")
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
    logger.info(f"[Signup] Candidate CREATED: id={new_candidate.id} name={new_candidate.name}")
    return new_candidate


@app.post("/signup/hr", response_model=HRResponse)
def signup_hr(hr: HRCreate, db: Session = Depends(get_db), current_user=Depends(allow_ceo)):
    user, role = current_user
    logger.info(f"[Signup] HR registration by CEO: name={hr.name} email={hr.email}")
    existing = db.query(HR).filter(HR.email == hr.email).first()
    if existing:
        logger.warning(f"[Signup] HR REJECTED: email={hr.email} already registered")
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(hr.password)
    new_hr = HR(name=hr.name, email=hr.email, password=hashed_password)
    db.add(new_hr)
    db.commit()
    db.refresh(new_hr)
    logger.info(f"[Signup] HR CREATED: id={new_hr.id} name={new_hr.name}")
    return new_hr


@app.get("/hr/jobs", response_model=List[JobPostingResponse])
def get_hr_jobs(db: Session = Depends(get_db), current_user=Depends(allow_hr)):
    user, role = current_user
    jobs = db.query(JobPosting).filter(JobPosting.hr_id == user.id).all()
    logger.info(f"[Jobs] HR id={user.id} fetched {len(jobs)} job postings")
    return jobs


@app.post("/hr/jobs", response_model=JobPostingResponse)
def create_job(
    job: JobPostingCreate,
    db: Session = Depends(get_db),
    current_user=Depends(allow_hr),
):
    user, role = current_user
    logger.info(f"[Jobs] HR id={user.id} creating job: title='{job.title}'")
    
    # Serialize interview_topics list to JSON string for DB storage
    topics_json = None
    if job.interview_topics:
        topics_json = json_module.dumps([t.model_dump() for t in job.interview_topics])
        logger.info(f"[Jobs] Interview topics: {len(job.interview_topics)} topics defined")
    
    new_job = JobPosting(
        hr_id=user.id,
        title=job.title,
        description=job.description,
        experience_required=job.experience_required,
        skills_required=job.skills_required,
        additional_requirements=job.additional_requirements,
        questions_to_ask=job.questions_to_ask,
        more_info=job.more_info,
        interview_topics=topics_json,
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    logger.info(f"[Jobs] Job CREATED: id={new_job.id} title='{new_job.title}' by HR id={user.id}")
    return new_job


@app.get("/jobs", response_model=List[JobPostingListResponse])
def get_all_jobs(db: Session = Depends(get_db)):
    jobs = db.query(JobPosting).all()
    logger.info(f"[Jobs] Public job listing: {len(jobs)} jobs")
    return jobs


@app.get("/jobs/{job_id}", response_model=JobPostingResponse)
def get_job(job_id: int, db: Session = Depends(get_db)):
    logger.debug(f"[Jobs] Fetching job_id={job_id}")
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    if not job:
        logger.warning(f"[Jobs] Job NOT FOUND: job_id={job_id}")
        raise HTTPException(status_code=404, detail="Job not found")
    logger.info(f"[Jobs] Fetched job: id={job.id} title='{job.title}'")
    return job


@app.post("/apply", response_model=CandidateApplicationResponse)
def apply_to_job(
    application: CandidateApplicationCreate,
    db: Session = Depends(get_db),
    current_user=Depends(allow_candidate),
):
    user, role = current_user
    logger.info(f"[Apply] Candidate id={user.id} applying to job_id={application.job_posting_id}")
    
    job = db.query(JobPosting).filter(JobPosting.id == application.job_posting_id).first()
    if not job:
        logger.warning(f"[Apply] Job NOT FOUND: job_id={application.job_posting_id}")
        raise HTTPException(status_code=404, detail="Job not found")
    
    existing_application = db.query(CandidateApplication).filter(
        CandidateApplication.job_posting_id == application.job_posting_id,
        CandidateApplication.candidate_id == user.id
    ).first()
    
    if existing_application:
        logger.warning(f"[Apply] DUPLICATE: candidate_id={user.id} already applied to job_id={application.job_posting_id}")
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
    logger.info(f"[Apply] Application CREATED: id={new_application.id} candidate_id={user.id} job_id={application.job_posting_id}")
    return new_application


@app.get("/candidate/applications", response_model=List[CandidateApplicationResponse])
def get_candidate_applications(
    db: Session = Depends(get_db),
    current_user=Depends(allow_candidate),
):
    user, role = current_user
    apps = db.query(CandidateApplication).filter(CandidateApplication.candidate_id == user.id).all()
    logger.info(f"[Applications] Candidate id={user.id} has {len(apps)} applications")
    return apps


@app.get("/hr/jobs/{job_id}/applications")
def get_job_applications(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(allow_hr),
):
    user, role = current_user
    logger.info(f"[Applications] HR id={user.id} fetching applications for job_id={job_id}")
    
    job = db.query(JobPosting).filter(JobPosting.id == job_id, JobPosting.hr_id == user.id).first()
    if not job:
        logger.warning(f"[Applications] Job NOT FOUND or not owned: job_id={job_id} hr_id={user.id}")
        raise HTTPException(status_code=404, detail="Job not found")
    
    applications = db.query(CandidateApplication).filter(CandidateApplication.job_posting_id == job_id).all()
    logger.info(f"[Applications] Found {len(applications)} applications for job_id={job_id}")
    # Attach candidate name to each application for HR display
    result = []
    for app in applications:
        candidate = db.query(Candidate).filter(Candidate.id == app.candidate_id).first()
        app_dict = {
            "id": app.id,
            "job_posting_id": app.job_posting_id,
            "candidate_id": app.candidate_id,
            "candidate_name": candidate.name if candidate else "Unknown",
            "years_of_experience": app.years_of_experience,
            "skills": app.skills,
            "university": app.university,
            "additional_info": app.additional_info,
            "status": app.status
        }
        result.append(app_dict)
    return result


@app.patch("/hr/jobs/{job_id}/applications/{app_id}/status")
def update_application_status(
    job_id: int,
    app_id: int,
    payload: ApplicationStatusUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(allow_hr),
):
    user, role = current_user
    logger.info(f"[Status] HR id={user.id} updating app_id={app_id} on job_id={job_id} to '{payload.status}'")
    
    # Verify the job belongs to this HR
    job = db.query(JobPosting).filter(JobPosting.id == job_id, JobPosting.hr_id == user.id).first()
    if not job:
        logger.warning(f"[Status] Job NOT FOUND or not owned: job_id={job_id} hr_id={user.id}")
        raise HTTPException(status_code=404, detail="Job not found")
    
    application = db.query(CandidateApplication).filter(
        CandidateApplication.id == app_id,
        CandidateApplication.job_posting_id == job_id
    ).first()
    if not application:
        logger.warning(f"[Status] Application NOT FOUND: app_id={app_id} job_id={job_id}")
        raise HTTPException(status_code=404, detail="Application not found")
    
    valid_statuses = ["pending", "interviewed", "hired", "rejected"]
    if payload.status not in valid_statuses:
        logger.warning(f"[Status] Invalid status '{payload.status}' — must be one of {valid_statuses}")
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
    
    old_status = application.status
    application.status = payload.status
    db.commit()
    db.refresh(application)
    logger.info(f"[Status] Application id={app_id} status changed: '{old_status}' -> '{payload.status}'")
    return {"message": "Status updated", "status": application.status}


@app.get("/candidates", response_model=List[CandidateResponse])
def get_candidates(db: Session = Depends(get_db), current_user=Depends(allow_ceo_hr)):
    user, role = current_user
    candidates = db.query(Candidate).all()
    logger.info(f"[Users] {role} fetched {len(candidates)} candidates")
    return candidates


@app.get("/hr/all", response_model=List[HRResponse])
def get_all_hr(db: Session = Depends(get_db), current_user=Depends(allow_ceo)):
    user, role = current_user
    hr_list = db.query(HR).all()
    logger.info(f"[Users] CEO fetched {len(hr_list)} HR users")
    return hr_list





@app.get("/ceo/applications", response_model=List[CandidateApplicationResponse])
def get_ceo_applications(db: Session = Depends(get_db), current_user=Depends(allow_ceo)):
    user, role = current_user
    apps = db.query(CandidateApplication).all()
    logger.info(f"[CEO] Fetched {len(apps)} total applications")
    return apps


@app.get("/ceo/profile")
def get_ceo_profile(db: Session = Depends(get_db), current_user=Depends(allow_ceo)):
    user, role = current_user
    logger.info(f"[CEO] Profile fetched for: {user.name} ({user.email})")
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


@app.put("/ceo/profile")
def update_ceo_profile(payload: CEOProfileUpdate, db: Session = Depends(get_db), current_user=Depends(allow_ceo)):
    user, role = current_user
    logger.info(f"[CEO] Profile update: name='{payload.name}' email='{payload.email}'")
    
    existing = db.query(SeniorExecutive).filter(SeniorExecutive.email == payload.email, SeniorExecutive.id != user.id).first()
    if existing:
        logger.warning(f"[CEO] Profile update REJECTED: email='{payload.email}' already in use")
        raise HTTPException(status_code=400, detail="Email already in use")
    
    user.name = payload.name
    user.email = payload.email
    if payload.password and payload.password.strip():
        user.password = get_password_hash(payload.password)
        logger.info("[CEO] Password updated")
    
    db.commit()
    db.refresh(user)
    logger.info(f"[CEO] Profile UPDATED: id={user.id} name='{user.name}'")
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


@app.get("/senior-executives", response_model=List[SeniorExecutiveResponse])
def get_senior_executives(db: Session = Depends(get_db), current_user=Depends(allow_ceo)):
    user, role = current_user
    execs = db.query(SeniorExecutive).all()
    logger.info(f"[Executives] Fetched {len(execs)} senior executives")
    return execs


@app.post("/senior-executives", response_model=SeniorExecutiveResponse)
def create_senior_executive(executive: SeniorExecutiveCreate, db: Session = Depends(get_db), current_user=Depends(allow_ceo)):
    user, role = current_user
    logger.info(f"[Executives] Creating: name='{executive.name}' email='{executive.email}' role='{executive.role}'")
    
    existing = db.query(SeniorExecutive).filter(SeniorExecutive.email == executive.email).first()
    if existing:
        logger.warning(f"[Executives] REJECTED: email='{executive.email}' already registered")
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
    logger.info(f"[Executives] CREATED: id={new_executive.id} name='{new_executive.name}' role='{new_executive.role}'")
    return new_executive


@app.delete("/senior-executives/{executive_id}")
def delete_senior_executive(executive_id: int, db: Session = Depends(get_db), current_user=Depends(allow_ceo)):
    user, role = current_user
    logger.info(f"[Executives] Deleting executive_id={executive_id}")
    
    executive = db.query(SeniorExecutive).filter(SeniorExecutive.id == executive_id, SeniorExecutive.is_ceo == "no").first()
    if not executive:
        logger.warning(f"[Executives] NOT FOUND or CEO: executive_id={executive_id}")
        raise HTTPException(status_code=404, detail="Senior executive not found or cannot delete CEO")
    
    db.delete(executive)
    db.commit()
    logger.info(f"[Executives] DELETED: id={executive_id} name='{executive.name}'")
    return {"message": "Senior executive deleted successfully"}



# ══════════════════════════════════════════════════════════════════════════════
# INTERVIEW ENDPOINTS — Resume upload, preparation, and live WebSocket session
# ══════════════════════════════════════════════════════════════════════════════


@app.post(
    "/api/interview/prepare",
    summary="Prepare interview -- upload resume PDF + generate question file",
    tags=["Interview"],
)
async def prepare_interview(
    file: UploadFile = File(...),
    job_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Mandatory pre-interview step. Accepts a resume PDF, extracts a structured
    candidate profile, and generates a tailored question file.

    The prepared data is stored in memory and retrieved when the WebSocket connects.
    """
    user, role = current_user
    if role != "candidate":
        raise HTTPException(status_code=403, detail="Only candidates can prepare interviews")
    candidate_id = user.id
    logger.info(f"[Prepare] Called | job_id={job_id} | candidate_id={candidate_id} | file={file.filename}")
    t_start = time.time()

    # Validate job exists
    job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Read PDF
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    logger.info(f"[Prepare] PDF read | size={len(file_bytes):,} bytes")

    # Save PDF to uploads/
    UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    pdf_path = os.path.join(UPLOAD_DIR, f"job_{job_id}_candidate_{candidate_id}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(file_bytes)
    logger.info(f"[Prepare] PDF saved: {pdf_path}")

    # Update resume_path in DB (optional — best-effort)
    try:
        application = db.query(CandidateApplication).filter(
            CandidateApplication.candidate_id == candidate_id,
            CandidateApplication.job_posting_id == job_id,
        ).first()
        if application:
            application.resume_path = pdf_path
            db.commit()
    except Exception as e:
        logger.warning(f"[Prepare] Could not update resume_path in DB: {e}")

    # Step 1: Extract text from PDF
    try:
        resume_text = await asyncio.to_thread(extract_text_from_pdf, file_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Step 2: Extract candidate profile via Gemini
    logger.info("[Prepare] Extracting candidate profile...")
    resume_profile = await asyncio.to_thread(extract_candidate_profile, resume_text)
    logger.info(f"[Prepare] Profile extracted: name={resume_profile.get('name')} | skills={len(resume_profile.get('skills', []))}")

    # Step 3: Generate question file
    logger.info("[Prepare] Generating question file...")
    job_details_for_gen = {
        "title": job.title,
        "description": job.description,
        "skills_required": job.skills_required,
        "questions_to_ask": job.questions_to_ask,
    }
    # Parse HR-defined interview topics (with per-topic thresholds)
    interview_topics = []
    if job.interview_topics:
        try:
            interview_topics = json_module.loads(job.interview_topics)
            logger.info(f"[Prepare] HR-defined topics: {len(interview_topics)} topics with thresholds")
        except json_module.JSONDecodeError:
            logger.warning("[Prepare] Failed to parse interview_topics JSON, using auto-generation")
    question_file = await asyncio.to_thread(generate_question_file, resume_profile, job_details_for_gen, interview_topics)
    logger.info(f"[Prepare] Question file generated: {len(question_file.get('topics', []))} topics")

    # Store in memory for the WS handler to pick up
    _prepared_interviews[(job_id, candidate_id)] = {
        "resume_profile": resume_profile,
        "question_file": question_file,
    }

    elapsed = round(time.time() - t_start, 2)
    logger.info(f"[Prepare] Done in {elapsed}s")

    return {
        "status": "ok",
        "resume_profile": resume_profile,
        "question_file": question_file,
        "elapsed_seconds": elapsed,
    }


@app.websocket("/api/ws/interview/{job_id}")
async def websocket_interview(websocket: WebSocket, job_id: int):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    db = SessionLocal()
    try:
        payload = decode_token(token)
        email = payload.get("sub")
        role = payload.get("role")
        if email is None or role != "candidate":
            logger.warning(f"[WS] Auth rejected: email={email} role={role}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        candidate = db.query(Candidate).filter(Candidate.email == email).first()
        if not candidate:
            logger.warning(f"[WS] Candidate not found: email={email}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
        if not job:
            logger.warning(f"[WS] Job not found: job_id={job_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Retrieve prepared interview data (mandatory)
        prep_key = (job_id, candidate.id)
        prepared = _prepared_interviews.pop(prep_key, None)
        if not prepared:
            logger.error(f"[WS] No prepared interview data for {prep_key}. Candidate must call /api/interview/prepare first.")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        resume_profile = prepared["resume_profile"]
        question_file = prepared["question_file"]
        logger.info(f"[WS] Prepared data loaded for {prep_key} | topics={len(question_file.get('topics', []))}")

        job_details = {
            "job_id": job_id,
            "title": job.title,
            "description": job.description,
            "skills_required": job.skills_required,
            "questions_to_ask": job.questions_to_ask,
        }

        application = db.query(CandidateApplication).filter(
            CandidateApplication.candidate_id == candidate.id,
            CandidateApplication.job_posting_id == job_id,
        ).first()

        candidate_details = {
            "candidate_id": candidate.id,
            "name": candidate.name,
            "experience": candidate.experience,
            "skills": candidate.skills,
            "additional_info": application.additional_info if application else "",
        }

        await handle_voice_session(websocket, job_details, candidate_details, resume_profile, question_file)

    except Exception as e:
        logger.error(f"[WS] Auth/connection error: {type(e).__name__}: {e}")
        try:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except Exception:
            pass
    finally:
        db.close()

@app.get("/evaluations/job/{job_id}/candidate/{candidate_id}")
def get_evaluation_report(
    job_id: int,
    candidate_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    import os, json
    user, role = current_user
    if role not in ["hr", "ceo"]:
        raise HTTPException(status_code=403, detail="Only HR or CEO can view evaluation reports")
    
    logger.info(f"[Evaluations] Fetching report: job_id={job_id} candidate_id={candidate_id} by {role}")
    EVAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evaluations")
    eval_path = os.path.join(EVAL_DIR, f"job_{job_id}_candidate_{candidate_id}.json")
    if not os.path.exists(eval_path):
        logger.warning(f"[Evaluations] Report NOT FOUND: {eval_path}")
        raise HTTPException(status_code=404, detail="Evaluation report not found. The candidate may not have completed the interview yet.")
        
    with open(eval_path, "r") as f:
        report = json.load(f)
    logger.info(f"[Evaluations] Report loaded: verdict={report.get('verdict')} tech={report.get('technical_score')}")
    return report




if __name__ == "__main__":
    import uvicorn
    # ROOT CAUSE FIX: websockets v16 removed ping_interval from legacy server,
    # so uvicorn 0.27's ws_ping_interval=None is silently ignored and websockets
    # applies its own default 20s ping that kills long-running sessions.
    #
    # Solution: use wsproto backend — it has ZERO built-in ping mechanism.
    # Our application-level keepalive in voice_handler.py handles liveness.
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        ws="wsproto",
        log_level="info",
    )
