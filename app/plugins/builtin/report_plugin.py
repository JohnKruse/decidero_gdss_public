"""Report activity: a generic, consume-and-synthesize terminal deliverable.

Canary: Plainspoken Marmot

Unlike most activities, `report` takes no participant input. When it opens it reads
the upstream round history (Convergent Yak: `strategy.round_history`) and builds the
canonical report model (`report_builder.build_report`,
`docs/schemas/report_payload.schema.json`), finalizing it as the activity's output
bundle. Renderers (`report_renderers`) and the download endpoints derive every
format from that stored model — never recomputed.

Method-agnostic: the consensus shaping lives in the metrics/summarizer registries
and Layer-2 config, not here. For a linear (non-orchestrated) meeting it falls back
to the single input bundle as a one-"round" history.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.plugins.base import ActivityPlugin, ActivityPluginManifest


class ReportPlugin(ActivityPlugin):
    manifest = ActivityPluginManifest(
        tool_type="report",
        label="Report",
        description=(
            "Synthesize the meeting's results into a downloadable report "
            "(JSON, Markdown, DOCX, CSV) — final outcome plus the path to it."
        ),
        default_config={},
        collaboration_patterns=["Evaluate"],
        when_to_use="As a terminal step to produce a shareable deliverable.",
        when_not_to_use="Mid-method, when no results exist to synthesize yet.",
        input_requirements=(
            "Consumes prior activities' output bundles (a method's round history, "
            "or the immediately-prior bundle); no participant input."
        ),
        output_characteristics=(
            "A canonical report model (final outcome + per-round movement and "
            "consensus stats) rendered to JSON, Markdown, DOCX, and CSV."
        ),
        group_size_range={"min": 1, "max": 1000},
        typical_duration_minutes={"min": 1, "max": 10},
    )

    def open_activity(self, context, input_bundle=None) -> None:
        # Build once on open so the report is ready to view/download immediately.
        if context._bundle_manager().get_latest_bundle(
            context.meeting.meeting_id, context.activity.activity_id, "output"
        ):
            return None
        self._finalize_report(context, input_bundle)
        return None

    def close_activity(self, context) -> Optional[Dict[str, Any]]:
        bundle = context._bundle_manager().get_latest_bundle(
            context.meeting.meeting_id, context.activity.activity_id, "output"
        )
        if bundle is None:
            bundle = self._finalize_report(context, context.load_input_bundle())
        return {"bundle_id": bundle.bundle_id, "items": bundle.items}

    # ------------------------------------------------------------------ #
    def _finalize_report(self, context, input_bundle):
        report = self._build_report_payload(context, input_bundle)
        items = self._headline_items(report)
        return context.finalize_output_bundle(
            items,
            metadata={"report": True, "report_payload": report},
        )

    @staticmethod
    def _headline_items(report: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Mirror the final ranked list as bundle items (export-meaningful)."""
        for sec in report.get("sections") or []:
            if sec.get("type") == "ranked_list":
                return [
                    {
                        "content": it.get("label"),
                        "metadata": {"rank": it.get("rank"), **(it.get("stats") or {})},
                        "source": {"activity_id": ""},
                    }
                    for it in (sec.get("body") or {}).get("items") or []
                ]
        return []

    def _build_report_payload(self, context, input_bundle) -> Dict[str, Any]:
        from app.services.agenda_strategy import get_agenda_strategy
        from app.services.report_builder import build_report
        from app.models.facilitator_edit import FacilitatorEditEvent

        meeting, db = context.meeting, context.db
        strategy = get_agenda_strategy(meeting)

        history: List[Dict[str, Any]] = []
        round_history = getattr(strategy, "round_history", None)
        if callable(round_history):
            history = round_history(meeting, db) or []
        if not history and input_bundle is not None:
            history = [
                {
                    "items": list(input_bundle.items or []),
                    "metadata": dict(input_bundle.bundle_metadata or {}),
                }
            ]

        meeting_meta = {
            "meeting_id": meeting.meeting_id,
            "title": getattr(meeting, "title", None),
            "description": getattr(meeting, "description", None),
            "method": self._method_meta(strategy),
            "participant_count": self._participant_count(history),
        }
        edit_events = (
            db.query(FacilitatorEditEvent)
            .filter(FacilitatorEditEvent.meeting_id == meeting.meeting_id)
            .order_by(FacilitatorEditEvent.created_at.desc())
            .all()
        )
        if edit_events:
            n = len(edit_events)
            m = len({e.activity_id for e in edit_events if e.activity_id})
            last_created = edit_events[0].created_at
            last_at = last_created.isoformat() if last_created else None
            meeting_meta["facilitator_edits"] = {
                "count": n,
                "activity_count": m,
                "last_at": last_at,
            }
        spec = dict((context.activity.config or {}).get("report_spec") or {})

        if not history:
            # No upstream rounds: emit a minimal, valid report rather than fail.
            return {
                "report_version": "1.0",
                "title": meeting_meta["title"] or "Meeting Report",
                "meeting": {
                    "meeting_id": meeting.meeting_id,
                    "title": meeting_meta["title"] or "",
                    "method": meeting_meta["method"],
                    "round_count": 0,
                },
                "generated_at": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
                "sections": [
                    {
                        "id": "overview",
                        "type": "narrative",
                        "title": "Overview",
                        "body": {"markdown": "No results were available to report.",
                                 "ai_drafted": False},
                    }
                ],
            }
        return build_report(history, meeting_meta, spec)

    @staticmethod
    def _method_meta(strategy) -> Optional[Dict[str, Any]]:
        doc = getattr(strategy, "_document", None)
        if doc is None:
            return None
        return {
            "name": getattr(doc, "name", None),
            "version": getattr(doc, "version", None),
            "citation": getattr(doc, "citation", None),
        }

    @staticmethod
    def _participant_count(history: List[Dict[str, Any]]) -> Optional[int]:
        if not history:
            return None
        votes = (history[-1].get("metadata") or {}).get("votes") or []
        users = {v.get("user_id") for v in votes if v.get("user_id")}
        return len(users) or None


PLUGIN = ReportPlugin()
