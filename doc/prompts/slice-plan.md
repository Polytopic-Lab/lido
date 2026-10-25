# Prompt — slice planning

Canonical text of `doc/development.md` §6.1. Takes one argument: the slice
ID, e.g. `2.2`. Referred to below as `<slice-id>`.

Agent-specific shims supply the argument and point here — currently
`.claude/commands/slice-plan.md` and `.agents/skills/slice-plan/SKILL.md`
(Zed). Edit this file, not the shims.

---

Slice: `<slice-id>` (see doc/plan.md).

Read doc/plan.md for this slice's scope, requirements, and DoD, then read
doc/specs.md, doc/design.md, doc/code-style.md, doc/rust-style.md, and
doc/decisions.md. Produce a detailed implementation plan for this slice
only, and write it to `doc/slices/<slice-id>-<slug>.md`, where `<slug>` is
the slice's title from plan.md in kebab-case.

The plan must:
- Quote the slice DoD from plan.md verbatim.
- List every REQ-* ID this slice implements, and where each is tested.
- Name every file created or modified.
- Specify the tests first: what fails before the change, what passes after.
- Flag anything the specs do not determine, as an open question for me —
  do not decide it yourself.
- Flag any place where implementing this would require changing specs.md,
  design.md, or code-style.md. Those documents are read-only here.

Do not write any implementation code yet.
