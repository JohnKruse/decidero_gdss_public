from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional
import logging
import traceback
import json

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.staticfiles import StaticFiles  # For serving static files
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.database import engine, Base, SessionLocal
from app.database import ensure_sqlite_schema
import app.models  # noqa: F401  # Ensure all SQLAlchemy models are registered
from app.routers import auth as auth_router
from app.routers import pages as pages_router
from app.routers import users as users_router
from app.routers import meetings as meetings_router
from app.routers import brainstorming as brainstorming_router
from app.routers import transfer as transfer_router
from app.routers import voting as voting_router
from app.routers import categorization as categorization_router
from app.routers import realtime as realtime_router
from app.auth.auth import auth_middleware  # Updated middleware name
from app.models.meeting import meeting_facilitators_table
from app.utils.logging_config import setup_logging
import os
from grab_extension import is_grab_enabled
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

# Tables will be created during startup event
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
EXCERPT_LINE_COUNT = 24
MAX_GRAB_ITEMS = 20


class GrabItemRequest(BaseModel):
    template: str = Field(..., min_length=1)
    start_line: int = Field(..., gt=0)


class GrabRequest(BaseModel):
    items: List[GrabItemRequest] = Field(
        ..., min_length=1, max_length=MAX_GRAB_ITEMS
    )
    selection_bbox: dict | None = None
    url: str | None = None
    html_sample: str | None = None


def _resolve_template_path(template_name: str) -> Path:
    templates_root = TEMPLATES_DIR.resolve()
    candidate = (templates_root / template_name).resolve()
    try:
        candidate.relative_to(templates_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=403, detail="Template outside templates directory"
        ) from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Template not found")
    return candidate


def _build_excerpt(template_name: str, start_line: int) -> dict:
    template_path = _resolve_template_path(template_name)
    lines = template_path.read_text(encoding="utf-8").splitlines()
    total_lines = len(lines)
    if total_lines == 0:
        start = end = 1
        formatted = ""
    else:
        start = max(1, min(start_line, total_lines))
        end = min(total_lines, start + EXCERPT_LINE_COUNT - 1)
        formatted = "\n".join(
            f"{line_no:>4}: {lines[line_no - 1]}" for line_no in range(start, end + 1)
        )
    return {
        "template": template_name,
        "start_line": start,
        "end_line": end,
        "path": str(template_path.relative_to(TEMPLATES_DIR)),
        "snippet": formatted,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # Load the ML model
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_schema(engine)
    # Ensure the facilitator join table exists even if the DB predates the relationship
    meeting_facilitators_table.create(bind=engine, checkfirst=True)
    print("Database initialized. First user to register will become super admin.")
    yield
    # Clean up the ML model and release the resources
    print("Application shutdown.")


app = FastAPI(
    title="Decidero GDSS",
    description="A Group Decision Support System",
    lifespan=lifespan,
)

# Mount static files
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app/static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


async def audit_action_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    method = request.method.upper()
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return await call_next(request)

    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)

    user = getattr(request.state, "user", None)
    role = getattr(user, "role", None)
    if not role or str(role).lower() not in {"admin", "super_admin", "facilitator"}:
        return await call_next(request)

    payload_summary: Optional[str] = None
    if request.headers.get("content-type", "").lower().startswith("application/json"):
        try:
            body = await request.body()
            request._body = body  # Preserve for any downstream access
            if body:
                parsed = json.loads(body.decode("utf-8"))
                if isinstance(parsed, dict):
                    redacted = {}
                    for key, value in parsed.items():
                        lower_key = str(key).lower()
                        if "password" in lower_key or "token" in lower_key:
                            redacted[key] = "***"
                        else:
                            redacted[key] = value if isinstance(value, (str, int, float, bool, type(None))) else type(value).__name__
                    payload_summary = json.dumps(redacted, ensure_ascii=True)
                else:
                    payload_summary = type(parsed).__name__
        except Exception:
            payload_summary = "unavailable"

    response = await call_next(request)

    logger = logging.getLogger("audit")
    identifier = getattr(user, "email", None) or getattr(user, "login", None) or "unknown"
    details = {
        "method": method,
        "path": path,
        "status": response.status_code,
        "user": identifier,
        "role": str(role),
    }
    if payload_summary:
        details["payload"] = payload_summary
    logger.info("Audit action: %s", details)
    return response


app.add_middleware(BaseHTTPMiddleware, dispatch=audit_action_middleware)

# Add the authentication middleware
app.add_middleware(
    BaseHTTPMiddleware, dispatch=auth_middleware
)  # Updated middleware name

async def localhost_no_cache_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    response = await call_next(request)
    host = request.url.hostname or ""
    if host in {"localhost", "127.0.0.1", "::1"}:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.add_middleware(BaseHTTPMiddleware, dispatch=localhost_no_cache_middleware)

# Include routers
app.include_router(auth_router.router)
app.include_router(
    pages_router.router
)  # Should generally be last or carefully ordered if it has broad "/" paths
app.include_router(users_router.router)
app.include_router(meetings_router.router)
app.include_router(realtime_router.router)
app.include_router(brainstorming_router.brainstorming_router)
app.include_router(transfer_router.transfer_router)
app.include_router(voting_router.router)
app.include_router(categorization_router.router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger = logging.getLogger("app")
    logger.error(f"Global exception: {str(exc)}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal Server Error. Please check logs."},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger = logging.getLogger("app")
    if exc.status_code >= 500:
        logger.error(
            f"HTTP {exc.status_code} error: {exc.detail}\n{traceback.format_exc()}"
        )
    else:
        logger.info(f"HTTP {exc.status_code}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger = logging.getLogger("app")
    errors = exc.errors()

    # Extract just the error messages for a simpler, guaranteed-serializable response
    error_messages = [err["msg"] for err in errors]

    logger.warning(f"Validation error: {error_messages}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": error_messages},
    )


@app.get("/health", tags=["healthcheck"])
async def health_check():
    try:
        db = SessionLocal()
        # Simple query to check DB connection
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        # Log the exception for more details if needed
        print(f"Health check database connection error: {e}")
        raise HTTPException(
            status_code=503, detail=f"Database connection failed: {str(e)}"
        )


@app.post("/__grab")
async def grab_endpoint(payload: GrabRequest):
    if not is_grab_enabled():
        raise HTTPException(status_code=404, detail="Grab tooling disabled")
    excerpts = [
        _build_excerpt(item.template, item.start_line) for item in payload.items
    ]
    return {
        "items": excerpts,
        "count": len(excerpts),
    }


# The root endpoint from pages.py will handle "/" if it's defined as such.
# If pages.py has a more specific root (e.g. /pages/), then this can be uncommented.
# @app.get("/")
# async def root():
#     return {"message": "Welcome to Decidero GDSS. Visit /docs for API documentation."}
