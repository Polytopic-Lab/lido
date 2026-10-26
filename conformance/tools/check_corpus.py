#!/usr/bin/env python3
"""Self-check for the conformance corpus (D-007, slice 1.1).

Usage:
    check_corpus.py                 run every check against the real corpus
    check_corpus.py --check-format  also require the corpus JSON formatting
    check_corpus.py --self-test     run this tool's own tests

Needs `jsonschema` (see requirements.txt). Reads specs.md; never writes it.
"""
import argparse
import json
import re
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

CONFORMANCE = Path(__file__).resolve().parent.parent
SPECS = CONFORMANCE.parent / "doc" / "specs.md"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def norm(text):
    return " ".join(text.split())


# --- check 1: the manifest schema is itself a valid 2020-12 schema --------


def check_manifest_schema(schema):
    """REQ-ARCH-060: the manifest format validates against its own metaschema."""
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as e:  # SchemaError
        return [f"manifest.schema.json is not a valid 2020-12 schema: {e.message}"]
    return []


# --- checks 2, 7: case files ----------------------------------------------


def check_case_instance(schema, instance, name):
    """REQ-ARCH-060: a case file conforms to the manifest schema."""
    validator = Draft202012Validator(schema)
    return [
        f"{name}: {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(instance), key=lambda e: list(map(str, e.absolute_path)))
    ]


def check_format_text(text, name):
    """D-007 §6: LF only, trailing newline, no tabs, 2-space indentation."""
    errs = []
    if "\r" in text:
        errs.append(f"{name}: contains CR")
    if not text.endswith("\n") or text.endswith("\n\n"):
        errs.append(f"{name}: must end with exactly one newline")
    for n, line in enumerate(text.split("\n"), 1):
        if "\t" in line:
            errs.append(f"{name}:{n}: tab character")
        indent = len(line) - len(line.lstrip(" "))
        if indent % 2:
            errs.append(f"{name}:{n}: indentation is not a multiple of 2")
    try:
        json.loads(text)
    except ValueError as e:
        errs.append(f"{name}: not valid JSON: {e}")
    return errs


# --- checks 3: index <=> tree ---------------------------------------------


def check_index(index, schema_files, case_files):
    """REQ-ARCH-060: index.json lists exactly the files on disk."""
    errs = []
    for key, on_disk in (("schemas", schema_files), ("cases", case_files)):
        listed = index.get(key, [])
        if len(listed) != len(set(listed)):
            errs.append(f"index.json {key}: duplicate entries")
        for f in sorted(set(on_disk) - set(listed)):
            errs.append(f"{f}: on disk but not in index.json")
        for f in sorted(set(listed) - set(on_disk)):
            errs.append(f"{f}: in index.json but not on disk")
    return errs


# --- checks 4-6: construct coverage vs specs.md section 3 ------------------


def section3_bullets(specs_text):
    """The whitespace-normalized top-level bullets of specs.md section 3."""
    m = re.search(r"^## 3\. CDDL core subset.*?\n(.*?)^### 3\.1", specs_text, re.S | re.M)
    if not m:
        raise ValueError("specs.md: section 3 not found")
    bullets, cur = [], None
    for line in m.group(1).split("\n"):
        if line.startswith("- "):
            cur = [line[2:]]
            bullets.append(cur)
        elif cur is not None and line.startswith("  "):
            cur.append(line)
        elif not line.strip():
            cur = None
    return [norm(" ".join(b)) for b in bullets]


def check_coverage(coverage, specs_text, schema_stems):
    """specs.md §3: every bullet is covered, every construct maps to a schema,
    and every quote is real."""
    errs = []
    bullets = section3_bullets(specs_text)
    if not bullets:
        return ["specs.md section 3 has no bullets"]
    cited = set()
    ids = [c["id"] for c in coverage["constructs"]]
    if len(ids) != len(set(ids)):
        errs.append("construct-coverage.json: duplicate construct ids")
    for c in coverage["constructs"]:
        cid = c["id"]
        quote, derives = c.get("quote"), c.get("derives_from")
        if bool(quote) == bool(derives):
            errs.append(f"{cid}: needs exactly one of `quote` and `derives_from`")
        if quote:
            hits = [i for i, b in enumerate(bullets) if norm(quote) in b]
            if not hits:
                errs.append(f"{cid}: quote not found in specs.md §3: {quote!r}")
            elif len(hits) > 1:
                errs.append(f"{cid}: quote matches {len(hits)} §3 bullets: {quote!r}")
            else:
                cited.add(hits[0])
        if derives and derives not in specs_text:
            errs.append(f"{cid}: derives_from {derives} not found in specs.md")
        if not c["schemas"] and not c.get("deferred_to"):
            errs.append(f"{cid}: no schema and no `deferred_to`")
        for s in c["schemas"]:
            if s not in schema_stems:
                errs.append(f"{cid}: schema {s!r} does not exist")
    for i, b in enumerate(bullets):
        if i not in cited:
            errs.append(f"specs.md §3 bullet not covered by any construct: {b[:70]}...")
    return errs


# --- driver ---------------------------------------------------------------


def run(root, specs, check_format):
    errs = []
    schema = load(root / "manifest.schema.json")
    errs += check_manifest_schema(schema)
    index = load(root / "index.json")
    schema_files = sorted(p.name for p in (root / "schemas").rglob("*.cddl"))
    case_files = sorted(p.relative_to(root).as_posix() for p in (root / "cases").rglob("*.json"))
    errs += check_index(index, schema_files, case_files)
    for rel in case_files:
        errs += check_case_instance(schema, load(root / rel), rel)
    specs_text = specs.read_text(encoding="utf-8")
    errs += check_coverage(load(root / "construct-coverage.json"), specs_text, {f[:-5] for f in schema_files})
    if check_format:
        for rel in ["manifest.schema.json", "index.json", "construct-coverage.json", *case_files]:
            errs += check_format_text((root / rel).read_text(encoding="utf-8"), rel)
    return errs


# --- this tool's own tests --------------------------------------------------

SPECS_FIXTURE = """\
## 3. CDDL core subset (v1)

- First thing (`a`).
- Second thing, wrapped
  over two lines.

### 3.1 Map key encoding
REQ-KEY-020
"""


def _good_case():
    return {
        "manifest_version": 1,
        "schema": "s.cddl",
        "kind": "positive",
        "cases": [
            {
                "id": "s/a",
                "root": "T",
                "description": "d",
                "requirements": ["REQ-RT-160"],
                "derivation": "hand-encoded",
                "value": {"uint": "36"},
                "cbor": "1824",
                "json": "36",
            }
        ],
    }


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load(CONFORMANCE / "manifest.schema.json")

    def test_manifest_schema_is_valid(self):
        """REQ-ARCH-060"""
        self.assertEqual(check_manifest_schema(self.schema), [])
        self.assertTrue(check_manifest_schema({"type": 5}))

    def test_good_case_validates(self):
        """REQ-ARCH-060"""
        self.assertEqual(check_case_instance(self.schema, _good_case(), "x"), [])

    def test_spaced_cbor_hex_rejected(self):
        """REQ-ARCH-060: cbor is unseparated lowercase hex."""
        c = _good_case()
        c["cases"][0]["cbor"] = "a3 63 61"
        self.assertTrue(check_case_instance(self.schema, c, "x"))

    def test_bare_number_value_rejected(self):
        """REQ-ARCH-060 / REQ-RT-220: integers are tagged decimal strings."""
        c = _good_case()
        c["cases"][0]["value"] = 36
        self.assertTrue(check_case_instance(self.schema, c, "x"))
        c["cases"][0]["value"] = {"uint": 36}
        self.assertTrue(check_case_instance(self.schema, c, "x"))

    def test_two_member_value_rejected(self):
        """REQ-ARCH-060: a value has exactly one tag member."""
        c = _good_case()
        c["cases"][0]["value"] = {"uint": "1", "int": "1"}
        self.assertTrue(check_case_instance(self.schema, c, "x"))

    def test_unspecified_kinds_rejected(self):
        """REQ-ARCH-060: negative/noncanonical/evolution records are not yet defined."""
        c = _good_case()
        c["kind"] = "negative"
        self.assertTrue(check_case_instance(self.schema, c, "x"))

    def test_index_matches_tree(self):
        """REQ-ARCH-060"""
        idx = {"schemas": ["a.cddl"], "cases": ["cases/positive/a.json"]}
        self.assertEqual(check_index(idx, ["a.cddl"], ["cases/positive/a.json"]), [])
        self.assertTrue(check_index(idx, ["a.cddl", "b.cddl"], ["cases/positive/a.json"]))
        self.assertTrue(check_index(idx, ["a.cddl"], ["cases/positive/a.json", "cases/positive/b.json"]))
        self.assertTrue(check_index(idx, [], ["cases/positive/a.json"]))

    def test_every_section_3_bullet_is_covered(self):
        """specs.md §3 (REQ-KEY-020 for the escape hatch)"""
        self.assertEqual(
            section3_bullets(SPECS_FIXTURE),
            ["First thing (`a`).", "Second thing, wrapped over two lines."],
        )

        def cov(*constructs):
            return {"constructs": list(constructs)}

        one = {"id": "C-1", "quote": "First thing", "schemas": ["s"]}
        two = {"id": "C-2", "quote": "wrapped over two", "schemas": ["s"]}
        self.assertEqual(check_coverage(cov(one, two), SPECS_FIXTURE, {"s"}), [])
        # a bullet left uncited
        self.assertTrue(check_coverage(cov(one), SPECS_FIXTURE, {"s"}))
        # a quote altered by one word
        bad = dict(two, quote="wrapped under two")
        self.assertTrue(check_coverage(cov(one, bad), SPECS_FIXTURE, {"s"}))
        # a construct naming a schema that does not exist
        self.assertTrue(check_coverage(cov(one, two), SPECS_FIXTURE, set()))
        # derives_from escape hatch, and its failure modes
        ok = {"id": "C-3", "derives_from": "REQ-KEY-020", "schemas": [], "deferred_to": "later"}
        self.assertEqual(check_coverage(cov(one, two, ok), SPECS_FIXTURE, {"s"}), [])
        self.assertTrue(check_coverage(cov(one, two, dict(ok, derives_from="REQ-NOPE-1")), SPECS_FIXTURE, {"s"}))
        self.assertTrue(check_coverage(cov(one, two, dict(ok, deferred_to="")), SPECS_FIXTURE, {"s"}))

    def test_format_check(self):
        """D-007 §6"""
        self.assertEqual(check_format_text('{\n  "a": 1\n}\n', "x"), [])
        self.assertTrue(check_format_text('{\n  "a": 1\n}', "x"))
        self.assertTrue(check_format_text('{\r\n  "a": 1\r\n}\r\n', "x"))
        self.assertTrue(check_format_text('{\n "a": 1\n}\n', "x"))

    def test_real_corpus_is_clean(self):
        """REQ-ARCH-060: the committed corpus passes every check."""
        self.assertEqual(run(CONFORMANCE, SPECS, True), [])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check-format", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        sys.argv = sys.argv[:1]
        unittest.main(module=sys.modules[__name__], verbosity=2)
    errs = run(CONFORMANCE, SPECS, args.check_format)
    for e in errs:
        print(f"error: {e}", file=sys.stderr)
    print(f"check_corpus: {len(errs)} error(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
