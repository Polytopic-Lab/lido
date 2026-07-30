<!--
The five sections below are from development.md §2.2. Keep the order: a
reviewer reads 1 for scope, 3 to know where to spend their attention.
-->

## 1. Slice, tasks, requirements

Slice: <!-- e.g. 0.2 — CI and dependency gates; link doc/slices/<id>-<slug>.md -->
Tasks covered:
`REQ-*` implemented:
Semver impact: <!-- none | patch | minor | major, and the version this PR sets.
Pre-1.0 the minor is the breaking axis: breaking -> minor, additive -> patch
(development.md §3.10). "none" is the common answer — say it explicitly. -->

## 2. Deviations from the approved plan

<!-- The plan is frozen from its first commit (development.md §2.2). If the
implementation departed from it, say where and why. "None" if none. -->

## 3. What to look at and why

<!-- The 2-4 places a reviewer's attention is worth more than CI's. Prefer:
anything touching the wire format; anything where a test was changed rather
than added; anything where a golden or snapshot file moved. -->

1.
2.

## 4. Deferred

<!-- What was consciously left out, and where it is tracked (slice ID, issue,
or decision-log entry). "Nothing" if nothing. -->

## 5. DoD status

<!-- Quote the slice DoD from plan.md and state the result of running it,
with the command output that shows it. -->

---

- [ ] This PR does not modify `doc/specs.md`, `doc/design.md`, or
      `doc/code-style.md` (development.md §3.1). If a spec is wrong, that is
      a separate docs PR.
- [ ] This PR does not edit expected values under `conformance/`
      (development.md §3.3). If it does, the title says so and §3 explains
      how the vector was re-derived independently.
- [ ] No snapshot or golden file was bulk-accepted (development.md §3.4).
      Each changed expected output is explained in §3 above.
- [ ] Every test added names the `REQ-*` ID it covers (development.md §3.2).
- [ ] Durable decisions are promoted to `doc/decisions.md` (development.md
      §3.6).
