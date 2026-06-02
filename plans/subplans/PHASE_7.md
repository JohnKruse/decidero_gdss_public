# PHASE 7 - Meeting Templates, Paper Alignment, and Pilot Hardening

**Parent plan:** [plans/01_MASTER_PLAN.md](../01_MASTER_PLAN.md)
**Archived predecessor:** [plans/archive/orchestration_engine/01_MASTER_PLAN.md](../archive/orchestration_engine/01_MASTER_PLAN.md)
**User-testing guide:** [docs/USER_TESTING_GUIDE.md](../../docs/USER_TESTING_GUIDE.md)
**Paper outline:** [docs/HICSS_2027_DECIDERO_ORCHESTRATOR_PAPER_OUTLINE.md](../../docs/HICSS_2027_DECIDERO_ORCHESTRATOR_PAPER_OUTLINE.md)

**Phase objective:** Add a low-training, user-facing template path for prebuilt
and saved meeting designs, then use that path in pilot testing. The work is
primarily product flow and operational hardening, but it must now also support
the HICSS paper argument: activity contracts make custom activities fieldable,
orchestration composes activities into reusable complex methods, AI and
facilitator decisions support flow control, and templates expose those methods
to facilitators without requiring them to understand orchestration internals.

Delphi is the reference method for this argument. It should be surfaced as an
orchestration-backed built-in template, not as a hand-authored Delphi-like
agenda scaffold.

An orchestration-backed template is not a fixed agenda. It is a planned method
outline with runtime gates. The facilitator should be able to see the intended
flow, the control points, the possible next steps, and the hard bounds, but the
system should not pre-fill future agenda rows that may never be materialized.

**Core product model:**

- **Start from Template** creates a fresh meeting from reusable design structure.
- **Design with AI** generates a fresh meeting design from conversation.
- **Design Yourself** starts from a blank manual creator.
- **Import Meeting** restores or reviews an existing meeting archive and remains a separate operation.
- **Activity Library** explains individual activities and remains distinct from meeting templates.

**Paper-driven implementation chain:**

1. Activity contract and harness.
2. Orchestration layer and flow controls.
3. Reference method, currently Classical Delphi.
4. Template UX and CRUD/reuse.
5. Pilot evidence about facilitator comprehension and lowered training burden.

## Phase Canary

**Copper Compass**

Use this exact two-word canary in Phase 7 notes, UI tests, template fixtures, pilot reports, and commits tied to this phase.

## User Flow

### Dashboard Entry

Replace the three peer buttons inside the current "Create a Meeting" group with a single **Create Meeting** control that opens a short choice surface:

1. **Start from Template**
2. **Design with AI**
3. **Design Yourself**

Keep **Import Meeting** as its own button beside the create control. Import is distinct because it may restore data/history from a prior meeting rather than creating a clean session from reusable design.

### Template Landing Page

`Start from Template` opens a **Meeting Templates** page. The page should be usable with no training:

- Search/filter if the template count justifies it; otherwise keep the first version simple.
- Show **Built-in Templates** and **Custom Templates** as separate sections.
- Each card shows template name, one-line purpose, estimated duration, group size, tags, and whether it is linear or multi-round.
- Orchestration-backed cards show that they are packaged methods, including citation/version metadata where practical.
- Orchestration-backed cards show a method outline and runtime gates, not a pretend final agenda.
- Details should be lightweight: tooltip, popover, or expandable card content. Avoid forcing users through a separate preview page for v1.
- The primary action on each card is **Start from Template**.

### Configure/Create Flow

Starting from a template opens a meeting-creation flow prefilled from the template. This is not a separate "configure" product; it is the normal creation path with template defaults.

Required fields:

- Meeting title.
- Schedule, if known.
- Participants.
- Meeting description or topic/problem statement.

Template-specific fields should appear only when they materially affect the meeting. For Classical Delphi, likely candidates are:

- Problem statement.
- Maximum rounds.
- Convergence threshold, if exposed.
- AI summary/review option, if enabled in the shipped template.

For Classical Delphi, the creation flow should use the packaged orchestration
document as the source of method structure. If the bridge from templates to
orchestration-backed meetings is not complete, the UI should say so rather than
presenting a manually invented Delphi agenda.

The creation flow for an orchestration-backed method should collect meeting
details and method parameters, then bind the meeting to the orchestration
document. It should show a planned method outline, but it should not expose the
ordinary agenda editor as if the full final activity list were known.

For facilitator experience, the orchestration-backed start page should ask only
simple launch questions such as session name, group question/problem statement,
and start time. It should set the next expectation plainly: Decidero creates
the first activity now, and later rounds or stop/continue choices appear only
when the orchestration reaches those gates.

The final action remains **Create Meeting**.

### Save as Template

Existing meeting pages or meeting settings should expose **Save as Template** for users with facilitator/admin authority. The action extracts reusable design structure from the meeting and strips runtime data.

Save:

- Meeting title as a default template name.
- Meeting description as default context.
- Agenda activity order.
- Activity types.
- Activity titles.
- Instructions.
- Durations.
- Configuration defaults.
- Orchestration/template metadata when present.

Do not save by default:

- Submitted ideas.
- Votes.
- Rankings.
- Categorization state.
- Participant responses.
- Activity output bundles.
- Runtime active/closed status.
- Timers.
- Meeting state snapshots.
- Participant list.

Participant list may become an explicit opt-in later, but it should not be part of v1 unless a pilot proves it is needed.

### Template Management

Built-in templates are read-only and versioned. Custom templates should support:

- Rename.
- Edit high-level metadata.
- Archive/disable.
- Delete or hide, depending on data-retention preference.
- Start a new meeting.

Full graphical editing of template internals is not required for v1. The first useful editing loop is: start from a template, adjust the meeting in the normal creator/settings UI, then save the adjusted meeting as a new template.

## Atomic Steps

### Step 1 — [DONE] Dashboard Creation IA and Copy

Rework the dashboard creation controls around the user-facing creation model. The button set must make the distinction between template, AI design, manual design, and import obvious without training.

Conclude this step by:

- Implementing the **Create Meeting** choice surface with `Start from Template`, `Design with AI`, and `Design Yourself`.
- Keeping **Import Meeting** visible as a separate operation.
- Updating frontend smoke tests for the new dashboard affordances.
- Updating user-testing documentation so observers know what users are expected to understand from the dashboard alone.

Technical deviations:
- `Start from Template` points to `/meeting/templates`, the route owned by Step 3. Step 1 intentionally implements the dashboard information architecture and copy before the landing page exists, so user-facing template instantiation remains incomplete until Step 3 and Step 4.

### Step 2 — [DONE] Template Contract and Storage

Define the persisted meeting-template contract. The contract must support built-in templates, custom templates saved from meetings, and future orchestration-backed templates without mixing template data with meeting runtime data.

Conclude this step by:

- Creating the template schema/model/service layer chosen for the codebase.
- Defining the runtime-data stripping rules in tests.
- Recording the built-in/custom permission model.
- Documenting the contract in a new or existing docs file.

Technical deviations:
- None.

### Step 3 — Meeting Templates Landing Page

Build the `Start from Template` destination. The page should list built-in and custom templates with enough information to choose quickly.

Conclude this step by:

- Creating the Meeting Templates page and route.
- Listing Classical Delphi as a built-in template only if its packaged orchestration representation can be instantiated safely; otherwise listing it as unavailable with an explicit product-gap note is acceptable for the first iteration.
- Removing any hardcoded Delphi-like agenda payload that is not grounded in the packaged orchestration or clearly labeling it as a temporary scaffold outside the Classical Delphi built-in.
- Showing the Classical Delphi planned method outline and runtime gates from template/orchestration metadata.
- Adding card-level details through tooltip, popover, or expandable content rather than a mandatory preview page.
- Adding route/page tests and frontend smoke coverage.

### Step 4 — Start from Template to Create Meeting

Implement the clean meeting instantiation path from a selected template. This step owns the configure/create flow: meeting details are collected, template defaults are applied, and a fresh meeting is created without carrying old runtime data.

Conclude this step by:

- Adding the API/service path that turns an ordinary agenda template into meeting agenda payloads.
- Adding the API/service path that turns an orchestration-backed template into a meeting bound to the packaged orchestration document.
- Prefilling the normal meeting creator or a template-specific create form.
- Using a template-specific guided start page for orchestration-backed methods so facilitators are not asked to edit a fictional final agenda.
- Creating a fresh meeting with title, schedule, participants, agenda, and allowed template parameters.
- Proving that the Classical Delphi template uses the packaged Delphi orchestration rather than a separate hand-authored agenda.
- Proving that orchestration-backed creation does not pre-create future dynamic agenda rows beyond what the engine materializes.
- Adding tests proving no template-created meeting contains stale runtime data.

### Step 5 — Save Existing Meeting as Template

Add the reuse path for successful meetings. A facilitator should be able to say: "That worked well; save this structure for next time."

Conclude this step by:

- Adding **Save as Template** from the meeting page or meeting settings.
- Extracting only reusable structure from the meeting.
- Stripping ideas, votes, rankings, categories, output bundles, runtime state, timers, and participant responses.
- Adding regression coverage for the extraction boundary.
- Updating documentation and pilot scripts to include this flow.

### Step 6 — Template Management and Pilot Validation

Round out the v1 management surface and test it with users. This step is where implementation meets the Phase 7 pilot guide.

Conclude this step by:

- Supporting custom template rename/start/archive/delete or the chosen minimum management set.
- Running the agreed regression command to `[100%]`.
- Updating [docs/USER_TESTING_GUIDE.md](../../docs/USER_TESTING_GUIDE.md) with the final template workflow.
- Recording pilot findings about whether users understood `Start from Template`, `Design with AI`, `Design Yourself`, and `Import Meeting` without explanation.
- Recording pilot findings against the paper claims: whether templates make reusable methods understandable, whether AI/facilitator decision support lowers the facilitation burden, and whether ordinary agenda templates remain distinct from orchestration-backed methods.

## Phase Exit Criteria

Phase 7 clears only when:

- The dashboard creation choices reflect the final vocabulary: `Start from Template`, `Design with AI`, and `Design Yourself`.
- `Import Meeting` remains visible and conceptually separate from template creation.
- Users can start a fresh meeting from at least one built-in or custom template.
- The built-in Classical Delphi path is orchestration-backed, or it is explicitly unavailable pending orchestration-template wiring.
- Orchestration-backed templates display planned method outlines and runtime gates instead of fixed final agendas.
- Users can save an existing meeting as a custom template without carrying runtime data.
- Template management covers the v1 lifecycle for custom templates.
- Documentation explains the product distinction between templates, AI-designed meetings, manual meetings, and imports.
- Documentation explains the research distinction between ordinary agenda templates and orchestration-backed method templates.
- The agreed regression command reaches `[100%]`.
- A pilot or internal dry-run records user-flow findings against the template path.
- The HICSS outline has been reviewed and updated so the final implementation state, evidence state, and paper claims agree.

## Scope Boundary

This phase does not cover:

- Publication-grade empirical evaluation.
- New orchestration grammar features.
- In-place editing of built-in templates.
- Full visual workflow editing for template internals.
- Importing a meeting ZIP directly as a template unless separately authorized.
- Saving participant contributions or runtime meeting state into templates.
- Major dashboard redesign beyond the creation controls needed for the new flow.
