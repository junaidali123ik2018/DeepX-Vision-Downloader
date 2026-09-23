from __future__ import annotations

import os
from pathlib import Path
import subprocess

import customtkinter as ctk
from PIL import Image

from app.models import DownloadStatus, DownloadTask
from app.utils import format_bytes, format_eta, format_speed

ITEM_SURFACE = ("#FFFFFF", "#1E2738")
ITEM_BORDER = ("#E2E8F0", "#2D3B52")
TEXT_PRIMARY = ("#18233B", "#F3F6FF")
TEXT_MUTED = ("#71809B", "#A0AEC0")

BLUE_BG = ("#E8F0FF", "#1A2B4C")
BLUE_FG = ("#2563EB", "#60A5FA")
BLUE_BTN = ("#EDF2FF", "#223354")
BLUE_BTN_HOVER = ("#DDE8FF", "#2C426E")
BLUE_BTN_TEXT = ("#2563EB", "#60A5FA")

PAUSE_BG = ("#FFF8E6", "#3D2E14")
PAUSE_FG = ("#D97706", "#FBBF24")
PAUSE_BTN = ("#FFF8E6", "#3D2E14")
PAUSE_BTN_HOVER = ("#FEF08A", "#533E1A")
PAUSE_BTN_TEXT = ("#B45309", "#FBBF24")

DONE_BG = ("#ECFDF5", "#133527")
DONE_FG = ("#16A34A", "#4ADE80")

FOLDER_BTN = ("#EEF2FF", "#1E293B")
FOLDER_BTN_HOVER = ("#E0E7FF", "#2D3B52")
FOLDER_BTN_TEXT = ("#2563EB", "#60A5FA")

DANGER_BG = ("#FEF2F2", "#3E1C1F")
DANGER_FG = ("#DC2626", "#F87171")
DANGER_BTN = ("#FEE2E2", "#3E1C1F")
DANGER_BTN_HOVER = ("#FECACA", "#552428")
DANGER_BTN_TEXT = ("#DC2626", "#F87171")


class DownloadItem(ctk.CTkFrame):
    """A calm, dashboard-style row for one queued download with thumbnail preview."""

    def __init__(self, master, task: DownloadTask, on_cancel, on_retry, on_pause, on_resume, on_context) -> None:
        super().__init__(master, corner_radius=12, fg_color=ITEM_SURFACE, border_width=1, border_color=ITEM_BORDER)
        self.task = task
        self.on_cancel, self.on_retry = on_cancel, on_retry
        self.on_pause, self.on_resume, self.on_context = on_pause, on_resume, on_context
        self._thumb_loaded = False

        # Thumbnail / Icon container
        self.icon = ctk.CTkLabel(
            self,
            text="↓",
            width=76,
            height=50,
            corner_radius=8,
            fg_color=BLUE_BG,
            text_color=BLUE_FG,
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        self.icon.grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=11)

        # Title label
        self.name = ctk.CTkLabel(
            self,
            text="Analyzing video…",
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        )
        self.name.grid(row=0, column=1, sticky="ew", pady=(10, 1))

        # Details / telemetry label
        self.details = ctk.CTkLabel(
            self,
            text=f"{task.quality}  •  Waiting for an available slot",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        )
        self.details.grid(row=1, column=1, sticky="ew", pady=(0, 10))

        # Progress bar
        self.progress = ctk.CTkProgressBar(self, height=6, corner_radius=6, progress_color="#2563EB", fg_color=("#E2E8F0", "#2D3B52"))
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
            font=ctk.CTkFont(size=12, weight="bold"),
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

        self._try_load_thumbnail()
        self.name.configure(text=filename)

        if status == DownloadStatus.DOWNLOADING:
            remaining = (total - downloaded) / speed if total and speed else None
            detail = f"{quality}  •  {format_bytes(downloaded)} / {format_bytes(total)}  •  {format_speed(speed)}  •  {format_eta(remaining)} left"
            if not self._thumb_loaded:
                self.icon.configure(text="↓", fg_color=BLUE_BG, text_color=BLUE_FG)
            self.button.configure(text="Pause", state="normal", fg_color=BLUE_BTN, hover_color=BLUE_BTN_HOVER, text_color=BLUE_BTN_TEXT)

        elif status == DownloadStatus.PAUSED:
            detail = f"{quality}  •  Paused • will continue when resumed"
            if not self._thumb_loaded:
                self.icon.configure(text="Ⅱ", fg_color=PAUSE_BG, text_color=PAUSE_FG)
            self.button.configure(text="Resume", state="normal", fg_color=PAUSE_BTN, hover_color=PAUSE_BTN_HOVER, text_color=PAUSE_BTN_TEXT)

        elif status == DownloadStatus.COMPLETED:
            detail, progress = f"{quality}  •  Completed  •  {format_bytes(downloaded)}", 1.0
            if not self._thumb_loaded:
                self.icon.configure(text="✓", fg_color=DONE_BG, text_color=DONE_FG)
            self.button.configure(text="📂 Open", state="normal", fg_color=FOLDER_BTN, hover_color=FOLDER_BTN_HOVER, text_color=FOLDER_BTN_TEXT)

        elif status == DownloadStatus.FAILED:
            detail = f"{quality}  •  Couldn’t download: {error or 'Unknown error'}"
            if not self._thumb_loaded:
                self.icon.configure(text="!", fg_color=DANGER_BG, text_color=DANGER_FG)
            self.button.configure(text="Retry", state="normal", fg_color=DANGER_BTN, hover_color=DANGER_BTN_HOVER, text_color=DANGER_BTN_TEXT)

        elif status == DownloadStatus.CANCELLED:
            detail = f"{quality}  •  Cancelled"
            if not self._thumb_loaded:
                self.icon.configure(text="—", fg_color=("#F1F5F9", "#1E293B"), text_color=TEXT_MUTED)
            self.button.configure(text="Retry", state="normal", fg_color=BLUE_BTN, hover_color=BLUE_BTN_HOVER, text_color=BLUE_BTN_TEXT)

        elif status == DownloadStatus.FETCHING_INFO:
            detail = f"{quality}  •  Analyzing video metadata…"
            if not self._thumb_loaded:
                self.icon.configure(text="…", fg_color=BLUE_BG, text_color=BLUE_FG)
            self.button.configure(text="Cancel", state="normal", fg_color=BLUE_BTN, hover_color=BLUE_BTN_HOVER, text_color=BLUE_BTN_TEXT)

        else:  # QUEUED
            detail = f"{quality}  •  Queued • waiting for an available download slot"
            if not self._thumb_loaded:
                self.icon.configure(text="…", fg_color=BLUE_BG, text_color=BLUE_FG)
            self.button.configure(text="Cancel", state="normal", fg_color=BLUE_BTN, hover_color=BLUE_BTN_HOVER, text_color=BLUE_BTN_TEXT)

        self.details.configure(text=detail)
        self.progress.set(progress)
