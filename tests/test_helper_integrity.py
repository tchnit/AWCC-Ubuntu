from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from awcc_linux.helper_integrity import helper_payload_reason


class HelperIntegrityTests(unittest.TestCase):
    def test_matching_root_owned_payload_is_accepted(self):
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_uid=0, st_mode=0o100644)), patch.object(Path, "read_bytes", return_value=b"same"):
            self.assertIsNone(helper_payload_reason())

    def test_stale_payload_is_rejected(self):
        def contents(path):
            return b"old" if str(path).startswith("/usr/lib/") else b"new"
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_uid=0, st_mode=0o100644)), patch.object(Path, "read_bytes", contents):
            self.assertIn("cập nhật", helper_payload_reason())

    def test_user_owned_payload_is_rejected(self):
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_uid=1000, st_mode=0o100644)):
            self.assertIn("root", helper_payload_reason())

    def test_missing_helper_is_rejected(self):
        with patch.object(Path, "stat", side_effect=FileNotFoundError):
            self.assertIn("chưa đầy đủ", helper_payload_reason())
