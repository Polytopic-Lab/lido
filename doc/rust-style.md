# Rust style for Lido's own code

> Process document, not normative. It is the checklist for the self-review
> step of each slice (`doc/prompts/slice-implement.md`). Where it and a
> `REQ-*` requirement disagree, the requirement wins.

This governs the Rust that Lido is **written in**: the compiler crates, the
runtime library, `xtask`. It does not govern **generated** code, whose style is
`doc/code-style.md`; keep the two apart.

It is deliberately short. Add a rule when review finds the same mistake twice,
and say which mistake in the commit that adds it. Prefer a clippy lint to a
sentence here whenever a lint exists.

## Errors

- Library errors are enums with `thiserror`, not `String`, `Box<dyn Error>` or
  `anyhow`. A variant carries the data a caller needs (REQ-RT-065: path,
  expected, found, offset), not a pre-formatted message.
- No `unwrap()`, `expect()`, `panic!`, `unreachable!` or unchecked indexing
  (`v[i]`, `&s[a..b]`) in library code. Input can be hostile (REQ-RT-310), so a
  panic on input is a bug, not an assertion. Use `get`, `?`, and `checked_*`
  arithmetic. `expect()` with an invariant message is allowed only where the
  invariant is established a few lines above, and the comment says where.
- Tests, `main`, and `xtask` may `unwrap()`.

## Safety

- No `unsafe` in the runtime (REQ-PERF-070). Elsewhere the default is the
  same: each crate has `#![forbid(unsafe_code)]`, and removing it is a decision
  for `doc/decisions.md`, not a line in a diff.
- No hand-rolled float formatting or parsing, and no hand-written SIMD, in the
  runtime (REQ-PERF-070). Use a dependency (REQ-RT-100).

## Ownership

- Take `&str`, `&[u8]`, `&T` in parameters unless the function must own the
  value. Return owned values from public APIs (REQ-PERF-060: DTOs never borrow
  from the input).
- Every `.clone()` in a path the benchmarks will exercise (encode, decode, key
  dispatch) needs a one-line reason. Elsewhere it is fine when it is clearer.
- `Rc`, `Arc`, `RefCell` and `Mutex` need a comment saying why the data's shape
  requires them. The core must not depend on threads (REQ-RT-130).

## Types

- Newtypes, not bare integers or strings, for things that are easy to confuse:
  wire keys, discriminants, byte offsets, source spans, schema names.
- An enum, not `Vec<String>`, `bool` flags, or magic strings, for a closed set
  of cases. Match exhaustively; no wildcard arm that would swallow a variant
  added later unless it says why.

## Dependencies

- Prefer `core`/`alloc` paths over `std` in the runtime so slice 2.7 (`no_std`)
  is a flag, not a rewrite. Anything needing `std` goes behind the `std` feature.
- A new dependency is a decision: it must pass `cargo deny` (REQ-DEP-020), be
  justified in the PR body, and be the smallest thing that does the job
  (REQ-RT-100).

## Lints and attributes

- `cargo clippy --all-targets -- -D warnings` is a required check. Fix the
  warning. If a lint is wrong here, use `#[expect(lint, reason = "…")]` on the
  smallest item, never a module- or crate-level `#[allow]`.
- Public items have a doc comment that says what, not how; `# Errors` when the
  function returns `Result`. `#[must_use]` on values whose being dropped is a
  bug (builders, pure constructors, anything returned instead of mutated).
- A function that does not fit on one screen (roughly 60 lines) is a prompt to
  split it, not a rule.

## Tests

- Every test names the `REQ-*` it covers, in its name or a doc comment
  (CLAUDE.md, non-negotiable 3), for example `req_rt_165_key_order_is_length_first`.
- Conformance-driven tests read the corpus under `conformance/` and never
  hand-copy a vector's bytes into Rust source.

## Naming and layout

- Follow the Rust API Guidelines for names (`as_`/`to_`/`into_`, `iter`/
  `into_iter`, no `get_` prefix on getters).
- One concept per module; `lib.rs` re-exports the public surface and nothing
  else. A module that wants a section comment banner wants to be two modules.
