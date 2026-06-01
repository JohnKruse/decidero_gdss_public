# 01 — MASTER PLAN: Meeting Templates and Pilot-Ready Creation Flow

**Depends on:** Completed orchestration-engine plan archived at [plans/archive/orchestration_engine/01_MASTER_PLAN.md](archive/orchestration_engine/01_MASTER_PLAN.md)
**Primary subplan:** [plans/subplans/PHASE_7.md](subplans/PHASE_7.md)

**Target state:** Decidero gives facilitators a low-training path to create a meeting in the way they naturally think about the task:

1. **Start from Template** — choose a prebuilt or saved meeting design such as Classical Delphi and create a fresh meeting from it.
2. **Design with AI** — describe the situation and let the AI Meeting Designer draft a custom agenda.
3. **Design Yourself** — manually build a meeting from a blank agenda.
4. **Import Meeting** — load an existing meeting archive for review, recovery, or reuse of prior data.

The product distinction is deliberate: a **template** is reusable meeting structure without session data; an **imported meeting** is a prior meeting artifact that may carry data/history; the **AI Designer** creates a new design from conversation; and **manual design** starts from scratch.

## Global Canary

**Copper Compass**

Use this exact two-word canary in planning notes, UI tests, template fixtures, migration notes, pilot reports, and commits tied to this effort.

## User-Flow Principles

### UF1 — The Dashboard Must Teach the Model

The dashboard is the only reliable training surface. Users will not read architecture notes. The top-level controls must make the creation model self-evident:

- **Create Meeting** opens a small choice surface with `Start from Template`, `Design with AI`, and `Design Yourself`.
- **Import Meeting** remains separate because it is a restore/review operation, not a design path.
- **Activity Library** remains separate because activities are building blocks, not complete meeting designs.

### UF2 — Templates Are Designs, Not Meetings

Templates contain reusable structure only: title defaults, description defaults, agenda activities, activity instructions, durations, config defaults, orchestration references, tags, and template metadata. Templates do not contain votes, ideas, rankings, categorization state, runtime timers, active/closed state, or participant contributions.

### UF3 — Creation Is One Flow

Selecting a template, configuring meeting details, and creating the meeting are one user journey. Do not split "configure" and "create" into separate conceptual products. The user action is: **Start from Template**.

### UF4 — Built-Ins Are Read-Only

Built-in templates such as Classical Delphi are shipped, cited, versioned, and validated. They are not edited in place through the UI. If customization is needed, the user saves a custom template or starts from the built-in and adjusts the resulting meeting.

### UF5 — Reuse Comes from Real Meetings

The most valuable custom-template path is likely **Save as Template** from an existing meeting: "This worked well; use this approach again." This must strip runtime data and save only reusable structure.

## Strategic Phases

### Phase 7 — Meeting Templates and Pilot Hardening

Build the first product-grade template flow and use it to support pilot testing.

**Success Gate**

- Dashboard creation controls are reorganized around `Create Meeting` with choices for `Start from Template`, `Design with AI`, and `Design Yourself`, while `Import Meeting` stays separate.
- A Meeting Templates landing page exists and lists at least one built-in template: Classical Delphi.
- Starting from a template creates a fresh meeting through a clear configure/create flow with title, schedule, participants, and any required template parameters.
- Existing meetings can be saved as custom templates with runtime data stripped.
- Custom templates can be listed, started, renamed, disabled/archived, and deleted or hidden according to the chosen permission model.
- The first pilot protocol is updated to include the template flow, and at least one user-testing pass records whether facilitators understand the difference between templates, AI design, manual design, and import.

## Scope Boundary

This plan does not cover:

- A publication-grade empirical study.
- New orchestration grammar primitives.
- A visual redesign of the whole dashboard beyond the creation controls needed for template discoverability.
- Arbitrary drag-and-drop template editing beyond what is needed to save and reuse high-level meeting structure.
- Importing old meeting ZIPs as templates unless explicitly implemented as a separate extraction path.
- Making built-in templates editable in place.
