from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog
from typing import Callable, Optional
import customtkinter as ctk

# DeepX Vision Dark Modern Palette
MODAL_BG = ("#F8FAFC", "#0C111C")
MODAL_CARD = ("#FFFFFF", "#141D2E")
MODAL_BORDER = ("#E2E8F0", "#212E46")
MODAL_INK = ("#0F172A", "#F8FAFC")
MODAL_MUTED = ("#64748B", "#94A3B8")
PRIMARY_BLUE = "#2563EB"
PRIMARY_BLUE_HOVER = "#1D4ED8"
SECONDARY_BTN = ("#EEF2F6", "#192438")
SECONDARY_BTN_HOVER = ("#E2E8F0", "#24334E")

QUALITY_OPTIONS = [
    "Best Available",
    "1080p (Full HD)",
    "720p (HD)",
    "480p (SD)",
    "Audio (.mp3)",
]


class DownloadFileInfoModal(ctk.CTkToplevel):
    """
    IDM / Awesome Downloader-style 'Download File Info' modal.
    Prompts user with File Name, URL, Quality, and Destination before starting download.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        url: str,
        initial_title: str = "",
        initial_quality: str = "Best Available",
        initial_directory: str = "",
        on_start: Optional[Callable[[str, str, str, str], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.url = url.strip()
        self.on_start = on_start
        self._confirmed = False

        # Compute clean initial filename
        clean_title = (initial_title or "").strip()
        if not clean_title:
            try:
                import urllib.parse
                clean_title = Path(urllib.parse.urlparse(self.url).path).name
            except Exception:
                clean_title = ""
        if not clean_title:
            clean_title = "download_video.mp4"

        self.title("DeepX Vision — Download File Info")
        self.geometry("560x420")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.configure(fg_color=MODAL_BG)

        # Center modal on screen / parent
        try:
            self.update_idletasks()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            w = 560
            h = 420
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

        # Outer card container
        card = ctk.CTkFrame(self, corner_radius=12, fg_color=MODAL_BG)
        card.pack(fill="both", expand=True, padx=20, pady=18)

        # Header with icon and title
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", pady=(0, 14))

        badge = ctk.CTkLabel(
            header,
            text="⬇",
            width=36,
            height=36,
            corner_radius=8,
            fg_color=("#EFF6FF", "#13233C"),
            text_color=PRIMARY_BLUE,
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
        )
        badge.pack(side="left", padx=(0, 10))

        header_titles = ctk.CTkFrame(header, fg_color="transparent")
        header_titles.pack(side="left", fill="both")

        ctk.CTkLabel(
            header_titles,
            text="Download File Info",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color=MODAL_INK,
            anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            header_titles,
            text="Review video details and choose destination to start downloading",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=MODAL_MUTED,
            anchor="w",
        ).pack(anchor="w")

        # Form Card
        form = ctk.CTkFrame(card, fg_color=MODAL_CARD, border_width=1, border_color=MODAL_BORDER, corner_radius=10)
        form.pack(fill="both", expand=True, padx=2, pady=(0, 14))
        form.grid_columnconfigure(1, weight=1)

        # Row 0: File Name
        ctk.CTkLabel(
            form,
            text="File Name:",
            text_color=MODAL_MUTED,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))

        self.filename_entry = ctk.CTkEntry(
            form,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            height=32,
        )
        self.filename_entry.grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=(16, 8))
        self.filename_entry.insert(0, clean_title)

        # Row 1: URL / Source
        ctk.CTkLabel(
            form,
            text="URL:",
            text_color=MODAL_MUTED,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        ).grid(row=1, column=0, sticky="w", padx=16, pady=8)

        self.url_entry = ctk.CTkEntry(
            form,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            height=30,
            fg_color=("#F1F5F9", "#0B101B"),
            text_color=MODAL_MUTED,
        )
        self.url_entry.grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=8)
        self.url_entry.insert(0, self.url)
        self.url_entry.configure(state="readonly")

        # Row 2: Quality / Format
        ctk.CTkLabel(
            form,
            text="Quality / Format:",
            text_color=MODAL_MUTED,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        ).grid(row=2, column=0, sticky="w", padx=16, pady=8)

        matched_quality = "Best Available"
        for opt in QUALITY_OPTIONS:
            if initial_quality and (initial_quality.lower() in opt.lower() or opt.lower() in initial_quality.lower()):
                matched_quality = opt
                break

        self.quality_var = ctk.StringVar(value=matched_quality)
        self.quality_menu = ctk.CTkOptionMenu(
            form,
            variable=self.quality_var,
            values=QUALITY_OPTIONS,
            height=32,
            fg_color=("#EFF6FF", "#13233C"),
            button_color=PRIMARY_BLUE,
            button_hover_color=PRIMARY_BLUE_HOVER,
            text_color=MODAL_INK,
            font=ctk.CTkFont(family="Segoe UI", size=12),
        )
        self.quality_menu.grid(row=2, column=1, sticky="w", padx=(0, 16), pady=8)

        # Row 3: Save To (Folder + Browse)
        ctk.CTkLabel(
            form,
            text="Save To:",
            text_color=MODAL_MUTED,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        ).grid(row=3, column=0, sticky="w", padx=16, pady=(8, 16))

        save_row = ctk.CTkFrame(form, fg_color="transparent")
        save_row.grid(row=3, column=1, sticky="ew", padx=(0, 16), pady=(8, 16))
        save_row.grid_columnconfigure(0, weight=1)

        default_dest = initial_directory or str(Path.home() / "Downloads")
        self.dest_entry = ctk.CTkEntry(
            save_row,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            height=32,
        )
        self.dest_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.dest_entry.insert(0, default_dest)

        browse_btn = ctk.CTkButton(
            save_row,
            text="Browse…",
            width=80,
            height=32,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=MODAL_INK,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            command=self._browse_destination,
        )
        browse_btn.grid(row=0, column=1)

        # Footer Actions
        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.pack(fill="x", pady=(4, 0))

        cancel_btn = ctk.CTkButton(
            footer,
            text="Cancel",
            width=90,
            height=36,
            corner_radius=8,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=MODAL_MUTED,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            command=self._cancel,
        )
        cancel_btn.pack(side="right", padx=(8, 0))

        start_btn = ctk.CTkButton(
            footer,
            text="⬇  Start Download",
            width=140,
            height=36,
            corner_radius=8,
            fg_color=PRIMARY_BLUE,
            hover_color=PRIMARY_BLUE_HOVER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            command=self._start_download,
        )
        start_btn.pack(side="right")

        # Focus filename and bind Enter key to start download
        self.filename_entry.focus()
        self.bind("<Return>", lambda e: self._start_download())
        self.bind("<Escape>", lambda e: self._cancel())

    def _browse_destination(self) -> None:
        initial = self.dest_entry.get().strip() or str(Path.home() / "Downloads")
        chosen = filedialog.askdirectory(parent=self, initialdir=initial, title="Choose Download Folder")
        if chosen:
            self.dest_entry.delete(0, "end")
            self.dest_entry.insert(0, chosen)

    def _start_download(self) -> None:
        self._confirmed = True
        filename = self.filename_entry.get().strip()
        quality = self.quality_var.get()
        destination = self.dest_entry.get().strip()
        self.destroy()

        if self.on_start:
            self.on_start(self.url, filename, quality, destination)

    def _cancel(self) -> None:
        self.destroy()
