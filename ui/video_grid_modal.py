from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable
import customtkinter as ctk

from app.playlist import get_remote_image

_POOL = ThreadPoolExecutor(max_workers=6)


class VideoCardWidget(ctk.CTkFrame):
    def __init__(
        self,
        parent: ctk.CTkFrame,
        video: dict,
        on_toggle: Callable[[dict, bool], None],
        initial_selected: bool = True,
    ) -> None:
        super().__init__(
            parent,
            corner_radius=8,
            fg_color="#1E293B",
            border_width=1,
            border_color="#334155",
            width=190,
            height=165,
        )
        self.pack_propagate(False)
        self.video = video
        self.on_toggle = on_toggle
        self.selected = initial_selected

        # Thumbnail Container
        self.thumb_frame = ctk.CTkFrame(self, corner_radius=6, fg_color="#0F172A", height=105)
        self.thumb_frame.pack(fill="x", padx=6, pady=(6, 4))
        self.thumb_frame.pack_propagate(False)

        is_short = video.get("media_type") == "short" or "/shorts/" in str(video.get("url", ""))
        self.thumb_label = ctk.CTkLabel(
            self.thumb_frame,
            text="⚡" if is_short else "🎬",
            font=ctk.CTkFont(size=20),
            text_color="#64748B",
        )
        self.thumb_label.place(relx=0.5, rely=0.5, anchor="center")

        # Top-left Type badge for Shorts
        if is_short:
            badge = ctk.CTkLabel(
                self.thumb_frame,
                text="⚡ Short",
                font=ctk.CTkFont(size=9, weight="bold"),
                text_color="#F8FAFC",
                fg_color="#DC2626",
                corner_radius=4,
                padx=5,
                pady=1,
            )
            badge.place(relx=0.06, rely=0.08, anchor="nw")

        # Top-right checkbox
        self.check_var = ctk.BooleanVar(value=initial_selected)
        self.checkbox = ctk.CTkCheckBox(
            self.thumb_frame,
            text="",
            variable=self.check_var,
            width=20,
            height=20,
            checkbox_width=20,
            checkbox_height=20,
            corner_radius=4,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            border_color="#94A3B8",
            command=self._handle_check_change,
        )
        self.checkbox.place(relx=0.92, rely=0.08, anchor="ne")

        # Title Label
        title_text = video.get("title") or "Untitled Video"
        if len(title_text) > 42:
            title_text = title_text[:39] + "..."
        self.title_label = ctk.CTkLabel(
            self,
            text=title_text,
            font=ctk.CTkFont(size=11),
            text_color="#F8FAFC",
            wraplength=175,
            justify="left",
            anchor="nw",
        )
        self.title_label.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        # Clicking thumbnail or label toggles selection
        self.thumb_label.bind("<Button-1>", lambda _: self.toggle())
        self.thumb_frame.bind("<Button-1>", lambda _: self.toggle())
        self.title_label.bind("<Button-1>", lambda _: self.toggle())
        self.bind("<Button-1>", lambda _: self.toggle())

        self._load_thumbnail(video.get("thumbnail") or video.get("thumbnail_url"))

    def toggle(self) -> None:
        self.selected = not self.selected
        self.check_var.set(self.selected)
        self._update_border()
        self.on_toggle(self.video, self.selected)

    def _handle_check_change(self) -> None:
        self.selected = self.check_var.get()
        self._update_border()
        self.on_toggle(self.video, self.selected)

    def set_selected(self, val: bool) -> None:
        self.selected = val
        self.check_var.set(val)
        self._update_border()

    def _update_border(self) -> None:
        if self.selected:
            self.configure(border_color="#3B82F6", fg_color="#1E2B45")
        else:
            self.configure(border_color="#334155", fg_color="#182234")

    def _load_thumbnail(self, thumb_url: str | None) -> None:
        if not thumb_url:
            return

        def _worker() -> None:
            pil_img = get_remote_image(thumb_url, size=(180, 100))
            if pil_img:
                try:
                    ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(180, 100))
                    self.after(0, lambda: self._apply_image(ctk_img))
                except Exception:
                    pass

        _POOL.submit(_worker)

    def _apply_image(self, ctk_img: ctk.CTkImage) -> None:
        if self.winfo_exists() and self.thumb_label.winfo_exists():
            self.thumb_label.configure(image=ctk_img, text="")


class VideoGridModal(ctk.CTkToplevel):
    def __init__(
        self,
        parent: ctk.CTk,
        title: str,
        videos: list[dict],
        on_download_selected: Callable[[list[dict]], None],
    ) -> None:
        super().__init__(parent)
        self.parent_app = parent
        self.videos = videos
        self.on_download_selected = on_download_selected
        self.selected_map: dict[str, bool] = {v.get("url", str(i)): True for i, v in enumerate(videos)}
        self.cards: list[VideoCardWidget] = []

        self.videos_regular = [v for v in self.videos if v.get("media_type") != "short" and "/shorts/" not in str(v.get("url", ""))]
        self.videos_shorts = [v for v in self.videos if v.get("media_type") == "short" or "/shorts/" in str(v.get("url", ""))]
        self.current_filter = "All"

        self.title(f"{title} - {len(videos)} Items")
        self.geometry("900x660")
        self.minsize(720, 500)
        self.configure(fg_color="#0F172A")
        self.transient(parent)
        self.grab_set()

        # Top Bar
        top_bar = ctk.CTkFrame(self, height=54, fg_color="#1E293B", corner_radius=0)
        top_bar.pack(fill="x", side="top")
        top_bar.pack_propagate(False)

        ctk.CTkLabel(
            top_bar,
            text=f"📁 {title}",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#F8FAFC",
        ).pack(side="left", padx=(16, 10))

        self.count_badge = ctk.CTkLabel(
            top_bar,
            text=f"{len(videos)} Items",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38BDF8",
            fg_color="#0F2440",
            corner_radius=6,
            padx=8,
            pady=2,
        )
        self.count_badge.pack(side="left", padx=(0, 10))

        # Filter Tabs: All / Videos / Shorts
        if self.videos_shorts and self.videos_regular:
            self.filter_values = [
                f"All ({len(self.videos)})",
                f"🎬 Videos ({len(self.videos_regular)})",
                f"⚡ Shorts ({len(self.videos_shorts)})",
            ]
            self.filter_seg = ctk.CTkSegmentedButton(
                top_bar,
                values=self.filter_values,
                height=28,
                selected_color="#2563EB",
                selected_hover_color="#1D4ED8",
                unselected_color="#334155",
                unselected_hover_color="#475569",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=self._on_filter_changed,
            )
            self.filter_seg.set(self.filter_values[0])
            self.filter_seg.pack(side="left", padx=(4, 10))

        # Select All Checkbox
        self.select_all_var = ctk.BooleanVar(value=True)
        self.select_all_cb = ctk.CTkCheckBox(
            top_bar,
            text="Select All",
            variable=self.select_all_var,
            font=ctk.CTkFont(size=12),
            text_color="#F8FAFC",
            fg_color="#2563EB",
            command=self._toggle_select_all,
        )
        self.select_all_cb.pack(side="right", padx=20)

        # Bottom Bar
        bottom_bar = ctk.CTkFrame(self, height=60, fg_color="#1E293B", corner_radius=0)
        bottom_bar.pack(fill="x", side="bottom")
        bottom_bar.pack_propagate(False)

        self.status_lbl = ctk.CTkLabel(
            bottom_bar,
            text=f"Selected: {len(videos)} / {len(videos)}",
            font=ctk.CTkFont(size=13),
            text_color="#94A3B8",
        )
        self.status_lbl.pack(side="left", padx=20)

        ctk.CTkButton(
            bottom_bar,
            text="Cancel",
            width=100,
            height=36,
            fg_color="#334155",
            hover_color="#475569",
            text_color="#F8FAFC",
            command=self.destroy,
        ).pack(side="right", padx=(8, 20))

        self.dl_btn = ctk.CTkButton(
            bottom_bar,
            text=f"Download ({len(videos)}) ⬇",
            width=160,
            height=36,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            font=ctk.CTkFont(weight="bold"),
            command=self._download_now,
        )
        self.dl_btn.pack(side="right")

        # Scrollable Cards Grid
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=16, pady=12)

        self._populate_cards()

    def _get_active_videos(self) -> list[dict]:
        if "Shorts" in self.current_filter:
            return self.videos_shorts
        elif "Videos" in self.current_filter:
            return self.videos_regular
        return self.videos

    def _on_filter_changed(self, value: str) -> None:
        self.current_filter = value
        self._populate_cards()
        self._refresh_selection_state()

    def _populate_cards(self) -> None:
        for widget in self.scroll.winfo_children():
            widget.destroy()
        self.cards.clear()

        active_list = self._get_active_videos()
        columns = 4
        for col in range(columns):
            self.scroll.grid_columnconfigure(col, weight=1, uniform="card")

        for idx, video in enumerate(active_list):
            row = idx // columns
            col = idx % columns
            key = video.get("url") or str(id(video))
            is_sel = self.selected_map.get(key, True)
            card = VideoCardWidget(
                self.scroll,
                video=video,
                on_toggle=self._on_card_toggle,
                initial_selected=is_sel,
            )
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            self.cards.append(card)

    def _on_card_toggle(self, video: dict, is_selected: bool) -> None:
        key = video.get("url") or str(id(video))
        self.selected_map[key] = is_selected
        self._refresh_selection_state()

    def _toggle_select_all(self) -> None:
        target = self.select_all_var.get()
        active_list = self._get_active_videos()
        for v in active_list:
            key = v.get("url") or str(id(v))
            self.selected_map[key] = target
        for card in self.cards:
            card.set_selected(target)
        self._refresh_selection_state()

    def _refresh_selection_state(self) -> None:
        active_list = self._get_active_videos()
        active_selected = sum(1 for v in active_list if self.selected_map.get(v.get("url") or str(id(v)), False))
        total_active = len(active_list)
        total_all_selected = sum(1 for v in self.videos if self.selected_map.get(v.get("url") or str(id(v)), False))

        self.status_lbl.configure(text=f"Selected: {total_all_selected} / {len(self.videos)} (Tab: {active_selected}/{total_active})")
        self.dl_btn.configure(text=f"Download ({total_all_selected}) ⬇", state="normal" if total_all_selected > 0 else "disabled")
        self.count_badge.configure(text=f"{total_active} Items")
        self.select_all_var.set(active_selected == total_active and total_active > 0)

    def _download_now(self) -> None:
        chosen = [v for v in self.videos if self.selected_map.get(v.get("url") or str(id(v)), False)]
        if chosen:
            self.on_download_selected(chosen)
        self.destroy()
