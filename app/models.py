from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import Event, Lock
from typing import Callable
from uuid import uuid4


class DownloadStatus(str, Enum):
    QUEUED = "Queued"
    FETCHING_INFO = "Analyzing…"
    DOWNLOADING = "Downloading"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


@dataclass
class DownloadTask:
    url: str
    destination: str
    quality: str = "Best Quality"
    speed_limit_bps: int | None = None
    numbering: int | None = None
    cookies_source: str | None = None
    id: str = field(default_factory=lambda: uuid4().hex)
    filename: str = "Preparing download…"
    thumbnail_url: str = ""
    thumbnail_path: str = ""
    status: DownloadStatus = DownloadStatus.QUEUED
    downloaded: int = 0
    total: int | None = None
    speed_bps: float = 0.0
    error: str = ""
    output_path: str = ""
    creator: str = ""
    media_id: str = ""
    platform: str = ""
    is_duplicate_copy: bool = False
    on_duplicate_prompt: Callable[[str, str, str], bool] | None = field(default=None, repr=False)
    delete_file_on_remove: bool = False
    cancel_event: Event = field(default_factory=Event, repr=False)
    pause_event: Event = field(default_factory=Event, repr=False)
    lock: Lock = field(default_factory=Lock, repr=False)

    @property
    def progress(self) -> float:
        if not self.total:
            return 0.0
        return min(1.0, self.downloaded / self.total)
