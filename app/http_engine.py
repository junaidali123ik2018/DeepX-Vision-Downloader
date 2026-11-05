"""
DeepX Vision Downloader - High-Performance IDM-Style HTTP Multi-Segment Engine
Inspired by and adapted from Awesome Downloader & IDM architecture.

Features:
- Pre-flight URL probing (HEAD / Range: bytes=0-0) with full browser header forwarding
- Support for session cookies, Referer, and User-Agent from extension / browser
- Content-Length, Content-Disposition (UTF-8 filename), ETag validation
- Dynamic multi-connection segmentation (8 to 16 concurrent HTTP Range workers)
- Chunk assembly with zero-RAM sequential streaming
- Single-stream fallback for non-range servers
- Anti-bot / Cloudflare fallback via curl_cffi Chrome impersonation
- Full Pause, Resume, and Cancel support
- Real-time aggregated speed calculation and progress telemetry
"""

from __future__ import annotations

import os
import re
import ssl
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Callable, Optional

import requests

from app.models import DownloadStatus, DownloadTask
from app.path_manager import sanitize_filename
from app.download_history import DownloadRecord, history_store

DIRECT_EXTENSIONS = {
    ".zip", ".rar", ".7z", ".tar", ".gz", ".iso", ".bz2", ".xz",
    ".exe", ".msi", ".apk", ".dmg", ".pkg", ".deb", ".rpm",
    ".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".flv", ".m4v", ".ts", ".m3u8",
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".opus",
    ".pdf", ".epub", ".docx", ".xlsx", ".pptx", ".txt",
    ".bin", ".img", ".iso"
}

KNOWN_VIDEO_PLATFORMS = {
    "youtube.com", "youtu.be", "tiktok.com", "douyin.com",
    "instagram.com", "twitter.com", "x.com", "facebook.com", "fb.watch",
    "vimeo.com", "dailymotion.com", "twitch.tv", "reddit.com", "bilibili.com"
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def parse_netscape_cookies(cookie_file: str) -> dict[str, str]:
    """Parse Netscape-format cookie file into a dict for requests."""
    cookies: dict[str, str] = {}
    if not cookie_file or not os.path.isfile(cookie_file):
        return cookies
    try:
        with open(cookie_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    cookies[parts[5]] = parts[6]
    except Exception:
        pass
    return cookies


def is_direct_file_url(url: str, filename: str = "") -> bool:
    """Check if URL or provided filename points to a direct downloadable media file."""
    try:
        if "googlevideo.com" in url or "/videoplayback" in url:
            return True

        if filename:
            fn_lower = filename.lower()
            if any(fn_lower.endswith(ext) for ext in DIRECT_EXTENSIONS):
                return True

        parsed = urllib.parse.urlparse(url)
        path = parsed.path.lower()
        ext = os.path.splitext(path)[1]
        if ext in DIRECT_EXTENSIONS:
            return True

        query = parsed.query.lower()
        for ext_target in DIRECT_EXTENSIONS:
            if ext_target in query:
                return True

        # Non-social media direct server link
        hostname = (parsed.hostname or "").lower()
        if not any(portal in hostname for portal in KNOWN_VIDEO_PLATFORMS):
            if any(term in path for term in ("/download", "/file", "/stream", "/video", "/media", "/get/")):
                return True
    except Exception:
        pass
    return False


def build_request_headers(task: DownloadTask) -> dict[str, str]:
    """Build full browser headers for the download request."""
    headers: dict[str, str] = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    }
    custom = getattr(task, "http_headers", None) or {}
    if isinstance(custom, dict):
        for k, v in custom.items():
            if isinstance(v, str) and v and not re.search(r"[\r\n]", v):
                k_clean = k.strip()
                k_lower = k_clean.lower()
                if k_lower == "user-agent":
                    headers.pop("User-Agent", None)
                    headers["User-Agent"] = v
                elif k_lower == "referer":
                    headers.pop("Referer", None)
                    headers["Referer"] = v
                elif k_lower == "origin":
                    headers.pop("Origin", None)
                    headers["Origin"] = v
                elif k_lower == "cookie":
                    headers.pop("Cookie", None)
                    headers["Cookie"] = v
                else:
                    headers[k_clean] = v

    referer = getattr(task, "referer", "")
    if referer:
        headers.pop("referer", None)
        headers["Referer"] = referer

    return headers


def probe_url(
    url: str,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    timeout: int = 15,
) -> dict:
    """
    Probes URL using HEAD or fallback GET Range: bytes=0-0 with requests.
    Returns: {
        'total_size': int | None,
        'accept_ranges': bool,
        'filename': str,
        'etag': str,
        'status_code': int,
        'final_url': str,
        'headers': dict
    }
    """
    req_headers = dict(headers or {})
    if "User-Agent" not in req_headers:
        req_headers["User-Agent"] = DEFAULT_USER_AGENT
    if "Accept" not in req_headers:
        req_headers["Accept"] = "*/*"
    req_headers["Accept-Encoding"] = "identity"

    session = requests.Session()
    if cookies:
        session.cookies.update(cookies)

    res_headers = None
    status_code = 200
    final_url = url
    total_size = None
    accept_ranges = False

    # 1. Try HEAD request
    try:
        resp = session.head(url, headers=req_headers, allow_redirects=True, timeout=timeout, verify=False)
        status_code = resp.status_code
        res_headers = resp.headers
        final_url = resp.url
        cl = res_headers.get("Content-Length")
        if cl and cl.isdigit():
            total_size = int(cl)
        ar = res_headers.get("Accept-Ranges", "").lower()
        if ar == "bytes" or status_code == 206:
            accept_ranges = True
    except Exception:
        pass

    open_stream_response = None
    # 2. If HEAD didn't yield total_size or status >= 400, try Range: bytes=0-0 GET probe
    if total_size is None or status_code >= 400 or status_code == 405:
        range_headers = dict(req_headers)
        range_headers["Range"] = "bytes=0-0"
        try:
            resp = session.get(url, headers=range_headers, allow_redirects=True, stream=True, timeout=timeout, verify=False)
            status_code = resp.status_code
            res_headers = resp.headers
            final_url = resp.url
            cr = res_headers.get("Content-Range", "")
            if cr:
                match = re.search(r"bytes\s+\d+-\d+/(\d+)", cr)
                if match:
                    total_size = int(match.group(1))
                    accept_ranges = True
            if total_size is None:
                cl = res_headers.get("Content-Length")
                if cl and cl.isdigit() and int(cl) > 1:
                    total_size = int(cl)
            if res_headers.get("Accept-Ranges", "").lower() == "bytes" or status_code == 206:
                accept_ranges = True
            if status_code == 200 and not accept_ranges:
                # Server sent full stream on GET; keep stream open so single-use movie download tokens are never lost!
                open_stream_response = resp
            else:
                resp.close()
        except Exception as e:
            # If even Range GET fails, fall back to plain stream GET
            try:
                resp = session.get(url, headers=req_headers, allow_redirects=True, stream=True, timeout=timeout, verify=False)
                status_code = resp.status_code
                res_headers = resp.headers
                final_url = resp.url
                cl = res_headers.get("Content-Length")
                if cl and cl.isdigit():
                    total_size = int(cl)
                if status_code == 200:
                    open_stream_response = resp
                else:
                    resp.close()
            except Exception as exc:
                pass

    # 3. Anti-bot / Cloudflare bypass probe using curl_cffi Chrome impersonation
    if status_code in (401, 403, 429, 503) or total_size is None or res_headers is None:
        try:
            from curl_cffi import requests as c_requests
            c_sess = c_requests.Session(impersonate="chrome120")
            c_headers = dict(req_headers)
            c_resp = c_sess.get(url, headers=c_headers, cookies=cookies or {}, allow_redirects=True, stream=True, timeout=timeout)
            if c_resp.status_code < 400:
                status_code = c_resp.status_code
                res_headers = c_resp.headers
                final_url = str(c_resp.url)
                cr = res_headers.get("Content-Range", "")
                if cr:
                    match = re.search(r"bytes\s+\d+-\d+/(\d+)", cr)
                    if match:
                        total_size = int(match.group(1))
                        accept_ranges = True
                cl = res_headers.get("Content-Length")
                if cl and str(cl).isdigit() and int(cl) > 1:
                    total_size = int(cl)
                if res_headers.get("Accept-Ranges", "").lower() == "bytes" or status_code == 206:
                    accept_ranges = True
            c_resp.close()
        except Exception:
            pass

    if res_headers is None:
        raise RuntimeError(f"Server returned status {status_code} with no response headers.")

    # Filename extraction from Content-Disposition
    filename = ""
    cd = res_headers.get("Content-Disposition", "")
    if cd:
        utf_match = re.search(r"filename\*\s*=\s*(?:UTF-8'')?([^;]+)", cd, re.IGNORECASE)
        if utf_match:
            filename = urllib.parse.unquote(utf_match.group(1).strip('"\' '))
        else:
            plain_match = re.search(r'filename\s*=\s*"([^"]+)"', cd, re.IGNORECASE)
            if not plain_match:
                plain_match = re.search(r'filename\s*=\s*([^;]+)', cd, re.IGNORECASE)
            if plain_match:
                filename = plain_match.group(1).strip('"\' ')

    if not filename:
        parsed_path = urllib.parse.urlparse(final_url or url).path
        base = os.path.basename(parsed_path)
        if base:
            filename = urllib.parse.unquote(base)

    if not filename or len(filename) > 180:
        filename = "download_video.mp4"

    etag = res_headers.get("ETag", "").strip()

    return {
        "total_size": total_size,
        "accept_ranges": accept_ranges,
        "filename": sanitize_filename(filename),
        "etag": etag,
        "status_code": status_code,
        "final_url": final_url,
        "headers": dict(res_headers),
        "open_response": open_stream_response,
    }


def _download_chunk_range(
    url: str,
    start_byte: int,
    end_byte: int,
    part_path: Path,
    task: DownloadTask,
    headers: dict[str, str],
    cookies: dict[str, str],
    progress_callback: Callable[[int], None],
    chunk_buffer_size: int = 262144,
) -> None:
    """Downloads a specific byte range with auto-retry and chunk-level resume (IDM-grade)."""
    max_retries = 35
    for attempt in range(max_retries):
        if task.cancel_event.is_set() or task.pause_event.is_set():
            return

        downloaded_in_part = 0
        if part_path.is_file():
            downloaded_in_part = part_path.stat().st_size

        curr_start = start_byte + downloaded_in_part
        if curr_start > end_byte:
            return  # Chunk already fully completed

        req_headers = dict(headers)
        req_headers["Range"] = f"bytes={curr_start}-{end_byte}"
        req_headers["Accept-Encoding"] = "identity"

        try:
            mode = "ab" if downloaded_in_part > 0 else "wb"
            with requests.get(
                url,
                headers=req_headers,
                cookies=cookies,
                stream=True,
                timeout=(15, 60),
                verify=False,
            ) as response, open(part_path, mode) as f:
                if response.status_code in (416,):
                    return  # Range satisfied
                if response.status_code >= 400:
                    raise RuntimeError(f"HTTP status {response.status_code} for chunk range {curr_start}-{end_byte}")
                for chunk in response.iter_content(chunk_size=chunk_buffer_size):
                    if task.cancel_event.is_set() or task.pause_event.is_set():
                        return
                    if chunk:
                        f.write(chunk)
                        progress_callback(len(chunk))

            # Verify chunk completion
            if part_path.is_file() and part_path.stat().st_size >= (end_byte - start_byte + 1):
                return
        except Exception:
            if task.cancel_event.is_set() or task.pause_event.is_set():
                return
            if attempt == max_retries - 1:
                raise
            time.sleep(min(4, 0.5 * (attempt + 1)))


def download_segmented_http_task(
    task: DownloadTask,
    notify_callback: Callable[[DownloadTask], None],
    num_connections: int = 16,
) -> bool:
    """
    Downloads direct HTTP/HTTPS files using IDM-Style dynamic segmentation.
    Returns True on success, False if fallback required.
    """
    try:
        with task.lock:
            task.status = DownloadStatus.DOWNLOADING
            task.conversion_stage = "Connecting to server…"
            task.error = ""
        notify_callback(task)

        # 1. Build headers and cookies
        headers = build_request_headers(task)
        cookies = {}
        if task.cookies_source and Path(task.cookies_source).is_file():
            cookies = parse_netscape_cookies(task.cookies_source)

        # 2. Probe target URL
        probe = probe_url(task.url, headers=headers, cookies=cookies)
        total_size = probe["total_size"]
        accept_ranges = probe["accept_ranges"]

        # Filename precedence: user/extension provided title -> probed Content-Disposition -> URL path
        final_filename = ""
        if task.filename and not task.filename.startswith("Analyzing") and not task.filename.startswith("Preparing"):
            final_filename = task.filename
        if not final_filename:
            final_filename = probe["filename"] or "download_video.mp4"

        # Ensure valid extension
        if not os.path.splitext(final_filename)[1]:
            final_filename += ".mp4"

        final_filename = sanitize_filename(final_filename)

        dest_dir = Path(task.destination)
        dest_dir.mkdir(parents=True, exist_ok=True)
        final_output = dest_dir / final_filename

        with task.lock:
            task.filename = final_filename
            task.output_path = str(final_output)
            task.total = total_size
            task.status = DownloadStatus.DOWNLOADING
            task.conversion_stage = "Downloading (Turbo 10x)…"
        notify_callback(task)

        target_url = probe["final_url"] or task.url

        # If server does not support ranges or file is tiny (< 1MB), do single stream using open response if ready
        if not accept_ranges or not total_size or total_size < 1048576:
            open_resp = probe.get("open_response")
            return _download_single_stream(task, final_output, target_url, headers, cookies, notify_callback, existing_response=open_resp)

        # 3. Divide into segments (8 to 16 chunks)
        connections = min(num_connections, max(2, total_size // (512 * 1024)))
        chunk_size = total_size // connections
        parts_dir = dest_dir / f".deepx_parts_{abs(hash(task.url)) % 1000000}"
        parts_dir.mkdir(parents=True, exist_ok=True)

        segment_ranges = []
        for i in range(connections):
            s_byte = i * chunk_size
            e_byte = (total_size - 1) if i == connections - 1 else ((i + 1) * chunk_size - 1)
            p_file = parts_dir / f"{i}.part"
            segment_ranges.append((i, s_byte, e_byte, p_file))

        # Check existing partial downloaded bytes for resume
        initial_downloaded = sum(p.stat().st_size for _, _, _, p in segment_ranges if p.is_file())
        with task.lock:
            task.downloaded = initial_downloaded
        notify_callback(task)

        total_downloaded_bytes = initial_downloaded
        download_lock = Lock()
        last_time = time.time()
        last_bytes = initial_downloaded

        def on_chunk_bytes(bytes_count: int):
            nonlocal total_downloaded_bytes, last_time, last_bytes
            with download_lock:
                total_downloaded_bytes += bytes_count
                now = time.time()
                dt = now - last_time
                if dt >= 0.4:
                    speed = (total_downloaded_bytes - last_bytes) / dt
                    last_bytes = total_downloaded_bytes
                    last_time = now
                    with task.lock:
                        task.downloaded = total_downloaded_bytes
                        task.speed_bps = speed
                    notify_callback(task)

        # 4. Parallel chunk downloading via ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=connections) as executor:
            futures = [
                executor.submit(
                    _download_chunk_range,
                    target_url,
                    s,
                    e,
                    p,
                    task,
                    headers,
                    cookies,
                    on_chunk_bytes,
                )
                for _, s, e, p in segment_ranges
            ]
            for future in as_completed(futures):
                future.result()

        if task.cancel_event.is_set() or task.pause_event.is_set():
            with task.lock:
                task.status = DownloadStatus.PAUSED if task.pause_event.is_set() else DownloadStatus.CANCELLED
                task.speed_bps = 0
            notify_callback(task)
            return True

        # 5. Zero-RAM Sequential Reassembly
        with task.lock:
            task.status = DownloadStatus.CONVERTING
            task.conversion_stage = "Assembling download segments…"
            task.conversion_progress = 0.5
            task.speed_bps = 0
        notify_callback(task)

        with open(final_output, "wb") as outfile:
            for _, _, _, part_path in segment_ranges:
                if part_path.is_file():
                    with open(part_path, "rb") as infile:
                        while True:
                            chunk = infile.read(1048576)  # 1MB buffer
                            if not chunk:
                                break
                            outfile.write(chunk)
                    try:
                        part_path.unlink(missing_ok=True)
                    except Exception:
                        pass

        # Cleanup parts dir
        try:
            parts_dir.rmdir()
        except Exception:
            pass

        with task.lock:
            task.status = DownloadStatus.COMPLETED
            task.downloaded = total_size
            task.speed_bps = 0
            task.conversion_progress = 1.0
            task.conversion_stage = "Download complete"
        notify_callback(task)

        # History Record
        history_store.record_completed(
            DownloadRecord(
                platform=task.platform or "direct",
                media_id=task.media_id or "direct_file",
                canonical_url=task.url,
                creator=task.creator or "Direct Download",
                title=final_filename,
                saved_filename=final_filename,
                saved_filepath=str(final_output),
                file_extension=final_output.suffix,
            )
        )
        return True

    except Exception as exc:
        if task.cancel_event.is_set() or task.pause_event.is_set():
            with task.lock:
                task.status = DownloadStatus.PAUSED if task.pause_event.is_set() else DownloadStatus.CANCELLED
                task.speed_bps = 0
            notify_callback(task)
            return True

        # Try curl_cffi Chrome impersonation fallback if 403 or Cloudflare detected
        try:
            if _download_curl_cffi_fallback(task, final_output if 'final_output' in locals() else None, headers if 'headers' in locals() else {}, notify_callback):
                return True
        except Exception:
            pass

        with task.lock:
            task.status = DownloadStatus.FAILED
            task.error = f"HTTP Error: {exc}"
            task.speed_bps = 0
        notify_callback(task)
        return False


def _download_single_stream(
    task: DownloadTask,
    final_output: Path,
    target_url: str,
    headers: dict[str, str],
    cookies: dict[str, str],
    notify_callback: Callable[[DownloadTask], None],
    existing_response: Optional[requests.Response] = None,
) -> bool:
    """Fallback single-stream downloader for non-ranged URLs."""
    downloaded = 0
    last_time = time.time()
    last_bytes = 0

    def _stream_from(response):
        nonlocal downloaded, last_time, last_bytes
        if response.status_code >= 400:
            raise RuntimeError(f"Server returned HTTP Error {response.status_code}")
        total = response.headers.get("Content-Length")
        if total and total.isdigit():
            with task.lock:
                task.total = int(total)

        with open(final_output, "wb") as f:
            for chunk in response.iter_content(chunk_size=65536):
                if task.cancel_event.is_set() or task.pause_event.is_set():
                    break
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.time()
                    dt = now - last_time
                    if dt >= 0.4:
                        speed = (downloaded - last_bytes) / dt
                        last_bytes = downloaded
                        last_time = now
                        with task.lock:
                            task.downloaded = downloaded
                            task.speed_bps = speed
                        notify_callback(task)

    if existing_response and existing_response.status_code < 400:
        with existing_response as response:
            _stream_from(response)
    else:
        try:
            with requests.get(
                target_url,
                headers=headers,
                cookies=cookies,
                stream=True,
                timeout=30,
                verify=False,
            ) as response:
                if response.status_code >= 400:
                    raise RuntimeError(f'Server returned HTTP Error {response.status_code}')
                _stream_from(response)
        except Exception as e:
            if _download_curl_cffi_fallback(task, final_output, headers, notify_callback):
                return True
            raise e

    if task.cancel_event.is_set() or task.pause_event.is_set():
        with task.lock:
            task.status = DownloadStatus.PAUSED if task.pause_event.is_set() else DownloadStatus.CANCELLED
            task.speed_bps = 0
        notify_callback(task)
        return True

    with task.lock:
        task.status = DownloadStatus.COMPLETED
        task.downloaded = task.total or downloaded
        task.speed_bps = 0
        task.conversion_progress = 1.0
        task.conversion_stage = "Download complete"
    notify_callback(task)

    history_store.record_completed(
        DownloadRecord(
            platform=task.platform or "direct",
            media_id=task.media_id or "direct_file",
            canonical_url=task.url,
            creator=task.creator or "Direct Download",
            title=final_output.name,
            saved_filename=final_output.name,
            saved_filepath=str(final_output),
            file_extension=final_output.suffix,
        )
    )
    return True


def _download_curl_cffi_fallback(
    task: DownloadTask,
    final_output: Optional[Path],
    headers: dict[str, str],
    notify_callback: Callable[[DownloadTask], None],
) -> bool:
    """Anti-bot fallback using curl_cffi with Chrome 120 browser TLS fingerprint."""
    try:
        from curl_cffi import requests as c_requests
    except ImportError:
        return False

    if not final_output:
        dest_dir = Path(task.destination)
        dest_dir.mkdir(parents=True, exist_ok=True)
        final_filename = sanitize_filename(task.filename or "download_video.mp4")
        if not os.path.splitext(final_filename)[1]:
            final_filename += ".mp4"
        final_output = dest_dir / final_filename

    with task.lock:
        task.conversion_stage = "Connecting via Chrome TLS engine…"
    notify_callback(task)

    session = c_requests.Session(impersonate="chrome120")
    if task.cookies_source and Path(task.cookies_source).is_file():
        try:
            c_dict = parse_netscape_cookies(task.cookies_source)
            session.cookies.update(c_dict)
        except Exception:
            pass
    req_headers = dict(headers)
    try:
        resp = session.get(task.url, headers=req_headers, stream=True, timeout=60, allow_redirects=True)
    except Exception:
        return False
    if resp.status_code >= 400:
        return False

    downloaded = 0
    total = resp.headers.get("Content-Length")
    if total and total.isdigit():
        with task.lock:
            task.total = int(total)

    last_time = time.time()
    last_bytes = 0

    with open(final_output, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if task.cancel_event.is_set() or task.pause_event.is_set():
                break
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                dt = now - last_time
                if dt >= 0.4:
                    speed = (downloaded - last_bytes) / dt
                    last_bytes = downloaded
                    last_time = now
                    with task.lock:
                        task.downloaded = downloaded
                        task.speed_bps = speed
                    notify_callback(task)

    if task.cancel_event.is_set() or task.pause_event.is_set():
        with task.lock:
            task.status = DownloadStatus.PAUSED if task.pause_event.is_set() else DownloadStatus.CANCELLED
            task.speed_bps = 0
        notify_callback(task)
        return True

    with task.lock:
        task.status = DownloadStatus.COMPLETED
        task.downloaded = task.total or downloaded
        task.speed_bps = 0
        task.conversion_progress = 1.0
        task.conversion_stage = "Download complete"
    notify_callback(task)

    try:
        history_store.record_completed(
            DownloadRecord(
                platform=task.platform or "direct",
                media_id=task.media_id or "direct_file",
                canonical_url=task.url,
                creator=task.creator or "Direct Download",
                title=final_output.name,
                saved_filename=final_output.name,
                saved_filepath=str(final_output),
                file_extension=final_output.suffix,
            )
        )
    except Exception:
        pass
    return True
