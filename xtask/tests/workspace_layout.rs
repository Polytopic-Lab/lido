//! Slice 0.1's Definition of Done as tests: the workspace that
//! `cargo metadata` reports is the workspace design.md §2 describes.
//!
//! A virtual workspace root cannot host `tests/`, so these live in `xtask`
//! (decisions.md D-002). They stay integration tests rather than becoming a
//! `cargo xtask` subcommand so that `cargo test` alone checks the DoD.

use std::collections::BTreeSet;
use std::fs;
use std::path::PathBuf;
use std::process::Command;

use serde_json::Value;

/// design.md §2 names these crates. The DoD for slice 0.1 is that
/// `cargo metadata` lists every one of them.
///
/// `xtask` is in the list because the comparison below is set equality and
/// `cargo metadata` reports every workspace member: a crate not named in
/// design.md §2 is exactly what that assertion exists to catch.
const EXPECTED_PACKAGES: [&str; 9] = [
    "lido-cddl",
    "lido-ir",
    "lido-codegen",
    "lido-codegen-cpp",
    "lido-codegen-java",
    "lido-codegen-rust",
    "lido-cli",
    "lido-runtime",
    "xtask",
];

/// The backend crates REQ-ARCH-030/040 require to stay isolated from one
/// another.
const BACKEND_PACKAGES: [&str; 3] = ["lido-codegen-cpp", "lido-codegen-java", "lido-codegen-rust"];

/// DoD clause 3: `cargo metadata` lists every crate named in design.md §2 —
/// no more and no less.
#[test]
fn crates_match_design_section_2() {
    let metadata = metadata();
    let actual: BTreeSet<&str> = packages(&metadata).iter().map(package_name).collect();
    let expected: BTreeSet<&str> = EXPECTED_PACKAGES.into_iter().collect();

    let missing: Vec<&str> = expected.difference(&actual).copied().collect();
    let unexpected: Vec<&str> = actual.difference(&expected).copied().collect();
    assert_eq!(
        actual, expected,
        "missing from `cargo metadata`: {missing:?}; \
         present but not named in design.md §2: {unexpected:?}"
    );
}

/// REQ-DEP-010: the project is licensed under the MIT license.
#[test]
fn req_dep_010_every_package_is_mit_licensed() {
    let metadata = metadata();

    let license = workspace_root(&metadata).join("LICENSE");
    assert!(
        license.is_file(),
        "REQ-DEP-010: {} does not exist",
        license.display()
    );

    for package in packages(&metadata) {
        assert_eq!(
            package["license"].as_str(),
            Some("MIT"),
            "REQ-DEP-010: package `{}` does not declare `license = \"MIT\"`",
            package_name(package)
        );
    }
}

/// REQ-NFR-030: Rust 2021 edition baseline, pinned to a specific version
/// rather than tracking current stable.
#[test]
fn req_nfr_030_every_package_targets_rust_2021() {
    let metadata = metadata();

    for package in packages(&metadata) {
        assert_eq!(
            package["edition"].as_str(),
            Some("2021"),
            "REQ-NFR-030: package `{}` does not declare `edition = \"2021\"`",
            package_name(package)
        );
    }

    let path = workspace_root(&metadata).join("rust-toolchain.toml");
    let manifest = fs::read_to_string(&path)
        .unwrap_or_else(|error| panic!("REQ-NFR-030: cannot read {}: {error}", path.display()));
    let channel = toolchain_channel(&manifest)
        .unwrap_or_else(|| panic!("REQ-NFR-030: {} declares no `channel`", path.display()));
    assert!(
        channel.starts_with(|first: char| first.is_ascii_digit()),
        "REQ-NFR-030: {} must pin an explicit version, not a moving channel \
         such as stable/beta/nightly; found `{channel}`",
        path.display()
    );
}

/// REQ-ARCH-040: no backend crate depends on another backend crate.
#[test]
fn req_arch_040_no_backend_depends_on_another_backend() {
    let metadata = metadata();

    for package in packages(&metadata) {
        let name = package_name(package);
        if !BACKEND_PACKAGES.contains(&name) {
            continue;
        }
        for dependency in dependencies(package) {
            // Direct declarations only, which is what REQ-ARCH-040 forbids
            // between backends; nothing in design.md §2's graph sits between
            // two backends for a transitive path to run through.
            let dependency_name = package_name(dependency);
            assert!(
                !BACKEND_PACKAGES.contains(&dependency_name),
                "REQ-ARCH-040: backend `{name}` depends on backend `{dependency_name}`"
            );
        }
    }
}

/// `cargo metadata --no-deps` for the workspace this test is compiled into.
fn metadata() -> Value {
    let output = Command::new(env!("CARGO"))
        .args([
            "metadata",
            "--no-deps",
            "--format-version",
            "1",
            "--manifest-path",
            concat!(env!("CARGO_MANIFEST_DIR"), "/Cargo.toml"),
        ])
        .output()
        .expect("failed to run `cargo metadata`");
    assert!(
        output.status.success(),
        "`cargo metadata` failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).expect("`cargo metadata` emitted invalid JSON")
}

fn packages(metadata: &Value) -> &[Value] {
    metadata["packages"]
        .as_array()
        .expect("`cargo metadata` has no `packages` array")
}

fn dependencies(package: &Value) -> &[Value] {
    package["dependencies"]
        .as_array()
        .expect("package has no `dependencies` array")
}

fn package_name(package: &Value) -> &str {
    package["name"]
        .as_str()
        .expect("package has no `name` string")
}

fn workspace_root(metadata: &Value) -> PathBuf {
    PathBuf::from(
        metadata["workspace_root"]
            .as_str()
            .expect("`cargo metadata` has no `workspace_root` string"),
    )
}

/// Extracts `channel = "…"` from a `rust-toolchain.toml`.
///
/// Hand-parsed rather than via a TOML crate: one key out of a five-line file
/// does not justify a second third-party dependency (D-002).
fn toolchain_channel(manifest: &str) -> Option<&str> {
    for line in manifest.lines() {
        let Some(rest) = line.trim().strip_prefix("channel") else {
            continue;
        };
        let Some(value) = rest.trim_start().strip_prefix('=') else {
            continue;
        };
        return Some(value.trim().trim_matches('"'));
    }
    None
}
