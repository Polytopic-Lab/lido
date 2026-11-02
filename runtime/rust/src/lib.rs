//! The Rust runtime support library: CBOR and JSON encode/decode for
//! generated DTOs (design.md §4, REQ-DIST-010).
//!
//! Versioned and distributed independently of the compiler; generated code
//! depends on it and Lido never regenerates it.
//!
//! This crate is `no_std` + `alloc`. The default `std` feature exists for
//! conveniences that need the standard library; the core does not (REQ-RT-110).
//!
//! # What is here (slice 2.1)
//!
//! The error types ([`DecodeError`], [`EncodeError`]) and the path they carry
//! ([`Path`], REQ-RT-065/066). The encoder and decoder traits arrive with them
//! in this slice; the CBOR and JSON implementations follow in 2.2–2.4.

#![no_std]
#![forbid(unsafe_code)]
#![warn(missing_docs)]

extern crate alloc;

mod error;
mod path;

pub use error::{
    DecodeError, DecodeErrorKind, EncodeError, EncodeErrorKind, ErrorContext, Position, ValueKind,
};
pub use path::{Path, PathParseError, PathSegment};
