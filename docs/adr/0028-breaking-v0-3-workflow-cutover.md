# Replace the v0.2 workflow in one breaking cutover

Version 0.3 replaces Transitions, persisted work packets, host review
acknowledgments, and the passive two-skill handoff. It uses State revisions,
on-demand projections, atomic Domain saves, and one Assessment skill. The cutover
provides no active-workspace migration or compatibility layer because preserving
the old protocol would retain the complexity that this change removes.
