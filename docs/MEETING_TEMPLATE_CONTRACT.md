# Meeting Template Contract

Phase 7 canary: **Copper Compass**

Meeting templates are reusable meeting designs. They are not meeting archives and they must not carry participant contributions, runtime state, or historical meeting data.

## Storage

Templates are stored in the `meeting_templates` table.

Core fields:

- `template_id`: stable template identifier.
- `source`: `built_in` or `custom`.
- `status`: `active` or `archived`.
- `name`, `purpose`, `description`: user-facing selection copy.
- `estimated_duration_minutes`, `min_participants`, `max_participants`: quick-choice metadata for the template landing page.
- `tags`: short labels used for filtering and scanning.
- `flow_type`: `linear`, `multi_round`, or `multi_track`.
- `template_version`: version of the template content.
- `built_in_key`: stable key for built-in templates.
- `created_by_user_id`: owner for custom templates.
- `contract_version`: currently `1`.
- `template_payload`: JSON contract payload.

## Payload

`template_payload` uses `schema_version: 1`.

Required shape:

```json
{
  "schema_version": 1,
  "defaults": {
    "title": "Default meeting title",
    "description": "Default meeting context"
  },
  "agenda": [
    {
      "tool_type": "brainstorming",
      "title": "Activity title",
      "instructions": "Prompt or instructions shown to participants",
      "order_index": 1,
      "duration_minutes": 10,
      "config": {}
    }
  ],
  "parameters": {},
  "orchestration": null,
  "metadata": {
    "phase_canary": "Copper Compass"
  }
}
```

The agenda stores reusable structure: activity order, activity type, titles,
participant-facing instructions, duration defaults, and configuration defaults.
For orchestration-backed templates, `orchestration` identifies the Layer-2 method
document; runtime orchestration metadata may also appear in activity config.

When a facilitator starts an orchestration-backed template, the start form requires
a new session name and a question for the group. These values are not silently
prefilled from the reusable template defaults. The group question becomes the
meeting description and is also supplied to the first brainstorming activity as
its participant-facing prompt.

## Runtime Stripping Boundary

Saving a meeting as a template extracts only reusable design structure.

Saved:

- Meeting title as a default template title.
- Meeting description as default context.
- Agenda activity order.
- Activity types.
- Activity titles.
- Instructions.
- Duration defaults discoverable from activity config.
- Activity configuration defaults.
- Orchestration metadata when present.

Not saved:

- Participant list.
- Submitted ideas.
- Votes.
- Rankings.
- Categorization items, buckets, assignments, ballots, or final state.
- Participant responses.
- Input, draft, or output bundles.
- Active/closed runtime status.
- Timers, started/stopped timestamps, elapsed time, or meeting state snapshots.

## Permission Model

Built-in templates are read-only and versioned by the application. Facilitators, admins, and super admins may start meetings from active built-in templates, but no user edits the built-in row through the v1 UI.

Custom templates are owned by `created_by_user_id`.

- The owner, admins, and super admins may edit, archive, or delete a custom template.
- Other facilitators may start from an active custom template when it is visible to them, but they do not edit or delete it.
- Participants do not start, edit, archive, or delete templates.

The first v1 editing loop is intentionally simple: start from a template, adjust the meeting in the normal creator/settings UI, then save that adjusted meeting as a new custom template.
