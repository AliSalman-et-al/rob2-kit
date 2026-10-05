# Authorized pair: pre-inference tool-inventory blocker

Parent explicitly authorized exactly two tool-free `gpt-6-luna` / `medium`
sessions after independently reproducing the approved checker. Neither session
has launched. No credentials, new auth home, provider schema probe or inference
request was created. Original frozen sources, prompts, rubric and schema remain
unchanged.

The installed CLI is 0.159.0. Offline help confirms the intended exec flags;
feature listings and the bundled model catalog were saved privately. A neutral
working directory and the existing `_codex_environment(..., strict=True)` remove
inherited host tool-pipe/environment settings. Explicit overrides disable shell,
unified exec, images, apps, plugins, skill search, multi-agent, browser/computer,
image generation, tool suggestions and sleep; web search is disabled, code mode
is disabled, and the existing configured MCP server is disabled in the offline
render. Paid exec would also ignore user config and rules.

Offline `debug prompt-input` initially rejected JSON object syntax where a
feature setting required TOML. Corrected TOML rendered successfully without
inference; the failed preflight was preserved. The rendered list still includes
generic skill/agent instructions and does not include a tool registry. The
bundled Luna catalog advertises `send_user_message_async` and `clock` as
experimental supported tools. These observations do not prove that those tools
would be advertised by the configured paid exec; they also do not prove their
absence. Disabling known external tools or observing zero tool invocations would
not establish the requested zero advertised-tool configuration.

No existing offline CLI command found in this check exposes the exact resulting
tool registry. The debug renderer returns only model input items; generated
app-server protocol schemas expose config/thread settings but not that registry.
The existing usage/session records similarly do not provide an advertised tool
list. No custom CLI build, provider proxy, model-catalog rewrite or paid probe was
introduced to resolve this.

Execution therefore remains blocked on verifying the strict zero-tool exposure
requirement before inference. Resolve through a supported existing configuration
or verification route, or parent clarification of the required tool-free
boundary. The already approved two-session authority has not been consumed;
there is no output to anonymize or scientifically score. The frozen U/V naming
and usage-accounting plan remains available in `execution-readiness.md`.

Private evidence is retained under
`diagnostics/synthetic-source-inference-contrast-20261005/paid/`: initial and
corrected offline render/stdout/stderr, config overrides, exec help, feature
listing, bundled catalog and generated protocol schemas. No semantic output was
inspected because none exists. These offline checks do not establish provider
acceptance or scientific benefit.
