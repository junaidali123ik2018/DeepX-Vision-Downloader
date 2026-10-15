from __future__ import annotations

from tkinter import messagebox
import customtkinter as ctk

from app.license import DAILY_TRIAL_LIMIT, TIER_NAMES, license_mgr


class LicenseDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        is_limit_reached: bool = False,
        on_status_changed=None,
    ) -> None:
        super().__init__(parent)
        self.on_status_changed = on_status_changed
        self.title("DeepX Vision Pro - Activation & Licensing")
        self.resizable(False, False)
        self.configure(fg_color="#0F172A")
        self.transient(parent)
        self.grab_set()

        is_pro = license_mgr.is_pro()
        if is_pro:
            self.geometry("520x330")
            self._build_pro_ui()
        else:
            self.geometry("560x510")
            self._build_trial_ui(is_limit_reached)

    # ------------------------------------------------------------------
    # UI when Pro license IS activated
    # ------------------------------------------------------------------
    def _build_pro_ui(self) -> None:
        # Header
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=26, pady=(20, 8))

        ctk.CTkLabel(
            head,
            text="👑 DeepX Vision Pro — Activated",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#F8FAFC",
        ).pack(anchor="w")

        ctk.CTkLabel(
            head,
            text="Your Pro license is active on this machine.",
            font=ctk.CTkFont(size=12),
            text_color="#94A3B8",
        ).pack(anchor="w")

        # Status + Machine ID card
        card = ctk.CTkFrame(self, corner_radius=12, fg_color="#1E293B", border_width=1, border_color="#334155")
        card.pack(fill="x", padx=26, pady=10)

        # Status row
        s_row = ctk.CTkFrame(card, fg_color="transparent")
        s_row.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(s_row, text="Status:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94A3B8").pack(side="left")
        ctk.CTkLabel(
            s_row,
            text=license_mgr.get_status_text(),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#34D399",
        ).pack(side="left", padx=8)

        # Machine ID row
        m_row = ctk.CTkFrame(card, fg_color="transparent")
        m_row.pack(fill="x", padx=16, pady=(4, 14))
        ctk.CTkLabel(m_row, text="Machine ID:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94A3B8").pack(side="left")
        ctk.CTkLabel(m_row, text=license_mgr.machine_id, font=ctk.CTkFont(family="Consolas", size=12, weight="bold"), text_color="#38BDF8").pack(side="left", padx=8)

        def copy_mid():
            self.clipboard_clear()
            self.clipboard_append(license_mgr.machine_id)
            messagebox.showinfo("Copied", "Machine ID copied to clipboard!")

        ctk.CTkButton(m_row, text="📋 Copy", width=65, height=24, fg_color="#334155", hover_color="#475569", command=copy_mid).pack(side="right")

        # Action buttons row
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=26, pady=(6, 6))

        def change_key():
            """Deactivate current key so user can enter a new one."""
            if messagebox.askyesno("Change Key", "This will deactivate the current key on this machine and let you enter a new one. Continue?"):
                license_mgr.deactivate_key()
                if self.on_status_changed:
                    self.on_status_changed()
                self.destroy()
                LicenseDialog(self.master, on_status_changed=self.on_status_changed)

        def logout():
            if messagebox.askyesno("Logout / Deactivate", "Are you sure you want to deactivate this Pro license on this machine?"):
                license_mgr.deactivate_key()
                if self.on_status_changed:
                    self.on_status_changed()
                self.destroy()

        ctk.CTkButton(
            actions,
            text="🔑 Change Key",
            height=36,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=change_key,
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            actions,
            text="🚪 Logout / Deactivate",
            height=36,
            fg_color="#451A1A",
            hover_color="#7F1D1D",
            text_color="#FCA5A5",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=logout,
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            actions,
            text="🛒 View Pricing & Status",
            height=36,
            fg_color="#F97316",
            hover_color="#EA580C",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._open_pricing_modal,
        ).pack(side="left", fill="x", expand=True)

        # Close button
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=26, pady=(8, 20))
        ctk.CTkButton(
            footer,
            text="Close",
            height=34,
            fg_color="#334155",
            hover_color="#475569",
            command=self.destroy,
        ).pack(fill="x")

    # ------------------------------------------------------------------
    # UI when NO Pro license (Trial mode) — original full UI
    # ------------------------------------------------------------------
    def _build_trial_ui(self, is_limit_reached: bool) -> None:
        # Header
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=26, pady=(20, 8))

        ctk.CTkLabel(
            head,
            text="👑 DeepX Vision Pro Activation",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#F8FAFC",
        ).pack(anchor="w")

        ctk.CTkLabel(
            head,
            text="Unlock unlimited downloads, 8K/4K high speed, and multi-platform auto-save.",
            font=ctk.CTkFont(size=12),
            text_color="#94A3B8",
        ).pack(anchor="w")

        # Trial Limit Alert Banner
        if is_limit_reached:
            alert = ctk.CTkFrame(self, corner_radius=8, fg_color=("#451A1A", "#451A1A"), border_width=1, border_color="#DC2626")
            alert.pack(fill="x", padx=26, pady=(0, 10))
            ctk.CTkLabel(
                alert,
                text="⚠️ Daily Free Trial Limit Reached (5/5 Videos Used Today)\nEnter a Pro License Key below or upgrade to download unlimited videos!",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#FCA5A5",
                justify="center",
            ).pack(padx=12, pady=8)

        # Status Card
        card = ctk.CTkFrame(self, corner_radius=12, fg_color="#1E293B", border_width=1, border_color="#334155")
        card.pack(fill="x", padx=26, pady=6)

        s_row = ctk.CTkFrame(card, fg_color="transparent")
        s_row.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(s_row, text="Status:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94A3B8").pack(side="left")
        self.lbl_status = ctk.CTkLabel(
            s_row,
            text=license_mgr.get_status_text(),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#F59E0B",
        )
        self.lbl_status.pack(side="left", padx=8)

        # Machine ID Row
        m_row = ctk.CTkFrame(card, fg_color="transparent")
        m_row.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(m_row, text="Machine ID:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94A3B8").pack(side="left")
        ctk.CTkLabel(m_row, text=license_mgr.machine_id, font=ctk.CTkFont(family="Consolas", size=12, weight="bold"), text_color="#38BDF8").pack(side="left", padx=8)

        def copy_mid():
            self.clipboard_clear()
            self.clipboard_append(license_mgr.machine_id)
            messagebox.showinfo("Copied", "Machine ID copied to clipboard!")

        ctk.CTkButton(m_row, text="📋 Copy", width=65, height=24, fg_color="#334155", hover_color="#475569", command=copy_mid).pack(side="right")

        # License Key Input Box
        input_card = ctk.CTkFrame(self, corner_radius=12, fg_color="#1E293B", border_width=1, border_color="#334155")
        input_card.pack(fill="x", padx=26, pady=10)

        ctk.CTkLabel(
            input_card,
            text="Enter License Key:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#F8FAFC",
        ).pack(anchor="w", padx=16, pady=(12, 4))

        self.key_var = ctk.StringVar()

        self.entry_key = ctk.CTkEntry(
            input_card,
            textvariable=self.key_var,
            placeholder_text="DXVP-XXXX-XXXX-XXXX-XXXX",
            height=40,
            corner_radius=8,
            border_width=1,
            border_color="#475569",
            fg_color="#0F172A",
            text_color="#F8FAFC",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
        )
        self.entry_key.pack(fill="x", padx=16, pady=(0, 10))

        def paste_key():
            try:
                clip = self.clipboard_get().strip()
                if clip:
                    self.key_var.set(clip)
            except Exception:
                pass

        btn_grid = ctk.CTkFrame(input_card, fg_color="transparent")
        btn_grid.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkButton(btn_grid, text="📋 Paste Key", width=95, height=32, fg_color="#334155", hover_color="#475569", command=paste_key).pack(side="left")

        ctk.CTkButton(
            btn_grid,
            text="⚡ Activate License",
            height=34,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_activate,
        ).pack(side="right", fill="x", expand=True, padx=(8, 0))

        # Bottom Actions (Buy License / Close)
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=26, pady=(10, 20))

        ctk.CTkButton(
            footer,
            text="🛒 View Pricing & Buy License",
            height=36,
            fg_color="#F97316",
            hover_color="#EA580C",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._open_pricing_modal,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            footer,
            text="Close",
            width=90,
            height=36,
            fg_color="#334155",
            hover_color="#475569",
            command=self.destroy,
        ).pack(side="right")

    def _on_activate(self) -> None:
        raw_key = self.key_var.get().strip().upper()
        if not raw_key:
            messagebox.showwarning("Enter Key", "Please enter a valid license key.")
            return

        success, msg = license_mgr.activate_key(raw_key)
        if success:
            messagebox.showinfo("Activated! 🎉", msg)
            if self.on_status_changed:
                self.on_status_changed()
            self.destroy()
        else:
            messagebox.showerror("Activation Failed", msg)

    def _open_pricing_modal(self) -> None:
        self.destroy()
        from ui.pricing_modal import PricingModal
        PricingModal(self.master)
