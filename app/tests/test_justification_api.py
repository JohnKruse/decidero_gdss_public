import asyncio
import os
from uuid import uuid4

from fastapi.testclient import TestClient

from app.models.meeting import AgendaActivity, Meeting
from app.models.user import User, UserRole
from app.services import meeting_state_manager
from app.utils.security import get_password_hash


_SEED = [
    {
        "option_id": "o1",
        "content": "Idea A",
        "median": 1.0,
        "iqr": 0.0,
        "outlier_flags": {"justify_outlier": True, "justify_clear": False},
        "ranks_by_user": {"justify_outlier": 9, "justify_clear": 1},
    },
    {
        "option_id": "o2",
        "content": "Idea B",
        "median": 2.0,
        "iqr": 1.0,
        "outlier_flags": {"justify_outlier": False, "justify_clear": False},
        "ranks_by_user": {"justify_outlier": 2, "justify_clear": 2},
    },
]


def _add_participant(_user_manager, db_session, *, user_id, login, password):
    user = User(
        user_id=user_id,
        first_name="Justify",
        last_name=login,
        email=f"{login}@example.com",
        hashed_password=get_password_hash(password),
        role=UserRole.PARTICIPANT.value,
        login=login,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_justification_meeting(
    db_session, admin_user, participants, config_extra=None
):
    suffix = uuid4().hex[:8]
    meeting_id = f"M-JUST-{suffix}"
    activity_id = f"A-JUST-{suffix}"
    meeting = Meeting(
        meeting_id=meeting_id,
        owner_id=admin_user.user_id,
        title="Justification API",
        description="Outlier justification API fixture",
    )
    meeting.participants.extend(participants)
    config = {"justification_seed": _SEED}
    if config_extra:
        config.update(config_extra)
    activity = AgendaActivity(
        activity_id=activity_id,
        meeting_id=meeting.meeting_id,
        tool_type="outlier_justification",
        title="Justify Outlier Rankings",
        order_index=1,
        tool_config_id=f"tc-{activity_id}",
        config=config,
    )
    meeting.agenda_activities.append(activity)
    db_session.add(meeting)
    db_session.commit()
    db_session.refresh(meeting)
    return meeting, activity.activity_id


def _login(client: TestClient, login: str, password: str):
    response = client.post(
        "/api/auth/token",
        json={"username": login, "password": password},
    )
    assert response.status_code == 200, response.json()


def _open_activity(meeting_id: str, activity_id: str):
    asyncio.run(
        meeting_state_manager.apply_patch(
            meeting_id,
            {
                "currentActivity": activity_id,
                "agendaItemId": activity_id,
                "currentTool": "outlier_justification",
                "status": "in_progress",
                "participants": ["justify_outlier", "justify_clear"],
            },
        )
    )


def test_get_state_returns_participant_queue(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    admin_user = user_manager_with_admin.get_user_by_email(admin_email)
    outlier = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_outlier",
        login="justify_outlier",
        password="JustifyOutlier1!",
    )
    clear = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_clear",
        login="justify_clear",
        password="JustifyClear1!",
    )
    meeting, activity_id = _create_justification_meeting(
        db_session, admin_user, [outlier, clear]
    )
    _open_activity(meeting.meeting_id, activity_id)
    _login(client, "justify_outlier", "JustifyOutlier1!")

    response = client.get(
        f"/api/meetings/{meeting.meeting_id}/justification/state",
        params={"activity_id": activity_id},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["activity_id"] == activity_id
    assert payload["nothing_to_justify"] is False
    assert payload["submitted"] is False
    assert payload["progress"] is None
    assert [item["option_id"] for item in payload["items"]] == ["o1"]
    assert payload["items"][0]["your_rank"] == 9
    assert payload["items"][0]["group_median"] == 1.0


def test_get_state_returns_empty_queue_for_non_outlier(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    outlier = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_outlier",
        login="justify_outlier",
        password="JustifyOutlier1!",
    )
    clear = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_clear",
        login="justify_clear",
        password="JustifyClear1!",
    )
    meeting, activity_id = _create_justification_meeting(
        db_session, admin_user, [outlier, clear]
    )
    _open_activity(meeting.meeting_id, activity_id)
    _login(client, "justify_clear", "JustifyClear1!")

    response = client.get(
        f"/api/meetings/{meeting.meeting_id}/justification/state",
        params={"activity_id": activity_id},
    )

    assert response.status_code == 200, response.json()
    assert response.json()["nothing_to_justify"] is True
    assert response.json()["items"] == []


def test_get_state_returns_selected_comment_items_for_any_participant(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    outlier = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_outlier",
        login="justify_outlier",
        password="JustifyOutlier1!",
    )
    clear = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_clear",
        login="justify_clear",
        password="JustifyClear1!",
    )
    meeting, activity_id = _create_justification_meeting(
        db_session,
        admin_user,
        [outlier, clear],
        config_extra={
            "comment_scope": "selected_items",
            "selected_comment_items": [
                {
                    "option_id": "o2",
                    "content": "Idea B",
                    "median": 2.0,
                    "iqr": 1.0,
                    "ranks_by_user": {"justify_clear": 2},
                }
            ],
        },
    )
    _open_activity(meeting.meeting_id, activity_id)
    _login(client, "justify_clear", "JustifyClear1!")

    response = client.get(
        f"/api/meetings/{meeting.meeting_id}/justification/state",
        params={"activity_id": activity_id},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["nothing_to_justify"] is False
    assert [item["option_id"] for item in payload["items"]] == ["o2"]
    assert payload["items"][0]["your_rank"] == 2


def test_post_rationale_stores_and_is_idempotent(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    outlier = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_outlier",
        login="justify_outlier",
        password="JustifyOutlier1!",
    )
    clear = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_clear",
        login="justify_clear",
        password="JustifyClear1!",
    )
    meeting, activity_id = _create_justification_meeting(
        db_session, admin_user, [outlier, clear]
    )
    _open_activity(meeting.meeting_id, activity_id)
    _login(client, "justify_outlier", "JustifyOutlier1!")

    first = client.post(
        f"/api/meetings/{meeting.meeting_id}/justification/rationale",
        json={"activity_id": activity_id, "option_id": "o1", "rationale": "cost"},
    )
    revised = client.post(
        f"/api/meetings/{meeting.meeting_id}/justification/rationale",
        json={"activity_id": activity_id, "option_id": "o1", "rationale": "risk"},
    )

    assert first.status_code == 200, first.json()
    assert revised.status_code == 200, revised.json()
    payload = revised.json()
    assert payload["submitted"] is True
    assert payload["items"][0]["rationale"] == "risk"


def test_post_non_queued_option_returns_400(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    outlier = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_outlier",
        login="justify_outlier",
        password="JustifyOutlier1!",
    )
    clear = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_clear",
        login="justify_clear",
        password="JustifyClear1!",
    )
    meeting, activity_id = _create_justification_meeting(
        db_session, admin_user, [outlier, clear]
    )
    _open_activity(meeting.meeting_id, activity_id)
    _login(client, "justify_outlier", "JustifyOutlier1!")

    response = client.post(
        f"/api/meetings/{meeting.meeting_id}/justification/rationale",
        json={"activity_id": activity_id, "option_id": "o2", "rationale": "nope"},
    )

    assert response.status_code == 400
    assert "your own outlier rankings" in response.json()["detail"]


def test_post_selected_comment_item_stores_for_non_outlier(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    outlier = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_outlier",
        login="justify_outlier",
        password="JustifyOutlier1!",
    )
    clear = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_clear",
        login="justify_clear",
        password="JustifyClear1!",
    )
    meeting, activity_id = _create_justification_meeting(
        db_session,
        admin_user,
        [outlier, clear],
        config_extra={
            "comment_scope": "selected_items",
            "selected_comment_items": [
                {"option_id": "o2", "content": "Idea B"},
            ],
        },
    )
    _open_activity(meeting.meeting_id, activity_id)
    _login(client, "justify_clear", "JustifyClear1!")

    accepted = client.post(
        f"/api/meetings/{meeting.meeting_id}/justification/rationale",
        json={"activity_id": activity_id, "option_id": "o2", "rationale": "context"},
    )
    rejected = client.post(
        f"/api/meetings/{meeting.meeting_id}/justification/rationale",
        json={"activity_id": activity_id, "option_id": "o1", "rationale": "nope"},
    )

    assert accepted.status_code == 200, accepted.json()
    assert accepted.json()["submitted"] is True
    assert rejected.status_code == 400
    assert "not open for comments" in rejected.json()["detail"]


def test_post_when_inactive_returns_403(
    client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    outlier = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_outlier",
        login="justify_outlier",
        password="JustifyOutlier1!",
    )
    clear = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_clear",
        login="justify_clear",
        password="JustifyClear1!",
    )
    meeting, activity_id = _create_justification_meeting(
        db_session, admin_user, [outlier, clear]
    )
    _login(client, "justify_outlier", "JustifyOutlier1!")

    response = client.post(
        f"/api/meetings/{meeting.meeting_id}/justification/rationale",
        json={"activity_id": activity_id, "option_id": "o1", "rationale": "cost"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "This activity is not open for justification."


def test_facilitator_get_returns_progress(
    authenticated_client: TestClient,
    user_manager_with_admin,
    db_session,
):
    admin_user = user_manager_with_admin.get_user_by_email(
        os.getenv("ADMIN_EMAIL", "admin@decidero.local")
    )
    outlier = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_outlier",
        login="justify_outlier",
        password="JustifyOutlier1!",
    )
    clear = _add_participant(
        user_manager_with_admin,
        db_session,
        user_id="justify_clear",
        login="justify_clear",
        password="JustifyClear1!",
    )
    meeting, activity_id = _create_justification_meeting(
        db_session, admin_user, [outlier, clear]
    )

    response = authenticated_client.get(
        f"/api/meetings/{meeting.meeting_id}/justification/state",
        params={"activity_id": activity_id},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["items"] == []
    assert payload["progress"] == {
        "outlier_count": 1,
        "submitted_count": 0,
        "selected_item_count": None,
    }
