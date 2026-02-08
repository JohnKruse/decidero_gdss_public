# Fluent Emoji Attribution

This project vendors a curated subset of SVG assets from Microsoft Fluent Emoji.

- Source repository: https://github.com/microsoft/fluentui-emoji
- License: MIT (`third_party/fluent-emoji/LICENSE`)
- Included categories: `Animals & Nature`, `Food & Drink`, `Activities`
- Included style: `Color` SVG
- Local build script: `scripts/build_fluent_avatar_subset.py`

## Pinned Source

- Commit: 62ecdc0d7ca5c6df32148c169556bc8d3782fca4

## Update Workflow

1. Clone/update `microsoft/fluentui-emoji`.
2. Run `python3 scripts/build_fluent_avatar_subset.py --source-dir /path/to/fluentui-emoji`.
3. Review `app/static/avatars/fluent/manifest.json` and generated icons.
4. Keep this attribution file and license in sync.
