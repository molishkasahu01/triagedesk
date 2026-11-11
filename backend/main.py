"""FastAPI application entrypoint serving TriageDesk REST API and Bootstrap 5 workspace."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from backend.config import settings
from backend.database import engine, init_db
from backend.routes import admin, auth, tickets, users
from backend.seed import seed_demo_data

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"
STATIC_DIR = BASE_DIR / "frontend" / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialize relational tables and idempotent local demo records on startup."""
    init_db()
    if settings.auto_seed:
        with Session(engine) as session:
            seed_demo_data(session)
    yield


def create_app() -> FastAPI:
    """Construct configured FastAPI application instance."""
    app = FastAPI(
        title="TriageDesk API",
        description="Customer support ticketing, SLA tracking, groups, API keys, and RBAC triage platform.",
        version="2.0.0",
        lifespan=lifespan,
    )
    app.include_router(auth.router)
    app.include_router(tickets.router)
    app.include_router(admin.router)
    app.include_router(users.router)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.get("/health", tags=["Health"])
    def health_check() -> dict[str, str]:
        """Liveness health check endpoint."""
        return {"status": "ok", "service": "TriageDesk"}

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        """Avoid 404 console warnings when browsers request favicon.ico."""
        return Response(status_code=204)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def serve_dashboard(request: Request):
        """Serve the Bootstrap 5 customer/agent support triage web workspace."""
        return templates.TemplateResponse(request, "index.html", {"app_name": settings.app_name})

    return app


app = create_app()
