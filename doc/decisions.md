# Lido — Decision Log

A document of record. **Append-only:** entries are never edited or deleted.
A decision that turns out wrong gets a *new* entry that supersedes the old
one by number, and the old entry gains a "Superseded by D-nnn" line — so the
reasoning that was current at the time survives.

Numbering is a single sequence, `D-001` upward, in the order decisions
close — not grouped by phase. Cite the number from code comments, commit
messages, and PR bodies.

Entry format (development.md §3.6):

```markdown
## D-nnn — Short title
Date: YYYY-MM-DD · Closes: <where the question was open> · Phase: <n>

Decision: …
Alternatives: …
Rationale: …
Consequences: …
```

The point is not documentation for its own sake. It is that a session three
phases from now, which has never seen the reasoning, will otherwise
re-derive a *different* answer and quietly implement it.

design.md §8's four open questions, specs.md §16's six, and code-style.md's
four are migrated into this log as they close.

---

## D-001 — Toolchain pinned to Rust 1.97.1
Date: 2026-07-29 · Closes: slice 0.1 plan §4 Q1 · Phase: 0

Decision: `rust-toolchain.toml` pins `channel = "1.97.1"` — an exact
three-part version — with `components = ["rustfmt", "clippy"]` and
`profile = "minimal"`. `[workspace.package]` sets
`rust-version = "1.97.1"`. No `targets` key.

Alternatives: `channel = "stable"` (rejected — REQ-NFR-030 requires pinning
to specific versions rather than tracking current stable); pinning the
locally installed 1.92.0 (rejected — five releases behind on day one, which
defers the bump into Phase 2 where lint churn would land on top of real
code); a lower `rust-version` than the pin (deferred, see below).

Rationale: REQ-NFR-030 pins the *edition* (2021), and recent Rust defaults
new crates to edition 2024, so the edition must be set explicitly regardless.
The compiler pin matters less for compilation than for `rustfmt` and
`clippy`, whose output changes between releases: it is what makes
`cargo fmt --check` and `cargo clippy -- -D warnings` agree across the three
CI platforms from slice 0.2 onward.

Consequences: a toolchain bump is its own PR, expected to carry fmt and
clippy churn, and is never folded into a feature slice. `rust-version` equal
to the pin is self-enforcing but rises with every bump; `lido-runtime`'s MSRV
is the one that will matter to consumers (REQ-RT-110 targets lag stable), so
it is set independently and below the pin when that crate is published in
slice 10.1 — which will need an MSRV CI job and that one crate *not*
inheriting `rust-version.workspace`. `targets` is deferred to slice 2.7,
which owns the `no_std` job and the choice of bare-metal target.

## D-002 — `xtask` hosts project automation and the workspace-layout test
Date: 2026-07-29 · Closes: slice 0.1 plan §4 Q4 · Phase: 0

Decision: a dedicated `xtask` crate at the repository root, `publish =
false`, inheriting `edition`/`license` from `[workspace.package]`. It hosts
`xtask/tests/workspace_layout.rs`, with `serde_json` as a dev-dependency for
parsing `cargo metadata` output.

Alternatives: `crates/lido-cli/tests/` (rejected — makes the product CLI the
accidental owner of build tooling, which gets harder to unwind with every
task added); making the workspace root a real package rather than virtual
(rejected — changes the shape design.md §2 shows); substring matching on
`cargo metadata` output instead of `serde_json` (rejected — cannot reliably
attribute a `license` field to a package).

Rationale: a virtual workspace root cannot host `tests/`, so the DoD check
needs a host package. `xtask` is the standard Rust home for project
automation and the workspace-layout check is the first of several such tasks.

Consequences: design.md §2 names the crate and states that nothing under
`crates/` or `runtime/` may depend on it. `EXPECTED_PACKAGES` in the layout
test is 9 entries including `"xtask"`, because that assertion is exact set
equality. The check stays an integration test rather than a `cargo xtask`
subcommand, so `cargo test` alone satisfies the slice DoD. No
`.cargo/config.toml` alias yet — `[alias] xtask = "run --package xtask --"`
is added by the first slice that needs `cargo xtask <cmd>` invoked outside
`cargo test`. `serde_json` (MIT/Apache-2.0, satisfies REQ-DEP-020) lands one
slice before the `cargo deny` gate exists, so its license was verified by
hand.

## D-003 — `Cargo.lock` is committed
Date: 2026-07-29 · Closes: slice 0.1 plan §4 Q6 · Phase: 0

Decision: `Cargo.lock` is tracked in git.

Alternatives: gitignoring it, conventional for library-only workspaces.

Rationale: the workspace produces a binary (`lido-cli`), which is the
conventional case for committing the lockfile, and both slice 0.2's
`cargo deny check` and CI build reproducibility depend on it.

Consequences: it shapes every future PR diff — dependency changes are
visible and reviewable rather than implicit.

## D-004 — Version follows semver over a defined surface; tags mark version changes
Date: 2026-07-29 · Closes: process gap raised after slice 0.1 · Phase: 0

Decision: four parts.

1. **One version for the workspace.** `[workspace.package].version`,
   inherited by all nine members, is the single number. It moves only in a
   PR that changes the *versioned surface*, and by the amount semver
   dictates for that change — not on a per-PR or per-phase cadence.
2. **The versioned surface** is: the public Rust API of the crates that
   ship (`lido-runtime`, `lido-cli`); the CLI interface (flags, exit codes,
   the stdout/stderr contract); the shape of generated code; and the wire
   format. A change outside all four — an internal refactor, a test, a
   document, CI — carries no version change. Through Phase 4 that is most
   PRs.
3. **Pre-1.0 the minor is the compatibility axis**, because that is what
   Cargo's resolver treats as breaking while the major is 0. So until
   1.0: breaking → minor (`0.1.0` → `0.2.0`); additive or fix → patch
   (`0.1.0` → `0.1.1`); major stays 0. `1.0.0` is cut at Phase 10 with the
   first published artifacts, after which the usual mapping applies.
4. **Tags mark version changes and nothing else.** After merging a PR that
   moved the version, `main` gets an annotated tag (`git tag -a v0.1.1`)
   at that merge commit. PRs that don't move the version aren't tagged.

Alternatives: a bump and a tag on every merged PR (rejected — the version
is workspace-inherited, so every bump touches `Cargo.toml` and
`Cargo.lock` for all nine members: a guaranteed conflict between any two
in-flight branches and a line of noise in every review, in exchange for a
number no consumer can see before slice 10.2, when the merge commit and PR
number already identify the state); version keyed to plan coordinates,
minor = phase and patch = slice (rejected — self-documenting, but silent
about compatibility, which is the only thing a version is ever read for,
and with nowhere to put a fix PR that isn't a slice); tagging only at
phase close (rejected — ties the number to the calendar rather than to the
change, so a wire-format break mid-phase would ship untagged).

Rationale: the version is not bookkeeping here — it is stamped into
generated output (REQ-GEN-080), and REQ-GEN-195 puts that stamp in a
single per-language manifest specifically so that upgrading Lido does not
produce a diff touching every generated file in a downstream project. A
version that increments on every merge turns that stamp into a build
counter and spends what REQ-GEN-195 buys. Tying the number to the change
keeps it meaningful. Semver is also what Cargo's resolver acts on from
slice 10.2 onward, so the habit is cheaper to establish before publication
than to retrofit at it.

Consequences: every PR states its semver impact in its body (PR template
§1), which makes the bump an explicit judgement rather than an omission —
"none" is the expected answer for most of Phases 0–4. Pre-1.0, a run of
breaking changes moves the minor quickly (`0.2`, `0.3` within one phase);
that is the scheme working, not instability. Until slice 10.2 the surface
has no external consumers, so each classification is a judgement with
nothing external to check it against; the value is the habit and the
record. The REQ-GEN-190 runtime API version and the REQ-IR-050 IR schema
version are *separate* numbers with their own compatibility rules and are
not slaved to this one. Slice 10.7 supersedes this entry for published
artifacts: it owns whether the CLI and the three runtime libraries version
in lockstep, and the single workspace version assumes they do — which 10.7
may reverse.
