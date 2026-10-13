from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_PATCHED = False


def apply_custom_patches() -> None:
    """
    Applies runtime compatibility patches to yt-dlp extractors.
    Fixes Odnoklassniki (ok.ru) flashvars metadata already parsed as dict.
    """
    global _PATCHED
    if _PATCHED:
        return
    try:
        from yt_dlp.extractor.odnoklassniki import OdnoklassnikiIE

        orig_parse_json = OdnoklassnikiIE._parse_json

        def patched_parse_json(self, json_string, *args, **kwargs):
            if isinstance(json_string, dict):
                return json_string
            return orig_parse_json(self, json_string, *args, **kwargs)

        OdnoklassnikiIE._parse_json = patched_parse_json
        _PATCHED = True
    except Exception as e:
        logger.debug("Could not patch OdnoklassnikiIE: %s", e)


# Auto-apply patches upon import
apply_custom_patches()

from app.custom_extractors.moviebox import is_moviebox_url, extract_moviebox
from app.custom_extractors.watch_movies import is_watch_movies_url, extract_watch_movies


def is_custom_site_url(url: str) -> bool:
    """Checks if the URL is from one of the custom supported streaming sites."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    return is_moviebox_url(u) or is_watch_movies_url(u)


def resolve_custom_media(url: str, desired_quality: str = "Best Available") -> dict | None:
    """
    Resolves metadata and stream information for supported custom sites.
    Returns a yt-dlp-compatible info_dict with formats, title, thumbnail, etc.
    """
    if not url:
        return None
    u = url.strip()
    apply_custom_patches()

    if is_moviebox_url(u):
        return extract_moviebox(u, desired_quality=desired_quality)
    if is_watch_movies_url(u):
        return extract_watch_movies(u, desired_quality=desired_quality)
    return None


def select_best_custom_format(formats: list[dict], desired_quality: str) -> dict | None:
    """Selects the format best matching the user's requested quality."""
    if not formats:
        return None
    q = (desired_quality or "").upper()
    valid_formats = [f for f in formats if f.get("url")]
    if not valid_formats:
        return None

    target_h = None
    if "1080" in q:
        target_h = 1080
    elif "720" in q:
        target_h = 720
    elif "480" in q:
        target_h = 480
    elif "360" in q:
        target_h = 360
    elif "240" in q:
        target_h = 240
    elif "144" in q:
        target_h = 144

    if target_h:
        for f in valid_formats:
            if f.get("height") == target_h:
                return f
        lesser = [f for f in valid_formats if (f.get("height") or 0) <= target_h]
        if lesser:
            return max(lesser, key=lambda f: f.get("height") or 0)

    return max(valid_formats, key=lambda f: f.get("height") or 0)


def download_custom_stream_fallback(
    task,
    info: dict | None,
    notify_fn,
) -> bool:
    """
    Direct chunked streaming fallback downloader for MovieBox and Watch-Movies
    if yt-dlp encounters a protocol or network exception.
    """
    import re
    import time
    from pathlib import Path
    import urllib.request
    from app.models import DownloadStatus
    from app.path_manager import (
        get_creator_folder,
        get_next_duplicate_filename,
        reserve_path,
        sanitize_creator_name,
        sanitize_filename,
    )
    from app.download_history import DownloadRecord, history_store

    if not info:
        info = resolve_custom_media(task.url, desired_quality=task.quality)
    if not info or not info.get("formats"):
        return False

    selected = select_best_custom_format(info["formats"], task.quality)
    if not selected or not selected.get("url"):
        return False

    stream_url = selected["url"]
    headers = selected.get("http_headers") or {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": info.get("webpage_url") or task.url,
    }

    raw_title = info.get("title") or task.filename or "Video"
    base_name = sanitize_filename(raw_title)
    if task.numbering is not None:
        base_name_clean = re.sub(r"^\d{1,4}[\.\s_-]+\s*", "", base_name)
        clean_title = f"{task.numbering:02d}. {base_name_clean or base_name}"
    else:
        clean_title = base_name

    task.creator = sanitize_creator_name(info.get("uploader") or task.creator or "Streaming")
    task.platform = info.get("platform") or "web"
    task.media_id = str(info.get("id") or "")

    creator_folder = get_creator_folder(task.destination, task.creator)
    creator_folder.mkdir(parents=True, exist_ok=True)

    ext = selected.get("ext") or "mp4"

    # Duplicate checking
    existing_record = history_store.find_duplicate(
        url=task.url,
        platform=task.platform,
        media_id=task.media_id,
        creator=task.creator,
        title=clean_title,
        check_disk=True,
    )
    existing_disk_file = None
    if creator_folder.exists():
        for p in creator_folder.iterdir():
            if p.is_file() and not p.name.endswith((".part", ".tmp", ".ytdl")):
                if p.stem.lower() == clean_title.lower():
                    existing_disk_file = p
                    break

    is_duplicate = bool(existing_record or existing_disk_file)
    existing_path_str = existing_record.saved_filepath if existing_record else (str(existing_disk_file) if existing_disk_file else "")

    if is_duplicate and not task.is_duplicate_copy:
        if task.on_duplicate_prompt:
            user_confirmed = task.on_duplicate_prompt(clean_title, task.creator, existing_path_str)
            if not user_confirmed:
                with task.lock:
                    task.status = DownloadStatus.CANCELLED
                    task.error = "Download cancelled — video already exists."
                    task.speed_bps = 0
                notify_fn(task)
                return True
            else:
                task.is_duplicate_copy = True
        else:
            task.is_duplicate_copy = True

    if task.is_duplicate_copy:
        target_file = get_next_duplicate_filename(creator_folder, clean_title, f".{ext}")
    else:
        target_file = creator_folder / f"{clean_title}.{ext}"

    reserve_path(target_file)
    part_file = target_file.with_suffix(f".{ext}.part")

    with task.lock:
        task.status = DownloadStatus.DOWNLOADING
        task.filename = target_file.name
        task.output_path = str(target_file)
    notify_fn(task)

    try:
        req = urllib.request.Request(stream_url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp, open(part_file, "wb") as out_f:
            total_bytes = int(resp.headers.get("Content-Length") or selected.get("filesize") or 0)
            with task.lock:
                task.total = total_bytes if total_bytes > 0 else None
            notify_fn(task)

            downloaded = 0
            start_time = time.time()
            last_notify = start_time
            chunk_size = 64 * 1024

            while True:
                if task.cancel_event.is_set():
                    part_file.unlink(missing_ok=True)
                    with task.lock:
                        task.status = DownloadStatus.CANCELLED
                        task.speed_bps = 0
                    notify_fn(task)
                    return True

                while task.pause_event.is_set():
                    with task.lock:
                        task.status = DownloadStatus.PAUSED
                        task.speed_bps = 0
                    notify_fn(task)
                    time.sleep(0.3)
                    if task.cancel_event.is_set():
                        part_file.unlink(missing_ok=True)
                        with task.lock:
                            task.status = DownloadStatus.CANCELLED
                            task.speed_bps = 0
                        notify_fn(task)
                        return True

                chunk = resp.read(chunk_size)
                if not chunk:
                    break

                out_f.write(chunk)
                downloaded += len(chunk)
                now = time.time()

                if now - last_notify >= 0.25:
                    elapsed = now - start_time
                    speed = downloaded / elapsed if elapsed > 0 else 0
                    with task.lock:
                        task.status = DownloadStatus.DOWNLOADING
                        task.downloaded = downloaded
                        task.speed_bps = speed
                    notify_fn(task)
                    last_notify = now

        # Download completed
        if part_file.exists():
            if target_file.exists():
                target_file.unlink(missing_ok=True)
            part_file.rename(target_file)

        with task.lock:
            task.status = DownloadStatus.COMPLETED
            task.downloaded = downloaded
            task.total = downloaded
            task.speed_bps = 0
            task.conversion_progress = 1.0
        notify_fn(task)

        history_store.record_completed(
            DownloadRecord(
                platform=task.platform,
                media_id=task.media_id,
                canonical_url=task.url,
                creator=task.creator,
                title=clean_title,
                saved_filename=target_file.name,
                saved_filepath=str(target_file),
                file_extension=target_file.suffix,
            )
        )
        return True
    except Exception as e:
        part_file.unlink(missing_ok=True)
        logger.error("Custom stream download fallback error: %s", e)
        return False

