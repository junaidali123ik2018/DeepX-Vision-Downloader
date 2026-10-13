from __future__ import annotations

import os
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


# Thread-safe reservation registry for output filepaths
_RESERVED_LOCK = threading.Lock()
_RESERVED_PATHS: set[str] = set()


def reserve_path(path: str | Path) -> None:
    """Reserves a filepath so concurrent downloads do not allocate the same filename."""
    norm = str(Path(path).resolve()).lower()
    with _RESERVED_LOCK:
        _RESERVED_PATHS.add(norm)


def release_path(path: str | Path) -> None:
    """Releases a reserved filepath."""
    norm = str(Path(path).resolve()).lower()
    with _RESERVED_LOCK:
        _RESERVED_PATHS.discard(norm)


def is_path_reserved(path: str | Path) -> bool:
    """Checks if a filepath is currently reserved by an active download."""
    norm = str(Path(path).resolve()).lower()
    with _RESERVED_LOCK:
        return norm in _RESERVED_PATHS


def get_reserved_paths() -> set[str]:
    """Returns a snapshot copy of all currently reserved paths."""
    with _RESERVED_LOCK:
        return set(_RESERVED_PATHS)


def sanitize_filename(name: str | None) -> str:
    r"""
    Sanitizes a title for safe use as a Windows/OS filename.
    STRICT RULES:
    1. Preserve original creator video title as much as possible.
    2. NEVER add dates, times, resolutions, timestamps, platform names, or usernames.
    3. Safely replace or remove only OS-invalid characters: \ / : * ? " < > |
    4. Strip trailing spaces and dots (invalid on Windows).
    """
    if not name or not str(name).strip():
        return "Untitled Media"

    text = str(name).strip()

    # Safely replace invalid path separators & colons
    text = text.replace(":", " - ")
    text = text.replace("/", "-").replace("\\", "-")

    # Remove remaining invalid Windows characters: * ? " < > |
    text = re.sub(r'[?*"<>|]', "", text)

    # Collapse repeated whitespace
    text = re.sub(r"\s+", " ", text).strip(". ")

    if not text:
        return "Untitled Media"

    # Avoid exceeding Windows MAX_PATH limits while keeping up to 200 characters of the original title
    if len(text) > 200:
        text = text[:200].rstrip(". ")

    return text


def sanitize_creator_name(creator: str | None) -> str:
    """
    Sanitizes a creator handle/username for folder naming.
    RULES:
    1. Strip leading '@' (e.g. '@MrBeast' -> 'MrBeast', '@cristiano' -> 'cristiano').
    2. Remove OS-invalid characters.
    3. Fallback to 'Unknown Creator' if empty.
    """
    if not creator or not str(creator).strip():
        return "Unknown Creator"

    c = str(creator).strip()
    if c.startswith("@"):
        c = c[1:].strip()

    # Remove invalid characters
    c = re.sub(r'[<>:"/\\|?*]', "_", c).strip(". ")

    return c if c else "Unknown Creator"


def get_creator_folder(base_folder: str | Path, creator: str | None) -> Path:
    """
    Returns the Path to the creator's folder inside base_folder and ensures it exists.
    Example:
      base_folder: C:\\Users\\Junaid Ali\\Desktop
      creator: @MrBeast
      Result: C:\\Users\\Junaid Ali\\Desktop\\MrBeast (created automatically)
    """
    base = Path(base_folder)
    folder_name = sanitize_creator_name(creator)
    creator_path = base / folder_name
    try:
        creator_path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return creator_path


def normalize_url(url: str) -> str:
    """
    Strips tracking queries and hash fragments to get a canonical clean URL.
    Removes tracking parameters like utm_*, si, fbclid, igshid, etc.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        qs = parse_qs(parsed.query)
        tracking_params = {
            "si", "utm_source", "utm_medium", "utm_campaign", "utm_term",
            "utm_content", "fbclid", "igshid", "feature", "app", "_r",
            "is_from_webapp", "sender_device", "share_id"
        }
        clean_qs = {k: v for k, v in qs.items() if k.lower() not in tracking_params}
        new_query = urlencode(clean_qs, doseq=True)
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.params, new_query, ""))
    except Exception:
        return url.strip()


def extract_media_identity(url: str, info: dict | None = None) -> tuple[str, str, str, str]:
    """
    Extracts (platform, media_id, creator, title) from URL and optional yt-dlp/platform info.
    Returns:
      (platform_name, media_id, creator_username, video_title)
    """
    norm = normalize_url(url)
    parsed = urlparse(norm)
    netloc = parsed.netloc.lower()
    path = parsed.path

    platform = "web"
    media_id = ""
    creator = ""
    title = ""

    if info:
        title = info.get("title") or ""
        media_id = str(info.get("id") or "")
        creator = (
            info.get("uploader_id")
            or info.get("uploader")
            or info.get("channel")
            or info.get("creator")
            or info.get("channel_id")
            or ""
        )
        extractor = (info.get("extractor") or info.get("extractor_key") or "").lower()
        if "moviebox" in extractor:
            platform = "moviebox"
        elif "watchmovies" in extractor:
            platform = "watchmoviespk"
        elif "youtube" in extractor:
            platform = "youtube"
        elif "tiktok" in extractor:
            platform = "tiktok"
        elif "instagram" in extractor:
            platform = "instagram"
        elif "facebook" in extractor:
            platform = "facebook"
        elif "twitter" in extractor or extractor in ("x", "x.com") or extractor.startswith("x:"):
            platform = "twitter"
        elif "pinterest" in extractor:
            platform = "pinterest"

    # If platform or media_id not fully resolved from info, extract via regex on URL:
    if not platform or platform == "web":
        if "youtube.com" in netloc or "youtu.be" in netloc:
            platform = "youtube"
            if "youtu.be" in netloc:
                media_id = media_id or path.strip("/").split("/")[0]
            elif "/shorts/" in path:
                media_id = media_id or path.split("/shorts/")[1].split("/")[0]
            elif "/watch" in path:
                qs = parse_qs(parsed.query)
                v = qs.get("v")
                if v:
                    media_id = media_id or v[0]
        elif "tiktok.com" in netloc:
            platform = "tiktok"
            m = re.search(r"@([^/]+)/video/(\d+)", path)
            if m:
                creator = creator or m.group(1)
                media_id = media_id or m.group(2)
            elif "/video/" in path:
                media_id = media_id or path.split("/video/")[1].split("/")[0]
        elif "instagram.com" in netloc:
            platform = "instagram"
            m = re.search(r"/(?:p|reel|tv)/([a-zA-Z0-9_-]+)", path)
            if m:
                media_id = media_id or m.group(1)
        elif "twitter.com" in netloc or "x.com" in netloc:
            platform = "twitter"
            m = re.search(r"/([^/]+)/status/(\d+)", path)
            if m:
                creator = creator or m.group(1)
                media_id = media_id or m.group(2)
        elif "pinterest.com" in netloc or "pin.it" in netloc:
            platform = "pinterest"
            m = re.search(r"/pin/(\d+)", path)
            if m:
                media_id = media_id or m.group(1)
        elif "facebook.com" in netloc:
            platform = "facebook"
        elif "moviebox" in netloc:
            platform = "moviebox"
            creator = creator or "MovieBox"
            m = re.search(r"/(?:detailpage|movies)/([^/?#]+)", path)
            if m:
                media_id = media_id or m.group(1)
        elif "watch-movies" in netloc:
            platform = "watchmoviespk"
            creator = creator or "Watch-Movies"
            m = re.search(r"/([^/?#]+-watch-online[^/?#]*)", path)
            if m:
                media_id = media_id or m.group(1)
            else:
                parts = [p for p in path.split("/") if p]
                if parts:
                    media_id = media_id or parts[-1]

    if not media_id:
        # Fallback to last non-empty path component
        parts = [p for p in path.split("/") if p]
        media_id = parts[-1] if parts else norm

    return platform, media_id, creator, title


def get_next_duplicate_filename(folder: Path, base_title: str, ext: str) -> Path:
    """
    Computes the next available numbered filename:
      Original: Video Title.mp4
      Second copy: Video Title (1).mp4
      Third copy: Video Title (2).mp4
      Fourth copy: Video Title (3).mp4

    Checks both existing files inside the creator's folder AND active in-memory reservations.
    Numbering is placed strictly BEFORE the extension.
    """
    clean_title = sanitize_filename(base_title)
    if not ext.startswith("."):
        ext = f".{ext}"

    pattern = re.compile(rf"^{re.escape(clean_title)}\s*\((\d+)\){re.escape(ext)}$", re.IGNORECASE)
    used_numbers: set[int] = set()

    # 1. Check disk files in folder
    if folder.exists():
        for item in folder.iterdir():
            if not item.is_file():
                continue
            name = item.name
            if name.lower() == f"{clean_title}{ext}".lower():
                used_numbers.add(0)
            m = pattern.match(name)
            if m:
                try:
                    used_numbers.add(int(m.group(1)))
                except ValueError:
                    pass

    # 2. Check actively reserved paths
    reserved = get_reserved_paths()
    folder_resolved = str(folder.resolve()).lower()
    for r in reserved:
        try:
            r_path = Path(r)
            if str(r_path.parent).lower() == folder_resolved:
                name = r_path.name
                if name.lower() == f"{clean_title}{ext}".lower():
                    used_numbers.add(0)
                m = pattern.match(name)
                if m:
                    try:
                        used_numbers.add(int(m.group(1)))
                    except ValueError:
                        pass
        except Exception:
            pass

    # Find the lowest available number starting from 1
    num = 1
    while num in used_numbers:
        num += 1

    return folder / f"{clean_title} ({num}){ext}"
