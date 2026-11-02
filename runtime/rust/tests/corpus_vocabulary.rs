//! The one place slice 2.1's contract meets the conformance corpus: every error
//! kind and path the corpus names must be expressible by the runtime's types.
//!
//! The corpus is read, never written (CLAUDE.md, non-negotiable 2).

use std::fs;
use std::path::{Path as FsPath, PathBuf};

use lido_runtime::{DecodeErrorKind, EncodeErrorKind, Path};
use serde_json::Value;

fn corpus_files(kind: &str) -> Vec<PathBuf> {
    let dir = FsPath::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../conformance/cases")
        .join(kind);
    let mut files: Vec<PathBuf> = fs::read_dir(&dir)
        .unwrap_or_else(|e| panic!("{}: {e}", dir.display()))
        .map(|entry| entry.expect("directory entry").path())
        .filter(|p| p.extension().is_some_and(|x| x == "json"))
        .collect();
    files.sort();
    files
}

fn cases(kind: &str) -> Vec<Value> {
    let mut out = Vec::new();
    for file in corpus_files(kind) {
        let text = fs::read_to_string(&file).expect("readable corpus file");
        let doc: Value = serde_json::from_str(&text).expect("corpus file is JSON");
        out.extend(
            doc["cases"]
                .as_array()
                .expect("cases array")
                .iter()
                .cloned(),
        );
    }
    out
}

/// Every `error` object in the corpus: `(case id, kind, path)`.
fn errors(kind: &str) -> Vec<(String, String, Option<String>)> {
    let mut out = Vec::new();
    for case in cases(kind) {
        let id = case["id"].as_str().expect("id").to_owned();
        let mut push = |err: &Value| {
            out.push((
                id.clone(),
                err["kind"].as_str().expect("error.kind").to_owned(),
                err["path"].as_str().map(str::to_owned),
            ));
        };
        if kind == "negative" {
            push(&case["error"]);
        } else {
            for side in ["cbor", "json"] {
                if case["expect"][side].is_object() {
                    push(&case["expect"][side]["error"]);
                }
            }
        }
    }
    out
}

/// REQ-RT-060, REQ-RT-300/310/315/350/380: every decode error kind the corpus
/// names has a home in `DecodeErrorKind`, and every variant is used by some vector
/// or is a limit kind (REQ-RT-270/290, which the corpus cannot express).
#[test]
fn req_rt_060_every_corpus_decode_error_kind_is_expressible() {
    let named: Vec<&str> = DecodeErrorKind::NAMES.to_vec();
    let mut seen = Vec::new();
    for (id, kind, _) in errors("negative") {
        assert!(
            named.contains(&kind.as_str()),
            "{id}: unknown decode error kind {kind:?}"
        );
        seen.push(kind);
    }
    for name in named {
        let limit = matches!(name, "depth_exceeded" | "size_exceeded");
        assert!(
            limit || seen.iter().any(|s| s == name),
            "{name} is in the runtime but no negative vector uses it"
        );
    }
}

/// REQ-RT-210/250/255: the same for encode errors.
#[test]
fn req_rt_210_every_corpus_encode_error_kind_is_expressible() {
    let named: Vec<&str> = EncodeErrorKind::NAMES.to_vec();
    let mut seen = Vec::new();
    for (id, kind, _) in errors("encode_error") {
        assert!(
            named.contains(&kind.as_str()),
            "{id}: unknown encode error kind {kind:?}"
        );
        seen.push(kind);
    }
    for name in named {
        assert!(
            seen.iter().any(|s| s == name),
            "{name} is in the runtime but no vector uses it"
        );
    }
}

/// REQ-RT-066: every path in the corpus parses and prints back unchanged.
#[test]
fn req_rt_066_every_corpus_path_round_trips() {
    let mut count = 0;
    for kind in ["negative", "encode_error"] {
        for (id, _, path) in errors(kind) {
            let Some(text) = path else { continue };
            let parsed: Path = text
                .parse()
                .unwrap_or_else(|e| panic!("{id}: {text:?}: {e}"));
            assert_eq!(parsed.to_string(), text, "{id}");
            count += 1;
        }
    }
    assert!(
        count > 50,
        "expected to see the corpus's paths, saw {count}"
    );
}
