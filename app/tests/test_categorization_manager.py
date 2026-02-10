from app.models.categorization import (
    CategorizationAssignment,
    CategorizationAuditEvent,
    CategorizationBallot,
    CategorizationBucket,
    CategorizationItem,
)
from app.models.meeting import AgendaActivity, Meeting
from app.models.user import User, UserRole
from app.services.categorization_manager import (
    CategorizationManager,
    UNSORTED_CATEGORY_ID,
)


def _seed_context(db_session):
    user = User(
        user_id="USR-CATMGR-001",
        login="catmgr@example.test",
        hashed_password="hash",
        role=UserRole.ADMIN.value,
    )
    meeting = Meeting(
        meeting_id="MTG-CATMGR-0001",
        owner_id=user.user_id,
        title="Categorization Manager",
        description="",
    )
    activity = AgendaActivity(
        activity_id="MTG-CATMGR-0001-CATGRY-0001",
        meeting_id=meeting.meeting_id,
        tool_type="categorization",
        title="Categorize",
        order_index=1,
        tool_config_id="TL-MTG-CATMGR-0001-CATGRY-0001-01",
        config={
            "items": [
                {"id": "seed-1", "content": "Idea 1"},
                {"id": "seed-2", "content": "Idea 2"},
            ],
            "buckets": ["Bucket A", "Bucket B"],
        },
    )
    db_session.add_all([user, meeting, activity])
    db_session.commit()
    return user, meeting, activity


def test_seed_activity_creates_unsorted_items_buckets_and_assignments(db_session):
    user, meeting, activity = _seed_context(db_session)
    manager = CategorizationManager(db_session)

    seeded = manager.seed_activity(
        meeting_id=meeting.meeting_id,
        activity=activity,
        actor_user_id=user.user_id,
    )

    assert seeded["items"] == 2
    assert seeded["buckets"] == 2

    buckets = (
        db_session.query(CategorizationBucket)
        .filter(
            CategorizationBucket.meeting_id == meeting.meeting_id,
            CategorizationBucket.activity_id == activity.activity_id,
        )
        .all()
    )
    assert any(bucket.category_id == UNSORTED_CATEGORY_ID for bucket in buckets)

    items = (
        db_session.query(CategorizationItem)
        .filter(
            CategorizationItem.meeting_id == meeting.meeting_id,
            CategorizationItem.activity_id == activity.activity_id,
        )
        .all()
    )
    assert len(items) == 2

    assignments = (
        db_session.query(CategorizationAssignment)
        .filter(
            CategorizationAssignment.meeting_id == meeting.meeting_id,
            CategorizationAssignment.activity_id == activity.activity_id,
        )
        .all()
    )
    assert len(assignments) == 2
    assert all(item.category_id == UNSORTED_CATEGORY_ID for item in assignments)


def test_log_event_persists_payload(db_session):
    user, meeting, activity = _seed_context(db_session)
    manager = CategorizationManager(db_session)
    manager.log_event(
        meeting_id=meeting.meeting_id,
        activity_id=activity.activity_id,
        actor_user_id=user.user_id,
        event_type="item_moved",
        payload={"item_key": "seed-1", "to": "CAT-1"},
    )
    event = (
        db_session.query(CategorizationAuditEvent)
        .filter(
            CategorizationAuditEvent.meeting_id == meeting.meeting_id,
            CategorizationAuditEvent.activity_id == activity.activity_id,
            CategorizationAuditEvent.event_type == "item_moved",
        )
        .one()
    )
    assert event.payload["item_key"] == "seed-1"


def test_compute_agreement_metrics_thresholds_and_ties(db_session):
    user, meeting, activity = _seed_context(db_session)
    manager = CategorizationManager(db_session)
    manager.seed_activity(
        meeting_id=meeting.meeting_id,
        activity=activity,
        actor_user_id=user.user_id,
    )
    buckets = manager.list_buckets(meeting.meeting_id, activity.activity_id)
    target_bucket = next(
        bucket.category_id for bucket in buckets if bucket.category_id != UNSORTED_CATEGORY_ID
    )
    db_session.add_all(
        [
            User(
                user_id="USR-1",
                login="usr1@example.test",
                hashed_password="hash",
                role=UserRole.PARTICIPANT.value,
            ),
            User(
                user_id="USR-2",
                login="usr2@example.test",
                hashed_password="hash",
                role=UserRole.PARTICIPANT.value,
            ),
            User(
                user_id="USR-3",
                login="usr3@example.test",
                hashed_password="hash",
                role=UserRole.PARTICIPANT.value,
            ),
            User(
                user_id="USR-4",
                login="usr4@example.test",
                hashed_password="hash",
                role=UserRole.PARTICIPANT.value,
            ),
            User(
                user_id="USR-5",
                login="usr5@example.test",
                hashed_password="hash",
                role=UserRole.PARTICIPANT.value,
            ),
        ]
    )
    db_session.commit()

    db_session.add_all(
        [
            CategorizationBallot(
                meeting_id=meeting.meeting_id,
                activity_id=activity.activity_id,
                user_id="USR-1",
                item_key="seed-1",
                category_id=target_bucket,
                submitted=True,
            ),
            CategorizationBallot(
                meeting_id=meeting.meeting_id,
                activity_id=activity.activity_id,
                user_id="USR-2",
                item_key="seed-1",
                category_id=target_bucket,
                submitted=True,
            ),
            CategorizationBallot(
                meeting_id=meeting.meeting_id,
                activity_id=activity.activity_id,
                user_id="USR-3",
                item_key="seed-1",
                category_id=UNSORTED_CATEGORY_ID,
                submitted=True,
            ),
            CategorizationBallot(
                meeting_id=meeting.meeting_id,
                activity_id=activity.activity_id,
                user_id="USR-4",
                item_key="seed-2",
                category_id=target_bucket,
                submitted=True,
            ),
            CategorizationBallot(
                meeting_id=meeting.meeting_id,
                activity_id=activity.activity_id,
                user_id="USR-5",
                item_key="seed-2",
                category_id=UNSORTED_CATEGORY_ID,
                submitted=True,
            ),
        ]
    )
    db_session.commit()

    metrics = manager.compute_agreement_metrics(
        meeting_id=meeting.meeting_id,
        activity_id=activity.activity_id,
        agreement_threshold=0.6,
        minimum_ballots=2,
    )

    assert metrics["seed-1"]["top_category_id"] == target_bucket
    assert metrics["seed-1"]["top_share"] == 2 / 3
    assert metrics["seed-1"]["status_label"] == "AGREED"
    assert metrics["seed-2"]["top_count"] == 1
    assert metrics["seed-2"]["second_share"] == 0.5
    assert metrics["seed-2"]["margin"] == 0.0
    assert metrics["seed-2"]["status_label"] == "DISPUTED"


def test_create_bucket_uses_new_suffix_after_delete_and_reorder(db_session):
    user, meeting, activity = _seed_context(db_session)
    manager = CategorizationManager(db_session)
    manager.seed_activity(
        meeting_id=meeting.meeting_id,
        activity=activity,
        actor_user_id=user.user_id,
    )

    created = manager.create_bucket(
        meeting_id=meeting.meeting_id,
        activity_id=activity.activity_id,
        title="Bucket C",
        actor_user_id=user.user_id,
    )
    assert created.category_id.endswith(":bucket-3")

    manager.delete_bucket(
        meeting_id=meeting.meeting_id,
        activity_id=activity.activity_id,
        category_id=f"{activity.activity_id}:bucket-2",
        actor_user_id=user.user_id,
    )
    manager.reorder_buckets(
        meeting_id=meeting.meeting_id,
        activity_id=activity.activity_id,
        ordered_category_ids=[
            "UNSORTED",
            f"{activity.activity_id}:bucket-3",
            f"{activity.activity_id}:bucket-1",
        ],
        actor_user_id=user.user_id,
    )

    second = manager.create_bucket(
        meeting_id=meeting.meeting_id,
        activity_id=activity.activity_id,
        title="Bucket D",
        actor_user_id=user.user_id,
    )
    assert second.category_id.endswith(":bucket-4")
