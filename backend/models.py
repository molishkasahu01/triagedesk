"""SQLModel relational schema definitions for TriageDesk."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class UserRole(str, Enum):
    """Supported application roles enforced across API endpoints."""

    CUSTOMER = "CUSTOMER"
    AGENT = "AGENT"
    ADMIN = "ADMIN"


class TicketPriority(str, Enum):
    """Priority tiers controlling SLA windows and queue order."""

    URGENT = "URGENT"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class TicketStatus(str, Enum):
    """Managed lifecycle states for customer support tickets."""

    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_CUSTOMER = "WAITING_CUSTOMER"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class TicketCategory(str, Enum):
    """Supported functional ticket categories."""

    BUG = "BUG"
    BILLING = "BILLING"
    ACCESS = "ACCESS"
    FEATURE = "FEATURE"
    GENERAL = "GENERAL"


class User(SQLModel, table=True):
    """Registered customer, support agent, or administrator account."""

    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True, max_length=255)
    full_name: str = Field(max_length=120)
    role: UserRole = Field(default=UserRole.CUSTOMER, index=True)
    hashed_password: str
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)


class SupportGroup(SQLModel, table=True):
    """Functional support queues/teams to route and group incoming tickets."""

    __tablename__ = "support_groups"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, max_length=80)
    description: str = Field(default="", max_length=240)
    created_at: datetime = Field(default_factory=utc_now)


class SlaPolicy(SQLModel, table=True):
    """Configurable acknowledgement and resolution SLA targets per priority tier."""

    __tablename__ = "sla_policies"

    priority: TicketPriority = Field(primary_key=True)
    target_ack_minutes: int = Field(default=30, ge=1)
    target_resolve_minutes: int = Field(default=1440, ge=5)
    updated_at: datetime = Field(default_factory=utc_now)


class ApiKey(SQLModel, table=True):
    """Hashed programmatic API keys linked to user RBAC permissions."""

    __tablename__ = "api_keys"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=80)
    key_prefix: str = Field(max_length=16, index=True)
    key_hash: str = Field(max_length=128, unique=True, index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)
    last_used_at: Optional[datetime] = Field(default=None)


class Ticket(SQLModel, table=True):
    """Customer support ticket with group routing, priority, SLA tracking, and owner refs."""

    __tablename__ = "tickets"

    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_key: str = Field(index=True, unique=True, max_length=24)
    title: str = Field(max_length=180)
    description: str
    category: TicketCategory = Field(default=TicketCategory.GENERAL, index=True)
    priority: TicketPriority = Field(default=TicketPriority.MEDIUM, index=True)
    status: TicketStatus = Field(default=TicketStatus.OPEN, index=True)
    sla_due_at: datetime
    created_by_id: int = Field(foreign_key="users.id", index=True)
    assigned_to_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    group_id: Optional[int] = Field(default=None, foreign_key="support_groups.id", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    acknowledged_at: Optional[datetime] = Field(default=None)
    resolved_at: Optional[datetime] = Field(default=None)
    closed_at: Optional[datetime] = Field(default=None)


class TicketComment(SQLModel, table=True):
    """Public replies and internal agent-only notes attached to a ticket."""

    __tablename__ = "ticket_comments"

    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="tickets.id", index=True)
    author_id: int = Field(foreign_key="users.id", index=True)
    body: str
    is_internal: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class TicketAttachment(SQLModel, table=True):
    """Metadata for files uploaded onto a ticket thread."""

    __tablename__ = "ticket_attachments"

    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="tickets.id", index=True)
    uploaded_by_id: int = Field(foreign_key="users.id", index=True)
    original_filename: str = Field(max_length=255)
    stored_filename: str = Field(max_length=255, unique=True)
    content_type: str = Field(default="application/octet-stream", max_length=120)
    size_bytes: int
    created_at: datetime = Field(default_factory=utc_now)


class AuditEvent(SQLModel, table=True):
    """Immutable field-level audit entry recording ticket mutations."""

    __tablename__ = "audit_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="tickets.id", index=True)
    actor_id: int = Field(foreign_key="users.id", index=True)
    event_type: str = Field(max_length=40)
    field_name: Optional[str] = Field(default=None, max_length=60)
    old_value: Optional[str] = Field(default=None, max_length=255)
    new_value: Optional[str] = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=utc_now)
