from __future__ import annotations

import json
import os
from pathlib import Path
from app.models import DownloadStatus, DownloadTask


def get_queue_file_path() -> Path:
    appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    dir_path = Path(appdata) / "DeepX Vision Downloader"
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path / "pending_queue.json"


def save_pending_queue(tasks: list[DownloadTask]) -> None:
    pending_data = []
    for t in tasks:
        if t.status in (
            DownloadStatus.QUEUED,
            DownloadStatus.FETCHING_INFO,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.CONVERTING,
            DownloadStatus.PAUSED,
            DownloadStatus.FAILED,
        ):
            pending_data.append({
                "id": t.id,
                "url": t.url,
                "destination": t.destination,
                "quality": t.quality,
                "speed_limit_bps": t.speed_limit_bps,
                "numbering": t.numbering,
                "filename": t.filename,
                "thumbnail_url": t.thumbnail_url,
                "thumbnail_path": t.thumbnail_path,
                "downloaded": t.downloaded,
                "total": t.total,
                "creator": t.creator,
                "media_id": t.media_id,
                "platform": t.platform,
                "cookies_source": t.cookies_source,
            })

    q_file = get_queue_file_path()
    try:
        if pending_data:
            q_file.write_text(json.dumps(pending_data, indent=2), encoding="utf-8")
        else:
            if q_file.is_file():
                q_file.unlink(missing_ok=True)
    except Exception:
        pass


def load_pending_queue() -> list[dict]:
    q_file = get_queue_file_path()
    if not q_file.is_file():
        return []
    try:
        raw = json.loads(q_file.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw
    except Exception:
        pass
    return []
