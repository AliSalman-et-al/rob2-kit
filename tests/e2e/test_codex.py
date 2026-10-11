"""The Codex entrypoint keeps rendered pixels beside the receipt.

Codex prefers structured content over content blocks, so `rob2 mcp-codex`
advertises render_page without an output schema and returns the receipt as text.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.types import ImageContent, TextContent

from e2e import trial
from e2e.agent import Agent
from e2e.test_assessment import OUTCOME
from rob2_kit.interfaces.mcp.contracts import output_schema, validate_output


def test_codex_render_delivers_pixels_and_a_usable_receipt(tmp_path: Path) -> None:
    trial.build(tmp_path)
    agent = Agent(tmp_path, server="mcp-codex")
    try:
        agent.prepare(OUTCOME)
        render = agent.tools()["render_page"]
        assert render.output_schema is None
        assert render.meta and render.meta["rob2_receipt_schema"] == output_schema("render_page")
        assert agent.tools()["get_status"].output_schema is not None

        source = agent.sources["main_article"]
        result = agent.raw(
            "render_page", {"trial_id": agent.trial_id, "source_id": source, "page": 2}
        )
        assert not result.is_error and result.structured_content is None
        receipt_block, image, schema_block = result.content
        assert isinstance(receipt_block, TextContent) and isinstance(schema_block, TextContent)
        assert isinstance(image, ImageContent) and image.mime_type == "image/png"
        receipt = json.loads(receipt_block.text)
        validate_output("render_page", receipt)
        assert json.loads(schema_block.text) == {
            "tool": "render_page",
            "receipt_schema": output_schema("render_page"),
        }
        # The text receipt is enough to cite what the model saw.
        agent.ok(
            "select_visual_evidence",
            {
                "trial_id": agent.trial_id,
                "source_id": source,
                "delivery_receipt": receipt["data"]["delivery_receipt"],
                "transcription": "Table 2: recurrent stroke 31/602 apixaban, 52/602 aspirin.",
            },
        )
    finally:
        agent.close()
