# Prompt — slice implementation

Canonical text of `doc/development.md` §6.2. Takes one argument: the slice
ID, e.g. `2.2`. Referred to below as `<slice-id>`.

Agent-specific shims supply the argument and point here — currently
`.claude/commands/slice-implement.md` and
`.agents/skills/slice-implement/SKILL.md` (Zed). Edit this file, not the
shims.

---

Implement slice `<slice-id>` per the approved plan in
`doc/slices/<slice-id>-<slug>.md` (find the file by its `<slice-id>-`
prefix).

First: create the branch and commit that plan file, unchanged, as the
first commit. Then implement.

Constraints:
- Do not modify specs.md, design.md, or code-style.md.
- Do not modify the slice plan file. If you deviate from it, leave it as
  approved and describe the deviation in the PR body.
- Do not modify existing conformance vectors. If a vector and the
  implementation disagree, stop and tell me.
- Do not bulk-accept snapshot or golden-file changes. Each one gets an
  explanation in the PR body.
- Follow doc/rust-style.md.
- Every test names the REQ-* ID it covers.

Then: review your own work against the approved plan and the cited
requirements, and fix what you find.

Then: create a branch, commit, and open a PR whose body has —
1. Slice ID, tasks, REQ-* IDs
2. Deviations from the approved plan, with reasons (or "none")
3. What I should look at and why (2–4 items)
4. Anything deferred and where it's tracked
5. DoD status
