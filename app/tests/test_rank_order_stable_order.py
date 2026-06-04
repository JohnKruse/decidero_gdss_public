"""The per-participant randomized order must be stable across Delphi rounds.

Option ids embed the activity id, and each round is a new activity, so the order
key must key on the item's stable identity (the part after the activity prefix),
not the raw option id — otherwise a participant's list reshuffles every round.
"""

from __future__ import annotations

from app.services.rank_order_voting_manager import RankOrderVotingManager as M


def test_stable_option_key_strips_activity_prefix():
    assert M._stable_option_key("ACT1:idea-5") == "idea-5"
    assert M._stable_option_key("ACT2:idea-5") == "idea-5"
    assert M._stable_option_key("noprefix") == "noprefix"


def test_order_key_is_stable_across_rounds():
    # Same item (idea-5) in two different round activities -> same order key.
    r1 = M._participant_order_key("M1", "u1", "ROUND1ACT:idea-5")
    r2 = M._participant_order_key("M1", "u1", "ROUND2ACT:idea-5")
    assert r1 == r2


def test_order_key_differs_by_item_and_user():
    a = M._participant_order_key("M1", "u1", "ACT:idea-5")
    b = M._participant_order_key("M1", "u1", "ACT:idea-6")
    c = M._participant_order_key("M1", "u2", "ACT:idea-5")
    assert a != b  # different items
    assert a != c  # different participants
