from __future__ import annotations

import queue
import re
import shutil
from pathlib import Path
from threading import Condition, Thread
from typing import Callable
import urllib.request

import imageio_ffmpeg
import yt_dlp

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
from app.ytdl_utils import apply_ytdl_robust_options, download_tiktok_fallback

TaskCallback = Callable[[DownloadTask], None]


class QuietLogger:
    """Keeps yt-dlp diagnostics inside the app instead of the launch terminal."""

    def debug(self, message: str) -> None:
        pass

    def info(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass


class DownloadManager:
    """Concurrent downloader for public direct-file and supported site URLs."""

    def __init__(self, max_workers: int, on_update: TaskCallback) -> None:
        self._queue: queue.Queue[DownloadTask | None] = queue.Queue()
        self._on_update = on_update
        self._workers: list[Thread] = []
        self._closed = False
        self._target_workers = 1
        self._active_downloads = 0
        self._worker_condition = Condition()
        self.set_worker_limit(max_workers)

    def set_worker_limit(self, limit: int) -> None:
        """Apply a new concurrent-download limit to queued work."""
        limit = max(1, min(10, int(limit)))
        with self._worker_condition:
            self._target_workers = limit
            self._worker_condition.notify_all()
        while len(self._workers) < limit:
            worker = Thread(target=self._worker, daemon=True)
            worker.start()
            self._workers.append(worker)

    def add(self, task: DownloadTask) -> None:
        self._queue.put(task)
        self._notify(task)

    def retry(self, task: DownloadTask) -> DownloadTask:
        task.cancel_event.clear()
        task.pause_event.clear()
        with task.lock:
            task.status = DownloadStatus.QUEUED
            task.downloaded = 0
            task.total = None
            task.speed_bps = 0
            task.error = ""
        self.add(task)
        return task

    def pause(self, task: DownloadTask) -> None:
        task.pause_event.set()
        if task.status in {DownloadStatus.QUEUED, DownloadStatus.FETCHING_INFO}:
            with task.lock:
                task.status = DownloadStatus.PAUSED
            self._notify(task)

    def resume(self, task: DownloadTask) -> None:
        task.pause_event.clear()
        task.cancel_event.clear()
        with task.lock:
            task.status = DownloadStatus.QUEUED
            task.error = ""
        self.add(task)

    def shutdown(self) -> None:
        self._closed = True
        with self._worker_condition:
            self._worker_condition.notify_all()
        for _ in self._workers:
            self._queue.put(None)

    def _notify(self, task: DownloadTask) -> None:
        self._on_update(task)

    def _worker(self) -> None:
        while not self._closed:
            task = self._queue.get()
            if task is None:
                return
            with self._worker_condition:
                while not self._closed and self._active_downloads >= self._target_workers:
                    self._worker_condition.wait()
                if self._closed:
                    return
                self._active_downloads += 1
            try:
                if task.pause_event.is_set():
                    with task.lock:
                        task.status = DownloadStatus.PAUSED
                    self._notify(task)
                elif task.cancel_event.is_set():
                    with task.lock:
                        task.status = DownloadStatus.CANCELLED
                    self._notify(task)
                else:
                    self._download(task)
            finally:
                with self._worker_condition:
                    self._active_downloads -= 1
                    self._worker_condition.notify_all()

    def _cache_thumbnail(self, task: DownloadTask, thumb_url: str) -> None:
        if not thumb_url:
            return
        try:
            cache_dir = Path(task.destination) / ".thumbnails"
            cache_dir.mkdir(parents=True, exist_ok=True)
            thumb_file = cache_dir / f"{task.id}.jpg"
            req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as response, open(thumb_file, "wb") as out:
                out.write(response.read())
            with task.lock:
                task.thumbnail_path = str(thumb_file)
            self._notify(task)
        except Exception:
            pass

    def _format_selector(self, quality: str, has_ffmpeg: bool) -> tuple[str, list[dict]]:
        postprocessors = []
        q_upper = quality.upper()

        if "AUDIO" in q_upper:
            format_str = "bestaudio/best"
            if has_ffmpeg:
                target_codec = "mp3"
                if "M4A" in q_upper:
                    target_codec = "m4a"
                elif "WAV" in q_upper:
                    target_codec = "wav"
                elif "FLAC" in q_upper:
                    target_codec = "flac"
                elif "AAC" in q_upper:
                    target_codec = "aac"
                postprocessors.append({
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": target_codec,
                    "preferredquality": "192",
                })
        elif "8K" in q_upper or "4320" in q_upper:
            # Download best available; post-download will upscale if needed
            format_str = "bestvideo+bestaudio/best" if has_ffmpeg else "b"
        elif "4K" in q_upper or "2160" in q_upper:
            format_str = "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best" if has_ffmpeg else "best[height<=2160]/best"
        elif "2K" in q_upper or "1440" in q_upper:
            format_str = "bestvideo[height<=1440]+bestaudio/best[height<=1440]/best" if has_ffmpeg else "best[height<=1440]/best"
        elif "1080" in q_upper:
            format_str = "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best" if has_ffmpeg else "best[height<=1080]/best"
        elif "720" in q_upper:
            format_str = "bestvideo[height<=720]+bestaudio/best[height<=720]/best" if has_ffmpeg else "best[height<=720]/best"
        elif "480" in q_upper:
            format_str = "bestvideo[height<=480]+bestaudio/best[height<=480]/best" if has_ffmpeg else "best[height<=480]/best"
        elif "360" in q_upper:
            format_str = "bestvideo[height<=360]+bestaudio/best[height<=360]/best" if has_ffmpeg else "best[height<=360]/best"
        elif "240" in q_upper:
            format_str = "bestvideo[height<=240]+bestaudio/best[height<=240]/best" if has_ffmpeg else "best[height<=240]/best"
        elif "144" in q_upper:
            format_str = "bestvideo[height<=144]+bestaudio/best[height<=144]/best" if has_ffmpeg else "best[height<=144]/best"
        else:  # "Best Available"
            format_str = "bv*+ba/b" if has_ffmpeg else "b"

        return format_str, postprocessors

    def _download(self, task: DownloadTask) -> None:
        from app.image_downloader import is_image_request, download_image_task
        if is_image_request(task):
            download_image_task(task, self._notify)
            return

        with task.lock:
            task.status = DownloadStatus.FETCHING_INFO
            task.error = ""
        self._notify(task)

        def progress_hook(progress: dict) -> None:
            if task.pause_event.is_set():
                raise DownloadPaused()
            if task.cancel_event.is_set():
                raise DownloadCancelled()
            if progress.get("status") == "downloading":
                total = progress.get("total_bytes") or progress.get("total_bytes_estimate")
                path = progress.get("filename", "")
                with task.lock:
                    task.status = DownloadStatus.DOWNLOADING
                    if path:
                        task.filename = Path(path).name.removesuffix(".part")
                    task.downloaded = int(progress.get("downloaded_bytes") or 0)
                    task.total = int(total) if total else None
                    task.speed_bps = float(progress.get("speed") or 0)
                self._notify(task)
            elif progress.get("status") == "finished":
                path = progress.get("filename", "")
                if path:
                    with task.lock:
                        task.output_path = path
                        task.filename = Path(path).name

        def postprocessor_hook(progress: dict) -> None:
            info = progress.get("info_dict") or {}
            path = info.get("filepath")
            if path:
                with task.lock:
                    task.output_path = path
                    task.filename = Path(path).name

        try:
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        except (RuntimeError, Exception):
            ffmpeg_path = shutil.which("ffmpeg")

        format_str, postprocessors = self._format_selector(task.quality, bool(ffmpeg_path))

        if task.numbering is not None:
            out_template = str(Path(task.destination) / f"{task.numbering:02d}. %(title).200B.%(ext)s")
        else:
            out_template = str(Path(task.destination) / "%(title).200B.%(ext)s")

        options = {
            "format": format_str,
            "format_sort": ["res", "fps", "br"],
            "outtmpl": out_template,
            "windowsfilenames": True,
            "noplaylist": True,
            "overwrites": False,
            "quiet": True,
            "no_warnings": True,
            "logger": QuietLogger(),
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [postprocessor_hook],
            "postprocessors": postprocessors,
        }
        if ffmpeg_path:
            options["ffmpeg_location"] = ffmpeg_path
            if "AUDIO" not in task.quality.upper():
                options["merge_output_format"] = "mp4"
        if task.speed_limit_bps:
            options["ratelimit"] = task.speed_limit_bps

        apply_ytdl_robust_options(options)
        cookie_src = task.cookies_source
        if not cookie_src:
            try:
                from ui.browser_window import detect_platform_from_url, get_cookie_file_path
                platform = detect_platform_from_url(task.url)
                p_cookie = get_cookie_file_path(platform)
                if p_cookie.is_file() and p_cookie.stat().st_size > 50:
                    cookie_src = str(p_cookie)
                else:
                    b_cookie = get_cookie_file_path("browser")
                    if b_cookie.is_file() and b_cookie.stat().st_size > 50:
                        cookie_src = str(b_cookie)
            except Exception:
                pass

        if cookie_src:
            if Path(cookie_src).is_file():
                options["cookiefile"] = cookie_src
            else:
                options["cookiesfrombrowser"] = (cookie_src,)

        target_file = Path(task.destination) / "output.mp4"
        clean_title = task.filename
        reserved_final_path: Path | None = None

        try:
            Path(task.destination).mkdir(parents=True, exist_ok=True)
            with yt_dlp.YoutubeDL(options) as downloader:
                # 1. Fetch info and thumbnail first
                raw_title = ""
                try:
                    info = downloader.extract_info(task.url, download=False)
                    if info:
                        raw_title = info.get("title", "")
                        platform, mid, creator, _ = extract_media_identity(task.url, info)
                        task.platform = platform
                        task.media_id = mid
                        if not task.creator:
                            task.creator = sanitize_creator_name(creator)
                        task.thumbnail_url = info.get("thumbnail", "")
                        if task.thumbnail_url:
                            self._cache_thumbnail(task, task.thumbnail_url)
                except Exception:
                    pass

                if task.cancel_event.is_set():
                    raise DownloadCancelled()
                if task.pause_event.is_set():
                    raise DownloadPaused()

                # 2. Determine Creator Folder & Original Creator Title Filename
                task.creator = sanitize_creator_name(task.creator)
                creator_folder = get_creator_folder(task.destination, task.creator)

                base_name = sanitize_filename(raw_title or task.filename)
                if task.numbering is not None:
                    clean_title = f"{task.numbering:02d}. {base_name}"
                else:
                    clean_title = base_name

                with task.lock:
                    task.filename = clean_title

                # 3. Check for duplicates
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

                # 4. If duplicate and not pre-approved, prompt user
                if is_duplicate and not task.is_duplicate_copy:
                    if task.on_duplicate_prompt:
                        user_confirmed = task.on_duplicate_prompt(clean_title, task.creator, existing_path_str)
                        if not user_confirmed:
                            with task.lock:
                                task.status = DownloadStatus.CANCELLED
                                task.error = "Download cancelled — video already exists."
                                task.speed_bps = 0
                            self._notify(task)
                            return
                        else:
                            task.is_duplicate_copy = True
                    else:
                        task.is_duplicate_copy = True

                # 5. Determine unique target path and reserve it
                ext = "mp3" if "AUDIO" in task.quality.upper() else "mp4"
                if task.is_duplicate_copy:
                    target_file = get_next_duplicate_filename(creator_folder, clean_title, f".{ext}")
                else:
                    target_file = creator_folder / f"{clean_title}.{ext}"

                final_stem = target_file.stem
                reserved_final_path = target_file
                reserve_path(reserved_final_path)

                # Update yt-dlp outtmpl to target creator folder and final stem
                downloader.params["outtmpl"] = {"default": str(creator_folder / f"{final_stem}.%(ext)s")}
                with task.lock:
                    task.output_path = str(target_file)
                    task.filename = target_file.name

                # 6. Begin download
                with task.lock:
                    task.status = DownloadStatus.DOWNLOADING
                self._notify(task)
                downloader.download([task.url])

            # Auto-upscale to target resolution if user specified 8K or 4K and source was smaller
            if task.output_path and Path(task.output_path).is_file():
                q_upper = task.quality.upper()
                target_h = None
                if "8K" in q_upper or "4320" in q_upper:
                    target_h = 4320
                elif "4K" in q_upper or "2160" in q_upper:
                    target_h = 2160

                if target_h:
                    try:
                        from app.converter import upscale_video_to_resolution
                        with task.lock:
                            task.error = f"Converting/Upscaling to {task.quality}..."
                        self._notify(task)
                        upscaled = upscale_video_to_resolution(task.output_path, target_h)
                        if upscaled:
                            task.output_path = upscaled
                    except Exception:
                        pass

            if task.delete_file_on_remove and task.output_path:
                Path(task.output_path).unlink(missing_ok=True)

            with task.lock:
                task.status = DownloadStatus.COMPLETED
                task.speed_bps = 0
                if task.total:
                    task.downloaded = task.total
            self._notify(task)

            # Record in download history store
            actual_file = Path(task.output_path) if task.output_path and Path(task.output_path).is_file() else target_file
            history_store.record_completed(
                DownloadRecord(
                    platform=task.platform,
                    media_id=task.media_id,
                    canonical_url=task.url,
                    creator=task.creator,
                    title=clean_title,
                    saved_filename=actual_file.name,
                    saved_filepath=str(actual_file),
                    file_extension=actual_file.suffix,
                )
            )

        except (DownloadCancelled, DownloadPaused):
            with task.lock:
                task.status = DownloadStatus.PAUSED if task.pause_event.is_set() else DownloadStatus.CANCELLED
                task.speed_bps = 0
            self._notify(task)
        except (yt_dlp.utils.DownloadError, OSError, ValueError) as error:
            err_str = str(error)
            # Automatic fallback for TikTok if yt-dlp gets IP-blocked or encounters format issues
            if "tiktok.com" in task.url.lower() or "douyin.com" in task.url.lower():
                try:
                    if download_tiktok_fallback(task, self._notify):
                        return
                except Exception:
                    pass

            if "No video formats found" in err_str or "Unsupported URL" in err_str or "ExtractorError" in err_str:
                try:
                    from app.image_downloader import download_image_task
                    with task.lock:
                        task.status = DownloadStatus.FETCHING_INFO
                        task.error = "Checking for photos/images..."
                    self._notify(task)
                    if download_image_task(task, self._notify):
                        return
                except Exception:
                    pass

            with task.lock:
                task.status = (
                    DownloadStatus.PAUSED if task.pause_event.is_set()
                    else DownloadStatus.CANCELLED if task.cancel_event.is_set()
                    else DownloadStatus.FAILED
                )
                task.speed_bps = 0
                message = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(error))
                if "Requested format is not available" in message:
                    message = (
                        "Requested format is not available for this video. Try selecting 'Best Available' or another resolution."
                    )
                task.error = "Paused" if task.pause_event.is_set() else "Cancelled" if task.cancel_event.is_set() else message.replace("ERROR: ", "")
            self._notify(task)
        finally:
            if reserved_final_path:
                release_path(reserved_final_path)


class DownloadCancelled(Exception):
    """Raised from a yt-dlp progress hook to stop this download."""


class DownloadPaused(Exception):
    """Raised from a yt-dlp progress hook to preserve the partial download."""
