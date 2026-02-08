from app.utils.user_colors import get_user_color


class _UserStub:
    def __init__(self, color: str | None):
        self.avatar_color = color


def test_user_color_prefers_user_avatar_color():
    color = "#1A2B3C"
    user = _UserStub(color)
    assert get_user_color(user=user) == color


def test_user_color_handles_missing_identifier():
    assert get_user_color() is None
    assert get_user_color(None) is None
    assert get_user_color("") is None
