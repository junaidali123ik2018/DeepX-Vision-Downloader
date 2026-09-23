from __future__ import annotations

from datetime import datetime, timezone
import threading
from tkinter import messagebox
import customtkinter as ctk

from app.telemetry import telemetry_service

# Theme Palette matching DeepX Dark Mode
SURFACE = "#1E293B"
BG_MAIN = "#0F172A"
BORDER_COL = "#334155"
TEXT_MAIN = "#F8FAFC"
TEXT_MUTED = "#94A3B8"
BLUE_ACCENT = ("#2563EB", "#38BDF8")
DANGER_RED = "#EF4444"
SUCCESS_GREEN = "#10B981"
AMBER_WARN = "#F59E0B"


class AdminDashboardModal(ctk.CTkToplevel):
    def __init__(self, parent: ctk.CTk) -> None:
        super().__init__(parent)
        self.title("DeepX Vision - Owner Admin Dashboard")
        self.geometry("980x720")
        self.minsize(880, 620)
        self.configure(fg_color=BG_MAIN)
        self.transient(parent)
        self.grab_set()

        self._data: dict = {}
        self._authenticated = False

        # First prompt for Owner Password
        self._show_login_screen()

    def _show_login_screen(self) -> None:
        self.login_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.login_frame.place(relx=0.5, rely=0.5, anchor="center")

        card = ctk.CTkFrame(self.login_frame, fg_color=SURFACE, corner_radius=16, border_width=1, border_color=BORDER_COL, width=440, height=360)
        card.pack(padx=20, pady=20)
        card.pack_propagate(False)

        ctk.CTkLabel(
            card,
            text="👑 Owner Administration",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#38BDF8",
        ).pack(pady=(30, 4))

        ctk.CTkLabel(
            card,
            text="DeepX Vision Downloader Telemetry & Remote Control\nEnter your Owner Admin Password to continue.",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
            justify="center",
        ).pack(pady=(0, 24), padx=20)

        self.pass_entry = ctk.CTkEntry(
            card,
            placeholder_text="Enter Admin Password (Default: admin123)",
            show="•",
            width=320,
            height=38,
            corner_radius=8,
            fg_color=BG_MAIN,
            border_color=BORDER_COL,
            font=ctk.CTkFont(size=13),
        )
        self.pass_entry.pack(pady=(0, 16))
        self.pass_entry.bind("<Return>", lambda e: self._attempt_login())
        self.pass_entry.focus()

        self.login_err = ctk.CTkLabel(card, text="", text_color=DANGER_RED, font=ctk.CTkFont(size=11))
        self.login_err.pack(pady=(0, 8))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=60, pady=(0, 20))

        ctk.CTkButton(
            btn_row,
            text="Unlock Dashboard",
            height=36,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._attempt_login,
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            btn_row,
            text="Cancel",
            width=80,
            height=36,
            fg_color="#334155",
            hover_color="#475569",
            command=self.destroy,
        ).pack(side="right")

    def _attempt_login(self) -> None:
        p = self.pass_entry.get()
        if telemetry_service.verify_admin_password(p):
            self._authenticated = True
            self.login_frame.destroy()
            self._build_dashboard_ui()
            self._fetch_and_render_data()
        else:
            self.login_err.configure(text="Incorrect password. Please try again.")

    def _build_dashboard_ui(self) -> None:
        # Top Header Bar
        top_bar = ctk.CTkFrame(self, fg_color=SURFACE, height=66, corner_radius=0)
        top_bar.pack(fill="x")
        top_bar.pack_propagate(False)

        # Title & Subtitle
        t_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        t_box.pack(side="left", padx=24, pady=12)
        ctk.CTkLabel(t_box, text="👑 DeepX Vision - Owner Admin Dashboard", font=ctk.CTkFont(size=18, weight="bold"), text_color="#38BDF8").pack(anchor="w")
        self.sync_lbl = ctk.CTkLabel(t_box, text="Syncing telemetry from cloud bridge...", font=ctk.CTkFont(size=11), text_color=TEXT_MUTED)
        self.sync_lbl.pack(anchor="w")

        # Action buttons
        btn_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        btn_box.pack(side="right", padx=24, pady=14)

        self.refresh_btn = ctk.CTkButton(
            btn_box,
            text="🔄 Refresh",
            width=90,
            height=32,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._fetch_and_render_data,
        )
        self.refresh_btn.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_box,
            text="⚙️ Bridge Settings",
            width=125,
            height=32,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._open_bridge_settings,
        ).pack(side="left")

        # Main Body Container
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=24, pady=16)

        # 1. Top KPI Metric Cards (4 Cards in a row)
        kpi_row = ctk.CTkFrame(self.main_container, fg_color="transparent")
        kpi_row.pack(fill="x", pady=(0, 14))
        kpi_row.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.kpi_devices = self._create_kpi_card(kpi_row, 0, "👥 Total Devices", "0", "#38BDF8")
        self.kpi_downloads = self._create_kpi_card(kpi_row, 1, "⚡ Total Downloads", "0", SUCCESS_GREEN)
        self.kpi_licenses = self._create_kpi_card(kpi_row, 2, "👑 Pro vs Trial", "0 Pro / 0 Trial", AMBER_WARN)
        self.kpi_banned = self._create_kpi_card(kpi_row, 3, "🚫 Banned PCs", "0 Banned", DANGER_RED)

        # 2. Tabs Selector
        self.tab_var = ctk.StringVar(value="devices")
        self.seg_tab = ctk.CTkSegmentedButton(
            self.main_container,
            values=["💻 Active Devices", "🚫 Banned Devices", "🗺️ Countries & Cities", "📈 Platforms Stats"],
            command=self._on_tab_changed,
            selected_color="#2563EB",
            selected_hover_color="#1D4ED8",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
        )
        self.seg_tab.set("💻 Active Devices")
        self.seg_tab.pack(fill="x", pady=(0, 12))

        # 3. Content Frame for Selected Tab
        self.content_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.content_frame.pack(fill="both", expand=True)

    def _create_kpi_card(self, parent, col: int, title: str, initial_val: str, val_color: str):
        card = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=BORDER_COL, height=76)
        card.grid(row=0, column=col, padx=4, sticky="nsew")
        card.pack_propagate(False)

        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_MUTED).pack(anchor="w", padx=14, pady=(10, 2))
        lbl_val = ctk.CTkLabel(card, text=initial_val, font=ctk.CTkFont(size=18, weight="bold"), text_color=val_color)
        lbl_val.pack(anchor="w", padx=14)
        return lbl_val

    def _on_tab_changed(self, tab_text: str) -> None:
        for child in self.content_frame.winfo_children():
            child.destroy()

        if "Active Devices" in tab_text:
            self._render_devices_tab()
        elif "Banned Devices" in tab_text:
            self._render_banned_tab()
        elif "Countries" in tab_text:
            self._render_countries_tab()
        elif "Platforms" in tab_text:
            self._render_platforms_tab()

    # -------------------------------------------------------------
    # Live Data Fetching
    # -------------------------------------------------------------
    def _fetch_and_render_data(self) -> None:
        if not self._authenticated:
            return

        self.sync_lbl.configure(text="Fetching live telemetry from cloud bridge...", text_color=AMBER_WARN)
        self.refresh_btn.configure(state="disabled")

        def _worker():
            data = telemetry_service.fetch_dashboard_data()
            self._data = data

            def _update():
                if not self.winfo_exists():
                    return
                self.refresh_btn.configure(state="normal")

                if data.get("connected"):
                    now_str = datetime.now().strftime("%I:%M:%S %p")
                    self.sync_lbl.configure(text=f"● Live Synced at {now_str} (Connected)", text_color=SUCCESS_GREEN)
                else:
                    err = data.get("error_message") or "Cloud bridge not configured"
                    self.sync_lbl.configure(text=f"⚠️ {err[:65]}", text_color=AMBER_WARN)

                # Update Top KPI Cards
                self.kpi_devices.configure(text=str(data.get("total_devices", 0)))
                self.kpi_downloads.configure(text=str(data.get("total_downloads", 0)))
                self.kpi_licenses.configure(text=f"{data.get('pro_devices', 0)} Pro / {data.get('trial_devices', 0)} Trial")
                self.kpi_banned.configure(text=f"{data.get('banned_count', 0)} Banned")

                # Refresh active tab content
                self._on_tab_changed(self.seg_tab.get())

            self.after(0, _update)

        threading.Thread(target=_worker, daemon=True).start()

    # -------------------------------------------------------------
    # Tab 1: Active Devices Table & Ban Actions
    # -------------------------------------------------------------
    def _render_devices_tab(self) -> None:
        devices = self._data.get("devices", [])

        # Quick Control Bar (Search + Manual Ban)
        bar = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 8))

        # Search Entry
        search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(
            bar,
            placeholder_text="🔍 Filter devices by Machine ID, City, Country, or OS...",
            width=360,
            height=32,
            textvariable=search_var,
            fg_color=SURFACE,
            border_color=BORDER_COL,
            font=ctk.CTkFont(size=12),
        )
        search_entry.pack(side="left")

        # Quick Ban By Machine ID input
        ban_btn_box = ctk.CTkFrame(bar, fg_color="transparent")
        ban_btn_box.pack(side="right")

        manual_mid_var = ctk.StringVar()
        manual_entry = ctk.CTkEntry(
            ban_btn_box,
            placeholder_text="Enter Machine ID to Ban...",
            width=210,
            height=32,
            textvariable=manual_mid_var,
            fg_color=SURFACE,
            border_color=BORDER_COL,
            font=ctk.CTkFont(size=11),
        )
        manual_entry.pack(side="left", padx=(0, 6))

        def on_manual_ban():
            mid = manual_mid_var.get().strip().upper()
            if not mid:
                messagebox.showwarning("Enter Machine ID", "Please enter a Machine ID to ban.")
                return
            self._prompt_ban_device(mid)

        ctk.CTkButton(
            ban_btn_box,
            text="🚫 Ban PC",
            width=90,
            height=32,
            fg_color=DANGER_RED,
            hover_color="#DC2626",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=on_manual_ban,
        ).pack(side="left")

        # Table Header
        header = ctk.CTkFrame(self.content_frame, fg_color=SURFACE, height=36, corner_radius=6)
        header.pack(fill="x", pady=(0, 4))
        header.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        cols = ["Machine ID", "Location (City, Country)", "OS & Version", "License", "Status", "Action"]
        for idx, col in enumerate(cols):
            anchor = "e" if idx == 5 else "w"
            ctk.CTkLabel(header, text=col, font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_MUTED).grid(row=0, column=idx, padx=12, pady=6, sticky=anchor)

        # Scrollable rows
        scroll_list = ctk.CTkScrollableFrame(self.content_frame, fg_color="transparent", corner_radius=8)
        scroll_list.pack(fill="both", expand=True)

        def populate_rows(filter_text=""):
            for child in scroll_list.winfo_children():
                child.destroy()

            filt = filter_text.strip().lower()
            matching = []
            for d in devices:
                mid = str(d.get("machine_id", "")).lower()
                loc = f"{d.get('city', '')} {d.get('country', '')}".lower()
                os_str = str(d.get("os_name", "")).lower()
                if not filt or filt in mid or filt in loc or filt in os_str:
                    matching.append(d)

            if not matching:
                empty = ctk.CTkLabel(scroll_list, text="No active devices found." if not devices else "No devices matching your search filter.", text_color=TEXT_MUTED, font=ctk.CTkFont(size=12))
                empty.pack(pady=30)
                return

            for idx, dev in enumerate(matching):
                is_banned = dev.get("is_banned", False)
                row_bg = "#2D1515" if is_banned else (SURFACE if idx % 2 == 0 else "#162032")

                row = ctk.CTkFrame(scroll_list, fg_color=row_bg, corner_radius=6, height=44)
                row.pack(fill="x", pady=2)
                row.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

                mid_text = dev.get("machine_id", "Unknown")
                ctk.CTkLabel(row, text=mid_text, font=ctk.CTkFont(family="Consolas", size=11, weight="bold"), text_color="#38BDF8").grid(row=0, column=0, padx=12, pady=8, sticky="w")

                loc_str = f"{dev.get('city', 'Unknown')}, {dev.get('country', 'Unknown')}"
                ctk.CTkLabel(row, text=loc_str[:25], font=ctk.CTkFont(size=11), text_color=TEXT_MAIN).grid(row=0, column=1, padx=12, pady=8, sticky="w")

                os_info = f"{dev.get('os_name', 'Windows')} (v{dev.get('app_version', APP_VERSION)})"
                ctk.CTkLabel(row, text=os_info[:24], font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).grid(row=0, column=2, padx=12, pady=8, sticky="w")

                is_pro = dev.get("is_pro", False)
                lic_text = f"👑 {dev.get('tier', 'Pro')}" if is_pro else "⏳ Trial"
                lic_col = SUCCESS_GREEN if is_pro else AMBER_WARN
                ctk.CTkLabel(row, text=lic_text, font=ctk.CTkFont(size=11, weight="bold"), text_color=lic_col).grid(row=0, column=3, padx=12, pady=8, sticky="w")

                stat_text = "🚫 BANNED" if is_banned else "● Active"
                stat_col = DANGER_RED if is_banned else SUCCESS_GREEN
                ctk.CTkLabel(row, text=stat_text, font=ctk.CTkFont(size=11, weight="bold"), text_color=stat_col).grid(row=0, column=4, padx=12, pady=8, sticky="w")

                # Action button: Ban or Unban
                btn_frame = ctk.CTkFrame(row, fg_color="transparent")
                btn_frame.grid(row=0, column=5, padx=12, pady=6, sticky="e")

                if is_banned:
                    ctk.CTkButton(
                        btn_frame,
                        text="✅ Unban",
                        width=72,
                        height=26,
                        fg_color=SUCCESS_GREEN,
                        hover_color="#059669",
                        font=ctk.CTkFont(size=11, weight="bold"),
                        command=lambda m=mid_text: self._unban_device_action(m),
                    ).pack(side="right")
                else:
                    ctk.CTkButton(
                        btn_frame,
                        text="🚫 Ban",
                        width=65,
                        height=26,
                        fg_color=DANGER_RED,
                        hover_color="#DC2626",
                        font=ctk.CTkFont(size=11, weight="bold"),
                        command=lambda m=mid_text: self._prompt_ban_device(m),
                    ).pack(side="right")

        search_var.trace_add("write", lambda *args: populate_rows(search_var.get()))
        populate_rows()

    # -------------------------------------------------------------
    # Tab 2: Banned Devices Tab
    # -------------------------------------------------------------
    def _render_banned_tab(self) -> None:
        banned_list = self._data.get("banned_devices", [])

        top_info = ctk.CTkLabel(
            self.content_frame,
            text=f"Total Suspended Computers: {len(banned_list)} PC(s). Banned PCs are blocked from downloading and viewing content.",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
            anchor="w",
        )
        top_info.pack(fill="x", pady=(0, 10))

        if not banned_list:
            ctk.CTkLabel(self.content_frame, text="✅ No computers are currently banned. All active devices have normal access.", text_color=SUCCESS_GREEN, font=ctk.CTkFont(size=13, weight="bold")).pack(pady=40)
            return

        scroll_banned = ctk.CTkScrollableFrame(self.content_frame, fg_color="transparent")
        scroll_banned.pack(fill="both", expand=True)

        for b in banned_list:
            card = ctk.CTkFrame(scroll_banned, fg_color="#2D1515", border_width=1, border_color="#7F1D1D", corner_radius=8, height=54)
            card.pack(fill="x", pady=4)
            card.grid_columnconfigure(1, weight=1)

            mid = b.get("machine_id", "Unknown")
            reason = b.get("reason", "Suspended by Administrator")
            b_at = str(b.get("banned_at", ""))[:19].replace("T", " ")

            ctk.CTkLabel(card, text=f"🚫 {mid}", font=ctk.CTkFont(family="Consolas", size=13, weight="bold"), text_color=DANGER_RED).grid(row=0, column=0, padx=14, pady=10, sticky="w")
            ctk.CTkLabel(card, text=f"Reason: {reason}  •  Date: {b_at}", font=ctk.CTkFont(size=11), text_color="#FCA5A5").grid(row=0, column=1, padx=10, pady=10, sticky="w")

            ctk.CTkButton(
                card,
                text="✅ Unban PC",
                width=90,
                height=28,
                fg_color=SUCCESS_GREEN,
                hover_color="#059669",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda m=mid: self._unban_device_action(m),
            ).grid(row=0, column=2, padx=14, pady=10, sticky="e")

    # -------------------------------------------------------------
    # Tab 3: Countries & Cities Breakdown
    # -------------------------------------------------------------
    def _render_countries_tab(self) -> None:
        countries = self._data.get("countries", {})
        cities = self._data.get("cities", {})

        split_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        split_frame.pack(fill="both", expand=True)
        split_frame.grid_columnconfigure((0, 1), weight=1)

        # Left Column: Countries
        c_box = ctk.CTkFrame(split_frame, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=BORDER_COL)
        c_box.grid(row=0, column=0, padx=6, pady=4, sticky="nsew")

        ctk.CTkLabel(c_box, text="🌍 Top Countries", font=ctk.CTkFont(size=14, weight="bold"), text_color="#38BDF8").pack(anchor="w", padx=16, pady=(14, 8))

        c_scroll = ctk.CTkScrollableFrame(c_box, fg_color="transparent")
        c_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        sorted_countries = sorted(countries.items(), key=lambda x: x[1], reverse=True)
        if not sorted_countries:
            ctk.CTkLabel(c_scroll, text="No country data yet.", text_color=TEXT_MUTED).pack(pady=20)
        else:
            for idx, (cntry, count) in enumerate(sorted_countries, 1):
                row = ctk.CTkFrame(c_scroll, fg_color=BG_MAIN, corner_radius=6, height=36)
                row.pack(fill="x", pady=2)
                ctk.CTkLabel(row, text=f"{idx}. {cntry}", font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_MAIN).pack(side="left", padx=12)
                ctk.CTkLabel(row, text=f"{count} users", font=ctk.CTkFont(size=12, weight="bold"), text_color=SUCCESS_GREEN).pack(side="right", padx=12)

        # Right Column: Cities
        city_box = ctk.CTkFrame(split_frame, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=BORDER_COL)
        city_box.grid(row=0, column=1, padx=6, pady=4, sticky="nsew")

        ctk.CTkLabel(city_box, text="🏙️ Top Cities", font=ctk.CTkFont(size=14, weight="bold"), text_color="#38BDF8").pack(anchor="w", padx=16, pady=(14, 8))

        city_scroll = ctk.CTkScrollableFrame(city_box, fg_color="transparent")
        city_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 10))

        sorted_cities = sorted(cities.items(), key=lambda x: x[1], reverse=True)
        if not sorted_cities:
            ctk.CTkLabel(city_scroll, text="No city data yet.", text_color=TEXT_MUTED).pack(pady=20)
        else:
            for idx, (city, count) in enumerate(sorted_cities, 1):
                row = ctk.CTkFrame(city_scroll, fg_color=BG_MAIN, corner_radius=6, height=36)
                row.pack(fill="x", pady=2)
                ctk.CTkLabel(row, text=f"{idx}. {city}", font=ctk.CTkFont(size=12), text_color=TEXT_MAIN).pack(side="left", padx=12)
                ctk.CTkLabel(row, text=f"{count} users", font=ctk.CTkFont(size=11, weight="bold"), text_color="#38BDF8").pack(side="right", padx=12)

    # -------------------------------------------------------------
    # Tab 4: Platform Breakdown
    # -------------------------------------------------------------
    def _render_platforms_tab(self) -> None:
        plats = self._data.get("platforms", {})
        total_dls = self._data.get("total_downloads", 0)

        card = ctk.CTkFrame(self.content_frame, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=BORDER_COL)
        card.pack(fill="both", expand=True, padx=10, pady=6)

        ctk.CTkLabel(card, text="📊 Platform Usage Breakdown", font=ctk.CTkFont(size=16, weight="bold"), text_color="#38BDF8").pack(anchor="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(card, text="Shows what media sites and apps your users are downloading from.", font=ctk.CTkFont(size=12), text_color=TEXT_MUTED).pack(anchor="w", padx=20, pady=(0, 16))

        plat_meta = [
            ("YouTube & Shorts", plats.get("youtube", 0), "#EF4444"),
            ("TikTok Videos & Slides", plats.get("tiktok", 0), "#EC4899"),
            ("Instagram Posts/Reels", plats.get("instagram", 0), "#A855F7"),
            ("Facebook Videos", plats.get("facebook", 0), "#3B82F6"),
            ("Other 10,000+ Sites", plats.get("other", 0), "#10B981"),
        ]

        for name, cnt, col in plat_meta:
            pct = (cnt / total_dls * 100.0) if total_dls > 0 else 0.0

            row = ctk.CTkFrame(card, fg_color=BG_MAIN, corner_radius=8, height=44)
            row.pack(fill="x", padx=20, pady=4)

            ctk.CTkLabel(row, text=name, font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_MAIN).pack(side="left", padx=14)
            ctk.CTkLabel(row, text=f"{cnt} downloads ({pct:.1f}%)", font=ctk.CTkFont(size=12, weight="bold"), text_color=col).pack(side="right", padx=14)

    # -------------------------------------------------------------
    # Ban / Unban Dialog Actions
    # -------------------------------------------------------------
    def _prompt_ban_device(self, machine_id: str) -> None:
        prompt_win = ctk.CTkToplevel(self)
        prompt_win.title(f"Ban Device - {machine_id}")
        prompt_win.geometry("440x260")
        prompt_win.resizable(False, False)
        prompt_win.configure(fg_color=BG_MAIN)
        prompt_win.transient(self)
        prompt_win.grab_set()

        ctk.CTkLabel(prompt_win, text=f"🚫 Suspend Device {machine_id}", font=ctk.CTkFont(size=15, weight="bold"), text_color=DANGER_RED).pack(pady=(20, 6))
        ctk.CTkLabel(prompt_win, text="This computer will be immediately blocked from downloading\nor running the software until you unban it.", font=ctk.CTkFont(size=11), text_color=TEXT_MUTED, justify="center").pack(pady=(0, 14))

        reason_var = ctk.StringVar(value="Unauthorized Key Sharing")
        ctk.CTkLabel(prompt_win, text="Reason for Ban:", font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_MAIN).pack(anchor="w", padx=26, pady=(0, 2))

        reasons = ["Unauthorized Key Sharing", "Trial Limit Circumvention", "Payment Dispute / Chargeback", "Excessive Bot Abusing", "Custom Reason"]
        opt = ctk.CTkOptionMenu(prompt_win, values=reasons, variable=reason_var, fg_color=SURFACE, button_color="#334155")
        opt.pack(fill="x", padx=26, pady=(0, 18))

        btn_row = ctk.CTkFrame(prompt_win, fg_color="transparent")
        btn_row.pack(fill="x", padx=26)

        def do_ban():
            r = reason_var.get()
            prompt_win.destroy()
            success, msg = telemetry_service.ban_device(machine_id, r)
            if success:
                messagebox.showinfo("Device Banned", f"Device {machine_id} has been banned successfully!")
                self._fetch_and_render_data()
            else:
                messagebox.showerror("Ban Failed", msg)

        ctk.CTkButton(btn_row, text="Confirm Ban", fg_color=DANGER_RED, hover_color="#DC2626", font=ctk.CTkFont(weight="bold"), command=do_ban).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(btn_row, text="Cancel", width=80, fg_color="#334155", hover_color="#475569", command=prompt_win.destroy).pack(side="right")

    def _unban_device_action(self, machine_id: str) -> None:
        confirm = messagebox.askyesno("Unban Device", f"Are you sure you want to restore full access for device {machine_id}?")
        if not confirm:
            return

        success, msg = telemetry_service.unban_device(machine_id)
        if success:
            messagebox.showinfo("Device Restored", f"Device {machine_id} has been unbanned successfully!")
            self._fetch_and_render_data()
        else:
            messagebox.showerror("Unban Failed", msg)

    # -------------------------------------------------------------
    # Bridge Settings Modal (Firebase URL & Password change)
    # -------------------------------------------------------------
    def _open_bridge_settings(self) -> None:
        win = ctk.CTkToplevel(self)
        win.title("Cloud Bridge & Admin Settings")
        win.geometry("540x420")
        win.resizable(False, False)
        win.configure(fg_color=BG_MAIN)
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="⚙️ Cloud Bridge & Owner Security", font=ctk.CTkFont(size=17, weight="bold"), text_color="#38BDF8").pack(pady=(20, 4))
        ctk.CTkLabel(win, text="Configure your Google Firebase Realtime Database URL & Admin Password.", font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack(pady=(0, 16))

        box = ctk.CTkFrame(win, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=BORDER_COL)
        box.pack(fill="x", padx=26, pady=(0, 14))

        ctk.CTkLabel(box, text="Firebase Realtime Database URL:", font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_MAIN).pack(anchor="w", padx=14, pady=(12, 2))
        url_entry = ctk.CTkEntry(box, width=460, height=34, fg_color=BG_MAIN, border_color=BORDER_COL, font=ctk.CTkFont(size=11))
        url_entry.insert(0, telemetry_service._cloud_url)
        url_entry.pack(padx=14, pady=(0, 10))

        ctk.CTkLabel(box, text="Change Owner Admin Password:", font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_MAIN).pack(anchor="w", padx=14, pady=(6, 2))
        pass_entry = ctk.CTkEntry(box, placeholder_text="Enter new password (leave blank to keep current)", show="•", width=460, height=34, fg_color=BG_MAIN, border_color=BORDER_COL, font=ctk.CTkFont(size=11))
        pass_entry.pack(padx=14, pady=(0, 14))

        def save_settings():
            new_url = url_entry.get().strip()
            telemetry_service.set_configured_cloud_url(new_url)

            new_p = pass_entry.get().strip()
            if new_p:
                telemetry_service.set_admin_password(new_p)
                messagebox.showinfo("Saved", "Cloud Bridge URL and Admin Password updated successfully!")
            else:
                messagebox.showinfo("Saved", "Cloud Bridge URL updated successfully!")

            win.destroy()
            self._fetch_and_render_data()

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=26, pady=(10, 0))

        ctk.CTkButton(btn_row, text="💾 Save Configuration", height=36, fg_color="#2563EB", hover_color="#1D4ED8", font=ctk.CTkFont(weight="bold"), command=save_settings).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(btn_row, text="Close", width=80, height=36, fg_color="#334155", hover_color="#475569", command=win.destroy).pack(side="right")
