from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import threading

from app.path_manager import normalize_url, sanitize_creator_name, sanitize_filename


@dataclass
class DownloadRecord:
    platform: str
    media_id: str
    canonical_url: str
    creator: str
    title: str
    saved_filename: str
    saved_filepath: str
    file_extension: str
    completed_at: str = ""
    status: str = "completed"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> DownloadRecord:
        return cls(
            platform=data.get("platform", ""),
            media_id=str(data.get("media_id", "")),
            canonical_url=data.get("canonical_url", ""),
            creator=data.get("creator", ""),
            title=data.get("title", ""),
            saved_filename=data.get("saved_filename", ""),
            saved_filepath=data.get("saved_filepath", ""),
            file_extension=data.get("file_extension", ""),
            completed_at=data.get("completed_at", ""),
            status=data.get("status", "completed"),
        )


class DownloadHistoryStore:
    """Thread-safe persistent store for completed download metadata and duplicate recognition."""

    def __init__(self) -> None:
        from app.utils import get_appdata_dir
        base = get_appdata_dir("DeepX Vision Downloader")
        self.file_path = base / "download_history.json"
        self._lock = threading.Lock()
        self._records: list[DownloadRecord] = []
        self._load()

    def _load(self) -> None:
        if not self.file_path.is_file():
            self._records = []
            return
        try:
            raw = json.loads(self.file_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                self._records = [DownloadRecord.from_dict(item) for item in raw if isinstance(item, dict)]
            elif isinstance(raw, dict):
                items = raw.get("records", [])
                self._records = [DownloadRecord.from_dict(item) for item in items if isinstance(item, dict)]
        except Exception:
            self._records = []

    def _save(self) -> None:
        try:
            data = [r.to_dict() for r in self._records]
            self.file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def record_completed(self, record: DownloadRecord) -> None:
        """Records a successfully completed download."""
        if not record.completed_at:
            record.completed_at = datetime.now().isoformat()
        record.status = "completed"

        with self._lock:
            # Update existing record if matching platform + media_id, or append
            updated = False
            for idx, r in enumerate(self._records):
                if (
                    record.platform
                    and record.media_id
                    and r.platform.lower() == record.platform.lower()
                    and r.media_id.lower() == record.media_id.lower()
                ):
                    self._records[idx] = record
                    updated = True
                    break
                elif (
                    record.canonical_url
                    and r.canonical_url
                    and r.canonical_url == record.canonical_url
                ):
                    self._records[idx] = record
                    updated = True
                    break

            if not updated:
                self._records.append(record)
            self._save()

    def find_duplicate(
        self,
        url: str = "",
        platform: str = "",
        media_id: str = "",
        creator: str = "",
        title: str = "",
        check_disk: bool = True,
    ) -> DownloadRecord | None:
        """
        Finds a previously downloaded record.
        Prioritizes:
        1. (platform, media_id)
        2. Canonical URL
        3. (creator, title)
        If check_disk is True, verifies that the saved file physically exists on disk.
        """
        norm_url = normalize_url(url) if url else ""
        clean_creator = sanitize_creator_name(creator) if creator else ""
        clean_title = sanitize_filename(title) if title else ""

        with self._lock:
            for r in reversed(self._records):
                matched = False

                # 1. Match by platform + media_id
                if platform and media_id and r.platform and r.media_id:
                    if r.platform.lower() == platform.lower() and r.media_id.lower() == media_id.lower():
                        matched = True

                # 2. Match by canonical URL
                if not matched and norm_url and r.canonical_url:
                    if r.canonical_url == norm_url:
                        matched = True

                # 3. Match by creator + title
                if not matched and clean_creator and clean_title:
                    if (
                        sanitize_creator_name(r.creator).lower() == clean_creator.lower()
                        and sanitize_filename(r.title).lower() == clean_title.lower()
                    ):
                        matched = True

                if matched:
                    if check_disk:
                        if r.saved_filepath and Path(r.saved_filepath).is_file():
                            return r
                        # If file on disk was deleted or moved, check if another copy exists
                    else:
                        return r

        return None

    def get_all_records(self) -> list[DownloadRecord]:
        with self._lock:
            return list(self._records)

    def remove_record(self, filepath: str = "", canonical_url: str = "") -> bool:
        with self._lock:
            init_len = len(self._records)
            self._records = [
                r for r in self._records
                if not (
                    (filepath and r.saved_filepath == filepath)
                    or (canonical_url and r.canonical_url == canonical_url)
                )
            ]
            if len(self._records) < init_len:
                self._save()
                return True
            return False


# Global singleton instance for easy import across modules
history_store = DownloadHistoryStore()
