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

## D-005 — Reference CI runner configuration (REQ-NFR-010 artifact)
Date: 2026-08-08 · Closes: slice 0.2 plan §4 Q2, DoD clause 3 · Phase: 0

Decision: Linux (`ubuntu-24.04`) is *the* reference runner REQ-NFR-010's
5-second bar is measured against. Recorded verbatim from the `runner-spec
(ubuntu-24.04)` job of CI run
[31260737102](https://github.com/Polytopic-Lab/lido/actions/runs/31260737102)
(2026-08-08):

```
image: ubuntu24 20260720.247.2
arch: x86_64
cores: 4
memory: 15Gi
rustc 1.97.1 (8bab26f4f 2026-07-14)
binary: rustc
commit-hash: 8bab26f4f68e0e26f0bb7960be334d5b520ea452
commit-date: 2026-07-14
host: x86_64-unknown-linux-gnu
release: 1.97.1
LLVM version: 22.1.6
```

Slice 9.6's measurement assumes the `--release` cargo profile — a
debug-build timing is not meaningful against a 5-second bar — and a *cold*
dependency cache: GitHub-hosted runners provision a fresh VM per job, so
the first `cargo build` in a job is the only cache state this record can
promise reproduces.

The other two matrix legs, informative only:

```
macos-26:   image macos26 20260728.0273.1 · arm64 · 3 cores · 7 GB
windows-2025: image win25-vs2026 20260803.193.1 · AMD64 · 4 cores · ~16 GB
```
(both: `rustc 1.97.1 (8bab26f4f 2026-07-14)`, `LLVM version: 22.1.6`)

Alternatives: recording all three platforms as co-equal references
(rejected — REQ-NFR-010 names a singular reference runner, and three
co-equal numbers could not be violated by a regression that broke only
one); macOS or Windows as the reference (rejected — Linux is the cheapest
and fastest of the three and the one CI will always run, plan §4 Q2).

Rationale: slice 9.6 needs a reproducible figure to measure against, not a
range. Recording the exact image label, core count, and toolchain build
means a 5-second-bar failure three phases from now can be attributed to
either a real regression or a runner change, rather than argued about.

Consequences: if GitHub deprecates the `ubuntu-24.04` label, the bump is
its own PR (same shape as D-001's toolchain-bump consequence), and it gets
a new decision entry that supersedes this one rather than an edit to it.

## D-006 — CI shape: pinned runners, job split, what's not gated yet
Date: 2026-08-08 · Closes: slice 0.2 plan §4 Q1, Q3, Q5, Q8 · Phase: 0

Decision: four parts.

1. **Runner images are pinned by label** — `ubuntu-24.04`, `windows-2025`,
   `macos-26` — not `-latest`.
2. **Five jobs** in `.github/workflows/ci.yml`: `test` (build, test,
   clippy; 3-OS matrix), `fmt` (Linux only), `deny` (`cargo deny check
   licenses bans sources`, Linux only, **required**), `advisories` (`cargo
   deny check advisories`, Linux only, path-filtered to `Cargo.lock`,
   `Cargo.toml`, `**/Cargo.toml`, `deny.toml`, plus `workflow_dispatch`,
   **not required**), and `runner-spec` (3-OS matrix, produces D-005).
   Dependabot alerts are enabled (confirmed via the GitHub API — a 204 on
   `GET /repos/.../vulnerability-alerts`); Dependabot version-update PRs
   are left off.
3. **Every third-party Action is pinned by commit SHA**, not tag or
   branch: `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1`
   (v7.0.1), `EmbarkStudios/cargo-deny-action@3c6349835b2b7b196a839186cb8b78e02f7b5f25`
   (v2.1.1). No toolchain-install action is used — GitHub-hosted runners
   ship `rustup`, which resolves `rust-toolchain.toml` (D-001)
   automatically on the first `cargo`/`rustc` invocation; `rustup show` is
   run as an explicit first step so that resolution happens up front
   rather than inside the first timed command.
4. **Branch protection on `main`**: the 8 non-`advisories` job-legs listed
   above are required status checks (not strict — branches need not be up
   to date); a pull request is required to merge; 0 approvals required;
   administrators are included (no force-push around a broken `main`);
   linear history is required; force-pushes and deletions are disabled on
   `main`.

Alternatives: tracking `-latest` runner images (rejected — the whole point
of D-001 was that `rustfmt`/`clippy` output must not drift underneath CI,
and an unpinned image can rotate that out from under it); one `cargo deny
check` job covering `advisories` too (rejected — ties DoD clause 1, "CI is
green," to an external advisory database's publish schedule rather than to
this repo's own changes); `cargo install cargo-deny --locked` instead of
the Embark action (rejected — minutes of compile time on every PR, against
an action already pinned by SHA).

Rationale: this is D-001's toolchain-pinning argument applied to the rest
of the CI surface — anything that can silently change the pass/fail
verdict underneath a fixed set of source files should be pinned, and the
resulting bump should be its own reviewable PR.

Consequences: a runner-image deprecation, a toolchain bump, or an Action
version bump are each their own PR, expected to carry no code changes.
Branch protection's required-check list does not update itself — renaming
a job or changing the matrix means the list in this entry (and on GitHub)
goes stale until someone updates both by hand. Per plan.md §2's
"Deliberately not created" list: no MSRV job (arrives slice 10.1), no
`no_std` job (slice 2.7), no requirement-coverage check (slice 1.4), no
determinism test (Phase 5), no `-fno-exceptions -fno-rtti` build (Phase
8), no benchmark/throughput job (slice 9.6/9.9), no release/publish
workflow (Phase 10), no merge queue. development.md §3.5 lists `cargo deny
check` unqualified as a required check; this entry's split of
`licenses`/`bans`/`sources` (required) from `advisories` (not required) is
the more precise statement, and development.md should be reconciled to it
in the Phase 0 close docs PR (slice 0.1 plan §5 already flagged that PR for
the `.github/`/`deny.toml` gap in design.md §2; add this to its scope).

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
