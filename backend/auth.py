from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("interviewer.auth")

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password, hashed_password):
    result = pwd_context.verify(plain_password, hashed_password)
    logger.debug(f"[Auth] Password verification: {'MATCH' if result else 'MISMATCH'}")
    return result


def get_password_hash(password):
    hashed = pwd_context.hash(password)
    logger.debug("[Auth] Password hashed successfully")
    return hashed


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    logger.info(f"[Auth] Token created: sub={data.get('sub')} role={data.get('role')} expires_in={ACCESS_TOKEN_EXPIRE_MINUTES}min")
    return encoded_jwt


def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        logger.debug(f"[Auth] Token decoded: sub={payload.get('sub')} role={payload.get('role')}")
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("[Auth] Token EXPIRED")
        raise
    except jwt.JWTError as e:
        logger.warning(f"[Auth] Token INVALID: {type(e).__name__}: {e}")
        raise
