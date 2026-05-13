"""
Auth router — login, register, me, logout.
"""
from __future__ import annotations

import asyncio
import random
import string
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infra.config.settings import settings
from infra.errors import AppException, ErrorCodes
from infra.notifications.mailer import notify_admin_new_registration
from infra.observability.logger import get_logger
from infra.storage.database import db_session_dependency as get_db
from infra.storage.models import User

logger = get_logger(__name__)
router = APIRouter()

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: str
    password: Optional[str] = None
    display_name: Optional[str] = None


class RegisterResponse(BaseModel):
    message: str
    email: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    display_name: Optional[str] = None
    role: Optional[str] = None


class UserMe(BaseModel):
    user_id: str
    email: str
    display_name: Optional[str] = None
    is_superuser: bool = False
    role: str = "user"
    status: str = "active"
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hash(password: str) -> str:
    return pwd_ctx.hash(password)


def _verify(plain: str, hashed: str | None) -> bool:
    if hashed is None:
        return False
    return pwd_ctx.verify(plain, hashed)


def _create_token(user_id: str, email: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode(
        {"sub": user_id, "email": email, "exp": expire},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _generate_temp_password() -> str:
    digits = "".join(random.choices(string.digits, k=6))
    return f"{settings.password_prefix}{digits}"


def _check_user_active(user: User) -> None:
    if user.status == "pending":
        raise AppException(ErrorCodes.REGISTRATION_PENDING.code)
    if user.status == "disabled":
        raise AppException(ErrorCodes.REGISTRATION_DISABLED_ACCOUNT.code)


def _validate_email_domain(email: str) -> None:
    domain = email.split("@")[-1].lower() if "@" in email else ""
    allowed = settings.registration_allowed_email_domain.strip().lower()
    if domain != allowed:
        raise AppException(ErrorCodes.REGISTRATION_EMAIL_DOMAIN_DENIED.code)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id: str = payload.get("sub", "")
    except JWTError:
        raise AppException(ErrorCodes.AUTH_INTERNAL_ERROR.code, message="Invalid token")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or user.status != "active":
        raise AppException(ErrorCodes.AUTH_INTERNAL_ERROR.code, message="User not found")
    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/auth/register", response_model=RegisterResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)) -> RegisterResponse:
    if not settings.registration_enabled:
        raise AppException(ErrorCodes.REGISTRATION_DISABLED.code)

    email = (req.email or "").strip().lower()
    if not email:
        raise AppException(ErrorCodes.PARAM_INVALID.code, message="Email is required")

    _validate_email_domain(email)

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise AppException(ErrorCodes.RESOURCE_EXISTS.code, message="Email already registered")

    user = User(
        id=str(uuid.uuid4()),
        email=email,
        hashed_password=None,
        display_name=req.display_name or email.split("@")[0],
        status="pending",
        role="user",
    )
    db.add(user)
    await db.commit()

    try:
        asyncio.create_task(notify_admin_new_registration(email, req.display_name or ""))
    except Exception:
        logger.warning("Failed to schedule admin notification", email=email)

    logger.info("User registered (pending approval)", email=user.email)
    return RegisterResponse(
        message="注册申请已提交，请耐心等待管理员审核。审核结果将发送至您的邮箱。",
        email=user.email,
    )


@router.post("/auth/token", response_model=LoginResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    email = (form.username or "").strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise AppException(ErrorCodes.AUTH_INTERNAL_ERROR.code, message="Invalid credentials")
    _check_user_active(user)
    if not _verify(form.password, user.hashed_password):
        raise AppException(ErrorCodes.AUTH_INTERNAL_ERROR.code, message="Invalid credentials")
    token = _create_token(user.id, user.email)
    logger.info("User logged in", email=user.email)
    return LoginResponse(
        access_token=token, user_id=user.id,
        email=user.email, display_name=user.display_name,
        role=user.role,
    )


@router.post("/auth/login", response_model=LoginResponse)
async def login_json(
    req: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """JSON login endpoint (alternative to OAuth2 form)."""
    email = (req.email or "").strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise AppException(ErrorCodes.AUTH_INTERNAL_ERROR.code, message="Invalid credentials")
    _check_user_active(user)
    if not _verify(req.password, user.hashed_password):
        raise AppException(ErrorCodes.AUTH_INTERNAL_ERROR.code, message="Invalid credentials")
    token = _create_token(user.id, user.email)
    return LoginResponse(
        access_token=token, user_id=user.id,
        email=user.email, display_name=user.display_name,
        role=user.role,
    )


@router.get("/auth/me", response_model=UserMe)
async def me(current_user: User = Depends(get_current_user)) -> UserMe:
    return UserMe(
        user_id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        is_superuser=current_user.is_superuser,
        role=current_user.role,
        status=current_user.status,
        created_at=current_user.created_at.isoformat(),
    )
