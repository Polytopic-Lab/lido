#!/usr/bin/env python3
"""Tests for cborcheck.py. Every test names the REQ it covers."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cborcheck  # noqa: E402


def h(s):
    return bytes.fromhex(s.replace(" ", ""))


def bad(test, hexstr, needle=None):
    errs = cborcheck.check(h(hexstr))
    test.assertTrue(errs, f"{hexstr} should be rejected")
    if needle:
        test.assertTrue(any(needle in e for e in errs), f"{hexstr}: {errs}")


class Tests(unittest.TestCase):
    def test_req_rt_160_rfc8949_appendix_a_canonical_items_accepted(self):
        """REQ-RT-160: items transcribed from RFC 8949 Appendix A Table 6
        that lie inside the §3 subset and are already deterministic."""
        for x in [
            "00", "01", "0a", "17", "1818", "1819", "1864", "1903e8",
            "1a000f4240", "1b000000e8d4a51000", "1bffffffffffffffff",
            "3bffffffffffffffff", "20", "29", "3863", "3903e7",
            "f90000", "f98000", "f93c00", "fb3ff199999999999a", "f93e00",
            "f97bff", "fa47c35000", "fa7f7fffff", "fb7e37e43c8800759c",
            "f90001", "f90400", "f9c400", "fbc010666666666666",
            "f97c00", "f97e00", "f9fc00", "f4", "f5", "f6",
            "40", "4401020304", "60", "6161", "6449455446", "62225c",
            "62c3bc", "63e6b0b4", "64f0908591", "80", "83010203",
            "8301820203820405",
            "98190102030405060708090a0b0c0d0e0f101112131415161718181819",
            "a0", "a201020304", "a26161016162820203", "826161a161626163",
            "a56161614161626142616361436164614461656145",
        ]:
            self.assertEqual(cborcheck.check(h(x)), [], x)

    def test_req_rt_160_indefinite_lengths_rejected(self):
        """REQ-RT-160: definite lengths only."""
        for x in ["5f42010243030405ff", "7f657374726561646d696e67ff", "9fff",
                  "9f018202039f0405ffff", "bf61610161629f0203ffff"]:
            bad(self, x, "indefinite")

    def test_req_rt_160_non_shortest_heads_rejected(self):
        """REQ-RT-160: heads in shortest form."""
        for x in ["1800", "1817", "190001", "1900ff", "1a0000ffff", "1b00000000ffffffff",
                  "3800", "5800", "780161", "9800", "b800", "98 01 00"]:
            bad(self, x, "shortest")

    def test_req_rt_160_non_shortest_floats_rejected(self):
        """REQ-RT-160: floats in the shortest form that round-trips."""
        bad(self, "fa3fc00000", "shortest")      # 1.5 as float32
        bad(self, "fb3ff8000000000000", "shortest")  # 1.5 as float64
        bad(self, "fa7f800000", "shortest")      # +Infinity as float32
        bad(self, "fbfff0000000000000", "shortest")  # -Infinity as float64
        bad(self, "fa80000000", "shortest")      # -0.0 as float32

    def test_req_rt_172_only_canonical_nan_accepted(self):
        """REQ-RT-172: NaN is 0xf97e00 and nothing else."""
        self.assertEqual(cborcheck.check(h("f97e00")), [])
        for x in ["f97e01", "f97c01", "f9fe00", "fa7fc00000", "fb7ff8000000000000"]:
            bad(self, x)

    def test_req_rt_165_map_key_order_is_over_encoded_bytes(self):
        """REQ-RT-165: "age" < "name" < "email" — length-first, not alphabetical."""
        age, name, email = "63616765", "646e616d65", "65656d61696c"
        ok = "a3" + age + "01" + name + "02" + email + "03"
        self.assertEqual(cborcheck.check(h(ok)), [])
        alphabetical = "a3" + age + "01" + email + "03" + name + "02"
        bad(self, alphabetical, "key order")
        declaration = "a3" + name + "02" + age + "01" + email + "03"
        bad(self, declaration, "key order")

    def test_req_rt_165_bytewise_tie_break_within_a_length(self):
        """REQ-RT-165: equal-length keys sort bytewise."""
        self.assertEqual(cborcheck.check(h("a2 6161 01 6162 02")), [])
        bad(self, "a2 6162 02 6161 01", "key order")

    def test_req_rt_165_integer_keys_sort_numerically(self):
        """REQ-RT-165: unsigned-integer keys sort in numeric order."""
        self.assertEqual(cborcheck.check(h("a3 01 00 0a 00 1818 00")), [])
        bad(self, "a2 0a 00 01 00", "key order")
        bad(self, "a2 1818 00 0a 00", "key order")

    def test_req_rt_160_duplicate_map_keys_rejected(self):
        """REQ-RT-160: duplicate keys are not a sorted map."""
        bad(self, "a2 6161 01 6161 02", "key order")

    def test_req_rt_160_nested_maps_are_checked(self):
        """REQ-RT-160: the ordering rule applies at every depth."""
        bad(self, "a1 6161 a2 6162 01 6161 02", "key order")

    def test_req_rt_160_malformed_input_rejected(self):
        """REQ-RT-160: truncation, trailing bytes, bad UTF-8, reserved heads."""
        bad(self, "", "truncated")
        bad(self, "18", "truncated")
        bad(self, "6261", "truncated")
        bad(self, "8201", "truncated")
        bad(self, "00 00", "trailing")
        bad(self, "62c328", "UTF-8")
        bad(self, "1c", "reserved")
        bad(self, "ff", "break")
        bad(self, "f800", "simple")

    def test_req_rt_160_constructs_outside_the_subset_rejected(self):
        """REQ-RT-160 / specs.md §3: no tags, no undefined, no other simple values."""
        bad(self, "c11a514b67b0", "tag")
        bad(self, "c249010000000000000000", "tag")
        bad(self, "f7", "simple")
        bad(self, "f0", "simple")
        bad(self, "f8ff", "simple")


if __name__ == "__main__":
    unittest.main()
