"""
Tests for app.services.meeting_designer_prompt

Covers:
  - parse_agenda_json()  — strict parse, repair fallback, comment stripping,
                           fence stripping, file saving, error cases
  - _normalise_agenda()  — backward compat defaults for all new/old fields
  - build_system_prompt() / build_generation_messages() — smoke tests
"""
import json
import textwrap
from pathlib import Path

import pytest

from app.services.meeting_designer_prompt import (
    _normalise_agenda,
    build_generation_messages,
    build_system_prompt,
    parse_agenda_json,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_agenda(**overrides) -> dict:
    """Return a minimal valid agenda dict, with optional overrides."""
    base = {
        "meeting_summary": "Test meeting.",
        "session_name": "Test Session",
        "evaluation_criteria": [],
        "design_rationale": "Simple.",
        "complexity": "simple",
        "phases": [],
        "agenda": [
            {
                "tool_type": "brainstorming",
                "title": "Brainstorm ideas",
                "instructions": "Share your thoughts.",
                "duration_minutes": 15,
                "collaboration_pattern": "Generate",
                "rationale": "Divergent first.",
                "config_overrides": {},
                "phase_id": None,
                "track_id": None,
            }
        ],
    }
    base.update(overrides)
    return base


def _json(d: dict) -> str:
    return json.dumps(d)


# ---------------------------------------------------------------------------
# parse_agenda_json — strict (happy path)
# ---------------------------------------------------------------------------

class TestParseAgendaJsonStrict:
    def test_clean_json_parses(self, tmp_path):
        raw = _json(_minimal_agenda())
        result = parse_agenda_json(raw, save_dir=str(tmp_path))
        assert result["session_name"] == "Test Session"
        assert len(result["agenda"]) == 1

    def test_strips_markdown_json_fence(self, tmp_path):
        raw = "```json\n" + _json(_minimal_agenda()) + "\n```"
        result = parse_agenda_json(raw, save_dir=str(tmp_path))
        assert result["complexity"] == "simple"

    def test_strips_plain_code_fence(self, tmp_path):
        raw = "```\n" + _json(_minimal_agenda()) + "\n```"
        result = parse_agenda_json(raw, save_dir=str(tmp_path))
        assert result["agenda"]

    def test_ignores_prose_before_and_after_json(self, tmp_path):
        raw = "Here is your agenda:\n" + _json(_minimal_agenda()) + "\nLet me know!"
        result = parse_agenda_json(raw, save_dir=str(tmp_path))
        assert result["session_name"] == "Test Session"

    def test_strips_js_line_comments(self, tmp_path):
        """The old schema template had // comments inside config_overrides."""
        raw = textwrap.dedent("""\
            {
              "meeting_summary": "TBI summit.",
              "session_name": "TBI Summit",
              "evaluation_criteria": [],
              "design_rationale": "Multi-track.",
              "complexity": "simple",
              "phases": [],
              "agenda": [
                {
                  "tool_type": "brainstorming",
                  "title": "Ideate",
                  "instructions": "Go.",
                  "duration_minutes": 20,
                  "collaboration_pattern": "Generate",
                  "rationale": "Why.",
                  "config_overrides": {
                    // OPTIONAL: brainstorming: "allow_anonymous" (bool)
                  },
                  "phase_id": null,
                  "track_id": null
                }
              ]
            }
        """)
        result = parse_agenda_json(raw, save_dir=str(tmp_path))
        assert result["agenda"][0]["config_overrides"] == {}

    def test_saves_raw_file_on_success(self, tmp_path):
        raw = _json(_minimal_agenda())
        parse_agenda_json(raw, save_dir=str(tmp_path))
        saved = (tmp_path / "decidero_last_agenda_raw.txt").read_text()
        assert saved == raw

    def test_saves_parsed_file_on_success(self, tmp_path):
        raw = _json(_minimal_agenda())
        parse_agenda_json(raw, save_dir=str(tmp_path))
        parsed = json.loads((tmp_path / "decidero_last_agenda_parsed.json").read_text())
        assert parsed["session_name"] == "Test Session"


# ---------------------------------------------------------------------------
# parse_agenda_json — repair fallback
# ---------------------------------------------------------------------------

class TestParseAgendaJsonRepair:
    def test_repairs_missing_comma_between_fields(self, tmp_path):
        """Missing comma between two object fields — the exact bug seen in prod."""
        raw = textwrap.dedent("""\
            {
              "meeting_summary": "TBI summit."
              "session_name": "TBI Summit",
              "evaluation_criteria": [],
              "design_rationale": "Multi-track.",
              "complexity": "simple",
              "phases": [],
              "agenda": []
            }
        """)
        result = parse_agenda_json(raw, save_dir=str(tmp_path))
        assert isinstance(result, dict)
        # json_repair should recover the session_name
        assert result.get("session_name") == "TBI Summit"

    def test_repairs_trailing_comma_in_array(self, tmp_path):
        raw = textwrap.dedent("""\
            {
              "meeting_summary": "Quick sync.",
              "session_name": "Sync",
              "evaluation_criteria": ["cost", "impact",],
              "design_rationale": "Simple.",
              "complexity": "simple",
              "phases": [],
              "agenda": []
            }
        """)
        result = parse_agenda_json(raw, save_dir=str(tmp_path))
        assert isinstance(result, dict)

    def test_repairs_trailing_comma_in_object(self, tmp_path):
        raw = textwrap.dedent("""\
            {
              "meeting_summary": "Session.",
              "session_name": "Session",
              "evaluation_criteria": [],
              "design_rationale": "Simple.",
              "complexity": "simple",
              "phases": [],
              "agenda": [
                {
                  "tool_type": "brainstorming",
                  "title": "Ideas",
                  "instructions": "Go.",
                  "duration_minutes": 15,
                  "collaboration_pattern": "Generate",
                  "rationale": "Why.",
                  "config_overrides": {},
                  "phase_id": null,
                  "track_id": null,
                }
              ],
            }
        """)
        result = parse_agenda_json(raw, save_dir=str(tmp_path))
        assert isinstance(result, dict)
        assert len(result["agenda"]) >= 1

    def test_saves_raw_on_repair(self, tmp_path):
        """Even when repair is needed, raw should be saved."""
        bad_raw = '{"meeting_summary": "x" "session_name": "y", "agenda": []}'
        try:
            parse_agenda_json(bad_raw, save_dir=str(tmp_path))
        except Exception:
            pass
        assert (tmp_path / "decidero_last_agenda_raw.txt").read_text() == bad_raw


# ---------------------------------------------------------------------------
# parse_agenda_json — failure cases
# ---------------------------------------------------------------------------

class TestParseAgendaJsonFailure:
    def test_raises_on_completely_invalid_input(self, tmp_path):
        with pytest.raises(ValueError, match="invalid JSON"):
            parse_agenda_json("this is not json at all !!!", save_dir=str(tmp_path))

    def test_raises_on_empty_string(self, tmp_path):
        with pytest.raises((ValueError, Exception)):
            parse_agenda_json("", save_dir=str(tmp_path))

    def test_saves_raw_even_on_failure(self, tmp_path):
        bad = "not json"
        try:
            parse_agenda_json(bad, save_dir=str(tmp_path))
        except Exception:
            pass
        assert (tmp_path / "decidero_last_agenda_raw.txt").read_text() == bad


# ---------------------------------------------------------------------------
# _normalise_agenda — field defaults and backward compat
# ---------------------------------------------------------------------------

class TestNormaliseAgenda:

    # ── New fields added in multi-track feature ──────────────────────────

    def test_session_name_defaults_to_empty(self):
        result = _normalise_agenda({"agenda": []})
        assert result["session_name"] == ""

    def test_session_name_preserved(self):
        result = _normalise_agenda({"session_name": "My Retreat", "agenda": []})
        assert result["session_name"] == "My Retreat"

    def test_evaluation_criteria_defaults_to_empty_list(self):
        result = _normalise_agenda({"agenda": []})
        assert result["evaluation_criteria"] == []

    def test_evaluation_criteria_preserved(self):
        result = _normalise_agenda({"evaluation_criteria": ["cost", "impact"], "agenda": []})
        assert result["evaluation_criteria"] == ["cost", "impact"]

    def test_evaluation_criteria_non_strings_filtered(self):
        result = _normalise_agenda({"evaluation_criteria": ["cost", 42, None, "impact"], "agenda": []})
        assert result["evaluation_criteria"] == ["cost", "impact"]

    def test_evaluation_criteria_wrong_type_becomes_empty(self):
        result = _normalise_agenda({"evaluation_criteria": "not a list", "agenda": []})
        assert result["evaluation_criteria"] == []

    # ── Complexity ───────────────────────────────────────────────────────

    def test_complexity_defaults_to_simple(self):
        result = _normalise_agenda({"agenda": []})
        assert result["complexity"] == "simple"

    def test_complexity_multi_phase_preserved(self):
        result = _normalise_agenda({"complexity": "multi_phase", "agenda": []})
        assert result["complexity"] == "multi_phase"

    def test_complexity_multi_track_preserved(self):
        result = _normalise_agenda({"complexity": "multi_track", "agenda": []})
        assert result["complexity"] == "multi_track"

    def test_complexity_invalid_value_reset_to_simple(self):
        result = _normalise_agenda({"complexity": "banana", "agenda": []})
        assert result["complexity"] == "simple"

    def test_complexity_auto_detected_from_parallel_phase(self):
        data = {
            "complexity": "simple",
            "phases": [
                {"phase_id": "p1", "phase_type": "parallel", "tracks": [
                    {"track_id": "t1", "label": "Track A"},
                ]},
            ],
            "agenda": [],
        }
        result = _normalise_agenda(data)
        assert result["complexity"] == "multi_track"

    def test_complexity_auto_detected_as_multi_phase(self):
        data = {
            "complexity": "simple",
            "phases": [
                {"phase_id": "p1", "phase_type": "plenary"},
                {"phase_id": "p2", "phase_type": "plenary"},
            ],
            "agenda": [],
        }
        result = _normalise_agenda(data)
        assert result["complexity"] == "multi_phase"

    # ── Phases normalisation ─────────────────────────────────────────────

    def test_phases_defaults_to_empty_list(self):
        result = _normalise_agenda({"agenda": []})
        assert result["phases"] == []

    def test_phase_defaults_applied(self):
        data = {"phases": [{}], "agenda": []}
        result = _normalise_agenda(data)
        phase = result["phases"][0]
        assert phase["phase_id"] is None
        assert phase["title"] == ""
        assert phase["description"] == ""
        assert phase["phase_type"] == "plenary"
        assert phase["suggested_duration_minutes"] == 0

    def test_parallel_phase_gets_tracks_list(self):
        data = {"phases": [{"phase_type": "parallel"}], "agenda": []}
        result = _normalise_agenda(data)
        assert result["phases"][0]["tracks"] == []

    def test_plenary_phase_has_no_tracks_key(self):
        data = {"phases": [{"phase_type": "plenary", "tracks": ["x"]}], "agenda": []}
        result = _normalise_agenda(data)
        assert "tracks" not in result["phases"][0]

    def test_invalid_phase_type_reset_to_plenary(self):
        data = {"phases": [{"phase_type": "diagonal"}], "agenda": []}
        result = _normalise_agenda(data)
        assert result["phases"][0]["phase_type"] == "plenary"

    # ── Agenda item normalisation ─────────────────────────────────────────

    def test_agenda_item_gets_phase_id_and_track_id(self):
        data = {"agenda": [{"tool_type": "brainstorming"}]}
        result = _normalise_agenda(data)
        assert result["agenda"][0]["phase_id"] is None
        assert result["agenda"][0]["track_id"] is None

    def test_agenda_item_phase_id_preserved(self):
        data = {"agenda": [{"tool_type": "brainstorming", "phase_id": "p1", "track_id": "t1"}]}
        result = _normalise_agenda(data)
        assert result["agenda"][0]["phase_id"] == "p1"
        assert result["agenda"][0]["track_id"] == "t1"

    def test_agenda_defaults_to_empty_list(self):
        result = _normalise_agenda({})
        assert result["agenda"] == []


# ---------------------------------------------------------------------------
# build_system_prompt — smoke test
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    def test_returns_non_empty_string(self):
        prompt = build_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 1000

    def test_contains_all_motion_phases(self):
        prompt = build_system_prompt()
        for phase in [
            "Phase 1 — GOAL",
            "Phase 2 — GROUP",
            "Phase 3 — COMPLEXITY ASSESSMENT",
            "Phase 4 — CONSTRAINTS",
            "Phase 4.5 — EVALUATION CRITERIA",
            "Phase 5 — DESIGN DISCUSSION",
            "Phase 6 — AGENDA GENERATION",
        ]:
            assert phase in prompt, f"Missing phase: {phase}"

    def test_contains_session_name_instruction(self):
        prompt = build_system_prompt()
        assert "session" in prompt.lower()
        assert "call this session" in prompt.lower() or "name" in prompt.lower()

    def test_contains_evaluation_criteria_section(self):
        prompt = build_system_prompt()
        assert "EVALUATION CRITERIA" in prompt

    def test_contains_no_json_output_rule(self):
        prompt = build_system_prompt()
        assert "Never output JSON" in prompt

    def test_no_raw_json_generation_in_system_prompt(self):
        """Old Rule 7 text must not be present — it caused raw JSON in chat."""
        prompt = build_system_prompt()
        assert "output ONLY valid JSON" not in prompt

    def test_generate_prompt_contains_reconvergence_rules(self):
        from app.services.meeting_designer_prompt import GENERATE_AGENDA_PROMPT
        assert "Reconvergence rules" in GENERATE_AGENDA_PROMPT
        assert "MUST be immediately followed" in GENERATE_AGENDA_PROMPT

    def test_no_js_comments_in_json_schema(self):
        """The JSON schema block must not contain // comments (breaks AI output)."""
        from app.services.meeting_designer_prompt import GENERATE_AGENDA_PROMPT
        # Find the JSON block
        start = GENERATE_AGENDA_PROMPT.find("{")
        end = GENERATE_AGENDA_PROMPT.rfind("}")
        json_block = GENERATE_AGENDA_PROMPT[start:end + 1]
        assert "//" not in json_block, (
            "Found // comment inside JSON schema block — AI will copy it and produce invalid JSON"
        )

    def test_generate_prompt_contains_required_fields(self):
        from app.services.meeting_designer_prompt import GENERATE_AGENDA_PROMPT
        for field in ["session_name", "evaluation_criteria", "complexity", "phases", "agenda"]:
            assert field in GENERATE_AGENDA_PROMPT, f"Missing field in schema: {field}"


# ---------------------------------------------------------------------------
# build_generation_messages — smoke test
# ---------------------------------------------------------------------------

class TestBuildGenerationMessages:
    def test_appends_generation_prompt_as_user_message(self):
        history = [
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "40 people, 1.5 days, 3 issues."},
        ]
        msgs = build_generation_messages(history)
        assert len(msgs) == 3
        assert msgs[-1]["role"] == "user"
        assert "session_name" in msgs[-1]["content"]

    def test_does_not_mutate_input_history(self):
        history = [{"role": "user", "content": "test"}]
        original_len = len(history)
        build_generation_messages(history)
        assert len(history) == original_len


# ---------------------------------------------------------------------------
# Integration: parse_agenda_json → _normalise_agenda round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_multi_track_agenda_round_trips(self, tmp_path):
        data = {
            "meeting_summary": "Strategy summit.",
            "session_name": "Strategic Planning Retreat",
            "evaluation_criteria": ["cost", "feasibility", "impact"],
            "design_rationale": "Decomposition pattern.",
            "complexity": "multi_track",
            "phases": [
                {
                    "phase_id": "phase_1",
                    "title": "Opening Plenary",
                    "description": "All together.",
                    "phase_type": "plenary",
                    "suggested_duration_minutes": 30,
                },
                {
                    "phase_id": "phase_2",
                    "title": "Deep Dives",
                    "description": "Parallel tracks.",
                    "phase_type": "parallel",
                    "tracks": [
                        {"track_id": "t2a", "label": "AI Threats", "participant_subset": "~13"},
                        {"track_id": "t2b", "label": "Real Estate", "participant_subset": "~13"},
                    ],
                    "suggested_duration_minutes": 90,
                },
            ],
            "agenda": [
                {"tool_type": "brainstorming", "title": "Open Brainstorm",
                 "instructions": "Go.", "duration_minutes": 20,
                 "collaboration_pattern": "Generate", "rationale": "Why.",
                 "config_overrides": {}, "phase_id": "phase_1", "track_id": None},
                {"tool_type": "rank_order_voting", "title": "Rank AI Options",
                 "instructions": "Consider cost, feasibility, impact.",
                 "duration_minutes": 15, "collaboration_pattern": "Evaluate",
                 "rationale": "Why.", "config_overrides": {},
                 "phase_id": "phase_2", "track_id": "t2a"},
            ],
        }
        result = parse_agenda_json(json.dumps(data), save_dir=str(tmp_path))

        assert result["session_name"] == "Strategic Planning Retreat"
        assert result["evaluation_criteria"] == ["cost", "feasibility", "impact"]
        assert result["complexity"] == "multi_track"
        assert len(result["phases"]) == 2
        assert result["phases"][1]["phase_type"] == "parallel"
        assert len(result["phases"][1]["tracks"]) == 2
        assert len(result["agenda"]) == 2
        assert result["agenda"][1]["track_id"] == "t2a"

    def test_simple_legacy_agenda_backward_compat(self, tmp_path):
        """Old agendas without session_name/criteria/phases still parse cleanly."""
        data = {
            "meeting_summary": "Legacy meeting.",
            "design_rationale": "Old style.",
            "agenda": [
                {"tool_type": "brainstorming", "title": "Ideas",
                 "instructions": "Go.", "duration_minutes": 15,
                 "collaboration_pattern": "Generate", "rationale": "Why.",
                 "config_overrides": {}},
            ],
        }
        result = parse_agenda_json(json.dumps(data), save_dir=str(tmp_path))
        assert result["session_name"] == ""
        assert result["evaluation_criteria"] == []
        assert result["complexity"] == "simple"
        assert result["phases"] == []
        assert len(result["agenda"]) == 1
        assert result["agenda"][0]["phase_id"] is None
        assert result["agenda"][0]["track_id"] is None
