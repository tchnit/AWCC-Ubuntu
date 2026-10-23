from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .presets import PRESETS_BY_KEY


REFRESH_OPTIONS = (1, 2, 5)


@dataclass(frozen=True, slots=True)
class AppSettings:
    preferred_preset: str = "auto"
    refresh_seconds: int = 2

    def normalized(self) -> AppSettings:
        preset = (
            self.preferred_preset
            if self.preferred_preset in PRESETS_BY_KEY
            else "auto"
        )
        refresh = self.refresh_seconds if self.refresh_seconds in REFRESH_OPTIONS else 2
        return AppSettings(preset, refresh)


def default_settings_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    root = Path(config_home) if config_home else Path.home() / ".config"
    return root / "alienware-control-center" / "settings.json"


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_settings_path()

    def load(self) -> AppSettings:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return AppSettings()
            settings = AppSettings(
                preferred_preset=str(payload.get("preferred_preset", "auto")),
                refresh_seconds=int(payload.get("refresh_seconds", 2)),
            )
        except (OSError, ValueError, TypeError, OverflowError):
            return AppSettings()
        return settings.normalized()

    def save(self, settings: AppSettings) -> None:
        normalized = settings.normalized()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(normalized), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(self.path)
