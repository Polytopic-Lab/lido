# Lido — Development Process

Status: Draft v0.1

## 0. What this document is

`specs.md` says *what* to build, `design.md` says *how it is structured*,
`plan.md` says *in what order*. This document says **how the work actually
gets done** when most of the typing is done by an LLM: the unit of work,
the review loop, the mechanisms that keep the implementation anchored to
the specs, and which model to use at each stage.

Two constraints shape every recommendation here:

1. **Speed to a useful three-language toolchain.** The vertical slice
   through Phase 5 is the critical path; everything else is sequenced
   around it.
2. **No silent drift.** With four documents of frozen decisions and ~250
   `REQ-*` IDs, the failure mode isn't bad code — it's code that quietly
   stops matching the spec, plus a spec that quietly gets edited to match
   the code. The mechanisms in §3 exist specifically to make that
   impossible to do accidentally.

A third, softer goal: this project should teach Rust. §4 designates which
work is done by hand for that reason, and how to keep it from becoming a
bottleneck.

---

## 1. The unit of work: a slice

**One slice = one branch = one PR = one plan-implement-review loop.**

`plan.md` holds the slices themselves; this section holds the rules for
cutting them. Phases 0–5 are already sliced there; Phases 6–10 are still
task lists and get sliced at their phase kickoff.

Sizing heuristics:

- A slice should be reviewable by a human in **30–45 minutes**. If the
  diff is bigger than that, split it — the review is what catches drift,
  and a review you skim is a review that didn't happen.
- **A slice must carry its own runnable DoD.** Not a subjective
  judgement, and not inherited from the phase. This is the single most
  important property: a slice without a check of its own forces the
  implementing session to invent one, and a self-authored DoD is one it
  can satisfy trivially.
- Rule of thumb for size: a slice is roughly **one L-sized task, or one
  M, or two to three S/M tasks**. The mapping from the old v0.1 task list
  is deliberately many-to-one and uneven.
- Never split a slice such that `main` is left with failing tests or a
  half-migrated interface. Every merge is a coherent state.
- Phases 7 and 8 tolerate larger slices, because by then the Rust backend
  is a working reference implementation and each slice is "mirror a proven
  behavior in another language" rather than "decide a behavior."

Phases are checkpoints, not sprints. They are uneven by design — Phase 0
is two slices, Phase 2 is seven — and evening them out would mean either
merging unrelated gates or splitting a real one.

---

## 2. The loop

Three nested loops. Most of the value is in the middle one.

### 2.1 Outer loop — per phase

**Phase kickoff** (one session, no code):

1. Read the phase's tasks and their `REQ-*` references.
2. Resolve every open question the phase touches. Phase 3 must close
   design.md §8 Q1 (parser approach). Phase 4 touches §8 Q3 (whether
   `lido-ir` stays one crate). Phase 5 touches §8 Q2 and Q4. Phase 9
   closes specs.md §16 Q5.
3. Record each resolution in `doc/decisions.md` (§3.6) as a numbered
   entry with the alternatives considered and the reason.
4. Draft the slice breakdown for the phase.

This is the highest-leverage half hour in the whole process. An LLM asked
to implement slice 4.3 without a written wire-key policy will invent one,
and it will be plausible, and you will not notice for three phases.

**Phase close** (one session, mostly docs):

1. Run the phase DoD explicitly and record the result.
2. Reconcile: does `design.md` still describe what was built? Does
   `plan.md` need re-sequencing for what was learned? Update them in a
   dedicated docs PR.
3. Note any requirement that turned out to be wrong, ambiguous, or
   unimplementable — as a spec PR, not a silent code deviation.

### 2.2 Middle loop — per slice

This is your existing workflow with one cut added:

```
  [1] AI: detailed implementation plan for the slice
       │
       ▼
  ═══ HUMAN GATE ═══  ← the new step. 5 minutes. This is the whole point.
       │
       ▼
  [2] AI: implement the approved plan
       │
  [3] AI: self-review the result against the plan + specs, apply fixes
       │
  [4] AI: open PR; body highlights what needs human attention and why
       │
       ▼
  [5] HUMAN: review PR → merge, or send back with comments
```

**Why split at the gate.** Your previous single-prompt version is more
efficient per slice, and for a well-trodden codebase it's fine. It is the
wrong trade here because Lido's specs are dense, mostly-frozen, and full
of decisions that are cheap to violate and expensive to unwind (canonical
key order, wire-key derivation, cycle-breaking edges, the runtime
contract). A plan is ~200 lines and takes five minutes to read; a wrong
plan produces a 2,000-line PR that looks correct.

**Where the plan lives: `doc/slices/<id>-<slug>.md`, committed as the
first commit on the branch.** For example `doc/slices/2.2-cbor-encoder.md`.

Not scrollback, not a GitHub issue, not a paste-back into the next
prompt. Four reasons:

- **It's in the PR diff.** The reviewer sees the approved plan and the
  implementation together, so checking for deviation is mechanical rather
  than a memory exercise.
- **The implementing session reads it from disk**, so nothing is lost or
  reworded in transcription between the two prompts.
- **Being the first commit fixes it in time.** Later commits can't
  quietly retrofit the plan to match what got built.
- It survives a session crash or a context reset mid-slice.

Rules for the file:

- **Do not update it during implementation.** If the implementation
  deviates, the plan stays as approved and the deviation is described in
  the PR body. The point is to make the gap visible, not to close it.
- **Keep it after merge.** These are small and they are the closest thing
  to a per-PR design rationale. But they are **not normative** — every
  file in `doc/slices/` carries a header saying so, and
  `doc/slices/README.md` states that `specs.md`, `design.md`,
  `code-style.md`, and `decisions.md` are the documents of record. A
  stale slice plan read as spec is the one real risk of keeping them.
- **Durable decisions don't stay here.** Anything that will constrain a
  future slice gets promoted to `doc/decisions.md` before the PR merges.

The file's structure mirrors the planning prompt in §6.1:

```markdown
# Slice 2.2 — CBOR encoder

> Historical implementation plan, not normative. See specs.md,
> design.md, code-style.md, and decisions.md for the documents of record.

**Plan DoD** (from plan.md): <quoted verbatim>

## Requirements covered
| REQ | Where tested |

## Files
| Path | New/modified | Purpose |

## Tests first
<what fails before, what passes after>

## Open questions for review
<anything the specs do not determine — decided by the human, not here>

## Spec conflicts found
<or "none">
```

Read the plan for four things specifically:

- Does it cite the right `REQ-*` IDs, and did it miss any?
- Does it invent any behavior not in specs.md or design.md? (If yes,
  that's either a spec gap to record or drift to reject.)
- Does it propose editing `specs.md`, `design.md`, or `code-style.md`?
  Reject — see §3.1.
- Does it plan to write the tests, and do the tests actually test the
  requirement rather than the implementation?

**Steps 2–4 stay a single prompt.** That part of your workflow works.

**Step 3 (AI self-review) is worth keeping**, but scope it: review against
the *approved plan and the cited requirements*, not "review this code."
The generic version produces cosmetic churn; the anchored version catches
real deviations.

**Step 4 PR body** should contain, in this order:

1. Slice ID, tasks covered, `REQ-*` IDs implemented.
2. **Deviations from the approved plan**, with reasons. If none, say so.
3. **What to look at and why** — the 2–4 places where a reviewer's
   attention is worth more than CI's. Prefer: anything touching wire
   format, anything where a test was changed rather than added, anything
   where a golden/snapshot file moved.
4. Anything deferred, and where it's tracked.
5. DoD status.

Put this in `.github/pull_request_template.md` so it's structural rather
than remembered.

### 2.3 Inner loop — within implementation

Test-first wherever the requirement is expressible as a vector or an
assertion, which for this project is nearly everywhere:

- Phase 3: write the rejection-corpus case (schema + expected span) before
  the parser change.
- Phase 4: write the golden IR JSON before the lowering code.
- Phases 2/5/7/8: the Phase 1 corpus **is** the test. Wire the vector in
  first, watch it fail, make it pass.

This matters more than usual with an LLM: a test written after the
implementation tends to encode what the code does. A test written from
the spec encodes what the code should do.

---

## 3. Anti-drift mechanisms

These are the load-bearing part of this document. Each one converts a
"remember not to do that" into something mechanical.

### 3.1 The specs are normative and read-only during implementation

**An implementation PR must not modify `specs.md`, `design.md`, or
`code-style.md`.** If the spec is wrong, incomplete, or contradicts
itself, that is a finding — stop, open a separate docs PR describing the
problem and the proposed change, get it merged, then resume.

This is the single most important rule here. The characteristic LLM
failure on a spec-heavy project is not writing wrong code; it is writing
wrong code and then adjusting the spec so the code is right. Once the
spec is downstream of the code, every subsequent review is worthless
because there is nothing left to check against.

Enforce it with a CI check on implementation branches, or at minimum a
line in `CLAUDE.md` and a checkbox in the PR template.

`plan.md` is different — it is a working document and slices routinely
refine it. `doc/decisions.md` is append-only.

### 3.2 Requirement traceability

Every slice cites `REQ-*` IDs, and those IDs appear in the tests:

```rust
/// REQ-RT-165: canonical field order is bytewise over encoded keys,
/// length-first — "age" < "name" < "email".
#[test]
fn req_rt_165_key_order_is_length_first() { … }
```

Two payoffs. First, a reviewer can check coverage by grepping rather than
by reading. Second — and this is the real one — a test named after a
requirement is very hard for a later session to quietly weaken, because
weakening it means editing a line that names the rule it's breaking.

Phase 1 already plans a coverage manifest (slice 1.4). Extend it to the
whole requirement set, and make "every `REQ-*` in the phases completed so
far maps to at least one test" a phase-close check.

### 3.3 The conformance corpus is the ground truth

The corpus is Phase 1 — first after foundations, ahead of the parser —
precisely because it is the only part of this system that can tell you
the implementation is wrong rather than merely self-consistent. Three
consequences of that ordering:

- Authoring vectors against RFC 8949 with an independent tool forces you
  to understand the wire format before any Lido code exists to bias you.
- Every phase after it (2, 5, 7, 8, 9) gets a DoD of the form "make the
  oracle pass" instead of "does this look right?" — which is exactly the
  kind of check an LLM cannot argue its way around.
- The runtime (Phase 2) can be proven with hand-written codecs before any
  generator exists, so Phase 5 becomes "does codegen reproduce known-good
  code?" rather than "build the generator and the contract together and
  hope."

Two rules hold for the life of the project:

**Expected vectors are never generated by Lido's own runtime.** Stated in
`plan.md` Phase 1; hold it absolutely, including in Phase 9 when adding
fuzz-derived cases is tempting.

**The corpus is never edited to make Lido pass.** If a vector and the
implementation disagree, one of them is wrong, and you find out which by
re-deriving the vector with the independent tool — not by inspection. Any
PR touching expected values under `conformance/` must say so in its title.

### 3.4 Golden files and snapshots are reviewed, never bulk-accepted

Phases 1, 2, and 5 all lean on snapshot tests. "Update the snapshots"
is the single easiest way for a session to turn a real regression into a
green build.

Rules:

- A snapshot/golden diff in a PR must be called out in the PR body with
  an explanation of *why the expected output changed*.
- Never run a blanket snapshot-accept command as part of implementation.
  Accept individually, having read each diff.
- If a slice's plan doesn't anticipate a snapshot change but the PR has
  one, that's a signal to review harder, not a formality.

### 3.5 CI is the gate that can't be talked around

From slice 0.2, plus additions as later phases land, the required checks:

- `cargo build` / `cargo test` on Linux, macOS, Windows
- `cargo clippy -- -D warnings`
- `cargo fmt --check`
- `cargo deny check` (permissive-only, REQ-DEP-020)
- Conformance self-check once slice 1.2 lands
- `no_std` target build once slice 2.7 lands (REQ-RT-110)
- Requirement-coverage check once slice 1.4 lands
- Determinism test once Phase 5 lands (REQ-GEN-070)
- `-fno-exceptions -fno-rtti` build once Phase 8 lands (REQ-RT-120)

Branch protection on `main` requiring all of them. An LLM will
occasionally propose `#[allow(dead_code)]` or a `clippy::allow` to get
green; treat each one as requiring an explicit justification comment, and
be suspicious of blanket module-level allows.

### 3.6 A decision log

Create `doc/decisions.md`. Append-only, numbered, one entry per resolved
question:

```markdown
## D-004 — Parser implementation for lido-cddl
Date: 2026-08-02 · Closes: design.md §8 Q1 · Phase: 1

Decision: hand-written recursive descent.
Alternatives: chumsky, nom, pest.
Rationale: …
Consequences: …
```

The purpose is not documentation for its own sake. It's that a session
three phases later, which has never seen the reasoning, will otherwise
re-derive a *different* answer and quietly implement it. Point `CLAUDE.md`
at this file so every session loads the index.

Migrate design.md §8's four questions, specs.md §16's six, and
code-style.md's four into this log as they close.

### 3.7 Context hygiene

- **One session per slice.** Start fresh. Long sessions accumulate stale
  assumptions and half-abandoned approaches, and are the main mechanical
  source of drift.
- **`CLAUDE.md` at the repo root** pointing at the four docs, the decision
  log, and the non-negotiable rules (specs are read-only; corpus is
  ground truth; cite REQ IDs; no snapshot bulk-accept). Keep it short —
  it's loaded every session, so every line competes for attention.
- **State the slice explicitly** at the start of each session rather than
  "continue where we left off."

### 3.8 A style guide for Lido's own Rust

This closes code-style.md open question 1, and it earns its keep for a
specific reason: LLM-written Rust compiles and passes tests while being
unidiomatic in consistent, recognizable ways — `clone()` where a borrow
works, `unwrap()`/`expect()` in library code, `Rc<RefCell<_>>` reaching
for a shape that doesn't need it, stringly-typed errors, `Vec<String>`
where an enum belongs, and 200-line functions that should be three.

Write `doc/rust-style.md` at Phase 2 kickoff, before slice 2.1 — that is
the first slice that produces real Rust. It's small, two pages. Make it
the checklist for the self-review step. Suggested content:

- Error handling: `thiserror` for library errors, no `unwrap`/`expect`
  outside tests and `main`, no `panic!` on user input.
- Ownership: prefer borrows; justify each `clone()` in a hot path;
  `Rc`/`RefCell` requires a comment explaining why the tree shape needs it.
- Types: newtypes for wire keys, spans, discriminants — not bare `u64`.
- Naming and module layout conventions.
- What "done" looks like: doc comments on public items, `#[must_use]`
  where it matters, no `#[allow]` without justification.

Note this is *separate from* `code-style.md`, which governs the style of
**generated** output. Don't let the two blur.

### 3.9 Deeper review at checkpoints

The per-PR review catches most things. At two points, spend more:

- **End of Phase 4** (the IR is frozen into golden files — errors here
  propagate into three backends).
- **End of Phase 5** — the plan already calls this the architecture
  go/no-go. Any IR or runtime-contract rework must happen here, before
  it has to be done three times.

At those two points, run `/code-review ultra` on the accumulated branch
(multi-agent cloud review; you trigger it, it's billed separately), and
budget real time for the DoD rather than treating it as a formality.
`/security-review` is worth one pass at the end of Phase 9, where the
fuzzing and malformed-input work lands.

---

## 4. Where you write the code

Hand-writing everything defeats the purpose; hand-writing nothing means
you finish the project without the Rust fluency you wanted. The split
below picks tasks where the didactic value is highest *and* where being
the author has independent engineering value.

### 4.1 Tasks to write yourself (AI reviews)

| Slice | Why |
|---|---|
| **2.1 The runtime contract** | The most important one. Traits, generics, associated types, error design — the core of intermediate Rust. It is also the contract all three backends target for the rest of the project's life. Owning it by hand means you understand every downstream PR. |
| **3.1 Lexer** | Byte-offset spans, `&str` vs `String`, iterator patterns. The canonical first real Rust exercise, and small enough to finish. |
| **3.2 AST types** | Enums and pattern matching are *the* Rust idiom. Designing this data model by hand is the highest-value hour in the front end. |
| **4.2 Cycle classification** | Graph algorithms fight the borrow checker. Learning to reach for index-based graphs (`Vec<Node>` + `usize`) instead of `Rc<RefCell<Node>>` is a genuine Rust milestone. |
| **4.3 Key-order comparator** (the comparator specifically, not the whole slice) | Tiny, high-stakes, easy to get subtly wrong — `plan.md` notes an alphabetical implementation must fail the test. Perfect test-first exercise. |

For these, invert the loop: **you write, then AI reviews.** Being
corrected on your own code teaches far more than reading correct code.
Ask specifically for "idiomatic Rust" feedback rather than correctness
feedback — correctness is what the tests are for.

**Note the ordering tension.** Under the critical-path numbering, the
runtime contract (2.1) now comes *before* the lexer and AST — hardest
first, pedagogically backwards. The engineering argument wins: proving
the wire contract against the corpus before any generator exists is worth
more than an easy on-ramp. If 2.1 proves too steep as a first
hand-written piece, delegate it with a thorough explain-the-diff pass and
hand-write 3.1/3.2 when you reach them. Don't reorder the phases for it.

### 4.2 Tasks to delegate (you review)

Everything else, and specifically: CI configuration (0.4–0.6), code
generation (5.2–5.4 — mostly string building, low didactic value), CLI
plumbing (Phase 6), the Java and C++ backends (Phases 7–8 mirror proven
Rust behavior), benchmarking harnesses (9.7–9.9), and packaging
(Phase 10).

For AI-written Rust, add an **explain-the-diff pass** on the first few
PRs of each new area: ask for a walkthrough of the non-obvious parts
before merging. It costs ten minutes and converts reviewing into
learning. Drop it once the patterns are familiar.

### 4.3 Don't let this become the bottleneck

If a hand-written task stalls for more than a day or two, hand it over
with the constraint "implement this the way I started it" and take the
explain-the-diff pass instead. The learning goal is real but it is
secondary to shipping the vertical slice.

---

## 5. Model selection

Available: **Claude Opus 5** (`claude-opus-5`), **Claude Sonnet 5**
(`claude-sonnet-5`), **Claude Haiku 4.5** (`claude-haiku-4-5`), and
**Claude Fable 5** (`claude-fable-5`). In Claude Code, switch with
`/model`; `/fast` toggles fast mode (same Opus model, higher output
speed, premium pricing).

Effort matters as much as model choice. Claude Code defaults to `xhigh`,
which is the right setting for coding and agentic work. Where the table
below says "high effort," it means don't reach for `max` reflexively —
higher effort is not monotonically better and can overthink routine work.

| Stage | Model | Notes |
|---|---|---|
| **Phase kickoff / architecture decisions** | Opus 5 | Deep reasoning, weighing alternatives, closing open questions. This is where model quality pays off most. |
| **The two or three genuinely hardest calls** | Fable 5 | The runtime contract (slice 2.1), the IR data model (slice 4.1), the Phase 5 go/no-go. Anthropic's most capable model, ~2× Opus pricing ($10/$50 per MTok vs $5/$25), and single turns can run many minutes. Reserve it; don't default to it. |
| **Slice planning (step 1)** | Opus 5 | Needs to hold specs + design + code-style + decisions in context and produce a plan that cites the right requirements. |
| **Implementation (step 2)** | Opus 5 | Default. Strongest on multi-file agentic work, which is what a slice is. |
| **Implementation of mechanical slices** | Sonnet 5 | Genuinely viable once a pattern is established: Phase 7/8 slices mirroring the proven Rust codec, CLI plumbing (Phase 6), test-harness expansion, benchmark scaffolding. Near-Opus quality on coding at lower cost. Not for anything that *decides* wire behavior. |
| **Self-review (step 3)** | Opus 5 | Bug-finding is where Opus 5 is strongest. Run it in a **fresh session** — separating review from authorship matters more than the model tier. |
| **Phase-boundary deep review** | `/code-review ultra` | Multi-agent, you trigger it, billed separately. Use at end of Phase 4 and end of Phase 5. |
| **Chores** | Haiku 4.5 | Commit-message drafting, log triage, one-off scripts, file renames. **Not** for Rust you intend to learn from, and not for anything touching wire format. |

Practical notes:

- **Fast mode (`/fast`)** is worth it when you're sitting there watching a
  tight compile-fix loop and latency is the annoyance. It's the same Opus
  model at higher output speed and premium pricing — not a quality
  downgrade, but not free either. Leave it off for background work.
- **Don't switch models mid-session.** Caches are model-scoped, so a
  switch re-processes the whole context. Pick per session.
- **Where Sonnet 5 is the right call, use it deliberately** — decide at
  slice-planning time and note it in the plan, rather than downgrading
  ad hoc when a session feels expensive.
- Claude Code usage is subscription-based, so the cost lever in practice
  is context size and session count, not per-token price. Two consequences:
  keep sessions scoped to one slice, and don't re-paste documents the
  session can read from disk.

---

## 6. Prompt shapes

Two templates. Keep them in `doc/` or as slash commands so they're
consistent across sessions.

### 6.1 Slice planning prompt

```
Slice: <ID> (see doc/plan.md).

Read doc/plan.md for this slice's scope, requirements, and DoD, then read
doc/specs.md, doc/design.md, doc/code-style.md, doc/rust-style.md, and
doc/decisions.md. Produce a detailed implementation plan for this slice
only, and write it to doc/slices/<id>-<slug>.md.

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
```

### 6.2 Implementation prompt

```
Implement slice <ID> per the approved plan in doc/slices/<id>-<slug>.md.

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
```

---

## 7. Getting started

In order:

1. **Slice 0.1** — `git init`, add the remote, then the workspace
   skeleton *and* the process scaffolding it depends on: `CLAUDE.md`
   (§3.7), `doc/decisions.md` (§3.6), `doc/slices/README.md` (§2.2), and
   `.github/pull_request_template.md` (§2.2). Nothing else in this
   document works without the repo existing, so this one slice is done
   by hand rather than through the loop.
2. **Slice 0.2** — CI, `cargo-deny`, branch protection. Get the gates
   green on an empty workspace before any real code exists, and watch the
   license gate fail closed once.
3. **Phase 1 kickoff, then slices 1.1–1.4** — the conformance corpus,
   built with independent tooling. This is the oracle for everything
   after it, so it is worth taking slowly.
4. **Phase 2 kickoff** — write `doc/rust-style.md` (§3.8), decide whether
   slice 2.1 is hand-written (§4.1), then run 2.1–2.7. This is the
   heaviest phase; expect it to take longer than Phases 0 and 1 combined.
5. **Phase 3 kickoff** — close design.md §8 Q1 as a numbered decision,
   then slices 3.1–3.4, with the lexer and AST written by hand.

Phases 3–4 don't depend on 1–2, so if the corpus stalls on some CBOR
subtlety, switching to the parser is a legitimate unblock rather than a
detour.

---

## 8. Open questions about the process itself

1. Whether Phase 7 (Java) and Phase 8 (C++) should run concurrently in
   separate worktrees. They're independent in the plan, and concurrency
   would compress the schedule — but reviewing two backends in parallel
   against a shared contract is where a single reviewer becomes the
   bottleneck. Decide at Phase 5 close.
2. Whether to adopt a merge queue once CI covers three platforms plus
   three language toolchains, or accept the slower serial merge.
3. Whether generated code is committed to the repo. It affects how much
   REQ-GEN-070's determinism guarantee is worth in practice, and it
   changes what a PR diff looks like. Decide before Phase 5.
