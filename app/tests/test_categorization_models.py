import pytest
from sqlalchemy.exc import IntegrityError

from app.models.categorization import (
    CategorizationAssignment,
    CategorizationAuditEvent,
    CategorizationBallot,
    CategorizationBucket,
    CategorizationFinalAssignment,
    CategorizationItem,
)
from app.models.meeting import Meeting
from app.models.user import User, UserRole


def _seed_owner_and_meeting(db_session, *, user_id: str, meeting_id: str):
    user = User(
        user_id=user_id,
        login=f"{user_id.lower()}@example.test",
        hashed_password="hash",
        role=UserRole.ADMIN.value,
    )
    meeting = Meeting(
        meeting_id=meeting_id,
        owner_id=user_id,
        title="Categorization Model Test",
        description="",
    )
    db_session.add_all([user, meeting])
    db_session.commit()


def test_categorization_models_roundtrip(db_session):
    meeting_id = "MTG-CAT-0001"
    activity_id = "MTG-CAT-0001-CATGRY-0001"
    user_id = "USR-CATMODA-001"
    _seed_owner_and_meeting(db_session, user_id=user_id, meeting_id=meeting_id)

    item = CategorizationItem(
        meeting_id=meeting_id,
        activity_id=activity_id,
        item_key="item-1",
        content="Seed idea",
        submitted_name="Pat",
        item_metadata={"tag": "seed"},
        source={"meeting_id": meeting_id, "activity_id": "UPSTREAM-0001"},
    )
    bucket = CategorizationBucket(
        meeting_id=meeting_id,
        activity_id=activity_id,
        category_id="UNSORTED",
        title="Unsorted",
        order_index=0,
        created_by=user_id,
    )
    assignment = CategorizationAssignment(
        meeting_id=meeting_id,
        activity_id=activity_id,
        item_key="item-1",
        category_id="UNSORTED",
        is_unsorted=True,
        assigned_by=user_id,
    )
    ballot = CategorizationBallot(
        meeting_id=meeting_id,
        activity_id=activity_id,
        user_id=user_id,
        item_key="item-1",
        category_id="UNSORTED",
        submitted=False,
    )
    final_assignment = CategorizationFinalAssignment(
        meeting_id=meeting_id,
        activity_id=activity_id,
        item_key="item-1",
        category_id="UNSORTED",
        resolved_by=user_id,
    )
    audit_event = CategorizationAuditEvent(
        meeting_id=meeting_id,
        activity_id=activity_id,
        actor_user_id=user_id,
        event_type="bucket_created",
        payload={"category_id": "UNSORTED"},
    )

    db_session.add_all([item, bucket, assignment, ballot, final_assignment, audit_event])
    db_session.commit()

    stored_item = (
        db_session.query(CategorizationItem)
        .filter_by(meeting_id=meeting_id, activity_id=activity_id, item_key="item-1")
        .one()
    )
    assert stored_item.content == "Seed idea"
    assert stored_item.item_metadata.get("tag") == "seed"

    stored_bucket = (
        db_session.query(CategorizationBucket)
        .filter_by(meeting_id=meeting_id, activity_id=activity_id, category_id="UNSORTED")
        .one()
    )
    assert stored_bucket.title == "Unsorted"


def test_categorization_item_unique_key_constraint(db_session):
    meeting_id = "MTG-CAT-0002"
    activity_id = "MTG-CAT-0002-CATGRY-0001"
    _seed_owner_and_meeting(
        db_session,
        user_id="USR-CATMODB-001",
        meeting_id=meeting_id,
    )

    first = CategorizationItem(
        meeting_id=meeting_id,
        activity_id=activity_id,
        item_key="dup-item",
        content="A",
        item_metadata={},
        source={},
    )
    second = CategorizationItem(
        meeting_id=meeting_id,
        activity_id=activity_id,
        item_key="dup-item",
        content="B",
        item_metadata={},
        source={},
    )
    db_session.add(first)
    db_session.commit()

    with db_session.begin_nested():
        db_session.add(second)
        with pytest.raises(IntegrityError):
            db_session.flush()
