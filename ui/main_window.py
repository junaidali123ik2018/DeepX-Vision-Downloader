from __future__ import annotations

import os
from pathlib import Path
import re
import threading
import time
from tkinter import Canvas, Menu, TclError, filedialog, messagebox
from urllib.parse import urlparse

import customtkinter as ctk
from PIL import Image

# Globally enforce "Times New Roman" font family across all CustomTkinter components
if not getattr(ctk.CTkFont, "_is_times_new_roman_patched", False):
    _orig_ctkfont_init = ctk.CTkFont.__init__

    def _times_new_roman_font_init(self, *args, **kwargs):
        kwargs["family"] = "Times New Roman"
        return _orig_ctkfont_init(self, *args, **kwargs)

    ctk.CTkFont.__init__ = _times_new_roman_font_init
    ctk.CTkFont._is_times_new_roman_patched = True

try:
    from customtkinter import ThemeManager
    ThemeManager.theme["CTkFont"]["family"] = "Times New Roman"
except Exception:
    pass


from app.converter import convert_media
from app.downloader import DownloadManager
from app.models import DownloadStatus, DownloadTask
from app.playlist import (
    fetch_channel_all_playlists,
    fetch_channel_catalog,
    fetch_instagram_catalog,
    fetch_playlist_info,
    get_remote_image,
    is_playlist_or_channel,
    normalize_creator_input,
)
from app.settings import AppSettings, SettingsStore
from app.utils import format_bytes, format_eta, parse_speed_limit, get_asset_path
from ui.channel_card import FolderCard, InstagramPostCard, PlaylistCard
from ui.download_item import DownloadItem
from ui.download_settings_modal import DownloadSettingsModal
from ui.settings_dialog import SettingsDialog
from ui.video_grid_modal import VideoGridModal
from ui.browser_window import BrowserIPCServer, BrowserManager, detect_platform_from_url, get_cookie_file_path
from app.image_downloader import extract_media_images, is_direct_image_url
from app.path_manager import (
    extract_media_identity,
    get_creator_folder,
    get_next_duplicate_filename,
    sanitize_creator_name,
    sanitize_filename,
)
from app.download_history import DownloadRecord, history_store
from ui.duplicate_dialog import DuplicateConfirmationDialog, BatchDuplicateDialog
from app.license import license_mgr
from app.updater import check_for_updates, update_core_engine_ytdlp
from app.version import APP_NAME, APP_EDITION, APP_VERSION
from app.clipboard_monitor import ClipboardMonitor
from app.telemetry import telemetry_service
from ui.pricing_modal import PricingModal
from ui.license_dialog import LicenseDialog
from ui.update_modal import UpdateModal
import webbrowser

# Unified Color Palette with Consistent Dark & Light Mode Contrast
BLUE = ("#2563EB", "#3B82F6")
BLUE_HOVER = ("#1D4ED8", "#2563EB")
SIDEBAR = ("#1E40AF", "#0F172A")
INK = ("#0F172A", "#F8FAFC")
MUTED = ("#64748B", "#94A3B8")
SURFACE = ("#FFFFFF", "#1E293B")
BACKGROUND = ("#F8FAFC", "#0B0F19")
BORDER = ("#E2E8F0", "#334155")
SECONDARY_BTN = ("#EEF2F6", "#26354D")
SECONDARY_BTN_HOVER = ("#E2E8F0", "#334464")
DANGER_BTN = ("#FEE2E2", "#451A1A")
DANGER_BTN_HOVER = ("#FECACA", "#5F2222")
DANGER_TEXT = ("#DC2626", "#F87171")

QUALITY_OPTIONS = [
    "Best Available",
    "8K (4320p)",
    "4K (2160p)",
    "2K / 1440p",
    "1080p (Full HD)",
    "720p (HD)",
    "480p (SD)",
    "360p",
    "240p",
    "144p",
    "Audio MP3",
    "Audio M4A",
    "Audio WAV",
    "Audio AAC",
    "Audio FLAC",
    "Image / Photo",
]


class HQVideoDownloaderApp(ctk.CTk):
    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        ctk.set_appearance_mode(settings.appearance_mode.lower())
        ctk.set_default_color_theme("blue")
        try:
            from customtkinter import ThemeManager
            ThemeManager.theme["CTkFont"]["family"] = "Times New Roman"
        except Exception:
            pass

        import tkinter.font as tkfont
        for font_name in (
            "TkDefaultFont",
            "TkTextFont",
            "TkFixedFont",
            "TkMenuFont",
            "TkHeadingFont",
            "TkCaptionFont",
            "TkSmallCaptionFont",
            "TkIconFont",
            "TkTooltipFont",
        ):
            try:
                tkfont.nametofont(font_name).configure(family="Times New Roman")
            except Exception:
                pass

        try:
            self.option_add("*Font", "{Times New Roman} 11")
        except Exception:
            pass

        self.settings, self.store = settings, SettingsStore()
        self.tasks: dict[str, DownloadTask] = {}
        self.items: dict[str, DownloadItem] = {}
        self.manager = DownloadManager(settings.simultaneous_downloads, lambda _: None)
        self.title("DeepX Vision Downloader")
        self.geometry("1160x760")
        self.minsize(960, 620)
        self.configure(fg_color=BACKGROUND)
        self.protocol("WM_DELETE_WINDOW", self._close)
        icon_path = get_asset_path("assets/app_icon.ico")
        if icon_path.is_file():
            try:
                self.iconbitmap(str(icon_path))
            except Exception:
                pass

        # Set taskbar icon via iconphoto
        try:
            from PIL import ImageTk
            png_icon = get_asset_path("assets/icon_perfect.png")
            if not png_icon.is_file():
                png_icon = get_asset_path("assets/brand_logo.png")
            if png_icon.is_file():
                self._taskbar_icon_photo = ImageTk.PhotoImage(Image.open(png_icon))
                self.iconphoto(True, self._taskbar_icon_photo)
        except Exception:
            pass

        self._refresh_job: str | None = None
        self.ipc_server = BrowserIPCServer(
            self._on_browser_download_received,
            self._on_browser_cookies_synced,
            self._on_browser_focus_requested,
        )
        try:
            self.ipc_server.start()
        except Exception as e:
            print(f"[DeepX Vision] IPC server start error: {e}", flush=True)

        self._build_shell()
        self.show_page("dashboard")
        self._schedule_refresh()

        # Clipboard auto-detector
        self.clipboard_monitor = ClipboardMonitor(self, on_url_detected=self._on_clipboard_url_detected)
        if getattr(self.settings, "monitor_clipboard", True):
            self.clipboard_monitor.start()

        # Background update check (3.5s after launch)
        if getattr(self.settings, "auto_update", "Everyday") != "Disabled":
            self.after(3500, self._check_updates_background)

        # Startup heartbeat & device ban check
        self.after(1500, self._init_telemetry_and_ban_check)

    def _get_icon(self, filename: str, size: tuple[int, int] = (18, 18)) -> ctk.CTkImage | None:
        if not hasattr(self, "_icons_cache"):
            self._icons_cache = {}
        key = (filename, size)
        if key in self._icons_cache:
            return self._icons_cache[key]
        p = get_asset_path(f"assets/{filename}")
        if p.is_file():
            try:
                img = Image.open(p).convert("RGBA")
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=size)
                self._icons_cache[key] = ctk_img
                return ctk_img
            except Exception:
                pass
        return None

    def _build_shell(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Left Sidebar
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0, fg_color=SIDEBAR)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar.grid_propagate(False)

        brand_path = get_asset_path("assets/brand_logo.png")
        if brand_path.is_file():
            try:
                b_img = Image.open(brand_path)
                ctk_b = ctk.CTkImage(light_image=b_img, dark_image=b_img, size=(144, 93))
                ctk.CTkLabel(self.sidebar, text="", image=ctk_b).pack(anchor="center", padx=10, pady=(16, 4))
            except Exception:
                ctk.CTkLabel(
                    self.sidebar,
                    text="⚡ DeepX Vision",
                    corner_radius=8,
                    fg_color="#1E3A8A",
                    text_color="#F8FAFC",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    padx=10,
                    pady=6,
                ).pack(anchor="center", padx=16, pady=(16, 6))
        else:
            ctk.CTkLabel(
                self.sidebar,
                text="⚡ DeepX Vision",
                corner_radius=8,
                fg_color="#1E3A8A",
                text_color="#F8FAFC",
                font=ctk.CTkFont(size=14, weight="bold"),
                padx=10,
                pady=6,
            ).pack(anchor="center", padx=16, pady=(16, 6))

        ctk.CTkLabel(
            self.sidebar,
            text="👑 Pro Edition • by Junaid Ali",
            text_color="#38BDF8",
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="center", padx=10, pady=(0, 12))

        self.nav_buttons = {}

        # 1. Primary Dashboard Nav Item
        dash_icon = self._get_icon("nav_dashboard.png", (18, 18))
        btn_dash = ctk.CTkButton(
            self.sidebar,
            image=dash_icon,
            compound="left",
            text="  Dashboard",
            anchor="w",
            height=38,
            corner_radius=8,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self.show_page("dashboard"),
        )
        btn_dash.pack(fill="x", padx=10, pady=(0, 6))
        self.nav_buttons["dashboard"] = btn_dash

        # Download Section
        ctk.CTkLabel(
            self.sidebar,
            text="Download",
            text_color="#64748B",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=16, pady=(4, 2))

        download_items = (
            ("downloads", "nav_downloads.png", "  General"),
            ("image_downloader", "nav_image.png", "  Image Downloader"),
            ("channel_hub", "plat_youtube.png", "  YTB Auto-save"),
            ("tiktok_hub", "plat_tiktok.png", "  TikTok Auto-save"),
            ("ig_hub", "plat_instagram.png", "  IG Auto-save"),
            ("x_hub", "plat_x.png", "  X Auto-save"),
            ("sites", "nav_sites.png", "  More Platforms"),
        )
        for key, icon_file, label in download_items:
            nav_img = self._get_icon(icon_file, (18, 18))
            button = ctk.CTkButton(
                self.sidebar,
                image=nav_img,
                compound="left",
                text=label,
                anchor="w",
                height=36,
                corner_radius=8,
                fg_color="transparent",
                hover_color="#2563EB",
                text_color="#FFFFFF",
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda page=key: self.show_page(page),
            )
            button.pack(fill="x", padx=10, pady=1)
            self.nav_buttons[key] = button

        # Convert Section
        ctk.CTkLabel(
            self.sidebar,
            text="Convert",
            text_color="#64748B",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=16, pady=(10, 2))

        convert_items = (
            ("converter", "nav_convert.png", "  Video to MP3"),
        )
        for key, icon_file, label in convert_items:
            nav_img = self._get_icon(icon_file, (18, 18))
            button = ctk.CTkButton(
                self.sidebar,
                image=nav_img,
                compound="left",
                text=label,
                anchor="w",
                height=36,
                corner_radius=8,
                fg_color="transparent",
                hover_color="#2563EB",
                text_color="#FFFFFF",
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda page=key: self.show_page(page),
            )
            button.pack(fill="x", padx=10, pady=1)
            self.nav_buttons[key] = button

        # Bottom Settings
        settings_icon = self._get_icon("nav_settings.png", (18, 18))
        ctk.CTkButton(
            self.sidebar,
            image=settings_icon,
            compound="left",
            text="  Settings",
            anchor="w",
            height=36,
            corner_radius=8,
            fg_color="transparent",
            hover_color="#2563EB",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._open_settings_dialog,
        ).pack(side="bottom", fill="x", padx=10, pady=(6, 8))

        # Pro Tip Card in sidebar
        protip_card = ctk.CTkFrame(
            self.sidebar,
            corner_radius=10,
            fg_color="#172554",
            border_width=1,
            border_color="#1E3A8A",
        )
        protip_card.pack(side="bottom", fill="x", padx=10, pady=(6, 4))

        protip_head = ctk.CTkFrame(protip_card, fg_color="transparent")
        protip_head.pack(fill="x", padx=8, pady=(8, 2))
        ctk.CTkLabel(
            protip_head,
            text="👑  Pro Tip",
            text_color="#F59E0B",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="left")

        ctk.CTkLabel(
            protip_card,
            text="Enable Auto-save for 1-click downloads",
            text_color="#93C5FD",
            font=ctk.CTkFont(size=10),
            wraplength=160,
            justify="left",
        ).pack(fill="x", padx=8, pady=(0, 8))

        # Top Bar
        self.topbar = ctk.CTkFrame(self, height=60, corner_radius=0, fg_color=SURFACE, border_width=1, border_color=BORDER)
        self.topbar.grid(row=0, column=1, sticky="new")
        self.topbar.grid_propagate(False)

        # Left: Title + Slogan
        left_box = ctk.CTkFrame(self.topbar, fg_color="transparent")
        left_box.pack(side="left", padx=(20, 10), pady=6)

        self.title_label = ctk.CTkLabel(left_box, text="General", text_color=INK, font=ctk.CTkFont(size=17, weight="bold"))
        self.title_label.pack(anchor="w")

        self.slogan_label = ctk.CTkLabel(left_box, text="Download • Save • Convert • Enjoy Anywhere", text_color=MUTED, font=ctk.CTkFont(size=10))
        self.slogan_label.pack(anchor="w")

        # Right: ≡, ⚙ Settings, 🔔, [JA] Junaid Ali ● Online
        self.top_menu_btn = ctk.CTkButton(
            self.topbar,
            text="≡",
            width=36,
            height=34,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            font=ctk.CTkFont(size=18, weight="bold"),
            command=self._show_top_menu,
        )
        self.top_menu_btn.pack(side="right", padx=(4, 18), pady=13)

        # Theme Selector: Dark, Light, System
        self.theme_var = ctk.StringVar(value=self.settings.appearance_mode.title())
        self.theme_menu = ctk.CTkOptionMenu(
            self.topbar,
            values=["Dark", "Light", "System"],
            variable=self.theme_var,
            width=92,
            height=34,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            button_color=BLUE,
            text_color=INK,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._set_appearance_mode,
        )
        self.theme_menu.pack(side="right", padx=4, pady=13)

        ctk.CTkButton(
            self.topbar,
            text="⚙ Settings",
            width=92,
            height=34,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=BLUE,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._open_settings_dialog,
        ).pack(side="right", padx=4, pady=13)

        ctk.CTkButton(
            self.topbar,
            text="🔔",
            width=36,
            height=34,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            font=ctk.CTkFont(size=15),
            command=self._show_notifications_dialog,
        ).pack(side="right", padx=4, pady=13)



        # Pro Status / Trial Badge Button
        self.pro_badge_btn = ctk.CTkButton(
            self.topbar,
            text="👑 PRO",
            height=32,
            corner_radius=16,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._on_pro_badge_clicked,
        )
        self.pro_badge_btn.pack(side="right", padx=(4, 6), pady=14)
        self._update_pro_badge_ui()

        # Floating Clipboard Quick Download Toast
        self.clip_toast = ctk.CTkFrame(
            self,
            corner_radius=10,
            fg_color=("#1E293B", "#1E293B"),
            border_width=1,
            border_color="#38BDF8",
            height=44,
        )

        # Center Search Bar
        search_box = ctk.CTkFrame(self.topbar, fg_color="transparent")
        search_box.pack(side="left", fill="x", expand=True, padx=(10, 10), pady=12)

        self.top_search_var = ctk.StringVar()
        self.top_search_entry = ctk.CTkEntry(
            search_box,
            textvariable=self.top_search_var,
            placeholder_text="Search downloads, paste links, or explore features...",
            height=36,
            corner_radius=18,
            border_width=1,
            border_color=BORDER,
            fg_color=BACKGROUND,
            text_color=INK,
            font=ctk.CTkFont(size=12),
        )
        self.top_search_entry.pack(fill="x", expand=True)
        self.top_search_entry.bind("<Return>", lambda _: self._on_top_search())

        # Content Area
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=1, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self._build_dashboard_page()
        self._build_downloads_page()
        self._build_image_downloader_page()
        self._build_channel_hub_page()
        self._build_tiktok_hub_page()
        self._build_ig_hub_page()
        self._build_x_hub_page()
        self._build_converter_page()
        self._build_sites_page()

    def _build_dashboard_page(self) -> None:
        self.dashboard_page = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        self.dashboard_page.grid_columnconfigure(0, weight=1)

        # 1. Total Video / Metrics Row (Top)
        self.metrics_container = ctk.CTkFrame(self.dashboard_page, fg_color="transparent")
        self.metrics_container.pack(fill="x", padx=16, pady=(16, 12))
        self.metrics_container.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="metric_cols")

        self.lbl_metric_total = self._create_metric_card(
            parent=self.metrics_container,
            col=0,
            title="Total Downloads",
            initial_val="0",
            trend="↑ 12% this week",
            color="#38BDF8",
            icon_char="↓",
            spark_points=[(5, 22), (18, 18), (30, 21), (42, 12), (54, 15), (65, 6)],
        )

        self.lbl_metric_images = self._create_metric_card(
            parent=self.metrics_container,
            col=1,
            title="Images Downloaded",
            initial_val="0",
            trend="↑ 28% this week",
            color="#10B981",
            icon_char="🖼",
            spark_points=[(5, 24), (16, 20), (28, 14), (40, 16), (52, 10), (65, 5)],
        )

        self.lbl_metric_audio = self._create_metric_card(
            parent=self.metrics_container,
            col=2,
            title="Audio Converted",
            initial_val="0",
            trend="↑ 5% this week",
            color="#818CF8",
            icon_char="🎵",
            spark_points=[(5, 18), (18, 22), (32, 16), (44, 18), (56, 12), (65, 8)],
        )

        self.lbl_metric_video = self._create_metric_card(
            parent=self.metrics_container,
            col=3,
            title="Videos Converted",
            initial_val="0",
            trend="↑ 18% this week",
            color="#F59E0B",
            icon_char="🎬",
            spark_points=[(5, 25), (18, 19), (30, 15), (42, 17), (55, 9), (65, 4)],
        )

        # 2. Hero Downloader Banner (Below Metrics)
        hero = ctk.CTkFrame(
            self.dashboard_page,
            corner_radius=16,
            fg_color=SURFACE,
            border_width=1,
            border_color=BORDER,
        )
        hero.pack(fill="x", padx=16, pady=(0, 16))

        # Heading: "Download Anything from the Web"
        heading_box = ctk.CTkFrame(hero, fg_color="transparent")
        heading_box.pack(anchor="w", padx=20, pady=(18, 4))
        ctk.CTkLabel(heading_box, text="Download ", text_color=INK, font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkLabel(heading_box, text="Anything ", text_color=BLUE, font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkLabel(heading_box, text="from the Web", text_color=INK, font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")

        # Subtitle
        ctk.CTkLabel(
            hero,
            text="Paste any video, playlist, image, or audio link from YouTube, TikTok, Instagram, X and 1000+ sites.",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=20, pady=(0, 14))

        # Main Hero Input Bar
        input_card = ctk.CTkFrame(hero, corner_radius=10, fg_color=("#F1F5F9", "#131D30"), border_width=1, border_color=BORDER)
        input_card.pack(fill="x", padx=20, pady=(0, 12))

        ctk.CTkLabel(input_card, text="🔗", font=ctk.CTkFont(size=14), text_color=BLUE).pack(side="left", padx=(12, 6))

        self.dash_url_var = ctk.StringVar()
        self.dash_url_entry = ctk.CTkEntry(
            input_card,
            textvariable=self.dash_url_var,
            placeholder_text="Paste any video, playlist, or image link here...",
            height=38,
            border_width=0,
            fg_color="transparent",
            text_color=INK,
            font=ctk.CTkFont(size=13),
        )
        self.dash_url_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.dash_url_entry.bind("<Return>", lambda _: self._on_dash_download())

        # Paste split button (📋 Paste ⌄)
        paste_grp = ctk.CTkFrame(input_card, fg_color="transparent")
        paste_grp.pack(side="left", padx=(2, 4))

        ctk.CTkButton(
            paste_grp,
            text="📋 Paste",
            width=68,
            height=32,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._paste_from_clipboard_dash,
        ).pack(side="left")

        self.dash_paste_menu_btn = ctk.CTkButton(
            paste_grp,
            text="⌄",
            width=24,
            height=32,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            command=self._show_paste_menu,
        )
        self.dash_paste_menu_btn.pack(side="left", padx=(2, 0))

        # Format Dropdown: Download Video / Audio MP3 / Audio WAV / Image
        self.dash_format_var = ctk.StringVar(value="Download Video")
        self.dash_format_menu = ctk.CTkOptionMenu(
            input_card,
            values=["Download Video", "Audio MP3", "Audio WAV", "Image / Photo (JPG/PNG)"],
            variable=self.dash_format_var,
            command=self._on_dash_format_changed,
            width=140,
            height=32,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            button_color="#3B82F6",
            text_color=INK,
            font=ctk.CTkFont(size=11),
        )
        self.dash_format_menu.pack(side="left", padx=(2, 4))

        # Quality Dropdown
        self.dash_quality_var = ctk.StringVar(value=self.settings.default_quality if self.settings.default_quality in QUALITY_OPTIONS else "Best Available")
        self.dash_quality_menu = ctk.CTkOptionMenu(
            input_card,
            values=QUALITY_OPTIONS,
            variable=self.dash_quality_var,
            width=125,
            height=32,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            button_color="#3B82F6",
            text_color=INK,
            font=ctk.CTkFont(size=11),
        )
        self.dash_quality_menu.pack(side="left", padx=(2, 4))

        # Download Now Button
        ctk.CTkButton(
            input_card,
            text="⚡ Download Now",
            width=125,
            height=32,
            corner_radius=6,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_dash_download,
        ).pack(side="left", padx=(2, 8))

        # Hero Secondary Controls Toolbar
        ctrl_bar = ctk.CTkFrame(hero, fg_color="transparent")
        ctrl_bar.pack(fill="x", padx=20, pady=(0, 18))

        ctk.CTkButton(
            ctrl_bar,
            text="☷ Batch URLs",
            width=105,
            height=26,
            corner_radius=6,
            fg_color=("#1E293B", "#1E293B"),
            hover_color="#2563EB",
            text_color=BLUE,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._go_to_downloads,
        ).pack(side="left", padx=(0, 8))

        self.dash_folder_label = ctk.CTkLabel(
            ctrl_bar,
            text="",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        )
        self.dash_folder_label.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(
            ctrl_bar,
            text="⚙ Settings",
            width=78,
            height=26,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            font=ctk.CTkFont(size=11),
            command=self._open_download_settings_modal,
        ).pack(side="right")

        ctk.CTkButton(
            ctrl_bar,
            text="📁 Browse",
            width=70,
            height=26,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            font=ctk.CTkFont(size=11),
            command=self._choose_folder,
        ).pack(side="right", padx=(0, 8))

        self._update_folder_label()

    def _on_dash_format_changed(self, choice: str) -> None:
        if "Image" in choice:
            self.dash_quality_var.set("Image / Photo")
        elif "MP3" in choice:
            self.dash_quality_var.set("Audio MP3")
        elif "WAV" in choice:
            self.dash_quality_var.set("Audio WAV")
        elif "Video" in choice:
            if "Audio" in self.dash_quality_var.get() or "Image" in self.dash_quality_var.get():
                self.dash_quality_var.set(self.settings.default_quality if self.settings.default_quality in QUALITY_OPTIONS and "Audio" not in self.settings.default_quality and "Image" not in self.settings.default_quality else "Best Available")

    def _paste_from_clipboard_dash(self) -> None:
        try:
            url = self.clipboard_get().strip()
        except TclError:
            messagebox.showinfo("Clipboard is empty", "Copy a public video URL first, then choose Paste.")
            return
        if url:
            self.dash_url_var.set(url)
            self._on_dash_download()

    def _on_dash_download(self) -> None:
        url = self.dash_url_var.get().strip()
        if not url:
            try:
                clip = self.clipboard_get().strip()
                if clip and ("http://" in clip or "https://" in clip):
                    url = clip
                    self.dash_url_var.set(clip)
            except Exception:
                pass
        if not url:
            messagebox.showwarning("Enter URL", "Please enter or paste a valid video or image URL to download.")
            return
        format_choice = self.dash_format_var.get()
        selected_quality = "Image / Photo" if "Image" in format_choice else self.dash_quality_var.get()
        self.format_choice_var.set(format_choice)
        self.quality_var.set(selected_quality)
        self._queue_urls([url])
        self.show_page("downloads")
        self._set_downloads_tab("downloading")
        self.dash_url_var.set("")

    def _create_metric_card(
        self,
        parent: ctk.CTkFrame,
        col: int,
        title: str,
        initial_val: str,
        trend: str,
        color: str,
        icon_char: str,
        spark_points: list[tuple[int, int]],
    ) -> ctk.CTkLabel:
        card = ctk.CTkFrame(parent, corner_radius=14, fg_color=SURFACE, border_width=1, border_color=BORDER)
        card.grid(row=0, column=col, sticky="nsew", padx=5, pady=2)

        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=14, pady=(12, 6))

        icon_lbl = ctk.CTkLabel(
            top_row,
            text=icon_char,
            width=36,
            height=36,
            corner_radius=18,
            fg_color=("#EEF2F6", "#1E293B"),
            text_color=color,
            font=ctk.CTkFont(size=17, weight="bold"),
        )
        icon_lbl.pack(side="left")

        bg_c = "#FFFFFF" if ctk.get_appearance_mode() == "Light" else "#1E293B"
        canvas = Canvas(top_row, width=70, height=28, bg=bg_c, highlightthickness=0)
        canvas.pack(side="right")
        if not hasattr(self, "_spark_canvases"):
            self._spark_canvases = []
        self._spark_canvases.append(canvas)
        self._draw_sparkline(canvas, spark_points, color)

        ctk.CTkLabel(
            card,
            text=title,
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 2))

        val_lbl = ctk.CTkLabel(
            card,
            text=initial_val,
            text_color=INK,
            font=ctk.CTkFont(size=24, weight="bold"),
            anchor="w",
        )
        val_lbl.pack(fill="x", padx=14, pady=(0, 4))

        ctk.CTkLabel(
            card,
            text=trend,
            text_color="#10B981",
            font=ctk.CTkFont(size=10, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 12))

        return val_lbl

    def _draw_sparkline(self, canvas: Canvas, points: list[tuple[int, int]], color: str) -> None:
        try:
            canvas.delete("all")
            flat = [coord for pt in points for coord in pt]
            if len(flat) >= 4:
                canvas.create_line(*flat, smooth=True, fill=color, width=2)
                last_x, last_y = points[-1]
                canvas.create_oval(last_x - 3, last_y - 3, last_x + 3, last_y + 3, fill=color, outline=color)
        except Exception:
            pass

    def _bind_clickable_card(self, widget, cmd) -> None:
        def on_click(e=None):
            cmd()

        def on_enter(e=None):
            try:
                widget.configure(border_color=BLUE, fg_color=("#F1F5F9", "#1E293B"))
            except Exception:
                pass

        def on_leave(e=None):
            try:
                widget.configure(border_color=BORDER, fg_color=("#F8FAFC", "#0F172A"))
            except Exception:
                pass

        def bind_rec(w):
            w.bind("<Button-1>", on_click)
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass
            if hasattr(w, "winfo_children"):
                for c in w.winfo_children():
                    bind_rec(c)

        bind_rec(widget)

    def _refresh_dashboard_metrics(self) -> None:
        try:
            records = history_store.get_all_records()
            total = len(records)
            images = sum(1 for r in records if r.file_extension.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"} or r.platform == "image")
            audio = sum(1 for r in records if r.file_extension.lower() in {".mp3", ".wav", ".m4a", ".aac", ".flac"} or "audio" in r.platform.lower())
            video = max(0, total - images - audio)

            if hasattr(self, "lbl_metric_total"):
                self.lbl_metric_total.configure(text=str(total))
            if hasattr(self, "lbl_metric_images"):
                self.lbl_metric_images.configure(text=str(images))
            if hasattr(self, "lbl_metric_audio"):
                self.lbl_metric_audio.configure(text=str(audio))
            if hasattr(self, "lbl_metric_video"):
                self.lbl_metric_video.configure(text=str(video))
        except Exception:
            pass

    def _refresh_recent_downloads_list(self) -> None:
        if not hasattr(self, "dash_recent_list_frame"):
            return
        for w in self.dash_recent_list_frame.winfo_children():
            w.destroy()
        try:
            records = history_store.get_all_records()
            recent = sorted(records, key=lambda r: r.timestamp, reverse=True)[:5]
        except Exception:
            recent = []

        if not recent:
            if hasattr(self, "dash_empty_state"):
                self.dash_empty_state.pack(fill="both", expand=True, pady=18)
            return

        if hasattr(self, "dash_empty_state"):
            self.dash_empty_state.pack_forget()

        for rec in recent:
            item_row = ctk.CTkFrame(self.dash_recent_list_frame, corner_radius=8, fg_color=("#F8FAFC", "#0F172A"), border_width=1, border_color=BORDER)
            item_row.pack(fill="x", padx=4, pady=3)

            p_color = "#3B82F6"
            p_name = rec.platform.capitalize() if rec.platform else "Web"
            if "youtube" in rec.platform.lower():
                p_color = "#EF4444"
            elif "tiktok" in rec.platform.lower():
                p_color = "#00F2FE"
            elif "instagram" in rec.platform.lower():
                p_color = "#E1306C"
            elif "x" in rec.platform.lower():
                p_color = "#CBD5E1"

            ctk.CTkLabel(
                item_row,
                text=p_name,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=p_color,
                fg_color=("#EEF2F6", "#1E293B"),
                corner_radius=6,
                width=65,
                height=24,
            ).pack(side="left", padx=(8, 8), pady=8)

            info_box = ctk.CTkFrame(item_row, fg_color="transparent")
            info_box.pack(side="left", fill="x", expand=True, pady=4)

            t_title = rec.title if rec.title else "Downloaded Media"
            if len(t_title) > 55:
                t_title = t_title[:52] + "..."
            ctk.CTkLabel(info_box, text=t_title, font=ctk.CTkFont(size=11, weight="bold"), text_color=INK, anchor="w").pack(anchor="w")

            meta_str = f"{rec.file_extension.upper()} • {rec.status.capitalize()}"
            if rec.creator:
                meta_str = f"Creator: {rec.creator} • " + meta_str
            ctk.CTkLabel(info_box, text=meta_str, font=ctk.CTkFont(size=9), text_color=MUTED, anchor="w").pack(anchor="w")

            ctk.CTkButton(
                item_row,
                text="⋮",
                width=28,
                height=26,
                corner_radius=6,
                fg_color=SECONDARY_BTN,
                hover_color=SECONDARY_BTN_HOVER,
                text_color=INK,
                font=ctk.CTkFont(size=14, weight="bold"),
                command=lambda r=rec, b=item_row: self._show_recent_item_menu(r, b),
            ).pack(side="right", padx=(4, 8), pady=6)

    def _show_recent_item_menu(self, record: DownloadRecord, widget: ctk.CTkFrame) -> None:
        menu = Menu(self, tearoff=False)
        if record.saved_filepath and Path(record.saved_filepath).is_file():
            menu.add_command(label="▶ Open File", command=lambda: os.startfile(record.saved_filepath))
            menu.add_command(label="📁 Open Folder", command=lambda: os.system(f'explorer /select,"{Path(record.saved_filepath).resolve()}"'))
        elif record.saved_filepath and Path(record.saved_filepath).parent.is_dir():
            menu.add_command(label="📁 Open Folder", command=lambda: os.startfile(str(Path(record.saved_filepath).parent)))
        if record.url:
            menu.add_command(label="📋 Copy Link", command=lambda: self._copy_to_clipboard(record.url))
        menu.add_separator()
        menu.add_command(label="🗑 Remove from History", command=lambda: self._remove_history_record(record))
        try:
            x = widget.winfo_rootx() + widget.winfo_width() - 30
            y = widget.winfo_rooty() + 20
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _copy_to_clipboard(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)

    def _remove_history_record(self, record: DownloadRecord) -> None:
        history_store.remove_record(record.id)
        self._refresh_dashboard_metrics()
        self._refresh_recent_downloads_list()

    def _build_downloads_page(self) -> None:
        self.download_page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.download_page.grid_columnconfigure(0, weight=1)
        self.download_page.grid_rowconfigure(3, weight=1)

        self._downloads_tab = "downloading"

        # 1. Top Options Card (Exact options requested: URL bar, Paste, Format, Quality, Download Now, Batch URLs, Folder, Browse, Settings)
        top_card = ctk.CTkFrame(
            self.download_page,
            corner_radius=12,
            fg_color=SURFACE,
            border_width=1,
            border_color=BORDER,
        )
        top_card.grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 8))
        top_card.grid_columnconfigure(0, weight=1)

        # Row 1: Universal Link Input + Paste + Format Menu + Quality Menu + Download Now Button
        input_card = ctk.CTkFrame(
            top_card,
            corner_radius=8,
            fg_color=("#F1F5F9", "#131D30"),
            border_width=1,
            border_color=BORDER,
        )
        input_card.pack(fill="x", padx=12, pady=(12, 8))

        ctk.CTkLabel(input_card, text="🔗", font=ctk.CTkFont(size=14), text_color="#38BDF8").pack(side="left", padx=(10, 4))

        self.hero_url_var = ctk.StringVar()
        self.hero_url_entry = ctk.CTkEntry(
            input_card,
            textvariable=self.hero_url_var,
            placeholder_text="Paste any video, playlist, or image link here...",
            height=36,
            border_width=0,
            fg_color="transparent",
            text_color=INK,
            font=ctk.CTkFont(size=13),
        )
        self.hero_url_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.hero_url_entry.bind("<Return>", lambda _: self._on_hero_download())

        # Paste split button (📋 Paste Link ⌄)
        paste_grp = ctk.CTkFrame(input_card, fg_color="transparent")
        paste_grp.pack(side="left", padx=(2, 4))

        ctk.CTkButton(
            paste_grp,
            text="📋 Paste",
            width=68,
            height=32,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._paste_from_clipboard,
        ).pack(side="left")

        self.paste_menu_button = ctk.CTkButton(
            paste_grp,
            text="⌄",
            width=24,
            height=32,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            command=self._show_paste_menu,
        )
        self.paste_menu_button.pack(side="left", padx=(2, 0))

        # Format Dropdown: Download Video / Audio MP3 / Audio WAV / Image
        self.format_choice_var = ctk.StringVar(value="Download Video")
        self.format_menu = ctk.CTkOptionMenu(
            input_card,
            values=["Download Video", "Audio MP3", "Audio WAV", "Image / Photo (JPG/PNG)"],
            variable=self.format_choice_var,
            command=self._on_format_changed,
            width=135,
            height=32,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            button_color="#3B82F6",
            text_color=INK,
            font=ctk.CTkFont(size=11),
        )
        self.format_menu.pack(side="left", padx=(2, 4))

        # Quality Dropdown
        self.quality_var = ctk.StringVar(value=self.settings.default_quality if self.settings.default_quality in QUALITY_OPTIONS else "Best Available")
        self.speed_var = ctk.StringVar(value=self.settings.default_speed_limit)
        self.quality_menu = ctk.CTkOptionMenu(
            input_card,
            values=QUALITY_OPTIONS,
            variable=self.quality_var,
            width=120,
            height=32,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            button_color="#3B82F6",
            text_color=INK,
            font=ctk.CTkFont(size=11),
        )
        self.quality_menu.pack(side="left", padx=(2, 4))

        # Download Now Button
        ctk.CTkButton(
            input_card,
            text="⚡ Download Now",
            width=120,
            height=32,
            corner_radius=6,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_hero_download,
        ).pack(side="left", padx=(2, 6))

        # Row 2: Secondary Toolbar (Batch URLs, Folder Selector, Browse, Settings)
        ctrl_bar = ctk.CTkFrame(top_card, fg_color="transparent")
        ctrl_bar.pack(fill="x", padx=12, pady=(0, 10))

        ctk.CTkButton(
            ctrl_bar,
            text="☷ Batch URLs",
            width=100,
            height=26,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=BLUE,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._toggle_multi_urls,
        ).pack(side="left", padx=(0, 8))

        self.folder_label = ctk.CTkLabel(
            ctrl_bar,
            text="",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        )
        self.folder_label.pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            ctrl_bar,
            text="📁 Browse",
            width=70,
            height=26,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            font=ctk.CTkFont(size=11),
            command=self._choose_folder,
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            ctrl_bar,
            text="⚙ Settings",
            width=76,
            height=26,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            font=ctk.CTkFont(size=11),
            command=self._open_download_settings_modal,
        ).pack(side="right")

        # 2. Multi-URLs Batch Drawer (Expandable)
        self.form_drawer = ctk.CTkFrame(self.download_page, corner_radius=10, fg_color=SURFACE, border_width=1, border_color=BORDER)
        self.form_drawer.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 8))
        self.form_drawer.grid_columnconfigure(0, weight=1)

        self._batch_placeholder = "Paste one public video URL per line…"
        self._batch_placeholder_active = True

        self.url_box = ctk.CTkTextbox(
            self.form_drawer,
            height=68,
            corner_radius=8,
            border_width=1,
            border_color=BORDER,
            fg_color=("#F8FAFC", "#131C2E"),
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        )
        self.url_box.pack(fill="x", padx=12, pady=(10, 6))
        self.url_box.insert("1.0", self._batch_placeholder)

        def _on_url_box_focus_in(event=None):
            if getattr(self, "_batch_placeholder_active", False):
                self.url_box.delete("1.0", "end")
                self.url_box.configure(text_color=INK)
                self._batch_placeholder_active = False

        def _on_url_box_focus_out(event=None):
            content = self.url_box.get("1.0", "end").strip()
            if not content:
                self.url_box.delete("1.0", "end")
                self.url_box.insert("1.0", self._batch_placeholder)
                self.url_box.configure(text_color=MUTED)
                self._batch_placeholder_active = True

        self.url_box.bind("<FocusIn>", _on_url_box_focus_in)
        self.url_box.bind("<FocusOut>", _on_url_box_focus_out)
        self._reset_url_box_placeholder = _on_url_box_focus_out

        drawer_ctrls = ctk.CTkFrame(self.form_drawer, fg_color="transparent")
        drawer_ctrls.pack(fill="x", padx=12, pady=(0, 10))

        ctk.CTkLabel(
            drawer_ctrls,
            text="Tip: Batch URLs will be sequentially named and auto-placed in creator folders.",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
        ).pack(side="left")

        ctk.CTkButton(
            drawer_ctrls,
            text="✕ Close",
            width=65,
            height=28,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            font=ctk.CTkFont(size=11),
            command=self._toggle_multi_urls,
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            drawer_ctrls,
            text="+ Add to queue",
            width=110,
            height=28,
            corner_radius=6,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._add_urls,
        ).pack(side="right")

        self.form_drawer.grid_remove()
        self._multi_urls_visible = False

        # 3. Status Tabs Bar: [ Downloading (0) ] [ Finished (0) ] [ Clear all ]
        tabs_bar = ctk.CTkFrame(self.download_page, fg_color="transparent")
        tabs_bar.grid(row=2, column=0, sticky="ew", padx=20, pady=(4, 8))

        self.tab_downloading_btn = ctk.CTkButton(
            tabs_bar,
            text="Downloading (0)",
            width=130,
            height=32,
            corner_radius=6,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._set_downloads_tab("downloading"),
        )
        self.tab_downloading_btn.pack(side="left", padx=(0, 8))

        self.tab_finished_btn = ctk.CTkButton(
            tabs_bar,
            text="Finished (0)",
            width=110,
            height=32,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=MUTED,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._set_downloads_tab("finished"),
        )
        self.tab_finished_btn.pack(side="left")

        self.delete_all_button = ctk.CTkButton(
            tabs_bar,
            text="Clear all",
            width=78,
            height=28,
            corner_radius=6,
            fg_color=DANGER_BTN,
            hover_color=DANGER_BTN_HOVER,
            text_color=DANGER_TEXT,
            font=ctk.CTkFont(size=11),
            command=self._delete_all,
        )
        self.delete_all_button.pack(side="right")

        self.queue_label = ctk.CTkLabel(tabs_bar, text="", text_color=MUTED, font=ctk.CTkFont(size=12))
        self.queue_label.pack(side="right", padx=12)

        # 4. Scrollable Download Tasks Queue
        self.list_frame = ctk.CTkScrollableFrame(
            self.download_page,
            corner_radius=12,
            fg_color=("#F8FAFC", "#0F172A"),
            border_width=1,
            border_color=BORDER,
        )
        self.list_frame.grid(row=3, column=0, sticky="nsew", padx=20, pady=(0, 16))

        # Empty state graphic
        self.empty_state = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        self.empty_state.pack(expand=True, pady=70)

        folder_icon_box = ctk.CTkFrame(self.empty_state, width=64, height=54, corner_radius=12, fg_color=("#38BDF8", "#0284C7"))
        folder_icon_box.pack(pady=(0, 10))
        folder_icon_box.pack_propagate(False)

        ctk.CTkLabel(
            folder_icon_box,
            text="↓",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=26, weight="bold"),
        ).place(relx=0.5, rely=0.5, anchor="center")

        self.empty_state_text = ctk.CTkLabel(
            self.empty_state,
            text="No download tasks yet.\nPaste any link in the bar above to start downloading!",
            text_color=MUTED,
            font=ctk.CTkFont(size=12, weight="bold"),
            justify="center",
        )
        self.empty_state_text.pack()

        self._update_folder_label()

    def _on_hero_download(self) -> None:
        url = self.hero_url_var.get().strip()
        if not url:
            try:
                clip = self.clipboard_get().strip()
                if clip and ("http://" in clip or "https://" in clip):
                    url = clip
                    self.hero_url_var.set(clip)
            except Exception:
                pass
        if not url:
            messagebox.showwarning("Enter URL", "Please enter or paste a valid video or image URL to download.")
            return
        if is_playlist_or_channel(url):
            self._open_playlist_dialog(initial_url=url)
            self.hero_url_var.set("")
            return
        self._queue_urls([url])
        self._set_downloads_tab("downloading")
        self.hero_url_var.set("")

    def _on_top_search(self) -> None:
        val = self.top_search_var.get().strip()
        if not val:
            return
        if "://" in val or val.startswith("www.") or (("." in val) and (" " not in val) and len(val.split(".")) >= 2):
            if is_playlist_or_channel(val):
                self._open_playlist_dialog(initial_url=val)
                self.top_search_var.set("")
                return
            self._queue_urls([val])
            self.show_page("downloads")
            self._set_downloads_tab("downloading")
            self.top_search_var.set("")
        elif val.startswith("@") or "youtube" in val.lower() or "channel" in val.lower():
            if hasattr(self, "channel_search_var"):
                self.channel_search_var.set(val)
            self.show_page("channel_hub")
            self._explore_channel()
        elif "tiktok" in val.lower():
            if hasattr(self, "tiktok_search_var"):
                self.tiktok_search_var.set(val)
            self.show_page("tiktok_hub")
            self._explore_tiktok()
        elif "instagram" in val.lower() or "insta" in val.lower():
            if hasattr(self, "ig_search_var"):
                self.ig_search_var.set(val)
            self.show_page("ig_hub")
            self._explore_instagram()
        else:
            self._queue_urls([val])
            self.show_page("downloads")
            self._set_downloads_tab("downloading")
            self.top_search_var.set("")

    def _show_notifications_dialog(self) -> None:
        messagebox.showinfo(
            "Notifications",
            "DeepX Vision Downloader is up to date!\n\n"
            "• Engine: yt-dlp + FFmpeg Ready\n"
            "• Creator Folder Organization: Active\n"
            "• Duplicate Detection & History: Active\n"
            "• 10+ Supported Platforms: Ready"
        )

    def _set_downloads_tab(self, tab: str) -> None:
        self._downloads_tab = tab
        if tab == "downloading":
            self.tab_downloading_btn.configure(fg_color=BLUE, text_color="#FFFFFF")
            self.tab_finished_btn.configure(fg_color=SECONDARY_BTN, text_color=MUTED)
        else:
            self.tab_downloading_btn.configure(fg_color=SECONDARY_BTN, text_color=MUTED)
            self.tab_finished_btn.configure(fg_color=BLUE, text_color="#FFFFFF")
        self._filter_task_list()

    def _filter_task_list(self) -> None:
        tab = getattr(self, "_downloads_tab", "downloading")
        active_count = 0
        finished_count = 0
        visible_count = 0

        for task_id, item in list(self.items.items()):
            task = self.tasks.get(task_id)
            if not task:
                continue
            is_finished = task.status in {DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED}
            if is_finished:
                finished_count += 1
            else:
                active_count += 1

            if tab == "downloading":
                if not is_finished:
                    item.pack(fill="x", padx=6, pady=5)
                    visible_count += 1
                else:
                    item.pack_forget()
            else:
                if is_finished:
                    item.pack(fill="x", padx=6, pady=5)
                    visible_count += 1
                else:
                    item.pack_forget()

        if hasattr(self, "tab_downloading_btn"):
            self.tab_downloading_btn.configure(text=f"Downloading ({active_count})")
        if hasattr(self, "tab_finished_btn"):
            self.tab_finished_btn.configure(text=f"Finished ({finished_count})")

        if visible_count == 0:
            self.empty_state.pack(expand=True, pady=70)
            if tab == "downloading":
                self.empty_state_text.configure(text="No download tasks yet.")
            else:
                self.empty_state_text.configure(text="No finished tasks yet.")
        else:
            self.empty_state.pack_forget()

    # =========================================================================
    # DEDICATED IMAGE & PHOTO DOWNLOADER SECTION
    # =========================================================================

    def _build_image_downloader_page(self) -> None:
        self.image_downloader_page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.image_downloader_page.grid_columnconfigure(0, weight=1)
        self.image_downloader_page.grid_rowconfigure(1, weight=1)

        # 1. Top Input Card
        top_card = ctk.CTkFrame(self.image_downloader_page, corner_radius=12, fg_color=SURFACE, border_width=1, border_color=BORDER)
        top_card.grid(row=0, column=0, sticky="ew", padx=24, pady=(16, 12))
        top_card.grid_columnconfigure(0, weight=1)

        header_row = ctk.CTkFrame(top_card, fg_color="transparent")
        header_row.pack(fill="x", padx=18, pady=(16, 6))

        ctk.CTkLabel(
            header_row,
            text="🖼 Image & Photo Downloader",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=INK,
        ).pack(side="left")

        # Pill tags showing supported platforms
        tag_frame = ctk.CTkFrame(header_row, fg_color="transparent")
        tag_frame.pack(side="right")
        for tag_icon, tag_text, tag_color in [
            ("plat_instagram.png", "Instagram Carousels", "#EC4899"),
            ("plat_youtube.png", "YouTube Thumbnails", "#EF4444"),
            ("plat_tiktok.png", "TikTok Photos", "#06B6D4"),
            ("plat_pinterest.png", "Pinterest / Web", "#F59E0B"),
        ]:
            t_icon_img = self._get_icon(tag_icon, (15, 15))
            ctk.CTkLabel(
                tag_frame,
                image=t_icon_img,
                compound="left",
                text=f"  {tag_text}",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=tag_color,
                fg_color=SECONDARY_BTN,
                corner_radius=6,
                padx=8,
                pady=2,
            ).pack(side="left", padx=4)

        ctk.CTkLabel(
            top_card,
            text="Paste any post, carousel, profile, video, or direct image URL to extract and download all full-resolution photos.",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            anchor="w",
        ).pack(fill="x", padx=18, pady=(0, 12))

        # Input & Button Row
        input_row = ctk.CTkFrame(top_card, fg_color="transparent")
        input_row.pack(fill="x", padx=18, pady=(0, 10))
        input_row.grid_columnconfigure(0, weight=1)

        self.img_url_entry = ctk.CTkEntry(
            input_row,
            placeholder_text="Paste image or post link here (Instagram, YouTube, TikTok, Pinterest, .jpg, .png)...",
            height=38,
            corner_radius=8,
            border_color=BORDER,
            fg_color=BACKGROUND,
            text_color=INK,
            font=ctk.CTkFont(size=12),
        )
        self.img_url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.img_url_entry.bind("<Return>", lambda _: self._img_analyze_link())

        ctk.CTkButton(
            input_row,
            text="📋 Paste",
            width=80,
            height=38,
            corner_radius=8,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._img_paste_from_clipboard,
        ).grid(row=0, column=1, padx=(0, 6))

        self.img_analyze_btn = ctk.CTkButton(
            input_row,
            text="🔍 Preview Media",
            width=120,
            height=38,
            corner_radius=8,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._img_analyze_link,
        )
        self.img_analyze_btn.grid(row=0, column=2, padx=(0, 6))

        self.img_quick_btn = ctk.CTkButton(
            input_row,
            text="⬇ Quick Download",
            width=135,
            height=38,
            corner_radius=8,
            fg_color="#10B981",
            hover_color="#059669",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._img_quick_download,
        )
        self.img_quick_btn.grid(row=0, column=3)

        # Options / Destination bar below input
        opts_row = ctk.CTkFrame(top_card, fg_color="transparent")
        opts_row.pack(fill="x", padx=18, pady=(0, 14))

        ctk.CTkLabel(opts_row, text="Save to:", font=ctk.CTkFont(size=12, weight="bold"), text_color=MUTED).pack(side="left")
        self.img_folder_label = ctk.CTkLabel(
            opts_row,
            text=str(self.settings.resolved_download_folder()),
            font=ctk.CTkFont(size=11),
            text_color=INK,
        )
        self.img_folder_label.pack(side="left", padx=(6, 12))

        ctk.CTkButton(
            opts_row,
            text="📂 Browse",
            width=70,
            height=24,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            font=ctk.CTkFont(size=11),
            command=self._img_browse_folder,
        ).pack(side="left", padx=(0, 16))

        self.img_status_label = ctk.CTkLabel(
            opts_row,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=BLUE,
        )
        self.img_status_label.pack(side="right")

        # 2. Main Results & Preview Area
        self.img_main_scroll = ctk.CTkScrollableFrame(self.image_downloader_page, fg_color="transparent")
        self.img_main_scroll.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 16))
        self.img_main_scroll.grid_columnconfigure(0, weight=1)

        self._current_extracted_images: list[dict] = []
        self._img_card_checkboxes: list[tuple[dict, ctk.BooleanVar]] = []
        self._render_image_empty_state()

    def _render_image_empty_state(self) -> None:
        for child in self.img_main_scroll.winfo_children():
            child.destroy()

        empty_box = ctk.CTkFrame(self.img_main_scroll, fg_color=SURFACE, corner_radius=14, border_width=1, border_color=BORDER)
        empty_box.pack(fill="both", expand=True, padx=10, pady=20)

        center_img = self._get_icon("nav_image.png", (64, 64))
        if center_img:
            ctk.CTkLabel(
                empty_box,
                image=center_img,
                text="",
            ).pack(pady=(40, 12))
        else:
            ctk.CTkLabel(
                empty_box,
                text="🖼",
                font=ctk.CTkFont(size=56),
                text_color=BLUE,
            ).pack(pady=(40, 12))

        ctk.CTkLabel(
            empty_box,
            text="Multi-Platform Photo & Image Downloader",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=INK,
        ).pack(pady=(0, 8))

        ctk.CTkLabel(
            empty_box,
            text="Paste any link above to preview all photos or download them directly in full resolution.",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        ).pack(pady=(0, 24))

        # Guides grid
        guide_grid = ctk.CTkFrame(empty_box, fg_color="transparent")
        guide_grid.pack(padx=30, pady=(0, 40))

        guides = [
            ("plat_instagram.png", "Instagram Carousels", "Downloads every slide from multi-photo carousel posts sequentially (01.jpg, 02.jpg...)."),
            ("plat_youtube.png", "YouTube Thumbnails", "Extracts the highest-resolution HD & 4K video thumbnails directly."),
            ("plat_tiktok.png", "TikTok Photo Mode", "Grabs all original slides from TikTok photo posts and slideshows."),
            ("plat_pinterest.png", "Pinterest & Web Images", "Supports Pinterest pins, Twitter photos, and any direct image link (.jpg, .png, .webp)."),
        ]

        for i, (g_icon_file, g_title, g_desc) in enumerate(guides):
            col = i % 2
            row = i // 2
            card = ctk.CTkFrame(guide_grid, corner_radius=10, fg_color=SECONDARY_BTN, width=280, height=84)
            card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
            card.pack_propagate(False)

            g_img = self._get_icon(g_icon_file, (20, 20))
            ctk.CTkLabel(
                card,
                image=g_img,
                compound="left",
                text=f"  {g_title}",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=INK,
                anchor="w",
            ).pack(fill="x", padx=12, pady=(10, 4))

            ctk.CTkLabel(
                card,
                text=g_desc,
                font=ctk.CTkFont(size=11),
                text_color=MUTED,
                anchor="w",
                justify="left",
                wraplength=250,
            ).pack(fill="x", padx=12, pady=(0, 10))

    def _img_paste_from_clipboard(self) -> None:
        try:
            url = self.clipboard_get().strip()
            if url:
                self.img_url_entry.delete(0, "end")
                self.img_url_entry.insert(0, url)
                self._img_analyze_link()
        except TclError:
            messagebox.showinfo("Clipboard Empty", "Copy an image or post link first, then click Paste.")

    def _img_browse_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=str(self.settings.resolved_download_folder()))
        if chosen:
            self.settings.download_folder = chosen
            self.store.save(self.settings)
            self.img_folder_label.configure(text=chosen)
            self._update_folder_label()

    def _img_quick_download(self) -> None:
        url = self.img_url_entry.get().strip()
        if not url:
            messagebox.showwarning("Enter URL", "Please paste or enter an image or post link.")
            return

        cookie_src = self._get_cookie_source_for_url(url)
        p, mid, creator, _ = extract_media_identity(url)
        task = DownloadTask(
            url=url,
            destination=str(self.settings.resolved_download_folder()),
            quality="Image / Photo",
            cookies_source=cookie_src,
            creator=creator,
            media_id=mid,
            platform=p,
            on_duplicate_prompt=self.prompt_duplicate_confirmation_sync,
        )
        self.empty_state.pack_forget()
        self.tasks[task.id] = task
        item = DownloadItem(
            self.list_frame,
            task,
            self._cancel,
            self._retry,
            self._pause,
            self._resume,
            self._show_task_menu,
        )
        item.pack(fill="x", padx=6, pady=5)
        self.items[task.id] = item
        self.manager.add(task)
        self.show_page("downloads")
        messagebox.showinfo("Download Started", "Queued image download task! Check the General Downloads tab.")

    def _img_analyze_link(self) -> None:
        url = self.img_url_entry.get().strip()
        if not url:
            messagebox.showwarning("Enter URL", "Please paste or enter an image or post link.")
            return

        self.img_analyze_btn.configure(state="disabled")
        self.img_quick_btn.configure(state="disabled")
        self.img_status_label.configure(text="Analyzing link and extracting images... Please wait.")

        cookie_src = self._get_cookie_source_for_url(url)

        def worker():
            try:
                images = extract_media_images(url, cookies_source=cookie_src)
                def on_done():
                    self.img_analyze_btn.configure(state="normal")
                    self.img_quick_btn.configure(state="normal")
                    self.img_status_label.configure(text="")
                    self._render_extracted_images(images, url)
                self.after(0, on_done)
            except Exception as exc:
                def on_err():
                    self.img_analyze_btn.configure(state="normal")
                    self.img_quick_btn.configure(state="normal")
                    self.img_status_label.configure(text=f"Error: {exc}")
                    messagebox.showerror("Extraction Error", f"Failed to extract images: {exc}")
                self.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _render_extracted_images(self, images: list[dict], source_url: str) -> None:
        self._current_extracted_images = images
        self._img_card_checkboxes.clear()

        for child in self.img_main_scroll.winfo_children():
            child.destroy()

        if not images:
            warn_card = ctk.CTkFrame(self.img_main_scroll, fg_color=SURFACE, corner_radius=12, border_width=1, border_color=BORDER)
            warn_card.pack(fill="both", expand=True, padx=20, pady=30)
            ctk.CTkLabel(warn_card, text="⚠️", font=ctk.CTkFont(size=36)).pack(pady=(30, 8))
            ctk.CTkLabel(warn_card, text="No Images Found", font=ctk.CTkFont(size=16, weight="bold"), text_color=INK).pack(pady=(0, 4))
            ctk.CTkLabel(warn_card, text="Could not find any photos or carousels at this link.\nIf it's a private Instagram post, make sure to log in via Authorization Settings.", font=ctk.CTkFont(size=12), text_color=MUTED, justify="center").pack(pady=(0, 24))
            return

        # Top Control Bar
        ctrl_bar = ctk.CTkFrame(self.img_main_scroll, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=BORDER)
        ctrl_bar.pack(fill="x", pady=(0, 14))

        left_ctrl = ctk.CTkFrame(ctrl_bar, fg_color="transparent")
        left_ctrl.pack(side="left", padx=16, pady=10)

        ctk.CTkLabel(
            left_ctrl,
            text=f"📷 Found {len(images)} Photo(s) / Slide(s)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=INK,
        ).pack(side="left", padx=(0, 16))

        # Select All checkbox
        self._img_select_all_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            left_ctrl,
            text="Select All",
            variable=self._img_select_all_var,
            font=ctk.CTkFont(size=12),
            command=self._img_toggle_select_all,
            width=18,
            height=18,
        ).pack(side="left")

        # Right Action Buttons
        right_ctrl = ctk.CTkFrame(ctrl_bar, fg_color="transparent")
        right_ctrl.pack(side="right", padx=16, pady=10)

        ctk.CTkButton(
            right_ctrl,
            text=f"Download Selected",
            height=32,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._img_download_selected_from_preview,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            right_ctrl,
            text=f"⬇ Download All ({len(images)})",
            height=32,
            corner_radius=6,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._img_download_all_from_preview(images, source_url),
        ).pack(side="left")

        # Images Grid
        grid_frame = ctk.CTkFrame(self.img_main_scroll, fg_color="transparent")
        grid_frame.pack(fill="both", expand=True)
        columns = 4

        for idx, img_info in enumerate(images):
            row = idx // columns
            col = idx % columns

            card = ctk.CTkFrame(
                grid_frame,
                fg_color=SURFACE,
                border_width=1,
                border_color=BORDER,
                corner_radius=10,
                width=185,
                height=230,
            )
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            card.pack_propagate(False)
            card.grid_propagate(False)

            # Thumbnail Box
            thumb_box = ctk.CTkFrame(card, fg_color=("#E2E8F0", "#0F172A"), corner_radius=8, height=135)
            thumb_box.pack(fill="x", padx=8, pady=(8, 6))
            thumb_box.pack_propagate(False)

            thumb_lbl = ctk.CTkLabel(thumb_box, text="🖼", font=ctk.CTkFont(size=24), text_color=MUTED)
            thumb_lbl.pack(expand=True)

            # Slide Badge
            badge = ctk.CTkLabel(
                thumb_box,
                text=f"#{idx+1}",
                font=ctk.CTkFont(size=9, weight="bold"),
                fg_color=("#DBEAFE", "#1E3A8A"),
                text_color="#2563EB",
                corner_radius=4,
                width=34,
                height=18,
            )
            badge.place(relx=0.06, rely=0.08)

            img_url = img_info.get("url")
            if img_url:
                self._load_async_image_preview(img_url, thumb_lbl, thumb_box)

            check_row = ctk.CTkFrame(card, fg_color="transparent")
            check_row.pack(fill="x", padx=8, pady=(0, 4))

            c_var = ctk.BooleanVar(value=True)
            self._img_card_checkboxes.append((img_info, c_var))

            ctk.CTkCheckBox(
                check_row,
                text=f"Photo {idx+1}",
                variable=c_var,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=INK,
                width=16,
                height=16,
            ).pack(side="left")

            ctk.CTkButton(
                card,
                text="⬇ Save",
                height=26,
                corner_radius=6,
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color=SECONDARY_BTN,
                hover_color=SECONDARY_BTN_HOVER,
                text_color=INK,
                command=lambda item=img_info, i=idx+1: self._img_download_single_image(item, i),
            ).pack(fill="x", side="bottom", padx=8, pady=(0, 8))

    def _load_async_image_preview(self, url: str, label: ctk.CTkLabel, container: ctk.CTkFrame) -> None:
        def fetch():
            try:
                ctk_img = get_remote_image(url, size=(165, 130))
                if ctk_img and label.winfo_exists():
                    label.configure(image=ctk_img, text="")
            except Exception:
                pass
        threading.Thread(target=fetch, daemon=True).start()

    def _img_toggle_select_all(self) -> None:
        val = self._img_select_all_var.get()
        for _, c_var in self._img_card_checkboxes:
            c_var.set(val)

    def _img_download_all_from_preview(self, images: list[dict], source_url: str) -> None:
        if not images:
            return
        dest_dir = self.settings.resolved_download_folder()
        cookie_src = self._get_cookie_source_for_url(source_url)
        p, mid, creator, _ = extract_media_identity(source_url)

        task = DownloadTask(
            url=source_url,
            destination=str(dest_dir),
            quality="Image / Photo",
            cookies_source=cookie_src,
            creator=creator,
            media_id=mid,
            platform=p,
            on_duplicate_prompt=self.prompt_duplicate_confirmation_sync,
        )
        self.empty_state.pack_forget()
        self.tasks[task.id] = task
        item = DownloadItem(
            self.list_frame,
            task,
            self._cancel,
            self._retry,
            self._pause,
            self._resume,
            self._show_task_menu,
        )
        item.pack(fill="x", padx=6, pady=5)
        self.items[task.id] = item
        self.manager.add(task)
        self.show_page("downloads")
        messagebox.showinfo("Downloads Started", f"Queued download of all {len(images)} images! View progress in Downloads.")

    def _img_download_selected_from_preview(self) -> None:
        selected = [item for item, c_var in self._img_card_checkboxes if c_var.get()]
        if not selected:
            messagebox.showwarning("No Selection", "Please check at least one photo to download.")
            return

        dest_dir = self.settings.resolved_download_folder()
        has_mult = len(selected) > 1
        for idx, item in enumerate(selected, 1):
            p, mid, creator, _ = extract_media_identity(item["url"])
            clean_title = sanitize_filename(item.get('title', 'Photo'))
            clean_base_title = re.sub(r"^\d{1,4}[\.\s_-]+\s*", "", clean_title)
            final_img_title = f"{idx:02d}. {clean_base_title or clean_title}" if has_mult else clean_title
            task = DownloadTask(
                url=item["url"],
                destination=str(dest_dir),
                quality="Image / Photo",
                filename=f"{final_img_title}.jpg",
                numbering=idx if has_mult else None,
                creator=creator,
                media_id=mid,
                platform=p,
                on_duplicate_prompt=self.prompt_duplicate_confirmation_sync,
            )
            self.empty_state.pack_forget()
            self.tasks[task.id] = task
            item_widget = DownloadItem(
                self.list_frame,
                task,
                self._cancel,
                self._retry,
                self._pause,
                self._resume,
                self._show_task_menu,
            )
            item_widget.pack(fill="x", padx=6, pady=5)
            self.items[task.id] = item_widget
            self.manager.add(task)

        self.show_page("downloads")
        messagebox.showinfo("Downloads Started", f"Queued {len(selected)} selected image(s) for download!")

    def _img_download_single_image(self, img_info: dict, index: int) -> None:
        dest_dir = self.settings.resolved_download_folder()
        title = sanitize_filename(img_info.get("title") or f"Photo_{index}")
        p, mid, creator, _ = extract_media_identity(img_info["url"])
        task = DownloadTask(
            url=img_info["url"],
            destination=str(dest_dir),
            quality="Image / Photo",
            filename=f"{title}.jpg",
            creator=creator,
            media_id=mid,
            platform=p,
            on_duplicate_prompt=self.prompt_duplicate_confirmation_sync,
        )
        self.empty_state.pack_forget()
        self.tasks[task.id] = task
        item_widget = DownloadItem(
            self.list_frame,
            task,
            self._cancel,
            self._retry,
            self._pause,
            self._resume,
            self._show_task_menu,
        )
        item_widget.pack(fill="x", padx=6, pady=5)
        self.items[task.id] = item_widget
        self.manager.add(task)
        self.show_page("downloads")
        messagebox.showinfo("Download Started", f"Downloading {title}.jpg...")

    def _build_converter_page(self) -> None:
        """Dedicated media converter section for local files with format & resolution selection."""
        self.converter_page = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        self.converter_page.grid_columnconfigure(0, weight=1)

        # Title & Subtitle
        ctk.CTkLabel(
            self.converter_page,
            text="Media Converter",
            text_color=INK,
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(anchor="w", padx=28, pady=(22, 2))

        ctk.CTkLabel(
            self.converter_page,
            text="Convert local videos or audio between formats, or upscale/downscale resolution (up to 8K).",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=28, pady=(0, 16))

        # 1. Source File Selector Card
        file_card = ctk.CTkFrame(self.converter_page, corner_radius=14, fg_color=SURFACE, border_width=1, border_color=BORDER)
        file_card.pack(fill="x", padx=28, pady=(0, 14))
        file_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            file_card,
            text="🎬",
            width=44,
            height=44,
            corner_radius=10,
            fg_color=SECONDARY_BTN,
            font=ctk.CTkFont(size=22),
        ).grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=14)

        self.conv_file_title = ctk.CTkLabel(
            file_card,
            text="No media file selected",
            text_color=INK,
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        )
        self.conv_file_title.grid(row=0, column=1, sticky="ew", pady=(14, 2))

        self.conv_file_subtitle = ctk.CTkLabel(
            file_card,
            text="Choose an MP4, MKV, AVI, MOV, WMV, MP3, WAV, or FLAC file from your computer.",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        )
        self.conv_file_subtitle.grid(row=1, column=1, sticky="ew", pady=(0, 14))

        ctk.CTkButton(
            file_card,
            text="Browse File",
            width=105,
            height=34,
            corner_radius=8,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            command=self._converter_browse_file,
        ).grid(row=0, column=2, rowspan=2, padx=(10, 16), pady=14)

        # 2. Format Selection Card (Inspired by User Screenshot)
        format_card = ctk.CTkFrame(self.converter_page, corner_radius=14, fg_color=SURFACE, border_width=1, border_color=BORDER)
        format_card.pack(fill="x", padx=28, pady=(0, 14))

        self.converter_selected_format = ctk.StringVar(value="MP4")
        self.converter_format_buttons: dict[str, ctk.CTkButton] = {}

        # Video Formats
        ctk.CTkLabel(
            format_card,
            text="Video Formats",
            text_color=INK,
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", padx=20, pady=(18, 10))

        video_formats = [
            "MP4", "Original Video", "HEVC MP4", "MOV",
            "AVI", "FLV", "WMV", "HEVC MKV",
            "MKV", "3GP", "iPhone/iPod", "iPad",
            "Android Phone", "Android Tablets",
        ]

        v_grid = ctk.CTkFrame(format_card, fg_color="transparent")
        v_grid.pack(fill="x", padx=16, pady=(0, 14))
        for col in range(4):
            v_grid.grid_columnconfigure(col, weight=1)

        for i, fmt in enumerate(video_formats):
            btn = ctk.CTkButton(
                v_grid,
                text=f"•  {fmt}",
                height=32,
                corner_radius=8,
                fg_color=BLUE if fmt == "MP4" else SECONDARY_BTN,
                hover_color=BLUE_HOVER if fmt == "MP4" else SECONDARY_BTN_HOVER,
                text_color="#FFFFFF" if fmt == "MP4" else INK,
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda f=fmt: self._select_conv_format(f),
            )
            btn.grid(row=i // 4, column=i % 4, padx=5, pady=4, sticky="ew")
            self.converter_format_buttons[fmt] = btn

        # Audio Formats
        ctk.CTkLabel(
            format_card,
            text="Audio Formats",
            text_color=INK,
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", padx=20, pady=(4, 10))

        audio_formats = [
            "MP3", "Original Audio", "M4A", "WAV",
            "AAC", "FLAC", "OGG", "AIFF",
            "MKA",
        ]

        a_grid = ctk.CTkFrame(format_card, fg_color="transparent")
        a_grid.pack(fill="x", padx=16, pady=(0, 18))
        for col in range(4):
            a_grid.grid_columnconfigure(col, weight=1)

        for i, fmt in enumerate(audio_formats):
            btn = ctk.CTkButton(
                a_grid,
                text=f"•  {fmt}",
                height=32,
                corner_radius=8,
                fg_color=SECONDARY_BTN,
                hover_color=SECONDARY_BTN_HOVER,
                text_color=INK,
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda f=fmt: self._select_conv_format(f),
            )
            btn.grid(row=i // 4, column=i % 4, padx=5, pady=4, sticky="ew")
            self.converter_format_buttons[fmt] = btn

        # 3. Settings & Execution Card
        opts_card = ctk.CTkFrame(self.converter_page, corner_radius=14, fg_color=SURFACE, border_width=1, border_color=BORDER)
        opts_card.pack(fill="x", padx=28, pady=(0, 24))
        opts_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(opts_card, text="Target Resolution:", text_color=INK, font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, padx=(18, 10), pady=(16, 6), sticky="w")
        self.conv_res_var = ctk.StringVar(value="Original")
        self.conv_res_menu = ctk.CTkOptionMenu(
            opts_card,
            values=["Original", "8K (4320p)", "4K (2160p)", "2K / 1440p", "1080p", "720p", "480p", "360p", "240p", "144p"],
            variable=self.conv_res_var,
            width=150,
            height=32,
            corner_radius=8,
        )
        self.conv_res_menu.grid(row=0, column=1, padx=(0, 18), pady=(16, 6), sticky="w")

        # Action row
        action_box = ctk.CTkFrame(opts_card, fg_color="transparent")
        action_box.grid(row=1, column=0, columnspan=2, sticky="ew", padx=18, pady=(10, 14))

        self.conv_start_btn = ctk.CTkButton(
            action_box,
            text="⇄  Convert Now",
            width=140,
            height=36,
            corner_radius=8,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._start_conversion,
        )
        self.conv_start_btn.pack(side="left")

        self.conv_open_btn = ctk.CTkButton(
            action_box,
            text="Open Folder",
            width=120,
            height=36,
            corner_radius=8,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=BLUE,
            state="disabled",
            command=self._open_converted_folder,
        )
        self.conv_open_btn.pack(side="left", padx=10)

        # Progress bar & status
        self.conv_progress = ctk.CTkProgressBar(opts_card, height=6, corner_radius=4, progress_color="#2563EB")
        self.conv_progress.set(0.0)
        self.conv_progress.grid(row=2, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 6))

        self.conv_status_label = ctk.CTkLabel(
            opts_card,
            text="Ready • Select a file and format to convert",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        )
        self.conv_status_label.grid(row=3, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 16))

        self._converter_input_file: str | None = None
        self._converter_output_file: str | None = None

    def _select_conv_format(self, fmt: str) -> None:
        self.converter_selected_format.set(fmt)
        for name, btn in self.converter_format_buttons.items():
            if name == fmt:
                btn.configure(fg_color=BLUE, hover_color=BLUE_HOVER, text_color="#FFFFFF")
            else:
                btn.configure(fg_color=SECONDARY_BTN, hover_color=SECONDARY_BTN_HOVER, text_color=INK)

    def _converter_browse_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select video or audio to convert",
            filetypes=[
                ("Media Files", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.3gp *.webm *.mp3 *.m4a *.wav *.aac *.flac *.ogg"),
                ("All files", "*.*"),
            ],
        )
        if selected:
            self._converter_input_file = selected
            p = Path(selected)
            self.conv_file_title.configure(text=p.name)
            try:
                size_str = format_bytes(os.path.getsize(selected))
                self.conv_file_subtitle.configure(text=f"Path: {p}  •  Size: {size_str}")
            except OSError:
                self.conv_file_subtitle.configure(text=f"Path: {p}")
            self.conv_status_label.configure(text="File loaded. Click 'Convert Now' to start.")
            self.conv_progress.set(0.0)
            self.conv_open_btn.configure(state="disabled")

    def _start_conversion(self) -> None:
        if not self._converter_input_file or not Path(self._converter_input_file).is_file():
            messagebox.showwarning("No File", "Please select a media file first using 'Browse File'.")
            return

        target_fmt = self.converter_selected_format.get()
        target_res = self.conv_res_var.get()
        out_dir = str(self.settings.resolved_download_folder())

        self.conv_start_btn.configure(state="disabled")
        self.conv_open_btn.configure(state="disabled")
        self.conv_progress.set(0.2)
        self.conv_status_label.configure(text=f"Converting to {target_fmt} ({target_res})... Please wait.")

        def run_thread():
            try:
                out_path = convert_media(
                    input_path=self._converter_input_file,
                    output_dir=out_dir,
                    target_format=target_fmt,
                    target_resolution=target_res,
                )
                self._converter_output_file = out_path

                def on_done():
                    self.conv_progress.set(1.0)
                    self.conv_status_label.configure(
                        text=f"✓ Conversion completed! Saved as: {Path(out_path).name}"
                    )
                    self.conv_start_btn.configure(state="normal")
                    self.conv_open_btn.configure(state="normal")

                self.after(0, on_done)
            except Exception as exc:
                def on_err(err_text=str(exc)):
                    self.conv_progress.set(0.0)
                    self.conv_status_label.configure(text=f"Error during conversion: {err_text}")
                    self.conv_start_btn.configure(state="normal")
                    messagebox.showerror("Conversion Failed", f"Could not convert file:\n{err_text}")

                self.after(0, on_err)

        threading.Thread(target=run_thread, daemon=True).start()

    def _open_converted_folder(self) -> None:
        if self._converter_output_file:
            folder = str(Path(self._converter_output_file).parent)
            try:
                os.startfile(folder)
            except Exception:
                pass

    def _build_channel_hub_page(self) -> None:
        self.channel_hub_page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.channel_hub_page.grid_columnconfigure(0, weight=1)
        self.channel_hub_page.grid_rowconfigure(1, weight=1)

        self._current_catalog: dict | None = None

        # 1. Top Search Header Card (EaseUS style)
        search_card = ctk.CTkFrame(self.channel_hub_page, corner_radius=14, fg_color=SURFACE, border_width=1, border_color=BORDER)
        search_card.grid(row=0, column=0, sticky="ew", padx=28, pady=(20, 12))
        search_card.grid_columnconfigure(1, weight=1)

        # Creator / YouTube logo badge
        yt_badge_icon = self._get_icon("plat_youtube.png", (24, 24))
        badge = ctk.CTkLabel(
            search_card,
            image=yt_badge_icon,
            text="",
            width=38,
            height=38,
            corner_radius=10,
            fg_color=("#FEE2E2", "#3A1719"),
        )
        badge.grid(row=0, column=0, padx=(16, 10), pady=12)

        self.channel_search_var = ctk.StringVar()
        self.channel_search_entry = ctk.CTkEntry(
            search_card,
            textvariable=self.channel_search_var,
            placeholder_text="Enter @username, channel link, or TikTok creator (e.g. @browntownmusic, @tseries)...",
            height=38,
            border_color=BORDER,
            fg_color=BACKGROUND,
            text_color=INK,
        )
        self.channel_search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=12)
        self.channel_search_entry.bind("<Return>", lambda _: self._explore_channel())

        def paste_search():
            try:
                clip = self.clipboard_get().strip()
                if clip:
                    self.channel_search_var.set(clip)
                    self._explore_channel()
            except Exception:
                pass

        ctk.CTkButton(
            search_card,
            text="Paste",
            width=65,
            height=38,
            corner_radius=8,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=BLUE,
            command=paste_search,
        ).grid(row=0, column=2, padx=(0, 8), pady=12)

        self.explore_btn = ctk.CTkButton(
            search_card,
            text="Explore Channel 🔍",
            width=150,
            height=38,
            corner_radius=8,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._explore_channel,
        )
        self.explore_btn.grid(row=0, column=3, padx=(0, 16), pady=12)

        # Status label under search bar (no suggestion chips)
        self.channel_hub_status = ctk.CTkLabel(search_card, text="", text_color=MUTED, font=ctk.CTkFont(size=11))
        self.channel_hub_status.grid(row=1, column=0, columnspan=4, sticky="w", padx=16, pady=(0, 8))

        # 2. Middle Content Container
        self.channel_main_container = ctk.CTkFrame(self.channel_hub_page, fg_color="transparent")
        self.channel_main_container.grid(row=1, column=0, sticky="nsew", padx=28, pady=(0, 10))
        self.channel_main_container.grid_columnconfigure(0, weight=1)
        self.channel_main_container.grid_rowconfigure(0, weight=1)

        # 2A. Initial Welcome / Empty state (like EaseUS Image 4)
        self.channel_welcome_frame = ctk.CTkFrame(self.channel_main_container, fg_color="transparent")
        self.channel_welcome_frame.grid(row=0, column=0, sticky="nsew")

        welcome_card = ctk.CTkFrame(self.channel_welcome_frame, corner_radius=16, fg_color=SURFACE, border_width=1, border_color=BORDER)
        welcome_card.pack(fill="x", pady=40, padx=20)

        yt_center_icon = self._get_icon("plat_youtube.png", (48, 48))
        if yt_center_icon:
            ctk.CTkLabel(
                welcome_card,
                image=yt_center_icon,
                text="",
            ).pack(pady=(36, 0))

        ctk.CTkLabel(
            welcome_card,
            text="Search for your favourite creators for quick downloads!",
            text_color=INK,
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(pady=(16 if yt_center_icon else 36, 6))

        ctk.CTkLabel(
            welcome_card,
            text="Browse full creator catalogs, inspect playlist contents, or download entire channels in 1-click!\nEnter @username or paste a channel link above to begin.",
            text_color=MUTED,
            font=ctk.CTkFont(size=13),
            justify="center",
        ).pack(pady=(0, 24))

        # 2B. Results Scrollable Frame
        self.channel_results_frame = ctk.CTkScrollableFrame(self.channel_main_container, fg_color="transparent")
        self.channel_results_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        # 3. Bottom Channel Stats Bar (like EaseUS Image 3)
        self.channel_stats_bar = ctk.CTkFrame(self.channel_hub_page, height=58, corner_radius=12, fg_color=SURFACE, border_width=1, border_color=BORDER)

    def _explore_channel(self, channel_override: str | None = None) -> None:
        raw_val = channel_override if channel_override else self.channel_search_var.get().strip()
        if not raw_val:
            messagebox.showwarning("Enter Channel", "Please enter a creator @username or channel URL.")
            return

        self.channel_search_var.set(raw_val)
        self.explore_btn.configure(state="disabled")
        self.channel_hub_status.configure(text="Analyzing creator channel & playlists... Please wait.")
        cookie_src = self.settings.authorized_accounts.get("youtube") or self.settings.authorized_accounts.get("google")

        def worker():
            try:
                catalog = fetch_channel_catalog(raw_val, cookies_source=cookie_src)

                def on_done():
                    self.explore_btn.configure(state="normal")
                    self.channel_hub_status.configure(text="")
                    self._current_catalog = catalog
                    self._render_channel_catalog(catalog)

                self.after(0, on_done)
            except Exception as exc:
                def on_err(err_text=str(exc)):
                    self.explore_btn.configure(state="normal")
                    self.channel_hub_status.configure(text=f"Error: {err_text[:40]}")
                    messagebox.showerror("Search Failed", f"Could not load channel catalog:\n{err_text}")

                self.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _render_channel_catalog(self, catalog: dict) -> None:
        self.channel_welcome_frame.grid_forget()
        self.channel_results_frame.grid(row=0, column=0, sticky="nsew")

        # Clear existing cards
        for widget in self.channel_results_frame.winfo_children():
            widget.destroy()

        playlists = catalog.get("playlists", [])
        total_pls = len(playlists)

        # Card 0: "All Files" Blue Folder Card
        total_vid_text = f"{catalog.get('estimated_videos')} videos" if catalog.get('estimated_videos') else "All Videos"
        folder_card = FolderCard(
            self.channel_results_frame,
            title="All Files",
            subtitle=total_vid_text,
            on_view=self._on_view_all_files,
            on_download=self._on_download_all_files,
        )
        folder_card.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")

        # Card 1: "⚡ Shorts" Red Folder Card (if available)
        start_idx = 1
        if catalog.get("all_shorts_url"):
            shorts_card = FolderCard(
                self.channel_results_frame,
                title="⚡ Shorts",
                subtitle="YouTube Shorts",
                on_view=self._on_view_all_shorts,
                on_download=self._on_download_all_shorts,
                icon="⚡",
                icon_color="#DC2626",
                folder_bg=("#FEE2E2", "#3A1719"),
            )
            shorts_card.grid(row=0, column=1, padx=8, pady=8, sticky="nsew")
            start_idx = 2

        # Cards start_idx..N: Playlist Cards
        for i, pl in enumerate(playlists):
            idx = start_idx + i
            row = idx // 4
            col = idx % 4
            pl_card = PlaylistCard(
                self.channel_results_frame,
                playlist_data=pl,
                on_view=self._on_view_playlist_card,
                on_download=self._on_download_playlist_card,
            )
            pl_card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

        # Setup & show Bottom Stats Bar
        self.channel_stats_bar.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 16))
        for child in self.channel_stats_bar.winfo_children():
            child.destroy()

        left_info = ctk.CTkFrame(self.channel_stats_bar, fg_color="transparent")
        left_info.pack(side="left", padx=16, pady=8)

        # Channel avatar placeholder
        avatar_lbl = ctk.CTkLabel(left_info, text="👤", width=38, height=38, corner_radius=19, fg_color=SECONDARY_BTN, font=ctk.CTkFont(size=18))
        avatar_lbl.pack(side="left", padx=(0, 10))

        if catalog.get("avatar_url"):
            def load_avatar(url=catalog["avatar_url"], lbl=avatar_lbl):
                img = get_remote_image(url, size=(38, 38))
                if img:
                    def apply_avatar():
                        if lbl.winfo_exists():
                            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(38, 38))
                            lbl.configure(image=ctk_img, text="")
                    self.after(0, apply_avatar)
            threading.Thread(target=load_avatar, daemon=True).start()

        name_box = ctk.CTkFrame(left_info, fg_color="transparent")
        name_box.pack(side="left")

        ctk.CTkLabel(name_box, text=catalog.get("channel_title", "Creator"), font=ctk.CTkFont(size=13, weight="bold"), text_color=INK, anchor="w").pack(anchor="w")
        ctk.CTkLabel(name_box, text=catalog.get("handle", ""), font=ctk.CTkFont(size=11), text_color=MUTED, anchor="w").pack(anchor="w")

        # Middle stats badges
        badges_box = ctk.CTkFrame(self.channel_stats_bar, fg_color="transparent")
        badges_box.pack(side="left", padx=24)

        ctk.CTkLabel(badges_box, text=f"📁 Playlists: {total_pls}", font=ctk.CTkFont(size=12, weight="bold"), text_color=BLUE).pack(side="left", padx=10)
        est_vids = f"🎬 Videos: {catalog.get('estimated_videos')}" if catalog.get('estimated_videos') else "🎬 Full Catalog"
        ctk.CTkLabel(badges_box, text=est_vids, font=ctk.CTkFont(size=12, weight="bold"), text_color=MUTED).pack(side="left", padx=10)

        # Right actions & quality selector
        right_box = ctk.CTkFrame(self.channel_stats_bar, fg_color="transparent")
        right_box.pack(side="right", padx=16, pady=8)

        ctk.CTkLabel(right_box, text="Quality:", font=ctk.CTkFont(size=11), text_color=MUTED).pack(side="left", padx=(0, 6))
        self.channel_hub_quality_var = ctk.StringVar(value=self.quality_var.get())
        ctk.CTkOptionMenu(right_box, values=QUALITY_OPTIONS, variable=self.channel_hub_quality_var, width=135, height=32).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            right_box,
            text="Download All Playlists ⬇",
            height=32,
            corner_radius=8,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._download_all_channel_playlists,
        ).pack(side="left")

    def _queue_batch_with_numbering(self, items: list[dict], quality: str) -> None:
        if not self._check_device_not_banned():
            return
        if not items:
            return

        # Enforce free daily limit if applicable
        can_dl, _ = license_mgr.can_download(len(items))
        if not can_dl:
            LicenseDialog(self, is_limit_reached=True, on_status_changed=self._update_pro_badge_ui)
            return

        self.empty_state.pack_forget()
        dest_folder = str(self.settings.resolved_download_folder())
        speed_val = getattr(self, "speed_var", None)
        speed_str = speed_val.get() if speed_val else self.settings.default_speed_limit
        speed_limit = parse_speed_limit(speed_str)

        # Determine creator context from active catalogs if available
        creator = ""
        if getattr(self, "_current_catalog", None):
            creator = self._current_catalog.get("handle") or self._current_catalog.get("channel_title") or ""
        elif getattr(self, "_current_tiktok_catalog", None):
            creator = self._current_tiktok_catalog.get("handle") or self._current_tiktok_catalog.get("channel_title") or ""
        elif getattr(self, "_current_ig_catalog", None):
            creator = self._current_ig_catalog.get("handle") or self._current_ig_catalog.get("channel_title") or ""

        # Check for duplicates in history and on disk
        duplicates = []
        for it in items:
            u = it.get("url") or it.get("webpage_url") or it.get("original_url") or ""
            if not u:
                continue
            title = it.get("title", "")
            rec = history_store.find_duplicate(url=u, creator=creator, title=title, check_disk=True)
            if rec:
                duplicates.append((it, rec))

        items_to_queue: list[tuple[dict, bool]] = []
        if duplicates:
            dup_dicts = []
            for it, rec in duplicates:
                u_item = it.get("url") or it.get("webpage_url") or it.get("original_url") or ""
                dup_dicts.append({
                    "url": u_item,
                    "title": rec.title or it.get("title", "Untitled"),
                    "creator": rec.creator or creator or "Unknown",
                    "filepath": rec.saved_filepath,
                })

            decision_result = ["skip", []]
            def on_decision(dec, sel):
                decision_result[0] = dec
                decision_result[1] = sel

            dialog = BatchDuplicateDialog(self, dup_dicts, on_decision)
            self.wait_window(dialog)
            dec, sel = decision_result[0], decision_result[1]

            dup_urls_map = {it.get("url") or it.get("webpage_url") or it.get("original_url"): True for it, _ in duplicates}
            selected_urls = {d["url"] for d in sel} if dec == "download_selected" else set()
            for it in items:
                u_it = it.get("url") or it.get("webpage_url") or it.get("original_url")
                if u_it in dup_urls_map:
                    if dec == "download_all" or (dec == "download_selected" and u_it in selected_urls):
                        items_to_queue.append((it, True))
                else:
                    items_to_queue.append((it, False))
        else:
            for it in items:
                items_to_queue.append((it, False))

        if not items_to_queue:
            messagebox.showinfo("No Downloads Queued", "All duplicate videos were skipped.")
            return

        license_mgr.record_downloads(len(items_to_queue))
        self._update_pro_badge_ui()

        for num, (item, is_dup) in enumerate(items_to_queue, 1):
            item_url = item.get("url") or item.get("webpage_url") or item.get("original_url") or ""
            if not item_url:
                continue
            original_title = sanitize_filename(item.get("title", "Video"))
            cookie_src = self._get_cookie_source_for_url(item_url)
            p, mid, c_meta, _ = extract_media_identity(item_url)
            item_creator = creator or c_meta

            # Clean any pre-existing numbering to avoid duplicate prefixes
            clean_base_title = re.sub(r"^\d{1,4}[\.\s_-]+\s*", "", original_title)
            numbered_title = f"{num:02d}. {clean_base_title or original_title}"

            task = DownloadTask(
                url=item_url,
                destination=dest_folder,
                quality=quality,
                speed_limit_bps=speed_limit,
                filename=numbered_title,
                numbering=num,
                cookies_source=cookie_src,
                creator=item_creator,
                media_id=mid,
                platform=p,
                is_duplicate_copy=is_dup,
                on_duplicate_prompt=self.prompt_duplicate_confirmation_sync,
            )
            self.tasks[task.id] = task
            item_widget = DownloadItem(
                self.list_frame,
                task,
                self._cancel,
                self._retry,
                self._pause,
                self._resume,
                self._show_task_menu,
            )
            item_widget.pack(fill="x", padx=6, pady=5)
            self.items[task.id] = item_widget
            self.manager.add(task)
            if num % 25 == 0:
                self.update_idletasks()

        self._filter_task_list()

    def _on_view_all_files(self) -> None:
        if not self._current_catalog:
            return
        target_url = self._current_catalog["all_videos_url"]
        self.channel_hub_status.configure(text="Loading all videos for selection... Please wait.")

        def worker():
            try:
                title, entries = fetch_playlist_info(target_url, max_items=0, mode="all_videos")
                def on_done():
                    self.channel_hub_status.configure(text="")
                    if not entries:
                        messagebox.showwarning("No Videos", "Could not load videos from this channel.")
                        return
                    VideoGridModal(
                        self,
                        title=f"All Files - {self._current_catalog['channel_title']}",
                        videos=entries,
                        on_download_selected=lambda chosen: (
                            self._queue_batch_with_numbering(chosen, self.channel_hub_quality_var.get()),
                            self.show_page("downloads"),
                            messagebox.showinfo("Downloads Started", f"Queued {len(chosen)} video(s)!")
                        ),
                    )
                self.after(0, on_done)
            except Exception as e:
                self.after(0, lambda: self.channel_hub_status.configure(text=""))
                self.after(0, lambda: messagebox.showerror("Error", f"Failed to load videos: {str(e)}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_download_all_files(self) -> None:
        if not self._current_catalog:
            return
        target_url = self._current_catalog["all_videos_url"]
        self.channel_hub_status.configure(text="Queuing all channel videos... Please wait.")

        def worker():
            try:
                title, entries = fetch_playlist_info(target_url, max_items=0, mode="all_videos")
                def on_done():
                    self.channel_hub_status.configure(text="")
                    if not entries:
                        messagebox.showwarning("No Videos", "No videos found to download.")
                        return
                    self._queue_batch_with_numbering(entries, self.channel_hub_quality_var.get())
                    self.show_page("downloads")
                    messagebox.showinfo("Downloads Started", f"Queued {len(entries)} channel videos with sequential numbering (01, 02, 03...)!")
                self.after(0, on_done)
            except Exception as e:
                self.after(0, lambda: self.channel_hub_status.configure(text=""))
                self.after(0, lambda: messagebox.showerror("Error", f"Failed to queue videos: {str(e)}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_view_all_shorts(self) -> None:
        if not self._current_catalog:
            return
        target_url = self._current_catalog.get("all_shorts_url") or self._current_catalog["all_videos_url"]
        self.channel_hub_status.configure(text="Loading YouTube Shorts... Please wait.")

        def worker():
            try:
                title, entries = fetch_playlist_info(target_url, max_items=0)
                shorts_entries = [e for e in entries if e.get("media_type") == "short" or "/shorts/" in str(e.get("url", ""))]
                if not shorts_entries:
                    shorts_entries = entries
                def on_done():
                    self.channel_hub_status.configure(text="")
                    if not shorts_entries:
                        messagebox.showwarning("No Shorts", "No YouTube Shorts found for this channel.")
                        return
                    VideoGridModal(
                        self,
                        title=f"⚡ Shorts - {self._current_catalog['channel_title']}",
                        videos=shorts_entries,
                        on_download_selected=lambda chosen: (
                            self._queue_batch_with_numbering(chosen, self.channel_hub_quality_var.get()),
                            self.show_page("downloads"),
                            messagebox.showinfo("Downloads Started", f"Queued {len(chosen)} Short(s)!")
                        ),
                    )
                self.after(0, on_done)
            except Exception as e:
                self.after(0, lambda: self.channel_hub_status.configure(text=""))
                self.after(0, lambda: messagebox.showerror("Error", f"Failed to load Shorts: {str(e)}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_download_all_shorts(self) -> None:
        if not self._current_catalog:
            return
        target_url = self._current_catalog.get("all_shorts_url") or self._current_catalog["all_videos_url"]
        self.channel_hub_status.configure(text="Queuing all channel Shorts... Please wait.")

        def worker():
            try:
                title, entries = fetch_playlist_info(target_url, max_items=0)
                shorts_entries = [e for e in entries if e.get("media_type") == "short" or "/shorts/" in str(e.get("url", ""))]
                if not shorts_entries:
                    shorts_entries = entries
                def on_done():
                    self.channel_hub_status.configure(text="")
                    if not shorts_entries:
                        messagebox.showwarning("No Shorts", "No Shorts found to download.")
                        return
                    self._queue_batch_with_numbering(shorts_entries, self.channel_hub_quality_var.get())
                    self.show_page("downloads")
                    messagebox.showinfo("Downloads Started", f"Queued {len(shorts_entries)} Shorts!")
                self.after(0, on_done)
            except Exception as e:
                self.after(0, lambda: self.channel_hub_status.configure(text=""))
                self.after(0, lambda: messagebox.showerror("Error", f"Failed to queue Shorts: {str(e)}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_view_playlist_card(self, pl_data: dict) -> None:
        if pl_data.get("videos"):
            VideoGridModal(
                self,
                title=pl_data.get("title", "Playlist"),
                videos=pl_data["videos"],
                on_download_selected=lambda chosen: (
                    self._queue_batch_with_numbering(chosen, self.channel_hub_quality_var.get()),
                    self.show_page("downloads"),
                    messagebox.showinfo("Downloads Started", f"Queued {len(chosen)} video(s)!")
                ),
            )
            return

        self.channel_hub_status.configure(text=f"Loading playlist '{pl_data['title'][:25]}'...")

        def worker():
            try:
                title, entries = fetch_playlist_info(pl_data["url"], max_items=0)
                pl_data["videos"] = entries
                def on_done():
                    self.channel_hub_status.configure(text="")
                    if not entries:
                        messagebox.showwarning("No Videos", "No videos found in this playlist.")
                        return
                    VideoGridModal(
                        self,
                        title=pl_data.get("title", "Playlist"),
                        videos=entries,
                        on_download_selected=lambda chosen: (
                            self._queue_batch_with_numbering(chosen, self.channel_hub_quality_var.get()),
                            self.show_page("downloads"),
                            messagebox.showinfo("Downloads Started", f"Queued {len(chosen)} video(s)!")
                        ),
                    )
                self.after(0, on_done)
            except Exception as e:
                self.after(0, lambda: self.channel_hub_status.configure(text=""))
                self.after(0, lambda: messagebox.showerror("Error", f"Could not load playlist: {str(e)}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_download_playlist_card(self, pl_data: dict) -> None:
        self.channel_hub_status.configure(text=f"Queuing playlist '{pl_data['title'][:25]}'...")

        def worker():
            try:
                entries = pl_data.get("videos")
                if not entries:
                    _, entries = fetch_playlist_info(pl_data["url"], max_items=0)
                    pl_data["videos"] = entries

                def on_done():
                    self.channel_hub_status.configure(text="")
                    if not entries:
                        messagebox.showwarning("No Videos", "No videos found in this playlist.")
                        return
                    self._queue_batch_with_numbering(entries, self.channel_hub_quality_var.get())
                    self.show_page("downloads")
                    messagebox.showinfo("Downloads Started", f"Queued {len(entries)} videos from '{pl_data['title']}' with sequential numbering (01, 02, 03...)!")
                self.after(0, on_done)
            except Exception as e:
                self.after(0, lambda: self.channel_hub_status.configure(text=""))
                self.after(0, lambda: messagebox.showerror("Error", f"Failed to download playlist: {str(e)}"))

        threading.Thread(target=worker, daemon=True).start()

    def _download_all_channel_playlists(self) -> None:
        if not self._current_catalog:
            return
        playlists = self._current_catalog.get("playlists", [])
        if not playlists:
            messagebox.showwarning("No Playlists", "No playlists available to download.")
            return

        self.channel_hub_status.configure(text="Gathering all playlist videos... Please wait.")

        def worker():
            all_videos = []
            for pl in playlists:
                vids = pl.get("videos")
                if not vids:
                    try:
                        _, vids = fetch_playlist_info(pl["url"], max_items=0)
                        pl["videos"] = vids
                    except Exception:
                        vids = []
                all_videos.extend(vids)

            def on_done():
                self.channel_hub_status.configure(text="")
                if not all_videos:
                    messagebox.showwarning("No Videos", "No videos found in the playlists.")
                    return
                self._queue_batch_with_numbering(all_videos, self.channel_hub_quality_var.get())
                self.show_page("downloads")
                messagebox.showinfo(
                    "Downloads Started",
                    f"Queued {len(all_videos)} videos across {len(playlists)} playlist(s) with sequential numbering (01, 02, 03...)!",
                )

            self.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _build_tiktok_hub_page(self) -> None:
        self.tiktok_hub_page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.tiktok_hub_page.grid_columnconfigure(0, weight=1)
        self.tiktok_hub_page.grid_rowconfigure(1, weight=1)

        self._current_tiktok_catalog: dict | None = None

        # 1. Search Header Card
        search_card = ctk.CTkFrame(self.tiktok_hub_page, corner_radius=14, fg_color=SURFACE, border_width=1, border_color=BORDER)
        search_card.grid(row=0, column=0, sticky="ew", padx=28, pady=(20, 12))
        search_card.grid_columnconfigure(1, weight=1)

        # TikTok Badge
        tt_badge_icon = self._get_icon("plat_tiktok.png", (24, 24))
        badge = ctk.CTkLabel(
            search_card,
            image=tt_badge_icon,
            text="",
            width=38,
            height=38,
            corner_radius=10,
            fg_color=("#E0F2FE", "#10283B"),
        )
        badge.grid(row=0, column=0, padx=(16, 10), pady=12)

        self.tiktok_search_var = ctk.StringVar()
        self.tiktok_search_entry = ctk.CTkEntry(
            search_card,
            textvariable=self.tiktok_search_var,
            placeholder_text="Enter TikTok @username or collection link (e.g. @asmrberlinn)...",
            height=38,
            border_color=BORDER,
            fg_color=BACKGROUND,
            text_color=INK,
        )
        self.tiktok_search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=12)
        self.tiktok_search_entry.bind("<Return>", lambda _: self._explore_tiktok())

        def paste_tiktok_search():
            try:
                clip = self.clipboard_get().strip()
                if clip:
                    self.tiktok_search_var.set(clip)
                    self._explore_tiktok()
            except Exception:
                pass

        ctk.CTkButton(
            search_card,
            text="Paste",
            width=65,
            height=38,
            corner_radius=8,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=BLUE,
            command=paste_tiktok_search,
        ).grid(row=0, column=2, padx=(0, 8), pady=12)

        self.tiktok_explore_btn = ctk.CTkButton(
            search_card,
            text="Explore TikTok 🔍",
            width=150,
            height=38,
            corner_radius=8,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._explore_tiktok,
        )
        self.tiktok_explore_btn.grid(row=0, column=3, padx=(0, 16), pady=12)

        # Status label under search bar (no suggestion chips)
        self.tiktok_hub_status = ctk.CTkLabel(search_card, text="", text_color=MUTED, font=ctk.CTkFont(size=11))
        self.tiktok_hub_status.grid(row=1, column=0, columnspan=4, sticky="w", padx=16, pady=(0, 8))

        # 2. Main Content Container
        self.tiktok_main_container = ctk.CTkFrame(self.tiktok_hub_page, fg_color="transparent")
        self.tiktok_main_container.grid(row=1, column=0, sticky="nsew", padx=28, pady=(0, 10))
        self.tiktok_main_container.grid_columnconfigure(0, weight=1)
        self.tiktok_main_container.grid_rowconfigure(0, weight=1)

        # 2A. Welcome State
        self.tiktok_welcome_frame = ctk.CTkFrame(self.tiktok_main_container, fg_color="transparent")
        self.tiktok_welcome_frame.grid(row=0, column=0, sticky="nsew")

        welcome_card = ctk.CTkFrame(self.tiktok_welcome_frame, corner_radius=16, fg_color=SURFACE, border_width=1, border_color=BORDER)
        welcome_card.pack(fill="x", pady=40, padx=20)

        tt_center_icon = self._get_icon("plat_tiktok.png", (48, 48))
        if tt_center_icon:
            ctk.CTkLabel(
                welcome_card,
                image=tt_center_icon,
                text="",
            ).pack(pady=(36, 0))

        ctk.CTkLabel(
            welcome_card,
            text="Explore & Download TikTok Creators & Collections",
            text_color=INK,
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(pady=(16 if tt_center_icon else 36, 6))

        ctk.CTkLabel(
            welcome_card,
            text="Download full creator catalogs without watermarks, inspect playlist contents,\nor download all videos in 1-click!\nEnter a TikTok @username or playlist URL above to begin.",
            text_color=MUTED,
            font=ctk.CTkFont(size=13),
            justify="center",
        ).pack(pady=(0, 24))

        # 2B. Results Scrollable Frame
        self.tiktok_results_frame = ctk.CTkScrollableFrame(self.tiktok_main_container, fg_color="transparent")
        self.tiktok_results_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        # 3. Bottom TikTok Stats Bar
        self.tiktok_stats_bar = ctk.CTkFrame(self.tiktok_hub_page, height=58, corner_radius=12, fg_color=SURFACE, border_width=1, border_color=BORDER)

    def _explore_tiktok(self) -> None:
        raw_val = self.tiktok_search_var.get().strip()
        if not raw_val:
            messagebox.showwarning("Enter TikTok Creator", "Please enter a TikTok @username or collection link.")
            return

        self.tiktok_explore_btn.configure(state="disabled")
        self.tiktok_hub_status.configure(text="Analyzing TikTok creator & videos... Please wait.")
        cookie_src = self.settings.authorized_accounts.get("tiktok")

        def worker():
            try:
                catalog = fetch_channel_catalog(raw_val, platform="tiktok", cookies_source=cookie_src)

                def on_done():
                    self.tiktok_explore_btn.configure(state="normal")
                    self.tiktok_hub_status.configure(text="")
                    self._current_tiktok_catalog = catalog
                    self._render_tiktok_catalog(catalog)

                self.after(0, on_done)
            except Exception as exc:
                def on_err(err_text=str(exc)):
                    self.tiktok_explore_btn.configure(state="normal")
                    self.tiktok_hub_status.configure(text=f"Error: {err_text[:40]}")
                    messagebox.showerror("Search Failed", f"Could not load TikTok creator:\n{err_text}")

                self.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _render_tiktok_catalog(self, catalog: dict) -> None:
        self.tiktok_welcome_frame.grid_forget()
        self.tiktok_results_frame.grid(row=0, column=0, sticky="nsew")

        for widget in self.tiktok_results_frame.winfo_children():
            widget.destroy()

        playlists = catalog.get("playlists", [])

        # Card 0: "All Videos" Folder Card
        total_vid_text = f"{catalog.get('estimated_videos')} videos" if catalog.get('estimated_videos') else "All Videos"
        folder_card = FolderCard(
            self.tiktok_results_frame,
            title="All Videos",
            subtitle=total_vid_text,
            on_view=self._on_view_all_tiktok,
            on_download=self._on_download_all_tiktok,
        )
        folder_card.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")

        # Cards 1..N: Collection Cards
        for idx, pl in enumerate(playlists, 1):
            row = idx // 4
            col = idx % 4
            pl_card = PlaylistCard(
                self.tiktok_results_frame,
                playlist_data=pl,
                on_view=self._on_view_tiktok_playlist,
                on_download=self._on_download_tiktok_playlist,
            )
            pl_card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

        # Bottom Bar
        self.tiktok_stats_bar.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 16))
        for child in self.tiktok_stats_bar.winfo_children():
            child.destroy()

        left_info = ctk.CTkFrame(self.tiktok_stats_bar, fg_color="transparent")
        left_info.pack(side="left", padx=16, pady=8)

        avatar_lbl = ctk.CTkLabel(left_info, text="♪", width=38, height=38, corner_radius=19, fg_color=SECONDARY_BTN, font=ctk.CTkFont(size=18, weight="bold"), text_color="#0284C7")
        avatar_lbl.pack(side="left", padx=(0, 10))

        name_box = ctk.CTkFrame(left_info, fg_color="transparent")
        name_box.pack(side="left")

        ctk.CTkLabel(name_box, text=catalog.get("channel_title", "TikTok Creator"), font=ctk.CTkFont(size=13, weight="bold"), text_color=INK, anchor="w").pack(anchor="w")
        ctk.CTkLabel(name_box, text=catalog.get("handle", ""), font=ctk.CTkFont(size=11), text_color=MUTED, anchor="w").pack(anchor="w")

        # Middle stats
        badges_box = ctk.CTkFrame(self.tiktok_stats_bar, fg_color="transparent")
        badges_box.pack(side="left", padx=24)

        est_vids = f"🎬 {catalog.get('estimated_videos')} Videos" if catalog.get('estimated_videos') else "🎬 Full Profile"
        ctk.CTkLabel(badges_box, text=est_vids, font=ctk.CTkFont(size=12, weight="bold"), text_color=BLUE).pack(side="left", padx=10)

        # Right actions
        right_box = ctk.CTkFrame(self.tiktok_stats_bar, fg_color="transparent")
        right_box.pack(side="right", padx=16, pady=8)

        ctk.CTkLabel(right_box, text="Quality:", font=ctk.CTkFont(size=11), text_color=MUTED).pack(side="left", padx=(0, 6))
        self.tiktok_hub_quality_var = ctk.StringVar(value=self.quality_var.get())
        ctk.CTkOptionMenu(right_box, values=QUALITY_OPTIONS, variable=self.tiktok_hub_quality_var, width=135, height=32).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            right_box,
            text="Download All Videos ⬇",
            height=32,
            corner_radius=8,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_download_all_tiktok,
        ).pack(side="left")

    def _on_view_all_tiktok(self) -> None:
        if not self._current_tiktok_catalog:
            return
        target_url = self._current_tiktok_catalog["all_videos_url"]
        self.tiktok_hub_status.configure(text="Loading TikTok videos for selection... Please wait.")

        def worker():
            try:
                title, entries = fetch_playlist_info(target_url, max_items=0, mode="all_videos")
                def on_done():
                    self.tiktok_hub_status.configure(text="")
                    if not entries:
                        messagebox.showwarning("No Videos", "Could not load videos from this TikTok profile.")
                        return
                    VideoGridModal(
                        self,
                        title=f"TikTok - {self._current_tiktok_catalog['channel_title']}",
                        videos=entries,
                        on_download_selected=lambda chosen: (
                            self._queue_batch_with_numbering(chosen, self.tiktok_hub_quality_var.get()),
                            self.show_page("downloads"),
                            messagebox.showinfo("Downloads Started", f"Queued {len(chosen)} video(s)!")
                        ),
                    )
                self.after(0, on_done)
            except Exception as e:
                self.after(0, lambda: self.tiktok_hub_status.configure(text=""))
                self.after(0, lambda: messagebox.showerror("Error", f"Failed to load TikTok videos: {str(e)}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_download_all_tiktok(self) -> None:
        if not self._current_tiktok_catalog:
            return
        target_url = self._current_tiktok_catalog["all_videos_url"]
        self.tiktok_hub_status.configure(text="Queuing all TikTok videos... Please wait.")

        def worker():
            try:
                title, entries = fetch_playlist_info(target_url, max_items=0, mode="all_videos")
                def on_done():
                    self.tiktok_hub_status.configure(text="")
                    if not entries:
                        messagebox.showwarning("No Videos", "No videos found to download.")
                        return
                    self._queue_batch_with_numbering(entries, self.tiktok_hub_quality_var.get())
                    self.show_page("downloads")
                    messagebox.showinfo("Downloads Started", f"Queued {len(entries)} TikTok videos with sequential numbering (01, 02, 03...)!")
                self.after(0, on_done)
            except Exception as e:
                self.after(0, lambda: self.tiktok_hub_status.configure(text=""))
                self.after(0, lambda: messagebox.showerror("Error", f"Failed to queue TikTok videos: {str(e)}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_view_tiktok_playlist(self, pl_data: dict) -> None:
        if pl_data.get("videos"):
            VideoGridModal(
                self,
                title=pl_data.get("title", "Collection"),
                videos=pl_data["videos"],
                on_download_selected=lambda chosen: (
                    self._queue_batch_with_numbering(chosen, self.tiktok_hub_quality_var.get()),
                    self.show_page("downloads"),
                    messagebox.showinfo("Downloads Started", f"Queued {len(chosen)} video(s)!")
                ),
            )
            return

        self.tiktok_hub_status.configure(text=f"Loading collection '{pl_data['title'][:25]}'...")

        def worker():
            try:
                title, entries = fetch_playlist_info(pl_data["url"], max_items=0)
                pl_data["videos"] = entries
                def on_done():
                    self.tiktok_hub_status.configure(text="")
                    if not entries:
                        messagebox.showwarning("No Videos", "No videos found in this collection.")
                        return
                    VideoGridModal(
                        self,
                        title=pl_data.get("title", "Collection"),
                        videos=entries,
                        on_download_selected=lambda chosen: (
                            self._queue_batch_with_numbering(chosen, self.tiktok_hub_quality_var.get()),
                            self.show_page("downloads"),
                            messagebox.showinfo("Downloads Started", f"Queued {len(chosen)} video(s)!")
                        ),
                    )
                self.after(0, on_done)
            except Exception as e:
                self.after(0, lambda: self.tiktok_hub_status.configure(text=""))
                self.after(0, lambda: messagebox.showerror("Error", f"Could not load collection: {str(e)}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_download_tiktok_playlist(self, pl_data: dict) -> None:
        self.tiktok_hub_status.configure(text=f"Queuing collection '{pl_data['title'][:25]}'...")

        def worker():
            try:
                entries = pl_data.get("videos")
                if not entries:
                    _, entries = fetch_playlist_info(pl_data["url"], max_items=0)
                    pl_data["videos"] = entries

                def on_done():
                    self.tiktok_hub_status.configure(text="")
                    if not entries:
                        messagebox.showwarning("No Videos", "No videos found in this collection.")
                        return
                    self._queue_batch_with_numbering(entries, self.tiktok_hub_quality_var.get())
                    self.show_page("downloads")
                    messagebox.showinfo("Downloads Started", f"Queued {len(entries)} videos from '{pl_data['title']}' with sequential numbering (01, 02, 03...)!")
                self.after(0, on_done)
            except Exception as e:
                self.after(0, lambda: self.tiktok_hub_status.configure(text=""))
                self.after(0, lambda: messagebox.showerror("Error", f"Failed to download collection: {str(e)}"))

        threading.Thread(target=worker, daemon=True).start()

    def _build_ig_hub_page(self) -> None:
        self.ig_hub_page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.ig_hub_page.grid_columnconfigure(0, weight=1)
        self.ig_hub_page.grid_rowconfigure(1, weight=1)

        self._current_ig_catalog: dict | None = None

        # 1. Search Header Card (EaseUS Instagram Pill Style)
        search_card = ctk.CTkFrame(self.ig_hub_page, corner_radius=14, fg_color=SURFACE, border_width=1, border_color=BORDER)
        search_card.grid(row=0, column=0, sticky="ew", padx=24, pady=(16, 8))
        search_card.grid_columnconfigure(1, weight=1)

        # Instagram Badge
        ig_badge_icon = self._get_icon("plat_instagram.png", (24, 24))
        badge = ctk.CTkLabel(
            search_card,
            image=ig_badge_icon,
            text="",
            width=38,
            height=38,
            corner_radius=10,
            fg_color=("#FCE7F3", "#3B1527"),
        )
        badge.grid(row=0, column=0, padx=(16, 10), pady=10)

        # Search Entry
        self.ig_search_var = ctk.StringVar()
        self.ig_search_entry = ctk.CTkEntry(
            search_card,
            textvariable=self.ig_search_var,
            placeholder_text="Enter Instagram @username (e.g. @ireniusx) or profile URL...",
            height=38,
            corner_radius=8,
            border_width=1,
            border_color=BORDER,
            fg_color=("#F8FAFC", "#0F172A"),
            text_color=INK,
            font=ctk.CTkFont(size=13),
        )
        self.ig_search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=10)
        self.ig_search_entry.bind("<Return>", lambda _: self._explore_instagram())

        # Clear Button
        ctk.CTkButton(
            search_card,
            text="✕",
            width=32,
            height=38,
            corner_radius=8,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=MUTED,
            command=lambda: self.ig_search_var.set(""),
        ).grid(row=0, column=2, padx=(0, 6), pady=10)

        # Search Button (Blue magnifying glass)
        self.ig_explore_btn = ctk.CTkButton(
            search_card,
            text="🔍",
            width=48,
            height=38,
            corner_radius=8,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self._explore_instagram,
        )
        self.ig_explore_btn.grid(row=0, column=3, padx=(0, 8), pady=10)

        # Settings gear icon (opens Authorization tab for Instagram login!)
        ctk.CTkButton(
            search_card,
            text="⚙",
            width=36,
            height=38,
            corner_radius=8,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            font=ctk.CTkFont(size=15),
            command=lambda: self._open_settings_dialog("auth"),
        ).grid(row=0, column=4, padx=(0, 16), pady=10)

        # Status Label
        self.ig_hub_status = ctk.CTkLabel(search_card, text="", text_color=BLUE, font=ctk.CTkFont(size=12))
        self.ig_hub_status.grid(row=1, column=0, columnspan=5, sticky="w", padx=18, pady=(0, 6))

        # 2. Main Content Frame
        self.ig_main_container = ctk.CTkFrame(self.ig_hub_page, fg_color="transparent")
        self.ig_main_container.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 8))
        self.ig_main_container.grid_columnconfigure(0, weight=1)
        self.ig_main_container.grid_rowconfigure(0, weight=1)

        # Welcome Placeholder Frame
        self.ig_welcome_frame = ctk.CTkFrame(self.ig_main_container, corner_radius=14, fg_color=SURFACE, border_width=1, border_color=BORDER)
        self.ig_welcome_frame.grid(row=0, column=0, sticky="nsew")

        ig_center_icon = self._get_icon("plat_instagram.png", (48, 48))
        ctk.CTkLabel(
            self.ig_welcome_frame,
            image=ig_center_icon,
            text="",
            width=70,
            height=70,
            corner_radius=22,
            fg_color=("#FCE7F3", "#3B1527"),
        ).pack(pady=(70, 14))

        ctk.CTkLabel(
            self.ig_welcome_frame,
            text="Instagram Profile Explorer (IG Auto-save)",
            text_color=INK,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(pady=(0, 6))

        ctk.CTkLabel(
            self.ig_welcome_frame,
            text="Search an Instagram @username above to view public posts, reels, and photos.\nHover over any media to download in high quality!",
            text_color=MUTED,
            font=ctk.CTkFont(size=13),
            justify="center",
        ).pack(pady=(0, 24))

        # Results Scrollable Frame
        self.ig_results_frame = ctk.CTkScrollableFrame(self.ig_main_container, fg_color="transparent")
        self.ig_results_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        # Bottom IG Stats Bar
        self.ig_stats_bar = ctk.CTkFrame(self.ig_hub_page, height=58, corner_radius=12, fg_color=SURFACE, border_width=1, border_color=BORDER)

    def _explore_instagram(self) -> None:
        raw_val = self.ig_search_var.get().strip()
        if not raw_val:
            messagebox.showwarning("Enter Username or Link", "Please enter an Instagram @username, profile link, or direct Reel / Post URL.")
            return

        self.ig_explore_btn.configure(state="disabled")
        self.ig_hub_status.configure(text="Fetching Instagram media... Please wait.")

        # Check if cookie authorization exists for Instagram
        cookie_src = self.settings.authorized_accounts.get("instagram")

        def worker():
            try:
                catalog = fetch_instagram_catalog(raw_val, cookies_source=cookie_src)

                def on_done():
                    self.ig_explore_btn.configure(state="normal")
                    self.ig_hub_status.configure(text="")
                    self._current_ig_catalog = catalog
                    self._render_instagram_catalog(catalog)

                self.after(0, on_done)
            except Exception as exc:
                def on_err(err_text=str(exc)):
                    self.ig_explore_btn.configure(state="normal")
                    self.ig_hub_status.configure(text="")
                    # Instead of a harsh popup, render the informative auth card
                    fallback_catalog = {
                        "channel_title": raw_val,
                        "uploader": raw_val.lstrip("@"),
                        "handle": f"@{raw_val.lstrip('@')}",
                        "channel_url": raw_val,
                        "avatar_url": None,
                        "posts": [],
                        "total_posts": 0,
                        "requires_auth": True,
                        "error_msg": err_text,
                    }
                    self._current_ig_catalog = fallback_catalog
                    self._render_instagram_catalog(fallback_catalog)

                self.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _render_instagram_catalog(self, catalog: dict) -> None:
        self.ig_welcome_frame.grid_forget()
        self.ig_results_frame.grid(row=0, column=0, sticky="nsew")

        for widget in self.ig_results_frame.winfo_children():
            widget.destroy()

        posts = catalog.get("posts", [])
        if not posts or catalog.get("requires_auth"):
            self.ig_stats_bar.grid_forget()
            
            auth_card = ctk.CTkFrame(self.ig_results_frame, corner_radius=14, fg_color=SURFACE, border_width=1, border_color=BORDER)
            auth_card.pack(fill="x", padx=30, pady=24)

            ctk.CTkLabel(
                auth_card,
                text="🔒",
                font=ctk.CTkFont(size=38),
                text_color="#F59E0B",
            ).pack(pady=(28, 8))

            ctk.CTkLabel(
                auth_card,
                text="Instagram Authorization Required",
                font=ctk.CTkFont(size=17, weight="bold"),
                text_color=INK,
            ).pack(pady=(0, 6))

            uploader_name = catalog.get("uploader") or "creator"
            ctk.CTkLabel(
                auth_card,
                text=f"Instagram blocks anonymous profile browsing. To view and download all posts from @{uploader_name},\nplease link your account in Authorization Settings (via browser session or cookies.txt file).",
                font=ctk.CTkFont(size=12),
                text_color=MUTED,
                justify="center",
            ).pack(pady=(0, 18), padx=20)

            btn_row = ctk.CTkFrame(auth_card, fg_color="transparent")
            btn_row.pack(pady=(0, 14))

            ctk.CTkButton(
                btn_row,
                text="🌐 Open in Built-in Browser",
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color=BLUE,
                hover_color=BLUE_HOVER,
                height=36,
                width=220,
                corner_radius=8,
                command=lambda: self.open_in_app_browser(f"https://www.instagram.com/{uploader_name}/"),
            ).pack(side="left", padx=6)

            ctk.CTkButton(
                btn_row,
                text="🔑 Authorize Account",
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color=SECONDARY_BTN,
                hover_color=SECONDARY_BTN_HOVER,
                text_color=INK,
                height=36,
                width=180,
                corner_radius=8,
                command=lambda: self._open_settings_dialog("auth"),
            ).pack(side="left", padx=6)

            ctk.CTkLabel(
                auth_card,
                text="💡 Tip: You can also paste direct Instagram Reel or Post links (e.g. instagram.com/reel/...) above to preview and download them immediately!",
                font=ctk.CTkFont(size=11),
                text_color=MUTED,
            ).pack(pady=(0, 24))
            return

        # Multi-column grid of InstagramPostCard
        columns = 4
        start_row = 0

        # If Instagram capped at guest limit, display actionable notification banner
        total_acc = catalog.get("total_account_posts", "")
        is_guest_limit = catalog.get("guest_limit_reached") or (not catalog.get("is_authenticated") and len(posts) <= 15)
        if is_guest_limit:
            banner = ctk.CTkFrame(self.ig_results_frame, corner_radius=10, fg_color=SURFACE, border_width=1, border_color="#F59E0B")
            banner.grid(row=0, column=0, columnspan=columns, sticky="ew", padx=8, pady=(0, 12))

            b_left = ctk.CTkFrame(banner, fg_color="transparent")
            b_left.pack(side="left", padx=14, pady=10)

            total_display = total_acc if total_acc else "entire profile"
            ctk.CTkLabel(
                b_left,
                text=f"⚠️ Showing {len(posts)} of {total_display} posts (Instagram Guest Mode)",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#D97706",
                anchor="w",
            ).pack(anchor="w")

            ctk.CTkLabel(
                b_left,
                text="Instagram restricts anonymous visitors to 12 posts. Log in once in the Built-in Browser, then click Refresh to grab all posts.",
                font=ctk.CTkFont(size=11),
                text_color=MUTED,
                anchor="w",
            ).pack(anchor="w")

            b_right = ctk.CTkFrame(banner, fg_color="transparent")
            b_right.pack(side="right", padx=14, pady=10)

            ctk.CTkButton(
                b_right,
                text="🌐 Log In to Instagram",
                height=30,
                corner_radius=6,
                fg_color=BLUE,
                hover_color=BLUE_HOVER,
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda: self.open_in_app_browser("https://www.instagram.com/accounts/login/"),
            ).pack(side="left", padx=(0, 6))

            ctk.CTkButton(
                b_right,
                text="↻ Refresh Account",
                height=30,
                corner_radius=6,
                fg_color=SECONDARY_BTN,
                hover_color=SECONDARY_BTN_HOVER,
                text_color=INK,
                font=ctk.CTkFont(size=11, weight="bold"),
                command=self._search_instagram_profile,
            ).pack(side="left", padx=(0, 6))

            start_row = 1

        for idx, post in enumerate(posts):
            row = start_row + (idx // columns)
            col = idx % columns
            card = InstagramPostCard(
                self.ig_results_frame,
                post_data=post,
                on_download=self._download_single_ig_post,
            )
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

        # Bottom Creator Bar
        self.ig_stats_bar.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 14))
        for child in self.ig_stats_bar.winfo_children():
            child.destroy()

        left_info = ctk.CTkFrame(self.ig_stats_bar, fg_color="transparent")
        left_info.pack(side="left", padx=16, pady=8)

        avatar_lbl = ctk.CTkLabel(
            left_info,
            text="📷",
            width=36,
            height=36,
            corner_radius=18,
            fg_color=SECONDARY_BTN,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#DB2777",
        )
        avatar_lbl.pack(side="left", padx=(0, 10))

        name_box = ctk.CTkFrame(left_info, fg_color="transparent")
        name_box.pack(side="left")

        ctk.CTkLabel(name_box, text=catalog.get("channel_title", "Instagram User"), font=ctk.CTkFont(size=13, weight="bold"), text_color=INK, anchor="w").pack(anchor="w")
        ctk.CTkLabel(name_box, text=catalog.get("handle", ""), font=ctk.CTkFont(size=11), text_color=MUTED, anchor="w").pack(anchor="w")

        # Middle stats
        badges_box = ctk.CTkFrame(self.ig_stats_bar, fg_color="transparent")
        badges_box.pack(side="left", padx=20)

        if total_acc:
            avail_text = f"📷 Available: {len(posts)} of {total_acc} Posts"
        else:
            avail_text = f"📷 Available Posts: {len(posts)}"
        ctk.CTkLabel(badges_box, text=avail_text, font=ctk.CTkFont(size=12, weight="bold"), text_color=BLUE).pack(side="left", padx=8)

        # Right action
        right_box = ctk.CTkFrame(self.ig_stats_bar, fg_color="transparent")
        right_box.pack(side="right", padx=16, pady=8)

        ctk.CTkButton(
            right_box,
            text="Download All Posts ⬇",
            height=32,
            corner_radius=8,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._download_all_ig_posts,
        ).pack(side="right")

    def _download_single_ig_post(self, post: dict) -> None:
        url = post.get("url")
        if not url:
            return
        self._queue_urls([url])
        self.show_page("downloads")
        messagebox.showinfo("Download Started", f"Queued Instagram post: {post.get('title', 'Post')}")

    def _download_all_ig_posts(self) -> None:
        if not self._current_ig_catalog:
            return
        posts = self._current_ig_catalog.get("posts", [])
        if not posts:
            messagebox.showwarning("No Posts", "No posts available to download.")
            return
        self._queue_batch_with_numbering(posts, self.quality_var.get())
        self.show_page("downloads")
    def _build_x_hub_page(self) -> None:
        self.x_hub_page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.x_hub_page.grid_columnconfigure(0, weight=1)
        self.x_hub_page.grid_rowconfigure(1, weight=1)

        # 1. Search Header Card
        search_card = ctk.CTkFrame(self.x_hub_page, corner_radius=14, fg_color=SURFACE, border_width=1, border_color=BORDER)
        search_card.grid(row=0, column=0, sticky="ew", padx=24, pady=(16, 8))
        search_card.grid_columnconfigure(1, weight=1)

        # X Badge
        x_badge_icon = self._get_icon("plat_x.png", (24, 24))
        badge = ctk.CTkLabel(
            search_card,
            image=x_badge_icon,
            text="",
            width=38,
            height=38,
            corner_radius=10,
            fg_color=("#F1F5F9", "#1E293B"),
        )
        badge.grid(row=0, column=0, padx=(16, 10), pady=10)

        # Search Entry
        self.x_search_var = ctk.StringVar()
        self.x_search_entry = ctk.CTkEntry(
            search_card,
            textvariable=self.x_search_var,
            placeholder_text="Enter X (Twitter) @username (e.g. @SpaceX) or tweet URL...",
            height=38,
            corner_radius=8,
            border_width=1,
            border_color=BORDER,
            fg_color=("#F8FAFC", "#0F172A"),
            text_color=INK,
            font=ctk.CTkFont(size=13),
        )
        self.x_search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=10)
        self.x_search_entry.bind("<Return>", lambda _: self._explore_x())

        def paste_x_search():
            try:
                clip = self.clipboard_get().strip()
                if clip:
                    self.x_search_var.set(clip)
                    self._explore_x()
            except Exception:
                pass

        ctk.CTkButton(
            search_card,
            text="Paste",
            width=65,
            height=38,
            corner_radius=8,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=BLUE,
            command=paste_x_search,
        ).grid(row=0, column=2, padx=(0, 8), pady=10)

        ctk.CTkButton(
            search_card,
            text="Explore Profile 🔍",
            width=140,
            height=38,
            corner_radius=8,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._explore_x,
        ).grid(row=0, column=3, padx=(0, 8), pady=10)

        ctk.CTkButton(
            search_card,
            text="Open in Browser 🌐",
            width=135,
            height=38,
            corner_radius=8,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self.open_in_app_browser("https://www.x.com"),
        ).grid(row=0, column=4, padx=(0, 16), pady=10)

        # Center Welcome Frame
        welcome_frame = ctk.CTkFrame(self.x_hub_page, fg_color="transparent")
        welcome_frame.grid(row=1, column=0, sticky="nsew", padx=24, pady=20)

        w_card = ctk.CTkFrame(welcome_frame, corner_radius=16, fg_color=SURFACE, border_width=1, border_color=BORDER)
        w_card.pack(fill="x", pady=40, padx=20)

        x_center_icon = self._get_icon("plat_x.png", (48, 48))
        if x_center_icon:
            ctk.CTkLabel(
                w_card,
                image=x_center_icon,
                text="",
            ).pack(pady=(36, 0))

        ctk.CTkLabel(
            w_card,
            text="Download media directly from X (Twitter) creators!",
            text_color=INK,
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(pady=(16 if x_center_icon else 36, 6))

        ctk.CTkLabel(
            w_card,
            text="Enter @username or paste a tweet link above to download videos and GIFs in 1-click.\nOr click 'Open in Browser' to browse your bookmarks with the integrated high-speed downloader!",
            text_color=MUTED,
            font=ctk.CTkFont(size=13),
            justify="center",
        ).pack(pady=(0, 24))

    def _explore_x(self) -> None:
        raw_val = self.x_search_var.get().strip()
        if not raw_val:
            messagebox.showwarning("Enter Username or URL", "Please enter an X @username or tweet URL.")
            return
        if "://" in raw_val:
            self._queue_urls([raw_val])
            self.show_page("downloads")
        else:
            handle = raw_val.lstrip("@")
            url = f"https://x.com/{handle}"
            self.open_in_app_browser(url)

    def _build_sites_page(self) -> None:
        self.sites_page = ctk.CTkFrame(self.content, fg_color="transparent")
        self.sites_page.grid_columnconfigure(0, weight=1)
        self.sites_page.grid_rowconfigure(1, weight=1)

        # 1. Top Browser Navigation & Quick Download Bar
        nav_bar = ctk.CTkFrame(self.sites_page, corner_radius=12, fg_color=SURFACE, border_width=1, border_color=BORDER)
        nav_bar.grid(row=0, column=0, sticky="ew", padx=24, pady=(16, 12))
        nav_bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            nav_bar,
            text="🌐 Web Browser:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=BLUE,
        ).pack(side="left", padx=(14, 8), pady=8)

        self.browser_url_var = ctk.StringVar(value="https://www.youtube.com")
        self.browser_url_entry = ctk.CTkEntry(
            nav_bar,
            textvariable=self.browser_url_var,
            height=34,
            corner_radius=6,
            border_width=1,
            border_color=BORDER,
            fg_color=("#F8FAFC", "#0F172A"),
            text_color=INK,
            font=ctk.CTkFont(size=12),
        )
        self.browser_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.browser_url_entry.bind("<Return>", lambda _: self._open_browser_url())

        ctk.CTkButton(
            nav_bar,
            text="🌐 Open in Browser",
            width=135,
            height=34,
            corner_radius=6,
            fg_color=SECONDARY_BTN,
            hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._open_browser_url,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            nav_bar,
            text="⬇ Quick Download",
            width=135,
            height=34,
            corner_radius=6,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._download_from_browser_bar,
        ).pack(side="left", padx=(0, 12))

        # 2. Main Center Sites Hub
        center_frame = ctk.CTkFrame(self.sites_page, fg_color="transparent")
        center_frame.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 20))
        center_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            center_frame,
            text="Click the website below to browse and download",
            text_color=INK,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(pady=(36, 20))

        # Grid of 10 Platforms (2 rows of 5)
        grid_box = ctk.CTkFrame(center_frame, fg_color=SURFACE, corner_radius=14, border_width=1, border_color=BORDER)
        grid_box.pack(padx=40, pady=10)

        platforms = [
            ("plat_youtube.png", "▶", "YouTube", "https://www.youtube.com", "#EF4444"),
            ("plat_tiktok.png", "♪", "TikTok", "https://www.tiktok.com", "#00F2FE"),
            ("plat_facebook.png", "f", "Facebook", "https://www.facebook.com", "#1877F2"),
            ("plat_instagram.png", "📷", "Instagram", "https://www.instagram.com", "#E1306C"),
            ("plat_x.png", "𝕏", "X", "https://www.x.com", "#FFFFFF"),
            ("plat_soundcloud.png", "☁", "SoundCloud", "https://www.soundcloud.com", "#FF5500"),
            ("plat_twitch.png", "👾", "Twitch", "https://www.twitch.tv", "#9146FF"),
            ("plat_vimeo.png", "v", "Vimeo", "https://www.vimeo.com", "#1AB7EA"),
            ("plat_dailymotion.png", "d", "Dailymotion", "https://www.dailymotion.com", "#0066DC"),
            ("plat_bilibili.png", "📺", "Bilibili", "https://www.bilibili.com", "#FB7299"),
        ]

        self._platform_icons_cache = []

        for idx, (img_file, fallback_icon, name, site_url, color) in enumerate(platforms):
            row = idx // 5
            col = idx % 5

            card_frame = ctk.CTkFrame(
                grid_box,
                width=112,
                height=96,
                corner_radius=12,
                fg_color=("#F8FAFC", "#0F172A"),
                border_width=1,
                border_color=BORDER,
            )
            card_frame.grid(row=row, column=col, padx=12, pady=14)
            card_frame.grid_propagate(False)

            # Load official PNG logo with fallback to icon text
            logo_ctk_img = None
            try:
                p = get_asset_path(f"assets/{img_file}")
                if os.path.exists(p):
                    pil_img = Image.open(p).convert("RGBA")
                    logo_ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(38, 38))
                    self._platform_icons_cache.append(logo_ctk_img)
            except Exception:
                logo_ctk_img = None

            if logo_ctk_img:
                icon_box = ctk.CTkLabel(
                    card_frame,
                    image=logo_ctk_img,
                    text="",
                    width=44,
                    height=44,
                    corner_radius=10,
                    fg_color="transparent",
                )
            else:
                icon_box = ctk.CTkLabel(
                    card_frame,
                    text=fallback_icon,
                    width=44,
                    height=44,
                    corner_radius=10,
                    fg_color=("#EEF2F6", "#1E293B"),
                    text_color=color,
                    font=ctk.CTkFont(size=22, weight="bold"),
                )
            icon_box.place(relx=0.5, y=32, anchor="center")

            name_lbl = ctk.CTkLabel(
                card_frame,
                text=name,
                text_color=INK,
                font=ctk.CTkFont(size=12, weight="bold"),
            )
            name_lbl.place(relx=0.5, y=72, anchor="center")

            # Fully recursive click & hover binding across all components
            self._make_card_clickable(card_frame, site_url)

    def _make_card_clickable(self, card_frame: ctk.CTkFrame, site_url: str) -> None:
        def on_click(event=None):
            self._select_site(site_url)

        def on_enter(event=None):
            try:
                card_frame.configure(border_color=BLUE, fg_color=("#F1F5F9", "#1E293B"))
            except Exception:
                pass

        def on_leave(event=None):
            try:
                card_frame.configure(border_color=BORDER, fg_color=("#F8FAFC", "#0F172A"))
            except Exception:
                pass

        def bind_recursive(w):
            w.bind("<Button-1>", on_click)
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass
            for attr in ("_canvas", "_label", "_text_label"):
                sub = getattr(w, attr, None)
                if sub:
                    try:
                        sub.bind("<Button-1>", on_click)
                        sub.bind("<Enter>", on_enter)
                        sub.bind("<Leave>", on_leave)
                        sub.configure(cursor="hand2")
                    except Exception:
                        pass
            if hasattr(w, "winfo_children"):
                for child in w.winfo_children():
                    bind_recursive(child)

        bind_recursive(card_frame)

    def open_in_app_browser(self, url: str) -> None:
        clean_url = url.strip()
        if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
            clean_url = f"https://{clean_url}"
        port = self.ipc_server.port if hasattr(self, "ipc_server") and self.ipc_server else None
        preferred = getattr(self.settings, "preferred_browser", "Google Chrome")
        BrowserManager.open_browser(clean_url, port, browser_name=preferred)

    def _on_browser_focus_requested(self) -> None:
        def _focus():
            try:
                self.deiconify()
                self.lift()
                self.focus_force()
            except Exception:
                pass
        self.after(0, _focus)

    def _on_browser_download_received(self, url: str, cookies_path: str, title: str) -> None:
        def _do_enqueue():
            if cookies_path and Path(cookies_path).is_file():
                platform = detect_platform_from_url(url)
                from ui.settings_dialog import is_platform_cookie_authenticated
                if is_platform_cookie_authenticated(platform, cookies_path):
                    self.settings.authorized_accounts[platform] = cookies_path
                    self.store.save(self.settings)

            self._queue_urls([url])
            self.show_page("downloads")
            try:
                self.deiconify()
                self.lift()
                self.focus_force()
            except Exception:
                pass

        self.after(0, _do_enqueue)

    def _on_browser_cookies_synced(self, platform: str, cookies_path: str) -> None:
        def _do_sync():
            if cookies_path and Path(cookies_path).is_file():
                from ui.settings_dialog import is_platform_cookie_authenticated
                if is_platform_cookie_authenticated(platform, cookies_path):
                    self.settings.authorized_accounts[platform] = cookies_path
                    if platform == "youtube":
                        self.settings.authorized_accounts["google"] = cookies_path
                    elif platform == "x":
                        self.settings.authorized_accounts["twitter"] = cookies_path
                    self.store.save(self.settings)

        self.after(0, _do_sync)

    def _select_site(self, url: str) -> None:
        self.browser_url_var.set(url)
        self.open_in_app_browser(url)

    def _back_to_sites_grid(self) -> None:
        self.browser_url_var.set("https://www.youtube.com")
        self.show_page("sites")

    def _open_browser_url(self) -> None:
        url = self.browser_url_var.get().strip()
        if url:
            self.open_in_app_browser(url)

    def _download_from_browser_bar(self) -> None:
        url = self.browser_url_var.get().strip()
        if not url:
            messagebox.showwarning("Enter URL", "Please enter a video URL to download.")
            return
        self._queue_urls([url])
        self.show_page("downloads")

    def show_page(self, page: str) -> None:
        for p in ("dashboard_page", "download_page", "image_downloader_page", "channel_hub_page",
                  "tiktok_hub_page", "ig_hub_page", "x_hub_page", "converter_page", "sites_page"):
            if hasattr(self, p):
                getattr(self, p).grid_forget()

        self._current_page = page
        if page == "dashboard":
            active = self.dashboard_page
            title_text = "Dashboard"
            self._refresh_dashboard_metrics()
            self._refresh_recent_downloads_list()
        elif page == "downloads":
            active = self.download_page
            title_text = "General"
            self._filter_task_list()
        elif page == "image_downloader":
            active = self.image_downloader_page
            title_text = "Image Downloader"
        elif page == "channel_hub":
            active = self.channel_hub_page
            title_text = "YTB Auto-save"
        elif page == "tiktok_hub":
            active = self.tiktok_hub_page
            title_text = "TikTok Auto-save"
        elif page == "ig_hub":
            active = self.ig_hub_page
            title_text = "IG Auto-save"
        elif page == "x_hub":
            active = self.x_hub_page
            title_text = "X Auto-save"
        elif page == "converter":
            active = self.converter_page
            title_text = "Video to MP3"
        elif page == "sites":
            active = self.sites_page
            title_text = "More Platforms"
        else:
            active = self.dashboard_page
            title_text = "Dashboard"
            self._refresh_dashboard_metrics()
            self._refresh_recent_downloads_list()

        active.grid(row=0, column=0, sticky="nsew")
        self.title_label.configure(text=title_text)
        for name, button in self.nav_buttons.items():
            button.configure(fg_color="#2563EB" if name == page else "transparent")

    def _go_to_downloads(self) -> None:
        self.show_page("downloads")
        self._toggle_multi_urls(show=True)
        self.url_box.focus_set()

    def _on_format_changed(self, choice: str) -> None:
        if "Image" in choice:
            self.quality_var.set("Image / Photo")
        elif "MP3" in choice:
            self.quality_var.set("Audio MP3")
        elif "WAV" in choice:
            self.quality_var.set("Audio WAV")
        elif "Video" in choice:
            if "Audio" in self.quality_var.get() or "Image" in self.quality_var.get():
                self.quality_var.set(self.settings.default_quality if self.settings.default_quality in QUALITY_OPTIONS and "Audio" not in self.settings.default_quality and "Image" not in self.settings.default_quality else "Best Available")

    def _show_paste_menu(self) -> None:
        menu = Menu(self, tearoff=False)
        menu.add_command(label="📋 Paste URL from clipboard", command=self._paste_from_clipboard)
        menu.add_command(label="🎵 Download as Audio (MP3)", command=lambda: self._paste_as_audio())
        menu.add_command(label="🖼 Download as Image / Photo", command=lambda: self._paste_as_image())
        menu.add_command(label="☷ Batch Download (Multiple URLs)", command=self._toggle_multi_urls)
        menu.add_command(label="☰ Download Playlist / Channel", command=self._open_playlist_dialog)
        x = self.paste_menu_button.winfo_rootx()
        y = self.paste_menu_button.winfo_rooty() + self.paste_menu_button.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _paste_as_audio(self) -> None:
        self.format_choice_var.set("Audio MP3")
        self.quality_var.set("Audio MP3")
        self._paste_from_clipboard()

    def _paste_as_image(self) -> None:
        self.format_choice_var.set("Image / Photo (JPG/PNG)")
        self.quality_var.set("Image / Photo")
        self._paste_from_clipboard()

    def _toggle_multi_urls(self, show: bool | None = None) -> None:
        visible = not self._multi_urls_visible if show is None else show
        self._multi_urls_visible = visible
        if visible:
            self.form_drawer.grid()
            self.url_box.focus_set()
        else:
            self.form_drawer.grid_remove()

    def _open_download_settings_modal(self) -> None:
        DownloadSettingsModal(self, self.settings, on_save=self._on_settings_saved)

    def _open_settings_dialog(self, initial_tab: str = "basic") -> None:
        SettingsDialog(self, self.settings, on_save=self._on_settings_saved, initial_tab=initial_tab)

    def _on_settings_saved(self, updated: AppSettings) -> None:
        self.settings = updated
        self.store.save(updated)
        self.manager.set_worker_limit(updated.simultaneous_downloads)
        self._update_folder_label()
        if hasattr(self, "theme_menu"):
            self.theme_menu.set(updated.appearance_mode.title())
        self._set_appearance_mode(updated.appearance_mode)
        if hasattr(self, "clipboard_monitor"):
            if getattr(updated, "monitor_clipboard", True):
                self.clipboard_monitor.start()
            else:
                self.clipboard_monitor.stop()

    def _show_top_menu(self) -> None:
        menu = Menu(self, tearoff=False)
        menu.add_command(label="🔑 Enter License Key...", command=self._open_license_dialog)
        menu.add_separator()
        menu.add_command(label="🔄 Check for App Updates...", command=self._check_for_updates)
        menu.add_separator()
        menu.add_command(label="⚙ Settings", command=self._open_settings_dialog)
        menu.add_command(label="👤 Authorization (Log In)", command=lambda: self._open_settings_dialog("auth"))
        menu.add_separator()
        theme_menu = Menu(menu, tearoff=False)
        theme_menu.add_command(label="🌙 Dark Mode", command=lambda: self._set_appearance_mode("Dark"))
        theme_menu.add_command(label="☀️ Light Mode", command=lambda: self._set_appearance_mode("Light"))
        theme_menu.add_command(label="💻 System Default", command=lambda: self._set_appearance_mode("System"))
        menu.add_cascade(label="🎨 Theme (Dark / Light / System)", menu=theme_menu)
        menu.add_separator()
        menu.add_command(label="ℹ About DeepX Vision Downloader", command=lambda: self._open_settings_dialog("about"))
        try:
            x = self.top_menu_btn.winfo_rootx()
            y = self.top_menu_btn.winfo_rooty() + self.top_menu_btn.winfo_height() + 4
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _update_pro_badge_ui(self) -> None:
        if not hasattr(self, "pro_badge_btn"):
            return
        if license_mgr.is_pro():
            days = license_mgr.get_days_remaining()
            if days is None:
                txt = "👑 PRO ACTIVATED"
            else:
                txt = f"👑 PRO • {days}d left"
            self.pro_badge_btn.configure(
                text=txt,
                fg_color="#F59E0B",
                hover_color="#D97706",
                text_color="#0F172A",
            )
        else:
            left = license_mgr.get_daily_trial_remaining()
            self.pro_badge_btn.configure(
                text=f"⏳ Trial: {left}/5 left",
                fg_color=("#EFF6FF", "#1E3A8A"),
                hover_color=("#DBEAFE", "#1D4ED8"),
                text_color=("#1D4ED8", "#93C5FD"),
            )

    def _on_pro_badge_clicked(self) -> None:
        if license_mgr.is_pro():
            LicenseDialog(self, on_status_changed=self._update_pro_badge_ui)
        else:
            PricingModal(self, on_activate_clicked=lambda: LicenseDialog(self, on_status_changed=self._update_pro_badge_ui))

    def _open_pricing_modal(self) -> None:
        PricingModal(self, on_activate_clicked=lambda: LicenseDialog(self, on_status_changed=self._update_pro_badge_ui))

    def _open_license_dialog(self) -> None:
        LicenseDialog(self, on_status_changed=self._update_pro_badge_ui)

    def _check_for_updates(self, silent_if_latest: bool = False) -> None:
        def _worker():
            try:
                has_up, manifest, msg = check_for_updates()
                def _ui():
                    try:
                        if not self.winfo_exists():
                            return
                        if has_up and manifest:
                            UpdateModal(self, manifest)
                        elif not silent_if_latest:
                            messagebox.showinfo("DeepX Vision Downloader", msg)
                    except Exception:
                        pass
                try:
                    self.after(0, _ui)
                except Exception:
                    pass
            except Exception:
                pass
        threading.Thread(target=_worker, daemon=True).start()

    def _check_updates_background(self) -> None:
        self._check_for_updates(silent_if_latest=True)

    def _on_clipboard_url_detected(self, url: str) -> None:
        self._show_clipboard_toast(url)

    def _show_clipboard_toast(self, url: str) -> None:
        if not hasattr(self, "clip_toast"):
            return
        if self.clip_toast.winfo_ismapped():
            self.clip_toast.place_forget()

        for w in self.clip_toast.winfo_children():
            w.destroy()

        ctk.CTkLabel(
            self.clip_toast,
            text="📋 Video link copied!",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38BDF8",
        ).pack(side="left", padx=(12, 6), pady=6)

        disp_url = url if len(url) <= 38 else url[:35] + "..."
        ctk.CTkLabel(
            self.clip_toast,
            text=disp_url,
            font=ctk.CTkFont(size=11),
            text_color="#CBD5E1",
        ).pack(side="left", padx=(0, 10), pady=6)

        def do_quick_dl():
            self.clip_toast.place_forget()
            self._queue_urls([url])
            self.show_page("downloads")
            self._set_downloads_tab("downloading")

        ctk.CTkButton(
            self.clip_toast,
            text="⚡ Quick Download",
            height=28,
            corner_radius=6,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=do_quick_dl,
        ).pack(side="left", padx=(0, 6), pady=6)

        ctk.CTkButton(
            self.clip_toast,
            text="✕",
            width=26,
            height=26,
            corner_radius=13,
            fg_color="#334155",
            hover_color="#475569",
            text_color="#CBD5E1",
            command=self.clip_toast.place_forget,
        ).pack(side="left", padx=(0, 8), pady=6)

        self.clip_toast.place(relx=0.98, rely=0.96, anchor="se")
        self.after(12000, lambda: self.clip_toast.place_forget() if hasattr(self, "clip_toast") else None)

    def _set_appearance_mode(self, mode: str) -> None:
        m = mode.strip().lower()
        if "light" in m:
            clean = "Light"
        elif "system" in m:
            clean = "System"
        else:
            clean = "Dark"

        ctk.set_appearance_mode(clean.lower())
        self.settings.appearance_mode = clean
        self.store.save(self.settings)

        if hasattr(self, "theme_menu"):
            self.theme_menu.set(clean)
        if hasattr(self, "theme_var"):
            self.theme_var.set(clean)

        detected = ctk.get_appearance_mode()
        c_bg = "#FFFFFF" if detected == "Light" else "#1E293B"
        if hasattr(self, "_spark_canvases"):
            for c in self._spark_canvases:
                try:
                    c.configure(bg=c_bg)
                except Exception:
                    pass

        try:
            self.configure(fg_color=BACKGROUND)
        except Exception:
            pass

    def _toggle_appearance(self) -> None:
        curr = ctk.get_appearance_mode()
        new_mode = "Light" if curr == "Dark" else "Dark"
        self._set_appearance_mode(new_mode)

    def _paste_from_clipboard(self) -> None:
        try:
            url = self.clipboard_get().strip()
        except TclError:
            messagebox.showinfo("Clipboard is empty", "Copy a public video URL first, then choose Paste URL.")
            return

        if is_playlist_or_channel(url):
            self._open_playlist_dialog(initial_url=url)
            return

        self._queue_urls([url])

    def _add_urls(self) -> None:
        if getattr(self, "_batch_placeholder_active", False):
            content = ""
        else:
            content = self.url_box.get("1.0", "end").strip()
            if content == getattr(self, "_batch_placeholder", "Paste one public video URL per line…"):
                content = ""
        urls = [line.strip() for line in content.splitlines() if line.strip()]
        if len(urls) == 1 and is_playlist_or_channel(urls[0]):
            self._open_playlist_dialog(initial_url=urls[0])
            self.url_box.delete("1.0", "end")
            if hasattr(self, "_reset_url_box_placeholder"):
                self._reset_url_box_placeholder()
            return
        if self._queue_urls(urls):
            self.url_box.delete("1.0", "end")
            if hasattr(self, "_reset_url_box_placeholder"):
                self._reset_url_box_placeholder()

    def _open_playlist_dialog(self, initial_url: str = "") -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Download Playlist / Channel")
        dialog.geometry("620x520")
        dialog.minsize(600, 500)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color=BACKGROUND)

        # Footer pinned to bottom first so buttons are ALWAYS visible
        footer = ctk.CTkFrame(dialog, fg_color="transparent")
        footer.pack(fill="x", side="bottom", padx=26, pady=16)

        ctk.CTkButton(footer, text="Cancel", width=80, height=36, fg_color=SECONDARY_BTN, hover_color=SECONDARY_BTN_HOVER, text_color=INK, command=dialog.destroy).pack(side="right", padx=(8, 0))

        analyze_btn = ctk.CTkButton(footer, text="Analyze & Select Videos", width=190, height=36, fg_color=BLUE, hover_color=BLUE_HOVER, font=ctk.CTkFont(size=13, weight="bold"))
        analyze_btn.pack(side="right")

        # Status label above footer
        status_label = ctk.CTkLabel(dialog, text="", text_color=MUTED, font=ctk.CTkFont(size=11))
        status_label.pack(side="bottom", anchor="w", padx=26, pady=(0, 4))

        ctk.CTkLabel(
            dialog,
            text="Download Playlist or Channel",
            text_color=INK,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", padx=26, pady=(18, 2))

        ctk.CTkLabel(
            dialog,
            text="Select download mode, paste a link, and choose which videos to download.",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=26, pady=(0, 12))

        card = ctk.CTkFrame(dialog, corner_radius=12, fg_color=SURFACE, border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=26)
        card.grid_columnconfigure(0, weight=1)

        # URL row
        ctk.CTkLabel(card, text="Playlist / Channel URL:", text_color=INK, font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))

        if not initial_url:
            try:
                clip = self.clipboard_get().strip()
                if "http" in clip:
                    initial_url = clip
            except Exception:
                initial_url = ""

        url_var = ctk.StringVar(value=initial_url)
        url_entry = ctk.CTkEntry(card, textvariable=url_var, height=34, border_color=BORDER, fg_color=BACKGROUND, text_color=INK)
        url_entry.grid(row=1, column=0, sticky="ew", padx=(16, 8), pady=(0, 10))

        # Mode Selector under URL entry
        ctk.CTkLabel(card, text="Select Mode:", text_color=INK, font=ctk.CTkFont(size=12, weight="bold")).grid(row=2, column=0, columnspan=2, sticky="w", padx=16, pady=(2, 4))

        # Determine sensible initial mode
        init_lower = initial_url.lower()
        if "playlist" in init_lower or "list=" in init_lower:
            start_mode = "Playlist"
        elif "/@" in init_lower or "/channel/" in init_lower:
            start_mode = "All Videos"
        else:
            start_mode = "Playlist"

        mode_var = ctk.StringVar(value=start_mode)

        def _update_mode_description(val: str) -> None:
            if val == "All Videos":
                mode_desc_lbl.configure(text="Downloads all uploaded videos from the channel or profile with sequential numbering.")
            elif val == "All Playlists":
                mode_desc_lbl.configure(text="Fetches all creator playlists. Click ⌄ below each playlist to view and select videos.")
            else:
                mode_desc_lbl.configure(text="Directly downloads all videos from a specific playlist URL with sequential numbering.")

        mode_seg = ctk.CTkSegmentedButton(
            card,
            values=["All Videos", "All Playlists", "Playlist"],
            variable=mode_var,
            command=_update_mode_description,
            height=32,
            selected_color=BLUE,
            selected_hover_color=BLUE_HOVER,
            unselected_color=SECONDARY_BTN,
            unselected_hover_color=SECONDARY_BTN_HOVER,
            text_color=INK,
        )
        mode_seg.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 6))

        mode_desc_lbl = ctk.CTkLabel(
            card,
            text="",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
            justify="left",
            wraplength=520,
        )
        mode_desc_lbl.grid(row=4, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 10))
        _update_mode_description(start_mode)

        def paste_clipboard():
            try:
                pasted = self.clipboard_get().strip()
                url_var.set(pasted)
                p_low = pasted.lower()
                if "playlist" in p_low or "list=" in p_low:
                    mode_var.set("Playlist")
                    _update_mode_description("Playlist")
                elif "/@" in p_low or "/channel/" in p_low:
                    mode_var.set("All Videos")
                    _update_mode_description("All Videos")
            except Exception:
                pass

        ctk.CTkButton(card, text="Paste", width=65, height=34, fg_color=SECONDARY_BTN, hover_color=SECONDARY_BTN_HOVER, text_color=BLUE, command=paste_clipboard).grid(row=1, column=1, padx=(0, 16), pady=(0, 10))

        # Max items & Order on one sleek row
        options_row = ctk.CTkFrame(card, fg_color="transparent")
        options_row.grid(row=5, column=0, columnspan=2, sticky="ew", padx=16, pady=(2, 16))

        ctk.CTkLabel(options_row, text="Max items:", text_color=INK, font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 6))
        limit_var = ctk.StringVar(value="100 items")
        ctk.CTkOptionMenu(options_row, values=["50 items", "100 items", "250 items", "500 items", "All items"], variable=limit_var, width=110).pack(side="left", padx=(0, 16))

        ctk.CTkLabel(options_row, text="Order:", text_color=INK, font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 6))
        order_var = ctk.StringVar(value="Latest to Oldest (01=Latest)")
        ctk.CTkOptionMenu(options_row, values=["Latest to Oldest (01=Latest)", "Oldest to Latest (01=Oldest)"], variable=order_var, width=210).pack(side="left")

        def start_analysis():
            raw_url = url_var.get().strip()
            if not raw_url or not raw_url.startswith("http"):
                messagebox.showwarning("Invalid Link", "Please enter a valid HTTP or HTTPS playlist or channel URL.")
                return

            limit_text = limit_var.get()
            max_items = 0 if "All" in limit_text else int(limit_text.split()[0])
            sel_mode = mode_var.get()
            sel_order = "latest_first" if "Latest" in order_var.get() else "oldest_first"

            analyze_btn.configure(state="disabled")
            status_label.configure(text=f"Analyzing {sel_mode.lower()}... Please wait.")

            def worker():
                try:
                    if sel_mode == "All Playlists":
                        title, playlists = fetch_channel_all_playlists(raw_url, max_playlists=max_items)
                        def on_pl_done():
                            if not playlists:
                                analyze_btn.configure(state="normal")
                                status_label.configure(text="")
                                switch = messagebox.askyesno(
                                    "No Playlists Found",
                                    "No public playlists were found for this channel or creator.\n\nWould you like to fetch 'All Videos' from this channel instead?"
                                )
                                if switch:
                                    mode_var.set("All Videos")
                                    _update_mode_description("All Videos")
                                    start_analysis()
                                return
                            dialog.destroy()
                            self._show_all_playlists_modal(title, playlists)
                        self.after(0, on_pl_done)
                    else:
                        title, entries = fetch_playlist_info(
                            raw_url,
                            max_items=max_items,
                            mode="all_videos" if sel_mode == "All Videos" else "playlist",
                            order=sel_order,
                        )
                        def on_video_done():
                            if not entries:
                                analyze_btn.configure(state="normal")
                                status_label.configure(text="")
                                messagebox.showwarning("No Videos Found", "Could not find any videos in this playlist or channel.")
                                return
                            dialog.destroy()
                            self._show_playlist_selection_modal(title, entries, order=sel_order)
                        self.after(0, on_video_done)
                except Exception as exc:
                    def on_err(err_str=str(exc)):
                        analyze_btn.configure(state="normal")
                        status_label.configure(text=f"Error: {err_str[:60]}")
                        messagebox.showerror("Error", f"Could not analyze playlist/channel:\n{err_str}")
                    self.after(0, on_err)

            threading.Thread(target=worker, daemon=True).start()

        analyze_btn.configure(command=start_analysis)

    def _show_all_playlists_modal(self, channel_title: str, playlists: list[dict]) -> None:
        modal = ctk.CTkToplevel(self)
        clean_channel = channel_title[:60] + ("..." if len(channel_title) > 60 else "")
        modal.title(f"Channel Playlists - {clean_channel}")
        modal.geometry("820x680")
        modal.minsize(720, 520)
        modal.transient(self)
        modal.grab_set()
        modal.configure(fg_color=BACKGROUND)

        # Header
        header = ctk.CTkFrame(modal, fg_color="transparent")
        header.pack(fill="x", padx=26, pady=(20, 10))

        ctk.CTkLabel(header, text=clean_channel, text_color=INK, font=ctk.CTkFont(size=18, weight="bold"), anchor="w").pack(fill="x")
        ctk.CTkLabel(
            header,
            text=f"Found {len(playlists)} playlist(s). Check playlists to download, or click ⌄ on any playlist to view and uncheck specific videos.",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

        # Selection Toolbar
        tools = ctk.CTkFrame(modal, fg_color="transparent")
        tools.pack(fill="x", padx=26, pady=(0, 10))

        pl_vars: list[ctk.BooleanVar] = [ctk.BooleanVar(value=True) for _ in playlists]
        # Mapping: pl_id -> list[ctk.BooleanVar] for video rows
        pl_video_vars: dict[str, list[ctk.BooleanVar]] = {}
        # Mapping: pl_id -> toggle function
        pl_expand_toggles: dict[str, callable] = {}

        def update_global_count():
            sel_pl = sum(v.get() for v in pl_vars)
            count_lbl.configure(text=f"Selected: {sel_pl} / {len(playlists)} playlists")
            download_btn.configure(
                text=f"Download Selected Playlists ({sel_pl})",
                state="normal" if sel_pl > 0 else "disabled",
            )

        def select_all_pl():
            for v in pl_vars:
                v.set(True)
            for v_list in pl_video_vars.values():
                for v in v_list:
                    v.set(True)
            update_global_count()

        def deselect_all_pl():
            for v in pl_vars:
                v.set(False)
            for v_list in pl_video_vars.values():
                for v in v_list:
                    v.set(False)
            update_global_count()

        ctk.CTkButton(tools, text="Select All", width=80, height=28, corner_radius=6, fg_color=SECONDARY_BTN, hover_color=SECONDARY_BTN_HOVER, text_color=INK, command=select_all_pl).pack(side="left", padx=(0, 6))
        ctk.CTkButton(tools, text="Deselect All", width=90, height=28, corner_radius=6, fg_color=SECONDARY_BTN, hover_color=SECONDARY_BTN_HOVER, text_color=INK, command=deselect_all_pl).pack(side="left", padx=(0, 12))

        count_lbl = ctk.CTkLabel(tools, text=f"Selected: {len(playlists)} / {len(playlists)} playlists", text_color=BLUE, font=ctk.CTkFont(size=12, weight="bold"))
        count_lbl.pack(side="left")

        # Quality dropdown
        ctk.CTkLabel(tools, text="Quality:", text_color=MUTED, font=ctk.CTkFont(size=12)).pack(side="right", padx=(8, 0))
        modal_quality_var = ctk.StringVar(value=self.quality_var.get())
        ctk.CTkOptionMenu(tools, values=QUALITY_OPTIONS, variable=modal_quality_var, width=135, height=28).pack(side="right")

        # Footer (packed first with side='bottom' so it is never pushed off-screen)
        footer = ctk.CTkFrame(modal, fg_color="transparent")
        footer.pack(fill="x", side="bottom", padx=26, pady=16)

        # Scrollable list of playlist cards
        list_container = ctk.CTkScrollableFrame(modal, corner_radius=12, fg_color=("#F1F5F9", "#111827"))
        list_container.pack(fill="both", expand=True, padx=26, pady=(0, 12))

        for idx, (pl, p_var) in enumerate(zip(playlists, pl_vars), 1):
            pl_id = pl["id"]
            card = ctk.CTkFrame(list_container, fg_color=SURFACE, border_width=1, border_color=BORDER, corner_radius=10)
            card.pack(fill="x", padx=4, pady=4)
            card.grid_columnconfigure(0, weight=1)

            # Top header row of playlist card
            top_bar = ctk.CTkFrame(card, fg_color="transparent")
            top_bar.pack(fill="x", padx=12, pady=8)
            top_bar.grid_columnconfigure(2, weight=1)

            def on_pl_checkbox_toggle(current_p_var=p_var, current_id=pl_id):
                checked = current_p_var.get()
                if current_id in pl_video_vars:
                    for vv in pl_video_vars[current_id]:
                        vv.set(checked)
                update_global_count()

            pl_chk = ctk.CTkCheckBox(
                top_bar,
                text="",
                variable=p_var,
                width=24,
                text_color=INK,
                fg_color=BLUE,
                hover_color=BLUE_HOVER,
                font=ctk.CTkFont(size=13, weight="bold"),
                command=on_pl_checkbox_toggle,
            )
            pl_chk.grid(row=0, column=0, padx=(0, 8), sticky="w")

            # Playlist cover thumbnail box (60x38)
            pl_thumb_box = ctk.CTkFrame(top_bar, width=60, height=38, corner_radius=6, fg_color=("#E2E8F0", "#1E293B"))
            pl_thumb_box.pack_propagate(False)
            pl_thumb_box.grid(row=0, column=1, padx=(0, 10), sticky="w")

            pl_thumb_lbl = ctk.CTkLabel(pl_thumb_box, text="📁", font=ctk.CTkFont(size=14), text_color=MUTED)
            pl_thumb_lbl.pack(expand=True, fill="both")

            pl_thumb_url = pl.get("thumbnail_url")
            if pl_thumb_url:
                def _load_pl_thumb(u=pl_thumb_url, lbl=pl_thumb_lbl, top=modal):
                    try:
                        p_img = get_remote_image(u, (60, 38))
                        if p_img:
                            c_img = ctk.CTkImage(light_image=p_img, dark_image=p_img, size=(60, 38))
                            def _show():
                                if top.winfo_exists() and lbl.winfo_exists():
                                    lbl.configure(image=c_img, text="")
                                    lbl.image = c_img
                            top.after(0, _show)
                    except Exception:
                        pass
                threading.Thread(target=_load_pl_thumb, daemon=True).start()

            item_count_str = f"  ({pl['item_count']} videos)" if pl.get("item_count") else ""
            pl_title_lbl = ctk.CTkLabel(
                top_bar,
                text=f"{idx:02d}.  {pl['title']}{item_count_str}",
                text_color=INK,
                font=ctk.CTkFont(size=13, weight="bold"),
                anchor="w",
            )
            pl_title_lbl.grid(row=0, column=2, sticky="ew")

            # Accordion collapsible frame
            sub_frame = ctk.CTkFrame(card, fg_color=BACKGROUND, corner_radius=8)
            # Not packed initially

            toggle_state = {"expanded": False, "loaded": bool(pl.get("videos"))}

            def render_playlist_videos(target_pl=pl, target_sub=sub_frame, target_id=pl_id, target_p_var=p_var):
                for child in target_sub.winfo_children():
                    child.destroy()

                videos = target_pl.get("videos") or []
                if not videos:
                    ctk.CTkLabel(target_sub, text="No videos found in this playlist.", text_color=MUTED, font=ctk.CTkFont(size=11)).pack(padx=12, pady=10)
                    return

                # Mini controls inside sub_frame
                mini_bar = ctk.CTkFrame(target_sub, fg_color="transparent")
                mini_bar.pack(fill="x", padx=10, pady=(6, 4))

                v_vars = [ctk.BooleanVar(value=target_p_var.get()) for _ in videos]
                pl_video_vars[target_id] = v_vars

                def sync_from_videos():
                    any_checked = any(v.get() for v in v_vars)
                    target_p_var.set(any_checked)
                    update_global_count()

                def select_all_v():
                    for v in v_vars:
                        v.set(True)
                    target_p_var.set(True)
                    update_global_count()

                def deselect_all_v():
                    for v in v_vars:
                        v.set(False)
                    target_p_var.set(False)
                    update_global_count()

                ctk.CTkLabel(mini_bar, text=f"{len(videos)} videos", font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED).pack(side="left")
                ctk.CTkButton(mini_bar, text="Select All", width=65, height=22, corner_radius=4, font=ctk.CTkFont(size=11), fg_color=SECONDARY_BTN, hover_color=SECONDARY_BTN_HOVER, text_color=INK, command=select_all_v).pack(side="right", padx=(4, 0))
                ctk.CTkButton(mini_bar, text="Deselect All", width=75, height=22, corner_radius=4, font=ctk.CTkFont(size=11), fg_color=SECONDARY_BTN, hover_color=SECONDARY_BTN_HOVER, text_color=INK, command=deselect_all_v).pack(side="right")

                scroll_vids = ctk.CTkScrollableFrame(target_sub, height=min(240, max(90, len(videos) * 44)), fg_color="transparent")
                scroll_vids.pack(fill="both", expand=True, padx=6, pady=(0, 6))

                for v_idx, (vid, v_var) in enumerate(zip(videos, v_vars), 1):
                    v_row = ctk.CTkFrame(scroll_vids, fg_color=SURFACE, corner_radius=6, height=40)
                    v_row.pack(fill="x", padx=2, pady=2)
                    v_row.grid_columnconfigure(2, weight=1)

                    v_chk = ctk.CTkCheckBox(
                        v_row,
                        text="",
                        variable=v_var,
                        width=22,
                        text_color=INK,
                        fg_color=BLUE,
                        hover_color=BLUE_HOVER,
                        command=sync_from_videos,
                    )
                    v_chk.grid(row=0, column=0, padx=(8, 6), pady=4)

                    # Video mini thumbnail box (48x28)
                    v_thumb_box = ctk.CTkFrame(v_row, width=48, height=28, corner_radius=4, fg_color=("#E2E8F0", "#1E293B"))
                    v_thumb_box.pack_propagate(False)
                    v_thumb_box.grid(row=0, column=1, padx=(0, 8), pady=4)

                    is_v_short = (
                        vid.get("media_type") == "short"
                        or "/shorts/" in str(vid.get("url", ""))
                        or (vid.get("duration") and 0 < vid["duration"] <= 60 and ("youtube" in str(vid.get("url", "")) or "youtu.be" in str(vid.get("url", ""))))
                    )
                    v_thumb_lbl = ctk.CTkLabel(v_thumb_box, text="⚡" if is_v_short else "🎬", font=ctk.CTkFont(size=10), text_color=MUTED)
                    v_thumb_lbl.pack(expand=True, fill="both")

                    v_thumb_url = vid.get("thumbnail_url") or vid.get("thumbnail")
                    if v_thumb_url:
                        def _load_v_thumb(u=v_thumb_url, lbl=v_thumb_lbl, top=modal):
                            try:
                                p_img = get_remote_image(u, (48, 28))
                                if p_img:
                                    c_img = ctk.CTkImage(light_image=p_img, dark_image=p_img, size=(48, 28))
                                    def _show():
                                        if top.winfo_exists() and lbl.winfo_exists():
                                            lbl.configure(image=c_img, text="")
                                            lbl.image = c_img
                                    top.after(0, _show)
                            except Exception:
                                pass
                        threading.Thread(target=_load_v_thumb, daemon=True).start()

                    dur = f"  ({format_eta(vid['duration'])})" if vid.get("duration") else ""
                    short_flag = "  [⚡ Short]" if is_v_short else ""
                    clean_v_name = re.sub(r"^\d{1,4}[\.\s_-]+\s*", "", vid.get("title", ""))
                    v_title = ctk.CTkLabel(
                        v_row,
                        text=f"{v_idx:02d}.  {clean_v_name or vid.get('title', 'Video')}{dur}{short_flag}",
                        text_color=INK,
                        font=ctk.CTkFont(size=11),
                        anchor="w",
                    )
                    v_title.grid(row=0, column=2, sticky="ew", padx=(0, 8), pady=4)

            def toggle_accordion(btn, current_pl=pl, current_sub=sub_frame, state=toggle_state, current_id=pl_id):
                if state["expanded"]:
                    current_sub.pack_forget()
                    btn.configure(text="⌄ Videos")
                    state["expanded"] = False
                else:
                    current_sub.pack(fill="x", padx=12, pady=(0, 10))
                    btn.configure(text="⌃ Hide")
                    state["expanded"] = True

                    if not state["loaded"]:
                        for child in current_sub.winfo_children():
                            child.destroy()
                        loading_lbl = ctk.CTkLabel(current_sub, text="Fetching playlist videos... Please wait", text_color=MUTED, font=ctk.CTkFont(size=11))
                        loading_lbl.pack(padx=12, pady=12)

                        def fetch_task():
                            try:
                                _, fetched_vids = fetch_playlist_info(current_pl["url"], max_items=0)
                                current_pl["videos"] = fetched_vids
                                state["loaded"] = True
                                def on_fetched():
                                    render_playlist_videos(current_pl, current_sub, current_id)
                                self.after(0, on_fetched)
                            except Exception as ex:
                                def on_err(err_text=str(ex)):
                                    for child in current_sub.winfo_children():
                                        child.destroy()
                                    ctk.CTkLabel(current_sub, text=f"Could not load videos: {err_text[:60]}", text_color=DANGER_TEXT, font=ctk.CTkFont(size=11)).pack(padx=12, pady=10)
                                self.after(0, on_err)

                        threading.Thread(target=fetch_task, daemon=True).start()
                    else:
                        if not current_sub.winfo_children():
                            render_playlist_videos(current_pl, current_sub, current_id)

            arrow_btn = ctk.CTkButton(
                top_bar,
                text="⌄ Videos",
                width=85,
                height=26,
                corner_radius=6,
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color=SECONDARY_BTN,
                hover_color=SECONDARY_BTN_HOVER,
                text_color=BLUE,
            )
            arrow_btn.configure(command=lambda b=arrow_btn, p=pl, s=sub_frame, st=toggle_state, pid=pl_id: toggle_accordion(b, p, s, st, pid))
            arrow_btn.grid(row=0, column=3, padx=(8, 0))
            pl_expand_toggles[pl_id] = lambda b=arrow_btn, p=pl, s=sub_frame, st=toggle_state, pid=pl_id: toggle_accordion(b, p, s, st, pid)

        # Footer buttons and actions

        status_bar = ctk.CTkLabel(footer, text="", text_color=MUTED, font=ctk.CTkFont(size=11))
        status_bar.pack(side="left")

        ctk.CTkButton(footer, text="Cancel", width=85, fg_color=SECONDARY_BTN, hover_color=SECONDARY_BTN_HOVER, text_color=INK, command=modal.destroy).pack(side="right", padx=(8, 0))

        def on_confirm_batch_download():
            sel_quality = modal_quality_var.get()
            chosen_pls = [p for p, v in zip(playlists, pl_vars) if v.get()]
            if not chosen_pls:
                messagebox.showwarning("No Selection", "Please select at least one playlist to download.")
                return

            download_btn.configure(state="disabled")
            status_bar.configure(text="Preparing videos for download... Please wait.")

            def background_gather():
                final_video_list = []
                for p, v in zip(playlists, pl_vars):
                    if not v.get():
                        continue
                    # Fetch videos if not loaded
                    if not p.get("videos"):
                        try:
                            _, vids = fetch_playlist_info(p["url"], max_items=0)
                            p["videos"] = vids
                        except Exception:
                            p["videos"] = []

                    pid = p["id"]
                    if pid in pl_video_vars:
                        # Only take checked videos
                        v_vars = pl_video_vars[pid]
                        for vid, vv in zip(p.get("videos", []), v_vars):
                            if vv.get():
                                final_video_list.append(vid)
                    else:
                        final_video_list.extend(p.get("videos", []))

                def finish_queue():
                    if not final_video_list:
                        download_btn.configure(state="normal")
                        status_bar.configure(text="")
                        messagebox.showwarning("No Videos", "No videos were found to download from the selected playlists.")
                        return

                    modal.destroy()
                    self._queue_batch_with_numbering(final_video_list, sel_quality)
                    self.show_page("downloads")
                    messagebox.showinfo(
                        "Queue Updated",
                        f"Added {len(final_video_list)} videos from {len(chosen_pls)} playlist(s) to the queue!",
                    )

                self.after(0, finish_queue)

            threading.Thread(target=background_gather, daemon=True).start()

        download_btn = ctk.CTkButton(
            footer,
            text=f"Download Selected Playlists ({len(playlists)})",
            width=215,
            fg_color=BLUE,
            hover_color=BLUE_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=on_confirm_batch_download,
        )
        download_btn.pack(side="right")

    def _show_playlist_selection_modal(self, playlist_title: str, entries: list[dict], order: str = "latest_first") -> None:
        clean_title = playlist_title[:65] + ("..." if len(playlist_title) > 65 else "")
        sel_quality = self.quality_var.get() if hasattr(self, "quality_var") else "Best Available"

        def _on_download(chosen: list[dict], quality: str = sel_quality) -> None:
            self._queue_batch_with_numbering(chosen, quality)
            self.show_page("downloads")
            messagebox.showinfo("Downloads Started", f"Queued {len(chosen)} video(s) from {clean_title}!")

        VideoGridModal(
            self,
            title=clean_title,
            videos=entries,
            on_download_selected=_on_download,
            initial_quality=sel_quality,
            order=order,
        )


    def _get_cookie_source_for_url(self, url: str) -> str | None:
        platform = detect_platform_from_url(url)
        # 1. User explicit configuration
        explicit = self.settings.authorized_accounts.get(platform)
        if explicit:
            return explicit
        if platform in {"x", "twitter"}:
            explicit_x = self.settings.authorized_accounts.get("x") or self.settings.authorized_accounts.get("twitter")
            if explicit_x:
                return explicit_x
        if platform in {"youtube", "google"}:
            explicit_yt = self.settings.authorized_accounts.get("youtube") or self.settings.authorized_accounts.get("google")
            if explicit_yt:
                return explicit_yt
        # 2. Check platform-specific synced cookie file
        p_file = get_cookie_file_path(platform)
        if p_file.is_file() and p_file.stat().st_size > 50:
            return str(p_file)
        if platform in {"x", "twitter"}:
            x_file = get_cookie_file_path("x")
            if x_file.is_file() and x_file.stat().st_size > 50:
                return str(x_file)
        if platform in {"youtube", "google"}:
            yt_file = get_cookie_file_path("youtube")
            if yt_file.is_file() and yt_file.stat().st_size > 50:
                return str(yt_file)
        # 3. Check general browser cookie file
        b_file = get_cookie_file_path("browser")
        if b_file.is_file() and b_file.stat().st_size > 50:
            return str(b_file)
        return None

    def prompt_duplicate_confirmation_sync(self, title: str, creator: str, existing_filepath: str) -> bool:
        """
        Thread-safe synchronous prompt. Can be called from a worker thread or the main thread.
        Displays DuplicateConfirmationDialog and waits for user's decision.
        Returns True if user chose [Download Again], False if user chose [Cancel].
        """
        if threading.current_thread() is threading.main_thread():
            done_event = threading.Event()
            result_holder = [False]
            def on_choice(choice: bool):
                result_holder[0] = choice
                done_event.set()
            dialog = DuplicateConfirmationDialog(self, title, creator, existing_filepath, on_choice)
            self.wait_window(dialog)
            return result_holder[0]
        else:
            done_event = threading.Event()
            result_holder = [False]
            def show_dialog():
                def on_choice(choice: bool):
                    result_holder[0] = choice
                    done_event.set()
                DuplicateConfirmationDialog(self, title, creator, existing_filepath, on_choice)
            self.after(0, show_dialog)
            done_event.wait()
            return result_holder[0]

    def _queue_urls(self, urls: list[str]) -> bool:
        if not self._check_device_not_banned():
            return False

        valid, invalid = [], []
        for url in urls:
            parsed = urlparse(url)
            (valid if parsed.scheme in {"http", "https"} and parsed.netloc else invalid).append(url)

        if not valid:
            messagebox.showwarning("No valid links", "Paste one or more public HTTP or HTTPS video URLs.")
            return False

        if len(valid) == 1 and is_playlist_or_channel(valid[0]):
            self._open_playlist_dialog(initial_url=valid[0])
            return True

        # Enforce Daily Free Trial (5 downloads/day for free users)
        can_dl, reason = license_mgr.can_download(len(valid))
        if not can_dl:
            LicenseDialog(self, is_limit_reached=True, on_status_changed=self._update_pro_badge_ui)
            return False

        self.empty_state.pack_forget()
        speed_limit = parse_speed_limit(self.settings.default_speed_limit)
        format_choice = self.format_choice_var.get()
        selected_quality = "Image / Photo" if "Image" in format_choice else self.quality_var.get()
        base_dest = str(self.settings.resolved_download_folder())

        # Check for duplicates in history
        items_to_download: list[tuple[str, bool]] = []
        duplicates: list[tuple[str, DownloadRecord]] = []
        for url in valid:
            record = history_store.find_duplicate(url=url, check_disk=True)
            if record:
                duplicates.append((url, record))

        if len(valid) == 1 and len(duplicates) == 1:
            dup_url, record = duplicates[0]
            confirmed = self.prompt_duplicate_confirmation_sync(
                record.title, record.creator, record.saved_filepath
            )
            if not confirmed:
                messagebox.showinfo("Download Cancelled", "Download cancelled — video already exists.")
                return False
            items_to_download.append((dup_url, True))
        elif duplicates:
            dup_dicts = []
            for u, r in duplicates:
                dup_dicts.append({
                    "url": u,
                    "title": r.title or "Video",
                    "creator": r.creator or "Unknown",
                    "filepath": r.saved_filepath,
                })
            decision_result = ["skip", []]
            def on_decision(dec, sel):
                decision_result[0] = dec
                decision_result[1] = sel

            dialog = BatchDuplicateDialog(self, dup_dicts, on_decision)
            self.wait_window(dialog)
            dec, sel = decision_result[0], decision_result[1]

            dup_urls_set = {u for u, _ in duplicates}
            non_duplicates = [u for u in valid if u not in dup_urls_set]
            for u in non_duplicates:
                items_to_download.append((u, False))

            if dec == "download_all":
                for u, _ in duplicates:
                    items_to_download.append((u, True))
            elif dec == "download_selected":
                selected_urls = {item["url"] for item in sel}
                for u in selected_urls:
                    items_to_download.append((u, True))
        else:
            for url in valid:
                items_to_download.append((url, False))

        if not items_to_download:
            messagebox.showinfo("No Downloads Queued", "All duplicate videos were skipped.")
            return True

        license_mgr.record_downloads(len(items_to_download))
        self._update_pro_badge_ui()

        has_multiple = len(items_to_download) > 1
        for num, (url, is_dup) in enumerate(items_to_download, 1):
            cookie_src = self._get_cookie_source_for_url(url)
            p, mid, creator, _ = extract_media_identity(url)
            item_numbering = num if has_multiple else None
            initial_filename = f"{item_numbering:02d}. Analyzing video…" if item_numbering else "Analyzing video…"
            task = DownloadTask(
                url=url,
                destination=base_dest,
                quality=selected_quality,
                speed_limit_bps=speed_limit,
                cookies_source=cookie_src,
                filename=initial_filename,
                numbering=item_numbering,
                creator=creator,
                media_id=mid,
                platform=p,
                is_duplicate_copy=is_dup,
                on_duplicate_prompt=self.prompt_duplicate_confirmation_sync,
            )
            self.tasks[task.id] = task
            item = DownloadItem(
                self.list_frame,
                task,
                self._cancel,
                self._retry,
                self._pause,
                self._resume,
                self._show_task_menu,
            )
            item.pack(fill="x", padx=6, pady=5)
            self.items[task.id] = item
            self.manager.add(task)

        self._filter_task_list()

        if invalid:
            messagebox.showwarning("Some links skipped", f"{len(invalid)} line(s) were not valid HTTP/HTTPS URLs.")
        return True

    def _cancel(self, task: DownloadTask) -> None:
        task.cancel_event.set()
        with task.lock:
            if task.status in {DownloadStatus.QUEUED, DownloadStatus.FETCHING_INFO, DownloadStatus.DOWNLOADING, DownloadStatus.CONVERTING}:
                task.status = DownloadStatus.CANCELLED

    def _pause(self, task: DownloadTask) -> None:
        self.manager.pause(task)

    def _resume(self, task: DownloadTask) -> None:
        self.manager.resume(task)

    def _retry(self, task: DownloadTask) -> None:
        self.manager.retry(task)

    def _show_task_menu(self, task: DownloadTask, x: int, y: int) -> None:
        menu = Menu(self, tearoff=False)
        menu.add_command(label="📋 Copy Video Link", command=lambda: self._copy_task_url(task))
        menu.add_separator()
        if task.status in {DownloadStatus.FAILED, DownloadStatus.CANCELLED}:
            menu.add_command(label="🔄 Retry Download", command=lambda: self._retry(task))
        elif task.status in {DownloadStatus.DOWNLOADING, DownloadStatus.QUEUED}:
            menu.add_command(label="⏸ Pause", command=lambda: self._pause(task))
        elif task.status == DownloadStatus.PAUSED:
            menu.add_command(label="▶ Resume", command=lambda: self._resume(task))
        if task.status not in {DownloadStatus.COMPLETED, DownloadStatus.CANCELLED, DownloadStatus.FAILED}:
            menu.add_command(label="✕ Cancel", command=lambda: self._cancel(task))
        menu.add_separator()
        menu.add_command(label="🗑 Delete", command=lambda: self._confirm_delete([task]))
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _copy_task_url(self, task: DownloadTask) -> None:
        if not task or not task.url:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(task.url)
            self.update()
            messagebox.showinfo("Link Copied", f"Video link copied to clipboard:\n\n{task.url}")
        except Exception:
            pass

    def _delete_all(self) -> None:
        if self.tasks:
            self._confirm_delete(list(self.tasks.values()), all_items=True)

    def _confirm_delete(self, tasks: list[DownloadTask], all_items: bool = False) -> None:
        count = len(tasks)
        dialog = ctk.CTkToplevel(self)
        dialog.title("Delete downloads")
        dialog.geometry("460x240")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color=BACKGROUND)

        heading = "Delete all downloads?" if all_items else "Delete this download?"
        ctk.CTkLabel(dialog, text=heading, text_color=INK, font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=24, pady=(20, 4))
        ctk.CTkLabel(dialog, text=f"This will remove {count} item(s) from your queue.", text_color=MUTED).pack(anchor="w", padx=24)

        remove_files = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(dialog, text="Also delete downloaded files from disk", variable=remove_files, text_color=INK, fg_color=BLUE).pack(anchor="w", padx=24, pady=(18, 12))

        footer = ctk.CTkFrame(dialog, fg_color="transparent")
        footer.pack(fill="x", side="bottom", padx=24, pady=18)

        ctk.CTkButton(footer, text="Cancel", width=80, fg_color=SECONDARY_BTN, hover_color=SECONDARY_BTN_HOVER, text_color=INK, command=dialog.destroy).pack(side="right", padx=(8, 0))

        def confirm() -> None:
            for task in tasks:
                task.delete_file_on_remove = remove_files.get()
                task.cancel_event.set()

                # Safe file deletion on Windows without locking crashes
                if remove_files.get() and task.output_path:
                    target_file = Path(task.output_path)

                    def safe_unlink(f_path: Path):
                        for _ in range(6):
                            try:
                                if f_path.is_file():
                                    f_path.unlink()
                                break
                            except OSError:
                                time.sleep(0.3)

                    threading.Thread(target=safe_unlink, args=(target_file,), daemon=True).start()

                item = self.items.pop(task.id, None)
                if item:
                    item.destroy()
                self.tasks.pop(task.id, None)

            if not self.tasks:
                self.empty_state.pack(expand=True, pady=65)
            dialog.destroy()

        ctk.CTkButton(footer, text="Delete", width=80, fg_color=DANGER_TEXT, hover_color="#B91C1C", command=confirm).pack(side="right")

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=str(self.settings.resolved_download_folder()))
        if selected:
            self.settings.download_folder = selected
            self.store.save(self.settings)
            self._update_folder_label()

    def _update_folder_label(self) -> None:
        path_str = str(self.settings.resolved_download_folder())
        text = f"Save to: {path_str}"
        if hasattr(self, "folder_label"):
            self.folder_label.configure(text=text)
        if hasattr(self, "dash_folder_label"):
            self.dash_folder_label.configure(text=text)
        if hasattr(self, "img_folder_label"):
            self.img_folder_label.configure(text=path_str)

    def _open_preferences(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Preferences")
        dialog.geometry("620x420")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(fg_color=BACKGROUND)

        ctk.CTkLabel(dialog, text="Preferences", text_color=INK, font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", padx=26, pady=(22, 2))
        ctk.CTkLabel(dialog, text="Configure defaults for downloads, concurrency, and appearance.", text_color=MUTED).pack(anchor="w", padx=26, pady=(0, 16))

        card = ctk.CTkFrame(dialog, corner_radius=12, fg_color=SURFACE, border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=26)
        card.grid_columnconfigure((0, 1), weight=1)

        # Folder row
        ctk.CTkLabel(card, text="Default Download Folder", text_color=INK, font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 4))
        folder_value = ctk.StringVar(value=str(self.settings.resolved_download_folder()))
        folder_entry = ctk.CTkEntry(card, textvariable=folder_value, height=34, border_color=BORDER, fg_color=SURFACE, text_color=INK)
        folder_entry.grid(row=1, column=0, sticky="ew", padx=(16, 8), pady=(0, 14))

        def pick_folder() -> None:
            selected = filedialog.askdirectory(initialdir=folder_value.get())
            if selected:
                folder_value.set(selected)

        ctk.CTkButton(card, text="Change", width=75, height=34, fg_color=SECONDARY_BTN, hover_color=SECONDARY_BTN_HOVER, text_color=BLUE, command=pick_folder).grid(row=1, column=1, padx=(0, 16), pady=(0, 14), sticky="w")

        # Concurrency & Appearance
        ctk.CTkLabel(card, text="Concurrent Downloads", text_color=INK, font=ctk.CTkFont(size=12, weight="bold")).grid(row=2, column=0, sticky="w", padx=16, pady=(0, 4))
        limit_value = ctk.StringVar(value=str(self.settings.simultaneous_downloads))
        ctk.CTkOptionMenu(card, values=[str(n) for n in range(1, 11)], variable=limit_value, width=120).grid(row=3, column=0, sticky="w", padx=16, pady=(0, 14))

        ctk.CTkLabel(card, text="Appearance Mode", text_color=INK, font=ctk.CTkFont(size=12, weight="bold")).grid(row=2, column=1, sticky="w", padx=16, pady=(0, 4))
        appearance_value = ctk.StringVar(value=self.settings.appearance_mode)
        ctk.CTkOptionMenu(card, values=["System", "Light", "Dark"], variable=appearance_value, width=120).grid(row=3, column=1, sticky="w", padx=16, pady=(0, 14))

        # Default Quality & Speed
        ctk.CTkLabel(card, text="Default Quality", text_color=INK, font=ctk.CTkFont(size=12, weight="bold")).grid(row=4, column=0, sticky="w", padx=16, pady=(0, 4))
        pref_quality_value = ctk.StringVar(value=self.settings.default_quality if self.settings.default_quality in QUALITY_OPTIONS else "Best Available")
        ctk.CTkOptionMenu(card, values=QUALITY_OPTIONS, variable=pref_quality_value, width=140).grid(row=5, column=0, sticky="w", padx=16, pady=(0, 16))

        ctk.CTkLabel(card, text="Default Speed Limit", text_color=INK, font=ctk.CTkFont(size=12, weight="bold")).grid(row=4, column=1, sticky="w", padx=16, pady=(0, 4))
        pref_speed_value = ctk.StringVar(value=self.settings.default_speed_limit)
        ctk.CTkOptionMenu(card, values=["Unlimited", "10 MB/s", "5 MB/s", "2 MB/s", "1 MB/s", "500 KB/s"], variable=pref_speed_value, width=120).grid(row=5, column=1, sticky="w", padx=16, pady=(0, 16))

        def save() -> None:
            self.settings.download_folder = folder_value.get().strip()
            self.settings.simultaneous_downloads = int(limit_value.get())
            self.settings.appearance_mode = appearance_value.get()
            self.settings.default_quality = pref_quality_value.get()
            self.settings.default_speed_limit = pref_speed_value.get()
            self.store.save(self.settings)

            self.quality_var.set(self.settings.default_quality)
            self.speed_var.set(self.settings.default_speed_limit)
            self.manager.set_worker_limit(self.settings.simultaneous_downloads)
            self._update_folder_label()
            self._set_appearance_mode(self.settings.appearance_mode)
            dialog.destroy()

        footer = ctk.CTkFrame(dialog, fg_color="transparent")
        footer.pack(fill="x", padx=26, pady=18)

        ctk.CTkButton(footer, text="Cancel", width=80, fg_color=SECONDARY_BTN, hover_color=SECONDARY_BTN_HOVER, text_color=INK, command=dialog.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(footer, text="Save changes", width=110, fg_color=BLUE, hover_color=BLUE_HOVER, command=save).pack(side="right")

    def _schedule_refresh(self) -> None:
        self._refresh_job = self.after(300, self._refresh)

    def _refresh(self) -> None:
        if not self.winfo_exists():
            return
        active = 0
        for task_id, item in list(self.items.items()):
            item.refresh()
            t = self.tasks[task_id]
            if t.status in (DownloadStatus.DOWNLOADING, DownloadStatus.CONVERTING):
                active += 1
            elif t.status == DownloadStatus.COMPLETED:
                if not getattr(t, "_telemetry_reported", False):
                    t._telemetry_reported = True
                    try:
                        telemetry_service.report_download_event_async(
                            machine_id=license_mgr.machine_id,
                            url=t.url,
                            bytes_downloaded=t.downloaded or t.total or 0,
                        )
                    except Exception:
                        pass
        total = len(self.tasks)
        if hasattr(self, "queue_label"):
            self.queue_label.configure(text=f"{active} active  •  {total} total" if total else "No downloads yet")
        if getattr(self, "_current_page", "") == "dashboard":
            self._refresh_dashboard_metrics()
        self._schedule_refresh()

    # -------------------------------------------------------------
    # Telemetry, Ban Checking & Owner Dashboard Helpers
    # -------------------------------------------------------------
    def _init_telemetry_and_ban_check(self) -> None:
        def _check_worker():
            try:
                is_pro = license_mgr.is_pro()
                tier = license_mgr.get_license_tier()
                telemetry_service.report_session_start_async(license_mgr.machine_id, is_pro, tier)
                is_banned, reason = telemetry_service.check_device_ban(license_mgr.machine_id)
                if is_banned:
                    self.after(0, lambda: self._show_device_suspended_lock(reason))
            except Exception:
                pass

        threading.Thread(target=_check_worker, daemon=True).start()

    def _show_device_suspended_lock(self, reason: str = "") -> None:
        if getattr(self, "_device_suspended_shown", False):
            return
        self._device_suspended_shown = True
        msg = (
            f"🚫 ACCESS SUSPENDED\n\n"
            f"This machine (Device ID: {license_mgr.machine_id}) has been suspended by the administrator.\n\n"
            f"Reason: {reason or 'Unauthorized access or license revocation'}\n\n"
            f"All downloads and features have been disabled on this computer.\n\n"
            f"Contact administrator for reinstatement:\n"
            f"Jaidijutt0012@gmail.com"
        )
        messagebox.showerror("Device Suspended", msg, parent=self)

    def _check_device_not_banned(self) -> bool:
        try:
            is_banned, reason = telemetry_service.check_device_ban(license_mgr.machine_id)
            if is_banned:
                self._show_device_suspended_lock(reason)
                return False
        except Exception:
            pass
        return True

    def _close(self) -> None:
        if self._refresh_job is not None:
            try:
                self.after_cancel(self._refresh_job)
            except Exception:
                pass
        self.store.save(self.settings)
        if hasattr(self, "ipc_server") and self.ipc_server:
            try:
                self.ipc_server.stop()
            except Exception:
                pass
        self.manager.shutdown()
        self.destroy()


DeepXVisionApp = HQVideoDownloaderApp

