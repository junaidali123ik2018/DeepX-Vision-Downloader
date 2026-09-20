from __future__ import annotations

import re
import threading
import time
from typing import Callable, Optional
import tkinter as tk

MEDIA_URL_REGEX = re.compile(
    r"https?://(?:www\.)?(?:youtu\.be/|youtube\.com/|tiktok\.com/|instagram\.com/|"
    r"facebook\.com/|fb\.watch/|twitter\.com/|x\.com/|vimeo\.com/|soundcloud\.com/|"
    r"reddit\.com/|pinterest\.com/|pin\.it/)[^\s]+",
    re.IGNORECASE,
)


class ClipboardMonitor:
    def __init__(
        self,
        root: tk.Tk,
        on_url_detected: Callable[[str], None],
        poll_interval: float = 1.0,
    ) -> None:
        self.root = root
        self.on_url_detected = on_url_detected
        self.poll_interval = poll_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_url: str = ""
        self.enabled: bool = True

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            time.sleep(self.poll_interval)
            if not self.enabled:
                continue

            try:
                # Safely read clipboard via root
                clip_text = self.root.clipboard_get().strip()
            except Exception:
                continue

            if not clip_text or clip_text == self._last_url:
                continue

            # Check if it matches media URLs
            match = MEDIA_URL_REGEX.search(clip_text)
            if match:
                url = match.group(0)
                if url != self._last_url:
                    self._last_url = url
                    # Schedule callback in main thread
                    try:
                        self.root.after(0, lambda u=url: self.on_url_detected(u))
                    except Exception:
                        pass
