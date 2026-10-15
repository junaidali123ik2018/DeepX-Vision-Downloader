from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable
import customtkinter as ctk

from app.playlist import get_remote_image, reindex_video_entries

_POOL = ThreadPoolExecutor(max_workers=4)
PAGE_SIZE = 24


class VideoCardWidget(ctk.CTkFrame):
    def __init__(
        self,
        parent: ctk.CTkFrame,
        video: dict,
        on_toggle: Callable[[dict, bool], None],
        initial_selected: bool = True,
        index: int | None = None,
    ) -> None:
        super().__init__(
            parent,
            corner_radius=8,
            fg_color="#1E2B45" if initial_selected else "#182234",
            border_width=1,
            border_color="#3B82F6" if initial_selected else "#334155",
            width=185,
            height=160,
        )
        self.pack_propagate(False)
        self.video = video
        self.on_toggle = on_toggle
        self.selected = initial_selected

        # Thumbnail Container
        self.thumb_frame = ctk.CTkFrame(self, corner_radius=6, fg_color="#0B132B", height=100)
        self.thumb_frame.pack(fill="x", padx=6, pady=(6, 4))
        self.thumb_frame.pack_propagate(False)

        is_short = video.get("media_type") == "short" or "/shorts/" in str(video.get("url", ""))
        self.thumb_label = ctk.CTkLabel(
            self.thumb_frame,
            text="⚡ Short" if is_short else "▶ Video",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#64748B",
        )
        self.thumb_label.place(relx=0.5, rely=0.5, anchor="center")

        # Top-left index badge (e.g. #01, #02...)
        if index is not None:
            self.index_badge = ctk.CTkLabel(
                self.thumb_frame,
                text=f"#{index:02d}",
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color="#0F2440",
                text_color="#38BDF8",
                corner_radius=4,
                padx=5,
                pady=1,
            )
            self.index_badge.place(relx=0.08, rely=0.08, anchor="nw")

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
        raw_title = video.get("title") or "Untitled Video"
        clean_title = re.sub(r"^\d{1,4}[\.\s_-]+\s*", "", raw_title)
        if index is not None:
            title_text = f"{index:02d}. {clean_title or raw_title}"
        else:
            title_text = raw_title
        if len(title_text) > 42:
            title_text = title_text[:39] + "..."
        self.title_label = ctk.CTkLabel(
            self,
            text=title_text,
            font=ctk.CTkFont(size=11),
            text_color="#F8FAFC",
            wraplength=170,
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
            pil_img = get_remote_image(thumb_url, size=(180, 95))
            if pil_img:
                try:
                    ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(180, 95))
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
        on_download_selected: Callable,
        initial_quality: str = "Best Available",
        order: str = "latest_first",
    ) -> None:
        super().__init__(parent)
        self.parent_app = parent
        self.title_text = title
        self.videos = list(videos)
        self.current_order = order
        reindex_video_entries(self.videos)
        self.on_download_selected = on_download_selected
        self.selected_map: dict[str, bool] = {v.get("url", str(i)): True for i, v in enumerate(self.videos)}
        self.cards: list[VideoCardWidget] = []
        self.current_page = 0

        self.videos_regular = [v for v in self.videos if v.get("media_type") != "short" and "/shorts/" not in str(v.get("url", ""))]
        self.videos_shorts = [v for v in self.videos if v.get("media_type") == "short" or "/shorts/" in str(v.get("url", ""))]
        self.current_filter = "All"

        self.title(f"{title} - {len(videos)} Items")

        # Responsive Geometry (Never taller than screen height, fits all monitors)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        target_w = min(880, max(720, int(sw * 0.85)))
        target_h = min(540, max(440, int(sh * 0.72)))
        x = max(10, (sw - target_w) // 2)
        y = max(10, (sh - target_h) // 2 - 25)
        self.geometry(f"{target_w}x{target_h}+{x}+{y}")
        self.minsize(min(680, target_w), min(420, target_h))
        self.configure(fg_color="#0F172A")
        self.transient(parent)
        self.grab_set()

        # 1. Top Bar (Channel / Playlist Info & Filters)
        top_bar = ctk.CTkFrame(self, height=50, fg_color="#1E293B", corner_radius=0)
        top_bar.pack(fill="x", side="top")
        top_bar.pack_propagate(False)

        clean_header = f"Videos: {title}" if len(title) < 40 else f"Videos: {title[:37]}..."
        ctk.CTkLabel(
            top_bar,
            text=clean_header,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#F8FAFC",
        ).pack(side="left", padx=(16, 8))

        self.count_badge = ctk.CTkLabel(
            top_bar,
            text=f"{len(videos)} Total",
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
                f"Videos ({len(self.videos_regular)})",
                f"Shorts ({len(self.videos_shorts)})",
            ]
            self.filter_seg = ctk.CTkSegmentedButton(
                top_bar,
                values=self.filter_values,
                height=26,
                selected_color="#2563EB",
                selected_hover_color="#1D4ED8",
                unselected_color="#334155",
                unselected_hover_color="#475569",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=self._on_filter_changed,
            )
            self.filter_seg.set(self.filter_values[0])
            self.filter_seg.pack(side="left", padx=(4, 10))

        # Order / Numbering dropdown on top-right
        order_default_val = "Latest to Oldest (01=Latest)" if order == "latest_first" else "Oldest to Latest (01=Oldest)"
        self.order_var = ctk.StringVar(value=order_default_val)
        self.order_menu = ctk.CTkOptionMenu(
            top_bar,
            values=["Latest to Oldest (01=Latest)", "Oldest to Latest (01=Oldest)"],
            variable=self.order_var,
            width=205,
            height=28,
            fg_color="#334155",
            button_color="#2563EB",
            text_color="#F8FAFC",
            font=ctk.CTkFont(size=11),
            command=self._on_order_changed,
        )
        self.order_menu.pack(side="right", padx=(4, 16))

        ctk.CTkLabel(
            top_bar,
            text="Order:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94A3B8",
        ).pack(side="right", padx=(8, 2))

        # 2. Pagination & Global Selection Bar
        self.page_bar = ctk.CTkFrame(self, height=42, fg_color="#182234", corner_radius=0)
        self.page_bar.pack(fill="x", side="top")
        self.page_bar.pack_propagate(False)

        self.prev_btn = ctk.CTkButton(
            self.page_bar,
            text="◀ Prev",
            width=70,
            height=28,
            fg_color="#334155",
            hover_color="#475569",
            text_color="#F8FAFC",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._prev_page,
        )
        self.prev_btn.pack(side="left", padx=(16, 8), pady=7)

        self.page_lbl = ctk.CTkLabel(
            self.page_bar,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94A3B8",
        )
        self.page_lbl.pack(side="left", padx=6, pady=7)

        self.next_btn = ctk.CTkButton(
            self.page_bar,
            text="Next ▶",
            width=70,
            height=28,
            fg_color="#334155",
            hover_color="#475569",
            text_color="#F8FAFC",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._next_page,
        )
        self.next_btn.pack(side="left", padx=8, pady=7)

        self.select_all_btn = ctk.CTkButton(
            self.page_bar,
            text=f"Select All ({len(videos)})",
            width=140,
            height=28,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._select_all_global,
        )
        self.select_all_btn.pack(side="right", padx=(6, 16), pady=7)

        self.deselect_all_btn = ctk.CTkButton(
            self.page_bar,
            text="Deselect All",
            width=90,
            height=28,
            fg_color="#334155",
            hover_color="#475569",
            text_color="#F8FAFC",
            font=ctk.CTkFont(size=11),
            command=self._deselect_all_global,
        )
        self.deselect_all_btn.pack(side="right", padx=(6, 0), pady=7)

        # 3. Bottom Bar (Always pinned to bottom)
        bottom_bar = ctk.CTkFrame(self, height=56, fg_color="#1E293B", corner_radius=0)
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
            width=85,
            height=34,
            fg_color="#334155",
            hover_color="#475569",
            text_color="#F8FAFC",
            command=self.destroy,
        ).pack(side="right", padx=(8, 20))

        self.dl_btn = ctk.CTkButton(
            bottom_bar,
            text=f"Download ({len(videos)}) ⬇",
            width=165,
            height=34,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            font=ctk.CTkFont(weight="bold"),
            command=self._download_now,
        )
        self.dl_btn.pack(side="right", padx=(6, 0))

        # Quality Selection in Bottom Bar
        QUALITY_CHOICES = [
            "Best Available",
            "8K (4320p)",
            "4K (2160p)",
            "2K / 1440p",
            "1080p (Full HD)",
            "720p (HD)",
            "480p (SD)",
            "Audio MP3",
            "Audio WAV",
        ]
        self.quality_var = ctk.StringVar(value=initial_quality if initial_quality in QUALITY_CHOICES else "Best Available")
        self.quality_menu = ctk.CTkOptionMenu(
            bottom_bar,
            values=QUALITY_CHOICES,
            variable=self.quality_var,
            width=135,
            height=32,
            fg_color="#334155",
            button_color="#2563EB",
            text_color="#F8FAFC",
            font=ctk.CTkFont(size=11),
        )
        self.quality_menu.pack(side="right", padx=(0, 6))

        ctk.CTkLabel(
            bottom_bar,
            text="Quality:",
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8",
        ).pack(side="right", padx=(0, 4))

        # 4. Scrollable Cards Grid
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=12, pady=6)

        self._populate_cards()

    def _get_active_videos(self) -> list[dict]:
        if "Shorts" in self.current_filter:
            return self.videos_shorts
        elif "Videos" in self.current_filter:
            return self.videos_regular
        return self.videos

    def _on_filter_changed(self, value: str) -> None:
        self.current_filter = value
        self.current_page = 0
        self._populate_cards()

    def _on_order_changed(self, value: str) -> None:
        new_order = "latest_first" if "Latest" in value else "oldest_first"
        if new_order != self.current_order:
            self.current_order = new_order
            self.videos.reverse()
            reindex_video_entries(self.videos)
            self.videos_regular = [v for v in self.videos if v.get("media_type") != "short" and "/shorts/" not in str(v.get("url", ""))]
            self.videos_shorts = [v for v in self.videos if v.get("media_type") == "short" or "/shorts/" in str(v.get("url", ""))]
            self.current_page = 0
            self._populate_cards()

    def _populate_cards(self) -> None:
        for widget in self.scroll.winfo_children():
            widget.destroy()
        self.cards.clear()

        active_list = self._get_active_videos()
        total_items = len(active_list)
        total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)
        self.current_page = max(0, min(self.current_page, total_pages - 1))

        start = self.current_page * PAGE_SIZE
        end = min(total_items, start + PAGE_SIZE)
        page_videos = active_list[start:end]

        columns = 4
        for col in range(columns):
            self.scroll.grid_columnconfigure(col, weight=1, uniform="card")

        for idx, video in enumerate(page_videos):
            row = idx // columns
            col = idx % columns
            key = video.get("url") or str(id(video))
            is_sel = self.selected_map.get(key, True)
            v_num = video.get("index", start + idx + 1)
            card = VideoCardWidget(
                self.scroll,
                video=video,
                on_toggle=self._on_card_toggle,
                initial_selected=is_sel,
                index=v_num,
            )
            card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
            self.cards.append(card)

        # Update Navigation & Labels
        self.prev_btn.configure(state="normal" if self.current_page > 0 else "disabled")
        self.next_btn.configure(state="normal" if self.current_page < total_pages - 1 else "disabled")
        if total_items > 0:
            self.page_lbl.configure(text=f"Page {self.current_page + 1} of {total_pages}  ({start + 1}–{end} of {total_items})")
        else:
            self.page_lbl.configure(text="No videos found")

        self._refresh_selection_state()

    def _prev_page(self) -> None:
        if self.current_page > 0:
            self.current_page -= 1
            self._populate_cards()
            try:
                self.scroll._parent_canvas.yview_moveto(0.0)
            except Exception:
                pass

    def _next_page(self) -> None:
        active_list = self._get_active_videos()
        total_pages = max(1, (len(active_list) + PAGE_SIZE - 1) // PAGE_SIZE)
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self._populate_cards()
            try:
                self.scroll._parent_canvas.yview_moveto(0.0)
            except Exception:
                pass

    def _on_card_toggle(self, video: dict, is_selected: bool) -> None:
        key = video.get("url") or str(id(video))
        self.selected_map[key] = is_selected
        self._refresh_selection_state()

    def _select_all_global(self) -> None:
        active_list = self._get_active_videos()
        for v in active_list:
            key = v.get("url") or str(id(v))
            self.selected_map[key] = True
        for card in self.cards:
            card.set_selected(True)
        self._refresh_selection_state()

    def _deselect_all_global(self) -> None:
        active_list = self._get_active_videos()
        for v in active_list:
            key = v.get("url") or str(id(v))
            self.selected_map[key] = False
        for card in self.cards:
            card.set_selected(False)
        self._refresh_selection_state()

    def _refresh_selection_state(self) -> None:
        active_list = self._get_active_videos()
        total_all_selected = sum(1 for v in self.videos if self.selected_map.get(v.get("url") or str(id(v)), False))

        self.status_lbl.configure(text=f"Selected: {total_all_selected} / {len(self.videos)}")
        self.dl_btn.configure(
            text=f"Download ({total_all_selected}) ⬇",
            state="normal" if total_all_selected > 0 else "disabled",
        )
        self.count_badge.configure(text=f"{len(active_list)} Total")
        self.select_all_btn.configure(text=f"Select All ({len(active_list)})")

    def _download_now(self) -> None:
        chosen = [v for v in self.videos if self.selected_map.get(v.get("url") or str(id(v)), False)]
        cb = self.on_download_selected
        q = self.quality_var.get() if hasattr(self, "quality_var") else "Best Available"
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        if chosen and cb:
            reindex_video_entries(chosen)
            try:
                cb(chosen, q)
            except TypeError:
                cb(chosen)
