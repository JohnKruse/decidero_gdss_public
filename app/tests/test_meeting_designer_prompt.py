"""
Tests for app.services.meeting_designer_prompt

Covers:
  - parse_agenda_json()  — strict parse, repair fallback, comment stripping,
                           fence stripping, file saving, error cases
  - _normalise_agenda()  — backward compat defaults for all new/old fields
  - build_system_prompt() / build_generation_messages() — smoke tests
"""
import json
import inspect
import textwrap
from pathlib import Path

import pytest

from app.services.meeting_designer_prompt import (
    _extract_json_object,
    _build_config_overrides_block,
    _build_duration_guidance,
    _build_tool_type_enum,
    _normalise_agenda,
    build_generation_prompt,
    build_generation_messages,
    build_generation_system_prompt,
    build_outline_messages,
    build_outline_prompt,
    build_system_prompt,
    get_generation_prompt,
    parse_agenda_json,
    parse_outline_json,
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


def _catalog_for_helpers() -> list[dict]:
    return [
        {
            "tool_type": "brainstorming",
            "default_config": {
                "allow_anonymous": False,
                "allow_subcomments": True,
            },
            "typical_duration_minutes": {"min": 5, "max": 30},
        },
        {
            "tool_type": "voting",
            "default_config": {
                "options": [],
                "vote_type": "updown",
                "max_votes": 3,
            },
            "typical_duration_minutes": {"min": 3, "max": 15},
        },
        {
            "tool_type": "rank_order_voting",
            "default_config": {
                "max_votes": 5,
            },
            "typical_duration_minutes": {"min": 10, "max": 20},
        },
        {
            "tool_type": "categorization",
            "default_config": {
                "allow_new_buckets": True,
            },
            "typical_duration_minutes": {"min": 15, "max": 45},
        },
    ]


def _synthetic_catalog(n: int = 4) -> list[dict]:
    """Return synthetic enriched-catalog entries with unique tool_type values."""
    greek = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    names = greek[:n]
    catalog: list[dict] = []
    for idx, name in enumerate(names, start=1):
        catalog.append(
            {
                "tool_type": name,
                "label": name.title(),
                "description": f"Synthetic {name} activity",
                "default_config": {
                    "flag_enabled": idx % 2 == 0,
                    "threshold": idx,
                },
                "typical_duration_minutes": {"min": idx, "max": idx + 5},
                "collaboration_patterns": ["Generate", "Evaluate"],
            }
        )
    return catalog


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
        generation_prompt = get_generation_prompt()
        assert "Reconvergence rules" in generation_prompt
        assert "MUST be immediately followed" in generation_prompt

    def test_no_js_comments_in_json_schema(self):
        """The JSON schema block must not contain // comments (breaks AI output)."""
        generation_prompt = get_generation_prompt()
        # Find the JSON block
        start = generation_prompt.find("{")
        end = generation_prompt.rfind("}")
        json_block = generation_prompt[start:end + 1]
        assert "//" not in json_block, (
            "Found // comment inside JSON schema block — AI will copy it and produce invalid JSON"
        )

    def test_generate_prompt_contains_required_fields(self):
        generation_prompt = get_generation_prompt()
        for field in ["session_name", "evaluation_criteria", "complexity", "phases", "agenda"]:
            assert field in generation_prompt, f"Missing field in schema: {field}"


class TestBuildGenerationSystemPrompt:
    def test_requires_json_only_output(self):
        prompt = build_generation_system_prompt()
        assert "Output ONLY JSON" in prompt
        assert "one top-level JSON object" in prompt

    def test_lists_allowed_tool_types(self):
        prompt = build_generation_system_prompt()
        assert "Allowed tool_type values:" in prompt


class TestBuildGenerationPrompt:
    def test_build_generation_prompt_contains_all_tool_types(self):
        from app.services.activity_catalog import get_enriched_activity_catalog

        prompt = build_generation_prompt()
        catalog = get_enriched_activity_catalog()
        for activity in catalog:
            tool_type = activity.get("tool_type")
            if isinstance(tool_type, str) and tool_type:
                assert tool_type in prompt

    def test_build_generation_prompt_no_hardcoded_tool_types(self):
        source = inspect.getsource(build_generation_prompt)
        for forbidden in ["brainstorming", "voting", "rank_order_voting", "categorization"]:
            assert forbidden not in source

    def test_build_generation_prompt_includes_json_schema(self):
        prompt = build_generation_prompt()
        for field in ["tool_type", "title", "instructions", "config_overrides", "duration_minutes"]:
            assert field in prompt

    def test_build_generation_prompt_without_outline(self):
        prompt = build_generation_prompt()
        assert "activity outline has been approved" not in prompt

    def test_build_generation_prompt_with_outline(self):
        outline = [
            {"tool_type": "alpha", "title": "First activity"},
            {"tool_type": "beta", "title": "Second activity"},
            {"tool_type": "gamma", "title": "Third activity"},
        ]
        prompt = build_generation_prompt(outline=outline)
        assert "activity outline has been approved" in prompt
        first_pos = prompt.find("First activity")
        second_pos = prompt.find("Second activity")
        third_pos = prompt.find("Third activity")
        assert first_pos != -1 and second_pos != -1 and third_pos != -1
        assert first_pos < second_pos < third_pos

    def test_generate_prompt_output_only_instruction(self):
        prompt = build_generation_prompt()
        assert "Output ONLY" in prompt


class TestBuildOutlinePrompt:
    def test_build_outline_prompt_contains_tool_types(self):
        from app.services.activity_catalog import get_enriched_activity_catalog

        prompt = build_outline_prompt()
        catalog = get_enriched_activity_catalog()
        for activity in catalog:
            tool_type = activity.get("tool_type")
            if isinstance(tool_type, str) and tool_type:
                assert tool_type in prompt

    def test_build_outline_prompt_no_hardcoded_tool_types(self):
        source = inspect.getsource(build_outline_prompt)
        for forbidden in ["brainstorming", "voting", "rank_order_voting", "categorization"]:
            assert forbidden not in source

    def test_build_outline_prompt_excludes_config_schema(self):
        prompt = build_outline_prompt()
        assert '"config_overrides"' not in prompt
        assert '"instructions"' not in prompt

    def test_build_outline_prompt_includes_outline_key(self):
        prompt = build_outline_prompt()
        assert '"outline"' in prompt

    def test_build_outline_prompt_output_only(self):
        prompt = build_outline_prompt()
        assert "Output ONLY" in prompt


class TestBuildOutlineMessages:
    def test_build_outline_messages_appends_prompt(self):
        history = [
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "Need a workshop agenda"},
        ]
        msgs = build_outline_messages(history)
        assert len(msgs) == 3
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == build_outline_prompt()

    def test_build_outline_messages_preserves_history(self):
        history = [{"role": "user", "content": "test"}]
        original_history = list(history)
        build_outline_messages(history)
        assert history == original_history


class TestParseOutlineJson:
    def test_parse_outline_json_clean(self):
        raw = json.dumps(
            {
                "meeting_summary": "Test",
                "outline": [
                    {"tool_type": "brainstorming", "title": "Open", "duration_minutes": 10},
                ],
            }
        )
        parsed = parse_outline_json(raw)
        assert isinstance(parsed, dict)
        assert isinstance(parsed["outline"], list)

    def test_parse_outline_json_markdown_fenced(self):
        payload = {"meeting_summary": "Test", "outline": []}
        raw = "```json\n" + json.dumps(payload) + "\n```"
        parsed = parse_outline_json(raw)
        assert parsed["outline"] == []

    def test_parse_outline_json_with_preamble(self):
        payload = {"meeting_summary": "Test", "outline": [{"title": "A"}]}
        raw = "Here is the outline:\n" + json.dumps(payload) + "\nThanks."
        parsed = parse_outline_json(raw)
        assert parsed["outline"][0]["title"] == "A"

    def test_parse_outline_json_missing_outline_key(self):
        with pytest.raises(ValueError, match="outline"):
            parse_outline_json(json.dumps({"meeting_summary": "Test"}))

    def test_parse_outline_json_outline_not_list(self):
        with pytest.raises(ValueError, match="outline"):
            parse_outline_json(json.dumps({"outline": "wrong"}))

    def test_parse_outline_json_invalid_json(self):
        with pytest.raises(ValueError, match="invalid outline JSON"):
            parse_outline_json("not-json")

    def test_parse_agenda_json_still_works(self, tmp_path):
        payload = _minimal_agenda()
        plain = json.dumps(payload)
        fenced = f"```json\n{plain}\n```"
        preamble = f"Agenda follows:\n{plain}\nDone."

        parsed_plain = parse_agenda_json(plain, save_dir=str(tmp_path))
        parsed_fenced = parse_agenda_json(fenced, save_dir=str(tmp_path))
        parsed_preamble = parse_agenda_json(preamble, save_dir=str(tmp_path))

        assert parsed_plain["session_name"] == "Test Session"
        assert parsed_fenced["session_name"] == "Test Session"
        assert parsed_preamble["session_name"] == "Test Session"

    def test_extract_json_object_shared(self):
        outline_payload = {"meeting_summary": "Summary", "outline": []}
        agenda_payload = _minimal_agenda()

        wrapped_outline = f"prefix\n```json\n{json.dumps(outline_payload)}\n```\nsuffix"
        wrapped_agenda = f"prefix\n```json\n{json.dumps(agenda_payload)}\n```\nsuffix"

        assert _extract_json_object(wrapped_outline) == json.dumps(outline_payload)
        assert _extract_json_object(wrapped_agenda) == json.dumps(agenda_payload)


class TestStep6IntegrationAndAudit:
    def test_hypothetical_5th_plugin_appears_in_generation_prompt(self, monkeypatch):
        synthetic = _synthetic_catalog(5)
        monkeypatch.setattr(
            "app.services.activity_catalog.get_enriched_activity_catalog",
            lambda: synthetic,
        )
        prompt = build_generation_prompt()
        assert "epsilon" in prompt

    def test_hypothetical_5th_plugin_appears_in_outline_prompt(self, monkeypatch):
        synthetic = _synthetic_catalog(5)
        monkeypatch.setattr(
            "app.services.activity_catalog.get_enriched_activity_catalog",
            lambda: synthetic,
        )
        prompt = build_outline_prompt()
        assert "epsilon" in prompt

    def test_no_hardcoded_tool_types_in_new_functions(self):
        forbidden = ["brainstorming", "voting", "rank_order_voting", "categorization"]
        for fn in [
            build_generation_prompt,
            build_outline_prompt,
            _build_tool_type_enum,
            _build_config_overrides_block,
            _build_duration_guidance,
        ]:
            source = inspect.getsource(fn)
            for token in forbidden:
                assert token not in source

    def test_build_system_prompt_unchanged(self):
        prompt = build_system_prompt()
        for token in ["PURPOSE", "RULES", "IDENTITY", "STANDARD SEQUENCES", "MOTION"]:
            assert token in prompt

    def test_full_round_trip_outline_then_generation(self):
        history = [
            {"role": "assistant", "content": "Let's design your meeting."},
            {"role": "user", "content": "Need a 1-day prioritization workshop."},
        ]
        outline_messages = build_outline_messages(history)
        assert outline_messages[-1]["role"] == "user"

        outline_raw = json.dumps(
            {
                "meeting_summary": "Prioritization workshop",
                "outline": [
                    {"tool_type": "brainstorming", "title": "Collect options", "duration_minutes": 15},
                    {"tool_type": "voting", "title": "Down-select options", "duration_minutes": 10},
                ],
            }
        )
        parsed_outline = parse_outline_json(outline_raw)
        generation_messages = build_generation_messages(
            history, outline=parsed_outline["outline"]
        )
        final_prompt = generation_messages[-1]["content"]
        assert "Collect options" in final_prompt
        assert "Down-select options" in final_prompt
        for field in ["tool_type", "title", "instructions", "config_overrides", "duration_minutes"]:
            assert field in final_prompt

    def test_generation_prompt_with_synthetic_catalog(self, monkeypatch):
        synthetic = _synthetic_catalog(5)
        monkeypatch.setattr(
            "app.services.activity_catalog.get_enriched_activity_catalog",
            lambda: synthetic,
        )
        prompt = build_generation_prompt()
        for tool_type in ["alpha", "beta", "gamma", "delta", "epsilon"]:
            assert tool_type in prompt
        for real_tool_type in ["brainstorming", "voting", "rank_order_voting", "categorization"]:
            assert real_tool_type not in prompt


# ---------------------------------------------------------------------------
# Step 1 helper fragments — catalog-driven
# ---------------------------------------------------------------------------

class TestCatalogDrivenHelperFragments:
    def test_tool_type_enum_from_catalog(self):
        catalog = [
            {"tool_type": "alpha"},
            {"tool_type": "beta"},
        ]
        assert _build_tool_type_enum(catalog) == "alpha|beta"

    def test_tool_type_enum_ordering(self):
        catalog = [
            {"tool_type": "zeta"},
            {"tool_type": "alpha"},
            {"tool_type": "gamma"},
        ]
        assert _build_tool_type_enum(catalog) == "zeta|alpha|gamma"

    def test_config_overrides_block_contains_all_types(self):
        block = _build_config_overrides_block(_catalog_for_helpers())
        for tool_type in ["brainstorming", "voting", "rank_order_voting", "categorization"]:
            assert f"// {tool_type}:" in block

    def test_config_overrides_block_skips_internal_keys(self):
        block = _build_config_overrides_block(_catalog_for_helpers())
        assert '"options" (' not in block
        assert '"vote_type" (' not in block
        assert '"max_votes" (int)' in block

    def test_duration_guidance_all_types(self):
        guidance = _build_duration_guidance(_catalog_for_helpers())
        for tool_type in ["brainstorming", "voting", "rank_order_voting", "categorization"]:
            assert f"{tool_type}:" in guidance

    def test_duration_guidance_missing_range(self):
        guidance = _build_duration_guidance(
            [
                {
                    "tool_type": "alpha",
                    "default_config": {},
                    "typical_duration_minutes": {},
                }
            ]
        )
        assert "alpha: varies" in guidance


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
        assert msgs[-1]["content"] == build_generation_prompt()

    def test_does_not_mutate_input_history(self):
        history = [{"role": "user", "content": "test"}]
        original_history = list(history)
        original_len = len(history)
        build_generation_messages(history)
        assert len(history) == original_len
        assert history == original_history

    def test_build_generation_messages_without_outline(self):
        history = [{"role": "user", "content": "design a session"}]
        msgs = build_generation_messages(history)
        assert msgs[-1]["content"] == build_generation_prompt()

    def test_build_generation_messages_with_outline(self):
        history = [{"role": "user", "content": "design a session"}]
        outline = [
            {"tool_type": "alpha", "title": "Start"},
            {"tool_type": "beta", "title": "Decide"},
        ]
        msgs = build_generation_messages(history, outline=outline)
        assert msgs[-1]["content"] == build_generation_prompt(outline=outline)

    def test_build_generation_messages_backward_compatible(self):
        history = [{"role": "user", "content": "test"}]
        msgs = build_generation_messages(history)
        assert len(msgs) == 2


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
