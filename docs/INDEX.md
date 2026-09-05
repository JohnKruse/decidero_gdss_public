# Decidero Docs Index

Use this page as the entry point for all project docs.

## Hosting

1. Local setup (single machine): `docs/LOCAL_SETUP_GUIDE.md`
2. Admin/facilitator hosting modes: `docs/ADMIN_HOSTING_GUIDE.md`
3. Production server/domain setup: `docs/SERVER_HOSTING_GUIDE.md`
4. SQLite 100-concurrency reliability plan: `docs/RELIABILITY_100_CONCURRENCY_PLAN.md`
5. Reliability rehearsal report template: `docs/RELIABILITY_REHEARSAL_REPORT_TEMPLATE.md`

The operator-specific local/VPS load-testing plan is intentionally not tracked in
the public repository. The k6 scenarios themselves remain at the repository root.

## Runtime Configuration

1. Admin/Facilitator Settings page reference: `docs/SETTINGS_GUIDE.md`
   - What can be changed via the UI vs. config.yaml
   - AI provider setup (Anthropic, OpenAI, Azure, OpenRouter, Ollama)
   - Role permissions per settings section
   - API key encryption and security model
   - How DB overrides interact with config.yaml defaults

## Frontend & Template Development

If you are adding new pages, UI components, or modifying the navigation, start here.

1. Frontend and template conventions: `docs/FRONTEND_DEV_GUIDE.md`
   - How to add a new page (template + route + CSS + JS)
   - Header protection model — why it never disappears
   - Role system and how to check roles safely in Python and Jinja2
   - Quick Actions dashboard pattern for new tools
   - CSS design system and layout primitives
   - Common mistakes to avoid

## Activity Development (Critical Path)

If you are new to activity development, start with the first link below. It explains the mental model in plain language before the technical details.

1. Activity contract specification: `docs/ACTIVITY_CONTRACT_SPEC.md`
2. Activity implementation guide: `docs/ACTIVITY_CONTRACT_GUIDE.md`
3. Plugin implementation guide: `docs/PLUGIN_DEV_GUIDE.md`
4. Categorization contract: `docs/CATEGORIZATION_CONTRACT.md`
5. Transfer metadata contract: `docs/TRANSFER_METADATA.md`
6. Built-in ThinkLet audit: `docs/THINKLET_AUDIT.md`

## Activity Specs

1. Categorization production spec: `docs/CATEGORIZATION_ACTIVITY_SPEC.md`
2. Meeting template contract: `docs/MEETING_TEMPLATE_CONTRACT.md`

## Reference Evaluations

1. Delphi synthetic validation: `docs/DELPHI_VALIDATION.md`
2. Classical Delphi demonstration: `docs/delphi.md`

## Other References

1. Avatar pipeline: `docs/AVATAR_PIPELINE.md`
2. GitHub handoff: `docs/github/GITHUB_HANDOFF.md`
3. Legacy VPS redirect note: `docs/VPS_HOSTING_GUIDE.md`
4. Phase 6 validation checklist: `docs/PHASE_6_VALIDATION_CHECKLIST.md`
5. User testing guide: `docs/USER_TESTING_GUIDE.md`
6. AI configuration refactor record: `docs/AI_CONFIG_REFACTOR_PLAN.md`
7. Copper Compass pilot findings: `docs/PILOT_FINDINGS_COPPER_COMPASS.md`
8. Orchestration figure sources: `docs/figures/README.md`
