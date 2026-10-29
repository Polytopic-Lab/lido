#!/usr/bin/env python3
"""Structural validator for the deterministic CBOR of RFC 8949 §4.2 (REQ-RT-160/165).

Written directly from the RFC; standard library only; shares no code with Lido
or with cbor2 (D-007 §4). It checks one self-contained data item:

* definite lengths only, no tags, no simple values other than false/true/null
  (specs.md §3 admits nothing else, so a vector using them is an authoring error);
* every head in its shortest form;
* floats in the shortest form that preserves the value, NaN only as 0xf97e00 (REQ-RT-172);
* map keys strictly increasing in bytewise order of their *encoded* bytes, which
  also rules out duplicates (REQ-RT-165);
* well-formed: no truncation, no trailing bytes, valid UTF-8 text.

`analyze` returns the findings in four disjoint lists (malformed, invalid,
nondeterministic with a category, outside_subset) and parses indefinite-length
items so that findings inside them are found; `check` is their union and is
what a positive vector must pass with an empty result.

Usage: cborcheck.py HEX [HEX...]   (prints violations; exit 1 if any)
"""
import struct
import sys

MAX_DEPTH = 512


class _Stop(Exception):
    """Malformed input: nothing after this point can be interpreted."""


def _fits(fmt, x):
    """True if float `x` survives a round trip through struct format `fmt`."""
    try:
        return struct.unpack(">" + fmt, struct.pack(">" + fmt, x))[0] == x
    except OverflowError:
        return False


class Analysis:
    """Findings for one data item.

    malformed         not well-formed (RFC 8949 §1.2): nothing else is reliable
    invalid           well-formed but invalid: text that is not UTF-8, duplicate map keys
    nondeterministic  (category, message): departures from §4.2; category is one of
                      indefinite, head, float, nan, key_order
    outside_subset    tags, undefined, and simple values other than false/true/null
    """

    def __init__(self):
        self.malformed, self.invalid, self.nondeterministic, self.outside_subset = [], [], [], []

    def messages(self):
        return (self.malformed + self.invalid + [m for _, m in self.nondeterministic]
                + self.outside_subset)


class _Checker:
    def __init__(self, data):
        self.d = data
        self.i = 0
        self.a = Analysis()

    def take(self, n, at):
        if self.i + n > len(self.d):
            self.a.malformed.append(
                f"offset {at}: truncated: needs {n} byte(s), {len(self.d) - self.i} left")
            raise _Stop
        b = self.d[self.i : self.i + n]
        self.i += n
        return b

    def bad(self, at, msg):
        self.a.malformed.append(f"offset {at}: {msg}")
        raise _Stop

    def item(self, depth=0):
        """Validate one item starting at self.i; return its (start, end)."""
        start = self.i
        if depth > MAX_DEPTH:
            self.bad(start, "nesting too deep")
        ib = self.take(1, start)[0]
        major, ai = ib >> 5, ib & 31
        if major == 7:
            self.simple_or_float(ai, start)
            return start, self.i
        if 28 <= ai <= 30:
            self.bad(start, f"reserved additional information {ai}")
        if ai == 31:
            if major not in (2, 3, 4, 5):
                self.bad(start, "reserved additional information 31")
            self.a.nondeterministic.append(
                ("indefinite", f"offset {start}: indefinite length is not deterministic (REQ-RT-160)"))
            self.indefinite(major, start, depth)
            return start, self.i
        arg = self.argument(ai, start)
        if major in (2, 3):
            self.text_or_bytes(major, arg, start)
        elif major == 4:
            for _ in range(arg):
                self.item(depth + 1)
        elif major == 5:
            self.map_entries(range(arg), depth)
        elif major == 6:
            self.a.outside_subset.append(f"offset {start}: tag (major type 6) is outside the §3 subset")
            self.item(depth + 1)
        return start, self.i

    def text_or_bytes(self, major, n, at):
        body = self.take(n, at)
        if major == 3:
            try:
                body.decode("utf-8")
            except UnicodeDecodeError:
                self.a.invalid.append(f"offset {at}: text string is not valid UTF-8 (REQ-RT-315)")

    def is_break(self):
        return self.i < len(self.d) and self.d[self.i] == 0xFF

    def indefinite(self, major, start, depth):
        if major in (2, 3):
            while True:
                at = self.i
                if self.take(1, at)[0] == 0xFF:
                    return
                self.i = at
                ib = self.take(1, at)[0]
                if ib >> 5 != major or (ib & 31) == 31 or 28 <= (ib & 31) <= 30:
                    self.bad(at, "chunk of an indefinite-length string must be a definite-length "
                                 "string of the same type")
                self.text_or_bytes(major, self.argument(ib & 31, at), at)
        elif major == 4:
            while not self.is_break_or_truncated(start):
                self.item(depth + 1)
            self.i += 1
        else:
            self.map_entries(None, depth, start)

    def is_break_or_truncated(self, start):
        if self.i >= len(self.d):
            self.bad(start, "truncated: indefinite-length item is not terminated by a break")
        return self.d[self.i] == 0xFF

    def map_entries(self, count, depth, start=None):
        prev, seen = None, set()
        n = 0
        while True:
            if count is None:
                if self.is_break_or_truncated(start):
                    self.i += 1
                    return
            elif n == len(count):
                return
            n += 1
            ks, ke = self.item(depth + 1)
            key = self.d[ks:ke]
            if key in seen:
                self.a.invalid.append(
                    f"offset {ks}: duplicate map key; key order must be strictly increasing "
                    "bytewise (REQ-RT-165, REQ-RT-300)")
            elif prev is not None and key < prev:
                self.a.nondeterministic.append(
                    ("key_order", f"offset {ks}: key order: encoded keys must strictly increase "
                                  f"bytewise (REQ-RT-165); {key.hex()} follows {prev.hex()}"))
            seen.add(key)
            prev = key
            if count is None and self.is_break_or_truncated(start):
                self.bad(self.i, "break where a map value was expected")
            self.item(depth + 1)

    def argument(self, ai, at):
        if ai < 24:
            return ai
        width = {24: 1, 25: 2, 26: 4, 27: 8}[ai]
        v = int.from_bytes(self.take(width, at), "big")
        floor = {24: 24, 25: 1 << 8, 26: 1 << 16, 27: 1 << 32}[ai]
        if v < floor:
            self.a.nondeterministic.append(
                ("head", f"offset {at}: head is not in shortest form: {v} needs a smaller "
                         "argument (REQ-RT-160)"))
        return v

    def simple_or_float(self, ai, at):
        nd = self.a.nondeterministic
        if ai in (20, 21, 22):
            return
        if ai == 25:
            raw = self.take(2, at)
            x = struct.unpack(">e", raw)[0]
            if x != x and raw != b"\x7e\x00":
                nd.append(("nan", f"offset {at}: NaN must be encoded as 0xf97e00 (REQ-RT-172)"))
        elif ai == 26:
            x = struct.unpack(">f", self.take(4, at))[0]
            if x != x:
                nd.append(("nan", f"offset {at}: NaN must be encoded as 0xf97e00 (REQ-RT-172)"))
            elif _fits("e", x):
                nd.append(("float", f"offset {at}: float is not in shortest form: fits in half "
                                    "precision (REQ-RT-160)"))
        elif ai == 27:
            x = struct.unpack(">d", self.take(8, at))[0]
            if x != x:
                nd.append(("nan", f"offset {at}: NaN must be encoded as 0xf97e00 (REQ-RT-172)"))
            elif _fits("f", x):
                nd.append(("float", f"offset {at}: float is not in shortest form: fits in single "
                                    "precision (REQ-RT-160)"))
        elif ai == 31:
            self.bad(at, "unexpected break")
        elif ai == 24:
            v = self.take(1, at)[0]
            if v < 32:
                self.bad(at, f"simple value {v} in the two-byte form is not well-formed")
            self.a.outside_subset.append(
                f"offset {at}: simple value other than false/true/null is outside the §3 subset")
        elif ai > 24:
            self.bad(at, f"reserved additional information {ai}")
        else:
            self.a.outside_subset.append(
                f"offset {at}: simple value other than false/true/null is outside the §3 subset")


def analyze(data):
    """Return the categorised findings (an `Analysis`) for one CBOR data item."""
    c = _Checker(bytes(data))
    try:
        c.item()
        if c.i != len(c.d):
            c.a.malformed.append(f"offset {c.i}: trailing bytes: {len(c.d) - c.i} after the item")
    except _Stop:
        pass
    return c.a


def check(data):
    """Return a list of violation strings; empty means `data` is one valid
    deterministic CBOR item within the §3 subset."""
    return analyze(data).messages()


def main(argv):
    bad = False
    for arg in argv:
        for e in check(bytes.fromhex(arg)):
            print(f"{arg[:24]}: {e}")
            bad = True
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
