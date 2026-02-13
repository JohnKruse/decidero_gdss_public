from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import HTMLResponse
from app.schemas.schemas import (
    UserCreate,
    Token,
    UserRole,
    Permission,
)  # Ensure Permission is imported
from app.schemas.user import (
    UserResponse,
    UserProfileUpdate,
    BatchCreateByPattern,
    BatchCreateByEmails,
    BatchCreateResult,
    UserDirectoryResponse,
    UserDirectorySort,
    UserDirectoryEntry,
    UserDirectoryPagination,
    UserDirectoryContext,
)
from app.models.user import User
from app.auth.auth import (
    create_access_token,
    check_permission,
    get_user_role,
    get_current_user,
    get_current_active_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from app.utils.security import get_password_hash, verify_password
from app.data.user_manager import (
    UserManager,
    get_user_manager,
)  # Import both class and dependency provider
from app.data.meeting_manager import MeetingManager, get_meeting_manager
from app.services.avatar_catalog import is_valid_avatar_key, list_avatar_entries
from app.utils.encryption import encryption_manager
from datetime import timedelta
from typing import List, Dict, Optional
from pydantic import BaseModel  # Added BaseModel for LoginRequest
import logging
import re
import math

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Get auth logger
auth_logger = logging.getLogger("auth")


class LoginRequest(BaseModel):  # Pydantic model for the login request
    login: str
    password: str


router = APIRouter(
    prefix="/api/users",
    tags=["users"],
)


def _user_can_manage_meeting(meeting, user: "User") -> bool:

    facilitator_links = getattr(meeting, "facilitator_links", []) or []

    return any(
        (
            user.role in {UserRole.ADMIN, UserRole.SUPER_ADMIN},
            meeting.owner_id == getattr(user, "user_id", None),
            any(link.user_id == user.user_id for link in facilitator_links),
        )
    )


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def register_user(
    user: UserCreate,
    current_user_role: Optional[UserRole] = Depends(get_user_role),
    current_user: Optional[str] = Depends(get_current_user),
    user_manager: UserManager = Depends(
        get_user_manager
    ),  # Added user_manager dependency
):
    """
    Register a new user.

    First registration creates super admin user and initializes encryption.
    Subsequent registrations require admin authentication.

    Args:
        user: User creation data including email, name, login, password, and role
        current_user_role: Role of the authenticated user (if any)
        current_user: Username of the authenticated user (if any)

    Returns:
        User: Created user information

    Raises:
        HTTPException:
            - 403: Non-admin trying to register users
            - 400: Invalid input data
            - 409: User already exists
    """
    try:
        # Get existing users
        existing_users = user_manager.get_users()
        users_exist = len(existing_users) > 0

        if not users_exist:
            logger.info(
                "*** Setting up admin account. This is a one-time process for initializing the application. ***"
            )

        # Validate registration permissions
        if users_exist:
            if not current_user_role or current_user_role not in {
                UserRole.ADMIN,
                UserRole.SUPER_ADMIN,
            }:
                logger.warning(
                    f"Unauthorized registration attempt by user with role: {current_user_role}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "status": "error",
                        "code": 403,
                        "message": "Only administrators can register new users",
                        "details": {"current_role": current_user_role},
                    },
                )
            logger.info(
                f"Admin user {current_user} initiating user registration for {user.email}"
            )
        else:
            # First user must be super admin
            user.role = UserRole.SUPER_ADMIN
            logger.info("Registering first super admin user")
        if users_exist:
            requested_role = (
                user.role.value if isinstance(user.role, UserRole) else str(user.role)
            )
            requested_role = requested_role.lower()
            if requested_role in {
                UserRole.ADMIN.value,
                UserRole.SUPER_ADMIN.value,
            }:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Admin role requires promotion from facilitator.",
                )

        duplicate_email = bool(
            user.email and any(u for u in existing_users if u.email == user.email)
        )
        duplicate_login = any(u for u in existing_users if u.login == user.login)

        if duplicate_email or duplicate_login:
            logger.warning(
                "Registration attempt with duplicate email/login: %s/%s",
                user.email,
                user.login,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "status": "error",
                    "code": 409,
                    "message": "User with this email or login already exists",
                    "details": {
                        "email": user.email if duplicate_email else None,
                        "login": user.login if duplicate_login else None,
                    },
                },
            )

        # Additional input validation
        # Sanitize and validate names
        for field in ["first_name", "last_name"]:
            value = getattr(user, field)
            if not value.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "error",
                        "code": 400,
                        "message": f"{field.replace('_', ' ').title()} cannot be empty",
                        "field": field,
                    },
                )
            if not re.match(r"^[a-zA-Z\s-']+$", value):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": "error",
                        "code": 400,
                        "message": f"{field.replace('_', ' ').title()} can only contain letters, spaces, hyphens, and apostrophes",
                        "field": field,
                    },
                )

        # Create user
        try:
            hashed_password = get_password_hash(user.password)
            created_user = user_manager.add_user(
                first_name=user.first_name,
                last_name=user.last_name,
                email=user.email,
                hashed_password=hashed_password,
                role=user.role.value if isinstance(user.role, UserRole) else user.role,
                login=user.login,
            )

            logger.info(
                f"Successfully registered user: {user.email} with role: {user.role}"
            )
            return UserResponse.model_validate(created_user)

        except Exception as e:
            logger.error(f"Error creating user: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "status": "error",
                    "code": 500,
                    "message": "Internal server error during user creation",
                    "details": {"error": str(e)},
                },
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in register_user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "code": 500,
                "message": "An unexpected error occurred",
                "details": {"error": str(e)},
            },
        )


@router.post("/login", response_model=Token)
async def login_user(
    login_request: LoginRequest,
    user_manager: UserManager = Depends(
        get_user_manager
    ),  # Added user_manager dependency
):  # Changed to use LoginRequest Pydantic model
    """Authenticate user and return access token."""

    login = login_request.login
    password = login_request.password

    auth_logger.info(f"Login attempt for user: {login}")

    if (
        not login or not password
    ):  # This check might be redundant due to Pydantic validation
        auth_logger.warning(
            f"Missing credentials - login: {login is None}, password: {password is None}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "status": "error",
                "code": 400,
                "message": "Missing credentials",
                "details": {
                    "login": "required" if not login else None,
                    "password": "required" if not password else None,
                },
            },
        )

    # Try to get user by login or email
    user_record = user_manager.get_user_by_login(login)
    auth_logger.debug(f"User record by login: {user_record}")

    if not user_record:
        # Try email if login fails
        user_record = user_manager.get_user_by_email(login)
        auth_logger.debug(f"User record by email: {user_record}")

    if not user_record:
        auth_logger.warning(f"Failed login attempt for non-existent user: {login}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"status": "error", "code": 401, "message": "Invalid credentials"},
        )

    auth_logger.info(f"Found user with login '{user_record.login}'")

    # If user is admin, initialize encryption with their password
    if user_record.role in {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}:
        try:
            encryption_manager.initialize_with_admin_password(password)
            auth_logger.debug("Successfully initialized encryption with admin password")
        except Exception as e:
            auth_logger.error(f"Failed to initialize encryption: {str(e)}")

    # Verify password using the password auth provider
    hashed_password = user_record.hashed_password
    auth_logger.debug(f"Stored hashed password: {hashed_password}")

    if not hashed_password or not verify_password(password, hashed_password):
        auth_logger.warning(
            f"Failed login attempt with invalid password for user: {login}"
        )
        auth_logger.debug(
            f"Password verification failed. Input length: {len(password)}, Hash exists: {bool(hashed_password)}"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"status": "error", "code": 401, "message": "Invalid credentials"},
        )

    auth_logger.info(
        f"Successful login for user: {user_record.login}"
    )  # Use user_record.login

    # Create access token with user data
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_record.login, "role": user_record.role},
        expires_delta=access_token_expires,
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/batch/pattern", response_model=BatchCreateResult)
async def batch_create_by_pattern(
    payload: BatchCreateByPattern,
    current_user: str = Depends(get_current_user),
    _: bool = Depends(check_permission(Permission.MANAGE_USERS)),
    user_manager: UserManager = Depends(get_user_manager),
):
    """Create users using a numeric pattern for logins e.g. user_00..user_99."""
    try:
        role_value = (
            payload.role.value if hasattr(payload.role, "value") else payload.role
        )
        if str(role_value).lower() in {
            UserRole.ADMIN.value,
            UserRole.SUPER_ADMIN.value,
        }:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin role requires promotion from facilitator.",
            )
        result = user_manager.batch_add_users_by_pattern(
            prefix=payload.prefix,
            start=payload.start,
            end=payload.end,
            default_password=payload.default_password,
            role=payload.role.value if hasattr(payload.role, "value") else payload.role,
            email_domain=payload.email_domain,
            first_name=payload.first_name,
            last_name=payload.last_name,
        )
        return BatchCreateResult(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch/emails", response_model=BatchCreateResult)
async def batch_create_by_emails(
    payload: BatchCreateByEmails,
    current_user: str = Depends(get_current_user),
    _: bool = Depends(check_permission(Permission.MANAGE_USERS)),
    user_manager: UserManager = Depends(get_user_manager),
):
    """Create users from a list of emails."""
    try:
        role_value = (
            payload.role.value if hasattr(payload.role, "value") else payload.role
        )
        if str(role_value).lower() in {
            UserRole.ADMIN.value,
            UserRole.SUPER_ADMIN.value,
        }:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin role requires promotion from facilitator.",
            )
        result = user_manager.batch_add_users_by_emails(
            emails=payload.emails,
            default_password=payload.default_password,
            role=payload.role.value if hasattr(payload.role, "value") else payload.role,
            first_name=payload.first_name,
            last_name=payload.last_name,
        )
        return BatchCreateResult(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{identifier}")
async def delete_user(
    identifier: str,
    current_user: str = Depends(get_current_user),
    _: bool = Depends(check_permission(Permission.MANAGE_USERS)),
    user_manager: UserManager = Depends(get_user_manager),
):
    """Delete a user by login or email."""
    target = user_manager.get_user_by_email(identifier) or user_manager.get_user_by_login(
        identifier
    )
    if target and target.role == UserRole.SUPER_ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin cannot be deleted.",
        )
    ok = user_manager.delete_user(identifier)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "deleted", "identifier": identifier}


class ResetPasswordRequest(BaseModel):
    new_password: str


@router.post("/{identifier}/reset_password")
async def reset_user_password(
    identifier: str,
    payload: ResetPasswordRequest,
    current_user: str = Depends(get_current_user),
    _: bool = Depends(check_permission(Permission.MANAGE_USERS)),
    user_manager: UserManager = Depends(get_user_manager),
):
    """Reset a user's password; marks password_changed False."""
    # Validate password complexity using the same validator as schemas
    from app.utils.password_validation import validate_password

    is_valid, error_message = validate_password(payload.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_message)

    target = user_manager.get_user_by_email(identifier) or user_manager.get_user_by_login(
        identifier
    )
    if target and target.role == UserRole.SUPER_ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin password cannot be reset here.",
        )

    ok = user_manager.reset_password(identifier, payload.new_password)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "reset", "identifier": identifier}


class SelfPasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/me/change_password")
async def change_own_password(
    payload: SelfPasswordChangeRequest,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
):
    """Allow the current user to change their own password."""
    from app.utils.password_validation import validate_password

    user = user_manager.get_user_by_login(current_user)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    is_valid, error_message = validate_password(payload.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_message)

    ok = user_manager.reset_password(user.login, payload.new_password)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update password.",
        )
    return {"status": "changed"}


@router.post("/me/avatar/regenerate", response_model=UserResponse)
async def regenerate_my_avatar(
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
):
    updated = user_manager.regenerate_avatar(current_user)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return updated


@router.post("/me/avatar/regenerate_color", response_model=UserResponse)
async def regenerate_my_avatar_color(
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
):
    updated = user_manager.regenerate_avatar_color(current_user)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return updated


@router.get("/avatars/catalog")
async def list_avatar_catalog(
    current_user: str = Depends(get_current_user),
):
    return {"count": len(list_avatar_entries()), "avatars": list_avatar_entries()}


class RoleUpdateRequest(BaseModel):
    role: UserRole


@router.patch("/{identifier}/role")
async def update_user_role(
    identifier: str,
    payload: RoleUpdateRequest,
    current_user: str = Depends(get_current_user),
    _: bool = Depends(check_permission(Permission.MANAGE_ROLES)),
    user_manager: UserManager = Depends(get_user_manager),
):
    """Update a user's role. Admin only."""
    desired_role = (
        payload.role.value if hasattr(payload.role, "value") else payload.role
    )
    desired_role = str(desired_role).lower()
    if desired_role == UserRole.SUPER_ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot assign super admin role via this endpoint.",
        )

    user = user_manager.get_user_by_email(identifier)
    if not user:
        user = user_manager.get_user_by_login(identifier)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.role == UserRole.SUPER_ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin roles cannot be modified.",
        )

    if desired_role not in {
        UserRole.PARTICIPANT.value,
        UserRole.FACILITATOR.value,
        UserRole.ADMIN.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be participant, facilitator, or admin.",
        )

    if desired_role == UserRole.ADMIN.value and user.role == UserRole.PARTICIPANT.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Participant must be promoted to facilitator before admin.",
        )

    updated = user_manager.update_user_role(identifier, desired_role)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user role.",
        )

    return {
        "status": "updated" if updated.role == desired_role else "unchanged",
        "identifier": identifier,
        "role": updated.role,
    }


@router.get("/me/profile", response_model=UserResponse)
async def get_current_user_profile(
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
):
    """Get current user's profile information, including the profile SVG."""
    try:
        logger.debug(f"Fetching profile info for: {current_user}")
        user = user_manager.get_user_by_login(current_user)
        if user is None:
            logger.error(f"User not found: {current_user}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        logger.debug(f"Successfully retrieved profile info for: {current_user}")
        return user
    except Exception as e:
        logger.error(f"Error retrieving profile info: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve profile information",
        )


@router.patch("/me/profile", response_model=UserResponse)
async def update_current_user_profile(
    profile_update: UserProfileUpdate,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
):
    """Update current user's profile information (only about_me)."""
    try:
        logger.debug(f"Updating profile for user: {current_user}")

        existing_user = user_manager.get_user_by_login(current_user)
        if not existing_user:
            logger.error(f"User not found for update: {current_user}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        if profile_update.avatar_key is not None:
            candidate_key = str(profile_update.avatar_key).strip()
            if not is_valid_avatar_key(candidate_key):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid avatar key",
                )

        # Call user manager to perform the update, using email as the current datastore key
        updated_user = user_manager.update_user(
            user_identifier=existing_user.login,
            updated_data=profile_update.model_dump(exclude_unset=True),
        )

        if not updated_user:
            logger.error(f"Failed to update profile for user: {current_user}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to update profile",
            )

        logger.info(f"Successfully updated profile for user: {current_user}")
        return updated_user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating profile: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile due to internal error",
        )


@router.get("/directory", response_model=UserDirectoryResponse)
async def user_directory(
    search: Optional[str] = Query(None, min_length=0, max_length=120, alias="q"),
    roles: Optional[List[UserRole]] = Query(None, description="Filter by user roles"),
    sort: UserDirectorySort = Query(UserDirectorySort.NAME),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    meeting_id: Optional[str] = Query(
        None, description="Restrict context to a meeting"
    ),
    activity_id: Optional[str] = Query(
        None, description="Restrict context to a specific activity"
    ),
    include_inactive: bool = Query(
        False, description="Include inactive users (admins only)"
    ),
    draft: bool = Query(
        False,
        description="Allow facilitators/admins to browse the directory without an existing meeting context.",
    ),
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
    meeting_manager: MeetingManager = Depends(get_meeting_manager),
):
    """Return a searchable, pageable directory of users with meeting/activity context metadata."""
    try:
        requester = user_manager.get_user_by_login(current_user)
        if not requester:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        safe_page = max(1, page)
        safe_page_size = max(1, min(page_size, 100))

        meeting = None
        meeting_participant_ids: set[str] = set()
        facilitator_ids: set[str] = set()
        activity_participant_ids: set[str] = set()
        activity_mode = "all"

        if activity_id and not meeting_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="meeting_id is required when filtering by activity_id",
            )

        if meeting_id:
            meeting = meeting_manager.get_meeting(meeting_id)
            if not meeting:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
                )
            if not _user_can_manage_meeting(meeting, requester):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only facilitators or admins can view the meeting directory",
                )
            meeting_participant_ids = {
                participant.user_id
                for participant in getattr(meeting, "participants", []) or []
                if getattr(participant, "user_id", None)
            }
            facilitator_ids = {
                link.user_id
                for link in getattr(meeting, "facilitator_links", []) or []
                if getattr(link, "user_id", None)
            }

            if activity_id:
                activity = next(
                    (
                        item
                        for item in getattr(meeting, "agenda_activities", []) or []
                        if item.activity_id == activity_id
                    ),
                    None,
                )
                if not activity:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Agenda activity not found",
                    )
                config = dict(getattr(activity, "config", {}) or {})
                configured = config.get("participant_ids")
                if isinstance(configured, list) and configured:
                    activity_participant_ids = {
                        str(pid).strip() for pid in configured if str(pid).strip()
                    }
                    activity_mode = "custom"
        else:
            if draft:
                if requester.role not in {
                    UserRole.ADMIN,
                    UserRole.SUPER_ADMIN,
                    UserRole.FACILITATOR,
                }:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Directory draft mode is limited to facilitators or administrators.",
                    )
            elif requester.role not in {UserRole.ADMIN, UserRole.SUPER_ADMIN}:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Meeting context is required unless you are an administrator",
                )

        if include_inactive and requester.role not in {
            UserRole.ADMIN,
            UserRole.SUPER_ADMIN,
        }:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can view inactive accounts",
            )

        role_filters = [role.value for role in roles] if roles else None
        records, total = user_manager.query_directory(
            search=search,
            roles=role_filters,
            include_inactive=include_inactive,
            sort=sort.value,
            page=safe_page,
            page_size=safe_page_size,
        )

        items: List[UserDirectoryEntry] = []
        for entry in records:
            user_id = getattr(entry, "user_id", None)
            if not user_id:
                continue
            role_value = getattr(entry, "role", UserRole.PARTICIPANT)
            if not isinstance(role_value, UserRole):
                try:
                    role_value = UserRole(role_value)
                except ValueError:
                    role_value = UserRole.PARTICIPANT

            is_meeting_participant = user_id in meeting_participant_ids
            inherits_activity = (
                activity_id is not None
                and activity_mode == "all"
                and is_meeting_participant
            )
            is_activity_participant = (
                user_id in activity_participant_ids
                if activity_participant_ids
                else inherits_activity
            )
            is_facilitator = (meeting and meeting.owner_id == user_id) or (
                user_id in facilitator_ids
            )

            disabled_reason = None
            if not getattr(entry, "is_active", True):
                disabled_reason = "User account is inactive"
            elif activity_id and not is_meeting_participant:
                disabled_reason = (
                    "Add user to the meeting before assigning to this activity"
                )

            items.append(
                UserDirectoryEntry(
                    user_id=user_id,
                    login=getattr(entry, "login", ""),
                    first_name=getattr(entry, "first_name", None),
                    last_name=getattr(entry, "last_name", None),
                    email=getattr(entry, "email", None),
                    avatar_color=getattr(entry, "avatar_color", None),
                    avatar_key=getattr(entry, "avatar_key", None),
                    avatar_icon_path=getattr(entry, "avatar_icon_path", None),
                    role=role_value,
                    is_active=getattr(entry, "is_active", True),
                    is_meeting_participant=is_meeting_participant,
                    is_activity_participant=is_activity_participant,
                    is_facilitator=bool(is_facilitator),
                    disabled_reason=disabled_reason,
                )
            )

        total_pages = math.ceil(total / safe_page_size) if total else 0
        pagination = UserDirectoryPagination(
            page=safe_page,
            page_size=safe_page_size,
            total=total,
            pages=total_pages,
        )

        activity_participant_count = (
            len(activity_participant_ids)
            if activity_id and activity_mode == "custom"
            else len(meeting_participant_ids) if activity_id else 0
        )

        context = UserDirectoryContext(
            meeting_id=meeting.meeting_id if meeting else None,
            activity_id=activity_id,
            meeting_participant_count=len(meeting_participant_ids),
            activity_participant_count=activity_participant_count,
            activity_mode=activity_mode,
        )

        return UserDirectoryResponse(
            items=items, pagination=pagination, context=context
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to build user directory: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load user directory",
        )


@router.get("/search", response_model=List[UserResponse])
async def search_users(
    q: str,
    limit: int = 10,
    current_user: str = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    Search users by login, first name, last name, or email.
    Requires authentication. Results are limited to public profile fields.
    """
    try:
        cleaned = (q or "").strip()
        if len(cleaned) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query must be at least 2 characters",
            )
        limit = max(1, min(int(limit or 10), 50))
        results = user_manager.search_users(cleaned, limit)
        return results
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "code": 500,
                "message": "Failed to search users",
                "details": str(e),
            },
        )


@router.get("/{email}", response_class=HTMLResponse)
async def get_user(
    email: str,
    current_user=Depends(get_current_active_user),
    user_manager: UserManager = Depends(get_user_manager),
):
    """Get user information by email."""
    try:
        logger.debug(f"Fetching user info for email: {email}")
        # Check if current user has permission to view other users
        if not current_user:
            logger.error("Current user not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Current user not found"
            )

        # Only allow admin users to view other users' information
        if current_user.role not in {UserRole.ADMIN, UserRole.SUPER_ADMIN} and email != current_user.email:
            logger.warning(
                f"Unauthorized access attempt by {current_user.email} to view {email}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view other users' information",
            )

        user = user_manager.get_user_by_email(email)
        if not user:
            logger.error(f"Requested user not found: {email}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        logger.debug(f"Successfully retrieved user info for: {email}")
        return user
    except Exception as e:
        logger.error(f"Error retrieving user info: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user information",
        )


@router.get("/", response_model=List[Dict])
async def get_users(
    current_user: str = Depends(get_current_user),
    current_user_role: UserRole = Depends(get_user_role),
    _: bool = Depends(check_permission(Permission.MANAGE_USERS)),
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    Retrieve all users.
    Only users with MANAGE_USERS permission can access this endpoint.
    Returns only public user information.
    """
    try:
        users = user_manager.get_all_users()
        return [
            {
                "user_id": u.user_id,
                "login": u.login,
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "avatar_color": u.avatar_color,
                "avatar_icon_path": u.avatar_icon_path,
                "role": u.role,
                "is_active": u.is_active,
            }
            for u in users
        ]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "code": 500,
                "message": "Failed to retrieve users",
                "details": str(e),
            },
        )
