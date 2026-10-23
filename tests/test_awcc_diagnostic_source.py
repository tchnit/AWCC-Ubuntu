"""Verify the offline diagnostic candidate does not add firmware operations."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "research/sources/ubuntu-hwe-7.0/alienware"
CANDIDATE = ROOT / "research/alienware-module-diagnostic"


def split_wrapper(source: str):
    prefix, tail = source.split("static int awcc_wmi_command", 1)
    wrapper, suffix = tail.split("static int awcc_get_fan_sensors", 1)
    return prefix, wrapper, suffix


class DiagnosticSourceTests(unittest.TestCase):
    def test_other_translation_units_and_header_are_unchanged(self) -> None:
        for name in ("alienware-wmi-base.c", "alienware-wmi-legacy.c", "alienware-wmi.h"):
            with self.subTest(name=name):
                self.assertEqual((ORIGINAL / name).read_bytes(), (CANDIDATE / name).read_bytes())

    def test_only_awcc_command_wrapper_changed(self) -> None:
        old = split_wrapper((ORIGINAL / "alienware-wmi-wmax.c").read_text())
        new = split_wrapper((CANDIDATE / "alienware-wmi-wmax.c").read_text())
        self.assertEqual(old[0], new[0])
        self.assertEqual(old[2], new[2])

    def test_call_and_error_return_tail_are_unchanged(self) -> None:
        old = split_wrapper((ORIGINAL / "alienware-wmi-wmax.c").read_text())[1]
        new = split_wrapper((CANDIDATE / "alienware-wmi-wmax.c").read_text())[1]
        call = "ret = alienware_wmi_command(wdev, method_id, args, sizeof(*args), out);"
        self.assertEqual(old.count(call), 1)
        self.assertEqual(new.count(call), 1)
        self.assertEqual(old[old.index("\n\tif (ret)\n"):], new[new.index("\n\tif (ret)\n"):])
        self.assertNotRegex(new, r"\*out\s*=(?!=)")
        self.assertNotIn("wmidev_evaluate_method(", new)
