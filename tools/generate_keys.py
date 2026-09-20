from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.license import TIER_NAMES, generate_license_key


def generate_batch(tier: str, hwid: str, count: int, client: str = "") -> list[str]:
    keys = []
    for _ in range(count):
        k = generate_license_key(tier=tier, target_hwid=hwid)
        keys.append(k)

    # Save to generated_licenses.txt
    out_file = Path(__file__).resolve().parent / "generated_licenses.txt"
    with open(out_file, "a", encoding="utf-8") as f:
        f.write(f"\n# --- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} --- #\n")
        f.write(f"# Tier: {TIER_NAMES.get(tier, tier)} | Target HWID: {hwid} | Client: {client or 'General'}\n")
        for k in keys:
            f.write(f"{k}\n")

    return keys


def run_gui():
    import customtkinter as ctk
    from tkinter import messagebox

    ctk.set_appearance_mode("Dark")
    app = ctk.CTk()
    app.title("DeepX Vision Pro - Official License Generator")
    app.geometry("640x560")
    app.resizable(False, False)
    app.configure(fg_color="#0F172A")

    # Header
    head = ctk.CTkFrame(app, fg_color="transparent")
    head.pack(fill="x", padx=24, pady=(20, 10))
    ctk.CTkLabel(head, text="👑 DeepX Vision Pro", font=ctk.CTkFont(size=20, weight="bold"), text_color="#38BDF8").pack(anchor="w")
    ctk.CTkLabel(head, text="Official Commercial License Key Generator by Junaid Ali", font=ctk.CTkFont(size=12), text_color="#94A3B8").pack(anchor="w")

    # Card
    card = ctk.CTkFrame(app, corner_radius=12, fg_color="#1E293B", border_width=1, border_color="#334155")
    card.pack(fill="x", padx=24, pady=10)

    # Row 1: License Tier
    r1 = ctk.CTkFrame(card, fg_color="transparent")
    r1.pack(fill="x", padx=16, pady=(14, 8))
    ctk.CTkLabel(r1, text="License Tier:", width=120, anchor="w", font=ctk.CTkFont(weight="bold")).pack(side="left")
    tier_map = {
        "1 Month Pro (30 Days)": "1M",
        "3 Months Pro (90 Days)": "3M",
        "6 Months Pro (180 Days)": "6M",
        "1 Year Pro (365 Days)": "1Y",
        "Lifetime Pro (1 PC) - $60": "LT",
        "Family Lifetime (5 PCs) - $90": "FAM",
    }
    tier_var = ctk.StringVar(value="Lifetime Pro (1 PC) - $60")
    tier_menu = ctk.CTkOptionMenu(r1, values=list(tier_map.keys()), variable=tier_var, width=280)
    tier_menu.pack(side="left", padx=10)

    # Row 2: Target Hardware ID
    r2 = ctk.CTkFrame(card, fg_color="transparent")
    r2.pack(fill="x", padx=16, pady=8)
    ctk.CTkLabel(r2, text="Target Machine ID:", width=120, anchor="w", font=ctk.CTkFont(weight="bold")).pack(side="left")
    hwid_var = ctk.StringVar(value="ANY")
    hwid_entry = ctk.CTkEntry(r2, textvariable=hwid_var, width=280, placeholder_text="Enter Machine ID or leave ANY")
    hwid_entry.pack(side="left", padx=10)

    # Row 3: Client Name & Quantity
    r3 = ctk.CTkFrame(card, fg_color="transparent")
    r3.pack(fill="x", padx=16, pady=8)
    ctk.CTkLabel(r3, text="Client Name:", width=120, anchor="w", font=ctk.CTkFont(weight="bold")).pack(side="left")
    client_var = ctk.StringVar(value="")
    ctk.CTkEntry(r3, textvariable=client_var, width=160, placeholder_text="Optional").pack(side="left", padx=(10, 16))
    
    ctk.CTkLabel(r3, text="Qty:").pack(side="left")
    qty_var = ctk.StringVar(value="1")
    ctk.CTkOptionMenu(r3, values=["1", "5", "10", "20", "50"], variable=qty_var, width=70).pack(side="left", padx=8)

    # Result Box
    res_frame = ctk.CTkFrame(app, fg_color="transparent")
    res_frame.pack(fill="both", expand=True, padx=24, pady=10)

    res_box = ctk.CTkTextbox(res_frame, height=130, font=ctk.CTkFont(family="Consolas", size=12))
    res_box.pack(fill="both", expand=True, pady=(0, 10))

    def on_generate():
        sel_tier = tier_map[tier_var.get()]
        raw_hwid = hwid_var.get().strip().upper() or "ANY"
        count = int(qty_var.get())
        client = client_var.get().strip()

        keys = generate_batch(tier=sel_tier, hwid=raw_hwid, count=count, client=client)
        res_box.delete("1.0", "end")
        for k in keys:
            res_box.insert("end", f"{k}\n")
        messagebox.showinfo("Success", f"{count} key(s) generated and saved to tools/generated_licenses.txt!")

    def on_copy():
        txt = res_box.get("1.0", "end").strip()
        if txt:
            app.clipboard_clear()
            app.clipboard_append(txt)
            messagebox.showinfo("Copied", "Keys copied to clipboard!")

    btn_row = ctk.CTkFrame(app, fg_color="transparent")
    btn_row.pack(fill="x", padx=24, pady=(0, 20))

    ctk.CTkButton(btn_row, text="⚡ Generate License Keys", height=38, fg_color="#2563EB", hover_color="#1D4ED8", font=ctk.CTkFont(size=13, weight="bold"), command=on_generate).pack(side="left", fill="x", expand=True, padx=(0, 8))
    ctk.CTkButton(btn_row, text="📋 Copy All", width=120, height=38, fg_color="#334155", hover_color="#475569", command=on_copy).pack(side="right")

    app.mainloop()


def main():
    parser = argparse.ArgumentParser(description="DeepX Vision Pro - Official License Generator")
    parser.add_argument("--tier", choices=["1M", "3M", "6M", "1Y", "LT", "FAM"], default="LT", help="License Tier")
    parser.add_argument("--hwid", default="ANY", help="Target Machine ID (e.g. DXV-XXXX-XXXX) or ANY")
    parser.add_argument("--count", type=int, default=1, help="Number of keys to generate")
    parser.add_argument("--client", default="", help="Client name or reference note")
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode instead of GUI")

    args = parser.parse_args()

    if args.cli or len(sys.argv) > 1:
        keys = generate_batch(tier=args.tier, hwid=args.hwid, count=args.count, client=args.client)
        print(f"\nGenerated {len(keys)} {TIER_NAMES.get(args.tier)} License Key(s):")
        for k in keys:
            print(f"  {k}")
        print("\nSaved to tools/generated_licenses.txt")
    else:
        run_gui()


if __name__ == "__main__":
    main()
