"""Authentication endpoints for registration, login, and profile inspection."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import User, UserRole
from backend.schemas import LoginRequest, TokenResponse, UserPublic, UserRegisterRequest
from backend.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


def to_user_public(user: User) -> UserPublic:
    """Map database User entity to safe public response model."""
    return UserPublic(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegisterRequest, session: Session = Depends(get_session)) -> TokenResponse:
    """Register a new CUSTOMER account and issue a Bearer access token."""
    normalized_email = payload.email.strip().lower()
    if session.exec(select(User).where(User.email == normalized_email)).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        email=normalized_email,
        full_name=payload.full_name.strip(),
        role=UserRole.CUSTOMER,
        hashed_password=hash_password(payload.password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return TokenResponse(access_token=create_access_token(user), user=to_user_public(user))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, session: Session = Depends(get_session)) -> TokenResponse:
    """Authenticate an existing account and return a JWT token."""
    normalized_email = payload.email.strip().lower()
    user = session.exec(select(User).where(User.email == normalized_email)).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated.",
        )
    return TokenResponse(access_token=create_access_token(user), user=to_user_public(user))


@router.get("/me", response_model=UserPublic)
def read_me(current_user: User = Depends(get_current_user)) -> UserPublic:
    """Return the authenticated caller profile and active role."""
    return to_user_public(current_user)
