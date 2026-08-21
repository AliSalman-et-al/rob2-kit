---
name: rob2-signalling
description: Complete RoB 2 Domain signalling from an exact approved work packet.
---

# RoB 2 signalling

Start only from the exact `work_packet` in authoritative status. It fixes the Trial, Result, active Domain, source inventory, pack identities, and prior checkpoint basis. The generated public contract is the schema source of truth; preserve returned references and Transitions unchanged.

1. Use `list_sources`, `retrieve_evidence`, and `render_page` only as needed for deliberate scoped Evidence. Complete when each active answer has its evidence use and rationale.
2. Submit the strict active-Domain draft with `validate_domain_judgment`. Repair every returned defect, including independent defects, then validate again. Complete when a candidate and Transition are returned.
3. Deliberately inspect that candidate using `read_record`, then `commit_domain_judgment` with the exact returned Transition. Complete when status exposes the next work packet or Trial-finish continuation.

Repeat for each active Domain. Never recreate an identity, use Evidence outside the packet scope, or replace a checkpoint revision. Conditions and conflicts return to authoritative status. Once all five active checkpoints are committed, return the exact synthesis/finish continuation to `rob2-workflow`; it owns researcher review, terminal preparation, finalization, reporting, and discard.
