#!/usr/bin/env python3
"""Build a curated Fluent Emoji avatar subset and manifest."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import hashlib


DEFAULT_GROUPS = ("Animals & Nature", "Food & Drink", "Activities")
EXCLUDED_KEYWORDS = (
    "blood",
    "weapon",
    "coffin",
    "headstone",
    "zombie",
    "skull",
    "cigarette",
    "smoking",
)


@dataclass(frozen=True)
class Asset:
    key: str
    name: str
    category: str
    unicode: str | None
    glyph: str | None
    keywords: tuple[str, ...]
    source_svg: Path
    output_svg: Path


def _slug(value: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-"
    text = value.strip().lower().replace("_", "-").replace(" ", "-")
    collapsed = []
    last_dash = False
    for ch in text:
        if ch in allowed:
            collapsed.append(ch)
            last_dash = ch == "-"
            continue
        if not last_dash:
            collapsed.append("-")
            last_dash = True
    result = "".join(collapsed).strip("-")
    return result or "item"


def _repo_commit(source_root: Path) -> str | None:
    git_dir = source_root / ".git"
    if not git_dir.exists():
        return None
    try:
        out = subprocess.check_output(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or None
    except Exception:
        return None


def _safe_keywords(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return tuple()
    normalized = []
    for item in raw:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if cleaned:
            normalized.append(cleaned)
    return tuple(normalized)


def _asset_key(metadata: dict[str, Any], asset_name: str) -> str:
    unicode_value = metadata.get("unicode")
    if isinstance(unicode_value, str) and unicode_value.strip():
        return f"fluent-{_slug(unicode_value)}"
    cldr = metadata.get("cldr")
    if isinstance(cldr, str) and cldr.strip():
        return f"fluent-{_slug(cldr)}"
    digest = hashlib.sha1(asset_name.encode("utf-8")).hexdigest()[:12]
    return f"fluent-{digest}"


def collect_assets(
    source_root: Path,
    output_dir: Path,
    style: str,
    allowed_groups: tuple[str, ...],
) -> list[Asset]:
    assets_root = source_root / "assets"
    if not assets_root.exists():
        raise FileNotFoundError(f"Missing assets directory: {assets_root}")

    collected: list[Asset] = []
    for emoji_dir in sorted(assets_root.iterdir(), key=lambda p: p.name.lower()):
        if not emoji_dir.is_dir():
            continue
        metadata_path = emoji_dir / "metadata.json"
        if not metadata_path.exists():
            continue
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        group = str(metadata.get("group") or "").strip()
        if group not in allowed_groups:
            continue

        keywords = _safe_keywords(metadata.get("keywords"))
        keyword_blob = " ".join(k.lower() for k in keywords)
        if any(block in keyword_blob for block in EXCLUDED_KEYWORDS):
            continue

        style_dir = emoji_dir / style
        if not style_dir.exists():
            continue
        svg_files = sorted(style_dir.glob("*.svg"))
        if not svg_files:
            continue

        key = _asset_key(metadata, emoji_dir.name)
        unicode_value = metadata.get("unicode")
        target_name = f"{key}.svg"
        target_path = output_dir / "icons" / target_name

        collected.append(
            Asset(
                key=key,
                name=str(metadata.get("tts") or metadata.get("cldr") or emoji_dir.name),
                category=group,
                unicode=str(unicode_value) if unicode_value else None,
                glyph=str(metadata.get("glyph")) if metadata.get("glyph") else None,
                keywords=keywords,
                source_svg=svg_files[0],
                output_svg=target_path,
            )
        )
    return collected


def write_manifest(
    output_dir: Path,
    source_repo: str,
    source_commit: str | None,
    style: str,
    groups: tuple[str, ...],
    assets: list[Asset],
) -> None:
    manifest_entries = []
    for asset in assets:
        manifest_entries.append(
            {
                "key": asset.key,
                "name": asset.name,
                "category": asset.category,
                "path": f"/static/avatars/fluent/icons/{asset.output_svg.name}",
                "unicode": asset.unicode,
                "glyph": asset.glyph,
                "keywords": list(asset.keywords),
            }
        )

    payload = {
        "schema_version": 1,
        "provider": "microsoft/fluentui-emoji",
        "source_repository": source_repo,
        "source_commit": source_commit,
        "style": style,
        "groups": list(groups),
        "count": len(manifest_entries),
        "avatars": manifest_entries,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build(args: argparse.Namespace) -> int:
    source_dir = Path(args.source_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    groups = tuple(args.groups)
    output_icons = output_dir / "icons"

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_icons.mkdir(parents=True, exist_ok=True)

    assets = collect_assets(
        source_root=source_dir,
        output_dir=output_dir,
        style=args.style,
        allowed_groups=groups,
    )
    assets = sorted(assets, key=lambda a: (a.category, a.name, a.key))

    if args.max_icons and args.max_icons > 0:
        assets = assets[: args.max_icons]
    if len(assets) < args.min_icons:
        raise RuntimeError(
            f"Only {len(assets)} avatars collected; expected at least {args.min_icons}."
        )

    seen: set[str] = set()
    deduped: list[Asset] = []
    for asset in assets:
        if asset.key in seen:
            continue
        seen.add(asset.key)
        deduped.append(asset)
    assets = deduped

    for asset in assets:
        shutil.copy2(asset.source_svg, asset.output_svg)

    source_commit = _repo_commit(source_dir)
    write_manifest(
        output_dir=output_dir,
        source_repo=args.source_repo,
        source_commit=source_commit,
        style=args.style,
        groups=groups,
        assets=assets,
    )
    print(f"Wrote {len(assets)} avatar icons to {output_icons}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, help="Path to fluentui-emoji repo")
    parser.add_argument(
        "--source-repo",
        default="https://github.com/microsoft/fluentui-emoji",
        help="Source repository URL for manifest metadata",
    )
    parser.add_argument(
        "--output-dir",
        default="app/static/avatars/fluent",
        help="Destination avatar folder in this repo",
    )
    parser.add_argument(
        "--style",
        default="Color",
        help="Fluent style folder to consume (e.g., Color, Flat).",
    )
    parser.add_argument(
        "--groups",
        nargs="+",
        default=list(DEFAULT_GROUPS),
        help="Emoji group names to include.",
    )
    parser.add_argument(
        "--min-icons",
        type=int,
        default=100,
        help="Minimum icons required after filtering.",
    )
    parser.add_argument(
        "--max-icons",
        type=int,
        default=240,
        help="Maximum icons to keep after sorting (0 for unlimited).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(build(parse_args()))
