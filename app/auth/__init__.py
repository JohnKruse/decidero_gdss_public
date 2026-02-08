from .auth import (
    create_access_token,
    get_token_from_cookie,
    get_current_user,
    get_optional_user_model_dependency,
    _get_current_user_model_optional,  # If it's intended to be used directly elsewhere
    get_current_active_user,
    get_user_role,
    check_permission,
    check_role,
    auth_middleware,  # Renamed middleware
    ACCESS_TOKEN_EXPIRE_MINUTES,
    SECRET_KEY,
    ALGORITHM,
)

__all__ = [
    "create_access_token",
    "get_token_from_cookie",
    "get_current_user",
    "get_optional_user_model_dependency",
    "_get_current_user_model_optional",
    "get_current_active_user",
    "get_user_role",
    "check_permission",
    "check_role",
    "auth_middleware",
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    "SECRET_KEY",
    "ALGORITHM",
]
