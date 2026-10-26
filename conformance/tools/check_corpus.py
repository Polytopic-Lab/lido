#!/usr/bin/env python3
"""Self-check for the conformance corpus (D-007, slice 1.1).

Usage:
    check_corpus.py                  run every check against the real corpus
    check_corpus.py --check-format   also require the corpus JSON formatting
    check_corpus.py --self-test      run this tool's own tests
    check_corpus.py --mutation-test  prove every cbor byte and json character matters
                                     (add --without-cborcheck to see why cborcheck exists)

Needs `jsonschema` and `cbor2` (see requirements.txt). Reads specs.md; never
writes it. No Lido code is involved anywhere in this file (REQ-ARCH-060).
"""
import argparse
import base64
import json
import math
import re
import struct
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cbor2  # noqa: E402
import cborcheck  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402

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


# --- the value model, checked against cbor2 (D-007 §3, §4) -----------------

MAX_SAFE = (1 << 53) - 1


def _float_of(payload):
    """The float a value-model float string denotes."""
    if payload == "NaN":
        return math.nan
    if payload in ("Infinity", "-Infinity"):
        return math.inf if payload[0] != "-" else -math.inf
    if "0x" in payload.lower():
        return float.fromhex(payload)
    return float(payload)


def _same_float(a, b):
    if a != a or b != b:
        return a != a and b != b
    return a == b and math.copysign(1, a) == math.copysign(1, b)


def _fits(fmt, x):
    try:
        return struct.unpack(">" + fmt, struct.pack(">" + fmt, x))[0] == x
    except OverflowError:
        return False


def value_matches(v, obj, path="value"):
    """Return a list of mismatches between value-model `v` and the Python
    object `obj` that cbor2 decoded. Type-strict; map pairs compared in order."""
    (tag, payload), = v.items()
    if tag == "bool":
        return [] if type(obj) is bool and obj == payload else [f"{path}: expected bool {payload}"]
    if tag in ("uint", "int"):
        ok = type(obj) is int and str(obj) == payload and (tag == "int" or obj >= 0)
        return [] if ok else [f"{path}: expected {tag} {payload}, decoded {obj!r}"]
    if tag in ("f16", "f32", "f64"):
        if type(obj) is not float:
            return [f"{path}: expected {tag} {payload}, decoded {obj!r}"]
        want = _float_of(payload)
        if not _same_float(want, obj):
            return [f"{path}: expected {tag} {payload}, decoded {obj!r}"]
        errs = []
        if tag == "f16" and want == want and not _fits("e", want):
            errs.append(f"{path}: {payload} is not exactly representable as float16 (REQ-RT-255)")
        if tag in ("f16", "f32") and want == want and not _fits("f", want):
            errs.append(f"{path}: {payload} is not exactly representable as float32")
        return errs
    if tag == "tstr":
        return [] if type(obj) is str and obj == payload else [f"{path}: expected tstr {payload!r}, decoded {obj!r}"]
    if tag == "bstr":
        return [] if type(obj) is bytes and obj == bytes.fromhex(payload) else [f"{path}: expected bstr {payload}, decoded {obj!r}"]
    if tag == "null":
        return [] if obj is None else [f"{path}: expected null, decoded {obj!r}"]
    if tag == "array":
        if type(obj) is not list or len(obj) != len(payload):
            return [f"{path}: expected array of {len(payload)}, decoded {obj!r}"]
        return [e for i, (pv, po) in enumerate(zip(payload, obj)) for e in value_matches(pv, po, f"{path}[{i}]")]
    if tag == "map":
        if type(obj) is not dict or len(obj) != len(payload):
            return [f"{path}: expected map of {len(payload)} entries, decoded {obj!r}"]
        errs = []
        for i, ((kv, vv), (ko, vo)) in enumerate(zip(payload, obj.items())):
            errs += value_matches(kv, ko, f"{path}.key[{i}]")
            errs += value_matches(vv, vo, f"{path}.val[{i}]")
        return errs
    return [f"{path}: unknown tag {tag!r}"]


def check_cbor(case, use_cborcheck=True):
    """The three-way check (D-007 §4): cbor2 decode == value; cbor2 canonical
    re-encode == cbor; cborcheck finds no violation. Returns violations."""
    try:
        data = bytes.fromhex(case["cbor"])
    except ValueError:
        return ["cbor is not hex"]
    errs = []
    try:
        obj = cbor2.loads(data)
    except Exception as e:  # any decoder failure is a detection
        return [f"cbor2 cannot decode: {type(e).__name__}: {e}"]
    errs += value_matches(case["value"], obj)
    try:
        if cbor2.dumps(obj, canonical=True) != data:
            errs.append("cbor2 canonical re-encoding differs from cbor")
    except Exception as e:
        errs.append(f"cbor2 cannot re-encode: {type(e).__name__}: {e}")
    if use_cborcheck:
        errs += [f"cborcheck: {e}" for e in cborcheck.check(data)]
    return errs


# --- the JSON writer (REQ-RT-175/177/178/179/200/220/230) ------------------


def _shortest_digits(x, width):
    """(digits, n) with x = 0.DIGITS * 10**n: the fewest digits that read back
    as exactly x at `width`, and of those the one closest to x (ECMA-262
    Number::toString, step 5)."""
    fmt = "f" if width == 32 else "d"
    exact = Decimal(x)

    def reads_back(d):
        try:
            return struct.unpack(">" + fmt, struct.pack(">" + fmt, float(d)))[0] == x
        except OverflowError:
            return False

    for prec in range(1, 18):
        base = Decimal(f"{x:.{prec - 1}e}")
        step = Decimal(1).scaleb(base.adjusted() - prec + 1)
        found = [d for d in (base - step, base, base + step) if d > 0 and reads_back(d)]
        if found:
            d = min(found, key=lambda c: abs(c - exact))
            digits = "".join(map(str, d.as_tuple().digits)).rstrip("0") or "0"
            return digits, d.adjusted() + 1
    raise AssertionError("unreachable: 17 digits always round-trip a double")


def json_float(x, width):
    """REQ-RT-178: ECMAScript Number::toString layout, shortest digits at
    `width` (32 for float16/float32 fields, 64 for float64), -0 for negative zero."""
    if x != x or x in (math.inf, -math.inf):
        raise ValueError("NaN and infinities have no JSON form (REQ-RT-210)")
    if x == 0:
        return "-0" if math.copysign(1, x) < 0 else "0"
    sign = "-" if x < 0 else ""
    k_digits, n = _shortest_digits(abs(x), width)
    k = len(k_digits)
    if k <= n <= 21:
        body = k_digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = k_digits[:n] + "." + k_digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + k_digits
    else:
        e = n - 1
        mant = k_digits[0] + ("." + k_digits[1:] if k > 1 else "")
        body = f"{mant}e{'+' if e >= 0 else '-'}{abs(e)}"
    return sign + body


_SHORT = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def json_string(s):
    """REQ-RT-179: escape only `"`, `\\` and U+0000-U+001F; all else raw UTF-8."""
    return '"' + "".join(_SHORT.get(c) or (f"\\u{ord(c):04x}" if ord(c) < 0x20 else c) for c in s) + '"'


def json_from_value(v):
    """Derive the expected JSON text of value-model `v` (compact, REQ-RT-175)."""
    (tag, payload), = v.items()
    if tag == "bool":
        return "true" if payload else "false"
    if tag in ("uint", "int"):
        return payload if abs(int(payload)) <= MAX_SAFE else f'"{payload}"'
    if tag in ("f16", "f32", "f64"):
        return json_float(_float_of(payload), 64 if tag == "f64" else 32)
    if tag == "tstr":
        return json_string(payload)
    if tag == "bstr":
        return '"' + base64.urlsafe_b64encode(bytes.fromhex(payload)).decode().rstrip("=") + '"'
    if tag == "null":
        return "null"
    if tag == "array":
        return "[" + ",".join(json_from_value(x) for x in payload) + "]"
    if tag == "map":
        members = []
        for k, val in payload:
            (_, kp), = k.items()
            # tstr key: the text; uint key: its decimal digits (REQ-KEY-030)
            members.append(json_string(kp) + ":" + json_from_value(val))
        return "{" + ",".join(members) + "}"
    raise ValueError(f"unknown tag {tag!r}")


def check_json(case):
    try:
        want = json_from_value(case["value"])
    except ValueError as e:
        return [f"cannot derive JSON: {e}"]
    return [] if want == case["json"] else [f"json differs: expected {want!r}, found {case['json']!r}"]


# --- checks 9, 12: case structure -------------------------------------------


def schema_roots(text):
    return set(re.findall(r"^([A-Za-z][A-Za-z0-9_]*)\s*=", text, re.M))


def check_case_file(rel, doc, schema_texts, req_ids):
    """File-level and per-case structure: file location, schema reference,
    root exists, ids well-formed, requirements exist in specs.md."""
    errs = []
    parts = rel.split("/")
    if len(parts) != 3 or parts[0] != "cases" or parts[1] != doc["kind"]:
        errs.append(f"{rel}: must live at cases/{doc['kind']}/<stem>.json")
    stem = doc["schema"][:-5]
    if parts[-1] != stem + ".json":
        errs.append(f"{rel}: file name must be {stem}.json to match its schema")
    text = schema_texts.get(doc["schema"])
    if text is None:
        return errs + [f"{rel}: schema {doc['schema']} does not exist"]
    roots = schema_roots(text)
    for c in doc["cases"]:
        if c["id"].split("/")[0] != stem:
            errs.append(f"{c['id']}: id stem must be {stem!r}")
        if c["root"] not in roots:
            errs.append(f"{c['id']}: root {c['root']!r} is not defined in {doc['schema']}")
        for r in c["requirements"]:
            if r not in req_ids:
                errs.append(f"{c['id']}: {r} does not exist in specs.md")
    return errs


def check_unique_ids(docs):
    seen, errs = set(), []
    for rel, doc in docs.items():
        for c in doc["cases"]:
            if c["id"] in seen:
                errs.append(f"{rel}: duplicate case id {c['id']}")
            seen.add(c["id"])
    return errs


def check_schemas_have_cases(schema_files, docs):
    have = {d["schema"] for d in docs.values() if d["kind"] == "positive"}
    return [f"{s}: no positive case file" for s in sorted(set(schema_files) - have)]


# --- the mutation test (DoD: mutating any expected byte fails the check) ----

JSON_PROBES = ['0', '1', 'x', ' ', '"', '\\', ',', ':', '{', '}', '[', ']']


def case_detects(case, use_cborcheck=True):
    return bool(check_cbor(case, use_cborcheck) or check_json(case))


def mutations(case):
    """Yield (description, mutated case) for every single-byte and
    single-character change of `cbor` and `json`."""
    data = bytes.fromhex(case["cbor"])
    for i in range(len(data)):
        for b in range(256):
            if b != data[i]:
                yield f"cbor[{i}]={b:02x}", dict(case, cbor=(data[:i] + bytes([b]) + data[i + 1 :]).hex())
    text = case["json"]
    for i in range(len(text)):
        for ch in JSON_PROBES:
            if ch != text[i]:
                yield f"json[{i}]={ch!r}", dict(case, json=text[:i] + ch + text[i + 1 :])
        yield f"json[{i}] deleted", dict(case, json=text[:i] + text[i + 1 :])
        yield f"json[{i}] doubled", dict(case, json=text[:i] + text[i] + text[i:])


def mutation_test(docs, use_cborcheck=True):
    """Return (survivors, total). A survivor is a mutation nothing detected."""
    survivors, total = [], 0
    for rel, doc in docs.items():
        for case in doc["cases"]:
            assert case_detects(dict(case), use_cborcheck) is False, f"{case['id']} must pass unmutated"
            for desc, m in mutations(case):
                total += 1
                if not case_detects(m, use_cborcheck):
                    survivors.append(f"{case['id']} {desc}")
    return survivors, total


# --- driver ---------------------------------------------------------------


def load_docs(root, case_files):
    return {rel: load(root / rel) for rel in case_files}


def run(root, specs, check_format):
    errs = []
    schema = load(root / "manifest.schema.json")
    errs += check_manifest_schema(schema)
    index = load(root / "index.json")
    schema_files = sorted(p.name for p in (root / "schemas").rglob("*.cddl"))
    case_files = sorted(p.relative_to(root).as_posix() for p in (root / "cases").rglob("*.json"))
    errs += check_index(index, schema_files, case_files)
    docs = load_docs(root, case_files)
    for rel, doc in docs.items():
        errs += check_case_instance(schema, doc, rel)
    if errs:
        return errs  # structure first: later checks assume a valid shape
    specs_text = specs.read_text(encoding="utf-8")
    errs += check_coverage(load(root / "construct-coverage.json"), specs_text, {f[:-5] for f in schema_files})
    schema_texts = {f: (root / "schemas" / f).read_text(encoding="utf-8") for f in schema_files}
    req_ids = set(re.findall(r"REQ-[A-Z]+-[0-9]{3}", specs_text))
    errs += check_schemas_have_cases(schema_files, docs)
    errs += check_unique_ids(docs)
    for rel, doc in docs.items():
        errs += check_case_file(rel, doc, schema_texts, req_ids)
        for case in doc["cases"]:
            errs += [f"{case['id']}: {e}" for e in check_cbor(case) + check_json(case)]
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


    # --- slice 1.2 ---------------------------------------------------------

    def test_value_model_is_type_strict(self):
        """REQ-ARCH-060: True is not 1, 1.0 is not 1, -0.0 is not 0.0, NaN is NaN."""
        self.assertEqual(value_matches({"uint": "1"}, 1), [])
        self.assertTrue(value_matches({"uint": "1"}, True))
        self.assertTrue(value_matches({"uint": "1"}, 1.0))
        self.assertTrue(value_matches({"f64": "1"}, 1))
        self.assertTrue(value_matches({"f64": "0"}, -0.0))
        self.assertEqual(value_matches({"f64": "-0"}, -0.0), [])
        self.assertEqual(value_matches({"f64": "NaN"}, math.nan), [])
        self.assertEqual(value_matches({"f64": "0x1.8p+0"}, 1.5), [])
        self.assertTrue(value_matches({"uint": "-1"}, -1))
        self.assertTrue(value_matches({"f16": "1.1"}, 1.1))  # not a float32 value
        self.assertTrue(value_matches({"f32": "1.1"}, 1.1))
        self.assertEqual(value_matches({"f64": "1.1"}, 1.1), [])

    def test_value_model_map_pairs_are_ordered(self):
        """REQ-RT-165: a map's pairs are compared in wire order."""
        a, b = ({"tstr": "a"}, {"uint": "1"}), ({"tstr": "b"}, {"uint": "2"})
        self.assertEqual(value_matches({"map": [list(a), list(b)]}, {"a": 1, "b": 2}), [])
        self.assertTrue(value_matches({"map": [list(b), list(a)]}, {"a": 1, "b": 2}))

    def test_json_float_layout(self):
        """REQ-RT-178: ECMAScript layout, shortest digits at the held width, -0."""
        for x, width, want in [
            (1.0, 64, "1"), (1.5, 64, "1.5"), (100000.0, 32, "100000"), (0.0, 64, "0"),
            (-0.0, 64, "-0"), (1e21, 64, "1e+21"), (1e20, 64, "100000000000000000000"),
            (1e-6, 64, "0.000001"), (1e-7, 64, "1e-7"), (1.2345e-7, 64, "1.2345e-7"),
            (1e300, 64, "1e+300"), (-4.1, 64, "-4.1"), (65504.0, 32, "65504"),
            (3.4028234663852886e38, 32, "3.4028235e+38"),
            (3.4028234663852886e38, 64, "3.4028234663852886e+38"),
            (2.0 ** -24, 32, "5.9604645e-8"), (2.0 ** -24, 64, "5.960464477539063e-8"),
            (123456789.125, 64, "123456789.125"),
        ]:
            self.assertEqual(json_float(x, width), want, (x, width))
        with self.assertRaises(ValueError):
            json_float(math.nan, 64)

    def test_json_string_escaping(self):
        """REQ-RT-179: only quote, backslash and C0 are escaped; "/" and non-ASCII are raw."""
        self.assertEqual(json_string('a"b\\c/\n\x01\x1f\x7f\u00fc\u6c34'),
                         '"a\\"b\\\\c/\\n\\u0001\\u001f\x7f\u00fc\u6c34"')

    def test_json_from_value(self):
        """REQ-RT-175/177/200/220/230: compact, wire order, base64url, wide ints as strings."""
        v = {"map": [[{"uint": "9"}, {"bstr": "fbff"}], [{"uint": "10"}, {"uint": "9007199254740992"}]]}
        self.assertEqual(json_from_value(v), '{"9":"-_8","10":"9007199254740992"}')
        self.assertEqual(json_from_value({"int": "-9007199254740991"}), "-9007199254740991")
        self.assertEqual(json_from_value({"int": "-9007199254740992"}), '"-9007199254740992"')
        self.assertEqual(json_from_value({"bstr": ""}), '""')
        self.assertEqual(json_from_value({"array": [{"null": None}, {"bool": True}]}), "[null,true]")

    def test_cbor_check_detects_each_failure_mode(self):
        """REQ-RT-160/165: a wrong value, wrong bytes, or non-canonical bytes are all caught."""
        case = _good_case()
        case["cases"][0]["json"] = "36"
        c = case["cases"][0]
        self.assertEqual(check_cbor(c), [])
        self.assertTrue(check_cbor(dict(c, cbor="1825")))                  # different value
        self.assertTrue(check_cbor(dict(c, cbor="190024")))                # non-shortest head
        self.assertTrue(check_cbor(dict(c, value={"uint": "37"})))         # value disagrees
        self.assertTrue(check_cbor(dict(c, cbor="18")))                    # truncated
        self.assertTrue(check_cbor(dict(c, cbor="182400")))                # trailing byte

    def test_json_check_detects_mutations(self):
        """REQ-RT-175: whitespace, quoted integers and reordering are caught."""
        c = dict(_good_case()["cases"][0], json="36")
        self.assertEqual(check_json(c), [])
        self.assertTrue(check_json(dict(c, json=' 36')))
        self.assertTrue(check_json(dict(c, json='"36"')))

    def test_case_structure_checks(self):
        """REQ-ARCH-060: ids, roots, requirement IDs, file placement, completeness."""
        doc = _good_case()
        texts = {"s.cddl": "T = uint\n"}
        ids = {"REQ-RT-160"}
        self.assertEqual(check_case_file("cases/positive/s.json", doc, texts, ids), [])
        self.assertTrue(check_case_file("cases/positive/other.json", doc, texts, ids))
        self.assertTrue(check_case_file("cases/negative/s.json", doc, texts, ids))
        self.assertTrue(check_case_file("cases/positive/s.json", doc, texts, set()))  # REQ-RT-999-style typo
        doc["cases"][0]["root"] = "Missing"
        self.assertTrue(check_case_file("cases/positive/s.json", doc, texts, ids))
        doc["cases"][0].update(root="T", id="z/a")
        self.assertTrue(check_case_file("cases/positive/s.json", doc, texts, ids))
        self.assertTrue(check_unique_ids({"a": _good_case(), "b": _good_case()}))
        self.assertTrue(check_schemas_have_cases(["s.cddl", "t.cddl"], {"a": _good_case()}))
        self.assertEqual(check_schemas_have_cases(["s.cddl"], {"a": _good_case()}), [])

    def test_mutation_test_has_teeth(self):
        """REQ-ARCH-060 / DoD: no mutation of cbor or json survives."""
        docs = {"a": dict(_good_case(), cases=[dict(_good_case()["cases"][0], json="36")])}
        survivors, total = mutation_test(docs)
        self.assertEqual(survivors, [])
        self.assertGreater(total, 500)

    def test_real_corpus_is_clean(self):
        """REQ-ARCH-060: the committed corpus passes every check."""
        self.assertEqual(run(CONFORMANCE, SPECS, True), [])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check-format", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--mutation-test", action="store_true")
    ap.add_argument("--without-cborcheck", action="store_true", help="with --mutation-test: disable cborcheck")
    args = ap.parse_args()
    if args.self_test:
        import test_cborcheck

        loader = unittest.defaultTestLoader
        suite = unittest.TestSuite(
            [loader.loadTestsFromTestCase(Tests), loader.loadTestsFromModule(test_cborcheck)]
        )
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    if args.mutation_test:
        case_files = sorted(p.relative_to(CONFORMANCE).as_posix() for p in (CONFORMANCE / "cases").rglob("*.json"))
        survivors, total = mutation_test(load_docs(CONFORMANCE, case_files), not args.without_cborcheck)
        for sv in survivors:
            print(f"survivor: {sv}", file=sys.stderr)
        print(f"mutation-test: {total} mutations, {len(survivors)} survivor(s)")
        return 1 if survivors else 0
    errs = run(CONFORMANCE, SPECS, args.check_format)
    for e in errs:
        print(f"error: {e}", file=sys.stderr)
    print(f"check_corpus: {len(errs)} error(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
