from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class AppSettings:
    download_folder: str = ""
    simultaneous_downloads: int = 3
    appearance_mode: str = "Dark"
    default_quality: str = "Best Available"
    default_speed_limit: str = "Unlimited"
    download_thumbnail: bool = True
    subtitle_language: str = "Auto"
    video_format: str = "Auto"
    auto_update: str = "Everyday"
    media_type: str = "Video"
    run_in_background: bool = False
    display_floating_window: bool = False
    monitor_clipboard: bool = True
    preferred_browser: str = "Google Chrome"
    play_sound_on_complete: bool = True
    authorized_accounts: dict[str, str] = field(default_factory=dict)

    def resolved_download_folder(self) -> Path:
        if self.download_folder:
            path = Path(self.download_folder)
        else:
            path = Path.home() / "Downloads" / "DeepX Vision Downloader"
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path
        except OSError:
            fallback = Path.home() / "Downloads"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback


class SettingsStore:
    def __init__(self) -> None:
        from app.utils import get_appdata_dir
        base = get_appdata_dir("DeepX Vision Downloader")
        self.path = base / "settings.json"

    def load(self) -> AppSettings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            limit = int(raw.get("simultaneous_downloads", 3))
            appearance = str(raw.get("appearance_mode", "Dark")).title()
            if appearance not in {"Light", "Dark", "System"}:
                appearance = "Dark"
            quality = str(raw.get("default_quality", "Best Available"))
            speed = str(raw.get("default_speed_limit", "Unlimited"))
            return AppSettings(
                download_folder=str(raw.get("download_folder", "")),
                simultaneous_downloads=max(1, min(10, limit)),
                appearance_mode=appearance,
                default_quality=quality,
                default_speed_limit=speed,
                download_thumbnail=bool(raw.get("download_thumbnail", True)),
                subtitle_language=str(raw.get("subtitle_language", "Auto")),
                video_format=str(raw.get("video_format", "Auto")),
                auto_update=str(raw.get("auto_update", "Everyday")),
                media_type=str(raw.get("media_type", "Video")),
                run_in_background=bool(raw.get("run_in_background", False)),
                display_floating_window=bool(raw.get("display_floating_window", False)),
                monitor_clipboard=bool(raw.get("monitor_clipboard", True)),
                preferred_browser=str(raw.get("preferred_browser", "Google Chrome")),
                play_sound_on_complete=bool(raw.get("play_sound_on_complete", True)),
                authorized_accounts=dict(raw.get("authorized_accounts", {})),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
