#!/usr/bin/env python3
"""Extract a human-readable Meeting Designer report from meeting_designer_logs.

Outputs:
- Conversation back-and-forth transcript (from request_messages)
- AI feedback signals from assistant turns
- Human-readable outline of the final generated agenda JSON
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


BIAS_TERMS = [
    "groupthink",
    "abilene",
    "hippo",
    "production blocking",
    "hidden profile",
    "evaluation apprehension",
    "status",
    "social desirability",
    "power dynamic",
]

PROMPT_SIGNALS: Sequence[Tuple[str, Sequence[str]]] = [
    ("meeting_goal", ("goal", "purpose", "outcome", "decision")),
    ("session_name", ("session name", "call this session", "what would you like to call")),
    ("group_composition", ("who will be", "how many", "roles", "expertise")),
    ("power_dynamics", ("power dynamic", "senior leader", "self-censor", "decision-maker")),
    ("constraints", ("duration", "time", "constraints", "tech comfort")),
    ("evaluation_criteria", ("evaluation criteria", "criteria", "feasibility", "cost", "risk")),
    ("complexity_recommendation", ("simple", "multi-phase", "multi-track", "decomposition pattern")),
    ("ready_to_generate", ("generate agenda", "click the", "ready")),
]


@dataclass
class LogRow:
    log_id: str
    event_type: str
    user_login: str
    created_at: str
    status_code: Optional[int]
    request_messages: Any
    new_message: Optional[str]
    assistant_response: Optional[str]
    raw_output: Optional[str]
    parsed_output: Any
    error_detail: Optional[str]
    provider: Optional[str]
    model: Optional[str]


def _parse_json_field(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return fallback
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return fallback
    return fallback


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_generate_row(
    conn: sqlite3.Connection,
    *,
    log_id: Optional[str],
    user_login: Optional[str],
) -> LogRow:
    if log_id:
        row = conn.execute(
            """
            SELECT *
            FROM meeting_designer_logs
            WHERE log_id = ?
            """,
            (log_id,),
        ).fetchone()
        if row is None:
            raise SystemExit(f"No log row found for log_id={log_id}")
    else:
        if user_login:
            row = conn.execute(
                """
                SELECT *
                FROM meeting_designer_logs
                WHERE event_type = 'generate_agenda'
                  AND status_code = 200
                  AND user_login = ?
                ORDER BY created_at DESC, log_id DESC
                LIMIT 1
                """,
                (user_login,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT *
                FROM meeting_designer_logs
                WHERE event_type = 'generate_agenda'
                  AND status_code = 200
                ORDER BY created_at DESC, log_id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            scope = f" for user_login={user_login}" if user_login else ""
            raise SystemExit(f"No successful generate_agenda row found{scope}.")

    return LogRow(
        log_id=row["log_id"],
        event_type=row["event_type"],
        user_login=row["user_login"],
        created_at=row["created_at"],
        status_code=row["status_code"],
        request_messages=row["request_messages"],
        new_message=row["new_message"],
        assistant_response=row["assistant_response"],
        raw_output=row["raw_output"],
        parsed_output=row["parsed_output"],
        error_detail=row["error_detail"],
        provider=row["provider"],
        model=row["model"],
    )


def _message_text(msg: Dict[str, Any]) -> str:
    content = msg.get("content")
    return content if isinstance(content, str) else ""


def _messages_from_generate_row(row: LogRow) -> List[Dict[str, str]]:
    data = _parse_json_field(row.request_messages, [])
    messages: List[Dict[str, str]] = []
    if not isinstance(data, list):
        return messages
    for item in data:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and isinstance(content, str):
            messages.append({"role": role, "content": content})
    return messages


def _assistant_feedback(messages: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    assistant_turns = [m["content"] for m in messages if m.get("role") == "assistant"]
    joined = "\n".join(assistant_turns).lower()

    signal_hits: Dict[str, int] = {}
    for label, keywords in PROMPT_SIGNALS:
        signal_hits[label] = sum(1 for kw in keywords if kw in joined)

    bias_mentions = sorted({term for term in BIAS_TERMS if term in joined})

    questions: List[str] = []
    for turn in assistant_turns:
        for line in turn.splitlines():
            stripped = line.strip()
            if "?" in stripped:
                questions.append(stripped)

    return {
        "assistant_turn_count": len(assistant_turns),
        "question_count": len(questions),
        "question_samples": questions[:12],
        "signal_hits": signal_hits,
        "bias_mentions": bias_mentions,
    }


def _extract_agenda_payload(row: LogRow) -> Dict[str, Any]:
    parsed = _parse_json_field(row.parsed_output, {})
    if isinstance(parsed, dict) and parsed:
        return parsed

    raw = row.raw_output or ""
    raw = raw.strip()
    if not raw:
        return {}

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or start > end:
        return {}
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _phase_map(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    phases = payload.get("phases")
    if not isinstance(phases, list):
        return {}
    result: Dict[str, Dict[str, Any]] = {}
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        phase_id = phase.get("phase_id")
        if isinstance(phase_id, str) and phase_id:
            result[phase_id] = phase
    return result


def _activity_lines(item: Dict[str, Any], indent: str, idx: int) -> List[str]:
    title = str(item.get("title") or "Untitled")
    tool = str(item.get("tool_type") or "")
    mins = item.get("duration_minutes")
    duration = f"{mins}m" if isinstance(mins, int) else "?m"
    collab = str(item.get("collaboration_pattern") or "")

    lines = [f"{indent}- {idx}. [{tool}] {title} ({duration}) | {collab}"]

    instructions = str(item.get("instructions") or "").strip().replace("\n", " ")
    rationale = str(item.get("rationale") or "").strip().replace("\n", " ")
    if instructions:
        lines.append(
            f"{indent}  - instructions: "
            f"{instructions[:260]}{'...' if len(instructions) > 260 else ''}"
        )
    if rationale:
        lines.append(
            f"{indent}  - rationale: {rationale[:220]}{'...' if len(rationale) > 220 else ''}"
        )
    return lines


def _outline_lines(payload: Dict[str, Any]) -> List[str]:
    """Render a human-readable outline from an agenda payload. Produces a hierarchical tree (phase -> track -> activity) for multi-phase agendas with parallel tracks, or a flat activity list for simple agendas. Returns a list of formatted strings."""
    lines: List[str] = []

    meeting_summary = payload.get("meeting_summary", "")
    session_name = payload.get("session_name", "")
    complexity = payload.get("complexity", "simple")
    eval_criteria = payload.get("evaluation_criteria", [])

    lines.append(f"- Session name: {session_name or '(not provided)'}")
    lines.append(f"- Complexity: {complexity}")
    if isinstance(eval_criteria, list) and eval_criteria:
        criteria = ", ".join(str(x) for x in eval_criteria)
    else:
        criteria = "(none)"
    lines.append(f"- Evaluation criteria: {criteria}")
    if isinstance(meeting_summary, str) and meeting_summary.strip():
        lines.append(f"- Meeting summary: {meeting_summary.strip()}")

    phases = payload.get("phases")
    agenda = payload.get("agenda")
    if isinstance(phases, list) and phases and isinstance(agenda, list) and agenda:
        lines.append("\nAgenda tree (phase -> track -> activity):")

        # Keep original agenda order for stable, human-readable sequencing.
        indexed_agenda: List[Tuple[int, Dict[str, Any]]] = []
        for idx, item in enumerate(agenda, start=1):
            if isinstance(item, dict):
                indexed_agenda.append((idx, item))

        for phase_idx, phase in enumerate(phases, start=1):
            if not isinstance(phase, dict):
                continue
            title = str(phase.get("title") or "Untitled phase")
            phase_id = str(phase.get("phase_id") or "")
            phase_type = str(phase.get("phase_type") or "plenary")
            mins = phase.get("suggested_duration_minutes")
            duration = f" ({mins}m)" if isinstance(mins, int) and mins > 0 else ""
            phase_key = phase_id or f"phase_{phase_idx}"
            lines.append(f"- Phase {phase_idx}: {title} [{phase_type}] ({phase_key}){duration}")

            phase_items = [
                (idx, item)
                for idx, item in indexed_agenda
                if str(item.get("phase_id") or "") == phase_id
            ]

            if phase_type == "parallel":
                tracks = phase.get("tracks")
                track_list = tracks if isinstance(tracks, list) else []

                for track in track_list:
                    if not isinstance(track, dict):
                        continue
                    track_id = str(track.get("track_id") or "")
                    track_label = str(track.get("label") or track_id or "Unnamed track")
                    subset = str(track.get("participant_subset") or "").strip()
                    track_hdr = f"  - Track: {track_label} ({track_id or 'no_id'})"
                    if subset:
                        track_hdr += f" | participants: {subset}"
                    lines.append(track_hdr)

                    track_items = [
                        (idx, item)
                        for idx, item in phase_items
                        if str(item.get("track_id") or "") == track_id
                    ]
                    if not track_items:
                        lines.append("    - (no activities listed for this track)")
                        continue
                    for idx, item in track_items:
                        lines.extend(_activity_lines(item, "    ", idx))

                # Catch activities in this phase with unknown/missing track_id
                known_track_ids = {
                    str(t.get("track_id") or "")
                    for t in track_list
                    if isinstance(t, dict)
                }
                unassigned = [
                    (idx, item)
                    for idx, item in phase_items
                    if str(item.get("track_id") or "") not in known_track_ids
                ]
                if unassigned:
                    lines.append("  - Unassigned/unknown track activities:")
                    for idx, item in unassigned:
                        lines.extend(_activity_lines(item, "    ", idx))
            else:
                plenary_items = [
                    (idx, item)
                    for idx, item in phase_items
                    if not str(item.get("track_id") or "")
                ]
                if not plenary_items and phase_items:
                    plenary_items = phase_items
                if not plenary_items:
                    lines.append("  - (no activities listed for this phase)")
                for idx, item in plenary_items:
                    lines.extend(_activity_lines(item, "  ", idx))
    elif isinstance(agenda, list) and agenda:
        lines.append("\nAgenda activities:")
        for idx, item in enumerate(agenda, start=1):
            if not isinstance(item, dict):
                continue
            lines.extend(_activity_lines(item, "", idx))

    return lines


def _fetch_recent_chat_turns(
    conn: sqlite3.Connection,
    *,
    user_login: str,
    generated_at: str,
    window_hours: int,
) -> List[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT log_id, created_at, new_message, assistant_response, status_code
        FROM meeting_designer_logs
        WHERE event_type = 'chat_turn'
          AND user_login = ?
          AND created_at <= ?
          AND created_at >= datetime(?, ?)
        ORDER BY created_at ASC, log_id ASC
        """,
        (user_login, generated_at, generated_at, f"-{window_hours} hours"),
    ).fetchall()
    return list(rows)


def _render_report(
    row: LogRow,
    transcript_messages: Sequence[Dict[str, str]],
    feedback: Dict[str, Any],
    payload: Dict[str, Any],
    recent_chat_rows: Sequence[sqlite3.Row],
) -> str:
    lines: List[str] = []
    lines.append("# AI Meeting Designer Report")
    lines.append("")
    lines.append("## Metadata")
    lines.append(f"- Generated log_id: `{row.log_id}`")
    lines.append(f"- Timestamp: `{row.created_at}`")
    lines.append(f"- User login: `{row.user_login}`")
    lines.append(f"- Provider/model: `{row.provider or ''}` / `{row.model or ''}`")
    lines.append(f"- Status code: `{row.status_code}`")
    lines.append("")

    lines.append("## Conversation Back-and-Forth")
    if not transcript_messages:
        lines.append("- No request_messages payload found on this generation row.")
    else:
        lines.append(f"- Total turns: `{len(transcript_messages)}`")
        lines.append("")
        for idx, msg in enumerate(transcript_messages, start=1):
            role = msg.get("role", "unknown")
            content = msg.get("content", "").strip()
            lines.append(f"### Turn {idx} ({role})")
            lines.append(content if content else "(empty)")
            lines.append("")

    lines.append("## AI Feedback Signals")
    lines.append(f"- Assistant turns: `{feedback['assistant_turn_count']}`")
    lines.append(f"- Questions asked by AI: `{feedback['question_count']}`")
    bias_text = ", ".join(feedback["bias_mentions"]) if feedback["bias_mentions"] else "(none detected)"
    lines.append(f"- Bias terms mentioned: {bias_text}")
    lines.append("- Coverage signals (keyword hits in AI turns):")
    for key, value in feedback["signal_hits"].items():
        lines.append(f"  - {key}: {value}")
    if feedback["question_samples"]:
        lines.append("- Sample AI questions:")
        for q in feedback["question_samples"]:
            lines.append(f"  - {q}")
    lines.append("")

    lines.append("## Final Agenda (Human-Readable)")
    if not payload:
        lines.append("- No parsed agenda payload found.")
    else:
        lines.extend(_outline_lines(payload))
    lines.append("")

    lines.append("## Recent Chat-Turn Timeline")
    if not recent_chat_rows:
        lines.append("- No recent chat_turn rows found in the selected window.")
    else:
        for r in recent_chat_rows:
            user_msg = (r["new_message"] or "").strip().replace("\n", " ")
            ai_msg = (r["assistant_response"] or "").strip().replace("\n", " ")
            lines.append(
                f"- `{r['created_at']}` chat_turn `{r['log_id']}` status={r['status_code']} "
                f"| user: {user_msg[:120]}{'...' if len(user_msg) > 120 else ''} "
                f"| ai: {ai_msg[:120]}{'...' if len(ai_msg) > 120 else ''}"
            )
    lines.append("")

    lines.append("## Suggested Additional Design Report Fields")
    lines.append("- Design assumptions explicitly captured by AI (constraints, risks, unknowns).")
    lines.append("- Rationale trace per activity: which facilitator input caused this activity to appear.")
    lines.append("- Bias-mitigation map: activity -> targeted bias risk.")
    lines.append("- Time budget summary: planned minutes by phase, by collaboration pattern, and by plenary vs breakout.")
    lines.append("- Confidence flags: where AI inferred missing info vs where facilitator provided explicit guidance.")
    lines.append("- Readiness checklist before generation (goal, group, constraints, criteria, complexity decision).")
    lines.append("- Delta from prior generated agenda (if iterative redesigns are common).")
    lines.append("")

    return "\n".join(lines)


def _default_output_path(output_dir: Path, row: LogRow) -> Path:
    stamp = row.created_at.replace(" ", "T").replace(":", "-")
    filename = f"meeting_designer_report_{stamp}_{row.log_id[:8]}.md"
    return output_dir / filename


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="decidero.db", help="Path to SQLite database")
    parser.add_argument("--log-id", default=None, help="Specific generate_agenda log_id")
    parser.add_argument("--user-login", default=None, help="Filter latest successful generate_agenda by user login")
    parser.add_argument("--window-hours", type=int, default=8, help="Window for recent chat_turn timeline")
    parser.add_argument("--output", default=None, help="Output markdown file path")
    parser.add_argument("--output-dir", default="reports/meeting_designer", help="Directory for auto-named output")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        raise SystemExit(f"Database file not found: {db_path}")

    with _connect(db_path) as conn:
        row = _fetch_generate_row(conn, log_id=args.log_id, user_login=args.user_login)
        transcript_messages = _messages_from_generate_row(row)
        feedback = _assistant_feedback(transcript_messages)
        payload = _extract_agenda_payload(row)
        recent_chat_rows = _fetch_recent_chat_turns(
            conn,
            user_login=row.user_login,
            generated_at=row.created_at,
            window_hours=max(1, args.window_hours),
        )

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else _default_output_path(Path(args.output_dir).expanduser().resolve(), row)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report_text = _render_report(row, transcript_messages, feedback, payload, recent_chat_rows)
    output_path.write_text(report_text, encoding="utf-8")

    print(f"Wrote report: {output_path}")
    print(f"Source log_id: {row.log_id} ({row.created_at})")


if __name__ == "__main__":
    main()
