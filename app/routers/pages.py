# Standard library imports
from pathlib import Path
import logging  # Add this
from app.config.loader import (
    get_brainstorming_limits,
    get_meeting_activity_log_settings,
    get_meeting_refresh_settings,
    get_ui_refresh_settings,
    load_config,
)

# FastAPI imports
from fastapi import APIRouter, Depends, Request, status, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from grab_extension import GrabExtension, is_grab_enabled

# Local imports
from ..auth import get_current_active_user, get_optional_user_model_dependency
from ..schemas.user import User
from ..models.user import UserRole
from ..data.user_manager import UserManager, get_user_manager
from ..data.meeting_manager import MeetingManager, get_meeting_manager
from sqlalchemy.orm import Session
from ..database import get_db

# Constants for redirects and error handling
REDIRECT_PREFIX = "/"
ERROR_PREFIX = "?error="
SUCCESS_PREFIX = "?message="
INVALID_EMAIL_PREFIX = f"{ERROR_PREFIX}invalid_email&details="
INVALID_PASSWORD_PREFIX = f"{ERROR_PREFIX}invalid_password&details="

router = APIRouter()

# Initialize Jinja2 templates
templates_path = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))
templates.env = templates.env.overlay(extensions=[GrabExtension])
templates.env.globals["grab_enabled"] = is_grab_enabled

logger = logging.getLogger(__name__)  # Add this


def _load_default_user_password() -> str:
    try:
        config = load_config()
        return str(config.get("default_user_password", "") or "")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to read default user password: %s", exc)
        return ""


DEFAULT_USER_PASSWORD = _load_default_user_password()
PROJECT_GITHUB_URL = "https://github.com/JohnKruse/decidero_gdss_public"
PROJECT_LICENSE_URL = f"{PROJECT_GITHUB_URL}/blob/main/LICENSE"


@router.get("/", response_class=HTMLResponse)
async def root(
    request: Request,
    current_user: User = Depends(get_optional_user_model_dependency),
):
    """Redirect to /login or /dashboard depending on auth state."""
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@router.get("/about", response_class=HTMLResponse, response_model=None)
async def about(
    request: Request,
    current_user: User = Depends(get_optional_user_model_dependency),
):
    """Public about page with project attribution and licensing links."""
    return templates.TemplateResponse(
        request,
        "about.html",
        {
            "request": request,
            "current_user": current_user,
            "project_github_url": PROJECT_GITHUB_URL,
            "project_license_url": PROJECT_LICENSE_URL,
        },
    )


@router.get("/dashboard", response_class=HTMLResponse, response_model=None)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        get_current_active_user
    ),  # Use get_current_active_user to get full user model
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    """Display the adaptive dashboard based on user role."""

    if current_user is None:
        cached_user = getattr(request.state, "user", None)
        if cached_user is None:
            raise HTTPException(
                status_code=500,
                detail="Authenticated user not available for dashboard render.",
            )
        current_user = cached_user

    ui_refresh = get_ui_refresh_settings()
    context = {
        "request": request,
        "current_user": current_user,
        "UserRole": UserRole,  # Pass the Enum itself to the template for comparisons
        "ui_refresh": ui_refresh,
    }

    # Fetch data common to all roles (e.g., notifications - implement later)

    # Fetch data specific to roles
    if current_user.role in {UserRole.ADMIN, UserRole.SUPER_ADMIN}:
        try:
            context["total_user_count"] = (
                user_manager.get_user_count()
            )  # Renamed for clarity
            context["meeting_count"] = meeting_manager.get_meeting_count()
            # context["users"] = user_manager.get_all_users() # No longer showing full list on dashboard
            # Fetch role counts
            context["admin_count"] = user_manager.get_admin_count()
            context["facilitator_count"] = user_manager.get_facilitator_count()
            context["participant_count"] = user_manager.get_participant_count()
        except Exception as e:
            print(f"Error fetching admin data for dashboard: {e}")
            # Handle error appropriately, maybe set defaults
            context["total_user_count"] = "Error"
            context["meeting_count"] = "Error"
            context["meeting_count"] = "Error"
            context["admin_count"] = "Error"
            context["facilitator_count"] = "Error"
            context["participant_count"] = "Error"

    if current_user.role in {UserRole.FACILITATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN}:
        # Fetch facilitator-specific data (e.g., meetings they facilitate)
        # context["facilitated_meetings"] = meeting_manager.get_meetings_by_facilitator(db, current_user.user_id) # Example
        context["facilitated_meetings"] = []  # Placeholder
        pass  # Add facilitator data fetching later

    # Fetch participant-specific data (e.g., meetings they are part of)
    # context["participant_meetings"] = meeting_manager.get_meetings_by_participant(db, current_user.user_id) # Example
    context["participant_meetings"] = []  # Placeholder

    context.update(
        {
            "role": current_user.role,
            "UserRole": UserRole,  # For role comparisons in template
        }
    )
    return templates.TemplateResponse(request, "dashboard.html", context)


@router.get("/login", response_class=HTMLResponse, response_model=None)
async def login(
    request: Request,
    current_user: User = Depends(get_optional_user_model_dependency),
    user_manager: UserManager = Depends(get_user_manager),
):
    """Show login page"""
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    # Check if any admin user exists
    show_setup_alert = not user_manager.has_admin_user()

    return templates.TemplateResponse(request, 
        "login.html",
        {
            "request": request,
            "UserRole": UserRole,  # For role comparisons in template
            "show_setup_alert": show_setup_alert,
        },
    )


# The POST /login route (handle_login) is removed.
# Login submission is now handled by client-side JavaScript in login.html,
# which calls the /api/auth/token endpoint directly.


@router.get("/register", response_class=HTMLResponse, response_model=None)
async def register(
    request: Request,
    current_user: User = Depends(get_optional_user_model_dependency),
    db: Session = Depends(get_db),
    user_manager: UserManager = Depends(get_user_manager),
):
    """Show register page - handles initial admin setup"""
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    is_initial_setup = not user_manager.has_admin_user()

    return templates.TemplateResponse(request, 
        "register.html",
        {
            "request": request,
            "is_initial_setup": is_initial_setup,
            "initial_role": (
                UserRole.SUPER_ADMIN.value if is_initial_setup else UserRole.PARTICIPANT.value
            ),
            "UserRole": UserRole,  # For role comparisons in template
        },
    )


# The POST /register route (handle_register) is removed.
# Registration submission is handled by client-side JavaScript in register.html,
# which calls the /api/auth/register endpoint directly. The JS in register.html
# already implements this.

#
# Meeting Management Routes
#


@router.get("/meeting/create", response_class=HTMLResponse, response_model=None)
async def create_meeting(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    """Display meeting creation page - requires facilitator/admin"""
    if current_user is None:
        cached_user = getattr(request.state, "user", None)
        if cached_user is None:
            raise HTTPException(
                status_code=500,
                detail="Authenticated user not available for meeting creation.",
            )
        current_user = cached_user
    if current_user.role not in [UserRole.FACILITATOR, UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(
            status_code=403,
            detail="Only facilitators and administrators can create meetings",
        )

    return templates.TemplateResponse(request, 
        "create_meeting.html",
        {
            "request": request,
            "current_user": current_user,
            "role": current_user.role,
            "UserRole": UserRole,  # For role comparisons in template
            "page_mode": "create",
            "meeting_id": None,
        },
    )


@router.get("/meeting/{meeting_id}/settings", response_class=HTMLResponse, response_model=None)
async def meeting_settings(
    request: Request,
    meeting_id: str,
    current_user: User = Depends(get_current_active_user),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    if current_user is None:
        cached_user = getattr(request.state, "user", None)
        if cached_user is None:
            raise HTTPException(
                status_code=500,
                detail="Authenticated user not available for meeting settings.",
            )
        current_user = cached_user

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    facilitator_ids = {
        link.user_id for link in getattr(meeting, "facilitator_links", []) or []
    }
    facilitator_ids.add(getattr(meeting, "owner_id", ""))

    is_admin = current_user.role in {UserRole.ADMIN, UserRole.SUPER_ADMIN}
    is_meeting_facilitator = current_user.user_id in facilitator_ids

    if not (is_admin or is_meeting_facilitator):
        raise HTTPException(
            status_code=403,
            detail="Only facilitators and administrators can configure meetings",
        )

    return templates.TemplateResponse(request, 
        "create_meeting.html",
        {
            "request": request,
            "current_user": current_user,
            "role": current_user.role,
            "UserRole": UserRole,
            "page_mode": "edit",
            "meeting_id": meeting_id,
        },
    )


@router.get("/meeting/{meeting_id}/activity-log", response_class=HTMLResponse, response_model=None)
async def meeting_activity_log(
    request: Request,
    meeting_id: str,
    current_user: User = Depends(get_current_active_user),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    """Display the meeting activity log - requires facilitator/admin."""
    if current_user is None:
        cached_user = getattr(request.state, "user", None)
        if cached_user is None:
            raise HTTPException(
                status_code=500,
                detail="Authenticated user not available for activity log.",
            )
        current_user = cached_user

    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    facilitator_ids = {
        link.user_id for link in getattr(meeting, "facilitator_links", []) or []
    }
    facilitator_ids.add(getattr(meeting, "owner_id", ""))

    is_admin = current_user.role in {UserRole.ADMIN, UserRole.SUPER_ADMIN}
    is_meeting_facilitator = current_user.user_id in facilitator_ids

    if not (is_admin or is_meeting_facilitator):
        raise HTTPException(
            status_code=403,
            detail="Only facilitators and administrators can view the activity log",
        )

    activity_log_settings = get_meeting_activity_log_settings()

    return templates.TemplateResponse(request, 
        "meeting_activity_log.html",
        {
            "request": request,
            "meeting_id": meeting_id,
            "current_user": current_user,
            "meeting": meeting,
            "role": current_user.role,
            "UserRole": UserRole,
            "activity_log_settings": activity_log_settings,
        },
    )


# This must come after other /meeting/... routes
@router.get("/meeting/{meeting_id}", response_class=HTMLResponse, response_model=None)
async def meeting(
    request: Request,
    meeting_id: str,
    current_user: User = Depends(get_current_active_user),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    """Display a specific meeting - requires authenticated user with meeting access"""
    if current_user is None:
        cached_user = getattr(request.state, "user", None)
        if cached_user is None:
            raise HTTPException(
                status_code=500,
                detail="Authenticated user not available for meeting view.",
            )
        current_user = cached_user
    # Validate that current user has access to this meeting
    meeting = meeting_manager.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Check if user is participant/facilitator/admin
    facilitator_ids = {
        link.user_id
        for link in getattr(meeting, "facilitator_links", []) or []
        if getattr(link, "user_id", None)
    }
    if getattr(meeting, "owner_id", None):
        facilitator_ids.add(meeting.owner_id)
    participant_ids = {
        getattr(participant, "user_id", None)
        for participant in getattr(meeting, "participants", [])
    }

    if (
        current_user.role not in {UserRole.ADMIN, UserRole.SUPER_ADMIN}
        and current_user.user_id not in participant_ids
        and current_user.user_id not in facilitator_ids
    ):
        raise HTTPException(
            status_code=403, detail="You do not have access to this meeting"
        )

    brainstorming_limits = get_brainstorming_limits()
    meeting_refresh = get_meeting_refresh_settings()

    return templates.TemplateResponse(request, 
        "meeting.html",
        {
            "request": request,
            "meeting_id": meeting_id,
            "current_user": current_user,
            "meeting": meeting,
            "role": current_user.role,
            "UserRole": UserRole,  # For role comparisons in template
            "brainstorming_limits": brainstorming_limits,
            "meeting_refresh": meeting_refresh,
        },
    )


@router.get("/admin/users", response_class=HTMLResponse, response_model=None)
async def admin_users(
    request: Request, current_user: User = Depends(get_current_active_user)
):
    """Display user management page - requires authenticated admin user"""
    if current_user is None:
        cached_user = getattr(request.state, "user", None)
        if cached_user is None:
            raise HTTPException(
                status_code=500,
                detail="Authenticated user not available for admin view.",
            )
        current_user = cached_user
    if current_user.role not in {UserRole.ADMIN, UserRole.SUPER_ADMIN}:
        raise HTTPException(status_code=403, detail="Admin access required")

    return templates.TemplateResponse(request, 
        "admin/users.html",
        {
            "request": request,
            "current_user": current_user,
            "role": current_user.role,
            "UserRole": UserRole,  # For role comparisons in template
            "default_user_password": DEFAULT_USER_PASSWORD,
            "ui_refresh": get_ui_refresh_settings(),
        },
    )


# Removed obsolete /admin/dashboard route


@router.get("/profile", response_class=HTMLResponse)
async def read_profile_page(
    request: Request, current_user: User = Depends(get_current_active_user)
):
    """Display the user profile page."""
    if current_user is None:
        cached_user = getattr(request.state, "user", None)
        if cached_user is None:
            raise HTTPException(
                status_code=500,
                detail="Authenticated user not available for profile view.",
            )
        current_user = cached_user
    return templates.TemplateResponse(request, 
        "profile.html",
        {
            "request": request,
            "current_user": current_user,
            "role": current_user.role,
            "UserRole": UserRole,  # For role comparisons in template
        },
    )
