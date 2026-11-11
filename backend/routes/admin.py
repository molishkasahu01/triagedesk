"""Administration endpoints for support groups, SLA policies, and API keys."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import (
    ApiKey,
    SlaPolicy,
    SupportGroup,
    TicketPriority,
    User,
    UserRole,
    utc_now,
)
from backend.schemas import (
    ApiKeyCreatedPublic,
    ApiKeyCreateRequest,
    ApiKeyPublic,
    SlaPolicyPublic,
    SlaPolicyUpdateRequest,
    SupportGroupCreateRequest,
    SupportGroupPublic,
)
from backend.security import generate_api_key_pair, get_current_user, require_roles
from backend.workflow import DEFAULT_SLA_TARGETS, is_staff

router = APIRouter(prefix="/api/v1", tags=["Groups, SLA & API Keys"])


@router.get("/groups", response_model=list[SupportGroupPublic])
def list_groups(
    _: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[SupportGroupPublic]:
    """List configured support routing groups."""
    groups = session.exec(select(SupportGroup).order_by(SupportGroup.name.asc())).all()
    return [
        SupportGroupPublic(
            id=g.id,
            name=g.name,
            description=g.description,
            created_at=g.created_at,
        )
        for g in groups
    ]


@router.post("/groups", response_model=SupportGroupPublic, status_code=status.HTTP_201_CREATED)
def create_group(
    payload: SupportGroupCreateRequest,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> SupportGroupPublic:
    """Create a new functional support group (ADMIN only)."""
    clean_name = payload.name.strip()
    if session.exec(select(SupportGroup).where(SupportGroup.name == clean_name)).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Group '{clean_name}' already exists.",
        )
    group = SupportGroup(name=clean_name, description=payload.description.strip())
    session.add(group)
    session.commit()
    session.refresh(group)
    return SupportGroupPublic(
        id=group.id,
        name=group.name,
        description=group.description,
        created_at=group.created_at,
    )


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: int,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> None:
    """Delete a support group (ADMIN only)."""
    group = session.exec(select(SupportGroup).where(SupportGroup.id == group_id)).first()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found.")
    session.delete(group)
    session.commit()


@router.get("/sla", response_model=list[SlaPolicyPublic])
def list_sla_policies(
    _: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[SlaPolicyPublic]:
    """Return SLA targets for all four ticket priorities."""
    stored = {p.priority: p for p in session.exec(select(SlaPolicy)).all()}
    result: list[SlaPolicyPublic] = []
    for prio in (TicketPriority.URGENT, TicketPriority.HIGH, TicketPriority.MEDIUM, TicketPriority.LOW):
        if prio in stored:
            p = stored[prio]
            result.append(
                SlaPolicyPublic(
                    priority=p.priority,
                    target_ack_minutes=p.target_ack_minutes,
                    target_resolve_minutes=p.target_resolve_minutes,
                    updated_at=p.updated_at,
                )
            )
        else:
            ack_m, res_m = DEFAULT_SLA_TARGETS[prio]
            result.append(
                SlaPolicyPublic(
                    priority=prio,
                    target_ack_minutes=ack_m,
                    target_resolve_minutes=res_m,
                    updated_at=utc_now(),
                )
            )
    return result


@router.put("/sla/{priority}", response_model=SlaPolicyPublic)
def update_sla_policy(
    priority: TicketPriority,
    payload: SlaPolicyUpdateRequest,
    _: User = Depends(require_roles(UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> SlaPolicyPublic:
    """Update SLA acknowledgement and resolution targets for a priority (ADMIN only)."""
    policy = session.exec(select(SlaPolicy).where(SlaPolicy.priority == priority)).first()
    now = utc_now()
    if not policy:
        policy = SlaPolicy(
            priority=priority,
            target_ack_minutes=payload.target_ack_minutes,
            target_resolve_minutes=payload.target_resolve_minutes,
            updated_at=now,
        )
    else:
        policy.target_ack_minutes = payload.target_ack_minutes
        policy.target_resolve_minutes = payload.target_resolve_minutes
        policy.updated_at = now
    session.add(policy)
    session.commit()
    session.refresh(policy)
    return SlaPolicyPublic(
        priority=policy.priority,
        target_ack_minutes=policy.target_ack_minutes,
        target_resolve_minutes=policy.target_resolve_minutes,
        updated_at=policy.updated_at,
    )


@router.get("/api-keys", response_model=list[ApiKeyPublic])
def list_api_keys(
    current_user: User = Depends(require_roles(UserRole.AGENT, UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[ApiKeyPublic]:
    """List programmatic API keys visible to staff (all keys for ADMIN, own keys for AGENT)."""
    stmt = select(ApiKey).order_by(ApiKey.id.desc())
    if current_user.role != UserRole.ADMIN:
        stmt = stmt.where(ApiKey.user_id == current_user.id)
    keys = session.exec(stmt).all()
    users = {u.id: u for u in session.exec(select(User)).all() if u.id is not None}
    return [
        ApiKeyPublic(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            user_id=k.user_id,
            owner_name=users[k.user_id].full_name if k.user_id in users else "Unknown",
            is_active=k.is_active,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
        )
        for k in keys
    ]


@router.post("/api-keys", response_model=ApiKeyCreatedPublic, status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: ApiKeyCreateRequest,
    current_user: User = Depends(require_roles(UserRole.AGENT, UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> ApiKeyCreatedPublic:
    """Create a hashed API key for script/automation access under the caller's RBAC role."""
    raw_key, prefix, digest = generate_api_key_pair()
    record = ApiKey(
        name=payload.name.strip(),
        key_prefix=prefix,
        key_hash=digest,
        user_id=current_user.id,
        is_active=True,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return ApiKeyCreatedPublic(
        id=record.id,
        name=record.name,
        key_prefix=record.key_prefix,
        user_id=record.user_id,
        owner_name=current_user.full_name,
        is_active=record.is_active,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        raw_key=raw_key,
    )


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(
    key_id: int,
    current_user: User = Depends(require_roles(UserRole.AGENT, UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> None:
    """Revoke an existing API key."""
    record = session.exec(select(ApiKey).where(ApiKey.id == key_id)).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")
    if current_user.role != UserRole.ADMIN and record.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot revoke another user's key.")
    if not is_staff(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff privileges required.")
    record.is_active = False
    session.add(record)
    session.commit()
