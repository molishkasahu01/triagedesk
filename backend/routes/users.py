"""User directory and admin role-management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import User, UserRole
from backend.routes.auth import to_user_public
from backend.schemas import RoleUpdateRequest, UserPublic
from backend.security import require_roles

router = APIRouter(prefix="/api/v1/users", tags=["Users & RBAC"])


@router.get("/agents", response_model=list[UserPublic])
def list_support_staff(
    _: User = Depends(require_roles(UserRole.AGENT, UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[UserPublic]:
    """List active AGENT and ADMIN accounts available for ticket assignment."""
    staff = session.exec(
        select(User).where(
            User.is_active.is_(True),
            User.role.in_([UserRole.AGENT, UserRole.ADMIN]),
        )
    ).all()
    return [to_user_public(u) for u in staff]


@router.get("", response_model=list[UserPublic])
def list_all_users(
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[UserPublic]:
    """List all registered users (ADMIN only)."""
    users = session.exec(select(User).order_by(User.id.asc())).all()
    return [to_user_public(u) for u in users]


@router.patch("/{user_id}/role", response_model=UserPublic)
def update_user_role(
    user_id: int,
    payload: RoleUpdateRequest,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> UserPublic:
    """Promote or demote a user role cleanly (ADMIN only)."""
    target = session.exec(select(User).where(User.id == user_id)).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    target.role = payload.role
    session.add(target)
    session.commit()
    session.refresh(target)
    return to_user_public(target)
