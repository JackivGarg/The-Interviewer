from fastapi import FastAPI, Depends, HTTPException, status, Header, Security, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import os
import io
import wave
import base64
import time
import asyncio
import logging
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
from backend.voice_service import voice_service
from backend.services.voice_handler import handle_voice_session, whisper_model
import edge_tts
from typing import List, Dict, Any, Optional
from pydantic import BaseModel as PydanticBaseModel

# ── Logger setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("interviewer")

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


Base.metadata.create_all(bind=engine)

EVAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evaluations")
os.makedirs(EVAL_DIR, exist_ok=True)

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


@app.get("/hr/jobs/{job_id}/applications")
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
    
    applications = db.query(CandidateApplication).filter(CandidateApplication.job_posting_id == job_id).all()
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
    current_user = Depends(get_current_user)
):
    user, role = current_user
    if role != "hr":
        raise HTTPException(status_code=403, detail="Only HR can update application status")
    
    # Verify the job belongs to this HR
    job = db.query(JobPosting).filter(JobPosting.id == job_id, JobPosting.hr_id == user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    application = db.query(CandidateApplication).filter(
        CandidateApplication.id == app_id,
        CandidateApplication.job_posting_id == job_id
    ).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    
    valid_statuses = ["pending", "interviewed", "hired", "rejected"]
    if payload.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
    
    application.status = payload.status
    db.commit()
    db.refresh(application)
    return {"message": "Status updated", "status": application.status}


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
def update_ceo_profile(payload: CEOProfileUpdate, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    user, role = current_user
    if role != "ceo":
        raise HTTPException(status_code=403, detail="Only CEO can update profile")
    
    existing = db.query(SeniorExecutive).filter(SeniorExecutive.email == payload.email, SeniorExecutive.id != user.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already in use")
    
    user.name = payload.name
    user.email = payload.email
    if payload.password and payload.password.strip():
        user.password = get_password_hash(payload.password)
    
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
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
            
        candidate = db.query(Candidate).filter(Candidate.email == email).first()
        if not candidate:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
            
        job = db.query(JobPosting).filter(JobPosting.id == job_id).first()
        if not job:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
            
        job_details = {
            "job_id": job_id,
            "title": job.title,
            "description": job.description,
            "skills_required": job.skills_required,
            "questions_to_ask": job.questions_to_ask
        }
        
        application = db.query(CandidateApplication).filter(
            CandidateApplication.candidate_id == candidate.id,
            CandidateApplication.job_posting_id == job_id
        ).first()
        
        candidate_details = {
            "candidate_id": candidate.id,
            "name": candidate.name,
            "experience": candidate.experience,
            "skills": candidate.skills,
            "additional_info": application.additional_info if application else ""
        }
        
        await handle_voice_session(websocket, job_details, candidate_details)
        
    except Exception as e:
        print(f"WebSocket auth/connection error: {e}")
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
        
    EVAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evaluations")
    eval_path = os.path.join(EVAL_DIR, f"job_{job_id}_candidate_{candidate_id}.json")
    if not os.path.exists(eval_path):
        raise HTTPException(status_code=404, detail="Evaluation report not found. The candidate may not have completed the interview yet.")
        
    with open(eval_path, "r") as f:
        report = json.load(f)
    return report



# ══════════════════════════════════════════════════════════════════════════════
# DEBUG ENDPOINTS  — for isolated component testing during development
# All endpoints are prefixed with /api/debug/
# NO authentication required so they are easy to call from Swagger UI / curl
# ══════════════════════════════════════════════════════════════════════════════


class DebugChatRequest(PydanticBaseModel):
    """Request body for the debug LLM endpoint."""
    text: str
    job_title: Optional[str] = "Software Engineer"
    job_description: Optional[str] = "General software engineering role"
    skills_required: Optional[str] = "Python, problem-solving"
    questions_to_ask: Optional[str] = None
    candidate_name: Optional[str] = "Test Candidate"
    candidate_experience: Optional[str] = "3 years"
    candidate_skills: Optional[str] = "Python, FastAPI"


class DebugSynthesizeRequest(PydanticBaseModel):
    """Request body for the debug TTS endpoint."""
    text: str
    voice: Optional[str] = "en-US-ChristopherNeural"


@app.post(
    "/api/debug/transcribe",
    summary="[DEBUG] STT — Upload audio file → get transcription",
    tags=["Debug"]
)
async def debug_transcribe(file: UploadFile = File(...)):
    """
    Upload any WAV or MP3 audio file and get the Whisper transcription back.
    Use this to verify the STT component is working independently.

    **Steps in Swagger UI:**
    1. Click 'Try it out'
    2. Upload a .wav file
    3. Click 'Execute'
    4. Check the terminal for live logs
    """
    logger.info("━" * 60)
    logger.info(f"[DEBUG/STT] ▶ Called | file='{file.filename}' | content_type='{file.content_type}'")
    t_start = time.time()

    audio_bytes = await file.read()
    logger.info(f"[DEBUG/STT]   File read | size={len(audio_bytes):,} bytes")

    if len(audio_bytes) == 0:
        logger.error("[DEBUG/STT] ✗ Uploaded file is empty")
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        audio_io = io.BytesIO(audio_bytes)
        logger.info("[DEBUG/STT]   Running Whisper transcription...")
        segments, info = await asyncio.to_thread(
            whisper_model.transcribe,
            audio_io,
            beam_size=1,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400}
        )
        transcription = " ".join(seg.text for seg in segments).strip()
        elapsed = round(time.time() - t_start, 2)

        logger.info(f"[DEBUG/STT] ✓ Done | elapsed={elapsed}s | transcription='{transcription}'")
        logger.info("━" * 60)

        return {
            "status": "ok",
            "transcription": transcription,
            "elapsed_seconds": elapsed,
            "file_size_bytes": len(audio_bytes),
            "detected_language": info.language,
            "language_probability": round(info.language_probability, 4)
        }
    except Exception as e:
        elapsed = round(time.time() - t_start, 2)
        logger.error(f"[DEBUG/STT] ✗ Error after {elapsed}s: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")


@app.post(
    "/api/debug/chat",
    summary="[DEBUG] LLM — Send text → get Gemini AI response",
    tags=["Debug"]
)
async def debug_chat(request: DebugChatRequest):
    """
    Send a text message to the Gemini LLM with optional job/candidate context.
    Get the AI interviewer's response back as plain text.

    Use this to verify:
    - Your GOOGLE_API_KEY is valid
    - The system prompt is working correctly
    - Gemini is generating sensible interview questions
    """
    logger.info("━" * 60)
    logger.info(f"[DEBUG/LLM] ▶ Called | text='{request.text[:80]}...'")
    logger.info(f"[DEBUG/LLM]   Job='{request.job_title}' | Candidate='{request.candidate_name}'")
    t_start = time.time()

    job_details = {
        "title": request.job_title,
        "description": request.job_description,
        "skills_required": request.skills_required,
        "questions_to_ask": request.questions_to_ask
    }
    candidate_details = {
        "name": request.candidate_name,
        "experience": request.candidate_experience,
        "skills": request.candidate_skills
    }
    history = [
        {"role": "user", "parts": [request.text]}
    ]

    try:
        logger.info("[DEBUG/LLM]   Sending to Gemini API...")
        ai_response = await asyncio.wait_for(
            asyncio.to_thread(voice_service.get_response, history, job_details, candidate_details),
            timeout=45.0
        )
        elapsed = round(time.time() - t_start, 2)
        logger.info(f"[DEBUG/LLM] ✓ Done | elapsed={elapsed}s | response='{ai_response[:100]}...'")
        logger.info("━" * 60)

        return {
            "status": "ok",
            "ai_response": ai_response,
            "elapsed_seconds": elapsed,
            "end_interview_signal": "[END_INTERVIEW]" in ai_response
        }
    except asyncio.TimeoutError:
        logger.error("[DEBUG/LLM] ✗ Gemini API timed out after 45s")
        raise HTTPException(status_code=504, detail="Gemini API timed out after 45 seconds")
    except Exception as e:
        elapsed = round(time.time() - t_start, 2)
        logger.error(f"[DEBUG/LLM] ✗ Error after {elapsed}s: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"LLM call failed: {str(e)}")


@app.post(
    "/api/debug/synthesize",
    summary="[DEBUG] TTS — Send text → download audio file",
    tags=["Debug"]
)
async def debug_synthesize(request: DebugSynthesizeRequest):
    """
    Send text and get an MP3 audio file back.
    In Swagger UI, the response will show as a downloadable file.

    Available voices (examples):
    - en-US-ChristopherNeural (default — male, professional)
    - en-US-JennyNeural (female, friendly)
    - en-GB-RyanNeural (British male)
    """
    logger.info("━" * 60)
    logger.info(f"[DEBUG/TTS] ▶ Called | voice='{request.voice}' | text='{request.text[:80]}...'")
    t_start = time.time()

    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    try:
        communicate = edge_tts.Communicate(request.text, request.voice)
        audio_buffer = bytearray()

        logger.info("[DEBUG/TTS]   Streaming TTS from edge-tts...")
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.extend(chunk["data"])

        if not audio_buffer:
            logger.error("[DEBUG/TTS] ✗ edge-tts returned no audio")
            raise HTTPException(status_code=500, detail="TTS produced no audio output")

        elapsed = round(time.time() - t_start, 2)
        logger.info(f"[DEBUG/TTS] ✓ Done | elapsed={elapsed}s | audio_size={len(audio_buffer):,} bytes")
        logger.info("━" * 60)

        return StreamingResponse(
            io.BytesIO(bytes(audio_buffer)),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": 'attachment; filename="tts_output.mp3"',
                "X-Elapsed-Seconds": str(elapsed),
                "X-Audio-Size-Bytes": str(len(audio_buffer))
            }
        )
    except Exception as e:
        elapsed = round(time.time() - t_start, 2)
        logger.error(f"[DEBUG/TTS] ✗ Error after {elapsed}s: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {str(e)}")


@app.post(
    "/api/debug/pipeline",
    summary="[DEBUG] Full Pipeline — Audio file → transcription + AI response + audio (base64)",
    tags=["Debug"]
)
async def debug_full_pipeline(file: UploadFile = File(...)):
    """
    The full end-to-end pipeline in one HTTP call:
    1. Upload audio → Whisper STT → transcription text
    2. Transcription → Gemini LLM → AI response text
    3. AI response text → edge-tts → audio (returned as base64 in JSON)

    This is the single most useful debug endpoint.
    If any step fails, the response will indicate exactly which stage broke.
    """
    logger.info("━" * 60)
    logger.info(f"[DEBUG/PIPELINE] ▶ Called | file='{file.filename}'")
    t_total = time.time()
    result: Dict[str, Any] = {
        "status": "ok",
        "stages": {}
    }

    # ── Stage 1: STT ──────────────────────────────────────────────
    logger.info("[DEBUG/PIPELINE]   Stage 1/3: STT (Whisper)")
    t1 = time.time()
    audio_bytes = await file.read()
    if len(audio_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        audio_io = io.BytesIO(audio_bytes)
        segments, info = await asyncio.to_thread(
            whisper_model.transcribe,
            audio_io,
            beam_size=1,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400}
        )
        transcription = " ".join(seg.text for seg in segments).strip()
        stt_elapsed = round(time.time() - t1, 2)
        logger.info(f"[DEBUG/PIPELINE]   STT ✓ | elapsed={stt_elapsed}s | text='{transcription}'")
        result["stages"]["stt"] = {
            "status": "ok",
            "transcription": transcription,
            "elapsed_seconds": stt_elapsed,
            "detected_language": info.language
        }
    except Exception as e:
        logger.error(f"[DEBUG/PIPELINE] ✗ STT failed: {e}")
        result["status"] = "error"
        result["stages"]["stt"] = {"status": "error", "error": str(e)}
        result["stages"]["llm"] = {"status": "skipped"}
        result["stages"]["tts"] = {"status": "skipped"}
        return result

    if not transcription:
        logger.warning("[DEBUG/PIPELINE]   STT returned empty transcription — audio may be silent")
        result["stages"]["llm"] = {"status": "skipped", "reason": "Empty transcription"}
        result["stages"]["tts"] = {"status": "skipped", "reason": "Empty transcription"}
        result["status"] = "warning"
        return result

    # ── Stage 2: LLM ──────────────────────────────────────────────
    logger.info("[DEBUG/PIPELINE]   Stage 2/3: LLM (Gemini)")
    t2 = time.time()
    job_details = {
        "title": "Senior Python Developer",
        "description": "Debug pipeline test",
        "skills_required": "Python, FastAPI",
        "questions_to_ask": None
    }
    candidate_details = {
        "name": "Debug Candidate",
        "experience": "3 years",
        "skills": "Python"
    }
    history = [{"role": "user", "parts": [transcription]}]
    try:
        ai_response = await asyncio.wait_for(
            asyncio.to_thread(voice_service.get_response, history, job_details, candidate_details),
            timeout=45.0
        )
        llm_elapsed = round(time.time() - t2, 2)
        clean_response = ai_response.replace("[END_INTERVIEW]", "").strip()
        logger.info(f"[DEBUG/PIPELINE]   LLM ✓ | elapsed={llm_elapsed}s | response='{clean_response[:80]}'")
        result["stages"]["llm"] = {
            "status": "ok",
            "ai_response": clean_response,
            "elapsed_seconds": llm_elapsed,
            "end_interview_signal": "[END_INTERVIEW]" in ai_response
        }
    except asyncio.TimeoutError:
        logger.error("[DEBUG/PIPELINE] ✗ LLM timed out after 45s")
        result["status"] = "error"
        result["stages"]["llm"] = {"status": "error", "error": "Gemini API timeout (45s)"}
        result["stages"]["tts"] = {"status": "skipped"}
        return result
    except Exception as e:
        logger.error(f"[DEBUG/PIPELINE] ✗ LLM failed: {e}")
        result["status"] = "error"
        result["stages"]["llm"] = {"status": "error", "error": str(e)}
        result["stages"]["tts"] = {"status": "skipped"}
        return result

    # ── Stage 3: TTS ──────────────────────────────────────────────
    logger.info("[DEBUG/PIPELINE]   Stage 3/3: TTS (edge-tts)")
    t3 = time.time()
    try:
        communicate = edge_tts.Communicate(clean_response, "en-US-ChristopherNeural")
        audio_buffer = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.extend(chunk["data"])
        tts_elapsed = round(time.time() - t3, 2)
        audio_b64 = base64.b64encode(bytes(audio_buffer)).decode("utf-8")
        logger.info(f"[DEBUG/PIPELINE]   TTS ✓ | elapsed={tts_elapsed}s | audio={len(audio_buffer):,} bytes")
        result["stages"]["tts"] = {
            "status": "ok",
            "elapsed_seconds": tts_elapsed,
            "audio_size_bytes": len(audio_buffer),
            "audio_base64_mp3": audio_b64
        }
    except Exception as e:
        logger.error(f"[DEBUG/PIPELINE] ✗ TTS failed: {e}")
        result["status"] = "partial"
        result["stages"]["tts"] = {"status": "error", "error": str(e)}

    total_elapsed = round(time.time() - t_total, 2)
    result["total_elapsed_seconds"] = total_elapsed
    logger.info(f"[DEBUG/PIPELINE] ✓ Complete | total={total_elapsed}s")
    logger.info("━" * 60)
    return result


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
