Packaged operational guidance through MCP
========================================

Tools-only clients can read `SKILL.md` and its local reference links through the read-only `read_guidance(document)` tool. Each response includes exact UTF-8 content, a content hash and resolved local links. Resource-capable clients can use `rob2://guidance/SKILL` or `rob2://guidance/<reference basename>` for the same content. This is instruction access, not Trial Source intake or scientific Evidence selection.

The tool reads only documents in the installed rob2-assess skill. It rejects arbitrary filesystem paths and unavailable documents; local links cannot leave that package. Reading guidance preserves canonical assessment and working state. The ordinary typed response contract and read-only annotations apply. The skill describes this route so a host without filesystem reading can follow mandatory reference instructions.

Native diagnostic preparation must test the actual stdio client and enabled-tool configuration: walk the skill's transitive local links, compare returned UTF-8 bytes/hashes with the frozen package, verify every required document is reachable, and freeze the receipts. Check that the root skill is supplied in actual client instructions. Client capability/availability does not establish that a later model consumed a reference; inspect that invocation's native receipts separately. No exhaustive unrelated document reading is imposed on the assessor.

This fixes a general integration defect exposed by a tools-only invocation whose root instructions required a local reference that no enabled interface could read. It adds no scientific rule, default prototype activation, case hint, Source substitution or shell access. The first failed invocation remains immutable; corrected attempts must be separately authorized and versioned.
