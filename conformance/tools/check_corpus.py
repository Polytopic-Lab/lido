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
import io
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


def _py_key(kv):
    (tag, payload), = kv.items()
    return int(payload) if tag == "uint" else payload


def value_matches(v, obj, path="value", ordered=True):
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
        return [e for i, (pv, po) in enumerate(zip(payload, obj))
                for e in value_matches(pv, po, f"{path}[{i}]", ordered)]
    if tag == "map":
        if type(obj) is not dict or len(obj) != len(payload):
            return [f"{path}: expected map of {len(payload)} entries, decoded {obj!r}"]
        errs = []
        if not ordered:  # pairs match by key; the order is the variance under test
            for i, (kv, vv) in enumerate(payload):
                want = _py_key(kv)
                if want not in obj:
                    errs.append(f"{path}: key {want!r} missing from decoded map")
                else:
                    errs += value_matches(vv, obj[want], f"{path}.val[{i}]", ordered)
            return errs
        for i, ((kv, vv), (ko, vo)) in enumerate(zip(payload, obj.items())):
            errs += value_matches(kv, ko, f"{path}.key[{i}]")
            errs += value_matches(vv, vo, f"{path}.val[{i}]", ordered)
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
    have = {d["schema"] for d in docs.values() if d["kind"] == "positive"}  # every top-level schema needs positives
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
        if doc["kind"] != "positive":
            continue
        for case in doc["cases"]:
            assert case_detects(dict(case), use_cborcheck) is False, f"{case['id']} must pass unmutated"
            for desc, m in mutations(case):
                total += 1
                if not case_detects(m, use_cborcheck):
                    survivors.append(f"{case['id']} {desc}")
    return survivors, total


# --- negative, noncanonical and encode_error records (slice 1.3) -------------

CBOR_KIND_OF = {"truncated": "truncated", "trailing": "trailing_data"}
VARIANCE_CATEGORY = {
    "indefinite_length": "indefinite", "unsorted_keys": "key_order", "non_shortest_head": "head",
    "wider_float": "float", "non_canonical_nan": "nan",
}
JSON_VARIANCES = {"whitespace", "string_escapes", "number_spelling", "int_as_string",
                  "int_as_number", "base64_padding", "member_order"}

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")
_INDEX = re.compile(r"\[([0-9]+)\]")
_TKEY = re.compile(r'\[("(?:[^"\\]|\\.)*")\]')


def parse_path(path):
    """REQ-RT-066: the segments of an error path, or ValueError. A field segment
    follows `.` except at the start; `[...]` segments attach with no dot."""
    segs, i = [], 0
    while i < len(path):
        if path[i] == "[":
            m = _INDEX.match(path, i)
            if m:
                segs.append(("idx", int(m.group(1))))
            else:
                m = _TKEY.match(path, i)
                if not m:
                    raise ValueError(f"bad path {path!r} at {i}")
                segs.append(("tkey", json.loads(m.group(1))))
        else:
            if i > 0:
                if path[i] != ".":
                    raise ValueError(f"bad path {path!r} at {i}")
                i += 1
            m = _NAME.match(path, i)
            if not m:
                raise ValueError(f"bad path {path!r} at {i}")
            segs.append(("key", m.group(0)))
        i = m.end()
    return segs


def walk_decoded(obj, segs):
    """Follow `segs` through a decoded (cbor2 or json) object; return
    (found, value). Table keys that look numeric are tried as integers too."""
    for kind, seg in segs:
        if kind == "idx" and isinstance(obj, dict):  # [7]: a uint-keyed table entry
            if seg not in obj:
                return False, None
            obj = obj[seg]
        elif kind == "idx":
            if type(obj) is not list or seg >= len(obj):
                return False, None
            obj = obj[seg]
        else:
            if not isinstance(obj, dict):
                return False, None
            for cand in (seg, int(seg) if isinstance(seg, str) and seg.isdigit() else None):
                if cand is not None and cand in obj:
                    obj = obj[cand]
                    break
            else:
                return False, None
    return True, obj


def walk_value(v, segs):
    """Follow `segs` through a value-model value; return (found, value)."""
    for kind, seg in segs:
        (tag, payload), = v.items()
        if kind == "idx" and tag == "map":  # [7]: a uint-keyed table entry
            hit = [val for k, val in payload if str(_py_key(k)) == str(seg)]
            if not hit:
                return False, None
            v = hit[0]
        elif kind == "idx":
            if tag != "array" or seg >= len(payload):
                return False, None
            v = payload[seg]
        else:
            if tag != "map":
                return False, None
            hit = [val for k, val in payload if str(_py_key(k)) == str(seg)]
            if not hit:
                return False, None
            v = hit[0]
    return True, v


def cbor2_strict(data):
    """cbor2 decode of exactly one item; raises on anything cbor2 rejects,
    including trailing bytes (which cbor2.loads alone ignores)."""
    fp = io.BytesIO(data)
    obj = cbor2.CBORDecoder(fp).decode()
    if fp.read(1):
        raise ValueError("trailing bytes")
    return obj


class _Num(str):
    """A JSON number kept as its source spelling."""


def json_strict(text, hook=None):
    """Parse JSON text strictly. Returns the object, or raises ValueError whose
    first argument is the error kind: truncated, trailing_data, syntax, duplicate_key."""
    def reject(c):
        raise ValueError("syntax", f"{c} is not JSON")

    def pairs(ps):
        names = [k for k, _ in ps]
        if len(names) != len(set(names)):
            raise ValueError("duplicate_key", "duplicate member name")
        return hook(ps) if hook else dict(ps)

    try:
        return json.loads(text, parse_constant=reject, parse_float=_Num, parse_int=_Num,
                          object_pairs_hook=pairs)
    except json.JSONDecodeError as e:
        stripped = len(text.rstrip())
        if e.msg.startswith("Extra data"):
            raise ValueError("trailing_data", e.msg)
        if e.msg.startswith("Unterminated") or e.pos >= stripped:
            raise ValueError("truncated", e.msg)
        raise ValueError("syntax", e.msg)


def cbor_kinds(a):
    """The negative-vector error kinds an `Analysis` supports."""
    kinds = set()
    for m in a.malformed:
        kinds.add("truncated" if "truncated" in m else "trailing_data" if "trailing" in m else "syntax")
    for m in a.invalid:
        kinds.add("invalid_utf8" if "UTF-8" in m else "duplicate_key")
    return kinds


def check_negative(case, schema_text):
    """Slice 1.3 plan §4: confirm `classification` (and the declared kind) against
    two independent parsers; confirm the path resolves in the input."""
    errs = []
    cls, err = case["classification"], case["error"]
    kind = err["kind"]
    inp = case["input"]
    if "cbor" in inp:
        data = bytes.fromhex(inp["cbor"])
        a = cborcheck.analyze(data)
        kinds = cbor_kinds(a)
        derived = "malformed" if kinds else "schema_invalid"
        try:
            decoded, c2err = cbor2_strict(data), None
        except Exception as e:  # any decoder refusal
            decoded, c2err = None, e
        if cls != derived:
            errs.append(f"classification is {cls} but cborcheck finds {derived} ({sorted(kinds)})")
        if cls == "malformed":
            if kind not in kinds:
                errs.append(f"error.kind {kind} not among cborcheck findings {sorted(kinds)}")
            if kind != "duplicate_key" and c2err is None:
                errs.append(f"cbor2 accepts the input but kind is {kind}")
            if kind == "duplicate_key" and c2err is not None:
                errs.append(f"duplicate_key input must be otherwise decodable by cbor2: {c2err}")
        else:
            if c2err is not None:
                errs.append(f"schema_invalid input must be decodable: cbor2 says {c2err}")
    else:
        try:
            decoded = json_strict(inp["json"])
            derived, jkind = "schema_invalid", None
        except ValueError as e:
            decoded, derived, jkind = None, "malformed", e.args[0]
        if cls != derived:
            errs.append(f"classification is {cls} but a strict JSON parser finds {derived}")
        if cls == "malformed" and kind != jkind:
            errs.append(f"error.kind is {kind} but the JSON parser reports {jkind}")
    if cls == "schema_invalid" and not errs:
        errs += _check_error_target(case, decoded, schema_text)
    return errs


def _plain(obj):
    """_Num -> int/float for numeric comparison."""
    if isinstance(obj, _Num):
        return Decimal(obj)
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    return obj


def _check_error_target(case, decoded, schema_text):
    err, kind = case["error"], case["error"]["kind"]
    try:
        segs = parse_path(err["path"])
    except ValueError as e:
        return [str(e)]
    found, obj = walk_decoded(_plain(decoded), segs)
    if kind == "missing_field":
        if not segs or segs[-1][0] != "key":
            return ["missing_field path must end in a field name"]
        found_parent, parent = walk_decoded(_plain(decoded), segs[:-1])
        if not found_parent or not isinstance(parent, dict):
            return [f"missing_field: parent of {err['path']!r} is not a map in the input"]
        if walk_decoded(parent, segs[-1:])[0]:
            return [f"missing_field: {err['path']!r} is present in the input"]
        return []
    if not found:
        return [f"path {err['path']!r} does not resolve in the input"]
    if kind == "out_of_range":
        return _check_range(err.get("constraint"), obj, schema_text)
    if kind == "unknown_discriminant" and "discriminant" not in err:
        return ["unknown_discriminant must name the offending discriminant (REQ-RT-380)"]
    return []


def _check_range(constraint, num, schema_text):
    if not constraint:
        return ["out_of_range needs error.constraint"]
    m = re.fullmatch(r"(-?[0-9.]+)\.\.(-?[0-9.]+)", constraint)
    if not m:
        return [f"constraint {constraint!r} is not lo..hi"]
    if constraint not in schema_text:
        return [f"constraint {constraint!r} does not occur in the schema"]
    if isinstance(num, bool) or not isinstance(num, (int, float, Decimal)):
        return [f"out_of_range target is not a number: {num!r}"]
    lo, hi = Decimal(m.group(1)), Decimal(m.group(2))
    if lo <= Decimal(num) <= hi:
        return [f"value {num} lies inside {constraint}"]
    return []


def _subset(a, b, errs, path="$"):
    """a's entries all occur in b with equal values (absent_default)."""
    if isinstance(b, dict) and isinstance(a, dict):
        for k, v in a.items():
            if k not in b:
                errs.append(f"{path}.{k} is not in the canonical value")
            else:
                _subset(v, b[k], errs, f"{path}.{k}")
    elif _plain(a) != _plain(b):
        errs.append(f"{path}: {a!r} != {b!r}")


def json_equivalent(input_text, canon_text, variance):
    """Parse both texts and compare them, allowing exactly the relaxation
    `variance` names. Returns a list of problems (empty = equivalent)."""
    errs, used = [], []
    try:
        a = json_strict(input_text, hook=lambda ps: ps)
        b = json_strict(canon_text, hook=lambda ps: ps)
    except ValueError as e:
        return [f"not parseable: {e}"]

    def walk(x, y, path):
        if isinstance(y, list) and y and isinstance(y[0], tuple):  # object (pairs)
            if not (isinstance(x, list) and (not x or isinstance(x[0], tuple))):
                return errs.append(f"{path}: expected an object")
            xd, yd = dict(x), dict(y)
            if variance == "absent_default":
                for k in xd:
                    if k not in yd:
                        errs.append(f"{path}.{k} not in canonical")
                if len(xd) < len(yd):
                    used.append(path)
            elif set(xd) != set(yd):
                return errs.append(f"{path}: member names differ")
            for k in xd:
                if k in yd:
                    walk(xd[k], yd[k], f"{path}.{k}")
            if variance == "member_order" and [k for k, _ in x] != [k for k, _ in y]:
                used.append(path)
        elif isinstance(y, list):
            if not isinstance(x, list) or len(x) != len(y):
                return errs.append(f"{path}: arrays differ in shape")
            for i, (p, q) in enumerate(zip(x, y)):
                walk(p, q, f"{path}[{i}]")
        elif isinstance(y, _Num):
            if isinstance(x, _Num):
                if x == y:
                    return
                if variance in ("number_spelling", "int_as_number") and Decimal(x) == Decimal(y):
                    used.append(path)
                else:
                    errs.append(f"{path}: number spelled {x} where {y} is canonical")
            elif isinstance(x, str) and variance == "int_as_string" and re.fullmatch(r"-?[0-9]+", x) \
                    and Decimal(x) == Decimal(y):
                used.append(path)
            else:
                errs.append(f"{path}: {x!r} is not a permitted spelling of {y}")
        elif isinstance(y, str):
            if isinstance(x, _Num) and variance == "int_as_number" and re.fullmatch(r"-?[0-9]+", y) \
                    and Decimal(x) == Decimal(y):
                used.append(path)
            elif isinstance(x, str) and not isinstance(x, _Num):
                if x == y:
                    return
                if variance == "base64_padding" and x.rstrip("=") == y and "=" not in y:
                    used.append(path)
                else:
                    errs.append(f"{path}: {x!r} != {y!r}")
            else:
                errs.append(f"{path}: {x!r} != {y!r}")
        elif x != y or type(x) is not type(y):
            errs.append(f"{path}: {x!r} != {y!r}")

    walk(a, b, "$")
    if input_text == canon_text:
        errs.append("input is identical to the canonical json")
    elif not used and variance not in ("whitespace", "string_escapes"):
        errs.append(f"input does not exhibit variance {variance}")
    return errs


def _has_nonfinite(v):
    for tag, payload in _walk_tags(v):
        if tag in ("f16", "f32", "f64") and payload in ("NaN", "Infinity", "-Infinity"):
            return True
    return False


def _walk_tags(v):
    (tag, payload), = v.items()
    yield tag, payload
    if tag == "array":
        for x in payload:
            yield from _walk_tags(x)
    if tag == "map":
        for k, x in payload:
            yield from _walk_tags(k)
            yield from _walk_tags(x)


def check_noncanonical(case):
    """DoD clause 2: the input is valid and acceptable, genuinely non-canonical
    in the declared way, and equivalent to the canonical vector."""
    errs = []
    variance, inp = case["variance"], case["input"]
    errs += check_cbor(case)
    if "json" in case:  # the canonical triple is a 1.2-style vector
        errs += check_json(case)
    elif not _has_nonfinite(case["value"]):
        errs.append("json may be omitted only when the value contains NaN or an infinity")
    if "cbor" in inp:
        if variance in JSON_VARIANCES:
            return errs + [f"variance {variance} needs a json input"]
        data = bytes.fromhex(inp["cbor"])
        a = cborcheck.analyze(data)
        if a.malformed or a.invalid:
            errs.append(f"input is not valid CBOR: {a.malformed + a.invalid}")
        if a.outside_subset:
            errs.append(f"input uses constructs outside the §3 subset: {a.outside_subset}")
        try:
            obj = cbor2_strict(data)
        except Exception as e:
            return errs + [f"cbor2 rejects the input: {e}"]
        if data.hex() == case["cbor"]:
            errs.append("input equals the canonical cbor")
        if variance == "absent_default":
            _subset(obj, cbor2.loads(bytes.fromhex(case["cbor"])), errs)
            if len(obj) >= len(cbor2.loads(bytes.fromhex(case["cbor"]))):
                errs.append("absent_default input omits nothing")
        else:
            want = VARIANCE_CATEGORY.get(variance)
            if want is None:
                errs.append(f"variance {variance} does not apply to cbor")
            elif want not in {c for c, _ in a.nondeterministic}:
                errs.append(f"input shows no {want} departure from RFC 8949 §4.2")
            errs += value_matches(case["value"], obj, ordered=False)
    else:
        if variance in VARIANCE_CATEGORY:
            return errs + [f"variance {variance} needs a cbor input"]
        errs += json_equivalent(inp["json"], case["json"], variance)
    return errs


def check_encode_error(case, schema_text):
    """An encode that must fail: confirm each expected failure is real, and each
    expected success against the 1.2 machinery."""
    errs = []
    expect = case["expect"]
    for enc in ("cbor", "json"):
        e = expect[enc]
        if isinstance(e, dict):
            errs += _encode_failure_is_real(case, enc, e["error"], schema_text)
        elif enc == "cbor":
            errs += check_cbor(dict(case, cbor=e))
        else:
            errs += check_json(dict(case, json=e))
    return errs


def _encode_failure_is_real(case, enc, error, schema_text):
    try:
        segs = parse_path(error["path"])
    except ValueError as e:
        return [str(e)]
    found, leaf = walk_value(case["value"], segs)
    if not found:
        return [f"{enc}: path {error['path']!r} does not resolve in value"]
    (tag, payload), = leaf.items()
    if error["kind"] == "out_of_range":
        if tag not in ("uint", "int", "f16", "f32", "f64"):
            return [f"{enc}: out_of_range target is a {tag}"]
        return _check_range(error.get("constraint"), Decimal(payload) if tag in ("uint", "int") else Decimal(str(_float_of(payload))), schema_text)
    if tag not in ("f16", "f32", "f64"):
        return [f"{enc}: not_representable target is a {tag}"]
    x = _float_of(payload)
    nonfinite = x != x or x in (math.inf, -math.inf)
    half_bad = tag == "f16" and not nonfinite and not _fits("e", x)
    if enc == "json" and (nonfinite or half_bad):
        return []
    if enc == "cbor" and half_bad:
        return []
    return [f"{enc}: {payload} in a {tag} field encodes fine, so no error is expected"]


# --- evolution pairs (slice 1.4) ---------------------------------------------

SCENARIOS = ["add_optional_field", "add_defaulted_field", "add_uint_keyed_field", "append_array_element",
             "declaration_order_independent", "nested_struct_gains_field", "unknown_value_types"]


def _seg(parent, key):
    """REQ-RT-066: append one segment to a path."""
    if isinstance(key, int):
        return f"{parent}[{key}]" if isinstance(parent, tuple) else f"{parent}.{key}" if parent else str(key)
    return f"{parent}.{key}" if parent else key


def _extras(a, b, path, out, errs):
    """Walk `a` against `b`: everything in `b` must occur in `a` with an equal
    value; entries that occur only in `a` are appended to `out` as paths."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k, v in b.items():
            if k not in a:
                errs.append(f"{path or '<root>'}: {k!r} is missing")
            else:
                _extras(a[k], v, _seg(path, k), out, errs)
        for k in a:
            if k not in b:
                out.append(_seg(path, k if isinstance(k, str) else str(k)))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) < len(b):
            errs.append(f"{path or '<root>'}: array has {len(a)} element(s), {len(b)} expected")
        for i in range(min(len(a), len(b))):
            _extras(a[i], b[i], f"{path}[{i}]", out, errs)
        for i in range(len(b), len(a)):
            out.append(f"{path}[{i}]")
    elif _plain(a) != _plain(b) or type(a) is not type(b) and not (
            isinstance(a, (_Num, Decimal)) and isinstance(b, (_Num, Decimal))):
        errs.append(f"{path or '<root>'}: {a!r} != {b!r}")


def _generic(case, which):
    """The generic decoded form of the case's `input`, or of its own canonical
    `cbor`/`json` (`which` = "input" | "output"), in the input's encoding."""
    inp = case["input"]
    if "cbor" in inp:
        return cbor2_strict(bytes.fromhex(inp["cbor"] if which == "input" else case["cbor"]))
    return _plain(json_strict(inp["json"] if which == "input" else case["json"]))


def json_compact(obj):
    """Compact JSON text of a parsed document with numbers kept as spelled."""
    if isinstance(obj, dict):
        return "{" + ",".join(json_string(k) + ":" + json_compact(v) for k, v in obj.items()) + "}"
    if isinstance(obj, list):
        return "[" + ",".join(json_compact(v) for v in obj) + "]"
    if isinstance(obj, _Num):
        return str(obj)
    if isinstance(obj, str):
        return json_string(obj)
    return {True: "true", False: "false", None: "null"}[obj]


def check_evolution_case(case, texts):
    """Slice 1.4 plan §4.2. `texts` maps "v1"/"v2" to the pair's schema text."""
    errs = check_cbor(case) + check_json(case)  # the reader's vector is a positive vector
    inp = case["input"]
    if "cbor" in inp:
        data = bytes.fromhex(inp["cbor"])
        errs += [f"input: {e}" for e in cborcheck.check(data)]
    else:
        try:
            doc = json_strict(inp["json"], hook=lambda ps: dict(ps))
        except ValueError as e:
            return errs + [f"input is not valid JSON: {e}"]
        if json_compact(doc) != inp["json"]:
            errs.append("input json is not the writer's compact canonical text")
    if errs:
        return errs
    reader, writer = ("v1", "v2") if case["direction"] == "new_to_old" else ("v2", "v1")
    for v in ("v1", "v2"):
        if case["root"] not in schema_roots(texts[v]):
            errs.append(f"root {case['root']!r} is not defined in {v}")
    inp_g, out_g = _generic(case, "input"), _generic(case, "output")
    found, mism = [], []
    if case["direction"] == "new_to_old":
        _extras(inp_g, out_g, "", found, mism)
        want = sorted(case["ignored"])
    else:
        _extras(out_g, inp_g, "", found, mism)
        want = sorted(case.get("populated", []))
    errs += mism
    if sorted(found) != want:
        label = "ignored" if case["direction"] == "new_to_old" else "populated"
        errs.append(f"{label} is {want} but the input and the reader's value differ at {sorted(found)}")
    return errs


def check_evolution_file(rel, doc, schema_texts, req_ids):
    errs, pair = [], doc["pair"]
    if rel != f"cases/evolution/{pair}.json":
        errs.append(f"{rel}: must live at cases/evolution/{pair}.json")
    for v in ("v1", "v2"):
        if f"evolution/{pair}/{v}.cddl" not in schema_texts:
            errs.append(f"{rel}: schemas/evolution/{pair}/{v}.cddl does not exist")
    if errs:
        return errs
    if schema_texts[f"evolution/{pair}/v1.cddl"] == schema_texts[f"evolution/{pair}/v2.cddl"]:
        errs.append(f"{rel}: v1 and v2 are identical")
    scenarios = {c["scenario"] for c in doc["cases"]}
    if len(scenarios) != 1:
        errs.append(f"{rel}: a pair has exactly one scenario, found {sorted(scenarios)}")
    for c in doc["cases"]:
        if c["id"].split("/")[0] != pair:
            errs.append(f"{c['id']}: id stem must be {pair!r}")
        for r in c["requirements"]:
            if r not in req_ids:
                errs.append(f"{c['id']}: {r} does not exist in specs.md")
    for direction in ("old_to_new", "new_to_old"):
        for enc in ("cbor", "json"):
            if not any(c["direction"] == direction and enc in c["input"] for c in doc["cases"]):
                errs.append(f"{rel}: no {direction} case with a {enc} input")
    return errs


def check_scenarios_complete(docs):
    have = {c["scenario"] for d in docs.values() if d["kind"] == "evolution" for c in d["cases"]}
    return [f"scenario {s}: no pair" for s in SCENARIOS if s not in have]


# --- the coverage manifest (slice 1.4) -----------------------------------------

EXEMPT_CATEGORIES = ["api_shape", "dependency_policy", "build_constraint", "optional_behaviour",
                     "configuration", "non_guarantee"]


def section9_requirements(specs_text):
    """The REQ ids of every bullet in specs.md section 9 (introduction and 9.x)."""
    m = re.search(r"^## 9\. .*?\n(.*?)^## 10\. ", specs_text, re.S | re.M)
    if not m:
        raise ValueError("specs.md: section 9 not found")
    ids = re.findall(r"^- \*\*(REQ-[A-Z]+-[0-9]{3})\*\*", m.group(1), re.M)
    if not ids:
        raise ValueError("specs.md: section 9 has no requirements")
    return ids


def plan_slices(plan_text):
    return set(re.findall(r"^### ([0-9]+\.[0-9]+) — ", plan_text, re.M))


def derive_coverage(docs, req_ids, implied):
    """{req: sorted case ids}, over `req_ids`, from case tags and kind-implied ids."""
    cov = {r: set() for r in req_ids}
    for doc in docs.values():
        for c in doc["cases"]:
            for r in set(c["requirements"]) | set(implied.get(doc["kind"], [])):
                if r in cov:
                    cov[r].add(c["id"])
    return {r: sorted(v) for r, v in cov.items()}


def build_coverage(docs, req_ids, previous):
    """The coverage.json document: regenerated `cases`, preserved hand-written
    `implied_by_kind` and `exempt` entries."""
    implied = previous.get("implied_by_kind", {})
    derived = derive_coverage(docs, req_ids, implied)
    old = previous.get("requirements", {})
    reqs = {}
    for r in req_ids:
        entry = {}
        if derived[r]:
            entry["cases"] = derived[r]
        if "exempt" in old.get(r, {}):
            entry["exempt"] = old[r]["exempt"]
        reqs[r] = entry
    return {"manifest_version": 1, "scope": "specs.md §9", "implied_by_kind": implied, "requirements": reqs}


def check_requirement_coverage(cov, docs, specs_text, plan_text):
    """Slice 1.4 DoD: every §9 requirement has a case or a recorded exemption;
    the file is fresh; exemptions are disciplined."""
    errs = []
    req_ids = section9_requirements(specs_text)
    slices = plan_slices(plan_text)
    implied = cov.get("implied_by_kind", {})
    for kind, ids in implied.items():
        for r in ids:
            if r not in req_ids:
                errs.append(f"implied_by_kind {kind}: {r} is not a specs.md §9 requirement")
    entries = cov.get("requirements", {})
    for r in sorted(set(entries) - set(req_ids)):
        errs.append(f"{r}: in coverage.json but not a requirement in specs.md §9")
    derived = derive_coverage(docs, req_ids, implied)
    for r in req_ids:
        e = entries.get(r)
        if e is None:
            errs.append(f"{r}: missing from coverage.json (no case and no exemption)")
            continue
        have, ex = derived[r], e.get("exempt")
        if e.get("cases", []) != have:
            errs.append(f"{r}: coverage.json cases are stale (run --write-coverage)")
        if not have and not ex:
            errs.append(f"{r}: no corpus case and no recorded exemption")
        if have and ex:
            errs.append(f"{r}: stale exemption: it now has cases ({len(have)})")
        if ex:
            if ex.get("category") not in EXEMPT_CATEGORIES:
                errs.append(f"{r}: exemption category must be one of {EXEMPT_CATEGORIES}")
            if not ex.get("reason", "").strip():
                errs.append(f"{r}: exemption needs a reason")
            t = ex.get("tested_in")
            if t is None:
                if ex.get("category") != "non_guarantee":
                    errs.append(f"{r}: only a non_guarantee may omit tested_in")
            elif not re.fullmatch(r"slice [0-9]+\.[0-9]+", t) or t.split()[1] not in slices:
                errs.append(f"{r}: tested_in {t!r} is not a slice heading in plan.md")
    return errs


# --- driver ---------------------------------------------------------------


def load_docs(root, case_files):
    return {rel: load(root / rel) for rel in case_files}


def run(root, specs, check_format):
    errs = []
    schema = load(root / "manifest.schema.json")
    errs += check_manifest_schema(schema)
    index = load(root / "index.json")
    schema_files = sorted(p.relative_to(root / "schemas").as_posix() for p in (root / "schemas").rglob("*.cddl"))
    top_schemas = [f for f in schema_files if "/" not in f]
    case_files = sorted(p.relative_to(root).as_posix() for p in (root / "cases").rglob("*.json"))
    errs += check_index(index, schema_files, case_files)
    docs = load_docs(root, case_files)
    for rel, doc in docs.items():
        errs += check_case_instance(schema, doc, rel)
    if errs:
        return errs  # structure first: later checks assume a valid shape
    specs_text = specs.read_text(encoding="utf-8")
    plan_text = (specs.parent / "plan.md").read_text(encoding="utf-8")
    errs += check_coverage(load(root / "construct-coverage.json"), specs_text, {f[:-5] for f in top_schemas})
    schema_texts = {f: (root / "schemas" / f).read_text(encoding="utf-8") for f in schema_files}
    req_ids = set(re.findall(r"REQ-[A-Z]+-[0-9]{3}", specs_text))
    errs += check_schemas_have_cases(top_schemas, docs)
    errs += check_unique_ids(docs)
    errs += check_scenarios_complete(docs)
    for rel, doc in docs.items():
        if doc["kind"] == "evolution":
            errs += check_evolution_file(rel, doc, schema_texts, req_ids)
            pair = doc["pair"]
            texts = {v: schema_texts.get(f"evolution/{pair}/{v}.cddl", "") for v in ("v1", "v2")}
            for case in doc["cases"]:
                errs += [f"{case['id']}: {e}" for e in check_evolution_case(case, texts)]
            continue
        errs += check_case_file(rel, doc, schema_texts, req_ids)
        stext = schema_texts.get(doc["schema"], "")
        for case in doc["cases"]:
            if doc["kind"] == "positive":
                found = check_cbor(case) + check_json(case)
            elif doc["kind"] == "negative":
                found = check_negative(case, stext)
            elif doc["kind"] == "noncanonical":
                found = check_noncanonical(case)
            else:
                found = check_encode_error(case, stext)
            errs += [f"{case['id']}: {e}" for e in found]
    cov_path = root / "coverage.json"
    if not cov_path.exists():
        errs.append("coverage.json is missing (run --write-coverage)")
    else:
        errs += check_requirement_coverage(load(cov_path), docs, specs_text, plan_text)
    if check_format:
        for rel in ["manifest.schema.json", "index.json", "construct-coverage.json", "coverage.json", *case_files]:
            if (root / rel).exists():
                errs += check_format_text((root / rel).read_text(encoding="utf-8"), rel)
    return errs


def write_coverage(root, specs):
    case_files = sorted(p.relative_to(root).as_posix() for p in (root / "cases").rglob("*.json"))
    path = root / "coverage.json"
    previous = load(path) if path.exists() else {}
    doc = build_coverage(load_docs(root, case_files), section9_requirements(specs.read_text(encoding="utf-8")), previous)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path


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


def _doc(kind, case):
    return {"manifest_version": 1, "schema": "s.cddl", "kind": kind, "cases": [case]}


def _neg(**kw):
    c = {"id": "s/a", "root": "T", "description": "d", "requirements": ["REQ-RT-060"],
         "derivation": "hand-encoded", "input": {"cbor": "a1"}, "classification": "malformed",
         "error": {"kind": "truncated"}}
    c.update(kw)
    return _doc("negative", c)


def _noncanon(**kw):
    c = {"id": "s/a", "root": "T", "description": "d", "requirements": ["REQ-RT-180"],
         "derivation": "hand-encoded", "variance": "indefinite_length", "input": {"cbor": "9f01ff"},
         "value": {"array": [{"uint": "1"}]}, "cbor": "8101", "json": "[1]"}
    c.update(kw)
    return _doc("noncanonical", c)


def _enc(**kw):
    c = {"id": "s/a", "root": "T", "description": "d", "requirements": ["REQ-RT-210"],
         "derivation": "cbor2", "value": {"f64": "NaN"},
         "expect": {"cbor": "f97e00", "json": {"error": {"kind": "not_representable", "path": ""}}}}
    c.update(kw)
    return _doc("encode_error", c)


def _evo_doc(**kw):
    c = {"id": "p/a", "root": "T", "description": "d", "requirements": ["REQ-COMPAT-020"],
         "derivation": "cbor2", "scenario": "add_optional_field", "direction": "new_to_old",
         "input": {"cbor": "a2616101616202"}, "ignored": ["b"],
         "value": {"map": [[{"tstr": "a"}, {"uint": "1"}]]}, "cbor": "a1616101", "json": '{"a":1}'}
    c.update(kw)
    return {"manifest_version": 1, "pair": "p", "kind": "evolution", "cases": [c]}


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

    # --- slice 1.3 ---------------------------------------------------------

    def test_record_shapes_accept_good_records(self):
        """REQ-ARCH-060: negative, noncanonical and encode_error records are defined."""
        for d in (_neg(), _noncanon(), _enc(),
                  _neg(classification="schema_invalid", input={"json": "{}"},
                       error={"kind": "type_mismatch", "path": "a.b[2]"}),
                  _neg(input={"cbor": ""}),
                  _enc(expect={"cbor": {"error": {"kind": "out_of_range", "path": "level", "constraint": "0..255"}},
                               "json": {"error": {"kind": "out_of_range", "path": "level"}}})):
            self.assertEqual(check_case_instance(self.schema, d, "x"), [], d)

    def test_record_shapes_reject_bad_records(self):
        """REQ-ARCH-060: the shapes are closed and internally consistent."""
        bad = [
            _neg(input={"cbor": "a1", "json": "{}"}),                       # both encodings
            _neg(input={}),                                                  # neither
            _neg(input={"cbor": "A1"}),                                      # not lowercase hex
            {**_neg(), "cases": [{k: v for k, v in _neg()["cases"][0].items() if k != "classification"}]},
            _neg(error={"kind": "gremlins"}),                                # unknown kind
            _neg(classification="invalid"),                                  # not one of the DoD's two
            _neg(error={"kind": "truncated", "path": "a"}),                  # malformed carries no path
            _neg(classification="schema_invalid", error={"kind": "type_mismatch"}),  # path required
            _neg(classification="schema_invalid", error={"kind": "truncated", "path": ""}),  # wrong class
            _neg(error={"kind": "type_mismatch"}),                           # wrong class, other way
            _noncanon(variance="shuffled"),
            _noncanon(input={"cbor": "9f01ff", "json": "[1]"}),
            _enc(expect={"cbor": "f97e00", "json": "null"}),                # neither side is an error
            _enc(expect={"json": {"error": {"kind": "not_representable", "path": ""}}}),
            _enc(expect={"cbor": "f97e00", "json": {"error": {"kind": "malformed", "path": ""}}}),
            _doc("evolution", {"id": "s/a"}),                                # still reserved for 1.4
        ]
        for d in bad:
            self.assertTrue(check_case_instance(self.schema, d, "x"), d)

    def test_parse_path_grammar(self):
        """REQ-RT-066: the path grammar."""
        self.assertEqual(parse_path(""), [])
        self.assertEqual(parse_path("[1]"), [("idx", 1)])
        self.assertEqual(parse_path("items[2].price"), [("key", "items"), ("idx", 2), ("key", "price")])
        self.assertEqual(parse_path('stock[7].qty'), [("key", "stock"), ("idx", 7), ("key", "qty")])
        self.assertEqual(parse_path('scores["a\\"b"]'), [("key", "scores"), ("tkey", 'a"b')])
        self.assertEqual(parse_path("9.x"), [("key", "9"), ("key", "x")])
        for bad in [".a", "a..b", "a[", "a[x]", "a b", "[1]x"]:
            with self.assertRaises(ValueError, msg=bad):
                parse_path(bad)

    def test_negative_classification_cbor(self):
        """REQ-RT-300/310/315, REQ-RT-060: two parsers agree on the class."""
        def neg(cbor, cls, kind, path=None):
            err = {"kind": kind}
            if path is not None:
                err["path"] = path
            return {"input": {"cbor": cbor}, "classification": cls, "error": err}
        ok = [
            neg("a2616101", "malformed", "truncated"),                       # map of 2, one pair
            neg("a0 00".replace(" ", ""), "malformed", "trailing_data"),
            neg("1c", "malformed", "syntax"),
            neg("62c328", "malformed", "invalid_utf8"),
            neg("a2616101616102", "malformed", "duplicate_key"),
            neg("a1616101", "schema_invalid", "type_mismatch", ""),         # a map where a Person-like root is wanted
            neg("c11a514b67b0", "schema_invalid", "type_mismatch", ""),     # tag: well-formed
        ]
        for c in ok:
            self.assertEqual(check_negative(c, ""), [], c)
        wrong = [
            neg("a2616101", "schema_invalid", "type_mismatch", ""),         # actually truncated
            neg("a1616101", "malformed", "truncated"),                       # actually fine
            neg("62c328", "malformed", "truncated"),                         # wrong kind
            neg("a2616101616102", "schema_invalid", "type_mismatch", ""),    # duplicate keys are malformed (D-010)
            neg("a1616101", "schema_invalid", "type_mismatch", "nope"),      # path does not resolve
        ]
        for c in wrong:
            self.assertTrue(check_negative(c, ""), c)

    def test_negative_classification_json(self):
        """REQ-RT-300/310, REQ-RT-070: strict JSON parsing decides the class."""
        def neg(text, cls, kind, path=None):
            err = {"kind": kind}
            if path is not None:
                err["path"] = path
            return {"input": {"json": text}, "classification": cls, "error": err}
        for c in [neg('{"a":1', "malformed", "truncated"), neg("", "malformed", "truncated"),
                  neg('{"a":1}x', "malformed", "trailing_data"), neg("{'a':1}", "malformed", "syntax"),
                  neg('{"a":1,}', "malformed", "syntax"), neg("NaN", "malformed", "syntax"),
                  neg('{"a":1,"a":2}', "malformed", "duplicate_key"),
                  neg('{"a":"x"}', "schema_invalid", "type_mismatch", "a")]:
            self.assertEqual(check_negative(c, ""), [], c)
        for c in [neg('{"a":1', "schema_invalid", "type_mismatch", ""),
                  neg('{"a":"x"}', "malformed", "syntax"),
                  neg('{"a":1,"a":2}', "malformed", "syntax")]:
            self.assertTrue(check_negative(c, ""), c)

    def test_negative_missing_field_and_range_targets(self):
        """REQ-RT-060/240: paths must resolve; out_of_range needs a real range and a real excess."""
        mf = {"input": {"json": '{"b":1}'}, "classification": "schema_invalid",
              "error": {"kind": "missing_field", "path": "a"}}
        self.assertEqual(check_negative(mf, ""), [])
        mf["error"]["path"] = "b"
        self.assertTrue(check_negative(mf, ""))
        oor = {"input": {"json": '{"level":256}'}, "classification": "schema_invalid",
               "error": {"kind": "out_of_range", "path": "level", "constraint": "0..255"}}
        self.assertEqual(check_negative(oor, "Byte = 0..255"), [])
        self.assertTrue(check_negative(oor, "Byte = 0..256"))               # constraint not in schema
        oor["input"]["json"] = '{"level":255}'
        self.assertTrue(check_negative(oor, "Byte = 0..255"))               # in range after all

    def test_negative_flip_is_detected_for_every_real_negative(self):
        """DoD clause 1: swapping malformed and schema_invalid fails the check."""
        root = CONFORMANCE
        for p in sorted((root / "cases" / "negative").glob("*.json")) if (root / "cases" / "negative").exists() else []:
            doc = load(p)
            stext = (root / "schemas" / doc["schema"]).read_text(encoding="utf-8")
            for case in doc["cases"]:
                flipped = dict(case, classification="malformed" if case["classification"] == "schema_invalid" else "schema_invalid")
                self.assertTrue(check_negative(flipped, stext), case["id"])

    def test_noncanonical_cbor(self):
        """REQ-RT-180: the input is valid, really departs in the declared way, and decodes to value."""
        def nc(cbor, variance, canon="83010203", value=None):
            value = value or {"array": [{"uint": "1"}, {"uint": "2"}, {"uint": "3"}]}
            return {"variance": variance, "input": {"cbor": cbor}, "value": value, "cbor": canon,
                    "json": "[1,2,3]"}
        self.assertEqual(check_noncanonical(nc("9f010203ff", "indefinite_length")), [])
        self.assertEqual(check_noncanonical(nc("83 01 1802 03".replace(" ", ""), "non_shortest_head")), [])
        self.assertTrue(check_noncanonical(nc("83010203", "indefinite_length")))        # actually canonical
        self.assertTrue(check_noncanonical(nc("9f010203ff", "non_shortest_head")))      # wrong variance
        self.assertTrue(check_noncanonical(nc("9f010203", "indefinite_length")))        # unterminated
        self.assertTrue(check_noncanonical(nc("9f010204ff", "indefinite_length")))      # decodes to another value
        self.assertTrue(check_noncanonical(nc("9f010203ff", "whitespace")))             # json variance, cbor input
        m = {"map": [[{"tstr": "a"}, {"uint": "1"}], [{"tstr": "b"}, {"uint": "2"}]]}
        self.assertEqual(check_noncanonical({"variance": "unsorted_keys", "input": {"cbor": "a2616202616101"},
                                             "value": m, "cbor": "a2616101616202", "json": '{"a":1,"b":2}'}), [])

    def test_json_equivalent(self):
        """REQ-RT-175/178/179/200/220/176: only the named relaxation is allowed."""
        c = '{"a":1,"b":"x"}'
        self.assertEqual(json_equivalent(' { "a" : 1 , "b" : "x" } ', c, "whitespace"), [])
        self.assertEqual(json_equivalent('{"a":1,"b":"\\u0078"}', c, "string_escapes"), [])
        self.assertEqual(json_equivalent('{"a":1.0,"b":"x"}', c, "number_spelling"), [])
        self.assertEqual(json_equivalent('{"a":"1","b":"x"}', c, "int_as_string"), [])
        self.assertEqual(json_equivalent('{"b":"x","a":1}', c, "member_order"), [])
        self.assertEqual(json_equivalent('{"a":1}', c, "absent_default"), [])
        self.assertEqual(json_equivalent('{"a":9007199254740993}', '{"a":"9007199254740993"}', "int_as_number"), [])
        self.assertEqual(json_equivalent('{"k":"AQI"}', '{"k":"AQI"}'.replace('AQI','AQI'), "base64_padding") != [], True)  # identical text
        self.assertEqual(json_equivalent('{"k":"AQI="}', '{"k":"AQI"}', "base64_padding"), [])
        for variance, text in [("whitespace", '{"a":1.0,"b":"x"}'), ("whitespace", '{"a":"1","b":"x"}'),
                               ("number_spelling", '{"a":"1","b":"x"}'), ("int_as_string", '{"a":2,"b":"x"}'),
                               ("member_order", '{"a":1,"b":"x"}'), ("int_as_string", '{"a":1.5,"b":"x"}'),
                               ("whitespace", '{"a":1,"b":"y"}'), ("whitespace", '{"a":1}'),
                               ("absent_default", '{"a":1,"b":"x","c":1}'), ("whitespace", c)]:
            self.assertTrue(json_equivalent(text, c, variance), (variance, text))

    def test_encode_error_failures_must_be_real(self):
        """REQ-RT-210/250/255: an expected failure must really be one."""
        def enc(value, expect):
            return {"value": value, "expect": expect}
        nan = {"map": [[{"tstr": "ratio"}, {"f64": "NaN"}]]}
        err = lambda kind, path, **kw: {"error": dict(kind=kind, path=path, **kw)}
        self.assertEqual(check_encode_error(enc(nan, {"cbor": "a1657261746" + "96f" + "f97e00" if False else "a165726174696ff97e00", "json": err("not_representable", "ratio")}), ""), [])
        self.assertTrue(check_encode_error(enc({"map": [[{"tstr": "ratio"}, {"f64": "1.5"}]]},
                                               {"cbor": "a165726174696ff93e00", "json": err("not_representable", "ratio")}), ""))
        half = {"map": [[{"tstr": "half"}, {"f16": "1.1"}]]}
        self.assertEqual(check_encode_error(enc(half, {"cbor": err("not_representable", "half"),
                                                       "json": err("not_representable", "half")}), ""), [])
        ok_half = {"map": [[{"tstr": "half"}, {"f16": "1.5"}]]}
        self.assertTrue(check_encode_error(enc(ok_half, {"cbor": err("not_representable", "half"),
                                                         "json": err("not_representable", "half")}), ""))
        lvl = {"map": [[{"tstr": "level"}, {"uint": "256"}]]}
        both = {"cbor": err("out_of_range", "level", constraint="0..255"),
                "json": err("out_of_range", "level", constraint="0..255")}
        self.assertEqual(check_encode_error(enc(lvl, both), "Byte = 0..255"), [])
        self.assertTrue(check_encode_error(enc({"map": [[{"tstr": "level"}, {"uint": "255"}]]}, both), "Byte = 0..255"))

    # --- slice 1.4 ---------------------------------------------------------

    def test_evolution_record_shape(self):
        """REQ-COMPAT-010/020: the evolution record and its `pair` envelope."""
        self.assertEqual(check_case_instance(self.schema, _evo_doc(), "x"), [])
        ok_old = _evo_doc(direction="old_to_new", populated=["b"])
        del ok_old["cases"][0]["ignored"]
        self.assertEqual(check_case_instance(self.schema, ok_old, "x"), [])
        bad = [
            dict(_evo_doc(), schema="s.cddl"),                          # schema on an evolution file
            {k: v for k, v in _evo_doc().items() if k != "pair"},       # pair missing
            _evo_doc(scenario="rename_field"),
            _evo_doc(direction="sideways"),
            _evo_doc(ignored=[]),                                        # new_to_old needs something ignored
            _evo_doc(populated=["b"]),                                   # populated on new_to_old
            _evo_doc(direction="old_to_new"),                            # ignored on old_to_new
            dict(_good_case(), pair="p"),                                # pair on a positive file
        ]
        for d in bad:
            self.assertTrue(check_case_instance(self.schema, d, "x"), d)

    def test_index_is_path_based(self):
        """REQ-ARCH-060: v1.cddl in two pairs does not collide."""
        idx = {"schemas": ["a.cddl", "evolution/p/v1.cddl", "evolution/q/v1.cddl"], "cases": []}
        self.assertEqual(check_index(idx, ["a.cddl", "evolution/p/v1.cddl", "evolution/q/v1.cddl"], []), [])
        self.assertTrue(check_index(idx, ["a.cddl", "evolution/p/v1.cddl"], []))
        self.assertEqual(check_schemas_have_cases(["a.cddl"], {"x": _good_case(), }), ["a.cddl: no positive case file"])

    def test_evolution_case_verification(self):
        """REQ-COMPAT-020/025: extras are really extra, really dropped, input is canonical."""
        texts = {"v1": "T = {a: uint}\n", "v2": "T = {a: uint, ? b: uint}\n"}
        good = _evo_doc()["cases"][0]
        self.assertEqual(check_evolution_case(good, texts), [])
        self.assertTrue(check_evolution_case(dict(good, ignored=["a"]), texts))          # wrong path
        self.assertTrue(check_evolution_case(dict(good, ignored=["b", "c"]), texts))     # claims too much
        self.assertTrue(check_evolution_case(dict(good, input={"cbor": "a2616202616101"}), texts))   # non-canonical input
        self.assertTrue(check_evolution_case(dict(good, input={"cbor": "a1616101"}), texts))         # no extras at all
        self.assertTrue(check_evolution_case(dict(good, cbor="a1616102", value={"map": [[{"tstr": "a"}, {"uint": "2"}]]}, json='{"a":2}'), texts))
        self.assertTrue(check_evolution_case(dict(good, root="Missing"), texts))
        js = dict(good, input={"json": '{"a":1,"b":2}'})
        self.assertEqual(check_evolution_case(js, texts), [])
        self.assertTrue(check_evolution_case(dict(js, input={"json": '{ "a":1,"b":2}'}), texts))     # whitespace: not canonical
        old = dict(good, direction="old_to_new", input={"cbor": "a1616101"}, populated=["b"],
                   value={"map": [[{"tstr": "a"}, {"uint": "1"}], [{"tstr": "b"}, {"uint": "7"}]]},
                   cbor="a2616101616207", json='{"a":1,"b":7}')
        del old["ignored"]
        self.assertEqual(check_evolution_case(old, texts), [])
        self.assertTrue(check_evolution_case(dict(old, populated=["c"]), texts))
        self.assertTrue(check_evolution_case(dict(old, populated=["a"]), texts))
        arr = {"direction": "new_to_old", "input": {"cbor": "83010203"}, "ignored": ["[2]"], "id": "p/a", "root": "T",
               "value": {"array": [{"uint": "1"}, {"uint": "2"}]}, "cbor": "820102", "json": "[1,2]"}
        self.assertEqual(check_evolution_case(arr, texts), [])

    def test_evolution_file_requirements(self):
        """REQ-COMPAT-010/020: each pair has both directions in both encodings, one scenario, two revisions."""
        texts = {"evolution/p/v1.cddl": "T = {a: uint}\n", "evolution/p/v2.cddl": "T = {a: uint, ? b: uint}\n"}
        doc = _evo_doc()
        errs = check_evolution_file("cases/evolution/p.json", doc, texts, {"REQ-COMPAT-020"})
        self.assertTrue(any("old_to_new case with a cbor" in e for e in errs))               # incomplete directions
        self.assertTrue(check_evolution_file("cases/evolution/q.json", doc, texts, {"REQ-COMPAT-020"}))
        self.assertTrue(check_evolution_file("cases/evolution/p.json", doc, {k: texts["evolution/p/v1.cddl"] for k in texts}, set()))
        self.assertEqual(len(check_scenarios_complete({"a": doc})), len(SCENARIOS) - 1)

    SPECS9 = """\
## 9. Runtime
- **REQ-RT-010** x
- **REQ-RT-020** y
### 9.1 Sub
- **REQ-RT-160** z
- **REQ-COMPAT-040** n
## 10. Next
- **REQ-CLI-010** not in scope
"""
    PLAN = "### 2.1 — A\n### 9.4 — B\n"

    def _cov_docs(self, tags):
        return {"a": {"kind": "positive", "cases": [{"id": "s/a", "requirements": tags}]}}

    def _cov(self, docs, **over):
        implied = {"positive": ["REQ-RT-010"]}
        cov = build_coverage(docs, ["REQ-RT-010", "REQ-RT-020", "REQ-RT-160", "REQ-COMPAT-040"],
                             {"implied_by_kind": implied, "requirements": {
                                 "REQ-RT-020": {"exempt": {"category": "api_shape", "reason": "r", "tested_in": "slice 2.1"}},
                                 "REQ-COMPAT-040": {"exempt": {"category": "non_guarantee", "reason": "r", "tested_in": None}}}})
        cov.update(over)
        return cov

    def test_coverage_requirement_ids_come_from_section_9(self):
        """specs.md §9: the introduction and every 9.x, nothing from §10."""
        self.assertEqual(section9_requirements(self.SPECS9),
                         ["REQ-RT-010", "REQ-RT-020", "REQ-RT-160", "REQ-COMPAT-040"])

    def test_coverage_complete_and_fresh(self):
        """Slice 1.4 DoD: a case or an exemption for every §9 requirement; CI fails otherwise."""
        docs = self._cov_docs(["REQ-RT-160"])
        self.assertEqual(check_requirement_coverage(self._cov(docs), docs, self.SPECS9, self.PLAN), [])
        # a requirement added to §9 with no case and no exemption
        more = self.SPECS9.replace("### 9.1 Sub", "- **REQ-RT-025** new\n### 9.1 Sub")
        self.assertTrue(any("REQ-RT-025" in e for e in check_requirement_coverage(self._cov(docs), docs, more, self.PLAN)))
        # an id in the manifest that is not in §9
        cov = self._cov(docs)
        cov["requirements"]["REQ-RT-999"] = {"cases": ["s/a"]}
        self.assertTrue(check_requirement_coverage(cov, docs, self.SPECS9, self.PLAN))
        # a case re-tagged (or added) without regenerating
        retagged = self._cov_docs(["REQ-RT-160", "REQ-RT-020"])
        errs = check_requirement_coverage(self._cov(docs), retagged, self.SPECS9, self.PLAN)
        self.assertTrue(any("stale" in e for e in errs), errs)
        # a case deleted without regenerating
        self.assertTrue(check_requirement_coverage(self._cov(docs), self._cov_docs([]), self.SPECS9, self.PLAN))
        # a hand-edited cases list
        cov = self._cov(docs)
        cov["requirements"]["REQ-RT-160"]["cases"] = ["s/a", "s/ghost"]
        self.assertTrue(check_requirement_coverage(cov, docs, self.SPECS9, self.PLAN))

    def test_coverage_exemption_discipline(self):
        """Slice 1.4 plan §4.3: an exemption needs a category, a reason and a real slice; none may linger."""
        docs = self._cov_docs(["REQ-RT-160"])

        def with_exempt(**kw):
            cov = self._cov(docs)
            ex = dict(cov["requirements"]["REQ-RT-020"]["exempt"], **kw)
            cov["requirements"]["REQ-RT-020"]["exempt"] = ex
            return check_requirement_coverage(cov, docs, self.SPECS9, self.PLAN)
        self.assertEqual(with_exempt(), [])
        self.assertTrue(with_exempt(reason=" "))
        self.assertTrue(with_exempt(category="because"))
        self.assertTrue(with_exempt(tested_in="slice 7.7"))        # no such heading in plan.md
        self.assertTrue(with_exempt(tested_in=None))               # only a non_guarantee may omit it
        self.assertTrue(with_exempt(tested_in="2.1"))
        # stale: a case now tests a requirement that is still marked exempt
        tagged = self._cov_docs(["REQ-RT-160", "REQ-RT-020"])
        cov = self._cov(docs)
        cov["requirements"]["REQ-RT-020"]["cases"] = ["s/a"]
        errs = check_requirement_coverage(cov, tagged, self.SPECS9, self.PLAN)
        self.assertTrue(any("stale exemption" in e for e in errs), errs)
        # implied_by_kind may only name §9 requirements
        cov = self._cov(docs)
        cov["implied_by_kind"]["positive"].append("REQ-KEY-010")
        self.assertTrue(check_requirement_coverage(cov, docs, self.SPECS9, self.PLAN))

    def test_real_corpus_is_clean(self):
        """REQ-ARCH-060: the committed corpus passes every check."""
        self.assertEqual(run(CONFORMANCE, SPECS, True), [])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check-format", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--mutation-test", action="store_true")
    ap.add_argument("--write-coverage", action="store_true",
                    help="regenerate coverage.json (keeps its hand-written exemptions)")
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
    if args.write_coverage:
        print(f"wrote {write_coverage(CONFORMANCE, SPECS)}")
        return 0
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
