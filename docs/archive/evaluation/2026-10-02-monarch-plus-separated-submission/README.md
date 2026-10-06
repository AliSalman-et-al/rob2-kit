# One bounded check of separated Domain submission

The sole paid follow-up ran frozen 4dd280de4449f057dd38bb60a8130cedfe87b95f,
gpt-6-luna medium, CLI 0.159.0. Same prompt, approved target, seeded D1/D2 and
source hashes as the preceding MONARCH-plus attempt; discovery caches were
cleared in a separate owned copy. This remains a seeded D3 probe with unavailable
raw registry bytes, not a cold end-to-end assessment or exact registry replay.
Previous attempts and workspaces remain preserved.

The process automatically stopped after the second rejected submission:
85.48 seconds, 11 tool calls (4 context pages, 1 failed broad source search,
3 page reads including an unavailable registry read, 1 render, 2 rejected saves).
No accepted model checkpoint, final response, third attempt or paid retry.
Exit code zero reflects CLI interruption handling, not success. All owned MCP
processes exited.

Durable usage recording retained 11 generation usage records. Their summed and
last cumulative figures agree: **361,845 input; 293,120 cached input; 68,725
uncached input; 2,031 output**, including 501 reasoning tokens. These are recorded
actual generation totals, not estimates. The interrupted turn has no final
completion event; any unreported in-flight usage cannot be certified by this
ledger. Guards were 400,000 total input, 100,000 uncached, 10,000 output, 18 tools,
8 minutes wall and 2 minutes idle, with monitored in-flight overshoot authorized.
The correction guard fired; no other recorded guard threshold was reached.
Credentials and full local rollout/home databases are excluded from Git. Exact
usage records, outputs, config, prompt and stop reason are retained here.

## What changed and what failed

Both drafts used the separate limitations and absence_searches collections,
so the previous nested limitation shape disappeared. The first used explicit
scientific **role** values and **premise** keys. The second corrected the premise
key but replaced roles with the invalid generic kind **evidence**. Neither was
silently coerced. D3 answers remained NI / No / NI / NI; no gain in completion or
scientific accuracy was observed. Missing raw registry integrity still blocks
broad search/read and limits source coverage. The model's account of unreadable
flow data is preserved as its assertion, not an independently verified absence.

The final public interface uses the clear field names role and premise. These
are replacements, not compatibility aliases. Role is an explicit scientific
classification; its value is copied into canonical kind without inference.
The limitations collection already identifies an unresolved proposition, so the
server copies premise into canonical unresolved_premise. Original stored
records keep their format. Public callers, skill guidance, contract snapshot and
release/test callers were migrated.

The first follow-up call now validates unchanged at the transport boundary. A
separate **offline** MCP control still rejects it at the existing scientific
uncertainty gate: its definitive D3.2 No also declares an unresolved premise
(complete_claim_has_unresolved_premise). The answer is unchanged and no checkpoint
is accepted. This demonstrates that simpler syntax does not bypass the guard;
it does not establish that the scientific question has a particular true answer.
The second generic-evidence draft remains invalid. No further paid check of the
final names ran.

## Verification and remaining limits

15 submission regressions passed, including all five earlier malformed calls,
the newly captured call shapes, preservation of explicit answers/roles/prose,
and definitive claims with unresolved limits. Five release checks, the public
schema check, eight previously affected boundary tests, and 18 input-contract /
reasoning tests passed. Full src/tests/docs/release typing and focused lint passed.
The named-field conversion initially left an old serialization expression and
schema assertion; tests exposed them and both were fixed before commit.

Completion benefit of the final field names remains unmeasured. The next useful
step is offline review of question-specific uncertainty and retrieval recovery,
not another automatic same-case paid cycle. The full benchmark stays off.
