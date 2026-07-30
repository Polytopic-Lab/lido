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
