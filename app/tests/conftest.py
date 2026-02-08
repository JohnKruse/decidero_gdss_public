import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import os

# Ensure tests always use HTTP-friendly cookies regardless of local config.yaml.
os.environ["DECIDERO_SECURE_COOKIES"] = "false"

from app.database import Base, get_db
from app.main import app
from app.data.user_manager import UserManager  # For admin user setup

# Test constants for admin credentials
ADMIN_EMAIL_FOR_TEST = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
ADMIN_PASSWORD_FOR_TEST = os.getenv("ADMIN_PASSWORD", "Admin@123!")
ADMIN_LOGIN_FOR_TEST = os.getenv("ADMIN_LOGIN", ADMIN_EMAIL_FOR_TEST.split("@")[0])

# Define a test database URL
TEST_DATABASE_URL = "sqlite:///:memory:"  # Use in-memory SQLite for tests
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session")
def create_test_tables():
    """Create all database tables once per session before tests run."""
    Base.metadata.create_all(bind=engine)
    yield
    # Base.metadata.drop_all(bind=engine) # Remove dropping tables


@pytest.fixture(scope="function")
def db_session(create_test_tables):  # Depends on table creation
    """
    Provides a transactional database session for a test.
    Rolls back changes after the test.
    Overrides the main app's get_db dependency.
    """
    connection = engine.connect()
    transaction = connection.begin()
    db = TestingSessionLocal(bind=connection)

    # Store original get_db dependency to restore later if necessary, though usually not for function scope
    original_get_db = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: db

    try:
        yield db
    finally:
        db.close()
        transaction.rollback()
        connection.close()
        # Restore original dependency or clear it
        if original_get_db:
            app.dependency_overrides[get_db] = original_get_db
        else:
            del app.dependency_overrides[get_db]


@pytest.fixture(scope="function")
def client(db_session: Session):  # client fixture now depends on db_session fixture
    """Provides a TestClient instance for making requests to the FastAPI app."""
    # The db_session fixture already handles overriding get_db for this function's scope
    with TestClient(app) as c:
        yield c


# Fixture specifically for tests that need the UserManager and default admin
@pytest.fixture(scope="function")
def user_manager_with_admin(db_session: Session):
    manager = UserManager()
    manager.set_db(db_session)

    # Since the first user becomes admin automatically, we just register normally
    # The registration logic will assign ADMIN role if no users exist
    from app.utils.security import get_password_hash

    hashed_password = get_password_hash(ADMIN_PASSWORD_FOR_TEST)

    admin_user = manager.add_user(
        first_name="Admin",
        last_name="User",
        email=ADMIN_EMAIL_FOR_TEST,
        hashed_password=hashed_password,
        role="admin",  # Explicitly set as admin for test consistency
        login=ADMIN_LOGIN_FOR_TEST,
    )
    db_session.commit()  # Ensure the admin user is committed

    # Expose the created admin user to test modules that expect a module-level reference.
    try:
        import sys

        test_module = sys.modules.get("app.tests.test_api_meetings")
        if test_module is not None:
            setattr(test_module, "admin_user", admin_user)
    except Exception:
        pass

    return manager


@pytest.fixture(scope="function")
def authenticated_client(client: TestClient, user_manager_with_admin: UserManager):
    """
    Provides a TestClient instance that is authenticated as an admin user.
    This fixture ensures the admin user exists and then logs them in via the API
    to obtain the necessary authentication cookie.
    """
    # The user_manager_with_admin fixture ensures the admin user is created and committed
    # Now, log in the admin user via the API to get the auth cookie
    login_data = {"username": ADMIN_LOGIN_FOR_TEST, "password": ADMIN_PASSWORD_FOR_TEST}

    # Make a request to the login endpoint to get the cookie
    response = client.post("/api/auth/token", json=login_data)
    assert response.status_code == 200

    # The 'access_token' cookie should be set by the login endpoint
    # The TestClient automatically manages cookies received in responses
    # so subsequent requests made with this 'client' instance will include the cookie.

    yield client  # Yield the client with the authentication cookie set


# The fixture named 'session' used in some tests, make it an alias for db_session
@pytest.fixture(scope="function")
def session(db_session: Session):
    yield db_session
