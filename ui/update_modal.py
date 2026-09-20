from __future__ import annotations

import os
from pathlib import Path
import threading
from tkinter import messagebox
import customtkinter as ctk

from app.updater import UpdateManifest, apply_update_and_restart, download_update_installer
from app.version import APP_VERSION


class UpdateModal(ctk.CTkToplevel):
    def __init__(self, parent: ctk.CTk, manifest: UpdateManifest) -> None:
        super().__init__(parent)
        self.manifest = manifest
        self.title("Software Update Available - DeepX Vision Pro")
        self.geometry("540x510")
        self.resizable(False, False)
        self.configure(fg_color="#0F172A")
        self.transient(parent)
        self.grab_set()

        self._download_thread: threading.Thread | None = None
        self._cancel_flag = threading.Event()
        self._downloaded_file: Path | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        # Header
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=24, pady=(20, 8))

        ctk.CTkLabel(
            head,
            text="🚀 Software Update Available",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#38BDF8",
        ).pack(anchor="w")

        v_row = ctk.CTkFrame(head, fg_color="transparent")
        v_row.pack(anchor="w", pady=(4, 0))

        ctk.CTkLabel(
            v_row,
            text=f"Current: v{APP_VERSION}  ➔  ",
            font=ctk.CTkFont(size=12),
            text_color="#94A3B8",
        ).pack(side="left")

        new_badge = ctk.CTkFrame(v_row, fg_color="#0284C7", corner_radius=6)
        new_badge.pack(side="left")
        ctk.CTkLabel(
            new_badge,
            text=f"Latest: v{self.manifest.version}",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#FFFFFF",
        ).pack(padx=8, pady=2)

        # Changelog Card
        card = ctk.CTkFrame(self, corner_radius=12, fg_color="#1E293B", border_width=1, border_color="#334155")
        card.pack(fill="both", expand=True, padx=24, pady=10)

        ctk.CTkLabel(
            card,
            text="What's New in this Release:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#F8FAFC",
        ).pack(anchor="w", padx=16, pady=(12, 6))

        scroll = ctk.CTkScrollableFrame(card, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        if self.manifest.changelog:
            for item in self.manifest.changelog:
                i_row = ctk.CTkFrame(scroll, fg_color="transparent")
                i_row.pack(fill="x", anchor="w", pady=3)
                ctk.CTkLabel(i_row, text="•", font=ctk.CTkFont(size=14, weight="bold"), text_color="#38BDF8").pack(side="left", padx=(4, 8), anchor="n")
                ctk.CTkLabel(i_row, text=item, font=ctk.CTkFont(size=12), text_color="#CBD5E1", wraplength=410, justify="left").pack(side="left")
        else:
            ctk.CTkLabel(scroll, text="Performance enhancements and bug fixes.", text_color="#CBD5E1").pack(anchor="w", padx=8)

        # Progress Area
        self.prog_container = ctk.CTkFrame(self, fg_color="transparent")
        self.prog_container.pack(fill="x", padx=24, pady=(0, 10))

        self.prog_bar = ctk.CTkProgressBar(self.prog_container, height=10, progress_color="#3B82F6")
        self.prog_bar.set(0)
        self.prog_bar.pack(fill="x", pady=(0, 4))
        self.prog_bar.pack_forget()

        self.lbl_progress = ctk.CTkLabel(self.prog_container, text="", font=ctk.CTkFont(size=11), text_color="#94A3B8")
        self.lbl_progress.pack(anchor="w")
        self.lbl_progress.pack_forget()

        # Footer Actions
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=24, pady=(0, 20))

        self.btn_action = ctk.CTkButton(
            footer,
            text="⚡ Download & Install Update",
            height=38,
            corner_radius=8,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_action_clicked,
        )
        self.btn_action.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_later = ctk.CTkButton(
            footer,
            text="Remind Me Later",
            width=120,
            height=38,
            corner_radius=8,
            fg_color="#334155",
            hover_color="#475569",
            text_color="#F8FAFC",
            command=self._on_close,
        )
        self.btn_later.pack(side="right")

    def _on_action_clicked(self) -> None:
        if self._downloaded_file and self._downloaded_file.is_file():
            # Ready to apply
            try:
                apply_update_and_restart(self._downloaded_file)
            except Exception as e:
                messagebox.showerror("Update Error", f"Could not launch installer: {e}")
            return

        # Start download
        if not self.manifest.download_url:
            messagebox.showwarning("Download Error", "No download link provided in update manifest.")
            return

        self.btn_action.configure(state="disabled", text="Downloading Update...")
        self.btn_later.configure(text="Cancel Download")
        self.prog_bar.pack(fill="x", pady=(0, 4))
        self.lbl_progress.pack(anchor="w")
        self.lbl_progress.configure(text="Connecting to download server...")

        self._download_thread = threading.Thread(target=self._worker_download, daemon=True)
        self._download_thread.start()

    def _worker_download(self) -> None:
        def on_prog(done: int, total: int, pct: float, spd: str):
            mb_done = done / (1024 * 1024)
            mb_tot = total / (1024 * 1024)
            self.after(0, lambda: self._update_progress_ui(pct, mb_done, mb_tot, spd))

        try:
            dest = download_update_installer(
                self.manifest.download_url,
                on_progress=on_prog,
                cancel_flag=self._cancel_flag,
            )
            self._downloaded_file = dest
            self.after(0, self._on_download_complete)
        except InterruptedError:
            self.after(0, lambda: self.lbl_progress.configure(text="Download cancelled."))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Download Error", f"Download failed:\n{e}"))
            self.after(0, self._reset_buttons)

    def _update_progress_ui(self, pct: float, mb_done: float, mb_tot: float, spd: str) -> None:
        try:
            self.prog_bar.set(pct / 100.0)
            self.lbl_progress.configure(
                text=f"Downloading: {mb_done:.1f} MB / {mb_tot:.1f} MB ({spd}) • {pct:.0f}%"
            )
        except Exception:
            pass

    def _on_download_complete(self) -> None:
        self.prog_bar.set(1.0)
        self.lbl_progress.configure(text="✓ Update downloaded successfully! Ready to install.", text_color="#34D399")
        self.btn_action.configure(
            state="normal",
            text="🚀 Restart & Apply Update Now",
            fg_color="#10B981",
            hover_color="#059669",
        )
        self.btn_later.configure(text="Close")

    def _reset_buttons(self) -> None:
        self.btn_action.configure(state="normal", text="⚡ Download & Install Update")
        self.btn_later.configure(text="Remind Me Later")

    def _on_close(self) -> None:
        if self._download_thread and self._download_thread.is_alive():
            self._cancel_flag.set()
        self.destroy()
