"""Authoritative ticket triage workflow, SLA computation, RBAC checks, and audit mutations."""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlmodel import Session, select

from backend.models import (
    AuditEvent,
    SlaPolicy,
    SupportGroup,
    Ticket,
    TicketCategory,
    TicketPriority,
    TicketStatus,
    User,
    UserRole,
    utc_now,
)

DEFAULT_SLA_TARGETS: dict[TicketPriority, tuple[int, int]] = {
    TicketPriority.URGENT: (15, 240),
    TicketPriority.HIGH: (30, 720),
    TicketPriority.MEDIUM: (60, 1440),
    TicketPriority.LOW: (240, 4320),
}

PRIORITY_ORDER: dict[TicketPriority, int] = {
    TicketPriority.URGENT: 0,
    TicketPriority.HIGH: 1,
    TicketPriority.MEDIUM: 2,
    TicketPriority.LOW: 3,
}

ALLOWED_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.OPEN: {
        TicketStatus.IN_PROGRESS,
        TicketStatus.WAITING_CUSTOMER,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.IN_PROGRESS: {
        TicketStatus.OPEN,
        TicketStatus.WAITING_CUSTOMER,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.WAITING_CUSTOMER: {
        TicketStatus.IN_PROGRESS,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.RESOLVED: {
        TicketStatus.CLOSED,
        TicketStatus.IN_PROGRESS,
    },
    TicketStatus.CLOSED: {
        TicketStatus.IN_PROGRESS,
    },
}


def ensure_utc(dt: datetime) -> datetime:
    """Normalize naive SQLite datetimes to UTC for safe arithmetic."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def resolve_sla_minutes(session: Session | None, priority: TicketPriority) -> tuple[int, int]:
    """Read configured SLA (ack_minutes, resolve_minutes) or return safe default."""
    if session is not None:
        policy = session.exec(select(SlaPolicy).where(SlaPolicy.priority == priority)).first()
        if policy:
            return policy.target_ack_minutes, policy.target_resolve_minutes
    return DEFAULT_SLA_TARGETS[priority]


def compute_sla_deadline(
    priority: TicketPriority,
    created_at: datetime,
    session: Session | None = None,
) -> datetime:
    """Calculate SLA due timestamp from priority target resolution minutes."""
    _, resolve_minutes = resolve_sla_minutes(session, priority)
    return ensure_utc(created_at) + timedelta(minutes=resolve_minutes)


def is_staff(user: User) -> bool:
    """Return True when the user holds AGENT or ADMIN privileges."""
    return user.role in {UserRole.AGENT, UserRole.ADMIN}


def assert_ticket_access(user: User, ticket: Ticket) -> None:
    """Raise 403 if a customer attempts to read or mutate another user's ticket."""
    if is_staff(user):
        return
    if ticket.created_by_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customers may only access their own support tickets.",
        )


def validate_status_transition(current: TicketStatus, target: TicketStatus) -> None:
    """Reject illegal lifecycle state transitions with HTTP 400."""
    if current == target:
        return
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot transition ticket from {current.value} to {target.value}.",
        )


def record_audit_event(
    session: Session,
    *,
    ticket_id: int,
    actor_id: int,
    event_type: str,
    field_name: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> AuditEvent:
    """Persist a structured audit log event onto the current database session."""
    event = AuditEvent(
        ticket_id=ticket_id,
        actor_id=actor_id,
        event_type=event_type,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
    )
    session.add(event)
    return event


def apply_ticket_patch(
    session: Session,
    ticket: Ticket,
    *,
    actor: User,
    users: dict[int, User],
    groups: dict[int, SupportGroup],
    title: str | None = None,
    description: str | None = None,
    status_val: TicketStatus | None = None,
    priority_val: TicketPriority | None = None,
    category_val: TicketCategory | None = None,
    assigned_to_id: int | None = None,
    unassign: bool = False,
    group_id: int | None = None,
    clear_group: bool = False,
) -> bool:
    """Apply validated ticket triage/metadata updates and record field-level audit events."""
    now = utc_now()
    changes: list[tuple[str, str | None, str | None]] = []

    if title is not None:
        cleaned_title = title.strip()
        if cleaned_title and cleaned_title != ticket.title:
            changes.append(("title", ticket.title[:120], cleaned_title[:120]))
            ticket.title = cleaned_title

    if description is not None:
        cleaned_desc = description.strip()
        if cleaned_desc and cleaned_desc != ticket.description:
            changes.append(("description", ticket.description[:80], cleaned_desc[:80]))
            ticket.description = cleaned_desc

    if status_val is not None and status_val != ticket.status:
        validate_status_transition(ticket.status, status_val)
        changes.append(("status", ticket.status.value, status_val.value))
        ticket.status = status_val
        if ticket.acknowledged_at is None and status_val != TicketStatus.OPEN:
            ticket.acknowledged_at = now
        if status_val == TicketStatus.RESOLVED:
            ticket.resolved_at = now
        elif status_val == TicketStatus.CLOSED:
            ticket.closed_at = now
            if ticket.resolved_at is None:
                ticket.resolved_at = now
        elif status_val == TicketStatus.IN_PROGRESS:
            ticket.closed_at = None

    if priority_val is not None and priority_val != ticket.priority:
        changes.append(("priority", ticket.priority.value, priority_val.value))
        ticket.priority = priority_val
        ticket.sla_due_at = compute_sla_deadline(priority_val, ticket.created_at, session)

    if category_val is not None and category_val != ticket.category:
        changes.append(("category", ticket.category.value, category_val.value))
        ticket.category = category_val

    if unassign and ticket.assigned_to_id is not None:
        old_name = users[ticket.assigned_to_id].full_name if ticket.assigned_to_id in users else str(ticket.assigned_to_id)
        changes.append(("assigned_to", old_name, "Unassigned"))
        ticket.assigned_to_id = None
    elif assigned_to_id is not None and assigned_to_id != ticket.assigned_to_id:
        assignee = users.get(assigned_to_id)
        if not assignee or not is_staff(assignee):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tickets may only be assigned to active AGENT or ADMIN users.",
            )
        old_name = (
            users[ticket.assigned_to_id].full_name
            if ticket.assigned_to_id and ticket.assigned_to_id in users
            else "Unassigned"
        )
        changes.append(("assigned_to", old_name, assignee.full_name))
        ticket.assigned_to_id = assignee.id
        if ticket.acknowledged_at is None:
            ticket.acknowledged_at = now

    if clear_group and ticket.group_id is not None:
        old_g = groups[ticket.group_id].name if ticket.group_id in groups else str(ticket.group_id)
        changes.append(("group", old_g, "Unassigned"))
        ticket.group_id = None
    elif group_id is not None and group_id != ticket.group_id:
        target_group = groups.get(group_id)
        if not target_group:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Support group not found.")
        old_g = groups[ticket.group_id].name if ticket.group_id and ticket.group_id in groups else "Unassigned"
        changes.append(("group", old_g, target_group.name))
        ticket.group_id = target_group.id

    if not changes:
        return False

    ticket.updated_at = now
    session.add(ticket)
    for field_name, old_val, new_val in changes:
        record_audit_event(
            session,
            ticket_id=ticket.id,
            actor_id=actor.id,
            event_type="UPDATED",
            field_name=field_name,
            old_value=old_val,
            new_value=new_val,
        )
    return True
