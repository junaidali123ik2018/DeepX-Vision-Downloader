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


def check_or_focus_existing_instance() -> bool:
    """
    Ensures only a single instance of DeepX Vision Downloader runs at a time.
    If an instance is already running:
      1. Pings IPC server on port 18932/18933 to bring existing window to front.
      2. Uses Win32 Mutex and ShowWindow to restore and focus the running app.
      3. Returns False so this second process exits cleanly.
    """
    if sys.platform != "win32":
        return True

    import urllib.request

    # 1. Try sending /focus to active IPC server
    for port in (18932, 18933, 18934, 18935):
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/focus",
                data=b'{"action":"focus_main"}',
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=0.6) as resp:
                if resp.getcode() == 200:
                    return False
        except Exception:
            pass

    # 2. Windows Named Mutex Check
    kernel32 = ctypes.windll.kernel32
    CreateMutexW = kernel32.CreateMutexW
    GetLastError = kernel32.GetLastError
    ERROR_ALREADY_EXISTS = 183
    MUTEX_NAME = "Global\\DeepX_Vision_Downloader_Pro_Single_Instance_Mutex"

    mutex = CreateMutexW(None, True, MUTEX_NAME)
    if GetLastError() == ERROR_ALREADY_EXISTS:
        # Existing instance running - restore and bring to foreground
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "DeepX Vision Downloader")
        if hwnd:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        return False

    globals()["_SINGLE_INSTANCE_MUTEX"] = mutex
    return True


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--browser":
        url = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else "https://www.youtube.com"
        ipc_port = None
        if "--port" in sys.argv:
            try:
                p_idx = sys.argv.index("--port")
                ipc_port = int(sys.argv[p_idx + 1])
            except Exception:
                pass
        if "--ipc-port" in sys.argv:
            try:
                p_idx = sys.argv.index("--ipc-port")
                ipc_port = int(sys.argv[p_idx + 1])
            except Exception:
                pass
        if "--test-mode" in sys.argv:
            from ui.browser_window import launch_browser
            launch_browser(initial_url=url, ipc_port=ipc_port, auto_close_after=4.0)
            return

        target_browser = None
        if "--engine" in sys.argv:
            try:
                e_idx = sys.argv.index("--engine")
                target_browser = sys.argv[e_idx + 1]
            except Exception:
                pass

        if not target_browser:
            settings = SettingsStore().load()
            target_browser = getattr(settings, "preferred_browser", "Built-in Browser (WebView)")

        if "built-in" in target_browser.lower() or "webview" in target_browser.lower():
            from ui.browser_window import launch_browser
            launch_browser(initial_url=url, ipc_port=ipc_port)
            return

        from ui.browser_window import launch_isolated_browser
        launch_isolated_browser(url, browser_name=target_browser, ipc_port=ipc_port)
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

    # Single Instance Guard: If software is already running, bring existing window to front and exit
    if not check_or_focus_existing_instance():
        print("[DeepX Vision] Software is already running. Brought existing window to front.")
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
