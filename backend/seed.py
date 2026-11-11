"""Idempotent local demo data seeder for testing multi-role triage workflows."""

from datetime import timedelta

from sqlmodel import Session, select

from backend.models import (
    AuditEvent,
    SlaPolicy,
    SupportGroup,
    Ticket,
    TicketCategory,
    TicketComment,
    TicketPriority,
    TicketStatus,
    User,
    UserRole,
    utc_now,
)
from backend.security import hash_password
from backend.workflow import DEFAULT_SLA_TARGETS, compute_sla_deadline


def seed_demo_data(session: Session) -> None:
    """Populate demo users, support groups, SLA policies, tickets, notes, and audit logs when empty."""
    if session.exec(select(User)).first():
        return

    for prio, (ack_m, res_m) in DEFAULT_SLA_TARGETS.items():
        if not session.exec(select(SlaPolicy).where(SlaPolicy.priority == prio)).first():
            session.add(
                SlaPolicy(
                    priority=prio,
                    target_ack_minutes=ack_m,
                    target_resolve_minutes=res_m,
                )
            )
    session.commit()

    group_platform = SupportGroup(name="Platform & API", description="Webhook, runtime, and REST API incidents")
    group_billing = SupportGroup(name="Billing Operations", description="Invoices, refunds, and subscription plans")
    group_access = SupportGroup(name="Identity & Access", description="SSO, RBAC permissions, and account onboarding")
    session.add_all([group_platform, group_billing, group_access])
    session.commit()
    for grp in (group_platform, group_billing, group_access):
        session.refresh(grp)

    customer_maya = User(
        email="maya@client.local",
        full_name="Maya Verma",
        role=UserRole.CUSTOMER,
        hashed_password=hash_password("DemoPass123!"),
    )
    customer_rohan = User(
        email="rohan@client.local",
        full_name="Rohan Kapoor",
        role=UserRole.CUSTOMER,
        hashed_password=hash_password("DemoPass123!"),
    )
    agent_alex = User(
        email="alex@triagedesk.local",
        full_name="Alex Sharma",
        role=UserRole.AGENT,
        hashed_password=hash_password("DemoPass123!"),
    )
    admin_user = User(
        email="admin@triagedesk.local",
        full_name="Admin Lead",
        role=UserRole.ADMIN,
        hashed_password=hash_password("DemoPass123!"),
    )
    session.add_all([customer_maya, customer_rohan, agent_alex, admin_user])
    session.commit()
    for user in (customer_maya, customer_rohan, agent_alex, admin_user):
        session.refresh(user)

    now = utc_now()
    sample_tickets = [
        Ticket(
            ticket_key="TD-1001",
            title="Production checkout webhook returning HTTP 502",
            description="Payment webhooks started failing with 502 Bad Gateway after the signing secret rotation at 09:30 UTC.",
            category=TicketCategory.BUG,
            priority=TicketPriority.URGENT,
            status=TicketStatus.IN_PROGRESS,
            sla_due_at=compute_sla_deadline(TicketPriority.URGENT, now - timedelta(hours=1), session),
            created_by_id=customer_maya.id,
            assigned_to_id=agent_alex.id,
            group_id=group_platform.id,
            created_at=now - timedelta(hours=1),
            updated_at=now - timedelta(minutes=20),
            acknowledged_at=now - timedelta(minutes=52),
        ),
        Ticket(
            ticket_key="TD-1002",
            title="Duplicate invoice charge on Pro workspace subscription",
            description="Card ending 4421 was charged twice for invoice #INV-8821. Need confirmation on refund timeline.",
            category=TicketCategory.BILLING,
            priority=TicketPriority.HIGH,
            status=TicketStatus.OPEN,
            sla_due_at=compute_sla_deadline(TicketPriority.HIGH, now - timedelta(hours=2), session),
            created_by_id=customer_maya.id,
            assigned_to_id=None,
            group_id=group_billing.id,
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=2),
        ),
        Ticket(
            ticket_key="TD-1003",
            title="SSO role claim mismatch blocking QA engineer onboarding",
            description="New team member can authenticate through OIDC but defaults to read-only viewer.",
            category=TicketCategory.ACCESS,
            priority=TicketPriority.MEDIUM,
            status=TicketStatus.WAITING_CUSTOMER,
            sla_due_at=compute_sla_deadline(TicketPriority.MEDIUM, now - timedelta(hours=5), session),
            created_by_id=customer_rohan.id,
            assigned_to_id=agent_alex.id,
            group_id=group_access.id,
            created_at=now - timedelta(hours=5),
            updated_at=now - timedelta(hours=1),
            acknowledged_at=now - timedelta(hours=4, minutes=45),
        ),
        Ticket(
            ticket_key="TD-1004",
            title="Add CSV export option on audit trail panel",
            description="Compliance team would like a monthly CSV export button for ticket mutation history.",
            category=TicketCategory.FEATURE,
            priority=TicketPriority.LOW,
            status=TicketStatus.RESOLVED,
            sla_due_at=compute_sla_deadline(TicketPriority.LOW, now - timedelta(days=2), session),
            created_by_id=customer_rohan.id,
            assigned_to_id=admin_user.id,
            group_id=group_platform.id,
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(hours=8),
            acknowledged_at=now - timedelta(days=1, hours=23, minutes=40),
            resolved_at=now - timedelta(hours=8),
        ),
    ]
    session.add_all(sample_tickets)
    session.commit()
    for t in sample_tickets:
        session.refresh(t)

    comments = [
        TicketComment(
            ticket_id=sample_tickets[0].id,
            author_id=agent_alex.id,
            body="Investigating upstream signature verification logs now. We will post an update within 30 minutes.",
            is_internal=False,
        ),
        TicketComment(
            ticket_id=sample_tickets[0].id,
            author_id=agent_alex.id,
            body="Internal check: webhook worker restarted cleanly; verifying new signing secret propagation.",
            is_internal=True,
        ),
        TicketComment(
            ticket_id=sample_tickets[2].id,
            author_id=agent_alex.id,
            body="Could you share the mapped OIDC group attribute name from your IdP assertion?",
            is_internal=False,
        ),
    ]
    events = [
        AuditEvent(
            ticket_id=sample_tickets[0].id,
            actor_id=customer_maya.id,
            event_type="CREATED",
            field_name="status",
            old_value=None,
            new_value="OPEN",
        ),
        AuditEvent(
            ticket_id=sample_tickets[0].id,
            actor_id=agent_alex.id,
            event_type="UPDATED",
            field_name="assigned_to",
            old_value="Unassigned",
            new_value=agent_alex.full_name,
        ),
        AuditEvent(
            ticket_id=sample_tickets[0].id,
            actor_id=agent_alex.id,
            event_type="UPDATED",
            field_name="status",
            old_value="OPEN",
            new_value="IN_PROGRESS",
        ),
        AuditEvent(
            ticket_id=sample_tickets[0].id,
            actor_id=agent_alex.id,
            event_type="INTERNAL_NOTE",
            field_name="comment",
            old_value=None,
            new_value="Internal check: webhook worker restarted cleanly",
        ),
        AuditEvent(
            ticket_id=sample_tickets[1].id,
            actor_id=customer_maya.id,
            event_type="CREATED",
            field_name="status",
            old_value=None,
            new_value="OPEN",
        ),
        AuditEvent(
            ticket_id=sample_tickets[3].id,
            actor_id=admin_user.id,
            event_type="UPDATED",
            field_name="status",
            old_value="IN_PROGRESS",
            new_value="RESOLVED",
        ),
    ]
    session.add_all(comments + events)
    session.commit()
