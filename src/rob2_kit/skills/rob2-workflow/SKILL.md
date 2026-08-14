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

`discard_active_batch` is destructive and is never error recovery. Call it only
after an explicit researcher instruction in the current conversation, with the
current frozen-batch hash, the exact confirmation literal, an attributable actor,
a UTC observation time, and the researcher's nonempty reason. These fields bind
the request to the displayed batch and make the destructive action explicit; they
do not prove who authored it. On a tool, coordinate, or judgment error, resume or
retry within the returned bounds, or return `needs_input`; never discard to recover.
