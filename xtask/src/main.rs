//! Project automation — the [cargo-xtask] pattern (design.md §2).
//!
//! Not part of the compiler pipeline, not published, and never a
//! dependency of anything under `crates/` or `runtime/`. Its only task in
//! slice 0.1 is hosting `tests/workspace_layout.rs`; the `cargo xtask`
//! alias arrives with the first task that must run outside `cargo test`.
//!
//! [cargo-xtask]: https://github.com/matklad/cargo-xtask

fn main() {}
