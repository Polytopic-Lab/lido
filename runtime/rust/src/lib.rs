//! The Rust runtime support library: CBOR and JSON encode/decode for
//! generated DTOs (design.md §4, REQ-DIST-010).
//!
//! Versioned and distributed independently of the compiler; generated code
//! depends on it and Lido never regenerates it. Empty in slice 0.1; Phase 2
//! builds it.
