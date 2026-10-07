"""
auth.py
-------
ระบบความปลอดภัยและการยืนยันตัวตน:
- เข้ารหัสและตรวจสอบรหัสผ่านด้วย bcrypt
- ออกและตรวจสอบ JWT access token (HS256)
- FastAPI dependencies สำหรับดึงข้อมูล current_user และตรวจสอบสิทธิ์ admin/instructor
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.dynamodb_service import get_user_by_id
from app.models import UserInDB, UserRole

security_bearer = HTTPBearer(auto_error=False)


# ==========================================
# PASSWORD HASHING
# ==========================================

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except Exception:
        return False


# ==========================================
# JWT TOKENS
# ==========================================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    settings = get_settings()
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ==========================================
# FASTAPI DEPENDENCIES
# ==========================================

async def get_current_user(
    request: Request,
    bearer_auth: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
    access_token_cookie: Optional[str] = Cookie(None, alias="access_token"),
) -> UserInDB:
    token: Optional[str] = None

    if bearer_auth and bearer_auth.credentials:
        token = bearer_auth.credentials
    elif access_token_cookie:
        token = access_token_cookie

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a Bearer token or sign-in cookie.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identity subject.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_dict = get_user_by_id(user_id)
    if not user_dict:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found in system.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return UserInDB(**user_dict)


async def get_current_admin_user(
    current_user: UserInDB = Depends(get_current_user),
) -> UserInDB:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required to perform this action.",
        )
    return current_user


async def get_current_instructor_or_admin(
    current_user: UserInDB = Depends(get_current_user),
) -> UserInDB:
    if current_user.role not in [UserRole.INSTRUCTOR, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Instructor or Admin privileges required.",
        )
    return current_user


async def get_current_instructor_user(
    current_user: UserInDB = Depends(get_current_user),
) -> UserInDB:
    """เฉพาะ Instructor (Admin สร้างแบบฝึกหัดไม่ได้)"""
    if current_user.role != UserRole.INSTRUCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only instructors can create exercises.",
        )
    return current_user