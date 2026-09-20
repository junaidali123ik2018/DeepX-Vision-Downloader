from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable
import customtkinter as ctk

from app.settings import AppSettings
from ui.browser_window import BrowserManager, get_cookie_file_path
from app.license import license_mgr
from app.updater import check_for_updates, update_core_engine_ytdlp
from app.version import APP_NAME, APP_EDITION, APP_VERSION
from ui.update_modal import UpdateModal


def is_platform_cookie_authenticated(platform: str, path_or_src: str | Path | None) -> bool:
    """Verifies that a cookie file actually contains valid authentication session cookies rather than guest/anonymous cookies."""
    if not path_or_src:
        return False
    src_str = str(path_or_src).strip()
    if src_str.lower() in {"chrome", "firefox", "edge", "opera", "brave", "safari"}:
        return True

    p = Path(src_str)
    if not p.is_file() or p.stat().st_size < 30:
        return False

    try:
        content = p.read_text(encoding="utf-8", errors="ignore")
        p_lower = platform.lower()
        if "instagram" in p_lower:
            return ("sessionid" in content or "ds_user_id" in content)
        elif "youtube" in p_lower or "google" in p_lower:
            return ("SAPISID" in content or "SSID" in content or "LOGIN_INFO" in content or "__Secure-3PSID" in content)
        elif "tiktok" in p_lower:
            return ("sessionid" in content or "sid_tt" in content or "sessionid_ss" in content)
        elif "facebook" in p_lower:
            return ("c_user" in content or "xs" in content)
        elif "twitter" in p_lower or p_lower == "x":
            return ("auth_token" in content or "ct0" in content)
        return p.stat().st_size > 300
    except Exception:
        return False


class SettingsDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        settings: AppSettings,
        on_save: Callable[[AppSettings], None],
        initial_tab: str = "basic",
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.on_save = on_save

        self.title("Settings")
        self.geometry("740x520")
        self.resizable(False, False)
        self.configure(fg_color="#111827")
        self.transient(parent)
        self.grab_set()

        # Main Layout: Left Sidebar + Right Content
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left Tabs Sidebar
        self.sidebar = ctk.CTkFrame(self, width=160, corner_radius=0, fg_color="#182234")
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        # Right Content Container
        self.content_area = ctk.CTkFrame(self, fg_color="#111827", corner_radius=0)
        self.content_area.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.content_area.grid_columnconfigure(0, weight=1)
        self.content_area.grid_rowconfigure(0, weight=1)

        # Sidebar Buttons
        self.nav_btns: dict[str, ctk.CTkButton] = {}
        items = [
            ("basic", "📋", "Basic"),
            ("download", "⬇", "Download"),
            ("auth", "👤", "Authorization"),
            ("license", "👑", "License & Pro"),
            ("about", "ℹ", "About"),
        ]

        ctk.CTkLabel(
            self.sidebar,
            text="Settings",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#F8FAFC",
        ).pack(anchor="w", padx=16, pady=(20, 16))

        for key, icon, name in items:
            btn = ctk.CTkButton(
                self.sidebar,
                text=f"  {icon}  {name}",
                anchor="w",
                height=38,
                corner_radius=6,
                fg_color="transparent",
                hover_color="#2563EB",
                text_color="#94A3B8",
                font=ctk.CTkFont(size=13),
                command=lambda k=key: self.switch_tab(k),
            )
            btn.pack(fill="x", padx=10, pady=3)
            self.nav_btns[key] = btn

        # Build Tab Pages
        self.pages: dict[str, ctk.CTkFrame] = {}
        self._build_basic_tab()
        self._build_download_tab()
        self._build_auth_tab()
        self._build_license_tab()
        self._build_about_tab()

        self.switch_tab(initial_tab)

    def switch_tab(self, key: str) -> None:
        for k, page in self.pages.items():
            page.grid_forget()
        for k, btn in self.nav_btns.items():
            if k == key:
                btn.configure(fg_color="#2563EB", text_color="#FFFFFF")
            else:
                btn.configure(fg_color="transparent", text_color="#94A3B8")

        if key in self.pages:
            self.pages[key].grid(row=0, column=0, sticky="nsew")

    def _build_basic_tab(self) -> None:
        page = ctk.CTkFrame(self.content_area, fg_color="transparent")
        self.pages["basic"] = page

        ctk.CTkLabel(page, text="Basic Settings", font=ctk.CTkFont(size=18, weight="bold"), text_color="#F8FAFC").pack(
            anchor="w", pady=(0, 16)
        )

        card = ctk.CTkFrame(page, fg_color="#1E293B", corner_radius=10)
        card.pack(fill="x", pady=6)

        # Language
        lang_row = ctk.CTkFrame(card, fg_color="transparent")
        lang_row.pack(fill="x", padx=16, pady=12)
        ctk.CTkLabel(lang_row, text="Language", text_color="#F8FAFC", font=ctk.CTkFont(size=13, weight="bold")).pack(
            side="left"
        )
        ctk.CTkOptionMenu(
            lang_row,
            values=["English", "Urdu", "Hindi", "Spanish", "French"],
            width=140,
            fg_color="#2D3A4F",
            button_color="#3B82F6",
        ).pack(side="right")

        # App Settings checkboxes
        app_set = ctk.CTkFrame(page, fg_color="#1E293B", corner_radius=10)
        app_set.pack(fill="x", pady=12)

        ctk.CTkLabel(app_set, text="App Settings", text_color="#F8FAFC", font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=16, pady=(12, 8)
        )

        self.float_var = ctk.BooleanVar(value=self.settings.display_floating_window)
        ctk.CTkCheckBox(
            app_set,
            text="Display floating download window",
            variable=self.float_var,
            text_color="#CBD5E1",
            fg_color="#3B82F6",
            command=self._save_basic,
        ).pack(anchor="w", padx=16, pady=6)

        self.bg_var = ctk.BooleanVar(value=self.settings.run_in_background)
        ctk.CTkCheckBox(
            app_set,
            text="Run in the background after closing",
            variable=self.bg_var,
            text_color="#CBD5E1",
            fg_color="#3B82F6",
            command=self._save_basic,
        ).pack(anchor="w", padx=16, pady=6)

        self.clip_var = ctk.BooleanVar(value=getattr(self.settings, "monitor_clipboard", True))
        ctk.CTkCheckBox(
            app_set,
            text="Smart clipboard auto-detector (prompt when video link copied)",
            variable=self.clip_var,
            text_color="#CBD5E1",
            fg_color="#3B82F6",
            command=self._save_basic,
        ).pack(anchor="w", padx=16, pady=(6, 16))

    def _save_basic(self) -> None:
        self.settings.display_floating_window = self.float_var.get()
        self.settings.run_in_background = self.bg_var.get()
        self.settings.monitor_clipboard = self.clip_var.get()
        self.on_save(self.settings)

    def _build_download_tab(self) -> None:
        page = ctk.CTkFrame(self.content_area, fg_color="transparent")
        self.pages["download"] = page

        ctk.CTkLabel(page, text="Download Preferences", font=ctk.CTkFont(size=18, weight="bold"), text_color="#F8FAFC").pack(
            anchor="w", pady=(0, 16)
        )

        card = ctk.CTkFrame(page, fg_color="#1E293B", corner_radius=10)
        card.pack(fill="x", pady=6)

        # Folder row
        f_row = ctk.CTkFrame(card, fg_color="transparent")
        f_row.pack(fill="x", padx=16, pady=12)
        ctk.CTkLabel(f_row, text="Save location :", text_color="#94A3B8").pack(side="left")
        self.folder_var = ctk.StringVar(value=str(self.settings.resolved_download_folder()))
        ctk.CTkEntry(f_row, textvariable=self.folder_var, height=30, fg_color="#111827", text_color="#F8FAFC").pack(
            side="left", fill="x", expand=True, padx=8
        )
        ctk.CTkButton(
            f_row,
            text="📁 Browse",
            width=80,
            height=30,
            fg_color="#334155",
            hover_color="#3B82F6",
            command=self._browse_dl_folder,
        ).pack(side="right")

        # Concurrency
        c_row = ctk.CTkFrame(card, fg_color="transparent")
        c_row.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(c_row, text="Simultaneous downloads :", text_color="#94A3B8").pack(side="left")
        self.simul_var = ctk.IntVar(value=self.settings.simultaneous_downloads)
        ctk.CTkOptionMenu(
            c_row,
            values=["1", "2", "3", "5", "8", "10"],
            variable=ctk.StringVar(value=str(self.settings.simultaneous_downloads)),
            width=80,
            fg_color="#2D3A4F",
            command=lambda v: self._set_simul(int(v)),
        ).pack(side="right")

        # Speed limit
        s_row = ctk.CTkFrame(card, fg_color="transparent")
        s_row.pack(fill="x", padx=16, pady=(8, 14))
        ctk.CTkLabel(s_row, text="Speed limit :", text_color="#94A3B8").pack(side="left")
        self.speed_var = ctk.StringVar(value=self.settings.default_speed_limit)
        ctk.CTkOptionMenu(
            s_row,
            values=["Unlimited", "5 MB/s", "2 MB/s", "1 MB/s", "500 KB/s"],
            variable=self.speed_var,
            width=120,
            fg_color="#2D3A4F",
            command=self._set_speed,
        ).pack(side="right")

    def _browse_dl_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.folder_var.get())
        if chosen:
            self.folder_var.set(chosen)
            self.settings.download_folder = chosen
            self.on_save(self.settings)

    def _set_simul(self, val: int) -> None:
        self.settings.simultaneous_downloads = val
        self.on_save(self.settings)

    def _set_speed(self, val: str) -> None:
        self.settings.default_speed_limit = val
        self.on_save(self.settings)

    def _build_auth_tab(self) -> None:
        page = ctk.CTkFrame(self.content_area, fg_color="transparent")
        self.pages["auth"] = page

        ctk.CTkLabel(page, text="Authorization", font=ctk.CTkFont(size=18, weight="bold"), text_color="#F8FAFC").pack(
            anchor="w", pady=(0, 4)
        )

        ctk.CTkLabel(
            page,
            text="Account authorization is only used for video downloads. After authorization, you can download some private or members-only content.",
            text_color="#94A3B8",
            font=ctk.CTkFont(size=11),
            wraplength=520,
            justify="left",
        ).pack(anchor="w", pady=(0, 14))

        # Platform list card
        card = ctk.CTkFrame(page, fg_color="#1E293B", corner_radius=10)
        card.pack(fill="both", expand=True)

        platforms = [
            ("youtube", "YouTube", "▶", "#EF4444"),
            ("instagram", "Instagram", "📷", "#E1306C"),
            ("facebook", "Facebook", "f", "#1877F2"),
            ("tiktok", "TikTok", "♪", "#00F2FE"),
            ("x", "X / Twitter", "𝕏", "#FFFFFF"),
        ]

        self.auth_labels: dict[str, ctk.CTkLabel] = {}
        self.auth_btns: dict[str, ctk.CTkButton] = {}

        for key, name, icon, color in platforms:
            row = ctk.CTkFrame(card, fg_color="transparent", height=48)
            row.pack(fill="x", padx=16, pady=4)
            row.pack_propagate(False)

            # Icon badge
            icon_lbl = ctk.CTkLabel(
                row,
                text=icon,
                width=28,
                height=28,
                corner_radius=6,
                fg_color="#0F172A",
                text_color=color,
                font=ctk.CTkFont(size=14, weight="bold"),
            )
            icon_lbl.pack(side="left")

            name_lbl = ctk.CTkLabel(
                row,
                text=f"  {name}",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#F8FAFC",
            )
            name_lbl.pack(side="left")

            source = self.settings.authorized_accounts.get(key)
            b_cookie = get_cookie_file_path(key)
            is_authed = False
            display_source = source

            if source and source in {"chrome", "firefox", "edge", "opera", "brave"}:
                is_authed = True
            elif source and is_platform_cookie_authenticated(key, source):
                is_authed = True
            elif is_platform_cookie_authenticated(key, b_cookie):
                is_authed = True
                display_source = "Built-in Browser"
                self.settings.authorized_accounts[key] = str(b_cookie)
            else:
                if source and not is_platform_cookie_authenticated(key, source):
                    self.settings.authorized_accounts.pop(key, None)
                is_authed = False
                display_source = None

            status_text = f"Authorized ({display_source})" if is_authed else "Not logged in or expired"
            status_color = "#34D399" if is_authed else "#F59E0B"

            status_lbl = ctk.CTkLabel(
                row,
                text=status_text,
                font=ctk.CTkFont(size=11),
                text_color=status_color,
            )
            status_lbl.pack(side="left", padx=24)
            self.auth_labels[key] = status_lbl

            # Action button
            btn_text = "Log Out" if is_authed else "Log In"
            btn_color = "#475569" if is_authed else "#2563EB"
            btn = ctk.CTkButton(
                row,
                text=btn_text,
                width=80,
                height=28,
                corner_radius=6,
                fg_color=btn_color,
                hover_color="#1D4ED8",
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda k=key, n=name: self._handle_auth_click(k, n),
            )
            btn.pack(side="right")
            self.auth_btns[key] = btn

    def _handle_auth_click(self, key: str, name: str) -> None:
        existing = self.settings.authorized_accounts.get(key)
        b_cookie = get_cookie_file_path(key)
        is_authed = (
            (existing and existing in {"chrome", "firefox", "edge", "opera", "brave"})
            or is_platform_cookie_authenticated(key, existing)
            or is_platform_cookie_authenticated(key, b_cookie)
        )
        if is_authed:
            # Logout
            if messagebox.askyesno("Log Out", f"Remove authorization for {name}?"):
                self.settings.authorized_accounts.pop(key, None)
                p = get_cookie_file_path(key)
                if p.is_file():
                    try:
                        p.unlink()
                    except Exception:
                        pass
                self.on_save(self.settings)
                self.auth_labels[key].configure(text="Not logged in or expired", text_color="#F59E0B")
                self.auth_btns[key].configure(text="Log In", fg_color="#2563EB")
            return

        # Offer login options
        choice_win = ctk.CTkToplevel(self)
        choice_win.title(f"Authorize {name}")
        choice_win.geometry("420x290")
        choice_win.resizable(False, False)
        choice_win.configure(fg_color="#1E293B")
        choice_win.transient(self)
        choice_win.grab_set()

        ctk.CTkLabel(
            choice_win,
            text=f"Authorize {name}",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#F8FAFC",
        ).pack(pady=(16, 6))

        ctk.CTkLabel(
            choice_win,
            text="Choose how you'd like to link your account:\n(For best results, import a cookies.txt file exported from your browser)",
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8",
            justify="center",
        ).pack(pady=(0, 12))

        # Option 1: Browser cookies (Chrome / Edge / Firefox)
        def _use_browser(browser_name: str) -> None:
            self.settings.authorized_accounts[key] = browser_name
            self.on_save(self.settings)
            self.auth_labels[key].configure(text=f"Authorized ({browser_name})", text_color="#34D399")
            self.auth_btns[key].configure(text="Log Out", fg_color="#475569")
            choice_win.destroy()
            messagebox.showinfo("Success", f"{name} authorized successfully using {browser_name.title()} session!\nNote: Ensure {browser_name.title()} is closed when downloading so cookies can be accessed.")

        def _import_file() -> None:
            file_path = filedialog.askopenfilename(
                title=f"Select {name} Cookies File",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            )
            if file_path:
                authed = is_platform_cookie_authenticated(key, file_path)
                if not authed:
                    if not messagebox.askyesno("Warning", f"This cookies file doesn't seem to have logged-in session cookies for {name}. Use it anyway?"):
                        return
                self.settings.authorized_accounts[key] = file_path
                self.on_save(self.settings)
                self.auth_labels[key].configure(text="Authorized (File)", text_color="#34D399")
                self.auth_btns[key].configure(text="Log Out", fg_color="#475569")
                choice_win.destroy()
                messagebox.showinfo("Success", f"Cookies imported for {name}!")

        def _use_in_app_browser() -> None:
            login_urls = {
                "instagram": "https://www.instagram.com/accounts/login/",
                "youtube": "https://accounts.google.com/ServiceLogin?service=youtube",
                "tiktok": "https://www.tiktok.com/login",
                "facebook": "https://www.facebook.com/login/",
                "x": "https://x.com/i/flow/login",
            }
            target_url = login_urls.get(key, "https://www.google.com")
            BrowserManager.open_browser(target_url)
            choice_win.destroy()
            messagebox.showinfo(
                "Browser Opened",
                f"The In-App Browser has opened for {name}.\n\nPlease enter your login credentials inside the browser window.\nOnce logged in, your session is saved automatically!",
            )

        btn_box = ctk.CTkFrame(choice_win, fg_color="transparent")
        btn_box.pack(fill="x", padx=28)

        ctk.CTkButton(
            btn_box,
            text="🌐 Log In via Built-in Browser (Automatic)",
            height=36,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=_use_in_app_browser,
        ).pack(fill="x", pady=(4, 6))

        ctk.CTkButton(
            btn_box,
            text="📁 Import cookies.txt File",
            height=32,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=12),
            command=_import_file,
        ).pack(fill="x", pady=4)

        ctk.CTkButton(
            btn_box,
            text="🌐 Use Chrome / Edge Session",
            height=32,
            fg_color="#334155",
            hover_color="#475569",
            command=lambda: _use_browser("chrome"),
        ).pack(fill="x", pady=4)

        ctk.CTkButton(
            btn_box,
            text="🦊 Use Firefox Session",
            height=32,
            fg_color="#1E2230",
            hover_color="#2D3548",
            command=lambda: _use_browser("firefox"),
        ).pack(fill="x", pady=4)

    def _build_license_tab(self) -> None:
        page = ctk.CTkFrame(self.content_area, fg_color="transparent")
        self.pages["license"] = page

        ctk.CTkLabel(page, text="License & Pro Edition", font=ctk.CTkFont(size=18, weight="bold"), text_color="#F8FAFC").pack(
            anchor="w", pady=(0, 16)
        )

        card = ctk.CTkFrame(page, fg_color="#1E293B", corner_radius=10)
        card.pack(fill="x", pady=6)

        # Current Status
        s_row = ctk.CTkFrame(card, fg_color="transparent")
        s_row.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(s_row, text="Status:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94A3B8").pack(side="left")
        
        status_col = "#34D399" if license_mgr.is_pro() else "#F59E0B"
        self.settings_lic_status = ctk.CTkLabel(
            s_row,
            text=license_mgr.get_status_text(),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=status_col,
        )
        self.settings_lic_status.pack(side="left", padx=8)

        # Machine ID
        m_row = ctk.CTkFrame(card, fg_color="transparent")
        m_row.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(m_row, text="Machine ID:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94A3B8").pack(side="left")
        ctk.CTkLabel(m_row, text=license_mgr.machine_id, font=ctk.CTkFont(family="Consolas", size=12, weight="bold"), text_color="#38BDF8").pack(side="left", padx=8)

        def copy_mid():
            self.clipboard_clear()
            self.clipboard_append(license_mgr.machine_id)
            messagebox.showinfo("Copied", "Machine ID copied to clipboard!")

        ctk.CTkButton(m_row, text="📋 Copy ID", width=80, height=26, fg_color="#334155", hover_color="#475569", command=copy_mid).pack(side="right")

        # License Key entry
        k_card = ctk.CTkFrame(page, fg_color="#1E293B", corner_radius=10)
        k_card.pack(fill="x", pady=10)

        ctk.CTkLabel(k_card, text="Enter License Key:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#F8FAFC").pack(anchor="w", padx=16, pady=(12, 4))

        key_input_row = ctk.CTkFrame(k_card, fg_color="transparent")
        key_input_row.pack(fill="x", padx=16, pady=(0, 14))

        self.lic_entry_var = ctk.StringVar(value=license_mgr.license_data.key if license_mgr.is_pro() else "")
        entry = ctk.CTkEntry(
            key_input_row,
            textvariable=self.lic_entry_var,
            placeholder_text="DXVP-XXXX-XXXX-XXXX-XXXX",
            font=ctk.CTkFont(family="Consolas", size=12),
            height=34,
            fg_color="#0F172A",
        )
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        def activate_action():
            k = self.lic_entry_var.get().strip().upper()
            if not k:
                messagebox.showwarning("Enter Key", "Please enter a license key.")
                return
            ok, msg = license_mgr.activate_key(k)
            if ok:
                messagebox.showinfo("Activated! 🎉", msg)
                self.settings_lic_status.configure(text=license_mgr.get_status_text(), text_color="#34D399")
            else:
                messagebox.showerror("Error", msg)

        ctk.CTkButton(key_input_row, text="⚡ Activate", width=95, height=34, fg_color="#2563EB", hover_color="#1D4ED8", font=ctk.CTkFont(size=12, weight="bold"), command=activate_action).pack(side="left", padx=(0, 6))

        if license_mgr.is_pro():
            def deactivate_action():
                if messagebox.askyesno("Deactivate", "Are you sure you want to deactivate the license on this machine?"):
                    license_mgr.deactivate_key()
                    self.settings_lic_status.configure(text=license_mgr.get_status_text(), text_color="#F59E0B")
                    self.lic_entry_var.set("")
            ctk.CTkButton(key_input_row, text="Deactivate", width=85, height=34, fg_color="#451A1A", hover_color="#7F1D1D", text_color="#FCA5A5", command=deactivate_action).pack(side="left")

        # Buy Plans Button
        btn_box = ctk.CTkFrame(page, fg_color="transparent")
        btn_box.pack(fill="x", pady=6)

        def open_pricing():
            self.destroy()
            from ui.pricing_modal import PricingModal
            PricingModal(self.master)

        ctk.CTkButton(
            btn_box,
            text="🛒 View Commercial Plans (Lifetime $60 / Family $90) ➔",
            height=38,
            fg_color="#F97316",
            hover_color="#EA580C",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=open_pricing,
        ).pack(fill="x")

    def _build_about_tab(self) -> None:
        page = ctk.CTkFrame(self.content_area, fg_color="transparent")
        self.pages["about"] = page

        ctk.CTkLabel(page, text="About", font=ctk.CTkFont(size=18, weight="bold"), text_color="#F8FAFC").pack(
            anchor="w", pady=(0, 16)
        )

        card = ctk.CTkFrame(page, fg_color="#1E293B", corner_radius=10)
        card.pack(fill="both", expand=True, padx=4, pady=4)

        ctk.CTkLabel(
            card,
            text=APP_NAME,
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color="#F8FAFC",
        ).pack(pady=(20, 2))

        ctk.CTkLabel(card, text=f"Version {APP_VERSION} ({APP_EDITION})", text_color="#38BDF8", font=ctk.CTkFont(size=12, weight="bold")).pack(
            pady=(0, 6)
        )
        ctk.CTkLabel(card, text=f"Created by {AUTHOR}", text_color="#94A3B8", font=ctk.CTkFont(size=12)).pack(
            pady=(0, 10)
        )
        ctk.CTkLabel(
            card,
            text="High-speed 8K/4K video & audio downloader, batch extractor,\ncreator folder organizer, and multi-platform media converter.",
            text_color="#64748B",
            font=ctk.CTkFont(size=11),
            justify="center",
        ).pack(pady=(0, 16))

        # Update Buttons Frame
        up_box = ctk.CTkFrame(card, fg_color="#0F172A", corner_radius=8, border_width=1, border_color="#334155")
        up_box.pack(fill="x", padx=20, pady=(0, 16))

        ctk.CTkLabel(up_box, text="Software & Engine Updates", font=ctk.CTkFont(size=11, weight="bold"), text_color="#94A3B8").pack(anchor="w", padx=12, pady=(10, 6))

        b_row = ctk.CTkFrame(up_box, fg_color="transparent")
        b_row.pack(fill="x", padx=12, pady=(0, 12))

        lbl_up_status = ctk.CTkLabel(up_box, text="", font=ctk.CTkFont(size=11), text_color="#38BDF8")
        lbl_up_status.pack(pady=(0, 8))

        def on_check_update():
            lbl_up_status.configure(text="Checking for updates...", text_color="#94A3B8")
            def _check():
                has_up, manifest, msg = check_for_updates()
                def _ui():
                    if has_up and manifest:
                        lbl_up_status.configure(text=f"New version v{manifest.version} available!", text_color="#10B981")
                        UpdateModal(self, manifest)
                    else:
                        lbl_up_status.configure(text=msg, text_color="#38BDF8")
                self.after(0, _ui)
            import threading
            threading.Thread(target=_check, daemon=True).start()

        def on_update_engine():
            lbl_up_status.configure(text="Updating extraction engine (yt-dlp)...", text_color="#94A3B8")
            def _eng():
                ok, msg = update_core_engine_ytdlp()
                col = "#10B981" if ok else "#EF4444"
                self.after(0, lambda: lbl_up_status.configure(text=msg, text_color=col))
            import threading
            threading.Thread(target=_eng, daemon=True).start()

        ctk.CTkButton(b_row, text="🔄 Check for App Updates", height=32, fg_color="#2563EB", hover_color="#1D4ED8", font=ctk.CTkFont(size=11, weight="bold"), command=on_check_update).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(b_row, text="⚡ Update yt-dlp Core Engine", height=32, fg_color="#334155", hover_color="#475569", font=ctk.CTkFont(size=11), command=on_update_engine).pack(side="right")
