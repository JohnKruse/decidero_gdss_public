import json
import os
import uuid
from typing import Any, Optional

from jinja2 import nodes
from jinja2.ext import Extension
from markupsafe import Markup, escape


def is_grab_enabled() -> bool:
    """Return True when GRAB_ENABLED=true (case-insensitive)."""
    return os.getenv("GRAB_ENABLED", "").strip().lower() == "true"


class GrabExtension(Extension):
    """
    Provides a {% grab %}...{% endgrab %} block that wraps rendered
    content with DOM markers to help map UI selections back to templates.
    """

    tags = {"grab"}

    def parse(self, parser):  # type: ignore[override]
        token = next(parser.stream)
        lineno = token.lineno

        id_expression: nodes.Expr = nodes.Const(None)
        while parser.stream.current.type != "block_end":
            attr_name = parser.stream.expect("name")
            if attr_name.value != "id":
                parser.fail(f"Unsupported attribute '{attr_name.value}'", attr_name.lineno)
            parser.stream.expect("assign")
            id_expression = parser.parse_expression()
        body = parser.parse_statements(["name:endgrab"], drop_needle=True)

        call = self.call_method(
            "_render_grab",
            args=[
                nodes.ContextReference(),
                nodes.Const(lineno),
                id_expression,
            ],
        )
        return nodes.CallBlock(call, [], [], body).set_lineno(lineno)

    def _render_grab(
        self,
        context: Any,
        lineno: int,
        provided_id: Optional[Any],
        caller,
    ) -> Markup:
        template_name = getattr(context, "name", None) or getattr(
            context.environment, "template_name", "unknown"
        )
        block_id = str(provided_id) if provided_id not in (None, "", False) else f"grab-{uuid.uuid4().hex}"
        escaped_id = escape(block_id)
        payload = {
            "template": template_name,
            "start_line": lineno,
            "id": block_id,
        }
        meta_json = json.dumps(payload, ensure_ascii=False)
        content = caller()
        wrapper = (
            f'<div data-grab-id="{escaped_id}">{content}</div>'
            f'<script type="application/json" data-grab-meta data-grab-id="{escaped_id}">{meta_json}</script>'
        )
        return Markup(wrapper)
