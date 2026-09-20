from __future__ import annotations

from pathlib import Path
from typing import Callable
import customtkinter as ctk


class DuplicateConfirmationDialog(ctk.CTkToplevel):
    """
    Modal confirmation dialog shown when a video has already been downloaded.
    Matches the dark-blue DeepX Vision Downloader design system.
    Default action is [Cancel].
    """

    def __init__(
        self,
        parent: ctk.CTk,
        title: str,
        creator: str,
        existing_filepath: str,
        on_choice: Callable[[bool], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.on_choice = on_choice
        self.result: bool = False  # False = Cancel, True = Download Again

        self.title("Video Already Downloaded")
        self.geometry("540x360")
        self.minsize(500, 340)
        self.transient(parent)
        self.grab_set()

        # Dark theme background matching DeepX Vision
        self.configure(fg_color="#0D1527")

        # Main Card
        card = ctk.CTkFrame(self, fg_color="#141F36", corner_radius=12, border_width=1, border_color="#223254")
        card.pack(fill="both", expand=True, padx=20, pady=20)

        # Header Title
        header_row = ctk.CTkFrame(card, fg_color="transparent")
        header_row.pack(fill="x", padx=20, pady=(20, 8))

        ctk.CTkLabel(
            header_row,
            text="⚠️  Video Already Downloaded",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color="#F8FAFC",
            anchor="w",
        ).pack(fill="x")

        ctk.CTkLabel(
            card,
            text="This video has already been downloaded to your system.",
            font=ctk.CTkFont(size=12),
            text_color="#94A3B8",
            anchor="w",
        ).pack(fill="x", padx=20, pady=(0, 14))

        # Details Box
        info_box = ctk.CTkFrame(card, fg_color="#0A101D", corner_radius=8, border_width=1, border_color="#1E2C4A")
        info_box.pack(fill="x", padx=20, pady=(0, 14))

        # Title
        t_row = ctk.CTkFrame(info_box, fg_color="transparent")
        t_row.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(t_row, text="Title:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38BDF8", width=80, anchor="w").pack(side="left")
        display_title = title if len(title) <= 52 else title[:50] + "…"
        ctk.CTkLabel(t_row, text=display_title, font=ctk.CTkFont(size=12), text_color="#F8FAFC", anchor="w").pack(side="left", fill="x", expand=True)

        # Creator
        c_row = ctk.CTkFrame(info_box, fg_color="transparent")
        c_row.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(c_row, text="Creator:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38BDF8", width=80, anchor="w").pack(side="left")
        creator_tag = f"@{creator.lstrip('@')}" if creator and creator != "Unknown Creator" else "Unknown Creator"
        ctk.CTkLabel(c_row, text=creator_tag, font=ctk.CTkFont(size=12), text_color="#F8FAFC", anchor="w").pack(side="left", fill="x", expand=True)

        # Existing File
        f_row = ctk.CTkFrame(info_box, fg_color="transparent")
        f_row.pack(fill="x", padx=12, pady=(4, 10))
        ctk.CTkLabel(f_row, text="Existing file:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38BDF8", width=80, anchor="w").pack(side="left")
        clean_path = str(existing_filepath)
        if len(clean_path) > 52:
            clean_path = "…" + clean_path[-49:]
        ctk.CTkLabel(f_row, text=clean_path, font=ctk.CTkFont(size=11), text_color="#94A3B8", anchor="w").pack(side="left", fill="x", expand=True)

        # Prompt question
        ctk.CTkLabel(
            card,
            text="Do you want to download it again?",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#F8FAFC",
            anchor="w",
        ).pack(fill="x", padx=20, pady=(0, 16))

        # Footer Buttons
        btn_bar = ctk.CTkFrame(card, fg_color="transparent")
        btn_bar.pack(fill="x", padx=20, pady=(0, 16))

        # [Cancel] Button is default / safe action
        cancel_btn = ctk.CTkButton(
            btn_bar,
            text="Cancel",
            width=120,
            height=36,
            fg_color="#1E293B",
            hover_color="#29374F",
            text_color="#F8FAFC",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_cancel,
        )
        cancel_btn.pack(side="left")

        # [Download Again] Button
        download_again_btn = ctk.CTkButton(
            btn_bar,
            text="Download Again",
            width=150,
            height=36,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_download_again,
        )
        download_again_btn.pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _on_cancel(self) -> None:
        self.result = False
        if self.on_choice:
            self.on_choice(False)
        self.destroy()

    def _on_download_again(self) -> None:
        self.result = True
        if self.on_choice:
            self.on_choice(True)
        self.destroy()


class BatchDuplicateDialog(ctk.CTkToplevel):
    """
    Intelligent confirmation dialog for multiple duplicates found in a batch or playlist download.
    Provides options:
      1. [Skip Duplicates] (Default / Safe): Queues only new videos.
      2. [Download Duplicates Again]: Queues duplicates with (1), (2) numbering.
      3. [Review]: Selectively check or uncheck individual items.
    """

    def __init__(
        self,
        parent: ctk.CTk,
        duplicate_items: list[dict],
        on_decision: Callable[[str, list[dict]], None],
    ) -> None:
        super().__init__(parent)
        self.duplicate_items = duplicate_items
        self.on_decision = on_decision
        self.chosen_items = list(duplicate_items)

        self.title("Duplicate Videos Detected")
        self.geometry("640x480")
        self.minsize(560, 420)
        self.transient(parent)
        self.grab_set()

        self.configure(fg_color="#0D1527")

        card = ctk.CTkFrame(self, fg_color="#141F36", corner_radius=12, border_width=1, border_color="#223254")
        card.pack(fill="both", expand=True, padx=20, pady=20)

        # Header
        ctk.CTkLabel(
            card,
            text=f"⚠️  {len(duplicate_items)} video(s) have already been downloaded",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#F8FAFC",
            anchor="w",
        ).pack(fill="x", padx=20, pady=(20, 6))

        ctk.CTkLabel(
            card,
            text="The following media already exists in your creator download folders:",
            font=ctk.CTkFont(size=12),
            text_color="#94A3B8",
            anchor="w",
        ).pack(fill="x", padx=20, pady=(0, 12))

        # Scrollable list
        self.scroll_frame = ctk.CTkScrollableFrame(card, fg_color="#0A101D", corner_radius=8)
        self.scroll_frame.pack(fill="both", expand=True, padx=20, pady=(0, 14))

        self.check_vars: list[tuple[dict, ctk.BooleanVar]] = []
        for item in duplicate_items:
            row = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            row.pack(fill="x", pady=4, padx=4)

            c_var = ctk.BooleanVar(value=True)
            self.check_vars.append((item, c_var))

            cb = ctk.CTkCheckBox(
                row,
                text=item.get("title", "Untitled")[:55],
                variable=c_var,
                font=ctk.CTkFont(size=12),
                text_color="#F8FAFC",
                fg_color="#2563EB",
                hover_color="#1D4ED8",
            )
            cb.pack(side="left", fill="x", expand=True)

            creator = item.get("creator") or "Unknown"
            ctk.CTkLabel(
                row,
                text=f"@{creator.lstrip('@')}",
                font=ctk.CTkFont(size=11),
                text_color="#38BDF8",
            ).pack(side="right", padx=6)

        # Action Buttons Bar
        btn_bar = ctk.CTkFrame(card, fg_color="transparent")
        btn_bar.pack(fill="x", padx=20, pady=(0, 16))

        # [Skip Duplicates] - Default / Safe Action
        skip_btn = ctk.CTkButton(
            btn_bar,
            text="Skip Duplicates",
            width=140,
            height=36,
            fg_color="#1E293B",
            hover_color="#29374F",
            text_color="#F8FAFC",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_skip,
        )
        skip_btn.pack(side="left", padx=(0, 10))

        # [Download Duplicates Again]
        download_again_btn = ctk.CTkButton(
            btn_bar,
            text="Download Again",
            width=160,
            height=36,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_download_again,
        )
        download_again_btn.pack(side="right")

        # [Review / Selected Only]
        review_btn = ctk.CTkButton(
            btn_bar,
            text="Download Selected Only",
            width=170,
            height=36,
            fg_color="#0F4C81",
            hover_color="#1360A3",
            text_color="#F8FAFC",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_selected_only,
        )
        review_btn.pack(side="right", padx=(0, 10))

        self.protocol("WM_DELETE_WINDOW", self._on_skip)

    def _on_skip(self) -> None:
        self.on_decision("skip", [])
        self.destroy()

    def _on_download_again(self) -> None:
        self.on_decision("download_all", self.duplicate_items)
        self.destroy()

    def _on_selected_only(self) -> None:
        selected = [item for item, var in self.check_vars if var.get()]
        self.on_decision("download_selected", selected)
        self.destroy()
