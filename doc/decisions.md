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

## D-007 — Conformance corpus: layout, manifest format, and verification tooling
Date: 2026-10-19 · Closes: Phase 1 kickoff (development.md §2.1) · Phase: 1

Decision: six parts.

### 1. Directory layout

`conformance/` at the repository root (design.md §2, REQ-ARCH-060), text
only — no binary fixtures; CBOR is stored as hex:

```
conformance/
├── README.md                  # the format documentation (1.1 DoD clause 1)
├── manifest.schema.json       # JSON Schema 2020-12 for case files
├── index.json                 # explicit list of every case file
├── construct-coverage.json    # specs.md §3 construct -> schema (1.1 DoD clause 2)
├── coverage.json              # REQ-* -> case id (slice 1.4; distinct file)
├── schemas/
│   ├── <name>.cddl
│   └── evolution/<name>/{v1,v2}.cddl      # slice 1.4
├── cases/
│   ├── positive/<name>.json               # slice 1.2
│   ├── negative/<name>.json               # slice 1.3
│   ├── noncanonical/<name>.json           # slice 1.3
│   └── evolution/<name>.json              # slice 1.4
└── tools/
    ├── check_corpus.py        # the self-check; grows slice by slice
    ├── cborcheck.py           # dependency-free canonical-CBOR validator
    └── requirements.txt       # pinned, hashed
```

Cases are grouped by **kind** first and named after their schema, because
kind is the slice boundary (1.2/1.3/1.4) and that keeps each slice's diff
in its own directory. `index.json` lists every case file explicitly and
the self-check asserts index ⇔ directory tree set-equality, so a case file
cannot be silently orphaned or dropped, and the Java and C++ harnesses get
one entry point instead of recursive globbing.

One manifest file per (schema, kind) holding an array of cases — not one
file per case (hundreds of 15-line files) and not one file per schema
(every slice then edits every file).

**`conformance/` holds only the three-runtime wire oracle.** Phase 3's
CDDL *rejection* corpus — unsupported constructs, syntax errors, expected
spans (REQ-CDDL-050/060) — is compiler input consumed by exactly one
language and lives under `crates/lido-cddl/tests/`. The split is by
consumer, not by file type.

### 2. Manifest format: JSON, schema-validated

JSON (not YAML/TOML): every consumer already has a parser, and slice 1.2's
self-check runs under Python's `json` with no dependency. `manifest.schema.json`
is JSON Schema draft 2020-12, itself validated against the 2020-12
metaschema — that is what "validates against its own schema" means in the
1.1 DoD. Case files carry `"$schema": "../../manifest.schema.json"` so
editors validate live.

File envelope:

```json
{ "$schema": "../../manifest.schema.json",
  "manifest_version": 1,
  "schema": "struct_text_keys.cddl",
  "kind": "positive",
  "cases": [ … ] }
```

Positive case record (the shape plan.md 1.1 names; `negative`,
`noncanonical`, and `evolution` are reserved `kind` values whose records
are defined by slices 1.3 and 1.4):

```json
{ "id": "struct_text_keys/basic",
  "root": "Person",
  "description": "three text keys whose canonical order is length-first",
  "requirements": ["REQ-RT-160", "REQ-RT-165"],
  "derivation": "hand-encoded",
  "value": { … },
  "cbor": "a3636167651824646e616d6563416461656d61696c…",
  "json": "{\"age\":36,\"name\":\"Ada\",\"email\":\"a@b.c\"}" }
```

- `id` is `<schema-stem>/<case-name>`, lower snake_case, and is **stable
  for the life of the project** — it is cited by `coverage.json` and by
  test names in three languages, so renaming one silently breaks
  traceability in places CI cannot see.
- `cbor` is lowercase hex, no prefix or separators, and is the
  **canonical** (REQ-RT-160) encoding.
- `json` is the **exact expected JSON text**, stored as a JSON string, in
  compact form (no insignificant whitespace, single line) — not as an
  embedded JSON value, which would lose member order and force the harness
  to re-serialize through the very writer under test.
- `derivation` is one of `rfc8949-appendix-a`, `hand-encoded`, `cbor2`,
  and records where the expected bytes came from. It exists so that
  plan.md Phase 1's "never generated by Lido's own runtime" rule is a
  reviewable field rather than a convention.

### 3. The value model is self-describing, not schema-directed

`value` is the logical DTO value, independent of both wire formats.
**Every value is a JSON object with exactly one member, whose name is a
type tag**:

| Tag | Payload |
|---|---|
| `bool` | JSON `true`/`false` |
| `uint`, `int` | decimal **string** |
| `f16`, `f32`, `f64` | **string**: decimal, C99 hex-float (`0x1.8p+0`), `NaN`, `Infinity`, `-Infinity` |
| `tstr` | JSON string |
| `bstr` | lowercase hex string |
| `null` | JSON `null` |
| `array` | JSON array of values |
| `map` | JSON array of `[key, value]` pairs, key tagged `tstr` or `uint`, in expected wire order |

Self-describing is the load-bearing word: a schema-directed value model
would require the Python self-check to parse CDDL, i.e. to reimplement
Lido's front end in Python before Lido's front end exists. Uniform tagging
also means no member name is ever user data (user keys live inside `map`
pair arrays), so no escaping convention is needed, and the whole model is
checkable by JSON Schema.

Integers and floats are **strings** so that no expected value can be
mangled by a JSON parser's double-precision number handling — which is
precisely the failure REQ-RT-220 exists to prevent, and which would
otherwise corrupt the vectors testing it.

Choice types and enumerations get **no distinct tag**: REQ-RT-360 encodes
a choice as a single-entry map (`map`) and REQ-RT-385 encodes an enum as
its literal, so the value model already expresses both. Absent optional
fields are simply missing from `map`; an explicit null is `{"null":null}` —
which is REQ-RT-330's distinction represented structurally.

### 4. Verification tooling: Python 3 + `cbor2` + `jsonschema`, zero Lido code

`conformance/tools/`, Python 3 with `cbor2` (MIT) and `jsonschema` (MIT),
pinned to exact versions with hashes in `requirements.txt`, installed with
`pip install --require-hashes`, and run by a Linux-only `conformance` CI
job. **The runner's system Python is used** — no `actions/setup-python`:
that would be a fourth pinned thing and a fifth Action to pin by SHA
(D-006 §3), to decouple a version this tooling has no stated requirement
on. The consequence is accepted explicitly: the Python minor version moves
when the `ubuntu-24.04` image moves, so a corpus failure after an image
rotation is attributable to it (D-005's reasoning, same shape). If the
self-check ever depends on a version-sensitive behavior, that is the
moment to add the pin, not before. `uv`/`uv.lock` was considered and set
aside as new tooling for a two-dependency script. Not Rust/`xtask`: an xtask self-check
would live in Lido's own workspace and would likely reach for the same
CBOR crate Phase 2's runtime does, so a bug in that crate would be invisible
to the oracle. Python's `cbor2` is an independent implementation lineage.

Every expected `cbor` value is checked **three ways** from slice 1.2:

1. `cbor2.loads` of the hex equals the declared `value` model;
2. `cbor2.dumps(..., canonical=True)` of that decoded value is
   byte-identical to the stored hex;
3. `cborcheck.py` — a dependency-free structural validator written in this
   repo directly against RFC 8949 §4.2 — confirms definite lengths,
   shortest-form heads, shortest round-tripping floats, and **map key
   order computed over encoded key bytes** (REQ-RT-165).

(3) is not redundant with (2): it is the only check that states REQ-RT-165
as a rule rather than deferring to another library's interpretation of it,
and writing it before any Lido code exists is the point of Phase 1's
ordering (development.md §3.3). Where a case corresponds to an example in
**RFC 8949 Appendix A**, its hex SHALL be transcribed from the RFC and
marked `"derivation": "rfc8949-appendix-a"` — a third ground truth that no
tool in this repo produced.

Python is an **authoring and verification** tool only. The corpus
artifacts are plain text and every language harness reads them natively;
no Lido build, test, or user ever requires a Python interpreter, so
REQ-IMPL-010 and specs.md §13's rationale are untouched.

### 5. Dependency licensing

`cbor2` and `jsonschema` are MIT, satisfying REQ-DEP-020 in spirit, but
they are developer tooling rather than compiler or runtime dependencies
and `cargo deny` cannot see them. Their licenses are verified by hand at
pin time and re-verified at each version bump, as D-002 did for
`serde_json`.

### 6. Formatting

Corpus JSON is 2-space indented, LF, trailing newline, and `check_corpus.py`
has a `--check-format` mode so diffs stay reviewable (development.md §3.4 —
these files are read one diff at a time, forever). `.gitattributes` forces
LF on `conformance/**` so a Windows checkout cannot alter expected text.

Alternatives: cases grouped by schema rather than by kind (rejected —
every Phase 1 slice would then edit every file, and three slices' diffs
would interleave); glob-based discovery instead of `index.json` (rejected
— a dropped file reads as a passing suite); expected JSON stored as an
embedded JSON value (rejected — loses member order and byte-exactness,
and forces re-serialization through the implementation under test); plain
JSON as the input value model (rejected — cannot express `bstr`, `float16`,
NaN, integer map keys, or absent-vs-null, which are exactly the §9.2/§9.7
cases, and makes the expected JSON vector trivially equal to its own
input); a schema-directed value model (rejected — needs a CDDL parser in
Python); a Rust `xtask` self-check (rejected — shares a workspace and
probably a CBOR crate with the implementation it is meant to judge); `cbor2`
round-tripping alone, with no hand-written validator (rejected — proves
agreement with one library, not conformance to RFC 8949 §4.2, and
REQ-RT-165 is the clause most likely to be got wrong by both).

Rationale: the corpus is the only artifact in this project that can say
Lido is *wrong* rather than merely self-consistent (development.md §3.3),
and every decision above is chosen to keep it that way — independent
tooling, provenance recorded per case, canonical form asserted from the
RFC rather than from a library, and a format in which a missing or
weakened vector is a CI failure rather than a smaller test run.

Consequences: `manifest_version` is a compatibility surface for three
language harnesses; bumping it is its own PR and gets a new decision entry.
The `conformance` CI job is **added by slice 1.1 as a non-required check**
and **becomes required when slice 1.2 lands** and gives it teeth — at which
point branch protection and D-006's required-check list are both edited by
hand, since D-006 notes that list does not update itself. A job that is
green over an almost-empty corpus is one people stop reading, so 1.1's PR
demonstrates it failing (a construct uncovered, an index entry removed)
rather than only passing. Case `id`s and the
`construct-coverage.json` construct ids are effectively append-only.
Slice 1.4's requirement-coverage file is `coverage.json`, deliberately a
different name from 1.1's `construct-coverage.json`; they answer different
questions and must not be merged. Phase 3 does not add to `conformance/`.

Storing expected JSON as exact compact text imposed a constraint specs.md
did not state. Rather than let the corpus become the normative home of a
wire-visible rule, a docs PR added **REQ-RT-175** (no insignificant
whitespace on encode; arbitrary whitespace accepted on decode) and
**REQ-RT-177** (JSON member order is the canonical CBOR key order of
REQ-RT-160/165) to specs.md §9.1, ahead of this slice. REQ-RT-177 was a
second gap found while drafting the first: byte-exact JSON comparison
needs a defined member order, and §9.1 defined one only for CBOR. Both
are placed in §9.1 — "Deterministic encoding" — rather than §9.2, whose
subject is values JSON cannot natively express; whitespace and member
order are determinism rules, and §9.1's preamble ("byte-exact conformance
vectors … are only well-defined if encoding is canonical") is their
motivation verbatim. Both were drafted as pure insertions, changing no
existing requirement's meaning.

Pinning Python dependencies adds a third pin class to the
repo (toolchain D-001, runner images D-006, now `requirements.txt`), each
bumped in its own PR.

## D-008 — Enumerations of integer literals are in the §3 core subset
Date: 2026-10-19 · Closes: slice 1.1 plan §4 Q3 · Phase: 1

Decision: specs.md §3's "Enumerations of literal values (e.g. `"red" /
"green" / "blue"`)" admits **both text-string and unsigned-integer
literals**. `Status = 1 / 2 / 3` is a supported enumeration type, not an
unsupported construct under REQ-CDDL-050. The parenthetical in §3 is an
example, not a restriction.

Mixing literal kinds within one enumeration (`"red" / 2`) is **not**
decided here and remains unsupported until something decides it; a parser
encountering one reports an unsupported-construct error (REQ-CDDL-050)
rather than guessing. Negative-integer literals are likewise out until
asked for — §3.1's key rules and §8.1's enum mapping both talk in terms of
unsigned values, and nothing yet needs them.

Alternatives: text literals only (rejected — the restriction appears
nowhere in the normative sentence, only in its example, and would have to
be invented by whoever wrote the parser; integer enums are also the
natural companion to §3.1's integer keys, which exist for exactly the
same payload-size reason on the same constrained links); deferring the
question to Phase 3 (rejected — the corpus authored in slices 1.1–1.2 is
the oracle Phase 3 is later judged against, so an enumeration kind absent
from the corpus is one no backend is ever checked on, and the gap would
surface in Phase 7 or 8 as a missing feature rather than in Phase 3 as a
decision).

Rationale: §3 is the contract REQ-GEN-120 holds all three backends to in
full — "a backend that cannot generate correct code for every construct
in §3 is not a supported backend" — so an ambiguity in §3 is an ambiguity
about what three languages must implement, and leaving it open means three
separate chances to resolve it differently.

Consequences:

- **Corpus** (slice 1.1): `conformance/schemas/enum.cddl` carries both a
  text-literal and an integer-literal enumeration, and the construct
  enumeration splits C-090 into C-090 (text literals) and C-091 (integer
  literals), both quoting the same §3 bullet.
- **Parser** (Phase 3): the grammar must distinguish an enumeration of
  integer literals from two neighbouring constructs it resembles — a
  choice over named types (REQ-CDDL-070), and a numeric range `1..3`
  (§3's range bullet). `1 / 2 / 3` and `1..3` describe overlapping value
  sets but lower to different IR (REQ-CDDL-080's named enumeration vs a
  ranged primitive) and generate different code, so this is a real
  disambiguation and not a parsing nicety.
- **Codegen**: §8.1 maps "enum of literals" to `enum class` / `enum` /
  fieldless `enum` without reference to literal kind, so the mapping
  already covers this; backends carry the literal value as wire metadata
  (REQ-GEN-030) and emit it directly per REQ-RT-385 — an integer-literal
  enum encodes as a CBOR unsigned integer and a JSON number, never as an
  ordinal index, which for integer literals is a distinction that is easy
  to lose because the two frequently coincide. A conformance case where
  the literals are deliberately **not** `0,1,2…` in declaration order is
  therefore required (slice 1.2), or REQ-RT-385 is untested for this kind.
- **Docs**: specs.md §3's enumeration bullet was clarified to admit both
  literal kinds, and to exclude mixed-kind, negative, and floating-point
  literals, by the same Phase 1 kickoff docs PR that added REQ-RT-175/177
  under D-007. The specs are read-only during implementation
  (development.md §3.1), so that edit did not ride along in a slice PR —
  it merged before slice 1.1 branched, which is also why slice 1.2 can
  author vectors against a rule the spec states rather than one only the
  corpus knows.
