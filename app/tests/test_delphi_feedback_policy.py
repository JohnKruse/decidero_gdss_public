"""Tests for adaptive Delphi controlled-feedback selection."""

from app.services.delphi_feedback_policy import build_delphi_feedback_selection


def _item(key, iqr, dispersion=0.0):
    return {
        "content": key,
        "metadata": {
            "rank_order_voting": {"option_id": f"rank:{key}"},
            "delphi": {
                "median": 1.0,
                "iqr": iqr,
                "dispersion": dispersion,
            },
        },
    }


def _bundle(items):
    return {"items": items, "metadata": {}}


def test_high_disagreement_suggests_top_quarter_and_caps_at_half():
    items = [_item(f"idea-{idx}", 3.0 + idx / 100.0) for idx in range(12)]

    result = build_delphi_feedback_selection(_bundle(items))

    assert result["band_counts"] == {"green": 0, "yellow": 0, "red": 12}
    assert result["suggested_count"] == 3
    assert result["max_selectable_count"] == 6
    assert len(result["selected_item_keys"]) == 3


def test_moderate_disagreement_uses_smaller_suggestion_fraction():
    items = [_item(f"idea-{idx}", 1.5) for idx in range(12)]

    result = build_delphi_feedback_selection(_bundle(items))

    assert result["band_counts"] == {"green": 0, "yellow": 12, "red": 0}
    assert result["suggested_count"] == 2
    assert result["max_selectable_count"] == 6


def test_all_green_suggests_skipping_comments():
    items = [_item(f"idea-{idx}", 0.5) for idx in range(8)]

    result = build_delphi_feedback_selection(_bundle(items))

    assert result["band_counts"] == {"green": 8, "yellow": 0, "red": 0}
    assert result["suggested_count"] == 0
    assert result["selected_item_keys"] == []
    assert result["allow_skip"] is True


def test_tie_breaks_by_dispersion_for_selected_items():
    items = [
        _item("lower-dispersion", 3.0, dispersion=0.2),
        _item("higher-dispersion", 3.0, dispersion=1.2),
        _item("green", 0.0, dispersion=0.0),
    ]

    result = build_delphi_feedback_selection(_bundle(items))

    assert result["suggested_count"] == 1
    assert result["selected_item_keys"] == ["rank:higher-dispersion"]
    assert result["items"][0]["item_key"] == "rank:higher-dispersion"


def test_small_disputed_set_still_suggests_one_item():
    items = [
        _item("disputed", 3.0, dispersion=1.0),
        _item("settled-a", 0.0),
        _item("settled-b", 0.0),
    ]

    result = build_delphi_feedback_selection(_bundle(items))

    assert result["suggested_count"] == 1
    assert result["max_selectable_count"] == 2
    assert result["selected_item_keys"] == ["rank:disputed"]


def test_partial_policy_override_preserves_other_defaults():
    items = [_item(f"idea-{idx}", 3.0) for idx in range(10)]

    result = build_delphi_feedback_selection(
        _bundle(items),
        {"comment_selection": {"high_disagreement_fraction": 0.1}},
    )

    assert result["suggested_count"] == 1
    assert result["max_selectable_count"] == 5
    assert result["allow_skip"] is True
