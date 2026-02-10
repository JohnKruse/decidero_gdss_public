from app.plugins.builtin.categorization_plugin import CategorizationPlugin
from app.routers.transfer import _append_comments_to_content


def test_comments_parentheses_format_matches_transfer_convention():
    idea_entry = {"id": 42, "content": "Base idea"}
    comments_by_parent = {
        "42": [
            {"content": "first comment"},
            {"content": "second comment"},
        ]
    }

    transfer_text = _append_comments_to_content(idea_entry, comments_by_parent)
    categorization_text = CategorizationPlugin._append_comments_to_content(
        idea_id=idea_entry["id"],
        content=idea_entry["content"],
        comments_by_parent=comments_by_parent,
    )

    assert transfer_text == categorization_text
    assert transfer_text == "Base idea (Comments: first comment; second comment)"
