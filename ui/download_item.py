from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import time

import customtkinter as ctk
from PIL import Image

from app.models import DownloadStatus, DownloadTask
from app.utils import format_bytes, format_eta, format_speed

# Ultra-Modern Pro Dark Palette
ITEM_SURFACE = ("#FFFFFF", "#0F172A")
ITEM_BORDER = ("#E2E8F0", "#1E293B")
TEXT_PRIMARY = ("#0F172A", "#F8FAFC")
TEXT_MUTED = ("#64748B", "#94A3B8")

# Badge Palettes (Light / Dark)
BLUE_BG = ("#EFF6FF", "#0C2340")
BLUE_FG = ("#2563EB", "#38BDF8")
BLUE_BTN = ("#EFF6FF", "#13233C")
BLUE_BTN_HOVER = ("#DBEAFE", "#1E3A5F")
BLUE_BTN_TEXT = ("#2563EB", "#60A5FA")

PAUSE_BG = ("#FEF3C7", "#2D2006")
PAUSE_FG = ("#D97706", "#FBBF24")
PAUSE_BTN = ("#FEF3C7", "#2D2006")
PAUSE_BTN_HOVER = ("#FDE68A", "#42300A")
PAUSE_BTN_TEXT = ("#B45309", "#FBBF24")

DONE_BG = ("#ECFDF5", "#062E1E")
DONE_FG = ("#16A34A", "#34D399")

FOLDER_BTN = ("#EFF6FF", "#132E4F")
FOLDER_BTN_HOVER = ("#DBEAFE", "#1E4A7D")
FOLDER_BTN_TEXT = ("#2563EB", "#93C5FD")

DANGER_BG = ("#FEF2F2", "#3D1217")
DANGER_FG = ("#DC2626", "#F87171")
DANGER_BTN = ("#FEF2F2", "#3D1217")
DANGER_BTN_HOVER = ("#FEE2E2", "#5A1B22")
DANGER_TEXT = ("#DC2626", "#F87171")


class DownloadItem(ctk.CTkFrame):
    """A sleek, modern dashboard card for one download item with thumbnail preview."""

    def __init__(self, master, task: DownloadTask, on_cancel, on_retry, on_pause, on_resume, on_context) -> None:
        super().__init__(master, corner_radius=10, fg_color=ITEM_SURFACE, border_width=1, border_color=ITEM_BORDER)
        self.task = task
        self.on_cancel, self.on_retry = on_cancel, on_retry
        self.on_pause, self.on_resume, self.on_context = on_pause, on_resume, on_context
        self._thumb_loaded = False
        self._last_state: tuple | None = None
        self._last_thumb_checked: float = 0.0
        self._last_filename: str = task.filename or ""

        # Modern Thumbnail / Status Badge
        self.icon = ctk.CTkLabel(
            self,
            text="↓",
            width=76,
            height=50,
            corner_radius=8,
            fg_color=BLUE_BG,
            text_color=BLUE_FG,
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
        )
        self.icon.grid(row=0, column=0, rowspan=2, padx=(12, 12), pady=11)

        # Title label
        self.name = ctk.CTkLabel(
            self,
            text=task.filename or "Preparing download…",
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            anchor="w",
        )
        self.name.grid(row=0, column=1, sticky="ew", pady=(10, 2))

        # Details / telemetry row
        self.details = ctk.CTkLabel(
            self,
            text=f"{task.quality}  •  Queued — waiting for download slot",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            anchor="w",
        )
        self.details.grid(row=1, column=1, sticky="ew", pady=(0, 10))

        # Progress bar
        self.progress = ctk.CTkProgressBar(
            self,
            height=5,
            corner_radius=4,
            progress_color=BLUE_FG,
            fg_color=("#E2E8F0", "#1E293B"),
        )
        self.progress.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 10))
        self.progress.set(0)

        # Action button (Pause/Resume/Retry/Cancel/Open)
        self.button = ctk.CTkButton(
            self,
            text="Cancel",
            width=84,
            height=30,
            corner_radius=8,
            fg_color=BLUE_BTN,
            hover_color=BLUE_BTN_HOVER,
            text_color=BLUE_BTN_TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            command=self._action,
        )
        self.button.grid(row=0, column=2, rowspan=2, padx=(10, 12), pady=11)

        self.grid_columnconfigure(1, weight=1)

        for widget in (self, self.icon, self.name, self.details, self.progress, self.button):
            widget.bind("<Button-3>", self._right_click)
            if hasattr(widget, "_label") and widget._label:
                widget._label.bind("<Button-3>", self._right_click)
            if hasattr(widget, "_canvas") and widget._canvas:
                widget._canvas.bind("<Button-3>", self._right_click)

    def _action(self) -> None:
        if self.task.status == DownloadStatus.DOWNLOADING:
            self.on_pause(self.task)
        elif self.task.status == DownloadStatus.CONVERTING:
            self.on_cancel(self.task)
        elif self.task.status == DownloadStatus.PAUSED:
            self.on_resume(self.task)
        elif self.task.status in {DownloadStatus.FAILED, DownloadStatus.CANCELLED}:
            self.on_retry(self.task)
        elif self.task.status == DownloadStatus.COMPLETED:
            self._open_file_location()
        else:
            self.on_cancel(self.task)

    def _open_file_location(self) -> None:
        try:
            target = self.task.output_path or self.task.destination
            if target and os.path.exists(target):
                norm = os.path.normpath(str(target))
                if os.path.isfile(norm):
                    subprocess.Popen(f'explorer /select,"{norm}"')
                else:
                    subprocess.Popen(f'explorer "{norm}"')
            elif self.task.destination and os.path.isdir(self.task.destination):
                subprocess.Popen(f'explorer "{os.path.normpath(self.task.destination)}"')
        except Exception:
            pass

    def _right_click(self, event) -> None:
        self.on_context(self.task, event.x_root, event.y_root)

    def _try_load_thumbnail(self) -> None:
        if self._thumb_loaded or not self.task.thumbnail_path:
            return
        p = Path(self.task.thumbnail_path)
        if p.is_file():
            try:
                pil_img = Image.open(p)
                ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(76, 50))
                self.icon.configure(image=ctk_img, text="")
                self._thumb_loaded = True
            except Exception:
                pass

    def refresh(self) -> None:
        with self.task.lock:
            status = self.task.status
            filename = self.task.filename
            downloaded = self.task.downloaded
            total = self.task.total
            speed = self.task.speed_bps
            error = self.task.error
            progress = self.task.progress
            quality = self.task.quality
            stage = getattr(self.task, "conversion_stage", "Converting…")

        current_state = (status, filename, downloaded, total, speed, error, round(progress, 3), quality, stage)
        if current_state == self._last_state:
            if not self._thumb_loaded and self.task.thumbnail_path:
                now = time.time()
                if now - self._last_thumb_checked > 3.0:
                    self._last_thumb_checked = now
                    self._try_load_thumbnail()
            return
        self._last_state = current_state

        if filename != self._last_filename:
            self._last_filename = filename
            self.name.configure(text=filename)

        self._try_load_thumbnail()

        if status == DownloadStatus.DOWNLOADING:
            remaining = (total - downloaded) / speed if total and speed else None
            detail = f"{quality}  •  {format_bytes(downloaded)} / {format_bytes(total)}  •  {format_speed(speed)}  •  ⚡ Turbo 10x  •  {format_eta(remaining)} left"
            if not self._thumb_loaded:
                self.icon.configure(text="↓", fg_color=BLUE_BG, text_color=BLUE_FG)
            self.button.configure(
                text="Pause",
                state="normal",
                fg_color=BLUE_BTN,
                hover_color=BLUE_BTN_HOVER,
                text_color=BLUE_BTN_TEXT,
            )

        elif status == DownloadStatus.CONVERTING:
            pct_int = int(round(progress * 100))
            detail = f"{quality}  •  {stage}  •  {pct_int}%"
            if not self._thumb_loaded:
                self.icon.configure(text="⚡", fg_color=("#EDE9FE", "#2A1647"), text_color=("#7C3AED", "#C084FC"))
            self.button.configure(
                text="Converting…",
                state="disabled",
                fg_color=("#F1F5F9", "#1E293B"),
                text_color=TEXT_MUTED,
            )

        elif status == DownloadStatus.PAUSED:
            detail = f"{quality}  •  Paused — click Resume to continue"
            if not self._thumb_loaded:
                self.icon.configure(text="⏸", fg_color=PAUSE_BG, text_color=PAUSE_FG)
            self.button.configure(
                text="Resume",
                state="normal",
                fg_color=PAUSE_BTN,
                hover_color=PAUSE_BTN_HOVER,
                text_color=PAUSE_BTN_TEXT,
            )

        elif status == DownloadStatus.COMPLETED:
            detail, progress = f"{quality}  •  Completed  •  {format_bytes(downloaded or total)}  •  Saved to Downloads", 1.0
            if not self._thumb_loaded:
                self.icon.configure(text="✓", fg_color=DONE_BG, text_color=DONE_FG)
            self.button.configure(
                text="📂 Open",
                state="normal",
                fg_color=FOLDER_BTN,
                hover_color=FOLDER_BTN_HOVER,
                text_color=FOLDER_BTN_TEXT,
            )

        elif status == DownloadStatus.FAILED:
            clean_err = re.sub(r"^(?:ERROR|HTTP Error \d+|Exception):\s*", "", error or "Server connection failed").strip()
            if len(clean_err) > 60:
                clean_err = clean_err[:57] + "…"
            detail = f"{quality}  •  Download failed: {clean_err or 'Server connection error'}"
            if not self._thumb_loaded:
                self.icon.configure(text="✕", fg_color=DANGER_BG, text_color=DANGER_FG)
            self.button.configure(
                text="Retry",
                state="normal",
                fg_color=DANGER_BTN,
                hover_color=DANGER_BTN_HOVER,
                text_color=DANGER_TEXT,
            )

        elif status == DownloadStatus.CANCELLED:
            detail = f"{quality}  •  Cancelled"
            if not self._thumb_loaded:
                self.icon.configure(text="—", fg_color=("#F1F5F9", "#1E293B"), text_color=TEXT_MUTED)
            self.button.configure(
                text="Retry",
                state="normal",
                fg_color=BLUE_BTN,
                hover_color=BLUE_BTN_HOVER,
                text_color=BLUE_BTN_TEXT,
            )

        elif status == DownloadStatus.FETCHING_INFO:
            detail = f"{quality}  •  Connecting & preparing stream…"
            if not self._thumb_loaded:
                self.icon.configure(text="◌", fg_color=BLUE_BG, text_color=BLUE_FG)
            self.button.configure(
                text="Cancel",
                state="normal",
                fg_color=BLUE_BTN,
                hover_color=BLUE_BTN_HOVER,
                text_color=BLUE_BTN_TEXT,
            )

        else:  # QUEUED
            detail = f"{quality}  •  Queued — waiting for available download slot"
            if not self._thumb_loaded:
                self.icon.configure(text="⏳", fg_color=("#F1F5F9", "#1E293B"), text_color=TEXT_MUTED)
            self.button.configure(
                text="Cancel",
                state="normal",
                fg_color=BLUE_BTN,
                hover_color=BLUE_BTN_HOVER,
                text_color=BLUE_BTN_TEXT,
            )

        self.details.configure(text=detail)
        self.progress.set(progress)
