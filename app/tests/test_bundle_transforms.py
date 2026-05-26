"""Tests for bundle transforms.

Canary: Convergent Yak
"""

from app.services.bundle_transforms import (
    get_bundle_transform_registry,
    IdentityBundleTransform,
    DelphiStatisticalAggregationTransform,
)


def test_registry_contains_expected_transforms():
    registry = get_bundle_transform_registry()
    assert "identity" in registry.list_transforms()
    assert "delphi_statistical_aggregation" in registry.list_transforms()

    assert isinstance(registry.get_transform("identity"), IdentityBundleTransform)
    assert isinstance(
        registry.get_transform("delphi_statistical_aggregation"),
        DelphiStatisticalAggregationTransform,
    )


def test_identity_transform():
    transform = IdentityBundleTransform()
    input_bundle = {
        "items": [
            {"content": "Idea A", "metadata": {}, "source": {}},
        ],
        "metadata": {"test": True}
    }
    output = transform(input_bundle, {})
    assert output == input_bundle


def test_delphi_statistical_aggregation_transform_basic():
    transform = DelphiStatisticalAggregationTransform()
    input_bundle = {
        "items": [
            {
                "id": "1",
                "content": "Option A",
                "metadata": {
                    "rank_order_voting": {
                        "option_id": "opt_a"
                    }
                },
                "source": {}
            },
            {
                "id": "2",
                "content": "Option B",
                "metadata": {
                    "rank_order_voting": {
                        "option_id": "opt_b"
                    }
                },
                "source": {}
            }
        ],
        "metadata": {
            "votes": [
                {"user_id": "u1", "option_id": "opt_a", "rank_position": 1},
                {"user_id": "u1", "option_id": "opt_b", "rank_position": 2},
                {"user_id": "u2", "option_id": "opt_a", "rank_position": 2},
                {"user_id": "u2", "option_id": "opt_b", "rank_position": 1},
                {"user_id": "u3", "option_id": "opt_a", "rank_position": 1},
                {"user_id": "u3", "option_id": "opt_b", "rank_position": 2},
            ]
        }
    }

    output = transform(input_bundle, {})

    items = output["items"]
    assert len(items) == 2

    # Option A: ranks [1, 2, 1] -> sorted [1, 1, 2]
    # Median is 1.0. Q1 = 1.0, Q3 = 1.5, IQR = 0.5. Mean = 4/3.
    opt_a_item = next(
        item for item in items if item["metadata"]["rank_order_voting"]["option_id"] == "opt_a"
    )
    delphi_a = opt_a_item["metadata"]["delphi"]
    assert delphi_a["median"] == 1.0
    assert delphi_a["iqr"] == 0.5
    assert delphi_a["outlier_flags"] == {"u1": False, "u2": False, "u3": False}
    assert delphi_a["outliers"] == []

    # Option B: ranks [2, 1, 2] -> sorted [1, 2, 2]
    # Median is 2.0. Q1 = 1.5, Q3 = 2.0, IQR = 0.5.
    opt_b_item = next(
        item for item in items if item["metadata"]["rank_order_voting"]["option_id"] == "opt_b"
    )
    delphi_b = opt_b_item["metadata"]["delphi"]
    assert delphi_b["median"] == 2.0
    assert delphi_b["iqr"] == 0.5
    assert delphi_b["outlier_flags"] == {"u1": False, "u2": False, "u3": False}
    assert delphi_b["outliers"] == []


def test_delphi_statistical_aggregation_transform_outliers():
    transform = DelphiStatisticalAggregationTransform()
    input_bundle = {
        "items": [
            {
                "id": "1",
                "content": "Option A",
                "metadata": {
                    "rank_order_voting": {
                        "option_id": "opt_a"
                    }
                },
                "source": {}
            }
        ],
        "metadata": {
            "votes": [
                # Let's create a clear outlier.
                # Ranks: [1, 1, 1, 1, 5] -> sorted: [1, 1, 1, 1, 5]
                # Median = 1.0
                # Q1 = 1.0, Q3 = 1.0, IQR = 0.0
                # Since IQR is 0.0, lower_bound = 1.0, upper_bound = 1.0
                # Ranks differing from 1.0 are outliers.
                {"user_id": "u1", "option_id": "opt_a", "rank_position": 1},
                {"user_id": "u2", "option_id": "opt_a", "rank_position": 1},
                {"user_id": "u3", "option_id": "opt_a", "rank_position": 1},
                {"user_id": "u4", "option_id": "opt_a", "rank_position": 1},
                {"user_id": "u5", "option_id": "opt_a", "rank_position": 5},
            ]
        }
    }

    output = transform(input_bundle, {})
    items = output["items"]
    delphi = items[0]["metadata"]["delphi"]
    assert delphi["median"] == 1.0
    assert delphi["iqr"] == 0.0
    assert delphi["outlier_flags"] == {
        "u1": False,
        "u2": False,
        "u3": False,
        "u4": False,
        "u5": True,
    }
    assert delphi["outliers"] == ["u5"]
