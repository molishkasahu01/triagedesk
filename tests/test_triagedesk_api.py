"""Comprehensive automated API, RBAC, SLA, attachment, and bulk triage tests."""


def login_token(client, email: str, password: str = "DemoPass123!") -> str:
    """Authenticate and return Bearer token for helper calls."""
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    """Build Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}


def test_health_ui_and_dashboard_metrics(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/favicon.ico").status_code == 204

    home = client.get("/")
    assert home.status_code == 200
    assert "TriageDesk" in home.text
    assert 'name="color-scheme"' in home.text

    agent_headers = auth_headers(login_token(client, "alex@triagedesk.local"))
    dash = client.get("/api/v1/dashboard", headers=agent_headers)
    assert dash.status_code == 200
    body = dash.json()
    assert body["total"] == 4
    assert body["open_count"] == 1
    assert body["in_progress_count"] == 1
    assert body["mtta_minutes"] is not None
    assert body["mttr_minutes"] is not None
    assert len(body["priority_distribution"]) == 4
    assert len(body["recent_activity"]) >= 4


def test_registration_enforces_customer_role(client):
    res = client.post(
        "/api/v1/auth/register",
        json={
            "email": "new.customer@example.com",
            "full_name": "New Customer",
            "password": "SafePassword123!",
            "role": "ADMIN",
        },
    )
    assert res.status_code == 201
    assert res.json()["user"]["role"] == "CUSTOMER"


def test_customer_isolation_notes_and_attachment_rbac(client):
    maya_headers = auth_headers(login_token(client, "maya@client.local"))
    rohan_headers = auth_headers(login_token(client, "rohan@client.local"))
    agent_headers = auth_headers(login_token(client, "alex@triagedesk.local"))

    maya_list = client.get("/api/v1/tickets", headers=maya_headers).json()
    assert {t["ticket_key"] for t in maya_list} == {"TD-1001", "TD-1002"}

    rohan_ticket_id = client.get("/api/v1/tickets", headers=rohan_headers).json()[0]["id"]
    assert client.get(f"/api/v1/tickets/{rohan_ticket_id}", headers=maya_headers).status_code == 403

    # Customers cannot see internal notes OR search inside internal notes
    td_1001 = next(t for t in maya_list if t["ticket_key"] == "TD-1001")
    detail = client.get(f"/api/v1/tickets/{td_1001['id']}", headers=maya_headers).json()
    assert all(not c["is_internal"] for c in detail["comments"])
    cust_note_search = client.get("/api/v1/tickets?q=propagation", headers=maya_headers).json()
    assert cust_note_search == []
    staff_note_search = client.get("/api/v1/tickets?q=propagation", headers=agent_headers).json()
    assert [t["ticket_key"] for t in staff_note_search] == ["TD-1001"]

    # Customer cannot post internal note or mutate status/priority
    assert (
        client.post(
            f"/api/v1/tickets/{td_1001['id']}/comments",
            headers=maya_headers,
            json={"body": "Secret", "is_internal": True},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/tickets/{td_1001['id']}",
            headers=maya_headers,
            json={"priority": "LOW"},
        ).status_code
        == 403
    )

    # Customer can upload attachment to own ticket, but another customer cannot download it
    up = client.post(
        f"/api/v1/tickets/{td_1001['id']}/attachments",
        headers=maya_headers,
        files={"file": ("debug.log", b"ERROR 502 Bad Gateway", "text/plain")},
    )
    assert up.status_code == 201
    att_id = up.json()["id"]
    assert client.get(f"/api/v1/attachments/{att_id}", headers=maya_headers).status_code == 200
    assert client.get(f"/api/v1/attachments/{att_id}", headers=rohan_headers).status_code == 403
    assert client.get(f"/api/v1/attachments/{att_id}", headers=agent_headers).status_code == 200


def test_agent_bulk_triage_workflow_and_api_keys(client):
    agent_headers = auth_headers(login_token(client, "alex@triagedesk.local"))
    maya_headers = auth_headers(login_token(client, "maya@client.local"))

    t1 = client.post(
        "/api/v1/tickets",
        headers=maya_headers,
        json={
            "title": "Keyboard layout resets on save",
            "description": "Saving workspace settings clears hotkey bindings.",
            "category": "BUG",
            "priority": "MEDIUM",
        },
    ).json()
    t2 = client.post(
        "/api/v1/tickets",
        headers=maya_headers,
        json={
            "title": "Export modal clipped on mobile",
            "description": "Dialog overflows horizontally on 375px screens.",
            "category": "BUG",
            "priority": "LOW",
        },
    ).json()

    # Create API Key as agent and authenticate bulk triage via X-API-Key header
    key_res = client.post("/api/v1/api-keys", headers=agent_headers, json={"name": "CI Triage Bot"})
    assert key_res.status_code == 201
    raw_key = key_res.json()["raw_key"]
    assert raw_key.startswith("tdk_")

    me_via_key = client.get("/api/v1/auth/me", headers={"X-API-Key": raw_key})
    assert me_via_key.status_code == 200
    assert me_via_key.json()["role"] == "AGENT"

    bulk = client.post(
        "/api/v1/tickets/bulk",
        headers={"X-API-Key": raw_key},
        json={
            "ticket_ids": [t1["id"], t2["id"]],
            "status": "IN_PROGRESS",
            "priority": "HIGH",
            "assigned_to_id": me_via_key.json()["id"],
        },
    )
    assert bulk.status_code == 200
    for item in bulk.json():
        assert item["status"] == "IN_PROGRESS"
        assert item["priority"] == "HIGH"
        assert item["acknowledged_at"] is not None

    # Revoke key and verify subsequent call returns 401
    assert client.delete(f"/api/v1/api-keys/{key_res.json()['id']}", headers=agent_headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers={"X-API-Key": raw_key}).status_code == 401


def test_admin_groups_sla_config_and_role_updates(client):
    maya_headers = auth_headers(login_token(client, "maya@client.local"))
    admin_headers = auth_headers(login_token(client, "admin@triagedesk.local"))

    # Create support group (Admin only)
    assert (
        client.post("/api/v1/groups", headers=maya_headers, json={"name": "SRE"}).status_code == 403
    )
    grp = client.post(
        "/api/v1/groups",
        headers=admin_headers,
        json={"name": "Cybersecurity", "description": "Security incidents"},
    )
    assert grp.status_code == 201

    # Update SLA target (Admin only)
    sla = client.put(
        "/api/v1/sla/URGENT",
        headers=admin_headers,
        json={"target_ack_minutes": 10, "target_resolve_minutes": 120},
    )
    assert sla.status_code == 200
    assert sla.json()["target_ack_minutes"] == 10
    assert sla.json()["target_resolve_minutes"] == 120
