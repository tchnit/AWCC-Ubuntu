from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from awcc_linux.presets import PRESETS_BY_KEY
from awcc_linux.settings import AppSettings, SettingsStore


class SettingsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "config" / "settings.json"
        self.store = SettingsStore(self.path)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_missing_file_uses_safe_defaults(self) -> None:
        self.assertEqual(self.store.load(), AppSettings())

    def test_wrong_json_structure_uses_safe_defaults(self):
        self.path.parent.mkdir(parents=True)
        for content in ('[]', 'null', 'true', '42', '"text"', '{"refresh_seconds": Infinity}'):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                self.assertEqual(self.store.load(), AppSettings())

    def test_round_trip(self) -> None:
        expected = AppSettings("performance", 5)
        self.store.save(expected)
        self.assertEqual(self.store.load(), expected)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_invalid_values_are_normalized(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            '{"preferred_preset": "gaming", "refresh_seconds": 99, '
            '"selected_fan_mode": "invalid"}',
            encoding="utf-8",
        )
        self.assertEqual(self.store.load(), AppSettings())

    def test_legacy_fan_mode_and_curve_settings_are_ignored(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            '{"preferred_preset": "balanced", "refresh_seconds": 5, '
            '"selected_fan_mode": "gaming", "custom_curve_duties": [20, 40, 60]}',
            encoding="utf-8",
        )
        self.assertEqual(self.store.load(), AppSettings("balanced", 5))

    def test_save_removes_legacy_fan_mode_and_curve_settings(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            '{"preferred_preset": "balanced", "refresh_seconds": 5, '
            '"selected_fan_mode": "gaming", "custom_curve_duties": [20, 40, 60]}',
            encoding="utf-8",
        )

        self.store.save(self.store.load())

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload, {"preferred_preset": "balanced", "refresh_seconds": 5})


class PresetTests(unittest.TestCase):
    def test_only_verified_profile_targets_are_exposed(self) -> None:
        self.assertEqual(
            set(PRESETS_BY_KEY), {"auto", "balanced", "quiet", "performance"}
        )
        self.assertIsNone(PRESETS_BY_KEY["auto"].profile)
        self.assertEqual(PRESETS_BY_KEY["balanced"].profile, "balanced")
        self.assertEqual(PRESETS_BY_KEY["quiet"].profile, "quiet")
        self.assertEqual(PRESETS_BY_KEY["performance"].profile, "performance")


if __name__ == "__main__":
    unittest.main()
