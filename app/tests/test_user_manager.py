import pytest
from sqlalchemy.orm import Session
from app.data.user_manager import UserManager
from app.utils.security import get_password_hash
from app.models.user import UserRole

# Removed setup_module as encryption_manager is not directly tested here,
# and User Manager relies on password hashes, not direct encryption itself.


@pytest.fixture
def user_manager(db_session: Session) -> UserManager:
    manager = UserManager()
    manager.set_db(db_session)
    return manager


def test_add_and_get_user(user_manager: UserManager, db_session: Session):
    email = "testadd@example.com"
    first_name = "Test"
    last_name = "UserAdd"
    hashed_password = get_password_hash("ValidPassword123!")

    # Ensure user does not exist
    if user_manager.get_user_by_email(email):
        user_manager.delete_user(email)
        db_session.commit()

    added_user = user_manager.add_user(
        first_name=first_name,
        last_name=last_name,
        email=email,
        hashed_password=hashed_password,
        role=UserRole.PARTICIPANT.value,
    )
    db_session.commit()  # Commit after add
    assert added_user is not None
    assert added_user.email == email.lower()
    assert added_user.user_id.startswith("USR-")
    assert isinstance(added_user.avatar_color, str)
    assert added_user.avatar_color.startswith("#")
    assert len(added_user.avatar_color) == 7
    assert isinstance(added_user.avatar_seed, int)
    assert added_user.avatar_seed == 0
    assert isinstance(added_user.avatar_key, str)
    assert added_user.avatar_key.startswith("fluent-")
    assert isinstance(added_user.avatar_icon_path, str)
    assert added_user.avatar_icon_path.startswith("/static/avatars/fluent/icons/")

    fetched_user = user_manager.get_user_by_email(email)
    assert fetched_user is not None
    assert fetched_user.email == email.lower()
    assert fetched_user.first_name == first_name
    assert fetched_user.avatar_color == added_user.avatar_color
    assert fetched_user.avatar_key == added_user.avatar_key
    assert fetched_user.avatar_seed == 0
    assert fetched_user.is_verified is True
    assert fetched_user.verification_token is None


def test_add_user_assigns_unique_avatar_colors(
    user_manager: UserManager, db_session: Session
):
    user_one = user_manager.add_user(
        first_name="Color",
        last_name="One",
        email="color.one@example.com",
        hashed_password=get_password_hash("ValidPassword123!"),
        role=UserRole.PARTICIPANT.value,
        login="color.one",
    )
    user_two = user_manager.add_user(
        first_name="Color",
        last_name="Two",
        email="color.two@example.com",
        hashed_password=get_password_hash("ValidPassword123!"),
        role=UserRole.PARTICIPANT.value,
        login="color.two",
    )

    assert user_one.avatar_color is not None
    assert user_two.avatar_color is not None
    assert user_one.avatar_color != user_two.avatar_color


def test_update_user(user_manager: UserManager, db_session: Session):
    email = "testupdate@example.com"
    # Add user first
    if not user_manager.get_user_by_email(email):
        user_manager.add_user(
            first_name="TestUpdate",
            last_name="UserInitial",
            email=email,
            hashed_password=get_password_hash("ValidPassword123!"),
            role=UserRole.PARTICIPANT.value,
        )
        db_session.commit()

    updated_data = {"about_me": "Updated bio for testupdate"}
    updated_user = user_manager.update_user(email, updated_data)
    db_session.commit()  # Commit after update
    assert updated_user is not None
    assert updated_user.about_me == "Updated bio for testupdate"

    fetched_user = user_manager.get_user_by_email(email)
    assert fetched_user.about_me == "Updated bio for testupdate"


def test_regenerate_avatar_increments_seed(user_manager: UserManager, db_session: Session):
    login = "avatar.regen"
    user = user_manager.add_user(
        first_name="Avatar",
        last_name="Regen",
        email="avatar.regen@example.com",
        hashed_password=get_password_hash("ValidPassword123!"),
        role=UserRole.PARTICIPANT.value,
        login=login,
    )
    original_key = user.avatar_key
    original_seed = user.avatar_seed

    updated = user_manager.regenerate_avatar(login)
    assert updated is not None
    assert updated.avatar_seed == original_seed + 1
    assert updated.avatar_key is not None
    if updated.avatar_key == original_key:
        updated = user_manager.regenerate_avatar(login)
        assert updated is not None
        assert updated.avatar_seed == original_seed + 2
        assert updated.avatar_key != original_key


def test_delete_user(user_manager: UserManager, db_session: Session):
    email = "testdelete@example.com"
    # Add user first
    if not user_manager.get_user_by_email(email):
        user_manager.add_user(
            first_name="TestDelete",
            last_name="User",
            email=email,
            hashed_password=get_password_hash("ValidPassword123!"),
            role=UserRole.PARTICIPANT.value,
        )
        db_session.commit()

    assert user_manager.get_user_by_email(email) is not None

    delete_success = user_manager.delete_user(email)
    db_session.commit()  # Commit after delete
    assert delete_success is True

    assert user_manager.get_user_by_email(email) is None


def test_user_exists(user_manager: UserManager, db_session: Session):
    email_existing = "testexists@example.com"
    email_non_existing = "nonexistent@example.com"

    # Ensure existing user is there
    if not user_manager.get_user_by_email(email_existing):
        user_manager.add_user(
            first_name="TestExist",
            last_name="User",
            email=email_existing,
            hashed_password=get_password_hash("ValidPassword123!"),
            role=UserRole.PARTICIPANT.value,
        )
        db_session.commit()

    # Ensure non-existing user is not there
    if user_manager.get_user_by_email(email_non_existing):
        user_manager.delete_user(email_non_existing)
        db_session.commit()

    assert user_manager.user_exists(email_existing) is True
    assert user_manager.user_exists(email_non_existing) is False


def test_batch_add_users_by_emails_creates_new_user(
    user_manager: UserManager, db_session: Session
):
    result = user_manager.batch_add_users_by_emails(
        emails=["alice@example.com"],
        default_password="ValidPassword123!",
        role=UserRole.PARTICIPANT.value,
        first_name="Alice",
        last_name="Example",
    )

    assert result["created_count"] == 1
    assert result["updated_count"] == 0
    assert "alice@example.com" in result["created_logins"]
    created_user = user_manager.get_user_by_email("alice@example.com")
    assert created_user is not None
    assert created_user.login == "alice@example.com"
    assert created_user.first_name == "alice@example.com"


def test_batch_add_users_by_emails_updates_existing_login_without_email(
    user_manager: UserManager, db_session: Session
):
    # Pre-create a user with a login but no email
    user_manager.add_user(
        first_name="Sam",
        last_name="Placeholder",
        email=None,
        hashed_password=get_password_hash("ExistingPassword123!"),
        role=UserRole.PARTICIPANT.value,
        login="sam@example.com",
    )

    result = user_manager.batch_add_users_by_emails(
        emails=["sam@example.com"],
        default_password="ValidPassword123!",
        role=UserRole.PARTICIPANT.value,
        first_name="Sam",
        last_name="Updated",
    )

    assert result["created_count"] == 0
    assert result["updated_count"] == 1
    assert "sam@example.com" in result["updated_logins"]

    updated_user = user_manager.get_user_by_login("sam@example.com")
    assert updated_user.email == "sam@example.com"
    assert updated_user.password_changed is False
    assert updated_user.first_name == "sam@example.com"


def test_batch_add_users_by_emails_generates_unique_login_on_conflict(
    user_manager: UserManager, db_session: Session
):
    # Existing user already uses the full email as login
    user_manager.add_user(
        first_name="Jane",
        last_name="Original",
        email="jane@old.com",
        hashed_password=get_password_hash("ExistingPassword123!"),
        role=UserRole.PARTICIPANT.value,
        login="jane@old.com",
    )

    result = user_manager.batch_add_users_by_emails(
        emails=["jane@new.com"],
        default_password="ValidPassword123!",
        role=UserRole.FACILITATOR.value,
        first_name="Jane",
        last_name="New",
    )

    assert result["created_count"] == 1
    assert result["updated_count"] == 0
    assert result["created_logins"] == ["jane@new.com"]

    created_login = result["created_logins"][0]
    new_user = user_manager.get_user_by_email("jane@new.com")
    assert new_user is not None
    assert new_user.login == created_login


def test_add_user_without_email_is_verified(
    user_manager: UserManager, db_session: Session
):
    login = "noemailuser1"
    # Clean up any previous run
    existing = user_manager.get_user_by_login(login)
    if existing:
        user_manager.delete_user(login)
        db_session.commit()

    user = user_manager.add_user(
        first_name="No",
        last_name="Email",
        email=None,
        hashed_password=get_password_hash("ValidPassword123!"),
        role=UserRole.PARTICIPANT.value,
        login=login,
    )

    assert user.is_verified is True
    assert user.verification_token is None


def test_batch_add_users_by_pattern_verifies_users_without_email(
    user_manager: UserManager, db_session: Session
):
    prefix = "bulktest"
    start = 900
    end = 902
    # Ensure clean slate
    for number in range(start, end + 1):
        login = f"{prefix}{number:0{len(str(end))}d}"
        if user_manager.get_user_by_login(login):
            user_manager.delete_user(login)
    db_session.commit()

    result = user_manager.batch_add_users_by_pattern(
        prefix=prefix,
        start=start,
        end=end,
        default_password="ValidPassword123!",
        role=UserRole.PARTICIPANT.value,
        email_domain=None,
        first_name="Bulk",
        last_name="User",
    )

    assert result["created_count"] == (end - start + 1)
    for login in result["created_logins"]:
        created_user = user_manager.get_user_by_login(login)
        assert created_user is not None
        assert created_user.is_verified is True
