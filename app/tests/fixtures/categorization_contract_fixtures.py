FACILITATOR_LIVE_CONFIG = {
    "schema_version": 1,
    "mode": "FACILITATOR_LIVE",
    "items": [
        {
            "id": 101,
            "content": "Idea A",
            "metadata": {"origin": "brainstorming"},
            "source": {
                "meeting_id": "MTG20260210-0001",
                "activity_id": "MTG20260210-0001-BRAINS-0001",
            },
        },
        "Idea B",
    ],
    "buckets": [
        {"category_id": "UNSORTED", "title": "Unsorted Ideas", "order_index": 0},
        {"category_id": "CAT-1", "title": "Category 1", "order_index": 1},
    ],
    "single_assignment_only": True,
    "allow_unsorted_submission": True,
    "agreement_threshold": 0.6,
    "minimum_ballots": 1,
    "tie_policy": "TIE_UNRESOLVED",
    "missing_vote_handling": "ignore",
    "private_until_reveal": True,
}


PARALLEL_STATE = {
    "schema_version": 1,
    "meeting_id": "MTG20260210-0001",
    "activity_id": "MTG20260210-0001-CATGRY-0001",
    "mode": "PARALLEL_BALLOT",
    "locked": False,
    "buckets": [
        {
            "category_id": "UNSORTED",
            "title": "Unsorted Ideas",
            "order_index": 0,
            "status": "active",
        },
        {"category_id": "CAT-1", "title": "Category 1", "order_index": 1, "status": "active"},
        {"category_id": "CAT-2", "title": "Category 2", "order_index": 2, "status": "active"},
    ],
    "assignments": {"item-1": "CAT-1", "item-2": "UNSORTED"},
    "ballots": {
        "USR-A": {"item-1": "CAT-1", "item-2": "CAT-2"},
        "USR-B": {"item-1": "CAT-1", "item-2": "UNSORTED"},
    },
    "agreement_metrics": {
        "item-1": {
            "top_category_id": "CAT-1",
            "top_count": 2,
            "top_share": 1.0,
            "second_share": 0.0,
            "margin": 1.0,
            "status_label": "AGREED",
        },
        "item-2": {
            "top_category_id": "CAT-2",
            "top_count": 1,
            "top_share": 0.5,
            "second_share": 0.5,
            "margin": 0.0,
            "status_label": "DISPUTED",
        },
    },
}


FINAL_OUTPUT = {
    "schema_version": 1,
    "meeting_id": "MTG20260210-0001",
    "activity_id": "MTG20260210-0001-CATGRY-0001",
    "categories": [
        {"category_id": "UNSORTED", "title": "Unsorted Ideas", "item_ids": []},
        {"category_id": "CAT-1", "title": "Category 1", "item_ids": ["item-1"]},
        {"category_id": "CAT-2", "title": "Category 2", "item_ids": ["item-2"]},
    ],
    "finalization_metadata": {
        "mode": "PARALLEL_BALLOT",
        "finalized_at": "2026-02-10T10:00:00Z",
        "facilitator_id": "USR-ADMIN-001",
        "agreement_threshold": 0.6,
        "minimum_ballots": 2,
        "ballot_count": 2,
    },
    "tallies": {"item-2": {"CAT-2": 1, "UNSORTED": 1}},
}
