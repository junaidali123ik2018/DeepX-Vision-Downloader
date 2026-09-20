from __future__ import annotations

import mimetypes
from pathlib import Path
import re
import time
from typing import Callable
import urllib.parse
import urllib.request

from app.models import DownloadStatus, DownloadTask
from app.path_manager import (
    extract_media_identity,
    get_creator_folder,
    get_next_duplicate_filename,
    sanitize_creator_name,
    sanitize_filename,
)
from app.download_history import DownloadRecord, history_store

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".svg", ".ico", ".tiff"}

IMAGE_DOMAINS = {
    "images.unsplash.com",
    "i.imgur.com",
    "pbs.twimg.com",
    "i.pinimg.com",
    "scontent.cdninstagram.com",
    "instagram.com",
    "fbcdn.net",
    "preview.redd.it",
    "i.redd.it",
}


def is_direct_image_url(url: str) -> bool:
    """Returns True if the URL points directly to an image file or known image host."""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    for ext in IMAGE_EXTENSIONS:
        if path.endswith(ext):
            return True
    host = parsed.netloc.lower()
    if any(h in host for h in ["images.unsplash.com", "i.imgur.com", "i.pinimg.com", "preview.redd.it", "i.redd.it"]):
        return True
    return False


def is_image_request(task: DownloadTask) -> bool:
    """Checks if a download task should be processed by the image downloader."""
    q_upper = (task.quality or "").upper()
    if "IMAGE" in q_upper or "PHOTO" in q_upper:
        return True
    return is_direct_image_url(task.url)


def _sanitize_title(title: str, max_len: int = 80) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip(" ._")
    return cleaned or "Image"


def extract_youtube_thumbnail(url: str) -> list[dict]:
    """Extracts max-res and high-quality YouTube thumbnail URLs."""
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([a-zA-Z0-9_-]{11})", url)
    if not m:
        return []
    vid = m.group(1)
    return [
        {
            "url": f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
            "fallback_url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "title": f"YouTube_Thumbnail_{vid}",
            "ext": "jpg",
        }
    ]


def extract_webpage_images(url: str, cookies_source: str | None = None) -> list[dict]:
    """Fetches OpenGraph og:image, twitter:image, or main article images from a web page."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if cookies_source and Path(cookies_source).is_file():
        try:
            cookies = []
            for line in Path(cookies_source).read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip() and not line.startswith("#"):
                    p = line.split("\t")
                    if len(p) >= 7:
                        cookies.append(f"{p[5]}={p[6]}")
            if cookies:
                headers["Cookie"] = "; ".join(cookies)
        except Exception:
            pass

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type", "").lower()
            if "image/" in content_type:
                ext = mimetypes.guess_extension(content_type.split(";")[0]) or ".jpg"
                ext = ext.lstrip(".")
                return [{
                    "url": url,
                    "title": "Image",
                    "ext": ext,
                }]

            html = resp.read().decode("utf-8", errors="ignore")
            title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            page_title = title_m.group(1).strip() if title_m else "Image"
            page_title = _sanitize_title(page_title)

            found_urls = []
            seen = set()
            for pattern in [
                r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
                r'<meta\s+name=["\']twitter:image["\']\s+content=["\']([^"\']+)["\']',
                r'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']twitter:image["\']',
                r'<link\s+rel=["\']image_src["\']\s+href=["\']([^"\']+)["\']',
            ]:
                for match in re.findall(pattern, html, re.I):
                    m_url = urllib.parse.urljoin(url, match)
                    if m_url not in seen:
                        seen.add(m_url)
                        found_urls.append(m_url)

            if found_urls:
                return [{
                    "url": u,
                    "title": f"{page_title}_{i+1}" if len(found_urls) > 1 else page_title,
                    "ext": "jpg",
                } for i, u in enumerate(found_urls)]
    except Exception:
        pass
    return []


def extract_media_images(url: str, cookies_source: str | None = None) -> list[dict]:
    """
    Extracts high-resolution images from any supported URL:
    - Direct image URLs (.jpg, .png, etc.)
    - Instagram single photo and multi-image carousel posts
    - YouTube video thumbnails
    - TikTok photo posts / slideshows
    - Pinterest, Twitter, Facebook, or general webpages
    """
    clean_url = url.strip()
    parsed = urllib.parse.urlparse(clean_url)

    # 1. Direct Image File URL
    path_lower = parsed.path.lower()
    for ext in IMAGE_EXTENSIONS:
        if path_lower.endswith(ext):
            clean_name = _sanitize_title(Path(parsed.path).stem)
            return [{
                "url": clean_url,
                "title": clean_name or "Image",
                "ext": ext.lstrip("."),
            }]

    # 2. YouTube Thumbnail
    if "youtube.com" in parsed.netloc or "youtu.be" in parsed.netloc:
        yt_imgs = extract_youtube_thumbnail(clean_url)
        if yt_imgs:
            return yt_imgs

    # 3. Instagram Photos & Carousels
    if "instagram.com" in parsed.netloc:
        try:
            from ui.browser_window import extract_media_images_via_process
            proc_imgs = extract_media_images_via_process(clean_url)
            if proc_imgs:
                return proc_imgs
        except Exception:
            pass

    # 4. Fallback to OpenGraph / HTML scraping
    web_imgs = extract_webpage_images(clean_url, cookies_source=cookies_source)
    if web_imgs:
        return web_imgs

    # 5. Direct Stream Fallback
    return [{
        "url": clean_url,
        "title": "Image",
        "ext": "jpg",
    }]


def download_image_task(task: DownloadTask, notify_fn: Callable[[DownloadTask], None]) -> bool:
    """
    Downloads images for the given DownloadTask.
    Supports single images and multi-photo carousels with progress updates and sequential naming.
    """
    with task.lock:
        task.status = DownloadStatus.FETCHING_INFO
        task.error = ""
        task.downloaded = 0
        task.total = None
        task.speed_bps = 0
    notify_fn(task)

    images = extract_media_images(task.url, cookies_source=task.cookies_source)
    if not images:
        with task.lock:
            task.status = DownloadStatus.FAILED
            task.error = "No images or photos found at this URL."
        notify_fn(task)
        return False

    if not task.creator:
        p, mid, c, _ = extract_media_identity(task.url)
        task.creator = sanitize_creator_name(c)
        task.platform = p
        task.media_id = mid
    else:
        task.creator = sanitize_creator_name(task.creator)

    dest_dir = get_creator_folder(task.destination, task.creator)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": task.url,
    }

    first_img_url = images[0].get("url", "")
    if first_img_url:
        with task.lock:
            task.thumbnail_url = first_img_url
        try:
            thumb_dir = dest_dir / ".thumbnails"
            thumb_dir.mkdir(parents=True, exist_ok=True)
            thumb_file = thumb_dir / f"{task.id}.jpg"
            if not thumb_file.is_file():
                req = urllib.request.Request(first_img_url, headers=headers)
                with urllib.request.urlopen(req, timeout=8) as r, open(thumb_file, "wb") as f:
                    f.write(r.read())
            with task.lock:
                task.thumbnail_path = str(thumb_file)
        except Exception:
            pass

    total_images = len(images)
    total_bytes_downloaded = 0
    start_time = time.time()
    last_saved_path = ""

    with task.lock:
        task.status = DownloadStatus.DOWNLOADING
        if total_images > 1:
            task.filename = f"Downloading {total_images} photos/slides..."
        else:
            task.filename = images[0].get("title", "Image")
    notify_fn(task)

    for idx, img_info in enumerate(images, 1):
        if task.cancel_event.is_set():
            with task.lock:
                task.status = DownloadStatus.CANCELLED
            notify_fn(task)
            return False

        if task.pause_event.is_set():
            with task.lock:
                task.status = DownloadStatus.PAUSED
            notify_fn(task)
            return False

        target_url = img_info.get("url")
        fallback_url = img_info.get("fallback_url")
        ext = img_info.get("ext", "jpg").lstrip(".")
        raw_title = sanitize_filename(img_info.get("title") or (f"Photo_{idx}" if total_images > 1 else "Photo"))

        if total_images > 1:
            base_name = f"{raw_title}_{idx:02d}"
        else:
            base_name = raw_title

        filename = f"{base_name}.{ext}"
        out_path = dest_dir / filename
        if out_path.exists() or task.is_duplicate_copy:
            out_path = get_next_duplicate_filename(dest_dir, base_name, f".{ext}")
            filename = out_path.name

        part_path = dest_dir / f"{filename}.part"

        req = urllib.request.Request(target_url, headers=headers)
        resp = None
        try:
            resp = urllib.request.urlopen(req, timeout=15)
        except urllib.error.HTTPError:
            if fallback_url:
                try:
                    req_fallback = urllib.request.Request(fallback_url, headers=headers)
                    resp = urllib.request.urlopen(req_fallback, timeout=15)
                except Exception:
                    pass
            if not resp:
                continue
        except Exception:
            if fallback_url:
                try:
                    req_fallback = urllib.request.Request(fallback_url, headers=headers)
                    resp = urllib.request.urlopen(req_fallback, timeout=15)
                except Exception:
                    pass
            if not resp:
                continue

        with resp, open(part_path, "wb") as out_file:
            content_length = resp.headers.get("Content-Length")
            img_total = int(content_length) if content_length and content_length.isdigit() else None

            while True:
                if task.cancel_event.is_set():
                    part_path.unlink(missing_ok=True)
                    with task.lock:
                        task.status = DownloadStatus.CANCELLED
                    notify_fn(task)
                    return False

                chunk = resp.read(64 * 1024)
                if not chunk:
                    break

                out_file.write(chunk)
                total_bytes_downloaded += len(chunk)
                elapsed = max(0.1, time.time() - start_time)
                speed = total_bytes_downloaded / elapsed

                with task.lock:
                    task.downloaded = total_bytes_downloaded
                    if img_total:
                        task.total = max(total_bytes_downloaded, img_total * total_images)
                    task.speed_bps = speed
                    if total_images > 1:
                        task.filename = f"[{idx}/{total_images}] {filename}"
                    else:
                        task.filename = filename
                notify_fn(task)

        part_path.replace(out_path)
        last_saved_path = str(out_path)

    with task.lock:
        task.status = DownloadStatus.COMPLETED
        task.speed_bps = 0
        task.output_path = last_saved_path
        if total_images > 1:
            task.filename = f"{total_images} photos downloaded ({dest_dir.name})"
        else:
            task.filename = Path(last_saved_path).name if last_saved_path else "Image downloaded"
        if task.total:
            task.downloaded = task.total

    if last_saved_path and Path(last_saved_path).is_file():
        saved_f = Path(last_saved_path)
        history_store.record_completed(
            DownloadRecord(
                platform=task.platform or "image",
                media_id=task.media_id,
                canonical_url=task.url,
                creator=task.creator,
                title=task.filename,
                saved_filename=saved_f.name,
                saved_filepath=str(saved_f),
                file_extension=saved_f.suffix,
            )
        )

    notify_fn(task)
    return True
