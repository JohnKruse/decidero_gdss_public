from typing import Dict, Optional, Set
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, UTC
from jose import JWTError, jwt
from urllib.parse import urlencode  # Added import
from app.schemas.schemas import UserRole, Permission
from app.schemas.user import User as UserSchema
from app.data.user_manager import UserManager  # Import the class
from app.database import (
    get_db,
)  # Import DB session dependency AND SessionLocal for middleware
from app.models.user import User as UserModel  # Import the User model
import os
import logging
from fastapi.responses import RedirectResponse, JSONResponse
from grab_extension import is_grab_enabled
from app.config.loader import load_config, get_guest_join_enabled

# Set up a dedicated logger for authentication events
logger = logging.getLogger("auth_module")  # Changed logger name for clarity
logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())  # Allow configuring log level


# --- Configuration ---
def generate_dev_key() -> str:
    """Generate a secure default key for development environments ONLY."""
    import secrets

    key = secrets.token_urlsafe(48)  # 48 bytes = 64 characters
    logger.warning(
        "\n"
        + "*" * 80
        + "\n"
        + "⚠️ DEVELOPMENT MODE: Using generated secret key.\n"
        + "This is NOT secure for production use!\n"
        + "Set DECIDERO_JWT_SECRET_KEY in your environment variables for production.\n"
        + "*" * 80
    )
    return key


def validate_secret_key(key: str) -> bool:
    """Validate that a JWT secret key meets minimum security requirements."""
    if not key:
        return False
    if len(key) < 32:
        logger.error("JWT secret key must be at least 32 characters long for security.")
        return False
    return True


def _is_production_mode() -> bool:
    env = os.getenv("DECIDERO_ENV", "development").strip().lower()
    return env in {"production", "prod"}


def _get_access_token_expire_minutes(default: int = 30) -> int:
    """
    Source the access token expiration time from config.yaml, falling back to
    environment variable DECIDERO_ACCESS_TOKEN_EXPIRE_MINUTES, then a hard default.
    """
    def _coerce_positive_int(value, fallback=None):
        try:
            minutes = int(value)
            return minutes if minutes > 0 else fallback
        except Exception:  # noqa: BLE001
            return fallback

    config = load_config()
    auth_section = config.get("auth") or {}
    config_value = _coerce_positive_int(
        auth_section.get("access_token_expire_minutes"), None
    )

    if config_value:
        logger.info(
            "Token expiration loaded from config.yaml: %s minutes", config_value
        )
        return config_value

    env_value = _coerce_positive_int(
        os.getenv("DECIDERO_ACCESS_TOKEN_EXPIRE_MINUTES"), None
    )
    if env_value:
        logger.info("Token expiration loaded from environment: %s minutes", env_value)
        return env_value

    logger.info("Token expiration using default: %s minutes", default)
    return default


SECRET_KEY = os.getenv("DECIDERO_JWT_SECRET_KEY")
ALGORITHM = "HS256"
JWT_ISSUER = os.getenv("DECIDERO_JWT_ISSUER", "decidero")
ACCESS_TOKEN_EXPIRE_MINUTES = _get_access_token_expire_minutes()

# Validate and set up the secret key
if not SECRET_KEY:
    # In production, require an explicit secret key instead of generating ephemeral keys.
    if _is_production_mode():
        raise RuntimeError(
            "Missing DECIDERO_JWT_SECRET_KEY while DECIDERO_ENV is set to production. "
            + "Configure a strong static secret before startup."
        )
    SECRET_KEY = generate_dev_key()
elif not validate_secret_key(SECRET_KEY):
    raise RuntimeError(
        "Invalid JWT secret key configuration. "
        + "The key must be at least 32 characters long. "
        + "Update DECIDERO_JWT_SECRET_KEY in your environment variables."
    )
else:
    logger.info("JWT secret key validated and loaded from environment.")

# Warn about token expiration configuration
if ACCESS_TOKEN_EXPIRE_MINUTES > 60:
    logger.warning(
        f"Long token expiration time configured: {ACCESS_TOKEN_EXPIRE_MINUTES} minutes. "
        + "Consider reducing this value for better security."
    )

# --- Token Utilities ---


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Creates a new JWT access token.
    The 'sub' (subject) of the token should be the user's unique identifier (login/username).
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
        logger.debug(f"Token expiration set with custom delta: {expires_delta}")
    else:
        expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        logger.debug(
            f"Token expiration set with default minutes: {ACCESS_TOKEN_EXPIRE_MINUTES}"
        )

    to_encode.update(
        {
            "exp": expire,
            "iat": datetime.now(UTC),
            "iss": JWT_ISSUER,
        }
    )

    try:
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        logger.info(f"Successfully created access token for subject: {data.get('sub')}")
        return encoded_jwt
    except Exception as e:
        logger.error(
            f"Error creating access token for subject {data.get('sub')}: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create access token due to an internal error.",
        )


async def get_token_from_cookie(request: Request) -> Optional[str]:
    """
    Extracts JWT token from the 'access_token' HTTPOnly cookie.
    Handles potential 'Bearer ' prefix.
    """
    token_with_prefix = request.cookies.get("access_token")
    if not token_with_prefix:
        logger.debug("No 'access_token' cookie found in request.")
        return None

    logger.debug(
        "Found access token cookie in request."
    )

    if token_with_prefix.startswith("Bearer "):
        token = token_with_prefix.split(" ", 1)[1]
        logger.debug("Stripped 'Bearer ' prefix from token.")
    else:
        token = token_with_prefix
        logger.debug("No 'Bearer ' prefix found in token cookie.")

    return token


# --- User Retrieval Dependencies ---


async def get_current_user(
    token: Optional[str] = Depends(get_token_from_cookie),
) -> str:
    """
    FastAPI dependency to get current user's identifier (login) from JWT token
    stored in an HTTPOnly cookie.
    Raises HTTPException if token is missing or invalid.
    Returns the login/username (subject) from the token.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials. Invalid or expired token.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if token is None:
        logger.warning(
            "Authentication required: No token found (via get_token_from_cookie)."
        )
        raise credentials_exception

    try:
        logger.debug("Attempting to decode JWT token for get_current_user.")
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=JWT_ISSUER,
            options={"verify_aud": False},
        )
        login: Optional[str] = payload.get("sub")

        if login is None:
            logger.error(
                "Token decoding error: 'sub' claim (login) missing in token payload."
            )
            raise credentials_exception

        logger.info(f"Token successfully decoded. User identified by login: {login}")
        return login
    except JWTError as e:
        logger.error(f"JWTError during token decoding: {str(e)}", exc_info=True)
        raise credentials_exception
    except Exception as e:
        logger.error(f"Unexpected error in get_current_user: {str(e)}", exc_info=True)
        # Generic error for unexpected issues
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred during authentication.",
        )


async def _get_current_user_model_optional(
    token: Optional[str], db: Session
) -> Optional[UserModel]:
    """
    Core logic to get the user model if a valid token is provided.
    Returns UserModel or None. Does not raise HTTPException directly for auth failures.
    """
    if not token:
        logger.debug("_get_current_user_model_optional: No token provided.")
        return None

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=JWT_ISSUER,
            options={"verify_aud": False},
        )
        login: Optional[str] = payload.get("sub")
        if login is None:
            logger.warning(
                "_get_current_user_model_optional: Token payload missing 'sub' (login)."
            )
            return None

        logger.debug(
            f"_get_current_user_model_optional: Attempting to fetch user '{login}' from DB."
        )
        user_crud = (
            UserManager()
        )  # Consider making UserManager a true dependency if it manages state
        user_crud.set_db(db)  # This pattern is okay for stateless managers
        user = user_crud.get_user_by_login(login)

        if user:
            logger.debug(
                f"_get_current_user_model_optional: User '{login}' found in DB."
            )
        else:
            logger.warning(
                f"_get_current_user_model_optional: User '{login}' not found in DB (token valid but user deleted?)."
            )
        return user
    except JWTError:
        logger.warning("_get_current_user_model_optional: JWT decode failure.")
        return None
    except Exception as e:
        logger.error(
            f"_get_current_user_model_optional: Unexpected error for token '{token[:10]}...': {str(e)}",
            exc_info=True,
        )
        return None  # Or re-raise if this should be a server error


async def get_optional_user_model_dependency(
    token: Optional[str] = Depends(get_token_from_cookie), db: Session = Depends(get_db)
) -> Optional[UserSchema]:
    """
    FastAPI dependency wrapper to get the optional UserModel.
    Uses Depends() for token and db, then calls the core logic.
    """
    logger.debug("get_optional_user_model_dependency called.")
    user = await _get_current_user_model_optional(token=token, db=db)
    return UserSchema.model_validate(user) if user else None


async def get_current_active_user(
    request: Request,
    current_user_login: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserSchema:
    """
    FastAPI dependency to get the full, active user from the database
    based on the login from a validated token. Returns a detached Pydantic
    model so templates and downstream logic can safely access attributes
    after the DB session closes.
    """
    logger.debug(
        f"get_current_active_user: Attempting to fetch active user for login: {current_user_login}"
    )

    cached_user = getattr(request.state, "user", None)
    if cached_user and getattr(cached_user, "login", None) == current_user_login:
        logger.debug(
            "get_current_active_user: Returning cached user from request state."
        )
        return cached_user

    user_crud = UserManager()
    user_crud.set_db(db)
    user = user_crud.get_user_by_login(current_user_login)

    if not user:
        logger.error(
            f"get_current_active_user: User with login '{current_user_login}' not found in DB, though token was valid."
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User associated with token not found.",
        )

    safe_user = UserSchema.model_validate(user)
    request.state.user = safe_user
    user_identifier = safe_user.email or safe_user.login
    logger.info(
        f"get_current_active_user: Successfully retrieved active user: {user_identifier}"
    )
    return safe_user


# --- Role and Permission Dependencies ---


async def get_user_role(
    current_user: UserSchema = Depends(get_current_active_user),
) -> UserRole:
    """
    FastAPI dependency that gets the role of the current active user.
    """
    if not current_user or not hasattr(current_user, "role") or not current_user.role:
        safe_id = getattr(current_user, "user_id", None) if current_user else None
        logger.error(
            "get_user_role: Could not determine role for user ID %s. User object or role attribute missing.",
            safe_id or "Unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User role could not be determined.",
        )
    try:
        role_enum = UserRole(
            current_user.role.lower()
        )  # Ensure role string matches Enum values (case-insensitive)
        identifier = current_user.email or current_user.login
        logger.debug(
            f"get_user_role: User '{identifier}' has role '{role_enum.value}'."
        )
        return role_enum
    except ValueError:
        identifier = current_user.email or current_user.login
        logger.error(
            f"get_user_role: Invalid role value '{current_user.role}' found for user '{identifier}'."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invalid role '{current_user.role}' configured for user.",
        )


# Define permission inheritance explicitly:
# - Participants: can view meetings.
# - Facilitators: everything participants can do + create/update/delete meetings.
# - Admins/Super Admins: everything facilitators can do + user/role management.
PARTICIPANT_PERMISSIONS: Set[Permission] = {Permission.VIEW_MEETING}
FACILITATOR_PERMISSIONS: Set[Permission] = PARTICIPANT_PERMISSIONS | {
    Permission.CREATE_MEETING,
    Permission.UPDATE_MEETING,
    Permission.DELETE_MEETING,
}
ADMIN_PERMISSIONS: Set[Permission] = FACILITATOR_PERMISSIONS | {
    Permission.MANAGE_USERS,
    Permission.MANAGE_ROLES,
}

ROLE_PERMISSIONS: Dict[UserRole, Set[Permission]] = {
    UserRole.SUPER_ADMIN: ADMIN_PERMISSIONS,
    UserRole.ADMIN: ADMIN_PERMISSIONS,
    UserRole.FACILITATOR: FACILITATOR_PERMISSIONS,
    UserRole.PARTICIPANT: PARTICIPANT_PERMISSIONS,
}


def has_permission(user_role: UserRole, required_permission: Permission) -> bool:
    """Checks if a user role has a specific permission."""
    permissions_for_role = ROLE_PERMISSIONS.get(user_role, [])
    has_perm = required_permission in permissions_for_role
    logger.debug(
        f"Permission check: Role '{user_role.value}' requires '{required_permission.value}'. Has permission: {has_perm}. Role permissions: {[p.value for p in permissions_for_role]}"
    )
    return has_perm


def check_permission(required_permission: Permission):
    """
    FastAPI dependency factory to check if the current user has a required permission.
    """

    async def _check_permission_dependency(
        user_role: UserRole = Depends(get_user_role),
    ):
        logger.debug(
            f"check_permission: Verifying permission '{required_permission.value}' for role '{user_role.value}'."
        )
        if not has_permission(user_role, required_permission):
            logger.warning(
                f"Access denied: Role '{user_role.value}' lacks required permission '{required_permission.value}'."
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You do not have permission to '{required_permission.value}'. Your role '{user_role.value}' is insufficient.",
            )
        logger.info(
            f"Access granted: Role '{user_role.value}' has required permission '{required_permission.value}'."
        )
        return True  # Or return user_role if needed downstream

    return _check_permission_dependency


def check_role(required_role: UserRole):
    """
    FastAPI dependency factory to check if the current user has a specific role.
    """

    async def _check_role_dependency(user_role: UserRole = Depends(get_user_role)):
        logger.debug(
            f"check_role: Verifying role. Required: '{required_role.value}', Actual: '{user_role.value}'."
        )
        if user_role != required_role:
            logger.warning(
                f"Access denied: User role '{user_role.value}' does not match required role '{required_role.value}'."
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access restricted. Role '{required_role.value}' is required, but you have role '{user_role.value}'.",
            )
        logger.info(
            f"Access granted: User role '{user_role.value}' matches required role '{required_role.value}'."
        )
        return True  # Or return user_role

    return _check_role_dependency


# --- Authentication Middleware ---

GRAB_ENDPOINT_PATH = "/__grab"

EXEMPT_PATHS = [
    "/login",  # HTML login page
    "/register",  # HTML registration page
    "/api/auth/login",  # API endpoint for form-based login (pages.py)
    "/api/auth/token",  # API endpoint for token generation
    "/api/auth/register",  # API endpoint for user registration
    "/api/auth/logout",  # API endpoint for logout
    "/health",  # Health check endpoint
    # Add other public API endpoints or pages if they shouldn't require auth
]
GUEST_EXEMPT_PATHS = [
    "/api/meetings/join",  # Allow guest join API without prior auth
]
STATIC_PATH_PREFIX = "/static/"  # Static files are inherently exempt


async def auth_middleware(request: Request, call_next):
    """
    Middleware to check user authentication via HTTPOnly cookie token.
    Redirects unauthenticated users to '/login' for protected UI routes.
    Returns 401 for unauthenticated API calls to protected API routes.
    """
    path = request.url.path
    method = request.method
    logger.debug(f"Auth Middleware: Processing {method} request for path: {path}")

    # Check if path is exempt from authentication
    # Guest join is disabled by default; see config.yaml (auth.allow_guest_join).
    guest_join_enabled = get_guest_join_enabled()
    is_exempt = (
        path in EXEMPT_PATHS
        or (guest_join_enabled and path in GUEST_EXEMPT_PATHS)
        or path.startswith(STATIC_PATH_PREFIX)
        or path == "/"
    )  # Root might redirect to login
    if path == GRAB_ENDPOINT_PATH and is_grab_enabled():
        logger.info(
            "Auth Middleware: Allowing /__grab access because grab tooling is enabled."
        )
        is_exempt = True

    if is_exempt:
        logger.info(f"Auth Middleware: Path '{path}' is exempt. Allowing access.")
        response = await call_next(request)
        return response

    logger.debug(
        f"Auth Middleware: Path '{path}' requires authentication. Checking token."
    )
    token = await get_token_from_cookie(request)

    user: Optional[UserModel] = None
    db: Optional[Session] = None  # Initialize db to None

    if token:
        try:
            # Check if there's a dependency override for get_db (used in tests)
            # This ensures the middleware uses the same session context as the tests
            # from app.main import app # Removed re-import of app
            if get_db in request.app.dependency_overrides:  # Use request.app
                # Use the overridden dependency (test session)
                db_dependency = request.app.dependency_overrides[
                    get_db
                ]  # Use request.app
                db = db_dependency()
                logger.debug(
                    "Auth Middleware: Using overridden database session (test context)."
                )
            else:
                # Use the normal get_db dependency
                db = next(get_db())
                logger.debug("Auth Middleware: Using normal database session.")

            logger.debug(
                "Auth Middleware: Token found in cookie. Validating and fetching user."
            )
            user = await _get_current_user_model_optional(token=token, db=db)
            if user:
                safe_user = UserSchema.model_validate(user)
                request.state.user = safe_user
                user_identifier = safe_user.email or safe_user.login
                logger.info(
                    f"Auth Middleware: Token valid. User '{user_identifier}' authenticated for path '{path}'."
                )
            else:
                logger.warning(
                    f"Auth Middleware: Token found but invalid or user not found for path '{path}'."
                )
        except Exception as e:
            logger.error(
                f"Auth Middleware: Unexpected error during token validation for path '{path}': {str(e)}",
                exc_info=True,
            )
            # Decide if this should be a 500 error or treat as unauthenticated
            user = None  # Treat as unauthenticated on error
        finally:
            # Only close the session if it's not from a dependency override (test sessions are managed by the test framework)
            if db and get_db not in request.app.dependency_overrides:  # Use request.app
                db.close()  # Ensure DB session is always closed
                logger.debug("Auth Middleware: Database session closed.")
            elif db:
                logger.debug(
                    "Auth Middleware: Test database session left open (managed by test framework)."
                )
    else:
        logger.info(f"Auth Middleware: No token found for protected path '{path}'.")

    if user is None:  # Unauthenticated access to a protected route
        logger.warning(
            f"Auth Middleware: Unauthenticated access attempt to protected path: {path}"
        )
        if path.startswith("/api/"):
            logger.info(
                f"Auth Middleware: Returning 401 UNAUTHORIZED for API path: {path}"
            )
            # For API routes, return 401 without raising to keep middleware errors from surfacing as 500
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Not authenticated to access this API endpoint."},
                headers={
                    "WWW-Authenticate": "Bearer"
                },  # Though cookie auth, Bearer is conventional
            )
        else:
            # For UI routes, redirect to login
            logger.info(
                f"Auth Middleware: Redirecting to /login for UI path: {path} due to authentication failure."
            )
            # Use a neutral message so first-time visitors don't see a password error
            query_params: Dict[str, str] = {"message": "login_required"}
            if path and path != "/":  # Avoid adding 'next=/' for root path
                query_params["next"] = path
            redirect_url = f"/login?{urlencode(query_params)}"
            return RedirectResponse(
                url=redirect_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT
            )

    # User is authenticated, proceed with the request
    cached_user = getattr(request.state, "user", None)
    user_identifier = (
        getattr(cached_user, "email", None)
        or getattr(cached_user, "login", None)
        or "unknown"
    )
    logger.debug(
        f"Auth Middleware: User '{user_identifier}' authenticated. Proceeding with request to '{path}'."
    )
    response = await call_next(request)
    return response


# Ensure all functions intended for export are in __all__
__all__ = [
    "create_access_token",
    "get_token_from_cookie",
    "get_current_user",
    "get_optional_user_model_dependency",
    "_get_current_user_model_optional",  # Might be useful for direct use in some specific cases
    "get_current_active_user",
    "get_user_role",
    "check_permission",
    "check_role",
    "auth_middleware",  # Renamed from check_auth_middleware for clarity
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    "SECRET_KEY",  # Exporting for potential use elsewhere, though generally encapsulated
    "ALGORITHM",
    "JWT_ISSUER",
]
