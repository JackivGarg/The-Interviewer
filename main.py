from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from database import engine, Base, SessionLocal
from models import CEO, HR, Candidate
from schemas import (
    HRCreate, HRResponse, CandidateCreate, CandidateResponse,
    LoginRequest, TokenResponse
)
from auth import (
    verify_password, get_password_hash, create_access_token,
    decode_token
)
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = decode_token(token)
        email = payload.get("sub")
        role = payload.get("role")
        if email is None or role is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    if role == "ceo":
        user = db.query(CEO).filter(CEO.name == "Jackiv Garg").first()
    elif role == "hr":
        user = db.query(HR).filter(HR.email == email).first()
    elif role == "candidate":
        user = db.query(Candidate).filter(Candidate.email == email).first()
    else:
        raise HTTPException(status_code=401, detail="Invalid role")
    
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user, role


@app.on_event("startup")
def create_tables():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    existing_ceo = db.query(CEO).filter(CEO.name == "Jackiv Garg").first()
    if not existing_ceo:
        hashed_password = pwd_context.hash("admin@123")
        ceo = CEO(name="Jackiv Garg", password=hashed_password)
        db.add(ceo)
        db.commit()
    db.close()


@app.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    ceo = db.query(CEO).filter(CEO.name == "Jackiv Garg").first()
    if ceo and verify_password(request.password, ceo.password):
        token = create_access_token({"sub": ceo.name, "role": "ceo"})
        return TokenResponse(access_token=token, token_type="bearer", role="ceo")
    
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
def login_form(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    ceo = db.query(CEO).filter(CEO.name == "Jackiv Garg").first()
    if ceo and verify_password(form_data.password, ceo.password):
        token = create_access_token({"sub": ceo.name, "role": "ceo"})
        return TokenResponse(access_token=token, token_type="bearer", role="ceo")
    
    hr = db.query(HR).filter(HR.email == form_data.username).first()
    if hr and verify_password(form_data.password, hr.password):
        token = create_access_token({"sub": hr.email, "role": "hr"})
        return TokenResponse(access_token=token, token_type="bearer", role="hr")
    
    candidate = db.query(Candidate).filter(Candidate.email == form_data.username).first()
    if candidate and verify_password(form_data.password, candidate.password):
        token = create_access_token({"sub": candidate.email, "role": "candidate"})
        return TokenResponse(access_token=token, token_type="bearer", role="candidate")
    
    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.post("/signup", response_model=CandidateResponse)
def signup(candidate: CandidateCreate, db: Session = Depends(get_db)):
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


@app.post("/hr", response_model=HRResponse)
def create_hr(hr: HRCreate, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
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


@app.get("/candidates", response_model=list[CandidateResponse])
def get_candidates(db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    user, role = current_user
    return db.query(Candidate).all()
