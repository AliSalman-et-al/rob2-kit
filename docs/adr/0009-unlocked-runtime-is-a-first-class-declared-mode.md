# Unlocked runtime is a first-class, declared mode

`rob2-kit`'s default Harness install keeps a project-local `.rob2/runtime` copy of the released wheel, verified byte-for-byte against the release's pin (Locked runtime). A real deployment wires its Harness configuration directly to the shared release runtime instead, entirely outside any bootstrap or doctor path — so its ownership/pin checks never ran, and simply failing those checks retroactively would make an already-working production deployment permanently unable to pass.

We treat direct-shared-runtime wiring as a first-class Unlocked runtime mode: an explicit declaration written once by its own bootstrap mode into the project's lock state, validated against the shared release runtime's own self-consistency rather than requiring a project-local copy. Wiring that resembles this shape without the recorded declaration still fails as a Run integrity failure — undeclared and declared bypass must stay distinguishable, or the mode defeats its own purpose.

## Considered Options

Keep unlocked wiring unsupported and let every ownership check fail for it. Rejected: it doesn't close the stale-pin risk this design addresses, it just relocates it to a check nobody can make pass, on a deployment shape we know exists.
