from app.services.transfer_transforms import (
    PROFILE_BUCKET_ROLLUP,
    PROFILE_BUCKET_SUFFIX,
    apply_transfer_transform,
)


def test_categorization_bucket_rollup_includes_empty_buckets_and_sorts_by_count_then_alpha():
    items = [
        {
            "id": "i1",
            "content": "Create handbook",
            "metadata": {"categorization": {"bucket_id": "rules", "bucket_title": "Rules"}},
        },
        {
            "id": "i2",
            "content": "Update policy",
            "metadata": {"categorization": {"bucket_id": "rules", "bucket_title": "Rules"}},
        },
        {
            "id": "i3",
            "content": "Move parking signs",
            "metadata": {"categorization": {"bucket_id": "logistics", "bucket_title": "Logistics"}},
        },
        {
            "id": "i4",
            "content": "Reserve room",
            "metadata": {"categorization": {"bucket_id": "logistics", "bucket_title": "Logistics"}},
        },
    ]
    source_metadata = {
        "categorization_buckets": [
            {"category_id": "rules", "title": "Rules", "order_index": 1},
            {"category_id": "logistics", "title": "Logistics", "order_index": 2},
            {"category_id": "empty", "title": "Empty", "order_index": 3},
        ]
    }

    result = apply_transfer_transform(
        items=items,
        donor_tool_type="categorization",
        requested_profile=PROFILE_BUCKET_ROLLUP,
        source_metadata=source_metadata,
    )

    assert result.profile == PROFILE_BUCKET_ROLLUP
    assert [entry["content"] for entry in result.items] == [
        "Category: Logistics (Ideas: Move parking signs; Reserve room)",
        "Category: Rules (Ideas: Create handbook; Update policy)",
        "Category: Empty (Ideas: )",
    ]


def test_categorization_bucket_suffix_sorts_by_bucket_order_then_preserves_item_order():
    items = [
        {
            "id": "i1",
            "content": "Idea C",
            "metadata": {
                "categorization": {
                    "bucket_id": "rules",
                    "bucket_title": "Rules & Regulations",
                    "bucket_order_index": 2,
                }
            },
        },
        {
            "id": "i2",
            "content": "Idea A",
            "metadata": {
                "categorization": {
                    "bucket_id": "logistics",
                    "bucket_title": "Logistics",
                    "bucket_order_index": 1,
                }
            },
        },
        {
            "id": "i3",
            "content": "Idea B",
            "metadata": {
                "categorization": {
                    "bucket_id": "logistics",
                    "bucket_title": "Logistics",
                    "bucket_order_index": 1,
                }
            },
        },
    ]

    result = apply_transfer_transform(
        items=items,
        donor_tool_type="categorization",
        requested_profile=PROFILE_BUCKET_SUFFIX,
        source_metadata={},
    )

    assert result.profile == PROFILE_BUCKET_SUFFIX
    assert [entry["content"] for entry in result.items] == [
        "Idea A (Category: Logistics)",
        "Idea B (Category: Logistics)",
        "Idea C (Category: Rules & Regulations)",
    ]
