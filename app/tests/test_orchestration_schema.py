"""Tests for COPPER-HERON-4/Insolent Metronome orchestration document validation and parsing.

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
