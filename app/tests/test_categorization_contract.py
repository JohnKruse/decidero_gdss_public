import copy

import pytest
from pydantic import ValidationError

from app.schemas.categorization_contract import (
    validate_categorization_config,
    validate_categorization_output,
    validate_categorization_state,
)
from app.tests.fixtures.categorization_contract_fixtures import (
    FACILITATOR_LIVE_CONFIG,
    FINAL_OUTPUT,
    PARALLEL_STATE,
)


def test_validate_facilitator_live_config_fixture():
    payload = copy.deepcopy(FACILITATOR_LIVE_CONFIG)
    validated = validate_categorization_config(payload)
    assert validated.mode == "FACILITATOR_LIVE"
    assert validated.schema_version == 1


def test_validate_parallel_state_fixture():
    payload = copy.deepcopy(PARALLEL_STATE)
    validated = validate_categorization_state(payload)
    assert validated.mode == "PARALLEL_BALLOT"
    assert "item-1" in validated.agreement_metrics


def test_validate_final_output_fixture():
    payload = copy.deepcopy(FINAL_OUTPUT)
    validated = validate_categorization_output(payload)
    assert validated.activity_id.endswith("CATGRY-0001")
    assert validated.finalization_metadata.mode == "PARALLEL_BALLOT"


def test_contract_allows_additive_fields():
    payload = copy.deepcopy(FACILITATOR_LIVE_CONFIG)
    payload["new_future_field"] = {"enabled": True}
    validated = validate_categorization_config(payload)
    assert validated.model_extra["new_future_field"]["enabled"] is True


def test_contract_fails_when_required_output_block_missing():
    payload = copy.deepcopy(FINAL_OUTPUT)
    payload.pop("finalization_metadata")
    with pytest.raises(ValidationError):
        validate_categorization_output(payload)


def test_contract_fails_when_required_state_field_missing():
    broken = copy.deepcopy(PARALLEL_STATE)
    broken.pop("activity_id")
    with pytest.raises(ValidationError):
        validate_categorization_state(broken)
