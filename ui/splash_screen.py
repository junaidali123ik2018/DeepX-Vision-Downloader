from __future__ import annotations

from pathlib import Path
import time
from typing import Callable
import customtkinter as ctk
from PIL import Image

from app.utils import get_asset_path
from app.version import APP_EDITION, APP_NAME, APP_VERSION


class SplashScreen(ctk.CTkToplevel):
    def __init__(self, on_complete: Callable[[], None]) -> None:
        super().__init__()
        self.on_complete = on_complete

        # Set Window and Taskbar Icon
        try:
            ico_path = get_asset_path("assets/app_icon.ico")
            if ico_path.is_file():
                self.iconbitmap(str(ico_path))
        except Exception:
            pass
        try:
            from PIL import ImageTk
            png_icon = get_asset_path("assets/icon_perfect.png")
            if not png_icon.is_file():
                png_icon = get_asset_path("assets/brand_logo.png")
            if png_icon.is_file():
                self._splash_tk_ico = ImageTk.PhotoImage(Image.open(png_icon))
                self.iconphoto(True, self._splash_tk_ico)
        except Exception:
            pass

        self.overrideredirect(True)
        w, h = 500, 310
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.configure(fg_color="#090D16")
        self.attributes("-topmost", True)

        # Border outline frame
        outer = ctk.CTkFrame(self, corner_radius=16, fg_color="#0F172A", border_width=1, border_color="#1E293B")
        outer.pack(fill="both", expand=True, padx=2, pady=2)

        # Logo or Brand Icon
        logo_path = get_asset_path("assets/brand_logo.png")
        if logo_path.is_file():
            try:
                b_img = Image.open(logo_path)
                ctk_b = ctk.CTkImage(light_image=b_img, dark_image=b_img, size=(120, 76))
                ctk.CTkLabel(outer, text="", image=ctk_b).pack(pady=(28, 6))
            except Exception:
                self._render_fallback_logo(outer)
        else:
            self._render_fallback_logo(outer)

        ctk.CTkLabel(
            outer,
            text=APP_NAME,
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#F8FAFC",
        ).pack(pady=(0, 2))

        ctk.CTkLabel(
            outer,
            text=f"{APP_EDITION}  •  v{APP_VERSION}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38BDF8",
        ).pack(pady=(0, 24))

        # Progress bar
        self.prog_bar = ctk.CTkProgressBar(outer, width=380, height=8, progress_color="#3B82F6", fg_color="#1E293B")
        self.prog_bar.set(0)
        self.prog_bar.pack(pady=(0, 8))

        self.lbl_status = ctk.CTkLabel(
            outer,
            text="Initializing core engines...",
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8",
        )
        self.lbl_status.pack(pady=(0, 16))

        # Sequence of steps
        self._step = 0
        self._steps = [
            (0.20, "Loading core settings and user profiles..."),
            (0.50, "Checking Pro license & hardware lock..."),
            (0.75, "Initializing high-speed multi-thread engine..."),
            (0.95, "Syncing clipboard monitor & platform rules..."),
            (1.00, "Ready!"),
        ]
        self.after(200, self._advance_step)

    def _render_fallback_logo(self, parent) -> None:
        ctk.CTkLabel(
            parent,
            text="DX",
            width=50,
            height=50,
            corner_radius=12,
            fg_color="#2563EB",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(pady=(28, 10))

    def _advance_step(self) -> None:
        if self._step < len(self._steps):
            prog, text = self._steps[self._step]
            self.prog_bar.set(prog)
            self.lbl_status.configure(text=text)
            self._step += 1
            delay = 240 if self._step < len(self._steps) else 350
            self.after(delay, self._advance_step)
        else:
            self.after(100, self._finish)

    def _finish(self) -> None:
        try:
            self.destroy()
        except Exception:
            pass
        if self.on_complete:
            self.on_complete()
