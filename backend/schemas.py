"""Pydantic API request and response contracts for TriageDesk."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from backend.models import TicketCategory, TicketPriority, TicketStatus, UserRole


class UserRegisterRequest(BaseModel):
    """Payload for self-service registration (always creates CUSTOMER accounts)."""

    email: str = Field(min_length=5, max_length=255)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    """Email and password login credentials."""

    email: str
    password: str


class RoleUpdateRequest(BaseModel):
    """Admin-only role assignment payload."""

    role: UserRole


class UserPublic(BaseModel):
    """Public user summary returned in API responses."""

    id: int
    email: str
    full_name: str
    role: UserRole
    is_active: bool


class TokenResponse(BaseModel):
    """JWT access token response paired with authenticated user info."""

    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class SupportGroupCreateRequest(BaseModel):
    """Admin payload for creating a support group/queue."""

    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=240)


class SupportGroupPublic(BaseModel):
    """Support group summary."""

    id: int
    name: str
    description: str
    created_at: datetime


class SlaPolicyUpdateRequest(BaseModel):
    """Admin update for per-priority SLA target durations."""

    target_ack_minutes: int = Field(ge=1, le=10080)
    target_resolve_minutes: int = Field(ge=5, le=43200)


class SlaPolicyPublic(BaseModel):
    """Configured SLA policy row."""

    priority: TicketPriority
    target_ack_minutes: int
    target_resolve_minutes: int
    updated_at: datetime


class ApiKeyCreateRequest(BaseModel):
    """Payload to issue a named API key."""

    name: str = Field(min_length=2, max_length=80)


class ApiKeyPublic(BaseModel):
    """Masked API key record safe for listing."""

    id: int
    name: str
    key_prefix: str
    user_id: int
    owner_name: str
    is_active: bool
    created_at: datetime
    last_used_at: Optional[datetime]


class ApiKeyCreatedPublic(ApiKeyPublic):
    """One-time response exposing raw API key secret upon creation."""

    raw_key: str


class TicketCreateRequest(BaseModel):
    """Payload to create a new support ticket."""

    title: str = Field(min_length=4, max_length=180)
    description: str = Field(min_length=8, max_length=5000)
    category: TicketCategory = TicketCategory.GENERAL
    priority: TicketPriority = TicketPriority.MEDIUM
    group_id: Optional[int] = None


class TicketUpdateRequest(BaseModel):
    """Payload for updating ticket content, triage state, group, or assignee."""

    title: Optional[str] = Field(default=None, min_length=4, max_length=180)
    description: Optional[str] = Field(default=None, min_length=8, max_length=5000)
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    category: Optional[TicketCategory] = None
    assigned_to_id: Optional[int] = None
    unassign: bool = False
    group_id: Optional[int] = None
    clear_group: bool = False


class BulkTicketUpdateRequest(BaseModel):
    """Bulk triage action payload across selected ticket IDs."""

    ticket_ids: list[int] = Field(min_length=1, max_length=100)
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    assigned_to_id: Optional[int] = None
    unassign: bool = False
    group_id: Optional[int] = None
    clear_group: bool = False


class CommentCreateRequest(BaseModel):
    """Payload to append a public reply or internal agent note."""

    body: str = Field(min_length=1, max_length=4000)
    is_internal: bool = False


class CommentPublic(BaseModel):
    """Serialized conversation entry."""

    id: int
    ticket_id: int
    author_id: int
    author_name: str
    author_role: UserRole
    body: str
    is_internal: bool
    created_at: datetime


class AttachmentPublic(BaseModel):
    """Serialized attachment metadata."""

    id: int
    ticket_id: int
    uploaded_by_id: int
    uploaded_by_name: str
    original_filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class AuditEventPublic(BaseModel):
    """Serialized audit history item with parent ticket key for dashboard activity feeds."""

    id: int
    ticket_id: int
    ticket_key: str
    actor_id: int
    actor_name: str
    event_type: str
    field_name: Optional[str]
    old_value: Optional[str]
    new_value: Optional[str]
    created_at: datetime


class TicketPublic(BaseModel):
    """Queue item summary returned by list and mutation endpoints."""

    id: int
    ticket_key: str
    title: str
    description: str
    category: TicketCategory
    priority: TicketPriority
    status: TicketStatus
    sla_due_at: datetime
    sla_breached: bool
    target_ack_minutes: int
    target_resolve_minutes: int
    created_by_id: int
    created_by_name: str
    assigned_to_id: Optional[int]
    assigned_to_name: Optional[str]
    group_id: Optional[int]
    group_name: Optional[str]
    created_at: datetime
    updated_at: datetime
    acknowledged_at: Optional[datetime]
    resolved_at: Optional[datetime]
    closed_at: Optional[datetime]


class TicketDetailPublic(TicketPublic):
    """Full ticket detail response with comments, attachments, and audit trail."""

    comments: list[CommentPublic]
    attachments: list[AttachmentPublic]
    audit_events: list[AuditEventPublic]


class PrioritySlice(BaseModel):
    """Single priority tier entry in the dashboard distribution bar."""

    priority: TicketPriority
    count: int
    percent: float


class DashboardOverviewPublic(BaseModel):
    """Service-desk KPI metrics, SLA MTTA/MTTR averages, priority distribution, and recent activity."""

    total: int
    open_count: int
    in_progress_count: int
    waiting_customer_count: int
    resolved_or_closed_count: int
    urgent_count: int
    unassigned_count: int
    sla_breached_count: int
    mtta_minutes: Optional[int]
    mttr_minutes: Optional[int]
    priority_distribution: list[PrioritySlice]
    recent_activity: list[AuditEventPublic]
