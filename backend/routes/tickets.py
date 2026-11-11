"""Dashboard analytics, ticket queue, bulk triage, attachments, comments, and audit history."""

from pathlib import Path
import re
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from backend.config import settings
from backend.database import get_session
from backend.models import (
    AuditEvent,
    SlaPolicy,
    SupportGroup,
    Ticket,
    TicketAttachment,
    TicketCategory,
    TicketComment,
    TicketPriority,
    TicketStatus,
    User,
    UserRole,
    utc_now,
)
from backend.schemas import (
    AttachmentPublic,
    AuditEventPublic,
    BulkTicketUpdateRequest,
    CommentCreateRequest,
    CommentPublic,
    DashboardOverviewPublic,
    PrioritySlice,
    TicketCreateRequest,
    TicketDetailPublic,
    TicketPublic,
    TicketUpdateRequest,
)
from backend.security import get_current_user, require_roles
from backend.workflow import (
    DEFAULT_SLA_TARGETS,
    PRIORITY_ORDER,
    apply_ticket_patch,
    assert_ticket_access,
    compute_sla_deadline,
    ensure_utc,
    is_staff,
    record_audit_event,
)

router = APIRouter(prefix="/api/v1", tags=["Dashboard & Tickets"])


def _lookups(
    session: Session,
) -> tuple[dict[int, User], dict[int, SupportGroup], dict[TicketPriority, tuple[int, int]]]:
    """Load users, groups, and SLA targets efficiently per request."""
    users = {u.id: u for u in session.exec(select(User)).all() if u.id is not None}
    groups = {g.id: g for g in session.exec(select(SupportGroup)).all() if g.id is not None}
    policies = dict(DEFAULT_SLA_TARGETS)
    for row in session.exec(select(SlaPolicy)).all():
        policies[row.priority] = (row.target_ack_minutes, row.target_resolve_minutes)
    return users, groups, policies


def _serialize_ticket(
    ticket: Ticket,
    users: dict[int, User],
    groups: dict[int, SupportGroup],
    policies: dict[TicketPriority, tuple[int, int]],
) -> TicketPublic:
    """Convert Ticket DB row into TicketPublic response with SLA targets & breach status."""
    creator = users.get(ticket.created_by_id)
    assignee = users.get(ticket.assigned_to_id) if ticket.assigned_to_id else None
    group = groups.get(ticket.group_id) if ticket.group_id else None
    ack_mins, resolve_mins = policies.get(ticket.priority, DEFAULT_SLA_TARGETS[ticket.priority])
    is_terminal = ticket.status in {TicketStatus.RESOLVED, TicketStatus.CLOSED}
    sla_breached = (not is_terminal) and (ensure_utc(ticket.sla_due_at) < utc_now())
    return TicketPublic(
        id=ticket.id,
        ticket_key=ticket.ticket_key,
        title=ticket.title,
        description=ticket.description,
        category=ticket.category,
        priority=ticket.priority,
        status=ticket.status,
        sla_due_at=ticket.sla_due_at,
        sla_breached=sla_breached,
        target_ack_minutes=ack_mins,
        target_resolve_minutes=resolve_mins,
        created_by_id=ticket.created_by_id,
        created_by_name=creator.full_name if creator else "Unknown User",
        assigned_to_id=ticket.assigned_to_id,
        assigned_to_name=assignee.full_name if assignee else None,
        group_id=ticket.group_id,
        group_name=group.name if group else None,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        acknowledged_at=ticket.acknowledged_at,
        resolved_at=ticket.resolved_at,
        closed_at=ticket.closed_at,
    )


def _next_ticket_key(session: Session) -> str:
    """Generate sequential human-readable ticket key (TD-1001+)."""
    latest = session.exec(select(Ticket).order_by(Ticket.id.desc())).first()
    next_num = 1001 + (latest.id if latest and latest.id else 0)
    return f"TD-{next_num}"


def _load_ticket_or_404(session: Session, ticket_id: int) -> Ticket:
    """Fetch ticket by ID or raise HTTP 404."""
    ticket = session.exec(select(Ticket).where(Ticket.id == ticket_id)).first()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found.")
    return ticket


def _safe_filename(raw_name: str) -> str:
    """Strip path traversal characters while keeping original filename readable."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(raw_name).name).strip("._")
    return cleaned or "attachment.bin"


@router.get("/dashboard", response_model=DashboardOverviewPublic)
def read_dashboard_overview(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> DashboardOverviewPublic:
    """Compute service-desk KPIs, MTTA/MTTR averages, priority breakdown, and recent activity."""
    stmt = select(Ticket)
    if not is_staff(current_user):
        stmt = stmt.where(Ticket.created_by_id == current_user.id)
    tickets = session.exec(stmt).all()
    ticket_map = {t.id: t for t in tickets if t.id is not None}
    now = utc_now()

    ack_deltas = [
        max(0.0, (ensure_utc(t.acknowledged_at) - ensure_utc(t.created_at)).total_seconds() / 60.0)
        for t in tickets
        if t.acknowledged_at is not None
    ]
    res_deltas = [
        max(0.0, (ensure_utc(t.resolved_at) - ensure_utc(t.created_at)).total_seconds() / 60.0)
        for t in tickets
        if t.resolved_at is not None
    ]

    total = len(tickets)
    slices: list[PrioritySlice] = []
    for prio in (TicketPriority.URGENT, TicketPriority.HIGH, TicketPriority.MEDIUM, TicketPriority.LOW):
        cnt = sum(1 for t in tickets if t.priority == prio)
        pct = round((cnt / total) * 100.0, 1) if total else 0.0
        slices.append(PrioritySlice(priority=prio, count=cnt, percent=pct))

    users, _, _ = _lookups(session)
    audit_stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    raw_events = session.exec(audit_stmt).all()
    recent: list[AuditEventPublic] = []
    for ev in raw_events:
        parent = ticket_map.get(ev.ticket_id)
        if not parent:
            continue
        recent.append(
            AuditEventPublic(
                id=ev.id,
                ticket_id=ev.ticket_id,
                ticket_key=parent.ticket_key,
                actor_id=ev.actor_id,
                actor_name=users[ev.actor_id].full_name if ev.actor_id in users else "System",
                event_type=ev.event_type,
                field_name=ev.field_name,
                old_value=ev.old_value,
                new_value=ev.new_value,
                created_at=ev.created_at,
            )
        )
        if len(recent) >= 12:
            break

    return DashboardOverviewPublic(
        total=total,
        open_count=sum(1 for t in tickets if t.status == TicketStatus.OPEN),
        in_progress_count=sum(1 for t in tickets if t.status == TicketStatus.IN_PROGRESS),
        waiting_customer_count=sum(1 for t in tickets if t.status == TicketStatus.WAITING_CUSTOMER),
        resolved_or_closed_count=sum(
            1 for t in tickets if t.status in {TicketStatus.RESOLVED, TicketStatus.CLOSED}
        ),
        urgent_count=sum(
            1
            for t in tickets
            if t.priority == TicketPriority.URGENT
            and t.status not in {TicketStatus.RESOLVED, TicketStatus.CLOSED}
        ),
        unassigned_count=sum(
            1
            for t in tickets
            if t.assigned_to_id is None
            and t.status not in {TicketStatus.RESOLVED, TicketStatus.CLOSED}
        ),
        sla_breached_count=sum(
            1
            for t in tickets
            if t.status not in {TicketStatus.RESOLVED, TicketStatus.CLOSED}
            and ensure_utc(t.sla_due_at) < now
        ),
        mtta_minutes=round(sum(ack_deltas) / len(ack_deltas)) if ack_deltas else None,
        mttr_minutes=round(sum(res_deltas) / len(res_deltas)) if res_deltas else None,
        priority_distribution=slices,
        recent_activity=recent,
    )


@router.get("/tickets", response_model=list[TicketPublic])
def list_tickets(
    status_filter: TicketStatus | None = Query(default=None, alias="status"),
    priority_filter: TicketPriority | None = Query(default=None, alias="priority"),
    category_filter: TicketCategory | None = Query(default=None, alias="category"),
    group_id: int | None = Query(default=None),
    assigned_to_me: bool = Query(default=False),
    q: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[TicketPublic]:
    """Return priority-sorted tickets scoped to role, searchable across titles, descriptions, and permitted notes."""
    stmt = select(Ticket)
    if not is_staff(current_user):
        stmt = stmt.where(Ticket.created_by_id == current_user.id)
    if status_filter is not None:
        stmt = stmt.where(Ticket.status == status_filter)
    if priority_filter is not None:
        stmt = stmt.where(Ticket.priority == priority_filter)
    if category_filter is not None:
        stmt = stmt.where(Ticket.category == category_filter)
    if group_id is not None:
        stmt = stmt.where(Ticket.group_id == group_id)
    if assigned_to_me:
        stmt = stmt.where(Ticket.assigned_to_id == current_user.id)

    tickets = session.exec(stmt).all()
    if q:
        needle = q.strip().lower()
        note_stmt = select(TicketComment)
        if not is_staff(current_user):
            note_stmt = note_stmt.where(TicketComment.is_internal.is_(False))
        matching_note_ticket_ids = {
            c.ticket_id for c in session.exec(note_stmt).all() if needle in c.body.lower()
        }
        tickets = [
            t
            for t in tickets
            if needle in t.title.lower()
            or needle in t.description.lower()
            or needle in t.ticket_key.lower()
            or (t.id in matching_note_ticket_ids)
        ]

    tickets.sort(
        key=lambda t: (
            t.status in {TicketStatus.RESOLVED, TicketStatus.CLOSED},
            PRIORITY_ORDER[t.priority],
            ensure_utc(t.sla_due_at),
        )
    )
    users, groups, policies = _lookups(session)
    return [_serialize_ticket(t, users, groups, policies) for t in tickets]


@router.post("/tickets", response_model=TicketPublic, status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: TicketCreateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TicketPublic:
    """Create a support ticket and write the initial audit event."""
    users, groups, policies = _lookups(session)
    if payload.group_id is not None and payload.group_id not in groups:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Support group not found.")

    now = utc_now()
    ticket = Ticket(
        ticket_key=_next_ticket_key(session),
        title=payload.title.strip(),
        description=payload.description.strip(),
        category=payload.category,
        priority=payload.priority,
        status=TicketStatus.OPEN,
        sla_due_at=compute_sla_deadline(payload.priority, now, session),
        created_by_id=current_user.id,
        group_id=payload.group_id,
        created_at=now,
        updated_at=now,
    )
    session.add(ticket)
    session.commit()
    session.refresh(ticket)

    record_audit_event(
        session,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        event_type="CREATED",
        field_name="status",
        old_value=None,
        new_value=TicketStatus.OPEN.value,
    )
    session.commit()
    return _serialize_ticket(ticket, users, groups, policies)


@router.post("/tickets/bulk", response_model=list[TicketPublic])
def bulk_update_tickets(
    payload: BulkTicketUpdateRequest,
    current_user: User = Depends(require_roles(UserRole.AGENT, UserRole.ADMIN)),
    session: Session = Depends(get_session),
) -> list[TicketPublic]:
    """Apply status, priority, assignee, or group updates across multiple selected tickets."""
    users, groups, policies = _lookups(session)
    updated_tickets: list[Ticket] = []
    for tid in payload.ticket_ids:
        ticket = _load_ticket_or_404(session, tid)
        apply_ticket_patch(
            session,
            ticket,
            actor=current_user,
            users=users,
            groups=groups,
            status_val=payload.status,
            priority_val=payload.priority,
            assigned_to_id=payload.assigned_to_id,
            unassign=payload.unassign,
            group_id=payload.group_id,
            clear_group=payload.clear_group,
        )
        updated_tickets.append(ticket)

    session.commit()
    for t in updated_tickets:
        session.refresh(t)
    return [_serialize_ticket(t, users, groups, policies) for t in updated_tickets]


@router.get("/tickets/{ticket_id}", response_model=TicketDetailPublic)
def read_ticket_detail(
    ticket_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TicketDetailPublic:
    """Fetch full ticket detail, comments, attachments, and chronological audit log."""
    ticket = _load_ticket_or_404(session, ticket_id)
    assert_ticket_access(current_user, ticket)

    users, groups, policies = _lookups(session)
    comment_stmt = select(TicketComment).where(TicketComment.ticket_id == ticket.id)
    if not is_staff(current_user):
        comment_stmt = comment_stmt.where(TicketComment.is_internal.is_(False))
    comments = session.exec(comment_stmt.order_by(TicketComment.created_at.asc())).all()

    attachments = session.exec(
        select(TicketAttachment)
        .where(TicketAttachment.ticket_id == ticket.id)
        .order_by(TicketAttachment.created_at.desc())
    ).all()

    audit_events = session.exec(
        select(AuditEvent)
        .where(AuditEvent.ticket_id == ticket.id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    ).all()

    base = _serialize_ticket(ticket, users, groups, policies)
    return TicketDetailPublic(
        **base.model_dump(),
        comments=[
            CommentPublic(
                id=c.id,
                ticket_id=c.ticket_id,
                author_id=c.author_id,
                author_name=users[c.author_id].full_name if c.author_id in users else "Unknown",
                author_role=users[c.author_id].role if c.author_id in users else UserRole.CUSTOMER,
                body=c.body,
                is_internal=c.is_internal,
                created_at=c.created_at,
            )
            for c in comments
        ],
        attachments=[
            AttachmentPublic(
                id=a.id,
                ticket_id=a.ticket_id,
                uploaded_by_id=a.uploaded_by_id,
                uploaded_by_name=users[a.uploaded_by_id].full_name if a.uploaded_by_id in users else "Unknown",
                original_filename=a.original_filename,
                content_type=a.content_type,
                size_bytes=a.size_bytes,
                created_at=a.created_at,
            )
            for a in attachments
        ],
        audit_events=[
            AuditEventPublic(
                id=ev.id,
                ticket_id=ev.ticket_id,
                ticket_key=ticket.ticket_key,
                actor_id=ev.actor_id,
                actor_name=users[ev.actor_id].full_name if ev.actor_id in users else "System",
                event_type=ev.event_type,
                field_name=ev.field_name,
                old_value=ev.old_value,
                new_value=ev.new_value,
                created_at=ev.created_at,
            )
            for ev in audit_events
        ],
    )


@router.patch("/tickets/{ticket_id}", response_model=TicketPublic)
def patch_ticket(
    ticket_id: int,
    payload: TicketUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TicketPublic:
    """Update ticket content or triage fields while enforcing role boundaries."""
    ticket = _load_ticket_or_404(session, ticket_id)
    assert_ticket_access(current_user, ticket)

    triage_fields_present = any(
        [
            payload.status is not None,
            payload.priority is not None,
            payload.category is not None,
            payload.assigned_to_id is not None,
            payload.unassign,
            payload.group_id is not None,
            payload.clear_group,
        ]
    )
    if triage_fields_present and not is_staff(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only support agents or admins can modify triage properties.",
        )

    users, groups, policies = _lookups(session)
    changed = apply_ticket_patch(
        session,
        ticket,
        actor=current_user,
        users=users,
        groups=groups,
        title=payload.title,
        description=payload.description,
        status_val=payload.status,
        priority_val=payload.priority,
        category_val=payload.category,
        assigned_to_id=payload.assigned_to_id,
        unassign=payload.unassign,
        group_id=payload.group_id,
        clear_group=payload.clear_group,
    )
    if changed:
        session.commit()
        session.refresh(ticket)
    return _serialize_ticket(ticket, users, groups, policies)


@router.post("/tickets/{ticket_id}/comments", response_model=CommentPublic, status_code=status.HTTP_201_CREATED)
def add_ticket_comment(
    ticket_id: int,
    payload: CommentCreateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CommentPublic:
    """Append a public reply or internal agent-only note to a ticket conversation."""
    ticket = _load_ticket_or_404(session, ticket_id)
    assert_ticket_access(current_user, ticket)

    if payload.is_internal and not is_staff(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only support agents or admins can create internal notes.",
        )

    now = utc_now()
    comment = TicketComment(
        ticket_id=ticket.id,
        author_id=current_user.id,
        body=payload.body.strip(),
        is_internal=payload.is_internal,
        created_at=now,
    )
    session.add(comment)

    if is_staff(current_user) and ticket.acknowledged_at is None:
        ticket.acknowledged_at = now

    if not is_staff(current_user) and ticket.status == TicketStatus.WAITING_CUSTOMER:
        ticket.status = TicketStatus.IN_PROGRESS
        record_audit_event(
            session,
            ticket_id=ticket.id,
            actor_id=current_user.id,
            event_type="AUTO_REOPENED",
            field_name="status",
            old_value=TicketStatus.WAITING_CUSTOMER.value,
            new_value=TicketStatus.IN_PROGRESS.value,
        )

    ticket.updated_at = now
    session.add(ticket)
    record_audit_event(
        session,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        event_type="INTERNAL_NOTE" if payload.is_internal else "COMMENTED",
        field_name="comment",
        old_value=None,
        new_value=comment.body[:120],
    )
    session.commit()
    session.refresh(comment)

    return CommentPublic(
        id=comment.id,
        ticket_id=comment.ticket_id,
        author_id=comment.author_id,
        author_name=current_user.full_name,
        author_role=current_user.role,
        body=comment.body,
        is_internal=comment.is_internal,
        created_at=comment.created_at,
    )


@router.post("/tickets/{ticket_id}/attachments", response_model=AttachmentPublic, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    ticket_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> AttachmentPublic:
    """Attach a diagnostic file or screenshot cleanly onto a ticket."""
    ticket = _load_ticket_or_404(session, ticket_id)
    assert_ticket_access(current_user, ticket)

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File exceeds 5 MB limit.")

    original = _safe_filename(file.filename or "attachment.bin")
    stored = f"{ticket.id}_{uuid.uuid4().hex[:12]}_{original}"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    target_path = settings.upload_dir / stored
    target_path.write_bytes(content)

    record = TicketAttachment(
        ticket_id=ticket.id,
        uploaded_by_id=current_user.id,
        original_filename=original,
        stored_filename=stored,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
    )
    session.add(record)
    ticket.updated_at = utc_now()
    session.add(ticket)
    record_audit_event(
        session,
        ticket_id=ticket.id,
        actor_id=current_user.id,
        event_type="ATTACHMENT_ADDED",
        field_name="attachment",
        old_value=None,
        new_value=original,
    )
    session.commit()
    session.refresh(record)

    return AttachmentPublic(
        id=record.id,
        ticket_id=record.ticket_id,
        uploaded_by_id=record.uploaded_by_id,
        uploaded_by_name=current_user.full_name,
        original_filename=record.original_filename,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
        created_at=record.created_at,
    )


@router.get("/attachments/{attachment_id}")
def download_attachment(
    attachment_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> FileResponse:
    """Download an attachment after checking parent ticket RBAC access."""
    record = session.exec(select(TicketAttachment).where(TicketAttachment.id == attachment_id)).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")
    ticket = _load_ticket_or_404(session, record.ticket_id)
    assert_ticket_access(current_user, ticket)

    path = settings.upload_dir / record.stored_filename
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored file missing.")
    return FileResponse(
        path=str(path),
        media_type=record.content_type,
        filename=record.original_filename,
    )
