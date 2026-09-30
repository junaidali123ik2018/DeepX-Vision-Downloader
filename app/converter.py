from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
from typing import Callable

import imageio_ffmpeg

RESOLUTION_MAP = {
    "Original": None,
    "8K (4320p)": 4320,
    "4K (2160p)": 2160,
    "2K / 1440p": 1440,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
    "240p": 240,
    "144p": 144,
}


def get_ffmpeg_path() -> str | None:
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def get_video_resolution(filepath: str) -> tuple[int, int] | None:
    """Extracts width and height of a media file using ffmpeg."""
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        return None
    try:
        cmd = [ffmpeg, "-i", filepath]
        res = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, errors="replace")
        match = re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})", res.stderr)
        if match:
            return int(match.group(1)), int(match.group(2))
    except Exception:
        pass
    return None


def get_video_duration(filepath: str) -> float | None:
    """Extracts duration in seconds of a media file using ffmpeg."""
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        return None
    try:
        cmd = [ffmpeg, "-i", filepath]
        res = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, errors="replace")
        match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", res.stderr)
        if match:
            h, m, s = float(match.group(1)), float(match.group(2)), float(match.group(3))
            return h * 3600 + m * 60 + s
    except Exception:
        pass
    return None


def convert_media(
    input_path: str,
    output_dir: str,
    target_format: str,
    target_resolution: str | None = None,
    on_progress: Callable[[float, str], None] | None = None,
) -> str:
    """Converts input media to target format and resolution with progress callbacks."""
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("FFmpeg executable not found.")

    src = Path(input_path)
    if not src.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    out_folder = Path(output_dir)
    out_folder.mkdir(parents=True, exist_ok=True)

    # Determine extension and codec flags
    fmt = target_format.upper().replace(" ", "_")
    audio_only = False
    vcodec = "libx264"
    acodec = "aac"
    ext = ".mp4"
    extra_args: list[str] = []

    # Video Formats
    if fmt in {"MP4", "ORIGINAL_VIDEO"}:
        ext = ".mp4"
        vcodec = "libx264"
        acodec = "aac"
    elif fmt == "HEVC_MP4":
        ext = ".mp4"
        vcodec = "libx265"
        acodec = "aac"
    elif fmt == "HEVC_MKV":
        ext = ".mkv"
        vcodec = "libx265"
        acodec = "aac"
    elif fmt == "MKV":
        ext = ".mkv"
        vcodec = "libx264"
        acodec = "aac"
    elif fmt == "MOV":
        ext = ".mov"
        vcodec = "libx264"
        acodec = "aac"
    elif fmt == "AVI":
        ext = ".avi"
        vcodec = "mpeg4"
        acodec = "mp3"
    elif fmt == "WMV":
        ext = ".wmv"
        vcodec = "wmv2"
        acodec = "wmav2"
    elif fmt == "FLV":
        ext = ".flv"
        vcodec = "flv"
        acodec = "mp3"
    elif fmt == "3GP":
        ext = ".3gp"
        vcodec = "h263"
        acodec = "aac"
    elif fmt in {"IPHONE/IPOD", "IPAD"}:
        ext = ".mp4"
        vcodec = "libx264"
        acodec = "aac"
        extra_args.extend(["-profile:v", "main", "-level", "3.1"])
    elif fmt in {"ANDROID_PHONE", "ANDROID_TABLETS"}:
        ext = ".mp4"
        vcodec = "libx264"
        acodec = "aac"

    # Audio Formats
    elif fmt in {"MP3", "ORIGINAL_AUDIO"}:
        audio_only = True
        ext = ".mp3"
        acodec = "libmp3lame"
        extra_args.extend(["-b:a", "192k"])
    elif fmt == "M4A":
        audio_only = True
        ext = ".m4a"
        acodec = "aac"
        extra_args.extend(["-b:a", "192k"])
    elif fmt == "WAV":
        audio_only = True
        ext = ".wav"
        acodec = "pcm_s16le"
    elif fmt == "AAC":
        audio_only = True
        ext = ".aac"
        acodec = "aac"
        extra_args.extend(["-b:a", "192k"])
    elif fmt == "FLAC":
        audio_only = True
        ext = ".flac"
        acodec = "flac"
    elif fmt == "OGG":
        audio_only = True
        ext = ".ogg"
        acodec = "libvorbis"
    elif fmt == "AIFF":
        audio_only = True
        ext = ".aiff"
        acodec = "pcm_s16be"
    elif fmt == "MKA":
        audio_only = True
        ext = ".mka"
        acodec = "aac"

    # Target output filename
    base_name = src.stem
    if target_resolution and not audio_only and target_resolution != "Original":
        clean_res = target_resolution.split()[0]
        out_filename = f"{base_name}_{clean_res}{ext}"
    else:
        out_filename = f"{base_name}_converted{ext}"

    output_path = out_folder / out_filename
    counter = 1
    while output_path.exists():
        output_path = out_folder / f"{base_name}_{counter}{ext}"
        counter += 1

    # Build FFmpeg command
    cmd = [ffmpeg, "-y", "-i", str(src)]

    if audio_only:
        cmd.extend(["-vn", "-c:a", acodec])
        cmd.extend(extra_args)
    else:
        cmd.extend(["-c:v", vcodec, "-c:a", acodec])
        cmd.extend(extra_args)

        # Handle resolution scaling
        res_height = RESOLUTION_MAP.get(target_resolution or "Original")
        if res_height:
            # -2 preserves aspect ratio and ensures width is divisible by 2
            scale_filter = f"scale=-2:{res_height}:flags=lanczos"
            cmd.extend(["-vf", scale_filter])

        # Faststart for web-friendly mp4
        if ext == ".mp4":
            cmd.extend(["-movflags", "+faststart"])

    cmd.append(str(output_path))

    total_sec = get_video_duration(str(src))
    total_us = (total_sec * 1_000_000) if total_sec else None

    # Insert -progress pipe:1 right after -y
    cmd_with_prog = [cmd[0], "-progress", "pipe:1"] + cmd[1:]

    if on_progress:
        on_progress(0.05, f"Converting to {target_format}…")

    # Run FFmpeg process
    proc = subprocess.Popen(
        cmd_with_prog,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )

    stderr_lines = []
    def read_stderr():
        if proc.stderr:
            for line in proc.stderr:
                stderr_lines.append(line)
    err_t = threading.Thread(target=read_stderr, daemon=True)
    err_t.start()

    if proc.stdout:
        for line in proc.stdout:
            if on_progress and total_us:
                m = re.search(r"out_time_us=(\d+)", line)
                if m:
                    us = int(m.group(1))
                    pct = min(0.99, max(0.05, us / total_us))
                    on_progress(pct, f"Converting to {target_format} ({int(pct*100)}%)…")

    proc.wait()
    err_t.join(timeout=1.0)
    stderr = "".join(stderr_lines)

    if proc.returncode != 0:
        err_msg = stderr[-400:] if len(stderr) > 400 else stderr
        raise RuntimeError(f"FFmpeg error: {err_msg}")

    if on_progress:
        on_progress(1.0, "Conversion complete!")

    return str(output_path)


def upscale_video_to_resolution(
    video_path: str,
    target_height: int,
    on_progress: Callable[[float, str], None] | None = None,
) -> str | None:
    """Upscales a video file to the requested resolution if source is smaller."""
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        return None

    res = get_video_resolution(video_path)
    if not res:
        return None

    src_w, src_h = res
    if src_h >= target_height:
        return video_path  # Already at or above target resolution

    src = Path(video_path)
    temp_out = src.parent / f"{src.stem}_upscaled_{target_height}p{src.suffix}"

    total_sec = get_video_duration(str(src))
    total_us = (total_sec * 1_000_000) if total_sec else None

    cmd = [
        ffmpeg, "-y", "-progress", "pipe:1", "-i", str(src),
        "-vf", f"scale=-2:{target_height}:flags=lanczos",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(temp_out),
    ]

    if on_progress:
        on_progress(0.05, f"Upscaling to {target_height}p…")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )

    if proc.stdout:
        for line in proc.stdout:
            if on_progress and total_us:
                m = re.search(r"out_time_us=(\d+)", line)
                if m:
                    us = int(m.group(1))
                    pct = min(0.99, max(0.05, us / total_us))
                    on_progress(pct, f"Upscaling to {target_height}p ({int(pct*100)}%)…")

    proc.wait()

    if proc.returncode == 0 and temp_out.is_file():
        if on_progress:
            on_progress(1.0, f"Upscaled to {target_height}p!")
        # Replace original with upscaled version
        try:
            src.unlink()
            temp_out.rename(src)
            return str(src)
        except OSError:
            return str(temp_out)
    return None
