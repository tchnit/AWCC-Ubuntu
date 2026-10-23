from pathlib import Path
import stat
import subprocess
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


class FanPackagingTests(unittest.TestCase):
    def test_fan_policy_requires_admin_and_only_the_separate_root_helper(self):
        action = ET.parse(ROOT/"data/io.github.awcclinux.FanControl.policy").find("action")
        self.assertEqual(action.attrib["id"],"io.github.awcclinux.ControlCenter.fan-session")
        self.assertEqual(action.findtext("defaults/allow_active"),"auth_admin")
        self.assertEqual(action.findtext("defaults/allow_inactive"),"no")
        self.assertEqual(action.findtext("defaults/allow_any"),"no")
        self.assertEqual(action.findtext("annotate"),"/usr/libexec/awcc-fan-helper")

    def test_root_launcher_is_isolated_and_imports_only_root_library(self):
        launcher = ROOT/"data/awcc-fan-helper"
        text = launcher.read_text()
        self.assertTrue(launcher.stat().st_mode & stat.S_IXUSR)
        self.assertTrue(text.startswith("#!/usr/bin/python3 -I\n"))
        self.assertIn('sys.path.insert(0, "/usr/lib/alienware-control-center")',text)
        self.assertIn("from awcc_linux.fan_helper import main",text)

    def test_candidate_installer_only_prepares_files_and_preserves_a_backup(self):
        script = ROOT/"tools/install-fan-helper.sh"
        self.assertEqual(subprocess.run(["bash","-n",str(script)]).returncode,0)
        text = script.read_text()
        self.assertIn("/var/backups/awcc-fan-helper.XXXXXX",text)
        self.assertIn('[[ ${EUID} -ne 0 ]]',text)
        self.assertIn('"$PROJECT_DIR/tools/check-helper.py"',text)
        for forbidden in ("systemctl", "modprobe", "reboot", "pkexec", "pip install",
                          "/usr/libexec/awcc-fan-helper session", "/usr/libexec/awcc-fan-helper validation-session"):
            self.assertNotIn(forbidden,text)
