from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Callable, Optional
import requests

from app.version import APP_VERSION, DEFAULT_UPDATE_URL


@dataclass
class UpdateManifest:
    version: str
    release_date: str
    download_url: str
    changelog: list[str]
    mandatory: bool = False


def parse_version_tuple(v_str: str) -> tuple[int, ...]:
    clean = v_str.strip().lstrip("vV")
    parts = []
    for p in clean.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def is_newer(remote_v: str, current_v: str = APP_VERSION) -> bool:
    return parse_version_tuple(remote_v) > parse_version_tuple(current_v)


def check_for_updates(manifest_url: str = DEFAULT_UPDATE_URL, timeout: int = 5) -> tuple[bool, Optional[UpdateManifest], str]:
    """
    Checks remote manifest URL for updates.
    Returns: (update_available, manifest_obj, message)
    """
    try:
        resp = requests.get(manifest_url, timeout=timeout)
        if resp.status_code != 200:
            return False, None, f"Update server returned status {resp.status_code}."
        data = resp.json()
        remote_ver = str(data.get("version", "")).strip()
        if not remote_ver:
            return False, None, "Invalid update manifest (missing version)."

        manifest = UpdateManifest(
            version=remote_ver,
            release_date=str(data.get("release_date", "")),
            download_url=str(data.get("download_url", "")),
            changelog=list(data.get("changelog", [])),
            mandatory=bool(data.get("mandatory", False)),
        )

        if is_newer(remote_ver, APP_VERSION):
            return True, manifest, f"New version {remote_ver} is available!"
        else:
            return False, manifest, f"You are on the latest version ({APP_VERSION})."

    except requests.RequestException as e:
        return False, None, f"Could not connect to update server: {e}"
    except Exception as e:
        return False, None, f"Update check error: {e}"


def download_update_installer(
    download_url: str,
    target_dir: Optional[Path] = None,
    on_progress: Optional[Callable[[int, int, float, str], None]] = None,
    cancel_flag: Optional[threading.Event] = None,
) -> Path:
    """
    Downloads the update setup .exe with live progress reporting.
    Calls on_progress(bytes_done, total_bytes, percent, speed_str)
    """
    if target_dir is None:
        target_dir = Path(os.environ.get("TEMP", ".")) / "DeepX_Vision_Update"
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = download_url.split("/")[-1] or "DeepX_Vision_Update_Setup.exe"
    if not filename.endswith(".exe"):
        filename += ".exe"
    dest_path = target_dir / filename

    response = requests.get(download_url, stream=True, timeout=15)
    response.raise_for_status()

    total_bytes = int(response.headers.get("content-length", 0))
    bytes_done = 0
    start_time = time.time()

    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=65536):
            if cancel_flag and cancel_flag.is_set():
                raise InterruptedError("Update download cancelled by user.")
            if chunk:
                f.write(chunk)
                bytes_done += len(chunk)
                elapsed = max(0.001, time.time() - start_time)
                speed_bps = bytes_done / elapsed
                speed_str = f"{speed_bps / (1024 * 1024):.1f} MB/s"
                pct = (bytes_done / total_bytes * 100.0) if total_bytes > 0 else 0.0

                if on_progress:
                    on_progress(bytes_done, total_bytes, pct, speed_str)

    return dest_path


def apply_update_and_restart(installer_path: Path) -> None:
    """
    Spawns a detached batch script to wait for current process to exit,
    runs the installer silently, replaces the app, and relaunches the app.
    """
    current_exe = Path(sys.executable).resolve()
    temp_dir = installer_path.parent
    bat_path = temp_dir / "run_silent_update.bat"

    script_lines = [
        "@echo off",
        "title Updating DeepX Vision Downloader...",
        "echo Closing old process...",
        'taskkill /F /IM "DeepX Vision Downloader.exe" >nul 2>&1',
        "timeout /t 2 /nobreak >nul",
        f'echo Installing update: {installer_path.name}...',
        f'start /wait "" "{installer_path.resolve()}" /VERYSILENT /SUPPRESSMSGBOXES /FORCECLOSEAPPLICATIONS',
        "timeout /t 2 /nobreak >nul",
        'echo Relaunching DeepX Vision Downloader...',
        'set "EXE1=%LOCALAPPDATA%\\Programs\\DeepX Vision Downloader\\DeepX Vision Downloader.exe"',
        'set "EXE2=%ProgramFiles%\\DeepX Vision Downloader\\DeepX Vision Downloader.exe"',
        f'set "EXE3={current_exe}"',
        'if exist "%EXE1%" (',
        '    start "" "%EXE1%"',
        ') else if exist "%EXE2%" (',
        '    start "" "%EXE2%"',
        ') else if exist "%EXE3%" (',
        '    start "" "%EXE3%"',
        ')',
        "timeout /t 2 /nobreak >nul",
        f'del "{installer_path.resolve()}" >nul 2>&1',
        'del "%~f0" >nul 2>&1',
    ]

    bat_path.write_text("\n".join(script_lines), encoding="utf-8")

    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200

    subprocess.Popen(
        ["cmd.exe", "/c", str(bat_path.resolve())],
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    # Terminate current app immediately so all file handles and locks are released
    os._exit(0)


def update_core_engine_ytdlp(on_output: Optional[Callable[[str], None]] = None) -> tuple[bool, str]:
    """Updates yt-dlp core extraction rules."""
    try:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        out = (proc.stdout + "\n" + proc.stderr).strip()
        if proc.returncode == 0:
            return True, "Core Engine (yt-dlp) successfully updated to latest version!"
        return False, f"Update exited with code {proc.returncode}:\n{out[:300]}"
    except Exception as e:
        return False, f"Engine update failed: {e}"
