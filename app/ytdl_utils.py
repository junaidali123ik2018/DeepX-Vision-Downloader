from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Callable
import urllib.parse
import urllib.request

from app.models import DownloadStatus, DownloadTask
from app.path_manager import (
    extract_media_identity,
    get_creator_folder,
    get_next_duplicate_filename,
    reserve_path,
    release_path,
    sanitize_creator_name,
    sanitize_filename,
)
from app.download_history import DownloadRecord, history_store


def find_node_executable() -> str | None:
    """
    Locates the Node.js executable on the system or bundled with the application.
    Supports PATH, standard Program Files directories, nvm, and local app paths.
    """
    # 1. System PATH
    found = shutil.which("node")
    if found and Path(found).is_file():
        return str(Path(found).resolve())

    # 2. Bundled next to python executable or in bin/
    candidates = [
        Path(sys.executable).parent / "node.exe",
        Path(sys.executable).parent / "_internal" / "node.exe",
        Path(__file__).resolve().parent.parent / "bin" / "node.exe",
        Path(__file__).resolve().parent.parent / "assets" / "node.exe",
        Path(r"C:\Program Files\nodejs\node.exe"),
        Path(r"C:\Program Files (x86)\nodejs\node.exe"),
        Path.home() / "AppData" / "Roaming" / "nvm" / "current" / "node.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "node" / "node.exe",
    ]
    for c in candidates:
        try:
            if c.is_file():
                return str(c.resolve())
        except Exception:
            continue
    return None


def get_js_runtimes_config() -> dict:
    """
    Builds the js_runtimes dictionary for yt-dlp YoutubeDL options.
    Enables Node.js to solve modern YouTube JavaScript challenges (n-sig, player challenges).
    """
    node_path = find_node_executable()
    if node_path:
        return {"node": {"path": node_path}}

    deno_found = shutil.which("deno")
    if deno_found and Path(deno_found).is_file():
        return {"deno": {"path": str(Path(deno_found).resolve())}}

    return {}


def get_default_browser_headers() -> dict[str, str]:
    """
    Standard modern browser headers that mimic a desktop Chrome browser on Windows.
    Prevents anti-bot blocks across YouTube, TikTok, and social platforms.
    """
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }


def get_impersonate_target():
    """
    Returns an ImpersonateTarget instance if curl_cffi is available.
    """
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget
        return ImpersonateTarget.from_str("chrome")
    except Exception:
        return None


def apply_ytdl_robust_options(options: dict) -> dict:
    """
    Enriches yt-dlp options with:
    - Node.js JavaScript runtime for YouTube n-sig challenge solving
    - Impersonation and realistic browser headers for anti-bot platforms (TikTok, etc.)
    - Resilient retry settings
    """
    runtimes = get_js_runtimes_config()
    if runtimes and "js_runtimes" not in options:
        options["js_runtimes"] = runtimes

    if "http_headers" not in options:
        options["http_headers"] = get_default_browser_headers()

    target = get_impersonate_target()
    if target and "impersonate" not in options:
        options["impersonate"] = target

    # Ensure retries and stability
    options.setdefault("retries", 3)
    options.setdefault("fragment_retries", 3)
    options.setdefault("skip_unavailable_fragments", True)
    options.setdefault("socket_timeout", 30)

    return options


def extract_tiktok_slides(url: str) -> list[dict]:
    """
    Fetches full-resolution images for TikTok photo posts/slideshows via direct API.
    Returns list of dicts: {'url', 'title', 'ext'}.
    """
    try:
        api_url = f"https://www.tikwm.com/api/?url={urllib.parse.quote(url)}"
        req = urllib.request.Request(api_url, headers=get_default_browser_headers())
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        if data.get("code") == 0:
            d = data.get("data", {})
            raw_title = d.get("title") or "TikTok_Photo"
            clean_title = sanitize_filename(raw_title)[:80] or "TikTok_Photo"
            images = d.get("images") or []
            if images:
                return [
                    {
                        "url": img_url,
                        "title": f"{clean_title}_{i+1}" if len(images) > 1 else clean_title,
                        "ext": "jpg",
                    }
                    for i, img_url in enumerate(images)
                ]
    except Exception:
        pass
    return []


def download_tiktok_fallback(
    task: DownloadTask,
    notify_fn: Callable[[DownloadTask], None],
) -> bool:
    """
    Fallback downloader for TikTok videos and photos when yt-dlp is IP-blocked
    or encounters extraction errors (10204 / ExtractorError / No video formats).
    Uses direct CDN streams with resume, pause, cancel, and speed reporting.
    """
    clean_url = task.url.strip()
    if "tiktok.com" not in clean_url and "douyin.com" not in clean_url:
        return False

    with task.lock:
        task.status = DownloadStatus.FETCHING_INFO
        task.error = "Attempting high-speed direct extraction..."
    notify_fn(task)

    try:
        api_url = f"https://www.tikwm.com/api/?url={urllib.parse.quote(clean_url)}"
        req = urllib.request.Request(api_url, headers=get_default_browser_headers())
        with urllib.request.urlopen(req, timeout=12) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))

        if payload.get("code") != 0 or not payload.get("data"):
            return False

        d = payload["data"]

        # If post contains images instead of video, delegate to image downloader
        images = d.get("images") or []
        if images:
            from app.image_downloader import download_image_task
            return download_image_task(task, notify_fn)

        video_stream_url = d.get("play") or d.get("wmplay")
        if not video_stream_url:
            return False

        # Metadata extraction
        raw_title = d.get("title") or task.filename or "TikTok Video"
        base_name = sanitize_filename(raw_title)[:120] or "TikTok Video"
        author_info = d.get("author") or {}
        creator_name = (
            author_info.get("unique_id")
            or author_info.get("nickname")
            or task.creator
            or "TikTok"
        )
        task.creator = sanitize_creator_name(creator_name)
        task.platform = "tiktok"
        task.media_id = str(d.get("id") or "")

        if task.numbering is not None:
            clean_title = f"{task.numbering:02d}. {base_name}"
        else:
            clean_title = base_name

        # Cache thumbnail
        cover_url = d.get("origin_cover") or d.get("cover")
        if cover_url:
            task.thumbnail_url = cover_url
            try:
                dest_p = Path(task.destination)
                cache_dir = dest_p / ".thumbnails"
                cache_dir.mkdir(parents=True, exist_ok=True)
                thumb_file = cache_dir / f"{task.id}.jpg"
                t_req = urllib.request.Request(cover_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(t_req, timeout=8) as tr, open(thumb_file, "wb") as tf:
                    tf.write(tr.read())
                task.thumbnail_path = str(thumb_file)
            except Exception:
                pass

        creator_folder = get_creator_folder(task.destination, task.creator)
        creator_folder.mkdir(parents=True, exist_ok=True)

        is_audio = "AUDIO" in (task.quality or "").upper()
        if is_audio and d.get("music"):
            download_url = d["music"]
            ext = "mp3"
        else:
            download_url = video_stream_url
            ext = "mp4"

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
        existing_path_str = (
            existing_record.saved_filepath
            if existing_record
            else (str(existing_disk_file) if existing_disk_file else "")
        )

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

        try:
            with task.lock:
                task.status = DownloadStatus.DOWNLOADING
                task.filename = target_file.name
                task.output_path = str(target_file)
            notify_fn(task)

            v_req = urllib.request.Request(
                download_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "Referer": "https://www.tiktok.com/",
                },
            )

            with urllib.request.urlopen(v_req, timeout=20) as v_resp, open(part_file, "wb") as out_f:
                total_bytes = int(v_resp.headers.get("Content-Length") or d.get("size") or 0)
                with task.lock:
                    task.total = total_bytes if total_bytes > 0 else None
                notify_fn(task)

                chunk_size = 64 * 1024
                downloaded = 0
                last_time = time.time()
                last_bytes = 0

                while True:
                    if task.cancel_event.is_set():
                        part_file.unlink(missing_ok=True)
                        with task.lock:
                            task.status = DownloadStatus.CANCELLED
                            task.speed_bps = 0
                        notify_fn(task)
                        return True

                    if task.pause_event.is_set():
                        with task.lock:
                            task.status = DownloadStatus.PAUSED
                            task.speed_bps = 0
                        notify_fn(task)
                        return True

                    chunk = v_resp.read(chunk_size)
                    if not chunk:
                        break

                    out_f.write(chunk)
                    downloaded += len(chunk)

                    now = time.time()
                    elapsed = now - last_time
                    if elapsed >= 0.5:
                        speed = (downloaded - last_bytes) / elapsed
                        last_bytes = downloaded
                        last_time = now
                        with task.lock:
                            task.downloaded = downloaded
                            task.speed_bps = speed
                        notify_fn(task)

            # Move part file to final file
            if target_file.exists():
                target_file.unlink(missing_ok=True)
            part_file.rename(target_file)

            with task.lock:
                task.status = DownloadStatus.COMPLETED
                task.speed_bps = 0
                task.downloaded = downloaded
                task.total = downloaded
                task.output_path = str(target_file)
                task.error = ""
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
                    file_extension=f".{ext}",
                )
            )
            return True

        finally:
            release_path(target_file)

    except Exception as exc:
        return False
