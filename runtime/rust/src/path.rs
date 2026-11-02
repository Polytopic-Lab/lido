//! The path from the root of a DTO to a value, as REQ-RT-066 writes it.

use alloc::borrow::Cow;
use alloc::string::String;
use alloc::vec::Vec;
use core::fmt;
use core::str::FromStr;

use thiserror::Error;

/// One step of a [`Path`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PathSegment {
    /// A struct field, by its name as written in the schema (not the generated
    /// identifier), or by its decimal key for an integer-keyed field. A choice
    /// variant's discriminant is written the same way.
    Field(Cow<'static, str>),
    /// An array element (zero-based), or a table entry with a `uint` key.
    Index(u64),
    /// A table entry with a `tstr` key.
    Key(String),
}

/// The path from the root of the DTO to the offending value (REQ-RT-065).
///
/// REQ-RT-066 fixes the written form: the root is the empty path, `.` joins
/// field segments, array elements and table entries are `[n]` or `["key"]`
/// attached with no preceding `.`.
///
/// A path is built on the way *out* of a failed call, so segments are added
/// outermost-last; that costs nothing on the success path.
///
/// ```
/// use lido_runtime::{Path, PathSegment};
///
/// let path: Path = "items[2].price".parse()?;
/// assert_eq!(path.segments().count(), 3);
/// assert_eq!(path.to_string(), "items[2].price");
/// assert!(matches!(path.segments().next(), Some(PathSegment::Field(f)) if f == "items"));
/// # Ok::<(), lido_runtime::PathParseError>(())
/// ```
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Path {
    /// Innermost segment first: the order in which failures unwind.
    inner_first: Vec<PathSegment>,
}

impl Path {
    /// The root: the empty path.
    #[must_use]
    pub fn root() -> Self {
        Self::default()
    }

    /// Whether this is the root.
    #[must_use]
    pub fn is_root(&self) -> bool {
        self.inner_first.is_empty()
    }

    /// Add a segment *outside* the existing ones, as a failure unwinds one
    /// level.
    pub fn push_outer(&mut self, segment: PathSegment) {
        self.inner_first.push(segment);
    }

    /// The segments, outermost first.
    pub fn segments(&self) -> impl Iterator<Item = &PathSegment> {
        self.inner_first.iter().rev()
    }
}

impl fmt::Display for Path {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        for (i, segment) in self.segments().enumerate() {
            match segment {
                PathSegment::Field(name) if i == 0 => f.write_str(name)?,
                PathSegment::Field(name) => write!(f, ".{name}")?,
                PathSegment::Index(n) => write!(f, "[{n}]")?,
                PathSegment::Key(key) => {
                    f.write_str("[")?;
                    write_json_string(f, key)?;
                    f.write_str("]")?;
                }
            }
        }
        Ok(())
    }
}

/// A string escaped as REQ-RT-179 requires: only `"`, `\` and U+0000–U+001F.
fn write_json_string(f: &mut fmt::Formatter<'_>, s: &str) -> fmt::Result {
    f.write_str("\"")?;
    for c in s.chars() {
        match c {
            '"' => f.write_str("\\\"")?,
            '\\' => f.write_str("\\\\")?,
            '\u{8}' => f.write_str("\\b")?,
            '\u{c}' => f.write_str("\\f")?,
            '\n' => f.write_str("\\n")?,
            '\r' => f.write_str("\\r")?,
            '\t' => f.write_str("\\t")?,
            c if u32::from(c) < 0x20 => write!(f, "\\u{:04x}", u32::from(c))?,
            c => write!(f, "{c}")?,
        }
    }
    f.write_str("\"")
}

/// A string that is not a valid [`Path`].
#[derive(Debug, Clone, PartialEq, Eq, Error)]
#[error("invalid error path: unexpected input at byte {position}")]
pub struct PathParseError {
    /// Byte offset into the text at which parsing failed.
    pub position: usize,
}

impl FromStr for Path {
    type Err = PathParseError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let fail = |rest: &str| PathParseError {
            position: s.len() - rest.len(),
        };
        let mut outer_first: Vec<PathSegment> = Vec::new();
        let mut rest = s;
        while !rest.is_empty() {
            if let Some(after) = rest.strip_prefix('[') {
                let (segment, remaining) = parse_bracket(after).ok_or_else(|| fail(rest))?;
                outer_first.push(segment);
                rest = remaining;
            } else {
                let name_start = if outer_first.is_empty() {
                    rest
                } else {
                    rest.strip_prefix('.').ok_or_else(|| fail(rest))?
                };
                let (name, remaining) = split_name(name_start).ok_or_else(|| fail(name_start))?;
                outer_first.push(PathSegment::Field(Cow::Owned(String::from(name))));
                rest = remaining;
            }
        }
        outer_first.reverse();
        Ok(Self {
            inner_first: outer_first,
        })
    }
}

/// `[A-Za-z_][A-Za-z0-9_]*` or `[0-9]+`, and the text after it.
fn split_name(s: &str) -> Option<(&str, &str)> {
    let first = s.chars().next()?;
    let end = if first.is_ascii_digit() {
        s.find(|c: char| !c.is_ascii_digit()).unwrap_or(s.len())
    } else if first.is_ascii_alphabetic() || first == '_' {
        s.find(|c: char| !(c.is_ascii_alphanumeric() || c == '_'))
            .unwrap_or(s.len())
    } else {
        return None;
    };
    Some(s.split_at(end))
}

/// The inside of `[...]` after the `[`: a number or a JSON string, then `]`.
fn parse_bracket(s: &str) -> Option<(PathSegment, &str)> {
    if s.starts_with(|c: char| c.is_ascii_digit()) {
        let end = s.find(|c: char| !c.is_ascii_digit()).unwrap_or(s.len());
        let (digits, rest) = s.split_at(end);
        let n = digits.parse::<u64>().ok()?;
        return Some((PathSegment::Index(n), rest.strip_prefix(']')?));
    }
    let (key, rest) = parse_json_string(s.strip_prefix('"')?)?;
    Some((PathSegment::Key(key), rest.strip_prefix(']')?))
}

/// A JSON string body (after the opening quote) up to and including the closing
/// quote. Accepts every escape RFC 8259 §7 defines.
fn parse_json_string(s: &str) -> Option<(String, &str)> {
    let mut out = String::new();
    let mut chars = s.char_indices();
    while let Some((i, c)) = chars.next() {
        match c {
            '"' => return Some((out, s.get(i + 1..)?)),
            '\\' => {
                let (_, e) = chars.next()?;
                match e {
                    '"' | '\\' | '/' => out.push(e),
                    'b' => out.push('\u{8}'),
                    'f' => out.push('\u{c}'),
                    'n' => out.push('\n'),
                    'r' => out.push('\r'),
                    't' => out.push('\t'),
                    'u' => {
                        let hi = hex4(&mut chars)?;
                        let code = if (0xD800..0xDC00).contains(&hi) {
                            // A high surrogate must be followed by `\u` and a low one.
                            if chars.next()?.1 != '\\' || chars.next()?.1 != 'u' {
                                return None;
                            }
                            let lo = hex4(&mut chars)?;
                            if !(0xDC00..0xE000).contains(&lo) {
                                return None;
                            }
                            0x10000 + ((hi - 0xD800) << 10) + (lo - 0xDC00)
                        } else {
                            hi
                        };
                        out.push(char::from_u32(code)?);
                    }
                    _ => return None,
                }
            }
            c if u32::from(c) < 0x20 => return None,
            c => out.push(c),
        }
    }
    None
}

fn hex4(chars: &mut core::str::CharIndices<'_>) -> Option<u32> {
    let mut v = 0u32;
    for _ in 0..4 {
        v = v * 16 + chars.next()?.1.to_digit(16)?;
    }
    Some(v)
}

#[cfg(test)]
mod tests {
    use alloc::string::ToString;

    use super::*;

    fn p(s: &str) -> Path {
        s.parse().unwrap()
    }

    /// REQ-RT-066: the written forms the corpus uses round-trip.
    #[test]
    fn req_rt_066_grammar_round_trips() {
        for text in [
            "",
            "age",
            "[1]",
            "items[2].price",
            "items[2].price.amount",
            "stock[7].qty",
            "[7].qty",
            "scores[\"a\"]",
            "[\"a b\"][0]",
            "1",
            "9.x",
            "Circle.radius",
            "scores[\"a\\\"b\\\\c\"]",
            "scores[\"line\\nbreak\\u0001\"]",
            "scores[\"é水\"]",
        ] {
            let path = p(text);
            assert_eq!(path.to_string(), text, "{text:?}");
        }
    }

    /// REQ-RT-066: malformed paths are rejected, with the position of the fault.
    #[test]
    fn req_rt_066_rejects_malformed_paths() {
        for text in [
            ".a",
            "a..b",
            "a.",
            "a[",
            "a[x]",
            "a[1",
            "a b",
            "[1]x",
            "a[\"x]",
            "a[\"x\"",
            "[99999999999999999999]",
            "a[\"\\q\"]",
            "a[\"\\ud800\"]",
            "a[\"\\u12\"]",
            "a[\"\u{1}\"]",
        ] {
            assert!(text.parse::<Path>().is_err(), "{text:?} should not parse");
        }
        assert_eq!("a..b".parse::<Path>().unwrap_err().position, 2);
    }

    /// REQ-RT-065: segments are added outermost-last while a failure unwinds,
    /// and read outermost-first.
    #[test]
    fn req_rt_065_push_outer_builds_the_path_innermost_first() {
        let mut path = Path::root();
        assert!(path.is_root());
        path.push_outer(PathSegment::Field(Cow::Borrowed("price")));
        path.push_outer(PathSegment::Index(2));
        path.push_outer(PathSegment::Field(Cow::Borrowed("items")));
        assert!(!path.is_root());
        assert_eq!(path.to_string(), "items[2].price");
        assert_eq!(path, p("items[2].price"));
    }

    /// REQ-RT-066: a surrogate pair escape in a table key names one character.
    #[test]
    fn req_rt_066_surrogate_pair_escapes_decode() {
        assert_eq!(
            p("m[\"\\ud83d\\ude00\"]").segments().nth(1),
            Some(&PathSegment::Key("😀".into()))
        );
    }
}
