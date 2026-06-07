"""Tests for the deterministic report builder + renderers (Plainspoken Marmot)."""

import csv
import io
import json

from app.services.report_builder import build_report
from app.services import report_renderers as rr


def _round_bundle(activity_id, votes_by_user):
    """Build a rank_order_voting-shaped output bundle.

    votes_by_user: {user_id: {option_label: rank_position}}
    """
    labels = sorted({lbl for v in votes_by_user.values() for lbl in v})
    items = [
        {
            "content": f"Idea {lbl}",
            "id": f"{activity_id}:{lbl}",
            "metadata": {"rank_order_voting": {"option_id": f"{activity_id}:{lbl}"}},
        }
        for lbl in labels
    ]
    votes = []
    for uid, ranks in votes_by_user.items():
        for lbl, pos in ranks.items():
            votes.append(
                {"option_id": f"{activity_id}:{lbl}", "user_id": uid, "rank_position": pos}
            )
    return {"items": items, "metadata": {"votes": votes}}


def _two_round_report():
    r1 = _round_bundle("act1", {
        "u1": {"A": 1, "B": 2, "C": 3},
        "u2": {"A": 1, "B": 3, "C": 2},
        "u3": {"A": 2, "B": 1, "C": 3},
    })
    r2 = _round_bundle("act2", {  # perfect agreement
        "u1": {"A": 1, "B": 2, "C": 3},
        "u2": {"A": 1, "B": 2, "C": 3},
        "u3": {"A": 1, "B": 2, "C": 3},
    })
    meeting = {"meeting_id": "m1", "title": "Test Delphi",
               "method": {"name": "Classical Delphi", "version": "1.0"},
               "participant_count": 3, "generated_at": "2026-06-07T00:00:00Z"}
    return build_report([r1, r2], meeting)


def test_build_report_structure():
    rep = _two_round_report()
    assert rep["report_version"] == "1.0"
    assert rep["meeting"]["round_count"] == 2
    by_type = {s["type"] for s in rep["sections"]}
    assert {"narrative", "key_value", "ranked_list", "table", "chart", "rounds"} <= by_type
    # three charts present
    assert sum(s["type"] == "chart" for s in rep["sections"]) == 3


def test_final_ranking_sorted_and_complete():
    rep = _two_round_report()
    rl = next(s for s in rep["sections"] if s["type"] == "ranked_list")
    items = rl["body"]["items"]
    assert [i["rank"] for i in items] == [1, 2, 3]
    assert items[0]["label"] == "Idea A"  # consensus winner
    assert items[0]["stats"]["agreement_band"] == "green"


def test_trajectory_table_no_truncation():
    rep = _two_round_report()
    tbl = next(s for s in rep["sections"] if s["id"] == "trajectory")
    rows = tbl["body"]["rows"]
    assert len(rows) == 3  # every item, no truncation
    keys = {c["key"] for c in tbl["body"]["columns"]}
    assert {"item", "r1", "r2", "delta", "median", "iqr", "band"} <= keys


def test_kendalls_w_rises_to_consensus():
    rep = _two_round_report()
    rounds = next(s for s in rep["sections"] if s["type"] == "rounds")["body"]["rounds"]
    w1 = rounds[0]["stats"]["kendalls_w"]
    w2 = rounds[1]["stats"]["kendalls_w"]
    assert w2 == 1.0 and w2 >= w1


def test_render_json_roundtrips():
    rep = _two_round_report()
    assert json.loads(rr.render_json(rep)) == rep


def test_render_markdown_includes_every_item():
    rep = _two_round_report()
    md = rr.render_markdown(rep)
    for label in ("Idea A", "Idea B", "Idea C"):
        assert label in md
    assert "Final Ranking" in md


def test_render_html_preview_escapes_and_may_elide_rows():
    rep = _two_round_report()
    rep["title"] = "<script>bad()</script>"
    html = rr.render_html(rep, max_rows=1)
    assert "&lt;script&gt;bad()&lt;/script&gt;" in html
    assert "<script>bad()</script>" not in html
    assert "Showing 1 of" in html
    assert "Download for the complete table." in html


def test_render_csv_primary_table_full_rows():
    rep = _two_round_report()
    text = rr.render_csv(rep)  # defaults to trajectory table
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows) == 1 + 3  # header + every item


def test_render_csv_files_covers_tabular_sections():
    rep = _two_round_report()
    files = rr.render_csv_files(rep)
    assert "trajectory" in files and "final_ranking" in files
    # chart series also exported as tables
    assert "convergence" in files


def test_render_chart_png_headless():
    rep = _two_round_report()
    chart = next(s for s in rep["sections"] if s["type"] == "chart")
    png = rr.render_chart_png(chart)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_docx_produces_document():
    rep = _two_round_report()
    data = rr.render_docx(rep)
    assert data[:2] == b"PK"  # docx is a zip
    assert len(data) > 1000
