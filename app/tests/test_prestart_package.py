import asyncio
from fastapi.testclient import TestClient

from app.data.activity_bundle_manager import ActivityBundleManager
from app.data.meeting_template_manager import seed_builtin_meeting_templates
from app.data.user_manager import UserManager
from app.main import app
from app.models.activity_bundle import ActivityBundle
from app.models.idea import Idea
from app.models.meeting import AgendaActivity, Meeting
from app.models.user import User, UserRole
from app.plugins.builtin.categorization_plugin import CategorizationPlugin
from app.plugins.builtin.report_plugin import ReportPlugin
from app.plugins.builtin.voting_plugin import VotingPlugin
from app.plugins.context import ActivityContext
from app.services import meeting_state_manager
from app.utils.security import get_password_hash


def test_prestart_package_visibility_end_to_end(
    authenticated_client: TestClient,
    user_manager_with_admin: UserManager,
    db_session,
):
    """Test full Delphi lifecycle pre-start package visibility:

    1. Advancing an orchestrated meeting to a rank-order step populates that activity's
       config["ideas"] before it is started.
    2. A facilitator GET on the rank-order summary for that not-yet-started activity returns
       the items; a participant still gets 403.
    3. Starting an activity that was already prepared does not duplicate ideas or re-seed
       (rank-order idempotency).
    4. Advancing to a brainstorming comment-surface step (seed_from_input) creates its Idea
       rows before start.
    5. Starting the comment activity does not duplicate ideas (brainstorming idempotency).
    6. Advancing to a report step does not produce an output bundle before start
       (prepare_package is a no-op there).
    """
    [template] = seed_builtin_meeting_templates(db_session)

    # Create participant user
    participant = user_manager_with_admin.add_user(
        first_name="Panel",
        last_name="Member",
        email="panel.member@example.com",
        hashed_password=get_password_hash("PanelPass1!"),
        role=UserRole.PARTICIPANT.value,
        login="panel_member",
    )
    user_manager_with_admin.db.commit()
    user_manager_with_admin.db.refresh(participant)

    participant_client = TestClient(app)
    auth_resp = participant_client.post(
        "/api/auth/token",
        json={"username": "panel_member", "password": "PanelPass1!"},
    )
    assert auth_resp.status_code == 200, auth_resp.text

    create = authenticated_client.post(
        f"/api/meetings/templates/{template.template_id}/meetings",
        json={
            "title": "Delphi Prestart Test Run",
            "description": "Verify pre-start package visibility in Delphi.",
            "participant_ids": [participant.user_id],
        },
    )
    assert create.status_code == 200, create.text
    meeting_id = create.json()["meeting_id"]
    asyncio.run(meeting_state_manager.reset(meeting_id))
    brainstorm_id = create.json()["agenda"][0]["activity_id"]

    # Finalize initial brainstorm output bundle
    bm = ActivityBundleManager(db_session)
    bm.finalize_output_bundle(
        meeting_id,
        brainstorm_id,
        [{"content": "Idea Alpha"}, {"content": "Idea Beta"}],
        metadata={"source": "test"},
    )

    # 1. Advance to rank-order step -> config["ideas"] populated BEFORE start
    rank_resp = authenticated_client.post(f"/api/meetings/{meeting_id}/orchestration/advance")
    assert rank_resp.status_code == 200, rank_resp.text
    rank = rank_resp.json()["activity"]
    assert rank["tool_type"] == "rank_order_voting"
    rank_id = rank["activity_id"]

    # Verify rank_order_voting activity is not yet started/active
    db_session.expire_all()
    db_rank = db_session.query(AgendaActivity).filter_by(activity_id=rank_id).first()
    assert db_rank is not None
    assert db_rank.config is not None
    assert "ideas" in db_rank.config
    ideas_in_config = db_rank.config["ideas"]
    assert len(ideas_in_config) == 2
    idea_contents = [i.get("content") for i in ideas_in_config]
    assert "Idea Alpha" in idea_contents
    assert "Idea Beta" in idea_contents

    # 2. Permission guard: Facilitator GET on summary returns items, participant GET returns 403
    fac_summary = authenticated_client.get(
        f"/api/meetings/{meeting_id}/rank-order-voting/summary?activity_id={rank_id}"
    )
    assert fac_summary.status_code == 200, fac_summary.text
    fac_payload = fac_summary.json()
    assert len(fac_payload.get("options", [])) == 2
    option_labels = [opt.get("label") for opt in fac_payload["options"]]
    assert "Idea Alpha" in option_labels
    assert "Idea Beta" in option_labels

    part_summary = participant_client.get(
        f"/api/meetings/{meeting_id}/rank-order-voting/summary?activity_id={rank_id}"
    )
    assert part_summary.status_code == 403, part_summary.text

    # 3. Start the rank-order activity -> verify idempotency (ideas not duplicated or cleared)
    start_rank = authenticated_client.post(
        f"/api/meetings/{meeting_id}/control",
        json={
            "action": "start_tool",
            "tool": "rank_order_voting",
            "activityId": rank_id,
        },
    )
    assert start_rank.status_code == 200, start_rank.text
    db_session.expire_all()
    db_rank = db_session.query(AgendaActivity).filter_by(activity_id=rank_id).first()
    assert len(db_rank.config.get("ideas", [])) == 2

    # Stop rank-order and finalize output bundle with votes for statistical transform
    stop_rank = authenticated_client.post(
        f"/api/meetings/{meeting_id}/control",
        json={
            "action": "stop_tool",
            "tool": "rank_order_voting",
            "activityId": rank_id,
        },
    )
    assert stop_rank.status_code == 200, stop_rank.text

    orch = rank["config"]["_orchestration"]
    opt_a = f"{rank_id}:idea-alpha"
    opt_b = f"{rank_id}:idea-beta"
    bm.finalize_output_bundle(
        meeting_id,
        rank_id,
        [
            {
                "content": "Idea Alpha",
                "metadata": {"rank_order_voting": {"option_id": opt_a}},
            },
            {
                "content": "Idea Beta",
                "metadata": {"rank_order_voting": {"option_id": opt_b}},
            },
        ],
        metadata={
            "source": "test",
            "votes": [
                {"user_id": "u1", "option_id": opt_a, "rank_position": 1},
                {"user_id": "u1", "option_id": opt_b, "rank_position": 2},
                {"user_id": "u2", "option_id": opt_a, "rank_position": 2},
                {"user_id": "u2", "option_id": opt_b, "rank_position": 1},
            ],
        },
        logical_step_id=orch["logical_step_id"],
        round_index=orch["round_index"],
    )

    # In-round facilitator decision
    in_round = authenticated_client.post(f"/api/meetings/{meeting_id}/orchestration/advance")
    assert in_round.status_code == 200, in_round.text
    decision = in_round.json()["pending_decision"]
    assert decision["options"] == ["open_comments", "skip_comments"]
    choose_comments = authenticated_client.post(
        f"/api/meetings/{meeting_id}/orchestration/facilitator-decisions/{decision['activity_id']}/responses",
        json={"chosen_option": "open_comments"},
    )
    assert choose_comments.status_code == 200, choose_comments.text

    # 4. Advance to comment step -> Idea rows created BEFORE start
    comment_resp = authenticated_client.post(f"/api/meetings/{meeting_id}/orchestration/advance")
    assert comment_resp.status_code == 200, comment_resp.text
    comment = comment_resp.json()["activity"]
    assert comment["tool_type"] == "brainstorming"
    comment_id = comment["activity_id"]

    db_session.expire_all()
    comment_ideas = (
        db_session.query(Idea)
        .filter(Idea.meeting_id == meeting_id, Idea.activity_id == comment_id)
        .all()
    )
    assert len(comment_ideas) > 0, "Idea rows must be seeded before start"
    initial_idea_count = len(comment_ideas)

    # 5. Start comment step -> verify idempotency (Idea rows not re-seeded or duplicated)
    start_comment = authenticated_client.post(
        f"/api/meetings/{meeting_id}/control",
        json={
            "action": "start_tool",
            "tool": "brainstorming",
            "activityId": comment_id,
        },
    )
    assert start_comment.status_code == 200, start_comment.text
    db_session.expire_all()
    comment_ideas_after_start = (
        db_session.query(Idea)
        .filter(Idea.meeting_id == meeting_id, Idea.activity_id == comment_id)
        .all()
    )
    assert len(comment_ideas_after_start) == initial_idea_count

    # Stop comment activity and finalize output bundle
    stop_comment = authenticated_client.post(
        f"/api/meetings/{meeting_id}/control",
        json={
            "action": "stop_tool",
            "tool": "brainstorming",
            "activityId": comment_id,
        },
    )
    assert stop_comment.status_code == 200, stop_comment.text
    comment_orch = comment["config"]["_orchestration"]
    bm.finalize_output_bundle(
        meeting_id,
        comment_id,
        [],
        metadata={"source": "brainstorming", "comment_surface": True},
        logical_step_id=comment_orch["logical_step_id"],
        round_index=comment_orch["round_index"],
    )

    # Conclude iteration gate
    gate_resp = authenticated_client.post(f"/api/meetings/{meeting_id}/orchestration/advance")
    assert gate_resp.status_code == 200, gate_resp.text
    gate = gate_resp.json()["pending_decision"]
    assert gate["options"] == ["continue", "conclude"]
    conclude = authenticated_client.post(
        f"/api/meetings/{meeting_id}/orchestration/facilitator-decisions/{gate['activity_id']}/responses",
        json={"chosen_option": "conclude"},
    )
    assert conclude.status_code == 200, conclude.text

    # 6. Advance to report step -> prepare_package is a no-op, NO output bundle before start
    report_resp = authenticated_client.post(f"/api/meetings/{meeting_id}/orchestration/advance")
    assert report_resp.status_code == 200, report_resp.text
    report_activity = report_resp.json()["activity"]
    assert report_activity["tool_type"] == "report"
    report_id = report_activity["activity_id"]

    db_session.expire_all()
    report_output_bundle = bm.get_latest_bundle(meeting_id, report_id, "output")
    assert report_output_bundle is None, "Report step must NOT produce an output bundle before start"


def test_voting_and_categorization_prepare_package_unit(db_session):
    """Unit test prepare_package on VotingPlugin and CategorizationPlugin:
    - Binds input bundle items into content config key when empty
    - Does not call reset_activity_state or seed_activity from prepare_package
    - open_activity called after prepare_package is idempotent
    """
    user = User(
        user_id="u-unit-prep",
        login="u_prep",
        hashed_password="hash",
        role=UserRole.ADMIN.value,
    )
    meeting = Meeting(meeting_id="m-unit-prep", title="Unit Prep Meeting", owner_id=user.user_id)
    vote_act = AgendaActivity(
        activity_id="act-vote",
        meeting_id=meeting.meeting_id,
        tool_type="voting",
        title="Vote",
        order_index=1,
        tool_config_id="tc-v",
        config={},
    )
    cat_act = AgendaActivity(
        activity_id="act-cat",
        meeting_id=meeting.meeting_id,
        tool_type="categorization",
        title="Categorize",
        order_index=2,
        tool_config_id="tc-c",
        config={},
    )
    db_session.add_all([user, meeting, vote_act, cat_act])
    db_session.commit()

    bm = ActivityBundleManager(db_session)
    bundle = bm.create_bundle(
        meeting.meeting_id,
        "donor-act",
        "output",
        [{"id": "item-1", "content": "Option 1"}, {"id": "item-2", "content": "Option 2"}],
    )

    # Test VotingPlugin prepare_package
    vote_plugin = VotingPlugin()
    vote_ctx = ActivityContext(db=db_session, meeting=meeting, activity=vote_act)
    vote_plugin.prepare_package(vote_ctx, bundle)

    assert "options" in vote_act.config
    assert len(vote_act.config["options"]) == 2
    assert vote_act.config["options"][0]["content"] == "Option 1"

    # open_activity after prepare_package is idempotent
    vote_plugin.open_activity(vote_ctx, bundle)
    assert len(vote_act.config["options"]) == 2

    # Test CategorizationPlugin prepare_package
    cat_plugin = CategorizationPlugin()
    cat_ctx = ActivityContext(db=db_session, meeting=meeting, activity=cat_act)
    cat_plugin.prepare_package(cat_ctx, bundle)

    assert "items" in cat_act.config
    assert len(cat_act.config["items"]) == 2
    assert cat_act.config["items"][0]["content"] == "Option 1"

    # open_activity after prepare_package seeds database rows
    cat_plugin.open_activity(cat_ctx, bundle)
    assert len(cat_act.config["items"]) == 2


def test_report_plugin_prepare_package_is_noop(db_session):
    """ReportPlugin must NOT implement prepare_package (inherits default no-op)."""
    assert "prepare_package" not in ReportPlugin.__dict__, (
        "ReportPlugin must NOT implement prepare_package"
    )

    user = User(
        user_id="u-rep-prep",
        login="u_rep",
        hashed_password="hash",
        role=UserRole.ADMIN.value,
    )
    meeting = Meeting(meeting_id="m-rep-unit", title="Report Meeting", owner_id=user.user_id)
    rep_act = AgendaActivity(
        activity_id="act-rep",
        meeting_id=meeting.meeting_id,
        tool_type="report",
        title="Report",
        order_index=1,
        tool_config_id="tc-r",
        config={},
    )
    db_session.add_all([user, meeting, rep_act])
    db_session.commit()

    bm = ActivityBundleManager(db_session)
    bundle = bm.create_bundle(
        meeting.meeting_id,
        "donor-act",
        "output",
        [{"id": "item-1", "content": "Idea 1"}],
    )

    rep_plugin = ReportPlugin()
    rep_ctx = ActivityContext(db=db_session, meeting=meeting, activity=rep_act)
    res = rep_plugin.prepare_package(rep_ctx, bundle)
    assert res is None

    # Verify no output bundle was created
    output_bundle = bm.get_latest_bundle(meeting.meeting_id, rep_act.activity_id, "output")
    assert output_bundle is None
