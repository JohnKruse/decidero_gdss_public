"""Tests for orchestration document validation and parsing.

Canary: Insolent Metronome


This focused test module is authored instead of extending test_agenda_validator.py
because the agenda validator is designed for validation of user-configured
meeting designer agendas, whereas this suite tests the loader, parser,
AST generation, and schema invariants of the process orchestration grammar.
"""

from __future__ import annotations

import json
from app.services.orchestration_loader import (
    load_orchestration_file,
    validate_orchestration,
    SequenceStep,
    IterateStep,
    ActivityStep,
    FacilitatorDecisionStep,
    AIDecisionStep,
    ConditionalStep,
)

VALID_DOC = {
    "name": "Delphi Consensus Iteration",
    "version": "1.0",
    "author": "Vulcan Science Academy",
    "citation": "Spock (2026)",
    "metadata": {
        "thinklets": ["delphi_loop"],
        "collaboration_patterns": ["diverge", "converge"],
        "deliverables": ["Consensus Report"],
        "group_size_range": {"min": 3, "max": 12},
        "typical_duration_minutes": {"min": 15, "max": 45}
    },
    "steps": [
        {
            "type": "sequence",
            "steps": [
                {
                    "type": "activity",
                    "tool_type": "brainstorming",
                    "title": "Brainstorm Delphi Ideas",
                    "config": {"allow_anonymous": True}
                },
                {
                    "type": "iterate",
                    "max_rounds": 5,
                    "convergence_predicate": {
                        "name": "IQRStabilityPredicate",
                        "config": {"threshold": 0.5}
                    },
                    "bundle_transform": {
                        "name": "DelphiStatisticalAggregationTransform",
                        "config": {}
                    },
                    "steps": [
                        {
                            "type": "activity",
                            "tool_type": "rank_order_voting",
                            "title": "Rate Delphi Items"
                        }
                    ]
                }
            ]
        }
    ]
}


def test_valid_document_parses_successfully(monkeypatch) -> None:
    """Verify that a valid orchestration document is parsed into the typed AST representation."""
    monkeypatch.setattr(
        "app.services.orchestration_loader.get_enriched_activity_catalog",
        lambda: [{"tool_type": "brainstorming"}, {"tool_type": "rank_order_voting"}]
    )
    doc_str = json.dumps(VALID_DOC)
    doc = load_orchestration_file(doc_str)

    assert doc.name == "Delphi Consensus Iteration"
    assert doc.version == "1.0"
    assert doc.author == "Vulcan Science Academy"
    assert doc.citation == "Spock (2026)"
    assert doc.metadata.thinklets == ["delphi_loop"]
    assert doc.metadata.group_size_range == {"min": 3, "max": 12}
    
    assert len(doc.steps) == 1
    seq = doc.steps[0]
    assert isinstance(seq, SequenceStep)
    assert len(seq.steps) == 2
    
    act = seq.steps[0]
    assert isinstance(act, ActivityStep)
    assert act.tool_type == "brainstorming"
    assert act.title == "Brainstorm Delphi Ideas"
    assert act.config == {"allow_anonymous": True}
    
    it = seq.steps[1]
    assert isinstance(it, IterateStep)
    assert it.max_rounds == 5
    assert it.convergence_predicate == {"name": "IQRStabilityPredicate", "config": {"threshold": 0.5}}
    assert it.bundle_transform == {"name": "DelphiStatisticalAggregationTransform", "config": {}}
    assert len(it.steps) == 1
    assert isinstance(it.steps[0], ActivityStep)
    assert it.steps[0].tool_type == "rank_order_voting"


def test_missing_top_level_fails() -> None:
    """Verify that missing top-level properties are caught by the validator."""
    invalid_doc = VALID_DOC.copy()
    del invalid_doc["name"]
    
    res = validate_orchestration(invalid_doc)
    assert not res.valid
    assert any(e.field == "name" for e in res.errors)


def test_invalid_metadata_range_fails() -> None:
    """Verify that min > max in metadata ranges is flagged as invalid."""
    invalid_doc = json.loads(json.dumps(VALID_DOC))
    invalid_doc["metadata"]["group_size_range"]["min"] = 15
    invalid_doc["metadata"]["group_size_range"]["max"] = 5
    
    res = validate_orchestration(invalid_doc)
    assert not res.valid
    assert any("min" in e.message and "max" in e.message for e in res.errors)


def test_conditional_step_reserved_error(monkeypatch) -> None:
    """Verify that the conditional step type is treated as a reserved/deferred error."""
    monkeypatch.setattr(
        "app.services.orchestration_loader.get_enriched_activity_catalog",
        lambda: [{"tool_type": "brainstorming"}, {"tool_type": "rank_order_voting"}]
    )
    invalid_doc = json.loads(json.dumps(VALID_DOC))
    invalid_doc["steps"][0]["steps"].append({
        "type": "conditional"
    })
    
    res = validate_orchestration(invalid_doc)
    assert not res.valid
    assert any("conditional step is reserved" in e.message for e in res.errors)


def test_review_required_ai_decision_pairing_error(monkeypatch) -> None:
    """Verify that an ai-decision with review_required=true not followed by facilitator-decision is invalid."""
    monkeypatch.setattr(
        "app.services.orchestration_loader.get_enriched_activity_catalog",
        lambda: [{"tool_type": "brainstorming"}, {"tool_type": "rank_order_voting"}]
    )
    
    invalid_doc = json.loads(json.dumps(VALID_DOC))
    invalid_doc["steps"][0]["steps"].append({
        "type": "ai-decision",
        "prompt_template": "Summarize {{ideas}}",
        "output_schema": {},
        "review_required": True
    })
    
    res = validate_orchestration(invalid_doc)
    assert not res.valid
    assert any("must be immediately followed by a facilitator-decision" in e.message for e in res.errors)


def test_review_required_ai_decision_pairing_success(monkeypatch) -> None:
    """Verify that an ai-decision with review_required=true followed by a facilitator-decision is valid."""
    monkeypatch.setattr(
        "app.services.orchestration_loader.get_enriched_activity_catalog",
        lambda: [{"tool_type": "brainstorming"}, {"tool_type": "rank_order_voting"}]
    )
    
    valid_doc = json.loads(json.dumps(VALID_DOC))
    valid_doc["steps"][0]["steps"].extend([
        {
            "type": "ai-decision",
            "prompt_template": "Summarize {{ideas}}",
            "output_schema": {},
            "review_required": True
        },
        {
            "type": "facilitator-decision",
            "prompt": "Approve AI summary?",
            "options": ["yes", "no"]
        }
    ])
    
    res = validate_orchestration(valid_doc)
    assert res.valid


def test_unregistered_activity_tool_type_fails(monkeypatch) -> None:
    """Verify that an activity step with an unregistered tool_type is invalid."""
    monkeypatch.setattr(
        "app.services.orchestration_loader.get_enriched_activity_catalog",
        lambda: [{"tool_type": "brainstorming"}]
    )
    invalid_doc = json.loads(json.dumps(VALID_DOC))
    invalid_doc["steps"][0]["steps"].append({
        "type": "activity",
        "tool_type": "unknown_tool",
        "title": "Should fail validation"
    })
    
    res = validate_orchestration(invalid_doc)
    assert not res.valid
    assert any("tool_type 'unknown_tool' is not registered" in e.message for e in res.errors)


# Schema-vs-loader correspondence corpus.
#
# Each entry pairs a minimal document fragment with its expected validity
# under the loader. The corpus mirrors the constraints in
# docs/schemas/orchestration.schema.json so that drift between the schema
# file and the hand-rolled loader surfaces as a test failure.
#
# Schema and loader agree on:
#   - `conditional` is excluded from the type enum (schema $comment, loader
#     hard-rejects with "reserved and deferred"). See QC fix #2.
#   - `iterate` requires steps, max_rounds, convergence_predicate,
#     bundle_transform; named registry entries each require name + config.
#   - `activity` requires tool_type (lowercase snake_case, registered) and
#     non-empty title.
#   - `facilitator-decision` requires non-empty prompt and a non-empty
#     options list of non-empty strings.
#   - `ai-decision` requires prompt_template, output_schema, review_required.
#   - ai-decision review_required=true requires an immediately-following
#     facilitator-decision in the same step list.
#   - metadata ranges require integer min/max with min <= max.


def _minimal_doc(steps):
    return {
        "name": "n",
        "version": "1",
        "author": "a",
        "citation": "c",
        "metadata": {
            "thinklets": ["t"],
            "collaboration_patterns": ["p"],
            "deliverables": ["d"],
            "group_size_range": {"min": 1, "max": 2},
            "typical_duration_minutes": {"min": 1, "max": 2}
        },
        "steps": steps
    }


CORRESPONDENCE_CORPUS = [
    # (label, steps, expected_valid, expected_error_substring_or_None)
    ("conditional_at_top_rejected",
     [{"type": "conditional"}],
     False, "conditional step is reserved"),
    ("unknown_step_type",
     [{"type": "loop"}],
     False, "Invalid step type"),
    ("iterate_missing_max_rounds",
     [{"type": "iterate", "steps": [],
       "convergence_predicate": {"name": "fixed_n", "config": {}},
       "bundle_transform": {"name": "identity", "config": {}}}],
     False, "max_rounds"),
    ("iterate_zero_max_rounds",
     [{"type": "iterate", "steps": [], "max_rounds": 0,
       "convergence_predicate": {"name": "fixed_n", "config": {}},
       "bundle_transform": {"name": "identity", "config": {}}}],
     False, "positive integer"),
    ("iterate_predicate_missing_name",
     [{"type": "iterate", "steps": [], "max_rounds": 1,
       "convergence_predicate": {"config": {}},
       "bundle_transform": {"name": "identity", "config": {}}}],
     False, "convergence_predicate"),
    ("activity_uppercase_tool_type",
     [{"type": "activity", "tool_type": "Brainstorming", "title": "x"}],
     False, "snake_case"),
    ("activity_missing_title",
     [{"type": "activity", "tool_type": "brainstorming"}],
     False, "title"),
    ("facilitator_decision_empty_options",
     [{"type": "facilitator-decision", "prompt": "?", "options": []}],
     False, "non-empty list"),
    ("ai_decision_review_required_no_pair",
     [{"type": "ai-decision", "prompt_template": "t",
       "output_schema": {}, "review_required": True}],
     False, "immediately followed by a facilitator-decision"),
    ("ai_decision_review_required_with_pair",
     [{"type": "ai-decision", "prompt_template": "t",
       "output_schema": {}, "review_required": True},
      {"type": "facilitator-decision", "prompt": "ok?",
       "options": ["yes"]}],
     True, None),
    ("metadata_range_min_gt_max",
     None,  # handled inline below
     False, "cannot exceed"),
    # Plainspoken Marmot: unified gate + report/recommender (L.1/L.2/L.3).
    ("round_gate_old_enum_rejected",
     [{"type": "iterate", "steps": [], "max_rounds": 2,
       "convergence_predicate": {"name": "fixed_n", "config": {}},
       "bundle_transform": {"name": "identity", "config": {}},
       "round_gate": {"mode": "facilitator", "recommendation": "convergence"}}],
     False, "now embeds a 'decision'"),
    ("round_gate_embedded_decision_accepted",
     [{"type": "iterate", "steps": [], "max_rounds": 2,
       "convergence_predicate": {"name": "fixed_n", "config": {}},
       "bundle_transform": {"name": "identity", "config": {}},
       "round_gate": {"decision": {
           "prompt": "?", "options": ["continue", "conclude"],
           "recommender": {"rule": [
               {"when": "converged", "recommend": "conclude"},
               {"default": "continue"}]}}}}],
     True, None),
    ("round_gate_missing_decision",
     [{"type": "iterate", "steps": [], "max_rounds": 2,
       "convergence_predicate": {"name": "fixed_n", "config": {}},
       "bundle_transform": {"name": "identity", "config": {}},
       "round_gate": {}}],
     False, "Missing required 'decision'"),
    ("facilitator_decision_bad_report_audience",
     [{"type": "facilitator-decision", "prompt": "?", "options": ["a"],
       "report": {"summarizer": "x", "audience": "nobody"}}],
     False, "audience"),
    ("facilitator_decision_unsafe_recommender_condition",
     [{"type": "facilitator-decision", "prompt": "?", "options": ["a"],
       "recommender": {"rule": [{"when": "len(items) > 0", "recommend": "a"}]}}],
     False, "unsafe or invalid"),
    ("facilitator_decision_report_recommender_accepted",
     [{"type": "facilitator-decision", "prompt": "?", "options": ["continue", "conclude"],
       "report": {"summarizer": "delphi_round_agreement", "config": {}, "audience": "facilitator"},
       "recommender": {"metrics": ["delphi_round_agreement"], "rule": [
           {"when": "median_iqr <= 1.0", "recommend": "conclude"},
           {"default": "continue"}]}}],
     True, None),
]


def test_schema_loader_correspondence(monkeypatch):
    """Pin the schema/loader correspondence corpus.

    If a future schema edit changes the acceptable shapes (or the loader
    diverges), one of these cases will flip and force the author to
    reconcile both artifacts.
    """
    monkeypatch.setattr(
        "app.services.orchestration_loader.get_enriched_activity_catalog",
        lambda: [{"tool_type": "brainstorming"}]
    )

    for label, steps, expected_valid, expected_substr in CORRESPONDENCE_CORPUS:
        if label == "metadata_range_min_gt_max":
            doc = _minimal_doc([])
            doc["metadata"]["group_size_range"] = {"min": 5, "max": 1}
        else:
            doc = _minimal_doc(steps)

        res = validate_orchestration(doc)
        assert res.valid == expected_valid, (
            f"{label}: expected valid={expected_valid}, got {res.valid}; "
            f"errors={[e.message for e in res.errors]}"
        )
        if expected_substr is not None:
            assert any(expected_substr in e.message for e in res.errors), (
                f"{label}: expected error containing {expected_substr!r}, "
                f"got {[e.message for e in res.errors]}"
            )


def test_load_orchestration_path_and_data_split(tmp_path, monkeypatch):
    """The split entry points each handle their own input shape."""
    monkeypatch.setattr(
        "app.services.orchestration_loader.get_enriched_activity_catalog",
        lambda: [{"tool_type": "brainstorming"}]
    )
    from app.services.orchestration_loader import (
        load_orchestration_data,
        load_orchestration_path,
    )

    doc_dict = _minimal_doc([
        {"type": "activity", "tool_type": "brainstorming", "title": "x"}
    ])

    parsed_from_data = load_orchestration_data(doc_dict)
    assert parsed_from_data.name == "n"

    p = tmp_path / "orch.json"
    p.write_text(json.dumps(doc_dict), encoding="utf-8")
    parsed_from_path = load_orchestration_path(p)
    assert parsed_from_path.name == "n"
