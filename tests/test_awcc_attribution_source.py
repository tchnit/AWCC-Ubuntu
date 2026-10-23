"""Offline proof that the attribution build only adds logging."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import re


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "research/sources/ubuntu-hwe-7.0/alienware"
PATCH_DIR = ROOT / "research/alienware-module-attribution"
SOURCE_FILES = (
    "alienware-wmi-base.c",
    "alienware-wmi-legacy.c",
    "alienware-wmi-wmax.c",
    "alienware-wmi.h",
)


def generated_source() -> tuple[str, list[str]]:
    with tempfile.TemporaryDirectory() as temporary:
        build = Path(temporary)
        for name in SOURCE_FILES:
            shutil.copy2(ORIGINAL / name, build / name)
        outputs = []
        for patch in sorted(PATCH_DIR.glob("*.patch")):
            result = subprocess.run(
                ["patch", "--batch", "--fuzz=0", "-d", str(build), "-p1"],
                input=patch.read_text(encoding="utf-8"), text=True, check=True,
                capture_output=True,
            )
            outputs.append(result.stdout + result.stderr)
        return (build / "alienware-wmi-wmax.c").read_text(encoding="utf-8"), outputs


def wrapper(source: str) -> str:
    _, tail = source.split("static int awcc_wmi_command", 1)
    result, _ = tail.split("static int awcc_get_fan_sensors", 1)
    return result


class AttributionSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.original = (ORIGINAL / "alienware-wmi-wmax.c").read_text(encoding="utf-8")
        cls.generated, cls.patch_outputs = generated_source()

    def test_patches_apply_exactly_to_the_hwe_source(self) -> None:
        self.assertIn("AWCC_ATTRIB setter pid=%d comm=%s", self.generated)
        self.assertIn("#include <linux/sched.h>", self.generated)
        self.assertEqual(wrapper(self.generated).count("ret = alienware_wmi_command("), 1)
        self.assertFalse(any("offset" in output or "fuzz" in output for output in self.patch_outputs))

    def test_attribution_is_logging_only(self) -> None:
        self.assertIn("task_pid_nr(current), current->comm", self.generated)
        self.assertNotIn("wmidev_evaluate_method(", self.generated)
        self.assertNotIn("force_gmode =", self.generated)
        self.assertIsNone(re.search(r"\*out\s*=(?!=)", wrapper(self.generated)))
        self.assertEqual(self.original.count("awcc_op_activate_profile("),
                         self.generated.count("awcc_op_activate_profile("))
        old_wrapper = wrapper(self.original)
        new_wrapper = wrapper(self.generated)
        call = "ret = alienware_wmi_command(wdev, method_id, args, sizeof(*args), out);"
        self.assertEqual(old_wrapper[old_wrapper.index("\n\tif (ret)\n"):],
                         new_wrapper[new_wrapper.index("\n\tif (ret)\n"):])
        self.assertEqual(old_wrapper.count(call), new_wrapper.count(call))

    def test_unmodified_translation_units_and_header_remain_source_of_truth(self) -> None:
        for name in ("alienware-wmi-base.c", "alienware-wmi-legacy.c", "alienware-wmi.h"):
            with self.subTest(name=name):
                self.assertTrue((ORIGINAL / name).is_file())
                self.assertNotIn(name, "\n".join(
                    patch.read_text(encoding="utf-8") for patch in PATCH_DIR.glob("*.patch")
                ))


if __name__ == "__main__":
    unittest.main()
