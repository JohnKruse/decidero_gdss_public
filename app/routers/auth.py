from fastapi import APIRouter, Depends, HTTPException, status, Response
from datetime import timedelta
from typing import Dict
from pydantic import BaseModel

# Moved from below
from app.utils.password_validation import validate_password

from app.auth.auth import (
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    get_current_active_user,
)
from app.utils.security import get_password_hash
from app.data.user_manager import UserManager, get_user_manager
from app.database import get_db
from sqlalchemy.orm import Session
from app.schemas.schemas import LoginResponse
from app.schemas.user import UserCreate
from app.config.loader import get_secure_cookies_enabled

router = APIRouter(prefix="/api/auth", tags=["authentication"])


class TokenRequest(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@router.post("/token", response_model=LoginResponse)
async def login_for_access_token(
    response: Response,
    token_request: TokenRequest,
    db: Session = Depends(get_db),
    user_manager: UserManager = Depends(get_user_manager),
) -> LoginResponse:
    """
    Token login using JSON body for credentials.
    Sets an HTTPOnly cookie with the access token.
    """
    username = token_request.username
    password = token_request.password

    print(f"Attempting login for username: {username}")
    print(f"Password provided: {'********' if password else 'No password provided'}")
    user = user_manager.verify_user_credentials(username, password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    needs_change = not user.password_changed

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user.login,
            "role": user.role,
            "needs_password_change": needs_change,
        },
        expires_delta=access_token_expires,
    )
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        secure=get_secure_cookies_enabled(),
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        path="/",
    )

    return LoginResponse(
        login_successful=True,
        needs_password_change=needs_change,
        role=user.role.lower(),
    )


@router.post("/change-password")
async def change_password(
    password_change: PasswordChange,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Dict[str, str]:
    """Change user password and mark it as changed."""
    user_manager = get_user_manager(db)
    if not user_manager.verify_user_credentials(
        current_user.login, password_change.current_password
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    new_hash = get_password_hash(password_change.new_password)

    success = user_manager.update_user(
        current_user.login, {"hashed_password": new_hash, "password_changed": True}
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update password",
        )

    return {
        "message": "Password updated successfully"
    }  # Added return statement for successful change


@router.post("/register")
async def register_user(
    user: UserCreate,
    db: Session = Depends(get_db),
    user_manager: UserManager = Depends(get_user_manager),
):
    # Validate password complexity
    is_valid, error_message = validate_password(user.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=error_message
        )

    # Hash the password
    hashed_password = get_password_hash(user.password)

    # Check if an admin user exists
    is_initial_setup = not user_manager.has_admin_user()

    # Determine user role
    role = "super_admin" if is_initial_setup else "participant"

    # Create the user
    try:
        # Use first_name and last_name directly from UserCreate
        user_manager.add_user(  # Removed `created_user =`
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            hashed_password=hashed_password,
            role=role,
            login=user.login,
            organization=user.organization,
        )

        return {"message": "User registered successfully. Please log in."}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/verify")
async def verify_email(
    token: str, user_manager: UserManager = Depends(get_user_manager)
):
    return {"message": "Email verification is disabled."}


@router.post("/logout")
async def logout(response: Response):
    """Logs the user out by clearing the access token cookie."""
    response.delete_cookie(
        key="access_token",
        path="/",
        httponly=True,
        secure=get_secure_cookies_enabled(),
        samesite="lax",
    )
    return {"message": "Logout successful"}
