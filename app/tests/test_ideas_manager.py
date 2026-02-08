import pytest
from sqlalchemy.orm import Session
from app.data.ideas_manager import IdeasManager
from app.models.user import User, UserRole
from app.models.meeting import Meeting
from app.models.idea import Idea
from app.utils.security import get_password_hash  # For creating test users
from app.utils.identifiers import generate_user_id, generate_meeting_id


@pytest.fixture
def ideas_manager_instance():
    return IdeasManager()


@pytest.fixture
def test_user(db_session: Session) -> User:
    user_id = generate_user_id(db_session, "Test", "User")
    user = User(
        user_id=user_id,
        email="testuser@example.com",
        login="testuser",
        hashed_password=get_password_hash("ValidPassword123!"),
        first_name="Test",
        last_name="User",
        role=UserRole.PARTICIPANT.value,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_meeting(db_session: Session, test_user: User) -> Meeting:
    meeting = Meeting(
        meeting_id=generate_meeting_id(db_session),
        title="Brainstorming Session",
        description="A meeting for innovative ideas.",
        owner_id=test_user.user_id,
        status="active",
    )
    meeting.owner = test_user
    db_session.add(meeting)
    db_session.commit()
    db_session.refresh(meeting)
    return meeting


def test_add_idea(
    ideas_manager_instance: IdeasManager,
    db_session: Session,
    test_user: User,
    test_meeting: Meeting,
):
    idea_data = {
        "content": "This is a revolutionary idea!",
        "submitted_name": "Test User",
    }
    new_idea = ideas_manager_instance.add_idea(
        db=db_session,
        meeting_id=test_meeting.meeting_id,
        user_id=test_user.user_id,
        idea_data=idea_data,
    )
    assert new_idea is not None
    assert new_idea.id is not None
    assert new_idea.content == idea_data["content"]
    assert new_idea.meeting_id == test_meeting.meeting_id
    assert new_idea.user_id == test_user.user_id
    assert new_idea.submitted_name == "Test User"


def test_get_ideas_for_meeting(
    ideas_manager_instance: IdeasManager,
    db_session: Session,
    test_user: User,
    test_meeting: Meeting,
):
    idea_data1 = {"content": "Idea Alpha", "submitted_name": "Alpha"}
    idea_data2 = {"content": "Idea Beta", "submitted_name": "Beta"}
    ideas_manager_instance.add_idea(
        db_session, test_meeting.meeting_id, test_user.user_id, idea_data1
    )
    ideas_manager_instance.add_idea(
        db_session, test_meeting.meeting_id, test_user.user_id, idea_data2
    )

    ideas_list = ideas_manager_instance.get_ideas_for_meeting(
        db_session, test_meeting.meeting_id
    )
    assert len(ideas_list) == 2
    contents = {idea.content for idea in ideas_list}
    assert "Idea Alpha" in contents
    assert "Idea Beta" in contents


def test_get_idea(
    ideas_manager_instance: IdeasManager,
    db_session: Session,
    test_user: User,
    test_meeting: Meeting,
):
    idea_data = {"content": "Specific Idea", "submitted_name": "Specific"}
    created_idea = ideas_manager_instance.add_idea(
        db_session, test_meeting.meeting_id, test_user.user_id, idea_data
    )
    assert created_idea is not None

    fetched_idea = ideas_manager_instance.get_idea(db_session, created_idea.id)
    assert fetched_idea is not None
    assert fetched_idea.id == created_idea.id
    assert fetched_idea.content == "Specific Idea"


def test_update_idea(
    ideas_manager_instance: IdeasManager,
    db_session: Session,
    test_user: User,
    test_meeting: Meeting,
):
    idea_data = {"content": "Original Content", "submitted_name": "Original"}
    created_idea = ideas_manager_instance.add_idea(
        db_session, test_meeting.meeting_id, test_user.user_id, idea_data
    )
    assert created_idea is not None

    updated_data = {"content": "Updated Content"}
    updated_idea = ideas_manager_instance.update_idea(
        db_session, created_idea.id, updated_data
    )
    assert updated_idea is not None
    assert updated_idea.content == "Updated Content"
    assert updated_idea.updated_at is not None  # Check if timestamp was updated

    # Verify in DB
    final_idea = db_session.query(Idea).filter(Idea.id == created_idea.id).first()
    assert final_idea.content == "Updated Content"


def test_delete_idea(
    ideas_manager_instance: IdeasManager,
    db_session: Session,
    test_user: User,
    test_meeting: Meeting,
):
    idea_data = {"content": "Idea to Delete", "submitted_name": "Delete"}
    created_idea = ideas_manager_instance.add_idea(
        db_session, test_meeting.meeting_id, test_user.user_id, idea_data
    )
    assert created_idea is not None

    idea_id_to_delete = created_idea.id
    result = ideas_manager_instance.delete_idea(db_session, idea_id_to_delete)
    assert result is True

    deleted_idea_check = (
        db_session.query(Idea).filter(Idea.id == idea_id_to_delete).first()
    )
    assert deleted_idea_check is None


def test_add_idea_force_anonymous(
    ideas_manager_instance: IdeasManager,
    db_session: Session,
    test_user: User,
    test_meeting: Meeting,
):
    idea_data = {"content": "Anonymous insight"}
    created_idea = ideas_manager_instance.add_idea(
        db=db_session,
        meeting_id=test_meeting.meeting_id,
        user_id=test_user.user_id,
        idea_data=idea_data,
        force_anonymous_name=True,
    )
    assert created_idea is not None
    assert created_idea.submitted_name == "Anonymous"
