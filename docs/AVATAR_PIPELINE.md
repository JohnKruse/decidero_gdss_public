# Avatar Pipeline (Fluent Emoji)

## Source and licensing
- Upstream: `https://github.com/microsoft/fluentui-emoji`
- License: MIT (`third_party/fluent-emoji/LICENSE`)
- Attribution: `third_party/fluent-emoji/README.md`

## Build/update assets
1. Clone or update the Fluent repo locally.
2. Run:
   - `python3 scripts/build_fluent_avatar_subset.py --source-dir /path/to/fluentui-emoji`
3. Review generated files:
   - `app/static/avatars/fluent/manifest.json`
   - `app/static/avatars/fluent/icons/*.svg`
4. Commit updated assets + attribution metadata.

## Assignment model
- Default avatar key is deterministic:
  - `avatar_key = hash(user_id + ":" + avatar_seed) % manifest_count`
- `avatar_seed` defaults to `0`.
- Profile action `Generate new avatar` increments `avatar_seed` and recomputes key.
- `avatar_color` remains deterministic and is used as the avatar background/fallback color.

## Collision simulation
Use:
- `./venv/bin/python scripts/simulate_avatar_collisions.py --sizes 50 100 200`

Observed with 240 curated avatars (seed `0`):
- `size=50 unique_keys=44 duplicate_users=6 duplicated_keys=6 max_users_on_single_key=2`
- `size=100 unique_keys=77 duplicate_users=23 duplicated_keys=22 max_users_on_single_key=3`
- `size=200 unique_keys=136 duplicate_users=64 duplicated_keys=49 max_users_on_single_key=4`

Interpretation:
- Collisions are expected in large cohorts.
- Participant differentiation relies on `avatar icon + color + display name`.
