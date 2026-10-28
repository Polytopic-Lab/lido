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


class _Checker:
    def __init__(self, data):
        self.d = data
        self.i = 0
        self.errs = []

    def err(self, at, msg):
        self.errs.append(f"offset {at}: {msg}")

    def take(self, n, at):
        if self.i + n > len(self.d):
            self.err(at, f"truncated: needs {n} byte(s), {len(self.d) - self.i} left")
            raise _Stop
        b = self.d[self.i : self.i + n]
        self.i += n
        return b

    def item(self, depth=0):
        """Validate one item starting at self.i; return its (start, end)."""
        start = self.i
        if depth > MAX_DEPTH:
            self.err(start, "nesting too deep")
            raise _Stop
        ib = self.take(1, start)[0]
        major, ai = ib >> 5, ib & 31
        if major == 7:
            self.simple_or_float(ai, start)
            return start, self.i
        if ai == 31:
            if major in (2, 3, 4, 5):
                self.err(start, "indefinite length is not deterministic (REQ-RT-160)")
            else:
                self.err(start, "reserved additional information 31")
            raise _Stop
        if 28 <= ai <= 30:
            self.err(start, f"reserved additional information {ai}")
            raise _Stop
        arg = self.argument(ai, start)
        if major in (0, 1):
            pass
        elif major in (2, 3):
            body = self.take(arg, start)
            if major == 3:
                try:
                    body.decode("utf-8")
                except UnicodeDecodeError:
                    self.err(start, "text string is not valid UTF-8")
        elif major == 4:
            for _ in range(arg):
                self.item(depth + 1)
        elif major == 5:
            prev = None
            for _ in range(arg):
                ks, ke = self.item(depth + 1)
                key = self.d[ks:ke]
                if prev is not None and key <= prev:
                    self.err(ks, "key order: encoded keys must strictly increase bytewise "
                                 f"(REQ-RT-165); {key.hex()} follows {prev.hex()}")
                prev = key
                self.item(depth + 1)
        else:
            self.err(start, "tag (major type 6) is outside the §3 subset")
            raise _Stop
        return start, self.i

    def argument(self, ai, at):
        if ai < 24:
            return ai
        width = {24: 1, 25: 2, 26: 4, 27: 8}[ai]
        v = int.from_bytes(self.take(width, at), "big")
        floor = {24: 24, 25: 1 << 8, 26: 1 << 16, 27: 1 << 32}[ai]
        if v < floor:
            self.err(at, f"head is not in shortest form: {v} needs a smaller argument (REQ-RT-160)")
        return v

    def simple_or_float(self, ai, at):
        if ai in (20, 21, 22):
            return
        if ai == 25:
            raw = self.take(2, at)
            x = struct.unpack(">e", raw)[0]
            if x != x and raw != b"\x7e\x00":
                self.err(at, "NaN must be encoded as 0xf97e00 (REQ-RT-172)")
        elif ai == 26:
            raw = self.take(4, at)
            x = struct.unpack(">f", raw)[0]
            if x != x:
                self.err(at, "NaN must be encoded as 0xf97e00 (REQ-RT-172)")
            elif _fits("e", x):
                self.err(at, "float is not in shortest form: fits in half precision (REQ-RT-160)")
        elif ai == 27:
            raw = self.take(8, at)
            x = struct.unpack(">d", raw)[0]
            if x != x:
                self.err(at, "NaN must be encoded as 0xf97e00 (REQ-RT-172)")
            elif _fits("f", x):
                self.err(at, "float is not in shortest form: fits in single precision (REQ-RT-160)")
        elif ai == 31:
            self.err(at, "unexpected break")
            raise _Stop
        elif ai < 24 or ai == 24:
            if ai == 24:
                self.take(1, at)
            self.err(at, "simple value other than false/true/null is outside the §3 subset")
            if ai == 24:
                raise _Stop
        else:
            self.err(at, f"reserved additional information {ai}")
            raise _Stop


def check(data):
    """Return a list of violation strings; empty means `data` is one valid
    deterministic CBOR item within the §3 subset."""
    c = _Checker(bytes(data))
    try:
        c.item()
        if c.i != len(c.d):
            c.err(c.i, f"trailing bytes: {len(c.d) - c.i} after the item")
    except _Stop:
        pass
    return c.errs


def main(argv):
    bad = False
    for arg in argv:
        for e in check(bytes.fromhex(arg)):
            print(f"{arg[:24]}: {e}")
            bad = True
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
