from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Callable
import customtkinter as ctk

from app.settings import AppSettings


MODAL_BG = ("#F8FAFC", "#0C111C")
MODAL_CARD = ("#FFFFFF", "#141D2E")
MODAL_BORDER = ("#E2E8F0", "#212E46")
MODAL_INK = ("#0F172A", "#F8FAFC")
MODAL_MUTED = ("#64748B", "#94A3B8")
MODAL_BTN_SEC = ("#EEF2F6", "#192438")
MODAL_BTN_SEC_HOVER = ("#E2E8F0", "#24334E")

QUALITY_CHOICES = [
    "Best Available",
    "8K (4320p)",
    "4K (2160p)",
    "2K / 1440p",
    "1080p (Full HD)",
    "720p (HD)",
    "480p (SD)",
    "Image / Photo",
]


class DownloadSettingsModal(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        settings: AppSettings,
        on_save: Callable[[AppSettings], None],
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.on_save = on_save

        self.title("Download settings")
        self.geometry("520x460")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        # Dark theme background matching EaseUS
        self.configure(fg_color=MODAL_BG)

        # Container card
        card = ctk.CTkFrame(self, corner_radius=12, fg_color=MODAL_BG)
        card.pack(fill="both", expand=True, padx=24, pady=20)
        card.grid_columnconfigure(1, weight=1)

        # Header Title
        title_row = ctk.CTkFrame(card, fg_color="transparent")
        title_row.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(
            title_row,
            text="Download Settings",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=MODAL_INK,
        ).pack(side="left")

        # Form content
        form = ctk.CTkFrame(card, fg_color=MODAL_CARD, border_width=1, border_color=MODAL_BORDER, corner_radius=10)
        form.pack(fill="both", expand=True, padx=4, pady=4)
        form.grid_columnconfigure(1, weight=1)

        row = 0

        # Auto-update
        ctk.CTkLabel(form, text="Auto-update :", text_color=MODAL_MUTED, font=ctk.CTkFont(size=13)).grid(
            row=row, column=0, sticky="w", padx=16, pady=10
        )
        self.auto_update_var = ctk.StringVar(value=settings.auto_update or "Everyday")
        ctk.CTkOptionMenu(
            form,
            values=["Everyday", "Every week", "Never"],
            variable=self.auto_update_var,
            width=160,
            fg_color=MODAL_BTN_SEC,
            button_color="#3B82F6",
        ).grid(row=row, column=1, sticky="w", padx=16, pady=10)
        row += 1

        # Type, Quality, Video format in 1 row
        type_frame = ctk.CTkFrame(form, fg_color="transparent")
        type_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=16, pady=8)

        ctk.CTkLabel(type_frame, text="Type :", text_color=MODAL_MUTED, font=ctk.CTkFont(size=13)).pack(side="left")
        self.type_var = ctk.StringVar(value=settings.media_type or "Video")
        ctk.CTkOptionMenu(
            type_frame,
            values=["Video", "Audio", "Image"],
            variable=self.type_var,
            width=90,
            fg_color=MODAL_BTN_SEC,
            button_color="#3B82F6",
        ).pack(side="left", padx=(8, 14))

        ctk.CTkLabel(type_frame, text="Quality :", text_color=MODAL_MUTED, font=ctk.CTkFont(size=13)).pack(side="left")
        self.quality_var = ctk.StringVar(value=settings.default_quality or "Best Available")
        ctk.CTkOptionMenu(
            type_frame,
            values=QUALITY_CHOICES,
            variable=self.quality_var,
            width=130,
            fg_color=MODAL_BTN_SEC,
            button_color="#3B82F6",
        ).pack(side="left", padx=(8, 14))

        ctk.CTkLabel(type_frame, text="Format :", text_color=MODAL_MUTED, font=ctk.CTkFont(size=13)).pack(side="left")
        self.format_var = ctk.StringVar(value=settings.video_format or "Auto")
        ctk.CTkOptionMenu(
            type_frame,
            values=["Auto", "MP4", "MKV", "MP3", "WAV"],
            variable=self.format_var,
            width=80,
            fg_color=MODAL_BTN_SEC,
            button_color="#3B82F6",
        ).pack(side="left", padx=(8, 0))
        row += 1

        # Download Thumbnail & Subtitles Language
        opt_frame = ctk.CTkFrame(form, fg_color="transparent")
        opt_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=16, pady=8)

        self.thumb_var = ctk.BooleanVar(value=settings.download_thumbnail)
        ctk.CTkCheckBox(
            opt_frame,
            text="Download Thumbnail",
            variable=self.thumb_var,
            text_color=MODAL_INK,
            fg_color="#3B82F6",
            hover_color="#2563EB",
        ).pack(side="left")

        ctk.CTkLabel(opt_frame, text="Subtitles Language :", text_color=MODAL_MUTED, font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(30, 8)
        )
        self.sub_var = ctk.StringVar(value=settings.subtitle_language or "Auto")
        ctk.CTkOptionMenu(
            opt_frame,
            values=["Auto", "English", "Spanish", "Urdu", "Hindi", "None"],
            variable=self.sub_var,
            width=100,
            fg_color=MODAL_BTN_SEC,
            button_color="#3B82F6",
        ).pack(side="left")
        row += 1

        # Save to
        save_frame = ctk.CTkFrame(form, fg_color="transparent")
        save_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=16, pady=12)

        ctk.CTkLabel(save_frame, text="Save to :", text_color=MODAL_MUTED, font=ctk.CTkFont(size=13)).pack(side="left")
        self.save_var = ctk.StringVar(value=str(settings.resolved_download_folder()))
        self.save_entry = ctk.CTkEntry(
            save_frame,
            textvariable=self.save_var,
            fg_color=MODAL_CARD,
            border_color=MODAL_BORDER,
            text_color=MODAL_INK,
            height=32,
        )
        self.save_entry.pack(side="left", fill="x", expand=True, padx=8)

        ctk.CTkButton(
            save_frame,
            text="📁",
            width=36,
            height=32,
            fg_color=MODAL_BTN_SEC,
            hover_color="#3B82F6",
            command=self._browse_folder,
        ).pack(side="right")
        row += 1

        # Bottom buttons: Cancel and Confirm
        btn_bar = ctk.CTkFrame(card, fg_color="transparent")
        btn_bar.pack(fill="x", pady=(18, 0))

        ctk.CTkButton(
            btn_bar,
            text="Cancel",
            width=110,
            height=36,
            corner_radius=8,
            fg_color=MODAL_BTN_SEC,
            hover_color="#334155",
            text_color=MODAL_INK,
            command=self.destroy,
        ).pack(side="left", padx=(100, 16))

        ctk.CTkButton(
            btn_bar,
            text="Confirm",
            width=120,
            height=36,
            corner_radius=8,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            text_color="#FFFFFF",
            font=ctk.CTkFont(weight="bold"),
            command=self._confirm,
        ).pack(side="left")

    def _browse_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.save_var.get())
        if chosen:
            self.save_var.set(chosen)

    def _confirm(self) -> None:
        self.settings.auto_update = self.auto_update_var.get()
        self.settings.media_type = self.type_var.get()
        self.settings.default_quality = self.quality_var.get()
        self.settings.video_format = self.format_var.get()
        self.settings.download_thumbnail = self.thumb_var.get()
        self.settings.subtitle_language = self.sub_var.get()
        self.settings.download_folder = self.save_var.get().strip()
        self.on_save(self.settings)
        self.destroy()
