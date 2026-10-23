from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "awcc_aml", Path(__file__).resolve().parents[1] / "research/analyze_awcc_aml.py"
)
assert spec and spec.loader
aml = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aml)


def package(opcode: int, body: bytes) -> bytes:
    length = len(body) + 1
    if length < 64:
        return bytes((opcode, length)) + body
    length = len(body) + 2
    return bytes((opcode, 0x40 | (length & 15), length >> 4)) + body


def dispatch(ids: tuple[int, ...]) -> bytes:
    default = b"\x70\x0c\xff\xff\xff\xff\x60\xa5"
    for value in reversed(ids):
        default = package(0xA0, b"\x93_T_0\x0a" + bytes((value,)) + b"\xa5") + package(0xA1, default)
    return default


class AmlDispatchTests(unittest.TestCase):
    def test_single_byte_package(self) -> None:
        self.assertEqual(aml.pkg(b"\x04abc", 0), (1, 4))

    def test_multi_byte_package(self) -> None:
        data = package(0xA0, b"x" * 100)
        self.assertEqual(aml.pkg(data, 1), (3, len(data)))

    def test_rejects_truncated_package(self) -> None:
        for data in (b"", b"\x40", b"\x3f"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                aml.pkg(data, 0)

    def test_rejects_reserved_package_bits(self) -> None:
        with self.assertRaises(ValueError):
            aml.pkg(b"\x50\x00", 0)

    def test_missing_method_enters_known_failure_default(self) -> None:
        data = dispatch((0x13, 0x14, 0x15))
        branches, default, consumed = aml.chain(data, 0, len(data))
        self.assertEqual(consumed, len(data))
        self.assertEqual([b["method_id"] for b in branches], ["0x13", "0x14", "0x15"])
        self.assertEqual(default["store_local0"], "0xffffffff")
        self.assertTrue(default["break"])

    def test_present_game_shift_is_not_falsely_reported_absent(self) -> None:
        data = dispatch((0x14, 0x25))
        branches, _, _ = aml.chain(data, 0, len(data))
        self.assertIn("0x25", [b["method_id"] for b in branches])

    def test_unknown_predicate_refuses_conclusion(self) -> None:
        data = dispatch((0x25,)).replace(b"_T_0", b"_T_1")
        with self.assertRaises(ValueError):
            aml.chain(data, 0, len(data))

    def test_unknown_default_refuses_conclusion(self) -> None:
        data = dispatch((0x25,)).replace(b"\xff\xff\xff\xff", b"\x00\x00\x00\x00")
        with self.assertRaises(ValueError):
            aml.chain(data, 0, len(data))

    def test_invalid_table_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            aml.analyze(b"DSDT" + bytes(40))

    def test_integer_bounds_and_width(self) -> None:
        self.assertEqual(aml.integer(b"\x0c\xff\xff\xff\xff", 0), (0xFFFFFFFF, 5))
        for data in (b"", b"\x0c\x00", b"\x70"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                aml.integer(data, 0)
