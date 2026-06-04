#!/usr/bin/env python3
"""Generate Mermaid + Graphviz diagrams from an orchestration document.

Figures are rendered directly from the orchestration JSON, so they stay in sync
with what the engine runs. Use for paper figures.

Usage:
    python scripts/export_orchestration_diagram.py orchestrations/delphi.json
    python scripts/export_orchestration_diagram.py orchestrations/delphi.json --out-dir docs/figures

Writes `<stem>.mmd` and `<stem>.dot` to the output directory (default:
docs/figures), and echoes the Mermaid to stdout. Render the DOT with, e.g.:
    dot -Tpng docs/figures/delphi.dot -o docs/figures/delphi.png
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Allow running as a plain script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.orchestration_diagram import to_graphviz, to_mermaid  # noqa: E402
from app.services.orchestration_loader import load_orchestration_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", help="Path to an orchestration JSON document.")
    parser.add_argument(
        "--out-dir",
        default="docs/figures",
        help="Directory to write <stem>.mmd and <stem>.dot (default: docs/figures).",
    )
    args = parser.parse_args()

    doc_path = Path(args.document)
    document = load_orchestration_path(doc_path)

    mermaid = to_mermaid(document)
    dot = to_graphviz(document)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = doc_path.stem
    (out_dir / f"{stem}.mmd").write_text(mermaid, encoding="utf-8")
    (out_dir / f"{stem}.dot").write_text(dot, encoding="utf-8")

    print(f"# {document.name} (v{document.version}) — Mermaid\n")
    print(mermaid)
    print(f"Wrote {out_dir / (stem + '.mmd')} and {out_dir / (stem + '.dot')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
