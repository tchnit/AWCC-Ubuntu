"""Offline proof that attribution v3 only expands caller metadata logging."""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "research/sources/ubuntu-hwe-7.0/alienware"
PATCH_DIR = ROOT / "research/alienware-module-attribution-v3"
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


class AttributionV3SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.original = (ORIGINAL / "alienware-wmi-wmax.c").read_text(encoding="utf-8")
        cls.generated, cls.patch_outputs = generated_source()

    def test_patches_apply_exactly_to_hwe_source(self) -> None:
        self.assertIn("AWCC_TRACE setter pid=%d tgid=%d ppid=%d uid=%u", self.generated)
        self.assertIn("#include <linux/sched/signal.h>", self.generated)
        self.assertFalse(any("offset" in output or "fuzz" in output for output in self.patch_outputs))

    def test_candidate_is_logging_only(self) -> None:
        self.assertIn("task_ppid_nr(current)", self.generated)
        self.assertIn("from_kuid_munged(&init_user_ns, current_uid())", self.generated)
        self.assertNotIn("get_task_cmdline", self.generated)
        self.assertNotIn("wmidev_evaluate_method(", self.generated)
        self.assertNotIn("force_gmode =", self.generated)
        self.assertEqual(self.original.count("awcc_op_activate_profile("),
                         self.generated.count("awcc_op_activate_profile("))
        old_wrapper = wrapper(self.original)
        new_wrapper = wrapper(self.generated)
        call = "ret = alienware_wmi_command(wdev, method_id, args, sizeof(*args), out);"
        self.assertEqual(old_wrapper.count(call), new_wrapper.count(call))
        self.assertIsNone(re.search(r"\\*out\\s*=(?!=)", wrapper(self.generated)))


if __name__ == "__main__":
    unittest.main()
