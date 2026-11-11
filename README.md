# TriageDesk

Original full-stack customer & IT support ticketing platform built with **FastAPI**, **SQLModel**, **PostgreSQL / SQLite**, and a **Bootstrap 5** dark/light web workspace.

---

## Core Capabilities

* **Dashboard & SLA Health:** Live status counts, **MTTA** (Mean Time to Assign), **MTTR** (Mean Time to Resolve), stacked Priority Distribution bar, and clickable Recent Activity audit stream.
* **Priority Queue & Bulk Operations:** Search across ticket keys, titles, descriptions, and permitted notes; filter by status, priority, group, or assignee; select multiple tickets for bulk status/priority/assignee triage.
* **Ticket Detail Workspace:** Inline title/description editing, **Notes** (public replies + staff-only internal notes), **Attachments** (upload/download with RBAC enforcement), chronological **Audit Log**, Properties editor, and live SLA target breakdown.
* **Role-Based Access Control (RBAC):**
  * **`CUSTOMER`**: Creates/edits own tickets, uploads attachments, replies publicly, and cannot view internal agent notes or other users' tickets.
  * **`AGENT`**: Triages the full queue, assigns groups/agents, runs bulk actions, posts internal notes, and generates API keys.
  * **`ADMIN`**: Full access including user role management (`Users`), routing queues (`Groups`), and live `SLA Config` targets per priority.
* **API Keys (`X-API-Key`) & Bearer JWT:** Supports both interactive web sessions and hashed programmatic `X-API-Key` tokens.

---

## Quick Start (Local Testing)

```bash
cd TriageDesk
.venv/bin/python run_local.py
```

`run_local.py` automatically detects if port `8000` is already occupied and selects the next free port (`8001+`), printing clickable UI and Swagger URLs.

### Local Demo Accounts (`DemoPass123!`)
| Role | Email | Password |
|---|---|---|
| Customer | `maya@client.local` | `DemoPass123!` |
| Customer | `rohan@client.local` | `DemoPass123!` |
| Support Agent | `alex@triagedesk.local` | `DemoPass123!` |
| Admin | `admin@triagedesk.local` | `DemoPass123!` |

### Run Tests

```bash
.venv/bin/pytest -v
```
