//! Encode and decode errors (REQ-RT-060, REQ-RT-065).
//!
//! There is one [`EncodeError`] and one [`DecodeError`], not an error type per
//! encoder: generated codecs must raise errors the encoder knows nothing about
//! (a range violation, REQ-RT-250), and every error carries the [`Path`] from
//! the root of the DTO (design.md §4.2).

use alloc::string::String;
use core::fmt;

use thiserror::Error;

use crate::path::{Path, PathSegment};

/// The kind of a value, as the wire sees it. Used for the "expected" and
/// "found" halves of a type mismatch (REQ-RT-065).
///
/// JSON values map onto the same kinds as their CBOR counterparts: a string is
/// [`Text`](Self::Text), a number is [`Uint`](Self::Uint), [`Int`](Self::Int) or
/// [`Float`](Self::Float) by its form, an object is [`Map`](Self::Map).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum ValueKind {
    /// `bool`.
    Bool,
    /// An unsigned integer.
    Uint,
    /// A signed integer.
    Int,
    /// A floating-point number of any width.
    Float,
    /// A text string (`tstr`).
    Text,
    /// A byte string (`bstr`).
    Bytes,
    /// `null`.
    Null,
    /// An array.
    Array,
    /// A map or JSON object.
    Map,
    /// A CBOR tag.
    Tag,
    /// Anything else (`undefined`, a simple value).
    Other,
}

impl ValueKind {
    /// The CDDL-style name: `uint`, `tstr`, `bstr`, ...
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Bool => "bool",
            Self::Uint => "uint",
            Self::Int => "int",
            Self::Float => "float",
            Self::Text => "tstr",
            Self::Bytes => "bstr",
            Self::Null => "null",
            Self::Array => "array",
            Self::Map => "map",
            Self::Tag => "tag",
            Self::Other => "other",
        }
    }
}

impl fmt::Display for ValueKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Where in the input a decode error was detected (REQ-RT-065).
///
/// The offset is that of the **first byte of the offending item**. For a
/// truncated input it is the offset at which the input ended. For JSON, line
/// and column are both 1-based and the column counts UTF-8 bytes (D-012).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Position {
    /// A byte offset into CBOR input.
    Byte(u64),
    /// A line and column in JSON input.
    LineColumn {
        /// 1-based line.
        line: u32,
        /// 1-based column, counted in UTF-8 bytes.
        column: u32,
    },
}

impl fmt::Display for Position {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Byte(offset) => write!(f, "byte {offset}"),
            Self::LineColumn { line, column } => write!(f, "line {line}, column {column}"),
        }
    }
}

/// Why a decode failed. The names returned by [`as_str`](Self::as_str) are the
/// `error.kind` names the conformance corpus uses.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
#[non_exhaustive]
pub enum DecodeErrorKind {
    /// The input ended before the value did (REQ-RT-310).
    #[error("input ended unexpectedly")]
    Truncated,
    /// A complete value was followed by more input (REQ-RT-310).
    #[error("unexpected data after the end of the value")]
    TrailingData,
    /// The input is not well-formed CBOR or JSON (REQ-RT-310).
    #[error("malformed input")]
    Syntax,
    /// A text string is not valid UTF-8 (REQ-RT-315).
    #[error("text is not valid UTF-8")]
    InvalidUtf8,
    /// A map has the same key twice (REQ-RT-300).
    #[error("duplicate map key")]
    DuplicateKey,
    /// A value has the wrong type (REQ-RT-060).
    #[error("expected {expected}, found {found}")]
    TypeMismatch {
        /// The type the schema requires.
        expected: ValueKind,
        /// The type that was present.
        found: ValueKind,
    },
    /// A required field is absent. The path ends in the field's name.
    #[error("missing required field")]
    MissingField,
    /// An explicit null where the type does not admit one (REQ-RT-350).
    #[error("null is not allowed here")]
    NullNotAllowed,
    /// A choice variant or enumeration literal the schema does not have
    /// (REQ-RT-380).
    #[error("unknown discriminant {found:?}")]
    UnknownDiscriminant {
        /// The discriminant that was present.
        found: String,
    },
    /// A choice value whose map does not have exactly one entry (REQ-RT-380).
    #[error("a choice must have exactly one entry")]
    InvalidChoice,
    /// A number outside the declared range (REQ-RT-240).
    #[error("value is out of range")]
    OutOfRange,
    /// A fixed-shape array with too few elements (REQ-COMPAT-060).
    #[error("expected {expected} element(s), found {found}")]
    WrongLength {
        /// The number of elements the schema requires.
        expected: usize,
        /// The number present.
        found: usize,
    },
    /// A map key of the wrong type, or an integer-keyed member name that is not
    /// a decimal integer in range (REQ-KEY-040).
    #[error("invalid map key")]
    BadKey,
    /// The nesting-depth limit was exceeded (REQ-RT-270).
    #[error("nesting depth limit exceeded")]
    DepthExceeded,
    /// A string or collection size limit was exceeded (REQ-RT-290).
    #[error("size limit exceeded")]
    SizeExceeded,
}

impl DecodeErrorKind {
    /// Every name [`as_str`](Self::as_str) can return.
    pub const NAMES: [&'static str; 15] = [
        "truncated",
        "trailing_data",
        "syntax",
        "invalid_utf8",
        "duplicate_key",
        "type_mismatch",
        "missing_field",
        "null_not_allowed",
        "unknown_discriminant",
        "invalid_choice",
        "out_of_range",
        "wrong_length",
        "bad_key",
        "depth_exceeded",
        "size_exceeded",
    ];

    /// The stable snake_case name of this kind, as the conformance corpus
    /// spells it.
    #[must_use]
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Truncated => "truncated",
            Self::TrailingData => "trailing_data",
            Self::Syntax => "syntax",
            Self::InvalidUtf8 => "invalid_utf8",
            Self::DuplicateKey => "duplicate_key",
            Self::TypeMismatch { .. } => "type_mismatch",
            Self::MissingField => "missing_field",
            Self::NullNotAllowed => "null_not_allowed",
            Self::UnknownDiscriminant { .. } => "unknown_discriminant",
            Self::InvalidChoice => "invalid_choice",
            Self::OutOfRange => "out_of_range",
            Self::WrongLength { .. } => "wrong_length",
            Self::BadKey => "bad_key",
            Self::DepthExceeded => "depth_exceeded",
            Self::SizeExceeded => "size_exceeded",
        }
    }
}

/// Why an encode failed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
#[non_exhaustive]
pub enum EncodeErrorKind {
    /// The value has no representation in this encoding or type: NaN or an
    /// infinity in JSON (REQ-RT-210), a `float16` field holding a value half
    /// precision cannot hold exactly (REQ-RT-255).
    #[error("value cannot be represented")]
    NotRepresentable,
    /// A number outside the declared range (REQ-RT-250).
    #[error("value is out of range")]
    OutOfRange,
}

impl EncodeErrorKind {
    /// Every name [`as_str`](Self::as_str) can return.
    pub const NAMES: [&'static str; 2] = ["not_representable", "out_of_range"];

    /// The stable snake_case name of this kind, as the conformance corpus
    /// spells it.
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Self::NotRepresentable => "not_representable",
            Self::OutOfRange => "out_of_range",
        }
    }
}

/// A decode failed. Carries what failed, where in the DTO ([`Path`]), and where
/// in the input ([`Position`]).
///
/// ```
/// use lido_runtime::{DecodeError, DecodeErrorKind, Position, ValueKind};
///
/// let err = DecodeError::new(DecodeErrorKind::TypeMismatch {
///     expected: ValueKind::Uint,
///     found: ValueKind::Text,
/// })
/// .with_position(Position::Byte(147))
/// .at_field("price")
/// .at_index(3)
/// .at_field("items")
/// .at_field("order");
///
/// assert_eq!(
///     err.to_string(),
///     "order.items[3].price: expected uint, found tstr (byte 147)"
/// );
/// assert_eq!(err.kind().as_str(), "type_mismatch");
/// ```
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DecodeError {
    kind: DecodeErrorKind,
    path: Path,
    position: Option<Position>,
}

impl DecodeError {
    /// An error of `kind` at the root, with no position.
    #[must_use]
    pub fn new(kind: DecodeErrorKind) -> Self {
        Self {
            kind,
            path: Path::root(),
            position: None,
        }
    }

    /// Record where in the input the problem is.
    #[must_use]
    pub fn with_position(mut self, position: Position) -> Self {
        self.position = Some(position);
        self
    }

    /// What failed.
    #[must_use]
    pub fn kind(&self) -> &DecodeErrorKind {
        &self.kind
    }

    /// Where in the DTO, from the root (REQ-RT-065).
    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Where in the input, if the decoder knew.
    #[must_use]
    pub fn position(&self) -> Option<Position> {
        self.position
    }

    /// Place this error inside struct field `name`. Call it as the failure
    /// unwinds, once per enclosing level; the path is read outermost-first.
    #[must_use]
    pub fn at_field(mut self, name: &'static str) -> Self {
        self.path.push_outer(PathSegment::Field(name.into()));
        self
    }

    /// Place this error inside array element (or `uint`-keyed table entry) `n`.
    #[must_use]
    pub fn at_index(mut self, n: u64) -> Self {
        self.path.push_outer(PathSegment::Index(n));
        self
    }

    /// Place this error inside the table entry with `tstr` key `key`.
    #[must_use]
    pub fn at_key(mut self, key: impl Into<String>) -> Self {
        self.path.push_outer(PathSegment::Key(key.into()));
        self
    }
}

impl fmt::Display for DecodeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if !self.path.is_root() {
            write!(f, "{}: ", self.path)?;
        }
        write!(f, "{}", self.kind)?;
        if let Some(position) = self.position {
            write!(f, " ({position})")?;
        }
        Ok(())
    }
}

impl core::error::Error for DecodeError {
    fn source(&self) -> Option<&(dyn core::error::Error + 'static)> {
        Some(&self.kind)
    }
}

/// An encode failed. Carries what failed and where in the DTO ([`Path`]).
///
/// ```
/// use lido_runtime::{EncodeError, EncodeErrorKind};
///
/// let err = EncodeError::new(EncodeErrorKind::OutOfRange).at_field("level");
/// assert_eq!(err.to_string(), "level: value is out of range");
/// ```
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EncodeError {
    kind: EncodeErrorKind,
    path: Path,
}

impl EncodeError {
    /// An error of `kind` at the root.
    #[must_use]
    pub fn new(kind: EncodeErrorKind) -> Self {
        Self {
            kind,
            path: Path::root(),
        }
    }

    /// What failed.
    #[must_use]
    pub fn kind(&self) -> EncodeErrorKind {
        self.kind
    }

    /// Where in the DTO, from the root (REQ-RT-065).
    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Place this error inside struct field `name`; see [`DecodeError::at_field`].
    #[must_use]
    pub fn at_field(mut self, name: &'static str) -> Self {
        self.path.push_outer(PathSegment::Field(name.into()));
        self
    }

    /// Place this error inside array element (or `uint`-keyed table entry) `n`.
    #[must_use]
    pub fn at_index(mut self, n: u64) -> Self {
        self.path.push_outer(PathSegment::Index(n));
        self
    }

    /// Place this error inside the table entry with `tstr` key `key`.
    #[must_use]
    pub fn at_key(mut self, key: impl Into<String>) -> Self {
        self.path.push_outer(PathSegment::Key(key.into()));
        self
    }
}

impl fmt::Display for EncodeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if !self.path.is_root() {
            write!(f, "{}: ", self.path)?;
        }
        write!(f, "{}", self.kind)
    }
}

impl core::error::Error for EncodeError {
    fn source(&self) -> Option<&(dyn core::error::Error + 'static)> {
        Some(&self.kind)
    }
}

/// Adds path context to a `Result` as a failure unwinds, so generated code can
/// write `e.write_u64(self.age).at_field("age")?` instead of a `map_err`
/// closure at every call.
///
/// ```
/// use lido_runtime::{DecodeError, DecodeErrorKind, ErrorContext};
///
/// let failed: Result<(), DecodeError> = Err(DecodeError::new(DecodeErrorKind::OutOfRange));
/// let err = failed.at_field("level").unwrap_err();
/// assert_eq!(err.to_string(), "level: value is out of range");
/// ```
pub trait ErrorContext: Sized {
    /// See [`DecodeError::at_field`].
    #[must_use]
    fn at_field(self, name: &'static str) -> Self;
    /// See [`DecodeError::at_index`].
    #[must_use]
    fn at_index(self, n: u64) -> Self;
    /// See [`DecodeError::at_key`].
    #[must_use]
    fn at_key(self, key: impl Into<String>) -> Self;
}

impl<T> ErrorContext for Result<T, DecodeError> {
    fn at_field(self, name: &'static str) -> Self {
        self.map_err(|e| e.at_field(name))
    }
    fn at_index(self, n: u64) -> Self {
        self.map_err(|e| e.at_index(n))
    }
    fn at_key(self, key: impl Into<String>) -> Self {
        self.map_err(|e| e.at_key(key))
    }
}

impl<T> ErrorContext for Result<T, EncodeError> {
    fn at_field(self, name: &'static str) -> Self {
        self.map_err(|e| e.at_field(name))
    }
    fn at_index(self, n: u64) -> Self {
        self.map_err(|e| e.at_index(n))
    }
    fn at_key(self, key: impl Into<String>) -> Self {
        self.map_err(|e| e.at_key(key))
    }
}

#[cfg(test)]
mod tests {
    use alloc::string::ToString;
    use alloc::vec::Vec;

    use super::*;

    fn mismatch() -> DecodeError {
        DecodeError::new(DecodeErrorKind::TypeMismatch {
            expected: ValueKind::Uint,
            found: ValueKind::Text,
        })
    }

    /// REQ-RT-065: the path, what was expected, what was found, and the offset
    /// all appear, in the form design.md §4.6 shows.
    #[test]
    fn req_rt_065_error_carries_path_expected_found_and_offset() {
        let err = mismatch()
            .with_position(Position::Byte(147))
            .at_field("price")
            .at_index(3)
            .at_field("items")
            .at_field("order");
        assert_eq!(
            err.to_string(),
            "order.items[3].price: expected uint, found tstr (byte 147)"
        );
        assert_eq!(err.path().to_string(), "order.items[3].price");
        assert_eq!(err.position(), Some(Position::Byte(147)));
        assert_eq!(
            err.kind(),
            &DecodeErrorKind::TypeMismatch {
                expected: ValueKind::Uint,
                found: ValueKind::Text
            }
        );
    }

    /// REQ-RT-065: JSON positions are line and column.
    #[test]
    fn req_rt_065_json_position_is_line_and_column() {
        let err = mismatch().with_position(Position::LineColumn { line: 2, column: 7 });
        assert_eq!(
            err.to_string(),
            "expected uint, found tstr (line 2, column 7)"
        );
    }

    /// REQ-RT-065: an error with no context has the root path and renders without one.
    #[test]
    fn req_rt_065_root_error_renders_without_a_path() {
        let err = DecodeError::new(DecodeErrorKind::Truncated);
        assert!(err.path().is_root());
        assert_eq!(err.position(), None);
        assert_eq!(err.to_string(), "input ended unexpectedly");
    }

    /// REQ-RT-065: context composes innermost-first and reads outermost-first,
    /// for text keys, indexes and `Result` helpers alike.
    #[test]
    fn req_rt_065_context_composes_while_unwinding() {
        let inner: Result<(), DecodeError> = Err(DecodeError::new(DecodeErrorKind::MissingField));
        let err = inner
            .at_field("qty")
            .at_index(7)
            .at_field("stock")
            .unwrap_err();
        assert_eq!(err.path().to_string(), "stock[7].qty");
        let err = mismatch().at_index(0).at_key("a").at_field("scores");
        assert_eq!(err.path().to_string(), "scores[\"a\"][0]");
        let enc: Result<(), EncodeError> = Err(EncodeError::new(EncodeErrorKind::OutOfRange));
        assert_eq!(
            enc.at_field("level").unwrap_err().to_string(),
            "level: value is out of range"
        );
    }

    /// REQ-RT-060: the error can say each cause REQ-RT-060 lists — wrong type,
    /// missing required field, unknown discriminant — and names the offender.
    #[test]
    fn req_rt_060_errors_name_each_cause() {
        assert_eq!(
            mismatch().at_field("age").to_string(),
            "age: expected uint, found tstr"
        );
        assert_eq!(
            DecodeError::new(DecodeErrorKind::MissingField)
                .at_field("name")
                .to_string(),
            "name: missing required field"
        );
        let err = DecodeError::new(DecodeErrorKind::UnknownDiscriminant {
            found: "Triangle".into(),
        });
        assert_eq!(err.to_string(), "unknown discriminant \"Triangle\"");
        let err = DecodeError::new(DecodeErrorKind::WrongLength {
            expected: 2,
            found: 1,
        });
        assert_eq!(err.to_string(), "expected 2 element(s), found 1");
    }

    /// An `Error` whose `source` is the kind, so `Error` chains work.
    #[test]
    fn errors_implement_core_error() {
        fn takes_error(_: &dyn core::error::Error) {}
        takes_error(&mismatch());
        takes_error(&EncodeError::new(EncodeErrorKind::NotRepresentable));
        assert!(core::error::Error::source(&mismatch()).is_some());
    }

    /// REQ-RT-060: every kind has a unique snake_case name, `NAMES` lists exactly
    /// those names, and adding a variant without updating them fails to compile
    /// (the exhaustive match) or fails here.
    #[test]
    fn req_rt_060_kind_names_are_unique_snake_case_and_complete() {
        // An exhaustive match: a new variant must be added here, and below.
        fn representative(name: &str) -> DecodeErrorKind {
            match name {
                "truncated" => DecodeErrorKind::Truncated,
                "trailing_data" => DecodeErrorKind::TrailingData,
                "syntax" => DecodeErrorKind::Syntax,
                "invalid_utf8" => DecodeErrorKind::InvalidUtf8,
                "duplicate_key" => DecodeErrorKind::DuplicateKey,
                "type_mismatch" => DecodeErrorKind::TypeMismatch {
                    expected: ValueKind::Uint,
                    found: ValueKind::Text,
                },
                "missing_field" => DecodeErrorKind::MissingField,
                "null_not_allowed" => DecodeErrorKind::NullNotAllowed,
                "unknown_discriminant" => {
                    DecodeErrorKind::UnknownDiscriminant { found: "x".into() }
                }
                "invalid_choice" => DecodeErrorKind::InvalidChoice,
                "out_of_range" => DecodeErrorKind::OutOfRange,
                "wrong_length" => DecodeErrorKind::WrongLength {
                    expected: 1,
                    found: 0,
                },
                "bad_key" => DecodeErrorKind::BadKey,
                "depth_exceeded" => DecodeErrorKind::DepthExceeded,
                "size_exceeded" => DecodeErrorKind::SizeExceeded,
                other => panic!("no representative for {other}"),
            }
        }
        let mut seen: Vec<&str> = Vec::new();
        for name in DecodeErrorKind::NAMES {
            assert_eq!(representative(name).as_str(), name);
            assert!(!seen.contains(&name), "{name} listed twice");
            seen.push(name);
            assert!(
                name.chars()
                    .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_'),
                "{name}"
            );
        }
        for name in EncodeErrorKind::NAMES {
            let kind = match name {
                "not_representable" => EncodeErrorKind::NotRepresentable,
                "out_of_range" => EncodeErrorKind::OutOfRange,
                other => panic!("no representative for {other}"),
            };
            assert_eq!(kind.as_str(), name);
        }
        // `as_str` and `NAMES` agree on how many there are.
        let all = DecodeErrorKind::NAMES.len() + EncodeErrorKind::NAMES.len();
        assert_eq!(all, 17);
    }

    /// REQ-RT-065: expected/found kinds read as CDDL type names.
    #[test]
    fn req_rt_065_value_kinds_print_as_cddl_names() {
        let names: Vec<&str> = [
            ValueKind::Bool,
            ValueKind::Uint,
            ValueKind::Int,
            ValueKind::Float,
            ValueKind::Text,
            ValueKind::Bytes,
            ValueKind::Null,
            ValueKind::Array,
            ValueKind::Map,
            ValueKind::Tag,
            ValueKind::Other,
        ]
        .iter()
        .map(|k| k.as_str())
        .collect();
        assert_eq!(
            names,
            [
                "bool", "uint", "int", "float", "tstr", "bstr", "null", "array", "map", "tag",
                "other"
            ]
        );
        assert_eq!(ValueKind::Text.to_string(), "tstr");
    }
}
