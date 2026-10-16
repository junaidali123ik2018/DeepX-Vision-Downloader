import ctypes
import sys
import customtkinter as ctk

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

from app.settings import SettingsStore
from ui.main_window import DeepXVisionApp, HQVideoDownloaderApp

# Ensure Windows Taskbar groups under DeepX Vision instead of python.exe
if sys.platform.startswith("win"):
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DeepXVision.VideoDownloader.Pro.2")
    except Exception:
        pass


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--browser":
        url = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else "https://www.youtube.com"
        ipc_port = None
        auto_close = None
        if "--port" in sys.argv:
            try:
                p_idx = sys.argv.index("--port")
                ipc_port = int(sys.argv[p_idx + 1])
            except Exception:
                pass
        if "--test-mode" in sys.argv:
            from ui.browser_window import launch_browser
            launch_browser(initial_url=url, ipc_port=ipc_port, auto_close_after=4.0)
            return

        settings = SettingsStore().load()
        from ui.browser_window import launch_isolated_browser
        launch_isolated_browser(url, browser_name=getattr(settings, "preferred_browser", "Google Chrome"), ipc_port=ipc_port)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--ig-extract":
        user = sys.argv[2] if len(sys.argv) > 2 else ""
        from ui.browser_window import extract_instagram_profile_headless
        extract_instagram_profile_headless(user)
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--media-extract":
        url = sys.argv[2] if len(sys.argv) > 2 else ""
        from ui.browser_window import extract_post_media_headless
        extract_post_media_headless(url)
        return

    settings = SettingsStore().load()
    app = HQVideoDownloaderApp(settings)
    if "--no-splash" in sys.argv:
        app.mainloop()
    else:
        app.withdraw()
        from ui.splash_screen import SplashScreen
        SplashScreen(on_complete=app.deiconify)
        app.mainloop()


if __name__ == "__main__":
    main()
