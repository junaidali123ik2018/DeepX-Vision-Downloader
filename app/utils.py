from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse


def format_bytes(value: float | int | None) -> str:
    if value is None:
        return "Unknown"
    value = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{value:.0f} B"
        value /= 1024
    return "Unknown"


def format_speed(value: float) -> str:
    return f"{format_bytes(value)}/s" if value > 0 else "—"


def format_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds == float("inf"):
        return "—"
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:d}:{secs:02d}"


def parse_speed_limit(limit_str: str) -> int | None:
    """Parses strings like '10 MB/s', '500 KB/s', or 'Unlimited' into bytes per second."""
    if not limit_str or "unlimited" in limit_str.lower():
        return None
    try:
        parts = limit_str.strip().split()
        val = float(parts[0])
        unit = parts[1].upper()
        if "KB" in unit:
            return int(val * 1024)
        if "MB" in unit:
            return int(val * 1024 * 1024)
        if "GB" in unit:
            return int(val * 1024 * 1024 * 1024)
    except Exception:
        pass
    return None


def filename_from_response(url: str, content_disposition: str | None) -> str:
    if content_disposition:
        match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", content_disposition, re.I)
        if match:
            candidate = unquote(match.group(1)).strip().strip('"')
            if candidate:
                return sanitize_filename(candidate)
    candidate = Path(unquote(urlparse(url).path)).name or "video-download"
    return sanitize_filename(candidate)


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(". ")
    return cleaned[:180] or "video-download"


def unique_path(folder: Path, filename: str) -> Path:
    target = folder / filename
    stem, suffix = target.stem, target.suffix
    number = 1
    while target.exists() or target.with_name(target.name + ".part").exists():
        target = folder / f"{stem} ({number}){suffix}"
        number += 1
    return target


def get_asset_path(rel_path: str | Path) -> Path:
    """
    Resolves an asset file path safely whether running from:
    1. PyInstaller bundled temp folder (sys._MEIPASS)
    2. Folder containing running executable (sys.executable)
    3. Python source development tree
    4. Current working directory
    """
    import sys
    rel = Path(rel_path)

    # 1. PyInstaller bundled temp directory
    if hasattr(sys, "_MEIPASS"):
        p = Path(sys._MEIPASS) / rel
        if p.exists():
            return p

    # 2. Directory containing executable (e.g. Inno Setup install directory)
    exe_dir = Path(sys.executable).parent / rel
    if exe_dir.exists():
        return exe_dir

    # 3. Source repository root
    src_root = Path(__file__).resolve().parent.parent / rel
    if src_root.exists():
        return src_root

    # 4. Current working directory
    cwd_path = Path.cwd() / rel
    if cwd_path.exists():
        return cwd_path

    return rel


def get_appdata_dir(app_name: str = "DeepX Vision Downloader") -> Path:
    """Returns the dedicated application data directory in %APPDATA%, migrating old data if present."""
    import os
    import shutil
    base = Path(os.getenv("APPDATA", Path.home())) / app_name
    old_base = Path(os.getenv("APPDATA", Path.home())) / "HQ Video Downloader"
    if not base.exists() and old_base.exists():
        try:
            shutil.copytree(old_base, base, dirs_exist_ok=True)
        except Exception:
            return old_base
    base.mkdir(parents=True, exist_ok=True)
    return base

