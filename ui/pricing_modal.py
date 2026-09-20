from __future__ import annotations

import webbrowser
from tkinter import messagebox
import customtkinter as ctk

from app.license import license_mgr


class PricingModal(ctk.CTkToplevel):
    def __init__(self, parent: ctk.CTk, on_activate_clicked=None) -> None:
        super().__init__(parent)
        self.on_activate_clicked = on_activate_clicked
        self.title("Buy DeepX Vision Pro - Choose Your Plan")
        self.geometry("980x690")
        self.minsize(940, 650)
        self.configure(fg_color="#F8FAFC")
        self.transient(parent)
        self.grab_set()

        self._coupon_applied = False
        self._discount_percent = 0.20  # 20% off
        self._plan_prices = {
            "1m": {"normal": 9.95, "orig": 19.95, "lbl": None},
            "1y": {"normal": 29.95, "orig": 69.95, "lbl": None},
            "lt": {"normal": 60.00, "orig": 120.00, "lbl": None},
            "fam": {"normal": 90.00, "orig": 180.00, "lbl": None},
        }

        self._build_ui()

    def _build_ui(self) -> None:
        # Top Title
        title_frame = ctk.CTkFrame(self, fg_color="transparent")
        title_frame.pack(fill="x", pady=(20, 4))

        ctk.CTkLabel(
            title_frame,
            text="Buy DeepX Vision Pro",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color="#0F172A",
        ).pack()

        # Guarantees Sub-header
        guarantee_row = ctk.CTkFrame(self, fg_color="transparent")
        guarantee_row.pack(fill="x", pady=(0, 12))

        g_items = [
            "🛡 30-Day Money-Back Guarantee",
            "🎧 Free Customer Support",
            "⚡ Lifetime Free Updates",
        ]
        g_box = ctk.CTkFrame(guarantee_row, fg_color="transparent")
        g_box.pack(anchor="center")
        for item in g_items:
            ctk.CTkLabel(
                g_box,
                text=item,
                font=ctk.CTkFont(size=12),
                text_color="#64748B",
            ).pack(side="left", padx=16)

        # Segmented Switch: Standard vs PRO
        toggle_frame = ctk.CTkFrame(self, fg_color="transparent")
        toggle_frame.pack(pady=(0, 10))

        self.seg_btn = ctk.CTkSegmentedButton(
            toggle_frame,
            values=["Standard", "PRO"],
            selected_color="#3B82F6",
            selected_hover_color="#2563EB",
            unselected_color="#E2E8F0",
            unselected_hover_color="#CBD5E1",
            text_color="#0F172A",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=30,
        )
        self.seg_btn.set("PRO")
        self.seg_btn.pack()

        # 20% OFF Limited-Time Coupon Banner
        coupon_banner = ctk.CTkFrame(
            self,
            corner_radius=10,
            fg_color="#F0F9FF",
            border_width=1,
            border_color="#BAE6FD",
            height=46,
        )
        coupon_banner.pack(fill="x", padx=40, pady=(0, 14))

        cb_inner = ctk.CTkFrame(coupon_banner, fg_color="transparent")
        cb_inner.pack(expand=True, pady=6)

        ctk.CTkLabel(
            cb_inner,
            text="🏷 % 20% OFF, Limited-Time Coupon",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#0284C7",
        ).pack(side="left", padx=(10, 16))

        code_box = ctk.CTkFrame(cb_inner, fg_color="#FFFFFF", border_width=1, border_color="#CBD5E1", corner_radius=6)
        code_box.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(
            code_box,
            text="SALEY20",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#0F172A",
        ).pack(padx=14, pady=3)

        self.btn_apply_banner = ctk.CTkButton(
            cb_inner,
            text="APPLY",
            width=75,
            height=28,
            corner_radius=6,
            fg_color="#0284C7",
            hover_color="#0369A1",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._apply_coupon,
        )
        self.btn_apply_banner.pack(side="left")

        # 4 Pricing Cards Row
        cards_container = ctk.CTkFrame(self, fg_color="transparent")
        cards_container.pack(fill="x", padx=30, pady=(0, 14))
        cards_container.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="plan_cols")

        # 1. 1 Month Plan
        self._build_card(
            parent=cards_container,
            col=0,
            plan_id="1m",
            title="1 Month Plan",
            sub="Auto-renew. Cancel any time.",
            is_bestseller=False,
            device_text="One license for 1 computer",
        )

        # 2. 1 Year Plan
        self._build_card(
            parent=cards_container,
            col=1,
            plan_id="1y",
            title="1 Year Plan",
            sub="Auto-renew. Cancel any time.",
            is_bestseller=False,
            device_text="One license for 1 computer",
        )

        # 3. Lifetime Plan (BEST SELLER - $60)
        self._build_card(
            parent=cards_container,
            col=2,
            plan_id="lt",
            title="Lifetime Plan",
            sub="One-time Purchase",
            is_bestseller=True,
            device_text="One license for 1 computer",
        )

        # 4. Family Plan ($90 - 5 Computers)
        self._build_card(
            parent=cards_container,
            col=3,
            plan_id="fam",
            title="Family Plan",
            sub="One-time Purchase",
            is_bestseller=False,
            device_text="One license for 5 computers",
        )

        # Bottom Coupon Entry & Activate Link
        bottom_bar = ctk.CTkFrame(self, fg_color="transparent")
        bottom_bar.pack(fill="x", padx=40, pady=(4, 16))

        # Center coupon bar
        c_entry_box = ctk.CTkFrame(bottom_bar, fg_color="transparent")
        c_entry_box.pack(anchor="center", pady=(0, 8))

        self.coupon_entry_var = ctk.StringVar()
        self.coupon_entry = ctk.CTkEntry(
            c_entry_box,
            textvariable=self.coupon_entry_var,
            placeholder_text="Enter Coupon Code",
            width=220,
            height=32,
            corner_radius=6,
            border_width=1,
            border_color="#CBD5E1",
            fg_color="#FFFFFF",
            text_color="#0F172A",
            font=ctk.CTkFont(size=12),
        )
        self.coupon_entry.pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            c_entry_box,
            text="APPLY",
            width=75,
            height=32,
            corner_radius=6,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._apply_custom_coupon,
        ).pack(side="left")

        # Bottom Key Link: "Already have a license key? Enter Key to Activate"
        act_row = ctk.CTkFrame(bottom_bar, fg_color="transparent")
        act_row.pack(anchor="center")

        ctk.CTkLabel(
            act_row,
            text="Already have a license key?",
            font=ctk.CTkFont(size=12),
            text_color="#64748B",
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            act_row,
            text="Enter Key to Activate ➔",
            height=26,
            fg_color="transparent",
            hover_color="#EEF2F6",
            text_color="#2563EB",
            font=ctk.CTkFont(size=12, weight="bold", underline=True),
            command=self._open_activation_dialog,
        ).pack(side="left")

    def _build_card(
        self,
        parent: ctk.CTkFrame,
        col: int,
        plan_id: str,
        title: str,
        sub: str,
        is_bestseller: bool,
        device_text: str,
    ) -> None:
        border_col = "#0284C7" if is_bestseller else "#E2E8F0"
        border_w = 2 if is_bestseller else 1

        card = ctk.CTkFrame(
            parent,
            corner_radius=12,
            fg_color="#FFFFFF",
            border_width=border_w,
            border_color=border_col,
        )
        card.grid(row=0, column=col, sticky="nsew", padx=6, pady=4)

        if is_bestseller:
            badge = ctk.CTkFrame(card, corner_radius=0, fg_color="#0284C7", height=26)
            badge.pack(fill="x")
            badge.pack_propagate(False)
            ctk.CTkLabel(
                badge,
                text="BEST SELLER",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#FFFFFF",
            ).place(relx=0.5, rely=0.5, anchor="center")

        pad_top = 10 if is_bestseller else 18
        ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#0F172A",
        ).pack(pady=(pad_top, 6))

        # Price Frame
        price_f = ctk.CTkFrame(card, fg_color="transparent")
        price_f.pack(pady=(0, 2))

        norm_p = self._plan_prices[plan_id]["normal"]
        orig_p = self._plan_prices[plan_id]["orig"]

        price_lbl = ctk.CTkLabel(
            price_f,
            text=f"${norm_p:.2f}",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color="#0F172A",
        )
        price_lbl.pack(side="left")
        self._plan_prices[plan_id]["lbl"] = price_lbl

        ctk.CTkLabel(
            price_f,
            text=f" ${orig_p:.2f}",
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8",
        ).pack(side="left", padx=(2, 0))

        ctk.CTkLabel(
            card,
            text=sub,
            font=ctk.CTkFont(size=10),
            text_color="#64748B",
        ).pack(pady=(0, 10))

        # Orange BUY NOW Button
        ctk.CTkButton(
            card,
            text="🛒 BUY NOW",
            height=36,
            corner_radius=6,
            fg_color="#F97316",
            hover_color="#EA580C",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda p=plan_id, t=title: self._on_buy(p, t),
        ).pack(fill="x", padx=16, pady=(0, 14))

        # Features List with Checkmarks
        feat_box = ctk.CTkFrame(card, fg_color="transparent")
        feat_box.pack(fill="x", padx=14, pady=(0, 16))

        features = [
            "Save from 10,000+ sites",
            "Download videos in 4K/8K",
            "Save music up to 320kbps",
            "Batch save video/audio",
            device_text,
        ]
        for f in features:
            f_row = ctk.CTkFrame(feat_box, fg_color="transparent")
            f_row.pack(anchor="w", pady=2)
            ctk.CTkLabel(
                f_row,
                text="✓",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#64748B",
            ).pack(side="left", padx=(0, 6))
            ctk.CTkLabel(
                f_row,
                text=f,
                font=ctk.CTkFont(size=10),
                text_color="#475569",
                anchor="w",
            ).pack(side="left")

    def _apply_coupon(self) -> None:
        self.coupon_entry_var.set("SALEY20")
        self._apply_custom_coupon()

    def _apply_custom_coupon(self) -> None:
        code = self.coupon_entry_var.get().strip().upper()
        if code in {"SALEY20", "PRO20", "JUNAID20"}:
            self._coupon_applied = True
            for pid, pdata in self._plan_prices.items():
                disc_p = pdata["normal"] * (1.0 - self._discount_percent)
                if pdata["lbl"]:
                    pdata["lbl"].configure(text=f"${disc_p:.2f}")
            messagebox.showinfo("Coupon Applied!", f"Coupon '{code}' applied successfully! 20% discount granted on all plans.")
        else:
            messagebox.showwarning("Invalid Coupon", "The entered coupon code is invalid or expired.")

    def _on_buy(self, plan_id: str, title: str) -> None:
        # Show purchase guidance with contact details and Machine ID
        mid = license_mgr.machine_id
        price_val = self._plan_prices[plan_id]["normal"]
        if self._coupon_applied:
            price_val *= (1.0 - self._discount_percent)

        info_win = ctk.CTkToplevel(self)
        info_win.title(f"Purchase {title}")
        info_win.geometry("520x400")
        info_win.resizable(False, False)
        info_win.configure(fg_color="#0F172A")
        info_win.transient(self)
        info_win.grab_set()

        ctk.CTkLabel(
            info_win,
            text=f"👑 Purchase {title}",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#38BDF8",
        ).pack(pady=(20, 6))

        ctk.CTkLabel(
            info_win,
            text=f"Price: ${price_val:.2f} USD\nIncludes Instant License Key Delivery & 1-on-1 Support",
            font=ctk.CTkFont(size=12),
            text_color="#CBD5E1",
            justify="center",
        ).pack(pady=(0, 14))

        box = ctk.CTkFrame(info_win, corner_radius=10, fg_color="#1E293B", border_width=1, border_color="#334155")
        box.pack(fill="x", padx=26, pady=(0, 14))

        ctk.CTkLabel(box, text="Your Machine ID (for single-PC activation):", font=ctk.CTkFont(size=11, weight="bold"), text_color="#94A3B8").pack(anchor="w", padx=14, pady=(10, 2))
        
        mid_row = ctk.CTkFrame(box, fg_color="transparent")
        mid_row.pack(fill="x", padx=14, pady=(0, 10))
        
        ctk.CTkLabel(mid_row, text=mid, font=ctk.CTkFont(family="Consolas", size=14, weight="bold"), text_color="#38BDF8").pack(side="left")
        
        def copy_mid():
            self.clipboard_clear()
            self.clipboard_append(mid)
            messagebox.showinfo("Copied", "Machine ID copied to clipboard!")

        ctk.CTkButton(mid_row, text="📋 Copy ID", width=80, height=28, fg_color="#334155", hover_color="#475569", command=copy_mid).pack(side="right")

        ctk.CTkLabel(
            info_win,
            text="To complete your purchase, contact Junaid Ali with your Machine ID.\nLicense keys are generated and sent immediately upon payment.",
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8",
            justify="center",
        ).pack(pady=(0, 16))

        btn_row = ctk.CTkFrame(info_win, fg_color="transparent")
        btn_row.pack(fill="x", padx=26)

        def open_chat():
            webbrowser.open("https://wa.me/?text=Hi%20Junaid,%20I%20want%20to%20buy%20DeepX%20Vision%20Pro%20(" + title + ")%20MachineID:" + mid)

        ctk.CTkButton(
            btn_row,
            text="💬 Contact via WhatsApp",
            height=36,
            fg_color="#10B981",
            hover_color="#059669",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=open_chat,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            btn_row,
            text="Close",
            width=90,
            height=36,
            fg_color="#334155",
            hover_color="#475569",
            command=info_win.destroy,
        ).pack(side="right")

    def _open_activation_dialog(self) -> None:
        self.destroy()
        if self.on_activate_clicked:
            self.on_activate_clicked()
        else:
            from ui.license_dialog import LicenseDialog
            LicenseDialog(self.master)
