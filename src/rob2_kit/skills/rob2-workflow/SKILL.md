---
name: rob2-workflow
description: Manage an RoB 2 batch through the rob2-kit MCP server.
---

# RoB 2 workflow

Use rob2-kit as a model-free MCP service. You are the only agent and model loop.
Follow the server's structured results when they become available: prepare one
complete batch proposal, obtain whole-batch approval, sequence trials, and hand off
terminal artifacts. Finish each Trial exactly once through `finish_trial`: use its
`assessment` envelope after all five checkpoints, or its `needs_input` / `failed`
envelope with typed problems. Then call `finalize_batch`. Do not invent evidence or
persist hidden reasoning in the host.
