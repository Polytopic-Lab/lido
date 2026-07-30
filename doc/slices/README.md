# Slice plans — historical, not normative

Every file in this directory is the implementation plan for one slice,
approved before that slice was implemented and **frozen from its first
commit onward** (development.md §2.2). Plans are kept after merge because
they are the closest thing this project has to per-PR design rationale.

**They are not normative.** A slice plan records what was believed and
decided at one point in time. It is not updated when later slices change the
answer, so a stale plan read as specification is the one real risk of keeping
these files.

The documents of record are:

- `../specs.md` — requirements
- `../design.md` — architecture
- `../code-style.md` — style of generated code
- `../decisions.md` — append-only decision log

If a slice plan and any of those four disagree, the document of record wins.
Anything in a plan that constrains a future slice is promoted to
`../decisions.md` before that slice's PR merges — so read the decision log,
not the plans, for standing constraints.

Naming: `<slice-id>-<slug>.md`, e.g. `0.1-workspace-skeleton.md`. Each file
opens with a header saying it is historical and not normative.
