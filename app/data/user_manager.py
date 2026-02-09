import logging
from sqlalchemy.orm import Session
from fastapi import Depends
from ..database import get_db
from sqlalchemy import func, or_
from typing import Dict, Optional, List, Any, Iterable, Tuple
import uuid
import hashlib
import secrets

from ..models.user import User, UserRole  # Import UserRole
from ..utils.security import get_password_hash, verify_password
from ..utils.identifiers import generate_user_id
from ..services.avatar_catalog import is_valid_avatar_key, pick_avatar_key

# Note: Removed imports for pandas, json, os, BaseManager

logger = logging.getLogger("auth")


def get_initials(first_name: str, last_name: str) -> str:
    """Extracts initials from the first and last names."""
    if not first_name and not last_name:
        return ""
    first_initial = first_name[0].upper() if first_name else ""
    last_initial = last_name[0].upper() if last_name else ""
    return f"{first_initial}{last_initial}"


def _color_from_seed(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    r = 40 + (digest[0] % 176)
    g = 40 + (digest[1] % 176)
    b = 40 + (digest[2] % 176)
    return f"#{r:02X}{g:02X}{b:02X}"


def assign_unique_avatar_color(db: Session, user_id: str) -> str:
    """Assign a color that is stable for user_id and unique within existing users."""
    used = {
        str(color).strip().upper()
        for (color,) in db.query(User.avatar_color)
        .filter(User.avatar_color.isnot(None))
        .all()
        if color and str(color).strip()
    }
    attempt = 0
    while True:
        seed = user_id if attempt == 0 else f"{user_id}:{attempt}"
        color = _color_from_seed(seed)
        if color.upper() not in used:
            return color
        attempt += 1


def generate_random_avatar_color(current_color: Optional[str] = None) -> str:
    """Generate a random avatar color, avoiding the current color when possible."""
    normalized_current = (
        str(current_color).strip().upper()
        if isinstance(current_color, str) and current_color.strip()
        else None
    )
    for _ in range(8):
        color = f"#{secrets.randbelow(0x1000000):06X}"
        if not normalized_current or color.upper() != normalized_current:
            return color
    return _color_from_seed(f"fallback:{uuid.uuid4().hex}")


def generate_svg(initials: str, color: str) -> str:
    """Generates the SVG XML string."""
    svg = f"""
    <svg width="120" height="120" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="60" cy="60" r="50" fill="{color}"/>
    <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-size="40" font-family="Verdana" fill="white">{initials}</text>
    </svg>
    """
    return svg.strip()


class UserManager:
    """Manages user data using SQLAlchemy."""

    def __init__(self):
        self.db = None

    def set_db(self, db: Session):
        """Set the database session."""
        self.db = db

    def _resolve_avatar_key(self, user_id: str, avatar_seed: int) -> Optional[str]:
        key = pick_avatar_key(user_id=user_id, avatar_seed=avatar_seed)
        if key and is_valid_avatar_key(key):
            return key
        return None

    def _ensure_avatar_state(self, user: User, commit: bool = False) -> User:
        changed = False
        if getattr(user, "avatar_seed", None) is None:
            user.avatar_seed = 0
            changed = True

        if not getattr(user, "avatar_color", None):
            user.avatar_color = assign_unique_avatar_color(self.db, user.user_id)
            changed = True

        current_key = getattr(user, "avatar_key", None)
        if not current_key or not is_valid_avatar_key(current_key):
            user.avatar_key = self._resolve_avatar_key(
                user_id=user.user_id,
                avatar_seed=int(getattr(user, "avatar_seed", 0) or 0),
            )
            changed = True

        if changed and commit:
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
        return user

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user data by email (case-insensitive)."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Attempting to get user with email: {email}")
        if not email:
            logger.warning(f"[{req_id}] No email provided.")
            return None
        clean_email = email.strip().lower()
        user = self.db.query(User).filter(func.lower(User.email) == clean_email).first()
        if user:
            self._ensure_avatar_state(user, commit=False)
            logger.info(f"[{req_id}] User found with email: {email}")
        else:
            logger.warning(f"[{req_id}] User not found with email: {email}")
        return user

    def get_user_by_login(self, login: str) -> Optional[User]:
        """Get user data by login/username (case-insensitive)."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Attempting to get user with login: {login}")
        if not login:
            logger.warning(f"[{req_id}] No login provided.")
            return None
        clean_login = login.strip().lower()
        user = self.db.query(User).filter(func.lower(User.login) == clean_login).first()
        if user:
            self._ensure_avatar_state(user, commit=False)
            logger.info(f"[{req_id}] User found with login: {login}")
        else:
            logger.warning(f"[{req_id}] User not found with login: {login}")
        return user

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user data by primary key user_id."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Attempting to get user with user_id: {user_id}")
        user = self.db.query(User).filter(User.user_id == user_id).first()
        if user:
            self._ensure_avatar_state(user, commit=False)
            logger.info(f"[{req_id}] User found with user_id: {user_id}")
        else:
            logger.warning(f"[{req_id}] User not found with user_id: {user_id}")
        return user

    def verify_user_credentials(self, identifier: str, password: str) -> Optional[User]:
        """
        Verify user credentials using login or email (case-insensitive).
        Returns the User object if credentials are valid, otherwise None.
        """
        req_id = uuid.uuid4()
        logger.debug(
            f"[{req_id}] Attempting to verify credentials for identifier: {identifier}"
        )
        if not identifier or not password:
            logger.warning(f"[{req_id}] Identifier or password not provided.")
            return None

        clean_identifier = identifier.strip()
        user = self.get_user_by_login(clean_identifier)
        if not user:
            user = self.get_user_by_email(clean_identifier)

        # If user found and password matches, return user
        if user and verify_password(password.strip(), user.hashed_password):
            return user

        # Otherwise, authentication failed
        logger.warning(f"[{req_id}] Failed login attempt for identifier: {identifier}")
        return None

    def user_exists(
        self, email: str
    ) -> bool:  # Added this method back, was removed inadvertently
        """Check if a user exists by email (case-insensitive)."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Checking if user exists with email: {email}")
        if not email:
            logger.info(f"[{req_id}] User exists: False for email: {email}")
            return False
        exists = self.get_user_by_email(email) is not None
        logger.info(f"[{req_id}] User exists: {exists} for email: {email}")
        return exists

    def login_exists(self, login: str) -> bool:
        """Check if a user exists by login (case-insensitive)."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Checking if user exists with login: {login}")
        exists = self.get_user_by_login(login) is not None
        logger.info(f"[{req_id}] User exists: {exists} for login: {login}")
        return exists

    def add_user(
        self,
        first_name: str,
        last_name: str,
        email: str,
        hashed_password: str,
        role: str = UserRole.PARTICIPANT.value,
        login: Optional[str] = None,
        organization: Optional[str] = None,
    ) -> User:
        """Add a new user to the database. Returns the created User model. Raises ValueError if user exists."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Adding user with email: {email}")
        raw_email = email.strip() if email else None
        clean_email = raw_email.lower() if raw_email else None
        proposed_login = (
            login or (clean_email.split("@")[0] if clean_email else "")
        ).strip()

        if not proposed_login:
            logger.warning(
                f"[{req_id}] No login provided or derivable for user with email: {email}"
            )
            raise ValueError("A login/username is required to create a user.")

        clean_login = proposed_login.lower()
        if clean_email and self.user_exists(clean_email):
            logger.warning(
                f"[{req_id}] Attempt to add existing user with email: {clean_email}"
            )
            raise ValueError(f"User with email {clean_email} already exists.")
        if self.login_exists(clean_login):
            logger.warning(
                f"[{req_id}] Attempt to add existing user with login: {clean_login}"
            )
            raise ValueError(f"User with login {clean_login} already exists.")
        new_user_id = generate_user_id(self.db, first_name, last_name)
        avatar_color = assign_unique_avatar_color(self.db, new_user_id)
        avatar_seed = 0
        avatar_key = self._resolve_avatar_key(new_user_id, avatar_seed)
        initials = get_initials(first_name, last_name)
        profile_svg = generate_svg(initials, avatar_color)
        # Email verification is disabled; mark all users as verified and skip tokens.
        is_verified = True
        verification_token = None

        db_user = User(
            user_id=new_user_id,
            email=clean_email,
            first_name=first_name,
            last_name=last_name,
            login=clean_login,
            hashed_password=hashed_password,
            role=role,  # Keep role as provided (should be lowercase to match UserRole enum)
            password_changed=False,  # Default for new user
            avatar_color=avatar_color,
            avatar_key=avatar_key,
            avatar_seed=avatar_seed,
            profile_svg=profile_svg,
            organization=organization,
            is_verified=is_verified,
            verification_token=verification_token,
        )

        try:
            self.db.add(db_user)
            self.db.commit()
            self.db.refresh(
                db_user
            )  # Refresh to get any server-side defaults updated on the instance.

            logger.info(
                f"[{req_id}] Successfully added user: {db_user.email} with user_id {db_user.user_id}"
            )
            return db_user
        except Exception as e:
            self.db.rollback()
            logger.error(f"[{req_id}] Error adding user {clean_email}: {str(e)}")
            raise  # Re-raise the exception to be handled by the caller

    def verify_user_email(self, token: str) -> bool:
        """Email verification is disabled; always return True."""
        logger.info("Email verification called but is disabled.")
        return True

    def get_user_count(self) -> int:
        """Get the total count of users."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Getting user count.")
        try:
            count = self.db.query(User).count()
            logger.info(f"[{req_id}] User count: {count}")
            return count
        except Exception as e:
            logger.error(f"[{req_id}] Error getting user count: {str(e)}")
            return 0  # Return 0 or raise an exception

    def get_all_users(self) -> List[User]:
        """Get a list of all users without pagination."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Getting all users.")
        try:
            users = self.db.query(User).order_by(User.user_id).all()
            logger.info(f"[{req_id}] Returning {len(users)} users.")
            return users
        except Exception as e:
            logger.error(f"[{req_id}] Error getting all users: {str(e)}")
            return []  # Return empty list or raise an exception

    def search_users(self, query: str, limit: int = 10) -> List[User]:
        """Search users by login, first name, last name, or email (case-insensitive)."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Searching users. query='{query}', limit={limit}")
        try:
            if not query:
                return []
            cleaned = (query or "").strip()
            if len(cleaned) < 2:
                # Require minimum length to avoid full-table scans for 1-char queries
                return []

            limit = max(1, min(int(limit or 10), 50))
            pattern = f"%{cleaned}%"

            results = (
                self.db.query(User)
                .filter(
                    (User.login.ilike(pattern))
                    | (User.first_name.ilike(pattern))
                    | (User.last_name.ilike(pattern))
                    | (User.email.ilike(pattern))
                )
                .order_by(User.last_name.asc(), User.first_name.asc(), User.login.asc())
                .limit(limit)
                .all()
            )
            logger.info(f"[{req_id}] Found {len(results)} users matching '{cleaned}'.")
            return results
        except Exception as e:
            logger.error(f"[{req_id}] Error searching users: {str(e)}")
            return []

    def query_directory(
        self,
        search: Optional[str] = None,
        roles: Optional[Iterable[str]] = None,
        include_inactive: bool = False,
        sort: str = "name",
        page: int = 1,
        page_size: int = 25,
    ) -> Tuple[List[User], int]:
        """Return paginated users for the participant directory along with the total count."""
        req_id = uuid.uuid4()
        logger.debug(
            "[%s] Directory query search='%s' roles=%s include_inactive=%s sort=%s page=%s page_size=%s",
            req_id,
            search,
            roles,
            include_inactive,
            sort,
            page,
            page_size,
        )

        try:
            safe_page = max(1, int(page or 1))
            safe_page_size = max(1, min(int(page_size or 25), 100))

            query = self.db.query(User)
            if not include_inactive:
                query = query.filter(User.is_active.is_(True))

            if roles:
                normalized_roles = {
                    str(role).lower() for role in roles if str(role).strip()
                }
                if normalized_roles:
                    query = query.filter(func.lower(User.role).in_(normalized_roles))

            cleaned = (search or "").strip()
            if cleaned:
                pattern = f"%{cleaned.lower()}%"
                query = query.filter(
                    or_(
                        func.lower(User.login).like(pattern),
                        func.lower(func.coalesce(User.first_name, "")).like(pattern),
                        func.lower(func.coalesce(User.last_name, "")).like(pattern),
                        func.lower(func.coalesce(User.email, "")).like(pattern),
                    )
                )

            total = query.count()
            query = self._apply_directory_sort(query, sort)

            offset = (safe_page - 1) * safe_page_size
            items = query.offset(offset).limit(safe_page_size).all()
            logger.debug(
                "[%s] Directory query returning %s items (total=%s)",
                req_id,
                len(items),
                total,
            )
            return items, total
        except Exception as exc:
            logger.error("[%s] Error querying directory: %s", req_id, exc)
            return [], 0

    def _apply_directory_sort(self, query, sort: str):
        """Apply sort ordering for directory queries."""
        sort_key = (sort or "name").lower()
        first_name_col = func.lower(func.coalesce(User.first_name, ""))
        last_name_col = func.lower(func.coalesce(User.last_name, ""))
        login_col = func.lower(func.coalesce(User.login, ""))

        if sort_key == "role":
            return query.order_by(
                func.lower(User.role), first_name_col, last_name_col, login_col
            )
        if sort_key == "login":
            return query.order_by(login_col)
        return query.order_by(first_name_col, last_name_col, login_col)

    def get_user_count_by_role(self, role: UserRole) -> int:
        """Get the count of users for a specific role."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Getting user count by role: {role}")
        try:
            count = self.db.query(User).filter(User.role == role).count()
            logger.info(f"[{req_id}] User count for role {role.value}: {count}")
            return count
        except Exception as e:
            logger.error(
                f"[{req_id}] Error getting user count for role {role.value}: {str(e)}"
            )
            return 0

    def get_admin_count(self) -> int:
        """Get the count of admin users."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Getting admin count.")
        count = (
            self.db.query(User)
            .filter(User.role.in_([UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value]))
            .count()
        )
        logger.info(f"[{req_id}] Admin count: {count}")
        return count

    def get_facilitator_count(self) -> int:
        """Get the count of facilitator users."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Getting facilitator count.")
        count = self.get_user_count_by_role(UserRole.FACILITATOR)
        logger.info(f"[{req_id}] Facilitator count: {count}")
        return count

    def get_participant_count(self) -> int:
        """Get the count of participant users."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Getting participant count.")
        count = self.get_user_count_by_role(UserRole.PARTICIPANT)
        logger.info(f"[{req_id}] Participant count: {count}")
        return count

    def update_user(
        self, user_identifier: str, updated_data: Dict[str, Any]
    ) -> Optional[User]:
        """Update user data. Only supports updating the about_me field."""
        req_id = uuid.uuid4()
        logger.debug(
            f"[{req_id}] Updating user with identifier: {user_identifier}, updated_data: {updated_data}"
        )
        try:
            user = self.get_user_by_email(user_identifier)
            if not user:
                user = self.get_user_by_login(user_identifier)
            if not user:
                print(f"User not found for update: {user_identifier}")
                return None

            updates_made = False
            if "about_me" in updated_data and updated_data["about_me"] is not None:
                user.about_me = updated_data["about_me"]
                updates_made = True

            if (
                "organization" in updated_data
                and updated_data["organization"] is not None
            ):
                user.organization = updated_data["organization"]
                updates_made = True

            if "first_name" in updated_data and updated_data["first_name"] is not None:
                user.first_name = updated_data["first_name"]
                updates_made = True

            if "last_name" in updated_data and updated_data["last_name"] is not None:
                user.last_name = updated_data["last_name"]
                updates_made = True

            if "avatar_key" in updated_data and updated_data["avatar_key"] is not None:
                proposed_key = str(updated_data["avatar_key"]).strip()
                if not is_valid_avatar_key(proposed_key):
                    raise ValueError("Invalid avatar key.")
                user.avatar_key = proposed_key
                updates_made = True

            if updates_made:
                self.db.add(user)
                self.db.commit()
                self.db.refresh(user)
                print(f"Successfully updated user: {user.email}")
            else:
                print(f"No relevant updates provided for user: {user.email}")

            return user
        except Exception as e:
            self.db.rollback()
            print(f"Error updating user {user_identifier}: {str(e)}")
            return None

    def regenerate_avatar(self, user_identifier: str) -> Optional[User]:
        user = self.get_user_by_email(user_identifier) or self.get_user_by_login(
            user_identifier
        )
        if not user:
            return None

        current_seed = int(getattr(user, "avatar_seed", 0) or 0)
        next_seed = current_seed + 1
        user.avatar_seed = next_seed
        user.avatar_key = self._resolve_avatar_key(user.user_id, next_seed)
        if not user.avatar_color:
            user.avatar_color = assign_unique_avatar_color(self.db, user.user_id)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def regenerate_avatar_color(self, user_identifier: str) -> Optional[User]:
        user = self.get_user_by_email(user_identifier) or self.get_user_by_login(
            user_identifier
        )
        if not user:
            return None

        user.avatar_color = generate_random_avatar_color(getattr(user, "avatar_color", None))
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_user_role(self, identifier: str, role: str) -> Optional[User]:
        """Update a user's role."""
        req_id = uuid.uuid4()
        logger.debug(
            f"[{req_id}] Updating role for user identifier: {identifier} to {role}"
        )
        try:
            user = self.get_user_by_email(identifier)
            if not user:
                user = self.get_user_by_login(identifier)
            if not user:
                logger.warning(
                    f"[{req_id}] User not found for role update: {identifier}"
                )
                return None

            if user.role == role:
                logger.info(
                    f"[{req_id}] Role unchanged for user {identifier}: {role}"
                )
                return user

            user.role = role
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
            logger.info(
                f"[{req_id}] Updated role for user {identifier} to {role}"
            )
            return user
        except Exception as e:
            self.db.rollback()
            logger.error(
                f"[{req_id}] Error updating role for user {identifier}: {str(e)}"
            )
            return None

    def delete_user(self, identifier: str) -> bool:
        """Delete a user by identifier (email or login)."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Deleting user with identifier: {identifier}")
        try:
            user = self.get_user_by_email(identifier)
            if not user:
                user = self.get_user_by_login(identifier)
            if not user:
                print(f"User not found for deletion: {identifier}")
                return False

            self.db.delete(user)
            self.db.commit()
            print(f"Successfully deleted user: {identifier}")
            return True
        except Exception as e:
            self.db.rollback()
            print(f"Error deleting user {identifier}: {str(e)}")
            return False

    def _generate_unique_login(self, base_login: str) -> str:
        """Generate a unique login based on the provided base."""
        normalized = (base_login or "").strip().lower() or "user"
        candidate = normalized
        counter = 1
        while self.login_exists(candidate):
            counter += 1
            candidate = f"{normalized}{counter}"
        return candidate

    def batch_add_users_by_pattern(
        self,
        prefix: str,
        start: int,
        end: int,
        default_password: str,
        role: str,
        email_domain: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create users following a sequential login pattern."""
        req_id = uuid.uuid4()
        logger.debug(
            f"[{req_id}] batch_add_users_by_pattern called "
            f"prefix={prefix}, start={start}, end={end}, role={role}, domain={email_domain}"
        )
        if end < start:
            raise ValueError("end must be greater than or equal to start")

        width = max(2, len(str(abs(end))) if end > 0 else len(str(abs(start or 0))))
        hashed_password = get_password_hash(default_password)
        created_logins: List[str] = []
        skipped: List[str] = []

        for number in range(start, end + 1):
            login = f"{prefix}{number:0{width}d}"
            email_value = f"{login}@{email_domain}".lower() if email_domain else None

            if self.login_exists(login):
                skipped.append(login)
                continue
            if email_value and self.user_exists(email_value):
                skipped.append(login)
                continue

            try:
                new_user = self.add_user(
                    first_name=first_name or login,
                    last_name=last_name or "",
                    email=email_value,
                    hashed_password=hashed_password,
                    role=role,
                    login=login,
                )
                created_logins.append(new_user.login)
            except ValueError as exc:
                logger.warning(
                    "[%s] Skipping login %s due to validation error: %s",
                    req_id,
                    login,
                    exc,
                )
                skipped.append(login)

        result = {
            "created_count": len(created_logins),
            "created_logins": created_logins,
            "updated_count": 0,
            "updated_logins": [],
            "skipped": skipped,
        }
        logger.info(
            f"[{req_id}] batch_add_users_by_pattern created {result['created_count']} users, "
            f"skipped {len(skipped)}"
        )
        return result

    def batch_add_users_by_emails(
        self,
        emails: List[str],
        default_password: str,
        role: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Bulk add users by email list. Updates users without emails when logins match.
        """
        created_logins: List[str] = []
        updated_logins: List[str] = []
        hashed_default_password = (
            get_password_hash(default_password) if default_password else None
        )

        for raw_email in emails or []:
            clean_email = (raw_email or "").strip().lower()
            if not clean_email:
                continue

            existing_by_email = self.get_user_by_email(clean_email)
            if existing_by_email:
                logger.info("Skipping %s because email already exists", clean_email)
                continue

            email_login = clean_email
            existing_by_login = self.get_user_by_login(email_login)

            if existing_by_login and not existing_by_login.email:
                logger.info(
                    "Updating login %s with new email %s",
                    existing_by_login.login,
                    clean_email,
                )
                existing_by_login.email = clean_email
                existing_by_login.first_name = clean_email
                if last_name:
                    existing_by_login.last_name = last_name
                if role:
                    existing_by_login.role = role
                self.db.add(existing_by_login)
                self.db.commit()
                self.db.refresh(existing_by_login)
                updated_logins.append(existing_by_login.login)
                continue

            if existing_by_login:
                logger.info(
                    "Skipping %s because login already exists",
                    clean_email,
                )
                continue
            unique_login = email_login
            hashed_password = hashed_default_password or get_password_hash(
                default_password or "TempPassword123!"
            )
            try:
                new_user = self.add_user(
                    first_name=clean_email,
                    last_name=last_name or "",
                    email=clean_email,
                    hashed_password=hashed_password,
                    role=role,
                    login=unique_login,
                )
                created_logins.append(new_user.login)
            except ValueError as exc:
                logger.warning(
                    "Skipping %s due to validation error: %s", clean_email, exc
                )
                continue

        return {
            "created_count": len(created_logins),
            "updated_count": len(updated_logins),
            "created_logins": created_logins,
            "updated_logins": updated_logins,
        }

    def needs_password_change(self, identifier: str) -> bool:
        """Check if a user needs to change their password."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Checking if user needs password change: {identifier}")
        user = self.get_user_by_email(identifier) or self.get_user_by_login(identifier)
        if not user:
            return False  # Or raise an error? Depends on desired behavior
        return not user.password_changed

    def mark_password_changed(self, identifier: str) -> bool:
        """Mark that a user has changed their password."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Marking password changed for user: {identifier}")
        try:
            user = self.get_user_by_email(identifier) or self.get_user_by_login(
                identifier
            )
            if not user:
                print(f"User not found to mark password changed: {identifier}")
                return False

            if not user.password_changed:
                user.password_changed = True
                self.db.add(user)
                self.db.commit()
                print(f"Marked password changed for user: {identifier}")
            else:
                print(f"Password already marked as changed for user: {identifier}")
            return True
        except Exception as e:
            self.db.rollback()
            print(f"Error marking password changed for {identifier}: {str(e)}")
            return False

    def reset_password(self, identifier: str, new_password: str) -> bool:
        """Reset a user's password and require them to change it on next login."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Resetting password for identifier: {identifier}")
        try:
            user = self.get_user_by_email(identifier) or self.get_user_by_login(
                identifier
            )
            if not user:
                logger.warning(
                    f"[{req_id}] Cannot reset password; user '{identifier}' not found."
                )
                return False

            user.hashed_password = get_password_hash((new_password or "").strip())
            user.password_changed = False
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
            logger.info(f"[{req_id}] Password reset for user: {user.login}")
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(
                f"[{req_id}] Error resetting password for {identifier}: {str(e)}"
            )
            return False

        """
        Ensures that an admin user exists in the system.
        If no admin exists with the specified email, creates one.
        If an admin exists but password needs setting/resetting, updates password.
        """
        req_id = uuid.uuid4()
        try:
            logger.debug(f"[{req_id}] Ensuring admin exists with email: {admin_email}")
            admin = self.get_user_by_email(admin_email)

            if not admin:
                print(f"Admin user {admin_email} not found. Creating...")
                hashed_password = get_password_hash(admin_password.strip())
                self.add_user(
                    first_name="Admin",
                    last_name="User",
                    email=admin_email.strip(),
                    login=admin_email.strip().split("@")[
                        0
                    ],  # Provide a login for admin
                    hashed_password=hashed_password,
                    role=UserRole.ADMIN.value,  # Use enum value
                )
                print(f"Admin user {admin_email} created successfully.")
            elif admin.role != UserRole.ADMIN.value:  # Compare with enum value
                print(
                    f"User {admin_email} exists but is not an admin. Updating role..."
                )
                # Ensure update_user can handle role updates; current implementation only handles about_me
                # For now, this will print the message but not update the role through self.update_user
                # To fix, update_user method needs to be extended or a specific role update method created.
                # This test primarily focuses on ensure_admin_exists's creation path.
                admin.role = UserRole.ADMIN.value
                self.db.add(admin)
                self.db.commit()
                self.db.refresh(admin)
                print(f"Role for user {admin_email} updated to ADMIN.")
            else:
                # Optionally, update password if needed (e.g., if password_changed is False)
                # Or just ensure the role is correct
                print(f"Admin user {admin_email} already exists.")
                # Example: Update password if it hasn't been changed
                # if not admin.password_changed:
                #     print(f"Updating password for existing admin {admin_email}...")
                #     self.update_user(db, admin_email, {'password': admin_password.strip()})

        except Exception as e:
            logger.error(f"[{req_id}] Error ensuring admin exists: {str(e)}")
            self.db.rollback()
            raise
        finally:
            pass

    def ensure_admin_exists(self, admin_email: str, admin_password: str):
        req_id = uuid.uuid4()
        """
        Ensures that an admin user exists in the system.
        If no admin exists with the specified email, creates one.
        If an admin exists but password needs setting/resetting, updates password.
        """
        try:
            logger.debug(f"[{req_id}] Ensuring admin exists with email: {admin_email}")
            try:
                admin = self.get_user_by_email(admin_email)

                if not admin:
                    print(f"Admin user {admin_email} not found. Creating...")
                    hashed_password = get_password_hash(admin_password.strip())
                    is_initial = self.get_user_count() == 0
                    desired_role = (
                        UserRole.SUPER_ADMIN.value
                        if is_initial
                        else UserRole.ADMIN.value
                    )
                    self.add_user(
                        first_name="Admin",
                        last_name="User",
                        email=admin_email.strip(),
                        login=admin_email.strip().split("@")[
                            0
                        ],  # Provide a login for admin
                        hashed_password=hashed_password,
                        role=desired_role,  # Use enum value
                    )
                    print(f"Admin user {admin_email} created successfully.")
                elif admin.role not in {
                    UserRole.ADMIN.value,
                    UserRole.SUPER_ADMIN.value,
                }:
                    print(
                        f"User {admin_email} exists but is not an admin. Updating role..."
                    )
                    # Ensure update_user can handle role updates; current implementation only handles about_me
                    # For now, this will print the message but not update the role through self.update_user
                    # To fix, update_user method needs to be extended or a specific role update method created.
                    # This test primarily focuses on ensure_admin_exists's creation path.
                    admin.role = UserRole.ADMIN.value
                    self.db.add(admin)
                    self.db.commit()
                    self.db.refresh(admin)
                    print(f"Role for user {admin_email} updated to ADMIN.")
                else:
                    # Optionally, update password if needed (e.g., if password_changed is False)
                    # Or just ensure the role is correct
                    print(f"Admin user {admin_email} already exists.")
                    # Example: Update password if it hasn't been changed
                    # if not admin.password_changed:
                    #     print(f"Updating password for existing admin {admin_email}...")
                    #     self.update_user(db, admin_email, {'password': admin_password.strip()})
            except Exception as e:
                logger.error(f"[{req_id}] Error ensuring admin exists: {str(e)}")
                self.db.rollback()
                raise
            finally:
                pass
        except Exception as e:
            logger.error(
                f"[{req_id}] Outer try-except block: Error ensuring admin exists: {str(e)}"
            )
            self.db.rollback()
            raise

    # Note: Removed the singleton instance creation `user_manager = UserManager()`
    def register_user(
        self, first_name: str, last_name: str, email: str, hashed_password: str
    ) -> None:
        """Registers a new user with the default 'PARTICIPANT' role."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Registering user with email: {email}")
        clean_email = email.strip().lower()

        if self.user_exists(clean_email):
            logger.warning(
                f"[{req_id}] Attempt to register existing user with email: {clean_email}"
            )
            raise ValueError("Email already registered")
        self.add_user(
            first_name=first_name,
            last_name=last_name,
            email=clean_email,
            hashed_password=hashed_password,
            role="PARTICIPANT",
        )

    def has_admin_user(self) -> bool:
        """Check if any admin user exists."""
        req_id = uuid.uuid4()
        logger.debug(f"[{req_id}] Checking if any admin user exists.")
        has_admin = (
            self.db.query(User)
            .filter(User.role.in_([UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value]))
            .first()
            is not None
        )
        logger.info(f"[{req_id}] Has admin user: {has_admin}")
        return has_admin


def get_user_manager(db: Session = Depends(get_db)) -> UserManager:
    """Dependency provider for UserManager."""
    req_id = uuid.uuid4()
    logger.debug(f"[{req_id}] get_user_manager called")
    manager = UserManager()
    logger.debug(f"[{req_id}] get_user_manager received db: {db}")
    manager.set_db(db)
    logger.debug(
        f"[{req_id}] get_user_manager set db on manager instance: {manager.db}"
    )
    logger.debug(f"[{req_id}] Returning manager with db: {manager.db}")
    return manager


# user_manager = get_user_manager() # Removed global instance
