from __future__ import annotations

import threading
from typing import Callable
import customtkinter as ctk
from PIL import Image

from app.playlist import get_remote_image

BLUE = ("#2563EB", "#3B82F6")
BLUE_HOVER = ("#1D4ED8", "#2563EB")
INK = ("#0F172A", "#F8FAFC")
MUTED = ("#64748B", "#94A3B8")
SURFACE = ("#FFFFFF", "#1E293B")
BORDER = ("#E2E8F0", "#334155")
SECONDARY_BTN = ("#EEF2F6", "#26354D")
SECONDARY_BTN_HOVER = ("#E2E8F0", "#334464")


class FolderCard(ctk.CTkFrame):
    """
    Represents the 'All Files' folder tile in the visual catalog grid.
    Features a folder badge, video count, and dual View / Download action buttons.
    """

    def __init__(
        self,
        parent,
        title: str = "All Files",
        subtitle: str = "All channel videos",
        on_view: Callable[[], None] | None = None,
        on_download: Callable[[], None] | None = None,
        icon: str = "📁",
        icon_color=BLUE,
        folder_bg=("#DBEAFE", "#1E3A8A"),
        **kwargs,
    ) -> None:
        super().__init__(
            parent,
            fg_color=SURFACE,
            border_width=1,
            border_color=BORDER,
            corner_radius=12,
            width=175,
            height=215,
            **kwargs,
        )
        self.pack_propagate(False)
        self.grid_propagate(False)

        # Folder graphic container
        folder_box = ctk.CTkFrame(self, fg_color=folder_bg, corner_radius=10, height=95)
        folder_box.pack(fill="x", padx=10, pady=(10, 8))
        folder_box.pack_propagate(False)

        ctk.CTkLabel(
            folder_box,
            text=icon,
            font=ctk.CTkFont(size=38),
            text_color=icon_color,
        ).pack(expand=True)

        # Title & Subtitle
        ctk.CTkLabel(
            self,
            text=title,
            text_color=INK,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 2))

        ctk.CTkLabel(
            self,
            text=subtitle,
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 10))

        # Action Buttons Row
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", side="bottom", padx=10, pady=(0, 10))

        ctk.CTkButton(
            actions,
            text="🔍 View",
            width=70,
            height=28,
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=BLUE,
            command=on_view,
        ).pack(side="left", expand=True, fill="x", padx=(0, 4))

        ctk.CTkButton(
            actions,
            text="⬇ DL",
            width=70,
            height=28,
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            text_color="#FFFFFF",
            command=on_download,
        ).pack(side="right", expand=True, fill="x", padx=(4, 0))


class PlaylistCard(ctk.CTkFrame):
    """
    Represents an individual playlist card with real video thumbnail,
    title, video count badge, and dual View / Download action buttons.
    """

    def __init__(
        self,
        parent,
        playlist_data: dict,
        on_view: Callable[[dict], None] | None = None,
        on_download: Callable[[dict], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            parent,
            fg_color=SURFACE,
            border_width=1,
            border_color=BORDER,
            corner_radius=12,
            width=175,
            height=215,
            **kwargs,
        )
        self.pack_propagate(False)
        self.grid_propagate(False)

        self.playlist_data = playlist_data
        self.on_view = on_view
        self.on_download = on_download

        # Thumbnail Area
        self.thumb_box = ctk.CTkFrame(self, fg_color=("#E2E8F0", "#0F172A"), corner_radius=10, height=95)
        self.thumb_box.pack(fill="x", padx=10, pady=(10, 8))
        self.thumb_box.pack_propagate(False)

        self.thumb_label = ctk.CTkLabel(
            self.thumb_box,
            text="▶",
            font=ctk.CTkFont(size=26),
            text_color=MUTED,
        )
        self.thumb_label.pack(expand=True)

        # Title (cleanly truncated)
        raw_title = playlist_data.get("title", "Untitled Playlist")
        display_title = raw_title if len(raw_title) <= 20 else raw_title[:18] + "…"

        ctk.CTkLabel(
            self,
            text=display_title,
            text_color=INK,
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 2))

        # Item Count
        count = playlist_data.get("item_count")
        if count:
            count_str = f"{count} videos"
        elif playlist_data.get("videos"):
            count_str = f"{len(playlist_data['videos'])} videos"
        else:
            count_str = "Playlist"

        ctk.CTkLabel(
            self,
            text=count_str,
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 10))

        # Action Buttons Row
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", side="bottom", padx=10, pady=(0, 10))

        ctk.CTkButton(
            actions,
            text="🔍 View",
            width=70,
            height=28,
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=BLUE,
            command=lambda: self.on_view(self.playlist_data) if self.on_view else None,
        ).pack(side="left", expand=True, fill="x", padx=(0, 4))

        ctk.CTkButton(
            actions,
            text="⬇ DL",
            width=70,
            height=28,
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            text_color="#FFFFFF",
            command=lambda: self.on_download(self.playlist_data) if self.on_download else None,
        ).pack(side="right", expand=True, fill="x", padx=(4, 0))

        # Asynchronously fetch thumbnail image
        thumb_url = playlist_data.get("thumbnail_url") or playlist_data.get("thumbnail")
        if thumb_url:
            self._load_async_thumbnail(thumb_url)

    def _load_async_thumbnail(self, url: str) -> None:
        def fetch():
            img = get_remote_image(url, size=(155, 95))
            if img:
                def set_img():
                    if not self.winfo_exists():
                        return
                    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(155, 95))
                    self.thumb_label.configure(image=ctk_img, text="")
                self.after(0, set_img)

        threading.Thread(target=fetch, daemon=True).start()


class InstagramPostCard(ctk.CTkFrame):
    """
    Represents an Instagram post or reel tile in IG Auto-save grid.
    Features thumbnail preview and a quick Download button.
    """

    def __init__(
        self,
        parent,
        post_data: dict,
        on_download: Callable[[dict], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            parent,
            fg_color=SURFACE,
            border_width=1,
            border_color=BORDER,
            corner_radius=10,
            width=165,
            height=210,
            **kwargs,
        )
        self.pack_propagate(False)
        self.grid_propagate(False)
        self.post_data = post_data
        self.on_download = on_download

        # Thumbnail box (portrait/square ratio typical for IG)
        self.thumb_box = ctk.CTkFrame(self, fg_color=("#E2E8F0", "#0F172A"), corner_radius=8, height=125)
        self.thumb_box.pack(fill="x", padx=8, pady=(8, 6))
        self.thumb_box.pack_propagate(False)

        self.thumb_label = ctk.CTkLabel(
            self.thumb_box,
            text="📷",
            font=ctk.CTkFont(size=24),
            text_color=MUTED,
        )
        self.thumb_label.pack(expand=True)

        # Type badge (Reel vs Photo)
        url_lower = post_data.get("url", "").lower()
        is_reel = "/reel/" in url_lower or "/reels/" in url_lower
        badge_text = "🎬 Reel" if is_reel else "📷 Photo"
        badge_fg = ("#EDE9FE", "#2E1065") if is_reel else ("#FCE7F3", "#500724")
        badge_text_color = "#7C3AED" if is_reel else "#DB2777"

        badge = ctk.CTkLabel(
            self.thumb_box,
            text=badge_text,
            font=ctk.CTkFont(size=9, weight="bold"),
            fg_color=badge_fg,
            text_color=badge_text_color,
            corner_radius=4,
            width=54,
            height=18,
        )
        badge.place(relx=0.06, rely=0.08)

        # Title / caption
        raw_title = post_data.get("title", "Instagram Post")
        display_title = raw_title if len(raw_title) <= 22 else raw_title[:19] + "..."
        ctk.CTkLabel(
            self,
            text=display_title,
            text_color=INK,
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 4))

        # Download button
        ctk.CTkButton(
            self,
            text="⬇ Download",
            height=28,
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            text_color="#FFFFFF",
            command=lambda: self.on_download(self.post_data) if self.on_download else None,
        ).pack(fill="x", side="bottom", padx=8, pady=(0, 8))

        thumb_url = post_data.get("thumbnail_url") or post_data.get("thumbnail")
        if thumb_url:
            self._load_async_thumbnail(thumb_url)

    def _load_async_thumbnail(self, url: str) -> None:
        def fetch():
            img = get_remote_image(url, size=(145, 120))
            if img:
                def set_img():
                    if not self.winfo_exists():
                        return
                    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(145, 120))
                    self.thumb_label.configure(image=ctk_img, text="")
                self.after(0, set_img)

        threading.Thread(target=fetch, daemon=True).start()

